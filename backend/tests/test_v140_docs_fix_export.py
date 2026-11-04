"""1.4.0 re-review suggestions: the latest copy never ends on an older version when two processes export at once (the
highest recorded version is checked again after the replace), stale .reserved / .tmp files of the day folder (older
than 1 hour) are removed before reserving. Integration with fakes (isolated temporary database)."""
import os
import time
from datetime import date

from app import db, paths
from app.ml.sel2 import export

D = "2026-11-02"


def _folder():
    return export.export_root() / "20261102"


def _versions():
    with db.read() as c:
        return [r[0] for r in c.execute("SELECT version FROM export_runs WHERE forecast_date=? ORDER BY version", (D,))]


def _age(p, seconds):
    t = time.time() - seconds
    os.utime(p, (t, t))


# ------------------------------------------------------------------ latest copy re-checked after the replace
def test_an_older_copy_replaced_after_a_newer_one_is_copied_again(sel2_on, monkeypatch):
    r1 = export.write_daily_export(D)
    r2 = export.write_daily_export(D)
    latest = paths.data_dir() / r2["latest_path"]
    assert export._sha256(latest) == r2["sha256"]
    # process A (version 1) passed its first check before version 2 was recorded; its replace lands after B's
    seen = iter([1])
    real = export._max_version
    monkeypatch.setattr(export, "_max_version", lambda d: next(seen, None) or real(d))
    v1 = paths.data_dir() / r1["path"]
    assert export._latest_copy(_folder(), v1, latest, date.fromisoformat(D), 1) is None
    assert export._sha256(latest) == r2["sha256"]                       # ends on version 2, not version 1
    assert not list(_folder().glob(".*.tmp"))


def test_the_latest_copy_is_skipped_when_a_newer_version_is_already_recorded(sel2_on):
    r1 = export.write_daily_export(D)
    r2 = export.write_daily_export(D)
    latest = paths.data_dir() / r2["latest_path"]
    assert export._latest_copy(_folder(), paths.data_dir() / r1["path"], latest, date.fromisoformat(D), 1) is None
    assert export._sha256(latest) == r2["sha256"]


def test_a_newer_version_copied_again_but_locked_is_flagged(sel2_on, monkeypatch):
    r1 = export.write_daily_export(D)
    r2 = export.write_daily_export(D)
    latest = paths.data_dir() / r2["latest_path"]
    calls = {"n": 0}
    real_replace = os.replace

    def replace(a, b):
        calls["n"] += 1
        if calls["n"] > 1:                                              # the second copy finds the file open
            raise PermissionError(13, "in use")
        real_replace(a, b)
    seen = iter([1])
    real = export._max_version
    monkeypatch.setattr(export, "_max_version", lambda d: next(seen, None) or real(d))
    monkeypatch.setattr(export.os, "replace", replace)
    flag = export._latest_copy(_folder(), paths.data_dir() / r1["path"], latest, date.fromisoformat(D), 1)
    assert flag == "LATEST_COPY_LOCKED" and calls["n"] == 2
    assert not list(_folder().glob(".*.tmp"))


# ------------------------------------------------------------------ stale temporary files
def test_stale_reservations_and_temporary_files_are_removed_before_reserving(sel2_on):
    f = _folder()
    f.mkdir(parents=True, exist_ok=True)
    old_res = f / ".du_bao_20261102_v1.reserved"                       # left by a crashed process 2 h ago
    old_tmp = f / ".du_bao_20261102_v1.1234.abcdef012345.tmp"
    old_latest_tmp = f / ".du_bao_20261102.xlsx.1234.abcdef012345.tmp"
    young_res = f / ".du_bao_20261102_v2.reserved"                     # another process is writing version 2 now
    young_tmp = f / ".du_bao_20261102_v2.999.abcdef012345.tmp"
    old_version = f / "du_bao_20261102_v7.xlsx"                        # a version file is never touched
    other = f / "ghi_chu.tmp"                                          # not a file of the export
    for p in (old_res, old_tmp, old_latest_tmp, young_res, young_tmp, old_version, other):
        p.write_bytes(b"x")
    for p in (old_res, old_tmp, old_latest_tmp, old_version, other):
        _age(p, 2 * 3600)
    res = export.write_daily_export(D)
    assert res["version"] == 1                                         # the stale reservation no longer blocks v1
    assert not old_res.exists() and not old_tmp.exists() and not old_latest_tmp.exists()
    assert young_res.exists() and young_tmp.exists() and old_version.exists() and other.exists()
    assert old_version.read_bytes() == b"x"
    assert _versions() == [1]


def test_a_reservation_younger_than_one_hour_is_kept_and_skipped(sel2_on):
    f = _folder()
    f.mkdir(parents=True, exist_ok=True)
    res_file = f / ".du_bao_20261102_v1.reserved"
    res_file.write_bytes(b"")
    _age(res_file, 3600 - 120)
    res = export.write_daily_export(D)
    assert res["version"] == 2 and res_file.exists()


def test_remove_stale_temp_counts_only_the_removed_files(tmp_path):
    a, b, c = tmp_path / ".du_bao_x_v1.reserved", tmp_path / ".du_bao_x.xlsx.1.ab.tmp", tmp_path / "du_bao_x_v1.xlsx"
    for p in (a, b, c):
        p.write_bytes(b"")
        _age(p, export.STALE_TEMP_SECONDS + 60)
    assert export._remove_stale_temp(tmp_path) == 2
    assert c.exists() and not a.exists() and not b.exists()
    assert export._remove_stale_temp(tmp_path) == 0
