"""Command line: style-atlas <command> ...  (run `style-atlas <command> -h` for options)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np

from styleatlas import __version__
from styleatlas.atlas import build_atlas, embed_paths
from styleatlas.cli_common import (  # noqa: F401 (re-exported for tests and callers)
    SOFT_PERIODS,
    _atlas,
    _cluster,
    _log_space,
    _neutralize_count,
    _opts,
    _positive_int,
    _reference,
    _space,
    characters_help,
    log,
    neutralize_help,
    reference_help,
)
from styleatlas.cli_inspect import cmd_audit, cmd_compare, cmd_duplicates, cmd_outliers
from styleatlas.cli_lora import FEW_FOR_LORA, _lora_args, cmd_cluster  # noqa: F401
from styleatlas.cli_report import cmd_report, report_args
from styleatlas.cli_sort import cmd_sort, sort_args
from styleatlas.cli_taste import cmd_taste, taste_args
from styleatlas.cluster import ARTISTS, GRANULARITY, METHODS, PERIODS
from styleatlas.encoder import CROP_MODES, RESOLUTIONS
from styleatlas.images import TIME_SOURCES, find_images, labels_from_folders
from styleatlas.lang import columns, pad, tr, wrap
from styleatlas.metrics import (
    PLAIN,
    split_half_noise,
    unit,
)
from styleatlas.project import PROJECTIONS
from styleatlas.timeline import TIMELINE


def cmd_embed(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    n, skipped = len(atlas), len(atlas.failed)
    log(tr(f"{n} images embedded, {skipped} skipped", f"{n} 张已算好向量，{skipped} 张略过"))
    return 0


LARGE_MAP = 8000  # thumbnails make the single-file map ~2 KB per image
LARGE_SHARE_MB = 10  # Discord's upload limit without Nitro


def cmd_map(a: argparse.Namespace) -> int:
    from styleatlas.export import output_dir
    from styleatlas.report import write_map

    atlas = _atlas(a, a.folder).with_looks(_opts(a), log)
    if a.by_folder:
        from styleatlas.atlas import MIN_FOLDERS, folder_atlas
        from styleatlas.cluster import family_cut

        atlas = folder_atlas(atlas)
        if len(atlas) < MIN_FOLDERS:
            log(
                tr(
                    f"{a.folder} has {len(atlas)} sub-folders; --by-folder needs at least 3",
                    f"{a.folder} 只有 {len(atlas)} 个子文件夹；--by-folder 至少要 3 个",
                )
            )
            return 1
        log(
            tr(
                f"{len(atlas)} sub-folders, each shown by its most typical image",
                f"{len(atlas)} 个子文件夹，每个用最有代表性的一张图显示",
            )
        )
        a.families = True
        if a.granularity == "auto" and a.threshold is None and a.k is None:
            a.threshold = family_cut(atlas.style)  # the automatic cut lumps folder means
    if len(atlas) > LARGE_MAP:
        log(
            tr(
                f"{len(atlas)} images: the HTML file will be large; "
                "`style-atlas serve` loads faster",
                f"{len(atlas)} 张图：HTML 文件会很大；用 `style-atlas serve` 开会比较快",
            )
        )
    result = _cluster(a, atlas)
    out = Path(a.out or output_dir(Path(a.folder)) / "style_atlas_map.html")
    path = write_map(
        atlas,
        result,
        out,
        a.projection,
        a.thumb,
        a.title,
        progress=log,
        time_source=a.time,
        reference=_reference(a),
        families=getattr(a, "families", False),
        preview_px=a.pictures,
    )
    log(
        tr(
            "open it in a browser (double-click); press ? on the page for help",
            "用浏览器打开（双击文件）；在页面上按 ? 看说明",
        )
    )
    mb = path.stat().st_size / 1e6
    log(
        tr(
            f"file size {mb:.1f} MB (the thumbnails are inside)",
            f"文件大小 {mb:.1f} MB（缩略图都在文件里）",
        )
    )
    if mb > LARGE_SHARE_MB:
        log(
            tr(
                f"over {LARGE_SHARE_MB} MB: some chat apps refuse it (Discord's free limit is "
                "10 MB); --thumb 64 makes it smaller",
                f"超过 {LARGE_SHARE_MB} MB：有些聊天软件传不了（Discord 免费账号上限 10 MB）；"
                "加 --thumb 64 可以变小",
            )
        )
    print(path)
    return 0


def cmd_search(a: argparse.Namespace) -> int:
    from styleatlas.search import search

    opts = _opts(a)
    missing = [q for q in a.query if not Path(q).exists()]
    if missing:
        raise FileNotFoundError(tr("not found: ", "找不到：") + ", ".join(missing))
    qpaths = [p for q in a.query for p in find_images(Path(q))]
    qkept, qstyle, qcontent, failed = embed_paths(qpaths, opts, log)
    for p, why in failed:
        log(tr(f"query skipped {p}: {why}", f"略过查找图 {p}：{why}"))
    if not qkept:
        log(tr("no readable query images", "查找的图都读不了"))
        return 1
    atlas = build_atlas(Path(a.within), opts, log, recursive=not a.no_recursive)
    plain = atlas.style  # near-copies are judged in plain CSD
    space = _space(a)
    if space != PLAIN:
        atlas, fitted = atlas.in_space(space)
        qstyle = fitted.apply(qstyle, qcontent)
    query_files = {q.resolve() for q in qkept}
    same = {i for i, p in enumerate(atlas.paths) if p.resolve() in query_files}
    names = [ALL_QUERIES] if a.combine else [str(p) for p in qkept]
    if a.by_folder:
        return _search_folders(a, atlas, qstyle, names, same)
    if a.keep_duplicates:
        results = search(qstyle, atlas.style, top=a.top, combine=a.combine, exclude=same)
    else:
        results = _search_folded(a, atlas, qstyle, plain, same)
    rows = [
        {
            "query": names[qi],
            "rank": r + 1,
            "path": atlas.rel(h.index),
            "score": round(h.score, 4),
            "cosine": round(h.cosine, 4),
        }
        for qi, hits in enumerate(results)
        for r, h in enumerate(hits)
    ]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        _print_by_query(rows, lambda r: f"{r['rank']:3d}  {r['cosine']:.3f}  {r['path']}")
        log(tr(SEARCH_ORDER_EN, SEARCH_ORDER_ZH))
    if a.copy_to:
        _copy_matches(atlas, [h.index for hits in results for h in hits], Path(a.copy_to))
    return 0


def _search_folders(a: argparse.Namespace, atlas, qstyle, names: list[str], same: set) -> int:
    from styleatlas.search import folder_verdict, rank_folders

    if a.copy_to:
        log(
            tr(
                "--copy-to copies single images; it is not used with --by-folder",
                "--copy-to 只复制单张图，和 --by-folder 一起用时不会作用",
            )
        )
    folders = labels_from_folders(atlas.paths, atlas.root)
    if len(set(folders) - {""}) < 2:
        log(
            tr(
                f"{a.within} has no sub-folders to rank; --by-folder compares its sub-folders",
                f"{a.within} 没有可以排名的子文件夹；--by-folder 比的是子文件夹",
            )
        )
        return 1
    results = rank_folders(qstyle, atlas.style, folders, top=a.top, combine=a.combine, exclude=same)
    rows = [
        {
            "query": names[qi],
            "rank": r + 1,
            "folder": h.folder,
            "score": round(h.score, 4),
            "images": h.size,
            "closest": atlas.rel(h.best),
        }
        for qi, hits in enumerate(results)
        for r, h in enumerate(hits)
    ]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    _print_by_query(
        rows,
        lambda r: (
            f"{r['rank']:3d}  {r['score']:.3f}  {r['folder']}"
            + tr(
                f" ({r['images']} images, closest {r['closest']})",
                f"（{r['images']} 张，最像的是 {r['closest']}）",
            )
        ),
    )
    log(
        tr(
            "score: similarity between the query and each folder's average style, in the search "
            "space, where numbers run small (0 or below: no closer than an average folder); what "
            "tells is how far the first folder leads the second:",
            "分数：查找图和每个文件夹平均画风的相似度（在搜索空间里算，数值偏小是正常的；"
            "0 或以下表示不比一般的文件夹像）。要看的是第一名领先第二名多少：",
        )
    )
    for qi, hits in enumerate(results):
        verdict = folder_verdict(hits, several=bool(a.combine) and len(qstyle) > 1)
        if verdict:
            prefix = "" if a.combine or len(results) == 1 else f"{names[qi]}: "
            log(prefix + _folder_verdict_text(hits[0].folder, *verdict))
    log(
        tr(
            "these rates hold when the artist is one of these folders; the ranking compares "
            "with the works now in each folder, and an artist's much earlier or later works can "
            "look more like someone else's"
            + (
                ""
                if a.combine
                else "; several works of one artist together (--combine) are "
                "surer (92% against 69% right first in the measurement)"
            ),
            "这些比例的前提是画师本来就在这些文件夹里；排名比的是各文件夹里现有作品的画风，"
            "同一位画师很早期或很后期的作品，可能反而比较像别人"
            + (
                ""
                if a.combine
                else "；同一位画师的几张一起查（--combine）会准很多"
                "（实测第一名对了 92%，一张只有 69%）"
            ),
        )
    )
    return 0


def _folder_verdict_text(folder: str, band: str, right: int, lead: float) -> str:
    if band == "sure":
        return tr(
            f"the first leads by {lead:.2f}: very likely {folder} (with a lead this large the "
            f"first was right {right}% of the time)",
            f"第一名领先 {lead:.2f}：很可能就是 {folder}（实测领先这么多时，第一名对了 {right}%）",
        )
    if band == "likely":
        return tr(
            f"the first leads by only {lead:.2f}: perhaps {folder}, not sure (right {right}% of "
            "the time at such a lead)",
            f"第一名只领先 {lead:.2f}：可能是 {folder}，但不确定（实测这种差距下对了 {right}%）",
        )
    return tr(
        f"the first two are only {lead:.2f} apart: no clear answer (the first was right {right}% "
        "of the time at such a small lead); look at the top few folders' closest images",
        f"前两名只差 {lead:.2f}：分不太出来（实测差距这么小时，第一名只对了 {right}%）；"
        "请看前几名最像的图自己判断",
    )


SEARCH_ORDER_EN = (
    "ranked by style match in the search space (whitened, corrected for images that are close to "
    "everything); the number shown is the plain cosine, so it is not always in order"
)
SEARCH_ORDER_ZH = (
    "名次按画风相似度排（在搜索空间里，并修正了“和什么都像”的图）；旁边的数字是一般的相似度，"
    "所以不一定按大小排"
)


ALL_QUERIES = "(all queries)"  # the "query" of a combined search, in JSON in every language


def _print_by_query(rows: list[dict], line: Callable[[dict], str]) -> None:
    """Each query's name once, then its results."""
    query = None
    for row in rows:
        if row["query"] != query:
            query = row["query"]
            print(
                tr(f"{ALL_QUERIES}:", "（全部查找图合在一起）：")
                if query == ALL_QUERIES
                else f"{query}:"
            )
        print(line(row))


