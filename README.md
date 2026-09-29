# Imaglr Integration for Stash

A [Stash](https://github.com/stashapp/stash) plugin for sharing your favourite images and clips from Stash to
your [imaglr](https://imaglr.com) blogs.

- **Images:** tag them `imaglr` in Stash, crop if you like, and send.
- **Clips:** tag a scene marker `imaglr` (or create one from the plugin's tab on the scene page), trim, crop and send.
- **Tags:** suggested from your Stash tags, performers and studio, and editable before you send.
- **Where it goes:** your imaglr drafts (the default), your imaglr queue, or published straight away. Set a
  default for each blog and change it when you send.
- **Privacy:** location and camera data are stripped from every file before upload.

Requires an imaglr API key, which is currently only available to
[paid supporters](https://imaglr.com/subscriptions) (see [imaglr's API page](https://imaglr.com/developers)).

> **Status: in development.** Nothing is installable yet. This README will cover installation, settings, usage
> and limitations before the first release.

## Planned features

- A **Post to imaglr** page inside Stash (menu item **imaglr**) with **Clips**, **Images** and **Sent** tabs:
  trim and crop clips, edit tags and caption, then send.
- Several imaglr blogs (one API key each), with a default send action per blog that can be changed at send time.
- Sets: up to 10 images or clips in one post.
- Works on any Stash v0.31.1 or later install, on desktop and phone.

## AI assistance

This plugin is being written with the help of an AI coding assistant (Claude, by Anthropic). All code is reviewed
and tested by a human maintainer before release, in line with the
[CommunityScripts contribution guidelines](https://github.com/stashapp/CommunityScripts#readme).

## Licence

[AGPL-3.0](LICENCE), the same licence as Stash.
