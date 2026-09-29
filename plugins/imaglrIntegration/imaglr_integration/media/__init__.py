# SPDX-License-Identifier: AGPL-3.0-only
"""Media processing: clip export, frame grabs and image preparation (reference spec §7 Export rules).

Everything runs on Stash's own ffmpeg/ffprobe, whose paths the caller passes in, plus pure-Python
metadata stripping for JPEG, PNG, WebP and GIF. No Pillow, no exiftool.
"""
