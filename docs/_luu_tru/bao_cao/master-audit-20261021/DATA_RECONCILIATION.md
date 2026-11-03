# Đối soát dữ liệu - master audit 21/10/2026

Nhãn bằng chứng: **VERIFIED** (có số liệu thật), **INFERRED** (suy luận, nêu giả định), **NOT_VERIFIED**, **BLOCKED**, **NOT_RUN**.
Mọi truy vấn BigQuery chỉ là `SELECT`, đều dry-run trước và có trần `maximum_bytes_billed` 2 GiB mỗi truy vấn. Không ghi gì vào
BigQuery hay vào production.

## 1. Snapshot nguồn (VERIFIED)

| Mục | Giá trị |
|---|---|
| Bảng | `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm` |
| Tạo / sửa lần cuối | 2026-10-20 15:18:39 UTC (22:18:39 giờ VN): bảng được **tạo lại**, `created == modified` |
| `refresh_time` trong dữ liệu | `22:18:21 20/10/2026` (một giá trị duy nhất trên 8.961.545 dòng) |
| Số dòng / dung lượng | 8.961.545 dòng; 1.692.144.874 byte; 18 cột (có thêm `customer_id`) |
| Phân vùng / clustering | **không có** (mọi truy vấn quét toàn bảng, xem PERFORMANCE_REPORT mục 4) |
| Phạm vi ngày có dữ liệu | 2026-01-01 .. 2026-10-19 (chưa có 20/10 tại thời điểm kiểm tra) |
| Cùng snapshot cho mọi phép đo | Có: metadata đọc trước và sau mỗi đợt truy vấn đều là 15:18:39 UTC (`bq_audit`, `bq_zero_hours_now`, `recon_keys`). Watcher chỉ đọc chạy tới 04:15 cũng không thấy lần dựng lại nào. |

## 2. Hạt dữ liệu (grain) (VERIFIED)

| Bảng / khái niệm | Hạt thực tế | Bằng chứng |
|---|---|---|
| Dòng nguồn D-1 | một dòng đơn hàng × item (`so_code` × `item_code`), có `fc_code`, `created_date`, `demand_quantity` | 7.248 dòng lặp khóa (so_code, SKU, FC, ngày): nhiều dòng của cùng đơn × SKU là bình thường, được cộng dồn (`key_duplicate_policy = SUM_ALL`) |
| Kho / FC | **chỉ** cột `fc_code` (ánh xạ `fc_id`) | `connector._daily_sql`: `GROUP BY 3, 4, 5` = ngày, `sku_id`, `fc_id`; không có hàm chuỗi nào trên mã SKU / item (test `test_v129e_item_suffix`, `test_v129h_*`) |
| Hậu tố item `.n` | **không** cho biết FC | Hậu tố .1, .2, .3, .4 đều có dòng ở cả BD và HN (vd. `.1`: 6.696.030 dòng BD và 84.177 dòng HN; `.2`: 145.439 BD và 1.934.219 HN); 108 cặp item × ngày bán ở 2 FC; mọi `item_code` = `sku_code` + "." + số |
| `total_open_hours` | **item × ngày** | 1.357.869 cặp item × ngày: 0 cặp có > 1 giá trị, kể cả 108 cặp bán ở 2 FC; 0 cặp item × FC × ngày có > 1 giá trị |
| Mục tiêu mô hình | ngày × SKU × FC (không đổi) | 1.357.876 khóa; 101 khóa có > 1 item (95 cùng giờ → OK, 6 khác giờ → MULTI_ITEM) |

## 3. Tổng nguồn 01/01-19/10 (VERIFIED)

| Trạng thái đơn | Dòng | Số lượng |
|---|---:|---:|
| COMPLETED | 8.667.387 | 41.069.936 |
| DELIVERED | 275.295 | 856.228 |
| DELIVERING | 13.471 | 54.428 |
| WAIT_TO_DELIVER | 3.307 | 12.723 |
| CONFIRMED | 1.513 | 9.162 |
| WAIT_TO_CONFIRM (so_code NULL ở cả 307 dòng) | 307 | 6.505 |
| PROCESSING | 265 | 980 |
| **Tổng** | **8.961.545** | **42.009.962** |

0 dòng thiếu SKU / FC / số lượng, 0 số lượng âm, 0 `customer_id` NULL. `so_code` NULL chỉ có ở `WAIT_TO_CONFIRM`, và mọi dòng
`WAIT_TO_CONFIRM` đều không có `so_code`.

## 4. Kiểm tra trùng và WAIT_TO_CONFIRM (VERIFIED)

Quy tắc trùng hoàn toàn của bản đang chạy (1.2.8) và gói 1.2.9: giống nhau ở cả 15 cột đã ánh xạ (`so_code, created_date,
sku_code, fc_code, demand_quantity, sales_price, product_id, item_code, outbound_quantity, order_status, seller_code,
sku_system_status, open_date, total_open_hours, total_open_days`), NULL = NULL. Không so sánh: `customer_id, seller_class,
refresh_time`.

