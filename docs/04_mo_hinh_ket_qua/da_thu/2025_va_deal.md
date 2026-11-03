# Đã thử: học lại LightGBM với dữ liệu 2025 và deal

Phương án đã thử, không dùng (30/10/2026).

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `docs\hoc_lai_2025_deal_20261030.md` (CHOT) | 30/10/2026 | 18347 | `FC0F84930EB9C263E0F976D928584F6AFC9D80748A18ED3644AF349F72C0B212` |

## 1. Học lại LightGBM với dữ liệu 2025 và deal (30/10/2026)

Nguồn: `docs\hoc_lai_2025_deal_20261030.md` (worktree CHOT).

**Nhiệm vụ:** chủ dự án giao ngày 30/10/2026, gồm 7 giai đoạn.

**Branch:** `feature/lgbm-2025-deal-20261030`.
- Tạo từ `feature/lgbm-chot-20261029` (`495384b`, bản 1.3.1 đang cài), làm trong worktree `D:\Buymed\lgbm-chot-20261029`.

**Quyền được giao:**

| Quyền | Giá trị |
|---|---|
| Backfill production | CO |
| Đổi cấu hình D-1 (giới hạn ngày nguồn) | CO |
| Migration (chỉ thêm) | CO |
| Commit cục bộ | CO (không push) |
| Cài production | CO |
| Promote | CO, chỉ khi đạt mọi kiểm tra giai đoạn 6; app vẫn ở chế độ chạy thử |

**Quyết định của chủ dự án (30/10/2026):**
- Bảng nguồn mới là số đúng: đã bỏ dòng trùng, dòng sai do ghép voucher/deal và đơn khách hủy.
- Dữ liệu app đồng bộ theo nguồn (`FOLLOW_SOURCE`).
- Chấp nhận vượt chốt 5 % cho đúng 2 ngày: 19/08/2026 và 21/10/2026.

### 0. Hiện trạng lúc bắt đầu (30/10 08:13)

**Production:**
- Bản 1.3.1, PID 23692, schema 11.
- `history_change_policy` = `FOLLOW_SOURCE` (từ 02:21:33).
- Model đang dùng: `MV-20261026-105345-C73F`.

**D-1 sáng 30/10** (`JOB-20261029220026-E7E404`): **FAILED** `SOURCE_INCOMPLETE`.
- Dò tín hiệu từ 05:00. Sau mốc dự phòng 06:10, kiểm tra đủ dữ liệu: nguồn có 0 dòng của 29/10, trong khi bình quân 7 ngày trước là 17.213 dòng.
- Thất bại hẳn lúc 06:39.
- Dữ liệu app vẫn đến 27/10 (watermark 27/10).

**Bảng nguồn được sửa lại lúc 08:59:44 giờ VN** và đã có ngày 29/10.
- Kiểm tra theo tháng 01/2025–29/10/2026 bằng đúng quy tắc trùng của app: **0 nhóm trùng ở mọi tháng**, đủ 667/667 ngày đến 29/10.
- Bằng chứng: `reports\hoc-lai-2025-deal-20261030\evidence\g1\census_all0909_*`.

**Giữ máy thức:**
- Script giữ máy thức chạy 72 giờ.
- `powercfg` standby AC đã là 0 (không ngủ), không cần đổi.

### 1. Thiết kế 1.3.2

#### 1.1 Vì sao không đổi thẳng `bigquery.history_start_date`

**Mốc đọc** của D-1 / backfill = max(`data_policy.window_start_date`, `bigquery.history_start_date`).
- Nguồn: `bq/connector.py` `read_range`.
- Chỉ hạ `history_start_date` xuống 2025-01-01 thì mốc đọc vẫn là 2026-01-01.

**Hạ cả `window_start_date`** thì 2025 thành input của model.
- `training_start_rule = WINDOW_START`: phương án chốt sẽ học cả năm 2025.
- Như vậy khác mọi backtest đã đăng ký, và S0 không tái lập được 4.1.

