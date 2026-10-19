"""Embed a folder (or file list) with caching: the input every command starts from."""

from __future__ import annotations

import contextlib
import os
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import (
    BrokenExecutor,
    Executor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
)
from contextlib import closing
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path

import numpy as np

from styleatlas.encoder import CSDEncoder, cache_dir, encoder_signature
from styleatlas.images import find_images, labels_from_folders, load_rgb
from styleatlas.lang import tr
from styleatlas.look import LOOK_NAMES, LOOK_VERSION, measure
from styleatlas.metrics import StyleSpace, centroid
from styleatlas.prepare import LOAD_ERRORS, prepare_file, worker_start
from styleatlas.store import VectorStore

Progress = Callable[[str], None]
LOOK_CHUNK = 500  # images measured between cache saves
LOADERS = 4  # threads that open and prepare the next images while the CPU runs the model
PROCESS_LOADERS = 8  # at most this many worker processes do it for a GPU (prepare.py)
PROCESS_MIN = 48  # fewer images than this are not worth starting worker processes for


@dataclass
class EncodeOptions:
    device: str = "auto"
    crop: str = "center"
    batch_size: int | None = None  # None: encoder.GPU_BATCH or CPU_BATCH
    resolution: int = 224
    save_every: int = 64
    db_path: Path | None = None


@dataclass
class Atlas:
    root: Path
    paths: list[Path]
    style: np.ndarray
    content: np.ndarray
    signature: str
    failed: list[tuple[Path, str]] = field(default_factory=list)
    looks: np.ndarray | None = field(default=None, repr=False, compare=False)  # see look.py
    _rels: list[str] | None = field(default=None, init=False, repr=False, compare=False)

    def __len__(self) -> int:
        return len(self.paths)

    def rel(self, i: int) -> str:
        """Path of image i relative to the root, as text (worked out once: the web page asks for
        every image's on each load)."""
        if self._rels is None:
            self._rels = [_relative(p, self.root) for p in self.paths]
        return self._rels[i]

    def in_space(self, name: str) -> tuple[Atlas, StyleSpace]:
        """A copy whose style vectors are in the named space (see metrics.StyleSpace)."""
        space = StyleSpace.fit(name, self.style, self.content)
        return replace(self, style=space.apply(self.style, self.content)), space

    def subset(self, idx: np.ndarray | list[int]) -> Atlas:
        idx = list(idx)
        return Atlas(
            self.root,
            [self.paths[i] for i in idx],
            self.style[idx],
            self.content[idx],
            self.signature,
            looks=None if self.looks is None else self.looks[idx],
        )

    def with_looks(self, opts: EncodeOptions, progress: Progress = lambda _: None) -> Atlas:
        """This atlas with its look measures (cached ones reused, the rest measured once)."""
        if self.looks is not None:
            return self
        return replace(self, looks=measure_looks(self.paths, opts, progress))


MIN_FOLDERS = 3  # sub-folders an artist map needs


def folder_atlas(atlas: Atlas) -> Atlas:
    """One point per first-level sub-folder (an artist, a style): the folder's mean style,
    shown by its most typical image (the one closest to that mean). Loose images at the top
    level are left out. Grouping these points finds families of similar folders."""
    folders = labels_from_folders(atlas.paths, atlas.root)
    names = sorted(set(folders) - {""})
    rows: dict[str, list[int]] = {name: [] for name in names}
    for i, folder in enumerate(folders):  # one pass, not one comparison of all per folder
        if folder:
            rows[folder].append(i)
    paths, style, content, looks = [], [], [], []
    for name in names:
        members = np.asarray(rows[name])
        mean = centroid(atlas.style[members])
        paths.append(atlas.paths[int(members[np.argmax(atlas.style[members] @ mean)])])
        style.append(mean)
        content.append(centroid(atlas.content[members]))
        if atlas.looks is not None:
            looks.append(atlas.looks[members].mean(axis=0))
    empty = np.zeros((0, atlas.style.shape[1]), np.float32)
    return Atlas(
        atlas.root,
        paths,
        np.stack(style).astype(np.float32) if style else empty,
        np.stack(content).astype(np.float32) if content else empty,
        atlas.signature,
        looks=np.stack(looks).astype(np.float32) if looks else None,
    )


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _silent(_: str) -> None:
    return None


_ENCODERS: dict[tuple[str, str, int, int], CSDEncoder] = {}


def get_encoder(opts: EncodeOptions, progress: Progress | None = None) -> CSDEncoder:
    """One loaded model per (device, crop, batch) for the life of the process. `progress` gets
    the first run's download lines."""
    key = (opts.device, opts.crop, opts.batch_size, opts.resolution)
    if key not in _ENCODERS:
        _ENCODERS[key] = CSDEncoder(
            opts.device, opts.crop, opts.batch_size, opts.resolution, progress=progress
        )
    return _ENCODERS[key]


