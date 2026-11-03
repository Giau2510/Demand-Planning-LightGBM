# Sự cố D-1, lịch sử dữ liệu và backfill

Chốt thực tế, khôi phục dữ liệu, diễn tập nâng cấp / backfill, fix 7.1 và đồng bộ lịch sử 20–22/10/2026.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\demandforecast_actual_finalization_20261020.md` (MAIN) | 20/10/2026 | 21625 | `5AF812F709AF1E70DC3B5416FDEFD8D983177D5FCB77FA767A5214201817217A` |
| 2 | `reports\demandforecast_data_recovery_learning_readiness_20261020.md` (MAIN) | 20/10/2026 | 48869 | `94244AFB6AB1E29660D40D96091678096A27A84B972C9E61370FCA463B68509D` |
| 3 | `reports\demandforecast_upgrade_backfill_rehearsal_20261020.md` (MAIN) | 20/10/2026 | 34523 | `8FBA57C2A11CE72C9C14F53AFC06D2E5A2D8CCF3E06CF69E424CB41A06603754` |
| 4 | `reports\fix71-restore-d1-20261021\DATA_RECONCILIATION.md` (MAIN) | 21/10/2026 | 7989 | `19FDF3EEEFC53C35A1C5DD5F336F69EDC3EDBCE16553E68CC75B09E2F0E38EB8` |
| 5 | `reports\fix71-restore-d1-20261021\FINAL_REPORT.md` (MAIN) | 21/10/2026 | 14615 | `02C4B5B56CC3E91C9E9E416527031CBEE26829316EC101C4EDF64E0C2AFC885B` |
| 6 | `reports\fix71-restore-d1-20261021\RESUME_CHECKPOINT.md` (MAIN) | 21/10/2026 | 4230 | `3A690DEAB1BC4B65BEAF24A221F8E34D80ED81E7F0710EC3F65EC2FF84B0F89D` |
| 7 | `reports\fix71-restore-d1-20261021\TEST_RESULTS.md` (MAIN) | 21/10/2026 | 8408 | `3613560F2D019730765E2982133A45AD6FF37FAFCDDDD6EDE7198163F259BCE0` |
| 8 | `reports\history-sync-20261022\FINAL_REPORT.md` (MAIN) | 22/10/2026 | 18880 | `E158D89F7982674786C855F3054AA491A7399D7598FBC88EF719E302A70BB30C` |
| 9 | `reports\history-sync-20261022\TEST_RESULTS.md` (MAIN) | 22/10/2026 | 8585 | `2CE66B05240505E79D469F17E70F89E59839A4C2793F39D936B33D779F290B68` |

## 1. Demand Forecasting – Chốt (đóng băng) thực tế trên màn hình "Lịch sử Forecast & Thực tế" (đợt 7, 20/10/2026)

Nguồn: `reports\demandforecast_actual_finalization_20261020.md` (worktree MAIN).

| | |
|---|---|
| Thời gian | 20/10/2026, 19:51 – 20:40 (giờ Việt Nam) |
| Yêu cầu | "FIX IMMUTABLE ACTUAL SNAPSHOTS IN FORECAST HISTORY DASHBOARD + CONTINUE INDEPENDENT DEMAND FORECASTING WORK" |
| Kết quả việc chính | **Đã sửa trong mã nguồn và kiểm tra ở local**: unit test, tích hợp trên DB tạm, migration và chốt thật trên bản sao DB production. **Chưa commit, chưa đóng gói, chưa triển khai.** |
| Trạng thái phát hành 1.2.9 | **`BLOCKED_BUSINESS_RULE`**: 6 khóa `MULTI_ITEM`; 931 khóa giờ = 0 đang chờ bạn xem; chưa có quyết định commit / phát hành. Không coi là sẵn sàng phát hành chỉ vì test đạt. |
| Production | **Không bị thay đổi.** Chỉ gọi GET (19:32, 20:30, 20:33): bản 1.2.8, schema 6, `storage.json` `8D79DBDD…E047`, cùng model và cấu hình, không có job, không có audit mới. |
| Người đọc | Chủ hệ thống và người duyệt nghiệp vụ |

### 1. Nguyên nhân màn hình mãi "Thực tế tạm tính"

Có ba lỗi chồng nhau, tất cả nằm trong `backend/app/forecast_history.py`.

1. **Điều kiện "Đã hoàn tất" không bao giờ thỏa trên production.**
   - Hàm `_source_context` chỉ gọi một ngày đã nạp D-1 là `COMPLETE` khi có `audit_log` `D1_SYNC` với `mode = SIGNAL`.
   - Chế độ `SIGNAL` chỉ có khi cấu hình bảng tín hiệu hoàn tất (`bigquery.completion_table`), mà production không có.
   - Mọi lần D-1 của production đều chạy `FALLBACK_TIME_VERIFIED`: sau giờ dự phòng, kiểm tra số dòng của ngày ≥ tỷ lệ × trung bình 7 ngày. Đã kiểm trên bản sao: 4/4 lần nạp đều ở chế độ này.
   - Vì vậy mọi ngày đã qua mãi là "Tạm tính" (`D1_NO_COMPLETION_SIGNAL`). Từ khi bật chốt 23:59 (18/10 19:19), các ngày đó thành "Đã chốt – cần xác minh".
   - Không có bước nào biến "một lần D-1 thành công" thành "đã hoàn tất".
2. **Con số không bao giờ được cố định.** Thực tế luôn được đọc lại từ `demand_daily`, bảng mà mỗi lần D-1 xóa và ghi lại theo cửa sổ (3 ngày lùi, nạp lại toàn bộ, backfill). Một ngày cũ âm thầm đổi số khi nguồn sửa lịch sử. Bản chốt 23:59 chỉ ghi vết các thay đổi, màn hình vẫn hiện số sống.
3. **KPI trộn trạng thái.** Tổng thực tế, sai lệch và WAPE tính trên mọi dòng có thực tế (tạm tính trong ngày, đã chốt 23:59…), rồi chỉ gắn một nhãn chung.

**Bằng chứng trên bản sao DB production (20:19).** Trước khi sửa, 18/10 và 19/10 là "Đã chốt – cần xác minh", 20/10 tạm tính, KPI không có thực tế đã hoàn tất. Sau khi sửa, 18/10 và 19/10 là "Đã hoàn tất" với số đóng băng, còn 20/10 vẫn tạm tính (mục 5).

### 2. File đã sửa

So với checkpoint trước khi sửa, có 24 file nguồn đổi (danh sách trong manifest của checkpoint cuối).

| File | Mục đích |
|---|---|
| `backend/app/migrations/0009_actual_finalization.sql` (mới) | 2 bảng `actual_finals` / `actual_final_values` + 10 trigger bất biến; migration không ghi dòng nào |
| `backend/app/actual_final.py` (mới) | Quy tắc chốt: lập kế hoạch chỉ đọc, chốt từng ngày trong transaction riêng, ghi `BLOCKED` kèm lý do, thử lại; chạy thử trên file DB; tóm tắt cho màn hình |
| `backend/app/sync.py` | Sau mỗi lần D-1 thành công (sau commit): `actual_final.finalize_quietly(...)`, không bao giờ làm D-1 thất bại |
| `backend/app/forecast_history.py` | Ngày đã chốt hiện `COMPLETE` với số của bản đóng băng (`FINAL`); ngày chưa chốt không bao giờ `COMPLETE`. KPI chính chỉ trên dòng đã chốt; nhóm `provisional` / `closed` riêng; `coverage`, `n_zero_absent`; Excel H4 |
| `backend/app/api/history_routes.py` | `overview.finalization` (số ngày đã chốt / bị chặn, ngày chốt mới nhất) |
| `backend/app/data_checks.py` | Kiểm tra `actual_final_sealed`, `actual_final_protection_triggers` |
| `backend/app/cli.py` | `python -m app.cli actual-finalize` (chạy thử chỉ đọc, `--db`; `--apply` để chốt) |
| `backend/app/export_i18n.py` | Nhãn Excel (vi/en) của KPI đã chốt và các nhóm riêng |
| `frontend/src/pages/ForecastHistory.tsx`, `frontend/src/i18n.tsx` | Thẻ KPI đã chốt, dòng "Cơ sở so sánh", thẻ "Thực tế chưa chốt", trạng thái "Chưa có actual đã chốt", quy tắc mới (vi/en) |
| `backend/tests/test_v129g_actual_final.py` (mới, 13 test); `frontend/src/v129g-final.test.tsx` (mới, 3 test) | Test hồi quy (mục 6) |
| Test cũ cập nhật: `test_v125_forecast_history.py`, `test_v126_eod_backup_close.py`, `test_v126_retention_defaults.py`, `test_v129_weekday_open_hours.py`, `test_v129c_window_spike_customer.py`, `test_v129_backfill_history_patterns.py`, `v125-history.test.tsx`, `v126.test.tsx` | Theo quy tắc mới. "Đã hoàn tất" chỉ khi đã chốt; KPI tạm tính ở nhóm riêng; schema 9; Excel H4. Không bỏ assertion nào về số hay công thức; các assertion được chuyển sang đúng nhóm. |
| `docs/02_kien_truc_du_lieu/LICH-SU-FORECAST.md` (mục 3, 4, 6, 7, 8 và mục 15 mới), `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `CHANGELOG.md`, `docs/03_van_hanh/CHECKPOINT.md` | Tài liệu |

### 3. Schema, migration, dữ liệu cũ

- **Migration 0009 chỉ thêm, schema 8 → 9.** Hai bảng và 10 trigger; không đổi bảng nào khác; không gán trạng thái cho dòng cũ.
- **Thử trên bản sao DB production** (sao chép bằng SQLite backup API, nguồn mở `mode=ro`, môi trường cô lập, không gọi BigQuery):
  - **Migration:** 6 → 9 (0007, 0008, 0009) mất 28,6 giây, kèm bản sao lưu `pre-migration-v6`. Hai bảng mới rỗng. `demand_daily` chỉ thêm cột NULL của 0007 / 0008, các bảng khác giữ nguyên. `data-check` không có FAIL; còn 2 WARN có từ trước (giờ mở bán chưa nạp, 1 `forecast_series_meta`).
  - **Chạy thử chốt trước migration:** 292/292 ngày (01/01–19/10) truy được về một lần D-1 đã xác minh; 0 ngày bị chặn.
    - 285 ngày đến từ lần nạp lại toàn bộ `JOB-20261017125803-0ED367` (17/10 20:00 giờ VN).
    - 7 ngày (13/10–19/10) đến từ các lần nạp tăng dần.
    - Các lần nạp 1.2.8 không có `load_id`; provenance là `synced_at` + `job_id`.
  - **Chốt thật trên bản sao:** 292 ngày, 1.358.317 dòng, 42.023.217 đơn vị.
    - Thời gian: khoảng 38 giây ghi, cộng khoảng 35 giây lập kế hoạch ở lần đầu (đo trên bản sao e9).
    - DB tăng khoảng 81 MB.
    - 100% dòng đóng băng bằng `demand_daily` lúc chốt.
    - Lần chạy lại không ghi gì (0,3 giây).
    - `data-check` của hai kiểm tra mới đều OK.
- **Dữ liệu cũ.** Không ngày nào được coi là chốt chỉ vì đã qua. Ngày cũ chỉ được chốt khi các dòng của nó truy được về đúng một lần D-1 đã xác minh; không truy được thì `BLOCKED` kèm lý do, và ngày đó giữ số sống với nhãn tạm tính.
- **Hệ quả cần quyết định khi phát hành.** Ngày cũ sẽ được chốt theo số của lần nạp đã xác minh gần nhất (với production: bản nạp lại 17/10 và các lần sau). Nguồn đã sửa lịch sử khoảng −0,03% từ đó (đợt 5). Nếu muốn ngày cũ khớp nguồn mới nhất, backfill có preview phải chạy **trước** lần chốt đầu tiên sau nâng cấp.
- **Rollback.** Bản 1.2.8 từ chối schema 9, nên rollback = khôi phục bản sao lưu trước nâng cấp (như 0004–0008).

### 4. Quy tắc chốt và tính idempotent

- **Ngày được chốt.** Ngày nghiệp vụ Việt Nam T (= `order_date` = `created_date` của nguồn), luôn trước hôm nay.
  - Đã kiểm trong code: D-1 chạy ngày 20/10 nạp tới `today_vn() − 1` = 19/10, nên 19/10 được chốt ngay sau lần đó.
  - Không bao giờ chốt hôm nay hay ngày tương lai.
- **Điều kiện, tất cả phải đúng:**
  - mọi dòng của T có cùng một `loaded_at`;
  - có đúng một `D1_SYNC` của scope với `synced_at` bằng giá trị đó. Lần nạp ghi audit trong cùng transaction, nên audit có nghĩa là lần nạp đã commit; D-1 thất bại không commit gì.
  - chế độ là `SIGNAL`, `FALLBACK_TIME_VERIFIED` hoặc `BACKFILL` (đúng quy tắc "nguồn đủ dữ liệu" sẵn có);
  - cửa sổ của lần nạp bao trùm T;
  - ngày Việt Nam của lần nạp sau T;
  - mọi dòng có SKU, FC và số lượng ≥ 0.
- **Không đạt.** Ghi `BLOCKED` với một trong các lý do: `NO_VERIFIED_D1_LOAD`, `MIXED_LOADS`, `LOAD_WINDOW_DOES_NOT_COVER_DAY`, `LOADED_BEFORE_DAY_ENDED`, `D1_MODE_NOT_ELIGIBLE`, `AMBIGUOUS_D1_LOAD`, `INVALID_ROWS`. Một lần nạp hợp lệ sau đó có thể chuyển `BLOCKED` → `FINALIZED`, không bao giờ ngược lại.
- **Nguyên tử.** Mỗi ngày một transaction `BEGIN IMMEDIATE`: đầu mục, toàn bộ SKU × FC, provenance (load id, job, `synced_at`, chế độ, cửa sổ, watermark, mapping hash, preview), số dòng, tổng, sha256. Sau đó kiểm lại với chính nó và với `demand_daily`, rồi mới niêm phong. Trigger cũng từ chối niêm phong khi số dòng hoặc tổng lệch. Lỗi thì cả ngày rollback.
- **Bất biến.** Sau khi niêm phong:
  - không cột nào đổi; không xóa, không `INSERT OR REPLACE`; không thêm, sửa, xóa giá trị;
  - D-1 sau đó báo số khác, bỏ một SKU × FC, nguồn sửa lịch sử, nạp lại hay huấn luyện lại đều không đổi bản đóng băng (có test);
  - sửa một ngày đã chốt phải là một quy trình riêng có kiểm soát và audit. Chưa làm, theo yêu cầu.
- **Idempotent và thử lại.**
  - Ngày đã chốt không bao giờ được xét lại; chạy lại không ghi gì.
  - Ngày `BLOCKED` chỉ ghi lại khi lý do hoặc lần nạp đổi.
  - Ngày lỗi rollback riêng, có alert ERROR `ACTUAL_FINALIZE_FAILED`, và được thử lại ở lần D-1 kế tiếp hoặc bằng `actual-finalize --apply`. Các ngày khác vẫn chốt bình thường.
- **Phạm vi và độc lập.**
  - Chỉ nguồn BIGQUERY. DEMO / Excel không bao giờ được chốt, màn hình ghi rõ.
  - Không ghi `demand_daily`, forecast, lịch sử D+1 hay bản chốt 23:59. Bản chốt 23:59 giữ quy tắc 1.2.6.

### 5. Màn hình

- **Thẻ chính:**
  - "Tổng forecast đã lưu": ý nghĩa giữ nguyên.
  - "Thực tế đã hoàn tất", "Sai lệch (đã chốt)", "WAPE (đã chốt)" kèm bias: chỉ tính trên dòng đã chốt. Công thức không đổi (`ml/metrics.py`); chỉ tập dòng đổi.
  - Không có dòng đã chốt: ghi "Chưa có actual đã chốt", không hiện số tạm tính như số chính thức.
- **Cơ sở so sánh:** số dòng và số ngày đã hoàn tất, tạm tính, đã chốt cuối ngày, chưa có thực tế (không tính 0); số dòng đã hoàn tất = 0 vì SKU × FC không có đơn.
- **Thẻ "Thực tế chưa chốt — xem riêng, không phải chất lượng mô hình":** nhóm tạm tính và nhóm đã chốt cuối ngày, mỗi nhóm có số dòng / ngày, tổng, forecast, sai lệch, WAPE riêng.
- **Biểu đồ:** điểm đã chốt là điểm đặc; điểm tạm tính / đã chốt cuối ngày là điểm rỗng, chú thích "Thực tế chưa chốt".
- **Bảng:** trạng thái theo từng dòng. Ô thực tế của ngày đã chốt ghi "đã chốt lúc …".
- **Thẻ quy tắc:** quy tắc chốt, số ngày đã chốt, ngày chốt mới nhất, số ngày chưa chốt được.
- **Giữ nguyên:** bộ lọc (khoảng ngày, FC, tìm SKU / tên, trạng thái thực tế, nguồn forecast), chuyển ngôn ngữ vi/en. Excel định dạng **H4**: KPI là của dòng đã chốt; các dòng mới nối vào cuối sheet Thông tin.
- **Bản sao DB production (20:19), KPI 30 ngày mặc định:**

| | Trước khi chốt | Sau khi chốt |
|---|---|---|
| 18/10, 19/10 | Đã chốt – cần xác minh | **Đã hoàn tất** (57.510 và 90.760 đơn vị, đóng băng) |
| 20/10 (hôm nay) | Tạm tính | Tạm tính (nhóm riêng) |
| KPI chính | Chưa có actual đã chốt | Thực tế 148.270; WAPE 73,0%; bias +14,8%; 34.252 dòng / 2 ngày |
| Nhóm tạm tính | – | 58.299 (lũy kế trong ngày 20/10); WAPE 109,0%, chỉ tham khảo |

### 6. Test đã chạy

| Loại | Kết quả |
|---|---|
| Backend toàn bộ, lượt cuối (unit / tích hợp trên DB tạm, FakeBQ) | **647 passed / 10 skipped / 0 failed**, 305 giây, xong 20:36 (10 skipped = test BigQuery thật cần bật riêng) |
| Backend toàn bộ, lượt trước (20:24–20:30, trước khi thêm test thứ 13) | 646 passed / 10 skipped / 0 failed |
| Test mới `test_v129g_actual_final.py` | 13 passed |
| Các bộ liên quan (lịch sử, chốt 23:59, retention, open hours, backfill, customer, 1.2.8) | 188 passed |
| Frontend `npm test` | 24 file, **152 passed**, 0 failed |
| Frontend `typecheck` / `build` | exit 0 / exit 0 (`frontend/dist`, git-ignored) |
| Migration + chốt trên bản sao DB production | Đạt (mục 3) |
| BigQuery thật (10 test opt-in) | Không chạy: đợt này không đổi SQL hay đọc BigQuery của ứng dụng |
| Lint | Chưa được cấu hình |

Test mới phủ 17 yêu cầu:

| # | Yêu cầu | Đã phủ bằng |
|---|---|---|
| 1, 4, 5, 6, 10 | Chốt ngày hôm qua; D-1 sau với số khác hoặc bỏ một khóa không đổi bản chốt; không nhân bản; forecast và lịch sử D+1 không đổi | D-1 thật qua FakeBQ |
| 2 | D-1 lỗi không chốt gì | D-1 thật qua FakeBQ |
| 3, 17 | Lần nạp không xác minh được, dữ liệu trộn lần nạp, cửa sổ không bao trùm, nạp trước khi ngày kết thúc, chế độ không hợp lệ: đều bị chặn, kèm lý do | DB tạm |
| 7, 8 | Lỗi giữa chừng rollback đúng ngày đó rồi thử lại được; trigger chặn mọi thay đổi và mọi niêm phong thiếu | DB tạm |
| 9 | Hôm nay luôn tạm tính | DB tạm |
| 11–14 | KPI chỉ trên dòng đã chốt; nhóm tạm tính tách riêng; WAPE / bias khớp `ml/metrics.py`; thiếu thực tế không thành 0; `SUM_ACTUAL_ZERO` | DB tạm |
| 15 | Ranh giới nửa đêm theo giờ Việt Nam | DB tạm |
| 16 | Bộ lọc, API, Excel vi/en, GET không ghi gì; chú thích, biểu đồ, hai ngôn ngữ | DB tạm + test frontend |
| Khác | DEMO / Excel không chốt; chốt 23:59 giữ quy tắc; hook D-1 không làm hỏng lần nạp; `MULTI_ITEM` vẫn chặn training nhưng không chặn việc chốt số lượng | DB tạm |

### 7. Việc phụ độc lập

| Việc | Kết quả |
|---|---|
| `MULTI_ITEM` | Không chọn quy tắc. Đã kiểm đường code: 6 khóa vẫn chặn training (`OPEN_HOURS_INVALID`) và không lan sang việc chốt số lượng (có test). Các phương án R0–R5 và tác động: báo cáo đợt 6, mục 5. **`BLOCKED_BUSINESS_RULE`** |
| Ý nghĩa và hạt của `fact_product_sku_status` (đọc 1,86 GB) | Đã xác minh hạt: đúng 1 dòng / item × FC × ngày (13.704.111 = số khóa phân biệt), đủ 202/202 ngày 01/04–19/10, FC chỉ BD/HN, `web_status` ∈ {NORMAL, LIMIT, OUT_OF_STOCK}, `is_active`, `product_afs` ∈ {AVAILABLE, UNAVAILABLE}. Bảng có cả seller `EXTERNAL` (64%), trong khi nguồn D-1 chỉ có `INTERNAL`. **Ý nghĩa nghiệp vụ và giờ chụp vẫn chưa được chủ dữ liệu xác nhận**: không đưa vào model |
| Chuỗi giảm mạnh × bảng trạng thái (chỉ mô tả, không kết luận nhân quả) | Tỷ lệ item-ngày `OUT_OF_STOCK`, tháng 4–6 → 01/09–19/10: giảm > 50% (4.741 chuỗi, 69% mức giảm ròng) 7,6% → 60,2% (3.608 chuỗi tăng ≥ 20 điểm); ngừng bán 29,2% → 82,8%; giảm 0–50% 5,7% → 27,3%; ổn định / tăng 10,1% → 24,2%. Hết hàng tăng ở mọi nhóm, mạnh nhất ở nhóm giảm. Chưa tách được chiều nhân quả: hết hàng làm giảm bán, hay bán giảm nên ít nhập |
| Lần làm mới nguồn kế tiếp | **`NOT_VERIFIED`**: lúc 20:40 bảng vẫn là bản 08:05:30 UTC, chưa làm mới. Kiểm lại sau lần làm mới kế tiếp (dự kiến khoảng 07:10 ngày 21/10): `p21/bq_meta.py` (miễn phí), `p20/bq_oh.py` (khoảng 6 GB) |
| Đơn 71.834 ngày 28/08 (`MEDX.9DCBBCV8`, BD) | Giữ nguyên kết luận đã kiểm: giờ mở bán 19,25, không thuộc 931 khóa. Không có thêm bằng chứng đọc được (nguồn không có khách hàng / kênh); vẫn là câu hỏi nghiệp vụ |
| Thí nghiệm offline | Không chạy: các cấu hình có tác động lớn cần xác nhận nghiệp vụ trước (kế hoạch `p21/plan_next.json`). D4 (tweedie) độc lập nhưng không cần cho đợt này |
| Rà soát code | Chốt actual: idempotent, từng ngày nguyên tử, khôi phục bằng chạy lại, alert khi lỗi, `data-check`, hook D-1 không làm hỏng lần nạp. Đã tối ưu bước lập kế hoạch: 8,9 giây → 0,3 giây khi lịch sử đã chốt |

BigQuery đợt này: chỉ đọc, có dry run và mức trần; 1,86 GB nội dung, metadata miễn phí; không ghi gì.

### 8. Quyết định nghiệp vụ còn mở

1. Quy tắc gộp giờ cho 6 khóa `MULTI_ITEM`. Đây vẫn là thứ chặn training của 1.2.9.
2. Kết quả bạn xem 931 khóa giờ = 0 có đơn (Excel đợt 6). Tôi không tự đổi gì.
3. Thứ tự khi phát hành:
   - (a) backfill có preview → chốt lần đầu: ngày cũ khớp nguồn mới nhất;
   - (b) chốt lần đầu ngay: ngày cũ khớp lần nạp đã xác minh gần nhất.
4. Ý nghĩa, giờ chụp và cách ánh xạ của `fact_product_sku_status`, trước khi dùng cho chẩn đoán hay feature.
5. Có cần một quy trình sửa thực tế đã chốt (có kiểm soát, có audit) không. Hiện không có, đúng yêu cầu.
6. Đơn 71.834 ngày 28/08 là nhu cầu thường hay đơn đặc biệt; phạm vi seller của nguồn D-1 (chỉ `INTERNAL`).

### 9. Checkpoint

- Trước khi sửa: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129g-before.zip`, SHA-256 `02BC4A772AADD2FF9CF0A2F976F75910C7609DFE337E4BCBC0CBA403741046BC`. Gồm 80 file chưa commit + patch; đã kiểm CRC, danh sách, hash từng file, hash bằng PowerShell.
- Cuối đợt: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129g-worktree.zip`, SHA-256 `753FC2C265DB8EA3ED98919641C6FCF5DABA97B4108606E49ADE4553B4A0D48D`, 1.301.625 byte, 107 mục: 86 file nguồn + patch, báo cáo, 18 file scratchpad p22; không gồm bản sao DB f1 / f2. Đã kiểm CRC, danh sách = manifest, hash từng file, hash bằng PowerShell. So với checkpoint trước: đúng 24 file nguồn ở mục 2. Bản báo cáo trong zip còn trống dòng này và số file đổi; hai chỗ đó được điền sau khi tạo zip.

### 10. Git và an toàn

