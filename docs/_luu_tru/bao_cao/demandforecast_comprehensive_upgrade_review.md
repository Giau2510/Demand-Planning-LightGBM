# Demand Forecasting: rà soát tổng thể dữ liệu, mô hình, backtest và an toàn (1.2.9, đợt 2)

Thời gian: 19/10/2026 22:35 – 20/10/2026 01:25, giờ Asia/Ho_Chi_Minh. Phạm vi theo prompt "Comprehensive Data, Model
Intelligence, Backtesting & Safety Upgrade". **Không commit, không push, không đóng gói, không cài, không deploy,
không huấn luyện production, không chạy D-0 / D-1 / EOD / backfill production, không đổi lịch hay cấu hình production.**
Production vẫn là **1.2.8** (kiểm chỉ đọc lúc 01:16 ngày 20/10: health 1.2.8, `current.txt` 1.2.8, forecast `FCR-20261019060524-9DE420`, nguồn BIGQUERY, `storage.json` `8D79DBDD…`; job mới chỉ có EOD 23:55 và chốt 23:59 của lịch, đều SUCCEEDED).

## Tóm tắt kết quả

| Mảng việc | Kết quả | Ghi chú ngắn |
|---|---|---|
| A. Thứ trong tuần (1–7) | **PASS** | Giữ nguyên; thêm test: đổi công tắc sau khi huấn luyện không làm lệch model đã có |
| B. `total_open_hours` bắt buộc + vai trò cột D-1 | **PARTIAL** | Cơ chế đúng và đã diễn tập trên dữ liệu thật (bản sao); bị chặn bởi dữ liệu nguồn: thiếu trước 19/03, 2 nhóm xung đột do nguồn tính theo item |
| C. Tên thứ tiếng Việt | **PASS** | Giữ nguyên; "Ngày thứ" (vị trí trong kỳ) và "Thứ trong tuần" vẫn tách biệt |
| Báo cáo deploy 1.2.8 ghi BLOCKED | **PASS** | Đã sửa tài liệu: BLOCKED 19:41 là trạng thái trước deploy; trạng thái cuối DEPLOYED_AND_VERIFIED (20:08), có bằng chứng |
| Điều tra dữ liệu giờ mở bán | **PASS** (điều tra) / quyết định còn mở | Đã xác định nguyên nhân 2 xung đột; 3 phương án cho giai đoạn thiếu, có số liệu |
| Backfill có kiểm soát | **PASS** (mã nguồn + diễn tập trên bản sao) | Thêm bắt buộc xem trước, mã xem trước, backup trước khi ghi; **chưa chạy backfill production** |
| Lịch sử forecast hiện số lẻ | **PASS** | Trang Lịch sử dùng số nguyên (cùng quy tắc với trang Kết quả), Excel H3 |
| Chỉ số theo nhóm nhu cầu (backtest) | **PASS** | Thêm vào mọi lần huấn luyện, chỉ để đánh giá |
| `customer_id` / chu kỳ mua lại | **BLOCKED** | Nguồn không có cột khách hàng; chỉ có thiết kế đề xuất |
| Thí nghiệm mô hình (tuning, feature) | **PASS** (thí nghiệm) / không đổi production | 66 lượt huấn luyện fold trên bản sao. Ứng viên tốt nhất (chặn đột biến khi huấn luyện + 63 lá) giảm WAPE 0,798 → 0,760 trên fold giữ lại, nhưng dự báo thiếu nhiều hơn (bias −16% so với −10%): cần chủ hệ thống quyết định, chưa đưa vào ứng dụng |
| Migration 0007 + rollback | **PASS** | Diễn tập lại trên bản sao mới: idempotent, giá trị cũ giữ nguyên, 1.2.8 từ chối schema 7, backup tự động khôi phục được |
| Test | **PASS** | Backend 588 passed / 8 skipped / 0 failed; BigQuery thật 8 + 17 passed; vitest 145/145; typecheck, build đạt; lint chưa cấu hình |

---

## 1. Trạng thái repository, file đã xem và đã sửa

- Nhánh `main`, HEAD `0da73b6` (Release 1.2.8), ahead 26 so với `origin/main` (ref local, không fetch). **Chưa
  commit** gì trong đợt này. Working tree: 56 file sửa + 9 file mới (65), `git diff --stat`: 1.404 dòng thêm, 182 dòng xóa (gồm cả đợt 1).
- Đợt trước (1.2.9 đợt 1, báo cáo `reports/weekday_total_open_hours_mapping_fix.md`) để lại 42 file sửa + 6 file mới,
  chưa commit; đợt này giữ nguyên các thay đổi đó và chỉ sửa thêm.
- Checkpoint: `checkpoints/checkpoint-20261019-v129-before.zip` (trước 1.2.9, đợt 1) và
  `checkpoints/checkpoint-20261019-v129b-worktree.zip` (63 file của working tree lúc 23:22, SHA-256
  `8207F8D6…8DFC`). **Sai lệch quy trình:** checkpoint của đợt 2 được tạo **sau** khi đã sửa; trạng thái giữa hai
  đợt không có bản riêng. Các thay đổi của đợt 2 liệt kê đầy đủ ở dưới và đều chưa commit.

**Đã đọc (chính):**
- `reports/weekday_total_open_hours_mapping_fix.md`, `reports/demandforecast_fix_and_deploy_20261019.md`;
- `backend/app/sync.py`, `bq/connector.py`, `jobs/flows.py`, `jobs/runner.py`, `api/bq_routes.py`;
- `ml/model.py`, `ml/pipeline.py`, `ml/features.py`, `ml/metrics.py`, `ml/methods.py`, `ml/training_explain.py`;
- `forecast_history.py`, `qty.py`, `backup.py`, `actual_close.py`, `data_checks.py`, `db.py`;
- `settings_service.py`, migration 0001–0007;
- trang `SqlSources.tsx`, `ForecastHistory.tsx`, `Results.tsx`;
- test `test_v116.py`, `test_v125_forecast_history.py`, `test_v126_eod_backup_close.py`,
  `test_v129_weekday_open_hours.py`;
- log deploy và hậu kiểm 1.2.8 (`scratchpad\p15\state\*`), `logs\runtime\app.log` (chỉ đọc).

**Đã sửa / thêm trong đợt này:**

| File | Thay đổi |
|---|---|
| `backend/app/sync.py` | `backfill_preview()` (xem trước chỉ đọc), `check_backfill_preview()`, `_backfill_window()`; `run_d1_sync(..., backfill_preview_id)` bắt buộc bản xem trước, backup online trước khi ghi, đánh dấu bản xem trước `USED` cùng giao dịch ghi |
| `backend/app/api/bq_routes.py` | `POST/GET /api/sync/backfill/preview`; `POST /api/sync/backfill` cần `preview_id`; kết quả job giữ thêm `open_hours_status_rows`, `preview_id`, `pre_backfill_backup` |
| `backend/app/jobs/runner.py` | truyền `backfill_preview_id` |
| `backend/app/backup.py` | file zip backup ghi dưới tên tạm, kiểm `testzip`, rồi mới đổi tên (theo review) |
| `backend/app/messages.py` | `BACKFILL_PREVIEW_REQUIRED`, `BACKFILL_BACKUP_FAILED` (vi/en) |
| `backend/app/forecast_history.py` | forecast số nguyên (`forecast_qty`) cho bảng, tổng, KPI, sai lệch, WAPE, sắp xếp, Excel H3; `yhat` giữ nguyên |
| `backend/app/export_i18n.py` | mô tả "Cách tính" của Excel lịch sử (vi/en) |
| `backend/app/ml/demand_patterns.py` (mới) | nhóm nhu cầu Syntetos–Boylan, nhóm khối lượng, ngưỡng và cờ ngày đột biến (chỉ đánh giá) |
| `backend/app/ml/model.py` | `backtest()` thêm `segments` (theo nhóm, khối lượng, ngày đột biến, ngày trong kỳ, tổng 7/15/30 ngày) |
| `backend/app/ml/pipeline.py`, `ml/training_explain.py` | lưu và trả `segments` |
| `frontend/src/pages/SqlSources.tsx` | thẻ backfill: "Xem trước (không ghi)", bảng tóm tắt, nút đọc lại chỉ bật khi bản xem trước khớp ngày, hộp xác nhận có số dòng |
| `frontend/src/pages/ForecastHistory.tsx`, `i18n.tsx` | cột Forecast số nguyên (di chuột: giá trị mô hình), sai lệch số nguyên, quy tắc hiển thị |
| Test backend | `tests/test_v129_backfill_history_patterns.py` (mới, 14 test); cập nhật kỳ vọng `test_v116.py`, `test_v125_forecast_history.py`, `test_v126_eod_backup_close.py`, `test_v121_remote_proxy.py` |
| Test frontend | `src/v129b.test.tsx` (mới, 3 test); fixture `v125-history.test.tsx`, `v126.test.tsx` thêm `forecast_qty` |
| Tài liệu | `CHANGELOG.md`, `docs/BIGQUERY.md` (backfill, mục 11b dữ liệu thật), `docs/MO-HINH-VA-CHI-SO.md`, `docs/LICH-SU-FORECAST.md`, `docs/data/DATA-DICTIONARY.md`, `docs/CHECKPOINT.md` |
| Báo cáo (ngoài Git) | `reports/demandforecast_fix_and_deploy_20261019.md` (thêm phần đầu và mục F), báo cáo này |

