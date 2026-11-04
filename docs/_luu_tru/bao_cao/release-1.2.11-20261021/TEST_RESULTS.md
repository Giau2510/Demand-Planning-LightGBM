# Test results - release 1.2.11 (21/10/2026)

## Loại kết quả và nơi lưu log

| Nhãn | Nghĩa |
|---|---|
| unit | DB tạm của conftest, không gọi ra ngoài |
| integration-fake | FakeBQ / TestClient |
| real external | BigQuery thật trên dòng inline (0 byte) hoặc bảng nguồn thật chỉ đọc |
| DB copy | bản sao production cô lập |
| isolated install | gói chính thức cài trong `LOCALAPPDATA` riêng trên bản sao DB |
| production | production thật |

Log nằm trong scratchpad
`C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p28\`.

## 1. Bộ test đầy đủ

| Lệnh | Cây mã | Kết quả | Log |
|---|---|---|---|
| `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | working tree, trước khi sửa proxy | **685 passed, 19 skipped, 0 failed** (972,7 s, chạy song song với truy vấn BigQuery) | `test_backend_full.log` |
| `cd frontend; npm test; npm run typecheck; npm run build` | working tree | vitest **25 file, 155 passed**; typecheck exit 0; build exit 0 (`index-UtAXUtMs.js` 684,58 kB) | `test_frontend.log` |
| `scripts\release.ps1` (QA = `scripts\run-tests.ps1` trên commit `9ee5a4a`, cây sạch → build → verify) | commit `9ee5a4a` | backend **686 passed, 19 skipped, 0 failed** (643,7 s); vitest **155 passed**; build OK; gói xác minh OK (commit 9ee5a4a, dirty=False, source `88A501578BD3CEA7`); prune chỉ dry run | `release1211.log` |
| Lint | - | **not configured** | - |

- **19 test bỏ qua** = test opt-in BigQuery thật / D-0 thật (`DF_REAL_BQ=1`). Các test này được chạy riêng ở mục 2.
- **So với 1.2.10 (663 passed / 15 skipped):**
  - +20 test offline MULTI_ITEM;
  - +2 test proof / rule mới trong `test_v129h_pending_orders_grain.py`;
  - +1 ca proxy;
  - +4 test opt-in BigQuery thật.

## 2. BigQuery thật

| Lệnh / kiểm chứng | Loại | Kết quả |
|---|---|---|
| `$env:DF_REAL_BQ="1"; pytest tests\test_v129h_real_bq_pending_grain.py tests\test_bq_real_semantics.py tests\test_v1210_real_bq_multi_item_regions.py tests\test_v129e_real_bq_item_suffix.py tests\test_v129c_real_bq_items_customers.py tests\test_v129_real_bq_open_hours.py` | real external, dòng inline, 0 byte | **14 passed** (74,6 s) |
| SQL cổng trùng 1.2.11 (ánh xạ production) trên bảng thật 01/01-20/10, snapshot 21/10 07:10:38 (`bq_app_sql_new.py`) | real external, chỉ đọc | xem chi tiết bên dưới |
| Dry-run byte (cùng ánh xạ) | real external, dry run | cổng trùng 1.695.466.952; tổng hợp D-1 1.345.256.624; validate_summary 1.345.256.624; validate_days 352.994.748 |

Kết quả cổng trùng 1.2.11 trên bảng thật:

- 8.979.752 dòng, 42.088.223 đơn vị, **0 nhóm trùng**.
- Dòng WAIT_TO_CONFIRM: 904 dòng / 12.933 đơn vị, tất cả chưa có `so_code`, đều được miễn.
  - 46 nhóm / 136 dòng giống nhau ở cột so sánh.
  - 0 dòng giống nhau ở mọi cột nguồn.
- So sánh thêm cả `item_code`: vẫn 0 nhóm ngoài WAIT_TO_CONFIRM.

## 3. Test mới hoặc đổi

