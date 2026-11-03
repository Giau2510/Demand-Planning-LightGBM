# Backtest đăng ký trước v3 – vòng 2 (27→28/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\backtest-prereg-v3-20261028\README.md` (MAIN) | 27/10/2026 | 8942 | `C0C3A39521226E3599490B6DD7DBD33DB1C45FC73AE8B200F82486E7A9261B1F` |
| 2 | `reports\backtest-prereg-v3-20261028\PREREGISTRATION.md` (MAIN) | 27/10/2026 | 5413 | `3187926CC13FA9B3E4B83D07DBC68BF3361DC8EB3763222CBA3133E188EA075A` |
| 3 | `reports\backtest-prereg-v3-20261028\data_checks.md` (MAIN) | 27/10/2026 | 6086 | `1C69BC65BB08E6ABEE3FE42E376C1847ABD93072C2ACFEDFD379EC2348AB8BA1` |
| 4 | `reports\backtest-prereg-v3-20261028\leakage_summary.md` (MAIN) | 27/10/2026 | 888 | `95741D7986F47E3EC4DB91BE8C1FD7129B65CD9A766E9A38F14DCF46B04950C8` |
| 5 | `reports\backtest-prereg-v3-20261028\chan_doan_khach_hang.md` (MAIN) | 27/10/2026 | 1318 | `0C737397B27D92C6940F281D4EC6AD831CC087966334FAD9B2CA8B7AF3F246A0` |

## 1. Backtest đăng ký trước v3 – vòng 2 (27→28/10/2026)

Nguồn: `reports\backtest-prereg-v3-20261028\README.md` (worktree MAIN).

### Đăng ký trước

- `PREREGISTRATION.md`: chép nguyên văn khối đăng ký của đề bài (UTF-8 không BOM, xuống dòng LF, 5.413 byte, có ký tự
  xuống dòng cuối file).
- **SHA-256 `3187926CC13FA9B3E4B83D07DBC68BF3361DC8EB3763222CBA3133E188EA075A`**, ghi lúc **2026-10-27 10:39:30** (giờ VN).
  File được ghi trước mọi truy vấn và mọi lần chạy.
- File được đặt thuộc tính chỉ đọc ngay sau khi tính SHA và không sửa về sau.

(Các phần dưới được bổ sung trong lúc chạy.)

### Bước 1.1: dòng đơn trong bản sao DB – KHÔNG CÓ → DỪNG R1–R7

Bản sao DB: `scratchpad\bt\db\app.db` (bản sao của vòng 1), SHA `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073`.
Mọi lần đọc dùng `mode=ro&immutable=1`.

| Kiểm tra (27/10 10:4x) | Kết quả |
|---|---|
| Bảng nào có `customer_id` / `so_code` / `created_date` | **không bảng nào** (đã liệt kê cột của cả 36 bảng) |
| `order_lines` | 93.238 dòng, **toàn bộ thuộc lô DEMO** (2024-10-16 → 2026-10-15); không có cột khách hàng, không có dòng nào của phạm vi BIGQUERY |
| `demand_held_lines` | dòng bị giữ lại của đồng bộ D-1, có `order_id` nhưng không có mã khách |
| Cách app tính 3 biến cust_* | `backend/app/data/customers.py` (dòng 9–11): mã khách **không bao giờ rời BigQuery**; truy vấn D-1 rút gọn ngay trong BigQuery thành 3 số đếm theo ngày × SKU × FC (`customer_count`, `repeat_customer_count`, `repeat_interval_days_sum` trong `demand_daily`, có từ 2026-01-01). App không lưu dòng đơn nào có mã khách. |

**Kết luận theo đề bài ("Không có: DỪNG R1–R7 và báo cáo").**
- **Không chạy R1, R2, R3, R4, R5, R7.** R2–R7 đều xây trên R1 (biến theo khách).
- **Chẩn đoán 1.4 và phần biến theo khách của 1.5 cũng dừng**, vì cần dòng đơn có mã khách.
- **Không dùng phương án thay thế:**
  - 3 số đếm tổng hợp trong `demand_daily` không đủ để tính các biến và chẩn đoán đã đăng ký;
  - truy vấn bảng demand trên BigQuery bị cấm (chỉ được truy vấn `fact_avg_demand_sku_historical` ở bước 1.2).
- **Phần biến xu hướng / phân loại của 1.5 cũng không tính.** Phần này không cần dữ liệu khách, nhưng chỉ dùng cho
  R2–R7, mà các biến thể này đã dừng.
