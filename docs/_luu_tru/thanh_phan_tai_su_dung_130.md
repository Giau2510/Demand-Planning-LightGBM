# Thành phần 1.3.0 dùng lại được cho hướng LightGBM thuần

**Bối cảnh:**
- Bản 1.3.0 đã **đóng băng** theo quyết định của chủ dự án lúc 28/10/2026 khoảng 17:10 (ghi ở đầu [ke_hoach_trien_khai.md](ke_hoach_trien_khai.md)).
- Hướng mới là LightGBM thuần:
  - không kết hợp Avg, không hệ số chậm bán, không làm tròn cộng dồn;
  - dự báo làm tròn **ROUNDUP**;
  - đánh giá theo **Đúng / Thiếu / Dư** so với demand thực từng ngày.

**Cập nhật 28/10/2026 17:10 theo chủ dự án** (chỉ sửa tài liệu, không sửa code, không commit):
- Phân nhóm SKU × FC: chuyển sang **GIỮ, chỉ dùng cho báo cáo** (mục 1.8); đổi tên nhóm thành A / B / C.
- SHADOW / LIVE: chuyển sang **GIỮ, dạng đơn giản** (mục 1.9).
- Mô phỏng tồn kho B8: **BỎ khỏi app** (mục 2).
- Thêm mục 3 **CẦN LÀM MỚI**.

**Cách lập:** chỉ đọc code ở commit cục bộ `969ebe2` (Release 1.3.0, branch `feature/du-bao-moi-20261028`, chưa push). Không chạy gì.
- Số dòng `file:dòng` tính theo nội dung ở commit đó.
- "Commit" là commit chứa phiên bản được dẫn. `3701f8b` chỉ chứa báo cáo.
- Đường dẫn tính từ `backend/app/`, trừ khi ghi khác.

## 1. Dùng lại được

### 1.1 Tác vụ làm mới dự báo + nút chạy tay + hạn chót cấu hình (commit `969ebe2`)

**Khung tác vụ làm mới**, `ml/shadow_refresh.py`:
- `run()` :183 và `_refresh()` :204: các bước kiểm tra → model đang dùng → panel → đọc nguồn → dự báo → lưu.
- **Dùng lại được:** thứ tự các bước, các lần trả về NOT_READY / SKIPPED / FAILED, và việc không bao giờ huấn luyện hay ghi `forecast_runs`.
- **Phải bỏ** các bước nằm trong `_refresh`: `fetch_avg_today`, `fetch_avg_history`, `avg_today_vs_previous_day`, `ensure_groups`.

**Lấy model đang dùng:** `ml/shadow_refresh.py` `_model_in_use()` :111, `_load_model()` :118.
- Kiểm sha256 của file model.
- Lấy `sku_codes` / `fc_codes` từ file json của model.
- Dùng lại nguyên.

**Panel dữ liệu đến D-1** (cùng đường với huấn luyện): `ml/shadow_refresh.py` `build_refresh_panel()` :140.
- Dùng lại nguyên. Đã chứng minh panel kết thúc đúng D-1 và test rò rỉ đạt.

**Dự báo bằng mã danh mục của model:** `ml/model.py` `forecast()` :161 và `_forecast_direct()` :206, với tham số tùy chọn `sku_codes` / `fc_codes`.
- Dùng lại nguyên. Không truyền thì hành vi y như 1.2.14.
- TÁI LẬP: LightGBM khớp `forecast_V1` ở mọi chuỗi (lệch tối đa 0,00005).

**Tính dự báo (lõi thuần):** `ml/shadow_refresh.py` `compute()` :79.
- **Sửa:** bỏ `avg`, `groups`, `state`, `weight`, `factor`, `avg_value` và lời gọi `postprocess.finalize`; thay bằng làm tròn ROUNDUP.

**Cờ chuỗi lạ:** `ml/shadow_refresh.py` `FLAG_CODE_UNKNOWN` :48, đặt trong `compute()`.
- Đánh dấu chuỗi không có trong mã danh mục của model. Dùng lại.

