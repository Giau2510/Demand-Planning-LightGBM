# Đưa dữ liệu BigQuery vào Demand Forecasting — chốt dòng trùng hoàn toàn, tổng hợp ngày × SKU × FC

Ngày 16/10/2026, 13:00–14:00 (giờ Việt Nam). Mã nguồn sau 1.1.8, **chưa commit, chưa push, chưa đóng gói, chưa cài**.

**Kết luận: `BLOCKED_DATA_SAFETY`.** Code ingest và kiểm thử đã xong. Hai chặn nằm ở dữ liệu nguồn, không phải ở code:
1. Bảng nguồn có **433 nhóm / 878 dòng / 445 dòng dư** trùng hoàn toàn trong 01/01–15/10/2026. Theo chính sách đã
   chọn, ingest bị chặn và báo cáo `.xlsx` đã được xuất.
2. Lúc 13:30 ngày 16/10, nguồn **chưa có dòng nào của ngày 15/10** (ngày mới nhất là 14/10). Vì vậy một lần D-1 chạy
   lúc này sẽ dừng với `SOURCE_INCOMPLETE` và không ghi gì.

## 1. Thay đổi

| File | Nội dung |
|---|---|
| `backend/app/bq/dup_report.py` (mới) | Báo cáo dòng trùng `.xlsx` (Summary / Duplicate_Rows / Duplicate_Groups), không ghi đè, CSV thay thế khi `.xlsx` lỗi; liệt kê + tải an toàn |
| `backend/app/bq/connector.py` | `dup_columns`, `require_mapping`, `_dup_sql`, `duplicate_check`, `duplicate_gate`; gọi trong `fetch_daily` **trước** tổng hợp và trong kiểm tra toàn kỳ (truy vấn `validate_duplicates`) |
| `backend/app/sync.py` | `_d1_window` (dùng chung), `check_output` (kiểm dữ liệu sau tổng hợp, không đổi gì thành 0), `d1_dry_run` (10 bước, không ghi), `ingest_check_state` |
| `backend/app/settings_service.py` | Mặc định luồng lịch sử `key_duplicate_policy = SUM_ALL` (D0 giữ BLOCK) |
| `backend/app/api/ops_routes.py` | `POST /api/bigquery/ingest-check`, `GET /api/bigquery/duplicate-reports[/{name}]`; `/api/bigquery/status` thêm `duplicate_check`, `duplicate_reports`, `ingest_check` |
| `backend/app/messages.py` | `BQ_DATA_DUPLICATES`, `BQ_MAPPING_INVALID` (hướng dẫn tiếng Việt), mới `BQ_AGGREGATE_INVALID` |
| `frontend/src/pages/BigQuery.tsx`, `frontend/src/i18n.tsx` | Nút *Kiểm tra trùng & thử tổng hợp (không ghi)*, bảng từng bước, số nhóm/dòng/dòng dư, link tải báo cáo, danh sách báo cáo gần đây |
| Test | `backend/tests/test_v118_bq_ingest.py` (mới, 19), `backend/tests/test_bq_real_semantics.py` (mới, BigQuery thật, opt-in), `backend/tests/test_v116.py` (1 test cập nhật theo mặc định SUM_ALL; BLOCK vẫn được kiểm), `frontend/src/v118-bq-ingest.test.tsx` (mới, 6) |
| Tài liệu | `docs/BIGQUERY.md` mục 13 (+ sửa câu chữ mục 12), `CHANGELOG.md`, `docs/CHECKPOINT.md` |

Checkpoint trước khi sửa: `checkpoints/source-1.1.8-before-bq-ingest-20261016-130203.zip`
(SHA-256 `1C39EB27DF7BB1C355F4863DE639DFDCB69F89977F14BC77D7B8DD453B08153F`). Các thay đổi audit buổi sáng (chưa commit)
được giữ nguyên.

## 2. Logic đã triển khai

Thứ tự của D-1 (`run_d1_sync` → `fetch_daily`) và của dry-run:
1. Cấu hình + xác thực Google (ADC). D-1 thật còn cần chế độ production và kiểm tra toàn kỳ đạt.
2. Phạm vi: `window_start_date` (01/01/2026) → **hôm qua theo giờ Việt Nam**; hôm nay không bao giờ được nạp.
3. Hôm qua đã đủ trong nguồn chưa: tín hiệu hoàn tất nếu có cấu hình; nếu không, số dòng hôm qua ≥ 50 % trung bình
   7 ngày trước. Chưa đủ thì D-1 chờ / thử lại, không ghi.
