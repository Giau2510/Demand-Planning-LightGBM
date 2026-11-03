# Backtest đăng ký trước v2 (26→27/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\backtest-prereg-v2-20261027\README.md` (MAIN) | 27/10/2026 | 11442 | `664D907A2F230F9437FF01FAA28DD41B2B4365DDAA253DB69318A9FA70F4C1F4` |
| 2 | `reports\backtest-prereg-v2-20261027\PREREGISTRATION.md` (MAIN) | 27/10/2026 | 4224 | `50DBB8F3C28C576CAD8D4FA5F97E05007C5BB4DEB840D099D5BC8FF526E8BAE1` |
| 3 | `reports\backtest-prereg-v2-20261027\data_checks.md` (MAIN) | 27/10/2026 | 3586 | `6A8E1A9E3035A538C2469BA7F02660D18DEDA97C155F3172DF32B5DC269AB2D2` |
| 4 | `reports\backtest-prereg-v2-20261027\leakage_summary.md` (MAIN) | 27/10/2026 | 1095 | `43A3642B3C2FB11DAF5C83FFEEA53D1E83FBAB4691A5BC8E56CDF4E1D1BA97FC` |

## 1. Backtest đăng ký trước v2 (26→27/10/2026)

Nguồn: `reports\backtest-prereg-v2-20261027\README.md` (worktree MAIN).

### Đăng ký trước

- `PREREGISTRATION.md`: chép nguyên văn nội dung đăng ký (UTF-8 không BOM, xuống dòng LF, 4.224 byte, 25 dòng, có
  ký tự xuống dòng cuối file).
- **SHA-256 `50DBB8F3C28C576CAD8D4FA5F97E05007C5BB4DEB840D099D5BC8FF526E8BAE1`**, ghi lúc **2026-10-27 00:19:49** (giờ VN).
- File được đặt thuộc tính chỉ đọc ngay sau khi tính SHA và không sửa về sau.

(Các phần dưới được bổ sung trong lúc chạy.)

### Lệnh chạy chính xác

Môi trường (PowerShell):

```
$bt = '<scratchpad>\bt'                       # thư mục dữ liệu của bản sao DB backtest
$env:DF_DATA_DIR = $bt
$env:LOCALAPPDATA = "$bt\L"
$env:DF_DISABLE_SCHEDULER = '1'
$env:PYTHONPATH = 'D:\Buymed\Lightgbm AI\backend'      # code app: chỉ import
```

Python: `D:\Buymed\Lightgbm AI\.venv\Scripts\python.exe` (Python 3.14.7, LightGBM 4.7.0, numpy 2.5.4, pandas 3.0.6;
giống runtime đã cài của 1.2.13). Code app không đổi về mô hình so với commit 1b00c42 của backtest cũ (chỉ thêm
explainer và số phiên bản).

```
python -X utf8 code\bq_openhours.py --out . --stage columns       # bước 1.1
python -X utf8 code\bq_openhours.py --out . --stage export        # bước 1.2
python -X utf8 -I code\data_checks.py . <bt>\db\app.db            # bước 1.3
python -X utf8 code\prereg_runner.py --out . --mode smoke         # bước 3 (chạy thử + tái lập + rò rỉ)
python -X utf8 code\prereg_runner.py --out . --mode run --phases A,B,C   # bước 4: A = V0, V1; B = V2, V3; C = V4
python -X utf8 -I code\assemble.py .                              # bước 5
```

### Bước 1: bảng giờ mở bán

Chi tiết: `data_checks.md`.

- Xuất 18.481.410 dòng: lưới đầy đủ 50.634 cặp SKU × FC × 365 ngày.
- 2 / 17.140 cặp demand không có trong bảng.
- Khớp 99,996 % với `open_hours` của `demand_daily`.
- **V2, V3 không bị đánh dấu** "dữ liệu giờ mở bán chưa đạt".

### Bước 2: runner

