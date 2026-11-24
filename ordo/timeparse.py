"""Human-friendly time parsing plus storage helpers (UTC ISO-8601, 'Z').

Accepted deadline forms::

    now
    today / tomorrow / yesterday            (+ optional clock)
    3d, 12h, 30m, 2w, "in 3 days", "+2w"
    mon / friday                            (next occurrence)
    2026-11-30, 30.11.2026
    2026-11-30 18:00, 2026-11-30T18:00
    tomorrow 09:30
    18:00                                   (today)

Storage format is always ``YYYY-MM-DDTHH:MM:SSZ`` in UTC so that plain
string comparison and SQL ordering behave correctly.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

UTC = timezone.utc

_UNITS = {
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
    "mo": 2592000, "month": 2592000, "months": 2592000,
}

_DUR_RE = re.compile(
    r"^(?:in\s+|from\s+now\s+)?\+?(?P<num>\d+)\s*(?P<unit>[a-z]+)$", re.IGNORECASE
)
_CLOCK_RE = re.compile(r"^(?P<h>\d{1,2})(?::(?P<m>\d{2}))?(?::(?P<s>\d{2}))?$")
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y.%m.%d")

_DAYS = {
    "today": 0, "tomorrow": 1, "yesterday": -1,
    "сегодня": 0, "завтра": 1, "вчера": -1,
}
_WEEKDAYS = {
    "mon": 0, "monday": 0, "пн": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "вт": 1,
    "wed": 2, "wednesday": 2, "ср": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "чт": 3,
    "fri": 4, "friday": 4, "пт": 4,
    "sat": 5, "saturday": 5, "сб": 5,
    "sun": 6, "sunday": 6, "вс": 6,
}


class TimeParseError(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def local_tz():
    return datetime.now().astimezone().tzinfo


def parse_duration(text: str) -> timedelta:
    match = _DUR_RE.match(text.strip())
    if not match:
        raise TimeParseError("not a duration: %r" % text)
    unit = match.group("unit").lower()
    if unit not in _UNITS:
        raise TimeParseError("unknown time unit: %r" % unit)
    return timedelta(seconds=int(match.group("num")) * _UNITS[unit])


def _parse_clock(text: str):
    match = _CLOCK_RE.match(text.strip())
    if not match:
        return None
    hour = int(match.group("h"))
    minute = int(match.group("m") or 0)
    second = int(match.group("s") or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return (hour, minute, second)


def _parse_date(text: str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _combine(day, clock, due_time, tz):
    if clock is None:
        clock = _parse_clock(due_time) or (18, 0, 0)
    return datetime(day.year, day.month, day.day, *clock, tzinfo=tz).astimezone(UTC)


def parse_when(text, now=None, due_time="18:00", tz=None) -> Optional[datetime]:
    """Parse a deadline string into an aware UTC datetime. ``None`` for empty input."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    now = now or now_utc()
    tz = tz or local_tz()
    local_now = now.astimezone(tz)
    low = raw.lower()

    if low in ("now", "сейчас"):
        return now.astimezone(UTC)

    # pure clock -> today at that time
    clock = _parse_clock(low)
    if clock is not None:
        return _combine(local_now.date(), clock, due_time, tz)

    # pure relative duration
    try:
        return (now + parse_duration(low)).astimezone(UTC)
    except TimeParseError:
        pass

    head, _, tail = raw.partition(" ")
    head_key = head.lower()

    if head_key in _DAYS:
        day = (local_now + timedelta(days=_DAYS[head_key])).date()
        return _combine(day, _parse_clock(tail) if tail else None, due_time, tz)

    if head_key in _WEEKDAYS and (not tail or _parse_clock(tail)):
        ahead = (_WEEKDAYS[head_key] - local_now.weekday()) % 7 or 7
        day = (local_now + timedelta(days=ahead)).date()
        return _combine(day, _parse_clock(tail) if tail else None, due_time, tz)

    for sep in ("T", " "):
        if sep in raw:
            left, _, right = raw.partition(sep)
            day = _parse_date(left)
            clock = _parse_clock(right)
            if day is not None and clock is not None:
                return _combine(day, clock, due_time, tz)

    day = _parse_date(raw)
    if day is not None:
        return _combine(day, None, due_time, tz)

    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(UTC)
    except ValueError:
        pass

    raise TimeParseError(
        "cannot understand deadline %r (try '2026-11-30', '3d', 'tomorrow 18:00')" % text
    )


def to_storage(dt) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_storage(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


def format_local(dt, fmt="%Y-%m-%d %H:%M", tz=None) -> str:
    if not dt:
        return "-"
    tz = tz or local_tz()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).strftime(fmt)