| Giả thuyết | Nhóm | Dòng | Dòng dư | Kết luận |
|---|---:|---:|---:|---|
| Quy tắc cũ (GROUP BY 15 cột) | 18 | 67 | 49 | 16/10: 4 nhóm / 12 dòng / dư 8; 19/10: 14 nhóm / 55 dòng / dư 41 |
| Trùng thật (có `so_code`) | 0 | 0 | 0 | không có |
| Dòng chờ xác nhận, mỗi dòng một khách khác nhau | 18 | 67 | - | **đơn riêng hợp lệ** (số khách khác nhau = số dòng ở cả 18 nhóm; 0 `customer_id` NULL) |
| Dòng chờ xác nhận, cùng khách lặp lại (mơ hồ) | 0 | 0 | - | không có |
| Fan-out do join | 0 | - | - | không có dấu hiệu (seller_class, refresh_time giống nhau; khách khác nhau) |

Quy tắc mới (mã nguồn working tree, chưa phát hành): dòng `order_id` NULL + `WAIT_TO_CONFIRM` không bao giờ là trùng hoàn toàn.
Preview chỉ đọc toàn kỳ với mã đã sửa: `duplicate_groups 0`, `pending_no_order_code` = 307 dòng / 6.505 / 18 nhóm / 67 dòng
giống nhau, `ingest_status PASSED`.

Workbook: `demandforecast_audit_duplicates_wait_to_confirm_20261021.xlsx`.

## 5. Sáu khóa MULTI_ITEM - before / after (VERIFIED)

Before = bản làm mới 20/10 15:05 (workbook `demandforecast_multi_item_review_20261020_v2.xlsx`); after = snapshot 22:18.

| # | Ngày (2026) | FC | SKU | Item: dòng, qty, giờ | Trước | Sau | Nguyên nhân | Sửa | Trạng thái |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 09/02 | HN | MEDX.DMTS-HOA-BAO-002 | .1: 1, 2, 23,92 · .2: 3, 6, 24 | MULTI_ITEM | MULTI_ITEM (không đổi) | 2 item cùng bán ở 1 FC, mỗi item 1 giá trị giờ | không (chưa có quy tắc gộp) | BLOCKED - quyết định nghiệp vụ |
| 2 | 10/02 | HN | MEDX.2LJ61PGE | .1: 1, 1, 21,16 · .3: 1, 10, 24 | MULTI_ITEM | không đổi | như trên | không | BLOCKED |
| 3 | 02/03 | BD | MEDX.DMTS-STA-LOS-002 | .1: 17, 78, 5 · .2: 1, 10, 24 | MULTI_ITEM | không đổi | như trên | không | BLOCKED |
| 4 | 02/03 | BD | MEDX.SOP-NEO-001 | .1: 2, 2, 1,7 · .2: 1, 1, 24 | MULTI_ITEM | không đổi | như trên | không | BLOCKED |
| 5 | 26/08 | BD | MEDX.COU-STR-001 | .1: 7, 40, 23,72 · .2: 1, 2, 24 | MULTI_ITEM | không đổi | như trên | không | BLOCKED |
| 6 | 26/08 | BD | MEDX.D6TABCV8 | .1: 3, 3, 22,85 · .2: 1, 1, 18,22 | MULTI_ITEM | không đổi | như trên | không | BLOCKED |

Tổng 39 dòng, 156 đơn vị. Khóa biến mất: 0; khóa mới: 0; không có khóa CONFLICT / MISSING / OUT_OF_RANGE trên snapshot này.
Phân loại nguyên nhân cho cả 6 khóa: **"nhiều giá trị hợp lệ nhưng data contract chưa xác định cách xử lý"**. Không phải do diễn giải
hậu tố (FC lấy từ `fc_code`, app chỉ đếm item), không phải do mapping/join/group-by (2 item khác nhau, mỗi item đúng 1 giá trị,
0 dòng thiếu item), không phải nguồn mâu thuẫn (cùng item cùng ngày luôn một giá trị). Các phương án gộp (MIN / MAX / bình quân
theo số lượng / item có số lượng lớn nhất) có số liệu ở sheet `Expected_vs_Actual`. **Không áp dụng** phương án nào.

Workbook: `demandforecast_audit_multi_item_6_keys_20261021.xlsx` (thêm sheet `Suffix_vs_FC`, `Grain_Counts`).

## 6. Combo 931 khóa (VERIFIED, một phần INFERRED)

