# Kết quả kiểm thử - release 1.2.12 (21-22/10/2026)

Mã nguồn: commit `a601f4c` (release `fe4ca9b` + bản sửa `a601f4c`), chưa push. Gói
`dist\DemandForecast-1.2.12-win64-portable.zip`, SHA-256 `10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05`,
source fingerprint `A4DB818B313CD67F`, Python nhúng 3.14.7.

## 1. Bảng tổng hợp

| Lần chạy | Loại | Kết quả |
|---|---|---|
| `scripts\release.ps1` - QA backend trên commit `a601f4c` | unit + integration với fake, DB tạm cách ly | **716 passed / 19 skipped / 0 failed** (351 s) |
| `scripts\release.ps1` - vitest | unit UI (jsdom) | **159 / 159 passed** (26 file) |
| `scripts\release.ps1` - typecheck, build | tĩnh / build | 0 lỗi / build OK |
| BigQuery thật, opt-in (`DF_REAL_BQ=1`): `test_v129h_real_bq_pending_grain`, `test_bq_real_semantics`, `test_v1210_real_bq_multi_item_regions`, `test_v129e_real_bq_item_suffix`, `test_v129c_real_bq_items_customers`, `test_v129_real_bq_open_hours` | real external, chỉ đọc | **14 passed** (58 s) |
| Test mới `test_v1212_open_hours_override.py` | unit / integration, DB cách ly, dữ liệu tổng hợp, LightGBM thật | **22 passed** |
| Test mới `test_v1212_weekday_parity.py` | unit, panel tổng hợp, LightGBM thật | **8 passed** |
| Test mới `v1212-weekday.test.tsx` | unit UI | **4 passed** (trong 159) |
| Cổng giờ mở bán trên **bản sao production** (`gate_copy.py`, mã 1.2.12) | DB copy | 6 / 6 khóa được phủ, `not_ok` rỗng, `demand_daily` không đổi (hash), data-check giờ mở bán OK |
| Diễn tập cách ly `iso1212r.ps1` (r13) | cài đặt cách ly trên DB copy | **36 / 36 PASS** (1.210 s) |
| Đối soát dữ liệu huấn luyện với nguồn (`recon_d1.py`) | DB copy + tổng hợp nguồn độc lập | khớp tuyệt đối (mục 4 `DATA_RECONCILIATION.md`) |
| Lint | - | **không cấu hình** (không tính là đạt) |

- 19 test skipped = test BigQuery thật / D-0 thật opt-in. Các test liên quan được chạy riêng ở dòng "BigQuery thật".
- Không test nào bị sửa để cho qua. Kỳ vọng thay đổi có chủ đích, theo yêu cầu "Thứ 2 … Chủ nhật" cho ngày dự báo, ở 5
  file frontend: `v112`, `v113`, `v125`, `v125-history`, `v126`.

## 2. Lần QA thất bại (đã sửa trước khi đóng gói)

- `release.ps1` trên commit `fe4ca9b` (22:09): QA backend thất bại, khoảng 18 test. **Không gói nào được tạo** (release dừng
  đúng thiết kế).
- Nguyên nhân: bản đầu biến khóa đã duyệt nhưng không còn dòng (`ROW_NOT_FOUND`) thành chặn huấn luyện
  (`OVERRIDE_KEY_NOT_FOUND`). Cấu hình BigQuery mặc định của test dùng đúng tên bảng production. Vì vậy mọi scope BigQuery
  tổng hợp, vốn không có 6 dòng, đều bị chặn `OPEN_HOURS_INVALID`.
- Sửa ở `a601f4c`: khóa không có dòng thì không được gán gì (không có dòng nào cần giá trị, không đoán) và được ghi kèm lần
  huấn luyện. Khóa có dòng nhưng không khớp vẫn chặn.
- QA chạy lại trên `a601f4c`: 716 passed.

## 3. Đánh giá độc lập (data-reviewer, chỉ đọc)

Kết luận: SAFE WITH CONDITIONS, không có BLOCKER. Xử lý từng mục:

