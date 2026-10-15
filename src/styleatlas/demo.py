"""72 demo images in four clearly different procedural styles (watercolour blobs, hard geometric
shapes, line art, halftone dots), to try style-atlas without your own images: `style-atlas demo`
makes them and opens them in the web app.

No artwork by anyone is involved; the README screenshots use these images."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

N = 18
SIZE = 512


def watercolor(rng):
    paper = tuple(int(v) for v in rng.integers(236, 252, 3))
    im = Image.new("RGB", (SIZE, SIZE), paper)
    d = ImageDraw.Draw(im, "RGBA")
    hues = rng.choice(
        np.array(
            [[120, 170, 220], [230, 150, 170], [150, 210, 170], [240, 200, 120],
             [190, 160, 220], [120, 200, 210]]
        ),
        3,
        replace=False,
    )  # fmt: skip
    for _ in range(int(rng.integers(6, 22))):
        c = tuple(int(v) for v in hues[rng.integers(0, 3)]) + (int(rng.integers(45, 95)),)
        x, y = rng.integers(-40, SIZE + 40, 2)
        rx, ry = rng.integers(25, 160, 2)
        d.ellipse([x - rx, y - ry, x + rx, y + ry], fill=c)
    return im.filter(ImageFilter.GaussianBlur(float(rng.uniform(6, 12))))


def geometric(rng):
    im = Image.new("RGB", (SIZE, SIZE), tuple(int(v) for v in rng.integers(10, 50, 3)))
    d = ImageDraw.Draw(im)
    palette = [
        (230, 57, 70),
        (255, 183, 3),
        (33, 158, 188),
        (241, 250, 238),
        (120, 200, 80),
    ]
    for _ in range(int(rng.integers(4, 14))):
        c = palette[rng.integers(0, len(palette))]
        pts = [tuple(int(v) for v in rng.integers(-60, SIZE + 60, 2)) for _ in range(3)]
        d.polygon(pts, fill=c)
    for _ in range(int(rng.integers(0, 5))):
        x, y = rng.integers(0, SIZE - 60, 2)
        d.rectangle(
            [x, y, x + rng.integers(20, 180), y + rng.integers(20, 180)],
            fill=palette[rng.integers(0, len(palette))],
        )
    return im


def lineart(rng):
    im = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    d = ImageDraw.Draw(im)
    petals = int(rng.integers(2, 7))
    for _ in range(int(rng.integers(3, 14))):
        cx, cy = rng.integers(30, SIZE - 30, 2)
        size = rng.uniform(18, 75)
        pts = []
        for t in np.linspace(0, 2 * np.pi, 48):
            r = size + size * 0.6 * np.sin(petals * t + rng.random() * 6)
            pts.append((cx + r * np.cos(t), cy + r * np.sin(t)))
        d.line(pts + [pts[0]], fill=(20, 20, 20), width=int(rng.integers(1, 5)))
    for _ in range(int(rng.integers(0, 4))):  # hatched patches
        x, y = rng.integers(0, SIZE - 120, 2)
        w, h = rng.integers(40, 160, 2)
        gap = int(rng.integers(4, 10))
        for k in range(0, int(w + h), gap):
            d.line([x + k, y, x + k - h, y + h], fill=(30, 30, 30), width=1)
    for _ in range(int(rng.integers(4, 24))):
        x0, y0, x1, y1 = (int(v) for v in rng.integers(0, SIZE, 4))
        d.line([x0, y0, x1, y1], fill=(40, 40, 40), width=1)
    return im


def halftone(rng):
    paper = tuple(int(v) for v in rng.integers(232, 250, 3))
    im = Image.new("RGB", (SIZE, SIZE), paper)
    d = ImageDraw.Draw(im)
    inks = [(30, 60, 140), (200, 40, 60), (20, 20, 20), (30, 120, 90)]
    ink = inks[int(rng.integers(0, len(inks)))]
    step = int(rng.integers(9, 19))
    square = rng.random() < 0.4
    if rng.random() < 0.5:  # radial: one to three dark centres
        centres = rng.integers(0, SIZE, (int(rng.integers(1, 4)), 2))
        reach = rng.uniform(0.25, 0.7, len(centres))

        def level(x, y):
            dist = np.hypot(centres[:, 0] - x, centres[:, 1] - y) / (SIZE * reach)
            return float(np.max(1 - dist))
    else:  # linear: a gradient at a random angle
        a = rng.uniform(0, 2 * np.pi)
        ux, uy = np.cos(a), np.sin(a)

        def level(x, y):
            return 0.5 + ((x - SIZE / 2) * ux + (y - SIZE / 2) * uy) / SIZE

    for y in range(0, SIZE, step):
        for x in range(0, SIZE, step):
            r = max(0.4, step * 0.48 * min(1.0, level(x, y)) + rng.normal(0, 0.3))
            box = [x - r, y - r, x + r, y + r]
            (d.rectangle if square else d.ellipse)(box, fill=ink)
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


def ensure_demo(out: Path, n: int = N) -> int:
    """Make the demo images in `out` unless they are all there; how many were made."""
    expected = [out / name / f"{name}_{1000 + i}.png" for name in STYLES for i in range(n)]
    if all(p.exists() for p in expected):
        return 0
    return len(make_all(out, n))
