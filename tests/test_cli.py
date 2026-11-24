import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ordo.cli import main


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "ordo.db")
        self.addCleanup(self._tmp.cleanup)
        self._env = mock.patch.dict(
            os.environ, {"ORDO_CONFIG": str(Path(self._tmp.name) / "config.json")}
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def run_cli(self, *args):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--db", self.db, *args])
        return code, buffer.getvalue()

    def test_add_list_show_done(self):
        code, output = self.run_cli("add", "write", "tests", "-d", "3d", "-P", "1")
        self.assertEqual(code, 0)
        self.assertIn("added", output)

        code, output = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("write tests", output)
        self.assertIn("P1", output)

        code, output = self.run_cli("show", "1")
        self.assertEqual(code, 0)
        self.assertIn("write tests", output)

        code, output = self.run_cli("done", "1", "-c", "all green")
        self.assertEqual(code, 0)
        self.assertIn("done", output)

        code, output = self.run_cli("show", "1")
        self.assertEqual(code, 0)
        self.assertIn("all green", output)

    def test_json_output(self):
        self.run_cli("add", "json me", "-d", "3d")
        code, output = self.run_cli("list", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload[0]["title"], "json me")
        self.assertEqual(payload[0]["priority"], 2)

    def test_project_and_check(self):
        self.assertEqual(self.run_cli("project", "add", "ordo")[0], 0)
        self.run_cli("add", "task", "-p", "ordo", "-d", "1d")
        code, output = self.run_cli("project", "list")
        self.assertEqual(code, 0)
        self.assertIn("ordo", output)

        code, output = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("DUE TODAY", output)

    def test_postpone_and_remind(self):
        self.run_cli("add", "slip", "-d", "1d")
        code, output = self.run_cli("postpone", "1", "-d", "4d", "-r", "busy")
        self.assertEqual(code, 0)
        self.assertIn("move #1", output)

        code, output = self.run_cli("remind", "--dry-run")
        self.assertEqual(code, 0)

    def test_errors_are_friendly(self):
        code, _ = self.run_cli("done", "999")
        self.assertEqual(code, 1)
        code, _ = self.run_cli("add", "bad", "-d", "banana")
        self.assertEqual(code, 1)

    def test_init(self):
        code, output = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertIn("config", output)


if __name__ == "__main__":
    unittest.main()
