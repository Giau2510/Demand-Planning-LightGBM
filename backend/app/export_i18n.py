"""Localised labels for Excel exports. Identifiers (SKU, FC, run id, model version, method code) are never
translated; numbers are written unchanged. EXPORT_FORMAT_VERSION is stamped into the Info sheet."""
from __future__ import annotations

EXPORT_FORMAT_VERSION = "5"   # 5: product name column after the SKU (1.2.4); 4: DD/MM/YYYY, VN local times, method label before the code

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
        "cols_daily": {"sku_id": "SKU", "product_name": "Tên sản phẩm", "fc_id": "FC/kho", "target_date": "Ngày", "horizon_day": "Ngày thứ",
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
        "cols_daily": {"sku_id": "SKU", "product_name": "Product name", "fc_id": "FC/warehouse", "target_date": "Date", "horizon_day": "Day #",
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
