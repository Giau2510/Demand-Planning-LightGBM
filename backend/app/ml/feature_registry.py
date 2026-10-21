"""Feature registry: one metadata record per model input that exists today and per input planned for the future.

Status of a feature for a data scope (computed, never stored as a fact about the data):
  ACTIVE       the next training on this scope uses it (switch on AND the data really exists)
  DISABLED     data exists (or the feature exists in code) but it is switched off / not activated yet
  PLANNED      prepared in the architecture only: no source column, rule or data yet
  UNAVAILABLE  the switch is on or the column is mapped, but the scope has no (or too little) data for it

Rules enforced here and in the pipeline:
* A feature without real data is never filled with invented values to be learned: its group is removed from the
  feature set of that training (`resolve`). The resolved switches are stored with the training run, so every model
  is explained later with exactly its own feature list (old models keep theirs).
* PLANNED features are documentation + metadata only. Nothing here adds a column to the model.
"""
from __future__ import annotations

import hashlib

from . import feature_catalog as cat
from .features import CUSTOMER, OPEN_HOURS, WEEKDAY, discount_on, feature_names, weekday_on

REGISTRY_VERSION = "2026-10-15.1"
# version of the feature COMPUTATION code (features_at). Bump only when the meaning of an existing feature changes.
FEATURE_CODE_VERSION = "fe-1"

GROUPS = {
    "DEMAND_HISTORY": ("Nhu cầu lịch sử & lịch", "Demand history & calendar"),
    "PRICE_PROMOTION": ("Giá & khuyến mãi", "Price & promotion"),
    "SKU_AVAILABILITY": ("Thuộc tính SKU & khả dụng", "SKU attributes & availability"),
    "CUSTOMER_BEHAVIOUR": ("Hành vi mua lại của khách (tổng hợp)", "Customer repeat behaviour (aggregated)"),
    "FUTURE": ("Mở rộng trong tương lai", "Future extensions"),
}
STATUSES = {
    "ACTIVE": ("Đang sử dụng", "In use"),
    "DISABLED": ("Có dữ liệu/có sẵn nhưng chưa kích hoạt", "Available but not activated"),
    "PLANNED": ("Đang lên kế hoạch", "Planned"),
    "UNAVAILABLE": ("Thiếu dữ liệu", "Missing data"),
}
REASONS = {
    "ALWAYS_ON": ("Luôn dùng (nhận diện chuỗi).", "Always used (series identity)."),
    "TOGGLE_ON": ("Bật trong cấu hình mô hình.", "Switched on in the model settings."),
    "TOGGLE_OFF": ("Tắt trong cấu hình mô hình.", "Switched off in the model settings."),
    "DATA_OK": ("Bật và nguồn có dữ liệu (độ phủ đạt ngưỡng).", "On and the source has the data (coverage above the threshold)."),
    "NO_DATA": ("Bật nhưng nguồn không có dữ liệu cho trường này — không tự tạo giá trị.",
                "On, but the source has no data for this field — no values are invented."),
    "LOW_COVERAGE": ("Bật nhưng độ phủ dữ liệu dưới ngưỡng — chưa dùng.", "On, but data coverage is below the threshold — not used."),
    "NO_DATA_IN_SCOPE": ("Nguồn đang chọn chưa có dữ liệu nhu cầu (chưa đồng bộ/nhập).", "The selected source has no demand data yet (not synced/imported)."),
    "NO_SOURCE_COLUMN": ("Chưa có cột nguồn/dữ liệu thực.", "No source column / real data yet."),
    "COLUMN_MAPPED_NOT_VALIDATED": ("Đã ánh xạ cột nguồn nhưng chưa kiểm tra dữ liệu.", "Source column mapped but the data has not been validated."),
    "HAS_SOURCE_DATA_NOT_ACTIVATED": ("Nguồn có dữ liệu cho cột này nhưng chưa có quy tắc tổng hợp/thiếu dữ liệu được duyệt — chưa đưa vào mô hình.",
                                      "The source has data for this column but no approved aggregation / missing-value rule yet — not a model input."),
    "MAPPED_NO_DATA": ("Đã ánh xạ nhưng cột không có giá trị trong kỳ kiểm tra.", "Mapped, but the column has no values in the validated period."),
    "MANDATORY_DATA_OK": ("Bắt buộc với nguồn BigQuery; mọi dòng nhu cầu của cửa sổ dữ liệu có giờ mở bán hợp lệ.",
                          "Mandatory for the BigQuery source; every demand row of the data window has valid open hours."),
    "MANDATORY_NOT_READY": ("Bắt buộc với nguồn BigQuery nhưng có dòng nhu cầu của cửa sổ dữ liệu chưa có giờ mở bán hợp lệ — huấn luyện dừng (OPEN_HOURS_INVALID), không tự điền giá trị.",
                            "Mandatory for the BigQuery source, but some demand rows of the data window have no valid open hours — training stops (OPEN_HOURS_INVALID); nothing is filled in."),
    "NOT_IN_SOURCE": ("Nguồn đang chọn không có cột giờ mở bán (chỉ BigQuery D-1 có) — không áp dụng.",
                      "The selected source has no open-hours column (only the BigQuery D-1 source has it) — not applicable."),
}

