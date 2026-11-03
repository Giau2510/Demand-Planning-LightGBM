# Bản đồ dự án: pipeline dự báo LightGBM (khảo sát chỉ đọc)

- **Ngày khảo sát:** 26/10/2026.
- **Repository:** `D:\Buymed\Lightgbm AI`, branch `main`, HEAD `af835b8`.
- **Số dòng** trích dẫn là của working tree hiện tại. Các file ML/dữ liệu được trích không có thay đổi chưa commit (mục 10).
- **Phương pháp:**
  - Chỉ đọc file (ls, find, grep, cat, git log/status/diff và công cụ đọc file).
  - Không huấn luyện, không chạy backtest, không truy vấn BigQuery, không mở DB, không gọi API.
  - Ngoại lệ cần ghi lại: một lệnh `python -c "print(1)" >/dev/null` lọt vào một chuỗi lệnh đọc. Lệnh này không đọc hay ghi gì và không có tác động.
- **File được tạo:** chỉ file này.

> **PHÁT HIỆN CHẶN: `docs/spec_lightgbm_v3.md` KHÔNG TỒN TẠI.**
>
> Đã tìm ở các nơi sau, đều không có kết quả:
> - `docs/`, gồm `docs/data/` và `docs/agents/`;
> - toàn repo: `find -iname "*spec*"` chỉ ra 2 file không liên quan trong `reports/`;
> - lịch sử Git mọi branch: `git log --all -- '*spec_lightgbm*'` rỗng, không có file nào bị xóa trùng tên;
> - `D:\` (sâu 5 cấp);
> - `C:\Users\Giau Vo` (sâu 4 cấp).
>
> Vì vậy mục 11 đối chiếu theo **4 chủ đề nêu trong bối cảnh yêu cầu**: ngày đóng bán, mô hình riêng cho ngày D, cửa sổ nhãn mở rộng, huấn luyện lại mỗi ngày. Việc gán các số 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 3.1 vào chủ đề nào là **CHƯA RÕ**.

---

## 1. Tổng quan

### 1.1 Cây thư mục 2 cấp

Bỏ qua `.git`, `.venv`, `node_modules` và nội dung các thư mục dữ liệu, sao lưu, báo cáo.

```
D:\Buymed\Lightgbm AI
├── .claude/          agents/ (data-reviewer.md, repo-scout.md), settings.json
├── AGENTS.md  CLAUDE.md  README.md  CHANGELOG.md  REMOTE_ACCESS_GUIDE.md
├── Start-/Stop-/Setup-DemandForecast-*.bat      (link truy cập từ xa)
├── backend/
│   ├── app/          mã nguồn FastAPI (cấp 3 ở dưới)
│   ├── tests/        63 file test_*.py + conftest.py + fake_bq.py
│   └── requirements.txt, requirements.lock.txt, requirements-dev.txt
├── config/           app.env.example
├── docs/             KIEN-TRUC, MO-HINH-VA-CHI-SO, BIGQUERY, SCHEDULER, LICH-SU-FORECAST, VAN-HANH, ...
│   ├── data/         DATA-MODEL.md, DATA-DICTIONARY.md
│   └── agents/       GOVERNANCE.md
├── experiments/      final_release_20261017/, model_tuning_20261016/ (harness thí nghiệm; 64 file trong Git)
├── frontend/         src/ (App.tsx, pages/ 22 trang, components/, 27 file *.test.tsx), dist/, package.json, vite.config.ts
├── scripts/          start/stop/release/build-package/deploy-upgrade/rollback-*/run-tests .ps1, smoke_test.py, remote/, vps/
├── templates/        3 file .xlsx mẫu
└── [ngoài Git, .gitignore:10,26-31]  data/ (runtime: data\runtime\db\app.db, models\), backups/, checkpoints/, dist/, logs/, reports/
```

`backend/app` (cấp 3, phần liên quan):

```
app/  main.py  cli.py  settings_service.py  db.py  paths.py  qty.py  timeutil.py  weekday.py  messages.py  sync.py
      data_checks.py  forecast_history.py  forecast_backup.py  actual_close.py  actual_final.py  export_i18n.py  explain_export.py
  api/        forecast_routes.py  data_routes.py  ops_routes.py  bq_routes.py  history_routes.py  schedule_routes.py  background.py
  bq/         connector.py (SQL D-1)  d0_feed.py  sql_sources.py  sql_guard.py  oauth.py  secret_store.py  product_names.py
  data/       demand.py  open_hours.py  open_hours_override.py  customers.py  history_sync.py  importer.py  excel_io.py  demo.py  quality.py  identity.py  intraday.py
  jobs/       scheduler.py  runner.py  flows.py  progress.py  resources.py
  migrations/ 0001_initial.sql … 0010_history_sync.sql
  ml/         features.py  model.py  pipeline.py  methods.py  metrics.py  feature_registry.py  feature_catalog.py
              explain.py  forecast_explainer.py  training_explain.py  treeshap_trace.py  shap_audit.py  demand_patterns.py
```

### 1.2 Entry point

| Việc | Lệnh / đường vào | Bằng chứng |
|---|---|---|
| Chạy production (server + scheduler) | `scripts\start.ps1`, gọi `python -m app.cli serve --port <port>` (mặc định 8765, host 127.0.0.1). Scheduler chạy trong tiến trình, trừ khi `DF_DISABLE_SCHEDULER=1` | `scripts/start.ps1:22-25`; `backend/app/cli.py:94-96`; `backend/app/main.py:48-49` |
| Huấn luyện + dự báo production | **Không có lệnh CLI.** `POST /api/training/run` tạo job `TRAIN_PUBLISH`, job gọi `pipeline.train_and_publish`. Scheduler tự gọi mỗi ngày lúc `schedule.train_time` | `api/forecast_routes.py:47-49`; `jobs/runner.py:47,60`; `ml/pipeline.py:323`; `jobs/scheduler.py:130-147` |
| Backtest trong app | Không có lệnh riêng. Chạy bên trong `train_and_publish`, giai đoạn `BACKTESTING`, qua `model.backtest` | `ml/pipeline.py:478-479`; `ml/model.py:318` |
| Backtest lịch sử 21 lô (T6–T10) | `reports\backtest-20260601-20261022\code\backtest_runner.py`. File nằm **ngoài Git** (`reports/` bị ignore). Tham số: `--out` (bắt buộc), `--start` (mặc định 2026-06-01), `--end`, `--mode smoke\|run` (bắt buộc), `--smoke-days`, `--max-batches`. Cần `DF_DATA_DIR` trỏ tới bản sao DB (từ chối DB live), và cần import được package `app`. Bản sao DB tạo bằng `make_copy.py` | `backtest_runner.py:395-401`, `:114-117`, `:33-43`; `code/make_copy.py` |
| Lệnh chính xác đã dùng cho backtest lịch sử | **CHƯA RÕ.** README, run.log và báo cáo không ghi dòng lệnh. README chỉ ghi "Chạy lại đúng lệnh `--mode run` với cùng `--out`" | `reports/backtest-20260601-20261022/README.md:54` |
| Chạy test backend | `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | `AGENTS.md` §6; `scripts/run-tests.ps1:10` |
| Chạy test frontend | `cd frontend; npm test` (vitest run); `npm run typecheck`; `npm run build` | `frontend/package.json:8-10` |
| Test BigQuery thật (tự chọn) | `$env:DF_REAL_BQ = "1"`, rồi chạy pytest trên file `*_real_bq*.py`. Nếu không đặt biến thì test bị skip | `backend/tests/test_v121_d0_real_bq.py:10,22-23` |
| Lệnh chạy 8 test chống rò rỉ đã ghi | `PYTHONPATH=backend`; `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --rootdir backend <8 test>` | `reports/backtest-20260601-20261022/leakage/unit_tests.txt:6-16` |

### 1.3 Hệ thống cấu hình

**Nơi khai báo:**
- Không có YAML hay dataclass.
- Tham số là các lớp **Pydantic `BaseModel`** trong `backend/app/settings_service.py`.
- Mỗi section được lưu thành **một JSON trong bảng SQLite `app_settings`**, kèm lịch sử trong `settings_history`.
- Sửa qua `PUT /api/settings/{section}` (trang Cấu hình của UI).

```python
# backend/app/settings_service.py:563-573, :590-598 (rút gọn)
SECTIONS = {"sql_sources": SqlSourcesSettings, "general": GeneralSettings, "horizons": HorizonSettings,
            "quality": QualitySettings, "model": ModelSettings, "import": ImportSettings,
            "data_policy": DataPolicySettings, "schedule": ScheduleSettings, "bigquery": BigQuerySettings}
def save(section, value, note=None, conn=None):
    model = value if isinstance(value, cls) else cls.model_validate(value)
    js = model.model_dump_json()
    c.execute("INSERT INTO app_settings(section, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(section) ...")
    c.execute("INSERT INTO settings_history(section, value_json, changed_at, note) VALUES (?,?,?,?)", ...)
```

**Lưu ý quan trọng: mặc định trong code khác giá trị production.**
- Ví dụ: `ModelSettings.forecast_strategy` mặc định `"RECURSIVE"` (`settings_service.py:144`), `feature_customer` mặc định `False` (`:121`).
- Run production lưu `"forecast_strategy":"DIRECT"`, `"feature_customer":true` (`reports/model-learning-investigation-20261026/evidence/training-run-TRN-20261026031942-53C73F.json`, khóa `feature_config.config`).
- Giá trị đang lưu trong DB live: **CHƯA RÕ**. Phiên này không đọc DB hay API. Bằng chứng gián tiếp: cùng fingerprint `8468ebe66d1706f7` ở run 23/10 và run 26/10 (mục 7).

**Cấu hình lưu theo từng lần huấn luyện:**
- `training_runs.feature_config_json` (`features`, `config`, `config_fingerprint`, `feature_decisions`, `data_window`, …) và `params_json` (`model.lgb_params`): `ml/pipeline.py:394-417`.
- File phụ của model `models\MV-….json`: `ml/pipeline.py:615-628`.

**Biến môi trường:**

| Biến | Bằng chứng |
|---|---|
| `DF_PORT`, `DF_HOST` | `cli.py:95-96` |
| `DF_LOG_LEVEL`, `DF_DISABLE_SCHEDULER`, `DF_TICK_SECONDS` | `main.py:29,48-49` |
| `DF_DATA_DIR`, `DF_STORAGE_CONFIG`, `LOCALAPPDATA` | `paths.py:43,52,84-85` |
| `DF_FRONTEND_DIST` | `paths.py:260` |
| `DF_REAL_BQ` (chỉ test) | — |

Mẫu: `config/app.env.example`.

**Hằng số cứng (không cấu hình được):**

| Hằng số | Vị trí |
|---|---|
| `LAGS`, `ROLL_WINDOWS`, `LAST_SALE_WINDOW = 180`, `CUSTOMER_WINDOW = 28` | `ml/features.py:16-19,171` |
| `tweedie_variance_power 1.2`, `seed 7`, `min_data_in_leaf 20`, `feature_fraction/bagging 0.9`, `lambda_l2 1.0` | `ml/model.py:31-39` |
| `BASELINE_WINDOW_DAYS = 28` | `ml/model.py:23` |
| `REPEAT_LOOKBACK_DAYS = 90` | `data/customers.py:24` |
| `EQUAL_TOLERANCE` | `ml/pipeline.py:56` |

**Thêm một cờ mới vào cấu hình mô hình thì phải sửa:**

| # | Chỗ | Lý do / bằng chứng |
|---|---|---|
| 1 | `settings_service.py` `ModelSettings` (`:100-154`) | Khai báo trường, mặc định = hành vi cũ (`None`/`False`). Validator `_feature_groups` ở `:148-154` |
| 2 | `ml/features.py` (hàm đọc cờ, giống `discount_on`/`weekday_on` ở `:133-146`) | Dùng `getattr(cfg, "x", None)` để config cũ không có khóa vẫn chạy như trước |
| 3 | `ml/pipeline.py:394-417` | `settings_switches` liệt kê cứng các cờ (`:412-414`), `feature_groups`, `config_fingerprint` (`:409`) |
| 4 | `api/data_routes.py:46-51` | Nếu cờ không được để người dùng sửa (tiền lệ: `feature_open_hours` bị từ chối với `OPEN_HOURS_MANDATORY`) |
| 5 | `messages.py` | Mã `AppError` mới, kèm văn bản song ngữ (AGENTS §3) |
| 6 | `ml/feature_registry.py`, `ml/feature_catalog.py`, `ml/explain.py`, `ml/forecast_explainer.py`, `ml/training_explain.py` | Hiển thị và giải thích theo đúng cấu hình của run |
| 7 | `frontend/src/pages/Config.tsx` (ví dụ `:155-166`), `frontend/src/i18n.tsx` (ví dụ `:444-445`), `frontend/src/api.ts` | UI |
| 8 | `backend/tests/*`, `docs/MO-HINH-VA-CHI-SO.md`, `CHANGELOG.md` | AGENTS §10 |
| 9 | `reports/.../backtest_runner.py` (ngoài Git) | Nếu backtest lịch sử cần cờ đó |

```python
# backend/app/settings_service.py:124-128, :144-146
    min_total_history_days: int = Field(56, ge=14)
    min_series_history_days: int = Field(28, ge=7)
    intermittent_zero_share: float = Field(0.80, gt=0, le=1)
    inactive_days: int = Field(60, ge=7)
    fallback_window_days: int = Field(28, ge=7)
    ...
    forecast_strategy: Literal["RECURSIVE", "DIRECT"] = "RECURSIVE"
    direct_origins: int = Field(12, ge=1, le=52)
    direct_origin_step_days: int = Field(7, ge=1, le=30)
```

---

## 2. Luồng dữ liệu

### 2.1 Nguồn đầu vào và hàm đọc

Ba nguồn, không bao giờ trộn. Scope do `data/demand.py:resolve_scope` (`:109-137`) quyết định.

| Nguồn | Đường đi | Bằng chứng |
|---|---|---|
| **BIGQUERY**, D-1 (nguồn chính) | Bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`. Tên dataset/bảng nằm trong DB settings (mặc định trong code để trống: `settings_service.py:333-336`). SQL gom về ngày × SKU × FC: `bq/connector.py:_daily_sql` (`:1202-1285`). Job: `sync.run_d1_sync` (`sync.py:385`). Ghi bảng: `data/history_sync.py:_insert` (`:725-729`) | Tên bảng: `reports/backtest-20260601-20261022/README.md:13`; `run_config.json:6` |
| BIGQUERY, D-0 (trong ngày) | `bigquery.d0_table_id` = `...demand_planing_lightgbm_D0` (`settings_service.py:366`). `sync.run_d0_snapshot` (`sync.py:665`). **Chỉ** để hiển thị "thực tế hôm nay", không vào model | `data/demand.py:20-22` (`WINDOW_RULE`) |
| MANUAL_IMPORT (Excel `.xlsx`) | `data/importer.py` + `data/excel_io.py` ghi `order_lines`, rồi `demand.aggregate_batch` ghi `demand_daily` | `data/demand.py:140-153` |
| DEMO | `data/demo.py` | — |
| CSV | Không phải đầu vào của app (AGENTS §4). Các file CSV T06–T10 trong báo cáo điều tra 26/10 là trích xuất ngoài app, SQL không có trong repo | `reports/dieu-tra-30-cau-hoi-20261026/BAO_CAO_DIEU_TRA_30_CAU_HOI.md:216-219` |
| Tên sản phẩm (chỉ hiển thị) | Bảng `dim_sku` | `settings_service.py:372-374` |

**Đọc vào model:**
1. `data/demand.py:load_demand` (`:156-178`): một lần quét `demand_daily` theo scope, trong khoảng `[start, end]`.
2. `data/demand.py:data_window` (`:25-52`): cửa sổ = `window_start_date` (mặc định 2026-01-01) → hôm qua (giờ Việt Nam).
3. `ml/features.py:build_panel` (`:76-130`).

```python
# backend/app/bq/connector.py:1243-1250  (nhánh VALID của _daily_sql)
    valid = f"""SELECT 'VALID' AS _kind, CAST(NULL AS STRING) AS _reason, _order_date AS order_date, CAST(sku_id AS STRING) AS sku_id,
  CAST(fc_id AS STRING) AS fc_id, SUM(order_qty) AS qty, COUNT(DISTINCT CAST({oid} AS STRING)) AS n_orders,
  SAFE_DIVIDE(SUM({up} * order_qty), SUM(IF({up} IS NULL, NULL, order_qty))) AS avg_unit_price,
  SAFE_DIVIDE(SUM({disc}), SUM({up} * order_qty)) AS avg_discount_rate,
  AVG({pf}) AS promo_share, AVG({vf}) AS voucher_share,
  MAX({upd}) AS max_source_updated_at, MAX(CAST({bid} AS STRING)) AS max_batch_id, COUNT(*) AS n_rows,
  {oh}
FROM checked WHERE _reason IS NULL GROUP BY 3, 4, 5"""
```

**Quy tắc dòng nguồn:**

| Quy tắc | Bằng chứng |
|---|---|
| Dòng loại: SKU, FC hoặc qty NULL; qty âm | `connector.py:624-625` (`_REASON`) |
| Ngày = `DATE(order_date)`, hoặc `created_at` quy về giờ Việt Nam | `connector.py:553-560` |
| Đơn chờ xác nhận được miễn luật trùng | `connector.py:667-695` |
| Dòng nguồn biến mất được giữ lại (`KEEP_OBSERVED_LINES`) | `settings_service.py:186-190`; `data/history_sync.py` |

### 2.2 Panel `demand_daily`: grain, lấp ngày không đơn, NULL

**Bảng `demand_daily`:**
- Grain: `(scope_key, order_date, sku_id, fc_id)`; `qty REAL NOT NULL` (`migrations/0001_initial.sql:80-94`).
- Các cột thêm sau: `open_hours`, `open_hours_status` (0007); `customer_count`, `repeat_customer_count`, `repeat_interval_days_sum` (0008).
- **Chỉ có dòng cho ngày có ít nhất 1 dòng đơn hợp lệ.** Không có dòng "ngày không đơn".

**Panel** (`ml/features.py:Panel` `:27-64`, `build_panel` `:76-130`):
- Grain **SKU × FC × ngày lịch**. Ma trận S × T, một cột cho mỗi ngày.
- Khóa chuỗi = mọi cặp (sku_id, fc_id) có ít nhất 1 dòng trong cửa sổ (`:90-91`).
- **Ngày không có đơn điền 0**, sau ngày đơn đầu tiên của chuỗi, với điều kiện cả scope có dữ liệu ngày đó.
- NaN = (a) trước ngày có đơn đầu tiên của chuỗi trong panel; (b) ngày lịch mà cả scope không có dòng nào (`missing_days`). Bản sao production 23/10 có 0 ngày như vậy (`run.log:1`).

```python
# backend/app/ml/features.py:96-99, :120-124
    Y = np.zeros((S, T))
    Y[si, ti] = d["qty"].to_numpy(dtype=float)
    present = np.zeros((S, T), dtype=bool)
    present[si, ti] = True
    ...
    first =np.where(present.any(axis=1), present.argmax(axis=1), T)
    missing_days = ~present.any(axis=0)
    # not started yet -> NaN ; whole-calendar gaps -> NaN (unknown, not "zero demand")
    Y[np.arange(T)[None, :] < first[:, None]] = np.nan
    Y[:, missing_days] = np.nan
