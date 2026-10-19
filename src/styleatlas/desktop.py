"""The desktop program: Style Atlas in its own windows instead of browser tabs.

Each window starts on a start page (open a folder, drop one on the window, or pick one opened
before) and then shows that folder's map, served by the same local server as `serve`. "Start
page" on the map closes the folder and goes back; "New window" opens another window, and so does
starting the program again while it is open (the new start hands over to the open copy and
quits, so the model is loaded once). A folder is open in one window at a time. Closing a window
closes its folder; closing the last one ends the program. The windows are Edge WebView2 through
pywebview (`pip install style-atlas[app]`); everything inside them is the web app as it is.

`python -m styleatlas.desktop --shortcut` puts a "Style Atlas" shortcut on the Windows desktop."""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from styleatlas import __version__
from styleatlas.cachedir import cache_dir
from styleatlas.lang import tr
from styleatlas.webbase import CONTROL_PATH, POST_HEADER, StandIn

RECENT_FILE = "recent_folders.json"
OPEN_FILE = "desktop_open.json"  # how a later start reaches the copy that is open
RECENT_MAX = 12
TITLE = "Style Atlas"
ICON = "data/style-atlas.ico"
START_MARK = "/*__START_DATA__*/null"
LOAD_DELAY = 0.15  # seconds between answering a page and leaving it
DARK_TITLE_BAR = 20  # DWMWA_USE_IMMERSIVE_DARK_MODE
SW_RESTORE = 9
NEW_WIDTH, NEW_HEIGHT = 1400, 900  # a window opened after the first one
HAND_OVER_TIMEOUT = 5  # seconds a later start waits for the open copy's answer

START_TEXTS = {
    "en": {
        "lead": "See which styles an image folder holds, find pictures in a similar style, and "
        "prepare LoRA training sets.",
        "pick": "Open an image folder…",
        "dropHint": "or drop a folder onto this window",
        "recentTitle": "Opened before",
        "none": "No folder opened yet.",
        "gone": "not found (moved or deleted?)",
        "remove": "Remove from the list (the folder stays)",
        "opening": "Opening {f}…",
        "dropping": "Reading the dropped folder…",
        "dropFailed": "The drop did not work here; use Open an image folder instead.",
        "notReady": "Still starting up; try again in a moment.",
        "elsewhere": "{f} is already open in another window, now in front.",
        "note": "The first time, the style model is downloaded once (about 2.4 GB); after that "
        "only new pictures are computed. Pictures and results stay on this computer.",
    },
    "zh": {
        "lead": "看一个图片文件夹里有哪些画风、找画风相近的图、整理 LoRA 训练数据。",
        "pick": "打开图片文件夹…",
        "dropHint": "或把文件夹直接拖进这个窗口",
        "recentTitle": "开过的文件夹",
        "none": "还没有开过任何文件夹。",
        "gone": "找不到（被移走或删掉了？）",
        "remove": "从清单移除（文件夹本身不会动）",
        "opening": "正在打开 {f}…",
        "dropping": "正在读取拖进来的文件夹…",
        "dropFailed": "这里拖放没有成功，请改按“打开图片文件夹”。",
        "notReady": "程序还在启动，请稍等一下再按。",
        "elsewhere": "{f} 已经在另一个窗口打开，已切换到那个窗口。",
        "note": "第一次使用会先下载一次画风模型（约 2.4 GB），之后只会计算新加入的图。"
        "图片和结果都只留在这台电脑。",
    },
}


class Cancelled(BaseException):  # noqa: N818 - not an error: the window moved on meanwhile
    """Raised from the progress callback of a build that is no longer wanted. A BaseException,
    so no `except Exception` on the way swallows it."""


# ---------- the folders opened before ----------


