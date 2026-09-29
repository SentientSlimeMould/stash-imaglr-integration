# SPDX-License-Identifier: AGPL-3.0-only
import io
import unittest
from contextlib import redirect_stderr

from imaglr_integration import log


def capture(fn, *args):
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        fn(*args)
    return buffer.getvalue()


class LogTest(unittest.TestCase):
    def test_every_line_is_prefixed(self):
        out = capture(log.info, "first\nsecond")
        self.assertEqual(out, "\x01i\x02first\n\x01i\x02second\n")

    def test_keys_are_masked(self):
        out = capture(log.error, 'failed with key pbk_1234|abcDEF and "pbk_99|x"')
        self.assertNotIn("abcDEF", out)
        self.assertNotIn("99|x", out)
        self.assertEqual(out.count("pbk_***"), 2)

    def test_long_lines_are_truncated(self):
        out = capture(log.debug, "x" * 100_000)
        self.assertLess(len(out), log.MAX_LINE + 50)

    def test_progress_is_clamped(self):
        self.assertEqual(capture(log.progress, 1.7), "\x01p\x021.0\n")
        self.assertEqual(capture(log.progress, -1), "\x01p\x020.0\n")


if __name__ == "__main__":
    unittest.main()
