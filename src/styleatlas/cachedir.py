"""Where style-atlas keeps its caches (model weights, vectors, thumbnails)."""

from __future__ import annotations

import os
from pathlib import Path


def cache_dir() -> Path:
    root = os.environ.get("STYLE_ATLAS_CACHE") or Path.home() / ".cache" / "style-atlas"
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path
