# Mô hình dự báo và chỉ số chất lượng

## Đối tượng dự báo

Số lượng đặt hàng **theo ngày Việt Nam** cho mỗi tổ hợp **SKU × FC**. `order_qty` là số lượng khách đặt lúc tạo đơn,
**không trừ hủy**. Từ 1.1.7, **cửa sổ dữ liệu** dùng cho mô hình là các ngày đã đóng (giờ Việt Nam) từ `data_policy.window_start_date` (mặc định **01/01/2026**) đến **hôm qua**; hôm nay chỉ dùng cho D0, ngày tương lai không bao giờ dùng. Dữ liệu cũ hơn vẫn được lưu nguyên vẹn nhưng không đưa vào huấn luyện/backtest/forecast. Nếu dữ liệu không phủ hết cửa sổ, trang Chất lượng dữ liệu báo `SHORT_HISTORY` kèm số ngày thực tế.

## Dữ liệu → chuỗi thời gian

- Dòng đơn hàng được kiểm định rồi tổng hợp theo ngày × SKU × FC (số lượng, số đơn, giá bình quân có trọng số, tỷ lệ
  giảm giá, tỷ lệ khuyến mãi/voucher).
- Mỗi chuỗi bắt đầu từ ngày có đơn đầu tiên. Ngày không có đơn của chuỗi = 0. Ngày **không có đơn nào trên toàn bộ dữ
  liệu** được coi là *không rõ* (có thể thiếu dữ liệu), không phải 0 — loại khỏi mục tiêu huấn luyện.

## Feature (bật/tắt từng nhóm trong Cấu hình)

| Nhóm | Feature |
|---|---|
| Định danh | mã SKU, mã FC (categorical), tuổi chuỗi |
| Lag | nhu cầu 1–7, 14, 21, 28 ngày trước |
| Rolling | trung bình 7/14/28/56 ngày, độ lệch chuẩn 7/28, tỷ lệ ngày = 0 trong 28 ngày, số ngày từ lần bán gần nhất, max 28 ngày |
| Lịch | thứ, ngày trong tháng, tháng, tuần trong năm, cuối tuần, số ngày đến cuối tháng |
| Giá | giá gần nhất đã biết, giá so với trung bình 28 ngày, tỷ lệ giảm giá gần nhất |
| Khuyến mãi | tỷ lệ khuyến mãi hôm trước, trung bình 7 ngày |

**Chống rò rỉ (leakage)**: một hàm duy nhất (`features_at`) tính feature cho ngày *t* chỉ từ các cột < *t*; dùng chung
cho huấn luyện, backtest và dự báo. Test tự động xác nhận: thay đổi dữ liệu tương lai không làm thay đổi feature/forecast.
Tương lai không biết: giá giữ ở mức đã biết gần nhất; **không có lịch khuyến mãi tương lai → giả định không khuyến mãi**.
Không dùng tồn kho/hết hàng (chưa có nguồn).

### Feature registry và feature theo dữ liệu thật (từ 1.1.5)

`backend/app/ml/feature_registry.py` liệt kê mọi biến đầu vào. Trang **Quản lý feature** hiển thị danh sách này.

**Metadata mỗi biến:**
- mã;
- tên Việt/Anh;
- mô tả, kiểu;
- nguồn, cột nguồn;
- nhóm;
- trạng thái, lý do;
- bắt buộc;
- quy tắc thiếu dữ liệu;
- quy tắc tổng hợp;
- thời điểm biết được giá trị;
- hiệu lực;
- phiên bản registry.

**Gồm hai loại:**
- 33 feature mô hình hiện có (logic không đổi);
- 15 biến dự kiến:
  - giá lúc đặt, giá sau chiết khấu, tỷ lệ giảm giá;
  - deal, promotion, loại promotion, voucher;
  - trạng thái SKU, seller, giờ/ngày mở bán, số ngày từ ngày mở bán;
  - ngày lễ, chiến dịch, thuộc tính đơn.