- Nhánh `main`, HEAD `0da73b6`, 86 file chưa commit. Mọi thay đổi trước đó được giữ nguyên.
- Đã kiểm diff: chỉ các file ở mục 2 đổi so với checkpoint trước khi sửa.
- **Không commit, không push, không deploy, không đóng gói.** Không huấn luyện, promote hay backfill production; không chạy D-0 / D-1 / EOD; không đổi lịch hay cấu hình production.
- Không ghi gì vào production hay BigQuery. Không xóa log, checkpoint, scratchpad hay báo cáo nào.
- Bản sao DB dùng thử nằm trong scratchpad:
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p22\f2` (dùng để đo);
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p22\f1` (lần chạy đầu dừng vì lỗi script đo, giữ nguyên, không dùng cho số liệu).
- Price vẫn ON, `customer_id` vẫn OFF; không bật feature nào.

### 11. Blocker phát hành và việc tiếp theo

| Blocker | Ai |
|---|---|
| Quy tắc `MULTI_ITEM` (training BIGQUERY của 1.2.9 bị chặn tới khi có quy tắc) | Bạn |
| Thứ tự backfill / chốt lần đầu (mục 8.3) | Bạn |
| Cho phép commit → `scripts\release.ps1` (QA + đóng gói) → diễn tập nâng cấp 6 → 9 trên cài đặt cô lập, kèm rollback bằng khôi phục bản sao lưu | Bạn cho phép, tôi thực hiện |
| Triển khai trong khung giờ được duyệt (`deploy-upgrade -CheckOnly` trước) | Bạn cho phép |

**Việc kế tiếp cụ thể:** bạn quyết định quy tắc `MULTI_ITEM` và thứ tự backfill / chốt, rồi cho phép commit đợt 1.2.9. Sau đó tôi chạy `release.ps1`, diễn tập nâng cấp trên bản sao, và đưa kế hoạch triển khai để bạn duyệt. Màn hình chỉ có thực tế "Đã hoàn tất" trên production sau khi 1.2.9 được triển khai và có một lần D-1 thành công (hoặc chạy `actual-finalize --apply`).

## 2. Demand Forecasting — Khôi phục dữ liệu, kiểm tra giờ mở bán và điều kiện học của model (20/10/2026)

Nguồn: `reports\demandforecast_data_recovery_learning_readiness_20261020.md` (worktree MAIN).

**Đối tượng:** chủ hệ thống và người duyệt nghiệp vụ.
**Phạm vi:** đợt 5 của mã nguồn 1.2.9 (chưa phát hành).
**Thời gian thực hiện:** 20/10/2026, 15:15–17:15 (giờ Việt Nam).
**Trạng thái kết luận:** `BLOCKED_BUSINESS_RULE`. Chỉ 6 khóa ngày × SKU × FC (156 đơn vị) đang chờ quy tắc gộp giờ mở bán. Mọi kiểm tra dữ liệu khác đều đạt.

### 1. Tóm tắt

- **Giờ mở bán đã được sửa ở nguồn và đã xác minh.** Bản làm mới lúc 15:05:19 ngày 20/10 có giá trị `total_open_hours` trên **mọi dòng** từ 01/01 tới 19/10/2026. Ở bản 07:10 cùng ngày, 2.946.849 dòng của 01/01–19/03 còn thiếu.
- **Ở hạt ngày × SKU × FC:** 1.357.883 / 1.357.889 khóa có trạng thái `OK`. 6 khóa là `MULTI_ITEM`: nhiều item của cùng SKU có giờ khác nhau. Không còn khóa thiếu, mâu thuẫn hay ngoài miền 0–24.
- **Giả định "`.2` = miền HN" đã được rút lại** ở code, tài liệu và workbook bổ sung. Code chưa bao giờ đọc hậu tố; nay có test chặn việc này.
- **Đơn `SOBD38271068`:** không còn căn cứ để coi là sai. Đơn có 11 dòng hàng của 11 SKU khác nhau, không dòng nào bị đếm lặp, và tổng số lượng khớp với dữ liệu đã nạp.
- **Grain và tổng hợp đúng:** bản sao nạp bằng chính code D-1 của 1.2.9 khớp nguồn tuyệt đối trên 292/292 ngày (số khóa, số lượng, trạng thái giờ). Nguồn không có dòng trùng hoàn toàn.
- **Dataset đã xác minh:** bản sao `e9`, cửa sổ 01/01–19/10. Identity nội dung `2e11fa4d…0e80`; identity kèm giờ mở bán `f86669c2…f4b1`.
- **Thí nghiệm offline:** 6 cấu hình ghi trước (C1–C6) so với baseline B0 trên 5 fold:
  - **Không cấu hình nào đạt `IMPROVES`.**
  - C2 (cửa sổ 19/03) và C4 (trọng số thời gian) tốt hơn ở sàng lọc nhưng không xác nhận ở holdout.
  - C1 (tắt giờ mở bán) và C6 là trade-off; C3 và C5 không cải thiện.
  - Dự báo dư ngày thường của B0 là 48,5% (holdout 40,7%), tái lập kết quả cũ.
  - Nguyên nhân vẫn là ngày không có đơn và mức nhu cầu giảm.
  - Giữ baseline, không promote.
- **Production:** vẫn 1.2.8, `storage.json` không đổi. Tôi không deploy, promote, commit, push, train hay backfill production, và không đổi lịch chạy.
- Lúc 15:24, **người dùng** đã promote ứng viên `TRN-20261020054540-D7EEF6` từ ứng dụng, nên model đang dùng đã đổi (mục 15).

### 2. Production trước / sau

| Mục | Trước (15:15) | Sau (17:15) |
|---|---|---|
| Phiên bản (`/api/health`, `current.txt`) | 1.2.8 | 1.2.8 (không đổi) |
| `storage.json` SHA-256 | `8D79DBDD…E047` | `8D79DBDD…E047` (không đổi) |
| Job đang chạy | không | không |
| Model đang dùng | `TRN-20261019043033-A761C1` / forecast `FCR-20261019060524-9DE420` | `TRN-20261020054540-D7EEF6` / forecast `FCR-20261020082402-A42C91`: **người dùng promote lúc 15:24 từ ứng dụng** (mục 15) |
| Job và thao tác trong lúc thực hiện | – | 15:24 promote (người dùng); 16:00 D-0 theo lịch, SUCCEEDED (harness tự dừng chờ) |
| Git | HEAD `0da73b6`, 77 file chưa commit | HEAD `0da73b6`, 79 file chưa commit, không commit / push |

**Production 1.2.8 không dùng `total_open_hours`:**
- `features.py` ở HEAD không nhắc tới cột này.
- Schema dừng ở 6.
- D-1 chỉ ánh xạ cột để kiểm tra.

Vì vậy bản sửa nguồn chưa ảnh hưởng tới model đang chạy. Giờ mở bán chỉ là đầu vào trong mã nguồn 1.2.9, chưa phát hành.

### 3. Đính chính về `.1`, `.2`, `.3`

**Quy tắc chủ hệ thống xác nhận:**
- Hậu tố là **thứ tự SKU được mở bán ở các miền**, không phải mã miền.
- Không suy ra miền, FC hay giờ mở bán từ hậu tố.
- Grain dự báo là SKU × `fc_code` × ngày.

| Nơi đã ghi | Câu cũ | Xử lý |
|---|---|---|
| `backend/app/data/open_hours.py` (docstring) | "an item belongs to a sales region … another region's item" | Đã sửa: hậu tố là thứ tự mở bán, không phải mã miền |
| `backend/app/ml/feature_registry.py` (chữ hiển thị trên giao diện) | "listing theo miền bán … hợp lệ ở nguồn" | Đã sửa: "các item_code của SKU có giờ khác nhau … hậu tố .1/.2 là thứ tự mở bán, không phải mã miền" |
| `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `docs/02_kien_truc_du_lieu/BIGQUERY.md` (§6, §11c), `docs/03_van_hanh/CHECKPOINT.md`, `CHANGELOG.md` | "sales-region listing", "`.1` ở BD, `.2` ở HN", "item vùng HN", "khác biệt giữa miền bán (hợp lệ)" | Đã sửa; §11c có dòng đính chính |
| `reports/demandforecast_dq_spike_customer_20261020.md` (đợt 3, mục A, bảng cột) | "listing theo miền bán", "`.1` ở BD, `.2` ở HN", "item vùng HN", "khác biệt hợp lệ giữa miền bán" | **Rút lại** bằng báo cáo này; file cũ giữ nguyên |
| `reports/demandforecast_multi_item_overforecast_20261020.md` (đợt 4, mục 0, C, G) | "Giả thuyết `.2` = listing miền HN", câu hỏi xác nhận `.2` = HN | **Rút lại**; câu hỏi không còn cần trả lời |
| `reports/demandforecast_multi_item_review_20261020.xlsx` (sheet Summary) | "Item .2 là listing của miền phía Bắc (HN)…" | **Rút lại** bằng workbook v2; file gốc giữ nguyên (SHA `0C4C7ADA…DEADA` không đổi) |

**Những gì vẫn đúng (dữ kiện):**
- Giờ mở bán đo theo **item × ngày**: 108 item-ngày xuất hiện ở hai FC trong cùng ngày, giờ luôn bằng nhau; 0 item × FC × ngày có hai giá trị.
- Số dòng của mỗi item theo cột `fc_code`, ví dụ "item `.2` có phần lớn dòng ở FC HN". Đây là dữ kiện của cột `fc_code`, không nói lên miền của item.

**Kiểm tra code:** không đoạn code nào tách, parse hay so sánh hậu tố. Câu D-1 chỉ **đếm** số `item_code` khác nhau. Test mới khóa điều này (mục 8).

### 4. Kiểm tra lại đơn `SOBD38271068`

Kiểm tra theo khóa nguồn thực tế (bản làm mới 15:05):

| Kiểm tra | Kết quả |
|---|---|
| Dòng của đơn | 11 dòng, ngày 26/08, FC BD, trạng thái `COMPLETED` |
| SKU | 11 SKU khác nhau, **mỗi SKU 1 dòng** (item `.2` × 10, `.3` × 1) |
| Trùng hoàn toàn (17 cột) | 0: 11 dấu vân tay dòng khác nhau |
| Lặp khóa nghiệp vụ (so_code, sku_code, item_code, fc_code, ngày) | 0 trong đơn |
| Tổng hợp về ngày × SKU × FC | 11/11 khóa: số lượng và số đơn từ nguồn bằng dữ liệu đã nạp trên bản sao (ví dụ `MEDX.COU-STR-001`: 42 đơn vị / 8 đơn; `MEDX.GGHAXHR2`: 139 / 27) |
| Giờ mở bán của khóa | 9 khóa `OK` (24 giờ), 2 khóa `MULTI_ITEM` (`MEDX.COU-STR-001`, `MEDX.D6TABCV8`) |

**Kết luận:**
- Đây là **một đơn có nhiều dòng hàng hợp lệ**, không phải một dòng bị đếm lặp.
- Kết luận cũ chỉ dựa trên hậu tố `.2`, nên **không còn căn cứ** coi đơn là sai.
- Không có gì được sửa, xóa hay gộp.

**Chưa xác minh được:** tính đúng nghiệp vụ của đơn so với hệ thống bán hàng gốc. Không có nguồn đối chiếu ngoài bảng này, nên báo cáo không khẳng định đơn "hoàn toàn đúng".

### 5. Trạng thái dữ liệu MULTI_ITEM

Sau khi bổ sung giờ mở bán cho trước tháng 03, số khóa `MULTI_ITEM` tăng từ 2 lên **6**:

| Ngày | FC | SKU | Item: dòng / đơn / số lượng / giờ | Số lượng khóa |
|---|---|---|---|---|
| 09/02 | HN | MEDX.DMTS-HOA-BAO-002 | `.1`: 1 / 1 / 2 / 23,92 — `.2`: 3 / 3 / 6 / 24 | 8 |
| 10/02 | HN | MEDX.2LJ61PGE | `.1`: 1 / 1 / 1 / 21,16 — `.3`: 1 / 1 / 10 / 24 | 11 |
| 02/03 | BD | MEDX.DMTS-STA-LOS-002 | `.1`: 17 / 17 / 78 / 5,0 — `.2`: 1 / 1 / 10 / 24 | 88 |
| 02/03 | BD | MEDX.SOP-NEO-001 | `.1`: 2 / 2 / 2 / 1,7 — `.2`: 1 / 1 / 1 / 24 | 3 |
| 26/08 | BD | MEDX.COU-STR-001 | `.1`: 7 / 7 / 40 / 23,72 — `.2`: 1 / 1 / 2 / 24 | 42 |
| 26/08 | BD | MEDX.D6TABCV8 | `.1`: 3 / 3 / 3 / 22,85 — `.2`: 1 / 1 / 1 / 18,22 | 4 |

- Tổng 156 đơn vị, tức 0,0004% nhu cầu.
- 95 khóa khác cũng có từ 2 item nhưng cùng giờ, nên là `OK`.
- Mỗi item có đúng một giá trị giờ mỗi ngày.

**Trạng thái `BLOCKED_BUSINESS_RULE` cho đúng 6 khóa này:**
- Giá trị giờ để trống; không tự lấy MIN, MAX, trung bình hay 0.
- Nhu cầu vẫn giữ nguyên.
- Trong 1.2.9, cổng huấn luyện `OPEN_HOURS_INVALID` sẽ chặn training BigQuery cho tới khi có quy tắc.

**Workbook bổ sung:** `D:\Buymed\Lightgbm AI\reports\demandforecast_multi_item_review_20261020_v2.xlsx`
- SHA-256 `5B8AB0362A4344C192D543BD1869337FA8D7899DE4A4BCFC8CA3563201D265C4`; đã mở lại và kiểm tra.

| Sheet | Số dòng | Nội dung |
|---|---|---|
| `Dinh_chinh` | 5 | Câu cũ / nơi ghi / trạng thái / kết luận mới / phần chưa xác minh |
| `MULTI_ITEM_Keys` | 12 | 6 khóa × item, với trạng thái tính lại và trạng thái đã lưu |
| `MULTI_ITEM_Lines` | 113 | Dòng nguồn |
| `Item_FC_Month` | 111 | |
| `Keys_nhieu_item` | 101 | |
| `Order_SOBD38271068` | 11 | |
| `Duplicate_check` | 10 | |
| `Source_Trace` | 15 | |

### 6. Audit `total_open_hours` sau khi người dùng sửa

#### 6.1 Nguồn và thời điểm

| Mục | Giá trị |
|---|---|
| Bảng | `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`: 17 cột, không phân vùng, không clustering |
| Cập nhật | Bảng được tạo lại lúc 08:05:30 UTC (15:05 giờ VN); `refresh_time` = `15:05:19 20/10/2026` trên mọi dòng |
| Phạm vi | 01/01–19/10/2026: 292 ngày, ngày nào cũng có dòng; 8.961.566 dòng; 2 FC (BD, HN); 9.657 SKU; 17.128 SKU × FC |
| Trước / sau | Bản 07:10: 8.939.819 dòng tới 18/10, **2.946.849 dòng thiếu giờ** (78 ngày 01/01–19/03). Bản 12:29: 8.961.457 dòng. Bản 15:05: 8.961.566 dòng, **0 dòng thiếu giờ** |
| Thay đổi khác so với 07:10 | 76 ngày có số lượng khác (tổng +34 đơn vị trên cùng các ngày), do nguồn sửa lịch sử ở mỗi lần làm mới |
| Nguồn training thật sự đọc | Production 1.2.8 train từ `demand_daily` của DB production (nạp bằng D-1 tăng dần, lần cuối 12:29), **không có cột giờ mở bán**. 1.2.9 sẽ đọc `demand_daily.open_hours` sau backfill |
| Bản sao thí nghiệm cũ | `e8` (đợt 3–4): giờ chỉ từ 19–20/03. `e9` (đợt này): giờ từ 01/01 (mục 11) |

Chi phí BigQuery: khoảng 12 GB quét. Toàn bộ là SELECT, dry run trước, có trần bytes; preview và backfill trên bản sao chiếm khoảng 2,7 GB. Test BigQuery thật dùng dòng inline: 0 byte.

#### 6.2 Độ phủ

| Tháng | Dòng | Số lượng | Khóa ngày × SKU × FC | OK | MULTI_ITEM | Khóa OK giờ trong (0, 24) | Khóa OK giờ = 0 có đơn (số lượng) |
|---|---|---|---|---|---|---|---|
| 2026-01 | 1.236.672 | 5.544.776 | 169.563 | 169.563 | 0 | 4.053 | 65 (677) |
| 2026-02 | 974.854 | 4.505.372 | 130.846 | 130.844 | 2 | 4.689 | 61 (3.176) |
| 2026-03 | 1.194.880 | 6.145.707 | 168.803 | 168.801 | 2 | 7.778 | 149 (2.351) |
| 2026-04 | 966.411 | 4.450.447 | 148.537 | 148.537 | 0 | 3.916 | 136 (3.786) |
| 2026-05 | 1.026.713 | 4.892.127 | 155.294 | 155.294 | 0 | 4.403 | 219 (4.060) |
| 2026-06 | 996.750 | 4.789.177 | 152.090 | 152.090 | 0 | 4.439 | 95 (1.487) |
| 2026-07 | 955.216 | 4.209.142 | 158.314 | 158.314 | 0 | 6.335 | 52 (1.808) |
| 2026-08 | 735.333 | 3.391.968 | 130.511 | 130.509 | 2 | 14.223 | 97 (7.002) |
| 2026-09 | 519.122 | 2.572.654 | 84.064 | 84.064 | 0 | 11.254 | 26 (389) |
| 2026-10 | 355.615 | 1.509.738 | 59.867 | 59.867 | 0 | 6.732 | 31 (806) |
| **Tổng** | **8.961.566** | **42.011.108** | **1.357.889** | **1.357.883** | **6** | **67.822** | **931 (25.542)** |

- **0 ngày thiếu hoàn toàn**, 0 ngày có dòng thiếu giờ.
- **0 SKU × FC bị ảnh hưởng** bởi giờ thiếu. Số lượng của khóa không `OK` chỉ là 156 đơn vị (6 khóa `MULTI_ITEM`).
- Chuỗi thời gian có đủ 292/292 ngày lịch, không có khoảng trống.
- Ngày đầu 01/01 có 15.847 dòng và ngày cuối 19/10 có 21.706 dòng, cả hai đều đủ giờ. Riêng ngày 19/10 chưa có tín hiệu hoàn tất từ nguồn (cảnh báo `YESTERDAY_NOT_CONFIRMED` trong preview).
- Theo nhóm SKU (hạng nhu cầu):
  - nhóm A (80% số lượng): 1.333 chuỗi;
  - nhóm B (15% tiếp theo): 3.128 chuỗi;
  - nhóm C (5% cuối): 12.667 chuỗi.
  - Không nhóm nào thiếu giờ.

#### 6.3 Tính hợp lệ (hạt dòng và hạt khóa)

| Loại | Số |
|---|---|
| NULL / NaN / Inf / âm / > 24 | 0 / 0 / 0 / 0 / 0 |
| Không parse được | Không áp dụng: cột kiểu FLOAT trong BigQuery |
| = 24 giờ | 8.682.210 dòng (96,9%) |
| Trong (0, 24) | 276.339 dòng; 67.822 khóa |
| = 0 | 3.017 dòng, **đều có số lượng > 0**; 931 khóa `OK` có giờ 0 nhưng có đơn (25.542 đơn vị, 0,06%; 133 SKU × FC) |
| Không có đơn nhưng giờ = 0, hoặc không có đơn và thiếu giờ | 0 dòng. Nguồn là bảng **dòng đơn**: ngày không có đơn thì không có dòng, nên giờ mở bán của ngày đó **không quan sát được** (mục 7) |
| Mâu thuẫn trong cùng khóa | 0 `CONFLICT`; 0 item × FC × ngày có hai giá trị |
| Nhiều listing trong cùng SKU × FC × ngày | 101 khóa có từ 2 item: 95 cùng giờ (`OK`), 6 khác giờ (`MULTI_ITEM`) |
| Trùng do join / aggregation | Không có JOIN; tổng hợp khớp nguồn 292/292 ngày (mục 6.4) |

Giờ = 0 khi có đơn **không bị tự coi là lỗi**: được lưu `OK` với giá trị 0, khác với "thiếu". Ý nghĩa nghiệp vụ cần chủ dữ liệu giải thích (mục 9).

#### 6.4 Grain và tổng hợp

- **Không nhân bản số lượng, không mất dòng.**
  - Preview và backfill 1.2.9 trên bản sao đọc 8.961.566 dòng, giữ cả 8.961.566 (0 dòng bị loại), tổng hợp thành 1.357.889 khóa với tổng 42.011.108 đơn vị.
  - Truy vấn kiểm tra độc lập cho đúng các số này, và đối chiếu từng ngày khớp 292/292 ngày (số khóa, số lượng, số khóa `OK` / `MULTI_ITEM`).
- **Không trộn FC:** khóa gồm `fc_code`. **Không gộp sai listing:** không gộp giờ giữa các item, khóa khác giờ để trống.
- **Không dùng hậu tố.** Không tổng hợp giờ bằng SUM, MAX hay trung bình: giá trị chỉ được nhận khi mọi dòng có giờ bằng nhau.
- **Feature ở đúng grain:** giờ mở bán là giá trị của SKU × FC × ngày khi mọi dòng thống nhất. Chỉ 6 khóa `MULTI_ITEM` có giờ khác nhau theo item, và các khóa này để trống.
- **Lặp khóa D-1** (so_code, sku_code, fc_code, ngày): 7.203 dòng.
  - Luôn cùng item; khác số lượng và/hoặc giá; không có cặp nào giống hệt.
  - Được cộng theo quy tắc `SUM_ALL` chủ hệ thống đã duyệt (16/10).

#### 6.5 Pipeline từ nguồn tới dự báo (1.2.9)

| Bước | Kết quả |
|---|---|
| 1. Schema nguồn | `total_open_hours` FLOAT NULLABLE; `item_code` STRING |
| 2. Ánh xạ | `reference_mapping`: `open_hours ← total_open_hours`, `item_code ← item_code` (cài đặt production); mapping hash `bc5fcb06327569fb` không đổi |
| 3. Khóa join | Không có JOIN (một bảng). CTE khách hàng chỉ có khi có cột khách; cột này đang trống |
| 4. Tổng hợp | SUM số lượng, COUNT DISTINCT đơn; giờ: số dòng thiếu + MIN / MAX + 3 phép đếm item → `open_hours.cell` |
| 5. Đổi kiểu | FLOAT → REAL; 0 NaN / Inf |
| 6. Giá trị thiếu | Không giá trị → NULL + trạng thái; không bao giờ là 0 hay giá trị ngày bên cạnh |
| 7. Kiểm tra chất lượng | Preview: `OPEN_HOURS_WOULD_BE_LOST` = 0 dòng. `data-check` trên bản sao: WARN `open_hours_window_ready` = 6 (đúng 6 khóa) và `forecast_series_meta` = 1 (một lần chạy cũ, trước migration 0003, không liên quan) |
| 8. Feature | `open_hours_last` (ngày trước mốc) và `open_hours_mean_7` (các ngày biết giá trị trong 7 ngày trước mốc); NaN giữ nguyên |
| 9. Tập huấn luyện | Panel lấy giá trị đã lưu; 6 khóa `MULTI_ITEM` → NaN |
| 10. Backtest | Walk-forward; `truncate(origin)` chỉ dùng dữ liệu trước mốc |
| 11. Inference | Cùng hàm `features_at`; sau mốc không biết giờ (DIRECT: feature tại mốc) |
| 12. Lưu kết quả | Dự báo theo SKU × FC × ngày; identity của lần train có cả giờ mở bán |

**Fallback âm thầm:**
- Giờ mở bán không có fallback nào.
- Nhóm giảm giá và khuyến mãi: nguồn không có cột, nên registry tắt theo quy tắc độ phủ (`NO_DATA`); không thay bằng 0.
- Giá được forward-fill theo thiết kế đã ghi trong tài liệu.
- Nhu cầu 0 của ngày không có đơn sau khi chuỗi bắt đầu là định nghĩa của target, không phải điền thiếu.

### 7. Các vấn đề chất lượng dữ liệu còn lại

| # | Vấn đề | Số liệu | Tác động | Đề xuất |
|---|---|---|---|---|
| 1 | Giờ = 0 nhưng có đơn | 931 khóa / 133 SKU × FC / 25.542 đơn vị (0,06%) | Nhỏ; giá trị hợp lệ trong miền, giữ nguyên | Chủ dữ liệu giải thích (đơn tạo khi đóng bán? cách đo giờ?) |
| 2 | DB production lệch nguồn ở các ngày cũ | So với nguồn hiện tại: 772 khóa không còn ở nguồn, 344 khóa mới, 213 khóa đổi số lượng; −12.109 đơn vị (−0,03%) | Training production dùng lịch sử hơi cũ. D-1 thường chỉ đọc lại 3 ngày; nguồn sửa lịch sử ở mỗi lần làm mới | Sau khi phát hành 1.2.9: một lần backfill có preview (cũng là cách nạp giờ mở bán); chủ hệ thống quyết định |
| 3 | Giờ mở bán không quan sát được ngày không có đơn | Khoảng 70% điểm ngày thường có actual 0 (đợt 4) | Không phân biệt được "đóng bán" với "không có nhu cầu" | Cần một nguồn trạng thái mở bán theo ngày, không phụ thuộc đơn (chủ dữ liệu) |
| 4 | Dòng đơn rất lớn | 438 dòng ≥ 1.000 đơn vị (888.585 đơn vị, 2,1%); lớn nhất 71.834 (28/08, BD, `MEDX.9DCBBCV8`, DELIVERED), bằng khoảng 66% nhu cầu một ngày tháng 8 | Chi phối metric của fold 20/08. Không xóa, không clip | Chủ hệ thống xác nhận có phải đơn sỉ / dự án không |
| 5 | Nhu cầu giảm từ tháng 7 | Xem bảng dưới | Model học mức cũ → dự báo dư (đợt 4) | Xác nhận nguyên nhân; giờ mở bán giảm là một dấu hiệu |
| 6 | `sku_system_status` là trạng thái **hiện tại** | Đã xác minh ở đợt 2: 35 / 17.128 SKU × FC có hơn một giá trị | Không phải feature (đã có test) | Giữ nguyên |

Target (`demand_quantity`, bản 15:05):
- 7 trạng thái đơn: COMPLETED 96,7% số dòng, DELIVERED, DELIVERING, CONFIRMED, WAIT_TO_DELIVER, PROCESSING, WAIT_TO_CONFIRM.
- **Không có trạng thái hủy**, nên không có gì phải trừ.
- Số lượng mỗi dòng từ 1 tới 71.834; 0 NULL / âm; trung vị 2.

**Xu hướng nhu cầu theo SKU × FC (bản sao `e9`):**

| Tháng | Nhu cầu / ngày | Chuỗi SKU × FC có đơn | Số lượng / chuỗi-ngày có đơn | Ngày có đơn với giờ < 24 | Giờ TB ngày có đơn |
|---|---|---|---|---|---|
| 2026-01 | 178.864 | 12.716 | 32,7 | 2,4% | 23,77 |
| 2026-02 | 160.906 | 12.250 | 34,4 | 3,6% | 23,67 |
| 2026-03 | 198.249 | 12.822 | 36,4 | 4,7% | 23,49 |
| 2026-04 | 148.348 | 12.315 | 30,0 | 2,7% | 23,73 |
| 2026-05 | 157.811 | 12.514 | 31,5 | 3,0% | 23,68 |
| 2026-06 | 159.639 | 12.849 | 31,5 | 3,0% | 23,71 |
| 2026-07 | 135.779 | 13.173 | 26,6 | 4,0% | 23,64 |
| 2026-08 | 109.418 | 13.130 | 26,0 | 11,0% | 23,01 |
| 2026-09 | 85.755 | 11.369 | 30,6 | 13,4% | 22,66 |
| 2026-10 | 79.460 | 9.368 | 25,2 | 11,3% | 22,98 |

| Nhóm chuỗi (T4–T6 so với 01/09–19/10) | Số chuỗi | Nhu cầu / ngày T4–T6 | Nhu cầu / ngày T9–T10 | Phần của mức giảm ròng | Giờ TB ngày có đơn T4–T6 → T9–T10 |
|---|---|---|---|---|---|
| giảm 0–50% | 2.767 | 47.891 | 34.597 | 18,5% | 23,7 → 22,4 |
| giảm > 50% | 4.741 | 62.947 | 13.256 | 69,0% | 23,6 → 20,0 |
| mới / bán lại | 1.290 | 0 | 1.826 | -2,5% | – |
| ổn định hoặc tăng | 4.238 | 23.639 | 33.635 | -13,9% | 23,4 → 22,4 |
| ngừng (0 trong T9–T10) | 3.103 | 20.817 | 0 | 28,9% | – |

**Đọc bảng:**
- Mức giảm đến chủ yếu từ các chuỗi giảm hơn một nửa (69%) và các chuỗi ngừng bán (29%).
- Ở chính các chuỗi đó, giờ mở bán trung bình trên ngày có đơn giảm từ 23,6 xuống 20,0 giờ.
- Tỷ lệ ngày có đơn mà giờ dưới 24 tăng từ khoảng 3% (tháng 4–6) lên 11–13% (tháng 8–10).

Đây là **dấu hiệu khả năng bán bị thu hẹp** (SKU bị đóng bán một phần ngày), không chỉ nhu cầu giảm. Tuy nhiên mới là tương quan, chưa phải bằng chứng nhân quả, và ngày không có đơn thì không đo được giờ.

### 8. Code đã sửa và test

**Không phát hiện lỗi chức năng mới tái hiện được** trong pipeline:
- D-1 khớp nguồn tuyệt đối;
- không có JOIN, không nhân bản;
- không có fallback thay giờ thiếu.

Phần sửa là **câu chữ sai** về hậu tố, cộng test chặn việc dùng hậu tố về sau.

| File | Thay đổi |
|---|---|
| `backend/app/data/open_hours.py` | Docstring: bỏ "item = listing của một miền bán", ghi quy tắc hậu tố; cập nhật ghi chú lưu giữ giờ của nguồn (bản 15:05 có giờ từ 01/01) |
| `backend/app/ml/feature_registry.py` | Chữ giải thích feature giờ mở bán trên giao diện |
| `backend/tests/test_v129e_item_suffix.py` (mới, 3 test) | Câu D-1 không dùng hàm chuỗi nào trên `item_code`, chỉ đếm; trạng thái chỉ phụ thuộc số đếm; chữ giải thích không gọi item là miền |
| `backend/tests/test_v129e_real_bq_item_suffix.py` (mới, BigQuery thật, opt-in) | Dòng inline: hậu tố `.1/.2`, đảo ngược, số khác, không hậu tố → cùng `MULTI_ITEM`; mỗi FC một item → `OK`; một item hai giá trị → `CONFLICT`; không mã item nào trả về |
| `CHANGELOG.md`, `docs/02_kien_truc_du_lieu/BIGQUERY.md` (§6, §11c, §11d mới), `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `docs/03_van_hanh/CHECKPOINT.md` | Đính chính + dữ kiện đợt 5 |

