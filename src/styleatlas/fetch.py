"""Downloads from the fastest of several sources (the original and its mirrors), switching when the
one in use stalls or crawls.

Every file fetched this way has a known SHA256, so a mirror can only hand over the exact file: a
download that does not match is thrown away. Standard library only and no other styleatlas
import: the packaged program's launcher loads this file by its path to choose where pip
downloads from, before anything else is installed."""

from __future__ import annotations

import hashlib
import html
import http.client
import os
import re
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

USER_AGENT = "style-atlas"
PROBE_BYTES = 4 * 1024 * 1024  # read from each source to measure it
PROBE_SECONDS = 8.0  # a source slower than this to answer counts as unreachable
STALL_SECONDS = 20  # no data for this long: the source has stalled
CHUNK = 1024 * 1024
SLOW_AFTER = 30.0  # seconds on one source before it may be judged slow
SLOW_SHARE = 0.25  # slow: under this share of what another source measured
ROUNDS = 3  # passes over all sources without progress before giving up
ROUND_PAUSE = 3.0  # seconds to wait after a pass where every source failed (grows)
NETWORK_ERRORS = (OSError, http.client.HTTPException, ValueError)

Progress = Callable[[int, int, str], None]  # (bytes done, bytes total, host in use)


class FetchError(Exception):
    """No source could deliver the file (each one's reason is in the message)."""


class _Slow(Exception):
    """The source in use is much slower than another one measured."""

    def __init__(self, rate: float):
        super().__init__("much slower than another source")
        self.rate = rate


def host(url: str) -> str:
    return urlsplit(url).netloc or url


def _open(url: str, offset: int = 0, timeout: float | None = None):
    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(request, timeout=STALL_SECONDS if timeout is None else timeout)


def file_speed(url: str, started: float | None = None) -> float:
    """Bytes per second reading the first PROBE_BYTES of `url`, timed from its first data (the
    wait for a connection says little about a download of gigabytes); 0 when it does not answer
    within PROBE_SECONDS of `started` (when finding the file came first) or of now."""
    start = time.monotonic() if started is None else started
    deadline = start + PROBE_SECONDS
    got = first = 0
    first_at = None
    try:
        with _open(url, timeout=PROBE_SECONDS) as response:
            while got < PROBE_BYTES and time.monotonic() < deadline:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                if first_at is None:
                    first_at, first = time.monotonic(), len(chunk)
                got += len(chunk)
    except NETWORK_ERRORS:
        return 0.0
    if first_at is None or got == first:  # one chunk alone cannot be timed
        return got / max(time.monotonic() - start, 1e-3)
    return (got - first) / max(time.monotonic() - first_at, 1e-3)


def index_speed(index: str, package: str, wanted: Callable[[str], bool]) -> float:
    """file_speed of one of `package`'s files on the pip index `index` whose name `wanted`
    accepts, the time to read the index page included; 0 when the index does not answer."""
    start = time.monotonic()
    try:
        with _open(f"{index.rstrip('/')}/{package}/", timeout=PROBE_SECONDS) as response:
            page = response.read(8 * 1024 * 1024).decode("utf-8", "replace")
            base = response.geturl()
    except NETWORK_ERRORS:
        return 0.0
    links = [html.unescape(m) for m in re.findall(r'href="([^"]+)"', page)]
    files = [link for link in links if wanted(unquote(link.split("#")[0].rsplit("/", 1)[-1]))]
    urls = [urljoin(base, link.split("#")[0]) for link in files]
    urls = [url for url in urls if urlsplit(url).scheme in ("http", "https")]
    return file_speed(urls[-1], started=start) if urls else 0.0


def ranked(sources: list[str], measure: Callable[[str], float]) -> list[tuple[str, float]]:
    """Each source with its speed in bytes per second, fastest first, measured in parallel. Ties
    keep the given order, so the original wins over a mirror that is no faster."""
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
        speeds = list(pool.map(measure, sources))
    return sorted(zip(sources, speeds, strict=True), key=lambda pair: -pair[1])


def describe(ranking: list[tuple[str, float]], none: str = "no answer") -> str:
    """'hf-mirror.com 12.3 MB/s · huggingface.co 0.4 MB/s', for the progress lines."""
    return " · ".join(
        f"{host(url)} {speed / 1e6:.1f} MB/s" if speed else f"{host(url)} {none}"
        for url, speed in ranking
    )