4. Ánh xạ so với schema nguồn hiện tại. Thiếu trường bắt buộc hoặc mất cột đã ánh xạ → `BQ_MAPPING_INVALID` kèm danh
   sách trường; không âm thầm so ít cột hơn.
5. **Chốt trùng hoàn toàn trên dữ liệu gốc, trước tổng hợp**:
   - so mọi cột đã ánh xạ (15 cột với bảng thật), bằng `GROUP BY` trên giá trị gốc;
   - NULL bằng NULL; số so theo giá trị; ngày/giờ không đổi múi giờ; chuỗi so chính xác;
   - có trùng → báo cáo + `BQ_DATA_DUPLICATES`, dừng; job *Thất bại*, không thử lại.
6. Tổng hợp `SUM(demand_quantity)` theo `created_date × sku_code × fc_code` trong BigQuery; đối soát đọc = hợp lệ + loại.
7. Kiểm tra dữ liệu sau tổng hợp: một dòng mỗi khóa, ngày hợp lệ, có SKU/FC, số lượng thật → nếu sai
   `BQ_AGGREGATE_INVALID`.
8. Ghi trong một giao dịch (xóa cửa sổ của phạm vi BIGQUERY rồi chèn), đối soát số đã ghi, lỗi thì rollback toàn bộ;
   chạy lại không nhân đôi; không chạm dữ liệu DEMO/Excel.

Giữ nguyên theo yêu cầu: không loại `so_code` NULL, không lọc `order_status`, không thêm 0, không loại dòng trùng khóa
hay cùng số lượng khác giá/outbound (cộng dồn), không bật `DROP_EXACT`, không có nút "bỏ qua trùng".

## 3. Kết quả test

| Loại | Kết quả |
|---|---|
| Ingest mới (fake, 14 tình huống) | 19/19 đạt; 4/4 đột biến bị bắt (bỏ gate, so thiếu cột, bỏ kiểm đầu ra, xuất thiếu dòng), file khôi phục nguyên hash |
| BigQuery thật, dữ liệu nội tuyến (0 byte) | 2/2 đạt: trùng hoàn toàn chỉ khi mọi cột bằng nhau; NULL = NULL; NULL ≠ 0; khác giá / outbound / số lượng không phải trùng; `so_code` NULL được giữ và cộng; tổng 15 = 5 + 8 + 2 |
| Lint | không cấu hình |

## 4. BigQuery thật — bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`

Chạy trên **bản sao DB cô lập** (SQLite backup API, nguồn mở chỉ đọc), ADC của tài khoản Windows này, chỉ đọc
BigQuery (dry-run trước, giới hạn byte). Ánh xạ = gợi ý của ứng dụng, kiểm tra với schema thật, chỉ lưu trên bản sao.

| Hạng mục | Kết quả |
|---|---|
| Kết nối / xác thực | đạt (tài khoản @buymed.com, `asia-southeast1`, bảng `TABLE` không phân vùng, 8.885.547 dòng) |
| Dry-run, chính sách production (BLOCK), 01/01–15/10 | **BLOCKED**: 8.885.547 dòng nguồn; **433 nhóm, 878 dòng, 445 dòng dư** (54 dòng `so_code` NULL trong các nhóm); không ghi gì |
| Báo cáo | `bq-trung-lap_2026-01-01_2026-10-15_20261016-132304.xlsx` — 878 dòng / 433 nhóm, số thứ tự 1..n đúng (bản trên bản sao, thư mục scratchpad) |
| Đo trên bản sao (chính sách tạm KEEP, không phải production) | 1.345.228 dòng ngày × SKU × FC; tổng demand **41.654.787** (gồm cả 445 dòng trùng); 0 dòng bị loại; 9.769 dòng lặp khóa đơn được cộng dồn; đối soát khớp |
| Kiểm tra toàn kỳ trên bản sao (KEEP) | đạt; cảnh báo `EXACT_DUPLICATES`, `KEY_NOT_UNIQUE`, `MISSING_DAYS`, `TARGET_OUTLIER`; 3,48 GB |
| Ngày 15/10 trong nguồn | **0 dòng** (TB 7 ngày trước 18.817) → D-1 lúc 13:30 dừng `SOURCE_INCOMPLETE` |
| Ghi thử vào bản sao | xem mục 5 |

