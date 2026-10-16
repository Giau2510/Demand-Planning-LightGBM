# Thử nghiệm model độc lập trên dữ liệu BigQuery thật — 16/10/2026

Đánh giá offline, ngoài production. Không model nào được phát hành, kích hoạt hay thay thế. Không sửa quality gate,
nguồn dữ liệu, SQL, lịch chạy, DB production hay `storage.json`. Không commit, push hay tag.

## Kết luận

- **Không cấu hình nào đạt quality gate hiện tại** (WAPE ≤ 0,60 và |bias| ≤ 0,20). Ngưỡng này vẫn là ngưỡng ví dụ, chưa
  được kinh doanh duyệt. Vì vậy **chưa có model đủ điều kiện phát hành**.
- Tốt nhất về WAPE: **L5_l1** (hàm mục tiêu L1), WAPE **0,726**. Nhưng bias **−0,240**: dự báo thấp hơn thực tế ở cả
  7/7 fold, và |bias| vượt 0,20 ở 5/7 fold.
- Đáng xem xét nhất: **L7_direct** (dự báo trực tiếp nhiều kỳ, không đệ quy), WAPE **0,806**, bias **+0,069**.
  - Tốt hơn baseline 0,033 WAPE trên cùng tập điểm, thắng baseline ở 5/7 fold.
  - |bias| ≤ 0,20 ở 6/7 fold; sai số không tăng theo số ngày dự báo.
  - **C2** (direct + bỏ `sku_code` + regularization) cho kết quả gần như giống: 0,809 / +0,097.
- Model production hiện tại (R0, WAPE 1,017 / bias +0,399) kém baseline 0,839 / +0,119 và kém 15 trên 16 biến thể (L4,
  L8 chỉ tốt hơn R0 chưa tới 0,003).
- Ước lượng trung thực của quy trình "chọn cấu hình theo các fold trước" (walk-forward, không nhìn trước): WAPE
  **0,795**, bias **−0,103**. Quy trình chọn L5_l1 từ fold 7 trở đi. Bias tổng chỉ ở mức −0,10 vì fold 6 bắt buộc dùng
  R0 (bias +0,60) bù lại; riêng các fold 7–12 bias đều âm.

## 1. Trạng thái R0 và đối chiếu

- Đầu phiên thứ hai (18:06) R0 ở trạng thái **COMPLETED**: không còn tiến trình harness. Log có dòng kết thúc;
  `runs/R0_production.json` và `R0_production.npz` được ghi lúc 17:52:08.
- Phiên trước đã kết thúc trước khi lệnh bao in mã thoát, nên thiếu dòng "EXIT". R0 được **dùng lại**, không chạy lại
  (`progress/R0_production.json`: `DONE_REUSED`).
- R0 chạy 17:38–17:52, mất 800,9 giây.
  - Cùng lúc có một job huấn luyện thủ công trong app (`JOB-20261016103414-42E9B5`, 17:34–17:52, không phải do thử
    nghiệm này), nên R0 phải chia CPU và chạy chậm hơn.
  - Kết quả vẫn khớp tuyệt đối với lần chạy production `TRN-20261016095451-697A11`:

| | Lần chạy production đã lưu | R0 tái lập | Chênh lệch |
|---|---|---|---|
| WAPE | 1,0173069353426087 | 1,0173069353426087 | 0 |
| Bias | 0,3986120690842779 | 0,3986120690842779 | 0 |
| Baseline WAPE / bias | 0,8390370 / 0,1187603 | 0,8390370 / 0,1187603 | 0 |
| Số điểm | 3.353.298 | 3.353.298 | 0 |
| 7 fold (mốc, ngày cuối, số ngày train; WAPE, bias, tổng) | | | 0 ở mọi fold |

Công thức lấy từ `backend/app/ml/metrics.py`:
- WAPE = Σ|A−F| / ΣA.
- **Bias = (ΣF − ΣA) / ΣA**, tức > 0 là dự báo cao hơn thực tế.

## 2. Thiết kế và kiểm soát rò rỉ

**Dữ liệu và fold**
- Dữ liệu: bản sao DB (SQLite backup API, nguồn mở chỉ đọc) trong scratchpad
  `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\iso_exp`.
  Scope BIGQUERY, 01/01–15/10/2026, 17.137 chuỗi SKU × FC, 288 ngày. Thử nghiệm **không truy vấn BigQuery**.
