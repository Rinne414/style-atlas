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
