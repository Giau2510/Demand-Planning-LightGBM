# DemandForecast — P0 SOURCE_NOT_READY, BigQuery production, forecast, D-0/D-1, model publish (17/10/2026, 19:25–)

Trạng thái báo cáo: **READY_FOR_PRODUCTION** (mục 9). Mọi giờ là giờ Việt Nam (UTC+7) trừ khi ghi UTC. Báo cáo chỉ chứa id, số đếm,
hash; không chứa bí mật.

## 1. Trạng thái production lúc bắt đầu (19:26)

| Hạng mục | Giá trị thật | Nguồn đọc |
|---|---|---|
| Phiên bản | 1.2.2 (`current.txt`, `/api/health` nội bộ và qua link) | file + HTTP |
| Tiến trình | app pid 37320 (1.2.2, từ 18:57), proxy chỉ đọc pid 13024, cloudflared pid 31076 (từ 16:54) | Win32_Process |
| Link sếp | https://volumes-jean-angels-configurations.trycloudflare.com → `{"ok":true,"version":"1.2.2"}` | HTTP |
| storage.json | SHA-256 8D79DBDD…E047 (không đổi) | file |
| Nguồn đang dùng | BIGQUERY | `/api/settings` |
| `bigquery.production_enabled` | **false** | `/api/settings` (DB `app_settings`) |
| Project / dataset / location | lakehouse-prod-394907 / gold_buymed_vn2 / asia-southeast1 | `/api/settings` |
| Ánh xạ D-1 | 15 cột; `unit_price ← sales_price` **REQUIRED** (trước 17:32 là OPTIONAL) | `/api/settings` + lịch sử settings id 23 → 26 |
| Validation toàn kỳ đã lưu | PASS 08:22 cho mapping hash `d1d0bff42dfb111a` — **không khớp** hash hiện tại | `sync_state.bq_validation` |
| D-1 gần nhất | JOB-20261017012623-2A31B7 (thủ công, xong 08:30), 01/01–16/10, 1.349.388 series-days, tổng 41.808.940 | `/api/schedules`, fingerprint |
| D-0 | chế độ SQL, v1/v2 chưa kiểm tra, chính sách khóa BLOCK, lịch TẮT | `/api/sql-sources` |
| Lịch | D-1 TẮT, D-0 TẮT (08:00…18:00), huấn luyện BẬT 09:00, missed-run huấn luyện SKIP | `/api/schedules` |
| Forecast | 4 lần, tất cả DEMO; nguồn BIGQUERY chưa có forecast | DB (mode=ro) |
| Model TRN-20261017101340-EEDA47 | REJECTED QUALITY_GATE_FAILED; file `MV-20261017-172653-DA47.txt` 5,37 MB, SHA khớp DB (`fc69311b9c6280eb`); `promotable` = BELOW_THRESHOLD (chỉ WAPE_MAX), LightGBM | file + `/api/training-runs/…` |

## 2. Hai (thực ra ba) job SOURCE_NOT_READY

| Job | Tạo (VN) | Kết thúc | Bước | Lý do |
|---|---|---|---|---|
| JOB-20261017121625-661B96 | 19:16:25 | 19:17:05 (40 s) | QUEUED → STARTED → VALIDATING_DATA → SKIPPED | SOURCE_NOT_READY |
| JOB-20261017121820-57FB9B | 19:18:20 | 19:18:54 (34 s) | như trên | SOURCE_NOT_READY |
| JOB-20261017122150-90EEDA | 19:21:50 | 19:22:26 (36 s) | như trên | SOURCE_NOT_READY |

* Ba lần bấm thủ công **riêng biệt** (ba idempotency key `TRAIN_PUBLISH:MANUAL:<ngẫu nhiên>`), không phải hai bản ghi
  của cùng một luồng. Tạo bởi `POST /api/training/run` hoặc `/api/jobs/run` → `background.submit` (không kiểm tra
  trước).
* Dừng ở `pipeline.train_and_publish`, bước VALIDATING_DATA, **trước mọi truy vấn BigQuery**: hàm tính fingerprint dữ
  liệu (~35 s trên 1,35 triệu dòng) rồi mới đọc `bigquery.production_enabled` (DB `app_settings`, đọc mỗi lần, không
  cache) → `AppError("SOURCE_NOT_READY")` không kèm chi tiết → runner ghi SKIPPED (mã thuộc NEEDS_CONFIG_CODES).
