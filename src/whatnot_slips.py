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

RE_GIVEAWAY = re.compile(r'^(\[[^\]]*\] )?(GIVEAWAY)\b', re.I)

def name_ops(line, x=X_NAME):
    """A product-name line. A leading GIVEAWAY prints white on black so the
    packer can't miss it. The line is drawn as consecutive pieces at their
    exact widths, so it extracts as the very same text as one plain string."""
    m = RE_GIVEAWAY.match(line)
    if not m:
        return [f"8.5 HB ({esc(line)}) {x} 0 L"]
    pre, word, rest = m.group(1) or '', m.group(2), line[m.end():]
    xp = x + sw(pre, 8.5, True); w = sw(word, 8.5, True)
    ops = [f"8.5 HB ({esc(pre)}) {x} 0 L"] if pre else []
    ops += [f"{xp - 1.5:.1f} -2 {w + 3:.1f} 9.5 rectfill",
            f"1 setgray 8.5 HB ({esc(word)}) {xp:.1f} 0 L 0 setgray"]
    if rest: ops.append(f"8.5 HB ({esc(rest)}) {xp + w:.1f} 0 L")
    return ops

def build_rows(grouped, prices=True):
    blocks = []
    for e in grouped:
        b, ls = [], wrap(display_name(e), NAME_W, 8.5, True)
        head = [f"9 HB ({esc(str(e['qty']))}) {X_QTY} 0 L",
                *name_ops(ls[0])]
        if prices: head.append(f"9 HB ({esc('$%.2f' % e['subtotal'])}) {X_SUB} 0 R")
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
                       f"10.5 HB ({esc(n2)}) {x:.1f} 0 L"]
                x0 = x + sw(n2, 10.5, True) + 5
                if prices:
                    ops.append(f"8.5 HB ({esc(pr)}) {X_SUB} 0 R")
                    x1 = X_SUB - sw(pr, 8.5, True) - 5
                else:
                    x1 = X_SUB
                dots = " ".join(f"{x0 + 3.6 * k:.1f} 2.2 0.7 0.7 rectfill"
                                for k in range(max(0, int((x1 - x0) // 3.6))))
                if dots: ops.append(f"0.6 setgray {dots} 0 setgray")
                b.append((12, ops))
        blocks.append(b)
    return blocks

# every PS page string re-declares these: gs pages are concatenated
PS_PROLOG = ["/EncV ISOLatin1Encoding 256 array copy def",
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

def slip_ps(ship, grouped, to, frm, brand=None, footer=None, prices=True):
    blocks = build_rows(grouped) if prices else build_rows(grouped, False)
    n = sum(e['qty'] for e in grouped); tot = sum(e['subtotal'] for e in grouped)
    d = BAND if brand else 0         # a branded header pushes everything down
    fl = footer_lines(footer or "")
    u = FOOT_BAND if fl else 0      # a footer lifts the bottom block
    TOP_Y, BOT_Y = H - 116 - d, 74.0 + u
    pages, cur, y = [], [], TOP_Y
    for b in blocks:
        need = sum(h for h, _ in b) + 3
        if y - need < BOT_Y and cur:
            pages.append(cur); cur = []; y = TOP_Y
        cur.append(b); y -= need
    pages.append(cur)
    out = []
    for pi, pg in enumerate(pages, 1):
        s = list(PS_PROLOG)
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
        if prices: A(f"7 HB (Subtotal) {X_SUB} {th} R")
        A(f"0.5 setlinewidth {M} {th-5} moveto {W-M} {th-5} lineto stroke")
        y = TOP_Y
        for b in pg:
            for h, ops in b:
                A(f"gsave 0 {y:.1f} translate"); s.extend(ops); A("grestore")
                y -= h
            y -= 3
        A(f"0.8 setlinewidth {M} {66+u} moveto {W-M} {66+u} lineto stroke")
        if pi == len(pages):
            A(f"9 HB ({n} Item{'s' if n != 1 else ''}) {M} {52+u} L")
            if prices: A(f"9 HB ({esc('$%.2f' % tot)}) {W-M} {52+u} R")
        A(f"7.5 HV ({esc(ship.get('svc',''))}) {M} {34+u} L")
        A(f"7.5 HV ({esc(ship.get('dims',''))}) {W-M} {34+u} R")
        A(f"7 CO (#{esc(ship.get('track',''))}) {M} {22+u} L")
        A(f"7.5 HV ({esc(ship.get('weight',''))}) {W-M} {22+u} R")
        if fl:      # split_footer() relies on this being the lowest text on the page
            A(f"0.5 setlinewidth {M} 40 moveto {W-M} 40 lineto stroke")
            for k, ln in enumerate(fl):
                A(f"{FOOT_SIZE} HV ({esc(ln)}) {(W - sw(ln, FOOT_SIZE)) / 2:.1f} {29 - FOOT_LEAD * k} L")
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

FOOT_SIZE = 8
FOOT_LEAD = 10
FOOT_W = W - 2 * M
FOOT_BAND = 24.0                 # how far a footer lifts the bottom block

def footer_lines(text):
    """The footer as it will print: up to two lines of Helvetica regular."""
    text = renderable(text)
    if not text:
        return []
    return wrap(text, FOOT_W, FOOT_SIZE, bold=False)[:2]

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

# ------------------------------------------------------------------ pick list
RE_PICK_HEAD = re.compile(r'^\s*Pick List \d+/\d+')

def page_kind(text):
    """'P' pick list, 'S' slip, 'B' label - judged by the first non-blank line."""
    first = next((l for l in text.splitlines() if l.strip()), '')
    if RE_PICK_HEAD.match(first): return 'P'
    return 'S' if 'Packing Slip' in first else 'B'

def pick_rows(items):
    return sorted(({k: e[k] for k in ('product', 'sku', 'qty')} for e in group_items(items)),
                  key=lambda r: (r['sku'] is None, (r['sku'] or '').upper(), r['product'].upper()))

def _defuse(s):
    # any whitespace: pdftotext reads 'Packing  Slip' or a wrap as the marker too
    return re.sub(r'Packing\s+Slip', 'Packing-Slip', s)

PICK_X = M + 40
PICK_W = W - M - PICK_X

PICK_SUB_TAIL = " \u00b7 {} shipments \u00b7 {} items"

def pick_src_label(src_name):
    """The export's name as the pick-list subtitle prints it: no .pdf, defused,
    and cut with '...' so the whole line fits at 7 pt however long the name is.
    The audit reuses this on purpose (an exception to the independence rule,
    like audit_brand): the name is cosmetic, so a bug shared with the renderer
    can at worst pass an oddly shortened file name."""
    name = _defuse(re.sub(r'(?i)\.pdf$', '', src_name))
    room = W - 2 * M - sw(PICK_SUB_TAIL.format(9999, 99999), 7)
    if sw(name, 7) <= room:
        return name
    while name and sw(name + '...', 7) > room:
        name = name[:-1]
    return name.rstrip() + '...'

def pick_ps(rows, src_name, nships):
    nitems = sum(r['qty'] for r in rows)
    blocks = []
    for r in rows:
        ls = wrap(_defuse(display_name(r)), PICK_W, 8.5, True)
        ops = [f"0.6 setlinewidth {M} -1 7 7 rectstroke",
               f"10 HB ({esc(str(r['qty']))}) {M + 34} 0 R", *name_ops(ls[0], x=PICK_X)]
        b = [(12, ops)]
        b += [(10, [f"8.5 HB ({esc(l)}) {PICK_X} 0 L"]) for l in ls[1:]]
        blocks.append(b)
    top1, top = H - 60, H - 50
    pages, cur, y = [], [], top1
    for b in blocks:
        need = sum(h for h, _ in b) + 3
        if y - need < 40 and cur:
            pages.append(cur); cur = []; y = top
        cur.append(b); y -= need
    pages.append(cur)
    out = []
    for pi, pg in enumerate(pages, 1):
        s = list(PS_PROLOG)
        A = s.append
        A(f"11 HB 0 setgray (Pick List {pi}/{len(pages)}) {M} {H-26} L")
        A(f"0.8 setlinewidth {M} {H-33} moveto {W-M} {H-33} lineto stroke")
        if pi == 1:
            sub = pick_src_label(src_name) + PICK_SUB_TAIL.format(nships, nitems)
            A(f"7 HV ({esc(sub)}) {M} {H-45} L")
        y = top1 if pi == 1 else top
        for b in pg:
            for h, ops in b:
                A(f"gsave 0 {y:.1f} translate"); s.extend(ops); A("grestore")
                y -= h
            y -= 3
        if pi == len(pages):
            k = len(rows)
            A(f"0.8 setlinewidth {M} {y:.1f} moveto {W-M} {y:.1f} lineto stroke")
            tail = f"{k} product{'s' if k != 1 else ''} \u00b7 {nitems} item{'s' if nitems != 1 else ''}"
            A(f"9 HB ({esc(tail)}) {M} {y-12:.1f} L")
        A("showpage")
        out.append("\n".join(s) + "\n")
    return out

# ---------------------------------------------------------------------- build
PS_HEAD = f"%!PS-Adobe-3.0\n<< /PageSize [{W} {H}] >> setpagedevice\n"

def build(src, out, quiet=False, progress=None, brand=None, footer=None,
          prices=True, pick_list=False):
    raw, data = load(src)
    ps = [PS_HEAD + (logo_prolog(brand.logo) if brand and brand.logo is not None else "")]
    nsl = nlb = 0
    if pick_list:
        ps += pick_ps(pick_rows([it for _, _, items in data for it in items]),
                      os.path.basename(src), len(data))
    with tempfile.TemporaryDirectory() as td:
        for i, (pages, ship, items) in enumerate(data):
            to, frm = address(raw[pages[0] - 1])
            sp = slip_ps(ship, group_items(items), to, frm, brand, footer, prices)
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

def preview_png(brand, png, footer=None, prices=True):
    """One sample slip through the real renderer, at a thermal head's 203 dpi
    in pure black and white -- what the Branding tab shows is what prints."""
    ship = dict(svc='USPS Ground Advantage', dims='12 x 12 x 12 in',
                track='9300120762602517212464', weight='7.0 oz')
    items = [dict(qty=1, name='SAMPLE ITEM #2', order='1', price=2.0, sku='ABC-123'),
             dict(qty=1, name='SAMPLE ITEM #3', order='2', price=3.0, sku='ABC-123'),
             dict(qty=1, name='ANOTHER ITEM #1', order='3', price=3.0, sku='XYZ-789'),
             dict(qty=1, name='GIVEAWAY MYSTERY PRIZE #4', order='4', price=0.0)]
    to = ['To: buyer123', 'Jane Buyer', '1 Main St', 'Springfield, IL 62701']
    shop = renderable(brand.shop_name) if brand else ''
    frm = ['From: ' + (shop or 'your shop'),
           '2 Shop Rd', 'Townsville, CA 90001']
    ps = PS_HEAD + (logo_prolog(brand.logo) if brand and brand.logo is not None else "") \
         + slip_ps(ship, group_items(items), to, frm, brand, footer, prices)[0]
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
RE_SRC_ORDER = re.compile(r'\bOrder (\d+)\b')
# The qty is optional: pdftotext sometimes lifts a lone '#N' above its row and
# leaves the '[SKU] name' text on a line of its own.
# The auditor's own view of money on a slip printed without prices.
RE_PRICE_ANY = re.compile(r'\$\s*\d')
RE_OUT_COUNT = re.compile(r'^\s*(\d+) Items?\s*$', re.M)
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
    # which item a SKU belongs to, from the raw lines: a SKU line sits under
    # its item's "Order N". The checks above and below compare codes, so a
    # parse that hands a SKU to the wrong item would pass them all.
    owner, order = {}, None
    for ln in src_text.split('\n'):
        if (m := RE_SRC_ORDER.search(ln)): order = m.group(1)
        if (m := RE_SRC_SKU.search(ln)): owner[order] = m.group(1)
    mine = {it['order']: it['sku'] for it in sitems if it.get('sku')}
    bad = sorted((o for o in set(owner) | set(mine) if owner.get(o) != mine.get(o)), key=str)
    a.ok(not bad, f'{tag} SKU belongs to its order',
         f'order {bad[0]}: {mine.get(bad[0])} vs source {owner.get(bad[0])}' if bad else '')
    shown = set(RE_OUT_SKU.findall(out_text))
    a.ok(shown == set(raw), f'{tag} SKUs on slip',
         f'{sorted(shown)} vs source {sorted(set(raw))}')
    flat = renderable(out_text)
    for e in grouped:
        if e.get('sku'):
            first = renderable(e['product']).split(' ')[0]
            # a SKU too wide to share line 1 with the first word wraps alone,
            # and pdftotext reads the row's subtotal in between
            pair = re.escape(f"[{e['sku']}]") + r'(?: \$[\d,]+\.\d\d)? ' + re.escape(first)
            a.ok(re.search(pair, flat) is not None, f'{tag} SKU pairing',
                 f"{e['sku']} {e['product'][:30]!r}")
    a.ok('SKU ' not in out_text, f'{tag} no SKU text on slip')

def audit_brand(a, brand, slip_texts):
    """The message is cosmetic but promised on every page; checked line by
    line because a two-line message lands on two text lines. It reuses the
    renderer's wrap on purpose (an exception to the independence rule): the
    message is cosmetic, so a bug the two share can at worst pass a badly
    wrapped thank-you line."""
    if brand is None:
        return
    lines = brand_message_lines(brand)
    if not lines:
        return
    for i, t in enumerate(slip_texts, 1):
        flat = renderable(t)
        a.ok(all(ln in flat for ln in lines), f'slip page {i} brand message',
             lines[0][:40])

def split_footer(body, lines):
    """Strip the footer's printed lines off the end of a slip body.
    -> (body without them, whether they were there). The footer is the user's
    free text, so no fact check may read it: '#1' or 'SKU ' in a message would
    otherwise pass or fail them. Like audit_brand it reuses the renderer's
    footer_lines on purpose (cosmetic, so a shared bug can at worst pass a
    badly wrapped message)."""
    if not lines:
        return body, True
    rows = body.split('\n')
    idx = [i for i, ln in enumerate(rows) if ln.strip()]
    n = len(lines)
    if len(idx) < n or [renderable(rows[i]) for i in idx[-n:]] != [renderable(x) for x in lines]:
        return body, False
    return '\n'.join(rows[:idx[-n]]), True

def audit_footer(a, footer, found):
    """One check per slip page: `found` is each page's split_footer flag."""
    if not footer_lines(footer or ""):
        return          # no footer: record no checks, like audit_brand
    for i, ok in enumerate(found, 1):
        a.ok(ok, f'slip page {i} footer', (footer or '')[:40])

def audit_units(a, tag, grouped, opage, prices=True):
    """Every unit: # present, price present, nothing invented. -> the units."""
    # a SKU is free seller text: '[AB#2]' must not pass for a missing '#2'
    bare = re.sub(r'\[[^\]\s]+\]', '', opage)
    units = []
    for e in grouped:
        for seg in wrap(display_name(e), NAME_W, 8.5, True):
            seg = renderable(seg)
            a.ok(seg and seg in renderable(opage), f'{tag} product',
                 f'{e["product"][:34]!r} segment {seg[:34]!r}')
        for v in e['variants']:
            units.append(v)
            if v['variant']:
                a.ok(re.search(re.escape(v['variant']) + r'(?!\d)', bare) is not None,
                     f'{tag} variant', f'{e["product"]} {v["variant"]}')
            else:
                a.ok('no #' in bare, f'{tag} unnumbered marker', e['product'])
            if prices and len(e['variants']) > 1:
                a.ok('$%.2f' % v['price'] in bare, f'{tag} unit price',
                     f'{v["variant"]} ${v["price"]:.2f}')
    return units

def kinds_detail(kinds, lead=''):
    """Point at where the slip/label pattern first breaks. Truncating the head
    just prints a screenful of correct 'SBSB...' and hides the one page that
    matters. `lead` is the pick-list prefix ('P+') when one is expected."""
    m = re.match(lead + r'(?:S+B)*', kinds)
    i = m.end() if m else 0
    if i >= len(kinds):
        return f'{len(kinds)} pages, ends mid-shipment: ...{kinds[-20:]}'
    return (f'page {i+1} unexpected {kinds[i]!r}: '
            f'...{kinds[max(0, i-16):i]}[{kinds[i]}]{kinds[i+1:i+17]}...')

# The auditor's own view of the pick list. Quantities come off the raw source
# slip lines, not parse_shipment(): the renderer summed what the parser read,
# so an audit that trusted the parser would pass its misreads.
# [ \t], never \s: a qty and its 'Order N' share one line, and a wrapped name
# whose continuation is a bare number ('100') must not reach the next item's.
RE_SRC_QTY = re.compile(r'^[ \t]*(\d+)[ \t]{2,}.*?[ \t]{2,}Order (\d+)\s', re.M)
RE_PICK_ROW = re.compile(r'^\s*(\d+)\s+(\S.*?)\s*$')
RE_PICK_NUM = re.compile(r'^\s*Pick List (\d+)/(\d+)')
RE_PICK_SUB = re.compile(r'\u00b7 (\d+) shipments? \u00b7 (\d+) items?\s*$')
RE_PICK_TAIL = re.compile(r'^\s*(\d+) products? \u00b7 (\d+) items?\s*$')

def read_pick(pick_texts):
    """-> ([(qty, text)], [(products, items)], [(n, m)], [(ships, items)]).
    A row is a qty then its name; the lines under it, until the next row, are
    the wrapped rest of the name. A wrapped line that happens to start with a
    number ('2024 CARD BOX') is told from a new row by its indent: the qty is
    right-aligned left of the name column, so a row starts further left."""
    rows, tails, nums, subs = [], [], [], []
    for t in pick_texts:
        name_col = None                 # pdftotext sets the columns per page
        lines = [ln for ln in t.split('\n') if ln.strip()]
        if lines and (m := RE_PICK_NUM.match(lines[0])):    # the page heading
            nums.append((int(m.group(1)), int(m.group(2)))); lines = lines[1:]
        for ln in lines:
            if (m := RE_PICK_TAIL.match(ln)):
                tails.append((int(m.group(1)), int(m.group(2)))); continue
            if not rows and (m := RE_PICK_SUB.search(ln)):
                subs.append((int(m.group(1)), int(m.group(2)))); continue
            indent = len(ln) - len(ln.lstrip())
            m = RE_PICK_ROW.match(ln)
            if m and (name_col is None or indent < name_col - 1):
                rows.append([int(m.group(1)), m.group(2)]); name_col = m.start(2)
            elif rows:
                rows[-1][1] += ' ' + ln.strip()
            else:
                rows.append([None, ln.strip()])     # text before any row
    return [(q, renderable(x)) for q, x in rows], tails, nums, subs

def audit_pick(a, raw_src_pages, src_ships, pick_texts, src_name=''):
    """Every pick row against the raw export: right product, right summed
    quantity, nothing missing or invented, in SKU order, no money, no #N.
    `src_name` is the export's file name, which the subtitle prints: it is the
    user's text, so '$' or '#1' in it must not fail the money/#N checks."""
    raw_qty, dup = {}, []
    for p in raw_src_pages:
        if 'Packing Slip' not in p:
            continue
        for q, order in RE_SRC_QTY.findall(p):
            if order in raw_qty: dup.append(order)
            raw_qty[order] = int(q)
    items = [it for _, _, its in src_ships for it in its]
    parsed = {it['order'] for it in items}
    a.ok(not dup and set(raw_qty) == parsed, 'pick source orders',
         f'dup={dup[:3]} missing={sorted(parsed - set(raw_qty))[:3]} '
         f'extra={sorted(set(raw_qty) - parsed)[:3]}')

    want = OrderedDict()            # (PRODUCT, sku) -> [display text, qty]
    for it in items:
        product = split_variant(it['name'])[0]
        e = want.setdefault((product.upper(), it.get('sku')), [
            renderable(_defuse(f"[{it['sku']}] {product}" if it.get('sku') else product)), 0])
        e[1] += raw_qty.get(it['order'], 0)
    order = sorted(want, key=lambda k: (k[1] is None, (k[1] or '').upper(), k[0]))
    exp = [tuple(want[k]) for k in order]

    rows, tails, nums, subs = read_pick(pick_texts)
    texts = [x for _, x in rows]
    for text, q in exp:
        hits = [r for r in rows if r[1] == text]
        a.ok(len(hits) == 1 and hits[0][0] == q, 'pick row',
             f'{text[:40]!r} want {q}, found {[h[0] for h in hits] or "no row"}')
    known = {t for t, _ in exp}
    extra = [r for r in rows if r[1] not in known]
    a.ok(not extra, 'pick no extra rows',
         ', '.join(f'{q} {x[:30]!r}' for q, x in extra[:3]))
    a.ok(texts == [t for t, _ in exp], 'pick row order',
         next((f'row {i+1}: {g[:30]!r} vs {w[:30]!r}' for i, (g, (w, _)) in
               enumerate(zip(texts, exp)) if g != w), f'{len(texts)} vs {len(exp)} rows'))

    total = sum(q for _, q in exp)
    a.ok(len(tails) == 1, 'pick totals line', f'{len(tails)} found')
    if tails:
        a.ok(tails[0][0] == len(exp) == len(rows), 'pick total products',
             f'{tails[0][0]} printed, {len(rows)} rows, {len(exp)} expected')
        a.ok(tails[0][1] == total, 'pick total items', f'{tails[0][1]} vs {total}')
    a.ok(len(subs) == 1 and subs[0] == (len(src_ships), total), 'pick subtitle counts',
         f'{subs} vs {(len(src_ships), total)}')
    stated = [s.get('stated') for _, s, _ in src_ships]
    if stated and all(stated):
        a.ok(total == sum(n for n, _ in stated), 'pick items match source footers',
             f'{total} vs {sum(n for n, _ in stated)}')

    flat = renderable('\n'.join(pick_texts))
    if renderable(pick_src_label(src_name)):
        flat = flat.replace(renderable(pick_src_label(src_name)), ' ', 1)
    # A '#' or '$' inside a product's own name ('CARD #25 HOLO', '$5 MYSTERY
    # BOX') prints; a variant number or a price must not. Remove every
    # expected name, then no #N and no $ amount may remain.
    for t in sorted(known, key=len, reverse=True):
        flat = flat.replace(t, ' ')
    a.ok(RE_PRICE_ANY.search(flat) is None, 'pick no prices',
         (re.search(r'.{0,20}\$\s*\d.{0,8}', flat) or [''])[0])
    a.ok(re.search(r'#\s*\d', flat) is None, 'pick no variant numbers',
         (re.search(r'.{0,20}#\s*\d', flat) or [''])[0])
    m = len(pick_texts)
    a.ok(nums == [(i, m) for i in range(1, m + 1)], 'pick page numbering',
         f'{nums} on {m} pages')

def verify(src, out, deep=False, progress=None, brand=None, footer=None,
           prices=True, pick_list=False):
    a = Audit()
    flines = footer_lines(footer or "")
    stripped = {}       # slip page number -> (footer-free body, footer found)
    def body_of(n):
        if n not in stripped:
            stripped[n] = split_footer(slip_body(out_pages[n - 1]), flines)
        return stripped[n][0]
    raw_s, src_ships = load(src)
    raw_o, out_ships = load(out)
    out_pages = pdf_pages(out)

    # ---- structure
    a.ok(len(out_ships) == len(src_ships), 'shipment count',
         f'{len(out_ships)} vs {len(src_ships)}')
    # A shipment is one or more slip pages followed by exactly one label. Dense
    # slips legitimately run to a second page, so the stride is not fixed at 2.
    # Pick pages lead when asked for; anywhere else (or unasked) they break it.
    kinds = ''.join(page_kind(p) for p in out_pages)
    lead = 'P+' if pick_list else ''
    a.ok(re.fullmatch(lead + r'(?:S+B)+', kinds) is not None, 'slip/label grouping',
         kinds_detail(kinds, lead))
    a.ok(kinds.count('B') == len(src_ships), 'label count',
         f"{kinds.count('B')} vs {len(src_ships)} shipments")
    a.ok(len(out_pages) == kinds.count('P') + kinds.count('S') + kinds.count('B'),
         'page count',
         f"{len(out_pages)} vs {kinds.count('P')} pick + {kinds.count('S')} slip"
         f" + {kinds.count('B')} label")
    if pick_list:
        audit_pick(a, raw_s, src_ships,
                   [p for p, k in zip(out_pages, kinds) if k == 'P'],
                   os.path.basename(src))

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
        opage = '\n'.join(body_of(n) for n in opages)

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
        if prices:
            m = RE_TOTAL.search(opage) or re.search(r'(\d+) Items?\s+\$([\d,]+\.\d\d)', opage)
            a.ok(m is not None, f'{tag} total line present')
            if m:
                a.ok(int(m.group(1)) == n, f'{tag} item count', f'{m.group(1)} vs {n}')
                a.ok(abs(float(m.group(2).replace(',', '')) - t) < .005,
                     f'{tag} total', f'{m.group(2)} vs {t:.2f}')
        else:
            cm = RE_OUT_COUNT.findall(opage)
            a.ok(len(cm) == 1, f'{tag} total line present', f'{len(cm)} count lines')
            if len(cm) == 1:
                a.ok(int(cm[0]) == n, f'{tag} item count', f'{cm[0]} vs {n}')
        if sship.get('stated'):
            a.ok(sship['stated'][0] == n, f'{tag} count matches source footer',
                 f'{sship["stated"][0]} vs {n}')
            a.ok(abs(float(sship['stated'][1].replace(',', '')) - t) < .005,
                 f'{tag} total matches source footer',
                 f'{sship["stated"][1]} vs {t:.2f}')

        for v in audit_units(a, tag, gr, opage, prices):
            out_orders[v['order']] = True

        stext = '\n'.join(raw_s[n - 1] for n in spages)
        audit_skus(a, tag, stext, sitems, gr, opage)

    audit_brand(a, brand, [p for p in out_pages if 'Packing Slip' in p])
    slip_nos = [n for n, p in enumerate(out_pages, 1) if 'Packing Slip' in p]
    for n in slip_nos: body_of(n)
    audit_footer(a, footer, [stripped[n][1] for n in slip_nos])
    if not prices:
        # a '$' in a product's own name ('$5 MYSTERY BOX') is not a price: the
        # page's expected name segments (as audit_units checks them) come off
        # before the search
        names = {}
        for k, (_, _, sitems) in enumerate(src_ships):
            segs = [renderable(sg) for e in group_items(sitems)
                    for sg in wrap(display_name(e), NAME_W, 8.5, True)]
            for n in (out_ships[k][0] if k < len(out_ships) else []):
                names[n] = segs
        for n in slip_nos:
            b = renderable(body_of(n))
            for sg in sorted(names.get(n, []), key=len, reverse=True):
                if sg: b = b.replace(sg, ' ')
            leak = RE_PRICE_ANY.search(b) or 'Subtotal' in b
            a.ok(not leak, f'no prices on slip page {n}',
                 (RE_PRICE_ANY.search(b).group(0) if RE_PRICE_ANY.search(b) else 'Subtotal'))

    # ---- no order lost or invented
    a.ok(set(out_orders) == set(src_orders), 'order id set identical',
         f'missing={sorted(set(src_orders)-set(out_orders))[:5]} '
         f'extra={sorted(set(out_orders)-set(src_orders))[:5]}')

    # ---- money
    def money(ships):
        return round(sum(sum(i['price'] for i in items) for _, _, items in ships), 2)
    src_total = money(src_ships)
    if not prices:
        counts = [int(m) for n in slip_nos for m in RE_OUT_COUNT.findall(body_of(n))]
        a.ok(len(counts) == len(src_ships), 'one count line per shipment',
             f'{len(counts)} found vs {len(src_ships)} shipments')
        want = sum(i['qty'] for _, _, items in src_ships for i in items)
        a.ok(sum(counts) == want, 'item total', f'{sum(counts)} vs {want}')
    else:
        found = [m for n in slip_nos
                 for m in [re.search(r'\d+ Items?\s+\$([\d,]+\.\d\d)', body_of(n))] if m]
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
    b.add_argument('--no-prices', action='store_true',
                   help='print slips without prices')
    b.add_argument('--pick-list', action='store_true',
                   help='put a pick list at the front of the PDF')
    v = sub.add_parser('verify', help='audit an existing source/output pair')
    v.add_argument('src'); v.add_argument('out')
    v.add_argument('--deep', action='store_true')
    v.add_argument('--no-brand', action='store_true',
                   help='skip the brand message check; otherwise verify expects '
                        'the currently saved message, so pass this to re-check '
                        'an output built without branding')
    v.add_argument('--no-prices', action='store_true',
                   help='expect an output built with --no-prices',)
    v.add_argument('--pick-list', action='store_true',
                   help='expect an output built with --pick-list')
    args = ap.parse_args()

    try:
        return _run(args)
    except Exception as exc:                 # never leave the caller a bare traceback
        print(f"\nAUDIT ABORTED: {type(exc).__name__}: {exc}")
        return 1

def _run(args):
    brand = footer = None
    prices, pick_list = not args.no_prices, args.pick_list
    if not args.no_brand:
        import branding            # lazily: branding imports this module
        brand = branding.active()
        footer = branding.active_footer()
        for note in branding.load().notes:   # also a footer dropped with the header off
            print(f"branding: {note}")
    if args.cmd == 'build':
        n, nsl, nlb = build(args.src, args.out, brand=brand, footer=footer,
                           prices=prices, pick_list=pick_list)
        size = os.path.getsize(args.out)
        print(f"built {args.out}: {n} shipments, {nsl} slip pages, {nlb} labels, "
              f"{size/1e6:.2f} MB")
        if args.no_verify: return 0
    a = verify(args.src, args.out, deep=args.deep, brand=brand,
               footer=footer, prices=prices, pick_list=pick_list)
    return 0 if a.report('AUDIT') else 1

if __name__ == '__main__':
    sys.exit(main())
