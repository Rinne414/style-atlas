from __future__ import annotations

import http.client
import json
import threading

import pytest
from PIL import Image

from styleatlas.atlas import Atlas, EncodeOptions
from styleatlas.serve import StyleAtlasApp, bind

from .conftest import make_blobs


@pytest.fixture
def server(tmp_path):
    x, _ = make_blobs([8, 7])
    paths = []
    for i in range(len(x)):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (32, 48), (i * 10, 0, 0)).save(p)
        paths.append(p)
    app = StyleAtlasApp(Atlas(tmp_path, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")
    srv = bind(app, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv.server_address[1], tmp_path
    srv.shutdown()
    srv.server_close()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_page_and_thumbnails(server):
    port, _ = server
    status, html = request(port, "GET", "/")
    assert status == 200 and b'"live"' in html
    status, data = request(port, "GET", "/thumb/0")
    assert status == 200 and data[:4] == b"RIFF"  # WebP
    assert request(port, "GET", "/thumb/999")[0] == 404
    assert request(port, "GET", "/image/..%2Fsecret")[0] == 404


def test_rejects_foreign_host_and_missing_post_header(server):
    port, _ = server
    assert request(port, "GET", "/", headers={"Host": "evil.example"})[0] == 403
    body = json.dumps({"threshold": 0.5})
    assert request(port, "POST", "/api/regroup", body)[0] == 403


def test_regroup_and_export(server):
    port, root = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    status, data = request(port, "POST", "/api/regroup", json.dumps({"threshold": 0.5}), hdr)
    assert status == 200 and json.loads(data)["clusters"] == 2
    status, data = request(port, "POST", "/api/regroup", json.dumps({"threshold": 9}), hdr)
    assert status == 400
    status, data = request(port, "POST", "/api/export", json.dumps({"mode": "copy"}), hdr)
    result = json.loads(data)
    assert status == 200 and result["placed"] == 15
    assert (root / "style_atlas_out" / "clusters.csv").exists()


def test_search_rejects_non_images(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "image/png"}
    status, data = request(port, "POST", "/api/search", b"not an image", hdr)
    assert status == 400 and "readable" in json.loads(data)["error"]
