from __future__ import annotations

import http.client
import json
import threading

import numpy as np
import pytest
from PIL import Image

from styleatlas.atlas import Atlas, EncodeOptions
from styleatlas.look import LOOK_NAMES
from styleatlas.quality import LOW_JPEG
from styleatlas.serve import StyleAtlasApp
from styleatlas.webserver import bind

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


def test_the_space_can_be_switched_live(server):
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    body = json.dumps({"space": "characters"})
    status, data = request(port, "POST", "/api/space", body, hdr)
    assert status == 200 and json.loads(data)["space"] == "characters"
    status, html = request(port, "GET", "/")
    assert b'"space":"characters"' in html
    for bad in ("neutralize-9", "neutralize-01", "Plain", 1, None):
        assert request(port, "POST", "/api/space", json.dumps({"space": bad}), hdr)[0] == 400
    status, data = request(port, "POST", "/api/space", json.dumps({"space": "plain"}), hdr)
    assert json.loads(data)["space"] == "plain"


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
    groups = sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith("_"))
    assert (folder / "dataset_config.toml").exists()  # the web export writes it too
    assert json.loads(data)["config"] is True
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
    app.set_space({"space": "characters"})
    app.undo({"rev": app.revision})  # back to the old space, hand edit and name included
    assert app.space.name == "plain" and app.clustering.n_clusters == 1
    assert app.names_by_group() == {0: "first"}


def test_a_groups_file_from_before_spaces_keeps_its_neutralize_count(tmp_path):
    app, atlas = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    path = app._groups_path
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["space"]
    for k, expected in ((1, "neutralize-1"), (0, "plain"), (99, "plain")):
        path.write_text(json.dumps({**data, "neutralize": k}), encoding="utf-8")
        again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
        assert again.restored and again.space.name == expected  # 99: invalid, the default


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
    app.set_space({"space": "neutralize-1"})
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert again.restored and again.space.name == "neutralize-1"
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
            return type("E", (), {"style": np.stack(rows), "content": np.stack(rows)})

    monkeypatch.setattr("styleatlas.serve.get_encoder", lambda opts: FakeEncoder())

    def png(i):
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), (i, 0, 0)).save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    got = app.search_set({"images": [png(0), png(1), png(2)]})
    assert {h["i"] for h in got["hits"][:8]} == set(range(8))  # the first blob, examples included
    assert got["folders"] == []  # no sub-folders to rank
    for bad in ({"images": []}, {"images": ["not base64!"]}, {"images": [png(0)] * 33}):
        with pytest.raises(ValueError):
            app.search_set(bad)


def test_a_search_names_the_closest_sub_folder(tmp_path, monkeypatch):
    import io

    x, labels = make_blobs([8, 7])
    paths = []
    for i, k in enumerate(labels):
        p = tmp_path / ("early" if k == 0 else "late") / f"img{i}.png"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    app = StyleAtlasApp(Atlas(tmp_path, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")

    class FakeEncoder:
        def encode(self, images):
            rows = [x[np.asarray(im)[0, 0, 0]] for im in images]
            return type("E", (), {"style": np.stack(rows), "content": np.stack(rows)})

    monkeypatch.setattr("styleatlas.serve.get_encoder", lambda opts: FakeEncoder())
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 0, 0)).save(buf, "PNG")  # stands for image 10, a "late" one
    folders = app.search_image(buf.getvalue())["folders"]
    assert [f["folder"] for f in folders] == ["late", "early"]
    assert folders[0]["size"] == 7 and labels[folders[0]["best"]] == 1
    app.exclude({"i": int(np.flatnonzero(labels == 1)[0])})  # a stray: no longer in the mean
    again = app.search_image(buf.getvalue())["folders"]
    assert again[0]["folder"] == "late" and again[0]["size"] == 6


def test_the_page_script_parses(tmp_path):
    """`node --check` skips .js files that use import, so the check runs on an .mjs copy."""
    import shutil
    import subprocess

    from styleatlas.report import page_script

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    copy = tmp_path / "map.mjs"
    copy.write_text(page_script(), encoding="utf-8")
    result = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_page_script_joins_every_template_script():
    """A templates/*.js file that page_script leaves out still parses, then fails at run time."""
    from pathlib import Path

    from styleatlas import report

    script = report.page_script()
    for f in (Path(report.__file__).parent / "templates").glob("*.js"):
        assert f.read_text(encoding="utf-8") in script, f.name


