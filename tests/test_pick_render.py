import re
import tempfile

import whatnot_slips as ws
import synth
from test_brand_render import ps_to_pdf

def it(name, sku=None, qty=1):
    return dict(qty=qty, name=name, order="1", price=1.0, sku=sku)

def rows_of(n):
    return [dict(product=f"PRODUCT {i}", sku=f"S{i:03d}", qty=1 + i % 3) for i in range(n)]

def test_pick_rows_sum_across_shipments_and_sort_by_sku():
    rows = ws.pick_rows([it("LOBSTER #1", sku="TB-2"), it("LOBSTER #4", sku="TB-2"),
                         it("DUCK #1", sku="AB-1"), it("BALL #2")])
    assert [(r["sku"], r["product"], r["qty"]) for r in rows] == \
           [("AB-1", "DUCK", 1), ("TB-2", "LOBSTER", 2), (None, "BALL", 1)]

def test_same_name_different_sku_are_separate_rows():
    rows = ws.pick_rows([it("DUCK #1", sku="A"), it("DUCK #2", sku="B"), it("DUCK #3")])
    assert len(rows) == 3

def test_pick_page_has_no_prices_or_numbers_or_slip_marker():
    rows = ws.pick_rows([it("GIVEAWAY SKULL #7"), it("DUCK Packing Slip #1", sku="AB-1"),
                         it("BALL #2", qty=3)])
    with tempfile.TemporaryDirectory() as td:
        pages = ws.pdf_pages(str(ps_to_pdf(ws.pick_ps(rows, "My Packing Slip.pdf", 2), td)))
    assert len(pages) == 1
    t = pages[0]
    assert ws.page_kind(t) == 'P'
    assert "$" not in t and not re.search(r'#\d', t)
    assert "Packing Slip" not in t and "Packing-Slip" in t
    assert "1/1" in t and "·" in t and "3 products · 5 items" in t

def test_long_pick_list_paginates():
    pages = ws.pick_ps(rows_of(80), "x.pdf", 150)
    assert len(pages) > 1 and f"(Pick List {len(pages)}/{len(pages)})" in pages[-1]
    assert all("products" not in p for p in pages[:-1])

def test_page_kind():
    assert ws.page_kind("\n  Pick List 1/2\nfoo Packing Slip") == 'P'
    assert ws.page_kind("Whatnot Packing Slip\n1/1") == 'S'
    assert ws.page_kind("Packing Slip 1/1") == 'S'
    assert ws.page_kind("\n\nSOME LABEL\nPick List 1/1") == 'B'

def test_build_puts_pick_pages_first(tmp_path):
    src = synth.make_export(tmp_path / "src.pdf", synth.sample())
    out = tmp_path / "out.pdf"
    ws.build(str(src), str(out), quiet=True, pick_list=True)
    kinds = "".join(ws.page_kind(p) for p in ws.pdf_pages(str(out)))
    assert re.fullmatch(r'P+(SB)+|P+(S+B)+', kinds), kinds
