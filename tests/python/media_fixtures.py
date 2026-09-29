# SPDX-License-Identifier: AGPL-3.0-only
"""Test images and metadata builders for the media tests (no ffmpeg needed).

The EXIF/XMP builders are copied from dev/make_media.py. The tiny images were made with ffmpeg 8 in
the Stash image and are embedded so the pure tests run anywhere.
"""

import base64
import os
import struct
import tempfile
import zlib

from imaglr_integration.media.image_inspect import inspect_image

JPEG_16x8 = base64.b64decode(
    "/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjExLjEwMAD/2wBDAAgUFBcUFxsbGxsbGyAeICEhISAgICAhISEkJCQqKiok"
    "JCQhISQkKCgqKi4vLisrKisvLzIyMjw8OTlGRkhWVmf/xABvAAEBAQAAAAAAAAAAAAAAAAAHAgYBAQEBAQAAAAAAAAAAAAAAAAUH"
    "AwYQAAEDAwQDAQAAAAAAAAAAAAIDASERABIEQSI0E3EUBREAAQIFAwQDAQAAAAAAAAAAAQIDEQQSACGBQQU0BlEyExRCMf/AABEI"
    "AAgAEAMBEgACEgADEgD/2gAMAwEAAhEDEQA/AMunol/gFvHyIi3GWqLtNfdpKPVRtPjeQlGXVpW5BRUPwsxFMP6E+bkLXWai0Zl4"
    "SrTjbyimLTQSnKhWHnVLhTEA0lETvgbWD3H763D6tEP0gLOghnnBbhRopPKz9btLX18lx05LorW3SmGTWg4zsFE+LszvR6G1JBKZ"
    "r7qkAL+Qy6miRugEKIqhSQCRmEQb17c9NL//2Q=="
)

WEBP_LOSSY_16x8 = base64.b64decode(
    "UklGRqwAAABXRUJQVlA4IKAAAABQAwCdASoQAAgAAsBMJbACdHMBfYG6RfsB6QBMrD9FVt/GAAD+8b+1vUR9+EctyPHPP5UZGmt9"
    "EPIXmf5PIAA3Rz7PO06nNWfTIwa3ziOPKDeamruya0fvw+CyesDY+AqyXdt/yPLj6VFT/2GOz/xCpdaZx//KNa/EnzIfHyY4p90X"
    "/7//pr3YNIcnHZ+JR/+uW23+N3Xm+NG1jxTPAAAA"
)

WEBP_LOSSLESS_ALPHA_16x8 = base64.b64decode(
    "UklGRlYAAABXRUJQVlA4TEoAAAAvD8ABEGAUSVKkdIYVnGEFZ/VjTwEI2rZNmGxMf6Y/ExtkG6lob/Jqb/JoK2CIAERKRZSCKiUR"
    "VAf8AZNNT0ejpq5aNcrm5sez1w=="
)

WEBP_ANIMATED_16x8 = base64.b64decode(
    "UklGRqIBAABXRUJQVlA4WAoAAAACAAAADwAABwAAQU5JTQYAAAD/////AABBTk1GpgAAAAAAAAAAAA8AAAcAAMgAAAJWUDggjgAA"
    "AFACAJ0BKhAACAAEAGglsAJ0MEg8oAEaw74oDgD+6l28TOjEgPq2DTW/xtLczy7mwoOfeLLq4zWvBpwAXhz7bFdYmTD6wpMKT9q8"
    "XM5LigG13UepFf86C4+SLWtePjW3+tBUIWNf+cyi+O9z1p+esDI/6/9f/xnexqyPf6jMlH/5diIx6Csf+q5Wf9i2gABBTk1GYAAA"
    "AAAAAAMAAA8AAAEAAMgAAABWUDggSAAAALQCAJ0BKhAAAgAAAGglsAJ0cwFyAb//mAAFupsmAAD+m/dE2l5zc3rAjvqP/DT3Kf5s"
    "Y3P9cS2s0Gtrv79cX12OHtdIk7wAAEFOTUZgAAAAAAAAAwAADwAAAQAAyAAAAFZQOCBIAAAAVAMAnQEqEAACAAAAaCWwAnS6AUQD"
    "+gfarv/+cAfsABbqalgA/rbtnRpnIQsY9Q4f+XQtJPf9guxXD34fqJ95lJejgOAWaAAA"
)