def test_regroup_without_a_threshold_is_auto(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    app.regroup({})
    assert app.settings["threshold"] is None and app.clustering.params["auto"]
    with pytest.raises(ValueError):
        app.regroup({"threshold": "0.4"})


def test_the_page_lists_each_groups_characteristic_tags(tmp_path):
    app, atlas = _app(tmp_path, (8, 7))
    app.regroup({"threshold": 0.5})
    for i, p in enumerate(atlas.paths):
        tag = "sketch" if app.clustering.labels[i] == 1 else "color"
        p.with_suffix(".txt").write_text(f"1girl, {tag}", encoding="utf-8")
    app._tag_sets = None  # captions written after start-up
    html = app.page()
    assert '"tags":["color"]' in html and '"tags":["sketch"]' in html


def test_the_map_can_be_saved_as_one_shareable_file(tmp_path):
    from pathlib import Path

    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    app.rename({"group": 0, "name": "early", "rev": app.revision})
    html = Path(app.save_map({})["file"]).read_text(encoding="utf-8")
    assert "data:image/" in html and '"names":{"0":"early"}' in html
    assert "thumb/" not in html  # nothing points back at the local server


def test_unreadable_captions_and_missing_images_do_not_break_the_page(server):
    port, root = server
    (root / "img0.txt").mkdir()  # a folder where the caption should be
    status, html = request(port, "GET", "/")
    assert status == 200 and b'"live"' in html
    (root / "img1.png").unlink()
    assert request(port, "GET", "/image/1")[0] == 404


def test_an_unexpected_error_still_gets_an_answer(server, monkeypatch):
    from styleatlas.serve import StyleAtlasApp

    port, _ = server

    def boom(self, body):
        raise RuntimeError("model fell over")

    monkeypatch.setattr(StyleAtlasApp, "similar", boom)
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    status, data = request(port, "POST", "/api/similar", json.dumps({"group": 0}), hdr)
    assert status == 500 and "RuntimeError" in json.loads(data)["error"]


def test_open_output_opens_only_the_output_folder(tmp_path, monkeypatch):
    import os

    app, _ = _app(tmp_path)
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    monkeypatch.setattr("styleatlas.serve.subprocess.Popen", lambda args: opened.append(args[-1]))
    folder = app.open_output({"folder": "C:/Windows"})["folder"]  # any body is ignored
    assert [str(f) for f in opened] == [folder] and folder == str(app.out_dir)


def test_regroup_into_periods(tmp_path):
    app, _ = _app(tmp_path)  # 15 images in two styles
    app.regroup({"method": "kmeans", "k": 2})
    assert app.clustering.n_clusters == 2 and app.clustering.n_unassigned == 0
    assert app.settings == {"method": "kmeans", "threshold": None, "k": 2}
    app.regroup({"method": "kmeans", "k": 6})  # periods under 3 images are set aside
    assert all(c.size >= 3 for c in app.clustering.clusters)


def test_prewarm_reads_the_captions(tmp_path):
    app, atlas = _app(tmp_path)
    atlas.paths[0].with_suffix(".txt").write_text("sketch", encoding="utf-8")
    app._read_tags()
    assert app._tag_sets[0] == {"sketch"} and app._tag_sets[1] == set()


def test_the_server_queues_bursts_of_thumbnail_requests(server):
    from styleatlas.webserver import _Server

    assert _Server.request_queue_size >= 64


def test_uploads_move_by_their_own_character_and_a_failed_switch_leaves_no_undo(
    tmp_path, monkeypatch
):
    import io

    import numpy as np

    from styleatlas import metrics

    app, _ = _app(tmp_path, (8, 7, 6))
    app.set_space({"space": "characters"})
    assert len(app.space.transform.centres) >= 2
    assert not np.allclose(app.atlas.style, app.raw.style)
    style, content = app.raw.style[:1], app.raw.content[-1:]  # content of another group

    class FakeEncoder:
        def encode(self, images):
            return type("E", (), {"style": style, "content": content})

    monkeypatch.setattr("styleatlas.serve.get_encoder", lambda opts: FakeEncoder())
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    got = app._embed([buf.getvalue()])
    assert np.allclose(got, app.space.apply(style, content))
    assert not np.allclose(got, app.space.apply(style, style))

    def broken(*args, **kwargs):
        raise ValueError("no subjects")

    monkeypatch.setattr(metrics.Neutralizer, "fit", broken)
    steps = len(app._history)
    with pytest.raises(ValueError):
        app.set_space({"space": "neutralize-1"})
    assert len(app._history) == steps and app.space.name == "characters"


def test_more_like_the_excluded_images(tmp_path):
    app, _ = _app(tmp_path, (12, 6))  # a main set and six strays
    with pytest.raises(ValueError):
        app.similar({"excluded": True})
    strays = [int(i) for i in np.flatnonzero(app.clustering.labels == app.clustering.labels[-1])]
    for i in strays[:2]:
        app.exclude({"i": i, "excluded": True})
    hits = [h["i"] for h in app.similar({"excluded": True})["hits"]]
    assert set(hits[:4]) <= set(strays) - set(strays[:2])


def test_two_groups_compared(server, tmp_path):
    app, _ = _app(tmp_path, (10, 10, 10))
    labels = app.clustering.labels
    a, b = int(labels[0]), int(labels[-1])
    got = app.compare({"a": a, "b": b})
    assert got["verdict"] == "clearly different" and got["p"] < 0.05 and got["sizes"] == [10, 10]
    assert set(got["look"]) == set(LOOK_NAMES)
    with pytest.raises(ValueError):
        app.compare({"a": a, "b": a})
    port, _ = server
    hdr = {"X-Style-Atlas": "1", "Content-Type": "application/json"}
    status, data = request(port, "POST", "/api/compare", json.dumps({"a": 0, "b": 1}), hdr)
    assert status == 200 and "distance" in json.loads(data)
    assert request(port, "POST", "/api/compare", json.dumps({"a": 0, "b": 0}), hdr)[0] == 400


def test_the_check_tab_lists_problems_by_index(tmp_path):
    app, _ = _app(tmp_path, (8, 7))  # 16 px pictures, no captions
    (tmp_path / "img0.txt").write_text("1girl, solo", encoding="utf-8")
    (tmp_path / "img1.txt").write_text("", encoding="utf-8")
    got = app.check({"min_side": 512})
    assert got["min_side"] == 512 and len(got["issues"]["smaller_than_min_side"]) == 15
    assert got["low_jpeg"] == LOW_JPEG
    assert got["consistency"]["verdict"] in {"tight", "like one artist", "mixed"}
    assert got["issues"]["soft_or_enlarged"] == []  # 16 px: too small to judge
    assert got["issues"]["empty_caption"] == [1] and 0 not in got["issues"]["no_caption"]
    (tmp_path / "img2.png").write_bytes(b"gone bad")  # damaged after the scan
    assert app.check({"min_side": 512})["issues"]["unreadable"] == [2]
    for bad in (10, 100000, "512", True):
        with pytest.raises(ValueError):
            app.check({"min_side": bad})


def test_a_reference_folder_can_be_set_and_cleared_live(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, (8, 7))
    labels = app.clustering.labels.copy()
    ref_dir = tmp_path / "known"
    ref_dir.mkdir()
    ref_vectors = app.raw.style[:3]
    fake = Atlas(ref_dir, [ref_dir / f"r{i}.png" for i in range(3)], ref_vectors, ref_vectors, "s")
    monkeypatch.setattr("styleatlas.serve.build_atlas", lambda path, opts, progress: fake)
    got = app.set_reference({"folder": f'"{ref_dir}"'})
    assert got == {"reference": "known", "images": 3}
    assert app.layout.ref_dist is not None and len(app.layout.ref_dist) == len(app.atlas)
    assert (app.clustering.labels == labels).all()  # groups stay
    assert '"reference":"known"' in app.page()
    assert app.set_reference({"folder": ""}) == {"reference": None, "images": 0}
    for bad in (str(tmp_path / "missing"), 5, "x" * 2000):
        with pytest.raises(ValueError):
            app.set_reference({"folder": bad})
    for network in ("\\\\host\\share", "//host/share"):  # never touched: it would send credentials
        with pytest.raises(ValueError, match="network"):
            app.set_reference({"folder": network})


def test_a_kohya_export_with_chinese_names_writes_a_valid_dataset_config(tmp_path):
    from pathlib import Path

    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    folder = tmp_path / "資料夾"
    folder.mkdir()
    app, _ = _app(folder, (8, 7))
    app.regroup({"threshold": 0.5})
    app.rename({"group": 0, "name": "早期 線稿", "rev": app.revision})
    out = app.export({"mode": "copy", "layout": "kohya", "name": "畫師", "trigger": True})
    root = Path(out["folder"])
    config = tomllib.loads((root / "dataset_config.toml").read_text(encoding="utf-8"))
    dirs = [Path(s["image_dir"]) for s in config["datasets"][0]["subsets"]]
    assert all(d.is_dir() for d in dirs) and any("早期 線稿" in d.name for d in dirs)
    assert config["general"]["keep_tokens"] == 1
    repeats = {Path(s["image_dir"]): s["num_repeats"] for s in config["datasets"][0]["subsets"]}
    pipe = tomllib.loads((root / "diffusion_pipe_dataset.toml").read_text(encoding="utf-8"))
    assert {Path(d["path"]): d["num_repeats"] for d in pipe["directory"]} == repeats
    concepts = json.loads((root / "onetrainer_concepts.json").read_text(encoding="utf-8"))
    assert {Path(c["path"]): c["balancing"] for c in concepts} == repeats
    assert all(c["balancing_strategy"] == "REPEATS" for c in concepts)
    assert all(c["text"]["prompt_source"] == "sample" for c in concepts)
    assert all(c["text"]["keep_tags_count"] == 1 for c in concepts)


def test_each_group_lists_its_closest_groups(tmp_path):
    from styleatlas.report import nearest_groups

    app, _ = _app(tmp_path, (8, 7, 6))
    app.regroup({"threshold": 0.5})
    near = nearest_groups(app.atlas, app.clustering)
    ids = {c.id for c in app.clustering.clusters}
    for gid, rows in near.items():
        assert gid not in [r[0] for r in rows] and {r[0] for r in rows} <= ids
        assert [r[1] for r in rows] == sorted(r[1] for r in rows)
    assert '"near":[[' in app.page()


def test_the_web_export_can_cap_each_group(tmp_path):
    from pathlib import Path

    app, _ = _app(tmp_path, (10, 7))
    app.regroup({"threshold": 0.5})
    out = app.export({"mode": "copy", "layout": "plain", "max_per_group": 4})
    root = Path(out["folder"])
    assert out["trimmed"] == (10 - 4) + (7 - 4)
    assert len(list((root / "_trimmed").glob("*.png"))) == out["trimmed"]
    for bad in (0, "4", 1.5, True):
        with pytest.raises(ValueError):
            app.export({"mode": "copy", "max_per_group": bad})


def test_several_images_are_excluded_or_moved_at_once(tmp_path):
    app, _ = _app(tmp_path, (8, 7))
    app.regroup({"threshold": 0.5})
    assert app.exclude({"items": [1, 2, 2, 3]})["excluded"] == [1, 2, 3]
    assert app.exclude({"items": [2, 3], "excluded": False})["excluded"] == [1]
    for bad in ([], [99], ["1"], [True], "1,2"):
        with pytest.raises(ValueError):
            app.exclude({"items": bad})
    target = int(app.clustering.labels[-1])
    moved = [0, 1, 2]
    app.move({"items": moved, "to": target, "rev": app.revision})
    labels = app.clustering.labels  # group ids are renumbered after an edit
    assert all(labels[i] == labels[-1] for i in moved)
    app.undo({"rev": app.revision})  # the whole batch is one step
    labels = app.clustering.labels
    assert all(labels[i] != labels[-1] for i in moved)


def test_images_are_found_by_a_caption_tag(tmp_path):
    app, _ = _app(tmp_path, (8, 7))
    (tmp_path / "img0.txt").write_text("1girl, Monochrome, greyscale", encoding="utf-8")
    (tmp_path / "img1.txt").write_text("1girl, rough_sketch", encoding="utf-8")
    (tmp_path / "img2.txt").write_text("1girl, colorful", encoding="utf-8")
    assert app.tagged({"tag": "mono"})["hits"] == [0]
    assert app.tagged({"tag": "Rough Sketch"})["hits"] == [1]  # spaces = underscores
    assert app.tagged({"tag": "1girl"})["hits"] == [0, 1, 2]
    for bad in ("", "  ", 5, "x" * 300, "__"):
        with pytest.raises(ValueError):
            app.tagged({"tag": bad})


def test_dropped_images_are_placed_in_a_group_or_called_outside(tmp_path):
    app, _ = _app(tmp_path, (12, 10))
    app.regroup({"threshold": 0.5})
    inside = app.atlas.style[:2]  # images of the first group itself
    rng = np.random.default_rng(3)
    stranger = rng.normal(size=(1, inside.shape[1]))
    stranger /= np.linalg.norm(stranger)
    got = app.fit(np.vstack([inside, stranger]))
    first = int(app.clustering.labels[0])
    assert [g["group"] for g in got[:2]] == [first, first] and got[0]["fits"] and got[1]["fits"]
    assert not got[2]["fits"]
