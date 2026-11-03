# Findings register - master audit 21/10/2026

Mỗi finding theo chuỗi: bằng chứng → nguyên nhân gốc → sửa → test hồi quy → kết quả test → rủi ro còn lại.
Trạng thái: **FIXED_LOCAL** (đã sửa trong working tree, có test, CHƯA phát hành / chưa commit), **VERIFIED** (đã kiểm, không có lỗi),
**BLOCKED** (chờ quyết định nghiệp vụ / nguồn / phê duyệt), **UNRESOLVED**, **PROPOSED** (đề xuất, chưa làm), **NOT_RUN**.
"Sửa" luôn là mã nguồn trong `D:\Buymed\Lightgbm AI` (working tree trên `a9486bb`); production 1.2.8 không bị thay đổi.

| ID | Mức | Hạng mục | Trạng thái |
|---|---|---|---|
| MA-01 | Cao (kiểm) | Hậu tố SKU / item bị dùng để suy ra FC | VERIFIED - không vi phạm |
| MA-02 | Cao | Cổng trùng coi đơn WAIT_TO_CONFIRM chưa có so_code là trùng hoàn toàn | FIXED_LOCAL |
| MA-03 | Cao (nghiệp vụ) | 6 khóa MULTI_ITEM | BLOCKED - quy tắc gộp |
| MA-04 | Trung bình | Combo 931 khóa | VERIFIED (một phần INFERRED); quyết định nghiệp vụ |
| MA-05 | Trung bình | customer_id: rò rỉ, khả dụng, chi phí | VERIFIED trên code; thử nghiệm BLOCKED |
| MA-06 | Cao | Nguồn dựng lại thay đổi lịch sử so với dữ liệu app | UNRESOLVED (nhóm nguồn) |
| MA-07 | Trung bình | Bảng nguồn không phân vùng: mỗi D-1 quét ~2,7 GB | PROPOSED (phía nguồn) |
| MA-08 | Trung bình | Trang Danh mục đặc trưng 9-24 s (coverage qua index) | FIXED_LOCAL |
| MA-09 | Thấp | Lineage của lần huấn luyện 8,6 s (qua index) | FIXED_LOCAL |
| MA-10 | Trung bình | load_demand 15,3 s (huấn luyện / dự báo / giải thích) | FIXED_LOCAL |
| MA-11 | Thấp | /api/system/status quét toàn bảng mỗi lần mở trang (0,76 s; lạnh 7,5-9,2 s) | PROPOSED |
| MA-12 | Thấp | Lần chốt actual đầu tiên sau nâng cấp: 292 truy vấn theo ngày (8,9 s) | PROPOSED |
| MA-13 | Trung bình | Dung lượng: phiên bản cài đặt, gói, backup, DB tăng ~76 MiB/ngày | PROPOSED (không xóa gì) |
| MA-14 | Thấp | Gói portable chứa thư mục test của thư viện (35,9 MiB) | PROPOSED |
| MA-15 | Thấp | D-0 so khớp toàn dòng: dòng chờ xác nhận giống nhau có thể bị chặn | RISK - chưa quan sát |
| MA-16 | Thấp | File thừa `app.db.migrating-shm/-wal` (14/10) trong `data\runtime\db` | PROPOSED (không xóa) |
| MA-17 | Thông tin | Test real-BigQuery cũ mã hóa quy tắc cũ | FIXED_LOCAL (kỳ vọng đổi có lý do) |
| MA-18 | Cao (vận hành) | D-1 06:00 21/10 trên production 1.2.8 sẽ bị chặn | BLOCKED (cần phát hành / nguồn) |

---

### MA-01 - Hậu tố SKU / item không được dùng để suy ra FC (VERIFIED)
- **Bằng chứng (code):** rà soát toàn repo (backend, tests, frontend, scripts, docs) bằng grep + agent trinh sát: không có `split` /
  regex / `SUBSTR` / cắt chuỗi nào trên mã SKU hoặc item; FC chỉ đến từ ánh xạ `fc_id ← fc_code`; D-1 `GROUP BY` ngày, `sku_id`, `fc_id`
  (`backend/app/bq/connector.py`, `_daily_sql`); item chỉ được ĐẾM (`COUNT(DISTINCT ...)`) cho trạng thái giờ mở bán; Excel / demo
  gộp theo `order_date, sku_id, fc_id` (`backend/app/data/demand.py:aggregate_batch`). Phân loại từng điểm: VALID (không CONFIRMED_BUG).