**Trạng thái**, tính từ dữ liệu thật của nguồn đang chọn và không lưu như một sự thật về dữ liệu:

| Trạng thái | Ý nghĩa |
|---|---|
| Đang sử dụng (`ACTIVE`) | lần huấn luyện tiếp theo dùng feature này: công tắc bật **và** nguồn có dữ liệu |
| Có dữ liệu nhưng chưa kích hoạt (`DISABLED`) | công tắc tắt, hoặc nguồn có cột/dữ liệu nhưng chưa có quy tắc tổng hợp/thiếu dữ liệu được duyệt |
| Đang lên kế hoạch (`PLANNED`) | chỉ là kiến trúc: chưa có cột nguồn, quy tắc hay dữ liệu |
| Thiếu dữ liệu (`UNAVAILABLE`) | công tắc bật hoặc cột đã ánh xạ, nhưng nguồn không có (hoặc có quá ít) dữ liệu |

**Quy tắc:**
- **Không tự tạo giá trị cho biến chưa có dữ liệu.**
  - Nhóm giá (`price_last`, `price_rel_28`), chiết khấu (`disc_last`) và khuyến mãi (`promo_last`, `promo_mean_7`) chỉ vào mô hình khi ≥ `feature_min_coverage` (mặc định 50%) số dòng SKU×FC×ngày của nguồn có giá trị.
  - Nếu không đạt, nhóm bị **bỏ khỏi lần huấn luyện đó**; không điền 0 và không điền giả.
  - Ví dụ: nguồn BIGQUERY với ánh xạ gợi ý không có giá/khuyến mãi nên dùng 28 feature.
  - DEMO có đủ dữ liệu nên vẫn dùng đủ 33 feature như trước.
- Công tắc của người dùng trong Cấu hình **không bị đổi**. Lần huấn luyện lưu riêng công tắc *đã áp dụng* cùng lý do (`feature_decisions`).
- `disc_last` có công tắc riêng `feature_discount`. Cấu hình cũ không có công tắc này thì `disc_last` đi theo `feature_price`, đúng như trước 1.1.5.
- Biến dự kiến chỉ là metadata, không thêm cột nào vào mô hình. Muốn kích hoạt một biến thì phải:
  - có cột thật;
  - có quy tắc tổng hợp về SKU × FC × ngày;
  - có quy tắc thiếu dữ liệu riêng cho biến đó;
  - xác định được giá trị *tại thời điểm dự báo* (không dùng thông tin phát sinh sau);
  - thêm code tính feature và tăng `FEATURE_CODE_VERSION`.
- Không đưa mã định danh thuần (seller, product_id…) vào mô hình khi chưa đánh giá.

## Mô hình

LightGBM (mục tiêu mặc định **Tweedie**, phù hợp dữ liệu đếm nhiều số 0), một mô hình chung cho mọi chuỗi. Dự báo
**đệ quy** từng ngày tới khoảng dài nhất được bật; giá trị âm bị cắt về 0.

### Phương pháp dự phòng (luôn ghi rõ trong kết quả, cột *Phương pháp*)

Quy tắc xét **theo đúng thứ tự** (`backend/app/ml/model.py::classification_details`, nguồn duy nhất cho cả dự báo lẫn
phần giải thích). "Ngày đã biết" = không phải NaN (ngày trước khi chuỗi bắt đầu và ngày toàn hệ thống không có dữ liệu
không được đếm).

| # | Điều kiện (tại forecast origin) | Phương pháp | Giá trị mỗi ngày |
|---|---|---|---|
| 1 | Không có đơn trong `inactive_days` (60) ngày **và** chuỗi đã tồn tại ≥ 60 ngày | `FALLBACK_INACTIVE_ZERO` | 0 |
| 2 | Tuổi chuỗi < `min_series_history_days` (28) ngày | `FALLBACK_NEW_SERIES` | Σ số lượng từ khi bắt đầu ÷ số ngày đã biết |
| 3 | Tỷ lệ ngày = 0 trong 2 × `fallback_window_days` (56) ngày ≥ `intermittent_zero_share` (80%) | `FALLBACK_INTERMITTENT` | Σ số lượng 28 ngày gần nhất ÷ số ngày đã biết trong 28 ngày |
| 4 | Còn lại | `LIGHTGBM` | mô hình |

