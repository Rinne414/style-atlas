"""The report command: one HTML page that sums up a folder's style (see report_card.py)."""

from __future__ import annotations

import argparse
from pathlib import Path

from styleatlas.atlas import Atlas, build_atlas
from styleatlas.cli_common import _atlas, _opts, _space, log, saved_groups, web_exclusions
from styleatlas.export import output_dir
from styleatlas.images import labels_from_folders
from styleatlas.lang import chinese, tr
from styleatlas.metrics import PLAIN

CLOSEST = 5  # reference artists listed


def cmd_report(a: argparse.Namespace) -> int:
    from styleatlas.report_card import write_report

    if a.renders and _space(a) != PLAIN:
        raise ValueError(
            tr(
                "--renders compares plain style vectors: leave out --neutralize and "
                "--ignore-characters",
                "--renders 比的是原始畫風向量：請拿掉 --neutralize 和 --ignore-characters",
            )
        )
    atlas = _atlas(a, a.folder).with_looks(_opts(a), log)
    if len(atlas) == 0:
        log(tr(f"no readable images in {a.folder}", f"{a.folder} 裡沒有讀得到的圖"))
        return 1
    excluded = web_exclusions(atlas, Path(a.folder))
    if len(excluded) == len(atlas):
        log(
            tr(
                "every image is excluded in the web app; nothing to report",
                "所有圖都在網頁裡排除了；沒有東西可以做報告",
            )
        )
        return 1
    if excluded:
        log(
            tr(
                f"{len(excluded)} image(s) you excluded in the web app are left out",
                f"略過你在網頁裡排除的 {len(excluded)} 張圖",
            )
        )
    clustering, names = saved_groups(a, atlas, Path(a.folder))
    closest = None
    if a.artists:
        skip = set(excluded)
        closest = _closest_artists(a, atlas.subset([i for i in range(len(atlas)) if i not in skip]))
    out = Path(a.out or output_dir(Path(a.folder)) / "style_report.html")
    renders = None
    if a.renders:
        renders = _atlas(a, a.renders).with_looks(_opts(a), log)
        log(
            tr(
                f"checking {len(renders)} renders from {a.renders} against this training set",
                f"用這個訓練集檢查 {len(renders)} 張算圖（{a.renders}）",
            )
        )
    title = a.title or Path(a.folder).resolve().name
    path = write_report(
        atlas,
        clustering,
        out,
        title,
        names=names,
        closest=closest,
        lang=a.lang or ("zh" if chinese() else "en"),
        excluded=excluded,
        renders=renders,
        time_source=a.time,
    )
    log(tr("report:", "報告："))
    print(path)
    return 0


def _closest_artists(a: argparse.Namespace, atlas: Atlas) -> list[tuple[str, float]] | None:
    """The reference library's sub-folders closest to the whole folder (search --by-folder)."""
    from styleatlas.search import rank_folders

    library = build_atlas(Path(a.artists), _opts(a), log)
    folders = labels_from_folders(library.paths, library.root)
    if len(set(folders) - {""}) < 2:
        log(
            tr(
                f"{a.artists} has fewer than 2 sub-folders; no closest artists listed",
                f"{a.artists} 的子資料夾少於 2 個；不列最接近的畫師",
            )
        )
        return None
    hits = rank_folders(atlas.style, library.style, folders, top=CLOSEST, combine=True)[0]
    return [(h.folder, h.score) for h in hits]


def report_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder")
    p.add_argument(
        "-o", "--out", help="HTML file (default: <folder>_style_atlas/style_report.html)"
    )
    p.add_argument("--title")
    p.add_argument(
        "--lang", choices=["zh", "en"], help="the page's language (default: as the messages)"
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="group afresh instead of using the groups the web app saved",
    )
    p.add_argument(
        "--renders",
        metavar="DIR",
        help="a LoRA's test images: check them against this folder as its training set",
    )
    p.add_argument(
        "--artists",
        metavar="DIR",
        help="a library with one sub-folder per artist: list the closest ones",
    )