| File | Loại | Thay đổi |
|---|---|---|
| `test_v129h_pending_orders_grain.py` | unit | Viết lại theo quy tắc mới (xem bên dưới). |
| `test_v129h_real_bq_pending_grain.py` | real external (opt-in) | Mô tả bên dưới. |
| `test_bq_real_semantics.py` | real external (opt-in) | Khóa `pending_orders` (số dòng, chưa có mã, giống ở cột so sánh / mọi cột). |
| `test_v118_bq_ingest.py`, `test_bigquery.py` | unit / integration-fake | Bỏ `item_code` khỏi GROUP BY; DROP_EXACT dùng `ROW_NUMBER`. Đây là hành vi mới có chủ đích. |
| `test_v121_remote_proxy.py` | unit + proxy thật trên cổng tạm | Bị từ chối: `GET /api/data-quality` (403) và `HEAD /api/*` (405). Vẫn mở: `/api/data-quality/history`, `HEAD` giao diện. |
| `test_v1210_multi_item_open_hours.py` (đợt trước, nay commit) | unit / integration-fake | 20 test: 6 mẫu thật, khóa FC kia, giá trị hợp lệ, phát hiện mâu thuẫn, cổng huấn luyện. |
| `test_v1210_real_bq_multi_item_regions.py` (đợt trước, nay commit) | real external (opt-in) | 2 test. |
| `frontend/src/v129h-pending.test.tsx` | unit (giao diện) | 3 test: dòng WAIT_TO_CONFIRM miễn trừ, dòng giống mọi cột nguồn ghi "không chặn", kết quả 1.2.10 cũ không hiện nhầm. |

Nội dung `test_v129h_pending_orders_grain.py`:

- Quy tắc chỉ cần cột `order_status`, không cần `so_code`.
- `item_code` không bao giờ là cột so sánh.
- SQL cổng trùng chỉ tính nhóm ngoài đơn chờ xác nhận.
- Khi không ánh xạ trạng thái: so mọi dòng.
- Dòng kiểm soát D-1 và kiểm tra toàn kỳ dùng cùng quy tắc, không đọc toàn dòng nguồn.
- DROP_EXACT giữ mọi dòng chờ xác nhận, mỗi nhóm khác giữ một dòng.
- Dòng chờ xác nhận giống mọi cột nguồn được báo cáo nhưng không chặn.
- Trùng thật vẫn chặn, báo cáo ghi quy tắc.
- Join duy nhất không nhân dòng.
- Bằng chứng: chặn hay không không phụ thuộc số item.

`test_v129h_real_bq_pending_grain.py` (+2 test, 1 test viết lại) kiểm tra trên BigQuery thật:

- Dòng WAIT_TO_CONFIRM được miễn khi giống mọi cột nguồn, có `so_code`, hoặc trùng khách.
- Dòng đơn bị nhân theo `item_code` thì **chặn**.
- Trạng thái trộn / chuyển trạng thái không gộp nhóm; `" wait_to_confirm "` được chuẩn hóa.
- Đơn COMPLETED trùng vẫn chặn.
- DROP_EXACT bỏ đúng dòng trùng thật và dòng nhân theo item, giữ đơn chờ xác nhận.

Đối chiếu với các yêu cầu test của đợt:

| Yêu cầu | Test |
|---|---|
| Nhiều dòng WAIT_TO_CONFIRM hợp lệ, `so_code` NULL | `test_real_bigquery_grain_and_pending_orders_pass_with_every_unit_kept`, `test_pending_rows_pass_the_gate_and_write_no_report` |
| Trùng `customer_id` giữa các đơn WAIT_TO_CONFIRM | `PENDING_SAME_ROW` / `PENDING_WITH_CODE` (cùng khách) - được miễn |
| Khác SO cùng SKU × FC × ngày | `BASE` (A/B/C), `test_v1210_*` (6 khóa thật: SO khác nhau, cộng đủ) |
| Trùng thật ở trạng thái khác WAIT_TO_CONFIRM | `test_real_bigquery_a_real_duplicate_still_blocks`, `test_a_real_duplicate_still_blocks_and_the_report_states_the_rules` |
| Join fan-out và trùng hoàn toàn | `test_real_bigquery_an_order_line_fanned_out_over_item_codes_blocks`, `test_real_bigquery_customer_counts_join_never_multiplies_demand`, `test_real_bigquery_customer_counts_join_never_changes_lines_quantities_or_open_hours` |
| Trạng thái trộn và chuyển trạng thái | `test_real_bigquery_mixed_statuses_never_form_one_group_and_pending_spelling_is_normalised` |
| Nhiều item, SO khác, miền khác, cùng FC | `test_v1210_multi_item_open_hours.py`, `test_v1210_real_bq_multi_item_regions.py` |
| Hồi quy fix 7.1 | Các test fix 7.1 được giữ và đổi kỳ vọng theo quy tắc mới. Dòng chờ xác nhận giống mọi cột trước đây chặn, nay được miễn và báo cáo. Đây là quyết định của chủ hệ thống, không phải làm yếu test. |