def _search_folded(a: argparse.Namespace, atlas, qstyle, plain: np.ndarray, same: set) -> list:
    """Each query's hits without near-copies of a better hit, looking further down the ranking
    until every query has --top hits or the folder runs out. The search ranks every image once;
    only the folding is repeated, on longer slices of that ranking."""
    from styleatlas.search import fold_hits, search

    ranked = search(qstyle, atlas.style, top=len(atlas), combine=a.combine, exclude=same)
    wide = 2 * a.top
    while True:
        folded = [fold_hits(hits[:wide], plain, atlas.content, a.top) for hits in ranked]
        if all(len(kept) >= a.top for kept, _ in folded) or wide >= len(atlas):
            break
        wide = min(2 * wide, len(atlas))
    n = sum(left for _, left in folded)
    if n:
        total = tr(" (all queries together)", "（所有查找图合计）") if len(folded) > 1 else ""
        log(
            tr(
                f"{n} near-copies of a higher match left out{total}; they take no place in the "
                "list (--keep-duplicates lists them)",
                f"另外略过 {n} 张和名次更前面的图几乎一样的图{total}，不占名额"
                "（加 --keep-duplicates 会列出）",
            )
        )
    return [kept for kept, _ in folded]


def _copy_matches(atlas, indices: list[int], dest: Path) -> None:
    from styleatlas.export import copy_ranked

    unique = list(dict.fromkeys(indices))  # several queries may find the same image
    done = copy_ranked(atlas.subset(unique), dest)
    log(
        tr(
            f"copied {done.placed} matches to {done.folder} (file names start with the rank: "
            "01_ is the closest)",
            f"已复制 {done.placed} 张结果到 {done.folder}（文件名开头是名次：01_ 最像）",
        )
    )
    for p, why in done.failed:
        log(tr(f"not copied {p}: {why}", f"没有复制 {p}：{why}"))


