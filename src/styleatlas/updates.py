"""A newer version: finding it and fetching it, for the packaged program (packaging/launch.py).

Nothing changes until the user presses the update button. `latest()` only reads the newest
release's version and notes from GitHub. `fetch()` downloads that release's code-only package,
checks it against the release's SHA256SUMS.txt (a mismatch is refused and nothing is kept) and
unpacks it into <package>/updates/ready, which launch.py swaps in at the next start. The bundled
Python and the installed packages stay; a release that needs another Python says so, and then
only the full package will do. Pictures, results next to them and the cache are never touched."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from styleatlas import __version__
from styleatlas.lang import tr

RELEASES_URL = "https://api.github.com/repos/Rinne414/style-atlas/releases/latest"
URL_ENV = "STYLE_ATLAS_UPDATE_URL"  # another address for the release information (test or mirror)
PACKAGE_ENV = "STYLE_ATLAS_PACKAGE"  # set by launch.py: the packaged program's folder
APP_ASSET = "style-atlas-app-{v}.zip"
SUMS_ASSET = "SHA256SUMS.txt"
INFO_ASSET = "update.json"  # {"version": ..., "python": "3.13"}
TIMEOUT = 15  # seconds per request
CHUNK = 1 << 20
MAX_APP_BYTES = 200 * 1024 * 1024  # a code-only package is a few MB


class UpdateError(Exception):
    """Why an update could not be fetched; nothing was changed."""


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    page: str
    assets: dict[str, str] = field(default_factory=dict)  # file name -> download address
    python: str = ""  # the Python version the release runs on ("" = not stated)

    def as_dict(self) -> dict:
        return {"version": self.version, "notes": self.notes, "page": self.page}


def version_key(text: str) -> tuple[int, ...]:
    """'v0.44.1' -> (0, 44, 1); parts that are not numbers count as 0."""
    parts = text.strip().lstrip("vV").split("+")[0].split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_key(candidate) > version_key(current)


def package_root() -> Path | None:
    """The packaged program's folder, or None when running from a source checkout."""
    root = os.environ.get(PACKAGE_ENV)
    return Path(root) if root and (Path(root) / "launch.py").is_file() else None


