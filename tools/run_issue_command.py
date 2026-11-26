#!/usr/bin/env python3
"""Run an Ordo CLI command that came from a GitHub issue (IssueOps).

The command text is read from the ``ORDO_ISSUE_COMMAND`` environment variable,
split with :mod:`shlex` (so there is no shell and no injection), and handed to
the normal Ordo CLI. Captured output is printed for the workflow to post back.

The issue title is used as the command, e.g.:

    add "Починить парсер" -d 3d -P 1
    /done 4 -c "готово"
    list --overdue
"""

from __future__ import annotations

import contextlib
import io
import os
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ordo.cli import main as ordo_main  # noqa: E402


def parse_command(raw):
    text = (raw or "").strip()
    if text.startswith("/"):
        text = text[1:].strip()
    if text.lower().startswith("ordo "):
        text = text[5:].strip()
    if not text:
        raise ValueError("empty command")
    return shlex.split(text)


def main(argv=None):
    raw = os.environ.get("ORDO_ISSUE_COMMAND", "")
    try:
        parsed = parse_command(raw)
    except ValueError as exc:
        print("ordo: %s (задайте команду в заголовке issue)" % exc)
        return 2

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = ordo_main(parsed)
    print(buffer.getvalue().rstrip())
    print("\n(exit code: %s)" % code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
