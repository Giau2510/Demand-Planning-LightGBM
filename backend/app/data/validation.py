"""Row-level normalisation + validation shared by all data sources.

Severity:
  ERROR     -> row is excluded (reason recorded)
  DUPLICATE -> exact duplicate of an earlier row; excluded so demand is not double counted
  WARNING   -> row kept; a value may have been blanked (always explained)
  INFO      -> row kept; valid but special (e.g. zero quantity)
"""
from __future__ import annotations

import re
from datetime import date, datetime

import numpy as np
import pandas as pd

from ..timeutil import VN_TZ, today_vn
from .schema import FIELD_BY_NAME

OUTPUT_COLUMNS = ["row_number", "order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty",
                  "unit_price", "discount_amount", "promotion_flag", "promotion_id", "voucher_flag",
                  "voucher_amount", "source_updated_at", "source_batch_id"]
MAX_STORED_ISSUES = 100_000
_OFFSET_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")
_TRUE = {"1", "true", "t", "yes", "y", "co", "có", "x"}
_FALSE = {"0", "false", "f", "no", "n", "khong", "không", ""}


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    if v is pd.NaT:
        return True
    return isinstance(v, str) and not v.strip()


def parse_datetime_series(s: pd.Series, naive_tz=VN_TZ) -> pd.Series:
    """Parse mixed Excel/BigQuery/text values to tz-aware Vietnam datetimes (NaT if invalid)."""
    out = pd.Series(pd.NaT, index=s.index, dtype=f"datetime64[ns, {VN_TZ.key}]")
    if s.empty:
        return out
    if pd.api.types.is_datetime64_any_dtype(s):
        ts = pd.to_datetime(s)
        if ts.dt.tz is None:
            return ts.dt.tz_localize(naive_tz, nonexistent="NaT", ambiguous="NaT").dt.tz_convert(VN_TZ)
        return ts.dt.tz_convert(VN_TZ)
    s = s.astype(object)
    kinds = s.map(lambda v: "blank" if _is_blank(v) else
                  ("aware" if isinstance(v, datetime) and v.tzinfo is not None else
                   ("naive" if isinstance(v, (datetime, date)) else
                    ("str" if isinstance(v, str) else "other"))))
    naive = s[kinds == "naive"]
    if len(naive):
        ts = pd.to_datetime(naive.map(lambda v: v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)),
                            errors="coerce")
        out.loc[naive.index] = ts.dt.tz_localize(naive_tz, nonexistent="NaT", ambiguous="NaT").dt.tz_convert(VN_TZ)
    aware = s[kinds == "aware"]
    if len(aware):
        out.loc[aware.index] = pd.to_datetime(aware.map(lambda v: v.isoformat()), utc=True,
                                              errors="coerce").dt.tz_convert(VN_TZ)
    strs = s[kinds == "str"].str.strip()
    if len(strs):
        has_off = strs.str.contains(_OFFSET_RE)
        off = strs[has_off]
        if len(off):
            out.loc[off.index] = pd.to_datetime(off, utc=True, errors="coerce", format="ISO8601").dt.tz_convert(VN_TZ)
        rest = strs[~has_off]
        parsed = pd.Series(pd.NaT, index=rest.index, dtype="datetime64[ns]")
        remaining = rest
        for fmt in ("ISO8601", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            if remaining.empty:
                break
            p = pd.to_datetime(remaining, format=fmt, errors="coerce")
            ok = p.notna()
            parsed.loc[p[ok].index] = p[ok]
            remaining = remaining[~ok]
        if len(parsed):
            loc = parsed.dt.tz_localize(naive_tz, nonexistent="NaT", ambiguous="NaT").dt.tz_convert(VN_TZ)
            out.loc[loc.index] = loc
    return out


def _parse_number(s: pd.Series) -> pd.Series:
    def conv(v):
        if _is_blank(v):
            return np.nan
        if isinstance(v, bool):
            return np.nan
        if isinstance(v, (int, float, np.integer, np.floating)):
            return float(v)
        if isinstance(v, str):
            t = v.strip().replace(" ", "")
            # accept "1,234.5" / "1234,5"? Only plain numbers and thousands separators with a dot decimal.
            if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):
                t = t.replace(",", "")
            try:
                return float(t)
            except ValueError:
                return np.inf  # marker for "not a number"
        return np.inf
    return s.map(conv).astype(float)


def _parse_flag(s: pd.Series) -> pd.Series:
    def conv(v):
        if _is_blank(v):
            return None
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float, np.integer, np.floating)):
            return 1 if float(v) == 1 else (0 if float(v) == 0 else -1)
        t = str(v).strip().lower()
        if t in _TRUE:
            return 1
        if t in _FALSE:
            return 0
        return -1
    return s.map(conv)