def embed_paths(
    paths: list[Path], opts: EncodeOptions, progress: Progress = _silent
) -> tuple[list[Path], np.ndarray, np.ndarray, list[tuple[Path, str]]]:
    """Vectors for `paths` (cached ones reused). Returns kept paths, style, content, failures."""
    signature = encoder_signature(opts.crop, opts.resolution)
    db = opts.db_path or cache_dir() / "vectors.sqlite"
    failed: list[tuple[Path, str]] = []
    with VectorStore(db) as store:
        keys: dict[Path, str] = {}
        for p in paths:
            try:
                keys[p] = store.key(p)
            except (OSError, ValueError) as e:  # ValueError: undecodable path name
                failed.append((p, f"unreadable: {e}"))
        store.commit()
        have = store.get(keys.values(), signature)
        first_by_key = {k: p for p, k in reversed(keys.items())}  # identical files: embed once
        todo = [p for k, p in first_by_key.items() if k not in have]
        if todo:
            cached = len(first_by_key) - len(todo)
            progress(
                tr(
                    f"{cached} already computed (read from the cache), {len(todo)} to compute "
                    f"({signature})",
                    f"{cached} 张已经算过（从缓存读取），{len(todo)} 张要计算（{signature}）",
                )
            )
            failed += _embed_missing(todo, keys, have, store, opts, progress)
        else:
            progress(
                tr(
                    f"all {len(keys)} images already computed, read from the cache ({signature})",
                    f"{len(keys)} 张都已经算过，直接从缓存读取（{signature}）",
                )
            )
    kept = [p for p in paths if p in keys and keys[p] in have]
    style = np.stack([have[keys[p]][0] for p in kept]) if kept else np.zeros((0, 768), np.float32)
    content = np.stack([have[keys[p]][1] for p in kept]) if kept else np.zeros((0, 768), np.float32)
    return kept, style, content, failed


def _embed_missing(
    todo: list[Path],
    keys: dict[Path, str],
    have: dict[str, tuple[np.ndarray, np.ndarray]],
    store: VectorStore,
    opts: EncodeOptions,
    progress: Progress,
) -> list[tuple[Path, str]]:
    encoder = get_encoder(opts, progress)
    progress(tr(f"model ready on {encoder.device}", f"模型已加载（{encoder.device}）"))
    failed: list[tuple[Path, str]] = []
    pending: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    looks: dict[str, np.ndarray] = {}  # measured while each image is open anyway
    done = seen = 0
    load = partial(prepare_file, crop=encoder.crop, px=encoder.px)
    pool, depth = _loaders(encoder.device, len(todo))
    with closing(_ahead(todo, encoder.batch_size, load, pool, depth)) as batches:  # Ctrl+C stops
        for batch, loaded in batches:
            ok = [(p, r) for p, r in zip(batch, loaded, strict=True) if not isinstance(r, str)]
            failed += [(p, r) for p, r in zip(batch, loaded, strict=True) if isinstance(r, str)]
            if ok:
                emb = encoder.encode_prepared([encoder.tensors(sq) for _, (sq, _) in ok])
                for i, (p, (_, look)) in enumerate(ok):
                    pending[keys[p]] = (emb.style[i], emb.content[i])
                    looks[keys[p]] = look
            done += len(ok)
            seen += len(batch)
            if len(pending) >= opts.save_every or seen == len(todo):
                store.put(pending, encoder.signature)
                store.put_looks(looks, LOOK_VERSION)
                looks = {}
                have.update(pending)
                pending = {}
                progress(tr(f"embedded {done}/{len(todo)}", f"已计算 {done}/{len(todo)}"))
    return failed


def _allowed_cpus() -> list[int]:
    import psutil

    try:
        return psutil.Process().cpu_affinity()
    except (AttributeError, psutil.Error, OSError):  # no affinity on macOS
        return list(range(os.cpu_count() or 1))


def _loaders(device: str, count: int) -> tuple[Executor, int]:
    """Where the next images are opened, and how many batches ahead: worker processes when a GPU
    runs the model (prepare.py says why), threads when the CPU does (it is busy with the model
    then) or for a few images (not worth starting processes). The workers keep to the CPUs this
    process may use, leaving one for it, at its lower priority."""
    if device != "cpu" and count >= PROCESS_MIN:
        cpus = _allowed_cpus()
        workers = max(2, min(PROCESS_LOADERS, len(cpus) - 1))
        with contextlib.suppress(OSError, ValueError):
            return ProcessPoolExecutor(workers, initializer=worker_start, initargs=(cpus,)), 2
    return ThreadPoolExecutor(LOADERS), 1


