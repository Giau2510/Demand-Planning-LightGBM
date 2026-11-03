# Backtest LightGBM thuần, dự báo 7 ngày: G0, G2 và G1 (28/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\backtest-lgbm7-20261029\README.md` (MAIN) | 28/10/2026 | 27429 | `7E3F0088D7D3CB8B8F442C71C85D838F932178761713703758D87D1256FCB700` |
| 2 | `reports\backtest-lgbm7-20261029\PREREGISTRATION.md` (MAIN) | 28/10/2026 | 1940 | `575B0694E6B11AEED8A40A4CEA61FDB57B6D04A879E9790EA12489BFFAE47B25` |
| 3 | `reports\backtest-lgbm7-20261029\PREREGISTRATION_G1.md` (MAIN) | 28/10/2026 | 1120 | `1678E90769E74B2715C4ED4C382CB5514AE224CD95447B1881CCE8E264289A8E` |
| 4 | `reports\backtest-lgbm7-20261029\data_checks.md` (MAIN) | 28/10/2026 | 7812 | `D13D21FD22F0C546B300251B1EAD7C4A0AC7FAB0EAFD2011BE41BF90965EC7CA` |
| 5 | `reports\backtest-lgbm7-20261029\leakage_summary.md` (MAIN) | 28/10/2026 | 2440 | `4520E1A51332E8C81BFE023CDD22124081D100F9B57C77F5F0BC11EC88A1BC15` |
| 6 | `reports\backtest-lgbm7-20261029\leakage_summary_G1.md` (MAIN) | 28/10/2026 | 1787 | `656BC64A3E46290D415F5E69283C2946446E9FC83089F2F0391A1249336554E3` |

## 1. Backtest LightGBM thuần, dự báo 7 ngày: G0, G2 và G1 (28/10/2026)

Nguồn: `reports\backtest-lgbm7-20261029\README.md` (worktree MAIN). Bản gốc vẫn ở chỗ cũ (đang dùng cho D3); đây là bản chép ngày 03/11/2026.