# switch (ModelSettings field) and demand_daily column behind every optional group
_OPTIONAL = {
    "price": {"toggle": "feature_price", "column": "avg_unit_price", "internal": "unit_price",
              "features": ["price_last", "price_rel_28"]},
    "discount": {"toggle": "feature_discount", "column": "avg_discount_rate", "internal": "discount_amount",
                 "features": ["disc_last"]},
    "promotion": {"toggle": "feature_promotion", "column": "promo_share", "internal": "promotion_flag",
                  "features": ["promo_last", "promo_mean_7"]},
    # 1.2.9b: OFF by default; data only when the owner maps a customer column (data/customers.py)
    "customer": {"toggle": "feature_customer", "column": "customer_count", "internal": "customer_id",
                 "features": list(CUSTOMER)},
}
_GROUP_OF_FEATURE = {f: g for g, d in _OPTIONAL.items() for f in d["features"]}
_TOGGLE_OF_CATALOG = {"LAG": "feature_lags", "ROLLING": "feature_rolling", "CALENDAR": "feature_calendar"}

_AGGREGATION = {
    "IDENTITY": "Mã hóa danh mục từ danh sách SKU/FC đã sắp xếp lúc huấn luyện.",
    "LAG": "Σ số lượng (target) theo SKU × FC × ngày.",
    "ROLLING": "Σ số lượng (target) theo SKU × FC × ngày, rồi tính trên cửa sổ ngày đã biết.",
    "CALENDAR": "Tính từ chính ngày dự báo.",
    "price": "Σ(giá × số lượng) ÷ Σ số lượng theo SKU × FC × ngày.",
    "discount": "Σ giảm giá ÷ Σ(giá × số lượng) theo SKU × FC × ngày.",
    "promotion": "Trung bình cờ khuyến mãi (0/1) của các dòng đơn theo SKU × FC × ngày.",
    "customer": ("Tổng hợp trong BigQuery theo SKU × FC × ngày từ cột mã khách (không lấy mã khách về ứng dụng): số khách "
                 "đặt, số khách đã đặt cùng SKU × FC trong 90 ngày trước, tổng số ngày từ lần đặt trước của họ."),
    "open_hours": ("total_open_hours của các dòng đơn cùng ngày × SKU × FC: chỉ nhận khi mọi dòng có giá trị, bằng nhau và "
                   "trong 0..24; thiếu / khác nhau / ngoài miền = không có giá trị (trạng thái MISSING / CONFLICT / "
                   "OUT_OF_RANGE; MULTI_ITEM khi các item_code của SKU có giờ khác nhau, mỗi item một giá trị - chưa có "
                   "quy tắc gộp về SKU × FC; hậu tố .1/.2 là thứ tự mở bán, không phải mã miền)."),
}
_AVAILABILITY = {
    "IDENTITY": "Biết trước (danh mục lúc huấn luyện).",
    "LAG": "Chỉ dùng ngày TRƯỚC ngày dự báo.",
    "ROLLING": "Chỉ dùng các ngày TRƯỚC ngày dự báo.",
    "CALENDAR": "Biết trước (lịch).",
    "price": "Giá đã biết của ngày trước ngày dự báo; sau mốc dự báo giữ giá cuối cùng.",
    "discount": "Giá trị đã biết của ngày trước ngày dự báo; sau mốc dự báo giữ giá trị cuối.",
    "promotion": "Giá trị của ngày trước ngày dự báo; sau mốc dự báo giả định 0 (không có lịch khuyến mãi tương lai).",
    "customer": ("Chỉ các ngày TRƯỚC mốc dự báo (28 ngày lịch, ngày đã biết); số của mỗi ngày chỉ dùng đơn tới chính ngày "
                 "đó. Ngày không có mã khách = chưa biết, không thay bằng 0."),
    "open_hours": ("Chỉ ngày TRƯỚC mốc dự báo (giá trị hôm trước và trung bình 7 ngày đã biết); giờ mở bán của ngày dự báo "
                   "chưa biết nên không dùng. Ngày không có giá trị = chưa biết, không thay bằng 0."),
}

