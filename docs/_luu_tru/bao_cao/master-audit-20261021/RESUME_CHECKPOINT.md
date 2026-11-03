# Resume checkpoint - master audit 21/10/2026

## Trạng thái

- Production: **1.2.8**, schema 6, `http://127.0.0.1:8765` (tiến trình 10884), `storage.json` SHA-256 `8D79DBDD…E047` không đổi. Không
  triển khai, không backfill, không chốt actual, không huấn luyện, không đổi cấu hình / lịch / ánh xạ, không push.
- Git: `main` tại `a9486bb` (trước origin 28 commit, chưa push). Thay đổi của batch này **chưa commit** (không có phê duyệt commit):
  11 file sửa + 4 file test mới (danh sách bên dưới).
- Gói 1.2.9 (`dist\DemandForecast-1.2.9-win64-portable.zip`, `B705F3DF…62BB`, từ `15d4f4b`) **không** chứa sửa của batch này.

## File thay đổi (working tree)

| File | Thay đổi |
|---|---|
| `backend/app/bq/connector.py` | quy tắc đơn chờ xác nhận chưa có mã (`PENDING_STATUSES`, `_pending_expr`, `_exact_dup_rows_expr`) ở cổng trùng, kiểm tra toàn kỳ, D-1 |
| `backend/app/bq/dup_report.py` | trang Summary: quy tắc + số dòng chờ xác nhận |
| `backend/app/ml/feature_registry.py` | coverage `NOT INDEXED` |
| `backend/app/ml/pipeline.py` | data_lineage `NOT INDEXED` |
| `backend/app/data/demand.py` | load_demand `NOT INDEXED` + `ORDER BY` thứ tự khóa |
| `backend/tests/test_bq_real_semantics.py` | kỳ vọng theo quy tắc mới + cặp NULL trạng thái khác |
| `backend/tests/test_v129h_pending_orders_grain.py` (mới) | 12 test offline |
| `backend/tests/test_v129h_perf_scans.py` (mới) | 2 test offline |
| `backend/tests/test_v129h_real_bq_pending_grain.py` (mới) | 3 test BigQuery thật (opt-in, 0 byte) |
| `frontend/src/pages/BigQuery.tsx`, `frontend/src/i18n.tsx` | dòng "đơn chờ xác nhận chưa có mã" trong bảng trùng |
| `frontend/src/v129h-pending.test.tsx` (mới) | 2 test |
| `CHANGELOG.md` (mục Unreleased), `docs/BIGQUERY.md` (mục 13), `docs/data/DATA-MODEL.md`, `docs/CHECKPOINT.md` | tài liệu |

## Checkpoint

- Trước khi sửa: `checkpoints\source-1.2.9-before-master-audit-20261021-010045.zip`
  SHA-256 `86BBDF6C41DB0B4996ED8566F21190F0B442C9A1FD985AF99E1FEB71B454C429` (git archive của `a9486bb`, 358 file).
- Sau batch: `checkpoints\checkpoint-20261021-master-audit.zip` (diff + nội dung file đổi + thư mục báo cáo này + script/kết quả scratchpad p25;
  SHA-256 trong file `.sha256` cạnh zip và trong `docs/CHECKPOINT.md`).
- Scratchpad: `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p25\`
  (bản sao DB `copy\`, môi trường cô lập `v\` đã migrate lên schema 9, script kiểm toán, kết quả JSON; tạm thời, có thể mất khi dọn Temp).

## Lệnh tiếp tục

```powershell
# 1. xem thay đổi
cd "D:\Buymed\Lightgbm AI"; git status; git diff --stat
# 2. test (backend ~8 min, chạy nền)
cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
cd ..\frontend; npm test; npm run typecheck; npm run build
# 3. BigQuery thật trên dòng inline (0 byte, cần ADC của tài khoản Windows này)
cd ..\backend; $env:DF_REAL_BQ = "1"; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_bq_real_semantics.py tests\test_v129h_real_bq_pending_grain.py
# 4. kiểm toán nguồn lại (chỉ đọc, dry-run + trần 2 GiB) khi nguồn dựng lại
& .\.venv\Scripts\python.exe -X utf8 <scratchpad p25>\bq_audit.py <out.json>
```

## Việc tiếp theo (cần người quyết)

1. **Phê duyệt** commit + phát hành bản kế tiếp (vd. 1.2.10) gồm MA-02 và MA-08..10: bump version, `scripts\release.ps1`, diễn tập nâng cấp /
   rollback cô lập, rồi `deploy-upgrade.ps1 -CheckOnly` → triển khai → preview → backfill → đối soát → chốt actual, ngoài khung lịch.
2. **Nhóm nguồn** xác nhận các thay đổi lịch sử của lần dựng lại 20/10 22:18 (785 khóa mất, 344 khóa mới) trước backfill; cân nhắc phân vùng bảng.
3. **Chủ hệ thống** chọn quy tắc cho 6 khóa MULTI_ITEM (hoặc giữ chặn) và phạm vi quy tắc combo.

## Điều kiện dừng đã tuân thủ

Không xóa / reset / stash / checkout đè; không xóa log / checkpoint / backup; không chạy lệnh phá hủy; không đổi lịch D-0 / D-1 / huấn luyện;
Price giữ ON; `customer_id` giữ OFF; không suy ra FC từ hậu tố; không dùng `sku_system_status` hiện tại làm trạng thái lịch sử.
