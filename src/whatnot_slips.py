#!/usr/bin/env python3
"""
Rebuild a Whatnot "Combined Labels + Packing Slips" PDF so that repeated
products collapse onto one line, keeping every #N variant and its price, and
re-interleave the result with the original 4x6 shipping-label images.

    ./whatnot_slips.py build IN.pdf -o OUT.pdf     # build, then self-verify
    ./whatnot_slips.py verify IN.pdf OUT.pdf       # audit an existing pair
    ./whatnot_slips.py verify IN.pdf OUT.pdf --deep   # + per-label pixel check

Requires: poppler-utils (pdftotext/pdfimages/pdftoppm), ghostscript, Pillow.
"""
import argparse, base64, glob, hashlib, os, re, subprocess, sys, tempfile, zlib
from collections import Counter, OrderedDict

from PIL import Image

# ------------------------------------------------------- external binaries
# Frozen bundles carry gs and poppler under bin/; unfrozen we use PATH as before.
_WIN_NAMES = {'gs': 'gswin64c.exe'}

def _bin(name):
    base = getattr(sys, '_MEIPASS', None)
    if not base:
        return name
    exe = _WIN_NAMES.get(name, name + '.exe') if os.name == 'nt' else name
    return os.path.join(base, 'bin', exe)

def _spawn(argv, **kw):
    """subprocess.run with check=True, and no console flash on Windows.
    A windowed .exe pops a console for every child process without this."""
    kw.setdefault('check', True)
    if os.name == 'nt':
        kw.setdefault('creationflags', 0x08000000)   # CREATE_NO_WINDOW
    return subprocess.run(argv, **kw)

W, H, M = 288.0, 432.0, 16.0          # 4x6 in page, 16 pt margin
X_QTY, X_NAME, X_SUB = M, M + 24, W - M
NAME_W, VAR_X = 172.0, M + 24

# ---------------------------------------------------------------- text metrics
_HB = {' ':278,'!':333,'"':474,'#':556,'$':556,'%':889,'&':722,"'":238,'(':333,
 ')':333,'*':389,'+':584,',':278,'-':333,'.':278,'/':278,':':333,';':333,'<':584,
 '=':584,'>':584,'?':611,'@':975,'[':333,'\\':278,']':333,'^':584,'_':556,'`':333,
 '{':389,'|':280,'}':389,'~':584}
for _c in '0123456789': _HB[_c] = 556
for _c, _w in zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
  [722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,944,667,667,611]): _HB[_c]=_w
for _c, _w in zip('abcdefghijklmnopqrstuvwxyz',
  [556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,556,333,611,556,778,556,556,500]): _HB[_c]=_w
_HV = dict(_HB)
_HV.update({"'":191,'&':667,'!':278,'?':556,'@':1015,'"':355})
for _c, _w in zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
  [667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611]): _HV[_c]=_w
for _c, _w in zip('abcdefghijklmnopqrstuvwxyz',
  [556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500]): _HV[_c]=_w

def sw(txt, size, bold=False):
    t = _HB if bold else _HV
    return sum(t.get(c, 556) for c in txt) * size / 1000.0

def wrap(txt, width, size, bold=False):
    out, cur = [], ""
    for word in txt.split():
        trial = (cur + " " + word).strip()
        if cur and sw(trial, size, bold) > width:
            out.append(cur); cur = word
        else:
            cur = trial
    if cur: out.append(cur)
    return out or [""]

def renderable(s):
    """Normalise text to exactly what survives onto the page. Fonts are
    re-encoded to ISO Latin-1, so ASCII and Latin-1 (accents, (R)) come through;
    anything outside it (emoji, (TM), the U+25A0 stand-ins pdftotext emits for
    unmapped glyphs) becomes a space. Renderer and auditor share this, so the
    two can never drift apart."""
    keep = lambda c: 32 <= ord(c) < 127 or 160 <= ord(c) < 256
    return re.sub(r'\s+', ' ', "".join(c if keep(c) else ' ' for c in s)).strip()

