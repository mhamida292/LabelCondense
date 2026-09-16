#!/usr/bin/env bash
# Prove dist/label-condense works with no system poppler/ghostscript.
# Requires docker. Usage: packaging/smoke_test.sh /path/to/export.pdf
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: smoke_test.sh EXPORT.pdf}"

# Default to the glibc floor the Releases page promises (Ubuntu 22.04+), so
# this script can actually catch a floor regression. A bundle built on a
# newer glibc will fail to start here — that is the test working, not a bug.
#
# On a dev machine newer than the floor (this one runs glibc 2.43, which both
# libpython and system Tcl/Tk link against), a locally built bundle cannot
# satisfy 22.04. Override to sanity-check the bundling itself:
#     SMOKE_IMAGE=ubuntu:devel packaging/smoke_test.sh export.pdf
# That proves Ghostscript and Poppler travel correctly, but says nothing
# about the floor — only a CI build on ubuntu-22.04 can prove that.
IMAGE="${SMOKE_IMAGE:-ubuntu:22.04}"
docker run --rm \
  -v "$PWD/dist:/app:ro" -v "$(realpath "$SRC"):/in.pdf:ro" \
  "$IMAGE" \
  bash -c '
    set -e
    command -v gs        && { echo "FAIL: gs present, not a clean room"; exit 1; } || true
    command -v pdftotext && { echo "FAIL: poppler present"; exit 1; } || true
    /app/label-condense --selftest /in.pdf
  '
echo "SMOKE OK"