# Planned inputs (architecture only). `reference` = reference field of the BigQuery mapping when the source has a
# candidate column; `internal` = internal order-line field (Excel import / generic BigQuery mapping).
PLANNED = [
    dict(key="price_at_order", group="PRICE_PROMOTION", data_type="float", reference="sales_price",
         vi=("Giá bán tại thời điểm đặt hàng", "Giá bán của SKU trên dòng đơn; cần xác nhận là đơn giá (không phải thành tiền) và là giá lúc đặt."),
         en=("Price at order time", "Selling price of the SKU on the order line; must be confirmed as a unit price at order time.")),
    dict(key="price_after_discount", group="PRICE_PROMOTION", data_type="float", reference="price_after_discount",
         vi=("Giá sau chiết khấu", "Giá sau chiết khấu của dòng đơn; cần quy tắc tổng hợp về SKU × FC × ngày."),
         en=("Price after discount", "Discounted price of the order line; needs an aggregation rule to SKU × FC × day.")),
    dict(key="discount_rate_order", group="PRICE_PROMOTION", data_type="float", reference=None,
         vi=("Tỷ lệ giảm giá trên dòng đơn", "Dự kiến = 1 − giá sau chiết khấu ÷ giá bán, chỉ khi hai cột cùng đơn vị và đã được duyệt."),
         en=("Order-line discount rate", "Planned = 1 − discounted price ÷ price, only once both columns are confirmed in the same unit.")),
    dict(key="deal_flag", group="PRICE_PROMOTION", data_type="bool", reference=None,
         vi=("SKU có deal", "SKU trong đơn có thuộc deal hay không. Chưa có cột nguồn."), en=("SKU in a deal", "Whether the SKU on the order belongs to a deal. No source column yet.")),
    dict(key="promotion_flag_line", group="PRICE_PROMOTION", data_type="bool", reference=None,
         vi=("SKU có promotion", "Cờ promotion trên dòng đơn. Bảng BigQuery hiện tại chưa có cột này."),
         en=("SKU on promotion", "Promotion flag on the order line. The current BigQuery table has no such column.")),
    dict(key="promotion_type", group="PRICE_PROMOTION", data_type="category", reference=None,
         vi=("Loại deal/promotion", "Loại chương trình. Chưa có cột nguồn."), en=("Deal/promotion type", "Programme type. No source column yet.")),
    dict(key="voucher", group="PRICE_PROMOTION", data_type="float", reference=None,
         vi=("Voucher / mức giảm", "Voucher hoặc mức giảm trên đơn. Chưa có cột nguồn."), en=("Voucher / discount amount", "Voucher or discount on the order. No source column yet.")),
    dict(key="sku_status", group="SKU_AVAILABILITY", data_type="category", reference="sku_status",
         vi=("Trạng thái SKU", "Trạng thái hệ thống của SKU; cần biết giá trị có tại thời điểm dự báo hay là trạng thái cập nhật sau."),
         en=("SKU status", "System status of the SKU; must be known at forecast time (not a later update).")),
    dict(key="seller_group", group="SKU_AVAILABILITY", data_type="category", reference="seller_code",
         vi=("Seller / nhóm seller", "Seller của SKU. Không đưa mã định danh thuần vào mô hình khi chưa đánh giá."),
         en=("Seller / seller group", "Seller of the SKU. A raw identifier is not used as an input before evaluation.")),
    # open_hours: a model input since 1.2.9 (open_hours_last, open_hours_mean_7), no longer planned
    dict(key="open_days", group="SKU_AVAILABILITY", data_type="float", reference="open_days",
         vi=("Số ngày SKU mở bán", "Số ngày SKU khả dụng; cần quy tắc tổng hợp."), en=("SKU open days", "Days the SKU was available; needs an aggregation rule.")),
    dict(key="days_since_open", group="SKU_AVAILABILITY", data_type="float", reference="open_date",
         vi=("Số ngày từ ngày mở bán", "Tính từ open_date; cần xác nhận ý nghĩa open_date."), en=("Days since open date", "From open_date; its meaning must be confirmed.")),
    dict(key="holiday_flag", group="FUTURE", data_type="bool", reference=None,
         vi=("Ngày lễ / mùa vụ", "Lịch lễ Việt Nam, Tết. Chưa có nguồn đáng tin cậy được chọn."), en=("Holiday / season", "Vietnamese holidays, Tet. No trusted source chosen yet.")),
    dict(key="campaign_flag", group="FUTURE", data_type="bool", reference=None,
         vi=("Chiến dịch", "Lịch chiến dịch bán hàng. Chưa có nguồn."), en=("Campaign", "Sales campaign calendar. No source yet.")),
    dict(key="order_attributes", group="FUTURE", data_type="mixed", reference=None,
         vi=("Thuộc tính đơn hàng", "Kênh, loại khách hàng... khi có nguồn phù hợp."), en=("Order attributes", "Channel, customer type... when a suitable source exists.")),
]