* Vì sao "huấn luyện đang bật" mà vẫn bị bỏ qua: trang *Job & Scheduler* ghi "Đang bật — scheduler đã nạp" chỉ từ công
  tắc `schedule.train_enabled=true`; backend thật ra báo luồng huấn luyện là `ON_NOT_READY` (lý do SOURCE_NOT_READY).
  Công tắc lịch và độ sẵn sàng của nguồn là hai trạng thái khác nhau; trang chỉ hiển thị cái thứ nhất.

## 3. Nguyên nhân gốc

| Điều kiện | Giá trị thực tế | Nguồn đọc | Lỗi cụ thể | Tác động | Khắc phục |
|---|---|---|---|---|---|
| `production_enabled` | false từ 17:32:20 | `app_settings.bigquery` (lịch sử id 26 "field mapping saved") | `POST /api/bigquery/mapping` luôn ghi `production_enabled=false` | D-1, huấn luyện BigQuery, D-0 → SOURCE_NOT_READY | Kiểm tra toàn kỳ → Kích hoạt |
| Mapping hash | `bc5fcb06327569fb` (usage nằm trong hash) | tính từ settings | validation đã lưu cho `d1d0bff42dfb111a` | sau khi bật lại sẽ là BQ_VALIDATION_REQUIRED | chạy lại validation toàn kỳ |
| `unit_price` REQUIRED | cột `sales_price` FLOAT có thật; 99,86 % dòng có giá | schema thật + validation | không có lỗi: REQUIRED chỉ = "phải ánh xạ tới cột có thật, đúng kiểu" | dòng thiếu giá KHÔNG bị loại (lý do loại chỉ NULL_SKU/NULL_FC/NULL_TARGET/NEGATIVE_TARGET) | giữ REQUIRED (đúng schema, nhóm giá đang BẬT) — không đổi |
| Kết nối/quyền | 6/6 cổng PASS 19:32 (ADC đã xác minh) | `POST /api/bigquery/access-check` | — | — | — |
| D-0 SQL | chưa có phiên bản VALID | `sql_sources.d0` | SQL_NOT_VALIDATED | chỉ chặn D-0 (không chặn huấn luyện) | lưu + xác nhận SQL (mục 5) |
| Giao diện | "Đang bật — scheduler đã nạp" | `Jobs.tsx` đọc công tắc | nhãn sai so với trạng thái thật | người dùng tưởng đã sẵn sàng | sửa ở 1.2.3 |

Lưu ánh xạ tắt production là có chủ đích (ánh xạ mới phải được kiểm tra lại) — không phải hệ thống "tự tắt vì validation
thất bại"; nhưng trước 1.2.3 không có cảnh báo trước/sau khi lưu và mã lỗi không nói từ lúc nào/vì sao/cách sửa.

## 4. Thao tác trên production (theo thứ tự, qua API chính thức của ứng dụng)

