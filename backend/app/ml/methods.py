"""Central registry of every forecast method code that exists in ml/model.py (single source for UI tooltips,
Excel exports and the Algorithm page). `scope` says where a code can appear:
  production -> can be published in forecast_values
  backtest   -> only inside walk-forward backtest evaluation (never published)
"""
from __future__ import annotations

import logging

from . import model

log = logging.getLogger("df.methods")

METHODS: dict[str, dict] = {
    model.METHOD_LGBM: {
        "scope": "production", "anchor": "method-lightgbm",
        "vi": {"name": "Mô hình học máy (LightGBM)", "short": "Mô hình học máy (tổ hợp nhiều cây quyết định) dự báo từng ngày.",
               "meaning": "Dùng cho chuỗi SKU × FC có đủ lịch sử, không gián đoạn và còn bán.",
               "when": "Không rơi vào quy tắc dự phòng nào: tuổi chuỗi ≥ ngưỡng lịch sử tối thiểu, tỷ lệ ngày = 0 trong 56 ngày < ngưỡng gián đoạn, có đơn trong số ngày ngừng bán gần nhất.",
               "how": "Dự báo đệ quy: ngày 1 dùng lịch sử thực; từ ngày 2 các lag/rolling dùng cả giá trị đã dự báo của những ngày trước. Kết quả là tổng điểm của nhiều cây, rồi qua hàm liên kết của objective (Tweedie/Poisson: exp), cắt về ≥ 0.",
               "limits": "Không phải công thức tuyến tính; sai số có thể tích lũy với khoảng dài; không biết khuyến mãi tương lai."},
        "en": {"name": "Machine-learning model (LightGBM)", "short": "Machine-learning model (ensemble of decision trees), forecasting day by day.",
               "meaning": "Used for SKU × FC series with enough, non-intermittent, still-active history.",
               "when": "None of the fallback rules apply: series age ≥ minimum history, zero-day share over 56 days < intermittent threshold, orders within the inactive window.",
               "how": "Recursive: day 1 uses actual history; from day 2 lags/rolling stats also use earlier forecast values. Output = sum of many trees passed through the objective's link (Tweedie/Poisson: exp), clipped at ≥ 0.",
               "limits": "Not a linear formula; error can accumulate over long periods; future promotions are unknown."},
    },
    model.FB_NEW: {
        "scope": "production", "anchor": "method-fallback-new-series",
        "vi": {"name": "Dự phòng cho chuỗi SKU–FC mới", "short": "Trung bình nhu cầu mỗi ngày kể từ khi chuỗi bắt đầu có đơn.",
               "meaning": "Chuỗi quá mới, chưa đủ lịch sử để LightGBM học các lag/rolling.",
               "when": "Tuổi chuỗi (số ngày từ đơn đầu tiên đến mốc dự báo) < 'lịch sử tối thiểu của 1 tổ hợp' (mặc định 28 ngày).",
               "how": "Giá trị mỗi ngày = tổng số lượng các ngày đã biết kể từ đơn đầu tiên ÷ số ngày đã biết (ngày không có dữ liệu toàn hệ thống không được đếm). Mọi ngày trong kỳ dự báo nhận cùng giá trị.",
               "limits": "Không có xu hướng hay mùa vụ theo tuần; nhạy với vài ngày đầu bán."},
        "en": {"name": "Fallback for a new SKU–FC series", "short": "Average daily demand since the series' first order.",
               "meaning": "The series is too new for LightGBM's lag/rolling features.",
               "when": "Series age (days from first order to the forecast origin) < 'minimum series history' (default 28 days).",
               "how": "Daily value = sum of quantities on known days since the first order ÷ number of known days (calendar days with no data at all are not counted). Every forecast day gets the same value.",
               "limits": "No trend or weekly seasonality; sensitive to the first few days."},
    },
    model.FB_INTERMITTENT: {
        "scope": "production", "anchor": "method-fallback-intermittent",
        "vi": {"name": "Dự phòng cho nhu cầu gián đoạn", "short": "Trung bình nhu cầu mỗi ngày trong 28 ngày gần nhất.",
               "meaning": "Phần lớn các ngày không có đơn; mô hình theo ngày khó học tín hiệu ổn định.",
               "when": "Tỷ lệ ngày = 0 trong 56 ngày gần nhất (2 × cửa sổ dự phòng) ≥ ngưỡng gián đoạn (mặc định 80%).",
               "how": "Giá trị mỗi ngày = tổng số lượng 28 ngày gần nhất (cửa sổ dự phòng) ÷ số ngày đã biết trong cửa sổ.",
               "limits": "Dự báo một mức trung bình phẳng; không đoán ngày nào sẽ có đơn."},
        "en": {"name": "Fallback for intermittent demand", "short": "Average daily demand over the last 28 days.",
               "meaning": "Most days have no orders; a daily model cannot learn a stable signal.",
               "when": "Zero-day share over the last 56 days (2 × fallback window) ≥ intermittent threshold (default 80%).",
               "how": "Daily value = sum of the last 28 days (fallback window) ÷ number of known days in that window.",
               "limits": "A flat average; it does not predict which days will have orders."},
    },
    model.FB_INACTIVE: {
        "scope": "production", "anchor": "method-fallback-inactive",
        "vi": {"name": "Dự phòng: ngừng bán → 0", "short": "Không có đơn trong thời gian dài nên dự báo 0.",
               "meaning": "SKU tại FC này có vẻ đã ngừng bán.",
               "when": "Không có đơn nào trong 'số ngày ngừng bán' gần nhất (mặc định 60) và chuỗi đã tồn tại ít nhất ngần ấy ngày.",
               "how": "Mọi ngày dự báo = 0.",
               "limits": "Nếu SKU bán trở lại, dự báo vẫn là 0 cho tới lần huấn luyện sau."},
        "en": {"name": "Fallback: inactive → 0", "short": "No orders for a long time, so the forecast is 0.",
               "meaning": "The SKU at this FC appears to be discontinued.",
               "when": "No order in the last 'inactive days' (default 60) and the series is at least that old.",
               "how": "Every forecast day = 0.",
               "limits": "If the SKU sells again, the forecast stays 0 until the next training."},
    },
    model.FB_MODEL_UNAVAILABLE: {
        "scope": "backtest", "anchor": "method-fallback-model-unavailable",
        "vi": {"name": "Dự phòng khi không có mô hình (chỉ trong backtest)", "short": "Trung bình 28 ngày khi một fold backtest không huấn luyện được mô hình.",
               "meaning": "Chỉ xuất hiện trong đánh giá backtest; forecast đã publish không bao giờ dùng phương pháp này (không có mô hình thì không qua quality gate).",
               "when": "Một fold backtest có quá ít dữ liệu để huấn luyện LightGBM.",
               "how": "Giá trị = tổng 28 ngày gần nhất ÷ số ngày đã biết.",
               "limits": "Chỉ dùng để chấm điểm fold đó."},
        "en": {"name": "Fallback when no model is available (backtest only)", "short": "28-day mean when a backtest fold could not train a model.",
               "meaning": "Only appears inside backtest evaluation; a published forecast never uses it (no model means the quality gate fails).",
               "when": "A backtest fold has too little data to train LightGBM.",
               "how": "Value = sum of the last 28 days ÷ number of known days.",
               "limits": "Only used to score that fold."},
    },
    model.METHOD_BASELINE: {
        "scope": "production", "anchor": "method-baseline-moving-average",
        "vi": {"name": "Trung bình 28 ngày (baseline được chọn)", "short": "Trung bình nhu cầu mỗi ngày trong 28 ngày gần nhất, cho mọi chuỗi.",
               "meaning": "Phương án so sánh (baseline) của backtest. Chỉ được publish khi nó có WAPE thấp hơn LightGBM trên CÙNG các điểm backtest của lần huấn luyện đó (chọn ứng viên tốt nhất).",
               "when": "Lần huấn luyện đánh giá cả hai ứng viên trên cùng các fold walk-forward; baseline có WAPE gộp thấp hơn (hoặc LightGBM không huấn luyện được).",
               "how": "Giá trị mỗi ngày = tổng số lượng 28 ngày gần nhất ÷ số ngày đã biết trong 28 ngày đó (ngày không có dữ liệu toàn hệ thống không được đếm); mọi ngày dự báo cùng một giá trị, cắt về ≥ 0.",
               "limits": "Một mức trung bình phẳng: không có xu hướng, mùa vụ theo tuần hay ảnh hưởng của giá."},
        "en": {"name": "28-day average (selected baseline)", "short": "Average daily demand over the last 28 days, for every series.",
               "meaning": "The backtest's comparison method (baseline). Published only when it has a lower WAPE than LightGBM on the SAME backtest points of that training (best candidate wins).",
               "when": "The training evaluated both candidates on the same walk-forward folds and the baseline had the lower pooled WAPE (or LightGBM could not be trained).",
               "how": "Daily value = sum of the last 28 days ÷ number of known days in those 28 days (calendar days with no data at all are not counted); every forecast day gets the same value, clipped at ≥ 0.",
               "limits": "A flat average: no trend, weekly seasonality or price effect."},
    },
}

