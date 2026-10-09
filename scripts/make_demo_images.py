"""Make 72 demo images in four clearly different procedural styles (watercolour blobs, hard
geometric shapes, line art, halftone dots), to try style-atlas without your own images:

    python scripts/make_demo_images.py demo_styles
    style-atlas serve demo_styles

No artwork by anyone is involved; the README screenshots use these images."""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

N = 18
SIZE = 512


def watercolor(rng):
    im = Image.new("RGB", (SIZE, SIZE), (250, 246, 238))
    d = ImageDraw.Draw(im, "RGBA")
    hues = rng.choice(
        np.array([[120, 170, 220], [230, 150, 170], [150, 210, 170], [240, 200, 120]]),
        3,
    )
    for _ in range(14):
        c = tuple(int(v) for v in hues[rng.integers(0, 3)]) + (70,)
        x, y, r = rng.integers(0, SIZE), rng.integers(0, SIZE), rng.integers(40, 140)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    return im.filter(ImageFilter.GaussianBlur(9))


def geometric(rng):
    im = Image.new("RGB", (SIZE, SIZE), tuple(int(v) for v in rng.integers(10, 40, 3)))
    d = ImageDraw.Draw(im)
    palette = [(230, 57, 70), (255, 183, 3), (33, 158, 188), (241, 250, 238)]
    for _ in range(10):
        c = palette[rng.integers(0, 4)]
        pts = [tuple(int(v) for v in rng.integers(0, SIZE, 2)) for _ in range(3)]
        d.polygon(pts, fill=c)
        x, y = rng.integers(0, SIZE - 80, 2)
        d.rectangle(
            [x, y, x + rng.integers(30, 140), y + rng.integers(30, 140)],
            fill=palette[rng.integers(0, 4)],
        )
    return im


def lineart(rng):
    im = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for _ in range(9):
        cx, cy = rng.integers(60, SIZE - 60, 2)
        pts = []
        for t in np.linspace(0, 2 * np.pi, 40):
            r = 40 + 25 * np.sin(3 * t + rng.random() * 6)
            pts.append((cx + r * np.cos(t), cy + r * np.sin(t)))
        d.line(pts + [pts[0]], fill=(20, 20, 20), width=int(rng.integers(2, 5)))
    for _ in range(12):
        x0, y0, x1, y1 = (int(v) for v in rng.integers(0, SIZE, 4))
        d.line([x0, y0, x1, y1], fill=(40, 40, 40), width=1)
    return im


def halftone(rng):
    im = Image.new("RGB", (SIZE, SIZE), (245, 240, 225))
    d = ImageDraw.Draw(im)
    ink = [(30, 60, 140), (200, 40, 60)][int(rng.integers(0, 2))]
    cx, cy = rng.integers(100, SIZE - 100, 2)
    for y in range(0, SIZE, 14):
        for x in range(0, SIZE, 14):
            dist = np.hypot(x - cx, y - cy) / SIZE
            r = max(0.5, 6.5 * (1 - dist * 1.6) + rng.normal(0, 0.4))
            d.ellipse([x - r, y - r, x + r, y + r], fill=ink)
    return im


STYLES = {
    "watercolor": watercolor,
    "geometric": geometric,
    "lineart": lineart,
    "halftone": halftone,
}


def make_all(out: Path, n: int = N) -> list[Path]:
    """`n` images per style in out/<style>/; the same images on every run."""
    made = []
    for name, draw in STYLES.items():
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            rng = np.random.default_rng(list(STYLES).index(name) * 1000 + i)
            path = folder / f"{name}_{1000 + i}.png"
            draw(rng).save(path)
            made.append(path)
    return made


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_styles")
    print("made", len(make_all(out)), "images in", out)
