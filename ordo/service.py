"""Business logic for Ordo: projects, tasks, comments, postpones, reminders."""

from __future__ import annotations

from datetime import timedelta

from . import db as _db
from . import timeparse as tp
from .config import load as load_config
from .models import (
    ALL_STATUSES,
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    PRIORITY_NAMES,
    REMINDER_DUE,
    REMINDER_DUE_SOON,
    REMINDER_OVERDUE,
    REMINDER_POSTPONE,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
    Comment,
    Event,
    Project,
    Reminder,
    Task,
    row_to,
)


class OrdoError(Exception):
    """User-facing error (unknown task, invalid input, ...)."""


class Store:
    """A thin, explicit layer over the SQLite connection."""

    def __init__(self, conn, config=None):
        self.conn = conn
        self.config = config or load_config()

    @classmethod
    def open(cls, path, config=None):
        return cls(_db.connect(path), config)

    # ------------------------------------------------------------------ utils
    def _now(self):
        return tp.now_utc()

    def _reminder_setting(self, key, default):
        return self.config.get("reminders", {}).get(key, default)

    def _log(self, kind, *, task_id=None, project_id=None, detail="",
             old_value=None, new_value=None, now=None):
        self.conn.execute(
            "INSERT INTO events(task_id, project_id, kind, detail, old_value,"
            " new_value, created_at) VALUES (?,?,?,?,?,?,?)",
            (task_id, project_id, kind, detail or "", old_value, new_value,
             tp.to_storage(now or self._now())),
        )

    def record_event(self, kind, **kwargs):
        self._log(kind, **kwargs)
        self.conn.commit()

    # --------------------------------------------------------------- projects
    def add_project(self, name, description=""):
        name = (name or "").strip()
        if not name:
            raise OrdoError("project name must not be empty")
        if self.get_project(name) is not None:
            raise OrdoError("project %r already exists" % name)
        now = tp.to_storage(self._now())
        cursor = self.conn.execute(
            "INSERT INTO projects(name, description, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (name, description or "", "active", now, now),
        )
        self.conn.commit()
        return self.get_project(cursor.lastrowid)

    def get_project(self, ref):
        if ref is None:
            return None
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            row = self.conn.execute(
                "SELECT * FROM projects WHERE id = ?", (int(ref),)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM projects WHERE name = ?", (str(ref),)
            ).fetchone()
        return row_to(Project, row)

    def require_project(self, ref):
        project = self.get_project(ref)
        if project is None:
            raise OrdoError("no such project: %s" % ref)
        return project

    def list_projects(self, include_archived=False):
        sql = "SELECT * FROM projects"
        if not include_archived:
            sql += " WHERE status != 'archived'"
        sql += " ORDER BY name COLLATE NOCASE"
        return [row_to(Project, row) for row in self.conn.execute(sql)]

    def project_open_counts(self):
        rows = self.conn.execute(
            "SELECT project_id, COUNT(*) AS n FROM tasks"
            " WHERE status NOT IN ('done','cancelled') GROUP BY project_id"
        )
        return {row["project_id"]: row["n"] for row in rows}

    # ------------------------------------------------------------------ tasks
    def add_task(self, title, *, project=None, due=None, priority=2, description="", comment=None):
        title = (title or "").strip()
        if not title:
            raise OrdoError("task title must not be empty")
        if not isinstance(priority, int) or not 0 <= priority <= 3:
            raise OrdoError("priority must be an integer 0..3")
        project_id = self.require_project(project).id if project else None
        now = self._now()
        cursor = self.conn.execute(
            "INSERT INTO tasks(project_id, title, description, status, priority,"
            " due_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (project_id, title, description or "", STATUS_TODO, priority,
             tp.to_storage(due), tp.to_storage(now), tp.to_storage(now)),
        )
        task_id = cursor.lastrowid
        self._log("created", task_id=task_id, project_id=project_id,
                  detail=title, new_value=tp.to_storage(due), now=now)
        if comment:
            self._insert_comment(task_id, comment, "note", now)
        self.conn.commit()
        task = self.get_task(task_id)
        self._schedule_due_reminders(task)
        return self.get_task(task_id)

    def get_task(self, task_id):
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
        return row_to(Task, row)

    def require_task(self, task_id):
        task = self.get_task(task_id)
        if task is None:
            raise OrdoError("no such task: %s" % task_id)
        return task

    def list_tasks(self, *, project=None, status=None, overdue=False,
                   include_done=False, priority=None, now=None, limit=None):
        clauses, params = [], []
        if project:
            clauses.append("t.project_id = ?")
            params.append(self.require_project(project).id)
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            clauses.append("t.status IN (%s)" % ",".join("?" * len(statuses)))
            params.extend(statuses)
        elif not include_done:
            clauses.append("t.status NOT IN ('done','cancelled')")
        if priority is not None:
            clauses.append("t.priority = ?")
            params.append(int(priority))
        if overdue:
            clauses.append("t.due_at IS NOT NULL AND t.due_at <= ?"
                           " AND t.status NOT IN ('done','cancelled')")
            params.append(tp.to_storage(now or self._now()))
        sql = "SELECT t.* FROM tasks t"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += (" ORDER BY t.priority ASC, (t.due_at IS NULL), t.due_at ASC, t.id ASC")
        if limit:
            sql += " LIMIT %d" % int(limit)
        return [row_to(Task, row) for row in self.conn.execute(sql, params)]

    def edit_task(self, task_id, *, title=None, description=None, priority=None,
                  project=None, due=None, clear_due=False):
        task = self.require_task(task_id)
        now = self._now()
        updates, params, changes = [], [], []
        if title is not None:
            updates.append("title = ?")
            params.append(title.strip())
            changes.append("title")
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if priority is not None:
            if not 0 <= int(priority) <= 3:
                raise OrdoError("priority must be 0..3")
            updates.append("priority = ?")
            params.append(int(priority))
            changes.append("priority")
        if project is not None:
            new_id = self.require_project(project).id if project else None
            updates.append("project_id = ?")
            params.append(new_id)
            changes.append("project")
        due_changed = False
        if clear_due:
            updates.append("due_at = NULL")
            changes.append("due")
            due_changed = True
        elif due is not None:
            updates.append("due_at = ?")
            params.append(tp.to_storage(due))
            changes.append("due")
            due_changed = True
        if not updates:
            return task
        updates.append("updated_at = ?")
        params.append(tp.to_storage(now))
        params.append(task.id)
        self.conn.execute("UPDATE tasks SET %s WHERE id = ?" % ", ".join(updates), params)
        self._log("edited", task_id=task.id, project_id=task.project_id,
                  detail=", ".join(changes), old_value=task.due_at,
                  new_value=tp.to_storage(due) if due is not None else None, now=now)
        self.conn.commit()
        if due_changed:
            self._schedule_due_reminders(self.get_task(task.id))
        return self.get_task(task.id)

    def delete_task(self, task_id):
        task = self.require_task(task_id)
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task.id,))
        self.conn.commit()
        return task

    def set_status(self, task_id, status, *, comment=None):
        if status not in ALL_STATUSES:
            raise OrdoError("unknown status: %s (use %s)" % (status, ", ".join(ALL_STATUSES)))
        task = self.require_task(task_id)
        now = self._now()
        updates = ["status = ?", "updated_at = ?"]
        params = [status, tp.to_storage(now)]
        if status == STATUS_DOING and not task.started_at:
            updates.append("started_at = ?")
            params.append(tp.to_storage(now))
        if status in TERMINAL_STATUSES:
            updates.append("done_at = ?")
            params.append(tp.to_storage(now))
        else:
            updates.append("done_at = NULL")
        params.append(task.id)
        self.conn.execute("UPDATE tasks SET %s WHERE id = ?" % ", ".join(updates), params)
        self._log("status", task_id=task.id, project_id=task.project_id,
                  detail=comment or "", old_value=task.status, new_value=status, now=now)
        if comment:
            self._insert_comment(task.id, comment, "note", now)
        self.conn.commit()
        if status in TERMINAL_STATUSES:
            self._cancel_reminders(task.id, status="cancelled")
            self.conn.commit()
        return self.get_task(task.id)

    def start_task(self, task_id):
        return self.set_status(task_id, STATUS_DOING)

    def block_task(self, task_id, comment=None):
        return self.set_status(task_id, STATUS_BLOCKED, comment=comment)

    def complete_task(self, task_id, comment=None):
        return self.set_status(task_id, STATUS_DONE, comment=comment)

    def cancel_task(self, task_id, comment=None):
        return self.set_status(task_id, STATUS_CANCELLED, comment=comment)

    def reopen_task(self, task_id, comment=None):
        task = self.set_status(task_id, STATUS_TODO, comment=comment)
        self._schedule_due_reminders(task)
        return self.get_task(task_id)

    # --------------------------------------------------------------- comments
    def _insert_comment(self, task_id, body, kind, now):
        cursor = self.conn.execute(
            "INSERT INTO comments(task_id, body, kind, created_at) VALUES (?,?,?,?)",
            (task_id, body, kind or "note", tp.to_storage(now)),
        )
        return cursor.lastrowid

    def add_comment(self, task_id, body, kind="note"):
        task = self.require_task(task_id)
        body = (body or "").strip()
        if not body:
            raise OrdoError("comment must not be empty")
        now = self._now()
        self._insert_comment(task.id, body, kind, now)
        self._log("comment", task_id=task.id, project_id=task.project_id,
                  detail=body[:200], now=now)
        self.conn.commit()
        return self.get_task(task.id)

    def list_comments(self, task_id):
        rows = self.conn.execute(
            "SELECT * FROM comments WHERE task_id = ? ORDER BY id", (int(task_id),)
        )
        return [row_to(Comment, row) for row in rows]

    # --------------------------------------------------------------- postpone
    def postpone_task(self, task_id, new_due, reason=""):
        task = self.require_task(task_id)
        if task.is_terminal:
            raise OrdoError("cannot postpone a %s task (#%d)" % (task.status, task.id))
        if new_due is None:
            raise OrdoError("postpone needs a new deadline")
        now = self._now()
        old_due = task.due_at
        self.conn.execute(
            "UPDATE tasks SET due_at = ?, updated_at = ?,"
            " postpone_count = postpone_count + 1, last_postponed_at = ? WHERE id = ?",
            (tp.to_storage(new_due), tp.to_storage(now), tp.to_storage(now), task.id),
        )
        self._log("postponed", task_id=task.id, project_id=task.project_id,
                  detail=reason or "", old_value=old_due,
                  new_value=tp.to_storage(new_due), now=now)
        if reason:
            self._insert_comment(task.id, "postponed: %s" % reason, "postpone", now)
        self.conn.commit()
        task = self.get_task(task.id)
        self._schedule_due_reminders(task, followup=True)
        return self.get_task(task.id)

    # -------------------------------------------------------------- reminders
    def _insert_reminder(self, task_id, kind, when):
        self.conn.execute(
            "INSERT INTO reminders(task_id, kind, scheduled_at, status, created_at)"
            " VALUES (?,?,?, 'pending', ?)",
            (task_id, kind, tp.to_storage(when), tp.to_storage(self._now())),
        )

    def _cancel_reminders(self, task_id, status="cancelled", kinds=None):
        sql = "UPDATE reminders SET status = ? WHERE task_id = ? AND status = 'pending'"
        params = [status, int(task_id)]
        if kinds:
            sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            params.extend(kinds)
        self.conn.execute(sql, params)

    def _schedule_due_reminders(self, task, *, followup=False):
        now = self._now()
        self._cancel_reminders(task.id, kinds=(REMINDER_DUE_SOON, REMINDER_DUE, REMINDER_OVERDUE))
        if task.is_terminal:
            self.conn.commit()
            return
        if followup:
            when = now + tp.parse_duration(self._reminder_setting("postpone_recheck", "1d"))
            due = task.due_datetime()
            if due is not None and when > due:
                when = due
            self._insert_reminder(task.id, REMINDER_POSTPONE, when)
        due = task.due_datetime()
        if due is None:
            self.conn.commit()
            return
        lead = tp.parse_duration(self._reminder_setting("before", "1d"))
        soon = due - lead
        if soon > now:
            self._insert_reminder(task.id, REMINDER_DUE_SOON, soon)
        if due > now:
            self._insert_reminder(task.id, REMINDER_DUE, due)
        else:
            self._insert_reminder(task.id, REMINDER_OVERDUE, now)
        self.conn.commit()

    def ensure_overdue_nags(self, now=None):
        """Safety net: give every overdue task something pending to send.

        Normally a reminder is already queued, either because the task was
        created late or because a previous run scheduled the next nag. This
        only fires when that queue ran empty (e.g. reminders were edited),
        and it respects the nag interval so it never spams.
        """
        now = now or self._now()
        nag = tp.parse_duration(self._reminder_setting("nag_interval", "12h"))
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE due_at IS NOT NULL AND due_at <= ?"
            " AND status NOT IN ('done','cancelled')",
            (tp.to_storage(now),),
        ).fetchall()
        created = 0
        for row in rows:
            task = row_to(Task, row)
            pending = self.conn.execute(
                "SELECT 1 FROM reminders WHERE task_id = ? AND status = 'pending' LIMIT 1",
                (task.id,),
            ).fetchone()
            if pending is not None:
                continue
            last = self.conn.execute(
                "SELECT MAX(sent_at) AS ts FROM reminders WHERE task_id = ? AND status = 'sent'",
                (task.id,),
            ).fetchone()
            last_sent = tp.from_storage(last["ts"]) if last and last["ts"] else None
            if last_sent is not None and (now - last_sent) < nag:
                continue
            self._insert_reminder(task.id, REMINDER_OVERDUE, now)
            created += 1
        self.conn.commit()
        return created

    def schedule_next_overdue(self, task, now=None):
        """Queue the follow-up nag that keeps an overdue task nagging."""
        now = now or self._now()
        nag = tp.parse_duration(self._reminder_setting("nag_interval", "12h"))
        self._insert_reminder(task.id, REMINDER_OVERDUE, now + nag)
        self.conn.commit()

    def pending_reminders(self, now=None):
        now = now or self._now()
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND scheduled_at <= ?"
            " ORDER BY scheduled_at ASC, id ASC",
            (tp.to_storage(now),),
        )
        return [row_to(Reminder, row) for row in rows]

    def all_reminders(self, *, task_id=None, limit=100):
        sql = "SELECT * FROM reminders"
        params = []
        if task_id is not None:
            sql += " WHERE task_id = ?"
            params.append(int(task_id))
        sql += " ORDER BY id DESC LIMIT %d" % int(limit)
        return [row_to(Reminder, row) for row in self.conn.execute(sql, params)]

    def mark_reminder(self, reminder_id, status, *, channel=None, error=None):
        now = tp.to_storage(self._now())
        self.conn.execute(
            "UPDATE reminders SET status = ?, channel = COALESCE(?, channel),"
            " attempts = attempts + 1, sent_at = ?, last_error = ? WHERE id = ?",
            (status, channel, now if status == "sent" else None, error, int(reminder_id)),
        )
        self.conn.commit()

    # ------------------------------------------------------------ history/api
    def history(self, task_id, limit=100):
        rows = self.conn.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY id DESC LIMIT ?",
            (int(task_id), int(limit)),
        )
        return [row_to(Event, row) for row in rows]

    def recent_events(self, limit=50, project=None):
        sql = "SELECT * FROM events"
        params = []
        if project is not None:
            sql += " WHERE project_id = ?"
            params.append(self.require_project(project).id)
        sql += " ORDER BY id DESC LIMIT %d" % int(limit)
        return [row_to(Event, row) for row in self.conn.execute(sql, params)]

    def review(self, now=None, soon_days=7, stale_days=3):
        now = now or self._now()
        local_today = now.astimezone(tp.local_tz()).date()
        tasks = self.list_tasks(include_done=False, now=now)
        buckets = {"overdue": [], "today": [], "soon": [], "postponed": [],
                   "blocked": [], "stale": []}
        for task in tasks:
            due = task.due_datetime()
            if due is not None:
                if due <= now:
                    buckets["overdue"].append(task)
                elif due.astimezone(tp.local_tz()).date() == local_today:
                    buckets["today"].append(task)
                elif due <= now + timedelta(days=soon_days):
                    buckets["soon"].append(task)
            if task.status == STATUS_BLOCKED:
                buckets["blocked"].append(task)
            if task.status == STATUS_DOING and task.started_at:
                started = tp.from_storage(task.started_at)
                if started and (now - started) >= timedelta(days=stale_days):
                    buckets["stale"].append(task)
            if task.postpone_count > 0:
                buckets["postponed"].append(task)
        buckets["postponed"].sort(key=lambda t: (-t.postpone_count, t.id))
        return buckets
