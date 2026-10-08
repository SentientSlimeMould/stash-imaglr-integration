# Changelog

## Unreleased

- **WebP** joins Video and GIF as a Format for clips: an animated WebP plays automatically in the feed like a GIF,
  has no sound, and is usually a third to a half of the GIF's size, so it loads faster. Same loop, picture size,
  preview and size ladder as GIF. (Needs an ffmpeg with the animated WebP encoder, which Stash's has.)
- **Preview a GIF before sending.** In the clip editor, **Preview GIF** makes the GIF exactly as it would be sent
  and shows it looping in place of the video, with its size, width and frame rate. Sending then uploads that
  very file. Any edit that changes the picture clears the preview, so what you see is always current.
- **Boomerang GIFs.** A **Loop** choice under Format: Forward, or Boomerang (forward then back), which loops
  without a jump. The estimate and the long-GIF warning allow for the doubled frames.
- A **Frame rate** for GIFs and WebPs under Format: Auto (the ladder's own, 15 at the top), or any of the
  usual rates up to the source's own; the estimate scales with it. The Format hint now states the pros and cons
  of whichever format is selected.
- A **Picture size** for GIFs under Format: Original (the feed width), 480 px or 320 px; the estimate follows.
- GIFs are sized for imaglr's feed: the first rung is now 698 px wide (the feed's content width) so a GIF is
  never shown upscaled, and the card says the width ("GIF · 9.4 MB · 698 px wide · 15 fps").

## 0.1.17 — 2026-10-08

- The menu icon is redrawn to the proportions of imaglr's own favicon: a narrower ring, a wider gap and a large
  highlight, all still visible at the smallest size.
- **Share a whole scene** without making a marker: tag the scene `imaglr` (one scene from its page, or several
  at once with the scene list's Edit button). It appears on the Clips tab as a clip over the scene's full length (up to the
  10-minute limit), with the scene's tags, performers and studio suggested, and everything in the editor works
  as for a marker clip. Trims stay in the plugin: the plugin still never creates or edits markers for you.
  Sending swaps the scene's tag to the sent tag, as it does for images.

## 0.1.16 — 2026-10-08

- The clip editor is laid out in sections: the preview and trim, then **Picture** (crop, edge trims, flip) and
  **Format** (video or GIF, codec, picture size, sound, with the size estimate), each folded away with a
  header that says what is set, e.g. "Format · Video · H.264 · 1080p · about 45 MB". The image editor has the
  same Picture section. Both remember whether you left them open.
- The crop can now **trim the edges** of a clip or image, for black borders the aspect presets couldn't
  remove: top, bottom, left and right in percent, with a **Detect borders** button that asks ffmpeg where
  the picture is (sampled across a clip's range). The aspect preset and its position apply inside what is
  left, the preview shows the result, and stills grabbed from a clip get the same controls.
- Videos are now sized for imaglr's real upload limit. Its API refuses any request over 100 MB (the
  documentation's 500 MB per video cannot be reached), so a long clip used to encode to several hundred MB and
  then fail. A clip is now encoded to fit 100 MB and the files of a multi-file post share that limit.
- Each clip has a **Codec** (H.264 or H.265) and a **Picture size** (Original, 720p or 480p) in the editor's
  **Format** section; only sizes smaller than the source are offered. The plugin never changes these for
  you: the editor estimates the size as you trim and warns when a long clip would look poor with the choices
  made. Two settings give new clips their defaults (**Clips as H.265 by default**, **Clip picture size by
  default**). The card shows what came out, e.g. "H.265 · 92.1 MB · 1280 px".

## 0.1.15 — 2026-10-04

- Clips can be sent as **animated GIFs** instead of videos (a **Format** choice in the editor; a plugin setting
  makes GIF the default for new clips). GIFs play straight away in feeds. imaglr's limit for a GIF is 40 MB, so
  the plugin makes a GIF smaller or slower, step by step, until it is under the **GIF size target** setting
  (20 MB unless changed); the editor estimates the size as you trim and warns on long clips, and the card shows
  what you got (e.g. "GIF · 9.4 MB · 480 px · 10 fps"). A GIF that can't fit even at its smallest fails with
  advice on how much to trim; **Send all** offers to send long clips as videos and, by default, falls back to a
  video for any GIF that won't fit.
- In the tag field, what you typed is offered first (so Enter adds it) unless a suggestion starts with it:
  typing "humping" no longer leaves you with only "dry humping" to pick.
- Hovering a clip card now plays Stash's marker preview: the plugin was pointing the player at the marker's
  still preview image, so nothing played.
- A sent clip whose Stash marker has since been deleted shows its scene's picture on the Sent tab instead of a
  broken image.

## 0.1.14 — 2026-10-02

- Clips can be **flipped horizontally** (a switch next to *Remove sound* in the editor). The crop is applied to
  the picture as you see it, then the result is mirrored.

## 0.1.13 — 2026-09-30

Interface polish (third batch from the code review).

- While something is being sent, the page polls a light status call instead of re-reading the whole list, keeps
  the list on screen if a refresh fails, and the editor of a sending item shows live progress.
- An expired Stash login takes you to the login page and back, as Stash does.
- **Select all** selects the current page, like Stash; Send all still covers every matching item. Removing or
  splitting several items is one call each instead of one per item.
- Changing the view or zoom keeps the current page; only filters, sort and page size go back to page 1.
- Card widths are fitted correctly after switching from list to grid view.
- On phones, small link-style buttons (Try again, Retry, Always drop, Edit/Remove rules, Split) are thumb-sized
  and the whole selection cell of a list row toggles it.
- Removing a tag rule asks first, like every other removal; the filter dialog closes on Escape or an outside
  click; the Sent details dialog is full screen on phones with a primary Close; Send all shows that it's
  checking before the plan appears.
- **Always drop** on the Sent tab now writes the rule for the Stash tag (or performer/studio name) the dropped
  imaglr tag came from, and only appears when that is known.
- Saved list settings from older versions can't break the list any more.
- Editing a file that belongs to a post being sent is refused; removing several items checks every marker
  before changing anything in Stash.

## 0.1.12 — 2026-09-30

Send-pipeline robustness (second batch from the code review).

- **Stop** now works during the upload and during rate-limit waits: the connection is dropped before imaglr has
  the whole post, so no draft is created.
- A network error after the whole upload went out is no longer retried (it could have created duplicate
  drafts); the item fails with a note to check your imaglr drafts.
- If the Stash tag swap fails after a send, the plugin remembers it and retries on the next page load instead of
  showing the same image or clip as newly queued (which risked sending it twice). Such failures are always
  reported, even alongside a queue/publish failure.
- Saving a clip's edits no longer rewrites the Stash marker (or regenerates previews) when only the sound or
  crop changed; marker times are stored to the millisecond.
- Send all runs an item as a draft without changing the item's own "Send as" setting; a send can no longer be
  queued twice by a double click.
- The plugin's database file is created readable by its owner only; Stash downloads never follow redirects
  with Stash's credentials; the development-only `IMAGLR_API_BASE` override refuses plain http to the internet
  and is reported by the ping check.
- Fewer database writes per page load; clearer messages when removing a sent item and after an interrupted send.
- README: limits on how many tagged items are shown, and that the plugins folder must not be on a network share.

## 0.1.11 — 2026-09-30

Fixes from a full code review (security, correctness, UI, release process).

- Fixed: grouping a clip or a still into a post broke the whole Post to imaglr page ("queue failed: 'bytes'").
- Fixed: Stash's own API key could appear in an error message, the sent history and Stash's log when a clip had
  to be read over HTTP and ffmpeg failed. Stream URLs no longer carry the key, and Stash's key and session
  cookie are masked wherever text leaves the plugin.
- Fixed: the tag refresh at send time (0.1.10) didn't actually run; Send all now uses current rules and Stash tags.
- Fixed: an unexpected error during a send left the item "Preparing" for ever with a misleading message; it is
  now marked failed with the reason, and anything that goes wrong after the draft exists still records the item
  as sent.
- Editor: a **Save** button keeps your edits (tags, caption, crop, trim, blog, send-as) without sending, so Send
  all can use each item's settings. Cancel still discards. The "Publish now" confirmation is a dialog.
- Removing several items at once says when stills will be deleted (they only exist in the plugin).
- Rate-limit messages name the right limit (daily posts vs hourly requests).
- README: what exactly is sent to imaglr, how keys are stored, that anyone who can use your Stash can use the
  plugin; status banner and AI-assistance statement updated.
- Project: releases now publish only after the tests pass and only when the version changed; an end-to-end test
  runs the built plugin inside Stash against the fake imaglr on every push; privacy checks run as git hooks and
  in CI; tests for the send pipeline.

## 0.1.10 — 2026-09-30

- Tag rules (and tag changes made in Stash) now apply to items already waiting, not just newly queued ones. An
  item's tags follow its Stash tags and the rules until you edit them in the editor; the editor says which is
  the case and offers "Use the suggested tags again". Refreshed when the list loads, when the editor opens and
  at send time, so Send all picks up rule changes too.

## 0.1.9 — 2026-09-30

- Removed the **imaglr** section added to image pages in 0.1.8: images and clips are queued the same way again
  (the `imaglr` tag, or the image lists' ⋯ menu).

## 0.1.8 — 2026-09-30

- Added an **imaglr** section to image pages (withdrawn in 0.1.9).

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
