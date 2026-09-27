"""Retire seed questions by key and rebuild the pool manifests.

    python -m tools.content.retire geography_c001 geography_img_001 ...

Runs against the environment configured by ``OLTIVRA_*`` variables (same as ``app.questions.seed``). Missing or
already retired questions are reported and skipped, so the command can be re-run safely.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.common.errors import ApiError
from app.questions.models import QuestionStatus
from app.questions.seed import SEED_LANGUAGES, seed_group_id

ACTOR = "content-retire"


async def retire(container, keys: list[str], reason: str) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"retired": [], "missing": [], "already_retired": [], "failed": []}
    for key in keys:
        group_id = seed_group_id(key)
        group = await container.question_repo.get_group(group_id)
        if group is None:
            report["missing"].append(key)
            continue
        if group["status"] == QuestionStatus.RETIRED:
            report["already_retired"].append(key)
            continue
        try:
            await container.question_repo.transition(group_id, QuestionStatus.RETIRED, ACTOR, reason)
            report["retired"].append(key)
        except ApiError:
            report["failed"].append(key)
    await container.manifest_builder.build_all(list(SEED_LANGUAGES))
    return report


async def _main(keys: list[str]) -> None:
    from app.common.settings import Settings
    from app.container import Container

    container = Container(Settings())
    print(json.dumps(await retire(container, keys, "image questions removed (playtest 2026-09-27)"), indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m tools.content.retire <seed key>...")
    asyncio.run(_main(sys.argv[1:]))
