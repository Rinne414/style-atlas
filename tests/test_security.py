"""Inputs the app must not trust: saved files, dataset contents, uploads, other web pages."""

from __future__ import annotations

import json
import os

import pytest
from PIL import Image

from styleatlas.atlas import Atlas
from styleatlas.export import export_folders

from .conftest import make_blobs


def _atlas(tmp_path, n=6):
    x, _ = make_blobs([n])
    paths = []
    for i in range(n):
        p = tmp_path / "lib" / f"i{i}.png"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (8, 8), (i, 0, 0)).save(p)
        paths.append(p)
    return Atlas(tmp_path / "lib", paths, x, x, "sig")


def test_names_in_a_saved_groups_file_cannot_leave_the_export(tmp_path):
    from styleatlas.groupfile import load_groups

    atlas = _atlas(tmp_path)
    data = {
        "labels": {atlas.rel(i): 0 for i in range(len(atlas))},
        "group_names": {"0": "../../escaped", "1": "C:\\Windows\\evil", "2": "..."},
    }
    path = tmp_path / "groups.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    names = load_groups(path, atlas).names
    assert names == {0: "escaped", 1: "C__Windows_evil"}


def test_export_refuses_folder_names_that_lead_outside(tmp_path):
    atlas = _atlas(tmp_path)
    folders = ["../evil", str(tmp_path / "abs"), "ok", "ok", "ok", "."]
    done = export_folders(atlas, folders, tmp_path / "out")
    assert done.placed == 3 and len(done.failed) == 3
    assert not (tmp_path / "evil").exists() and not (tmp_path / "abs").exists()


def test_huge_images_are_refused_before_decoding(tmp_path, monkeypatch):
    import styleatlas.images as images

    p = tmp_path / "big.png"
    Image.new("L", (40, 40)).save(p)
    monkeypatch.setattr(images, "MAX_PIXELS", 1000)
    with pytest.raises(ValueError, match="too large"):
        images.load_rgb(p)


def test_symlinked_files_in_a_dataset_are_skipped(tmp_path):
    from styleatlas.images import find_images

    outside = tmp_path / "secret.png"
    Image.new("RGB", (8, 8)).save(outside)
    lib = tmp_path / "lib"
    lib.mkdir()
    Image.new("RGB", (8, 8)).save(lib / "real.png")
    try:
        os.symlink(outside, lib / "link.png")
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot create symlinks")
    assert [p.name for p in find_images(lib)] == ["real.png"]


def test_other_sites_cannot_fetch_thumbnails(tmp_path):
    import http.client
    import threading

    from styleatlas.atlas import EncodeOptions
    from styleatlas.serve import StyleAtlasApp
    from styleatlas.webserver import bind

    app = StyleAtlasApp(_atlas(tmp_path), EncodeOptions(device="cpu"), "pca")
    srv = bind(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        for site, want in (("cross-site", 403), ("same-origin", 200), (None, 200)):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/thumb/0", headers={"Sec-Fetch-Site": site} if site else {})
            assert conn.getresponse().status == want
            conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