Không thay đổi schema mới nào ngoài migration 0007 của đợt 1.

## 2. Kết quả A/B/C của báo cáo trước: giữ nguyên hay thay đổi

| Hạng mục | Kiểm lại trong đợt này | Thay đổi |
|---|---|---|
| A. Thứ 2 = 1 … Chủ nhật = 7 | Mã và test đợt 1 (48 test) chạy lại đạt. Huấn luyện, backtest, dự báo (RECURSIVE và DIRECT), giải thích, mở rộng khoảng dự báo đều đọc `weekday_encoding` và danh sách feature **của chính run** (`extend_forecast` đọc `feature_config_json`). Thí nghiệm E02 (mã cũ 0–6 so với ISO 1–7) cho WAPE giống hệt nhau trên fold 22/05 (0,7017 = 0,7017): mã ISO không đổi chất lượng | Thêm test: tắt công tắc **sau** khi huấn luyện → giải thích vẫn khớp giá trị đã publish, `dow` vẫn là ISO của model đó; lần huấn luyện sau mới bỏ `dow` |
| B. Giờ mở bán bắt buộc | Diễn tập D-1 / backfill bằng mã 1.2.9 trên bản sao DB production với BigQuery thật (mục 4, 6). Cổng `OPEN_HOURS_INVALID` vẫn chặn đúng. Các trạng thái OK / MISSING / CONFLICT / OUT_OF_RANGE ghi đúng; không có giá trị nào bị điền 0 hay 24 | Không đổi quy tắc. Thêm bước xem trước và backup cho backfill |
| C. "Thứ 2" … "Chủ nhật" | Test frontend / backend đạt; Excel định dạng 6 giữ cột "Ngày thứ" (số) và thêm "Thứ trong tuần" | Không đổi |

## 3. Báo cáo deploy 1.2.8 ghi BLOCKED

**Kết luận:** chữ BLOCKED trong `reports/demandforecast_fix_and_deploy_20261019.md` là trạng thái của **lần thử đầu lúc
19:41**: Gate 2 FAIL vì Quick Tunnel bị xóa khi máy ngủ. Báo cáo viết lúc 19:50 và chưa được cập nhật sau lần deploy
thứ hai, vì lượt kiểm tra tiếp theo của chủ hệ thống (20:51) chỉ cho phép đọc.

Bằng chứng deploy đã hoàn tất (đều có sẵn, không chạy lại gì):
- `scratchpad\p15\state\launcher.log`: 19:56–20:02 các cổng G0–G6 PASS, backup chính thức đã kiểm; 20:02:50
  `deploy-upgrade -ConfirmToken UPGRADE-1.2.8`; 20:08:24 "exit 0 in 334.6 s (no retry)".
- `deploy_run.txt`: backup `backup-20261019-200306-manual.zip` (SHA-256 `02F00EFF…B4F4`), migration 6 → 6 (không có),
  "UPGRADE OK: 1.2.6 -> 1.2.8", app pid 10884.
- `post128_console.txt`: 14/15 PASS. Mục FAIL ("ERROR mới trong log") là dương tính giả. Kiểm lại lúc 23:12: cả 6
  dòng ERROR của `app.log` đều trước 13:02:50 UTC; dòng mới nhất là 03:21:56 UTC, job D-1 `SOURCE_INCOMPLETE` buổi sáng.
- Chỉ đọc lúc 23:11: `/api/health` = 1.2.8, `current.txt` = 1.2.8, job mới nhất vẫn là D-0 18:00.

**Đã sửa (chỉ tài liệu):**
- Thêm khung đầu báo cáo phân biệt bốn trạng thái: trước deploy (BLOCKED 19:41), deploy (20:02–20:08), hậu kiểm
  (14/15, 1 dương tính giả) và giới hạn còn lại.
- Thêm **mục F** gồm diễn biến, hậu kiểm, trạng thái lúc 23:11 và các giới hạn.
- Mục A–E giữ nguyên làm lịch sử; dòng trạng thái cũ được ghi rõ "lúc 19:50 (lịch sử)".

## 4. Dữ liệu giờ mở bán: phát hiện chi tiết

