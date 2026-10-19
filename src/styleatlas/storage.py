"""Moving the cache (style model, vectors, thumbnails) to a folder the user picks.

Copy first, then switch, then delete the old copies: a failure on the way leaves the cache where
it was. On the same drive the entries are renamed instead (instant). The mover holds the
program's model lock while it works, so no folder is computed into the old place meanwhile."""

from __future__ import annotations

import contextlib
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from styleatlas import cachedir
from styleatlas.cachedir import MODEL_GLOB, STATE_NAMES, cache_dir, state_dir
from styleatlas.lang import tr

SUBFOLDER = "StyleAtlas-cache"  # made inside a picked folder that already holds other things
CHUNK = 8 * 1024 * 1024
ROOM = 200 * 1024 * 1024  # bytes left free on the new drive after the copy
PARTIAL = ".moving"  # suffix of an entry still being copied
PROGRAM_PARTS = ("app", "python", "updates")  # replaced by updates: never a home for the cache

Tick = Callable[[int, int], None]


class MoveError(Exception):
    """Why the cache was not moved (it stays where it was)."""


def entries(folder: Path) -> list[Path]:
    """What moves with the cache: everything in its folder but the state files."""
    try:
        return sorted(p for p in folder.iterdir() if p.name not in STATE_NAMES)
    except OSError:
        return []


def size_of(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        files = path.rglob("*") if path.is_dir() else [path]
        for f in files:
            with contextlib.suppress(OSError):
                total += f.stat().st_size if f.is_file() else 0
    return total


def _key(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))  # a subst drive or junction: the real place


def _same(a: Path, b: Path) -> bool:
    return _key(a) == _key(b)


def _inside(path: Path, folder: Path) -> bool:
    inner, outer = _key(path), _key(folder)
    return inner != outer and inner.startswith(outer.rstrip(os.sep) + os.sep)


def target_for(chosen: Path) -> Path:
    """Where the cache goes for a picked folder: the folder itself when it is empty, already a
    cache, or the default place; else a StyleAtlas-cache folder inside it, so the files of a
    drive's root or a busy folder do not get mixed with the cache's."""
    chosen = Path(chosen).resolve()
    if _same(chosen, state_dir()) or cachedir.holds_cache(chosen):
        return chosen
    try:
        empty = not any(chosen.iterdir())
    except OSError as e:
        raise MoveError(tr(f"cannot read {chosen}: {e}", f"无法读取 {chosen}：{e}")) from e
    return chosen if empty else chosen / SUBFOLDER


def check_target(target: Path, source: Path) -> None:
    if _same(target, source):
        raise MoveError(tr(f"the cache is already in {target}", f"缓存已经在 {target}"))
    if _inside(target, source):
        raise MoveError(
            tr("the new place cannot be inside the cache itself", "新位置不能在缓存文件夹里面")
        )
    program = cachedir.program_dir()
    if program is not None and any(
        _inside(target, program / part) or _same(target, program / part) for part in PROGRAM_PARTS
    ):
        raise MoveError(
            tr(
                "the program's app, python and updates folders are replaced by updates; "
                "pick another folder",
                "程序的 app、python、updates 文件夹会在更新时被替换，请选别的文件夹",
            )
        )


def move(source: Path, target: Path, tick: Tick) -> dict:
    """Move the cache's entries from `source` to `target` and switch to it. Returns what stayed:
    `kept` (names `target` had already: its copy is used) and `leftovers` (old copies that could
    not be deleted, in use)."""
    items = entries(source)
    _check_writable(target)
    kept = [p for p in items if (target / p.name).exists()]
    todo = [p for p in items if p not in kept]
    renamed: list[Path] = []
    copied: list[Path] = []
    try:
        to_copy = todo
        if same_drive(source, target):
            to_copy = []
            for p in todo:
                try:
                    os.replace(p, target / p.name)
                    renamed.append(p)
                except OSError:  # in use: copied instead
                    to_copy.append(p)
        _copy_all(to_copy, target, tick, copied)
        cachedir.set_location(_pointer_for(target))
    except BaseException:
        for p in copied:
            _remove(target / p.name)
        for p in renamed:
            with contextlib.suppress(OSError):
                os.replace(target / p.name, p)
        raise
    leftovers = [str(p) for p in copied if not _remove(p)]
    return {"kept": [p.name for p in kept], "leftovers": leftovers}


def _pointer_for(target: Path) -> Path | None:
    """What cache-location.json should say: nothing for the default folder, unless an older
    version's cache in ~/.cache could still win (cachedir._resolve) -- then the folder itself."""
    if not _same(target, state_dir()):
        return target
    home = cachedir.home_cache()
    if (
        cachedir.program_dir() is not None
        and not _same(home, target)
        and cachedir.holds_cache(home)
    ):
        return target
    return None