| File | Vai trò | SHA-256 |
|---|---|---|
| `code/backtest_runner_original.py` | bản sao **không sửa** của runner cũ | `D8DE6DAB…AE60` (= `runner_sha256` của backtest cũ) |
| `code/prereg_runner.py` | runner của đợt này | `14396CB161CA1983513EBF73997A4F3C6CB9BDC3320D51B9A859A263C41FEE4C` |

`prereg_runner.py` import dữ liệu, cấu hình CAND, panel, bộ chặn bộ nhớ và kiểm tra rò rỉ T1–T3 từ runner gốc. Phần
cài đặt riêng của từng biến thể:
- **V0:** `model.train` / `model.forecast` của app, không đổi.
- **V1, V4:** lặp lại đúng `model.train`, thêm `weight = where(X[:, horizon] <= 7, 3.0, 1.0)` vào `lgb.Dataset`. V4 thêm
  `direct_origins = 24` (fingerprint cấu hình `fe455d71bbcd9205`).
- **V2:** panel che. Y = NaN trên ngày đóng (giờ = 0 và không có đơn) và ngày không có dòng giờ mà không có đơn.
  `p.hours` lấy từ `openhours.parquet`, chỉ các ngày < D. FALLBACK dùng `model.classify_series` trên panel CHƯA che.
- **V3:** dùng **chính model V2** (huấn luyện giống hệt; đã chứng minh ở bước 3: huấn luyện lại cho model trùng từng byte).
  `model_id` của V3 là `V2_<mốc>`. FALLBACK theo luật đăng ký, chỉ đếm ngày mở bán, thêm mã `FALLBACK_REOPEN`.

**Cách hiểu đã dùng.**
- "Có đơn" = demand > 0. Bản sao không có dòng qty ≤ 0, nên điều này tương đương "có dòng demand".
- Ngày không có dòng giờ nhưng **có** đơn là ngày mở bán theo định nghĩa (dùng "HOẶC"); giờ của ngày đó để NaN.
- Ngày được đếm cho luật V3 tính từ ngày bắt đầu chuỗi (đơn đầu tiên trong panel) và bỏ các ngày cả phạm vi không có dữ
  liệu, giống panel của app.

### Bước 3: chạy thử và tái lập (01–03/06, mốc 01/06)

**Tái lập: ĐẠT.** V0 h = 1 so với `cand_d1` của backtest cũ (`forecasts/batch_01_2026-06-01.csv.gz`):
- khớp 46.458 / 46.458 dòng, không thiếu khóa ở bên nào;
- **sai khác lớn nhất 0,0**;
- phương pháp trùng 100 %.

**Rò rỉ:**
- T1–T3 của runner cũ: đạt.
- T4 mới (V2 / V3): đổi 583.814 dòng demand và 2.433.880 ô giờ mở bán từ ngày D trở đi, model và dự báo giống hệt.
- T5 (đối chứng âm, đổi giờ của D-1): 2.461 chuỗi đổi dự báo.

**Tính tất định:** huấn luyện V2 lại thì model trùng từng byte với file đã lưu.

**Ước tính:** từ lô 1. Các lô sau có nhiều dữ liệu hơn nên chậm hơn và tốn RAM hơn.

| Pha | Biến thể | Huấn luyện / model | Dự báo / ngày | RAM đỉnh khi huấn luyện | Ước tính 21 lô |
|---|---|---|---|---|---|
| A | V0, V1 | 81 s; 4,52 triệu dòng, 12 mốc | 2,5 s cho cả hai | 1,95–2,0 GB | khoảng 70–110 phút |
| B | V2 (+ V3) | 71 s; 3,86 triệu dòng | 2,7 s | 1,95 GB | khoảng 35–60 phút |
| C | V4 | 146 s; 7,54 triệu dòng, 20 mốc (lô 1 chỉ đủ 20 trên 24 mốc vì dữ liệu từ 01/01) | 2,2 s | 2,65 GB | khoảng 60–110 phút |

Nạp dữ liệu mất 89 s. Kiểm tra rò rỉ và tính tất định mất 328 s.