**Lưu một lần chạy:** `ml/shadow_refresh.py` `_persist()` :348, `config_version()` :51.
- **Sửa:** chỉ ghi lần chạy và nhật ký; bỏ phần `slow_mover_state`.

**Chọn khoảng đọc giờ mở bán:** `ml/shadow_refresh.py` `open_hours_range()` :282.
- Đọc tăng dần, mốc đọc hoàn tất. Dùng lại.

**Thực bán theo ngày:** `ml/shadow_refresh.py` `refresh_actual_daily()` :399.
- Dùng lại; đây là đầu vào của đánh giá Đúng / Thiếu / Dư.

**Kiểu job và trạng thái**, `jobs/runner.py`:

| Vị trí | Nội dung |
|---|---|
| :25 | `HEAVY_TYPES` |
| :34 | `JOB_TYPES` |
| :38 | `FLOW_FLAG` |
| :41 | `FLOW_OFF_CODE` |
| :44 | `REFRESH_STATUS` |
| :48 | `CANCELLABLE` |
| :96 | bảng handler |
| :228 | `refresh_key()` |
| :233 | `record_stale()` (STALE_FORECAST, một lần) |
| :251 | `close_waiting()` (REFRESH_DEADLINE_PASSED) |

Dùng lại nguyên.

**Lập lịch:** `jobs/scheduler.py`:
- `_plan_refresh()` :222 (chạy sau D-1 thành công, thử lại mỗi N phút đến hạn chót, không áp `train_catchup_policy`, lập trước TRAIN, lọc theo phạm vi);
- `_refresh_retry_allowed()` :212;
- lời gọi :144;
- `loaded_flows()` :300.
- **Sửa:** bỏ điều kiện `shadow.enabled` / Avg nếu hướng mới không còn section "shadow".

**Hạn chót và chu kỳ thử lại (cấu hình):** `settings_service.py` `ScheduleSettings` :268-275 (`refresh_enabled`, `refresh_enabled_at`, `refresh_deadline` "05:55", `refresh_retry_minutes` 10) và kiểm tra HH:MM :285.
- Dùng lại nguyên. Lưu ý D-1 theo lịch đã thất bại hai ngày 27 và 28/10 (nguồn chưa có dữ liệu), nên cần chọn hạn chót cho hợp.

**Công tắc luồng (API lịch):**
- `jobs/flows.py` FLOWS :34 "refresh", trường sửa được :43, điều kiện sẵn sàng :142-147, lần chạy kế tiếp :250;
- `api/data_routes.py` `SCHEDULE_SWITCHES` :69 (không đổi qua PUT chung, giữ khi reset).
- **Sửa:** bỏ điều kiện sẵn sàng `AVG_SOURCE_NOT_CONFIGURED`.

**Các bước tiến độ:** `jobs/progress.py` :22 `FORECAST_REFRESH`.
- **Sửa:** bỏ bước đọc Avg.

**Nút chạy tay (API):** `api/shadow_routes.py` `shadow_refresh_run()` :230 (POST `/api/shadow/refresh/run`), qua `background.submit`.
- Dùng lại; nên đổi tiền tố đường dẫn nếu bỏ tên "shadow".

**Nút chạy tay (giao diện) và thẻ lịch:**
- `frontend/src/pages/ShadowForecast.tsx`: nút làm mới, bảng giá trị, xuất file;
- `frontend/src/pages/Schedules.tsx`: thẻ "refresh" (hạn chót + phút thử lại);
- `frontend/src/i18n.tsx` (`sch.refresh.*`).
- **Sửa:** bỏ các cột Avg / nhóm / quy tắc, banner SHADOW và hộp xác nhận LIVE.

**Chặn tác vụ nặng chồng nhau:** `ml/pipeline.py` :748, :868 (promote / ngoại lệ gate chờ FORECAST_REFRESH). Dùng lại nguyên.

**Thông báo:** `messages.py`: STALE_FORECAST, REFRESH_DEADLINE_PASSED, DATA_NOT_UP_TO_DATE, NO_MODEL_IN_USE, MODEL_FILE_MISMATCH, REFRESH_SCHEDULE_DISABLED, REFRESH_WAITS_FOR_D1. Dùng lại.

