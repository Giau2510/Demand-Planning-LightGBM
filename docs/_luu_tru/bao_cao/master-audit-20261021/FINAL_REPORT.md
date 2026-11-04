# Master audit Demand Forecasting - 21/10/2026

**Trạng thái: PARTIAL - BLOCKED_DATA_SAFETY** (sửa lỗi và tối ưu đã làm và kiểm thử trong mã nguồn; chưa phát hành vì không có phê duyệt
commit / triển khai, và còn quyết định nghiệp vụ + xác nhận nguồn). Đọc kèm: FINDINGS_REGISTER.md, TEST_RESULTS.md, PERFORMANCE_REPORT.md,
DATA_RECONCILIATION.md, RESUME_CHECKPOINT.md (cùng thư mục).

## 1. Tóm tắt

- **Hậu tố SKU → FC:** không có code nào suy ra kho / FC từ hậu tố `.1/.2/.3` (VERIFIED trên code và dữ liệu: mọi hậu tố có dòng ở cả BD và
  HN). Thêm test hồi quy cho 6 trường hợp hạt dữ liệu, cả offline và trên BigQuery thật (dòng inline, 0 byte).
- **Dòng trùng / WAIT_TO_CONFIRM (lỗi đã sửa trong mã nguồn):** 67 dòng "trùng" của nguồn dựng lại 20/10 22:18 là đơn chờ xác nhận chưa có
  `so_code`, mỗi dòng một khách khác nhau - đơn riêng hợp lệ, 0 dòng trùng thật. Quy tắc mới: dòng `so_code` NULL + `WAIT_TO_CONFIRM` không
  bao giờ là trùng hoàn toàn, được giữ và đếm riêng; mọi dòng khác giữ quy tắc chặn. Preview backfill toàn kỳ chỉ đọc bằng mã đã sửa, trên
  bản sao production cô lập: **READY**.
- **6 khóa MULTI_ITEM:** không đổi trước / sau; nguyên nhân là nhiều giá trị hợp lệ theo item, chưa có quy tắc gộp → vẫn **BLOCKED**
  (quyết định nghiệp vụ); không tự chọn giá trị.
- **Combo 931 khóa:** khớp từng dòng với snapshot hiện tại; 98,25 % đơn vị qua combo; không nhân đôi; phần sau 09/07 là INFERRED.
- **Nguồn so với app:** nguồn dựng lại đã đổi lịch sử: 344 khóa mới, 308 khóa đổi, 785 khóa mất, −13.255 đơn vị (UNRESOLVED, cần nhóm nguồn).
- **Hiệu năng:** trang Danh mục đặc trưng 9,0 s → 1,5 s trên cùng bản sao (production đo được 13,5 s), nạp dữ liệu huấn luyện / dự báo
  15,3 s → 6,2 s, lineage 8,6 s → 1,0 s - kết quả giống hệt. Bảng nguồn không phân vùng: mỗi D-1 quét ~2,7 GB (đề xuất phía nguồn).

## 2. Trạng thái production đã xác minh (21/10 00:54 và suốt batch)

| Mục | Giá trị |
|---|---|
| Phiên bản chạy | **1.2.8** (`GET /api/health` → `{"ok":true,"version":"1.2.8"}`; `current.txt` = 1.2.8; tiến trình 10884) |
| `storage.json` | SHA-256 `8D79DBDDC960B10964F3B137F352D9AD54D39F08C52EF841418781ED00FDE047` (không đổi) |
| Job | không có job đang chạy; 23:55 EOD và 23:59 close 20/10 SUCCEEDED |
| Ánh xạ / chính sách | `exact_duplicate_policy = BLOCK`, nguồn TABLE, `customer_id_column` rỗng, Price ON |
| Thay đổi trong batch | **không có**: không deploy, backfill, chốt actual, huấn luyện, đổi cấu hình / lịch / ánh xạ, push |
| Nguồn | bảng tạo lại 20/10 22:18:39, không đổi tới hết batch (watcher chỉ đọc + metadata trước/sau mỗi truy vấn) |
| D-1 06:00 sáng 21/10 | sẽ dừng `BQ_DATA_DUPLICATES` (1.2.8 chưa có sửa) → dữ liệu dừng ở 19/10 (MA-18) |

## 3. Lỗi đã phát hiện và sửa (mã nguồn, chưa phát hành)