`FALLBACK_MODEL_UNAVAILABLE` **chỉ xuất hiện trong backtest** (fold không huấn luyện được mô hình), không bao giờ có
trong forecast đã publish. Tên hiển thị, mô tả và tooltip của mọi mã nằm ở một registry duy nhất
`backend/app/ml/methods.py` (API `GET /api/methods`); phương pháp dự phòng không bao giờ được gọi là LightGBM.

Toàn bộ dữ liệu ngắn hơn `min_total_history_days` (56) → **không huấn luyện** (`DATA_NOT_TRAINABLE`).

## Backtest walk-forward

Tối đa `backtest_folds` (12) fold; fold *k* có mốc `T − H − (F−1−k) × step` (H = 30, step = 30 ngày → các cửa sổ 30 ngày liền nhau, tối đa ~12 tháng). Fold có mốc với ít hơn `min_total_history_days` (56) ngày lịch sử bị bỏ, nên khoảng backtest là khoảng dài nhất mà cửa sổ dữ liệu cho phép (01/01–15/10/2026: 7 fold = 210 ngày); dưới 6 tháng thì ghi chú `BACKTEST_SPAN_BELOW_6_MONTHS`. Mỗi fold: huấn luyện chỉ
với dữ liệu trước mốc → dự báo H ngày → so với thực tế. Không shuffle. Kết quả gộp các fold dùng cho quality gate; so
sánh với baseline trung bình 28 ngày; tách theo phương pháp. Ít hơn 2 fold hợp lệ → *không đủ tin cậy* → không publish.
Lưu cấu hình và kết quả từng lần backtest.

## Chỉ số (định nghĩa giống hệt ở backend `backend/app/ml/metrics.py` và giao diện)

| Chỉ số | Công thức | Tốt khi | Trường hợp đặc biệt |
|---|---|---|---|
| WAPE | Σ\|A−F\| / ΣA | thấp | ΣA = 0 → không tính được (hiển thị “—”, ghi chú `SUM_ACTUAL_ZERO`) |
| MAE | trung bình \|A−F\| (đơn vị sản phẩm) | thấp | — |
| Bias | (ΣF − ΣA) / ΣA | gần 0 (dương = dư, âm = thiếu) | ΣA = 0 → không tính được |
| MAPE | trung bình \|A−F\|/A chỉ trên điểm A ≥ `mape_min_actual` (1) | thấp | luôn hiển thị số điểm được tính / tổng; không có điểm nào → không tính được |

## Quality gate

Mặc định (**ví dụ để kiểm thử, CHƯA được phê duyệt nghiệp vụ**): WAPE ≤ 60%, |bias| ≤ 20%, ≥ 200 điểm backtest,
backtest đủ tin cậy; tùy chọn bắt buộc tốt hơn baseline. Ô *Đã được nghiệp vụ phê duyệt* chỉ là ghi nhận; cảnh báo
luôn hiển thị cho tới khi được đánh dấu. Lịch sử thay đổi ngưỡng được lưu.

Không đạt → không publish, giữ model và forecast hợp lệ trước đó, ghi lý do. Model mới không bao giờ xóa model cũ.

## Phiên bản & truy vết

Mỗi lần được chấp nhận tạo **model version** `MV-YYYYMMDD-HHMMSS-xxxx`, lưu file mô hình (`models\<version>.txt`, kèm
sha256) và metadata (feature, mã hóa SKU/FC, khoảng dữ liệu huấn luyện, tham số, chỉ số, gate). Mỗi lần publish tạo
**forecast run** `FCR-…` **bất biến** (trigger SQLite chặn sửa/xóa) ghi: model version, nguồn, scope (lô/bảng), forecast
origin, data-as-of, khoảng dự báo, thời điểm chạy.

