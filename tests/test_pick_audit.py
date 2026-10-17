"""The pick list is audited against the raw export, not against the parser the
renderer used: a wrong pick quantity sends a box out short."""
import re

import synth
import whatnot_slips as ws
from test_brand_render import ps_to_pdf


def _src(tmp_path, ships=None):
    return (str(synth.make_export(tmp_path / "src.pdf", ships or synth.sample())),
            str(tmp_path / "out.pdf"))


def _fails(a):
    return [f"{l}: {d}" for l, d in a.fail]


def _build_with(tmp_path, monkeypatch, name, wrapper, ships=None):
    """Build with ws.<name> wrapped, then verify with the real code."""
    src, out = _src(tmp_path, ships)
    real = getattr(ws, name)
    monkeypatch.setattr(ws, name, lambda *a, **kw: wrapper(real(*a, **kw)))
    ws.build(src, out, quiet=True, pick_list=True)
    monkeypatch.undo()
    return ws.verify(src, out, pick_list=True)


def _rewrite_pick_pages(fn):
    """A pick_ps wrapper that edits the PostScript of every pick page."""
    return lambda pages: [fn(p) for p in pages]


def test_pick_list_build_passes_audit(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, pick_list=True)
    a = ws.verify(src, out, deep=True, pick_list=True)
    assert a.fail == []
    plain = ws.verify(src, out, deep=False, pick_list=True)
    assert plain.checks > 0


def test_a_wrong_pick_quantity_fails(tmp_path, monkeypatch):
    def bump(rows):
        rows = [dict(r) for r in rows]
        rows[0]["qty"] += 1
        return rows
    a = _build_with(tmp_path, monkeypatch, "pick_rows", bump)
    assert any("pick" in f and "CRUNCHY LOBSTER" in f for f in _fails(a)), _fails(a)


def test_a_missing_pick_row_fails(tmp_path, monkeypatch):
    a = _build_with(tmp_path, monkeypatch, "pick_rows", lambda rows: rows[:-1])
    assert any("pick" in f and "ROSEY BALL" in f for f in _fails(a)), _fails(a)


def test_an_extra_pick_row_fails(tmp_path, monkeypatch):
    extra = dict(product="PHANTOM WIDGET", sku=None, qty=1)
    a = _build_with(tmp_path, monkeypatch, "pick_rows", lambda rows: rows + [extra])
    assert any("pick" in f and "PHANTOM WIDGET" in f for f in _fails(a)), _fails(a)


def test_swapped_pick_quantities_fail(tmp_path, monkeypatch):
    def swap(rows):
        rows = [dict(r) for r in rows]
        assert rows[0]["qty"] != rows[2]["qty"]
        rows[0]["qty"], rows[2]["qty"] = rows[2]["qty"], rows[0]["qty"]
        return rows
    a = _build_with(tmp_path, monkeypatch, "pick_rows", swap)
    assert any("pick row" in f and "CRUNCHY LOBSTER" in f for f in _fails(a)), _fails(a)


def test_a_duplicated_pick_row_fails(tmp_path, monkeypatch):
    a = _build_with(tmp_path, monkeypatch, "pick_rows", lambda rows: rows + [rows[0]])
    assert any("pick row" in f and "CRUNCHY LOBSTER" in f for f in _fails(a)), _fails(a)


def test_a_dollar_sign_in_a_product_name_passes(tmp_path):
    ships = synth.sample() + [synth.Ship("buyer_dollar", [
        synth.Item(1, "$5 MYSTERY BOX #1", "1439000021", 5.00)],
        "9400150106151234599992")]
    src, out = _src(tmp_path, ships)
    ws.build(src, out, quiet=True, pick_list=True)
    pick = [p for p in ws.pdf_pages(out) if ws.page_kind(p) == 'P']
    assert re.search(r"^\s*1 \$5 MYSTERY BOX\s*$", pick[0], re.M), pick[0]
    a = ws.verify(src, out, pick_list=True)
    assert a.fail == [], _fails(a)


