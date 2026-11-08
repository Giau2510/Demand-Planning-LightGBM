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
        "horizon": dict(vi="Kỳ dự báo (số ngày kể từ mốc)", en="Forecast horizon (days from the origin)",
                        fvi="Ngày dự báo − ngày cuối có dữ liệu (1 = ngày đầu tiên sau mốc dự báo). Chỉ có ở model dự báo trực tiếp (DIRECT); "
                            "ở model này mọi feature lag/rolling/giá được tính tại mốc dự báo từ dữ liệu thực.",
                        fen="Target day − last data day (1 = first day after the forecast origin). DIRECT models only; there every "
                            "lag / rolling / price feature is computed at the forecast origin from actual data.",
                        mvi="Cho model học khác biệt theo độ xa của ngày dự báo.", men="Lets the model learn how demand differs with the distance from the origin.",
                        uvi="ngày", uen="days"),
        "dow": dict(vi="Thứ trong tuần của ngày dự báo", en="Day of week of the target day",
                    fvi="Thứ của chính ngày dự báo: 1 = Thứ 2, 2 = Thứ 3, …, 6 = Thứ 7, 7 = Chủ nhật (model huấn luyện từ 1.2.9). "
                        "Model huấn luyện trước 1.2.9 giữ mã cũ 0 = Thứ 2 … 6 = Chủ nhật. Lịch sử dùng ngày của dòng nhu cầu "
                        "(order_date = cột created_date của D-1).",
                    fen="Weekday of the target day itself: 1 = Monday, 2 = Tuesday, …, 6 = Saturday, 7 = Sunday (models trained "
                        "from 1.2.9). Models trained before 1.2.9 keep their code 0 = Monday … 6 = Sunday. History uses the day of "
                        "the demand row (order_date = the D-1 created_date column).",
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
        # 1.2.9: SKU open hours of the day (BigQuery D-1 total_open_hours), mandatory for the BIGQUERY source
        "open_hours_last": ("AVAILABILITY", 1, "Giờ mở bán hôm trước", "Open hours previous day",
                            "Số giờ SKU mở bán (total_open_hours, 0–24) của ngày trước ngày dự báo / mốc dự báo, tại SKU × FC. Giờ mở bán của chính ngày dự báo chưa biết nên không dùng.",
                            "Hours the SKU was open for sale (total_open_hours, 0–24) on the day before the target day / forecast origin, per SKU × FC. The target day's own hours are not known yet and are not used.",
                            "SKU đóng bán / mở ít giờ thì đặt hàng ít hơn.", "A SKU closed or open for few hours sells less.", "giờ", "hours",
                            "Ngày đó không có dòng nhu cầu hoặc giá trị thiếu / khác nhau / ngoài 0–24 → thiếu (NaN), không thay bằng 0.",
                            "No demand row that day, or a missing / conflicting / out-of-range value → missing (NaN), never 0."),
        "open_hours_mean_7": ("AVAILABILITY", 7, "Giờ mở bán trung bình 7 ngày", "Open hours 7-day mean",
                              "Trung bình giờ mở bán của các ngày ĐÃ BIẾT trong 7 ngày lịch trước ngày dự báo / mốc dự báo (mẫu số = số ngày có giá trị).",
                              "Mean open hours of the KNOWN days among the 7 calendar days before the target day / origin (denominator = days with a value).",
                              "Tình trạng mở bán kéo dài gần đây.", "Recent sustained availability.", "giờ", "hours",
                              "Không có ngày nào có giá trị → thiếu (NaN).", "No day with a value → missing (NaN)."),
        # 1.2.9b: aggregate customer features (data/customers.py) - OFF by default, the identifier never leaves BigQuery
        "cust_mean_28": ("CUSTOMER", 28, "Số khách đặt bình quân 28 ngày", "Customers per day, 28-day mean",
                         "Trung bình số khách khác nhau đặt SKU × FC mỗi ngày, trên các ngày ĐÃ BIẾT trong 28 ngày lịch trước ngày dự báo / mốc dự báo.",
                         "Mean number of distinct customers ordering the SKU × FC per day, over the KNOWN days among the 28 calendar days before the target day / origin.",
                         "Độ rộng tập khách mua SKU tại kho.", "Breadth of the customer base of the SKU at the FC.", "khách/ngày", "customers/day",
                         "Không có ngày nào có mã khách → thiếu (NaN), không thay bằng 0.", "No day with a customer identifier → missing (NaN), never 0."),
        "cust_repeat_share_28": ("CUSTOMER", 28, "Tỷ lệ khách quay lại 28 ngày", "Repeat-customer share, 28 days",
                                 "Σ khách đã đặt cùng SKU × FC trong 90 ngày trước lần đặt ÷ Σ khách đặt, trên các ngày đã biết trong 28 ngày lịch trước ngày dự báo / mốc dự báo.",
                                 "Σ customers who had ordered the same SKU × FC in the 90 days before ÷ Σ customers, over the known days among the 28 calendar days before the target day / origin.",
                                 "Nhu cầu đến từ khách mua lại hay khách mới.", "Whether demand comes from returning or new customers.", "tỷ lệ 0–1", "share 0–1",
                                 "Không có ngày đã biết hoặc Σ khách = 0 → thiếu (NaN).", "No known day or Σ customers = 0 → missing (NaN)."),
        "cust_repeat_interval_28": ("CUSTOMER", 28, "Chu kỳ mua lại bình quân 28 ngày", "Mean repeat interval, 28 days",
                                    "Σ số ngày từ lần đặt trước ÷ Σ khách quay lại, trên các ngày đã biết trong 28 ngày lịch trước ngày dự báo / mốc dự báo.",
                                    "Σ days since the previous order ÷ Σ repeat customers, over the known days among the 28 calendar days before the target day / origin.",
                                    "Khách quay lại sau bao lâu (chu kỳ đặt hàng).", "How soon customers come back (order cycle).", "ngày", "days",
                                    "Không có khách quay lại trong các ngày đã biết → thiếu (NaN).", "No repeat customer in the known days → missing (NaN)."),
    }
    if name in other:
        g, w, vi, en, fvi, fen, mvi, men, uvi, uen, missvi, missen = other[name]
        e.update(group=g, window=win(w) if w > 1 else win(1, 1), window_days=w,
                 vi={"name": vi, "formula": fvi, "meaning": mvi, "unit": uvi, "missing": missvi},
                 en={"name": en, "formula": fen, "meaning": men, "unit": uen, "missing": missen})
        return e
    if name in EXTRA:
        # 1.3.2: computed at the forecast origin (DIRECT models only); the window is relative to the origin, not the
        # target day, so no calendar window is given
        g, w, vi, en, fvi, fen, mvi, men, uvi, uen, missvi, missen = EXTRA[name]
        e.update(group=g, window_days=w,
                 vi={"name": vi, "formula": fvi, "meaning": mvi, "unit": uvi, "missing": missvi},
                 en={"name": en, "formula": fen, "meaning": men, "unit": uen, "missing": missen})
        return e
    return {**e, "group": "OTHER", "vi": {"name": name, "formula": "Không có mô tả.", "meaning": "", "unit": "", "missing": ""},
            "en": {"name": name, "formula": "No description.", "meaning": "", "unit": "", "missing": ""}}


