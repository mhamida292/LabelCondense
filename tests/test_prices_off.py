import hashlib

import synth
import whatnot_slips as ws
from test_slip_golden import GOLDEN, golden_slip_ps


def _src(tmp_path, ships=None):
    return (str(synth.make_export(tmp_path / "src.pdf", ships or synth.sample())),
            str(tmp_path / "out.pdf"))


def test_prices_on_is_byte_identical():
    assert hashlib.sha256(golden_slip_ps(prices=True).encode()).hexdigest() == GOLDEN


def test_prices_off_draws_no_money():
    ps = golden_slip_ps(prices=False)
    assert "$" not in ps and "(Subtotal)" not in ps and "(3 Items)" in ps


def test_prices_off_build_passes_audit(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, prices=False)
    assert ws.verify(src, out, deep=True, prices=False).fail == []


def test_a_leaked_price_fails_the_audit(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, prices=True)
    a = ws.verify(src, out, prices=False)
    assert any("no prices on slip page" in str(f) for f in a.fail)


def test_prices_off_still_checks_counts(tmp_path, monkeypatch):
    src, out = _src(tmp_path)
    real = ws.slip_ps

    def lying(*args, **kw):
        return [p.replace("(3 Items)", "(4 Items)") for p in real(*args, **kw)]

    monkeypatch.setattr(ws, "slip_ps", lying)
    ws.build(src, out, quiet=True, prices=False)
    monkeypatch.undo()
    a = ws.verify(src, out, prices=False)
    assert any("item count" in str(f) for f in a.fail)


def test_footer_with_a_dollar_amount_does_not_trip_the_price_audit(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, footer="Free ship over $50", prices=False)
    assert ws.verify(src, out, footer="Free ship over $50", prices=False).fail == []


def test_dense_two_page_slip_with_footer_and_no_prices(tmp_path):
    items = [synth.Item(1, f"WIDGET NUMBER {chr(65 + i)}", str(1500000 + i), 1.5)
             for i in range(26)]
    ships = [synth.Ship("dense_buyer", items, "9400150106151234567890")]
    src, out = _src(tmp_path, ships)
    ws.build(src, out, quiet=True, footer="Thanks", prices=False)
    slips = [p for p in ws.pdf_pages(out) if "Packing Slip" in p]
    assert len(slips) == 2
    assert all("Thanks" in p and "$" not in p for p in slips)
    assert ws.verify(src, out, footer="Thanks", prices=False).fail == []


def test_a_dollar_sign_in_a_product_name_is_not_a_price(tmp_path):
    ships = synth.sample() + [synth.Ship("buyer_dollar", [
        synth.Item(1, "$5 MYSTERY BOX #1", "1439000021", 5.00),
        synth.Item(1, "$1 START LOT #2", "1439000022", 1.00)],
        "9400150106151234599992")]
    src, out = _src(tmp_path, ships)
    ws.build(src, out, quiet=True, prices=False)
    slips = [p for p in ws.pdf_pages(out) if "Packing Slip" in p]
    assert "$5 MYSTERY BOX" in slips[-1]
    assert ws.verify(src, out, prices=False).fail == []