Nguồn: bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm` (17 cột, 8.942.586 dòng, không phân vùng,
cập nhật lần cuối 19/10 03:30 UTC). Mọi truy vấn chỉ đọc: dry run trước, giới hạn byte. Tổng khoảng 6,7 GB quét trong
đợt này, gồm cả lần diễn tập backfill. Mã đơn, item và seller chỉ ở dạng tiền tố SHA-256; không có dữ liệu khách hàng.

**Diễn tập D-1 / backfill trên bản sao** (mã 1.2.9, 01/01–18/10, 735 s):

| Trạng thái `open_hours_status` | Dòng ngày × SKU × FC | Khoảng ngày |
|---|---|---|
| OK | 954.889 | 19/03 – 18/10 |
| MISSING | 400.082 | 01/01 – 18/03 (nguồn NULL mọi dòng) |
| CONFLICT | 2 | 26/08 |
| OUT_OF_RANGE | 0 | — |

- Giá trị đã lưu: 0 → 24; 900.499 dòng = 24, 53.668 dòng trong (0; 24), **722 dòng = 0 dù có đơn** (21.025 đơn vị).
  Dòng = 0 được giữ là 0 với trạng thái OK, khác với "thiếu".
- Từ 19/03, 54.390 dòng (5,7%) có giờ mở bán < 24, chiếm 1,35 triệu đơn vị.

**Hai nhóm xung đột** (cùng ngày 26/08/2026, FC `BD`):

| SKU | Dòng | Item | Seller | Giờ mở bán theo item | `total_open_days` | `sku_system_status` |
|---|---|---|---|---|---|---|
| `MEDX.COU-STR-001` | 8 | 2 | 1 (INTERNAL) | item A: 23,72 (7 dòng); item B: 24 (1 dòng) | 0,99 / 1,0 | NORMAL |
| `MEDX.D6TABCV8` | 4 | 2 | 1 (INTERNAL) | item C: 18,22 (1 dòng); item D: 22,85 (3 dòng) | 0,76 / 0,95 | OUT_OF_STOCK |

- Trong mỗi item, mọi dòng có cùng một giá trị. Cùng `product_id`, cùng `open_date` (= ngày đơn), cùng `refresh_time`
  (lần làm mới cả bảng). Giá bán khác nhau giữa hai item.
- Toàn kỳ từ 19/03: 954.891 nhóm ngày × SKU × FC, 551.504 nhóm có nhiều dòng, **11 nhóm có nhiều item**. 2 trong 11
  nhóm này lệch giờ, và đó đúng là 2 nhóm CONFLICT. 0 nhóm có nhiều seller hay nhiều `open_date`.
- **Nguyên nhân:** giờ mở bán do nguồn tính **theo item** (listing của seller), còn D-1 gộp theo SKU × FC. Đây là
  **lệch hạt tổng hợp** (aggregation grain): cùng SKU có hai item hoạt động trong ngày. Không phải lỗi trùng dòng do
  join (mỗi đơn chỉ một dòng / SKU trong nhóm; không có dòng trùng tuyệt đối), không phải nhiều giá trị trong một
  item, không có dấu hiệu sửa lịch sử (một `refresh_time`).
- **Đề xuất (cần chủ dữ liệu xác nhận, không tự áp dụng):** nguồn cung cấp giờ mở bán ở mức SKU × FC × ngày
  (khoảng thời gian có **ít nhất một** item mở bán). Không suy ra được con số này từ hai số giờ của hai item, vì
  không biết hai khoảng mở có chồng nhau không: MAX chỉ là cận dưới, tổng giới hạn 24 là cận trên. Nếu chủ hệ thống
  chọn một quy tắc (ví dụ MAX), cần ghi đó là quy tắc nghiệp vụ được duyệt.

**Phát hiện khác về nguồn** (ảnh hưởng tới mục 8–9):
- `sku_system_status` (`NORMAL` 4,1 triệu dòng, `OUT_OF_STOCK` 3,6 triệu, `LIMIT` 1,2 triệu) gần như không đổi theo
  ngày: chỉ 35/17.128 cặp SKU × FC có hơn một giá trị trong 9,5 tháng. Đây là **trạng thái hiện tại** của SKU, được
  chép vào mọi dòng lịch sử. Dùng nó làm feature hay làm nhãn "hết hàng" của ngày cũ sẽ **rò rỉ thông tin tương lai**.
- Không có cột khách hàng. `order_status` không có trạng thái huỷ (COMPLETED 8,64 triệu dòng, DELIVERED 270 nghìn,
  DELIVERING, CONFIRMED, WAIT_TO_*, PROCESSING). Target = Σ `demand_quantity` của mọi dòng, đúng định nghĩa "số
  lượng lúc tạo đơn". `outbound_quantity` (đã xuất) không được dùng.
- `total_open_days` khác `total_open_hours / 24` ở hàng chục nghìn dòng mỗi tháng (làm tròn 2 chữ số). Không dùng.

## 5. Giai đoạn thiếu giờ mở bán (01/01–18/03/2026): các phương án

Số liệu trên bản sao sau diễn tập backfill:
- Giai đoạn này chiếm 400.082 / 1.354.973 dòng (29,5%) và 13,49 / 41,93 triệu đơn vị (32,2%).
- 14.138 chuỗi SKU × FC có bán trong giai đoạn; **550 chuỗi chỉ có dữ liệu trong giai đoạn này**.
- **Tết Nguyên đán 2026 (13–21/02) nằm trọn trong giai đoạn thiếu**: nhu cầu giảm từ khoảng 270 nghìn/ngày (09/02)
  xuống khoảng 11 nghìn/ngày (14–18/02), rồi về khoảng 240 nghìn/ngày (23/02).
- Nhu cầu bình quân mỗi ngày giảm dần theo tháng: tháng 1 179 nghìn, tháng 3 198 nghìn, tháng 7 136 nghìn, tháng 9 86
  nghìn, tháng 10 79 nghìn. Đây là điểm đã ghi từ 16/10, chủ hệ thống chưa xác nhận nguyên nhân.

| | A. Cửa sổ dữ liệu bắt đầu từ 19/03/2026 | B. Lấy lại giờ mở bán lịch sử từ nguồn có thẩm quyền | C. Chế độ huấn luyện lịch sử không dùng giờ mở bán |
|---|---|---|---|
| Dữ liệu | Mất 29,5% dòng, 32,2% nhu cầu, 77 / 291 ngày, 550 chuỗi; còn 214 ngày | Giữ đủ 291 ngày nếu nguồn có dữ liệu thật; hiện chưa biết nguồn nào có | Giữ 291 ngày; giờ mở bán = "không biết" trước 19/03 |
| Huấn luyện, backtest | Hết `MISSING`. Vẫn bị chặn bởi 2 dòng `CONFLICT` cho tới khi có quyết định ở mục 4. Backtest còn 5 fold 30 ngày (thay vì 7); fold đầu 22/05 | Như hiện tại sau backfill | Model phải học được cả khi giờ mở bán không biết: cần quy tắc missing value được duyệt (ví dụ NaN như ngày không có đơn) |
| Chất lượng (thí nghiệm, mục 11) | Bỏ 01/01–18/03 (O0) so với giữ (E00): 4 fold sàng lọc 0,7963 so với 0,7972 (tương đương); fold giữ lại 0,8061 so với 0,7983 (kém hơn 0,008). Mất lịch sử có chi phí nhỏ nhưng có thật | Không thử được (không có dữ liệu) | Không thử trực tiếp. E00 (không có giờ mở bán, đủ 291 ngày) là cận gần nhất: tốt hơn O0 trên fold giữ lại |
| Rủi ro | Mất Tết 2026 (Tết 2027 khoảng 06/02 cũng không có trong dữ liệu học cho tới khi cửa sổ phủ tới đó); mất mùa đầu năm; chọn mẫu theo thời gian (chuỗi ngừng bán trước 19/03 biến mất) | Phụ thuộc tính đúng của dữ liệu lấy lại; phải kiểm như dữ liệu mới | Đi ngược chính sách "bắt buộc": giờ mở bán thành tùy chọn trong 1/3 dữ liệu; cần chủ hệ thống duyệt rõ |
| Schema / migration | Không | Có thể cần bảng hoặc nguồn mới; tùy cách lấy lại | Không, nhưng cần mã mới (chế độ, cờ trên run, cổng kiểm khác) |
| Thao tác | Đổi `data_policy.window_start_date` trên giao diện (chủ hệ thống); không xóa dữ liệu (dữ liệu trước cửa sổ vẫn giữ) | Chủ dữ liệu tìm nguồn; kiểm chỉ đọc; backfill có kiểm soát sau khi được duyệt | Thiết kế, test, review riêng; không làm ngầm |
| Rollback | Đổi lại ngày bắt đầu; không mất gì | Backup trước backfill (đã có trong 1.2.9) | Không bật chế độ |

Không chọn thay chủ hệ thống. Lưu ý: cả A và C đều cần thêm quyết định về **2 dòng CONFLICT** (mục 4).

## 6. Sẵn sàng cho backfill có kiểm soát

**Production backfill KHÔNG được chạy.** Diễn tập chỉ chạy trên bản sao DB production
(`scratchpad\p17\e`, schema 7), đọc BigQuery thật (chỉ đọc).

**Kết quả diễn tập (01/01–18/10, mã đọc / ghi của 1.2.9):**
- 735,5 s; đọc 8.942.586 dòng nguồn, ước tính 1,27 GB; RAM tiến trình đỉnh khoảng 1,9 GB.
- So với dữ liệu đang lưu: 0 dòng mới, **100 dòng đổi số lượng**, 1.354.873 giữ nguyên, **27 dòng bị xóa** (nguồn
  không còn). Tổng 41.933.254 → 41.932.631 đơn vị (−623).
- Không đổi: `forecast_runs`, `forecast_values`, `training_runs`, `d0_snapshots`, `forecast_history_values`,
  `forecast_eod_snapshot_values`, `actual_closes`. `audit_log` +2. Mốc `last_d1_sync` giữ nguyên. data-check: chỉ
  WARN (giờ mở bán chưa đủ cho cửa sổ; `forecast_series_meta` có từ trước).
- Diễn tập này chạy bằng mã trước khi có bước xem trước. Bước xem trước, mã xem trước và backup được kiểm bằng test
  (mục 15) và bằng lần đọc tương tự.

**Checklist** (✔ = có trong mã 1.2.9 và có test; ✘ = chưa có / cần người làm):

| # | Yêu cầu | Trạng thái |
|---|---|---|
| 1 | Khoảng ngày rõ ràng, giới hạn `[đầu cửa sổ, hôm qua]`, tối đa 400 ngày, chỉ scope BIGQUERY đang dùng | ✔ |
| 2 | Xem trước và kiểm trước khi ghi: cùng lần đọc với lần nạp, dry run, giới hạn byte, kiểm trùng tuyệt đối, kiểm đầu ra, không ghi `demand_daily` | ✔ (mới) |
| 3 | Bản xem trước bắt buộc: đúng khoảng, cùng mapping hash, cùng SQL, ≤ 6 giờ, dùng một lần. API và job đều kiểm; kiểm lại **trong giao dịch ghi** (vẫn READY, không có D-1 chen vào, số mới / đổi / xóa đúng như đã xem) | ✔ (mới) |
| 4 | Chống trùng / ghi đè ngoài ý muốn: khóa job D-1 (không chạy chồng); ghi trong một giao dịch; đối chiếu số dòng và tổng số lượng đã ghi với số đọc, sai thì không commit; đọc rỗng không bao giờ thay dữ liệu đã có | ✔ |
| 5 | Backup / đường phục hồi: backup online đã kiểm (DB + model) ngay trước khi thay; không có backup thì không ghi | ✔ (mới) |
| 6 | Báo cáo rõ: dòng đọc / hợp lệ / bị loại theo lý do, mới / đổi / giữ / bị xóa, trạng thái giờ mở bán, ngày đã chốt sẽ có bản chốt mới | ✔ |
| 7 | Chỉ ảnh hưởng `demand_daily` trong khoảng đã chọn | ✔ (diễn tập + test) |
| 8 | Không ảnh hưởng D-0, forecast, model, lịch sử forecast, thí nghiệm; không kích hoạt huấn luyện (`flows.d1_success_today` bỏ qua backfill) | ✔ |
| 9 | Ngày đã chốt 23:59 có thực tế thay đổi: thêm bản chốt mới, không sửa bản cũ | ✔ (có từ 1.2.6) |
| 10 | Phục hồi **chỉ một khoảng ngày** từ backup (không khôi phục cả DB) | ✘ Chưa có công cụ; hiện phục hồi = khôi phục cả DB từ backup, mất dữ liệu ghi sau thời điểm backup |
| 11 | Tài nguyên: khoảng 1,9 GB RAM, 12 phút cho 291 ngày; máy production chỉ còn khoảng 2 GB RAM trống | ✘ Khuyến nghị chia theo tháng, chạy ngoài giờ D-1 03:00–05:30, D-0 08:00–18:00, huấn luyện 09:00 |
| 12 | Quyết định nghiệp vụ trước khi backfill (mục 4–5) | ✘ Chủ hệ thống |
| 13 | Deploy 1.2.9 (migration 0007) trước khi backfill | ✘ Cần phê duyệt riêng |
| 14 | Bản xem trước có ngày hôm qua mà nguồn chưa có tín hiệu hoàn tất: cảnh báo `YESTERDAY_NOT_CONFIRMED`; đọc rỗng: `BLOCKED` | ✔ (mới) |
| 15 | File backup ghi dưới tên tạm, kiểm `testzip`, rồi mới đổi tên `backup-*.zip`; lỗi giữa chừng không để lại file giống backup | ✔ (mới) |

**Review độc lập** (agent `data-reviewer`, chỉ đọc mã): **SAFE WITH CONDITIONS**, 2 phát hiện mức trung bình và 6
mức thấp. Đã sửa 1–8 và có test: kiểm lại dưới khóa ghi, dữ liệu đổi sau bản xem trước, đọc rỗng, thời gian bản xem
trước ở tương lai, cảnh báo hôm qua, file zip backup, mã nhóm số nguyên, lỗi phân nhóm không làm dừng huấn luyện.
Điểm 9 (ngày D-1 không có dòng = 0) là hành vi có từ trước, không đổi.

## 7. Ánh xạ dữ liệu và xử lý chất lượng

Đã có từ đợt 1, kiểm lại trong đợt này:
- Vai trò: khóa / target / đặc trưng bắt buộc / tùy chọn / tham chiếu / chưa phân loại. Cột chưa phân loại không bao
  giờ tự thành feature. Một cột vừa là khóa hoặc target vừa là input bị từ chối (`COLUMN_ROLE_CONFLICT`).
- Kiểm tra target, khóa, ngày, kiểu dữ liệu, trùng hạt (`DUPLICATE_OUTPUT_KEY`), giá trị âm / NaN (`check_output`) và
  giờ mở bán bắt buộc.
- Trạng thái chất lượng ghi theo **từng dòng** (`open_hours_status`); dòng lỗi giờ mở bán vẫn ghi nhu cầu.

Còn hạn chế (không đổi trong đợt này vì cần quyết định):
- **Dữ liệu thô:** D-1 chỉ lưu bản tổng hợp ngày × SKU × FC. Dòng đơn gốc nằm ở BigQuery. Truy vết gồm bảng nguồn,
  SQL (phiên bản, SHA), mapping hash, job, `loaded_at`, hash nội dung theo ngày (`data/identity.py`). Excel nhập tay
  giữ `order_lines` theo batch.
- **Chọn dữ liệu theo tác vụ:** cổng `OPEN_HOURS_INVALID` chặn **cả lần huấn luyện** khi còn một dòng không OK trong
  cửa sổ. Đây là cách xử lý thận trọng theo yêu cầu đợt 1 ("chặn khi chưa có quy tắc được duyệt"); nó trái với mong
  muốn "không loại cả batch vì vài dòng lỗi" của prompt này.
  - Cách chọn theo tác vụ khả thi về kỹ thuật: coi giờ mở bán không hợp lệ là "không biết" (NaN), như ngày không có
    đơn. Nhu cầu của dòng đó vẫn là nhãn hợp lệ.
  - Đó là một **quy tắc missing value**, cần chủ hệ thống duyệt trước khi làm.
- Nhãn thiếu không thành target: ngày không có dữ liệu toàn hệ thống là NaN, bị loại; ngày đã nạp mà SKU × FC không
  có dòng thì nhu cầu = 0 (quy tắc nghiệp vụ đã có).
- `order_qty` vẫn là số lượng lúc tạo đơn. Không dùng trạng thái huỷ, số đã xuất hay số sau huỷ.

## 8. Feature: thứ trong tuần, giờ mở bán, customer_id

| Feature | Trạng thái |
|---|---|
| `dow` (1–7), `is_weekend` | **Hoàn tất.** Thí nghiệm E01 (tắt thứ): tắt thứ làm WAPE gộp tệ hơn (0,7972 → 0,8139) và bias +1,5% → +5,5%. Thứ trong tuần có ích, giữ bật |
| `open_hours_last`, `open_hours_mean_7` | **Có trong mã, chưa dùng được trên production** (dữ liệu). Chỉ dùng giá trị trước mốc dự báo. Thí nghiệm O1 so với O0 (cùng cửa sổ từ 19/03): kết quả không nhất quán. 4 fold sàng lọc: 0,7963 → 0,7977 (kém hơn chút). Fold giữ lại: 0,8061 → 0,7959 (tốt hơn). Chưa đủ bằng chứng là giờ mở bán cải thiện dự báo; việc dùng nó là quyết định nghiệp vụ đã có (bắt buộc), không phải kết quả thí nghiệm |
| `customer_id` / chu kỳ mua lại | **BLOCKED: nguồn không có cột khách hàng** (metadata 19/10, 17 cột). Không viết mã cho dữ liệu không tồn tại |

**Thiết kế đề xuất cho customer_id** (khi chủ dữ liệu thêm cột):
1. Chỉ dùng mã khách hàng đã băm. Không lưu mã thô vào DB ứng dụng, không đưa làm input.
2. Mapping: vai trò "tham chiếu, chỉ dùng để tổng hợp". Không phải key, không phải target.
3. Tổng hợp trong BigQuery về đúng hạt SKU × FC × ngày, mỗi chỉ số chỉ dùng đơn **trước** ngày đó:
   - số khách đặt;
   - số khách quay lại;
   - số khách "đến hạn mua lại" (lần mua cuối + trung vị khoảng cách mua của khách đó với SKU đó);
   - độ lệch khoảng cách mua.
4. Lưu: thêm cột nullable hoặc bảng riêng (migration cộng thêm) và nạp lại D-1 có kiểm soát.
5. Tại mốc dự báo T: "khách đến hạn" của ngày mục tiêu t > T tính từ lịch sử < T, không dùng đơn sau T. Test rò rỉ:
   đổi dữ liệu sau T, feature tại T không đổi (như test hiện có của giờ mở bán).
6. Lịch sử khách ít: feature = NaN và mô hình dùng các feature SKU × FC sẵn có.
7. Chỉ đưa vào sản xuất khi backtest cùng fold cho thấy cải thiện, kể cả theo từng nhóm (mục 10).

## 9. Đột biến, nhu cầu gián đoạn, ràng buộc nguồn cung

- **Phân nhóm và cờ đột biến** (`ml/demand_patterns.py`) chỉ dùng để **đánh giá**. Không giá trị nào bị xóa, cắt hay
  giảm trọng số trong dữ liệu lưu hoặc dữ liệu huấn luyện của ứng dụng.
  - Ngưỡng đột biến tính theo chính chuỗi, từ lịch sử trước mốc: ≥ 10 đơn vị và lớn hơn cả 3 × trung vị ngày có đơn lẫn
    trung vị + 5 MAD chuẩn hóa.
  - Kết quả thí nghiệm ở mục 11.
- **Thí nghiệm "huấn luyện chống đột biến"** (E13): chặn trên giá trị huấn luyện tại ngưỡng, chỉ trong bản sao của
  fold; đánh giá trên thực tế không chặn. Kết quả: giảm WAPE gộp 0,7972 → 0,7691 (4 fold) và 0,7983 → 0,7627 (fold giữ lại). Ngày thường tốt hơn (0,788 → 0,738), ngày đột biến kém hơn (0,845 → 0,876), và **dự báo thiếu nhiều hơn** (bias tổng 30 ngày −9,6% → −16,0%). Chi tiết ở mục 11
- **Nhu cầu gián đoạn:** so LightGBM / quy tắc dự phòng hiện có với Croston-SBA và dự báo 0 trên cùng điểm của nhóm
  INTERMITTENT + LUMPY. Kết quả: Croston-SBA **không tốt hơn**. Trên tổng 30 ngày của nhóm INTERMITTENT: mô hình hiện tại 0,778, baseline 0,820, Croston-SBA 1,133 (dư +33%, vì nó chậm theo kịp xu hướng giảm). Dự báo 0 cho WAPE theo ngày = 1,0 nhưng thiếu 100%, không dùng được để đặt hàng. Giữ cách hiện tại
- **Ràng buộc nguồn cung / nhu cầu bị cắt:** tín hiệu lịch sử duy nhất dùng được là giờ mở bán (từ 19/03).
  - `sku_system_status` là trạng thái hiện tại (rò rỉ, mục 4). Không có tồn kho hay giới hạn bán theo ngày.
  - `outbound_quantity` (đã xuất) chưa đủ cho ngày gần đây và là thông tin sau mốc; dùng làm tín hiệu thiếu hàng cần
    định nghĩa nghiệp vụ riêng.
  - **Không thể khôi phục nhu cầu thật (latent demand)** từ dữ liệu hiện có. Không ước lượng nào được lưu làm thực tế.
  - Đánh giá riêng các ngày có giờ mở bán < 24 (thông tin của ngày mục tiêu, chỉ dùng để phân nhóm đánh giá):
    WAPE 0,92, bias −26% trên 33.953 điểm (4 fold sàng lọc). Ngày có giờ mở bán < 24 lại có nhu cầu cao hơn dự báo; điều này khớp với việc hết hàng sau khi bán chạy (nhu cầu bị cắt), nhưng dữ liệu không chứng minh được
- **Cửa sổ bán ngắn:** không nhân nhu cầu theo 24 / giờ mở bán. Model chỉ thấy giờ mở bán của các ngày trước mốc.

## 10. Kiến trúc huấn luyện, backtest, tuning và khoảng trống

Đã có:
- **Cửa sổ dữ liệu có phiên bản:** hash nội dung theo ngày, cột dùng, mapping hash, SQL, khoảng ngày được lưu với mỗi
  run.
- **Walk-forward:** tối đa 12 fold × 30 ngày; mỗi fold chỉ dùng dữ liệu trước mốc. So với baseline 28 ngày trên cùng
  điểm; chỉ số theo phương pháp.
- **Lưu mỗi lần chạy:** cấu hình, feature, tham số, chỉ số, tầm quan trọng feature, model + SHA.
- **Bảo vệ model đang dùng:** ứng viên chỉ được dùng khi người dùng bấm promote (`PROMOTION_REVIEW_REQUIRED`). So với
  model đang dùng trên cùng điểm (`compare_with_incumbent`). Không tự thay.

Thêm trong đợt này: chỉ số theo nhóm (`segments`) lưu với mỗi backtest: nhóm nhu cầu, khối lượng, ngày đột biến, ngày
1–7 / 8–15 / 16–30, WAPE tổng 7 / 15 / 30 ngày.

Khoảng trống (chưa làm):
- **Tuning trong ứng dụng:** chưa có. Thí nghiệm của đợt này chạy bằng script ngoài ứng dụng, trên bản sao.
  - Tham số không có trong cài đặt: `min_data_in_leaf`, `feature_fraction`, `lambda_l2`, `tweedie_variance_power`.
  - Muốn dùng phải thêm vào cấu hình, có test và được duyệt.
- **Holdout độc lập:** backtest của ứng dụng dùng mọi fold để chấm. Thí nghiệm đợt này tách 4 fold để chọn và 1 fold
  cuối để giữ lại.
- **Quality gate theo nhóm:** quality gate vẫn chỉ dùng chỉ số gộp. Ngưỡng theo nhóm là quyết định nghiệp vụ.
- **Lịch sử thí nghiệm** không lưu trong DB ứng dụng (chỉ ở scratchpad).

## 11. Thí nghiệm: baseline và ứng viên

**Thiết kế (cố định trước khi chạy).**

- **Dữ liệu:** bản sao `scratchpad\p17\e` sau diễn tập backfill, tức DB production lúc 22:38 cộng nguồn đọc lại.
  Scope BIGQUERY có 1.354.973 dòng, 17.128 chuỗi, 01/01–18/10/2026 (291 ngày). O0 / O1 dùng 19/03–18/10 (214 ngày,
  16.578 chuỗi).
- **Mã:** working tree 1.2.9, đúng các hàm của ứng dụng: `load_demand`, `build_panel`, `registry.resolve`,
  `model.train`, `model.forecast`, `baseline_forecast`. Script `scratchpad\p17\exp\harness.py`. Không publish, không
  ghi model; bản sao chỉ được đọc.
- **Cấu hình gốc E00** = cấu hình của model đang dùng `TRN-20261019043033-A761C1`: DIRECT (12 mốc × 7 ngày), tweedie
  1.2, learning rate 0,05, 31 lá, 300 vòng, `min_data_in_leaf` 20, giá bật, thứ mã ISO, 31 feature. Seed 7,
  `deterministic`, 8 luồng CPU.
- **Fold:** đúng các fold backtest của production, mỗi fold 30 ngày:
  - **sàng lọc:** 4 mốc 22/05, 21/06, 21/07, 20/08;
  - **giữ lại:** mốc 19/09 (19/09–18/10), không dùng để chọn.
  - Quy tắc chọn đặt trước giai đoạn 2: WAPE gộp thấp nhất trên 4 fold sàng lọc.
- **Chỉ số:** chỉ trên ngày đã biết thực tế; WAPE, bias, MAE, theo nhóm (mục 9, 10) và tổng kỳ 7 / 30 ngày. Nhóm và
  ngưỡng đột biến chỉ dùng 91 ngày trước mốc.
- **Kiểm tái hiện:** E00 theo fold là 0,7017 / 0,7231 / 0,7972 / 1,1006, fold giữ lại 0,7983. Backtest đã lưu của
  production là 0,7068 / 0,7318 / 0,7948 / 1,1050 / 0,8085. Chênh ≤ 0,01, do dữ liệu được đọc lại (100 dòng đổi, 27
  dòng bị xóa) và số luồng khác nhau.

**Sàng lọc (4 fold, 1.956.344 điểm, 15,45 triệu đơn vị thực tế).** Đơn vị: WAPE (càng thấp càng tốt); bias của tổng
mọi điểm.

| ID | Thay đổi so với E00 | WAPE | Bias | MAE | SMOOTH | ERRATIC | Khối lượng lớn | Ngày đột biến | Ngày thường | Tổng 7 ngày | Tổng 30 ngày |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | trung bình 28 ngày, cùng điểm | 0,8599 | +13,6% | 6,79 | | | | | | | |
| **E00** | cấu hình production | **0,7972** | +1,5% | 6,30 | 0,528 | 0,839 | 0,695 | 0,855 | 0,785 | 0,495 | 0,477 |
| E01 | tắt thứ trong tuần | 0,8139 | +5,5% | 6,43 | 0,536 | 0,858 | 0,712 | 0,853 | 0,806 | 0,494 | 0,481 |
| E02 | mã thứ cũ 0–6 (1 fold) | = E00 trên fold đó (0,7017) | | | | | | | | | |
| E03 | 63 lá | 0,7909 | +0,2% | 6,25 | 0,534 | 0,834 | 0,692 | 0,857 | 0,778 | 0,484 | 0,474 |
| E04 | 15 lá | 0,8052 | +3,7% | 6,36 | 0,527 | 0,843 | 0,701 | 0,852 | 0,796 | 0,503 | 0,478 |
| E05 | learning rate 0,03 × 600 vòng | 0,7950 | +1,1% | 6,28 | 0,529 | 0,834 | 0,693 | 0,856 | 0,783 | 0,493 | 0,476 |
| E06 | 600 vòng | 0,7939 | +0,1% | 6,27 | 0,531 | 0,832 | 0,691 | 0,858 | 0,781 | 0,492 | 0,480 |
| E07 | `min_data_in_leaf` 100 | 0,7976 | +1,3% | 6,30 | 0,531 | 0,839 | 0,697 | 0,855 | 0,786 | 0,494 | 0,479 |
| E08 | objective poisson | **thất bại**: fold 2 phân kỳ (WAPE 6,6·10²⁰), fold 3 LightGBM dừng (`best_split_info.left_count > 0`) | | | | | | | | | |
| E09 | tweedie power 1,5 | 0,7983 | +2,8% | 6,31 | 0,531 | 0,841 | 0,700 | 0,856 | 0,787 | 0,498 | 0,474 |
| E10 | `feature_fraction` 0,7, `lambda_l2` 5 | 0,7930 | +1,9% | 6,27 | 0,525 | 0,829 | 0,690 | 0,855 | 0,780 | 0,492 | 0,469 |
| E12 | RECURSIVE | 0,9701 | +30,1% | 7,66 | 0,593 | 1,100 | 0,883 | 0,809 | 1,003 | 0,522 | 0,623 |
| E13 | chặn đột biến khi huấn luyện | 0,7691 | −2,4% | 6,08 | 0,528 | 0,804 | 0,674 | 0,869 | 0,749 | 0,467 | 0,453 |
| **E14** | E13 + 63 lá (**được chọn**) | **0,7650** | −3,9% | 6,04 | 0,532 | 0,801 | 0,673 | 0,871 | 0,744 | 0,463 | 0,455 |
| O0 | cửa sổ từ 19/03 | 0,7963 | +1,7% | 6,65* | 0,528 | 0,843 | 0,695 | 0,856 | 0,784 | 0,489 | 0,474 |
| O1 | cửa sổ từ 19/03 + giờ mở bán | 0,7977 | +1,7% | 6,67* | 0,530 | 0,843 | 0,697 | 0,858 | 0,785 | 0,491 | 0,477 |

\* MAE của O0 / O1 tính trên ít chuỗi hơn, nên không so trực tiếp với E00. So trên đúng cùng các điểm: WAPE như
trong bảng (`common_window.json`).

**"Chặn đột biến khi huấn luyện" (E13 / E14):**
- Trong bản sao huấn luyện của từng fold, ngày nào vượt ngưỡng đột biến của chính chuỗi (tính từ lịch sử trước mốc)
  được hạ về đúng ngưỡng.
- Lịch sử dùng để tính feature lúc dự báo cũng được hạ như vậy.
- Đánh giá luôn trên **thực tế gốc**. Dữ liệu lưu không đổi.

**Fold giữ lại (19/09–18/10/2026, 1 fold, không dùng để chọn):**

| ID | WAPE | Bias | Ngày thường | Ngày đột biến | Khối lượng lớn | Tổng 7 ngày (bias) | Tổng 30 ngày (bias) | Chuỗi tốt hơn / kém hơn E00 |
|---|---|---|---|---|---|---|---|---|
| E00 | 0,7983 | −9,6% | 0,788 | 0,845 | 0,714 | 0,527 (−11,9%) | 0,486 (−9,6%) | — |
| E03 | 0,7907 | −9,7% | 0,781 | 0,836 | 0,707 | 0,521 (−9,2%) | 0,479 (−9,7%) | 2.652 / 2.074 |
| E13 | 0,7627 | −16,0% | 0,738 | 0,876 | 0,677 | 0,529 (−18,3%) | 0,472 (−16,0%) | 2.906 / 1.983 |
| **E14** | **0,7603** | **−16,4%** | 0,736 | 0,870 | 0,675 | 0,525 (−18,0%) | 0,473 (−16,4%) | 2.967 / 1.922 |
| O0 | 0,8061 | −7,9% | 0,797 | 0,846 | 0,722 | 0,536 | 0,491 | (khác tập chuỗi) |
| O1 | 0,7959 | −8,8% | 0,788 | 0,832 | 0,711 | 0,516 | 0,476 | (khác tập chuỗi) |

**Kết luận:**
1. Cấu hình production đã gần tối ưu theo tham số. Đổi tham số thuần chỉ được tối đa khoảng 0,006–0,008 WAPE (63
   lá). `poisson` không dùng được. RECURSIVE kém xa DIRECT, khẳng định lựa chọn của 1.2.0.
2. Mức cải thiện lớn nhất đến từ **chặn đột biến khi huấn luyện**: −0,032 WAPE khi sàng lọc, −0,038 ở fold giữ lại.
   Ngày thường, nhóm khối lượng lớn và chuỗi ERRATIC đều tốt hơn; nhiều chuỗi tốt hơn là kém hơn.
3. Nhưng E14 **dự báo thiếu nhiều hơn**: tổng 30 ngày −16,4% so với −9,6% ở fold giữ lại, và kém hơn ở ngày đột biến.
   Ngày đột biến chiếm khoảng 17% nhu cầu ở các fold sàng lọc. Với việc đặt hàng, thiếu có hệ thống có thể gây hết hàng.
   **Không tự áp dụng**:
   - cần chủ hệ thống chọn giữa WAPE thấp hơn và bias âm hơn, và đặt tiêu chí bias;
   - đưa vào ứng dụng cần mã mới (tùy chọn huấn luyện, mặc định tắt), test và review.
4. Thứ trong tuần có ích: tắt thì kém hơn 0,017. Mã ISO cho kết quả giống hệt mã cũ.
5. Giờ mở bán: chưa đủ bằng chứng (mục 8). Bỏ giai đoạn 01/01–18/03 có chi phí nhỏ (fold giữ lại +0,008).
6. Nhóm gián đoạn: WAPE theo ngày > 1 với mọi phương pháp, vì WAPE theo ngày phạt sai ngày có đơn. Nên đánh giá bằng
   tổng kỳ; trên tổng 30 ngày, cách hiện tại tốt hơn baseline và Croston-SBA.
7. Không model nào được huấn luyện, promote hay đổi trong ứng dụng. Quality gate không đổi.

File kết quả: `scratchpad\p17\exp\screen_analysis.json`, `holdout_analysis.json`, `common_window.json`,
`screen\summary.jsonl`, `holdout\summary.jsonl`, `*.npz` theo (thí nghiệm, fold).

## 12. Quality gate và giữ model đang dùng

- Không đổi quality gate, ngưỡng hay chính sách promote. Không có model hay forecast production nào bị thay. Thí
  nghiệm không ghi model và không publish; bản sao chỉ được đọc trong lúc thí nghiệm.
- Test hiện có về bảo vệ model đang dùng và promote thủ công đạt trong lần chạy toàn bộ (mục 15).
- Ứng viên tốt hơn trong thí nghiệm **không** tự động trở thành cấu hình: đổi tham số là việc của chủ hệ thống trên
  trang Cấu hình, rồi huấn luyện, rồi promote thủ công.

## 13. Giao diện, Excel, số nguyên

- Kết quả dự báo (1.2.8): `forecast_qty` số nguyên ở bảng, tổng, biểu đồ, Excel định dạng 6, tiêu đề giải thích.
  Không đổi trong đợt này.
- **Lịch sử forecast & thực tế (đợt này):**
  - Bảng, tổng theo ngày, KPI, biểu đồ, sắp xếp và Excel dùng cùng số nguyên `qty.SQL`. Cho phép 0; không ép lên 1.
  - Sai lệch và WAPE của trang so số nguyên hiển thị với thực tế. Di chuột lên ô Forecast thấy giá trị mô hình đã lưu.
  - Định dạng Excel H3, vị trí cột không đổi.
  - Lý do: prompt yêu cầu số nguyên nhất quán giữa chi tiết, tổng, export và lịch sử. Báo cáo 1.2.8 đã nêu đây là
    quyết định cần chủ hệ thống, và prompt này là chỉ đạo đó.
  - Chỉ số chất lượng mô hình (backtest, quality gate, thẻ accuracy) vẫn dùng `yhat`. Muốn trang Lịch sử quay về `yhat`
    thì chỉ cần đổi một biểu thức (`FORECAST_QTY_SQL`).
- Thẻ backfill: xem trước, bảng tóm tắt, cảnh báo, nút chỉ bật khi khớp ngày, hộp xác nhận có số dòng. Link xem từ
  xa (proxy chỉ đọc) **không** hiện bản xem trước: `GET /api/sync/backfill/preview` chỉ dùng tại máy, proxy giữ nguyên
  nên khi deploy không cần sửa proxy.
- Hiệu năng:
  - Xem trước backfill là một lần đọc BigQuery như lần nạp, không tải dữ liệu lịch sử lên giao diện.
  - Truy vấn lịch sử chỉ thêm một biểu thức trên mỗi dòng.
  - Chỉ số theo nhóm tốn khoảng < 1 s mỗi fold.

## 14. Diễn tập migration và rollback

Bản sao mới của DB production lúc 22:38 (backup API, nguồn mở `mode=ro`, 2,7 s, 643 MB) → `scratchpad\p17\e`:

| Kiểm tra | Kết quả |
|---|---|
| `db.migrate()` đường khởi động thật: tự tạo backup `pre-migration-v6`, 6 → 7 | PASS, 68,7 s |
| Số dòng mọi bảng giống hệt (chỉ `schema_migrations` +1) | PASS |
| Giá trị cũ `demand_daily` (hash mọi cột cũ) giống hệt | PASS |
| `app_settings`, `training_runs`, `forecast_runs`, `settings_history`, `job_runs`, `sync_state` giống hệt (hash) | PASS: mapping và cấu hình model không mất |
| Hai cột mới đều NULL; trigger không đổi; `integrity_check` ok | PASS |
| Migrate lần 2: không có gì pending, không backup, không đổi gì (idempotent) | PASS |
| App 1.2.9 khởi động, 5 API GET trả 200; mapping hash vẫn `bc5fcb06327569fb`, validation vẫn hợp lệ | PASS |
| data-check | WARN `open_hours_window_ready` (1.355.000 dòng NOT_LOADED, đúng thiết kế); FAIL `accepted_model_files` chỉ vì bản sao chưa có file model (sau khi chép model: hết FAIL) |
| Mã 1.2.8 (`git archive 0da73b6`) mở DB schema 7 | **Từ chối**: "schema version 7 is newer than this app supports (6)" |
| Khôi phục backup `pre-migration-v6` (SHA-256 `0D3CA887…873C`) rồi chạy 1.2.8 | PASS: schema 6, hash dữ liệu bằng bản sao trước migration, không migration nào pending, app 1.2.8 trả 200, cấu hình model còn nguyên, data-check chỉ WARN có từ trước |

Kết luận rollback: sau khi deploy 1.2.9, quay về 1.2.8 = **khôi phục backup trước nâng cấp** (mất dữ liệu ghi sau thời
điểm đó). Câu lệnh đảo ngược trong 0007 chỉ dùng cho bản sao: model huấn luyện bằng 1.2.9 dùng `dow` 1–7, nên 1.2.8
sẽ đưa sai mã thứ (0–6) vào các model này.

## 15. Test

Mọi lệnh chạy trên working tree hiện tại, dữ liệu tạm (conftest), không đụng DB thật.

| # | Lệnh | Loại | Kết quả |
|---|---|---|---|
| 1 | `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` (00:51–01:02, chạy song song thí nghiệm) | unit + integration với fake BigQuery | **588 passed, 8 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning`, có từ trước). 8 test bỏ qua đều cần BigQuery thật (`DF_REAL_BQ=1`) |
| 2 | `DF_REAL_BQ=1 pytest tests/test_bq_real_semantics.py tests/test_v129_real_bq_open_hours.py tests/test_v121_d0_real_bq.py` | **BigQuery thật**, chỉ đọc, dữ liệu nhúng / dry run | **8 passed** |
| 3 | `DF_REAL_BQ=1 pytest tests/test_v121_d0.py` | integration | 17 passed |
| 4 | `cd frontend; npx vitest run` | unit (jsdom) | **22 file, 145/145** |
| 5 | `npm run typecheck` | — | exit 0 |
| 6 | `npm run build` | — | exit 0 (bundle 672 kB, gzip 204 kB) |
| 7 | Lint | — | **chưa cấu hình** |
| 8 | Kiểm tra line ending / ASCII trên 65 file thay đổi (`scratchpad\p16\eol_check.py`) | — | 0 vấn đề |
| 9 | Quét secret trên file thay đổi | — | 0 (chỉ trùng tên trường như `client_secret`) |