def _positive_float(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError("must be above 0")
    return value


def cmd_calibrate(a: argparse.Namespace) -> int:
    root = Path(a.folder)
    paths = find_images(root)
    kept, style, _, _ = embed_paths(paths, _opts(a), log)
    labels = np.array(labels_from_folders(kept, root))
    floors, sizes = {}, {}
    for lbl in sorted(set(labels.tolist()) - {""}):
        idx = np.flatnonzero(labels == lbl)
        if len(idx) >= 4:
            floors[lbl] = round(split_half_noise(style[idx]), 4)
            sizes[lbl] = len(idx)
    if not floors:
        log(
            tr(
                "need sub-folders with >= 4 images of one style each",
                "需要子文件夹，每个至少 4 张同一画风的图",
            )
        )
        return 1
    floor = round(float(np.median(list(floors.values()))), 4)
    if a.json:
        print(json.dumps({"per_group": floors, "noise_floor": floor}, indent=1))
        return 0
    print(
        tr(
            "each sub-folder's noise: the distance between two random halves of it",
            "每个子文件夹的噪声：随机分成两半之后，两半之间的距离",
        )
    )
    for lbl, value in floors.items():
        print(
            f"  {pad(lbl, 30)}{value:.4f}  " + tr(f"({sizes[lbl]} images)", f"（{sizes[lbl]} 张）")
        )
    print(
        tr(
            f"median {floor:.4f}: pass it to compare as --noise-floor {floor}",
            f"中位数 {floor:.4f}：compare 时加上 --noise-floor {floor}",
        ),
        flush=True,  # before the note below, also when the output is piped
    )
    log(
        tr(
            "each sub-folder must hold one style (mixed periods make the number too large); "
            "--noise-floor makes compare use the z scale, also with 5 or more images a side, "
            "where it would otherwise place the distance among pairs of real artists",
            "每个子文件夹都要是同一种画风（混了不同时期，数字会偏大）；加了 --noise-floor，"
            "compare 就改用 z 值，每边 5 张以上时也一样（不加的话会和真实画师的配对比）",
        )
    )
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    from styleatlas.bench import run_bench

    if not a.npz and not a.folder:
        log(
            tr(
                "give a folder whose sub-folders are the labels, or --npz",
                "请给一个以子文件夹当标签的文件夹，或用 --npz",
            )
        )
        return 1
    content = None
    if a.npz:
        with np.load(a.npz) as z:
            keys = list(z.files)
            style = np.stack([z[k] for k in keys]).astype(np.float32)
        style = unit(style)
        labels = [k.rsplit(a.sep, 1)[0] for k in keys]
    else:
        root = Path(a.folder)
        kept, style, content, _ = embed_paths(find_images(root), _opts(a), log)
        if a.labels == "prefix":
            labels = [p.stem.rsplit(a.sep, 1)[0] for p in kept]
        else:
            labels = labels_from_folders(kept, root)
    dedupe = None if a.keep_duplicates else a.dup_threshold
    report = run_bench(style, labels, trials=a.trials, content=content, dedupe=dedupe)
    print(json.dumps(report, indent=1))
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    from styleatlas.cachedir import cache_dir
    from styleatlas.demo import ensure_demo

    folder = Path(a.folder) if a.folder else cache_dir() / "demo_styles"
    made = ensure_demo(folder)
    if made:
        log(tr(f"made {made} demo images in {folder}", f"已在 {folder} 生成 {made} 张示范图"))
    a.folder = str(folder)
    return cmd_serve(a)


def cmd_serve(a: argparse.Namespace) -> int:
    from styleatlas.webserver import serve_when_ready

    build, title = serve_build(a)
    ok = serve_when_ready(build, title, port=a.port, open_browser=not a.no_browser)
    return 0 if ok else 1


def serve_build(a: argparse.Namespace):
    """`serve`'s app builder, run in the background while the page shows its progress (also
    the desktop program's), and the folder's title."""
    from styleatlas.serve import StyleAtlasApp

    space = _space(a)
    a.neutralize, a.ignore_characters = 0, False  # the app applies the space itself
    opts = _opts(a)

    def build(progress) -> StyleAtlasApp:  # in the background, while the page shows progress
        return StyleAtlasApp(
            _atlas(a, a.folder, progress=progress),
            opts,
            a.projection,
            a.title,
            progress=progress,
            time_source=a.time,
            space=space,
            reference=_reference(a, progress),
        )

    return build, a.title or Path(a.folder).resolve().name


def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group(tr("embedding", "画风向量"))
    g.add_argument(
        "--device",
        default="auto",
        help=tr("auto, cpu or cuda (default auto)", "auto、cpu 或 cuda（默认 auto）"),
    )
    g.add_argument(
        "--crop",
        default="center",
        choices=CROP_MODES,
        help=tr(
            "center: the middle square; tiles: squares along the long side, averaged",
            "center：取中间的正方形；tiles：沿长边取几块正方形再平均",
        ),
    )
    g.add_argument(
        "--resolution",
        type=int,
        default=224,
        choices=RESOLUTIONS,
        help=tr(
            "model input size; 336 sees finer detail, slower",
            "模型输入大小；336 看得到较细的细节，较慢",
        ),
    )
    g.add_argument(
        "--batch",
        type=int,
        default=8,
        help=tr("images per model batch", "每批送进模型的张数"),
    )
    g.add_argument(
        "--threads",
        type=int,
        default=8,
        help=tr("CPU threads cap (0 = all)", "CPU 线程上限（0 = 不限）"),
    )
    g.add_argument(
        "--cache-db",
        help=tr(
            "vector cache file (default: vectors.sqlite in the cache folder, which "
            "`style-atlas doctor` shows)",
            "画风向量缓存文件（默认：缓存文件夹里的 vectors.sqlite；"
            "`style-atlas doctor` 会显示位置）",
        ),
    )
    g.add_argument(
        "--no-recursive",
        action="store_true",
        help=tr("do not look into sub-folders", "不找子文件夹里的图"),
    )


def _cluster_args(p: argparse.ArgumentParser) -> None:
    g = _grouping_args(p)
    g.add_argument(
        "--projection",
        default="auto",
        choices=PROJECTIONS,
        help=tr(
            "how the 3D map is laid out (auto picks umap or t-SNE)",
            "3D 地图的排版方式（auto 会自动选 umap 或 t-SNE）",
        ),
    )
    g.add_argument(
        "--time",
        default="none",
        choices=TIME_SOURCES,
        help=tr(
            "show when each style was made: name = id or date in the file name (Pixiv, Danbooru, "
            "tweet ids; 2023-05-12), or mtime",
            "显示各画风是什么时候画的：name = 文件名里的编号或日期"
            "（Pixiv、Danbooru、推文编号；2023-05-12），或 mtime",
        ),
    )
    _space_args(g)
    g.add_argument("--reference", metavar="DIR", help=reference_help())
    g.add_argument(
        "--thumb",
        type=int,
        help=tr(
            "thumbnail px in the map (default 128, 72 above 2k)",
            "地图里的缩略图像素（默认 128，超过 2k 张为 72）",
        ),
    )


def _grouping_args(p: argparse.ArgumentParser) -> argparse._ArgumentGroup:
    g = p.add_argument_group(tr("clustering", "分组"))
    g.add_argument(
        "--granularity",
        default="auto",
        choices=["auto", "period", TIMELINE, ARTISTS, *GRANULARITY],
        help=tr(
            "auto picks the cut from the data; period splits one artist into --k periods "
            f"(default {PERIODS}, k-means, every image assigned); timeline cuts one artist's works "
            "into --k contiguous periods where the style changes most and tests the cuts (needs "
            "--time); artists groups a gallery of many artists (20 or more) by artist",
            "auto 按图片自动挑切分距离；period 把同一位画师分成 --k 个时期"
            f"（默认 {PERIODS}，k-means，每张图都会分进一段）；"
            "timeline 按时间顺序，在画风变化最大处切成 --k 个连续时期，并检验切点是否明显"
            "（需要 --time）；artists 按画师分组，"
            "给有很多位画师（20 位以上）的图库用",
        ),
    )
    g.add_argument(
        "--threshold",
        type=float,
        help=tr(
            "distance cut, after hub correction (overrides --granularity)",
            "切分距离，去 hub 校正后（会盖过 --granularity）",
        ),
    )
    g.add_argument(
        "--k",
        type=int,
        help=tr(
            "force this many styles (with period: periods)",
            "指定分成几组（搭配 period 时是几个时期）",
        ),
    )
    g.add_argument(
        "--method",
        default="agglomerative",
        choices=METHODS,
        help=tr(
            "grouping algorithm (agglomerative measured best)",
            "分组算法（agglomerative 量起来最好）",
        ),
    )
    g.add_argument(
        "--min-size",
        type=int,
        default=3,
        help=tr("smaller groups become 'unassigned'", "比这个小的组归入“未归类”"),
    )
    return g


Adder = Callable[..., argparse.ArgumentParser]


def _add_folder_commands(add: Adder) -> None:
    add(
        "embed", cmd_embed, tr("embed and cache a folder", "算出文件夹的画风向量并存进缓存")
    ).add_argument("folder")
    p = add(
        "cluster",
        cmd_cluster,
        tr(
            "group a folder by style; write CSV/JSON, map, optional folders",
            "把文件夹按画风分组；写出 CSV/JSON、地图，也可导出成文件夹",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "output folder (default: <folder>_style_atlas)",
            "输出文件夹（默认：<文件夹>_style_atlas）",
        ),
    )
    p.add_argument("--no-map", action="store_true", help=tr("skip the HTML map", "不写 HTML 地图"))
    _lora_args(p)
    _cluster_args(p)
    p = add(
        "report",
        cmd_report,
        tr(
            "one HTML page that sums up a folder's style (to keep or send)",
            "一页 HTML 报告，整理文件夹的画风（可留存或传给别人）",
        ),
    )
    report_args(p)
    _cluster_args(p)
    p = add(
        "sort",
        cmd_sort,
        tr(
            "place new images into the style groups of a sorted dataset",
            "把新图分进已经分好画风组的数据集",
        ),
    )
    sort_args(p)
    _grouping_args(p)
    p = add(
        "map",
        cmd_map,
        tr(
            "write the interactive 3D style map (one HTML file)",
            "写出可交互的 3D 画风地图（单个 HTML 文件）",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "HTML file (default: <folder>_style_atlas/style_atlas_map.html)",
            "HTML 文件（默认：<文件夹>_style_atlas/style_atlas_map.html）",
        ),
    )
    p.add_argument(
        "--title", help=tr("page title (default: the folder name)", "页面标题（默认：文件夹名称）")
    )
    p.add_argument(
        "--pictures",
        type=int,
        choices=[0, 320, 512],
        default=0,
        help=tr(
            "also put each picture in the file at this size, for sharp close-ups and the viewer "
            "on another computer (0: thumbnails only, the smallest file)",
            "每张图另外以这个大小放进文件，在别的电脑上拉近和看大图也清楚（0：只有缩略图，文件最小）",
        ),
    )
    p.add_argument(
        "--by-folder",
        action="store_true",
        help=tr(
            "one point per sub-folder (e.g. per artist) at its mean style, grouped into families",
            "每个子文件夹（例如每位画师）一个点，位置是它的平均画风，并分成几个家族",
        ),
    )
    _cluster_args(p)
    p = add(
        "serve",
        cmd_serve,
        tr(
            "open the interactive map in the browser with live search",
            "在浏览器打开可交互的地图，可实时搜索",
        ),
    )
    p.add_argument("folder")
    _serve_args(p)
    p = add(
        "demo",
        cmd_demo,
        tr(
            "make 72 demo images in four procedural styles (no one's artwork) and open them in "
            "the web app",
            "生成 72 张四种程序画出的示范图（不是任何人的作品），并在网页界面打开",
        ),
    )
    p.add_argument(
        "folder",
        nargs="?",
        help=tr(
            "where to put the demo images (default: demo_styles in the cache folder)",
            "示范图放在哪里（默认：缓存文件夹里的 demo_styles）",
        ),
    )
    _serve_args(p)


def _serve_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--port",
        type=int,
        default=8770,
        help=tr("local port of the web app", "网页界面用的本机连接端口"),
    )
    p.add_argument(
        "--title", help=tr("page title (default: the folder name)", "页面标题（默认：文件夹名称）")
    )
    p.add_argument(
        "--projection",
        default="auto",
        choices=PROJECTIONS,
        help=tr(
            "how the 3D map is laid out (auto picks umap or t-SNE)",
            "3D 地图的排版方式（auto 会自动选 umap 或 t-SNE）",
        ),
    )
    p.add_argument(
        "--time",
        default="none",
        choices=TIME_SOURCES,
        help=tr(
            "show when each style was made: name = id or date in the file name (Pixiv, Danbooru, "
            "tweet ids; 2023-05-12), or mtime",
            "显示各画风是什么时候画的：name = 文件名里的编号或日期"
            "（Pixiv、Danbooru、推文编号；2023-05-12），或 mtime",
        ),
    )
    _space_args(p)
    p.add_argument("--reference", metavar="DIR", help=reference_help())
    p.add_argument(
        "--no-browser",
        action="store_true",
        help=tr("do not open a browser tab", "不要自动开浏览器"),
    )


