"""Embed a folder (or file list) with caching: the input every command starts from."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.encoder import CSDEncoder, cache_dir, encoder_signature
from styleatlas.images import find_images, labels_from_folders, load_rgb
from styleatlas.look import LOOK_NAMES, LOOK_VERSION, measure
from styleatlas.metrics import StyleSpace, centroid
from styleatlas.store import VectorStore

Progress = Callable[[str], None]
LOAD_ERRORS = (OSError, ValueError, Image.DecompressionBombError, SyntaxError)
LOOK_CHUNK = 500  # images measured between cache saves


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
            progress(f"{len(first_by_key) - len(todo)} cached, {len(todo)} to embed ({signature})")
            failed += _embed_missing(todo, keys, have, store, opts, progress)
        else:
            progress(f"all {len(keys)} images cached ({signature})")
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
    progress(f"model ready on {encoder.device}")
    failed: list[tuple[Path, str]] = []
    pending: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    looks: dict[str, np.ndarray] = {}  # measured while each image is open anyway
    done = 0
    for start in range(0, len(todo), opts.batch_size):
        ims, owners = [], []
        for p in todo[start : start + opts.batch_size]:
            try:
                ims.append(load_rgb(p))
                owners.append(p)
            except LOAD_ERRORS as e:
                failed.append((p, f"cannot open: {e}"))
        if ims:
            emb = encoder.encode(ims)
            for i, p in enumerate(owners):
                pending[keys[p]] = (emb.style[i], emb.content[i])
                looks[keys[p]] = measure(ims[i])
        done += len(ims)
        if len(pending) >= opts.save_every or start + opts.batch_size >= len(todo):
            store.put(pending, encoder.signature)
            store.put_looks(looks, LOOK_VERSION)
            looks = {}
            have.update(pending)
            pending = {}
            progress(f"embedded {done}/{len(todo)}")
    return failed


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
            progress(f"measuring the look of {len(todo)} images (once)")
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
                        progress(f"measured {start + len(part)}/{len(todo)}")
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
        raise FileNotFoundError(f"no images found under {root}")
    kept, style, content, failed = embed_paths(paths, opts, progress)
    base = root if root.is_dir() else root.parent
    return Atlas(base, kept, style, content, encoder_signature(opts.crop, opts.resolution), failed)
