"""1.4.15 (lot 2): the settings registry ("so truong") - every setting field WITHOUT a box of its own in the UI, with its
risk level, plain-language label / description (vi + en, with the consequence of a change) and its rules.

Risk levels (api/settings_advanced_routes.py applies them):
  LOW      - acknowledged = true ("Toi hieu").
  HIGH     - typed DOI-CAI-DAT-AN-<Vietnam day> + reason >= 10 characters.
  PURCHASE - changes the forecast numbers / the purchase file / the training: typed
             DOI-CAI-DAT-ANH-HUONG-MUA-HANG-<Vietnam day> + reason >= 10 characters.
  READONLY - shown only, with its reason (fixed rule, internal state written by the system, or a source table that needs
             its own "Kiem tra" button, rule 19).
  OWN_PATH - has its own guarded path (flow switches, trial_mode, d0_paused_*, active_import_batch_id, production_enabled,
             OAuth, source tables): shown, never changed here.
Every field of every section of settings_service.SECTIONS (except sql_sources / feature_table, which have their own API)
is in exactly ONE of: this registry (ENTRIES), VISIBLE (own box in the UI, file:line), EXCLUDED (never exported /
imported / changed here: BigQuery connection and mapping) or DATA_POLICY (api/data_policy_routes.py + Config.tsx);
tests/test_v1415_settings_advanced.py fails when a new field is not classified.
The generic editor (PUT /api/settings/{section}) refuses a changed registry key (409 SETTINGS_FIELD_GUARDED) and its
reset keeps every registry key (api/data_routes.py).
"""
from __future__ import annotations

import typing
from dataclasses import dataclass
from pathlib import PureWindowsPath

from . import settings_service as ss

# spike cleaning (CLAUDE.md 18): owner decision 23/11/2026 - always editable at PURCHASE level (typed text + reason,
# preview, expected value, undo, busy gate), exported / imported like every PURCHASE key
SPIKE_KEYS = ("spike_cleaning", "spike_e4_n")

RISKS = ("LOW", "HIGH", "PURCHASE", "READONLY", "OWN_PATH")
EDITABLE = ("LOW", "HIGH", "PURCHASE")
RISK_ORDER = {"LOW": 1, "HIGH": 2, "PURCHASE": 3}
OWN_API_SECTIONS = ("sql_sources", "feature_table")      # own API, outside the registry check
SECTIONS_CHECKED = tuple(s for s in ss.SECTIONS if s not in OWN_API_SECTIONS)


@dataclass(frozen=True)
class Entry:
    section: str
    key: str
    risk: str
    label_vi: str
    label_en: str
    desc_vi: str                    # what it does + consequence of a change
    desc_en: str
    only_increase: bool = False     # a decrease deletes kept data: refused (RETENTION_DECREASE_NOT_ALLOWED)
    path_rule: str | None = None    # NAME = one folder name; SUBDIR = relative folder (no drive, root, '..')
    reason_code: str | None = None  # READONLY / OWN_PATH: why it is not changed here (messages.py code)
    own_path: str | None = None     # where it is changed instead (API / UI file:line)


def _e(section, key, risk, label_vi, label_en, desc_vi, desc_en, **kw) -> Entry:
    return Entry(section, key, risk, label_vi, label_en, desc_vi, desc_en, **kw)


_SCHED_UI = "PUT /api/schedules/{flow} (Schedules.tsx:{line})"
_SRC_TABLES = "PUT /api/bigquery/source-tables/{kind} (BigQuery.tsx:195)"
_SPIKE_VI = "Đổi hai trường này làm thay đổi dữ liệu học của mô hình (lọc đơn đột biến theo từng SKU×kho theo N); áp dụng từ lượt học kế tiếp; hoàn tác chỉ trả cài đặt, không trả lại kết quả đã học."
_SPIKE_EN = "Changing these two fields changes the model's training data (spike orders filtered per SKU×FC by N); it applies from the next training; an undo restores the setting only, not what was already trained."
_NEXT = "Áp dụng từ lượt chạy kế tiếp."
_NEXT_EN = "Applies from the next run."