def _ahead(
    items: list, size: int, load: Callable, pool: Executor, depth: int = 1
) -> Iterator[tuple[list, list]]:
    """(batch, load(x) for x in batch) in order, in batches of `size`. The next `depth` batches
    are loaded in `pool` while the caller works on this one; should the pool break (a worker
    process died), the rest is loaded in threads. Shuts the pool down at the end."""
    pools = [pool]
    chunks = [items[s : s + size] for s in range(0, len(items), size)]

    def submit(chunk: list) -> list:
        try:
            return [pools[-1].submit(load, x) for x in chunk]
        except BrokenExecutor:
            pools.append(ThreadPoolExecutor(LOADERS))
            return [pools[-1].submit(load, x) for x in chunk]

    def collect(futures: list, chunk: list) -> list:
        try:
            return [f.result() for f in futures]
        except BrokenExecutor:
            return [load(x) for x in chunk]

    try:
        queue = deque([submit(chunk) for chunk in chunks[:depth]])
        for n, chunk in enumerate(chunks):
            if n + depth < len(chunks):
                queue.append(submit(chunks[n + depth]))
            yield chunk, collect(queue.popleft(), chunk)
    finally:
        for each in pools:
            each.shutdown(cancel_futures=True)


def _measure_file(path: Path) -> np.ndarray:
    try:
        return measure(load_rgb(path))
    except LOAD_ERRORS:
        return np.full(len(LOOK_NAMES), np.nan, np.float32)


def measure_looks(
    paths: list[Path], opts: EncodeOptions, progress: Progress = _silent
) -> np.ndarray:
    """(n, 6) look measures for `paths`, in LOOK_NAMES order. Images embedded by this version
    were measured then; older ones are opened once more here, in parallel, and cached. An image
    that cannot be opened gets NaN."""
    db = opts.db_path or cache_dir() / "vectors.sqlite"
    nan = np.full(len(LOOK_NAMES), np.nan, np.float32)
    with VectorStore(db) as store:
        keys: dict[Path, str] = {}
        for p in paths:
            try:
                keys[p] = store.key(p)
            except (OSError, ValueError):  # gone or renamed since it was embedded
                continue
        store.commit()
        have = store.get_looks(keys.values(), LOOK_VERSION)
        todo = list({k: p for p, k in keys.items() if k not in have}.items())
        if todo:
            progress(
                tr(
                    f"measuring the look of {len(todo)} images (once)",
                    f"计算 {len(todo)} 张图的外观（只算一次）",
                )
            )
            workers = max(1, min(8, os.cpu_count() or 1))
            with ThreadPoolExecutor(workers) as pool:
                for start in range(0, len(todo), LOOK_CHUNK):  # saved as it goes: Ctrl+C keeps it
                    part = todo[start : start + LOOK_CHUNK]
                    measured = pool.map(_measure_file, [p for _, p in part])
                    found = {k: v for (k, _), v in zip(part, measured, strict=True)}
                    good = {k: v for k, v in found.items() if not np.isnan(v).any()}
                    store.put_looks(good, LOOK_VERSION)
                    have.update(found)
                    if len(todo) > LOOK_CHUNK:
                        done_looks = f"{start + len(part)}/{len(todo)}"
                        progress(tr(f"measured {done_looks}", f"外观 {done_looks}"))
    if not paths:
        return np.zeros((0, len(LOOK_NAMES)), np.float32)
    x = np.stack([have[keys[p]] if p in keys else nan for p in paths]).astype(np.float32)
    bad = np.isnan(x).any(axis=1)
    if bad.any():  # opened for embedding, gone since: show it as an average image
        x[bad] = x[~bad].mean(axis=0) if (~bad).any() else 0.0
    return x


def build_atlas(
    root: Path,
    opts: EncodeOptions,
    progress: Progress = _silent,
    recursive: bool = True,
    exclude: list[Path] | None = None,
) -> Atlas:
    root = Path(root)
    paths = find_images(root, recursive=recursive, exclude=exclude)
    if not paths:
        raise FileNotFoundError(
            tr(
                f"no images found under {root}",
                f"{root} 里找不到图片（png、jpg、jfif、webp、bmp、gif、avif）",
            )
        )
    kept, style, content, failed = embed_paths(paths, opts, progress)
    base = root if root.is_dir() else root.parent
    return Atlas(base, kept, style, content, encoder_signature(opts.crop, opts.resolution), failed)
