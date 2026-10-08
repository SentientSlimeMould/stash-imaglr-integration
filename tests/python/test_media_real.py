# SPDX-License-Identifier: AGPL-3.0-only
"""Media processing against a real ffmpeg/ffprobe. Skipped when they are not on PATH; they run in the
stashapp/stash image (ffmpeg 8), which is the runtime that matters."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from fractions import Fraction

from imaglr_integration.media import ffmpeg_cmd as fc
from imaglr_integration.media.ffmpeg_run import Cancelled, FfmpegError
from imaglr_integration.media.image_inspect import inspect_image
from imaglr_integration.media.image_plan import plan_image
from imaglr_integration.media.image_process import ImageTooLarge, process_image
from imaglr_integration.media.probe import probe
from imaglr_integration.media.video_export import UnsupportedMedia, VideoSettings, export_clip, gif_to_mp4, grab_frame

from . import media_fixtures as mf

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
LIMIT = int(40 * 1024 * 1024 * 0.95)
# Stored pixels for orientation o are the upright image with the inverse transform applied.
INVERSE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 8, 7: 7, 8: 6}


def ff(*args):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True, stderr=subprocess.PIPE)


def has_encoder(name):
    """Some ffmpeg builds (Homebrew's, for one) lack libwebp; Stash's image has it. False without ffmpeg."""
    if not FFMPEG:
        return False
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return f" {name} " in out


def ffprobe(path, *entries):
    args = list(entries) or ["-show_streams", "-show_format"]
    out = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", *args, path], check=True,
                         capture_output=True).stdout
    return json.loads(out)


def video_stream(path):
    return next(s for s in ffprobe(path)["streams"] if s["codec_type"] == "video")


def raw_rgb(path, w, h):
    """The image as a viewer sees it, scaled to w x h, as rgb24 bytes. Converting to RGB before scaling
    keeps 4:2:0 chroma from skewing heavy downscales."""
    return subprocess.run(
        [FFMPEG, "-v", "error", "-i", path, "-frames:v", "1", "-vf", f"format=rgb24,scale={w}:{h}", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], check=True, capture_output=True
    ).stdout


def mean_diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)
    return path


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe not on PATH")
class RealMediaTest(unittest.TestCase):
    def setUp(self):
        # The plugin log goes to stderr; ffmpeg's complaints about the fixtures' junk trailers are expected.
        quiet = contextlib.redirect_stderr(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out")
        self.settings = VideoSettings(FFMPEG, FFPROBE, preset="veryfast")  # ultrafast would be Baseline

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def prepare(self, src, crop="original", limit=LIMIT, base="photo"):
        info = inspect_image(src, FFPROBE)
        plan = plan_image(info, crop, limit)
        return plan, process_image(src, self.out, base, plan, info, crop, 0.5, limit, ffmpeg=FFMPEG)

    def assert_no_leftovers(self, directory):
        self.assertEqual([n for n in os.listdir(directory) if n.endswith((".part", ".strip", ".source.png"))], [])


class ImageTest(RealMediaTest):
    def make_orient6_jpeg(self):
        """dev/make_media.py's photo_gps_orient6.jpg: upright 1200x1600, stored sideways, EXIF GPS + XMP + COM."""
        upright = self.path("upright.png")
        ff("-f", "lavfi", "-i", "testsrc=size=1200x1600", "-frames:v", "1", upright)
        stored = self.path("stored.jpg")
        ff("-i", upright, "-vf", "transpose=cclock", "-q:v", "3", stored)
        write(stored, mf.add_jpeg_metadata(read(stored), orientation=6))
        return upright, stored

    def test_stripped_copy_leaves_ffmpeg_nothing_to_rotate(self):
        # ffmpeg versions differ on whether -noautorotate stops EXIF rotation of images (8.0 yes, 8.1 no),
        # so the re-encode feeds ffmpeg a stripped copy (no EXIF) and applies the orientation itself.
        _, stored = self.make_orient6_jpeg()
        from imaglr_integration.media import metadata_strip
        metadata_strip.strip_file(stored, self.path("stripped.jpg"))
        self.assertEqual(inspect_image(self.path("stripped.jpg")).orientation, 1)
        ff("-i", self.path("stripped.jpg"), "-frames:v", "1", self.path("n.png"))
        self.assertEqual(inspect_image(self.path("n.png")).display_size, (1600, 1200))

    def test_orient6_jpeg_comes_out_upright_and_clean(self):
        upright, stored = self.make_orient6_jpeg()
        self.assertTrue(all(s in read(stored) for s in (b"Exif", mf.XMP_NS, mf.COMMENT)))
        plan, res = self.prepare(stored)
        self.assertEqual(plan.action, "reencode")
        self.assertEqual((res.width, res.height, res.mime), (1200, 1600, "image/jpeg"))
        self.assertEqual(video_stream(res.path)["width"], 1200)
        data = read(res.path)
        self.assertEqual(mf.secrets_in(data), [])
        self.assertNotIn(b"Lavc", data)
        self.assertNotIn(b"MOTION-PHOTO-TRAILER", data)
        out_info = inspect_image(res.path)
        self.assertEqual((out_info.width, out_info.height, out_info.orientation), (1200, 1600, 1))
        good = mean_diff(raw_rgb(res.path, 30, 40), raw_rgb(upright, 30, 40))
        self.assertLess(good, 12)
        self.assert_no_leftovers(self.out)

    def test_every_exif_orientation_is_applied_once(self):
        upright = self.path("upright.png")
        ff("-f", "lavfi", "-i", "testsrc2=size=48x32", "-frames:v", "1", "-pix_fmt", "rgb24", upright)
        want = raw_rgb(upright, 48, 32)
        for o in range(1, 9):
            with self.subTest(orientation=o):
                stored = self.path(f"o{o}.png")
                vf = ",".join(fc.ORIENTATION_FILTERS.get(INVERSE[o], ["null"]))
                ff("-i", upright, "-vf", vf, "-pix_fmt", "rgb24", stored)
                jpeg = self.path(f"o{o}.jpg")
                ff("-i", stored, "-q:v", "2", jpeg)  # from the untagged PNG: newer ffmpeg would rotate a tagged one
                write(stored, mf.add_png_metadata(read(stored), orientation=o))
                _, res = self.prepare(stored, base=f"png{o}")
                self.assertEqual((res.width, res.height), (48, 32))
                self.assertEqual(raw_rgb(res.path, 48, 32), want)  # PNG is lossless: exact match
                write(jpeg, mf.add_jpeg_metadata(read(jpeg), orientation=o, extras=False))
                _, res = self.prepare(jpeg, base=f"jpg{o}")
                self.assertEqual((res.width, res.height), (48, 32))
                self.assertLess(mean_diff(raw_rgb(res.path, 48, 32), want), 12)

    def test_png_strip_removes_text_and_exif_and_keeps_alpha(self):
        src = self.path("t.png")
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240,format=rgba,colorchannelmixer=aa=0.5", "-frames:v", "1", src)
        write(src, mf.add_png_metadata(read(src)))
        plan, res = self.prepare(src)
        self.assertEqual(plan.action, "strip")
        self.assertEqual(mf.secrets_in(read(res.path)), [])
        self.assertEqual(video_stream(res.path)["pix_fmt"], "rgba")
        self.assertEqual(raw_rgb(res.path, 32, 24), raw_rgb(src, 32, 24))
        plan, res = self.prepare(src, crop="1:1", base="cropped")  # re-encode path keeps alpha too
        self.assertEqual((plan.action, res.width, res.height), ("reencode", 240, 240))
        self.assertEqual(video_stream(res.path)["pix_fmt"], "rgba")
        self.assertEqual(mf.secrets_in(read(res.path)), [])

    def test_jpeg_strip_decodes(self):
        src = self.path("plain.jpg")
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240", "-frames:v", "1", src)
        write(src, mf.add_jpeg_metadata(read(src)))
        plan, res = self.prepare(src)
        self.assertEqual(plan.action, "strip")
        self.assertEqual(mf.secrets_in(read(res.path)), [])
        self.assertEqual(raw_rgb(res.path, 32, 24), raw_rgb(src, 32, 24))

    def test_animated_gif_stays_animated_gif(self):
        src = self.path("a.gif")
        ff("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=2", "-vf",
           "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0", src)
        write(src, mf.add_gif_metadata(read(src)))
        plan, res = self.prepare(src)
        self.assertEqual((plan.action, res.mime), ("strip", "image/gif"))
        self.assertEqual(mf.secrets_in(read(res.path)), [])
        count = ffprobe(res.path, "-count_frames", "-show_streams")["streams"][0]["nb_read_frames"]
        self.assertEqual(int(count), 20)
        self.assertTrue(inspect_image(res.path).is_animated)

    def test_animated_webp_stays_animated_webp(self):
        src = self.path("a.webp")
        try:
            ff("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=1", "-loop", "0", "-c:v", "libwebp_anim",
               src)
        except subprocess.CalledProcessError:
            self.skipTest("this ffmpeg cannot write animated WebP")
        write(src, mf.add_webp_metadata(read(src), orientation=1))
        plan, res = self.prepare(src)
        self.assertEqual((plan.action, res.mime, res.width, res.height), ("strip", "image/webp", 160, 90))
        data = read(res.path)
        self.assertEqual(mf.secrets_in(data), [])
        self.assertTrue(inspect_image(res.path).is_animated)
        original = [c for c in mf.webp_chunks(read(src)) if c[0] == b"ANMF"]
        self.assertEqual([c for c in mf.webp_chunks(data) if c[0] == b"ANMF"], original)
        if shutil.which("vipsheader"):  # ffmpeg 8 cannot decode animated WebP; libvips (in the Stash image) can
            pages = subprocess.run(["vipsheader", "-f", "n-pages", res.path], check=True, capture_output=True)
            self.assertEqual(int(pages.stdout), 10)

    @unittest.skipUnless(has_encoder("libwebp"), "this ffmpeg can't encode WebP fixtures")
    def test_still_webp_strip_and_reencode(self):
        src = self.path("s.webp")
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240,format=rgba,colorchannelmixer=aa=0.5", "-frames:v", "1",
           "-c:v", "libwebp", "-lossless", "1", src)
        write(src, mf.add_webp_metadata(read(src), orientation=1))
        plan, res = self.prepare(src)
        self.assertEqual(plan.action, "strip")
        self.assertEqual(mf.secrets_in(read(res.path)), [])
        self.assertEqual(raw_rgb(res.path, 32, 24), raw_rgb(src, 32, 24))
        plan, res = self.prepare(src, crop="4:5", base="crop")
        self.assertEqual((plan.action, res.mime, res.width, res.height), ("reencode", "image/webp", 192, 240))
        self.assertEqual(video_stream(res.path)["pix_fmt"], "yuva420p")

    def test_other_formats_convert(self):
        made = []
        for name, args in (("p.tiff", []), ("p.bmp", []), ("p.avif", [])):
            try:
                ff("-f", "lavfi", "-i", "testsrc=size=320x240", "-frames:v", "1", *args, self.path(name))
                made.append(name)
            except subprocess.CalledProcessError:
                pass
        self.assertIn("p.tiff", made)
        for name in made:
            with self.subTest(name):
                plan, res = self.prepare(self.path(name), base=name.replace(".", "_"))
                self.assertEqual((plan.action, res.mime, res.width, res.height), ("convert", "image/jpeg", 320, 240))
                self.assertEqual(video_stream(res.path)["codec_name"], "mjpeg")
        self.assert_no_leftovers(self.out)

    def test_size_guard_png_to_jpeg_then_step_down_then_give_up(self):
        noise = "noise=alls=100:allf=t"
        png = self.path("noise.png")
        ff("-f", "lavfi", "-i", f"testsrc2=size=900x900,{noise}", "-frames:v", "1", png)
        limit = 1_000_000
        self.assertGreater(os.path.getsize(png), limit)
        plan, res = self.prepare(png, limit=limit)
        self.assertEqual((plan.out_format, res.mime), ("PNG", "image/jpeg"))
        self.assertLessEqual(res.bytes, limit)

        big = self.path("big.jpg")
        ff("-f", "lavfi", "-i", f"testsrc2=size=7000x5000,{noise}", "-frames:v", "1", "-q:v", "2", big)
        plan, res = self.prepare(big, limit=3_000_000, base="big")
        self.assertLessEqual(res.bytes, 3_000_000)
        self.assertLessEqual(max(res.width, res.height), 6000)
        self.assertEqual((video_stream(res.path)["width"], video_stream(res.path)["height"]), (res.width, res.height))

        with self.assertRaises(ImageTooLarge):
            self.prepare(png, limit=1000, base="tiny")
        self.assert_no_leftovers(self.out)
        self.assertFalse(any(n.startswith("tiny") for n in os.listdir(self.out)))