class RecentFolders:
    """The folders opened before, newest first, kept in a small JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [p for p in data if isinstance(p, str) and p][:RECENT_MAX]

    def _save(self, folders: list[str]) -> list[str]:
        folders = folders[:RECENT_MAX]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(folders, ensure_ascii=False, indent=1), "utf-8")
        except OSError:  # a read-only cache: the list lasts this run only
            pass
        return folders

    def remember(self, folder: Path) -> list[str]:
        text = str(folder)
        with self._lock:
            return self._save([text] + [p for p in self.load() if _same(p, text) is False])

    def forget(self, folder: str) -> list[str]:
        with self._lock:
            return self._save([p for p in self.load() if _same(p, folder) is False])

    def rows(self) -> list[dict]:
        """What the start page lists: name, full path, and whether the folder is still there."""
        return [
            {"path": p, "name": Path(p).name or p, "exists": Path(p).is_dir()} for p in self.load()
        ]


def _same(a: str, b: str) -> bool:
    """Two spellings of one folder (Windows paths ignore case)."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class StartPage(StandIn):
    """The page at the server's root while no folder is open."""

    def __init__(self, recent: RecentFolders):
        self.recent = recent

    def page(self) -> str:
        data = {"recent": self.recent.rows(), "version": __version__, "texts": START_TEXTS}
        text = json.dumps(data, ensure_ascii=False)
        # "<", ">" and "&" only occur inside JSON strings; escaped, a folder name stays inert
        text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        page = resources.files("styleatlas").joinpath("templates/start.html").read_text("utf-8")
        return page.replace(START_MARK, text, 1)