GIF_ANIMATED_16x8 = base64.b64decode(
    "R0lGODlhEAAIAPcfMQAAACQAAEgAAGwAAJAAALQAANgAAPwAAAAkACQkAEgkAGwkAJAkALQkANgkAPwkAABIACRIAEhIAGxIAJBI"
    "ALRIANhIAPxIAABsACRsAEhsAGxsAJBsALRsANhsAPxsAACQACSQAEiQAGyQAJCQALSQANiQAPyQAAC0ACS0AEi0AGy0AJC0ALS0"
    "ANi0APy0AADYACTYAEjYAGzYAJDYALTYANjYAPzYAAD8ACT8AEj8AGz8AJD8ALT8ANj8APz8AAAAVSQAVUgAVWwAVZAAVbQAVdgA"
    "VfwAVQAkVSQkVUgkVWwkVZAkVbQkVdgkVfwkVQBIVSRIVUhIVWxIVZBIVbRIVdhIVfxIVQBsVSRsVUhsVWxsVZBsVbRsVdhsVfxs"
    "VQCQVSSQVUiQVWyQVZCQVbSQVdiQVfyQVQC0VSS0VUi0VWy0VZC0VbS0Vdi0Vfy0VQDYVSTYVUjYVWzYVZDYVbTYVdjYVfzYVQD8"
    "VST8VUj8VWz8VZD8VbT8Vdj8Vfz8VQAAqiQAqkgAqmwAqpAAqrQAqtgAqvwAqgAkqiQkqkgkqmwkqpAkqrQkqtgkqvwkqgBIqiRI"
    "qkhIqmxIqpBIqrRIqthIqvxIqgBsqiRsqkhsqmxsqpBsqrRsqthsqvxsqgCQqiSQqkiQqmyQqpCQqrSQqtiQqvyQqgC0qiS0qki0"
    "qmy0qpC0qrS0qti0qvy0qgDYqiTYqkjYqmzYqpDYqrTYqtjYqvzYqgD8qiT8qkj8qmz8qpD8qrT8qtj8qvz8qgAA/yQA/0gA/2wA"
    "/5AA/7QA/9gA//wA/wAk/yQk/0gk/2wk/5Ak/7Qk/9gk//wk/wBI/yRI/0hI/2xI/5BI/7RI/9hI//xI/wBs/yRs/0hs/2xs/5Bs"
    "/7Rs/9hs//xs/wCQ/ySQ/0iQ/2yQ/5CQ/7SQ/9iQ//yQ/wC0/yS0/0i0/2y0/5C0/7S0/9i0//y0/wDY/yTY/0jY/2zY/5DY/7TY"
    "/9jY//zY/wD8/yT8/0j8/2z8/5D8/7T8/9j8//z8/yH/C05FVFNDQVBFMi4wAwEAAAAh+QQEFAAfACwAAAAAEAAIAAAIWwABADhw"
    "4NgxYMB+/MCB4wC+f/8EOjSIUCFDghAl4qOYcGHDAxkHbjzY8SLIiCI5WvwYciLJlRj/Hfjw4seOHHhw4UMHLRixY4eOHLhwwwcP"
    "hjrB9Rxm7NiRgAAAIfkEBRQAAAAsAAAGABAAAgAACCMAH5z40UMHDgD44GEDNqwYgCMHBBLUAQAXAIXAhBk7duhAQAAh+QQFFAAA"
    "ACwAAAYADwACAAAIIgA/3PDBAwceXADQIQtG7NghAB9e+NiRAwAAfOCgMXR4JCAAOw=="
)

# --- EXIF / XMP (from dev/make_media.py) ---------------------------------------------------------

BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5
COMMENT = b"Test comment that must be stripped"
CAMERA = b"TestCam"
XMP_NS = b"http://ns.adobe.com/xap"


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
    """EXIF with camera make/model, orientation and a GPS IFD."""
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


def exif_tiff_big_endian(orientation):
    ifd = struct.pack(">H", 1) + struct.pack(">HHIH", 0x0112, SHORT, 1, orientation) + b"\0\0" + b"\0\0\0\0"
    return b"MM\0*" + struct.pack(">I", 8) + ifd


XMP = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
    ' exif:GPSLatitude="51,30.44N" exif:GPSLongitude="0,7.66W"><dc:creator>Test Creator</dc:creator>'
    '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
).encode()

SECRETS = (b"Exif", CAMERA, XMP_NS, b"GPSLatitude", COMMENT)


def secrets_in(data):
    """The metadata markers still present in `data` (empty when clean)."""
    return [s for s in SECRETS if s in data]


# --- JPEG ----------------------------------------------------------------------------------------


def _segment(marker, payload):
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


ICC_SEGMENT = _segment(0xE2, b"ICC_PROFILE\0\x01\x01" + b"fake-icc-profile")
ADOBE_SEGMENT = _segment(0xEE, b"Adobe\0\x64\0\0\0\0\x01")


