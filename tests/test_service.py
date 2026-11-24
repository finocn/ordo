import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ordo import db, timeparse as tp
from ordo.config import DEFAULTS
from ordo.models import STATUS_DONE
from ordo.service import OrdoError, Store


def _config():
    return json.loads(json.dumps(DEFAULTS))


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(db.connect(Path(self._tmp.name) / "ordo.db"), _config())

    def tearDown(self):
        self.store.conn.close()
        self._tmp.cleanup()


class TaskTest(StoreTestCase):
    def test_add_and_priority_order(self):
        self.store.add_task("low", priority=3)
        self.store.add_task("urgent", priority=0)
        self.assertEqual([t.title for t in self.store.list_tasks()], ["urgent", "low"])

    def test_add_requires_project(self):
        with self.assertRaises(OrdoError):
            self.store.add_task("x", project="missing")

    def test_rejects_empty_title(self):
        with self.assertRaises(OrdoError):
            self.store.add_task("   ")

    def test_complete_cancels_pending_reminders(self):
        task = self.store.add_task("ship", due=tp.now_utc() + timedelta(days=1))
        self.assertTrue([r for r in self.store.all_reminders(task_id=task.id) if r.status == "pending"])
        self.store.complete_task(task.id, "shipped")
        self.assertEqual(self.store.get_task(task.id).status, STATUS_DONE)
        self.assertEqual([r for r in self.store.all_reminders(task_id=task.id) if r.status == "pending"], [])

    def test_reopen_reschedules(self):
        task = self.store.add_task("ship", due=tp.now_utc() + timedelta(days=2))
        self.store.complete_task(task.id)
        self.store.reopen_task(task.id)
        pending = [r for r in self.store.all_reminders(task_id=task.id) if r.status == "pending"]
        self.assertTrue(pending)

    def test_list_overdue(self):
        now = tp.now_utc()
        self.store.add_task("late", due=now - timedelta(hours=2))
        self.store.add_task("later", due=now + timedelta(days=3))
        overdue = self.store.list_tasks(overdue=True, now=now)
        self.assertEqual([t.title for t in overdue], ["late"])


class PostponeTest(StoreTestCase):
    def test_postpone_tracks_count_and_followup(self):
        now = tp.now_utc()
        task = self.store.add_task("draft", due=now + timedelta(days=1))
        task = self.store.postpone_task(task.id, now + timedelta(days=5), "waiting on review")
        self.assertEqual(task.postpone_count, 1)
        self.assertIn("postponed", [e.kind for e in self.store.history(task.id)])
        kinds = [r.kind for r in self.store.all_reminders(task_id=task.id) if r.status == "pending"]
        self.assertIn("postpone_followup", kinds)

    def test_cannot_postpone_done_task(self):
        task = self.store.add_task("x")
        self.store.complete_task(task.id)
        with self.assertRaises(OrdoError):
            self.store.postpone_task(task.id, tp.now_utc() + timedelta(days=1))


class CommentTest(StoreTestCase):
    def test_comment_is_stored(self):
        task = self.store.add_task("x")
        self.store.add_comment(task.id, "first note", "progress")
        comments = self.store.list_comments(task.id)
        self.assertEqual(comments[0].body, "first note")
        self.assertEqual(comments[0].kind, "progress")
        self.assertIn("comment", [e.kind for e in self.store.history(task.id)])

    def test_empty_comment_rejected(self):
        task = self.store.add_task("x")
        with self.assertRaises(OrdoError):
            self.store.add_comment(task.id, "   ")


class ReviewTest(StoreTestCase):
    def test_overdue_bucket(self):
        now = tp.now_utc()
        self.store.add_task("late", due=now - timedelta(days=2))
        self.store.add_task("fine", due=now + timedelta(days=10))
        buckets = self.store.review(now)
        self.assertEqual([t.title for t in buckets["overdue"]], ["late"])

    def test_postponed_bucket_sorted(self):
        now = tp.now_utc()
        first = self.store.add_task("once", due=now + timedelta(days=1))
        second = self.store.add_task("twice", due=now + timedelta(days=1))
        self.store.postpone_task(first.id, now + timedelta(days=2))
        self.store.postpone_task(second.id, now + timedelta(days=2))
        self.store.postpone_task(second.id, now + timedelta(days=3))
        buckets = self.store.review(now)
        self.assertEqual([t.title for t in buckets["postponed"]], ["twice", "once"])


if __name__ == "__main__":
    unittest.main()
