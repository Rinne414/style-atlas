"""Embed a folder (or file list) with caching: the input every command starts from."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.encoder import CSDEncoder, cache_dir, encoder_signature
from styleatlas.images import find_images, labels_from_folders, load_rgb
from styleatlas.lang import tr
from styleatlas.look import LOOK_NAMES, LOOK_VERSION, measure
from styleatlas.metrics import StyleSpace, centroid
from styleatlas.store import VectorStore

Progress = Callable[[str], None]
LOAD_ERRORS = (OSError, ValueError, Image.DecompressionBombError, SyntaxError)
LOOK_CHUNK = 500  # images measured between cache saves
LOADERS = 4  # threads that open and prepare the next images while the model runs


@dataclass
class EncodeOptions:
    device: str = "auto"
    crop: str = "center"
    batch_size: int = 8
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


FAMILY_CUT = 0.35  # folder means: about 11 families of 269 artists, loose (BENCHMARKS.md)
MIN_FOLDERS = 3  # sub-folders an artist map needs


def folder_atlas(atlas: Atlas) -> Atlas:
    """One point per first-level sub-folder (an artist, a style): the folder's mean style,
    shown by its most typical image (the one closest to that mean). Loose images at the top
    level are left out. Grouping these points finds families of similar folders."""
    folders = labels_from_folders(atlas.paths, atlas.root)
    names = sorted(set(folders) - {""})
    labels = np.asarray(folders, dtype=object)
    paths, style, content, looks = [], [], [], []
    for name in names:
        members = np.flatnonzero(labels == name)
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


def get_encoder(opts: EncodeOptions) -> CSDEncoder:
    """One loaded model per (device, crop, batch) for the life of the process."""
    key = (opts.device, opts.crop, opts.batch_size, opts.resolution)
    if key not in _ENCODERS:
        _ENCODERS[key] = CSDEncoder(opts.device, opts.crop, opts.batch_size, opts.resolution)
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
                    f"{cached} cached, {len(todo)} to embed ({signature})",
                    f"{cached} 張已有向量，{len(todo)} 張要計算（{signature}）",
                )
            )
            failed += _embed_missing(todo, keys, have, store, opts, progress)
        else:
            progress(
                tr(
                    f"all {len(keys)} images cached ({signature})",
                    f"{len(keys)} 張都已有向量（{signature}）",
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
    encoder = get_encoder(opts)
    progress(tr(f"model ready on {encoder.device}", f"模型已載入（{encoder.device}）"))
    failed: list[tuple[Path, str]] = []
    pending: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    looks: dict[str, np.ndarray] = {}  # measured while each image is open anyway
    done = seen = 0
    load = partial(_prepare, encoder)
    with closing(_ahead(todo, opts.batch_size, load, LOADERS)) as batches:  # Ctrl+C stops loading
        for batch, loaded in batches:
            ok = [(p, r) for p, r in zip(batch, loaded, strict=True) if not isinstance(r, str)]
            failed += [(p, r) for p, r in zip(batch, loaded, strict=True) if isinstance(r, str)]
            if ok:
                emb = encoder.encode_prepared([inputs for _, (inputs, _) in ok])
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
                progress(tr(f"embedded {done}/{len(todo)}", f"已計算 {done}/{len(todo)}"))
    return failed


def _prepare(encoder: CSDEncoder, path: Path) -> tuple[list, np.ndarray] | str:
    """(model inputs, look measures) for one image, or why it cannot be opened."""
    try:
        im = load_rgb(path)
        return encoder.prepare(im), measure(im)
    except LOAD_ERRORS as e:
        return f"cannot open: {e}"


def _ahead(items: list, size: int, load: Callable, workers: int) -> Iterator[tuple[list, list]]:
    """(batch, load(x) for x in batch) in order, in batches of `size`. The next batch is loaded
    on `workers` threads while the caller works on this one. At most `workers` images are open
    at full size at once (loading keeps only the small model inputs)."""
    pool = ThreadPoolExecutor(workers)
    try:
        ahead = [pool.submit(load, x) for x in items[:size]]
        for start in range(0, len(items), size):
            current = ahead
            ahead = [pool.submit(load, x) for x in items[start + size : start + 2 * size]]
            yield items[start : start + size], [f.result() for f in current]
    finally:
        pool.shutdown(cancel_futures=True)


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
                    f"計算 {len(todo)} 張圖的外觀（只算一次）",
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
                        progress(tr(f"measured {done_looks}", f"外觀 {done_looks}"))
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
                f"{root} 裡找不到圖片（png、jpg、jfif、webp、bmp、gif、avif）",
            )
        )
    kept, style, content, failed = embed_paths(paths, opts, progress)
    base = root if root.is_dir() else root.parent
    return Atlas(base, kept, style, content, encoder_signature(opts.crop, opts.resolution), failed)
