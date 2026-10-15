"""Periods along the timeline: one artist's works, in time order, cut into contiguous periods where
the style changes most (optimal change points), with two tests:

- time:  are the periods more distinct than cuts of the same works in shuffled time order? (does
  the style depend on time at all)
- turns: are they more distinct than cuts of the same smooth trend with its residuals shuffled?
  (does the style turn at some points, rather than only drift smoothly). Smooth drift alone passes
  the first test, so only the second says that the periods are eras worth training apart.

Both use the same cuts the user sees, on the distinct works (near-duplicates counted once).
docs/BENCHMARKS.md, "Periods along the timeline", has the measurements."""

from __future__ import annotations

import numpy as np

from styleatlas.cluster import UNASSIGNED, Clustering, _info

TIMELINE = "timeline"
SEGMENT_MIN = 5  # works per period at least
SEGMENT_DIMS = 32  # PCA dimensions the cuts are searched and tested in
SEGMENT_MAX = 1500  # distinct works the cuts are searched on (evenly through time); the rest follow
TEST_ROUNDS = 99  # rounds of each null; p is at least 0.01
TEST_SAMPLE = 400  # distinct works the tests use at most (evenly through time)
TEST_MIN = 20  # distinct works the tests need at least (and 2 per period's minimum)
TREND_DEGREE = 2  # the smooth trend kept in the turns test: a curve over time, no steps
CLEAR_P = 0.05


def cluster_timeline(
    style: np.ndarray,
    times: np.ndarray,
    k: int,
    min_size: int = SEGMENT_MIN,
    content: np.ndarray | None = None,
    seed: int = 0,
    plain: np.ndarray | None = None,
) -> Clustering:
    """Periods 0 (earliest) .. k-1 of the images with a known time (`times`, NaN when unknown, e.g.
    from images.timeline); the rest are unassigned. With `content`, near-duplicates count once:
    variants posted one after another would otherwise make cuts look real. They are judged on
    `plain` (the plain style vectors, when `style` is in another space), else on `style`.
    params: n_clusters, distinct, p_time, p_turns (None when too few distinct works), separation
    (silhouette of the periods on the tested works) and tied (share of works whose time equals
    another's)."""
    times = np.asarray(times, dtype=float)
    known = np.flatnonzero(np.isfinite(times))
    order = known[np.argsort(times[known], kind="stable")]
    min_size = max(1, min_size)
    if len(order) < k * min_size:
        from styleatlas.lang import tr

        raise ValueError(
            tr(
                f"{k} periods need at least {k * min_size} images with a time "
                f"({len(order)} have one)",
                f"分成 {k} 個時期至少要 {k * min_size} 張有時間資訊的圖（目前 {len(order)} 張）",
            )
        )
    style_t = np.asarray(style)[order]
    content_t = None if content is None else np.asarray(content)[order]
    distinct = _distinct(np.asarray(style if plain is None else plain)[order], content_t)
    n_distinct = len(distinct)
    if n_distinct < k * min_size:  # mostly copies of a few pictures: cut them as they are
        distinct = np.arange(len(order))
    z = _reduce(np.asarray(style_t, dtype=np.float64)[distinct])
    search = _even(len(z), SEGMENT_MAX)
    cuts_distinct = _follow(search, segment(z[search], k, min_size), len(z))
    labels = np.full(len(style), UNASSIGNED, dtype=int)
    labels[order] = _follow(distinct, cuts_distinct, len(order))  # copies take their time's period
    clusters = [_info(style, c, np.flatnonzero(labels == c)) for c in range(k)]
    tested = _even(len(z), TEST_SAMPLE)
    p_time = p_turns = None  # too few distinct works for either test to mean much
    if n_distinct >= max(2 * k * min_size, TEST_MIN):
        p_time, p_turns = _tests(z[tested], cuts_distinct[tested], k, min_size, seed)
    params = {
        "n_clusters": k,
        "distinct": n_distinct,
        "p_time": p_time,
        "p_turns": p_turns,
        "separation": round(_separation(z[tested], cuts_distinct[tested]), 3),
        "tied": round(1.0 - len(np.unique(times[order])) / len(order), 2),
    }
    return Clustering(labels, clusters, TIMELINE, params)


def verdict(params: dict) -> str:
    """One of: few (too few distinct works to test), none (the style does not follow time),
    drift (it changes smoothly, no clear turns) or turns (eras worth training apart)."""
    if params.get("p_time") is None:
        return "few"
    if params["p_time"] >= CLEAR_P:
        return "none"
    return "turns" if params["p_turns"] < CLEAR_P else "drift"