**Cả hai khóa đều nằm trong mapping hash.** Đổi một khóa thì:
1. phải chạy lại kiểm tra hợp lệ (nếu không, D-1 lỗi `BQ_VALIDATION_REQUIRED`);
2. lần D-1 thường kế tiếp là **nạp toàn bộ** một lần, cần ngày hôm qua đủ dữ liệu;
3. backfill bị từ chối cho đến lần D-1 đó.

Hệ quả: không chia theo tháng được, không có chốt từng tháng.

**Cách làm của 1.3.2:** thêm khóa riêng `data_policy.extended_history_start_date` (mặc định None = như 1.3.1).
- Khóa này **không** vào mapping hash.
- Chỉ có tác dụng ở hai chỗ:
  1. **Backfill có xem trước** (phải có bản xem trước và bản sao lưu) được đọc từ mốc này trở đi. D-1 thường và nạp toàn bộ vẫn dùng mốc cũ, nên D-1 hằng ngày không đọc lại 2025.
  2. **Biến cùng kỳ năm trước** đọc demand đã lưu từ mốc này. Đây là ngoại lệ có chủ đích với quy tắc "input của model chỉ trong cửa sổ dữ liệu", do chủ dự án giao: E1 là "dữ liệu từ 01/01/2025, cửa sổ nhãn giữ như nền".
- `bigquery.history_start_date` giữ 2026-01-01.
- Đây là **điểm khác giả định Đ1** so với chữ của đề bài ("đổi giới hạn ngày nguồn D-1 về 2025-01-01"). Mục đích của đề bài vẫn đạt: 2025 được nạp theo từng tháng, có chốt, và D-1 hằng ngày chỉ đọc cửa sổ gần nhất.

#### 1.2 Cấu hình mới

Mặc định = hành vi 1.3.1. Khóa mới không vào mapping hash; khóa model mới không vào fingerprint khi ở mặc định.

| Section.khóa | Mặc định | Ý nghĩa |
|---|---|---|
| `data_policy.extended_history_start_date` | None | Ngày đầu của lịch sử mở rộng, phải trước `window_start_date`. Backfill có xem trước được đọc từ ngày này; biến cùng kỳ đọc từ ngày này. |
| `bigquery.deal_code_column` | "" (tắt) | Cột mã deal của dòng đơn trong bảng nguồn D-1. Khi đặt, D-1 và backfill ghi thêm `demand_deal_daily` cho đúng cửa sổ của mình. |
| `bigquery.deal_table_id` | "" (tắt) | Bảng deal (project.dataset.table). Khi đặt, sau mỗi lần D-1 thường thành công thì làm mới bảng `deals` và lưu một ảnh chụp. |
| `model.feature_set` | `CHOT` | `CHOT` = không thêm biến; `CHOT_LY` = +4 biến cùng kỳ; `CHOT_LY_DEAL` = +4 cùng kỳ + 12 biến deal. Khác `CHOT` thì phải là DIRECT. |
| `model.ly_history_start` | None | Do lần huấn luyện đặt, bằng `extended_history_start_date` khi `feature_set` cần biến cùng kỳ; người dùng không đặt được. Là DAY0 của biến cùng kỳ. |

#### 1.3 Lược đồ: migration `0012_ly_deal.sql`, chỉ thêm

| Bảng / cột | Vai trò |
|---|---|
| `demand_deal_daily` | Lượng dòng đơn theo phạm vi × ngày × SKU × kho × `deal_code`, chỉ dòng có mã deal. Cùng dòng hợp lệ như demand: SKU, kho, lượng không NULL, lượng ≥ 0, quy tắc trùng của app. Mỗi lần nạp thay đúng cửa sổ của nó. |
| `deal_line_loads` | Một bản ghi mỗi lần nạp `demand_deal_daily` (D-1, backfill, chạy tay). |
| `deal_snapshots` | Mỗi lần làm mới bảng deal: thời điểm chụp, thời điểm sửa của bảng nguồn, số dòng, SHA nội dung. Toàn bộ dòng lưu nén gzip; nội dung trùng ảnh trước thì trỏ `same_as`, không lưu lại. |
| `deals` | Trạng thái hiện tại = ảnh chụp mới nhất. |
| `forecast_refresh_values.deal_active` | Cột mới (NULL khi chưa cấu hình deal): có deal hợp lệ của bảng deal phủ ngày đích. |

