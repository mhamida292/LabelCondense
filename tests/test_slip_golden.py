import hashlib
import whatnot_slips as ws

# A fixed slip, hashed before any of the SKU/branding work. With no SKUs and
# no brand, the renderer must keep producing exactly these bytes.
GOLDEN = "0f1e431b1eed5be620b7480cf54d0c6cdfa3ec200d5ff9f58ac499a558e2d782"

SHIP = dict(svc="USPS Ground Advantage", dims="12 x 12 x 12 in",
            track="9300120762602517212464", weight="7.0 oz")
ITEMS = [dict(qty=1, name="ROSEY BALL #2", order="1", price=2.0),
         dict(qty=1, name="ROSEY BALL #3", order="2", price=3.0),
         dict(qty=1, name="CRUNCHY LOBSTER #1", order="3", price=3.0)]
TO = ["To: buyer123", "Jane Buyer", "1 Main St", "Springfield, IL 62701"]
FRM = ["From: myshop", "2 Shop Rd", "Townsville, CA 90001"]

def golden_slip_ps(**kw):
    return "".join(ws.slip_ps(SHIP, ws.group_items(ITEMS), TO, FRM, **kw))

def test_unbranded_slip_without_skus_is_unchanged():
    assert hashlib.sha256(golden_slip_ps().encode()).hexdigest() == GOLDEN
