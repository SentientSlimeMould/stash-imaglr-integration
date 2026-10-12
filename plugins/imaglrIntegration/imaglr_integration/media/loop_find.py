# SPDX-License-Identifier: AGPL-3.0-only
"""Finding where a clip loops without a jump: In/Out pairs near the user's own where the frame at Out looks
like the frame at In, and the motion carries through the join.

Stash's ffmpeg decodes two short windows (around In and around Out) to tiny grey frames; this module scores
every (In, Out) pair in pure Python, standard library only. The picture is weighed by what moves: pixels that
barely change across the windows are left out, so a still background cannot hide a mismatch in the part that
matters. A loop must also move (a frozen picture would "loop" perfectly) and must not contain a hard cut, which
a coarse pass over the whole range checks step by step.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import compress
from operator import sub
from statistics import median

PROBE_FPS = 15  # the ladder's top rate: candidate times sit on this grid
PROBE_SIZE = (64, 36)  # the scored picture
BRIDGE_FPS = 5  # the coarse pass over the whole range, for the motion and cut checks
BRIDGE_SIZE = (32, 18)
SEAM_HALF = 2  # frames either side of the join that must match too: motion, not just a pose
NEAR_BIAS = 0.5  # score points per second away from the user's own In and Out
SHORT_BIAS = 0.1  # when Out is free ("from In"), score points per second of loop: a clean short loop beats a long one
MIN_LOOP_SECONDS = 1.0
DISTINCT_SECONDS = 0.3  # candidates closer than this in both In and Out are the same one
MOVING_FRACTION = 0.5  # the most-changing half of the pixels is scored (at least MIN_PIXELS of them)
MIN_PIXELS = 256
MOTION_FLOOR = 0.75  # mean step (0-255) below which the loop is a frozen picture
CUT_RATIO = 6.0  # a step this many times the loop's median step is a cut
SEAMLESS_BELOW = 4.0  # seam scores (0-255) that read as "seamless" / "close"; above is a visible join
CLOSE_BELOW = 10.0


@dataclass
class Window:
    """Frames decoded from `start` seconds on, one every 1/fps seconds."""
    start: float
    frames: list
    fps: float = PROBE_FPS

    def time(self, i: int) -> float:
        return self.start + i / self.fps


@dataclass
class Candidate:
    in_s: float
    out_s: float
    seam: float  # how different the join's frames are, 0-255 (lower is better)
    score: float  # seam plus the distance from the user's own points

    @property
    def quality(self) -> str:
        return "seamless" if self.seam < SEAMLESS_BELOW else "close" if self.seam < CLOSE_BELOW else "visible join"

    def as_dict(self) -> dict:
        return {"in_s": round(self.in_s, 3), "out_s": round(self.out_s, 3), "score": round(self.score, 2),
                "seam": round(self.seam, 2), "quality": self.quality}


def split_frames(raw: bytes, size: tuple[int, int] = PROBE_SIZE) -> list:
    """Raw 8-bit grey video (ffmpeg's rawvideo, format=gray) as a list of frames, each `w*h` bytes."""
    n = size[0] * size[1]
    return [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)]


def mad(a: bytes, b: bytes) -> float:
    """Mean absolute difference between two same-sized frames, 0-255."""
    return sum(map(abs, map(sub, a, b))) / len(a) if a else 0.0


def moving_mask(frames: list) -> list:
    """Which pixels change across these frames: a 0/1 mask over the most-changing MOVING_FRACTION of them
    (judged by the mean absolute step between consecutive frames), never fewer than MIN_PIXELS."""
    if len(frames) < 2:
        return [1] * len(frames[0]) if frames else []
    n = len(frames[0])
    total = [0] * n
    for a, b in zip(frames, frames[1:]):
        for p, d in enumerate(map(abs, map(sub, a, b))):
            total[p] += d
    keep = max(min(MIN_PIXELS, n), int(n * MOVING_FRACTION))
    ranked = sorted(range(n), key=total.__getitem__, reverse=True)
    chosen = set(ranked[:keep])
    return [1 if p in chosen else 0 for p in range(n)]


def select(frames: list, mask: list) -> list:
    return [bytes(compress(f, mask)) for f in frames]


