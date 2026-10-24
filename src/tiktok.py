"""
TikTok Shop label + packing slip exports: each order is a 4x6 label image on
an A6 page, then its packing slip. Rebuilt the same way as a Whatnot export --
repeated products collapse onto one line keeping every lot number and price,
labels re-interleaved after their slips -- and audited as hard.

The lot number a live auction prints is the Seller SKU column; an all-digit
one becomes '#N' so it reads like a Whatnot variant, anything else is treated
as a SKU and leads the product name in brackets.
"""
import hashlib, os, re, sys, tempfile
from collections import Counter, OrderedDict

from PIL import Image, ImageOps

import whatnot_slips as ws
from whatnot_slips import W, H, M, X_QTY, X_NAME, X_SUB, esc, renderable, sw

NAME = "TikTok Shop"

# The slip's header fields, in TikTok's order. The rebuilt slip prints them
# under the same labels, so the reader below reads source and output alike.
FIELDS = [('order', 'Order ID'), ('created', 'Created Time'),
          ('shipby', 'In transit by'), ('track', 'Tracking number'),
          ('show', 'Show name')]
RE_FIELD = {k: re.compile(r'^\s*' + re.escape(lab) + r':[ \t]*(.*?)\s*$', re.M)
            for k, lab in FIELDS}
RE_BUYER = re.compile(r'Buyer ID:[ \t]*(.*?)\s*$', re.M)
RE_NICK = re.compile(r'Buyer Nickname:[ \t]*(.*?)\s*$', re.M)
RE_QTY_TOTAL = re.compile(r'Qty Total:\s*(\d+)')
# a table row ends in its unit price and qty
RE_ROW_TAIL = re.compile(r'\s{2,}\$([\d,]+\.\d\d)\s+(\d+)\s*$')
RE_CHUNK = re.compile(r'\S+(?: \S+)*')       # text runs split at 2+ spaces

def is_slip(text):
    """A TikTok slip's first page. Continuation pages are found by load()."""
    return ('Packing Slip' in text and 'Seller SKU' in text
            and RE_FIELD['order'].search(text) is not None)

def lot_text(lot):
    """How a lot prints: '#21' for a number, '[MB-7]' for a SKU."""
    if not lot: return 'no #'
    return f'#{lot}' if lot.isdigit() else f'[{lot}]'

def _lot_key(lot):
    return (0, int(lot), '') if lot and lot.isdigit() else (1, 0, (lot or '').upper())

# -------------------------------------------------------------------- parsing
def _columns(header):
    start = header.index('Product Name') + len('Product Name')
    return header.index('SKU', start), header.index('Seller SKU')

def parse_order(pages):
    """-> (info, items) for one order's slip pages."""
    text = '\n'.join(pages)
    info = {k: (m.group(1) if (m := rx.search(text)) else '') for k, rx in RE_FIELD.items()}
    info['buyer'] = m.group(1) if (m := RE_BUYER.search(text)) else ''
    info['nick'] = m.group(1) if (m := RE_NICK.search(text)) else ''
    info['stated'] = int(m.group(1)) if (m := RE_QTY_TOTAL.search(text)) else None

    items, cols, pending = [], None, []
    for ln in text.split('\n'):
        if 'Product Name' in ln and 'Seller SKU' in ln:
            cols = _columns(ln); continue
        if cols is None: continue
        if RE_QTY_TOTAL.search(ln): break
        s = ln.strip()
        if (not s or s in ('(Unit)', 'SKU Price') or 'Packing Slip' in ln
                or any(rx.match(ln) for rx in RE_FIELD.values())):
            continue
        sku_col, seller_col = cols
        tail = RE_ROW_TAIL.search(ln)
        left = ln[:tail.start()] if tail else ln
        # pdftotext places a column a few characters either side of its
        # header, line by line, so the header only says where the name ends;
        # after it come SKU then Seller SKU, either of which may be blank
        name, codes = [], []
        for c in RE_CHUNK.finditer(left):
            (name if c.start() < sku_col - 1 and not codes else codes).append(c)
        if len(codes) == 1:
            near_seller = abs(codes[0].start() - seller_col) < abs(codes[0].start() - sku_col)
            sku, seller = ([], [codes[0].group()]) if near_seller else ([codes[0].group()], [])
        else:
            sku, seller = [c.group() for c in codes[:1]], [c.group() for c in codes[1:]]
        name = [c.group() for c in name]
        if tail:
            qty, unit = int(tail.group(2)), float(tail.group(1).replace(',', ''))
            lot = ' '.join(seller) or ' '.join(sku) or None
            items.append(dict(tname=' '.join(pending + name), lot=lot, qty=qty,
                              unit=unit, price=round(unit * qty, 2),
                              order=f"{info['order']}/{len(items)}"))
            pending = []
        elif items:                     # a wrapped name (or lot) continues
            if name: items[-1]['tname'] += ' ' + ' '.join(name)
            if seller: items[-1]['lot'] = (items[-1]['lot'] or '') + ''.join(seller)
        else:
            pending += name
    for it in items:                    # the shape the shared renderer takes
        it['tname'] = ws.clean(it['tname'])
        numbered = bool(it['lot']) and it['lot'].isdigit()
        it['name'] = f"{it['tname']} #{it['lot']}" if numbered else it['tname']
        it['sku'] = None if numbered else it['lot']
    return info, items