def same_drive(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def _check_writable(target: Path) -> None:
    probe = target / f"write-test{PARTIAL}"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise MoveError(tr(f"cannot write to {target}: {e}", f"无法写入 {target}：{e}")) from e


def _copy_all(paths: list[Path], target: Path, tick: Tick, copied: list[Path]) -> None:
    """Copy `paths` into `target` after checking the room, appending each one done to `copied`."""
    total = size_of(paths)
    free = shutil.disk_usage(target).free
    if total and free < total + ROOM:
        raise MoveError(
            tr(
                f"{target.anchor or target} has {free / 1e9:.1f} GB free; the cache needs "
                f"{(total + ROOM) / 1e9:.1f} GB",
                f"{target.anchor or target} 只剩 {free / 1e9:.1f} GB，缓存需要 "
                f"{(total + ROOM) / 1e9:.1f} GB",
            )
        )
    done = [0]

    def step(n: int) -> None:
        done[0] += n
        tick(done[0], total)

    tick(0, total)
    for p in paths:
        _copy(p, target / p.name, step)
        copied.append(p)


def _copy(src: Path, dst: Path, step: Callable[[int], None]) -> None:
    partial = dst.with_name(dst.name + PARTIAL)
    _remove(partial)
    try:
        if src.is_dir():
            for folder, _dirs, files in os.walk(src):
                out = partial / Path(folder).relative_to(src)
                out.mkdir(parents=True, exist_ok=True)
                for name in files:
                    _copy_file(Path(folder) / name, out / name, step)
        else:
            _copy_file(src, partial, step)
        os.replace(partial, dst)
    except BaseException:
        _remove(partial)
        raise


def _copy_file(src: Path, dst: Path, step: Callable[[int], None]) -> None:
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while chunk := fin.read(CHUNK):
            fout.write(chunk)
            step(len(chunk))
    shutil.copystat(src, dst)


def _remove(path: Path) -> bool:
    """Delete a file or folder; False when some of it is still there (in use)."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        with contextlib.suppress(OSError):
            path.unlink()
    return not path.exists()


class Mover:
    """The start page's view of the cache: where it is, how big, and a move in the background."""

    def __init__(self, model_lock: threading.Lock):
        self._model_lock = model_lock  # held while a folder is computed
        self._lock = threading.Lock()
        self._state = {"busy": False, "done": 0, "total": 0, "problem": "", "result": ""}
        self._size: int | None = None
        self._sizing = False

    def state(self) -> dict:
        path = cache_dir()
        with self._lock:
            state, size = dict(self._state), self._size
        if size is None:
            self._measure()
        with contextlib.suppress(OSError):
            state["free"] = shutil.disk_usage(path).free
        return {
            **state,
            "path": str(path),
            "size": size,
            "model": any(path.glob(MODEL_GLOB)),
            "env": bool(os.environ.get(cachedir.CACHE_ENV)),
            "missing": cachedir.problem,
        }

    def _measure(self) -> None:
        with self._lock:
            if self._sizing:
                return
            self._sizing = True

        def run() -> None:
            size = size_of(entries(cache_dir()))
            with self._lock:
                self._size, self._sizing = size, False

        threading.Thread(target=run, name="style-atlas-cache-size", daemon=True).start()

    def start(self, chosen: Path) -> dict:
        """Start moving the cache to `chosen` (see target_for); {"error": ...} when it cannot."""
        if os.environ.get(cachedir.CACHE_ENV):
            return {
                "error": tr(
                    f"the environment variable {cachedir.CACHE_ENV} chooses the cache folder; "
                    "change it there",
                    f"缓存文件夹由环境变量 {cachedir.CACHE_ENV} 指定，请改那里",
                )
            }
        source = cache_dir()
        try:
            target = target_for(chosen)
            check_target(target, source)
        except MoveError as e:
            return {"error": str(e)}
        if not self._model_lock.acquire(blocking=False):
            return {
                "error": tr(
                    "a folder is being computed; move the cache once it is ready",
                    "有文件夹正在计算画风，等它算完再搬",
                )
            }
        with self._lock:
            self._state = {"busy": True, "done": 0, "total": 0, "problem": "", "result": ""}
        threading.Thread(
            target=self._run, args=(source, target), name="style-atlas-move", daemon=True
        ).start()
        return {"ok": True, "target": str(target)}

    def _tick(self, done: int, total: int) -> None:
        with self._lock:
            self._state = {**self._state, "done": done, "total": total}

    def _run(self, source: Path, target: Path) -> None:
        problem, result = "", ""
        try:
            outcome = move(source, target, self._tick)
            result = tr("The cache is moved.", "缓存已经搬好。")  # the line above shows where
            if outcome["kept"]:
                names = ", ".join(outcome["kept"])
                result += tr(
                    f" {target} already had {names}; that copy is used.",
                    f"{target} 原本就有 {names}，用的是那边的。",
                )
            if outcome["leftovers"]:
                left = ", ".join(outcome["leftovers"])
                result += tr(
                    f" Still in use, not deleted: {left}",
                    f"还在使用中、没有删掉：{left}",
                )
        except Exception as e:  # noqa: BLE001 - the page must learn why, whatever it was
            problem = str(e) or type(e).__name__
        finally:
            self._model_lock.release()
        with self._lock:
            self._state = {**self._state, "busy": False, "problem": problem, "result": result}
            self._size = None
