"""Telegram bot: turn chat messages into Ordo commands (stdlib only).

There is no long-lived daemon by default, by the same reasoning as
``ordo remind``: :meth:`Bot.run_once` drains the pending ``getUpdates``, runs each
message through the normal CLI, replies in the same chat and remembers the last
update id - so it can be driven from cron / GitHub Actions. :meth:`Bot.follow` is
a convenience long-poll loop for local use (and for verifying the whole path).
"""

from __future__ import annotations

import time

from .command import HELP_TEXT, handle_text
from .notify.telegram import TelegramClient

OFFSET_KEY = "bot.telegram.offset"

WELCOME = ("Привет! Это Ordo - планировщик задач со сроками и напоминаниями.\n\n"
           + HELP_TEXT)

TEST_MESSAGE = ("Ordo: проверка связи. Если вы видите это сообщение, "
                "токен и chat_id настроены верно.")


def build_client(config):
    """Create a Telegram client from the effective config."""
    options = (config.get("notify") or {}).get("telegram") or {}
    return TelegramClient(
        options.get("token", ""),
        api_base=options.get("api_base", "https://api.telegram.org"),
        timeout=options.get("timeout", 15),
    )


def chat_id_of(update):
    message = (update.get("message") or update.get("edited_message")
               or update.get("channel_post") or {})
    chat = message.get("chat") or {}
    return chat.get("id")


def text_of(update):
    message = (update.get("message") or update.get("edited_message")
               or update.get("channel_post") or {})
    return message.get("text")


class Bot:
    """Process Telegram updates against a :class:`~ordo.service.Store`."""

    def __init__(self, store, client, *, allowed_chat=None, dry_run=False,
                 global_args=(), logger=None):
        self.store = store
        self.client = client
        self.allowed_chat = str(allowed_chat) if allowed_chat else None
        self.dry_run = dry_run
        self.global_args = tuple(global_args)
        self.log = logger or (lambda message: None)

    # ---------------------------------------------------------------- access
    def authorized(self, chat_id):
        if self.allowed_chat is None:
            return True
        return str(chat_id) == self.allowed_chat

    # ---------------------------------------------------------------- offset
    def next_offset(self):
        try:
            return int(self.store.get_meta(OFFSET_KEY, "0") or 0)
        except (TypeError, ValueError):
            return 0

    def remember(self, update_id):
        self.store.set_meta(OFFSET_KEY, str(int(update_id) + 1))

    # --------------------------------------------------------------- updates
    def handle_update(self, update):
        """Handle one update and return a result dict. Never raises."""
        update_id = update.get("update_id")
        chat_id = chat_id_of(update)
        text = text_of(update)
        if chat_id is None or text is None:
            return {"update_id": update_id, "status": "skipped"}
        if not self.authorized(chat_id):
            self.log("bot: ignoring message from unauthorized chat %s" % chat_id)
            return {"update_id": update_id, "status": "ignored", "chat_id": chat_id}

        code, reply = self._reply_for(text)
        if not self.dry_run:
            self.client.send_message(chat_id, reply)
        return {
            "update_id": update_id,
            "status": "dry-run" if self.dry_run else "replied",
            "chat_id": chat_id,
            "code": code,
            "reply": reply,
        }

    def _reply_for(self, text):
        """A bare /start greets; everything else is a normal Ordo command."""
        words = (text or "").strip().split()
        first = words[0].lstrip("/").lower() if words else ""
        if first == "start" and len(words) == 1:
            return 0, WELCOME
        return handle_text(text, global_args=self.global_args)

    def run_once(self, *, limit=100, poll_timeout=0):
        """Process the currently pending updates and return their results."""
        offset = self.next_offset()
        updates = self.client.get_updates(offset or None, limit=limit,
                                          timeout=poll_timeout)
        results = []
        for update in updates:
            results.append(self.handle_update(update))
            if update.get("update_id") is not None:
                self.remember(update["update_id"])
        return results

    def follow(self, *, interval=2.0, limit=100, max_seconds=None):
        """Long-poll until interrupted. Returns the number of processed updates."""
        processed = 0
        started = time.monotonic()
        while max_seconds is None or (time.monotonic() - started) < max_seconds:
            try:
                updates = self.client.get_updates(self.next_offset() or None,
                                                  limit=limit, timeout=int(interval))
            except Exception as exc:  # noqa: BLE001 - keep the bot alive
                self.log("bot: %s; retrying in %ss" % (exc, interval))
                time.sleep(interval)
                continue
            for update in updates:
                self.handle_update(update)
                if update.get("update_id") is not None:
                    self.remember(update["update_id"])
                processed += 1
        return processed