- Fold giữ đúng cấu trúc production (`model.backtest`): 30 ngày, bước 30 ngày, cần tối thiểu 56 ngày lịch sử, nên đánh
  giá **7 fold** từ 20/03 đến 15/10.

**Giữ nguyên ở mọi cấu hình**
- Target, cách dựng panel, feature, quy tắc fallback, baseline (trung bình 28 ngày, giữ phẳng) và cách phân nhóm chuỗi
  đều giống production.
- Mỗi fold chỉ huấn luyện trên các ngày trước mốc dự báo, và feature chỉ dùng cột < t (`features_at`).

**Các khóa chặn rò rỉ trong thiết kế biến thể**
- Cửa sổ huấn luyện tính lùi từ mốc dự báo.
- Early stopping chọn số vòng bằng 30 ngày cuối *trước* mốc, rồi huấn luyện lại.
- Trọng số theo độ cũ tính từ mốc dự báo.
- Dự báo trực tiếp lấy feature tại mốc; lịch là lịch của ngày đích, vốn biết trước.
- Feature xu hướng tính từ dữ liệu trước t.

**Coverage:** mọi cấu hình đánh giá đúng cùng **3.353.298 điểm**, 113.172 cặp chuỗi × fold, cả 17.137/17.137 chuỗi.
Số chuỗi tăng dần từ 14.853 ở fold 6 lên 17.137 ở fold 12. Không loại SKU khó nào. Các chuỗi fallback (gián đoạn, mới,
ngừng bán) vẫn nằm trong metric tổng; khoảng 46,7 % số điểm do LightGBM dự báo, riêng L8 là 44,8 %.

**Lựa chọn cấu hình**
- Bảng xếp hạng bên dưới so tất cả cấu hình trên **cùng các fold kiểm tra**, nên chỉ mang tính khám phá.
- Danh sách 16 biến thể được chốt **sau** khi xem chẩn đoán của R0. L9 được thêm theo yêu cầu, trước khi biến thể nào
  chạy (`experiment_config.v1.json` → `experiment_config.json`).
- Ước lượng độc lập duy nhất là giao thức chọn walk-forward: `selection_walkforward.csv`.
- Cần một tập kiểm tra mới, ví dụ dữ liệu 16/10–15/11, để xác nhận ứng viên.

## 3. Danh sách cấu hình và trạng thái

Tất cả **17/17 đã chạy xong**, exit 0, không lỗi. Không cấu hình nào bị bỏ qua (NOT_RUN). Định nghĩa: `harness.py`
dòng 46–88. Thư viện LightGBM 4.7.0, seed 7, deterministic, dùng mọi luồng.

| # | Cấu hình | Thay đổi so với R0 | WAPE | Bias | WAPE fold xấu nhất | Δ WAPE so với baseline | Thời gian (s) |
|---|---|---|---|---|---|---|---|
| 1 | L5_l1 | hàm mục tiêu L1 (median) | **0,726** | −0,240 | 0,971 | −0,113 | 463 |
| 2 | L7_direct | dự báo trực tiếp 30 kỳ, không đệ quy | **0,806** | +0,069 | 1,106 | −0,033 | 637* |
| 3 | C2_direct_nosku_reg | direct + bỏ `sku_code` + regularization | 0,809 | +0,097 | 1,089 | −0,030 | 394 |
| — | **BASELINE** | trung bình 28 ngày (production) | 0,839 | +0,119 | 1,183 | 0 | — |
| 4 | C3_w90_nosku_trend_es | W90 + bỏ `sku_code` + xu hướng + early stopping | 0,865 | +0,135 | 1,163 | +0,026 | 322 |
| 5 | W30 | dòng huấn luyện 30 ngày gần nhất | 0,924 | +0,249 | 1,376 | +0,085 | 176 |
| 6 | L6_trend | thêm 4 feature xu hướng | 0,932 | +0,207 | 1,381 | +0,093 | 441 |
| 7 | L1_no_sku | bỏ feature `sku_code` | 0,950 | +0,311 | 1,627 | +0,111 | 387 |
| 8 | C1_w90_nosku_reg | W90 + bỏ `sku_code` + regularization | 0,958 | +0,323 | 1,401 | +0,119 | 185 |
| 9 | W60 | 60 ngày | 0,964 | +0,316 | 1,424 | +0,125 | 292 |
| 10 | L9_recency60 | trọng số giảm một nửa sau mỗi 60 ngày | 0,971 | +0,323 | 1,507 | +0,132 | 602 |
| 11 | L3_early_stop | early stopping (l1, val 30 ngày, tối đa 2000 vòng) | 0,972 | +0,338 | 1,397 | +0,133 | 530 |
| 12 | W90 | 90 ngày | 0,984 | +0,341 | 1,460 | +0,145 | 434 |
| 13 | W180 | 180 ngày | 0,994 | +0,369 | 1,410 | +0,155 | 513 |
| 14 | L8_fallback14 | cửa sổ fallback 14 ngày | 1,015 | +0,395 | 1,551 | +0,176 | 395 |
| 15 | L4_tweedie15 | tweedie variance power 1,5 | 1,016 | +0,411 | 1,412 | +0,177 | 501 |
| 16 | R0_production | không đổi | 1,017 | +0,399 | 1,558 | +0,178 | 801 |
| 17 | L2_regularized | num_leaves 15, min_data_in_leaf 200, lambda_l2 10, feature/bagging fraction 0,7 | 1,058 | +0,459 | 1,507 | +0,219 | 445 |