- **Bằng chứng (dữ liệu, chỉ kiểm toán):** mọi hậu tố .1-.4 có dòng ở cả BD và HN; 108 item × ngày bán ở 2 FC; `total_open_hours` theo
  item × ngày (0 xung đột).
- **Rủi ro chữ nghĩa (RISK, lịch sử):** `CHANGELOG.md` mục 1.2.9 đợt 4 và `docs/BIGQUERY.md` (đoạn số liệu .2 ở FC HN) đặt số dòng theo
  FC cạnh hậu tố; cả hai đã được rút lại ngay trong cùng mục (đợt 5). Không sửa văn bản lịch sử.
- **Test:** sẵn có `test_v129e_item_suffix.py`, `test_v129e_real_bq_item_suffix.py`; mới `test_v129h_pending_orders_grain.py`
  (FC từ cột FC, 2 FC cho cùng SKU, .1/.2 cùng FC = 1 khóa, đảo hậu tố không đổi trạng thái, SKU đầy đủ khác nhau không gộp, tổng số lượng
  giữ nguyên) và `test_v129h_real_bq_pending_grain.py` (cùng các trường hợp trên BigQuery thật, dòng inline 0 byte). Kết quả: PASS.
- **Rủi ro còn lại:** không.

### MA-02 - Đơn chờ xác nhận chưa có so_code bị coi là trùng hoàn toàn (FIXED_LOCAL)
- **Bằng chứng:** snapshot 20/10 22:18: 18 nhóm / 67 dòng / 49 dòng dư giống nhau ở 15 cột so sánh, tất cả `WAIT_TO_CONFIRM` +
  `so_code` NULL; trong mỗi nhóm số khách khác nhau = số dòng (18/18). 0 nhóm trùng có `so_code`. Workbook
  `demandforecast_audit_duplicates_wait_to_confirm_20261021.xlsx`.
- **Nguyên nhân gốc:** quy tắc trùng hoàn toàn so NULL = NULL trên mọi cột ánh xạ (`connector._dup_sql`, tổng kiểm tra toàn kỳ và dòng
  kiểm soát `TOTAL_READ` của D-1). Đơn chờ xác nhận chưa có mã, và `customer_id` không được ánh xạ, nên các đơn của nhiều khách không
  phân biệt được. Trái với quy tắc chủ hệ thống (21/10): `so_code` NULL ở `WAIT_TO_CONFIRM` là bình thường.
- **Sửa:** `connector.PENDING_STATUSES = ("WAIT_TO_CONFIRM",)`, `_pending_expr`, `_exact_dup_rows_expr`: dòng `order_id` NULL + trạng thái
  chờ xác nhận không bao giờ là trùng hoàn toàn, ở cả ba nơi đếm trùng; `DROP_EXACT` giữ các dòng này; số dòng / số lượng / số nhóm
  giống hệt được đếm riêng (`pending_no_order_code`) trên trang BigQuery (`frontend/src/pages/BigQuery.tsx`, `i18n.tsx`) và trang
  Summary của báo cáo trùng (`bq/dup_report.py`). Dòng khác (có `so_code`, hoặc NULL ở trạng thái khác) giữ nguyên quy tắc. Chỉ áp dụng
  khi cả `order_id` và `order_status` được ánh xạ. Không lọc, không điền `so_code` giả, không dùng `customer_id` làm khóa.
- **Test:** `test_v129h_pending_orders_grain.py` (8 test về quy tắc), `test_v129h_real_bq_pending_grain.py` (3 test BigQuery thật: dòng chờ
  xác nhận qua cổng và giữ toàn bộ số lượng; trùng thật vẫn chặn; NULL ở trạng thái khác vẫn chặn; DROP_EXACT bỏ trùng thật, giữ dòng
  chờ), `v129h-pending.test.tsx` (2 test giao diện), `test_bq_real_semantics.py` (cập nhật, MA-17). Kết quả: PASS.
