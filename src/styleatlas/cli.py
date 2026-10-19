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
    log(tr(f"{n} images embedded, {skipped} skipped", f"{n} 張已算好向量，{skipped} 張略過"))
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
                    f"{a.folder} 只有 {len(atlas)} 個子資料夾；--by-folder 至少要 3 個",
                )
            )
            return 1
        log(
            tr(
                f"{len(atlas)} sub-folders, each shown by its most typical image",
                f"{len(atlas)} 個子資料夾，每個用最有代表性的一張圖顯示",
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
                f"{len(atlas)} 張圖：HTML 檔會很大；用 `style-atlas serve` 開會比較快",
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
            "用瀏覽器開啟（雙擊檔案）；在頁面上按 ? 看說明",
        )
    )
    mb = path.stat().st_size / 1e6
    log(
        tr(
            f"file size {mb:.1f} MB (the thumbnails are inside)",
            f"檔案大小 {mb:.1f} MB（縮圖都在檔案裡）",
        )
    )
    if mb > LARGE_SHARE_MB:
        log(
            tr(
                f"over {LARGE_SHARE_MB} MB: some chat apps refuse it (Discord's free limit is "
                "10 MB); --thumb 64 makes it smaller",
                f"超過 {LARGE_SHARE_MB} MB：有些聊天軟體傳不了（Discord 免費帳號上限 10 MB）；"
                "加 --thumb 64 可以變小",
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
        log(tr(f"query skipped {p}: {why}", f"略過查詢圖 {p}：{why}"))
    if not qkept:
        log(tr("no readable query images", "查詢的圖都讀不了"))
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
                "--copy-to 只複製單張圖，和 --by-folder 一起用時不會作用",
            )
        )
    folders = labels_from_folders(atlas.paths, atlas.root)
    if len(set(folders) - {""}) < 2:
        log(
            tr(
                f"{a.within} has no sub-folders to rank; --by-folder compares its sub-folders",
                f"{a.within} 沒有可以排名的子資料夾；--by-folder 比的是子資料夾",
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
                f"（{r['images']} 張，最像的是 {r['closest']}）",
            )
        ),
    )
    log(
        tr(
            "score: similarity between the query and each folder's average style, in the search "
            "space, where numbers run small (0 or below: no closer than an average folder); what "
            "tells is how far the first folder leads the second:",
            "分數：查詢圖和每個資料夾平均畫風的相似度（在搜尋空間裡算，數值偏小是正常的；"
            "0 或以下表示不比一般的資料夾像）。要看的是第一名領先第二名多少：",
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
            "這些比例的前提是畫師本來就在這些資料夾裡；排名比的是各資料夾裡現有作品的畫風，"
            "同一位畫師很早期或很後期的作品，可能反而比較像別人"
            + (
                ""
                if a.combine
                else "；同一位畫師的幾張一起查（--combine）會準很多"
                "（實測第一名對了 92%，一張只有 69%）"
            ),
        )
    )
    return 0


def _folder_verdict_text(folder: str, band: str, right: int, lead: float) -> str:
    if band == "sure":
        return tr(
            f"the first leads by {lead:.2f}: very likely {folder} (with a lead this large the "
            f"first was right {right}% of the time)",
            f"第一名領先 {lead:.2f}：很可能就是 {folder}（實測領先這麼多時，第一名對了 {right}%）",
        )
    if band == "likely":
        return tr(
            f"the first leads by only {lead:.2f}: perhaps {folder}, not sure (right {right}% of "
            "the time at such a lead)",
            f"第一名只領先 {lead:.2f}：可能是 {folder}，但不確定（實測這種差距下對了 {right}%）",
        )
    return tr(
        f"the first two are only {lead:.2f} apart: no clear answer (the first was right {right}% "
        "of the time at such a small lead); look at the top few folders' closest images",
        f"前兩名只差 {lead:.2f}：分不太出來（實測差距這麼小時，第一名只對了 {right}%）；"
        "請看前幾名最像的圖自己判斷",
    )


SEARCH_ORDER_EN = (
    "ranked by style match in the search space (whitened, corrected for images that are close to "
    "everything); the number shown is the plain cosine, so it is not always in order"
)
SEARCH_ORDER_ZH = (
    "名次依畫風相似度排（在搜尋空間裡，並修正了「和什麼都像」的圖）；旁邊的數字是一般的相似度，"
    "所以不一定照大小排"
)


ALL_QUERIES = "(all queries)"  # the "query" of a combined search, in JSON in every language