Test mới của đợt này:
- `test_v129_backfill_history_patterns.py`, 14 test:
  - nhóm nhu cầu, cờ đột biến không đổi dữ liệu, nhóm khối lượng;
  - `segments` khớp đúng các điểm của chỉ số gộp, được lưu và hiển thị;
  - lỗi trong `segments` không làm dừng backtest;
  - trang Lịch sử dùng số nguyên (cho phép 0, làm tròn nửa lên, KPI = công thức `ml/metrics.py`, API, Excel H3);
  - backfill:
    - từ chối khi không có bản xem trước, sai khoảng ngày, bản xem trước đã dùng, quá 6 giờ, thời gian ở tương lai, trùng dòng nguồn;
    - kiểm lại trong giao dịch ghi: bị job khác dùng, có D-1 chen vào, dữ liệu nguồn đổi;
    - backup trước khi ghi và backup giữ dữ liệu cũ; backup lỗi thì không ghi;
    - chỉ thay đúng khoảng; D-0, forecast, model không đổi; mốc D-1 không đổi;
  - đọc rỗng thì BLOCKED, cảnh báo hôm qua chưa xác nhận, file zip backup lỗi không để lại gì;
  - tắt công tắc thứ sau khi huấn luyện không làm lệch model đã có.
- `v129b.test.tsx`, 3 test: luồng xem trước → đọc lại, hủy xác nhận, bản xem trước lỗi, cảnh báo, ô Forecast số nguyên.

