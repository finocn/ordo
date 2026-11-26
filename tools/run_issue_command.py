#!/usr/bin/env python3
"""Run an Ordo CLI command that came from a GitHub issue (IssueOps).

The command text is read from the ``ORDO_ISSUE_COMMAND`` environment variable,
split with :mod:`shlex` (so there is no shell and no injection), and handed to
the normal Ordo CLI. Captured output is printed for the workflow to post back.

The issue title is used as the command, e.g.:

    add "Починить парсер" -d 3d -P 1
    /done 4 -c "готово"
    list --overdue

A title that is not a command (a normal bug report) no longer crashes the run:
it prints a short help so the workflow can still save the state branch.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ordo.command import handle_text, split_command  # noqa: E402


def parse_command(raw):
    """Split a command string into argv (kept for backwards compatibility)."""
    return split_command(raw)


def main(argv=None):
    raw = os.environ.get("ORDO_ISSUE_COMMAND", "")
    if not raw.strip():
        print('ordo: задайте команду в заголовке issue, например: add "Задача" -d 3d')
        return 2

    code, output = handle_text(raw)
    print(output)
    print("\n(exit code: %s)" % code)
    return 0 if code == 0 else code


if __name__ == "__main__":
    raise SystemExit(main())