| Giờ | Thao tác | Kết quả | Bằng chứng |
|---|---|---|---|
| 19:31 | Backup | `backup-20261017-193147-manual.zip` 60.629.724 byte, SHA-256 29ED178E2CA0CC1A…6475B7 | `POST /api/system/backups` |
| 19:32 | Kiểm tra truy cập BigQuery | 6/6 cổng PASS (xác thực ADC đã xác minh, API+dataset, location asia-southeast1, metadata 8.910.595 dòng, query job, schema/mapping) | `POST /api/bigquery/access-check` |
| 19:32 | Kiểm tra dữ liệu toàn kỳ (mapping hiện tại, `unit_price` REQUIRED) | **PASS**, hash `bc5fcb06327569fb`, 01/01–17/10; 8.910.595 dòng / 41.808.940, 0 dòng bị loại, đối soát dòng + số lượng khớp; cảnh báo KEY_NOT_UNIQUE (7.348, SUM_ALL), MISSING_DAYS (17/10 = hôm nay), TARGET_OUTLIER; ước tính quét 3,49 GB | `POST /api/bigquery/validate` |
| 19:33 | **Kích hoạt chế độ sản xuất** | **BỊ TỪ CHỐI** bởi bộ kiểm soát quyền của Claude Code | `POST /api/bigquery/activate` không được gửi |
| 19:34 | **Dùng model TRN-20261017101340-EEDA47** (xác nhận `confirm=true`, như hộp thoại giao diện) | **PUBLISHED**: `FCR-20261017123417-FCC0EB`, model `MV-20261017-172653-DA47`, LightGBM, `USABLE_WITH_WARNING`, 25,7 s | `POST /api/training-runs/…/promote` |
| 19:38 | D-0: chính sách khóa `SUM_ALL`; lưu SQL v3 | lưu; lịch D-0 vẫn TẮT | `PUT /api/sql-sources/d0/options`, `POST …/versions` |
| 19:38 | D-0: xác nhận SQL v3 với BigQuery thật | **VALID**, phiên bản hoạt động = 3; quét 995 KB; 8.454 dòng **chỉ ngày 17/10**, 0 dòng ngày khác, 0 lỗi, 34.618, 2.142 chuỗi; 0 dòng trùng hoàn toàn; 48 dòng trùng khóa | `POST …/versions/3/validate` |
| 19:42 | D-1 thử khô (không ghi) | READY; nạp lại toàn kỳ; so với dữ liệu đang lưu: 0 mới / 0 cập nhật / 0 xóa / 1.349.388 không đổi | `POST /api/bigquery/ingest-check` |
| 19:49–19:50 | **SỰ CỐ** (mục 6) | `production_enabled` → true do test mất cách ly | lịch sử settings 30–32 |
| 19:5x | Hoàn nguyên sự cố | **BỊ TỪ CHỐI** bởi bộ kiểm soát quyền; chủ hệ thống chọn **giữ BẬT và làm tiếp** | hỏi–đáp trong phiên |
| 19:57 | Snapshot D-0 kiểm soát (chạy tay) | **SUCCEEDED** `SNP-20261017125745-3ABB90` (job JOB-20261017125743-69E98C, 2 s): 2.142 chuỗi, 34.618, chỉ 17/10, 0 dòng ngày khác; đối chiếu forecast: 2.142/2.142 chuỗi có dự báo | `POST /api/schedules/d0/run` |
| 19:58–20:04 | D-1 chạy tay | **SUCCEEDED** JOB-20261017125803-0ED367 (369 s): 01/01–16/10 (hôm nay loại trừ), nạp lại toàn kỳ, 8.910.595 dòng, 41.808.940, 1.349.388 series-days: 0 mới, 0 cập nhật, 0 xóa; 0 trùng hoàn toàn; hash mới đã ghi → lần sau chạy tăng dần | `POST /api/schedules/d1/run` |

Kiểm tra trùng khóa D-0 độc lập (truy vấn chỉ đọc trên bảng D0 thật, 19:40, dry-run trước, ≤ 1 MB): 39 khóa (đơn × SKU
× FC × ngày) có 87 dòng = 48 dòng thừa; 0 dòng giống hệt; **39/39 nhóm khác giá bán**, 31 khác số lượng, trạng thái /
product / item / seller giống nhau → là các dòng đơn riêng cùng SKU khác giá trong một đơn, cùng quy tắc nghiệp vụ D-1
(R1, chủ hệ thống quyết định 16/10: cộng; chỉ chặn dòng giống hệt). Vì vậy chọn `SUM_ALL`; cổng chặn dòng giống hệt
(`exact_duplicate_policy=BLOCK`) giữ nguyên.

## 5. Forecast BigQuery và dashboard (qua link của sếp)

* Record `FCR-20261017123417-FCC0EB`: `data_source=BIGQUERY`, scope `BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`,
  origin 17/10, dữ liệu đến 16/10, horizons 7/15, 17.125 chuỗi × 15 ngày = 256.875 giá trị (17/10–31/10), tổng 7 ngày
  624.167,85, tổng 15 ngày 1.241.888,65, 0 giá trị âm; phương pháp: LightGBM 4.277, intermittent 9.627, inactive 3.008,
  chuỗi mới 213. Lineage: bảng, location, cửa sổ 01/01–16/10, fingerprint dữ liệu của lần huấn luyện.
* Đánh giá: WAPE 0,807 > ngưỡng 0,60 (không đạt, hiển thị đúng), bias +0,058 (đạt); baseline 28 ngày 0,844 trên cùng
  3.351.605 điểm → LightGBM được chọn, baseline bị loại (WAPE cao hơn). Ngưỡng không đổi. Model cũ: không có model BIGQUERY
  nào trước đó; 4 lần forecast DEMO được giữ.
