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


def test_groups_and_names_survive_a_restart(tmp_path):
    from styleatlas.atlas import Atlas, EncodeOptions
    from styleatlas.serve import StyleAtlasApp

    x, _ = make_blobs([8, 7])
    paths = []
    for i in range(len(x)):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    atlas = Atlas(tmp_path, paths, x, x, "sig")
    app = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    app.regroup({"threshold": 0.5})
    app.merge({"from": 1, "into": 0, "rev": app.revision})
    app.rename({"group": 0, "name": "all", "rev": app.revision})
    assert app.clustering.n_clusters == 1
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert again.restored and again.clustering.n_clusters == 1
    assert again.names_by_group() == {0: "all"} and again.settings["edited"] is True


def test_web_export_can_write_a_kohya_layout_with_triggers(server):
    from pathlib import Path

    port, root = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    request(port, "POST", "/api/regroup", json.dumps({"threshold": 0.5}), hdr)
    body = {"mode": "copy", "layout": "kohya", "name": "artistX", "trigger": True}
    status, data = request(port, "POST", "/api/export", json.dumps(body), hdr)
    assert status == 200
    folder = Path(json.loads(data)["folder"])
    groups = sorted(p.name for p in folder.iterdir() if not p.name.startswith("_"))
    assert groups and all(g.split("_", 1)[1].startswith("artistX_style") for g in groups)
    caption = next((folder / groups[0]).glob("*.txt")).read_text(encoding="utf-8")
    assert caption.startswith(groups[0].split("_", 1)[1])
    bad = {"layout": "zip"}
    assert request(port, "POST", "/api/export", json.dumps(bad), hdr)[0] == 400


def test_undo_reverts_edits_one_step_at_a_time(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}

    def post(route, body):
        status, data = request(port, "POST", route, json.dumps(body), hdr)
        return status, json.loads(data)

    post("/api/regroup", {"threshold": 0.5})  # rev 1, two groups
    status, r = post("/api/merge", {"from": 1, "into": 0, "rev": 1})
    assert r["clusters"] == 1
    status, r = post("/api/undo", {"rev": r["revision"]})
    assert status == 200 and r["clusters"] == 2
    status, r = post("/api/undo", {"rev": r["revision"]})  # back before the regroup
    assert status == 200
    status, html = request(port, "GET", "/")
    assert b'"can_undo":false' in html
    assert post("/api/undo", {"rev": r["revision"]})[0] == 400  # nothing left


def _app(tmp_path, sizes=(8, 7)):
    x, _ = make_blobs(list(sizes))
    paths = []
    for i in range(len(x)):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    atlas = Atlas(tmp_path, paths, x, x, "sig")
    return StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca"), atlas