def folder_from(text: object) -> Path:
    """The folder a page asked to open: an existing folder, or the folder of a dropped file."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError(tr("no folder given", "没有指定文件夹"))
    path = Path(text.strip()).expanduser()
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise ValueError(tr(f"not a folder: {text}", f"不是文件夹：{text}"))
    return path.resolve()


# ---------- one server, a folder per window ----------


class Pane:
    """One window and what it shows: the start page, a folder being prepared, or a folder's map,
    under an address prefix that is new for each folder."""

    def __init__(self) -> None:
        self.token = ""
        self.app: object = None
        self.folder: Path | None = None
        self.generation = 0
        self.window: Any = None
        self.extras: list[Any] = []  # the artist-map windows opened from it


class Desktop:
    """The server behind the windows. Each window's page lives under its own address prefix
    (webserver.StyleAtlasHandler.sites). One model run at a time for all windows: a folder whose
    window moved on stops at its next progress line, and a folder opened meanwhile waits."""

    def __init__(self, serve_args: list[str], port: int, recent: RecentFolders):
        from styleatlas.webserver import bind

        self.serve_args = serve_args
        self.recent = recent
        self.home_page = StartPage(recent)
        self.server = bind(self.home_page, port)
        self.handler = self.server.RequestHandlerClass
        self.handler.sites = {}
        self.handler.control = self.remote
        self.key = secrets.token_hex(16)  # what a later start shows to be given a window
        self.panes: list[Pane] = []
        self._lock = threading.Lock()
        self._model = threading.Lock()  # held by the folder being prepared
        self._opening = threading.Lock()  # checking and opening a folder are one step (claim)
        threading.Thread(
            target=self.server.serve_forever, name="style-atlas-http", daemon=True
        ).start()

    def url(self, pane: Pane) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/s/{pane.token}/"

    def add_pane(self) -> Pane:
        pane = Pane()
        with self._lock:
            self.panes.append(pane)
        return pane

    def _switch(
        self,
        pane: Pane,
        app: object,
        folder: Path | None = None,
        work: Callable | None = None,
    ) -> str:
        """Show `app` in `pane` under a new address and return it; `work(generation)` runs in
        the background (a folder's build). Nothing happens for a window closed meanwhile ("")."""
        with self._lock:
            if pane not in self.panes:
                return ""
            pane.generation += 1
            self.handler.sites.pop(pane.token, None)
            pane.token = secrets.token_hex(6)
            pane.app, pane.folder = app, folder
            self.handler.sites[pane.token] = app
            generation, url = pane.generation, self.url(pane)
        for extra in list(pane.extras):  # an artist map of the folder left behind
            extra.destroy()
        if work is not None:
            threading.Thread(
                target=work, args=(generation,), name="style-atlas-build", daemon=True
            ).start()
        return url

    def show_home(self, pane: Pane) -> str:
        return self._switch(pane, self.home_page)

    def open_folder(self, pane: Pane, folder: Path) -> str:
        """Start preparing `folder` in `pane` (in the background) and return its address."""
        from styleatlas.cli import build_parser, serve_build
        from styleatlas.webserver import Preparing

        args = build_parser().parse_args(["serve", str(folder), *self.serve_args])
        build, title = serve_build(args)
        preparing = Preparing(title)
        self.recent.remember(folder)
        return self._switch(
            pane,
            preparing,
            folder,
            lambda generation: self._build(pane, build, preparing, generation),
        )

    def _build(self, pane: Pane, build: Callable, preparing, generation: int) -> None:
        def progress(msg: str) -> None:
            if generation != pane.generation:
                raise Cancelled
            preparing.progress(msg)

        if not self._model.acquire(blocking=False):
            preparing.progress(
                tr(
                    "waiting for the folder in another window to be ready",
                    "等另一个窗口的文件夹准备好…",
                )
            )
            self._model.acquire()
        try:
            if generation != pane.generation:
                return
            app = build(progress)
            if generation != pane.generation:
                return
            app.prewarm()
        except Cancelled:
            return
        except BaseException as e:  # noqa: BLE001 - the page must learn why, whatever it was
            if generation == pane.generation:  # nobody looks at a page left behind
                preparing.fail(e)
            return
        finally:
            self._model.release()
        with self._lock:
            if generation == pane.generation:
                pane.app = app
                self.handler.sites[pane.token] = app

    def claim(self, folder: Path, pane: Pane) -> tuple[Pane, str | None]:
        """Open `folder` in `pane` and return it with its address, or return the window that
        already has `folder` open, with None. A folder is open in one window at a time (two
        would each keep their own group edits and save over each other), checked and opened in
        one step so that two quick opens of one folder cannot both win."""
        with self._opening:
            other = self.showing(folder)
            if other is not None and other is not pane:
                return other, None
            return pane, self.open_folder(pane, folder)

    def showing(self, folder: Path) -> Pane | None:
        """The window that has `folder` open."""
        with self._lock:
            return next(
                (
                    p
                    for p in self.panes
                    if p.folder is not None and _same(str(p.folder), str(folder))
                ),
                None,
            )

    def close(self, pane: Pane) -> None:
        """`pane`'s window was closed: its folder stops being prepared and is let go."""
        with self._lock:
            pane.generation += 1
            self.handler.sites.pop(pane.token, None)
            pane.app, pane.folder = None, None
            if pane in self.panes:
                self.panes.remove(pane)
        for extra in list(pane.extras):
            extra.destroy()

    def open_window(self, folder: Path | None = None, *, first: bool = False) -> Pane:
        """A new window on the start page, or on `folder`; the window that already has `folder`
        open is brought forward instead. The first window fills the screen; later ones open
        smaller on top, so it shows that the window before is still there."""
        import webview

        pane = self.add_pane()
        api = Api(self, pane)
        try:
            if folder is None:
                url = self.show_home(pane)
            else:
                other, url = self.claim(folder, pane)
                if url is None:
                    self.close(pane)
                    _to_front(other.window)
                    return other
            window = webview.create_window(
                _title(folder),
                url,
                js_api=api,
                width=NEW_WIDTH,
                height=NEW_HEIGHT,
                maximized=first,
                min_size=(900, 600),
                background_color="#0d0f12",
                text_select=True,
            )
        except BaseException:
            self.close(pane)
            raise
        if window is None:  # pywebview gives none only on platforms without windows (Android)
            self.close(pane)
            return pane
        pane.window = window
        window.events.loaded += _on_loaded(self, pane, api)
        window.events.closed += lambda: self.close(pane)
        done = threading.Event()

        def shown() -> None:
            if done.is_set() or pane not in self.panes:  # once; not after it was closed
                return
            done.set()
            _dark_title_bar(window)
            if not first:  # asked for from another window or another start
                _to_front(window)

        window.events.shown += shown
        if not first:  # shown at once during the loop: the event may come before this
            threading.Timer(1.0, shown).start()
        return pane

    def remote(self, payload: dict) -> bool:
        """A later start of the program asking for a window (webbase.CONTROL_PATH) with the key
        from OPEN_FILE; `folder` opens in it. Answered at once, before the window is made (the
        later start waits only a few seconds). False for a wrong key, and while the last window
        is closing: the later start then opens a copy of its own."""
        key = str(payload.get("key", "")).encode("utf-8", "replace")
        if not secrets.compare_digest(key, self.key.encode("ascii")) or not self.panes:
            return False
        try:
            folder = folder_from(payload["folder"]) if payload.get("folder") else None
        except ValueError:  # gone since it was dropped on the shortcut: the start page instead
            folder = None
        threading.Thread(
            target=self.open_window, args=(folder,), name="style-atlas-window", daemon=True
        ).start()
        return True

    def announce(self, path: Path) -> None:
        """Say in `path` how a later start reaches this copy (_hand_over)."""
        port = self.server.server_address[1]
        info = {"port": port, "pid": os.getpid(), "key": self.key}
        with contextlib.suppress(OSError):  # a read-only cache: later starts open their own copy
            path.write_text(json.dumps(info), "utf-8")

    def retire(self, path: Path) -> None:
        """Take back what `announce` wrote, unless a newer copy has written over it. Whatever
        is left behind only costs a later start one refused request before it opens its own."""
        with contextlib.suppress(OSError, ValueError, AttributeError):
            if json.loads(path.read_text("utf-8")).get("pid") == os.getpid():
                path.unlink()

    def stop(self) -> None:
        with self._lock:
            for pane in self.panes:
                pane.generation += 1  # a build still running stops at its next progress line
        self.server.shutdown()
        self.server.server_close()


# ---------- what the pages may ask of the program ----------


class Api:
    """`window.pywebview.api` on one window's pages. Attributes stay private: pywebview hands
    every public attribute to the page."""

    def __init__(self, desktop: Desktop, pane: Pane):
        self._desktop = desktop
        self._pane = pane

    def _load(self, url: str) -> None:
        """Go to `url` once this call has answered: leaving the page first leaves pywebview
        nowhere to deliver the answer (an error in the log for every switch)."""
        window = self._pane.window
        if window is not None and url:  # none: the window was closed meanwhile
            window.set_title(_title(self._pane.folder))
            threading.Timer(LOAD_DELAY, window.load_url, args=(url,)).start()

    def home(self) -> dict:
        self._load(self._desktop.show_home(self._pane))
        return {"ok": True}

    def new_window(self) -> dict:
        self._desktop.open_window()
        return {"ok": True}

    def open_folder(self, path: str) -> dict:
        try:
            folder = folder_from(path)
        except ValueError as e:
            return {"error": str(e)}
        pane, url = self._desktop.claim(folder, self._pane)
        if url is None:
            _to_front(pane.window)
            return {"elsewhere": str(folder)}
        self._load(url)
        return {"ok": True}

    def pick_folder(self) -> dict:
        import webview

        window = self._pane.window
        start = str(self._pane.folder or "")
        chosen = (
            window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
            if window
            else None
        )
        if not chosen:
            return {"cancelled": True}
        path = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        result = self.open_folder(path)
        return {**result, "path": str(path)}

    def choose_folder(self, start: str = "") -> dict:
        """A folder picked in the system's dialog, only handed back (an export's destination)."""
        import webview

        window = self._pane.window
        begin = start if isinstance(start, str) and start and Path(start).is_dir() else ""
        chosen = (
            window.create_file_dialog(webview.FileDialog.FOLDER, directory=begin)
            if window
            else None
        )
        if not chosen:
            return {"cancelled": True}
        return {"path": str(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)}

    def forget(self, path: str) -> dict:
        if not isinstance(path, str):
            return {"error": "path must be text"}
        self._desktop.recent.forget(path)
        return {"recent": self._desktop.recent.rows()}

    def open_window(self, url: str, title: str = TITLE) -> dict:
        """A second window for a page of this window's folder (the artist map), closed with it."""
        import webview

        base = self._desktop.url(self._pane)  # this folder's pages only (others answer 404)
        if not isinstance(url, str) or not url.startswith(base):
            return {"error": "only pages of this program open in its windows"}
        second = webview.create_window(
            str(title)[:120] or TITLE,
            url,
            width=NEW_WIDTH,
            height=NEW_HEIGHT,
            background_color="#0d0f12",
        )
        if second is not None:  # shown at once during the loop: the event may come before this
            self._pane.extras.append(second)
            second.events.closed += lambda: _drop(self._pane.extras, second)
            second.events.shown += lambda: _dark_title_bar(second)
            threading.Timer(1.0, _dark_title_bar, args=(second,)).start()
        return {"ok": True}


def _drop(items: list, item: object) -> None:
    if item in items:
        items.remove(item)


def _title(folder: Path | None) -> str:
    """A window's title: its folder's name first, to tell the windows apart in the taskbar."""
    return f"{folder.name or folder} - {TITLE}" if folder is not None else TITLE


def _on_loaded(desktop: Desktop, pane: Pane, api: Api) -> Callable[[], None]:
    """On every page load: the start page also takes folders dropped on the window."""

    def loaded() -> None:
        window = pane.window
        if window is None or pane.app is not desktop.home_page:
            return
        from webview.dom import DOMEventHandler

        def on_drop(event: dict) -> None:
            files = (event.get("dataTransfer") or {}).get("files") or []
            path = next(
                (f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")),
                None,
            )
            if not path:
                return
            window.evaluate_js(
                f"window.styleAtlasOpening && window.styleAtlasOpening({json.dumps(path)})"
            )
            result = api.open_folder(path)
            if result.get("error"):
                window.evaluate_js(
                    f"window.styleAtlasSay && window.styleAtlasSay({json.dumps(result['error'])})"
                )
            elif result.get("elsewhere"):
                where = json.dumps(result["elsewhere"])
                window.evaluate_js(
                    f"window.styleAtlasElsewhere && window.styleAtlasElsewhere({where})"
                )

        window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)

    return loaded


# ---------- start-up ----------


def _quiet_streams(log_file: Path) -> None:
    """Without a console (the .exe launcher), Python has no stdout/stderr: progress lines and
    errors go to a log file instead, which also keeps libraries that print from failing."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(log_file, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the program
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def _hwnd(window) -> int | None:
    """The Windows handle of a pywebview window; None for other kinds of window."""
    try:
        return int(window.native.Handle.ToInt64())
    except (AttributeError, TypeError):  # not the Windows Forms window
        return None


def _dark_title_bar(window) -> None:
    """A dark title bar over the dark page (Windows 10 2004+; older ones keep theirs)."""
    hwnd = _hwnd(window) if sys.platform == "win32" else None
    if hwnd is None:
        return
    import ctypes

    on = ctypes.c_int(1)
    size = ctypes.sizeof(on)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DARK_TITLE_BAR, ctypes.byref(on), size)


def _to_front(window) -> None:
    """Bring a window forward, restored if it was minimised."""
    if window is None:  # not made yet: it comes up in front by itself (open_window)
        return
    hwnd = _hwnd(window) if sys.platform == "win32" else None
    if hwnd is None:
        window.restore()
        return
    import ctypes

    user = ctypes.windll.user32
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd, SW_RESTORE)
    user.SetForegroundWindow(hwnd)


def _tell(message: str) -> None:
    """A message that reaches the user with or without a console (a box on Windows)."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)


def icon_path() -> Path:
    return Path(str(resources.files("styleatlas").joinpath(ICON)))


def _hand_over(folder: str | None) -> bool:
    """Ask a copy of the program that is already open for a new window (on `folder`, if given)
    instead of starting a second copy, which would load the model a second time. False when no
    copy answers: none is open, or one ended without tidying up."""
    try:
        info = json.loads((cache_dir() / OPEN_FILE).read_text("utf-8"))
        port, pid, key = int(info["port"]), int(info["pid"]), str(info["key"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not 0 < port < 65536:
        return False
    if sys.platform == "win32":  # started by a click: the open copy may bring its window forward
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(pid)
    target = str(Path(folder).expanduser().resolve()) if folder else None
    body = json.dumps({"key": key, "folder": target})  # ASCII: http.client sends it as Latin-1
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=HAND_OVER_TIMEOUT)
    try:
        conn.request("POST", CONTROL_PATH, body, {POST_HEADER: "1"})
        return conn.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def run(folder: str | None, serve_args: list[str], port: int) -> int:
    try:
        import webview
    except ImportError:
        _tell(
            tr(
                "The desktop window needs pywebview. Run scripts\\setup.bat again "
                "(or: pip install pywebview).",
                "桌面窗口需要 pywebview。请重新运行 scripts\\setup.bat"
                "（或 pip install pywebview）。",
            )
        )
        return 2
    root = cache_dir()
    _quiet_streams(root / "desktop.log")
    desktop = Desktop(serve_args, port, RecentFolders(root / RECENT_FILE))
    try:
        start = folder_from(folder) if folder else None
    except ValueError:  # not a folder (any more): the start page instead
        start = None
    webview.settings["ALLOW_DOWNLOADS"] = True  # saved pictures and recordings go to Downloads
    desktop.open_window(start, first=True)
    desktop.announce(root / OPEN_FILE)
    webview.start(private_mode=False, storage_path=str(root / "webview"), icon=str(icon_path()))
    desktop.retire(root / OPEN_FILE)
    desktop.stop()
    sys.stdout.flush()
    os._exit(0)  # a daemon thread inside torch can hang the normal interpreter exit


# ---------- the desktop shortcut ----------


def make_shortcut(desktop_dir: Path | None = None) -> Path:
    """A "Style Atlas" shortcut on the desktop that starts this program without a console.
    The paths reach PowerShell through the environment, never through the command text."""
    if sys.platform != "win32":
        raise OSError("shortcuts are made on Windows only")
    scripts = Path(sys.executable).parent
    target = scripts / "pythonw.exe"
    if not target.exists():
        target = Path(sys.executable)
    folder = desktop_dir or _desktop_folder()
    link = folder / f"{TITLE}.lnk"
    env = {
        **os.environ,
        "SA_LINK": str(link),
        "SA_TARGET": str(target),
        "SA_ARGS": "-m styleatlas.desktop",
        "SA_ICON": str(icon_path()),
        "SA_DIR": str(Path.home()),
    }
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SA_LINK); "
        "$s.TargetPath = $env:SA_TARGET; $s.Arguments = $env:SA_ARGS; "
        "$s.IconLocation = $env:SA_ICON; $s.WorkingDirectory = $env:SA_DIR; "
        "$s.Description = 'Style Atlas'; $s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        check=True,
        capture_output=True,
    )
    return link


def _desktop_folder() -> Path:
    """The user's desktop folder (it may have been moved, e.g. into OneDrive)."""
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Environment]::GetFolderPath('Desktop')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = out.stdout.strip()
    return Path(text) if text and Path(text).is_dir() else Path.home() / "Desktop"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="style-atlas-app", description="Style Atlas in a window")
    p.add_argument(
        "folder", nargs="?", help=tr("a folder to open at once", "启动时直接打开的文件夹")
    )
    p.add_argument("--device", default="auto", help=tr("auto, cpu or cuda", "auto、cpu 或 cuda"))
    p.add_argument("--port", type=int, default=8770, help=tr("first port to try", "先试的连接端口"))
    p.add_argument(
        "--shortcut",
        action="store_true",
        help=tr("make a desktop shortcut and stop", "在桌面创建快捷方式后结束"),
    )
    a = p.parse_args(argv)
    if a.shortcut:
        link = make_shortcut()
        print(tr(f"shortcut made: {link}", f"已创建快捷方式：{link}"))
        return 0
    if _hand_over(a.folder):
        return 0
    return run(a.folder, ["--time", "name", "--device", a.device], a.port)


if __name__ == "__main__":
    raise SystemExit(main())
