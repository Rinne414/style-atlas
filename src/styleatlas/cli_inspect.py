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
from styleatlas.metrics import (
    ARTIST_SCALE_ARTISTS,
    SEPARABLE_P,
    ArtistReading,
    StyleScale,
    artist_reading,
    distinctive_order,
    group_difference,
)


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
    _audit_advice(report["summary"], a.min_side)
    if report["frequent_tags"]:
        shares = ", ".join(f"{t} {round(100 * share)}%" for t, share in report["frequent_tags"])
        log(
            tr(
                f"tags in half or more of the captions: {shares} (content in nearly every "
                "image is learned along with the style)",
                f"出现在一半以上标注的标签：{shares}（几乎每张都有的内容会和画风一起被学进去）",
            )
        )
    if report["tags_spelt_two_ways"]:
        log(
            tr("tags written both with _ and with spaces: ", "同时有下划线和空格两种写法的标签：")
            + ", ".join(report["tags_spelt_two_ways"])
        )
    for key, files in report["files"].items():
        for f in files[: a.show]:
            print(f"  [{key}] {_short(f, root)}")
        if len(files) > a.show:
            more = len(files) - a.show
            print(
                f"  [{key}] "
                + tr(
                    f"... and {more} more (--show N, or --json for all)",
                    f"……还有 {more} 张（--show N 列更多，或 --json 列全部）",
                )
            )
    return 0


AUDIT_ZH = {
    "unreadable": "读不到",
    "truncated": "文件不完整",
    "smaller_than_min_side": "短边太小",
    "extreme_aspect_ratio": "长宽比太极端",
    "soft_or_enlarged": "模糊或放大过",
    "low_jpeg_quality": "JPEG 压缩太重",
    "animated": "动图",
    "exif_rotated": "只靠 EXIF 转正",
    "no_caption": "没有标注文件",
    "empty_caption": "标注是空的",
    "watermark_or_signature": "标注提到水印或签名",
    "tag_spelling_mixed": "同一标签有下划线也有空格",
    "greyscale_in_colour_set": "彩色文件夹里的灰阶图",
    "greyscale_untagged": "灰阶图的标注没有 monochrome",
    "greyscale_tag_on_colour": "标了 greyscale 却是彩色",
    "images": "图片数",
    "buckets": "kohya 的 1024 bucket",
    "short_side_median": "短边中位数",
    "short_side_p10": "短边第 10 百分位",
}


