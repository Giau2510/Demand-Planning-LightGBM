# Báo cáo batch v1.1.1: giải thích forecast, trạng thái job, horizon, thực tế trong ngày, Excel i18n, tài liệu thuật toán

- Thời điểm lập: 2026-10-14 16:20 (giờ VN)
- Phiên bản: **1.1.1**, gói `dist\DemandForecast-1.1.1-win64-portable.zip`
- Ứng dụng đang chạy: **vẫn là 1.1.0** (cổng 8765). Theo yêu cầu "Không tự ý cài đè ứng dụng đang chạy", tôi **chưa cài** 1.1.1.

**Kết luận: THÀNH CÔNG CÓ ĐIỀU KIỆN.** Phần source, test và gói phân phối đã hoàn tất và có bằng chứng (mục 10–12).
Điều kiện còn lại: người dùng tự chạy quy trình nâng cấp ở mục 14 trên máy này. Bản 1.1.1 mới chỉ được kiểm thử
trong môi trường cô lập trên chính máy này. Chưa kiểm thử trên máy Windows khác.

---

## 1. Nguyên nhân gốc từng vấn đề

| # | Vấn đề | Nguyên nhân gốc (đã xác minh) |
|---|---|---|
| 1 | Không biết job huấn luyện/forecast đang ở đâu | `job_runs` chỉ có `status`. Pipeline không ghi công đoạn nào. UI chỉ hỏi danh sách job, nên không gắn lại được vào job sau khi tải lại trang. Bấm nhiều lần có thể tạo job trùng loại. |
| 2 | Cấu hình 7+15 ngày nhưng trang Kết quả chỉ có 7 ngày | Đọc DB thật (chỉ đọc): run `FCR-20261014080621-8D88F1` tạo lúc 08:06:21Z với `horizons=[7]`; cấu hình đổi sang `[7,15]` lúc 08:10Z. Run là bất biến và chỉ chứa các khoảng được bật **lúc chạy**. Không có dữ liệu nào bị mất. UI không giải thích sự chênh lệch này. |
| 3 | Không có "Xem cách tính" | Không lưu lý do chọn phương pháp theo chuỗi. Không có API tái tạo dự báo. Không có cơ chế đóng góp feature. |
| 4 | Tên phương pháp chỉ là mã kỹ thuật | Không có registry tập trung; mỗi trang tự hiển thị mã. |
| 5 | Excel chỉ một ngôn ngữ | Nhãn sheet/cột được viết cứng trong route export. |
| 6 | Không có thực tế trong ngày bên cạnh forecast | Snapshot D0 có sẵn nhưng chưa được nối vào run (theo scope) ở trang Kết quả, Tổng quan và Excel. |
| 7 | Trang Thuật toán sơ sài | Chỉ có 8 dòng tóm tắt và bảng thuật ngữ. Thiếu quy tắc chọn phương pháp, backtest, quality gate, ví dụ số và ngưỡng thật. |

## 2. File thay đổi và chức năng

Thư mục dự án không phải Git repo. Không commit, không push.

**Backend**