def verdict_text(params: dict) -> str:
    """The verdict in words, for the command line (the web app has its own copy in map_i18n.js)."""
    from styleatlas.lang import tr

    p, q, sep = params.get("p_time"), params.get("p_turns"), params["separation"]
    n = params.get("distinct")
    text = {
        "few": tr(
            f"too few distinct works to test the periods ({n} once near-duplicates count once): "
            "judge them by eye in the map",
            f"去掉近重複後只有 {n} 張作品，太少，無法檢定各時期：請在地圖上直接看圖判斷",
        ),
        "none": tr(
            f"the style does not follow time here (p {p}): the periods are arbitrary cuts; "
            "one LoRA for all",
            f"畫風和時間沒有明顯關係（p {p}）：這些時期只是任意切點，合在一起訓練即可",
        ),
        "drift": tr(
            f"the style changes gradually over time (p {p}) but has no clear turning point "
            f"(turns p {q}): the cuts split a smooth drift. One LoRA for all usually works; to "
            "get one period's look, keep only that period",
            f"畫風隨時間慢慢變（p {p}），但沒有明確的轉折點（轉折 p {q}）："
            "切點只是把連續的變化切開。通常合在一起訓練即可；想要某個時期的畫風，就只留那一段",
        ),
        "turns": tr(
            f"the style turns at clear points (turns p {q}, separation {sep:+.3f}): the periods "
            "are distinct eras; training them separately can make sense",
            f"畫風在某些時間點有明確的轉折（轉折 p {q}，分離度 {sep:+.3f}）：各時期是不同階段，"
            "分開訓練有道理",
        ),
    }[verdict(params)]
    if params.get("tied", 0) >= TIED_NOTE:
        text += tr(
            f" ({params['tied']:.0%} of the images share a time with another; their order "
            "within it is arbitrary)",
            f"（{params['tied']:.0%} 的圖和別張時間相同，同一時間內的先後是任意的）",
        )
    return text


TIED_NOTE = 0.2  # share of tied times from which the verdict mentions them


def segment(z: np.ndarray, k: int, min_size: int) -> np.ndarray:
    """Labels 0..k-1 for the rows of `z` (in time order): the contiguous split with the least
    within-period squared distance to the period's mean (dynamic programming)."""
    n = len(z)
    z = z - z.mean(axis=0)  # keeps the running sums small, so the expansion below stays exact
    csum = np.vstack([np.zeros(z.shape[1]), np.cumsum(z, axis=0)])
    csq = np.concatenate([[0.0], np.cumsum((z * z).sum(axis=1))])
    sq = (csum * csum).sum(axis=1)
    ends = np.arange(n + 1)
    length = ends[None, :] - ends[:, None]  # [a, b]: works a..b-1
    with np.errstate(divide="ignore", invalid="ignore"):  # cost[a, b] of one period a..b-1
        cost = (
            csq[None, :] - csq[:, None] - (sq[None, :] + sq[:, None] - 2 * csum @ csum.T) / length
        )
    cost[length < min_size] = np.inf
    best = np.full((k + 1, n + 1), np.inf)
    back = np.zeros((k + 1, n + 1), dtype=int)
    best[0, 0] = 0.0
    for j in range(1, k + 1):
        total = best[j - 1][:, None] + cost
        back[j] = np.argmin(total, axis=0)
        best[j] = total[back[j], ends]
    labels = np.empty(n, dtype=int)
    b = n
    for j in range(k, 0, -1):
        a = back[j, b]
        labels[a:b] = j - 1
        b = a
    return labels


def _distinct(style: np.ndarray, content: np.ndarray | None) -> np.ndarray:
    """Positions (in time order) of the works kept once per near-duplicate group."""
    if content is None:
        return np.arange(len(style))
    from styleatlas.duplicates import keep_one_per_group, near_duplicate_groups

    groups = near_duplicate_groups(style, content)
    return np.sort(np.asarray(keep_one_per_group(len(style), groups), dtype=int))


def _even(n: int, at_most: int) -> np.ndarray:
    """At most `at_most` positions of 0..n-1, evenly spread (all of them when n is small)."""
    return np.arange(n) if n <= at_most else np.linspace(0, n - 1, at_most).round().astype(int)


def _follow(positions: np.ndarray, labels: np.ndarray, n: int) -> np.ndarray:
    """Labels for all of 0..n-1 from the labels at sorted `positions`: each takes the label of the
    last labelled position at or before it (positions before the first take the first label), so
    periods stay contiguous in time."""
    slot = np.searchsorted(positions, np.arange(n), side="right") - 1
    return labels[np.clip(slot, 0, len(positions) - 1)]


def _reduce(x: np.ndarray) -> np.ndarray:
    from sklearn.decomposition import PCA

    dims = min(SEGMENT_DIMS, len(x) - 1, x.shape[1])
    return PCA(n_components=dims, random_state=0).fit_transform(x) if dims >= 1 else x


def _separation(z: np.ndarray, labels: np.ndarray) -> float:
    """How distinct the periods are: their silhouette (-1..1; 0 = not at all)."""
    from sklearn.metrics import silhouette_score

    return float(silhouette_score(z, labels)) if len(set(labels.tolist())) > 1 else 0.0


def _tests(z: np.ndarray, cuts: np.ndarray, k: int, min_size: int, seed: int) -> tuple:
    """(p_time, p_turns) of the cuts on the works `z` (in time order)."""
    observed = _separation(z, cuts)
    rng = np.random.default_rng(seed)
    trend, resid = _smooth_trend(z)
    hits_time = hits_turns = 0
    for _ in range(TEST_ROUNDS):
        shuffled = z[rng.permutation(len(z))]
        hits_time += _separation(shuffled, segment(shuffled, k, min_size)) >= observed
        drifting = trend + resid[rng.permutation(len(z))]
        hits_turns += _separation(drifting, segment(drifting, k, min_size)) >= observed
    p_time = (1 + hits_time) / (1 + TEST_ROUNDS)
    p_turns = (1 + hits_turns) / (1 + TEST_ROUNDS)
    return round(p_time, 3), round(p_turns, 3)


def _smooth_trend(z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The smooth part of the style's course (a low-degree polynomial of the time rank, per
    dimension) and what is left over."""
    t = np.linspace(-1.0, 1.0, len(z))
    basis = np.vander(t, TREND_DEGREE + 1)
    coef, *_ = np.linalg.lstsq(basis, z, rcond=None)
    trend = basis @ coef
    return trend, z - trend