\* L7_direct có thời gian thực 11.660 s, trong đó **11.023 s là thời gian máy ở Modern Standby** (System log, Kernel-Power
506/507: 18:36:21–21:40:05), rơi trọn vào fold 12. Đã trừ phần này. Không cấu hình nào khác trùng với lúc máy ngủ.

**Kết luận về cửa sổ dữ liệu:** cửa sổ càng ngắn thì lỗi càng thấp nhưng vẫn kém baseline:
toàn bộ 1,017 > 180 ngày 0,994 > 90 ngày 0,984 > 60 ngày 0,964 > 30 ngày 0,924.
Recency weighting (0,971) chỉ cải thiện nhẹ.

**Các giả thuyết bị bác bỏ:**
- regularization mạnh hơn (L2, kém hơn R0);
- tweedie 1,5 (không đổi);
- cửa sổ fallback 14 ngày (không đổi).

## 4. Phân rã (file CSV cùng thư mục)

**Theo fold — WAPE / bias**

| Fold (mốc) | Baseline | R0 | L5_l1 | L7_direct | C2 |
|---|---|---|---|---|---|
| 6 (20/03) | 0,824 / +0,11 | 1,106 / +0,60 | 0,732 / −0,14 | 0,833 / +0,20 | 0,895 / +0,32 |
| 7 (19/04) | 0,784 / +0,13 | 0,983 / +0,45 | 0,675 / −0,21 | 0,746 / +0,05 | 0,747 / +0,10 |
| 8 (19/05) | 0,709 / −0,06 | 0,806 / +0,11 | 0,672 / −0,36 | 0,711 / −0,08 | 0,698 / −0,06 |
| 9 (18/06) | 0,796 / +0,12 | 0,855 / +0,20 | 0,681 / −0,29 | 0,756 / +0,04 | 0,747 / +0,05 |
| 10 (18/07) | 0,862 / +0,20 | 1,027 / +0,44 | 0,721 / −0,22 | 0,823 / +0,17 | 0,798 / +0,15 |
| 11 (17/08) | 1,183 / +0,42 | 1,558 / +0,92 | 0,971 / −0,06 | 1,106 / +0,28 | 1,089 / +0,24 |
| 12 (16/09) | 0,904 / +0,03 | 1,016 / +0,20 | 0,738 / −0,40 | 0,793 / −0,16 | 0,795 / −0,19 |

**Trước và sau 07/2026, theo ngày đích — WAPE / bias**

| | Baseline | R0 | L5_l1 | L7_direct | C2 |
|---|---|---|---|---|---|
| Trước 07/2026 | 0,771 / +0,07 | 0,943 / +0,36 | 0,687 / −0,24 | 0,758 / +0,05 | 0,773 / +0,12 |
| Từ 07/2026 | 0,938 / +0,19 | 1,126 / +0,45 | 0,782 / −0,25 | 0,875 / +0,09 | 0,862 / +0,07 |

