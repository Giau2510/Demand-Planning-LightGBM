# Performance report - master audit 21/10/2026

Số đo thật; chỗ nào chưa đo ghi **NOT_MEASURED**. Đo trên: (a) production 1.2.8 qua `GET` (chỉ đọc), (b) bản sao DB production
(SQLite backup API, `mode=ro`) trong môi trường cô lập (`DF_DISABLE_SCHEDULER=1`, `LOCALAPPDATA` / `DF_DATA_DIR` riêng), (c) BigQuery
dry-run. Không chạy `VACUUM` / `ANALYZE` / migration / xóa trên dữ liệu thật. Baseline chi tiết (bảng đầy đủ, JSON, script):
`C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p25\perf\baseline.md`
và `baseline.json`. Đơn vị: MiB = 2^20 byte.

## 1. Kết quả trước / sau

"Trước" = mã HEAD `a9486bb` (gói 1.2.9, lấy từ checkpoint `source-1.2.9-before-master-audit-20261021-010045.zip`); "sau" = working
tree. Cùng bản sao DB (schema 9, 1.358.317 dòng BIGQUERY), cùng máy, FastAPI TestClient trong tiến trình, 5 mẫu mỗi endpoint, 3 vòng
xen kẽ trước/sau; số là trung vị của 3 trung vị.

| Chỉ số | Trước | Sau | Chênh lệch | Phương pháp đo |
|---|---:|---:|---:|---|
| `GET /api/features/registry` | 9.044 ms | 1.471 ms | **−83,7 %** | cùng bản sao, 3 vòng × 5 mẫu; nội dung trả về giống hệt (SHA-256 thân JSON) |
| `GET /api/dashboard` | 1.261 ms | 1.198 ms | −5,0 % (nhiễu) | như trên, nội dung giống hệt |
| `GET /api/system/status` | 764 ms | 729 ms | −4,6 % (nhiễu) | như trên, nội dung giống hệt |
| Truy vấn `feature_registry.coverage` | 8.329 ms (lạnh 25.961) | 467 ms | **−94,4 %** | bản sao, kết nối mới mỗi lần, 5 lần; cùng kết quả |
| Truy vấn `pipeline.data_lineage` | 8.580 ms | 1.032 ms | **−88,0 %** | như trên; cùng kết quả |
| `demand.load_demand` (1.358.317 dòng, 13 cột) | 15.281 ms | 6.192 ms | **−59,5 %** | pandas `read_sql_query`, 3 lần; DataFrame giống hệt (giá trị, kiểu, thứ tự) |
| RAM đỉnh tiến trình API (working set) | 158,1 MiB | 157,7 MiB | ~0 % | GetProcessMemoryInfo, cùng tập endpoint (vòng 3) |
| Thời gian khởi động app (TestClient) | 2.760 ms | 1.897 ms | không quy cho thay đổi | 3 lần mỗi bên, thứ tự xen kẽ; thay đổi không chạm đường khởi động → coi là nhiễu bộ đệm OS |
| Dung lượng gói / cài đặt | 88,1 MiB zip / 256,7 MiB | không đổi | 0 | gói không được build lại (cần commit + phê duyệt) |
| BigQuery byte mỗi lần D-1 | 1.342.644.619 × 2 | không đổi | 0 | dry-run SQL của app; không đổi logic |
| Thời lượng test backend | 466,7 s (647 passed, QA phát hành 20/10) | 342,2 s (661 passed) | không so sánh được | số test và tải máy khác nhau |
| Build frontend | 4,37 s | 4,55 s | +4 % (nhiễu) | `npm run build` |

Ước lượng trên production (INFERRED): trang Danh mục đặc trưng hiện 13,5 s trung vị (production, `GET` thật) sẽ giảm tương tự (~−80 %) sau
khi phát hành; chưa đo được trên production vì không triển khai.

## 2. Thay đổi đã làm (chỉ thay đổi có số đo và kết quả giống hệt)

| Thay đổi | File | Lý do | Test |
|---|---|---|---|
| `NOT INDEXED` cho coverage | `backend/app/ml/feature_registry.py` | qua index khóa SQLite đọc lại từng dòng cho các cột không có trong index | `test_v129h_perf_scans.py` |
| `NOT INDEXED` cho lineage | `backend/app/ml/pipeline.py` | như trên | như trên |
| `NOT INDEXED` + `ORDER BY order_date, sku_id, fc_id` cho load_demand | `backend/app/data/demand.py` | như trên; ORDER BY giữ đúng thứ tự của index | như trên |

Cùng kỹ thuật đã được dùng ở 1.2.7 (`ops_routes`) và 1.2.8 (`demand.fingerprint`). Rollback: hoàn lại 3 câu SQL (không có thay đổi dữ liệu).
Đánh đổi: với một phạm vi rất nhỏ trong DB có phạm vi lớn khác (vd. demo cạnh BIGQUERY), quét tuần tự đọc cả bảng (~0,5 s) thay vì vài trang
index; `load_demand` dùng file tạm SQLite để sắp xếp (~100-150 MB, tạm thời).

## 3. Baseline production và bản sao (không đổi trong batch này)