def test_pick_rows_out_of_order_fail(tmp_path, monkeypatch):
    a = _build_with(tmp_path, monkeypatch, "pick_rows", lambda rows: rows[::-1])
    assert any("pick row order" in f for f in _fails(a)), _fails(a)


def test_a_leaked_variant_number_fails(tmp_path, monkeypatch):
    def leak(rows):
        rows = [dict(r) for r in rows]
        rows[-1]["product"] += " #3"
        return rows
    a = _build_with(tmp_path, monkeypatch, "pick_rows", leak)
    assert any("pick no variant numbers" in f for f in _fails(a)), _fails(a)


def test_a_price_on_the_pick_list_fails(tmp_path, monkeypatch):
    a = _build_with(tmp_path, monkeypatch, "pick_ps", _rewrite_pick_pages(
        lambda p: p.replace("showpage", "7 HV ($3.00) 200 20 L\nshowpage")))
    assert any("pick no prices" in f for f in _fails(a)), _fails(a)


def test_a_wrong_totals_line_fails(tmp_path, monkeypatch):
    a = _build_with(tmp_path, monkeypatch, "pick_ps", _rewrite_pick_pages(
        lambda p: p.replace("(6 products \\267 11 items)", "(6 products \\267 12 items)")))
    assert any("pick total items" in f for f in _fails(a)), _fails(a)


def test_wrong_page_numbering_fails(tmp_path, monkeypatch):
    a = _build_with(tmp_path, monkeypatch, "pick_ps", _rewrite_pick_pages(
        lambda p: p.replace("(Pick List 1/1)", "(Pick List 2/2)")))
    assert any("pick page numbering" in f for f in _fails(a)), _fails(a)


def test_pick_pages_when_not_asked_for_fail(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, pick_list=True)
    a = ws.verify(src, out, pick_list=False)
    assert any("slip/label grouping" in f for f in _fails(a)), _fails(a)


def test_missing_pick_list_fails(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, pick_list=False)
    a = ws.verify(src, out, pick_list=True)
    assert any("slip/label grouping" in f for f in _fails(a)), _fails(a)
    assert any(f.startswith("pick") for f in _fails(a)), _fails(a)


def test_default_audit_records_no_pick_checks(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True)
    a = ws.verify(src, out)
    assert a.fail == []
    ws.build(src, out, quiet=True, pick_list=True)
    b = ws.verify(src, out, pick_list=True)
    assert b.fail == [] and b.checks > a.checks


def test_quantities_come_from_the_raw_export_not_the_parser(tmp_path, monkeypatch):
    """A parser that misreads a quantity feeds the renderer and the slip
    checks alike; the pick audit reads the raw source lines itself."""
    real = ws.parse_shipment

    def misread(pages):
        ship, items = real(pages)
        if items:
            items[0] = dict(items[0], qty=items[0]["qty"] + 1)
        return ship, items
    src, out = _src(tmp_path)
    monkeypatch.setattr(ws, "parse_shipment", misread)
    ws.build(src, out, quiet=True, pick_list=True)
    a = ws.verify(src, out, pick_list=True)
    assert any(f.startswith("pick") and "CRUNCHY LOBSTER" in f for f in _fails(a)), _fails(a)


def _audit_one(items, rows, tmp_path):
    """audit_pick on a one-shipment export, fed directly: the source lines
    are written out as pdftotext -layout would read them."""
    raw = "Packing Slip\n" + "".join(
        f"{it['qty']}         {it['name']}   Order {it['order']}    $1.00\n" for it in items)
    pick = ws.pdf_pages(str(ps_to_pdf(ws.pick_ps(rows, "x.pdf", 1), tmp_path)))
    a = ws.Audit()
    n = sum(it["qty"] for it in items)
    ws.audit_pick(a, [raw], [([1], dict(stated=(n, "1.00")), items)], pick)
    return a, pick


CARD = [dict(qty=1, name="CARD #25 HOLO #3", order="1", price=1.0, sku=None),
        dict(qty=2, name="CARD #25 HOLO #4", order="2", price=1.0, sku=None)]


