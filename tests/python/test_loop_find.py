# SPDX-License-Identifier: AGPL-3.0-only
"""The seamless-loop finder's scoring, on synthetic byte frames (no ffmpeg)."""
import random
import unittest

from imaglr_integration.media import loop_find as lf

W, H = 16, 8  # tiny frames: the scorer takes any size
N = W * H


def frame(fn):
    return bytes(max(0, min(255, int(fn(x, y)))) for y in range(H) for x in range(W))


def periodic(t, period=1.2):
    """A bright blob circling the frame once per `period` seconds, on a static gradient."""
    import math
    cx, cy = W / 2 + 5 * math.cos(2 * math.pi * t / period), H / 2 + 2.5 * math.sin(2 * math.pi * t / period)
    return frame(lambda x, y: 40 + 6 * x + (180 if (x - cx) ** 2 + (y - cy) ** 2 < 4 else 0))


def window(start, end, fn, fps=lf.PROBE_FPS):
    n = int(round((end - start) * fps))
    return lf.Window(start, [fn(start + i / fps) for i in range(n)], fps)


class ScoringTest(unittest.TestCase):
    def test_periodic_footage_yields_whole_cycles(self):
        a, b = window(0.0, 2.0, periodic), window(3.0, 6.0, periodic)
        bridge = window(0.0, 6.0, periodic, fps=lf.BRIDGE_FPS)
        found = lf.find_candidates(a, b, 0.6, 4.5, bridge=bridge)
        self.assertTrue(found)
        for c in found:
            cycles = (c.out_s - c.in_s) / 1.2
            self.assertAlmostEqual(cycles, round(cycles), delta=1 / lf.PROBE_FPS / 1.2 + 1e-9, msg=c)
            self.assertEqual(c.quality, "seamless", c)
            self.assertGreaterEqual(c.out_s - c.in_s, lf.MIN_LOOP_SECONDS)
        self.assertEqual(found, sorted(found, key=lambda c: c.score))
        # the user's own points pull: the best is the whole-cycle pair nearest 0.6 → 4.5 (3.6 s = three cycles)
        self.assertAlmostEqual(found[0].out_s - found[0].in_s, 3.6, delta=0.1)

    def test_from_in_prefers_a_short_clean_loop_over_one_near_the_users_out(self):
        a, b = window(0.0, 2.0, periodic), window(1.0, 12.0, periodic)
        near = lf.find_candidates(a, b, 0.6, 11.5, bridge=window(0.0, 12.0, periodic, fps=lf.PROBE_FPS))
        free = lf.find_candidates(a, b, 0.6, 11.5, bridge=window(0.0, 12.0, periodic, fps=lf.PROBE_FPS), near_out=False)
        self.assertGreater(near[0].out_s - near[0].in_s, 9.0)  # pulled towards the user's Out at 11.5
        self.assertAlmostEqual(free[0].out_s - free[0].in_s, 1.2, delta=0.1)  # one cycle: the shortest clean loop
        self.assertTrue(all(c.quality == "seamless" for c in free))

    def test_candidates_are_distinct(self):
        a, b = window(0.0, 2.0, periodic), window(3.0, 6.0, periodic)
        found = lf.find_candidates(a, b, 0.6, 4.5)
        for i, c in enumerate(found):
            for o in found[i + 1:]:
                self.assertTrue(abs(c.in_s - o.in_s) > lf.DISTINCT_SECONDS or abs(c.out_s - o.out_s) > lf.DISTINCT_SECONDS, (c, o))
        self.assertLessEqual(len(found), 3)

    def test_a_cut_or_a_frozen_picture_is_not_a_loop(self):
        def with_cut(t):
            return periodic(t) if t < 2.5 else frame(lambda x, y: 255 - 6 * x)  # a different shot from 2.5 s on
        # (at the coarse rate this blob would leap a sixth of a circle per step; real motion is gentler, so the
        # bridge here is sampled at the probe rate)
        bridge = window(0.0, 6.0, with_cut, fps=lf.PROBE_FPS)
        self.assertTrue(lf.loop_is_live(bridge, 0.2, 2.2))
        self.assertFalse(lf.loop_is_live(bridge, 1.0, 4.0))  # straddles the cut
        frozen = lf.Window(0.0, [frame(lambda x, y: 100)] * 30, lf.BRIDGE_FPS)
        self.assertFalse(lf.loop_is_live(frozen, 0.0, 5.0))
        self.assertTrue(lf.loop_is_live(lf.Window(0.0, [], lf.BRIDGE_FPS), 0.0, 5.0))  # no bridge: benefit of the doubt
        a, b = window(0.0, 2.0, with_cut), window(3.0, 6.0, with_cut)
        self.assertEqual(lf.find_candidates(a, b, 0.6, 4.5, bridge=bridge), [])

    def test_moving_pixels_outweigh_a_noisy_background(self):
        rnd = random.Random(7)

        def noisy(t):
            base = periodic(t)
            return bytes(min(255, max(0, v + rnd.randint(-12, 12))) if x >= 8 else v
                         for i, v in enumerate(base) for x in [i % W])
        frames = [noisy(i / lf.PROBE_FPS) for i in range(45)]
        mask = lf.moving_mask(frames)
        # the blob's path (left of x=8 it is the only thing that changes) is in the mask
        path = {i for i in range(N) if any(abs(f[i] - g[i]) > 60 for f, g in zip(frames, frames[1:]))}
        self.assertTrue(path)
        self.assertTrue(all(mask[i] for i in path if i % W < 8))
        self.assertEqual(sum(mask), max(lf.MIN_PIXELS if lf.MIN_PIXELS < N else N, int(N * lf.MOVING_FRACTION)))

    def test_short_windows_give_nothing(self):
        a = lf.Window(0.0, [periodic(0)] * 3)
        self.assertEqual(lf.find_candidates(a, a, 0.0, 1.0), [])

    def test_split_frames_and_mad(self):
        raw = bytes(range(8)) * 3
        self.assertEqual(lf.split_frames(raw, (4, 2)), [bytes(range(8))] * 3)
        self.assertEqual(lf.split_frames(raw + b"\x00", (4, 2)), [bytes(range(8))] * 3)  # a partial frame is dropped
        self.assertEqual(lf.mad(b"\x00\x10", b"\x10\x00"), 16.0)


class WindowsTest(unittest.TestCase):
    def test_near_and_from_in_windows_clamp_and_snap(self):
        (a0, a1), (b0, b1) = lf.search_windows("near", 1.0, 7.3, 20.0)
        self.assertEqual((a0, a1), (0.0, 3.0))  # clamped at the start
        self.assertAlmostEqual(b0, int(5.3 * 15) / 15)  # snapped to the 1/15 s grid
        self.assertAlmostEqual(b1, 9.3)
        (a0, a1), (b0, b1) = lf.search_windows("near", 18.5, 19.5, 20.0)
        self.assertEqual((a1, b1), (20.0, 20.0))  # clamped at the end
        (a0, a1), (b0, b1) = lf.search_windows("from_in", 3.0, 7.3, None)
        self.assertEqual((a0, a1), (2.0, 4.0))
        self.assertEqual((b0, b1), (4.0, 7.3))
        (a0, a1), (b0, b1) = lf.search_windows("from_in", 3.0, 3.2, None)  # a start-only marker: up to In + 10 s
        self.assertEqual((b0, b1), (4.0, 13.0))


if __name__ == "__main__":
    unittest.main()
