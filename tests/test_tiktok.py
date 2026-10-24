import pathlib

import pytest

import branding
import job as J
import platforms
import synth
import tiktok as tt
import tiktok_synth as ts
import whatnot_slips as ws


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    """One synthetic export shared by the module; order 1 runs to two pages."""
    orders = ts.sample()
    orders[1].split_after = 2
    return str(ts.make_export(tmp_path_factory.mktemp("tt") / "tiktok.pdf", orders))


def _out(tmp_path):
    return str(tmp_path / "out.pdf")


# ---------------------------------------------------------------- detection
def test_detects_tiktok_and_whatnot(src, tmp_path):
    assert platforms.detect(src) == "tiktok"
    wn = synth.make_export(tmp_path / "wn.pdf", synth.sample())
    assert platforms.detect(str(wn)) == "whatnot"


def test_refuses_a_file_that_is_neither_or_both():
    with pytest.raises(platforms.UnknownExport):
        platforms.detect_pages(["hello", "a random invoice"])
    tik = "Packing Slip\nOrder ID: 1\nProduct Name   SKU   Seller SKU   Qty\n"
    wn = "Packing Slip\nTo: a        From: b\nQTY  Name\n"
    assert platforms.detect_pages([tik]) == "tiktok"
    assert platforms.detect_pages([wn]) == "whatnot"
    with pytest.raises(platforms.UnknownExport):
        platforms.detect_pages([tik, wn])


# ------------------------------------------------------------------ parsing
def test_load_reads_every_order(src):
    _, orders = tt.load(src)
    assert [p for p, _, _ in orders] == [[2], [4, 5], [7], [9]]
    assert [info["label"] for _, info, _ in orders] == [1, 3, 6, 8]
    info = orders[0][1]
    assert (info["order"], info["buyer"], info["nick"], info["stated"]) == \
        ("577630693427024173", "23taylor32", "Taylor23", 1)
    assert info["track"] == "9200190390868227255592"
    assert info["shipby"] == "10/23/2026 11:59 PM"
    assert orders[3][1]["show"] == "Bladesplus Live 10-20 1"


def test_lots_prices_and_names(src):
    _, orders = tt.load(src)
    lots = [[(it["lot"], it["qty"], it["price"]) for it in items] for _, _, items in orders]
    assert lots[1] == [("50", 1, 9.0), ("56", 1, 7.0), ("77", 1, 1.0), ("103", 1, 10.0)]
    third = orders[2][2]
    assert orders[2][1]["nick"] == ""
    # a numeric lot is a #N; anything else is a SKU; qty x unit price
    assert third[0]["name"] == f"{ts.WC} #31" and third[0]["sku"] is None
    assert (third[1]["name"], third[1]["sku"], third[1]["price"]) == \
        ("Mystery Blade Bundle", "MB-7", 50.0)
    assert third[2]["name"] == "Damascus Hunting Knife With Leather Sheath #88"


def test_a_slip_without_a_label_is_refused(tmp_path, monkeypatch):
    pages = ["Packing Slip\nOrder ID: 1\nProduct Name  SKU  Seller SKU  Qty\nQty Total: 0\n"]
    monkeypatch.setattr(ws, "pdf_pages", lambda p: pages)
    with pytest.raises(ValueError, match="no label before it"):
        tt.load("x.pdf")
    monkeypatch.setattr(ws, "pdf_pages", lambda p: ["", pages[0], "stray"])
    with pytest.raises(ValueError, match="belong to no order"):
        tt.load("x.pdf")


# -------------------------------------------------------------- build/verify
@pytest.mark.parametrize("kw", [
    dict(),
    dict(condense=False),
    dict(prices=False, pick_list=True),
    dict(pick_list=True, footer="Thanks! Order ID: 5 #9 $5"),
])
def test_build_passes_its_audit(src, tmp_path, kw):
    out = _out(tmp_path)
    n, nsl, nlb = tt.build(src, out, quiet=True, **kw)
    assert (n, nlb) == (4, 4)
    a = tt.verify(src, out, deep=True, **kw)
    assert a.fail == [] and a.checks > 100


def test_branded_build_passes_its_audit(src, tmp_path):
    b = branding.Brand(enabled=True, shop_name="Blades Plus", message="Thanks for the support!")
    out = _out(tmp_path)
    tt.build(src, out, quiet=True, brand=b, pick_list=True)
    assert tt.verify(src, out, deep=True, brand=b, pick_list=True).fail == []


def test_condense_groups_repeats_and_off_keeps_one_row_each(src, tmp_path):
    out = _out(tmp_path)
    tt.build(src, out, quiet=True)
    slip = ws.pdf_pages(out)[2]                   # order 1's slip
    assert slip.count(ts.WC) == 1 and "#103" in slip
    tt.build(src, out, quiet=True, condense=False)
    assert ws.pdf_pages(out)[2].count(ts.WC) == 4


def test_slip_is_header_b(src, tmp_path):
    out = _out(tmp_path)
    tt.build(src, out, quiet=True)
    first = ws.pdf_pages(out)[0]
    lines = [ln.strip() for ln in first.split("\n") if ln.strip()]
    assert lines[0].startswith("TikTok Packing Slip")
    for label in ("Order ID:", "Created Time:", "In transit by:", "Tracking number:", "Show name:"):
        assert any(ln.startswith(label) for ln in lines[1:6])
    assert lines[-2:] == ["Buyer ID: 23taylor32", "Buyer Nickname: Taylor23"]