- **Các phần không bị ảnh hưởng vẫn chạy:**
  - 1.2: Avg lịch sử và kiểm tra dữ liệu;
  - 1.3: căn ngày Avg, `avg_for_day`, kèm kiểm tra rò rỉ của Avg;
  - đóng gói `avg_for_day_eval.parquet` để chấm Avg và các bản kết hợp với R0. R0 = V1 vòng 1, có sẵn trong
    `reports\backtest-prereg-v2-20261027\package\goi2_dulieu.zip`, cột `V1`.
    - Cột đó là float32.
    - Giá trị chính xác 4 chữ số thập phân nằm trong `forecast_V1_2026-MM.csv` của vòng 1.

### Lệnh chạy chính xác

Môi trường (PowerShell), giống vòng 1:

```
$bt = '<scratchpad>\bt'                       # thư mục dữ liệu của bản sao DB vòng 1
$env:DF_DATA_DIR = $bt
$env:LOCALAPPDATA = "$bt\L"
$env:DF_DISABLE_SCHEDULER = '1'
$env:PYTHONPATH = 'D:\Buymed\Lightgbm AI\backend'      # code app: chỉ import (client BigQuery của app)
```

Python: `D:\Buymed\Lightgbm AI\.venv\Scripts\python.exe` (Python 3.14.7).

```
python -X utf8 code\bq_avg.py --out .                          # bước 1.2: dry run rồi chạy, trần 2 GB (461 s)
python -X utf8 -I code\avg_checks.py . <bt>\db\app.db          # bước 1.2 kiểm tra + 1.3 căn ngày + rò rỉ Avg
python -X utf8 -I code\make_package.py . <bt>\db\app.db <thư mục tạm>   # bước 3: đóng gói
```

**Một lần sửa lỗi** (giới hạn 1 lần cho mỗi bước):
- Lần chạy đầu của `avg_checks.py` dừng vì lỗi cú pháp (thừa một dấu ngoặc). Sửa một lần, chạy lại thành công.
- Chưa có kết quả nào được tạo trước khi sửa.

### Bước 1.2 và 1.3: Avg lịch sử và căn ngày (chi tiết ở `data_checks.md`)

| Mục | Kết quả |
|---|---|
| Dữ liệu | 5.505.821 dòng, 26.531 cặp SKU × FC, **26/02 → 23/10/2026**, 1 lần chạy mỗi ngày lúc khoảng 15:10 (giờ VN) |
| Chất lượng | không trùng khóa, mỗi cặp 1 product_id, 1.172 avg NULL, 0 âm; thiếu 7 ngày chạy (28/02, 01/03 → 06/03); 5 / 17.140 cặp demand không có Avg |
| Căn ngày (1.354 cặp TB ≥ 20 sp/ngày, 258.056 quan sát) | hệ số **D = 0,0024** (p = 0,57, không ý nghĩa); hệ số **D-1 = −0,0065** (p = 0,069); hệ số D-2 = 0,060 (p < 1e-7) |
| Quyết định | **không dịch lùi**; `avg_d(D)` = lần chạy mới nhất ≤ 06:00 ngày D, thực tế là lần chạy chiều D-1 |
| `avg_for_day.parquet` | 6.016.721 dòng (27/02 → 23/10). Kỳ chấm 01/06–22/10: 3.715.649 dòng, 8,6 % có tuổi nguồn > 8 ngày |
| Rò rỉ Avg | T6 (đổi dữ liệu Avg sau mốc) và T7 (đối chứng âm) **6 / 6 đạt** |

**Cách hiểu đã dùng.**
- "TB ≥ 20 sp/ngày" tính trên khoảng hoạt động của cặp: từ ngày demand đầu đến ngày demand cuối trong 01/01–22/10, ngày
  không có dòng tính là 0.
- Hồi quy chỉ dùng các ngày mà Avg của D và của D-1 đến từ hai lần chạy cách nhau đúng 1 ngày.
- Sai số chuẩn: cluster theo SKU × FC.
- Ngưỡng "có ý nghĩa": p < 0,05.
- Khi dự báo từ mốc D cho h = 2 (ngày đích D+1), người chấm dùng `avg_d` của chính ngày D (Avg đã có tại mốc D), không
  dùng `avg_d` của D+1.

### Bước 2: chạy – KHÔNG CHẠY