Dữ liệu thật **không** bị ghi: DB live vẫn 38.533 dòng / 1.015.057, 0 dòng BIGQUERY; cấu hình BigQuery live cập nhật lần
cuối 15/10; `storage.json` SHA bắt đầu `8D79DBDD`; ứng dụng 1.1.8 chạy bình thường.

## 5. Ghi thử vào bản sao (giả lập ngày chạy 15/10 10:00 vì nguồn chưa có 15/10)

Chính sách tạm KEEP **chỉ trên bản sao** để đo đường ghi với dữ liệu thật; production vẫn BLOCK.

| Lần | Cửa sổ | Đọc | Ghi | Kết quả |
|---|---|---|---|---|
| 1 (nạp lại toàn kỳ) | 01/01–14/10 | 8.885.547 dòng, 41.654.787 | 1.345.228 dòng ngày × SKU × FC | 1.345.228 mới; đối soát khớp |
| 2 (chạy lại) | 11/10–14/10 | 77.861 dòng, 331.518 | 13.120 dòng | 13.120 không đổi; tổng BIGQUERY vẫn 1.345.228 / 41.654.787 |

Sau ghi: không khóa ngày × SKU × FC nào lặp; 9.669 SKU, 2 FC, 01/01–14/10; dữ liệu DEMO 38.533 / 1.015.057 không đổi.
Dry-run cuối 13:39 (BLOCK, giờ thật): hôm qua `WARNING` (0 dòng, TB 7 ngày 18.817), trùng `BLOCKED` 433 / 878 / 445,
không ghi.

Tổng dữ liệu BigQuery quét trong đợt này ≈ 11 GB (mỗi truy vấn đều dry-run trước, có giới hạn byte).

## 6. Kết quả test lần cuối

| Loại | Kết quả |
|---|---|
| Backend toàn bộ (unit / integration với fake BigQuery) | **298 đạt, 2 bỏ qua** (2 test BigQuery thật opt-in), exit 0 |
| Frontend vitest | **61/61** (10 file) |
| Typecheck / build | đạt / đạt |

## 7. Việc người dùng cần làm để đưa dữ liệu vào ứng dụng

1. **Xử lý 445 dòng trùng tại nguồn** (hoặc xác nhận bằng văn bản một chính sách khác). Báo cáo trên máy thật sẽ được
   tạo ở `D:\Buymed\Lightgbm AI\reports\bigquery-duplicates\` khi chạy kiểm tra bằng bản có code này.
2. Xem lại thay đổi (`git diff`), cho phép commit/push; phát hành bản mới (`scripts\build-package.ps1`) và nâng cấp bằng
   `scripts\deploy-upgrade.ps1 -CheckOnly` rồi chạy thật với xác nhận (ngoài khung giờ lịch chạy).
3. Trên trang **Ánh xạ trường**: *Gợi ý* → xem lại → *Kiểm tra & lưu ánh xạ*.
4. Trên trang **BigQuery**: *Kiểm tra kết nối*, *Kiểm tra dữ liệu (30 ngày)*, *Kiểm tra dữ liệu toàn kỳ*, rồi
   *Kiểm tra trùng & thử tổng hợp (không ghi)*. Chỉ tiếp tục khi kết quả là **Sẵn sàng**.
5. *Kích hoạt chế độ sản xuất*, chọn nguồn **BIGQUERY** (người dùng tự đổi), trang **Lịch chạy dữ liệu** → luồng D-1
   → *Chạy ngay*. Lần đầu là nạp lại toàn kỳ 01/01 → hôm qua.
6. Bật lịch D-1 nếu muốn chạy hằng ngày. Nguồn được làm mới khoảng trưa D+1 nên giờ D-1 01:00 (fallback 06:00) sẽ thường
   phải thử lại; cân nhắc dời giờ D-1 sau giờ làm mới hoặc cấu hình bảng tín hiệu hoàn tất. Lịch không được đổi trong
   đợt này.
