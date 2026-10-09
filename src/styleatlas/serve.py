"""Local web app: the 3D map plus live search (drop an image), re-grouping and folder export.

Security model: the server binds to 127.0.0.1 only, answers only requests whose Host header is
the local address (blocks DNS-rebinding pages from reading your images), serves files only by
index into the scanned folder (no paths from the client), and requires a custom header on every
POST (a cross-site form or simple request cannot set it).
"""

from __future__ import annotations

import io
import json
import mimetypes
import threading
import webbrowser
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from styleatlas.atlas import LOAD_ERRORS, Atlas, EncodeOptions, get_encoder
from styleatlas.cluster import (
    GRANULARITY,
    METHODS,
    UNASSIGNED,
    cluster_styles,
    edit_groups,
    split_group,
)
from styleatlas.dataset import plan_folders
from styleatlas.export import export_folders, output_dir, write_table
from styleatlas.images import cached_thumbnail, load_rgb
from styleatlas.metrics import Neutralizer
from styleatlas.persist import RelPathMap
from styleatlas.report import build_payload, compute_layout, default_thumb_px, render_html
from styleatlas.search import search, style_path
from styleatlas.taste_session import TasteSession

MAX_UPLOAD = 40 * 1024 * 1024
POST_HEADER = "X-Style-Atlas"
SEARCH_TOP = 48
MAX_SPLIT = 4000  # splitting runs under the lock; larger groups would stall every request