#### 1.4 Biến mới

Đúng nguyên văn E1, E2 của `reports\backtest-2025-deal-20261030\PREREGISTRATION.md`. Cách tính chi tiết như `code\deal_lib.py` của đợt đó.

- **Cùng kỳ năm trước** (4 biến, chỉ dữ liệu < D), với `d` = chỉ số ngày D tính từ DAY0. Cửa sổ bắt đầu trước DAY0 thì là NaN; ngày không có dòng tính là 0.
  - `ly_same_day` = demand ngày D-364;
  - `ly_mean_7` = trung bình D-367..D-361;
  - `ly_mean_28` = trung bình D-391..D-364;
  - `ly_trend` = `ly_mean_28` / trung bình D-419..D-392, bằng 1 khi mẫu = 0.
- **Deal** (12 biến). Chỉ dùng deal có `ready_time` ≤ D 00:00 giờ VN; thời gian của bảng deal là giờ VN lưu dạng UTC.
  - Các biến: `deal_active`, `deal_days_since_start`, `deal_days_to_end`, `deal_max_qty`, `deal_used_to_date`, `deal_remaining_ratio`, `deal_used_1`, `deal_used_7`, `n_active_deals`, `sku_deal_uplift_hist`, `sku_deal_usage_hist`, `grp_deal_uplift_hist`.
  - Nhiều deal cùng lúc và các định nghĩa lịch sử: như Đ4, Đ5 của README đợt đó.
  - Nhóm A/B/C (quy tắc B7) tính tại ngày 1 của tháng D, trên 90 ngày trước đó; ngày mở bán lấy từ `open_hours_daily`, giờ > 0.
- **Vị trí cột:** sau các biến của mốc dự báo, trước lịch ngày đích và `horizon` (như E1/E2).
- **Áp dụng:** cả huấn luyện, kiểm thử lùi trong lúc huấn luyện, dựng lại panel của lần chạy và làm mới dự báo.

### 2. Tiến độ

#### 2.1 Sáng 30/10, đến lúc máy sập

**Giai đoạn 1.1:** D-1 sáng 30/10 thất bại `SOURCE_INCOMPLETE` (xem mục 0). Nguồn có ngày 29/10 từ lúc 08:59.

**Giai đoạn 1.2, trên bản sao `g1`** (bản sao production 09:08, SHA `5181CCBA…AE22`):
- Nạp lại 01/01–29/10 theo `FOLLOW_SOURCE`, nguồn phiên bản 10:03:48 giờ VN: xem trước `BFP-20261030031805-E0D11D`, nạp SUCCEEDED.
- Khớp nguồn 604/604 ô ngày × kho: 1.380.912 khóa, 42.607.730 đơn vị.
- Chốt chặn: chỉ 19/08 (8,42 %) và 21/10 (5,36 %) vượt 5 %, cả hai được phép. Ngày cao kế tiếp là 22/10 với 4,73 %.
- Lần nạp thử đầu tiên bị app tự chặn (`SOURCE_CHANGED_DURING_READ`) vì BI sửa bảng nguồn giữa chừng. Bảng nguồn được sửa lúc 08:59 rồi 10:03.

**Sao lưu production:** `backups\backup-20261030-100737-pre-backfill2026-20261030.zip` (SHA `602BAF8E…148C`), kèm file cấu hình. Khôi phục thử đạt: 44 bảng, số dòng khớp, 20 model trùng SHA.

