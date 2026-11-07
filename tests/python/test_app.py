# SPDX-License-Identifier: AGPL-3.0-only
import io
import json
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

from imaglr_integration import app
from imaglr_integration.context import Context

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


class UserAgentTest(unittest.TestCase):
    """imaglr knows the plugin by its User-Agent, and a release only bumps `version:` in the yml: the agent must
    follow that line, never a number written into the code."""

    def test_requests_name_the_released_version(self):
        with open(os.path.join(PLUGIN_DIR, "imaglrIntegration.yml"), encoding="utf-8") as f:
            released = re.search(r"(?m)^version:\s*(\S+)", f.read()).group(1)
        ctx = Context({"server_connection": {"PluginDir": PLUGIN_DIR}})
        with mock.patch("imaglr_integration.context.imaglr_base_override", return_value=None):
            client = ctx.imaglr({"api_key": "pbk_test_key_123"})
        self.assertEqual(client._headers["User-Agent"], f"stash-imaglr-integration/{released}")

    def test_no_version_is_written_into_the_agent(self):
        for folder, _, files in os.walk(os.path.join(PLUGIN_DIR, "imaglr_integration")):
            for name in (n for n in files if n.endswith(".py")):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    self.assertNotRegex(f.read(), r"stash-imaglr-integration/\d", name)


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
