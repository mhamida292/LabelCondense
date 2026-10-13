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
