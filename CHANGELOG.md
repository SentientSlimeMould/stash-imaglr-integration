# Changelog

## 0.1.9 — 2026-09-30

- Removed the **imaglr** section added to image pages in 0.1.8: images and clips are queued the same way again
  (the `imaglr` tag, or the image lists' ⋯ menu).

## 0.1.7 — 2026-09-30

- Fixed: saving, listing or deleting a tag rule failed with "name '_rules' is not defined" since 0.1.3 (a helper
  was lost in the Sent-tab refactor). Tests now cover the tag-rule operations, and a check that every
  operation only uses names that exist.

## 0.1.6 — 2026-09-30

- **Settings → Delete all plugin data**: removes every blog and API key, the sent history, tag rules and working
  files, for a clean slate before uninstalling. Stash's plugin manager leaves the plugin's `data` folder (and so
  the keys) in place on uninstall; the README now says so.

## 0.1.5 — 2026-09-30

- In the editor and the Sent details, the clip or image name links back to Stash: an image opens its image
  page; a clip opens its scene playing from the clip's start (Stash can't open a scene on its Markers tab from
  a link, and markers have no page of their own). The thumbnails of a multi-file post link the same way.

## 0.1.4 — 2026-09-30

- Fixed: **Remove "imaglr" tag** did nothing for clips; the marker kept its tag and the clip came back. It now
  removes the tag from the marker. When `imaglr` is the marker's primary tag, the next tag becomes primary;
  when it is the marker's only tag the plugin says so (Stash markers must keep a primary tag) instead of
  silently failing.
- Confirmations are Stash-style dialogs instead of the browser's popup (remove tag, delete still, remove blog,
  custom page size).
- Editor dialog is titled "Post to imaglr"; the clip / image name is shown inside it. Same for "Sent to imaglr".
- "When sent" is now "Send as": Draft, Queued or Published (in the editor and blog settings).
- The tag field is labelled "imaglr tags".

## 0.1.3 — 2026-09-30

- Sent tab now works like Clips and Images: the same toolbar (search, filter by blog or by draft/queued/published,
  sort by sent date, name or blog, page size), the same cards (grid or list, zoom) and paging. Searching,
  filtering and sorting run on the plugin side, so a long history stays quick.
- Tapping a sent card opens its details: the files it contained (each linking to its Stash page), blog, date,
  link on imaglr, tags kept and dropped (with "Always drop"), caption, and the retry when queueing or
  publishing failed.

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
