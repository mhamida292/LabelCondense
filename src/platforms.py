"""Which marketplace an export came from. Each platform module has the same
build() and verify(); callers detect once and use the module it names."""
import whatnot_slips as ws
import tiktok

NAMES = {'whatnot': 'Whatnot', 'tiktok': tiktok.NAME}

class UnknownExport(ValueError):
    pass

UNKNOWN = ("This PDF isn't a Whatnot or TikTok Shop export, "
           "or its layout has changed.")

def detect_pages(pages):
    """'whatnot' or 'tiktok' from the page texts. A file that looks like both,
    or neither, is refused rather than guessed at."""
    wn = any(ws.is_slip(p) for p in pages)
    tt = any(tiktok.is_slip(p) for p in pages)
    if wn == tt:
        raise UnknownExport(UNKNOWN)
    return 'tiktok' if tt else 'whatnot'

def detect(pdf):
    return detect_pages(ws.pdf_pages(pdf))

def module(kind):
    return {'whatnot': ws, 'tiktok': tiktok}[kind]