def steps(frames: list) -> list:
    """How much each frame differs from the one before it."""
    return [mad(a, b) for a, b in zip(frames, frames[1:])]


def loop_is_live(bridge: Window, in_s: float, out_s: float) -> bool:
    """True when the range moves (not a frozen picture) and holds no hard cut, judged on the coarse pass.
    Without a bridge that covers the range, the loop is given the benefit of the doubt."""
    if not bridge.frames:
        return True
    first = max(0, int((in_s - bridge.start) * bridge.fps))
    last = min(len(bridge.frames) - 1, int((out_s - bridge.start) * bridge.fps))
    inside = steps(bridge.frames[first:last + 1])
    if len(inside) < 2:
        return True
    if sum(inside) / len(inside) < MOTION_FLOOR:
        return False
    return max(inside) <= CUT_RATIO * max(median(inside), MOTION_FLOOR)


def find_candidates(window_a: Window, window_b: Window, user_in: float, user_out: float, *,
                    bridge: Window | None = None, limit: int = 3, near_out: bool = True) -> list:
    """The best (In, Out) pairs with In from window A and Out from window B: the frame at Out (exclusive) looks
    like the frame at In, and so do the frames either side. Best first, at most `limit`, no near-duplicates.
    Staying near the user's own points counts against a pair; with `near_out` off (the "from In" search, where
    Out is free) the user's Out is no pull and a shorter loop wins between equally clean joins."""
    if len(window_a.frames) < 2 * SEAM_HALF + 1 or len(window_b.frames) < 2 * SEAM_HALF + 1:
        return []
    mask = moving_mask(window_a.frames + window_b.frames)
    a, b = select(window_a.frames, mask), select(window_b.frames, mask)
    k = SEAM_HALF
    pairs = [(i, j) for i in range(k, len(a) - k) for j in range(k, len(b) - k)
             if window_b.time(j) - window_a.time(i) >= MIN_LOOP_SECONDS]
    if not pairs:
        return []
    d: dict = {}
    for i, j in pairs:
        for o in range(-k, k + 1):
            key = (i + o, j + o)
            if key not in d:
                d[key] = mad(a[i + o], b[j + o])
    scored = []
    for i, j in pairs:
        seam = sum(d[(i + o, j + o)] for o in range(-k, k + 1)) / (2 * k + 1)
        t_in, t_out = window_a.time(i), window_b.time(j)
        if near_out:
            score = seam + NEAR_BIAS * (abs(t_in - user_in) + abs(t_out - user_out))
        else:
            score = seam + NEAR_BIAS * abs(t_in - user_in) + SHORT_BIAS * (t_out - t_in)
        scored.append(Candidate(t_in, t_out, seam, score))
    scored.sort(key=lambda c: c.score)
    kept: list = []
    for c in scored:
        if any(abs(c.in_s - o.in_s) <= DISTINCT_SECONDS and abs(c.out_s - o.out_s) <= DISTINCT_SECONDS for o in kept):
            continue
        if bridge is not None and not loop_is_live(bridge, c.in_s, c.out_s):
            continue
        kept.append(c)
        if len(kept) >= limit:
            break
    return kept


def search_windows(mode: str, in_s: float, out_s: float, duration: float | None) -> tuple:
    """(start, end) of the In window and of the Out window for a search mode, clamped to the video.
    "near": within 2 s of each point. "from_in": In within 1 s, Out anywhere from In + 1 s to Out (or In + 10 s
    when the clip is shorter than a second), for markers that only mark a start."""
    end = duration if duration and duration > 0 else float("inf")
    if mode == "from_in":
        a = (in_s - 1.0, in_s + 1.0)
        far = out_s if out_s - in_s >= MIN_LOOP_SECONDS else in_s + 10.0
        b = (in_s + MIN_LOOP_SECONDS, far)
    else:
        a = (in_s - 2.0, in_s + 2.0)
        b = (out_s - 2.0, out_s + 2.0)
    def clamp(w):  # starts snap to the probe grid, so a frame in one window can match one in the other exactly
        start = max(0.0, min(w[0], end))
        start = int(start * PROBE_FPS) / PROBE_FPS
        return start, max(start, min(w[1], end))
    return clamp(a), clamp(b)
