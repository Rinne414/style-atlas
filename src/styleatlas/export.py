"""Write cluster results: a CSV/JSON table and, optionally, one folder per style.

Folder export copies (or hard-links) each image with its caption sidecars (.txt, .caption, .json
with the same stem), so a LoRA dataset can be split by style without losing captions. Source files
are never moved or deleted.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

from styleatlas.atlas import Atlas
from styleatlas.cluster import UNASSIGNED, Clustering
from styleatlas.report import cluster_table

SIDECARS = (".txt", ".caption", ".json")
EXPORT_MODES = ("copy", "link")


def folder_name(cid: int, width: int) -> str:
    return "unassigned" if cid == UNASSIGNED else f"style_{cid + 1:0{width}d}"


def write_table(atlas: Atlas, clustering: Clustering, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = cluster_table(atlas, clustering)
    width = max(2, len(str(clustering.n_clusters)))
    for r in rows:
        r["folder"] = folder_name(r["cluster"], width)
    csv_path = out_dir / "clusters.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["path"])
        w.writeheader()
        w.writerows(rows)
    summary = {
        "images": len(atlas),
        "method": clustering.method,
        "params": clustering.params,
        "signature": atlas.signature,
        "unassigned": clustering.n_unassigned,
        "clusters": [
            {
                "folder": folder_name(c.id, width),
                "size": c.size,
                "cohesion": round(c.cohesion, 4),
                "representative": atlas.rel(c.medoid),
            }
            for c in clustering.clusters
        ],
    }
    json_path = out_dir / "clusters.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return csv_path, json_path


def _place(src: Path, dst: Path, mode: str) -> None:
    if dst.exists():
        return
    if mode == "link":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass  # other drive or no hard-link support: fall back to a copy
    shutil.copy2(src, dst)


def export_folders(atlas: Atlas, clustering: Clustering, out_dir: Path, mode: str = "copy") -> int:
    """Copy or hard-link each image (and its sidecars) into style_NN folders; returns the count."""
    if mode not in EXPORT_MODES:
        raise ValueError(f"mode must be one of {EXPORT_MODES}")
    width = max(2, len(str(clustering.n_clusters)))
    placed = 0
    used: dict[Path, set[str]] = {}
    for i, src in enumerate(atlas.paths):
        folder = out_dir / folder_name(int(clustering.labels[i]), width)
        folder.mkdir(parents=True, exist_ok=True)
        stem = _unique_stem(src.stem, used.setdefault(folder, set()))
        _place(src, folder / f"{stem}{src.suffix}", mode)
        placed += 1
        for ext in SIDECARS:
            side = src.with_suffix(ext)
            if side.exists():
                _place(side, folder / f"{stem}{ext}", mode)
    return placed


def _unique_stem(stem: str, taken: set[str]) -> str:
    """Same file name from two sub-folders must not collide inside one style folder."""
    name, n = stem, 2
    while name.lower() in taken:
        name = f"{stem}_{n}"
        n += 1
    taken.add(name.lower())
    return name