ENTRIES: tuple[Entry, ...] = (
    # ---------------------------------------------------------------- horizons
    _e("horizons", "max_forecast_rows", "HIGH", "Số dòng dự báo tối đa mỗi lần", "Maximum forecast rows per run",
       "Giới hạn an toàn số dòng một lần dự báo được ghi; đặt thấp hơn số SKU×kho×ngày thực tế thì lần dự báo bị từ chối.",
       "Safety cap on the rows one forecast run writes; below the real SKU×FC×days count the run is refused."),
    # ---------------------------------------------------------------- model (1.3.1 training / refresh with the model in use)
    _e("model", "feature_calendar", "PURCHASE", "Nhóm đặc trưng lịch", "Calendar feature group",
       "Bật / tắt đặc trưng lịch (tháng, ngày lễ...) của mô hình LightGBM 1.3.1; đổi số dự báo ở lần học kế tiếp.",
       "Turns the calendar features of the 1.3.1 LightGBM model on/off; changes the forecast from the next training."),
    _e("model", "feature_promotion", "PURCHASE", "Đặc trưng khuyến mãi", "Promotion feature",
       "Dùng cờ khuyến mãi làm đầu vào mô hình; đổi số dự báo ở lần học kế tiếp.",
       "Uses the promotion flag as a model input; changes the forecast from the next training."),
    _e("model", "feature_discount", "PURCHASE", "Đặc trưng giảm giá", "Discount feature",
       "Trống = theo nhóm giá (như trước); bật / tắt riêng giảm giá; đổi số dự báo ở lần học kế tiếp.",
       "Empty = follows the price group (as before); switches the discount on/off; changes the forecast from the next training."),
    _e("model", "feature_min_coverage", "PURCHASE", "Tỷ lệ phủ tối thiểu của đặc trưng", "Minimum feature coverage",
       "Nhóm giá / giảm giá / khuyến mãi chỉ được dùng khi ít nhất tỷ lệ này số dòng có giá trị; đổi đầu vào mô hình.",
       "A price / discount / promotion group is used only when at least this share of rows has it; changes the model input."),
    _e("model", "num_threads", "PURCHASE", "Số luồng CPU khi học", "CPU threads for training",
       "0 = tự động. Đổi số luồng làm mô hình học ra khác (kết quả không trùng tuyệt đối) và đổi mức dùng CPU / RAM.",
       "0 = automatic. A different thread count trains a slightly different model and changes CPU / RAM use."),
    _e("model", "horizon_weight_short", "PURCHASE", "Trọng số ngày gần", "Short-horizon weight",
       "Chỉ cho chiến lược DIRECT: các dòng học có tầm dự báo <= ngưỡng được nhân trọng số này; đặt cùng ngưỡng hoặc để trống cả hai.",
       "DIRECT only: training rows whose horizon <= the cutoff get this weight; set with the cutoff or leave both empty."),
    _e("model", "horizon_weight_cutoff", "PURCHASE", "Ngưỡng ngày gần", "Short-horizon cutoff",
       "Tầm dự báo (ngày) tối đa nhận trọng số ngày gần; đổi số dự báo ở lần học kế tiếp.",
       "Largest horizon (days) that gets the short-horizon weight; changes the forecast from the next training."),
    _e("model", "feature_sku_code", "PURCHASE", "Mã SKU làm đầu vào", "SKU code as input",
       "Dùng mã SKU làm đặc trưng của mô hình; tắt đi đổi số dự báo ở lần học kế tiếp.",
       "Uses the SKU code as a model feature; turning it off changes the forecast from the next training."),
    _e("model", "fallback_enabled", "PURCHASE", "Quy tắc dự phòng", "Fallback rules",
       "Bật: chuỗi ngừng bán / mới / gián đoạn dùng phương pháp dự phòng; tắt: mọi chuỗi do LightGBM dự báo.",
       "On: inactive / new / intermittent series use the fallback; off: every series is forecast by LightGBM."),
    _e("model", "feature_open_hours", "READONLY", "Giờ mở bán làm đầu vào", "Open hours as input",
       "Đầu vào bắt buộc của nguồn BigQuery; do lần học ghi trên bản lưu kèm lần học, không phải công tắc.",
       "Mandatory input of the BigQuery source; written by the training on its own copy, not a switch.",
       reason_code="REG_SET_BY_TRAINING", own_path="training run"),
    _e("model", "weekday_encoding", "READONLY", "Cách mã hóa thứ trong tuần", "Weekday encoding",
       "Do lần học ghi (ISO 1 = Thứ Hai ... 7 = Chủ nhật).", "Written by the training (ISO 1 = Monday ... 7 = Sunday).",
       reason_code="REG_SET_BY_TRAINING", own_path="training run"),
    _e("model", "feature_table", "READONLY", "Bảng đặc trưng của lần học", "Feature table of the run",
       "Bản chụp bảng đặc trưng do lần học ghi; bảng sửa ở trang Đặc trưng.",
       "Snapshot of the feature table written by the training; the table is edited on the Features page.",
       reason_code="REG_SET_BY_TRAINING", own_path="PUT /api/feature-table"),
    # ---------------------------------------------------------------- import
    _e("import", "column_aliases", "HIGH", "Tên cột thay thế khi nhập Excel", "Column aliases for Excel import",
       "Tên cột khác được tự nhận là trường nào khi nhập Excel; sai có thể ánh xạ nhầm cột (số lượng, SKU, kho).",
       "Other column names recognised as each field when importing Excel; a wrong alias can map the wrong column."),
    # ---------------------------------------------------------------- schedule (night schedule)
    _e("schedule", "d1_signal_poll_start", "HIGH", "Giờ bắt đầu chờ tín hiệu D-1", "D-1 signal poll start",
       "Giờ (VN) bắt đầu hỏi bảng tín hiệu D-1; đổi giờ chạy cả chuỗi đêm (D-1, dự báo, Excel). " + _NEXT,
       "Time (Vietnam) the D-1 signal is first polled; moves the whole night chain (D-1, forecast, Excel). " + _NEXT_EN,
       own_path=_SCHED_UI.format(flow="d1", line=237)),
    _e("schedule", "d1_poll_interval_minutes", "HIGH", "Chu kỳ hỏi tín hiệu D-1 (phút)", "D-1 poll interval (minutes)",
       "Khoảng cách giữa hai lần hỏi tín hiệu D-1; dài hơn thì D-1 chạy muộn hơn.",
       "Minutes between two D-1 signal polls; longer = D-1 may run later.",
       own_path=_SCHED_UI.format(flow="d1", line=239)),
    _e("schedule", "d1_fallback_time", "HIGH", "Giờ chạy D-1 dự phòng", "D-1 fallback time",
       "Không có tín hiệu tới giờ này thì D-1 chạy theo dự phòng (có chốt số dòng).",
       "Without a signal by this time D-1 runs as fallback (row-count gate).",
       own_path=_SCHED_UI.format(flow="d1", line=238)),
    _e("schedule", "max_catchup_jobs_per_tick", "HIGH", "Số việc chạy bù mỗi nhịp", "Catch-up jobs per tick",
       "Số việc lỡ lịch được chạy bù trong một nhịp của bộ lập lịch; cao hơn = nhiều việc nặng chồng nhau hơn.",
       "Missed jobs caught up per scheduler tick; higher = more heavy jobs close together."),
    _e("schedule", "refresh_deadline", "HIGH", "Hạn chót làm mới dự báo", "Forecast refresh deadline",
       "Sau giờ này không thử làm mới dự báo nữa (ghi STALE_FORECAST).",
       "After this time the forecast refresh is no longer retried (STALE_FORECAST).",
       own_path=_SCHED_UI.format(flow="refresh", line=291)),
    _e("schedule", "refresh_retry_minutes", "HIGH", "Chu kỳ thử lại làm mới (phút)", "Refresh retry interval (minutes)",
       "Khoảng cách giữa hai lần thử làm mới dự báo khi D-1 chưa xong.", "Minutes between two refresh attempts while D-1 is not done.",
       own_path=_SCHED_UI.format(flow="refresh", line=292)),
    _e("schedule", "report_weekday", "LOW", "Thứ chạy báo cáo độ chính xác", "Accuracy report weekday",
       "Thứ trong tuần (1 = Thứ Hai) tạo báo cáo độ chính xác; chỉ đổi ngày tạo báo cáo.",
       "Weekday (1 = Monday) of the accuracy report; only moves the report.",
       own_path=_SCHED_UI.format(flow="report", line=303)),
    _e("schedule", "report_time", "LOW", "Giờ chạy báo cáo độ chính xác", "Accuracy report time",
       "Giờ (VN) tạo báo cáo độ chính xác; chỉ đổi giờ tạo báo cáo.", "Time (Vietnam) of the accuracy report; only moves the report.",
       own_path=_SCHED_UI.format(flow="report", line=307)),
    *(_e("schedule", k, "OWN_PATH", f"Công tắc luồng: {k}", f"Flow switch: {k}",
         "Công tắc / thời điểm bật của luồng tự động; chỉ đổi ở trang Lịch chạy (có kiểm tra sẵn sàng).",
         "Switch / switch-on time of an automatic flow; changed only on the Schedules page (readiness checked).",
         reason_code="REG_FLOW_SWITCH", own_path="PUT /api/schedules/{flow} (Schedules.tsx)")
      for k in ("d1_enabled", "d0_enabled", "train_enabled", "d1_enabled_at", "d0_enabled_at", "train_enabled_at",
                "eod_enabled", "close_enabled", "eod_enabled_at", "close_enabled_at", "refresh_enabled",
                "refresh_enabled_at", "report_enabled", "report_enabled_at")),
    _e("schedule", "d0_paused_until", "OWN_PATH", "D-0 tạm dừng tới", "D-0 paused until",
       "Hạn tạm dừng D-0 (tối đa 6 giờ, tự bật lại).", "End of the D-0 maintenance pause (at most 6 h, resumes by itself).",
       reason_code="REG_D0_PAUSE", own_path="POST /api/d0/pause | app.cli d0-pause"),
    _e("schedule", "d0_paused_by", "OWN_PATH", "Người tạm dừng D-0", "D-0 paused by",
       "Ai đặt lần tạm dừng D-0 hiện tại.", "Who set the current D-0 pause.",
       reason_code="REG_D0_PAUSE", own_path="POST /api/d0/pause | app.cli d0-pause"),
    _e("schedule", "d0_pause_windows", "READONLY", "Các khoảng D-0 đã tạm dừng", "Past D-0 pause windows",
       "Hệ thống ghi để không chạy bù các lượt D-0 trong lúc tạm dừng.", "Written by the system so paused D-0 slots are never caught up.",
       reason_code="REG_INTERNAL_STATE"),
    _e("schedule", "enabled", "READONLY", "Công tắc chung (cũ)", "Global switch (legacy)",
       "Chỉ giữ để quay về bản cũ; bản hiện tại không dùng.", "Kept only for a rollback to an old version; not used.",
       reason_code="REG_LEGACY"),
    # ---------------------------------------------------------------- bigquery (no connection / mapping)
    _e("bigquery", "max_retries", "LOW", "Số lần thử lại BigQuery", "BigQuery retries",
       "Số lần thử lại khi BigQuery lỗi tạm thời (mạng, giới hạn tần suất).", "Retries on transient BigQuery errors (network, rate limit)."),
    _e("bigquery", "query_timeout_seconds", "LOW", "Thời gian chờ truy vấn (giây)", "Query timeout (seconds)",
       "Truy vấn BigQuery chạy quá thời gian này thì bị dừng và báo lỗi.", "A BigQuery query running longer is stopped with an error."),
    _e("bigquery", "preview_rows", "LOW", "Số dòng xem trước", "Preview rows",
       "Số dòng hiện khi bấm Xem trước trên trang BigQuery; không ảnh hưởng dữ liệu.", "Rows shown by the BigQuery preview; no effect on data."),
    _e("bigquery", "fallback_min_rows_ratio", "HIGH", "Tỷ lệ dòng tối thiểu của D-1 dự phòng", "Fallback D-1 minimum row ratio",
       "Chốt chất lượng D-1: D-1 dự phòng chỉ nạp khi số dòng đạt tỷ lệ này so với bình thường; thấp hơn = dễ nạp ngày thiếu dữ liệu.",
       "D-1 quality gate: a fallback D-1 loads only with at least this share of the usual rows; lower = an incomplete day loads more easily."),
    _e("bigquery", "max_null_share", "HIGH", "Tỷ lệ ô trống tối đa", "Maximum null share",
       "Chốt chất lượng D-1: quá tỷ lệ ô trống này thì D-1 bị chặn; cao hơn = dễ nạp dữ liệu lỗi.",
       "D-1 quality gate: above this null share D-1 is blocked; higher = faulty data loads more easily."),
    _e("bigquery", "product_names_key_column", "READONLY", "Cột mã của bảng tên sản phẩm", "Product names key column",
       "Đọc cùng bảng tên sản phẩm; đổi cần kiểm tra bảng (quy tắc 19).", "Read with the product names table; a change needs the table check (rule 19).",
       reason_code="REG_SOURCE_TABLE_CHECK"),
    _e("bigquery", "product_names_name_column", "READONLY", "Cột tên của bảng tên sản phẩm", "Product names name column",
       "Đọc cùng bảng tên sản phẩm; đổi cần kiểm tra bảng (quy tắc 19).", "Read with the product names table; a change needs the table check (rule 19).",
       reason_code="REG_SOURCE_TABLE_CHECK"),
    _e("bigquery", "schema_snapshot", "READONLY", "Ảnh chụp cấu trúc bảng nguồn", "Source schema snapshot",
       "Do bước kiểm tra bảng / ánh xạ ghi.", "Written by the table / mapping check.", reason_code="REG_INTERNAL_STATE"),
    _e("bigquery", "product_names_table", "OWN_PATH", "Bảng tên sản phẩm", "Product names table",
       "Bảng nguồn tùy chọn; đổi qua ô Bảng nguồn có nút Kiểm tra.", "Optional source table; changed in Source tables with its check.",
       reason_code="REG_SOURCE_TABLE_CHECK", own_path=_SRC_TABLES),
    _e("bigquery", "d0_table_id", "OWN_PATH", "Bảng D-0", "D-0 table",
       "Bảng nguồn D-0; đổi qua ô Bảng nguồn có nút Kiểm tra.", "D-0 source table; changed in Source tables with its check.",
       reason_code="REG_SOURCE_TABLE_CHECK", own_path=_SRC_TABLES),
    _e("bigquery", "d0_mapping", "OWN_PATH", "Ánh xạ cột D-0", "D-0 column mapping",
       "Đổi ở trang SQL nguồn (kiểm tra lại cấu trúc).", "Changed on the SQL sources page (schema re-checked).",
       reason_code="REG_SOURCE_TABLE_CHECK", own_path="bq/d0_feed.py save mapping (SqlSources.tsx)"),
    _e("bigquery", "oauth_enabled", "OWN_PATH", "Đã đăng nhập Google", "Signed in with Google",
       "Do đăng nhập / đăng xuất Google ghi.", "Written by Google sign-in / sign-out.",
       reason_code="REG_OAUTH", own_path="/api/bigquery/oauth/* (GoogleAuth.tsx)"),
    _e("bigquery", "oauth_client_id", "OWN_PATH", "OAuth client ID", "OAuth client ID",
       "Đổi ở khung Đăng nhập Google (đổi thì phải đăng nhập lại).", "Changed in the Google sign-in box (a change signs out).",
       reason_code="REG_OAUTH", own_path="POST /api/bigquery/oauth/client (GoogleAuth.tsx:145)"),
    _e("bigquery", "production_enabled", "OWN_PATH", "Chế độ production BigQuery", "BigQuery production mode",
       "Chỉ bật / tắt qua nút kích hoạt sau khi kiểm tra đạt.", "Switched only by the activate / deactivate buttons after the checks.",
       reason_code="REG_BQ_PRODUCTION", own_path="/api/bigquery/activate | deactivate"),
    # ---------------------------------------------------------------- daily_forecast (1.3.1)
    # orchestrator decision 23/11/2026 (item #9): editable here with the PURCHASE text + reason
    _e("daily_forecast", "enabled", "PURCHASE", "Bật dự báo hằng ngày 1.3.1", "1.3.1 daily forecast on",
       "Công tắc của luồng làm mới dự báo 1.3.1 (khi SEL2 tắt) và báo cáo độ chính xác; bật / tắt đổi việc làm mới số dự báo.",
       "Switch of the 1.3.1 forecast refresh (when SEL2 is off) and the accuracy report; on / off changes whether the "
       "forecast numbers are refreshed."),
    _e("daily_forecast", "trial_mode", "OWN_PATH", "Chạy thử (chưa dùng mua hàng)", "Trial mode (not for purchasing)",
       "Đổi qua nút riêng có chữ xác nhận.", "Changed through its own button with a typed confirmation.",
       reason_code="REG_TRIAL_MODE", own_path="POST /api/daily-forecast/trial-mode"),
    _e("daily_forecast", "rounding_threshold", "READONLY", "Ngưỡng làm tròn forecast_used", "forecast_used rounding threshold",
       "Quy tắc cố định 05/11/2026: < 0,2 thành 0, còn lại làm tròn lên. Không đổi ở đây.",
       "Fixed rule of 05/11/2026: < 0.2 becomes 0, otherwise rounded up. Not changed here.", reason_code="REG_FIXED_RULE"),
    _e("daily_forecast", "log_retention_days", "HIGH", "Số ngày giữ nhật ký dự báo", "Forecast log retention (days)",
       "Giá trị và thực tế cũ hơn số ngày này bị XÓA sau lần làm mới thành công; chỉ được tăng (giảm = xóa dữ liệu, không lấy lại được).",
       "Values and actuals older than this are DELETED after a successful refresh; increase only (a decrease deletes data for good).",
       only_increase=True),
    _e("daily_forecast", "seller_code", "HIGH", "Mã seller khi đọc giờ mở bán", "Seller code of the open-hours read",
       "Lọc seller khi đọc giờ mở bán từ BigQuery; sai mã thì thiếu giờ mở bán (đầu vào bắt buộc).",
       "Seller filter of the BigQuery open-hours read; a wrong code leaves open hours missing (mandatory input)."),
    _e("daily_forecast", "report_subdir", "LOW", "Thư mục báo cáo độ chính xác", "Accuracy report folder",
       "Tên MỘT thư mục con trong thư mục báo cáo; báo cáo mới ghi vào đó, báo cáo cũ không di chuyển.",
       "ONE sub-folder name inside the reports folder; new reports go there, old ones are not moved.", path_rule="NAME"),
    _e("daily_forecast", "openhours_table", "OWN_PATH", "Bảng giờ mở bán", "Open-hours table",
       "Bảng nguồn; đổi qua ô Bảng nguồn có nút Kiểm tra (quy tắc 19).", "Source table; changed in Source tables with its check (rule 19).",
       reason_code="REG_SOURCE_TABLE_CHECK", own_path=_SRC_TABLES),
    # ---------------------------------------------------------------- sel2_pipeline (1.4.0)
    _e("sel2_pipeline", "enabled", "PURCHASE", "Bật quy trình SEL2", "SEL2 pipeline on",
       "Tắt = công tắc KHẨN CẤP quay về cách 1.3.1: đổi nguồn forecast_used của file mua hàng.",
       "Off = EMERGENCY switch back to 1.3.1: changes the source of forecast_used in the purchase file."),
    _e("sel2_pipeline", "p_threshold", "READONLY", "Ngưỡng xác suất two-stage", "Two-stage probability threshold",
       "Cố định 0,6 (là một phần tên ứng viên V36_two_stage@0.6 trong bảng).",
       "Fixed at 0.6 (part of the candidate name V36_two_stage@0.6 in the tables).", reason_code="REG_FIXED_RULE"),
    _e("sel2_pipeline", "window_days", "PURCHASE", "Cửa sổ chọn mô hình (ngày)", "Selection window (days)",
       "Số ngày dùng để chọn ứng viên cho từng SKU×kho; đổi lựa chọn và số mua hàng.",
       "Days used to choose the candidate per SKU×FC; changes the choice and the purchase numbers."),
    _e("sel2_pipeline", "min_days", "PURCHASE", "Số ngày tối thiểu để chọn", "Minimum days to select",
       "Chuỗi ít ngày hơn dùng ứng viên dự phòng; đổi số mua hàng.", "Series with fewer days use the fallback candidate; changes purchase numbers."),
    _e("sel2_pipeline", "fallback_model", "PURCHASE", "Ứng viên dự phòng", "Fallback candidate",
       "Ứng viên dùng khi không chọn được; đổi số mua hàng.", "Candidate used when no choice is possible; changes purchase numbers."),
    _e("sel2_pipeline", "group_mode", "PURCHASE", "Kiểu kỳ chọn", "Selection period mode",
       "Cuộn 7 ngày hoặc kỳ cố định (cần ngày bắt đầu / kết thúc); đổi số mua hàng.",
       "Rolling 7 days or a fixed period (start / end dates needed); changes purchase numbers."),
    _e("sel2_pipeline", "group_fixed_start", "PURCHASE", "Ngày bắt đầu kỳ cố định", "Fixed period start",
       "Dùng khi kiểu kỳ = FIXED.", "Used when the mode is FIXED."),
    _e("sel2_pipeline", "group_fixed_end", "PURCHASE", "Ngày kết thúc kỳ cố định", "Fixed period end",
       "Dùng khi kiểu kỳ = FIXED.", "Used when the mode is FIXED."),
    _e("sel2_pipeline", "retention_days", "HIGH", "Số ngày giữ dự báo ứng viên", "Candidate forecast retention (days)",
       "Dự báo ứng viên cũ hơn bị XÓA; chỉ được tăng (giảm = xóa dữ liệu, không lấy lại được); ít nhất cửa sổ + 7.",
       "Older candidate forecasts are DELETED; increase only (a decrease deletes data for good); at least window + 7.",
       only_increase=True),
    _e("sel2_pipeline", "export_subdir", "PURCHASE", "Thư mục file Excel hằng ngày", "Daily Excel folder",
       "Thư mục con (trong thư mục dữ liệu) ghi file Excel mua hàng; đổi thì các tác vụ lấy file phải theo.",
       "Sub-folder (inside the data folder) of the purchase Excel; tasks that pick the file up must follow.",
       path_rule="SUBDIR"),
    _e("sel2_pipeline", "export_deadline", "HIGH", "Hạn chót xuất Excel", "Excel export deadline",
       "Giờ (VN) phải có file Excel; quá giờ thì xuất bản STALE.", "Time (Vietnam) the Excel must exist; after it a STALE file is exported."),
    _e("sel2_pipeline", "prev_week_deadline", "HIGH", "Hạn chót bản tuần trước", "Previous-week deadline",
       "Phải trước hạn chót xuất Excel.", "Must be before the export deadline."),
    _e("sel2_pipeline", "avg_reexport_time", "PURCHASE", "Giờ xuất lại sau khi Avg đổi", "Re-export time after Avg change",
       "Trống = tắt (chờ chủ dự án duyệt). Bật thì có thêm bản Excel mua hàng khi bảng Avg Demand đổi.",
       "Empty = off (pending owner approval). On = a new purchase Excel version when the Avg Demand table changed."),
    _e("sel2_pipeline", "retrain_weekday", "HIGH", "Thứ học lại ứng viên", "Candidate retraining weekday",
       "Thứ (1 = Thứ Hai) học lại các ứng viên LightGBM (việc nặng nhiều giờ).",
       "Weekday (1 = Monday) of the LightGBM candidate retraining (heavy, several hours)."),
    _e("sel2_pipeline", "train_timeout_seconds", "HIGH", "Giới hạn thời gian học (giây)", "Training time limit (seconds)",
       "Quá giới hạn thì lần học bị dừng; cũng là mốc coi việc học là treo.", "Training is stopped beyond it; also the stale mark of a training job."),
    _e("sel2_pipeline", "open_hours_lag_days", "PURCHASE", "Độ trễ giờ mở bán (ngày)", "Open-hours lag (days)",
       "Số ngày trễ của giờ mở bán BigQuery; đổi dữ liệu đầu vào và số dự báo.", "Lag of the BigQuery open hours; changes the input and the forecast."),
    _e("sel2_pipeline", "open_hours_history_start", "PURCHASE", "Ngày đầu đọc giờ mở bán", "Open-hours first day",
       "Ngày đầu tiên đọc giờ mở bán; đổi dữ liệu học.", "First day of the open-hours read; changes the training data."),
    _e("sel2_pipeline", "tsb_alpha", "PURCHASE", "TSB alpha", "TSB alpha",
       "Hệ số làm trơn xác suất có cầu của ứng viên TSB; đổi số dự báo TSB.", "Smoothing of the demand probability of TSB; changes TSB numbers."),
    _e("sel2_pipeline", "tsb_beta", "PURCHASE", "TSB beta", "TSB beta",
       "Hệ số làm trơn cỡ cầu của ứng viên TSB; đổi số dự báo TSB.", "Smoothing of the demand size of TSB; changes TSB numbers."),
    _e("sel2_pipeline", "tsb_start", "PURCHASE", "Ngày đầu lịch sử TSB", "TSB history start",
       "Ngày đầu lịch sử của ứng viên TSB; đổi số dự báo TSB.", "First history day of TSB; changes TSB numbers."),
    _e("sel2_pipeline", "avg_seller_rule", "PURCHASE", "Cách gộp Avg Demand theo seller", "Avg Demand seller rule",
       "PENDING / SUM / MAX / SELLER:<mã>; đổi số Avg dùng cho forecast_used.", "PENDING / SUM / MAX / SELLER:<code>; changes the Avg used by forecast_used."),
    _e("sel2_pipeline", "spike_cleaning", "PURCHASE", "Làm sạch đơn đột biến", "Spike cleaning",
       "Bật / tắt lọc đơn đột biến (quyết định của chủ dự án, CLAUDE.md 18). " + _SPIKE_VI,
       "Turns the spike-order filter on / off (owner decision, CLAUDE.md 18). " + _SPIKE_EN),
    _e("sel2_pipeline", "spike_e4_n", "PURCHASE", "Ngưỡng N (E4) làm sạch đột biến", "Spike cleaning threshold N (E4)",
       "SKU×kho có dòng bị đánh dấu ở >= N trong 30 ngày trước thì không lọc (ngưỡng do chủ dự án duyệt, xem lại mỗi "
       "quý). " + _SPIKE_VI,
       "A SKU×FC with flagged lines on >= N of the 30 days before is not cleaned (threshold approved by the owner, "
       "reviewed each quarter). " + _SPIKE_EN),
    _e("sel2_pipeline", "avg_demand_table", "OWN_PATH", "Bảng Avg Demand", "Avg Demand table",
       "Bảng nguồn; đổi qua ô Bảng nguồn có nút Kiểm tra (quy tắc 19).", "Source table; changed in Source tables with its check (rule 19).",
       reason_code="REG_SOURCE_TABLE_CHECK", own_path=_SRC_TABLES),
    _e("sel2_pipeline", "avg_demand_hist_table", "OWN_PATH", "Bảng Avg Demand lịch sử", "Avg Demand history table",
       "Bảng nguồn; đổi qua ô Bảng nguồn có nút Kiểm tra (quy tắc 19).", "Source table; changed in Source tables with its check (rule 19).",
       reason_code="REG_SOURCE_TABLE_CHECK", own_path=_SRC_TABLES),
    # ---------------------------------------------------------------- general
    _e("general", "active_source", "OWN_PATH", "Nguồn dữ liệu đang dùng", "Active data source",
       "Đổi ở nút chọn nguồn (có kiểm tra BigQuery sẵn sàng).", "Changed by the source selector (BigQuery readiness checked).",
       reason_code="REG_ACTIVE_DATA", own_path="PUT /api/active-source"),
    _e("general", "active_import_batch_id", "OWN_PATH", "Lô Excel đang dùng", "Active Excel batch",
       "Đổi ở trang Lô dữ liệu.", "Changed on the Batches page.", reason_code="REG_ACTIVE_DATA",
       own_path="api/data_routes.py imports"),
    _e("general", "timezone", "READONLY", "Múi giờ", "Timezone",
       "Cố định Asia/Ho_Chi_Minh (ngày nghiệp vụ là ngày Việt Nam).", "Fixed Asia/Ho_Chi_Minh (business dates are Vietnam dates).",
       reason_code="REG_FIXED_RULE"),
)

