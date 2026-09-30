# Imaglr Integration for Stash

A [Stash](https://github.com/stashapp/stash) plugin for sharing your favourite images and clips from Stash to
your [imaglr](https://imaglr.com) blogs.

- **Images:** tag them `imaglr` in Stash (or tick them in any image list and choose **⋯ → Add to imaglr**),
  crop if you like, and send.
- **Clips:** create a scene marker in Stash as usual and tag it `imaglr`. Trim, crop and send.
- **Tags:** suggested from your Stash tags, performers, studio and galleries, and editable before you send.
- **Where it goes:** your imaglr drafts (the default), your imaglr queue, or published straight away. Set a
  default for each blog and change it when you send.
- **Privacy:** location, camera and other metadata are stripped from every file before upload.

> **Status: first test release (0.1.0).** It works end to end, but it hasn't been used widely yet. Please report
> problems on the [issue tracker](https://github.com/SentientSlimeMould/stash-imaglr-integration/issues).

## Requirements

- **Stash v0.31.1 or later.** The official Docker image has everything the plugin needs. Other installs need
  **Python 3.9 or later** available to Stash (Settings → System → **Python executable path**); no extra Python packages are needed.
- **An imaglr API key** for each blog you want to post to. imaglr's API is currently only available to
  [paid supporters](https://imaglr.com/subscriptions) (see [imaglr's API page](https://imaglr.com/developers)).
  Create the key on imaglr under **Settings → API** with these permissions:
  - **read**: lets the plugin check the blog's name, supporter status and daily limit;
  - **manage**: drafts, including publishing or queueing a draft, which is how everything is posted.

  Leave **write** off: it allows creating, editing and deleting posts directly, which the plugin never does.

The plugin's Settings show each blog's **posts left today**, as reported by imaglr. imaglr allows 1,000 new posts
a day; saving a draft doesn't use one, publishing does (including when imaglr publishes from your queue).

## Install

1. **Back up Stash first:** Settings → Tasks → **Backup** (use **Download backup** to keep a copy elsewhere).
2. In Stash, go to **Settings → Plugins → Available Plugins → Add Source** and enter:
   - **Name:** `Imaglr Integration`
   - **Source URL:** `https://sentientslimemould.github.io/stash-imaglr-integration/stable/index.yml`
   - **Local path:** `imaglr`
3. Expand the new source, tick **Imaglr Integration** and choose **Install**.
4. Reload the Stash page. A new **imaglr** entry appears in the main menu.

## Set up

1. Open **imaglr** in the menu, then **Settings**.
2. Under **Add a blog**, paste an API key and choose what should happen by default when you send to that blog:
   **Save as draft**, **Add to queue** or **Publish now**. The plugin checks the key with imaglr before saving it.
   Repeat for each blog.
3. Optional: under **Tag rules**, choose Stash tags that should always be sent as different imaglr tags (one Stash
   tag can become several), or never suggested.

A few more options live in Stash under **Settings → Plugins → Imaglr Integration**: the queue tag (default
`imaglr`), the tag applied after sending (default `imaglr-sent`), tags never suggested (default `^AI_`), keeping
tag capitals, the default clip length, and how long prepared files are kept.

## Use

- **Queue things in Stash.** Tag images or scene markers `imaglr`. In any image list (including a gallery's
  Images tab) you can also tick images and choose **⋯ → Add to imaglr**, or **⋯ → Add to imaglr as one post** for
  up to 10 images in a single post.
- **Open imaglr → Clips or Images.** Search, filter, sort and select work like Stash's own lists. Tick several
  cards and choose **Make one post** to combine clips and images into one post.
- **Tap a card to edit it:** crop; for clips, set in and out points (written back to the Stash marker), remove
  the sound or save a still; edit tags and caption; choose the blog and what happens when sent. Then press the
  send button, which says exactly what it will do. **Publish now** asks for confirmation.
- **Send all** sends every item shown (or the ticked ones) using each item's settings. It never publishes
  straight away: items set to Publish now are saved as drafts instead.
- **Sent** lists where each post went, which tags imaglr dropped, and lets you retry queueing or publishing if
  that step failed after the draft was saved.

Sending runs as a Stash task, so it also shows on Stash's **Settings → Tasks** page.

## What the plugin changes

**In Stash** it only ever:

- creates the queue tag and the sent tag (`imaglr`, `imaglr-sent`) if they don't exist, reusing existing tags
  whatever their capitalisation;
- adds the queue tag to images you choose **Add to imaglr** for, and removes it when you choose **Remove "imaglr"
  tag**;
- swaps the queue tag for the sent tag on markers and images you've sent;
- writes trimmed start and end times back to markers, and asks Stash to regenerate those markers' previews.

It never modifies, moves or deletes your media files, and it never creates markers. Its own data (including the
imaglr API keys) is kept in its `data` folder inside Stash's plugins directory.

**On imaglr** it can only make these five calls, enforced by a test: read your profile, read your limits, create a
draft, and publish or queue a draft it has just created. It never edits or deletes posts, changes your queue
settings or reads your feed.

**Nothing else:** no telemetry and no other network connections.

## Limitations

- Stash runs one task at a time, so long clip exports and uploads wait for (and hold up) Stash's own tasks such
  as scans.
- HDR videos are not tone-mapped; colours may look flat.
- Animated WebP images can be sent as they are, but not cropped or converted to video (Stash's ffmpeg can't read
  them).
- If you stop a send from Stash's Tasks page on macOS or Windows, the ffmpeg process may run on until it finishes.
  The plugin's own **Stop sending** button stops cleanly everywhere.

## Updating and uninstalling

Updates appear under **Settings → Plugins → Installed Plugins → Check for updates**. Uninstalling removes the
plugin's files but leaves its `data` folder (your blogs, keys, history and prepared files) and your Stash tags;
delete `<Stash plugins folder>/imaglr/imaglrIntegration/data` yourself if you don't need it.

## Development

See [dev/README.md](dev/README.md) for the local test environment (Stash in Docker with synthetic test media and a
fake imaglr).

## AI assistance

This plugin is being written with the help of an AI coding assistant (Claude, by Anthropic). All code is reviewed
and tested by a human maintainer before release, in line with the
[CommunityScripts contribution guidelines](https://github.com/stashapp/CommunityScripts#readme).

## Licence

[AGPL-3.0](LICENCE), the same licence as Stash.