- **Bằng chứng tích hợp:** preview backfill chỉ đọc toàn kỳ 01/01-19/10 bằng mã đã sửa trên bản sao production cô lập:
  `BFP-20261020181139-18A4F4` **READY**, 0 dòng trùng, 307 dòng chờ xác nhận được giữ.
- **Rủi ro còn lại:** (1) production 1.2.8 và gói 1.2.9 đã build CHƯA có sửa này (MA-18); (2) app không thấy khách hàng, nên nếu nguồn sinh
  lặp thật (fan-out) trên dòng chờ xác nhận thì app không phát hiện; trên snapshot này 0 trường hợp; đề xuất chạy lại truy vấn kiểm toán
  (`scratchpad p25\bq_audit.py`, mục `dup_rows`) sau mỗi lần nguồn dựng lại; (3) D-0 chưa áp dụng (MA-15).

### MA-03 - Sáu khóa MULTI_ITEM (BLOCKED - quyết định nghiệp vụ)
- **Bằng chứng:** đúng 6 khóa, 39 dòng, 156 đơn vị, trước (15:05) và sau (22:18) không đổi; bảng before/after đủ 6 khóa trong
  DATA_RECONCILIATION mục 5 và workbook `demandforecast_audit_multi_item_6_keys_20261021.xlsx`.
- **Nguyên nhân gốc:** hai item của cùng SKU bán qua cùng một FC trong ngày, mỗi item một giá trị `total_open_hours` hợp lệ (giờ đo theo item
  × ngày); data contract chưa có quy tắc gộp về hạt SKU × FC. Không do hậu tố, mapping, join hay group-by; nguồn không tự mâu thuẫn.
- **Sửa:** không (không được tự chọn MIN / MAX / trung bình). Cổng huấn luyện giữ nguyên (`OPEN_HOURS_INVALID`).
- **Test:** `open_hours.cell` (OK / MULTI_ITEM / CONFLICT / MISSING / OUT_OF_RANGE) trong `test_v129h_pending_orders_grain.py`; các test 1.2.9b sẵn có.
- **Rủi ro còn lại:** huấn luyện BIGQUERY bị chặn cho mọi cửa sổ chứa 09/02-26/08 tới khi có quyết định.

### MA-04 - Combo 931 khóa (VERIFIED, một phần INFERRED)
- **Bằng chứng:** 3.017 dòng / 931 khóa / 25.542 đơn vị khớp từng dòng với CSV trên snapshot hiện tại; 98,25 % đơn vị có nguồn gốc combo;
  `so_code ↔ order_id` 1:1; ở hạt đơn × SKU, số lượng nguồn = số lượng bảng combo cho 1.959/1.959 cặp có nhãn (không nhân đôi). "Uncertain = 0"
  đúng theo quy tắc nhưng 1.040 dòng sau 09/07 chỉ có mức INFERRED. 36 dòng "combo > nguồn" là do CSV lặp số theo đơn × SKU trên mỗi dòng.
- **Nguyên nhân gốc:** bảng `fact_fin_order_combo_unnested` dừng 09/07; sau đó dùng tín hiệu đã hiệu chỉnh.
- **Sửa:** không đổi nhãn, target hay chính sách combo; workbook `demandforecast_audit_combo_931_20261021.xlsx` ghi rõ mức bằng chứng từng dòng
  và cách đọc cột `via_qty`.
- **Rủi ro còn lại / quyết định:** phạm vi áp dụng quy tắc combo (chỉ 931 khóa hay mọi demand thành phần); có chấp nhận tín hiệu sau 09/07.

### MA-05 - customer_id (VERIFIED trên code; thử nghiệm BLOCKED)
- **Bằng chứng:** mã khách không rời BigQuery; số đếm ngày d chỉ dùng đơn đến ngày d; đặc trưng tại mốc t đọc `[t-28, t)`
  (`ml/features.py:290-302`); test `test_customer_features_read_only_the_known_days_before_the_target` PASS; chi phí +5,3 % byte (dry-run).
- **Sửa:** không cần. Production vẫn OFF.
- **Thử nghiệm offline:** NOT_RUN - huấn luyện BIGQUERY bị chặn bởi MA-03.

