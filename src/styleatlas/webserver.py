"""The HTTP side of `style-atlas serve`: a small server on 127.0.0.1 that hands the page and
thumbnails out and routes the page's JSON requests to StyleAtlasApp (serve.py).

Defenses: only Host headers naming this server are answered (no DNS rebinding); every POST needs
the X-Style-Atlas header, which a cross-site page cannot send without a preflight this server
never approves; image GETs that the browser marks as cross-site are refused."""

from __future__ import annotations

import json
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from styleatlas.encoder import ModelDownloadError
from styleatlas.images import IMAGE_TYPES
from styleatlas.lang import tr
from styleatlas.serve import StyleAtlasApp

MAX_UPLOAD = 40 * 1024 * 1024
POST_HEADER = "X-Style-Atlas"

JSON_ROUTES = {  # POST route -> StyleAtlasApp method taking the JSON body
    "api/regroup": "regroup",
    "api/move": "move",
    "api/place_unassigned": "place_unassigned",
    "api/split": "split",
    "api/merge": "merge",
    "api/exclude": "exclude",
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
    "api/save_report": "save_report",
    "api/open_output": "open_output",
    "api/copy_hits": "copy_hits",
    "api/export": "export",
    "api/export_plan": "export_plan",
}
REQUEST_ERRORS = (ValueError, OSError, KeyError, TypeError, OverflowError, ModelDownloadError)


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
            try:
                page = self.app.page().encode("utf-8")
            except Exception:  # noqa: BLE001 - show something instead of a blank tab
                self.log_error("page failed:\n%s", traceback.format_exc())
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "see the console for details")
                return
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
        route = self.path.split("?")[0].strip("/")
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


def make_handler(app: StyleAtlasApp, allowed_hosts: set[str]) -> type[BaseHTTPRequestHandler]:
    attrs = {"app": app, "allowed_hosts": frozenset(allowed_hosts)}
    return type("BoundStyleAtlasHandler", (StyleAtlasHandler,), attrs)


class _Server(ThreadingHTTPServer):
    # The page asks for many thumbnails at once; Windows refuses connections beyond the listen
    # backlog (5 by default) while the server is busy, e.g. making thumbnails right after start.
    request_queue_size = 64
    daemon_threads = True


def bind(app: StyleAtlasApp, port: int = 8770) -> ThreadingHTTPServer:
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
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(
        tr(
            f"style-atlas is running at {url}  (Ctrl+C to stop)",
            f"style-atlas 已開啟：{url}（關掉這個視窗或按 Ctrl+C 結束）",
        ),
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
