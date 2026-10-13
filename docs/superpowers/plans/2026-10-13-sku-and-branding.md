# SKU on Slips and Branded Header Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Print each product's SKU as `[SKU] NAME` (audited independently of the parser), and add an optional branded header band — logo or shop name plus a thank-you message — editable from a new Branding tab in the GUI.

**Architecture:** `src/whatnot_slips.py` stays the single renderer + auditor: it gains SKU parsing/grouping/rendering, a standalone `audit_skus()`, and the band drawing (`brand_ops`, `logo_prolog`, `preview_png`) driven by an optional `brand` argument whose `None` value reproduces today's output byte-for-byte. A new `src/branding.py` (no tkinter) owns the per-user settings (`settings.json` + `logo.png`), validation, and logo conversion. `job.py`, the CLI and the GUI each pass a loaded `Brand` (or `None`) into `build()`/`verify()`.

**Tech Stack:** Python 3 (venv at `.venv/`, Python 3.14), Pillow 12, tkinter/ttk, Ghostscript (`gs`) emitting PDF from hand-written PostScript, Poppler (`pdftotext`, `pdftoppm`, `pdfimages`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-sku-and-branding-design.md` — read it, including the final "Refinements made while planning" section, which wins where it differs.

## Global Constraints

- Every outcome is print-as-is or DO NOT PRINT. Never design anything that requires the user to correct a slip by hand.
- Must be right: quantities, prices, `#N`, tracking, labels, **SKUs**. Branding is cosmetic and must never fail a run.
- The auditor must not reuse the renderer's extraction path; new SKU checks read raw text with their own regexes.
- `load()`/`verify()` find slip pages by the text `Packing Slip`; it must appear on every slip page in every mode.
- `brand=None` must produce exactly today's PostScript (golden hash `0f1e431b1eed5be620b7480cf54d0c6cdfa3ec200d5ff9f58ac499a558e2d782`, Task 1) and the existing parity baseline.
- Thermal printer: pure black/white only. Logo box 108 × 36 pt; logo stored ≤ 450 × 150 px, mode `1`.
- Band geometry: `BAND = 19`; logo top `H - 12`; corner text 7 pt at `H - 20`; message 9 pt at `H - 33` / `H - 44`, width 140 pt; rule `H - 52`.
- Default message: `Thank you for shopping with us!`. Message ≤ 2 lines; shop name fits 108 pt at ≥ 8 pt bold.
- Settings live in `logstore.data_dir()` (`~/.local/share/label-condense/`, `%LOCALAPPDATA%\LabelCondense\`); tests override with env `LABEL_CONDENSE_SETTINGS_DIR`.
- Match the surrounding style: terse, comment only what's non-obvious and say *why*, regexes as module constants `RE_*`.
- Run tests with `.venv/bin/python -m pytest` (system python has no pytest). `pytest.ini` already puts `src/` on the path.
- Real exports for gated tests: `PACKING_TEST_PDF` (existing, any Sept export, e.g. `.packing/archive/2026-09-11-Whatnot-Combined-Labels-Packing-Slips-c4c74f99-1.pdf`) and new `PACKING_SKU_PDF=~/Desktop/labels/precondense-oct13.pdf`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **An item description line that itself ends in `SKU <word>`** (seller text) — expected: audit fails safe (count mismatch → DO NOT PRINT) rather than printing a wrong SKU. Pinned in Task 2 (`test_description_ending_in_sku_text_fails_safe`).
2. **Same product name, two different SKUs in one shipment** — expected: two separate lines, each with its own SKU, totals unchanged. Pinned in Task 1 (`test_same_name_different_sku_stays_apart`) and Task 2 (pairing).
3. **A chosen logo that is transparent, coloured, huge, tiny, or entirely white** — expected: transparent/colour/huge/tiny are fitted into 450×150 1-bit; all-white is refused with "The image is blank." Pinned in Task 3.
4. **Settings file corrupt or hand-edited with an overlong message** — expected: run proceeds with defaults / message omitted, and the run log says why; never crashes, never truncates. Pinned in Task 3 and Task 5.
5. **Logo drawn on page 2+ of a 300-page job** — expected: every slip page shows the logo (string DataSource re-read per use). Pinned in Task 4 (`test_logo_prints_on_every_page`).

---

### Task 0: Commit the pending blank-label and tracking fixes (prerequisite)

The working tree on `main` holds finished, tested fixes (`src/whatnot_slips.py`, `README.md`, both packaging scripts, `tests/test_labels.py`, `tests/test_tracking.py`). This plan edits the same file, so they must be committed first. **Ask the user before committing.**

- [ ] **Step 1: Confirm tests pass**

Run: `.venv/bin/python -m pytest -q`
Expected: `86 passed, 4 skipped`

- [ ] **Step 2: Commit (after user OK)**

```bash
git add README.md packaging/collect_binaries.py packaging/fetch_windows_binaries.ps1 src/whatnot_slips.py tests/test_labels.py tests/test_tracking.py
git commit -m "fix: render labels instead of extracting them; accept international tracking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Parse and group SKUs; stop SKU text leaking into names

**Files:**
- Modify: `src/whatnot_slips.py` (parsing section: `RE_*` constants ~line 94, `parse_shipment` ~line 123, `group_items` ~line 187)
- Create: `tests/test_sku.py`, `tests/test_slip_golden.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces: each parsed item dict gains `sku: str | None`. Each `group_items()` entry gains `sku: str | None`; grouping key is `(product.upper(), sku)`. `RE_SKU` constant. Test helper `golden_slip_ps()` in `tests/test_slip_golden.py`. Fixture `sku_pdf` and autouse fixture isolating settings in `tests/conftest.py`.

- [ ] **Step 1: Add fixtures to `tests/conftest.py`**

Append:

```python
@pytest.fixture(scope="session")
def sku_pdf():
    p = os.environ.get("PACKING_SKU_PDF")
    if not p:
        pytest.skip("set PACKING_SKU_PDF to a Whatnot export that carries SKUs")
    path = pathlib.Path(p).expanduser()
    if not path.is_file():
        pytest.skip(f"PACKING_SKU_PDF does not exist: {path}")
    return path

@pytest.fixture(autouse=True)
def settings_in_tmp(tmp_path, monkeypatch):
    """No test may read or write the real user's branding settings."""
    monkeypatch.setenv("LABEL_CONDENSE_SETTINGS_DIR", str(tmp_path / "settings"))
```

- [ ] **Step 2: Write the golden test (passes now; guards "branding off is unchanged" for the whole plan)**

Create `tests/test_slip_golden.py`:

```python
import hashlib
import whatnot_slips as ws

# A fixed slip, hashed before any of the SKU/branding work. With no SKUs and
# no brand, the renderer must keep producing exactly these bytes.
GOLDEN = "0f1e431b1eed5be620b7480cf54d0c6cdfa3ec200d5ff9f58ac499a558e2d782"

SHIP = dict(svc="USPS Ground Advantage", dims="12 x 12 x 12 in",
            track="9300120762602517212464", weight="7.0 oz")
ITEMS = [dict(qty=1, name="ROSEY BALL #2", order="1", price=2.0),
         dict(qty=1, name="ROSEY BALL #3", order="2", price=3.0),
         dict(qty=1, name="CRUNCHY LOBSTER #1", order="3", price=3.0)]
TO = ["To: buyer123", "Jane Buyer", "1 Main St", "Springfield, IL 62701"]
FRM = ["From: myshop", "2 Shop Rd", "Townsville, CA 90001"]

def golden_slip_ps(**kw):
    return "".join(ws.slip_ps(SHIP, ws.group_items(ITEMS), TO, FRM, **kw))

def test_unbranded_slip_without_skus_is_unchanged():
    assert hashlib.sha256(golden_slip_ps().encode()).hexdigest() == GOLDEN
```

Run: `.venv/bin/python -m pytest tests/test_slip_golden.py -v`
Expected: PASS (if it fails, stop — the baseline was taken from the Task 0 tree).

- [ ] **Step 3: Write the failing SKU parsing/grouping tests**

Create `tests/test_sku.py`:

```python
import whatnot_slips as ws

# Item blocks as pdftotext -layout prints them, lifted from the Oct 13 export
# (the first one to carry SKUs). The SKU sits in the Attributes column on the
# line after "Order N".
HEAD = "QTY Name & Description          Attributes                 Subtotal\n"

LOBSTER = HEAD + """1    CRUNCHY LOBSTER ■          Order 1437763335           $3.00
     #1                         SKU TB200-477
     BIDDING ON SINGLE ITEM
     , RANDOM COLOR. PLEA...

"""

# A wrapped name: the SKU shares a line with the name's second half and the
# #N comes after it, so cutting the name at #N used to keep the SKU text.
# Oct 13 printed "JUMBO CRUNCHY STRAWBERRY DUCK SKU ZW-112B #1".
DUCK = HEAD + """1    JUMBO CRUNCHY              Order 1438062700             $8.00
     STRAWBERRY DUCK            SKU ZW-112B
     ■■ #1
     BIDDING ON SINGLE ITEM

"""

# The SKU shares its line with seller boilerplate, which ends the item block.
ROSEY = HEAD + """1    ROSEY BALL \u25a0 #2            Order 1437826675           $2.00
     \u25a0\u25a0 Follow \u2022 \u25a0 Bookmark     SKU A-T-63
     \u2022 \u25a0 Save Big \u2022 \u25a0 Have...

"""

SKULL = HEAD + """1    CRUNCHY SKULL ■ #3         Order 1437266389           $3.00
     ASSORTED COLORS - PER
     ITEM - NO CANCELLATI...

"""

def only_item(text):
    _, items = ws.parse_shipment([text])
    assert len(items) == 1
    return items[0]

def test_sku_is_parsed_from_the_attributes_column():
    it = only_item(LOBSTER)
    assert it["sku"] == "TB200-477"
    assert ws.split_variant(it["name"]) == ("CRUNCHY LOBSTER", "#1")

def test_sku_does_not_leak_into_a_wrapped_name():
    it = only_item(DUCK)
    assert it["sku"] == "ZW-112B"
    assert "SKU" not in it["name"]
    assert ws.split_variant(it["name"]) == ("JUMBO CRUNCHY STRAWBERRY DUCK", "#1")

def test_sku_on_a_boilerplate_line_is_still_parsed():
    it = only_item(ROSEY)
    assert it["sku"] == "A-T-63"
    assert ws.split_variant(it["name"]) == ("ROSEY BALL", "#2")

def test_an_item_without_a_sku_has_none():
    it = only_item(SKULL)            # "SKULL" must not read as "SKU"
    assert it["sku"] is None
    assert ws.split_variant(it["name"]) == ("CRUNCHY SKULL", "#3")

def _item(name, sku, order, price=2.0):
    return dict(qty=1, name=name, order=order, price=price, sku=sku)

def test_same_name_same_sku_groups_together():
    g = ws.group_items([_item("ROSEY BALL #2", "A-T-63", "1"),
                        _item("ROSEY BALL #3", "A-T-63", "2")])
    assert len(g) == 1
    assert g[0]["sku"] == "A-T-63" and g[0]["qty"] == 2

def test_same_name_different_sku_stays_apart():
    g = ws.group_items([_item("ROSEY BALL #2", "A-T-63", "1"),
                        _item("ROSEY BALL #3", "A-T-64", "2", 3.0)])
    assert [(e["sku"], e["qty"], e["subtotal"]) for e in g] == \
           [("A-T-63", 1, 2.0), ("A-T-64", 1, 3.0)]

def test_items_without_a_sku_key_still_group():
    g = ws.group_items([dict(qty=1, name="ROSEY BALL #2", order="1", price=2.0)])
    assert g[0]["sku"] is None
```

- [ ] **Step 4: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sku.py -v`
Expected: FAIL — `KeyError: 'sku'` on the parse tests and grouping tests.

- [ ] **Step 5: Implement**

In `src/whatnot_slips.py`, after `RE_TRACK`:

```python
# Whatnot prints a listing's SKU in the Attributes column, on the line after
# "Order N". It has to come off the line before the rest joins the name: a
# wrapped name puts its #N after the SKU, so cutting at #N kept the SKU text.
RE_SKU   = re.compile(r'(?:^|\s{2,})SKU (\S+)\s*$')
```

In `parse_shipment`, replace the item loop body:

```python
    items, cur = [], None
    for ln in lines:
        if (m := RE_ITEM.match(ln)):
            cur = dict(qty=int(m.group(1)), name=m.group(2), order=m.group(3),
                       price=float(m.group(4).replace(',', '')), sku=None)
            items.append(cur)
        elif cur is not None:
            # the SKU first: it can share a line with the seller boilerplate
            # ("Follow • Bookmark     SKU A-T-63"), which ends the block
            if cur['sku'] is None and (s := RE_SKU.search(ln)):
                cur['sku'], ln = s.group(1), ln[:s.start()]
                if not ln.strip():
                    continue
            # an item block ends at a blank line, the boilerplate, or the footer
            if (not ln.strip() or RE_BOIL.search(ln) or RE_TOTAL.match(ln)
                    or ln.startswith('QTY') or 'Packing Slip' in ln or 'USPS' in ln):
                cur = None
            else:
                cur['name'] += ' ' + ln.strip()
```

Replace `group_items`:

```python
def group_items(items):
    # SKU is part of the key: two listings sharing a name but not a SKU sit in
    # different bins, so they must not share a line
    g = OrderedDict()
    for it in items:
        product, variant = split_variant(it['name'])
        sku = it.get('sku')
        e = g.setdefault((product.upper(), sku),
                         dict(product=product, sku=sku, qty=0, subtotal=0.0, variants=[]))
        e['qty'] += it['qty']; e['subtotal'] += it['price']
        e['variants'].append(dict(variant=variant, price=it['price'], order=it['order']))
    return list(g.values())
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass, including `test_sku.py` and the golden test.

- [ ] **Step 7: Commit**

```bash
git add src/whatnot_slips.py tests/test_sku.py tests/test_slip_golden.py tests/conftest.py
git commit -m "feat: parse each item's SKU and group by name and SKU

The SKU used to be glued onto the product name and then cut off at #N,
except when a wrapped name put #N after it: Oct 13 printed
'JUMBO CRUNCHY STRAWBERRY DUCK SKU ZW-112B #1'.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Print `[SKU] NAME` and audit SKUs independently

**Files:**
- Modify: `src/whatnot_slips.py` (`build_rows` ~line 201, `verify` product loop ~line 512, new `audit_skus` next to `Audit`)
- Modify: `tests/test_sku.py`
- Create: `tests/test_sku_e2e.py`

**Interfaces:**
- Consumes: `item['sku']`, entry `['sku']` from Task 1.
- Produces: `display_name(entry) -> str`; `audit_skus(a: Audit, tag: str, src_text: str, sitems: list, grouped: list, out_text: str) -> None`; constants `RE_SRC_SKU`, `RE_OUT_SKU`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_sku.py`:

```python
# --- rendering -------------------------------------------------------------

def test_display_name_leads_with_the_sku():
    e = ws.group_items([_item("ROSEY BALL #2", "A-T-63", "1")])[0]
    assert ws.display_name(e) == "[A-T-63] ROSEY BALL"

def test_display_name_without_a_sku_is_just_the_product():
    e = ws.group_items([_item("ROSEY BALL #2", None, "1")])[0]
    assert ws.display_name(e) == "ROSEY BALL"

def test_the_slip_carries_the_sku_before_the_name():
    g = ws.group_items([_item("ROSEY BALL #2", "A-T-63", "1")])
    ps = "".join(ws.slip_ps({}, g, ["To: x"], ["From: y"]))
    assert "([A-T-63] ROSEY BALL)" in ps

# --- audit: read raw text with regexes of its own ---------------------------
# Source and output text shaped like pdftotext -layout. The source block is the
# real Oct 13 layout; the output lines are what build_rows() prints.

SRC = HEAD + """1    ROSEY BALL ■ #2              Order 1437826675           $2.00
     ■■ Follow • ■ Bookmark       SKU A-T-63

1    CRUNCHY LOBSTER ■          Order 1437763335           $3.00
     #1                         SKU TB200-477

"""

GOOD_OUT = """QTY  Name & Description                     Subtotal
1    [A-T-63] ROSEY BALL #2                      $2.00
1    [TB200-477] CRUNCHY LOBSTER #1              $3.00
"""

def run_audit(src=SRC, out=GOOD_OUT, items=None):
    _, parsed = ws.parse_shipment([src])
    items = parsed if items is None else items
    a = ws.Audit()
    ws.audit_skus(a, "s0", src, items, ws.group_items(items), out)
    return a

def labels(a):
    return [l for l, _ in a.fail]

def test_a_correct_slip_passes_every_sku_check():
    a = run_audit()
    assert a.fail == [] and a.checks >= 4

def test_a_sku_the_parser_dropped_fails():
    _, items = ws.parse_shipment([SRC])
    items[0]["sku"] = None
    assert "s0 SKUs parsed" in labels(run_audit(items=items))

def test_a_sku_missing_from_the_slip_fails():
    out = GOOD_OUT.replace("[A-T-63] ", "")
    assert "s0 SKUs on slip" in labels(run_audit(out=out))

def test_an_invented_sku_fails():
    out = GOOD_OUT.replace("[A-T-63]", "[A-T-99]")
    assert "s0 SKUs on slip" in labels(run_audit(out=out))

def test_swapped_skus_fail_the_pairing():
    out = (GOOD_OUT.replace("[A-T-63]", "[X]").replace("[TB200-477]", "[A-T-63]")
                   .replace("[X]", "[TB200-477]"))
    assert "s0 SKU pairing" in labels(run_audit(out=out))

def test_sku_text_left_in_a_name_fails():
    out = GOOD_OUT.replace("ROSEY BALL #2", "ROSEY BALL SKU A-T-63 #2")
    assert "s0 no SKU text on slip" in labels(run_audit(out=out))

def test_description_ending_in_sku_text_fails_safe():
    """Seller text that happens to end 'SKU <word>' on a description line is
    indistinguishable from a real SKU line; the parser takes only the first per
    item, the raw count sees both, and the run stops rather than guess."""
    src = SRC.replace("     #1                         SKU TB200-477\n",
                      "     #1                         SKU TB200-477\n"
                      "     ASK ABOUT                  SKU LOOKUP\n")
    assert "s0 SKUs parsed" in labels(run_audit(src=src))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sku.py -v`
Expected: FAIL — `AttributeError: module 'whatnot_slips' has no attribute 'display_name'` / `'audit_skus'`.

- [ ] **Step 3: Implement rendering**

In `src/whatnot_slips.py`, above `build_rows`:

```python
def display_name(e):
    """What the product row prints. The SKU leads because it is what the
    picker reads to find the bin."""
    return f"[{e['sku']}] {e['product']}" if e.get('sku') else e['product']
```

In `build_rows`, change the wrap line:

```python
        b, ls = [], wrap(display_name(e), NAME_W, 8.5, True)
```

- [ ] **Step 4: Implement the audit**

Below `class Audit` (before `kinds_detail`):

```python
# The auditor's own view of SKUs. Not RE_SKU: the parser once glued SKU text
# onto names and an audit that parsed the same way passed it.
RE_SRC_SKU = re.compile(r'(?:^|\s{2})SKU (\S+)\s*$')
RE_OUT_SKU = re.compile(r'^\s*\d+\s+\[([^\]\s]+)\]', re.M)

def audit_skus(a, tag, src_text, sitems, grouped, out_text):
    """A wrong SKU sends the picker to the wrong bin, so it is held to the same
    standard as a wrong #N."""
    raw = sorted(m.group(1) for ln in src_text.split('\n')
                 if (m := RE_SRC_SKU.search(ln)))
    parsed = sorted(it['sku'] for it in sitems if it.get('sku'))
    a.ok(raw == parsed, f'{tag} SKUs parsed', f'{parsed} vs source {raw}')
    shown = set(RE_OUT_SKU.findall(out_text))
    a.ok(shown == set(raw), f'{tag} SKUs on slip',
         f'{sorted(shown)} vs source {sorted(set(raw))}')
    flat = renderable(out_text)
    for e in grouped:
        if e.get('sku'):
            first = renderable(e['product']).split(' ')[0]
            a.ok(f"[{e['sku']}] {first}" in flat, f'{tag} SKU pairing',
                 f"{e['sku']} {e['product'][:30]!r}")
    a.ok('SKU ' not in out_text, f'{tag} no SKU text on slip')
```

In `verify`, in the per-shipment loop, the product check must wrap what was printed. Change:

```python
            for seg in wrap(e['product'], NAME_W, 8.5, True):
```
to:
```python
            for seg in wrap(display_name(e), NAME_W, 8.5, True):
```

and right after the `# every unit: ...` loop (still inside the per-shipment loop) add:

```python
        stext = '\n'.join(raw_s[n - 1] for n in spages)
        audit_skus(a, tag, stext, sitems, gr, opage)
```

- [ ] **Step 5: Run unit tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (golden test still passes — no SKUs there).

- [ ] **Step 6: Write the end-to-end test**

Create `tests/test_sku_e2e.py`:

```python
import tempfile, pathlib
import whatnot_slips as ws

def test_oct13_export_builds_with_skus_and_passes_the_audit(sku_pdf):
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out.pdf"
        ws.build(str(sku_pdf), str(out), quiet=True)
        audit = ws.verify(str(sku_pdf), str(out), deep=False)
        text = "\f".join(ws.pdf_pages(str(out)))
    assert audit.fail == []
    assert "[TB200-477] CRUNCHY LOBSTER" in ws.renderable(text)
    assert "SKU ZW-112B" not in text           # the old leak
    assert "[ZW-112B] JUMBO CRUNCHY" in ws.renderable(text)
```

Run: `PACKING_SKU_PDF=~/Desktop/labels/precondense-oct13.pdf .venv/bin/python -m pytest tests/test_sku_e2e.py -v`
Expected: PASS (takes ~30 s).

Also run the parity tests on a Sept export to prove SKU-less output is unchanged:
Run: `PACKING_TEST_PDF=".packing/archive/2026-09-11-Whatnot-Combined-Labels-Packing-Slips-c4c74f99-1.pdf" .venv/bin/python -m pytest tests/test_parity.py -v`
Expected: `test_audit_passes_clean` PASS. `test_build_matches_baseline` will FAIL only on `checks` (the SKU audit adds checks per shipment): confirm `text_sha`, `pages`, `slip_pages`, `labels`, `failures` are unchanged, then re-record with `.venv/bin/python tests/record_baseline.py` (read it first for its arguments) and say so in the commit message.

- [ ] **Step 7: Commit**

```bash
git add src/whatnot_slips.py tests/test_sku.py tests/test_sku_e2e.py tests/baseline.json
git commit -m "feat: print [SKU] before the product name and audit it independently

Baseline re-recorded: only the assertion count changed (new SKU checks).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Settings store and logo conversion (`branding.py`)

**Files:**
- Modify: `src/logstore.py` (split `data_dir()` out of `log_dir()`)
- Modify: `src/whatnot_slips.py` (band geometry constants + `shop_name_size`, new section before `# ------ labels`)
- Create: `src/branding.py`
- Create: `tests/test_branding.py`

**Interfaces:**
- Consumes: `ws.wrap`, `ws.sw`, `ws.renderable`.
- Produces:
  - `logstore.data_dir() -> pathlib.Path`
  - `ws.BAND = 19.0`, `ws.LOGO_W = 108.0`, `ws.LOGO_H = 36.0`, `ws.LOGO_TOP = H - 12`, `ws.MSG_SIZE = 9`, `ws.MSG_W = 140.0`, `ws.shop_name_size(name) -> int | None`
  - `branding.Brand` dataclass: `enabled: bool, shop_name: str, message: str, logo: PIL.Image.Image | None, notes: list[str]`
  - `branding.DEFAULT_MESSAGE`, `branding.LOGO_PX = (450, 150)`
  - `branding.settings_dir()`, `load() -> Brand`, `active() -> Brand | None`, `save(Brand) -> None` (raises `ValueError` with human text on invalid, `OSError` on disk), `problems(Brand) -> list[str]`, `message_fits(str) -> bool`, `name_fits(str) -> bool`, `import_logo(path) -> Image` (mode `1`; raises `OSError`/`ValueError`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_branding.py`:

```python
import json, os
import pytest
from PIL import Image

import branding
import logstore
import whatnot_slips as ws

def sdir():
    return branding.settings_dir()

# --- where things live -----------------------------------------------------

def test_settings_dir_honours_the_test_override(tmp_path):
    assert sdir() == tmp_path / "settings" and sdir().is_dir()

def test_log_dir_still_sits_under_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("PACKING_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "xdg"))
    assert logstore.log_dir() == logstore.data_dir() / "logs"

# --- load / save -----------------------------------------------------------

def test_defaults_when_nothing_is_saved():
    b = branding.load()
    assert (b.enabled, b.shop_name, b.message, b.logo, b.notes) == \
           (False, "", "Thank you for shopping with us!", None, [])
    assert branding.active() is None

def test_round_trip():
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co",
                                 message="Thanks!"))
    b = branding.load()
    assert (b.enabled, b.shop_name, b.message) == (True, "Squish Co", "Thanks!")
    assert branding.active() is not None

def test_save_leaves_no_temp_files():
    branding.save(branding.Brand(enabled=True))
    assert sorted(p.name for p in sdir().iterdir()) == ["settings.json"]

@pytest.mark.parametrize("junk", ["{not json", "[1, 2]", ""])
def test_corrupt_settings_fall_back_to_defaults_with_a_note(junk):
    (sdir() / "settings.json").write_text(junk)
    b = branding.load()
    assert b.enabled is False and b.message == branding.DEFAULT_MESSAGE
    assert len(b.notes) == 1 and "settings" in b.notes[0]

def test_hand_edited_overlong_message_is_dropped_not_truncated():
    (sdir() / "settings.json").write_text(json.dumps(
        {"brand_enabled": True, "shop_name": "", "message": "word " * 80}))
    b = branding.load()
    assert b.message == "" and "too long" in b.notes[0]

def test_save_refuses_an_overlong_message():
    with pytest.raises(ValueError, match="2 lines"):
        branding.save(branding.Brand(enabled=True, message="word " * 80))
    assert not (sdir() / "settings.json").exists()

def test_save_refuses_a_shop_name_that_cannot_fit():
    with pytest.raises(ValueError, match="shop name"):
        branding.save(branding.Brand(enabled=True, shop_name="W" * 40))

# --- fitting rules ---------------------------------------------------------

def test_default_message_fits():
    assert branding.message_fits(branding.DEFAULT_MESSAGE)

def test_message_fit_boundary():
    two = "Thank you for shopping with us! Follow us for restocks"
    assert branding.message_fits(two)
    assert len(ws.wrap(two, ws.MSG_W, ws.MSG_SIZE)) == 2
    assert not branding.message_fits(two + " every single week, friends!")

def test_a_single_unbreakable_word_wider_than_the_band_does_not_fit():
    assert not branding.message_fits("W" * 40)

def test_shop_name_size_shrinks_then_gives_up():
    assert ws.shop_name_size("Squish") == 16
    assert 8 <= ws.shop_name_size("Squishy Collectibles Co") < 16
    assert ws.shop_name_size("W" * 40) is None

# --- logo ------------------------------------------------------------------

def _save(tmp_path, im, name="logo.png"):
    p = tmp_path / name; im.save(p); return p

def test_logo_is_trimmed_fitted_and_made_one_bit(tmp_path):
    im = Image.new("RGB", (3000, 3000), "white")
    im.paste((200, 30, 30), (1000, 1300, 2000, 1700))   # red bar, 1000 x 400
    out = branding.import_logo(_save(tmp_path, im))
    assert out.mode == "1"
    assert out.size == (375, 150)                       # 2.5:1, height-bound
    assert out.getpixel((10, 10)) == 0                  # red became black

def test_transparent_background_becomes_white(tmp_path):
    im = Image.new("RGBA", (600, 200), (0, 0, 0, 0))    # transparent *black*
    im.paste((0, 0, 0, 255), (100, 50, 500, 150))
    out = branding.import_logo(_save(tmp_path, im))
    assert out.size == (450, 112)              # 112.5 rounds to even
    assert any(p == 255 for p in out.get_flattened_data()) is False  # trimmed to the ink

def test_a_tiny_logo_is_scaled_up(tmp_path):
    im = Image.new("L", (30, 10), 0)
    assert branding.import_logo(_save(tmp_path, im)).size == (450, 150)

def test_a_blank_image_is_refused(tmp_path):
    with pytest.raises(ValueError, match="blank"):
        branding.import_logo(_save(tmp_path, Image.new("RGB", (300, 100), "white")))

def test_a_non_image_is_refused(tmp_path):
    p = tmp_path / "x.png"; p.write_text("not an image")
    with pytest.raises(OSError):
        branding.import_logo(p)

def test_logo_is_saved_with_settings_and_removed_with_none(tmp_path):
    logo = branding.import_logo(_save(tmp_path, Image.new("L", (300, 100), 0)))
    branding.save(branding.Brand(enabled=True, logo=logo))
    assert branding.load().logo.size == logo.size
    branding.save(branding.Brand(enabled=True, logo=None))
    assert branding.load().logo is None
    assert not (sdir() / "logo.png").exists()

def test_unreadable_stored_logo_falls_back_with_a_note():
    branding.save(branding.Brand(enabled=True, shop_name="Squish"))
    (sdir() / "logo.png").write_text("corrupt")
    b = branding.load()
    assert b.logo is None and "logo" in b.notes[0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_branding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'branding'`.

- [ ] **Step 3: Split `data_dir()` out of `logstore.log_dir()`**

Replace `log_dir` in `src/logstore.py`:

```python
def data_dir():
    """The app's own per-user folder. Logs and branding settings live in it."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData/Local")
        return _adopt_legacy(pathlib.Path(base), "PackingSlips", APP)
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local/share")
    return _adopt_legacy(pathlib.Path(base), "packing-slips", "label-condense")

def log_dir():
    override = os.environ.get("PACKING_LOG_DIR")
    d = pathlib.Path(override) if override else data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

Run: `.venv/bin/python -m pytest tests/test_logstore.py -q` — Expected: PASS.

- [ ] **Step 4: Add band geometry to `src/whatnot_slips.py`**

Insert before `# --------------------------------------------------------------------- labels`:

```python
# ----------------------------------------------------------------- brand band
BAND = 19.0                      # how far a branded header pushes the page down
LOGO_W, LOGO_H = 108.0, 36.0     # 1.5 x 0.5 in
LOGO_TOP = H - 12
MSG_SIZE = 9
MSG_W = W - M - (M + LOGO_W + 8) # 140 pt beside the logo box

def shop_name_size(name):
    """Largest bold size, 16 down to 8 pt, at which the name fills the logo
    box; None when even 8 pt is too wide."""
    name = renderable(name)
    for size in range(16, 7, -1):
        if sw(name, size, True) <= LOGO_W:
            return size
    return None
```

- [ ] **Step 5: Create `src/branding.py`**

```python
"""The shop's branding for the slip header: what it says, where it is kept,
and turning a chosen image into what the thermal head will print. Knows
nothing about tkinter; drawing it is whatnot_slips' job."""
import json, os, pathlib, tempfile
from dataclasses import dataclass, field

from PIL import Image, ImageOps

import logstore
import whatnot_slips as ws

DEFAULT_MESSAGE = "Thank you for shopping with us!"
LOGO_PX = (450, 150)             # the 108 x 36 pt logo box at 300 dpi
MESSAGE_LINES = 2

@dataclass
class Brand:
    enabled: bool = False
    shop_name: str = ""
    message: str = DEFAULT_MESSAGE
    logo: Image.Image | None = None
    notes: list = field(default_factory=list)   # why something fell back

def settings_dir():
    override = os.environ.get("LABEL_CONDENSE_SETTINGS_DIR")
    d = pathlib.Path(override) if override else logstore.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d

def _settings_path(): return settings_dir() / "settings.json"
def _logo_path():     return settings_dir() / "logo.png"

def message_fits(text):
    text = ws.renderable(text)
    if not text:
        return True
    lines = ws.wrap(text, ws.MSG_W, ws.MSG_SIZE)
    return (len(lines) <= MESSAGE_LINES
            and all(ws.sw(ln, ws.MSG_SIZE) <= ws.MSG_W for ln in lines))

def name_fits(name):
    return ws.shop_name_size(name) is not None

def problems(b):
    """Why `b` can't be saved, in words for the person; [] when it can.
    Refusing here is what keeps anything from being cut off on paper."""
    out = []
    if not message_fits(b.message):
        out.append("The message is too long: it must fit on 2 lines.")
    if not name_fits(b.shop_name):
        out.append("The shop name is too long to fit in the logo space.")
    return out

def load():
    b = Brand()
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
        b.enabled = bool(raw.get("brand_enabled", False))
        b.shop_name = str(raw.get("shop_name", ""))
        b.message = str(raw.get("message", DEFAULT_MESSAGE))
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError) as exc:
        b.notes.append(f"branding settings unreadable ({exc}); using defaults")
    if not message_fits(b.message):
        b.notes.append("branding message too long for 2 lines; not printed")
        b.message = ""
    if not name_fits(b.shop_name):
        b.notes.append("shop name too long to fit; not printed")
        b.shop_name = ""
    if _logo_path().exists():
        try:
            with Image.open(_logo_path()) as im:
                b.logo = im.convert("1")
        except (OSError, ValueError) as exc:
            b.notes.append(f"logo unreadable ({exc}); showing the shop name instead")
    return b

def active():
    """The brand to print with, or None when branding is switched off."""
    b = load()
    return b if b.enabled else None

def _replace_atomically(path, write):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise

def save(b):
    errs = problems(b)
    if errs:
        raise ValueError(" ".join(errs))
    data = json.dumps({"brand_enabled": b.enabled, "shop_name": b.shop_name,
                       "message": b.message}, indent=2)
    _replace_atomically(_settings_path(),
                        lambda tmp: pathlib.Path(tmp).write_text(data, encoding="utf-8"))
    if b.logo is None:
        _logo_path().unlink(missing_ok=True)
    else:
        _replace_atomically(_logo_path(), lambda tmp: b.logo.save(tmp, "PNG"))

def import_logo(path):
    """Any image Pillow reads, turned into exactly what will print:
    transparency flattened onto white, trimmed to its ink, fitted to the logo
    box at 300 dpi, then thresholded to pure black and white like the labels."""
    with Image.open(path) as im:
        im.load()
        rgba = im.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat.alpha_composite(rgba)
    g = flat.convert("L")
    box = ImageOps.invert(g).point(lambda p: 255 if p > 127 else 0).getbbox()
    if box is None:
        raise ValueError("The image is blank: nothing in it would print.")
    g = g.crop(box)
    r = min(LOGO_PX[0] / g.width, LOGO_PX[1] / g.height)
    g = g.resize((max(1, round(g.width * r)), max(1, round(g.height * r))),
                 Image.LANCZOS)
    return g.point(lambda p: 255 if p >= 128 else 0, "1")
```

Note on `test_transparent_background_becomes_white`: the transparent pixels are RGBA black at alpha 0; flattening onto white makes them white, so the bbox is the opaque 400×100 bar → fitted to 450×112, all ink. (`any(p == 255 ...) is False` asserts no white remains after trimming.)

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If `test_message_fit_boundary`'s sample text wraps differently from 2 lines, print `ws.wrap(two, ws.MSG_W, ws.MSG_SIZE)` and adjust the *sample text* (not the rule) so it is exactly 2 lines and the extended one is 3.

- [ ] **Step 7: Commit**

```bash
git add src/logstore.py src/whatnot_slips.py src/branding.py tests/test_branding.py
git commit -m "feat: branding settings store and logo conversion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Draw the branded band; audit the message; render a preview

**Files:**
- Modify: `src/whatnot_slips.py` (`slip_ps`, `build`, `verify`, new `brand_ops`, `brand_message_lines`, `logo_prolog`, `audit_brand`, `preview_png`, `PS_HEAD`)
- Create: `tests/test_brand_render.py`

**Interfaces:**
- Consumes: `branding.Brand` (duck-typed: `.shop_name`, `.message`, `.logo`), constants from Task 3.
- Produces:
  - `slip_ps(ship, grouped, to, frm, brand=None) -> list[str]`
  - `build(src, out, quiet=False, progress=None, brand=None)`
  - `verify(src, out, deep=False, progress=None, brand=None) -> Audit`
  - `brand_message_lines(brand) -> list[str]`, `brand_ops(brand, pi, npages) -> list[str]`, `logo_prolog(im) -> str`, `audit_brand(a, brand, slip_texts: list[str]) -> None`, `preview_png(brand, png_path) -> None`
  - `PS_HEAD` string constant

- [ ] **Step 1: Write the failing tests**

Create `tests/test_brand_render.py`:

```python
import pathlib, tempfile
from PIL import Image

import branding
import whatnot_slips as ws
from test_slip_golden import SHIP, ITEMS, TO, FRM, golden_slip_ps, GOLDEN

def brand(**kw):
    kw.setdefault("enabled", True)
    return branding.Brand(**kw)

def solid_logo(w=450, h=150):
    return Image.new("1", (w, h), 0)

def ps_to_pdf(ps_pages, tmp, prolog=""):
    ps = pathlib.Path(tmp) / "t.ps"; pdf = pathlib.Path(tmp) / "t.pdf"
    ps.write_text(ws.PS_HEAD + prolog + "".join(ps_pages))
    ws._spawn([ws._bin("gs"), "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
               "-dFIXEDMEDIA", f"-dDEVICEWIDTHPOINTS={ws.W}",
               f"-dDEVICEHEIGHTPOINTS={ws.H}", f"-sOutputFile={pdf}", str(ps)])
    return pdf

def test_no_brand_is_still_byte_identical():
    import hashlib
    assert hashlib.sha256(golden_slip_ps(brand=None).encode()).hexdigest() == GOLDEN

def test_band_draws_corner_text_message_and_shifts_the_page():
    ps = golden_slip_ps(brand=brand(shop_name="Squish Co"))
    assert "(Packing Slip 1/1)" in ps
    assert "(Thank you for shopping with us!)" in ps
    assert "(Squish Co)" in ps
    assert "(Whatnot Packing Slip)" not in ps
    assert f"{ws.M} {ws.H - 52}" in ps          # the rule under the band

def test_logo_is_invoked_per_page_but_defined_once():
    ps = golden_slip_ps(brand=brand(logo=solid_logo()))
    assert " Logo grestore" in ps and "LogoData" not in ps
    assert ws.logo_prolog(solid_logo()).count("/LogoData") == 1

def test_logo_takes_the_place_of_the_shop_name():
    ps = golden_slip_ps(brand=brand(shop_name="Squish Co", logo=solid_logo()))
    assert "(Squish Co)" not in ps

def test_no_logo_no_name_lets_the_message_use_the_full_width():
    ops = ws.brand_ops(brand(), 1, 1)
    assert any(f"({ws.esc('Thank you for shopping with us!')}) {ws.M:.1f}" in o for o in ops)

def test_branded_page_text_extracts_cleanly():
    """What pdftotext reads back is what load() and verify() will see."""
    msg = "Thank you for shopping with us! Follow us for restocks"
    b = brand(shop_name="Squish Co", message=msg)
    with tempfile.TemporaryDirectory() as td:
        pages = ws.pdf_pages(str(ps_to_pdf(
            ws.slip_ps(SHIP, ws.group_items(ITEMS), TO, FRM, b), td)))
    assert len(pages) == 1 and "Packing Slip" in pages[0]
    flat = ws.renderable(pages[0])
    for ln in ws.brand_message_lines(b):
        assert ln in flat
    assert "Jane Buyer" in flat and "ROSEY BALL" in flat

def test_logo_prints_on_every_page(tmp_path):
    """A string DataSource is re-read from the start on each use; if it were
    consumed, page 2 onward would print an empty logo box."""
    b = brand(logo=solid_logo())
    pages = ws.slip_ps(SHIP, ws.group_items(ITEMS), TO, FRM, b) * 3
    pdf = ps_to_pdf(pages, tmp_path, prolog=ws.logo_prolog(b.logo))
    ws._spawn([ws._bin("pdftoppm"), "-r", "72", "-gray", str(pdf),
               str(tmp_path / "p")])
    shots = sorted(tmp_path.glob("p*.pgm"))
    assert len(shots) == 3
    for s in shots:
        im = Image.open(s)
        # centre of the logo box: 16 + 54 pt across, 12 + 18 pt down
        assert im.getpixel((70, 30)) < 64, s.name

def test_audit_brand_passes_when_every_page_has_the_message():
    b = brand()
    a = ws.Audit()
    ws.audit_brand(a, b, ["Packing Slip 1/2 Thank you for shopping with us!",
                          "Packing Slip 2/2 Thank you for shopping with us!"])
    assert a.fail == [] and a.checks == 2

def test_audit_brand_fails_a_page_missing_the_message():
    a = ws.Audit()
    ws.audit_brand(a, brand(), ["Thank you for shopping with us!", "nothing here"])
    assert [l for l, _ in a.fail] == ["slip page 2 brand message"]

def test_audit_brand_is_silent_without_a_brand_or_message():
    a = ws.Audit()
    ws.audit_brand(a, None, ["x"]); ws.audit_brand(a, brand(message=""), ["x"])
    assert a.checks == 0

def test_preview_png_renders_one_slip(tmp_path):
    out = tmp_path / "preview.png"
    ws.preview_png(brand(shop_name="Squish Co", logo=solid_logo()), out)
    im = Image.open(out)
    assert im.size == (812, 1218)              # 4 x 6 in at 203 dpi
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_brand_render.py -v`
Expected: FAIL — `slip_ps() got an unexpected keyword argument 'brand'` / missing attributes.

- [ ] **Step 3: Implement band drawing**

In `src/whatnot_slips.py`, in the brand-band section from Task 3, append:

```python
def brand_message_lines(brand):
    """The message as it will print: up to two lines, in the width left over
    once the logo box is (or isn't) taken."""
    msg = renderable(brand.message)
    if not msg:
        return []
    taken = brand.logo is not None or renderable(brand.shop_name)
    return wrap(msg, MSG_W if taken else W - 2 * M, MSG_SIZE)[:2]

def brand_ops(brand, pi, npages):
    """Logo (or shop name) on the left, the message beside it, and
    'Packing Slip n/m' in the corner -- load() and verify() find slip pages
    by those words, so they stay on every page."""
    ops = [f"7 HV (Packing Slip {pi}/{npages}) {W-M} {H-20} R"]
    x = M
    if brand.logo is not None:
        w, h = brand.logo.size
        ops.append(f"gsave {M} {LOGO_TOP - h * 0.24:.2f} translate "
                   f"{w * 0.24:.2f} {h * 0.24:.2f} scale Logo grestore")  # 72/300
        x = M + LOGO_W + 8
    elif renderable(brand.shop_name):
        size = shop_name_size(brand.shop_name) or 8
        ops.append(f"{size} HB ({esc(renderable(brand.shop_name))}) {M} "
                   f"{LOGO_TOP - LOGO_H / 2 - size * 0.35:.1f} L")
        x = M + LOGO_W + 8
    for k, ln in enumerate(brand_message_lines(brand)):
        ops.append(f"{MSG_SIZE} HV ({esc(ln)}) {x:.1f} {H - 33 - 11 * k} L")
    return ops

def logo_prolog(im):
    """Define the logo once; every slip page draws it with `Logo`. A string
    DataSource is read from its start on each use, so a 300-page job carries
    one copy of the logo, not 300."""
    w, h = im.size
    data = base64.a85encode(im.tobytes()).decode()
    return ("/LogoData <~"
            + "\n".join(data[i:i+120] for i in range(0, len(data), 120))
            + "~> def\n"
            f"/Logo {{ /DeviceGray setcolorspace << /ImageType 1 /Width {w} "
            f"/Height {h} /BitsPerComponent 1 /Decode [0 1] "
            f"/ImageMatrix [{w} 0 0 -{h} 0 {h}] /DataSource LogoData >> image }} def\n")
```

- [ ] **Step 4: Thread `brand` through `slip_ps`**

Change the signature to `def slip_ps(ship, grouped, to, frm, brand=None):` and edit its body. Every changed line, in order:

```python
    d = BAND if brand else 0         # a branded header pushes everything down
    TOP_Y, BOT_Y = H - 116 - d, 74.0
```

Replace the two title lines:

```python
        A(f"11 HB 0 setgray (Whatnot Packing Slip) {M} {H-26} L")
        A(f"8 HV ({pi}/{len(pages)}) {W-M} {H-26} R")
```
with:
```python
        if brand:
            A("0 setgray"); s.extend(brand_ops(brand, pi, len(pages)))
        else:
            A(f"11 HB 0 setgray (Whatnot Packing Slip) {M} {H-26} L")
            A(f"8 HV ({pi}/{len(pages)}) {W-M} {H-26} R")
```

Then shift the rest of the header:

```python
        A(f"0.8 setlinewidth {M} {H-33-d} moveto {W-M} {H-33-d} lineto stroke")
        yy = H - 46 - d
```
and
```python
        th = H - 100 - d
```

(`H` is a float, so with `d = 0` every number formats exactly as before — the golden test proves it.)

- [ ] **Step 5: `PS_HEAD`, `build`, `verify`, `audit_brand`, `preview_png`**

Above `def build`:

```python
PS_HEAD = f"%!PS-Adobe-3.0\n<< /PageSize [{W} {H}] >> setpagedevice\n"
```

In `build`: change the signature to `def build(src, out, quiet=False, progress=None, brand=None):`, and replace `ps = [f"%!PS-Adobe-3.0\n..."]` with:

```python
    ps = [PS_HEAD + (logo_prolog(brand.logo) if brand and brand.logo is not None else "")]
```

and the slip call with `sp = slip_ps(ship, group_items(items), to, frm, brand)`.

Below `audit_skus`, add:

```python
def audit_brand(a, brand, slip_texts):
    """The message is cosmetic but promised on every page; checked line by
    line because a two-line message lands on two text lines."""
    if brand is None:
        return
    lines = brand_message_lines(brand)
    if not lines:
        return
    for i, t in enumerate(slip_texts, 1):
        flat = renderable(t)
        a.ok(all(ln in flat for ln in lines), f'slip page {i} brand message',
             lines[0][:40])
```

In `verify`: change the signature to `def verify(src, out, deep=False, progress=None, brand=None):` and, just before `# ---- no order lost or invented`, add:

```python
    audit_brand(a, brand, [p for p in out_pages if 'Packing Slip' in p])
```

At the end of the brand-band section (it needs `slip_ps`/`group_items`, so place it right after `build`):

```python
def preview_png(brand, png):
    """One sample slip through the real renderer, at a thermal head's 203 dpi
    in pure black and white -- what the Branding tab shows is what prints."""
    ship = dict(svc='USPS Ground Advantage', dims='12 x 12 x 12 in',
                track='9300120762602517212464', weight='7.0 oz')
    items = [dict(qty=1, name='ROSEY BALL #2', order='1', price=2.0, sku='A-T-63'),
             dict(qty=1, name='ROSEY BALL #3', order='2', price=3.0, sku='A-T-63'),
             dict(qty=1, name='CRUNCHY LOBSTER #1', order='3', price=3.0, sku='TB200-477')]
    to = ['To: buyer123', 'Jane Buyer', '1 Main St', 'Springfield, IL 62701']
    frm = ['From: ' + (renderable(brand.shop_name) or 'your shop'),
           '2 Shop Rd', 'Townsville, CA 90001']
    ps = PS_HEAD + (logo_prolog(brand.logo) if brand.logo is not None else "") \
         + slip_ps(ship, group_items(items), to, frm, brand)[0]
    with tempfile.NamedTemporaryFile('w', suffix='.ps', delete=False) as f:
        f.write(ps); psfile = f.name
    try:
        _spawn([_bin('gs'), '-q', '-dBATCH', '-dNOPAUSE', '-sDEVICE=pngmono',
                '-r203', '-dFIXEDMEDIA', f'-dDEVICEWIDTHPOINTS={W}',
                f'-dDEVICEHEIGHTPOINTS={H}', f'-sOutputFile={png}', psfile])
    finally:
        os.unlink(psfile)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If `test_logo_prints_on_every_page` fails only on pages 2+, the string DataSource is being consumed. Change `/DataSource LogoData` in `logo_prolog` to `/DataSource {{ LogoData }}` (inside the f-string; a procedure that hands back the whole string each call, which is valid because the string holds exactly one image's data) and re-run.

- [ ] **Step 7: Commit**

```bash
git add src/whatnot_slips.py tests/test_brand_render.py
git commit -m "feat: draw an optional branded header band and audit its message

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pass the brand through the job runner and the CLI

**Files:**
- Modify: `src/job.py` (`Job.__init__`, `Job.run`)
- Modify: `src/whatnot_slips.py` (`main`, `_run`)
- Modify: `tests/test_job.py` (fakes accept `brand`), add tests
- Create: `tests/test_cli_brand.py`

**Interfaces:**
- Consumes: `branding.active()`, `Brand.notes`, `build(..., brand=)`, `verify(..., brand=)`.
- Produces: `Job(src, dest, deep=True, brand=None)`; CLI flag `--no-brand` on `build` and `verify`.

- [ ] **Step 1: Make existing job fakes accept the new keyword**

Run:
```bash
sed -i 's/quiet=False, progress=None)/quiet=False, progress=None, brand=None)/; s/deep=False, progress=None)/deep=False, progress=None, brand=None)/' tests/test_job.py
grep -n "brand=None" tests/test_job.py | wc -l
```
Expected: `8`

- [ ] **Step 2: Write failing tests** — append to `tests/test_job.py`:

```python
def test_brand_reaches_build_and_verify_and_notes_reach_the_log(tmp_path, monkeypatch):
    import branding
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    seen = {}
    def fake_build(s, o, quiet=False, progress=None, brand=None):
        seen["build"] = brand; pathlib.Path(o).write_text("pdf"); return (1, 1, 1)
    def fake_verify(s, o, deep=False, progress=None, brand=None):
        seen["verify"] = brand; return FakeAudit(0)
    monkeypatch.setattr(J.ws, "build", fake_build)
    monkeypatch.setattr(J.ws, "verify", fake_verify)
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    b = branding.Brand(enabled=True, notes=["logo unreadable (x); showing the shop name instead"])
    lines = []
    res = J.Job(src, dest, brand=b).run(
        lambda e: lines.append(e["line"]) if e["kind"] == "log" else None)
    assert res.ok and seen == {"build": b, "verify": b}
    assert any("logo unreadable" in l for l in lines)
```

Create `tests/test_cli_brand.py`:

```python
import sys
import branding
import whatnot_slips as ws

def run_cli(monkeypatch, *argv):
    seen = {}
    def fake_build(s, o, quiet=False, progress=None, brand=None):
        seen["build"] = brand; open(o, "w").write("pdf"); return (1, 1, 1)
    class A:
        fail = []; checks = 1
        def report(self, t): return True
    def fake_verify(s, o, deep=False, progress=None, brand=None):
        seen["verify"] = brand; return A()
    monkeypatch.setattr(ws, "build", fake_build)
    monkeypatch.setattr(ws, "verify", fake_verify)
    monkeypatch.setattr(sys, "argv", ["whatnot_slips.py", *argv])
    assert ws.main() == 0
    return seen

def test_cli_uses_saved_branding_by_default(monkeypatch, tmp_path):
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert seen["build"].shop_name == "Squish Co" and seen["verify"] is seen["build"]

def test_no_brand_flag_turns_it_off(monkeypatch, tmp_path):
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"), "--no-brand")
    assert seen == {"build": None, "verify": None}

def test_branding_switched_off_means_none(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert seen == {"build": None, "verify": None}

def test_verify_subcommand_takes_the_flag_too(monkeypatch):
    branding.save(branding.Brand(enabled=True))
    assert run_cli(monkeypatch, "verify", "a.pdf", "b.pdf", "--no-brand") == {"verify": None}
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py tests/test_cli_brand.py -v`
Expected: FAIL — `Job.__init__() got an unexpected keyword argument 'brand'`; CLI: `unrecognized arguments: --no-brand` / brand never passed.

- [ ] **Step 4: Implement `job.py`**

```python
class Job:
    def __init__(self, src, dest, deep=True, brand=None):
        self.src = pathlib.Path(src)
        self.dest = pathlib.Path(dest)
        self.deep = deep
        self.brand = brand
```

In `run`, right after `def progress(...)` and before `try:`, add:

```python
        for note in (self.brand.notes if self.brand else []):
            log(f"branding: {note}")
```

and pass the brand on both calls:

```python
            n, nsl, nlb = ws.build(str(self.src), str(self.dest), quiet=True,
                                   progress=progress, brand=self.brand)
            ...
            audit = ws.verify(str(self.src), str(self.dest), deep=self.deep,
                              progress=progress, brand=self.brand)
```

- [ ] **Step 5: Implement the CLI** in `src/whatnot_slips.py`

In `main`, after each subparser's existing arguments add:

```python
    b.add_argument('--no-brand', action='store_true',
                   help='plain header, ignoring the saved branding')
```
and
```python
    v.add_argument('--no-brand', action='store_true')
```

Replace `_run`:

```python
def _run(args):
    brand = None
    if not args.no_brand:
        import branding            # lazily: branding imports this module
        brand = branding.active()
        for note in (brand.notes if brand else []):
            print(f"branding: {note}")
    if args.cmd == 'build':
        n, nsl, nlb = build(args.src, args.out, brand=brand)
        size = os.path.getsize(args.out)
        print(f"built {args.out}: {n} shipments, {nsl} slip pages, {nlb} labels, "
              f"{size/1e6:.2f} MB")
        if args.no_verify: return 0
    a = verify(args.src, args.out, deep=args.deep, brand=brand)
    return 0 if a.report('AUDIT') else 1
```

(`run.sh` calls `build` from `src/`, so `import branding` resolves via the script's own directory; it needs no change.)

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/job.py src/whatnot_slips.py tests/test_job.py tests/test_cli_brand.py
git commit -m "feat: pass saved branding through the job runner and the CLI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Branding tab in the GUI

**Files:**
- Modify: `src/packing_gui.py` (`__init__`, `show`, `start`, new `_build_branding` section)
- Create: `tests/test_gui_branding.py`

**Interfaces:**
- Consumes: `branding.load/save/problems/import_logo/active/Brand`, `ws.preview_png`, `Job(..., brand=)`.
- Produces: `App.brand_widgets`, `App.brand_save_btn`, `App.form_brand() -> Brand`, `App.save_branding() -> bool`, `App.choose_logo(path=None)`, `App.remove_logo()`, `App.preview_slip()`, tab name `"branding"`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_gui_branding.py`:

```python
import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")
import branding

@pytest.fixture
def app():
    import packing_gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    a = packing_gui.App(root)
    yield a
    root.destroy()

@pytest.fixture
def errors(monkeypatch):
    import packing_gui
    shown = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                        lambda title, msg: shown.append(msg))
    return shown

def test_branding_tab_exists(app):
    app.tab("branding")
    assert app.current_tab == "branding"

def test_form_starts_from_saved_settings(monkeypatch):
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co", message="Hi!"))
    import packing_gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    try:
        a = packing_gui.App(root)
        b = a.form_brand()
        assert (b.enabled, b.shop_name, b.message) == (True, "Squish Co", "Hi!")
    finally:
        root.destroy()

def test_save_writes_settings(app, errors):
    app.brand_on.set(True); app.shop_name.set("Squish Co")
    assert app.save_branding() is True and errors == []
    assert branding.load().shop_name == "Squish Co"

def test_save_refuses_an_overlong_message(app, errors):
    app.message_box.delete("1.0", "end")
    app.message_box.insert("1.0", "word " * 80)
    assert app.save_branding() is False
    assert "2 lines" in errors[0]
    assert branding.load().message == branding.DEFAULT_MESSAGE

def test_choosing_a_logo_does_not_change_what_prints_until_save(app, errors, tmp_path):
    p = tmp_path / "l.png"; Image.new("L", (300, 100), 0).save(p)
    app.choose_logo(str(p))
    assert errors == [] and app.form_brand().logo is not None
    assert branding.load().logo is None
    app.save_branding()
    assert branding.load().logo is not None

def test_a_bad_logo_shows_an_error_and_keeps_the_old_one(app, errors, tmp_path):
    p = tmp_path / "x.png"; p.write_text("nope")
    app.choose_logo(str(p))
    assert len(errors) == 1 and app.form_brand().logo is None

def test_remove_logo_clears_the_form(app, tmp_path):
    p = tmp_path / "l.png"; Image.new("L", (300, 100), 0).save(p)
    app.choose_logo(str(p)); app.remove_logo()
    assert app.form_brand().logo is None

def test_branding_is_locked_while_a_run_is_working(app):
    app.show("working")
    assert app.brand_save_btn.instate(["disabled"])
    assert str(app.message_box.cget("state")) == "disabled"
    app.show("idle")
    assert not app.brand_save_btn.instate(["disabled"])

def test_start_hands_the_saved_brand_to_the_job(app, monkeypatch, tmp_path):
    import packing_gui
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    seen = {}
    monkeypatch.setattr(app, "ask_destination", lambda: tmp_path / "o.pdf")
    monkeypatch.setattr(packing_gui.jobmod.Job, "run",
                        lambda self, emit: seen.setdefault("brand", self.brand))
    app.src = tmp_path / "in.pdf"
    app.start()
    app.root.after_cancel(app._after_id)
    import time; time.sleep(0.2)
    assert seen["brand"].shop_name == "Squish Co"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gui_branding.py -v`
Expected: FAIL — `KeyError: 'branding'` / missing attributes. (If it reports "no display available", run under `xvfb-run -a` as the other GUI tests do.)

- [ ] **Step 3: Implement**

In `src/packing_gui.py`, imports:

```python
import base64, io, tempfile
import branding
import whatnot_slips as ws
```

(merge into the existing `import datetime as dt, os, ...` line style: `import base64, datetime as dt, io, os, pathlib, queue, sys, tempfile, threading, tkinter as tk`.)

In `__init__`, add the tab button after the Logs button:

```python
        self.brand_btn = ttk.Button(bar, text="Branding", command=lambda: self.tab("branding"))
        self.brand_btn.pack(side="left")
```

add the pane to `self.panes`:

```python
            "branding": ttk.Frame(root),
```

and build it **before** `self.show("idle")` (because `show` now touches its widgets):

```python
        self._build_branding(self.panes["branding"])
        self.panes["run"].pack(fill="both", expand=True)
        self.show("idle")
```

In `show`, append:

```python
        if hasattr(self, "brand_widgets"):
            self._lock_branding(name == "working")
```

In `start`, replace `job = jobmod.Job(self.src, dest)` with:

```python
        job = jobmod.Job(self.src, dest, brand=branding.active())
```

Add a new section after the logs section:

```python
    # ------------------------------------------------------------ branding
    def _build_branding(self, pane):
        saved = branding.load()
        self.form_logo = saved.logo
        f = ttk.Frame(pane); f.pack(fill="both", expand=True, padx=16, pady=12)
        f.columnconfigure(1, weight=1)

        self.brand_on = tk.BooleanVar(value=saved.enabled)
        on = ttk.Checkbutton(f, text="Show branding on slips", variable=self.brand_on)
        on.grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(f, text="Shop name").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.shop_name = tk.StringVar(value=saved.shop_name)
        name = ttk.Entry(f, textvariable=self.shop_name)
        name.grid(row=1, column=1, columnspan=2, sticky="we", pady=(10, 0))

        ttk.Label(f, text="Logo").grid(row=2, column=0, sticky="nw", pady=(10, 0))
        self.logo_view = ttk.Label(f, text="(none — the shop name is shown)")
        self.logo_view.grid(row=2, column=1, sticky="w", pady=(10, 0))
        btns = ttk.Frame(f); btns.grid(row=2, column=2, sticky="ne", pady=(10, 0))
        choose = ttk.Button(btns, text="Choose…", command=self.choose_logo)
        remove = ttk.Button(btns, text="Remove", command=self.remove_logo)
        choose.pack(fill="x"); remove.pack(fill="x", pady=(4, 0))

        ttk.Label(f, text="Message").grid(row=3, column=0, sticky="nw", pady=(10, 0))
        self.message_box = tk.Text(f, height=2, width=30, wrap="word")
        self.message_box.insert("1.0", saved.message)
        self.message_box.grid(row=3, column=1, columnspan=2, sticky="we", pady=(10, 0))

        foot = ttk.Frame(f); foot.grid(row=4, column=0, columnspan=3, sticky="we", pady=(14, 0))
        preview = ttk.Button(foot, text="Preview slip", command=self.preview_slip)
        preview.pack(side="left")
        self.brand_save_btn = ttk.Button(foot, text="Save", command=self.save_branding)
        self.brand_save_btn.pack(side="right")
        self.brand_status = tk.StringVar(value="")
        ttk.Label(foot, textvariable=self.brand_status,
                  foreground="#6a6d73").pack(side="right", padx=8)

        self.brand_widgets = [on, name, choose, remove, preview, self.brand_save_btn]
        self._show_logo()

    def _lock_branding(self, locked):
        """Settings are read once when a run starts; editing mid-run would
        look like it applied when it didn't."""
        for w in self.brand_widgets:
            w.state(["disabled"] if locked else ["!disabled"])
        self.message_box.configure(state="disabled" if locked else "normal")

    def _show_logo(self):
        if self.form_logo is None:
            self.logo_photo = None
            self.logo_view.configure(image="", text="(none — the shop name is shown)")
            return
        im = self.form_logo.resize((self.form_logo.width // 2,
                                    max(1, self.form_logo.height // 2)), Image.NEAREST)
        buf = io.BytesIO(); im.save(buf, "PNG")
        self.logo_photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self.logo_view.configure(image=self.logo_photo, text="")

    def form_brand(self):
        return branding.Brand(enabled=self.brand_on.get(),
                              shop_name=self.shop_name.get().strip(),
                              message=self.message_box.get("1.0", "end-1c").strip(),
                              logo=self.form_logo)

    def choose_logo(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Choose your logo",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                           ("All files", "*.*")])
        if not path:
            return
        try:
            self.form_logo = branding.import_logo(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Can't use that image", str(exc))
            return
        self.brand_status.set("Not saved yet")
        self._show_logo()

    def remove_logo(self):
        self.form_logo = None
        self.brand_status.set("Not saved yet")
        self._show_logo()

    def save_branding(self):
        b = self.form_brand()
        errs = branding.problems(b)
        if errs:
            messagebox.showerror("Can't save", "\n".join(errs))
            return False
        try:
            branding.save(b)
        except OSError as exc:
            messagebox.showerror("Can't save", f"The settings could not be saved: {exc}")
            return False
        self.brand_status.set("Saved")
        return True

    def preview_slip(self):
        b = self.form_brand()
        errs = branding.problems(b)
        if errs:
            messagebox.showerror("Can't preview", "\n".join(errs))
            return
        with tempfile.TemporaryDirectory() as td:
            png = pathlib.Path(td) / "preview.png"
            try:
                ws.preview_png(b, png)
            except (OSError, subprocess.CalledProcessError) as exc:
                messagebox.showerror("Can't preview", f"The preview could not be drawn: {exc}")
                return
            photo = tk.PhotoImage(file=str(png)).subsample(2)
        win = tk.Toplevel(self.root); win.title("Slip preview")
        lbl = ttk.Label(win, image=photo); lbl.image = photo
        lbl.pack(padx=8, pady=8)
```

Also add `import subprocess` to the import line and `from PIL import Image` below the tkinter imports.

- [ ] **Step 4: Run the GUI tests and the full suite**

Run: `.venv/bin/python -m pytest tests/test_gui_branding.py tests/test_gui.py tests/test_gui_flow.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Look at it**

Run: `.venv/bin/python src/packing_gui.py`, open the Branding tab, set a shop name, Save, click Preview slip. Confirm the preview shows the band, `Packing Slip 1/1` in the corner, `[A-T-63] ROSEY BALL` in the table, and nothing overlapping. Close the window.

- [ ] **Step 6: Commit**

```bash
git add src/packing_gui.py tests/test_gui_branding.py
git commit -m "feat: Branding tab to set the shop name, logo and thank-you message

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Real-export verification, docs, and bundle check

**Files:**
- Modify: `README.md`
- Modify: `packaging/smoke_test.sh` only if Step 3 shows it needs to

- [ ] **Step 1: Full branded run on the SKU export, deep audit**

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
import os; os.environ["LABEL_CONDENSE_SETTINGS_DIR"] = "/tmp/claude-1000/lc-settings"
import branding, whatnot_slips as ws
branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
b = branding.active()
src = os.path.expanduser("~/Desktop/labels/precondense-oct13.pdf")
ws.build(src, "/tmp/claude-1000/oct13-branded.pdf", quiet=True, brand=b)
a = ws.verify(src, "/tmp/claude-1000/oct13-branded.pdf", deep=True, brand=b)
print(a.text("AUDIT"))
EOF
```
Expected: `failures : 0`. Then render one dense page and one ordinary page to PNG (`pdftoppm -r 100 -f N -l N`) and look at them: band, logo/name, SKU prefix, no overlaps, page 2 of a multi-page slip has the band too.

- [ ] **Step 2: Unbranded parity on a Sept export**

Run: `PACKING_TEST_PDF=".packing/archive/2026-09-11-Whatnot-Combined-Labels-Packing-Slips-c4c74f99-1.pdf" PACKING_SKU_PDF=~/Desktop/labels/precondense-oct13.pdf .venv/bin/python -m pytest -q`
Expected: all pass, 0 skipped except tests needing a display (if any).

- [ ] **Step 3: Bundle smoke test**

Read `packaging/smoke_test.sh` and run it as it documents. `branding.py` is imported by `packing_gui.py`, so PyInstaller's analysis picks it up through `pathex=[src]`; confirm the frozen app's `--selftest` still passes.

- [ ] **Step 4: README**

In `README.md`:
- Under **Download → Then:** add one short paragraph: "To put your logo and a thank-you note on the slips, open the **Branding** tab, fill it in, click **Preview slip**, then **Save**. Every run after that uses it. `./run.sh` uses the same settings; pass `--no-brand` to `whatnot_slips.py` to skip them."
- Under **Design notes** add:

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: branding tab and SKU design notes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
