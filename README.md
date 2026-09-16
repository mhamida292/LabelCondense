# Label Condense

Rebuilds the Whatnot **Combined Labels + Packing Slips** export so repeated
products collapse onto one line — keeping **every `#N` and its price** — and
re-interleaves them with the original shipping labels.

---

## Download

Go to the [Releases page](https://github.com/mhamida292/LabelCondense/releases)
and get one file. There is nothing to install.

| | |
|---|---|
| **Windows** | `label-condense.exe` — double-click it. The first time, Windows says "Windows protected your PC" because the file is not code-signed. Click **More info**, then **Run anyway**. |
| **Linux** | `label-condense` — run `chmod +x label-condense` once, then double-click. Needs Ubuntu 22.04 or newer. |

Then: drag a Whatnot export onto the icon, or open the app and click
**Choose file…**. Pick where to save, wait about 90 seconds while the progress
bar runs, and print.

**If it says `DO NOT PRINT`, don't print it.** Nothing was saved. Open the
**Logs** tab, click **Save report…**, and send that file over.

The download is around 100 MB because it carries its own copy of Ghostscript
and Poppler, so nothing has to be installed separately. See
[NOTICE.md](NOTICE.md).

---

## The command-line version

The original folder-based workflow still works, and is what's used on the
machine this was built for.

1. Drop the Whatnot export(s) into **`inbox/`**
2. In a terminal, run `./run.sh` (press **F4** in Dolphin to open one already
   in this folder)
3. Print from **`outbox/`**

You watch it work — a `rendering 84/152` counter ticks up per file, then a
one-line result. A full run is roughly 90 seconds per export.

(`.packing/` is a hidden folder holding processed sources and logs. You never
need to open it. Press Ctrl+H in Dolphin if you want to see it.)

### What a run looks like

```
Found 2 file(s) in inbox/

  export-morning.pdf
     OK   -> 2026-09-09-slips.pdf    304 pages, 3743 checks passed
  export-evening.pdf
     OK   -> 2026-09-09-slips-2.pdf  304 pages, 3743 checks passed

Done: 2 ready to print in outbox/
```

### Several files a day

Drop in as many as you like — each is processed separately and named
`YYYY-MM-DD-slips.pdf`, then `-2`, `-3`, and so on in the order processed.
Nothing overwrites anything, on the same day or across days.

### The one rule

If a file says **`FAIL`**, don't print it. Nothing is written to `outbox/`, and
the export stays in `inbox/` so a retry is just re-running `./run.sh`. The
reason is logged; send me `.packing/logs/<date>.log` and I'll fix it.

A pass is not a formality — each file is checked with roughly 26 assertions per
shipment (tracking numbers, addresses, every `#N`, every price, per-shipment and
grand totals, and every label compared pixel-by-pixel against its source and
confirmed paired with the right shipment). A 122-shipment export runs 3,244
checks; a 157-shipment one runs 4,395.

The audit is mutation-tested. Against the 122-shipment export: misfiling the
labels produces 122 failures, renumbering every `#` produces 302, corrupting
every subtotal produces 123.

### Options

```bash
./run.sh --fast   # skips the per-label pixel check, ~90s faster per file
                  # still runs ~3,300 of the checks
```

### Upkeep

None. Processed exports and logs are pruned automatically after 30 days.
`outbox/` is left alone — it's your output, delete what you've printed.

---

## Under the hood

`./run.sh` calls `src/whatnot_slips.py`, which can also be used directly:

```bash
python3 src/whatnot_slips.py build IN.pdf -o OUT.pdf --deep
python3 src/whatnot_slips.py verify IN.pdf OUT.pdf --deep
```

Requires `poppler-utils`, `ghostscript`, and Python 3 with Pillow — all already
installed here. Nothing to set up.

### Design notes

Non-obvious things that were fixed the hard way. Read before changing the renderer.

- **Item names.** An item block ends at a blank line or the seller boilerplate;
  the product name ends at its trailing `#N`, and anything after is description.
  Items with no `#N` at all print `no #` deliberately, so a missing number is
  visible rather than silent.
- **Fonts are re-encoded to ISO Latin-1**, with three overrides: code 39 →
  `quotesingle` (else `O'Leary` prints as `O’Leary`), code 45 → `hyphen`
  (ghostscript's ISOLatin1 has `/minus` there, which extracts as U+2212 and
  corrupts ZIP+4), and 173 → `hyphen`. Accented buyer names come through.
  Emoji and `™` are outside Latin-1 and become spaces — unavoidable, as the
  export's own text layer has no glyph mapping for them.
- **First-Class labels are landscape** (1800×1200) and must be rotated 90° CCW
  to fill the portrait sheet; parcel labels are already 1200×1800. Skipping this
  squashes the barcode.
- **Labels are reduced to 1-bit** (the source is 98.6% pure black/white), which
  is what a thermal printer does anyway — that's why output is ~3 MB, not 24 MB.
- **A single unit keeps its `#` inline** on the product row. Giving every unit
  its own row pushes dense slips onto a second page and undoes the grouping.
- **A dense slip may legitimately run to two pages.** The renderer already emits
  as many slip pages as the items need, so a shipment is *one or more* slip pages
  followed by exactly one label — the stride is not fixed at two. `verify()` used
  to assume it was, in four places (`out_pages[2 * k]`, `label_bitmap(out, 2 *
  (k + 1))`, and the two structural asserts); a 26-item order was the first to
  overflow and it failed the audit with 19 cascading errors on a correctly built
  PDF. The auditor now takes its page grouping from `load()`, which groups
  consecutive slip pages into a shipment. Don't reintroduce stride-2 arithmetic.

### Known limitations

- Order IDs aren't printed — eleven 10-digit IDs don't fit a 4×6. They're
  preserved in the parsed data if you want them added.
- Emoji in product names are lost (see above).
- Check the dot leaders and barcodes survive on **your** printer before a full
  batch; 0.7 pt dots can drop out on some thermal heads.