### Bước 4: chạy đầy đủ (27/10 01:06 → 03:57:43, exit 0, không tạm dừng, không chạy lại lô nào)

21 lô × 5 biến thể = 105 lô, **tất cả DONE**. Không có lỗi thiếu RAM: V4 chạy đủ, không phải bỏ.

| Pha | Biến thể | Thời gian thực | Tổng huấn luyện | RAM đỉnh khi huấn luyện | Số dòng huấn luyện lớn nhất | Số mốc |
|---|---|---|---|---|---|---|
| A | V0 | 01:08:07 → 02:19:36 (71,5 phút, chung với V1) | 1.879 s | 2.380 MB | 5.203.026 | 12 |
| A | V1 | (như trên) | 1.862 s | 2.486 MB | 5.203.026 | 12 |
| B | V2 | 02:19:36 → 02:52:59 (33,4 phút, chung với V3) | 1.441 s | 2.120 MB | 4.091.809 | 12 |
| B | V3 | (như trên) | dùng model V2, không huấn luyện riêng; `train_log.csv` lặp lại số của V2 | | | |
| C | V4 | 02:52:59 → 03:57:40 (64,7 phút) | 3.414 s | 3.592 MB | 10.851.756 | 20–24 (Đ2) |

Nạp dữ liệu: 01:06 → 01:08:07. `open_hours_warning` của V2 là OK ở cả 21 lô: 2 cặp thiếu, ≤ 0,0001 % demand.

**Số chuỗi theo phương pháp** (cộng mọi ngày D, `method_counts.csv`):
- V0, V1, V2, V4 giống nhau: LIGHTGBM 980.362, INTERMITTENT 1.013.238, INACTIVE_ZERO 337.090, NEW_SERIES 48.696. V2 phân
  loại trên panel chưa che, đúng như đăng ký.
- V3: LIGHTGBM 1.087.294, INTERMITTENT 790.195, REOPEN 347.874, INACTIVE_ZERO 97.421, NEW_SERIES 56.602.

### Bước 5: kết quả

| File | Nội dung |
|---|---|
| `forecast_<V>_2026-MM.csv` (25 file) | V0–V4 × tháng 06–10; cột sku_code, fc_code, forecast_date, target_date, horizon, forecast_qty (4 chữ số thập phân, không làm tròn), method_code, model_id |
| `feature_gain_<V>.csv` | gain và split_count theo model (V3 = model V2) |
| `train_log.csv` | 105 dòng, đúng các cột đăng ký |
| `method_counts.csv` | số chuỗi theo biến thể × ngày D × phương pháp |
| `leakage_summary.md` | **830 / 830 kiểm tra đạt**: 825 kiểm tra theo lô / ngày + T1–T5 của bước 3 |
| `data_checks.md`, `data_checks_1_3.json`, `BAT_THUONG_GIO_MO_BAN.xlsx` | bước 1 |
| `self_check.json` | tự kiểm tra cuối |
| `parts/`, `checkpoints/`, `models/`, `smoke/` | file từng lô (có SHA trong checkpoint), model đã lưu, chạy thử |

**Tự kiểm tra cuối: ĐẠT cho cả 5 biến thể.** Mỗi biến thể có:
- 4.758.772 dòng, đủ 144 / 144 ngày D (01/06–22/10);
- h = 1 và h = 2 ở mọi ngày, cùng số chuỗi;
- 0 giá trị NaN, 0 giá trị âm.

**Biến thể chưa xong:** không có.

**Chưa chấm điểm.** Đợt này không chấm điểm so với Avg hay so với thực tế, đúng như đề bài. Việc chấm do Claude làm độc lập.

**SHA của bản sao DB sau khi chạy:** `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073`, ghi lần cuối 23/10
10:32:18. Giống hệt trước khi chạy, nên đợt này không ghi gì vào bản sao.

