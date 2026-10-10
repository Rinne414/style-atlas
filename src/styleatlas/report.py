"""Write the self-contained 3D style map (one HTML file with embedded thumbnails)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from urllib.parse import quote

import numpy as np

from styleatlas.atlas import LOAD_ERRORS, Atlas
from styleatlas.cluster import Clustering, outlier_scores
from styleatlas.dataset import distinctive_tags, tag_summary
from styleatlas.duplicates import near_duplicate_groups
from styleatlas.images import file_time, thumbnail_data_url
from styleatlas.look import LOOK_NAMES
from styleatlas.metrics import centroid
from styleatlas.project import project_3d
from styleatlas.search import knn, nearest_reference

NEIGHBORS = 12
DATA_MARK = "/*__STYLE_ATLAS_DATA__*/null"


def _rel_link(path: Path, out_dir: Path) -> str:
    """URL from the HTML file to the image: relative and percent-encoded (# and % are legal in
    file names), or an absolute file URI when they sit on different Windows drives."""
    try:
        return quote(Path(os.path.relpath(path, out_dir)).as_posix(), safe="/")
    except ValueError:
        return path.resolve().as_uri()


def default_thumb_px(n: int) -> int:
    return 128 if n <= 2048 else 72


@dataclass(frozen=True)
class Layout:
    """Everything the map needs that does not depend on the clustering."""

    coords: np.ndarray
    projection: str
    neighbors: np.ndarray
    outliers: np.ndarray
    duplicates: list[list[int]]
    ref_dist: np.ndarray | None = None  # distance to the nearest --reference image
    ref_name: list[str] | None = None
    ref_title: str | None = None


def compute_layout(
    atlas: Atlas,
    projection: str = "auto",
    progress: Callable[[str], None] = lambda _: None,
    reference: Atlas | None = None,
) -> Layout:
    coords, used = project_3d(atlas.style, projection)
    progress(f"projected {len(atlas)} images with {used}")
    dups = near_duplicate_groups(atlas.style, atlas.content)
    layout = Layout(coords, used, knn(atlas.style, k=NEIGHBORS), outlier_scores(atlas.style), dups)
    if reference is None or not len(reference):
        return layout
    dist, which = nearest_reference(atlas.style, reference.style)
    names = [reference.rel(int(j)) for j in which]
    return replace(layout, ref_dist=dist, ref_name=names, ref_title=reference.root.name)


def build_payload(
    atlas: Atlas,
    clustering: Clustering,
    layout: Layout,
    thumb_of: Callable[[int], str],
    link_of: Callable[[int], str],
    title: str | None = None,
    time_source: str = "none",
    group_tags: dict[int, list[str]] | None = None,
) -> dict:
    times = [file_time(p, time_source) for p in atlas.paths]
    group_tags = group_tags or {}
    points = [
        {
            "p": layout.coords[i].round(4).tolist(),
            "c": int(clustering.labels[i]),
            "t": thumb_of(i),
            "n": atlas.rel(i),
            "f": link_of(i),
            "o": round(float(layout.outliers[i]), 4),
            "k": layout.neighbors[i].tolist(),
            "ts": times[i],
            "r": None if layout.ref_dist is None else round(float(layout.ref_dist[i]), 4),
            "rn": None if layout.ref_name is None else layout.ref_name[i],
        }
        for i in range(len(atlas))
    ]
    if atlas.looks is not None:
        rows = atlas.looks.astype(np.float64).round(3).tolist()  # float32 would print 0.59100002
        for pt, row in zip(points, rows, strict=True):
            pt["lk"] = row
    return {
        "title": title or atlas.root.name or "style atlas",
        "projection": layout.projection,
        "method": clustering.method,
        "params": clustering.params,
        "signature": atlas.signature,
        "clusters": [
            {
                "id": c.id,
                "size": c.size,
                "medoid": c.medoid,
                "cohesion": round(c.cohesion, 4),
                "tags": group_tags.get(c.id, []),
            }
            for c in clustering.clusters
        ],
        "points": points,
        "duplicates": layout.duplicates,
        "time_source": time_source if any(v is not None for v in times) else "none",
        "reference": layout.ref_title,
        "look_names": list(LOOK_NAMES) if atlas.looks is not None else [],
    }


def map_payload(
    atlas: Atlas,
    clustering: Clustering,
    out_path: Path,
    projection: str = "auto",
    thumb_px: int | None = None,
    title: str | None = None,
    progress: Callable[[str], None] = lambda _: None,
    time_source: str = "none",
    reference: Atlas | None = None,
    layout: Layout | None = None,
) -> dict:
    """Payload for a standalone file: thumbnails embedded, links relative to the HTML file.
    Pass `layout` to reuse one already computed (the web app's)."""
    px = thumb_px or default_thumb_px(len(atlas))
    layout = layout or compute_layout(atlas, projection, progress, reference)
    out_dir = out_path.resolve().parent

    def thumb_of(i: int) -> str:
        if (i + 1) % 500 == 0:
            progress(f"thumbnails {i + 1}/{len(atlas)}")
        try:
            return thumbnail_data_url(atlas.paths[i], size=px)
        except LOAD_ERRORS:
            return ""

    def link_of(i: int) -> str:
        return _rel_link(atlas.paths[i], out_dir)

    tags = distinctive_tags(tag_summary(atlas.paths, clustering))
    return build_payload(atlas, clustering, layout, thumb_of, link_of, title, time_source, tags)


def _vendor(name: str) -> str:
    code = resources.files("styleatlas").joinpath(f"templates/vendor/{name}").read_text("utf-8")
    return code.replace("</script", r"<\/script")  # cannot end the <script> element early


def page_script() -> str:
    """The page's module script: the map viewer, its layouts and labels, then the web-app
    features and start-up."""
    files = resources.files("styleatlas").joinpath("templates")
    parts = ("map.js", "map_layout.js", "map_app.js")
    return "\n".join(files.joinpath(f).read_text("utf-8") for f in parts)


def render_html(payload: dict) -> str:
    files = resources.files("styleatlas").joinpath("templates")
    template = files.joinpath("map.html").read_text("utf-8")
    template = template.replace("/*__MAP_CSS__*/", files.joinpath("map.css").read_text("utf-8"), 1)
    template = template.replace("/*__MAP_JS__*/", page_script(), 1)
    template = template.replace("/*__THREE_JS__*/", _vendor("three.module.min.js"), 1)
    template = template.replace("/*__ORBIT_JS__*/", _vendor("OrbitControls.js"), 1)
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
    time_source: str = "none",
    reference: Atlas | None = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = map_payload(
        atlas, clustering, out_path, projection, thumb_px, title, progress, time_source, reference
    )
    return write_payload(payload, out_path)


def write_payload(payload: dict, out_path: Path) -> Path:
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
        if atlas.looks is not None:
            rows[-1].update(
                zip(LOOK_NAMES, (round(float(v), 4) for v in atlas.looks[i]), strict=True)
            )
    return rows