def all_model_features() -> list[str]:
    """Every feature the computation code can produce, in model order (all switches on)."""
    class _All:
        feature_lags = feature_rolling = feature_calendar = feature_price = feature_promotion = True
        feature_discount = feature_weekday = feature_open_hours = feature_customer = True
    return feature_names(_All)


def feature_set_version(names: list[str]) -> str:
    h = hashlib.sha256((FEATURE_CODE_VERSION + "|" + ",".join(names)).encode()).hexdigest()[:12]
    return f"FS-{FEATURE_CODE_VERSION}-{h}"


def coverage(conn, scope_key: str) -> dict:
    """Share of the scope's demand rows that carry each optional value (rows = SKU × FC × day).
    Master audit 21/10/2026: ONE sequential scan (NOT INDEXED, as ops_routes 1.2.7 and demand.fingerprint 1.2.8). Through
    the key index SQLite fetched every row again for the counted columns: 8.3 s median (26 s cold) on a copy of
    production (1.36 M rows), 13.5 s median on the Feature registry page; 0.47 s now. Same counts."""
    r = conn.execute("SELECT COUNT(*), COUNT(avg_unit_price), COUNT(avg_discount_rate), COUNT(promo_share), "
                     "COUNT(open_hours), COUNT(customer_count) FROM demand_daily NOT INDEXED WHERE scope_key=?",
                     (scope_key,)).fetchone()
    n = r[0] or 0
    return {"rows": n, "avg_unit_price": (r[1] / n) if n else None, "avg_discount_rate": (r[2] / n) if n else None,
            "promo_share": (r[3] / n) if n else None, "open_hours": (r[4] / n) if n else None,
            "customer_count": (r[5] / n) if n else None}


