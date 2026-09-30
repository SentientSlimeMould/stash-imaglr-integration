#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Refuses (exit 1) if what is about to be committed contains the owner's personal details or a real-looking
# imaglr key. Checks the STAGED content (not the working copy) and, when given a file, the commit message.
# Installed as a git hook by `git config core.hooksPath .githooks` (see dev/README.md); can also be run by hand:
#   scripts/check-private.sh && git commit ...
# The owner's patterns live outside the repo (docs/private/private-patterns.txt, one extended regex per
# line) so this script does not itself publish them; scripts/check-generic.sh holds the public ones.
here="$(cd "$(dirname "$0")" && pwd)"
PATTERNS="$here/../docs/private/private-patterns.txt"
[ -f "$PATTERNS" ] || { echo "check-private: $PATTERNS missing" >&2; exit 1; }
status=0
# 1. staged file contents
for f in $(git diff --cached --name-only --diff-filter=ACMR | grep -v '^scripts/check-generic.sh$'); do
  if git show ":$f" | grep -niE -f "$PATTERNS" -- >/dev/null 2>&1; then
    echo "check-private: personal details in staged $f:" >&2
    git show ":$f" | grep -niE -f "$PATTERNS" -- | head -5 >&2
    status=1
  fi
done
# 2. the commit message, when the commit-msg hook passes its file
if [ -n "$1" ] && [ -f "$1" ]; then
  if grep -niE -f "$PATTERNS" -- "$1" >/dev/null 2>&1; then
    echo "check-private: personal details in the commit message. Not committing." >&2
    status=1
  fi
fi
# 3. the generic patterns too
"$here/check-generic.sh" "$@" || status=1
[ "$status" -eq 0 ] || echo "check-private: not committing." >&2
exit $status
