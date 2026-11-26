"""Command-line interface for Ordo (argparse, standard library only)."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import reminders as reminders_mod
from . import report
from . import timeparse as tp
from .config import config_path, load as load_config, resolve_db_path, write_example
from .db import connect
from .models import ALL_STATUSES, PRIORITY_NAMES
from .notify import NotifyError, build_notifier
from .service import OrdoError, Store

_PRIORITY_BY_NAME = {name: value for value, name in PRIORITY_NAMES.items()}
_ALIASES = {"ls": "list", "note": "comment", "delete": "rm",
            "review": "check", "log-task": "history"}


def parse_priority(text):
    key = str(text).strip().lower()
    if key.isdigit() and 0 <= int(key) <= 3:
        return int(key)
    if key in _PRIORITY_BY_NAME:
        return _PRIORITY_BY_NAME[key]
    raise argparse.ArgumentTypeError(
        "priority must be 0..3 or one of: %s" % ", ".join(PRIORITY_NAMES.values())
    )


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", metavar="PATH", default=argparse.SUPPRESS)
    common.add_argument("--config", metavar="PATH", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog="ordo",
        description="Ordo - a deadline planner with history, postpone tracking and reminders.",
    )
    parser.add_argument("--db", metavar="PATH", help="database file (default: ./ordo.db)")
    parser.add_argument("--config", metavar="PATH", help="config file (default: ~/.config/ordo/config.json)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    parser.add_argument("--version", action="version", version="ordo %s" % __version__)

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="create the database and show where things live", parents=[common])

    # -- projects ----------------------------------------------------------
    project = sub.add_parser("project", help="manage projects", parents=[common])
    psub = project.add_subparsers(dest="project_command", required=True)
    p_add = psub.add_parser("add", help="add a project", parents=[common])
    p_add.add_argument("name")
    p_add.add_argument("-d", "--description", default="")
    p_list = psub.add_parser("list", help="list projects", parents=[common])
    p_list.add_argument("-a", "--all", action="store_true", help="include archived")
    p_show = psub.add_parser("show", help="show one project", parents=[common])
    p_show.add_argument("ref")

    # -- tasks -------------------------------------------------------------
    add = sub.add_parser("add", aliases=["new"], help="add a task", parents=[common])
    add.add_argument("title", nargs="+", help="task title")
    add.add_argument("-p", "--project")
    add.add_argument("-d", "--due", metavar="WHEN", help="deadline, e.g. '2026-11-30', '3d', 'tomorrow 18:00'")
    add.add_argument("-P", "--priority", type=parse_priority, default=2,
                     help="0..3 or critical/high/normal/low (default 2)")
    add.add_argument("--desc", dest="description", default="")
    add.add_argument("-c", "--comment", help="attach an initial comment")

    ls = sub.add_parser("list", aliases=["ls"], help="list tasks", parents=[common])
    ls.add_argument("-p", "--project")
    ls.add_argument("-s", "--status", choices=ALL_STATUSES)
    ls.add_argument("-P", "--priority", type=parse_priority)
    ls.add_argument("--overdue", action="store_true")
    ls.add_argument("-a", "--all", action="store_true", help="include done/cancelled")
    ls.add_argument("-n", "--limit", type=int)

    show = sub.add_parser("show", help="show a task in detail", parents=[common])
    show.add_argument("task_id")

    for name, help_text in (
        ("start", "mark a task as in progress"),
        ("block", "mark a task as blocked"),
        ("done", "mark a task as done"),
        ("cancel", "cancel a task"),
        ("reopen", "reopen a task"),
    ):
        cmd = sub.add_parser(name, help=help_text, parents=[common])
        cmd.add_argument("task_id")
        if name in ("done", "block", "cancel", "reopen"):
            cmd.add_argument("-c", "--comment")

    edit = sub.add_parser("edit", help="edit task fields", parents=[common])
    edit.add_argument("task_id")
    edit.add_argument("-t", "--title")
    edit.add_argument("-d", "--due", metavar="WHEN")
    edit.add_argument("--clear-due", action="store_true")
    edit.add_argument("-P", "--priority", type=parse_priority)
    edit.add_argument("-p", "--project")
    edit.add_argument("--desc", dest="description")

    rm = sub.add_parser("rm", aliases=["delete"], help="delete a task", parents=[common])
    rm.add_argument("task_id")

    comment = sub.add_parser("comment", aliases=["note"], help="add a comment", parents=[common])
    comment.add_argument("task_id")
    comment.add_argument("body", nargs="+")
    comment.add_argument("-k", "--kind", default="note",
                         help="note/progress/blocker/review (default note)")

    postpone = sub.add_parser("postpone", help="move a deadline (and get reminded)", parents=[common])
    postpone.add_argument("task_id")
    postpone.add_argument("-d", "--due", "--to", dest="due", metavar="WHEN", required=True)
    postpone.add_argument("-r", "--reason", default="")

    # -- review / delivery -------------------------------------------------
    sub.add_parser("check", aliases=["review"], help="what needs attention now", parents=[common])

    remind = sub.add_parser("remind", help="deliver due reminders", parents=[common])
    remind.add_argument("--dry-run", action="store_true", help="show what would be sent")
    remind.add_argument("--channel", action="append", metavar="NAME",
                        help="override notify channels (repeatable)")
    remind.add_argument("--now", metavar="WHEN", help="pretend it is this time")

    bot = sub.add_parser("bot", help="answer Telegram commands (getUpdates)", parents=[common])
    bot.add_argument("--once", action="store_true",
                     help="process pending updates and exit (default)")
    bot.add_argument("--follow", action="store_true",
                     help="long-poll until stopped (for local use)")
    bot.add_argument("--test", action="store_true",
                     help="send a test message to the configured chat")
    bot.add_argument("--limit", type=int, default=100, help="max updates per run (default 100)")
    bot.add_argument("--timeout", type=float, default=2.0,
                     help="long-poll timeout in seconds for --follow (default 2)")
    bot.add_argument("--allow-chat", metavar="ID",
                     help="only accept this chat id (default: notify.telegram.chat_id)")
    bot.add_argument("--dry-run", action="store_true",
                     help="print the replies instead of sending them")

    history = sub.add_parser("history", aliases=["log-task"], help="show a task's history", parents=[common])
    history.add_argument("task_id")
    history.add_argument("-n", "--limit", type=int, default=50)

    log = sub.add_parser("log", help="recent activity across all tasks", parents=[common])
    log.add_argument("-n", "--limit", type=int, default=30)
    log.add_argument("-p", "--project")

    config_cmd = sub.add_parser("config", help="show config location and values", parents=[common])
    config_cmd.add_argument("--example", action="store_true", help="write a starter config file")

    return parser


def _emit(out, as_json, payload, text):
    if as_json:
        out.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    elif text:
        out.write(text.rstrip() + "\n")


def _task_id(value):
    try:
        return int(str(value).lstrip("#"))
    except ValueError:
        raise OrdoError("task id must be a number, got %r" % value)


def _resolve_when(text, config):
    return tp.parse_when(text, due_time=config.get("due_time", "18:00"))


def _task_payload(task, projects=None):
    due = task.due_datetime()
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "priority_name": PRIORITY_NAMES.get(task.priority),
        "project_id": task.project_id,
        "project": (projects or {}).get(task.project_id),
        "due_at": task.due_at,
        "due_local": tp.format_local(due) if due else None,
        "overdue": task.is_overdue(),
        "postpone_count": task.postpone_count,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "done_at": task.done_at,
    }


def _projects_map(store):
    return {p.id: p.name for p in store.list_projects(include_archived=True)}


def _status_summary(task):
    due = task.due_datetime()
    suffix = ""
    if due:
        suffix = " (due %s, %s)" % (tp.format_local(due), report.humanize(due))
    return "#%d %s -> %s%s" % (task.id, task.title, task.status, suffix)


def _masked(config):
    masked = json.loads(json.dumps(config, default=str))
    try:
        if masked["notify"]["telegram"]["token"]:
            masked["notify"]["telegram"]["token"] = "***"
    except (KeyError, TypeError):
        pass
    try:
        if masked["notify"]["email"]["password"]:
            masked["notify"]["email"]["password"] = "***"
    except (KeyError, TypeError):
        pass
    return masked


def dispatch(args, store, config, out, styler):
    command = _ALIASES.get(args.command, args.command)
    as_json = getattr(args, "json", False)

    if command is None or command == "check":
        now = tp.now_utc()
        buckets = store.review(now)
        if as_json:
            payload = {
                key: [_task_payload(task, _projects_map(store)) for task in tasks]
                for key, tasks in buckets.items()
            }
            _emit(out, True, payload, "")
        else:
            _emit(out, False, None, report.render_check(buckets, projects=_projects_map(store),
                                                        now=now, styler=styler))
        return 0

    if command == "init":
        _emit(out, as_json,
              {"db": str(store.conn.execute("PRAGMA database_list").fetchone()[2]),
               "config": str(config_path())},
              "database ready: %s\nconfig: %s\nrun 'ordo config --example' to write a starter config"
              % (store.conn.execute("PRAGMA database_list").fetchone()[2], config_path()))
        return 0

    if command == "config":
        if args.example:
            path = write_example()
            _emit(out, as_json, {"config": str(path)}, "wrote starter config to %s" % path)
            return 0
        _emit(out, as_json, _masked(config), json.dumps(_masked(config), indent=2, ensure_ascii=False))
        return 0

    if command == "project":
        return _dispatch_project(args, store, out, as_json, styler)

    if command == "add":
        due = _resolve_when(args.due, config) if args.due else None
        task = store.add_task(" ".join(args.title), project=args.project, due=due,
                              priority=args.priority, description=args.description,
                              comment=args.comment)
        _emit(out, as_json, _task_payload(task, _projects_map(store)),
              "added %s" % _status_summary(task))
        return 0

    if command == "list":
        now = tp.now_utc()
        tasks = store.list_tasks(project=args.project, status=args.status, overdue=args.overdue,
                                 include_done=args.all, priority=args.priority, now=now,
                                 limit=args.limit)
        projects = _projects_map(store)
        _emit(out, as_json, [_task_payload(task, projects) for task in tasks],
              report.render_task_table(tasks, projects=projects, now=now, styler=styler))
        return 0

    if command == "show":
        task = store.require_task(_task_id(args.task_id))
        _emit(out, as_json, _task_payload(task, _projects_map(store)),
              report.render_task_detail(store, task, styler=styler))
        return 0

    if command == "edit":
        due = _resolve_when(args.due, config) if args.due else None
        task = store.edit_task(_task_id(args.task_id), title=args.title,
                               description=args.description, priority=args.priority,
                               project=args.project, due=due, clear_due=args.clear_due)
        _emit(out, as_json, _task_payload(task, _projects_map(store)),
              "updated %s" % _status_summary(task))
        return 0

    if command == "rm":
        task = store.delete_task(_task_id(args.task_id))
        _emit(out, as_json, {"deleted": task.id}, "deleted #%d %s" % (task.id, task.title))
        return 0

    if command in ("start", "block", "done", "cancel", "reopen"):
        task_id = _task_id(args.task_id)
        comment = getattr(args, "comment", None)
        if command == "start":
            task = store.start_task(task_id)
        elif command == "block":
            task = store.block_task(task_id, comment)
        elif command == "done":
            task = store.complete_task(task_id, comment)
        elif command == "cancel":
            task = store.cancel_task(task_id, comment)
        else:
            task = store.reopen_task(task_id, comment)
        _emit(out, as_json, _task_payload(task, _projects_map(store)),
              "%s" % _status_summary(task))
        return 0

    if command == "comment":
        task = store.add_comment(_task_id(args.task_id), " ".join(args.body), args.kind)
        _emit(out, as_json, _task_payload(task, _projects_map(store)),
              "commented on #%d" % task.id)
        return 0

    if command == "postpone":
        new_due = _resolve_when(args.due, config)
        task = store.postpone_task(_task_id(args.task_id), new_due, args.reason)
        _emit(out, as_json, _task_payload(task, _projects_map(store)),
              "postponed %s (move #%d)" % (_status_summary(task), task.postpone_count))
        return 0

    if command == "history":
        task = store.require_task(_task_id(args.task_id))
        events = store.history(task.id, args.limit)
        if as_json:
            _emit(out, True, [event.__dict__ for event in events], "")
        else:
            lines = ["history for #%d %s" % (task.id, task.title)]
            for event in events:
                transition = ""
                if event.old_value or event.new_value:
                    transition = " (%s -> %s)" % (event.old_value or "-", event.new_value or "-")
                detail = (" %s" % event.detail) if event.detail else ""
                lines.append("  %s %s%s%s" % (tp.format_local(tp.from_storage(event.created_at)),
                                              event.kind, transition, detail))
            _emit(out, False, None, "\n".join(lines))
        return 0

    if command == "log":
        events = store.recent_events(args.limit, project=args.project)
        projects = _projects_map(store)
        if as_json:
            _emit(out, True, [event.__dict__ for event in events], "")
        else:
            rows = []
            for event in events:
                rows.append([
                    tp.format_local(tp.from_storage(event.created_at)),
                    event.kind,
                    ("#%d" % event.task_id) if event.task_id else "-",
                    projects.get(event.project_id, ""),
                    event.detail,
                ])
            _emit(out, False, None, report.table(["WHEN", "KIND", "TASK", "PROJECT", "DETAIL"], rows))
        return 0

    if command == "remind":
        notifier = build_notifier(config, args.channel)
        now = _resolve_when(args.now, config) if args.now else None
        try:
            results = reminders_mod.run(store, notifier, now=now, dry_run=args.dry_run)
        finally:
            notifier.close()
        if as_json:
            _emit(out, True, results, "")
        else:
            if not results:
                _emit(out, False, None, "nothing to remind about")
            else:
                for item in results:
                    _emit(out, False, None, "%-12s #%s %s%s"
                          % (item["status"], item.get("task_id"), item.get("kind", ""),
                             (" " + item["subject"]) if item.get("subject") else ""))
                    if args.dry_run and item.get("body"):
                        _emit(out, False, None, item["body"])
        return 0

    if command == "bot":
        return _dispatch_bot(args, store, config, out, as_json)

    raise OrdoError("unknown command: %s" % command)


def _dispatch_bot(args, store, config, out, as_json):
    from . import bot as bot_mod

    telegram = (config.get("notify") or {}).get("telegram") or {}
    chat_id = telegram.get("chat_id") or ""

    if getattr(args, "test", False):
        if not chat_id:
            raise OrdoError(
                "bot --test needs a chat id (set notify.telegram.chat_id or ORDO_TELEGRAM_CHAT)"
            )
        if args.dry_run:
            _emit(out, as_json, {"dry_run": True, "chat_id": chat_id, "text": bot_mod.TEST_MESSAGE},
                  "dry-run: would send a test message to %s" % chat_id)
            return 0
        client = bot_mod.build_client(config)
        client.send_message(chat_id, bot_mod.TEST_MESSAGE)
        me = {}
        try:
            me = client.get_me() or {}
        except Exception:  # noqa: BLE001 - getMe is a nice-to-have
            pass
        _emit(out, as_json, {"sent": True, "chat_id": chat_id, "bot": me.get("username")},
              "test message sent to %s as @%s" % (chat_id, me.get("username") or "?"))
        return 0

    global_args = []
    if getattr(args, "db", None):
        global_args += ["--db", args.db]
    if getattr(args, "config", None):
        global_args += ["--config", args.config]

    client = bot_mod.build_client(config)
    allowed = getattr(args, "allow_chat", None) or chat_id or None
    logger = (lambda text: None) if as_json else (lambda text: _emit(out, False, None, text))
    bot = bot_mod.Bot(store, client, allowed_chat=allowed, dry_run=args.dry_run,
                      global_args=global_args, logger=logger)

    if args.follow:
        _emit(out, as_json, {"following": True},
              "ordo bot: жду команды в Telegram (Ctrl+C - остановить)")
        bot.follow(interval=args.timeout, limit=args.limit)
        return 0

    results = bot.run_once(limit=args.limit)
    if as_json:
        _emit(out, True, results, "")
    elif not results:
        _emit(out, False, None, "no new updates")
    else:
        for item in results:
            _emit(out, False, None, "%-8s update=%s chat=%s"
                  % (item.get("status"), item.get("update_id"), item.get("chat_id")))
            if args.dry_run and item.get("reply"):
                _emit(out, False, None, item["reply"])
    return 0


def _dispatch_project(args, store, out, as_json, styler):
    sub_command = args.project_command
    if sub_command == "add":
        project = store.add_project(args.name, args.description)
        _emit(out, as_json, project.__dict__, "added project #%d %s" % (project.id, project.name))
        return 0
    if sub_command == "list":
        projects = store.list_projects(include_archived=args.all)
        counts = store.project_open_counts()
        _emit(out, as_json, [dict(project.__dict__, open_tasks=counts.get(project.id, 0))
                             for project in projects],
              report.render_projects(projects, counts, styler=styler))
        return 0
    if sub_command == "show":
        project = store.require_project(args.ref)
        tasks = store.list_tasks(project=project.id, include_done=False)
        payload = dict(project.__dict__, tasks=[_task_payload(task) for task in tasks])
        _emit(out, as_json, payload,
              "%s\n\n%s" % (project.name,
                            report.render_task_table(tasks, projects={project.id: project.name},
                                                     styler=styler)))
        return 0
    raise OrdoError("unknown project command: %s" % sub_command)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    out = sys.stdout
    err = sys.stderr

    try:
        config = load_config(getattr(args, "config", None))
        store = Store(connect(resolve_db_path(config, getattr(args, "db", None))), config)
    except Exception as exc:  # noqa: BLE001 - startup failures should be friendly
        print("ordo: %s" % exc, file=err)
        return 2

    enabled = False if getattr(args, "no_color", False) else None
    styler = report.make_styler(out, enabled=enabled)
    try:
        return dispatch(args, store, config, out, styler)
    except (OrdoError, tp.TimeParseError, NotifyError) as exc:
        print("ordo: %s" % exc, file=err)
        return 1
    finally:
        store.conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
