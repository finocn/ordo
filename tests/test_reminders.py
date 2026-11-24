import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ordo import db, reminders, timeparse as tp
from ordo.config import DEFAULTS
from ordo.notify.base import RecordingNotifier
from ordo.service import Store


class ReminderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(db.connect(Path(self._tmp.name) / "ordo.db"),
                           json.loads(json.dumps(DEFAULTS)))

    def tearDown(self):
        self.store.conn.close()
        self._tmp.cleanup()

    def test_overdue_is_delivered_and_nag_scheduled(self):
        now = tp.now_utc()
        task = self.store.add_task("late", due=now - timedelta(hours=3))
        notifier = RecordingNotifier()
        results = reminders.run(self.store, notifier, now=now)
        self.assertTrue(any(r["status"] == "sent" for r in results))
        self.assertEqual(len(notifier.messages), 1)
        pending = [r for r in self.store.all_reminders(task_id=task.id) if r.status == "pending"]
        self.assertEqual([r.kind for r in pending], ["overdue"])
        self.assertIn("reminded", [e.kind for e in self.store.history(task.id)])

    def test_nag_interval_is_respected(self):
        now = tp.now_utc()
        task = self.store.add_task("late", due=now - timedelta(hours=1))
        notifier = RecordingNotifier()
        reminders.run(self.store, notifier, now=now)
        # an hour later the next nag is queued but not yet due
        self.assertEqual(reminders.run(self.store, notifier, now=now + timedelta(hours=1)), [])
        # after the (default 12h) interval it fires again
        again = reminders.run(self.store, notifier, now=now + timedelta(hours=13))
        self.assertTrue(any(r["task_id"] == task.id and r["kind"] == "overdue" for r in again))

    def test_dry_run_keeps_reminder_pending(self):
        now = tp.now_utc()
        task = self.store.add_task("late", due=now - timedelta(hours=3))
        notifier = RecordingNotifier()
        results = reminders.run(self.store, notifier, now=now, dry_run=True)
        self.assertTrue(results)
        self.assertTrue(all(r["status"] == "dry-run" for r in results))
        self.assertEqual(notifier.messages, [])
        pending = [r for r in self.store.all_reminders(task_id=task.id) if r.status == "pending"]
        self.assertTrue(pending)

    def test_closed_task_reminder_is_skipped(self):
        now = tp.now_utc()
        task = self.store.add_task("late", due=now - timedelta(hours=3))
        self.store.complete_task(task.id)
        notifier = RecordingNotifier()
        reminders.run(self.store, notifier, now=now)
        self.assertEqual(notifier.messages, [])

    def test_pending_due_reminder_fires_when_deadline_passes(self):
        now = tp.now_utc()
        task = self.store.add_task("upcoming", due=now + timedelta(hours=20))
        notifier = RecordingNotifier()
        results = reminders.run(self.store, notifier, now=now + timedelta(days=1))
        self.assertTrue(any(r["task_id"] == task.id and r["kind"] == "due" for r in results))


if __name__ == "__main__":
    unittest.main()
