"""Task dispatch: every task kind maps to one idempotent handler."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.common.tasks import TaskKind

log = logging.getLogger("oltivra.tasks")

Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]
_HANDLERS: dict[TaskKind, Handler] = {}


def task_handler(*kinds: TaskKind) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        for kind in kinds:
            _HANDLERS[kind] = fn
        return fn
    return register


def _load_handlers() -> None:
    # Import modules that register handlers (kept lazy to avoid import cycles).
    import app.tasks.handlers  # noqa: F401


async def dispatch_task(container, body: dict[str, Any]) -> Any:
    _load_handlers()
    try:
        kind = TaskKind(body.get("task_kind"))
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "unknown_task_kind"}) from exc
    handler = _HANDLERS.get(kind)
    if handler is None:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "no_handler"})
    return await handler(container, body)
