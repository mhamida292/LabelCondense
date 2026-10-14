#!/usr/bin/env bash
# Prove "dist/Label Condense.app" works with Homebrew out of the way. Meant for
# CI: it moves the Homebrew prefix aside with sudo and puts it back on exit.
# Usage: packaging/smoke_test_macos.sh [EXPORT.pdf]
set -euo pipefail
cd "$(dirname "$0")/.."
APP="dist/Label Condense.app"
BIN="$APP/Contents/MacOS/label-condense"
BREW="${HOMEBREW_PREFIX:-/opt/homebrew}"

# 1. Nothing in the bundle may still load a library from Homebrew.
bad=0
while IFS= read -r -d '' f; do
  file -b "$f" | grep -q Mach-O || continue
  if otool -L "$f" | tail -n +2 | grep -E "^\s*($BREW|/usr/local)/"; then
    echo "FAIL: $f loads from Homebrew"; bad=1
  fi
done < <(find "$APP" -type f -print0)
[ "$bad" = 0 ]

# 2. Clean room: hide Homebrew, then run the app's own selftests.
sudo mv "$BREW" "$BREW.off"
trap 'sudo mv "$BREW.off" "$BREW"' EXIT
command -v gs        && { echo "FAIL: gs still on PATH"; exit 1; } || true
command -v pdftotext && { echo "FAIL: poppler still on PATH"; exit 1; } || true

"$BIN" --selftest                     # bundled gs renders a branded slip
if [ $# -ge 1 ]; then
  "$BIN" --selftest "$1"              # a full run, when an export is to hand
else                                  # otherwise each poppler tool must start
  for t in pdftotext pdfimages pdftoppm; do
    "$APP/Contents/Frameworks/bin/$t" -v
  done
fi
echo "SMOKE OK"