def test_label_is_cut_out_and_scaled_evenly(src, tmp_path):
    im = tt.label_bitmap(src, 1, str(tmp_path))
    assert im.size == (1200, 1800)
    # the synthetic label's border is its outermost ink: after the cut it
    # touches every edge, so nothing was left as margin or squashed off
    box = im.point(lambda p: 255 - p).getbbox()
    assert box[0] <= 4 and box[1] <= 4 and box[2] >= 1196 and box[3] >= 1796


# ------------------------------------------------------- the audit has teeth
def _tampered(src, tmp_path, monkeypatch, fn, old, new, **kw):
    real = getattr(tt, fn)
    def lying(*a, **k):
        r = real(*a, **k)
        return [p.replace(old, new) for p in r]
    monkeypatch.setattr(tt, fn, lying)
    out = _out(tmp_path)
    tt.build(src, out, quiet=True, **kw)
    monkeypatch.undo()
    return tt.verify(src, out, **kw)


@pytest.mark.parametrize("old,new,label", [
    ("(#56)", "(#57)", "variant"),
    ("Buyer ID: arielmarti97", "Buyer ID: someone", "buyer id"),
    ("($27.00)", "($28.00)", "total"),
    ("(10/23/2026 11:59 PM)", "(10/24/2026 11:59 PM)", "shipby"),
])
def test_a_wrong_slip_fact_fails(src, tmp_path, monkeypatch, old, new, label):
    a = _tampered(src, tmp_path, monkeypatch, "slip_ps", old, new)
    assert any(label in f[0] for f in a.fail), a.fail


def test_a_lot_given_to_the_wrong_buyer_on_the_pick_list_fails(src, tmp_path, monkeypatch):
    a = _tampered(src, tmp_path, monkeypatch, "pick_ps", "(Taylor23)", "(Ari)", pick_list=True)
    assert any(f[0] == "pick rows" for f in a.fail), a.fail


def test_swapped_labels_fail_the_pixel_check(src, tmp_path, monkeypatch):
    real = tt.label_bitmap
    monkeypatch.setattr(tt, "label_bitmap",
                        lambda pdf, n, td: real(pdf, {1: 3, 3: 1}.get(n, n), td))
    out = _out(tmp_path)
    tt.build(src, out, quiet=True)
    monkeypatch.undo()
    a = tt.verify(src, out, deep=True)
    assert {f[0] for f in a.fail} == {"order 0 label pixels identical",
                                      "order 1 label pixels identical"}


def test_a_parser_that_drops_a_row_is_caught(src, tmp_path, monkeypatch):
    real = tt.parse_order
    def lossy(pages):
        info, items = real(pages)
        return info, items[:-1] if len(items) > 1 else items
    monkeypatch.setattr(tt, "parse_order", lossy)
    out = _out(tmp_path)
    tt.build(src, out, quiet=True)
    a = tt.verify(src, out)
    assert any("rows parsed" in f[0] for f in a.fail)


# ---------------------------------------------------------------- pick list
def test_pick_list_groups_lots_by_show(src):
    _, orders = tt.load(src)
    groups = tt.pick_groups(orders)
    assert [show for show, _ in groups] == ["Bladesplus Live 10-21 1", "Bladesplus Live 10-20 1"]
    first = [(lot, who) for lot, _, who in groups[0][1]]
    assert first[:3] == [("21", "Taylor23"), ("31", "_solxce_"), ("50", "Ari")]
    assert first[-1] == ("MB-7", "_solxce_")      # a SKU sorts after the numbers
    # the same lot number in another show stays in its own section
    assert [lot for lot, _, _ in groups[1][1]] == ["21", "69"]


def test_pick_who_falls_back_to_buyer_id_and_fits():
    assert tt.pick_who(dict(nick="", buyer="_solxce_")) == "_solxce_"
    long = tt.pick_who(dict(nick="A Very Long Nickname Indeed Yes", buyer="x"))
    assert long.endswith("...") and ws.sw(long, 8) <= tt.PICK_WHO_W


# ------------------------------------------------------- Whatnot, condense off
def test_whatnot_condense_off_passes_its_audit(tmp_path):
    src = str(synth.make_export(tmp_path / "wn.pdf", synth.sample()))
    out = _out(tmp_path)
    ws.build(src, out, quiet=True, condense=False)
    assert ws.verify(src, out, condense=False).fail == []
    # buyer_two's three ROSEY BALLs are three rows, not one
    assert ws.pdf_pages(out)[2].count("ROSEY BALL") == 3


# ----------------------------------------------------------------- the job
def test_job_detects_tiktok_and_says_so(src, tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    lines = []
    res = J.Job(src, tmp_path / "out.pdf", deep=False).run(
        lambda e: lines.append(e["line"]) if e["kind"] == "log" else None)
    assert res.ok and res.platform == "TikTok Shop"
    assert "detected: TikTok Shop" in lines


def test_job_refuses_an_unknown_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    ps = tmp_path / "x.ps"
    ps.write_text("%!PS\n/Courier findfont 12 scalefont setfont 72 700 moveto (An invoice) show showpage\n")
    pdf = tmp_path / "x.pdf"
    ws._spawn([ws._bin("gs"), "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
               f"-sOutputFile={pdf}", str(ps)])
    res = J.Job(pdf, tmp_path / "out.pdf").run(lambda e: None)
    assert not res.ok and res.message == platforms.UNKNOWN
    assert not (tmp_path / "out.pdf").exists()


# ------------------------------------------------- a real export, if given
def test_real_tiktok_export(tiktok_pdf, tmp_path):
    out = _out(tmp_path)
    tt.build(str(tiktok_pdf), out, quiet=True, pick_list=True)
    a = tt.verify(str(tiktok_pdf), out, deep=True, pick_list=True)
    assert a.fail == []
