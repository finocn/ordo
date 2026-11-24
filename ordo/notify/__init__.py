"""Notifier registry. Channels are selected via ``notify.channels`` in config."""

from __future__ import annotations

from .base import (
    Message,
    MultiNotifier,
    Notifier,
    NotifyError,
    NullNotifier,
    RecordingNotifier,
)
from .console import ConsoleNotifier
from .email import EmailNotifier
from .file import FileNotifier
from .telegram import TelegramNotifier


def build_channel(name, config):
    name = (name or "").strip().lower()
    notify = config.get("notify", {})
    if name in ("console", "stdout"):
        return ConsoleNotifier()
    if name == "file":
        return FileNotifier(notify.get("file", {}).get("path", "ordo-outbox.jsonl"))
    if name == "telegram":
        options = notify.get("telegram", {})
        return TelegramNotifier(
            token=options.get("token", ""),
            chat_id=options.get("chat_id", ""),
            api_base=options.get("api_base", "https://api.telegram.org"),
            timeout=options.get("timeout", 15),
        )
    if name in ("email", "smtp", "mail"):
        options = notify.get("email", {})
        return EmailNotifier(
            host=options.get("host", ""),
            port=options.get("port", 587),
            username=options.get("username", ""),
            password=options.get("password", ""),
            sender=options.get("sender", ""),
            to=options.get("to", []),
            tls=options.get("tls", True),
        )
    if name in ("none", "null", "off"):
        return NullNotifier()
    raise NotifyError("unknown notify channel: %r" % name)


def build_notifier(config, channel_names=None):
    names = channel_names or config.get("notify", {}).get("channels") or ["console"]
    if isinstance(names, str):
        names = [names]
    channels = [build_channel(name, config) for name in names]
    if not channels:
        return NullNotifier()
    if len(channels) == 1:
        return channels[0]
    return MultiNotifier(channels)


__all__ = [
    "Message",
    "MultiNotifier",
    "Notifier",
    "NotifyError",
    "NullNotifier",
    "RecordingNotifier",
    "ConsoleNotifier",
    "EmailNotifier",
    "FileNotifier",
    "TelegramNotifier",
    "build_channel",
    "build_notifier",
]
