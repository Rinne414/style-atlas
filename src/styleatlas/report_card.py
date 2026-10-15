"""A one-page style report for a folder (`style-atlas report`): how consistent its style is, how
it looks next to Danbooru artists, which artists of a reference library it is closest to, which
of its sub-folders (e.g. artists) draw alike, and its style groups with their most typical
images. One HTML file with the thumbnails inside, to keep or send."""

from __future__ import annotations

import base64
import html
import json
import re
from collections import Counter
from collections.abc import Collection
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path

import numpy as np

from styleatlas.atlas import FAMILY_CUT, LOAD_ERRORS, MIN_FOLDERS, Atlas, folder_atlas
from styleatlas.cluster import UNASSIGNED, Clustering, batch_verdict, cluster_styles, keep_rows
from styleatlas.consistency import consistency
from styleatlas.dataset import distinctive_tags, tag_summary
from styleatlas.duplicates import near_duplicate_groups
from styleatlas.images import cached_thumbnail, labels_from_folders, timeline, timeline_span
from styleatlas.lang import tr
from styleatlas.look import LOOK_NAMES, NOTABLE, THAN_ZH, WORDS_ZH, profile
from styleatlas.metrics import centroid
from styleatlas.render_check import RenderCheck, check_renders

THUMBS = 6  # most typical images shown per group (one of each set of near-duplicates)
FOLDER_NEIGHBOURS = 2  # closest other sub-folders named per sub-folder
RENDER_THUMBS = 12  # renders least like the training set, and memorised pairs, shown
THUMB_PX = 160
PLACEHOLDER = re.compile(r"\{(title|lang|body)\}")

