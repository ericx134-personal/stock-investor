#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "public-safety check failed: $*" >&2
  exit 1
}

tracked_private_paths="$(
  git ls-files | grep -E '(^data/private/|^portfolio/|(^|/)\.env$|(^|/)service\.env$|(^|/)\.DS_Store$)' || true
)"
if [[ -n "$tracked_private_paths" ]]; then
  echo "$tracked_private_paths" >&2
  fail "private, local, or generated files are tracked"
fi

grep -qxF 'data/private/' .gitignore || fail ".gitignore must ignore data/private/"
grep -qxF 'portfolio/' .gitignore || fail ".gitignore must ignore portfolio/"
grep -qxF '.env' .gitignore || fail ".gitignore must ignore .env"

token_hits="$(
  git grep -n -I -E \
    'AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+|sk-[A-Za-z0-9_-]{20,}' \
    -- . || true
)"
if [[ -n "$token_hits" ]]; then
  echo "$token_hits" >&2
  fail "probable secret token committed"
fi

echo "public-safety check passed"