# own box in the UI (not in the registry): (section, key) -> where
VISIBLE: dict[tuple[str, str], str] = {
    ("horizons", "choices"): "Config.tsx:117-123", ("horizons", "enabled"): "Config.tsx:117-123",
    ("horizons", "max_allowed_days"): "Config.tsx:129",
    ("quality", "wape_max"): "Config.tsx:217", ("quality", "abs_bias_max"): "Config.tsx:218",
    ("quality", "min_backtest_points"): "Config.tsx:219", ("quality", "mape_min_actual"): "Config.tsx:220",
    ("quality", "require_beat_baseline"): "Config.tsx:221", ("quality", "approved_by_business"): "Config.tsx:222",
    ("quality", "below_threshold_policy"): "Config.tsx:223-227",
    ("model", "feature_lags"): "Config.tsx:148-153", ("model", "feature_rolling"): "Config.tsx:148-153",
    ("model", "feature_price"): "Config.tsx:154-161", ("model", "feature_weekday"): "Config.tsx:162-169, Mapping.tsx:142",
    ("model", "feature_customer"): "Config.tsx:176-185", ("model", "forecast_strategy"): "Config.tsx:188-193",
    ("model", "direct_origins"): "Config.tsx:196", ("model", "direct_origin_step_days"): "Config.tsx:197",
    ("model", "min_total_history_days"): "Config.tsx:238-240", ("model", "min_series_history_days"): "Config.tsx:238-240",
    ("model", "inactive_days"): "Config.tsx:238-240", ("model", "fallback_window_days"): "Config.tsx:238-240",
    ("model", "intermittent_zero_share"): "Config.tsx:241", ("model", "backtest_folds"): "Config.tsx:243-245",
    ("model", "backtest_horizon_days"): "Config.tsx:243-245", ("model", "backtest_step_days"): "Config.tsx:243-245",
    ("model", "num_boost_round"): "Config.tsx:247", ("model", "learning_rate"): "Config.tsx:248",
    ("model", "num_leaves"): "Config.tsx:249", ("model", "max_train_days"): "Config.tsx:250",
    ("model", "objective"): "Config.tsx:251-255",
    ("import", "max_file_mb"): "Config.tsx:305", ("import", "max_rows"): "Config.tsx:306",
    ("import", "grain_conflict_policy"): "Config.tsx:307-312",
    ("schedule", "slot_grace_minutes"): "Config.tsx:323", ("schedule", "max_attempts"): "Config.tsx:325",
    ("schedule", "retry_base_seconds"): "Config.tsx:326", ("schedule", "retry_max_seconds"): "Config.tsx:327",
    ("schedule", "timeout_seconds"): "Config.tsx:328",
    ("schedule", "d0_times"): "Schedules.tsx:246-247", ("schedule", "d0_catchup_policy"): "Schedules.tsx:249",
    ("schedule", "train_time"): "Schedules.tsx:258", ("schedule", "train_catchup_policy"): "Schedules.tsx:260",
    ("schedule", "eod_time"): "Schedules.tsx:271", ("schedule", "close_time"): "Schedules.tsx:281",
    ("schedule", "eod_timezone"): "Schedules.tsx:272 (TimezoneField 199-210)",
    ("schedule", "close_timezone"): "Schedules.tsx:282 (TimezoneField 199-210)",
    ("bigquery", "maximum_bytes_billed"): "BigQuery.tsx:273", ("bigquery", "initial_history_days"): "BigQuery.tsx:274",
}