TEXT = {
    "zh": {
        "images": "張圖",
        "made": "製作日期",
        "intro": "這頁依序是：畫風有多一致、外觀和 Danbooru 畫師比起來如何、"
        "（有子資料夾時）哪些子資料夾畫風相近、自動分出的畫風群。數字只描述畫風怎麼不同，不評好壞。",
        "ends_consistency": ("很一致", "很分散"),
        "consist_folders": "這個資料夾有 {n} 個子資料夾：一致性是把全部當成同一位畫師來比的，"
        "收藏了多位畫師的圖庫本來就會顯得很分散。",
        "folders": "子資料夾：哪些畫風相近",
        "folders_sub": "把每個子資料夾（例如每位畫師）的平均畫風拿來互相比較。",
        "closest_to": "最像：",
        "family": "家族 {k}",
        "alone": "自成一格",
        "folders_note": "家族分得很鬆（每位畫師換一半作品重算，結果只部分相同），請以「最像」為主。"
        "立體的畫師地圖：style-atlas map --by-folder，或網頁介面的「畫師地圖」。",
        "groups_sub": "自動分出的畫風群，張數多的在前；每群顯示最有代表性的幾張，"
        "幾乎相同的圖只放一張。",
        "copies": "其中 {n} 張屬於 {k} 組幾乎相同的圖（同一張圖、裁切或同場景的連續畫面），"
        "每組只放一張縮圖",
        "excluded": "另有 {n} 張已排除，不算在內",
        "consistency": "畫風一致性",
        "tight": "很一致",
        "like one artist": "在一位畫師的正常範圍內（兩三位畫師混在一起也常落在這裡）",
        "mixed": "可能混了不同畫風或時期（約 1 成的單一畫師也會落在這裡）",
        "spread": "比 {p}% 的單一畫師分散（和 114 位 Danbooru 畫師比較，每位抽 10 張）",
        "few": "圖太少（少於 10 張），不判斷一致性。",
        "looks": "外觀（和 278 位 Danbooru 畫師各自的平均外觀比較）",
        "than": "比 {p}% 的畫師{w}",
        "artists": "最像的畫師（參考圖庫）",
        "groups": "畫風群",
        "group": "畫風",
        "from": "來自：",
        "when": "時間位置：中位數在作品時間軸的 {m}%（中間一半 {a}%–{b}%；0% 最早）",
        "note": "畫風向量：CSD ViT-L（Somepalli 等，2024，CC-BY-4.0）。外觀數字是 256 px "
        "縮圖上的影像統計。",
    },
    "en": {
        "images": "images",
        "made": "Made",
        "intro": "This page shows, in order: how consistent the style is, how it looks next to "
        "Danbooru artists, which sub-folders draw alike (when there are any), and the style groups "
        "found automatically. The numbers describe how styles differ, not which is better.",
        "ends_consistency": ("very consistent", "very spread"),
        "consist_folders": "This folder has {n} sub-folders: the measure treats everything as one "
        "artist, so a collection of several artists is expected to read as spread.",
        "folders": "Sub-folders: which draw alike",
        "folders_sub": "Each sub-folder's (e.g. each artist's) average style, compared with the "
        "others.",
        "closest_to": "Closest: ",
        "family": "Family {k}",
        "alone": "On their own",
        "folders_note": "Families are loose (recomputed on half of each artist's works they agree "
        "only partly): go by the closest names. The artist map shows them in 3D: "
        "style-atlas map --by-folder, or Artist map in the web app.",
        "groups_sub": "Found automatically, largest first; each shows its most typical images, one "
        "of each set of near-duplicates.",
        "copies": "{n} of them fall in {k} sets of near-duplicates (the same picture, crops or "
        "frames of one scene); one of each set is shown",
        "excluded": "{n} excluded images left out",
        "consistency": "Style consistency",
        "tight": "very consistent",
        "like one artist": "in the range of one artist (a mix of two or three often is too)",
        "mixed": "may be a mix of styles or periods (about 1 in 10 single artists also lands here)",
        "spread": "more spread than {p}% of single artists (114 Danbooru artists, 10 works each)",
        "few": "Too few images (under 10) to judge consistency.",
        "looks": "Look (next to the mean look of each of 278 Danbooru artists)",
        "than": "{w} than {p}% of artists",
        "artists": "Closest artists (reference library)",
        "groups": "Style groups",
        "group": "Style",
        "from": "From: ",
        "when": "When: median at {m}% of the timeline (middle half {a}-{b}%; 0% oldest)",
        "note": "Style vectors: CSD ViT-L (Somepalli et al. 2024, CC-BY-4.0). Look numbers are "
        "image statistics on 256 px copies.",
    },
}
RENDER_TEXT = {
    "zh": {
        "title": "LoRA 算圖檢查（{n} 張算圖，和上面的訓練集比）",
        "distance": "畫風距離 {d:.3f}（z {z:.1f}，{v}；p {p}）",
        "verdict": {"same style": "同一畫風", "related": "相關", "clearly different": "明顯不同"},
        "fit": "{k} / {n} 張落在訓練集某一群的範圍內：{v}",
        "batch": {
            "few": "張數太少，不判斷整批（請用 8 張以上）",
            "in": "大致是訓練集的畫風",
            "some": "部分像訓練集",
            "out": "大多不像訓練集",
        },
        "fit_note": "實測：同一畫師沒用到的作品約 61% 落在範圍內，其他畫師約 1%。",
        "no_groups": "訓練集沒有 3 張以上的畫風群，不判斷算圖落在範圍內的比例。",
        "look": "外觀（算圖和訓練集比）：{w}",
        "look_same": "沒有明顯差異",
        "copies": "可能背下的訓練圖：{n} 張算圖和某張訓練圖幾乎一樣"
        "（每組左邊是算圖，右邊是訓練圖）",
        "no_copies": "沒有算圖和訓練圖幾乎一樣。",
        "far": "算圖（最不像訓練集的排前面）",
        "z_note": "z 的尺度來自一位使用者在 NovelAI 算圖上的校準；同一畫風的兩半約為 1。",
    },
    "en": {
        "title": "LoRA renders ({n}, against the training set above)",
        "distance": "Style distance {d:.3f} (z {z:.1f}, {v}; p {p})",
        "verdict": {
            "same style": "same style",
            "related": "related",
            "clearly different": "clearly different",
        },
        "fit": "{k} of {n} fall inside a style group of the training set: {v}",
        "batch": {
            "few": "too few to judge the batch (use 8 or more)",
            "in": "mostly the training set's style",
            "some": "partly the training set's style",
            "out": "mostly unlike the training set",
        },
        "fit_note": "Measured: 61% of an artist's unused works fall inside, 1% of another "
        "artist's.",
        "no_groups": "The training set has no style group of 3 images or more, so the share of "
        "renders inside one is not judged.",
        "look": "Look (renders against the training set): {w}",
        "look_same": "no clear difference",
        "copies": "Possibly memorised: {n} renders nearly repeat a training image (render left, "
        "training image right)",
        "no_copies": "No render repeats a training image.",
        "far": "Renders, least like the training set first",
        "z_note": "The z scale comes from one person's calibration on NovelAI renders; two "
        "halves of one style are about 1 apart.",
    },
}
LOOK_WORDS = {  # next to the reference artists: (above the middle, below it)
    "zh": THAN_ZH,  # "比 67% 的畫師色彩更淡"
    "en": {
        "brightness": ("brighter", "darker"),
        "contrast": ("more contrast", "less contrast"),
        "colourfulness": ("more colourful", "less colourful"),
        "warmth": ("warmer", "cooler"),
        "lines": ("more line work", "less line work"),
        "flatness": ("flatter colour", "more texture"),
    },
}
GROUP_WORDS = {"zh": WORDS_ZH, "en": LOOK_WORDS["en"]}  # a group next to the whole folder