Test cũ được sửa kỳ vọng vì hành vi mới (không bỏ assertion nào):
- `test_v116.py`: backfill cần xem trước;
- `test_v125_forecast_history.py`, `test_v126_eod_backup_close.py`: số nguyên, định dạng H3;
- `test_v121_remote_proxy.py`: `GET /api/sync/backfill/preview` chỉ dùng tại máy, proxy giữ nguyên và vẫn chặn;
- fixture `v125-history.test.tsx`, `v126.test.tsx` thêm `forecast_qty`.

Lượt chạy đầu (23:31–23:48) có 1 lỗi đúng ở test proxy này: 587 passed, 1 failed. Đã sửa như trên rồi chạy lại toàn bộ.

Diễn tập trên **bản sao DB production** (không phải test tự động): migration, idempotency, rollback với mã 1.2.8, backfill
với BigQuery thật (mục 6, 14).

## 16. Ngân sách tài nguyên

**Đặt trước khi chạy** (`plan_screen.json`):
- tối đa 70 lượt huấn luyện fold và 5 giờ mỗi lần chạy;
- 8 / 12 luồng CPU; dừng nếu RAM trống < 0,5 GB;
- tạm dừng khi production có job đang chạy (`GET /api/jobs?status=RUNNING`, chỉ đọc);
- tạm dừng trong các khung 23:50–00:10, 02:55–03:25, 07:55–08:10;
- có file STOP để dừng tay.