| Danh tính | SHA-256 |
|---|---|
| `PREREGISTRATION.md` | `50DBB8F3C28C576CAD8D4FA5F97E05007C5BB4DEB840D099D5BC8FF526E8BAE1` |
| `code/prereg_runner.py` | `14396CB161CA1983513EBF73997A4F3C6CB9BDC3320D51B9A859A263C41FEE4C` |
| `openhours.parquet` | `B3D3AE18164A3D367E3B766828CD0B03F043229A900CEACD2F1A1D7C8497E0BC` |
| Bản sao DB | `C7A663BE…F073` (xem Đ1) |

### Điểm khác giả định

#### Đ1. SHA-256 của bản sao DB (ghi nhận 27/10 00:35, trước mọi lần chạy)

| Mục | Kết quả |
|---|---|
| Bản sao | `scratchpad\bt\db\app.db`, đúng file mà backtest cũ dùng (`run_config.json` của backtest cũ ghi đường dẫn này) |
| Đăng ký | SHA `8ABD356D…`: SHA lúc tạo bản sao, 23/10 10:20 |
| Hiện tại | SHA `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073`, 2.653.442.048 byte (lớn hơn 4.096 byte, tức một trang), ghi lần cuối 23/10 10:32:18 |

**Nguyên nhân.** `phase_a_check.py` của backtest cũ chạy lúc 23/10 10:30–10:32. Nó gọi `build_report()` trong một giao dịch ghi
("written to the COPY only"), nên ghi thêm 1 dòng vào bảng `validation_reports` (`created_at` trong 03:21–04:00 UTC).
Kiểm tra chỉ đọc cho thấy đây là dòng duy nhất được ghi trong khoảng đó.

**Hệ quả.**
- Toàn bộ backtest cũ (smoke 11:05, chạy chính 10:50–12:37) chạy trên chính file đã có thay đổi này. File không đổi kể từ
  10:32:18.
- Demand của phạm vi BIGQUERY trong cửa sổ 01/01–22/10 là **1.367.447 dòng, qty 42.294.439**, trùng với `run_config.json`
  của backtest cũ. Không có dòng qty ≤ 0. `quick_check` = ok.
- Bảng `validation_reports` không được runner hay mô hình đọc.
- **Kết luận: không phần nào bị ảnh hưởng, không dừng phần nào.** Không tạo bản sao mới, vì đề bài không cho phép.
  SHA của file được ghi lại trước và sau khi chạy để chứng minh không có thay đổi. Phép tái lập V0 (bước 3.2) là kiểm tra
  thực nghiệm cho kết luận này.
- Lần đọc chỉ đọc (`mode=ro`) của tôi tạo `app.db-shm` và một `app.db-wal` rỗng cạnh file, nhưng không đổi `app.db`
  (thời điểm ghi vẫn là 23/10 10:32:18).

#### Đ2. V4 chưa đủ 24 mốc ở các lô đầu (ghi nhận 01:10, sau chạy thử)

- **Cách app chọn mốc:** `direct_training_matrix` chỉ dùng mốc `t0 = T − 7j` khi `t0 ≥ 7`. Dữ liệu bắt đầu 01/01, nên muốn
  đủ 24 mốc (cửa sổ nhãn 168 ngày) thì cần T ≥ 175 ngày, tức mốc lô từ 25/06/2026 trở đi.
- **Ảnh hưởng:** lô 1–4 (mốc 01/06, 08/06, 15/06, 22/06) dùng 20, 21, 22, 23 mốc. Số mốc thực tế của từng lô ghi trong
  `train_log.csv` (cột `n_origins`).
- **Không đổi cấu hình:** cấu hình V4 vẫn là `direct_origins = 24`; không thêm dữ liệu trước 01/01, vì ngoài cửa sổ dữ
  liệu của app.
- **Phạm vi ảnh hưởng:** chỉ giai đoạn chọn mô hình (01/06–31/08) có các lô này; giai đoạn kết luận (01/09–22/10) dùng đủ
  24 mốc.

## 2. PREREGISTRATION.md

