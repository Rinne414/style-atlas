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