def test_a_hash_inside_a_product_name_prints_and_passes(tmp_path):
    """Ruling: a '#' that is part of the product prints; only the variant
    number is kept off the pick list."""
    a, pick = _audit_one(CARD, ws.pick_rows(CARD), tmp_path)
    assert re.search(r"^\s*3 CARD #25 HOLO\s*$", pick[0], re.M), pick[0]
    assert a.fail == [] and a.checks > 0


def test_a_variant_number_after_such_a_name_still_fails(tmp_path):
    rows = [dict(r, product=r["product"] + " #3") for r in ws.pick_rows(CARD)]
    a, _ = _audit_one(CARD, rows, tmp_path)
    assert any("pick no variant numbers" in f for f in _fails(a)), _fails(a)


def test_a_hash_in_a_sku_prints_and_passes(tmp_path):
    ships = synth.sample() + [synth.Ship("buyer_card", [
        synth.Item(1, "HOLO CARD #3", "1439000001", 4.00, "HOLO#25"),
        synth.Item(2, "HOLO CARD #4", "1439000002", 8.00, "HOLO#25")],
        "9400150106151234599990")]
    src, out = _src(tmp_path, ships)
    ws.build(src, out, quiet=True, pick_list=True)
    pick = [p for p in ws.pdf_pages(out) if ws.page_kind(p) == 'P']
    assert re.search(r"^\s*3 \[HOLO#25\] HOLO CARD\s*$", pick[0], re.M), pick[0]
    assert ws.verify(src, out, pick_list=True).fail == []


def test_a_wrapped_name_whose_second_line_starts_with_a_number_passes(tmp_path):
    name, sku = "MMMMMMM WWWWWWWW 2024 BOX", "WWWWW-WWWW"
    ls = ws.wrap(ws.display_name(dict(product=name, sku=sku)), ws.PICK_W, 8.5, True)
    assert len(ls) > 1 and ls[1][0].isdigit(), ls
    ships = synth.sample() + [synth.Ship("buyer_box", [
        synth.Item(1, name + " #1", "1439000011", 40.00, sku)],
        "9400150106151234599991")]
    src, out = _src(tmp_path, ships)
    ws.build(src, out, quiet=True, pick_list=True)
    a = ws.verify(src, out, pick_list=True)
    assert a.fail == [], _fails(a)


def test_a_file_name_with_money_or_a_number_does_not_fail(tmp_path):
    src = str(synth.make_export(tmp_path / "Show #12 $5 off.pdf", synth.sample()))
    out = str(tmp_path / "out.pdf")
    ws.build(src, out, quiet=True, pick_list=True)
    assert ws.verify(src, out, pick_list=True).fail == []


def test_defuse_catches_whitespace_variants():
    assert ws._defuse("A Packing  Slip\nPacking\tSlip") == "A Packing-Slip\nPacking-Slip"


def _big_export(n_ships=150, n_products=80):
    ships, order = [], 1450000000
    for k in range(n_ships):
        items = []
        for j in range(1 + k % 3):
            p = (k * 7 + j * 13) % n_products
            order += 1
            sku = f"SK-{p:03d}" if p % 2 else None
            items.append(synth.Item(1 + (k + j) % 2, f"PRODUCT NUMBER {p} #{k + 1}",
                                    str(order), 1.0 + p % 5, sku))
        ships.append(synth.Ship(f"buyer_{k}", items, f"94001501061{k:011d}"))
    used = {(k * 7 + j * 13) % n_products for k in range(n_ships) for j in range(1 + k % 3)}
    assert len(used) == n_products
    return ships


def test_150_buyer_export_with_80_products(tmp_path):
    src, out = _src(tmp_path, _big_export())
    ws.build(src, out, quiet=True, pick_list=True)
    kinds = "".join(ws.page_kind(p) for p in ws.pdf_pages(out))
    assert kinds.count("P") > 1 and kinds.count("B") == 150
    a = ws.verify(src, out, pick_list=True)
    assert a.fail == [], _fails(a)[:10]
