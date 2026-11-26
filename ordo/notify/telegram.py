"""Telegram client and notifier built on urllib - no third-party dependency.

``TelegramClient`` is a thin wrapper over the Bot API (``getMe``, ``getUpdates``,
``sendMessage``); ``TelegramNotifier`` adapts it to the notifier interface used
by ``ordo remind``.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .base import Notifier, NotifyError

# Telegram's hard limit is 4096 characters; keep a margin.
MAX_LEN = 4000


def chunk_text(text, limit=MAX_LEN):
    """Split a message into Telegram-sized chunks, keeping the text intact."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # a single line longer than the limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current or not chunks:
        chunks.append(current)
    return chunks


class TelegramClient:
    """Minimal Bot API client (stdlib only)."""

    def __init__(self, token, api_base="https://api.telegram.org", timeout=15):
        if not token:
            raise NotifyError(
                "telegram needs a bot token "
                "(set notify.telegram.token or ORDO_TELEGRAM_TOKEN)"
            )
        self.token = token
        self.api_base = (api_base or "https://api.telegram.org").rstrip("/")
        self.timeout = timeout

    def _url(self, method):
        return "%s/bot%s/%s" % (self.api_base, self.token, method)

    def call(self, method, payload=None, timeout=None):
        data = urllib.parse.urlencode(payload or {}).encode("utf-8")
        request = urllib.request.Request(self._url(method), data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise NotifyError("telegram %s failed: %s" % (method, exc))
        if not body.get("ok"):
            raise NotifyError("telegram %s error: %s" % (method, body.get("description")))
        return body.get("result")

    def get_me(self):
        return self.call("getMe")

    def get_updates(self, offset=None, limit=100, timeout=0):
        """Fetch pending updates. ``timeout`` > 0 long-polls for that many seconds."""
        payload = {"limit": int(limit), "timeout": int(timeout or 0)}
        if offset is not None:
            payload["offset"] = int(offset)
        # give the HTTP layer a little more room than the long poll itself
        http_timeout = (int(timeout) + self.timeout) if timeout else None
        return self.call("getUpdates", payload, timeout=http_timeout) or []

    def send_message(self, chat_id, text, disable_notification=False):
        sent = []
        for part in chunk_text(text):
            payload = {
                "chat_id": chat_id,
                "text": part,
                "disable_web_page_preview": "true",
            }
            if disable_notification:
                payload["disable_notification"] = "true"
            sent.append(self.call("sendMessage", payload))
        return sent


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token, chat_id, api_base="https://api.telegram.org", timeout=15):
        if not token or not chat_id:
            raise NotifyError(
                "telegram channel needs a token and a chat_id "
                "(set notify.telegram.token/chat_id or ORDO_TELEGRAM_TOKEN/ORDO_TELEGRAM_CHAT)"
            )
        self.chat_id = chat_id
        self.client = TelegramClient(token, api_base=api_base, timeout=timeout)

    def send(self, message):
        self.client.send_message(self.chat_id, message.as_text())
        return []
