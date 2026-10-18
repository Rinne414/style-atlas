"""The desktop program: Style Atlas in its own window instead of a browser tab.

A start page (open a folder, drop one on the window, or pick one opened before), then that
folder's map, served by the same local server as `serve`. "Open another folder" on the map goes
back to the start page without restarting. The window is Edge WebView2 through pywebview
(`pip install style-atlas[app]`); everything inside it is the web app as it is.

`python -m styleatlas.desktop --shortcut` puts a "Style Atlas" shortcut on the Windows desktop."""

from __future__ import annotations

import argparse
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
from styleatlas.webserver import Preparing, StandIn, bind

RECENT_FILE = "recent_folders.json"
RECENT_MAX = 12
TITLE = "Style Atlas"
ICON = "data/style-atlas.ico"
START_MARK = "/*__START_DATA__*/null"
LOAD_DELAY = 0.15  # seconds between answering a page and leaving it
DARK_TITLE_BAR = 20  # DWMWA_USE_IMMERSIVE_DARK_MODE

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
        "note": "The first time, the style model is downloaded once (about 2.4 GB); after that "
        "only new pictures are computed. Pictures and results stay on this computer.",
    },
    "zh": {
        "lead": "看一個圖片資料夾裡有哪些畫風、找畫風相近的圖、整理 LoRA 訓練資料。",
        "pick": "開啟圖片資料夾…",
        "dropHint": "或把資料夾直接拖進這個視窗",
        "recentTitle": "開過的資料夾",
        "none": "還沒有開過任何資料夾。",
        "gone": "找不到（被移走或刪掉了？）",
        "remove": "從清單移除（資料夾本身不會動）",
        "opening": "正在開啟 {f}…",
        "dropping": "正在讀取拖進來的資料夾…",
        "dropFailed": "這裡拖放沒有成功，請改按「開啟圖片資料夾」。",
        "notReady": "程式還在啟動，請稍等一下再按。",
        "note": "第一次使用會先下載一次畫風模型（約 2.4 GB），之後只會計算新加入的圖。"
        "圖片和結果都只留在這台電腦。",
    },
}


class Cancelled(BaseException):  # noqa: N818 - not an error: another folder was opened meanwhile
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
        raise ValueError(tr("no folder given", "沒有指定資料夾"))
    path = Path(text.strip()).expanduser()
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise ValueError(tr(f"not a folder: {text}", f"不是資料夾：{text}"))
    return path.resolve()


# ---------- one server, one folder at a time ----------


class Desktop:
    """The server behind the window and the folder it shows. Each folder gets a new address
    prefix (webserver.StyleAtlasHandler.token); a folder still being prepared when another is
    opened stops at its next progress line."""

    def __init__(self, serve_args: list[str], port: int, recent: RecentFolders):
        self.serve_args = serve_args
        self.recent = recent
        self.home_page = StartPage(recent)
        self.server = bind(self.home_page, port)
        self.handler = self.server.RequestHandlerClass
        self.handler.token = secrets.token_hex(6)
        self.window: Any = None  # the pywebview window, set by run()
        self.folder: Path | None = None
        self._generation = 0
        self._builder: threading.Thread | None = None
        self._lock = threading.Lock()
        threading.Thread(
            target=self.server.serve_forever, name="style-atlas-http", daemon=True
        ).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/s/{self.handler.token}/"

    def _switch(self, app: object, folder: Path | None = None, work: Callable | None = None) -> str:
        """Show `app` under a new address and return it. `work(generation, previous)` runs in the
        background (a folder's build), handed the build before it to wait for: all in one step,
        so two quick opens cannot both take the same build as the one before."""
        with self._lock:
            self._generation += 1
            self.handler.app = app
            self.handler.token = secrets.token_hex(6)
            self.folder = folder
            if work is not None:
                previous = self._builder
                self._builder = threading.Thread(
                    target=work,
                    args=(self._generation, previous),
                    name="style-atlas-build",
                    daemon=True,
                )
                self._builder.start()
            return self.url

    def show_home(self) -> str:
        return self._switch(self.home_page)

    def open_folder(self, folder: Path) -> str:
        """Start preparing `folder` (in the background) and return the address that shows it."""
        from styleatlas.cli import build_parser, serve_build

        args = build_parser().parse_args(["serve", str(folder), *self.serve_args])
        build, title = serve_build(args)
        preparing = Preparing(title)
        self.recent.remember(folder)
        return self._switch(
            preparing,
            folder,
            lambda generation, previous: self._build(build, preparing, generation, previous),
        )

    def _build(self, build: Callable, preparing: Preparing, generation: int, previous) -> None:
        if previous is not None:
            previous.join()  # one model run at a time: the one before stops at its next line

        def progress(msg: str) -> None:
            if generation != self._generation:
                raise Cancelled
            preparing.progress(msg)

        try:
            app = build(progress)
            if generation != self._generation:
                return
            app.prewarm()
        except Cancelled:
            return
        except BaseException as e:  # noqa: BLE001 - the page must learn why, whatever it was
            if generation == self._generation:  # nobody looks at a page left behind
                preparing.fail(e)
            return
        with self._lock:
            if generation == self._generation:
                self.handler.app = app

    def stop(self) -> None:
        self._generation += 1  # a build still running stops at its next progress line
        self.server.shutdown()
        self.server.server_close()


