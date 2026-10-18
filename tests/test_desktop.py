"""The desktop program's parts that need no window: one server showing one folder after another
under its own address prefix, the start page, the folders opened before, stopping a build that
is no longer wanted, and opening an image in the computer's own program."""

from __future__ import annotations

import http.client
import json
import threading

import pytest
from PIL import Image

from styleatlas.atlas import Atlas, EncodeOptions

from .conftest import make_blobs


def _atlas(tmp_path, n=4):
    x, _ = make_blobs([n])
    paths = []
    for i in range(n):
        p = tmp_path / "lib" / f"i{i}.png"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (8, 8), (i, 0, 0)).save(p)
        paths.append(p)
    return Atlas(tmp_path / "lib", paths, x, x, "sig")


def _get(port, path, method="GET", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"X-Style-Atlas": "1", "Content-Type": "application/json"} if method == "POST" else {}
    conn.request(method, path, body=body, headers=headers)
    r = conn.getresponse()
    status, data = r.status, r.read()
    conn.close()
    return status, data


@pytest.fixture
def served(tmp_path):
    from styleatlas.serve import StyleAtlasApp
    from styleatlas.webserver import bind

    app = StyleAtlasApp(_atlas(tmp_path), EncodeOptions(device="cpu"), "pca")
    srv = bind(app, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_pages_under_the_current_prefix_are_answered_and_others_are_not(served):
    port = served.server_address[1]
    served.RequestHandlerClass.token = "abc123"
    assert _get(port, "/s/abc123/thumb/0")[0] == 200
    assert _get(port, "/s/abc123/")[0] == 200
    assert _get(port, "/thumb/0")[0] == 404  # with a token, only its prefix is answered
    assert _get(port, "/api/caption", "POST", json.dumps({"i": 0}))[0] == 404
    assert _get(port, "/s/old999/thumb/0")[0] == 404  # a page left from the folder before
    assert _get(port, "/s/")[0] == 404
    status, data = _get(port, "/s/abc123/api/caption", "POST", json.dumps({"i": 0}))
    assert status == 200 and "tags" in json.loads(data)
    assert _get(port, "/s/old999/api/caption", "POST", json.dumps({"i": 0}))[0] == 404


def test_without_a_token_the_prefix_is_refused_and_plain_paths_still_work(served):
    port = served.server_address[1]
    assert served.RequestHandlerClass.token == ""
    assert _get(port, "/s//thumb/0")[0] == 404
    assert _get(port, "/thumb/0")[0] == 200


def test_a_stand_in_page_answers_no_requests(tmp_path):
    from styleatlas.desktop import RecentFolders, StartPage
    from styleatlas.webserver import bind

    srv = bind(StartPage(RecentFolders(tmp_path / "recent.json")), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        status, page = _get(port, "/")
        assert status == 200 and b"Style Atlas" in page
        assert _get(port, "/thumb/0")[0] == 404
        assert _get(port, "/api/caption", "POST", json.dumps({"i": 0}))[0] == 503
    finally:
        srv.shutdown()
        srv.server_close()


def test_recent_folders_newest_first_without_repeats(tmp_path):
    from styleatlas.desktop import RECENT_MAX, RecentFolders

    recent = RecentFolders(tmp_path / "sub" / "recent.json")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    recent.remember(a)
    recent.remember(b)
    assert recent.remember(a) == [str(a), str(b)]
    rows = recent.rows()
    assert [r["name"] for r in rows] == ["a", "b"] and [r["exists"] for r in rows] == [True, False]
    assert recent.forget(str(b)) == [str(a)]
    for i in range(RECENT_MAX + 3):
        recent.remember(tmp_path / f"f{i}")
    assert len(recent.load()) == RECENT_MAX


def test_a_damaged_recent_file_reads_as_empty(tmp_path):
    from styleatlas.desktop import RecentFolders

    path = tmp_path / "recent.json"
    for text in ("not json", '{"a": 1}', "[1, null, 2]"):
        path.write_text(text, encoding="utf-8")
        assert RecentFolders(path).load() == []


def test_the_start_page_keeps_folder_names_inert(tmp_path):
    from styleatlas.desktop import RecentFolders, StartPage

    recent = RecentFolders(tmp_path / "recent.json")
    recent.remember(tmp_path / "<b>x&y")  # "/" would split the name into folders
    page = StartPage(recent).page()
    assert "<b>x" not in page and "\\u003cb\\u003ex\\u0026y" in page
    assert "/*__START_DATA__*/" not in page


def test_a_dropped_file_opens_its_folder_and_bad_paths_are_refused(tmp_path):
    from styleatlas.desktop import folder_from

    (tmp_path / "pic.png").write_bytes(b"x")
    assert folder_from(str(tmp_path / "pic.png")) == tmp_path.resolve()
    assert folder_from(f"  {tmp_path}  ") == tmp_path.resolve()
    for bad in ("", "   ", None, 3, str(tmp_path / "missing")):
        with pytest.raises(ValueError):
            folder_from(bad)


def test_a_build_for_a_folder_no_longer_shown_stops_and_is_not_shown(tmp_path):
    from styleatlas.desktop import Desktop, RecentFolders
    from styleatlas.webserver import Preparing

    desk = Desktop([], 0, RecentFolders(tmp_path / "recent.json"))
    try:
        preparing = Preparing("one")
        desk._switch(preparing)
        first = desk._generation
        reached = []

        def build(progress):
            progress("started")
            desk.show_home()  # another page shown meanwhile
            progress("embedded 8/100")  # stops here
            reached.append("after")

        desk._build(build, preparing, first, None)
        assert reached == [] and preparing.lines == ["started"] and preparing.error is None
        assert desk.handler.app is desk.home_page
    finally:
        desk.stop()


def test_each_build_is_handed_the_one_before_it(tmp_path):
    from styleatlas.desktop import Desktop, RecentFolders

    desk = Desktop([], 0, RecentFolders(tmp_path / "recent.json"))
    try:
        seen, release = [], threading.Event()

        def work(generation, previous):
            seen.append((generation, previous))
            release.wait(5)

        desk._switch(desk.home_page, tmp_path, work)
        first_thread = desk._builder
        desk._switch(desk.home_page, tmp_path, work)
        release.set()
        desk._builder.join(5)
        assert sorted(g for g, _ in seen) == [1, 2]
        assert dict(seen)[2] is first_thread and dict(seen)[1] is None
        assert desk.folder == tmp_path
    finally:
        desk.stop()


def test_each_switch_gets_a_new_address(tmp_path):
    from styleatlas.desktop import Desktop, RecentFolders

    desk = Desktop([], 0, RecentFolders(tmp_path / "recent.json"))
    try:
        first = desk.url
        second = desk.show_home()
        assert first != second and second.startswith("http://127.0.0.1:") and "/s/" in second
        assert _get(desk.server.server_address[1], "/s/" + second.split("/s/")[1])[0] == 200
        assert _get(desk.server.server_address[1], "/s/" + first.split("/s/")[1])[0] == 404
    finally:
        desk.stop()


def test_open_file_takes_an_index_of_this_folder_only(tmp_path, monkeypatch):
    import styleatlas.serve as serve
    from styleatlas.serve import StyleAtlasApp

    opened = []
    monkeypatch.setattr(serve.os, "startfile", lambda p: opened.append(("open", p)), raising=False)
    monkeypatch.setattr(serve.subprocess, "Popen", lambda args: opened.append(("run", args)))
    app = StyleAtlasApp(_atlas(tmp_path), EncodeOptions(device="cpu"), "pca")
    assert app.open_file({"i": 1}) == {"file": "i1.png"}
    app.open_file({"i": 2, "reveal": True})
    assert len(opened) == 2
    for bad in ({"i": -1}, {"i": 99}, {"i": "0"}, {}):
        with pytest.raises(ValueError):
            app.open_file(bad)
    app.atlas.paths[3].unlink()
    with pytest.raises(ValueError):
        app.open_file({"i": 3})
