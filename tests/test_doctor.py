from __future__ import annotations

from styleatlas import doctor


def test_doctor_reports_each_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path))
    rows = doctor.checks()
    names = [name for _, name, _ in rows]
    assert {"python", "torch", "GPU", "CSD model", "free disk", "search data"} <= set(names)
    assert next(st for st, name, _ in rows if name == "search data") == doctor.OK
    assert all(status in (doctor.OK, doctor.WARN, doctor.FAIL) for status, _, _ in rows)
    model = next(detail for _, name, detail in rows if name == "CSD model")
    assert "not downloaded" in model  # empty cache folder
    code = doctor.run()
    assert code in (0, 1) and "CSD model" in capsys.readouterr().out


def test_a_failed_model_download_explains_the_mirror(monkeypatch, tmp_path):
    import huggingface_hub
    import pytest

    from styleatlas import encoder

    def offline(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", offline)
    with pytest.raises(encoder.ModelDownloadError, match="HF_ENDPOINT"):
        encoder._extract_weights()


def test_doctor_shows_how_big_the_caches_are(tmp_path, monkeypatch):
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path))
    (tmp_path / "vectors.sqlite").write_bytes(b"x" * 3_000_000)
    (tmp_path / "thumbs" / "ab").mkdir(parents=True)
    (tmp_path / "thumbs" / "ab" / "t.webp").write_bytes(b"x" * 2_000_000)
    rows = {name: detail for _, name, detail in doctor.checks()}
    assert rows["vector cache"].startswith("3 MB") and rows["thumbnails"].startswith("2 MB")


def _own_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path))
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)


def test_too_little_space_fails_before_the_download(monkeypatch, tmp_path):
    import shutil
    from collections import namedtuple

    import pytest

    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 10**12, 10**9))
    with pytest.raises(encoder.ModelDownloadError, match="STYLE_ATLAS_CACHE"):
        encoder.check_space()


def test_the_checkpoint_is_downloaded_into_the_cache_and_removed_after(monkeypatch, tmp_path):
    import torch

    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(encoder, "check_space", lambda: None)

    def download():
        (encoder.download_dir() / "blob").parent.mkdir(parents=True, exist_ok=True)
        (encoder.download_dir() / "blob").write_bytes(b"x" * 1000)  # stands in for 2.4 GB
        return {"w": torch.zeros(2)}

    monkeypatch.setattr(encoder, "_extract_weights", download)
    weights = encoder.load_weights()
    assert set(weights) == {"w"}
    assert not (tmp_path / encoder.DOWNLOAD_DIR).exists()
    assert list(tmp_path.glob("csd_vit_l_*.safetensors"))  # the slim copy stays


def test_a_hugging_face_cache_of_the_users_own_is_left_alone(monkeypatch, tmp_path):
    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path)
    assert encoder.download_dir() == tmp_path / encoder.DOWNLOAD_DIR
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert encoder.download_dir() is None


def test_doctor_points_at_an_old_checkpoint_no_longer_needed(monkeypatch, tmp_path):
    from huggingface_hub import constants

    from styleatlas.encoder import CSD_REVISION

    cache = tmp_path / "cache"
    _own_cache(monkeypatch, cache)
    cache.mkdir()
    (cache / f"csd_vit_l_{CSD_REVISION[:8]}.safetensors").write_bytes(b"x")
    old = tmp_path / "hub" / "models--tomg-group-umd--CSD-ViT-L"
    old.mkdir(parents=True)
    (old / "blob").write_bytes(b"x" * 1000)
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path / "hub"))
    rows = {name: detail for _, name, detail in doctor.checks()}
    assert "only uses its 1.2 GB copy" in rows["old download"]


def test_a_checkpoint_left_by_a_stopped_run_is_removed(monkeypatch, tmp_path):
    import torch
    from safetensors.torch import save_file

    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path)
    save_file(
        {"w": torch.zeros(2)}, str(tmp_path / f"csd_vit_l_{encoder.CSD_REVISION[:8]}.safetensors")
    )
    (tmp_path / encoder.DOWNLOAD_DIR).mkdir()
    (tmp_path / encoder.DOWNLOAD_DIR / "blob").write_bytes(b"x")
    assert set(encoder.load_weights()) == {"w"}
    assert not (tmp_path / encoder.DOWNLOAD_DIR).exists()


def test_the_space_check_adds_up_what_one_drive_must_hold(monkeypatch, tmp_path):
    import shutil
    from collections import namedtuple

    import pytest

    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 0, 4 * 10**9))
    encoder.check_space()  # 4 GB holds the 2.4 GB checkpoint and the 1.2 GB copy (3.9 GB)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 0, 3 * 10**9))
    with pytest.raises(encoder.ModelDownloadError, match="3.9 GB"):
        encoder.check_space()
