from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from styleatlas.atlas import EncodeOptions, measure_looks
from styleatlas.look import LOOK_NAMES, describe, difference, measure, profile


def look(image: Image.Image) -> dict[str, float]:
    return dict(zip(LOOK_NAMES, measure(image).tolist(), strict=True))


def lines_drawing(size: int = 300) -> Image.Image:
    im = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(im)
    for x in range(0, size, 6):
        d.line([(x, 0), (x, size)], fill="black", width=1)
    return im


def test_plain_images_give_the_expected_extremes():
    black, white = look(Image.new("RGB", (64, 64))), look(Image.new("RGB", (64, 64), "white"))
    assert black["brightness"] == 0 and white["brightness"] == pytest.approx(1)
    assert white["flatness"] == 1 and white["lines"] == 0 and white["contrast"] == 0
    red, blue = (
        look(Image.new("RGB", (64, 64), (220, 30, 30))),
        look(Image.new("RGB", (64, 64), (30, 30, 220))),
    )
    assert red["warmth"] > 0.5 and blue["warmth"] < -0.5
    assert red["colourfulness"] > 0.2 and white["colourfulness"] == 0
    drawn = look(lines_drawing())
    assert drawn["lines"] > 0.2 and drawn["flatness"] < 0.5 and drawn["contrast"] > 0.2


def test_size_does_not_change_the_measures_much():
    small, large = look(lines_drawing(300)), look(lines_drawing(300).resize((1200, 1200)))
    for name in ("brightness", "contrast", "lines"):
        assert small[name] == pytest.approx(large[name], abs=0.1)


def test_profile_words_and_difference():
    rng = np.random.default_rng(0)
    looks = rng.normal(0.5, 0.1, size=(40, len(LOOK_NAMES))).astype(np.float32)
    lines = LOOK_NAMES.index("lines")
    looks[:10, lines] += 0.3  # the first ten have much more line work
    z = profile(looks, list(range(10)))
    assert z[lines] > 1 and describe(z).startswith("more line work")
    assert describe(np.zeros(len(LOOK_NAMES))) == ""
    d = difference(looks[10:], looks[:10])
    assert d[lines] > 2 and abs(d[0]) < 1


def test_looks_are_cached_and_measured_once(tmp_path, monkeypatch):
    from styleatlas import atlas as atlas_module

    paths = []
    for i, colour in enumerate(("red", "blue", "white")):
        p = tmp_path / f"{i}.png"
        Image.new("RGB", (32, 32), colour).save(p)
        paths.append(p)
    opts = EncodeOptions(device="cpu", db_path=tmp_path / "cache.sqlite")
    first = measure_looks(paths, opts)
    assert first.shape == (3, len(LOOK_NAMES))
    assert first[0, LOOK_NAMES.index("warmth")] > 0 > first[1, LOOK_NAMES.index("warmth")]

    def fail(path):
        raise AssertionError("measured again")

    monkeypatch.setattr(atlas_module, "_measure_file", fail)
    assert np.array_equal(measure_looks(paths, opts), first)


def test_an_image_that_cannot_be_opened_or_is_gone_gets_the_average(tmp_path):
    good = tmp_path / "good.png"
    Image.new("RGB", (32, 32), "white").save(good)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    gone = tmp_path / "gone.png"
    got = measure_looks([good, bad, gone], EncodeOptions(device="cpu", db_path=tmp_path / "c.db"))
    assert np.array_equal(got[1], got[0]) and np.array_equal(got[2], got[0])
