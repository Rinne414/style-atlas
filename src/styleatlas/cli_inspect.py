"""The commands that inspect a folder or compare two: audit, duplicates, outliers, compare."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from styleatlas.atlas import embed_paths, measure_looks
from styleatlas.cli_common import _atlas, _opts, log
from styleatlas.cluster import outlier_scores
from styleatlas.images import find_images
from styleatlas.lang import chinese, columns, pad, tr
from styleatlas.look import LOOK_NAMES, describe, difference
from styleatlas.metrics import StyleScale, group_difference


def cmd_audit(a: argparse.Namespace) -> int:
    from styleatlas.dataset import audit

    paths = find_images(Path(a.folder))
    looks = measure_looks(paths, _opts(a), log)
    report = audit(paths, min_side=a.min_side, max_ratio=a.max_ratio, looks=looks)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    root = Path(a.folder)
    width = max(columns(_audit_label(key)) for key in report["summary"]) + 2
    for key, value in report["summary"].items():
        if key == "buckets":
            value = " · ".join(f"{b} {n}" for b, n in value.items())
        print(f"{pad(_audit_label(key), width)}{value}")
    for key, files in report["files"].items():
        for f in files[: a.show]:
            print(f"  [{key}] {_short(f, root)}")
        if len(files) > a.show:
            more = len(files) - a.show
            print(
                f"  [{key}] "
                + tr(
                    f"... and {more} more (--show N, or --json for all)",
                    f"……還有 {more} 張（--show N 列更多，或 --json 列全部）",
                )
            )
    return 0


AUDIT_ZH = {
    "unreadable": "讀不到",
    "truncated": "檔案不完整",
    "smaller_than_min_side": "短邊太小",
    "extreme_aspect_ratio": "長寬比太極端",
    "soft_or_enlarged": "模糊或放大過",
    "low_jpeg_quality": "JPEG 壓縮太重",
    "animated": "動圖",
    "exif_rotated": "只靠 EXIF 轉正",
    "no_caption": "沒有標註檔",
    "empty_caption": "標註是空的",
    "watermark_or_signature": "標註提到浮水印或簽名",
    "tag_spelling_mixed": "同一標籤有底線也有空格",
    "greyscale_in_colour_set": "彩色資料夾裡的灰階圖",
    "greyscale_untagged": "灰階圖的標註沒有 monochrome",
    "greyscale_tag_on_colour": "標了 greyscale 卻是彩色",
    "images": "圖片數",
    "buckets": "kohya 的 1024 bucket",
    "short_side_median": "短邊中位數",
    "short_side_p10": "短邊第 10 百分位",
}


def _audit_label(key: str) -> str:
    """The audit's summary key, with its meaning in Chinese when messages are in Chinese."""
    if key == "buckets" and not chinese():
        return "buckets (kohya, 1024)"
    return f"{key}（{AUDIT_ZH[key]}）" if chinese() and key in AUDIT_ZH else key


