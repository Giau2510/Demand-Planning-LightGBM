"""Localised labels for Excel exports. Identifiers (SKU, FC, run id, model version, method code) are never
translated; numbers are written unchanged. EXPORT_FORMAT_VERSION is stamped into the Info sheet."""
from __future__ import annotations

# 6: weekday name of the target date after the date (1.2.9; the numeric horizon_day column is unchanged)
# 5: product name column after the SKU (1.2.4); 4: DD/MM/YYYY, VN local times, method label before the code
EXPORT_FORMAT_VERSION = "6"

LABELS = {
    "vi": {
        "sheet_info": "Thông tin", "sheet_totals": "Tổng {h} ngày", "sheet_daily": "Chi tiết theo ngày",
        "field": "Trường", "value": "Giá trị",
        "info": {"export_format_version": "Phiên bản định dạng file", "language": "Ngôn ngữ",
                 "forecast_run_id": "Mã lần dự báo (run ID)", "model_version": "Phiên bản mô hình",
                 "data_source": "Nguồn dữ liệu", "scope": "Bộ dữ liệu (scope)", "forecast_origin": "Mốc dự báo (ngày đầu)",
                 "data_as_of": "Dữ liệu tính đến ngày", "created_at_vn": "Thời điểm chạy (giờ Việt Nam)",
                 "created_at_utc": "Thời điểm chạy (UTC)",
                 "horizon_days": "Khoảng dự báo (ngày)", "start_date": "Ngày bắt đầu", "end_date": "Ngày kết thúc",
                 "derived_from_run_id": "Tạo bổ sung từ run",
                 "actual_date": "Ngày áp dụng 'thực tế đến hiện tại'", "actual_status": "Trạng thái thực tế trong ngày",
                 "actual_as_of_vn": "Thực tế đọc lúc (giờ Việt Nam)", "actual_as_of_utc": "Thực tế đọc lúc (UTC)", "actual_source_updated_max": "Bản ghi nguồn mới nhất",
                 "actual_snapshot_id": "Mã snapshot D0", "actual_is_demo": "Thực tế là dữ liệu DEMO mô phỏng",
                 "actual_note": "Ghi chú", "product_names_source": "Nguồn tên sản phẩm",
                 "product_names_fetched_at": "Tên sản phẩm đọc lúc (giờ Việt Nam)"},
        "actual_note": "Cột 'Thực tế đến hiện tại' chỉ có giá trị ở ngày hôm nay (giờ VN), là số lượng đặt lũy kế đến thời điểm đọc snapshot D0, KHÔNG phải số cả ngày. Ô trống = không áp dụng hoặc chưa có dữ liệu.",
        "actual_status": {"PARTIAL_DAY": "Đang cập nhật trong ngày", "STALE": "Có thể đã cũ", "NO_DATA_TODAY": "Chưa có dữ liệu hôm nay",
                          "NOT_APPLICABLE": "Không áp dụng cho nguồn này"},
        "cols_totals": {"sku_id": "SKU", "product_name": "Tên sản phẩm", "fc_id": "FC/kho", "method_label": "Phương pháp", "forecast_qty": "Tổng dự báo trong khoảng",
                        "actual_today": "Thực tế hôm nay đến hiện tại", "method": "Mã kỹ thuật phương pháp (không dịch)"},
        "cols_daily": {"sku_id": "SKU", "product_name": "Tên sản phẩm", "fc_id": "FC/kho", "target_date": "Ngày",
                       "weekday": "Thứ trong tuần", "horizon_day": "Ngày thứ",
                       "forecast_qty": "Số lượng dự báo", "actual_today": "Thực tế đến hiện tại",
                       "method_label": "Phương pháp", "method": "Mã kỹ thuật phương pháp (không dịch)"},
        "yes": "Có", "no": "Không", "language_name": "Tiếng Việt", "no_product_name": "Chưa có tên sản phẩm",
        "date_fmt": "%d/%m/%Y", "excel_date_fmt": "DD/MM/YYYY", "time_suffix": "giờ Việt Nam, UTC+7",
    },
    "en": {
        "sheet_info": "Info", "sheet_totals": "Totals {h}d", "sheet_daily": "Daily",
        "field": "Field", "value": "Value",
        "info": {"export_format_version": "File format version", "language": "Language",
                 "forecast_run_id": "Forecast run ID", "model_version": "Model version", "data_source": "Data source",
                 "scope": "Dataset (scope)", "forecast_origin": "Forecast origin (first day)", "data_as_of": "Data as of",
                 "created_at_vn": "Run time (Vietnam time)", "created_at_utc": "Run time (UTC)", "horizon_days": "Forecast period (days)", "start_date": "Start date",
                 "end_date": "End date", "derived_from_run_id": "Derived from run",
                 "actual_date": "Date of 'actual so far'", "actual_status": "Intraday actual status",
                 "actual_as_of_vn": "Actual read at (Vietnam time)", "actual_as_of_utc": "Actual read at (UTC)", "actual_source_updated_max": "Latest source record",
                 "actual_snapshot_id": "D0 snapshot ID", "actual_is_demo": "Actual is simulated DEMO data",
                 "actual_note": "Note", "product_names_source": "Product name source",
                 "product_names_fetched_at": "Product names read at (Vietnam time)"},
        "actual_note": "The 'Actual so far' column only has values for today (Vietnam time): cumulative ordered quantity up to the D0 snapshot read time, NOT a full-day figure. Empty = not applicable or no data yet.",
        "actual_status": {"PARTIAL_DAY": "Updating during the day", "STALE": "May be stale", "NO_DATA_TODAY": "No data today yet",
                          "NOT_APPLICABLE": "Not applicable for this source"},
        "cols_totals": {"sku_id": "SKU", "product_name": "Product name", "fc_id": "FC/warehouse", "method_label": "Method", "forecast_qty": "Period total forecast",
                        "actual_today": "Actual today so far", "method": "Technical method code (not translated)"},
        "cols_daily": {"sku_id": "SKU", "product_name": "Product name", "fc_id": "FC/warehouse", "target_date": "Date",
                       "weekday": "Weekday", "horizon_day": "Day #",
                       "forecast_qty": "Forecast qty", "actual_today": "Actual so far",
                       "method_label": "Method", "method": "Technical method code (not translated)"},
        "yes": "Yes", "no": "No", "language_name": "English", "no_product_name": "No product name yet",
        "date_fmt": "%d/%m/%Y", "excel_date_fmt": "DD/MM/YYYY", "time_suffix": "Vietnam time, UTC+7",
    },
}


