from __future__ import annotations

import hashlib
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from styleatlas import fetch

DATA = os.urandom(3 * 1024 * 1024 + 123)
SHA = hashlib.sha256(DATA).hexdigest()


class Source(BaseHTTPRequestHandler):
    """/good, /early (closes after 1 MB), /stall (stops after 1 MB), /norange (ignores Range),
    /wrong (other bytes), /slow (trickles), /page (a login page instead of the file),
    /badrange (a wrong Content-Range), /simple/pkg/ (a pip index page), /local/pkg/ (an index
    pointing at a local file)."""

    ranges: list[int] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        mode = self.path.strip("/").split("/")[0]
        pages = {
            "simple": '<a href="/good/pkg-1.0-cp313-cp313-win_amd64.whl#sha256=00">w</a>'
            '<a href="/good/pkg-1.0.tar.gz">s</a>',
            "local": '<a href="file:///C:/Windows/win.ini/pkg-1.0-cp313-cp313-win_amd64.whl">w</a>',
            "page": "<html><body>Please log in to this Wi-Fi first</body></html>",
        }
        if mode in pages:
            Source.ranges.append(-1)
            body = pages[mode].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = os.urandom(len(DATA)) if mode == "wrong" else DATA
        start = 0
        header = self.headers.get("Range")
        if header and mode != "norange":
            start = int(header.split("=")[1].rstrip("-"))
        Source.ranges.append(start)
        self.send_response(206 if start else 200)
        if start:
            first = 0 if mode == "badrange" else start  # badrange: claims a part from byte 0
            self.send_header("Content-Range", f"bytes {first}-{len(data) - 1}/{len(data)}")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data) - start))
        self.end_headers()
        body = data[start:]
        limit = 1024 * 1024
        try:
            if mode in ("early", "stall"):
                self.wfile.write(body[:limit])
                self.wfile.flush()
                if mode == "stall":
                    time.sleep(3)
                return
            if mode == "slow":
                for i in range(0, len(body), 64 * 1024):
                    self.wfile.write(body[i : i + 64 * 1024])
                    time.sleep(0.05)
                return
            self.wfile.write(body)
        except OSError:
            pass


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(fetch, "STALL_SECONDS", 0.5)
    Source.ranges = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def run(sources, tmp_path):
    dest = tmp_path / "model.bin"
    seen = []
    ranking = [(url, 1.0) for url in sources]
    fetch.download(ranking, dest, SHA, len(DATA), lambda d, t, h: seen.append((d, t)))
    return dest, seen


def test_downloads_and_checks_the_file(server, tmp_path):
    dest, seen = run([f"{server}/good"], tmp_path)
    assert dest.read_bytes() == DATA
    assert seen[-1] == (len(DATA), len(DATA))
    assert not (tmp_path / "model.bin.part").exists()


def test_continues_a_part_left_by_an_earlier_try(server, tmp_path):
    (tmp_path / "model.bin.part").write_bytes(DATA[:2_000_000])
    dest, _ = run([f"{server}/good"], tmp_path)
    assert dest.read_bytes() == DATA
    assert Source.ranges == [2_000_000]


@pytest.mark.parametrize("broken", ["early", "stall"])
def test_switches_source_at_the_same_byte(server, tmp_path, broken):
    dest, _ = run([f"{server}/{broken}", f"{server}/good"], tmp_path)
    assert dest.read_bytes() == DATA
    assert Source.ranges == [0, 1024 * 1024]


def test_a_source_ignoring_range_still_gives_the_right_file(server, tmp_path):
    dest, _ = run([f"{server}/early", f"{server}/norange"], tmp_path)
    assert dest.read_bytes() == DATA


def test_a_much_slower_source_hands_over(server, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "SLOW_AFTER", 0.3)
    dest = tmp_path / "model.bin"
    ranking = [(f"{server}/slow", 1e9), (f"{server}/good", 1e9)]
    fetch.download(ranking, dest, SHA, len(DATA), lambda d, t, h: None)
    assert dest.read_bytes() == DATA
    assert len(Source.ranges) == 2 and Source.ranges[1] > 0


def test_a_file_that_does_not_match_is_thrown_away(server, tmp_path):
    with pytest.raises(fetch.FetchError, match="SHA256"):
        run([f"{server}/wrong"], tmp_path)
    assert not (tmp_path / "model.bin").exists()
    assert not (tmp_path / "model.bin.part").exists()


def test_gives_up_when_no_source_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "ROUND_PAUSE", 0)
    started = time.monotonic()
    with pytest.raises(fetch.FetchError, match="127.0.0.1"):
        run(["http://127.0.0.1:9/a", "http://127.0.0.1:9/b"], tmp_path)
    assert time.monotonic() - started < 30


def test_ranks_the_fastest_first_and_keeps_order_on_ties(server):
    ranking = fetch.ranked(
        ["http://127.0.0.1:9/x", f"{server}/good", f"{server}/slow"], fetch.file_speed
    )
    assert [url.rsplit("/", 1)[-1] for url, _ in ranking] == ["good", "slow", "x"]
    assert ranking[-1][1] == 0.0
    same = fetch.ranked(["a", "b"], lambda url: 5.0)
    assert [url for url, _ in same] == ["a", "b"]


def test_index_speed_reads_a_wheel_the_page_lists(server):
    speed = fetch.index_speed(f"{server}/simple", "pkg", lambda name: "win_amd64" in name)
    assert speed > 0
    assert fetch.index_speed(f"{server}/simple", "pkg", lambda name: "linux" in name) == 0.0


def test_describe_names_hosts_and_speeds():
    text = fetch.describe([("https://hf-mirror.com/x", 12.3e6), ("https://huggingface.co/x", 0)])
    assert text == "hf-mirror.com 12.3 MB/s · huggingface.co no answer"


def test_a_login_page_never_ends_up_in_the_download(server, tmp_path):
    dest, _ = run([f"{server}/page", f"{server}/good"], tmp_path)
    assert dest.read_bytes() == DATA
    assert Source.ranges == [-1, 0]  # the page was refused before a byte was written


def test_a_source_answering_from_the_wrong_byte_is_refused(server, tmp_path):
    (tmp_path / "model.bin.part").write_bytes(DATA[:1000])
    dest, _ = run([f"{server}/badrange", f"{server}/good"], tmp_path)
    assert dest.read_bytes() == DATA
    assert Source.ranges == [1000, 1000]


def test_index_links_to_local_files_are_not_followed(server):
    assert fetch.index_speed(f"{server}/local", "pkg", lambda name: True) == 0.0