@lru_cache(maxsize=1)
def look_reference() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """(percentiles, measure -> values): the mean look of 278 Danbooru artists."""
    with resources.files("styleatlas").joinpath("data/look_reference.json").open("rb") as f:
        data = json.load(f)
    values = {name: np.asarray(v, dtype=float) for name, v in data["measures"].items()}
    return np.asarray(data["percentiles"], dtype=float), values


def look_percentiles(looks: np.ndarray) -> dict[str, float]:
    """Where the folder's mean look falls among the reference artists (0-100 per measure)."""
    percents, values = look_reference()
    mean = looks.mean(axis=0)
    return {
        name: float(np.interp(mean[j], values[name], percents)) for j, name in enumerate(LOOK_NAMES)
    }


def _thumb(path: Path) -> str:
    try:
        data = cached_thumbnail(path, THUMB_PX)
    except LOAD_ERRORS:
        return ""
    return "data:image/webp;base64," + base64.b64encode(data).decode()


def _words(looks: np.ndarray, members: np.ndarray, lang: str) -> str:
    z = profile(looks, members)
    picked = [j for j in np.argsort(-np.abs(z)) if abs(z[j]) >= NOTABLE]
    sep = "、" if lang == "zh" else ", "
    return sep.join(GROUP_WORDS[lang][LOOK_NAMES[j]][0 if z[j] > 0 else 1] for j in picked)


def group_cards(
    atlas: Atlas,
    clustering: Clustering,
    names: dict[int, str],
    lang: str,
    pos: np.ndarray | None = None,
) -> list:
    """One card per group, largest first: name, size, look words, typical tags, where it sits in
    the timeline (given positions `pos`), thumbnails of its most typical images."""
    tags = distinctive_tags(tag_summary(atlas.paths, clustering))
    folders = labels_from_folders(atlas.paths, atlas.root)
    several = len(set(folders)) > 1  # images directly in the root count as ""
    dups = near_duplicate_groups(atlas.style, atlas.content)
    copy_set = {i: g for g, group in enumerate(dups) for i in group}
    cards = []
    for c in sorted(clustering.clusters, key=lambda c: -c.size):
        members = np.asarray(c.members)
        typical = members[np.argsort(-(atlas.style[members] @ centroid(atlas.style[members])))]
        shown = _one_of_each(typical, copy_set)[:THUMBS]
        cards.append(
            {
                "name": names.get(c.id) or f"{TEXT[lang]['group']} {c.id + 1}",
                "size": int(c.size),
                "words": _words(atlas.looks, members, lang) if atlas.looks is not None else "",
                "tags": tags.get(c.id, []),
                "when": timeline_span(pos, members),
                "from": folder_mix([folders[i] for i in members]) if several else [],
                "copies": _copies_in(members, dups),
                "thumbs": [s for s in (_thumb(atlas.paths[i]) for i in shown) if s],
            }
        )
    return cards


def _one_of_each(order: np.ndarray, copy_set: dict[int, int]) -> list[int]:
    """`order` without the later images of each set of near-duplicates."""
    seen: set[int] = set()
    out = []
    for i in order.tolist():
        key = copy_set.get(i, -1 - i)  # an image without near-duplicates is a set of its own
        if key not in seen:
            out.append(i)
            seen.add(key)
    return out


