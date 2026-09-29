"""Generate synthetic test media for the local test Stash.

Runs inside the stashapp/stash image (Python 3.12 + ffmpeg), writing to the directory given
as the only argument. Everything is generated test patterns: no real content.

Files that exercise specific plugin behaviour:
- images/photo_gps_orient6.jpg: EXIF orientation 6, EXIF GPS, camera make/model, an XMP
  packet with GPS and a JPEG comment. Stored sideways; displays upright only if orientation
  is honoured. Every one of those metadata blocks must be gone from the plugin's output.
- images/transparent.png: alpha channel plus tEXt and eXIf chunks.
- images/animated.gif, images/animated.webp: must be sent as animations.
- videos/scene_h264.mp4: container title/comment/location tags and two chapters to strip.
- videos/scene_hevc.mkv: not browser-playable, so the UI must fall back to a transcoded stream.
- galleries/zipped_gallery.zip: images inside a zip file.
"""

import os
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def try_ffmpeg(label, *args):
    try:
        ffmpeg(*args)
    except subprocess.CalledProcessError:
        print(f"skipped {label}: this ffmpeg build cannot produce it")


# --- EXIF / XMP / PNG metadata builders -------------------------------------------------

BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5


def _ifd(entries, offset):
    """Pack a little-endian TIFF IFD placed at `offset`; values over 4 bytes follow it."""
    size = 2 + len(entries) * 12 + 4
    head, data = struct.pack("<H", len(entries)), b""
    for tag, typ, count, value in sorted(entries):
        if len(value) <= 4:
            head += struct.pack("<HHI", tag, typ, count) + value.ljust(4, b"\0")
        else:
            head += struct.pack("<HHII", tag, typ, count, offset + size + len(data))
            data += value + (b"\0" if len(value) % 2 else b"")
    return head + struct.pack("<I", 0) + data


def _ascii(text):
    raw = text.encode() + b"\0"
    return (ASCII, len(raw), raw)


def _rationals(*pairs):
    return (RATIONAL, len(pairs), b"".join(struct.pack("<II", n, d) for n, d in pairs))


def exif_tiff(orientation):
    gps = [
        (0x0000, BYTE, 4, bytes([2, 3, 0, 0])),
        (0x0001, *_ascii("N")),
        (0x0002, *_rationals((51, 1), (30, 1), (2640, 100))),
        (0x0003, *_ascii("W")),
        (0x0004, *_rationals((0, 1), (7, 1), (3960, 100))),
    ]
    ifd0 = [
        (0x010F, *_ascii("TestCam")),
        (0x0110, *_ascii("TestCam Model 1")),
        (0x0112, SHORT, 1, struct.pack("<H", orientation)),
        (0x0132, *_ascii("2026:09:29 12:00:00")),
        (0x8825, LONG, 1, struct.pack("<I", 0)),  # GPS IFD pointer, fixed below
    ]
    first = _ifd(ifd0, 8)
    ifd0[-1] = (0x8825, LONG, 1, struct.pack("<I", 8 + len(first)))
    first = _ifd(ifd0, 8)
    return b"II*\0" + struct.pack("<I", 8) + first + _ifd(gps, 8 + len(first))


XMP = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' exif:GPSLatitude="51,30.44N" exif:GPSLongitude="0,7.66W"><dc:creator>Test Creator</dc:creator>'
    "</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
).encode()


def _segment(marker, payload):
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def add_jpeg_metadata(path, orientation):
    data = open(path, "rb").read()
    assert data[:2] == b"\xff\xd8"
    pos = 2
    if data[2:4] == b"\xff\xe0":  # keep JFIF APP0 first
        pos = 4 + struct.unpack(">H", data[4:6])[0]
    extra = (
        _segment(0xE1, b"Exif\0\0" + exif_tiff(orientation))
        + _segment(0xE1, b"http://ns.adobe.com/xap/1.0/\0" + XMP)
        + _segment(0xFE, b"Test comment that must be stripped")
    )
    open(path, "wb").write(data[:pos] + extra + data[pos:])