| Endpoint production 1.2.8 (`GET`, 5 mẫu, CPU < 30 %) | Trung vị | Max | Byte |
|---|---:|---:|---:|
| `/api/features/registry` | 13.485 ms | 23.558 ms | 65.869 |
| `/api/dashboard` | 1.287 ms | 1.592 ms | 22.374 |
| `/api/system/status` (mọi trang) | 860 ms | 7.519 ms | 19.203 |
| `/api/forecast-runs/{id}/summary?horizon=15&limit=200` | 668 ms | 875 ms | 37.830 |
| `/api/history/rows` (100 dòng) | 409 ms | 492 ms | 67.663 |
| `/api/history/summary` | 356 ms | 760 ms | 15.960 |
| `/api/forecast-runs/{id}` | 187 ms | 2.396 ms | 176.713 |
| `/api/settings` | 46 ms | 49 ms | 11.374 |
| `/api/health` | 22 ms | 30 ms | 64 |
| 12 endpoint còn lại (bigquery/status, schedules, ...) | NOT_MEASURED | | | 

Truy vấn SQLite chậm khác (bản sao, chưa sửa): vòng chốt actual lần đầu sau nâng cấp 8.941 ms (292 truy vấn theo ngày, một lần);
`demand.excluded_summary` 2.479 ms; `open_hours.window_check` ~1.068 ms (proxy schema 6); `demand.fingerprint` 607 ms.

## 4. BigQuery

| Truy vấn (dry-run, SQL của app, ánh xạ production) | Cửa sổ 4 ngày | Toàn kỳ 01/01-19/10 |
|---|---:|---:|
| Cổng trùng (`dup_check`) | 1.342.644.619 | 1.342.644.619 |
| Tổng hợp D-1 (`daily`) | 1.342.644.619 | 1.342.644.619 |
| Tổng hợp nếu bật `customer_id` (chưa bật) | 1.414.336.979 (+5,3 %) | 1.414.336.979 |

Bảng nguồn không phân vùng, không clustering (MA-07): bộ lọc ngày không giảm byte; mỗi D-1 tăng dần quét ~2,69 GB. Chạy thật (kiểm toán):
cổng trùng 2,7 s, 1,34 GB. Đề xuất phía nguồn: phân vùng theo `created_date`, clustering `sku_code, fc_code` (ước tính INFERRED: ~18 MB mỗi
truy vấn cho cửa sổ 4 ngày). Gộp cổng trùng vào truy vấn tổng hợp sẽ giảm một nửa byte nhưng đổi thứ tự xử lý đã duyệt (kiểm trùng trước
khi tổng hợp) - chỉ đề xuất.

## 5. Dung lượng (chỉ đo, không xóa)

| Vị trí | Kích thước | Ghi chú / đề xuất |
|---|---:|---|
| `%LOCALAPPDATA%\Programs\DemandForecast` | 4,96 GiB (18 phiên bản × ~283 MiB) | giữ bản đang chạy + bản rollback + 1-2 bản mới nhất; có thể thu hồi ~4 GiB (cần phê duyệt) |
| `dist\` | 1,42 GiB (16 gói) | `prune-artifacts.ps1 -Keep 1.2.6 -KeepLatest 2` (dry run): **1.167,6 MB** có thể thu hồi; chưa `-Apply` |
| `backups\` | 1,77 GiB (53 file, gần đây 82 MiB/file) | chính sách giữ theo ngày/tuần/tháng - cần phê duyệt |
| DB `app.db` | 704 MiB; `demand_daily` 384 MiB (khóa chính 168 MiB), `forecast_values` 179 MiB | mỗi lần dự báo +44 MiB; ~76 MiB/ngày (ước tính) ≈ 27 GiB/năm nếu không có lưu giữ; `scope_key` 70 ký tự lặp ở mỗi dòng và index (migration cần duyệt); không có `sqlite_stat1`; freelist 0 |
| `checkpoints\` | 270,5 MiB (48 zip) | giữ (lịch sử); có thể nén lại / chuyển kho lạnh |
| Gói portable | 88,1 MiB zip / 256,7 MiB cài | thư mục test của scipy/pandas/numpy 35,9 MiB (nén 8,6 MiB) có thể bỏ: −9,8 % zip, −14 % cài - cần sửa `build-package.ps1` + diễn tập gói |
| `logs\` | 1,33 MiB | `app.log` xoay 10 MiB × 5; `logs\development` (55 file), `server.out.log`, `deploy-*.log` không xoay - nhỏ, chưa cần làm |
| `data\runtime\db\app.db.migrating-shm/-wal` | 32 KB | file thừa từ 14/10; không xóa |

## 6. Đề xuất chưa làm (theo thứ tự lợi ích)

1. Phía nguồn: phân vùng + clustering bảng D-1 (MA-07).
2. `/api/system/status` (mọi trang, 0,73-0,86 s ấm, tới 9 s lạnh): cache theo phiên bản dữ liệu hoặc thử `mmap_size` (đo trên bản sao trước).
3. Chính sách lưu giữ: phiên bản cài, gói, backup, dữ liệu dự báo cũ (MA-13) - cần phê duyệt.
4. Bỏ thư mục test khỏi gói (MA-14) ở lần phát hành tới, kèm diễn tập cài đặt cô lập.
5. Vòng chốt actual lần đầu: gộp 292 truy vấn thành 1 (MA-12).
6. GZip cho bundle JS 683,8 kB (gzip 208 kB) - lợi ích nhỏ trên máy đơn.
