"""Where style-atlas keeps its files: two folders, the same one until the user moves the cache.

- state_dir(): small files that stay put (settings, recent folders, the windows' storage, and
  cache-location.json, which says where the cache went). The packaged program keeps them in its
  own folder (data/), so they land on the drive it was unpacked to; a source install uses
  ~/.cache/style-atlas.
- cache_dir(): the big part (the style model, vectors, thumbnails). It starts in state_dir() and
  the start page can move it (storage.Mover). A packaged program that finds the model or vectors
  of an older version in ~/.cache/style-atlas keeps using them there instead of downloading again.

STYLE_ATLAS_CACHE puts both in that one folder and wins over everything else.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from functools import lru_cache
from pathlib import Path

CACHE_ENV = "STYLE_ATLAS_CACHE"
LOCATION_FILE = "cache-location.json"
MODEL_GLOB = "csd_vit_l_*.safetensors"  # encoder.slim_path()
VECTORS = "vectors.sqlite"
# state_dir() files, never moved with the cache
STATE_NAMES = frozenset(
    {
        LOCATION_FILE,
        "settings.json",
        "recent_folders.json",
        "desktop_open.json",
        "desktop.log",
        "webview",
    }
)
CARRIED_STATE = ("settings.json", "recent_folders.json")  # taken over from an older version

_resolved: dict[tuple, Path] = {}  # (state folder, location file stamp) -> cache folder
problem = ""  # why the chosen cache folder is not used this time ("" when it is)


def home_cache() -> Path:
    return Path.home() / ".cache" / "style-atlas"


@lru_cache(maxsize=1)
def program_dir() -> Path | None:
    """The unpacked program's folder (launch.py next to app/, which holds this package), or None
    for a source or pip install. Found by the layout, so the console .bat agrees with the app."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "launch.py").is_file() and (root / "app").is_dir() else None


def holds_cache(folder: Path) -> bool:
    """Whether `folder` has something costly to make again: the style model or vectors."""
    return (folder / VECTORS).is_file() or any(folder.glob(MODEL_GLOB))


def state_dir() -> Path:
    env = os.environ.get(CACHE_ENV)
    if env:
        return _made(Path(env))
    program = program_dir()
    if program is None:
        return _made(home_cache())
    root = program / "data"
    if not root.exists():
        _made(root)
        _carry_state(home_cache(), root)
    return root


def _carry_state(old: Path, new: Path) -> None:
    """Settings and recent folders of an older version (it kept them in ~/.cache/style-atlas)."""
    for name in CARRIED_STATE:
        if (old / name).is_file():
            with contextlib.suppress(OSError):  # a fresh list then; nothing the program needs
                shutil.copy2(old / name, new / name)


def cache_dir() -> Path:
    global problem
    env = os.environ.get(CACHE_ENV)
    if env:
        problem = ""
        return _made(Path(env))
    state = state_dir()
    location = state / LOCATION_FILE
    try:
        st = location.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    key = (str(state), stamp)
    if key not in _resolved:
        _resolved[key] = _resolve(state, location)
    return _made(_resolved[key])


def _resolve(state: Path, location: Path) -> Path:
    global problem
    problem = ""
    chosen = chosen_location(location)
    if chosen is not None:
        try:
            return _made(chosen)
        except OSError:  # an unplugged drive: work in the default folder meanwhile, and say so
            problem = str(chosen)
    if program_dir() is not None and holds_cache(home_cache()):
        return home_cache()
    return state


def chosen_location(location: Path | None = None) -> Path | None:
    """The folder the user moved the cache to, or None."""
    location = location or state_dir() / LOCATION_FILE
    try:
        path = json.loads(location.read_text("utf-8")).get("path")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(path) if isinstance(path, str) and Path(path).is_absolute() else None


def set_location(folder: Path | None) -> None:
    """Use `folder` for the cache from now on (None: the default again)."""
    location = state_dir() / LOCATION_FILE
    if folder is None:
        location.unlink(missing_ok=True)
    else:
        tmp = location.with_suffix(".tmp")
        tmp.write_text(json.dumps({"path": str(folder)}, ensure_ascii=False), "utf-8")
        os.replace(tmp, location)
    _resolved.clear()


def _made(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
