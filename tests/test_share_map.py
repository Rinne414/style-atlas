"""The shared map file: sharper pictures inside it for the recipient, and the size estimates the
page shows before saving."""

from __future__ import annotations

import json
import re

import pytest
from PIL import Image

from styleatlas.atlas import Atlas, EncodeOptions
from styleatlas.serve import StyleAtlasApp

from .conftest import make_blobs


def _app(tmp_path):
    x, _ = make_blobs([5, 4])
    folder = tmp_path / "pics"
    folder.mkdir()
    paths = []
    for i in range(len(x)):
        p = folder / f"img{i}.png"
        Image.new("RGB", (900, 1200), (20 * i, 90, 160)).save(p)
        paths.append(p)
    return StyleAtlasApp(Atlas(folder, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")


def _points(path):
    text = path.read_text(encoding="utf-8")
    data = re.search(r'<script id="atlas-data" type="application/json">(.*?)</script>', text, re.S)
    return json.loads(data.group(1))["points"]


def test_a_shared_map_carries_sharper_pictures_when_asked(tmp_path):
    app = _app(tmp_path)
    small = app.save_map({"preview": 0})
    assert all("v" not in p for p in _points(app.out_dir / "map.html"))
    sharp = app.save_map({"preview": 320})
    points = _points(app.out_dir / "map.html")
    assert all(p["v"].startswith("data:image/webp;base64,") for p in points)
    assert sharp["mb"] >= small["mb"]
    for bad in (100, "320", None, True):
        with pytest.raises(ValueError):
            app.save_map({"preview": bad})


def test_the_size_estimates_grow_with_the_pictures(tmp_path):
    app = _app(tmp_path)
    sizes = app.share_sizes({})["sizes"]
    assert set(sizes) == {"0", "320", "512"}
    assert 0 < sizes["0"] <= sizes["320"] <= sizes["512"]


def test_the_recipient_starts_on_the_senders_layout(tmp_path):
    app = _app(tmp_path)
    text_of = lambda: (app.out_dir / "map.html").read_text(encoding="utf-8")  # noqa: E731
    app.save_map({"preview": 0, "layout": "style"})
    assert '"start_layout":"style"' in text_of().replace(" ", "")
    with pytest.raises(ValueError):
        app.save_map({"preview": 0, "layout": "sideways"})
