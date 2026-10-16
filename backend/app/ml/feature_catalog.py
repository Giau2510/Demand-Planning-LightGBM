"""Business description of every LightGBM input feature, written from the implementation in ml/features.py
(features_at). One source for the explanation panel, the feature catalogue API and the Algorithm page.

Conventions verified in the code (features_at(p, ..., t)):
* t is the TARGET day (the day being forecast). Every lag/rolling/price/promotion feature reads columns [0, t) only,
  i.e. strictly BEFORE the target day; calendar features describe the target day itself.
* "Known day" = not NaN. NaN = the series had not started yet, or the whole dataset has no order that calendar day
  (unknown). A known day with no order is 0. NaN is never turned into 0 for demand features.
* Means / std / max / zero share are computed over the known days of the window (np.nan* functions); the
  denominator is the number of known days, not the window length. Std is the population std (ddof = 0) and needs
  at least 2 known days.
* After the forecast origin (recursive forecasting) the "history" of a later target day contains the model's own
  earlier forecasts; price is held at the last known value and promotion is assumed 0.
"""
from __future__ import annotations

from datetime import date, timedelta

from .features import LAGS, LAST_SALE_WINDOW, ROLL_WINDOWS

_MISSING_DEMAND = ("Ngày không rõ (NaN) bị bỏ qua, không tính là 0; ngày có dữ liệu nhưng không có đơn tính là 0.",
                   "Unknown days (NaN) are skipped, never counted as 0; a known day without orders counts as 0.")


def _static(name):
    d = {
        "sku_code": dict(vi="Mã SKU (dạng danh mục)", en="SKU (categorical code)",
                         fvi="Số thứ tự của SKU trong danh sách SKU đã sắp xếp lúc huấn luyện; LightGBM xử lý như biến danh mục, không phải số lớn/nhỏ.",
                         fen="Index of the SKU in the sorted SKU list at training time; LightGBM treats it as a category, not a magnitude.",
                         mvi="Cho mô hình học mức bán riêng của từng SKU.", men="Lets the model learn each SKU's own level.",
                         uvi="mã", uen="code"),
        "fc_code": dict(vi="Mã FC/kho (dạng danh mục)", en="FC/warehouse (categorical code)",
                        fvi="Số thứ tự của FC trong danh sách FC đã sắp xếp lúc huấn luyện; xử lý như biến danh mục.",
                        fen="Index of the FC in the sorted FC list at training time; treated as a category.",
                        mvi="Cho mô hình học khác biệt giữa các kho.", men="Lets the model learn differences between FCs.",
                        uvi="mã", uen="code"),
        "series_age": dict(vi="Tuổi chuỗi SKU×FC", en="Series age",
                           fvi="Số ngày từ ngày có đơn đầu tiên của SKU×FC đến ngày dự báo (ngày dự báo − ngày đầu tiên).",
                           fen="Days from the first order day of the SKU×FC to the target day (target day − first day).",
                           mvi="Chuỗi mới thường dao động hơn chuỗi lâu năm.", men="Young series behave differently from mature ones.",
                           uvi="ngày", uen="days"),
        "dow": dict(vi="Thứ trong tuần của ngày dự báo", en="Day of week of the target day",
                    fvi="0 = Thứ Hai, 1 = Thứ Ba, …, 5 = Thứ Bảy, 6 = Chủ Nhật (của chính ngày dự báo).",
                    fen="0 = Monday, 1 = Tuesday, …, 5 = Saturday, 6 = Sunday (of the target day itself).",
                    mvi="Mùa vụ trong tuần (vd. cuối tuần đặt ít hơn).", men="Weekly seasonality.", uvi="mã thứ", uen="day code"),
        "dom": dict(vi="Ngày trong tháng", en="Day of month", fvi="Ngày 1–31 của ngày dự báo.", fen="Day 1–31 of the target day.",
                    mvi="Hiệu ứng đầu/cuối tháng.", men="Start/end of month effects.", uvi="ngày", uen="day"),
        "month": dict(vi="Tháng", en="Month", fvi="Tháng 1–12 của ngày dự báo.", fen="Month 1–12 of the target day.",
                      mvi="Mùa vụ theo tháng.", men="Monthly seasonality.", uvi="tháng", uen="month"),
        "weekofyear": dict(vi="Tuần trong năm (ISO)", en="ISO week of year", fvi="Số tuần ISO 1–53 của ngày dự báo.",
                           fen="ISO week number 1–53 of the target day.", mvi="Mùa vụ theo tuần trong năm.", men="Seasonality over the year.",
                           uvi="tuần", uen="week"),
        "is_weekend": dict(vi="Cuối tuần", en="Weekend", fvi="1 nếu ngày dự báo là Thứ Bảy hoặc Chủ Nhật, ngược lại 0.",
                           fen="1 if the target day is Saturday or Sunday, else 0.", mvi="Hành vi đặt hàng cuối tuần.", men="Weekend ordering behaviour.",
                           uvi="0/1", uen="0/1"),
        "days_to_month_end": dict(vi="Số ngày đến cuối tháng", en="Days to month end",
                                  fvi="Số ngày của tháng − ngày trong tháng của ngày dự báo (0 = ngày cuối tháng).",
                                  fen="Days in the month − day of month of the target day (0 = last day).",
                                  mvi="Hiệu ứng chốt đơn cuối tháng.", men="End-of-month ordering.", uvi="ngày", uen="days"),
    }
    return d.get(name)