Mỗi ngày D từ 01/06 đến 22/10/2026, mô hình dự báo 7 ngày D..D+6 bằng dữ liệu đến D-1. Đợt này **không chấm điểm** so
với thực bán; việc chấm do Claude làm theo cách chấm đã đăng ký. Thư mục này nằm ngoài Git. Không có file nào trong
`backend\`, `frontend\`, `scripts\`, `config\` bị sửa, không đổi settings hay lịch. Nhánh `feature/du-bao-moi-20261028`
không bị đụng tới. Không train hay promote trong app, không commit, không push.

### 1. Đăng ký trước

| File | SHA-256 | Ghi lúc (giờ VN) | Ghi chú |
|---|---|---|---|
| `PREREGISTRATION.md` (G0, G2) | `575B0694E6B11AEED8A40A4CEA61FDB57B6D04A879E9790EA12489BFFAE47B25` | 28/10 13:27:23 | 1.940 byte, UTF-8 không BOM, LF; chỉ đọc |
| `PREREGISTRATION_G1.md` (G1) | `1678E90769E74B2715C4ED4C382CB5514AE224CD95447B1881CCE8E264289A8E` | 28/10 15:44:37 | 1.120 byte, UTF-8 không BOM, LF; chỉ đọc; `PREREGISTRATION.md` không đổi |

Cả hai file chép nguyên văn khối đăng ký của đề bài. SHA được tính và file được đặt thuộc tính chỉ đọc trước mọi bước khác
của đợt tương ứng.

### 2. Nguyên tắc đã giữ (mục A)

- Chỉ dùng bản sao DB vòng 1, SHA `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073`. SHA này đo được
  lúc bắt đầu (13:31), khi ghép G0 / G2 (17:34) và khi ghép G1 (18:24), không đổi. Đợt này không ghi gì vào bản sao.
- Seed 7, siêu tham số production (fingerprint cấu hình `8468ebe66d1706f7`, được kiểm ở mọi lô). Trọng số mẫu 3.0 cho
  horizon ≤ 7 (V1). Lô huấn luyện 7 ngày bắt đầu 01/06, 21 lô.
- Checkpoint mỗi lô và mỗi biến thể (`checkpoints\`, part có SHA). Mỗi bước tối đa một lần sửa lỗi (xem Đ8, Đ12).
- LightGBM thuần: không Avg, không kết hợp, không nhân hệ số, không làm tròn trong file xuất (float64).
- G0 / G2: không truy vấn BigQuery, không dùng deal / voucher. G1: chỉ các truy vấn ở bước 1 của đề bài, dry-run trước,
  trần 3 GB mỗi truy vấn.

### 3. Lệnh chạy

Môi trường (PowerShell):

```
$out = 'D:\Buymed\Lightgbm AI\reports\backtest-lgbm7-20261029'
$env:DF_DATA_DIR = '<scratchpad phiên 672ca914>\bt'            # thư mục của bản sao DB vòng 1 (giống vòng 1)
$env:LOCALAPPDATA = "$out\env\L"                               # thư mục rỗng: không đọc storage.json thật
$env:DF_DISABLE_SCHEDULER = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = "$out\code\app_af835b8\backend"              # code app của commit af835b8 (chỉ import)
```

Python: `D:\Buymed\Lightgbm AI\.venv\Scripts\python.exe`, gồm Python 3.14.7, LightGBM 4.7.0, numpy 2.5.4, pandas 3.0.6
và pyarrow 26.0.0, giống vòng 1.

```
python -X utf8 code\lgbm7_runner.py --out $out --mode smoke          # G0, G2: chạy thử 01-03/06 + tái lập + rò rỉ
python -X utf8 code\lgbm7_runner.py --out $out --mode run            # G0 (21 lô) -> tái lập toàn bộ -> G2 (21 lô)
python -X utf8 code\lgbm7_runner.py --out $out --mode assemble       # eval\eval_forecasts_2026-MM.parquet + MANIFEST
python -X utf8 code\summarize.py $out                                # leakage_summary.md
python -X utf8 code\bq_deal_voucher.py --out $out --stage columns    # G1 bước 1.1 (kiểu cột)
python -X utf8 code\bq_deal_voucher.py --out $out --stage monthly    # G1 bước 1.1 (theo tháng)
python -X utf8 code\bq_deal_voucher.py --out $out --stage export     # G1 bước 1.2 -> deal_voucher_daily.parquet
python -X utf8 -I code\deal_voucher_checks.py --out $out --db <bản sao>\db\app.db   # G1 bước 1.3
python -X utf8 code\lgbm7_g1.py --out $out --mode smoke              # G1: 1.4 + chạy thử + rò rỉ
python -X utf8 code\lgbm7_g1.py --out $out --mode run                # G1 (21 lô)
python -X utf8 code\lgbm7_g1.py --out $out --mode assemble           # eval_G1\eval_forecasts_G1_2026-MM.parquet + MANIFEST
python -X utf8 code\summarize_g1.py $out                             # data_checks.md, leakage_summary_G1.md
python -X utf8 code\lgbm7_runner.py --out $out --mode package        # package\goi1_hoso.zip, goi2_dulieu_2026-MM.zip
python -X utf8 code\lgbm7_g1.py --out $out --mode package            # package\goi1_hoso_G1.zip, goi2_dulieu_G1_2026-MM.zip
```

### 4. Code và định danh

| File | Vai trò | SHA-256 |
|---|---|---|
| `code\backtest_runner_original.py` | runner gốc, bản sao **không sửa** | `D8DE6DAB1E8755F255E876D73FD4F949D7D6DFE3D5FBD762297E94BDAE2AAE60` |
| `code\prereg_runner.py` | runner vòng 1, bản sao **không sửa** (V1 = `train_weighted`) | `14396CB161CA1983513EBF73997A4F3C6CB9BDC3320D51B9A859A263C41FEE4C` |
| `code\lgbm7_runner.py` | runner G0 / G2 (dùng cho cả chạy thử và chạy đầy đủ) | `61376CDC618B8FA06353563EE5D90D9CC8235635381394A12BCC08B60DE65097` |
| `code\lgbm7_g1.py` | module G1, import `lgbm7_runner.py` không sửa (bản dùng cho chạy thử lần 2 và chạy đầy đủ) | `7688B0D98C6D0F0E3121609564B622535F20C715109D301BD6C662D57EB9C03B` |
| `code\bq_deal_voucher.py` | truy vấn BigQuery bước 1 của G1 | `97A548B35E343808CF55EE5723D400EF0ADEBB74750AB23A1729071604629C5A` |
| `code\deal_voucher_checks.py` | đối soát 1.3 | `4252BE3A46977D8581D9D4C4B080DD4E51CC9FC56AA9756348C74A8F93A41EAC` |
| `code\app_af835b8\backend\app` | code app trích từ commit `af835b8` (git tree `4f81813a…`, = HEAD) | cây file: `29076406E2464BA90A7A1621F65E4E5F0EAE706A5AECA020FEC96FE9C25CEF2E` |
| `deal_voucher_daily.parquet` | dữ liệu deal / voucher của G1 | `D027C65035D52AC3D51014EE953852E727B1E4CBCD26E3DD33682D9EE64FFA51` |

**Dùng lại cho lần sau.** Biến thể mới viết thành module riêng như `lgbm7_g1.py`. Module đó import `lgbm7_runner.py`
không sửa và ghi vào cùng `parts\<biến thể>\`, `checkpoints\<biến thể>_batch_kk.json`, `models\`. G0 của lần này giữ
nguyên làm mốc so sánh: dòng của biến thể mới được kiểm trùng khóa và thứ tự với `parts\G0\`.

### 5. G0 và G2

#### 5.1 Cài đặt

- **G0** dùng `prereg_runner.train_weighted` (V1 của vòng 1) để huấn luyện. Dự báo là `model.forecast` của app cho
  horizon 1–7, gồm luật FALLBACK của app như V1. Runner dự báo bằng đường chung (giống `_forecast_direct`); mỗi ngày D,
  kết quả G0 phải trùng `model.forecast` từng giá trị và phương pháp, nếu không thì dừng.
- **G2** dùng đúng ma trận huấn luyện của G0 nhưng bỏ cột `sku_code`. Cột này bị bỏ ngay trong bộ nhớ của ma trận (không
  tạo bản thứ hai) và đã được thử đúng trên ma trận ngẫu nhiên. G2 có 35 biến, trong đó `fc_code` vẫn là biến phân loại.
  Dự báo bỏ cùng cột. Phương pháp và FALLBACK giống G0.

#### 5.2 Chạy thử 01–03/06 (13:39 → 13:55)

| | G0 | G2 |
|---|---|---|
| Huấn luyện lô 1 | 93,7 s; 4.523.334 dòng; 36 biến | 83,0 s; 4.523.334 dòng; 35 biến |
| RAM đỉnh | 1.764 MB | 1.720 MB |
| Dự báo / ngày (7 horizon) | 7,8 s | 7,7 s |

- **Tái lập (chạy thử): ĐẠT.** G0 h = 1–2 so với V1 vòng 1: 92.916 / 92.916 dòng, không thiếu khóa, sai khác lớn nhất
  5,0·10⁻⁵ (V1 lưu 4 chữ số), phương pháp trùng 100 %. File model G0 lô 1 trùng từng byte với model V1.
- **Rò rỉ (chạy thử):** T1–T3 của runner cũ đạt. T6–T8 mới cho G0 và G2, từng horizon 1–7, đạt (`leakage_summary.md`).
- Ước tính lúc đó là G0 khoảng 58 phút, G2 khoảng 54 phút.

#### 5.3 Chạy đầy đủ (13:56 → 16:12, exit 0)

| Biến thể | Thời gian | Tổng huấn luyện | RAM đỉnh | Dòng huấn luyện | Mốc |
|---|---|---|---|---|---|
| G0 | 13:57 → 15:19 (82 phút) | 2.551 s | 2.198 MB | 4.523.334–5.203.026 | 12 |
| tái lập | 15:19 → 15:20 | | | | |
| G2 | 15:20 → 16:12 (52 phút) | 1.916 s | 2.298 MB | 4.523.334–5.203.026 | 12 |

- 21 / 21 lô DONE cho mỗi biến thể, không lô nào thất bại hay phải chạy lại.
- Mỗi biến thể có 16.655.702 dòng, tức 144 ngày D × 7 horizon × 2.379.386 chuỗi-ngày. Không có NaN, không có số âm.
- Số chuỗi × ngày theo phương pháp, giống hệt vòng 1 (V0 / V1) và giống nhau giữa G0 và G2: LIGHTGBM 980.362,
  INTERMITTENT 1.013.238, INACTIVE_ZERO 337.090, NEW_SERIES 48.696.
- **Tái lập toàn bộ: ĐẠT.** G0 h = 1, 2 so với `parts\V1` của vòng 1 (SHA mỗi part được kiểm theo checkpoint vòng 1):
  4.758.772 / 4.758.772 dòng, sai khác lớn nhất 5,0·10⁻⁵, không lệch khóa, phương pháp hay ngày đích. **21 / 21 file
  model G0 trùng từng byte** với model V1 (`reproduction_G0_vs_V1.json`).
- **Rò rỉ: 339 / 339 kiểm tra đạt** (`leakage_summary.md`):
  - theo lô và theo ngày: 21 + 144 = 165 / 165 mỗi biến thể; ngày đích của h = 3–7 đều sau panel ở 720 / 720 ngày × horizon;
  - T1–T3 của runner cũ, và T6–T8 mới cho G0 và G2 ở từng horizon.
- **Kiểm tra nhất quán:** G0 trùng `model.forecast` của app ở 144 / 144 ngày. Dòng G0 và G2 trùng khóa và thứ tự ở 21 / 21
  lô. Phương pháp G0 = G2 ở mọi dòng. Ngày đích = ngày dự báo + h − 1 ở mọi dòng.
- `feature_gain_G0.csv` có 756 dòng (21 model × 36 biến), `feature_gain_G2.csv` có 735 dòng (× 35 biến), `train_log.csv`
  có 42 dòng.

### 6. G1 (deal / voucher)

#### 6.1 Bước 1: dữ liệu (chi tiết `data_checks.md`)

- `is_deal` và `is_voucher` đều kiểu **BOOL**. Từ 01/2026 đến 27/10, NULL bằng **0 %** ở mọi tháng, không có giá trị
  không ép được sang BOOL, tháng nào cũng có cờ true. Vì vậy dữ liệu **không** bị đánh dấu "chưa đủ tin cậy".
  - Tỷ lệ dòng deal true theo tháng: 20,1 / 28,3 / 23,7 / 24,8 / 22,3 / 23,9 / 25,5 / 29,4 / 36,1 / 30,9 %.
  - Tỷ lệ dòng voucher true theo tháng: 22,7 / 23,6 / 27,7 / 30,9 / 29,0 / 29,7 / 31,4 / 31,5 / 26,4 / 25,6 %.
- Có 3 truy vấn, tổng tính phí 556,8 MB, mỗi truy vấn dưới trần 3 GB (`bq_queries_G1.json`). `deal_voucher_daily.parquet`
  có 1.361.196 dòng.
- **Đối soát 1.3: khớp tuyệt đối 98,06 % (< 99 %, ĐÁNH DẤU; vẫn chạy G1).**
  - Có 1.342.621 / 1.369.198 khóa khớp, 16.824 khóa khác lượng, 1.751 khóa chỉ có ở BigQuery, 8.002 khóa chỉ có ở bản sao.
  - Tổng lượng BigQuery là 42.754.720, cao hơn bản sao (42.294.439) 1,09 %.
  - Phần lệch dồn vào ít chuỗi. 184 cặp SKU × FC (104 SKU) của bản sao không còn trong bảng. 1.315 cặp khác lượng, gần
    như luôn là BigQuery cao hơn.
  - Mọi khóa lệch nằm trong `BAT_THUONG_DEAL_VOUCHER.xlsx`.
- **1.4: ĐẠT.** Ở 3 mốc (01/06, 03/06, 15/09):
  - đổi mọi dữ liệu deal / voucher từ D trở đi thì 10 biến của mốc D giống hệt;
  - chỉ đổi D-1 thì cả 10 biến đều đổi, ở 1.607–4.792 chuỗi.

  Cách tính được kiểm thêm bằng phép thử đồ chơi so với cách tính "vét cạn": sai khác ≤ 1,4·10⁻⁸, do lưu float32.

#### 6.2 Bước 2: chạy

**Cài đặt.** G1 = G0 + 10 biến tại mốc D, tổng 46 biến.
- Ma trận huấn luyện là `direct_training_matrix` của app, nối thêm 10 cột vào phần biến tại mốc.
- Đối chiếu trên 3.000 chuỗi của lô 1 (863.575 dòng): bỏ 10 cột thì trùng từng dòng với ma trận của app.
- Cùng lô, seed, siêu tham số, trọng số và luật FALLBACK như G0.
- Mảng deal / voucher đưa vào mỗi lô và mỗi ngày được cắt trước D.

**Chạy thử 01–03/06:**
- Lần 1 (16:12–16:33) bị dừng vì bộ nhớ (Đ8). Lần 2 (16:35–16:58) đạt hết.
- Lô 1 huấn luyện mất 155 s, RAM đỉnh 2.426 MB.
- Dòng G1 trùng khóa và thứ tự với G0. T1–T3, T6, T7, T7b, T8 đạt; ước tính khoảng 85 phút.

**Chạy đầy đủ: 16:59 → 18:10 (71 phút), exit 0.**
- 21 / 21 lô DONE, không lô nào thất bại, không phải chờ bộ nhớ trước huấn luyện.
- Tổng huấn luyện 2.498 s, RAM đỉnh 2.735 MB, 4.523.334–5.203.026 dòng, 12 mốc.
- 16.655.702 dòng, 144 ngày D × 7 horizon, không NaN, không số âm. Số chuỗi theo phương pháp giống G0.

**Rò rỉ: 175 / 175 đạt** (`leakage_summary_G1.md`):
- theo lô và theo ngày: 21 + 144; mảng deal / voucher của mỗi lô và mỗi ngày kết thúc trước mốc;
- T1–T3; T6 (đổi demand **và** deal / voucher từ D trở đi); T7; T7b (chỉ đổi deal / voucher của D-1 thì khoảng
  4.000 chuỗi đổi dự báo LightGBM ở mọi horizon); T8; 1.4 ở 3 mốc.

**Mô tả, không phải chấm điểm.** 10 biến deal / voucher chiếm 0,03–0,12 % tổng gain mỗi model (trung vị 0,06 %). Theo
gain trung bình, chúng xếp hạng 36–46 trên 46 biến. Biến mạnh nhất vẫn là `roll_mean_28` (44 %), `roll_mean_56` (39 %)
và `sku_code` (6,7 %). Có tốt hơn G0 hay không phải chờ chấm theo cách đã đăng ký.

#### 6.3 Bước 3: ảnh hưởng tới app (chỉ đọc code của bản đang chạy 1.2.14 = `af835b8`, và DB thật ở `mode=ro`)

**3.1 Bảng D-1 có thêm `is_deal`, `is_voucher` thì luồng lấy D-1 có lỗi không? KHÔNG.**

Bằng chứng từ code, trích từ `code\app_af835b8\backend\app\bq\connector.py`:
- So schema theo **tên** cột, không theo vị trí: `schema_drift` dựng từ điển tên → kiểu (`:353-357`). Việc
  `refresh_time` dời từ vị trí 18 sang 20 không ảnh hưởng.
- Chỉ chặn (`SCHEMA_CHANGED`) khi một cột **đã map** bị xoá hoặc đổi kiểu (`:981-986`). Cột thêm chỉ được ghi là "added".
- `validate_mapping` chỉ kiểm các cột đã map (`:364-434`). Câu SELECT liệt kê đích danh các cột đã map, không dùng
  `SELECT *` (`_select_list` `:610-614`).
- Kiểm tra dòng trùng (chính sách `BLOCK` của bản cài đặt) chỉ so các cột đã map (`dup_columns` `:706-712`), nên 2 cột
  mới không vào phép so.
- `mapping_hash` không chứa schema (`:524-536`), nên không cần xác nhận lại mapping và không bị nạp lại toàn bộ.

Bằng chứng từ DB thật (`mode=ro`, `query_only`):
- Hôm nay 09:40–09:45, job D-1 chạy tay `JOB-20261028024003-CC1012` **SUCCEEDED**, watermark 27/10, 103.057 dòng.
- Lần kiểm schema lúc 09:40 thấy **18 cột**. Hai cột mới được thêm sau đó (15:48 đọc thấy 20 cột).
- Hai lần D-1 thất bại `SOURCE_INCOMPLETE` lúc 05:00–06:38 hôm nay và hôm qua xảy ra trước khi có cột mới. Mã lỗi đó do
  đếm dòng của ngày (`rows_for_day` = 0), không liên quan cột.
- **Chưa có lần D-1 nào chạy với 20 cột.** Lần đầu sẽ là lịch D-1 sáng mai. Kết luận "không lỗi" vì vậy dựa trên code,
  chưa được kiểm thực tế.

Hai rủi ro nhỏ, không do bản thân 2 cột:
- Truy vấn kiểm dòng trùng có phần JSON cả dòng cho đơn chờ xác nhận, nên quét thêm 2 cột BOOL. Truy vấn chỉ bị từ chối
  `BQ_QUERY_TOO_EXPENSIVE` nếu ước tính vốn đã sát trần `maximum_bytes_billed` (20 GB trong cài đặt).
- Bảng bị sửa ngay trong lúc app đang đọc thì báo `SOURCE_CHANGED_DURING_READ` và thử lại (`sync.py:433`, `:469-471`).
  Điều này đúng với mọi lần dựng lại bảng.

**3.2 Nếu sau này đưa 2 cột vào app, những chỗ cần sửa (chỉ liệt kê):**
- **Trường mapping:** `settings_service.py:22-24, 37-38`. Đã có `promotion_flag` (OPTIONAL_FEATURE) và `voucher_flag`
  (REFERENCE, không bao giờ là input của model); chưa có trường deal riêng. Gợi ý map sẵn ở `bq\connector.py:54-57`,
  ghi chú "cần quy tắc nghiệp vụ" ở `:504-505`.
- **Kiểm kiểu:** nhóm FLAG nhận BOOL / INT64 / STRING (`connector.py:33, 39, 384-388`). SQL ép `CAST(... AS INT64)`
  (`:1211-1212`): BOOL ép được, còn STRING 'true' / 'false' thì lỗi.
- **Gom D-1:** `AVG(...) AS promo_share, voucher_share` (`connector.py:1247`), phần NULL của UNION ALL (`:1276-1284`).
  Cờ đã map sẽ thành cột được so khi kiểm dòng trùng (`:706-712`).
- **Lưu mapping:** `api\ops_routes.py:445-460` lưu mapping và schema_snapshot mới, đồng thời đặt
  `production_enabled = False`. `mapping_hash` đổi (`connector.py:527`), nên phải xác nhận lại (`sync.py:396-397`) và lần
  D-1 kế tiếp nạp lại toàn bộ (`sync.py:72`).
- **Lưu trữ:** `demand_daily` có `promo_share`, `voucher_share` nhưng không có cột deal (`migrations\0001_initial.sql:90-91`).
  `order_lines` có `promotion_flag`, `voucher_flag` (`:58, 60`). Ghi ở `data\history_sync.py:67, 103, 728`; fingerprint
  nội dung ở `data\identity.py:28-29`; nhập Excel ở `data\demand.py:144-150, 162-163`.
- **Biến model:** `ml\features.py:102, 107-108` (promo NaN thành 0), `:199-200` (`promo_last`, `promo_mean_7`),
  `:276-278`. Hiện chưa biến nào đọc `voucher_share`. Ngoài ra có danh mục và giải thích ở `ml\feature_catalog.py:155-159`,
  `ml\explain.py:61-62, 92-97`, `ml\forecast_explainer.py:340-343`.
- **Bật / tắt và ngưỡng phủ:**
  - Nhóm promotion được bật / tắt bằng `feature_promotion`, mặc định True (`settings_service.py:105`). Nghĩa là map
    `promotion_flag` thì lần huấn luyện kế tiếp sẽ dùng nó.
  - Ngưỡng phủ là `feature_min_coverage` 0,5 (`settings_service.py:123`), áp ở `ml\feature_registry.py:67-68, 159-202`.
  - Các mục dự kiến `deal_flag`, `promotion_flag_line`, `voucher` hiện ghi "chưa có cột nguồn" (`feature_registry.py:117-125`).
- **Giao diện:** `frontend\src\pages\Mapping.tsx:8, 15-16`; nhãn ở `frontend\src\i18n.tsx:805-807`.
- **Kiểm tra dữ liệu:** `data_checks.py` chưa có kiểm tra nào cho promo / voucher.
- **Tài liệu:** `docs\02_kien_truc_du_lieu\BIGQUERY.md:144, 196`, `docs\02_kien_truc_du_lieu\DATA-DICTIONARY.md:146, 428-430`.
- **Cần nghiệp vụ quyết định:**
  - `is_deal` là `promotion_flag` hay một trường deal riêng?
  - voucher có thành input của model không?
  - cờ NULL có được coi là 0 không?
  - 10 biến kiểu G1 (share / days / days_since) có làm trong app không? App hiện chỉ có `promo_last`, `promo_mean_7`.

#### 6.4 Đầu ra G1

- `eval_G1\eval_forecasts_G1_2026-MM.parquet` có các cột `sku_code, fc_code, forecast_date, horizon, target_date, G1`
  (float64), cùng `G1_lgbm` và `method_G1` (Đ5). Dòng trùng khóa và thứ tự với file G0 / G2 cùng tháng (đã sắp xếp
  giống nhau).
- `feature_gain_G1.csv` có 966 dòng (21 model × 46 biến); `train_log_G1.csv` có 21 dòng; `data_checks.md`;
  `BAT_THUONG_DEAL_VOUCHER.xlsx` có 26.577 khóa lệch.
- Tự kiểm: ngày đích = ngày dự báo + h − 1 ở mọi dòng; 144 ngày đủ 7 horizon với cùng số chuỗi; MANIFEST khớp ở cả 5 tháng.

### 7. Đầu ra

| File | Nội dung |
|---|---|
| `package\goi1_hoso.zip` | README, PREREGISTRATION.md, feature_gain_G0.csv, feature_gain_G2.csv, train_log.csv, leakage_summary.md |
| `package\goi2_dulieu_2026-MM.zip` (06–10) | `eval_forecasts_2026-MM.parquet` + `MANIFEST.csv` |
| `package\goi1_hoso_G1.zip` | PREREGISTRATION_G1.md, data_checks.md, feature_gain_G1.csv, train_log_G1.csv, leakage_summary_G1.md, BAT_THUONG_DEAL_VOUCHER.xlsx, README |
| `package\goi2_dulieu_G1_2026-MM.zip` (06–10) | `eval_forecasts_G1_2026-MM.parquet` + `MANIFEST.csv` |
| `package\package_sha256*.json` | SHA-256 của từng gói |

Mỗi dòng `eval_forecasts_*` là một bộ `sku_code × fc_code × forecast_date × horizon (1–7) × target_date`. Các file chia
theo **tháng của target_date**; tháng 10 có ngày đích đến 28/10. Các cột:
- `G0`, `G2` (hoặc `G1`): dự báo DIRECT của app, float64, chưa làm tròn. Chuỗi LIGHTGBM lấy giá trị của model; chuỗi
  FALLBACK lấy mức của luật FALLBACK (như V1).
- `G0_lgbm`, `G2_lgbm` (`G1_lgbm`): giá trị LightGBM cho **mọi** chuỗi, cắt ở 0 như app (thêm, xem Đ5).
- `method_G0`, `method_G2` (`method_G1`): phương pháp của app.

`MANIFEST.csv` đối soát số dòng, tổng `G*` và tổng `G*_lgbm` (tổng chính xác `math.fsum`) với các part gốc, kèm tên và
SHA của file.

| Tháng của target_date | Dòng G0 / G2 | MANIFEST G0, G2 | Dòng G1 | MANIFEST G1 |
|---|---:|---|---:|---|
| 2026-06 | 2.967.654 | khớp, khớp | 2.967.654 | khớp |
| 2026-07 | 3.535.956 | khớp, khớp | 3.535.956 | khớp |
| 2026-08 | 3.622.860 | khớp, khớp | 3.622.860 | khớp |
| 2026-09 | 3.543.373 | khớp, khớp | 3.543.373 | khớp |
| 2026-10 | 2.985.859 | khớp, khớp | 2.985.859 | khớp |
| Tổng | 16.655.702 | | 16.655.702 | |

### 8. Điểm khác giả định

- **Đ1.** `README.md` của vòng 1 không có mục nào tên "A (nguyên tắc)". Tôi dùng các nguyên tắc đề bài liệt kê ở mục A và
  giữ cách làm của vòng 1.
- **Đ2. Code app lấy từ commit `af835b8`, không lấy từ thư mục làm việc.** Thư mục làm việc đang ở nhánh
  `feature/du-bao-moi-20261028`, có sửa `ml/model.py` và `pipeline.py` của 1.3.0 đã stage. Tôi trích
  `git archive af835b8 backend/app` vào `code\app_af835b8\`: thao tác này chỉ đọc repo, không đổi nhánh hay index.
  `af835b8` là bản production 1.2.14, cùng code mà vòng 1 dùng. Cây `backend/app` của nó (`4f81813a…`) trùng HEAD lúc
  bắt đầu (`f82c890`). Bằng chứng: 21 / 21 model G0 trùng từng byte với V1.
  - Trong lúc chạy, **phiên khác** commit 1.3.0 lên nhánh đó: `969ebe2` lúc 16:09 và `3701f8b` lúc 17:00; cây
    `backend/app` của HEAD giờ là `de833760…`.
  - Tôi không chạy lệnh git nào làm thay đổi repo. Đợt này không bị ảnh hưởng vì dùng bản trích (SHA cây file trong mục 4).
- **Đ3. Đường dẫn của bản sao DB.** Bản sao nằm trong scratchpad của phiên 672ca914, như vòng 1. App mở DB bằng
  `db.connect` (kiểu đọc-ghi của app) nhưng runner chỉ đọc. Vòng 1 đặt `LOCALAPPDATA` = `bt\L`; lần này dùng thư mục
  rỗng `env\L` trong thư mục này. SHA bản sao trước = sau (mục 2).
- **Đ4. Không nạp `openhours.parquet`.** G0 / G2 / G1 không dùng bảng giờ mở bán đăng ký, nên RAM sau nạp chỉ khoảng
  700 MB, so với 2,5 GB ở vòng 1. Vì vậy T4–T5 của vòng 1, vốn dành cho panel che của V2 / V3, không áp dụng.
- **Đ5. Thêm cột so với đề bài:** `*_lgbm` (giá trị LightGBM cho mọi chuỗi) và `method_*`. Cột `G0`, `G2`, `G1` là dự báo
  của app có FALLBACK, đúng như V1; bắt buộc như vậy để tái lập được V1. Chuỗi FALLBACK chiếm 1.399.024 / 2.379.386 =
  58,8 % số chuỗi × ngày, và giống nhau giữa các biến thể. Khi chấm "giá trị LightGBM", người chấm chọn `G*` (đúng như
  app sẽ xuất) hoặc `G*_lgbm` (LightGBM cho cả chuỗi FALLBACK).
- **Đ6.** G0 chạy 82 phút, lâu hơn ước tính 58 phút, vì mỗi ngày còn chạy `model.forecast` để đối chiếu và dự báo
  LightGBM cho mọi chuỗi.
- **Đ7.** Ngày đích 23/10–28/10 (của D = 17/10–22/10) nằm sau dữ liệu của bản sao (đến 22/10). Chấm các ngày này cần
  demand thực từ nguồn khác.
- **Đ8. Bộ nhớ.** Lần này chạy ban ngày, khi máy đang dùng (RAM trống 0,4–3 GB).
  - Trước khi huấn luyện, G2 phải chờ bộ nhớ ở 2 lô: lô 4 khoảng 2 phút (15:28–15:30), lô 13 khoảng 1 phút (15:52).
    Không lô nào phải dừng hay chạy lại.
  - Chạy thử G1 lần 1 (16:12–16:33) bị tôi **dừng**. Lúc chờ bộ nhớ trước T6, tiến trình giữ 2,36 GB, trong khi bộ nhớ
    cam kết trống toàn máy tụt xuống 477 MB, nguy cơ ảnh hưởng app production.
  - Tôi sửa hàm kiểm tra rò rỉ của G1 một lần: dùng lại mảng, giải phóng khung dữ liệu nhiễu trước khi huấn luyện.
    Chạy thử lại 16:35–16:58 đạt. Kết quả của lần 1 trước khi dừng (1.4, đối chiếu ma trận, lô 1, T1–T3) đều đạt và
    trùng lần 2.
  - Từ 16:18, phiên khác chạy C5 trên bản sao (`train_candidate.py`, khoảng 2 GB) song song với chạy thử G1.
- **Đ9.** Part lưu bằng parquet float64 (vòng 1 dùng csv.gz 4 chữ số). File model và checkpoint giữ cùng cấu trúc với
  vòng 1.
- **Đ10.** `goi1_*.zip` không chứa code; code nằm ở `code\` (gồm bản trích app).
- **Đ11. Truy vấn 1.2 thêm 5 cột đếm:** `n_rows`, `n_deal_rows`, `n_voucher_rows`, `n_qty_null`, `n_qty_negative`.
  Vẫn là cùng một truy vấn, quét cùng các cột. Cần thêm để đếm "ngày có ít nhất một dòng is_deal = true" đúng định nghĩa
  (dòng có lượng 0 vẫn tính), và để giải thích chỗ lệch ở 1.3. Truy vấn 1.1 tách làm hai: một truy vấn
  `INFORMATION_SCHEMA` để lấy kiểu cột, rồi một truy vấn theo tháng.
- **Đ12. Đối soát < 99 %.**
  - Biến deal / voucher lấy cả tử số và mẫu số từ bảng BigQuery hôm nay. Demand, nhãn và mọi biến khác lấy từ bản sao, như G0.
  - Lịch sử bảng đã đổi sau 23/10, nên với khoảng 1.500 chuỗi, biến G1 dựa trên lượng hơi khác demand của bản sao.
  - Có 1.748 dòng parquet thuộc khóa không có trong demand của bản sao; các dòng này không dùng.
  - Đối soát (1.3) cần thêm `import db_dtypes`: đây là lần sửa lỗi duy nhất của bước này.
- **Đ13.** Ngày trước 01/01/2026 nằm ngoài cửa sổ dữ liệu của app, nên coi như không có đơn và không có cờ. Ở các mốc
  sớm, `days_since_*` = 181 khi không có cờ nào kể từ 01/01.
- **Đ14.** Thứ tự cột của G1: 10 biến mới đặt sau các biến tại mốc của G0, trước lịch của ngày đích và `horizon`, theo
  cấu trúc DIRECT của app. Danh sách đủ 46 biến nằm trong `models\G1_*.json`.
- **Đ15.** Kiểm tra mới cho G1: 1.4 (mức biến, ở 3 mốc) và T7b (đối chứng âm chỉ đổi deal / voucher của D-1). T6 của
  G1 đổi cả demand lẫn deal / voucher từ ngày D trở đi.
- **Đ16.** Bước 3.1 kết luận từ code cộng DB thật. Chưa có lần D-1 nào chạy với 20 cột (mục 6.3).
- **Đ17. Thời gian.**
  - Các mốc của G0 / G2: đăng ký 13:27; chạy thử 13:39–13:55; chạy đầy đủ 13:56–16:12; ghép file 16:59–17:34.
  - Các mốc của G1: đăng ký 15:44; BigQuery 15:48–15:52; đối soát 15:53; chạy thử 16:35–16:58; chạy đầy đủ
    16:59–18:10; ghép file 18:10–18:24; đóng gói 18:27–18:30.
  - G1 bắt đầu ngay khi G2 xong (16:12), đúng theo hàng đợi.

## 2. PREREGISTRATION.md

Nguồn: `reports\backtest-lgbm7-20261029\PREREGISTRATION.md` (worktree MAIN). Bản đăng ký trước giữ nguyên từng byte: [PREREGISTRATION.md](../../_luu_tru/dang_ky_truoc/backtest-lgbm7-20261029/PREREGISTRATION.md), SHA-256 `575B0694E6B11AEED8A40A4CEA61FDB57B6D04A879E9790EA12489BFFAE47B25` (1940 byte, của bản gốc). Bản gốc vẫn ở chỗ cũ (đang dùng cho D3); đây là bản chép ngày 03/11/2026.

MỤC ĐÍCH: đo độ chính xác của LightGBM thuần khi dự báo 7 ngày, so với demand thực của đúng từng ngày; kiểm tra tác dụng của biến mã SKU.
NỀN: bản sao DB vòng 1; lô huấn luyện 7 ngày bắt đầu 01/06/2026; mỗi ngày D từ 01/06 đến 22/10/2026 dự báo 7 ngày D..D+6 bằng dữ liệu đến D-1; seed 7; siêu tham số production; trọng số mẫu 3.0 cho horizon <= 7 (cấu hình V1).
BIẾN THỂ:
G0 = V1 (36 biến như production).
G2 = V1 bỏ biến sku_code (35 biến).
(G1 = V1 + biến deal/voucher sẽ được đăng ký và chạy ở lần sau, so với G0 của lần này, cùng cách chấm dưới đây.)
CHẤM ĐIỂM (Claude chấm): dự báo = ROUNDUP(giá trị LightGBM, 0); chỉ ngày total_open_hours > 0; so với demand thực của đúng ngày đó, không bù giữa các ngày; lệch = dự báo − thực. Đúng: |lệch| <= 3 sp (nhóm A, B) hoặc <= 1 sp (nhóm C), hoặc |lệch| / thực <= 20%. Ít: 20% < |lệch| / thực <= 50%. Nhiều: > 50% (kể cả thực = 0 và vượt ngưỡng sp). Thiếu khi lệch < 0, dư khi lệch > 0. Nhóm (dữ liệu 01/06-31/08, ngày mở bán): A = trung bình > 20 sp/ngày và ngày không có đơn <= 20%; C = trung bình <= 5 sp/ngày và ngày không có đơn > 20%; B = còn lại. Báo cáo theo tháng, theo nhóm, theo ngày thứ 1-7 của dự báo: Qty lệch từng loại (Đúng, Thiếu ít, Thiếu nhiều, Dư ít, Dư nhiều) và % so với tổng demand thực.
SO SÁNH BIẾN THỂ: chỉ số chính = tổng Qty lệch mọi loại / tổng demand thực, ở ngày thứ 1 và tổng 7 ngày; chỉ số phụ = Qty (Thiếu nhiều + Dư nhiều) / tổng demand. Biến thể được coi là tốt hơn G0 khi chỉ số chính thấp hơn ở CẢ ngày thứ 1 VÀ tổng 7 ngày.
GIỚI HẠN: dữ liệu lịch sử là bản đã ổn định.

## 3. PREREGISTRATION_G1.md

Nguồn: `reports\backtest-lgbm7-20261029\PREREGISTRATION_G1.md` (worktree MAIN). Bản đăng ký trước giữ nguyên từng byte: [PREREGISTRATION_G1.md](../../_luu_tru/dang_ky_truoc/backtest-lgbm7-20261029/PREREGISTRATION_G1.md), SHA-256 `1678E90769E74B2715C4ED4C382CB5514AE224CD95447B1881CCE8E264289A8E` (1120 byte, của bản gốc). Bản gốc vẫn ở chỗ cũ (đang dùng cho D3); đây là bản chép ngày 03/11/2026.

BỔ SUNG ĐĂNG KÝ – BIẾN THỂ G1 (tham chiếu PREREGISTRATION.md của G0/G2, cùng nền, cùng cách chấm, cùng cách so sánh)
G1 = V1 (G0) + 10 biến từ is_deal và is_voucher của bảng demand_planing_lightgbm, chỉ tính từ đơn có created_date < D, theo SKU x FC:
deal_share_1, deal_share_7, deal_share_28 = tổng demand_quantity của dòng is_deal = true / tổng demand_quantity, trong 1, 7, 28 ngày gần nhất (không có đơn: 0);
deal_days_7 = số ngày trong 7 ngày gần nhất có ít nhất một dòng is_deal = true;
days_since_deal = số ngày từ ngày gần nhất có dòng is_deal = true (181 nếu không có trong 180 ngày);
voucher_share_1, voucher_share_7, voucher_share_28, voucher_days_7, days_since_voucher: tương tự với is_voucher.
So với G0 của lần chạy G0/G2. G1 tốt hơn G0 khi chỉ số chính (tổng Qty lệch / tổng demand thực) thấp hơn ở CẢ ngày thứ 1 VÀ tổng 7 ngày.
GIỚI HẠN: biến deal/voucher chỉ biết đến hết ngày D-1, không biết đợt deal sắp bắt đầu; không dùng lịch deal.

## 4. Kiểm tra dữ liệu deal / voucher (G1, bước 1)

Nguồn: `reports\backtest-lgbm7-20261029\data_checks.md` (worktree MAIN). Bản gốc vẫn ở chỗ cũ (đang dùng cho D3); đây là bản chép ngày 03/11/2026.

Nguồn: `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`, đọc ngày 28/10/2026, chỉ đọc. Mỗi truy vấn chạy dry-run trước, trần `maximum_bytes_billed` = 3 GB.

| Bước | Dry-run (byte) | Tính phí (byte) | Dòng | Giây | Job |
|---|---:|---:|---:|---:|---|
| columns | 10,485,760 | 10,485,760 | 20 | 0.8 | `f8c482d6-042f-4d88-8c07-72fa25cf57d4` |
| monthly | 165,515,904 | 165,675,008 | 10 | 1.6 | `728bedd7-2fb7-4399-8d72-81801c8d6714` |
| export | 379,844,745 | 380,633,088 | 1,361,196 | 153.4 | `86caeab9-9f68-4ebc-a18b-10fa408ebd9a` |

### 1.1 Kiểu dữ liệu và chất lượng theo tháng

- `is_deal`: **BOOL**, `is_voucher`: **BOOL** (NULLABLE). Bảng có 20 cột; 2 cột mới nằm ở vị trí 18–19, `refresh_time` chuyển từ 18 sang 20.
- Điều kiện "true" dùng đúng như đề bài: `COALESCE(SAFE_CAST(x AS BOOL), FALSE)`; với kiểu BOOL, đây chính là `x IS TRUE`. Không có giá trị nào không ép được sang BOOL.

| Tháng | Ngày | Dòng | NULL deal | Dòng deal true | Lượng có deal | NULL voucher | Dòng voucher true | Lượng có voucher |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-01 | 2026-01-01..2026-01-31 | 1,247,844 | 0.00 % | 20.14 % | 19.65 % | 0.00 % | 22.72 % | 22.78 % |
| 2026-02 | 2026-02-01..2026-02-28 | 985,650 | 0.00 % | 28.30 % | 30.10 % | 0.00 % | 23.63 % | 22.61 % |
| 2026-03 | 2026-03-01..2026-03-31 | 1,214,905 | 0.00 % | 23.73 % | 23.41 % | 0.00 % | 27.71 % | 26.84 % |
| 2026-04 | 2026-04-01..2026-04-30 | 981,948 | 0.00 % | 24.77 % | 24.70 % | 0.00 % | 30.91 % | 32.79 % |
| 2026-05 | 2026-05-01..2026-05-31 | 1,032,981 | 0.00 % | 22.34 % | 22.83 % | 0.00 % | 29.00 % | 29.72 % |
| 2026-06 | 2026-06-01..2026-06-30 | 1,000,053 | 0.00 % | 23.90 % | 24.91 % | 0.00 % | 29.69 % | 26.69 % |
| 2026-07 | 2026-07-01..2026-07-31 | 964,176 | 0.00 % | 25.53 % | 27.73 % | 0.00 % | 31.40 % | 30.72 % |
| 2026-08 | 2026-08-01..2026-08-31 | 744,362 | 0.00 % | 29.38 % | 30.19 % | 0.00 % | 31.47 % | 30.14 % |
| 2026-09 | 2026-09-01..2026-09-30 | 524,167 | 0.00 % | 36.08 % | 34.20 % | 0.00 % | 26.39 % | 29.46 % |
| 2026-10 | 2026-10-01..2026-10-27 | 499,242 | 0.00 % | 30.88 % | 27.58 % | 0.00 % | 25.64 % | 26.66 % |

Quy tắc đánh dấu: NULL > 5 % ở tháng nào: **không có**; tháng có tỷ lệ true = 0 % trong khi tháng khác > 0 %: **không có**. → dữ liệu deal / voucher **đạt**, không đánh dấu.

### 1.2 Xuất dữ liệu

`deal_voucher_daily.parquet`: một truy vấn gom theo `created_date, fc_code, sku_code`, 2026-01-01..2026-10-22, các cột `qty`, `qty_deal`, `qty_voucher` đúng như đề bài; **thêm** `n_rows`, `n_deal_rows`, `n_voucher_rows` (để đếm "ngày có ít nhất một dòng is_deal = true" đúng định nghĩa, kể cả dòng có lượng 0) và `n_qty_null`, `n_qty_negative` (để giải thích chỗ lệch ở 1.3); cùng truy vấn, cùng cột được quét. 1,361,196 dòng.

### 1.3 Đối soát với demand_daily của bản sao DB

Khóa = ngày × sku_code × fc_code, 01/01–22/10. Bản sao: SHA `C7A663BE…F073`, dữ liệu D-1 nạp đến 23/10. Khớp tuyệt đối = khóa có ở cả hai bên và cùng lượng.

| Chỉ số | Giá trị |
|---|---:|
| Khóa BigQuery / bản sao / hợp | 1,361,196 / 1,367,447 / 1,369,198 |
| Khớp tuyệt đối | **1,342,621 = 98.06 %** của hợp (98.18 % số khóa của bản sao) |
| Cùng khóa, khác lượng | 16,824 |
| Chỉ có ở BigQuery | 1,751 |
| Chỉ có ở bản sao | 8,002 |
| Tổng lượng BigQuery / bản sao | 42,754,720 / 42,294,439 (+1.09 %) |
| Lượng của khóa khớp tuyệt đối / lượng bản sao | 91.33 % |

**Khớp < 99 %: đánh dấu, vẫn chạy G1.** Không có khóa NULL, không có dòng lượng NULL hay âm trong phần lệch. Lệch rải ở mọi tháng (theo tháng: 2026-01 2,587 khóa / +49,447, 2026-02 2,521 khóa / +51,102, 2026-03 4,373 khóa / +121,483, 2026-04 3,548 khóa / +95,288, 2026-05 2,282 khóa / +12,962, 2026-06 2,664 khóa / +19,111, 2026-07 2,567 khóa / +50,424, 2026-08 2,316 khóa / +27,449, 2026-09 1,882 khóa / +31,654, 2026-10 1,837 khóa / +1,361). Cách hiểu khả dĩ: bảng nguồn được dựng lại hằng ngày nên lịch sử đã đổi sau lần nạp D-1 cuối của bản sao (23/10); không kiểm chứng được bằng truy vấn khác vì đề bài chỉ cho phép các truy vấn ở bước 1. Mọi khóa lệch nằm trong `BAT_THUONG_DEAL_VOUCHER.xlsx` (sheet BAT_THUONG, đủ cột hai bên + `status` + `reason`).

Phần lệch dồn vào ít chuỗi (`reconcile_G1_profile.json`):
- chỉ có ở bản sao: 8,002 khóa thuộc 241 cặp SKU × FC; 184 cặp (104 SKU) không còn dòng nào trong bảng BigQuery hôm nay;
- chỉ có ở BigQuery: 1,751 khóa thuộc 34 cặp;
- cùng khóa khác lượng: 16,824 khóa thuộc 1315 cặp; BigQuery cao hơn ở 16,333, thấp hơn ở 491; |lệch| / lượng bản sao: trung vị 0.286, phân vị 90 % 1.0.
Kiểu lệch này (một nhóm chuỗi, gần như luôn một chiều) giống thay đổi cách dựng bảng nguồn cho nhóm chuỗi đó hơn là đơn về muộn; chưa kiểm chứng.

Ảnh hưởng tới G1: 10 biến deal / voucher lấy cả tử số và mẫu số từ bảng BigQuery hôm nay; demand, nhãn và mọi biến khác của G1 (như G0) lấy từ bản sao. Chuỗi không có trong bảng BigQuery: mọi share = 0, days_7 = 0, days_since = 181.

### 1.4 Tính 10 biến và kiểm tra rò rỉ

Dữ liệu dùng: 1,359,448 / 1,361,196 dòng parquet (1,748 dòng có khóa không thuộc chuỗi demand nào của bản sao, 0 dòng khóa NULL), 17,140 chuỗi × 295 ngày.

Cách tính (mốc D, chỉ ngày < D): share_w = tổng lượng có cờ / tổng lượng trong w ngày gần nhất (không có lượng: 0); days_7 = số ngày trong 7 ngày có ít nhất một dòng cờ true (`n_*_rows > 0`); days_since = D − ngày gần nhất có dòng cờ true, 181 nếu không có trong 180 ngày. Ngày trước 01/01/2026 (ngoài cửa sổ dữ liệu) coi như không có đơn, không có cờ. Mảng đưa vào mỗi lô / mỗi ngày được cắt trước D, đọc quá mốc là lỗi.

| Mốc D | Đổi mọi dữ liệu ≥ D: biến không đổi | Đổi D-1: số chuỗi đổi theo biến | Kết quả |
|---|---|---|---|
| 2026-06-01 | ĐẠT (591,943 dòng) | deal_share_1 4,025, deal_share_7 4,025, deal_share_28 4,025, deal_days_7 3,953, days_since_deal 3,953, voucher_share_1 4,384, voucher_share_7 4,384, voucher_share_28 4,384, voucher_days_7 4,070, days_since_voucher 4,070 | ĐẠT |
| 2026-06-03 | ĐẠT (581,579 dòng) | deal_share_1 4,343, deal_share_7 4,343, deal_share_28 4,343, deal_days_7 4,259, days_since_deal 4,259, voucher_share_1 4,792, voucher_share_7 4,792, voucher_share_28 4,792, voucher_days_7 4,398, days_since_voucher 4,398 | ĐẠT |
| 2026-09-15 | ĐẠT (113,901 dòng) | deal_share_1 1,809, deal_share_7 1,809, deal_share_28 1,809, deal_days_7 1,607, days_since_deal 1,607, voucher_share_1 2,669, voucher_share_7 2,669, voucher_share_28 2,669, voucher_days_7 2,454, days_since_voucher 2,454 | ĐẠT |

Ma trận huấn luyện G1 bỏ 10 cột = `direct_training_matrix` của app, từng dòng (3,000 chuỗi đầu của lô 1, 863,575 dòng): ĐẠT. Tỷ lệ dòng có giá trị khác mặc định: deal_share_1 4.1 %, deal_share_7 8.4 %, deal_share_28 13.9 %, deal_days_7 8.4 %, days_since_deal 34.6 %, voucher_share_1 3.0 %, voucher_share_7 7.4 %, voucher_share_28 12.6 %, voucher_days_7 7.4 %, days_since_voucher 21.5 %.

## 5. Kiểm tra rò rỉ (G0, G2; horizon 1–7)

Nguồn: `reports\backtest-lgbm7-20261029\leakage_summary.md` (worktree MAIN). Bản gốc vẫn ở chỗ cũ (đang dùng cho D3); đây là bản chép ngày 03/11/2026.

Kiểm tra theo lô và theo ngày, ghi trong checkpoint của từng biến thể (giữ nguyên cách kiểm tra của vòng 1):
- lô: dữ liệu, panel và nhãn huấn luyện đều kết thúc trước mốc lô;
- ngày D: dữ liệu và panel dùng cho D kết thúc trước D. **Thêm cho horizon 1–7:** ngày đích phải đúng D..D+6 và đều sau ngày cuối của panel.

| Biến thể | Lô: đạt / tổng | Ngày: đạt / tổng | Ngày đích h = 3–7 sau panel |
|---|---|---|---|
| G0 | 21 / 21 | 144 / 144 | 720 / 720 |
| G2 | 21 / 21 | 144 / 144 | 720 / 720 |

Kiểm tra thực nghiệm (chạy thử, mốc 2026-06-01, ngày D = 2026-06-03, ngày đích 2026-06-03..2026-06-09):
- T1–T3 của runner cũ (giữ nguyên, cấu hình V0, h = 1): ĐẠT. T1: đổi mọi dữ liệu ≥ D (583814 dòng) và thêm 500 dòng chuỗi giả; model và dự báo phải giống hệt. T2: đối chứng âm, đổi D-1 thì dự báo phải đổi (5099 chuỗi). T3: dựng lại panel.
- T6–T8 mới, cho G0 và G2, từng horizon 1–7:
  - T6: đổi mọi dữ liệu ≥ D (583814 dòng, gồm mọi ngày đích của h = 3–7) và thêm 500 dòng chuỗi giả. Huấn luyện lại ở mốc lô; model, phương pháp và dự báo của cả 7 horizon phải giống hệt.
  - T7: đối chứng âm, chỉ đổi D-1 (5099 dòng); ở mọi horizon phải có dự báo đổi.
  - T8: dựng lại panel ở mốc lô, dự báo 7 horizon phải giống hệt.
  - G0: T6 ĐẠT, T7 ĐẠT (số chuỗi đổi theo horizon [5099, 5099, 5099, 5099, 5099, 5099, 5099]), T8 ĐẠT.
  - G2: T6 ĐẠT, T7 ĐẠT (số chuỗi đổi theo horizon [5099, 5099, 5099, 5099, 5099, 5099, 5099]), T8 ĐẠT.
- T4–T5 của vòng 1 **không áp dụng**: hai kiểm tra này dành cho panel che và bảng giờ mở bán đăng ký (`openhours.parquet`) của V2 / V3; G0 và G2 không dùng cả hai.

**Tổng: 339 / 339 kiểm tra đạt** (330 theo lô / ngày + 9 kiểm tra thực nghiệm).

Kiểm tra nhất quán (không tính vào tổng trên):
- G0: dự báo của runner trùng `model.forecast` của app, giá trị và phương pháp, ở 144 / 144 ngày D;
- tái lập G0 so với V1 của vòng 1 (h = 1, 2): ĐẠT, 4758772 dòng, sai khác lớn nhất 5.00e-05; 21 / 21 file model trùng từng byte.

## 6. Kiểm tra rò rỉ G1 (horizon 1–7)

Nguồn: `reports\backtest-lgbm7-20261029\leakage_summary_G1.md` (worktree MAIN). Bản gốc vẫn ở chỗ cũ (đang dùng cho D3); đây là bản chép ngày 03/11/2026.

Giữ mọi kiểm tra của G0 / G2 (và của vòng 1), thêm phần deal / voucher:
- lô: dữ liệu, panel, nhãn huấn luyện **và mảng deal / voucher** kết thúc trước mốc lô;
- ngày D: dữ liệu, panel và mảng deal / voucher dùng cho D kết thúc trước D; ngày đích đúng D..D+6, sau panel.

| Biến thể | Lô: đạt / tổng | Ngày: đạt / tổng | Ngày đích h = 3–7 sau panel |
|---|---|---|---|
| G1 | 21 / 21 | 144 / 144 | 720 / 720 |

Kiểm tra thực nghiệm (chạy thử, mốc 2026-06-01, D = 2026-06-03, ngày đích 2026-06-03..2026-06-09):
- T1–T3 của runner cũ (giữ nguyên, cấu hình V0, h = 1): ĐẠT.
- T6: đổi mọi dữ liệu demand ≥ D (583,814 dòng) **và mọi dữ liệu deal / voucher ≥ D** (581,579 dòng), thêm chuỗi giả; huấn luyện lại; model, phương pháp và dự báo 7 horizon giống hệt: ĐẠT.
- T7: đối chứng âm, đổi demand D-1 → số chuỗi đổi theo horizon [5099, 5099, 5099, 5099, 5099, 5099, 5099]: ĐẠT.
- T7b: đối chứng âm mới, chỉ đổi deal / voucher của D-1 (5,074 dòng) → số chuỗi có dự báo LightGBM đổi theo horizon [4018, 4018, 4018, 4011, 3976, 4018, 4018]: ĐẠT.
- T8: dựng lại panel và mảng deal / voucher ở mốc lô, dự báo 7 horizon giống hệt: ĐẠT.
- 1.4 (mức biến, 3 mốc): ĐẠT; chi tiết trong `data_checks.md`.
- T4–T5 của vòng 1 không áp dụng (panel che và bảng giờ mở bán của V2 / V3).

**Tổng: 175 / 175 kiểm tra đạt** (165 theo lô / ngày + 10 thực nghiệm).

Kiểm tra nhất quán: dòng G1 trùng khóa và thứ tự với G0 ở 21 / 21 lô; MANIFEST khớp: ĐẠT.