def esc(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch in '()\\':          out.append('\\' + ch)
        elif 32 <= o < 127:       out.append(ch)
        elif 160 <= o < 256:      out.append('\\%03o' % o)   # Latin-1 via ISOLatin1
        else:                     out.append(' ')
    return "".join(out)

# -------------------------------------------------------------------- parsing
RE_ITEM  = re.compile(r'^\s*(\d+)\s{2,}(.*?)\s{2,}Order (\d+)\s+\$([\d,]+\.\d\d)\s*$')
RE_BOIL  = re.compile(r'Follow|Bookmark|Save Big|Have\.\.\.')
RE_TOTAL = re.compile(r'^\s*(\d+) Items?\s+\$([\d,]+\.\d\d)\s*$')
RE_TO    = re.compile(r'^To:\s*(\S+)')
RE_SHIP  = re.compile(r'^\s*(USPS .+?)\s{2,}(.+?)\s*$')
# Domestic USPS issues a 20- or 22-digit IMpb barcode; an international
# shipment carries a 13-character UPU S10 number instead (2 letters, 9 digits,
# 2-letter country code). Spelling out both shapes rather than a bare length
# floor is what keeps an item's own '#12' out of this line.
RE_TRACK = re.compile(r'^\s*#(\d{20,}|[A-Z]{2}\d{9}[A-Z]{2})\s{2,}([\d.]+ \w+)\s*$')
# Whatnot prints a listing's SKU in the Attributes column, on the line after
# "Order N". It has to come off the line before the rest joins the name: a
# wrapped name puts its #N after the SKU, so cutting at #N kept the SKU text.
RE_SKU   = re.compile(r'(?:^|\s{2,})SKU (\S+)\s*$')

def clean(s):
    return re.sub(r'\s+', ' ', s.replace('■', ' ')).strip(' •-')

def split_variant(name):
    m = re.search(r'#\s*(\d+)\s*$', name)
    return (clean(name), None) if not m else (clean(name[:m.start()]), '#' + m.group(1))

def pdf_pages(pdf):
    """Text of every page, via pdftotext -layout."""
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
        tmp = f.name
    try:
        _spawn([_bin('pdftotext'), '-layout', '-enc', 'UTF-8', pdf, tmp])
        pages = open(tmp, encoding='utf-8').read().split('\f')
    finally:
        os.unlink(tmp)
    if pages and not pages[-1].strip(): pages.pop()
    return pages

def parse_shipment(pages):
    ship, lines = {}, []
    for p in pages:
        for ln in p.split('\n'):
            if (m := RE_TO.match(ln.strip())):    ship.setdefault('to', m.group(1))
            if (m := RE_TOTAL.match(ln)):         ship['stated'] = (int(m.group(1)), m.group(2))
            if (m := RE_TRACK.match(ln)):         ship['track'], ship['weight'] = m.groups()
            if (m := RE_SHIP.match(ln)) and 'USPS' in m.group(1):
                ship['svc'], ship['dims'] = clean(m.group(1)), m.group(2)
            lines.append(ln)
    items, cur = [], None
    for ln in lines:
        if (m := RE_ITEM.match(ln)):
            cur = dict(qty=int(m.group(1)), name=m.group(2), order=m.group(3),
                       price=float(m.group(4).replace(',', '')), sku=None)
            items.append(cur)
        elif cur is not None:
            # the SKU first: it can share a line with the seller boilerplate
            # ("Follow • Bookmark     SKU A-T-63"), which ends the block
            if cur['sku'] is None and (s := RE_SKU.search(ln)):
                cur['sku'], ln = s.group(1), ln[:s.start()]
                if not ln.strip():
                    continue
            # an item block ends at a blank line, the boilerplate, or the footer
            if (not ln.strip() or RE_BOIL.search(ln) or RE_TOTAL.match(ln)
                    or ln.startswith('QTY') or 'Packing Slip' in ln or 'USPS' in ln):
                cur = None
            else:
                cur['name'] += ' ' + ln.strip()
    for it in items:                       # trailing #N closes the name
        if (m := re.search(r'#\s*\d+', it['name'])):
            it['name'] = it['name'][:m.end()]
    return ship, items

def address(pagetext):
    """Split the two-column To:/From: header at the x of 'From:'. The block
    runs to the QTY table header, blank lines included: a long username wraps
    its NEW badge onto a line of its own, and pdftotext then leaves a blank
    line before the name and street, so stopping at the first blank line
    silently dropped the whole address."""
    return [x for x in header_lines(pagetext, 'to') if x], \
           [x for x in header_lines(pagetext, 'from') if x]

def header_region(pagetext):
    """The raw lines from the To:/From: line up to (not including) QTY."""
    out = None
    for ln in pagetext.split('\n'):
        if out is None:
            if 'To:' in ln and 'From:' in ln: out = [ln]
            continue
        if ln.lstrip().startswith('QTY'): break
        out.append(ln)
    return out or []

def slip_body(pagetext):
    """The page from the To:/From: line down. A branded band above it holds
    the user's free text, which the audit must not read as slip facts (a
    message saying '#1' or 'SKU ' would otherwise pass or fail checks). The
    real header is drawn once per page, under the band, so the LAST such line
    is the anchor even if the band itself imitates one."""
    lines = pagetext.split('\n')
    for i in range(len(lines) - 1, -1, -1):
        if 'To:' in lines[i] and 'From:' in lines[i]:
            return '\n'.join(lines[i:])
    return pagetext

def header_lines(pagetext, side):
    region = header_region(pagetext)
    if not region: return []
    col = region[0].index('From:')
    return [(ln[:col] if side == 'to' else ln[col:]).strip() for ln in region]

def load(pdf):
    """-> [(slip_page_numbers, ship, items)] in document order."""
    pages = pdf_pages(pdf)
    slips = [(i, p) for i, p in enumerate(pages) if 'Packing Slip' in p]
    groups = []
    for i, p in slips:
        if groups and groups[-1][-1][0] == i - 1: groups[-1].append((i, p))
        else: groups.append([(i, p)])
    return pages, [([n + 1 for n, _ in g], *parse_shipment([p for _, p in g])) for g in groups]

def group_items(items):
    # SKU is part of the key: two listings sharing a name but not a SKU sit in
    # different bins, so they must not share a line
    g = OrderedDict()
    for it in items:
        product, variant = split_variant(it['name'])
        sku = it.get('sku')
        e = g.setdefault((product.upper(), sku),
                         dict(product=product, sku=sku, qty=0, subtotal=0.0, variants=[]))
        e['qty'] += it['qty']; e['subtotal'] += it['price']
        e['variants'].append(dict(variant=variant, price=it['price'], order=it['order']))
    return list(g.values())

# ------------------------------------------------------------------ rendering
def _num_ops(num, x):
    return [f"10.5 HB ({esc(num)}) {x:.1f} 0 L"]

def display_name(e):
    """What the product row prints. The SKU leads because it is what the
    picker reads to find the bin."""
    return f"[{e['sku']}] {e['product']}" if e.get('sku') else e['product']

def build_rows(grouped):
    blocks = []
    for e in grouped:
        b, ls = [], wrap(display_name(e), NAME_W, 8.5, True)
        head = [f"9 HB ({esc(str(e['qty']))}) {X_QTY} 0 L",
                f"8.5 HB ({esc(ls[0])}) {X_NAME} 0 L",
                f"9 HB ({esc('$%.2f' % e['subtotal'])}) {X_SUB} 0 R"]
        inlined, num, bx = False, None, 0.0
        if len(e['variants']) == 1:
            # a lone unit keeps its # on the product row, so grouped sub-rows
            # only appear where a product actually repeats
            num = e['variants'][0]['variant'] or 'no #'
            bx = X_NAME + sw(ls[-1], 8.5, True) + 7
            if bx + sw(num, 10.5, True) < X_SUB - sw('$%.2f' % e['subtotal'], 9, True) - 10:
                inlined = True
                if len(ls) == 1: head += _num_ops(num, bx)
        b.append((12, head))
        for k, extra in enumerate(ls[1:]):
            ops = [f"8.5 HB ({esc(extra)}) {X_NAME} 0 L"]
            if inlined and k == len(ls) - 2: ops += _num_ops(num, bx)
            b.append((10, ops))
        if not inlined:
            for v in e['variants']:
                n2, pr = v['variant'] or 'no #', '$%.2f' % v['price']
                x = VAR_X + 11
                ops = [f"0.35 setgray {VAR_X:.1f} 1.6 3 3 rectfill 0 setgray",
                       f"10.5 HB ({esc(n2)}) {x:.1f} 0 L",
                       f"8.5 HB ({esc(pr)}) {X_SUB} 0 R"]
                x0 = x + sw(n2, 10.5, True) + 5
                x1 = X_SUB - sw(pr, 8.5, True) - 5
                dots = " ".join(f"{x0 + 3.6 * k:.1f} 2.2 0.7 0.7 rectfill"
                                for k in range(max(0, int((x1 - x0) // 3.6))))
                if dots: ops.append(f"0.6 setgray {dots} 0 setgray")
                b.append((12, ops))
        blocks.append(b)
    return blocks

def slip_ps(ship, grouped, to, frm, brand=None):
    blocks = build_rows(grouped)
    n = sum(e['qty'] for e in grouped); tot = sum(e['subtotal'] for e in grouped)
    d = BAND if brand else 0         # a branded header pushes everything down
    TOP_Y, BOT_Y = H - 116 - d, 74.0
    pages, cur, y = [], [], TOP_Y
    for b in blocks:
        need = sum(h for h, _ in b) + 3
        if y - need < BOT_Y and cur:
            pages.append(cur); cur = []; y = TOP_Y
        cur.append(b); y -= need
    pages.append(cur)
    out = []
    for pi, pg in enumerate(pages, 1):
        s = ["/EncV ISOLatin1Encoding 256 array copy def",
             "EncV 39 /quotesingle put",       # else code 39 draws a curly quote
             "EncV 96 /grave put",
             "EncV 45 /hyphen put",            # ISOLatin1 puts /minus here, which
                                               # extracts as U+2212 and breaks ZIP+4
             "EncV 173 /hyphen put",
             "/reencode { findfont dup length dict begin"
             " { 1 index /FID ne { def } { pop pop } ifelse } forall"
             " /Encoding EncV def currentdict end definefont pop } def",
             "/HelvB-L /Helvetica-Bold reencode",
             "/Helv-L  /Helvetica reencode",
             "/CourB-L /Courier-Bold reencode",
             "/HB { /HelvB-L findfont exch scalefont setfont } def",
             "/HV { /Helv-L findfont exch scalefont setfont } def",
             "/CO { /CourB-L findfont exch scalefont setfont } def",
             "/L { moveto show } def",
             "/R { 3 -1 roll dup stringwidth pop 4 -1 roll exch sub 3 -1 roll moveto show } def"]
        A = s.append
        if brand:
            A("0 setgray"); s.extend(brand_ops(brand, pi, len(pages)))
        else:
            A(f"11 HB 0 setgray (Whatnot Packing Slip) {M} {H-26} L")
            A(f"8 HV ({pi}/{len(pages)}) {W-M} {H-26} R")
        A(f"0.8 setlinewidth {M} {H-33-d} moveto {W-M} {H-33-d} lineto stroke")
        yy = H - 46 - d
        A(f"8 HB (To:) {M} {yy} L")
        A(f"8 HV ({esc(clean(to[0].replace('To:','')))}) {M+18} {yy} L")
        A(f"8 HB (From:) {W/2} {yy} L")
        A(f"8 HV ({esc(clean(frm[0].replace('From:','')))}) {W/2+26} {yy} L")
        yl = yr = yy - 10
        for ln in to[1:6]:  A(f"7.5 HV ({esc(ln)}) {M} {yl} L"); yl -= 9
        for ln in frm[1:6]: A(f"7.5 HV ({esc(ln)}) {W/2} {yr} L"); yr -= 9
        th = H - 100 - d
        A(f"0.5 setlinewidth {M} {th+8} moveto {W-M} {th+8} lineto stroke")
        A(f"7 HB (QTY) {X_QTY} {th} L  7 HB (Name & Description) {X_NAME} {th} L")
        A(f"7 HB (Subtotal) {X_SUB} {th} R")
        A(f"0.5 setlinewidth {M} {th-5} moveto {W-M} {th-5} lineto stroke")
        y = TOP_Y
        for b in pg:
            for h, ops in b:
                A(f"gsave 0 {y:.1f} translate"); s.extend(ops); A("grestore")
                y -= h
            y -= 3
        A(f"0.8 setlinewidth {M} 66 moveto {W-M} 66 lineto stroke")
        if pi == len(pages):
            A(f"9 HB ({n} Item{'s' if n != 1 else ''}) {M} 52 L")
            A(f"9 HB ({esc('$%.2f' % tot)}) {W-M} 52 R")
        A(f"7.5 HV ({esc(ship.get('svc',''))}) {M} 34 L")
        A(f"7.5 HV ({esc(ship.get('dims',''))}) {W-M} 34 R")
        A(f"7 CO (#{esc(ship.get('track',''))}) {M} 22 L")
        A(f"7.5 HV ({esc(ship.get('weight',''))}) {W-M} 22 R")
        A("showpage")
        out.append("\n".join(s) + "\n")
    return out

# ----------------------------------------------------------------- brand band
BAND = 19.0                      # how far a branded header pushes the page down
LOGO_W, LOGO_H = 108.0, 36.0     # 1.5 x 0.5 in
LOGO_TOP = H - 12
MSG_SIZE = 9
MSG_W = W - M - (M + LOGO_W + 8) # 140 pt beside the logo box

def brand_message_lines(brand):
    """The message as it will print: up to two lines, in the width left over
    once the logo box is (or isn't) taken."""
    msg = renderable(brand.message)
    if not msg:
        return []
    taken = brand.logo is not None or renderable(brand.shop_name)
    return wrap(msg, MSG_W if taken else W - 2 * M, MSG_SIZE)[:2]

def brand_ops(brand, pi, npages):
    """Logo (or shop name) on the left, the message beside it, and
    'Packing Slip n/m' in the corner -- load() and verify() find slip pages
    by those words, so they stay on every page."""
    ops = [f"7 HV (Packing Slip {pi}/{npages}) {W-M} {H-20} R"]
    x = M
    if brand.logo is not None:
        w, h = brand.logo.size
        k = min(0.24, LOGO_W / w, LOGO_H / h)   # 72/300; never outside the box
        ops.append(f"gsave {M} {LOGO_TOP - h * k:.2f} translate "
                   f"{w * k:.2f} {h * k:.2f} scale Logo grestore")
        x = M + LOGO_W + 8
    elif renderable(brand.shop_name):
        size = shop_name_size(brand.shop_name) or 8
        ops.append(f"{size} HB ({esc(renderable(brand.shop_name))}) {M} "
                   f"{LOGO_TOP - LOGO_H / 2 - size * 0.35:.1f} L")
        x = M + LOGO_W + 8
    for k, ln in enumerate(brand_message_lines(brand)):
        ops.append(f"{MSG_SIZE} HV ({esc(ln)}) {x:.1f} {H - 33 - 11 * k} L")
    return ops

def logo_prolog(im):
    """Define the logo once; every slip page draws it with `Logo`. A string
    DataSource is read from its start on each use, so a 300-page job carries
    one copy of the logo, not 300."""
    w, h = im.size
    data = base64.a85encode(im.tobytes()).decode()
    return ("/LogoData <~"
            + "\n".join(data[i:i+120] for i in range(0, len(data), 120))
            + "~> def\n"
            f"/Logo {{ /DeviceGray setcolorspace << /ImageType 1 /Width {w} "
            f"/Height {h} /BitsPerComponent 1 /Decode [0 1] "
            f"/ImageMatrix [{w} 0 0 -{h} 0 {h}] /DataSource LogoData >> image }} def\n")

def shop_name_size(name):
    """Largest bold size, 16 down to 8 pt, at which the name fills the logo
    box; None when even 8 pt is too wide."""
    name = renderable(name)
    for size in range(16, 7, -1):
        if sw(name, size, True) <= LOGO_W:
            return size
    return None

# --------------------------------------------------------------------- labels
LABEL_DPI = 300                        # 4x6 in at 300 dpi == the source rasters

def _to_1bit(im):
    """Whatnot already lays a landscape 6x4 First-Class label sideways on its
    portrait page, so a rendered page needs no rotation of its own -- it comes
    out oriented exactly as the old extract-and-rotate path left it. The guard
    stays only for a page that is itself landscape."""
    if im.width > im.height:
        im = im.transpose(Image.ROTATE_90)
    return im.convert('L').point(lambda p: 255 if p >= 128 else 0, '1')

def label_bitmap(pdf, pageno, tmpdir):
    """Render the label page `pageno` as a 1-bit PIL image (or None).

    Rendering the composited page, rather than digging an image out of it, is
    deliberate. A label carrying a transparency mask makes `pdfimages` write
    two files -- the artwork and the mask -- of byte-identical size, so
    choosing between them by file size was decided by unsorted directory
    order. It picked the blank mask and printed an empty label, twice, and the
    audit agreed with itself because it extracted the same way (Sept 16
    shipment 61, Sept 20 shipment 77). What the page renders to is what the
    printer puts on the sticker; nothing else is worth comparing.
    """
    for f in glob.glob(os.path.join(tmpdir, 'L*')): os.remove(f)
    _spawn([_bin('pdftoppm'), '-r', str(LABEL_DPI), '-gray',
            '-f', str(pageno), '-l', str(pageno),
            pdf, os.path.join(tmpdir, 'L')])
    cand = [f for f in os.listdir(tmpdir) if f.startswith('L')]
    if not cand: return None
    return _to_1bit(Image.open(os.path.join(tmpdir, cand[0])))

def embedded_bitmap(pdf, pageno, tmpdir):
    """The single 1-bit image this program itself embedded on `pageno`.

    Only ever pointed at our own output, whose label pages carry exactly one
    image and no mask, so there is nothing to choose between. Auditing the
    output this way keeps the comparison pixel-exact while running down a
    different path from the renderer -- the two cannot go blind together.
    """
    for f in glob.glob(os.path.join(tmpdir, 'E*')): os.remove(f)
    _spawn([_bin('pdfimages'), '-p', '-f', str(pageno), '-l', str(pageno),
            pdf, os.path.join(tmpdir, 'E')])
    cand = [f for f in os.listdir(tmpdir) if f.startswith('E')]
    if len(cand) != 1: return None
    return _to_1bit(Image.open(os.path.join(tmpdir, cand[0])))

def is_blank(im):
    """True if nothing would print. A blank label is never a correct result."""
    return im is None or not any(p == 0 for p in im.get_flattened_data())

def label_ps(im):
    w, h = im.size
    data = base64.a85encode(zlib.compress(im.tobytes(), 9)).decode() + '~>'
    return (f"gsave 0 0 translate {W} {H} scale\n/DeviceGray setcolorspace\n"
            f"<< /ImageType 1 /Width {w} /Height {h} /BitsPerComponent 1 /Decode [0 1]\n"
            f"   /ImageMatrix [{w} 0 0 -{h} 0 {h}]\n"
            f"   /DataSource currentfile /ASCII85Decode filter /FlateDecode filter >> image\n"
            + "\n".join(data[i:i+120] for i in range(0, len(data), 120))
            + "\ngrestore\nshowpage\n")

# ---------------------------------------------------------------------- build
PS_HEAD = f"%!PS-Adobe-3.0\n<< /PageSize [{W} {H}] >> setpagedevice\n"

def build(src, out, quiet=False, progress=None, brand=None):
    raw, data = load(src)
    ps = [PS_HEAD + (logo_prolog(brand.logo) if brand and brand.logo is not None else "")]
    nsl = nlb = 0
    with tempfile.TemporaryDirectory() as td:
        for i, (pages, ship, items) in enumerate(data):
            to, frm = address(raw[pages[0] - 1])
            sp = slip_ps(ship, group_items(items), to, frm, brand)
            ps += sp; nsl += len(sp)
            im = label_bitmap(src, pages[-1] + 1, td)
            if im is not None: ps.append(label_ps(im)); nlb += 1
            if progress:
                progress(i + 1, len(data), "building slips")
            elif not quiet and sys.stderr.isatty():
                print(f"\r  rendering {i+1}/{len(data)}", end='', file=sys.stderr, flush=True)
    if not progress and not quiet and sys.stderr.isatty():
        print(file=sys.stderr)
    with tempfile.NamedTemporaryFile('w', suffix='.ps', delete=False) as f:
        f.write("".join(ps)); psfile = f.name
    try:
        _spawn([_bin('gs'),'-q','-dBATCH','-dNOPAUSE','-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.4','-dEmbedAllFonts=true','-dSubsetFonts=true',
            '-dAutoFilterMonoImages=false','-dMonoImageFilter=/FlateEncode',
            '-dDownsampleMonoImages=false','-dFIXEDMEDIA',
            f'-dDEVICEWIDTHPOINTS={W}', f'-dDEVICEHEIGHTPOINTS={H}',
            f'-sOutputFile={out}', psfile])
    finally:
        os.unlink(psfile)
    return len(data), nsl, nlb

def preview_png(brand, png):
    """One sample slip through the real renderer, at a thermal head's 203 dpi
    in pure black and white -- what the Branding tab shows is what prints."""
    ship = dict(svc='USPS Ground Advantage', dims='12 x 12 x 12 in',
                track='9300120762602517212464', weight='7.0 oz')
    items = [dict(qty=1, name='ROSEY BALL #2', order='1', price=2.0, sku='A-T-63'),
             dict(qty=1, name='ROSEY BALL #3', order='2', price=3.0, sku='A-T-63'),
             dict(qty=1, name='CRUNCHY LOBSTER #1', order='3', price=3.0, sku='TB200-477')]
    to = ['To: buyer123', 'Jane Buyer', '1 Main St', 'Springfield, IL 62701']
    frm = ['From: ' + (renderable(brand.shop_name) or 'your shop'),
           '2 Shop Rd', 'Townsville, CA 90001']
    ps = PS_HEAD + (logo_prolog(brand.logo) if brand.logo is not None else "") \
         + slip_ps(ship, group_items(items), to, frm, brand)[0]
    with tempfile.NamedTemporaryFile('w', suffix='.ps', delete=False) as f:
        f.write(ps); psfile = f.name
    try:
        _spawn([_bin('gs'), '-q', '-dBATCH', '-dNOPAUSE', '-sDEVICE=pngmono',
                '-r203', '-dFIXEDMEDIA', f'-dDEVICEWIDTHPOINTS={W}',
                f'-dDEVICEHEIGHTPOINTS={H}', f'-sOutputFile={png}', psfile])
    finally:
        os.unlink(psfile)

# --------------------------------------------------------------------- verify
class Audit:
    def __init__(self):
        self.checks = 0; self.fail = []
    def ok(self, cond, label, detail=''):
        self.checks += 1
        if not cond: self.fail.append((label, detail))
        return cond
    def present(self, value, haystack, label):
        """A fact the source never yielded is a failure, not a pass.

        `'' in anything` is True, so auditing a missing value with a plain
        `in` test silently reports OK — and the slip prints without it."""
        return self.ok(bool(value) and value in haystack, label,
                       repr(value) if value else 'missing from the source slip')
    def text(self, title):
        lines = [f"\n{title}",
                 f"  assertions run : {self.checks}",
                 f"  failures       : {len(self.fail)}"]
        for l, d in self.fail[:40]:
            lines.append(f"    FAIL {l}: {d}")
        if len(self.fail) > 40:
            lines.append(f"    ... and {len(self.fail)-40} more")
        return "\n".join(lines)

    def report(self, title):
        print(self.text(title))
        return not self.fail

# The auditor's own view of SKUs. Not RE_SKU: the parser once glued SKU text
# onto names and an audit that parsed the same way passed it. The two strict
# regexes agree on what a SKU looks like, so a shape neither reads (say
# 'SKU AB 12') passes both; RE_SKU_WORD, a deliberately loose count of every
# SKU token, is what catches it.
RE_SKU_WORD = re.compile(r'\bSKU\b')
RE_SRC_SKU = re.compile(r'(?:^|\s{2})SKU (\S+)\s*$')
# The qty is optional: pdftotext sometimes lifts a lone '#N' above its row and
# leaves the '[SKU] name' text on a line of its own.
RE_OUT_SKU = re.compile(r'^\s*(?:\d+\s+)?\[([^\]\s]+)\]', re.M)

def audit_skus(a, tag, src_text, sitems, grouped, out_text):
    """A wrong SKU sends the picker to the wrong bin, so it is held to the same
    standard as a wrong #N."""
    raw = sorted(m.group(1) for ln in src_text.split('\n')
                 if (m := RE_SRC_SKU.search(ln)))
    parsed = sorted(it['sku'] for it in sitems if it.get('sku'))
    a.ok(len(RE_SKU_WORD.findall(src_text)) == len(parsed), f'{tag} SKUs counted',
         f'{len(RE_SKU_WORD.findall(src_text))} SKU tokens vs {len(parsed)} parsed')
    a.ok(raw == parsed, f'{tag} SKUs parsed', f'{parsed} vs source {raw}')
    shown = set(RE_OUT_SKU.findall(out_text))
    a.ok(shown == set(raw), f'{tag} SKUs on slip',
         f'{sorted(shown)} vs source {sorted(set(raw))}')
    flat = renderable(out_text)
    for e in grouped:
        if e.get('sku'):
            first = renderable(e['product']).split(' ')[0]
            a.ok(f"[{e['sku']}] {first}" in flat, f'{tag} SKU pairing',
                 f"{e['sku']} {e['product'][:30]!r}")
    a.ok('SKU ' not in out_text, f'{tag} no SKU text on slip')

def audit_brand(a, brand, slip_texts):
    """The message is cosmetic but promised on every page; checked line by
    line because a two-line message lands on two text lines."""
    if brand is None:
        return
    lines = brand_message_lines(brand)
    if not lines:
        return
    for i, t in enumerate(slip_texts, 1):
        flat = renderable(t)
        a.ok(all(ln in flat for ln in lines), f'slip page {i} brand message',
             lines[0][:40])

def kinds_detail(kinds):
    """Point at where the slip/label pattern first breaks. Truncating the head
    just prints a screenful of correct 'SBSB...' and hides the one page that
    matters."""
    i = re.match(r'(?:S+B)*', kinds).end()
    if i >= len(kinds):
        return f'{len(kinds)} pages, ends mid-shipment: ...{kinds[-20:]}'
    return (f'page {i+1} unexpected {kinds[i]!r}: '
            f'...{kinds[max(0, i-16):i]}[{kinds[i]}]{kinds[i+1:i+17]}...')

def verify(src, out, deep=False, progress=None, brand=None):
    a = Audit()
    raw_s, src_ships = load(src)
    raw_o, out_ships = load(out)
    out_pages = pdf_pages(out)

    # ---- structure
    a.ok(len(out_ships) == len(src_ships), 'shipment count',
         f'{len(out_ships)} vs {len(src_ships)}')
    # A shipment is one or more slip pages followed by exactly one label. Dense
    # slips legitimately run to a second page, so the stride is not fixed at 2.
    kinds = ''.join('S' if 'Packing Slip' in p else 'B' for p in out_pages)
    a.ok(re.fullmatch(r'(?:S+B)+', kinds) is not None, 'slip/label grouping',
         kinds_detail(kinds))
    a.ok(kinds.count('B') == len(src_ships), 'label count',
         f"{kinds.count('B')} vs {len(src_ships)} shipments")
    a.ok(len(out_pages) == kinds.count('S') + kinds.count('B'), 'page count',
         f"{len(out_pages)} vs {kinds.count('S')} slip + {kinds.count('B')} label")

    # ---- global item ledger
    src_orders, out_orders = {}, {}
    for _, _, items in src_ships:
        for it in items: src_orders[it['order']] = it
    a.ok(len(src_orders) == sum(len(i) for _, _, i in src_ships),
         'source order ids unique', f'{len(src_orders)}')

    # ---- per shipment
    for k, (spages, sship, sitems) in enumerate(src_ships):
        gr = group_items(sitems)
        tag = f'shipment {k} ({sship.get("to")})'
        # the shipment's own slip pages, however many it took
        opages = out_ships[k][0] if k < len(out_ships) else []
        if not a.ok(bool(opages), f'{tag} slip present'):
            continue
        opage = '\n'.join(slip_body(out_pages[n - 1]) for n in opages)

        # every word of the source To:/From: header must reach the slip. This
        # deliberately ignores columns and lines, so it does not share
        # address()'s idea of where the block ends and cannot share its bugs.
        swords = Counter(renderable(clean(' '.join(header_region(raw_s[spages[0] - 1])))).split())
        owords = Counter(renderable(clean(' '.join(header_region(out_pages[opages[0] - 1])))).split())
        missing = swords - owords
        a.ok(bool(swords) and not missing, f'{tag} header words',
             ' '.join(sorted(missing))[:60] or 'no header found')

        # recipient + full address block must survive
        sto, _ = address(raw_s[spages[0] - 1])
        for line in sto:
            probe = renderable(clean(line.replace('To:', '')))
            if probe:
                a.ok(probe in renderable(opage), f'{tag} address line',
                     repr(probe[:40]))

        # shipping facts
        a.present(sship.get('track', ''), opage, f'{tag} tracking')
        a.present(sship.get('weight', ''), opage, f'{tag} weight')
        a.present(sship.get('dims', ''), opage, f'{tag} dims')
        a.present(renderable(sship.get('svc', '')), renderable(opage),
                  f'{tag} service')

        # totals
        n = sum(e['qty'] for e in gr); t = sum(e['subtotal'] for e in gr)
        m = RE_TOTAL.search(opage) or re.search(r'(\d+) Items?\s+\$([\d,]+\.\d\d)', opage)
        a.ok(m is not None, f'{tag} total line present')
        if m:
            a.ok(int(m.group(1)) == n, f'{tag} item count', f'{m.group(1)} vs {n}')
            a.ok(abs(float(m.group(2).replace(',', '')) - t) < .005,
                 f'{tag} total', f'{m.group(2)} vs {t:.2f}')
        if sship.get('stated'):
            a.ok(sship['stated'][0] == n, f'{tag} count matches source footer',
                 f'{sship["stated"][0]} vs {n}')
            a.ok(abs(float(sship['stated'][1].replace(',', '')) - t) < .005,
                 f'{tag} total matches source footer',
                 f'{sship["stated"][1]} vs {t:.2f}')

        # every unit: # present, price present, nothing invented
        for e in gr:
            for seg in wrap(display_name(e), NAME_W, 8.5, True):
                seg = renderable(seg)
                a.ok(seg and seg in renderable(opage), f'{tag} product',
                     f'{e["product"][:34]!r} segment {seg[:34]!r}')
            for v in e['variants']:
                out_orders[v['order']] = True
                if v['variant']:
                    a.ok(re.search(re.escape(v['variant']) + r'(?!\d)', opage) is not None,
                         f'{tag} variant', f'{e["product"]} {v["variant"]}')
                else:
                    a.ok('no #' in opage, f'{tag} unnumbered marker', e['product'])
                if len(e['variants']) > 1:
                    a.ok('$%.2f' % v['price'] in opage, f'{tag} unit price',
                         f'{v["variant"]} ${v["price"]:.2f}')

        stext = '\n'.join(raw_s[n - 1] for n in spages)
        audit_skus(a, tag, stext, sitems, gr, opage)

    audit_brand(a, brand, [p for p in out_pages if 'Packing Slip' in p])

    # ---- no order lost or invented
    a.ok(set(out_orders) == set(src_orders), 'order id set identical',
         f'missing={sorted(set(src_orders)-set(out_orders))[:5]} '
         f'extra={sorted(set(out_orders)-set(src_orders))[:5]}')

    # ---- money
    def money(ships):
        return round(sum(sum(i['price'] for i in items) for _, _, items in ships), 2)
    src_total = money(src_ships)
    found = [m for p in out_pages if 'Packing Slip' in p
             for m in [re.search(r'\d+ Items?\s+\$([\d,]+\.\d\d)', slip_body(p))] if m]
    a.ok(len(found) == len(src_ships), 'one total line per shipment',
         f'{len(found)} found vs {len(src_ships)} shipments')
    out_total = round(sum(float(m.group(1).replace(',', '')) for m in found), 2)
    a.ok(abs(src_total - out_total) < .005, 'grand total',
         f'{src_total:.2f} vs {out_total:.2f}')

    # ---- label images, pixel-exact, correct pairing
    if deep:
        with tempfile.TemporaryDirectory() as td:
            for k, (spages, sship, _) in enumerate(src_ships):
                si = label_bitmap(src, spages[-1] + 1, td)
                opages = out_ships[k][0] if k < len(out_ships) else []
                if not a.ok(bool(opages), f'shipment {k} slip present'):
                    continue
                oi = embedded_bitmap(out, opages[-1] + 1, td)
                a.ok(si is not None and oi is not None,
                     f'shipment {k} label present')
                if si is None or oi is None: continue
                # A label that would print nothing is never a correct result,
                # however faithfully it matches. Checked on both sides so a
                # blank in the export is caught too, not copied.
                a.ok(not is_blank(si), f'shipment {k} source label not blank',
                     sship.get('track', ''))
                a.ok(not is_blank(oi), f'shipment {k} label not blank',
                     sship.get('track', ''))
                a.ok(si.size == oi.size, f'shipment {k} label size',
                     f'{si.size} vs {oi.size}')
                a.ok(hashlib.sha256(si.tobytes()).digest() ==
                     hashlib.sha256(oi.tobytes()).digest(),
                     f'shipment {k} label pixels identical',
                     f'{sship.get("to")} {sship.get("track")}')
                if progress:
                    progress(k + 1, len(src_ships), "checking labels")
                elif sys.stderr.isatty():
                    print(f"\r  checking label {k+1}/{len(src_ships)}", end='',
                          file=sys.stderr, flush=True)
            if not progress and sys.stderr.isatty(): print(file=sys.stderr)
    return a

# ------------------------------------------------------------------------ cli
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='rebuild grouped slips + labels')
    b.add_argument('src'); b.add_argument('-o', '--out', required=True)
    b.add_argument('--deep', action='store_true', help='pixel-check every label')
    b.add_argument('--no-verify', action='store_true')
    b.add_argument('--no-brand', action='store_true',
                   help='plain header, ignoring the saved branding')
    v = sub.add_parser('verify', help='audit an existing source/output pair')
    v.add_argument('src'); v.add_argument('out')
    v.add_argument('--deep', action='store_true')
    v.add_argument('--no-brand', action='store_true')
    args = ap.parse_args()

    try:
        return _run(args)
    except Exception as exc:                 # never leave the caller a bare traceback
        print(f"\nAUDIT ABORTED: {type(exc).__name__}: {exc}")
        return 1

def _run(args):
    brand = None
    if not args.no_brand:
        import branding            # lazily: branding imports this module
        brand = branding.active()
        for note in (brand.notes if brand else []):
            print(f"branding: {note}")
    if args.cmd == 'build':
        n, nsl, nlb = build(args.src, args.out, brand=brand)
        size = os.path.getsize(args.out)
        print(f"built {args.out}: {n} shipments, {nsl} slip pages, {nlb} labels, "
              f"{size/1e6:.2f} MB")
        if args.no_verify: return 0
    a = verify(args.src, args.out, deep=args.deep, brand=brand)
    return 0 if a.report('AUDIT') else 1

if __name__ == '__main__':
    sys.exit(main())