def describe(name: str, target_date: str | None = None) -> dict:
    """Catalogue entry of one feature. With target_date (YYYY-MM-DD), the concrete calendar window is included."""
    t = date.fromisoformat(target_date) if target_date else None

    def win(days_back_from: int, days_back_to: int = 1):
        if t is None:
            return None
        return {"from": str(t - timedelta(days=days_back_from)), "to": str(t - timedelta(days=days_back_to))}

    e: dict = {"name": name, "includes_target_day": False, "window": None, "window_days": None}
    st = _static(name)
    if st:
        cal = name in ("dow", "dom", "month", "weekofyear", "is_weekend", "days_to_month_end")
        e.update(group="CALENDAR" if cal else "IDENTITY", includes_target_day=cal or name == "series_age",
                 vi={"name": st["vi"], "formula": st["fvi"], "meaning": st["mvi"], "unit": st["uvi"],
                     "missing": "Không có giá trị thiếu." if cal or name != "series_age" else "Luôn có giá trị (chuỗi đã bắt đầu)."},
                 en={"name": st["en"], "formula": st["fen"], "meaning": st["men"], "unit": st["uen"],
                     "missing": "Never missing." if cal or name != "series_age" else "Always present (the series has started)."})
        if cal and t is not None:
            e["window"] = {"from": str(t), "to": str(t)}
        return e
    if name.startswith("lag_"):
        k = int(name[4:])
        e.update(group="LAG", window=win(k, k), window_days=1,
                 vi={"name": f"Nhu cầu {k} ngày trước", "formula": f"Số lượng đặt của đúng ngày (ngày dự báo − {k} ngày); không lấy ngày khác thay thế.",
                     "meaning": "Mức bán gần đây; lag_7, lag_14, lag_21, lag_28 cùng thứ trong tuần với ngày dự báo." if k % 7 == 0 else "Mức bán ngay trước ngày dự báo.",
                     "unit": "đơn vị sản phẩm", "missing": "Ngày đó không rõ (NaN) → giá trị thiếu, LightGBM đi nhánh 'missing'; ngày có dữ liệu không có đơn → 0."},
                 en={"name": f"Demand {k} days before", "formula": f"Ordered quantity of exactly the day (target day − {k}); no other day is substituted.",
                     "meaning": "Recent level; lag_7/14/21/28 fall on the same weekday as the target day." if k % 7 == 0 else "Level right before the target day.",
                     "unit": "units", "missing": "Unknown day (NaN) → missing value, LightGBM's 'missing' branch; known day without orders → 0."})
        return e
    if name.startswith("roll_mean_"):
        w = int(name[10:])
        e.update(group="ROLLING", window=win(w), window_days=w,
                 vi={"name": f"Trung bình nhu cầu {w} ngày", "formula": f"Tổng số lượng ÷ số ngày ĐÃ BIẾT trong {w} ngày lịch trước ngày dự báo (từ ngày −{w} đến ngày −1). Mẫu số là số ngày có dữ liệu, không phải {w}.",
                     "meaning": "Mức bán bình quân gần đây.", "unit": "đơn vị/ngày", "missing": _MISSING_DEMAND[0] + " Không có ngày nào biết → thiếu."},
                 en={"name": f"{w}-day mean demand", "formula": f"Sum of quantities ÷ number of KNOWN days among the {w} calendar days before the target day (day −{w} to day −1). The denominator is the number of known days, not {w}.",
                     "meaning": "Recent average level.", "unit": "units/day", "missing": _MISSING_DEMAND[1] + " No known day → missing."})
        return e
    roll = {
        "roll_std_7": (7, "Độ dao động 7 ngày", "7-day variability",
                       "Độ lệch chuẩn tổng thể (chia cho số ngày đã biết, ddof = 0) của số lượng 7 ngày trước ngày dự báo; cần ≥ 2 ngày đã biết.",
                       "Population standard deviation (divided by the known days, ddof = 0) of the 7 days before the target day; needs ≥ 2 known days.",
                       "Nhu cầu ổn định hay thất thường.", "Stable vs erratic demand.", "đơn vị", "units"),
        "roll_std_28": (28, "Độ dao động 28 ngày", "28-day variability",
                        "Độ lệch chuẩn tổng thể (ddof = 0) của số lượng 28 ngày trước ngày dự báo, trên các ngày đã biết; cần ≥ 2 ngày đã biết.",
                        "Population standard deviation (ddof = 0) over the known days of the 28 days before the target day; needs ≥ 2 known days.",
                        "Nhu cầu ổn định hay thất thường.", "Stable vs erratic demand.", "đơn vị", "units"),
        "zero_share_28": (28, "Tỷ lệ ngày không có đơn (28 ngày)", "Zero-day share (28 days)",
                          "Số ngày ĐÃ BIẾT có số lượng = 0 ÷ số ngày ĐÃ BIẾT trong 28 ngày trước ngày dự báo. Ngày không rõ không nằm ở tử số lẫn mẫu số.",
                          "Known days with quantity 0 ÷ known days among the 28 days before the target day. Unknown days are in neither numerator nor denominator.",
                          "Mức độ gián đoạn của nhu cầu.", "How intermittent demand is.", "tỷ lệ 0–1", "share 0–1"),
        "roll_max_28": (28, "Nhu cầu lớn nhất 28 ngày", "28-day maximum",
                        "Số lượng lớn nhất trong các ngày đã biết của 28 ngày trước ngày dự báo.",
                        "Largest quantity among the known days of the 28 days before the target day.",
                        "Đỉnh nhu cầu gần đây.", "Recent peak.", "đơn vị", "units"),
        "days_since_last_sale": (LAST_SALE_WINDOW, "Số ngày từ lần bán gần nhất", "Days since last sale",
                                 f"Khoảng cách (ngày) từ ngày dự báo đến ngày gần nhất có số lượng > 0,5 trong {LAST_SALE_WINDOW} ngày trước; không có ngày nào → {LAST_SALE_WINDOW + 1}. Ngày không rõ được coi là không bán.",
                                 f"Days from the target day back to the latest day with quantity > 0.5 within the previous {LAST_SALE_WINDOW} days; none → {LAST_SALE_WINDOW + 1}. Unknown days count as no sale.",
                                 "Chuỗi còn bán đều hay đã lâu không bán.", "Whether the series still sells.", "ngày", "days"),
    }
    if name in roll:
        w, vi, en, fvi, fen, mvi, men, uvi, uen = roll[name]
        e.update(group="ROLLING", window=win(w), window_days=w,
                 vi={"name": vi, "formula": fvi, "meaning": mvi, "unit": uvi, "missing": _MISSING_DEMAND[0]},
                 en={"name": en, "formula": fen, "meaning": men, "unit": uen, "missing": _MISSING_DEMAND[1]})
        return e
    other = {
        "price_last": ("PRICE", 1, "Giá bán gần nhất", "Last price",
                       "Giá bình quân (Σ giá × số lượng ÷ Σ số lượng) của ngày trước ngày dự báo; ngày không có giá dùng giá đã biết gần nhất trước đó (forward-fill). Sau mốc dự báo: giữ giá đã biết cuối cùng.",
                       "Average price (Σ price × qty ÷ Σ qty) of the day before the target day; days without a price use the last known price (forward-fill). After the origin: last known price held.",
                       "Ảnh hưởng của giá.", "Price effect.", "đơn vị tiền", "currency", "Chưa từng có giá → thiếu.", "Never priced → missing."),
        "price_rel_28": ("PRICE", 28, "Giá so với trung bình 28 ngày", "Price vs 28-day mean",
                         "price_last ÷ trung bình giá (đã forward-fill) của 28 ngày trước ngày dự báo; > 1 = đang đắt hơn bình thường.",
                         "price_last ÷ mean (forward-filled) price of the 28 days before the target day; > 1 = pricier than usual.",
                         "Tác động của tăng/giảm giá.", "Effect of price changes.", "tỷ lệ", "ratio", "Thiếu giá hoặc trung bình ≤ 0 → thiếu.", "Missing price or mean ≤ 0 → missing."),
        "disc_last": ("PRICE", 1, "Tỷ lệ giảm giá gần nhất", "Last discount rate",
                      "Σ giảm giá ÷ Σ(giá × số lượng) của ngày trước ngày dự báo (forward-fill như giá). Sau mốc dự báo: giữ giá trị cuối.",
                      "Σ discount ÷ Σ(price × qty) of the day before the target day (forward-filled like price). After the origin: last value held.",
                      "Ảnh hưởng của giảm giá.", "Discount effect.", "tỷ lệ", "share", "Chưa từng có → thiếu.", "Never present → missing."),
        "promo_last": ("PROMOTION", 1, "Khuyến mãi hôm trước", "Promotion previous day",
                       "Tỷ lệ dòng đơn có khuyến mãi của ngày trước ngày dự báo; không rõ = 0. Sau mốc dự báo: giả định 0 (không có lịch khuyến mãi tương lai).",
                       "Share of order lines with a promotion on the day before the target day; unknown = 0. After the origin: assumed 0 (no future promotion calendar).",
                       "Ảnh hưởng của khuyến mãi.", "Promotion effect.", "tỷ lệ 0–1", "share 0–1", "Không rõ → 0 (theo thiết kế).", "Unknown → 0 (by design)."),
        "promo_mean_7": ("PROMOTION", 7, "Khuyến mãi trung bình 7 ngày", "Promotion 7-day mean",
                         "Trung bình tỷ lệ khuyến mãi của 7 ngày lịch trước ngày dự báo (chia 7, vì ngày không rõ = 0).",
                         "Mean promotion share of the 7 calendar days before the target day (divided by 7, unknown days = 0).",
                         "Khuyến mãi kéo dài gần đây.", "Recent sustained promotion.", "tỷ lệ 0–1", "share 0–1", "Không rõ → 0 (theo thiết kế).", "Unknown → 0 (by design)."),
    }
    if name in other:
        g, w, vi, en, fvi, fen, mvi, men, uvi, uen, missvi, missen = other[name]
        e.update(group=g, window=win(w) if w > 1 else win(1, 1), window_days=w,
                 vi={"name": vi, "formula": fvi, "meaning": mvi, "unit": uvi, "missing": missvi},
                 en={"name": en, "formula": fen, "meaning": men, "unit": uen, "missing": missen})
        return e
    return {**e, "group": "OTHER", "vi": {"name": name, "formula": "Không có mô tả.", "meaning": "", "unit": "", "missing": ""},
            "en": {"name": name, "formula": "No description.", "meaning": "", "unit": "", "missing": ""}}


ROLES = {   # expected role of each feature group (business wording)
    "IDENTITY": ("Nhận diện SKU, kho và độ 'già' của chuỗi.", "Identify the SKU, the FC and the series' maturity."),
    "LAG": ("Mức bán ở những ngày cụ thể trước ngày dự báo.", "Sales on specific days before the target day."),
    "ROLLING": ("Mức bán bình quân, độ dao động, tần suất bán gần đây.", "Recent average, variability and frequency of sales."),
    "CALENDAR": ("Mùa vụ theo ngày/tuần/tháng của ngày dự báo.", "Day/week/month seasonality of the target day."),
    "PRICE": ("Ảnh hưởng của giá và giảm giá đã biết.", "Effect of known price and discount."),
    "PROMOTION": ("Ảnh hưởng của khuyến mãi đã biết.", "Effect of known promotions."),
    "OTHER": ("", ""),
}


def catalogue(names: list[str]) -> list[dict]:
    return [describe(n) for n in names]


def all_lags_and_windows() -> dict:
    return {"lags": LAGS, "roll_windows": ROLL_WINDOWS, "last_sale_window": LAST_SALE_WINDOW}