Từ 1.1.5, mỗi training run lưu thêm trong `training_runs.feature_config_json` (không cần migration):
- `feature_set_version`: `FS-<phiên bản code feature>-<hash danh sách feature>`, kèm `registry_version`;
- `settings_switches`: công tắc người dùng; `config`: công tắc đã áp dụng; `feature_decisions`: lý do và độ phủ dữ liệu;
- `lineage`:
  - nguồn, scope;
  - bảng BigQuery và mã ánh xạ, hoặc lô import và file;
  - khoảng ngày, số dòng;
  - thời điểm lấy dữ liệu, lần đồng bộ cuối, kết quả kiểm tra dữ liệu;
  - target mapping, grain.

Không lưu credential hay bản ghi thô. File `models\<version>.json` lưu cùng danh sách feature và `feature_set_version`.

Mô hình cũ, huấn luyện trước 1.1.5, vẫn được tái hiện và giải thích bằng đúng danh sách feature đã lưu. Phiên bản feature set của mô hình cũ được *tính lại* từ danh sách đó và ghi rõ như vậy.

## Công thức forecast LightGBM — từng bước (đã xác minh trong code)

`ml/model.py::forecast` gọi `booster.predict(X)`; `ml/explain.py` tái lập đúng dòng đó và phân rã bằng
`booster.predict(X, pred_contrib=True)` (TreeSHAP chính xác của LightGBM):

1. **Giá trị nền (base value)** = phần tử cuối của `pred_contrib` = Σ qua các cây của `Tree::ExpectedValue()` =
   Σ lá (`leaf_count` ÷ `internal_count` của gốc cây đó) × giá trị lá (thang log). Số dòng là số dòng huấn luyện LightGBM
   ghi trong file mô hình cho **chính cây đó** (bagging 90% ⇒ mỗi cây một mẫu con); lá của cây đầu tiên đã chứa điểm khởi
   đầu `boost_from_average`. Vì vậy giá trị nền **không** đúng bằng trung bình điểm thô trên toàn bộ dữ liệu huấn luyện.
2. **Đóng góp từng feature** = các phần tử còn lại của `pred_contrib` (dương = làm tăng, âm = làm giảm điểm thô).
3. **Tổng đóng góp** = Σ đóng góp (độ chính xác đầy đủ).
4. **Điểm thô (raw score)** = giá trị nền + tổng đóng góp.
5. **Hàm liên kết**: objective `tweedie`/`poisson` → đầu ra mô hình = `exp(điểm thô)`; `regression`/`regression_l1` → không
   biến đổi. Đầu ra này bằng đúng `booster.predict(X)` (có kiểm tra).
6. **Xử lý sau mô hình**: cắt ≥ 0; giá trị chưa làm tròn được dùng làm "lịch sử" cho ngày kế tiếp (đệ quy); khi publish
   làm tròn 4 chữ số thập phân.
7. **Forecast đã publish** = giá trị trong `forecast_values` (bảng dự báo, Excel) — phải khớp với giá trị tái lập, nếu
   không giao diện không hiển thị giải thích.

Giao diện hiển thị tối đa 2 chữ số thập phân (số khác 0 nhỏ hơn 0,01 hiện `<0,01` kèm dấu); mục "Chi tiết kỹ thuật"
hiện độ chính xác đầy đủ. Mức quan trọng toàn mô hình (gain) được ghi riêng, không phải đóng góp của một dòng.

### Trace TreeSHAP kiểm toán được (v1.1.4)