### 1.2 Đọc `openhours_by_sku` (commit `969ebe2`)

| Thành phần | Vị trí | Ghi chú |
|---|---|---|
| Đọc chỉ đọc, dry run + trần, gộp MAX theo item, ghi theo khối 200k dòng | `bq/aux_sources.py` `fetch_open_hours()` :92, `open_hours_source()` :61, `UPSERT_CHUNK_ROWS` :36 | Dùng lại nguyên. Đo thật: 120 ngày = 1,13 GB; giờ đọc tăng dần |
| Mốc đọc hoàn tất | `bq/aux_sources.py` `last_completed_read()` :73, `_record_read()` :79; bảng `shadow_source_reads` (migration 0011 :53) | Dùng lại nguyên |
| Bảng `open_hours_daily` | `migrations/0011_shadow_forecast.sql` :26 | Dùng lại nguyên. Khóa theo bảng nguồn + seller. Không ghi đè giá trị đã lưu bằng NULL |
| Cấu hình tên bảng, seller | `settings_service.py` `ShadowSettings.openhours_table`, `seller_code` (class :590) | **Sửa:** chuyển sang section mới nếu bỏ "shadow" |
| Kiểm tra `data-check` | `data_checks.py` `_shadow_checks()` :53 (`shadow_open_hours_range`) | Dùng lại |

**Lưu ý dữ liệu:** bảng nguồn làm mới lúc 04:10 nhưng chỉ có đến **D-2**.

### 1.3 Cấu hình trọng số horizon V1 (commit `969ebe2`)

| Thành phần | Vị trí | Ghi chú |
|---|---|---|
| Hai trường cấu hình + kiểm tra | `settings_service.py` :147-160: `horizon_weight_short`, `horizon_weight_cutoff`, `_horizon_weight()` (HORIZON_WEIGHT_INCOMPLETE, HORIZON_WEIGHT_DIRECT_ONLY) | Dùng lại nguyên |
| Trọng số khi huấn luyện | `ml/model.py` `train()` :47-70 (3,0 khi horizon ≤ 7, chỉ DIRECT) | Dùng lại nguyên. Byte-identical với công thức V1 của backtest vòng 2 |
| Fingerprint không đổi khi không đặt | `ml/pipeline.py` :409-413 | Dùng lại nguyên |
| Ứng viên đã huấn luyện thử (chỉ trên bản sao, **không promote**) | `MV-20261028-165730-1A9F`, báo cáo `3701f8b` | Chỉ để tham khảo |

### 1.4 Nhật ký dự báo (commit `969ebe2`)

| Thành phần | Vị trí | Ghi chú |
|---|---|---|
| Bảng `shadow_forecast_runs` (lần chạy) | migration 0011 :97 + trigger chống sửa/xóa | Dùng lại. **Sửa:** bỏ các cột `avg_source`, `avg_asof` |
| Bảng `forecast_daily_log` (giá trị từng chuỗi × horizon) | migration 0011 :115 | **Sửa:** bỏ `avg_demand`, `avg_used`, `rule`; giữ `lgb_raw`, `final_qty` (ROUNDUP), `flags`, `model_id` và `group_code` (A / B / C, chỉ để báo cáo, mục 1.8). Dung lượng khoảng 125 MB mỗi lần chạy, cần quyết thời gian lưu |
| Bảng `actual_daily` | migration 0011 :135 | Dùng lại nguyên |
| Đọc dữ liệu cho màn hình và file xuất | `api/shadow_routes.py` `shadow_status()` :68 (cờ trễ), `shadow_runs()` :104, `shadow_values()` :129, `shadow_export()` :148, `_export_workbook()` :167 (openpyxl write-only), `_latest_run()` :56 | **Sửa:** bỏ cột Avg / nhóm / quy tắc và banner |
| Kiểm tra `data-check` | `data_checks.py` `_shadow_checks()` :53 (trigger, liên kết lần chạy, ngày đích, số nguyên ≥ 0) | **Sửa:** bỏ các kiểm tra quy tắc / nhóm / Avg |