def _audit_advice(summary: dict, min_side: int) -> None:
    """What to do about the two findings that cover whole downloaded folders."""
    n = summary.get("images", 0)
    if n and summary.get("no_caption", 0) == n:
        log(
            tr(
                "no image has a caption: a style LoRA can be trained without them (kohya then "
                "uses the trigger word in the folder name); for captions, run a tagger such as "
                "WD14 first (style-atlas does not write captions)",
                "全部都没有标注文件：不加标注也能训练画风 LoRA"
                "（kohya 会改用文件夹名称里的触发词）；"
                "要标注的话，先用 WD14 tagger 之类的工具生成（style-atlas 不会生成标注）",
            )
        )
    if n and summary.get("smaller_than_min_side", 0) * 2 >= n:
        log(
            tr(
                f"half or more of the images are under {min_side} px on the short side: "
                "downloads from Danbooru or Pixiv are often the reduced 'sample' size, so get the "
                "originals where you can; training enlarges small images, which blurs them",
                f"一半以上的图短边小于 {min_side} px："
                "从 Danbooru、Pixiv 下载时常拿到缩小的 sample 版，能的话请改用原图；"
                "训练时小图会被放大，会变模糊",
            )
        )


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
            "分数 = 每张图和最像它的几张差多少（0 = 和其他图一样；由高到低）",
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
            f"{len(groups)} 组近重复的图（每组留一张的话，多出 {extra} 张）",
        )
    )
    for n, g in enumerate(groups, 1):
        style, content = atlas.style[g], atlas.content[g]
        least = float(np.minimum(style @ style.T, content @ content.T).min())
        print(
            tr(f"group {n} (similarity {least:.3f}+):", f"第 {n} 组（相似度 {least:.3f} 以上）：")
        )
        for i in g:
            print(f"  {atlas.rel(i)}")
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    from styleatlas.duplicates import copies_of

    if Path(a.a).resolve() == Path(a.b).resolve():
        raise ValueError(tr("A and B are the same folder", "A 和 B 是同一个文件夹"))
    opts = _opts(a)
    groups, contents, files, looks = [], [], [], []
    for folder in (a.a, a.b):
        kept, style, content, _ = embed_paths(find_images(Path(folder)), opts, log)
        if len(kept) < 2:
            log(
                tr(
                    f"{folder}: need at least 2 readable images, found {len(kept)}",
                    f"{folder}：至少要 2 张读得到的图，只找到 {len(kept)} 张",
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
    # works of real artists are read against real artists, unless a scale was calibrated
    reading = None if a.noise_floor else artist_reading(dist, len(groups[0]), len(groups[1]))
    if not a.json:
        _print_compare(a, groups, dist, p, scale, d, copies, files, reading)
        return 0
    print(
        json.dumps(
            {
                "images": [len(groups[0]), len(groups[1])],
                "centroid_distance": round(dist, 4),
                "z": round(scale.z(dist), 2),
                "verdict": scale.verdict(dist),
                "permutation_p": round(p, 4),
                "separable": p < SEPARABLE_P,
                "artist_reading": None
                if reading is None
                else {
                    "effective_works_a_side": reading.n,
                    "position": reading.position,
                    "different_artists_p5": round(reading.others_p5, 3),
                    "different_artists_median": round(reading.others_median, 3),
                    "one_artist_oldest_vs_newest_median": round(reading.one_artist_change, 3),
                },
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


VERDICT_ZH = {"same style": "同一画风", "related": "相关", "clearly different": "明显不同"}


COPIES_SHOWN = 10  # near-copy pairs listed; --json has them all
DISTINCTIVE_SHOWN = 3  # images per side that best show the difference


def _print_compare(a, groups, dist, p, scale, look, copies, files, reading=None) -> None:
    """`compare` for a reader: the verdict, the look change, the images that best show the
    difference, any near-copies, and what it means for training."""
    sizes = [len(g) for g in groups]
    na, nb = Path(a.a).name, Path(a.b).name
    pv = "< 0.01" if p < 0.01 else f"{p:.2f}"
    print(
        tr(
            f"A: {na} ({sizes[0]} images)   B: {nb} ({sizes[1]} images)",
            f"A：{na}（{sizes[0]} 张）  B：{nb}（{sizes[1]} 张）",
        )
    )
    if reading is None:  # few images, or a calibrated scale: the z scale
        z, verdict = scale.z(dist), scale.verdict(dist)
        print(
            tr(
                f"style distance {dist:.3f} (z {z:.2f}, {verdict}; p {pv})",
                f"画风距离 {dist:.3f}（z {z:.2f}，{VERDICT_ZH.get(verdict, verdict)}；p {pv}）",
            )
        )
        if a.noise_floor:
            log(
                tr(
                    "z on the scale from --noise-floor; the comparison with real artists is left "
                    "out",
                    "z 用的是 --noise-floor 的尺度；不和真实画师比",
                )
            )
    else:
        print(_separable_line(dist, pv, p < SEPARABLE_P))
        print(_reading_line(reading))
    words = describe(look, "zh" if chinese() else "en", than=True)
    print(
        tr(
            f"look: B is {words}" if words else "look: no clear difference",
            f"外观：B 比 A {words}" if words else "外观：没有明显差异",
        )
    )
    for side, name, other in ((0, "A", "B"), (1, "B", "A")):
        order = distinctive_order(groups[side], groups[1 - side])[:DISTINCTIVE_SHOWN]
        folder = (na, nb)[side]
        shown = ", ".join(f"{folder}/{files[side][k].name}" for k in order)
        print(
            tr(
                f"most typical of {name} and least like {other} (open them to see the "
                f"difference): {shown}",
                f"最能代表 {name}、又最不像 {other} 的图（打开来看最能看出差别）：{shown}",
            )
        )
    if copies or reading is None:  # with renders (few images), none repeating is news too
        print(
            tr(
                f"{len(copies)} images of B nearly repeat an image of A",
                f"B 里有 {len(copies)} 张和 A 的某张几乎一样",
            )
        )
    for i, j, s in copies[:COPIES_SHOWN]:
        print(f"  B {files[1][i].name}  ~  A {files[0][j].name}  ({s:.3f})")
    if len(copies) > COPIES_SHOWN:
        more = len(copies) - COPIES_SHOWN
        print(
            tr(
                f"  ... and {more} more (--json lists all)",
                f"  ……还有 {more} 组（--json 会全部列出）",
            )
        )
    if reading is not None:
        print(_training_line(reading, p < SEPARABLE_P))
        return
    log(
        tr(
            "z: in units of the difference between two halves of one style (the default scale "
            "was measured on AI renders; `calibrate` measures it on your own folders, then pass "
            "--noise-floor); --json for every number",
            "z：以“同一画风的两半”之间的差距为单位（默认尺度是在 AI 出图上量的；"
            "`calibrate` 可以用你自己的文件夹重新量，再用 --noise-floor 带入）；"
            "--json 会列出全部数字",
        )
    )


def _separable_line(dist: float, pv: str, separable: bool) -> str:
    if separable:
        return tr(
            f"style distance {dist:.3f}; p {pv}: the two sides likely differ (random splits of "
            "these images seldom come out this far apart)",
            f"画风距离 {dist:.3f}；p {pv}：两边很可能不同（把这些图随机分成两半，很少差这么多）",
        )
    return tr(
        f"style distance {dist:.3f}; p {pv}: no clear difference (random splits of these images "
        "often come out this far apart)",
        f"画风距离 {dist:.3f}；p {pv}：看不出明显差异（把这些图随机分成两半，常常也差这么多）",
    )


POSITION_EN = {
    "below_p5": "closer than 95% of pairs of different artists",
    "p5_to_median": "as far apart as the closer half of pairs of different artists",
    "above_median": "farther apart than half of pairs of different artists",
}
POSITION_ZH = {
    "below_p5": "比 95% 的“两位不同画师”都接近",
    "p5_to_median": "和比较接近的那一半“两位不同画师”差不多",
    "above_median": "比一半的“两位不同画师”还远",
}
FEW_A_SIDE = 10  # below this many works a side (effective), a real difference may not show


def _reading_line(r: ArtistReading) -> str:
    n, artists = round(r.n), ARTIST_SCALE_ARTISTS
    return tr(
        f"next to Danbooru artists (about {n} works a side): {POSITION_EN[r.position]}. For "
        f"reference, 95% of pairs of different artists are {r.others_p5:.3f} or more apart, half "
        f"{r.others_median:.3f} or more; one artist's oldest and newest works "
        f"{r.one_artist_change:.3f} (median; {artists} artists)",
        f"和 Danbooru 画师比（每边约 {n} 张）：{POSITION_ZH[r.position]}。参考：两位不同画师有 "
        f"95% 相差 {r.others_p5:.3f} 以上，一半相差 {r.others_median:.3f} 以上；同一位画师最早和"
        f"最新的作品，中位数相差 {r.one_artist_change:.3f}（{artists} 位画师）",
    )


def _training_line(r: ArtistReading, separable: bool) -> str:
    """Options, not orders: what training both sides together does (none of it measured on
    trained LoRAs)."""
    if not separable:
        few = r.n < FEW_A_SIDE
        return tr(
            "training: no sign that the two sides need splitting"
            + (" (with this few images a real difference may not show)" if few else ""),
            "训练：看不出需要分开的迹象"
            + ("（图这么少时，真的差异也可能看不出来）" if few else ""),
        )
    if r.position == "above_median":
        return tr(
            "training: together, a LoRA would mix two looks as far apart as many pairs of "
            "artists; train one side alone if you want its look",
            "训练：合在一起训练，LoRA 会混合两种差得像两位画师的画风；想要其中一种就只用那一边",
        )
    mix = tr(
        "training: together, a LoRA learns both looks mixed (often fine for an artist LoRA); for "
        "one side's look only, train that side alone (the images above show the difference)",
        "训练：合在一起训练，LoRA 会学到两边混合的画风（训练一位画师的 LoRA 时常常没关系）；"
        "只想要其中一边的画风，就只用那一边（上面的图看得出差别）",
    )
    if r.position != "below_p5":
        return mix
    return mix + tr(
        ". To see whether a style changed gradually or at a point, put all the works in one "
        "folder and run cluster --granularity timeline",
        "。想看画风是慢慢变还是在某个时间点转变：把作品放进同一个文件夹，用 cluster "
        "--granularity timeline",
    )