def download(
    ranking: list[tuple[str, float]], dest: Path, sha256: str, size: int, progress: Progress
) -> None:
    """Fetch one file of known `size` and `sha256` to `dest` from the sources in `ranking` (the
    same file at each URL, fastest first). A `.part` file left by an earlier try is continued; a
    stalled, failing or much slower source hands over to the next one at the same byte."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest, offset = _resume(part, size)
    order = [url for url, _ in ranking]
    speeds = dict(ranking)
    errors: dict[str, str] = {}
    current = failures = 0
    while offset < size:
        url = order[current % len(order)]
        best_other = max((s for u, s in speeds.items() if u != url), default=0.0)
        before = offset
        try:
            offset = _pull(url, part, offset, size, digest, progress, best_other)
            if offset < size:
                raise ConnectionError("the connection ended early")
        except (*NETWORK_ERRORS, _Slow) as e:
            errors[host(url)] = str(e)
            # what it really does, so a stalled fast source does not make the others look slow
            speeds[url] = e.rate if isinstance(e, _Slow) else 0.0
            offset = part.stat().st_size if part.exists() else 0
            current += 1
        failures = 0 if offset > before else failures + 1
        if failures >= ROUNDS * len(order):
            detail = "; ".join(f"{h}: {why}" for h, why in errors.items())
            raise FetchError(f"no source could deliver {dest.name} ({detail})")
        if failures and failures % len(order) == 0:  # a network blip: give it a moment
            time.sleep(ROUND_PAUSE * failures // len(order))
    if digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise FetchError(f"{dest.name} did not match its SHA256 and was thrown away")
    os.replace(part, dest)


def _hash_file(path: Path) -> hashlib._Hash:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK * 8):
            digest.update(chunk)
    return digest


def sha256_of(path: Path) -> str:
    return _hash_file(path).hexdigest()


def _resume(part: Path, size: int) -> tuple[hashlib._Hash, int]:
    """The SHA256 so far and the byte to go on from, for a `.part` of an earlier try."""
    if not part.exists() or part.stat().st_size > size:
        part.unlink(missing_ok=True)
        return hashlib.sha256(), 0
    return _hash_file(part), part.stat().st_size


def _bytes_to_skip(response, offset: int, size: int) -> int:
    """How much of the response comes before `offset` (a source that ignored Range), after making
    sure it is the file: an error or login page must not end up in the download."""
    length = response.headers.get("Content-Length")
    if response.headers.get_content_type() == "text/html":
        raise ValueError("sent a web page instead of the file")
    if response.status == 206:
        start = (response.headers.get("Content-Range") or "").removeprefix("bytes ").split("-")[0]
        if start != str(offset):
            raise ValueError(f"answered from byte {start or '?'} instead of {offset}")
        expected, skip = size - offset, 0
    elif response.status == 200:
        expected, skip = size, offset
    else:
        raise ValueError(f"answered {response.status}")
    if length is not None and int(length) != expected:
        raise ValueError(f"sent {length} bytes where {expected} were expected")
    return skip


def _pull(
    url: str,
    part: Path,
    offset: int,
    size: int,
    digest: hashlib._Hash,
    progress: Progress,
    best_other: float,
) -> int:
    """Append to `part` from `url` starting at `offset`; returns the bytes held when the source
    ends. Raises _Slow when, after SLOW_AFTER seconds, it runs under SLOW_SHARE of `best_other`."""
    with _open(url, offset) as response:
        skip = _bytes_to_skip(response, offset, size)
        started, start_offset = time.monotonic(), offset
        with open(part, "ab") as out:
            while offset < size:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                if skip:
                    dropped = min(skip, len(chunk))
                    chunk, skip = chunk[dropped:], skip - dropped
                chunk = chunk[: size - offset]
                out.write(chunk)
                digest.update(chunk)
                offset += len(chunk)
                progress(offset, size, host(url))
                elapsed = time.monotonic() - started
                rate = (offset - start_offset) / max(elapsed, 1e-3)
                if elapsed > SLOW_AFTER and rate < SLOW_SHARE * best_other:
                    raise _Slow(rate)
    return offset