### 1.5 Báo cáo tuần (commit `969ebe2`)

| Thành phần | Vị trí | Ghi chú |
|---|---|---|
| Khung job tuần | `ml/shadow_monitor.py` `run()` :361, `_monitor()` :397, `is_scheduled_job()` :352; `jobs/scheduler.py` `_plan_monitor()` :282; `jobs/runner.py` `SHADOW_MONITOR` (:34, :46, :93); `jobs/flows.py` "monitor" :35, :44; cấu hình `monitor_*` (`settings_service.py` :272-275) | Dùng lại |
| Kỳ báo cáo và nạp dữ liệu | `ml/shadow_monitor.py` `period_of()` :74, `_LATEST` :81, `load_h1()` :86, `load_open_days()` :100, `measured()` :109 | Dùng lại. **Sửa:** bỏ cột Avg |
| Sai lệch theo ngày | `ml/shadow_monitor.py` `daily_errors()` :228 | **Sửa:** thay bằng đếm Đúng / Thiếu / Dư so với demand thực |
| Ghi file .xlsx (không ghi đè) | `ml/shadow_monitor.py` `report_dir()` :333, `write_report()` :337, `report_sheets()` :285 | Dùng lại. **Sửa** nội dung các sheet |
| Lỗi báo cáo không làm hỏng kết quả | `ml/shadow_monitor.py` cuối `_monitor()` (`SHADOW_REPORT_NOT_WRITTEN`) | Dùng lại |
| Thẻ lịch theo dõi | `frontend/src/pages/Schedules.tsx` (thẻ "monitor") | Dùng lại |

### 1.6 Sao lưu / khôi phục (không đổi trong 1.3.0)

| Thành phần | Vị trí | Commit |
|---|---|---|
| Sao lưu trực tuyến (nguồn chỉ đọc, kiểm integrity, zip kiểm tra) | `backup.py` `backup_database()` :16, `list_backups()` :61 | `15d4f4b` (1.2.9) |
| Khôi phục (tạo sao lưu an toàn trước, kiểm integrity) | `backup.py` `restore_backup()` :69; `cli.py` lệnh `backup` / `restore` :98-99, :314-317 | `15d4f4b` / `1b00c42` |

Quy trình C2 đã dùng ngày 28/10:
- Gọi `backup_database()` của bản đã cài.
- Khôi phục vào LOCALAPPDATA / DF_DATA_DIR riêng.
- So số dòng 35 bảng và chạy `data-check`.

