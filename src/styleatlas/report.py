"""Write the self-contained 3D style map (one HTML file with embedded thumbnails)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from importlib import resources
from pathlib import Path

from styleatlas.atlas import Atlas
from styleatlas.cluster import Clustering, outlier_scores
from styleatlas.images import thumbnail_data_url
from styleatlas.metrics import centroid
from styleatlas.project import project_3d
from styleatlas.search import knn

NEIGHBORS = 12
DATA_MARK = "/*__STYLE_ATLAS_DATA__*/null"


def _rel_link(path: Path, out_dir: Path) -> str:
    try:
        return Path(os.path.relpath(path, out_dir)).as_posix()
    except ValueError:  # different drive on Windows
        return path.resolve().as_uri()


def map_payload(
    atlas: Atlas,
    clustering: Clustering,
    out_path: Path,
    projection: str = "auto",
    thumb_px: int | None = None,
    title: str | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> dict:
    thumb_px = thumb_px or (128 if len(atlas) <= 2048 else 72)
    coords, used = project_3d(atlas.style, projection)
    progress(f"projected {len(atlas)} images with {used}")
    neighbors = knn(atlas.style, k=NEIGHBORS)
    outliers = outlier_scores(atlas.style)
    out_dir = out_path.resolve().parent
    points = []
    for i, p in enumerate(atlas.paths):
        try:
            thumb = thumbnail_data_url(p, size=thumb_px)
        except OSError:
            thumb = ""
        points.append(
            {
                "p": coords[i].round(4).tolist(),
                "c": int(clustering.labels[i]),
                "t": thumb,
                "n": atlas.rel(i),
                "f": _rel_link(p, out_dir),
                "o": round(float(outliers[i]), 4),
                "k": neighbors[i].tolist(),
            }
        )
        if (i + 1) % 500 == 0:
            progress(f"thumbnails {i + 1}/{len(atlas)}")
    return {
        "title": title or atlas.root.name or "style atlas",
        "projection": used,
        "method": clustering.method,
        "params": clustering.params,
        "signature": atlas.signature,
        "clusters": [
            {"id": c.id, "size": c.size, "medoid": c.medoid, "cohesion": round(c.cohesion, 4)}
            for c in clustering.clusters
        ],
        "points": points,
    }


def render_html(payload: dict) -> str:
    template = resources.files("styleatlas").joinpath("templates/map.html").read_text("utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # "<", ">" and "&" only occur inside JSON strings; escaping them keeps file names inert
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace(DATA_MARK, data)


def write_map(
    atlas: Atlas,
    clustering: Clustering,
    out_path: Path,
    projection: str = "auto",
    thumb_px: int | None = None,
    title: str | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = map_payload(atlas, clustering, out_path, projection, thumb_px, title, progress)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(render_html(payload), encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path


def cluster_table(atlas: Atlas, clustering: Clustering) -> list[dict]:
    """One row per image, for CSV / JSON export."""
    outliers = outlier_scores(atlas.style)
    cents = {c.id: centroid(atlas.style[c.members]) for c in clustering.clusters}
    rows = []
    for i in range(len(atlas)):
        cid = int(clustering.labels[i])
        dist = round(float(1.0 - atlas.style[i] @ cents[cid]), 4) if cid >= 0 else None
        rows.append(
            {
                "path": atlas.rel(i),
                "cluster": cid,
                "distance_to_cluster": dist,
                "outlier": round(float(outliers[i]), 4),
            }
        )
    return rows
