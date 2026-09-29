# SPDX-License-Identifier: AGPL-3.0-only
"""Lossless metadata removal for JPEG, PNG, WebP and GIF (replaces `exiftool -all=`).

Each stripper walks the container and copies every block it keeps byte for byte, so pixels are
untouched. Only what is needed to decode and display the image survives:
- JPEG: APP0 JFIF, APP2 ICC_PROFILE and APP14 Adobe (its colour-transform flag changes how CMYK/YCCK
  decodes; exiftool keeps it too). Other APPn (EXIF, XMP, IPTC, MPF...) and COM go, and so does
  anything after EOI (MPO extra images, motion-photo videos, vendor trailers).
- PNG: tEXt, zTXt, iTXt, eXIf and tIME go; everything else stays (iCCP, sRGB, gAMA, cHRM, pHYs, and all
  image and APNG chunks). Anything after IEND goes.
- WebP: EXIF and XMP chunks go, the VP8X flags for them are cleared and the RIFF size is fixed.
- GIF: comment extensions and application extensions other than NETSCAPE2.0/ANIMEXTS1.0 (the loop
  count) go; XMP lives in an application extension. Anything after the trailer goes.

Files are read whole: strip only runs on files under imaglr's upload limit (tens of MB). The output is
written piece by piece, without building a second copy in memory.
"""

from __future__ import annotations

import os
import struct

from .image_inspect import PNG_SIGNATURE, sniff_format


class StripError(ValueError):
    pass


def _u16be(data, pos: int) -> int:
    if pos + 2 > len(data):
        raise StripError("truncated image")
    return (data[pos] << 8) | data[pos + 1]


# --- JPEG ----------------------------------------------------------------------------------------


def _keep_jpeg_segment(marker: int, payload) -> bool:
    if marker == 0xFE:  # COM
        return False
    if 0xE0 <= marker <= 0xEF:
        head = bytes(payload[:12])
        return (
            (marker == 0xE0 and head.startswith(b"JFIF\0"))
            or (marker == 0xE2 and head.startswith(b"ICC_PROFILE\0"))
            or (marker == 0xEE and head.startswith(b"Adobe"))
        )
    return True


def _entropy_end(data, pos: int) -> int:
    """Index of the first real marker after entropy-coded data (skipping FF00 stuffing and RSTn)."""
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            return len(data)
        nxt = data[pos + 1]
        if nxt == 0x00 or 0xD0 <= nxt <= 0xD7 or nxt == 0xFF:
            pos += 1 if nxt == 0xFF else 2
            continue
        return pos


def jpeg_pieces(data: bytes):
    if data[:3] != b"\xff\xd8\xff":
        raise StripError("not a JPEG")
    view = memoryview(data)
    yield view[:2]
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            raise StripError("bad JPEG marker")
        marker = data[pos + 1] if pos + 1 < len(data) else 0xD9
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xD9:  # EOI: stop, dropping any trailer
            yield b"\xff\xd9"
            return
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:  # markers without a length
            yield view[pos : pos + 2]
            pos += 2
            continue
        end = pos + 2 + _u16be(data, pos + 2)
        if end > len(data):
            raise StripError("truncated JPEG segment")
        if _keep_jpeg_segment(marker, view[pos + 4 : end]):
            yield view[pos:end]
        pos = end
        if marker == 0xDA:  # start of scan: copy the compressed data up to the next marker
            scan_end = _entropy_end(data, pos)
            yield view[pos:scan_end]
            pos = scan_end


# --- PNG -----------------------------------------------------------------------------------------

PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}


def png_pieces(data: bytes):
    if data[:8] != PNG_SIGNATURE:
        raise StripError("not a PNG")
    view = memoryview(data)
    yield view[:8]
    pos = 8
    while pos + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        end = pos + 12 + length
        if end > len(data):
            raise StripError("truncated PNG chunk")
        if kind not in PNG_DROP:
            yield view[pos:end]
        pos = end
        if kind == b"IEND":
            return
    raise StripError("PNG has no IEND")


# --- WebP ----------------------------------------------------------------------------------------

WEBP_DROP = {b"EXIF", b"XMP "}
VP8X_EXIF_XMP = 0x08 | 0x04


def webp_pieces(data: bytes):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise StripError("not a WebP")
    view = memoryview(data)
    end = min(len(data), 8 + struct.unpack_from("<I", data, 4)[0])
    kept = []
    pos = 12
    while pos + 8 <= end:
        fourcc, size = struct.unpack_from("<4sI", data, pos)
        chunk_end = pos + 8 + size + (size & 1)
        if pos + 8 + size > end:
            raise StripError("truncated WebP chunk")
        if fourcc == b"VP8X":
            flags = bytes([data[pos + 8] & ~VP8X_EXIF_XMP & 0xFF])
            kept += [view[pos : pos + 8], flags, view[pos + 9 : chunk_end]]
        elif fourcc not in WEBP_DROP:
            kept.append(view[pos:chunk_end])
        pos = chunk_end
    yield b"RIFF" + struct.pack("<I", 4 + sum(len(p) for p in kept)) + b"WEBP"
    yield from kept


# --- GIF -----------------------------------------------------------------------------------------

GIF_KEEP_APPS = {b"NETSCAPE2.0", b"ANIMEXTS1.0"}


def _subblocks_end(data, pos: int) -> int:
    while True:
        if pos >= len(data):
            raise StripError("truncated GIF")
        if data[pos] == 0:
            return pos + 1
        pos += data[pos] + 1


def gif_pieces(data: bytes):
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 13:
        raise StripError("not a GIF")
    view = memoryview(data)
    pos = 13
    if data[10] & 0x80:  # global colour table
        pos += 3 << ((data[10] & 7) + 1)
    yield view[:pos]
    while pos < len(data):
        block = data[pos]
        if block == 0x3B:  # trailer: stop, dropping anything after it
            yield b";"
            return
        if block == 0x21:
            if pos + 2 > len(data):
                raise StripError("truncated GIF")
            label = data[pos + 1]
            end = _subblocks_end(data, pos + 2)
            app_id = bytes(view[pos + 3 : pos + 14]) if data[pos + 2] == 11 else b""
            if not (label == 0xFE or (label == 0xFF and app_id not in GIF_KEEP_APPS)):
                yield view[pos:end]
        elif block == 0x2C:
            if pos + 10 > len(data):
                raise StripError("truncated GIF")
            start = pos + 10
            if data[pos + 9] & 0x80:  # local colour table
                start += 3 << ((data[pos + 9] & 7) + 1)
            end = _subblocks_end(data, start + 1)  # after the LZW minimum code size
            yield view[pos:end]
        else:
            raise StripError("bad GIF block")
        pos = end
    yield b";"  # truncated file: close it properly


# --- files ---------------------------------------------------------------------------------------

_PIECES = {"JPEG": jpeg_pieces, "PNG": png_pieces, "WEBP": webp_pieces, "GIF": gif_pieces}


def strip_bytes(data: bytes) -> bytes:
    fmt = sniff_format(data[:16])
    if fmt is None:
        raise StripError("not a JPEG, PNG, WebP or GIF")
    return b"".join(_PIECES[fmt](data))


def strip_file(src: str, dst: str) -> None:
    """Write src without metadata to dst (which may be src). dst appears only once complete."""
    with open(src, "rb") as f:
        data = f.read()
    fmt = sniff_format(data[:16])
    if fmt is None:
        raise StripError("not a JPEG, PNG, WebP or GIF")
    tmp = dst + ".strip"
    try:
        with open(tmp, "wb") as out:
            for piece in _PIECES[fmt](data):
                out.write(piece)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