def add_jpeg_metadata(data, orientation=1, extras=True):
    """EXIF (with GPS), XMP and a comment after JFIF; with extras also ICC, Adobe, IPTC and a trailer."""
    assert data[:2] == b"\xff\xd8"
    pos = 2
    if data[2:4] == b"\xff\xe0":  # keep JFIF APP0 first
        pos = 4 + struct.unpack(">H", data[4:6])[0]
    extra = (
        _segment(0xE1, b"Exif\0\0" + exif_tiff(orientation))
        + _segment(0xE1, b"http://ns.adobe.com/xap/1.0/\0" + XMP)
        + _segment(0xFE, COMMENT)
    )
    if extras:
        extra += ICC_SEGMENT + ADOBE_SEGMENT + _segment(0xED, b"Photoshop 3.0\0" + COMMENT)
    out = data[:pos] + extra + data[pos:]
    return out + (b"MOTION-PHOTO-TRAILER " + COMMENT if extras else b"")


# --- PNG -----------------------------------------------------------------------------------------


def png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def make_png(width, height, alpha=False, trns=False):
    """A plain RGB/RGBA PNG; `trns` adds a tRNS chunk to an RGB image instead of an alpha channel."""
    channels = 4 if alpha else 3

    def row(y):
        return b"\0" + b"".join(bytes((x * 16 % 256, y * 32 % 256, 128, 200)[:channels]) for x in range(width))

    rows = b"".join(row(y) for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    body = png_chunk(b"IHDR", ihdr)
    if trns:
        body += png_chunk(b"tRNS", b"\0\0\0\0\0\0")
    return b"\x89PNG\r\n\x1a\n" + body + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b"")


def add_png_metadata(data, orientation=1):
    ihdr_end = 8 + 8 + 13 + 4
    extra = (
        png_chunk(b"tEXt", b"Comment\0" + COMMENT)
        + png_chunk(b"eXIf", exif_tiff(orientation))
        + png_chunk(b"iTXt", b"XML:com.adobe.xmp\0\0\0\0\0" + XMP)
        + png_chunk(b"zTXt", b"Author\0\0" + zlib.compress(COMMENT))
        + png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 9, 29, 12, 0, 0))
        + png_chunk(b"iCCP", b"icc\0\0" + zlib.compress(b"fake-icc-profile"))
        + png_chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1))
    )
    return data[:ihdr_end] + extra + data[ihdr_end:] + b"TRAILER " + COMMENT


# --- WebP ----------------------------------------------------------------------------------------


def riff_chunk(fourcc, payload):
    return fourcc + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) % 2 else b"")


def webp_chunks(data):
    pos, out = 12, []
    while pos + 8 <= len(data):
        fourcc, size = struct.unpack_from("<4sI", data, pos)
        out.append((fourcc, data[pos + 8 : pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return out


def add_webp_metadata(data, orientation=1):
    """Convert to the extended (VP8X) layout if needed and add EXIF and XMP chunks."""
    chunks = webp_chunks(data)
    if chunks[0][0] != b"VP8X":
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as f:
            f.write(data)
        try:
            info = inspect_image(f.name)
        finally:
            os.remove(f.name)
        flags = 0x10 if info.has_alpha else 0
        size = (info.width - 1).to_bytes(3, "little") + (info.height - 1).to_bytes(3, "little")
        vp8x = bytes([flags, 0, 0, 0]) + size
        chunks.insert(0, (b"VP8X", vp8x))
    flags = chunks[0][1][0] | 0x08 | 0x04
    chunks[0] = (b"VP8X", bytes([flags]) + chunks[0][1][1:])
    chunks += [(b"EXIF", exif_tiff(orientation)), (b"XMP ", XMP + b"x")]  # odd length: needs a pad byte
    body = b"WEBP" + b"".join(riff_chunk(k, v) for k, v in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body + b"TRAILER " + COMMENT


# --- GIF -----------------------------------------------------------------------------------------


def _subblocks(payload):
    parts = [payload[i : i + 255] for i in range(0, len(payload), 255)]
    return b"".join(bytes([len(p)]) + p for p in parts) + b"\0"


GIF_COMMENT = b"\x21\xfe" + _subblocks(COMMENT)
# XMP's GIF embedding: the packet, then a 258-byte "magic trailer" that makes it walkable as sub-blocks.
GIF_XMP = b"\x21\xff\x0bXMP DataXMP" + XMP + b"\x01" + bytes(range(255, -1, -1)) + b"\x00"


def add_gif_metadata(data):
    """Insert a comment and an XMP application extension after the colour table, and another comment
    before the trailer."""
    flags = data[10]
    pos = 13 + (3 << ((flags & 7) + 1) if flags & 0x80 else 0)
    assert data.endswith(b";")
    return data[:pos] + GIF_COMMENT + GIF_XMP + data[pos:-1] + GIF_COMMENT + b";" + b"TRAILER " + COMMENT
