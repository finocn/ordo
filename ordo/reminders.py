"""Reminder scan + dispatch. Uses the pluggable notifier, stdlib only."""

from __future__ import annotations

from . import timeparse as tp
from .models import (
    PRIORITY_NAMES,
    REMINDER_DUE,
    REMINDER_DUE_SOON,
    REMINDER_OVERDUE,
    REMINDER_POSTPONE,
)
from .notify.base import Message
from .report import humanize

KIND_TITLES = {
    REMINDER_DUE_SOON: "Deadline approaching",
    REMINDER_DUE: "Deadline reached",
    REMINDER_OVERDUE: "Task overdue",
    REMINDER_POSTPONE: "Postponed task - check in",
}

URGENT_KINDS = (REMINDER_DUE, REMINDER_OVERDUE, REMINDER_POSTPONE)


def build_message(store, task, reminder, now=None):
    now = now or tp.now_utc()
    project = store.get_project(task.project_id) if task.project_id else None
    due = task.due_datetime()

    lines = ["Task #%d: %s" % (task.id, task.title)]
    lines.append("Status:   %s" % task.status)
    lines.append("Priority: %s (%s)" % (task.priority_label, PRIORITY_NAMES.get(task.priority, "?")))
    if project is not None:
        lines.append("Project:  %s" % project.name)
    if due is not None:
        lines.append("Deadline: %s (%s)" % (tp.format_local(due), humanize(due, now)))
    if task.postpone_count:
        lines.append("Postponed %d time(s); this is a check-in on the moved deadline."
                     % task.postpone_count)
    if task.description:
        lines.append("")
        lines.append(task.description.strip())

    title = KIND_TITLES.get(reminder.kind, reminder.kind)
    subject = "[Ordo] %s: #%d %s" % (title, task.id, task.title)
    return Message(
        subject=subject,
        body="\n".join(lines),
        task_id=task.id,
        kind=reminder.kind,
        urgent=reminder.kind in URGENT_KINDS,
    )


def run(store, notifier, *, now=None, dry_run=False, limit=None):
    """Deliver every reminder that is due. Returns a list of result dicts."""
    now = now or tp.now_utc()
    store.ensure_overdue_nags(now)
    pending = store.pending_reminders(now)
    if limit:
        pending = pending[: int(limit)]

    results = []
    channel = getattr(notifier, "name", None)
    for reminder in pending:
        task = store.get_task(reminder.task_id)
        if task is None or task.is_terminal:
            store.mark_reminder(reminder.id, "cancelled", error="task is closed")
            results.append({"reminder_id": reminder.id, "task_id": reminder.task_id,
                            "kind": reminder.kind, "status": "skipped"})
            continue

        message = build_message(store, task, reminder, now=now)
        if dry_run:
            results.append({"reminder_id": reminder.id, "task_id": task.id,
                            "kind": reminder.kind, "status": "dry-run",
                            "subject": message.subject, "body": message.body})
            continue

        try:
            errors = notifier.send(message) or []
        except Exception as exc:  # noqa: BLE001 - surface any transport failure
            store.mark_reminder(reminder.id, "failed", channel=channel, error=str(exc))
            results.append({"reminder_id": reminder.id, "task_id": task.id,
                            "kind": reminder.kind, "status": "failed", "error": str(exc)})
            continue

        store.mark_reminder(reminder.id, "sent", channel=channel,
                            error="; ".join(errors) if errors else None)
        store.record_event("reminded", task_id=task.id, project_id=task.project_id,
                           detail=reminder.kind, new_value=message.subject, now=now)

        # keep nagging overdue work: line up the next reminder before the
        # queue runs empty, so a cron-driven run always has something to do.
        due = task.due_datetime()
        if due is not None and due <= now and reminder.kind in (REMINDER_DUE, REMINDER_OVERDUE):
            store.schedule_next_overdue(task, now)

        results.append({"reminder_id": reminder.id, "task_id": task.id,
                        "kind": reminder.kind,
                        "status": "sent" if not errors else "sent-partial",
                        "subject": message.subject, "errors": errors})
    return results
