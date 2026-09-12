#!/usr/bin/env bash
# Prove dist/packing-slips works with no system poppler/ghostscript.
# Requires docker. Usage: packaging/smoke_test.sh /path/to/export.pdf
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: smoke_test.sh EXPORT.pdf}"

# ubuntu:devel, not 22.04: the bundle links against the build host's glibc
# (this machine runs Ubuntu 26.04 / glibc 2.43 — both Python's libpython and
# system Tcl/Tk are built against it), and glibc is forward-compatible only,
# so an older image can't run it. ubuntu:devel is the closest stock image
# with a matching-or-newer glibc; a machine on an older Ubuntu should build
# (and smoke-test) with its own toolchain rather than this exact tag. This
# is unrelated to Ghostscript and Poppler, which stay absent from the image
# below.
docker run --rm \
  -v "$PWD/dist:/app:ro" -v "$(realpath "$SRC"):/in.pdf:ro" \
  ubuntu:devel \
  bash -c '
    set -e
    command -v gs        && { echo "FAIL: gs present, not a clean room"; exit 1; } || true
    command -v pdftotext && { echo "FAIL: poppler present"; exit 1; } || true
    /app/packing-slips --selftest /in.pdf
  '
echo "SMOKE OK"