- **R1, R2, R3, R4, R5, R7 không chạy**, vì bước 1.1 không có dòng đơn có mã khách (xem trên). Không có chạy thử, chạy đầy
  đủ hay model nào.
- **R0** = V1 vòng 1, có sẵn, không chạy lại.

**File không tạo vì các biến thể đã dừng:**
- `forecast_<R>_2026-MM.csv`, `feature_gain_<R>.csv`, `train_log.csv`, `method_counts.csv`;
- `eval_forecasts_2026-MM.parquet`;
- `CHU_KY_KHACH_HANG.xlsx`.

`chan_doan_khach_hang.md` chỉ ghi lý do dừng.

### Kết quả và SHA-256

| File | SHA-256 |
|---|---|
| `PREREGISTRATION.md` | `3187926CC13FA9B3E4B83D07DBC68BF3361DC8EB3763222CBA3133E188EA075A` |
| `avg_history.parquet` | `F12A2A6E5C572C6B5758FA988FA0C135D60E9643043F23CD11C8589C23ABE887` |
| `avg_for_day.parquet` | `048E691B127679D75A47DE505BC7695F72177D115DF57CDAA85E862395A8A78C` |
| `code/bq_avg.py` | `B3D06F476BD7A9EE7CFA8785897D6F2605E968F0A083BCB10F00C050BC9C889D` |
| `code/avg_checks.py` | `8F4500CBF43C5DA4075B70D11E50D140DE2135BDECD4C49338B909AA92F44283` |
| `code/make_package.py` | `CECEB9377CC12FA1570F9E9E8D055B99C8183D0729FB58E2468FC7B4928AC04A` |
| Bản sao DB, trước và sau | `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073` (không đổi; mọi lần mở đều là `immutable`) |