| Kiểm tra | Kết quả |
|---|---|
| Backend (unit / tích hợp với fake) | **632 passed, 10 skipped, 0 failed, exit 0** (15:49–16:02). 10 skip = các test BigQuery thật opt-in. Log: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p20\pytest_full.txt` |
| BigQuery thật (opt-in, dòng inline, 0 byte) | `test_v129e_real_bq_item_suffix.py` + `test_v129c_real_bq_items_customers.py`: **2 passed** |
| Frontend | Không đổi trong đợt này → không chạy lại (149/149 lúc 10:52) |
| Lint | Chưa được cấu hình |
| Đuôi dòng | 0 lỗi trên mọi file thay đổi / mới |

### 9. Việc cần người dùng xử lý

1. **Quy tắc giờ mở bán cho 6 khóa `MULTI_ITEM`** (mục 5). Các lựa chọn, ứng dụng không tự chọn:
   - để trống và cho training bỏ qua đúng các khóa này;
   - lấy giờ của item có nhiều số lượng hơn;
   - MAX;
   - trung bình theo số lượng.

   Trước khi có quy tắc, training BigQuery của 1.2.9 bị chặn bởi `OPEN_HOURS_INVALID`.
2. **Giờ = 0 nhưng có đơn** (931 khóa): giải thích ý nghĩa nghiệp vụ.
3. **Dòng đơn rất lớn** (438 dòng ≥ 1.000 đơn vị; dòng 71.834 ngày 28/08): đơn sỉ / dự án hay bình thường?
4. **Nhu cầu giảm từ tháng 7:** xác nhận nguyên nhân. Giờ mở bán giảm ở các chuỗi giảm mạnh (mục 7).
5. **Nguồn trạng thái mở bán cho cả ngày không có đơn**, nếu có. Thiếu nguồn này, model không phân biệt được "đóng" với "không có nhu cầu".
6. **Phát hành 1.2.9 + backfill có preview.** Hai việc này nạp giờ mở bán và đồng bộ lại lịch sử đã lệch (−0,03%). Cả hai là quyết định của chủ hệ thống, không làm trong đợt này.
7. **Mục tiêu dự báo dư đo được** (từ đợt 4): metric, grain, tập ngày.

### 10. Phiên bản dataset

| Mục | Giá trị |
|---|---|
| Bản sao | `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p20\e9` |
| Cách tạo | DB production sao bằng backup API, nguồn mở chỉ đọc, lúc 15:25:57; migrate 6 → 8 bằng code 1.2.9; backfill 01/01–19/10 bằng chính code D-1 1.2.9; preview `BFP-20261020082746-E6B4D7` READY |
| Nguồn | Bản làm mới 15:05:19 ngày 20/10/2026 |
| Phạm vi | 01/01–19/10/2026: 292 ngày, 1.357.889 dòng ngày × SKU × FC, 42.011.108 đơn vị |
| Identity nội dung (`content-v1`) | `2e11fa4de98f50ea40d5a835d142e4281d251b228bcad77430823576d0120e80` |
| Identity kèm giờ mở bán | `f86669c2a556fa63762727124c3ed06f53a72a70b9b92201cd6c4dc66a99f4b1` |
| SHA-256 các dòng (gồm giờ, trạng thái) | `2051A74E2907417294932112650A90C8B0339D88BAA0E682173C3BD004560F7F` |
| Trạng thái giờ | OK 1.357.883; MULTI_ITEM 6 |
| `data-check` | WARN: 6 khóa `MULTI_ITEM` + 1 cảnh báo cũ (`forecast_series_meta`); không FAIL |

### 11. Ảnh hưởng tới kết quả S0–S5 và K1–K6 (và các đợt trước)

**So sánh `e8` (đợt 3–4) với `e9`, 01/01–18/10:**
- Giờ mở bán của mọi khóa `OK` ở cả hai bản **không đổi giá trị nào** (954.334 khóa của 20/03–18/10).
- Khoảng 400 nghìn khóa 01/01–19/03 chuyển MISSING → OK.
- 4 khóa MISSING → MULTI_ITEM; 2 khóa CONFLICT → MULTI_ITEM: chỉ là đổi tên trạng thái, có từ đợt 3.
- Nhu cầu: e8 41.932.631 → e9 41.920.352 đơn vị (−12.279, −0,03%). 755 khóa chỉ có ở e8, 340 khóa chỉ có ở e9, 188 khóa đổi số lượng.

| Tháng | Khóa có ở cả e8 và e9 | Chỉ e8 | Chỉ e9 | Khóa đổi số lượng | Giờ OK ở cả hai: số khóa / đổi giá trị | Đổi trạng thái giờ |
|---|---|---|---|---|---|---|
| 2026-01 | 169.508 | 77 | 55 | 0 | 0 / 0 | MISSING → OK 169.508 |
| 2026-02 | 130.800 | 59 | 46 | 0 | 0 / 0 | MISSING → MULTI_ITEM 2, MISSING → OK 130.798 |
| 2026-03 | 168.748 | 125 | 55 | 0 | 69.174 / 0 | MISSING → MULTI_ITEM 2, MISSING → OK 99.572 |
| 2026-04 | 148.492 | 117 | 45 | 0 | 148.492 / 0 | – |
| 2026-05 | 155.246 | 90 | 48 | 36 | 155.246 / 0 | – |
| 2026-06 | 152.054 | 81 | 36 | 0 | 152.054 / 0 | – |
| 2026-07 | 158.278 | 89 | 36 | 0 | 158.278 / 0 | – |
| 2026-08 | 130.496 | 51 | 15 | 0 | 130.494 / 0 | CONFLICT → MULTI_ITEM 2 |
| 2026-09 | 84.062 | 30 | 2 | 0 | 84.062 / 0 | – |
| 2026-10 | 56.534 | 36 | 2 | 152 | 56.534 / 0 | – |

| Kết quả | Dữ liệu / cửa sổ / cấu hình | Dùng giờ trước khi sửa? | Phân loại |
|---|---|---|---|
| Đợt 2: E00_prod, E01–E13 (66 fold, tối 19/10) | Bản sao `p17/e` (nguồn 19/10 tối), cửa sổ 01/01, giờ OFF, fold 22/05–20/08 (+ holdout 19/09) | Không | **STILL_VALID**: chênh dữ liệu −0,03% |
| Đợt 2: O0 / O1 ("giờ mở bán chưa rõ tác dụng") | Cửa sổ 19/03, giờ chỉ từ 19/03 | Có | **REQUIRES_RETEST** → đã retest bằng C1 (mục 12) |
| Đợt 3: S0–S5 (spike weight) | `e8`, cửa sổ 19/03–18/10, giờ ON, cùng 5 fold | Có, nhưng trong cửa sổ của chúng giờ không đổi | **STILL_VALID trong phạm vi cửa sổ 19/03**. Với cửa sổ đầy đủ 01/01: **REQUIRES_RETEST** → C2 so với B0 |
| Đợt 3: S6 | Không chạy (chủ hệ thống quyết định) | – | Không áp dụng |
| Đợt 4: K1–K6 (dự báo dư ngày thường) | `e8` + S0 đã lưu, cùng cửa sổ | Như trên | **STILL_VALID trong phạm vi cửa sổ 19/03**. K4 được retest bằng C4 trên dữ liệu đầy đủ |
| Đợt 1 (19/10): "giờ NULL toàn bộ trước 19/03" | Bản nguồn 19/10 | – | **INVALIDATED** (nguồn đã sửa) |
| Đợt 3: "nguồn chỉ giữ giờ ~7 tháng" | Bản 19/10 và 20/10 07:10 | – | **INVALIDATED** cho bản 15:05. Lần làm mới sau có giữ không: **UNKNOWN** |
| Đợt 3: workbook giờ = 0 có đơn (2.592 dòng, 20/03–18/10) | Bản 20/10 07:10 | – | **REQUIRES_RETEST**: nay 3.017 dòng / 931 khóa trên 01/01–19/10 (mục 6.3) |
| Ứng viên `TRN-20261020054540-D7EEF6` (người dùng train 12:43, 1.2.8) | DB production lúc 12:43, không dùng giờ | Không | Không bị ảnh hưởng bởi giờ mở bán. Người dùng đã promote lúc 15:24 (mục 15) |

### 12. Kết quả thí nghiệm offline

#### 12.1 Thiết kế (ghi trước khi train)

**Kế hoạch:** `scratchpad\p20\plan_lh.json`.
- Dataset `e9` (mục 10).
- 5 fold walk-forward, mỗi fold 30 ngày: 4 fold sàng lọc (22/05, 21/06, 21/07, 20/08) và holdout 19/09.
- Mỗi fold chỉ train trên dữ liệu **trước** mốc của nó. Không chỉnh gì theo kết quả của fold.

**Baseline B0:**
- Cài đặt model production: tweedie 1.2, 300 vòng, 31 lá, lr 0,05, DIRECT 12 mốc, Price ON, customer OFF.
- Quy tắc 1.2.9: giờ mở bán ON (bắt buộc cho BigQuery), thứ ISO.
- Cửa sổ từ 01/01, nay đã đủ giờ.

| Cấu hình | Thay đổi so với B0 (chỉ dùng cài đặt có sẵn) | Giả thuyết |
|---|---|---|
| C1_no_open_hours | Tắt giờ mở bán (= cách 1.2.8 đang train) | H-d: giờ mở bán đủ lịch sử giúp model |
| C2_window_0319 | Cửa sổ từ 19/03 (= S0 của đợt 3–4) | Kiểm tra lại S0 trên dữ liệu đã sửa; lịch sử dài hơn (tháng 1–3, mức nhu cầu cao) có làm dự báo dư hơn không |
| C3_origins6 | `direct_origins` 6 thay vì 12 (học từ 6 mốc gần nhất) | H-b: nhu cầu giảm từ tháng 7, học từ gần đây bám mức hiện tại |
| C4_recency30 | Trọng số thời gian 0,5^(tuổi/30) cho dòng train (chỉ trong thí nghiệm) | H-b, cách khác (K4 đợt 4, kiểm tra lại trên dữ liệu đầy đủ) |
| C5_no_intermittent_fallback | `intermittent_zero_share` 1,0: chuỗi gián đoạn dùng LightGBM thay vì mức phẳng 28 ngày (cùng booster B0) | H-a / H-c: mức phẳng đặt cùng một giá trị dương lên mọi ngày, kể cả ngày không có đơn |
| C6_inactive30 | `inactive_days` 30 thay vì 60: chuỗi 30 ngày không có đơn → 0 (cùng booster B0) | H-a: chuỗi "ngủ" tạo dự báo dương ở ngày không có đơn |

**Metric:**
- Tính trên tổng (pooled) các quan sát SKU × FC × ngày có actual. Actual 0 = không có đơn; ngày chưa bắt đầu hoặc trống lịch không được tính.
- Dự báo là số nguyên đã công bố (`app/qty.py`).
- Công thức:
  - WAPE = Σ|F−A| / ΣA;
  - bias = Σ(F−A) / ΣA;
  - over = Σmax(F−A, 0) / ΣA;
  - under = Σmax(A−F, 0) / ΣA;
  - F/A = ΣF / ΣA;
  - "actual 0 mà F > 0" = số quan sát actual 0 có dự báo dương ÷ số quan sát actual 0.
- ΣA = 0 thì tỷ lệ không xác định; quan sát vẫn giữ.
- Ứng viên có cửa sổ khác được so trên **quan sát chung** với B0.

**Quy tắc trạng thái** (mọi ngày, chỉ so chiều, không đặt ngưỡng nghiệp vụ):
- **Tốt hơn** = WAPE thấp hơn **và** over thấp hơn **và** under không cao hơn B0.
- `IMPROVES` = tốt hơn ở cả sàng lọc **và** holdout.
- `NOT_CONFIRMED` = tốt hơn ở sàng lọc, không ở holdout.
- `TRADE_OFF` = không tốt hơn nhưng WAPE hoặc over thấp hơn.
- `NO_IMPROVEMENT` = cả hai không thấp hơn.
- Không trạng thái nào dẫn tới promote.

**Chạy:**
- 25 lần train, 16:13–16:57 (1,17 giờ, kể cả thời gian harness tự chờ khung D-0 15:50–16:10 và job D-0 lúc 16:00).
- RAM trống thấp nhất 1,16 GB; không lỗi.
- Chỉ đọc bản sao; không ghi file model, không publish.

#### 12.2 Kết quả gộp

**4 fold sàng lọc (22/05, 21/06, 21/07, 20/08), gộp** (mọi ngày, dự báo số nguyên, hạt quan sát; so trên quan sát chung với B0)

| Cấu hình | WAPE | Bias | Over | Under | F/A | Ngày thường: over / bias | Ngày spike: WAPE | Actual 0 mà F > 0 | Tổng 30 ngày / chuỗi: WAPE | Chuỗi tốt hơn / kém hơn B0 |
|---|---|---|---|---|---|---|---|---|---|---|
| B0_base | 0,7948 | 1,2% | 40,4% | 39,1% | 1,012 | 48,5% / 18,7% | 0,8564 | 37,2% | 0,4817 | – |
| C1_no_open_hours | 0,7944 | 1,3% | 40,4% | 39,0% | 1,013 | 48,5% / 18,8% | 0,8548 | 37,1% | 0,4842 | 11.736 / 10.492 |
| C2_window_0319 | 0,7939 | 1,1% | 40,3% | 39,1% | 1,011 | 48,4% / 18,6% | 0,8529 | 40,1% | 0,4787 | 12.202 / 11.663 |
| C3_origins6 | 0,8035 | 2,1% | 41,2% | 39,1% | 1,021 | 49,5% / 19,7% | 0,8528 | 35,8% | 0,4878 | 12.623 / 12.294 |
| C4_recency30 | 0,7922 | 1,1% | 40,1% | 39,1% | 1,011 | 48,2% / 18,5% | 0,8531 | 36,7% | 0,4818 | 12.489 / 10.427 |
| C5_no_intermittent_fallback | 0,7954 | 1,4% | 40,5% | 39,1% | 1,014 | 48,6% / 18,8% | 0,8561 | 37,6% | 0,4809 | 2.356 / 2.963 |
| C6_inactive30 | 0,7947 | 1,2% | 40,3% | 39,1% | 1,012 | 48,4% / 18,6% | 0,8564 | 37,0% | 0,4815 | 91 / 6 |

**holdout 19/09** (mọi ngày, dự báo số nguyên, hạt quan sát; so trên quan sát chung với B0)

| Cấu hình | WAPE | Bias | Over | Under | F/A | Ngày thường: over / bias | Ngày spike: WAPE | Actual 0 mà F > 0 | Tổng 30 ngày / chuỗi: WAPE | Chuỗi tốt hơn / kém hơn B0 |
|---|---|---|---|---|---|---|---|---|---|---|
| B0_base | 0,7811 | -11,3% | 33,4% | 44,7% | 0,887 | 40,7% / 4,8% | 0,8534 | 20,5% | 0,4839 | – |
| C1_no_open_hours | 0,7915 | -9,4% | 34,9% | 44,3% | 0,906 | 42,5% / 7,0% | 0,8453 | 20,6% | 0,4916 | 1.884 / 1.910 |
| C2_window_0319 | 0,7864 | -10,6% | 34,0% | 44,6% | 0,894 | 41,4% / 5,6% | 0,8515 | 21,2% | 0,4897 | 1.868 / 1.814 |
| C3_origins6 | 0,7936 | -14,4% | 32,5% | 46,9% | 0,856 | 39,5% / 1,4% | 0,8692 | 18,3% | 0,5313 | 2.280 / 1.971 |
| C4_recency30 | 0,7856 | -10,6% | 34,0% | 44,6% | 0,894 | 41,4% / 5,5% | 0,8462 | 18,8% | 0,4856 | 2.149 / 1.638 |
| C5_no_intermittent_fallback | 0,7771 | -11,8% | 33,0% | 44,8% | 0,882 | 40,1% / 4,2% | 0,8534 | 18,7% | 0,4831 | 733 / 557 |
| C6_inactive30 | 0,7807 | -11,4% | 33,3% | 44,7% | 0,886 | 40,6% / 4,7% | 0,8534 | 20,3% | 0,4836 | 50 / 3 |

| Cấu hình | Trạng thái (quy tắc ghi trước) |
|---|---|
| B0_base | `baseline` |
| C1_no_open_hours | `TRADE_OFF` |
| C2_window_0319 | `NOT_CONFIRMED` |
| C3_origins6 | `NO_IMPROVEMENT` |
| C4_recency30 | `NOT_CONFIRMED` |
| C5_no_intermittent_fallback | `NO_IMPROVEMENT` |
| C6_inactive30 | `TRADE_OFF` |

#### 12.3 Đọc kết quả theo giả thuyết

**Không cấu hình nào đạt `IMPROVES`.** Mọi chênh lệch WAPE đều nhỏ hơn 0,011, trừ C3 kém rõ hơn.

- **H-d, giờ mở bán** (B0 so với C1):
  - Ở sàng lọc, hai cấu hình gần như bằng nhau (0,7948 / 0,7944).
  - Ở holdout, có giờ tốt hơn (0,7811 / 0,7915; over 33,4% / 34,9%). Theo fold, có giờ tốt hơn ở 3/5 fold.
  - Feature giờ chỉ chiếm khoảng 0,07% gain của model, vì 97% dòng là 24 giờ và giờ chỉ biết ở ngày có đơn.
  - **Kết luận:** giữ giờ mở bán như 1.2.9 quy định là hợp lý, nhưng đây không phải đòn bẩy chính. Bằng chứng còn yếu.
- **Cửa sổ** (C2, từ 19/03):
  - Tốt hơn nhẹ ở sàng lọc (0,7939), kém hơn ở holdout (0,7864): `NOT_CONFIRMED`.
  - Cùng cấu hình này, S0 trên `e8` và C2 trên `e9` cho WAPE từng fold chênh không quá 0,008 (bảng ở mục 13). Kết quả cũ **tái lập** được trên dữ liệu đã xác minh.
- **H-b, nhu cầu giảm:**
  - C3 (6 mốc) kém hơn: sàng lọc 0,8035, holdout 0,7936; dự báo dư còn tăng ở sàng lọc.
  - C4 (trọng số thời gian) tốt hơn nhẹ cả ba metric ở sàng lọc (0,7922) nhưng kém ở holdout (0,7856): `NOT_CONFIRMED`, giống K4 đợt 4.
  - Học "gần đây hơn" bằng cài đặt có sẵn không bám được mức mới một cách ổn định.
- **H-a / H-c, ngày không có đơn:**
  - C5 kém hơn ở sàng lọc, tốt hơn ở holdout: `NO_IMPROVEMENT` theo quy tắc. Chẩn đoán: các chuỗi đi theo mức phẳng `FALLBACK_INTERMITTENT` thực ra bị dự báo **thiếu** (bias −40% sàng lọc, −59% holdout), nên không phải nguồn dự báo dư.
  - C6 chỉ đổi 97 chuỗi-fold ở sàng lọc, ảnh hưởng không đáng kể.
- **Nguồn dự báo dư vẫn như đợt 4:**
  - Ngày actual = 0 nhận lượng dự báo bằng 15,7% tổng actual ở sàng lọc, tức khoảng 39% toàn bộ over; ở holdout là 10,8%.
  - Phần còn lại đến từ mức nhu cầu giảm: fold 20/08 có bias ngày thường +50,8% và WAPE 1,10.
  - 96,7% actual và khoảng 96% over (sàng lọc) nằm ở các chuỗi dự báo bằng LightGBM.
  - Không thay đổi cấu hình nào trong phạm vi cho phép (không đổi target, không clip, không đổi họ model) xử lý được hai nguyên nhân này.

**Quyết định theo quy tắc:**
- Giữ baseline.
- Không promote, không bật cài đặt mới.
- Không chạy thêm cấu hình nào.

### 13. Metric theo fold và theo nhóm SKU × FC

**WAPE / bias theo fold** (mọi ngày, số nguyên)

| Cấu hình | 2026-05-22 | 2026-06-21 | 2026-07-21 | 2026-08-20 | 2026-09-19 |
|---|---|---|---|---|---|
| B0_base | 0,7003 / -11,2% | 0,7212 / -3,5% | 0,7894 / 8,7% | 1,1030 / 21,8% | 0,7811 / -11,3% |
| C1_no_open_hours | 0,6992 / -10,7% | 0,7219 / -3,5% | 0,7912 / 8,5% | 1,0985 / 21,7% | 0,7915 / -9,4% |
| C2_window_0319 | 0,7000 / -11,4% | 0,7239 / -2,4% | 0,7877 / 7,9% | 1,0957 / 20,8% | 0,7864 / -10,6% |
| C3_origins6 | 0,7081 / -11,5% | 0,7493 / 2,0% | 0,7824 / 6,1% | 1,1032 / 21,7% | 0,7936 / -14,4% |
| C4_recency30 | 0,6990 / -11,2% | 0,7201 / -2,5% | 0,7830 / 7,7% | 1,1005 / 20,5% | 0,7856 / -10,6% |
| C5_no_intermittent_fallback | 0,7018 / -10,9% | 0,7216 / -3,4% | 0,7889 / 8,7% | 1,1036 / 21,9% | 0,7771 / -11,8% |
| C6_inactive30 | 0,7001 / -11,2% | 0,7210 / -3,6% | 0,7893 / 8,7% | 1,1027 / 21,8% | 0,7807 / -11,4% |

**B0 theo fold: ngày thường và ngày spike**

| Fold | Ngày thường: WAPE / over / under / bias | Ngày spike: WAPE / bias | Tổng actual |
|---|---|---|---|
| 2026-05-22 | 0,6697 / 35,4% / 31,5% / 3,9% | 0,8467 / -83,5% | 4.828.684 |
| 2026-06-21 | 0,6961 / 40,7% / 28,9% / 11,8% | 0,8552 / -85,5% | 4.337.656 |
| 2026-07-21 | 0,7805 / 51,3% / 26,8% / 24,5% | 0,8415 / -83,7% | 3.699.647 |
| 2026-08-20 | 1,1600 / 83,4% / 32,6% / 50,8% | 0,8878 / -87,5% | 2.582.872 |
| 2026-09-19 | 0,7653 / 40,7% / 35,9% / 4,8% | 0,8534 / -85,0% | 2.462.175 |

**B0 theo nhóm SKU × FC (sàng lọc)** - nhóm nhu cầu và hạng khối lượng tính từ 91 ngày trước mốc

| Nhóm | Phần actual | WAPE | Bias | Over | Under |
|---|---|---|---|---|---|
| actual>0 | 100,0% | 0,6375 | -14,5% | 24,6% | 39,1% |
| days=1-7 | 23,5% | 0,7079 | -1,7% | 34,5% | 36,3% |
| days=16-30 | 50,1% | 0,8330 | 4,8% | 44,1% | 39,2% |
| days=8-15 | 26,4% | 0,7998 | -3,0% | 38,5% | 41,5% |
| fc=BD | 70,7% | 0,7323 | -1,1% | 36,1% | 37,1% |
| fc=HN | 29,3% | 0,9455 | 6,8% | 50,7% | 43,9% |
| group=ERRATIC | 46,5% | 0,8381 | 0,4% | 42,1% | 41,7% |
| group=INACTIVE | 0,1% | 1,0000 | -100,0% | 0,0% | 100,0% |
| group=INTERMITTENT | 2,6% | 1,1966 | -18,4% | 50,6% | 69,0% |
| group=LUMPY | 11,6% | 1,3668 | 15,3% | 76,0% | 60,7% |
| group=SHORT_HISTORY | 0,9% | 1,2994 | -20,5% | 54,7% | 75,2% |
| group=SMOOTH | 38,4% | 0,5303 | -0,0% | 26,5% | 26,5% |
| tier=HIGH_VOLUME | 78,6% | 0,6969 | -0,1% | 34,8% | 34,9% |
| tier=LOW_VOLUME | 20,9% | 1,1588 | 8,4% | 62,2% | 53,7% |
| tier=NO_VOLUME | 0,5% | 1,0000 | -100,0% | 0,0% | 100,0% |
| ngày actual = 0 (dự báo trên các ngày này, so với tổng actual) | 0,0% | – | – | 15,7% | – |

**B0 theo cách dự báo của chuỗi (sàng lọc)**

| Cách dự báo | Quan sát | Actual | Dự báo | Over (đơn vị) | Bias |
|---|---|---|---|---|---|
| LIGHTGBM | 896.520 | 14.942.051 | 15.329.235 | 5.988.556 | 2,6% |
| FALLBACK_INTERMITTENT | 745.980 | 339.232 | 203.160 | 172.657 | -40,1% |
| FALLBACK_INACTIVE_ZERO | 237.930 | 33.353 | 0 | 0 | -100,0% |
| FALLBACK_NEW_SERIES | 75.194 | 134.223 | 106.770 | 73.477 | -20,5% |

**B0 theo nhóm SKU × FC (holdout)** - nhóm nhu cầu và hạng khối lượng tính từ 91 ngày trước mốc

| Nhóm | Phần actual | WAPE | Bias | Over | Under |
|---|---|---|---|---|---|
| actual>0 | 100,0% | 0,6736 | -22,1% | 22,6% | 44,7% |
| days=1-7 | 25,7% | 0,7306 | -13,0% | 30,0% | 43,0% |
| days=16-30 | 48,3% | 0,8175 | -5,4% | 38,2% | 43,6% |
| days=8-15 | 26,0% | 0,7634 | -20,7% | 27,8% | 48,5% |
| fc=BD | 72,7% | 0,6995 | -13,3% | 28,3% | 41,6% |
| fc=HN | 27,3% | 0,9988 | -6,2% | 46,9% | 53,0% |
| group=ERRATIC | 38,3% | 0,8728 | 3,3% | 45,3% | 42,0% |
| group=INACTIVE | 0,3% | 1,0000 | -100,0% | 0,0% | 100,0% |
| group=INTERMITTENT | 4,7% | 1,0504 | -56,0% | 24,5% | 80,5% |
| group=LUMPY | 17,1% | 1,1342 | -34,1% | 39,7% | 73,7% |
| group=SHORT_HISTORY | 1,4% | 2,5253 | 87,9% | 170,2% | 82,3% |
| group=SMOOTH | 38,3% | 0,4344 | -13,2% | 15,1% | 28,3% |
| tier=HIGH_VOLUME | 79,0% | 0,7043 | -3,2% | 33,6% | 36,8% |
| tier=LOW_VOLUME | 20,6% | 1,0720 | -41,1% | 33,0% | 74,2% |
| tier=NO_VOLUME | 0,4% | 1,0000 | -100,0% | 0,0% | 100,0% |
| ngày actual = 0 (dự báo trên các ngày này, so với tổng actual) | 0,0% | – | – | 10,8% | – |

**B0 theo cách dự báo của chuỗi (holdout)**

| Cách dự báo | Quan sát | Actual | Dự báo | Over (đơn vị) | Bias |
|---|---|---|---|---|---|
| FALLBACK_INTERMITTENT | 232.230 | 105.113 | 43.110 | 38.323 | -59,0% |
| LIGHTGBM | 189.390 | 2.310.896 | 2.076.686 | 726.387 | -10,1% |
| FALLBACK_INACTIVE_ZERO | 81.510 | 12.487 | 0 | 0 | -100,0% |
| FALLBACK_NEW_SERIES | 7.357 | 33.679 | 63.270 | 57.321 | 87,9% |

**Kiểm tra tái lập: S0 đợt 3 (bản sao e8) so với C2 đợt này (bản sao e9), cùng cấu hình và cửa sổ 19/03** (dự báo thô, quan sát chung)

| Fold | S0 (e8): WAPE / bias | C2 (e9): WAPE / bias | Quan sát chung |
|---|---|---|---|
| 2026-05-22 | 0,7001 / -11,1% | 0,7027 / -11,1% | 431.199 |
| 2026-06-21 | 0,7266 / -2,7% | 0,7266 / -2,1% | 457.179 |
| 2026-07-21 | 0,7993 / 10,4% | 0,7910 / 8,3% | 475.147 |
| 2026-08-20 | 1,0966 / 20,4% | 1,1012 / 21,4% | 485.250 |
| 2026-09-19 | 0,7997 / -8,8% | 0,8004 / -9,5% | 492.968 |

### 14. Đánh giá điều kiện dữ liệu (data readiness)

| # | Điều kiện | Kết quả |
|---|---|---|
| 1 | Nguồn được xác minh | **Đạt**: bảng, thời điểm làm mới, schema, số dòng; truy vấn độc lập = preview của code D-1 |
| 2 | Độ phủ giờ mở bán được định lượng | **Đạt**: 100% dòng, 99,9996% khóa có giá trị |
| 3 | Không còn lỗi dữ liệu bắt buộc chưa xử lý trong tập train | **Đạt**: 0 dòng không hợp lệ, 0 trùng hoàn toàn. Giờ = 0 có đơn và dòng rất lớn được báo cáo, không phải lỗi bắt buộc |
| 4 | Không có tổng hợp chưa rõ quy tắc trong phạm vi train | **Chặn có phạm vi:** 6 khóa `MULTI_ITEM` (156 đơn vị). Giờ để trống; offline dùng NaN cho đúng các khóa này. Training 1.2.9 thật vẫn bị chặn tới khi có quy tắc |
| 5 | Grain SKU × FC × ngày đúng | **Đạt**: 292/292 ngày khớp nguồn; 11 + 6 khóa kiểm từng dòng |
| 6 | Target giữ đúng ngữ nghĩa | **Đạt**: số lượng khách đặt; không trừ hủy (nguồn không có hủy); không clip / xóa |
| 7 | Không có rò rỉ nghiêm trọng | **Đạt**: feature chỉ dùng ngày trước mốc; `sku_system_status` không là feature; customer OFF |
| 8 | Train và inference cùng định nghĩa feature | **Đạt**: cùng `build_panel` / `features_at`; giờ từ cùng trạng thái D-1 |
| 9 | Thay đổi code có test | **Đạt**: 4 test mới; backend 632 passed |
| 10 | Tái lập được dataset và kết quả | **Đạt**: identity / SHA dataset, script, kế hoạch ghi trước, npz từng fold trong checkpoint |

**Kết luận readiness:**
- Đạt cho **thí nghiệm offline** trên `e9`, với 6 khóa `MULTI_ITEM` không có giá trị giờ.
- Chưa đạt cho **training production 1.2.9**: `BLOCKED_BUSINESS_RULE` cho tới khi có quy tắc cho 6 khóa.

### 15. Trạng thái ứng viên

- **Đợt này không tạo ứng viên production nào.** Model thí nghiệm chỉ nằm trong bộ nhớ harness; không ghi file model, không publish, không promote. Không cấu hình nào đủ điều kiện đề xuất (mục 12).
- **Production có một thay đổi do người dùng thực hiện trong lúc đợt này chạy.**
  - Lúc 15:24, audit ghi `MODEL_PROMOTED` cho `TRN-20261020054540-D7EEF6`: ứng viên người dùng train lúc 12:43 trên 1.2.8, không dùng giờ mở bán.
  - Forecast `FCR-20261020082402-A42C91` được publish kèm cảnh báo `WAPE_MAX` (`USABLE_WITH_WARNING`).
  - Model đang dùng trước đó: `TRN-20261019043033-A761C1` / `FCR-20261019060524-9DE420`.
  - Tôi không gọi API ghi nào tới production. Mọi lệnh gọi đều là GET (health, settings, jobs, forecast-runs, audit).
  - Model này không bị ảnh hưởng bởi bản sửa giờ mở bán (1.2.8 không dùng giờ).

### 16. Checkpoint và SHA-256

| Checkpoint | SHA-256 | Kích thước / số mục |
|---|---|---|
| Trước khi sửa: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129e-before.zip` (15:17) | `A488F502984AFE50F1C3981813F4616EF610F861BA04A9540357AC498EC4E781` | 714.782 byte, 79 mục (77 file + patch + manifest); đã kiểm CRC, danh sách = manifest, hash từng file |
| Cuối đợt: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129e-worktree.zip` | `FBD72FFD659B264632EF517DE2516A5EADA938D85C371051DEB1D9E092C35C05` | 122.118.060 byte, 159 mục (79 file + patch, báo cáo, 77 file scratchpad p20 gồm 25 npz của các fold), 17:15; đã kiểm CRC, danh sách = manifest, hash từng file, PowerShell Get-FileHash. Không gồm bản sao DB e9 (tạo lại được bằng mk_e9.py) và workbook v2 (giữ trong reports/). Bản báo cáo trong ZIP chưa có dòng SHA này |

Checkpoint cũ không bị ghi đè. `v129d-worktree` vẫn khớp hash `3E2DFAB7…BFAF7`.

### 17. Việc tiếp theo theo thứ tự ưu tiên

1. **Chủ hệ thống:** quy tắc giờ mở bán cho 6 khóa `MULTI_ITEM` (mục 9.1). Đây là blocker duy nhất của training 1.2.9 trên dữ liệu đã sửa.
2. **Chủ hệ thống / chủ dữ liệu:**
   - định nghĩa mục tiêu dự báo dư đo được (metric, hạt, tập ngày);
   - cho biết có nguồn trạng thái mở bán cho ngày không có đơn hay không. Đây là điều kiện để giảm dự báo dư trên ngày không có đơn mà không chỉ hạ dự báo đồng loạt.
3. **Chủ dữ liệu:** giải thích 931 khóa giờ = 0 có đơn, dòng 71.834 đơn vị ngày 28/08 và nguyên nhân nhu cầu giảm từ tháng 7.
4. **Kiểm tra lại ở lần làm mới nguồn kế tiếp** (Claude, chỉ đọc, khoảng 6 GB, `scratchpad\p20\bq_oh.py`): giờ trước tháng 03 có còn được giữ không.
5. **Khi có phê duyệt riêng:** review và commit 1.2.9 → đóng gói → diễn tập → deploy → backfill có preview. Việc này nạp giờ mở bán và đồng bộ lịch sử đang lệch −0,03%.
6. **Hướng model tiếp theo**, cần phê duyệt vì ngoài phạm vi đợt này:
   - tách xác suất có đơn và lượng đơn cho chuỗi gián đoạn (mô hình hai bước);
   - feature trạng thái mở bán nếu có nguồn;
   - đánh giá theo mục tiêu do chủ hệ thống chọn.

## 3. Demand Forecasting 1.2.9 – Diễn tập nâng cấp 6 → 9, backfill và chốt actual lần đầu trên bản sao cô lập (đợt 8, 20/10/2026)

Nguồn: `reports\demandforecast_upgrade_backfill_rehearsal_20261020.md` (worktree MAIN).

| | |
|---|---|
| Thời gian | 20/10/2026, 21:11 – 22:40 (giờ Việt Nam) |
| Yêu cầu | "DEMAND FORECASTING 1.2.9 — ISOLATED UPGRADE & BACKFILL REHEARSAL" |
| Kết luận diễn tập | **PASS** trên bản sao cô lập: đạt cả 9 tiêu chí của mục 9 trong yêu cầu (mục 1). Có 3 giới hạn cần biết (mục 1). |
| Trạng thái phát hành 1.2.9 | **Chưa sẵn sàng.** Chưa có quyền commit / đóng gói; 6 khóa `MULTI_ITEM` vẫn chặn training; cần chọn cách giữ thứ tự "backfill trước, chốt sau" trên production (mục 12). Không coi là sẵn sàng chỉ vì diễn tập và test đạt. |
| Production | **Không bị thay đổi.** Chỉ đọc DB thật qua SQLite backup API (`mode=ro`) để tạo bản sao và gọi GET: bản 1.2.8, `storage.json` `8D79DBDD…E047`, không có job hay audit mới (mục 13). |
| Người đọc | Chủ hệ thống và người duyệt nghiệp vụ |

### 1. Tóm tắt

| Tiêu chí (mục 9 của yêu cầu) | Kết quả | Bằng chứng |
|---|---|---|
| Migration chạy được trên DB copy | **Đạt** | Mục 5: 6 → 9 trong 89,8 giây; chỉ thêm 2 bảng và 10 trigger; mọi bảng cũ giữ nguyên nội dung; chạy lại không làm gì |
| Chốt actual có provenance, idempotent | **Đạt** | Mục 7: 292/292 ngày đều mang load, job, preview, cửa sổ, sha256; lần `--apply` thứ hai không ghi gì |
| Backfill dry-run đối chiếu đầy đủ | **Đạt** | Mục 6 và file CSV theo từng ngày: 292 ngày, 1.357.889 khóa, 0 khóa bị chặn, 0 khóa thiếu / mơ hồ provenance |
| Nguồn đổi số không làm đổi actual đã chốt | **Đạt** (mô phỏng) | Mục 7: D-1 giả lập đổi 350 khóa, bỏ 50 khóa, thêm 20 khóa → bản chốt và KPI không đổi |
| Lịch sử forecast không bị sửa | **Đạt** | Mục 7: 13 bảng forecast / lịch sử / model / D0 / chốt 23:59 và file model giống hệt trước khi chốt |
| KPI dashboard dùng đúng tập dữ liệu | **Đạt** | Mục 8: tính độc lập từ bảng thô khớp từng chỉ số; lọc FC, trạng thái; API, Excel vi/en, ảnh chụp màn hình |
| Backup / restore | **Đạt** | Mục 5: mã 1.2.8 từ chối schema 9; khôi phục bằng mã 1.2.8 trả DB về đúng từng bảng trước nâng cấp |
| Backend / frontend / typecheck / build | **Đạt** | Mục 9: backend 647 passed / 10 skipped (BigQuery thật, opt-in) / 0 failed; frontend 152 passed; typecheck và build exit 0 |
| Không ghi production, không commit / push / deploy / đổi lịch hay cấu hình | **Đạt** | Mục 13 |

**Ba giới hạn của diễn tập:**

1. **Chạy bằng mã nguồn, chưa phải gói phát hành.** Chưa có quyền commit nên chưa có gói. Đường nâng cấp thật (`deploy-upgrade.ps1`, `install.ps1`, `rollback-version.ps1`) phải được diễn tập lại bằng gói sau khi commit.
2. **Khoảng dừng giữa backfill và lần chốt đầu chỉ có trong diễn tập.** Ứng dụng tự chốt ngay sau khi backfill ghi xong (hook sau D-1). Script diễn tập ghi nhận lời gọi đó nhưng không chạy nó, để kiểm tra tác động trước khi chốt. Trên production, bước kiểm tra trước khi chốt là **preview của backfill**; diễn tập cho thấy số của preview đúng bằng số được ghi rồi chốt (mục 6). Thứ tự này không được code tự giữ (mục 12).
3. **Một số tình huống là mô phỏng trên bản sao,** không phải hiện tượng của dữ liệu thật: nguồn đổi số, D-1 lỗi, dòng trộn lần nạp, lần nạp không có audit, sự cố giữa transaction. Mỗi mục ghi rõ chữ "mô phỏng".

### 2. Repository, phiên bản, Git

- Repository `D:\Buymed\Lightgbm AI`, nhánh `main`, HEAD `0da73b6` ("Release 1.2.8…", 19/10 16:00).
- Chuỗi phiên bản trong mã nguồn vẫn là `1.2.8` (`backend/app/__init__.py`, `frontend/package.json`). Đổi sang 1.2.9 là việc của bước phát hành, chưa làm.
- **Trước diễn tập (21:11):** 86 file chưa commit (62 file đã theo dõi bị sửa, +2.618 / −332 dòng; 24 file mới).
- **Sau diễn tập (22:35):** vẫn 86 file chưa commit, HEAD `0da73b6`. 62 file đã theo dõi bị sửa, +2.658 / −332 dòng: thêm 40 dòng, đều là 2 file tài liệu ở mục 10. 24 file mới không đổi. Không commit, không stash, không đổi nhánh.

### 3. Checkpoint và bản sao lưu

| Mục | File | SHA-256 (tính lại trong đợt này) | Kiểm tra |
|---|---|---|---|
| Checkpoint trước diễn tập | `checkpoints/checkpoint-20261020-v129h-before.zip` (804.134 byte, 89 mục) | `2FCDB393223D57FFAE5A4E5278543346CFB82EB15F05B27E36713996F866301B` | CRC, danh sách = manifest, hash từng file; **giải nén ra thư mục mới và so từng byte với working tree: 0 khác biệt**; patch = `git diff HEAD`; PowerShell `Get-FileHash` cùng giá trị. So với checkpoint cuối đợt 7 chỉ khác `docs/03_van_hanh/CHECKPOINT.md` (2 dòng ghi sau checkpoint đó). |
| Checkpoint cuối đợt | `checkpoints/checkpoint-20261020-v129h-worktree.zip` (2.197.530 byte, 127 mục: 86 file + patch, 2 báo cáo, 37 file script / kết quả / ảnh của scratchpad p23; không có bản sao DB hay bản sao lưu), 22:35 | `994455795ACD0583A70B3BED72CB04C4F2BC97742BFB42A7A7F56AD8453C3210` | CRC, danh sách = manifest, hash từng file; giải nén ra thư mục mới, so từng byte với working tree: 0 khác biệt; PowerShell cùng hash. So với `v129h-before` chỉ khác `docs/03_van_hanh/CHECKPOINT.md` và `docs/02_kien_truc_du_lieu/LICH-SU-FORECAST.md`. Báo cáo đóng gói bên trong còn 3 ô chờ điền (mục này), được điền ngay sau khi tạo checkpoint. |
| Sao lưu `pre-migration-v6` (do migration tự tạo, trong môi trường cô lập) | `scratchpad\p23\a_backups\backup-20261020-212356-pre-migration-v6.zip` (95.686.921 byte, 13 mục) | `05FBF72CA9AF8AEAB4D854BD3433E1E3C4802029BDE99DD22FC8696739CE5AC2` | zip test OK; DB bên trong integrity `ok`, schema 6, **mọi bảng giống hệt DB trước migration** (số dòng + hash nội dung); SHA không đổi sau khi khôi phục |
| Sao lưu `pre-backfill` (do backfill tự tạo) | `scratchpad\p23\a_backups\backup-20261020-214741-pre-backfill.zip` (95.690.282 byte) | `72762EC30291A6D0E75135317F4A947A18CF842C2C3E8393CF4538B107F68107` | zip test OK; integrity `ok`; schema 9; 0 ngày đã chốt; `demand_daily` giống hệt bản tham chiếu chụp ngay trước backfill |
| Sao lưu an toàn `pre-restore` (do lệnh restore của 1.2.8 tự tạo) | `scratchpad\p23\r_backups\backup-20261020-222611-pre-restore.zip` | – | zip test OK; integrity `ok`; schema 9; 292 ngày đã chốt (DB trước khi khôi phục) |

Đường dẫn scratchpad đầy đủ: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p23\`.

### 4. Bản sao DB và cách bảo đảm cô lập

- **Bản sao:** tạo lúc 21:22:11 từ `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, mở nguồn ở chế độ chỉ đọc (`mode=ro`) bằng SQLite backup API. Kết quả 726.626.304 byte, integrity `ok`, kèm `storage-id.json` và 12 file model. Không dùng lại bản sao cũ của các đợt trước; mọi số đều đo lại.
- **Cô lập:**
  - Mỗi môi trường có `DF_DATA_DIR`, `DF_LOGS_DIR`, `DF_BACKUPS_DIR`, `DF_REPORTS_DIR`, `DF_STORAGE_CONFIG`, `LOCALAPPDATA` riêng trong `scratchpad\p23`, và `DF_DISABLE_SCHEDULER=1`.
  - Script dừng trước khi nhập bất kỳ mã nào có thể ghi, nếu một đường dẫn ứng dụng phân giải ra ngoài `p23` (DB, model, log, backup, report, upload, file runtime, `storage.json`, lịch sử storage).
  - Trước `--apply`, lệnh `python -m app.cli paths` chạy trong cùng môi trường in ra toàn bộ đường dẫn trong `p23\a`. Trước khi khôi phục, `paths` của mã 1.2.8 cũng được kiểm.
  - Máy chủ dùng để chụp màn hình chạy ở cổng 8893 và tự dừng nếu `/api/system/paths` không trỏ vào `p23`.