Nguồn: `reports\backtest-prereg-v2-20261027\PREREGISTRATION.md` (worktree MAIN). Bản đăng ký trước giữ nguyên từng byte: [PREREGISTRATION.md](../../_luu_tru/dang_ky_truoc/backtest-prereg-v2-20261027/PREREGISTRATION.md), SHA-256 `50DBB8F3C28C576CAD8D4FA5F97E05007C5BB4DEB840D099D5BC8FF526E8BAE1` (4224 byte, của bản gốc).

MỤC ĐÍCH: xác định các cải tiến LightGBM có làm dự báo ngày D tốt hơn mô hình hiện tại và tốt hơn Avg hay không, bằng kết quả không thể chỉnh sửa sau khi xem.

DỮ LIỆU: bản sao DB backtest 23/10 (SHA 8ABD356D…); giờ mở bán từ lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku (gom SKU x FC x ngày, MAX theo item); lô huấn luyện 7 ngày bắt đầu 01/06/2026, ngày dự báo cuối 22/10/2026; seed 7; siêu tham số production (Tweedie 1.2, 300 vòng, lr 0.05, 31 lá, 36 biến).

BIẾN THỂ:
V0 = cấu hình hiện tại (fingerprint 8468ebe66d1706f7).
V1 = V0 + trọng số mẫu 3.0 cho horizon <= 7, 1.0 cho phần còn lại.
V2 = V1 + ngày đóng bán là "chưa biết" (NaN) trong panel dùng cho biến đầu vào và nhãn; biến open_hours_last, open_hours_mean_7 lấy giờ từ openhours_by_sku cho mọi ngày; luật FALLBACK tính trên panel CHƯA che (giữ nguyên luật cũ).
V3 = V2 + luật FALLBACK chỉ đếm ngày mở bán, theo thứ tự: INACTIVE khi tổng demand trên ngày mở bán trong 60 ngày = 0 VÀ có >= 30 ngày mở bán -> dự báo 0; REOPEN (mã FALLBACK_REOPEN) khi số ngày mở bán trong 56 ngày < 14 -> trung bình demand ngày mở bán trong 180 ngày (không có ngày mở bán nào thì xét luật tiếp theo); NEW khi số ngày mở bán từ đầu chuỗi < 28 -> trung bình demand ngày mở bán từ đầu chuỗi; INTERMITTENT khi tỷ lệ ngày mở bán có demand = 0 trong 56 ngày >= 0.80 -> trung bình demand ngày mở bán trong 28 ngày (không có thì 56 ngày); còn lại -> LightGBM.
V4 = V1 + direct_origins = 24 (cửa sổ nhãn 168 ngày).

ĐỊNH NGHĨA: ngày mở bán = total_open_hours > 0 HOẶC có đơn. Ngày đóng bán = total_open_hours = 0 VÀ không có đơn. Thiếu dòng giờ mở bán = chưa biết: không dùng để học; cảnh báo nếu > 20 cặp SKU x FC hoặc > 1% demand trong cửa sổ huấn luyện, vẫn chạy tiếp.

ĐẦU RA: mỗi ngày D, dữ liệu đến D-1, dự báo h = 1 (ngày D) và h = 2 (ngày D+1).
CHỈ SỐ CHÍNH: h = 1 (vận hành dự kiến: dữ liệu D-1 có lúc 04:10, app lấy lúc 05:00, dự báo được làm mới bằng mô hình đã duyệt trước 06:00). h = 2 là chỉ số phụ, đại diện cho ngày làm mới thất bại.
MỐC SO SÁNH: avg_demand_history (tính lúc 02:00 ngày D, dữ liệu đến D-1, tức cũng là h = 1).

CHẤM ĐIỂM (Claude chấm độc lập): chỉ các ngày total_open_hours > 0; dự báo làm tròn nửa lên; lệch = tổng |dự báo - thực| / tổng thực; thừa/thiếu = tổng dự báo / tổng thực - 1; nhóm A (TB > 20 sp/ngày và <= 20% ngày mở bán không có đơn), B (TB <= 5 sp/ngày và > 20% ngày không có đơn), C (còn lại), xác định bằng dữ liệu 01/06-31/08.