| ID | Lỗi | Sửa | Test |
|---|---|---|---|
| MA-02 | đơn chờ xác nhận chưa có mã bị coi là trùng hoàn toàn → chặn D-1 / backfill | `connector.PENDING_STATUSES` ở cổng trùng, kiểm tra toàn kỳ, D-1; báo cáo + giao diện đếm riêng | 12 + 3 (BigQuery thật) + 2 (giao diện) + 1 test cũ cập nhật |
| MA-08 | Danh mục đặc trưng 9-24 s | coverage `NOT INDEXED` | `test_v129h_perf_scans.py` |
| MA-09 | lineage huấn luyện 8,6 s | `NOT INDEXED` | như trên |
| MA-10 | load_demand 15,3 s | `NOT INDEXED` + `ORDER BY` thứ tự khóa | như trên |

## 4. Chưa thể kết luận / chờ quyết định

- MA-03: quy tắc gộp giờ mở bán cho 6 khóa MULTI_ITEM (phương án và tác động ở workbook MULTI_ITEM, sheet `Expected_vs_Actual`).
- MA-04: phạm vi quy tắc combo; có chấp nhận tín hiệu sau 09/07 (INFERRED).
- MA-06: các thay đổi lịch sử của nguồn (785 khóa mất) - nhóm nguồn xác nhận trước backfill.
- MA-05: thử nghiệm `customer_id` offline NOT_RUN (huấn luyện BIGQUERY bị chặn bởi MA-03).
- MA-15: D-0 so khớp toàn dòng - rủi ro tương tự, chưa quan sát.

## 5. Hiệu năng (trước → sau, cùng bản sao)

| Chỉ số | Trước | Sau | Chênh |
|---|---:|---:|---:|
| `GET /api/features/registry` | 9.044 ms | 1.471 ms | −83,7 % |
| coverage (SQL) | 8.329 ms | 467 ms | −94,4 % |
| data_lineage (SQL) | 8.580 ms | 1.032 ms | −88,0 % |
| load_demand (1,36 triệu dòng) | 15.281 ms | 6.192 ms | −59,5 % |
| RAM đỉnh API | 158,1 MiB | 157,7 MiB | ~0 |
| Gói / BigQuery byte | 88,1 MiB / 2 × 1,34 GB mỗi D-1 | không đổi | 0 |

Dung lượng có thể thu hồi (chỉ đề xuất, chưa xóa gì): gói cũ trong `dist\` 1.167,6 MB (dry run), ~4 GiB phiên bản cài cũ, chính sách backup;
DB tăng ~76 MiB/ngày. Chi tiết: PERFORMANCE_REPORT.md.

## 6. Kiểm thử

Backend toàn bộ (cuối batch): **661 passed, 13 skipped, 0 failed** (342 s). Frontend: **154 passed**, typecheck và build đạt. BigQuery thật
(dòng inline, 0 byte): **8 passed**. Lint: not configured. Gói / cài đặt cô lập cho bản có sửa: NOT_RUN (chưa build). Chi tiết: TEST_RESULTS.md.

## 7. Sẵn sàng phát hành

**Chưa sẵn sàng.** Đối chiếu 7 điều kiện của yêu cầu:

| # | Điều kiện | Trạng thái |
|---|---|---|
| 1 | Kiểm tra trùng không còn blocker chưa giải thích | ĐẠT trong mã nguồn (giải thích đủ, sửa có test); CHƯA có trong bản phát hành nào |
| 2 | MULTI_ITEM phân loại đúng hạt, có cách xử lý được duyệt | Phân loại xong; **chưa có quy tắc được duyệt** (chặn huấn luyện, không chặn backfill) |
| 3 | Preview / đối soát toàn kỳ cùng snapshot | ĐẠT (preview READY + đối soát khóa, cùng snapshot 22:18) |
| 4 | Gói và migration / rollback đã kiểm thử | Gói 1.2.9 đã diễn tập (đợt trước); **bản có sửa này chưa build** (cần commit + phiên bản mới) |
| 5 | Backup đọc / khôi phục được | Backup mới nhất đọc được (đợt trước); kiểm lại khi phát hành |
| 6 | Thứ tự deploy → preview → backfill → đối soát → chốt actual an toàn | Quy trình có sẵn; cần khung giờ ngoài lịch và phê duyệt; MA-06 cần nhóm nguồn xác nhận trước backfill |
| 7 | Không ảnh hưởng bất ngờ D-1 / D-0 / dashboard | D-1 production hiện bị chặn bởi nguồn (MA-18); bản sửa gỡ được điều này; D-0 không đổi |

## 8. Hiện vật

Báo cáo và workbook trong `D:\Buymed\Lightgbm AI\reports\master-audit-20261021\` (SHA-256 workbook trong `workbooks_manifest.json`);
checkpoint trước / sau trong `checkpoints\` (RESUME_CHECKPOINT.md); script và kết quả trong scratchpad `p25`.
