from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from styleatlas import cachedir, storage


@pytest.fixture
def home(tmp_path, monkeypatch):
    """No STYLE_ATLAS_CACHE, a fresh ~/.cache/style-atlas, and a source install."""
    monkeypatch.delenv("STYLE_ATLAS_CACHE", raising=False)
    old = tmp_path / "home" / ".cache" / "style-atlas"
    monkeypatch.setattr(cachedir, "home_cache", lambda: old)
    monkeypatch.setattr(cachedir, "program_dir", lambda: None)
    cachedir._resolved.clear()
    yield old
    cachedir._resolved.clear()


@pytest.fixture
def program(tmp_path, monkeypatch, home):
    root = tmp_path / "StyleAtlas"
    root.mkdir()
    monkeypatch.setattr(cachedir, "program_dir", lambda: root)
    return root


def fill(folder: Path) -> None:
    """A cache with a model, vectors, thumbnails and the state files."""
    (folder / "thumbs" / "ab").mkdir(parents=True)
    (folder / "thumbs" / "ab" / "x.webp").write_bytes(b"t" * 10)
    (folder / "csd_vit_l_5bc26a6f.safetensors").write_bytes(b"m" * 100)
    (folder / "vectors.sqlite").write_bytes(b"v" * 50)
    (folder / "settings.json").write_text('{"check_updates": false}', "utf-8")
    (folder / "recent_folders.json").write_text('["D:/pictures"]', "utf-8")


def test_source_install_keeps_everything_in_the_home_cache(home):
    assert cachedir.state_dir() == home
    assert cachedir.cache_dir() == home


def test_packaged_program_keeps_everything_in_its_own_folder(program):
    assert cachedir.state_dir() == program / "data"
    assert cachedir.cache_dir() == program / "data"


def test_packaged_program_reuses_the_model_an_older_version_downloaded(program, home):
    fill(home)
    assert cachedir.cache_dir() == home
    state = cachedir.state_dir()
    assert state == program / "data"
    assert json.loads((state / "recent_folders.json").read_text("utf-8")) == ["D:/pictures"]
    assert not (state / "vectors.sqlite").exists()


def test_settings_alone_in_the_home_cache_do_not_keep_the_cache_there(program, home):
    home.mkdir(parents=True)
    (home / "settings.json").write_text("{}", "utf-8")
    assert cachedir.cache_dir() == program / "data"


def test_environment_variable_wins(program, tmp_path, monkeypatch):
    cachedir.set_location(tmp_path / "chosen")
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path / "env"))
    assert cachedir.cache_dir() == tmp_path / "env"
    assert cachedir.state_dir() == tmp_path / "env"


def test_chosen_location_is_used_and_can_be_reset(program, tmp_path):
    cachedir.set_location(tmp_path / "E" / "cache")
    assert cachedir.cache_dir() == tmp_path / "E" / "cache"
    cachedir.set_location(None)
    assert cachedir.cache_dir() == program / "data"


