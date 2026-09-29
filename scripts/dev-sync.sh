#!/bin/sh
# Copy the built plugin to a folder on this computer's own disk, which the local test Stash instances
# mount (dev/docker-compose.yml). The repo may live on a network share, and Docker's view of files that
# are rewritten on a share can go stale, so the test Stash never reads the plugin from the repo directly.
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${IMAGLR_DEV_PLUGIN:-$HOME/.imaglr-dev/plugin}"
mkdir -p "$dest"
rsync -a --delete --exclude data --exclude '.smbdelete*' --exclude '__pycache__' \
  "$root/plugins/imaglrIntegration/" "$dest/"
echo "synced plugin to $dest"