CHỌN MÔ HÌNH TỐI ƯU: chỉ dùng 01/06-31/08, h = 1, nhóm A: biến thể V1-V4 có lệch thấp nhất trong các biến thể có |thừa/thiếu| không lớn hơn của V1; nếu không biến thể nào có lệch thấp hơn V1 thì chọn V1.

KẾT LUẬN: dùng 01/09-22/10, h = 1, báo cáo kèm h = 2. Theo từng nhóm, mô hình tối ưu so với Avg: tốt hơn ở cả lệch và |thừa/thiếu|, và khoảng tin cậy 95% (bootstrap theo SKU x FC) của chênh lệch "lệch" không chứa 0 -> nên đổi; kém hơn ở cả hai -> giữ Avg; mỗi bên hơn một chỉ số -> chưa đủ cơ sở, cần business xác định chi phí thiếu hàng so với dư hàng.

GIỚI HẠN CÔNG BỐ TRƯỚC: (1) ý tưởng V2-V3 xuất phát từ quan sát T9-T10 nên giai đoạn kết luận không hoàn toàn độc lập; (2) dữ liệu lịch sử là bản đã ổn định, không phải đúng như tại thời điểm dự báo; (3) hiện app chưa có tác vụ làm mới dự báo hằng ngày nên kết quả h = 1 là khả năng đạt được khi vận hành đúng thiết kế; (4) Avg tính lúc 02:00 có thể dùng dữ liệu D-1 chưa đầy đủ bằng dữ liệu 04:10. Kết luận cuối cùng cần chạy song song từ 27/10.

## 3. Kiểm tra dữ liệu giờ mở bán (bước 1)

Nguồn: `reports\backtest-prereg-v2-20261027\data_checks.md` (worktree MAIN).

Mọi truy vấn chỉ đọc BigQuery: chạy dry run trước, trần `maximum_bytes_billed` = 2.000.000.000 byte mỗi truy vấn, chỉ
dùng 2 bảng đã đăng ký. Nhật ký truy vấn ở `bq_queries.json`; script ở `code/bq_openhours.py` và `code/data_checks.py`.

### 1.1 Cột của hai bảng (`INFORMATION_SCHEMA.COLUMNS`)

Chi tiết: `bq_columns.csv`. Truy vấn tính 10.485.760 byte (mức tối thiểu của BigQuery). Không bảng nào có cột phân
vùng hay cột clustering.

| Bảng | Cột |
|---|---|
| `openhours_by_sku` | fc_code STRING, product_id INT64, sku_code STRING, item_code STRING, product_name STRING, seller_code STRING, seller_class STRING, **open_date DATE**, **total_open_hours FLOAT64**, total_open_days FLOAT64 |
| `demand_planing_lightgbm` | fc_code, created_date DATE, so_code, customer_id INT64, order_status, product_id, sku_code, item_code, seller_code, sku_system_status, demand_quantity INT64, outbound_quantity INT64, sales_price FLOAT64, seller_class, open_date DATE, total_open_hours FLOAT64, total_open_days FLOAT64, refresh_time STRING |

### 1.2 Xuất bảng giờ mở bán

- Truy vấn đúng như đăng ký: gom SKU × FC × ngày, `open_date BETWEEN DATE '2025-10-26' AND DATE '2026-10-25'`.
- Dry run 825.473.780 byte; thực tế xử lý 825.473.780 byte, tính phí 826.277.888 byte; job
  `99f434b8-0538-4e7b-92ea-77ec5dc2fdbf`; tải về mất 985 s.
- Kết quả: **18.481.410 dòng** → `openhours.parquet`. Không ghi gì vào DB của app.

### 1.3 Chất lượng

Danh sách bất thường: `BAT_THUONG_GIO_MO_BAN.xlsx` (sheet `tong_hop` và một sheet cho mỗi loại, đủ cột nguồn + cột `ly_do`).
Số liệu máy đọc: `data_checks_1_3.json`.