| Hạng mục | Thực tế |
|---|---|
| Lượt huấn luyện fold | **66 / 70**: sàng lọc 47 + 8, thêm E14 4, fold giữ lại 6; cộng 1 lượt E08 lỗi |
| Thời gian | 23:03–01:12 (khoảng 2 giờ 9 phút, gồm 2 lần khởi động lại); mỗi fold 41–134 s (DIRECT 300 vòng khoảng 100 s) |
| RAM | Đỉnh working set khoảng 1,9 GB (đo bằng `Get-Process` lúc 23:18; đo trong script trả 0, là lỗi của script); RAM trống của máy 2,1–3,3 GB trong lúc chạy |
| BigQuery | Khoảng 6,7 GB quét, chỉ đọc: điều tra 5,4 GB, diễn tập backfill 1,27 GB; dry run trước, giới hạn 2–3 GiB mỗi truy vấn (backfill dùng giới hạn 20 GiB của ứng dụng) |
| Đĩa | Scratchpad `p17` 1,5 GB (2 bản sao DB, 2 backup tạm, kết quả). Ổ C: còn 42 GB |
| Lý do dừng | Đã chạy hết ma trận dự định (66/70); không chạm giới hạn ngân sách. E08 dừng vì LightGBM báo lỗi; chạy lại phần còn lại không có E08 |

