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