class VideoTest(RealMediaTest):
    def make_source(self, path, seconds=4, size="640x360", rate=30, audio=True):
        meta = self.path("meta.txt")
        with open(meta, "w") as f:
            f.write(
                ";FFMETADATA1\ntitle=Metadata title to strip\ncomment=Metadata comment to strip\n"
                "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=Chapter one\n"
                "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=Chapter two\n"
            )
        args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}"]
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"] if audio else []
        n = 2 if audio else 1
        args += ["-i", meta, "-map", "0:v"] + (["-map", "1:a"] if audio else [])
        args += ["-map_metadata", str(n), "-map_chapters", str(n), "-metadata", "location=+51.5074-000.1278/"]
        args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        args += ["-c:a", "aac"] if audio else []
        ff(*args, path)
        return path

    def test_clip_export_with_cut_and_crop_strips_everything(self):
        src = self.make_source(self.path("src.mp4"))
        before = ffprobe(src, "-show_format", "-show_chapters")
        self.assertEqual(len(before["chapters"]), 2)
        self.assertIn("title", before["format"]["tags"])
        progress = []
        res = export_clip(src, self.out, title="My Clip!", in_s=1.0, out_s=3.0, aspect="1:1",
                          settings=self.settings, progress_cb=progress.append)
        self.assertEqual(os.path.basename(res.path), "my-clip_1_0-3_0.mp4")
        self.assertTrue(progress)
        self.assertEqual(progress[-1], 1.0)
        after = ffprobe(res.path, "-show_format", "-show_chapters", "-show_streams")
        self.assertEqual(after["chapters"], [])
        tags = {k.lower() for k in (after["format"].get("tags") or {})}
        self.assertFalse(tags & {"title", "comment", "location", "location-eng", "com.apple.quicktime.location.iso6709"})
        v = next(s for s in after["streams"] if s["codec_type"] == "video")
        a = next(s for s in after["streams"] if s["codec_type"] == "audio")
        self.assertEqual((v["codec_name"], v["pix_fmt"], v["profile"]), ("h264", "yuv420p", "High"))
        self.assertEqual((v["width"], v["height"], res.width, res.height), (360, 360, 360, 360))
        self.assertEqual((a["codec_name"], a["sample_rate"], a["channels"]), ("aac", "48000", 2))
        self.assertAlmostEqual(float(after["format"]["duration"]), 2.0, delta=0.15)
        head = read(res.path)[:4096]  # +faststart: moov before mdat
        self.assertNotEqual(head.find(b"moov"), -1)
        self.assertTrue(head.find(b"mdat") == -1 or head.find(b"moov") < head.find(b"mdat"))
        self.assertTrue(res.thumb and os.path.exists(res.thumb))
        self.assert_no_leftovers(self.out)

    def test_mute_and_scale_down(self):
        src = self.make_source(self.path("src.mp4"), seconds=2, size="1280x720", rate=60)
        settings = VideoSettings(FFMPEG, FFPROBE, preset="ultrafast", max_long_edge=640)
        res = export_clip(src, self.out, title="t", in_s=0, out_s=1.5, mute=True, settings=settings)
        streams = ffprobe(res.path)["streams"]
        self.assertTrue(all(s["codec_type"] != "audio" for s in streams))
        self.assertEqual((streams[0]["width"], streams[0]["height"]), (640, 360))
        self.assertEqual(Fraction(streams[0]["avg_frame_rate"]), 60)

    def test_size_guard_two_pass(self):
        src = self.make_source(self.path("src.mp4"), seconds=3, size="1280x720", audio=False)
        # 1 MB for 3 s is about 2600 kbps: enough for H.264 at 720p, so the first encode runs at crf 1, overshoots,
        # and the two-pass encode at that bitrate takes over
        settings = VideoSettings(FFMPEG, FFPROBE, preset="ultrafast", crf=1, max_video_mb=1.0)
        res = export_clip(src, self.out, title="t", in_s=0, out_s=3, mute=True, settings=settings)
        self.assertLessEqual(res.bytes, 1.0 * 1024 * 1024 * 1.1)  # two-pass targets the limit
        self.assertFalse([n for n in os.listdir(self.out) if n.startswith("passlog")])
        self.assertEqual(res.note, f"H.264 · {res.bytes / 1048576:.1f} MB · 1280 px")
        self.assertEqual(ffprobe(res.path)["streams"][0]["width"], 1280)
        self.assert_no_leftovers(self.out)

    def test_long_clip_keeps_its_size_with_hevc(self):
        if not has_encoder("libx265"):
            self.skipTest("this ffmpeg has no libx265")
        src = self.make_source(self.path("src.mp4"), seconds=4, size="1920x1080", audio=False)
        # 4 s in 0.35 MB is about 700 kbps: too thin for H.264 at any size above 640 px, fine for H.265 at 854
        settings = VideoSettings(FFMPEG, FFPROBE, preset="ultrafast", max_video_mb=0.35, hevc_available=True)
        res = export_clip(src, self.out, title="t", in_s=0, out_s=4, mute=True, settings=settings)
        v = ffprobe(res.path)["streams"][0]
        self.assertEqual((v["codec_name"], v["codec_tag_string"], v["width"], v["height"]), ("hevc", "hvc1", 854, 480))
        self.assertEqual((res.width, res.height), (854, 480))
        self.assertEqual(res.note, f"H.265 · {res.bytes / 1048576:.1f} MB · 854 px")
        self.assertLessEqual(res.bytes, 0.35 * 1024 * 1024 * 1.1)
        self.assert_no_leftovers(self.out)

    def test_long_clip_without_hevc_steps_the_picture_down(self):
        src = self.make_source(self.path("src.mp4"), seconds=4, size="1920x1080", audio=False)
        settings = VideoSettings(FFMPEG, FFPROBE, preset="ultrafast", max_video_mb=0.35, allow_hevc=False)
        res = export_clip(src, self.out, title="t", in_s=0, out_s=4, mute=True, settings=settings)
        v = ffprobe(res.path)["streams"][0]
        self.assertEqual((v["codec_name"], v["width"], v["height"]), ("h264", 640, 360))
        self.assertEqual(res.note, f"H.264 · {res.bytes / 1048576:.1f} MB · 640 px")

    def test_failure_leaves_no_part(self):
        src = self.make_source(self.path("src.mp4"), seconds=2)
        info = probe(FFPROBE, src)
        broken = write(self.path("broken.mp4"), b"\0" * 5000)
        with self.assertRaises(FfmpegError):
            export_clip(broken, self.out, title="t", in_s=0, out_s=1, settings=self.settings, probe_info=info)
        self.assertEqual(os.listdir(self.out), [])

    def test_should_cancel_stops_the_export(self):
        src = self.make_source(self.path("src.mp4"), seconds=6, size="1920x1080")
        slow = VideoSettings(FFMPEG, FFPROBE, preset="veryslow")
        start = time.monotonic()
        with self.assertRaises(Cancelled):
            export_clip(src, self.out, title="t", in_s=0, out_s=6, settings=slow,
                        should_cancel=lambda: time.monotonic() - start > 1.0)
        self.assertLess(time.monotonic() - start, 20)
        self.assertEqual(os.listdir(self.out), [])

    def test_frame_grab_then_image_rules(self):
        src = self.make_source(self.path("src.mp4"), seconds=2)
        frame = grab_frame(src, 1.0, os.path.join(self.tmp, "f", "frame.jpg"), FFMPEG)
        self.assertEqual(frame, os.path.join(self.tmp, "f", "frame.jpg"))
        info = inspect_image(frame)
        self.assertEqual((info.format, info.width, info.height, info.orientation), ("JPEG", 640, 360, 1))
        plan, res = self.prepare(frame, crop="1:1", base="still")
        self.assertEqual((res.width, res.height), (360, 360))
        self.assertNotIn(b"Lavc", read(res.path))
        with self.assertRaises(FfmpegError):
            grab_frame(src, 60.0, self.path("past-end.jpg"), FFMPEG)
        self.assertFalse(os.path.exists(self.path("past-end.jpg.part")))

    def test_gif_to_mp4(self):
        gif = self.path("a.gif")
        ff("-f", "lavfi", "-i", "testsrc2=size=301x201:rate=10:duration=1", "-loop", "0", gif)
        res = gif_to_mp4(gif, self.out, "a", self.settings)
        v = video_stream(res.path)
        self.assertEqual((v["codec_name"], v["width"], v["height"]), ("h264", 300, 200))
        res = gif_to_mp4(gif, self.out, "sq", self.settings, aspect="1:1")
        self.assertEqual((video_stream(res.path)["width"], res.width), (200, 200))
        self.assert_no_leftovers(self.out)

    def test_animated_webp_to_mp4_is_refused_when_ffmpeg_cannot_decode_it(self):
        src = self.path("a.webp")
        try:
            ff("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=1", "-loop", "0", "-c:v", "libwebp_anim",
               src)
        except subprocess.CalledProcessError:
            self.skipTest("this ffmpeg cannot write animated WebP")
        if probe(FFPROBE, src).width:
            self.skipTest("this ffmpeg can decode animated WebP")
        with self.assertRaises(UnsupportedMedia):
            gif_to_mp4(src, self.out, "a", self.settings)


if __name__ == "__main__":
    unittest.main()