def runtime() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _get(url: str, limit: int = 4 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"style-atlas/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            data = answer.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(tr(f"could not reach {url}: {e}", f"连不上 {url}：{e}")) from e
    if len(data) > limit:
        raise UpdateError(tr(f"{url} answered with too much data", f"{url} 返回的数据过大"))
    return data


def latest() -> Release:
    """The newest release (version, notes, files). Raises UpdateError when GitHub (or the
    address in STYLE_ATLAS_UPDATE_URL) cannot be read."""
    try:
        info = json.loads(_get(os.environ.get(URL_ENV) or RELEASES_URL))
        assets = {a["name"]: a["browser_download_url"] for a in info.get("assets") or []}
        release = Release(
            version=str(info["tag_name"]).lstrip("vV"),
            notes=str(info.get("body") or ""),
            page=str(info.get("html_url") or ""),
            assets=assets,
        )
    except (ValueError, KeyError, TypeError) as e:
        raise UpdateError(tr("the release information is not readable", "发布信息读不懂")) from e
    if INFO_ASSET in assets:
        with contextlib.suppress(UpdateError, ValueError, AttributeError):
            needs = json.loads(_get(assets[INFO_ASSET])).get("python", "")
            release = Release(**{**release.__dict__, "python": str(needs)})
    return release


def needs_full_package(release: Release) -> bool:
    """True when the release runs on another Python than this package has."""
    return bool(release.python) and release.python != runtime()


def _sums(release: Release) -> dict[str, str]:
    if SUMS_ASSET not in release.assets:
        raise UpdateError(tr("the release has no SHA256SUMS.txt", "这个版本没有 SHA256SUMS.txt"))
    sums = {}
    for line in _get(release.assets[SUMS_ASSET]).decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def _download(url: str, target: Path, progress: Callable[[int, int], None]) -> str:
    """Save `url` to `target` and return its SHA256."""
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": f"style-atlas/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer, target.open("wb") as out:
            total = int(answer.headers.get("Content-Length") or 0)
            done = 0
            while chunk := answer.read(CHUNK):
                done += len(chunk)
                if done > MAX_APP_BYTES:
                    raise UpdateError(tr("the update is far too large", "更新文件大得不正常"))
                digest.update(chunk)
                out.write(chunk)
                progress(done, total)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(tr(f"the download failed: {e}", f"下载失败：{e}")) from e
    return digest.hexdigest()


def _unpack(archive: Path, target: Path) -> None:
    """Unpack the code-only package; it must hold launch.py and app/styleatlas, nothing outside."""
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        for name in names:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or ":" in name:
                raise UpdateError(
                    tr(f"unsafe path in the update: {name}", f"更新里有不安全的路径：{name}")
                )
        if "launch.py" not in names or "app/styleatlas/__init__.py" not in names:
            raise UpdateError(tr("the update is incomplete", "更新文件不完整"))
        z.extractall(target)


def fetch(release: Release, root: Path, progress: Callable[[int, int], None]) -> Path:
    """Download the release's code-only package into <root>/updates and make it ready for the
    next start; returns the ready folder. Raises UpdateError (nothing kept) on any problem."""
    if needs_full_package(release):
        raise UpdateError(
            tr(
                f"version {release.version} needs Python {release.python}: download the full "
                "package from the release page",
                f"{release.version} 版需要 Python {release.python}：请到发布页面下载完整安装包",
            )
        )
    name = APP_ASSET.format(v=release.version)
    if name not in release.assets:
        raise UpdateError(tr(f"the release has no {name}", f"这个版本没有 {name}"))
    expected = _sums(release).get(name)
    if not expected:
        raise UpdateError(
            tr(f"SHA256SUMS.txt does not list {name}", f"SHA256SUMS.txt 里没有 {name}")
        )
    updates = root / "updates"
    updates.mkdir(exist_ok=True)
    archive = updates / f"{name}.part"
    unpacked = updates / "ready.tmp"
    ready = updates / "ready"
    try:
        actual = _download(release.assets[name], archive, progress)
        if actual != expected:
            raise UpdateError(
                tr(
                    "the downloaded file does not match its SHA256: it was thrown away",
                    "下载的文件和 SHA256 校验值不符，已丢弃",
                )
            )
        shutil.rmtree(unpacked, ignore_errors=True)
        _unpack(archive, unpacked)
        shutil.rmtree(ready, ignore_errors=True)
        unpacked.rename(ready)
    except (OSError, zipfile.BadZipFile) as e:
        raise UpdateError(tr(f"the update could not be unpacked: {e}", f"更新解压失败：{e}")) from e
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(unpacked, ignore_errors=True)
    return ready


# ---------- what the pages show ----------

SETTINGS_FILE = "settings.json"


def _settings_path() -> Path:
    from styleatlas.cachedir import state_dir

    return state_dir() / SETTINGS_FILE


def check_enabled() -> bool:
    """Whether to look for a newer version at start (a user setting; on unless turned off)."""
    try:
        return bool(json.loads(_settings_path().read_text("utf-8")).get("check_updates", True))
    except (OSError, ValueError, AttributeError):
        return True


def set_check_enabled(on: bool) -> None:
    path = _settings_path()
    try:
        settings = json.loads(path.read_text("utf-8"))
        settings = settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        settings = {}
    path.write_text(json.dumps({**settings, "check_updates": bool(on)}), "utf-8")


class Updater:
    """The update state the pages show. Checked once per start when allowed; fetched only when
    the user presses Update; the program never restarts by itself."""

    def __init__(self) -> None:
        root = package_root()
        self._lock = threading.Lock()
        self._release: Release | None = None
        self._state = {
            "current": __version__,
            "packaged": root is not None,
            "check": check_enabled(),
            "checking": False,
            "latest": None,
            "newer": False,
            "full": False,
            "problem": "",  # why the last check or download failed
            "busy": False,
            "done": 0,
            "total": 0,
            "ready": root is not None and (root / "updates" / "ready" / "launch.py").is_file(),
        }

    def _set(self, **changes) -> None:
        with self._lock:
            self._state = {**self._state, **changes}

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start_check(self) -> None:
        if self.state()["check"]:
            threading.Thread(target=self._check, name="style-atlas-update", daemon=True).start()

    def _check(self) -> None:
        self._set(checking=True, problem="")
        try:
            release = latest()
        except UpdateError as e:
            self._set(checking=False, problem=str(e))
            return
        self._release = release
        self._set(
            checking=False,
            latest=release.as_dict(),
            newer=is_newer(release.version),
            full=needs_full_package(release),
        )

    def set_check(self, on: bool) -> None:
        set_check_enabled(on)
        self._set(check=bool(on))
        if on and self._release is None and not self.state()["checking"]:
            self.start_check()

    def fetch(self) -> None:
        """Start downloading the newer version (in the background)."""
        state, root, release = self.state(), package_root(), self._release
        if root is None or release is None or not state["newer"] or state["busy"]:
            return
        self._set(busy=True, problem="", done=0, total=0)

        def work() -> None:
            try:
                fetch(release, root, lambda done, total: self._set(done=done, total=total))
            except UpdateError as e:
                self._set(busy=False, problem=str(e))
                return
            self._set(busy=False, ready=True)

        threading.Thread(target=work, name="style-atlas-update-fetch", daemon=True).start()