**Sự cố của công cụ thí nghiệm** (đã sửa, ghi lại cho minh bạch):
1. Kiểm tra job production ban đầu gọi sai endpoint (`/api/jobs/active` cần `job_type`) và nhận lỗi. Script hiểu đó là
   "không rõ" nên tạm dừng 6 phút, không chạy gì; sau đó đã sửa.
2. Khung tạm dừng 23:50–00:10 vắt qua nửa đêm nên phép so sánh chuỗi không bao giờ khớp. Thí nghiệm **vẫn chạy** lúc
   EOD 23:55 và chốt 23:59 của production. Cả hai job production **SUCCEEDED** với thời gian bình thường: EOD 7 s
   (16:55:20–16:55:27 UTC), chốt 1 s. Đã sửa lỗi trong script; các khung không vắt qua nửa đêm vẫn hoạt động.

## 17. Quyết định nghiệp vụ còn mở

1. Giai đoạn thiếu giờ mở bán 01/01–18/03: phương án A, B hoặc C (mục 5).
2. Hai nhóm xung đột 26/08 (giờ mở bán theo item): chủ dữ liệu sửa nguồn ở mức SKU × FC, hoặc duyệt một quy tắc gộp (mục 4).
3. Có cho phép chọn dữ liệu theo tác vụ không: coi giờ mở bán không hợp lệ là "không biết" thay vì chặn cả lần huấn
   luyện (mục 7).