def _text(s: pd.Series) -> pd.Series:
    def conv(v):
        if _is_blank(v):
            return None
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v).strip()
    return s.map(conv).astype(object)


def normalize_and_validate(raw: pd.DataFrame, *, grain_conflict_policy: str = "ERROR",
                           min_date: str | None = None, price_outlier_factor: float = 10.0,
                           naive_tz=VN_TZ, today: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """raw: DataFrame with internal field names as columns (any subset) + optional 'row_number'.

    Returns (valid_rows, issues, summary).
    """
    today = today or today_vn()
    n = len(raw)
    df = pd.DataFrame(index=raw.index)
    df["row_number"] = raw["row_number"] if "row_number" in raw else np.arange(2, n + 2)
    issues: list[pd.DataFrame] = []

    def add(mask: pd.Series, field: str, code: str, severity: str, values: pd.Series | None = None):
        if not mask.any():
            return
        idx = mask[mask].index
        vals = (values if values is not None else raw[field] if field in raw else pd.Series(None, index=raw.index))
        issues.append(pd.DataFrame({"row_number": df.loc[idx, "row_number"].values, "field": field, "code": code,
                                    "severity": severity,
                                    "raw_value": vals.loc[idx].map(lambda v: None if _is_blank(v) else str(v)[:200]).values},
                                   index=idx))

    col = lambda name: raw[name] if name in raw else pd.Series([None] * n, index=raw.index, dtype=object)  # noqa: E731

    # --- text keys
    for f in ("order_id", "sku_id", "fc_id", "promotion_id"):
        df[f] = _text(col(f))
    df["source_batch_id"] = _text(col("batch_id"))
    add(df["sku_id"].isna(), "sku_id", "MISSING_SKU", "ERROR")
    add(df["fc_id"].isna(), "fc_id", "MISSING_FC", "ERROR")

    # --- time
    created = parse_datetime_series(col("created_at"), naive_tz)
    created_blank = col("created_at").map(_is_blank)
    add(created.isna() & ~created_blank, "created_at", "INVALID_DATETIME", "ERROR")
    od_raw = col("order_date")
    od_blank = od_raw.map(_is_blank)
    od_parsed = parse_datetime_series(od_raw, VN_TZ)
    add(od_parsed.isna() & ~od_blank, "order_date", "INVALID_DATE", "ERROR")
    def _dates(ts: pd.Series) -> pd.Series:
        return pd.Series([None if pd.isna(t) else t.date() for t in ts], index=ts.index, dtype=object)
    derived = _dates(created)
    explicit = _dates(od_parsed)
    order_date = pd.Series([e if e is not None else d for e, d in zip(explicit, derived)], index=raw.index,
                           dtype=object)
    add(order_date.isna() & created_blank & od_blank, "created_at", "MISSING_DATE", "ERROR")
    mism = explicit.notna() & derived.notna() & (explicit != derived)
    add(mism, "order_date", "ORDER_DATE_MISMATCH", "WARNING")
    df["order_date"] = order_date.map(lambda d: d.isoformat() if isinstance(d, date) else None)
    df["created_at"] = created.map(lambda t: t.isoformat() if not pd.isna(t) else None)
    od_valid = order_date.notna()
    future = od_valid & (order_date.map(lambda d: d > today if isinstance(d, date) else False))
    add(future, "order_date", "FUTURE_DATE", "ERROR", df["order_date"])
    if min_date:
        md = date.fromisoformat(min_date)
        add(od_valid & order_date.map(lambda d: isinstance(d, date) and d < md), "order_date", "OUT_OF_RANGE_DATE",
            "ERROR", df["order_date"])

    # --- quantity
    qty = _parse_number(col("order_qty"))
    qty_blank = col("order_qty").map(_is_blank)
    add(qty_blank, "order_qty", "MISSING_QTY", "ERROR")
    add(np.isinf(qty) & ~qty_blank, "order_qty", "INVALID_QTY", "ERROR")
    add(np.isfinite(qty) & (qty < 0), "order_qty", "NEGATIVE_QTY", "ERROR")
    df["order_qty"] = qty.where(np.isfinite(qty))
    add(df["order_qty"] == 0, "order_qty", "ZERO_QTY", "INFO")

    # --- optional numerics: invalid -> blanked with a WARNING (never silently)
    for f in ("unit_price", "discount_amount", "voucher_amount"):
        v = _parse_number(col(f))
        bad = np.isinf(v)
        neg = np.isfinite(v) & (v < 0)
        add(bad, f, "INVALID_NUMBER_BLANKED", "WARNING")
        add(neg, f, "NEGATIVE_VALUE_BLANKED", "WARNING")
        df[f] = v.where(np.isfinite(v) & (v >= 0))
    for f in ("promotion_flag", "voucher_flag"):
        v = _parse_flag(col(f))
        add(v == -1, f, "INVALID_FLAG_BLANKED", "WARNING")
        df[f] = v.where(v != -1)

    src_upd = parse_datetime_series(col("source_updated_at"), naive_tz)
    add(src_upd.isna() & ~col("source_updated_at").map(_is_blank), "source_updated_at", "INVALID_DATETIME_BLANKED",
        "WARNING")
    df["source_updated_at"] = src_upd.map(lambda t: t.isoformat() if not pd.isna(t) else None)
    both = created.notna() & src_upd.notna()
    add(both & (src_upd < created), "source_updated_at", "UPDATED_BEFORE_CREATED", "WARNING")
    add(both & ((src_upd - created) > pd.Timedelta(days=2)), "source_updated_at", "LATE_ARRIVING", "INFO")

    # discount larger than line value
    line_val = df["unit_price"] * df["order_qty"]
    add(df["discount_amount"].notna() & line_val.notna() & (df["discount_amount"] > line_val) & (line_val > 0),
        "discount_amount", "DISCOUNT_GT_LINE_VALUE", "WARNING")

    # --- rows with errors so far
    err_idx = set()
    for d in issues:
        err_idx.update(d.index[d["severity"] == "ERROR"])
    ok = ~df.index.isin(list(err_idx))

    # price outlier vs SKU median (among otherwise-valid rows)
    pr = df.loc[ok & df["unit_price"].notna(), ["sku_id", "unit_price"]]
    if len(pr):
        med = pr.groupby("sku_id")["unit_price"].transform("median")
        out_mask = (med > 0) & ((pr["unit_price"] > med * price_outlier_factor) | (pr["unit_price"] < med / price_outlier_factor))
        add(pd.Series(out_mask, index=pr.index).reindex(df.index, fill_value=False), "unit_price", "PRICE_OUTLIER", "WARNING")

    # --- duplicates (exact) among valid rows
    key_cols = [c for c in OUTPUT_COLUMNS if c != "row_number"]
    valid = df[ok]
    dup_mask = valid.duplicated(subset=key_cols, keep="first")
    add(dup_mask.reindex(df.index, fill_value=False), "order_id", "EXACT_DUPLICATE", "DUPLICATE")
    keep = ok & ~dup_mask.reindex(df.index, fill_value=False)

    # --- grain conflicts: same order_id x sku x fc with different values
    g = df[keep & df["order_id"].notna()]
    conflict = g.duplicated(subset=["order_id", "sku_id", "fc_id"], keep=False)
    conflict = conflict.reindex(df.index, fill_value=False)
    if grain_conflict_policy == "ERROR":
        add(conflict, "order_id", "GRAIN_CONFLICT", "ERROR")
        keep = keep & ~conflict
    else:
        add(conflict, "order_id", "GRAIN_MULTI_LINE_SUMMED", "WARNING")

    issues_df = (pd.concat(issues).sort_values(["row_number", "field"]) if issues else
                 pd.DataFrame(columns=["row_number", "field", "code", "severity", "raw_value"]))
    valid_df = df.loc[keep, OUTPUT_COLUMNS].copy()

    by_code = issues_df.groupby(["severity", "code"]).size().reset_index(name="count") if len(issues_df) else None
    dup_full = dup_mask.reindex(df.index, fill_value=False)
    error_rows = int((~keep & ~dup_full).sum())
    dup_rows = int(dup_full.sum())
    dates = sorted(set(valid_df["order_date"]))
    missing_dates: list[str] = []
    if dates:
        full = pd.date_range(dates[0], dates[-1], freq="D").strftime("%Y-%m-%d")
        missing_dates = sorted(set(full) - set(dates))
    summary = {
        "total_rows": int(n),
        "valid_rows": int(len(valid_df)),
        "error_rows": error_rows,
        "duplicate_rows": dup_rows,
        "issues_by_code": by_code.to_dict("records") if by_code is not None else [],
        "fields_with_problems": sorted(set(issues_df.loc[issues_df["severity"].isin(["ERROR", "WARNING"]), "field"]))
        if len(issues_df) else [],
        "min_order_date": dates[0] if dates else None,
        "max_order_date": dates[-1] if dates else None,
        "n_days": len(dates),
        "missing_dates": missing_dates[:366],
        "missing_dates_count": len(missing_dates),
        "n_skus": int(valid_df["sku_id"].nunique()),
        "n_fcs": int(valid_df["fc_id"].nunique()),
        "zero_qty_rows": int((valid_df["order_qty"] == 0).sum()),
        "issues_truncated": len(issues_df) > MAX_STORED_ISSUES,
    }
    return valid_df.reset_index(drop=True), issues_df.head(MAX_STORED_ISSUES).reset_index(drop=True), summary


__all__ = ["normalize_and_validate", "parse_datetime_series", "OUTPUT_COLUMNS", "FIELD_BY_NAME"]