- **Các môi trường:** `a` (chính), `p` (tham chiếu ngay trước backfill), `b` (đường production: hook sau backfill), `c` (tình huống biên, mô phỏng), `q` (màn hình trước khi chốt), `r` (khôi phục bằng mã 1.2.8).
- **BigQuery chỉ đọc:**
  - 2 lần đọc cửa sổ 01/01–19/10 (preview và backfill), mỗi lần ước tính 1.343.688.487 byte; connector tự chạy dry run và đặt `maximum_bytes_billed`.
  - 1 lần đọc metadata bảng nguồn (`get_table`, không tốn byte truy vấn) và 1 lần đọc nhỏ bảng tên sản phẩm (bước sau D-1 của ứng dụng).
  - Không có DML / DDL.
- **Cấu hình trong bản sao (không đổi):** nguồn BIGQUERY, production mode ON, Price ON (`feature_price = true`), customer_id OFF (`feature_customer = false`, cột trống), cửa sổ dữ liệu từ 01/01/2026, lùi 3 ngày.

### 5. Migration 6 → 9 và khôi phục

**Trước migration (đo trên bản sao):**

- Schema 6; 28 bảng, 35 trigger, 16 index.
- `demand_daily` (BIGQUERY): 292 ngày (01/01–19/10), 1.358.317 dòng, 42.023.217 đơn vị. Mỗi ngày đúng một `loaded_at`:
  - 285 ngày từ lần nạp lại toàn bộ 17/10 20:00 (`JOB-20261017125803-0ED367`);
  - 13/10 từ lần nạp 18/10, 14/10 từ lần nạp 19/10, 15–19/10 từ lần nạp 20/10 12:30 (`JOB-20261020052954-310535`).
- Lịch sử D+1: 4 ngày dự báo, 68.522 dòng; 2 ngày có bản sao lưu cuối ngày; 5 bản chốt 23:59 (`CLOSED_UNVERIFIED`, 18–19/10).
- Phạm vi DEMO: 38.568 dòng (không phải đối tượng chốt).
- Chưa có ngày nào được chốt, vì chưa có bảng chốt. Chạy thử chốt trên DB schema 6 (chỉ đọc): 292/292 ngày truy được về một lần nạp D-1 đã xác minh, 0 ngày bị chặn.

**Chạy migration (`db.migrate()` của mã nguồn, đúng như khi ứng dụng khởi động):**

| Bước | Kết quả |
|---|---|
| Sao lưu `pre-migration-v6` | Tạo tự động, 89,8 giây (gần như toàn bộ thời gian) |
| 0007 → schema 7, 0008 → schema 8, 0009 → schema 9 | Mỗi file một transaction; cả ba xong trong chưa tới 0,1 giây |
| Sau migration | 30 bảng (+`actual_finals`, `actual_final_values`, đều rỗng), 45 trigger (+10: `trg_afn_born_unsealed`, `trg_afn_final_fixed`, `trg_afn_keys_fixed`, `trg_afn_no_delete`, `trg_afn_no_replace`, `trg_afn_seal_checked`, `trg_afv_no_delete`, `trg_afv_no_replace`, `trg_afv_no_update`, `trg_afv_open_only`), 16 index; không đối tượng nào bị xóa. Số trigger khớp mã nguồn (10). |
| Nội dung bảng cũ | So hash từng bảng trên các cột cũ: chỉ `schema_migrations` đổi (6 → 9 dòng). 5 cột mới của `demand_daily` (0007 / 0008) đều NULL trên 1.358.317 dòng. |
| Toàn vẹn | `PRAGMA integrity_check` = `ok`; `foreign_key_check` rỗng |
| `data-check` | Không có FAIL. 2 WARN: `open_hours_window_ready` (giờ mở bán chưa nạp, hết sau backfill trừ 6 khóa `MULTI_ITEM`) và `forecast_series_meta` (1 lần chạy cũ từ 14/10, có từ trước) |
| Chạy migration lần hai | Không áp dụng gì, không tạo bản sao lưu, danh sách đối tượng giống hệt (0,03 giây) |

