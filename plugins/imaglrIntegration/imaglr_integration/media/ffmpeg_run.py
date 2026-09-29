# SPDX-License-Identifier: AGPL-3.0-only
"""Run ffmpeg/ffprobe: progress, cancellation, bounded stderr and safe partial files.

Stash cancels a task by SIGKILLing the plugin process, which would orphan a running ffmpeg
(docs/stash-plugin-facts.md §6). Children are therefore started so they die with us where possible:
- Linux: PR_SET_PDEATHSIG=SIGKILL, set in the child before exec. The signal fires when the *thread*
  that started the child exits, so run ffmpeg from the thread that waits for it (as run_ffmpeg does).
- macOS/BSD: no equivalent; the child gets its own process group so a cancel can kill all of it, but
  it survives a SIGKILL of the plugin and runs to completion.
- Windows: a new process group at below-normal priority; same limitation as macOS.
All platforms also support a cooperative `should_cancel()` callback, polled while ffmpeg runs.
"""

from __future__ import annotations

import collections
import functools
import os
import signal
import subprocess
import sys
import threading
import time

from .. import log

MAX_TAIL = 2000  # characters of ffmpeg stderr kept for error messages
PR_SET_PDEATHSIG = 1


class FfmpegError(Exception):
    def __init__(self, message: str, returncode: int | None = None, stderr_tail: str = ""):
        super().__init__(f"{message}: {stderr_tail[-300:]}" if stderr_tail.strip() else message)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class Cancelled(Exception):
    """The caller's should_cancel() returned true; ffmpeg was stopped and its output removed."""


@functools.lru_cache(maxsize=None)
def _prctl():
    """libc's prctl, loaded in the parent: dlopen after fork is not safe. CDLL(None) also finds musl's."""
    try:
        import ctypes

        return ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError, ImportError):
        return None


def _spawn_kwargs() -> dict:
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return {"creationflags": flags}
    prctl = _prctl() if sys.platform.startswith("linux") else None
    parent = os.getpid()

    def child_setup():  # runs in the child between fork and exec: keep it to plain syscalls
        try:
            os.nice(10)
        except OSError:
            pass
        if prctl is not None:
            prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
            if os.getppid() != parent:  # we died before prctl took effect
                os.kill(os.getpid(), signal.SIGKILL)

    return {"start_new_session": True, "preexec_fn": child_setup}


def _signal(proc: subprocess.Popen, sig) -> None:
    try:
        if os.name == "nt":
            proc.kill()  # TerminateProcess: Windows has no gentler signal for a console-less child
        else:
            os.killpg(proc.pid, sig)  # its own session, so pgid == pid
    except OSError:
        pass


def _stop(proc: subprocess.Popen) -> None:
    """Ask ffmpeg to stop (it exits cleanly on SIGTERM), then kill it if it does not."""
    for sig, wait in ((signal.SIGTERM, 5), (getattr(signal, "SIGKILL", signal.SIGTERM), 10)):
        if proc.poll() is not None:
            return
        _signal(proc, sig)
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            pass


def _remove(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _read_progress(stream, state: dict) -> None:
    try:
        for raw in iter(stream.readline, b""):
            line = raw.decode(errors="replace").strip()
            # out_time_ms is also in microseconds (a long-standing ffmpeg misnomer).
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    state["us"] = int(line.split("=", 1)[1])
                except ValueError:
                    pass
            elif line == "progress=end":
                state["end"] = True
    except (OSError, ValueError):  # pipe closed under us
        pass


def _read_tail(stream, chunks: collections.deque) -> None:
    try:
        for chunk in iter(lambda: stream.read(1024), b""):
            chunks.append(chunk)
    except (OSError, ValueError):
        pass


def run_ffmpeg(
    cmd: list[str],
    *,
    output: str | None = None,
    duration_s: float | None = None,
    progress_cb=None,
    progress_range: tuple[float, float] = (0.0, 1.0),
    should_cancel=None,
    timeout: float | None = None,
    poll_interval: float = 0.5,
) -> None:
    """Run cmd to completion. `output` (normally a `.part` path) is deleted if the run does not succeed.

    progress_cb(fraction) is called from this thread, scaled into progress_range, when the command has
    `-progress pipe:1` and duration_s is known. Raises FfmpegError on failure or timeout, Cancelled when
    should_cancel() returns true.
    """
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_spawn_kwargs()
    )
    state = {"us": None, "end": False}
    tail: collections.deque = collections.deque(maxlen=MAX_TAIL // 1024 + 2)
    readers = [
        threading.Thread(target=_read_progress, args=(proc.stdout, state), daemon=True),
        threading.Thread(target=_read_tail, args=(proc.stderr, tail), daemon=True),
    ]
    for t in readers:
        t.start()
    lo, hi = progress_range
    last = -1.0
    deadline = time.monotonic() + timeout if timeout else None

    def stderr_tail() -> str:
        return b"".join(tail).decode(errors="replace")[-MAX_TAIL:]

    ok = False
    try:
        while True:
            try:
                proc.wait(poll_interval)
                break
            except subprocess.TimeoutExpired:
                pass
            if progress_cb and duration_s and state["us"] is not None:
                value = lo + (hi - lo) * min(1.0, max(0.0, state["us"] / 1e6 / duration_s))
                if value - last >= 0.01:
                    last = value
                    progress_cb(value)
            if should_cancel is not None and should_cancel():
                raise Cancelled("cancelled")
            if deadline is not None and time.monotonic() > deadline:
                raise FfmpegError(f"ffmpeg timed out after {timeout:.0f} s", None, stderr_tail())
        for t in readers:
            t.join(5)
        if proc.returncode != 0:
            raise FfmpegError(f"ffmpeg exit {proc.returncode}", proc.returncode, stderr_tail())
        if progress_cb and (state["end"] or duration_s):
            progress_cb(hi)
        if stderr_tail().strip():
            log.debug(f"ffmpeg stderr: {stderr_tail()[-500:]}")
        ok = True
    finally:
        if not ok:
            _stop(proc)
            _remove(output)
            for t in readers:
                t.join(5)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass


def run_tool(cmd: list[str], timeout: float = 60) -> bytes:
    """Run a short command (ffprobe, `ffmpeg -encoders`) and return its stdout."""
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_spawn_kwargs()
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(proc)
        proc.communicate()
        raise FfmpegError(f"{os.path.basename(cmd[0])} timed out after {timeout:.0f} s") from None
    except BaseException:
        _stop(proc)
        raise
    if proc.returncode != 0:
        tail = err.decode(errors="replace")[-MAX_TAIL:]
        raise FfmpegError(f"{os.path.basename(cmd[0])} exit {proc.returncode}", proc.returncode, tail)
    return out


@functools.lru_cache(maxsize=None)
def encoders(ffmpeg: str) -> frozenset:
    """Names of the encoders this ffmpeg build has (e.g. whether libwebp is present)."""
    try:
        out = run_tool([ffmpeg, "-hide_banner", "-encoders"], timeout=30).decode(errors="replace")
    except (OSError, FfmpegError):
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS" and parts[1] != "=":
            names.add(parts[1])
    return frozenset(names)


def finalise_part(part: str) -> str:
    """Rename foo.mp4.part -> foo.mp4 atomically (replacing any previous foo.mp4)."""
    final = part[: -len(".part")] if part.endswith(".part") else part
    os.replace(part, final)
    return final