### MA-06 - Nguồn dựng lại thay đổi lịch sử so với dữ liệu app (UNRESOLVED)
- **Bằng chứng:** cùng snapshot: 344 khóa mới (+4.408), 308 khóa đổi (−3.168), 785 khóa mất (−14.495), tổng −13.255 trên 42.023.217; 273/292 ngày
  có thay đổi, ở mọi tháng. Preview READY cho ra cùng số. Workbook `demandforecast_audit_source_vs_app_20261021.xlsx`.
- **Nguyên nhân gốc:** chưa biết từ phía app (nguồn đã thay đổi các ngày cũ khi dựng lại 22:18). Chỉ 9 khóa liên quan dòng chờ xác nhận.
- **Sửa:** không. Backfill (phương án A) sẽ thay dữ liệu app bằng nguồn hiện tại cho đúng các khóa này.
- **Cần:** nhóm nguồn xác nhận các thay đổi lịch sử (đặc biệt 785 khóa mất) trước khi backfill.

### MA-07 - Bảng nguồn không phân vùng / clustering (PROPOSED, phía nguồn)
- **Bằng chứng:** `get_table`: `time_partitioning None`, `clustering None` (tạo lại 20/10 22:18; đã ghi nhận không phân vùng từ 16/10, báo cáo
  v118 R10). Dry-run truy vấn của app: cửa sổ tăng dần 4 ngày và toàn kỳ đều 1.342.644.619 byte cho cổng trùng và 1.342.644.619 byte cho
  truy vấn tổng hợp (~2,7 GB mỗi lần D-1); lọc theo ngày 4 ngày = không lọc (352 MB cho 4 cột).
- **Đề xuất:** nhóm nguồn tạo bảng phân vùng theo `created_date` (clustering `sku_code, fc_code`). Ước tính (INFERRED, giả định phân bố đều)
  D-1 tăng dần đọc ~4/292 dữ liệu: ~18 MB thay vì 1,34 GB mỗi truy vấn. App không cần đổi (đã có `partition_column = created_date`).

### MA-08 - Trang Danh mục đặc trưng chậm (FIXED_LOCAL)
- **Bằng chứng:** production `GET /api/features/registry` median 13,5 s, max 23,6 s; trên bản sao: truy vấn coverage qua index 8,3 s
  (lạnh 26 s) so với quét tuần tự 0,47 s, cùng kết quả.
- **Nguyên nhân gốc:** `feature_registry.coverage` đếm cột không nằm trong index qua index khóa → đọc lại từng dòng.
- **Sửa:** `NOT INDEXED` (như `ops_routes` 1.2.7, `demand.fingerprint` 1.2.8). Đầu cuối cùng bản sao: 9.044 ms → 1.500 ms median
  (PERFORMANCE_REPORT). Cũng dùng khi huấn luyện (`pipeline.py`).
- **Test:** `test_v129h_perf_scans.py` (cùng số đếm với câu lệnh cũ, kế hoạch là SCAN). PASS.

### MA-09 - Lineage của lần huấn luyện (FIXED_LOCAL)
- **Bằng chứng / sửa:** `pipeline.data_lineage` 8,6 s → 1,0 s trên bản sao, cùng giá trị; `NOT INDEXED`. Test: `test_v129h_perf_scans.py`. PASS.

### MA-10 - load_demand (FIXED_LOCAL)
- **Bằng chứng:** 1,36 triệu dòng: 15,3 s qua index; 6,2 s quét tuần tự + `ORDER BY` thứ tự khóa; DataFrame giống hệt (giá trị, kiểu,
  thứ tự dòng).
- **Sửa:** `demand.load_demand`: `NOT INDEXED` + `ORDER BY order_date, sku_id, fc_id`. Dùng cho huấn luyện, dự báo, kiểm tra chất lượng, panel
  giải thích.
- **Test:** `test_v129h_perf_scans.py` (thứ tự khóa khi dòng được ghi lộn xộn; khung giống hệt câu lệnh cũ). PASS.
- **Rủi ro còn lại:** sắp xếp 1,36 triệu dòng dùng file tạm của SQLite (~100-150 MB, tạm thời) mỗi lần nạp.