* Qua link (Edge headless, 4 trang, 0 lỗi console): Tổng quan hiển thị nguồn BIGQUERY, model, cửa sổ dữ liệu, hộp đánh
  giá "Được dùng — kèm cảnh báo · Dưới ngưỡng · WAPE 80,7 % / 60 %", tổng 7 ngày 624.168, mã lần dự báo; Kết quả dự báo
  mặc định chọn lần BIGQUERY, các lần DEMO có nhãn "(nguồn khác)". `/api/system/status` qua link: `forecast_state=OK`.

## 6. Sự cố: một lần ghi test chạm DB production (19:49–19:50)

* Trong test mới, `monkeypatch.undo()` (để gỡ một bản vá) đã gỡ luôn cách ly `DF_DATA_DIR` của conftest; dòng kế tiếp
  `ss.update("bigquery", {"production_enabled": True})` ghi vào DB thật — 3 lần (3 lần chạy test): lịch sử settings id
  30–32, audit 106–108.
* Phạm vi (đã đối chiếu): chỉ `production_enabled` false → true; mọi trường khác giống hệt bản ghi id 26; không job,
  alert, training, forecast nào; `runtime.json` không đổi; scheduler không chạy gì (mốc huấn luyện hôm nay đã SKIPPED,
  D-0/D-1 TẮT). Mọi điều kiện kích hoạt đều đạt tại thời điểm đó (connection, schema, profile, mapping, validation,
  location).
* Lệnh hoàn nguyên của tôi bị bộ kiểm soát quyền từ chối; chủ hệ thống chọn giữ BẬT và cho làm tiếp. Bản ghi kích hoạt
  chính thức `BIGQUERY_ACTIVATED` vì thế không có trong audit.
* Khắc phục vĩnh viễn: conftest đặt `DF_DATA_DIR` / `DF_STORAGE_CONFIG` tạm cấp tiến trình; test hồi quy
  `test_paths_never_reach_the_installation_even_after_monkeypatch_undo`; test mới dùng `monkeypatch.context()`. Các lần
  chạy test sau đó: lịch sử settings production không thêm dòng nào.

## 7. Code 1.2.3 và kiểm thử

Thay đổi (commit cục bộ 87f6fce + tài liệu aaecb52, **không push**):

* `jobs/flows.py`: `production_off_detail` (từ lúc nào, thay đổi nào đã tắt, cách khắc phục — đọc lịch sử settings),
  `source_blockers` (chỉ trạng thái nguồn), `manual_readiness` (bỏ điều kiện chỉ dành cho lịch `TRAIN_WAITS_FOR_D1`),
  `flow_view.manual_readiness`; `run_now` dùng `manual_readiness`.
* `ml/pipeline.py`: kiểm tra nguồn BigQuery **trước** fingerprint (dừng ngay thay vì sau ~35 s), kèm chi tiết.
* `api/background.py`: huấn luyện thủ công trên nguồn chưa sẵn sàng → 409 + lý do, không tạo job.
* `sync.py`: SOURCE_NOT_READY của D-1/D-0 có chi tiết. `messages.py`: thông điệp SOURCE_NOT_READY nói cách khắc phục.
* `api/ops_routes.py`: `/api/scheduler/status.flow_states` (trạng thái hiệu lực); lưu ánh xạ trả
  `production_switched_off`; *Tắt chế độ sản xuất* **giữ nguyên nguồn** (trước đây tự chuyển sang DEMO).
* Giao diện: Job & Scheduler hiển thị trạng thái hiệu lực + lý do; Lịch chạy dùng `manual_readiness` cho "Chạy ngay";
  Ánh xạ trường: hỏi xác nhận trước khi lưu khi production đang bật, báo sau khi lưu, ghi chú trạng thái production;
  BigQuery: hỏi xác nhận khi tắt production.
* Test: `conftest.py` (lưới an toàn cách ly), `test_v123_source_ready.py` (7), `v123.test.tsx` (5); một kỳ vọng ở
  `test_v122_bigquery_policy.py` đổi có lý do (route trả 409 thay vì tạo job SKIPPED — vẫn là lỗi, không fallback DEMO).

