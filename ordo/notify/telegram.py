"""Telegram notifier built on urllib - no third-party dependency."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .base import Notifier, NotifyError

MAX_LEN = 4000


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token, chat_id, api_base="https://api.telegram.org", timeout=15):
        if not token or not chat_id:
            raise NotifyError(
                "telegram channel needs a token and a chat_id "
                "(set notify.telegram.token/chat_id or ORDO_TELEGRAM_TOKEN/ORDO_TELEGRAM_CHAT)"
            )
        self.token = token
        self.chat_id = chat_id
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def send(self, message):
        text = message.as_text()
        if len(text) > MAX_LEN:
            text = text[: MAX_LEN - 1] + "\u2026"
        url = "%s/bot%s/sendMessage" % (self.api_base, self.token)
        payload = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise NotifyError("telegram send failed: %s" % exc)
        if not body.get("ok"):
            raise NotifyError("telegram error: %s" % body.get("description"))
        return []
