"""Tests for the free-hosting helpers in ``tools/`` (dashboard + IssueOps)."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ordo import timeparse as tp
from ordo.config import DEFAULTS
from ordo.db import connect
from ordo.service import Store
from tools import build_dashboard
from tools import run_issue_command


class _TempState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = str(self.root / "ordo.db")
        self._env = mock.patch.dict(
            os.environ, {"ORDO_CONFIG": str(self.root / "config.json")}
        )
        self._env.start()
        self.addCleanup(self._env.stop)


class DashboardTest(_TempState):
    def _seed(self):
        store = Store(connect(self.db), DEFAULTS)
        store.add_task("написать тесты", due=tp.now_utc(), priority=1)
        store.add_task("обычная задача", priority=2)
        store.conn.close()

    def test_builds_html(self):
        self._seed()
        out = self.root / "_site"
        target = build_dashboard.build(out, self.db)
        self.assertTrue(target.exists())
        self.assertTrue((out / ".nojekyll").exists())
        html = target.read_text(encoding="utf-8")
        self.assertIn("написать тесты", html)
        self.assertIn("Ordo", html)

    def test_empty_database_is_ok(self):
        target = build_dashboard.build(self.root / "_site", self.db)
        self.assertIn("Активных задач нет", target.read_text(encoding="utf-8"))


class IssueCommandTest(_TempState):
    def test_parse_strips_prefixes(self):
        self.assertEqual(
            run_issue_command.parse_command('/done 4 -c "готово"'),
            ["done", "4", "-c", "готово"],
        )
        self.assertEqual(
            run_issue_command.parse_command("ordo list --overdue"),
            ["list", "--overdue"],
        )

    def test_parse_rejects_empty(self):
        with self.assertRaises(ValueError):
            run_issue_command.parse_command("   ")

    def test_runs_a_real_command(self):
        buffer = io.StringIO()
        env = {"ORDO_ISSUE_COMMAND": 'add "через issue" -d 3d -P 1',
               "ORDO_DB": self.db, "ORDO_NOTIFY": "none"}
        with mock.patch.dict(os.environ, env):
            with contextlib.redirect_stdout(buffer):
                code = run_issue_command.main()
        self.assertEqual(code, 0)
        self.assertIn("added", buffer.getvalue())

        check = Store(connect(self.db), DEFAULTS)
        self.assertEqual(check.list_tasks()[0].title, "через issue")
        check.conn.close()

    def test_non_command_title_is_reported_not_crashed(self):
        """Regression: a plain issue title must not blow up the workflow.

        Previously argparse raised SystemExit before the database was created,
        so the "Save state" step failed with `pathspec 'ordo.db' did not match`.
        """
        buffer = io.StringIO()
        env = {"ORDO_ISSUE_COMMAND": "dashboard: Deploy to GitHub Pages падает с 404",
               "ORDO_DB": self.db, "ORDO_NOTIFY": "none"}
        with mock.patch.dict(os.environ, env):
            with contextlib.redirect_stdout(buffer):
                code = run_issue_command.main()
        self.assertNotEqual(code, 0)
        self.assertIn("Ordo", buffer.getvalue())

    def test_empty_command_is_reported(self):
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"ORDO_ISSUE_COMMAND": "  "}):
            with contextlib.redirect_stdout(buffer):
                code = run_issue_command.main()
        self.assertNotEqual(code, 0)
        self.assertIn("заголовке issue", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
