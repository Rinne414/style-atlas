"""A one-page style report for a folder (`style-atlas report`): how consistent its style is, how
it looks next to Danbooru artists, which artists of a reference library it is closest to, and
its style groups with their most typical images. One HTML file with the thumbnails inside, to
keep or send."""

from __future__ import annotations

import base64
import html
import json
import re
from collections.abc import Collection
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path

import numpy as np

from styleatlas.atlas import LOAD_ERRORS, Atlas
from styleatlas.cluster import Clustering, keep_rows
from styleatlas.consistency import consistency
from styleatlas.dataset import distinctive_tags, tag_summary
from styleatlas.images import cached_thumbnail
from styleatlas.look import LOOK_NAMES, NOTABLE, profile
from styleatlas.metrics import centroid

THUMBS = 6  # most typical images shown per group
THUMB_PX = 160
PLACEHOLDER = re.compile(r"\{(title|lang|body)\}")

TEXT = {
    "zh": {
        "images": "張圖",
        "made": "製作日期",
        "excluded": "另有 {n} 張已排除，不算在內",
        "consistency": "畫風一致性",
        "tight": "很一致",
        "like one artist": "在一位畫師的正常範圍內",
        "mixed": "多半混了不同畫風或時期",
        "spread": "比 {p}% 的單一畫師分散（和 114 位 Danbooru 畫師比較）",
        "few": "圖太少（少於 10 張），不判斷一致性。",
        "looks": "外觀（和 278 位 Danbooru 畫師的平均比較）",
        "than": "比 {p}% 的畫師{w}",
        "artists": "最像的畫師（參考圖庫）",
        "groups": "畫風群",
        "group": "畫風",
        "note": "畫風向量：CSD ViT-L（Somepalli 等，2024，CC-BY-4.0）。外觀數字是 256 px "
        "縮圖上的影像統計，描述畫風怎麼不同，不評好壞。",
    },
    "en": {
        "images": "images",
        "made": "Made",
        "excluded": "{n} excluded images left out",
        "consistency": "Style consistency",
        "tight": "very consistent",
        "like one artist": "in the range of one artist",
        "mixed": "probably a mix of styles or periods",
        "spread": "more spread than {p}% of single artists (114 Danbooru artists)",
        "few": "Too few images (under 10) to judge consistency.",
        "looks": "Look (next to the means of 278 Danbooru artists)",
        "than": "{w} than {p}% of artists",
        "artists": "Closest artists (reference library)",
        "groups": "Style groups",
        "group": "Style",
        "note": "Style vectors: CSD ViT-L (Somepalli et al. 2024, CC-BY-4.0). Look numbers are "
        "image statistics on 256 px copies; they describe how styles differ, not which is better.",
    },
}
LOOK_WORDS = {  # next to the reference artists: (above the middle, below it)
    "zh": {
        "brightness": ("亮", "暗"),
        "contrast": ("對比強", "對比弱"),
        "colourfulness": ("鮮豔", "淡"),
        "warmth": ("暖", "冷"),
        "lines": ("線條多", "線條少"),
        "flatness": ("色塊平", "質感多"),
    },
    "en": {
        "brightness": ("brighter", "darker"),
        "contrast": ("more contrast", "less contrast"),
        "colourfulness": ("more colourful", "less colourful"),
        "warmth": ("warmer", "cooler"),
        "lines": ("more line work", "less line work"),
        "flatness": ("flatter colour", "more texture"),
    },
}
GROUP_WORDS = {  # one group next to the whole folder, worded as on the web page
    "zh": {
        "brightness": ("偏亮", "偏暗"),
        "contrast": ("對比強", "對比弱"),
        "colourfulness": ("色彩鮮豔", "色彩淡"),
        "warmth": ("偏暖", "偏冷"),
        "lines": ("線條多", "線條少"),
        "flatness": ("色塊平", "質感多"),
    },
    "en": LOOK_WORDS["en"],
}


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


