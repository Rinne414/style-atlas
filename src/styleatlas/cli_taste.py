"""The taste command: learn a personal like / dislike model from two folders, then rank new
images with it (taste.py). Training says how far to trust the model and how the two folders
differ in look; scoring names each image's closest rated picture and flags images unlike all of
them, whose scores are close to guessing."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas, build_atlas
from styleatlas.cli_common import _opts, _positive_int, log
from styleatlas.lang import chinese, tr
from styleatlas.look import describe, difference

TOP_COPIED = 20  # --copy-to: the best this many, unless --top says otherwise


def cmd_taste(a: argparse.Namespace) -> int:
    return _train(a) if a.taste_cmd == "train" else _score(a)


def _train(a: argparse.Namespace) -> int:
    from styleatlas.taste import train_taste

    opts = _opts(a)
    sides = [build_atlas(Path(f), opts, log).with_looks(opts, log) for f in (a.like, a.dislike)]
    names = tuple(
        [f"{Path(folder).name}/{side.rel(i)}" for i in range(len(side))]
        for folder, side in zip((a.like, a.dislike), sides, strict=True)
    )
    model = train_taste(sides[0].style, sides[1].style, sides[0].signature, names=names)
    saved = model.save(Path(a.model))
    log(
        tr(
            f"saved {saved}: {model.n_like} liked / {model.n_dislike} disliked",
            f"已存 {saved}：喜欢 {model.n_like} 张 / 不喜欢 {model.n_dislike} 张",
        )
    )
    log(_trust_line(model.cv_auc, model.cv_auc_groups))
    log(_look_line(sides[0], sides[1]))
    return 0


def _trust_line(auc: float, auc_groups: float) -> str:
    grouped = (
        tr(
            f"with whole look-alike groups held out {auc_groups:.2f}",
            f"整组相似画风留出来验证 {auc_groups:.2f}",
        )
        if not np.isnan(auc_groups)
        else tr(
            "too few look-alike groups to hold out (4 a side are needed)",
            "相似画风的组太少，无法整组留出来验证（喜欢和不喜欢各需要 4 组）",
        )
    )
    return tr(
        f"how well it tells them apart (AUC, 0.5 = guessing, 1 = always right): the rated "
        f"artists' other works {auc:.2f}; {grouped}. On artists you never rated, expect clearly "
        "less than the latter, near guessing when your taste is not one coherent look: a rough "
        "filter, not a score of beauty",
        f"分得多开（AUC，0.5 = 乱猜，1 = 全对）：同一批画师的其他图 {auc:.2f}；{grouped}。"
        "遇到没评过的画师，会明显比后者低；偏好不是同一种画风时，接近乱猜。偏好模型适合粗筛，"
        "不是美的分数",
    )


def _look_line(liked: Atlas, disliked: Atlas) -> str:
    """How the liked folder looks next to the disliked one (the look measures; the model itself
    works on style vectors)."""
    if liked.looks is None or disliked.looks is None:
        return ""
    words = describe(
        difference(disliked.looks, liked.looks), "zh" if chinese() else "en", than=True
    )
    if not words:
        return tr(
            "the pictures you like look about the same as those you dislike in brightness, "
            "colour, lines and contrast: the model goes by style beyond those",
            "你喜欢和不喜欢的图，在亮度、色彩、线条和对比上差不多：模型看的是这些以外的画风",
        )
    return tr(
        f"the pictures you like, next to those you dislike: {words} (look measures of your two "
        "folders; the model itself goes by style vectors)",
        f"你喜欢的图和不喜欢的比：{words}（两个文件夹的外观量测；模型本身看的是画风向量）",
    )


def _score(a: argparse.Namespace) -> int:
    from styleatlas.taste import UNFAMILIAR, TasteModel

    model = TasteModel.load(Path(a.model))
    atlas = build_atlas(Path(a.folder), _opts(a), log)
    if model.signature != atlas.signature:
        log(
            tr(
                f"model was trained on {model.signature}, images embedded as {atlas.signature}; "
                "embed with the same settings or train again",
                f"模型是用 {model.signature} 训练的，这些图却是用 {atlas.signature} 算的；"
                "请用相同设置，或重新训练",
            )
        )
        return 1
    scores = model.score(atlas.style)
    order = np.argsort(-scores, kind="stable")
    near = model.nearest_example(atlas.style)
    log(
        tr(
            "score: the higher, the more like the pictures you like (0-1, for ranking; not an "
            "exact probability)",
            "分数：越高越像你喜欢的那一堆（0~1，用来排序，不是精确的概率）",
        )
    )
    for i in order:
        print(f"{scores[i]:.3f}  {atlas.rel(int(i))}" + _closest(model, near, int(i), UNFAMILIAR))
    sys.stdout.flush()  # the list before the notes below, also when the output is piped
    _score_notes(model, near, UNFAMILIAR)
    if a.copy_to:
        _copy_top(atlas, order[: a.top], Path(a.copy_to))
    return 0


def _closest(model, near, i: int, unfamiliar: float) -> str:
    if near is None:
        return ""
    j, cos = int(near[0][i]), float(near[1][i])
    side = tr("liked", "喜欢") if model.example_liked[j] else tr("disliked", "不喜欢")
    name = _printable(model.example_names[j])
    text = tr(
        f"   closest rated: {side} {name} ({cos:.2f})",
        f"   最像评过的：{side} {name}（{cos:.2f}）",
    )
    if cos < unfamiliar:
        text += tr("   <- unlike every rated picture", "   ← 和评过的图都不太像")
    return text


def _printable(name: str) -> str:
    """A name from a shared model file, without control characters (terminal escapes)."""
    return "".join(ch if ch.isprintable() else "?" for ch in name)


def _score_notes(model, near, unfamiliar: float) -> None:
    if near is None:
        log(
            tr(
                "this model file is from an older version and keeps no rated pictures: train "
                "again to see each image's closest rated picture",
                "这个模型文件是旧版的，没有存评过的图："
                "重新 train 一次，就会列出每张最像哪张评过的图",
            )
        )
        return
    far = int((near[1] < unfamiliar).sum())
    if far:
        log(
            tr(
                f"{far} images are unlike every rated picture (highest similarity under "
                f"{unfamiliar}): their scores are close to guessing; rate a few of them to teach "
                "the model. Measured with about 50 rated pictures; images not flagged can be "
                "unfamiliar too",
                f"{far} 张和评过的图都不太像（最高相似度低于 {unfamiliar}）：它们的分数接近乱猜；"
                "挑几张评分后重新训练，模型就学得到。这是用约 50 张评分量的；没被标出的图也可能是"
                "模型没看过的画风",
            )
        )


def _copy_top(atlas: Atlas, rows: np.ndarray, dest: Path) -> None:
    from styleatlas.export import copy_ranked

    done = copy_ranked(atlas.subset(rows.tolist()), dest)
    log(
        tr(
            f"copied the best {done.placed} to {done.folder} (file names start with the rank: "
            "01_ scored highest)",
            f"已把分数最高的 {done.placed} 张复制到 {done.folder}"
            "（文件名开头是名次：01_ 分数最高）",
        )
    )
    for p, why in done.failed:
        log(tr(f"not copied {p}: {why}", f"没有复制 {p}：{why}"))


def taste_args(
    p: argparse.ArgumentParser,
    common: Callable[[argparse.ArgumentParser], None],
    formatter: type[argparse.HelpFormatter],
) -> None:
    tsub = p.add_subparsers(dest="taste_cmd", required=True)
    t1 = tsub.add_parser(
        "train",
        formatter_class=formatter,
        help=tr("learn from a liked and a disliked folder", "从一个喜欢、一个不喜欢的文件夹学习"),
    )
    t1.add_argument(
        "--like", required=True, help=tr("folder of pictures you like", "你喜欢的图的文件夹")
    )
    t1.add_argument(
        "--dislike",
        required=True,
        help=tr("folder of pictures you dislike", "你不喜欢的图的文件夹"),
    )
    t1.add_argument(
        "--model", default="taste_model.npz", help=tr("model file to write", "要存的模型文件")
    )
    t2 = tsub.add_parser(
        "score",
        formatter_class=formatter,
        help=tr("rank a folder with a trained model", "用训练好的模型给文件夹排序"),
    )
    t2.add_argument("folder", help=tr("the pictures to rank", "要排序的图"))
    t2.add_argument(
        "--model",
        default="taste_model.npz",
        help=tr(
            "trained model file (default taste_model.npz here; the web app saves one as "
            "<folder>_style_atlas/taste_model.npz). It holds the rated pictures' file names and "
            "style vectors: whoever gets the file sees what you rated",
            "训练好的模型文件（默认是这里的 taste_model.npz；网页界面存的在 "
            "<文件夹>_style_atlas/taste_model.npz）。文件里有评过的图的文件名和画风向量："
            "拿到文件的人看得到你评过哪些图",
        ),
    )
    t2.add_argument(
        "--copy-to",
        metavar="DIR",
        help=tr(
            "copy the best-scored images into this new folder, led by their rank",
            "把分数最高的图复制到这个新文件夹，文件名开头是名次",
        ),
    )
    t2.add_argument(
        "--top",
        type=_positive_int,
        default=TOP_COPIED,
        help=tr(
            f"how many --copy-to copies (default {TOP_COPIED})",
            f"--copy-to 要复制几张（默认 {TOP_COPIED}）",
        ),
    )
    for t in (t1, t2):
        common(t)
