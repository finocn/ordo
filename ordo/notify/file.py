"""File notifier: appends delivered messages as JSON lines to an outbox.

Useful when Ordo runs from cron/automation and something else (or you)
later reads ``ordo-outbox.jsonl``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Notifier


class FileNotifier(Notifier):
    name = "file"

    def __init__(self, path):
        self.path = Path(path).expanduser()

    def send(self, message):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "subject": message.subject,
            "body": message.body,
            "task_id": message.task_id,
            "kind": message.kind,
            "urgent": message.urgent,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return []