# never exported / imported / changed here: BigQuery connection and mapping (own pages; a change of most of them turns
# production mode off, api/data_routes.py PUT bigquery) -> (section, key) -> reason / where
EXCLUDED: dict[tuple[str, str], str] = {
    ("bigquery", "project_id"): "connection, BigQuery.tsx:259", ("bigquery", "dataset_id"): "connection, BigQuery.tsx:260",
    ("bigquery", "location"): "connection, BigQuery.tsx:261", ("bigquery", "source_table"): "connection, BigQuery.tsx:262",
    ("bigquery", "partition_column"): "connection, BigQuery.tsx:263",
    ("bigquery", "created_at_is_utc"): "connection (mapping hash), BigQuery.tsx:264",
    ("bigquery", "auth_method"): "connection, BigQuery.tsx:265-270",
    ("bigquery", "service_account_file"): "connection (path), BigQuery.tsx:272",
    ("bigquery", "history_start_date"): "connection (turns production off), BigQuery.tsx:275",
    ("bigquery", "exact_duplicate_policy"): "connection (turns production off), BigQuery.tsx:276-280",
    ("bigquery", "completion_table"): "source table, BigQuery.tsx:282",
    ("bigquery", "completion_date_column"): "source column, BigQuery.tsx:283",
    ("bigquery", "completion_status_column"): "source column, BigQuery.tsx:284",
    ("bigquery", "completion_status_value"): "source value, BigQuery.tsx:285",
    ("bigquery", "field_mapping"): "mapping, Mapping.tsx:202 (POST /api/bigquery/mapping)",
    ("bigquery", "reference_mapping"): "mapping, Mapping.tsx:202",
    ("bigquery", "extra_reference_columns"): "mapping, Mapping.tsx:181,202",
    ("bigquery", "customer_id_column"): "mapping (hash), Mapping.tsx:182,202",
}