| Mục | Kết quả |
|---|---|
| Đối chiếu snapshot | 3.017 dòng / 931 khóa / 25.542 đơn vị có `total_open_hours = 0`: **khớp từng dòng** với CSV phân loại (0 dòng chỉ ở một bên) |
| VIA_COMBO (bảng combo, ≤ 09/07) | 1.865 dòng, 15.299 đơn vị - VERIFIED |
| DIRECT (bảng combo, ≤ 09/07) | 112 dòng, 364 đơn vị - VERIFIED |
| VIA_COMBO_SIGNAL (> 09/07) | 975 dòng, 9.796 đơn vị - INFERRED (tín hiệu `combo_quantity` có giá trị + không có dòng `fact_order_item_sku_combo`; hiệu chỉnh 937/937 dòng có nhãn) |
| GIFT / DIRECT_AFTER (> 09/07) | 43 dòng / 43 đơn vị; 22 dòng / 40 đơn vị - INFERRED |
| Tỷ trọng combo | 25.095 / 25.542 = **98,25 %** đơn vị |
| "uncertain = 0" | Đúng theo quy tắc: 1.040 dòng không có trong bảng combo đều sau 09/07 (bảng combo dừng 09/07); mức bằng chứng của chúng là INFERRED |
| Nhân đôi / join | `so_code` ↔ `order_id` 1:1 (2.847 mã); ở hạt đơn × SKU, số lượng nguồn = số lượng bảng combo cho 1.959 / 1.959 cặp có nhãn |
| "Combo quantity vượt quantity nguồn" | 36 dòng (20 cặp đơn × SKU có 2 dòng nguồn cùng item): cột `via_qty` của CSV là số theo đơn × SKU, lặp lại trên mỗi dòng (934 so với 467). Đây là cách trình bày của CSV; cộng cột này theo dòng sẽ đếm đôi |
| Code app | Không có logic combo; không nơi nào dùng `open_hours = 0` làm proxy combo |

Workbook: `demandforecast_audit_combo_931_20261021.xlsx`.

## 7. Nguồn so với dữ liệu app (VERIFIED)

App = bản sao production 1.2.8 (SQLite backup API, `mode=ro`) lúc 21/10 01:10, phạm vi BIGQUERY, nạp lần cuối trước lần dựng
lại nguồn. Cùng snapshot 22:18.

| Chỉ số | Giá trị |
|---|---:|
| Khóa ngày × SKU × FC: nguồn / app | 1.357.876 / 1.358.317 |
| Số lượng: nguồn / app | 42.009.962 / 42.023.217 (**−13.255**) |
| Khóa mới (nguồn có, app không) | 344 (+4.408) |
| Khóa đổi số lượng | 308 (36 tăng +99, 272 giảm −3.267; 238 trong tháng 10) |
| Khóa mất (app có, nguồn không còn) | 785 (−14.495; 772 nạp ngày 17/10) |
| Khóa không đổi | 1.357.224 |
| Ngày có thay đổi | 273 / 292 |
| Ngày đã chốt 23:59 có thay đổi | 2 / 2 |
| Preview backfill chỉ đọc (mã đã sửa, môi trường cô lập) | `BFP-20261020181139-18A4F4` **READY**, 0 cảnh báo, cùng các số trên |
| Giờ mở bán sẽ ghi | OK 1.357.870; MULTI_ITEM 6; MISSING / OUT_OF_RANGE / CONFLICT 0 |

Khóa mới / mất có ở mọi tháng 01-10/2026: nguồn đã thay đổi lịch sử khi dựng lại. Từ phía app không xác định được nguyên nhân
(UNRESOLVED): nhóm nguồn cần xác nhận trước khi backfill thay dữ liệu app bằng nguồn hiện tại. Chỉ 9 khóa đổi số lượng có dòng chờ xác
nhận; 0 khóa mới hoặc mất liên quan đến dòng chờ xác nhận.

Workbook: `demandforecast_audit_source_vs_app_20261021.xlsx`.

## 8. customer_id (VERIFIED trên code, NOT_RUN thử nghiệm)

- Production: `customer_id_column` rỗng, `feature_customer` tắt; không bật.
- Code (`data/customers.py`, `connector._customer_ctes`, `ml/features.py:290-302`): mã khách không ra khỏi BigQuery (chỉ số đếm theo
  ngày × SKU × FC); số đếm của ngày d chỉ dùng đơn đến ngày d; đặc trưng tại mốc dự báo t chỉ đọc các ngày `[t-28, t)` → không rò rỉ
  thời gian; test sẵn có `test_customer_features_read_only_the_known_days_before_the_target`.
- Chi phí: truy vấn D-1 có cột khách tăng từ 1.342.644.619 lên 1.414.336.979 byte (+5,3 %, dry-run).
- Hồ sơ dữ liệu (đợt trước): 35.055 khách, 0 NULL, mỗi đơn đúng 1 khách.
- Thử nghiệm baseline vs candidate offline: **NOT_RUN / BLOCKED**: huấn luyện nguồn BIGQUERY bị chặn `OPEN_HOURS_INVALID` bởi 6 khóa
  MULTI_ITEM cho mọi cửa sổ chứa 09/02-26/08 (chờ quyết định nghiệp vụ); không loại dòng để chạy cho qua.

## 9. D-0 (NOT_VERIFIED)

Bảng D-0 (`demand_planing_lightgbm_D0`) rỗng lúc kiểm tra (01:15, đã làm mới cho ngày mới). D-0 so khớp **toàn dòng** của SQL người dùng
(không có trạng thái được ánh xạ), nên dòng chờ xác nhận giống hệt nhau cũng có thể bị coi là trùng. Thực tế 20/10: 6/6 lần D-0 thành
công. Không đổi code D-0 trong batch này (RISK, theo dõi).