class StyleAtlasApp:
    """Holds one scanned folder in memory and answers the web page's requests."""

    def __init__(
        self,
        atlas: Atlas,
        opts: EncodeOptions,
        projection: str = "auto",
        title: str | None = None,
        progress: Callable[[str], None] = lambda _: None,
        time_source: str = "none",
        neutral: Neutralizer | None = None,
        reference: Atlas | None = None,
    ):
        self.opts = opts
        self.title = title
        self.time_source = time_source
        self.neutral = neutral or Neutralizer.fit(atlas.style, 0)
        self.atlas = atlas
        self.layout = compute_layout(self.atlas, projection, progress, reference)
        self.settings: dict = {"method": "agglomerative", "threshold": GRANULARITY["medium"]}
        self.clustering = cluster_styles(self.atlas.style, threshold=self.settings["threshold"])
        self.revision = 0  # bumped on every regroup / hand edit; edits must name the one they saw
        self.thumb_px = default_thumb_px(len(self.atlas))
        self._thumbs: dict[int, bytes] = {}
        self._lock = threading.Lock()
        self.taste = TasteSession(atlas, self.out_dir)
        self._excluded = RelPathMap(self.out_dir / "excluded.json", atlas)
        self.excluded: set[int] = {i for i, v in self._excluded.values.items() if v is True}

    @property
    def out_dir(self) -> Path:
        return output_dir(self.atlas.root)

    def page(self) -> str:
        with self._lock:  # votes and exclusions may change in another request thread
            payload = build_payload(
                self.atlas,
                self.clustering,
                self.layout,
                lambda i: f"thumb/{i}",
                lambda i: f"image/{i}",
                self.title,
                self.time_source,
            )
            payload["live"] = {
                "settings": dict(self.settings),
                "granularity": GRANULARITY,
                "taste": self.taste.state(),
                "excluded": sorted(self.excluded),
                "revision": self.revision,
            }
        return render_html(payload)

    def thumb(self, i: int) -> bytes:
        if i not in self._thumbs:
            try:
                self._thumbs[i] = cached_thumbnail(self.atlas.paths[i], size=self.thumb_px)
            except LOAD_ERRORS:
                self._thumbs[i] = b""
        return self._thumbs[i]

    def prewarm(self, workers: int = 4) -> None:
        """Make every thumbnail in the background, so the page is ready when it is opened."""
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="thumbs")
        for i in range(len(self.atlas)):
            pool.submit(self.thumb, i)
        pool.shutdown(wait=False)

    def regroup(self, body: dict) -> dict:
        method = body.get("method", "agglomerative")
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        threshold = body.get("threshold", GRANULARITY["medium"])
        k = body.get("k")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ValueError("threshold must be a number")
        if k is not None and type(k) is not int:
            raise ValueError("k must be a whole number")
        if not 0.05 <= threshold <= 1.5 or (k is not None and not 1 <= k <= len(self.atlas)):
            raise ValueError("threshold must be 0.05-1.5 and k between 1 and the image count")
        with self._lock:
            self.clustering = cluster_styles(
                self.atlas.style, method=method, threshold=threshold, n_clusters=k
            )
            self.settings = {"method": method, "threshold": threshold, "k": k}
            self.revision += 1
        return {"clusters": self.clustering.n_clusters, "unassigned": self.clustering.n_unassigned}

    def search_image(self, data: bytes, top: int = SEARCH_TOP) -> list[dict]:
        try:
            image = load_rgb(io.BytesIO(data))
        except LOAD_ERRORS as e:
            raise ValueError(f"not a readable image: {e}") from e
        with self._lock:
            query = self.neutral.apply(get_encoder(self.opts).encode([image]).style)
        hits = search(query, self.atlas.style, top=top)[0]
        return [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits]

    def _group(self, value: object, allow_unassigned: bool) -> int:
        if type(value) is not int:
            raise ValueError("group must be a whole number")
        if value == UNASSIGNED and allow_unassigned:
            return value
        if not 0 <= value < self.clustering.n_clusters:
            raise ValueError("no such group")
        return value

    def _check_revision(self, body: dict) -> None:
        """Group ids change after every edit; refuse an edit made on an outdated page."""
        if body.get("rev") != self.revision:
            raise ValueError("the groups changed in another tab or edit; reload the page")

    def _edited(self, clustering) -> dict:
        self.clustering = clustering
        self.settings = {**self.settings, "edited": True}
        self.revision += 1
        return {"clusters": self.clustering.n_clusters, "revision": self.revision}

    def move(self, body: dict) -> dict:
        """Hand edit: put one image into another group (or unassigned)."""
        i = self._index(body)
        with self._lock:
            self._check_revision(body)
            target = self._group(body.get("to"), allow_unassigned=True)
            return self._edited(edit_groups(self.atlas.style, self.clustering, {i: target}))

    def merge(self, body: dict) -> dict:
        """Hand edit: merge one group into another."""
        with self._lock:
            self._check_revision(body)
            source = self._group(body.get("from"), allow_unassigned=False)
            target = self._group(body.get("into"), allow_unassigned=False)
            if source == target:
                raise ValueError("pick two different groups")
            members = self.clustering.clusters[source].members
            moves = {m: target for m in members}
            return self._edited(edit_groups(self.atlas.style, self.clustering, moves))

    def split(self, body: dict) -> dict:
        """Hand edit: cut one group in two."""
        with self._lock:
            self._check_revision(body)
            group = self._group(body.get("group"), allow_unassigned=False)
            if self.clustering.clusters[group].size > MAX_SPLIT:
                raise ValueError("group too large to split here; regroup with a lower threshold")
            return self._edited(split_group(self.atlas.style, self.clustering, group))

    def _index(self, body: dict) -> int:
        i = body.get("i")
        if type(i) is not int or not 0 <= i < len(self.atlas):
            raise ValueError("i must be an image index")
        return i

    def exclude(self, body: dict) -> dict:
        i = self._index(body)
        excluded = body.get("excluded", True)
        if not isinstance(excluded, bool):
            raise ValueError("excluded must be true or false")
        with self._lock:
            if excluded:
                self.excluded.add(i)
            else:
                self.excluded.discard(i)
            self._excluded.values = {j: True for j in self.excluded}
            self._excluded.save()
            return {"excluded": sorted(self.excluded)}

    def path(self, body: dict) -> dict:
        a = self._index({"i": body.get("a")})
        b = self._index({"i": body.get("b")})
        steps = body.get("steps", 8)
        if type(steps) is not int or not 1 <= steps <= 40:
            raise ValueError("steps must be a whole number from 1 to 40")
        with self._lock:
            skip = set(self.excluded)
        return {"path": style_path(self.atlas.style, a, b, steps, skip=skip)}

    def next_to_rate(self, body: dict) -> dict:
        with self._lock:
            return {"i": self.taste.next_to_rate(skip=set(self.excluded))}

    def vote(self, body: dict) -> dict:
        i = self._index(body)
        like = body.get("like")
        if like is not None and not isinstance(like, bool):
            raise ValueError("like must be true, false or null")
        with self._lock:
            return self.taste.vote(i, like)

    def export(self, body: dict) -> dict:
        mode = body.get("mode", "copy")
        out = self.out_dir
        with self._lock:
            folders = plan_folders(
                self.atlas.paths,
                self.clustering,
                duplicate_groups=self.layout.duplicates,
                excluded=sorted(self.excluded),
            )
            write_table(self.atlas, self.clustering, out, folders)
            result = export_folders(self.atlas, folders, out / "folders", mode=mode)
        return {"placed": result.placed, "failed": len(result.failed), "folder": str(result.folder)}


