# Điều tra chất lượng mô hình

Đánh giá candidate 23/10, điều tra 30 câu hỏi và điều tra chất lượng học 26/10/2026.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\candidate-review-MV-20261023-132433-3B70-20261023.md` (MAIN) | 23/10/2026 | 16447 | `6DF53DA3091C083DD42242F3E91CCBF09CD17AC974810A2B2E8C3308CBFDE42A` |
| 2 | `reports\dieu-tra-30-cau-hoi-20261026\BAO_CAO_DIEU_TRA_30_CAU_HOI.md` (MAIN) | 26/10/2026 | 62676 | `B8045A41CE924144652666B17348A55ECE6D2F6473CA3C4DBC6FBCB709161C0D` |
| 3 | `reports\model-learning-investigation-20261026\BAO_CAO_DIEU_TRA.md` (MAIN) | 26/10/2026 | 45138 | `CCABD822EFEBD1874BA7B1A8A456129ED06B16A6F31D30DFCA6A29CED4F22908` |

## 1. Đánh giá candidate `MV-20261023-132433-3B70`

Nguồn: `reports\candidate-review-MV-20261023-132433-3B70-20261023.md` (worktree MAIN).

Ngày đánh giá: 23/10/2026, giờ Việt Nam (UTC+7). Đây là đánh giá chỉ đọc: không huấn luyện, không chạy backtest mới, không promote, không đổi dữ liệu hay cấu hình.

### Kết luận: **HOLD**

Candidate tốt hơn model đang dùng rất ít trên toàn kỳ. Lợi thế đó không còn ở 4 tuần gần nhất, và candidate vẫn trượt ngưỡng WAPE như model đang dùng. Chưa có quy tắc promote được kinh doanh phê duyệt. Bằng chứng chưa đủ để khuyến nghị promote vì độ chính xác.

---

### 1. Tóm tắt

| Mục | Kết quả |
|---|---|
| Job | `JOB-20261023055649-4DB587`: TRAIN_PUBLISH, MANUAL, SUCCEEDED, 12:56:49 → 13:24:34 (27,8 phút) |
| Training run | `TRN-20261023055745-933B70`: trạng thái REJECTED + `PROMOTION_REVIEW_REQUIRED`, tức là candidate chờ duyệt. Chưa dùng, chưa có forecast |
| Artifact | `D:\Buymed\Lightgbm AI\data\runtime\models\MV-20261023-132433-3B70.txt`, 5.263.949 byte. SHA-256 `7d9b5d0e…cad093db3` khớp bản ghi; metadata cho đúng 36 feature của run |
| So với model đang dùng, cùng fold | WAPE **80,58% so với 80,83%** (−0,25 điểm %); bias +5,77% so với +5,72% → `verdict=BETTER` |
| Quality gate | `WAPE_MAX` **FAIL** (0,806 > 0,60). Các điều kiện khác PASS → `BELOW_THRESHOLD` → `USABLE_WITH_WARNING`. Model đang dùng cũng ở đúng trạng thái này |
| Kiểm chứng độc lập (walk-forward 01/06–22/10, cùng cấu hình feature, 2,38 triệu điểm giống nhau) | Toàn kỳ: 70,27% so với 70,75% (−0,47 điểm %; khoảng tin cậy 95%: −0,67 … −0,29). **4 lô gần nhất: 72,20% so với 71,91% (+0,29 điểm %, candidate kém hơn ở cả 4 lô)** |
| Production | Model đang dùng `MV-20261020-131556-EEF6`; forecast đang dùng `FCR-20261020082402-A42C91`, đúng như kỳ vọng. Không thay đổi gì |

### 2. So sánh candidate và model đang dùng (incumbent)

#### 2.1 Danh tính

| | Candidate | Incumbent (đang dùng) |
|---|---|---|
| Training run / model | `TRN-20261023055745-933B70` / `MV-20261023-132433-3B70` | `TRN-20261020054540-D7EEF6` / `MV-20261020-131556-EEF6` |
| Trạng thái | REJECTED + `PROMOTION_REVIEW_REQUIRED` (candidate), có thể promote | ACCEPTED, đang dùng |
| Dữ liệu huấn luyện | 01/01–22/10/2026: 1.367.447 dòng, qty 42.294.439, 9.662 SKU, 2 FC, fingerprint `d03c1f19898cdf11` (D-1 `JOB-20261023000935-BA92E3`) | 01/01–19/10/2026: 1.358.317 dòng, qty 42.023.217, fingerprint `e4a56ce6592d4834` |
| Feature | **36**: thêm `open_hours_last`, `open_hours_mean_7`, `cust_mean_28`, `cust_repeat_share_28`, `cust_repeat_interval_28` | **31**: không có open hours, không có customer |
| Chiến lược và tham số | DIRECT, tweedie (power 1,2), learning rate 0,05, 31 lá, 300 vòng, seed 7 | Giống hệt |
| Số series / dòng huấn luyện | 17.140 / 5.212.941 | 17.138 / 5.207.073 |
| SHA-256 artifact | `7d9b5d0e…cad093db3`, khớp | `cd5f4ce5…5343456b`, khớp |

#### 2.2 Trên cùng tập đánh giá: so sánh "cùng fold" của app

Cách app làm: lấy cấu hình đã lưu của incumbent, fit lại walk-forward trên đúng các fold, panel và target của candidate (`WALK_FORWARD_SAME_FOLDS`).

- Có 7 fold, mỗi fold 30 ngày, từ 27/03 đến 22/10/2026.
- 3.367.553 điểm, tổng thực tế 27.184.491.

| Chỉ số | Candidate | Incumbent (fit lại, cùng fold) | Chênh lệch | Baseline 28 ngày (cùng fold) |
|---|---:|---:|---:|---:|
| WAPE | 80,58% | 80,83% | **−0,25 điểm %** | 85,12% |
| Bias | +5,77% | +5,72% | +0,05 điểm % (lệch tuyệt đối tăng nhẹ) | +13,14% |
| MAE | 6,505 | 6,525 | −0,020 | 6,871 |
| MAPE (thực tế ≥ 1) | 124,4% | 124,9% | −0,5 điểm % | 130,7% |
| Tổng dự báo | 28.753.589 | 28.740.724 | | 30.755.863 |

**Không so sánh được:** WAPE 79,72% của incumbent lúc nó được huấn luyện. Con số đó tính trên dữ liệu đến 19/10 và các fold khác (24/03–19/10), nên không tương đương với 80,58% của candidate. App chỉ lưu kết quả **gộp** của phép so sánh cùng fold. Kết quả từng fold và từng phân đoạn của incumbent trên các fold này **không được lưu**, xem mục 5.

#### 2.3 Theo nhóm và theo thời gian: walk-forward 01/06–22/10/2026 (cấp cấu hình)

Nguồn: `reports\backtest-20260601-20261022` (bản sao DB, chống rò rỉ đạt).

- Nhánh CAND có **đúng** danh sách 36 feature và tham số của candidate; nhánh PROD **đúng** 31 feature và tham số của incumbent (đã đối chiếu từng feature).
- Model ở đây là bản huấn luyện lại mỗi tuần, không phải chính artifact candidate. Cả hai nhánh được chấm trên cùng các điểm, horizon 1.

| Phân đoạn | Số điểm | WAPE CAND | WAPE PROD | Chênh lệch | Bias CAND | Bias PROD | WAPE BASE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Toàn kỳ | 2.379.386 | 70,27% | 70,75% | −0,47 | −0,95% | −1,05% | 76,80% |
| **4 lô gần nhất (28/09–22/10)** | 426.564 | **72,20%** | **71,91%** | **+0,29** | +0,58% | −0,90% | 75,41% |
| ↳ Lô 28/09 | 118.915 | 70,11% | 69,89% | +0,22 | −11,63% | −14,23% | 77,41% |
| ↳ Lô 05/10 | 119.412 | 76,79% | 76,67% | +0,13 | +15,88% | +15,20% | 76,14% |
| ↳ Lô 12/10 | 119.709 | 69,01% | 68,58% | +0,43 | −1,48% | −2,68% | 75,02% |
| ↳ Lô 19/10 (4 ngày) | 68.528 | 73,51% | 73,10% | +0,41 | −0,44% | −1,85% | 71,85% |
| Sản lượng cao, toàn kỳ | 166.100 | 60,70% | 61,14% | −0,44 | −1,27% | −1,55% | 67,92% |
| **Sản lượng cao, 4 lô gần nhất** | 27.304 | 61,92% | 61,57% | **+0,35** | +2,19% | +0,55% | 66,19% |
| Gián đoạn (INTERMITTENT), toàn kỳ | 869.142 | 116,67% | 117,40% | −0,73 | −15,88% | −14,70% | 123,51% |
| Gián đoạn, 4 lô gần nhất | 168.981 | 115,97% | 115,99% | −0,02 | −18,10% | −17,96% | 121,08% |
| Thất thường (ERRATIC), toàn kỳ | 218.257 | 75,39% | 75,87% | −0,48 | −0,78% | −0,61% | 84,27% |
| **Thất thường, 4 lô gần nhất** | 19.989 | 78,36% | 77,17% | **+1,19** | +6,54% | +4,93% | 84,26% |
| Cục (LUMPY), toàn kỳ | 918.801 | 119,62% | 120,71% | −1,09 | −1,68% | −0,34% | 126,85% |
| Cục, 4 lô gần nhất | 171.726 | 111,31% | 111,72% | −0,41 | −2,62% | −2,98% | 117,64% |
| Ổn định (SMOOTH), toàn kỳ | 96.464 | 41,99% | 42,23% | −0,24 | −0,88% | −1,87% | 45,53% |

Chênh lệch tính bằng điểm %; số âm nghĩa là CAND tốt hơn. Nhóm nhu cầu (Syntetos-Boylan) và nhóm sản lượng xác định trên lịch sử trước mốc của từng lô.

**Dự báo thiếu và dư** (đơn vị, cấp cấu hình):

| Phạm vi | CAND thiếu | CAND dư | PROD thiếu | PROD dư |
|---|---:|---:|---:|---:|
| Toàn kỳ | 5.955.063 | 5.796.090 | 6.002.606 | 5.827.533 |
| 4 lô gần nhất | 735.175 | 747.078 | 747.419 | 728.944 |
| Sản lượng cao, toàn kỳ | 4.107.642 | 3.939.039 | 4.155.149 | 3.949.809 |
| Gián đoạn, toàn kỳ | 336.415 | 255.807 | 335.284 | 260.645 |

- Tỷ lệ điểm dự báo thấp hơn thực tế (khi thực tế > 0): CAND 60,8%, PROD 60,9%.
- Ở 4 lô gần nhất, CAND dự báo thiếu ít hơn PROD 12.244 đơn vị nhưng dư nhiều hơn 18.134 đơn vị.
- Ở nhóm gián đoạn, CAND thiếu hơi nhiều hơn (bias −15,9% so với −14,7%).

### 3. Quality gate và các trạng thái

Các ngưỡng là mặc định của app, **chưa được kinh doanh phê duyệt** (`thresholds_approved_by_business=false`). Chính sách: `PUBLISH_WITH_WARNING`.

| Điều kiện | Giá trị | Ngưỡng | Kết quả |
|---|---:|---:|---|
| `BACKTEST_RELIABLE` | 7 fold được chấm (cấu hình 12; fold 1–5 bị bỏ vì chưa đủ 56 ngày lịch sử trước mốc) | ≥ min(2, số fold) và có WAPE | PASS |
| `MIN_BACKTEST_POINTS` | 3.367.553 | ≥ 200 | PASS |
| `WAPE_MAX` | 0,8058 | ≤ 0,60 | **FAIL** |
| `ABS_BIAS_MAX` | 0,0577 | ≤ 0,20 | PASS |
| `BEAT_BASELINE` | không áp dụng (`require_beat_baseline=false`); để tham khảo: 0,806 < 0,851 | — | — |

Ý nghĩa ba trạng thái (theo code `backend/app/ml/pipeline.py`):

- **`verdict=BETTER`** (`compare_with_incumbent`, dòng 194–234):
  - Cấu hình đã lưu của incumbent được fit lại walk-forward trên đúng 7 fold của candidate.
  - WAPE gộp của candidate trừ của incumbent = −0,0025 < 0 nên ra BETTER. Chỉ khi hai bên bằng nhau tuyệt đối (sai khác ≤ 1e-9) mới là EQUAL.
  - **Không có ngưỡng kinh doanh, không có kiểm định thống kê.** BETTER chỉ có nghĩa "thấp hơn".
- **`usage=USABLE_WITH_WARNING`** (`assess`, dòng 94–126):
  - Phần kỹ thuật OK. Phần chất lượng là `BELOW_THRESHOLD` vì `WAPE_MAX` trượt. Độ tin cậy NORMAL.
  - Với chính sách `PUBLISH_WITH_WARNING`, kết quả là "dùng được, kèm cảnh báo".
- **`reason_code=PROMOTION_REVIEW_REQUIRED`** (`train_and_publish`, dòng 522–563):
  - Khi đã có model đang dùng, lần huấn luyện chỉ lưu candidate để duyệt (REJECTED + `PROMOTION_REVIEW_REQUIRED`, alert `CANDIDATE_READY_FOR_REVIEW`) và **không publish forecast**.
  - Chỉ thao tác promote của người dùng mới publish. Hiện chưa có quy tắc promote tự động nào được duyệt.

#### Backtest của chính candidate (trong app; theo fold, so với baseline)

| Fold | Kỳ | Số ngày huấn luyện | WAPE model | Bias model | WAPE baseline | Bias baseline | Tổng thực tế |
|---|---|---:|---:|---:|---:|---:|---:|
| 6 | 27/03–25/04 | 85 | 88,62% | +27,60% | 87,62% | +21,74% | 4.874.895 |
| 7 | 26/04–25/05 | 115 | 71,23% | +0,43% | 74,31% | +6,26% | 4.587.239 |
| 8 | 26/05–24/06 | 145 | 71,52% | −8,92% | 72,63% | −4,77% | 4.887.679 |
| 9 | 25/06–24/07 | 175 | 74,21% | −0,59% | 82,47% | +15,37% | 4.232.478 |
| 10 | 25/07–23/08 | 205 | 81,25% | +8,22% | 86,81% | +18,66% | 3.545.245 |
| 11 | 24/08–22/09 | 235 | 103,03% | +9,96% | 120,47% | +37,00% | 2.615.372 |
| 12 | 23/09–22/10 | 265 | 86,29% | +4,60% | 89,66% | +7,31% | 2.441.583 |

Ở fold 6, model kém baseline. Kết quả từng fold của incumbent trên đúng các fold này không được lưu.

Phân đoạn trong backtest của candidate (model so với baseline, horizon 1–30):

- **Theo horizon:**
  - 1–7 ngày: 75,05% (bias +2,89%) so với 80,89%.
  - 8–15 ngày: 80,34% (+4,17%) so với 83,19%.
  - 16–30 ngày: 83,37% (+8,05%) so với 88,22%.
- **Tổng theo kỳ đặt hàng:** tổng 7 ngày 53,18%; tổng 15 ngày 49,05%; tổng 30 ngày 47,93%. Baseline lần lượt 56,20%, 51,79%, 51,60%.
- **Theo sản lượng:**
  - Cao (78,6% tổng thực tế): 71,61% (bias +6,78%) so với 76,94%.
  - Thấp: 113,82% so với 115,46%.
- **Theo nhóm nhu cầu:** SMOOTH 50,73%; ERRATIC 86,88% (bias +9,96%); INTERMITTENT 126,56% (bias −12,56%); LUMPY 129,73%; SHORT_HISTORY 123,15% (bias −18,43%); INACTIVE 100% (bias −100%).
- **Ngày đột biến** (16,5% sản lượng): WAPE 83,73%, **bias −83,21%** (thiếu rất nặng vào ngày đột biến). Ngày thường: 79,96%, **bias +23,34%** (dư).
- **Theo phương pháp:**
  - LightGBM 78,32% (bias +7,16%; 96,2% sản lượng).
  - Dự phòng gián đoạn 149,05% (−29,98%).
  - Dự phòng chuỗi mới 123,15% (−18,43%).
  - Dự phòng ngừng bán: bỏ sót 49.873 đơn vị.

### 4. Hiện trạng production (đã xác minh, chỉ đọc)

- **Model đang dùng:** `MV-20261020-131556-EEF6` (`TRN-20261020054540-D7EEF6`, ACCEPTED), theo registry `active_model`.
- **Forecast đang dùng: `FCR-20261020082402-A42C91`**, đúng như kỳ vọng.
  - PUBLISHED lúc 20/10 15:24:12, mốc 20/10, dữ liệu đến 19/10, horizon tối đa 15 ngày (phủ 20/10–03/11).
- Candidate không có forecast run nào. Job ghi `published_forecast_run_id = FCR-20261020082402-A42C91`.
- Hiện không có job nào đang chạy hay chờ. Sau job huấn luyện không có lần promote nào.

### 5. Rủi ro, dữ liệu thiếu và đề xuất

**Rủi ro nếu promote**

1. Mức lợi rất nhỏ (−0,25 điểm % trên cùng fold; −0,47 điểm % trong walk-forward) và **đảo chiều ở 4 tuần gần nhất**: +0,29 điểm % chung, +0,35 ở nhóm sản lượng cao, +1,19 ở nhóm thất thường.
2. Bias trên cùng fold xấu đi rất nhẹ (+0,05 điểm %). Ở nhóm gián đoạn, candidate dự báo thiếu nhiều hơn một chút.
3. Cả hai model đều trượt `WAPE_MAX`, và ngưỡng chưa được kinh doanh phê duyệt.
4. Ngày đột biến bị dự báo thiếu khoảng 83%, ngày thường dư khoảng 23%. Đây là đặc tính chung, promote không sửa được.
5. Candidate khác incumbent ở **hai** nhóm feature (open hours và customer), nên không tách được tác dụng riêng của Customer ID.
6. Feature customer khi kiểm chứng lịch sử là giả định "nếu đã có từ trước", vì mapping chỉ tồn tại từ 23/10.

**Lưu ý vận hành**

- Promote yêu cầu fingerprint dữ liệu hiện tại **bằng** của candidate (`d03c1f19898cdf11`). Lần nạp D-1 kế tiếp sẽ đổi fingerprint, và candidate này không promote được nữa (`DATA_CHANGED_SINCE_TRAINING`).
- Khi đang có model chạy, forecast mới **chỉ** xuất hiện qua promote. HOLD nghĩa là tiếp tục dùng forecast 20/10 (dữ liệu đến 19/10, phủ đến 03/11).
- Promote để có forecast mới hơn là một quyết định kinh doanh riêng, không dựa trên lý do độ chính xác.

**Chưa xác minh được (thiếu artifact)**

- Chỉ số từng fold và từng phân đoạn của incumbent trên đúng các fold của candidate: app chỉ lưu kết quả gộp. Phần so sánh theo nhóm và theo thời gian ở mục 2.3 là cấp cấu hình (fit lại mỗi tuần, horizon 1), không phải chính hai artifact.
- Độ chính xác thực tế của artifact candidate trên các ngày từ 23/10: chưa có actual.
- Ý nghĩa thống kê của −0,25 điểm %: app không tính khoảng tin cậy. Khoảng tin cậy chỉ có ở walk-forward cấp cấu hình.

**Đề xuất**

1. **HOLD** candidate `MV-20261023-132433-3B70` cho đến khi kinh doanh phê duyệt tiêu chí promote, ví dụ:
   - WAPE giảm tối thiểu X điểm % trên toàn kỳ **và** ở 4 tuần gần nhất **và** ở nhóm sản lượng cao;
   - giới hạn bias và dự báo thiếu.
2. Nếu cần tách tác dụng của Customer ID so với open hours: cần một backtest ablation mới (chỉ customer / chỉ open hours). Việc này phải được duyệt riêng.
3. Nếu cần forecast mới hơn ngay: quyết định promote vì độ tươi dữ liệu thuộc về anh/chị. Rủi ro độ chính xác thấp (tổng thể không kém hơn, gần đây kém khoảng 0,3 điểm %), nhưng đó không phải lập luận "model tốt hơn".

### 6. Bằng chứng và cách lấy

- **GET** (lưu nguyên văn trong scratchpad của phiên): `/api/jobs/JOB-20261023055649-4DB587`, `/api/training-runs/TRN-20261023055745-933B70`, `/api/training-runs/TRN-20261020054540-D7EEF6`, `/api/forecast-runs`, `/api/features/registry?source=BIGQUERY`, `/api/settings`.
- **Artifact:** băm SHA-256 file model trong `D:\Buymed\Lightgbm AI\data\runtime\models\` (chỉ đọc).
- **Walk-forward:** `D:\Buymed\Lightgbm AI\reports\backtest-20260601-20261022\` (`forecasts/`, `checkpoints/`, `BAO_CAO_BACKTEST.md`). Sai lệch thiếu/dư tính lại từ các file kết quả có sẵn, không dự báo lại.
- **Code tham chiếu:** `backend/app/ml/pipeline.py`: `quality_gate` / `_gate_checks` (31–52), `assess` (94–126), `compare_with_incumbent` (194–234), `train_and_publish` (522–563), `promotable` / `promote_candidate` (701–809).

### 7. Xác nhận chỉ đọc

- Không huấn luyện, không chạy backtest mới. Không promote. Không đổi DB, model, forecast, lịch hay cấu hình.
- Không deploy, commit hay push.
- Chỉ gọi GET và đọc file. File duy nhất tạo trong repo là báo cáo này; các file phân tích tạm nằm trong scratchpad.

## 2. Điều tra 30 câu hỏi: Demand Forecasting LightGBM (chỉ đọc)

Nguồn: `reports\dieu-tra-30-cau-hoi-20261026\BAO_CAO_DIEU_TRA_30_CAU_HOI.md` (worktree MAIN).

- **Ngày:** 26/10/2026, 15:15–16:15 giờ Việt Nam.
- **STATUS: `PARTIAL`.**
  - Đã trả lời đủ 30 câu.
  - 15 câu `ĐÃ XÁC MINH`, 10 câu `XÁC MINH MỘT PHẦN`, 1 câu `CHƯA XÁC MINH`, 4 câu `KHÔNG CÓ DỮ LIỆU ĐỂ KẾT LUẬN`.
- **Không làm:**
  - không train, không chạy backtest mới, không tạo forecast, không promote;
  - không truy vấn BigQuery, kể cả dry-run;
  - không sửa mã, cấu hình, DB, lịch chạy;
  - không commit, push hay deploy.
- **File đã tạo** (chỉ trong thư mục này; `reports/` nằm ngoài Git theo `.gitignore:31`):
  - báo cáo này;
  - `BAT_THUONG_30_CAU_HOI.xlsx`;
  - `evidence\`.

**Các nguồn được gọi tắt trong báo cáo:**
- **CSV:** 5 file `T06…T10-2026.csv` trong `C:\Users\Giau Vo\Downloads`, trích 24/10 lúc 14:24–14:30.
- **CSV cũ:** thư mục `Downloads\data cũ`, trích 24/10 lúc 13:37–13:43.
- **Workbook so sánh:** `So_sanh_AvgDemand_vs_LightGBM_T06-T10_2026 (update).xlsx`, lưu 25/10 22:26.
- **Backtest:** `reports\backtest-20260601-20261022\`. Đây là nguồn LightGBM duy nhất của workbook so sánh.

---

### 1. Executive Summary

**Tình trạng chung.** Phần mã nguồn, cấu hình và model production được xác minh đầy đủ. Các câu về dữ liệu nghiệp vụ còn phụ thuộc nguồn chưa có trong repository: SQL tạo CSV, công thức Avg, quy trình mua hàng, chi phí.

**Phát hiện ảnh hưởng nghiêm trọng tới độ tin cậy của backtest và so sánh:**

1. **`sku_system_status` trong CSV là trạng thái tại lúc trích, chép vào mọi ngày** (câu 10–12).
   - 0 / 22.849 cặp SKU × FC có quá một giá trị trong 145 ngày.
   - Giữa hai lần trích cách nhau 47 phút, 14 cặp (420 dòng) đổi LIMIT ↔ OUT_OF_STOCK.
   - Hệ quả:
     - "OUT_OF_STOCK nhưng mở bán 24 h" là 587.425 dòng;
     - đường "OUT_OF_STOCK giảm từ khoảng 37–40 % xuống khoảng 5 %" là **hiệu ứng của định nghĩa**, không phải thay đổi vận hành.
   - Không thể dùng cột này để phân tích hết hàng theo ngày.
2. **Backtest không mô phỏng cách production thật sự phát hành forecast** (câu 1–5).
   - Backtest: dự báo horizon 1 tại mốc từng ngày, model train lại mỗi thứ Hai.
   - Production: forecast chỉ đổi khi có người promote. Các run gần đây: 17/10, 18/10, 19/10, 20/10, 24/10, 26/10. Mỗi run dùng một mốc cố định, horizon tới 15 ngày.
   - Vì vậy kết quả backtest nhiều khả năng lạc quan hơn độ chính xác vận hành.
3. **Không tái lập được giá trị Avg (`avg_demand_history`)** (câu 14–16).
   - Không có công thức trong repository.
   - Giá trị là đầu ra của một truy vấn chạy ngày 24/10: hai lần trích lệch nhau đúng bởi `ROUND`.
   - Không giả thuyết trung bình trượt hay trung bình mũ nào khớp quá 0,5 % các giá trị khác 0.
   - Chưa chứng minh được Avg trong file là số đã dùng tại ngày đó, cũng chưa loại trừ được việc nó dùng thông tin sau ngày D.
4. **Luật FALLBACK đếm ngày không mở bán là ngày cầu = 0** (câu 21–23).
   - Tỷ lệ cặp-ngày có mở bán: 67–70 % (T6–T7) → 36–40 % (tuần giữa T9) → 45 % (T10).
   - Tại mốc 22/10, 50,8 % ngày = 0 của chuỗi FALLBACK_INTERMITTENT là ngày không mở bán.
   - Số chuỗi chủ yếu dùng LightGBM giảm từ 7.486 (T7) xuống 4.468 (T10).
5. **Làm tròn số nguyên trước khi cộng dồn** (câu 25).
   - 84 % điểm FALLBACK_INTERMITTENT (mức < 0,5/ngày) được công bố là 0 mỗi ngày.
   - Tổng 7/15 ngày trong file xuất = tổng các số nguyên theo ngày. SKU bán chậm vì vậy có tổng 0.
   - Workbook so sánh còn chấm MAE trên số đã làm tròn; chính README của workbook ghi đây là một phần lợi thế của LightGBM.

**Vấn đề ảnh hưởng trực tiếp tới mua hàng:**
- App **không có** logic mua hàng: không có tồn, hàng đang về, MOQ, quy cách, tồn an toàn, lead time, chi phí thiếu hay dư (câu 17–19).
- 2.770 cặp SKU × FC có mở bán nhưng không có dự báo. 2.747 cặp trong đó chưa từng có dòng đơn từ 01/01 (câu 24).
- Metric hiện có (WAPE, bias, MAE) không phản ánh chi phí mua hàng.

**Chưa thể kết luận:**
- SQL nguồn của CSV;
- công thức và lịch sử của Avg;
- xu hướng hết hàng thật theo ngày;
- ý nghĩa của LIMIT;
- quy tắc mua hàng, lead time, chi phí, giá vốn;
- nguồn deal / voucher;
- 18 cặp có cầu trong CSV nhưng không có chuỗi trong app.

---

### 2. Thông tin phiên bản và phạm vi

| Hạng mục | Giá trị đã xác minh |
|---|---|
| Repository | `D:\Buymed\Lightgbm AI`, branch `main`, HEAD `af835b8`. Working tree sạch lúc bắt đầu; phiên này không đổi file nào được Git theo dõi |
| App đang chạy | Lúc bắt đầu: 1.2.13 (PID 11964). **Trong lúc điều tra, chủ hệ thống chạy `deploy-upgrade.ps1` (15:26–15:46).** Từ 15:45:46: 1.2.14, PID 29408, `BUILD-INFO` commit `af835b8`, `dirty: false`. Toàn bộ `backend\app` của bản cài 1.2.14 **trùng từng byte** với repo (0 file khác). Mã ML của 1.2.13 cũng trùng repo, trừ file mới `forecast_explainer.py` (chỉ để giải thích) |
| Tác động của phiên này lên deploy | Khi app ngừng phản hồi, phiên này dừng tác vụ phân tích nền của chính mình để nhường RAM (RAM trống còn 1,1 GB), rồi chờ deploy xong mới chạy tiếp. Không chạm vào tiến trình deploy |
| Model production | `MV-20261026-105345-C73F`: training run `TRN-20261026031942-53C73F`, forecast run `FCR-20261026044021-330262`. File `data\runtime\models\MV-20261026-105345-C73F.txt` có SHA-256 `367182…6e8`, không đổi trước và sau deploy |
| Backtest được đánh giá | `reports\backtest-20260601-20261022` (chạy 23/10 04:04–05:37 UTC, runner SHA `D8DE6DAB…`, bản sao DB `8ABD356D…`). Workbook so sánh dùng nhánh **CAND** của backtest này |
| Nguồn đã đọc | Mã: `features.py`, `model.py`, `pipeline.py`, `demand.py`, `qty.py`, `forecast_routes.py`, `connector.py`, `feature_registry.py`, `settings_service.py`, code runner backtest. Tài liệu: `docs/02_kien_truc_du_lieu/BIGQUERY.md`, `docs/04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md`. Báo cáo: audit backtest 24/10, điều tra model 26/10. File người dùng: 5 CSV mới + 5 CSV cũ, workbook so sánh (update), `So sánh 2 model tháng 10-2026.xlsx`, `Import_stock_updated.xlsx` (chỉ phần đầu). API: chỉ `GET` |
| Không đọc | `avg_demand_2026-0x.xlsx`: README của workbook ghi nguồn là các CSV. Workbook so sánh bản V3 và bản gốc (bản cũ hơn) |

---

### 3. Trả lời chi tiết câu 1–30

#### A. Cách chạy backtest

##### Câu 1. Backtest T6–T10 có dùng đúng cấu hình của model production `MV-20261026` không? (feature, Tweedie 1,2, 300 vòng, FALLBACK…)

- **Kết luận:**
  - **Đúng cấu hình, không đúng file model.**
  - Nhánh CAND (nhánh workbook dùng) có fingerprint cấu hình `8468ebe66d1706f7` ở cả 21 lô, trùng fingerprint của run production. Fingerprint này là hash của toàn bộ `ModelSettings`, gồm:
    - 36 feature;
    - DIRECT 12 mốc × 7 ngày;
    - Tweedie với power 1,2;
    - 300 vòng, lr 0,05, 31 lá;
    - ngưỡng FALLBACK 60 / 28 / 0,80 / 28.
  - Mỗi lô train một model riêng. Không lô nào là file `MV-20261026`.
  - Nhánh PROD của backtest là cấu hình của `MV-20261020` (fingerprint `da229f54877aa87e`, 31 feature, không có giờ mở bán và khách hàng). Workbook không dùng nhánh này.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - `reports\backtest-audit-20260601-20261023\BATCH_TRAINING_SCHEDULE.csv`: cột `cand_config_fp`, `cand_n_features` = 36;
  - [backtest_runner.py:170-175](../../reports/backtest-20260601-20261022/code/backtest_runner.py#L170-L175): CAND dùng đúng `registry.resolve` như app;
  - [backtest_runner.py:236-240](../../reports/backtest-20260601-20261022/code/backtest_runner.py#L236-L240);
  - [backtest_report.py:85](../../reports/backtest-20260601-20261022/code/backtest_report.py#L85): Excel lấy `cand_d1`;
  - `config_fingerprint` của `TRN-20261026031942-53C73F` (`reports\model-learning-investigation-20261026\evidence\`).
- **Diễn giải:** cùng cấu hình nghĩa là cùng cách học và cùng luật. Khác biệt với production:
  1. dữ liệu đến 22/10 (bản sao 23/10), production đến 25/10;
  2. backtest không chọn giữa LightGBM và baseline tại mỗi mốc, app thì có;
  3. cách phát hành forecast khác (câu 3, 5);
  4. feature khách hàng của lịch sử được tính ngược, vì mapping chỉ có từ 23/10.
- **Ảnh hưởng:** kết quả backtest đại diện cho cấu hình đang chạy, không cho file model cụ thể.
- **Còn thiếu:** không.

##### Câu 2. Backtest có dùng model production đã học nhãn đến 25/10 để dự báo ngược T6–T10 không? Nguy cơ leakage?

- **Kết luận:** **Không.**
  - `MV-20261026` được tạo ngày 26/10 lúc 10:53, sau khi backtest chạy xong ngày 23/10.
  - Mỗi lô chỉ học từ dữ liệu trước thứ Hai của lô.
  - Cả hai workbook đều lấy cột LightGBM từ Excel backtest, không lấy từ model production:
    - workbook update: theo README;
    - workbook "2 model": sheet `Forecast LGBM` có 375.651 dòng, đúng bằng số dòng của `forecast_backtest_2026-10.xlsx`.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [backtest_runner.py:218-220](../../reports/backtest-20260601-20261022/code/backtest_runner.py#L218-L220) và [:253-255](../../reports/backtest-20260601-20261022/code/backtest_runner.py#L253-L255): assert dữ liệu < mốc;
  - 165/165 kiểm tra rò rỉ đạt (`BAO_CAO_BACKTEST.md`);
  - sheet `DOI_SOAT` và README của workbook so sánh (`evidence\workbook_update_README_KET_QUA_DOI_SOAT.txt`).
- **Diễn giải:** không có rò rỉ trực tiếp từ model. Rủi ro còn lại:
  1. dữ liệu là phiên bản đã sửa (bản sao 23/10, gồm dòng giữ `KEEP_OBSERVED_LINES`), không phải số "đã biết lúc đó";
  2. cấu hình được chọn bằng thí nghiệm chồng lên giai đoạn đánh giá;
  3. workbook lọc dòng bằng `total_open_hours` **của chính ngày D**: chỉ biết sau D, áp cho cả hai phương pháp, không phải input model;
  4. phía Avg: chưa biết giá trị có dùng thông tin ≥ D hay không (câu 14–15).
- **Ảnh hưởng:** phía LightGBM không lạc quan do rò rỉ model. So sánh với Avg chưa chắc công bằng vì (4).
- **Còn thiếu:** SQL và công thức của `avg_demand_history`.

##### Câu 3. Backtest train lại mỗi ngày, mỗi thứ Hai hay lịch khác?

- **Kết luận:** **mỗi thứ Hai.**
  - 21 lô, mốc 01/06, 08/06, … 19/10 (lô cuối 19–22/10, 4 ngày).
  - Trong lô dùng cùng một model, nhưng feature được tính lại mỗi ngày D từ dữ liệu < D.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - `BATCH_TRAINING_SCHEDULE.csv`: `origin`, `started_at_utc`, `cand_model`, SHA của 21 model;
  - [backtest_runner.py:214-299](../../reports/backtest-20260601-20261022/code/backtest_runner.py#L214-L299).
- **Diễn giải:** production có slot train hằng ngày (cài đặt hiện tại 08:20). Nhưng khi đã có model đang dùng, model mới chỉ là ứng viên chờ duyệt ([pipeline.py:538-563](../../backend/app/ml/pipeline.py#L538-L563)). Forecast đổi khi promote: các run 17, 18, 19, 20, 24, 26/10 (`GET /api/forecast-runs`).
- **Ảnh hưởng:** backtest (model mới mỗi tuần, mốc mỗi ngày) không phản ánh độ trễ của forecast production.
- **Còn thiếu:** không.

##### Câu 4. Cửa sổ nhãn là 84 ngày trượt hay mở rộng? Nhãn của forecast đầu tháng 6 bắt đầu từ ngày nào?

- **Kết luận:**
  - **Nhãn: 84 ngày trượt.** 12 mốc t0 = c − 7j (j = 1..12), mỗi mốc có h = 1..30 với ngày đích < c, nên ngày nhãn nằm trong [c − 84, c − 1].
  - **Lịch sử dùng tính feature: mở rộng** từ 01/01/2026. `max_train_days` 730 không cắt gì.
  - Lô 01/06: nhãn **09/03 → 31/05/2026**; feature dùng dữ liệu 01/01 → 31/05; 4.523.334 dòng train.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [features.py:403-425](../../backend/app/ml/features.py#L403-L425), [model.py:42-52](../../backend/app/ml/model.py#L42-L52);
  - dòng 1 của `BATCH_TRAINING_SCHEDULE.csv` (`train_first_day` 2026-01-01, `train_last_day` 2026-05-31, `cand_train_rows` 4.523.334).
- **Diễn giải:** feature xa nhất: `days_since_last_sale` 180 ngày, `roll_mean_56`, lag 28 ngày. Phần dữ liệu cũ hơn chỉ ảnh hưởng `series_age` và luật FALLBACK.
- **Ảnh hưởng:** model mỗi lô chỉ học 12 trạng thái gần nhất của mỗi chuỗi.
- **Còn thiếu:** không.

##### Câu 5. Khi dự báo ngày D, lag và rolling tính đến D-1, đến mốc gần nhất hay cách khác?

- **Kết luận:**
  - **Backtest (số trong Excel):** feature tại mốc D, chỉ từ dữ liệu ≤ D-1.
    - `lag_1` = D-1; rolling 7/14/28/56 kết thúc ở D-1; giá, giờ mở bán = D-1; khách hàng = [D-28, D-1].
    - Lịch là của ngày D; horizon = 1.
    - Model là model của lô, train trên dữ liệu < thứ Hai c.
  - **Production:** một mốc mỗi run (= ngày sau `train_end`). Ngày đích = mốc + h − 1; feature lấy từ dữ liệu ≤ mốc − 1. Run được dùng tới lần promote sau.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [backtest_runner.py:251-263](../../reports/backtest-20260601-20261022/code/backtest_runner.py#L251-L263);
  - [features.py:236-304](../../backend/app/ml/features.py#L236-L304), [features.py:332-334](../../backend/app/ml/features.py#L332-L334);
  - [model.py:196-219](../../backend/app/ml/model.py#L196-L219).
- **Diễn giải:** "D-1" trong backtest là dữ liệu đã ổn định (bản sao 23/10). Ở production, D-1 là bản nạp sáng hôm đó và có thể bị nguồn sửa sau.
- **Ảnh hưởng:** backtest dùng thông tin mới hơn và sạch hơn production. Sai số vận hành thực tế có thể lớn hơn.
- **Còn thiếu:** chấm forecast đã công bố so với actual (lịch sử D+1 từ 18/10).

##### Câu 6. Mỗi mốc train có nhãn một hay nhiều ngày đích? Horizon có phải feature không?

- **Kết luận:** **nhiều ngày đích.**
  - Mỗi mốc t0 tạo dòng cho h = 1..30 (ngày đích t0 + h − 1 < T); target = Y[t0 + h − 1].
  - **`horizon` là feature.** Ma trận = 29 feature tính tại mốc + 6 feature lịch của ngày đích + `horizon` = 36 cột.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [features.py:403-425](../../backend/app/ml/features.py#L403-L425), [:326-334](../../backend/app/ml/features.py#L326-L334), [:205-208](../../backend/app/ml/features.py#L205-L208);
  - file model production: `horizon` có khoảng [1:30], 104 split.
- **Diễn giải:** trong backtest, Excel chỉ lấy h = 1.
- **Ảnh hưởng:** model học chung mọi horizon; horizon 22–30 chỉ có 8–9 mốc.
- **Còn thiếu:** không.

##### Câu 7. Có feature nào lấy giá trị của chính ngày D không (`total_open_hours`, `available_to_buy`, giá, `sku_system_status`)?

- **Kết luận:** **không feature nào dùng giá trị của ngày D.**
  - `open_hours_last` = D-1, `open_hours_mean_7` = [D-7, D-1]; `price_last` = D-1 (forward-fill).
  - `sku_system_status` **không phải feature**: chỉ là cột tham chiếu; tài liệu cấm dùng làm feature vì là trạng thái hiện tại.
  - `available_to_buy` không có trong nguồn và trong app. Bảng `fact_product_sku_status` có `product_afs`, nhưng không được dùng.
  - Feature biết trước: lịch của ngày D (`dow`, `dom`, `month`, `weekofyear`, `is_weekend`, `days_to_month_end`) và `horizon`.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [features.py:269-289](../../backend/app/ml/features.py#L269-L289);
  - [connector.py:49](../../backend/app/bq/connector.py#L49) và [:61](../../backend/app/bq/connector.py#L61): `sku_status` là cột tham chiếu;
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:426-428](../02_kien_truc_du_lieu/BIGQUERY.md#L426-L428), [:479-485](../02_kien_truc_du_lieu/BIGQUERY.md#L479-L485);
  - `reference_mapping` lưu với run production.
- **Diễn giải:** giờ mở bán D-1 chỉ có sau khi D-1 kết thúc và D-1 đã nạp (tín hiệu từ 08:00, train 08:20). Workbook so sánh lọc dòng bằng giờ mở bán của ngày D. Giờ này được dựng lại từ nhật ký trạng thái, nên chỉ biết sau D (câu 2).
- **Ảnh hưởng:** model không rò rỉ qua feature. Phép lọc đánh giá thì dùng thông tin sau D.
- **Còn thiếu:** không.

##### Câu 8. Dữ liệu trích BigQuery ngày 24/10 có gồm các thay đổi về sau (hủy, trả hàng) không? Có tái dựng "as-of" được không?

- **Kết luận:**
  - **Có, theo trạng thái nguồn lúc trích.** Bảng nguồn của app được dựng lại mỗi sáng; đơn bị hủy rời khỏi bảng. Bản trích 24/10 vì vậy đã phản ánh các lần hủy tới thời điểm đó.
  - CSV **không** đến từ bảng nguồn của app:
    - CSV có 22.849 cặp × mọi ngày (kể cả ngày cầu = 0) và các cột `avg_demand_history`, `demand_zero_reason`;
    - bảng `demand_planing_lightgbm` chỉ có dòng đơn.
    - SQL tạo CSV không có trong repository.
  - `refresh_time` khác nhau theo từng file (13:37…14:30), nên là **giờ chạy truy vấn**, không phải giờ làm mới nguồn.
  - **Không tái dựng được as-of cho T6–T9:**
    - change log của app chỉ có từ 22/10 (1.2.13);
    - time travel của BigQuery là 168 giờ;
    - `sku_system_status` là trạng thái hiện tại.
- **Trạng thái:** `XÁC MINH MỘT PHẦN`.
- **Bằng chứng:**
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:554-571](../02_kien_truc_du_lieu/BIGQUERY.md#L554-L571);
  - `evidence\s1_csv_profile.txt` (`refresh_time` từng file);
  - `evidence\s3_backtest_join.txt`:
    - 2.356.947 khóa chung; `demand_quantity` = actual của backtest ở 99,98 %;
    - 457 khóa lệch, **mọi** khóa đều thấp hơn ở CSV, tổng −13.200 đơn vị (T10 −13.088);
    - chi tiết: sheet `Q9_ACTUAL_LECH`.
- **Diễn giải:** độ lệch khớp với giả thuyết đơn hủy hoặc chờ xác nhận bị bỏ sau 23/10, hoặc với dòng giữ của app. Chưa tách được hai khả năng.
- **Ảnh hưởng:** actual dùng chấm điểm là "hiện tại 24/10", không phải "đã biết lúc đó". Độ lệch nhỏ: 0,08 % lượng cầu tháng 10.
- **Còn thiếu:**
  - SQL của CSV;
  - đối chiếu 457 khóa với `demand_change_log` / `demand_held_lines` trên bản sao DB (không cần BigQuery).

#### B. Định nghĩa demand và nhãn

##### Câu 9. `order_qty` (nhãn) và `demand_quantity` (chấm điểm) có cùng định nghĩa, đơn vị, grain, nguồn? Có trừ hủy, hoàn, điều chỉnh không?

- **Kết luận:**
  - **Nhãn của app** = `order_qty` ← `demand_quantity` của bảng `demand_planing_lightgbm`, cộng theo `created_date × sku_code × fc_code`.
    - Không lọc `order_status`; loại dòng NULL hoặc âm; dòng trùng khóa thì cộng (SUM_ALL); dòng trùng hoàn toàn thì chặn.
    - Đơn hủy vắng mặt vì nguồn đã bỏ. Từ 1.2.13, dòng đã từng thấy được **giữ lại** (`KEEP_OBSERVED_LINES`).
    - **Trả hàng: không có xử lý nào** (không tìm thấy).
  - **Actual của backtest app** chính là `demand_daily.qty`, giống hệt định nghĩa nhãn.
  - **Actual của workbook so sánh** là `demand_quantity` của CSV (SQL chưa biết). Cùng grain và đơn vị; giá trị trùng 99,98 % khóa chung; 457 khóa thấp hơn (câu 8).
- **Trạng thái:** `XÁC MINH MỘT PHẦN`.
- **Bằng chứng:**
  - `target_mapping` lưu với run production: `order_qty` ← `demand_quantity`, `unit_price` ← `sales_price`;
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:115](../02_kien_truc_du_lieu/BIGQUERY.md#L115), [:129](../02_kien_truc_du_lieu/BIGQUERY.md#L129), [:569-571](../02_kien_truc_du_lieu/BIGQUERY.md#L569-L571), [:621-627](../02_kien_truc_du_lieu/BIGQUERY.md#L621-L627);
  - [connector.py:50](../../backend/app/bq/connector.py#L50).
- **Diễn giải:**
  - Chủ hệ thống quy định ngày 22/10: target = số lượng đặt của mọi đơn đã đặt.
  - Ý nghĩa nghiệp vụ của `demand_quantity` vẫn ghi "cần xác nhận" ([docs/02_kien_truc_du_lieu/BIGQUERY.md:368](../02_kien_truc_du_lieu/BIGQUERY.md#L368)).
- **Ảnh hưởng:** nhãn và actual gần như trùng. Nhãn của giai đoạn trước 22/10 không gồm đơn đã hủy trước lần nạp đầu.
- **Còn thiếu:** SQL CSV; xác nhận nghiệp vụ về trả hàng.

##### Câu 10. Ngày LIMIT hoặc OUT_OF_STOCK, khách có đặt được không? Demand có bị giới hạn không?

- **Kết luận:**
  - **OUT_OF_STOCK:** gần như không có đơn khi không mở bán.
    - CSV có 541 dòng (13.864 đơn vị, khoảng 0,08 % lượng cầu T6–T10) có đơn khi `total_open_hours` = 0.
    - Nguồn của app có 931 khóa (25.542 đơn vị) giờ = 0 nhưng có đơn; 619/621 dòng tương ứng là OUT_OF_STOCK trong `fact_product_sku_status`.
    - Như vậy cầu ghi nhận **bị cắt theo khả năng bán**.
  - **LIMIT:** được tính là mở bán (giờ mở bán = giờ ở trạng thái NORMAL hoặc LIMIT). Không có bằng chứng LIMIT giới hạn số lượng mỗi đơn hay mỗi khách.
  - CSV không trả lời được câu này theo trạng thái, vì `sku_system_status` là trạng thái hiện tại (câu 11).
- **Trạng thái:** `XÁC MINH MỘT PHẦN`.
- **Bằng chứng:**
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:460-463](../02_kien_truc_du_lieu/BIGQUERY.md#L460-L463), [:479-485](../02_kien_truc_du_lieu/BIGQUERY.md#L479-L485), [:493-496](../02_kien_truc_du_lieu/BIGQUERY.md#L493-L496);
  - `evidence\s1_csv_profile.txt`; sheet `Q10_DON_KHI_GIO_0` (541 dòng, đủ 13 cột nguồn).
- **Diễn giải:** định nghĩa giờ mở bán là quan sát dựng lại khớp 2.190/2.191 item-ngày, không phải tài liệu nguồn.
- **Ảnh hưởng:** ngày đóng bán làm nhãn thấp hơn cầu thật. Model và luật FALLBACK đều coi đó là "không có cầu" (câu 22).
- **Còn thiếu:** nghiệp vụ xác nhận (a) đặt trước khi hết hàng có được không, (b) LIMIT nghĩa là gì.

##### Câu 11. `sku_system_status` ghi lúc nào? Vì sao OUT_OF_STOCK mà `total_open_hours` = 24?

- **Kết luận:** **hai cột ở hai mốc thời gian khác nhau.**
  - `sku_system_status` = trạng thái **lúc chạy truy vấn**, chép vào mọi ngày:
    - 0 / 22.849 cặp có quá 1 giá trị trong 01/06–23/10;
    - giữa 13:37 và 14:24 ngày 24/10, 14 cặp (420 dòng) đổi LIMIT ↔ OUT_OF_STOCK.
  - `total_open_hours` = số giờ mở bán **của từng ngày**, thay đổi theo ngày.
  - "OUT_OF_STOCK + 24 h" = SKU đang hết hàng hôm nay nhưng đã mở bán đủ ngày trong quá khứ: 587.425 dòng (T6 185.717; T7 193.504; T8 146.554; T9 45.084; T10 16.566).
  - Đây không phải lỗi dữ liệu.
- **Trạng thái:** `ĐÃ XÁC MINH` (trên dữ liệu CSV; SQL nguồn chưa đọc được).
- **Bằng chứng:**
  - `evidence\s1_csv_profile.txt` ("pairs with >1 status value: 0");
  - `evidence\s2_old_new_status.txt` (status equal 0,999387; 14 cặp đổi);
  - cùng ngữ nghĩa trong bảng nguồn của app: [docs/02_kien_truc_du_lieu/BIGQUERY.md:426-428](../02_kien_truc_du_lieu/BIGQUERY.md#L426-L428).
- **Diễn giải:** khi so hai lần trích, giờ mở bán chỉ khác do làm tròn (câu 13), còn trạng thái đổi theo thời gian thực.
- **Ảnh hưởng:** mọi phân tích "theo trạng thái của ngày" dựa trên cột này đều sai về thời điểm.
- **Còn thiếu:** không, cho phần kết luận này.

##### Câu 12. OUT_OF_STOCK giảm từ 37 % (T6–T7) xuống 5 % (cuối T10) do vận hành thật hay do cách ghi trạng thái?

- **Kết luận:** **không phải cả hai mà là hiệu ứng của định nghĩa.**
  - Trên mọi dòng, tỷ lệ OUT_OF_STOCK **không đổi**: 52,9 % mọi tuần.
  - Đường giảm chỉ xuất hiện khi giới hạn vào các dòng **đang mở bán**: 40,4 % (01–07/06) → 39,5 % (03–09/08) → 4,1 % (19–23/10); theo ngày 6,2 % (17/10) → 2,3 % (23/10).
  - Vì trạng thái là của ngày 24/10, đường này đo "các SKU đang hết hàng hôm nay còn mở bán bao nhiêu ở mỗi ngày trong quá khứ" (51 % đầu tháng 6 → 3,5 % tuần cuối). Nói cách khác là các SKU đó **bắt đầu đóng từ khi nào**.
  - Con số 37 % không tái lập chính xác; định nghĩa gần nhất cho 40,4 % / 40,1 % (T6 / T7).
- **Trạng thái:** `XÁC MINH MỘT PHẦN`. Nguyên nhân của đường cong đã xác minh. Xu hướng hết hàng thật theo ngày chưa xác minh.
- **Bằng chứng:**
  - `evidence\oos_share_by_week.csv` (6 định nghĩa);
  - `evidence\s2_old_new_status.txt`;
  - app không dùng trạng thái ở bất cứ đâu (câu 7), nên không có thay đổi code nào của app liên quan.
- **Diễn giải:** tín hiệu theo ngày duy nhất có trong CSV là giờ mở bán. Tỷ lệ cặp-ngày mở bán: 67–70 % (T6–T7) → 36–40 % (09–20/09) → 45 % (T10). Không biết đó là do hết hàng hay do ngừng bán, vì nguồn không phân biệt.
- **Ảnh hưởng:** không được dùng "37 % → 5 %" để kết luận tình trạng hết hàng đã cải thiện.
- **Còn thiếu:** lịch sử trạng thái theo ngày (`staging_sku_status_history` / `fact_product_sku_status`). Cần truy vấn BigQuery được duyệt.

##### Câu 13. `total_open_hours` được tính thế nào?

- **Kết luận** (quan sát chỉ đọc, không phải tài liệu nguồn):
  - **Định nghĩa:** số giờ trong ngày (giờ Việt Nam) mà **item** ở trạng thái NORMAL hoặc LIMIT, theo nhật ký đổi trạng thái `staging_sku_status_history`. OUT_OF_STOCK và SUSPENDED là đóng.
  - **Trong nguồn của app** (grain item × FC × ngày):
    - app gộp về SKU × FC × ngày với trạng thái OK / MISSING / OUT_OF_RANGE / MULTI_ITEM / CONFLICT;
    - 6 khóa MULTI_ITEM dùng MAX theo quy tắc chủ hệ thống (1.2.12);
    - app chỉ lưu giờ trên **ngày có đơn**; ngày không đơn là NaN;
    - nguồn giữ giờ mở bán khoảng 7 tháng gần nhất, và đã được bổ sung ngày 20/10.
  - **Trong CSV:**
    - có giờ cho mọi ngày, kể cả cầu = 0;
    - bản cũ giữ 2 số lẻ, bản mới làm tròn về số nguyên: 1,4–3,7 % dòng đổi; giờ < 0,5 thành 0 (96 dòng T6, 291 dòng T9);
    - `demand_zero_reason` được tính **trước** khi làm tròn: 917 dòng có lý do "đủ mở bán" nhưng giờ = 0 (sheet `Q13_LY_DO_LECH_GIO`).
  - **Giờ theo lịch hay giờ thực tế đặt được:** giờ phản ánh trạng thái listing, không phải tồn thực hay giờ nhận đơn. Vẫn có đơn ở ngày giờ = 0 (câu 10).
- **Trạng thái:** `XÁC MINH MỘT PHẦN`.
- **Bằng chứng:**
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:443](../02_kien_truc_du_lieu/BIGQUERY.md#L443), [:455-463](../02_kien_truc_du_lieu/BIGQUERY.md#L455-L463), [:493-496](../02_kien_truc_du_lieu/BIGQUERY.md#L493-L496);
  - [features.py:39-41](../../backend/app/ml/features.py#L39-L41), [:109-111](../../backend/app/ml/features.py#L109-L111);
  - `evidence\s2_old_new_status.txt`.
- **Diễn giải:** không đọc được SQL dựng bảng (`INFORMATION_SCHEMA.JOBS` bị từ chối quyền, [docs/02_kien_truc_du_lieu/BIGQUERY.md:555](../02_kien_truc_du_lieu/BIGQUERY.md#L555)).
- **Ảnh hưởng:** ranh giới "mở bán" trong workbook phụ thuộc phép làm tròn của bản trích.
- **Còn thiếu:** SQL nguồn hoặc tài liệu của chủ dữ liệu.

#### C. Avg demand của hệ thống

##### Câu 14. Công thức chính xác của `avg_demand_history`?

- **Kết luận:** **chưa xác định.** Không có trong repository. Từ dữ liệu chỉ thấy:
  - bản mới = ROUND nửa lên của bản cũ (2 số lẻ) ở 100 % dòng;
  - NULL ở 108.841 dòng (bản cũ), phần lớn là SKU mới (2.095 dòng mở bán có Avg trống, sheet `LOAI_AVG_TRONG` của workbook);
  - = 0 ở 73,3 % ngày đóng bán và 28,7 % ngày mở bán;
  - đổi gần như mỗi ngày: 26,9 % cặp ngày liên tiếp có giá trị khác nhau.
  - Đã thử và loại các giả thuyết sau (khớp ≤ 0,5 % giá trị khác 0):
    - trung bình trượt 7/14/28/30/56/60/90 ngày của `demand_quantity` trong CSV, trên mọi ngày hoặc chỉ ngày mở bán;
    - gồm hoặc không gồm ngày D, trễ 2–3 ngày;
    - trung bình mũ (alpha 0,05–0,3).
- **Trạng thái:** `CHƯA XÁC MINH`.
- **Bằng chứng:** `evidence\s5_avg_formula.txt`, `evidence\s6_avg_lag_ewm.txt`, `evidence\code\`.
- **Diễn giải:** Avg có thể tính từ một số đo cầu khác, hoặc theo item / gộp FC. Chưa biết.
- **Ảnh hưởng:** không biết Avg có loại ngày hết hàng hay LIMIT, cũng không biết cửa sổ. So sánh LightGBM với Avg vì vậy chưa có cơ sở công bằng.
- **Còn thiếu:** SQL / tài liệu của Avg từ chủ hệ thống.

##### Câu 15. `avg_demand_history` trong file là số đã lưu và áp dụng tại ngày đó, hay tính lại khi trích ngày 24/10?

- **Kết luận:**
  - **Ít nhất phần trình bày được tạo khi trích:** hai lần trích cùng ngày cách nhau 47 phút lệch nhau đúng bởi `ROUND`, và `refresh_time` = giờ truy vấn.
  - Không xác định được truy vấn đọc một bảng lịch sử đã lưu theo ngày hay tính lại từ dữ liệu hiện tại.
  - Nếu tính lại, Avg sẽ phản ánh lịch sử đã bị nguồn sửa (đơn hủy bị bỏ, phạm vi sản phẩm đổi).
- **Trạng thái:** `XÁC MINH MỘT PHẦN`.
- **Bằng chứng:**
  - `evidence\s2_old_new_status.txt` (new = floor(old + 0,5) ở 100 %);
  - `evidence\s1_csv_profile.txt` (`refresh_time` từng file);
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:445](../02_kien_truc_du_lieu/BIGQUERY.md#L445), [:556-561](../02_kien_truc_du_lieu/BIGQUERY.md#L556-L561).
- **Diễn giải:** `refresh_time` giống nhau trong một file không chứng minh điều gì về giá trị đã dùng trong vận hành.
- **Ảnh hưởng:** chưa thể khẳng định phía Avg là "số hệ thống đã dùng".
- **Còn thiếu:** SQL; bảng lưu Avg theo ngày (nếu có); ảnh chụp đề xuất mua hàng thực tế của các ngày.

##### Câu 16. Công thức Avg có thay đổi trong T6–T10 không?

- **Kết luận:** **không có dữ liệu để kết luận.**
  - Repository và Git không chứa pipeline Avg.
  - Bằng chứng duy nhất về thay đổi là phép làm tròn đổi giữa hai lần trích ngày 24/10 (mức truy vấn, không phải công thức).
- **Trạng thái:** `KHÔNG CÓ DỮ LIỆU ĐỂ KẾT LUẬN`.
- **Bằng chứng:** tìm `avg_demand_history` trong toàn repository không có kết quả (repo-scout).
- **Diễn giải:** không thấy commit không có nghĩa là không đổi, vì pipeline nằm ngoài repo này.
- **Ảnh hưởng:** không biết Avg có đổi giữa các tháng hay không.
- **Còn thiếu:** lịch sử phiên bản pipeline Avg từ chủ hệ thống.

#### D. Mua hàng và ưu tiên business

##### Câu 17. Lượng mua hằng ngày được tính từ forecast như thế nào?

- **Kết luận:** **không có trong hệ thống này.**
  - App chỉ xuất dự báo theo ngày (số nguyên) và tổng 7/15 ngày (tổng các số nguyên).
  - Không có số ngày phủ, tồn an toàn, tồn hiện có, hàng đang về, PO chưa nhận, MOQ, bội số đóng gói, làm tròn mua hay giới hạn mua.
  - Có một file ngoài hệ thống `Import_stock_updated.xlsx` (Downloads, 24/10) với cột Giá vốn / Mã lô / HSD / Số lượng tồn. Mã sản phẩm (ví dụ 999900045) không phải `sku_code` MEDX, nên chưa liên kết được.
- **Trạng thái:** `KHÔNG CÓ DỮ LIỆU ĐỂ KẾT LUẬN` (quy tắc mua hàng thật).
- **Bằng chứng:**
  - [docs/04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md:32](MO-HINH-VA-CHI-SO.md#L32), [:440](MO-HINH-VA-CHI-SO.md#L440);
  - [forecast_routes.py:345-399](../../backend/app/api/forecast_routes.py#L345-L399);
  - repo-scout: không tìm thấy logic mua hàng.
- **Diễn giải:** không được trình bày một quy tắc mua giả định như quy tắc đang chạy.
- **Ảnh hưởng:** metric hiện tại không đo đúng quyết định mua.
- **Còn thiếu:** quy trình mua từ nghiệp vụ.

##### Câu 18. Lead time là bao lâu?

- **Kết luận:** không có dữ liệu lead time (theo nhà cung cấp, SKU, FC hay tuyến) trong repository hoặc nguồn đã duyệt.
- **Trạng thái:** `KHÔNG CÓ DỮ LIỆU ĐỂ KẾT LUẬN`.
- **Bằng chứng:** repo-scout (không tìm thấy); schema 17 cột của bảng nguồn ([docs/02_kien_truc_du_lieu/BIGQUERY.md:607](../02_kien_truc_du_lieu/BIGQUERY.md#L607)).
- **Ảnh hưởng:** không xác định được horizon cần tối ưu (7, 15 hay khác).
- **Còn thiếu:** dữ liệu lead time từ nghiệp vụ.

##### Câu 19. Business đánh giá chi phí thiếu hàng và dư hàng thế nào? Có rủi ro hết hạn không?

- **Kết luận:**
  - Không có tham số, tài liệu hay số liệu chi phí thiếu / dư hoặc mức phục vụ.
  - WAPE và bias đối xứng.
  - Ngưỡng quality gate **chưa được nghiệp vụ duyệt** (`approved_by_business` = false).
  - Rủi ro hết hạn: không có dữ liệu trong hệ thống. File `Import_stock_updated.xlsx` có cột HSD lô nhưng chưa liên kết được với SKU.
- **Trạng thái:** `KHÔNG CÓ DỮ LIỆU ĐỂ KẾT LUẬN`.
- **Bằng chứng:** [settings_service.py:91-97](../../backend/app/settings_service.py#L91-L97); repo-scout.
- **Ảnh hưởng:** không chọn được objective hay metric phù hợp (xem báo cáo 26/10: Tweedie so với WAPE).
- **Còn thiếu:** xác nhận nghiệp vụ (mục 6).

##### Câu 20. Có giá vốn và giá bán theo SKU không?

- **Kết luận:**
  - **Giá bán: có.** `sales_price` = đơn giá dòng đơn, đã gồm ảnh hưởng deal.
    - App tính `avg_unit_price` = Σ(giá × SL) / Σ(SL có giá) theo SKU × FC × ngày; độ phủ 99,99 %.
    - Chỉ có ở ngày có đơn. Đơn vị tiền tệ không được ghi.
  - **Giá vốn: không có** trong bảng nguồn (17 cột) và trong repository.
- **Trạng thái:** `XÁC MINH MỘT PHẦN`.
- **Bằng chứng:**
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:607](../02_kien_truc_du_lieu/BIGQUERY.md#L607), [:775-780](../02_kien_truc_du_lieu/BIGQUERY.md#L775-L780);
  - [connector.py:1245](../../backend/app/bq/connector.py#L1245);
  - `feature_decisions.price` của run production (độ phủ 0,99986).
- **Ảnh hưởng:** không tính được chi phí tồn hay giá trị thiếu hàng.
- **Còn thiếu:** nguồn giá vốn; xác nhận đơn vị tiền tệ.

#### E. Pipeline và luật FALLBACK

##### Câu 21. Vì sao số SKU–FC dùng LightGBM giảm từ 8.212 (T7) xuống 4.615 (T10)?

- **Kết luận:** **chủ yếu do luật FALLBACK đếm ngày không mở bán là ngày cầu = 0, trong lúc tỷ lệ mở bán giảm mạnh.** Không có thay đổi code hay cấu hình trong giai đoạn: một runner, một fingerprint.

  Số đo trên nhánh CAND:

  | Định nghĩa | T7 | T10 |
  |---|---:|---:|
  | ≥ 1 ngày dùng LightGBM | 8.426 | 5.854 |
  | ≥ 50 % số ngày dùng LightGBM | 7.486 | 4.468 |
  | Trung bình mỗi ngày | 7.488 | 4.562 |

  - **Hai số 8.212 / 4.615 không tái lập chính xác** với các định nghĩa trên.
  - Chuyển đổi T7 → T10 (theo phương pháp chiếm đa số ngày): trong 7.489 chuỗi LightGBM ở T7, 3.921 giữ LightGBM, **3.202 chuyển sang INTERMITTENT**, 366 sang INACTIVE.

  Tại mốc 22/10:

  | Nhóm | Số chuỗi | Phần ngày = 0 là ngày không mở bán | Ghi chú |
  |---|---:|---:|---|
  | INTERMITTENT | 9.333 | **50,8 %** (tại mốc 22/07 chỉ 14,9 %) | Nếu chỉ tính ngày mở bán, 3.072 chuỗi có tỷ lệ ngày 0 < 0,80. Đây là tính lại để phân rã, không phải đề xuất |
  | INACTIVE | 3.242 | 79,8 % | 2.365 chuỗi không mở bán ngày nào trong 60 ngày; 616 chuỗi mở bán ≥ 30 ngày mà không có đơn |

- **Trạng thái:** `XÁC MINH MỘT PHẦN`. Cơ chế đã xác minh; hai con số gốc chưa tái lập.
- **Bằng chứng:**
  - `evidence\s3_backtest_join.txt`;
  - [model.py:89-133](../../backend/app/ml/model.py#L89-L133);
  - `coverage_per_day.csv` của backtest.
- **Diễn giải:** cầu giảm thật (audit 24/10) và đóng bán cùng xảy ra. Phân rã là tương quan, không phải nhân quả.
- **Ảnh hưởng:** khi tình trạng mở bán phục hồi, chuỗi vẫn giữ fallback ít nhất cho tới khi cửa sổ 56 / 60 ngày đi qua.
- **Còn thiếu:** định nghĩa của hai số 8.212 / 4.615.

##### Câu 22. Tỷ lệ 80 % ngày không đơn (FALLBACK số 3) có tính ngày cầu = 0 do hết hàng hoặc đóng bán không?

- **Kết luận:** **có.**
  - Input là `demand_daily.qty`, chỉ gồm ngày có đơn. Ngày không có dòng đơn sau khi chuỗi bắt đầu được ghi **0**, bất kể giờ mở bán.
  - **Mẫu số** = số ngày đã biết (không phải NaN) trong 56 ngày cuối. NaN chỉ là ngày trước khi chuỗi bắt đầu, hoặc ngày cả scope không có dữ liệu (production không có ngày nào như vậy).
  - Giờ mở bán không tham gia. App cũng chỉ lưu giờ trên ngày có đơn, nên không biết ngày đóng.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [features.py:96-124](../../backend/app/ml/features.py#L96-L124);
  - [model.py:107-112](../../backend/app/ml/model.py#L107-L112), [:128-129](../../backend/app/ml/model.py#L128-L129);
  - số liệu ở câu 21.
- **Ảnh hưởng:** hết hàng kéo chuỗi sang mức phẳng hoặc 0, đúng lúc cầu bị kiềm chế.
- **Còn thiếu:** không.

##### Câu 23. Luật FALLBACK số 1 "không có đơn trong 60 ngày" có tính cả ngày đóng bán hoặc ngày không đủ giờ không?

- **Kết luận:** **có.**
  - Điều kiện: tổng cầu đã biết trong 60 ngày lịch cuối = 0 **và** tuổi chuỗi ≥ 60 ngày.
  - Ngày đóng bán và ngày mở bán thiếu giờ được tính như mọi ngày khác. Ngày thiếu dữ liệu toàn scope là NaN, được bỏ qua trong tổng (production không có).
  - Tại 22/10: 2.365 / 3.242 chuỗi INACTIVE không mở bán ngày nào trong 60 ngày; 616 chuỗi mở bán ≥ 30 ngày.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:** [model.py:113-115](../../backend/app/ml/model.py#L113-L115), [:124-125](../../backend/app/ml/model.py#L124-L125); `evidence\s3_backtest_join.txt`.
- **Ảnh hưởng:** chuỗi đóng bán lâu nhận dự báo 0, kể cả khi sắp mở lại.
- **Còn thiếu:** không.

##### Câu 24. Vì sao 2.770 SKU–FC đang mở bán không có dự báo?

- **Kết luận:** "Đang mở bán" theo workbook = cặp có ≥ 1 ngày `total_open_hours` > 0 trong 01/06–23/10 và không có trong Excel LightGBM.

  | Nhóm | Số cặp | Giải thích |
  |---|---:|---|
  | `NO_ORDER_ROW` | **2.747** | Không có dòng đơn nào trong nguồn của app từ 01/01 tới 25/10; cầu CSV 01/06–23/10 = 0. App chỉ tạo chuỗi từ dòng đơn, nên **theo thiết kế** không có dự báo, kể cả số 0 |
  | `FIRST_ORDER_AFTER_22_10` | 5 | Đơn đầu tiên 22–25/10; đã có trong run production 26/10 |
  | `CSV_DEMAND_NO_APP_SERIES` | **18** | CSV có cầu trước 23/10 (tổng 1.350 đơn vị) nhưng app không có chuỗi ở FC đó. 15/18 SKU được dự báo ở FC còn lại; 8/18 có chuỗi trong run 26/10. Nghi khác cách gán FC hoặc khác phạm vi sản phẩm giữa hai nguồn. **Chưa giải thích được** |

  - Trạng thái hiện tại của 2.770 cặp: 1.663 OUT_OF_STOCK, 577 NORMAL, 530 LIMIT.
  - Ngược lại, có 158 cặp có dự báo nhưng không có dòng CSV (57.050 đơn vị actual).
- **Trạng thái:** `XÁC MINH MỘT PHẦN` (2.752 / 2.770 đã giải thích; 18 cần kiểm tra).
- **Bằng chứng:**
  - [features.py:88-94](../../backend/app/ml/features.py#L88-L94);
  - sheet `Q24_KHONG_CO_DU_BAO` (2.770 dòng; giữ 6 cột nguồn của sheet `SKU_KHONG_CO_LGBM` cùng các cột giải thích);
  - sheet `BACKTEST_ONLY_TONG_HOP`;
  - `evidence\s4_anomalies.txt`;
  - danh sách chuỗi production: `evidence\prod_run_series_h1.csv`.
- **Ảnh hưởng:** cặp mở bán nhưng chưa có đơn không xuất hiện trong file xuất. Người mua hàng có thể không biết cặp đó tồn tại.
- **Còn thiếu:**
  - nghiệp vụ quyết định có cần dự báo cho các cặp này không;
  - kiểm tra 18 cặp trong BigQuery (cần duyệt).

##### Câu 25. Forecast được làm tròn như thế nào khi dùng thực tế?

- **Kết luận:** thứ tự xử lý:
  1. Dự báo: LightGBM trả exp(điểm thô), hoặc FALLBACK trả mức hằng.
  2. **Cắt ≥ 0.**
  3. Lưu `round(yhat, 4)`.
  4. Hiển thị và xuất: `CAST(MAX(yhat, 0) + 0,5 AS INTEGER)`, tức làm tròn **nửa lên** (0,5 → 1; giá trị âm thành 0).
  5. **Tổng 7/15 ngày = tổng các số nguyên theo ngày.**
  6. WAPE, bias và quality gate dùng `yhat` **chưa** làm tròn.
  - Excel backtest giữ 4 số lẻ. Workbook so sánh dùng `ROUND(x, 0)` của Excel: cùng kết quả với giá trị ≥ 0.
  - Số đo trên backtest:
    - 739.157 điểm 0 < y < 0,5 thành 0; 14.109 điểm đúng 0,5 thành 1;
    - FALLBACK_INTERMITTENT: 851.009 / 1.013.238 điểm (84 %) có mức < 0,5, nên công bố 0 mỗi ngày;
    - tổng sau làm tròn của nhóm này 266.264 so với 339.101 chưa làm tròn và 425.295 actual;
    - toàn bộ: bias −0,95 % trước làm tròn, −1,45 % sau làm tròn.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [model.py:190](../../backend/app/ml/model.py#L190), [:218](../../backend/app/ml/model.py#L218);
  - [pipeline.py:261](../../backend/app/ml/pipeline.py#L261);
  - [qty.py:1-20](../../backend/app/qty.py#L1-L20);
  - [forecast_routes.py:27](../../backend/app/api/forecast_routes.py#L27), [:286](../../backend/app/api/forecast_routes.py#L286), [:356](../../backend/app/api/forecast_routes.py#L356), [:373](../../backend/app/api/forecast_routes.py#L373);
  - `evidence\s3_backtest_join.txt`.
- **Ảnh hưởng:** SKU bán chậm có tổng kỳ công bố bằng 0 dù cầu thật > 0. Lợi thế của LightGBM trong workbook (MAE trên số đã làm tròn) một phần đến từ đây.
- **Còn thiếu:** nghiệp vụ chọn làm tròn trước hay sau khi cộng dồn.

#### F. Chi tiết mô hình

##### Câu 26. Bốn `roll_mean` dùng cửa sổ nào? Liệt kê 9 feature thống kê cửa sổ và các nhóm còn lại.

- **Kết luận:** mọi cửa sổ tính tại mốc t0, chỉ trên các ngày < t0.
  - **9 thống kê cửa sổ:**

    | Feature | Công thức |
    |---|---|
    | `roll_mean_7/14/28/56` | Trung bình các ngày đã biết; 0 được tính, NaN bỏ qua |
    | `roll_std_7`, `roll_std_28` | Std tổng thể; NaN nếu < 2 ngày đã biết |
    | `zero_share_28` | Ngày = 0 / ngày đã biết |
    | `days_since_last_sale` | Ngày cuối có qty > 0,5 trong 180 ngày; 181 nếu không có |
    | `roll_max_28` | Max ngày đã biết |

  - **Các nhóm còn lại:**

    | Nhóm | Feature |
    |---|---|
    | Lag | `lag_1`…`lag_7`, `lag_14`, `lag_21`, `lag_28` (theo mốc) |
    | Định danh | `sku_code`, `fc_code` (categorical), `series_age` |
    | Giá | `price_last`, `price_rel_28` |
    | Giờ mở bán | `open_hours_last`, `open_hours_mean_7` |
    | Khách hàng | `cust_mean_28`, `cust_repeat_share_28`, `cust_repeat_interval_28` |
    | Lịch ngày đích | `dow` (ISO 1..7), `dom`, `month`, `weekofyear`, `is_weekend`, `days_to_month_end` |
    | DIRECT | `horizon` |

  - **Cả 36 feature đều đi vào model production và có split.**
  - Chỉ có trong code, không vào model:
    - `disc_last`, `promo_last`, `promo_mean_7` (NO_DATA);
    - `holiday_flag` (chưa có nguồn);
    - trọng số đột biến (code thí nghiệm).
  - Gain: 4 `roll_mean` chiếm 87,3 %; 10 lag chỉ 0,47 %.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [features.py:16-19](../../backend/app/ml/features.py#L16-L19), [:187-304](../../backend/app/ml/features.py#L187-L304);
  - `reports\model-learning-investigation-20261026\evidence\model-artifact-inspection.txt`;
  - bảng đầy đủ: `reports\model-learning-investigation-20261026\BAO_CAO_DIEU_TRA.md` mục B.1.
- **Ảnh hưởng:** model gần như là "mức trung bình 28–56 ngày có hiệu chỉnh".
- **Còn thiếu:** không.

##### Câu 27. Hyperparameter thực tế?

- **Kết luận** (đọc từ file model production, khối `parameters`):

  | Nhóm | Giá trị |
  |---|---|
  | Objective | `tweedie`, `tweedie_variance_power` 1,2 |
  | Vòng học | `num_iterations` 300, `learning_rate` 0,05 |
  | Cây | `num_leaves` 31, `max_depth` −1, `min_data_in_leaf` 20, `min_sum_hessian_in_leaf` 0,001 |
  | Lấy mẫu | `feature_fraction` 0,9, `bagging_fraction` 0,9, `bagging_freq` 1 |
  | Regularization | `lambda_l1` 0, `lambda_l2` 1 |
  | Binning | `max_bin` 255 |
  | Categorical (0, 1) | `min_data_per_group` 100, `max_cat_threshold` 32, `cat_l2` 10, `cat_smooth` 10, `max_cat_to_onehot` 4 |
  | Khác | `boost_from_average` 1, `linear_tree` 0, seed 7, `deterministic`, `force_row_wise` |

  - Không có early stopping hay tập validation; 300 cây.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:** `model-artifact-inspection.txt` (báo cáo 26/10); [model.py:31-39](../../backend/app/ml/model.py#L31-L39), [:76](../../backend/app/ml/model.py#L76).
- **Ảnh hưởng:** —
- **Còn thiếu:** không.

##### Câu 28. Một model chung cho hai FC hay mỗi FC một model?

- **Kết luận:** **một model chung.**
  - Một file artifact (`MV-20261026-105345-C73F.txt`).
  - FC là feature categorical `fc_code` (BD = 0, HN = 1, trong `.json`).
  - Tập train gồm chuỗi của cả hai FC.
  - Suy luận chạy một lần trên toàn panel, không phân luồng theo FC.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [model.py:72](../../backend/app/ml/model.py#L72);
  - [pipeline.py:615-628](../../backend/app/ml/pipeline.py#L615-L628);
  - [model.py:196-219](../../backend/app/ml/model.py#L196-L219);
  - metadata model (`fc_codes`).
- **Ảnh hưởng:** `fc_code` chỉ có 59 split (0,11 % gain).
- **Còn thiếu:** không.

##### Câu 29. Quality gate hiện tại gồm những điều kiện nào?

- **Kết luận:**
  - **Điều kiện gate:**
    - `BACKTEST_RELIABLE` (≥ min(2, số fold) fold);
    - `MIN_BACKTEST_POINTS` ≥ 200;
    - `WAPE_MAX` ≤ 0,60;
    - `ABS_BIAS_MAX` ≤ 0,20;
    - `BEAT_BASELINE` chỉ khi `require_beat_baseline` (đang tắt).
  - **Metric:** WAPE và bias gộp trên mọi điểm walk-forward:
    - 12 fold × 30 ngày, bước 30; fold có < 56 ngày lịch sử bị bỏ;
    - **gộp horizon 1–30**, không tách nhóm hay horizon.
  - **Baseline:** trung bình 28 ngày. Chọn ứng viên theo WAPE gộp thấp nhất.
  - **Chính sách khi không đạt:** `PUBLISH_WITH_WARNING`, tức công bố kèm cảnh báo. `BLOCK` thì không công bố. Ngưỡng chưa được nghiệp vụ duyệt.
  - **Thay model đang dùng:** không tự động.
    - Champion/challenger train lại *cấu hình* của model đang dùng trên cùng fold, kết luận BETTER / WORSE / EQUAL.
    - Người dùng bấm promote; có ngoại lệ gate có chữ ký cho từng run.
  - Run production: WAPE 0,7896 không đạt `WAPE_MAX` → `USABLE_WITH_WARNING`; promote 26/10 lúc 11:40 với verdict `EQUAL`.
- **Trạng thái:** `ĐÃ XÁC MINH`.
- **Bằng chứng:**
  - [pipeline.py:31-52](../../backend/app/ml/pipeline.py#L31-L52), [:70-126](../../backend/app/ml/pipeline.py#L70-L126), [:194-234](../../backend/app/ml/pipeline.py#L194-L234), [:701-809](../../backend/app/ml/pipeline.py#L701-L809);
  - [settings_service.py:91-97](../../backend/app/settings_service.py#L91-L97), [:129-133](../../backend/app/settings_service.py#L129-L133);
  - `GET /api/settings`.
- **Ảnh hưởng:** gate không xét chi phí kinh doanh, horizon thật sự công bố (7/15) hay nhóm SKU.
- **Còn thiếu:** không.

##### Câu 30. Dữ liệu deal, voucher, khuyến mãi lấy từ đâu? Có lịch sử từ tháng 2 không?

- **Kết luận:** **có hỗ trợ trong app nhưng nguồn BigQuery hiện tại không có cột.**
  - App hỗ trợ các trường `promotion_flag`, `voucher_flag`, `discount_amount` (đầu vào Excel), lưu dưới dạng `promo_share`, `voucher_share`, `avg_discount_rate`.
  - Bảng BigQuery (17 cột) không có cột deal, khuyến mãi hay voucher. Mapping của run production chỉ gồm `order_id`, `order_date`, `sku_id`, `fc_id`, `order_qty`, `unit_price`, nên discount và promotion là NO_DATA (độ phủ 0,0).
  - Feature registry ghi deal / promotion / voucher là "chưa có cột nguồn".
  - Lịch sử từ tháng 2: không xác định được. Các bảng khác trong dataset chưa được kiểm tra.
- **Trạng thái:** `XÁC MINH MỘT PHẦN`. "Không có trong nguồn đã tích hợp" là đã xác minh; nguồn khác thì chưa.
- **Bằng chứng:**
  - [feature_registry.py:117-124](../../backend/app/ml/feature_registry.py#L117-L124);
  - [connector.py:1245-1248](../../backend/app/bq/connector.py#L1245-L1248);
  - [docs/02_kien_truc_du_lieu/BIGQUERY.md:607](../02_kien_truc_du_lieu/BIGQUERY.md#L607);
  - `feature_decisions` của run production.
- **Ảnh hưởng:** model không biết khuyến mãi; đột biến do deal bị học như nhiễu.
- **Còn thiếu:** chủ dữ liệu chỉ bảng nguồn và lịch sử.

---

### 4. Bảng tổng hợp 30 câu

| # | Kết luận ngắn | Trạng thái | Ảnh hưởng | Bằng chứng chính | Còn thiếu |
|---|---|---|---|---|---|
| 1 | Cùng cấu hình (fp `8468ebe66d1706f7`), khác file model | ĐÃ XÁC MINH | Trung bình | Schedule CSV, runner | — |
| 2 | Không dùng `MV-20261026`; rủi ro còn lại ở dữ liệu và phía Avg | ĐÃ XÁC MINH | Cao | Runner assert, DOI_SOAT | SQL Avg |
| 3 | Train lại mỗi thứ Hai (21 lô) | ĐÃ XÁC MINH | Cao | Schedule CSV | — |
| 4 | Nhãn 84 ngày trượt; lô 01/06: 09/03–31/05 | ĐÃ XÁC MINH | Trung bình | `features.py:403-425` | — |
| 5 | Backtest: mốc mỗi ngày, D-1; production: mốc cố định tới lần promote | ĐÃ XÁC MINH | Cao | Runner 251-263 | Chấm forecast vận hành |
| 6 | Nhiều ngày đích (h = 1..30); `horizon` là feature | ĐÃ XÁC MINH | Thấp | `features.py`, artifact | — |
| 7 | Không feature nào lấy ngày D; trạng thái không là feature | ĐÃ XÁC MINH | Trung bình | `features.py:269-289` | — |
| 8 | Bản trích phản ánh hủy tới 24/10; không tái dựng as-of được | XÁC MINH MỘT PHẦN | Trung bình | BIGQUERY 554-571; 457 khóa | SQL CSV, change log |
| 9 | Cùng định nghĩa, grain, đơn vị; 457 khóa lệch; không xử lý trả hàng | XÁC MINH MỘT PHẦN | Trung bình | `target_mapping`; s3 | SQL CSV |
| 10 | Ngày đóng gần như không có đơn → cầu bị cắt; LIMIT tính là mở | XÁC MINH MỘT PHẦN | Cao | BIGQUERY 460-496; Q10 sheet | Nghiệp vụ |
| 11 | Trạng thái = lúc trích; giờ = theo ngày | ĐÃ XÁC MINH | Cao | s1, s2 | — |
| 12 | 37 → 5 % là hiệu ứng định nghĩa | XÁC MINH MỘT PHẦN | Cao | `oos_share_by_week.csv` | Lịch sử trạng thái |
| 13 | Giờ theo trạng thái NORMAL / LIMIT; bản mới làm tròn | XÁC MINH MỘT PHẦN | Trung bình | BIGQUERY 493-496; s2 | SQL nguồn |
| 14 | Công thức Avg chưa biết; giả thuyết đơn giản bị loại | CHƯA XÁC MINH | Cao | s5, s6 | SQL Avg |
| 15 | Giá trị là đầu ra truy vấn 24/10 | XÁC MINH MỘT PHẦN | Cao | s2 | SQL Avg, bảng lưu |
| 16 | Không xác định | KHÔNG CÓ DỮ LIỆU | Trung bình | — | Lịch sử pipeline Avg |
| 17 | Không có logic mua hàng | KHÔNG CÓ DỮ LIỆU | Cao | MO-HINH 32, 440 | Quy trình mua |
| 18 | Không có lead time | KHÔNG CÓ DỮ LIỆU | Cao | — | Dữ liệu lead time |
| 19 | Không có chi phí thiếu / dư, HSD | KHÔNG CÓ DỮ LIỆU | Cao | settings quality | Nghiệp vụ |
| 20 | Có giá bán; không có giá vốn | XÁC MINH MỘT PHẦN | Trung bình | BIGQUERY 607, 775-780 | Nguồn giá vốn |
| 21 | Giảm do FALLBACK đếm ngày đóng là 0 + cầu giảm | XÁC MINH MỘT PHẦN | Cao | s3 | Định nghĩa 8.212 / 4.615 |
| 22 | Có tính ngày đóng; mẫu số = ngày đã biết | ĐÃ XÁC MINH | Cao | `model.py:107-129` | — |
| 23 | Có tính ngày đóng; 60 ngày lịch | ĐÃ XÁC MINH | Trung bình | `model.py:113-125` | — |
| 24 | 2.747 chưa từng có đơn (thiết kế); 5 đơn sau 22/10; 18 chưa giải thích | XÁC MINH MỘT PHẦN | Trung bình | Q24 sheet | 18 cặp; nghiệp vụ |
| 25 | Nửa lên, ≥ 0; tổng = tổng số nguyên | ĐÃ XÁC MINH | Cao | `qty.py`, routes | Nghiệp vụ |
| 26 | 36 feature đều vào model; 4 rolling mean 87 % gain | ĐÃ XÁC MINH | Trung bình | Artifact | — |
| 27 | Tweedie 1,2; 300 vòng; lr 0,05; 31 lá… | ĐÃ XÁC MINH | Thấp | Artifact | — |
| 28 | Một model chung, `fc_code` categorical | ĐÃ XÁC MINH | Thấp | Artifact | — |
| 29 | Gate WAPE / bias gộp, chỉ cảnh báo, promote thủ công | ĐÃ XÁC MINH | Cao | `pipeline.py` | Ngưỡng nghiệp vụ |
| 30 | Nguồn hiện tại không có deal / voucher | XÁC MINH MỘT PHẦN | Trung bình | `feature_registry`, mapping | Nguồn khác |

---

### 5. Bảng kiểm tra chéo

| Nhóm | Mâu thuẫn hoặc sai khác đã thấy | Câu | Tác động | Tin cậy |
|---|---|---|---|---|
| Backtest so với thông tin production có tại lúc dự báo | Backtest dùng mốc mỗi ngày, horizon 1, model mới mỗi tuần, dữ liệu D-1 đã ổn định. Production đổi forecast chỉ khi promote, mốc cố định, horizon tới 15, D-1 tạm thời | 1–5 | Backtest lạc quan hơn vận hành | Cao |
| Backtest so với thông tin production | Workbook lọc dòng bằng giờ mở bán của ngày D (chỉ biết sau D); Avg có thể là số tính lại | 2, 7, 15 | So sánh không phản ánh lúc ra quyết định | Trung bình |
| Target, actual, trạng thái | Actual backtest (23/10, có dòng giữ) khác CSV (24/10) ở 457 khóa, −13.200 đơn vị | 8, 9 | Nhỏ (0,08 % T10) | Cao |
| Target, actual, trạng thái | `sku_system_status` là trạng thái hiện tại, `total_open_hours` theo ngày, nên "OOS + 24 h" và "37 → 5 %" là hiệu ứng định nghĩa | 10–12 | Kết luận về hết hàng trong các phân tích trước không dùng được | Cao |
| Target, actual, trạng thái | Nhãn = đơn đặt được khi mở bán; ngày đóng ghi 0; không có trả hàng | 9, 10, 22 | Cầu bị cắt theo khả năng bán | Trung bình |
| Avg có đúng là số đã dùng | Không có công thức; giá trị do truy vấn ngày 24/10 tạo ra; không tái lập được | 14–16 | So sánh LightGBM với Avg chưa có cơ sở | Cao |
| Metric so với mua hàng | Workbook chấm MAE trên số đã làm tròn, theo SKU. App chấm WAPE trên số chưa làm tròn, gộp. Không metric nào có chi phí thiếu / dư hay lead time | 17–20, 25, 29 | "Model tốt hơn" chưa chắc mua tốt hơn | Cao |
| FALLBACK, thiếu forecast, làm tròn | Ngày đóng tính là 0 → nhiều chuỗi vào fallback; 84 % điểm intermittent công bố 0; 2.747 cặp mở bán chưa có đơn không xuất hiện; 18 cặp lệch nguồn | 21–25 | Thiếu forecast cho SKU bán chậm hoặc mới mở lại | Cao |
| Cấu hình model so với mô tả backtest | Khớp (fingerprint, 36 feature, Tweedie 1,2, 300 vòng). Tài liệu cũ lệch: [MO-HINH-VA-CHI-SO.md:439-441](MO-HINH-VA-CHI-SO.md#L439-L441) còn ghi "dự báo đệ quy" và "chưa đánh giá trên dữ liệu thật", trong khi production là DIRECT và đã backtest trên dữ liệu thật | 1, 26–29 | Tài liệu gây hiểu nhầm | Cao |

**Bất thường đã chứng minh từ dữ liệu sẵn có (8 loại):**
1. Trạng thái là ảnh chụp lúc trích (câu 11, 12).
2. 2.770 cặp mở bán không có dự báo (câu 24).
3. 18 cặp có cầu trong CSV nhưng không có chuỗi trong app (câu 24).
4. 457 khóa lệch actual (câu 8, 9).
5. 541 dòng có đơn khi giờ = 0 (câu 10).
6. 917 dòng lý do không khớp giờ do làm tròn (câu 13).
7. 158 cặp có dự báo nhưng không có trong CSV (câu 24).
8. Làm tròn từng ngày làm mất tổng của nhóm intermittent (câu 25).

---

### 6. Câu hỏi cần người dùng hoặc nghiệp vụ xác nhận

1. **SQL và bảng nguồn của 5 file CSV**: cách tính `sku_system_status`, `total_open_hours`, `avg_demand_history`, `demand_zero_reason`.
   - Quyết định câu 8, 11–16: có dùng được các cột này để đánh giá hay không.
2. **Công thức Avg, và Avg có được lưu theo ngày không** (số đã dùng để mua).
   - Quyết định so sánh LightGBM với Avg có công bằng không (câu 14–16).
3. **Khi OUT_OF_STOCK khách có đặt được không? LIMIT nghĩa là gì** (giới hạn số lượng mỗi đơn hay mỗi khách)?
   - Quyết định cầu có bị cắt không, và ngày đóng có nên loại khỏi luật FALLBACK hay khỏi phép chấm (câu 10, 22–23).
4. **Lượng mua được tính từ forecast thế nào**: số ngày phủ, tồn an toàn, tồn và hàng đang về, MOQ, quy cách, làm tròn.
   - Quyết định metric và horizon cần tối ưu (câu 17).
5. **Lead time** theo nhà cung cấp, SKU hoặc FC (câu 18).
6. **Chi phí thiếu hàng so với dư hàng, rủi ro hết hạn, mức phục vụ mục tiêu**.
   - Quyết định objective, bias chấp nhận được và ngưỡng gate (câu 19, 29).
7. **Nguồn giá vốn và đơn vị tiền tệ**, và file `Import_stock_updated.xlsx` dùng cho hệ thống nào (câu 20).
8. **Cặp SKU × FC mở bán nhưng chưa từng có đơn có cần dự báo không** (0 hay một quy tắc khác) (câu 24).
9. **Làm tròn khi mua hàng**: làm tròn từng ngày rồi cộng (hiện tại), hay cộng rồi mới làm tròn (câu 25).
10. **Nguồn deal / voucher / khuyến mãi và lịch sử từ tháng 2** (câu 30).
11. **Định nghĩa của các con số 8.212 / 4.615 và 37 % / 5 %** (câu 12, 21), để đối chiếu số chính xác.

---

### 7. Bước tiếp theo

**Có thể xác minh bằng nguồn hiện có** (chỉ đọc, không train):
- Đối chiếu 457 khóa với `demand_change_log` / `demand_held_lines` trên bản sao DB tạo bằng backup API (câu 8, 9).
- Chấm forecast đã công bố so với actual (lịch sử D+1 từ 18/10, endpoint `accuracy`) để đo độ chính xác vận hành (câu 3, 5).
- Chấm lại backtest theo WAPE chưa làm tròn và theo tổng 7/15 ngày; tách ngày mở bán và ngày đóng bán (câu 25).

**Cần dữ liệu hoặc file bổ sung:** SQL của CSV; tài liệu Avg; quy trình mua; lead time; nguồn giá vốn.

**Cần truy vấn BigQuery được duyệt** (dry-run trước, có `maximum_bytes_billed`; chưa chạy, kể cả dry-run):
- lịch sử trạng thái theo ngày `staging_sku_status_history` / `fact_product_sku_status`, 01/06–23/10 (câu 10, 12). Audit 24/10 ước tính khoảng 1,9 GB cho một truy vấn tương tự;
- 18 cặp của câu 24: so sánh FC hoặc phạm vi giữa nguồn CSV và `demand_planing_lightgbm`;
- các bảng deal / voucher, nếu chủ dữ liệu chỉ ra (câu 30).

**Cần xác nhận nghiệp vụ:** mục 6.

**Chưa nên thay đổi:** objective, luật FALLBACK, làm tròn, quality gate, model production. Lý do: cần trả lời câu 3, 4, 6, 9 của mục 6 trước.

---

### Phụ lục: file trong thư mục này

| File | Nội dung |
|---|---|
| `BAT_THUONG_30_CAU_HOI.xlsx` | README + 5 sheet: `Q24_KHONG_CO_DU_BAO` (2.770), `Q9_ACTUAL_LECH` (457), `Q10_DON_KHI_GIO_0` (541), `Q13_LY_DO_LECH_GIO` (917), `BACKTEST_ONLY_TONG_HOP` (158 cặp, tổng hợp). Sheet mức dòng giữ đủ cột nguồn, thêm `issue_id`, `issue_category`, `reason_flagged`, `source_file_or_table`, `source_record_key`, `sku_code`, `fc_code`, `created_date`, `expected_value`, `observed_value`, `reconciliation_status`, `evidence_reference`, `recommended_next_check`. Không xuất 587.425 dòng "OOS + 24 h" vì đó là ngữ nghĩa của cột, áp dụng cho mọi dòng của các cặp đang OOS |
| `evidence\s1…s6_*.txt` | Kết quả tính toán (profile CSV, so hai lần trích, ghép backtest, bất thường, giả thuyết Avg) |
| `evidence\oos_share_by_week.csv`, `status_rows_per_day.csv` | Tỷ lệ OUT_OF_STOCK theo các định nghĩa; số dòng theo trạng thái mỗi ngày |
| `evidence\prod_run_series_h1.csv` | 17.150 chuỗi của run production (`GET`, horizon 1) |
| `evidence\workbook_update_README_KET_QUA_DOI_SOAT.txt` | Nội dung 3 sheet mô tả của workbook so sánh |
| `evidence\code\` | Script chỉ đọc đã dùng (chạy bằng `python -I` trên file gốc, không ghi vào nguồn) |

## 3. Điều tra chỉ đọc: chất lượng học của LightGBM (model đang dùng `MV-20261026-105345-C73F`)

Nguồn: `reports\model-learning-investigation-20261026\BAO_CAO_DIEU_TRA.md` (worktree MAIN).

- **Ngày:** 26/10/2026, 14:58–15:15 giờ Việt Nam.
- **Trạng thái:** `PARTIAL`.
  - Câu 1, 3, 4 có bằng chứng tin cậy cao.
  - Câu 2: trả lời chắc chắn về panel, nhãn và cửa sổ. Riêng **ngày sớm nhất của bảng nguồn BigQuery** chỉ có bằng chứng mức trung bình (kiểm tra ngày 16/10, không ghi rõ có lọc ngày hay không). Mục E.1 nêu cách xác minh rẻ.
- **Phạm vi:** chỉ đọc mã nguồn, file model, `GET /api/*`, các báo cáo và artifact đã có.
- **Không làm:**
  - không sửa mã, cấu hình, SQL, DB;
  - không train, backtest, forecast hay promote;
  - không đổi lịch, không truy vấn BigQuery;
  - không commit, push hay deploy.

### 0. Đối tượng và trạng thái lúc kiểm tra

| Hạng mục | Giá trị |
|---|---|
| App đang chạy | 1.2.13, PID 11964, `/api/health` ok; `current.txt` = 1.2.13 |
| Repo | `main` @ `af835b8` (1.2.14 chỉ commit cục bộ, **chưa** deploy). Không có tiến trình release / deploy / test nào đang chạy |
| Mã ML production và mã repo | 15/15 module `backend/app/ml/*.py` của bản cài 1.2.13 **trùng từng byte** với repo. Ngoại lệ: `forecast_explainer.py` (mới ở 1.2.14, chỉ dùng để giải thích). Vì vậy số dòng trích dẫn trong repo đúng là hành vi production |
| Model đang dùng | `MV-20261026-105345-C73F`, từ training run `TRN-20261026031942-53C73F` (job `JOB-20261026031846-CE1653`, 10:19–10:53). Promote qua app lúc 11:40 → forecast run `FCR-20261026044021-330262` (mốc 26/10, dữ liệu đến 25/10, 15 ngày, 17.150 chuỗi) |
| SHA-256 file model | `367182097b39738ab529aac3ae819ef78b7a2d8a34b6622747a60c502eb076e8`, khớp `training_runs.model_sha256` |
| Cấu hình | `config_fingerprint` `8468ebe66d1706f7`, `feature_set_version` `FS-fe-1-33dded3cd98b`. Cài đặt hiện tại chỉ khác các trường do run tự quyết (giờ mở bán, discount/promotion NO_DATA, mã thứ ISO), nên lần train sau dùng cùng cấu hình |
| Trước = sau | `storage.json` SHA-256 `8D79DBDD…FDE047`; hash model; version; không có job PENDING/RUNNING. Không có gì thay đổi |

Bằng chứng gốc nằm trong `evidence\`:
- `training-run-TRN-20261026031942-53C73F.json`: kết quả `GET /api/training-runs/{id}`;
- `forecast-runs-latest10.json`;
- `data-quality-DQ-20261026031942-A3ADC4.json`;
- `model-artifact-inspection.txt`: đọc file model;
- `direct-label-calendar.txt`: lịch nhãn DIRECT, chỉ tính ngày từ cấu hình đã lưu;
- `series-concentration-backtest-20260601-20261022.txt`.

---

### A. Tóm tắt

| # | Câu hỏi | Kết luận | Tin cậy |
|---|---|---|---|
| 1 | Model có dùng lag, rolling, trend không? | **Có lag và rolling, không có trend.** 10 lag (1–7, 14, 21, 28 ngày) và 9 thống kê cửa sổ đều **ACTIVE** (có split trong 300 cây). Model là **DIRECT**: mọi lag và rolling tính tại **mốc dự báo**, không theo ngày đích. Model gần như chỉ dựa vào mức trung bình: 4 `roll_mean_*` chiếm **87,3 %** gain, cả 10 lag chỉ **0,47 %**. Không có feature trend hay ngày lễ. Discount và promotion bị loại vì nguồn không có dữ liệu | Cao |
| 2 | Dữ liệu huấn luyện bắt đầu từ ngày nào? | **Panel: 01/01/2026 → 25/10/2026** (298 ngày, ngày nào cũng có dữ liệu). **Nhãn thực sự được học: 03/08 → 25/10/2026** (84 ngày, 12 mốc cách 7 ngày). Dữ liệu cũ hơn chỉ đi vào feature (xa nhất 04/02 qua cửa sổ 180 ngày), tuổi chuỗi và phân loại fallback | Cao. Bảng nguồn bắt đầu 01/01/2026: trung bình |
| 3 | Objective là gì? | **`tweedie`, `tweedie_variance_power` 1,2** (log link). 300 vòng cố định, không early stopping, không tập validation, không trọng số mẫu, không biến đổi target. Sau dự báo chỉ cắt ≥ 0 (và làm tròn khi hiển thị). **WAPE và bias chỉ là metric đánh giá**: dùng cho backtest, chọn LightGBM hay baseline, quality gate, so với model đang dùng. Model **không** tối ưu chúng | Cao |
| 4 | Khi nào một chuỗi rơi vào FALLBACK? | Xét **từng chuỗi SKU × FC tại mốc dự báo**, theo thứ tự: (1) không có đơn trong 60 ngày và tuổi ≥ 60 ngày → `FALLBACK_INACTIVE_ZERO` = 0; (2) tuổi < 28 ngày → `FALLBACK_NEW_SERIES` = trung bình từ ngày bắt đầu; (3) tỷ lệ ngày = 0 trong 56 ngày ≥ 0,80 → `FALLBACK_INTERMITTENT` = trung bình 28 ngày; (4) còn lại → LightGBM. Run đang dùng: chỉ **4.256 / 17.150 chuỗi (24,8 %)** dùng LightGBM. Nhưng trong backtest, nhóm này chiếm **96,5 %** lượng cầu và **93,8 %** sai số tuyệt đối | Cao |

**Kết luận chung (tách bằng chứng và giả thuyết):**
- Model **có** feature cầu gần đây. Điểm yếu nằm ở chỗ khác:
  - **(đã xác nhận)** objective Tweedie học trung bình, còn WAPE theo ngày thưởng cho trung vị. Bias tổng ≈ 0 chỉ vì hai lỗi bù nhau: dư **+16,7 %** ở ngày thường và thiếu **−84 %** ở ngày đột biến (ngày đột biến: 1 % số điểm, 16,7 % lượng cầu);
  - **(đã xác nhận)** chỉ học từ 12 trạng thái của mỗi chuỗi (84 ngày nhãn), đúng lúc cầu giảm gần một nửa;
  - **(giả thuyết)** lag tính tại mốc, nên mất đồng bộ thứ trong tuần;
  - **(giả thuyết)** `sku_code` nhiều mức có thể học thuộc;
  - **(giả thuyết)** feature lịch nằm ngoài khoảng đã học;
  - **(giả thuyết)** ngày = 0 do hết hàng bị học như "không có cầu".
- Mức 0,79 của backtest trong app còn bị đẩy lên vì 50 % số điểm là horizon 16–30, trong khi production chỉ công bố 7 và 15 ngày.

---

### B. Bằng chứng kỹ thuật

#### B.1 Câu 1: feature cầu gần đây

**Nguồn đối chiếu:**
1. Feature engineering: [features.py](../../backend/app/ml/features.py).
2. Danh sách feature lúc train: `feature_config_json.features`, 36 tên, lưu cùng run.
3. Artifact production: header `feature_names`, `feature_infos`, số split và gain của 300 cây.
4. Inference: `_forecast_direct` gọi `origin_features` + `direct_extra`.
5. Test hiện có: xem báo cáo `backtest-audit-20260601-20261023\LEAKAGE_AUDIT.md` §3.

Ba nguồn (2), (3) và metadata `.json` của model trùng nhau (`features equal stored list: True`).

**Bảng feature.** Gain = phần trăm tổng gain trong file model. t0 = mốc dự báo; với DIRECT, mọi feature (trừ lịch và horizon) tính từ dữ liệu < t0.

| Feature | Nhóm | Cửa sổ / độ trễ | Có trong model production? | Có tại inference? | Bằng chứng |
|---|---|---|---|---|---|
| `sku_code` | Mã tĩnh, categorical | Thứ tự chữ cái của SKU trong panel | **ACTIVE**: 5.968 split (nhiều nhất), gain 8,89 %; khoảng 9,3 nghìn giá trị trong `feature_infos` | Có | [features.py:337-341](../../backend/app/ml/features.py#L337-L341), [model.py:72](../../backend/app/ml/model.py#L72) |
| `fc_code` | Mã tĩnh, categorical | — (BD, HN) | ACTIVE: 59 split, 0,11 % | Có | như trên |
| `series_age` | Tuổi chuỗi | t0 − ngày có dòng đầu tiên **trong panel** (bị cắt ở 01/01/2026) | ACTIVE: 90 split, 0,16 % | Có | [features.py:240](../../backend/app/ml/features.py#L240), [features.py:120](../../backend/app/ml/features.py#L120) |
| `lag_1` … `lag_7` | Lag | Y[t0−k], k = 1..7 | ACTIVE: 47/19/19/24/11/14/23 split; tổng gain 0,40 % | Có | [features.py:16](../../backend/app/ml/features.py#L16), [features.py:242-244](../../backend/app/ml/features.py#L242-L244) |
| `lag_14`, `lag_21`, `lag_28` | Lag | k = 14 / 21 / 28 | ACTIVE: gain 0,016 / 0,023 / 0,029 % | Có | như trên |
| `roll_mean_7`, `_14`, `_28`, `_56` | Trung bình trượt | Trung bình các ngày **đã biết** trong [t0−w, t0) | ACTIVE: gain **0,77 / 2,61 / 67,42 / 16,55 %** | Có | [features.py:17](../../backend/app/ml/features.py#L17), [features.py:245-247](../../backend/app/ml/features.py#L245-L247) |
| `roll_std_7`, `roll_std_28` | Độ lệch chuẩn trượt | Std tổng thể; NaN khi < 2 ngày đã biết | ACTIVE: 0,043 / 0,201 % | Có | [features.py:248-250](../../backend/app/ml/features.py#L248-L250), [features.py:228-233](../../backend/app/ml/features.py#L228-L233) |
| `zero_share_28` | Tính gián đoạn | Số ngày = 0 / số ngày đã biết, 28 ngày | ACTIVE: 0,018 % | Có | [features.py:251-253](../../backend/app/ml/features.py#L251-L253) |
| `days_since_last_sale` | Gián đoạn, độ gần | Số ngày từ ngày cuối có qty > 0,5, trong 180 ngày; 181 nếu không có | ACTIVE: 0,47 % | Có | [features.py:18](../../backend/app/ml/features.py#L18), [features.py:254-258](../../backend/app/ml/features.py#L254-L258) |
| `roll_max_28` | Max trượt | Max ngày đã biết, 28 ngày | ACTIVE: 0,091 % | Có | [features.py:259-263](../../backend/app/ml/features.py#L259-L263) |
| `price_last`, `price_rel_28` | Giá | Giá TB ngày t0−1 (forward-fill); tỷ lệ với TB 28 ngày | ACTIVE: 0,061 / 0,076 % (độ phủ 99,99 %) | Có | [features.py:269-273](../../backend/app/ml/features.py#L269-L273); `feature_decisions.price` |
| `open_hours_last`, `open_hours_mean_7` | Giờ mở bán | Giờ của t0−1 (**NaN nếu hôm đó không có dòng cầu**); TB 7 ngày đã biết | ACTIVE: 0,067 / 0,085 % | Có | [features.py:279-289](../../backend/app/ml/features.py#L279-L289), [features.py:39-41](../../backend/app/ml/features.py#L39-L41) |
| `cust_mean_28`, `cust_repeat_share_28`, `cust_repeat_interval_28` | Khách hàng | [t0−28, t0) | ACTIVE: 0,194 / 0,108 / 0,052 % (độ phủ 99,84 %) | Có | [features.py:290-302](../../backend/app/ml/features.py#L290-L302) |
| `dow`, `is_weekend` | Lịch của **ngày đích** | ISO 1 = thứ Hai … 7 | ACTIVE: 0,288 / 0,012 % | Có | [features.py:319-329](../../backend/app/ml/features.py#L319-L329) |
| `dom`, `days_to_month_end` | Lịch ngày đích | — | ACTIVE: 0,467 / 0,157 % | Có | như trên |
| `month`, `weekofyear` | Lịch ngày đích | Khoảng giá trị **lúc học: tháng 8–10, tuần ISO 32–43** | ACTIVE: 0,049 / 0,466 % | Có, nhưng ngày dự báo (tháng 10–11, tuần 44–46) **nằm ngoài khoảng đã học** | `feature_infos` trong `model-artifact-inspection.txt`; `direct-label-calendar.txt` |
| `horizon` | DIRECT | 1..30 | ACTIVE: 0,118 % | Có | [features.py:205-208](../../backend/app/ml/features.py#L205-L208), [features.py:326-329](../../backend/app/ml/features.py#L326-L329) |
| `disc_last` | Giảm giá | t−1 | **DEFINED_NOT_USED**: NO_DATA, độ phủ 0,0 | Không | `feature_decisions.discount` |
| `promo_last`, `promo_mean_7` | Khuyến mãi | t−1; 7 ngày | **DEFINED_NOT_USED**: công tắc ON nhưng NO_DATA, độ phủ 0,0 | Không | `feature_decisions.promotion` |
| `holiday_flag` | Ngày lễ | — | **DEFINED_NOT_USED**: chỉ có trong danh mục (nhóm FUTURE, "chưa có nguồn đáng tin cậy") | Không | [feature_registry.py:137-138](../../backend/app/ml/feature_registry.py#L137-L138) |
| `n_orders`, `voucher_share` | Cột đã lưu | — | Được đọc từ DB nhưng không feature nào dùng | Không | [features.py:76-130](../../backend/app/ml/features.py#L76-L130), [forecast_explainer.py:54](../../backend/app/ml/forecast_explainer.py#L54) |
| Trend (độ dốc, tỷ lệ 7/56 ngày…) | Trend | — | **Không định nghĩa.** Cây chỉ có thể kết hợp ngầm `roll_mean_7` với `roll_mean_56` | — | [features.py:187-209](../../backend/app/ml/features.py#L187-L209) |
| Số ngày có cầu | Gián đoạn | — | Không có feature riêng. Tương đương: `zero_share_28` (28 ngày), `days_since_last_sale` | — | như trên |
| ADI / CV², nhóm Syntetos-Boylan, cờ đột biến | Phân nhóm | 91 ngày | Chỉ dùng **đánh giá**, không phải input | — | [demand_patterns.py:1-26](../../backend/app/ml/demand_patterns.py#L1-L26) |
| Trọng số đột biến khi train | Trọng số | — | **DEFINED_NOT_USED**: code thí nghiệm; app gọi `train` không có `weights` | — | [model.py:47-53](../../backend/app/ml/model.py#L47-L53), `spike_weights.py:1-3` |

Không có feature nào ở trạng thái `UNKNOWN`: mọi feature của model đang dùng đều có trong file model và có split.

**Tầm quan trọng gộp theo nhóm** (gain, không phải đóng góp nhân quả; các feature tương quan chia gain cho nhau):

| Nhóm | Gain |
|---|---|
| Trung bình trượt | 87,35 % |
| `sku_code` | 8,89 % |
| Lịch | 1,44 % |
| Lag | 0,47 % |
| `days_since_last_sale` | 0,47 % |
| Khách hàng | 0,35 % |
| Std, max, tỷ lệ ngày 0 | 0,35 % |
| Tuổi chuỗi | 0,16 % |
| Giờ mở bán | 0,15 % |
| Giá | 0,14 % |
| horizon | 0,12 % |
| FC | 0,11 % |

**Lag theo mốc (DIRECT).** Trên dòng train có horizon h, ngày đích là t0 + h − 1. Vì vậy `lag_k` cách ngày đích k + h − 1 ngày.
- `lag_7` chỉ trùng thứ trong tuần với ngày đích khi h ∈ {1, 8, 15, 22, 29}.
- Với h = 30, `lag_1` là cầu 30 ngày trước ngày đích.
- Bằng chứng: [features.py:403-425](../../backend/app/ml/features.py#L403-L425), [model.py:196-219](../../backend/app/ml/model.py#L196-L219).
- Đây là cách DIRECT hoạt động, không phải lỗi. Nó có thể giải thích vì sao lag gần như không được dùng (giả thuyết).

**Ngày thiếu, ngày = 0, SKU mới** ([features.py:76-130](../../backend/app/ml/features.py#L76-L130)):

- Ngày không có dòng cầu của một chuỗi đã bắt đầu → **0**, tức "không có đơn".
  - Không phân biệt được với ngày hết hàng hoặc ngừng bán.
- Ngày trước khi chuỗi bắt đầu, hoặc ngày cả scope không có dữ liệu → **NaN**, không tính.
  - Production không có ngày nào như vậy: DQ ghi `n_days_with_data` 298 / 298.
- Giá: forward-fill. Giờ mở bán và khách hàng: không bao giờ điền, NaN là chưa biết.
- LightGBM xử lý NaN bằng nhánh missing; không có imputation, scaling hay feature selection.
- Dòng train của một chuỗi chỉ được tạo khi chuỗi đã bắt đầu trước mốc (t0 > start_idx) **và** ngày đích đã biết ([features.py:417](../../backend/app/ml/features.py#L417)).
- SKU mới < 28 ngày không đi qua model mà vào fallback NEW (B.4).

**Train và inference nhất quán:**
- Cả hai dùng cùng `features_at` / `origin_features` / `direct_extra`.
- Lúc promote, panel được dựng lại từ đúng `train_start`..`train_end` đã lưu ([demand.py:82-97](../../backend/app/data/demand.py#L82-L97)).
- Fingerprint dữ liệu và SHA của model được kiểm lại ([pipeline.py:752-762](../../backend/app/ml/pipeline.py#L752-L762)).
- Báo cáo `forecast-explainer-20261026\FINAL_REPORT.md` §5, trên bản sao DB 13:14 hôm nay, với run `FCR-20261026044021-330262`:
  - 36/36 mẫu tính lại khớp giá trị đã lưu;
  - 36/36 feature khớp;
  - lá của 300/300 cây khớp.

**Feature null, hằng hoặc giới hạn:**
- Không có feature hằng trong file model: mọi `feature_infos` đều là khoảng có độ rộng.
- `month` và `weekofyear` hẹp, nằm ngoài khoảng khi dự báo (đã nêu ở bảng).
- `open_hours_last` thiếu (NaN) mọi ngày không có đơn, theo thiết kế. Feature này vì vậy mang cả thông tin "hôm qua có đơn hay không", và không cho biết giờ mở bán của ngày = 0.
- Customer của lịch sử là số **tính ngược**: mapping chỉ có từ 23/10 (theo `LEAKAGE_AUDIT.md`).
- Chưa đo tỷ lệ NaN của từng feature tại 12 mốc huấn luyện (mục E.6).

**Rò rỉ từ tương lai.** Audit 24/10 (`backtest-audit-20260601-20261023\LEAKAGE_AUDIT.md`) kết luận:
- **PASS** cho rò rỉ trực tiếp:
  - code chỉ đọc `Y[:, :t]`, giá, giờ mở bán và khách hàng của các ngày < t;
  - 165/165 kiểm tra cấu trúc đạt;
  - test nhiễu loạn trên dữ liệu thật đạt.
- **PARTIAL** tổng thể, vì:
  - dữ liệu D-1 là phiên bản đã ổn định, không phải bản "đã biết lúc đó";
  - cấu hình được chọn qua thí nghiệm trên dữ liệu chồng lên giai đoạn đánh giá.
- Nhãn muộn nhất của mốc cuối là T−1 ([features.py:416](../../backend/app/ml/features.py#L416)).
- Đợt này không phát hiện gì mới về rò rỉ.

#### B.2 Câu 2: ngày bắt đầu dữ liệu huấn luyện

| # | Mốc | Ngày | Loại ngày | Bằng chứng | Tin cậy |
|---|---|---|---|---|---|
| 1 | Ngày sớm nhất trong bảng nguồn `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm` | **01/01/2026** theo kiểm tra chỉ đọc ngày 16/10: 8.885.547 dòng, 01/01 → 14/10/2026, 287 ngày, không thiếu ngày | Có sẵn ở nguồn | [docs/02_kien_truc_du_lieu/BIGQUERY.md:599-615](../02_kien_truc_du_lieu/BIGQUERY.md#L599-L615) | **Trung bình**: tài liệu không ghi truy vấn có lọc `>= 2026-01-01` không; bảng được dựng lại mỗi sáng. App **không bao giờ đọc** trước 01/01/2026 (read floor; validation 22/10 có `range.start` = 2026-01-01) |
| 2 | Ngày sớm nhất sau lọc (cửa sổ input) | **01/01/2026** | Trong cửa sổ | `data_policy.window_start_date` = 2026-01-01, `training_start_rule` = `WINDOW_START` ([demand.py:25-52](../../backend/app/data/demand.py#L25-L52)); DQ `min_date` 2026-01-01, `demand_rows_before_window` 0; lineage `demand_daily.min_date` 2026-01-01 | Cao |
| 3a | Ngày đầu của panel dùng để train | **01/01/2026** (`train_start`) | Được đưa vào panel | `training_runs.train_start`; [pipeline.py:450](../../backend/app/ml/pipeline.py#L450), [pipeline.py:466](../../backend/app/ml/pipeline.py#L466). `max_train_days` 730 không cắt gì (298 < 730) | Cao |
| 3b | Ngày sớm nhất **ảnh hưởng tới feature** của một dòng train | 04/02/2026 (`days_since_last_sale`, 180 ngày trước mốc 03/08). `roll_mean_56` từ 08/06; lag xa nhất 28 ngày. `series_age` và phân loại dùng từ 01/01 | Đi vào feature | `direct-label-calendar.txt`; [features.py:254](../../backend/app/ml/features.py#L254) | Cao |
| 3c | **Nhãn sớm nhất thực sự được học** | **03/08/2026** (mốc thứ 12) | Thực sự train | [features.py:403-425](../../backend/app/ml/features.py#L403-L425); cấu hình `direct_origins` 12, `direct_origin_step_days` 7; `n_rows` 5.218.927 = 304,3 dòng/chuỗi (tối đa 310) | Cao |
| 4 | Nhãn muộn nhất | **25/10/2026** (`train_end`) | Thực sự train | Mốc cuối 19/10 (feature từ dữ liệu ≤ 18/10), nhãn 19–25/10. Forecast công bố dùng mốc 26/10, dữ liệu ≤ 25/10 | Cao |
| 5a | Backtest trong app của run này | **28/02 → 25/10/2026**: 8 fold × 30 ngày; 4 fold đầu bỏ vì thiếu lịch sử; 3.796.777 điểm; span 240 ngày | Ngày dự báo / chấm, **không phải ngày train** | `backtest.config`, `backtest.notes` | Cao |
| 5b | Backtest gần nhất ngoài app | **01/06 → 22/10/2026**: 21 lô, horizon 1, train lại mỗi 7 ngày, cùng fingerprint cấu hình `8468ebe66d1706f7` | Ngày dự báo / chấm | `reports\backtest-20260601-20261022\` | Cao |
| 6 | Độ phủ | 298/298 ngày có dữ liệu; 2 FC mỗi ngày (16/10); ngày thấp bất thường 13–19/02 (Tết), 01/09; 69,3 % chuỗi-ngày bằng 0 | — | DQ `DQ-20261026031942-A3ADC4`; [docs/02_kien_truc_du_lieu/BIGQUERY.md:609-615](../02_kien_truc_du_lieu/BIGQUERY.md#L609-L615) | Cao (theo ngày). Theo chuỗi: chưa đo |

**Lịch nhãn DIRECT** (`direct-label-calendar.txt`):
- 12 mốc: 03/08, 10/08, … , 19/10. Mỗi mốc có h = 1..30 với ngày đích ≤ 25/10.
- Số mốc theo horizon: h 1–7: 12 mốc; 8–14: 11; 15–21: 10; 22–28: 9; 29–30: 8.
- Mỗi chuỗi có tối đa 310 dòng train, nhưng chỉ từ **12 vector feature khác nhau** (lịch và horizon thay đổi trong cùng một mốc).

#### B.3 Câu 3: objective và metric

| Thành phần | Giá trị thực tế | Vai trò | Nguồn bằng chứng |
|---|---|---|---|
| `objective` | `tweedie` | Hàm mất mát khi học (deviance Tweedie, log link: dự báo = e^(điểm thô)) | `params_json` của run; header file model `objective=tweedie`; [model.py:31-36](../../backend/app/ml/model.py#L31-L36); cài đặt [settings_service.py:137](../../backend/app/settings_service.py#L137) |
| `tweedie_variance_power` | 1,2 | Tham số objective, **cố định trong code**, không phải cài đặt | [model.py:35-36](../../backend/app/ml/model.py#L35-L36); file model |
| Tham số cây | `learning_rate` 0,05; 300 vòng; `num_leaves` 31; `min_data_in_leaf` 20; `feature_fraction` 0,9; `bagging_fraction` 0,9, `bagging_freq` 1; `lambda_l2` 1; `lambda_l1` 0; `max_depth` −1; `max_bin` 255; seed 7, `deterministic` | Học. Ba tham số đầu là cài đặt; `min_data_in_leaf`, `feature_fraction`, bagging, `lambda_l2` cố định trong code | [model.py:31-39](../../backend/app/ml/model.py#L31-L39); khối `parameters` trong file model |
| Categorical | `sku_code`, `fc_code`; mặc định LightGBM: `min_data_per_group` 100, `max_cat_threshold` 32, `cat_smooth` 10, `cat_l2` 10, `max_cat_to_onehot` 4 | Học | [model.py:72](../../backend/app/ml/model.py#L72); file model |
| Metric khi train hoặc validation | **Không có**: `lgb.train` không có `valid_sets`, không early stopping; số vòng cố định | — | [model.py:76](../../backend/app/ml/model.py#L76) |
| Trọng số mẫu | **Không có** (`weights=None`) | — | [model.py:47-53](../../backend/app/ml/model.py#L47-L53) |
| Biến đổi target | **Không có**: target = Σ `order_qty` hợp lệ theo SKU × FC × ngày; thang log chỉ nằm trong link của objective | — | [features.py:96-97](../../backend/app/ml/features.py#L96-L97); [pipeline.py:291](../../backend/app/ml/pipeline.py#L291) |
| Hậu xử lý | Cắt ≥ 0. Lưu `round(yhat, 4)`. Hiển thị và xuất file làm tròn nửa lên, ≥ 0. Metric tính trên `yhat` đã lưu, không làm tròn. Không cap, không hiệu chỉnh hệ số | Sau dự báo | [model.py:218](../../backend/app/ml/model.py#L218); [pipeline.py:261](../../backend/app/ml/pipeline.py#L261); [qty.py:1-20](../../backend/app/qty.py#L1-L20); `overforecast.py` (hiệu chỉnh) chỉ là code thí nghiệm |
| Metric đánh giá | WAPE = Σ\|A−F\| / ΣA; Bias = (ΣF−ΣA) / ΣA; MAE; MAPE (chỉ khi A ≥ 1) | **Đánh giá**, không tối ưu | [metrics.py:1-44](../../backend/app/ml/metrics.py#L1-L44) |
| Backtest | Walk-forward 12 fold × 30 ngày, bước 30; fold có < 56 ngày lịch sử bị bỏ; mỗi fold train lại trên dữ liệu trước mốc; **chấm cả horizon 1–30** | Đánh giá | [model.py:318-391](../../backend/app/ml/model.py#L318-L391) |
| Chọn ứng viên | **WAPE gộp thấp nhất** giữa LightGBM và baseline trung bình 28 ngày, trên cùng điểm; hòa thì giữ LightGBM. Run này: LightGBM 0,7896 so với baseline 0,8180 | Chọn | [pipeline.py:70-91](../../backend/app/ml/pipeline.py#L70-L91) |
| Quality gate | WAPE ≤ 0,60; \|bias\| ≤ 0,20; ≥ 200 điểm; ≥ 2 fold. `approved_by_business` = **false**; chính sách `PUBLISH_WITH_WARNING`, nên gate chỉ cảnh báo. Run này: WAPE_MAX **không đạt** (0,7896) → `USABLE_WITH_WARNING` | Đánh giá, cảnh báo | [pipeline.py:31-52](../../backend/app/ml/pipeline.py#L31-L52), [pipeline.py:94-126](../../backend/app/ml/pipeline.py#L94-L126); [settings_service.py:91-97](../../backend/app/settings_service.py#L91-L97) |
| Thay model đang dùng | **Không tự động.** Champion/challenger train lại **cấu hình** của model đang dùng trên cùng fold, so WAPE gộp; người dùng bấm promote. Run này: verdict `EQUAL`, delta 0 (cùng cấu hình, cùng dữ liệu) | Quyết định thủ công | [pipeline.py:194-234](../../backend/app/ml/pipeline.py#L194-L234), [pipeline.py:727-809](../../backend/app/ml/pipeline.py#L727-L809) |

**WAPE và bias là metric đánh giá, không phải objective.** Model tối ưu deviance Tweedie, tức hướng về **trung bình** có điều kiện. WAPE theo ngày đạt nhỏ nhất ở **trung vị**. Khi cầu lệch phải (nhiều ngày 0, ít ngày đột biến rất lớn), hai đích này khác nhau rõ (xem B.5).

#### B.4 Câu 4: điều kiện FALLBACK

**Hàm:** `model.classification_details` ([model.py:89-133](../../backend/app/ml/model.py#L89-L133)), gọi từ `forecast` ([model.py:160-169](../../backend/app/ml/model.py#L160-L169)). Ngưỡng lấy từ cấu hình **lưu cùng training run**.

**Pseudo-code đúng theo code** (T = ngày sau ngày cuối của panel = mốc dự báo 26/10/2026; xét từng chuỗi SKU × FC; một lần cho cả run, mọi horizon):

```
age          = T - start_idx                  # start_idx = ngày có dòng cầu đầu tiên trong panel (từ 01/01/2026)
recent_sum   = Σ qty đã biết trong 60 ngày cuối  (inactive_days = 60)
zero_share   = (#ngày = 0) / (#ngày đã biết) trong 56 ngày cuối  (2 x fallback_window_days); không có ngày đã biết -> 1,0
rate_28      = Σ / #ngày đã biết trong 28 ngày cuối  (fallback_window_days = 28)
rate_all     = Σ / #ngày đã biết từ khi chuỗi bắt đầu

IF recent_sum == 0 AND age >= 60:      FALLBACK_INACTIVE_ZERO, yhat = 0 mọi ngày       (reason INACTIVE)
ELSE IF age < 28:                      FALLBACK_NEW_SERIES,    yhat = rate_all mọi ngày (reason NEW_SERIES)
ELSE IF zero_share >= 0,80:            FALLBACK_INTERMITTENT,  yhat = rate_28 mọi ngày  (reason INTERMITTENT)
ELSE:                                  LIGHTGBM, MV-20261026-105345-C73F (DIRECT, h = 1..15)
# chỉ khi booster = None: mọi chuỗi LIGHTGBM -> FALLBACK_MODEL_UNAVAILABLE, yhat = rate_28
# mọi giá trị cắt >= 0
```

| Điều kiện thực tế | Phạm vi | Hành động | Lý do | Bằng chứng |
|---|---|---|---|---|
| Σ qty 60 ngày cuối = 0 **và** tuổi ≥ 60 ngày | Chuỗi SKU × FC, tại mốc dự báo | `FALLBACK_INACTIVE_ZERO`, dự báo 0 | Lâu không có đơn | [model.py:113-115](../../backend/app/ml/model.py#L113-L115), [model.py:124-125](../../backend/app/ml/model.py#L124-L125) |
| Tuổi < 28 ngày | Chuỗi | `FALLBACK_NEW_SERIES`, trung bình mọi ngày đã biết từ khi bắt đầu | Quá ít lịch sử cho lag | [model.py:120-122](../../backend/app/ml/model.py#L120-L122), [model.py:126-127](../../backend/app/ml/model.py#L126-L127) |
| Tỷ lệ ngày 0 trong 56 ngày ≥ 0,80 (tức ≤ 11 ngày có cầu trên 56 ngày đã biết) | Chuỗi | `FALLBACK_INTERMITTENT`, trung bình 28 ngày cuối, mức phẳng | Cầu gián đoạn | [model.py:107-112](../../backend/app/ml/model.py#L107-L112), [model.py:116-119](../../backend/app/ml/model.py#L116-L119), [model.py:128-129](../../backend/app/ml/model.py#L128-L129) |
| Không có booster | Cả run | Chuỗi LIGHTGBM → `FALLBACK_MODEL_UNAVAILABLE`, trung bình 28 ngày | Model không train được (< 100 dòng hoặc Σy ≤ 0) | [model.py:66-68](../../backend/app/ml/model.py#L66-L68), [model.py:161-167](../../backend/app/ml/model.py#L161-L167) |
| Baseline có WAPE gộp thấp hơn LightGBM, hoặc model không train được | **Cả run** | Mọi chuỗi `BASELINE_MOVING_AVERAGE` (trung bình 28 ngày) | Chọn ứng viên | [pipeline.py:78-87](../../backend/app/ml/pipeline.py#L78-L87), [model.py:237-245](../../backend/app/ml/model.py#L237-L245) |
| Lỗi feature hoặc ngoại lệ khi suy luận | Cả job | **Không có fallback theo chuỗi.** Job FAILED (`TRAINING_FAILED` / `PUBLISH_FAILED`); forecast cũ giữ nguyên. Feature NaN đi vào nhánh missing của LightGBM; thiếu mảng giờ mở bán hoặc khách hàng → `ValueError` | — | [pipeline.py:592-597](../../backend/app/ml/pipeline.py#L592-L597); [features.py:283-284](../../backend/app/ml/features.py#L283-L284), [features.py:293-294](../../backend/app/ml/features.py#L293-L294) |

**Thứ tự ưu tiên:** INACTIVE → NEW → INTERMITTENT → LightGBM. Điều kiện đầu tiên đúng thì dừng.

**Fallback dù model có thể dự báo:** **có**.
- Chuỗi INTERMITTENT và INACTIVE vẫn có dòng train: tập train không lọc theo phương pháp ([features.py:417](../../backend/app/ml/features.py#L417)).
- Nên model dự báo được cho chúng, nhưng luật thay bằng mức phẳng hoặc 0.
- Thí nghiệm C5 (20/10) đã thử cho chuỗi gián đoạn dùng LightGBM với cùng booster:
  - sàng lọc 0,7954 so với 0,7948;
  - giữ lại 0,7771 so với 0,7811;
  - trạng thái `NO_IMPROVEMENT` (`demandforecast_data_recovery_learning_readiness_20261020.md` §12.2).

**Cách ghi nhận:**
- `forecast_values.method` + `fallback_reason` cho từng ngày ([pipeline.py:259-262](../../backend/app/ml/pipeline.py#L259-L262));
- `forecast_series_meta.reason_code` + `details_json`: tuổi, tỷ lệ ngày 0, cửa sổ, tổng, rate dùng, các ngưỡng ([model.py:136-151](../../backend/app/ml/model.py#L136-L151));
- `forecast_runs.method_counts_json`.

**Run đang dùng** (`FCR-20261026044021-330262`):

| Phương pháp | Số chuỗi | Tỷ lệ |
|---|---:|---:|
| `LIGHTGBM` | 4.256 | 24,8 % |
| `FALLBACK_INTERMITTENT` | 9.047 | 52,8 % |
| `FALLBACK_INACTIVE_ZERO` | 3.667 | 21,4 % |
| `FALLBACK_NEW_SERIES` | 180 | 1,0 % |

Ba run trước có tỷ lệ tương tự (4.228–4.277 chuỗi LIGHTGBM).

Lưu ý nhỏ: báo cáo chất lượng dữ liệu đếm 8.975 chuỗi INTERMITTENT, khác 9.047.
- Lý do: [data/quality.py:98-101](../../backend/app/data/quality.py#L98-L101) chia cho 56 ngày cố định và không áp thứ tự ưu tiên.
- Số đó chỉ để tham khảo, không quyết định phương pháp.

#### B.5 Phân tích bổ sung (chỉ từ artifact đã có)

Hai nguồn số liệu:
- **(I) Backtest trong app** của run đang dùng: 8 fold, 28/02–25/10, horizon 1–30, 3.796.777 điểm, 32,62 triệu đơn vị.
- **(E) Backtest ngoài app** 01/06–22/10: horizon 1, train lại mỗi 7 ngày, cùng fingerprint cấu hình, 2.379.386 điểm, 16,72 triệu đơn vị.

**Bằng chứng xác nhận:**

1. **Bias tổng ≈ 0 che hai lỗi ngược chiều (I).**

   | Ngày | Số điểm | Phần lượng cầu | Phần sai số tuyệt đối | Bias model | WAPE model | WAPE baseline |
   |---|---:|---:|---:|---:|---:|---:|
   | Đột biến | 0,97 % | 16,7 % | 17,8 % | **−84 %** | 0,842 | 0,846 |
   | Ngày thường | 99,0 % | 83,3 % | 82,2 % | **+16,7 %** | 0,779 | 0,812 |

   - Dư khoảng +4,54 triệu ở ngày thường, thiếu khoảng −4,56 triệu ở ngày đột biến; gộp lại bias −0,05 %.
   - Đột biến theo [demand_patterns.py:84-96](../../backend/app/ml/demand_patterns.py#L84-L96): ≥ 10 và > 3 × trung vị và > trung vị + 5 × 1,4826 × MAD của chính chuỗi.
2. **WAPE tổng không che lỗi ở SKU bán chạy; SKU bán chạy tốt hơn trung bình.**

   | Nguồn | Nhóm | Phần lượng cầu | Phần sai số | WAPE | Baseline | Bias |
   |---|---|---:|---:|---:|---:|---:|
   | (E) | Top 1 % chuỗi (171) | 49,5 % | 41,0 % | 0,582 | 0,651 | −3,1 % |
   | (E) | Top 5 % (857) | 75,8 % | 64,5 % | 0,598 | 0,667 | −2,4 % |
   | (E) | 95 % chuỗi còn lại | 24,2 % | 35,5 % | 1,030 | — | — |
   | (I) | HIGH_VOLUME | 78,7 % | — | 0,701 | 0,736 | — |

   Ngay cả top 1 %, WAPE theo ngày vẫn khoảng 0,57–0,58. Bias từng chuỗi của top 1 %: p10 −17 %, p90 +18,5 %. Một số chuỗi lớn lệch có hệ thống, ví dụ `MEDX.2110dcfad25e` × BD bias −46 %.
3. **Theo horizon (I):**
   - theo ngày: 1–7: 0,734; 8–15: 0,768; 16–30: 0,829 (baseline 0,787 / 0,778 / 0,856);
   - trên tổng kỳ của từng chuỗi: 7 ngày 0,494; 15 ngày 0,464; 30 ngày 0,457.
   - Horizon 16–30 chiếm **50,4 %** số điểm của backtest app, nhưng production chỉ công bố 7 và 15 ngày (`horizons.enabled`).
4. **Theo mẫu cầu (I):**

   | Nhóm | WAPE model | WAPE baseline |
   |---|---:|---:|
   | SMOOTH | 0,515 | 0,522 |
   | ERRATIC | 0,843 | 0,885 |
   | INTERMITTENT | 1,201 | 1,244 |
   | LUMPY | 1,259 | 1,295 |

   Model hơn baseline ở mọi nhóm, nhưng chỉ 0,01–0,04.
5. **Chuỗi model so với chuỗi FALLBACK (I):**

   | Phương pháp | Phần lượng cầu | Phần sai số | WAPE | Bias |
   |---|---:|---:|---:|---:|
   | LIGHTGBM | 96,5 % | 93,8 % | 0,768 | +1,2 % |
   | INTERMITTENT | 2,3 % | 4,3 % | 1,463 | −34 % |
   | NEW | 1,0 % | 1,7 % | 1,306 | −29 % |
   | INACTIVE | 0,15 % | 0,19 % | 1,0 | −100 % |

   (E) cho kết quả tương tự: LIGHTGBM 0,672, 97 % lượng cầu. Fallback không phải đòn bẩy chính cho WAPE gộp.
6. **Forecast lưu và forecast tái lập:** khớp 36/36 mẫu (B.1).
   - Verdict `EQUAL`, delta 0 khi promote chỉ có nghĩa là **cấu hình** giống nhau: hàm so sánh train lại cấu hình, không chấm file model cũ.
   - Hàm này vì vậy không cho biết dữ liệu mới có làm model tốt hơn hay không.

**Giả thuyết cần kiểm chứng (mới có tương quan):**

7. **Độ dài lịch sử (I):**
   - fold có 58 và 88 ngày lịch sử: model thua baseline (0,766 so với 0,679; 0,880 so với 0,875);
   - từ 118 ngày trở lên: model thắng ở cả 6 fold.
   - Nhưng fold đầu chứa Tết và mùa khác, nên không tách được nguyên nhân.
   - Thí nghiệm cũ: cửa sổ bắt đầu 19/03 (C2 / O0) chỉ chênh ≤ 0,008.
8. **Cầu bị kiểm duyệt do hết hàng.** Theo audit 24/10:
   - tỷ lệ ngày = 0 tăng từ 68 % lên 83 % (tháng 6 → 9);
   - dòng có giờ mở bán < 12 h tăng từ 1,2 % lên 5,3 %.
   - Model học các ngày này như "không có cầu", vì giờ mở bán của ngày 0 là NaN.

**Chưa đủ dữ liệu:** sai số theo SKU × FC × horizon cho run đang dùng ngoài backtest (forecast vận hành so với actual từ 26/10); tách ngày hết hàng.

---

### C. Những điểm có khả năng làm model học chưa tốt

Xếp theo ảnh hưởng tiềm năng. Không mục nào đã được sửa.

| # | Điểm | Ảnh hưởng tiềm năng | Bằng chứng hiện có | Rủi ro nếu thay đổi | Cách kiểm chứng tiếp |
|---|---|---|---|---|---|
| 1 | **Objective (trung bình, Tweedie) lệch với metric (WAPE theo ngày, gần trung vị); cầu đuôi dày (đột biến)** | Cao: đột biến 17,8 % sai số; ngày thường dư 16,7 % | **Mạnh** (B.5-1). Thí nghiệm cũ: `regression_l1` có WAPE 0,718 so với 0,795 nhưng thiếu 30–48 %; hạ đột biến khi train (E13 / E14) có WAPE −0,03 đến −0,04 nhưng bias −16 % | **Cao**: hạ WAPE bằng cách dự báo thiếu có hệ thống có thể gây hết hàng. Chọn theo WAPE gộp đơn thuần ([pipeline.py:84](../../backend/app/ml/pipeline.py#L84)) sẽ thưởng hướng đó | D0 (chủ hệ thống chọn bộ metric), rồi D1 |
| 2 | **Học từ ít trạng thái:** DIRECT 12 mốc → 84 ngày nhãn (03/08–25/10), đúng giai đoạn cầu giảm khoảng 47 %; horizon 22–30 chỉ 8–9 mốc; lag theo mốc lệch thứ trong tuần | Trung bình–cao | Code và cấu hình (B.2, B.1); lag 0,47 % gain; sai số tăng 0,734 → 0,829 theo horizon. Đã thử 6 mốc (C3): **kém hơn**. **Chưa thử** nhiều mốc hơn | Thấp–trung bình: `direct_origins` (≤ 52) và `direct_origin_step_days` là cài đặt có sẵn; tốn thời gian train hơn | D2 |
| 3 | **Cầu bị kiểm duyệt** (ngày 0 vì hết hàng hoặc ngừng bán = 0) | Trung bình–cao, chưa định lượng | Trung bình (audit 24/10, B.5-8). Không feature nào phân biệt; giờ mở bán NaN ở ngày 0 | Trung bình: cần dữ liệu tồn kho / trạng thái bán và truy vấn BigQuery có duyệt (khoảng 1,9 GB theo audit) | D6 |
| 4 | **`sku_code` categorical khoảng 9,3 nghìn mức:** nhiều split nhất (5.968), gain 8,9 %, chỉ 12 trạng thái mỗi chuỗi → có thể học thuộc mức của tháng 8–10 | Chưa rõ | File model (B.1). Chưa có thí nghiệm bỏ feature này | Thấp (chỉ thí nghiệm) | D3 |
| 5 | **Feature lịch ngoài khoảng đã học** (tháng 8–10, tuần 32–43, so với khi dự báo tháng 10–11, tuần 44–46); `dom` / `weekofyear` có thể mã hóa sự kiện một lần (lễ 2/9, đơn 71.947 ngày 28/08) | Thấp–trung bình | `feature_infos`; 682 split trên `dom` + `weekofyear` | Thấp | D4 |
| 6 | **Tập train khác tập phục vụ:** khoảng 75 % chuỗi (INTERMITTENT / INACTIVE) có dòng train nhiều số 0 nhưng khi suy luận đi fallback | Chưa rõ | Code (không lọc) và số chuỗi theo phương pháp. Chưa đo tỷ lệ dòng theo nhóm tại 12 mốc (E.4) | Thấp (chỉ thí nghiệm) | D5 |
| 7 | **Lịch sử ngắn, không có mùa vụ năm, không có ngày lễ** | Trung bình, không sửa được chỉ bằng model | Cửa sổ 10 tháng; `holiday_flag` chưa có nguồn; audit: lễ 2/9 dư 35–77 % rồi thiếu 28–40 % | Trung bình (cần nguồn lịch lễ được duyệt) | E.1; thí nghiệm lễ đã đề xuất trong audit 24/10 |
| 8 | **Quy trình đánh giá làm sai lệch hình ảnh về chất lượng** (không phải lỗi học) | Trung bình đối với quyết định | (a) Backtest app chấm horizon 16–30 (50 % điểm) mà production không công bố. (b) Fold đầu chỉ có 58 ngày lịch sử. (c) `Panel.truncate` giữ chuỗi xuất hiện sau mốc fold, dự báo 0 cho chúng ([features.py:56-64](../../backend/app/ml/features.py#L56-L64); audit §4). (d) Champion/challenger so **cấu hình**, không so file model. (e) Ngưỡng gate chưa được nghiệp vụ duyệt. (f) Forecast production chỉ đổi khi promote | Thấp (chỉ báo cáo) | D7 |

---

### D. Kế hoạch kiểm chứng tiếp theo (đề xuất, chưa chạy)

**Điều kiện chung:**
- Chạy trên **bản sao** DB tạo bằng SQLite backup API (nguồn mở `mode=ro`).
- `LOCALAPPDATA` và `DF_DATA_DIR` cách ly; `DF_DISABLE_SCHEDULER=1`.
- Chạy ngoài khung lịch (D-0 08:00–18:00 mỗi 2 giờ, D-1 từ 08:00, train 08:20) và không chạy song song job production. Bộ nhớ đã từng là giới hạn.
- Không ghi model hay publish vào production.
- **Baseline đối chứng B0** = cấu hình `8468ebe66d1706f7` train lại.
- Trước hết tái lập fold 12 của backtest app: WAPE 0,8149 ± 0,01.

**Fold:**
- sàng lọc: 4 fold, mốc 29/05, 28/06, 28/07, 27/08 (trùng fold 8–11 của app);
- giữ lại: 26/09–25/10, không dùng để chọn.

**Metric** (cùng điểm với B0):
- WAPE và bias theo ngày, horizon 1–15;
- over và under;
- WAPE và bias **tổng 7 và 15 ngày** theo chuỗi;
- HIGH_VOLUME;
- ngày đột biến so với ngày thường;
- 1–7 so với 8–15.

**Điều kiện chấp nhận:** dùng lại quy tắc có hướng đã ghi trước trong báo cáo 20/10, **không đặt ngưỡng nghiệp vụ mới**.
- `IMPROVES` = WAPE thấp hơn **và** over thấp hơn **và** under không cao hơn B0, ở **cả** sàng lọc và giữ lại.
- Mọi đánh đổi bias để lấy WAPE là `TRADE_OFF`, chờ chủ hệ thống quyết định.
- Không kết quả nào dẫn tới promote.

**Chi phí:** khoảng 100–130 giây mỗi lần train (theo các lô backtest 01/06–22/10), nên khoảng 10 phút cho mỗi cấu hình × 5 fold.

| ID | Thí nghiệm | Thay đổi so với B0 | Cần sửa app? | Dữ liệu | Ghi chú |
|---|---|---|---|---|---|
| D0 | **Chọn bộ metric quyết định** (không chạy gì) | — | Không | — | Cần chủ hệ thống chọn: WAPE theo ngày, WAPE / bias tổng 7–15 ngày, hay giới hạn bias. Không có lựa chọn này thì D1 không kết luận được |
| D1 | Đuôi đột biến, trên dữ liệu và cấu hình hiện tại (có customer) | (a) E13: hạ ngày đột biến về ngưỡng khi train, như 20/10. (b) (a) + chấm thêm tổng 7 / 15 ngày | Không (script thí nghiệm) | Bản sao 25/10 | Kiểm lại kết quả 20/10 trên dữ liệu mới; ghi rõ đánh đổi bias |
| D2 | Số mốc DIRECT | `direct_origins` 24 × 7 ngày; 36 × 7; 28 × 3 ngày | Không (cài đặt có sẵn, chỉ đổi trên bản sao) | Như trên | Giả thuyết C.2. Đã biết 6 mốc kém hơn |
| D3 | Bỏ `sku_code` | Bỏ `sku_code`, giữ `fc_code` | Không (harness) | Như trên | Giả thuyết C.4 |
| D4 | Bỏ lịch dễ ngoại suy | (a) bỏ `month` + `weekofyear`; (b) (a) + bỏ `dom` | Không (harness) | Như trên | Giả thuyết C.5; giữ `dow`, `is_weekend`, `days_to_month_end` |
| D5 | Train chỉ trên chuỗi đủ điều kiện LightGBM tại từng mốc | Lọc dòng train theo `classification_details` tại t0 | Không (harness) | Như trên | Giả thuyết C.6; chấm riêng nhóm LIGHTGBM |
| D6 | Tách ngày hết hàng (chỉ đánh giá trước) | Ghép sai số với trạng thái bán / tồn theo ngày | Không | Truy vấn BigQuery chỉ đọc, dry-run, `maximum_bytes_billed`, **cần duyệt** | Giả thuyết C.3 |
| D7 | Đánh giá đúng phạm vi công bố (chỉ báo cáo) | Chấm lại điểm backtest đã lưu theo horizon 1–15 và tổng 7 / 15 ngày; chấm forecast đã công bố so với actual (lịch sử từ 18/10) | Không | Artifact sẵn có, `/api/forecast-runs/{id}/accuracy` | Không train; rẻ nhất, nên làm trước |

**Thứ tự đề xuất:**
1. D7 và D0: không train.
2. D2: chỉ đổi cài đặt.
3. D3, D4, D5: tối đa 5 cấu hình trong một lần chạy.
4. D1.
5. D6: khi có phê duyệt BigQuery.

---

### E. Những thông tin chưa xác định

| # | Thiếu | Cách lấy, chi phí thấp | Cần duyệt? |
|---|---|---|---|
| E.1 | Ngày sớm nhất **hiện nay** của bảng nguồn BigQuery (có dữ liệu trước 01/01/2026 không) | Dry-run rồi chạy `SELECT MIN(created_date), MAX(created_date), COUNT(*)` với `maximum_bytes_billed`. Bảng không phân vùng, chỉ quét 1 cột DATE: khoảng 8 byte × khoảng 9 triệu dòng, tức chưa tới 100 MB. Hoặc hỏi chủ dữ liệu | Có (BigQuery) |
| E.2 | Ngày 0 do hết hàng hay do không có cầu | Trạng thái bán / tồn theo ngày (`fact_product_sku_status` theo audit 24/10) | Có |
| E.3 | Tỷ lệ **lượng forecast đã công bố** theo phương pháp của run đang dùng | `SUM(yhat) GROUP BY method` trên bản sao DB | Không |
| E.4 | Tỷ lệ dòng train theo nhóm (LIGHTGBM / INTERMITTENT / INACTIVE) tại 12 mốc | Chạy `classification_details` trên panel cắt tại từng mốc, trên bản sao (không train) | Không |
| E.5 | Độ chính xác vận hành của forecast đã công bố (không phải backtest) | Lịch sử forecast D+1 từ 18/10 so với actual đã chốt; endpoint `accuracy` có sẵn | Không |
| E.6 | Tỷ lệ NaN của từng feature tại 12 mốc huấn luyện | `origin_features` tại 12 mốc trên bản sao (không train) | Không |
| E.7 | Ảnh hưởng nhân quả của `sku_code`, lịch, số mốc | D2–D4 | Không (bản sao) |

---

### Kết quả thực hiện

- **Thay đổi:** chỉ tạo thư mục báo cáo mới `reports\model-learning-investigation-20261026\` gồm báo cáo này và `evidence\`.
  - `reports/` nằm ngoài Git (`.gitignore:31`).
  - Script đọc bằng chứng nằm ở scratchpad của phiên. Không sửa mã, cấu hình, DB, model, lịch hay truy cập từ xa.
- **Đã chạy:**
  - `GET /api/health`, `/jobs`, `/training-runs`, `/training-runs/{id}`, `/forecast-runs`, `/forecast-runs/{id}/summary`, `/settings`, `/data-quality`;
  - đọc file model bằng `lightgbm.Booster(model_str=…)`, không ghi;
  - đọc `per_series_sku_fc.csv.gz` có sẵn.
- **Không chạy:** train, backtest, forecast, promote; truy vấn BigQuery; test (không có thay đổi mã).
- **Bằng chứng toàn vẹn (trước = sau):**
  - `storage.json` `8D79DBDD…FDE047`;
  - model `367182…6e8`;
  - app 1.2.13;
  - không có job PENDING/RUNNING;
  - `git status` sạch.
- **Trạng thái cuối: `PARTIAL`.** Câu 1, 3, 4 đủ bằng chứng. Câu 2 thiếu xác minh trực tiếp ngày sớm nhất của bảng nguồn (E.1).
- **Bước nhỏ nhất tiếp theo:**
  - chủ hệ thống chọn bộ metric quyết định (D0);
  - duyệt chạy D7 (không train) và D2 (đổi cài đặt trên bản sao);
  - nếu muốn chốt Câu 2: duyệt truy vấn E.1.