| File | Chức năng |
|---|---|
| `backend/app/__init__.py` | Version 1.1.1 |
| `backend/app/migrations/0003_job_stages_explainability.sql` (mới) | Cột công đoạn job, `derived_from_run_id`, bảng `forecast_series_meta` (có trigger chặn sửa/xóa) |
| `backend/app/jobs/progress.py` (mới) | Danh sách công đoạn thật theo loại job; `set_stage()` ghi lịch sử |
| `backend/app/jobs/runner.py` | Ghi công đoạn khi đổi trạng thái; job `FORECAST_EXTEND`; khôi phục job bị gián đoạn ghi `INTERRUPTED` |
| `backend/app/api/background.py` | Chống job trùng theo nhóm (huấn luyện và bổ sung khoảng dùng chung nhóm), trả về `already_active` |
| `backend/app/ml/model.py` | `classification_details()` là nguồn duy nhất cho quy tắc chọn phương pháp; `series_meta()`; `forecast(capture=)` lấy đúng hàng feature đã đưa vào model |
| `backend/app/ml/pipeline.py` | Báo công đoạn; phân biệt `PUBLISH_FAILED` với lỗi huấn luyện, có `failed_stage`; `_publish_run()` dùng chung; `extend_forecast()` |
| `backend/app/ml/methods.py` (mới) | Registry phương pháp và lý do (vi/en, scope production/backtest, anchor) |
| `backend/app/ml/explain.py` (mới) | Giải thích một SKU × FC × ngày (mục 6) |
| `backend/app/data/intraday.py` (mới) | Thực tế trong ngày (mục 7) |
| `backend/app/export_i18n.py` (mới) | Nhãn Excel vi/en, `EXPORT_FORMAT_VERSION = "2"` |
| `backend/app/api/forecast_routes.py` | `horizon_coverage`, cột actual, export theo `lang`, các API explain/extend/methods |
| `backend/app/api/ops_routes.py` | `/jobs/active`, `/jobs/latest`, `/jobs/{id}`; thêm `stage_history`, `elapsed_seconds`, `stale` |
| `backend/app/messages.py` | Mã mới: `PUBLISH_FAILED`, `FORECAST_EXTENDED`, `NOTHING_TO_EXTEND`, `MODEL_ARTIFACT_MISSING`, `DATA_CHANGED_SINCE_TRAINING`, `REPRODUCTION_MISMATCH` |
| `backend/tests/test_v111.py` (mới) | 16 test cho K1–K6 |

**Frontend**

| File | Chức năng |
|---|---|
| `frontend/package.json` | Version 1.1.1 |
| `src/components/ui.tsx` | `LineChart` với một điểm actual; `MethodLabel` + tooltip (hover/focus/chạm, Esc); `JobProgress`; `jobOutcome`; `useMethods` |
| `src/pages/Results.tsx` | Thông báo khoảng thiếu + nút bổ sung; cột actual; nút "Xem cách tính"; export theo ngôn ngữ |
| `src/pages/ExplainPanel.tsx` (mới) | Modal giải thích, chuyển ngày trước/sau |
| `src/pages/Dashboard.tsx` | Tiến trình job (gắn lại sau reload), khóa nút khi đang chạy, khoảng theo run, actual |
| `src/pages/Jobs.tsx` | Cột công đoạn và thời gian chạy, kết quả, lịch sử công đoạn, `?job=` |
| `src/pages/Methodology.tsx`, `src/algorithms.ts` (mới) | Trang Thuật toán & thuật ngữ (mục 9) |
| `src/i18n.tsx`, `src/styles.css` | 125 khóa vi/en mới; CSS |
| `src/v111.test.tsx`, `src/test-fixtures/methods.json` (mới) | 10 test frontend; fixture xuất từ registry backend |

**Tài liệu:** `docs/MO-HINH-VA-CHI-SO.md`, `docs/SCHEDULER.md`, `docs/HUONG-DAN-SU-DUNG.md`, `docs/VAN-HANH.md`
(quy trình nâng cấp 1.1.0 → 1.1.1), `docs/CHECKPOINT.md`.

## 3. Thay đổi schema/API

**Schema 2 → 3** (`0003`): migration này chỉ **thêm**, không sửa hay xóa dữ liệu cũ. Ứng dụng tự tạo bản sao lưu
`pre-migration-v2` trước khi chạy migration.
- `job_runs`: thêm `stage`, `stage_updated_at`, `stage_history_json`.
- `forecast_runs`: thêm `derived_from_run_id`.
- Bảng mới `forecast_series_meta(run_id, sku_id, fc_id, method, reason_code, details_json)` có trigger chặn UPDATE/DELETE.

Không có migration ngược: 1.1.0 từ chối mở schema 3. Thay vào đó, chiến lược quay lại là khôi phục bản sao lưu
`pre-migration-v2`, và cách này **đã được kiểm thử** (mục 12).

