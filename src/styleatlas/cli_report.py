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
                "--renders 比的是原始画风向量：请拿掉 --neutralize 和 --ignore-characters",
            )
        )
    atlas = _atlas(a, a.folder).with_looks(_opts(a), log)
    if len(atlas) == 0:
        log(tr(f"no readable images in {a.folder}", f"{a.folder} 里没有读得到的图"))
        return 1
    excluded = web_exclusions(atlas, Path(a.folder))
    if len(excluded) == len(atlas):
        log(
            tr(
                "every image is excluded in the web app; nothing to report",
                "所有图都在网页里排除了；没有东西可以做报告",
            )
        )
        return 1
    if excluded:
        log(
            tr(
                f"{len(excluded)} image(s) you excluded in the web app are left out",
                f"略过你在网页里排除的 {len(excluded)} 张图",
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
                f"用这个训练集检查 {len(renders)} 张出图（{a.renders}）",
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
        folders=_space(a) == PLAIN,  # the families' cut was measured on plain CSD
    )
    log(tr("report:", "报告："))
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
                f"{a.artists} 的子文件夹少于 2 个；不列最接近的画师",
            )
        )
        return None
    hits = rank_folders(atlas.style, library.style, folders, top=CLOSEST, combine=True)[0]
    return [(h.folder, h.score) for h in hits]


def report_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder")
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "HTML file (default: <folder>_style_atlas/style_report.html)",
            "HTML 文件（默认：<文件夹>_style_atlas/style_report.html）",
        ),
    )
    p.add_argument(
        "--title", help=tr("page title (default: the folder name)", "页面标题（默认：文件夹名称）")
    )
    p.add_argument(
        "--lang",
        choices=["zh", "en"],
        help=tr("the page's language (default: as the messages)", "页面的语言（默认：和消息相同）"),
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help=tr(
            "group afresh instead of using the groups the web app saved",
            "重新分组，不沿用网页界面存的分组",
        ),
    )
    p.add_argument(
        "--renders",
        metavar="DIR",
        help=tr(
            "a LoRA's test images: check them against this folder as its training set",
            "某个 LoRA 的出图：拿这个文件夹当它的训练集来检查",
        ),
    )
    p.add_argument(
        "--artists",
        metavar="DIR",
        help=tr(
            "a library with one sub-folder per artist: list the closest ones",
            "每位画师一个子文件夹的图库：列出最接近的几位",
        ),
    )