def load(pdf):
    """-> (raw page texts, [(slip_page_numbers, info, items)]). Each order is
    its label page then one or more slip pages, the last of which carries
    'Qty Total:'. info['label'] is the label's page number."""
    pages = ws.pdf_pages(pdf)
    orders, i, used = [], 0, set()
    while i < len(pages):
        if not is_slip(pages[i]):
            i += 1; continue
        if i == 0 or is_slip(pages[i - 1]) or (i - 1) in used:
            raise ValueError(f"TikTok export: the slip on page {i + 1} has no label before it")
        group = [i]
        while not RE_QTY_TOTAL.search(pages[group[-1]]):
            nxt = group[-1] + 1
            if nxt >= len(pages) or is_slip(pages[nxt]):
                raise ValueError(f"TikTok export: the slip on page {i + 1} never ends")
            group.append(nxt)
        info, items = parse_order([pages[n] for n in group])
        info['label'] = i                   # 1-based: the page before the slip
        used.update([i - 1, *group])
        orders.append(([n + 1 for n in group], info, items))
        i = group[-1] + 1
    stray = [n + 1 for n in range(len(pages)) if n not in used]
    if stray:
        raise ValueError(f"TikTok export: page(s) {stray[:5]} belong to no order")
    if not orders:
        raise ValueError("TikTok export: no packing slips found")
    return pages, orders

