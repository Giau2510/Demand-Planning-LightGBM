"""1.3.1 (B10): feature importance of a training run - gain and number of splits of every model feature, their shares of
the total and the totals per feature group (docs/ke_hoach_lgbm_chot.md section 6.2).

Stored in training_feature_importance (migration 0011) and written as <reports_dir>\\<daily_forecast.report_subdir>\\
ty-trong-bien-<training_run_id>.xlsx after every training that has a model file, only while daily_forecast is enabled.
The report never changes the training: the caller logs an error and raises one WARNING alert FEATURE_REPORT_NOT_WRITTEN.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .. import db, paths
from ..timeutil import now_iso
from . import feature_catalog

TRIAL_LABEL = "Chạy thử – chưa dùng để mua hàng"
OTHER_GROUP = "OTHER"


def feature_group(name: str) -> str:
    """Group of a model feature as in the feature catalogue (IDENTITY, LAG, ROLLING, CALENDAR, PRICE, ...); OTHER when
    the catalogue does not know the name."""
    try:
        return feature_catalog.describe(name).get("group") or OTHER_GROUP
    except Exception:  # noqa: BLE001 - an unknown name is never a reason to lose the report
        return OTHER_GROUP


def _share(x: float, total: float) -> float:
    return float(x) / total if total > 0 else 0.0


def importance_rows(names: list[str], gains, splits) -> list[dict]:
    """One row per feature {feature, feature_group, gain, split, gain_share, split_share, rank}: shares of the total
    (0 when the total is 0), rank 1 = largest gain (ties keep the model order). Returned in rank order."""
    if not (len(names) == len(gains) == len(splits)):
        raise ValueError(f"names {len(names)} / gains {len(gains)} / splits {len(splits)} differ")
    g = [float(x) for x in gains]
    k = [int(x) for x in splits]
    tg, tk = float(sum(g)), float(sum(k))
    rows = [{"feature": n, "feature_group": feature_group(n), "gain": g[i], "split": k[i],
             "gain_share": _share(g[i], tg), "split_share": _share(k[i], tk)} for i, n in enumerate(names)]
    order = sorted(range(len(rows)), key=lambda i: -rows[i]["gain"])
    for r, i in enumerate(order, start=1):
        rows[i]["rank"] = r
    return [rows[i] for i in order]


def group_rows(rows: list[dict]) -> list[dict]:
    """Totals per feature group {feature_group, n_features, gain, split, gain_share, split_share}, largest gain first."""
    by: dict[str, dict] = {}
    for r in rows:
        d = by.setdefault(r["feature_group"], {"feature_group": r["feature_group"], "n_features": 0, "gain": 0.0,
                                                "split": 0})
        d["n_features"] += 1
        d["gain"] += float(r["gain"])
        d["split"] += int(r["split"])
    tg = float(sum(d["gain"] for d in by.values()))
    tk = float(sum(d["split"] for d in by.values()))
    out = [{**d, "gain_share": _share(d["gain"], tg), "split_share": _share(d["split"], tk)} for d in by.values()]
    return sorted(out, key=lambda d: -d["gain"])


def record(training_run_id: str, rows: list[dict]) -> int:
    """Stores the rows of one training run (one row per feature); returns the number of rows written."""
    with db.tx() as c:
        c.executemany("INSERT INTO training_feature_importance(training_run_id, feature, feature_group, gain, split, "
                      "gain_share, split_share, rank) VALUES (?,?,?,?,?,?,?,?)",
                      [(training_run_id, r["feature"], r["feature_group"], float(r["gain"]), int(r["split"]),
                        float(r["gain_share"]), float(r["split_share"]), int(r["rank"])) for r in rows])
    return len(rows)


def _header(ws, cols: list[str], widths: list[int]) -> None:
    ws.append(cols)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(ord("A") + i)].width = w


def write_workbook(path: Path, training_run_id: str, rows: list[dict], meta: dict) -> Path:
    """Sheets "Thông tin" (trial label first when meta["trial_mode"], run, model version, number of features, created
    at), "Theo biến" (one row per feature, rank order) and "Theo nhóm biến" (totals per group)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Thông tin"
    if meta.get("trial_mode"):
        ws.append([TRIAL_LABEL])
        ws["A1"].font = Font(bold=True)
    for k, v in (("Lần huấn luyện", training_run_id), ("Phiên bản mô hình", meta.get("model_version")),
                 ("Số biến", len(rows)), ("Thời điểm tạo (UTC)", meta.get("created_at") or now_iso())):
        ws.append([k, v])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 40
    wf = wb.create_sheet("Theo biến")
    _header(wf, ["Hạng", "Biến", "Nhóm biến", "Gain", "% gain", "Số lần chia nhánh", "% chia nhánh"],
            [8, 28, 18, 18, 10, 18, 14])
    for r in rows:
        wf.append([r["rank"], r["feature"], r["feature_group"], float(r["gain"]), float(r["gain_share"]),
                   int(r["split"]), float(r["split_share"])])
        for col in ("E", "G"):
            wf[f"{col}{wf.max_row}"].number_format = "0.00%"
    wf.freeze_panes = "A2"
    wg = wb.create_sheet("Theo nhóm biến")
    _header(wg, ["Nhóm biến", "Số biến", "Gain", "% gain", "Số lần chia nhánh", "% chia nhánh"],
            [18, 10, 18, 10, 18, 14])
    for d in group_rows(rows):
        wg.append([d["feature_group"], d["n_features"], float(d["gain"]), float(d["gain_share"]), int(d["split"]),
                   float(d["split_share"])])
        for col in ("D", "F"):
            wg[f"{col}{wg.max_row}"].number_format = "0.00%"
    wg.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def free_path(folder: Path, training_run_id: str) -> Path:
    """ty-trong-bien-<run>.xlsx in `folder`, never an existing file: -2, -3 ... added when the name is taken."""
    base = f"ty-trong-bien-{training_run_id}"
    p = folder / f"{base}.xlsx"
    n = 2
    while p.exists():
        p = folder / f"{base}-{n}.xlsx"
        n += 1
    return p


def publish(training_run_id: str, model_version: str | None, importance_full: list[dict], dcfg) -> Path:
    """Rows of info["feature_importance_full"] stored for the run, then the workbook written; returns its path."""
    rows = importance_rows([r["feature"] for r in importance_full], [r["gain"] for r in importance_full],
                           [r["split"] for r in importance_full])
    record(training_run_id, rows)
    folder = paths.reports_dir() / dcfg.report_subdir
    folder.mkdir(parents=True, exist_ok=True)
    return write_workbook(free_path(folder, training_run_id), training_run_id, rows,
                          {"trial_mode": bool(dcfg.trial_mode), "model_version": model_version,
                           "created_at": now_iso()})