def _print_by_query(rows: list[dict], line: Callable[[dict], str]) -> None:
    """Each query's name once, then its results."""
    query = None
    for row in rows:
        if row["query"] != query:
            query = row["query"]
            print(
                tr(f"{ALL_QUERIES}:", "（全部查詢圖合在一起）：")
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
        total = tr(" (all queries together)", "（所有查詢圖合計）") if len(folded) > 1 else ""
        log(
            tr(
                f"{n} near-copies of a higher match left out{total}; they take no place in the "
                "list (--keep-duplicates lists them)",
                f"另外略過 {n} 張和名次更前面的圖幾乎一樣的圖{total}，不佔名額"
                "（加 --keep-duplicates 會列出）",
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
            f"已複製 {done.placed} 張結果到 {done.folder}（檔名開頭是名次：01_ 最像）",
        )
    )
    for p, why in done.failed:
        log(tr(f"not copied {p}: {why}", f"沒有複製 {p}：{why}"))


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
                "需要子資料夾，每個至少 4 張同一畫風的圖",
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
            "每個子資料夾的雜訊：隨機分成兩半之後，兩半之間的距離",
        )
    )
    for lbl, value in floors.items():
        print(
            f"  {pad(lbl, 30)}{value:.4f}  " + tr(f"({sizes[lbl]} images)", f"（{sizes[lbl]} 張）")
        )
    print(
        tr(
            f"median {floor:.4f}: pass it to compare as --noise-floor {floor}",
            f"中位數 {floor:.4f}：compare 時加上 --noise-floor {floor}",
        ),
        flush=True,  # before the note below, also when the output is piped
    )
    log(
        tr(
            "each sub-folder must hold one style (mixed periods make the number too large); "
            "--noise-floor makes compare use the z scale, also with 5 or more images a side, "
            "where it would otherwise place the distance among pairs of real artists",
            "每個子資料夾都要是同一種畫風（混了不同時期，數字會偏大）；加了 --noise-floor，"
            "compare 就改用 z 值，每邊 5 張以上時也一樣（不加的話會和真實畫師的配對比）",
        )
    )
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    from styleatlas.bench import run_bench

    if not a.npz and not a.folder:
        log(
            tr(
                "give a folder whose sub-folders are the labels, or --npz",
                "請給一個以子資料夾當標籤的資料夾，或用 --npz",
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
        log(tr(f"made {made} demo images in {folder}", f"已在 {folder} 產生 {made} 張示範圖"))
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
    g = p.add_argument_group(tr("embedding", "畫風向量"))
    g.add_argument(
        "--device",
        default="auto",
        help=tr("auto, cpu or cuda (default auto)", "auto、cpu 或 cuda（預設 auto）"),
    )
    g.add_argument(
        "--crop",
        default="center",
        choices=CROP_MODES,
        help=tr(
            "center: the middle square; tiles: squares along the long side, averaged",
            "center：取中間的正方形；tiles：沿長邊取幾塊正方形再平均",
        ),
    )
    g.add_argument(
        "--resolution",
        type=int,
        default=224,
        choices=RESOLUTIONS,
        help=tr(
            "model input size; 336 sees finer detail, slower",
            "模型輸入大小；336 看得到較細的細節，較慢",
        ),
    )
    g.add_argument(
        "--batch",
        type=int,
        default=8,
        help=tr("images per model batch", "每批送進模型的張數"),
    )
    g.add_argument(
        "--threads",
        type=int,
        default=8,
        help=tr("CPU threads cap (0 = all)", "CPU 執行緒上限（0 = 不限）"),
    )
    g.add_argument(
        "--cache-db",
        help=tr(
            "vector cache file (default: vectors.sqlite in the cache folder, which "
            "`style-atlas doctor` shows)",
            "畫風向量快取檔（預設：快取資料夾裡的 vectors.sqlite；"
            "`style-atlas doctor` 會顯示位置）",
        ),
    )
    g.add_argument(
        "--no-recursive",
        action="store_true",
        help=tr("do not look into sub-folders", "不找子資料夾裡的圖"),
    )


def _cluster_args(p: argparse.ArgumentParser) -> None:
    g = _grouping_args(p)
    g.add_argument(
        "--projection",
        default="auto",
        choices=PROJECTIONS,
        help=tr(
            "how the 3D map is laid out (auto picks umap or t-SNE)",
            "3D 地圖的排版方式（auto 會自動選 umap 或 t-SNE）",
        ),
    )
    g.add_argument(
        "--time",
        default="none",
        choices=TIME_SOURCES,
        help=tr(
            "show when each style was made: name = id or date in the file name (Pixiv, Danbooru, "
            "tweet ids; 2023-05-12), or mtime",
            "顯示各畫風是什麼時候畫的：name = 檔名裡的編號或日期"
            "（Pixiv、Danbooru、推文編號；2023-05-12），或 mtime",
        ),
    )
    _space_args(g)
    g.add_argument("--reference", metavar="DIR", help=reference_help())
    g.add_argument(
        "--thumb",
        type=int,
        help=tr(
            "thumbnail px in the map (default 128, 72 above 2k)",
            "地圖裡的縮圖像素（預設 128，超過 2k 張為 72）",
        ),
    )


def _grouping_args(p: argparse.ArgumentParser) -> argparse._ArgumentGroup:
    g = p.add_argument_group(tr("clustering", "分群"))
    g.add_argument(
        "--granularity",
        default="auto",
        choices=["auto", "period", TIMELINE, ARTISTS, *GRANULARITY],
        help=tr(
            "auto picks the cut from the data; period splits one artist into --k periods "
            f"(default {PERIODS}, k-means, every image assigned); timeline cuts one artist's works "
            "into --k contiguous periods where the style changes most and tests the cuts (needs "
            "--time); artists groups a gallery of many artists (20 or more) by artist",
            "auto 依圖片自動挑切分距離；period 把同一位畫師分成 --k 個時期"
            f"（預設 {PERIODS}，k-means，每張圖都會分進一段）；"
            "timeline 依時間順序，在畫風變化最大處切成 --k 個連續時期，並檢驗切點是否明顯"
            "（需要 --time）；artists 依畫師分群，"
            "給有很多位畫師（20 位以上）的圖庫用",
        ),
    )
    g.add_argument(
        "--threshold",
        type=float,
        help=tr(
            "distance cut, after hub correction (overrides --granularity)",
            "切分距離，去 hub 校正後（會蓋過 --granularity）",
        ),
    )
    g.add_argument(
        "--k",
        type=int,
        help=tr(
            "force this many styles (with period: periods)",
            "指定分成幾群（搭配 period 時是幾個時期）",
        ),
    )
    g.add_argument(
        "--method",
        default="agglomerative",
        choices=METHODS,
        help=tr(
            "grouping algorithm (agglomerative measured best)",
            "分群演算法（agglomerative 量起來最好）",
        ),
    )
    g.add_argument(
        "--min-size",
        type=int,
        default=3,
        help=tr("smaller groups become 'unassigned'", "比這個小的群歸入「未歸類」"),
    )
    return g


Adder = Callable[..., argparse.ArgumentParser]


def _add_folder_commands(add: Adder) -> None:
    add(
        "embed", cmd_embed, tr("embed and cache a folder", "算出資料夾的畫風向量並存進快取")
    ).add_argument("folder")
    p = add(
        "cluster",
        cmd_cluster,
        tr(
            "group a folder by style; write CSV/JSON, map, optional folders",
            "把資料夾依畫風分群；寫出 CSV/JSON、地圖，也可匯出成資料夾",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "output folder (default: <folder>_style_atlas)",
            "輸出資料夾（預設：<資料夾>_style_atlas）",
        ),
    )
    p.add_argument("--no-map", action="store_true", help=tr("skip the HTML map", "不寫 HTML 地圖"))
    _lora_args(p)
    _cluster_args(p)
    p = add(
        "report",
        cmd_report,
        tr(
            "one HTML page that sums up a folder's style (to keep or send)",
            "一頁 HTML 報告，整理資料夾的畫風（可留存或傳給別人）",
        ),
    )
    report_args(p)
    _cluster_args(p)
    p = add(
        "sort",
        cmd_sort,
        tr(
            "place new images into the style groups of a sorted dataset",
            "把新圖分進已經分好畫風群的資料集",
        ),
    )
    sort_args(p)
    _grouping_args(p)
    p = add(
        "map",
        cmd_map,
        tr(
            "write the interactive 3D style map (one HTML file)",
            "寫出可互動的 3D 畫風地圖（單一 HTML 檔）",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "HTML file (default: <folder>_style_atlas/style_atlas_map.html)",
            "HTML 檔（預設：<資料夾>_style_atlas/style_atlas_map.html）",
        ),
    )
    p.add_argument(
        "--title", help=tr("page title (default: the folder name)", "頁面標題（預設：資料夾名稱）")
    )
    p.add_argument(
        "--pictures",
        type=int,
        choices=[0, 320, 512],
        default=0,
        help=tr(
            "also put each picture in the file at this size, for sharp close-ups and the viewer "
            "on another computer (0: thumbnails only, the smallest file)",
            "每張圖另外以這個大小放進檔案，在別的電腦上拉近和看大圖也清楚（0：只有縮圖，檔案最小）",
        ),
    )
    p.add_argument(
        "--by-folder",
        action="store_true",
        help=tr(
            "one point per sub-folder (e.g. per artist) at its mean style, grouped into families",
            "每個子資料夾（例如每位畫師）一個點，位置是它的平均畫風，並分成幾個家族",
        ),
    )
    _cluster_args(p)
    p = add(
        "serve",
        cmd_serve,
        tr(
            "open the interactive map in the browser with live search",
            "在瀏覽器開啟可互動的地圖，可即時搜尋",
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
            "產生 72 張四種程式畫出的示範圖（不是任何人的作品），並在網頁介面打開",
        ),
    )
    p.add_argument(
        "folder",
        nargs="?",
        help=tr(
            "where to put the demo images (default: demo_styles in the cache folder)",
            "示範圖放在哪裡（預設：快取資料夾裡的 demo_styles）",
        ),
    )
    _serve_args(p)


def _serve_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--port",
        type=int,
        default=8770,
        help=tr("local port of the web app", "網頁介面用的本機連接埠"),
    )
    p.add_argument(
        "--title", help=tr("page title (default: the folder name)", "頁面標題（預設：資料夾名稱）")
    )
    p.add_argument(
        "--projection",
        default="auto",
        choices=PROJECTIONS,
        help=tr(
            "how the 3D map is laid out (auto picks umap or t-SNE)",
            "3D 地圖的排版方式（auto 會自動選 umap 或 t-SNE）",
        ),
    )
    p.add_argument(
        "--time",
        default="none",
        choices=TIME_SOURCES,
        help=tr(
            "show when each style was made: name = id or date in the file name (Pixiv, Danbooru, "
            "tweet ids; 2023-05-12), or mtime",
            "顯示各畫風是什麼時候畫的：name = 檔名裡的編號或日期"
            "（Pixiv、Danbooru、推文編號；2023-05-12），或 mtime",
        ),
    )
    _space_args(p)
    p.add_argument("--reference", metavar="DIR", help=reference_help())
    p.add_argument(
        "--no-browser",
        action="store_true",
        help=tr("do not open a browser tab", "不要自動開瀏覽器"),
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
            "在資料夾裡找畫風最接近範例的圖",
        ),
    )
    p.add_argument(
        "query", nargs="+", help=tr("query image(s) or folder(s)", "範例圖或資料夾（可多個）")
    )
    p.add_argument(
        "--in",
        dest="within",
        required=True,
        help=tr("folder to search", "要搜尋的資料夾"),
    )
    p.add_argument(
        "--top",
        type=_positive_int,
        default=20,
        help=tr("results per query", "每張查詢圖列出幾個結果"),
    )
    p.add_argument(
        "--combine",
        action="store_true",
        help=tr(
            "treat all queries as one style (their average style; from 10 images up, a model "
            "learned from them)",
            "把所有範例當成同一種畫風（用它們的平均畫風；10 張以上時，改用它們訓練的小模型）",
        ),
    )
    p.add_argument(
        "--copy-to",
        metavar="DIR",
        help=tr(
            "copy the matches (with captions) into this new folder, named by rank (01_ first)",
            "把找到的圖（連同標註檔）複製到這個新資料夾，檔名開頭是名次（01_ 最像）",
        ),
    )
    p.add_argument(
        "--by-folder",
        action="store_true",
        help=tr(
            "rank the sub-folders of --in (e.g. one per artist) instead of single images",
            "改為排序 --in 的子資料夾（例如每位畫師一個），而不是單張圖",
        ),
    )
    p.add_argument(
        "--keep-duplicates",
        action="store_true",
        help=tr(
            "also list near-copies of a better match (left out by default)",
            "也列出和更好結果幾乎一樣的圖（預設略過）",
        ),
    )
    _space_args(p)
    p.add_argument(
        "--json", action="store_true", help=tr("print JSON instead of text", "改用 JSON 輸出")
    )
    p = add(
        "outliers",
        cmd_outliers,
        tr("images least like the rest of a folder", "資料夾裡最不合群的圖"),
    )
    p.add_argument("folder")
    p.add_argument("--top", type=_positive_int, default=30, help=tr("how many to list", "列出幾張"))
    p = add(
        "audit",
        cmd_audit,
        tr(
            "check a training folder: sizes, aspect ratios, captions",
            "檢查訓練資料夾：尺寸、長寬比、標註",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "--min-side",
        type=int,
        default=512,
        help=tr("training resolution to check against", "用來對照的訓練解析度"),
    )
    p.add_argument(
        "--max-ratio",
        type=float,
        default=2.5,
        help=tr(
            "long side / short side above which an image is extreme", "長邊／短邊超過多少算極端"
        ),
    )
    p.add_argument(
        "--show",
        type=int,
        default=10,
        help=tr("files to list per problem", "每種問題列出幾個檔案"),
    )
    p.add_argument(
        "--json", action="store_true", help=tr("print JSON instead of text", "改用 JSON 輸出")
    )
    p = add(
        "duplicates",
        cmd_duplicates,
        tr(
            "near-duplicate groups (same picture, crops, frames)",
            "近重複圖的分組（同一張圖、裁切、影格）",
        ),
    )
    p.add_argument("folder")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help=tr(
            "min(style, content) cosine; 0.92 is looser",
            "min(畫風, 內容) 的餘弦相似度；0.92 較寬鬆",
        ),
    )
    p.add_argument(
        "--json", action="store_true", help=tr("print JSON instead of text", "改用 JSON 輸出")
    )


