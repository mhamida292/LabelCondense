import whatnot_slips as ws

# Header text as pdftotext -layout prints it (Sept 16 export, shipment 32).
WRAPPED_NEW = """      Whatnot Packing Slip                                       1/1

To: the_above_average_savage    From: directdealzz
    NEW

Alex DiFilippo                  COCONUT OIL & CRUNCHY
2871 SE 151st Ave. Morriston,   SQUISHY MADNESS!!! GIVVY
FL. 32668-2848. US              FRENZY!!
                                16 September, 2026

QTY Name & Description          Attributes                 Subtotal
"""

def test_address_survives_new_badge_wrapped_onto_its_own_line():
    to, frm = ws.address(WRAPPED_NEW)
    assert to == ["To: the_above_average_savage", "NEW", "Alex DiFilippo",
                  "2871 SE 151st Ave. Morriston,", "FL. 32668-2848. US"]
    assert frm == ["From: directdealzz", "COCONUT OIL & CRUNCHY",
                   "SQUISHY MADNESS!!! GIVVY", "FRENZY!!", "16 September, 2026"]

def test_header_region_stops_at_qty():
    region = ws.header_region(WRAPPED_NEW)
    assert region[0].startswith("To:")
    assert not any(ln.lstrip().startswith("QTY") for ln in region)
    assert "Alex DiFilippo" in "\n".join(region)