**Trigger, ràng buộc và đường ghi:** kiểm trên DB đã chốt, mỗi thao tác trong một transaction rồi rollback.

- 14/14 thao tác bị cấm đều bị chặn:
  - sửa, xóa, thêm hoặc `INSERT OR REPLACE` giá trị;
  - thêm giá trị không có đầu mục;
  - sửa tổng; đưa về `BLOCKED`; bỏ niêm phong; đổi `finalized_at`, ngày hay lần nạp;
  - xóa hoặc `REPLACE` đầu mục;
  - tạo đầu mục đã niêm phong sẵn.
- Các thao tác hợp lệ vẫn chạy:
  - tạo và sửa đầu mục `BLOCKED`;
  - chuyển `BLOCKED` → `FINALIZED` chưa niêm phong, thêm giá trị, niêm phong khi khớp;
  - D-1 xóa / ghi lại `demand_daily` của ngày đã chốt (bản chốt không đổi).
- Niêm phong khi số dòng không khớp bị từ chối. Sau đó DB giống hệt trước khi thử.

**Khôi phục (rollback) trong môi trường riêng `r`, bằng mã 1.2.8 lấy từ HEAD (`git archive`, không sửa repository):**

1. `python -m app.cli migrate` của 1.2.8 trên DB schema 9: **từ chối** ("Database schema version 9 is newer than this app supports (6)…"). Vậy không thể rollback mà không khôi phục.
2. `python -m app.cli restore <pre-migration-v6>` của 1.2.8: 67,1 giây. Lệnh tự tạo bản sao lưu an toàn của DB đang có (schema 9), kiểm tra integrity, thay DB, rồi chạy migrate của 1.2.8 (không có gì để áp dụng).
3. DB sau khôi phục: integrity `ok`, schema 6, không còn bảng chốt, **mọi bảng giống hệt DB trước migration**. `data-check` của 1.2.8: WARN, chỉ `forecast_series_meta` (có từ trước), 24 kiểm tra.
4. File sao lưu gốc không bị ghi (SHA-256 trước và sau như nhau). Không khôi phục gì vào production.

### 6. Backfill có kiểm soát trước khi chốt

**Cơ chế đã kiểm (mã nguồn `sync.backfill_preview` / `sync.run_d1_sync`):**

- **Preview chỉ đọc:** cùng truy vấn với lần ghi (dry run, giới hạn byte, chặn dòng trùng y hệt), so với dữ liệu đang lưu; chỉ lưu kết quả preview.
- **Backfill cần preview READY** của đúng cửa sổ, mapping và SQL, chưa dùng, không quá 6 giờ.
- **Trình tự ghi:**
  - Trước khi ghi, ứng dụng tạo một bản sao lưu online; không tạo được thì không ghi.
  - Trong khóa ghi, ứng dụng kiểm lại rằng preview vẫn READY, không có D-1 nào chen vào, và số mới / đổi / bỏ giống hệt preview.
  - Sau đó ứng dụng thay các dòng của cửa sổ, đối chiếu tổng ghi với tổng đọc, và ghi audit `D1_SYNC` trong cùng transaction.
- **Lệnh `actual-finalize`** (đã đọc mã và chạy thử):
  - Mặc định là chạy thử: mở file DB `mode=ro`, không ghi gì.
  - Chỉ `--apply` mới ghi, và chỉ vào DB đang cấu hình; `--apply` kèm `--db` bị từ chối.
  - Lệnh không gọi BigQuery, không ghi `demand_daily`, forecast, lịch sử D+1 hay bản chốt 23:59.
  - Chọn lần nạp: mọi dòng của ngày phải cùng một `loaded_at` bằng `synced_at` của đúng một audit `D1_SYNC`; chế độ hợp lệ; cửa sổ bao trùm ngày; nạp sau khi ngày kết thúc.
  - Ngày đã chốt không bao giờ được xét lại.

**Nguồn:** bảng `demand_planing_lightgbm` được tạo lại lúc 20/10 08:05:30 UTC (15:05 giờ VN), 8.961.566 dòng. Đây đúng là bản đã dùng cho bản sao xác minh ở đợt 5 (e9).

**Chạy thử khi CHƯA backfill** (phương án "chốt ngay", để so sánh): 292/292 ngày sẽ được chốt theo các lần nạp cũ: 285 ngày theo lần nạp lại 17/10, 7 ngày theo các lần nạp tăng dần. Tất cả ở chế độ `FALLBACK_TIME_VERIFIED`, không có `load_id` (các lần nạp của 1.2.8).

**Preview** (`BFP-20261020143352-B2F6F7`, READY, 482,8 giây):

| | |
|---|---|
| Đọc | 8.961.566 dòng, 0 lỗi, 0 dòng trùng y hệt; 7.203 dòng trùng khóa được cộng theo quy tắc `SUM_ALL` đã duyệt |
| Sau gộp | 1.357.889 dòng SKU × FC × ngày, tổng 42.011.108 |
| So với số đang lưu | 344 khóa mới, 213 khóa đổi số, 1.357.332 khóa giữ nguyên, 772 khóa nguồn đã bỏ; tổng −12.109; 272 ngày có thay đổi |
| Giờ mở bán sẽ ghi | `OK` 1.357.883, `MULTI_ITEM` 6; không mất giá trị OK nào đang lưu |
| Cảnh báo | `YESTERDAY_NOT_CONFIRMED` (19/10): nguồn không có tín hiệu hoàn tất, đúng như production |
| Ngày đã chốt 23:59 trong cửa sổ | 2; 1 ngày (19/10) có thay đổi → backfill tạo thêm một revision chốt 23:59, revision cũ giữ nguyên |

**Backfill** (804,1 giây): `D1L-20261020145411-F00BD1`, job `ISO-P23-BACKFILL`, `synced_at` 14:48:55 UTC (21:48:55 giờ VN), chế độ `BACKFILL`, cửa sổ 01/01–19/10.

- Kết quả đúng bằng preview: 1.357.889 dòng; 344 / 213 / 772; tổng 42.011.108.
- Watermark D-1 giữ nguyên (19/10). Preview chuyển sang `USED`. Bản sao lưu `pre-backfill` được tạo trước khi ghi.
- Ứng dụng gọi bước chốt ngay sau backfill. Script ghi nhận lời gọi (`finalize_quietly(scope, "BIGQUERY", "D-1 job ISO-P23-BACKFILL", "ISO-P23-BACKFILL")`) và **không chạy**: còn 0 ngày đã chốt.

**Chạy thử sau backfill, trước khi chốt** (CLI mặc định, 41,4 giây):

- **Không ghi gì:** hash `app.db` và `-wal`, số dòng bảng chốt, id audit / alert cuối đều giống trước và sau, kể cả khi chạy với `--db`. Hai kết quả giống nhau.
- **Kết quả:** 292 ngày `FINALIZE`, 0 `BLOCK`. Cả 292 ngày đến từ đúng một lần nạp backfill; cửa sổ bao trùm; ngày Việt Nam của lần nạp (20/10) sau ngày được chốt.
- 1.357.889 khóa chốt được, 0 khóa bị chặn, 0 khóa thiếu hoặc mơ hồ provenance.

**Đối chiếu theo ngày:** file `reports/demandforecast_upgrade_backfill_rehearsal_20261020_per_day.csv` (292 dòng; SHA-256 bắt đầu `B373388E`). Mỗi dòng có:

- ngày; lần nạp được chọn (id, job, chế độ, `synced_at`, cửa sổ, preview); bằng chứng bao trùm và "nạp sau khi ngày kết thúc";
- số khóa dự kiến, chốt được, bị chặn, thiếu / mơ hồ provenance;
- tổng trước / sau, chênh lệch theo đơn vị và %, số khóa mới / đổi / bỏ;
- quyết định nếu không backfill;
- so với bản sao xác minh đợt 5.

| Ngày (lần nạp cũ) | Số ngày | Tổng trước | Tổng sau backfill | Chênh lệch |
|---|---|---|---|---|
| 01/01–12/10 (nạp lại toàn bộ 17/10) | 285 | 41.445.377 | 41.433.682 | −11.695 (−0,028%) |
| 13/10 (nạp 18/10) | 1 | 77.216 | 77.125 | −91 (−0,12%) |
| 14/10 (nạp 19/10) | 1 | 100.296 | 100.046 | −250 (−0,25%) |
| 15–19/10 (nạp 20/10) | 5 | 400.328 | 400.255 | −73 (−0,018%) |
| **Tổng** | **292** | **42.023.217** | **42.011.108** | **−12.109 (−0,029%)** |

- 237 ngày giảm, 34 ngày tăng, 21 ngày không đổi.
- Theo tháng, chênh lệch lớn nhất là tháng 6 (−0,064%) và 01–19/10 (−0,148%).
- Ngày lệch nhiều nhất theo %: 10/10 (−927; −1,33%), 04/05 (−1.710; −0,80%), 02/06 (−988; −0,61%).

**So với báo cáo đợt 7 (số tham khảo):**

| | Đợt 7 (bản sao 20:19) | Đợt 8 (đo lại) | Giải thích |
|---|---|---|---|
| Số ngày truy được | 292/292 | 292/292 | Giống |
| Số dòng / tổng được chốt | 1.358.317 / 42.023.217 | 1.357.889 / 42.011.108 | Đợt 7 chốt ngay theo lần nạp cũ; đợt 8 chốt sau backfill theo nguồn hiện tại (−428 dòng, −12.109) |
| Chênh lệch nguồn | khoảng −0,03% | −0,029% | Giống |
| DB tăng | khoảng 81 MB | 80.982.016 byte | Giống |
| Thời gian ghi khi chốt | khoảng 38 giây | khoảng 101 giây ghi, sau khoảng 40 giây lập kế hoạch | Cùng mã, cùng số ngày. Lượt này chậm hơn có thể do I/O của máy lúc đó (bản sao cách đó vài phút); chưa đo lặp lại. Vẫn dưới 3 phút. |
| So với bản sao xác minh đợt 5 (e9) | – | 292/292 ngày bằng nhau (số dòng và tổng) | Nguồn chưa đổi từ 15:05 |

### 7. Chốt actual lần đầu trên bản sao

**Điều kiện trước khi ghi:**

- DB đích là bản sao cô lập (mục 4).
- Checkpoint và các bản sao lưu đọc được (mục 3).
- Đã lưu kết quả chạy thử và bảng đối chiếu (mục 6).
- Provenance từng ngày đã xác minh.
- Có đường khôi phục (mục 5).

**Lần chốt (`python -m app.cli actual-finalize --apply`, môi trường `a`):**

- 292 ngày (01/01–19/10) `FINALIZED` và niêm phong; 1.357.889 dòng; 42.011.108 đơn vị.
- Mọi ngày dùng lần nạp `D1L-20261020145411-F00BD1` (`BACKFILL`, preview `BFP-20261020143352-B2F6F7`, job `ISO-P23-BACKFILL`).
- 292 audit `ACTUAL_FINALIZED`; 0 alert lỗi. DB tăng 80.982.016 byte.
- Script lần 1 dừng khi đọc kết quả in ra của lệnh, vì trước JSON có một dòng log của ứng dụng; lệnh vẫn thoát bình thường. Kết quả được lấy lại từ DB và audit; script lần 2 kiểm tra tiếp. Không chạy lại lần chốt đầu.

| # | Điều kiện | Kết quả |
|---|---|---|
| 1 | Chỉ chốt ngày Việt Nam đã qua | Ngày chốt cuối là 19/10 (hôm nay 20/10); không có dòng nào của hôm nay trong `demand_daily`. Mô phỏng: kế hoạch "như thể hôm nay là 19/10" chỉ liệt kê tới 18/10; chốt "như thể chạy ngày 10/10" chốt 282 ngày, không ngày nào từ 10/10 trở đi. |
| 2 | D-1 thành công, bao trùm ngày | Cả 292 ngày: lần nạp có audit trong cùng transaction, cửa sổ 01/01–19/10 bao trùm, nạp ngày 20/10 (sau ngày được chốt) |
| 3 | Provenance rõ ràng | 292/292 ngày đủ: load id, job, `synced_at`, chế độ, cửa sổ, mapping hash, preview, sha256, thời điểm chốt |
| 4 | Transaction / đủ dữ liệu | Mỗi ngày: số dòng đầu mục = số giá trị = số dòng `demand_daily`; tổng khớp; sha256 tính lại từ giá trị và từ `demand_daily` đều bằng sha256 đã lưu; 0 dòng lệch |
| 5 | D-1 sau báo số khác không đổi bản chốt | Mô phỏng: D-1 thường (chạy qua `sync.run_d1_sync` thật, connector được thay bằng dữ liệu giả, không gọi BigQuery) cho 16–19/10: +7 đơn vị trên 350 khóa, bỏ 50 khóa, thêm 20 khóa. `demand_daily` đổi (vd. 16/10 lên 92.701), bản chốt giữ 91.986. Bảng chốt giống hệt; KPI và từng ngày trên màn hình không đổi. |
| 6 | Khóa vắng ở lần nạp sau không mất | 50 khóa bị bỏ trong mô phỏng vẫn còn trong bản chốt (vd. 189, 39, 3, 11, 2 đơn vị) |
| 7 | Chạy lại không trùng | Lần `--apply` thứ hai: 0 ngày chốt, 0 audit mới, bảng chốt giống hệt |
| 8 | Lỗi rồi chạy lại | Mô phỏng (môi trường `c`): sự cố sau khi đã ghi giá trị và niêm phong 15/10, trước commit. Ngày đó rollback hoàn toàn (0 đầu mục, 0 giá trị), alert `ACTUAL_FINALIZE_FAILED`, các ngày khác vẫn chốt. Lần chạy sau chốt 15/10; các ngày đã chốt không đổi. |
| 9 | Forecast và lịch sử không đổi | 13 bảng (`forecast_runs`, `forecast_values`, 3 bảng lịch sử D+1, 2 bảng sao lưu cuối ngày, `training_runs`, `model_versions`, 2 bảng chốt 23:59, 2 bảng D0) và `demand_daily` giống hệt trước khi chốt; 12 file model giống hệt |
| 10 | Thiếu provenance thì không chốt, có lý do | Dữ liệu thật: 0 ngày như vậy. Mô phỏng: 17/10 có 1 dòng mang `loaded_at` khác → `BLOCKED` `MIXED_LOADS`; 18/10 mọi dòng mang `loaded_at` không có audit → `BLOCKED` `NO_VERIFIED_D1_LOAD`. Màn hình giữ 18/10 là "Đã chốt – cần xác minh" kèm lý do. Lần chạy lại: 2 ngày `UNCHANGED`. Một lần nạp hợp lệ sau đó chuyển cả hai sang `FINALIZED` theo lần nạp mới; 16/10 và 19/10 giữ bản chốt từ backfill. |

**Đường production (môi trường `b`):** gọi đúng lời gọi mà ứng dụng tự gọi sau backfill. Kết quả: 292 ngày, và **giống hệt đường CLI** về trạng thái, số dòng, tổng, sha256, nội dung giá trị, lần nạp, chế độ, preview. Chỉ khác người chạy (`AFTER_D1` thay vì `CLI`) và job.

**D-1 lỗi (mô phỏng):** đọc nguồn lỗi `SOURCE_INCOMPLETE` thì không ghi gì: bảng chốt, `demand_daily` và audit không đổi.

**Khóa `MULTI_ITEM`:**

- 6 khóa có số lượng đã được chốt: 09/02 HN, 10/02 HN, 02/03 BD ×2, 26/08 BD ×2; cộng 156 đơn vị.
- Kiểm tra giờ mở bán của cửa sổ huấn luyện vẫn không đạt (`MULTI_ITEM` 6 dòng), nên training của 1.2.9 vẫn dừng với `OPEN_HOURS_INVALID`.
- Không chọn quy tắc gộp nào.

**`data-check` sau khi chốt:** `actual_final_sealed` và `actual_final_protection_triggers` OK; còn 2 WARN: 6 dòng `MULTI_ITEM` và `forecast_series_meta` có từ trước.

### 8. Dashboard và KPI trên bản sao

Mặc định 30 ngày chạy (21/09–20/10); lịch sử có 4 ngày dự báo (18/10–21/10).

| | Production 1.2.8 (GET, cùng thời điểm) | Bản sao sau nâng cấp, chưa chốt | Bản sao sau backfill + chốt |
|---|---|---|---|
| Thẻ thực tế chính | 206.569 (trộn tạm tính + chốt 23:59), nhãn "Tạm tính" | — "Chưa có actual đã chốt" | **148.240** "Thực tế đã hoàn tất" trên 34.252 dòng / 2 ngày |
| WAPE / bias chính | 83,9% / +25,5% (trộn 3 ngày) | — | **73,0% / +14,82%** |
| 18/10, 19/10 | Đã chốt – cần xác minh | Đã chốt – cần xác minh (nhóm riêng) | **Đã hoàn tất**: 57.510 và 90.730 |
| 20/10 (hôm nay) | Tạm tính | Tạm tính (nhóm riêng) 58.299, WAPE 109,0% | Tạm tính (nhóm riêng) 58.299, WAPE 109,0% |
| 21/10 | Chưa có thực tế | Chưa có thực tế | Chưa có thực tế (17.138 dòng, không tính 0) |

- 19/10 hiện 90.730 thay vì 90.760 của lần nạp cũ: backfill ghi số nguồn hiện tại (−30 trên các dòng có forecast).
- **Tính độc lập từ bảng thô** (forecast D+1, làm tròn nửa lên, × giá trị đã chốt, khóa vắng = 0): tổng thực tế, forecast, sai số tuyệt đối, sai lệch, WAPE, bias, số dòng, số ngày **đều khớp** với mã. Kiểm cho mặc định 30 ngày, toàn khoảng, và lọc FC: BD 114.845 (WAPE 63,7%, bias +9,4%), HN 33.395 (WAPE 105,3%, bias +33,5%).
- **Lọc trạng thái:**
  - "Đã hoàn tất": KPI 148.240, nhóm tạm tính rỗng.
  - "Tạm tính": KPI chính trống (`NO_FINAL_ACTUAL`), nhóm tạm tính 58.299.
- **API:**
  - `overview.finalization`: 292 ngày đã chốt, 0 bị chặn, ngày chốt mới nhất 19/10.
  - `summary`: KPI bằng mã; 30 điểm biểu đồ; mọi điểm đã chốt có `d1_load_id`.
  - `rows` lọc "Đã hoàn tất": 34.252 dòng, nguồn `FINAL`.
- **Excel H4:** tiếng Việt (sheet "Thông tin", "Phiên forecast", "Theo ngày", "Chi tiết SKU x FC") và tiếng Anh ("Info", "Forecast sessions", "By day", "SKU x FC detail"). Có cơ sở KPI, số dòng từng nhóm, tổng / WAPE tạm tính riêng; số khớp API.
- **Ảnh chụp** (mã nguồn + UI đã build, chạy trên bản sao, cổng 8893), trong `reports/demandforecast_upgrade_backfill_rehearsal_20261020_screens/`:
  - `after-finalization-vi.png`, `after-finalization-en.png`: thẻ chính đã chốt, thẻ "Thực tế chưa chốt" riêng, biểu đồ điểm đặc (đã chốt) / rỗng (chưa chốt), quy tắc chốt.
  - `before-finalization-vi.png`, `before-finalization-en.png`: ba thẻ chính ghi "Chưa có actual đã chốt", nhóm tạm tính và nhóm chốt 23:59 ở thẻ riêng.
