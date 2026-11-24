"""Console notifier: prints a framed block to stdout (or any stream)."""

from __future__ import annotations

import sys

from .base import Notifier

RULER = "=" * 68


class ConsoleNotifier(Notifier):
    name = "console"

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout

    def send(self, message):
        self.stream.write("\n" + RULER + "\n")
        self.stream.write(message.as_text() + "\n")
        self.stream.write(RULER + "\n")
        self.stream.flush()
        return []
