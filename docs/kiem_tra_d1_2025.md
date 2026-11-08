# Kiểm tra D-1 sau khi bảng nguồn có thêm dữ liệu 2025 và cột deal_code (29/10/2026)

Bản đang chạy: 1.3.1 (commit 495384b). Bảng nguồn: `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`.
Chỉ đọc code và chỉ đọc BigQuery (dry-run trước, trần 5·10⁹ byte mỗi truy vấn). Chạy thử trên **bản sao** DB production;
DB thật không bị ghi. Bằng chứng: `reports\kiem-tra-d1-2025-20261029\` (ngoài Git).

## 1. Kết luận

**Trường hợp (b): D-1 lỗi.** Nguyên nhân không phải dữ liệu 2025: bảng nguồn mới có **dòng trùng tuyệt đối**, nên cổng
chống trùng của app chặn lần nạp (`BQ_DATA_DUPLICATES`). Không có gì được ghi.

- **Không kéo dòng 2025.** Câu truy vấn lọc `created_date` từ 2026-01-01. App đã có sẵn thiết lập giới hạn ngày nguồn
  (`bigquery.history_start_date`) và nó đang là 2026-01-01, nên không có gì phải đổi.
- **Không lỗi mapping với `deal_code`.** Cột mới không được map. App chỉ ghi nó vào danh sách "không so".
- **Truy vấn quét nhiều hơn khoảng 2,5 lần.** Bảng không phân vùng. Ví dụ truy vấn gom dữ liệu: 1,43 GB → 3,64 GB.
- **Chưa chạy D-1 trên production** (mục 1.5), vì bước 1.3 không đạt.
- **Lịch D-1 sáng 30/10 sẽ bị chặn giống vậy** nếu bảng nguồn chưa được sửa. Kéo theo: huấn luyện 05:20 bị bỏ qua, và
  làm mới dự báo bị gắn STALE lúc 12:00.

## 2. Luồng D-1 của 1.3.1 (đọc code)

| Mục | Hành vi | Code |
|---|---|---|
| Cửa sổ đọc | Nạp nối tiếp: từ (watermark − `late_data_lookback_days`, mặc định 3) đến hôm qua. Nạp lại toàn bộ (từ mốc sàn) chỉ khi `mapping_hash` đổi. Lần tới: **24/10–28/10**, không nạp lại toàn bộ | `sync.py:67-75`, `:428-430` |
| Mốc sàn ngày nguồn | `max(data_policy.window_start_date, bigquery.history_start_date)`, hiện cả hai là 2026-01-01 | `bq/connector.py:628-635` |
| Lọc ngày | `WHERE DATE(created_date) BETWEEN @start AND @end`. Có thêm bộ lọc phân vùng `created_date` ±1 ngày, nhưng chỉ giảm byte khi bảng có phân vùng. Bảng hiện **không** phân vùng | `connector.py:594-599`, `:638-649` |
| Đếm khách hàng | Đọc từ `start − 90` ngày. Với lần nạp nối tiếp vẫn nằm trong 2026. Lần nạp lại toàn bộ hoặc kiểm từng ngày từ 01/01 sẽ đọc tới 03/10/2025 (chỉ để đếm, không ghi dòng 2025) | `connector.py:1288-1310` |
| Kiểm đủ dữ liệu | Không cấu hình bảng tín hiệu → sau 06:10 dùng ngưỡng: số dòng của hôm qua ≥ 0,5 × trung bình 7 ngày trước. Không đạt → `SOURCE_INCOMPLETE`, thử lại | `sync.py:403-414`, `connector.py:1495-1508` |
| Mapping | So cột đã map với schema thật, theo tên. Cột thêm không gây lỗi | `connector.py:715-728` |
| Dòng trùng | Chính sách `BLOCK`: dòng không ở trạng thái `WAIT_TO_CONFIRM` mà giống nhau ở **mọi cột đã map** (14 cột, trừ item_code) là trùng. Có trùng → xuất file báo cáo, dừng, không ghi | `connector.py:731-756`, `:833-844`, `:1359-1360` |
| Gom và kiểm đầu ra | Gom theo ngày × SKU × kho. Mỗi khóa đúng một dòng; ngày, SKU, kho phải có; lượng không NULL, không âm. Một dòng sai là dừng | `connector.py:1202-1285`, `sync.py:78-109` |
| Ghi | Một giao dịch. Thay toàn bộ các dòng của cửa sổ bằng dòng đọc được cộng dòng đang giữ (đơn nguồn đã bỏ). Mỗi thay đổi ghi nhật ký. Đối soát số ghi = số đọc, không khớp thì không ghi | `sync.py:474-556`, `data/history_sync.py` |
| Bảo vệ khác | Đọc rỗng không bao giờ xoá dữ liệu đã lưu (`EMPTY_READ`). Bảng bị dựng lại trong lúc đọc → không ghi, thử lại (`SOURCE_CHANGED_DURING_READ`). Quá 50.000 khóa đổi → dừng (`HISTORY_CHANGE_TOO_LARGE`) | `sync.py:451-459`, `:469-471`, `:483-487`; `history_sync.py:73`, `:450` |
| Sau khi ghi | Làm mới tên sản phẩm (đọc bảng `dim_sku`), chốt actual, đối soát ngày đã đóng. Kiểm từng ngày lịch sử từ 01/01 tới trước cửa sổ: chỉ báo, không làm hỏng lần nạp | `sync.py:119-136`, `:149-167` |
| Giới hạn | Mỗi truy vấn được dry-run trước; quá `maximum_bytes_billed` (20 GiB) thì bị từ chối. Thời gian chờ 300 s mỗi truy vấn. Lỗi tạm thời thử lại tối đa 2 lần, hết giờ thì không thử lại. Không có giới hạn số dòng; báo cáo trùng liệt kê tối đa 100.000 nhóm | `connector.py:222-275`, `:653`; `settings_service.py:413-414` |

## 3. Dry-run đúng các câu truy vấn của lần D-1 tới (1.2)

Câu SQL do chính hàm của app dựng ra, với thiết lập của bản sao. Kết quả ở `evidence\d1_dryrun.json`.

Bảng nguồn: 23.001.982 dòng, 4,47 GB, sửa lần cuối 29/10 17:29 (giờ VN). Không phân vùng, không cluster. Có 21 cột,
trong đó có `deal_code` (STRING), `is_deal`, `is_voucher`. Ngày nhỏ nhất 2025-01-01, lớn nhất 2026-10-28.

| Truy vấn | Byte quét (dry-run) |
|---|---:|
| kiểm đủ dữ liệu (`sufficiency`) | 184.015.856 |
| kiểm trùng (`dup_check`, có JSON cả dòng của đơn chờ xác nhận) | 4.467.896.274 |
| gom D-1 (`daily`) | 3.643.129.788 (lần trước 1.431.040.159) |
| kiểm từng ngày lịch sử (`hr_day_totals`) | 1.090.517.890 |
| bằng chứng dòng đơn (`hr_lines`, `hr_order_lines`, mỗi truy vấn) | 2.158.064.154 |

Số dòng (truy vấn đếm, 184,5 MB):
- cửa sổ 24–28/10: **86.210** dòng, trong đó hôm qua (28/10) có 18.114 dòng;
- dòng trước 2026 có trong bảng: 13.787.686;
- dòng 2025 mà câu D-1 lấy về: **0** (điều kiện `BETWEEN @start AND @end` với start = 2026-10-24).

## 4. Chạy thử trên bản sao (1.3)

- **Bản sao.** Tạo bằng SQLite backup API, nguồn mở `mode=ro`. 2.896.420.864 byte, schema 11, `quick_check` ok.
  `LOCALAPPDATA` và `DF_DATA_DIR` riêng, `DF_DISABLE_SCHEDULER=1`.
- **Cách chạy.** Gọi `sync.run_d1_sync` của bản cài 1.3.1, đúng hàm job runner gọi. Trên bản sao (chỉ bản sao), trần byte
  được hạ xuống 5·10⁹ để mọi truy vấn của lần chạy nằm dưới trần của nhiệm vụ. Trần không nằm trong `mapping_hash`.
- **Kết quả.** 18:41:10 → 18:41:22 (12,2 s), **lỗi `BQ_DATA_DUPLICATES`**. RAM đỉnh 153 MB (working set) / 480 MB
  (private).
  - Cửa sổ 24–28/10 có 86.210 dòng, 390.284 đơn vị.
  - Có **1.527 nhóm trùng, 3.173 dòng, thừa 1.646 dòng / 7.146 đơn vị**.
- **Không có dòng nào được ghi.** Trước = sau: `demand_daily` 2026 có 1.397.619 dòng / 43.107.741, ngày mới nhất 27/10;
  nhật ký thay đổi 1.381.855; dòng đang giữ 12.228.
- **Không ghi dòng 2025 nào.** Các dòng 2024 / 2025 có sẵn trong DB (4.075 + 19.255 dòng, không phải nguồn BIGQUERY) vẫn y
  nguyên.
- **Không lỗi mapping** với `deal_code`.
- data-check của bản sao sau lần chạy: xem mục 6.

**Bản chất dòng trùng** (truy vấn chỉ đọc, 4,47 GB):
- Cả 1.527 nhóm trùng **ở mọi cột nguồn**: cả `deal_code`, `customer_id`, `refresh_time` cũng giống nhau. Tức là bảng có
  dòng nhân đôi tuyệt đối, không phải một dòng đơn bị tách theo deal.
- Trong 3.173 dòng trùng, 2.379 dòng có `deal_code` NULL.
- Số nhóm theo ngày: 24/10 có 172, 25/10 có 85, 26/10 có 313, 27/10 có 639, 28/10 có 318.
- **Các dòng trùng mới xuất hiện sau lần dựng lại bảng.** Lần D-1 chạy tay sáng 28/10 (cửa sổ 22–27/10) không có dòng
  trùng nào; giờ chính các ngày 24–27/10 lại có.

Thống kê theo tháng toàn bảng (`evidence\dup_census_by_month.csv`, 3,03 GB):

| Tháng | Nhóm trùng | Dòng thừa | Đơn vị thừa | Tổng đơn vị (dòng không chờ xác nhận) |
|---|---:|---:|---:|---:|
| 2025-01 → 2025-05 | 0 | 0 | 0 | |
| 2025-06 → 2025-09 | 4 / 88 / 85 / 331 | | 17 / 174 / 223 / 665 | |
| 2025-10 | 8.627 | 9.248 | 47.889 | 5.950.042 |
| 2025-11 | 21.936 | 24.144 | 107.734 | 5.981.166 |
| 2025-12 | 16.037 | 17.168 | 105.351 | 6.230.400 |
| 2026-01 | 11.225 | 13.023 | 86.539 | 5.594.621 |
| 2026-03 | 19.191 | 21.490 | 138.021 | 6.268.259 |
| 2026-06 | 4.923 | 5.701 | 41.857 | 4.809.620 |
| 2026-10 | 7.272 | 7.560 | 33.651 | 2.231.766 |

Tháng nào từ 10/2025 cũng có dòng trùng, khoảng 0,6–2,2 % số đơn vị.

## 5. Xử lý (1.4) và đề xuất cho BI

- **Không đổi thiết lập nào trên production.** Giới hạn ngày nguồn đã là 2026-01-01. Đặt lại cũng không gỡ được lỗi, vì
  dòng trùng nằm trong 2026. Quyền giao chỉ cho đổi thiết lập này, nên chính sách dòng trùng (`BLOCK`) giữ nguyên. Không
  sửa code.
- **Không chạy D-1 production** (1.5).

Đề xuất cho BI:
1. **Bỏ dòng trùng tuyệt đối** trong `demand_planing_lightgbm`: mỗi dòng đơn đúng một lần. Rất có thể do bước ghép
   deal / dựng lại bảng ngày 29/10 nhân đôi dòng. Danh sách ở `BAT_THUONG_D1_TRUNG_DONG_20261024_20261028.xlsx`.
2. **Tách dữ liệu cho app đọc.** Cho app đọc một bảng hoặc view chỉ có `created_date >= 2026-01-01`, phân vùng theo
   `created_date`; dữ liệu 2025 để ở bảng hoặc view riêng. App đã cấu hình cột phân vùng `created_date`, nên sẽ tự cắt
   byte quét.
   - Hiện mỗi lần D-1 quét khoảng 9–12 GB, thay vì khoảng 3–4 GB như trước.
   - Riêng truy vấn kiểm trùng đã 4,47 GB, sát trần 5 GB của nhiệm vụ.
3. **Sau khi BI sửa:** chạy lại bước 1.3 trên bản sao mới, đạt thì mới chạy D-1 production.

## 6. data-check của bản sao

Chạy lúc 18:46 (159 s), so với data-check production sau cài đặt (29/10 13:37):

- **Giống production:** đúng 3 cảnh báo cũ, cùng số lượng (`finalized_days_changed` 230, `forecast_series_meta` 1,
  `history_source_drift` 294). Mọi kiểm tra khác OK.
- **Số dòng chỉ khác** ở `d0_snapshots` (84 → 87) và `job_runs` (189 → 192), do các D0 của production chạy trước lúc tạo
  bản sao. Không có thay đổi nào từ lần D-1 bị chặn.
- **Một FAIL do bản sao:** `accepted_model_files` (8). Bản sao không chép thư mục model, nên kiểm tra này không thấy file
  model. Không liên quan tới D-1.

## 7. Chạy lại sau khi BI sửa (29/10/2026 23:49) – DỪNG ở bước 1, bảng nguồn vẫn còn dòng trùng

**Bảng sau khi BI sửa** (metadata, không tốn byte):
- Sửa lúc **23:37 giờ VN** (16:37 UTC).
- 22.844.733 dòng (trước: 23.001.982, ít hơn 157.249 dòng); 4,44 GB.
- Vẫn không phân vùng, không clustering.

**Kiểm tra** từ 2026-01-01 (đúng mốc đọc của app) tới 28/10. Script tạo SQL bằng chính hàm của app 1.3.1
(`connector._src_cte`, `connector.dup_columns`), nên dùng đúng quy tắc của cổng D-1:
- trùng khi giống nhau ở mọi cột app so sánh, NULL = NULL;
- dòng WAIT_TO_CONFIRM được miễn.

Dry-run trước, mọi truy vấn dưới trần 5 GB:

| Truy vấn | Byte quét | Thời gian |
|---|---:|---:|
| Thống kê theo tháng | 2.946.498.560 | 2,4 s |
| Danh sách đủ cột | 4.437.573.632 | 12,8 s |

**Ngày dữ liệu mới nhất: 28/10/2026** (hôm qua). Đủ mọi ngày từ 01/01.

| Tháng | Dòng | Nhóm trùng | Dòng trùng | Dòng thừa | Đơn vị thừa |
|---|---:|---:|---:|---:|---:|
| 2026-01 | 1.235.810 | 465 | 1.674 | 1.209 | 10.777 |
| 2026-02 | 974.309 | 322 | 1.052 | 730 | 7.752 |
| 2026-03 | 1.193.586 | 210 | 512 | 302 | 7.130 |
| 2026-04 | 965.332 | 167 | 474 | 307 | 3.350 |
| 2026-05 | 1.026.150 | 308 | 948 | 640 | 1.312 |
| 2026-06 | 995.346 | 377 | 1.238 | 861 | 1.989 |
| 2026-07 | 955.176 | 772 | 2.800 | 2.028 | 12.502 |
| 2026-08 | 734.548 | 345 | 1.124 | 779 | 1.848 |
| 2026-09 | 517.077 | 121 | 444 | 323 | 768 |
| 2026-10 (tới 28/10) | 509.850 | 86 | 344 | 258 | 519 |
| **Tổng** | **9.107.184** | **3.173** | **10.610** | **7.437** | **47.947** |

- **Cả 3.173 nhóm đều trùng tuyệt đối:** giống nhau ở cả 21 cột nguồn, kể cả `customer_id`, `deal_code` và
  `refresh_time`.
- **Ít hơn trước nhiều, nhưng chưa hết.** Ví dụ tháng 10 trước còn 7.272 nhóm, nay 86 nhóm.
- **Trong cửa sổ D-1 kế tiếp (24–28/10) còn 40 nhóm, 160 dòng**, nên cổng D-1 vẫn chặn `BQ_DATA_DUPLICATES`.
  - Theo ngày: 24/10: 4 nhóm; 25/10: 2; 26/10: 2; 27/10: 30; 28/10: 2.
- **Bảng cũ không có các dòng trùng này.** Lần D-1 production gần nhất (28/10 09:40, cửa sổ 22–27/10, 103.057 dòng) có
  0 nhóm trùng. Vậy dòng trùng xuất hiện khi BI dựng lại bảng.

**Theo nhiệm vụ: DỪNG.**
- Không chạy D-1 trên bản sao, không chạy D-1 production.
- Không đổi cấu hình.
- Chưa làm tiếp C5–C7.

**Bằng chứng** (`D:\Buymed\Lightgbm AI\reports\kiem-tra-d1-2025-20261029\`):
- `evidence\chay-lai-sau-bi-sua\BAT_THUONG_D1_TRUNG_DONG_20260101_20261029.xlsx`: 10.610 dòng, đủ 21 cột nguồn, cùng cột
  `ly_do`, `group_no`, `rows_in_group` và số giá trị khác nhau của từng cột không so sánh.
- `evidence\chay-lai-sau-bi-sua\`: `census_2026_by_month.csv`, `census_2026_summary.json`, `dup_rows_summary.json`,
  `table_meta.json` và `bq_queries.json` (SQL, byte, job id).
- `code\d1_recheck.py`, `code\d1_recheck_summary.py`, `code\last_dup_check.py`.

## 8. Chạy lại lần 2 (30/10/2026 01:23–01:31) – hết dòng trùng; DỪNG ở bước 2 vì nguồn chưa có ngày 29/10

**Bước 0.**
- Không có build, test, train hay backtest nào khác đang chạy.
- RAM trống lúc 01:18 chỉ có 1,7 GB. Tôi chờ tới 01:23, khi RAM lên 3,1 GB, rồi mới bắt đầu.

### 8.1 Bảng nguồn (bước 1; chỉ đọc, dry-run trước, trần 5 GB)

**Bảng** (1.1):
- Sửa lần cuối lúc **30/10 01:16:41 giờ VN** (29/10 18:16:41 UTC).
- 22.835.276 dòng, 4,44 GB, 21 cột.
- **Vẫn không phân vùng, không clustering.**

**Byte quét** (dry-run các truy vấn của D-1 kế tiếp, cửa sổ 24–29/10):

| Truy vấn | Byte |
|---|---:|
| Kiểm tra đủ dữ liệu | 182.682.208 |
| Kiểm tra trùng | 4.435.451.970 |
| Đọc dữ liệu ngày | 3.617.100.832 |
| Tổng theo ngày (kiểm tra lịch sử) | 1.082.720.465 |
| Dòng đơn (bằng chứng) | 2.142.627.806 |

- Mỗi truy vấn dưới 5 GB.
- Trần của production là 20 GiB, không đổi.

**Dòng trùng** (1.2):

| Phạm vi | Quy tắc | Byte | Kết quả |
|---|---|---:|---|
| 2026-01-01 → 28/10, theo từng tháng | của app: 14 cột nguồn đã map, miễn WAIT_TO_CONFIRM | 2.945.449.984 | **0 nhóm ở cả 10 tháng** (9.099.747 dòng) |
| Toàn bảng 01/2025 → 10/2026 | trùng tuyệt đối 21 cột | 4.435.476.480 | **0 nhóm ở cả 22 tháng** (22.835.276 dòng), kể cả dòng chờ xác nhận |

**Ngày dữ liệu** (1.3):
- **Mới nhất là 28/10.** Ngày 29/10 (hôm qua) có **0 dòng**.
- Đủ 301/301 ngày từ 01/01 tới 28/10.

### 8.2 Thử D-1 trên bản sao DB production (bước 2)

**Bản sao:** tạo lúc 01:25 bằng backup API, nguồn mở `mode=ro`:
- `scratchpad\d1test2\data\db\app.db`, 2,91 GB, schema 11, quick_check ok;
- `DF_DATA_DIR` và `LOCALAPPDATA` riêng, scheduler tắt;
- trần BigQuery của bản sao đặt 5e9 byte.

| Lần chạy (`sync.run_d1_sync` của bản 1.3.1) | Thời gian | Kết quả | Ghi gì |
|---|---:|---|---|
| Như chạy tay lúc này (trước mốc dự phòng 06:10) | 0,0 s | `WAITING_FOR_SIGNAL`: chưa có bảng tín hiệu hoàn tất, nên chờ tới 06:10 | không |
| Như sau mốc dự phòng 06:10 | 2,8 s | **`SOURCE_INCOMPLETE`**: ngày 29/10 có 0 dòng, cần ≥ 0,5 × trung bình 7 ngày trước (17.213 dòng) | không |
| **Mô phỏng** (chỉ trên bản sao): ngày VN ghim 29/10, nên hôm qua = 28/10, cửa sổ 24–28/10 | 73,8 s, RAM đỉnh 0,8 GB | **SUCCEEDED**, không bị chặn `BQ_DATA_DUPLICATES` | xem dưới |

**Mô phỏng.** Ghim ngày bằng cách thay hàm `today_vn` trong tiến trình thử; không sửa code app.
- Đọc 84.543 dòng, hợp lệ 84.543.
- Chuỗi-ngày: ghi 15.008, gồm thêm 3.024, sửa 419, giữ nguyên 11.511; bỏ 54.
- Dòng đơn mà nguồn đã bỏ được giữ lại: +336.
- Lịch sử thay đổi: +3.693 dòng.
- Giờ mở bán: OK cả 14.954 dòng.
- Dữ liệu mới nhất của bản sao: 27/10 → 28/10.

**data-check sau mô phỏng** (39 s):
- Một FAIL: `accepted_model_files` 8, do bản sao không chép file model.
- Các cảnh báo:
  - `history_source_drift` 296 (trước 294);
  - `finalized_days_changed` 232 (trước 230);
  - `forecast_series_meta` 1 (cảnh báo cũ).
- Mọi kiểm tra khác OK.

**Phát hiện mới: bảng dựng lại khác lịch sử app đang lưu.**
- Lần kiểm tra lịch sử của D-1 (01/01–23/10) báo **DIFF ở cả 296/296 ngày**.
- Nguồn mới ít hơn **5.188** cặp SKU×FC×ngày và **123.368** đơn vị.
  - Ví dụ 01/01: nguồn 3.775 cặp / 73.003 đơn vị, app lưu 3.789 / 73.717.
- D-1 chỉ cảnh báo, không chặn, và chỉ ghi lại cửa sổ 24–28/10. Các ngày cũ giữ số của bảng cũ.
- Muốn lịch sử khớp bảng mới thì phải chạy backfill có xem trước và sao lưu. Việc này **cần chủ dự án quyết định**.

**Kết luận bước 2: KHÔNG ĐẠT, DỪNG.**
- D-1 thật (cửa sổ tới hôm qua 29/10) không chạy được vì nguồn chưa có ngày 29/10.
- **Không chạy D-1 production**, không đổi cấu hình, chưa làm bước 4 (C5–C7).
- Mô phỏng cho thấy phần còn lại của đường nạp chạy được trên bảng đã sửa.

**Lịch tự động sáng 30/10** (không do tôi chạy):
- D-1 dò từ 05:00, mốc dự phòng 06:10.
- Nếu BI nạp xong ngày 29/10 trước lúc đó, D-1 production sẽ tự chạy.
- Huấn luyện 05:20 chỉ chạy khi D-1 thành công trước 05:40.

**Bằng chứng** (`evidence\chay-lai-lan-2\`):
- `table_meta.json`, `census_2026_by_month.csv`, `census_2026_summary.json`;
- `whole21_by_month.csv`, `whole21_summary.json`;
- `d1_dryrun.json`, `bq_queries.json`;
- `d1_copy_asis.json`, `d1_copy_fallback.json`, `d1_copy_sim28.json`, `datacheck_copy2.json`.

Code: `code\d1_recheck.py` (thêm `whole21`, `window`), `code\run_d1_copy2.py`.

## 9. Nạp lại lịch sử theo bảng nguồn mới (30/10/2026)

### 9.1 Quyết định của chủ dự án (30/10/2026), thay quy tắc KEEP_OBSERVED_LINES ngày 22/10/2026

> Đơn bị BI loại khỏi bảng nguồn là đơn khách hủy (không còn nhu cầu / đặt nhầm) → KHÔNG phải demand. Dữ liệu app
> phải ĐỒNG BỘ THEO BẢNG NGUỒN, cả lịch sử lẫn các lần D-1 sau này.

**Thiết lập có sẵn của app:** `data_policy.history_change_policy`.
- `FOLLOW_SOURCE`: dữ liệu lưu = bảng nguồn; mọi dòng đơn đang được "giữ lại" của các cặp được ghi đều được giải phóng
  (`OWNER_DECISION`).
- `KEEP_OBSERVED_LINES` (mặc định): giữ lại dòng đơn mà nguồn đã bỏ.

**Đã đổi trên production lúc 30/10/2026 02:21:33 giờ VN:**
- `settings_history` thêm 1 dòng (55 → 56), section `data_policy`, `changed_at` 2026-10-29T19:21:33Z.
- Ghi chú: "OWNER DECISION 30/10/2026 … KEEP_OBSERVED_LINES -> FOLLOW_SOURCE (replaces the owner rule of 22/10/2026)".
- Có audit `SETTINGS_SAVED`. Mọi khoá khác của section giữ nguyên (đã kiểm tra).
- Bằng chứng: `reports\backtest-dulieu-moi-20261030\evidence\b3\prod_policy.json`.

### 9.2 Bước 1: nạp lại trên bản sao – ĐẠT

**Bản sao DB production** tạo 01:54 bằng backup API, nguồn mở `mode=ro`, SHA `F1D50EFC…7445ED`.
- Dùng đúng hai hàm của app: `sync.backfill_preview` và `sync.run_d1_sync(backfill…)`, như `POST /api/sync/backfill/preview` và
  `POST /api/sync/backfill`.
- Cửa sổ 01/01–28/10, phiên bản nguồn 01:16:41 ngày 30/10.

**Xem trước với chính sách cũ `KEEP_OBSERVED_LINES`** (`BFP-20261029185603-B5E929`, 404 s): **không khớp nguồn.**
- App sẽ giữ lại thêm 8.070 dòng / 183.467 đơn vị, chủ yếu `NO_EVIDENCE`: bản cũ đã quá thời gian time travel 7 ngày, nên app không
  đọc được dòng cũ để làm bằng chứng.
- Tổng đơn vị "giữ lại" sau khi nạp: 259.196.

**Với `FOLLOW_SOURCE`:**
- Xem trước `BFP-20261029190327-E1B922` (280 s), rồi áp dụng (440 s).
- Nguồn đọc được 9.099.747 dòng = 42.534.115 đơn vị.
- Cặp SKU×FC×ngày: thêm 4.784; sửa 1.097 về số lượng (173.546 về nội dung); bỏ 9.207.
- Giải phóng 12.228 dòng đang "giữ lại" (92.042 đơn vị). Sau khi nạp, còn 0 đơn vị giữ lại.

**Đối soát** (`bang_doi_soat_backfill.xlsx`): **602/602 ô ngày×kho khớp nguồn**, đủ 10 tháng.

| | Cặp SKU×FC×ngày | Đơn vị |
|---|---:|---:|
| Nguồn | 1.377.958 | 42.534.115 |
| Bản sao sau nạp | 1.377.958 | 42.534.115 |
| Trước khi nạp (đến 27/10) | 1.382.381 | 42.665.877 |
| Thay đổi | −4.423 | −131.762 (−0,31 %, đã gồm +ngày 28/10) |

**data-check của bản sao:**
- Cảnh báo lệch lịch sử với nguồn (`history_source_drift`) đã hết.
- `finalized_days_changed` 300: số thực bán đã chốt giữ nguyên làm ảnh chụp KPI.
- FAIL duy nhất là `accepted_model_files`, do bản sao không chép file model.

### 9.3 Bước 3: production – DỪNG ở chốt chặn 3.3, CHƯA nạp lại

**3.1 Sao lưu:**
- `backups\backup-20261030-021827-pre-backfill-20261030.zip`: 264 MB, SHA `95D7821B…910E6`, gồm DB + 20 file model.
- `backups\config-20261030-021827-pre-backfill-20261030.json`: mọi section cấu hình + `storage.json`, SHA `2CD8B0EB…5531`.
- **Thử khôi phục đạt** (thư mục tách riêng): integrity ok, 44 bảng, 9.092.129 dòng, không bảng nào lệch số dòng; 20 model trùng
  SHA.

**3.2 Đổi chính sách:** xem 9.1.

**3.3 Chốt chặn:**
- Bản xem trước trên production `BFP-20261029192210-4971D1` (286 s, qua API) **giống hệt bản sao**: cùng số thêm / sửa / bỏ, cùng
  −131.762 đơn vị, cùng digest kế hoạch `907b6b5126f0cd4d`. Tổng xoá lệch bản sao 0 %.
- Production trước khi nạp = bản sao trước khi nạp, khớp từng ngày×kho.
- **Nhưng 2 ngày xoá quá 5 % đơn vị của ngày đó, nên DỪNG, không áp dụng:**

| Ngày | Đang lưu | Theo nguồn | Đơn vị bị xoá | Tỷ lệ |
|---|---:|---:|---:|---:|
| 19/08 | 117.702 | 107.872 | 9.905 | 8,42 % |
| 21/10 | 96.250 | 91.093 | 5.157 | 5,36 % |

- Ngày 19/08: 98 % số bị xoá là một cặp, `MEDX.OPC-COR-001` kho BD (9.684 đơn vị / 25 đơn).
- Ngày 21/10: chủ yếu `MEDX.dmts04a5083e06ba` BD (−2.343) và `MEDX.DMTS-MER-GLU-002` BD (−1.200).

**Phát hiện: phần lớn chênh lệch không phải đơn hủy lẻ, mà là cả chuỗi bị loại khỏi bảng nguồn.**
- **196 chuỗi SKU×FC mất toàn bộ lịch sử 2026, 239.855 đơn vị.** Lớn nhất:
  - `MEDX.74Q61PGE` BD: 45.379
  - `MEDX.OPC-COR-001` BD: 45.077 (kho HN của mã này vẫn còn)
  - `MEDX.a39c3a20fb80` HN: 20.208
  - `MEDX.USP-CEF-0056` BD: 12.052
- 21 chuỗi mới (20.301 đơn vị).
- Chỉ 3 chuỗi giảm hơn 20 % mà vẫn còn (130 đơn vị).
- Cần BI xác nhận vì sao các chuỗi này bị loại: thay đổi phạm vi sản phẩm, gán kho hay trạng thái SKU. Có xác nhận rồi mới
  nạp lại production.

**Danh sách:**
- `evidence\b3\chot_chan_xoa_theo_ngay.xlsx`: theo ngày, các ngày trên 5 %, mọi cặp bị giảm.
- `evidence\b3\ngay_tren_5pct_cap_giam.csv`
- `evidence\b3\chuoi_bi_bo_hoac_giam.xlsx`: chuỗi mất hết, chuỗi giảm trên 20 %, chuỗi mới.

**Trạng thái production sau bước 3:**
- Dữ liệu demand KHÔNG đổi.
- Chính sách đã là `FOLLOW_SOURCE` theo quyết định 9.1.
- Lần D-1 tự động kế tiếp (dò từ 05:00, dự phòng 06:10, khi nguồn có ngày 29/10) sẽ đồng bộ cửa sổ 24–29/10 theo nguồn. Tỷ lệ
  xoá các ngày 24–28/10 trên bản sao đều dưới 5 % (cao nhất 25/10: 4,58 %).

### 9.4 Các lần D-1 sau (3.5)

**Tự bỏ dòng nguồn đã xoá: CÓ, khi `history_change_policy = FOLLOW_SOURCE`.**
- `history_sync.prepare` đặt mục tiêu ghi = dòng nguồn cho mọi cặp trong cửa sổ D-1 (`watermark − late_data_lookback_days`
  (3) … hôm qua).
- Cặp không còn trong nguồn bị bỏ (`series_days_removed`). Mỗi thay đổi ghi vào `demand_change_log`.
- Quay lui được từng lần nạp bằng `python -m app.cli sync-rollback`.

**Chốt chặn tỷ lệ xoá bất thường: CHƯA CÓ** cho D-1 / backfill. App hiện có:
- Lần đọc rỗng không bao giờ thay ngày đã lưu (`EMPTY_READ`).
- Ngày hôm qua phải đủ ≥ 0,5 × trung bình 7 ngày (`fallback_min_rows_ratio` 0,5; chỉ ở đường dự phòng).
- Cổng dòng trùng `BLOCK`.
- Nguồn đổi phiên bản giữa lúc đọc thì không ghi.
- Kiểm tra lịch sử ngoài cửa sổ mỗi ngày (`history_day_check`, chỉ cảnh báo).
- Backfill phải xem trước và tự sao lưu.

### 9.5 Bước 2: backtest phương án chốt trên bản sao đã đồng bộ – ĐÃ ĐÓNG GÓI (chưa chấm)

- Thư mục: `reports\backtest-dulieu-moi-20261030\`, với `PREREGISTRATION.md` SHA `AB4356CF…EB03D894`.
- Chạy 21/21 lô trong 33,1 phút, 16.495.192 dòng.
- Rò rỉ: 171/171.
- Gói: `package\`. Chi tiết trong README của thư mục.

### 9.6 Đề xuất chốt chặn

**Đề xuất (KHÔNG sửa code trong đợt này):**
1. Thêm thiết lập `data_policy.max_day_removal_share` (ví dụ 0,05). D-1 / backfill tính tỷ lệ đơn vị bị bỏ của từng ngày trước khi
   ghi; vượt ngưỡng thì chặn như cổng dòng trùng: xuất danh sách, cảnh báo, không ghi.
2. Thêm ngưỡng cho chuỗi mất toàn bộ trong cửa sổ, đi kèm ngưỡng số chuỗi.
3. Hiện cột "đơn vị bị xoá theo ngày" ngay trên màn hình xem trước backfill.
