"""Opening an image and cutting the model's input squares, without torch.

With a GPU the model waits for the images, and threads of one process take turns at this work
(the GIL), so it runs in worker processes there; those import only this module's light
dependencies. Measured 2026-10-20 on an RTX 3090 with the program's 8 CPUs, 720 PNGs: threads
46 images/s, worker processes 53. On the CPU the model is the slow part and threads do. The
squares come back as uint8 arrays, the same pixels the model always got, so the vectors do not
change (checked: identical to the last bit)."""

from __future__ import annotations

import contextlib
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.images import load_rgb
from styleatlas.look import measure

INPUT_PX = 224
MAX_TILES = 3
MAX_ASPECT = 4.0  # longer strips are centre-cropped first (keeps memory bounded)
LOAD_ERRORS = (OSError, ValueError, Image.DecompressionBombError, SyntaxError)

Prepared = tuple[list[np.ndarray], np.ndarray]  # (input squares, look measures)


def square_crops(im: Image.Image, mode: str, px: int = INPUT_PX) -> list[Image.Image]:
    """Resize the short side to `px`; take the centre square or tiles along the long side."""
    w, h = im.size
    if max(w, h) > MAX_ASPECT * min(w, h):
        long_keep = int(MAX_ASPECT * min(w, h))
        if w > h:
            im = im.crop(((w - long_keep) // 2, 0, (w - long_keep) // 2 + long_keep, h))
        else:
            im = im.crop((0, (h - long_keep) // 2, w, (h - long_keep) // 2 + long_keep))
        w, h = im.size
    scale = px / min(w, h)
    rw, rh = max(px, round(w * scale)), max(px, round(h * scale))
    im = im.resize((rw, rh), Image.Resampling.BICUBIC)
    long_side = max(rw, rh)
    n = 1 if mode == "center" else min(MAX_TILES, math.ceil(long_side / px - 0.15))
    if n <= 1:
        offsets = [(long_side - px) // 2]
    else:
        offsets = [round(i * (long_side - px) / (n - 1)) for i in range(n)]
    if rw >= rh:
        return [im.crop((o, 0, o + px, px)) for o in offsets]
    return [im.crop((0, o, px, o + px)) for o in offsets]


def prepare_file(path: Path, crop: str, px: int) -> Prepared | str:
    """The input squares and look measures of one image file, or why it cannot be opened."""
    try:
        im = load_rgb(path)
        return [np.asarray(c) for c in square_crops(im, crop, px)], measure(im)
    except LOAD_ERRORS as e:
        return f"cannot open: {e}"


def worker_start(cpus: list[int] | None) -> None:
    """In each worker process: the CPUs and the lower priority its parent runs with, so the
    workers never load more of the machine than the capped program itself."""
    import psutil

    proc = psutil.Process()
    if cpus and hasattr(proc, "cpu_affinity"):
        with contextlib.suppress(psutil.Error, OSError, ValueError):
            proc.cpu_affinity(cpus)
    with contextlib.suppress(psutil.Error, OSError):
        proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 10)
