"""Draw the program icon (src/styleatlas/data/style-atlas.ico): three overlapping style
groups, in the map's first three group colours, on the map's dark background.

    python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024  # drawn large, then scaled down for every icon size
BG = (13, 15, 18, 255)  # the map's --bg
GROUPS = [  # centre x, centre y, radius (share of SIZE), colour (map.js PALETTE)
    (0.39, 0.41, 0.22, (242, 153, 74)),
    (0.62, 0.43, 0.19, (86, 204, 242)),
    (0.50, 0.64, 0.20, (187, 107, 217)),
]
OUT = Path(__file__).resolve().parents[1] / "src" / "styleatlas" / "data" / "style-atlas.ico"


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=210, fill=BG)
    for cx, cy, r, colour in GROUPS:
        layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        box = (
            int((cx - r) * SIZE),
            int((cy - r) * SIZE),
            int((cx + r) * SIZE),
            int((cy + r) * SIZE),
        )
        ImageDraw.Draw(layer).ellipse(box, fill=(*colour, 215))
        img = Image.alpha_composite(img, layer)
    return img


def main() -> None:
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw().resize((256, 256), Image.Resampling.LANCZOS).save(OUT, sizes=sizes)
    print(OUT)


if __name__ == "__main__":
    main()