4. Cách hiểu dòng có giờ mở bán = 0 nhưng có đơn (722 dòng).
5. Đổi tham số mô hình theo kết quả thí nghiệm, nếu có ứng viên đạt (mục 11). Thêm tham số mới vào cấu hình cần duyệt.
6. Phương pháp riêng cho nhu cầu gián đoạn (mục 9, 11).
7. Ngưỡng chất lượng theo nhóm cho quality gate (chưa có).
8. `customer_id`: chủ dữ liệu thêm cột (dạng băm), xác nhận định nghĩa khách quay lại.
9. Trang Lịch sử dùng số nguyên cho sai lệch / WAPE (đã làm theo prompt; có thể đổi lại).
10. Nguyên nhân nhu cầu giảm dần từ tháng 7 (mở từ 16/10).

## 18. Thao tác cần chủ hệ thống cho phép (CHƯA thực hiện)

- Commit và push mã 1.2.9 (63 file).
- Đóng gói 1.2.9 (`scripts\release.ps1`), diễn tập cách ly, deploy bằng `deploy-upgrade.ps1` (có migration 0007), trong khung giờ được duyệt.
- Backfill D-1 production (sau deploy và sau các quyết định), có xem trước.
- Đổi `data_policy.window_start_date` (nếu chọn phương án A).
- Đổi tham số mô hình, huấn luyện production, promote.
- Mọi thay đổi lịch chạy, nguồn dữ liệu, quality gate.

## 19. Bước tiếp theo

**Mã nguồn (local):** (1) nếu chủ hệ thống chọn, đưa "huấn luyện chống đột biến" vào ứng dụng thành tùy chọn có test, mặc định tắt, kèm tiêu chí bias; (2) công cụ phục hồi một khoảng ngày từ backup (checklist #10); (3) lưu kết quả thí nghiệm vào ứng dụng thay vì scratchpad; (4) thêm tham số `min_data_in_leaf` / `feature_fraction` vào cấu hình nếu cần tuning tiếp; (5) dọn bản sao DB trong scratchpad sau khi chủ hệ thống xem báo cáo

**Quyết định nghiệp vụ:** mục 17, ưu tiên 1–3 vì chúng chặn huấn luyện BigQuery sau khi deploy 1.2.9.

**Chủ dữ liệu:** giờ mở bán ở hạt SKU × FC × ngày (hoặc xác nhận quy tắc); lịch sử giờ mở bán trước 19/03 nếu có;
trạng thái tồn kho / giới hạn bán **theo ngày** (không phải trạng thái hiện tại); mã khách hàng đã băm.

**Vận hành production (sau khi được duyệt):**
1. Commit.
2. Release và diễn tập.
3. Deploy 1.2.9.
4. Quyết định cửa sổ / quy tắc.
5. Xem trước rồi backfill theo tháng, ngoài giờ lịch chạy.
6. Huấn luyện thủ công, so với model đang dùng, rồi promote thủ công nếu đạt.