`backend/app/ml/treeshap_trace.py` là bản port từng dòng của LightGBM v4.7.0 (`src/io/tree.cpp`: `ExtendPath`,
`UnwindPath`, `UnwoundPathSum`, `TreeSHAP`, `ExpectedValue`; `include/LightGBM/tree.h`: `Decision`), đọc chính file mô hình
(sha256 đã kiểm) và ghi lại từng thành phần `w × (one_fraction − zero_fraction) × giá trị lá` cho mỗi cây, mỗi lá, mỗi
feature trên đường đi. `backend/app/ml/shap_audit.py` đối soát mọi lần xem: SHAP của engine vs `pred_contrib` (dung sai
1e-12), đường đi tới lá vs `pred_leaf`, giá trị nền, điểm thô (1e-9), exp(điểm thô) vs đầu ra LightGBM, giá trị publish.
Không đạt → `FAILED`; thiếu/khác file mô hình hoặc không tái lập được dòng feature → `NOT_REPRODUCIBLE` (không dùng mô
hình khác thay thế). API: `GET /api/forecast-runs/{id}/shap-trace` (+ `feature`, phân trang), `/shap-trace/tree`,
`/shap-trace.xlsx|csv`. Giao diện: nút *Vì sao?* ở từng feature trong *Xem cách tính* (cấp A/B/C).

Danh mục toàn bộ feature (công thức chính xác, khoảng ngày, xử lý thiếu/0, đơn vị, ý nghĩa): `backend/app/ml/feature_catalog.py`,
API `GET /api/features/catalog`, trang *Thuật toán & thuật ngữ → Danh mục feature*.

## WAPE, Bias, số điểm đánh giá, quality gate (đã xác minh trong code)

- Một **điểm đánh giá** = một cặp (thực tế, dự báo) của một SKU×FC×ngày trong một fold backtest; ngày thực tế không rõ
  bị loại, thực tế = 0 vẫn tính. Với cấu hình mặc định từ 1.1.7 (fold 30 ngày, bước 30) các fold không chồng ngày; nếu
  cấu hình bước nhỏ hơn số ngày mỗi fold thì một SKU×FC×ngày có thể được đếm nhiều lần (do các mô hình khác nhau dự báo).
- WAPE = Σ|A−F| ÷ ΣA; Bias = (ΣF − ΣA) ÷ ΣA (**dương = dự báo dư**); các tổng ΣA, ΣF được lưu cùng lần huấn luyện,
  Σ|A−F| = MAE × số điểm.
- Quality gate dùng chỉ số **gộp mọi phương pháp**, so sánh ở độ chính xác đầy đủ với ngưỡng trong cấu hình lúc huấn
  luyện. Ngưỡng chưa được phê duyệt → giao diện cảnh báo.
- `GET /api/training-runs/{id}/backtest-points.xlsx` tái lập backtest trong bộ nhớ (không ghi DB) với đúng cấu hình và
  dữ liệu của lần huấn luyện; chỉ trả file khi chỉ số tái lập khớp chỉ số đã lưu.

## Huấn luyện LightGBM (thực tế)

Một mô hình chung cho mọi SKU×FC (SKU, FC là feature danh mục); không có mô hình riêng theo nhóm hay theo khoảng dự báo.
Ma trận huấn luyện: mọi (chuỗi, ngày) có target đã biết, từ ngày thứ 7, sau ngày chuỗi bắt đầu, tối đa 4 triệu hàng.
`lgb.train` với số cây cố định (`num_boost_round`), **không có tập validation, không early stopping**; chất lượng đo
bằng backtest walk-forward. Thông tin thực tế của từng lần huấn luyện: `GET /api/model/training-explain`, trang
*Thuật toán & thuật ngữ → Mô hình được huấn luyện như thế nào?*.

## Định dạng hiển thị

Chỉ lớp hiển thị và file Excel thay đổi; API, database và mọi phép tính giữ nguyên độ chính xác.
- Số trong phần giải thích, bảng feature, kết quả & chất lượng: **tối đa 2 chữ số thập phân**, không có số 0 thừa
  (số khác 0 nhỏ hơn 0,01 hiện `<0,01` kèm dấu). Các nơi khác: số chữ số thập phân cần thiết, **không có số 0 thừa** (`7,2000` → `7,2`; `10,0000` → `10`); dấu thập phân
  theo ngôn ngữ (vi: `7,2`, `1.204` · en: `7.2`, `1,204`). Chỉ số phần trăm 1 chữ số thập phân (`13,3%`).