def labels(lang: str | None) -> tuple[str, dict]:
    lang = lang if lang in LABELS else "vi"
    return lang, LABELS[lang]


def fmt_date(iso_date: str | None, L: dict) -> str:
    from datetime import date
    return date.fromisoformat(iso_date).strftime(L["date_fmt"]) if iso_date else ""


def fmt_vn_time(iso_ts: str | None, L: dict) -> str:
    """UTC ISO timestamp -> local Vietnam time in the export language, with the zone spelled out."""
    if not iso_ts:
        return ""
    from .timeutil import VN_TZ, parse_iso
    t = parse_iso(iso_ts).astimezone(VN_TZ)
    return f"{t.strftime(L['date_fmt'])} {t.strftime('%H:%M')} ({L['time_suffix']})"


_ISO_DATE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DT = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def fmt_dateish(v, L: dict):
    """Display form of a value that may be a date: ISO dates -> DD/MM/YYYY, ISO timestamps with a zone -> Vietnam
    local time, ISO timestamps without a zone (raw input values) -> same wall-clock in DD/MM/YYYY HH:mm[:ss].
    Anything else (e.g. an unparseable raw input that caused a validation error) is returned unchanged."""
    from datetime import datetime
    if not isinstance(v, str):
        return v
    t = v.strip()
    if _ISO_DATE.match(t):
        return fmt_date(t, L)
    if _ISO_DT.match(t):
        if t.endswith("Z") or "+" in t[10:] or t[10:].count("-"):
            return fmt_vn_time(t, L)
        d = datetime.fromisoformat(t.replace(" ", "T"))
        return d.strftime(L["date_fmt"] + (" %H:%M:%S" if d.second else " %H:%M"))
    return v


