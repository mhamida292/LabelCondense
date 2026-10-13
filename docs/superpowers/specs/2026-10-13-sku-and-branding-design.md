# SKU on slips, and a branded header — design

Date: 2026-10-13
Status: approved, ready for implementation planning

## Purpose

Two additions to the rebuilt packing slip:

1. **SKU.** Show each product's SKU so it can be used for *picking* — read at a
   glance to find the item on the shelf.
2. **Branding.** A band at the top of every slip page carrying the shop's logo
   (or, until one exists, the shop name in bold) and a thank-you message, both
   editable from the GUI.

## Scope

**In:** SKU parsing, grouping, rendering and audit; a fix for SKU text leaking
into product names; a branded header band; a per-user settings store; a
Branding tab in the GUI; a `--no-brand` CLI flag.

**Out:** extra branding lines (social handle, URL), message-only-on-last-page,
colour or greyscale printing, logo design itself, any change to labels.

## Constraints

- The user cannot hand-correct a printed slip. Every outcome is print-as-is or
  DO NOT PRINT — never "fix by hand".
- What must be right: quantities, prices, `#N`, tracking numbers, labels — and
  now SKUs, because a wrong SKU sends the picker to the wrong bin. Branding is
  cosmetic and must never block a run.
- The output goes to a thermal printer: pure black dots, nothing else.
- The auditor must not share an extraction path with the renderer (README,
  "Design notes"; twice before a shared helper blinded the audit). New checks
  read the raw source text independently of `parse_shipment()`.
- `load()` and `verify()` identify slip pages by the text `Packing Slip`. That
  text must survive on every slip page in every mode.
- With branding off, output must be identical to today's (parity baseline).

## What the data looks like

Only one export so far carries SKUs: `~/Desktop/labels/precondense-oct13.pdf`
(67 shipments, 390 items, 194 with a SKU). Under `pdftotext -layout` the SKU
sits in the Attributes column on the line after the `Order` line:

```
1    CRUNCHY LOBSTER ■          Order 1437763335           $3.00
     #1                         SKU TB200-477
     BIDDING ON SINGLE ITEM
```

In that export every product name maps to exactly one SKU; items without a SKU
simply have no such line.

**Existing bug.** `parse_shipment()` appends continuation lines to the name,
SKU included, then cuts the name at its trailing `#N`. When the `#N` comes
after the SKU (a wrapped name), the SKU survives into the name: today's Oct 13
slips printed `JUMBO CRUNCHY STRAWBERRY DUCK SKU ZW-112B #1`. The audit passed
it because it parses the same way.

## Part 1 — SKU

### Parsing

`RE_SKU = re.compile(r'\s{2,}SKU (\S+)\s*$')`. While collecting an item's
continuation lines, a trailing `SKU <code>` match is recorded as
`item['sku']` and removed from the line *before* the remainder is appended to the name. A line that was
only the SKU contributes nothing to the name. An item without a match gets
`sku = None`.

### Grouping

`group_items()` keys on `(product.upper(), sku)`. Same name with different SKUs
→ separate lines; no SKU behaves exactly as today. Each grouped entry carries
`sku`.

### Rendering

The product row's first line reads `[SKU] PRODUCT NAME`, the bracketed SKU in
the same 8.5 pt Helvetica-Bold as the name. Implementation: the display string
`f"[{sku}] {product}"` is what `build_rows()` wraps, so wrap width, the inline
`#N` placement and continuation lines all keep working unchanged. Entries with
no SKU render exactly as today.

### Audit

Per shipment, reading raw text with regexes of its own rather than through
`parse_shipment()`:

1. **Parsed = source.** The multiset of codes matched by `\bSKU (\S+)\s*$`
   over the raw source slip lines must equal the multiset of parsed item
   `sku`s. A SKU the parser dropped or mangled fails.
2. **Output = source.** The set of codes matched by `\[([^\]\s]+)\]` in the
   output slip text must equal the set of distinct raw source codes. A SKU
   dropped from the slip, or one invented, fails.
3. **Pairing.** For each grouped entry with a SKU, the renderable text
   `[SKU] <first word of the product>` must appear in the output slip text.
   A SKU attached to the wrong product fails.
4. **No leak.** The output slip text contains no `SKU ` at all.

### Tests

- Parse fixtures lifted verbatim from Oct 13 text: the Lobster layout, the
  wrapped Strawberry Duck (regression for the leak), an item with no SKU.
- Grouping: same name + different SKUs → two entries; same name + same SKU → one.
- Mutation tests on a built Oct 13 output's text: swapping two SKUs fails
  check 3; deleting a SKU from the slip fails check 2; injecting `SKU X` into a
  name fails check 4.
- End-to-end: build + `verify --deep` of `precondense-oct13.pdf` with zero
  failures (skipped when the file is absent, like the existing sample fixture).
