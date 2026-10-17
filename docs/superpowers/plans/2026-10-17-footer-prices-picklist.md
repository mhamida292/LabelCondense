# Footer, price toggle and pick list Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user-set footer message on slips (own switch), a switch that hides every price, and an optional pick list at the front of the PDF — each audited.

**Architecture:** All rendering and auditing stays in `src/whatnot_slips.py`, threaded through `build()`/`verify()` as three new keyword inputs (`footer`, `prices`, `pick_list`) beside `brand`. Footer text is stored by `branding.py`; the two per-run switches are stored in `prefs.json` via `recent.py`. `job.py`, the CLI and `run.sh` pass the inputs through; the GUI sets them.

**Tech Stack:** Python 3, PostScript rendered by Ghostscript, Poppler `pdftotext`/`pdftoppm`, Pillow, Tkinter + ttk (Sun Valley), pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-footer-prices-picklist-design.md`

## Global Constraints

- **Byte-identical default:** `footer=None, prices=True, pick_list=False` must reproduce today's output. `tests/test_slip_golden.py` (`GOLDEN`) and `tests/test_brand_render.py::test_no_brand_is_still_byte_identical` pass unchanged; no existing PS op may change when the new inputs are at their defaults.
- Every outcome is print-as-is or DO NOT PRINT. The auditor must not reuse the renderer's parsing for anything that must be right (pick quantities); the footer may reuse the renderer's wrap (cosmetic exception, as `audit_brand()`).
- `Packing Slip` must stay on every slip page and must never appear on a pick-list page; the To:/From: line still anchors `slip_body()`.
- Nothing prints below the 16 pt bottom margin (`M`). Pure black on white.
- Footer: max **120 characters**, at most **2 lines**, refused words `To:`, `From:`, `Packing Slip`, `Pick List`. Own switch, off by default, independent of branding.
- Show prices: default **on**. Add pick list: default **off**. Both remembered across launches.
- Pick list: no `$` amounts and no `#N`, ever; no branding band, no footer.
- Tests: `python3 -m pytest`. If pytest is missing, `python3 -m venv --system-site-packages .venv && .venv/bin/pip install pytest` and use `.venv/bin/python -m pytest` (`.venv/` is gitignored). GUI tests skip without `python3-tk`; say so in reports rather than claiming they passed.
- Never commit a real export (`*.pdf` is gitignored; keep it that way).

## Review Focus

1. **Footer with emoji / non-Latin-1 / newlines** — the GUI Text box allows Enter and pasted emoji. Expect: fit and rendering use `renderable()` text (newlines collapse to spaces, emoji to spaces); a footer that is empty after `renderable()` behaves as no footer. Test in Task 2.
2. **Same product name, different SKU (or SKU vs none) on the pick list** — expect separate rows, each with its own total. Test in Task 6.
3. **A 150-buyer export: pick list spanning several pages** — expect correct `n/m`, the totals line only on the last page, and a passing audit. Test in Task 7 (80 products).
4. **Dense two-page slip with footer and prices off** — expect footer on both pages, no `$` on either, audit passes. Test in Task 5.
5. **Footer saved while header branding is off** — expect the footer still prints (own switch) and the header stays the plain "Whatnot Packing Slip" one. Test in Task 4.

---

### Task 1: Synthetic export fixture

Real exports carry customer data and are never committed, so `verify()` currently has no end-to-end test without `PACKING_TEST_PDF`. Every later audit task needs one.

**Files:**
- Create: `tests/synth.py`
- Test: `tests/test_synth.py`