def _short(path: str, root: Path) -> str:
    """A path relative to the checked folder when it lies under it."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return path


def cmd_outliers(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    scores = outlier_scores(atlas.style)
    log(
        tr(
            "score = how unlike its nearest neighbours each image is (0 = like the rest; "
            "highest first)",
            "分數 = 每張圖和最像它的幾張差多少（0 = 和其他圖一樣；由高到低）",
        )
    )
    for i in np.argsort(-scores)[: a.top]:
        print(f"{scores[i]:.3f}  {atlas.rel(int(i))}")
    return 0


def cmd_duplicates(a: argparse.Namespace) -> int:
    from styleatlas.duplicates import near_duplicate_groups

    atlas = _atlas(a, a.folder)
    groups = near_duplicate_groups(atlas.style, atlas.content, a.threshold)
    if a.json:
        print(json.dumps([[atlas.rel(i) for i in g] for g in groups], ensure_ascii=False, indent=1))
        return 0
    extra = sum(len(g) - 1 for g in groups)
    log(
        tr(
            f"{len(groups)} near-duplicate groups ({extra} images beyond the first of each group)",
            f"{len(groups)} 組近重複的圖（每組留一張的話，多出 {extra} 張）",
        )
    )
    for n, g in enumerate(groups, 1):
        style, content = atlas.style[g], atlas.content[g]
        least = float(np.minimum(style @ style.T, content @ content.T).min())
        print(
            tr(f"group {n} (similarity {least:.3f}+):", f"第 {n} 組（相似度 {least:.3f} 以上）：")
        )
        for i in g:
            print(f"  {atlas.rel(i)}")
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    from styleatlas.duplicates import copies_of

    if Path(a.a).resolve() == Path(a.b).resolve():
        raise ValueError(tr("A and B are the same folder", "A 和 B 是同一個資料夾"))
    opts = _opts(a)
    groups, contents, files, looks = [], [], [], []
    for folder in (a.a, a.b):
        kept, style, content, _ = embed_paths(find_images(Path(folder)), opts, log)
        if len(kept) < 2:
            log(
                tr(
                    f"{folder}: need at least 2 readable images, found {len(kept)}",
                    f"{folder}：至少要 2 張讀得到的圖，只找到 {len(kept)} 張",
                )
            )
            return 1
        groups.append(style)
        contents.append(content)
        files.append(kept)
        looks.append(measure_looks(kept, opts, log))
    copies = copies_of(groups[1], contents[1], groups[0], contents[0])
    dist, p = group_difference(groups[0], groups[1], rounds=a.rounds)
    d = difference(*looks)
    scale = StyleScale(noise_floor=a.noise_floor) if a.noise_floor else StyleScale()
    if not a.json:
        _print_compare(a, [len(g) for g in groups], dist, p, scale, d, copies, files)
        return 0
    print(
        json.dumps(
            {
                "images": [len(groups[0]), len(groups[1])],
                "centroid_distance": round(dist, 4),
                "z": round(scale.z(dist), 2),
                "verdict": scale.verdict(dist),
                "permutation_p": round(p, 4),
                "look_b_minus_a": dict(
                    zip(LOOK_NAMES, (round(float(v), 2) for v in d), strict=True)
                ),
                "look_words": f"B is {describe(d)}" if describe(d) else "no clear difference",
                # B images that repeat an A image: e.g. LoRA renders copying a training image
                "b_copies_of_a": [
                    {"b": str(files[1][i]), "a": str(files[0][j]), "score": round(s, 3)}
                    for i, j, s in copies
                ],
            },
            indent=1,
        )
    )
    return 0


VERDICT_ZH = {"same style": "同一畫風", "related": "相關", "clearly different": "明顯不同"}


COPIES_SHOWN = 10  # near-copy pairs listed; --json has them all


def _print_compare(a, sizes, dist, p, scale, look, copies, files) -> None:
    """`compare` for a reader: the verdict, the look change and any near-copies."""
    na, nb = Path(a.a).name, Path(a.b).name
    z, verdict = scale.z(dist), scale.verdict(dist)
    pv = "< 0.01" if p < 0.01 else f"{p:.2f}"
    print(
        tr(
            f"A: {na} ({sizes[0]} images)   B: {nb} ({sizes[1]} images)",
            f"A：{na}（{sizes[0]} 張）  B：{nb}（{sizes[1]} 張）",
        )
    )
    print(
        tr(
            f"style distance {dist:.3f} (z {z:.1f}, {verdict}; p {pv})",
            f"畫風距離 {dist:.3f}（z {z:.1f}，{VERDICT_ZH.get(verdict, verdict)}；p {pv}）",
        )
    )
    words = describe(look, "zh" if chinese() else "en")
    print(
        tr(
            f"look: B is {words}" if words else "look: no clear difference",
            f"外觀：B 比 A {words}" if words else "外觀：沒有明顯差異",
        )
    )
    print(
        tr(
            f"{len(copies)} images of B nearly repeat an image of A",
            f"B 裡有 {len(copies)} 張和 A 的某張幾乎一樣",
        )
    )
    for i, j, s in copies[:COPIES_SHOWN]:
        print(f"  B {files[1][i].name}  ~  A {files[0][j].name}  ({s:.3f})")
    if len(copies) > COPIES_SHOWN:
        more = len(copies) - COPIES_SHOWN
        print(
            tr(
                f"  ... and {more} more (--json lists all)",
                f"  ……還有 {more} 組（--json 會全部列出）",
            )
        )
    log(
        tr(
            "z: in units of the difference between two halves of one style (the default scale "
            "was measured on AI renders; `calibrate` measures it on your own folders, then pass "
            "--noise-floor); --json for every number",
            "z：以「同一畫風的兩半」之間的差距為單位（預設尺度是在 AI 算圖上量的；"
            "`calibrate` 可以用你自己的資料夾重新量，再用 --noise-floor 帶入）；"
            "--json 會列出全部數字",
        )
    )