- **Nguồn đổi số (mô phỏng, mục 7 #5):** KPI và mọi ngày trên màn hình giống hệt trước.
- **Lỗi nhỏ phát hiện:** tiếng Anh ghi "1 days" ở thẻ "Actual not finalized" (số nhiều cố định). Chỉ là hiển thị, chưa sửa.

### 9. Test

| Loại | Kết quả |
|---|---|
| Backend tập trung (9 file: chốt actual, lịch sử, chốt 23:59, retention, giờ mở bán, backfill, `MULTI_ITEM` / mã item, customer; unit + tích hợp trên DB tạm, FakeBQ) | **165 passed, 0 failed** (119 giây, 22:06–22:08) |
| Backend toàn bộ | **647 passed / 10 skipped / 0 failed** (331 giây, xong 22:33). 10 skipped = test BigQuery thật, chỉ chạy khi đặt `DF_REAL_BQ=1` (`test_bq_real_semantics` ×2, `test_v121_d0_real_bq` ×5, `test_v129_real_bq_open_hours`, `test_v129c_real_bq_items_customers`, `test_v129e_real_bq_item_suffix`) |
| Frontend `npm test` | **24 file, 152 passed, 0 failed** (21:28) |
| Frontend `typecheck` / `build` | exit 0 / exit 0 (`frontend/dist`, git-ignored; không phải gói phát hành) |
| Diễn tập trên bản sao DB thật (migration, backfill thật từ BigQuery chỉ đọc, chốt, khôi phục) | Đạt (mục 5–8) |
| Test BigQuery thật (opt-in) | Không chạy: cần bật riêng; đợt này không đổi truy vấn. Phần đọc BigQuery thật đã có trong backfill diễn tập. |
| Lint | Chưa được cấu hình |

### 10. File thay đổi trong lượt này

| File | Thay đổi |
|---|---|
| `docs/02_kien_truc_du_lieu/LICH-SU-FORECAST.md` | Mục 15: thêm quyết định "backfill trước, chốt sau", số liệu diễn tập và lưu ý vận hành (code không tự giữ thứ tự) |
| `docs/03_van_hanh/CHECKPOINT.md` | Thêm phần đợt 8 (checkpoint, các bước, kết quả) |

Không sửa mã nguồn, migration hay test. Ngoài Git (thư mục `reports/`, `checkpoints/` bị ignore):

- báo cáo này;
- file CSV theo ngày;
- thư mục ảnh chụp;
- hai checkpoint `v129h-*` kèm file `.sha256`.

Script và kết quả JSON nằm trong `scratchpad\p23`.

### 11. Thay đổi chưa commit từ trước

- Cả 86 file chưa commit trước đợt này được giữ nguyên.
- Checkpoint `v129h-before` chứa toàn bộ, đã giải nén và so từng byte.
- Checkpoint cuối liệt kê chính xác các file khác so với lúc đầu (mục 3): chỉ 2 file tài liệu ở mục 10.
- Không xóa hay ghi đè dữ liệu, log, bản sao lưu, checkpoint hay scratchpad nào có sẵn.
- File Excel 931 khóa đang mở trên máy (có file khóa `~$…`); không đụng tới.

### 12. Blocker nghiệp vụ còn lại

1. **6 khóa `MULTI_ITEM`:** chưa có quy tắc gộp giờ mở bán, nên training 1.2.9 trên BIGQUERY vẫn bị chặn (đã kiểm lại sau backfill). Không ảnh hưởng việc chốt số lượng.
2. **Giữ thứ tự "backfill trước, chốt sau" trên production.** Code không tự giữ thứ tự này: lần D-1 đầu tiên sau nâng cấp (lịch 03:00, dự phòng 05:00, thử lại mỗi 30 phút; hoặc bấm tay) cũng chốt mọi ngày truy được, theo các lần nạp cũ. Hai cách:
   - **(a) Theo quy trình, không đổi code (đề xuất):** nâng cấp vào buổi tối, sau D0 18:00 và ngoài 23:55 / 23:59, rồi chạy ngay preview → xem số → backfill. Toàn bộ khoảng 25 phút: preview khoảng 8 phút, backfill khoảng 13,5 phút, chốt khoảng 2,5 phút. Phải xong trước 03:00. Nếu preview không READY (ví dụ nguồn đang dựng lại), bạn tạm tắt D-1 trên trang Lịch chạy cho đến khi backfill xong. Bước kiểm tra trước khi chốt là preview: diễn tập cho thấy số của preview đúng bằng số được ghi rồi chốt.
   - **(b) Thêm một công tắc trong code** (ví dụ tắt chốt cho tới khi bạn bật sau backfill): an toàn hơn nếu không chắc làm kịp trong một buổi, nhưng là thay đổi hành vi, cần duyệt, test và diễn tập lại.
3. **931 khóa giờ mở bán = 0:** vẫn chờ bạn xem file Excel; không tự phân loại hay sửa.
4. **`fact_product_sku_status`:** grain (1 dòng / item × FC × ngày), độ phủ (202/202 ngày từ 01/04) và giá trị cột đã kiểm ở đợt 7. Ý nghĩa nghiệp vụ và thời điểm chụp chưa được xác nhận, nên không dùng làm feature.
5. **Đơn 71.834:** giữ kết luận cũ, giờ mở bán 19,25 (không phải 0); không có bằng chứng mới.
6. **Sửa một ngày đã chốt:** chưa có quy trình (có kiểm soát, có audit). Hiện không có cách sửa ngoài khôi phục bản sao lưu.

### 13. Xác nhận phạm vi

- Không commit, không push, không chạy `release.ps1`, không đóng gói, không deploy.
- Không train, không promote, không chạy D-0 / D-1 / EOD / chốt / backfill / chốt actual trên production; không đổi lịch chạy, `storage.json`, cấu hình hay model đang dùng.
- Không ghi vào DB production hay BigQuery. DB production chỉ được đọc một lần (21:20–21:22) bằng backup API ở chế độ chỉ đọc để tạo bản sao.
- GET production lúc 21:17, 22:28 và 22:35:
  - bản 1.2.8 (`current.txt` 1.2.8);
  - `storage.json` `8D79DBDDC960B10964F3B137F352D9AD54D39F08C52EF841418781ED00FDE047`;
  - không có job đang chạy; job mới nhất vẫn là D-0 19:14 (bù slot 18:00, do bộ lập lịch chạy);
  - tác vụ nền `bfdeqbpps` của đợt deploy 1.2.8 không bị đụng tới.
- Price ON, customer_id OFF; lịch D-0 giữ nguyên; `MULTI_ITEM` và 931 khóa không bị đổi.

### 14. Bước tiếp theo và bằng chứng cần xem

**Bạn cần xem:**

1. Báo cáo này, mục 1 và mục 12.
2. File `reports/demandforecast_upgrade_backfill_rehearsal_20261020_per_day.csv`: chênh lệch backfill theo từng ngày (−12.109; 10/10 lệch nhiều nhất −1,33%).
3. Bốn ảnh trong `reports/demandforecast_upgrade_backfill_rehearsal_20261020_screens/`.

**Bạn cần quyết định:**

1. Cách giữ thứ tự backfill / chốt: (a) quy trình hay (b) công tắc trong code.
2. Có cho phép commit không (bước riêng).
3. Quy tắc `MULTI_ITEM`. Không cần cho việc nâng cấp và chốt, nhưng cần cho training 1.2.9.

**Sau khi được phép commit, tôi sẽ:**

1. Commit các thay đổi đã duyệt.
2. Đổi chuỗi phiên bản sang 1.2.9.
3. Chạy `release.ps1`.
4. Diễn tập bằng gói trên bản cài cô lập: `deploy-upgrade -CheckOnly`, nâng cấp 6 → 9 trên bản sao, `rollback-version` từ chối schema 9, khôi phục.
5. Gửi kế hoạch triển khai và giờ chạy để bạn duyệt.

Không bước nào trong số này được thực hiện khi chưa có xác nhận của bạn.

## 4. Data reconciliation - fix 7.1 / release 1.2.10 (21/10/2026)

Nguồn: `reports\fix71-restore-d1-20261021\DATA_RECONCILIATION.md` (worktree MAIN).

Mọi số liệu BigQuery là truy vấn **chỉ đọc** (dry-run trước, `maximum_bytes_billed` 2 GiB mỗi truy vấn của kiểm toán),
trên **một snapshot**: bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm` dựng lại **21/10/2026 07:10:38**
(giờ VN; `modified` UTC `2026-10-21 00:10:38.658`), 8.979.752 dòng, 1.695.466.952 byte, không phân vùng / clustering.
Metadata đọc trước và sau mỗi bộ truy vấn: không đổi (`same_snapshot = true`). Phía app: bản sao DB production làm bằng SQLite
backup API (nguồn mở `mode=ro`) trong scratchpad, hoặc DB của môi trường diễn tập cô lập. Không có `customer_id` thô nào rời
BigQuery (chỉ đếm số khách khác nhau). Workbook bằng chứng 7 sheet: xem mục 6.

### 1. Snapshot nguồn đã đổi so với các báo cáo trước

| Snapshot | Dòng bảng | Dòng 01/01-19/10 | Có 20/10 | Ghi chú |
|---|---:|---:|---|---|
| 20/10 22:18:39 (master audit) | 8.961.545 | 8.961.545 | không | 18 nhóm / 67 dòng "trùng" (16/10, 19/10) |
| **21/10 07:10:38 (đợt này)** | **8.979.752** | **8.961.544** | **18.208 dòng** | 46 nhóm / 136 dòng "trùng" (16/10, 19/10, 20/10) |

D-1 06:00 sáng 21/10 trên 1.2.8 (`JOB-20261020230002-325754`, 4/4 lần) dừng **SOURCE_INCOMPLETE** (0 dòng của 20/10 lúc
06:00-06:38; nguồn dựng lại lúc 07:10) - chưa tới cổng trùng. Với snapshot 07:10, mọi lần đọc có 16/10, 19/10 hoặc 20/10 trên
1.2.8 sẽ dừng `BQ_DATA_DUPLICATES`.

### 2. Phân loại các dòng bị cổng trùng đánh dấu (snapshot 07:10, 01/01-20/10)

Định nghĩa của cổng: dòng giống nhau ở **15 cột ánh xạ** (`so_code, created_date, sku_code, fc_code, demand_quantity,
sales_price, product_id, item_code, outbound_quantity, order_status, seller_code, sku_system_status, open_date,
total_open_hours, total_open_days`). Cột nguồn không ánh xạ: `customer_id, seller_class, refresh_time`.

| Lớp | Nhóm | Dòng | Dòng dư (quy tắc cũ) | Số lượng | Tiêu chí |
|---|---:|---:|---:|---:|---|
| Trùng thật (có `so_code`, hoặc NULL ở trạng thái khác) | **0** | 0 | 0 | 0 | quy tắc cột ánh xạ, chặn |
| Chưa đủ bằng chứng (giống nhau ở MỌI 18 cột nguồn: trùng thật hoặc nhân dòng do join) | **0** | 0 | 0 | 0 | so toàn dòng, chặn |
| **Đơn riêng hợp lệ** (WAIT_TO_CONFIRM, `so_code` NULL, khác nhau ở toàn dòng nguồn) | **46** | **136** | 90 | 2.791 | mỗi nhóm: số khách khác nhau = số dòng, 0 khách NULL |
| Trong phạm vi backfill 01/01-19/10 | 18 | 65 | 47 | - | 16/10 (4 nhóm HN), 19/10 (13 BD + 1 HN) |
| Ngày 20/10 | 28 | 71 | 43 | - | 20 BD + 8 HN |

Khác:
- `so_code` NULL chỉ có ở `WAIT_TO_CONFIRM`: 904 dòng / 12.933 đơn vị, 6 ngày (12/07 .. 20/10). Không trạng thái nào khác có
  `so_code` NULL.
- Dòng giống nhau ở **mọi** cột nguồn (toàn bảng 01/01-20/10): **0** (cả dòng chờ xác nhận lẫn dòng khác).
- Nhiều dòng của **một đơn x SKU x FC x ngày** (có mã đơn), các dòng khác nhau: 7.008 khóa / 14.169 dòng (tối đa 4 dòng);
  được cộng theo quy tắc SUM_ALL của chủ hệ thống (16/10), không phải trùng hoàn toàn. Nếu một join phía nguồn nhân dòng mà
  các bản sao khác nhau ở cột của bảng được join, app không phân biệt được (không có dòng gốc) - rủi ro còn lại, không quan sát
  được bằng dữ liệu hiện có.
- Join phía app: cổng trùng đọc dòng thô (không join). Truy vấn D-1 chỉ có một join (đếm khách, chỉ khi ánh xạ cột khách -
  đang TẮT) theo đủ khóa ngày x SKU x FC, một dòng mỗi khóa (test thật: bật / tắt cho cùng số dòng và số lượng).

Cổng trùng **của app 1.2.10** (SQL thật của app, ánh xạ production) trên cùng snapshot 01/01-20/10: 8.979.752 dòng,
42.088.223 đơn vị, **0 nhóm trùng**, 904 dòng chờ xác nhận (12.933), 46 nhóm / 136 dòng giống ở cột ánh xạ, **0** nhóm giống ở
mọi cột - khớp phân loại độc lập.

### 3. Tổng nguồn của phạm vi backfill (01/01-19/10, snapshot 07:10, SQL độc lập)

| Chỉ số | Giá trị |
|---|---:|
| Dòng nguồn hợp lệ (sku, fc, qty không NULL, qty >= 0) | 8.961.544 |
| Khóa ngày x SKU x FC | 1.357.876 |
| Số lượng (`demand_quantity`) | 42.009.957 |
| Ngày | 292 |
| Dòng chờ xác nhận không mã (giữ nguyên) | 289 / 6.068 đơn vị |

### 4. Production TRƯỚC backfill so với nguồn (bản sao production 21/10 ~09:56, 1.2.8, schema 6)

| Chỉ số | Giá trị |
|---|---:|
| Khóa app (BIGQUERY, 01/01-19/10) | 1.358.317 |
| Số lượng app | 42.023.217 |
| Khóa mới (chỉ có ở nguồn) | 344 (+4.408 đơn vị) |
| Khóa mất (chỉ có ở app; nguồn không còn) | 785 (-14.495 đơn vị) |
| Khóa đổi số lượng | 309 (-3.173 đơn vị) |
| Khóa không đổi | 1.357.223 |
| Chênh số lượng nguồn - app | **-13.260 (-0,032 %)** |
| Ngày có chênh lệch | 273 / 292 |

Phân bố: khóa mới / mất trải đều tháng 1-10 (mất: 33-130 khóa mỗi tháng); khóa đổi tập trung tháng 10 (239 khóa, -3.147).
Cùng hiện tượng đã ghi từ 16/10 (nguồn viết lại lịch sử mỗi lần dựng lại; D-1 chỉ đọc lại 3 ngày gần nhất). Snapshot 22:18
cho 344 / 308 / 785 / -13.255: snapshot 07:10 chỉ khác 1 khóa đổi, -5 đơn vị.

Bản sao production lúc 12:29 (sau deploy 1.2.10 và preview, trước backfill) cho đúng cùng các số trên; preview của app
`BFP-20261021051921-51731D` cũng vậy (`series_days_new 344 / updated 309 / removed 785 / unchanged 1.357.223`,
`qty_change -13.260`, `rows_stored_in_window 1.358.317`, `qty_stored_in_window 42.023.217`).

### 5. Sau backfill (production 1.2.10)

Backfill `JOB-20261021052939-2D9CCE` (preview trên, cùng snapshot 07:10 - metadata kiểm lại trước và sau): đọc 8.961.544
dòng / 42.009.957 đơn vị, 0 trùng hoàn toàn, 7.241 dòng lặp khóa (cộng theo SUM_ALL), ghi 1.357.876 khóa = số khóa đọc
(kiểm tra trong giao dịch), giờ mở bán OK 1.357.870 / MULTI_ITEM 6.

| Chỉ số (01/01-19/10) | App | Nguồn | Chênh |
|---|---:|---:|---:|
| Khóa ngày x SKU x FC | 1.357.876 | 1.357.876 | 0 |
| Số lượng | 42.009.957 | 42.009.957 | 0 |
| Khóa mới / mất / đổi | - | - | 0 / 0 / 0 |
| Ngày có chênh lệch | - | - | 0 |

Đối soát độc lập trên bản sao production lúc 12:47 (`recon71.py`): **khớp tuyệt đối** (`match = true`). Chốt actual: 292 ngày
(01/01-19/10) từ tải backfill (`load_id` của job), 0 chặn. Close 23:59 có lý do `D1_RELOADED`: 18/10 revision 4
(57.532 -> 57.340), 19/10 revision 3 (90.786 -> 89.862); các revision cũ giữ nguyên.

D-1 dry run sau backfill (cửa sổ 16/10-20/10, chưa ghi): cổng trùng 0 nhóm; 892 dòng chờ xác nhận không mã trong cửa sổ, 136
giống nhau ở cột ánh xạ (46 nhóm, đơn riêng), 0 giống mọi cột. Diễn tập r11 cùng cửa sổ: D-1 thật ghi 15.115 khóa (20/10: 3.037
khóa mới, 16-19/10 không đổi), 385.502 đơn vị, 0 trùng.

### 6. Hiện vật

| File | SHA-256 |
|---|---|
| `demandforecast_fix71_duplicates_reconciliation_20261021.xlsx` (thư mục này; 7 sheet) | `561FB23AD5E9F9EC05D9FD33D61EDC777CD2BD41867FADA917F9B3368FD52A20` |
| Kết quả JSON (scratchpad p26): `audit71_0815.json` (phân loại), `app_sql71.json` (cổng 1.2.10 trên bảng thật), `src_agg_0710_0101_1019.json.gz` (tổng nguồn theo khóa), `recon_prod_before.json`, `state\recon_before.json`, `state\recon_after.json`, `state\preview.json`, `state\backfill_job.json`, `state\ingest_check.json` | trong `checkpoints\checkpoint-20261021-fix71-after.zip` |

## 5. Fix 7.1 - khôi phục D-1 an toàn: phát hành 1.2.10 (21/10/2026)

Nguồn: `reports\fix71-restore-d1-20261021\FINAL_REPORT.md` (worktree MAIN).

**Trạng thái: READY_FOR_PRODUCTION - đã triển khai và xác minh (DEPLOYED_AND_VERIFIED).** Production chạy **1.2.10** từ
21/10/2026 12:18:48; preview → backfill 01/01-19/10 → đối soát → chốt actual đã chạy theo đúng thứ tự, đối soát khớp tuyệt đối
với nguồn. Chưa có lần D-1 thật nào chạy trên 1.2.10 (lần kế tiếp: lịch 22/10 06:00); D-1 dry run trên production: READY.
Còn 2 việc cần chủ hệ thống (mục 9). Đọc kèm: TEST_RESULTS.md, DATA_RECONCILIATION.md, RESUME_CHECKPOINT.md (cùng thư mục).

### 1. Root cause và code diff của item 7.1

**Triệu chứng.** D-1 production 1.2.8 không nạp được dữ liệu sau 19/10: mọi lần đọc chứa 16/10, 19/10 hoặc 20/10 dừng
`BQ_DATA_DUPLICATES`. Bằng chứng production: D-1 thủ công lúc 09:36 hôm nay (`JOB-20261021023641-FAB4DD`) FAILED
`BQ_DATA_DUPLICATES`, `groups=46 rows=136 extra=90 range=2026-10-16..2026-10-20`. (D-1 lịch 06:00 hôm nay dừng sớm hơn ở
`SOURCE_INCOMPLETE`: nguồn chỉ có 20/10 sau lần dựng lại 07:10.)

**Nguyên nhân gốc.** Cổng trùng hoàn toàn (BLOCK) coi hai dòng là trùng khi giống nhau ở mọi cột **ánh xạ** (15 cột), NULL =
NULL. Đơn `WAIT_TO_CONFIRM` chưa được cấp `so_code` (NULL là bình thường): đơn của nhiều khách cùng ngày x SKU x FC x số lượng
x giá thì giống nhau ở 15 cột, chỉ khác ở cột **không ánh xạ** `customer_id`. Gói 1.2.8 / 1.2.9 vì vậy chặn cả đơn riêng hợp lệ.

**Sửa (commit `dd0dfa1`, 20 file).**
- Master audit (sáng 21/10, chưa phát hành) đã miễn trừ *mọi* dòng chờ xác nhận không mã khỏi phép đếm trùng. Đợt này phát
  hiện điểm yếu của cách đó: hai dòng chờ xác nhận giống nhau ở **mọi** cột nguồn (trùng thật hoặc nhân dòng do join) cũng
  không bao giờ bị phát hiện - đi ngược yêu cầu "không nới cổng trùng để PASS giả".
- **Sửa 7.1** (`backend/app/bq/connector.py`): dòng chờ xác nhận không mã được so trên **toàn bộ dòng nguồn** - cột `_praw`
  = `IF(<so_code NULL và trạng thái WAIT_TO_CONFIRM>, TO_JSON_STRING(<dòng nguồn>), NULL)` trong CTE nguồn (`_src_cte`,
  `_pending_raw_expr`); dòng nguồn không rời BigQuery, chỉ được nhóm / đếm. Áp dụng thống nhất ở cổng trùng (`_dup_sql`:
  `GROUP BY <15 cột>, _praw`), kiểm tra toàn kỳ (`_validation_sqls`), dòng kiểm soát D-1 (`TOTAL_READ`) và `DROP_EXACT`.
  - khác nhau ở bất kỳ cột nguồn nào -> **đơn riêng**: giữ, cộng, đếm riêng (`pending_no_order_code`), không chặn;
  - giống nhau ở **mọi** cột nguồn -> **chưa đủ bằng chứng** -> vẫn là trùng hoàn toàn: chặn, báo cáo Excel ghi
    `compared_on = whole source row`, đếm `pending_no_order_code.duplicate_*`;
  - mọi dòng khác (có mã, hoặc NULL ở trạng thái khác) giữ nguyên quy tắc 15 cột; không cột nào (kể cả `customer_id`) là khóa.
- `dup_report.py` (Summary + cột `compared_on`), trang BigQuery (dòng "giống nhau ở mọi cột nguồn"), tài liệu
  (`docs/02_kien_truc_du_lieu/BIGQUERY.md` §13, `docs/02_kien_truc_du_lieu/DATA-MODEL.md`), CHANGELOG 1.2.10, phiên bản 1.2.10.
- Kèm theo (master audit, đã có test): 3 truy vấn đọc toàn phạm vi chạy `NOT INDEXED` (danh mục đặc trưng, lineage,
  `load_demand`) - kết quả giống hệt.
- Chi phí: khi `order_id` và `order_status` được ánh xạ, cổng trùng và truy vấn tổng hợp đọc mọi cột: 1,70 GB thay vì 1,35 GB
  mỗi truy vấn (bảng không phân vùng).

### 2. Duplicate trước / sau (snapshot nguồn 21/10 07:10, 01/01-20/10)

| | 1.2.8 / 1.2.9 (quy tắc cũ) | 1.2.10 |
|---|---|---|
| Nhóm / dòng bị đánh dấu | 46 nhóm / 136 dòng (90 dòng dư) | **0** nhóm |
| Trùng thật (có mã / trạng thái khác) | 0 | 0 |
| Chưa đủ bằng chứng (giống mọi cột nguồn) | - (không phát hiện được) | 0 (sẽ chặn nếu có) |
| Đơn riêng hợp lệ (mỗi dòng một khách, khác toàn dòng) | bị coi là trùng | 46 nhóm / 136 dòng / 2.791 đơn vị: giữ |
| Kết quả cổng | `BQ_DATA_DUPLICATES` (production 09:36) | PASSED (preview, backfill, D-1 dry run) |

Phạm vi backfill 01/01-19/10: 18 nhóm / 65 dòng (47 dư) theo quy tắc cũ, 0 theo 1.2.10. Chi tiết: DATA_RECONCILIATION.md mục 2,
workbook mục 8.

### 3. Rows / keys / quantity / đối soát (01/01-19/10)

| | Rows nguồn | Keys | Quantity |
|---|---:|---:|---:|
| Nguồn (SQL độc lập, snapshot 07:10) | 8.961.544 | 1.357.876 | 42.009.957 |
| Production trước backfill | - | 1.358.317 | 42.023.217 |
| Preview production `BFP-20261021051921-51731D` | 8.961.544 đọc, 0 trùng | 1.357.876 | 42.009.957 |
| Khác biệt trước backfill | mới **344** (+4.408) / đổi **309** (-3.173) / mất **785** (-14.495) / không đổi 1.357.223 | | **-13.260 (-0,032 %)** |
| Backfill `JOB-20261021052939-2D9CCE` | ghi 1.357.876 = đọc | 1.357.876 | 42.009.957 |
| Production sau backfill (đối soát độc lập trên bản sao) | - | **1.357.876** | **42.009.957** |
| Chênh sau backfill | mới 0 / mất 0 / đổi 0 - **khớp tuyệt đối** | | 0 |

Đối soát độc lập (`recon71.py`, không dùng mã app) trước backfill = preview của app (344 / 309 / 785 / -13.260); 3 nguồn số
(app preview, đối soát độc lập, diễn tập r11) trùng nhau.

### 4. Test (chi tiết + lệnh + log: TEST_RESULTS.md)

| Bộ | Kết quả |
|---|---|
| Backend toàn bộ (working tree) | 663 passed / 15 skipped / 0 failed |
| QA của `release.ps1` trên commit `dd0dfa1` | backend 663 passed / 15 skipped; vitest 155 passed; typecheck + build OK |
| BigQuery thật trên dòng inline (opt-in, 0 byte) | 10 passed |
| Cổng 1.2.10 trên bảng thật (chỉ đọc) | 0 nhóm trùng, 0 giống mọi cột |
| Diễn tập cô lập r10 (nâng cấp + rollback) | 28/31 (3 FAIL do script diễn tập: thiếu header `X-DF-Client` ở POST, trường status mới `start_rule`) |
| Diễn tập cô lập r11 (toàn chuỗi) | **40/40 PASS** |
| Production sau triển khai (`post1210.ps1`) | 11/12; FAIL duy nhất = so JSON thiết lập: 1.2.10 chỉ **thêm** trường mặc định (`model.feature_open_hours`, `weekday_encoding`, `feature_customer=false`, `data_policy.training_start_rule=WINDOW_START`), không giá trị cũ nào đổi |
| Lint | not configured |

### 5. Production trước / sau, gói, backup, health

| Mục | Giá trị |
|---|---|
| Trước | **1.2.8**, schema 6, PID 10884 (từ 19/10 20:08) |
| Sau | **1.2.10**, schema 9, PID 30096; `GET /api/health` -> `{"ok":true,"version":"1.2.10"}`; `current.txt` 1.2.10; scheduler chạy |
| Gói | `dist\DemandForecast-1.2.10-win64-portable.zip` SHA-256 `326E358799B911607C84E693374212839B5BC86F259798AE08D18A5B37724E62` (92.366.426 byte, commit `dd0dfa1`, dirty=false, source fingerprint `2D7025F4...68C2`; 7.169 mục, không dữ liệu / credential / `__pycache__`, 74 file `.py` = git) |
| Backup đã xác minh trước deploy | `D:\Buymed\Lightgbm AI\backups\backup-20261021-120556-manual.zip` SHA-256 `6DE2BA719B873A7355B8844312EA1DAE90901E7420A982DFAECBC8F7B2F1BC46` - CRC, `integrity_check` ok, schema 6, đủ model, có forecast / training / job hôm nay |
| Backup của deploy-upgrade | `backup-20261021-121031-manual.zip` SHA-256 `AEFEA7516817286728A20CFFCDF6B3098E209838C4BA10580B125274C968601F` - xác minh lại: ok, schema 6 |
| Backup trước migration / sau cài | `backup-20261021-121514-pre-migration-v6.zip`, `backup-20261021-121614-cli.zip` (do install tạo) |
| Backup trước backfill | `backup-20261021-123506-pre-backfill.zip` SHA-256 `978F86D26D71E892C3470FDE736EAF954312D57551F3327445DE72CDCDDCC14E` (97.216.998 byte) - xác minh: ok, schema 9 |
| Thời gian | deploy 12:09:43-12:18:52 (548 s), app gián đoạn ~12:11:50-12:18:50 (~7 phút), không trùng lịch nào (D-0 12:00 đã xong, kế tiếp 14:00) |
| Bất biến | `storage.json` SHA-256 `8D79DBDD...E047` không đổi; 5 lịch (D-1 06:00/06:30, D-0 08-18h mỗi 2 h, huấn luyện 07:00, EOD 23:55, close 23:59) không đổi; Price ON; `customer_id` OFF; ánh xạ (target `demand_quantity`), `exact_duplicate_policy=BLOCK`, bảng nguồn, production ON không đổi; forecast đang dùng `FCR-20261020082402-A42C91` / model `TRN-20261020054540-D7EEF6` không đổi; không huấn luyện, không promote |
| Smoke production | 14 GET đều 200: dashboard 13,0 s (lần đầu), status 2,3 s, danh mục đặc trưng 3,9 s (1.2.8: trung vị 13,5 s), history summary 1,8 s, Excel lịch sử 67 s, forecast 0,5 / 1,6 s |
| data-check (chỉ đọc, bản 1.2.10) | WARN (không FAIL): `open_hours_window_ready` (6 khóa MULTI_ITEM), `forecast_series_meta` |

### 6. Trạng thái các bước

| Bước | Trạng thái | Bằng chứng |
|---|---|---|
| 1. Backup / checkpoint mới | DONE | checkpoint trước sửa `checkpoints\checkpoint-20261021-fix71-before.zip` (`C0BBE916...4713`); backup xác minh 120556 |
| 2. Deploy + version + health | DONE | deploy-upgrade exit 0, `UPGRADE OK: 1.2.8 -> 1.2.10`, health 1.2.10 |
| 3. Preview trên snapshot hiện tại | DONE - READY | `BFP-20261021051921-51731D` (12:19-12:28), 0 trùng, cảnh báo: không |
| 4. Backfill 01/01-19/10 | DONE | `JOB-20261021052939-2D9CCE` SUCCEEDED `BACKFILL_DONE` 12:29:39-12:46:11 (1.004 s) |
| 5. Đối soát | DONE - khớp tuyệt đối | mục 3 |
| 6. Chốt actual (finalization) | DONE | hook sau backfill: **292 ngày** chốt, 0 chặn, 0 lỗi (12:46:08); close 23:59 sửa đổi có lý do `D1_RELOADED`: 18/10 rev 4 (57.532 -> 57.340), 19/10 rev 3 (90.786 -> 89.862); revision cũ giữ nguyên |
| 7. Smoke API / dashboard / actuals / export | DONE | mục 5 |
| 8. D-1 chạy lại an toàn | VERIFIED (dry run) | `POST /api/bigquery/ingest-check` 12:48: READY, mọi bước PASSED, cổng trùng 0 nhóm, 892 dòng chờ xác nhận trong cửa sổ 16-20/10 (136 giống cột ánh xạ, 0 giống mọi cột), `write=NOT_RUN`. D-1 thật trên 1.2.10 đã diễn tập trên bản sao (r11: 16-20/10, 15.115 khóa, 20/10 mới 3.037 khóa, 0 trùng, chốt 293 ngày). D-1 thật trên production: chưa chạy (lịch 22/10 06:00) |
| 9. Rollback readiness | READY | `rollback-version -To 1.2.8 -CheckOnly` từ chối đúng (exit 3, schema 9 > 6): rollback = `restore.ps1` của 1.2.8 với `backup-20261021-121031-manual.zip` (hoặc 120556) rồi `rollback-version -To 1.2.8` - diễn tập 2 lần (r10 sau nâng cấp, r11 sau backfill + D-1): bảng giống hệt trạng thái trước deploy. Rollback làm mất mọi thứ ghi sau 12:10 (backfill, chốt actual, D-0 sau đó) |
| Huấn luyện / promote | KHÔNG chạy | huấn luyện lịch hôm nay vẫn chờ D-1 hôm nay (backfill không được tính) |

Ghi chú vận hành: trong lúc backfill ghi, scheduler hoãn 5 tick (`SCHEDULER_TICK_DEFERRED`, DB bận) - không có lịch nào đến
hạn. Script chuỗi production có 2 lỗi của chính script (biến `$s` / `$S` trùng tên trong PowerShell làm POST preview đầu
tiên bị 422 không chạy gì; đường dẫn kết quả job) - đã sửa trước khi backfill; app không ghi gì ở lần 422.

### 7. Workbook và hiện vật

| File | SHA-256 |
|---|---|
| `reports\fix71-restore-d1-20261021\demandforecast_fix71_duplicates_reconciliation_20261021.xlsx` (7 sheet: Summary, Affected_Rows, Business_Keys, Reasons, Expected_vs_Actual, Reconciliation, Evidence; không có customer_id thô) | `561FB23AD5E9F9EC05D9FD33D61EDC777CD2BD41867FADA917F9B3368FD52A20` |
| `dist\DemandForecast-1.2.10-win64-portable.zip` | `326E358799B911607C84E693374212839B5BC86F259798AE08D18A5B37724E62` |
| `checkpoints\checkpoint-20261021-fix71-before.zip` | `C0BBE91681E6B5C3105C3C9B26F9FC8AE55A339403EF1C9ED463CD6FE3304713` |
| `checkpoints\checkpoint-20261021-fix71-after.zip` | xem `.sha256` cạnh zip và RESUME_CHECKPOINT.md |
| Báo cáo trùng do production 1.2.8 tạo lúc 09:36: `reports\bigquery-duplicates\bq-trung-lap_2026-10-16_2026-10-20_20261021-093647.xlsx` | (21.570 byte, tạo bởi app) |
| Script / kết quả: scratchpad `p26` (`bq_audit71.py`, `bq_app_sql71.py`, `src_agg71.py`, `recon71.py`, `iso1210r.ps1`, `deploy1210.ps1`, `prodchain1210.ps1`, `post1210.ps1`, `state\*`) | trong checkpoint after |

### 8. Blocker / rủi ro chưa giải quyết

1. **Huấn luyện BIGQUERY bị chặn bởi 6 khóa MULTI_ITEM** (quy tắc giờ mở bán bắt buộc của 1.2.9): danh mục đặc trưng báo
   `next_training.blocked_by = OPEN_HOURS_INVALID` (6 dòng, 09/02-26/08). Huấn luyện lịch 22/10 07:00 (sau D-1 thành công) sẽ
   dừng với lỗi này cho tới khi chủ hệ thống chọn quy tắc gộp (MA-03). Forecast đang dùng không bị ảnh hưởng.
2. **Giờ D-1 so với giờ nguồn dựng lại**: hôm nay nguồn có 20/10 lúc 07:10, sau lần thử cuối của D-1 (06:38) -> D-1 06:00 dừng
   `SOURCE_INCOMPLETE`. Nếu ngày mai tương tự, 20-21/10 chỉ được nạp khi có D-1 thủ công. Không đổi lịch (ngoài phạm vi).
3. **Lịch sử nguồn bị viết lại** (785 khóa mất, 344 mới, 309 đổi, -13.260): backfill đã làm app khớp nguồn hiện tại theo quyết
   định backfill-trước của chủ hệ thống (20/10); 292 ngày nay đã chốt từ tải này. Nhóm nguồn chưa xác nhận lý do (MA-06).
4. Rủi ro còn lại của quy tắc: hai dòng nhân do join phía nguồn mà khác nhau ở cột của bảng được join vẫn là hai dòng (app
   không có dòng gốc để so); cổng trùng / tổng hợp đọc 1,70 GB mỗi truy vấn (bảng không phân vùng).
5. Remote link: cloudflared `/ready` trả 503 trước triển khai (không thuộc đợt này, không đụng tới).

### 9. Việc tiếp theo nhỏ nhất (ai làm)

1. **Chủ hệ thống**: chọn quy tắc cho 6 khóa MULTI_ITEM (hoặc chấp nhận huấn luyện dừng) trước 22/10 07:00.
2. **Chủ hệ thống**: nếu muốn có 20/10 ngay hôm nay, bấm "Chạy ngay" D-1 (đã dry run READY); nếu không, D-1 lịch 22/10 06:00.
3. **Claude (khi được duyệt)**: push `dd0dfa1` + commit tài liệu; theo dõi D-1 22/10 và đối chiếu chốt actual 20-21/10.

## 6. Resume checkpoint - fix 7.1 / release 1.2.10 (21/10/2026)

Nguồn: `reports\fix71-restore-d1-20261021\RESUME_CHECKPOINT.md` (worktree MAIN).

### Trạng thái (21/10/2026 ~13:00)

- Production: **1.2.10**, schema 9, `http://127.0.0.1:8765` (PID 30096), cài đặt `%LOCALAPPDATA%\Programs\DemandForecast\1.2.10`,
  `current.txt` 1.2.10; thư mục 1.2.8 giữ nguyên để rollback. `storage.json` SHA-256 `8D79DBDD…E047` không đổi.
- Dữ liệu BIGQUERY 01/01-19/10 = nguồn snapshot 21/10 07:10 (1.357.876 khóa, 42.009.957 đơn vị); 292 ngày đã chốt actual từ
  tải backfill. 20/10 **chưa** nạp (chưa có D-1 thật trên 1.2.10).
- Lịch không đổi: D-1 06:00 / 06:30, D-0 08-18 h mỗi 2 h (kế tiếp 14:00), huấn luyện 07:00 (SKIP khi lỡ), EOD 23:55, close 23:59.
- Không huấn luyện, không promote; forecast đang dùng `FCR-20261020082402-A42C91` (model `TRN-20261020054540-D7EEF6`).
- Git: `main` tại `dd0dfa1` "Release 1.2.10" (+ commit tài liệu CHECKPOINT nếu có, xem `git log`), **chưa push**.

### Hiện vật

| Hiện vật | Vị trí | SHA-256 |
|---|---|---|
| Gói | `dist\DemandForecast-1.2.10-win64-portable.zip` | `326E358799B911607C84E693374212839B5BC86F259798AE08D18A5B37724E62` |
| Backup xác minh trước deploy | `backups\backup-20261021-120556-manual.zip` | `6DE2BA719B873A7355B8844312EA1DAE90901E7420A982DFAECBC8F7B2F1BC46` |
| Backup của deploy-upgrade (điểm rollback) | `backups\backup-20261021-121031-manual.zip` | `AEFEA7516817286728A20CFFCDF6B3098E209838C4BA10580B125274C968601F` |
| Backup trước backfill (schema 9) | `backups\backup-20261021-123506-pre-backfill.zip` | `978F86D26D71E892C3470FDE736EAF954312D57551F3327445DE72CDCDDCC14E` |
| Checkpoint trước sửa | `checkpoints\checkpoint-20261021-fix71-before.zip` | `C0BBE91681E6B5C3105C3C9B26F9FC8AE55A339403EF1C9ED463CD6FE3304713` |
| Checkpoint sau (báo cáo + script + kết quả + state) | `checkpoints\checkpoint-20261021-fix71-after.zip` | file `.sha256` cạnh zip; ghi trong `docs\03_van_hanh\CHECKPOINT.md` |
| Workbook bằng chứng | `reports\fix71-restore-d1-20261021\demandforecast_fix71_duplicates_reconciliation_20261021.xlsx` | `561FB23AD5E9F9EC05D9FD33D61EDC777CD2BD41867FADA917F9B3368FD52A20` |
| Scratchpad (tạm thời) | `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p26\` (+ `r10`, `r11` môi trường diễn tập) | - |

### Rollback (chỉ khi cần, theo quy trình đã diễn tập r10 / r11)

```powershell
# 1.2.10 tự từ chối rollback không restore (schema 9 > 6):
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\scripts\rollback-version.ps1" -To 1.2.8 -CheckOnly   # exit 3
# Rollback = dừng 1.2.10, restore bản backup trước nâng cấp bằng restore.ps1 của 1.2.8, rồi rollback-version:
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\scripts\stop.ps1"
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.8\scripts\restore.ps1" -File "D:\Buymed\Lightgbm AI\backups\backup-20261021-121031-manual.zip"
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\scripts\rollback-version.ps1" -To 1.2.8 -ConfirmToken ROLLBACK-1.2.8
```

Mất dữ liệu khi rollback: mọi thứ ghi sau 12:10 (backfill, 292 ngày chốt, revision close 18-19/10, D-0 / D-1 sau đó). 1.2.8
trở lại sẽ lại bị chặn `BQ_DATA_DUPLICATES` với nguồn hiện tại.

### Lệnh kiểm tra nhanh (chỉ đọc)

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health                       # version 1.2.10
Invoke-RestMethod "http://127.0.0.1:8765/api/jobs?limit=5"                # D-1 22/10 06:00
Invoke-RestMethod http://127.0.0.1:8765/api/history/overview              # finalization: 292 (+ ngày mới sau D-1)
cd "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\backend"; ..\python\python.exe -m app.cli data-check   # WARN, không FAIL
```

### Việc tiếp theo

1. Chủ hệ thống: quy tắc 6 khóa MULTI_ITEM (huấn luyện BIGQUERY đang bị `OPEN_HOURS_INVALID` chặn).
2. Chủ hệ thống: D-1 thủ công hôm nay nếu cần 20/10 ngay; nếu không, D-1 lịch 22/10 06:00 (có thể `SOURCE_INCOMPLETE` nếu nguồn
   dựng lại sau 06:38 như hôm nay).
3. Push `main` (`dd0dfa1` + tài liệu) khi được duyệt.

## 7. Test results - fix 7.1 / release 1.2.10 (21/10/2026)

Nguồn: `reports\fix71-restore-d1-20261021\TEST_RESULTS.md` (worktree MAIN).

Nhãn loại: **unit** (DB tạm, không gọi ngoài), **integration-fake** (FakeBQ / TestClient), **real external** (BigQuery
thật; dòng inline 0 byte, hoặc bảng nguồn thật chỉ đọc), **DB copy** (bản sao production cô lập), **isolated install**
(gói chính thức cài trong `LOCALAPPDATA` riêng trên bản sao DB). Log trong scratchpad
`C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p26\`.

### 1. Bộ test đầy đủ

| Lệnh | Thời điểm | Kết quả | Thời lượng | Log |
|---|---|---|---|---|
| `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` (working tree trước commit) | 09:35-09:52 | **663 passed, 15 skipped, 0 failed**, 1 warning (Starlette httpx, có từ trước) | 1.008,9 s (chạy song song với frontend + truy vấn BigQuery) | `test_backend_full.log` |
| `cd frontend; npm test; npm run typecheck; npm run build` | 09:35-09:38 | **25 file, 155 passed**; typecheck exit 0; build exit 0 (`index-CWFdCJhm.js` 684,53 kB, gzip 208,14 kB) | ~3 phút | `test_frontend.log` |
| `scripts\release.ps1` (QA = `scripts\run-tests.ps1` trên commit `dd0dfa1`, cây sạch, rồi build + kiểm tra gói) | 10:01-10:23 | backend **663 passed, 15 skipped**; vitest **155 passed**; build OK; gói 1.2.10 tạo + xác minh; prune chỉ dry run (không xóa gì) | 633 s backend; tổng 22 phút | `release1210.log` |
| Lint | - | **not configured** (không có trong dự án) | - | - |

15 test bỏ qua = test opt-in BigQuery thật / D-0 thật (`DF_REAL_BQ=1`), gồm 2 test mới của đợt này; chúng được chạy
riêng ở mục 2. So với master audit (661 passed / 13 skipped): +2 offline, +2 opt-in.

### 2. BigQuery thật

| Lệnh / kiểm chứng | Loại | Kết quả | Log / file |
|---|---|---|---|
| `$env:DF_REAL_BQ="1"; pytest tests\test_bq_real_semantics.py tests\test_v129h_real_bq_pending_grain.py tests\test_v129_real_bq_open_hours.py tests\test_v129c_real_bq_items_customers.py tests\test_v129e_real_bq_item_suffix.py` | real external, dòng inline, 0 byte | **10 passed** (55,9 s) | `test_real_bq_inline.log` |
| Cổng trùng 1.2.10 (SQL của app, ánh xạ production) trên bảng thật 01/01-20/10, snapshot 21/10 07:10 | real external, chỉ đọc | 8.979.752 dòng; **0 nhóm trùng**; 904 dòng chờ xác nhận / 12.933 đơn vị; 46 nhóm / 136 dòng giống ở 15 cột ánh xạ; **0** giống ở mọi cột nguồn; 1.695.547.392 byte, 2,6 s | `app_sql71.json` |
| Phân loại độc lập (SQL riêng, không qua app) cùng snapshot | real external, chỉ đọc | 46 nhóm = SEPARATE_ORDERS (mỗi dòng một khách, khác nhau ở toàn dòng); 0 TRUE_DUPLICATE; 0 INSUFFICIENT_EVIDENCE; `so_code` NULL chỉ có ở WAIT_TO_CONFIRM | `audit71_0815.json` |
| Dry-run byte các truy vấn của app 1.2.10 | real external, dry run | cổng trùng / tổng hợp / validate_summary: 1.695.466.952 mỗi truy vấn (trước: ~1,345 GB); validate_days 352.994.748 | `app_sql71.json` |

### 3. Test mới / đổi trong đợt

| File | Thay đổi | Loại | Bao phủ (6 yêu cầu tối thiểu) |
|---|---|---|---|
| `backend/tests/test_v129h_pending_orders_grain.py` | 3 test viết lại theo SQL mới, +2 test mới | unit | (1) WAIT_TO_CONFIRM + so_code NULL không tự là lỗi; (3) dòng chờ xác nhận giống ở MỌI cột nguồn vẫn chặn + báo cáo `compared_on`; (4) join duy nhất là đếm khách theo đủ khóa ngày x SKU x FC, cổng trùng đọc dòng thô; (6) nhóm theo cột FC, không cắt mã SKU |
| `backend/tests/test_v129h_real_bq_pending_grain.py` | dòng inline có cột `customer_id`; +2 test mới | real external (opt-in) | (2) dòng giống ở cột ánh xạ nhưng khác khách được giữ; (3) trùng thật (có mã / NULL trạng thái khác) chặn dù khác khách; dòng chờ xác nhận giống mọi cột chặn, DROP_EXACT bỏ đúng 1; (4) bật đếm khách: số dòng / số lượng / n_rows giống hệt khi tắt; (5) tổng số lượng giữ nguyên; (6) FC từ `fc_code` |
| `backend/tests/test_bq_real_semantics.py` | dòng inline có cột `customer_id` (mỗi dòng một khách), kỳ vọng `not_compared` + khóa mới của `pending_no_order_code` | real external (opt-in) | cặp WAIT_TO_CONFIRM khác khách được giữ; cặp O7 / cặp NULL CONFIRMED khác khách vẫn là trùng (customer_id không phải khóa) |
| `backend/tests/test_v118_bq_ingest.py` | GROUP BY của cổng trùng = các cột ánh xạ + `_praw` | unit | dòng không chờ xác nhận vẫn so trên đúng các cột ánh xạ |
| `frontend/src/v129h-pending.test.tsx` | +1 test | unit (giao diện) | dòng "giống nhau ở mọi cột nguồn (trùng, chặn)" hiện đúng |

Kỳ vọng thay đổi ở 4 file test trên là do hành vi mới có chủ đích (sửa 7.1: dòng chờ xác nhận so trên toàn bộ dòng
nguồn), được chứng minh trên dữ liệu thật (mục 2); không test nào bị xóa hoặc làm yếu.

### 4. Gói, cài đặt cô lập, production

| Kiểm chứng | Loại | Kết quả | File |
|---|---|---|---|
| Nội dung gói 1.2.10 | package | 7.169 mục; VERSION / BUILD-INFO 1.2.10, commit `dd0dfa1`, dirty=false; 0 file cấm (DB, storage.json, credential, `.env`, log, `__pycache__`, `.pyc`); 74 file `backend/app/*.py` giống hệt git HEAD; bundle UI có dòng mới; `testzip` sạch | - |
| Diễn tập r10 (`iso1210r.ps1 -IsoName r10`): 1.2.8 chính thức cô lập trên bản sao DB production -> deploy-upgrade 1.2.10 -> kiểm tra -> rollback bằng restore | isolated install + DB copy | **28/31**: 3 FAIL do script diễn tập (POST thiếu header `X-DF-Client` nên dry run 1.2.8 và preview không chạy; trường status mới `data_window.start_rule` của 1.2.9 - giống r9). Nâng cấp 719 s (gián đoạn 300 s), schema 9, bảng giống hệt, rollback 341 s -> bảng giống hệt trước deploy | `iso1210r_console_r10.txt`, `iso1210r_result.json` |
| Diễn tập r11 (script đã sửa): như r10 + dry run 1.2.8 + preview + đối soát trước + backfill + đối soát sau + chốt actual + D-1 dry run + D-1 thật + smoke + rollback sau backfill | isolated install + DB copy + BigQuery thật (chỉ đọc) | **40/40 PASS**: 1.2.8 dry run: bước trùng BLOCKED; nâng cấp 608 s (gián đoạn 284 s); preview READY 408 s (344 / 309 / 785 / -13.260) = đối soát độc lập; backfill 1.151 s; sau backfill app = nguồn mọi khóa; chốt 292 ngày; D-1 dry run READY; D-1 thật 16-20/10 SUCCEEDED (15.115 khóa, 0 trùng), chốt 293; không huấn luyện; 19 GET smoke 200; rollback 179 s -> bảng giống hệt trước deploy | `iso1210r_console_r11.txt`, `iso1210r_result_r11.json` |
| Cổng production (`deploy1210.ps1 -Mode gates / backup`) | production (chỉ đọc + backup chính thức) | PASS; backup 120556 xác minh (CRC, integrity, schema 6, model, dữ liệu hôm nay) | `state\launcher.log`, `state\backup_verify.json` |
| Deploy production (`-Mode deploy`) | production | exit 0, 548 s, `UPGRADE OK: 1.2.8 -> 1.2.10` | `state\deploy_run.txt` |
| Chuỗi production (`prodchain1210.ps1`) | production + BigQuery thật | preview READY; đối soát trước = preview; backfill SUCCEEDED; đối soát sau khớp tuyệt đối; D-1 dry run READY | `state\chain.log` |
| Kiểm tra sau triển khai (`post1210.ps1`, chỉ GET) | production | 11/12; FAIL = so JSON thiết lập (chỉ trường mới thêm, giá trị cũ không đổi - đã kiểm từng khóa) | `state\post_post.json` |
| data-check bản 1.2.10 (chỉ đọc) | production | WARN, không FAIL | - |
| `rollback-version -To 1.2.8 -CheckOnly` | production (chỉ đọc) | từ chối đúng thiết kế (exit 3, schema 9) | `state\rollback_checkonly.txt` |
| Xác minh backup deploy 121031 / trước backfill 123506 | production backup (chỉ đọc) | ok / ok (schema 6 / 9, integrity ok) | `state\verify_*.json` |

### 5. Không làm để đạt PASS

Không xóa / làm yếu test; không lọc `so_code IS NOT NULL`; không điền mã giả; không xóa WAIT_TO_CONFIRM; không dùng
`customer_id` làm khóa; không nới cổng trùng cho dòng không chờ xác nhận.

## 8. Báo cáo cuối - đồng bộ lịch sử D-1, đơn hủy (release 1.2.13 chuẩn bị, 22/10/2026)

Nguồn: `reports\history-sync-20261022\FINAL_REPORT.md` (worktree MAIN).

**Trạng thái:** `READY_FOR_EXTERNAL_SETUP` - kết luận **PARTIAL**.

### 1. Kết luận: PARTIAL

| Phần | Kết luận | Bằng chứng |
|---|---|---|
| Cơ chế đồng bộ lịch sử (1.2.13) | **FIXED** | 751 test backend đạt (35 test mới). Diễn tập toàn bộ lịch sử trên bản sao production với nguồn BigQuery thật (chỉ đọc): 9/9 khối, chạy lại không đổi gì, rollback khôi phục chính xác, áp lại cho đúng nội dung lần đầu, kiểm tra cuối 294/294 ngày khớp (mục 4) |
| Production | **chưa thay đổi** | Vẫn 1.2.11, DB schema 9, không có bảng mới (mục 9). 1.2.12 và 1.2.13 chưa triển khai; backfill lần đầu trên production cần chủ hệ thống |
| Tổng cầu gồm đơn hủy **trước** lần nạp đầu | **BLOCKED** | Nguồn D-1 không chứa các đơn này. Cần chủ nguồn định nghĩa một nguồn tổng cầu (mục 5) |

### 2. Nguyên nhân gốc (đã kiểm bằng mã và dữ liệu thật)

**Mã nguồn trước 1.2.13:**
- `backend/app/sync.py` `_d1_window`: D-1 chỉ đọc cửa sổ `watermark - late_data_lookback_days (3)` .. hôm qua.
- `run_d1_sync`: `DELETE` toàn bộ dòng của cửa sổ rồi `INSERT` đúng như nguồn.
  - Ngày cũ hơn cửa sổ **không bao giờ** được đọc lại hay so sánh.
  - Không có nhật ký theo khóa, không có giá trị trước.
- `actual_final.py` đóng băng bản thực tế cho KPI (bảng `actual_finals`), nhưng không đánh dấu khi `demand_daily` của ngày
  đã chốt thay đổi sau đó.

**Nguồn BigQuery** (`lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`, chỉ đọc):
- Bảng được **tạo lại mỗi sáng** (thời điểm tạo = thời điểm sửa, khoảng 07:10), không partition. Dataset giữ time travel 168 giờ.
- **Không có trạng thái hủy** trong bảng. 9.000.299 dòng gồm COMPLETED, DELIVERED, DELIVERING, CONFIRMED, WAIT_TO_DELIVER,
  PROCESSING, WAIT_TO_CONFIRM.
- Không đọc được SQL dựng bảng: `INFORMATION_SCHEMA.JOBS_BY_USER` và `JOBS_BY_PROJECT` bị từ chối quyền.

**Hệ quả:**
- Trong cửa sổ D-1, đơn hủy làm **giảm** cầu đã lưu. Ví dụ D-1 07:14 ngày 22/10 đã bỏ 126 đơn vị của đơn hủy và 313 đơn vị
  WAIT_TO_CONFIRM không được xác nhận.
- Ngoài cửa sổ, mọi thay đổi của nguồn bị bỏ qua: 841 khóa trước 17/10 lệch nguồn ngày 22/10.
- Dữ liệu lưu vì vậy không theo một định nghĩa thống nhất.

### 3. Thay đổi đã thực hiện (release 1.2.13, chưa commit, chưa push)

**Quy tắc (`data_policy.history_change_policy`):**
- Mặc định `KEEP_OBSERVED_LINES`: dòng lưu = nguồn hiện tại + các dòng đơn đã từng thấy mà nguồn bỏ đi không phải do
  chuyển SKU / FC / ngày (gọi là "dòng giữ").
- `FOLLOW_SOURCE` = quy tắc trước 1.2.13, giữ lại để chủ hệ thống quay về khi cần.

| File | Chức năng |
|---|---|
| `backend/app/migrations/0010_history_sync.sql` (mới) | 5 bảng, chỉ thêm. `demand_held_lines`: dòng giữ, ACTIVE → RELEASED một lần. `demand_change_log`: trước / sau từng dòng, append-only, cờ `finalized`. `demand_sync_runs`: bản ghi lần chạy. `demand_sync_run_keys`: quyết định từng khóa. `source_day_checks`: kiểm tra từng ngày. Kèm trigger bảo vệ và câu lệnh gỡ ngược trong đầu file |
| `backend/app/data/history_sync.py` (mới) | `prepare`: lập kế hoạch, chỉ đọc. `classify_key`: phân loại từng dòng, hàm thuần. `write`: một transaction, kiểm tra lại trạng thái dưới khóa ghi. `rollback`, `release_holds`, `day_check`, `rows_as_of`, `window_identity_as_of` |
| `backend/app/bq/source_lines.py` (mới) | Đọc BigQuery chỉ đọc (dry run trước, có trần): dòng của đúng các khóa, hiện tại hoặc `FOR SYSTEM_TIME AS OF`; dòng theo mã đơn; tổng theo ngày kèm dấu vân tay; phiên bản bảng |
| `backend/app/sync.py` | D-1 thường và backfill ghi qua kế hoạch. Phiên bản nguồn phải ổn định trong lúc đọc (`SOURCE_CHANGED_DURING_READ`). Đọc rỗng: dừng sớm. Backfill: chỉ ghi lại dòng đổi; ngày chưa chốt ghi lại cả ngày. Xem trước báo cáo dòng giữ và digest. Kiểm tra lịch sử sau D-1. Cảnh báo `FULL_RELOAD_HELD_LINES` |
| `backend/app/bq/connector.py` | Tham số mảng cho truy vấn BigQuery |
| `backend/app/settings_service.py` | 3 cài đặt mới trong `data_policy`, không nằm trong mapping hash |
| `backend/app/data_checks.py` | `held_lines_in_demand` (FAIL), `history_sync_protection_triggers` (FAIL), `finalized_days_changed` (WARN), `history_source_drift` (WARN) |
| `backend/app/cli.py` | `sync-runs`, `sync-rollback`, `held-lines` (xem / giải phóng), `history-check`. Không bao giờ migrate; từ chối DB dưới schema 10 |
| `backend/app/data/identity.py` | Khóa cache định danh gồm id nhật ký mới nhất |
| `backend/app/messages.py` | Thông báo song ngữ cho các mã mới |
| `backend/app/__init__.py`, `frontend/package.json`, `package-lock.json` | Phiên bản 1.2.13 (không đổi giao diện) |
| `docs/02_kien_truc_du_lieu/BIGQUERY.md` mục 11g, `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `CHANGELOG.md` | Tài liệu |
| `backend/tests/test_v1213_history_sync.py` (mới) + 7 file test cũ | Mục 6 và `TEST_RESULTS.md` |

**Không đổi:**
- grain ngày × SKU × FC; `item_code` không phải khóa; hậu tố .1/.2/.3 không quyết định FC;
- miễn chặn trùng của WAIT_TO_CONFIRM (`so_code` NULL); chặn trùng tuyệt đối với trạng thái khác;
- giờ mở bán không bao giờ tự điền; quy tắc MAX sáu khóa;
- Price ON / `customer_id` OFF; feature thứ trong tuần; lịch chạy;
- huấn luyện, promote, forecast: sửa lịch sử không kích hoạt việc nào.

**Đánh giá độc lập** (data-reviewer, SAFE WITH CONDITIONS): 1 BLOCKER, 8 SHOULD-FIX và các NOTE đã xử lý, mỗi mục có test.
- **B1:** trùng id dòng giữ khi giữ hàng nghìn dòng trong cùng một giây.
- **S2 / S3:** dòng giữ không được giải phóng khi dòng quay lại.
- **S4:** bằng chứng "chuyển" còn yếu.
- **S5:** dòng 0 đơn vị làm hỏng ràng buộc.
- **S7:** CLI có thể tự migrate DB thật.
- **S1:** bộ nhớ và thời gian khóa.
- **S8:** ngày chưa chốt sau backfill không còn chốt được.

### 4. Đối soát lịch sử - diễn tập trên bản sao production

**Cách làm** (loại bằng chứng: DB copy + real external service, chỉ đọc):
- Bản sao DB thật bằng SQLite backup API (nguồn mở `mode=ro`) lúc 22/10 13:35:54. `DF_DATA_DIR` riêng, scheduler tắt.
- Mã 1.2.13 (cây làm việc trên `24590d2`); migration 0010 chạy trên bản sao.
- Phạm vi `BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`, 01/01 - 21/10/2026 (294 ngày).
- Nguồn phiên bản `2026-10-22T00:10:45Z` (07:10 giờ Việt Nam), không đổi trong suốt lần chạy.
- 9 khối 35 ngày. Mỗi khối: xem trước → backfill với digest của bản xem trước.
- Chạy 13:50:54 - 14:58:16 (67 phút); `exit=0`.

**Kết quả toàn phạm vi:**

| Chỉ số | Trước | Sau | Ghi chú |
|---|---|---|---|
| Ngày lệch nguồn (kiểm tra theo ngày, dấu vân tay) | 239 / 294 | **0 / 294** | trước: khóa −364, đơn vị +1.303 (nguồn − lưu) |
| Dòng `demand_daily` | 1.364.054 | 1.364.268 | +214 |
| Đơn vị | 42.184.054 | 42.192.146 | **+8.092** = dòng nguồn mới thêm |
| Dòng giữ ACTIVE | 0 | 933 dòng / 6.789 đơn vị | LINE_GONE 871 / 6.323; ORDER_GONE 62 / 466 |
| Nhật ký thay đổi | 0 | INSERT 249 (+10.616), UPDATE 69 (±0), DELETE 35 (−2.524, rollback thử) | mọi dòng thuộc ngày đã chốt → cờ `finalized` |

- **Khớp với bằng chứng mức dòng (time travel 21/10 ↔ 22/10):** chênh lịch sử nguồn − lưu = +1.303 = +8.092 (thêm) −
  6.789 (giữ). Khớp tuyệt đối.
- 8.092 đơn vị thêm đều thuộc 3 SKU nguồn mới đưa vào phạm vi:
  - `MEDX.CRE-ROS-001` +8.053: 7.990 trong 2.330 đơn cũ + 63 trong 11 đơn mới;
  - `MEDX.HLJAXHR2` +33; `MEDX.6P7EQ1PG` +6.

| Khối | Xem trước (s) | Áp dụng (s) | Dòng trước → sau | Đơn vị trước → sau | Dòng giữ mới (đơn vị) |
|---|---|---|---|---|---|
| 01/01 - 04/02 | 105,2 | 329,4 | 193.573 → 193.610 | 6.522.798 → 6.523.987 | 234 (2.562) |
| 05/02 - 11/03 | 81,4 | 242,5 | 168.371 → 168.405 | 5.619.169 → 5.620.039 | 97 (744) |
| 12/03 - 15/04 | 86,9 | 358,8 | 182.441 → 182.476 | 6.253.325 → 6.254.584 | 150 (944) |
| 16/04 - 20/05 | 84,4 | 206,8 | 175.345 → 175.380 | 5.456.577 → 5.459.101 | 176 (1.171) |
| 21/05 - 24/06 | 44,9 | 134,8 | 174.798 → 174.834 | 5.600.514 → 5.601.985 | 142 (732) |
| 25/06 - 29/07 | 47,7 | 105,6 | 178.747 → 178.782 | 4.848.169 → 4.848.927 | 49 (299) |
| 30/07 - 02/09 | 40,3 | 113,6 | 145.267 → 145.269 | 3.729.066 → 3.729.087 | 18 (33) |
| 03/09 - 07/10 | 31,0 | 89,2 | 101.406 → 101.406 | 3.029.031 → 3.029.031 | 21 (95) |
| 08/10 - 21/10 | 21,0 | 202,3 | 44.106 → 44.106 | 1.125.405 → 1.125.405 | 46 (209) |

Thời gian "áp dụng" gồm đọc lại nguồn, kiểm tra trùng, sao lưu (khoảng 110 MB mỗi khối) và ghi.

**Các bước kiểm tra:**

| Kiểm tra | Kết quả |
|---|---|
| Chạy lại khối 01/01 - 04/02 với cùng nguồn | **PASS**: 137 khóa `HELD_UNCHANGED`, 0 dòng nhật ký mới, 0 dòng giữ mới, dữ liệu không đổi |
| Rollback `D1L-20261022072221-CC053C` (khối 16/04 - 20/05) bằng `RBK-20261022074834-EDB725` | **PASS**: 35 mục nhật ký đảo ngược, 176 dòng giữ chuyển RELEASED (`ROLLBACK`). Dữ liệu khối trở về đúng sha256 trước khi chạy (kể cả `loaded_at`) |
| Áp lại sau rollback (`D1L-20261022075045-33C8BC`) | **PASS**: 175.380 dòng / 5.459.101 đơn vị như lần đầu. 35 bản ghi sau (bỏ `loaded_at`) và 176 dòng giữ **giống hệt** lần đầu |
| Kiểm tra ngày cuối cùng | **MATCH** 294 / 294 |
| Quy tắc MAX sáu khóa giờ mở bán | 6 / 6 vẫn áp dụng |
| Cổng giờ mở bán của huấn luyện | OK: 1.364.268 dòng, 6 dòng override, 0 lỗi |
| Phạm vi khác (DEMO) | không đổi |
| Huấn luyện / forecast / thực tế / D-0 | không đổi: 8 / 8 run, 1.033.458 giá trị forecast, 294 ngày / 1.364.064 giá trị thực tế, 44 snapshot |
| Trùng khóa grain | 0 |
| `data-check` của bản sao | WARN, không có FAIL. `forecast_series_meta` (1): có từ trước, đã ghi ở các đợt trước. `finalized_days_changed` (212 ngày): kiểm tra mới báo đúng thiết kế rằng ngày đã chốt có thay đổi; bản thực tế đóng băng giữ nguyên |

**Tài nguyên của lần diễn tập:**
- Tiến trình Python: RAM private khoảng 747 MB (đỉnh working set 743 MB); CPU khoảng 2.680 s (user 1.342 + kernel 1.339).
- CPU kernel cao và 8,85 triệu page fault: máy chỉ còn khoảng 1 GB RAM trống, pagefile dùng 6,9 GB.
- BigQuery: 122 truy vấn, ước tính dry run **122,26 GB** cho toàn bộ diễn tập (gồm cả rollback và áp lại):
  - `dup_check` 37,39; `hr_lines` 37,03; `daily` 29,67; `hr_order_lines` 16,85; `hr_day_totals` 1,06; `product_names` 0,25.
  - Bảng nguồn không partition, nên mỗi truy vấn quét các cột cần dùng của cả bảng.

### 5. Đơn hủy: nguồn làm gì và 1.2.13 xử lý ra sao

So từng dòng bản 21/10 07:10 với bản 22/10 07:10 bằng time travel, đối chiếu với `fact_order` (chỉ đọc).

| Nhóm | Nguồn làm gì | Số liệu | 1.2.13 |
|---|---|---|---|
| Đơn bị hủy (`fact_order.order_status = CANCEL`) | **Xóa mọi dòng của đơn** khỏi bảng D-1, không đổi trạng thái, không giữ số lượng | 22 đơn / 92 dòng rời bảng (hủy ngày 21/10, đơn tạo từ 28/09): 53 dòng ở lịch sử, 39 dòng trong cửa sổ D-1 | Lịch sử: giữ (`ORDER_GONE`). Cửa sổ: D-1 07:14 ngày 22/10 (trước 1.2.13) đã bỏ |
| WAIT_TO_CONFIRM không được xác nhận | Xóa dòng | 114 dòng / 313 đơn vị (cửa sổ 17-20/10) | Giữ (`PENDING_GONE`) từ 1.2.13; 114 dòng này đã bị D-1 trước 1.2.13 bỏ |
| WAIT_TO_CONFIRM được xác nhận | Dòng có `so_code` thay dòng chờ, cùng sản phẩm và số lượng | 53 dòng, không đổi số lượng | Nhận là xác nhận, không giữ, không cộng hai lần |
| Phạm vi sản phẩm của nguồn thay đổi | Thêm hoặc bỏ **toàn bộ lịch sử** của vài SKU; đơn vẫn COMPLETED | Thêm: 3 SKU, +8.092 đơn vị (`MEDX.CRE-ROS-001` +8.053). Bỏ: 7 SKU, −6.323 đơn vị dòng biến mất (`RIS-DNP-002` −2.940, `HUY-JUI-001` −2.542, …) | Thêm: áp dụng. Bỏ: giữ (`LINE_GONE`), chủ hệ thống quyết định giữ hay giải phóng |
| Đổi mã 1-1 hoặc đổi FC của cùng dòng | Không thấy | 0 dòng; chỉ 3 đơn có cả `RIS-DNP-002` bị bỏ và `CRE-ROS-001` mới | Chỉ coi là "chuyển" khi cùng số lượng và đích mới chứng minh được |

- Trong diễn tập, dòng giữ `ORDER_GONE` là 62 dòng / 466 đơn vị trên nhiều SKU; 53 dòng trong số đó thuộc đơn CANCEL theo `fact_order`.

**Xung đột định nghĩa:**
- Target được nêu là tổng cầu: số lượng của mọi đơn đã đặt.
- Nguồn D-1 lại là đơn **chưa hủy tại lúc làm mới**.
- Không tự đặt định nghĩa mới. 1.2.13 áp dụng đúng quy tắc đã nêu: không tự giảm cầu chỉ vì đơn biến mất.

**Khôi phục tổng cầu:**
- `fact_order_item` giữ dòng của đơn hủy với cùng SKU, FC, ngày và số lượng: 92/92 dòng khớp.
- Đơn hủy 01-21/10 = 67.738 đơn vị, bằng **4,0 %** nguồn (1.682.477 đơn vị); 0 dòng thiếu FC.
- Đơn hủy *trước* lần nạp đầu không có trong nguồn D-1, nên không giữ được. Muốn có, cần chủ nguồn định nghĩa một nguồn tổng cầu.
- Phương án kiểm chứng được: bảng hoặc SQL mới từ `fact_order_item` + `fact_order`, cùng phạm vi SKU/FC, gồm CANCEL; đối chiếu
  với nguồn D-1 theo ngày (phần không hủy khớp 99,97 % trong 01-21/10).

### 6. Kiểm thử

Chi tiết: `TEST_RESULTS.md`.

| Lần chạy | Loại | Kết quả |
|---|---|---|
| Backend toàn bộ, mã cuối | unit + integration với BigQuery giả, DB tạm cách ly | **751 passed / 19 skipped / 0 failed** |
| `test_v1213_history_sync.py` (20 trường hợp bắt buộc + 15) | integration với nguồn giả có phiên bản | 35 passed |
| Frontend vitest / typecheck / build | unit UI / tĩnh / build | 26 file, **159 passed**; typecheck OK; build OK |
| Diễn tập toàn lịch sử | DB copy + real external service (chỉ đọc) | 9/9 khối; mọi kiểm tra ở mục 4 PASS |
| Lint | - | **không cấu hình** |

### 7. Báo cáo Excel

`reports\history-sync-20261022\HISTORY_RECONCILIATION_BIGQUERY_20260101-20261021_20261022-1504.xlsx`
(SHA-256 `773A265C152D3AE1D75DA733BBCCDAE79CAF45BBC717AE05B6382829AF29A5EE`).

- 9 sheet: `Executive_Summary`, `Key_Differences` (974 khóa), `Order_Cancellation` (206 dòng), `Missing_Keys`,
  `SKU_FC_Mapping` (59 SKU), `Duplicate_Check`, `Reconciliation_Log` (mọi lần chạy của diễn tập), `Recovery_Status`, `Validation`.
- Mọi chênh lệch và tỷ lệ là công thức; có bộ lọc và cố định dòng tiêu đề.

### 8. Backup và checkpoint

| Mục | Đường dẫn | SHA-256 |
|---|---|---|
| Checkpoint trước khi sửa | `checkpoints\source-1.2.12-before-history-sync-20261022.zip` | `B8B335BB…0137` |
| Checkpoint sau diễn tập: 23 file nguồn, trạng thái git, log + JSON diễn tập, script | `checkpoints\source-1.2.13-history-sync-rehearsed-20261022.zip` | `64EB82052B636C5E655AC3FBA15EA8436617BAC0C53BC8EBB5B60969B69C2D0F` |
| Bằng chứng diễn tập | `reports\history-sync-20261022\evidence\rehearsal.log`, `rehearsal.json` | - |
| Bằng chứng dòng (time travel bản 21/10) | `reports\history-sync-20261022\evidence\tt_detail_1021_1022.json.gz` | nội dung `58661424…` |

- Bằng chứng time travel tái tạo được từ BigQuery chỉ đến khoảng 28/10 07:10, nên đã lưu lại bản nén.
- Production không có backup mới vì không ghi gì vào production.
- Các backup theo khối của bản sao (khoảng 110 MB mỗi khối) đã được script diễn tập xóa. Đó là bản sao của bản sao, không
  phải dữ liệu thật.

### 9. Ảnh hưởng production

**Không có.** Kiểm tra chỉ đọc lúc 15:09:
- `/api/health` = 1.2.11 (PID 7316, chạy từ 21/10 18:08); `current.txt` = 1.2.11.
- `storage.json` SHA-256 `8D79DBDD…E047`, không đổi.
- DB thật schema 9 (`0009_actual_finalization.sql`), không có bảng của 1.2.13.
- Không có job đang chạy; D-0 vẫn chạy bình thường (14:00 SUCCEEDED).

Không triển khai, không backfill production, không đổi lịch, không huấn luyện, không promote, không push. Mã 1.2.13 chưa
commit: 23 file trên `24590d2`, đã lưu trong checkpoint.

### 10. Việc cần chủ hệ thống quyết định

1. **Triển khai 1.2.12** (gói `10BF50BF…4C05`, đã diễn tập 36/36). Bộ phân loại quyền đã từ chối Claude hai lần; chủ hệ
   thống chạy `scripts\deploy-upgrade.ps1`.
2. **Commit 1.2.13** (cần phê duyệt theo AGENTS.md mục 8), đóng gói, rồi triển khai sau 1.2.12.
3. **Backfill lịch sử lần đầu trên production** sau khi có 1.2.13: xem trước → backfill từng khối, có backup.
   - Theo nguồn 22/10, dự kiến +214 dòng / +8.092 đơn vị và 933 dòng giữ / 6.789 đơn vị. Số liệu sẽ khác theo ngày chạy.
   - Mỗi khối tạo một backup khoảng 110 MB.
4. **SKU bị nguồn bỏ khỏi phạm vi** (7 SKU, 6.323 đơn vị, đơn vẫn COMPLETED): giữ (mặc định) hay giải phóng
   (`app.cli held-lines --release --sku ...`).
5. **Nguồn tổng cầu** gồm đơn hủy trước lần nạp đầu: cần chủ nguồn định nghĩa, ví dụ từ `fact_order_item` + `fact_order`.
6. **Đơn hủy và yêu cầu chưa xác nhận mà D-1 trước 1.2.13 đã bỏ** (cửa sổ 17-20/10: 126 + 313 đơn vị): để nguyên, hoặc
   khôi phục từ `fact_order_item` hoặc time travel (đến khoảng 28/10).

## 9. Kết quả kiểm thử - đồng bộ lịch sử D-1 (1.2.13, 22/10/2026)

Nguồn: `reports\history-sync-20261022\TEST_RESULTS.md` (worktree MAIN).

Mã nguồn: cây làm việc trên `24590d2` (1.2.12) + thay đổi của đợt này (chưa commit lúc chạy). Python 3.14 (`.venv`).

### 1. Bảng tổng hợp

| Lần chạy | Loại | Kết quả |
|---|---|---|
| Toàn bộ backend (`pytest -q`), mã cuối (sau đánh giá độc lập) | unit + integration với BigQuery giả, DB tạm cách ly | **751 passed / 19 skipped / 0 failed** (898 s; máy thiếu RAM nên chậm) |
| Toàn bộ backend, trước khi sửa theo đánh giá | như trên | 742 passed / 19 skipped / 0 failed (331 s) |
| Test mới `test_v1213_history_sync.py` | integration với nguồn giả CÓ PHIÊN BẢN (time travel), DB tạm | **35 passed** (26 + 9 test hồi quy cho phát hiện của đánh giá độc lập) |
| Diễn tập trên bản sao production, nguồn BigQuery thật (chỉ đọc) | DB copy + real external service (read-only) | **9/9 khối, mọi kiểm tra PASS** (mục 4) |
| Frontend vitest / typecheck / build | unit UI / tĩnh / build | **26 file, 159 passed**; typecheck OK; build OK (mục 5) |
| Lint | - | **không cấu hình** (không tính là đạt) |

- 19 skipped = test BigQuery thật / D-0 thật opt-in (như trước).
- Nguồn giả của test mới: mọi số tổng hợp (`daily`), dòng (`hr_lines`, `hr_order_lines`) và tổng ngày (`hr_day_totals`) đều tính
  từ cùng các dòng đơn của từng phiên bản. Đây là dữ liệu tổng hợp, **không** phải bằng chứng tích hợp thật.

### 2. 20 trường hợp bắt buộc → test

| # | Trường hợp | Test (`test_v1213_history_sync.py`) |
|---|---|---|
| 1 | Ngày cũ đổi số lượng sau khi đơn hủy | `test_a_cancelled_order_keeps_the_gross_demand_in_the_window_and_is_logged`, `test_the_daily_check_detects_a_change_of_an_old_day_and_a_backfill_reconciles_it` |
| 2 | Đơn hủy không làm giảm tổng cầu | như trên (giữ 8, dòng giữ `ORDER_GONE` 3) |
| 3 | Nguồn đổi số lượng lịch sử | `test_a_bigger_quantity_is_taken_a_smaller_one_is_held_for_review` |
| 4 | Dòng nguồn biến mất trong bản đầy đủ | `test_a_key_the_source_dropped_entirely_is_kept_not_deleted` |
| 5 | Bản nguồn chưa hoàn tất: không xóa, không chốt | `test_an_empty_read_or_a_source_rebuilt_during_the_read_writes_nothing`, `test_a_day_missing_from_an_incomplete_source_is_kept_and_heals_when_it_comes_back` |
| 6 | Phân biệt khóa mới / cập nhật / biến mất | `test_new_updated_and_held_keys_are_told_apart_and_a_second_run_changes_nothing` |
| 7 | Chạy lại cùng snapshot không đổi gì | như trên (nhật ký, dòng giữ, dữ liệu không đổi) |
| 8 | Cùng khóa cập nhật nhiều lần | `test_the_same_key_updated_over_several_runs_never_double_counts` |
| 9 | Đổi SKU / FC, không suy FC từ hậu tố | `test_a_line_moved_to_another_fc_or_sku_is_a_move_not_a_hold` |
| 10 | WAIT_TO_CONFIRM `so_code` NULL không bị chặn | `test_wait_to_confirm_without_code_loads_is_confirmed_or_kept` |
| 11 | `item_code` không vào grain / chặn trùng | `test_item_code_is_neither_grain_nor_duplicate_criterion_and_exact_duplicates_still_block` |
| 12 | Trùng ở trạng thái khác vẫn bị phát hiện | như trên (`BQ_DATA_DUPLICATES`, không ghi gì) |
| 13 | `total_open_hours` thiếu không bị tự điền | `test_missing_open_hours_stay_missing_and_a_held_row_keeps_its_stored_hours` |
| 14 | MAX chỉ cho đúng 6 khóa, khi nguồn còn khớp | `test_a_history_backfill_rewrites_only_changed_rows_so_the_six_key_rule_still_applies` + 22 test của `test_v1212_open_hours_override.py` |
| 15 | Không ghi đè DEMO / dataset khác / snapshot huấn luyện | `test_other_scopes_training_runs_and_forecasts_are_never_touched` |
| 16 | Rollback khôi phục dữ liệu trước khi chạy | `test_rollback_restores_the_rows_exactly_and_refuses_after_a_later_change`, `test_an_owner_release_reduces_the_rows_is_logged_and_reversible` |
| 17 | Snapshot huấn luyện cũ tái lập được; mới dùng dữ liệu đã đối soát | `test_the_data_of_an_older_training_can_be_rebuilt_after_history_changes` |
| 18 | Nguồn đổi trong lúc chạy → phát hiện, thử lại có giới hạn | `test_an_empty_read_or_a_source_rebuilt_during_the_read_writes_nothing` (`SOURCE_CHANGED_DURING_READ`, Retryable của job: tối đa 4 lần) |
| 19 | Lỗi giữa chừng không để dữ liệu ghi dở | `test_a_failure_inside_the_write_leaves_no_half_written_data` |
| 20 | Sửa lịch sử không promote / không đổi forecast | `test_other_scopes_training_runs_and_forecasts_are_never_touched` (0 job huấn luyện, số forecast không đổi) |

Thêm:
- `test_the_backfill_refuses_a_plan_that_changed_after_its_preview` (digest);
- `test_a_change_of_a_finalized_day_is_written_marked_and_the_frozen_actual_stays`;
- `test_follow_source_releases_the_held_lines_of_the_keys_it_writes`;
- `test_the_new_tables_are_append_only`;
- 4 test của hàm phân loại thuần.
- 9 test hồi quy cho đánh giá độc lập: id dòng giữ duy nhất với 2.500 dòng (B1); `NO_EVIDENCE` được giải phóng khi nguồn
  trở lại (S2); cảnh báo nạp lại toàn bộ (S2); dòng chờ quay lại (S3); 5 → 4 → 5 (S3); đơn tách hai FC hủy một phần (S4);
  dòng 0 đơn vị (S5); CLI không migrate DB cũ (S7); ngày chưa chốt được ghi lại cả ngày (S8).

### 3. Test cũ đã sửa (có chủ đích, không nới kiểm tra)

| Test | Thay đổi | Lý do |
|---|---|---|
| `test_v129g_actual_final.py::test_legacy_rows_get_no_status...` | đường migration gồm 0010; gỡ ngược 0010 trước 0009 (theo đầu migration 0010) | migration mới trên đường nâng cấp |
| `test_v129_weekday_open_hours.py`, `test_v129c_window_spike_customer.py`, `test_v126_eod_backup_close.py`, `test_v126_retention_defaults.py` (2 chỗ) | danh sách migration / phiên bản đích thêm 0010 / 10 | như trên |
| `test_v129_backfill_history_patterns.py::test_backfill_needs_a_matching_preview...`, `test_v129g_actual_final.py::test_a_successful_d1_load_finalizes...` | chạy với `history_change_policy = FOLLOW_SOURCE`, **giữ nguyên mọi assert** | hai test này kiểm cơ chế thay thế của 1.2.9 (khóa nguồn bỏ → xóa). Chính sách mặc định mới được kiểm trên cùng kịch bản trong file test mới |

### 4. Diễn tập toàn lịch sử trên bản sao production (22/10 13:50 - 14:58)

Loại: **DB copy + real external service** (BigQuery thật, chỉ đọc). Bản sao bằng SQLite backup API lúc 13:35:54,
`DF_DATA_DIR` riêng, scheduler tắt. Script: `scratchpad\p31\rehearse.py`. Log và JSON: `evidence\rehearsal.log`,
`evidence\rehearsal.json`.

| Bước | Kết quả |
|---|---|
| Migration 0010 trên bản sao | áp dụng, schema 10 |
| Kiểm tra ngày trước | DIFF: 239 / 294 ngày, khóa −364, đơn vị +1.303 (78,9 s) |
| 9 khối 35 ngày (xem trước → backfill có digest) | 9/9 xong; xem trước 21-105 s, áp dụng 89-359 s mỗi khối |
| Kiểm tra ngày sau | MATCH 294 / 294 (65,2 s) |
| Chạy lại khối 1 | 0 dòng nhật ký mới, 0 dòng giữ mới, dữ liệu không đổi |
| Rollback khối 16/04 - 20/05 | 35 mục, 176 dòng giữ RELEASED, sha256 khối = trước khi chạy (kể cả `loaded_at`) |
| Áp lại | 175.380 dòng / 5.459.101 đơn vị. Bản ghi sau (bỏ `loaded_at`) và 176 dòng giữ giống hệt lần đầu (`state\reapply_equal.json`) |
| Kiểm tra ngày cuối | MATCH 294 / 294 |
| Kiểm tra cuối | `data-check` WARN, 0 FAIL: `forecast_series_meta` 1 có từ trước; `finalized_days_changed` 212 đúng thiết kế. Sáu khóa 6/6. Cổng huấn luyện OK. DEMO không đổi. Số run huấn luyện / forecast / thực tế / D-0 không đổi. Trùng khóa 0 |
| Tổng | 1.364.054 → 1.364.268 dòng; 42.184.054 → 42.192.146 đơn vị; dòng giữ ACTIVE 933 / 6.789 đơn vị |
| BigQuery | 122 truy vấn, ước tính dry run 122,26 GB |
| Kết thúc | `DONE`, `exit=0` |

### 5. Frontend (22/10 15:05, chỉ đổi số phiên bản)

| Lệnh | Kết quả | Thời gian |
|---|---|---|
| `npm test` (vitest) | 26 file, **159 passed**, 0 failed | 72 s |
| `npm run typecheck` | OK (exit 0) | 20 s |
| `npm run build` | OK (`built in 10.85s`, ra `frontend/dist`, Git bỏ qua) | 30 s |

Log: `scratchpad\p31\state\frontend_checks.log`.