def coverage_of_frame(demand) -> dict:
    n = len(demand)
    out = {"rows": n}
    for col in ("avg_unit_price", "avg_discount_rate", "promo_share", "open_hours", "customer_count"):
        out[col] = (float(demand[col].notna().sum()) / n) if n and col in demand else (None if not n else 0.0)
    return out


def resolve(mcfg, cov: dict):
    """Switches actually usable on this data. Returns (resolved ModelSettings copy, decisions per optional group)."""
    decisions = {}
    upd = {}
    for g, d in _OPTIONAL.items():
        on = discount_on(mcfg) if g == "discount" else bool(getattr(mcfg, d["toggle"]))
        c = cov.get(d["column"])
        if not on:
            used, reason = False, "TOGGLE_OFF"
        elif not cov.get("rows"):
            used, reason = False, "NO_DATA_IN_SCOPE"
        elif not c:
            used, reason = False, "NO_DATA"
        elif c < mcfg.feature_min_coverage:
            used, reason = False, "LOW_COVERAGE"
        else:
            used, reason = True, "DATA_OK"
        decisions[g] = {"switch": d["toggle"], "switch_on": on, "data_column": d["column"], "coverage": c,
                        "min_coverage": mcfg.feature_min_coverage, "used": used, "reason": reason,
                        "features": d["features"]}
        upd[d["toggle"]] = used
    return mcfg.model_copy(update=upd), decisions


def _labels(table: dict, key: str) -> dict:
    vi, en = table[key]
    return {"vi": vi, "en": en}


def model_feature_entry(name: str, mcfg, decisions: dict | None, n_rows: int | None) -> dict:
    d = cat.describe(name)
    cgroup = d["group"]
    opt = _GROUP_OF_FEATURE.get(name)
    if cgroup == "IDENTITY":
        status, reason, toggle = "ACTIVE", "ALWAYS_ON", None
    elif opt:
        dec = (decisions or {}).get(opt) or {}
        toggle = _OPTIONAL[opt]["toggle"]
        if dec.get("used"):
            status, reason = "ACTIVE", "DATA_OK"
        elif dec.get("reason") == "TOGGLE_OFF":
            status, reason = "DISABLED", "TOGGLE_OFF"
        else:
            status, reason = "UNAVAILABLE", dec.get("reason") or "NO_DATA"
    elif name in OPEN_HOURS:       # 1.2.9: mandatory for the BIGQUERY source - decided by the source and its data
        dec = (decisions or {}).get("open_hours") or {}
        toggle = None
        if not dec.get("mandatory"):
            status, reason = "UNAVAILABLE", "NOT_IN_SOURCE"
        elif dec.get("ok"):
            status, reason = "ACTIVE", "MANDATORY_DATA_OK"
        else:
            status, reason = "UNAVAILABLE", "MANDATORY_NOT_READY"
    elif name in WEEKDAY:          # 1.2.8: day of week of the target day has its own switch
        toggle = "feature_weekday"
        status, reason = ("ACTIVE", "TOGGLE_ON") if weekday_on(mcfg) else ("DISABLED", "TOGGLE_OFF")
    else:
        toggle = _TOGGLE_OF_CATALOG.get(cgroup)
        on = bool(getattr(mcfg, toggle)) if toggle else True
        status, reason = ("ACTIVE", "TOGGLE_ON") if on else ("DISABLED", "TOGGLE_OFF")
    if status == "ACTIVE" and not n_rows:
        status, reason = "UNAVAILABLE", "NO_DATA_IN_SCOPE"
    oh = name in OPEN_HOURS
    key = "open_hours" if oh else (opt or cgroup)
    if oh:
        src_col, internal = "open_hours", "open_hours (total_open_hours)"
    elif opt:
        src_col, internal = _OPTIONAL[opt]["column"], _OPTIONAL[opt]["internal"]
    else:
        src_col = "qty" if cgroup in ("LAG", "ROLLING") else None
        internal = "order_qty" if cgroup in ("LAG", "ROLLING") else None
    return {
        "feature_key": name, "kind": "MODEL",
        "feature_group": "SKU_AVAILABILITY" if oh else ("CUSTOMER_BEHAVIOUR" if opt == "customer" else
                                                        "PRICE_PROMOTION" if opt else "DEMAND_HISTORY"),
        "catalog_group": cgroup, "display_name": {"vi": d["vi"]["name"], "en": d["en"]["name"]},
        "description": {"vi": d["vi"]["formula"], "en": d["en"]["formula"]}, "data_type": "float",
        "source_name": "demand_daily (tổng hợp SKU × FC × ngày của nguồn đang chọn)",
        "source_column": src_col, "internal_field": internal,
        "required": cgroup == "IDENTITY" or (oh and bool(((decisions or {}).get("open_hours") or {}).get("mandatory"))),
        "switch": toggle,
        "default_or_missing_policy": {"vi": d["vi"]["missing"], "en": d["en"]["missing"]},
        "aggregation_rule": _AGGREGATION.get(key), "time_availability": _AVAILABILITY.get(key),
        "effective_from": None, "effective_to": None, "created_at": "2026-10-14", "updated_at": REGISTRY_VERSION[:10],
        "registry_version": REGISTRY_VERSION, "availability_status": status, "status_label": _labels(STATUSES, status),
        "reason": reason, "reason_label": _labels(REASONS, reason),
    }


