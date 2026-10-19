"""The HTTP side of `style-atlas serve`: a small server on 127.0.0.1 that hands the page and
thumbnails out and routes the page's JSON requests to StyleAtlasApp (serve.py).

Defenses: only Host headers naming this server are answered (no DNS rebinding); every POST needs
the X-Style-Atlas header, which a cross-site page cannot send without a preflight this server
never approves; image GETs that the browser marks as cross-site are refused.

`serve_when_ready` opens the page first and builds the app in the background: until it is ready
a `Preparing` stand-in shows the progress (the model download, embedding) in the browser."""

from __future__ import annotations

import html
import json
import os
import re
import socket
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from styleatlas.encoder import ModelDownloadError
from styleatlas.images import IMAGE_TYPES
from styleatlas.lang import tr
from styleatlas.serve import StyleAtlasApp
from styleatlas.webbase import CONTROL_PATH, POST_HEADER, StandIn

MAX_UPLOAD = 40 * 1024 * 1024

JSON_ROUTES = {  # POST route -> StyleAtlasApp method taking the JSON body
    "api/regroup": "regroup",
    "api/move": "move",
    "api/place_unassigned": "place_unassigned",
    "api/split": "split",
    "api/merge": "merge",
    "api/exclude": "exclude",
    "api/keep_copy": "keep_copy",
    "api/taste": "vote",
    "api/next": "next_to_rate",
    "api/path": "path",
    "api/space": "set_space",
    "api/rename": "rename",
    "api/undo": "undo",
    "api/similar": "similar",
    "api/compare": "compare",
    "api/check": "check",
    "api/reference": "set_reference",
    "api/tagged": "tagged",
    "api/caption": "caption",
    "api/note": "note",
    "api/search_set": "search_set",
    "api/save_map": "save_map",
    "api/artist_map": "artist_map",
    "api/artists": "artists",
    "api/save_report": "save_report",
    "api/open_output": "open_output",
    "api/open_export": "open_export",
    "api/share_sizes": "share_sizes",
    "api/open_file": "open_file",
    "api/copy_hits": "copy_hits",
    "api/export": "export",
    "api/export_plan": "export_plan",
}
REQUEST_ERRORS = (ValueError, OSError, KeyError, TypeError, OverflowError, ModelDownloadError)
PREPARING_LINES = 12  # progress lines the waiting page shows


