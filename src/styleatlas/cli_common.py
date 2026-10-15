"""Helpers every command shares: logging, encoder options, embedding a folder in the chosen
vector space, the reference folder, and the grouping options."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

from styleatlas.atlas import Atlas, EncodeOptions, build_atlas
from styleatlas.cluster import (
    ARTISTS,
    ARTISTS_CUT,
    ARTISTS_FEW,
    GRANULARITY,
    PERIODS,
    Clustering,
    cluster_by_artist,
    cluster_styles,
    edit_groups,
)
from styleatlas.lang import tr
from styleatlas.metrics import (
    CHARACTERS,
    MAX_NEUTRALIZE,
    PLAIN,
    SubjectCentring,
)
from styleatlas.timeline import TIMELINE

SOFT_PERIODS = 100  # below this, k-means periods changed with the seed (agreement ARI 0.3-0.7)


def neutralize_help() -> str:
    return tr(
        "ignore the N strongest directions of variation (try 1) when the same characters appear "
        "in many styles (--ignore-characters usually does better); not for a mix of different "
        "artists",
        "忽略變化最大的 N 個方向（可試 1）；同樣的角色出現在很多畫風裡時用"
        "（--ignore-characters 通常更好）；混了不同畫師時不要用",
    )


def characters_help() -> str:
    return tr(
        "when the same characters appear in many styles: find the characters from the picture "
        "content and compare styles as if all were drawn on the same character; not for a mix of "
        "different artists",
        "同樣的角色出現在很多畫風裡時用：從畫面內容找出角色，再把畫風當成都畫同一個角色來比；"
        "混了不同畫師時不要用",
    )


def reference_help() -> str:
    return tr(
        "folder of styles you already know (artists, forum recipes); adds an originality axis: "
        "distance from each image to its closest reference",
        "已知畫風的資料夾（畫師、論壇配方）；多一條原創軸：每張圖到最近參考圖的距離",
    )


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _opts(a: argparse.Namespace) -> EncodeOptions:
    from styleatlas.safety import limit_resources

    limit_resources(a.threads)
    return EncodeOptions(
        device=a.device,
        crop=a.crop,
        batch_size=a.batch,
        resolution=a.resolution,
        db_path=Path(a.cache_db) if a.cache_db else None,
    )


def _atlas(
    a: argparse.Namespace, folder: str, exclude: list[Path] | None = None, progress=log
) -> Atlas:
    recursive = not a.no_recursive
    atlas = build_atlas(Path(folder), _opts(a), progress, recursive=recursive, exclude=exclude)
    for p, why in atlas.failed:
        progress(tr(f"skipped {p}: {why}", f"略過 {p}：{why}"))
    space = _space(a)
    if space != PLAIN:
        atlas, a.fitted_space = atlas.in_space(space)  # reused for --reference
        _log_space(a.fitted_space.transform)
    return atlas


def _space(a: argparse.Namespace) -> str:
    """The vector space chosen on the command line (see metrics.StyleSpace)."""
    if getattr(a, "ignore_characters", False):
        return CHARACTERS
    n = getattr(a, "neutralize", 0)
    return f"neutralize-{n}" if n else PLAIN


def _positive_int(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def _neutralize_count(text: str) -> int:
    n = int(text)
    if not 0 <= n <= MAX_NEUTRALIZE:
        raise argparse.ArgumentTypeError(f"takes 0 to {MAX_NEUTRALIZE}")
    return n


def _log_space(transform: object) -> None:
    if isinstance(transform, SubjectCentring):
        n = len(transform.centres)
        if not n:
            log(
                tr(
                    "too few images to find characters: styles are compared as they are",
                    "圖太少，找不出角色：照原樣比較畫風",
                )
            )
        else:
            log(
                tr(
                    f"comparing styles per character: {n} subjects found in the picture content",
                    f"依角色比較畫風：從畫面內容找到 {n} 個主體",
                )
            )
    else:
        k = len(getattr(transform, "axes", []))
        log(
            tr(
                f"ignoring the {k} strongest direction(s) of variation (subject axis)",
                f"忽略變化最大的 {k} 個方向（主體軸）",
            )
        )


def _reference(a: argparse.Namespace, progress=log) -> Atlas | None:
    """The --reference folder (styles you already know), embedded the same way."""
    if not getattr(a, "reference", None):
        return None
    ref = build_atlas(Path(a.reference), _opts(a), progress, recursive=True)
    for p, why in ref.failed:
        progress(tr(f"reference skipped {p}: {why}", f"參考圖略過 {p}：{why}"))
    space = getattr(a, "fitted_space", None)  # same space as the folder
    if space is not None:
        ref = replace(ref, style=space.apply(ref.style, ref.content))
    progress(
        tr(
            f"reference: {len(ref)} images from {a.reference}",
            f"參考圖：{a.reference} 的 {len(ref)} 張",
        )
    )
    return ref


def _cluster(a: argparse.Namespace, atlas: Atlas):
    if a.granularity == ARTISTS:
        return _cluster_by_artist(a, atlas)
    if a.granularity == TIMELINE:
        return _cluster_timeline(a, atlas)
    method, k, threshold = a.method, a.k, a.threshold
    if a.granularity == "period" and threshold is None:
        if method != "agglomerative":
            raise ValueError(
                tr(
                    "--granularity period uses k-means; leave out --method",
                    "--granularity period 用的是 k-means；請拿掉 --method",
                )
            )
        method, k = "kmeans", a.k or PERIODS
        if len(atlas) < SOFT_PERIODS:
            log(
                tr(
                    f"note: with fewer than {SOFT_PERIODS} images the period boundaries are soft; "
                    "check them in the web app (serve)",
                    f"注意：少於 {SOFT_PERIODS} 張時，時期的分界不太穩定，請在網頁介面確認",
                )
            )
    elif threshold is None:
        threshold = GRANULARITY.get(a.granularity)  # None for auto
    result = cluster_styles(
        atlas.style, method=method, threshold=threshold, n_clusters=k, min_size=a.min_size
    )
    cut = result.params.get("threshold")
    auto = result.params.get("auto")
    how = f", cut {cut} ({'auto' if auto else 'set'})" if cut else ""
    how_zh = f"，切分距離 {cut}，{'自動選的' if auto else '指定的'}" if cut else ""
    method_zh = METHOD_ZH.get(result.method, result.method)
    if getattr(a, "families", False):
        log(_families_line(result, a.min_size))
    else:
        log(_groups_line(result, f"{result.method}{how}", f"{method_zh}{how_zh}"))
    if "note" in result.params:
        log(tr("note: ", "注意：") + result.params["note"])
    return result


def saved_groups(
    a: argparse.Namespace, atlas: Atlas, folder: Path
) -> tuple[Clustering, dict[int, str]]:
    """The groups as left in the web app for `folder` (hand edits and names), else a fresh
    grouping."""
    from styleatlas.export import output_dir
    from styleatlas.groupfile import GROUPS_FILE, carry_names, load_groups

    clustering = _cluster(a, atlas)
    path = output_dir(folder) / GROUPS_FILE
    saved = None if getattr(a, "fresh", False) else load_groups(path, atlas)
    if saved is None:
        return clustering, {}
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
    log(
        tr(
            f"using the groups and names the web app saved in {path} ({when}); --fresh to regroup",
            f"沿用網頁介面在 {when} 存的分群和名稱（{path}）；要重新分群請加 --fresh",
        )
    )
    edited = edit_groups(atlas.style, clustering, dict(enumerate(saved.labels.tolist())))
    return edited, carry_names(saved.labels, edited.labels, saved.names)


def _cluster_by_artist(a: argparse.Namespace, atlas: Atlas) -> Clustering:
    if _space(a) != PLAIN or a.threshold is not None or a.k or a.method != "agglomerative":
        raise ValueError(
            tr(
                "--granularity artists takes plain style vectors and its own cut: leave out "
                "--neutralize, --ignore-characters, --threshold, --k and --method",
                "--granularity artists 用原始畫風向量和自己的切分：請拿掉 "
                "--neutralize、--ignore-characters、--threshold、--k 和 --method",
            )
        )
    result = cluster_by_artist(atlas.style, min_size=a.min_size)
    how = f"by artist: whitened, cut {ARTISTS_CUT}"
    log(_groups_line(result, how, f"依畫師分群，切分距離 {ARTISTS_CUT}"))
    if result.n_clusters < ARTISTS_FEW:
        log(
            tr(
                f"note: grouping by artist is meant for galleries of 20 or more artists; with "
                f"{result.n_clusters} groups the default (auto) may suit this folder better",
                f"注意：依畫師分群是給 20 位以上畫師的圖庫用的；這裡只分出 {result.n_clusters} 群，"
                "預設的自動分群可能更合適",
            )
        )
    return result


METHOD_ZH = {"agglomerative": "階層式分群", "kmeans": "k-means 分段", "hdbscan": "HDBSCAN"}


def _groups_line(result: Clustering, how: str, how_zh: str) -> str:
    n, u = result.n_clusters, result.n_unassigned
    return tr(f"{n} styles, {u} unassigned ({how})", f"分成 {n} 群，{u} 張未分群（{how_zh}）")


def _cluster_timeline(a: argparse.Namespace, atlas: Atlas):
    """--granularity timeline: contiguous periods along the --time order, with their test."""
    from styleatlas.images import file_times
    from styleatlas.timeline import cluster_timeline, verdict_text

    source = getattr(a, "time", "none")
    if source == "none":
        raise ValueError(
            tr(
                "--granularity timeline needs a time: add --time name (ids or dates in the file "
                "names) or --time mtime",
                "--granularity timeline 需要時間：加 --time name（檔名裡的編號或日期）"
                "或 --time mtime",
            )
        )
    k = a.k or PERIODS
    result = cluster_timeline(
        atlas.style, file_times(atlas.paths, source), k, content=atlas.content
    )
    sizes = ", ".join(str(c.size) for c in result.clusters)
    log(
        tr(
            f"{k} periods along the timeline ({sizes} images, earliest first; "
            f"{result.n_unassigned} without a time)",
            f"依時間分成 {k} 個時期（由早到晚各 {sizes} 張；{result.n_unassigned} 張沒有時間資訊）",
        )
    )
    log(verdict_text(result.params))
    return result


def _families_line(result: Clustering, min_size: int) -> str:
    """`map --by-folder`: the points are sub-folders, grouped into families of similar style."""
    n, u, cut = result.n_clusters, result.n_unassigned, result.params.get("threshold")
    return tr(
        f"{n} families of similar sub-folders, {u} folders in none (cut {cut}; a family needs "
        f"{min_size} folders or more)",
        f"分成 {n} 個畫風相近的家族，{u} 個資料夾不屬於任何家族（切分距離 {cut}；"
        f"一個家族至少要 {min_size} 個資料夾）",
    )


def export_notes(
    done, folders: list[str], layout: str, trigger: bool, respell: dict | None = None
) -> None:
    """After an export: small training images, photos written upright, respelt tags, and the
    trigger words in the captions (with a warning when one is not plain ASCII)."""
    from styleatlas.export import SMALL_FOR_TRAINING, trigger_of

    if done.small_training:
        log(
            tr(
                f"{done.small_training} training image(s) have a short side under "
                f"{SMALL_FOR_TRAINING} px: a 1024 training size enlarges them (blurry); "
                "`style-atlas audit` lists them",
                f"有 {done.small_training} 張訓練圖短邊小於 {SMALL_FOR_TRAINING} px："
                "用 1024 訓練時會被放大（會模糊）；`style-atlas audit` 會列出它們",
            )
        )
    if done.upright:
        log(
            tr(
                f"{done.upright} photo(s) turned only by EXIF were written upright "
                "(kohya would train them sideways); the originals are unchanged",
                f"{done.upright} 張只靠 EXIF 轉正的照片已轉正後存出（kohya 會把它們橫著訓練）；"
                "原檔沒有改動",
            )
        )
    if respell:
        log(
            tr("tags respelt in the copies: ", "複本中統一寫法的標籤：")
            + ", ".join(f"{tag} -> {spelt}" for tag, spelt in sorted(respell.items()))
        )
    if not trigger:
        return
    words = sorted({w for f in folders if (w := trigger_of(f, layout)) is not None})
    if words:
        log(tr("trigger words: ", "觸發詞：") + ", ".join(words))
    if any(not w.isascii() for w in words):
        log(tr(NON_ASCII_TRIGGER_EN, NON_ASCII_TRIGGER_ZH))


NON_ASCII_TRIGGER_EN = (
    "note: some trigger words are not plain English: the text encoders of SD 1.5 and SDXL split "
    "them into many byte pieces; name the groups in English for those models"
)
NON_ASCII_TRIGGER_ZH = (
    "注意：有些觸發詞不是英文：SD 1.5、SDXL 的文字編碼器會把中文拆成很多碎片；"
    "訓練這些模型時，群名建議用英文"
)


def web_exclusions(atlas: Atlas, folder: Path) -> list[int]:
    """Images excluded by hand (X) in the web app, as indices into `atlas`."""
    from styleatlas.export import output_dir
    from styleatlas.persist import RelPathMap

    marks = RelPathMap(output_dir(folder) / "excluded.json", atlas, read_only=True)
    if marks.unreadable:
        log(
            tr(
                f"warning: could not read {marks.path}; the web app's exclusions are NOT applied",
                f"警告：讀不到 {marks.path}，網頁介面的排除不會套用",
            )
        )
    return sorted(i for i, v in marks.values.items() if v is True)