Mọi phương án đều kém đi sau tháng 7, giai đoạn nhu cầu giảm khoảng một nửa. Tháng xấu nhất là 08–09/2026 (baseline
0,975 và 1,082; L7 0,922 và 0,984). Chi tiết theo tháng: `monthly_results.csv`.

**Theo FC — WAPE / bias:** BD dễ dự báo hơn HN ở mọi phương án.

| | BD | HN |
|---|---|---|
| Baseline | 0,777 / +0,11 | 0,984 / +0,14 |
| R0 | 0,913 / +0,33 | 1,261 / +0,55 |
| L5_l1 | 0,679 / −0,25 | 0,834 / −0,21 |
| L7_direct | 0,742 / +0,05 | 0,956 / +0,11 |

**Theo nhóm chuỗi** (theo quy tắc production tại mốc dự báo; giống nhau cho mọi cấu hình):

| Nhóm | Tỷ lệ số điểm / tỷ lệ nhu cầu | Ghi chú |
|---|---|---|
| LightGBM, ngày bằng 0 dưới 50 % | 25,9 % / **90,9 %** | **Quyết định WAPE.** Baseline 0,783, R0 0,959, L5 0,674, L7 0,746 |
| LightGBM, ngày bằng 0 từ 50–80 % | 20,8 % / 5,5 % | Baseline 1,368, R0 1,706, L5 1,117, L7 1,375 |
| Gián đoạn (fallback) | 38,4 % / 2,2 % | WAPE 1,505, bias −0,29 ở mọi cấu hình (trừ L8) |
| Chuỗi mới | 4,3 % / 1,1 % | 1,404 |
| Ngừng bán (dự báo 0) | 10,6 % / 0,2 % | 1,0 |

**Theo số ngày dự báo — WAPE (bias):**

| | Ngày 1–7 | Ngày 8–14 | Ngày 15–30 |
|---|---|---|---|
| R0 | 0,754 (+0,18) | 1,017 (+0,37) | 1,139 (+0,51) |
| L7_direct | 0,703 (+0,03) | 0,834 (+0,09) | 0,841 (+0,08) |

R0 xấu dần theo số ngày dự báo; L7 gần như phẳng. Điều này **xác nhận giả thuyết vòng lặp đệ quy**: giá trị kỳ vọng dự
báo được đưa ngược vào lag, tỷ lệ ngày bằng 0 và số ngày từ lần bán cuối, làm dự báo bị đẩy lên.

## 5. Chi phí tính toán

- Toàn bộ driver chạy 18:09:48–23:16:29, trong đó có 3 giờ 4 phút máy ngủ; thời gian tính thực khoảng 2 giờ 3 phút.
- Không tính R0, mỗi cấu hình trung bình 420 s (thời gian harness, không gồm máy ngủ).
  - Nhanh nhất: W30 176 s, C1 185 s, C3 322 s.
  - Dự báo trực tiếp có chi phí tương đương R0: L7 637 s, C2 394 s.
- CPU trung bình khoảng 30 %: LightGBM chỉ dùng đủ 12 luồng lúc huấn luyện. RAM trống khoảng 2,1–2,8 GB, có phân trang.
  Vì vậy các cấu hình chạy tuần tự, mỗi cấu hình một tiến trình.

## 6. Ứng viên và quality gate

| Loại | Cấu hình |
|---|---|
| Đạt gate hiện tại | **không có** |
| Tốt hơn baseline nhưng chưa đạt gate | L7_direct (0,806 / +0,069), C2 (0,809 / +0,097), L5_l1 (0,726 / −0,240; bias vượt ngưỡng) |
| Không cải thiện so với baseline | 13 cấu hình còn lại (gồm R0) |

**Đề xuất cho người xem xét, không kích hoạt:** L7_direct, có thể kèm C2. Đây là cách cải thiện có bias thấp và ổn định
theo số ngày dự báo. L5_l1 thì WAPE thấp nhất nhưng thiếu khoảng 24 % tổng nhu cầu một cách có hệ thống, có rủi ro thiếu
hàng nếu dùng để đặt hàng.

## 7. Hướng thử nghiệm tiếp theo