# Worked examples ("example") and how to read the number ("read"). Every number is verified against the real code in
# backend/tests/test_v111.py::test_method_registry_examples_are_computed_by_the_code.
_EXAMPLES = {
    model.METHOD_LGBM: {
        "vi": {"example": "Minh họa hàm liên kết (không phải số của mô hình thật): gốc + tổng đóng góp = 1,45 → exp(1,45) ≈ 4,263 đơn vị/ngày. Số thật của từng dòng: nút 'Xem cách tính'.",
               "read": "Là mức nhu cầu kỳ vọng của ngày đó nên có thể là số lẻ (vd. 4,263), không phải số đơn chắc chắn. Cộng các ngày để có tổng kỳ."},
        "en": {"example": "Link-function illustration (not real model numbers): base + sum of contributions = 1.45 → exp(1.45) ≈ 4.263 units/day. Real numbers per row: 'How is this calculated?'.",
               "read": "It is the expected demand of that day, so it can be fractional (e.g. 4.263), not a guaranteed order count. Sum the days for the period total."},
    },
    model.FB_NEW: {
        "vi": {"example": "Chuỗi có đơn đầu tiên 10 ngày trước mốc dự báo; 10 ngày đã biết có tổng 56 → 56 ÷ 10 = 5,6/ngày; khoảng 7 ngày = 7 × 5,6 = 39,2.",
               "read": "Mọi ngày trong kỳ có cùng một giá trị; độ tin cậy thấp vì dựa trên ít ngày."},
        "en": {"example": "First order 10 days before the forecast origin; the 10 known days total 56 → 56 ÷ 10 = 5.6/day; a 7-day period = 7 × 5.6 = 39.2.",
               "read": "Every day of the period has the same value; low confidence because it rests on few days."},
    },
    model.FB_INTERMITTENT: {
        "vi": {"example": "56 ngày gần nhất có 53 ngày = 0 (94,6% ≥ 80%) → gián đoạn. 28 ngày gần nhất có tổng 3 trên 28 ngày đã biết → 3 ÷ 28 ≈ 0,1071/ngày; 7 ngày ≈ 0,75.",
               "read": "Đọc như tổng kỳ vọng của cả khoảng (vd. ~0,75 trong 7 ngày ≈ khoảng 1 đơn vị), không phải nhu cầu từng ngày."},
        "en": {"example": "53 of the last 56 days are 0 (94.6% ≥ 80%) → intermittent. The last 28 days total 3 over 28 known days → 3 ÷ 28 ≈ 0.1071/day; 7 days ≈ 0.75.",
               "read": "Read it as the expected total over the period (e.g. ~0.75 in 7 days ≈ about 1 unit), not as daily demand."},
    },
    model.FB_INACTIVE: {
        "vi": {"example": "Chuỗi tồn tại 120 ngày, lần bán cuối cách mốc dự báo 75 ngày (≥ 60 ngày không có đơn) → mọi ngày = 0.",
               "read": "0 nghĩa là hệ thống coi SKU tại FC này đã ngừng bán, không phải dự báo sai; kiểm tra lại nếu biết SKU sắp bán trở lại."},
        "en": {"example": "Series 120 days old, last sale 75 days before the origin (≥ 60 days without orders) → every day = 0.",
               "read": "0 means the SKU at this FC is treated as discontinued, not a model error; review it if you know the SKU will sell again."},
    },
    model.FB_MODEL_UNAVAILABLE: {
        "vi": {"example": "Fold backtest không huấn luyện được mô hình; 28 ngày cuối của dữ liệu fold có tổng 42 trên 28 ngày đã biết → 42 ÷ 28 = 1,5/ngày.",
               "read": "Chỉ thấy trong bảng chỉ số backtest theo phương pháp; không bao giờ có trong kết quả dự báo."},
        "en": {"example": "A backtest fold could not train a model; the fold's last 28 days total 42 over 28 known days → 42 ÷ 28 = 1.5/day.",
               "read": "Only visible in backtest metrics by method; never in forecast results."},
    },
    model.METHOD_BASELINE: {
        "vi": {"example": "28 ngày gần nhất có tổng 84 trên 28 ngày đã biết → 84 ÷ 28 = 3/ngày; khoảng 7 ngày = 7 × 3 = 21.",
               "read": "Mọi ngày trong kỳ có cùng một giá trị; được dùng vì trên dữ liệu backtest nó sai số ít hơn LightGBM."},
        "en": {"example": "The last 28 days total 84 over 28 known days → 84 ÷ 28 = 3/day; a 7-day period = 7 × 3 = 21.",
               "read": "Every day of the period has the same value; used because it had a smaller backtest error than LightGBM."},
    },
}
for _code, _ex in _EXAMPLES.items():
    for _lang in ("vi", "en"):
        METHODS[_code][_lang].update(_ex[_lang])