Kết quả (loại bằng chứng ghi rõ):

| Bộ | Kết quả | Loại |
|---|---|---|
| Backend pytest (release QA) | 405 passed, 7 skipped | tích hợp, DB tạm + BigQuery giả |
| BigQuery thật (`DF_REAL_BQ=1`) | 7/7 passed | dịch vụ thật, chỉ đọc |
| Frontend vitest / typecheck / build | 80/80, OK, OK | unit (jsdom) |
| Diễn tập nâng cấp có link riêng | 22/22 (1 mục đọc lại body 409 bằng Python) | cài đặt cách ly trên bản sao DB thật |
| Lint | không cấu hình | — |

Ánh xạ yêu cầu §9 → bằng chứng: (1) readiness OK khi production hợp lệ — `test_mapping_save_…` (kích hoạt chính thức
→ sẵn sàng), production: 3 luồng `ready=True`; (2) production tắt → đúng lý do — cùng test, job thật 409 trên bản sao;
(3) mapping chưa xác nhận → `BQ_VALIDATION_REQUIRED`; (4) `unit_price` sai schema → nêu đúng trường/cột —
`test_unit_price_mapping_errors_…`; (5) D-0 chưa sẵn sàng không ảnh hưởng huấn luyện/D-1 — `test_ready_production_…`,
`test_v118` D-1 độc lập D-0; (6) D-1 chạy tay được tính — `test_v121_d0::test_training_follows_a_successful_d1_…` +
production (`D1_TODAY_SUCCEEDED`); (7) huấn luyện thủ công không bị chặn bởi lịch — `test_ready_production_…`;
(8) dưới ngưỡng vẫn publish kèm cảnh báo — `test_v122` + production; (9) forecast `BIGQUERY` — `test_v122` + record
production; (10) không fallback DEMO — `test_v122`, `v122.test.tsx`, `test_deactivate_keeps_…`, kiểm tra qua link;
(11) D-0 chỉ hôm nay — `test_v121_d0`, `test_v121_d0_real_bq` + snapshot production; (12) D-1 không chứa hôm nay —
D-1 production đến 16/10, hôm nay loại trừ; (13) công tắc lưu bền, không job trùng — `test_v118::test_restart_…`,
`test_v111::test_no_duplicate_job_…`; (14)–(15) proxy + link — kiểm tra thật trên production (mục 8).

## 8. Deploy 1.2.3 và link

* Gói `dist\DemandForecast-1.2.3-win64-portable.zip` SHA-256 39C1DA4ADAB36854C38F497BCCF363482EA106519FF718A13F31BB70598C3410
  (commit 87f6fce, dirty=False). Prechecks `-CheckOnly` OK (20:30).
* Deploy 20:32–20:37 bằng `deploy-upgrade.ps1` với token `UPGRADE-1.2.3`: UPGRADE OK, app pid 24100, schema 3 → 3;
  backup `backup-20261017-203230-manual.zip` (SHA-256 25E71FB86C460159…27386EF) + `backup-20261017-203501-cli.zip`.
* Link: cùng URL; proxy pid 13024 và cloudflared pid 31076 **không đổi**; theo dõi từng giây: 502 từ 20:35:00 đến
  20:36:28 (~87 s), sau đó 200 / 1.2.3. Qua link sau deploy: `forecast_state=OK`, forecast `FCR-20261017123417-FCC0EB`;
  10 lệnh ghi → 405; `/api/system/paths`, `/system/backups`, `/audit`, `/bigquery/status` → 403 (đọc `/api/settings`,
  `/api/scheduler/status` được phép theo allow-list từ 1.2.1, có che đường dẫn); Edge headless 4 trang, 0 lỗi; trang
  Snapshot D0 hiện `SNP-20261017125745-3ABB90` BIGQUERY.
* Sau deploy: fingerprint dữ liệu + settings **giống hệt** trước deploy (audit +1), `data-check` WARN (chỉ meta DEMO
  cũ), rollback `-To 1.2.2 -CheckOnly` OK (không cần khôi phục DB), storage.json 8D79DBDD… không đổi.

## 9. Bảng kết quả

