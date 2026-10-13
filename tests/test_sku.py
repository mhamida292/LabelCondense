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
ROSEY = HEAD + """1    ROSEY BALL ■ #2            Order 1437826675           $2.00
     ■■ Follow • ■ Bookmark     SKU A-T-63
     • ■ Save Big • ■ Have...

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