| Mục | Xử lý |
|---|---|
| S1 - khóa đã duyệt không còn dòng | Không gán gì và được báo cáo. Docstring sửa cho đúng. Lần đầu xử lý bằng cách chặn; cách đó làm hỏng các scope hợp lệ (mục 2) nên đã bỏ. |
| S2 - kiểm lại khung dữ liệu khi gán | `fill()` kiểm số lượng, số đơn, giá trị chưa có, và giá trị là MAX hợp lệ của listing đã ghi. Có test. |
| S3 - giá trị listing có thể đổi sau khi nạp lại | Chỉ áp dụng cho đúng lần nạp đã đối chiếu (`APPROVED_LOADED_AT`). Nạp lại thì chặn với lý do `RELOADED_SINCE_APPROVAL`. Có test. |
| S4 - bằng chứng | `OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx`, bản sao production, diễn tập. |
| N1 - giá trị đã ghi không hợp lệ | `fill()` kiểm hữu hạn, 0..24 và là MAX. |
| N5 - cảnh báo data-check | Không cảnh báo khi khóa đã OK nhờ nguồn, hoặc không còn dòng. |
| N6 - hiệu năng khi so ngày | So trực tiếp cột TEXT, không đổi kiểu trên 1,36 triệu dòng. |
| N2, N3, N4 | Ghi nhận trong `FINAL_REPORT.md` mục 8. |

## 4. Diễn tập r13 (`iso1212r.ps1`, 36 / 36)

Môi trường cách ly: `LOCALAPPDATA` riêng, cổng 8879, scheduler tắt, DB sao chép bằng backup API (nguồn `mode=ro`) cùng file
model. Các bước:

1. Cài 1.2.11 chính thức. Baseline: huấn luyện bị chặn bởi đúng 6 dòng `MULTI_ITEM`.
2. `deploy-upgrade -CheckOnly` không ghi gì vào bản sao.
3. Nâng cấp lên 1.2.12: exit 0, 286,5 s, gián đoạn 122,1 s, có backup trực tuyến.
4. Không migration (schema 9, cùng trigger). Mọi bảng nghiệp vụ giống hệt; chỉ `audit_log` +1. Settings, model, 5 luồng lịch
   và trạng thái hệ thống không đổi.
5. Bundle UI mới có cột thứ của ngày dự báo.
6. Cổng 1.2.12:
   - `blocked_by` rỗng; đúng 6 dòng được phủ với MAX 24, 24, 24, 24, 24, 22,85;
   - 33 feature, gồm `open_hours_last`, `dow`, `is_weekend`, `price_last`; không có feature khách hàng;
   - data-check `open_hours_window_ready` và `open_hours_owner_override` OK;
   - 6 dòng lưu giữ nguyên (`MULTI_ITEM`, NULL, cùng số lượng / số đơn / `loaded_at`).
7. D-1 dry run trên nguồn thật: READY, 0 nhóm trùng.
8. Smoke GET: tất cả 200.
9. Rollback về 1.2.11 (cùng schema, không restore):
   - `-CheckOnly` exit 0; rollback 14,8 s, gián đoạn 6,1 s;
   - bảng, settings và lịch như trước;
   - 1.2.11 chặn lại đúng 6 dòng, chứng minh quy tắc đảo ngược được, không cần sửa dữ liệu.
10. Production vẫn 1.2.11 và sống; SHA gói không đổi.

## 5. Bằng chứng bổ sung (không phải test)

- Truy vấn BigQuery chỉ đọc (dry run trước, giới hạn byte) cho 6 khóa (`bq_six.py`):
  - `0ff8827f-99df-43c8-a0f6-64b53cc3cbfa` (listing);
  - `3e308e70-c4b9-485e-977a-0b88805d49bd` (khóa);
  - `cfc2a6f0-28e7-4242-bbd8-9e93b4dd5713` (độ mới).
- Bảng nguồn sửa lần cuối 2026-10-21 00:10:38 UTC; cùng bản trong suốt lần đọc.
- Hồ sơ `customer_id` và tổng hợp khách hàng (`cust_bq.py`, SQL của ứng dụng): 4 truy vấn chỉ đọc. Xem `cust_bq.json` trong
  checkpoint.

## 6. Lượt 22/10/2026 (10:53-11:40): kiểm trước deploy, deploy bị từ chối

