"""Plain-text rendering for the Ordo CLI (tables, colours, detail views)."""

from __future__ import annotations

import os
import re
import shutil

from . import timeparse as tp
from .models import (
    PRIORITY_NAMES,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_DOING,
    STATUS_DONE,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_CODES = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
}


class Styler:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def __call__(self, text, *styles):
        if not self.enabled or not styles:
            return text
        prefix = "".join(_CODES[s] for s in styles if s in _CODES)
        return prefix + text + _CODES["reset"]


def make_styler(stream=None, enabled=None):
    if enabled is None:
        stream = stream or os.sys.stdout
        enabled = bool(
            getattr(stream, "isatty", lambda: False)()
            and os.environ.get("NO_COLOR") is None
        )
    return Styler(enabled)


def _visible_len(text):
    return len(_ANSI_RE.sub("", str(text)))


def table(headers, rows):
    rows = [["" if c is None else str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], _visible_len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    for row in rows:
        parts = []
        for index, cell in enumerate(row):
            pad = widths[index] - _visible_len(cell)
            parts.append(cell + " " * max(0, pad))
        lines.append("  ".join(parts).rstrip())
    return "\n".join(lines)


def humanize(due, now=None):
    if not due:
        return "-"
    now = now or tp.now_utc()
    seconds = (due - now).total_seconds()
    sign = 1 if seconds >= 0 else -1
    magnitude = abs(seconds)
    if magnitude < 90:
        amount = "%d sec" % round(magnitude)
    elif magnitude < 5400:
        amount = "%d min" % round(magnitude / 60)
    elif magnitude < 36 * 3600:
        amount = "%d h" % round(magnitude / 3600)
    else:
        amount = "%d d" % round(magnitude / 86400)
    return ("in %s" % amount) if sign >= 0 else ("%s overdue" % amount)


def _status_text(task, now, styler):
    if task.is_overdue(now):
        return styler(task.status, "bold", "red")
    if task.status == STATUS_DONE:
        return styler(task.status, "green")
    if task.status == STATUS_DOING:
        return styler(task.status, "cyan")
    if task.status == STATUS_BLOCKED:
        return styler(task.status, "yellow")
    if task.status == STATUS_CANCELLED:
        return styler(task.status, "dim")
    return task.status


def render_task_table(tasks, *, projects=None, now=None, styler=None):
    now = now or tp.now_utc()
    styler = styler or Styler(False)
    projects = projects or {}
    if not tasks:
        return "  (none)"
    rows = []
    for task in tasks:
        due = task.due_datetime()
        when = humanize(due, now) if due else ""
        if due and due <= now and not task.is_terminal:
            when = styler(when, "red")
        rows.append([
            "#%d" % task.id,
            task.priority_label,
            _status_text(task, now, styler),
            tp.format_local(due) if due else "-",
            when,
            projects.get(task.project_id, ""),
            task.title,
        ])
    return table(["ID", "P", "STATUS", "DUE", "WHEN", "PROJECT", "TITLE"], rows)


def render_check(buckets, *, projects=None, now=None, styler=None):
    now = now or tp.now_utc()
    sections = [
        ("OVERDUE", buckets.get("overdue", [])),
        ("DUE TODAY", buckets.get("today", [])),
        ("DUE SOON (7 days)", buckets.get("soon", [])),
        ("POSTPONED", buckets.get("postponed", [])),
        ("BLOCKED", buckets.get("blocked", [])),
        ("STALLED (in progress > 3 days)", buckets.get("stale", [])),
    ]
    out = []
    for title, tasks in sections:
        out.append(styler("%s (%d)" % (title, len(tasks)), "bold"))
        out.append(render_task_table(tasks, projects=projects, now=now, styler=styler))
        out.append("")
    return "\n".join(out).rstrip()


def render_projects(projects, counts=None, styler=None):
    styler = styler or Styler(False)
    if not projects:
        return "(no projects)"
    rows = []
    counts = counts or {}
    for project in projects:
        rows.append([
            "#%d" % project.id,
            project.name,
            project.status,
            str(counts.get(project.id, 0)),
            project.description,
        ])
    return table(["ID", "NAME", "STATUS", "OPEN", "DESCRIPTION"], rows)


def render_task_detail(store, task, *, now=None, styler=None):
    now = now or tp.now_utc()
    styler = styler or Styler(False)
    project = store.get_project(task.project_id) if task.project_id else None
    due = task.due_datetime()

    lines = [
        styler("#%d %s" % (task.id, task.title), "bold"),
        "  status:    %s" % task.status,
        "  priority:  %s (%s)" % (task.priority_label, PRIORITY_NAMES.get(task.priority, "?")),
        "  project:   %s" % (project.name if project else "-"),
        "  due:       %s" % (("%s (%s)" % (tp.format_local(due), humanize(due, now))) if due else "-"),
        "  created:   %s" % tp.format_local(tp.from_storage(task.created_at)),
        "  updated:   %s" % tp.format_local(tp.from_storage(task.updated_at)),
    ]
    if task.postpone_count:
        lines.append("  postponed: %d time(s), last %s"
                     % (task.postpone_count, tp.format_local(tp.from_storage(task.last_postponed_at))))
    if task.description:
        lines.append("")
        lines.append(task.description.strip())

    reminders = [r for r in store.all_reminders(task_id=task.id, limit=20) if r.status == "pending"]
    if reminders:
        lines.append("")
        lines.append(styler("pending reminders", "bold"))
        for reminder in sorted(reminders, key=lambda r: r.scheduled_at or ""):
            lines.append("  %s at %s (%s)"
                         % (reminder.kind, tp.format_local(tp.from_storage(reminder.scheduled_at)), humanize(tp.from_storage(reminder.scheduled_at), now)))

    comments = store.list_comments(task.id)
    if comments:
        lines.append("")
        lines.append(styler("comments", "bold"))
        for comment in comments:
            lines.append("  %s [%s] %s"
                         % (tp.format_local(tp.from_storage(comment.created_at)), comment.kind, comment.body))

    history = store.history(task.id, limit=25)
    if history:
        lines.append("")
        lines.append(styler("history", "bold"))
        for event in history:
            transition = ""
            if event.old_value or event.new_value:
                transition = " (%s -> %s)" % (event.old_value or "-", event.new_value or "-")
            detail = (" %s" % event.detail) if event.detail else ""
            lines.append("  %s %s%s%s"
                         % (tp.format_local(tp.from_storage(event.created_at)), event.kind, transition, detail))
    return "\n".join(lines)


def terminal_width(default=100):
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:  # pragma: no cover - very defensive
        return default
