"""Embed a folder (or file list) with caching: the input every command starts from."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.encoder import CSDEncoder, cache_dir, encoder_signature
from styleatlas.images import find_images, load_rgb
from styleatlas.store import VectorStore

Progress = Callable[[str], None]
LOAD_ERRORS = (OSError, ValueError, Image.DecompressionBombError, SyntaxError)


@dataclass
class EncodeOptions:
    device: str = "auto"
    crop: str = "center"
    batch_size: int = 8
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

    def __len__(self) -> int:
        return len(self.paths)

    def rel(self, i: int) -> str:
        p = self.paths[i]
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.as_posix()

    def subset(self, idx: np.ndarray | list[int]) -> Atlas:
        idx = list(idx)
        return Atlas(
            self.root,
            [self.paths[i] for i in idx],
            self.style[idx],
            self.content[idx],
            self.signature,
        )


def _silent(_: str) -> None:
    return None


_ENCODERS: dict[tuple[str, str, int], CSDEncoder] = {}


def get_encoder(opts: EncodeOptions) -> CSDEncoder:
    """One loaded model per (device, crop, batch) for the life of the process."""
    key = (opts.device, opts.crop, opts.batch_size)
    if key not in _ENCODERS:
        _ENCODERS[key] = CSDEncoder(device=opts.device, crop=opts.crop, batch_size=opts.batch_size)
    return _ENCODERS[key]


def embed_paths(
    paths: list[Path], opts: EncodeOptions, progress: Progress = _silent
) -> tuple[list[Path], np.ndarray, np.ndarray, list[tuple[Path, str]]]:
    """Vectors for `paths` (cached ones reused). Returns kept paths, style, content, failures."""
    signature = encoder_signature(opts.crop)
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
        done += len(ims)
        if len(pending) >= opts.save_every or start + opts.batch_size >= len(todo):
            store.put(pending, encoder.signature)
            have.update(pending)
            pending = {}
            progress(f"embedded {done}/{len(todo)}")
    return failed


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
    return Atlas(base, kept, style, content, encoder_signature(opts.crop), failed)