**API mới/đổi**
- `GET /api/jobs/{id}`, `GET /api/jobs/active?job_type=`, `GET /api/jobs/latest`. Job có thêm `stage`, `stage_history`, `elapsed_seconds`, `stale`.
- `POST /api/training/run`: nếu đã có job đang chạy thì trả về job đó kèm `already_active: true`.
- `GET /api/forecast-runs/{id}` có thêm `horizon_coverage`.
- `POST /api/forecast-runs/{id}/extend` tạo job `FORECAST_EXTEND`.
- `GET /api/forecast-runs/{id}/explain?sku_id&fc_id&target_date`.
- `GET /api/methods`.
- `summary`/`values` có thêm khối `actual` và trường `actual_today`.
- `export.xlsx?lang=vi|en`.

## 4. Thiết kế trạng thái job và cập nhật UI

- Công đoạn chỉ được ghi khi code thực sự bước sang bước đó.
  - Huấn luyện: QUEUED → STARTED → VALIDATING_DATA → PREPARING_DATA → BACKTESTING → TRAINING → QUALITY_GATE → FORECASTING → PUBLISHING → DONE.
  - Bổ sung khoảng: … VERIFYING_MODEL → PREPARING_DATA → FORECASTING → PUBLISHING → DONE.
  - D0/D1: … SYNCING → DONE.
  - **Không có phần trăm.**
- Kết quả huấn luyện và kết quả publish hiển thị riêng (vd. "Hoàn tất — không đạt chất lượng · Kết quả publish: Không publish (giữ forecast trước đó)").
  - Lỗi trong bước PUBLISHING có mã `PUBLISH_FAILED`.
  - Lỗi trước đó có mã `TRAINING_FAILED` kèm `failed_stage`.
  - Forecast hợp lệ trước đó luôn được giữ.
- Không có job trùng: khi chèn job, hệ thống kiểm tra job đang chờ/chạy cùng nhóm trong cùng transaction.
- Sau khi tải lại trang: Tổng quan và Kết quả dự báo gọi `/api/jobs/active` để gắn lại vào job đang chạy, rồi hỏi trạng thái mỗi 2 giây.
- Lỗi khi hỏi trạng thái hiển thị "Mất kết nối… KHÔNG có nghĩa là job thất bại".
- Job RUNNING không cập nhật công đoạn quá `timeout + 60 s` được gắn cờ `stale`. Khi khởi động lại, job dở dang được đánh dấu `INTERRUPTED`; job bấm tay chỉ có 1 lượt nên chuyển thành Thất bại. Không job nào hiển thị "đang chạy" mãi.
- Hiển thị ở Tổng quan, Kết quả dự báo (job bổ sung) và Job & Scheduler, vi/en.

## 5. Đồng bộ horizon khi cấu hình thay đổi sau một run

- Run không bao giờ được hiển thị như có thêm ngày. Bộ chọn khoảng chỉ liệt kê các khoảng có trong run. API trả 422 nếu yêu cầu khoảng run không có.
- Trang báo rõ: "Lần chạy này được tạo trước khi bật khoảng 15 ngày…".
- **Bổ sung không huấn luyện lại** chỉ chạy khi đủ cả các điều kiện sau:
  - mô hình còn file và sha256 khớp;
  - dấu vân tay dữ liệu bằng lúc huấn luyện, và `data_as_of` không đổi;
  - kích thước nằm trong `max_forecast_rows`;
  - dự báo tái tạo **khớp chính xác mọi giá trị đã publish**.
- Kết quả là một run **mới** có `derived_from_run_id`, cùng model version, origin và data-as-of. Run gốc không bị sửa.
- Nếu không đủ điều kiện, trang hiện mã lý do và hướng dẫn huấn luyện mới.
- Ngày bắt đầu = forecast origin, ngày kết thúc = origin + h − 1. Cô lập: 2026-10-14 → 2026-10-28 cho 15 ngày.

## 6. Giải thích forecast (LightGBM và dự phòng)

