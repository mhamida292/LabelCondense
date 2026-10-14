"""Vendor the Sun Valley ttk theme into src/assets/sv/ with its blue accent
recoloured to the app's teal. Run after upgrading sv-ttk (pip install sv-ttk);
the output is committed, so builds and the app never need sv-ttk itself."""
import colorsys, importlib.metadata as md, pathlib, shutil
import sv_ttk
from PIL import Image

OUT = pathlib.Path(__file__).resolve().parent.parent / "src" / "assets" / "sv"
# sv-ttk's accent in each mode -> ours. selbg is the text-selection colour.
ACCENT = {"light": ("#005fb8", "#00796b"), "dark": ("#57c8ff", "#4fd8c4")}
SELBG = "#2f60d8"

def hsv(h):
    return colorsys.rgb_to_hsv(*(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)))

def recolour(png, src, dst):
    """Shift every strongly coloured pixel near the source hue to the target,
    keeping its relative shading, so hover/pressed variants stay distinct."""
    sh, ss, sv = hsv(src); th, ts, tv = hsv(dst)
    im = Image.open(png).convert("RGBA"); px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if a and s > .35 and abs(h - sh) < .08:
                r, g, b = colorsys.hsv_to_rgb(th, min(1, s * ts / ss), min(1, v * tv / sv))
                px[x, y] = (round(r * 255), round(g * 255), round(b * 255), a)
    im.save(png, optimize=True)

def main():
    src = pathlib.Path(sv_ttk.__file__).parent
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(src, OUT, ignore=shutil.ignore_patterns("*.py", "*.pyc", "__pycache__", "py.typed"))
    lic = next(f for f in md.distribution("sv-ttk").files if f.name.upper().startswith("LICENSE"))
    shutil.copy(lic.locate(), OUT / "LICENSE")
    for mode, (old, new) in ACCENT.items():
        recolour(OUT / "theme" / f"spritesheet_{mode}.png", old, new)
        tcl = OUT / "theme" / f"{mode}.tcl"
        tcl.write_text(tcl.read_text().replace(old, new).replace(SELBG, new))
    print(f"sv-ttk {md.version('sv-ttk')} vendored into {OUT}")

if __name__ == "__main__":
    main()