Không chạy lại QA hay build: gói và mã không đổi. Commit sau `a601f4c` chỉ là `24590d2`, thay đổi duy nhất `docs/CHECKPOINT.md`.

| Kiểm tra | Loại | Kết quả |
|---|---|---|
| Gói 1.2.12 (`pkg_check.py`): SHA-256, VERSION, BUILD-INFO, manifest, file chính so với commit, quy tắc 6 khóa, weekday, mã khách, bundle UI, file cấm | kiểm tĩnh gói | **PASS** (chi tiết bên dưới) |
| Test của dự án trong gói | - | Không đóng gói, đúng thiết kế. 3 file test 1.2.12 có trong commit `a601f4c`, kết quả ở mục 1 |
| Backup trực tuyến chính thức (`POST /api/system/backups`, cùng đường `deploy-upgrade` dùng) + `verify_b.py` | production (tạo file backup) + kiểm chỉ đọc | **PASS** (chi tiết bên dưới) |
| `deploy-upgrade.ps1 -CheckOnly`, đúng lệnh được giao | production, chỉ đọc | **PASS**, exit 0 (11:16:12-11:18:33), `PRECHECK OK` |
| `deploy-upgrade.ps1 -ConfirmToken "UPGRADE-1.2.12"`, đúng lệnh được giao | production | **BỊ TỪ CHỐI** bởi bộ phân loại quyền (auto mode) của Claude Code lúc 11:20:37. Lệnh không chạy, không thử đường khác |
| Đối soát nguồn đến 21/10 (`src_agg_d1.py` + `recon_d1.py`) | BigQuery thật (chỉ đọc) + DB copy | Cửa sổ D-1 khớp tuyệt đối. Lịch sử lệch 841 khóa (`DATA_RECONCILIATION.md` mục 5) |
| 6 khóa ở mức listing (`bq_six.py`, bản nguồn 22/10) | BigQuery thật, chỉ đọc | 12 / 12 giá trị giống bản đã duyệt; không có khóa nhiều listing lệch giờ nào khác |
| Cổng giờ mở bán 1.2.12 trên bản sao 22/10 (`gate_copy.py`) | DB copy | **PASS**: phủ đúng 6 dòng, `not_ok` rỗng, dữ liệu không đổi |
| `app.cli data-check` của production 1.2.11 | production, chỉ đọc | WARN, 0 FAIL (30 / 32 OK) |
| Kiểm tra sau deploy: health, smoke, cổng 6 khóa, cấu hình / lịch, data-check 1.2.12, rollback `-CheckOnly` | - | **NOT STARTED** (deploy bị từ chối) |

**Chi tiết gói:**
- SHA-256 đúng giá trị kỳ vọng.
- BUILD-INFO: commit `a601f4c`, `dirty` false, source fingerprint `A4DB818B…6781`.
- Manifest: 7.148 / 7.148 file khớp SHA-256.
- 14 / 14 file chính giống hệt commit, gồm `open_hours_override.py`, `pipeline.py`, `features.py`, `connector.py`,
  `deploy-upgrade.ps1` và `rollback-version.ps1`.
- `RULE_VERSION` 1.2.12, đủ 6 khóa.
- Có `dow`, `is_weekend`, ISO, và `_customer_ctes` (tắt theo cài đặt).
- Bundle `web/assets/index-BkuuaeJI.js` có "Thứ 2" … "Chủ nhật" và `fh-row-target`.
- 0 file cấm.

**Chi tiết backup:**
- `backups\backup-20261022-111140-manual.zip`, SHA-256 `A3564E18EBAEC29953334EFBC3BDF4F2EA72AD9EF1034F3345E84B865866AFD6`.
- CRC đạt, integrity ok, 0 FK, schema 9.
- Có job mới nhất `JOB-20261022034240-F8F64C`, audit tới 03:43:01 UTC, model và forecast đang dùng.
- 12 / 12 file model giống hệt.
- Lần kiểm đầu báo lỗi do **kỳ vọng của tôi sai**: tôi lấy mốc audit *sau* khi backup, trong khi chính backup ghi thêm audit
  `BACKUP_CREATED` lúc 04:12:58. Kiểm lại với mốc lấy trước backup: PASS. Không có lỗi nào ở file backup.