- Older exports (no SKUs) keep the existing parity baseline.

## Part 2 — Branded header band

### Layout (branding on)

The band replaces today's title row and is 16 pt taller; everything below it
(To/From, table header, `TOP_Y`) shifts down 16 pt. The footer is unchanged, so
the item area loses ~16 pt per page and some dense orders reach a second slip
page sooner — already supported.

- **Left:** logo box 108 × 36 pt (1.5" × 0.5"), top-aligned at the margin.
  The logo is scaled to fit preserving aspect, left-aligned. With no logo, the
  shop name in Helvetica-Bold, largest size ≤ 16 pt that fits 108 pt width.
  With neither, the box is empty and the message takes the full width.
- **Middle:** the message, 9 pt Helvetica, wrapped to at most 2 lines in the
  width between the box (+8 pt gap) and the corner text.
- **Top-right:** `Packing Slip 1/1` in 7 pt Helvetica — keeps slip detection
  and the page count.
- The rule under the band, then the rest of the page as today.

### Branding off

`build(..., brand=None)` produces exactly today's header. The parity baseline
is the proof.

### Logo pipeline

On *Choose…* in the GUI, `branding.import_logo(path)`:

1. opens the image with Pillow (PNG/JPG; anything Pillow reads),
2. flattens transparency onto white,
3. scales to fit 450 × 150 px (the box at 300 dpi), preserving aspect,
4. thresholds at 128 to mode `1` (same rule as labels),
5. writes it as `logo.png` in the settings folder and returns it for preview.

The original file is never read again. At build time the stored 1-bit image is
emitted once in the PostScript prolog as a procedure (`/Logo { ... } def`, data
held in a string) and invoked on every slip page.

### Failure handling (binary)

- Message longer than 2 lines at 9 pt in the available width: Save is refused
  with a message; nothing is truncated on paper.
- `logo.png` missing or unreadable at run time: fall back to the shop name and
  log one informational line. Never blocks the run.
- Invalid image chosen in the GUI: an error dialog; the previous logo stays.

### Audit additions

- Every output slip page contains `Packing Slip` (already implied by page
  grouping; made an explicit check).
- With branding on and a non-empty message, the message's renderable text
  appears on every output slip page.

## Part 3 — Settings, GUI, CLI

### Settings store

Same per-user folder as the logs (`logstore`'s base: `~/.local/share/label-condense/`
on Linux, `%LOCALAPPDATA%\label-condense\` on Windows):

- `settings.json` — `{"brand_enabled": bool, "shop_name": str, "message": str}`
- `logo.png` — the converted 1-bit logo

Defaults when the file is missing or unparseable: branding off, empty shop
name, message `Thank you for shopping with us!`. Writes go to a temp file and
are renamed into place.

### `src/branding.py` (new, no tkinter)

- `load() -> Brand` / `save(Brand)` — with validation (message fits 2 lines).
- `import_logo(path) -> Image` / `remove_logo()`.
- `message_fits(text) -> bool`.
- `header_ps(brand, page_no, page_count) -> list[str]` and `prolog_ps(brand)`.

`Brand` is a small dataclass: `enabled, shop_name, message, logo (Image|None)`.
`whatnot_slips.build()` and `slip_ps()` take `brand=None`; the renderer never
reads settings files.

### Who passes the brand

- **GUI:** `branding.load()` once at run start, passed through `Job` to
  `build()`; edits mid-run don't affect that run.
- **CLI:** `whatnot_slips.py build` loads settings by default; `--no-brand`
  disables. `./run.sh` gains nothing — it calls `build`, so it inherits.
- **verify:** receives the same brand so it knows which message to check;
  `verify` subcommand gets `--no-brand` too.

### Branding tab

Third tab beside Run and Logs:

```
[x] Show branding on slips
Shop name: [______________]
Logo:      [ 1-bit preview ]  [Choose…] [Remove]
Message:   [ 2-line text box ]
[Preview slip]                      [Save]
```

- *Preview slip* renders a sample slip header through the real renderer
  (Ghostscript → PNG) so the preview is what prints.
- *Save* validates; on failure shows why and keeps the form as-is.
- The tab is disabled while a run is in progress.

### Tests

- `branding`: settings round trip; defaults on missing/corrupt JSON; atomic
  write; `import_logo` turns a colour+alpha PNG into a mode-`1` image within
  450 × 150; `message_fits` boundaries.
- Renderer: branding off → header PS identical to today; branded build of the
  sample and Oct 13 exports passes the audit; logo data appears once in the PS.
- GUI: Branding tab exists, disables during a run, Save refuses an overlong
  message — following `tests/test_gui.py` patterns.

## Build order

SKU first (it fixes a live bug and is correctness-critical), then branding.
