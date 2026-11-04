# Kế hoạch 1.3.1: LightGBM chốt (C2)

**Căn cứ:**
- Yêu cầu của chủ dự án, ngày 28–29/10/2026: PHƯƠNG ÁN CHỐT B1–B12 và các bước C0–C7.
- Kết quả C0: [kiem_tra_hien_trang_20261029.md](kiem_tra_hien_trang_20261029.md).
- Backtest `reports\backtest-lgbm7-20261029\`: biến thể G2, cột `G2_lgbm`.
- Danh sách thành phần dùng lại của 1.3.0: commit `969ebe2`, tài liệu `docs/thanh_phan_tai_su_dung.md` ở working tree chính.

**Branch:** `feature/lgbm-chot-20261029`.
- Tạo từ production `af835b8` (1.2.14), làm trong worktree `D:\Buymed\lgbm-chot-20261029`.
- Branch `feature/du-bao-moi-20261028` đóng băng, không dùng làm nền. Code 1.3.0 chỉ được chép lại theo danh sách "dùng lại được".

**Nguyên tắc:** mọi thay đổi nằm sau cấu hình.
- Giá trị mặc định trong code = hành vi 1.2.14.
- Bản phát hành đặt cấu hình theo PHƯƠNG ÁN CHỐT bằng lệnh `python -m app.cli apply-preset lgbm-chot --apply`. Lệnh này đi qua `settings_service`, có kiểm tra hợp lệ và ghi lịch sử, chạy một lần khi triển khai.
- Không dùng Avg của hệ thống cũ, không dùng deal/voucher, không ghi BigQuery, không đổi lịch D0 / D-1 / huấn luyện.

## 1. Thiết kế theo từng mục

| Mục | Chỗ sửa (file:hàm) | Cấu hình (mặc định = 1.2.14 → giá trị chốt) | Hành vi khi tắt |
|---|---|---|---|
| **B1** 35 biến, bỏ `sku_code`, trọng số 3,0 khi h ≤ 7 | `ml/features.py`: `dropped_features()` mới; `feature_names()`, `features_at()`, `direct_extra()` bỏ cột bị loại. `ml/model.py` `train()`: trọng số theo horizon (lấy từ 1.3.0); `categorical_feature` chỉ gồm cột còn lại | `model.feature_sku_code` True → **False**; `model.horizon_weight_short` / `horizon_weight_cutoff` None → **3,0 / 7** | Danh sách biến, ma trận, model và fingerprint y hệt 1.2.14 (khóa mới không đưa vào fingerprint khi bằng mặc định) |
| **B2** Tắt luật dự phòng | `ml/model.py` `classification_details()`: khi tắt, mọi chuỗi là `LIGHTGBM` (`LIGHTGBM_ELIGIBLE`). Các đại lượng giải thích vẫn tính | `model.fallback_enabled` True → **False** | Luật INACTIVE → NEW_SERIES → INTERMITTENT như cũ |
| **B3** Số công bố | `ml/daily_refresh.py` `published_qty()`: v = làm tròn 6 chữ số; v < ngưỡng thì 0, ngược lại ROUNDUP. Lưu thêm giá trị gốc (float) | `daily_forecast.rounding_threshold` = 0,2 | Chỉ áp cho số của tác vụ Làm mới. Màn hình Kết quả cũ (`qty.py`) giữ ROUND_HALF_UP |
| **B4** Khung dự báo | `ml/daily_refresh.py`: H = max(7, max(`horizons.enabled`)), không quá `direct_max_horizon` | `horizons` không đổi ([7, 15]) | — |
| **B5** Làm mới dự báo | `ml/daily_refresh.py` `run()` (khung `shadow_refresh` của 1.3.0, bỏ Avg / nhóm chọn công thức / chậm bán). `jobs/runner.py` `FORECAST_REFRESH`; `jobs/scheduler.py` `_plan_refresh()`: sau D-1 thành công, thử lại mỗi N phút tới hạn chót, quá hạn thì một bản ghi STALE_FORECAST + cảnh báo; `jobs/flows.py` luồng `refresh`. Nút chạy tay: `POST /api/daily-forecast/refresh` | `daily_forecast.enabled` False → **True**; `schedule.refresh_enabled` False → **True**; `schedule.refresh_deadline` "12:00"; `refresh_retry_minutes` 10 | Không có tác vụ, không có bảng nào được ghi |
| **B6** `openhours_by_sku` → `open_hours_daily` | `bq/aux_sources.py` `fetch_open_hours()` (1.3.0, dry-run + trần, MAX theo item, ghi theo khối, mốc đọc hoàn tất). Mới: `source_modified()` đọc thời điểm sửa bảng (metadata, không tốn byte). Chỉ đọc khi bảng nguồn đã làm mới sau lần đọc hoàn tất cuối. Đọc tăng dần từ (ngày cuối đã đọc − 3) tới D-1; lần đầu đọc 93 ngày | `daily_forecast.openhours_table` = `lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku`; `seller_code` = "MEDX" | — |
| **B7** Nhóm A / B / C | `ml/sku_group.py` (1.3.0, đổi mã FAST/OTHER/SLOW → A/B/C). Tính khi lần làm mới đầu tiên của tháng hoặc lần đầu: 90 ngày tới D-1, chỉ ngày mở bán (giờ > 0) | — | Chỉ dùng cho báo cáo; không chọn công thức |
| **B8** Nhật ký | Bảng `forecast_refresh_runs` + `forecast_refresh_values` (h, `lgb_raw` float, `final_qty`, `method`, `group_code`; `model_version` + `config_version` ở cấp lần chạy) + `actual_daily` (thực bán + giờ mở bán theo ngày) | `daily_forecast.log_retention_days` = 120 | — |
| **B9** Báo cáo độ chính xác | `ml/accuracy_report.py`: `classify_cells()`, `build_tables()` (hàm thuần), `write_workbook()`, `run()`. Job `ACCURACY_REPORT`: thứ 2 lúc `report_time` + nút tay. File `<reports_dir>\theo-doi\bao-cao-do-chinh-xac-<thời điểm>.xlsx`, không ghi đè | `schedule.report_enabled` False → **True**; `report_weekday` 1; `report_time` "09:30"; `daily_forecast.report_subdir` "theo-doi" | — |
| **B10** Tỷ trọng biến | `ml/feature_report.py`: gain + số lần chia nhánh từng biến, % trên tổng, theo nhóm biến. Lưu bảng `training_feature_importance`, ghi `.xlsx` sau mỗi lần huấn luyện có model; lỗi ghi file không làm hỏng lần huấn luyện. API + bảng trên giao diện | Chạy khi `daily_forecast.enabled` | Không ghi gì thêm |
| **B11** Bảng cấu hình biến | Section mới `feature_table` (`features`: tên biến → {`enabled`, `contri`}). Sửa qua `PUT /api/feature-table` (`confirm` bắt buộc, ghi `settings_history` + audit). `train_and_publish` chép các dòng khác mặc định vào `model.feature_table` của lần huấn luyện (None khi mọi dòng mặc định), nên chỉ có hiệu lực ở lần huấn luyện sau và làm đổi fingerprint. `enabled=False` → bỏ cột; `contri ≠ 1` → tham số LightGBM `feature_contri` | Mặc định mọi biến Bật, hệ số 1,0 | Mặc định cho fingerprint, model và dự báo y hệt B1 |
| **B12** Chế độ chạy thử | `daily_forecast.trial_mode` (mặc định True). Chỉ đổi qua `POST /api/daily-forecast/trial-mode`: phải gõ đúng cụm xác nhận, ghi lịch sử + audit. `PUT` chung từ chối. Nhãn **"Chạy thử – chưa dùng để mua hàng"** hiện ở banner toàn app khi `enabled` và `trial_mode`, và trên mọi file xuất mới (dự báo làm mới, báo cáo độ chính xác, tỷ trọng biến) | Mặc định **BẬT** | Banner không hiện khi `daily_forecast.enabled` = False |

**Chỉ chủ dự án được tắt chế độ chạy thử.**
- App một người dùng, không có tài khoản. Liên kết xem từ xa là chỉ đọc: proxy chặn POST.
- Vì vậy "chủ dự án" = người dùng tại máy, cùng cụm xác nhận gõ tay. Đây là điểm cần chủ dự án xác nhận.

## 2. Giữ hành vi cũ khi tắt cấu hình

- Mọi trường mới của `model` có mặc định = 1.2.14 và không vào fingerprint khi bằng mặc định. Vì vậy model đang dùng và mọi lần huấn luyện với cấu hình cũ giữ fingerprint `8468ebe66d1706f7`.
- Section mới (`daily_forecast`, `feature_table`) và trường lịch mới: thiếu khóa thì đọc ra giá trị tắt (`daily_forecast.enabled` = False, luồng `refresh` / `report` OFF).
- Migration `0011_lgbm_chot.sql` chỉ thêm bảng và index, không sửa dòng nào.
- Lần làm mới **không bao giờ** ghi `forecast_runs` / `forecast_values` / `training_runs`, cũng không huấn luyện.
  - Các màn hình và file xuất của 1.2.14 (Kết quả, lịch sử D+1, sao lưu cuối ngày, chốt thực bán) giữ nguyên.
  - Dự báo làm mới có màn hình và file xuất riêng.

## 3. Lược đồ (migration 0011, chỉ thêm)

| Bảng | Vai trò |
|---|---|
| `open_hours_daily` | Giờ mở bán theo bảng nguồn × seller × FC × SKU × ngày (1.3.0) |
| `aux_source_reads` | Mốc đọc hoàn tất (append-only) |
| `sku_group` | Nhóm A / B / C theo phạm vi dữ liệu × tháng |
| `forecast_refresh_runs` | Một dòng mỗi lần làm mới (PUBLISHED, không sửa): mốc, dữ liệu đến, model, `config_version`, `trial_mode`, số chuỗi, số chuỗi dự phòng |
| `forecast_refresh_values` | (lần chạy, h, FC, SKU): `lgb_raw`, `final_qty`, `method`, `group_code`, `flags` |
| `actual_daily` | Thực bán + giờ mở bán theo ngày |
| `accuracy_report_runs` | Mỗi lần chạy báo cáo B9 |
| `training_feature_importance` | B10 |

**Thời hạn lưu**, chạy sau mỗi lần làm mới thành công:
- Giá trị h > 7 của các lần đã bị lần sau thay thế được xóa, chỉ giữ ngày 1–7 đúng như B8.
- Giá trị và thực bán cũ hơn `log_retention_days` được xóa. Dòng đầu của lần chạy vẫn giữ.

## 4. Task

| Task | Nội dung | File được sửa |
|---|---|---|
| T0 | Nền: cấu hình, migration, mã thông báo, chặn PUT chung | `settings_service.py`, `migrations/0011_lgbm_chot.sql`, `messages.py`, `api/data_routes.py`, `data_checks.py` |
| T1 | B1, B2, B11 (phần model), B10 | `ml/features.py`, `ml/model.py`, `ml/pipeline.py`, `ml/feature_report.py` (mới) |
| T2 | B3–B8: làm mới, giờ mở bán, nhóm, nhật ký, lịch; đấu job B9 | `ml/daily_refresh.py`, `ml/sku_group.py`, `bq/aux_sources.py` (mới); `jobs/runner.py`, `jobs/scheduler.py`, `jobs/flows.py`, `jobs/progress.py` |
| T3 | B9 báo cáo | `ml/accuracy_report.py` (mới) |
| T4 | API + giao diện + lệnh preset | `api/daily_routes.py` (mới), `main.py`, `cli.py`, `frontend/src/**` |
| T5 | Tài liệu, CHANGELOG, phiên bản 1.3.1 | `docs/*`, `CHANGELOG.md`, `backend/app/__init__.py`, `frontend/package.json` |

- Test viết trước cho công thức B3, B7, B9, B11 (tester).
- Mỗi task: coder → tester → reviewer. Migration và xử lý dữ liệu thêm `data-reviewer`.

## 5. Tái lập (C3)

**A. LightGBM.** Bản sao DB backtest (SHA `C7A663BE…F073`), các ngày 15/06, 15/09, 20/10.
- Model của lô: mốc 15/06, 14/09, 19/10. Huấn luyện bằng `model.train` của branch với cấu hình B1 + B2.
- Dự báo bằng `daily_refresh.build_refresh_panel()` + `compute()` (H = 7).
- So `lgb_raw` với `G2_lgbm` (≤ 1e-4, h = 1..7), và `final_qty` với B3 áp lên `G2_lgbm`.

**B. Báo cáo.** `accuracy_report.build_tables()` trên `G2_lgbm` 01/06–22/10, ngày thứ 1, cả kỳ.
- Nhóm: `sku_group.compute_metrics()` trên 01/06–31/08.
- Giờ mở bán: `openhours.parquet` của vòng 2.
- Kỳ vọng:
  - 11.587 SKU bq/ngày;
  - Qty lệch 10.813.068;
  - tổng demand 16.710.161;
  - nhóm A Đúng 220 SKU (25,3 %), 353.356 sp (≤ 0,1 %).

**C. Rò rỉ.** Đổi demand từ ngày D trở đi thì kết quả làm mới không đổi.

## 6. Giao diện hàm (đặc tả cho test viết trước; tên tiếng Anh như trong code)

### 6.1 Cấu hình (`settings_service.py`, T0)
- `FeatureRule(BaseModel)`: `enabled: bool = True`, `contri: float = Field(1.0, gt=0, le=10)`.
- `ModelSettings`, các trường mới (mặc định = 1.2.14):
  - `horizon_weight_short: float | None = None` (gt 0) và `horizon_weight_cutoff: int | None = None` (ge 1);
    - đặt một trong hai mà thiếu cái kia → `HORIZON_WEIGHT_INCOMPLETE`;
    - đặt khi không phải DIRECT → `HORIZON_WEIGHT_DIRECT_ONLY` (như 1.3.0);
  - `feature_sku_code: bool = True`;
  - `fallback_enabled: bool = True`;
  - `feature_table: dict[str, FeatureRule] | None = None`: bản chụp do lần huấn luyện đặt, không bao giờ do người dùng sửa trong section `model`.
- `FeatureTableSettings` (section `feature_table`): `features: dict[str, FeatureRule] = {}`.
  - Thiếu khóa = mặc định.
  - Tên biến khớp `^[a-z][a-z0-9_]{0,63}$`.
  - `sku_code` không được có trong bảng → `FEATURE_NOT_IN_TABLE`; B1 điều khiển biến này.
  - `horizon` không được tắt → `FEATURE_REQUIRED`.
- `DailyForecastSettings` (section `daily_forecast`):
  - `enabled=False`, `trial_mode=True`, `rounding_threshold=0.2` (0..1), `log_retention_days=120` (14..3650);
  - `openhours_table="lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku"` (project.dataset.table);
  - `seller_code="MEDX"`, `report_subdir="theo-doi"` (chữ, số, `-`, `_`).
- `ScheduleSettings`, các trường mới: `refresh_enabled=False`, `refresh_enabled_at=None`, `refresh_deadline="12:00"`, `refresh_retry_minutes=10` (1..60), `report_enabled=False`, `report_enabled_at=None`, `report_weekday=1` (1..7, ISO), `report_time="09:30"`; giờ theo dạng HH:MM.

### 6.2 Model (T1)
- `features.dropped_features(cfg) -> set[str]`:
  - gồm `{"sku_code"}` khi `getattr(cfg, "feature_sku_code", True)` là False;
  - cộng các tên có `enabled=False` trong `getattr(cfg, "feature_table", None)`.
- `features.feature_names(cfg)` = danh sách 1.2.14 bỏ các tên trong `dropped_features(cfg)`, thứ tự giữ nguyên.
  - Với cấu hình production (DIRECT, giờ mở bán, khách hàng, ISO) cộng `feature_sku_code=False` thì ra đúng 35 biến B1:
    `fc_code, series_age, lag_1..lag_7, lag_14, lag_21, lag_28, roll_mean_7, roll_mean_14, roll_mean_28, roll_mean_56, roll_std_7, roll_std_28, zero_share_28, days_since_last_sale, roll_max_28, price_last, price_rel_28, open_hours_last, open_hours_mean_7, cust_mean_28, cust_repeat_share_28, cust_repeat_interval_28, dow, dom, month, weekofyear, is_weekend, days_to_month_end, horizon`.
- `features_at()`, `origin_features()`, `direct_extra()`, `training_matrix()`, `direct_training_matrix()`:
  - các cột bị loại không có trong kết quả;
  - giá trị các cột còn lại y hệt khi không loại gì.
- `model.lgb_params(cfg, seed=7, names=None)`:
  - không truyền `names` → y như 1.2.14;
  - truyền `names` và có biến với `contri ≠ 1` → thêm `"feature_contri": [contri của từng tên theo thứ tự names]`.
- `model.train(p, cfg)`:
  - trọng số = `horizon_weight_short` khi horizon ≤ `horizon_weight_cutoff`, ngược lại 1,0 (chỉ DIRECT);
  - `info["horizon_weight"] = {"short", "cutoff", "rows_weighted"}`;
  - `categorical_feature` = các cột trong `("sku_code", "fc_code")` còn trong `feature_names(cfg)`;
  - `info["feature_importance_full"]` = mọi biến `{feature, gain, split}`.
- `model.classification_details(p, cfg)`: khi `fallback_enabled` False, `methods` = `LIGHTGBM` cho mọi chuỗi, `reasons` = `LIGHTGBM_ELIGIBLE`, `rate` = 0. Các khóa khác vẫn tính như cũ.
- `model.forecast(p, booster, cfg, horizon, cancel=None, capture=None, sku_codes=None, fc_codes=None)` như 1.3.0.
- `pipeline.config_fingerprint(fcfg: dict) -> str`:
  - = sha256(json.dumps(fcfg đã bỏ các khóa mới đang ở mặc định, sort_keys=True))[:16];
  - khóa mới bị bỏ khi: `horizon_weight_short/cutoff` None, `feature_sku_code` True, `fallback_enabled` True, `feature_table` None.
- `pipeline.feature_table_snapshot(table: FeatureTableSettings) -> dict | None`: các dòng khác mặc định, None khi không có dòng nào.
- `train_and_publish` đặt `mcfg.feature_table = feature_table_snapshot(ss.get("feature_table"))` trước khi huấn luyện.
- `ml/feature_report.py`:
  - `importance_rows(names, gains, splits) -> list[dict]`, mỗi dòng `{feature, feature_group, gain, split, gain_share, split_share, rank}`; share = phần trên tổng, 0 khi tổng 0; rank theo gain giảm dần;
  - `group_rows(rows) -> list[dict]`, mỗi dòng `{feature_group, n_features, gain, split, gain_share, split_share}`;
  - `record(training_run_id, rows)` ghi bảng;
  - `write_workbook(path, training_run_id, rows, meta)`.

### 6.3 Làm mới (T2)
- `daily_refresh.published_qty(values: np.ndarray, threshold: float) -> np.ndarray[int64]`:
  - v = `np.round(values, 6)`; kết quả 0 nơi v < threshold, `np.ceil(v)` nơi còn lại;
  - NaN → `ValueError`;
  - ví dụ: 0,19 → 0; 0,2 → 1; 1,000001 → 2; 3,0 → 3.
- `daily_refresh.refresh_horizon(enabled: list[int], mcfg) -> int` = max(7, max(enabled)), không quá `direct_max_horizon(mcfg)` (DIRECT).
- `daily_refresh.compute(panel, booster, mcfg, horizon, d, *, sku_codes, fc_codes, groups, threshold, baseline=False, cancel=None) -> dict`:
  - `keys` = [(fc_code, sku_code)];
  - `dates` = [ISO];
  - `raw` (S×H, float) = `model.forecast(...)["yhat"]`;
  - `final` (S×H, int) = `published_qty(raw, threshold)`;
  - `methods`; `groups` (mã A/B/C hoặc None); `flags` (`CODE_UNKNOWN`, `GROUP_MISSING`);
  - panel phải kết thúc đúng d-1, sai thì `ValueError`.
- `daily_refresh.build_refresh_panel(scope, d, mcfg) -> (panel, window)` như 1.3.0.
- `daily_refresh.run(business_date=None, job_id=None, cancel=None, progress=None, trigger="SCHEDULE") -> dict`:
  - kết quả `status` ∈ PUBLISHED | NOT_READY | SKIPPED | FAILED;
  - SKIPPED `DAILY_FORECAST_DISABLED` khi `daily_forecast.enabled` False.
- `sku_group`: `GROUP_A="A"`, `GROUP_B="B"`, `GROUP_C="C"`, `WINDOW_DAYS=90`, `MIN_OPEN_DAYS=14`, cùng các hàm `classify()`, `compute_metrics()`, `ensure_groups()` như 1.3.0 với mã mới:
  - A: TB > 20 và tỷ lệ ngày không đơn ≤ 0,20;
  - C: TB ≤ 5 và tỷ lệ > 0,20;
  - B: còn lại, kể cả < 14 ngày mở bán.

### 6.4 Báo cáo B9 (T3, `ml/accuracy_report.py`)
- `CATEGORIES = ("DUNG", "DU_NHIEU", "DU_IT", "THIEU_NHIEU", "THIEU_IT")`; nhãn vi: "Đúng với demand", "Dư nhiều", "Dư ít", "Thiếu nhiều", "Thiếu ít".
- `classify_cells(final_qty, demand, group) -> np.ndarray[object]`:
  - lệch = final − demand; tol = 1 khi nhóm C, 3 khi khác (thiếu nhóm = B);
  - DUNG khi |lệch| ≤ tol hoặc (demand > 0 và |lệch| / demand ≤ 0,20);
  - còn lại: tỷ lệ = |lệch| / demand (vô cùng khi demand = 0); IT khi ≤ 0,50, NHIEU khi lớn hơn; DU khi lệch > 0, THIEU khi lệch < 0.
- `build_tables(cells: pd.DataFrame) -> dict`:
  - `cells` có các cột `forecast_date, target_date, horizon, fc_code, sku_code, group_code, final_qty, demand`. Đã lọc ngày mở bán; demand của ngày mở bán không có đơn = 0.
  - Trả `{"D1": [...], "D7": [...]}`:
    - D1 = horizon 1; D7 = horizon 1..7.
    - Mỗi phần tử: `{"period": "YYYY-MM" | "TOTAL", "slots": n, "sku_per_day", "sku_share", "qty_dev", "demand", "qty_dev_share"}`. Tháng tính theo `target_date`.
  - Mỗi bảng: `{category: {"A", "B", "C", "TOTAL"}}`. `qty_dev` và `qty_dev_share` có thêm dòng `"TOTAL"`; `demand` là `{"A", "B", "C", "TOTAL"}`.
  - Các đại lượng:
    - `slots` = số cặp (target_date, horizon) khác nhau trong kỳ;
    - `sku_per_day` = số ô / slots;
    - `sku_share` = số ô / tổng số ô của cột (cộng 100 %);
    - `qty_dev` = Σ|lệch|;
    - `qty_dev_share` = Σ|lệch| / Σ demand của cột.
- Tính theo khối để ít RAM (120 ngày × 17 nghìn chuỗi × 7 ngày ≈ 14 triệu ô, không nạp hết một lần):
  - `aggregate(cells) -> (agg, slots)`:
    - `agg` có các cột `view` ("D1" / "D7"), `period` ("YYYY-MM"), `group_code` ("A" / "B" / "C"), `category`, `cells`, `qty_dev`, `demand`;
    - `slots` có các cột `view`, `period`, `slots`.
  - `combine(pairs) -> (agg, slots)`: cộng các khối. Một ô (target_date, h) chỉ thuộc một ngày dự báo, nên số slots cộng được.
  - `tables_from_aggregates(agg, slots) -> dict`.
  - `build_tables(cells) = tables_from_aggregates(*aggregate(cells))`.
  - `run()` đọc và gộp theo từng ngày dự báo (hoặc từng tháng).
- `write_workbook(tables, path, meta)`: sheet "Thông tin" có nhãn chạy thử; sheet "Ngày thứ 1", "7 ngày"; mỗi kỳ 4 bảng, cột A, B, C, Tổng 3 nhóm.
- `run(business_date=None, job_id=None, trigger="SCHEDULE", progress=None) -> dict`:
  - kỳ báo cáo = mọi ngày đích đã đóng có trong nhật ký;
  - mỗi ngày dự báo lấy lần làm mới PUBLISHED mới nhất của ngày đó;
  - ghi `accuracy_report_runs` và file .xlsx (không ghi đè).

## 7. Điều chỉnh sau review (29/10/2026)

**Kết quả review:** reviewer backend A, reviewer backend B, reviewer giao diện và data-reviewer đều không có lỗi nghiêm trọng. Sửa trong 2 vòng; reviewer vòng 2 kết luận APPROVE.

- **Làm mới chạy theo lịch** cho một ngày đã có lần PUBLISHED thì trả SKIPPED `ALREADY_PUBLISHED`, không ghi gì.
  - Chạy tay (MANUAL) vẫn tạo lần mới.
  - Scheduler không lập lần thử mới khi một lần của hôm nay còn trong hàng đợi worker.
- **Giờ mở bán** được đọc TRƯỚC khi dựng panel.
  - Khoảng dài hơn 15 ngày đọc thành các khoảng con ≤ 15 ngày, lần lượt từ cũ đến mới, mỗi khoảng là một lần đọc hoàn tất riêng.
  - Lần đọc 93 ngày bị ngắt giữa chừng thì lần sau đọc tiếp, không đọc lại từ đầu, và không giữ cả 93 ngày trong RAM.
- **Thử lại TRAIN_PUBLISH** chờ trong lúc lần làm mới của hôm nay đang chờ hoặc đang chạy, trước hạn chót.
- **`actual_daily`** thay cả khoảng (xóa rồi ghi lại trong một transaction).
  - Ngày mà cả phạm vi không có dòng demand nào là không biết: không có dòng, không bao giờ ghi 0.
  - Khoảng ngày được cắt theo đầu cửa sổ dữ liệu.
  - Nhóm A / B / C dùng cùng quy tắc ngày này.
- **Migration 0011** bỏ index `idx_frv_target` (không truy vấn nào dùng).
- **Dung lượng đo trên bản sao DB production:**
  - mỗi lần làm mới (15 ngày) là 21,2 MB, ghi trong 3,1 giây;
  - mỗi lần đã cắt còn 7 ngày khoảng 9,9 MB;
  - với 120 ngày, log khoảng 1,2 GB (docs/data/DATA-MODEL.md mục 12).