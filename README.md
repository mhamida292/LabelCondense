# Label Condense

Rebuilds the Whatnot **Combined Labels + Packing Slips** export so repeated
products collapse onto one line — keeping **every `#N` and its price** — and
re-interleaves them with the original shipping labels.

**TikTok Shop** label + packing slip exports work too. The app tells the two
apart by itself: drop either one in. On a TikTok live auction the lot number
(the Seller SKU) becomes the `#N`, so a buyer's nine wins print as one line
with nine numbers under it.

---

## Download

Go to the [Releases page](https://github.com/mhamida292/LabelCondense/releases)
and get one file. There is nothing to install.

| | |
|---|---|
| **Windows** | `label-condense.exe` — double-click it. The first time, Windows says "Windows protected your PC" because the file is not code-signed. Click **More info**, then **Run anyway**. |
| **Linux** | `label-condense` — run `chmod +x label-condense` once, then double-click. Needs Ubuntu 22.04 or newer. |
| **Mac** | `LabelCondense-mac.zip` — unzip it and drag **Label Condense** into Applications. Apple Silicon (M1 or newer) with macOS 14.8 or newer. The first open is refused because the app is not signed: open **System Settings → Privacy & Security**, scroll down, click **Open Anyway**. |

Then: drag a Whatnot export onto the icon, or open the app and click
**Choose file…**. Pick where to save, wait about 90 seconds while the progress
bar runs, and print.

To put your logo and a thank-you note on the slips, open the **Branding** tab, fill it in, click **Preview slip**, then **Save**. Every run after that uses it. `./run.sh` uses the same settings; pass `--no-brand` to `whatnot_slips.py` to skip them (that drops the footer too).

The Branding tab also has a **Footer message** (2 lines, 120 characters) printed at the bottom of every slip; **Show footer on slips** turns it on or off separately from the header message. On the Run tab, untick **Show prices** to print slips without prices, and tick **Add pick list** to put a pick list (each product once, with the quantity to pull) at the front of the PDF. Untick **Condense repeated items** to give every item its own row instead of grouping repeats.

For a TikTok export the pick list is different: every lot number in order, two columns, with the buyer's nickname beside it, grouped by show (two shows can both have a #69). The TikTok slip keeps TikTok's own fields at the top (order ID, created time, ship-by, tracking number, show name) and the buyer ID and nickname at the bottom. TikTok labels arrive on A6 pages; the label is cut out and scaled evenly to fill the 4×6, never stretched.

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
./run.sh --no-prices  # print slips without prices
./run.sh --pick-list  # put a pick list at the front of the PDF
./run.sh --no-condense  # one row per item; repeats are not grouped
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
- **Labels come from rendering the page, never from extracting its images.**
  `pdfimages` writes a label's artwork *and* its transparency mask as separate
  files of byte-identical size, so picking "the biggest one" was decided by
  unsorted directory order. It chose the blank mask and printed an empty label
  twice — Sept 16 shipment 61 (domestic Ground Advantage) and Sept 20 shipment
  77 (First-Class International). Two of 732 shipments carried such a mask.
  `label_bitmap()` now renders the page with `pdftoppm`, which composites the
  mask exactly as the printer will. Don't reintroduce image extraction here.
- **The auditor must not reuse the renderer's extraction path.** The blank
  labels passed `--deep` with zero failures because `verify()` called the same
  `label_bitmap()` on both sides and compared blank to blank. The auditor now
  reads the output with `embedded_bitmap()` — a different route — and asserts
  no label is blank on either side. This is the second time a shared helper
  blinded the audit to its own bug; the first was `address()` (commit f5c214d).
- **First-Class labels are landscape** (1800×1200), but Whatnot already lays
  them sideways on a portrait page, so a rendered page needs no rotation of its
  own — it arrives oriented exactly as the old extract-and-rotate path left it.
  `_to_1bit()` still rotates a page that is *itself* landscape. Rotating a
  correctly-placed label again squashes the barcode.
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

- **SKUs come off the line before it joins the name.** Whatnot prints a
  listing's SKU in the Attributes column on the line after `Order N`. The
  parser used to append that line to the name and cut at `#N` — which works
  until a long name wraps and puts `#N` *after* the SKU: Oct 13 printed
  `JUMBO CRUNCHY STRAWBERRY DUCK SKU ZW-112B #1`, and the audit, parsing the
  same way, passed it. `audit_skus()` now reads SKUs from raw text with its own
  regexes and fails on any mismatch, any SKU on the wrong product, or any
  `SKU ` left in the output.
- **Branding off is byte-identical.** `slip_ps(..., brand=None)` must produce
  exactly the old header; `tests/test_slip_golden.py` pins it. The band keeps
  the words `Packing Slip` on every page because that is how `load()` finds
  slip pages.

- **The footer is stripped from the slip body before any fact check.** It is
  free text at the bottom of the page, so a footer saying `#1` or `$1.00`
  could pass a slip that lost those, or fail a good one. `split_footer()`
  removes it first and `audit_footer()` checks it on its own. It may reuse the
  renderer's wrap because it is cosmetic (same exception as the header
  message). The footer must stay the lowest text on the page.
- **Prices off is audited, not assumed.** With Show prices off, `verify()`
  fails any `$` amount left on a slip body after the expected product names
  are removed (a name like `$5 MYSTERY BOX` is part of the name, not a price).
- **Pick-list quantities come from the raw `Order` lines.** `audit_pick()`
  reads them with `RE_SRC_QTY` straight from the export, not from the parser
  or `group_items`, and matches them to rows read back from the PDF with the
  auditor's own regex. Each row must appear exactly once with its quantity.
- **Pages are P, S or B.** `page_kind()` classifies a page by its first line
  (pick list, slip, label). `Packing Slip` is defused to `Packing-Slip` on
  pick pages (`_defuse`) because `load()` finds slip pages by that phrase and
  would otherwise treat a pick page as a shipment.

- **TikTok: the lot comes from columns read two ways.** `parse_order()` uses
  the table header only to find where the name ends (pdftotext moves a column a
  few characters either way, line by line, so a lot read by header position
  landed in both SKU columns). The auditor's `raw_rows()` splits each row from
  the right instead (qty, price, Seller SKU, SKU). The two must agree on every
  lot, price and qty.
- **TikTok labels are cut out, not stretched.** The page is A6 (298×420 pt)
  and the label artwork inside it is 2:3. `tiktok.label_bitmap()` renders the
  page, as for Whatnot, then crops to the ink, pads to exactly 2:3 and scales
  evenly to 1200×1800. Stretching the whole page would squash the barcode by 6%.
- **TikTok output is slip, then label**, like Whatnot, although the export
  puts the label first. `verify()` pairs each run of slip pages with its
  source order by order ID, then compares the label after it pixel for pixel.

### Known limitations

- The parser cuts a product name at its first `#N`, so `CARD #25 HOLO #3`
  groups as `CARD` with number #25.

- Order IDs aren't printed — eleven 10-digit IDs don't fit a 4×6. They're
  preserved in the parsed data if you want them added.
- Emoji in product names are lost (see above).
- Check the dot leaders and barcodes survive on **your** printer before a full
  batch; 0.7 pt dots can drop out on some thermal heads.