- **Lý do chọn phương pháp:** đọc từ `forecast_series_meta`. Run cũ được tính lại bằng đúng dữ liệu và cấu hình của lần huấn luyện, nhưng chỉ khi dấu vân tay dữ liệu không đổi; giao diện ghi rõ "tính lại". Nếu dữ liệu đã đổi, giao diện báo không xác định được và không đoán.
- **Lịch sử:** 56 ngày đến data-as-of (không có ngày tương lai). Mỗi ngày được phân biệt: có đơn / 0 đơn / không có dữ liệu / trước khi chuỗi bắt đầu.
- **Dự phòng:** hiển thị đúng phép chia code đã dùng. Ví dụ thật trong môi trường cô lập: `892 ÷ 19 = 46,9474`, khớp giá trị đã publish. Phương pháp dự phòng không bao giờ được gọi là LightGBM.
- **LightGBM:** tải lại file mô hình đã kiểm sha256, tái tạo dự báo đệ quy, và chỉ hiển thị khi giá trị tái tạo bằng giá trị publish.
  - Đóng góp feature là SHAP chính xác do LightGBM tính (`pred_contrib=True`, TreeSHAP), trong thang điểm thô: `exp(gốc + Σ đóng góp)` với Tweedie/Poisson, cắt ≥ 0.
  - Mỗi feature có giá trị, nguồn (thực tế / dự báo ngày trước / lịch / giữ giá trị cuối / giả định 0) và cờ "được cây sử dụng". Feature không cây nào dùng được liệt kê riêng.
  - Không bịa hệ số hay công thức.

## 7. Thực tế trong ngày (actual intraday)

- **Nguồn:** snapshot D0 **thành công** gần nhất của **cùng scope** với run, cho ngày VN hôm nay. Ngày được tính theo `Asia/Ho_Chi_Minh`.
- **Giá trị:** số lượng lũy kế. `as_of` = `snapshot_at`, tức lúc đọc nguồn thật, không bao giờ là giờ hiện tại.
- **Trạng thái:**
  - `PARTIAL_DAY`;
  - `STALE`: quá (khoảng cách lớn nhất giữa các mốc D0 + `slot_grace_minutes`), mặc định 140 phút;
  - `NO_DATA_TODAY`;
  - `NOT_APPLICABLE` cho MANUAL_IMPORT.
- **0 và trống:** SKU × FC vắng trong snapshot thành công = 0. Không có snapshot = trống, không phải 0.
- **Phạm vi hiển thị:**
  - chỉ ngày hôm nay có giá trị;
  - ngày tương lai luôn trống;
  - tổng chỉ cộng các chuỗi của run đã qua bộ lọc, mỗi chuỗi một lần;
  - biểu đồ có đúng một điểm actual;
  - DEMO luôn gắn nhãn.
- **Sau nửa đêm VN:** snapshot của hôm qua không được dùng cho ngày mới.

## 8. Quy tắc Excel/i18n

- `export.xlsx?lang=` theo ngôn ngữ UI.
  - vi: sheet `Thông tin`, `Tổng {h} ngày`, `Chi tiết theo ngày`.
  - en: `Info`, `Totals {h}d`, `Daily`.
- Tiêu đề cột, tên phương pháp (từ cùng registry với UI), trạng thái actual và metadata run được dịch.
- **Giữ nguyên:** mã phương pháp, run id, SKU, FC và giá trị số.
- Có định dạng phiên bản `2` và cột thực tế hôm nay (cùng quy tắc mục 7).
- Test đọc lại workbook: cả hai ngôn ngữ có cùng số liệu.

## 9. Thuật toán đã inventory và bổ sung tài liệu

Trang **Thuật toán & thuật ngữ** gồm 6 nhóm, có mục lục và anchor:
- **Quy trình:** pipeline, tổng hợp nhu cầu ngày, ma trận & ngày thiếu.
- **Feature:** đặc trưng LightGBM, chống rò rỉ.
- **Mô hình & phương pháp:** LightGBM, quy tắc chọn phương pháp, dự báo đệ quy, giải thích, cùng 5 mã từ registry. `FALLBACK_MODEL_UNAVAILABLE` được ghi "chỉ dùng trong backtest".
- **Đánh giá:** backtest walk-forward, baseline 28 ngày, WAPE/MAE/Bias/MAPE.
- **Chất lượng & publish:** kiểm tra dữ liệu, quality gate, publish/phiên bản/bổ sung khoảng.
- **Dữ liệu & snapshot:** snapshot D0, thực tế trong ngày.

Mỗi mục có tên vi/en, vị trí trong code, mục đích, đầu vào, các bước, công thức, ví dụ số, ý nghĩa nghiệp vụ, giới hạn
và liên kết.