Trạng thái báo cáo: **READY_FOR_PRODUCTION** (đã chạy trên production; còn quyết định của chủ hệ thống ở cuối).

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Nguyên nhân gốc `SOURCE_NOT_READY` | PASS | lưu ánh xạ 17:32:20 (`unit_price` OPTIONAL→REQUIRED) → `production_enabled=false` + mapping hash mới; job dừng ở VALIDATING_DATA trước BigQuery; giao diện hiển thị công tắc thay vì trạng thái |
| Hai job ID đã được điều tra | PASS | 3 lần bấm riêng biệt (thêm JOB-…121625-661B96), cùng một nguyên nhân (mục 2) |
| `bigquery.production_enabled` hiện tại | PASS (bật) | `true`; bật bởi lần ghi test ngoài ý muốn 19:49 (mục 6), mọi điều kiện kích hoạt đạt, chủ hệ thống chọn giữ; nút kích hoạt chính thức bị bộ kiểm soát quyền từ chối |
| Mapping và SQL đã được xác nhận | PASS | validation toàn kỳ PASS hash `bc5fcb06327569fb`; D-1 chế độ TABLE; D-0 SQL v3 VALID |
| BigQuery readiness cho huấn luyện | PASS | luồng huấn luyện `ON`, `ready=True`, `manual_ready=True` |
| D-1 manual run và scheduler | PASS | JOB-20261017125803-0ED367 SUCCEEDED, 0 thay đổi giá trị; lịch D-1 vẫn TẮT (không tự bật) |
| D-0 SQL validation | PASS | v3 VALID trên production; snapshot kiểm soát `SNP-20261017125745-3ABB90` chỉ 17/10 |
| Nút bật/tắt D-0/D-1 | PASS | cả hai luồng `ready=True` → nút bật dùng được; backend vẫn kiểm tra readiness; trạng thái hiệu lực hiển thị đúng (1.2.3); chưa bật (quyết định của chủ hệ thống) |
| Model đã publish | PASS | TRN-20261017101340-EEDA47 → ACCEPTED, `MV-20261017-172653-DA47`, không huấn luyện lại |
| Forecast BigQuery đã tạo | PASS | `FCR-20261017123417-FCC0EB`, BIGQUERY, 17.125 chuỗi, 17/10–31/10, 7 ngày 624.167,85 |
| Dashboard hiển thị forecast BigQuery | PASS | qua link: Tổng quan + Kết quả dự báo mặc định BIGQUERY; DEMO chỉ còn là "nguồn khác" |
| Chất lượng model được cảnh báo đúng | PASS | "Được dùng — kèm cảnh báo · Dưới ngưỡng · WAPE 80,7 % / 60 %"; ngưỡng không đổi; LightGBM 0,807 < baseline 0,844 |
| Link Cloudflare cũ còn hoạt động | PASS | cùng URL, 1.2.3; ~87 s 502 khi restart |
| Readonly proxy còn nguyên | PASS | pid 13024 không đổi; 405 / 403 |
| Dữ liệu cũ được bảo toàn | PASS | `demand_daily` giống hệt; 4 forecast DEMO, model, snapshot, job cũ giữ nguyên; data-check WARN cũ |
| Phiên bản production thực tế | PASS | 1.2.3 (`current.txt`, `/api/health` nội bộ + qua link), pid 24100 |
| Việc còn bị chặn bởi quyền người dùng | BLOCKED (2 thao tác) | kích hoạt production chính thức (19:33) và hoàn nguyên sự cố (19:5x) bị từ chối; kết quả cuối cùng đã do chủ hệ thống quyết định |

Việc còn lại cho chủ hệ thống (không phải lỗi):
1. Quyết định bật lịch **D-1** (03:00, fallback 06:00) — khi bật, huấn luyện 09:00 sẽ theo D-1 mỗi ngày (missed-run SKIP).
2. Quyết định bật lịch **D-0** (08:00–18:00, 2 giờ/lần) — SQL và lượt chạy kiểm soát đã đạt.
3. Push commit 7053999, 2ea4085, 87f6fce, aaecb52 khi đồng ý.
4. (Tùy chọn) Nếu muốn có bản ghi kích hoạt chính thức trong audit: trang Ánh xạ trường lưu lại không đổi → Kiểm tra
   dữ liệu toàn kỳ → Kích hoạt chế độ sản xuất (không bắt buộc; trạng thái hiện tại đã đầy đủ điều kiện).
