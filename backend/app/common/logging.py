"""Structured JSON logging (spec §28.6, §35.2). Never log tokens, answers, signed URLs or secrets."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
# "<platform>/<build>" from the app's x-client-platform / x-client-build headers ("-" when absent: builds <= 8).
client_var: contextvars.ContextVar[str] = contextvars.ContextVar("client", default="-")

_REDACT_KEYS = {"authorization", "token", "id_token", "app_check", "purchase_token", "signed_image_url",
                "signed_media_fallback_url_if_needed", "correct_concept_id", "secret", "password",
                "signature", "jws", "x-firebase-appcheck"}
_SAFE_EXTRA = {"match_id", "shard_id", "action", "state_version", "latency_ms", "outcome", "uid_ref",
               "task", "attempt", "path", "method", "status", "task_kind", "round_id", "config_version",
               "has_token", "reason", "token_app"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
            "client": client_var.get(),
        }
        for key in _SAFE_EXTRA:
            if hasattr(record, key):
                payload[key] = redact(getattr(record, key))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
