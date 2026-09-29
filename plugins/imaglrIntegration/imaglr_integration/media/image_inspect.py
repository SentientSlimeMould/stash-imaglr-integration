# SPDX-License-Identifier: AGPL-3.0-only
"""Read an image's format, size, EXIF orientation, alpha and animation from its headers.

Pure Python for JPEG, PNG, WebP and GIF, reading only headers and seeking past pixel data. Anything
else (AVIF, HEIC, TIFF, BMP...) is described by ffprobe, when the caller supplies its path.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from .probe import probe

PARSED = ("JPEG", "PNG", "WEBP", "GIF")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# JPEG start-of-frame markers (not DHT C4, JPG C8 or DAC CC).
SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
# ffprobe codec names for the formats we cannot parse; used for the plan's labels.
PROBED_FORMATS = {"av1": "AVIF", "hevc": "HEIC", "tiff": "TIFF", "bmp": "BMP", "mjpeg": "JPEG", "png": "PNG"}


class ImageFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ImageInfo:
    format: str  # upper case: JPEG, PNG, WEBP, GIF, or e.g. AVIF/HEIC/TIFF/BMP from ffprobe
    width: int  # as stored, before orientation
    height: int
    bytes: int
    orientation: int = 1
    has_alpha: bool = False
    is_animated: bool = False

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)

    @property
    def display_size(self) -> tuple[int, int]:
        if self.orientation in (5, 6, 7, 8):
            return self.height, self.width
        return self.width, self.height


def sniff_format(head: bytes) -> str | None:
    if head[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if head[:8] == PNG_SIGNATURE:
        return "PNG"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    return None


def exif_orientation(tiff: bytes) -> int:
    """Orientation (tag 0x0112) from a TIFF-structured EXIF block, or 1 when absent or unreadable."""
    if tiff[:6] == b"Exif\0\0":
        tiff = tiff[6:]
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if order is None or len(tiff) < 8:
        return 1
    try:
        (ifd,) = struct.unpack_from(order + "I", tiff, 4)
        (count,) = struct.unpack_from(order + "H", tiff, ifd)
        for i in range(count):
            tag, typ, _n = struct.unpack_from(order + "HHI", tiff, ifd + 2 + 12 * i)
            if tag == 0x0112 and typ == 3:
                (value,) = struct.unpack_from(order + "H", tiff, ifd + 2 + 12 * i + 8)
                return value if 1 <= value <= 8 else 1
    except struct.error:
        pass
    return 1


def _read(f, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise ImageFormatError("truncated image")
    return data


def _inspect_jpeg(f) -> dict:
    f.seek(2)
    out = {"orientation": 1}
    while True:
        byte = _read(f, 1)
        if byte != b"\xff":
            raise ImageFormatError("bad JPEG marker")
        marker = _read(f, 1)[0]
        while marker == 0xFF:  # fill bytes
            marker = _read(f, 1)[0]
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if marker in (0xD9, 0xDA):  # EOI or start of scan: no more headers
            break
        (length,) = struct.unpack(">H", _read(f, 2))
        payload = _read(f, length - 2)
        if marker == 0xE1 and payload[:6] == b"Exif\0\0" and out["orientation"] == 1:
            out["orientation"] = exif_orientation(payload[6:])
        elif marker in SOF_MARKERS:
            out["height"], out["width"] = struct.unpack_from(">HH", payload, 1)
    if "width" not in out:
        raise ImageFormatError("JPEG has no frame header")
    return out


def _png_chunks(f):
    """Yield (type, length, data offset), leaving the file positioned at the chunk's data."""
    f.seek(8)
    while True:
        head = f.read(8)
        if len(head) < 8:
            return
        length, kind = struct.unpack(">I4s", head)
        pos = f.tell()
        yield kind, length, pos
        if kind == b"IEND":
            return
        f.seek(pos + length + 4)


def _inspect_png(f) -> dict:
    out = {"orientation": 1, "has_alpha": False, "is_animated": False}
    for kind, length, _pos in _png_chunks(f):
        if kind == b"IHDR":
            data = _read(f, 13)
            out["width"], out["height"] = struct.unpack_from(">II", data)
            out["has_alpha"] = data[9] in (4, 6)  # grey+alpha, RGBA
        elif kind == b"tRNS":
            out["has_alpha"] = True
        elif kind == b"acTL":
            out["is_animated"] = struct.unpack(">I", _read(f, 4))[0] > 1
        elif kind == b"eXIf":
            out["orientation"] = exif_orientation(_read(f, length))
    if "width" not in out:
        raise ImageFormatError("PNG has no IHDR")
    return out


