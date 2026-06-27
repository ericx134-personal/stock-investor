#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"

fail() {
  echo "public export failed: $*" >&2
  exit 1
}

REMOTE="${PUBLIC_REVIEW_REMOTE:-$(git config --get remote.origin.url || true)}"
BRANCH="${PUBLIC_REVIEW_BRANCH:-main}"
OUT_DIR="${PUBLIC_REVIEW_OUTPUT_DIR:-$ROOT/public_exports}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PACKAGE_NAME="${PUBLIC_REVIEW_PACKAGE_NAME:-stock-investor-public-review-$STAMP}"

[[ -n "$REMOTE" ]] || fail "PUBLIC_REVIEW_REMOTE is empty and remote.origin.url is not configured"
command -v git >/dev/null || fail "git is required"
command -v zip >/dev/null || fail "zip is required"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stock-investor-public.XXXXXX")"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

CLONE_DIR="$WORK_DIR/$PACKAGE_NAME"
ZIP_PATH="$OUT_DIR/$PACKAGE_NAME.zip"
mkdir -p "$OUT_DIR"

echo "Cloning latest $BRANCH for public review package..."
git clone --quiet --depth 1 --branch "$BRANCH" "$REMOTE" "$CLONE_DIR"
SOURCE_COMMIT="$(git -C "$CLONE_DIR" rev-parse HEAD)"

echo "Removing Git history and local/private artifacts..."
rm -rf "$CLONE_DIR/.git"
rm -rf "$CLONE_DIR/data/private" "$CLONE_DIR/portfolio"
rm -f "$CLONE_DIR/.env" "$CLONE_DIR/service.env" "$CLONE_DIR/data/service.env"
rm -f "$CLONE_DIR"/scratch*.md
find "$CLONE_DIR" -name ".DS_Store" -delete
find "$CLONE_DIR" -name "*.pyc" -delete
find "$CLONE_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +

cat > "$CLONE_DIR/PUBLIC_REVIEW_PACKAGE.md" <<EOF
# Public Review Package

This zip is a sanitized source snapshot for external code review.

- Source branch: $BRANCH
- Source commit: $SOURCE_COMMIT
- Created UTC: $STAMP
- Git history: removed
- Local/private data removed: data/private, portfolio, .env, service.env, scratch files, caches

This package is for code review and architecture feedback. It intentionally
does not include private portfolio data, broker snapshots, credentials, local
logs, or generated private dashboards.
EOF

echo "Running package safety checks..."
[[ ! -d "$CLONE_DIR/.git" ]] || fail ".git history still exists in package"
[[ ! -e "$CLONE_DIR/data/private" ]] || fail "data/private still exists in package"
[[ ! -e "$CLONE_DIR/portfolio" ]] || fail "portfolio still exists in package"
[[ ! -e "$CLONE_DIR/.env" ]] || fail ".env still exists in package"
[[ ! -e "$CLONE_DIR/service.env" ]] || fail "service.env still exists in package"

token_pattern='AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+|sk-[A-Za-z0-9_-]{20,}'
identity_pattern="$(printf '%s%s_%s|%s%s%s' 'E' 'ricX' '1' 'er' 'icx' '134')"
package_hits="$(
  grep -RInE "$token_pattern|$identity_pattern" "$CLONE_DIR" \
    --exclude-dir=.git \
    --binary-files=without-match || true
)"
if [[ -n "$package_hits" ]]; then
  echo "$package_hits" >&2
  fail "package contains probable secret or personal identity marker"
fi

echo "Creating zip..."
rm -f "$ZIP_PATH"
(cd "$WORK_DIR" && zip -qr "$ZIP_PATH" "$PACKAGE_NAME")

if command -v shasum >/dev/null; then
  SHA256="$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}')"
elif command -v sha256sum >/dev/null; then
  SHA256="$(sha256sum "$ZIP_PATH" | awk '{print $1}')"
else
  SHA256="unavailable"
fi

echo "Public review package created:"
echo "$ZIP_PATH"
echo "source_commit=$SOURCE_COMMIT"
echo "sha256=$SHA256"
