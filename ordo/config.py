"""Configuration loading for Ordo.

Layering (lowest to highest priority):

1. the built-in ``DEFAULTS`` below
2. a JSON config file (``~/.config/ordo/config.json`` or ``$ORDO_CONFIG``)
3. environment variables (handy for secrets and for tests)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "db": "ordo.db",
    "due_time": "18:00",
    "reminders": {
        # how far before the deadline to fire the "approaching" reminder
        "before": "1d",
        # how often to nag once a task is overdue
        "nag_interval": "12h",
        # how long after a postpone to check back in on the task
        "postpone_recheck": "1d",
    },
    "notify": {
        # any of: console, file, telegram, email, none
        "channels": ["console"],
        "file": {"path": "ordo-outbox.jsonl"},
        "telegram": {
            "token": "",
            "chat_id": "",
            "api_base": "https://api.telegram.org",
            "timeout": 15,
        },
        "email": {
            "host": "",
            "port": 587,
            "username": "",
            "password": "",
            "sender": "",
            "to": [],
            "tls": True,
        },
    },
}

_ENV_MAP = {
    "ORDO_TELEGRAM_TOKEN": ("notify", "telegram", "token"),
    "ORDO_TELEGRAM_CHAT": ("notify", "telegram", "chat_id"),
    "ORDO_SMTP_HOST": ("notify", "email", "host"),
    "ORDO_SMTP_PORT": ("notify", "email", "port"),
    "ORDO_SMTP_USER": ("notify", "email", "username"),
    "ORDO_SMTP_PASSWORD": ("notify", "email", "password"),
    "ORDO_SMTP_FROM": ("notify", "email", "sender"),
    "ORDO_SMTP_TO": ("notify", "email", "to"),
}


def config_path() -> Path:
    override = os.environ.get("ORDO_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "ordo" / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _env_overrides() -> dict:
    overrides: dict = {}
    if os.environ.get("ORDO_DB"):
        overrides["db"] = os.environ["ORDO_DB"]
    channels = os.environ.get("ORDO_NOTIFY")
    if channels:
        overrides.setdefault("notify", {})["channels"] = [
            c.strip() for c in channels.split(",") if c.strip()
        ]
    for env_name, path in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        node = overrides
        for part in path[:-1]:
            node = node.setdefault(part, {})
        leaf = path[-1]
        if leaf == "port":
            raw = int(raw)
        elif leaf == "to":
            raw = [item.strip() for item in raw.split(",") if item.strip()]
        node[leaf] = raw
    return overrides


def load(path=None) -> dict:
    """Return the effective configuration as a plain dict."""
    config = json.loads(json.dumps(DEFAULTS))
    target = Path(path).expanduser() if path else config_path()
    if target.exists():
        with target.open(encoding="utf-8") as handle:
            _deep_merge(config, json.load(handle))
    _deep_merge(config, _env_overrides())
    return config


def resolve_db_path(config: dict, override=None, cwd=None) -> Path:
    value = override or config.get("db") or "ordo.db"
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(cwd or Path.cwd()) / path
    return path


def write_example(path=None) -> Path:
    """Write a commented starter config and return its path."""
    target = Path(path).expanduser() if path else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    with target.open("w", encoding="utf-8") as handle:
        json.dump(DEFAULTS, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target
