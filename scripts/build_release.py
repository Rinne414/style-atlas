"""Build the release files into dist/<version>/:

- StyleAtlas-<v>-windows.zip and StyleAtlas-<v>-linux.tar.gz: the program with its own Python
  (python-build-standalone, checked against its published SHA256 sums) and the launcher;
- style-atlas-app-<v>.zip: the code-only update the program downloads (launch.py + app/);
- update.json ({"version", "python"}) and SHA256SUMS.txt over all of them.

    python scripts/build_release.py            # the version in src/styleatlas/__init__.py
    python scripts/build_release.py --as-version 0.44.1   # a test build of the update path

The standalone Python archives are downloaded once into dist/cache."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGING = REPO / "packaging"
PBS_TAG = "20260610"
PYTHON_VERSION = "3.13.14"
PBS_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"
PBS_NAME = "cpython-{v}+{tag}-x86_64-{triple}-install_only_stripped.tar.gz"
PBS = {
    "windows": PBS_NAME.format(v=PYTHON_VERSION, tag=PBS_TAG, triple="pc-windows-msvc"),
    "linux": PBS_NAME.format(v=PYTHON_VERSION, tag=PBS_TAG, triple="unknown-linux-gnu"),
}
TOP = "StyleAtlas"  # the folder inside the zip and the tar.gz
APP_FILES = ("requirements.txt", "requirements-torch.txt", "constraints.txt")
SKIP_PARTS = {"__pycache__"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, target: Path) -> Path:
    if not target.exists():
        print("downloading", url)
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=60) as answer, tmp.open("wb") as out:
            shutil.copyfileobj(answer, out)
        tmp.rename(target)
    return target


def standalone_python(cache: Path, platform: str) -> Path:
    """The python-build-standalone archive for `platform`, checked against SHA256SUMS."""
    cache.mkdir(parents=True, exist_ok=True)
    sums_file = download(PBS_URL + "SHA256SUMS", cache / f"SHA256SUMS-{PBS_TAG}")
    sums = {}
    for line in sums_file.read_text("utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1]] = parts[0]
    name = PBS[platform]
    archive = download(PBS_URL + name.replace("+", "%2B"), cache / name)
    if sha256(archive) != sums.get(name):
        archive.unlink()
        raise SystemExit(f"{name}: SHA256 does not match the published sum; deleted, run again")
    return archive


def app_files(version: str | None) -> list[tuple[str, bytes, int]]:
    """(path inside the package, content, mode) for launch.py, app/ and the root files."""
    files: list[tuple[str, bytes, int]] = []
    src = REPO / "src" / "styleatlas"
    for path in sorted(src.rglob("*")):
        if path.is_dir() or SKIP_PARTS & set(path.parts) or path.suffix == ".pyc":
            continue
        data = path.read_bytes()
        if version and path.name == "__init__.py" and path.parent == src:
            data = re.sub(rb'__version__ = "[^"]+"', f'__version__ = "{version}"'.encode(), data)
        files.append((f"app/styleatlas/{path.relative_to(src).as_posix()}", data, 0o644))
    for name in APP_FILES:
        files.append((f"app/{name}", (PACKAGING / name).read_bytes(), 0o644))
    files.append(("launch.py", (PACKAGING / "launch.py").read_bytes(), 0o755))
    return files


def root_files(platform: str, version: str) -> list[tuple[str, bytes, int]]:
    crlf = platform == "windows"
    readme = (PACKAGING / "README.txt").read_text("utf-8").replace("{version}", version)
    licence = (REPO / "LICENSE").read_text("utf-8")
    files = [("README.txt", readme, 0o644), ("LICENSE.txt", licence, 0o644)]
    starters = (
        ("Style Atlas.bat", "Style Atlas console.bat")
        if crlf
        else ("style-atlas.sh", "style-atlas-cli.sh")
    )
    for name in starters:  # the program, and a console for the style-atlas command
        files.append((name, (PACKAGING / name).read_text("utf-8"), 0o644 if crlf else 0o755))
    out = []
    for name, text, mode in files:
        text = text.replace("\r\n", "\n")
        out.append((name, (text.replace("\n", "\r\n") if crlf else text).encode("utf-8"), mode))
    if not crlf:
        out.append(("style-atlas.png", linux_icon(), 0o644))
    return out


def linux_icon() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    with Image.open(REPO / "src" / "styleatlas" / "data" / "style-atlas.ico") as ico:
        ico.convert("RGBA").save(buf, "PNG")  # an .ico opens at its largest size
    return buf.getvalue()


def build_windows(out: Path, archive: Path, files: list, version: str) -> Path:
    target = out / f"StyleAtlas-{version}-windows.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        with tarfile.open(archive) as tar:
            for member in tar:
                if member.isfile():
                    data = tar.extractfile(member).read()
                    z.writestr(_zip_info(f"{TOP}/{member.name}", 0o644), data)
        for name, data, mode in files:
            z.writestr(_zip_info(f"{TOP}/{name}", mode), data)
    return target


def _zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100000 | mode) << 16
    return info


def build_linux(out: Path, archive: Path, files: list, version: str) -> Path:
    """Members of the standalone Python archive are copied as they are (modes, symlinks)."""
    target = out / f"StyleAtlas-{version}-linux.tar.gz"
    now = int(time.time())
    with tarfile.open(target, "w:gz", compresslevel=6) as dst, tarfile.open(archive) as src:
        for member in src:
            copy = member.replace(name=f"{TOP}/{member.name}", deep=False)
            dst.addfile(copy, src.extractfile(member) if member.isfile() else None)
        for name, data, mode in files:
            info = tarfile.TarInfo(f"{TOP}/{name}")
            info.size, info.mode, info.mtime = len(data), mode, now
            dst.addfile(info, io.BytesIO(data))
    return target


def build_app_zip(out: Path, files: list, version: str) -> Path:
    target = out / f"style-atlas-app-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in files:
            z.writestr(_zip_info(name, mode), data)
    return target


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as-version", help="build as this version (to test the update path)")
    p.add_argument("--only", choices=["windows", "linux", "app"], action="append")
    a = p.parse_args()
    init = (REPO / "src" / "styleatlas" / "__init__.py").read_text("utf-8")
    version = a.as_version or re.search(r'__version__ = "([^"]+)"', init).group(1)
    out = REPO / "dist" / version
    out.mkdir(parents=True, exist_ok=True)
    cache = REPO / "dist" / "cache"
    files = app_files(a.as_version)
    wanted = set(a.only or ["windows", "linux", "app"])
    made = []
    if "windows" in wanted:
        archive = standalone_python(cache, "windows")
        made.append(build_windows(out, archive, files + root_files("windows", version), version))
    if "linux" in wanted:
        archive = standalone_python(cache, "linux")
        made.append(build_linux(out, archive, files + root_files("linux", version), version))
    if "app" in wanted:
        made.append(build_app_zip(out, files, version))
    info = out / "update.json"
    python = ".".join(PYTHON_VERSION.split(".")[:2])
    info.write_text(json.dumps({"version": version, "python": python}), "utf-8")
    made.append(info)
    present = sorted(p for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    sums = "".join(f"{sha256(p)}  {p.name}\n" for p in present)
    (out / "SHA256SUMS.txt").write_text(sums, "utf-8")
    for path in made:
        print(f"{path.stat().st_size / 1e6:8.1f} MB  {path}")


if __name__ == "__main__":
    main()
