# SPDX-License-Identifier: AGPL-3.0-only
"""ffmpeg_run with a stand-in "ffmpeg" (a Python script), so these run without ffmpeg installed."""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from imaglr_integration.media import ffmpeg_run
from imaglr_integration.media.ffmpeg_run import Cancelled, FfmpegError, finalise_part, run_ffmpeg

FAKE = r"""
import os, sys, time
mode, out = sys.argv[1], sys.argv[2]
with open(out, "wb") as f:
    f.write(b"partial")
if mode == "info":
    with open(out, "w") as f:
        f.write(str(os.nice(0)) if hasattr(os, "nice") else "0")
elif mode == "ok":
    for us in (0, 500000, 1000000, 1500000, 2000000):
        print("out_time_us=%d" % us, flush=True)
        time.sleep(0.1)
    print("progress=end", flush=True)
elif mode == "fail":
    for i in range(3000):
        sys.stderr.write("noise line %d\n" % i)
    sys.stderr.write("the real error\n")
    sys.exit(3)
elif mode == "hang":
    with open(out + ".pid", "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
"""

PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "imaglrIntegration"))


def alive(pid):
    """True if pid is running (a zombie counts as dead: it has exited but nobody reaped it)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return not os.path.isdir("/proc")


def wait_for(predicate, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class RunFfmpegTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = os.path.join(self.tmp, "fake_ffmpeg.py")
        with open(self.fake, "w") as f:
            f.write(FAKE)
        self.out = os.path.join(self.tmp, "out.mp4.part")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cmd(self, mode):
        return [sys.executable, self.fake, mode, self.out]

    def test_success_reports_scaled_progress_and_keeps_output(self):
        seen = []
        run_ffmpeg(self.cmd("ok"), output=self.out, duration_s=2.0, progress_cb=seen.append,
                   progress_range=(0.2, 0.6), poll_interval=0.05)
        self.assertTrue(os.path.exists(self.out))
        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))
        self.assertTrue(all(0.2 <= v <= 0.6 for v in seen))
        self.assertEqual(seen[-1], 0.6)

    def test_failure_raises_with_bounded_tail_and_removes_output(self):
        with self.assertRaises(FfmpegError) as ctx:
            run_ffmpeg(self.cmd("fail"), output=self.out)
        e = ctx.exception
        self.assertEqual(e.returncode, 3)
        self.assertIn("the real error", str(e))
        self.assertLessEqual(len(e.stderr_tail), ffmpeg_run.MAX_TAIL)
        self.assertLess(len(str(e)), 400)
        self.assertFalse(os.path.exists(self.out))

    def test_should_cancel_stops_the_process(self):
        calls = []

        def should_cancel():
            calls.append(1)
            return os.path.exists(self.out + ".pid")

        start = time.monotonic()
        with self.assertRaises(Cancelled):
            run_ffmpeg(self.cmd("hang"), output=self.out, should_cancel=should_cancel, poll_interval=0.05)
        self.assertLess(time.monotonic() - start, 15)
        with open(self.out + ".pid") as f:
            pid = int(f.read())
        self.assertTrue(wait_for(lambda: not alive(pid)))
        self.assertFalse(os.path.exists(self.out))

    def test_timeout(self):
        with self.assertRaises(FfmpegError) as ctx:
            run_ffmpeg(self.cmd("hang"), output=self.out, timeout=0.5, poll_interval=0.05)
        self.assertIn("timed out", str(ctx.exception))
        self.assertFalse(os.path.exists(self.out))

    @unittest.skipUnless(hasattr(os, "nice"), "POSIX only")
    def test_runs_at_lower_priority(self):
        run_ffmpeg(self.cmd("info"), output=self.out)
        with open(self.out) as f:
            child = int(f.read())
        self.assertEqual(child, min(os.nice(0) + 10, 19))

    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_PDEATHSIG is Linux only")
    def test_child_dies_when_plugin_is_killed(self):
        parent_code = (
            f"import sys; sys.path.insert(0, {PLUGIN_DIR!r})\n"
            "from imaglr_integration.media.ffmpeg_run import run_ffmpeg\n"
            f"run_ffmpeg({self.cmd('hang')!r}, output={self.out!r})\n"
        )
        parent = subprocess.Popen([sys.executable, "-c", parent_code])
        try:
            self.assertTrue(wait_for(lambda: os.path.exists(self.out + ".pid")))
            with open(self.out + ".pid") as f:
                pid = int(f.read())
            self.assertTrue(alive(pid))
            parent.send_signal(signal.SIGKILL)  # what Stash does on cancel
            parent.wait()
            self.assertTrue(wait_for(lambda: not alive(pid), 5), "ffmpeg outlived the killed plugin")
        finally:
            if parent.poll() is None:
                parent.kill()

    def test_encoders_of_missing_binary_is_empty(self):
        self.assertEqual(ffmpeg_run.encoders(os.path.join(self.tmp, "no-such-ffmpeg")), frozenset())

    def test_finalise_part(self):
        with open(self.out, "wb") as f:
            f.write(b"x")
        final = finalise_part(self.out)
        self.assertEqual(final, os.path.join(self.tmp, "out.mp4"))
        self.assertTrue(os.path.exists(final))
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