## 4. Diễn tập, proxy, kiểm chứng phụ

| Kiểm chứng | Loại | Kết quả | File |
|---|---|---|---|
| Diễn tập r12 (`iso1211r.ps1`): 1.2.10 chính thức cô lập trên bản sao DB production → deploy-upgrade 1.2.11 → kiểm tra → preview toàn kỳ → đối soát → D-1 dry run → D-1 "Chạy ngay" → đối soát → cổng huấn luyện → smoke → rollback-version → kiểm tra | isolated install + DB copy + BigQuery thật (chỉ đọc) | **36/36 PASS** (chi tiết bên dưới) | `iso1211r_console_r12.txt`, `iso1211r_result_r12.json` |
| Proxy chỉ đọc (mã repo 1.2.11) trước production trên cổng tạm 127.0.0.1:8896, không tunnel (`proxy_check.ps1`) | production (chỉ GET đi qua) | **28/29** (chi tiết bên dưới) | `state\proxy_check.json`, `state\proxy_check_access*.log` |
| Kiểm toán endpoint được proxy cho phép (agent đọc mã) | đọc mã | 1 endpoint ghi được: `GET /api/data-quality` (INSERT `validation_reports` khi chưa có cache) - đã chặn; HEAD trên `/api` - đã chặn | báo cáo agent (tóm tắt ở FINAL_REPORT) |
| Hạt dữ liệu ở mọi bảng tiêu thụ (`grain_check.py`, bản sao production) | DB copy | 7/7 bảng khóa SKU × FC (× ngày / run / snapshot) duy nhất, không bảng nào có cột item | `state\grain_check_*.json` |

Chi tiết diễn tập r12:

- Nâng cấp mất 430 s, gián đoạn 266 s.
- Không migration: mọi bảng giống hệt, chỉ `audit_log` +1.
- Preview `BFP-20261021102725-09F712` READY sau 338 s, 0 thay đổi. Đối soát độc lập bằng preview: 1.360.913 khóa = nguồn; giờ mở bán OK 1.360.907 / MULTI_ITEM 6.
- D-1 dry run: 0 nhóm trùng, 855 dòng chờ xác nhận được miễn.
- D-1 thật `JOB-20261021103356-F8D179` (17-20/10) SUCCEEDED: 11.995 khóa, 0 đổi; app = nguồn trên toàn kỳ.
- Huấn luyện thử `JOB-20261021103524-7A3984`: FAILED `OPEN_HOURS_INVALID`, không có model.
- Smoke 19 GET đều 200.
- `rollback-version -To 1.2.10` (cùng schema, không restore): 14 s, gián đoạn 6 s. Dữ liệu giống hệt; dry run 1.2.10 vẫn READY.

Chi tiết kiểm tra proxy:

- Đọc được (200): `/`, health, status, schedules, forecast runs, history, data-quality history, settings. Không lộ đường dẫn Windows.
- Bị từ chối: 6 ghi (405), `HEAD /api` (405), `/api/data-quality` (403), 7 API quản trị (403).
- Kill proxy rồi khởi động lại: đọc lại được.
- 1 FAIL là do PowerShell chuẩn hóa `../`. Gửi đường dẫn nguyên văn bằng `curl --path-as-is` nhận 400. Đường dẫn đã chuẩn hóa chỉ trả `index.html` 779 byte, không phải DB.

## 5. Không làm để đạt PASS

- Không xóa test, không làm yếu kiểm tra ở trạng thái khác WAIT_TO_CONFIRM.
- Không tắt giờ mở bán bắt buộc, không điền giờ.
- Không dùng `item_code`, hậu tố hay `customer_id` làm khóa.
- Không sửa dữ liệu nguồn.