**Code:**
- G3-T0 (cấu hình + migration 0012) xong.
- Test viết trước cho biến mới (G3-T2a) và cho lớp dữ liệu (G3-T1a) xong.
- G3-T2 (biến mới) làm dở; G3-T1 (lớp dữ liệu) mới bắt đầu.

#### 2.2 Máy sập 30/10, khoảng 11:03–11:19

**Diễn biến:**
- Máy khởi động lại không sạch lúc 11:19:08 (Kernel-Power 41; không có BugCheck).
- Lúc đó đang chạy cùng lúc: bản xem trước backfill trên production (từ 11:03:16), coder T2 và các bộ test.
- Trước đó, lúc 10:56: bộ nhớ commit trống 3,8 GB, RAM trống 1,6 GB.
- Máy còn vào Modern Standby do gập nắp lúc 08:14 và 09:13–09:44.

**Production sau khi sập** (kiểm tra 11:24, DB mở `mode=ro`):
- `quick_check` ok, schema 11.
- Dữ liệu 2026 không đổi: 1.382.381 khóa, 42.665.877 đơn vị. Chưa có bản xem trước nào được ghi, không có job dở.

#### 2.3 Quyết định của chủ dự án sau khi máy sập (30/10, khoảng 11:30)

1. **Chạy lại production ngay.**
   - App 1.3.1 khởi động lại lúc 11:39 (PID 21968), health ok, scheduler chạy, 7 luồng ON.
   - D0 kế tiếp 12:00, không lỡ. D-1 05:00 và huấn luyện 05:20 sáng 31/10.
   - Liên kết xem từ xa (`DemandForecastLink`) chạy lại; `https://log-pc.tail12f031.ts.net/api/health` ok.
