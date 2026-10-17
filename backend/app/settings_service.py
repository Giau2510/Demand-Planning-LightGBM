"""Centralised, validated, persisted configuration (one JSON document per section + full history).

Nothing in here is secret: BigQuery uses Application Default Credentials (or the *path* to a key file
kept outside the repository). Secrets are never stored in the DB or sent to the frontend.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import db
from .timeutil import now_iso

DEFAULT_HORIZON_CHOICES = [1, 3, 7, 14, 15, 21, 28, 30, 45, 60, 90, 180, 365]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,299}$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9\-]{4,61}[a-z0-9]$")
INTERNAL_FIELDS = ["order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price",
                   "discount_amount", "promotion_flag", "promotion_id", "voucher_flag", "voucher_amount",
                   "source_updated_at", "batch_id"]
# Reference columns: read for validation / reconciliation / future features only. They are NEVER the target and
# never a model input until a feature using them is explicitly activated (see ml/feature_registry.py).
REFERENCE_FIELDS = ["product_id", "item_code", "outbound_qty", "order_status", "sales_price", "price_after_discount",
                    "seller_code", "sku_status", "open_date", "open_hours", "open_days"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# full BigQuery table id project.dataset.table (1.2.0 source tables of the D-1 and D-0 feeds)
TABLE_ID_RE = re.compile(r"^([a-z][a-z0-9\-]{4,61}[a-z0-9])\.([A-Za-z_][A-Za-z0-9_]{0,1023})\.([A-Za-z_][A-Za-z0-9_]{0,1023})$")
# 1.2.1: fields the D-0 feed reads, mapped to the D-0 output's OWN column names (never through the D-1 mapping).
# Essential: SKU, FC, quantity and the day of the line (order_date, or created_at when only a timestamp exists).
D0_FIELDS = ["sku_id", "fc_id", "order_qty", "order_date", "created_at", "order_id", "source_updated_at"]
D0_ESSENTIAL = ("sku_id", "fc_id", "order_qty")


class GeneralSettings(BaseModel):
    active_source: Literal["DEMO", "MANUAL_IMPORT", "BIGQUERY"] = "DEMO"
    active_import_batch_id: str | None = None
    timezone: Literal["Asia/Ho_Chi_Minh"] = "Asia/Ho_Chi_Minh"


class HorizonSettings(BaseModel):
    choices: list[int] = Field(default_factory=lambda: list(DEFAULT_HORIZON_CHOICES))
    enabled: list[int] = Field(default_factory=lambda: [7, 15, 30])
    max_allowed_days: int = Field(365, ge=1, le=730)
    max_forecast_rows: int = Field(5_000_000, ge=1000)

    @model_validator(mode="after")
    def _check(self):
        for v in self.choices + self.enabled:
            if v < 1 or v > self.max_allowed_days:
                raise ValueError(f"horizon {v} must be an integer between 1 and {self.max_allowed_days}")
        self.choices = sorted(set(self.choices))
        self.enabled = sorted(set(self.enabled))
        missing = [v for v in self.enabled if v not in self.choices]
        if missing:
            raise ValueError(f"enabled horizons {missing} are not in the choice list")
        if not self.enabled:
            raise ValueError("at least one horizon must be enabled")
        return self


class QualitySettings(BaseModel):
    """Quality gate. Initial values are EXAMPLES for testing only — not business-approved."""
    wape_max: float = Field(0.60, gt=0, le=10)
    abs_bias_max: float = Field(0.20, ge=0, le=10)
    min_backtest_points: int = Field(200, ge=1)
    require_beat_baseline: bool = False
    mape_min_actual: float = Field(1.0, gt=0)
    approved_by_business: bool = False


class ModelSettings(BaseModel):
    feature_lags: bool = True
    feature_rolling: bool = True
    feature_calendar: bool = True
    feature_price: bool = True
    feature_promotion: bool = True
    # None = legacy behaviour (disc_last follows feature_price); training stores the resolved True/False
    feature_discount: bool | None = None
    # a price/discount/promotion group is used only when at least this share of the scope's demand rows has the value
    feature_min_coverage: float = Field(0.5, gt=0, le=1)
    min_total_history_days: int = Field(56, ge=14)
    min_series_history_days: int = Field(28, ge=7)
    intermittent_zero_share: float = Field(0.80, gt=0, le=1)
    inactive_days: int = Field(60, ge=7)
    fallback_window_days: int = Field(28, ge=7)
    # 1.1.7: walk-forward over up to 12 consecutive 30-day windows (up to ~12 months); folds whose origin has less than
    # min_total_history_days of history are skipped, so the span is the longest one the data window allows
    backtest_folds: int = Field(12, ge=1, le=12)
    backtest_horizon_days: int = Field(30, ge=1, le=90)
    backtest_step_days: int = Field(30, ge=1, le=90)
    num_boost_round: int = Field(300, ge=10, le=5000)
    learning_rate: float = Field(0.05, gt=0, le=1)
    num_leaves: int = Field(31, ge=4, le=1024)
    objective: Literal["tweedie", "poisson", "regression", "regression_l1"] = "tweedie"
    max_train_days: int = Field(730, ge=60, le=3650)
    num_threads: int = Field(0, ge=0, le=64)
    # 1.2.0: how the multi-day forecast is produced. RECURSIVE (every model before 1.2.0): a one-day model whose own
    # forecasts feed the lags of the next days. DIRECT: one model for every horizon day - features computed at the
    # forecast origin, calendar of the target day and the horizon as a feature; trained on `direct_origins` origins
    # taken every `direct_origin_step_days` days before the end of the data (experiment L7_direct, 16/10/2026)
    forecast_strategy: Literal["RECURSIVE", "DIRECT"] = "RECURSIVE"
    direct_origins: int = Field(12, ge=1, le=52)
    direct_origin_step_days: int = Field(7, ge=1, le=30)

    @model_validator(mode="after")
    def _feature_groups(self):
        # feature groups (1.2.0 UI): historical demand = lags + rolling statistics; price. Calendar and the SKU / FC
        # codes alone do not describe demand: at least one of the two groups must stay on
        if not (self.feature_lags or self.feature_rolling or self.feature_price):
            raise ValueError("FEATURE_GROUPS_EMPTY: turn on 'historical demand' or 'price'")
        return self


class ImportSettings(BaseModel):
    max_file_mb: int = Field(50, ge=1, le=500)
    max_rows: int = Field(2_000_000, ge=10)
    grain_conflict_policy: Literal["ERROR", "SUM"] = "ERROR"
    column_aliases: dict[str, list[str]] = Field(default_factory=lambda: {
        "created_at": ["order_created_at", "created_time"],
        "sku_id": ["sku", "sku_code"],
        "fc_id": ["fc", "warehouse_id", "warehouse"],
        "order_qty": ["qty", "quantity"],
    })


class DataPolicySettings(BaseModel):
    stale_check_sources: list[Literal["DEMO", "MANUAL_IMPORT", "BIGQUERY"]] = Field(default_factory=lambda: ["BIGQUERY"])
    max_data_lag_days: int = Field(2, ge=1, le=60)
    late_data_lookback_days: int = Field(3, ge=0, le=60)
    min_date: str | None = None
    price_outlier_factor: float = Field(10.0, gt=1)
    # 1.1.7: first business date used as MODEL INPUT (training, backtest, forecast panel, data-quality report) and the
    # floor of BigQuery reads. Stored history before it is kept untouched - it is only not used. The window ends with
    # the last COMPLETE Vietnam day (yesterday): today's partial day is D0-only, future dates are never used.
    window_start_date: str = "2026-01-01"

    @field_validator("window_start_date")
    @classmethod
    def _window_start(cls, v):
        if not v or not DATE_RE.match(v):
            raise ValueError("window_start_date must be YYYY-MM-DD")
        from datetime import date as _d
        _d.fromisoformat(v)
        return v


class ScheduleSettings(BaseModel):
    """Automatic flows, each with its OWN switch (1.1.8): D-1 (closed days), D-0 (today) and daily training.
    Switches are changed only through /api/schedules (readiness checked), never by the generic settings editor."""
    # 1.1.6/1.1.7: ONE switch for every automatic job. Kept only so that a rollback to an older version behaves as
    # before; 1.1.8 does not use it for planning (it only seeds train_enabled when that key is missing).
    enabled: bool = True
    d1_enabled: bool = False      # OFF until the user turns it on (requires a ready BigQuery source)
    d0_enabled: bool = False      # OFF until the user turns it on
    train_enabled: bool = True    # missing in older stored settings -> takes the old `enabled` (never OFF -> ON)
    # moment each flow was switched ON (ISO, Vietnam time). Slots before it are neither run nor "missed": switching a
    # flow on never triggers a run by itself. None = ON since before 1.1.8 (old behaviour).
    d1_enabled_at: str | None = None
    d0_enabled_at: str | None = None
    train_enabled_at: str | None = None
    d0_times: list[str] = Field(default_factory=lambda: ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"])
    d1_signal_poll_start: str = "01:00"
    d1_poll_interval_minutes: int = Field(30, ge=5, le=240)
    d1_fallback_time: str = "06:00"
    train_time: str = "07:00"
    slot_grace_minutes: int = Field(20, ge=1, le=180)
    d0_catchup_policy: Literal["LATEST_ONCE", "SKIP"] = "LATEST_ONCE"
    train_catchup_policy: Literal["RUN_ONCE", "SKIP"] = "RUN_ONCE"
    max_attempts: int = Field(4, ge=1, le=20)
    retry_base_seconds: int = Field(60, ge=1, le=3600)
    retry_max_seconds: int = Field(1800, ge=1, le=86400)
    timeout_seconds: int = Field(3600, ge=30, le=6 * 3600)
    max_catchup_jobs_per_tick: int = Field(1, ge=1, le=10)

    @field_validator("d1_signal_poll_start", "d1_fallback_time", "train_time")
    @classmethod
    def _hhmm(cls, v):
        if not HHMM.match(v):
            raise ValueError("time must be HH:MM (24h)")
        return v

    @field_validator("d0_times")
    @classmethod
    def _times(cls, v):
        for t in v:
            if not HHMM.match(t):
                raise ValueError(f"invalid time {t!r}, expected HH:MM")
        if len(set(v)) > 24:
            raise ValueError("at most 24 D-0 times per day")
        return sorted(set(v))

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data):
        # settings saved by 1.1.7 or older have no per-flow switches: training keeps the state of the old global
        # switch; D-1 and D-0 stay OFF (defaults). Nothing that was OFF becomes ON.
        if isinstance(data, dict) and "train_enabled" not in data:
            data = {**data, "train_enabled": bool(data.get("enabled", True))}
        return data

    @model_validator(mode="after")
    def _d0_needs_times(self):
        if self.d0_enabled and not self.d0_times:
            raise ValueError("D-0 is enabled but has no time")
        return self


class FieldMapping(BaseModel):
    column: str | None = None
    usage: Literal["REQUIRED", "OPTIONAL", "UNUSED"] = "OPTIONAL"


def _default_reference_mapping() -> dict[str, FieldMapping]:
    return {f: FieldMapping(column=None, usage="OPTIONAL") for f in REFERENCE_FIELDS}


def _default_mapping() -> dict[str, FieldMapping]:
    req = {"created_at", "sku_id", "fc_id", "order_qty"}
    return {f: FieldMapping(column=None, usage="REQUIRED" if f in req else ("UNUSED" if f == "order_date" else "OPTIONAL"))
            for f in INTERNAL_FIELDS}


# Columns of the D-0 table demand_planing_lightgbm_D0 as read from BigQuery metadata on 17/10/2026 (12 columns:
# fc_code, created_date DATE, so_code, sku_code, demand_quantity INTEGER, ...). Only a pre-fill: every D-0 SQL
# validation and every D-0 table check compares the mapping with the REAL output schema again.
D0_DEFAULT_COLUMNS = {"sku_id": "sku_code", "fc_id": "fc_code", "order_qty": "demand_quantity",
                      "order_date": "created_date", "order_id": "so_code"}


def _default_d0_mapping() -> dict[str, FieldMapping]:
    return {f: FieldMapping(column=D0_DEFAULT_COLUMNS.get(f),
                            usage="REQUIRED" if f in D0_ESSENTIAL else ("UNUSED" if f == "created_at" else "OPTIONAL"))
            for f in D0_FIELDS}


class BigQuerySettings(BaseModel):
    project_id: str = "lakehouse-prod-394907"
    dataset_id: str = ""
    location: str = ""
    source_table: str = ""
    auth_method: Literal["ADC", "SERVICE_ACCOUNT_FILE"] = "ADC"
    service_account_file: str = ""   # path only; the key never enters the repo or the DB
    field_mapping: dict[str, FieldMapping] = Field(default_factory=_default_mapping)
    created_at_is_utc: bool = True
    partition_column: str = ""
    completion_table: str = ""
    completion_date_column: str = ""
    completion_status_column: str = ""
    completion_status_value: str = ""
    fallback_min_rows_ratio: float = Field(0.5, ge=0, le=1)
    initial_history_days: int = Field(730, ge=7, le=3650)
    maximum_bytes_billed: int = Field(20 * 1024 ** 3, ge=10 * 1024 ** 2)
    query_timeout_seconds: int = Field(300, ge=10, le=3600)
    preview_rows: int = Field(50, ge=1, le=500)
    production_enabled: bool = False
    schema_snapshot: list[dict] = Field(default_factory=list)
    # --- 1.1.5 (new top-level keys: older versions ignore them, so a rollback keeps working)
    reference_mapping: dict[str, FieldMapping] = Field(default_factory=_default_reference_mapping)
    history_start_date: str = "2026-01-01"     # first day read from the source ("" = no lower bound)
    exact_duplicate_policy: Literal["BLOCK", "KEEP", "DROP_EXACT"] = "BLOCK"
    max_retries: int = Field(2, ge=0, le=5)     # transient errors only (unavailable / rate limit)
    max_null_share: float = Field(0.05, ge=0, le=1)
    # --- 1.1.6 (top-level keys, ignored by older versions). OAuth "Sign in with Google" for the Windows user that runs
    # the app. Only the client ID is stored here; the client secret and the refresh token live in Windows Credential
    # Manager (DPAPI, per Windows account) and never in the DB, logs or the frontend.
    oauth_enabled: bool = False
    oauth_client_id: str = ""
    # --- 1.2.0: table of the D-0 feed (today, intraday), full id project.dataset.table; read only by D0_SYNC when the
    # D-0 feed is in TABLE mode. The D-1 table stays project_id / dataset_id / source_table (scope key unchanged).
    d0_table_id: str = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0"
    # --- 1.2.1: the D-0 feed's own mapping (output column per D0_FIELDS). Independent of field_mapping: the D-0 output
    # may have fewer / other columns than D-1. Not part of the D-1 mapping hash (changing it never touches D-1).
    d0_mapping: dict[str, FieldMapping] = Field(default_factory=_default_d0_mapping)

    @field_validator("d0_mapping")
    @classmethod
    def _d0_map(cls, v):
        for k, m in v.items():
            if k not in D0_FIELDS:
                raise ValueError(f"unknown D-0 field {k}")
            if m.column and not IDENT.match(m.column):
                raise ValueError(f"invalid column name for D-0 field {k}")
        for k in D0_FIELDS:
            v.setdefault(k, FieldMapping(column=None, usage="OPTIONAL"))
        return v

    @field_validator("d0_table_id")
    @classmethod
    def _d0_table(cls, v):
        v = (v or "").strip()
        if v and not TABLE_ID_RE.match(v):
            raise ValueError("d0_table_id must be project.dataset.table")
        return v

    @field_validator("oauth_client_id")
    @classmethod
    def _client_id(cls, v):
        v = (v or "").strip()
        if v and not re.match(r"^[0-9A-Za-z\-_.]+\.apps\.googleusercontent\.com$", v):
            raise ValueError("OAuth client ID must look like <id>.apps.googleusercontent.com")
        return v

    @field_validator("history_start_date")
    @classmethod
    def _start(cls, v):
        if v:
            if not DATE_RE.match(v):
                raise ValueError("history_start_date must be YYYY-MM-DD")
            from datetime import date as _d
            _d.fromisoformat(v)
        return v

    @field_validator("reference_mapping")
    @classmethod
    def _ref(cls, v):
        for k, m in v.items():
            if k not in REFERENCE_FIELDS:
                raise ValueError(f"unknown reference field {k}")
            if m.column and not IDENT.match(m.column):
                raise ValueError(f"invalid column name for {k}")
            if m.usage == "REQUIRED":
                raise ValueError(f"reference field {k} cannot be REQUIRED")
        for k in REFERENCE_FIELDS:
            v.setdefault(k, FieldMapping())
        return v

    @field_validator("project_id")
    @classmethod
    def _proj(cls, v):
        if v and not PROJECT_RE.match(v):
            raise ValueError("invalid GCP project id")
        return v

    @field_validator("dataset_id", "source_table", "partition_column", "completion_table",
                     "completion_date_column", "completion_status_column")
    @classmethod
    def _ident(cls, v):
        if v and not IDENT.match(v):
            raise ValueError("only letters, digits and underscore are allowed")
        return v

    @field_validator("field_mapping")
    @classmethod
    def _mapping(cls, v):
        for k, m in v.items():
            if k not in INTERNAL_FIELDS:
                raise ValueError(f"unknown internal field {k}")
            if m.column and not IDENT.match(m.column):
                raise ValueError(f"invalid column name for {k}")
        for k in INTERNAL_FIELDS:
            v.setdefault(k, FieldMapping())
        for k in ("sku_id", "fc_id", "order_qty"):
            if v[k].usage == "UNUSED":
                raise ValueError(f"{k} is mandatory and cannot be UNUSED")
        if v["created_at"].usage == "UNUSED" and v["order_date"].usage == "UNUSED":
            raise ValueError("either created_at or order_date must be used")
        return v


MAX_SQL_VERSIONS = 50
D0_USER_SQL_FILE = "d0_user_sql_20261015.sql"
D0_PROPOSED_SQL_FILE = "d0_proposed_v2_20261015.sql"


class SqlVersion(BaseModel):
    """One saved SQL text. Saving never activates it: only a successful BigQuery validation does."""
    id: int
    sql: str = Field(max_length=100_000)
    sha256: str
    saved_at: str | None = None
    note: str | None = None
    validation: dict | None = None      # {status: VALID|INVALID, checked_at, statement_type, estimated_bytes, columns, error}


class SqlSource(BaseModel):
    mode: Literal["TABLE", "SQL"] = "TABLE"
    versions: list[SqlVersion] = Field(default_factory=list)
    active_version_id: int | None = None       # last version that PASSED validation; used by the scheduler
    # candidate unique key (output column names); empty = derived from the field mapping (order, SKU, FC, date)
    key_columns: list[str] = Field(default_factory=list)
    key_duplicate_policy: Literal["BLOCK", "SUM_ALL"] = "BLOCK"
    # scheduled runs of this feed on BigQuery (D0): OFF until the user turns it on after a successful validation
    schedule_enabled: bool = False

    @field_validator("key_columns")
    @classmethod
    def _keys(cls, v):
        for k in v:
            if not IDENT.match(k):
                raise ValueError(f"invalid key column {k!r}")
        return v


def _sha(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _d0_seed() -> SqlSource:
    """The D0 SQL given by the user (15/10/2026), stored VERBATIM as version 1 and NOT validated / NOT active."""
    from pathlib import Path
    d = Path(__file__).resolve().parent / "bq"
    text = (d / D0_USER_SQL_FILE).read_text(encoding="utf-8").rstrip("\n")
    prop = (d / D0_PROPOSED_SQL_FILE).read_text(encoding="utf-8").rstrip("\n")
    return SqlSource(mode="SQL", versions=[
        SqlVersion(id=1, sql=text, sha256=_sha(text), saved_at=None,
                   note="SQL D0 do người dùng cung cấp (yêu cầu ngày 15/10/2026) — lưu nguyên văn, chưa kiểm tra"),
        SqlVersion(id=2, sql=prop, sha256=_sha(prop), saved_at=None,
                   note="ĐỀ XUẤT hiệu chỉnh (15/10/2026) — chưa xác nhận nghiệp vụ, chưa kiểm tra, KHÔNG tự kích hoạt")],
        key_columns=[])


class SqlSourcesSettings(BaseModel):
    # history = order LINES: several lines of one order x SKU x FC x day are normal and summed (business rule
    # confirmed 16/10/2026); only fully identical rows are a data error (exact-duplicate gate). BLOCK stays selectable.
    history: SqlSource = Field(default_factory=lambda: SqlSource(mode="TABLE", key_duplicate_policy="SUM_ALL"))
    d0: SqlSource = Field(default_factory=_d0_seed)


SECTIONS: dict[str, type[BaseModel]] = {
    "sql_sources": SqlSourcesSettings,
    "general": GeneralSettings,
    "horizons": HorizonSettings,
    "quality": QualitySettings,
    "model": ModelSettings,
    "import": ImportSettings,
    "data_policy": DataPolicySettings,
    "schedule": ScheduleSettings,
    "bigquery": BigQuerySettings,
}


def get(section: str, conn=None):
    cls = SECTIONS[section]
    def _load(c):
        r = c.execute("SELECT value_json FROM app_settings WHERE section=?", (section,)).fetchone()
        if not r:
            return cls()
        data = json.loads(r[0])
        return cls.model_validate(data)
    if conn is not None:
        return _load(conn)
    with db.read() as c:
        return _load(c)


def save(section: str, value: dict | BaseModel, note: str | None = None, conn=None):
    cls = SECTIONS[section]
    model = value if isinstance(value, cls) else cls.model_validate(value)
    js = model.model_dump_json()

    def _save(c):
        c.execute("INSERT INTO app_settings(section, value_json, updated_at) VALUES (?,?,?) "
                  "ON CONFLICT(section) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (section, js, now_iso()))
        c.execute("INSERT INTO settings_history(section, value_json, changed_at, note) VALUES (?,?,?,?)",
                  (section, js, now_iso(), note))
        db.audit(c, "SETTINGS_SAVED", "settings", section, {"note": note})
    if conn is not None:
        _save(conn)
    else:
        with db.tx() as c:
            _save(c)
    return model


def update(section: str, patch: dict, note: str | None = None, conn=None):
    cur = get(section, conn).model_dump()
    cur.update(patch)
    return save(section, cur, note, conn)


def history(section: str, limit: int = 50) -> list[dict]:
    with db.read() as c:
        out = db.rows(c, "SELECT id, value_json, changed_at, note FROM settings_history WHERE section=? "
                         "ORDER BY id DESC LIMIT ?", (section, limit))
    for r in out:
        r["value"] = json.loads(r.pop("value_json"))
    return out


def reset(section: str, note: str = "reset to defaults"):
    return save(section, SECTIONS[section](), note)