**Interfaces:**
- Produces: `synth.Item(qty:int, name:str, order:str, price:float, sku:str|None=None)`, `synth.Ship(to:str, items:list[Item], track:str, weight:str="7.0 oz", svc:str="USPS Ground Advantage", dims:str="12 x 12 x 12 in")`, `synth.make_export(path, ships:list[Ship]) -> pathlib.Path` writing a Whatnot-shaped PDF (per shipment: one slip page, then one label page). `synth.sample(n_ships=3) -> list[Ship]` — a small varied set (repeated product with several `#N`, one SKU'd item, one GIVEAWAY, one item with no `#`).

- [ ] **Step 1: Write the failing tests**

```python
def test_synthetic_export_round_trips_through_build_and_verify(tmp_path):
    src = synth.make_export(tmp_path / "src.pdf", synth.sample())
    out = tmp_path / "out.pdf"
    ws.build(str(src), str(out), quiet=True)
    a = ws.verify(str(src), str(out), deep=True)
    assert a.fail == [] and a.checks > 50

def test_synthetic_source_parses_like_a_real_one(tmp_path):
    ships = synth.sample()
    _, data = ws.load(str(synth.make_export(tmp_path / "s.pdf", ships)))
    assert [len(items) for _, _, items in data] == [len(s.items) for s in ships]
    assert [ship["track"] for _, ship, _ in data] == [s.track for s in ships]
    assert any(it["sku"] for _, _, items in data for it in items)
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_synth.py -v` — Expected: FAIL (`No module named 'synth'`).

- [ ] **Step 3: Implement `tests/synth.py`.** Write each source line as one Courier 7 pt `show` string at a fixed x per column so `pdftotext -layout` reproduces the spacing that `RE_ITEM`, `RE_TOTAL`, `RE_SHIP`, `RE_TRACK`, `RE_SKU`, `RE_TO` and `header_lines()` (split at the `From:` column) expect — use the line shapes in `tests/test_sku.py` (`HEAD`, `LOBSTER`) as the template, plus a top line containing `Packing Slip`, a `To: …  From: …` line with address lines under each column, a blank line after each item block, `N Items  $T`, the `USPS …  dims` line and `#track  weight`. The label page draws a black-bordered box with a few filled bars (non-blank when rendered) and no `Packing Slip` text. Render with the same `gs pdfwrite` call `tests/test_brand_render.py::ps_to_pdf` uses.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_synth.py -v` — Expected: PASS. If a regex misses, adjust the fixture's spacing, never the parser.

- [ ] **Step 5: Commit** — `git add tests/synth.py tests/test_synth.py && git commit -m "test: synthetic Whatnot export for end-to-end audit tests"`

---

### Task 2: Footer settings

**Files:**
- Modify: `src/whatnot_slips.py` (brand band section: footer constants + `footer_lines`)
- Modify: `src/branding.py`
- Test: `tests/test_branding_footer.py`

**Interfaces:**
- Produces in `whatnot_slips`: `FOOT_SIZE = 8`, `FOOT_LEAD = 10`, `FOOT_W = W - 2 * M`, `FOOT_BAND = 24.0` (how far a footer lifts the bottom block), `footer_lines(text:str) -> list[str]` (renderable text wrapped to `FOOT_W` at `FOOT_SIZE`, Helvetica regular, first 2 lines; `[]` when empty).
- Produces in `branding`: `Brand.footer_enabled: bool = False`, `Brand.footer: str = ""`, `FOOTER_MAX = 120`, `footer_fits(text) -> bool` (≤120 chars **and** wraps to ≤2 lines with each line ≤ `FOOT_W`), `active_footer() -> str | None` (the saved footer when `footer_enabled` and non-empty after `renderable()`, else `None`; independent of `enabled`). Settings keys `footer_enabled` (bool), `footer` (str).

- [ ] **Step 1: Write the failing tests**

```python
def test_footer_defaults_off_and_empty():
    b = branding.load(); assert (b.footer_enabled, b.footer) == (False, "")
    assert branding.active_footer() is None

def test_footer_round_trips_and_is_independent_of_branding():
    branding.save(branding.Brand(enabled=False, footer_enabled=True, footer="Live Tues 7pm"))
    assert branding.active_footer() == "Live Tues 7pm"

def test_footer_over_120_chars_is_refused():
    errs = branding.problems(branding.Brand(footer="a " * 61))
    assert "The footer is too long: it must fit on 2 lines." in errs

def test_wide_footer_under_120_chars_that_needs_3_lines_is_refused():
    assert len("W" * 100) <= 120 and not branding.footer_fits("W" * 100)

@pytest.mark.parametrize("word", ["To:", "From:", "Packing Slip", "Pick List"])
def test_footer_refuses_page_marker_words(word):
    assert any("footer can't contain" in e for e in
               branding.problems(branding.Brand(footer=f"see {word} here")))

def test_hand_edited_bad_footer_is_dropped_with_a_note(): ...
    # write settings.json with footer "x" * 300 → load().footer == "" and a note mentions "footer"

def test_footer_with_emoji_and_newlines_uses_renderable_text():   # Review Focus 1
    assert ws.footer_lines("Thanks!\n🎉 Live Tues") == ["Thanks! Live Tues"]
    branding.save(branding.Brand(footer_enabled=True, footer="🎉\n"))
    assert branding.active_footer() is None

def test_a_wrong_typed_footer_enabled_is_not_coerced(): ...
    # footer_enabled: "yes" → stays False, note added (mirror test_a_string_brand_enabled_is_not_coerced)
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_branding_footer.py -v` — Expected: FAIL.

- [ ] **Step 3: Implement.** Extend `load()`'s key table and the drop-with-note checks; `save()` writes the two keys; `problems()` adds exactly `"The footer is too long: it must fit on 2 lines."` and `"The footer can't contain \"To:\", \"From:\", \"Packing Slip\" or \"Pick List\" — the app uses those words to find each part of the page."`

- [ ] **Step 4: Run** `python3 -m pytest tests/test_branding_footer.py tests/test_branding.py -v` — Expected: PASS.

- [ ] **Step 5: Commit** — `feat: footer message settings with its own switch`

---

### Task 3: Draw the footer

**Files:**
- Modify: `src/whatnot_slips.py` (`slip_ps`, `preview_png`)
- Test: `tests/test_footer_render.py`

**Interfaces:**
- Consumes: `footer_lines`, `FOOT_*` (Task 2).
- Produces: `slip_ps(ship, grouped, to, frm, brand=None, footer=None, prices=True)` (prices used in Task 5; accept it now as a no-op), `preview_png(brand, png, footer=None, prices=True)` where `brand` may now be `None` (plain header).

Layout with a footer (`footer_lines(footer)` non-empty), `u = FOOT_BAND`: the totals rule, totals, service/dims and tracking/weight move from y 66/52/34/22 to 66+u/52+u/34+u/22+u; `BOT_Y` becomes `74 + u`; a 0.5 pt rule at y 40; footer lines centred on `W/2`, 8 pt Helvetica, baselines `29 - FOOT_LEAD*k`. On every slip page. Without a footer, no op changes.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_footer_is_byte_identical():
    assert sha(golden_slip_ps(footer=None)) == GOLDEN and sha(golden_slip_ps(footer="")) == GOLDEN

def test_footer_lifts_the_bottom_block_and_prints_centred():
    ps = golden_slip_ps(footer="Follow @shop on Whatnot")
    assert f"{ws.M} {66 + ws.FOOT_BAND} moveto" in ps and "(Follow @shop on Whatnot)" in ps

def test_footer_is_on_every_page_of_a_two_page_slip():           # 26 distinct items
    pages = ws.slip_ps(SHIP, ws.group_items(MANY), TO, FRM, footer="Thanks")
    assert len(pages) >= 2 and all("(Thanks)" in p for p in pages)

def test_footer_page_extracts_with_footer_last(tmp_path):
    # ps_to_pdf (from test_brand_render) → pdf_pages: the last non-blank line of the page
    # renders to the footer, and the tracking line is above it

def test_nothing_prints_below_the_margin(tmp_path):
    # render one footer page with gs -sDEVICE=pngmono -r72; rows y >= H - M (bottom 16 px) are all white

def test_preview_shows_the_footer_without_branding(tmp_path):
    ws.preview_png(None, tmp_path / "p.png", footer="Thanks")   # does not raise; file exists
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** in `slip_ps` and `preview_png` (`brand=None` → no logo prolog, plain header; `From:` uses `"your shop"`).
- [ ] **Step 4: Run** `python3 -m pytest tests/test_footer_render.py tests/test_slip_golden.py tests/test_brand_render.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: draw the footer message at the bottom of every slip page`

---

### Task 4: Build and audit with a footer

**Files:**
- Modify: `src/whatnot_slips.py` (`build`, `verify`, new `split_footer`, new `audit_footer`)
- Test: `tests/test_footer_audit.py`

**Interfaces:**
- Consumes: `synth.make_export`, `synth.sample` (Task 1); `footer_lines` (Task 2).
- Produces: `build(src, out, quiet=False, progress=None, brand=None, footer=None, prices=True, pick_list=False)` and `verify(src, out, deep=False, progress=None, brand=None, footer=None, prices=True, pick_list=False)` — accept all three now; `prices`/`pick_list` are wired in Tasks 5–7. `split_footer(body:str, lines:list[str]) -> tuple[str, bool]`: if the last `len(lines)` non-blank lines of `body` equal `lines` under `renderable()`, return the body without them and `True`; else `(body, False)`. With `lines == []` return `(body, True)`.

In `verify`, every slip page's `slip_body()` passes through `split_footer` **before** any fact check reads it; `audit_footer` records one check per slip page (`slip page {i} footer`). The money section's per-page total search reads the stripped body too.

- [ ] **Step 1: Write the failing tests**

```python
HOSTILE = "#1 $1.00 1 Item $1.00 SKU A"

def test_footer_build_passes_audit(tmp_path): ...            # build+verify with footer="Live Tues 7pm" → fail == []

def test_hostile_footer_does_not_fail_a_good_slip(tmp_path): ...   # footer=HOSTILE → fail == []

def test_hostile_footer_does_not_pass_a_broken_slip(tmp_path, monkeypatch):
    # build with footer=HOSTILE while monkeypatching build_rows to drop the first unit's '#N'
    # → verify(footer=HOSTILE) reports a 'variant' failure

def test_missing_footer_fails(tmp_path): ...   # build footer=None, verify footer="Thanks" → 'footer' failures

def test_footer_without_branding_keeps_the_plain_header(tmp_path):   # Review Focus 5
    # build(brand=None, footer="Thanks"): pages contain "Whatnot Packing Slip" and the footer; audit passes
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `split_footer`, `audit_footer`, and pass `footer` from `build` to `slip_ps`.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_footer_audit.py tests/test_synth.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: audit the footer and keep its text out of the slip facts`

---

### Task 5: Hide prices

**Files:**
- Modify: `src/whatnot_slips.py` (`build_rows`, `slip_ps`, `verify`, `audit_units`)
- Test: `tests/test_prices_off.py`

**Interfaces:**
- Consumes: `build`/`verify` signatures (Task 4).
- Produces: `build_rows(grouped, prices=True)`; `RE_PRICE_ANY = re.compile(r'\$\s*\d')` (auditor's); `RE_OUT_COUNT = re.compile(r'^\s*(\d+) Items?\s*$', re.M)` (auditor's).

With `prices=False`: no subtotal op on product rows, no price op on sub-rows (dot leaders run to `X_SUB`), no `Subtotal` heading, totals line is `N Item(s)` only. Inline-`#` placement keeps today's arithmetic (do not use the freed space). Audit: per shipment, the count comes from `RE_OUT_COUNT` and is checked against the source (and source footer); `audit_units` skips unit-price checks; per slip page `no prices on slip page {i}` asserts `RE_PRICE_ANY` finds nothing and `Subtotal` is absent in the footer-stripped body; the money section asserts one count line per shipment and that the counts sum to the source's item total, instead of the grand-total check.

- [ ] **Step 1: Write the failing tests**

```python
def test_prices_on_is_byte_identical(): assert sha(golden_slip_ps(prices=True)) == GOLDEN

def test_prices_off_draws_no_money():
    ps = golden_slip_ps(prices=False)
    assert "$" not in ps and "(Subtotal)" not in ps and "(3 Items)" in ps

def test_prices_off_build_passes_audit(tmp_path): ...       # synth sample, prices=False → fail == []

def test_a_leaked_price_fails_the_audit(tmp_path):
    # build prices=True, verify prices=False → failures labelled 'no prices on slip page'

def test_prices_off_still_checks_counts(tmp_path, monkeypatch):
    # monkeypatch slip_ps output to say "4 Items" where source has 3 → 'item count' failure

def test_dense_two_page_slip_with_footer_and_no_prices(tmp_path):   # Review Focus 4
    # synth shipment with 26 distinct items; build footer="Thanks", prices=False
    # → that shipment has 2 slip pages, both carry the footer, no '$' on either, fail == []
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python3 -m pytest tests/test_prices_off.py tests/test_slip_golden.py tests/test_footer_audit.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: a switch to print slips without prices, audited for leaks`

---

### Task 6: Render the pick list

**Files:**
- Modify: `src/whatnot_slips.py` (new "pick list" section; `name_ops`; `build`)
- Test: `tests/test_pick_render.py`

**Interfaces:**
- Produces: `name_ops(line, x=X_NAME)` (default keeps golden); `pick_rows(items:list[dict]) -> list[dict(product, sku, qty)]` — `group_items(items)` over every shipment's items, sorted by `(sku is None, (sku or "").upper(), product.upper())`; `pick_ps(rows, src_name:str, nships:int) -> list[str]` (one PS page string per page); `RE_PICK_HEAD = re.compile(r'^\s*Pick List \d+/\d+')`; `page_kind(text) -> 'P' | 'S' | 'B'` (`'P'` when the first non-blank line matches `RE_PICK_HEAD`, else `'S'` if `Packing Slip` in it, else `'B'`). `build(..., pick_list=True)` emits `pick_ps` pages before the first slip.

Page: `Pick List n/m` bold 11 pt top-left at `H-26`, rule under it; page 1 adds `"{src_name} · {nships} shipments · {nitems} items"` (7 pt). Row: open 7 pt square (`rectstroke`) at `M`, quantity bold 10 pt right-aligned at `M+34`, name (`display_name()` form, wrapped to `W - M - (M + 40)` at 8.5 pt bold) via `name_ops(line, x=M+40)` so GIVEAWAY gets its box. Row heights 12 then 10 per wrapped line, +3 gap; new page when a row would cross y 40. Last page: rule, then `"{k} product(s) · {m} item(s)"` (singular for 1). Any `Packing Slip` in a name or `src_name` is written as `Packing-Slip`. No `#N`, no prices, no band, no footer.

- [ ] **Step 1: Write the failing tests**

```python
def test_pick_rows_sum_across_shipments_and_sort_by_sku():
    rows = ws.pick_rows([it("LOBSTER #1", sku="TB-2"), it("LOBSTER #4", sku="TB-2"),
                         it("DUCK #1", sku="AB-1"), it("BALL #2")])
    assert [(r["sku"], r["product"], r["qty"]) for r in rows] == \
           [("AB-1", "DUCK", 1), ("TB-2", "LOBSTER", 2), (None, "BALL", 1)]

def test_same_name_different_sku_are_separate_rows():          # Review Focus 2
    rows = ws.pick_rows([it("DUCK #1", sku="A"), it("DUCK #2", sku="B"), it("DUCK #3")])
    assert len(rows) == 3

def test_pick_page_has_no_prices_or_numbers_or_slip_marker(tmp_path):
    # render pick_ps for rows incl. a GIVEAWAY and src_name "My Packing Slip.pdf" → pdf_pages:
    # page_kind == 'P', no "$", no re '#\d', "Packing Slip" not in text, "1/1" present

def test_long_pick_list_paginates():
    pages = ws.pick_ps(rows_of(80), "x.pdf", 150)
    assert len(pages) > 1 and f"(Pick List {len(pages)}/{len(pages)})" in pages[-1]
    assert all("products" not in p for p in pages[:-1])

def test_build_puts_pick_pages_first(tmp_path):
    # synth sample, build(pick_list=True) → [page_kind(p) for p in pdf_pages(out)] starts 'P', then (S+B)+
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python3 -m pytest tests/test_pick_render.py tests/test_slip_golden.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: optional pick list at the front of the PDF`

---

### Task 7: Audit the pick list

**Files:**
- Modify: `src/whatnot_slips.py` (`verify` structure checks, new `audit_pick`)
- Test: `tests/test_pick_audit.py`

**Interfaces:**
- Consumes: `page_kind`, `pick_rows`, `RE_PICK_HEAD` (Task 6).
- Produces: `RE_SRC_QTY = re.compile(r'^\s*(\d+)\s{2,}.*?\s{2,}Order (\d+)\s', re.M)` (auditor's own); `RE_PICK_ROW = re.compile(r'^\s*(\d+)\s+(\S.*?)\s*$')` (auditor's own); `audit_pick(a, raw_src_pages, src_ships, pick_texts)`.

`verify` classifies pages with `page_kind`; the structure check becomes `P+(S+B)+` when `pick_list` else `(S+B)+` (so stray `P` pages fail); page count includes `P`; `kinds_detail` handles `P`. `audit_pick`:
- Quantities: per order id, qty from `RE_SRC_QTY` over the raw source slip pages (not `parse_shipment`); assert that order-id set equals the parsed one. Expected rows: product identity `(split_variant(name)[0].upper(), sku)` from the parsed items, qty summed from the **raw** per-order quantities.
- Read the pick pages with `RE_PICK_ROW` (+ continuation lines joined until the next row) into `(qty, text)`; each expected row's `renderable(display_name)` appears exactly once with its qty; no extra rows; order matches the expected sort.
- Totals line matches the row count and the sum, and the sum equals the total of the source shipments' stated `N Items` footers when every shipment has one.
- No `$` amount and no `#\d` on any pick page; `n/m` numbering is `1..m` in order.

- [ ] **Step 1: Write the failing tests**

```python
def test_pick_list_build_passes_audit(tmp_path): ...         # synth sample, pick_list=True → fail == []

def test_a_wrong_pick_quantity_fails(tmp_path, monkeypatch):
    # monkeypatch pick_rows to add 1 to the first row's qty → failure mentioning that product

def test_a_missing_pick_row_fails(tmp_path, monkeypatch): ...      # drop last row → failure
def test_an_extra_pick_row_fails(tmp_path, monkeypatch): ...       # append a fake row → failure

def test_pick_pages_when_not_asked_for_fail(tmp_path):
    # build pick_list=True, verify pick_list=False → 'slip/label grouping' failure

def test_missing_pick_list_fails(tmp_path): ...              # build False, verify True → failure

def test_150_buyer_export_with_80_products(tmp_path):        # Review Focus 3
    # synth: 150 shipments drawn from 80 products → pick pages > 1, fail == []
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python3 -m pytest tests/test_pick_audit.py tests/test_pick_render.py tests/test_synth.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: audit pick-list quantities from the raw export`

---

### Task 8: CLI, run.sh and the job runner

**Files:**
- Modify: `src/whatnot_slips.py` (`main`, `_run`), `run.sh`, `src/job.py`
- Modify tests: `tests/test_cli_brand.py`, `tests/test_job.py` (fakes take `**kw`)
- Test: `tests/test_cli_options.py`, additions to `tests/test_job.py`

**Interfaces:**
- Consumes: `branding.active_footer()` (Task 2); `build`/`verify` keywords (Task 4).
- Produces: CLI flags on both `build` and `verify`: `--no-prices`, `--pick-list`; `--no-brand` also turns the footer off. `Job(src, dest, deep=True, brand=None, footer=None, prices=True, pick_list=False)` passing all three to `build` and `verify`. `run.sh` accepts `--no-prices` and `--pick-list` (alongside `--fast`), passes them to `whatnot_slips.py build`, and lists them in its `--help` header.

- [ ] **Step 1: Write the failing tests**

```python
def test_cli_defaults(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert seen["build"]["prices"] is True and seen["build"]["pick_list"] is False
    assert seen["build"]["footer"] is None and seen["verify"] == seen["build"]

def test_cli_flags(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"),
                   "--no-prices", "--pick-list")
    assert (seen["build"]["prices"], seen["build"]["pick_list"]) == (False, True)

def test_cli_reads_the_saved_footer_and_no_brand_drops_it(monkeypatch, tmp_path): ...

def test_job_passes_footer_prices_and_pick_list(tmp_path, monkeypatch): ...
    # Job(..., footer="Hi", prices=False, pick_list=True) → fakes saw exactly those, in build and verify
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python3 -m pytest tests/test_cli_options.py tests/test_cli_brand.py tests/test_job.py -v` and `bash -n run.sh && ./run.sh --help` — Expected: PASS; help lists the two new options.
- [ ] **Step 5: Commit** — `feat: --no-prices and --pick-list on the CLI, run.sh and job runner`

---

### Task 9: GUI

**Files:**
- Modify: `src/recent.py` (generic prefs), `src/packing_gui.py`
- Test: `tests/test_gui_options.py`, additions to `tests/test_recent.py`

**Interfaces:**
- Consumes: `Brand.footer_enabled/footer`, `FOOTER_MAX`, `branding.active_footer()` (Task 2); `Job` keywords (Task 8); `preview_png(brand, png, footer, prices)` (Task 3).
- Produces: `recent.get_pref(key:str, default)`, `recent.set_pref(key:str, value) -> None` (never raises; `remember_folder` uses it); pref keys `show_prices` (default `True`), `pick_list` (default `False`). App attributes: `self.footer_on` (BooleanVar), `self.footer_box` (tk.Text), `self.footer_count` (StringVar, `"{n} / 120"`), `self.show_prices`, `self.pick_list` (BooleanVars).

Branding tab: a **Show footer on slips** switch (`Switch.TCheckbutton`) and a **Footer message** Text box (height 2) under Message, counter label beneath; input past 120 characters is cut back to 120 (typed or pasted); edits mark "Not saved yet"; footer widgets join `brand_widgets` and lock during a run; `form_brand()` carries both fields; Preview slip passes `footer` (when the switch is on) and `prices=self.show_prices.get()`, and passes `brand` only when `enabled` is on. Run tab idle card: **Show prices** and **Add pick list** checkboxes under Choose file…, initialised from prefs and saved on change. `start()` builds `Job(..., brand=branding.active(), footer=branding.active_footer(), prices=…, pick_list=…)`.

- [ ] **Step 1: Write the failing tests** (in the `app` fixture style of `tests/test_gui_branding.py`)

```python
def test_footer_counter_and_cap(app):
    app.footer_box.insert("1.0", "x" * 150); app.root.update()
    assert len(app.footer_box.get("1.0", "end-1c")) == 120 and app.footer_count.get() == "120 / 120"

def test_footer_saves_with_its_own_switch(app, errors): ...   # footer_on True + text → active_footer() == text

def test_run_switches_default_and_persist(app): ...           # True/False; set → new App reads them back

def test_start_passes_switches_to_job(app, monkeypatch, tmp_path): ...  # capture Job kwargs

def test_prefs_round_trip_and_survive_junk(tmp_path): ...     # recent.get_pref/set_pref; junk prefs.json → default
```

- [ ] **Step 2: Run** — Expected: FAIL (or SKIP without tkinter — then install `python3-tk` or report the skip).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python3 -m pytest tests/test_gui_options.py tests/test_gui_branding.py tests/test_gui_flow.py tests/test_recent.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: footer, Show prices and Add pick list in the app`

---

### Task 10: Docs and full run

**Files:**
- Modify: `README.md` (usage paragraph near the Branding one; Design notes; Options for `run.sh`), `CHANGELOG.md` (new `## v1.7.0` section on top)

- [ ] **Step 1: Write docs.** CHANGELOG v1.7.0 in the existing voice: footer message (own switch, 2 lines, 120 characters), Show prices, Add pick list. README Design notes: the footer is stripped from the slip body before fact checks (`split_footer`) and why; pick-list quantities are audited from raw `Order` lines, not the parser; page kinds `P/S/B` and why `Packing Slip` may never reach a pick page.
- [ ] **Step 2: Run the whole suite** `python3 -m pytest -v` — Expected: all pass; record which tests skipped (parity without `PACKING_TEST_PDF`, GUI without tkinter) in the report.
- [ ] **Step 3: If a real export is available**, run `PACKING_TEST_PDF=<export> python3 -m pytest tests/test_parity.py -v` — Expected: PASS against the unchanged `tests/baseline.json`.
- [ ] **Step 4: Commit** — `docs: footer, price toggle and pick list`
