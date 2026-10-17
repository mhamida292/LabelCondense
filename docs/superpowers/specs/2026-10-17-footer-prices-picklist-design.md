# Footer message, a price toggle, and a pick list — design

Date: 2026-10-17
Status: approved, ready for implementation planning

The footer's own on/off switch is the user's decision; the rest of
"Calls made without the user" below are mine.

## Purpose

Three additions to the print-ready PDF, all switched from the GUI:

1. **Footer message.** A line or two of the user's own text at the very bottom
   of every slip page — whatever they want buyers to read last (next show,
   a handle, a returns note). Set and changed freely, like the header message.
2. **Price toggle.** Not every run should show what the buyer paid. One switch
   hides every dollar amount on the slips.
3. **Pick list.** For pulling a whole batch off the shelves at once: one or
   more pages at the very front of the PDF listing every product across every
   shipment in the export, with the total quantity to pull. Optional per run.

The user sells to around 150 buyers per export, which is why the pick list is
totals-only (see "Pick list" below).

## Scope

**In:** the footer text (setting, rendering, audit, GUI box with a character
limit); a show/hide-prices switch (GUI, CLI, renderer, audit); a pick-list
section at the front of the output (GUI, CLI, renderer, audit); README design
notes and a CHANGELOG entry.

**Out:** templated or personalised footer text (no `{buyer}` placeholders —
the user wants plain free text); a per-buyer breakdown on the pick list;
branding or the footer on pick-list pages; any change to the shipping labels.

**Anti-goals** — failures even if the feature "works":

- A pick list with a wrong quantity. The picker will trust it and short a box.
- A price leaking onto a slip when prices are off.
- Free text (footer) able to fake or break an audit check.
- Any change to today's output when all three are off / empty.

## Constraints (inherited — see README "Design notes")

- Every outcome is print-as-is or DO NOT PRINT. Nothing is fixed by hand.
- The auditor must not share an extraction or parsing path with the renderer
  for anything that must be right. Quantities on the pick list must be right.
  The footer, like the header message, is cosmetic; `audit_brand()` already
  documents the one sanctioned exception (reusing the renderer's wrap for
  cosmetic text) and the footer may use the same exception.
- `load()` and `verify()` find slip pages by the text `Packing Slip`, and the
  To:/From: line anchors `slip_body()`. Neither pick-list pages nor the
  footer may break that.
- Output goes to a thermal printer: pure black, nothing grey that matters.
- **Byte-identical default.** Footer empty, prices shown, pick list off must
  produce exactly today's PDF. `tests/test_slip_golden.py` and the parity
  baseline must pass unchanged.

## 1. Footer message

### What the user sees

- A **Show footer on slips** checkbox on the Branding tab, separate from
  **Show branding on slips** (the user asked for its own switch, so a footer
  can print without the header band and vice versa). Off by default.
- A **Footer message** text box under it, below the existing Message box, with a live counter beneath it (`72 / 120`). The box will not
  accept more than **120 characters** (typing or pasting past it is cut at
  120). It is saved with the rest of the branding by the same Save button
  and marks the tab "Not saved yet" when edited.
