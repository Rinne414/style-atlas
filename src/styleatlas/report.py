"""Write the self-contained 3D style map (one HTML file with embedded thumbnails)."""

from __future__ import annotations

import base64
import json
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from urllib.parse import quote

import numpy as np

from styleatlas.atlas import LOAD_ERRORS, Atlas
from styleatlas.cluster import Clustering, outlier_scores
from styleatlas.dataset import distinctive_tags, tag_summary
from styleatlas.duplicates import near_duplicate_groups
from styleatlas.images import preview_bytes, thumbnail_data_url, usable_times
from styleatlas.lang import tr
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


SLOW_LAYOUT = 1000  # images from which the map layout says it is working first


def compute_layout(
    atlas: Atlas,
    projection: str = "auto",
    progress: Callable[[str], None] = lambda _: None,
    reference: Atlas | None = None,
) -> Layout:
    if len(atlas) >= SLOW_LAYOUT:  # the projection says nothing while it runs
        progress(
            tr(
                f"placing {len(atlas)} images on the 3D map (this can take a minute or two)",
                f"正在計算 {len(atlas)} 張在 3D 地圖上的位置（可能要一兩分鐘）",
            )
        )
    coords, used = project_3d(atlas.style, projection)
    progress(
        tr(
            f"projected {len(atlas)} images with {used}",
            f"已算好 {len(atlas)} 張在 3D 地圖上的位置（{used}）",
        )
    )
    dups = near_duplicate_groups(atlas.style, atlas.content)
    layout = Layout(coords, used, knn(atlas.style, k=NEIGHBORS), outlier_scores(atlas.style), dups)
    return with_reference(layout, atlas, reference)


def with_reference(layout: Layout, atlas: Atlas, reference: Atlas | None) -> Layout:
    """The layout with its originality fields measured against `reference` (cleared for None);
    positions and everything else stay."""
    if reference is None or not len(reference):
        return replace(layout, ref_dist=None, ref_name=None, ref_title=None)
    dist, which = nearest_reference(atlas.style, reference.style)
    names = [reference.rel(int(j)) for j in which]
    return replace(layout, ref_dist=dist, ref_name=names, ref_title=reference.root.name)


NEAR_GROUPS = 3


def nearest_groups(atlas: Atlas, clustering: Clustering) -> dict[int, list[list]]:
    """For each group, the closest other groups: [[id, centroid distance], ...]."""
    groups = [c for c in clustering.clusters if c.size]
    if len(groups) < 2:
        return {}
    cents = np.stack([centroid(atlas.style[c.members]) for c in groups])
    dist = 1.0 - cents @ cents.T
    np.fill_diagonal(dist, np.inf)
    out = {}
    for row, c in enumerate(groups):
        order = np.argsort(dist[row])[: min(NEAR_GROUPS, len(groups) - 1)]  # never itself
        out[c.id] = [[groups[j].id, round(float(dist[row, j]), 3)] for j in order]
    return out


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
    usable = usable_times(atlas.paths, time_source)
    times = [None] * len(atlas) if usable is None else [_or_none(v) for v in usable]
    return {
        "title": title or atlas.root.name or "style atlas",
        "projection": layout.projection,
        "method": clustering.method,
        "params": clustering.params,
        "signature": atlas.signature,
        "clusters": _cluster_rows(atlas, clustering, group_tags or {}),
        "points": _points(atlas, clustering, layout, thumb_of, link_of, times),
        "duplicates": layout.duplicates,
        "time_source": time_source if usable is not None else "none",
        "reference": layout.ref_title,
        "look_names": list(LOOK_NAMES) if atlas.looks is not None else [],
    }


def _cluster_rows(atlas: Atlas, clustering: Clustering, group_tags: dict) -> list[dict]:
    near = nearest_groups(atlas, clustering)
    return [
        {
            "id": c.id,
            "size": c.size,
            "medoid": c.medoid,
            "cohesion": round(c.cohesion, 4),
            "tags": group_tags.get(c.id, []),
            "near": near.get(c.id, []),
        }
        for c in clustering.clusters
    ]