2. **Chống sập lại.**
   - Mỗi lúc chỉ một việc nặng (nạp dữ liệu, xem trước, bộ test, backtest, huấn luyện); coder viết code song song nhưng chạy test lần lượt, tối đa một tiến trình test.
   - Chỉ bắt đầu khi bộ nhớ commit trống ≥ 5 GB và RAM trống ≥ 3 GB.
   - Đang chạy mà commit trống < 2,5 GB thì tạm dừng an toàn và báo.
   - Script giữ máy thức 72 giờ chạy lại từ 11:43.
   - `powercfg`: standby AC = 0. Gập nắp khi cắm điện = "Do nothing" (`LIDACTION` AC = 0; khi chạy pin vẫn là Sleep). Giá trị AC cũ của `LIDACTION` không đọc được trước khi đổi, vì thiết lập này ẩn với `/query`.
   - Đã xoá các bản sao DB tạm `bt2030`, `chot`, `d1test`, `d1test2`, `repro`, `restore30`, `restoreg1`, `bf` (chỉ phần dữ liệu; script nhỏ giữ lại). Giữ `g1`. Ổ C trống 34,9 → 57,1 GB. `backups\` giữ nguyên.
3. **Khóa phiên bản nguồn khi nạp:**
   - ghi thời điểm sửa cuối của bảng nguồn trước bản xem trước;
   - kiểm tra lại ngay trước và ngay sau khi áp dụng;
   - bảng đổi giữa chừng thì không áp dụng (nếu đã áp dụng thì đối soát lại và nạp bù) và báo.
4. **Làm tiếp theo thứ tự:** 1.2 trên production, rồi các giai đoạn 2–7 theo quy tắc ở mục 2.

#### 2.4 Prompt hoàn chỉnh của chủ dự án (30/10, khoảng 11:50) – thay mọi đoạn bổ sung trước

Prompt mới thêm các quy tắc sau:
- **Bản sao DB tạm** và file trung gian lớn đặt ở `D:\Buymed\tmp\`. Riêng bản sao `g1` (C:, scratchpad) và lần thử khôi phục của bước 1.2 đang chạy được giữ như cũ.
- **Khung tránh** cho mọi bước ghi production: 04:50–06:40 và 23:45–00:15.
- **Quy tắc pin / máy thức dậy** (A4), kèm một dòng nhật ký mỗi lần dừng hoặc tiếp tục.
- **LightGBM khi chạy cùng app:** `num_threads` = số nhân − 2 (máy có 12 nhân logic, nên là 10).
- **Mục O:** đo và tối ưu RAM / dung lượng sau 1.2. Bảng O3 gửi chủ dự án duyệt; chỉ đưa vào 1.3.2 những tối ưu không đổi kết quả.

**Nhật ký dừng / tiếp tục:**

| Thời điểm | Bước | Trạng thái production |
|---|---|---|
| 30/10 ~11:05–11:19 | 1.2: bản xem trước trên production | Máy sập. App dừng; DB nguyên vẹn, chưa ghi gì |
| 30/10 11:39 | Tiếp tục | App 1.3.1 chạy lại, health ok |
| 30/10 11:50 | 1.2: chờ D0 12:00, rồi sao lưu, khôi phục thử, xem trước, nạp | Cắm sạc, pin 44 % |
| 30/10 12:31 | 1.2 xong (mục 2.5) | Health ok, data-check WARN (không có FAIL) |
| 30/10 13:10–16:47 | Dừng: tester G3-T3 chạm giới hạn lượt lúc 13:10, không báo cáo, không ai làm tiếp | Health ok, không có việc chạy |
| 30/10 16:47 | Tiếp tục theo trả lời của chủ dự án (mục 2.6) | Health ok, cắm sạc, pin 98 % |

#### 2.5 Giai đoạn 1.2 trên production – XONG (30/10 12:31)

Bằng chứng ở `reports\hoc-lai-2025-deal-20261030\evidence\g1\` (`backup2\`, `prod\`).

**Sao lưu:** `backups\backup-20261030-120135-pre-backfill2026b-20261030.zip`, SHA `6A850480…033C`, kèm `config-20261030-120135-…json`.
- Lấy sau D0 12:00.
- Khôi phục thử đạt: 44 bảng, số dòng khớp, 20 model trùng SHA. Bản khôi phục tạm đã xoá sau khi kiểm tra.

**Khóa phiên bản nguồn:** bảng nguồn ở phiên bản 2026-10-30T03:03:48Z (10:03:48 giờ VN) trước bản xem trước, ngay trước khi nạp, trong job và ngay sau khi nạp.

**Bản xem trước** `BFP-20261030050737-43A5B3` (619 giây):
- READY, quét 3,62 GB (dưới trần 5 GB).
- Trùng hoàn toàn với bản sao `g1`: 7.790 khóa mới, 1.108 khóa đổi, 9.259 khóa bị bỏ; lượng −58.147; mã kế hoạch `6ff83ea4a5a07d07`.

**Chốt chặn**, tính từ quyết định từng khóa của chính bản xem trước:
- Chỉ 19/08 (8,42 %) và 21/10 (5,36 %) vượt 5 %, cả hai được phép.
- Tổng lượng bị bỏ: 260.782 đơn vị.

**Nạp:** job `JOB-20261030052148-578783`, 12:21–12:31, SUCCEEDED `BACKFILL_DONE`.
- Load `D1L-20261030052740-AC92E8`.
- App tự sao lưu trước khi nạp: `backup-20261030-122545-pre-backfill.zip`.

**Đối soát:**
- Production khớp nguồn 604/604 ô ngày × kho: 1.380.912 khóa, 42.607.730 đơn vị, 302 ngày (01/01–29/10).
- Không tháng nào lệch nguồn. Production trùng bản sao `g1` ở cả 604 ô.
- So với trước khi nạp: −1.469 khóa, −58.147 đơn vị (−0,14 %; đã gồm ngày 29/10 mới thêm). 12.228 dòng đang giữ được trả về theo nguồn.

**Kiểm tra sau nạp:**
- data-check: không có FAIL. WARN `forecast_series_meta` (có từ trước) và `finalized_days_changed` (do nạp lại); `history_source_drift` OK.
- Health ok.
- Watermark D-1 vẫn là 27/10 (backfill không đổi watermark), nên D-1 sáng 31/10 đọc cửa sổ 24/10–30/10.

#### 2.6 Trả lời của chủ dự án (30/10 16:45), sau lần kiểm tra tình hình 16:42

1. **Tiếp tục.** Quy tắc mới:
   - phiên phụ nào dừng hoặc chạm giới hạn lượt thì trong vòng 5 phút phải cho chạy tiếp hoặc mở phiên mới để làm nốt, và báo chủ dự án;
   - báo tiến độ ngắn mỗi 30 phút khi đang có việc chạy.
   - Đã làm lúc 16:48: dừng tiến trình treo PID 17532 (lệnh `python -` của tester, chờ đầu vào từ 13:05); xoá bản sao sót `scratchpad\repro\leak` (2,47 GB, ổ C).
2. **Test:** chạy lại `test_v132_deal_data.py` (sau khi tester sửa), rồi bộ test đầy đủ (1 tiến trình). Có lỗi thì sửa (tối đa 1 vòng) và báo.
3. **Bước 4.1: chọn (a).**
   - S0 chạy đầy đủ trên `p4`, làm mốc so sánh cho S1, S2. Không dùng lại `CHOT_lgbm`, vì nguồn đã đổi từ phiên bản 01:16 sang 10:03.
   - Kiểm tra tính đúng của code: trên cùng dữ liệu `p4`, lô 01/06, so S0 bằng code app 1.3.2 với runner + bản trích code cố định của `reports\backtest-lgbm7-20261029\` (cấu hình G2). Sai khác ≤ 1e-4 ở mọi horizon 1–7; không đạt thì dừng và báo.
   - PREREGISTRATION.md giai đoạn 4 ghi như đã định, chỉ đổi điểm 4.1 theo trên; tính SHA-256 trước khi chạy.
   - Trước khi chạy đầy đủ: chạy thử 01–03/06 cho S0, S1, S2, đo thời gian thật và cập nhật bảng dự kiến.
4. **Chuẩn bị `p4`:**
   - nếu chủ dự án báo đã phân vùng bảng nguồn thì đọc lại phiên bản mới trước khi bắt đầu;
   - dữ liệu 2025: một truy vấn cho cả năm nếu dry-run ≤ 5 GB, nếu không thì chia tháng;
   - xoá dữ liệu DEMO 2025 trong `p4` trước khi nạp dữ liệu thật.
5. **Bảng O3:**
   - Đưa vào 1.3.2: mục 1, 3, 4, 5, 6. Test phải chứng minh kết quả backfill / đối soát / dự báo trùng tuyệt đối trước và sau; ghi đỉnh RAM trước / sau.
   - Mục 11: chỉ thêm cấu hình. Mục 2: để sau. Mục 7: giữ nguyên.
   - Dọn dẹp, ngoài khung giờ tránh và không chạy cùng việc nặng; ghi dung lượng trước / sau:
     - mục 8: áp quy tắc giữ sao lưu;
     - mục 9: nén các thư mục backtest cũ, trừ `backtest-lgbm7-20261029`, `backtest-dulieu-moi-20261030`, `backtest-2025-deal-20261030`;
     - mục 10: `prune-artifacts.ps1` chạy thử, liệt kê, rồi mới xoá thật.
6. Các quy tắc vận hành giữ nguyên (tuần tự, ngưỡng RAM, khung giờ tránh 04:50–06:40 và 23:45–00:15, tiếp tục an toàn, khoá phiên bản nguồn).

Báo ngắn khi: test đầy đủ xong; `p4` chuẩn bị xong; kiểm tra tính đúng của code xong (kèm thời gian thật của chạy thử); sau mỗi S0 / S1 / S2.
