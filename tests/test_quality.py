import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from styleatlas.dataset import audit
from styleatlas.quality import LOW_JPEG, SOFT, jpeg_quality, softness, softness_of_file


def _drawing(size: int = 512, seed: int = 0) -> Image.Image:
    """Flat shapes and hard lines, like line art: sharp at full size."""
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (size, size), (250, 248, 240))
    d = ImageDraw.Draw(im)
    for _ in range(60):
        x, y = rng.integers(0, size, 2)
        r = int(rng.integers(10, 80))
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    for _ in range(120):
        ends = [tuple(int(v) for v in rng.integers(0, size, 2)) for _ in range(2)]
        d.line(ends, fill=(20, 20, 30), width=int(rng.integers(1, 4)))
    return im


def _enlarged(im: Image.Image, factor: float = 2) -> Image.Image:
    w, h = im.size
    small = im.resize((round(w / factor), round(h / factor)), Image.Resampling.LANCZOS)
    return small.resize((w, h), Image.Resampling.BICUBIC)


def _reopened(im: Image.Image, fmt: str, **kw) -> Image.Image:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    buf.seek(0)
    return Image.open(buf)


def test_jpeg_quality_is_read_from_the_table():
    im = _drawing()
    for q in (40, 69, 90):
        assert jpeg_quality(_reopened(im, "JPEG", quality=q)) == q
    assert jpeg_quality(_reopened(im, "PNG")) is None


def test_enlarged_images_are_soft_and_originals_are_not():
    im = _drawing()
    assert softness(im) > 3 * SOFT
    assert softness(_enlarged(im, 2)) < SOFT
    assert softness(_enlarged(im, 3)) < SOFT


def test_flat_or_tiny_images_are_not_judged():
    assert softness(Image.new("RGB", (512, 512), (9, 9, 9))) is None
    assert softness(_drawing(100)) is None


def test_softness_is_measured_at_full_size_on_the_centre(tmp_path):
    big = _enlarged(_drawing(2048, seed=1), 2)  # larger than the window: still caught
    path = tmp_path / "big.png"
    big.save(path)
    assert softness_of_file(path) < SOFT
    assert softness_of_file(tmp_path / "missing.png") is None


def test_audit_flags_enlarged_and_heavily_compressed(tmp_path):
    _drawing(seed=2).save(tmp_path / "ok.png")
    _enlarged(_drawing(seed=3)).save(tmp_path / "enlarged.png")
    _drawing(seed=4).save(tmp_path / "crushed.jpg", quality=LOW_JPEG - 30)
    _drawing(seed=5).save(tmp_path / "fine.jpg", quality=95)
    report = audit(sorted(tmp_path.iterdir()), min_side=256)
    files = {k: [Path(f).name for f in v] for k, v in report["files"].items()}
    assert files["soft_or_enlarged"] == ["enlarged.png"]
    assert files["low_jpeg_quality"] == ["crushed.jpg"]
