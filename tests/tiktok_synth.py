"""A fake TikTok Shop label + packing slip export, so the TikTok path can be
tested end to end without customer data. Shapes are lifted from a real
export: A6 pages, each order a label page then its slip, the slip's table
columns Product Name / SKU / Seller SKU / SKU Price (Unit) / Qty. Every source
line is one Courier 7 pt string at a fixed x per column, so pdftotext -layout
reproduces the spacing the parser reads."""
import pathlib
from dataclasses import dataclass, field

import whatnot_slips as ws

PW, PH = 298, 420                       # TikTok pages are A6
X_NAME, X_SKU, X_SELLER, X_PRICE, X_QTY = 12, 150, 176, 222, 268
X_RIGHT = 150                           # the right-hand footer block

@dataclass
class Line:
    name: str
    lot: str                            # what both SKU columns print
    price: float                        # unit price
    qty: int = 1
    more: list = field(default_factory=list)   # wrapped continuation of the name
    sku: str | None = None              # the SKU column, when it differs from lot

@dataclass
class Order:
    order_id: str
    buyer: str
    nick: str
    lines: list
    track: str
    show: str = "Bladesplus Live 10-21 1"
    created: str = "10/22/2026 5:01:12 PM"
    shipby: str = "10/23/2026 11:59 PM"
    split_after: int | None = None      # spill the table onto a second page

def _ps(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def _slip(o):
    pages, ops, y = [], [], PH - 24
    def put(x, text):
        ops.append(f"{x} {y} moveto ({_ps(text)}) show")
    def nl(n=1):
        nonlocal y; y -= 9 * n
    def page_break():
        nonlocal ops, y
        pages.append("\n".join(ops) + "\nshowpage\n"); ops = []; y = PH - 24
    put(X_NAME, "Packing Slip"); nl()
    put(X_NAME, f"Order ID: {o.order_id}"); nl()
    put(X_NAME, f"Created Time: {o.created}"); nl()
    put(X_NAME, f"In transit by: {o.shipby}"); nl(2)
    put(X_NAME, f"Tracking number: {o.track}"); nl()
    put(X_NAME, f"Show name: {o.show}"); nl(2)
    put(X_PRICE, "SKU Price"); nl()
    put(X_NAME, "Product Name"); put(X_SKU, "SKU"); put(X_SELLER, "Seller SKU")
    put(X_QTY, "Qty"); nl()
    put(X_PRICE + 8, "(Unit)"); nl()
    for i, ln in enumerate(o.lines):
        if o.split_after is not None and i == o.split_after:
            page_break()
        put(X_NAME, ln.name); put(X_SKU, ln.sku or ln.lot); put(X_SELLER, ln.lot)
        put(X_PRICE, f"${ln.price:,.2f}"); put(X_QTY, str(ln.qty)); nl()
        for extra in ln.more:
            put(X_NAME, extra); nl()
    put(X_RIGHT + 50, f"Qty Total: {sum(ln.qty for ln in o.lines)}"); nl()
    put(X_RIGHT, f"Order ID: {o.order_id}"); nl(2)
    put(X_RIGHT, f"Buyer ID: {o.buyer}"); nl()
    put(X_RIGHT, f"Buyer Nickname: {o.nick}")
    page_break()
    return pages

def _label(seed):
    """A 2:3 label inset on the A6 page, like TikTok's 1000x1500 artwork.
    The bars differ per order so a swapped label shows in the pixel check."""
    bars = "".join(f"{40 + 11 * k} 120 {2 + (seed + k) % 5} 160 rectfill\n"
                   for k in range(16))
    return ("2 setlinewidth 0 setgray 9 7 270 405 rectstroke\n"
            f"40 320 moveto /Courier findfont 14 scalefont setfont (LABEL {seed}) show\n"
            "/Courier findfont 7 scalefont setfont\n"
            f"{bars}showpage\n")

def make_export(path, orders):
    path = pathlib.Path(path)
    ps = [f"%!PS-Adobe-3.0\n<< /PageSize [{PW} {PH}] >> setpagedevice\n"
          "/Courier findfont 7 scalefont setfont\n"]
    for k, o in enumerate(orders):
        ps.append(_label(k))
        ps += _slip(o)
    src = path.with_suffix(".ps")
    src.write_text("".join(ps))
    ws._spawn([ws._bin("gs"), "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
               "-dFIXEDMEDIA", f"-dDEVICEWIDTHPOINTS={PW}",
               f"-dDEVICEHEIGHTPOINTS={PH}", f"-sOutputFile={path}", str(src)])
    return path

WC = "Winners Choice Item On Screen"

def sample():
    """Varied: a buyer with many lots, a single lot, a blank nickname, a named
    product with a non-numeric seller SKU, a qty-2 line, a wrapped name, and
    a second show that reuses a lot number."""
    return [
        Order("577630693427024173", "23taylor32", "Taylor23",
              [Line(WC, "21", 10.00)], "9200190390868227255592"),
        Order("577630769308799315", "arielmarti97", "Ari",
              [Line(WC, "50", 9.00), Line(WC, "56", 7.00), Line(WC, "77", 1.00),
               Line(WC, "103", 10.00)], "9234690390868227076922"),
        Order("577630730813150086", "_solxce_", "",
              [Line(WC, "31", 12.00), Line("Mystery Blade Bundle", "MB-7", 25.00, qty=2),
               Line("Damascus Hunting Knife With", "88", 40.00, more=["Leather Sheath"])],
              "9200190390868227255769"),
        Order("577628873039844075", "runawaymexican0", "Sam",
              [Line(WC, "21", 8.00), Line(WC, "69", 6.00)],
              "9234690390868226990342", show="Bladesplus Live 10-20 1",
              shipby="10/22/2026 11:59 PM"),
    ]
