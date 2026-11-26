"""Tests for the Telegram command layer (no network: the client is faked)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ordo.bot import WELCOME, Bot
from ordo.command import HELP_TEXT, handle_text, run_command, split_command
from ordo.config import DEFAULTS
from ordo.db import connect
from ordo.notify.base import NotifyError
from ordo.notify.telegram import TelegramClient, TelegramNotifier, chunk_text
from ordo.service import Store


class FakeClient:
    """Stands in for TelegramClient: records sends, replays queued updates."""

    def __init__(self, updates=None):
        self.updates = list(updates or [])
        self.sent = []
        self.calls = []

    def get_updates(self, offset=None, limit=100, timeout=0):
        self.calls.append(("getUpdates", offset, limit, timeout))
        if offset is None:
            return list(self.updates)
        return [item for item in self.updates if item.get("update_id", 0) >= int(offset)]

    def send_message(self, chat_id, text, disable_notification=False):
        self.sent.append((chat_id, text))
        return [{"message_id": len(self.sent)}]


def make_update(update_id, text, chat_id=42):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Tester"},
            "text": text,
        },
    }


class _TempState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = str(self.root / "ordo.db")
        self.config_arg = ["--config", str(self.root / "config.json")]
        self._env = mock.patch.dict(
            os.environ, {"ORDO_CONFIG": str(self.root / "config.json")}
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        self.store = Store(connect(self.db), DEFAULTS)
        self.addCleanup(self.store.conn.close)

    def global_args(self):
        return ["--db", self.db, *self.config_arg]


class CommandTest(_TempState):
    def test_split_strips_prefixes(self):
        self.assertEqual(split_command('/add "x y" -d 3d'), ["add", "x y", "-d", "3d"])
        self.assertEqual(split_command("ordo list --overdue"), ["list", "--overdue"])

    def test_split_rejects_empty(self):
        with self.assertRaises(ValueError):
            split_command("   ")
        with self.assertRaises(ValueError):
            split_command("/")

    def test_greetings_return_help(self):
        for text in ("/start", "/help", "help"):
            code, reply = handle_text(text)
            self.assertEqual(code, 0)
            self.assertIn("/add", reply)

    def test_unknown_command_returns_help_with_nonzero_code(self):
        code, reply = handle_text("/frobnicate", global_args=self.global_args())
        self.assertNotEqual(code, 0)
        self.assertIn("/help", reply)

    def test_real_command_adds_a_task(self):
        code, reply = handle_text('/add "из бота" -d 3d -P 1',
                                  global_args=self.global_args())
        self.assertEqual(code, 0)
        self.assertIn("added", reply)
        self.assertIn("из бота", [task.title for task in self.store.list_tasks()])

    def test_run_command_reports_cli_error(self):
        code, output = run_command(["done", "999"], global_args=self.global_args())
        self.assertEqual(code, 1)
        self.assertIn("no such task", output)


class BotTest(_TempState):
    def build(self, updates, **kwargs):
        client = FakeClient(updates)
        kwargs.setdefault("global_args", self.global_args())
        bot = Bot(self.store, client, **kwargs)
        return bot, client

    def test_start_replies_with_welcome(self):
        bot, client = self.build([make_update(1, "/start")])
        results = bot.run_once()
        self.assertEqual(results[0]["status"], "replied")
        self.assertEqual(client.sent[0][0], 42)
        self.assertTrue(client.sent[0][1].startswith(WELCOME[:20]))

    def test_add_creates_task_and_replies(self):
        bot, client = self.build([make_update(1, '/add "через бота" -d 3d')])
        bot.run_once()
        self.assertIn("added", client.sent[0][1])
        self.assertIn("через бота", [task.title for task in self.store.list_tasks()])

    def test_offset_advances_and_updates_are_not_replayed(self):
        bot, client = self.build([make_update(7, "/list")])
        bot.run_once()
        self.assertEqual(self.store.get_meta("bot.telegram.offset"), "8")
        self.assertEqual(bot.run_once(), [])
        self.assertEqual(len(client.sent), 1)

    def test_unauthorized_chat_is_ignored(self):
        bot, client = self.build([make_update(1, "/list", chat_id=999)], allowed_chat="42")
        results = bot.run_once()
        self.assertEqual(results[0]["status"], "ignored")
        self.assertEqual(client.sent, [])

    def test_dry_run_never_sends(self):
        bot, client = self.build([make_update(1, "/start")], dry_run=True)
        results = bot.run_once()
        self.assertEqual(results[0]["status"], "dry-run")
        self.assertEqual(client.sent, [])

    def test_unknown_text_still_gets_an_answer(self):
        bot, client = self.build([make_update(1, "dashboard: упал деплой")])
        bot.run_once()
        self.assertIn(HELP_TEXT.splitlines()[0], client.sent[-1][1])

    def test_updates_without_text_are_skipped(self):
        bot, client = self.build([{"update_id": 3, "message": {"chat": {"id": 42}}}])
        results = bot.run_once()
        self.assertEqual(results[0]["status"], "skipped")
        self.assertEqual(client.sent, [])


class TelegramPiecesTest(unittest.TestCase):
    def test_client_needs_a_token(self):
        with self.assertRaises(NotifyError):
            TelegramClient("")

    def test_notifier_needs_token_and_chat(self):
        with self.assertRaises(NotifyError):
            TelegramNotifier("tok", "")
        with self.assertRaises(NotifyError):
            TelegramNotifier("", "42")

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text("привет"), ["привет"])

    def test_long_text_is_split_losslessly(self):
        text = "\n".join("line %d" % i for i in range(500))
        parts = chunk_text(text, limit=200)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 200 for part in parts))
        self.assertEqual("".join(parts), text)


if __name__ == "__main__":
    unittest.main()
