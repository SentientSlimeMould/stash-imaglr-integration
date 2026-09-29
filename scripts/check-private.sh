#!/bin/sh
# Refuses (exit 1) if staged files contain the owner's personal details or a real-looking imaglr key.
# Run before every commit: scripts/check-private.sh && git commit ...
# Patterns live outside the repo (docs/private/private-patterns.txt, one extended regex per line) so
# this script does not itself publish them.
PATTERNS="$(dirname "$0")/../docs/private/private-patterns.txt"
[ -f "$PATTERNS" ] || { echo "check-private: $PATTERNS missing" >&2; exit 1; }
files=$(git diff --cached --name-only --diff-filter=ACMR)
[ -z "$files" ] && exit 0
if printf '%s\n' "$files" | xargs grep -niE -f "$PATTERNS" -- 2>/dev/null; then
  echo "check-private: personal details found in staged files (above). Not committing." >&2
  exit 1
fi
