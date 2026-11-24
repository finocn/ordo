"""Plain data objects for Ordo."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional

from . import timeparse as tp

# ---- task statuses ---------------------------------------------------------

STATUS_TODO = "todo"
STATUS_DOING = "doing"
STATUS_BLOCKED = "blocked"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = (STATUS_TODO, STATUS_DOING, STATUS_BLOCKED)
TERMINAL_STATUSES = (STATUS_DONE, STATUS_CANCELLED)
ALL_STATUSES = ACTIVE_STATUSES + TERMINAL_STATUSES

# ---- priorities (0 is the most urgent) -------------------------------------

PRIORITY_NAMES = {0: "critical", 1: "high", 2: "normal", 3: "low"}
PRIORITY_SHORT = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}

# ---- reminder kinds --------------------------------------------------------

REMINDER_DUE_SOON = "due_soon"
REMINDER_DUE = "due"
REMINDER_OVERDUE = "overdue"
REMINDER_POSTPONE = "postpone_followup"

REMINDER_KINDS = (
    REMINDER_DUE_SOON,
    REMINDER_DUE,
    REMINDER_OVERDUE,
    REMINDER_POSTPONE,
)


def row_to(cls, row):
    """Build a dataclass from a sqlite3.Row, ignoring unknown columns."""
    if row is None:
        return None
    data = dict(row)
    known = {f.name for f in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class Project:
    id: int = 0
    name: str = ""
    description: str = ""
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Task:
    id: int = 0
    project_id: Optional[int] = None
    title: str = ""
    description: str = ""
    status: str = STATUS_TODO
    priority: int = 2
    due_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    done_at: Optional[str] = None
    postpone_count: int = 0
    last_postponed_at: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def due_datetime(self):
        return tp.from_storage(self.due_at)

    def is_overdue(self, now=None) -> bool:
        due = self.due_datetime()
        if due is None or self.is_terminal:
            return False
        return due <= (now or tp.now_utc())

    @property
    def priority_label(self) -> str:
        return PRIORITY_SHORT.get(self.priority, "P%d" % self.priority)


@dataclass
class Comment:
    id: int = 0
    task_id: int = 0
    body: str = ""
    kind: str = "note"
    created_at: Optional[str] = None


@dataclass
class Event:
    id: int = 0
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    kind: str = ""
    detail: str = ""
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Reminder:
    id: int = 0
    task_id: int = 0
    kind: str = ""
    scheduled_at: Optional[str] = None
    status: str = "pending"
    channel: Optional[str] = None
    attempts: int = 0
    sent_at: Optional[str] = None
    last_error: Optional[str] = None
    created_at: Optional[str] = None
