#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Run the Python test suite inside the official Stash image (the real runtime: its Python and ffmpeg).
# Works from a copy on this computer's own disk, never by mounting the repo (which may be on a network
# share) into Docker.   Usage: scripts/test-in-stash.sh [image tag, default v0.31.1]
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
copy="${IMAGLR_DEV_REPO:-$HOME/.imaglr-dev/repo}"
mkdir -p "$copy"
rsync -a --delete --exclude .git --exclude node_modules --exclude 'plugins/imaglrIntegration/data' \
  --exclude '.smbdelete*' --exclude '__pycache__' --exclude '*.fresh' "$root/" "$copy/"
docker run --rm -v "$copy":/w -w /w --entrypoint python3 "stashapp/stash:${1:-v0.31.1}" \
  -m unittest discover -s tests/python -t .