**Bảng ngưỡng** đọc trực tiếp từ `/api/settings`.

**Ví dụ số** được kiểm tra bằng code thật (`test_documented_examples_are_correct`):
- MAE/WAPE/Bias/MAPE với [100,120,80] và [110,100,90];
- MAPE loại điểm A < 1;
- chuỗi gián đoạn 53/56 → 3 ÷ 28;
- `roll_mean_7` = 4;
- mốc backtest 122/129/136;
- exp(1,45) ≈ 4,263;
- ngưỡng cũ 140 phút.

Không đưa credential hay đường dẫn bí mật vào trang.

## 10. Kết quả kiểm thử

| Bộ | Pass | Fail | Skip | Bằng chứng |
|---|---|---|---|---|
| Backend pytest toàn bộ | 118 | 0 | 0 | `logs\development\tests_20261014_155749.log` (1 cảnh báo deprecation của starlette testclient, không liên quan) |
| Frontend vitest | 19 | 0 | 0 | cùng log |
| Typecheck (`tsc -b`, strict) | OK | — | — | cùng log |
| Production build (vite) | OK | — | — | cùng log |
| Lint/format | — | — | — | Dự án **không cấu hình** ESLint/Prettier/ruff nên không chạy. Typecheck strict là kiểm tra tĩnh duy nhất. |
| Gói 1.1.1, cài mới cô lập (LOCALAPPDATA tạm, cổng 8877): smoke chung | 24 | 0 | 0 | |
| Gói 1.1.1, cài mới cô lập: kiểm tra v1.1.1 (job, horizon, extend, explain, actual, Excel vi/en) | 30 | 0 | 0 | |
| Gói 1.1.1, nâng cấp trên **bản sao** DB thật (schema 2 → 3, cổng 8878) | 13 | 0 | 0 | |
| Rollback cô lập bằng gói 1.1.0 (`release\`) | 2 | 0 | 0 | 1.1.0 từ chối schema 3 (exit 1); bản `pre-migration-v2` mở được, 1 run, 588 dòng, tổng 10395,456, integrity ok |
| Smoke **chỉ đọc** trên app thật 1.1.0 | 7 | 0 | 0 | |

Một lần chạy smoke chỉ đọc đầu tiên có 1 FAIL ("active dataset unchanged"). Lỗi này do **tham số kỳ vọng của tôi sai**:
tôi dùng `CB692D` lấy từ báo cáo cũ. DB thật cho thấy lô ACTIVE là `DEMO-20261014080556-5342EB`, do người dùng tạo lúc
08:05:57Z, trước batch này, và là scope của run `FCR-…8D88F1`. Chạy lại với đúng kỳ vọng: 7/7.

## 11. Version và gói phân phối

- Version **1.1.1** (`backend/app/__init__.py`, `frontend/package.json`, `VERSION` trong gói). Không dùng lại 1.1.0.
- Gói: `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.1-win64-portable.zip`, 101 332 086 byte, SHA256 `52A79792BAFDF7277C04F32ADB6E56401CC1E0F392FD87CBEFB87ADEE554DE89`.
- Thư mục: `dist\DemandForecast-1.1.1\`. Python nhúng 3.14.7, LightGBM 4.7.0.
- Build bằng script chính thức `scripts\build-package.ps1`.

## 12. Dữ liệu, database và storage config được bảo toàn

- DB thật `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`:
  - vẫn **schema 2**, 1 forecast run, lô ACTIVE không đổi;
  - integrity + khóa ngoại OK;
  - app 1.1.0 vẫn dùng đúng DB này.
- Không ghi gì vào DB thật trong batch này. Bản sao cho test nâng cấp được lấy bằng SQLite backup API, nguồn mở `mode=ro`.
- Không cần sao lưu DB thật vì không có thao tác nào ghi vào nó.
- `storage.json` không đổi: `storage_id 6cff0821634b0447`, `data_dir D:\Buymed\Lightgbm AI\data\runtime`, `updated_at 2026-10-14T03:23:06Z`.
- Không chạy `storage-repair --apply`. Không đổi runtime path hay cấu hình migration storage.
- Không cài vào `%LOCALAPPDATA%\Programs\DemandForecast`: chỉ có 1.0.0 và 1.1.0. Không tạo shortcut, không có tác vụ autostart.
- Các app cô lập đã dừng (cổng 8877/8878 đóng).
- Không xóa dữ liệu, forecast, batch hay lịch sử job.
- Logic quality gate không đổi. Publish chỉ được tách thành `_publish_run()` dùng chung, cùng thứ tự ghi, trong một transaction.

## 13. Giới hạn và rủi ro chưa xử lý

- **Chưa triển khai** vào app đang chạy. 1.1.1 chỉ có hiệu lực sau khi người dùng chạy quy trình ở mục 14.
- Sau khi nâng cấp, muốn quay lại 1.1.0 thì phải khôi phục bản `pre-migration-v2`. Mọi dữ liệu phát sinh sau nâng cấp sẽ mất trong bản khôi phục.
- Giải thích LightGBM và bổ sung khoảng cần dữ liệu **không đổi** từ lúc huấn luyện. Khi dữ liệu thay đổi (vd. đồng bộ D-1 với BigQuery), run cũ chỉ còn hiển thị kết quả và lý do đã lưu; muốn có khoảng mới thì phải huấn luyện mới.
- Thực tế trong ngày với **BigQuery** chưa được kiểm thử với nguồn thật, vì BigQuery vẫn bị chặn. Mới kiểm thử với DEMO (mô phỏng).
- Sau mốc D0 cuối ngày (18:00), trạng thái chuyển "Có thể đã cũ" sau 140 phút. Hành vi này là có chủ đích nhưng có thể gây lo lắng vào buổi tối.
- **Lỗi từng công đoạn — đã test:** lỗi trong backtest, lỗi publish sau huấn luyện, quality gate không đạt, job bị gián đoạn. **Chưa test riêng:** lỗi giả lập ở VALIDATING_DATA và FORECASTING. Code xử lý chung theo cùng một đường.
- Đóng góp SHAP tính ở thang điểm thô (log) nên người dùng nghiệp vụ có thể khó đọc; đã ghi chú trong modal và trang thuật toán.
- Không có test trình duyệt E2E cho modal giải thích. Đã có component test và test API trên gói thật.
- Trong môi trường cô lập, một số file `__pycache__` của scipy không chép được vì đường dẫn tạm vượt 260 ký tự. App vẫn chạy bình thường. Đường cài thật ngắn hơn nhiều (~150 ký tự).
- Dự án không có công cụ lint/format.
- `package-lock.json` vẫn ghi version 1.0.0 (chỉ là hiển thị).
- Chưa kiểm thử trên máy Windows khác.

## 14. Hướng dẫn kiểm thử sau khi cập nhật (một quy trình)

1. Trên trang **Job & Scheduler**, chờ không còn job đang chạy.
2. Giải nén `DemandForecast-1.1.1-win64-portable.zip` ra thư mục tạm, rồi chạy `Install.bat` trong đó. Installer sẽ:
   - dừng 1.1.0;
   - sao lưu DB;
   - cài 1.1.1 bên cạnh 1.1.0;
   - chạy migration 0003 (có bản `pre-migration-v2`);
   - khởi động app.
3. Trên trang **Hệ thống**, kiểm tra:
   - phiên bản 1.1.1;
   - DB `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`;
   - schema 3.
4. Trên trang **Kết quả dự báo**, chọn run `FCR-20261014080621-8D88F1`:
   - Trang sẽ báo thiếu khoảng 15 ngày.
   - Bấm **Bổ sung khoảng dự báo**, chờ tiến trình đến *Hoàn tất*.
   - Run mới có 7/15 ngày; run cũ vẫn còn.
   - Bấm **Xem cách tính** ở một dòng LightGBM và một dòng dự phòng.
   - Đổi ngôn ngữ, rồi **Xuất Excel**.
5. Nếu có lỗi, dừng app, khôi phục bản `pre-migration-v2` bằng `scripts\restore.ps1` của 1.1.0, rồi chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0\Start.bat`. Chi tiết trong `docs\VAN-HANH.md`, mục *Nâng cấp 1.1.0 → 1.1.1*.
