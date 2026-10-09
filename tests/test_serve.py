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
    assert (root.parent / f"{root.name}_style_atlas" / "clusters.csv").exists()


def test_search_rejects_non_images(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "image/png"}
    status, data = request(port, "POST", "/api/search", b"not an image", hdr)
    assert status == 400 and "readable" in json.loads(data)["error"]


def test_taste_votes_train_after_enough_examples_and_persist(server):
    port, root = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}

    def vote(i, like):
        status, data = request(port, "POST", "/api/taste", json.dumps({"i": i, "like": like}), hdr)
        assert status == 200
        return json.loads(data)

    for i in range(4):  # first blob = images 0-7, second = 8-14
        vote(i, True)
        state = vote(8 + i, False)
    assert state["likes"] == 4 and state["scores"] is None  # below 5 of each
    vote(4, True)
    state = vote(12, False)
    assert state["scores"] is not None and len(state["scores"]) == 15
    state = vote(12, None)  # removing a vote drops below the minimum again
    assert state["dislikes"] == 4 and state["scores"] is None
    status, data = request(port, "POST", "/api/next", "{}", hdr)
    assert status == 200 and json.loads(data)["i"] not in {0, 1, 2, 3, 4, 8, 9, 10, 11}
    out = root.parent / f"{root.name}_style_atlas"
    saved = json.loads((out / "taste_votes.json").read_text(encoding="utf-8"))
    assert len(saved) == 9
    assert request(port, "POST", "/api/taste", json.dumps({"i": 0, "like": "yes"}), hdr)[0] == 400


def test_excluded_images_persist_and_go_to_excluded_folder(server):
    port, root = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    status, data = request(port, "POST", "/api/exclude", json.dumps({"i": 3}), hdr)
    assert status == 200 and json.loads(data)["excluded"] == [3]
    status, data = request(port, "POST", "/api/export", json.dumps({"mode": "copy"}), hdr)
    folder = json.loads(data)["folder"]
    from pathlib import Path

    assert (Path(folder) / "_excluded" / "img3.png").exists()
    out = root.parent / f"{root.name}_style_atlas"
    assert json.loads((out / "excluded.json").read_text(encoding="utf-8")) == {"img3.png": True}
    status, data = request(
        port, "POST", "/api/exclude", json.dumps({"i": 3, "excluded": False}), hdr
    )
    assert json.loads(data)["excluded"] == []


def test_bad_request_bodies_are_rejected_cleanly(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    for route, body in [
        ("/api/exclude", "[1, 2]"),
        ("/api/exclude", '{"i": null}'),
        ("/api/exclude", '{"i": 1, "excluded": "false"}'),
        ("/api/taste", '{"i": 1.5, "like": true}'),
        ("/api/regroup", '{"threshold": "0.4"}'),
        ("/api/regroup", '{"k": 2.0}'),
        ("/api/regroup", "not json"),
    ]:
        status, data = request(port, "POST", route, body, hdr)
        assert status == 400, (route, body, status)


def test_hand_edits_merge_and_move(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    status, data = request(port, "POST", "/api/regroup", json.dumps({"threshold": 0.5}), hdr)
    assert json.loads(data)["clusters"] == 2
    rev = 1  # one regroup so far
    stale = {"from": 1, "into": 0, "rev": 0}
    assert request(port, "POST", "/api/merge", json.dumps(stale), hdr)[0] == 400
    body = {"from": 1, "into": 0, "rev": rev}
    status, data = request(port, "POST", "/api/merge", json.dumps(body), hdr)
    assert status == 200 and json.loads(data)["clusters"] == 1
    rev = json.loads(data)["revision"]
    body = {"i": 0, "to": -1, "rev": rev}
    status, data = request(port, "POST", "/api/move", json.dumps(body), hdr)
    assert status == 200
    rev = json.loads(data)["revision"]
    status, html = request(port, "GET", "/")
    assert b'"edited":true' in html
    for body in ({"from": 0, "into": 0}, {"from": 5, "into": 0}, {"from": "0", "into": 1}):
        assert request(port, "POST", "/api/merge", json.dumps({**body, "rev": rev}), hdr)[0] == 400
    bad = {"i": 0, "to": 9, "rev": rev}
    assert request(port, "POST", "/api/move", json.dumps(bad), hdr)[0] == 400


def test_split_cuts_a_group_in_two(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    request(port, "POST", "/api/regroup", json.dumps({"k": 1}), hdr)
    status, data = request(port, "POST", "/api/split", json.dumps({"group": 0, "rev": 1}), hdr)
    assert status == 200 and json.loads(data)["clusters"] == 2
    bad = {"group": 7, "rev": 2}
    assert request(port, "POST", "/api/split", json.dumps(bad), hdr)[0] == 400


def test_neutralize_can_be_switched_live(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    status, data = request(port, "POST", "/api/neutralize", json.dumps({"k": 1}), hdr)
    assert status == 200 and json.loads(data)["neutralize"] == 1
    status, html = request(port, "GET", "/")
    assert b'"neutralize":1' in html
    assert request(port, "POST", "/api/neutralize", json.dumps({"k": 9}), hdr)[0] == 400
    status, data = request(port, "POST", "/api/neutralize", json.dumps({"k": 0}), hdr)
    assert json.loads(data)["neutralize"] == 0


def test_group_names_follow_the_group_and_name_the_export(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    request(port, "POST", "/api/regroup", json.dumps({"threshold": 0.5}), hdr)
    body = {"group": 1, "name": "早期: sketch/line", "rev": 1}
    status, data = request(port, "POST", "/api/rename", json.dumps(body), hdr)
    assert status == 200 and json.loads(data)["names"] == {"1": "早期_ sketch_line"}
    status, data = request(port, "POST", "/api/export", json.dumps({"mode": "copy"}), hdr)
    from pathlib import Path

    folders = {p.name for p in Path(json.loads(data)["folder"]).iterdir()}
    assert "早期_ sketch_line" in folders
    bad = {"group": 0, "name": 5, "rev": 1}
    assert request(port, "POST", "/api/rename", json.dumps(bad), hdr)[0] == 400
