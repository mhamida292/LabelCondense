#!/usr/bin/env bash
# Process every Whatnot export sitting in inbox/ and put print-ready PDFs in outbox/.
#   ./run.sh            process everything in inbox/, full audit
#   ./run.sh --fast     skip the per-label pixel check (~90s/file faster)
#   ./run.sh --no-prices  print slips without prices
#   ./run.sh --pick-list  put a pick list at the front of the PDF
set -uo pipefail
cd "$(dirname "$0")"

TOOL=src
IN=inbox; OUTBOX=outbox; ARCH=.packing/archive; LOGS=.packing/logs
KEEP_DAYS=30                 # archives and logs older than this are pruned
DEEP=--deep
EXTRA=()

for a in "$@"; do
  case "$a" in
    --fast) DEEP="" ;;
    --no-prices) EXTRA+=(--no-prices) ;;
    --pick-list) EXTRA+=(--pick-list) ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

mkdir -p "$IN" "$OUTBOX" "$ARCH" "$LOGS"
STAMP=$(date +%Y-%m-%d)
LOG="$LOGS/$STAMP.log"

shopt -s nullglob nocaseglob
files=("$IN"/*.pdf)
shopt -u nocaseglob

if [ ${#files[@]} -eq 0 ]; then
  echo "inbox/ is empty — drop today's Whatnot export in there, then run this again."
  exit 0
fi

echo "Found ${#files[@]} file(s) in $IN/"
echo

ok=0; fail=0; skip=0
for src in "${files[@]}"; do
  base=$(basename "$src")

  # a file written seconds ago may still be downloading
  if [ $(( $(date +%s) - $(stat -c %Y "$src") )) -lt 5 ]; then
    echo "  SKIP  $base — still being written, run again in a moment"
    skip=$((skip+1)); continue
  fi

  # pick a free name in outbox
  n=1; out="$OUTBOX/$STAMP-slips.pdf"
  while [ -e "$out" ]; do n=$((n+1)); out="$OUTBOX/$STAMP-slips-$n.pdf"; done

  echo "  $base"
  { echo "=== $(date '+%F %T')  $base -> $out"; } >> "$LOG"
  # stdout (the audit report) -> log; stderr (live progress) stays on screen
  if python3 "$TOOL/whatnot_slips.py" build "$src" -o "$out" $DEEP ${EXTRA[@]+"${EXTRA[@]}"} >>"$LOG"; then
    pages=$(pdfinfo "$out" | awk '/^Pages:/{print $2}')
    checks=$(grep -a 'assertions run' "$LOG" | tail -1 | tr -dc 0-9)
    echo "     OK   -> $(basename "$out")  ${pages} pages, ${checks} checks passed"
    # archive the source under a name that cannot collide
    dest="$ARCH/$STAMP-$base"; m=1
    while [ -e "$dest" ]; do m=$((m+1)); dest="$ARCH/$STAMP-${m}-$base"; done
    mv "$src" "$dest"
    ok=$((ok+1))
  else
    echo "     FAIL -> left in inbox/, nothing to print. See $LOG"
    rm -f "$out"
    fail=$((fail+1))
  fi
done

# housekeeping: nothing to remember, nothing to clean by hand
find "$ARCH" -type f -mtime +$KEEP_DAYS -delete 2>/dev/null
find "$LOGS" -type f -mtime +$KEEP_DAYS -delete 2>/dev/null

echo
if [ $fail -eq 0 ]; then
  msg="Done: $ok ready to print in $OUTBOX/"
  [ "$skip" -gt 0 ] && msg="$msg ($skip skipped)"
  echo "$msg"
else
  echo "Done: $ok ok, $fail FAILED (still in inbox/, do not print)"
fi
[ $fail -eq 0 ]