def test_unreachable_location_falls_back_and_says_so(program, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", "utf-8")
    cachedir.set_location(blocker / "cache")  # cannot be made: its parent is a file
    assert cachedir.cache_dir() == program / "data"
    assert cachedir.problem == str(blocker / "cache")


def test_target_is_the_picked_folder_when_empty_or_a_cache(program, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert storage.target_for(empty) == empty
    old = tmp_path / "old-cache"
    old.mkdir()
    (old / "vectors.sqlite").write_bytes(b"")
    assert storage.target_for(old) == old
    assert storage.target_for(program / "data") == program / "data"


def test_busy_folder_gets_a_cache_folder_inside(program, tmp_path):
    busy = tmp_path / "D"
    busy.mkdir()
    (busy / "movies").mkdir()
    assert storage.target_for(busy) == busy / storage.SUBFOLDER


@pytest.mark.parametrize("inside", ["data/thumbs", "data", "app", "python/Lib"])
def test_refuses_places_that_would_lose_the_cache(program, inside):
    source = cachedir.cache_dir()
    with pytest.raises(storage.MoveError):
        storage.check_target(program / inside, source)


@pytest.mark.parametrize("drives", ["same", "different"])
def test_move_carries_the_cache_but_not_the_state(program, tmp_path, monkeypatch, drives):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: drives == "same")
    source = cachedir.cache_dir()
    fill(source)
    target = tmp_path / "E" / "cache"
    ticks = []
    outcome = storage.move(source, target, lambda done, total: ticks.append((done, total)))
    assert outcome == {"kept": [], "leftovers": []}
    assert cachedir.cache_dir() == target
    assert (target / "thumbs" / "ab" / "x.webp").read_bytes() == b"t" * 10
    assert (target / "csd_vit_l_5bc26a6f.safetensors").stat().st_size == 100
    assert not (source / "vectors.sqlite").exists() and not (source / "thumbs").exists()
    assert (source / "settings.json").exists() and not (target / "settings.json").exists()
    if drives == "different":
        assert ticks[-1] == (160, 160)


def test_moving_back_to_the_default_forgets_the_location(program, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: False)
    away = tmp_path / "E" / "cache"
    cachedir.set_location(away)
    fill(away)
    storage.move(away, program / "data", lambda done, total: None)
    assert cachedir.chosen_location() is None
    assert cachedir.cache_dir() == program / "data"
    assert (program / "data" / "vectors.sqlite").exists()


def test_failed_copy_changes_nothing(program, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: False)
    source = cachedir.cache_dir()
    fill(source)
    real = storage._copy_file

    def broken(src, dst, step):
        if src.name == "vectors.sqlite":
            raise OSError("disk pulled out")
        real(src, dst, step)

    monkeypatch.setattr(storage, "_copy_file", broken)
    target = tmp_path / "E" / "cache"
    with pytest.raises(OSError, match="disk pulled out"):
        storage.move(source, target, lambda done, total: None)
    assert cachedir.cache_dir() == source
    assert (source / "csd_vit_l_5bc26a6f.safetensors").exists()
    assert list(target.iterdir()) == []


def test_not_enough_room_undoes_what_was_renamed(program, tmp_path, monkeypatch):
    source = cachedir.cache_dir()
    fill(source)
    real_replace = storage.os.replace

    def locked(src, dst):  # the vectors are in use: they would have to be copied
        if Path(src).name == "vectors.sqlite":
            raise PermissionError("in use")
        real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", locked)
    monkeypatch.setattr(storage, "same_drive", lambda a, b: True)
    monkeypatch.setattr(storage, "ROOM", 10**18)
    with pytest.raises(storage.MoveError, match="GB"):
        storage.move(source, tmp_path / "E" / "cache", lambda done, total: None)
    assert (source / "thumbs" / "ab" / "x.webp").exists()
    assert (source / "csd_vit_l_5bc26a6f.safetensors").exists()
    assert cachedir.cache_dir() == source


def test_target_keeps_what_it_already_has(program, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: False)
    source = cachedir.cache_dir()
    fill(source)
    target = tmp_path / "E" / "cache"
    target.mkdir(parents=True)
    (target / "vectors.sqlite").write_bytes(b"theirs")
    outcome = storage.move(source, target, lambda done, total: None)
    assert outcome["kept"] == ["vectors.sqlite"]
    assert (target / "vectors.sqlite").read_bytes() == b"theirs"


def test_mover_waits_for_no_folder_being_computed(program, tmp_path):
    lock = threading.Lock()
    mover = storage.Mover(lock)
    lock.acquire()
    try:
        assert "error" in mover.start(tmp_path)
    finally:
        lock.release()


def test_mover_moves_in_the_background_and_reports(program, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: False)
    fill(cachedir.cache_dir())
    lock = threading.Lock()
    mover = storage.Mover(lock)
    target = tmp_path / "E"
    target.mkdir()
    assert mover.start(target)["ok"]
    for thread in threading.enumerate():
        if thread.name == "style-atlas-move":
            thread.join(10)
    state = mover.state()
    assert not state["busy"] and state["problem"] == ""
    assert state["path"] == str(target)
    assert state["result"] == "The cache is moved."
    assert lock.acquire(blocking=False)


def test_a_failed_switch_puts_everything_back(program, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: True)
    source = cachedir.cache_dir()
    fill(source)

    def read_only(folder):
        raise PermissionError("state folder is read-only")

    monkeypatch.setattr(cachedir, "set_location", read_only)
    with pytest.raises(PermissionError):
        storage.move(source, tmp_path / "E" / "cache", lambda done, total: None)
    assert (source / "vectors.sqlite").exists() and (source / "thumbs" / "ab" / "x.webp").exists()
    assert not (tmp_path / "E" / "cache" / "vectors.sqlite").exists()


def test_moving_an_old_home_cache_to_the_default_folder_sticks(program, home, monkeypatch):
    monkeypatch.setattr(storage, "same_drive", lambda a, b: False)
    fill(home)
    assert cachedir.cache_dir() == home  # an older version's cache is used where it is
    real_remove = storage._remove
    monkeypatch.setattr(  # the vectors are in use and stay behind
        storage, "_remove", lambda p: False if p.name == "vectors.sqlite" else real_remove(p)
    )
    outcome = storage.move(home, program / "data", lambda done, total: None)
    assert outcome["leftovers"] == [str(home / "vectors.sqlite")]
    assert cachedir.cache_dir() == program / "data"


def test_the_environment_variable_cannot_be_moved_from_the_page(program, tmp_path, monkeypatch):
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path / "env"))
    result = storage.Mover(threading.Lock()).start(tmp_path / "E")
    assert "STYLE_ATLAS_CACHE" in result["error"]


def test_an_unexpected_failure_does_not_leave_the_page_waiting(program, tmp_path, monkeypatch):
    def broken(source, target, tick):
        raise RuntimeError("something else")

    monkeypatch.setattr(storage, "move", broken)
    lock = threading.Lock()
    mover = storage.Mover(lock)
    target = tmp_path / "E"
    target.mkdir()
    assert mover.start(target)["ok"]
    for thread in threading.enumerate():
        if thread.name == "style-atlas-move":
            thread.join(10)
    state = mover.state()
    assert not state["busy"] and state["problem"] == "something else"
    assert lock.acquire(blocking=False)
