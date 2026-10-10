"""The report command: one HTML page that sums up a folder's style (see report_card.py)."""

from __future__ import annotations

import argparse
from pathlib import Path

from styleatlas.atlas import Atlas, build_atlas
from styleatlas.cli_common import _atlas, _cluster, _opts, log, web_exclusions
from styleatlas.cluster import Clustering, edit_groups
from styleatlas.export import output_dir
from styleatlas.groupfile import GROUPS_FILE, carry_names, load_groups
from styleatlas.images import labels_from_folders

CLOSEST = 5  # reference artists listed


def cmd_report(a: argparse.Namespace) -> int:
    from styleatlas.report_card import write_report

    atlas = _atlas(a, a.folder).with_looks(_opts(a), log)
    if len(atlas) == 0:
        log(f"no readable images in {a.folder}")
        return 1
    excluded = web_exclusions(atlas, Path(a.folder))
    if len(excluded) == len(atlas):
        log("every image is excluded in the web app; nothing to report")
        return 1
    if excluded:
        log(f"{len(excluded)} image(s) you excluded in the web app are left out")
    clustering, names = _groups(a, atlas)
    closest = None
    if a.artists:
        skip = set(excluded)
        closest = _closest_artists(a, atlas.subset([i for i in range(len(atlas)) if i not in skip]))
    out = Path(a.out or output_dir(Path(a.folder)) / "style_report.html")
    title = a.title or Path(a.folder).resolve().name
    path = write_report(
        atlas,
        clustering,
        out,
        title,
        names=names,
        closest=closest,
        lang=a.lang,
        excluded=excluded,
    )
    print(path)
    return 0


def _groups(a: argparse.Namespace, atlas: Atlas) -> tuple[Clustering, dict[int, str]]:
    """The groups as left in the web app (hand edits and names), else a fresh grouping."""
    clustering = _cluster(a, atlas)
    saved = load_groups(output_dir(Path(a.folder)) / GROUPS_FILE, atlas)
    if saved is None:
        return clustering, {}
    log("using the groups and names saved by the web app")
    edited = edit_groups(atlas.style, clustering, dict(enumerate(saved.labels.tolist())))
    return edited, carry_names(saved.labels, edited.labels, saved.names)


def _closest_artists(a: argparse.Namespace, atlas: Atlas) -> list[tuple[str, float]] | None:
    """The reference library's sub-folders closest to the whole folder (search --by-folder)."""
    from styleatlas.search import rank_folders

    library = build_atlas(Path(a.artists), _opts(a), log)
    folders = labels_from_folders(library.paths, library.root)
    if len(set(folders) - {""}) < 2:
        log(f"{a.artists} has fewer than 2 sub-folders; no closest artists listed")
        return None
    hits = rank_folders(atlas.style, library.style, folders, top=CLOSEST, combine=True)[0]
    return [(h.folder, h.score) for h in hits]


def report_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder")
    p.add_argument(
        "-o", "--out", help="HTML file (default: <folder>_style_atlas/style_report.html)"
    )
    p.add_argument("--title")
    p.add_argument("--lang", choices=["zh", "en"], default="zh")
    p.add_argument(
        "--artists",
        metavar="DIR",
        help="a library with one sub-folder per artist: list the closest ones",
    )