# data_policy: 5 guarded fields (api/data_policy_routes.py, DataPolicyGuarded.tsx) + 5 saved by the old card
DATA_POLICY: dict[str, str] = {
    "window_start_date": "guarded (locked), DataPolicyGuarded.tsx",
    "history_change_policy": "guarded, DataPolicyGuarded.tsx", "history_day_check": "guarded, DataPolicyGuarded.tsx",
    "source_time_travel_hours": "guarded, DataPolicyGuarded.tsx", "training_start_rule": "guarded, DataPolicyGuarded.tsx",
    "stale_check_sources": "Config.tsx:274-283", "max_data_lag_days": "Config.tsx:284",
    "late_data_lookback_days": "Config.tsx:285", "min_date": "Config.tsx:286", "price_outlier_factor": "Config.tsx:295",
}

# keys the generic editor (PUT /api/settings/{section}) already treats by its own rules (refused with their own code,
# ignored or forced): the registry guard does not compare them again
PUT_EXISTING_RULES: dict[str, tuple[str, ...]] = {
    "model": ("feature_open_hours", "weekday_encoding", "feature_table"),
    "daily_forecast": ("trial_mode",),
    "bigquery": ("production_enabled", "schema_snapshot", "oauth_enabled"),
}

_BY_KEY: dict[tuple[str, str], Entry] = {(e.section, e.key): e for e in ENTRIES}