class Preparing(StandIn):
    """Stands in for StyleAtlasApp while it is built: the waiting page and its progress."""

    def __init__(self, title: str):
        self.title = title
        self.lines: list[str] = []
        self.error: str | None = None
        self.started = time.monotonic()
        self._lock = threading.Lock()

    def progress(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
        with self._lock:
            self.lines = [*self.lines, msg][-PREPARING_LINES:]

    def fail(self, e: BaseException) -> None:
        known = isinstance(e, (*REQUEST_ERRORS, RuntimeError))
        if not known:
            traceback.print_exc()
        message = (
            str(e)
            if known
            else tr(
                f"internal error ({type(e).__name__}); see the console",
                f"内部错误（{type(e).__name__}）；详情见控制台",
            )
        )
        print(message, file=sys.stderr, flush=True)
        self.error = message

    def status(self) -> dict:
        with self._lock:
            return {"ready": False, "lines": self.lines, "error": self.error}

    def page(self) -> str:
        text = {
            "elapsed": tr("({m}:{s} so far)", "（已经过 {m}:{s}）"),
            "failed": tr("Could not prepare the map:", "无法准备地图："),
        }
        heading = tr(f"Preparing {self.title}", f"正在准备 {self.title}")
        note = tr(
            "The map opens here by itself when the styles are ready. The first run downloads the "
            "style model once (about 2.4 GB); after that only new images are computed.",
            "画风算好后，地图会自动在这里打开。第一次使用会先下载一次画风模型（约 2.4 GB）；"
            "之后只会计算新加入的图。",
        )
        page = resources.files("styleatlas").joinpath("templates/preparing.html").read_text("utf-8")
        values = {
            "__LANG__": tr("en", "zh-Hans"),
            "__TITLE__": html.escape(self.title),
            "__HEADING__": html.escape(heading),
            "__NOTE__": html.escape(note),
            "/*__TEXT__*/{}": json.dumps(text, ensure_ascii=False),
        }  # one pass: a title that happens to contain a placeholder stays as it is
        pattern = re.compile("|".join(re.escape(key) for key in values))
        return pattern.sub(lambda m: values[m.group(0)], page)


class StyleAtlasHandler(BaseHTTPRequestHandler):
    """Request handler; `make_handler` binds `app` and `allowed_hosts` on a subclass.

    With `sites` set (the desktop program: several windows, each showing one folder after
    another, on one server) each page lives under /s/<token>/ and is answered by sites[token]:
    each folder's thumbnails get their own addresses, so none is taken from the browser cache of
    the folder opened before, and a page left from that folder gets no answers. `control` takes
    a later start's request for a window (desktop.Desktop.remote)."""

    app: StyleAtlasApp | StandIn
    allowed_hosts: frozenset[str] = frozenset()
    sites: dict[str, StyleAtlasApp | StandIn] | None = None
    control: Callable[[dict], bool] | None = None

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

    def _parts(self) -> list[str] | None:
        """The request path in parts, without the /s/<token> prefix, with `self.app` the one
        that answers it; None after a 404 for a prefix no window shows, or for no prefix in the
        desktop program."""
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts[0] != "s" and self.sites is None:  # `serve`: plain paths
            return parts
        site = self.sites.get(parts[1]) if len(parts) > 1 and self.sites else None
        if parts[0] != "s" or site is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        self.app = site
        return parts[2:] or [""]

    def _image_index(self, part: str) -> int | None:
        try:
            i = int(part)
        except ValueError:
            return None
        return i if 0 <= i < len(self.app.atlas) else None

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        parts = self._parts()
        if parts is None:
            return
        if parts == [""]:
            try:
                page = self.app.page().encode("utf-8")
            except Exception:  # noqa: BLE001 - show something instead of a blank tab
                self.log_error("page failed:\n%s", traceback.format_exc())
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "see the console for details")
                return
            self._send(200, page, "text/html; charset=utf-8")
            return
        if parts == ["status"]:  # the waiting page asks until the app is ready
            app = self.app
            self._json(200, app.status() if isinstance(app, Preparing) else {"ready": True})
            return
        if parts == ["artist_map"] and not isinstance(self.app, StandIn):  # written on request
            page = self.app.artist_map_html()
            if page is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._send(200, page, "text/html; charset=utf-8")
            return
        if parts == ["favicon.ico"]:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        i = self._image_index(parts[1]) if len(parts) == 2 else None
        if i is not None and self.headers.get("Sec-Fetch-Site", "same-origin") not in (
            "same-origin",
            "none",
        ):  # other sites could otherwise probe the image list through <img> tags
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if parts[0] == "thumb" and i is not None:
            self._send(200, self.app.thumb(i), "image/webp")
        elif parts[0] == "view" and i is not None:
            self._send(200, self.app.view_thumb(i), "image/webp")
        elif parts[0] == "image" and i is not None:
            path = self.app.atlas.paths[i]
            ctype = IMAGE_TYPES.get(path.suffix.lower(), "application/octet-stream")
            try:
                data = path.read_bytes()
            except OSError:  # moved or deleted since the folder was opened
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send(200, data, ctype)
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
        if self.path == CONTROL_PATH and self.control is not None:
            self._control(body)
            return
        parts = self._parts()
        if parts is None:
            return
        route = "/".join(parts)
        if isinstance(self.app, StandIn):
            self._json(503, {"error": tr("still preparing", "还在准备中")})
            return
        try:
            if route == "api/search":
                self._json(200, self.app.search_image(body))
            elif route in JSON_ROUTES:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON object")
                self._json(200, getattr(self.app, JSON_ROUTES[route])(payload))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except REQUEST_ERRORS as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - the page must get an answer, not a dropped line
            self.log_error("%s failed:\n%s", route, traceback.format_exc())
            self._json(500, {"error": f"internal error ({type(e).__name__}); see the console"})

    def _control(self, body: bytes) -> None:
        """A later start of the desktop program asking this one for a window."""
        try:
            payload = json.loads(body)
            done = isinstance(payload, dict) and self.control(payload)
        except ValueError:
            done = False
        if done:
            self._json(200, {"ok": True})
        else:
            self.send_error(HTTPStatus.FORBIDDEN)