def test_undo_restores_names_and_the_space_after_a_switch(tmp_path):
    x, _ = make_blobs([8, 7])
    paths = []
    for i in range(len(x)):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    app = StyleAtlasApp(Atlas(tmp_path, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")
    app.regroup({"threshold": 0.5})
    app.rename({"group": 0, "name": "first", "rev": app.revision})
    app.rename({"group": 0, "name": "second", "rev": app.revision})
    app.undo({"rev": app.revision})
    assert app.names_by_group() == {0: "first"}
    app.merge({"from": 1, "into": 0, "rev": app.revision})
    app.set_neutralize({"k": 1})
    app.undo({"rev": app.revision})  # back to the old space, hand edit and name included
    assert app.neutralize == 0 and app.clustering.n_clusters == 1
    assert app.names_by_group() == {0: "first"}


def test_names_follow_their_images_through_edits(tmp_path):
    app, _ = _app(tmp_path, (8, 7, 6))
    app.regroup({"threshold": 0.5})
    assert app.clustering.n_clusters == 3
    sizes = {c.id: c.size for c in app.clustering.clusters}
    app.rename({"group": 0, "name": "big", "rev": app.revision})
    app.rename({"group": 2, "name": "small", "rev": app.revision})
    app.merge({"from": 0, "into": 2, "rev": app.revision})  # the target's name wins
    assert list(app.names_by_group().values()) == ["small"]
    assert app.clustering.clusters[0].size == sizes[0] + sizes[2]
    app.undo({"rev": app.revision})
    app.split({"group": 0, "rev": app.revision})  # the larger half keeps the name
    named = next(g for g, n in app.names_by_group().items() if n == "big")
    assert app.clustering.clusters[named].size >= 4


def test_failed_or_unchanged_renames_add_no_undo_step(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    steps = len(app._history)
    with pytest.raises(ValueError):
        app.rename({"group": 0, "name": " ... ", "rev": app.revision})
    app.rename({"group": 0, "name": "a", "rev": app.revision})
    app.rename({"group": 0, "name": "a", "rev": app.revision})
    assert len(app._history) == steps + 1
    with pytest.raises(ValueError, match="already called"):
        app.rename({"group": 1, "name": "A", "rev": app.revision})
    with pytest.raises(ValueError, match="reload"):
        app.undo({"rev": app.revision + 1})
    for i in range(40):
        app.rename({"group": 0, "name": f"n{i}", "rev": app.revision})
    assert len(app._history) == 30


def test_a_damaged_groups_file_is_set_aside(tmp_path):
    app, atlas = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    path = app._groups_path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["labels"][next(iter(data["labels"]))] = "x"
    path.write_text(json.dumps(data), encoding="utf-8")
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert not again.restored
    assert len(list(path.parent.glob("groups.json.*.bad"))) == 1


def test_the_saved_space_and_names_come_back(tmp_path):
    app, atlas = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    app.rename({"group": 1, "name": "second", "rev": app.revision})
    app.set_neutralize({"k": 1})
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert again.restored and again.neutralize == 1
    assert again.names_by_group() == app.names_by_group()
    assert (again.clustering.labels == app.clustering.labels).all()


def test_web_export_reports_groups_too_small_to_keep(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    for i in app.clustering.clusters[1].members[2:]:  # leave 2 images in the smaller group
        app.move({"i": i, "to": -1, "rev": app.revision})
    assert app.export({"mode": "copy"})["small_groups"] == 1


def test_more_like_a_group_finds_its_strays(tmp_path):
    app, _ = _app(tmp_path, (8, 7, 6))
    app.regroup({"threshold": 0.5})
    target = app.clustering.clusters[0]
    stray = target.members[0]
    app.move({"i": stray, "to": -1, "rev": app.revision})
    group = int(app.clustering.labels[target.members[1]])
    hits = app.similar({"group": group})["hits"]
    assert hits[0] == {"i": stray, "group": -1}
    assert all(h["group"] != group for h in hits)
    with pytest.raises(ValueError):
        app.similar({"group": 99})


def test_several_dropped_images_search_as_one_style(tmp_path, monkeypatch):
    import base64
    import io

    import numpy as np

    app, atlas = _app(tmp_path, (8, 7))

    class FakeEncoder:  # the images' red channel picks the stored vector they stand for
        def encode(self, images):
            rows = [atlas.style[np.asarray(im)[0, 0, 0]] for im in images]
            return type("E", (), {"style": np.stack(rows)})

    monkeypatch.setattr("styleatlas.serve.get_encoder", lambda opts: FakeEncoder())

    def png(i):
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), (i, 0, 0)).save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    hits = app.search_set({"images": [png(0), png(1), png(2)]})["hits"]
    assert {h["i"] for h in hits[:8]} == set(range(8))  # the first blob, examples included
    for bad in ({"images": []}, {"images": ["not base64!"]}, {"images": [png(0)] * 33}):
        with pytest.raises(ValueError):
            app.search_set(bad)


def test_the_page_script_parses(tmp_path):
    """`node --check` skips .js files that use import, so the check runs on an .mjs copy."""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    src = Path(__file__).parents[1] / "src" / "styleatlas" / "templates" / "map.js"
    copy = tmp_path / "map.mjs"
    copy.write_bytes(src.read_bytes())
    result = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_regroup_without_a_threshold_is_auto(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    app.regroup({})
    assert app.settings["threshold"] is None and app.clustering.params["auto"]
    with pytest.raises(ValueError):
        app.regroup({"threshold": "0.4"})
