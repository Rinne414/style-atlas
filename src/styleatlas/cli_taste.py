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
            f"已存 {saved}：喜歡 {model.n_like} 張 / 不喜歡 {model.n_dislike} 張",
        )
    )
    log(_trust_line(model.cv_auc, model.cv_auc_groups))
    log(_look_line(sides[0], sides[1]))
    return 0


def _trust_line(auc: float, auc_groups: float) -> str:
    grouped = (
        tr(
            f"with whole look-alike groups held out {auc_groups:.2f}",
            f"整組相似畫風留出來驗證 {auc_groups:.2f}",
        )
        if not np.isnan(auc_groups)
        else tr(
            "too few look-alike groups to hold out (4 a side are needed)",
            "相似畫風的群太少，無法整組留出來驗證（喜歡和不喜歡各需要 4 群）",
        )
    )
    return tr(
        f"how well it tells them apart (AUC, 0.5 = guessing, 1 = always right): the rated "
        f"artists' other works {auc:.2f}; {grouped}. On artists you never rated, expect clearly "
        "less than the latter, near guessing when your taste is not one coherent look: a rough "
        "filter, not a score of beauty",
        f"分得多開（AUC，0.5 = 亂猜，1 = 全對）：同一批畫師的其他圖 {auc:.2f}；{grouped}。"
        "遇到沒評過的畫師，會明顯比後者低；口味不是同一種畫風時，接近亂猜。口味模型適合粗篩，"
        "不是美的分數",
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
            "你喜歡和不喜歡的圖，在亮度、色彩、線條和對比上差不多：模型看的是這些以外的畫風",
        )
    return tr(
        f"the pictures you like, next to those you dislike: {words} (look measures of your two "
        "folders; the model itself goes by style vectors)",
        f"你喜歡的圖和不喜歡的比：{words}（兩個資料夾的外觀量測；模型本身看的是畫風向量）",
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
                f"模型是用 {model.signature} 訓練的，這些圖卻是用 {atlas.signature} 算的；"
                "請用相同設定，或重新訓練",
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
            "分數：越高越像你喜歡的那一堆（0～1，用來排序，不是精確的機率）",
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
    side = tr("liked", "喜歡") if model.example_liked[j] else tr("disliked", "不喜歡")
    name = _printable(model.example_names[j])
    text = tr(
        f"   closest rated: {side} {name} ({cos:.2f})",
        f"   最像評過的：{side} {name}（{cos:.2f}）",
    )
    if cos < unfamiliar:
        text += tr("   <- unlike every rated picture", "   ← 和評過的圖都不太像")
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
                "這個模型檔是舊版的，沒有存評過的圖：重新 train 一次，就會列出每張最像哪張評過的圖",
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
                f"{far} 張和評過的圖都不太像（最高相似度低於 {unfamiliar}）：它們的分數接近亂猜；"
                "挑幾張評分後重新訓練，模型就學得到。這是用約 50 張評分量的；沒被標出的圖也可能是"
                "模型沒看過的畫風",
            )
        )


def _copy_top(atlas: Atlas, rows: np.ndarray, dest: Path) -> None:
    from styleatlas.export import copy_ranked

    done = copy_ranked(atlas.subset(rows.tolist()), dest)
    log(
        tr(
            f"copied the best {done.placed} to {done.folder} (file names start with the rank: "
            "01_ scored highest)",
            f"已把分數最高的 {done.placed} 張複製到 {done.folder}（檔名開頭是名次：01_ 分數最高）",
        )
    )
    for p, why in done.failed:
        log(tr(f"not copied {p}: {why}", f"沒有複製 {p}：{why}"))


def taste_args(
    p: argparse.ArgumentParser,
    common: Callable[[argparse.ArgumentParser], None],
    formatter: type[argparse.HelpFormatter],
) -> None:
    tsub = p.add_subparsers(dest="taste_cmd", required=True)
    t1 = tsub.add_parser(
        "train",
        formatter_class=formatter,
        help=tr("learn from a liked and a disliked folder", "從一個喜歡、一個不喜歡的資料夾學習"),
    )
    t1.add_argument(
        "--like", required=True, help=tr("folder of pictures you like", "你喜歡的圖的資料夾")
    )
    t1.add_argument(
        "--dislike",
        required=True,
        help=tr("folder of pictures you dislike", "你不喜歡的圖的資料夾"),
    )
    t1.add_argument(
        "--model", default="taste_model.npz", help=tr("model file to write", "要存的模型檔")
    )
    t2 = tsub.add_parser(
        "score",
        formatter_class=formatter,
        help=tr("rank a folder with a trained model", "用訓練好的模型替資料夾排序"),
    )
    t2.add_argument("folder", help=tr("the pictures to rank", "要排序的圖"))
    t2.add_argument(
        "--model",
        default="taste_model.npz",
        help=tr(
            "trained model file (default taste_model.npz here; the web app saves one as "
            "<folder>_style_atlas/taste_model.npz). It holds the rated pictures' file names and "
            "style vectors: whoever gets the file sees what you rated",
            "訓練好的模型檔（預設是這裡的 taste_model.npz；網頁介面存的在 "
            "<資料夾>_style_atlas/taste_model.npz）。檔案裡有評過的圖的檔名和畫風向量："
            "拿到檔案的人看得到你評過哪些圖",
        ),
    )
    t2.add_argument(
        "--copy-to",
        metavar="DIR",
        help=tr(
            "copy the best-scored images into this new folder, led by their rank",
            "把分數最高的圖複製到這個新資料夾，檔名開頭是名次",
        ),
    )
    t2.add_argument(
        "--top",
        type=_positive_int,
        default=TOP_COPIED,
        help=tr(
            f"how many --copy-to copies (default {TOP_COPIED})",
            f"--copy-to 要複製幾張（預設 {TOP_COPIED}）",
        ),
    )
    for t in (t1, t2):
        common(t)