- Ngày: **`DD/MM/YYYY`** trên mọi trang, biểu đồ, bộ lọc, tooltip, thông báo lỗi và Excel; ngày giờ `DD/MM/YYYY HH:mm`
  theo giờ Việt Nam. Ô chọn ngày nhập và hiển thị `DD/MM/YYYY` (nút 📅 mở lịch của trình duyệt).
- Ngoại lệ có chủ đích: mã định danh kỹ thuật chứa ngày (vd. khóa idempotency `TRAIN_PUBLISH:2026-10-14`) và trường
  `*_utc` trong Excel giữ nguyên dạng chuẩn.

## Giải thích một con số dự báo ("Xem cách tính")

`GET /api/forecast-runs/{id}/explain?sku_id=&fc_id=&target_date=` (`backend/app/ml/explain.py`), mở từ nút *Xem cách
tính* ở trang Kết quả dự báo. Chỉ trả về dữ kiện kiểm chứng được:

1. **Định danh**: run, model version, nguồn/bộ dữ liệu, data-as-of, ngày và thứ tự ngày trong kỳ.
2. **Phương pháp & lý do**: đọc từ bảng `forecast_series_meta` (ghi lúc publish, từ v1.1.1). Run cũ hơn không có bảng
   này → tính lại bằng đúng dữ liệu + cấu hình của lần huấn luyện **nếu dấu vân tay dữ liệu không đổi** (ghi rõ
   "tính lại"); nếu đã đổi → báo không xác định được, không đoán.
3. **Lịch sử** đến data-as-of (không có dữ liệu tương lai), dạng bảng **Ngày | Demand | Trạng thái | Dùng trong phép
   tính**, theo thứ tự cũ → mới; độ dài = max(56, 2 × cửa sổ dự phòng, số ngày ngừng bán) để luôn chứa mọi ngày quy tắc
   đã xét. Phân biệt *có đơn / 0 đơn / không có dữ liệu (—) / trước khi chuỗi bắt đầu*; ô trống không bao giờ được coi
   là 0. Với dự phòng, các ngày được dùng có dấu ✓ và dòng tổng; backend tự đối chiếu tổng và số ngày của các dòng này
   với phép tính (`matches_history`).
4. **Dự phòng**: cửa sổ, tổng, số ngày đã biết và phép chia đúng như code; so khớp với giá trị đã publish.
5. **LightGBM**: tải lại file mô hình (kiểm tra sha256), tái tạo dự báo đệ quy cho chuỗi đó, chỉ hiển thị khi giá trị
   tái tạo **bằng** giá trị đã publish. Đóng góp từng feature là SHAP chính xác do LightGBM tính
   (`predict(pred_contrib=True)`, TreeSHAP) trong không gian điểm thô: `dự báo = exp(gốc + Σ đóng góp)` với
   Tweedie/Poisson, cắt ≥ 0. Mỗi feature có giá trị, nguồn (thực tế / dự báo của ngày trước / lịch / giữ giá trị
   cuối / giả định 0) và cờ "được cây sử dụng". Feature importance toàn cục chỉ để tham khảo.
6. **Kết quả & chất lượng**: giá trị, quality gate và backtest của chính phương pháp đó.

Dữ liệu đổi sau khi huấn luyện hoặc thiếu file mô hình → `DATA_CHANGED` / `MODEL_MISSING`, không hiển thị số ước đoán.

## Khoảng dự báo của một run so với cấu hình

