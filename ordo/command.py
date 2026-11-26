"""Run Ordo CLI commands coming from text (Telegram messages, GitHub issues).

The text is split with :mod:`shlex` - no shell, no injection - and handed to the
normal Ordo CLI. Output is captured so a bot reply or an issue comment can quote
it. This module is shared by ``ordo bot`` and ``tools/run_issue_command.py``.
"""

from __future__ import annotations

import contextlib
import io
import shlex

HELP_TEXT = """Ordo - планировщик задач. Команды:
  /help                        - эта справка
  /start                       - поздороваться с ботом
  /check                       - что требует внимания сейчас
  /list [--all] [--overdue]    - список задач
  /add "текст" -d 3d -P 1      - новая задача (-d срок, -P приоритет 0..3)
  /show <id>                   - подробности задачи
  /start <id>                  - взять в работу
  /done <id> [-c текст]        - закрыть задачу
  /block <id> [-c текст]       - пометить как заблокированную
  /comment <id> текст          - добавить комментарий
  /postpone <id> -d 5d -r причина

Работает весь CLI Ordo: незнакомый текст передаётся команде как есть."""


def split_command(text):
    """``'/add "x y" -d 3d'`` -> ``['add', 'x y', '-d', '3d']``."""
    raw = (text or "").strip()
    if raw.startswith("/"):
        raw = raw[1:].strip()
    if raw.lower().startswith("ordo "):
        raw = raw[5:].strip()
    if not raw:
        raise ValueError("empty command")
    return shlex.split(raw)


def run_command(argv, global_args=()):
    """Run the Ordo CLI, capture stdout/stderr, return ``(code, output)``.

    ``global_args`` are inserted before the command (e.g. ``--db``/``--config``)
    so the caller can pin the same database the bot is using.
    """
    from .cli import main as ordo_main

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = ordo_main([*global_args, *argv])
    except SystemExit as exc:  # argparse errors: unknown command, bad flags
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001 - never crash the caller
        return 1, "%s: %s" % (type(exc).__name__, exc)
    return code if code is not None else 1, buffer.getvalue().strip()


def handle_text(text, global_args=()):
    """Turn one user message into ``(code, reply)``."""
    raw = (text or "").strip()
    if not raw:
        return 2, HELP_TEXT
    words = raw.split()
    first = words[0].lstrip("/").lower()
    # Telegram's built-in /start and a bare /help are greetings - but
    # "/start 3" is the Ordo command that takes a task into work.
    if first == "help" or (first == "start" and len(words) == 1):
        return 0, HELP_TEXT
    try:
        argv = split_command(raw)
    except ValueError:
        return 2, HELP_TEXT
    code, output = run_command(argv, global_args=global_args)
    output = output.strip()
    if code == 0:
        return 0, output or "(готово)"
    if code == 2:
        return 2, (output + "\n\n" if output else "") + HELP_TEXT
    return code, output or "Команда не выполнена."
