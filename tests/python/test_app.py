# SPDX-License-Identifier: AGPL-3.0-only
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

from imaglr_integration import app

PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "imaglrIntegration")


class DispatchTest(unittest.TestCase):
    def test_unknown_mode_is_an_error(self):
        output, error = app.handle({"args": {"mode": "nope"}})
        self.assertIsNone(output)
        self.assertIn("nope", error)

    def test_user_errors_are_returned_verbatim(self):
        def fails(ctx):
            raise app.UserError("Choose a blog first")

        with mock.patch.dict(app.OPERATIONS, {"x": fails}):
            self.assertEqual(app.handle({"args": {"mode": "x"}}), (None, "Choose a blog first"))

    def test_unexpected_errors_are_logged_and_reported(self):
        def crashes(ctx):
            raise ValueError("boom")

        stderr = io.StringIO()
        with mock.patch.dict(app.OPERATIONS, {"x": crashes}), redirect_stderr(stderr):
            output, error = app.handle({"args": {"mode": "x"}})
        self.assertIsNone(output)
        self.assertEqual(error, "x failed: boom")
        self.assertIn("Traceback", stderr.getvalue())

    def test_plugin_version_is_read_from_the_yaml(self):
        self.assertRegex(app.plugin_version(PLUGIN_DIR), r"^\d+\.\d+\.\d+$")


class EntryPointTest(unittest.TestCase):
    """Stash parses all of stdout as one JSON object, so main.py must print nothing else."""

    def test_stdout_is_exactly_one_json_reply(self):
        request = json.dumps({"server_connection": {}, "args": {"mode": "nope"}})
        result = subprocess.run(
            [sys.executable, os.path.join(PLUGIN_DIR, "main.py")],
            input=request.encode(), capture_output=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout), {"output": None, "error": "Unknown mode: 'nope'"})


if __name__ == "__main__":
    unittest.main()