def _copies_in(members: np.ndarray, dups: list[list[int]]) -> tuple[int, int]:
    """(images, sets): the group's images that have a near-duplicate inside the group (as the
    web app counts them), and how many sets of near-duplicates they form."""
    inside = set(members.tolist())
    counts = [n for n in (sum(i in inside for i in group) for group in dups) if n >= 2]
    return sum(counts), len(counts)


def _folder_section(atlas: Atlas, t: dict, lang: str) -> str:
    """Which sub-folders (e.g. artists) draw alike: each one's closest others by average style,
    and the families the artist map makes (plain CSD, as the cut was measured)."""
    labels = labels_from_folders(atlas.paths, atlas.root)
    names = sorted(set(labels) - {""})  # folder_atlas's order
    if len(names) < MIN_FOLDERS:
        return ""
    means = folder_atlas(atlas)
    sizes = Counter(labels)
    sims = means.style @ means.style.T
    np.fill_diagonal(sims, -np.inf)
    e, sep = html.escape, "、" if lang == "zh" else ", "
    rows = []
    for k, name in enumerate(names):
        closest = sep.join(names[j] for j in np.argsort(-sims[k])[:FOLDER_NEIGHBOURS])
        rows.append(
            f'<tr><td><img class="mini" src="{_thumb(means.paths[k])}" alt=""></td>'
            f'<td>{e(name)} <span class="sub">{sizes[name]} {t["images"]}</span></td>'
            f"<td>{e(t['closest_to'] + closest)}</td></tr>"
        )
    families = cluster_styles(means.style, threshold=FAMILY_CUT, min_size=2)
    lines = [
        f"{t['family'].format(k=n + 1)}{'：' if lang == 'zh' else ': '}"
        + sep.join(names[i] for i in c.members)
        for n, c in enumerate(sorted(families.clusters, key=lambda c: -c.size))
    ]
    alone = [names[i] for i in np.flatnonzero(families.labels == UNASSIGNED)]
    if alone:
        lines.append(f"{t['alone']}{'：' if lang == 'zh' else ': '}{sep.join(alone)}")
    return (
        f'<section><h2>{t["folders"]}</h2><p class="sub">{e(t["folders_sub"])}</p>'
        f'<table class="folders">{"".join(rows)}</table>'
        + "".join(f"<p>{e(line)}</p>" for line in lines)
        + f'<p class="sub">{e(t["folders_note"])}</p></section>'
    )


FOLDERS_SHOWN = 3  # sub-folders named per group, most images first


def folder_mix(folders: list[str]) -> list[tuple[str, int]]:
    """(sub-folder, images) for a group's images, most first, at most FOLDERS_SHOWN; images
    directly in the root show as "."."""
    return [(f or ".", n) for f, n in Counter(folders).most_common(FOLDERS_SHOWN)]


def _bar(percent: float, ends: tuple[str, str] = ("", "")) -> str:
    """A 0-100 scale with a mark, and what its left and right ends mean."""
    bar = f'<div class="bar"><span style="left:{percent:.0f}%"></span></div>'
    if not any(ends):
        return bar
    left, right = (html.escape(end) for end in ends)
    return f'{bar}<div class="ends"><span>{left}</span><span>{right}</span></div>'


def _consistency_section(atlas: Atlas, t: dict) -> str:
    tight = consistency(atlas.style)
    if tight is None:
        return f"<section><h2>{t['consistency']}</h2><p>{t['few']}</p></section>"
    spread = t["spread"].format(p=round(tight.percentile))
    scale = _bar(tight.percentile, t["ends_consistency"])
    body = f"<p><b>{t[tight.verdict]}</b> · {spread}</p>{scale}"
    folders = len(set(labels_from_folders(atlas.paths, atlas.root)) - {""})
    if folders >= 2:  # a collection: spread by design
        body += f'<p class="sub">{html.escape(t["consist_folders"].format(n=folders))}</p>'
    return f"<section><h2>{t['consistency']}</h2>{body}</section>"


def _looks_section(looks: np.ndarray, t: dict, lang: str) -> str:
    rows = []
    for name, p in look_percentiles(looks).items():
        up, down = LOOK_WORDS[lang][name]
        text = t["than"].format(p=round(max(p, 100 - p)), w=up if p >= 50 else down)
        high, low = GROUP_WORDS[lang][name]
        rows.append(f"<tr><td>{html.escape(text)}</td><td>{_bar(p, (low, high))}</td></tr>")
    return f"<section><h2>{t['looks']}</h2><table>{''.join(rows)}</table></section>"