def entry(section: str, key: str) -> Entry | None:
    return _BY_KEY.get((section, key))


def risk(e: Entry) -> str:
    return e.risk


def reason_code(e: Entry) -> str | None:
    return e.reason_code


def editable(e: Entry) -> bool:
    return risk(e) in EDITABLE


def exportable(e: Entry) -> bool:
    """For lot 2B (export / import): editable entries and the fixed rules (an import must carry the same value);
    internal state, own paths and connection-like entries never."""
    return editable(e) or (risk(e) == "READONLY" and reason_code(e) == "REG_FIXED_RULE")


def keys_of(section: str) -> tuple[str, ...]:
    return tuple(e.key for e in ENTRIES if e.section == section)


def put_guarded_keys(section: str) -> tuple[str, ...]:
    skip = PUT_EXISTING_RULES.get(section, ())
    return tuple(k for k in keys_of(section) if k not in skip)


def same(a, b) -> bool:
    """Equal values for the guards: a bool is never a number (True is not 1); 3 == 3.0 (JSON from a browser)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def path_ok(e: Entry, value) -> bool:
    """Lexical check of a folder value (never touches the disk): NAME = one folder name, SUBDIR = relative folder; no
    drive, no root, no '..' (both are joined under the app's own folder: accuracy_report.report_dir,
    feature_report, sel2 export)."""
    if e.path_rule is None:
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    p = PureWindowsPath(value.replace("/", "\\"))
    if p.drive or p.root or p.anchor or any(part in ("..", ".") for part in p.parts):
        return False
    return len(p.parts) == 1 if e.path_rule == "NAME" else len(p.parts) >= 1


def risk_max(risks) -> str | None:
    rs = [r for r in risks if r in RISK_ORDER]
    return max(rs, key=RISK_ORDER.get) if rs else None


def constraints(section: str, key: str) -> dict:
    """Range / choices of the field, read from the pydantic model (never typed twice)."""
    fi = ss.SECTIONS[section].model_fields[key]
    out: dict = {"type": _type_name(fi.annotation)}
    for m in fi.metadata:
        for attr in ("ge", "gt", "le", "lt", "max_length", "min_length"):
            v = getattr(m, attr, None)
            if v is not None:
                out[attr] = v
    choices = _literal_args(fi.annotation)
    if choices:
        out["choices"] = choices
    return out


def _literal_args(ann) -> list:
    if typing.get_origin(ann) is typing.Literal:
        return list(typing.get_args(ann))
    out: list = []
    for a in typing.get_args(ann):
        out += _literal_args(a)
    return out


def _type_name(ann) -> str:
    return str(ann).replace("typing.", "") if typing.get_args(ann) else getattr(ann, "__name__", str(ann))


def classification() -> dict[str, dict[str, str]]:
    """section -> key -> REGISTRY | VISIBLE | EXCLUDED | DATA_POLICY (a key in two groups is listed as DUPLICATE)."""
    out: dict[str, dict[str, str]] = {}
    groups = [("REGISTRY", set(_BY_KEY)), ("VISIBLE", set(VISIBLE)), ("EXCLUDED", set(EXCLUDED)),
              ("DATA_POLICY", {("data_policy", k) for k in DATA_POLICY})]
    for name, keys in groups:
        for s, k in keys:
            cur = out.setdefault(s, {}).get(k)
            out[s][k] = name if cur is None else "DUPLICATE"
    return out