Script kiểm tra nằm trong scratchpad (`c2\verify_restore.py`), **không commit**. Nếu cần dùng lại thì đưa vào `scripts\`.

### 1.7 Test (commit `969ebe2`)

| File | Dùng lại |
|---|---|
| `backend/tests/test_v130_b1_settings.py` | Toàn bộ: trọng số horizon, cấu hình lịch, migration. **Sửa** phần cấu trúc bảng nếu đổi schema |
| `backend/tests/test_v130_refresh.py` | Phần nguồn giờ mở bán, model / mã danh mục, panel D-1 và rò rỉ, chạy lại cùng ngày, lập lịch (thử lại, hạn chót, STALE, LOCKED, phạm vi), `actual_daily`, công tắc. **Bỏ** phần Avg, nhóm, trạng thái chậm bán |
| `backend/tests/test_v130_shadow_api.py` | Phần trạng thái trễ, phân trang, xuất file streaming, nút chạy tay. **Bỏ** phần chuyển LIVE |
| `backend/tests/test_v130_monitor.py` | Phần khung job, chọn lần theo lịch, tên file, lỗi báo cáo. **Bỏ** phần B7 |
| `backend/tests/test_data_checks.py` (phần shadow) | Dùng lại |
| `frontend/src/v130-shadow.test.tsx` | Phần thẻ lịch. **Bỏ** phần hộp xác nhận LIVE |
| Sửa số migration trong 5 test cũ; `reverse_0011` (`test_v129g_actual_final.py`) | Dùng lại nếu giữ migration 0011 |

### 1.8 Phân nhóm SKU × FC: GIỮ, chỉ dùng cho báo cáo (commit `969ebe2`)

**Đổi tên nhóm** (ngưỡng giữ nguyên; tính trên ngày mở bán):

| Nhóm | Tên cũ | Điều kiện |
|---|---|---|
| **A**, bán chạy | `FAST` | TB > 20 sp/ngày mở bán **và** tỷ lệ ngày mở bán không có đơn ≤ 20 % |
| **B**, bán bình thường | `OTHER` ("còn lại") | các trường hợp còn lại, kể cả chuỗi có < 14 ngày mở bán trong 90 ngày |
| **C**, bán chậm | `SLOW` | TB ≤ 5 **và** tỷ lệ ngày mở bán không có đơn > 20 % |

**Nhóm KHÔNG dùng để chọn công thức dự báo**: dự báo là LightGBM thuần + ROUNDUP cho mọi nhóm.

| Thành phần | Vị trí | Ghi chú |
|---|---|---|
| Luật nhóm + chỉ số | `ml/sku_group.py` `classify()` :47, `compute_metrics()` :58; hằng số :27-33 (`WINDOW_DAYS` 90, `MIN_OPEN_DAYS` 14, ngưỡng) | Dùng lại. **Sửa:** mã nhóm `FAST/OTHER/SLOW` → `A/B/C` (hằng số đang lấy từ `postprocess.GROUP_*`, phải tách ra khi bỏ `postprocess`) |
| Cửa sổ, cắt theo vùng dữ liệu, hoãn khi giờ mở bán trễ, tính tháng một lần | `ml/sku_group.py` `window_for()` :41, `clipped_window()` :106, `open_hours_last_day()` :127, `OPEN_HOURS_MAX_LAG_DAYS` :98, `load_rows()` :115, `ensure_groups()` :134 | Dùng lại |
| Bảng `sku_group` | migration 0011 :66 | Dùng lại (giá trị `group_code` đổi thành A / B / C) |
| Test | `backend/tests/test_v130_sku_group.py`; phần nhóm trong `test_v130_refresh.py` | Dùng lại, đổi mã nhóm |

### 1.9 Chế độ chạy thử: GIỮ, dạng đơn giản (commit `969ebe2`)

- Một công tắc chế độ chạy thử.
- Nhãn **"chưa dùng để mua hàng"** trên giao diện và trên file xuất.
- Bỏ mọi logic gắn với kết hợp Avg.

| Thành phần | Vị trí | Ghi chú |
|---|---|---|
| Cờ chế độ + chặn đổi qua PUT chung / giữ khi reset | `settings_service.py` `ShadowSettings.forecast_output_mode` (class :590); `api/data_routes.py` :62-65, :83-84 | Dùng lại (chuyển sang section mới nếu bỏ "shadow") |
| Đổi chế độ có xác nhận gõ chữ + ghi lịch sử, audit | `api/shadow_routes.py` `shadow_mode()` :210 | Dùng lại |
| Nhãn trên giao diện / file xuất | `api/shadow_routes.py` `_banner()` :35, sheet thông tin trong `_export_workbook()` :167; `ml/shadow_monitor.py` `BANNER_VI/EN` :62-63; `frontend/src/pages/ShadowForecast.tsx` (banner, hộp xác nhận); `Config.tsx` (hiển thị chế độ, chỉ đọc) | Dùng lại; **sửa** chữ thành "chưa dùng để mua hàng" |
| Test | phần chuyển chế độ trong `test_v130_shadow_api.py` và hộp xác nhận trong `frontend/src/v130-shadow.test.tsx` | Dùng lại |

## 2. Phải bỏ

| Thành phần | Vị trí (commit `969ebe2`) |
|---|---|
| **Kết hợp Avg** (0,35 × LightGBM + 0,65 × Avg) và làm tròn kiểu ROUND | `ml/postprocess.py` `finalize()` :61 (nhánh BLEND / BLEND_AVG_MISSING), `round_half_away()` :43, hằng số `RULE_BLEND*`, `FLAG_AVG_MISSING`, `AVG_ROUNDED/RAW` :29-40; `settings_service.py` `ShadowSettings.forecast_blend_weight`, `blend_avg_value` |
| **Hệ số chậm bán** (× 2,2) | `ml/postprocess.py` `finalize()` (nhánh SLOW); `settings_service.py` `ShadowSettings.slow_mover_factor`; `ml/shadow_monitor.py` `slow_forecast()` :208, `SLOW_FACTORS` :54 |
| **Làm tròn cộng dồn** | `ml/postprocess.py` `finalize()` (`RULE_SLOW_CUMULATIVE`, `state_after`); `ml/shadow_refresh.py` `c0_of()` :63, `load_state()` :168, phần `slow_mover_state` trong `_persist()`; bảng `slow_mover_state` (migration 0011 :85) |
| **Nguồn Avg** | `bq/aux_sources.py` `fetch_avg_history()` :132, `fetch_avg_today()` :194, `parse_asof()` :177, `avg_source()` :67, `stored_avg()` :254, `_avg()` :85; `ml/shadow_refresh.py` `avg_history_once_a_day()` :300, `avg_today_vs_previous_day()` :313, `AVG_*` :42-47; bảng `avg_demand_daily` (0011 :39); cấu hình `avg_history_table`, `avg_today_*`; thông báo AVG_SOURCE_NOT_CONFIGURED, AVG_NOT_FOR_TODAY, AVG_TODAY_EQUALS_PREVIOUS_DAY |
| **B7** (tự chọn và tự đổi tỷ lệ kết hợp) | `ml/shadow_monitor.py` `blend()` :116, `weight_error()` :125, `weight_errors()` :133, `best_weight()` :137, `decide()` :152, `previous_scheduled()` :387, `WEIGHTS` / `MAX_STEP` / `MIN_GAIN` / `CONSECUTIVE_RUNS` :49-53, phần lưu `forecast_blend_weight` trong `_monitor()`; thông báo SHADOW_WEIGHT_AUTO_CHANGED, SHADOW_WEIGHT_OUT_OF_RANGE |
| **Logic gắn với kết hợp Avg trong màn hình / API** | Cột Avg / quy tắc trong `ShadowForecast.tsx` và `VALUE_COLS` của `api/shadow_routes.py` :29; nhóm chỉ còn là cột báo cáo (mục 1.8) |
| **Mô phỏng tồn kho B8: BỎ khỏi app** (giữ trong lịch sử commit `969ebe2` để tham khảo) | `ml/inventory_sim.py` (toàn bộ: `simulate_series()` :73, `summarize()` :104); phần dùng nó trong `ml/shadow_monitor.py` `simulation_rows()` :193, `analyse()` :248; `backend/tests/test_v130_inventory_sim.py` |

## 3. CẦN LÀM MỚI (chỉ ghi yêu cầu, chưa thiết kế; 28/10/2026 17:10)

**a. Báo cáo Đúng / Thiếu ít / Thiếu nhiều / Dư ít / Dư nhiều**
- Gộp theo **tháng × nhóm A / B / C**; ghi cả số lượng (Qty) và % so với demand thực.
- Chỉ tính **ngày mở bán**; so dự báo với demand của **cùng ngày**.
- Dự báo làm tròn **ROUNDUP**.
- **Đúng** khi thỏa một trong các điều kiện:
  - |lệch| ≤ 3 sp (nhóm A, B);
  - |lệch| ≤ 1 sp (nhóm C);
  - |lệch| ≤ 20 %.
- **Ít:** lệch 20–50 %. **Nhiều:** lệch > 50 %. Thiếu hay Dư theo dấu của lệch.

**b. Bảng cấu hình biến**
- Mỗi biến có công tắc bật/tắt và hệ số ưu tiên (`feature_contri`).
- Kèm báo cáo tỷ trọng thực tế của từng biến sau mỗi lần huấn luyện.

**c. Đọc `is_deal` / `is_voucher`**: chỉ làm nếu backtest G1 chứng minh có ích.

**d. Nhật ký dự báo**
- Chỉ lưu **7 ngày dự báo**.
- Thời hạn lưu cấu hình được, mặc định **120 ngày**.