def _renders_section(check: RenderCheck, train: Atlas, lang: str) -> str:
    """The LoRA render check: distance, fit share, look change, memorised pairs, the farthest."""
    r, e = RENDER_TEXT[lang], html.escape
    n = len(check.renders)
    p = "< 0.01" if check.p < 0.01 else f"{check.p:.2f}"
    verdict = r["verdict"].get(check.verdict, check.verdict)
    lines = [r["distance"].format(d=check.distance, z=check.z, v=verdict, p=p)]
    if check.fits:  # empty when no training group has 3 images or more
        reading = r["batch"][batch_verdict(check.fitting / n, n)]
        lines.append(r["fit"].format(k=check.fitting, n=n, v=reading))
    else:
        lines.append(r["no_groups"])
    if check.look is not None:
        lines.append(r["look"].format(w=_look_change(check.look, lang) or r["look_same"]))
    out = [f"<section><h2>{e(r['title'].format(n=n))}</h2>"]
    out += [f"<p>{e(line)}</p>" for line in lines]
    out.append(f'<p class="sub">{e(r["fit_note"])} {e(r["z_note"])}</p>')
    if check.copies:
        out.append(f"<h3>{e(r['copies'].format(n=len(check.copies)))}</h3>")
        pairs = [(check.renders.paths[i], train.paths[j]) for i, j, _ in check.copies]
        cells = "".join(f'<div class="pair">{_imgs(pair)}</div>' for pair in pairs[:RENDER_THUMBS])
        out.append(f'<div class="thumbs">{cells}</div>')
    else:
        out.append(f"<p>{e(r['no_copies'])}</p>")
    if check.fits:
        farthest = np.argsort([-f.dist for f in check.fits])[:RENDER_THUMBS]
        out.append(f"<h3>{e(r['far'])}</h3>")
        out.append(_thumb_grid([check.renders.paths[i] for i in farthest]))
    return "".join(out) + "</section>"


def _look_change(z: np.ndarray, lang: str) -> str:
    """The renders next to the training set: "更亮、線條更少" (a comparison, so the 更 form)."""
    picked = [j for j in np.argsort(-np.abs(z)) if abs(z[j]) >= NOTABLE]
    sep = "、" if lang == "zh" else ", "
    return sep.join(LOOK_WORDS[lang][LOOK_NAMES[j]][0 if z[j] > 0 else 1] for j in picked)


def _imgs(paths) -> str:
    return "".join(f'<img src="{s}" alt="">' for s in (_thumb(p) for p in paths) if s)


def _thumb_grid(paths: list) -> str:
    return f'<div class="thumbs">{_imgs(paths)}</div>'


def _group_section(cards: list, t: dict) -> str:
    e = html.escape
    out = [f'<section><h2>{t["groups"]}</h2><p class="sub">{e(t["groups_sub"])}</p>']
    for card in cards:
        imgs = "".join(f'<img src="{src}" alt="">' for src in card["thumbs"])
        size = f'<span class="sub">{card["size"]} {t["images"]}</span>'
        when = ""
        if card.get("when"):
            q1, med, q3 = card["when"]
            text = t["when"].format(m=round(100 * med), a=round(100 * q1), b=round(100 * q3))
            when = f'<p class="sub">{e(text)}</p>'
        source = ""
        if card.get("from"):
            mix = " · ".join(f"{f} {n}" for f, n in card["from"])
            source = f'<p class="sub">{e(t["from"])}{e(mix)}</p>'
        copies = ""
        n, k = card.get("copies", (0, 0))
        if n:
            copies = f'<p class="sub">{e(t["copies"].format(n=n, k=k))}</p>'
        out.append(
            f'<div class="card"><h3>{e(card["name"])} {size}</h3><p>{e(card["words"])}</p>'
            f'{source}<p class="sub">{e(", ".join(card["tags"]))}</p>{when}{copies}'
            f'<div class="thumbs">{imgs}</div></div>'
        )
    return "".join(out) + "</section>"