1. Kiểm tra độc lập trên dữ liệu mới, khi có 16/10–15/11, cho L7, C2 và L5, không chỉnh thêm.
2. Kết hợp dự báo trực tiếp với hàm mục tiêu L1 hoặc quantile 0,5–0,6 và hiệu chỉnh bias trên validation trước mốc. Mục
   tiêu: giữ WAPE của L5 nhưng đưa |bias| ≤ 0,20.
3. Thống nhất với kinh doanh về ngưỡng gate và cấp đánh giá. WAPE ≤ 0,60 ở cấp ngày × SKU × FC với dữ liệu thưa có thể
   không khả thi; có thể cân nhắc đánh giá theo tuần hoặc theo nhóm.
4. Xác nhận nguyên nhân nhu cầu giảm khoảng 50 % từ tháng 7, và giá trị ngoại lai 71.947.

## 8. Production không bị thay đổi bởi thử nghiệm này

Bằng chứng chỉ đọc:
- Fingerprint nội dung DB thật (`prod_fingerprint.py`) lúc 18:12 và lúc 23:2x **giống hệt**: training_runs,
  forecast_runs, giá trị dự báo theo lần chạy, demand theo nguồn, settings đã lưu, schema.
- Các thứ không đổi:
  - model file;
  - `storage.json` `8D79DBDD…`;
  - backup, checkpoint, config;
  - các bản cài, `current.txt` 1.1.9;
  - Git HEAD `72d7671`.
- App 1.1.9: health ok. Nguồn BIGQUERY, chế độ sản xuất bật.
- Quality gate vẫn 0,60 / 0,20 (chưa duyệt). SQL D-0 chưa có phiên bản active; history ở chế độ TABLE, `SUM_ALL`.

**Thay đổi trên DB thật trong khoảng 17:34–17:58 (trước khi bắt đầu giám sát), không do thử nghiệm này.** Thử nghiệm
chỉ đọc bản sao trong scratchpad, và trong phiên này không gọi API ghi nào. Audit log ghi:
- 17:34:14: job huấn luyện **MANUAL** `JOB-20261016103414-42E9B5` → `TRN-20261016103616-3FCDDB` bị REJECTED, cùng kết
  quả 1,0173 / 0,3986.
- 17:57:02: đổi trên giao diện (UI): D-1 bắt đầu dò tín hiệu lúc **03:00** (trước là 01:00).
- 17:57:29: đổi trên giao diện (UI): lịch huấn luyện **09:00** (trước là 07:00).

Trạng thái lịch hiện tại: D-0 OFF, D-1 OFF, huấn luyện ON lúc 09:00.

## 9. File

**Tạo trong `experiments/model_tuning_20261016/`** (Git: chỉ có thư mục mới `experiments/` chưa được track; không file
nào khác của repo bị sửa):
- Mã:
  - `harness.py`;
  - `run_all.py` (driver chạy tiếp được, mỗi cấu hình một tiến trình);
  - `analyze.py`.
- Cấu hình: `experiment_config.json` (17 cấu hình), `experiment_config.v1.json` (bản 16 cấu hình ban đầu).
- Kết quả:
  - `ranking.csv`, `baseline_results.csv`, `fold_results.csv`;
  - `window_comparison.csv`, `lgbm_comparison.csv`;
  - `monthly_results.csv`, `period_results.csv`, `fc_results.csv`;
  - `segment_analysis.csv`, `horizon_results.csv`;
  - `selection_walkforward.csv`;
  - `experiment_summary.md`.
- Checkpoint và log: `runs/*.json` (17), `progress/*.json` (17), `logs/*.log` (17 cấu hình + log driver).
- Model: **không lưu** file model của thử nghiệm. Có thể tái lập từng model bằng
  `harness.py run <tên>`, seed 7, deterministic.

**Ngoài repo (scratchpad tạm, 97 MB):**
- Mảng điểm cho phân tích:
  `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\exp_points`
- Bản sao DB:
  `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\iso_exp`

**Tái lập** (đặt `EXP_DB`, `EXP_POINTS`, `DF_DATA_DIR`, `LOCALAPPDATA` trỏ vào scratchpad):
`.venv\Scripts\python.exe experiments\model_tuning_20261016\run_all.py <tên…>`; cấu hình đã có kết quả sẽ được bỏ qua.
Sau đó chạy `analyze.py`.
