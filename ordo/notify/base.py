"""Notifier base types shared by every delivery channel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class NotifyError(RuntimeError):
    """Raised when a channel cannot deliver a message."""


@dataclass
class Message:
    subject: str
    body: str
    task_id: Optional[int] = None
    kind: str = "info"
    urgent: bool = False

    def as_text(self) -> str:
        prefix = "[URGENT] " if self.urgent else ""
        return "%s%s\n%s" % (prefix, self.subject, self.body)


class Notifier:
    """Interface: subclasses implement ``send`` and optionally ``close``."""

    name = "base"

    def send(self, message):  # pragma: no cover - abstract
        raise NotImplementedError

    def close(self):
        pass


class NullNotifier(Notifier):
    """Swallows everything - useful for tests and for disabling delivery."""

    name = "none"

    def send(self, message):
        return []


class RecordingNotifier(Notifier):
    """Keeps messages in memory. Handy for tests and dry runs."""

    name = "recording"

    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return []


class MultiNotifier(Notifier):
    """Fan-out to several channels; fails only when *all* of them fail."""

    name = "multi"

    def __init__(self, children):
        self.children = list(children)
        self.name = ",".join(child.name for child in self.children) or "none"

    def send(self, message):
        errors = []
        for child in self.children:
            try:
                child.send(message)
            except Exception as exc:  # noqa: BLE001
                errors.append((child.name, str(exc)))
        if self.children and len(errors) == len(self.children):
            raise NotifyError("; ".join("%s: %s" % pair for pair in errors))
        return ["%s: %s" % pair for pair in errors]

    def close(self):
        for child in self.children:
            try:
                child.close()
            except Exception:  # noqa: BLE001
                pass