```

**Xử lý NULL theo cột:**

| Cột | Xử lý | Bằng chứng |
|---|---|---|
| `qty` | Không thể NULL (NOT NULL) | — |
| Giá, chiết khấu | NaN rồi **forward-fill** theo chuỗi | `:100-106`, `:127` (`_ffill_rows` `:67-73`) |
| `promo_share` | NULL thành **0** (`nan_to_num`) | `:107-108` |
| `open_hours` | NULL thành NaN, **không** ffill, không thay bằng 0 | `:109-111` |
| Số khách | NULL thành NaN; không tạo mảng nếu cả frame không có giá trị | `:112-119` |

`max_days` (`max_train_days` 730) chỉ cắt khi khoảng dữ liệu dài hơn 730 ngày (`:86-87`).

### 2.3 `total_open_hours` / `open_hours`

**Nguồn:** cột `total_open_hours` của bảng D-1, ánh xạ thành trường tham chiếu `open_hours`, vai trò `REQUIRED_FEATURE` (`connector.py:62`; `settings_service.py:41-45`).

**Gom về ngày × SKU × FC:**
- Bước 1, trong SQL D-1: đếm số dòng thiếu giá trị, MIN/MAX, và số item (`connector.py:1218-1231`).
- Bước 2, trong Python: `data/open_hours.py:cell` (`:57-74`) quy ra một giá trị và một trạng thái OK / MISSING / OUT_OF_RANGE / CONFLICT / MULTI_ITEM.
- Chỉ trạng thái OK có giá trị. Riêng 6 khóa MULTI_ITEM dùng luật MAX của chủ hệ thống (`data/open_hours_override.py`).

```python
# backend/app/data/open_hours.py:64-74
    if int(null_rows or 0) > 0 or lo is None or hi is None:
        return None, "MISSING"
    lo, hi = float(lo), float(hi)
    if lo < MIN_HOURS or hi > MAX_HOURS:
        return None, "OUT_OF_RANGE"
    if hi != lo:
        if (items is not None and item_values is not None and int(items) > 1 and int(item_values) == int(items)
                and not int(no_item_rows or 0)):
            return None, "MULTI_ITEM"
        return None, "CONFLICT"
    return lo, "OK"
```

**Kết luận: chỉ có giờ mở bán cho NGÀY CÓ ĐƠN, không có cho mọi ngày.**
- Giờ được gom trên các dòng đơn hợp lệ (`WHERE _reason IS NULL GROUP BY 3, 4, 5`, `connector.py:1250`).
- Ngày không có dòng đơn thì không có dòng trong `demand_daily`, nên panel có `hours = NaN` (`features.py:39-41`, `:109-111`).
- Test `test_v129_weekday_open_hours.py:428` (`test_panel_takes_open_hours_from_the_demand_rows_only`) khẳng định điều này.

**Ngày có đơn nhưng giờ = 0:**
- Lưu là 0, trạng thái OK.
- Vào feature là 0, không bị mang sang ngày khác.
- Bằng chứng: `backend/tests/test_v129f_zero_open_hours.py:1-6, :20-57`.

**Bắt buộc với BIGQUERY:**
- Huấn luyện dừng (`OPEN_HOURS_INVALID`) nếu có dòng trong cửa sổ không OK (`ml/pipeline.py:357-368`, `:455-465`).
- DEMO và Excel không có cột này (`data/open_hours.py:52-54`).

### 2.4 `sku_system_status`

**Không phải đầu vào model.** Chỉ dùng ở các chỗ sau:

| # | Chỗ dùng | Bằng chứng |
|---|---|---|
| a | Ánh xạ thành trường tham chiếu `sku_status` | `connector.py:61` |
| b | Thuộc `REF_CATEGORY`. Trong kiểm tra nguồn, chỉ đếm phân bố giá trị | `connector.py:49`, `:965-969` |
| c | Feature **PLANNED**, chưa kích hoạt, trong registry | `ml/feature_registry.py:126-128` |
| d | SQL D-0 do người dùng cung cấp (bản seed 1, chưa xác thực) có lọc `c.sku_system_status IN ('OUT_OF_STOCK','LIMIT','NORMAL')`. SQL D-0 chỉ phục vụ snapshot trong ngày | `bq/d0_user_sql_20261015.sql:22`; `bq/d0_proposed_v2_20261015.sql:15`; `settings_service.py:542-553` |

```python
# backend/app/ml/feature_registry.py:126-128
    dict(key="sku_status", group="SKU_AVAILABILITY", data_type="category", reference="sku_status",
         vi=("Trạng thái SKU", "Trạng thái hệ thống của SKU; cần biết giá trị có tại thời điểm dự báo hay là trạng thái cập nhật sau."),
         en=("SKU status", "System status of the SKU; must be known at forecast time (not a later update).")),
```

**Ngữ nghĩa** (theo tài liệu, không phải code): cột này là trạng thái hiện tại, gần như không đổi theo ngày (`docs/BIGQUERY.md:426`). Báo cáo 26/10 xác nhận trong CSV đây là trạng thái lúc trích, chép vào mọi ngày (`reports/dieu-tra-30-cau-hoi-20261026/...:278-294`).

---

## 3. Biến đầu vào (36 biến)

**Bộ 36 biến** là cấu hình CAND của backtest và của model production `MV-20261026-105345-C73F`.

Bằng chứng:
- Danh sách `features` trong `training-run-TRN-20261026031942-53C73F.json`;
- `BATCH_TRAINING_SCHEDULE.csv` cột `cand_n_features` = 36.

**Cách ra con số 36** (`ml/features.py:feature_names` `:187-209`):

| Nhóm | Số biến |
|---|---:|
| Định danh | 3 |
| Lag | 10 |
| Rolling | 9 |
| Giá | 2 |
| Giờ mở bán | 2 |
| Khách hàng | 3 |
| Lịch của ngày đích | 6 |
| `horizon` | 1 |
| **Tổng** | **36** |

- `disc_last`, `promo_last`, `promo_mean_7` có trong code nhưng **không** dùng, vì nguồn không có dữ liệu (`registry.resolve` NO_DATA).
- Thứ tự cột DIRECT: biến tại mốc (bỏ lịch), rồi lịch của ngày đích, rồi `horizon` (`:205-208`).

**Quy ước của bảng dưới:**
- `t` là chỉ số ngày truyền vào `features_at` (`:236-304`). Với DIRECT, `t` = **mốc** `t0` (`origin_features` `:332-334`).
- `hist = Y[:, :t]`, nghĩa là chỉ ngày < t.
- "Đến ngày" = ngày cuối cùng được đọc. Mốc dự báo production = ngày sau `train_end`, nên mọi biến tại mốc đọc tới `train_end` (= `data_as_of`, hôm qua của ngày chạy).

| # | Biến | file:hàm:dòng | Công thức thực tế trong code | Cửa sổ dữ liệu (đến ngày nào) |
|---|---|---|---|---|
| 1 | `sku_code` | features.py:`features_at`:240; `static_codes`:337-341 | Chỉ số SKU trong danh sách SKU đã sắp xếp lúc huấn luyện; −1 nếu không có; categorical (`model.py:72`) | Danh mục của panel huấn luyện |
| 2 | `fc_code` | như trên | Chỉ số FC (BD = 0, HN = 1 theo metadata model); categorical | như trên |
| 3 | `series_age` | features_at:240 | `t − start_idx`; `start_idx` = ngày có đơn đầu tiên **trong panel** (panel bắt đầu 01/01/2026) | Tại mốc |
| 4–13 | `lag_1…lag_7, lag_14, lag_21, lag_28` | features_at:242-244 | `Y[:, t−k]`, NaN nếu t−k < 0 | Ngày t−k; `lag_1` = mốc − 1 |
| 14–17 | `roll_mean_7/14/28/56` | features_at:245-247; `_nanmean`:212-216 | Trung bình các ngày đã biết (không NaN) trong `[t−w, t)`; ngày 0 được tính | `[mốc−w, mốc−1]` |
| 18 | `roll_std_7` | features_at:248; `_nanstd`:228-233 | Độ lệch chuẩn tổng thể (ddof 0) trên `[t−7, t)`; NaN nếu < 2 ngày đã biết | `[mốc−7, mốc−1]` |
| 19 | `roll_std_28` | features_at:249-250 | Như trên, trên `[t−28, t)` | `[mốc−28, mốc−1]` |
| 20 | `zero_share_28` | features_at:251-253 | Số ngày = 0 ÷ số ngày đã biết trong `[t−28, t)` | `[mốc−28, mốc−1]` |
| 21 | `days_since_last_sale` | features_at:254-258 | `w = hist[:, t−180:t]`; ngày "có bán" = `nan_to_num(w) > 0.5`; giá trị = số ngày từ ngày bán cuối tới t (1 = hôm qua); 181 nếu không có ngày bán | `[mốc−180, mốc−1]` |
| 22 | `roll_max_28` | features_at:259-263 | Max các ngày đã biết trong `[t−28, t)` | `[mốc−28, mốc−1]` |
| 23 | `price_last` | features_at:269-270 | `price[:, t−1]`; giá đã forward-fill (giá biết gần nhất ≤ t−1) | mốc − 1 (giá trị ffill có thể cũ hơn) |
| 24 | `price_rel_28` | features_at:271-273 | `price_last ÷ mean(price[t−28:t])` nếu mean > 0 | `[mốc−28, mốc−1]` |
| 25 | `open_hours_last` | features_at:279-287 | `hours[:, t−1]`, NaN nếu ngày đó không có dòng đơn hoặc không OK | mốc − 1 |
| 26 | `open_hours_mean_7` | features_at:288-289 | Trung bình các ngày đã biết trong `hours[:, t−7:t]` | `[mốc−7, mốc−1]` |
| 27 | `cust_mean_28` | features_at:290-300 | Trung bình số khách khác nhau của các ngày đã biết trong `[t−28, t)` | `[mốc−28, mốc−1]` |
| 28 | `cust_repeat_share_28` | features_at:301; `_ratio`:219-225 | Σ khách quay lại ÷ Σ khách (ngày có cả hai giá trị) | `[mốc−28, mốc−1]`; khách quay lại = đơn trước đó trong 90 ngày (`connector.py:1303-1309`) |
| 29 | `cust_repeat_interval_28` | features_at:302 | Σ số ngày từ lần đặt trước ÷ Σ khách quay lại | như trên |
| 30 | `dow` | `calendar_row`:319-323; `direct_extra`:326-329 | ISO 1 = Thứ 2 … 7 = Chủ nhật (`weekday_encoding="ISO"`); model trước 1.2.9 dùng 0..6 | **Ngày đích** (biết trước) |
| 31 | `dom` | như trên | `d.day` | Ngày đích |
| 32 | `month` | như trên | `d.month` | Ngày đích |
| 33 | `weekofyear` | như trên | `d.isocalendar()[1]` | Ngày đích |
| 34 | `is_weekend` | như trên | 1 nếu `iso_weekday ≥ 6` | Ngày đích |
| 35 | `days_to_month_end` | như trên | `days_in_month − day` | Ngày đích |
| 36 | `horizon` | `direct_extra`:329 | `h` (1 = ngày dự báo đầu tiên) | — |

```python
# backend/app/ml/features.py:205-208, :326-334
    if is_direct(cfg):
        # features at the ORIGIN (calendar removed), then the calendar of the TARGET day and the horizon (1 = first
        # forecast day); same column order as the experiment harness (L7_direct)
        names = [n for n in names if n not in CALENDAR] + calendar_names(cfg) + ["horizon"]
...
def direct_extra(cfg, target_day, h: int) -> list[float]:
    cal = calendar_names(cfg)
    return [v for n, v in zip(CALENDAR, calendar_row(target_day, cfg)) if n in cal] + [float(h)]
def origin_features(p: Panel, Y, price, disc, promo, dates, t0: int, cfg, sc, fcc) -> np.ndarray:
    return features_at(p, Y, price, disc, promo, dates, t0, _NoCalendar(cfg), sc, fcc)
```

### Mở rộng theo horizon trong kiến trúc DIRECT

**Huấn luyện:**
- Với mỗi mốc `t0` và mỗi `h = 1..H`, tạo một dòng gồm: biến tại `t0` (dữ liệu < t0), lịch của ngày đích `t0+h−1`, `horizon = h`.
- Nhãn = `Y[t0+h−1]`.
- `H = direct_max_horizon = backtest_horizon_days = 30` (`model.py:42-44`; `features.py:403-444`).

**Dự báo:**
- Biến tính **một lần** tại mốc `T` (ngày sau `train_end`).
- Mỗi `h` chỉ đổi phần lịch và `horizon`.
- Không đưa giá trị dự báo ngược vào feature (`model.py:_forecast_direct` `:196-219`).
- Kỳ dự báo > 30 ngày bị từ chối (`DIRECT_HORIZON_EXCEEDS_TRAINING`, `model.py:200-201`; `pipeline.py:382-384`).

**Hệ quả:** với ngày đích D = T + h − 1, mọi biến lịch sử vẫn dừng ở T − 1. Ví dụ ở h = 7, `lag_1` là ngày D − 7.

**Kỳ đang công bố:** run 26/10 công bố 15 ngày (26/10–09/11, theo `direct-label-calendar.txt`, dòng cuối). Giá trị `horizons.enabled` đang lưu: CHƯA RÕ (mặc định trong code `[7, 15, 30]`, `settings_service.py:63`).

---

## 4. Luật FALLBACK

**Vị trí:**
- Hàm `ml/model.py:classification_details` (`:89-133`), được `classify_series` (`:83-86`) gọi.
- Dùng trong `forecast` (`:160`), `pipeline.candidate_forecast` (`:177`), `_publish_run` (`series_meta` `:263`) và phần giải thích.
- Áp dụng **tại mốc dự báo T, trên panel dữ liệu < T**.

**Thứ tự điều kiện** (luật đầu tiên khớp sẽ thắng):

| # | Điều kiện | Mã sinh ra | Giá trị dự báo |
|---|---|---|---|
| 1 | Tổng cầu đã biết trong `inactive_days` ngày lịch cuối = 0 **và** tuổi chuỗi ≥ `inactive_days` | `FALLBACK_INACTIVE_ZERO` (lý do `INACTIVE`) | 0 |
| 2 | Tuổi chuỗi < `min_series_history_days` | `FALLBACK_NEW_SERIES` (`NEW_SERIES`) | Σ ngày đã biết ÷ số ngày đã biết, từ đầu chuỗi |
| 3 | Tỷ lệ ngày = 0 trên các ngày đã biết trong `2 × fallback_window_days` (56) ngày cuối ≥ `intermittent_zero_share` | `FALLBACK_INTERMITTENT` (`INTERMITTENT`) | Σ ÷ số ngày đã biết trong `fallback_window_days` (28) ngày cuối |
| 4 | Còn lại | `LIGHTGBM` (`LIGHTGBM_ELIGIBLE`) | Model |

- Giá trị fallback là hằng số cho mọi `h` (`model.py:184`, `:212`).
- Mã thêm, chỉ có trong backtest: `FALLBACK_MODEL_UNAVAILABLE`, khi không có booster (`model.py:161-167`).
- Mã của ứng viên baseline: `BASELINE_MOVING_AVERAGE` (`model.py:22`).
- Hằng mã: `model.py:16-22`. Registry nhãn UI và xuất file: `ml/methods.py:14-93`.

**Ngưỡng 60 / 28 / 0,80 / 28:**

| Trường | Giá trị | Vị trí |
|---|---:|---|
| `inactive_days` | 60 | `settings_service.py:127` |
| `min_series_history_days` | 28 | `:125` |
| `intermittent_zero_share` | 0.80 | `:126` |
| `fallback_window_days` | 28 | `:128` |

- Run production lưu đúng các giá trị này (`feature_config.config` trong file JSON bằng chứng).
- Cửa sổ 56 ngày = `cfg.fallback_window_days * 2`, viết cứng (`model.py:107`).

```python
# backend/app/ml/model.py:106-129 (rút gọn)
    age = T - p.start_idx
    zs_win = cfg.fallback_window_days * 2
    win = p.Y[:, max(0, T - zs_win):]
    nn = np.sum(~np.isnan(win), axis=1)
    zeros = np.sum(win == 0, axis=1)
    zero_share = np.where(nn > 0, zeros / np.maximum(nn, 1), 1.0)
    recent = p.Y[:, max(0, T - cfg.inactive_days):]
    sold_recent = np.nansum(recent, axis=1) > 0
    ...
    for s in range(S):
        if not sold_recent[s] and age[s] >= cfg.inactive_days:   methods[s], rate[s], reasons[s] = FB_INACTIVE, 0.0, "INACTIVE"
        elif age[s] < cfg.min_series_history_days:               methods[s], rate[s], reasons[s] = FB_NEW, hist_rate[s], "NEW_SERIES"
        elif zero_share[s] >= cfg.intermittent_zero_share:       methods[s], rate[s], reasons[s] = FB_INTERMITTENT, fb_rate[s], "INTERMITTENT"
