# Test results - master audit 21/10/2026

Nhãn loại: **unit** (DB tạm, không gọi ngoài), **integration-fake** (FakeBQ / TestClient), **real external** (BigQuery thật trên dòng
inline: 0 byte, không đọc bảng, không ghi), **DB copy** (bản sao production cô lập), **isolated install** (không chạy trong batch này).
Log: thư mục scratchpad `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p25\`.

## 1. Bộ test đầy đủ

| Lệnh | Thời điểm | Kết quả | Thời lượng | Log |
|---|---|---|---|---|
| `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` (sau sửa trùng, trước tối ưu) | 21/10 ~01:07 | **659 passed, 13 skipped, 0 failed**, 1 warning (Starlette httpx, có từ trước) | 455,9 s (chạy song song với test frontend + preview) | `test_backend_full.log` |
| như trên (cuối batch, sau mọi thay đổi) | 21/10 01:36-01:42 | **661 passed, 13 skipped, 0 failed**, 1 warning (như trên) | 342,2 s | `test_backend_final.log` |
| `cd frontend; npm test` (cuối batch) | 21/10 ~01:46 | **25 file, 154 passed** (152 cũ + 2 mới) | 22,9 s | `test_frontend_final.log` |
| `npm run typecheck` | như trên | exit 0 | - | như trên |
| `npm run build` | như trên | exit 0; `index.js` 683,81 kB (gzip 207,97 kB), css 32,17 kB | 4,55 s | như trên |
| Lint | - | **not configured** (không có trong dự án) | - | - |

13 test bỏ qua = test opt-in BigQuery thật / D-0 thật (`DF_REAL_BQ=1`), gồm 3 test mới; các test inline được chạy riêng ở mục 2.
So với QA phát hành 20/10 (647 passed / 10 skipped): +14 test offline mới, +3 test opt-in mới.

## 2. BigQuery thật (real external, dòng inline, 0 byte)

| Lệnh | Kết quả | Log |
|---|---|---|
| `$env:DF_REAL_BQ="1"; pytest tests\test_bq_real_semantics.py tests\test_v129_real_bq_open_hours.py tests\test_v129c_real_bq_items_customers.py tests\test_v129e_real_bq_item_suffix.py tests\test_v129h_real_bq_pending_grain.py` (lần 1, trước khi cập nhật kỳ vọng) | 7 passed, **1 failed**: `test_bq_real_semantics::test_real_bigquery_exact_duplicates_only_when_every_mapped_column_is_equal` - `(1, 2, 1) != (2, 4, 2)`: cặp WAIT_TO_CONFIRM so_code NULL không còn là nhóm trùng (đúng quy tắc mới) | `test_real_bq_inline.log` |
| như trên (cuối batch, sau cập nhật kỳ vọng, MA-17) | **8 passed**, 34,1 s | `test_real_bq_inline_final.log` |

Không chạy: `test_v121_d0_real_bq.py` (D-0, không đổi code D-0; có đọc bảng D-0 thật).

## 3. Test mới / đổi trong batch

| File | Số test | Loại | Bao phủ |
|---|---:|---|---|
| `backend/tests/test_v129h_pending_orders_grain.py` | 12 | unit | quy tắc đơn chờ xác nhận ở cổng trùng / kiểm tra toàn kỳ / D-1 / DROP_EXACT; không áp dụng khi thiếu ánh xạ; kết quả kiểm tra + báo cáo; hạt ngày × SKU × FC theo cột FC; 2 FC cho cùng SKU; mã SKU đầy đủ không bị cắt / gộp; tổng số lượng giữ nguyên; `open_hours.cell` |
| `backend/tests/test_v129h_perf_scans.py` | 2 | unit | coverage / lineage / load_demand: quét tuần tự, cùng kết quả với câu lệnh cũ, thứ tự khóa |
| `backend/tests/test_v129h_real_bq_pending_grain.py` | 3 | real external (opt-in) | cùng các quy tắc trên BigQuery thật: dòng chờ xác nhận qua cổng, trùng thật vẫn chặn (có so_code, hoặc NULL ở trạng thái khác), DROP_EXACT; FC từ `fc_code`; hậu tố đảo không đổi trạng thái; SKU khác không gộp; tổng số lượng |
| `backend/tests/test_bq_real_semantics.py` | 2 (đổi) | real external (opt-in) | kỳ vọng theo quy tắc 21/10 + cặp NULL trạng thái `CONFIRMED` để vẫn kiểm NULL = NULL |
| `frontend/src/v129h-pending.test.tsx` | 2 | unit (giao diện) | dòng "đơn chờ xác nhận chưa có mã" hiện / ẩn đúng |

## 4. Kiểm chứng trên bản sao DB và dữ liệu thật

| Kiểm chứng | Loại | Kết quả |
|---|---|---|
| Preview backfill toàn kỳ 01/01-19/10 bằng mã đã sửa (`sync.backfill_preview`) | DB copy + BigQuery thật (chỉ đọc) | READY `BFP-20261020181139-18A4F4`; 8.961.545 dòng; 0 trùng; 307 dòng chờ xác nhận giữ lại; 312 s; migrate 6→9 trên bản sao 59 s |
| Đối soát khóa nguồn / app | DB copy + BigQuery thật | 344 / 308 / 785 / 1.357.224 - trùng khớp preview |
| Endpoint trước / sau (HEAD so với working tree), nội dung trả về | DB copy | 7 endpoint: thân JSON giống hệt (SHA-256); 12 endpoint đo thời gian, 3 vòng |
| Kiểm toán nguồn (9 truy vấn), số 0 giờ, dòng chờ xác nhận | BigQuery thật (chỉ đọc) | xem DATA_RECONCILIATION.md; tổng byte quét cả batch ≈ 13,6 GB (kiểm toán 7,88 GB + dòng 0 giờ 1,15 GB + preview 2,69 GB + đối soát 1,92 GB), mỗi truy vấn ≤ 1,7 GB |
| Gói / cài đặt cô lập / nâng cấp / rollback / backup-restore | isolated install | **NOT_RUN** trong batch này: bản có sửa chưa được build (cần commit + phiên bản mới). Gói 1.2.9 đã diễn tập 33/34 ở đợt 20/10 (không gồm sửa này). |
| Migration | - | không có migration mới |

## 5. Không làm để đạt PASS

Không xóa / làm yếu test nào; kỳ vọng duy nhất bị đổi (MA-17) gắn với quy tắc chủ hệ thống 21/10 và được bù bằng một cặp kiểm NULL = NULL mới.