# 1.3.2 (docs/hoc_lai_2025_deal_20261030.md 1.4, ml/extra_features.py): the extra features of model.feature_set CHOT_LY
# (same period last year) and CHOT_LY_DEAL (+ deals), computed at the forecast origin from what is known at its 00:00
# (Vietnam time). Same tuple layout as `other` in describe().
_LY_MISSING = ("Cửa sổ bắt đầu trước ngày đầu lịch sử mở rộng (model.ly_history_start) → thiếu (NaN); ngày không có dòng nhu cầu = 0.",
               "A window starting before the first day of the extended history (model.ly_history_start) → missing (NaN); a day without a demand row = 0.")
_NO_DEAL = ("Không có deal đang chạy tại mốc → thiếu (NaN).", "No running deal at the origin → missing (NaN).")
_NO_DEAL_0 = ("Không có deal đang chạy tại mốc → 0.", "No running deal at the origin → 0.")
_RUNNING = ("deal đang chạy = deal hợp lệ của SKU × kho có ready_time ≤ mốc 00:00 và end_time ≥ mốc 00:00 (giờ Việt Nam)",
            "running deal = a valid deal of the SKU × FC with ready_time ≤ origin 00:00 and end_time ≥ origin 00:00 (Vietnam time)")
EXTRA = {
    "ly_same_day": ("SAME_PERIOD_LAST_YEAR", 1, "Nhu cầu cùng ngày năm trước", "Demand on the same day last year",
                    "Số lượng đặt của ngày (mốc dự báo − 364 ngày), cùng thứ trong tuần của năm trước.",
                    "Ordered quantity of the day (forecast origin − 364 days), the same weekday one year earlier.",
                    "Mùa vụ theo năm.", "Yearly seasonality.", "đơn vị", "units", *_LY_MISSING),
    "ly_mean_7": ("SAME_PERIOD_LAST_YEAR", 7, "Trung bình 7 ngày cùng kỳ năm trước", "Same-period-last-year 7-day mean",
                  "Tổng số lượng của các ngày (mốc − 367) … (mốc − 361) ÷ 7.",
                  "Sum of the quantities of the days (origin − 367) … (origin − 361) ÷ 7.",
                  "Mức bán quanh cùng ngày năm trước.", "Level around the same day last year.", "đơn vị/ngày", "units/day",
                  *_LY_MISSING),
    "ly_mean_28": ("SAME_PERIOD_LAST_YEAR", 28, "Trung bình 28 ngày cùng kỳ năm trước", "Same-period-last-year 28-day mean",
                   "Tổng số lượng của các ngày (mốc − 391) … (mốc − 364) ÷ 28.",
                   "Sum of the quantities of the days (origin − 391) … (origin − 364) ÷ 28.",
                   "Mức bán của 4 tuần cùng kỳ năm trước.", "Level of the same 4 weeks last year.", "đơn vị/ngày",
                   "units/day", *_LY_MISSING),
    "ly_trend": ("SAME_PERIOD_LAST_YEAR", 56, "Xu hướng cùng kỳ năm trước", "Same-period-last-year trend",
                 "ly_mean_28 ÷ trung bình 28 ngày (mốc − 419) … (mốc − 392); mẫu số = 0 → 1.",
                 "ly_mean_28 ÷ the mean of the 28 days (origin − 419) … (origin − 392); denominator 0 → 1.",
                 "Năm trước nhu cầu đang tăng hay giảm vào thời điểm này.",
                 "Whether demand was rising or falling at this time last year.", "tỷ lệ", "ratio", *_LY_MISSING),
    "deal_active": ("DEAL", 1, "Đang có deal tại mốc dự báo", "Deal running at the forecast origin",
                    f"1 nếu SKU × kho có ít nhất một {_RUNNING[0]}, ngược lại 0.",
                    f"1 if the SKU × FC has at least one {_RUNNING[1]}, else 0.",
                    "Deal làm tăng nhu cầu trong thời gian chạy.", "A deal lifts demand while it runs.", "0/1", "0/1",
                    "Không có deal → 0.", "No deal → 0."),
    "deal_days_since_start": ("DEAL", 1, "Số ngày từ khi deal bắt đầu", "Days since the deal started",
                              f"Mốc − ngày bắt đầu (ngày của ready_time), nhỏ nhất trong các deal đang chạy ({_RUNNING[0]}).",
                              f"Origin − start day (day of ready_time), the smallest over the running deals ({_RUNNING[1]}).",
                              "Deal mới bắt đầu hay đã chạy lâu.", "Whether the deal is new or has run for long.", "ngày",
                              "days", *_NO_DEAL),
    "deal_days_to_end": ("DEAL", 1, "Số ngày đến khi deal kết thúc", "Days until the deal ends",
                         "Ngày kết thúc (ngày của end_time) − mốc, lớn nhất trong các deal đang chạy.",
                         "End day (day of end_time) − origin, the largest over the running deals.",
                         "Deal còn chạy bao lâu.", "How long the deal still runs.", "ngày", "days", *_NO_DEAL),
    "deal_max_qty": ("DEAL", 1, "Hạn mức của deal đang chạy", "Quantity cap of the running deals",
                     "Σ max_quantity của các deal đang chạy (hạn mức trống tính 0).",
                     "Σ max_quantity of the running deals (an empty cap counts 0).",
                     "Quy mô deal.", "Size of the deal.", "đơn vị", "units", *_NO_DEAL),
    "deal_used_to_date": ("DEAL", 1, "Lượng deal đã dùng đến hôm trước", "Deal quantity used up to the day before",
                          "Σ số lượng các dòng đơn mang mã của các deal đang chạy, từ ngày đầu lịch sử đến ngày trước mốc.",
                          "Σ quantities of the order lines carrying the code of a running deal, from the first history day to the day before the origin.",
                          "Deal đã được dùng bao nhiêu.", "How much of the deal was used.", "đơn vị", "units", *_NO_DEAL_0),
    "deal_remaining_ratio": ("DEAL", 1, "Tỷ lệ hạn mức deal còn lại", "Remaining share of the deal cap",
                             "1 − deal_used_to_date ÷ deal_max_qty (không chặn ở 0); hạn mức = 0 → thiếu.",
                             "1 − deal_used_to_date ÷ deal_max_qty (not clipped at 0); cap 0 → missing.",
                             "Deal sắp hết hạn mức thì bán chậm lại.", "A deal close to its cap slows down.", "tỷ lệ",
                             "ratio", *_NO_DEAL),
    "deal_used_1": ("DEAL", 1, "Lượng deal dùng hôm trước", "Deal quantity used the day before",
                    "Σ số lượng các dòng đơn của ngày trước mốc mang mã của các deal đang chạy.",
                    "Σ quantities of the order lines of the day before the origin carrying the code of a running deal.",
                    "Tốc độ dùng deal gần nhất.", "Latest deal usage pace.", "đơn vị", "units", *_NO_DEAL_0),
    "deal_used_7": ("DEAL", 7, "Lượng deal dùng 7 ngày trước", "Deal quantity used in the previous 7 days",
                    "Σ số lượng các dòng đơn của 7 ngày trước mốc mang mã của các deal đang chạy.",
                    "Σ quantities of the order lines of the 7 days before the origin carrying the code of a running deal.",
                    "Tốc độ dùng deal trong tuần.", "Weekly deal usage pace.", "đơn vị", "units", *_NO_DEAL_0),
    "n_active_deals": ("DEAL", 1, "Số deal đang chạy", "Number of running deals",
                       "Số deal đang chạy của SKU × kho tại mốc.", "Number of running deals of the SKU × FC at the origin.",
                       "Nhiều deal cùng lúc.", "Overlapping deals.", "deal", "deals", "Không có deal → 0.", "No deal → 0."),
    "sku_deal_uplift_hist": ("DEAL", None, "Mức tăng bán khi có deal (lịch sử SKU × kho)",
                             "Deal uplift (history of the SKU × FC)",
                             "Trung bình, trên các deal của SKU × kho đã kết thúc trước mốc, của (bán trong các ngày deal ÷ số ngày) ÷ trung bình 28 ngày trước deal; deal có nền 0 không tính.",
                             "Mean, over the deals of the SKU × FC finished before the origin, of (sales in the deal days ÷ days) ÷ the mean of the 28 days before the deal; a deal with base 0 is left out.",
                             "Deal trước đây làm tăng bán bao nhiêu lần.", "How much past deals lifted sales.", "lần",
                             "times", "Chưa có deal đã kết thúc có nền > 0 → thiếu (NaN).",
                             "No finished deal with a base > 0 → missing (NaN)."),
    "sku_deal_usage_hist": ("DEAL", None, "Tỷ lệ dùng hạn mức deal (lịch sử)", "Deal cap usage (history)",
                            "Trung bình quantity_used ÷ max_quantity của các deal của SKU × kho đã kết thúc trước mốc (max_quantity > 0).",
                            "Mean quantity_used ÷ max_quantity of the deals of the SKU × FC finished before the origin (max_quantity > 0).",
                            "Deal trước đây có dùng hết hạn mức không.", "Whether past deals used their cap.", "tỷ lệ",
                            "ratio", "Không có deal đã kết thúc có hạn mức > 0 → thiếu (NaN).",
                            "No finished deal with a cap > 0 → missing (NaN)."),
    "grp_deal_uplift_hist": ("DEAL", None, "Mức tăng bán khi có deal của nhóm A/B/C", "Deal uplift of the A/B/C group",
                             "Khi SKU × kho chưa có sku_deal_uplift_hist: trung bình uplift của mọi deal đã kết thúc trước mốc của các SKU × kho cùng nhóm A/B/C (quy tắc B7 tại ngày 1 của tháng của mốc, trên 90 ngày trước đó; ngày mở bán = giờ mở bán > 0).",
                             "When the SKU × FC has no sku_deal_uplift_hist: mean uplift of every deal finished before the origin of the SKU × FC of the same A/B/C group (B7 rule at the first day of the origin's month over the 90 days before; open day = open hours > 0).",
                             "Hiệu quả deal của các mặt hàng tương tự.", "Deal effect of similar items.", "lần", "times",
                             "Đã có uplift riêng, không có nhóm hoặc nhóm chưa có deal → thiếu (NaN).",
                             "Own uplift present, no group, or no deal in the group → missing (NaN)."),
}


