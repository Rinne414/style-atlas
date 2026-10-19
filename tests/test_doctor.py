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


def test_a_failed_model_download_explains_what_to_try(monkeypatch, tmp_path):
    import pytest

    from styleatlas import encoder, fetch

    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path))
    monkeypatch.setattr(fetch, "ranked", lambda urls, measure: [(u, 0.0) for u in urls])

    def offline(*args, **kwargs):
        raise fetch.FetchError("no source could deliver pytorch_model.bin")

    monkeypatch.setattr(fetch, "download", offline)
    with pytest.raises(encoder.ModelDownloadError, match="HF_ENDPOINT"):
        encoder.fetch_checkpoint(lambda msg: None)


def test_the_model_comes_from_the_faster_host_unless_one_is_chosen(monkeypatch, tmp_path):
    from styleatlas import encoder, fetch

    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path))
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    assert [u.split("/")[2] for u in encoder.model_urls()] == ["huggingface.co", "hf-mirror.com"]
    monkeypatch.setattr(fetch, "ranked", lambda urls, measure: [(urls[1], 9e6), (urls[0], 1e6)])
    calls, lines = [], []

    def fake_download(ranking, dest, sha256, size, progress):
        calls.append((ranking, dest, sha256, size))
        progress(size, size, "hf-mirror.com")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")

    monkeypatch.setattr(fetch, "download", fake_download)
    path = encoder.fetch_checkpoint(lines.append)
    ((ranking, dest, sha256, size),) = calls
    assert ranking[0][0].startswith("https://hf-mirror.com/") and dest == path
    assert sha256 == encoder.CSD_SHA256 and size == encoder.CSD_BYTES
    assert "hf-mirror.com 9.0 MB/s" in lines[0] and lines[-1].startswith("\r")
    monkeypatch.setenv("HF_ENDPOINT", "https://mirror.example/")
    assert encoder.model_urls() == [
        f"https://mirror.example/{encoder.CSD_REPO}/resolve/{encoder.CSD_REVISION}/"
        f"{encoder.CSD_FILE}"
    ]


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
    monkeypatch.setattr(encoder, "check_space", lambda downloading=True: None)
    monkeypatch.setattr(encoder, "hf_cached", lambda: None)
    old_layout = encoder.download_dir() / "models--tomg-group-umd--CSD-ViT-L"
    old_layout.mkdir(parents=True)  # an older version's unfinished download

    def download(progress):
        assert not old_layout.exists()
        path = encoder.download_dir() / encoder.CSD_FILE
        path.write_bytes(b"x" * 1000)  # stands in for 2.4 GB
        return path

    monkeypatch.setattr(encoder, "fetch_checkpoint", download)
    monkeypatch.setattr(encoder, "_extract_weights", lambda path: {"w": torch.zeros(2)})
    lines = []
    weights = encoder.load_weights(lines.append)
    assert set(weights) == {"w"}
    assert not (tmp_path / encoder.DOWNLOAD_DIR).exists()
    assert list(tmp_path.glob("csd_vit_l_*.safetensors"))  # the slim copy stays
    assert "downloading the style model" in lines[0]


def test_a_checkpoint_in_the_users_hugging_face_cache_is_used_and_left_alone(monkeypatch, tmp_path):
    import torch

    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path / "cache")
    theirs = tmp_path / "hf" / "pytorch_model.bin"
    theirs.parent.mkdir()
    theirs.write_bytes(b"x")
    monkeypatch.setattr(encoder, "hf_cached", lambda: theirs)
    spaces = []
    monkeypatch.setattr(encoder, "check_space", lambda downloading=True: spaces.append(downloading))

    def no_download(progress):
        raise AssertionError("downloaded although the user's cache had it")

    monkeypatch.setattr(encoder, "fetch_checkpoint", no_download)
    read = []
    monkeypatch.setattr(
        encoder, "_extract_weights", lambda path: read.append(path) or {"w": torch.zeros(2)}
    )
    assert set(encoder.load_weights(lambda msg: None)) == {"w"}
    assert read == [theirs] and theirs.exists() and spaces == [False]


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


def test_doctor_says_how_to_use_a_gpu_the_cpu_torch_cannot(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.version, "cuda", None)  # the CPU build
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "C:/nvidia-smi.exe")
    gpu = next(detail for _, name, detail in doctor._torch_lines() if name == "GPU")
    assert "--force-reinstall torch" in gpu and doctor.CUDA_INDEX in gpu
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)  # no NVIDIA card
    gpu = next(detail for _, name, detail in doctor._torch_lines() if name == "GPU")
    assert "CPU-only torch build" in gpu


def test_a_download_finished_before_a_crash_is_used_not_downloaded_again(monkeypatch, tmp_path):
    import hashlib

    import torch

    from styleatlas import encoder

    _own_cache(monkeypatch, tmp_path)
    data = b"checkpoint" * 100
    monkeypatch.setattr(encoder, "CSD_BYTES", len(data))
    monkeypatch.setattr(encoder, "CSD_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(encoder, "hf_cached", lambda: None)
    monkeypatch.setattr(encoder, "check_space", lambda downloading=True: None)
    done = encoder.download_dir() / encoder.CSD_FILE
    done.parent.mkdir(parents=True)
    done.write_bytes(data)

    def no_download(progress):
        raise AssertionError("downloaded again")

    monkeypatch.setattr(encoder, "fetch_checkpoint", no_download)
    read = []
    monkeypatch.setattr(
        encoder, "_extract_weights", lambda path: read.append(path) or {"w": torch.zeros(2)}
    )
    assert set(encoder.load_weights(lambda msg: None)) == {"w"}
    assert read == [done] and not done.exists()  # used, then removed with the download folder
    done.parent.mkdir(parents=True)
    done.write_bytes(data[:-1] + b"X")  # same size, other bytes: not trusted
    assert encoder.finished_download() is None


def test_a_broken_copy_in_the_users_hugging_face_cache_is_not_used(monkeypatch, tmp_path):
    import huggingface_hub

    from styleatlas import encoder

    short = tmp_path / "pytorch_model.bin"
    short.write_bytes(b"x" * 10)
    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda *a, **k: str(short))
    assert encoder.hf_cached() is None
    monkeypatch.setattr(encoder, "CSD_BYTES", 10)
    assert encoder.hf_cached() == short
