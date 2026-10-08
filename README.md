# Imaglr Integration for Stash

A [Stash](https://github.com/stashapp/stash) plugin for sharing your favourite images and clips from Stash to
your [imaglr](https://imaglr.com) blogs.

- **Share Images:** add the tag `imaglr` to an image, or multi-select them in any image list and choose **⋯ → Add to imaglr**. 
- **Share Clips:** create a scene marker in Stash and tag it `imaglr`. You can fine-tune the edit if needed before sending.
- **Share a whole scene:** tag the scene `imaglr` and it joins the Clips tab over its full length, no marker needed. Trim it in the editor like any clip.
- **GIF or video:** each clip can go out as an animated GIF, which plays straight away in feeds, or as a video. The plugin shrinks a GIF step by step until it fits imaglr's limit.
- **Tags:** Tags for your imaglr posts are suggested from your Stash tags (including performers, studio and galleries). These can be edited before sending.
- **Tag Mapping:** Set up rules on your Stash tags to automatically translate them to one or many corresponding Imaglr tags. 
- **Draft, Queue or Publish immediately:** You can set a default upload action for each blog you want to send to and alter that if needed any time you send.
- **Privacy:** location, camera and other metadata are removed from every file before upload.

> **Status: early release (0.1.x).** It works end to end and is tested on Stash v0.31.1 and the development
> build, but it hasn't been used widely yet. Please report problems on the
> [issue tracker](https://github.com/SentientSlimeMould/stash-imaglr-integration/issues).

## Demos

Performed on a demo library of public-domain films and NASA images.

### 1 · Tag media & send it to Imaglr

Select an image from Stash's library, click **⋯ → Add to imaglr**, then in the imaglr tab, you can make your final edits before sending to your blog.

https://github.com/user-attachments/assets/2c2d1845-b4b8-4f8f-981d-3dab37551908

---

### 2 · Clips created from markers - no video editing knowledge, bit-rate or codec tweaking is needed to fit within Imaglr's upload limits

Make a marker on a scene the same way you bookmark your favourite bits, tag the marker `imaglr`, trim the in and out points in the editor
if necessary and send to Imaglr.

https://github.com/user-attachments/assets/5a98b1db-fe1a-4b8b-a2da-eb19c941e514

---

### 3 · Create posts from several images

Select a few images, **Add to imaglr as one post**, put them in order, select the blog and publish. 

https://github.com/user-attachments/assets/4a9fb196-368e-48a4-86b4-b03ec7e26b87

<sub>Demo media: Prelinger Archives films via archive.org and NASA images, all public domain. The clips are also
in [docs/media](docs/media).</sub>

## Requirements

- **Stash v0.31.1 or later.** The official Docker image has everything the plugin needs. Other installs need
  **Python 3.9 or later** available to Stash (Settings → System → **Python executable path**); no extra Python
  packages are needed. On macOS with Python from python.org, run its **Install Certificates.command** once,
  or HTTPS to imaglr fails with a certificate error.
- **An imaglr API key** for each blog you want to post to. imaglr's API is currently only available to
  [paid supporters](https://imaglr.com/subscriptions) (see [imaglr's API page](https://imaglr.com/developers)).
  Create the key on imaglr under **Settings → API** with these permissions:
  - **read**: lets the plugin check the blog's name, supporter status and daily limit;
  - **manage**: drafts, including publishing or queueing a draft, which is how everything is posted.

  Leave **write** off: weirdly, this permission is not needed?! - Likely to change, as the Imaglr API is currently in Beta. 

The plugin's Settings show each blog's **posts left today**, as reported by imaglr. imaglr allows 1,000 new posts
a day; saving a draft doesn't use one, publishing does (including when imaglr publishes from your queue).

## Install

1. In Stash, go to **Settings → Plugins → Available Plugins → Add Source** and enter:
   - **Name:** `Imaglr Integration`
   - **Source URL:** `https://sentientslimemould.github.io/stash-imaglr-integration/stable/index.yml`
   - **Local path:** `imaglr`
2. Expand the new source, tick **Imaglr Integration** and choose **Install**.
3. Reload the Stash page. A new **imaglr** entry appears in the main menu.

## Set up

1. Open **imaglr** in the menu, then **Settings**.
2. Under **Add a blog**, paste an API key and choose what a post becomes on that blog by default (**Send as**):
   **Draft**, **Queued** or **Published**. The plugin checks the key with imaglr before saving it.
   Repeat for each blog.
3. Optional: under **Tag rules**, choose Stash tags that should always be sent as different imaglr tags (one Stash
   tag can become several tags for your Imaglr post) e.g. a Stash tag of "Ham" can be configured to always automatically convert to the Imaglr tags "Ham", "Meat", "Deli Meat".

A few more options live in Stash under **Settings → Plugins → Imaglr Integration**: the queue tag (default
`imaglr`), the tag applied after sending (default `imaglr-sent`), tags never suggested (default `^AI_`), keeping
tag capitals, the default clip length, whether new clips start as GIFs, the GIF size target, the default codec and
picture size for clips, and how long prepared files are kept.

## Use

- **Queue things in Stash.** Tag images, scene markers or whole scenes `imaglr`. In any image list (including a gallery's
  Images tab) you can also tick images and choose **⋯ → Add to imaglr**, or **⋯ → Add to imaglr as one post** for
  up to 10 images in a single post.
- **Open imaglr → Clips or Images.** Search, filter, sort and select items. Select several
  cards and choose **Make one post** to combine clips and images into one post.
- **Tap a card to edit it:** crop, including trimming the edges off black borders (there's a button that finds
  them); for clips, set in and out points (written back to the Stash marker), output as GIF or video, choose the
  codec and picture size, remove the sound or save a still; edit tags and caption; choose the blog and what
  happens when sent. Then press the send button.
- **Send all** sends every item shown (or the ticked ones) using each item's settings. It never publishes
  straight away: items set to Publish now are saved as drafts instead.
- **Sent** lists where each post went, which tags imaglr dropped, and lets you retry queueing or publishing if
  that step failed after the draft was saved.

Sending is queued as a Stash task, so it shows on Stash's **Settings → Tasks** page.

## What the plugin changes

**In Stash** it only ever:

- creates the queue tag and the sent tag (`imaglr`, `imaglr-sent`) if they don't exist, reusing an existing tag
  with that name (whatever its capitalisation) or with that name as an alias;
- adds the queue tag to images you choose **Add to imaglr** for, and removes it when you choose **Remove "imaglr"
  tag**;
- swaps the queue tag for the sent tag on markers and images you've sent;
- writes trimmed start and end times back to markers, and asks Stash to regenerate those markers' previews.

It never modifies, moves or deletes your media files, and it never creates markers.

**Its own data** — the imaglr API keys, the sent history, tag rules and prepared files — are kept in its `data`
folder inside Stash's plugins directory, in a SQLite database.
**On imaglr** it can only make these five calls: read your profile, read your API rate limits, create a
draft, and publish or queue a draft it has just created. It never edits or deletes posts, changes your queue
settings or reads your feed.

**What is sent to imaglr** for each post: the prepared files (metadata stripped), each with a file name made from
the Stash title or original file name (letters, digits and dashes only — rename in Stash first if a name says
too much); the tags and caption you chose; and the plugin's name and version as the `User-Agent`. Nothing about
your Stash library, other files or your machine.

**Nothing else:** no telemetry and no other network connections.

## Limitations

- Stash runs one task at a time in a queue, so clip exports and uploads can be held up by Stash's own tasks such
  as scans and vice versa.
- HDR videos are not tone-mapped; colours may look flat.
- imaglr's API refuses any upload over 100 MB, whatever its documentation says, so a video is encoded to fit that.
  A long clip is encoded at a lower bitrate to fit; the editor estimates the size as you trim and warns when a
  smaller picture or H.265 would look better.
- imaglr accepts GIFs up to 40 MB. A long clip, or one with a lot of movement, may only fit as a GIF at a low frame
  rate and resolution; the editor estimates the size as you trim, and Send all can fall back to a video for any GIF
  that won't fit.
- Animated WebP images can be sent as they are, but not cropped or converted to video (Stash's ffmpeg can't read
  them).
- If you stop a send from Stash's Tasks page on macOS or Windows, the ffmpeg process may continue to run on until 
  it finishes.
- The page shows at most 1000 tagged images, 500 tagged markers and 500 tagged scenes at a time; send some before
  tagging more.
- The plugin's `data` folder holds a SQLite database, which doesn't always work reliably on network shares (SMB/NFS).
  Keep Stash's plugins directory on a local disk, as Stash itself needs for its own database.
  The plugin's own **Stop sending** button stops cleanly everywhere.

## Updating and uninstalling

Updates appear under **Settings → Plugins → Installed Plugins → Check for updates**. After updating, do a hard
refresh of the browser tab (Ctrl/Cmd+Shift+R): the browser keeps the old copy of the plugin's page otherwise. The
footer of the **Post to imaglr** page shows which version is running.

Uninstalling removes the plugin's files but **leaves its `data` folder** — your blogs and their API keys, the sent
history, tag rules and working files — and your Stash tags. Stash's plugin manager doesn't ask; it only removes
what it installed, so the plugin folder itself may also remain (Python leaves a `__pycache__` folder in it). If
you're removing the plugin for good, first open the **Post to imaglr** page, press its **Settings** button and
use **Delete all plugin data** at the bottom; then, after uninstalling, delete what is left of
`<Stash plugins folder>/imaglr/imaglrIntegration` if you want a clean plugins folder. Reinstalling or updating
keeps everything, which is what you usually want.

## Development

See [dev/README.md](dev/README.md) for the local test environment (Stash in Docker with synthetic test media and a
fake imaglr) and how to run the tests.

## AI assistance

This plugin is being written with the help of an AI coding assistant (Claude, by Anthropic). All code is reviewed
and tested by a human maintainer before release, who takes full responsibility for it, including licence
compliance, in line with the
[CommunityScripts contribution guidelines](https://github.com/stashapp/CommunityScripts#readme).

## Licence

[AGPL-3.0](LICENCE), the same licence as Stash.