### MA-11 - /api/system/status mỗi lần mở trang (PROPOSED)
- **Bằng chứng:** đã là một lần quét tuần tự (1.2.7); 0,76-0,86 s ấm, 7,5-9,2 s lạnh; gọi ở mọi trang. Cache SQLite mặc định 2 MB, `mmap_size 0`.
- **Đề xuất:** cache kết quả theo phiên bản dữ liệu (load id của D-1 / lô nhập), hoặc thử `mmap_size` trên bản sao trước. Chưa làm vì đổi
  hành vi bộ nhớ / làm mới cần thiết kế và đo riêng.

### MA-12 - Lần chốt actual đầu tiên sau nâng cấp (PROPOSED)
- **Bằng chứng:** `actual_final.plan` 292 truy vấn theo ngày: 8,9 s (chỉ lần đầu; sau đó vài ngày). **Đề xuất:** một truy vấn gộp theo ngày.

### MA-13 - Dung lượng (PROPOSED, không xóa gì)
- 18 phiên bản đã cài 4,96 GiB (~283 MiB mỗi bản); `dist\` 1,42 GiB, trong đó `prune-artifacts.ps1 -Keep 1.2.6 -KeepLatest 2` (dry run) cho
  thấy **1.167,6 MB** có thể thu hồi; backup 1,77 GiB (53 file, gần đây 82 MiB/file); checkpoints 270,5 MiB; DB 704 MiB, tăng ~76 MiB/ngày
  (ước tính từ bản sao: mỗi lần dự báo +44 MiB) ≈ 27 GiB/năm nếu không có lưu giữ. `logs\development` (55 file) và `server.out.log`,
  `deploy-*.log` không xoay vòng (`app.log` xoay 10 MiB × 5).
- **Đề xuất:** chính sách giữ (vd. 3 phiên bản cài gần nhất + bản rollback, 2 gói mới nhất + bản đang chạy, backup theo tuần/tháng) và lưu giữ
  dữ liệu dự báo cũ - cần phê duyệt riêng; migration giảm kích thước khóa (`scope_key` 70 ký tự lặp ở mỗi dòng và index) cần phê duyệt.

### MA-14 - Thư mục test trong gói (PROPOSED)
- 2.304 file / 35,9 MiB (nén 8,6 MiB) dưới `site-packages/*/tests` (scipy, pandas, numpy). Bỏ khỏi gói: zip ~88,1 → ~79,5 MiB (−9,8 %),
  cài đặt 256,7 → ~220,8 MiB (−14 %). Cần sửa `scripts\build-package.ps1` + build + cài thử cô lập + chạy app: chưa làm (cần commit để build
  gói chính thức).

### MA-15 - D-0 so khớp toàn dòng (RISK)
- D-0 so trùng trên toàn dòng của SQL người dùng (không ánh xạ trạng thái). 20/10: 6/6 lần thành công; bảng D-0 rỗng lúc kiểm tra. Không đổi code.

### MA-16 - File thừa trong thư mục DB (PROPOSED)
- `data\runtime\db\app.db.migrating-shm` (32 KB) và `app.db.migrating-wal` (0 B) từ 14/10 10:23 (lần chuyển lưu trữ). Không xóa; đề xuất
  xóa có phê duyệt khi app dừng.

### MA-17 - Kỳ vọng của test real-BigQuery cũ (FIXED_LOCAL)
- `test_bq_real_semantics.py` (opt-in) mã hóa quy tắc cũ: cặp WAIT_TO_CONFIRM so_code NULL giống hệt = nhóm trùng. Đổi kỳ vọng theo quy tắc
  chủ hệ thống 21/10 (cặp này được giữ, cộng 6 thay vì 3) và **thêm** cặp NULL ở trạng thái `CONFIRMED` để vẫn kiểm NULL = NULL. PASS.

### MA-18 - D-1 06:00 ngày 21/10 trên production (BLOCKED)
- Production 1.2.8 (và gói 1.2.9) vẫn áp quy tắc cũ; nguồn chưa đổi (watcher không thấy lần dựng lại) → D-1 06:00 / 06:30 sẽ dừng
  `BQ_DATA_DUPLICATES`, dữ liệu dừng ở 19/10. Không tự triển khai trong batch này. Cách gỡ: phát hành bản có MA-02 (cần phê duyệt) hoặc nguồn
  bổ sung khóa phân biệt cho dòng chờ xác nhận.
