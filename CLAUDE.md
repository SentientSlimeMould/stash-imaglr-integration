# Working on this repository

Instructions for AI coding agents (and a reminder for humans). The owner is the final say on everything below.

## Ask before changing

- **README.md** — do not change its wording, structure or media without the owner's approval first. Propose
  the exact text, then edit only what was agreed. (Code-driven facts that go stale — a renamed setting, a new
  limitation — still need a proposal, not a silent edit.)
- Anything published: releases (`version:` in `plugins/imaglrIntegration/imaglrIntegration.yml`, tags), posts on
  the owner's real imaglr blogs, and anything sent to third parties.

## Always

- Run the privacy gate before every commit (`git config core.hooksPath .githooks` installs it as hooks). The
  repository is published anonymously: no names, e-mail addresses other than GitHub's noreply one, LAN addresses,
  local paths, hostnames, keys, or copied third-party documentation — in files, commit messages or screenshots
  (the scanner can't read pixels: check recordings frame by frame).
- Keep the UI Stash-native (Stash's own components, markup and CSS classes; never re-implement a Stash feature)
  and treat phone use as a first-class requirement.
- Python backend: standard library only, Python 3.9–3.14, Windows and macOS included. imaglr calls stay within the
  five allowlisted routes.
- Tests before a release: `npm run typecheck`, `npm test`, `npm run test:py`, `npm run test:py:stash`, and
  `python3 dev/e2e.py 9931` against the local test Stash. CI gates publishing on the same.
- Never mount the repository folder into Docker (it may live on a network share); the test instances use the local
  copy made by `npm run dev`.

See `CONTRIBUTING.md`, `dev/README.md` and `docs/stash-plugin-facts.md` for the rest.
