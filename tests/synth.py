"""A fake Whatnot "Combined Labels + Packing Slips" export, so the audit can
be tested end to end without customer data. Each source line is one Courier
7 pt string at a fixed x per column, which makes pdftotext -layout reproduce
the spacing the RE_* parsers expect (shapes lifted from tests/test_sku.py)."""
import pathlib
import subprocess
from dataclasses import dataclass, field

import whatnot_slips as ws

PW, PH = 612, 792                       # source pages are Letter
X_QTY, X_NAME, X_ATTR, X_SUB, X_FROM = 40, 70, 250, 340, 300

@dataclass
class Item:
    qty: int
    name: str
    order: str
    price: float
    sku: str | None = None

@dataclass
class Ship:
    to: str
    items: list
    track: str
    weight: str = "7.0 oz"
    svc: str = "USPS Ground Advantage"
    dims: str = "12 x 12 x 12 in"

def _ps(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def _slip(ship):
    ops, y = [], PH - 50
    def put(x, text):
        ops.append(f"{x} {y} moveto ({_ps(text)}) show")
    def nl(n=1):
        nonlocal y; y -= 10 * n
    put(X_QTY, "Packing Slip"); nl(2)
    put(X_QTY, f"To: {ship.to}"); put(X_FROM, "From: Example Seller"); nl()
    put(X_QTY, "Jane Buyer"); put(X_FROM, "Example Seller LLC"); nl()
    put(X_QTY, "12 Main St"); put(X_FROM, "99 Warehouse Way"); nl()
    put(X_QTY, "Springfield, IL 62701"); put(X_FROM, "Reno, NV 89501"); nl(2)
    put(X_QTY, "QTY"); put(X_NAME, "Name & Description")
    put(X_ATTR, "Attributes"); put(X_SUB, "Subtotal"); nl()
    for it in ship.items:
        put(X_QTY, str(it.qty)); put(X_NAME, it.name)
        put(X_ATTR, f"Order {it.order}"); put(X_SUB, f"${it.price:,.2f}"); nl()
        if it.sku:
            put(X_ATTR, f"SKU {it.sku}"); nl()
        nl()                                      # blank line ends the block
    n = sum(i.qty for i in ship.items); t = sum(i.price for i in ship.items)
    put(X_QTY, f"{n} Items"); put(X_SUB, f"${t:,.2f}"); nl(2)
    put(X_QTY, ship.svc); put(X_SUB, ship.dims); nl()
    put(X_QTY, f"#{ship.track}"); put(X_SUB, ship.weight)
    return "\n".join(ops) + "\nshowpage\n"

def _label():
    bars = "".join(f"{x} 90 {w} 560 rectfill\n" for x, w in
                   [(80, 6), (96, 3), (110, 9), (130, 4), (150, 12), (180, 5)])
    return ("2 setlinewidth 0 setgray 60 60 400 640 rectstroke\n"
            f"{bars}showpage\n")

def make_export(path, ships):
    path = pathlib.Path(path)
    ps = [f"%!PS-Adobe-3.0\n<< /PageSize [{PW} {PH}] >> setpagedevice\n"
          "/Courier findfont 7 scalefont setfont\n"]
    for s in ships:
        ps += [_slip(s), _label()]
    src = path.with_suffix(".ps")
    src.write_text("".join(ps))
    ws._spawn([ws._bin("gs"), "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
               "-dFIXEDMEDIA", f"-dDEVICEWIDTHPOINTS={PW}",
               f"-dDEVICEHEIGHTPOINTS={PH}", f"-sOutputFile={path}", str(src)])
    return path

def sample(n_ships=3):
    """Varied: a product repeated as several #N, a SKU'd item, a GIVEAWAY and
    an item with no #."""
    base = [
        Ship("buyer_one", [Item(1, "CRUNCHY LOBSTER #1", "1437763335", 3.00, "TB200-477"),
                           Item(1, "CRUNCHY LOBSTER #2", "1437763336", 3.00, "TB200-477"),
                           Item(1, "ROSEY BALL #4", "1437826675", 2.00),
                           Item(1, "MYSTERY GRAB BAG", "1437900001", 5.00)],
             "9400150106151234567890"),
        Ship("buyer_two", [Item(1, "ROSEY BALL #1", "1438062700", 2.00),
                           Item(1, "ROSEY BALL #2", "1438062701", 2.00),
                           Item(1, "ROSEY BALL #3", "1438062702", 2.00),
                           Item(1, "GIVEAWAY CRUNCHY SKULL #7", "1438062703", 0.00)],
             "9400150106151234567907", "4.2 oz"),
        Ship("buyer_three", [Item(2, "JUMBO DUCK #1", "1438100001", 16.00, "ZW-112B"),
                             Item(1, "CRUNCHY SKULL #3", "1438100002", 3.00)],
             "9400150106151234567914", "9.5 oz"),
    ]
    out = list(base)
    while len(out) < n_ships:
        k = len(out) + 1
        out.append(Ship(f"buyer_{k}", [Item(1, f"ROSEY BALL #{k}", str(1438200000 + k), 2.00)],
                        f"94001501061512345679{k % 100:02d}"))
    return out[:n_ships]