```

**Các chỗ khác cũng dùng 4 ngưỡng này:**

| Chỗ | Vai trò | Bằng chứng |
|---|---|---|
| `data/quality.py` | Báo cáo chất lượng dữ liệu đếm SHORT / INACTIVE / INTERMITTENT, với công thức xấp xỉ riêng | `:88-101` |
| `ml/explain.py`, `ml/training_explain.py` | Giải thích | `explain.py:285-289,350`; `training_explain.py:90-91` |
| Frontend | Văn bản có ghi số 60 / 28 / 56 / 80 % | `frontend/src/algorithms.ts:161-178` |
| `ml/methods.py` | Văn bản có ghi số | `:19,32,45,58` |

**Ngày đóng bán:** luật **không** dùng giờ mở bán. Ngày không có đơn sau khi chuỗi bắt đầu là 0, nên bị đếm vào tử số của `zero_share`, và tính là "không bán" cho luật INACTIVE.

---

## 5. Tạo nhãn và cửa sổ huấn luyện

**Cửa sổ nhãn 84 ngày = `direct_origins` (12) × `direct_origin_step_days` (7).**
- Khai báo ở `settings_service.py:145-146`.
- Hàm `ml/features.py:direct_training_matrix` (`:403-444`), gọi từ `model.train` (`model.py:52`).
- Các mốc: `t0 = T − 7j`, với `j = 1..12`, dừng nếu `t0 < 7` (`:412-415`).
- Nhãn `Y[t0+h−1]`, chỉ lấy khi `t0+h−1 < T`. Vì vậy ngày nhãn nằm trong `[T−84, T−1]`, tức **cửa sổ trượt**.
- Mốc gần nhất chỉ có h nhỏ. Ở run 26/10: mốc 1 chỉ có h = 1..7; h = 29–30 chỉ có 8 mốc (`direct-label-calendar.txt`).

**Lịch sử dùng tính feature: mở rộng** từ `window_start_date` (01/01/2026) tới `train_end`, giới hạn `max_train_days` 730 (`data/demand.py:25-52`; `features.py:86-87`).

**Lọc chuỗi đưa vào model:**

| Quy tắc | Bằng chứng |
|---|---|
| Một dòng (chuỗi, mốc, h) được dùng khi nhãn đã biết (không NaN; **0 vẫn được dùng**) **và** chuỗi đã bắt đầu trước mốc (`t0 > start_idx`) | `:417`, `:437` |
| **Không lọc theo phương pháp fallback**: chuỗi INACTIVE / INTERMITTENT / NEW tại thời điểm dự báo vẫn có dòng huấn luyện | `model.train` (`:47-80`) không có điều kiện method |
| Không có trần số dòng cho DIRECT | `max_rows = 4_000_000` chỉ áp cho `training_matrix` RECURSIVE (`:376-383`) |

```python
# backend/app/ml/features.py:410-418
    if not with_index:
        plan = []
        for j in range(1, cfg.direct_origins + 1):
            t0 = T - j * cfg.direct_origin_step_days
            if t0 < 7:
                break
            plan.append((t0, [(h, t0 + h - 1, ok) for h in range(1, horizon + 1) if t0 + h - 1 < T
                              for ok in [~np.isnan(p.Y[:, t0 + h - 1]) & (t0 > p.start_idx)] if ok.any()]))
```

**Số liệu đo được (run production 26/10):**
- Panel 01/01–25/10/2026, T = 298.
- Nhãn 03/08–25/10 (84 ngày).
- 5.218.927 dòng huấn luyện, 17.150 chuỗi.

Nguồn: `direct-label-calendar.txt`; `training-run-...json` (`n_rows`, `n_series`).

---

## 6. Huấn luyện

**Hàm:** `ml/model.py:train` (`:47-80`):
- `lgb.Dataset(X, y, categorical_feature=["sku_code","fc_code"])`;
- `lgb.train(lgb_params(cfg), ds, num_boost_round=cfg.num_boost_round)`;
- **không** có early stopping hay tập validation;
- trả `None` nếu < 100 dòng hoặc Σy ≤ 0.

`weights` chỉ dùng cho thí nghiệm; app không truyền (`:48-50`; test `test_v129c_window_spike_customer.py:339`).

**Nguồn siêu tham số:**

| Tham số | Nguồn | Vị trí |
|---|---|---|
| `objective`, `learning_rate`, `num_leaves`, `num_boost_round`, `num_threads` | `ModelSettings` | `settings_service.py:134-139` |
| Các giá trị còn lại | Viết cứng | `lgb_params` |

**Giá trị production:**
- Tweedie, power 1,2;
- lr 0,05; 31 lá; 300 vòng;
- seed 7.

Nguồn: `params` trong file JSON bằng chứng.

```python
# backend/app/ml/model.py:31-39
def lgb_params(cfg, seed: int = 7) -> dict:
    p = {"objective": cfg.objective, "learning_rate": cfg.learning_rate, "num_leaves": cfg.num_leaves,
         "min_data_in_leaf": 20, "feature_fraction": 0.9, "bagging_fraction": 0.9, "bagging_freq": 1,
         "lambda_l2": 1.0, "verbose": -1, "seed": seed, "deterministic": True, "force_row_wise": True}
    if cfg.objective == "tweedie":
        p["tweedie_variance_power"] = 1.2
    if cfg.num_threads:
        p["num_threads"] = cfg.num_threads
    return p
```

**Một model chung cho mọi FC.**
- Một booster mỗi lần huấn luyện.
- Lưu `models\MV-<thời gian>-<4 ký tự>.txt` kèm `.json` (`features`, `sku_codes`, `fc_codes`, `forecast_strategy`, `max_horizon`): `pipeline.py:_save_model` (`:615-628`).

**Chuỗi các bước trong `train_and_publish`** (`pipeline.py:323-597`):

| # | Bước | Dòng |
|---|---|---|
| 1 | Kiểm tra nguồn | `:330-339` |
| 2 | Fingerprint dữ liệu; nếu không đổi thì `SKIPPED` | `:343-364` |
| 3 | Giờ mở bán | `:357-368` |
| 4 | `registry.resolve`, quyết định nhóm feature theo độ phủ | `:371-380` |
| 5 | `load_demand` + `build_panel` | `:450-466` |
| 6 | `model.backtest` | `:478-479` |
| 7 | `model.train` | `:480-481` |
| 8 | Quality gate và chọn ứng viên | `:482-491` |
| 9 | So với model đang dùng | `:522-530` |
| 10 | Nếu đang có model dùng: chỉ lưu **ứng viên chờ duyệt** | `:538-563` |
| 11 | Nếu chưa có: dự báo và publish | `:564-588` |

---

## 7. Vòng lặp backtest

### 7.1 Backtest trong app (dùng cho quality gate)

**Hàm `ml/model.py:backtest`** (`:318-391`):
- Fold k có mốc `origin = T − H − (F−1−k)·step`, với H = 30, F = 12, step = 30 (`settings_service.py:131-133`).
- Bỏ fold nếu `origin < min_total_history_days` (56).
- Mỗi fold: `train(p.truncate(origin))`, rồi `forecast(…, H)`, chấm trên `~isnan(actual)`.
- Baseline = trung bình 28 ngày, tính trên cùng điểm.

**Quality gate** (`pipeline.py:31-52`):
- Điều kiện: `BACKTEST_RELIABLE`, `MIN_BACKTEST_POINTS ≥ 200`, `WAPE_MAX ≤ 0,60`, `ABS_BIAS_MAX ≤ 0,20`, và `BEAT_BASELINE` nếu bật.
- Ngưỡng ở `settings_service.py:91-97`. `approved_by_business = False`.
- Chính sách `PUBLISH_WITH_WARNING`.

**Lưu ý đã được audit ghi nhận:** `Panel.truncate` giữ mọi khóa chuỗi, nên chuỗi xuất hiện sau mốc fold vẫn bị chấm (`reports/backtest-audit-20260601-20261023/LEAKAGE_AUDIT.md:82-84`).

```python
# backend/app/ml/model.py:330-343
    for k in range(F):
        origin = T - H - (F - 1 - k) * step
        if origin < cfg.min_total_history_days:
            notes.append({"code": "FOLD_SKIPPED_SHORT_HISTORY", "fold": k + 1, "origin_index": int(origin)})
            continue
        if cancel and cancel():
            raise Cancelled()
        train_p = p.truncate(origin)
        booster, _ = train(train_p, cfg, cancel)
        fc = forecast(train_p, booster, cfg, H, cancel)
        actual = p.Y[:, origin:origin + H]
        base = baseline_forecast(train_p, H)
        valid = ~np.isnan(actual)
        a, f, b = actual[valid], fc["yhat"][valid], base[valid]
```

### 7.2 Backtest lịch sử 21 lô (T6–T10)

**Nằm ngoài Git:** `reports/backtest-20260601-20261022/code/backtest_runner.py`, SHA-256 `D8DE6DAB…AAE60` (`code/SHA256SUMS.txt:2`). Runner gọi lại code app 1.2.13 (commit `1b00c42`).

**21 lô "thứ Hai":**
- `make_batches` (`:310-317`) cắt từ `--start` mỗi 7 ngày tới `last` (watermark D-1 = 2026-10-22).
- "Thứ Hai" đến từ **ngày bắt đầu mặc định 2026-06-01** (một thứ Hai, `:397`), **không** đến từ logic theo thứ trong tuần.
- Lô cuối 19–22/10, gồm 4 ngày.

**Mỗi lô** (`run_batch` `:214-307`):
1. Lấy frame < mốc `c`.
2. Huấn luyện 2 model CAND và PROD trên cùng panel.
3. Với mỗi ngày D trong lô: dựng lại panel từ dữ liệu < D (`panel_before` `:178-181`), dự báo **h = 1** bằng model của lô (`:261`).
4. Thêm góc nhìn "gốc theo tuần" h = 1..7 (`:248`), chỉ để đánh giá.

**Nhánh CAND:**
- `cand_config` (`:170-175`): độ phủ tính trên frame < mốc, rồi `registry.resolve(settings đã lưu trong bản sao DB)`, rồi `feature_open_hours=True`, `weekday_encoding="ISO"`.
- Đúng như `train_and_publish`.
- PROD = cấu hình đã lưu của model đang dùng lúc đó (`MV-20261020-131556-EEF6`, 31 biến).
- BASE = trung bình 28 ngày.

```python
# reports/backtest-20260601-20261022/code/backtest_runner.py:170-175, :184-189
def cand_config(data: Data, frame_c: pd.DataFrame):
    cov = registry.coverage_of_frame(frame_c)
    cfg, decisions = registry.resolve(data.mcfg_settings, cov)
    cfg = cfg.model_copy(update={"feature_open_hours": True, "weekday_encoding": "ISO"})
    return cfg, cov, {g: {"used": d["used"], "reason": d["reason"], "coverage": d["coverage"]} for g, d in decisions.items()}