def _png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def add_png_metadata(path):
    data = open(path, "rb").read()
    ihdr_end = 8 + 8 + 13 + 4
    extra = _png_chunk(b"tEXt", b"Comment\0Test comment that must be stripped") + _png_chunk(
        b"eXIf", exif_tiff(1)
    )
    open(path, "wb").write(data[:ihdr_end] + extra + data[ihdr_end:])


# --- media ----------------------------------------------------------------------------------


def make_videos(out):
    d = os.path.join(out, "videos")
    os.makedirs(d, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as meta:
        meta.write(
            ";FFMETADATA1\ntitle=Metadata title to strip\ncomment=Metadata comment to strip\n"
            "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=15000\ntitle=Chapter one\n"
            "[CHAPTER]\nTIMEBASE=1/1000\nSTART=15000\nEND=30000\ntitle=Chapter two\n"
        )
    tone = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30", *tone, "-i", meta.name,
        "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2",
        "-metadata", "location=+51.5074-000.1278/", "-t", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", os.path.join(d, "scene_h264.mp4"),
    )
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30", *tone, "-t", "20", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", os.path.join(d, "scene_vertical.mp4"),
    )
    try_ffmpeg(
        "HEVC clip",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25", *tone, "-t", "20", "-shortest",
        "-c:v", "libx265", "-preset", "ultrafast", "-crf", "30", "-tag:v", "hvc1", "-x265-params", "log-level=error",
        "-c:a", "aac", os.path.join(d, "scene_hevc.mkv"),
    )


def make_images(out):
    d = os.path.join(out, "images")
    os.makedirs(d, exist_ok=True)

    def img(name, source, *args):
        ffmpeg("-f", "lavfi", "-i", source, "-frames:v", "1", *args, os.path.join(d, name))

    # Upright portrait test pattern, stored rotated 90° anticlockwise; orientation 6 displays it upright.
    img("photo_gps_orient6.jpg", "testsrc=size=1200x1600", "-vf", "transpose=2", "-q:v", "3")
    add_jpeg_metadata(os.path.join(d, "photo_gps_orient6.jpg"), orientation=6)
    img("plain.jpg", "testsrc2=size=1920x1080", "-q:v", "3")
    img("transparent.png", "testsrc2=size=800x800,format=rgba,colorchannelmixer=aa=0.5")
    add_png_metadata(os.path.join(d, "transparent.png"))
    img("opaque.png", "testsrc2=size=1024x768")
    img("still.webp", "testsrc2=size=1024x768")
    img("photo.tiff", "testsrc=size=1024x768")
    img("photo.bmp", "testsrc=size=640x480")
    try_ffmpeg(
        "AVIF image", "-f", "lavfi", "-i", "testsrc2=size=1024x768", "-frames:v", "1",
        os.path.join(d, "photo.avif"),
    )
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=10:duration=3",
        "-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0",
        os.path.join(d, "animated.gif"),
    )
    try_ffmpeg(
        "animated WebP", "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=10:duration=3",
        "-loop", "0", "-c:v", "libwebp_anim", os.path.join(d, "animated.webp"),
    )


def make_gallery(out):
    d = os.path.join(out, "galleries")
    os.makedirs(d, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(
        os.path.join(d, "zipped_gallery.zip"), "w"
    ) as z:
        for i, size in enumerate(["1600x1200", "1200x1600", "1920x1080"], 1):
            name = f"gallery_{i}.jpg"
            ffmpeg("-f", "lavfi", "-i", f"smptehdbars=size={size}", "-frames:v", "1", "-q:v", "3",
                   os.path.join(tmp, name))
            z.write(os.path.join(tmp, name), name)


if __name__ == "__main__":
    target = sys.argv[1]
    make_videos(target)
    make_images(target)
    make_gallery(target)
    for root, _, files in sorted(os.walk(target)):
        for f in sorted(files):
            p = os.path.join(root, f)
            print(f"{os.path.getsize(p) / 1e6:8.2f} MB  {os.path.relpath(p, target)}")