def planned_entry(p: dict, source: str | None, bq=None, validation: dict | None = None) -> dict:
    col = None
    status, reason = "PLANNED", "NO_SOURCE_COLUMN"
    if p["reference"] and source == "BIGQUERY" and bq is not None:
        m = bq.reference_mapping.get(p["reference"])
        col = m.column if m and m.usage != "UNUSED" else None
        if col:
            comp = ((validation or {}).get("reference_completeness") or {}).get(p["reference"])
            if comp is None:
                reason = "COLUMN_MAPPED_NOT_VALIDATED"
            elif comp.get("non_null", 0) > 0:
                status, reason = "DISABLED", "HAS_SOURCE_DATA_NOT_ACTIVATED"
            else:
                status, reason = "UNAVAILABLE", "MAPPED_NO_DATA"
    return {
        "feature_key": p["key"], "kind": "PLANNED", "feature_group": p["group"], "catalog_group": None,
        "display_name": {"vi": p["vi"][0], "en": p["en"][0]}, "description": {"vi": p["vi"][1], "en": p["en"][1]},
        "data_type": p["data_type"], "source_name": "BIGQUERY" if col else None, "source_column": col,
        "reference_field": p["reference"], "internal_field": None, "required": False, "switch": None,
        "default_or_missing_policy": None, "aggregation_rule": None,
        "time_availability": "Phải xác định được giá trị tại thời điểm dự báo trước khi kích hoạt.",
        "effective_from": None, "effective_to": None, "created_at": REGISTRY_VERSION[:10], "updated_at": REGISTRY_VERSION[:10],
        "registry_version": REGISTRY_VERSION, "availability_status": status, "status_label": _labels(STATUSES, status),
        "reason": reason, "reason_label": _labels(REASONS, reason),
    }


