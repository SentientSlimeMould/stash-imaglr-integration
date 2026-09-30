#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Public half of the privacy gate, also run in CI: things that should never be in an anonymous open-source
# repo whoever the author is — private-network addresses, local machine paths, e-mail addresses other than
# GitHub's noreply ones, tokens. Checks staged content when run as a hook (with an optional commit-message
# file as $1), or every tracked file with --all. POSIX sh + grep -E only (macOS and Linux).
PATTERN='(^|[^0-9.])(192\.168\.[0-9]+\.[0-9]+|10\.[0-9]+\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)([^0-9]|$)'
PATTERN="$PATTERN|/Users/[A-Za-z]|/Volumes/[A-Za-z]|/mnt/user/|C:\\\\Users\\\\|/home/[a-z]+/"
PATTERN="$PATTERN|pbk_[A-Za-z0-9]{4,}\|[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}"
EMAIL='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}'
ALLOWED_EMAIL='@users\.noreply\.github\.com|@anthropic\.com|@example\.'
status=0
scan() {  # $1 = label, stdin = content
  content=$(cat)
  hits=$(printf '%s\n' "$content" | grep -nE "$PATTERN" | head -5)
  mails=$(printf '%s\n' "$content" | grep -noE "$EMAIL" | grep -vE "$ALLOWED_EMAIL" | head -5)
  if [ -n "$hits$mails" ]; then
    printf '%s\n' "$hits" "$mails" | grep . >&2
    echo "check-generic: private-looking content in $1 (above)." >&2
    status=1
  fi
}
if [ "$1" = "--all" ]; then
  for f in $(git ls-files | grep -vE 'package-lock.json$|^scripts/check-generic.sh$'); do
    scan "$f" < "$f"
  done
else
  for f in $(git diff --cached --name-only --diff-filter=ACMR | grep -vE 'package-lock.json$|^scripts/check-generic.sh$'); do
    git show ":$f" | scan "staged $f"
  done
  if [ -n "$1" ] && [ -f "$1" ]; then
    scan "the commit message" < "$1"
  fi
fi
exit $status
