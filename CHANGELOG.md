# Changelog

## 0.1.2 — 2026-09-30

- Item counts on the Clips, Images and Sent tabs.
- Paging like Stash's lists: page-size dropdown, "1-40 of 120" index and page buttons on all three tabs.
- Sent list shows thumbnails for clips and stills too.

## 0.1.1 — 2026-09-30

- Menu icon: the imaglr lens mark instead of a paper plane.
- Images with an EXIF orientation are now rotated correctly on newer ffmpeg builds too (ffmpeg 8.1 ignores
  `-noautorotate` for images, which would have rotated them twice).
- README and Settings explain which imaglr key permissions are needed (read + manage, never write) and where
  "posts left today" comes from.
- Releases publish from `main` when the plugin version changes.

## 0.1.0 — 2026-09-29

First test release.

- **Post to imaglr** page (main menu → **imaglr**) with Clips, Images and Sent tabs, using Stash's own list
  toolbar, cards and selection.
- Queue images and scene markers with the `imaglr` tag, or with **⋯ → Add to imaglr** / **Add to imaglr as one
  post** in any Stash image list (including a gallery's Images tab).
- Editor: crop; for clips, trim (written back to the Stash marker), remove sound and save stills; Stash-style
  tag field; caption; blog and action (draft, queue or publish now).
- Posts with up to 10 files, mixing clips and images.
- Send, Send all / Send selected (never publishes straight away), with progress on each card and Stash's Tasks page.
- Several blogs (one API key each), each with its own default action; keys are stored only by the plugin.
- Tag rules: send a Stash tag as one or more other imaglr tags, or never suggest it.
- Metadata stripped from every file (EXIF, GPS, XMP, IPTC, comments, video metadata and chapters) using Stash's
  own ffmpeg; no extra Python packages.
- Works with and without a Stash login; Stash v0.31.1 or later.