def make_handler(
    app: StyleAtlasApp | StandIn, allowed_hosts: set[str]
) -> type[BaseHTTPRequestHandler]:
    attrs = {"app": app, "allowed_hosts": frozenset(allowed_hosts)}
    return type("BoundStyleAtlasHandler", (StyleAtlasHandler,), attrs)


class _Server(ThreadingHTTPServer):
    # The page asks for many thumbnails at once; Windows refuses connections beyond the listen
    # backlog (5 by default) while the server is busy, e.g. making thumbnails right after start.
    request_queue_size = 64
    daemon_threads = True
    # HTTPServer sets SO_REUSEADDR, and on Windows that lets a second server bind a port already
    # in use: a second copy of the program then shared this one's port and its window was answered
    # by the first copy (404). An exclusive port makes bind() move on to the next one.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address) -> None:
        # The browser drops thumbnail requests it no longer needs (a scrolled-past list, a closed
        # tab): nothing went wrong, so no traceback in the console
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def bind(app: StyleAtlasApp | StandIn, port: int = 8770) -> ThreadingHTTPServer:
    """Server on the first free port from `port`, wired to `app` (not yet serving)."""
    server = None
    for candidate in range(port, port + 20):
        try:
            server = _Server(("127.0.0.1", candidate), BaseHTTPRequestHandler)
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
    _run(server, open_browser)


def serve_when_ready(
    build: Callable[[Callable[[str], None]], StyleAtlasApp],
    title: str,
    port: int = 8770,
    open_browser: bool = True,
) -> bool:
    """Open the page at once and build the app (`build(progress)`) in the background; the page
    shows the progress and turns into the app when it is ready, or shows why it failed. Without
    a browser (scripts) a failed build stops the server. False when the build failed."""
    preparing = Preparing(title)
    server = bind(preparing, port)
    handler = server.RequestHandlerClass

    def work() -> None:
        try:
            app = build(preparing.progress)
            app.prewarm()
        except BaseException as e:  # noqa: BLE001 - the page must learn why, whatever it was
            preparing.fail(e)
            if not open_browser:  # nobody is looking at the page
                server.shutdown()
            return
        handler.app = app
        print(tr("ready", "准备好了"), flush=True)

    builder = threading.Thread(target=work, name="style-atlas-build", daemon=True)
    builder.start()
    interrupted = _run(server, open_browser)
    if interrupted and builder.is_alive():  # Ctrl+C while still preparing: torch may be mid-batch
        print(
            tr(
                "stopped while preparing; the images computed so far are kept for next time",
                "准备到一半就停止了；已经算好的图会保留，下次会接着算",
            ),
            flush=True,
        )
        sys.stderr.flush()
        os._exit(1)  # a daemon thread inside torch can hang the normal interpreter exit
    return preparing.error is None


def _run(server: ThreadingHTTPServer, open_browser: bool) -> bool:
    """Serve until stopped; True when stopped by Ctrl+C."""
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(
        tr(
            f"style-atlas is running at {url}  (Ctrl+C to stop)",
            f"style-atlas 已打开：{url}（关掉这个窗口或按 Ctrl+C 结束）",
        ),
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return True
    finally:
        server.server_close()
    return False
