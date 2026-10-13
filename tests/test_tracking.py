import whatnot_slips as ws

# Footers as pdftotext -layout prints them. Domestic USPS issues a 20- or
# 22-digit IMpb barcode; an international shipment carries a 13-character UPU
# S10 number instead (2 letters, 9 digits, 2-letter country code).
DOMESTIC = """      Whatnot Packing Slip                                       1/1

QTY Name & Description          Attributes                 Subtotal
1     CHUBBY KITTY #1           Order 1370668757             $4.00

1 Item                                                        $4.00
USPS Ground Advantage™                                12 x 12 x 12 in
#9300120762602517212464                                       7.0 oz
"""

INTERNATIONAL = """      Whatnot Packing Slip                                       1/1

QTY Name & Description          Attributes                 Subtotal
9     CHUBBY KITTY #10          Order 1370668758            $33.00

9 Items                                                      $33.00
USPS First-Class Package International Se...          12 x 12 x 12 in
#LZ123456789US                                               63.0 oz
"""

def test_domestic_impb_tracking_and_weight_are_parsed():
    ship, _ = ws.parse_shipment([DOMESTIC])
    assert ship["track"] == "9300120762602517212464"
    assert ship["weight"] == "7.0 oz"

def test_international_s10_tracking_and_weight_are_parsed():
    """A 13-character international number is not a 20-digit IMpb barcode.

    Sept 20 export, shipment 77. The old 20-character floor rejected it, so
    the slip rendered an empty '#' with no weight and the audit crashed with
    KeyError: 'track'.
    """
    ship, _ = ws.parse_shipment([INTERNATIONAL])
    assert ship["track"] == "LZ123456789US"
    assert ship["weight"] == "63.0 oz"

def test_item_number_is_not_mistaken_for_a_tracking_number():
    ship, _ = ws.parse_shipment(["      ■ ■ #10\n"])
    assert "track" not in ship

# --- a shipping fact that never parsed must fail, not pass vacuously --------
# `'' in anything` is True, so auditing a missing fact with a plain `in` test
# reports OK. Sept 20 only stopped because 'tracking' happened to index the
# dict strictly and crashed; weight, dims and service would all have sailed
# through, and the slip would have printed with a bare '#'.

def test_a_missing_fact_fails_instead_of_passing_vacuously():
    a = ws.Audit()
    assert not a.present("", "a slip with no tracking number on it",
                         "shipment 77 tracking")
    assert a.fail == [("shipment 77 tracking", "missing from the source slip")]

def test_a_fact_absent_from_the_slip_fails():
    a = ws.Audit()
    assert not a.present("LZ123456789US", "a slip without it", "s tracking")
    assert a.fail == [("s tracking", "'LZ123456789US'")]

def test_a_fact_that_reached_the_slip_passes():
    a = ws.Audit()
    assert a.present("LZ123456789US", "#LZ123456789US    63.0 oz", "s tracking")
    assert a.fail == []
    assert a.checks == 1