def centre_distances(x: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Each image's style distance to its group's centre (as a group's cohesion averages it),
    NaN for the unassigned: the group view lists the most typical first."""
    labels = np.asarray(labels)
    out = np.full(len(labels), np.nan)
    for cid in np.unique(labels[labels >= 0]):
        rows = np.flatnonzero(labels == cid)
        out[rows] = 1.0 - x[rows] @ centroid(x[rows])
    return out


def _or_none(v: float) -> float | None:  # JSON has no NaN
    return None if np.isnan(v) else float(v)


def _points(
    atlas: Atlas,
    clustering: Clustering,
    layout: Layout,
    thumb_of: Callable[[int], str],
    link_of: Callable[[int], str],
    times: list,
) -> list[dict]:
    centre = centre_distances(atlas.style, clustering.labels)
    points = [
        {
            "p": layout.coords[i].round(4).tolist(),
            "c": int(clustering.labels[i]),
            "g": _or_none(round(float(centre[i]), 4)),
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
    return points


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
    preview_px: int = 0,
) -> dict:
    """Payload for a standalone file: thumbnails embedded, links relative to the HTML file.
    Pass `layout` to reuse one already computed (the web app's). With `preview_px`, each point
    also carries a picture that size ("v"), for the recipient's close-ups and viewer: the links
    lead into the sender's folder, which the recipient does not have."""
    px = thumb_px or default_thumb_px(len(atlas))
    layout = layout or compute_layout(atlas, projection, progress, reference)
    out_dir = out_path.resolve().parent

    def thumb_of(i: int) -> str:
        if (i + 1) % 500 == 0:
            progress(tr(f"thumbnails {i + 1}/{len(atlas)}", f"縮圖 {i + 1}/{len(atlas)}"))
        try:
            return thumbnail_data_url(atlas.paths[i], size=px)
        except LOAD_ERRORS:
            return ""

    def link_of(i: int) -> str:
        return _rel_link(atlas.paths[i], out_dir)

    tags = distinctive_tags(tag_summary(atlas.paths, clustering))
    payload = build_payload(atlas, clustering, layout, thumb_of, link_of, title, time_source, tags)
    if preview_px:
        for i, data in enumerate(_previews(atlas.paths, preview_px)):
            if data:
                payload["points"][i]["v"] = (
                    "data:image/webp;base64," + base64.b64encode(data).decode()
                )
    return payload


PREVIEW_WORKERS = 4  # previews made at once (about 18 ms each from the cached 512 px views)


def _previews(paths: list[Path], px: int) -> list[bytes]:
    """Each picture's preview, b"" for one that cannot be read."""

    def one(path: Path) -> bytes:
        try:
            return preview_bytes(path, px)
        except LOAD_ERRORS:
            return b""

    with ThreadPoolExecutor(max_workers=PREVIEW_WORKERS) as pool:
        return list(pool.map(one, paths))


def _vendor(name: str) -> str:
    code = resources.files("styleatlas").joinpath(f"templates/vendor/{name}").read_text("utf-8")
    return code.replace("</script", r"<\/script")  # cannot end the <script> element early


def page_script() -> str:
    """The page's module script: the map viewer, its layouts and labels, then the web-app
    features and start-up."""
    files = resources.files("styleatlas").joinpath("templates")
    parts = (
        "map_i18n.js",
        "map.js",
        "map_layout.js",
        "map_sharp.js",
        "map_group.js",
        "map_browse.js",
        "map_viewer.js",
        "map_walk.js",
        "map_shell.js",
        "map_export.js",
        "map_app.js",
    )
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
    families: bool = False,
    preview_px: int = 0,
) -> Path:
    """With `families`, the points are sub-folders (folder_atlas) and the groups families of
    them: the page says so on the cards."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = map_payload(
        atlas,
        clustering,
        out_path,
        projection,
        thumb_px,
        title,
        progress,
        time_source,
        reference,
        preview_px=preview_px,
    )
    if families:
        payload["families"] = True
    return write_payload(payload, out_path)


def write_payload(payload: dict, out_path: Path) -> Path:
    tmp = out_path.with_name(f"{out_path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
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