def view(conn, source: str | None = None) -> dict:
    """Registry with statuses for the active (or given) source, plus the feature set the next training would use."""
    import json
    from .. import settings_service as ss
    from ..data.demand import resolve_scope
    from ..messages import AppError
    mcfg = ss.get("model", conn)
    g = ss.get("general", conn)
    src = source or g.active_source
    scope, scope_error, cov = None, None, {"rows": 0}
    try:
        scope = resolve_scope(conn, src)
        cov = coverage(conn, scope["scope_key"])
    except AppError as e:
        scope_error = e.to_dict()
    resolved, decisions = resolve(mcfg, cov)
    # 1.2.9: SKU open hours - mandatory for the BIGQUERY source (same check as the training: every row of the window)
    from ..data import open_hours, open_hours_override
    from ..data.demand import data_window
    mand = open_hours.mandatory(src)
    chk = None
    if mand and scope:
        w = data_window(conn, scope=scope)       # 1.2.9b: same start rule as the training
        # 1.2.12: same check as the training, with the owner's adhoc rule for six exact keys
        ovr = open_hours_override.resolve(conn, scope["scope_key"], w["start"], w["end"])
        chk = open_hours.window_check(conn, scope["scope_key"], w["start"], w["end"], overrides=ovr["applied"])
        chk["override"] = open_hours_override.summary(ovr) if ovr["applies_to_scope"] else None
    decisions["open_hours"] = {"mandatory": mand, "ok": bool(chk and chk["ok"]), "window_check": chk,
                               "used": bool(chk and chk["ok"]), "reason": ("NOT_IN_SOURCE" if not mand else
                                                                          "MANDATORY_DATA_OK" if chk and chk["ok"]
                                                                          else "MANDATORY_NOT_READY"),
                               "features": list(OPEN_HOURS)}
    resolved = resolved.model_copy(update={"feature_open_hours": mand, "weekday_encoding": "ISO"})
    names = feature_names(resolved)
    bq = ss.get("bigquery", conn) if src == "BIGQUERY" else None
    validation = None
    if bq is not None:
        r = conn.execute("SELECT value_json FROM sync_state WHERE name='bq_validation'").fetchone()
        validation = json.loads(r[0]) if r else None
    active_model = None
    if scope:
        tr = conn.execute("SELECT id, model_version, feature_config_json FROM training_runs WHERE scope_key=? AND "
                          "status='ACCEPTED' ORDER BY started_at DESC, rowid DESC LIMIT 1", (scope["scope_key"],)).fetchone()
        if tr:
            fc = json.loads(tr[2] or "{}")
            feats = fc.get("features") or []
            active_model = {"training_run_id": tr[0], "model_version": tr[1], "features": feats,
                            "feature_set_version": fc.get("feature_set_version") or feature_set_version(feats),
                            "feature_set_version_stored": bool(fc.get("feature_set_version"))}
    entries = [model_feature_entry(n, mcfg, decisions, cov.get("rows")) for n in all_model_features()]
    used_by_model = set((active_model or {}).get("features") or [])
    for e in entries:
        e["in_active_model"] = e["feature_key"] in used_by_model if active_model else None
    entries += [planned_entry(p, src, bq, validation) for p in PLANNED]
    for e in entries:
        e["in_active_model"] = e.get("in_active_model", False if active_model else None)
    counts = {s: sum(1 for e in entries if e["availability_status"] == s) for s in STATUSES}
    return {"registry_version": REGISTRY_VERSION, "feature_code_version": FEATURE_CODE_VERSION, "source": src,
            "scope": scope, "scope_error": scope_error, "coverage": cov, "decisions": decisions,
            "next_training": {"features": names, "n_features": len(names), "feature_set_version": feature_set_version(names),
                              "blocked_by": None if (not mand or decisions["open_hours"]["ok"]) else "OPEN_HOURS_INVALID"},
            "active_model": active_model, "groups": {k: {"vi": v[0], "en": v[1]} for k, v in GROUPS.items()},
            "statuses": {k: {"vi": v[0], "en": v[1]} for k, v in STATUSES.items()}, "counts": counts, "entries": entries}
