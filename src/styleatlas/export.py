"""Write cluster results: a CSV/JSON table and, optionally, one folder per style.

Folder export copies (or hard-links) each image with its caption sidecars (.txt, .caption, .json
with the same stem), so a LoRA dataset can be split by style without losing captions. Source files
are never moved or deleted, and an export never writes into a folder that already has files: a
fresh `folders_2`, `folders_3`, ... is used instead, so groups from different runs never mix.

Hard links share the file with the original: editing a linked caption edits the source caption.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from styleatlas.atlas import Atlas
from styleatlas.cluster import UNASSIGNED, Clustering
from styleatlas.report import cluster_table

SIDECARS = (".txt", ".caption", ".json")
EXPORT_MODES = ("copy", "link")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class ExportResult:
    folder: Path
    placed: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)


def folder_name(cid: int, width: int) -> str:
    return "unassigned" if cid == UNASSIGNED else f"style_{cid + 1:0{width}d}"


def _safe_cell(value: object) -> object:
    """Spreadsheet apps run cells starting with = + - @ as formulas; neutralise file names."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def _write_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def write_table(atlas: Atlas, clustering: Clustering, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = cluster_table(atlas, clustering)
    width = max(2, len(str(clustering.n_clusters)))
    for r in rows:
        r["folder"] = folder_name(r["cluster"], width)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["path"])
    w.writeheader()
    w.writerows({k: _safe_cell(v) for k, v in r.items()} for r in rows)
    csv_path = out_dir / "clusters.csv"
    _write_atomic(csv_path, buf.getvalue(), encoding="utf-8-sig")
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
    _write_atomic(json_path, json.dumps(summary, ensure_ascii=False, indent=1))
    return csv_path, json_path


def fresh_dir(base: Path) -> Path:
    """`base` if it is missing or empty, else the first free base_2, base_3, ..."""
    candidate, n = base, 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = base.with_name(f"{base.name}_{n}")
        n += 1
    return candidate


def _place(src: Path, dst: Path, mode: str) -> None:
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")
    if mode == "link":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass  # other drive or no hard-link support: fall back to a copy
    shutil.copy2(src, dst)


def export_folders(
    atlas: Atlas, clustering: Clustering, out_dir: Path, mode: str = "copy"
) -> ExportResult:
    """Copy or hard-link each image (and its sidecars) into style_NN folders of a fresh folder."""
    if mode not in EXPORT_MODES:
        raise ValueError(f"mode must be one of {EXPORT_MODES}")
    result = ExportResult(fresh_dir(Path(out_dir)))
    width = max(2, len(str(clustering.n_clusters)))
    used: dict[Path, set[str]] = {}
    for i, src in enumerate(atlas.paths):
        folder = result.folder / folder_name(int(clustering.labels[i]), width)
        stem = _unique_stem(src.stem, used.setdefault(folder, set()))
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _place(src, folder / f"{stem}{src.suffix}", mode)
            for ext in SIDECARS:
                side = src.with_suffix(ext)
                if side.exists():
                    _place(side, folder / f"{stem}{ext}", mode)
        except OSError as e:  # long path, permissions, full disk: report and keep going
            result.failed.append((src, str(e)))
            continue
        result.placed += 1
    return result


def _unique_stem(stem: str, taken: set[str]) -> str:
    """Same file name from two sub-folders must not collide inside one style folder."""
    name, n = stem, 2
    while name.lower() in taken:
        name = f"{stem}_{n}"
        n += 1
    taken.add(name.lower())
    return name
