"""Updates: reading the newest release, fetching its code-only package (checked against its
SHA256; refused and nothing kept when it does not match), and the launcher putting it in place."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from styleatlas import updates

REPO = Path(__file__).resolve().parents[1]


def _app_zip(version: str, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("launch.py", "# new launcher\n")
        z.writestr("app/styleatlas/__init__.py", f'__version__ = "{version}"\n')
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return buf.getvalue()


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return


@pytest.fixture
def release_server(tmp_path, monkeypatch):
    """A local stand-in for GitHub: /latest (the API answer) and the release files."""
    files = tmp_path / "server"
    files.mkdir()
    handler = partial(_Quiet, directory=str(files))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def publish(version: str, app: bytes, *, sums_of: bytes | None = None, python: str = ""):
        name = f"style-atlas-app-{version}.zip"
        (files / name).write_bytes(app)
        digest = hashlib.sha256(app if sums_of is None else sums_of).hexdigest()
        (files / "SHA256SUMS.txt").write_text(f"{digest}  {name}\n", "utf-8")
        assets = [name, "SHA256SUMS.txt"]
        if python:
            (files / "update.json").write_text(json.dumps({"python": python}), "utf-8")
            assets.append("update.json")
        info = {
            "tag_name": f"v{version}",
            "body": "## 更新内容\n- something new",
            "html_url": f"{base}/page",
            "assets": [{"name": n, "browser_download_url": f"{base}/{n}"} for n in assets],
        }
        (files / "latest").write_text(json.dumps(info), "utf-8")

    monkeypatch.setenv(updates.URL_ENV, f"{base}/latest")
    yield publish
    server.shutdown()
    server.server_close()


def test_versions_compare_by_number():
    assert updates.is_newer("v0.44.1", "0.44.0") and updates.is_newer("0.100.0", "0.99.9")
    assert not updates.is_newer("0.44.0", "0.44.0") and not updates.is_newer("0.43.9", "0.44.0")
    assert updates.version_key("v1.2") == (1, 2)


def test_a_newer_release_is_read_and_fetched_into_ready(release_server, tmp_path):
    release_server("9.9.9", _app_zip("9.9.9"))
    release = updates.latest()
    assert release.version == "9.9.9" and "更新内容" in release.notes
    assert updates.is_newer(release.version)
    seen = []
    ready = updates.fetch(release, tmp_path, lambda done, total: seen.append(done))
    assert ready == tmp_path / "updates" / "ready" and seen
    assert '"9.9.9"' in (ready / "app" / "styleatlas" / "__init__.py").read_text("utf-8")
    assert sorted(p.name for p in (tmp_path / "updates").iterdir()) == ["ready"]  # no leftovers


def test_a_file_that_does_not_match_its_sha256_is_thrown_away(release_server, tmp_path):
    release_server("9.9.9", _app_zip("9.9.9"), sums_of=b"something else")
    with pytest.raises(updates.UpdateError, match="SHA256"):
        updates.fetch(updates.latest(), tmp_path, lambda *_: None)
    assert list((tmp_path / "updates").iterdir()) == []


def test_unsafe_or_incomplete_packages_are_refused(release_server, tmp_path):
    release_server("9.9.9", _app_zip("9.9.9", {"../evil.py": "x"}))
    with pytest.raises(updates.UpdateError):
        updates.fetch(updates.latest(), tmp_path, lambda *_: None)
    assert not (tmp_path / "evil.py").exists() and not (tmp_path / "updates" / "ready").exists()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "no program inside")
    release_server("9.9.9", buf.getvalue())
    with pytest.raises(updates.UpdateError):
        updates.fetch(updates.latest(), tmp_path, lambda *_: None)


def test_a_release_on_another_python_asks_for_the_full_package(release_server, tmp_path):
    release_server("9.9.9", _app_zip("9.9.9"), python="2.7")
    release = updates.latest()
    assert updates.needs_full_package(release)
    with pytest.raises(updates.UpdateError, match="2.7"):
        updates.fetch(release, tmp_path, lambda *_: None)


def test_an_unreachable_server_is_an_update_error(monkeypatch):
    monkeypatch.setenv(updates.URL_ENV, "http://127.0.0.1:9/latest")
    with pytest.raises(updates.UpdateError):
        updates.latest()


def test_the_check_at_start_is_a_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path))
    assert updates.check_enabled() is True
    updates.set_check_enabled(False)
    assert updates.check_enabled() is False and updates.Updater().state()["check"] is False


def _launcher(root: Path):
    """packaging/launch.py loaded as if it sat in `root` (its folder is the package's folder)."""
    shutil.copy(REPO / "packaging" / "launch.py", root / "launch.py")
    spec = importlib.util.spec_from_file_location("launch_under_test", root / "launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_launcher_puts_a_ready_update_in_place_and_keeps_the_one_before(tmp_path):
    launch = _launcher(tmp_path)
    (tmp_path / "app" / "styleatlas").mkdir(parents=True)
    (tmp_path / "app" / "styleatlas" / "__init__.py").write_text("old", "utf-8")
    ready = tmp_path / "updates" / "ready"
    with zipfile.ZipFile(io.BytesIO(_app_zip("9.9.9"))) as z:
        z.extractall(ready)
    launch.apply_update()
    assert '"9.9.9"' in (tmp_path / "app" / "styleatlas" / "__init__.py").read_text("utf-8")
    assert (tmp_path / "updates" / "previous" / "app" / "styleatlas" / "__init__.py").read_text(
        "utf-8"
    ) == "old"
    assert (tmp_path / "launch.py").read_text("utf-8") == "# new launcher\n"
    assert not ready.exists()
    launch.apply_update()  # nothing ready: nothing happens
    assert (tmp_path / "app").is_dir()


def _launcher_with_lists(root: Path):
    """The launcher with an app/ that has its package lists (the lock files)."""
    launch = _launcher(root)
    (root / "app" / "locks").mkdir(parents=True)
    (root / "app" / "requirements-torch.txt").write_text("torch==1\n", "utf-8")
    for step in ("torch-cpu", "torch-cuda", "packages"):
        launch.lock(step).write_text(f"{step}==1 --hash=sha256:00\n", "utf-8")
    (root / "python").mkdir()
    return launch


def test_the_launcher_reinstalls_only_when_the_package_lists_change(tmp_path, monkeypatch):
    launch = _launcher_with_lists(tmp_path)
    monkeypatch.delenv(launch.TORCH_ENV, raising=False)
    assert not launch.ready()  # nothing installed yet
    launch.MARK.write_text(json.dumps(launch.wanted({"torch": "cpu"})), "utf-8")
    assert launch.ready() and launch.torch_variant(launch.installed()) == "cpu"
    launch.lock("packages").write_text("numpy==9 --hash=sha256:11\n", "utf-8")  # an update
    assert not launch.ready()
    launch.MARK.write_text(json.dumps(launch.wanted({"torch": "cpu"})), "utf-8")
    monkeypatch.setenv(launch.TORCH_ENV, "cuda")  # asked for the other torch build
    assert not launch.ready()


def test_the_launcher_keeps_pip_downloads_in_its_folder_until_installed(tmp_path, monkeypatch):
    launch = _launcher_with_lists(tmp_path)
    monkeypatch.delenv("PIP_CACHE_DIR", raising=False)
    monkeypatch.delenv("PIP_NO_CACHE_DIR", raising=False)
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.setenv(launch.TORCH_ENV, "cpu")
    monkeypatch.setattr(launch, "sources", lambda indexes, package: list(indexes))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        launch.PIP_CACHE.mkdir(exist_ok=True)  # what pip leaves behind
        return subprocess.CompletedProcess(command, returncode=0 if len(calls) < 2 else 1)

    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    assert not launch.prepare()  # the packages failed from every source: downloads stay
    assert all(c[c.index("--cache-dir") + 1] == str(launch.PIP_CACHE) for c in calls)
    assert launch.PIP_CACHE.is_dir()
    monkeypatch.setattr(
        launch.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0)
    )
    assert launch.prepare()
    assert not launch.PIP_CACHE.exists()


def test_the_launcher_installs_the_locked_files_and_falls_back_to_the_next_source(
    tmp_path, monkeypatch
):
    launch = _launcher_with_lists(tmp_path)
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.setenv(launch.TORCH_ENV, "cuda")
    ranked = []

    def fastest_mirror_first(indexes, package):
        ranked.append(package)
        return [indexes[1], indexes[0], *indexes[2:]]

    monkeypatch.setattr(launch, "sources", fastest_mirror_first)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        index = command[command.index("--index-url") + 1]
        fails = index == launch.PYPI_SOURCES[1]  # the fastest PyPI mirror breaks off
        return subprocess.CompletedProcess(command, returncode=1 if fails else 0)

    monkeypatch.setattr(launch.subprocess, "run", fake_run)
    assert launch.prepare()
    used = [(c[c.index("-r") + 1], c[c.index("--index-url") + 1]) for c in calls]
    assert used == [
        (str(launch.lock("torch-cuda")), launch.TORCH_SOURCES["cuda"][1]),
        (str(launch.lock("packages")), launch.PYPI_SOURCES[1]),
        (str(launch.lock("packages")), launch.PYPI_SOURCES[0]),
    ]
    assert all("--require-hashes" in c for c in calls)
    assert ranked == ["torch", "scipy"]


def test_the_users_own_package_index_is_used_as_it_is(tmp_path, monkeypatch):
    launch = _launcher_with_lists(tmp_path)
    monkeypatch.setenv("PIP_INDEX_URL", "https://pypi.example/simple")

    def no_probe(indexes, package):
        raise AssertionError("measured although the user chose an index")

    monkeypatch.setattr(launch, "sources", no_probe)
    assert launch.package_indexes() == ["https://pypi.example/simple"]


def test_wheels_for_this_python_and_system_are_recognised(tmp_path):
    launch = _launcher(tmp_path)
    abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
    here = "win_amd64" if launch.WINDOWS else "manylinux_2_28_x86_64"
    assert launch._wheel_for_here(f"scipy-1.0-{abi}-{abi}-{here}.whl")
    assert not launch._wheel_for_here(f"scipy-1.0-{abi}-{abi}-macosx_14_0_arm64.whl")
    assert not launch._wheel_for_here(f"scipy-1.0-cp27-cp27-{here}.whl")
    assert not launch._wheel_for_here("scipy-1.0.tar.gz")