| Mục | Kết quả |
|---|---|
| a. Khoảng ngày | 2025-10-26 → 2026-10-25, đủ 365/365 ngày |
| a. Số dòng mỗi ngày | **đúng 50.634 dòng mọi ngày**: bảng là lưới đầy đủ 50.634 cặp SKU × FC × mọi ngày, kể cả cặp không bán |
| a. Giờ ngoài [0, 24] | 0 |
| a. Giờ hoặc ngày NULL | 0 |
| a. hours > 0 nhưng days = 0 | **693 dòng** (sheet `a_gio_ngay_mau_thuan`) |
| a. hours = 0 nhưng days > 0 | 0 |
| b. Nhiều item cùng SKU × FC × ngày khác giờ | 0. Bảng đã ở mức SKU × FC × ngày (`n_rows` = 1 ở mọi dòng), nên "MAX theo item" không đổi giá trị nào |
| c. Cặp có trong `demand_daily` nhưng không có trong bảng | **2 / 17.140 cặp (0,012 %)**, tổng demand 75 sp (sheet `c_cap_thieu_trong_bang`) |
| c. Ngày thiếu trong khoảng hoạt động của chuỗi | 0 trên 3.755.755 cặp-ngày (khoảng hoạt động = ngày demand đầu tiên → cuối cùng trong cửa sổ 01/01–22/10) |
| d. Ngày có đơn nhưng hours = 0 | **952 cặp-ngày**, demand 25.740 sp (0,061 % demand ngày có đơn) (sheet `d_co_don_gio_0`) |
| d. Ngày có đơn nhưng không có dòng giờ | 32 cặp-ngày, 75 sp (chính là 2 cặp ở mục c) |
| e. Khớp với `open_hours` của `demand_daily` trên ngày có đơn | **99,996 %** (1.367.354 / 1.367.409); lệch 55 cặp-ngày, trung bình lệch 5,70 giờ (sheet `e_lech_voi_demand_daily`); 6 ngày có đơn không có `open_hours` trong `demand_daily` |

**Quyết định theo quy tắc.** Ngưỡng là: tỷ lệ khớp ở mục e < 95 %, hoặc thiếu > 5 % số cặp ở mục c. Kết quả khớp
99,996 % và thiếu 0,012 % cặp, nên **không đánh dấu** V2, V3 là "dữ liệu giờ mở bán chưa đạt".

## 4. Kiểm tra rò rỉ

Nguồn: `reports\backtest-prereg-v2-20261027\leakage_summary.md` (worktree MAIN).

Kiểm tra theo lô và theo ngày, ghi trong checkpoint, cho mỗi biến thể:
- lô: dữ liệu, panel và nhãn huấn luyện đều kết thúc trước mốc lô; với V2 / V3, giờ mở bán cũng kết thúc trước mốc;
- ngày D: dữ liệu, panel và giờ mở bán dùng cho D đều kết thúc trước D.

| Biến thể | Đạt / tổng |
|---|---|
| V0 | 165 / 165 |
| V1 | 165 / 165 |
| V2 | 165 / 165 |
| V3 | 165 / 165 |
| V4 | 165 / 165 |

Kiểm tra thực nghiệm (chạy thử, mốc 01/06, ngày 03/06):
- T1–T3 của runner cũ (V0): ĐẠT. T1: thay đổi mọi dữ liệu ≥ D và thêm chuỗi giả, model và dự báo phải giống hệt; T2: đối chứng âm, đổi D-1 thì dự báo phải đổi; T3: dựng lại panel.
- T4–T5 thêm cho V2 / V3: ĐẠT. T4: đổi demand và giờ mở bán ≥ D, model V2 và dự báo V2 / V3 phải giống hệt; T5: đối chứng âm, đổi giờ mở bán của D-1 thì dự báo V2 đổi (2461 chuỗi).

**Tổng: 830 / 830 kiểm tra đạt.**