def group_cards(atlas: Atlas, clustering: Clustering, names: dict[int, str], lang: str) -> list:
    """One card per group, largest first: name, size, look words, typical tags, thumbnails of
    its most typical images (closest to the group's centre)."""
    tags = distinctive_tags(tag_summary(atlas.paths, clustering))
    cards = []
    for c in sorted(clustering.clusters, key=lambda c: -c.size):
        members = np.asarray(c.members)
        typical = members[np.argsort(-(atlas.style[members] @ centroid(atlas.style[members])))]
        cards.append(
            {
                "name": names.get(c.id) or f"{TEXT[lang]['group']} {c.id + 1}",
                "size": int(c.size),
                "words": _words(atlas.looks, members, lang) if atlas.looks is not None else "",
                "tags": tags.get(c.id, []),
                "thumbs": [s for s in (_thumb(atlas.paths[i]) for i in typical[:THUMBS]) if s],
            }
        )
    return cards


def _bar(percent: float) -> str:
    return f'<div class="bar"><span style="left:{percent:.0f}%"></span></div>'


def _consistency_section(atlas: Atlas, t: dict) -> str:
    tight = consistency(atlas.style)
    if tight is None:
        return f"<section><h2>{t['consistency']}</h2><p>{t['few']}</p></section>"
    spread = t["spread"].format(p=round(tight.percentile))
    body = f"<p><b>{t[tight.verdict]}</b> · {spread}</p>{_bar(tight.percentile)}"
    return f"<section><h2>{t['consistency']}</h2>{body}</section>"


def _looks_section(looks: np.ndarray, t: dict, lang: str) -> str:
    rows = []
    for name, p in look_percentiles(looks).items():
        up, down = LOOK_WORDS[lang][name]
        text = t["than"].format(p=round(max(p, 100 - p)), w=up if p >= 50 else down)
        rows.append(f"<tr><td>{html.escape(text)}</td><td>{_bar(p)}</td></tr>")
    return f"<section><h2>{t['looks']}</h2><table>{''.join(rows)}</table></section>"


def _group_section(cards: list, t: dict) -> str:
    e = html.escape
    out = [f"<section><h2>{t['groups']}</h2>"]
    for card in cards:
        imgs = "".join(f'<img src="{src}" alt="">' for src in card["thumbs"])
        size = f'<span class="sub">{card["size"]} {t["images"]}</span>'
        out.append(
            f'<div class="card"><h3>{e(card["name"])} {size}</h3><p>{e(card["words"])}</p>'
            f'<p class="sub">{e(", ".join(card["tags"]))}</p><div class="thumbs">{imgs}</div></div>'
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
) -> str:
    """The report page; `closest` is (folder, score) of the nearest reference artists.
    `excluded` images (excluded by hand in the web app) are left out of every number."""
    t, e = TEXT[lang], html.escape
    skip = set(excluded)
    if skip:
        kept = [i for i in range(len(atlas)) if i not in skip]
        if not kept:
            raise ValueError("all images are excluded")
        clustering = keep_rows(atlas.style, clustering, kept)
        atlas = atlas.subset(kept)
    sub = f"{len(atlas)} {t['images']} · {t['made']} {date.today()}"
    if skip:
        sub += " · " + t["excluded"].format(n=len(skip))
    parts = [
        f"<h1>{e(title)}</h1>",
        f'<p class="sub">{sub}</p>',
        _consistency_section(atlas, t),
    ]
    if atlas.looks is not None:
        parts.append(_looks_section(atlas.looks, t, lang))
    if closest:
        rows = "".join(f'<li>{e(n)} <span class="sub">{s:.3f}</span></li>' for n, s in closest)
        parts.append(f"<section><h2>{t['artists']}</h2><ol>{rows}</ol></section>")
    parts.append(_group_section(group_cards(atlas, clustering, names or {}, lang), t))
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
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 12px; margin: 10px 0; }
  .card p { margin: 2px 0; }
  .thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 6px; margin-top: 8px; }
  .thumbs img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px;
    background: var(--line); }
  .note { margin-top: 32px; }
</style></head>
<body><main>
{body}
</main></body></html>
"""
