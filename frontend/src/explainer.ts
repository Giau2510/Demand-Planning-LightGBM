import { numberLocale } from "./i18n";

/** 1.2.14 forecast explainer - DISPLAY formatting only. The backend sends every value with its full precision; these
 *  strings are never parsed or computed with.
 *  - intermediate numbers: at most 2 decimals, Vietnamese format in Vietnamese ("2,05", "125,40", "-0,35");
 *    a whole number keeps no decimals ("2.669"), a non-zero value that would show as 0,00 is "≈0,00" (see isTiny);
 *  - the final forecast: a whole number ("125"). */
export function fmt2(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (isTiny(v)) return `≈${(0).toLocaleString(numberLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const whole = Number.isInteger(v);
  return v.toLocaleString(numberLocale(), { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 });
}

export const isTiny = (v: number | null | undefined) => typeof v === "number" && v !== 0 && Math.abs(v) < 0.005;

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString(numberLocale(), { maximumFractionDigits: 0 });
}

/** The value shown with 2 decimals, as a number (to tell whether displayed parts add up to the displayed total). */
export const shown2 = (v: number) => Math.round(v * 100) / 100;

/** True when the displayed (rounded) parts do not add up to the displayed (rounded) total: the page then says that the
 *  difference comes from rounding the display, never changes a part to make the sum match. */
export function roundingGap(parts: number[], total: number): boolean {
  const s = parts.reduce((a, b) => a + shown2(b), 0);
  return Math.abs(shown2(s) - shown2(total)) >= 0.005;
}

type T2 = { vi: string; en: string };
const tx = (vi: string, en: string): T2 => ({ vi, en });

/** Meaning (business) and general formula of each feature of the production models (app/ml/features.py). */
export const FEATURE_TEXT: Record<string, { meaning: T2; formula: T2 }> = {
  sku_code: { meaning: tx("Mã SKU (biến phân loại)", "SKU code (categorical)"),
    formula: tx("sku_code = số thứ tự của SKU trong bảng mã lưu cùng model", "sku_code = index of the SKU in the code table saved with the model") },
  fc_code: { meaning: tx("Mã kho / FC (biến phân loại)", "FC code (categorical)"),
    formula: tx("fc_code = số thứ tự của FC trong bảng mã lưu cùng model", "fc_code = index of the FC in the code table saved with the model") },
  series_age: { meaning: tx("Số ngày SKU × FC đã có đơn", "Days since the first order of the series"),
    formula: tx("series_age = ngày gốc dự báo − ngày có đơn đầu tiên", "series_age = forecast origin − first order day") },
  lag: { meaning: tx("Nhu cầu đúng k ngày trước ngày gốc", "Demand exactly k days before the origin"),
    formula: tx("lag_k = Y(ngày gốc − k)", "lag_k = Y(origin − k)") },
  roll_mean: { meaning: tx("Nhu cầu trung bình w ngày gần nhất", "Mean demand of the last w days"),
    formula: tx("roll_mean_w = tổng Y của các ngày có dữ liệu trong w ngày trước ngày gốc / số ngày đó", "roll_mean_w = sum of Y over the known days among the w days before the origin / their number") },
  roll_std: { meaning: tx("Độ dao động của nhu cầu w ngày gần nhất", "Spread of demand over the last w days"),
    formula: tx("roll_std_w = √( Σ (Y − trung bình)² / n ), n = số ngày có dữ liệu (cần n > 1)", "roll_std_w = √( Σ (Y − mean)² / n ), n = known days (needs n > 1)") },
  zero_share_28: { meaning: tx("Tỷ lệ ngày không có nhu cầu trong 28 ngày", "Share of zero-demand days in 28 days"),
    formula: tx("zero_share_28 = số ngày Y = 0 / số ngày có dữ liệu trong 28 ngày", "zero_share_28 = days with Y = 0 / known days in 28 days") },
  days_since_last_sale: { meaning: tx("Số ngày kể từ lần bán gần nhất", "Days since the last sale"),
    formula: tx("days_since_last_sale = ngày gốc − ngày bán gần nhất (Y > 0,5) trong 180 ngày; không có thì 181", "days_since_last_sale = origin − last day with Y > 0.5 within 180 days; none: 181") },
  roll_max_28: { meaning: tx("Nhu cầu lớn nhất trong 28 ngày", "Largest demand in 28 days"),
    formula: tx("roll_max_28 = max Y của các ngày có dữ liệu trong 28 ngày", "roll_max_28 = max Y over the known days in 28 days") },
  price_last: { meaning: tx("Giá bán trung bình gần nhất", "Latest average unit price"),
    formula: tx("price_last = giá TB của ngày trước ngày gốc (giữ giá gần nhất nếu ngày đó không có)", "price_last = average price of the day before the origin (last known price carried forward)") },
  price_rel_28: { meaning: tx("Giá gần nhất so với giá TB 28 ngày", "Latest price relative to the 28-day mean"),
    formula: tx("price_rel_28 = price_last / trung bình giá 28 ngày", "price_rel_28 = price_last / 28-day mean price") },
  disc_last: { meaning: tx("Tỷ lệ chiết khấu gần nhất", "Latest discount rate"),
    formula: tx("disc_last = tỷ lệ chiết khấu của ngày trước ngày gốc (giữ giá trị gần nhất)", "disc_last = discount rate of the day before the origin (carried forward)") },
  promo_last: { meaning: tx("Tỷ lệ dòng khuyến mãi ngày gần nhất", "Promotion share of the last day"),
    formula: tx("promo_last = promo_share của ngày trước ngày gốc (không có thì 0)", "promo_last = promo_share of the day before the origin (unknown: 0)") },
  promo_mean_7: { meaning: tx("Tỷ lệ khuyến mãi trung bình 7 ngày", "Mean promotion share of 7 days"),
    formula: tx("promo_mean_7 = trung bình promo_share 7 ngày (không có thì 0)", "promo_mean_7 = mean promo_share of 7 days (unknown: 0)") },
  open_hours_last: { meaning: tx("Số giờ mở bán ngày gần nhất", "Open hours of the last day"),
    formula: tx("open_hours_last = giờ mở bán của ngày trước ngày gốc (không có thì để trống)", "open_hours_last = open hours of the day before the origin (unknown stays empty)") },
  open_hours_mean_7: { meaning: tx("Giờ mở bán trung bình 7 ngày", "Mean open hours of 7 days"),
    formula: tx("open_hours_mean_7 = trung bình giờ mở bán của các ngày có dữ liệu trong 7 ngày", "open_hours_mean_7 = mean open hours over the known days of 7 days") },
  cust_mean_28: { meaning: tx("Số khách hàng trung bình mỗi ngày (28 ngày)", "Mean customers per day (28 days)"),
    formula: tx("cust_mean_28 = trung bình số khách của các ngày có dữ liệu trong 28 ngày", "cust_mean_28 = mean customers over the known days of 28 days") },
  cust_repeat_share_28: { meaning: tx("Tỷ lệ khách mua lại (28 ngày)", "Share of repeat customers (28 days)"),
    formula: tx("cust_repeat_share_28 = Σ khách mua lại / Σ khách (các ngày có đủ hai số)", "cust_repeat_share_28 = Σ repeat customers / Σ customers (days with both)") },
  cust_repeat_interval_28: { meaning: tx("Khoảng cách trung bình giữa hai lần mua của khách mua lại (ngày)", "Mean days between orders of repeat customers"),
    formula: tx("cust_repeat_interval_28 = Σ số ngày từ lần mua trước / Σ khách mua lại", "cust_repeat_interval_28 = Σ days since the previous order / Σ repeat customers") },
  dow: { meaning: tx("Thứ trong tuần của ngày dự báo", "Weekday of the forecast day"),
    formula: tx("dow = 1 (Thứ 2) … 7 (Chủ nhật)", "dow = 1 (Monday) … 7 (Sunday)") },
  dom: { meaning: tx("Ngày trong tháng của ngày dự báo", "Day of month of the forecast day"), formula: tx("dom = ngày trong tháng", "dom = day of month") },
  month: { meaning: tx("Tháng của ngày dự báo", "Month of the forecast day"), formula: tx("month = tháng (1–12)", "month = month (1–12)") },
  weekofyear: { meaning: tx("Tuần ISO của ngày dự báo", "ISO week of the forecast day"), formula: tx("weekofyear = số tuần ISO", "weekofyear = ISO week number") },
  is_weekend: { meaning: tx("Ngày dự báo có phải cuối tuần", "Is the forecast day a weekend"), formula: tx("is_weekend = 1 nếu Thứ 7 / Chủ nhật, ngược lại 0", "is_weekend = 1 on Saturday / Sunday, else 0") },
  days_to_month_end: { meaning: tx("Số ngày đến cuối tháng", "Days to the end of the month"), formula: tx("days_to_month_end = số ngày của tháng − ngày trong tháng", "days_to_month_end = days in month − day of month") },
  horizon: { meaning: tx("Ngày dự báo là ngày thứ mấy kể từ ngày gốc", "Forecast day number counted from the origin"),
    formula: tx("horizon = ngày dự báo − ngày gốc + 1", "horizon = forecast day − origin + 1") },
};

export function featureText(name: string) {
  if (FEATURE_TEXT[name]) return FEATURE_TEXT[name];
  if (name.startsWith("lag_")) return FEATURE_TEXT.lag;
  if (name.startsWith("roll_mean_")) return FEATURE_TEXT.roll_mean;
  if (name.startsWith("roll_std_")) return FEATURE_TEXT.roll_std;
  return null;
}

export const CHECK_TEXT: Record<string, T2> = {
  FEATURE_NAMES: tx("Danh sách feature: cấu hình = file model = bảng mã", "Feature list: settings = model file = code table"),
  METHOD_LIGHTGBM: tx("Chuỗi này được dự báo bằng LightGBM (không phải quy tắc dự phòng)", "This series is forecast by LightGBM (not a fallback rule)"),
  FEATURES_RECOMPUTED: tx("Từng feature tính lại độc lập = giá trị đưa vào model", "Each feature recomputed independently = model input"),
  TREE_LEAVES_EQUAL_LIGHTGBM: tx("Lá của từng cây = lá LightGBM chọn", "Leaf of every tree = the leaf LightGBM chooses"),
  RAW_SUM_EQUALS_LIGHTGBM: tx("Tổng giá trị lá = điểm thô của LightGBM", "Sum of leaf values = LightGBM raw score"),
  OUTPUT_TRANSFORM_EQUALS_LIGHTGBM: tx("Biến đổi đầu ra = dự đoán của LightGBM", "Output transform = LightGBM prediction"),
  PUBLISHED_EQUALS_STORED: tx("Kết quả tính lại = forecast đã lưu", "Recomputed result = stored forecast"),
  INPUTS_AS_AT_RUN: tx("Dữ liệu đầu vào đúng như lúc tạo forecast", "Inputs as they were when the forecast was made"),
  OPEN_HOURS_OVERRIDE: tx("Quy tắc giờ mở bán của chủ hệ thống áp dụng như lần chạy", "Owner's open-hours rule applied as in the run"),
};

export const STATUS_TEXT: Record<string, T2> = {
  NO_FORECAST: tx("Chưa có forecast thật nào đang được dùng để giải thích.", "No real forecast in use to explain yet."),
  NOT_FOUND: tx("Không tìm thấy giá trị forecast này trong forecast đang dùng.", "This forecast value is not in the forecast in use."),
  NOT_LIGHTGBM: tx("Giá trị này do quy tắc dự phòng tạo ra, không phải model LightGBM.", "This value comes from a fallback rule, not from the LightGBM model."),
  MODEL_MISSING: tx("Không đọc được file model đã kiểm chứng của forecast đang dùng.", "The verified model file of the forecast in use cannot be read."),
  DATA_UNAVAILABLE: tx("Dữ liệu của lần chạy không còn đủ để tái lập giá trị này.", "The run's data is no longer available to rebuild this value."),
  UNSUPPORTED_STRATEGY: tx("Model đang dùng không phải chiến lược DIRECT nên chưa giải thích từng bước được.", "The model in use is not DIRECT: no step-by-step explanation yet."),
  BAD_REQUEST: tx("Tham số không hợp lệ.", "Invalid parameters."),
};