def config_summary(cfg) -> dict:
    names = feature_names(cfg)
    dump = cfg.model_dump()
    return {"features": names, "n_features": len(names), "forecast_strategy": "DIRECT" if is_direct(cfg) else "RECURSIVE",
            "config_fingerprint": hashlib.sha256(json.dumps(dump, sort_keys=True, default=str).encode()).hexdigest()[:16],
```

**Fingerprint `8468ebe66d1706f7`:**
- **Cách tính:** `sha256(json.dumps(ModelSettings.model_dump(), sort_keys=True))[:16]`, tức hash của **toàn bộ** cấu hình mô hình đã resolve (mọi trường, kể cả ngưỡng fallback, tham số backtest, DIRECT).
  - Trong runner: `config_summary` dòng 188.
  - Trong app: `pipeline.py:409`, cùng công thức (`default=str` không làm khác kết quả khi mọi giá trị là JSON thuần).
- **Nơi ghi nhận:** checkpoint `batch_NN.json` (`models.CAND.config_fingerprint`), được `reports/backtest-audit-20260601-20261023/code/audit_analysis.py:50,66` tổng hợp vào `audit_summary.json:11-13` và `BATCH_TRAINING_SCHEDULE.csv`.
- **Trùng với:**
  - run production `TRN-20261026031942-53C73F` (`"config_fingerprint":"8468ebe66d1706f7"` trong JSON bằng chứng);
  - candidate `TRN-20261023055745-933B70` (`LEAKAGE_AUDIT.md:26`).
- **Hệ quả cho việc sửa:** thêm bất kỳ trường nào vào `ModelSettings` sẽ làm đổi fingerprint của mọi run mới, kể cả khi cờ tắt. Tiền lệ đo được: fingerprint PROD `da229f54…` khác `e9bf1939…` lưu trong run gốc chỉ vì khi validate có thêm 3 trường mặc định (`LEAKAGE_AUDIT.md:27`).

**165 kiểm tra rò rỉ:**
- **Không phải** một bộ test riêng. Đây là các bản ghi `leakage_checks` mà `run_batch` tự ghi khi chạy `--mode run`.
- Gồm 21 kiểm tra "train" (1 mỗi lô: `frame_max_date < origin`, `:234-235`) và 144 kiểm tra theo ngày (1 mỗi ngày D: `frame_max_date < D` và `panel_last_day < D`, `:292-293`).
- 21 + 144 = 165 (lô 1 có 8 = 1 + 7 ngày; lô 21 có 5 = 1 + 4).
- Đếm bởi `audit_analysis.py:54-55, 68`. Kết quả `audit_summary.json:23-24`: 165/165.
- Có thêm `assert` cứng ở `:220`, `:255`, `:262`.
- Test nhiễu loạn T1/T2/T3 (`leakage_tests` `:333-381`) chỉ chạy ở `--mode smoke`, **1 mốc và 1 ngày** (01/06 và 03/06): `LEAKAGE_AUDIT.md:67,73-75`.
- 8 test unit chống rò rỉ của repo: `leakage/unit_tests.txt:9-18`.

```python
# reports/backtest-20260601-20261022/code/backtest_runner.py:234-235, :292-293
    rec["leakage_checks"]["train"] = {"frame_max_date": str(fmax), "panel_last_day": str(panel_c.dates[-1].date()),
                                      "rule": "frame and panel end before the batch origin", "passed": fmax < origin}
...
        rec["leakage_checks"][str(D)] = {"passed": fDmax < D and pD.dates[-1].date() < D, "frame_max_date": str(fDmax),
                                         "panel_last_day": str(pD.dates[-1].date())}
```

**Thời gian chạy mỗi lô** (có log):

| Phần | Thời gian | Nguồn |
|---|---|---|
| Mỗi lô | 202,6–299,6 giây | `reports/backtest-20260601-20261022/run.log:5-45` |
| Tổng 21 lô | 93 phút | `BAO_CAO_BACKTEST.md:160` |
| Huấn luyện mỗi model, nhánh CAND | 96,7–133,3 giây | `BAO_CAO_BACKTEST.md:161-181` |
| Huấn luyện mỗi model, nhánh PROD | 88,3–123,7 giây | như trên |
| Nạp dữ liệu | 51,1 giây | `run_config.json:87` |
| Smoke | 251 giây | `run.log:2` |

Run production 26/10 (trong app, gồm backtest nội bộ, huấn luyện và so sánh) chạy từ 03:19:42 tới 03:53:46 UTC, khoảng 34 phút (`started_at`/`finished_at` trong JSON bằng chứng).

---

## 8. Xuất kết quả

**Ghi dự báo vào DB:** `pipeline.py:_publish_run` (`:250-279`).
- Bảng `forecast_values`: `(run_id, sku_id, fc_id, target_date, horizon_day, yhat, method, fallback_reason)`, với `yhat = round(yhat, 4)` (`:261`).
- Bảng `forecast_series_meta`: lý do phương pháp từng chuỗi.
- Bảng `forecast_runs`: `forecast_origin` = ngày sau dữ liệu cuối, `data_as_of`.
- Sau khi commit: lưu lịch sử D+1 (`forecast_history.capture_after_publish`, `pipeline.py:581`).
- Trước đó, dự báo đã được **cắt ≥ 0** (`model.py:190`, `:218`, `:243`).

```python
# backend/app/ml/pipeline.py:258-262
    for s, (sku, fcid) in enumerate(panel.keys):
        fb = None if methods[s] in (model.METHOD_LGBM, model.METHOD_BASELINE) else methods[s]
        for h, dte in enumerate(fc["dates"]):
            vals.append((fr_id, sku, fcid, str(dte.date()), h + 1, float(round(fc["yhat"][s, h], 4)),
                         str(methods[s]), fb))
```

**Làm tròn khi hiển thị và xuất:** `backend/app/qty.py:12-20`.
- Làm tròn nửa lên, không âm: `CAST(MAX(yhat, 0) + 0.5 AS INTEGER)`.
- Dùng ở `api/forecast_routes.py:27,286,312,318,320,356`.
- Tổng kỳ = tổng các số nguyên theo ngày (`:373`).
- WAPE, bias và quality gate dùng `yhat` chưa làm tròn (docstring `qty.py:1-6`).

```python
# backend/app/qty.py:12-20
RULE = "ROUND_HALF_UP_NON_NEGATIVE"
# SQL form of business_qty() over a column `yhat`; CAST truncates toward zero, which is floor() for MAX(yhat, 0) + 0.5
SQL = "CAST(MAX(yhat, 0) + 0.5 AS INTEGER)"
def business_qty(yhat: float | None) -> int | None:
    if yhat is None or (isinstance(yhat, float) and math.isnan(yhat)):
        return None
    return int(math.floor(max(float(yhat), 0.0) + 0.5))
```

**File Excel của app:** `GET /api/forecast-runs/{id}/export.xlsx` (`forecast_routes.py:345-399`).
- 3 sheet: thông tin, tổng kỳ, theo ngày.
- **Cột theo ngày** (vi, `export_i18n.py:30-33`): SKU, Tên sản phẩm, FC/kho, Ngày, Thứ trong tuần, Ngày thứ, Số lượng dự báo, Thực tế đến hiện tại, Phương pháp, Mã kỹ thuật phương pháp.
- **Cột tổng kỳ:** `export_i18n.py:28-29`.

**File Excel của backtest lịch sử** (ngoài Git): `backtest_report.py:write_excel` (`:63-91`).
- Đúng 8 cột (`COLS` `:23`): SKU, Tên sản phẩm, FC/kho, Ngày, Ngày thứ, Số lượng dự báo, Phương pháp, Mã kỹ thuật phương pháp.
- Giá trị = `cand_d1` = `np.round(yhat, 4)` (`backtest_runner.py:275`), **không** làm tròn về số nguyên.

**Các luồng khác đọc `forecast_values`:**

| Luồng | Vị trí |
|---|---|
| Lịch sử D+1 | `forecast_history.py:92-141` |
| Snapshot cuối ngày | `forecast_backup.py:53-120` |
| Chốt actual | `actual_close.py`, `actual_final.py` |
| Bất biến "mỗi run có đủ n_series × max_horizon giá trị" | `data_checks.py:258-262` |

---

## 9. Test hiện có

**Phạm vi:**
- Backend: 63 file `test_*.py`, 685 hàm `def test_` (đếm tĩnh, chưa tính parametrize).
- Frontend: 27 file `*.test.tsx`.
- **Không chạy test trong phiên này.**

**Cách ly:** `conftest.py:9,14,20` đặt `DF_DISABLE_SCHEDULER=1` và `DF_DATA_DIR` tạm. Các file `*_real_bq*.py` cần `DF_REAL_BQ=1`.

**Lệnh chạy:** xem mục 1.2.

| Mục | Test liên quan (file:dòng, tên) |
|---|---|
| 2. Luồng dữ liệu | `test_ml.py:75` `test_calendar_gap_is_unknown_not_zero`; `test_v117.py:59` (cửa sổ 01/01 → hôm qua), `:115`; `test_v129_weekday_open_hours.py:253` (SQL D-1 đọc giờ), `:276` (D-1 lưu giá trị + trạng thái), `:428` `test_panel_takes_open_hours_from_the_demand_rows_only`; `test_v129f_zero_open_hours.py:20,40`; `test_v129c_window_spike_customer.py:577` (`load_demand`); `test_v1213_history_sync.py` (KEEP_OBSERVED_LINES) |
| 3. Biến đầu vào | `test_ml.py:42` `test_features_never_use_data_at_or_after_t`; `test_v120_features.py:27,61,85`; `test_v129_weekday_open_hours.py:348,380,436`; `test_v129c_window_spike_customer.py:347,426,457`; `test_v1212_weekday_parity.py:80,93,145`; `test_v128_fixes.py:231-265` (công tắc thứ trong tuần, danh sách feature cũ); `test_v120_direct.py:25` (thứ tự cột DIRECT), `:37`; `test_v113.py` (giá trị feature qua API giải thích) |
| 4. FALLBACK | `test_ml.py:83` `test_fallback_classification` (STABLE/NEW/INTER/DEAD); `test_v111.py` (ví dụ registry phương pháp tính bằng code) |
| 5. Nhãn và cửa sổ | `test_v120_direct.py:37` (số dòng = 3 chuỗi × Σ min(14, …) theo 4 mốc × 7 ngày); `test_v1212_weekday_parity.py:80` |
| 6. Huấn luyện | `test_v120_direct.py:56` (DIRECT không đệ quy, nạp lại cho kết quả trùng); `test_v1213_job_resources.py`; `test_v129c_window_spike_customer.py:313,339` (trọng số chỉ cho thí nghiệm) |
| 7. Backtest, gate | `test_ml.py:58` `test_backtest_forecast_unchanged_when_future_changes`, `:106` quality gate, `:121-158`; `test_v120_direct.py:78` (fold không thấy cửa sổ được chấm), `:111-200` (ngoại lệ gate); `test_v117.py:179,199,218,227,241,278` (span, so sánh champion/challenger, không tự thay model); `test_v122_bigquery_policy.py` |
| 8. Xuất kết quả | `test_v128_fixes.py:155,161,165` (luật số lượng Python = SQL; giá trị, tổng, xuất, giải thích cùng số nguyên); `test_v112.py:57,80` (nhãn phương pháp và định dạng ngày khi xuất); `test_v129_weekday_open_hours.py:608` (cột thứ trong tuần) |

`backtest_runner.py` (ngoài Git) **không có test** trong repo. Chỉ có smoke và kiểm tra cấu trúc khi chạy (mục 7.2).

---

## 10. Trạng thái Git

**Branch hiện tại:** `main`, HEAD `af835b8`.

**Thay đổi chưa commit** (`git status --short`; `git diff --stat`: 7 file, +1318/−398). **Không** chạm vào mục 2–8; tất cả thuộc tính năng link truy cập từ xa:

| File | Trạng thái |
|---|---|
| `CHANGELOG.md` | sửa |
| `REMOTE_ACCESS_GUIDE.md` | sửa |
| `Start-DemandForecast-Remote.bat` | sửa |
| `Stop-DemandForecast-Remote.bat` | sửa |
| `docs/CHECKPOINT.md` | sửa |
| `scripts/remote/readonly_proxy.py` | sửa |
| `scripts/remote/remote-access.ps1` | sửa |
| `Setup-DemandForecast-Link.bat` | mới, chưa theo dõi |
| `backend/tests/test_remote_link.py` | mới, chưa theo dõi |
| `scripts/remote/link_supervisor.py` | mới, chưa theo dõi |

**10 commit gần nhất chạm mục 2–8.** Lệnh dùng: `git log -10 -- backend/app/ml backend/app/data backend/app/bq/connector.py backend/app/settings_service.py backend/app/api/forecast_routes.py backend/app/qty.py backend/app/jobs/scheduler.py`.

| Commit | Ngày | Nội dung | File ML/dữ liệu chạm tới |
|---|---|---|---|
| `af835b8` | 26/10 | Release 1.2.14: màn hình giải thích dự báo | `ml/forecast_explainer.py` |
| `1b00c42` | 22/10 | Release 1.2.13: history sync (gross demand), Customer ID | `connector.py`, `history_sync.py`, `features.py`, `model.py`, `pipeline.py`, `settings_service.py`, `scheduler.py`, … |
| `a601f4c` | 21/10 | 1.2.12 fix: khóa giờ mở bán được duyệt nhưng không có dòng | `open_hours_override.py`, `feature_registry.py`, `pipeline.py` |
| `fe4ca9b` | 21/10 | 1.2.12: luật MAX cho 6 khóa; tên thứ | `demand.py`, `open_hours*.py`, `feature_registry.py`, `pipeline.py` |
| `9ee5a4a` | 21/10 | 1.2.11: luật trùng theo trạng thái đơn | `connector.py`, `open_hours.py` |
| `dd0dfa1` | 21/10 | 1.2.10: khôi phục D-1, đơn chờ | `connector.py`, `demand.py`, `feature_registry.py`, `pipeline.py` |
| `15d4f4b` | 20/10 | 1.2.9: thứ 1–7, giờ mở bán bắt buộc, khách hàng | `features.py`, `model.py`, `pipeline.py`, `customers.py`, `open_hours.py`, `quality.py`, `forecast_routes.py`, … |
| `0da73b6` | 19/10 | 1.2.8: dự báo số nguyên, công tắc thứ | `qty.py`, `features.py`, `pipeline.py`, `forecast_routes.py`, `demand.py` |
| `89d2f6a` | 18/10 | 1.2.6: cấu hình 2 luồng cuối ngày | `settings_service.py` |
| `6a65fa2` | 18/10 | 1.2.6: giữ snapshot 90 ngày | `scheduler.py`, `settings_service.py` |

Riêng `features.py` / `model.py` có các commit: `1b00c42`, `15d4f4b`, `0da73b6`, `7053999` (1.2.2), `775644e` (1.2.0: DIRECT), `d87c315` (import ban đầu 1.1.8).

---

## 11. ĐỐI CHIẾU VỚI ĐẶC TẢ

**Không có `docs/spec_lightgbm_v3.md`.** Với mỗi mục 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 3.1:
- Chỗ code cần sửa: **CHƯA RÕ** cho từng số mục.
- Điểm khác với đặc tả: **CHƯA RÕ**, vì không có văn bản để so.

Phần dưới đối chiếu theo 4 chủ đề trong bối cảnh yêu cầu. Khi có đặc tả, gán từng mục vào A–D và kiểm lại.

**Nguyên tắc chung để giữ hành vi khi cờ tắt** (áp cho cả 4 chủ đề):

1. **Cờ mới trong `ModelSettings` mặc định là hành vi cũ** (`None`/`False`) và được đọc bằng `getattr(cfg, "x", None)`, giống `discount_on` / `weekday_on` (`features.py:133-146`).
   - Lý do: config của các run cũ được validate lại ở `extend_forecast` (`pipeline.py:658`), `promote_candidate` (`:761`), `release_with_gate_exception` (`:884`) và `compare_with_incumbent` (`:216-217`). Thiếu khóa thì phải ra đúng hành vi cũ.
2. **Lưới an toàn có sẵn:** `extend_forecast` buộc tái tạo **từng giá trị** của run gốc, nếu không khớp thì báo `REPRODUCTION_MISMATCH` (`pipeline.py:675-687`).
3. **Test đã ghim hành vi cũ:**
   - `test_v120_direct.py:25-34` (config không có trường thì vẫn là RECURSIVE);
   - `test_v128_fixes.py:231` (cờ chưa đặt thì danh sách feature y như cũ);
   - `test_v129_weekday_open_hours.py:436` (model trước 1.2.9 giữ danh sách feature).
4. **Không giữ được:** `config_fingerprint` của run mới sẽ đổi khi thêm trường (mục 7.2). `feature_set_version` chỉ phụ thuộc tên feature (`feature_registry.py:154-156`), nên không đổi nếu danh sách tên không đổi.

### A. Xử lý ngày đóng bán

**Chỗ code tương ứng:**

| Bước | Vị trí |
|---|---|
| Dữ liệu | `bq/connector.py:_daily_sql` (`:1202-1285`); `sync.run_d1_sync` (`sync.py:385`); `data/history_sync.py:_insert` (`:725-729`); migration mới `backend/app/migrations/0011_*.sql` (AGENTS §4) |
| Đọc | `data/demand.py:load_demand` (`:156-178`) |
| Panel | `ml/features.py:build_panel` (`:96-124`): chỗ gán 0 cho ngày không có dòng |
| Feature | `features_at` (`:240-263` cho lag/rolling/zero_share/days_since_last_sale/roll_max; `:279-289` cho giờ mở bán) |
| Nhãn | `direct_training_matrix` (`:417`, `:437`, mặt nạ `~np.isnan(Y)`) |
| FALLBACK | `model.py:classification_details` (`:106-129`) |
| Baseline | `model.py:_baseline_window` (`:222-227`) |
| Chấm backtest | `model.py:backtest` (`:340-343`); runner `backtest_runner.py:283` (`amap.get(key, 0.0)`: ngày không dòng = 0) |

**Điểm khác giữa code thực tế và mô tả "xử lý ngày đóng bán":**
- Code **không có khái niệm ngày đóng bán**.
- Ngày đóng **không có đơn** là `Y = 0`, giống hệt ngày mở mà không ai đặt.
- Ngày đóng **có đơn** (giờ = 0): lưu qty thật và giờ 0, trạng thái OK (`test_v129f_zero_open_hours.py`).
- Giờ mở bán **chỉ có ở ngày có đơn** (mục 2.3). Vì vậy app hiện **không thể biết** một ngày không đơn là đóng hay mở.
- `sku_system_status` không được dùng (mục 2.4).
- Bảng `demand_daily` có `qty NOT NULL` và chỉ chứa ngày có đơn. Lưu "ngày đóng không có đơn" cần nơi lưu mới.
- Nguồn có thể có trong BigQuery nhưng **chưa tích hợp**: `fact_sku_status_day_by_date`, `staging_sku_status_history` (`docs/BIGQUERY.md:480-496`).

**Phạm vi ảnh hưởng:**

| Phần | Ảnh hưởng | Bằng chứng |
|---|---|---|
| `build_panel` | Dùng chung cho mọi luồng: huấn luyện, backtest, `panel_for_run` (dựng lại panel cho extend, promote, ngoại lệ gate), giải thích (`explain.py:184`, `forecast_explainer.py:54,235-247`, `training_explain.py:134`), runner backtest | `pipeline.py:466`; `demand.py:97` (gọi từ `pipeline.py:665,762,885`); `backtest_runner.py:178-181` |
| Run cũ | Nếu panel đổi mà không theo cấu hình của **từng run**, run cũ dựng lại khác đi: extend báo `REPRODUCTION_MISMATCH`; giải thích lệch | — |
| Chữ ký hàm | `build_panel` hiện không nhận `cfg` | — |
| Quality gate, champion/challenger | Đổi tập điểm chấm `valid` làm đổi WAPE, bias, `n_points`. `compare_with_incumbent` chấm hai bên trên **cùng panel** của candidate | `pipeline.py:194-234` |
| FALLBACK | Số chuỗi LightGBM / INTERMITTENT / INACTIVE đổi (báo cáo 26/10: 50,8 % ngày 0 của chuỗi INTERMITTENT là ngày không mở bán) | — |
| Báo cáo chất lượng dữ liệu | Có công thức đếm riêng | `data/quality.py:88-101` |
| UI, văn bản | Văn bản luật | `frontend/src/algorithms.ts:161-178`; `ml/methods.py`; `ml/feature_catalog.py` (`_MISSING_DEMAND`) |
| Xuất file | Nếu ngày đóng không được dự báo hoặc nhận mã mới: nhãn phương pháp (`methods.label`) | — |
| Bất biến dữ liệu | `forecast_runs_complete` (n_series × max_horizon) | `data_checks.py:258-262` |
| DEMO / Excel | Không có giờ mở bán | `open_hours.py:52-54` |

**Cách giữ hành vi khi cờ tắt:**
- Áp mặt nạ ngày đóng **sau** khi `build_panel` dựng Y như cũ, chỉ khi cấu hình đã lưu của run bật cờ.
- `panel_for_run` (`demand.py:82-97`) phải đọc cờ đó từ `feature_config_json` của run.
- Bảng hoặc cột dữ liệu mới chỉ thêm (additive), không đổi `demand_daily.qty`. Như vậy fingerprint dữ liệu (`demand.py:181-193`) và danh tính dữ liệu (`identity.py:39-42`) của run cũ giữ nguyên.

### B. Mô hình riêng cho ngày D

**Chỗ code tương ứng:**

| Phần | Vị trí |
|---|---|
| Huấn luyện | `model.py:train` (`:47-80`) |
| Dự báo | `_forecast_direct` (`:196-219`): chọn model theo h |
| Chọn ứng viên | `pipeline.py:candidate_forecast` (`:173-177`) |
| Lưu model | `_save_model` (`:615-628`) |
| Cập nhật run | `train_and_publish` (`:478-481`, `:532-550`, `:571-576`) |
| So sánh, extend, promote, ngoại lệ | `compare_with_incumbent` (`:194-234`), `extend_forecast` (`:631-698`), `promote_candidate` (`:727-809`), `release_with_gate_exception` (`:832-932`) |
| Giải thích | `forecast_explainer.py:570-599`, `treeshap_trace.py`, `explain.py` |
| Runner | `backtest_runner.py:train_arm` (`:193-211`) |

**Điểm khác giữa code thực tế và mô tả "mô hình riêng cho ngày D":**
- Hiện có **một** booster DIRECT chung cho h = 1..30, với `horizon` là feature (mục 3).
- h = 1 có 12 trong 310 khe nhãn mỗi chuỗi (`direct-label-calendar.txt`: `origins per horizon {1: 12, …}`).
- `training_runs` chỉ có một `model_path` / `model_sha256` (`pipeline.py:543-550`).
- **"Ngày D" là gì thì CHƯA RÕ:**
  - Nếu là ngày dự báo đầu tiên (h = 1): cần thêm một model.
  - Nếu là hôm nay dùng dữ liệu trong ngày (D-0): hiện bị cấm làm đầu vào (`demand.py:20-22`). Dữ liệu D-0 chỉ để hiển thị (`data/intraday.py:32`, `sync.py:665`).

**Phạm vi ảnh hưởng:**
- Kiểm tra SHA-256 file model khi extend, promote và ngoại lệ (`pipeline.py:656,758-760,882`).
- Metadata `.json` của model.
- Màn giải thích (`frontend/src/pages/ForecastExplainer.tsx`, `TrainingExplain.tsx`; `api/explainer_routes.py`).
- Nếu tách mã phương pháp: registry phương pháp (`methods.py`), xuất Excel (cột "Mã kỹ thuật phương pháp").
- Thời gian huấn luyện (thêm một lần train mỗi fold backtest).
- Có thể cần migration nếu lưu thêm file model.

**Cách giữ hành vi khi cờ tắt:**
- Cờ tắt hoặc không có: đường đi một model như cũ, không đổi cột DB.
- Model thứ hai (nếu có) lưu dưới dạng file phụ, ghi trong `feature_config_json`.
- Mọi hàm đọc model cũ chỉ mở `model_path`.

### C. Cửa sổ nhãn mở rộng

**Chỗ code tương ứng:**
- `ml/features.py:direct_training_matrix` (`:410-444`);
- `settings_service.py:145-146` (`direct_origins` cho phép 1..52; `direct_origin_step_days` 1..30);
- UI đã có ô sửa 2 trường này (`frontend/src/pages/Config.tsx:161-164`);
- runner kế thừa qua `model.train`.

**Điểm khác giữa code thực tế và mô tả "cửa sổ nhãn mở rộng":**
- Hiện là **trượt 84 ngày** (12 × 7): mốc đếm lùi từ T.
- Lịch sử dùng tính feature thì đã **mở rộng** từ 01/01/2026.
- Có thể tăng số mốc chỉ bằng cấu hình (tối đa 52 × 7 = 364 ngày), không cần sửa code.
  - Vòng lặp tự dừng khi `t0 < 7` (`:414-415`).
  - Cần thêm điều kiện `t0 > start_idx` (`:417`).
- "Mở rộng" theo nghĩa **mọi mốc từ đầu cửa sổ** (số mốc thay đổi theo T) **chưa có**. Cần một chế độ mới.

**Phạm vi ảnh hưởng:**

| Phần | Ảnh hưởng |
|---|---|
| RAM, thời gian | DIRECT **không có trần số dòng**. Production 12 mốc = 5.218.927 dòng × 36 cột float32. Panel 298 ngày cho tối đa khoảng 41 mốc (ước tính: (298 − 7) ÷ 7, chưa đo), tức khoảng 3,4 lần số dòng |
| Backtest trong app | Mỗi fold huấn luyện lại với cùng cửa sổ (`model.py:337-338`) |
| `compare_with_incumbent` | Huấn luyện lại model đang dùng với `direct_origins` **của chính nó** (`pipeline.py:216-221`) |
| Tài nguyên job | `jobs/resources.py` |
| Fingerprint cấu hình | Đổi khi đổi giá trị |
| Tài liệu | `docs/MO-HINH-VA-CHI-SO.md:471-473` |

**Cách giữ hành vi khi cờ tắt:** mặc định 12/7 không đổi. Chế độ mới là trường riêng, mặc định `None` = trượt như cũ.

### D. Huấn luyện lại mỗi ngày

**Chỗ code tương ứng:**

| Phần | Vị trí |
|---|---|
| Production: lịch | `jobs/scheduler.py:130-147` |
| Production: bỏ qua khi dữ liệu không đổi | `pipeline.py:363-364` |
| Production: giữ ứng viên chờ duyệt | `pipeline.py:538-563` |
| Production: promote | `pipeline.py:727-809` |
| Backtest lịch sử: chia lô 7 ngày | `backtest_runner.py:make_batches` (`:310-317`) |
| Backtest lịch sử: dùng lại model trong lô | `run_batch` (`:251-293`) |
| Backtest trong app: bước fold | `model.py:backtest` (`backtest_step_days` 30, `backtest_folds` ≤ 12, `settings_service.py:131-133`) |

**Điểm khác giữa code thực tế và mô tả "huấn luyện lại mỗi ngày":**
- **Production đã huấn luyện mỗi ngày.** Job `TRAIN_PUBLISH` chạy một lần mỗi ngày (khóa `TRAIN_PUBLISH:<ngày>`), với BIGQUERY thì chờ D-1 thành công.
- Nhưng run **bị bỏ qua** nếu fingerprint dữ liệu không đổi.
- Khi đã có model đang dùng, model mới **chỉ là ứng viên**, không được publish. Forecast chỉ đổi khi có người promote. AGENTS §4 cấm tự thay model khi chưa có luật promote được nghiệp vụ duyệt.
- **Backtest lịch sử huấn luyện mỗi 7 ngày, không phải mỗi ngày.**
- Backtest trong app: fold cách 30 ngày. Với `backtest_folds ≤ 12`, đặt bước 1 ngày chỉ phủ 12 ngày.

**Phạm vi ảnh hưởng:**
- Production publish hằng ngày tự động là thay đổi chính sách: đụng `pipeline.py:538-563` và quy định AGENTS §4.
- Lịch sử D+1 (`forecast_history`) và snapshot cuối ngày (`forecast_backup`) ghi theo phiên publish.
- Trang Lịch chạy (`frontend/src/pages/Schedules.tsx`).
- Backtest lịch sử huấn luyện mỗi ngày: 144 lần × 2 nhánh. **Ước tính** từ log khoảng 110 giây mỗi model, tức khoảng 9 giờ (chưa đo).

**Cách giữ hành vi khi cờ tắt:**
- Production: không đổi scheduler hay chính sách promote khi cờ tắt.
- Runner: tham số bước lô mặc định 7.

---

## 12. Câu hỏi và điểm chưa rõ

1. **Đặc tả:** `docs/spec_lightgbm_v3.md` không có trong repo, lịch sử Git hay các thư mục lân cận. Bạn gửi file (hoặc đường dẫn) để đối chiếu 1.1–3.1 được không?
2. **Phạm vi:** khi chưa có đặc tả, 4 chủ đề A–D ở mục 11 có đúng và đủ phạm vi của 7 mục 1.1–3.1 không? Mục nào thuộc chủ đề nào?
3. **Định nghĩa "ngày đóng bán":**
   - `total_open_hours = 0`, hay dưới một ngưỡng giờ?
   - Dựa trên trạng thái `OUT_OF_STOCK` / `SUSPENDED`?
   - `LIMIT` tính là mở hay đóng?
4. **Nguồn giờ mở bán cho ngày KHÔNG có đơn:** app hiện chỉ có giờ trên ngày có đơn.
   - Dùng bảng BigQuery nào (`fact_sku_status_day_by_date`, `staging_sku_status_history`, hay bảng mới)?
   - Có được thêm truy vấn đọc mới (dry-run, có trần bytes) không?
5. **Lưu trữ:** có duyệt một migration additive mới (bảng riêng cho lịch mở/đóng theo SKU × FC × ngày) không? Hay giữ hoàn toàn trong bộ nhớ lúc huấn luyện?
6. **Nhãn và feature lịch sử:** ngày đóng bán xử lý thế nào? Bỏ khỏi nhãn huấn luyện? Coi là chưa biết (NaN) thay vì 0 trong lag và rolling?
7. **FALLBACK và baseline:**
   - Có loại ngày đóng khỏi mẫu số `zero_share` (56 ngày) và khỏi luật INACTIVE (60 ngày) không?
   - Có loại khỏi baseline 28 ngày không?
8. **Chấm điểm:** backtest và quality gate có loại điểm ngày đóng không? Việc này đổi `n_points`, WAPE và so sánh với model đang dùng.
9. **Dự báo cho ngày đích đang đóng:** dự báo 0, bỏ trống, hay vẫn dự báo? Lịch đóng tương lai có biết trước không?
10. **931 khóa có đơn nhưng giờ = 0** (hiện lưu là 0, trạng thái OK): xếp là ngày đóng hay ngày mở?
11. Thay đổi về ngày đóng bán chỉ áp cho nguồn BIGQUERY (DEMO và Excel không có giờ mở bán), đúng không?
12. **"Mô hình riêng cho ngày D":** D là ngày dự báo đầu tiên (h = 1, ngày sau dữ liệu cuối) hay hôm nay (D-0)? Model này thay phần h = 1 của model DIRECT hay chạy song song để so sánh?
13. Nếu D là hôm nay: có được dùng dữ liệu D-0 trong ngày làm đầu vào model không? Quy tắc cửa sổ hiện tại cấm (`data/demand.py:20-22`).
14. **Model ngày D:** cùng 36 feature, objective Tweedie 1,2 và siêu tham số? Có cần mã phương pháp mới hiển thị trong UI và file xuất không?
15. **Lưu 2 file model mỗi run:** chấp nhận thay đổi schema `training_runs` hay dùng file phụ? Champion/challenger, promote và ngoại lệ gate xét theo cặp model hay từng model?
16. **"Cửa sổ nhãn mở rộng":**
    - Mở từ đâu (01/01/2026, đầu chuỗi, hay N mốc tối đa)?
    - Giữ bước mốc 7 ngày không?
    - Áp cho production, backtest trong app, runner lịch sử, hay cả ba?
17. **Giới hạn tài nguyên:** run production hiện khoảng 34 phút, 5,2 triệu dòng. Mở rộng có thể gấp khoảng 3,4 lần số dòng. Mức RAM và thời gian chấp nhận được là bao nhiêu? Có chấp nhận lấy mẫu hoặc giảm trọng số mốc cũ không?
18. **"Huấn luyện lại mỗi ngày":** cho backtest lịch sử (lô 1 ngày thay 7), cho production, hay cả hai?
    - Production đã huấn luyện mỗi ngày nhưng chỉ tạo ứng viên. Có luật promote tự động được nghiệp vụ duyệt không?
    - Nếu không, giữ promote thủ công.
19. **`backtest_runner.py` nằm ngoài Git** (`reports/` bị ignore): sửa tại chỗ hay đưa vào repo (ví dụ `scripts/` hoặc `backend/app/ml/`) kèm test?
20. **Cờ:** tên cờ, mặc định OFF. Chấp nhận rằng thêm trường làm đổi `config_fingerprint` của run mới không? Khi đó `8468ebe66d1706f7` không còn tái lập được cho cấu hình "cờ tắt". Hay cần giữ fingerprint khi cờ tắt?
21. **Dữ liệu so sánh:** backtest so sánh trước/sau chạy trên bản sao DB nào (bản 23/10, SHA `8ABD356D…`, hay bản sao mới) và khoảng ngày nào (giữ 01/06–22/10)?
22. **Tiêu chí chấp nhận:** đo bằng chỉ số nào (WAPE, bias, theo horizon 7/15, theo nhóm), ngưỡng bao nhiêu, ai duyệt? Hiện ngưỡng gate chưa được nghiệp vụ duyệt và tôi không được tự đặt.
23. **Làm tròn và xuất file:** có trong phạm vi đặc tả không? App làm tròn từng ngày rồi cộng; Excel backtest giữ 4 số lẻ.
24. Có cập nhật `docs/MO-HINH-VA-CHI-SO.md` trong cùng đợt không? Tài liệu này còn đoạn mô tả "dự báo đệ quy" ở dòng 439.
25. **Thứ tự ưu tiên:** triển khai chủ đề nào trước? Mỗi chủ đề một cờ riêng, hay một cờ "v3" chung?
26. Có cho phép đọc `GET /api/settings` (chỉ đọc) để xác nhận cấu hình đang lưu của bản cài không (`train_time`, `horizons.enabled`, section `model`)? Phiên này không đọc DB hay API, nên các giá trị đó đang ghi CHƯA RÕ.
    *(Đã trả lời một phần ở mục 13: `schedule`, `horizons`, `general` đọc từ DB ở chế độ chỉ đọc.)*

---

## 13. Luồng chạy hằng ngày (khảo sát bổ sung, chỉ đọc, 26/10/2026 ~22:20 giờ VN)

**Cách đọc:**
- Code đọc bằng công cụ đọc file.
- DB live `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` mở bằng URI `file:///…/app.db?mode=ro` cùng `PRAGMA query_only=1`. Chỉ chạy `SELECT` / `PRAGMA table_info` trên các bảng nhỏ: `app_settings`, `settings_history`, `training_runs`, `forecast_runs`, `job_runs`, `audit_log`, `forecast_history_*`, `forecast_eod_snapshots`.
- Log: `logs\runtime\app.log` (JSON, từ 14/10).
- Không train, forecast hay promote; không đổi lịch; không đọc bảng `bigquery`/OAuth.
- **Ghi nhận phụ:** khi mở DB ở chế độ WAL, SQLite tạo tạm hai file phụ rỗng `app.db-wal` (0 byte) và `app.db-shm`.
  - Nội dung và mtime của `app.db` không đổi do lần đọc: 22:20 trước lần đọc đầu, 22:22 sau đó, do chính app ghi heartbeat.
  - App tự xóa hai file ở lần đóng kết nối kế tiếp: lúc 22:22 thư mục không còn chúng.
- Đã mở `data\runtime\runtime.json` (có token tắt máy cục bộ của app). Không chép token vào báo cáo.

**Quy ước:**
- Giờ ghi theo **giờ Việt Nam (UTC+7)**; DB lưu UTC.
- "Lập" = `forecast_runs.created_at`.
- "Dữ liệu đến" = `forecast_runs.data_as_of`.
- `h` = vị trí của ngày D trong kỳ của run (`D − forecast_origin + 1`).

### 13.1 Lịch chạy (cấu hình đang lưu)

**Nơi cấu hình:**
- Bảng `app_settings`, section `schedule`, cập nhật lần cuối 2026-10-23T18:00:30Z. Lớp `ScheduleSettings` ở `settings_service.py:207-301`; giá trị mặc định trong code khác giá trị đã lưu.
- Sửa qua `/api/schedules` (`api/schedule_routes.py`, `jobs/flows.py`).
- Scheduler chạy **trong tiến trình app** (`main.py:48-49`), mỗi 30 giây gọi `Scheduler.tick` → `plan` (`jobs/scheduler.py:246-282`, `:50-166`) → `runner.execute`.
- Handler theo loại job: `jobs/runner.py:46-76`.
- Ngoài app chỉ có Windows task `DemandForecast` để tự khởi động app khi đăng nhập (`scripts/register-autostart.ps1:3-10`). **Không có** task Windows nào chạy train hay forecast. (Có đang đăng ký trên máy hay không: không kiểm tra.)

Giá trị đọc được:

```text
schedule (DB, mode=ro): d1_enabled=true  d0_enabled=true  train_enabled=true  eod_enabled=true  close_enabled=true
  d1_signal_poll_start="08:00"  d1_poll_interval_minutes=30  d1_fallback_time="08:10"
  train_time="08:20"  slot_grace_minutes=20  train_catchup_policy="SKIP"
  d0_times=["08:00","10:00","12:00","14:00","16:00","18:00"]  d0_catchup_policy="LATEST_ONCE"
  eod_time="23:55"  close_time="23:59"  max_attempts=4  timeout_seconds=3600
horizons.enabled=[7,15]      general.active_source="BIGQUERY" (từ 2026-10-16T09:43:15Z)
```

**Các tác vụ:**

| Tác vụ | Có lịch? | Giờ (đang lưu) | Hàm được gọi | Bằng chứng code |
|---|---|---|---|---|
| Lấy dữ liệu D-1 (`D1_SYNC`) | Có, `d1_enabled` | Từ 08:00 dò tín hiệu hoàn tất mỗi 30 phút; sau 08:10 kiểm tra đủ dữ liệu; tối đa 4 lần thử. Khóa `D1_SYNC:<ngày>` | `sync.run_d1_sync` | `scheduler.py:118-128`; `runner.py:54-57` |
| Snapshot D-0 (`D0_SYNC`) | Có, `d0_enabled` | 08:00, 10:00 … 18:00 | `sync.run_d0_snapshot`: chỉ lưu "thực tế hôm nay", **không** dự báo | `scheduler.py:93-116`; `runner.py:50-52` |
| Huấn luyện (`TRAIN_PUBLISH`) | Có, `train_enabled` | 08:20, **một lần mỗi ngày** (khóa `TRAIN_PUBLISH:<ngày>`). Với BIGQUERY chỉ chạy **sau khi D-1 hôm nay thành công**. Nếu lúc D-1 xong đã quá 08:20 + 20 phút thì `train_catchup_policy="SKIP"` làm slot bị ghi `SKIPPED / MISSED_SLOT_NO_BACKFILL` | `pipeline.train_and_publish` | `scheduler.py:130-147`; `flows.py:188-207`; `runner.py:59-61` |
| Forecast | **Không có tác vụ riêng, không có lịch.** Con số dự báo chỉ được tạo trong 4 trường hợp: (a) `train_and_publish` khi scope **chưa có** model đang dùng; (b) promote; (c) phát hành theo ngoại lệ gate; (d) `FORECAST_EXTEND` (tay, cùng model, cùng dữ liệu, chỉ thêm horizon) | — | `pipeline.py:564-588`, `:727-809`, `:832-932`, `:631-698`; `runner.py:33` ("FORECAST_EXTEND is manual only") |
| Publish | Không có lịch riêng. Là bước cuối của (a), (b), (c), (d) qua `_publish_run` | — | `pipeline.py:250-279` |
| Promote | **Không có lịch.** Chỉ qua API `POST /api/training-runs/{id}/promote` với `confirm=true` (nút "Dùng model này" trên UI) | — | `api/forecast_routes.py:104-113`; `pipeline.py:727-809` |
| Sao lưu dự báo cuối ngày (`EOD_FORECAST_SNAPSHOT`) | Có, `eod_enabled` | 23:55 | `forecast_backup.run_job`: **chép** 7 ngày kế tiếp từ phiên chính thức mới nhất; không train, không forecast | `scheduler.py:149-157`; `forecast_backup.py:1-15, 53-118` |
| Chốt actual (`ACTUAL_CLOSE`) | Có, `close_enabled` | 23:59 | `actual_close.run_job` | `scheduler.py:149-157`; `runner.py:71-74` |

**Lịch sử thay đổi giờ** (`settings_history`, section `schedule`):

| Từ (giờ VN) | `train_time` | `d1_signal_poll_start` |
|---|---|---|
| 14/10 | 07:00 | 01:00 |
| 16/10 17:57 | 09:00 | 03:00 |
| 21/10 00:08 | 07:00 | 06:00 |
| 24/10 01:00 | **08:20** | **08:00** |

`train_catchup_policy` = `SKIP` từ 17/10 16:37.

### 13.2 Train tự động xong thì model mới có tự thành model đang dùng không?

**Không, khi scope đã có model đang dùng.** Không có điều kiện tự promote nào: không dựa vào quality gate, `PUBLISH_WITH_WARNING`, hay verdict `BETTER` của champion/challenger.

**Luồng trong `train_and_publish`:**
1. Đánh giá `usage`.
   - `NOT_USABLE` → `REJECTED / QUALITY_GATE_FAILED`, không publish (`pipeline.py:505-513`).
   - `USABLE` / `USABLE_WITH_WARNING` → đi tiếp.
2. Tìm model đang dùng `incumbent` (`:523-524`).
   - **Có:** so champion/challenger (`:527`), rồi luôn ghi run thành `REJECTED` + `PROMOTION_REVIEW_REQUIRED` = **ứng viên chờ duyệt**, trả `status: "CANDIDATE"`. Dừng trước bước `FORECASTING` (`:538-563`).
   - **Không có:** publish ngay (`INITIAL_MODEL`, `:528-529`, `:564-588`).

`PUBLISH_WITH_WARNING` (`settings_service.py:85-97`) chỉ có nghĩa: run dưới ngưỡng vẫn được publish khi **chưa có** model đang dùng, hoặc được phép promote bằng tay (`promotable`, `pipeline.py:701-724`).

```python
# backend/app/ml/pipeline.py:522-530, :538-543
        # incumbent protection: a model already in use is never replaced automatically (no approved promotion rule)
        with db.read() as c:
            inc = incumbent(scope["scope_key"], c)
        promotion = {"policy": "MANUAL_REVIEW", "decided_at": now_iso()}
        if inc:
            promotion.update(compare_with_incumbent(panel, bt, mcfg, inc["training_run"], qcfg, cancel, chosen))
        else:
            promotion.update(decision="INITIAL_MODEL", note="no model in use for this scope: nothing to protect")
        ...
        if inc:
            promotion["decision"] = "REVIEW_REQUIRED"
            gate["promotion"] = promotion
            common["quality_gate_json"] = json.dumps(gate)
            with db.tx() as c:   # kept as a reviewable candidate: model file + metrics + comparison, NOT published
                c.execute("UPDATE training_runs SET status='REJECTED', finished_at=?, reject_reason=?, model_version=?, "
```

```python
# backend/app/api/forecast_routes.py:108-113
@router.post("/training-runs/{run_id}/promote")
def promote_training_run(run_id: str, body: PromoteBody):
    """User decision to put a reviewed candidate in use (there is no approved automatic promotion rule)."""
    if not body.confirm:
        raise AppError("CONFIRMATION_MISMATCH", 422, detail="confirm=true required")
    return pipeline.promote_candidate(run_id)
```

**Bằng chứng runtime:**
- Mọi `TRAINING_CANDIDATE` trong `audit_log` 18–26/10 đều có `decision = REVIEW_REQUIRED`.
- Hai ứng viên **không bao giờ** được dùng: `TRN-20261023055745-933B70` (verdict `BETTER`) và `TRN-20261025152426-A4C635` (`EQUAL`). Cả hai vẫn ở `REJECTED / PROMOTION_REVIEW_REQUIRED`.
- Ứng viên có verdict `BETTER` cũng không tự lên.
- Lưu ý: một ứng viên chỉ promote được khi dữ liệu chưa đổi kể từ lúc train (`pipeline.py:752-753`, `DATA_CHANGED_SINCE_TRAINING`). Lần nạp D-1 kế tiếp vì vậy khiến ứng viên cũ không promote được nữa.

### 13.3 Forecast hằng ngày dùng model nào, dữ liệu đến ngày nào, có con số MỚI cho ngày D mỗi ngày không?

**Không có job forecast hằng ngày** (13.1). Bản dự báo hiện hành = `forecast_runs` mới nhất của scope:
- `pipeline.latest_published` (`:237-247`), sắp `created_at DESC, rowid DESC`;
- trang tổng quan đọc ở `ops_routes.py:79-80`;
- trang Kết quả mặc định chọn run mới nhất (`frontend/src/pages/Results.tsx:70`).

**Model dùng để tạo số:**
- Chỉ khi có lần publish mới (thường là promote). Số được tạo bằng **chính model vừa promote**, không bao giờ bằng "candidate mới nhất chưa duyệt".
- Promote dựng lại **panel của chính run đó**: `panel_for_run(tr)`, tức `train_start..train_end` (`pipeline.py:762`; `data/demand.py:82-97`), rồi dự báo từ mốc `train_end + 1`.

**Dữ liệu đầu vào đến ngày nào:**
- Đến `train_end` = ngày trước ngày train (`data_window`: hôm qua giờ VN, `data/demand.py:25-52`).
- Ngày đầu của kỳ (`h = 1`) là **chính ngày train/promote**. Số cho "ngày mai" là `h = 2`.
- Ví dụ `FCR-20261026044021-330262`: origin 26/10, data_as_of 25/10, lập 26/10 11:40.

**Con số cho ngày D có mới mỗi ngày không:**
- **Không.** Con số chỉ mới vào ngày có promote.
- Các ngày khác, ngày D nhận giá trị **có sẵn** trong run cũ, ở `h = D − origin + 1`: cùng model, cùng dữ liệu đến `data_as_of` cũ.
- Snapshot cuối ngày và lịch sử D+1 chỉ **chép** số của run cũ (`forecast_backup.py:4-15`; `forecast_history.py:28-30`).

```python
# backend/app/ml/pipeline.py:752-753, :761-765, :774
    if tr["data_fingerprint"] != cur_fp:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="the data changed after this candidate was trained")
    ...
    mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
    panel = panel_for_run(tr)
    if panel is None:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="training data no longer available")
    max_h = max(hcfg.enabled)
    ...
    fc, details = candidate_forecast(chosen, panel, booster, mcfg, max_h, cancel)
```

### 13.4 "Forecast tiếp tục được sử dụng cho đến lần promote tiếp theo" nghĩa là gì

**Câu trong báo cáo 30 câu hỏi:**
- "Run được dùng tới lần promote sau" (`reports/dieu-tra-30-cau-hoi-20261026/BAO_CAO_DIEU_TRA_30_CAU_HOI.md:172`);
- "Production: forecast chỉ đổi khi có người promote" (`:40`);
- bảng tổng hợp câu 5 (`:669`).

**Nghĩa chính xác, theo code:**

1. **"Forecast đang dùng"** là **một** `forecast_runs` (một model, một mốc, một `data_as_of`, `max_horizon` = 15 ngày). Đó là run mới nhất của scope (`pipeline.py:237-247`). Model đang dùng = training run đứng sau run đó (`incumbent`, `pipeline.py:185-191`).
2. Huấn luyện hằng ngày (tự động hay tay) khi đã có model đang dùng **không tạo `forecast_runs` mới** (13.2). Vì vậy run cũ vẫn là "mới nhất".
3. Một `forecast_runs` mới chỉ xuất hiện khi:
   - promote (`pipeline.py:794-796`);
   - phát hành theo ngoại lệ gate (`:918-920`);
   - mở rộng horizon (`:691-694`, cùng model, cùng dữ liệu);
   - huấn luyện đầu tiên của một scope chưa có model (`:577-578`).
4. Trong thời gian đó, ngày D (D lùi dần về cuối kỳ) đọc giá trị của run cũ ở `h` tăng dần. Số được tính một lần tại mốc cũ với dữ liệu đến `data_as_of` cũ, **không tính lại**. Model DIRECT tính mọi biến tại mốc (`model.py:196-219`).
5. Nếu không promote quá `max_horizon` = 15 ngày, run cũ hết giá trị cho các ngày sau.

Ví dụ thực tế: `FCR-20261020082402-A42C91` (lập 20/10 15:24, dữ liệu đến 19/10) là nguồn số cho các ngày 21/10 (`h = 2`) → 24/10 (`h = 5`), cho tới khi promote 24/10 23:38.

```python
# backend/app/ml/pipeline.py:185-191, :237-243
def incumbent(scope_key: str, conn) -> dict | None:
    """The model in use for a scope = the training run behind the latest published forecast run of that scope."""
    fr = latest_published(scope_key, conn)
    if not fr:
        return None
    tr = db.one(conn, "SELECT * FROM training_runs WHERE id=?", (fr["training_run_id"],))
    return {"forecast_run": fr, "training_run": tr} if tr else None
def latest_published(scope_key: str | None = None, conn=None) -> dict | None:
    sql = "SELECT * FROM forecast_runs"
    if scope_key:
        sql += " WHERE scope_key=?"
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
```

### 13.5 Bằng chứng runtime 14 ngày (13/10–26/10/2026)

**Nguồn:**
- `job_runs` (TRAIN_PUBLISH, D1_SYNC, FORECAST_EXTEND);
- `training_runs`, `forecast_runs`;
- `audit_log` (`MODEL_PROMOTED`, `TRAINING_CANDIDATE`, `FORECAST_PUBLISHED`);
- `logs\runtime\app.log` (`training window`, `candidate kept for review`, `candidate promoted`), khớp với DB.

**Danh sách run dự báo của scope BIGQUERY** (`forecast_runs`):

| Run | Lập (giờ VN) | Mốc | Dữ liệu đến |
|---|---|---|---|
| `FCR-20261017123417-FCC0EB` | 17/10 19:34 | 17/10 | 16/10 |
| `FCR-20261018043737-798B4D` | 18/10 11:37 | 18/10 | 17/10 |
| `FCR-20261019060524-9DE420` | 19/10 13:05 | 19/10 | 18/10 |
| `FCR-20261020082402-A42C91` | 20/10 15:24 | 20/10 | 19/10 |
| `FCR-20261024163842-4EEFD8` | 24/10 23:38 | 24/10 | 23/10 |
| `FCR-20261026044021-330262` | 26/10 11:40 | 26/10 | 25/10 |

Mỗi run có 15 ngày và được tạo **bởi promote** (`MODEL_PROMOTED` cùng giây với `FORECAST_PUBLISHED`). `job_id` của run = NULL, tức không do job lập lịch tạo. Trước 17/10 chỉ có run DEMO.

**Cách đọc cột "forecast cho ngày D":** ghi run **đang hiện hành lúc 00:00 của ngày D**, và nếu trong ngày D có promote thì ghi thêm run mới cùng giờ của nó.

**Cách đọc cột khoảng cách:** "ngày lập → D / dữ liệu đến → D", đơn vị ngày.

| Ngày | Các lần train (run_id, giờ VN, kết quả) | Promote | Model đang dùng (cuối ngày) | Forecast cho ngày D (run, lập lúc, dữ liệu đến) | Khoảng cách |
|---|---|---|---|---|---|
| 13/10 | Không có job (job đầu tiên 14/10 09:19) | — | — | Không có | — |
| 14/10 *(DEMO)* | 09:20 lịch `CATCH_UP`: FAILED `NO_ACTIVE_DATASET`. 15:06 tay: `TRN-20261014080606-47DF32` ACCEPTED (publish đầu tiên, DEMO). 17:37, 18:17 tay: SKIPPED `NO_NEW_DATA`; 2 lần `FORECAST_EXTEND` (17:36, 18:18) | — | DEMO `MV-20261014-150621-DF32` | DEMO `FCR-20261014080621-8D88F1`, 14/10 15:06, dữ liệu 13/10, h = 1 | 0 / 1 |
| 15/10 *(DEMO)* | 07:00 lịch: SKIPPED `NO_NEW_DATA` | — | DEMO DF32 | DEMO `FCR-20261014111845-8B81D1` (14/10 18:18, dữ liệu 13/10), h = 2 | 1 / 2 |
| 16/10 | 07:00 lịch: SKIPPED `NO_NEW_DATA`. 14:32 tay: DEMO `TRN-20261016073229-7F6555` ACCEPTED. Nguồn đổi sang BIGQUERY lúc 16:43. 16:54 tay: `TRN-20261016095451-697A11` REJECTED `QUALITY_GATE_FAILED`. 17:36 tay: `TRN-20261016103616-3FCDDB` REJECTED `QUALITY_GATE_FAILED` | — | BIGQUERY: **chưa có** | BIGQUERY: **không có** (chỉ có run DEMO) | — |
| 17/10 | 16:52 lịch: SKIPPED `MISSED_SLOT_NO_BACKFILL` (slot 09:00). 17:12 tay: `TRN-20261017101340-EEDA47` REJECTED `QUALITY_GATE_FAILED`. 19:16–19:22 tay ×3: SKIPPED `SOURCE_NOT_READY` | **19:34** `TRN-…EEDA47` (từ `QUALITY_GATE_FAILED`) | `MV-20261017-172653-DA47` | 00:00: không có. 19:34: `FCR-20261017123417-FCC0EB`, dữ liệu 16/10, h = 1 | 0 / 1 |
| 18/10 | D-1 lịch FAILED `SOURCE_INCOMPLETE`; D-1 tay OK 08:59. **09:00 lịch** (lần train lịch thành công duy nhất): `TRN-20261018020140-642DB8` → CANDIDATE `EQUAL` (09:01–09:26). 11:26 tay: SKIPPED `NO_NEW_DATA` | **11:37** `TRN-…642DB8` | `MV-20261018-092617-2DB8` | 00:00: `FCR-…FCC0EB` (17/10 19:34, dữ liệu 16/10), h = 2. 11:37: `FCR-20261018043737-798B4D`, dữ liệu 17/10, h = 1 | 1 / 2; sau promote 0 / 1 |
| 19/10 | D-1 lịch FAILED; D-1 tay FAILED rồi OK 10:35. 10:35 lịch: SKIPPED `MISSED_SLOT_NO_BACKFILL`. 11:20 tay: `TRN-20261019043033-A761C1` → CANDIDATE `EQUAL` (11:30–12:00) | **13:05** `TRN-…A761C1` | `MV-20261019-120018-61C1` | 00:00: `FCR-…798B4D` (18/10 11:37, dữ liệu 17/10), h = 2. 13:05: `FCR-20261019060524-9DE420`, dữ liệu 18/10, h = 1 | 1 / 2; sau promote 0 / 1 |
| 20/10 | D-1 lịch FAILED; D-1 tay OK 12:31. 12:31 lịch: SKIPPED `MISSED_SLOT`. 12:43 tay: `TRN-20261020054540-D7EEF6` → CANDIDATE `EQUAL` (12:45–13:15) | **15:24** `TRN-…D7EEF6` | `MV-20261020-131556-EEF6` | 00:00: `FCR-…9DE420` (19/10 13:05, dữ liệu 18/10), h = 2. 15:24: `FCR-20261020082402-A42C91`, dữ liệu 19/10, h = 1 | 1 / 2; sau promote 0 / 1 |
| 21/10 | D-1 lịch FAILED; backfill 12:29–12:46; D-1 tay OK 15:11, 18:20. 15:12 lịch: SKIPPED `MISSED_SLOT`. 16:35 và 21:23 tay: FAILED `OPEN_HOURS_INVALID` (không tạo training run) | — | EEF6 | `FCR-…A42C91` (20/10 15:24, dữ liệu 19/10), h = 2 | 1 / 2 |
| 22/10 | D-1 lịch FAILED; D-1 tay OK 07:16. **07:16 lịch: FAILED `OPEN_HOURS_INVALID`** | — | EEF6 | `FCR-…A42C91`, h = 3 | 2 / 3 |
| 23/10 | D-1 lịch FAILED; D-1 tay OK 07:35 (nạp lại từ 01/01). 07:35 lịch: SKIPPED `MISSED_SLOT` (slot 07:00). 12:56 tay: `TRN-20261023055745-933B70` → CANDIDATE **`BETTER`** (12:57–13:24) | — (không promote) | EEF6 | `FCR-…A42C91`, h = 4 | 3 / 4 |
| 24/10 | D-1 lịch FAILED; D-1 tay OK 11:38. 11:38 lịch: SKIPPED `MISSED_SLOT`. 16:04 tay: `TRN-20261024090507-1EEA7D` → CANDIDATE **`BETTER`** (16:05–16:36). 23:37 tay: SKIPPED `NO_NEW_DATA` | **23:38** `TRN-…1EEA7D` | `MV-20261024-163642-EA7D` | 00:00: `FCR-…A42C91`, h = 5. 23:38: `FCR-20261024163842-4EEFD8`, dữ liệu 23/10, h = 1 | 4 / 5; sau promote 0 / 1 (22 phút trước hết ngày) |
| 25/10 | D-1 lịch FAILED; D-1 tay OK 22:21. 22:19 lịch: SKIPPED `MISSED_SLOT`. 22:22 tay: `TRN-20261025152426-A4C635` → CANDIDATE `EQUAL` (22:23–22:57) | — (không promote) | EA7D | `FCR-…4EEFD8` (24/10 23:38, dữ liệu 23/10), h = 2 | 1 / 2 |
| 26/10 | D-1 lịch (08:00) FAILED 09:47; D-1 tay OK 10:01. 10:01 lịch: SKIPPED `MISSED_SLOT`. 10:18 tay: `TRN-20261026031942-53C73F` → CANDIDATE `EQUAL` (10:19–10:53) | **11:40** `TRN-…53C73F` | `MV-20261026-105345-C73F` | 00:00: `FCR-…4EEFD8`, h = 3. 11:40: `FCR-20261026044021-330262`, dữ liệu 25/10, h = 1 | 2 / 3; sau promote 0 / 1 |

**Đối chiếu với lịch sử D+1 và snapshot cuối ngày** (`forecast_history_days`, `forecast_eod_snapshots`): số "chính thức" cho ngày đích D lấy như sau.

| Ngày đích | Nguồn số chính thức |
|---|---|
| 18/10 | Phiên `FCR-…FCC0EB` |
| 19/10 | Phiên `FCR-…798B4D` |
| 20/10 | Phiên `FCR-…9DE420` |
| 21/10 | Phiên `FCR-…A42C91` |
| 22, 23, 24/10 | **Không có phiên** (run date 21–23/10 không có publish). Dùng snapshot cuối ngày 21, 22, 23/10, đều chép từ `FCR-…A42C91` |
| 25/10 | Phiên `FCR-…4EEFD8` |
| 26/10 | Snapshot 25/10, chép từ `FCR-…4EEFD8` |
| 27/10 | Phiên `FCR-…330262` |

**Tổng hợp 17–26/10** (từ khi có nguồn BIGQUERY):

| Hạng mục | Kết quả |
|---|---|
| Slot `TRAIN_PUBLISH` theo lịch | 1 SUCCEEDED (18/10, ra ứng viên), 1 FAILED (22/10), **8 SKIPPED `MISSED_SLOT_NO_BACKFILL`**. Lý do: D-1 lịch FAILED `SOURCE_INCOMPLETE` ở mọi ngày từ 18/10; D-1 tay xong sau slot + 20 phút; `train_catchup_policy = SKIP` |
| Training run BIGQUERY | 10 run: 9 chạy tay, 1 theo lịch |
| Promote | 6 lần (17, 18, 19, 20, 24, 26/10), đều bằng tay qua API. Actor không được ghi trong `audit_log`. Không có promote tự động |
| Ngày có số dự báo **mới** | 6 ngày. Ngày 21, 22, 23, 25/10 dùng số lập trước đó 1–4 ngày, dữ liệu cũ 2–5 ngày |

### 13.6 Kết luận

**Không.** Luồng hiện tại không phải "mỗi ngày dữ liệu D-1 → huấn luyện lại → dùng mô hình mới dự báo ngày D". Có 4 điểm khác chính xác:

1. **Huấn luyện lại không tự động diễn ra mỗi ngày trong thực tế.**
   - Có lịch `TRAIN_PUBLISH` một lần mỗi ngày, chờ D-1 (`scheduler.py:130-147`).
   - Nhưng 17–26/10 chỉ 1 lần train theo lịch thành công. 8 slot bị bỏ vì D-1 xong sau 08:20 + 20 phút và `train_catchup_policy = SKIP`. Các lần train khác là chạy tay.
2. **Model mới không bao giờ tự thành model đang dùng.** Khi đã có model đang dùng, kết quả train luôn là ứng viên `PROMOTION_REVIEW_REQUIRED` (`pipeline.py:538-563`). Chỉ promote bằng tay mới đổi model: 6 lần promote trên 10 training run BIGQUERY. Hai run 16/10 bị gate từ chối; ứng viên 23/10 (`BETTER`) và 25/10 không được promote.
3. **Không có bước dự báo hằng ngày.** Con số chỉ được tạo khi publish hay promote. Ngày không promote dùng lại số đã lập 1–4 ngày trước, ở `h = 2…5`, với dữ liệu cũ hơn D-1 (21–23/10 và 25/10).
4. **Thời điểm số cho ngày D:**
   - Mốc của run = chính ngày train/promote (`h = 1` = hôm đó).
   - Vào đầu ngày D, số đang hiện hành luôn là của run trước (`h ≥ 2`).
   - Số `h = 1` dùng dữ liệu D-1 và model mới chỉ có sau lúc promote trong ngày D (11:37, 13:05, 15:24, 23:38, 11:40), và chỉ ở 6/10 ngày.

## 14. Cấu trúc dữ liệu đầu vào (khảo sát chỉ đọc, 26/10/2026 ~23:40–23:55 giờ VN)

**Cách đọc:**
- Code đọc bằng công cụ đọc file. App đang chạy là 1.2.14 (PID 29408); code cài đặt trùng từng byte với repo.
- DB live `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` mở bằng URI `file:///…/app.db?mode=ro` + `PRAGMA query_only=1`. Chỉ chạy `SELECT` / `PRAGMA` trên:
  - `app_settings` (section `bigquery`, `sql_sources`); hai trường `oauth_client_id`, `service_account_file` không in ra;
  - `demand_daily` (đếm theo ngày, 14 ngày).
- Script ở scratchpad của phiên, không nằm trong repo.
- Không train, không đổi lịch, không gọi BigQuery (kể cả dry-run).
- File `app.db-wal` / `app.db-shm` có mặt vì app đang chạy và tự ghi (heartbeat), không do lần đọc này.

### 14.1 Bảng D-1 `demand_planing_lightgbm`

**Nguồn đang dùng** (DB, `app_settings.bigquery`, cập nhật lần cuối 2026-10-22T17:57:27Z; `sql_sources.history`, cập nhật 2026-10-17T12:38:52Z):

```text
project_id=lakehouse-prod-394907  dataset_id=gold_buymed_vn2  source_table=demand_planing_lightgbm  location=asia-southeast1
sql_sources.history: mode=TABLE (0 phiên bản SQL)  key_columns=[]  key_duplicate_policy=SUM_ALL
partition_column="created_date" (bảng thật KHÔNG phân vùng, docs/BIGQUERY.md:608: chỉ là điều kiện ngày nới ±1 ngày)
history_start_date=2026-01-01  exact_duplicate_policy=BLOCK  max_null_share=0.05  customer_id_column="customer_id"
production_enabled=true  maximum_bytes_billed=21474836480 (20 GiB)  created_at_is_utc=true (không dùng: created_at UNUSED)
```

**Grain của một dòng nguồn:**
- **Một dòng đơn hàng** (order line).
- Nhiều dòng có thể cùng `so_code × sku_code × fc_code × created_date`. Đó là các dòng khác nhau của cùng một đơn và được **cộng dồn** (quy tắc 16/10, `docs/BIGQUERY.md:621-627`).
- Bảng chỉ có ngày có đơn, mỗi dòng số lượng ≥ 1 (`docs/BIGQUERY.md:476-477`).
- App gom về **ngày × SKU × FC** (`GROUP BY 3, 4, 5` trong `_daily_sql`) rồi ghi vào `demand_daily`: một dòng mỗi khóa, khóa duy nhất `sqlite_autoindex_demand_daily_1`.

**Định nghĩa trường và vai trò:**

```python
# backend/app/settings_service.py:22-45
INTERNAL_FIELDS = ["order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price",
                   "discount_amount", "promotion_flag", "promotion_id", "voucher_flag", "voucher_amount",
                   "source_updated_at", "batch_id"]
REFERENCE_FIELDS = ["product_id", "item_code", "outbound_qty", "order_status", "sales_price", "price_after_discount",
                    "seller_code", "sku_status", "open_date", "open_hours", "open_days"]
ROLES = ("KEY", "TARGET", "REQUIRED_FEATURE", "OPTIONAL_FEATURE", "REFERENCE")
FIELD_ROLES = {
    "order_id": "KEY", "created_at": "KEY", "order_date": "KEY", "sku_id": "KEY", "fc_id": "KEY",
    "order_qty": "TARGET",
    "unit_price": "OPTIONAL_FEATURE", "discount_amount": "OPTIONAL_FEATURE", "promotion_flag": "OPTIONAL_FEATURE",
    "promotion_id": "REFERENCE", "voucher_flag": "REFERENCE", "voucher_amount": "REFERENCE",
    "source_updated_at": "REFERENCE", "batch_id": "REFERENCE",
    **{f: "REFERENCE" for f in REFERENCE_FIELDS},
    "open_hours": "REQUIRED_FEATURE",
}
MANDATORY_REFERENCE_FIELDS = ("open_hours",)
```

`FieldMapping.usage` = `REQUIRED | OPTIONAL | UNUSED` (`settings_service.py:304-306`). Kiểu chấp nhận theo trường: `connector.py:31-48`. Gợi ý mặc định (chỉ điền sẵn trên trang, không lưu): `connector.py:54-63`.

**Mapping đang lưu** (DB) và kiểu cột theo `schema_snapshot` (18 cột, lưu cùng lần lưu mapping):

| Cột nguồn | Kiểu (snapshot) | Tên nội bộ | Vai trò / usage | Dùng ở đâu |
|---|---|---|---|---|
| `created_date` | DATE | `order_date` | KEY / REQUIRED | Ngày = `DATE(created_date)` (`connector.py:553-560`); lọc `BETWEEN @start AND @end` (`:647-649`); điều kiện "phân vùng" nới ±1 ngày (`:594-599`); `GROUP BY` ngày; CTE khách hàng (`:1294-1300`) |
| `sku_code` | STRING | `sku_id` | KEY / REQUIRED | `GROUP BY`; loại `NULL_SKU` (`:624-625`); so trùng; CTE khách hàng |
| `fc_code` | STRING | `fc_id` | KEY / REQUIRED | `GROUP BY`; loại `NULL_FC`; so trùng; CTE khách hàng |
| `demand_quantity` | INTEGER | `order_qty` | TARGET / REQUIRED | `SUM` → `qty` (nhãn); loại `NULL_TARGET`, `NEGATIVE_TARGET`; trọng số giá; đối soát tổng (`:1362-1365`) |
| `so_code` | STRING | `order_id` | KEY / OPTIONAL | `n_orders = COUNT(DISTINCT)` (`:1244`); so trùng. `key_columns` rỗng nên không có gate khóa (SUM_ALL, `:1313-1323`) |
| `sales_price` | FLOAT | `unit_price` **và** ref `sales_price` | OPTIONAL_FEATURE (usage REQUIRED) + REFERENCE | `avg_unit_price = SUM(giá×SL)/SUM(SL có giá)` (`:1245`) → feature `price_last`, `price_rel_28`. Bản ref: so trùng, thống kê kiểm tra. Một cột dùng cho hai trường → cảnh báo `COLUMN_USED_TWICE` (`:424-425`) |
| `product_id` | INTEGER | ref `product_id` | REFERENCE | So trùng; kiểm tra toàn kỳ |
| `item_code` | STRING | ref `item_code` | REFERENCE | Phân biệt `MULTI_ITEM` / `CONFLICT` của giờ mở bán (`:1225-1231`); **không** so trùng (`DUP_NOT_COMPARED_FIELDS`, `:668`) |
| `outbound_quantity` | INTEGER | ref `outbound_qty` | REFERENCE | Đối chiếu xuất / cầu trong kiểm tra; so trùng |
| `order_status` | STRING | ref `order_status` | REFERENCE | Miễn gate trùng cho dòng `WAIT_TO_CONFIRM` (`:667`, `:671-695`); phân bố trạng thái. **Không** lọc dòng |
| `seller_code` | STRING | ref `seller_code` | REFERENCE | So trùng; kiểm tra |
| `sku_system_status` | STRING | ref `sku_status` | REFERENCE | So trùng; phân bố. Không là feature (trạng thái hiện tại, `docs/BIGQUERY.md:426-428`) |
| `open_date` | DATE | ref `open_date` | REFERENCE | So trùng; kiểm tra |
| `total_open_hours` | FLOAT | ref `open_hours` | **REQUIRED_FEATURE** (lưu ở `reference_mapping`, usage OPTIONAL; bắt buộc qua `MANDATORY_REFERENCE_FIELDS`) | `COUNTIF NULL`, `MIN`, `MAX`, số item (`:1216-1231`) → `open_hours.cell` → `demand_daily.open_hours` / `open_hours_status` → feature `open_hours_last`, `open_hours_mean_7`; gate huấn luyện; kiểm tra toàn kỳ (`:944-945`, `:1074-1079`); so trùng |
| `total_open_days` | FLOAT | ref `open_days` | REFERENCE | So trùng; kiểm tra |
| `customer_id` | INTEGER | `customer_id_column` (không phải trường mapping; nằm trong mapping hash) | (feature khách hàng) | CTE `cust_src` → `cust_seq` → `cust` (`:1288-1310`): đếm khách, khách quay lại, tổng khoảng cách → feature `cust_*`. Mã khách **không** ra khỏi BigQuery |
| `seller_class` | STRING | — | UNCLASSIFIED | Không đọc |
| `refresh_time` | STRING | — | UNCLASSIFIED | Không đọc. `source_updated_at` cần TIMESTAMP / DATETIME (`:40`) |

Trường nội bộ không có cột (`discount_amount`, `promotion_flag`, `promotion_id`, `voucher_flag`, `voucher_amount`, `source_updated_at`, `batch_id`, ref `price_after_discount`) được thay bằng NULL có kiểu (`:1208-1215`). Hệ quả: `avg_discount_rate`, `promo_share`, `voucher_share` = NULL, nhóm feature tương ứng là NO_DATA.

**Gom ngày** (phần VALID của `_daily_sql`):

```python
# backend/app/bq/connector.py:1243-1250
    valid = f"""SELECT 'VALID' AS _kind, CAST(NULL AS STRING) AS _reason, _order_date AS order_date, CAST(sku_id AS STRING) AS sku_id,
  CAST(fc_id AS STRING) AS fc_id, SUM(order_qty) AS qty, COUNT(DISTINCT CAST({oid} AS STRING)) AS n_orders,
  SAFE_DIVIDE(SUM({up} * order_qty), SUM(IF({up} IS NULL, NULL, order_qty))) AS avg_unit_price,
  SAFE_DIVIDE(SUM({disc}), SUM({up} * order_qty)) AS avg_discount_rate,
  AVG({pf}) AS promo_share, AVG({vf}) AS voucher_share,
  MAX({upd}) AS max_source_updated_at, MAX(CAST({bid} AS STRING)) AS max_batch_id, COUNT(*) AS n_rows,
  {oh}
FROM checked WHERE _reason IS NULL GROUP BY 3, 4, 5"""
```

**Kiểm tra chất lượng và chống trùng** (theo thứ tự trong `fetch_daily`, `connector.py:1326-1373`):
1. `require_mapping` (`:715-728`): mapping so với schema **sống** (metadata bảng, `:1116-1121`). Thiếu cột, sai kiểu hoặc thiếu trường bắt buộc → `BQ_MAPPING_INVALID`.
2. `duplicate_gate`: dòng thô giống hệt nhau ở **mọi cột đã map**, trừ `item_code` (`dup_columns`, `:706-712`), và không phải đơn chờ. Chính sách `BLOCK` → `BQ_DATA_DUPLICATES`.
3. Loại dòng theo lý do `NULL_SKU`, `NULL_FC`, `NULL_TARGET`, `NEGATIVE_TARGET` (`:624-625`). Không loại theo `order_status`.
4. Gate khóa (`_key_gate`, `:1313-1323`): bỏ qua vì `SUM_ALL` và không có `key_columns`.
5. Đối soát: số dòng / tổng giữ = hợp lệ + bị loại (`:1362-1365`) → nếu lệch: `BQ_SYNC_RECONCILIATION_FAILED`.
6. Sau đó Python tính trạng thái giờ mở bán theo từng khóa (`open_hours.row_cell`) và ghi theo `history_sync` (giữ dòng đã thấy, nhật ký thay đổi).

**Cột của `demand_daily`** (`PRAGMA table_info`): `scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, voucher_share, loaded_at, open_hours, open_hours_status, customer_count, repeat_customer_count, repeat_interval_days_sum`.

### 14.2 `total_open_hours`: mọi chỗ code yêu cầu, và nếu XÓA cột khỏi bảng D-1

**Chỗ yêu cầu hoặc sử dụng** (backend: 241 lần trong 20 file; test: 363 lần trong 28 file; frontend: 46 lần trong 12 file):

| Lớp | Vị trí | Vai trò |
|---|---|---|
| Cấu hình | `settings_service.py:41-45`, `:111-114`, `:180-185` | `open_hours` = REQUIRED_FEATURE, `MANDATORY_REFERENCE_FIELDS`; `feature_open_hours` do run tự đặt; `training_start_rule = OPEN_HOURS_COVERAGE` |
| Mapping | `connector.py:46-48`, `:389-401`; `ops_routes.py:445-475` | Kiểu NUMERIC; bắt buộc map (`REQUIRED_NOT_MAPPED`, role REQUIRED_FEATURE); cột phải có trong schema sống (`COLUMN_NOT_FOUND`). Lưu mapping bị từ chối nếu lỗi; lưu thành công thì tắt `production_enabled` |
| Đọc BigQuery | `connector.py:1216-1231` (gom), `:944-945`, `:1074-1079` (kiểm tra toàn kỳ), `:715-728` (`require_mapping`) | Đếm NULL, MIN, MAX, số item theo khóa |
| Trạng thái theo khóa | `data/open_hours.py:52-80` | `mandatory()` = nguồn BIGQUERY; `cell()` → OK / MISSING / OUT_OF_RANGE / MULTI_ITEM / CONFLICT |
| Ghi D-1 / backfill | `sync.py:263-381` (`OPEN_HOURS_WOULD_BE_LOST`, preview), `:491-545`, `:607-612`; `data/history_sync.py:62-68`, `:101`, `:728` | Ghi giá trị và trạng thái; đếm giờ bị mất; so sánh lịch sử |
| Lưu trữ | `migrations/0007_open_hours.sql:19-20` | `demand_daily.open_hours REAL`, `open_hours_status TEXT` |
| Gate huấn luyện | `pipeline.py:354-368`, `:374`, `:455-465`; `data/open_hours.py:83-115` | `window_check` mọi dòng trong cửa sổ phải OK → nếu không: `OPEN_HOURS_INVALID`; `feature_open_hours = True` cho BIGQUERY |
| Quy tắc 6 khóa | `data/open_hours_override.py`; `data/demand.py:87-96` | MAX theo listing cho 6 khóa MULTI_ITEM |
| Panel / feature | `data/demand.py:157-163`; `ml/features.py:39-41`, `:109-111`, `:161-167`, `:279-289` | Đọc từ `demand_daily`; giờ chỉ có ở ngày có dòng cầu; `open_hours_last`, `open_hours_mean_7`; thiếu mảng → `ValueError OPEN_HOURS_NOT_IN_PANEL` |
| Registry / catalogue | `ml/feature_registry.py:55-56`, `:165-176`, `:225-260`, `:314-357`; `ml/feature_catalog.py`; `api/forecast_routes.py:446-450` | Độ phủ; `MANDATORY_NOT_READY`; `blocked_by: OPEN_HOURS_INVALID` |
| Nhận dạng dữ liệu | `data/identity.py:33-41` | Cột `open_hours` thuộc identity của run có dùng giờ |
| Kiểm tra dữ liệu | `data_checks.py:98-166`, `:251` | Bất biến giá trị/trạng thái, chỉ BIGQUERY, cửa sổ sẵn sàng |
| API / thông điệp | `api/data_routes.py:49-51` (`OPEN_HOURS_MANDATORY`); `api/bq_routes.py:246`; `messages.py:378-381`, `:408` | Không cho tắt; văn bản song ngữ |
| Giải thích | `ml/forecast_explainer.py` (12), `ml/explain.py` (4) | Tính lại feature từ `demand_daily` |
| Frontend | `pages/Mapping.tsx`, `Config.tsx`, `Dashboard.tsx`, `SqlSources.tsx`, `ForecastExplainer.tsx`, `explainer.ts`, `i18n.tsx` | Hiển thị / nhãn |

**Nếu XÓA `total_open_hours` khỏi bảng D-1** (mapping trong DB vẫn trỏ `open_hours ← total_open_hours`):

1. **D-1 (`D1_SYNC`):**
   - Vượt qua gate đầu: `production_enabled` vẫn true; validation đã lưu vẫn hợp lệ vì mapping hash không đổi (`sync.py:394-397`).
   - Sau tín hiệu / kiểm tra đủ dữ liệu, `fetch_daily` → `require_mapping` đọc metadata bảng sống → `validate_mapping` báo `COLUMN_NOT_FOUND` (`field open_hours, column total_open_hours, reference: true`, `connector.py:392-393`) → `AppError BQ_MAPPING_INVALID` 422.
   - Runner: mã này không thuộc `NEEDS_CONFIG_CODES` và không phải `BQ_ERROR` / `BQ_AUTH_MISSING`, nên `_fail(retry=False)` → **FAILED ngay, không thử lại**, alert ERROR `BQ_MAPPING_INVALID` (`runner.py:336-339`, `:375-389`).
   - **Không ghi dòng nào** vào `demand_daily`. Lặp lại như vậy mỗi ngày. `ingest-check` (`sync.d1_dry_run`, `:596`) và gate `schema_mapping` của access-check cũng báo cùng lỗi.
2. **Không sửa được bằng cách bỏ map:**
   - `POST /api/bigquery/mapping` gọi `validate_mapping` → `REQUIRED_NOT_MAPPED` (role REQUIRED_FEATURE, `connector.py:397-401`) → 422, không lưu (`ops_routes.py:456-457`).
   - Đổi `feature_open_hours` qua cấu hình model cũng bị từ chối (`OPEN_HOURS_MANDATORY`, `data_routes.py:49-50`).
3. **Huấn luyện:**
   - Slot lịch của BIGQUERY chờ D-1 hôm nay thành công nên **không chạy** (`scheduler.py:135-140`).
   - Train tay vẫn qua `_bq_ready` (`flows.py:74-81`), nhưng dữ liệu không đổi → `SKIPPED NO_NEW_DATA` (`pipeline.py:363-364`).
   - Nếu ép chạy, `window_check` đọc **dòng đã lưu** (đều OK), nên **không** sinh `OPEN_HOURS_INVALID`.
   - Khi dữ liệu trễ quá `max_data_lag_days` = 2 ngày → `STALE_DATA` → `REJECTED STALE_DATA_BLOCKED` (`data/quality.py:108-121`; `pipeline.py:444-446`).
   - `OPEN_HOURS_INVALID` chỉ xuất hiện nếu có dòng không OK lọt vào cửa sổ, điều không xảy ra khi D-1 đã bị chặn.
4. **Feature `open_hours_*`:**
   - Không đổi cho các ngày đã lưu; không có ngày mới.
   - Model đang dùng (`MV-20261026-105345-C73F`) và forecast run hiện hành không bị chạm (forecast chỉ đổi khi promote, mục 13).
   - `ValueError OPEN_HOURS_NOT_IN_PANEL` không xảy ra, vì `build_panel` luôn tạo mảng giờ khi cột `open_hours` có trong `demand_daily`.
5. **D-0 không bị ảnh hưởng:** SQL D-0 đang dùng (phiên bản 3) đọc `demand_planing_lightgbm_D0`, không nhắc `total_open_hours`; `d0_mapping` chỉ có `sku_id, fc_id, order_qty, order_date, order_id`.
6. **Test:**
   - **Không test nào fail**: test đơn vị dùng BigQuery giả; test BigQuery thật (`test_*real_bq*`, `test_bq_real_semantics.py`) chỉ chạy khi `DF_REAL_BQ=1` và dùng dòng INLINE, không đọc bảng thật.
   - Các test **khóa yêu cầu này** sẽ fail chỉ khi **code** bị đổi để bỏ cột (ví dụ `tests/test_v129_weekday_open_hours.py`):
     - `test_open_hours_must_be_mapped_and_cannot_be_unused` (:155);
     - `test_training_on_bigquery_stops_until_every_row_of_the_window_has_valid_open_hours` (:458);
     - `test_a_panel_without_open_hours_is_never_passed_off_as_the_input` (:380);
     - `test_model_settings_refuse_switching_open_hours_off_and_never_store_the_dow_encoding` (:105);
     - `test_daily_sql_reads_line_counts_and_min_max_of_open_hours` (:253);
     - `test_full_period_validation_reports_missing_and_out_of_range_open_hours` (:320);
     - `test_registry_shows_open_hours_mandatory_for_bigquery_and_not_applicable_elsewhere` (:511).

**Kết luận 14.2:** xóa cột làm job D-1 dừng ngay với `BQ_MAPPING_INVALID` (không thử lại, không ghi), và không bỏ map được vì `open_hours` là REQUIRED_FEATURE. Huấn luyện dừng vì không có dữ liệu mới, không phải vì `OPEN_HOURS_INVALID`. Model và forecast đang dùng không đổi; không test nào fail.

### 14.3 Nếu thêm MỘT BẢNG RIÊNG giờ mở bán (`fc_code, sku_code, ngày, total_open_hours`, mọi ngày): các chỗ phải thêm

Chỉ liệt kê, **không** thiết kế, **không** sửa.

| Hạng mục | Chỗ phải thêm / đổi |
|---|---|
| Cài đặt | `BigQuerySettings` (`settings_service.py:332-382`): khóa mới cấp trên cùng cho bảng và cột (mẫu "older versions ignore them"); `FIELD_ROLES` / `MANDATORY_REFERENCE_FIELDS` (`:41-45`) đang gắn giờ vào mapping bảng D-1; `mapping_hash` (`connector.py:524-537`) và điều kiện nạp lại toàn kỳ khi hash đổi (`sync._d1_window`); `schema_snapshot` / drift cho bảng thứ hai; `data_policy.training_start_rule` (`:180-185`) |
| Connector SQL | Đọc schema + `validate_mapping` / `require_mapping` cho bảng mới (`connector.py:337-434`, `:715-728`); kiểu `REF_COMPATIBLE` (`:42-48`); `_daily_sql` đang lấy giờ từ dòng đơn và phát hiện MULTI_ITEM qua `item_code` (`:1216-1231`); `dup_columns` đang so cả `ref_open_hours` (`:706-712`); kiểm tra toàn kỳ (`:930-1110`, `:944-945`, `:1074-1079`); ước tính chi phí / dry-run (`estimate_daily_query`, `maximum_bytes_billed`); access-check (`ACCESS_GATES`, `:1531`); tín hiệu hoàn tất / đủ dữ liệu cho bảng mới (`completion_signal`, `sufficiency_check`, `:1480-1510`) |
| Job đồng bộ | `sync.run_d1_sync` (`sync.py:385-…`): đọc và ghép bảng thứ hai, cùng phiên bản nguồn trong một lần đọc; backfill preview và `OPEN_HOURS_WOULD_BE_LOST` (`:263-381`); `d1_dry_run` (`:590-640`); `history_sync` (`data/history_sync.py:62-68`, `:101`, `:728`; nhật ký thay đổi, dòng giữ); lập lịch nếu bảng có giờ làm mới riêng (`jobs/scheduler.py`, `jobs/flows.py`) |
| Migration SQLite (additive) | File mới `backend/app/migrations/0011_<name>.sql` (bản mới nhất hiện là `0010_history_sync.sql`). Hiện giờ chỉ nằm trên dòng `demand_daily` (`0007_open_hours.sql`), tức chỉ có ở ngày có đơn. Cần chỗ lưu cho ngày không đơn. Kiểm tra trên bản sao DB, đếm dòng trước / sau, `data-check`, kế hoạch rollback (AGENTS.md mục 4) |
| Ghép vào panel | `data/demand.load_demand` (`demand.py:156-178`) và `panel_for_run` (`:82-97`); `ml/features.build_panel` (`features.py:109-111`) và tài liệu của `Panel.hours` (`:39-41`: "NaN = no demand row that day"); `features_at` (`:279-289`): nghĩa của `open_hours_last` / `open_hours_mean_7` đổi, nên phải train lại; `open_hours_override.fill` (6 khóa); `identity.columns_for` (`data/identity.py:33-41`); `demand.fingerprint` (`:181-193`) chỉ băm `demand_daily` (thay đổi chỉ ở giờ sẽ không được thấy, `NO_NEW_DATA`); tái lập / giải thích run cũ (`ml/forecast_explainer.py:52-54`, `ml/explain.py`, `shap_audit.py`, `treeshap_trace.py`) |
| Kiểm tra chất lượng | `data/open_hours.window_check` / `coverage_start` (`open_hours.py:83-115`, đang quét `demand_daily`); gate trong `pipeline.train_and_publish` (`pipeline.py:354-368`, `:455-465`); `ml/feature_registry` (độ phủ `:165-176`, quyết định `:225-260`, `:314-357`); `data_checks._open_hours_checks` (`data_checks.py:98-166`); báo cáo chất lượng dữ liệu (`data/quality.py`) |
| API / UI | `ops_routes.py` (`/bigquery/mapping` `:445-475`, `/bigquery/validate` `:384-387`, `/bigquery/ingest-check` `:390-394`); `bq_routes.py` (access-check `:134-137`, kết quả D-1 `:246`); `messages.py` (mã lỗi song ngữ, `:378-381`, `:408`); frontend `pages/Mapping.tsx`, `pages/SqlSources.tsx`, `pages/Config.tsx`, `pages/Dashboard.tsx`, `pages/ForecastExplainer.tsx`, `explainer.ts`, `i18n.tsx` |
| Test | 28 file test backend có `open_hours` (nhiều nhất: `test_v129_weekday_open_hours.py` 113 lần, `test_v1212_open_hours_override.py` 47, `test_v129c_window_spike_customer.py` 44, `test_v1213_six_key_reverify.py` 19, `test_v1210_multi_item_open_hours.py` 21); test BigQuery thật opt-in (`test_v129_real_bq_open_hours.py`, `test_v1210_real_bq_multi_item_regions.py`); frontend `v115`, `v129`, `v129b`, `v129c`, `v1214.test.tsx`; test migration trên bản sao DB |
| Tài liệu | `docs/BIGQUERY.md`, `docs/data/DATA-MODEL.md`, `docs/data/DATA-DICTIONARY.md`, `docs/MO-HINH-VA-CHI-SO.md`, `CHANGELOG.md` |

### 14.4 `demand_daily`: số dòng và số cặp SKU × FC mỗi ngày, 14 ngày gần nhất

Scope `BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`; ngày lưu mới nhất 25/10 (D-1 của ngày 26/10). Một dòng = một khóa ngày × SKU × FC, nên số dòng = số cặp.

| Ngày | Dòng | Cặp SKU × FC | Tổng qty | `open_hours` NULL | `customer_count` NULL | `open_hours_status` = OK |
|---|---:|---:|---:|---:|---:|---:|
| 12/10 | 3.510 | 3.510 | 89.613 | 0 | 9 | 3.510 |
| 13/10 | 3.326 | 3.326 | 77.121 | 0 | 2 | 3.326 |
| 14/10 | 3.255 | 3.255 | 100.046 | 0 | 1 | 3.255 |
| 15/10 | 3.219 | 3.219 | 91.916 | 0 | 3 | 3.219 |
| 16/10 | 3.120 | 3.120 | 91.980 | 0 | 3 | 3.120 |
| 17/10 | 2.965 | 2.965 | 68.050 | 0 | 1 | 2.965 |
| 18/10 | 2.661 | 2.661 | 57.312 | 0 | 1 | 2.661 |
| 19/10 | 3.326 | 3.326 | 89.512 | 0 | 7 | 3.326 |
| 20/10 | 3.033 | 3.033 | 78.110 | 0 | 5 | 3.033 |
| 21/10 | 3.151 | 3.151 | 96.250 | 0 | 8 | 3.151 |
| 22/10 | 3.124 | 3.124 | 99.164 | 0 | 0 | 3.124 |
| 23/10 | 2.950 | 2.950 | 73.941 | 0 | 0 | 2.950 |
| 24/10 | 2.784 | 2.784 | 50.652 | 0 | 0 | 2.784 |
| 25/10 | 2.763 | 2.763 | 55.335 | 0 | 0 | 2.763 |

Cả 14 ngày: BD 25.870 dòng (4.108 SKU), HN 17.317 dòng (4.163 SKU). Chỉ có cặp có đơn; ngày không đơn không có dòng (14.1).

### 14.5–14.7 Phần B (BigQuery): **CHƯA CHẠY**

Lý do: yêu cầu ghi "CHỈ CHẠY NẾU ĐƯỢC CHO PHÉP", và lần này chưa có cho phép. Không chạy truy vấn nào, kể cả dry-run. Dưới đây là truy vấn dự kiến, để duyệt.

| Mục | Truy vấn dự kiến (chạy qua đường xác thực của app, dry-run trước, `maximum_bytes_billed` = 1 GB) | Ghi chú chi phí |
|---|---|---|
| 14.5 | `SELECT column_name, data_type, is_nullable, ordinal_position FROM \`lakehouse-prod-394907.gold_buymed_vn2.INFORMATION_SCHEMA.COLUMNS\` WHERE table_name = 'demand_planing_lightgbm' ORDER BY ordinal_position` | Truy vấn metadata, tính tối thiểu 10 MB |
| 14.6 | `SELECT * EXCEPT (customer_id, so_code), TO_HEX(SHA256(CAST(customer_id AS STRING))) AS customer_id_sha256, TO_HEX(SHA256(so_code)) AS so_code_sha256 FROM \`…demand_planing_lightgbm\` WHERE created_date = '<ngày gần nhất>' LIMIT 20` | **Bảng không phân vùng** (`docs/BIGQUERY.md:608`): lọc ngày và `LIMIT` không giảm số byte quét, tức quét toàn bộ các cột được chọn trên cả bảng. Các lần đọc trước quét 1,3–3,5 GB, nên có thể **vượt trần 1 GB**. Dry-run sẽ cho số chính xác; nếu vượt thì cần bớt cột hoặc duyệt trần khác |
| 14.7 | `SELECT created_date, COUNT(*) AS rows FROM \`…demand_planing_lightgbm\` WHERE created_date >= DATE_SUB(CURRENT_DATE('Asia/Ho_Chi_Minh'), INTERVAL 14 DAY) GROUP BY 1 ORDER BY 1` | Chỉ quét cột `created_date` (DATE, 8 byte / dòng, khoảng 9 triệu dòng), ước tính dưới 100 MB |

**Thông tin có sẵn tạm thời cho 14.5, không phải truy vấn mới:**
- `schema_snapshot` trong `app_settings.bigquery`, lưu cùng mapping lúc 2026-10-22T17:57:27Z.
- 18 cột, mọi cột `mode = NULLABLE`: `fc_code` STRING, `created_date` DATE, `so_code` STRING, `customer_id` INTEGER, `order_status` STRING, `product_id` INTEGER, `sku_code` STRING, `item_code` STRING, `seller_code` STRING, `sku_system_status` STRING, `demand_quantity` INTEGER, `outbound_quantity` INTEGER, `sales_price` FLOAT, `seller_class` STRING, `open_date` DATE, `total_open_hours` FLOAT, `total_open_days` FLOAT, `refresh_time` STRING.
- Đây là ảnh chụp ngày 22/10, không phải schema sống hôm nay.