# ---------- what the pages may ask of the program ----------


class Api:
    """`window.pywebview.api` on the window's pages. Attributes stay private: pywebview hands
    every public attribute to the page."""

    def __init__(self, desktop: Desktop):
        self._desktop = desktop

    def _load(self, url: str) -> None:
        """Go to `url` once this call has answered: leaving the page first leaves pywebview
        nowhere to deliver the answer (an error in the log for every switch)."""
        window = self._desktop.window
        if window is not None:
            threading.Timer(LOAD_DELAY, window.load_url, args=(url,)).start()

    def _open(self, folder: Path) -> None:
        self._load(self._desktop.open_folder(folder))

    def home(self) -> dict:
        self._load(self._desktop.show_home())
        return {"ok": True}

    def open_folder(self, path: str) -> dict:
        try:
            self._open(folder_from(path))
        except ValueError as e:
            return {"error": str(e)}
        return {"ok": True}

    def pick_folder(self) -> dict:
        import webview

        window = self._desktop.window
        start = str(self._desktop.folder or "")
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

        window = self._desktop.window
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
        """A second window for a page of this server (the artist map)."""
        import webview

        base = self._desktop.url  # this folder's pages only (an old address would answer 404)
        if not isinstance(url, str) or not url.startswith(base):
            return {"error": "only pages of this program open in its windows"}
        second = webview.create_window(
            str(title)[:120] or TITLE, url, width=1400, height=900, background_color="#0d0f12"
        )
        if second is not None:  # shown at once during the loop: the event may come before this
            second.events.shown += lambda: _dark_title_bar(second)
            threading.Timer(1.0, _dark_title_bar, args=(second,)).start()
        return {"ok": True}


def _on_loaded(desktop: Desktop, api: Api) -> Callable[[], None]:
    """On every page load: the start page also takes folders dropped on the window."""

    def loaded() -> None:
        window = desktop.window
        if window is None or desktop.handler.app is not desktop.home_page:
            return
        from webview.dom import DOMEventHandler

        def on_drop(event: dict) -> None:
            files = (event.get("dataTransfer") or {}).get("files") or []
            path = next(
                (f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), None
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


def _dark_title_bar(window) -> None:
    """A dark title bar over the dark page (Windows 10 2004+; older ones keep theirs)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        hwnd = int(window.native.Handle.ToInt64())
    except (AttributeError, TypeError):  # not the Windows Forms window
        return
    on = ctypes.c_int(1)
    size = ctypes.sizeof(on)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DARK_TITLE_BAR, ctypes.byref(on), size)


def _tell(message: str) -> None:
    """A message that reaches the user with or without a console (a box on Windows)."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)


def icon_path() -> Path:
    return Path(str(resources.files("styleatlas").joinpath(ICON)))


def run(folder: str | None, serve_args: list[str], port: int) -> int:
    try:
        import webview
    except ImportError:
        _tell(
            tr(
                "The desktop window needs pywebview. Run scripts\\setup.bat again "
                "(or: pip install pywebview).",
                "桌面視窗需要 pywebview。請重新執行 scripts\\setup.bat"
                "（或 pip install pywebview）。",
            )
        )
        return 2
    root = cache_dir()
    _quiet_streams(root / "desktop.log")
    desktop = Desktop(serve_args, port, RecentFolders(root / RECENT_FILE))
    api = Api(desktop)
    first = desktop.open_folder(folder_from(folder)) if folder else desktop.show_home()
    webview.settings["ALLOW_DOWNLOADS"] = True  # saved pictures and recordings go to Downloads
    window = webview.create_window(
        TITLE,
        first,
        js_api=api,
        maximized=True,
        min_size=(900, 600),
        background_color="#0d0f12",
        text_select=True,
    )
    if window is None:  # pywebview gives none only on platforms without windows (Android)
        return 2
    desktop.window = window
    window.events.loaded += _on_loaded(desktop, api)
    window.events.shown += lambda: _dark_title_bar(window)
    webview.start(private_mode=False, storage_path=str(root / "webview"), icon=str(icon_path()))
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
        "folder", nargs="?", help=tr("a folder to open at once", "啟動時直接開啟的資料夾")
    )
    p.add_argument("--device", default="auto", help=tr("auto, cpu or cuda", "auto、cpu 或 cuda"))
    p.add_argument("--port", type=int, default=8770, help=tr("first port to try", "先試的連接埠"))
    p.add_argument(
        "--shortcut",
        action="store_true",
        help=tr("make a desktop shortcut and stop", "在桌面建立捷徑後結束"),
    )
    a = p.parse_args(argv)
    if a.shortcut:
        link = make_shortcut()
        print(tr(f"shortcut made: {link}", f"已建立捷徑：{link}"))
        return 0
    return run(a.folder, ["--time", "name", "--device", a.device], a.port)


if __name__ == "__main__":
    raise SystemExit(main())