def render(
    atlas: Atlas,
    clustering: Clustering,
    title: str,
    names: dict[int, str] | None = None,
    closest: list[tuple[str, float]] | None = None,
    lang: str = "zh",
    excluded: Collection[int] = (),
    renders: Atlas | None = None,
    time_source: str = "none",
    folders: bool = True,
) -> str:
    """The report page; `closest` is (folder, score) of the nearest reference artists.
    `excluded` images (excluded by hand in the web app) are left out of every number. With
    `renders` (e.g. a LoRA's test images), a section checks them against this training set.
    `folders` adds which sub-folders draw alike (plain CSD vectors only: the families' cut was
    measured there)."""
    t, e = TEXT[lang], html.escape
    skip = set(excluded)
    if skip:
        kept = [i for i in range(len(atlas)) if i not in skip]
        if not kept:
            raise ValueError(tr("all images are excluded", "所有圖都被排除了"))
        clustering = keep_rows(atlas.style, clustering, kept)
        atlas = atlas.subset(kept)
    sub = f"{len(atlas)} {t['images']} · {t['made']} {date.today()}"
    if skip:
        sub += " · " + t["excluded"].format(n=len(skip))
    parts = [
        f"<h1>{e(title)}</h1>",
        f'<p class="sub">{sub}</p>',
        f"<p>{e(t['intro'])}</p>",
        _consistency_section(atlas, t),
    ]
    if atlas.looks is not None:
        parts.append(_looks_section(atlas.looks, t, lang))
    if renders is not None:
        parts.append(_renders_section(check_renders(atlas, clustering, renders), atlas, lang))
    if closest:
        rows = "".join(f'<li>{e(n)} <span class="sub">{s:.3f}</span></li>' for n, s in closest)
        parts.append(f"<section><h2>{t['artists']}</h2><ol>{rows}</ol></section>")
    if folders:
        parts.append(_folder_section(atlas, t, lang))
    pos = timeline(atlas.paths, time_source)
    parts.append(_group_section(group_cards(atlas, clustering, names or {}, lang, pos), t))
    parts.append(f'<p class="sub note">{e(t["note"])}</p>')
    body = "\n".join(parts)
    fill = {"title": e(title), "lang": "zh-Hant" if lang == "zh" else "en", "body": body}
    # one pass, so a title such as "{body}" stays text
    return PLACEHOLDER.sub(lambda m: fill[m.group(1)], PAGE)


def write_report(atlas: Atlas, clustering: Clustering, out: Path, title: str, **kw) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(atlas, clustering, title, **kw), encoding="utf-8")
    return out


PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root { --bg: #fafaf8; --ink: #1d1f23; --muted: #6b7078; --line: #e2e2de;
    --accent: #c2410c; --panel: #ffffff; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111317; --ink: #e8e8e6; --muted: #9aa0a8; --line: #2a2d33;
      --accent: #f2c38b; --panel: #181b20; }
  }
  body { background: var(--bg); color: var(--ink); margin: 0;
    font: 15px/1.6 system-ui, "Noto Sans TC", sans-serif; }
  main { max-width: 960px; margin: 0 auto; padding: 28px 16px 48px; }
  h1 { font-size: 26px; margin: 0; } h2 { font-size: 17px; margin: 28px 0 8px; }
  h3 { font-size: 15px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; }
  section { border-top: 1px solid var(--line); }
  table { border-collapse: collapse; width: 100%; }
  td { padding: 4px 8px 4px 0; vertical-align: middle; }
  td:first-child { width: 55%; }
  .bar { position: relative; height: 8px; border-radius: 4px; background: var(--line);
    min-width: 120px; }
  .bar span { position: absolute; top: -3px; width: 4px; height: 14px; margin-left: -2px;
    border-radius: 2px; background: var(--accent); }
  .ends { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px;
    margin-top: 2px; }
  .folders td { padding: 3px 10px 3px 0; } .folders td:first-child { width: 52px; }
  img.mini { width: 44px; height: 44px; object-fit: cover; border-radius: 4px; display: block;
    background: var(--line); }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 12px; margin: 10px 0; }
  .card p { margin: 2px 0; }
  .thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 6px; margin-top: 8px; }
  .thumbs img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px;
    background: var(--line); }
  .pair { grid-column: span 2; display: grid; grid-template-columns: 1fr 1fr; gap: 3px;
    padding: 3px; border: 1px solid var(--line); border-radius: 8px; }
  .note { margin-top: 32px; }
</style></head>
<body><main>
{body}
</main></body></html>
"""
