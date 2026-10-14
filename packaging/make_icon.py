"""Draw the app icon: a 4x6 shipping label on a fanned stack (many labels,
condensed into one) on a teal rounded square. Writes the window icons into
src/assets/ and the .ico/.icns the Windows and Mac builds stamp on the app.
The output is committed; rerun only to change the design."""
import pathlib
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEAL = (0, 137, 123)
INK, GREY = (25, 32, 44), (150, 160, 175)
N = 1024                                   # drawn big, scaled down for each size

def draw():
    s = N / 256                            # the design lives on a 256 grid
    R = lambda *v: [c * s for c in v]
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle(R(8, 8, 248, 248), radius=56 * s, fill=TEAL)
    for dx, alpha in ((-26, 90), (-13, 150)):          # the stack behind
        d.rounded_rectangle(R(84 + dx, 44 + abs(dx) * .6, 192 + dx, 212 - abs(dx) * .6),
                            radius=10 * s, fill=(255, 255, 255, alpha))
    d.rounded_rectangle(R(92, 40, 200, 216), radius=12 * s, fill="white")
    d.rounded_rectangle(R(106, 56, 186, 66), radius=4 * s, fill=INK)
    for y, x1 in ((80, 172), (94, 160), (108, 172)):
        d.rounded_rectangle(R(106, y, x1, y + 6), radius=3 * s, fill=GREY)
    x = 106
    for w in (4, 2, 6, 2, 3, 5, 2, 4, 2, 6, 3, 2, 5, 3, 2, 4):   # barcode
        d.rectangle(R(x, 156, x + w, 198), fill=INK); x += w + 2.2
    return im

def main():
    im = draw()
    size = lambda z: im.resize((z, z), Image.LANCZOS)
    assets = ROOT / "src" / "assets"; assets.mkdir(exist_ok=True)
    size(256).save(assets / "icon-256.png", optimize=True)
    size(32).save(assets / "icon-32.png", optimize=True)
    icons = ROOT / "packaging" / "icons"; icons.mkdir(exist_ok=True)
    size(256).save(icons / "label-condense.ico",
                   sizes=[(z, z) for z in (16, 24, 32, 48, 64, 128, 256)])
    im.save(icons / "label-condense.icns")
    print(f"icons written to {assets} and {icons}")

if __name__ == "__main__":
    main()