- Width, not just count, decides fit: a message of wide capitals can wrap to a
  third line under 120 characters. The existing pattern applies —
  `branding.problems()` refuses it on Save with a plain sentence ("The footer
  is too long: it must fit on 2 lines"), and `load()` drops an unfit stored
  value with a note rather than printing it cut off.
- Refused words, for the same reason as the header message: `To:`, `From:`.
  Also refused: `Packing Slip` and `Pick List`, since those words identify
  page kinds.
- **Preview slip** shows the footer exactly as it prints.

### Where it prints

Layout **B** (chosen by the user from mockups): at the very bottom of the
slip, *under* the tracking/weight line, centred, at most two lines. When a
footer is present the whole bottom block (totals rule, item count/total,
service/dims, tracking/weight) moves up by the footer's height and the item
area's floor (`BOT_Y`) rises by the same amount, so dense slips spill to a
second page slightly sooner. A thin rule separates the footer from the
tracking line.

- On **every** slip page of a multi-page slip, like the shipping facts.
  *(Builder's-call default — the user did not object.)*
- **Empty footer → no space taken**, slip identical to today.
- Has **its own switch**, independent of Show branding on slips. Footer off
  (or empty) → no footer and today's slip; this is what keeps the default
  byte-identical. Header branding on/off does not affect it.
- Suggested size: 8 pt Helvetica (the header message is 9 pt). The bottom
  16 pt margin stays clear; nothing may print below it.

### Audit

- Like `audit_brand()`: every slip page carries the footer's lines.
- The footer is free text at the bottom of the slip body, so it sits inside
  the region `slip_body()` hands to every fact check. A footer saying
  `#1`, `$5.00`, `3 Items $9.00` or `SKU X` must not be able to satisfy or
  fail any item, price, total or SKU check. The fact checks must read the
  slip with the footer excluded — the builder picks the anchor (for example,
  cutting the body at the last fixed slip line, the tracking/weight line,
  the way `slip_body()` cuts at the last To:/From: line). A test must prove a
  hostile footer (`#1 $1.00 1 Item $1.00 SKU A`) neither passes a broken
  slip nor fails a good one.

### Storage

`settings.json` gains `footer_enabled` (bool, default false) and `footer`
(string, default empty), read by `branding.load()` with the same
type-checking and fallback rules as `brand_enabled` and `message`. The
renderer and `verify()` take the footer as its own input alongside `brand`,
since either can be on without the other; `--no-brand` on the CLI skips
both (builder may add a separate `--no-footer`).

## 2. Price toggle

### What the user sees

- A **Show prices** checkbox on the Run tab, near Choose file…. On by
  default. It remembers the last choice across launches (store it with the
  other prefs; `recent.py` already keeps `prefs.json`).
- CLI: `whatnot_slips.py build … --no-prices` (and the same on `verify`).
  `run.sh` passes `--no-prices` through.

### What changes on the slip when prices are off

**Every dollar amount goes**: each `#N`'s price on grouped sub-rows, each
product row's subtotal, the `Subtotal` column heading, and the order total.
The item count stays (`3 Items`). Layout otherwise unchanged — the space
simply stays blank (builder may let names use it, but must keep the
byte-identical default when prices are on).

### Audit when prices are off

- Assert **no `$` amount appears anywhere** on any slip body (this is the
  anti-goal check), and no `Subtotal` heading.
- Item counts per shipment are still checked against the source; the source
  footer's stated count still is too.
- Price, subtotal, total and grand-total checks are replaced by the no-price
  assertion, not silently skipped — the report's check count should show it.
- `verify` must be told the mode (like `brand` is today); the GUI's job runner
  passes it through.

## 3. Pick list

### What the user sees

- An **Add pick list** checkbox on the Run tab beside Show prices. **Off by
  default** (keeps the default output identical). Remembered like Show
  prices. CLI: `--pick-list` on build/verify; `run.sh` passes it through.
- The output PDF then starts with one or more 4×6 **Pick List** pages,
  followed by the slips and labels exactly as today.

### Layout (style A, chosen by the user)

Per page: a header `Pick List` with `n/m` page numbers in the corner, a
rule, then a sub-header on page 1 with the export's file name, shipment count
and total item count. Then one row per product:

```
☐  12   [TB200-477] CRUNCHY LOBSTER
☐   7   [TB200-480] SQUISHY CRAB
☐   1   GIVEAWAY STICKER PACK        ← GIVEAWAY white-on-black, as on slips
```

- A tick box, the total quantity in bold, then the product as the slip shows
  it (`display_name()` form: `[SKU] NAME`), wrapping onto further lines if
  long. **No `#N` numbers and no prices** — ever, regardless of the price
  toggle.
- One row per (product name, SKU), summed across every shipment: the same key
  `group_items()` uses (name case-insensitive, SKU part of the key), so two
  listings with the same name but different SKUs are separate rows.
- **Sorted by SKU** (so the list follows the shelves), then items without a
  SKU after, by name. Builder chooses plain vs natural sort for SKUs.
- Last page ends with a rule and `N products · M items`.
- No branding band and no footer message on pick-list pages.

### Audit

The quantities must be right, so the check is independent of the renderer's
grouping:

- The output starts with a run of pick-list pages and then the existing
  `(S+B)+` pattern; nothing else. Page classification must not be fooled by a
  product name that happens to contain `Packing Slip` or `Pick List`
  (classify by position and page header, not a bare substring).
- Every product the source contains appears once, with a quantity equal to
  the sum of that product's units across all source shipments, computed from
  the source by the auditor's own route (not `group_items()` over
  `parse_shipment()` output) — the builder picks how, in the spirit of
  `audit_skus()` reading raw text with its own regexes.
- No product on the pick list that isn't in the source; product count and
  total item count lines match.
- No `$` amount and no `#N` on pick-list pages.
- With the pick list off, assert there are no pick-list pages.

## Combined behaviour

| Footer | Prices | Pick list | Output |
|---|---|---|---|
| off or empty | on | off | identical to today |
| set, footer switch on | any | any | footer on every slip page |
| any | off | any | no `$` on any page |
| any | any | on | pick list first, then slips + labels |

The success screen's stats line ("N pages, N checks passed") counts pick-list
pages in the total.

## Left to the builder

- Exact point sizes, spacing, rule weights, and how many rows fit per pick
  page (thermal legibility first; 8.5 pt bold names like the slips).
- The footer-exclusion anchor for the audit, and the independent route for
  pick-list quantities, within the constraints above.
- Whether to let product names use the freed subtotal column when prices are
  off (default: don't).
- Where in `prefs.json` / settings the two Run-tab switches live, and widget
  placement on the Run card.
- Test structure; at minimum: golden byte-identical default, hostile footer,
  prices-off leak check (mutation: inject one price → must fail), pick-list
  quantity mutation (alter one qty → must fail), pick-list classification.

## Calls made without the user (check these)

- Footer prints on every slip page, not just the last.
- Footer may not contain `Packing Slip` or `Pick List` (in addition to
  `To:`/`From:`).
- Show prices and Add pick list live on the Run tab, are remembered, and have
  CLI flags; pick list defaults off, prices default on.
- Pick list carries no prices or `#N` even with prices on, and no branding or
  footer.
- Pick list sorts by SKU, then unSKU'd items by name.