# Snapshot (D0) export and import error report: same language rules as the forecast export
OTHER = {
    "vi": {
        "snap_sheet_info": "Thông tin snapshot", "snap_sheet_values": "Số lượng lũy kế",
        "snap_info": {"id": "Mã snapshot", "data_source": "Nguồn dữ liệu", "scope_key": "Bộ dữ liệu (scope)",
                      "order_date": "Ngày đặt hàng", "snapshot_at": "Thời điểm đọc nguồn (giờ Việt Nam)",
                      "scheduled_slot": "Mốc lịch", "is_catch_up": "Chạy bù", "sync_status": "Trạng thái",
                      "rows_read": "Số dòng đọc", "rows_valid": "Số dòng hợp lệ", "rows_error": "Số dòng lỗi",
                      "source_updated_max": "Bản ghi nguồn mới nhất", "source_batch_id": "Mã lô nguồn",
                      "job_id": "Mã job", "created_at": "Thời điểm lưu (giờ Việt Nam)"},
        "snap_cols": {"sku_id": "SKU", "fc_id": "FC/kho", "cumulative_qty": "Số lượng đặt lũy kế đến lúc đọc",
                      "source_updated_at": "Bản ghi nguồn cập nhật lúc", "full_day_forecast": "Dự báo cả ngày",
                      "end_of_day_actual": "Thực tế cuối ngày"},
        "err_sheet_summary": "Tóm tắt", "err_sheet_errors": "Lỗi",
        "err_summary": {"id": "Mã lô", "file_name": "Tên file", "sheet_name": "Sheet", "status": "Trạng thái",
                        "total_rows": "Tổng số dòng", "valid_rows": "Dòng hợp lệ", "error_rows": "Dòng lỗi",
                        "duplicate_rows": "Dòng trùng", "min_order_date": "Ngày đặt hàng sớm nhất",
                        "max_order_date": "Ngày đặt hàng muộn nhất", "created_at": "Thời điểm tạo (giờ Việt Nam)"},
        "err_cols": ["Dòng", "Cột", "Mã lỗi", "Mức độ", "Giá trị trong file", "Giải thích"],
    },
    "en": {
        "snap_sheet_info": "Snapshot info", "snap_sheet_values": "Cumulative quantities",
        "snap_info": {"id": "Snapshot ID", "data_source": "Data source", "scope_key": "Dataset (scope)",
                      "order_date": "Order date", "snapshot_at": "Source read at (Vietnam time)",
                      "scheduled_slot": "Schedule slot", "is_catch_up": "Catch-up run", "sync_status": "Status",
                      "rows_read": "Rows read", "rows_valid": "Valid rows", "rows_error": "Error rows",
                      "source_updated_max": "Latest source record", "source_batch_id": "Source batch ID",
                      "job_id": "Job ID", "created_at": "Stored at (Vietnam time)"},
        "snap_cols": {"sku_id": "SKU", "fc_id": "FC/warehouse", "cumulative_qty": "Cumulative ordered qty at read time",
                      "source_updated_at": "Source record updated at", "full_day_forecast": "Full-day forecast",
                      "end_of_day_actual": "End-of-day actual"},
        "err_sheet_summary": "Summary", "err_sheet_errors": "Errors",
        "err_summary": {"id": "Batch ID", "file_name": "File name", "sheet_name": "Sheet", "status": "Status",
                        "total_rows": "Total rows", "valid_rows": "Valid rows", "error_rows": "Error rows",
                        "duplicate_rows": "Duplicate rows", "min_order_date": "Earliest order date",
                        "max_order_date": "Latest order date", "created_at": "Created at (Vietnam time)"},
        "err_cols": ["Row", "Column", "Error code", "Severity", "Value in file", "Explanation"],
    },
}