JSON_ROUTES = {  # POST route -> StyleAtlasApp method taking the JSON body
    "api/regroup": "regroup",
    "api/move": "move",
    "api/split": "split",
    "api/merge": "merge",
    "api/exclude": "exclude",
    "api/taste": "vote",
    "api/next": "next_to_rate",
    "api/path": "path",
    "api/export": "export",
}
REQUEST_ERRORS = (ValueError, OSError, KeyError, TypeError, OverflowError)


class StyleAtlasHandler(BaseHTTPRequestHandler):
    """Request handler; `make_handler` binds `app` and `allowed_hosts` on a subclass."""

    app: StyleAtlasApp
    allowed_hosts: frozenset[str] = frozenset()

    def log_message(self, fmt: str, *args: object) -> None:  # keep the console quiet
        return

    def _host_ok(self) -> bool:
        if self.headers.get("Host", "") in self.allowed_hosts:
            return True
        self.send_error(HTTPStatus.FORBIDDEN, "unexpected Host header")
        return False

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        cache = "no-store" if ctype.startswith("text/html") else "max-age=3600"
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json")

    def _image_index(self, part: str) -> int | None:
        try:
            i = int(part)
        except ValueError:
            return None
        return i if 0 <= i < len(self.app.atlas) else None

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts == [""]:
            self._send(200, self.app.page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if parts == ["favicon.ico"]:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        i = self._image_index(parts[1]) if len(parts) == 2 else None
        if parts[0] == "thumb" and i is not None:
            self._send(200, self.app.thumb(i), "image/webp")
        elif parts[0] == "image" and i is not None:
            path = self.app.atlas.paths[i]
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._send(200, path.read_bytes(), ctype)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _read_body(self) -> bytes | None:
        """The POST body, or None after an error response (bad host, header or size)."""
        if not self._host_ok():
            return None
        if self.headers.get(POST_HEADER) != "1":
            self.send_error(HTTPStatus.FORBIDDEN, f"missing {POST_HEADER} header")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_UPLOAD:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        return self.rfile.read(length)

    def do_POST(self) -> None:
        body = self._read_body()
        if body is None:
            return
        route = self.path.split("?")[0].strip("/")
        try:
            if route == "api/search":
                self._json(200, {"hits": self.app.search_image(body)})
            elif route in JSON_ROUTES:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
                self._json(200, getattr(self.app, JSON_ROUTES[route])(payload))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except REQUEST_ERRORS as e:
            self._json(400, {"error": str(e)})


def make_handler(app: StyleAtlasApp, allowed_hosts: set[str]) -> type[BaseHTTPRequestHandler]:
    attrs = {"app": app, "allowed_hosts": frozenset(allowed_hosts)}
    return type("BoundStyleAtlasHandler", (StyleAtlasHandler,), attrs)


def bind(app: StyleAtlasApp, port: int = 8770) -> ThreadingHTTPServer:
    """Server on the first free port from `port`, wired to `app` (not yet serving)."""
    server = None
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), BaseHTTPRequestHandler)
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"no free port in {port}-{port + 19}")
    bound = server.server_address[1]
    hosts = {f"127.0.0.1:{bound}", f"localhost:{bound}"}
    server.RequestHandlerClass = make_handler(app, hosts)
    return server


def serve(app: StyleAtlasApp, port: int = 8770, open_browser: bool = True) -> None:
    server = bind(app, port)
    app.prewarm()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"style-atlas is running at {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