REASONS = {
    "LIGHTGBM_ELIGIBLE": ("Không rơi vào quy tắc dự phòng nào → dùng LightGBM.", "No fallback rule applies → LightGBM is used."),
    "NEW_SERIES": ("Chuỗi mới: tuổi chuỗi nhỏ hơn ngưỡng lịch sử tối thiểu.", "New series: age is below the minimum series history."),
    "INTERMITTENT": ("Nhu cầu gián đoạn: tỷ lệ ngày bằng 0 vượt ngưỡng.", "Intermittent demand: zero-day share at or above the threshold."),
    "INACTIVE": ("Ngừng bán: không có đơn trong cửa sổ ngừng bán.", "Inactive: no order within the inactive window."),
    "BASELINE_SELECTED": ("Baseline 28 ngày được chọn: WAPE thấp hơn LightGBM trên cùng các điểm backtest.",
                          "28-day baseline selected: lower WAPE than LightGBM on the same backtest points."),
}


UNKNOWN_LABEL = {"vi": "Phương pháp chưa có mô tả ({code})", "en": "Undocumented method ({code})"}


def label(code: str | None, lang: str = "vi") -> str:
    """Business name of a method code in the given language. The code itself is never changed. An unknown code
    (should not happen: every code in ml/model.py is registered, see tests) gets a visible, safe fallback label and
    a warning in the log instead of failing the export or showing a bare internal code."""
    if not code:
        return ""
    lang = lang if lang in ("vi", "en") else "vi"
    m = METHODS.get(code)
    if m is None:
        log.warning("method code without label", extra={"ctx": {"code": code}})
        return UNKNOWN_LABEL[lang].format(code=code)
    return m[lang]["name"]


def registry() -> dict:
    return {"methods": {k: {"code": k, **v} for k, v in METHODS.items()},
            "reasons": {k: {"vi": v[0], "en": v[1]} for k, v in REASONS.items()}}
