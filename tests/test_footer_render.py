import hashlib, subprocess
import whatnot_slips as ws
from test_slip_golden import SHIP, TO, FRM, golden_slip_ps, GOLDEN
from test_brand_render import ps_to_pdf

MANY = [dict(qty=1, name=f"PRODUCT NUMBER {i} WIDGET", order=str(i), price=1.0 + i)
        for i in range(26)]

def sha(ps): return hashlib.sha256(ps.encode()).hexdigest()

def test_no_footer_is_byte_identical():
    assert sha(golden_slip_ps(footer=None)) == GOLDEN and sha(golden_slip_ps(footer="")) == GOLDEN

def test_footer_lifts_the_bottom_block_and_prints_centred():
    ps = golden_slip_ps(footer="Follow @shop on Whatnot")
    assert f"{ws.M} {66 + ws.FOOT_BAND} moveto" in ps and "(Follow @shop on Whatnot)" in ps

def test_footer_is_on_every_page_of_a_two_page_slip():
    pages = ws.slip_ps(SHIP, ws.group_items(MANY), TO, FRM, footer="Thanks")
    assert len(pages) >= 2 and all("(Thanks)" in p for p in pages)

def test_footer_page_extracts_with_footer_last(tmp_path):
    pdf = ps_to_pdf(ws.slip_ps(SHIP, ws.group_items(MANY), TO, FRM, footer="Thanks"), tmp_path)
    txt = subprocess.run(["pdftotext", "-layout", "-f", "1", "-l", "1", str(pdf), "-"],
                         capture_output=True, text=True).stdout
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    assert lines[-1] == "Thanks" and "#9300120762602517212464" in lines[-2]

def test_nothing_prints_below_the_margin(tmp_path):
    pdf = ps_to_pdf(ws.slip_ps(SHIP, ws.group_items(MANY), TO, FRM,
                    footer="Thanks for shopping with us, follow along on Whatnot for more"), tmp_path)
    png = tmp_path / "p.png"
    subprocess.run(["gs", "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pngmono", "-r72",
                    "-dFirstPage=1", "-dLastPage=1", f"-sOutputFile={png}", str(pdf)], check=True)
    from PIL import Image
    im = Image.open(png).convert("L")
    w, h = im.size
    assert im.crop((0, h - 16, w, h)).getextrema()[0] == 255
    assert im.crop((0, h - 40, w, h - 16)).getextrema()[0] < 128   # footer is there

def test_preview_shows_the_footer_without_branding(tmp_path):
    ws.preview_png(None, tmp_path / "p.png", footer="Thanks")
    assert (tmp_path / "p.png").exists()