# --------------------------------------------------------------------- labels
def label_bitmap(pdf, pageno, tmpdir):
    """The label on `pageno` as a 1-bit 4x6 image at 300 dpi, or None if blank.

    TikTok's page is A6, not 4x6: the 2:3 label artwork sits inside it with a
    margin. Stretching the page to 4x6 would squash the label (and barcode)
    by 6%, so the artwork is cut out, padded with white to exactly 2:3 if its
    ink stops short of an edge, and scaled evenly."""
    for f in os.listdir(tmpdir):
        if f.startswith('T'): os.remove(os.path.join(tmpdir, f))
    ws._spawn([ws._bin('pdftoppm'), '-r', str(ws.LABEL_DPI), '-gray',
               '-f', str(pageno), '-l', str(pageno), pdf, os.path.join(tmpdir, 'T')])
    cand = [f for f in os.listdir(tmpdir) if f.startswith('T')]
    if not cand: return None
    im = Image.open(os.path.join(tmpdir, cand[0])).convert('L')
    box = ImageOps.invert(im).point(lambda p: 255 if p >= 128 else 0).getbbox()
    if box is None: return None
    im = im.crop(box)
    w, h = im.size
    if w * 3 > h * 2: tw, th = w, round(w * 1.5)
    else:             tw, th = round(h * 2 / 3), h
    if (tw, th) != (w, h):
        pad = Image.new('L', (tw, th), 255)
        pad.paste(im, ((tw - w) // 2, (th - h) // 2)); im = pad
    size = (round(4 * ws.LABEL_DPI), round(6 * ws.LABEL_DPI))
    return ws._to_1bit(im.resize(size, Image.LANCZOS))

# ------------------------------------------------------------------ rendering
HDR_X = M + 68                          # where header values start
def _fit(txt, width, size, bold, floor=5.0):
    while size > floor and sw(txt, size, bold) > width: size -= 0.5
    return size

def slip_ps(info, grouped, brand=None, footer=None, prices=True):
    blocks = ws.build_rows(grouped, prices)
    n = sum(e['qty'] for e in grouped); tot = sum(e['subtotal'] for e in grouped)
    d = ws.BAND if brand else 0
    fl = ws.footer_lines(footer or "")
    u = ws.FOOT_BAND if fl else 0
    TOP_Y, BOT_Y = H - 116 - d, 74.0 + u
    pages, cur, y = [], [], TOP_Y
    for b in blocks:
        need = sum(h for h, _ in b) + 3
        if y - need < BOT_Y and cur:
            pages.append(cur); cur = []; y = TOP_Y
        cur.append(b); y -= need
    pages.append(cur)
    buyer = [f"Buyer ID: {renderable(info['buyer'])}",
             f"Buyer Nickname: {renderable(info['nick'])}".rstrip()]
    out = []
    for pi, pg in enumerate(pages, 1):
        s = list(ws.PS_PROLOG)
        A = s.append
        if brand:
            A("0 setgray"); s.extend(ws.brand_ops(brand, pi, len(pages)))
        else:
            A(f"11 HB 0 setgray (TikTok Packing Slip) {M} {H-26} L")
            A(f"8 HV ({pi}/{len(pages)}) {W-M} {H-26} R")
        A(f"0.8 setlinewidth {M} {H-33-d} moveto {W-M} {H-33-d} lineto stroke")
        for k, (key, lab) in enumerate(FIELDS):
            y = H - 46 - d - 9 * k
            val = renderable(info[key])
            A(f"7.5 HB ({esc(lab)}:) {M} {y} L")
            A(f"{_fit(val, W - M - HDR_X, 7.5, False)} HV ({esc(val)}) {HDR_X} {y} L")
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
        for k, ln in enumerate(buyer):
            A(f"{_fit(ln, W - 2 * M, 9, True)} HB ({esc(ln)}) {W-M} {34 + u - 12 * k} R")
        if fl:      # split_footer() relies on this being the lowest text on the page
            A(f"0.5 setlinewidth {M} 40 moveto {W-M} 40 lineto stroke")
            for k, ln in enumerate(fl):
                A(f"{ws.FOOT_SIZE} HV ({esc(ln)}) {(W - sw(ln, ws.FOOT_SIZE)) / 2:.1f} "
                  f"{29 - ws.FOOT_LEAD * k} L")
        A("showpage")
        out.append("\n".join(s) + "\n")
    return out

# ------------------------------------------------------------------ pick list
PICK_ROW = 14
PICK_COLW = (W - 2 * M) / 2
PICK_LOT_W = 35                          # '#140' at 10.5 pt bold, plus a gap
PICK_WHO_W = PICK_COLW - 11 - PICK_LOT_W - 8
PICK_SUB_TAIL = " · {} orders · {} items"

def pick_who(info):
    """Whose bag a lot goes in: the nickname, else the buyer ID, cut to fit
    its column. The audit reuses this on purpose, like pick_src_label: it is
    cosmetic, and a lot paired with the wrong buyer still fails."""
    who = ws._defuse(renderable(info['nick']) or renderable(info['buyer']) or '?')
    if sw(who, 8) <= PICK_WHO_W: return who
    while who and sw(who + '...', 8) > PICK_WHO_W: who = who[:-1]
    return who.rstrip() + '...'

def pick_lot(lot, qty):
    return lot_text(lot) + (f" ×{qty}" if qty > 1 else '')

def pick_groups(orders):
    """-> [(show, [(lot, qty, who)])], the busiest show first, lots in order."""
    shows = OrderedDict()
    for _, info, items in orders:
        for it in items:
            shows.setdefault(info['show'], []).append((it['lot'], it['qty'], pick_who(info)))
    return [(show, sorted(rows, key=lambda r: (_lot_key(r[0]), r[2])))
            for show, rows in sorted(shows.items(),
                                     key=lambda kv: (-sum(q for _, q, _ in kv[1]), kv[0]))]

def show_line(show, rows):
    nb = len({who for _, _, who in rows}); ni = sum(q for _, q, _ in rows)
    return (f"{ws._defuse(renderable(show)) or 'No show name'} · "
            f"{nb} buyer{'s' if nb != 1 else ''} · {ni} item{'s' if ni != 1 else ''}")

def pick_ps(orders, src_name):
    groups = pick_groups(orders)
    nitems = sum(q for _, rows in groups for _, q, _ in rows)
    nlots = sum(len(rows) for _, rows in groups)
    pages, pg = [], []
    top1, top, floor = H - 58, H - 50, 30
    y, col = top1, 0
    def newpage():
        nonlocal pg, y, col
        pages.append(pg); pg = []; y = top; col = 0
    for show, rows in groups:
        if col == 1: y -= PICK_ROW; col = 0
        if y - 2 * PICK_ROW < floor: newpage()
        y -= 4
        pg.append(f"0.5 setlinewidth {M} {y+9:.1f} moveto {W-M} {y+9:.1f} lineto stroke")
        pg.append(f"8 HB ({esc(show_line(show, rows))}) {M} {y:.1f} L")
        y -= PICK_ROW + 2
        for lot, qty, who in rows:
            if y < floor: newpage()
            x = M + col * PICK_COLW
            lt = pick_lot(lot, qty)
            pg.append(f"0.6 setlinewidth {x:.1f} {y-1:.1f} 7 7 rectstroke")
            pg.append(f"{_fit(lt, PICK_LOT_W - 3, 10.5, True)} HB ({esc(lt)}) {x+11:.1f} {y:.1f} L")
            pg.append(f"8 HV ({esc(who)}) {x + 11 + PICK_LOT_W:.1f} {y:.1f} L")
            col ^= 1
            if col == 0: y -= PICK_ROW
    if col == 1: y -= PICK_ROW
    if y - 14 < floor: newpage()
    tail = f"{nlots} lot{'s' if nlots != 1 else ''} · {nitems} item{'s' if nitems != 1 else ''}"
    pg.append(f"0.8 setlinewidth {M} {y+6:.1f} moveto {W-M} {y+6:.1f} lineto stroke")
    pg.append(f"9 HB ({esc(tail)}) {M} {y-6:.1f} L")
    pages.append(pg)
    out = []
    for i, body in enumerate(pages, 1):
        s = list(ws.PS_PROLOG)
        s.append(f"11 HB 0 setgray (Pick List {i}/{len(pages)}) {M} {H-26} L")
        s.append(f"0.8 setlinewidth {M} {H-33} moveto {W-M} {H-33} lineto stroke")
        if i == 1:
            sub = ws.pick_src_label(src_name) + PICK_SUB_TAIL.format(len(orders), nitems)
            s.append(f"7 HV ({esc(sub)}) {M} {H-45} L")
        s += body
        s.append("showpage")
        out.append("\n".join(s) + "\n")
    return out

# ---------------------------------------------------------------------- build
def build(src, out, quiet=False, progress=None, brand=None, footer=None,
          prices=True, pick_list=False, condense=True):
    raw, data = load(src)
    ps = [ws.PS_HEAD + (ws.logo_prolog(brand.logo) if brand and brand.logo is not None else "")]
    nsl = nlb = 0
    if pick_list:
        ps += pick_ps(data, os.path.basename(src))
    with tempfile.TemporaryDirectory() as td:
        for i, (pages, info, items) in enumerate(data):
            sp = slip_ps(info, ws.grouping(items, condense), brand, footer, prices)
            ps += sp; nsl += len(sp)
            im = label_bitmap(src, info['label'], td)
            if im is not None: ps.append(ws.label_ps(im)); nlb += 1
            if progress:
                progress(i + 1, len(data), "building slips")
            elif not quiet and sys.stderr.isatty():
                print(f"\r  rendering {i+1}/{len(data)}", end='', file=sys.stderr, flush=True)
    if not progress and not quiet and sys.stderr.isatty():
        print(file=sys.stderr)
    ws.write_pdf(ps, out)
    return len(data), nsl, nlb

# --------------------------------------------------------------------- verify
# The auditor's own reading of a source slip. A row is split from the right
# -- qty, unit price, seller SKU, SKU -- where the parser goes by header
# column; the two must agree, so a column misread fails here.
def raw_rows(text):
    """-> [(first name text, lot, unit price, qty)] for every priced line."""
    rows = []
    for ln in text.split('\n'):
        if not RE_ROW_TAIL.search(ln): continue
        ch = RE_CHUNK.findall(ln)
        qty, price = int(ch[-1]), float(ch[-2].lstrip('$').replace(',', ''))
        lot = ch[-3] if len(ch) >= 4 else None
        name = ' '.join(ch[:-4] if len(ch) >= 5 else ch[:-3])
        rows.append((name, lot, price, qty))
    return rows

def header_words(text):
    """Every word of the five header fields, read straight off the lines."""
    return Counter(renderable(' '.join(
        m.group(0) for rx in RE_FIELD.values() for m in [rx.search(text)] if m)).split())

def slip_body(text):
    """From the header's 'Order ID:' line down: a branded band above it holds
    the user's free text, which no fact check may read."""
    lines = text.split('\n')
    for i in range(len(lines) - 1, -1, -1):
        if RE_FIELD['order'].match(lines[i]):
            return '\n'.join(lines[i:])
    return text

RE_PICK_LOT = re.compile(r'(?:(?<=\s)|^)(#\d+|\[[^\]]+\]|no #)( ×(\d+))?\s+')
RE_PICK_SHOW = re.compile(r'^\s*(.+?) · (\d+) buyers? · (\d+) items?\s*$')
RE_PICK_TAIL = re.compile(r'^\s*(\d+) lots? · (\d+) items?\s*$')
RE_PICK_SUB = re.compile(r'· (\d+) orders? · (\d+) items?\s*$')

def read_pick(pick_texts):
    """-> ([(show, lot text, qty, who)], [show lines], tails, page nums, subs)."""
    rows, shows, tails, nums, subs, show = [], [], [], [], [], None
    for t in pick_texts:
        lines = [ln for ln in t.split('\n') if ln.strip()]
        if lines and (m := ws.RE_PICK_NUM.match(lines[0])):
            nums.append((int(m.group(1)), int(m.group(2)))); lines = lines[1:]
        for ln in lines:
            if (m := RE_PICK_TAIL.match(ln)):
                tails.append((int(m.group(1)), int(m.group(2)))); continue
            if not shows and (m := RE_PICK_SUB.search(ln)):
                subs.append((int(m.group(1)), int(m.group(2)))); continue
            if (m := RE_PICK_SHOW.match(ln)):
                show = renderable(m.group(1))
                shows.append((show, int(m.group(2)), int(m.group(3)))); continue
            hits = list(RE_PICK_LOT.finditer(ln))
            if not hits:
                rows.append((show, None, None, renderable(ln))); continue
            for k, h in enumerate(hits):
                end = hits[k + 1].start() if k + 1 < len(hits) else len(ln)
                rows.append((show, h.group(1), int(h.group(3) or 1),
                             renderable(ln[h.end():end])))
    return rows, shows, tails, nums, subs

def audit_pick(a, raw_src, src_orders, pick_texts, src_name=''):
    """Every lot of every show against the raw slips: right buyer, right
    show, in lot order, nothing missing or invented, no money."""
    want = OrderedDict()
    for spages, _, _ in src_orders:
        text = '\n'.join(raw_src[n - 1] for n in spages)
        show = renderable(m.group(1)) if (m := RE_FIELD['show'].search(text)) else ''
        who = pick_who(dict(nick=m.group(1) if (m := RE_NICK.search(text)) else '',
                            buyer=m.group(1) if (m := RE_BUYER.search(text)) else ''))
        for _, lot, _, qty in raw_rows(text):
            want.setdefault(show, []).append((lot_text(lot), qty, who, lot))
    exp = []
    for show, rows in sorted(want.items(), key=lambda kv: (-sum(r[1] for r in kv[1]), kv[0])):
        for lt, q, who, lot in sorted(rows, key=lambda r: (_lot_key(r[3]), r[2])):
            exp.append((ws._defuse(show) or 'No show name', lt, q, who))
    rows, shows, tails, nums, subs = read_pick(pick_texts)
    got = [(s, lt, q, who) for s, lt, q, who in rows]
    a.ok(Counter(got) == Counter(exp), 'pick rows',
         f'missing={list((Counter(exp) - Counter(got)).elements())[:3]} '
         f'extra={list((Counter(got) - Counter(exp)).elements())[:3]}')
    # two columns read left to right, row by row, give the lot order back
    a.ok(got == exp, 'pick row order',
         next((f'row {i+1}: {g} vs {w}' for i, (g, w) in enumerate(zip(got, exp)) if g != w),
              f'{len(got)} vs {len(exp)} rows'))
    eshows = []
    for show, rows_ in sorted(want.items(), key=lambda kv: (-sum(r[1] for r in kv[1]), kv[0])):
        eshows.append((renderable(ws._defuse(show)) or 'No show name',
                       len({r[2] for r in rows_}), sum(r[1] for r in rows_)))
    a.ok(shows == eshows, 'pick show headings', f'{shows} vs {eshows}')
    total = sum(r[2] for r in exp)
    a.ok(tails == [(len(exp), total)], 'pick totals line', f'{tails} vs {[(len(exp), total)]}')
    a.ok(subs == [(len(src_orders), total)], 'pick subtitle counts',
         f'{subs} vs {(len(src_orders), total)}')
    stated = [info.get('stated') for _, info, _ in src_orders]
    if all(s is not None for s in stated):
        a.ok(total == sum(stated), 'pick items match source Qty Totals',
             f'{total} vs {sum(stated)}')
    flat = renderable('\n'.join(pick_texts))
    if renderable(ws.pick_src_label(src_name)):
        flat = flat.replace(renderable(ws.pick_src_label(src_name)), ' ', 1)
    for _, _, _, who in exp:
        flat = flat.replace(who, ' ')
    for show, _, _ in eshows:
        flat = flat.replace(show, ' ')
    a.ok(ws.RE_PRICE_ANY.search(flat) is None, 'pick no prices',
         (re.search(r'.{0,20}\$\s*\d.{0,8}', flat) or [''])[0])
    m = len(pick_texts)
    a.ok(nums == [(i, m) for i in range(1, m + 1)], 'pick page numbering',
         f'{nums} on {m} pages')

def verify(src, out, deep=False, progress=None, brand=None, footer=None,
           prices=True, pick_list=False, condense=True):
    a = ws.Audit()
    flines = ws.footer_lines(footer or "")
    raw_s, src_orders = load(src)
    out_pages = ws.pdf_pages(out)
    stripped = {}       # page number -> (footer-free body, footer found)
    def body_of(n):
        if n not in stripped:
            body, found = ws.split_footer(out_pages[n - 1], flines)
            stripped[n] = (slip_body(body), found)
        return stripped[n][0]

    # ---- structure: [pick] then per order its slip page(s) and one label
    kinds = ''.join(ws.page_kind(p) for p in out_pages)
    lead = 'P+' if pick_list else ''
    a.ok(re.fullmatch(lead + r'(?:S+B)+', kinds) is not None, 'slip/label grouping',
         ws.kinds_detail(kinds, lead))
    a.ok(kinds.count('B') == len(src_orders), 'label count',
         f"{kinds.count('B')} vs {len(src_orders)} orders")
    runs = [[m.start() + 1 + j for j in range(len(m.group()))]
            for m in re.finditer(r'S+', kinds)]
    a.ok(len(runs) == len(src_orders), 'order count', f'{len(runs)} vs {len(src_orders)}')
    if pick_list:
        audit_pick(a, raw_s, src_orders,
                   [p for p, k in zip(out_pages, kinds) if k == 'P'], os.path.basename(src))

    src_lines, out_lines = {}, {}
    for spages, info, items in src_orders:
        for it in items: src_lines[it['order']] = it

    # ---- per order
    for k, (spages, info, items) in enumerate(src_orders):
        tag = f"order {k} ({info.get('order')})"
        opages = runs[k] if k < len(runs) else []
        if not a.ok(bool(opages), f'{tag} slip present'):
            continue
        stext = '\n'.join(raw_s[n - 1] for n in spages)
        otext = '\n'.join(out_pages[n - 1] for n in opages)
        opage = '\n'.join(body_of(n) for n in opages)

        # the right slip in the right place: the order ID ties them
        a.present(info.get('order', ''), opage, f'{tag} order id')
        missing = header_words(stext) - header_words(opage)
        a.ok(bool(header_words(stext)) and not missing, f'{tag} header words',
             ' '.join(sorted(missing))[:60] or 'no header found')
        for key in ('created', 'shipby', 'track', 'show'):
            a.present(renderable(info.get(key, '')), renderable(opage), f'{tag} {key}')
        sb = renderable(m.group(1)) if (m := RE_BUYER.search(stext)) else ''
        sn = renderable(m.group(1)) if (m := RE_NICK.search(stext)) else ''
        a.present(f'Buyer ID: {sb}' if sb else '', renderable(opage), f'{tag} buyer id')
        if sn:
            a.present(f'Buyer Nickname: {sn}', renderable(opage), f'{tag} buyer nickname')

        # the parser against the auditor's own reading of the rows
        rr = raw_rows(stext)
        a.ok(Counter((lot, p, q) for _, lot, p, q in rr) ==
             Counter((it['lot'], it['unit'], it['qty']) for it in items),
             f'{tag} rows parsed', f'{len(items)} parsed vs {len(rr)} in source')
        # a set, not a count: a condensed slip prints a repeated name once
        nwords = set(renderable(' '.join(n for n, _, _, _ in rr)).split())
        lost = nwords - set(renderable(opage).split())
        a.ok(not lost, f'{tag} product words', ' '.join(sorted(lost))[:60])

        # totals
        gr = ws.grouping(items, condense)
        n = sum(q for _, _, _, q in rr)
        t = round(sum(p * q for _, _, p, q in rr), 2)
        if info.get('stated') is not None:
            a.ok(info['stated'] == n, f'{tag} count matches source Qty Total',
                 f"{info['stated']} vs {n}")
        if prices:
            m = re.search(r'(\d+) Items?\s+\$([\d,]+\.\d\d)', opage)
            if a.ok(m is not None, f'{tag} total line present'):
                a.ok(int(m.group(1)) == n, f'{tag} item count', f'{m.group(1)} vs {n}')
                a.ok(abs(float(m.group(2).replace(',', '')) - t) < .005,
                     f'{tag} total', f'{m.group(2)} vs {t:.2f}')
        else:
            cm = ws.RE_OUT_COUNT.findall(opage)
            if a.ok(len(cm) == 1, f'{tag} total line present', f'{len(cm)} count lines'):
                a.ok(int(cm[0]) == n, f'{tag} item count', f'{cm[0]} vs {n}')
            b = renderable(opage)
            for e in gr:
                for sg in ws.wrap(ws.display_name(e), ws.NAME_W, 8.5, True):
                    if renderable(sg): b = b.replace(renderable(sg), ' ')
            leak = ws.RE_PRICE_ANY.search(b)
            a.ok(not leak and 'Subtotal' not in b, f'{tag} no prices on slip',
                 leak.group(0) if leak else 'Subtotal')
        for v in ws.audit_units(a, tag, gr, opage, prices):
            out_lines[v['order']] = True
        a.ok('Packing Slip' in otext, f'{tag} slip marked')

    slips = [n for n, kd in enumerate(kinds, 1) if kd == 'S']
    ws.audit_brand(a, brand, [out_pages[n - 1] for n in slips])
    for n in slips: body_of(n)
    ws.audit_footer(a, footer, [stripped[n][1] for n in slips])

    a.ok(set(out_lines) == set(src_lines), 'line set identical',
         f'missing={sorted(set(src_lines) - set(out_lines))[:5]} '
         f'extra={sorted(set(out_lines) - set(src_lines))[:5]}')

    # ---- labels: cut and scaled the same way, compared pixel for pixel
    if deep:
        with tempfile.TemporaryDirectory() as td:
            for k, (spages, info, _) in enumerate(src_orders):
                if k >= len(runs): break
                si = label_bitmap(src, info['label'], td)
                oi = ws.embedded_bitmap(out, runs[k][-1] + 1, td)
                if not a.ok(si is not None and oi is not None, f'order {k} label present'):
                    continue
                a.ok(not ws.is_blank(si), f'order {k} source label not blank', info.get('track', ''))
                a.ok(not ws.is_blank(oi), f'order {k} label not blank', info.get('track', ''))
                a.ok(si.size == oi.size, f'order {k} label size', f'{si.size} vs {oi.size}')
                a.ok(hashlib.sha256(si.tobytes()).digest() ==
                     hashlib.sha256(oi.tobytes()).digest(),
                     f'order {k} label pixels identical', f"{info.get('order')} {info.get('track')}")
                if progress:
                    progress(k + 1, len(src_orders), "checking labels")
                elif sys.stderr.isatty():
                    print(f"\r  checking label {k+1}/{len(src_orders)}", end='',
                          file=sys.stderr, flush=True)
            if not progress and sys.stderr.isatty(): print(file=sys.stderr)
    return a
