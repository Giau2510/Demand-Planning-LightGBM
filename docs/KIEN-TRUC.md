# Kiến trúc & luồng dữ liệu

```
Trình duyệt ──HTTP 127.0.0.1:8765──► FastAPI (1 tiến trình Python trên Windows)
                                     ├─ /api/*            REST + JSON (schema Pydantic)
                                     ├─ /                 UI React đã build (web/ hoặc frontend/dist)
                                     ├─ Scheduler thread  (jobs/scheduler.py) ─► runner (lock, retry, timeout)
                                     └─ SQLite WAL        %LOCALAPPDATA%\DemandForecast\db\app.db
                                                    ▲
             BigQuery (chỉ đọc, dry-run + giới hạn bytes) ┘
```

## Stack

| Lớp | Công nghệ | Lý do |
|---|---|---|
| Backend | Python 3.14, FastAPI 0.143, Uvicorn | Một tiến trình, dễ đóng gói trên Windows |
| ML | LightGBM 4.7 (wheel chính thức), NumPy, pandas | scikit-learn không được dùng (backtest/metrics tự viết, giảm dung lượng gói) |
| DB | SQLite (WAL) + migration SQL có phiên bản | Không cần cài DB server |
| Excel | openpyxl (read-only, data_only, không macro) | |
| BigQuery | google-cloud-bigquery + OAuth trong ứng dụng (1.1.6) hoặc ADC | Chỉ đọc |
| Frontend | React 18 + TypeScript + Vite, biểu đồ SVG tự viết | Ít dependency |
| Đóng gói | Python embeddable (python.org) + wheels + UI build | Máy đích không cần Python/Node |

## Module backend (`backend/app`)

| Module | Trách nhiệm |
|---|---|
| `paths.py` | Nguồn duy nhất cho mọi đường dẫn (env > `storage.json` > mặc định), kiểm tra quyền ghi, chặn tạo DB trống — xem [LUU-TRU.md](LUU-TRU.md) |
| `storage_migrate.py` | Di chuyển thư mục lưu trữ có backup xác minh + rollback |
| `diagnostics.py` | Báo cáo chẩn đoán không chứa secret |
| `db.py`, `migrations/` | Kết nối, transaction, migration có backup trước, audit, alert |
| `settings_service.py` | Cấu hình tập trung có validation (Pydantic) + lịch sử; không chứa secret |
| `messages.py` | Danh mục mã lỗi/trạng thái song ngữ (`/api/messages`) |
| `data/schema.py` | Schema tạm thời, gợi ý ánh xạ (chỉ khớp chính xác/bí danh) |
| `data/validation.py` | Chuẩn hóa + kiểm định dòng dùng chung cho mọi nguồn |
| `data/excel_io.py` | Đọc .xlsx an toàn, file mẫu, báo cáo lỗi |
| `data/importer.py` | Vòng đời lô: upload → validate (PENDING_REVIEW) → confirm/cancel, thay thế, xóa |
| `data/demo.py` | Sinh dữ liệu DEMO + file mẫu |
| `data/demand.py` | Scope (1 bộ dữ liệu), tổng hợp `demand_daily`, fingerprint |
| `data/quality.py` | Báo cáo chất lượng dữ liệu cấp bộ dữ liệu |
| `ml/features.py` | Panel + `features_at` (không rò rỉ) |
| `ml/model.py` | Huấn luyện, phân loại dự phòng, dự báo đệ quy, backtest walk-forward |
| `ml/metrics.py` | WAPE, MAE, bias, MAPE |
| `ml/pipeline.py` | Huấn luyện → backtest → quality gate → publish bất biến |
| `sync.py` | Đồng bộ D-1 (BigQuery) và snapshot D0 |
| `bq/connector.py` | Kết nối, schema, ánh xạ, preview, profile, truy vấn tổng hợp (có fake client cho test) |
| `jobs/runner.py`, `jobs/scheduler.py` | Thực thi job và lập lịch, catch-up |
| `security.py` | Host allow-list, chống CSRF, token tắt ứng dụng |
| `backup.py`, `cli.py` | Sao lưu/khôi phục, lệnh `serve/migrate/backup/restore/check-env/data-check` |
| `data_checks.py` | Kiểm tra bất biến dữ liệu chỉ đọc (`app.cli data-check`) — xem [data/DATA-MODEL.md](data/DATA-MODEL.md) |
| `bq/oauth.py`, `bq/secret_store.py`, `bq/sql_guard.py`, `bq/sql_sources.py` | Đăng nhập Google (OAuth, Credential Manager), kiểm tra SQL, phiên bản SQL lịch sử/D0 (1.1.6) |
| `api/*` | Các router REST |

## Cô lập nguồn dữ liệu (scope)

`scope_key` xác định đúng **một** bộ dữ liệu: lô DEMO đang hoạt động, **một** lô MANUAL_IMPORT được chọn, hoặc
`BIGQUERY:<project>.<dataset>.<table>`. Mọi truy vấn, tổng hợp, huấn luyện, forecast, snapshot đều lọc theo scope —
không có đường nào trộn nguồn. Forecast run lưu scope, nguồn, model version.

## Bảng chính (migration `0001_initial.sql`, `0002_one_active_demo.sql`: tối đa 1 lô DEMO ACTIVE, `0003_job_stages_explainability.sql`)

Mô hình dữ liệu đầy đủ (ER, vòng đời, khóa, múi giờ, quy tắc ngầm định): [data/DATA-MODEL.md](data/DATA-MODEL.md);
từ điển dữ liệu: [data/DATA-DICTIONARY.md](data/DATA-DICTIONARY.md).

`app_settings`, `settings_history`, `import_batches`, `order_lines`, `import_row_errors`, `demand_daily`,
`validation_reports`, `training_runs`, `backtest_runs`, `forecast_runs` + `forecast_values` (trigger chặn UPDATE/DELETE),
`d0_snapshots` + `d0_snapshot_values` (chỉ ghi khi đồng bộ thành công; trigger chặn sửa giá trị), `job_runs`
(idempotency_key UNIQUE), `job_locks`, `sync_state`, `alerts`, `audit_log`, `schema_migrations`.

## Luồng chính

1. **Import**: upload (uploads/<id>.xlsx) → validate → lô `PENDING_REVIEW` + dòng đã chuẩn hóa + lỗi dòng → confirm
   (1 transaction: [thay thế lô cũ] → ACTIVE → tổng hợp `demand_daily`) hoặc cancel (xóa dữ liệu tạm).
2. **Huấn luyện**: báo cáo chất lượng → (dữ liệu không đổi? bỏ qua) → panel → backtest → train → gate →
   [lưu model file] → forecast đệ quy → 1 transaction ghi `training_runs` ACCEPTED + `forecast_runs` + `forecast_values`.
3. **D0**: đọc nguồn → chỉ khi thành công mới ghi snapshot + values (1 transaction).
4. **D-1**: tín hiệu/giờ dự phòng + kiểm tra đủ dữ liệu → truy vấn tổng hợp tăng dần → thay thế cửa sổ ngày trong
   `demand_daily` (1 transaction) → cập nhật watermark.

## Mở rộng về sau

- Đăng nhập: thêm middleware xác thực trong `security.py`; các router đã tách theo nhóm chức năng.
- Truy cập từ máy khác: hiện bị chặn (`DF_ALLOW_REMOTE`, `DF_ALLOWED_HOSTS`) — cần đánh giá bảo mật + đăng nhập trước.
- Migration mới: thêm `000N_<tên>.sql`; backup tự động trước khi áp dụng.