def _riff_chunks(f):
    """Yield (fourcc, size, data offset) for each chunk of a RIFF/WEBP file."""
    f.seek(4)
    end = min(8 + struct.unpack("<I", _read(f, 4))[0], os.fstat(f.fileno()).st_size)
    pos = 12
    while pos + 8 <= end:
        f.seek(pos)
        fourcc, size = struct.unpack("<4sI", _read(f, 8))
        yield fourcc, size, pos + 8
        pos += 8 + size + (size & 1)


def _inspect_webp(f) -> dict:
    out = {"orientation": 1, "has_alpha": False, "is_animated": False}
    frames = 0
    for fourcc, size, pos in _riff_chunks(f):
        f.seek(pos)
        if fourcc == b"VP8X":
            data = _read(f, 10)
            out["has_alpha"] = bool(data[0] & 0x10)
            out["width"] = int.from_bytes(data[4:7], "little") + 1
            out["height"] = int.from_bytes(data[7:10], "little") + 1
        elif fourcc == b"VP8 " and "width" not in out:
            data = _read(f, 10)
            if data[3:6] != b"\x9d\x01\x2a":
                raise ImageFormatError("bad VP8 frame header")
            w, h = struct.unpack_from("<HH", data, 6)
            out["width"], out["height"] = w & 0x3FFF, h & 0x3FFF
        elif fourcc == b"VP8L" and "width" not in out:
            data = _read(f, 5)
            if data[0] != 0x2F:
                raise ImageFormatError("bad VP8L header")
            (bits,) = struct.unpack_from("<I", data, 1)
            out["width"], out["height"] = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            out["has_alpha"] = bool((bits >> 28) & 1)
        elif fourcc == b"ALPH":
            out["has_alpha"] = True
        elif fourcc == b"ANMF":
            frames += 1
        elif fourcc == b"EXIF":
            out["orientation"] = exif_orientation(_read(f, size))
    out["is_animated"] = frames > 1
    if "width" not in out:
        raise ImageFormatError("WebP has no image data")
    return out


def _skip_subblocks(f) -> None:
    while True:
        n = _read(f, 1)[0]
        if n == 0:
            return
        f.seek(n, os.SEEK_CUR)


def _inspect_gif(f) -> dict:
    f.seek(6)
    width, height, flags = struct.unpack("<HHB", _read(f, 5))
    f.seek(2, os.SEEK_CUR)  # background colour, aspect ratio
    if flags & 0x80:  # global colour table
        f.seek(3 << ((flags & 7) + 1), os.SEEK_CUR)
    out = {"width": width, "height": height, "orientation": 1, "has_alpha": False}
    frames = 0
    while frames < 2:
        block = f.read(1)
        if block in (b"", b";"):
            break
        if block == b"!":
            label = _read(f, 1)[0]
            if label == 0xF9:  # graphic control: packed byte bit 0 = transparent colour index
                data = _read(f, 6)
                out["has_alpha"] = out["has_alpha"] or bool(data[1] & 1)
                f.seek(-6, os.SEEK_CUR)
            _skip_subblocks(f)
        elif block == b",":
            frames += 1
            desc = _read(f, 9)
            if desc[8] & 0x80:
                f.seek(3 << ((desc[8] & 7) + 1), os.SEEK_CUR)
            f.seek(1, os.SEEK_CUR)  # LZW minimum code size
            _skip_subblocks(f)
        else:
            raise ImageFormatError("bad GIF block")
    out["is_animated"] = frames > 1
    return out


_PARSERS = {"JPEG": _inspect_jpeg, "PNG": _inspect_png, "WEBP": _inspect_webp, "GIF": _inspect_gif}


def inspect_image(path: str, ffprobe: str | None = None) -> ImageInfo:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        fmt = sniff_format(f.read(16))
        if fmt is not None:
            try:
                return ImageInfo(format=fmt, bytes=size, **_PARSERS[fmt](f))
            except (struct.error, IndexError) as e:
                raise ImageFormatError(f"unreadable {fmt}: {e}") from None
    if not ffprobe:
        raise ImageFormatError("not a JPEG, PNG, WebP or GIF, and no ffprobe to identify it")
    p = probe(ffprobe, path)
    codec = (p.video_codec or "").lower()
    w, h = p.display_size  # the re-encode lets ffmpeg apply any rotation it knows about
    return ImageInfo(PROBED_FORMATS.get(codec, codec.upper() or "UNKNOWN"), w, h, size, 1, p.has_alpha, False)
