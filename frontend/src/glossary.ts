// Plain-language glossary. Definitions match the backend implementation (backend/app/ml/metrics.py).

export interface Term {
  id: string;
  vi: { name: string; meaning: string; purpose: string; example: string; read?: string };
  en: { name: string; meaning: string; purpose: string; example: string; read?: string };
}

export const GLOSSARY: Term[] = [
  {
    id: "wape",
    vi: {
      name: "WAPE — Sai số tuyệt đối có trọng số",
      meaning: "Tổng |thực tế − dự báo| chia cho tổng thực tế. Công thức: Σ|A−F| / ΣA.",
      purpose: "Đo mức sai lệch chung của toàn bộ dự báo, không bị méo bởi các ngày có số lượng rất nhỏ.",
      example: "Thực tế 100 + 50 = 150; dự báo 90 + 60 → sai số 10 + 10 = 20 → WAPE = 20/150 = 13,3%.",
      read: "Càng thấp càng tốt. 0% là hoàn hảo. Không tính được khi tổng thực tế = 0 (hiển thị “Chưa có”).",
    },
    en: {
      name: "WAPE — Weighted Absolute Percentage Error",
      meaning: "Sum of |actual − forecast| divided by the sum of actuals: Σ|A−F| / ΣA.",
      purpose: "Measures overall error without being distorted by days with tiny quantities.",
      example: "Actual 100 + 50 = 150; forecast 90 + 60 → error 10 + 10 = 20 → WAPE = 20/150 = 13.3%.",
      read: "Lower is better; 0% is perfect. Undefined when total actual is 0 (shown as “Not available”).",
    },
  },
  {
    id: "mae",
    vi: {
      name: "MAE — Sai số tuyệt đối trung bình",
      meaning: "Trung bình của |thực tế − dự báo| trên mỗi điểm (SKU × FC × ngày).",
      purpose: "Cho biết trung bình mỗi ngày dự báo lệch bao nhiêu đơn vị sản phẩm.",
      example: "Sai số 2, 0, 4 → MAE = (2+0+4)/3 = 2 đơn vị.",
      read: "Càng thấp càng tốt. Đơn vị là số lượng sản phẩm, không phải %.",
    },
    en: {
      name: "MAE — Mean Absolute Error",
      meaning: "Average of |actual − forecast| per point (SKU × FC × day).",
      purpose: "Tells how many units the forecast is off per day on average.",
      example: "Errors 2, 0, 4 → MAE = (2+0+4)/3 = 2 units.",
      read: "Lower is better. Measured in units, not %.",
    },
  },
  {
    id: "bias",
    vi: {
      name: "Forecast bias — Độ lệch dự báo",
      meaning: "(Tổng dự báo − tổng thực tế) / tổng thực tế.",
      purpose: "Cho biết mô hình có xu hướng dự báo dư hay thiếu.",
      example: "Dự báo tổng 110, thực tế 100 → bias = +10% (dự báo dư).",
      read: "Gần 0 là tốt nhất. Dương = dự báo dư; âm = dự báo thiếu.",
    },
    en: {
      name: "Forecast bias",
      meaning: "(Total forecast − total actual) / total actual.",
      purpose: "Shows whether the model tends to over- or under-forecast.",
      example: "Forecast total 110, actual 100 → bias = +10% (over-forecast).",
      read: "Closest to 0 is best. Positive = over-forecast; negative = under-forecast.",
    },
  },
  {
    id: "mape",
    vi: {
      name: "MAPE — Sai số phần trăm tuyệt đối trung bình",
      meaning: "Trung bình |thực tế − dự báo| / thực tế, CHỈ tính trên các điểm có thực tế ≥ ngưỡng cấu hình (mặc định 1).",
      purpose: "Sai số tương đối từng điểm. Các ngày thực tế = 0 bị loại vì phép chia cho 0 không có nghĩa; số điểm bị loại luôn được hiển thị.",
      example: "Thực tế 10, dự báo 8 → 20%; thực tế 0 → không tính.",
      read: "Càng thấp càng tốt. Không tin cậy khi nhiều ngày có số lượng nhỏ — ưu tiên WAPE.",
    },
    en: {
      name: "MAPE — Mean Absolute Percentage Error",
      meaning: "Mean of |actual − forecast| / actual, ONLY over points with actual ≥ the configured minimum (default 1).",
      purpose: "Per-point relative error. Days with actual = 0 are excluded (division by zero); the excluded count is always shown.",
      example: "Actual 10, forecast 8 → 20%; actual 0 → excluded.",
      read: "Lower is better. Unreliable with many small quantities — prefer WAPE.",
    },
  },
  {
    id: "backtesting",
    vi: {
      name: "Backtesting (walk-forward)",
      meaning: "Giả lập quá khứ: cắt dữ liệu tại một ngày, huấn luyện chỉ với dữ liệu trước ngày đó, dự báo các ngày sau rồi so với thực tế. Lặp lại ở nhiều mốc.",
      purpose: "Đánh giá mô hình trung thực, giống như khi dùng thật, không “nhìn trước” tương lai.",
      example: "Fold 1: học đến 30/06, dự báo 01–14/07; Fold 2: học đến 07/07, dự báo 08–21/07.",
      read: "Kết quả gộp các fold được dùng để kiểm tra ngưỡng chất lượng.",
    },
    en: {
      name: "Backtesting (walk-forward)",
      meaning: "Simulate the past: cut the data at a date, train only on earlier data, forecast the following days and compare with actuals. Repeat at several dates.",
      purpose: "Honest evaluation that mirrors real use, without seeing the future.",
      example: "Fold 1: train to 30 Jun, forecast 1–14 Jul; Fold 2: train to 7 Jul, forecast 8–21 Jul.",
      read: "Pooled fold results are used by the quality gate.",
    },
  },
  {
    id: "model_version",
    vi: {
      name: "Model version — Phiên bản mô hình",
      meaning: "Mã duy nhất của một mô hình đã được huấn luyện và chấp nhận (ví dụ MV-20261014-070012-AB12).",
      purpose: "Truy xuất chính xác mô hình nào đã tạo ra một kết quả dự báo.",
      example: "Forecast run FCR-… ghi model version MV-… và file mô hình tương ứng được lưu lại.",
    },
    en: {
      name: "Model version",
      meaning: "Unique ID of a trained and accepted model (e.g. MV-20261014-070012-AB12).",
      purpose: "Trace exactly which model produced a forecast.",
      example: "Forecast run FCR-… records model version MV-… and the model file is kept.",
    },
  },
  {
    id: "snapshot",
    vi: {
      name: "Snapshot D0",
      meaning: "Bản chụp số lượng đặt hàng lũy kế trong ngày hiện tại (D0) tại một thời điểm, được lưu tự động sau mỗi lần đồng bộ thành công.",
      purpose: "Theo dõi đơn hàng trong ngày. Số lũy kế lúc 10:00 KHÔNG phải số cả ngày.",
      example: "Snapshot 10:00: SKU A tại FC-HCM đã đặt 35 → dự báo cả ngày 120 là cho đến hết ngày.",
    },
    en: {
      name: "D0 snapshot",
      meaning: "A capture of today's (D0) cumulative ordered quantity at a point in time, saved automatically after each successful sync.",
      purpose: "Track intraday orders. The 10:00 cumulative is NOT a full-day number.",
      example: "10:00 snapshot: SKU A at FC-HCM has 35 ordered → the full-day forecast of 120 covers the whole day.",
    },
  },
  {
    id: "freshness",
    vi: {
      name: "Data freshness — Độ mới của dữ liệu",
      meaning: "Khoảng cách giữa hôm nay và ngày dữ liệu mới nhất đã đồng bộ thành công.",
      purpose: "Tránh dự báo trên dữ liệu cũ mà không biết. Với BigQuery, dữ liệu quá cũ sẽ chặn publish.",
      example: "Hôm nay 14/10, dữ liệu đến 13/10 → trễ 1 ngày (bình thường cho D-1).",
    },
    en: {
      name: "Data freshness",
      meaning: "Gap between today and the latest successfully synced data date.",
      purpose: "Avoid forecasting on stale data unknowingly. For BigQuery, stale data blocks publishing.",
      example: "Today 14 Oct, data up to 13 Oct → 1 day lag (normal for D-1).",
    },
  },
  {
    id: "leakage",
    vi: {
      name: "Data leakage — Rò rỉ dữ liệu",
      meaning: "Khi mô hình vô tình dùng thông tin chưa thể biết tại thời điểm dự báo (ví dụ số liệu tương lai).",
      purpose: "Ngăn rò rỉ để kết quả backtest không đẹp giả tạo. Mọi feature chỉ dùng dữ liệu trước ngày cần dự báo.",
      example: "Không dùng khuyến mãi ngày mai khi chưa có lịch khuyến mãi; giá tương lai được giữ bằng giá đã biết gần nhất.",
    },
    en: {
      name: "Data leakage",
      meaning: "When a model accidentally uses information not knowable at forecast time (e.g. future figures).",
      purpose: "Prevented so backtests are not artificially good. Every feature uses only data before the forecast day.",
      example: "Tomorrow's promotion is not used without a promotion calendar; future price is held at the last known price.",
    },
  },
  {
    id: "retry",
    vi: {
      name: "Retry — Thử lại",
      meaning: "Tự động chạy lại job thất bại sau thời gian chờ tăng dần (exponential backoff).",
      purpose: "Vượt qua lỗi tạm thời (mạng, nguồn chậm) mà không cần thao tác tay.",
      example: "Lần 1 lỗi → chờ 1 phút; lần 2 lỗi → chờ 2 phút; hết số lần thử → báo lỗi và cảnh báo.",
    },
    en: {
      name: "Retry",
      meaning: "Automatically re-run a failed job after an increasing wait (exponential backoff).",
      purpose: "Recover from temporary errors (network, slow source) without manual action.",
      example: "Attempt 1 fails → wait 1 min; attempt 2 fails → wait 2 min; attempts exhausted → failed + alert.",
    },
  },
  {
    id: "idempotency",
    vi: {
      name: "Idempotency — Chạy lặp an toàn",
      meaning: "Mỗi job có một khóa duy nhất (ví dụ D0_SYNC:2026-10-14T10:00). Chạy lại cùng khóa không tạo kết quả trùng.",
      purpose: "Tránh chạy trùng job đã thành công sau khi khởi động lại.",
      example: "Mốc 10:00 đã thành công → lần kiểm tra lịch sau không chạy lại mốc đó.",
    },
    en: {
      name: "Idempotency",
      meaning: "Each job has a unique key (e.g. D0_SYNC:2026-10-14T10:00). Re-running the same key never duplicates results.",
      purpose: "Avoid re-running jobs that already succeeded after a restart.",
      example: "The 10:00 slot succeeded → later schedule checks do not run it again.",
    },
  },
  {
    id: "origin",
    vi: {
      name: "Forecast origin — Mốc dự báo",
      meaning: "Ngày đầu tiên được dự báo; là ngày ngay sau ngày dữ liệu đầy đủ cuối cùng.",
      purpose: "Xác định rõ dự báo dùng dữ liệu đến đâu và bắt đầu từ ngày nào.",
      example: "Dữ liệu đến 13/10 → origin = 14/10; khoảng 7 ngày = 14/10 đến 20/10.",
    },
    en: {
      name: "Forecast origin",
      meaning: "The first forecast day; the day right after the last complete data day.",
      purpose: "Makes clear which data the forecast used and where it starts.",
      example: "Data to 13 Oct → origin = 14 Oct; a 7-day period = 14–20 Oct.",
    },
  },
  {
    id: "features",
    vi: {
      name: "Feature engineering — Tạo đặc trưng",
      meaning: "Biến dữ liệu lịch sử thành các con số mô hình học được: nhu cầu các ngày trước (lag), trung bình trượt, thứ trong tuần, giá, khuyến mãi…",
      purpose: "Giúp LightGBM nhận ra xu hướng, mùa vụ theo tuần và tác động giá/khuyến mãi.",
      example: "lag_7 = số lượng đúng 7 ngày trước; roll_mean_28 = trung bình 28 ngày gần nhất.",
    },
    en: {
      name: "Feature engineering",
      meaning: "Turning history into numbers the model can learn from: previous days' demand (lags), rolling means, weekday, price, promotion…",
      purpose: "Helps LightGBM capture trend, weekly seasonality and price/promotion effects.",
      example: "lag_7 = quantity exactly 7 days ago; roll_mean_28 = mean of the last 28 days.",
    },
  },
  {
    id: "fallback",
    vi: {
      name: "Fallback — Phương pháp dự phòng",
      meaning: "Cách dự báo đơn giản dùng khi một tổ hợp SKU × FC không đủ điều kiện cho LightGBM (mới, gián đoạn, ngừng bán).",
      purpose: "Không ép LightGBM dự báo khi thiếu dữ liệu; phương pháp dùng luôn được ghi rõ trong kết quả.",
      example: "SKU mới 10 ngày → dự báo = trung bình 10 ngày đó; SKU 60 ngày không có đơn → 0.",
    },
    en: {
      name: "Fallback",
      meaning: "A simple method used when a SKU × FC series is not eligible for LightGBM (new, intermittent, inactive).",
      purpose: "LightGBM is not forced onto thin data; the method used is always shown in the results.",
      example: "New SKU with 10 days → forecast = mean of those days; no orders for 60 days → 0.",
    },
  },
  {
    id: "quality_gate",
    vi: {
      name: "Quality gate — Ngưỡng chất lượng",
      meaning: "Các điều kiện (WAPE, bias, số điểm backtest…) mô hình mới phải đạt trước khi forecast được publish.",
      purpose: "Không publish kết quả kém; khi không đạt, forecast hợp lệ trước đó được giữ nguyên.",
      example: "WAPE backtest 72% > ngưỡng 60% → không publish, ghi lý do.",
    },
    en: {
      name: "Quality gate",
      meaning: "Conditions (WAPE, bias, backtest points…) a new model must meet before its forecast is published.",
      purpose: "Poor results are not published; the previous valid forecast is kept.",
      example: "Backtest WAPE 72% > 60% threshold → not published, reason recorded.",
    },
  },
  {
    id: "d1_d0",
    vi: {
      name: "D-1 và D0",
      meaning: "D-1 = dữ liệu đầy đủ của ngày hôm qua (dùng để huấn luyện). D0 = dữ liệu đang phát sinh trong hôm nay (dùng cho snapshot).",
      purpose: "Phân biệt dữ liệu hoàn tất với dữ liệu trong ngày.",
      example: "08:00 ngày 14/10: D-1 = 13/10 (đầy đủ); D0 = đơn từ 00:00 đến 08:00 ngày 14/10.",
    },
    en: {
      name: "D-1 and D0",
      meaning: "D-1 = yesterday's complete data (used for training). D0 = today's data as it arrives (used for snapshots).",
      purpose: "Separates complete data from intraday data.",
      example: "08:00 on 14 Oct: D-1 = 13 Oct (complete); D0 = orders from 00:00 to 08:00 on 14 Oct.",
    },
  },
];

export const TERM_BY_ID: Record<string, Term> = Object.fromEntries(GLOSSARY.map((t) => [t.id, t]));