ROLES = {   # expected role of each feature group (business wording)
    "IDENTITY": ("Nhận diện SKU, kho và độ 'già' của chuỗi.", "Identify the SKU, the FC and the series' maturity."),
    "LAG": ("Mức bán ở những ngày cụ thể trước ngày dự báo.", "Sales on specific days before the target day."),
    "ROLLING": ("Mức bán bình quân, độ dao động, tần suất bán gần đây.", "Recent average, variability and frequency of sales."),
    "CALENDAR": ("Mùa vụ theo ngày/tuần/tháng của ngày dự báo.", "Day/week/month seasonality of the target day."),
    "PRICE": ("Ảnh hưởng của giá và giảm giá đã biết.", "Effect of known price and discount."),
    "PROMOTION": ("Ảnh hưởng của khuyến mãi đã biết.", "Effect of known promotions."),
    "AVAILABILITY": ("Ảnh hưởng của số giờ SKU mở bán đã biết.", "Effect of the known hours the SKU was open for sale."),
    "CUSTOMER": ("Hành vi mua lại đã biết của tập khách (chỉ số tổng hợp, không theo từng khách).",
                 "Known repeat behaviour of the customer base (aggregates, never per customer)."),
    # 1.3.2
    "SAME_PERIOD_LAST_YEAR": ("Mức bán cùng kỳ năm trước (mùa vụ theo năm), từ lịch sử mở rộng.",
                              "Sales of the same period last year (yearly seasonality), from the extended history."),
    "DEAL": ("Deal đang chạy và hiệu quả của deal trong lịch sử, đã biết tại mốc dự báo.",
             "Running deals and the deal history known at the forecast origin."),
    "OTHER": ("", ""),
}


def catalogue(names: list[str]) -> list[dict]:
    return [describe(n) for n in names]


def all_lags_and_windows() -> dict:
    return {"lags": LAGS, "roll_windows": ROLL_WINDOWS, "last_sale_window": LAST_SALE_WINDOW}