**Các file khác:**
- `data_checks.md`, `avg_checks.json`, `BAT_THUONG_AVG.xlsx`, `bq_queries.json`;
- `feature_list.csv`: mọi biến đăng ký, kèm trạng thái tính hay không tính;
- `leakage_summary.md`, `chan_doan_khach_hang.md`;
- `package\`: SHA của từng file ở `MANIFEST.csv`.

**Mã khách hàng:** không có ở dạng nào trong mọi file xuất ra. Vòng này không đọc dữ liệu khách nào.

**Tổng thời gian** (từ ghi đăng ký đến đóng gói): 27/10 10:39 → khoảng 11:00, tức khoảng 20 phút. Không có lần chạy model nào.

### Điểm khác giả định

1. **Không có dòng đơn có mã khách** trong bản sao DB (bước 1.1), nên dừng R1–R7, chẩn đoán 1.4 và bảng biến 1.5.
2. **Avg lịch sử chỉ có từ 26/02/2026**, không phải từ 01/12/2025 như khoảng truy vấn. Kỳ chấm 01/06–22/10 không bị ảnh
   hưởng.
3. **Hệ số D-1 không dương như kỳ vọng.** Avg tại 06:00 ngày D (lần chạy 15:10 ngày D-1) phản ứng với demand ngày D-2, tức
   trễ 2 ngày. Hệ số ngày D ≈ 0 nên không dịch lùi; luật đăng ký giữ nguyên.
4. **Avg cũ được dùng tiếp.** Luật "bản ghi mới nhất" không giới hạn tuổi, nên cặp rời khỏi lần chạy hằng ngày vẫn dùng
   Avg cũ: 8,6 % dòng kỳ chấm có tuổi nguồn > 8 ngày. Dữ liệu giữ nguyên, có `source_transformed_at` để người chấm thấy.
5. **7 ngày không có lần chạy Avg** (28/02, 01/03 → 06/03) và 2 lần chạy khác giờ (26/02 lúc 21:29, 27/02 lúc 17:23).
   Cả hai nằm ngoài kỳ chấm.
6. **Không có thực bán ngày 23/10**, giống vòng 1: bản sao DB chỉ có demand đến 22/10. Vì vậy dự báo h = 2 từ mốc 22/10
   không chấm được.

## 2. PREREGISTRATION.md

Nguồn: `reports\backtest-prereg-v3-20261028\PREREGISTRATION.md` (worktree MAIN). Bản đăng ký trước giữ nguyên từng byte: [PREREGISTRATION.md](../../_luu_tru/dang_ky_truoc/backtest-prereg-v3-20261028/PREREGISTRATION.md), SHA-256 `3187926CC13FA9B3E4B83D07DBC68BF3361DC8EB3763222CBA3133E188EA075A` (5413 byte, của bản gốc).

MỤC ĐÍCH: tìm cho từng nhóm SKU phương án dự báo ngày D tốt nhất với câu trả lời có/không; kiểm chứng chu kỳ đặt lại của khách có dự đoán được ngày đột biến không.

NỀN: bản sao DB vòng 1 (SHA C7A663BE…F073); lô 7 ngày từ 01/06/2026, ngày dự báo cuối 22/10/2026; seed 7; siêu tham số production trừ khi biến thể ghi khác; h = 1 là chỉ số chính, h = 2 phụ.

DỮ LIỆU AVG LỊCH SỬ: lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku_historical, seller_code = MEDX, sku_system_status thuộc (OUT_OF_STOCK, LIMIT, NORMAL). Avg dùng cho ngày D = bản ghi có transformed_at (giờ Asia/Ho_Chi_Minh) mới nhất <= 06:00 ngày D, theo SKU x FC. Chỉ dùng nếu kiểm tra căn ngày xác nhận Avg đó không phản ứng với demand của chính ngày D; nếu kiểm tra cho thấy Avg chứa demand ngày D thì dịch lùi 1 ngày và ghi lại. Khi dự báo từ mốc D cho mọi horizon, chỉ dùng Avg đã có tại mốc D.

CHẨN ĐOÁN (chỉ dữ liệu 01/06-31/08): nhóm A như vòng 1. Ngày đột biến = thực bán > 2 lần trung vị thực bán ngày mở bán của SKU x FC trong 01/06-31/08. Khách đều tại ngày D = có >= 3 ngày đặt trong 180 ngày trước D và hệ số biến thiên khoảng cách giữa các lần đặt <= 0.5. Khách đến hạn tại ngày D = khách đều có (số ngày kể từ lần đặt cuối) / (trung vị khoảng cách) trong [0.8, 1.5], chỉ dùng dữ liệu trước D. Báo cáo: % lượng hàng nhóm A từ khách đều; % lượng hàng ngày đột biến từ khách đều và từ khách đến hạn; cùng các chỉ số đó ở ngày thường.

BIẾN THEO KHÁCH (chỉ dòng đơn có created_date < D, cửa sổ 180 ngày, theo SKU x FC): n_orders_7, n_orders_28, n_customers_7, n_customers_28, avg_order_qty_28, max_order_qty_28, top_customer_share_28, days_since_big_order (đơn >= phân vị 90 cỡ đơn của SKU x FC trong 180 ngày; 181 nếu không có), n_regular, n_due, n_overdue (tỷ lệ trong (1.5, 3]), due_qty (tổng trung vị cỡ đơn của khách đến hạn), overdue_qty, big_due_qty (due_qty của khách thuộc 10% lớn nhất theo lượng hàng 180 ngày), expected_rate (tổng của trung vị cỡ đơn / trung vị khoảng cách, trên khách đều), min_days_to_due (nhỏ nhất của trung vị khoảng cách trừ số ngày kể từ lần đặt cuối, trên khách đều; 999 nếu không có), regular_share_90 (tỷ trọng lượng hàng 90 ngày từ khách đều).
BIẾN XU HƯỚNG VÀ PHÂN LOẠI: ratio_7_28 = roll_mean_7 / roll_mean_28; ratio_1_7 = lag_1 / roll_mean_7; ewm_3, ewm_7 (trung bình mũ, chu kỳ bán rã 3 và 7 ngày, trên ngày mở bán); mean_open_90 và zero_share_open_90 (trên ngày mở bán 90 ngày trước D).

BIẾN THỂ:
R0 = V1 vòng 1 (dùng lại dự báo đã có, không chạy lại).
R1 = R0 + biến theo khách.
R2 = R1 + biến xu hướng và phân loại + che ngày đóng bán đúng như V2 vòng 1.
R3 = R2 + direct_origins = 24.
R4 = R3 + dừng sớm: tập kiểm định = 14 ngày nhãn cuối của cửa sổ huấn luyện mỗi lô (vẫn trước mốc lô); tối đa 1000 vòng; dừng sau 50 vòng không cải thiện WAPE trên dòng horizon <= 7; huấn luyện lại trên toàn cửa sổ với số vòng tìm được; 31 lá; Tweedie 1.2.
R5 = R4 với objective = l1.
R7 = R4 + biến avg_d (Avg đã có tại mốc dự báo) và avg_ratio = avg_d / roll_mean_14.
Dự phòng đăng ký trước: nếu 24 mốc gây thiếu RAM, R3, R4, R5, R7 dùng 12 mốc và ghi rõ.

KẾT HỢP (Claude tính khi chấm): mỗi R0-R5, R7 kết hợp với Avg: w*R + (1-w)*Avg, w thuộc {0.25, 0.5, 0.75}.

CHẤM: chỉ ngày total_open_hours > 0; dự báo làm tròn nửa lên; lệch = tổng |dự báo - thực| / tổng thực; thừa/thiếu = tổng dự báo / tổng thực - 1; lệch cộng dồn theo tuần = tổng theo SKU x FC x tuần của |tổng dự báo - tổng thực| / tổng thực; nhóm A/B/C như vòng 1, xác định bằng dữ liệu 01/06-31/08. Mốc so sánh: avg_demand_history như vòng 1. Chỉ số chính: lệch theo ngày.

CHỌN (chỉ 01/06-31/08, h = 1, từng nhóm): trong {Avg, R0-R5, R7, các bản kết hợp}, phương án có lệch theo ngày thấp nhất trong số phương án có |thừa/thiếu| <= |thừa/thiếu của Avg|.

XÁC NHẬN (01/09-22/10, h = 1, từng nhóm): nếu phương án được chọn có lệch theo ngày cao hơn Avg và khoảng tin cậy 95% (bootstrap theo SKU x FC) của chênh lệch không chứa 0 -> nhóm đó GIỮ Avg; ngược lại -> nhóm đó CHUYỂN sang phương án được chọn. Báo cáo kèm theo tháng, h = 2 và các chỉ số phụ.

GIỚI HẠN CÔNG BỐ TRƯỚC: (1) ý tưởng biến theo khách, mục tiêu L1, kết hợp và R7 xuất phát từ việc xem kết quả 01/09-22/10 của vòng 1, nên giai đoạn xác nhận không hoàn toàn độc lập; (2) dữ liệu lịch sử là bản đã ổn định; (3) app chưa có tác vụ làm mới dự báo hằng ngày; (4) kết hợp và R7 cần app lấy Avg mỗi ngày trước 06:00. Quyết định cuối cùng cần chạy song song tối thiểu 2 tuần.

## 3. Kiểm tra dữ liệu Avg lịch sử (bước 1.2) và căn ngày Avg (bước 1.3)

Nguồn: `reports\backtest-prereg-v3-20261028\data_checks.md` (worktree MAIN).

- **Nguồn:** `code/bq_avg.py` (truy vấn đăng ký, giữ nguyên văn) và `code/avg_checks.py`.
- **Số liệu máy đọc:** `avg_checks.json`. **Danh sách bất thường:** `BAT_THUONG_AVG.xlsx` (sheet `tong_hop` và một sheet cho mỗi
  loại, đủ cột nguồn và cột `ly_do`).
- **Đọc dữ liệu:** demand đọc từ bản sao DB (`mode=ro&immutable=1`), phạm vi BIGQUERY, 01/01–22/10/2026. Không ghi gì vào
  DB nào.

### 1.2 Truy vấn

| Mục | Giá trị |
|---|---|
| Bảng | `fact_avg_demand_sku_historical`, đúng SQL đăng ký (`bq_queries.json`) |
| Dry run | 808.002.530 byte, dưới trần 2.000.000.000 |
| Chạy thật | xử lý 808.002.530 byte, tính phí 808.452.096 byte |
| Job | `ffc91c8d-1bbc-4e38-9079-8b8062f892e7` |
| Thời gian | 461 s |
| Kết quả | **5.505.821 dòng** → `avg_history.parquet` (SHA ở README) |
| Kiểu cột | `transformed_at` TIMESTAMP (UTC), `avg_demand` FLOAT |

`sku_system_status` chỉ để tham khảo, không dùng làm biến và không dùng để lọc thêm.

| Mục | Kết quả |
|---|---|
| a. Giờ chạy (giờ VN) | **1 lần chạy mỗi ngày**: 233 lần chạy / 233 ngày. 231 lần vào khoảng **15:10**. 2 lần khác giờ: 26/02 lúc 21:29 và 27/02 lúc 17:23 (sheet `a_lan_chay_khac_gio`). |
| a. Số dòng mỗi lần chạy | 22.887 – 24.343, trung vị 23.592 |
| b. Trùng khóa SKU × FC × transformed_at | 0 |
| b. Nhiều product_id cho một SKU × FC | 0. Mỗi cặp chỉ có 1 product_id trong toàn kỳ. |
| c. avg_demand NULL | 1.172 dòng: 1.165 OUT_OF_STOCK, 7 NORMAL (sheet `c_avg_trong`) |
| c. avg_demand âm | 0 |
| c. Khoảng ngày | **2026-02-26 → 2026-10-23**. Truy vấn yêu cầu từ 2025-12-01, nhưng bảng không có dữ liệu trước 26/02/2026 (87 ngày). |
| c. Ngày không có lần chạy sau 26/02 | **7 ngày: 28/02, 01/03 → 06/03** (sheet `c_ngay_khong_co_lan_chay`, gồm cả 87 ngày trước 26/02) |
| c. Cặp có demand 01/01–22/10 nhưng không có Avg | **5 / 17.140 cặp**, tổng demand 40 sp (sheet `c_cap_demand_khong_co_avg`) |
| c. Cặp vắng mặt trong một số lần chạy | 1.031 / 26.531 cặp, tổng 18.101 cặp-ngày, tính giữa ngày đầu và ngày cuối của cặp (sheet `c_cap_thieu_ngay`) |

### 1.3 Căn ngày Avg

**Luật đăng ký.**
- `avg_d` của ngày D = bản ghi có `transformed_at` (giờ VN) mới nhất ≤ 06:00 ngày D, theo SKU × FC.
- Bản ghi đó có avg NULL thì `avg_d` để NULL; không lùi sang bản ghi cũ hơn.
- Ngày không có bản ghi nào trước mốc thì không có dòng; không tự điền.

**Kết quả `avg_for_day.parquet`:**
- 6.016.721 dòng, 26.522 cặp, ngày đích 27/02 → 23/10;
- 1.202 giá trị NULL;
- cột `source_transformed_at` cho biết bản ghi gốc.

Vì lần chạy ở khoảng 15:10 nên Avg của ngày D thực chất là **lần chạy chiều ngày D-1** (91,1 % dòng có tuổi nguồn 1 ngày).

**Tuổi nguồn > 1 ngày.** Xảy ra khi cặp vắng mặt ở lần chạy gần nhất, hoặc khi không có lần chạy (28/02–06/03). Luật
đăng ký không giới hạn tuổi nên vẫn dùng bản ghi mới nhất.
- Trên toàn bộ: 477.840 dòng có tuổi > 3 ngày.
- **Trong kỳ chấm (01/06–22/10):** 3.715.649 dòng. Tuổi nguồn 1 ngày: 3.372.301 dòng; 2–8 ngày: 23.067; **> 8 ngày: 320.281
  (8,6 %)**. Đây là các cặp đã rời khỏi lần chạy hằng ngày, thường do trạng thái SKU đổi sang nhóm bị lọc.
- Người chấm có thể đọc tuổi nguồn từ `source_transformed_at`.

**Phủ demand trong kỳ chấm:** 842 / 594.226 dòng demand (0,025 % lượng) không có `avg_d`.

#### Kiểm tra căn ngày

**Thiết kế.**
- Mẫu: 1.354 cặp có trung bình ≥ 20 sp/ngày; 1.330 cặp vào hồi quy.
  - Trung bình tính trên khoảng hoạt động, từ ngày demand đầu đến ngày demand cuối trong 01/01–22/10.
  - Ngày không có dòng demand tính là 0.
- Ngày D: 28/02–22/10. Chỉ lấy ngày mà `avg_d(D)` và `avg_d(D-1)` đến từ hai lần chạy cách nhau đúng 1 ngày. Ngày không có
  lần chạy không tạo thay đổi nên bị bỏ.
- Có 258.056 quan sát.
- Mô hình: Δavg_d(D) = b0·demand(D) + b1·demand(D-1) + b2·demand(D-2). Mọi biến đã trừ trung bình theo chuỗi (hiệu ứng cố
  định SKU × FC).
- Sai số chuẩn: cluster-robust theo SKU × FC.

| Hệ số | Ước lượng | SE (cluster) | t | p |
|---|---|---|---|---|
| demand ngày **D** | **0,00239** | 0,00419 | 0,57 | 0,57 |
| demand ngày **D-1** | **−0,00645** | 0,00355 | −1,82 | 0,069 |
| demand ngày D-2 | 0,05994 | 0,01060 | 5,65 | 1,6e-8 |

**Kết luận.**
- **Hệ số ngày D không có ý nghĩa** (p = 0,57): Avg dùng cho ngày D không phản ứng với demand của chính ngày D. **Không dịch
  lùi**, dùng đúng luật đăng ký (`shift_days` = 0).
- **Khác giả định: hệ số D-1 không dương.** Hệ số này xấp xỉ 0 và hơi âm, không có ý nghĩa ở mức 5 %. Avg phản ứng với
  demand ngày **D-2**.
- Nghĩa là lần chạy lúc 15:10 ngày D-1 chỉ chứa demand đến hết ngày D-2. Avg tại mốc D trễ 2 ngày so với demand, không
  phải 1 ngày.
- Điều này không làm thay đổi luật đăng ký và không phần nào phải dừng. Nó được ghi để người chấm biết.

#### Kiểm tra rò rỉ của Avg (phần Avg của bước 1.5)

Ba ngày được thử: 03/06, 15/08 và 22/10.

- **T6:** nhân 7 rồi cộng 100 vào mọi bản ghi có `transformed_at` > 06:00 ngày D, và thêm 1.000 cặp giả sau mốc. Kết quả
  `avg_d` của ngày D **giống hệt ở cả 3 ngày**.
- **T7 (đối chứng âm):** cộng 1 vào lần chạy thực sự được dùng (chiều D-1). `avg_d` đổi ở 23.545 / 23.721 / 22.957 cặp.
- **6 / 6 kiểm tra đạt.**

## 4. Kiểm tra rò rỉ – vòng 2

Nguồn: `reports\backtest-prereg-v3-20261028\leakage_summary.md` (worktree MAIN).

| Kiểm tra | Phạm vi | Đạt / tổng |
|---|---|---|
| T6: đổi mọi bản ghi Avg sau 06:00 ngày D và thêm cặp giả sau mốc → `avg_d` của D không đổi | 03/06, 15/08, 22/10 | 3 / 3 |
| T7 (đối chứng âm): đổi lần chạy Avg thực sự được dùng → `avg_d` của D phải đổi | 03/06, 15/08, 22/10 | 3 / 3 |
| **Tổng** | | **6 / 6** |

**Chưa chạy:**
- **T1–T5** của vòng 1 và kiểm tra rò rỉ của biến theo khách. Không model R1–R7 nào được huấn luyện hay dự báo, vì bước
  1.1 không có dòng đơn có mã khách (README).
- **Kiểm tra biến xu hướng / phân loại.** Bảng biến này không được tính, vì chỉ dùng cho R2–R7.

Chi tiết: `data_checks.md`, mục "Kiểm tra rò rỉ của Avg"; số liệu ở `avg_checks.json` (`leakage_avg`).

## 5. Chẩn đoán khách hàng (bước 1.4) – KHÔNG THỰC HIỆN

Nguồn: `reports\backtest-prereg-v3-20261028\chan_doan_khach_hang.md` (worktree MAIN).

**Không thực hiện:**
- 3 con số của chẩn đoán đã đăng ký:
  - % lượng hàng nhóm A từ khách đều;
  - % lượng hàng ngày đột biến từ khách đều;
  - % lượng hàng ngày đột biến từ khách đến hạn;
- các chỉ số tương ứng ở ngày thường;
- file `CHU_KY_KHACH_HANG.xlsx`.

**Lý do (bước 1.1).**
- Các chỉ số trên cần dòng đơn có mã khách (`created_date`, `so_code`, `customer_id`, `qty`, `order_status`), nhưng
  bản sao DB (SHA `C7A663BE…F073`) không có.
- App chỉ lưu 3 số đếm tổng hợp theo ngày × SKU × FC (`customer_count`, `repeat_customer_count`,
  `repeat_interval_days_sum`). Mã khách không bao giờ rời BigQuery (`backend/app/data/customers.py`).
- Từ 3 số đếm này không thể xác định "khách đều" (cần chuỗi ngày đặt của từng khách) hay "khách đến hạn".
- Truy vấn bảng demand trên BigQuery bị cấm ở vòng này.

**Phương án thay thế:** không dùng (đề bài cấm tự tạo phương án thay thế).

**Muốn thực hiện chẩn đoán này cần:** một lần xuất dòng đơn có mã khách đã băm, được phép riêng cho bảng
`demand_planing_lightgbm`.