def _add_measure_commands(add: Adder) -> None:
    p = add(
        "compare",
        cmd_compare,
        tr(
            "do two folders differ in style? distance, z units, p-value",
            "兩個資料夾的畫風不同嗎？輸出距離、z 值、p 值",
        ),
    )
    p.add_argument("a", help=tr("first folder (A)", "第一個資料夾（A）"))
    p.add_argument("b", help=tr("second folder (B)", "第二個資料夾（B）"))
    p.add_argument(
        "--rounds",
        type=int,
        default=999,
        help=tr("random shuffles for the p-value", "算 p 值用的隨機重排次數"),
    )
    p.add_argument(
        "--noise-floor",
        type=_positive_float,
        help=tr("from `calibrate` (default 0.071)", "取自 `calibrate`（預設 0.071）"),
    )
    p.add_argument(
        "--json", action="store_true", help=tr("every number, as JSON", "所有數字，用 JSON 輸出")
    )
    p = add(
        "calibrate",
        cmd_calibrate,
        tr(
            "estimate the noise floor from one-style sub-folders",
            "用每個只有一種畫風的子資料夾估計雜訊底線",
        ),
    )
    p.add_argument("folder")
    p.add_argument("--json", action="store_true", help=tr("print JSON", "輸出 JSON 格式"))
    p = add(
        "bench",
        cmd_bench,
        tr(
            "score retrieval and clustering against sub-folder labels",
            "用子資料夾當標籤，替搜尋和分群打分",
        ),
    )
    p.add_argument("folder", nargs="?")
    p.add_argument(
        "--npz",
        help=tr(
            "precomputed vectors; label = key prefix before --sep",
            "算好的畫風向量；標籤 = --sep 之前的鍵名前綴",
        ),
    )
    p.add_argument(
        "--labels",
        choices=["folder", "prefix"],
        default="folder",
        help=tr("labels from sub-folders or from file-name prefixes", "標籤取自子資料夾或檔名前綴"),
    )
    p.add_argument(
        "--sep", default="__", help=tr("file-name prefix separator", "檔名前綴的分隔符號")
    )
    p.add_argument(
        "--keep-duplicates",
        action="store_true",
        help=tr("score duplicates too", "近重複圖也一起計分"),
    )
    p.add_argument("--dup-threshold", type=float, default=0.92)
    p.add_argument("--trials", type=int, default=30)
    p = add(
        "taste",
        cmd_taste,
        tr(
            "train or apply a personal like/dislike model",
            "訓練或套用個人的喜歡/不喜歡口味模型",
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
        "從哪裡開始：\n"
        "試玩：demo\n"
        "打開自己的資料夾：serve（或把資料夾拖到 scripts\\StyleAtlas.bat 上）\n"
        "整理 LoRA 資料集：audit，再 cluster（加 --export），之後的新圖用 sort；"
        "另有 duplicates、outliers\n"
        "找畫風相近的圖：search（或 serve 網頁裡的以圖搜尋）\n"
        "比較和分享：compare、report、map\n"
        "研究用：embed、calibrate、bench、taste\n"
        "安裝有問題：doctor",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="style-atlas",
        description=tr(
            "style-atlas <command> ...  (each command's options: style-atlas <command> -h)",
            "style-atlas <指令> ...（各指令的選項：style-atlas <指令> -h）",
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
            "檢查 Python、torch、GPU、模型下載和磁碟空間",
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
        log(tr("error: ", "錯誤：") + str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