# 1.2.5: "Forecast & actual history" export (format H1, independent of the forecast export format above)
HISTORY = {
    "vi": {
        "sheet_info": "Thông tin", "sheet_sessions": "Phiên forecast", "sheet_daily": "Theo ngày",
        "sheet_rows": "Chi tiết SKU x FC", "field": "Trường", "value": "Giá trị", "all": "Tất cả",
        "info": {"export_format_version": "Phiên bản định dạng file", "language": "Ngôn ngữ",
                 "generated_at_vn": "Thời điểm xuất (giờ Việt Nam)", "scope": "Bộ dữ liệu (scope)",
                 "data_source": "Nguồn dữ liệu", "run_from": "Ngày chạy forecast từ", "run_to": "Ngày chạy forecast đến",
                 "fc_filter": "Lọc FC/kho", "search_filter": "Lọc SKU / tên sản phẩm", "status_filter": "Lọc trạng thái thực tế",
                 "rows": "Số dòng SKU x FC", "days_with_history": "Số ngày chạy có lịch sử",
                 "forecast_total": "Tổng forecast đã lưu", "actual_total": "Tổng thực tế đã hoàn tất (chỉ dòng đã chốt)",
                 "forecast_compared": "Tổng forecast trên các dòng đã chốt",
                 "deviation": "Sai lệch Forecast - Thực tế (dòng đã chốt)", "wape": "WAPE (dòng đã chốt)",
                 "kpi_status": "Trạng thái số liệu thực tế", "rule_d1": "Quy tắc lưu forecast",
                 "rule_actual": "Quy tắc thực tế", "rule_wape": "Cách tính", "source_filter": "Lọc nguồn forecast",
                 "days_primary": "Số ngày dùng forecast chính", "days_backup": "Số ngày dùng snapshot dự phòng",
                 "rule_backup": "Quy tắc snapshot dự phòng", "rule_close": "Quy tắc chốt thực tế cuối ngày",
                 "basis": "Cơ sở tính KPI thực tế", "rows_final": "Số dòng có thực tế đã hoàn tất",
                 "rows_provisional": "Số dòng thực tế tạm tính", "rows_closed": "Số dòng đã chốt cuối ngày - cần xác minh",
                 "rows_no_actual": "Số dòng chưa có thực tế (không tính 0)",
                 "provisional_actual_total": "Tổng thực tế tạm tính (riêng, không phải kết quả mô hình)",
                 "provisional_wape": "WAPE tạm tính (riêng)", "closed_actual_total": "Tổng thực tế đã chốt cuối ngày - cần xác minh (riêng)",
                 "closed_wape": "WAPE của dòng đã chốt cuối ngày - cần xác minh (riêng)",
                 "zero_absent": "Dòng đã chốt có thực tế 0 vì SKU x FC không có đơn trong ngày",
                 "rule_final": "Quy tắc thực tế đã hoàn tất"},
        "basis_final": "Chỉ các dòng có thực tế đã hoàn tất (đã chốt từ D-1); dòng tạm tính / đã chốt cuối ngày tính riêng",
        "rule_final": ("Thực tế của một ngày đã qua được chốt (đóng băng) từ lần D-1 thành công đã ghi ngày đó: D-1 đã kiểm tra nguồn đủ dữ liệu, phạm vi của lần nạp bao trùm ngày, và lần nạp chạy sau khi ngày kết thúc (giờ Việt Nam). Từ đó số không bao giờ đổi, kể cả khi nguồn sửa lịch sử, đơn bị hủy hay một SKU x FC vắng ở lần nạp sau. Hôm nay và ngày chưa chốt được thì là tạm tính; ngày không chốt được ghi lý do."),
        "rule_backup": ("Ngày chạy không có phiên forecast hợp lệ dùng snapshot cuối ngày (7 ngày kế tiếp) hoàn chỉnh mới nhất "
                        "còn bao phủ ngày được dự báo; luôn ưu tiên forecast chính. Không có snapshot bao phủ = thiếu dữ "
                        "liệu forecast (không điền 0, không tạo số mới)."),
        "rule_close": ("Vào giờ chốt cuối ngày (giờ Việt Nam, mặc định 23:59) thực tế của ngày được chốt thành một bản lưu riêng. Nguồn chưa có tín hiệu "
                       "hoàn tất thì là 'Đã chốt - cần xác minh', không phải 'Đã hoàn tất'. Dữ liệu đến muộn tạo bản chốt "
                       "bổ sung (revision) có số trước/sau; bản chốt cũ không bị sửa."),
        "source": {"PRIMARY": "Forecast chính", "SNAPSHOT": "Snapshot dự phòng", "MISSING": "Thiếu dữ liệu forecast"},
        "rule_d1": ("Mỗi ngày chạy chỉ lưu forecast của ngày hôm sau (D+1) từ phiên forecast hợp lệ mới nhất của ngày đó "
                    "(phiên = một lần forecast đã publish thành công). Forecast đã lưu không bao giờ bị sửa."),
        "rule_actual": ("Thực tế đọc từ dữ liệu D-1 đã nạp (SKU x FC không có dòng trong ngày đã nạp = 0); trước khi D-1 nạp "
                        "ngày đó: số lũy kế của snapshot D0 mới nhất. 'Đã hoàn tất' chỉ khi ngày đã được chốt từ D-1 (bản đóng "
                        "băng, xem quy tắc thực tế đã hoàn tất); ngày đã chốt cuối ngày nhưng chưa chốt từ D-1 là 'Đã chốt - "
                        "cần xác minh'; còn lại là 'Tạm tính'. Ô trống = chưa có dữ liệu thực tế (không phải 0)."),
        "rule_wape": ("Forecast = số lượng dự báo số nguyên (làm tròn nửa lên giá trị đã lưu, không âm; đúng số trên màn "
                      "hình). Sai lệch = Forecast - Thực tế; WAPE = tổng |Forecast - Thực tế| / tổng Thực tế, chỉ trên các dòng có thực tế "
                      "đã hoàn tất (dòng tạm tính / đã chốt cuối ngày tính riêng); không tính khi tổng thực tế = 0. WAPE theo dòng = |F - T| / T khi T > 0."),
        "status": {"COMPLETE": "Đã hoàn tất", "CLOSED": "Đã chốt - cần xác minh", "PROVISIONAL": "Tạm tính",
                   "NO_ACTUAL": "Chưa có dữ liệu thực tế"},
        "reason": {"COMPLETION_SIGNAL": "D-1 đã nạp theo tín hiệu hoàn tất của nguồn",
                   "FINALIZED_D1": "Đã chốt từ lần D-1 thành công (bản đóng băng, không đổi nữa)",
                   "D1_NOT_FINALIZED": "D-1 đã nạp nhưng ngày chưa được chốt - số có thể còn thay đổi",
                   "CLOSED_D0": "Đã chốt cuối ngày theo snapshot D0 cuối ngày; nguồn chưa xác nhận đầy đủ",
                   "CLOSED_D1": "Đã chốt; D-1 đã nạp nhưng nguồn chưa có tín hiệu hoàn tất",
                   "D1_NO_COMPLETION_SIGNAL": "D-1 đã nạp, nguồn chưa có tín hiệu hoàn tất",
                   "D0_INTRADAY": "Lũy kế trong ngày (snapshot D0)",
                   "D0_LAST_READ": "Snapshot D0 cuối của ngày, D-1 chưa nạp",
                   "FUTURE_DATE": "Ngày chưa tới", "NO_D0_READ_TODAY": "Hôm nay chưa có snapshot D0",
                   "NOT_LOADED_YET": "D-1 chưa nạp ngày này", "DAY_WITHOUT_DATA": "Ngày đã nạp nhưng không có dòng dữ liệu"},
        "cols_sessions": {"run_date": "Ngày chạy forecast", "target_date": "Ngày được dự báo",
                          "session_started_at": "Thời điểm phiên", "published_at": "Thời điểm publish",
                          "forecast_run_id": "Mã phiên (run ID)", "model_version": "Phiên bản mô hình",
                          "official": "Là phiên chính thức", "decision": "Quyết định khi ghi nhận",
                          "decision_reason": "Lý do", "capture_mode": "Cách ghi nhận", "captured_at": "Ghi nhận lúc",
                          "n_rows": "Số dòng D+1", "usage_status": "Đánh giá sử dụng"},
        "cols_daily": {"run_date": "Ngày chạy forecast", "target_date": "Ngày được dự báo", "forecast": "Forecast",
                       "actual": "Thực tế", "deviation": "Sai lệch (F - T)", "wape": "WAPE",
                       "forecast_run_id": "Mã phiên (run ID)", "status": "Trạng thái thực tế", "reason": "Chi tiết",
                       "forecast_source": "Nguồn forecast", "snapshot_id": "Mã snapshot dự phòng",
                       "snapshot_business_date": "Ngày nghiệp vụ của snapshot"},
        "cols_rows": {"run_date": "Ngày chạy forecast", "target_date": "Ngày được dự báo", "forecast_run_id": "Mã phiên (run ID)",
                      "model_version": "Phiên bản mô hình", "session_started_at": "Thời điểm phiên được chọn", "sku_id": "SKU",
                      "product_name": "Tên sản phẩm", "fc_id": "FC/kho", "forecast": "Forecast", "actual": "Thực tế",
                      "deviation": "Sai lệch (F - T)", "row_wape": "WAPE dòng", "status": "Trạng thái thực tế",
                      "reason": "Chi tiết", "actual_as_of": "Thực tế tính đến", "forecast_source": "Nguồn forecast",
                      "snapshot_id": "Mã snapshot dự phòng", "snapshot_business_date": "Ngày nghiệp vụ của snapshot",
                      "snapshot_created_at": "Snapshot tạo lúc"},
        "no_history": "Chưa có lịch sử forecast được lưu cho ngày này",
        "yes": "Có", "no": "Không", "language_name": "Tiếng Việt", "no_product_name": "Chưa có tên sản phẩm",
        "date_fmt": "%d/%m/%Y", "excel_date_fmt": "DD/MM/YYYY", "time_suffix": "giờ Việt Nam, UTC+7",
    },
    "en": {
        "sheet_info": "Info", "sheet_sessions": "Forecast sessions", "sheet_daily": "By day",
        "sheet_rows": "SKU x FC detail", "field": "Field", "value": "Value", "all": "All",
        "info": {"export_format_version": "File format version", "language": "Language",
                 "generated_at_vn": "Exported at (Vietnam time)", "scope": "Dataset (scope)", "data_source": "Data source",
                 "run_from": "Forecast run date from", "run_to": "Forecast run date to", "fc_filter": "FC/warehouse filter",
                 "search_filter": "SKU / product name filter", "status_filter": "Actual status filter",
                 "rows": "SKU x FC rows", "days_with_history": "Run dates with history",
                 "forecast_total": "Stored forecast total", "actual_total": "Complete actual total (finalized rows only)",
                 "forecast_compared": "Forecast on the finalized rows",
                 "deviation": "Deviation forecast - actual (finalized rows)", "wape": "WAPE (finalized rows)",
                 "kpi_status": "Actual figures status", "rule_d1": "Forecast storage rule", "rule_actual": "Actual rule",
                 "rule_wape": "Formulas", "source_filter": "Forecast source filter",
                 "days_primary": "Run dates using the official forecast", "days_backup": "Run dates using the backup snapshot",
                 "rule_backup": "Backup snapshot rule", "rule_close": "End-of-day actual close rule",
                 "basis": "Basis of the actual KPI", "rows_final": "Rows with a complete (finalized) actual",
                 "rows_provisional": "Rows with a provisional actual", "rows_closed": "Rows closed at the end of the day - needs verification",
                 "rows_no_actual": "Rows without an actual (not counted as 0)",
                 "provisional_actual_total": "Provisional actual total (separate, not a model result)",
                 "provisional_wape": "Provisional WAPE (separate)", "closed_actual_total": "Actual closed at the end of the day - needs verification (separate)",
                 "closed_wape": "WAPE of the rows closed at the end of the day (separate)",
                 "zero_absent": "Finalized rows whose actual is 0 because the SKU x FC had no order that day",
                 "rule_final": "Complete actual rule"},
        "basis_final": "Only rows with a complete actual (finalized from D-1); provisional / end-of-day closed rows are counted apart",
        "rule_final": ("The actual of a past day is finalized (frozen) from the successful D-1 load that wrote that day: D-1 checked that the source was complete, the load window covers the day and the load ran after the day ended (Vietnam time). The number never changes afterwards, not even when the source corrects history, an order is cancelled or a SKU x FC is missing from a later load. Today and days that cannot be finalized yet are provisional; a day that cannot be finalized records why."),
        "rule_backup": ("A run date without a valid forecast session uses the newest complete end-of-day snapshot (next 7 "
                        "days) that still covers its forecast date; the official forecast always wins. No covering snapshot "
                        "= forecast data missing (never 0, no new number is made)."),
        "rule_close": ("At the end-of-day close time (Vietnam time, default 23:59) the actual of the day is closed into a separate copy. Without a completion "
                       "signal from the source it is 'Closed - needs verification', not 'Complete'. Late data adds a revision "
                       "with before/after figures; an earlier close is never changed."),
        "source": {"PRIMARY": "Official forecast", "SNAPSHOT": "Backup snapshot", "MISSING": "Forecast data missing"},
        "rule_d1": ("For each run date only the forecast of the next day (D+1) of the newest valid forecast session of that "
                    "day is kept (session = one successfully published forecast). A stored forecast is never changed."),
        "rule_actual": ("Actual comes from the loaded D-1 data (a SKU x FC without a row on a loaded day = 0); before D-1 has "
                        "loaded the day: the cumulative quantity of the latest D0 snapshot. 'Complete' only when the day was "
                        "finalized from D-1 (frozen copy, see the complete actual rule); a day closed at the end of the day but "
                        "not finalized is 'Closed - needs verification'; otherwise 'Provisional'. Empty = no actual yet (not 0)."),
        "rule_wape": ("Forecast = whole-number forecast quantity (stored value rounded half up, never below 0; the number "
                      "shown on screen). Deviation = forecast - actual; WAPE = sum |forecast - actual| / sum actual, only over the rows with a "
                      "complete actual (provisional / end-of-day closed rows apart); not computed when that sum is 0. Row WAPE = |F - A| / A when A > 0."),
        "status": {"COMPLETE": "Complete", "CLOSED": "Closed - needs verification", "PROVISIONAL": "Provisional",
                   "NO_ACTUAL": "No actual data yet"},
        "reason": {"COMPLETION_SIGNAL": "D-1 loaded on the source's completion signal",
                   "FINALIZED_D1": "Finalized from a successful D-1 load (frozen copy, never changes again)",
                   "D1_NOT_FINALIZED": "D-1 loaded but the day is not finalized yet - the number may still change",
                   "CLOSED_D0": "Closed at the end of the day from the last D0 snapshot; not confirmed complete by the source",
                   "CLOSED_D1": "Closed; D-1 loaded without a completion signal from the source",
                   "D1_NO_COMPLETION_SIGNAL": "D-1 loaded, no completion signal from the source",
                   "D0_INTRADAY": "Cumulative so far today (D0 snapshot)",
                   "D0_LAST_READ": "Last D0 snapshot of the day, D-1 not loaded yet",
                   "FUTURE_DATE": "Date not reached yet", "NO_D0_READ_TODAY": "No D0 snapshot today yet",
                   "NOT_LOADED_YET": "D-1 has not loaded this day", "DAY_WITHOUT_DATA": "Day loaded but without any data row"},
        "cols_sessions": {"run_date": "Forecast run date", "target_date": "Forecast date",
                          "session_started_at": "Session time", "published_at": "Published at",
                          "forecast_run_id": "Session (run ID)", "model_version": "Model version", "official": "Official session",
                          "decision": "Decision when recorded", "decision_reason": "Reason", "capture_mode": "Recorded how",
                          "captured_at": "Recorded at", "n_rows": "D+1 rows", "usage_status": "Usage assessment"},
        "cols_daily": {"run_date": "Forecast run date", "target_date": "Forecast date", "forecast": "Forecast",
                       "actual": "Actual", "deviation": "Deviation (F - A)", "wape": "WAPE",
                       "forecast_run_id": "Session (run ID)", "status": "Actual status", "reason": "Detail",
                       "forecast_source": "Forecast source", "snapshot_id": "Backup snapshot ID",
                       "snapshot_business_date": "Snapshot business date"},
        "cols_rows": {"run_date": "Forecast run date", "target_date": "Forecast date", "forecast_run_id": "Session (run ID)",
                      "model_version": "Model version", "session_started_at": "Selected session time", "sku_id": "SKU",
                      "product_name": "Product name", "fc_id": "FC/warehouse", "forecast": "Forecast", "actual": "Actual",
                      "deviation": "Deviation (F - A)", "row_wape": "Row WAPE", "status": "Actual status",
                      "reason": "Detail", "actual_as_of": "Actual as of", "forecast_source": "Forecast source",
                      "snapshot_id": "Backup snapshot ID", "snapshot_business_date": "Snapshot business date",
                      "snapshot_created_at": "Snapshot created at"},
        "no_history": "No stored forecast history for this day",
        "yes": "Yes", "no": "No", "language_name": "English", "no_product_name": "No product name yet",
        "date_fmt": "%d/%m/%Y", "excel_date_fmt": "DD/MM/YYYY", "time_suffix": "Vietnam time, UTC+7",
    },
}


def history_labels(lang: str | None) -> tuple[str, dict]:
    lang = lang if lang in HISTORY else "vi"
    L = dict(HISTORY[lang])
    L["fmt_date"] = lambda d: fmt_date(d, L)
    L["fmt_time"] = lambda t: fmt_vn_time(t, L)
    return lang, L