Một forecast run chỉ chứa các khoảng được bật **tại thời điểm chạy** (lưu trong `horizons_json`). Bật thêm khoảng sau
đó không làm run cũ "có thêm" ngày: trang Kết quả chỉ cho chọn khoảng có trong run và hiển thị cảnh báo khoảng còn
thiếu (`horizon_coverage` trong `GET /api/forecast-runs/{id}`).

**Bổ sung không huấn luyện lại** (`POST /api/forecast-runs/{id}/extend`, job `FORECAST_EXTEND`) chỉ được phép khi:
mô hình của run còn file và sha256 khớp; dấu vân tay dữ liệu bằng lúc huấn luyện; kích thước nằm trong
`max_forecast_rows`; và dự báo tái tạo **khớp chính xác** mọi giá trị đã publish của run gốc. Kết quả là một run
**mới** (`derived_from_run_id` = run gốc) với cùng model version, data-as-of, forecast origin; run gốc không bị sửa.
Không đủ điều kiện → mã lý do (`DATA_CHANGED_SINCE_TRAINING`, `MODEL_ARTIFACT_MISSING`, `REPRODUCTION_MISMATCH`,
`FORECAST_TOO_LARGE`, `NOTHING_TO_EXTEND`) và cần huấn luyện mới.

## Thực tế trong ngày (actual so far today)

`backend/app/data/intraday.py`. Lấy từ snapshot D0 **thành công** gần nhất của **cùng bộ dữ liệu** (scope) với forecast
run, cho ngày VN hôm nay. Giá trị = số lượng lũy kế trong snapshot; thời điểm = `snapshot_at` (lúc đọc nguồn thật).

| Trạng thái | Khi nào |
|---|---|
| `PARTIAL_DAY` | Có snapshot hôm nay, lần đọc gần nhất còn mới |
| `STALE` | Lần đọc gần nhất cũ hơn (khoảng cách lớn nhất giữa các mốc D0 + `slot_grace_minutes`) — mặc định 120 + 20 = 140 phút |
| `NO_DATA_TODAY` | Chưa có snapshot hôm nay |
| `NOT_APPLICABLE` | Bộ dữ liệu MANUAL_IMPORT (không có nguồn trong ngày) |

SKU × FC không có trong snapshot thành công = 0 đơn đến lúc đọc; không có snapshot = trống (không phải 0). Chỉ ngày hôm
nay có giá trị, ngày tương lai luôn trống; tổng chỉ cộng các SKU × FC thuộc run và bộ lọc. DEMO luôn gắn nhãn DEMO.
Đây là số **một phần ngày** — không dùng để kết luận forecast sai.

## Xuất Excel

`GET /api/forecast-runs/{id}/export.xlsx?horizon=&lang=vi|en` (định dạng phiên bản `4`, `backend/app/export_i18n.py`).
Tên sheet, tiêu đề cột, tên phương pháp, trạng thái và thông tin run theo ngôn ngữ giao diện; mã định danh (run ID,
model version, SKU, FC) và giá trị số giữ nguyên.

- **Ngày luôn `DD/MM/YYYY`** ở cả tiếng Việt và tiếng Anh: cột ngày là ô ngày thật của Excel (định dạng `DD/MM/YYYY`,
  vẫn sắp xếp/lọc được); các ngày trong sheet thông tin cũng `DD/MM/YYYY`. Thời điểm (chạy, đọc thực tế) ghi theo
  **giờ Việt Nam** `DD/MM/YYYY HH:mm`, kèm bản UTC kỹ thuật.
- **Phương pháp:** cột *Phương pháp* / *Method* là tên dễ hiểu theo ngôn ngữ (vd. *Mô hình học máy (LightGBM)*,
  *Dự phòng cho chuỗi SKU–FC mới*), lấy từ registry duy nhất `backend/app/ml/methods.py`; cột cuối *Mã kỹ thuật
  phương pháp (không dịch)* giữ nguyên mã để đối chiếu. Mã không có trong registry (không thể xảy ra với mã hiện có —
  có test) hiển thị *Phương pháp chưa có mô tả (MÃ)* và được ghi cảnh báo vào log, không làm hỏng file.