def _space_args(p) -> None:
    x = p.add_mutually_exclusive_group()
    x.add_argument("--ignore-characters", action="store_true", help=characters_help())
    x.add_argument(
        "--neutralize", type=_neutralize_count, default=0, metavar="N", help=neutralize_help()
    )


def _add_inspect_commands(add: Adder) -> None:
    p = add(
        "search",
        cmd_search,
        tr(
            "find images in a folder whose style is closest to the query",
            "在文件夹里找画风最接近范例的图",
        ),
    )
    p.add_argument(
        "query", nargs="+", help=tr("query image(s) or folder(s)", "范例图或文件夹（可多个）")
    )
    p.add_argument(
        "--in",
        dest="within",
        required=True,
        help=tr("folder to search", "要搜索的文件夹"),
    )
    p.add_argument(
        "--top",
        type=_positive_int,
        default=20,
        help=tr("results per query", "每张查找图列出几个结果"),
    )
    p.add_argument(
        "--combine",
        action="store_true",
        help=tr(
            "treat all queries as one style (their average style; from 10 images up, a model "
            "learned from them)",
            "把所有范例当成同一种画风（用它们的平均画风；10 张以上时，改用它们训练的小模型）",
        ),
    )
    p.add_argument(
        "--copy-to",
        metavar="DIR",
        help=tr(
            "copy the matches (with captions) into this new folder, named by rank (01_ first)",
            "把找到的图（连同标注文件）复制到这个新文件夹，文件名开头是名次（01_ 最像）",
        ),
    )
    p.add_argument(
        "--by-folder",
        action="store_true",
        help=tr(
            "rank the sub-folders of --in (e.g. one per artist) instead of single images",
            "改为排序 --in 的子文件夹（例如每位画师一个），而不是单张图",
        ),
    )
    p.add_argument(
        "--keep-duplicates",
        action="store_true",
        help=tr(
            "also list near-copies of a better match (left out by default)",
            "也列出和更好结果几乎一样的图（默认略过）",
        ),
    )
    _space_args(p)
    p.add_argument(
        "--json", action="store_true", help=tr("print JSON instead of text", "改用 JSON 输出")
    )
    p = add(
        "outliers",
        cmd_outliers,
        tr("images least like the rest of a folder", "文件夹里最不合群的图"),
    )
    p.add_argument("folder")
    p.add_argument("--top", type=_positive_int, default=30, help=tr("how many to list", "列出几张"))
    p = add(
        "audit",
        cmd_audit,
        tr(
            "check a training folder: sizes, aspect ratios, captions",
            "检查训练文件夹：尺寸、长宽比、标注",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "--min-side",
        type=int,
        default=512,
        help=tr("training resolution to check against", "用来对照的训练分辨率"),
    )
    p.add_argument(
        "--max-ratio",
        type=float,
        default=2.5,
        help=tr(
            "long side / short side above which an image is extreme", "长边/短边超过多少算极端"
        ),
    )
    p.add_argument(
        "--show",
        type=int,
        default=10,
        help=tr("files to list per problem", "每种问题列出几个文件"),
    )
    p.add_argument(
        "--json", action="store_true", help=tr("print JSON instead of text", "改用 JSON 输出")
    )
    p = add(
        "duplicates",
        cmd_duplicates,
        tr(
            "near-duplicate groups (same picture, crops, frames)",
            "近重复图的分组（同一张图、裁切、帧）",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help=tr(
            "min(style, content) cosine; 0.92 is looser",
            "min(画风, 内容) 的余弦相似度；0.92 较宽松",
        ),
    )
    p.add_argument(
        "--json", action="store_true", help=tr("print JSON instead of text", "改用 JSON 输出")
    )


def _add_measure_commands(add: Adder) -> None:
    p = add(
        "compare",
        cmd_compare,
        tr(
            "do two folders differ in style? distance, z units, p-value",
            "两个文件夹的画风不同吗？输出距离、z 值、p 值",
        ),
    )
    p.add_argument("a", help=tr("first folder (A)", "第一个文件夹（A）"))
    p.add_argument("b", help=tr("second folder (B)", "第二个文件夹（B）"))
    p.add_argument(
        "--rounds",
        type=int,
        default=999,
        help=tr("random shuffles for the p-value", "算 p 值用的随机重排次数"),
    )
    p.add_argument(
        "--noise-floor",
        type=_positive_float,
        help=tr("from `calibrate` (default 0.071)", "取自 `calibrate`（默认 0.071）"),
    )
    p.add_argument(
        "--json", action="store_true", help=tr("every number, as JSON", "所有数字，用 JSON 输出")
    )
    p = add(
        "calibrate",
        cmd_calibrate,
        tr(
            "estimate the noise floor from one-style sub-folders",
            "用每个只有一种画风的子文件夹估计噪声下划线",
        ),
    )
    p.add_argument("folder")
    p.add_argument("--json", action="store_true", help=tr("print JSON", "输出 JSON 格式"))
    p = add(
        "bench",
        cmd_bench,
        tr(
            "score retrieval and clustering against sub-folder labels",
            "用子文件夹当标签，给搜索和分组打分",
        ),
    )
    p.add_argument("folder", nargs="?")
    p.add_argument(
        "--npz",
        help=tr(
            "precomputed vectors; label = key prefix before --sep",
            "算好的画风向量；标签 = --sep 之前的键名前缀",
        ),
    )
    p.add_argument(
        "--labels",
        choices=["folder", "prefix"],
        default="folder",
        help=tr(
            "labels from sub-folders or from file-name prefixes", "标签取自子文件夹或文件名前缀"
        ),
    )
    p.add_argument(
        "--sep", default="__", help=tr("file-name prefix separator", "文件名前缀的分隔符号")
    )
    p.add_argument(
        "--keep-duplicates",
        action="store_true",
        help=tr("score duplicates too", "近重复图也一起计分"),
    )
    p.add_argument("--dup-threshold", type=float, default=0.92)
    p.add_argument("--trials", type=int, default=30)
    p = add(
        "taste",
        cmd_taste,
        tr(
            "train or apply a personal like/dislike model",
            "训练或套用个人的喜欢/不喜欢偏好模型",
        ),
        common=False,
    )
    taste_args(p, _common, HelpFormatter)


def cmd_doctor(a: argparse.Namespace) -> int:
    from styleatlas.doctor import run

    return run()


class HelpFormatter(argparse.HelpFormatter):
    """Wraps help by display width, so Chinese help lines fit the terminal."""

    def _split_lines(self, text: str, width: int) -> list[str]:
        if all(columns(ch) == 1 for ch in text):
            return super()._split_lines(text, width)  # English: argparse's own wrapping
        return wrap(text, width)

    def _fill_text(self, text: str, width: int, indent: str) -> str:  # line by line
        return "\n".join(self._fill_line(line, width, indent) for line in text.splitlines())

    def _fill_line(self, line: str, width: int, indent: str) -> str:
        if all(columns(ch) == 1 for ch in line):
            return super()._fill_text(line, width, indent) if line.strip() else ""
        return "\n".join(indent + part for part in wrap(line, width - len(indent)))


def START_HERE() -> str:  # noqa: N802 - text, built when the language is known
    return tr(
        "where to start:\n"
        "try it: demo\n"
        "your own folder: serve (or drag the folder onto scripts\\StyleAtlas.bat)\n"
        "a LoRA dataset: audit, then cluster (--export), then sort for new images; "
        "duplicates, outliers\n"
        "images in a similar style: search (or the image search in serve)\n"
        "compare and share: compare, report, map\n"
        "research: embed, calibrate, bench, taste\n"
        "setup problems: doctor",
        "从哪里开始：\n"
        "试玩：demo\n"
        "打开自己的文件夹：serve（或把文件夹拖到 scripts\\StyleAtlas.bat 上）\n"
        "整理 LoRA 数据集：audit，再 cluster（加 --export），之后的新图用 sort；"
        "另有 duplicates、outliers\n"
        "找画风相近的图：search（或 serve 网页里的以图搜索）\n"
        "比较和分享：compare、report、map\n"
        "研究用：embed、calibrate、bench、taste\n"
        "安装有问题：doctor",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="style-atlas",
        description=tr(
            "style-atlas <command> ...  (each command's options: style-atlas <command> -h)",
            "style-atlas <指令> ...（各指令的选项：style-atlas <指令> -h）",
        ),
        epilog=START_HERE(),
        formatter_class=HelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"style-atlas {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, help_: str, common: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_, formatter_class=HelpFormatter)
        p.set_defaults(fn=fn)
        if common:
            _common(p)
        return p

    add(
        "doctor",
        cmd_doctor,
        tr(
            "check Python, torch, GPU, model download and disk space",
            "检查 Python、torch、GPU、模型下载和磁盘空间",
        ),
        common=False,
    )
    _add_folder_commands(add)
    _add_inspect_commands(add)
    _add_measure_commands(add)
    return ap


def main(argv: list[str] | None = None) -> int:
    from styleatlas.encoder import ModelDownloadError

    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError, ModelDownloadError) as e:
        log(tr("error: ", "错误：") + str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
