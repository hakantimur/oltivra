"""Print the gcloud commands that provision the sharded Cloud Tasks queues for an environment.

Usage: python scripts/provision_queues.py prod europe-west1 > provision.sh
"""

from __future__ import annotations

import sys
from pathlib import Path


def parse(path: Path) -> dict:
    """Minimal parser for infra/cloudtasks.yaml (two-level maps of scalars)."""
    data: dict = {}
    section: dict | None = None
    sub: dict | None = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if indent == 0:
            section = data.setdefault(key, {})
        elif indent == 2 and section is not None:
            if value:
                section[key] = value
            else:
                sub = section.setdefault(key, {})
        elif indent == 4 and sub is not None:
            sub[key] = value
    return data


def main() -> None:
    env, region = sys.argv[1], sys.argv[2]
    config = parse(Path(__file__).resolve().parent.parent / "infra" / "cloudtasks.yaml")
    shards = int(config["shard_counts"][env])
    for family, opts in config["families"].items():
        for i in range(shards):
            print(
                f"gcloud tasks queues create {family}-{i:02d} --location={region}"
                f" --max-dispatches-per-second={opts['max_dispatches_per_second']}"
                f" --max-concurrent-dispatches={opts['max_concurrent_dispatches']}"
                f" --max-attempts={opts['max_attempts']}"
                f" --min-backoff={opts['min_backoff']} --max-backoff={opts['max_backoff']}"
            )


if __name__ == "__main__":
    main()