- Cột thực tế hôm nay theo quy tắc ở mục trên.
- Export snapshot D0 (`/api/snapshots/{id}/export.xlsx?lang=`) và báo cáo lỗi import
  (`/api/imports/{id}/errors.xlsx?lang=`) theo cùng quy tắc ngôn ngữ và ngày. Trong báo cáo lỗi, giá trị gốc của cột
  ngày được hiển thị `DD/MM/YYYY` nếu đọc được; giá trị không đọc được (chính là lỗi) giữ nguyên như trong file.

## Giới hạn

- Không tự học từ sai số theo thời gian thực — chỉ huấn luyện lại theo lịch (hoặc khi bấm).
- Dự báo đệ quy: sai số có thể tích lũy với khoảng dài (90–365 ngày) — đọc như xu hướng.
- Không xử lý hết hàng (thiếu dữ liệu tồn kho); không có lịch khuyến mãi tương lai.
- Mô hình chưa được đánh giá trên dữ liệu thật của doanh nghiệp (chỉ Demo / file mẫu tổng hợp).

## Bảo vệ model đang dùng (1.1.7)

- **Model đang dùng** của một bộ dữ liệu = model của forecast run được publish gần nhất của bộ dữ liệu đó.
- Lần huấn luyện đầu tiên (chưa có model đang dùng) đạt quality gate → publish như trước (`INITIAL_MODEL`).
- Khi đã có model đang dùng, model mới đạt quality gate **không tự thay thế** (chưa có tiêu chí thay model được nghiệp vụ
  phê duyệt). Model mới được lưu (file + chỉ số) với trạng thái *Chờ duyệt thay model* (`PROMOTION_REVIEW_REQUIRED`)
  cùng kết quả so sánh; forecast đang publish không đổi.
- **So sánh trên cùng tập kiểm định:** cấu hình của model đang dùng (feature, tham số LightGBM, quy tắc dự phòng — lưu
  cùng lần huấn luyện của nó) được huấn luyện lại walk-forward trên **đúng các fold** của model mới, cùng dữ liệu
  SKU × FC × ngày, cùng target, cùng các điểm đánh giá. Kết luận theo WAPE gộp: `BETTER` / `WORSE` / `EQUAL`
  (chỉ khi bằng nhau về số học, sai khác ≤ 1e-9) / `INSUFFICIENT_DATA` (ít hơn `min_backtest_points` điểm, không
  có fold, hoặc không dựng lại được cấu hình cũ). Bias, MAE, MAPE được hiển thị cạnh nhau. Không áp ngưỡng nghiệp vụ.
- Người dùng xem so sánh ở trang *Hiệu năng model* và bấm **Dùng model này**: ứng dụng kiểm tra lại (dữ liệu chưa đổi,
  file model đúng hash, chưa có model mới hơn) rồi publish forecast từ model đó trong một transaction. Model cũ và mọi
  forecast cũ được giữ.
- Lịch huấn luyện tự động (07:00) vẫn huấn luyện khi có dữ liệu mới, nhưng chỉ tạo model chờ duyệt; khi dữ liệu không đổi
  so với model đang dùng hoặc model đang chờ duyệt thì bỏ qua (`NO_NEW_DATA`).
  Lưu ý (kiểm toán 16/10/2026): "dữ liệu không đổi" được so bằng dấu vân tay `COUNT, SUM(qty), MIN/MAX(order_date),
  MAX(loaded_at)` của cả phạm vi. Với BIGQUERY mỗi lần D-1 ghi lại cửa sổ (`loaded_at` mới) nên dấu vân tay luôn đổi:
  `NO_NEW_DATA` thực tế chỉ xảy ra với DEMO / Excel, và model chờ duyệt sẽ không duyệt được nữa
  (`DATA_CHANGED_SINCE_TRAINING`) sau lần D-1 kế tiếp.
