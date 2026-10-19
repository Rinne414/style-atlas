"""The desktop program's parts that need no window: one server for several windows, each
showing one folder after another under its own address prefix, the start page, the folders
opened before, builds that take turns and stop when no longer wanted, a later start handing over
to the copy that is open, and opening an image in the computer's own program."""

from __future__ import annotations

import http.client
import json
import threading
import time

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
    served.RequestHandlerClass.sites = {"abc123": served.RequestHandlerClass.app}
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
    assert served.RequestHandlerClass.sites is None
    assert _get(port, "/s//thumb/0")[0] == 404
    assert _get(port, "/thumb/0")[0] == 200


def test_a_second_copy_of_the_program_gets_its_own_port(tmp_path):
    from styleatlas.desktop import RecentFolders, StartPage
    from styleatlas.webserver import bind

    # Windows let two servers share a port: the second copy's window was answered by the first
    # one, which knows no such address (404)
    page = StartPage(RecentFolders(tmp_path / "recent.json"))
    first = bind(page, port=20480)
    second = bind(page, port=first.server_address[1])
    try:
        assert second.server_address[1] != first.server_address[1]
    finally:
        first.server_close()
        second.server_close()


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


def _desk(tmp_path):
    from styleatlas.desktop import Desktop, RecentFolders

    return Desktop([], 0, RecentFolders(tmp_path / "recent.json"))


def _path_of(url):
    return "/s/" + url.split("/s/")[1]


def test_a_build_for_a_folder_no_longer_shown_stops_and_is_not_shown(tmp_path):
    from styleatlas.webserver import Preparing

    desk = _desk(tmp_path)
    try:
        pane = desk.add_pane()
        preparing = Preparing("one")
        desk._switch(pane, preparing, tmp_path)
        first = pane.generation
        reached = []

        def build(progress):
            progress("started")
            desk.show_home(pane)  # the window went back to the start page meanwhile
            progress("embedded 8/100")  # stops here
            reached.append("after")

        desk._build(pane, build, preparing, first)
        assert reached == [] and preparing.lines == ["started"] and preparing.error is None
        assert pane.app is desk.home_page and desk.handler.sites[pane.token] is desk.home_page
        assert not desk._model.locked()  # the next folder may go ahead
    finally:
        desk.stop()


def test_two_windows_show_two_folders_at_once(tmp_path):
    from styleatlas.serve import StyleAtlasApp

    desk = _desk(tmp_path)
    try:
        port = desk.server.server_address[1]
        one, two = desk.add_pane(), desk.add_pane()
        app = StyleAtlasApp(_atlas(tmp_path), EncodeOptions(device="cpu"), "pca")
        first = desk._switch(one, app, tmp_path / "lib")
        second = desk.show_home(two)
        assert first != second
        assert _get(port, _path_of(first) + "thumb/0")[0] == 200
        assert _get(port, _path_of(second) + "thumb/0")[0] == 404  # a start page has no images
        assert b"Style Atlas" in _get(port, _path_of(second))[1]
        assert desk.showing(tmp_path / "lib") is one and desk.showing(tmp_path) is None
        desk.close(one)  # its window was closed: the folder is let go
        assert _get(port, _path_of(first) + "thumb/0")[0] == 404
        assert desk.showing(tmp_path / "lib") is None and desk.panes == [two]
        assert _get(port, _path_of(second))[0] == 200
    finally:
        desk.stop()


def test_a_folder_opens_in_one_window_and_a_closed_window_stays_closed(tmp_path, monkeypatch):
    desk = _desk(tmp_path)
    shown = lambda pane, folder: desk._switch(pane, desk.home_page, folder)  # noqa: E731 - no build
    monkeypatch.setattr(desk, "open_folder", shown)
    monkeypatch.setattr(desk, "open_window", lambda folder=None, **_: None)  # no real window
    try:
        one, two = desk.add_pane(), desk.add_pane()
        assert desk.claim(tmp_path, one)[0] is one
        other, url = desk.claim(tmp_path, two)
        assert other is one and url is None and two.folder is None
        assert desk.claim(tmp_path, one)[1]  # the window that has it may open it again
        desk.show_home(two)
        old = two.token
        desk.close(two)
        assert desk.show_home(two) == "" and two.token == old and old not in desk.handler.sites
        assert desk.remote({"key": desk.key}) is True
        desk.close(one)
        assert desk.remote({"key": desk.key}) is False  # the last window is closing
    finally:
        desk.stop()


def test_folders_take_turns_on_the_model_and_a_closed_window_stops_its_turn(tmp_path):
    from styleatlas.webserver import Preparing

    desk = _desk(tmp_path)
    try:
        one, two = desk.add_pane(), desk.add_pane()
        started, release = threading.Event(), threading.Event()
        order = []

        def slow(progress):
            order.append("one")
            started.set()
            release.wait(5)
            progress("done")
            return _Ready()

        def quick(progress):
            order.append("two")
            return _Ready()

        waiting = Preparing("two")
        desk._switch(
            one,
            Preparing("one"),
            tmp_path / "a",
            lambda g: desk._build(one, slow, Preparing("one"), g),
        )
        assert started.wait(5)
        desk._switch(two, waiting, tmp_path / "b", lambda g: desk._build(two, quick, waiting, g))
        _wait_for(lambda: waiting.lines)
        assert order == ["one"]  # the second folder waits for the first
        assert any(word in waiting.lines[0] for word in ("another window", "另一個視窗"))
        release.set()
        _wait_for(lambda: isinstance(two.app, _Ready))
        assert order == ["one", "two"] and isinstance(one.app, _Ready)

        three = desk.add_pane()
        hold = threading.Event()
        desk._switch(
            three,
            Preparing("three"),
            tmp_path / "c",
            lambda g: desk._build(three, lambda p: hold.wait(5) and p("x"), Preparing("three"), g),
        )
        _wait_for(desk._model.locked)
        desk.close(three)  # closed while preparing
        hold.set()
        _wait_for(lambda: not desk._model.locked())
        assert three.app is None
    finally:
        desk.stop()


class _Ready:
    def prewarm(self):
        return None


def _wait_for(cond, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_a_later_start_hands_over_to_the_open_copy(tmp_path, monkeypatch):
    from styleatlas import desktop

    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path / "cache"))
    assert desktop._hand_over(None) is False  # nothing open
    desk = _desk(tmp_path)
    desk.add_pane()  # a window is open
    asked = []
    monkeypatch.setattr(desk, "open_window", lambda folder=None, **_: asked.append(folder))
    marker = tmp_path / "cache" / desktop.OPEN_FILE
    try:
        desk.announce(marker)
        assert desktop._hand_over(None) is True  # answered before the window is made
        _wait_for(lambda: asked == [None])
        assert desktop._hand_over(str(tmp_path)) is True
        _wait_for(lambda: len(asked) == 2)
        assert asked[-1] == tmp_path.resolve()
        info = json.loads(marker.read_text("utf-8"))
        marker.write_text(json.dumps({**info, "key": "guessed"}), "utf-8")
        assert desktop._hand_over(None) is False and len(asked) == 2  # a wrong key opens nothing
        marker.write_text(json.dumps(info), "utf-8")
        desk.retire(marker)
        assert not marker.exists()
    finally:
        desk.stop()
    marker.write_text(json.dumps(info), "utf-8")  # left by a copy that ended without tidying up
    assert desktop._hand_over(None) is False


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
