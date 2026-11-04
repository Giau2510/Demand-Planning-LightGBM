# Demand Forecasting 1.2.7: review cuối và release candidate (bản sửa tốc độ trang Tổng quan)

**Kết luận: `READY FOR REVIEW`.**

Trong lượt này đã làm xong:
- review diff;
- QA hai lượt trên đúng mã release, cả hai đạt;
- nâng version 1.2.7 đồng bộ;
- **một** commit local `ad9505c`;
- gói release candidate có SHA-256 đã kiểm;
- diễn tập nâng cấp và rollback cách ly: **38/38 PASS**.

**Production vẫn là 1.2.6** và chưa được triển khai. Chưa push. Chưa chạy training hay pipeline nào.

Bản này **chưa** phải `READY FOR PRODUCTION`. Còn cần:
- anh/chị review release candidate;
- chọn một khung giờ deploy và phê duyệt riêng việc deploy;
- phê duyệt push riêng, nếu muốn.

Thời gian lượt này: 12:04–14:10 ngày 19/10/2026, giờ VN (UTC+07:00).

Lượt trước của báo cáo này (10:35–11:05) ở cuối file, phần "Phụ lục", và được giữ nguyên.

Quy ước trong các bảng:

| Ký hiệu | Nghĩa |
|---|---|
| `PASS` | Có bằng chứng thực tế đạt |
| `FAIL` | Có bằng chứng thực tế không đạt |
| `BLOCKED` | Chưa xác minh được vì thiếu điều kiện |
| `NOT RUN` | Chưa thực hiện |
| `NOT CONFIGURED` | Tính năng hoặc công cụ chưa được cấu hình |

## A. Summary

| Hạng mục | Giá trị |
|---|---|
| Kết quả | **`READY FOR REVIEW`**: mọi tiêu chí kết thúc đều đạt (bảng cuối mục này) |
| Version trong source | **1.2.7**: `backend/app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json` (2 chỗ) |
| Production | **1.2.6**, không đổi: pid 13820, `current.txt` = 1.2.6, `/api/health` = 1.2.6 (kiểm lần cuối ở mục H) |
| Release candidate | `dist\DemandForecast-1.2.7-win64-portable.zip`: 92.253.195 byte, SHA-256 **`1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B`**, commit `ad9505c`, `dirty=false` |
| Commit local | `ad9505c9275a6b39b44d5614e981baed33c019e9` "Release 1.2.7: optimize dashboard status loading", 10 file. Chưa push |
| Diễn tập 1.2.6 → 1.2.7 → 1.2.6 | **38/38 PASS** trên bản sao DB cách ly |

**Kết quả diễn tập:**
- Không có migration.
- Mọi bảng nghiệp vụ, thiết lập, model và lịch giống hệt; chỉ `audit_log` thêm 1 dòng (`BACKUP_CREATED` của backup trước nâng cấp).
- `/api/system/status` của **gói chính thức** trên cùng bản sao giảm từ **32,5 / 36,0 s** (1.2.6) xuống **4,2 / 4,3 s** (1.2.7), và cho **cùng giá trị**.
- Rollback không cần restore, mất 9,7 s.

**Tiêu chí kết thúc (prompt, mục 12):**

| Tiêu chí | Trạng thái |
|---|---|
| Diff đã được review | PASS (mục B) |
| Test và build đạt | PASS, hai lượt (mục C) |
| Version 1.2.7 đồng bộ | PASS (mục B.6 và G) |
| Commit local thành công | PASS, `ad9505c` (mục F) |
| Release candidate tồn tại, SHA-256 đã xác minh | PASS (mục G) |
| Không có thao tác production trái phép | PASS (mục H) |
| Blocker còn lại được ghi rõ | PASS (mục I và J) |

## B. Review

### B.1 Trạng thái ban đầu (12:04, trước khi sửa file nào)

| Hạng mục | Thực tế | So với baseline |
|---|---|---|
| Repository | `D:/Buymed/Lightgbm AI`, nhánh `main` | khớp |
| HEAD | `bd52203cf2bf8a06926fcd9ea5d5249819d728cf` | khớp |
| Ahead / behind | 24 / 0 so với `origin/main` `72d7671`, ref local có sẵn, **không fetch** | khớp |
| Working tree | 5 file sửa (`CHANGELOG.md`, `ops_routes.py`, `test_v121_remote_proxy.py`, `App.tsx`, `Dashboard.tsx`) và 2 file mới (`test_v126_status_perf.py`, `v126dash.test.tsx`). Không có file nào khác | khớp 7 file |
| Nội dung 7 file | Hash diff tracked `341CCA1674204209`, **trùng** hash lúc đầu và cuối lượt QA đã review (10:39–10:52). Mọi file sửa lần cuối lúc 09:49–10:37, tức trước lượt QA đó | không bị ghi đè |
| Version | `__init__.py` 1.2.6; `package.json` 1.2.6; `package-lock.json` 1.2.6 (2 chỗ). Các script build và release **đọc** `app.__version__`, không ghi cứng version nào | — |
| Artifact 1.2.6 | `DemandForecast-1.2.6-win64-portable.zip` SHA `0464EEDA…6171`, khớp `.sha256`. Bản `-superseded-20261018-160552` (`BBD73386…`) vẫn còn | khớp |
| Báo cáo trước | `demandforecast_v126_post_deployment_operations.md`, `demandforecast_remote_access_recovery.md`, bản trước của file này | — |

Không có điều kiện dừng nào. Tôi không stash, checkout, restore hay reset.

### B.2 Phân loại diff (cả 10 file đều vào commit)

| File | Loại | Nội dung |
|---|---|---|
| `backend/app/api/ops_routes.py` (CRLF) | Dashboard optimization | Gộp hai câu SQL freshness và window thành **một** lần quét `demand_daily NOT INDEXED WHERE scope_key=:k`. Các số liệu window tính bằng `COUNT/MIN/MAX(CASE WHEN order_date BETWEEN :s AND :e …)` |
| `frontend/src/App.tsx` (CRLF) | Dashboard optimization | Hook status: `refresh()` dùng chung request đang chạy; `reload()` luôn hỏi mới; số thứ tự để câu trả lời cũ không thắng. Context **thêm** `loading` và `error` |
| `frontend/src/pages/Dashboard.tsx` (CRLF) | Dashboard optimization | Không gọi `/api/dashboard` nữa. Dùng status của khung app, cộng `/api/forecast-runs/{id}/summary?horizon=min(h, max)&limit=10`. Mỗi thẻ có loading và lỗi riêng |
| `backend/tests/test_v126_status_perf.py` (mới, LF) | Test | 4 test: giá trị bằng hai câu SQL cũ, scope rỗng, plan `SCAN demand_daily` đọc đúng một lần, thẻ `/summary` bằng hệt `/api/dashboard` |
| `frontend/src/v126dash.test.tsx` (mới, LF) | Test | 7 test về trạng thái loading, lỗi, rỗng và số request |
| `backend/tests/test_v121_remote_proxy.py` (LF) | Test | Câu assert sơ bộ của bộ quét đường dẫn chuyển từ `/api/dashboard` sang `/api/forecast-runs/X1/summary`. **Không nới lỏng:** test vẫn bắt mọi đường đọc của các trang phải qua được proxy; allowlist proxy không đổi |
| `backend/app/__init__.py` | Version / release metadata | `1.2.6` → `1.2.7` |
| `frontend/package.json`, `frontend/package-lock.json` | Version / release metadata | `1.2.6` → `1.2.7`, chỉ trường version của gói (2 chỗ trong lock). Không đổi dependency |
| `CHANGELOG.md` | Version / release metadata | Mục "Unreleased" thành `## 1.2.7 - 2026-10-19`, thêm "không migration" và số benchmark cùng phiên |

- **Không liên quan:** không có.
- **Giữ ngoài release:** không có. Sau commit, working tree sạch.

### B.3 Backend: tối ưu system status

| Yêu cầu | Kết quả và bằng chứng |
|---|---|
| Không còn tra lại cho từng dòng (khoảng 1,35 triệu dòng) | PASS. Test `test_the_status_reads_demand_daily_once_and_never_row_by_row`: đọc `demand_daily` đúng **một** lần, plan `["SCAN demand_daily"]`. Trên mã gốc test này thất bại (`SEARCH … USING INDEX`) |
| Không đổi kết quả nghiệp vụ; không bỏ sót SKU, FC, key hay series | PASS. Test so với **hai câu SQL cũ**: scope khác có `loaded_at` mới hơn; `loaded_at` lớn nhất nằm giữa thứ tự khóa; có dòng trước và sau window. Scope rỗng vẫn cho `NULL` / `0`. Diễn tập trên gói chính thức: toàn bộ khối status mà trang hiển thị giống hệt giữa 1.2.6 và 1.2.7 (`rows` 1.355.000, `window_rows` 1.355.000, ngày mới nhất 18/10) |
| Không đổi cách tính trạng thái, dữ liệu thiếu hay hợp lệ | PASS. `lag_days`, `stale` và `stale_enforced` vẫn tính từ `max_date` như cũ |
| Không có truy vấn đắt mới | PASS, kèm một đánh đổi (bên dưới) |
| Không đổi schema, migration hay hợp đồng API công khai | PASS. Không có file migration nào; JSON của `/api/system/status` giữ đúng các khóa; `/api/dashboard` vẫn giữ cho các nơi gọi khác |

**Đánh đổi của bản sửa:** câu mới **cố ý** quét tuần tự toàn bảng `demand_daily` bằng `NOT INDEXED`. Nó thay cho 1,5 triệu lần đọc ngẫu nhiên qua index.
- Chi phí tăng theo **tổng số dòng của bảng**, kể cả các scope khác, chứ không chỉ scope đang dùng.
- Trên bản sao, scope BigQuery đang dùng chiếm 97,2% số dòng (1.352.355 / 1.390.923), nên phần đọc thêm khoảng 2,8%.
- Câu mới chỉ chậm hơn câu cũ khi tổng số dòng lớn gấp khoảng **28 lần** scope đang dùng. Cách tính: cũ khoảng 1,12 lần đọc mỗi dòng của scope; mới khoảng 0,04 lần đọc mỗi dòng của bảng.
- Cách tốt hơn là thêm index phủ `(scope_key, loaded_at)`, nhưng việc đó cần thay đổi schema. Tôi để thành đề xuất riêng.

### B.4 Frontend

| Yêu cầu | Kết quả |
|---|---|
| Status không bị tính hoặc tải trùng | PASS. Test "asks the status once": khung app và trang dùng chung một request. Benchmark: số lần tính status mỗi lần mở trang 2 → 1 |
| Nội dung chính hiện trước khi mọi thẻ tải xong | PASS. Test "shows the status parts before the forecast summary arrives" |
| Mỗi thẻ có loading và lỗi đúng | PASS. Lỗi `/summary` chỉ hiện trong thẻ forecast; lỗi status hiện ở khung app, các thẻ ghi "Chưa có" |
| Không có số 0 giả khi chưa có dữ liệu | PASS. Các thẻ chỉ dựng số khi status đã về (`!s ? waiting`) |
| Không hiện "Cần cấu hình" khi đang tải hoặc lỗi | PASS. Test "while the status is slow…"; `NEEDS_CONFIG` chỉ hiện khi status **đã tải** và thật sự không có scope |
| "Chưa có" chỉ hiện khi request đã dừng | PASS. `waiting` = "Chưa có" chỉ khi `statusReady && !sys.loading` và không có status (tức request đã kết thúc bằng lỗi); ngược lại hiện loading |
| Race condition hoặc request trùng của bản sửa | PASS. Status có số thứ tự, câu trả lời cũ không ghi đè câu mới. `/summary` hỏi đúng một lần khi status và settings đã về (test). Thẻ forecast chỉ dùng dữ liệu của đúng run đang hiển thị (`fc.data.run_id === run.id`) |
| Race có sẵn, **không phải hồi quy** | Khi đổi horizon liên tục nhanh hơn thời gian trả lời của `/summary`, câu trả lời của horizon trước có thể về sau. `useAsync` dùng chung không có số thứ tự. **1.2.6 có y hệt** với `/api/dashboard?horizon=`. Hậu quả nhỏ: thẻ vẫn ghi đúng horizon của số đang hiện (`f.horizon`), chỉ ô chọn có thể lệch. Đề xuất sửa riêng: thêm số thứ tự vào `useAsync`; không đưa vào release này để giữ đúng phạm vi đã review |

### B.5 Regression: những phần không đổi

Lệnh `git diff --stat HEAD` trên `scripts/`, `backend/app/migrations/`, `backend/app/settings_service.py`, `backend/app/jobs/`, `backend/app/ml/` và `scripts/remote/` **không có dòng nào**. Như vậy không đổi:
- lịch D-0, D-1 và huấn luyện;
- backup forecast cuối ngày và chốt actual;
- logic forecast, feature Price, quality gate;
- lưu giữ 90 ngày;
- proxy chỉ đọc;
- cấu hình lưu trữ.

Diễn tập xác nhận thêm trên gói chính thức:
- kế hoạch scheduler của 1.2.7 trùng hệt 1.2.6 ở 7 mốc giờ (15 hành động);
- 5 lịch giữ nguyên công tắc và giờ;
- JSON thiết lập schedule, bigquery, model, general, quality và data_policy giống hệt;
- trigger và file model giống hệt.

**Kết luận:** không có thay đổi hành vi nghiệp vụ hay hợp đồng bảo mật, nên không có lý do dừng trước commit.

### B.6 Thay đổi thêm trong lượt này (sau lượt review trước)

- Nâng version (3 file) và đổi mục CHANGELOG (B.2).
- Nhãn comment "1.2.6 hotfix" → "1.2.7" ở 5 chỗ: `ops_routes.py`, `Dashboard.tsx`, `test_v121_remote_proxy.py`, docstring `test_v126_status_perf.py`, header và `describe` của `v126dash.test.tsx`. Chỉ là comment hoặc tên nhóm test.
- Tên hai file test **giữ nguyên** `v126`, vì các báo cáo và CHANGELOG đã dẫn tới tên này.
- Ký tự xuống dòng của mọi file giữ nguyên: CRLF ở `ops_routes.py`, `App.tsx`, `Dashboard.tsx`; LF ở các file còn lại.
- `docs/CHECKPOINT.md` **không** sửa. Prompt yêu cầu một commit, và ở các bản trước dòng checkpoint (ghi SHA gói) luôn là commit docs riêng **sau** khi build. Việc này chờ phê duyệt (mục I).

## C. Test

| # | Lệnh | Thời gian | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `powershell -File scripts\run-tests.ps1`, trên working tree đã nâng 1.2.7, **trước** commit. Hash cây `b4cee28accf8cd08` lúc bắt đầu và kết thúc trùng nhau | 12:10:40–12:20:21 | **0** | `backend=0 typecheck=0 frontend=0 build=0`. Backend **497 passed, 7 skipped** (496 s). Vitest **19 file, 123/123**. Build `index-C7oYoyas.js`. Log `logs\development\tests_20261019_121041.log` |
| 2 | `scripts\release.ps1`, chạy lại chính `run-tests.ps1` trên commit `ad9505c` (cây sạch) | 13:10:36–13:30:38 | **0** | Backend **497 passed, 7 skipped** (600 s). Vitest **123/123**. Typecheck và build 0. Log `logs\development\tests_20261019_131037.log`; console tại `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p11\release127.log` |

**Theo loại test:**

| Loại | Kết quả |
|---|---|
| Backend | unit và tích hợp, chạy trên SQLite thật trong thư mục cách ly với dữ liệu DEMO tổng hợp; OAuth và BigQuery giả lập |
| Readonly proxy và bảo mật | `test_v121_remote_proxy.py` PASS (cả hai lượt). Diễn tập kiểm thật qua proxy cục bộ: ghi 405 ×4, admin 403 ×4 |
| Test mới của Tổng quan | `v126dash.test.tsx` 7/7 và `test_v126_status_perf.py` 4/4 PASS. Cả 11 test này đều thất bại trên mã gốc (kiểm ở lượt trước) |
| So status trước và sau | Test so với hai câu SQL cũ (fixture tổng hợp). Thêm bằng chứng trên **bản sao DB production với hai gói chính thức**: khối status giống hệt (mục G) |
| **Skipped** | 7 test BigQuery thật: `test_bq_real_semantics.py` (2) và `test_v121_d0_real_bq.py` (5), lý do `set DF_REAL_BQ=1`. Không chạy vì bản sửa không đụng BigQuery và không được gọi dịch vụ thật |
| Lint | **NOT CONFIGURED** |

**Cảnh báo (không ảnh hưởng release):**
- pytest: 1 `StarletteDeprecationWarning` của test client (dependency dev).
- Vitest in ra stderr cảnh báo "React Router Future Flag" và một cảnh báo `InLang` cũ trong `v112.test.tsx`.
- PowerShell bọc dòng stderr đầu tiên thành `NativeCommandError`. Đây không phải lỗi; lần release 1.2.6 có y hệt (3 `InLang`, 36 so với 38 cảnh báo Router; 2 cảnh báo thêm đến từ test mới có dựng router).

## D. Performance

**1. Benchmark trang (lượt trước, 10:57–11:03, đo liền nhau):**
- Bản sao DB production lúc 08:46 (SQLite backup API, nguồn mở `mode=ro`).
- Backend chạy từ mã nguồn trên cổng 8893, cách ly, `DF_DISABLE_SCHEDULER=1`.
- Edge headless qua CDP, tắt cache, mỗi lần đo một tab mới.
- Máy production: i5-1335U, 16 GB RAM.

| Chỉ số | Trước | Sau | Thay đổi |
|---|---|---|---|
| Nội dung chính (trung vị, 5 lần) | 60.593 ms | 3.537 ms | −94,2% |
| Hoàn tất toàn trang | 60.593 ms | 5.259 ms | −91,3% |
| CPU server mỗi lần mở trang | 81,7–84,9 s | 5,2–5,5 s | −93,6% |
| Số lần đọc mỗi lần mở trang | 3.095.850 (12,1 GB) | 107.554 (0,42 GB) | −96,5% |
| RAM | 153–162 MB | 153–159 MB | ≈ |

**2. Mới trong lượt này, gói chính thức (diễn tập 13:32–13:56):**
- Bản sao DB production lúc 13:32.
- Bản cài cách ly, cổng 8879, scheduler tắt.
- Production chạy song song trên cùng máy.

| Bản | `/api/system/status`, lần 1 / lần 2 |
|---|---|
| 1.2.6 trước nâng cấp | **32,5 s / 36,0 s** |
| 1.2.7 | **4,2 s / 4,3 s** |
| 1.2.6 sau rollback | 32 s |

Cả ba lần cho **cùng giá trị**.

**Cache nóng và lạnh:**
- Các lần đo lặp là "nóng", vì file DB nằm trong cache của hệ điều hành.
- Lần mở đầu tiên sau khi khởi động server vẫn mất khoảng 20 s trên bản sao. Đó là một lần quét `demand_daily` (225 MB) cộng phần `forecast_values`.
- Không đo được cache lạnh thật, vì không thể xả cache file của Windows mà không ảnh hưởng production.
- Số lần đọc không phụ thuộc cache, nên là chỉ số so sánh đáng tin nhất.

**Giới hạn khi suy rộng sang production:**
- Bản sửa chưa chạy trên production. Production 1.2.6 đo lúc 10:53 mất 32,9 s với 1.521.324 lần đọc, khớp chi phí câu SQL cũ trên bản sao.
- Thời gian thật sau deploy còn phụ thuộc tải máy, lượng RAM trống (1,6–1,9 GB), proxy và tunnel (Cloudflare cắt request ở 100 s).
- Ước lượng hợp lý: status khoảng 3–5 s khi cache nóng, khoảng 20 s ở lần đầu sau khi khởi động. Cần đo lại một lần sau deploy (mục I, bước 9).

## E. Training readiness (chỉ đọc; **lượt này không tạo job training nào**)

Kiểm tra bằng GET tới `127.0.0.1:8765` lúc 12:06 và 13:57; script `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p10\train_readiness.ps1`. Tôi cố ý **không** gọi `/api/data-quality`, vì endpoint đó tự tạo và lưu một báo cáo khi chưa có.

| Điều kiện | Thực tế | Trạng thái |
|---|---|---|
| D-1 hôm nay | `JOB-20261019033144-51D4BD` (MANUAL) SUCCEEDED lúc 10:35, dữ liệu tới 18/10 | ĐẠT |
| Readiness của chính app (`/api/schedules/train`) | `ready: true`, không có lý do chặn; ghi chú `D1_TODAY_SUCCEEDED` | ĐẠT |
| Chất lượng dữ liệu đầu vào | `DQ-20261019043032-E006DA` (11:30), `can_train = 1`; do chính job training tạo | ĐẠT |
| Job đang chạy | Không có job PENDING, RUNNING hay RETRY_WAIT (12:06, 13:32, 13:57) | ĐẠT |
| Lịch | `train_enabled` ON, 09:00, chính sách bù `SKIP`. Slot 09:00 hôm nay: `SKIPPED MISSED_SLOT_NO_BACKFILL`. Lần kế tiếp **20/10 09:00**, cần D-1 thành công trước giờ đó | không đổi |
| Quality gate (thiết lập hiện tại, **không đổi**) | `wape_max` 0,60; `abs_bias_max` 0,20; `min_backtest_points` 200; `require_beat_baseline` false; `approved_by_business` **false** (ngưỡng là giá trị ví dụ); `below_threshold_policy` `PUBLISH_WITH_WARNING` | — |
| Feature model, gồm Price | `feature_price` true, `feature_promotion` true; không đổi | không đổi |

**Diễn biến hôm nay, do người vận hành làm, không phải lượt này:**
1. **11:20:25:** chạy training thủ công `JOB-20261019042025-496B0D`, SUCCEEDED lúc 12:00:22. Candidate `TRN-20261019043033-A761C1` (`MV-20261019-120018-61C1`), dữ liệu 01/01–18/10, 17.132 series:
   - WAPE **0,799**: **FAIL** `WAPE_MAX` (> 0,60);
   - bias 0,050: đạt;
   - tốt hơn model cũ (WAPE 0,810) và baseline (0,843);
   - kết luận của hệ thống `PROMOTION_REVIEW_REQUIRED`: **không** tự promote.
2. **13:05:36:** **promote thủ công** (audit 164 `MODEL_PROMOTED`), rồi publish `FCR-20261019060524-9DE420` (audit 163 và 165 `FORECAST_PUBLISHED_WITH_WARNING`, origin 19/10, horizon tối đa 15, khớp horizons đang bật 7 và 15).
   - Promote là thao tác POST cục bộ; proxy chặn mọi POST.
   - Lúc đó phiên này không gửi lệnh nào: QA kết thúc lúc 12:20, lệnh kế tiếp là commit lúc 13:10.

**Phân loại:**
- Điều kiện đầu vào **ELIGIBLE**: mọi điều kiện xác minh được đều đạt.
- Chất lượng candidate **BELOW_THRESHOLD**: gate FAIL `WAPE_MAX`; ngưỡng vẫn là ví dụ, chưa được nghiệp vụ duyệt.
- Training hôm nay **đã chạy và đã được promote bởi người vận hành**, nên không cần chạy thêm.
- Lượt này không chạy training, không đổi quality gate, không đổi chính sách `SKIP` và không promote.

## F. Git

| Hạng mục | Giá trị |
|---|---|
| HEAD ban đầu | `bd52203cf2bf8a06926fcd9ea5d5249819d728cf` |
| Commit mới | **`ad9505c9275a6b39b44d5614e981baed33c019e9`**, tác giả Giau Vo, 13:10:22 +07:00, cha là `bd52203` (không amend, không viết lại lịch sử) |
| Message | `Release 1.2.7: optimize dashboard status loading`, kèm mô tả và dòng `Co-Authored-By` |
| File trong commit (10) | `CHANGELOG.md`, `backend/app/__init__.py`, `backend/app/api/ops_routes.py`, `backend/tests/test_v121_remote_proxy.py`, `backend/tests/test_v126_status_perf.py` (mới), `frontend/package-lock.json`, `frontend/package.json`, `frontend/src/App.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/v126dash.test.tsx` (mới). 388 dòng thêm, 54 dòng xóa |
| Cách stage | `git add --` từng đường dẫn, không dùng `git add -A` hay `git add .`. Quét file cấm và secret theo `docs/GITHUB_WORKFLOW.md` mục 5: **0 kết quả** |
| Thay đổi còn lại | **Không có.** `git status --short` rỗng sau commit, sau release và sau diễn tập |
| Ahead / behind | **25 / 0** so với `origin/main` `72d7671` (ref local, không fetch) |
| Push / fetch / pull | **Không** |

## G. Release candidate

| Hạng mục | Giá trị |
|---|---|
| Đường dẫn | `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.7-win64-portable.zip`, cùng `.zip.sha256` và `.manifest.json` |
| Kích thước | 92.253.195 byte (88 MB); bản 1.2.6 là 92.248.384 byte |
| SHA-256 | `1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B`. Kiểm độc lập: `Get-FileHash` = file `.sha256` = `zip_sha256` trong manifest |
| Version và nguồn | `VERSION` 1.2.7. `BUILD-INFO.json`: commit `ad9505c…`, `dirty=false`, source fingerprint `15990653C86D9DD1…`, Python 3.14.7, build lúc 13:22:45. Runtime nhúng chạy được: `embedded runtime OK, app 1.2.7 lightgbm 4.7.0` |
| Nội dung | 7.158 entry, 7.136 file. Script `scratchpad\p11\pkgcheck127.py` cho kết quả: |
| | • `testzip` sạch; |
| | • **118/118** file có trong Git **giống hệt từng byte** blob của `ad9505c`; |
| | • 0 file `backend/app` hay script nằm ngoài Git; 0 file Git bị thiếu; |
| | • `web/` 3/3 file giống hệt `frontend/dist` của QA; |
| | • bundle `index-C7oYoyas.js` gọi `/summary?horizon=` và **không** gọi `/api/dashboard`; |
| | • **0 file cấm**: không DB, `storage.json`, credential, `.env`, log, backup, model hay `__pycache__` |
| Không ghi đè lịch sử | Gói 1.2.6 (`0464EEDA…`), bản `1.2.6-superseded` (`BBD73386…`) và 1.2.5 (`F502042C…`) còn nguyên, hash giống trước và sau. `dist\` từ 41 lên 44 file (3 file 1.2.7). Kế hoạch dọn của `prune-artifacts` chỉ là **dry run**, không xóa gì |

**Diễn tập nâng cấp và rollback: 38/38 PASS** (13:32:07–13:56:31).
- Script: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p11\iso127r.ps1`.
- Kết quả: `…\scratchpad\p11\iso127r_result.json`; console: `…\scratchpad\p11\iso127r_console.txt`; môi trường: `…\scratchpad\r7`.
- Chạy trực tiếp bằng PowerShell, **không** dùng Windows task.

**Cách ly:**
- `LOCALAPPDATA`, `DF_DATA_DIR`, logs, backups, reports và `DF_STORAGE_CONFIG` đều nằm trong `scratchpad\r7`.
- Cổng 8879, `DF_DISABLE_SCHEDULER=1`.
- Proxy cục bộ 8878 chạy đúng file proxy của production; không có tunnel.

**Tự dừng nếu:**
- `data_dir` nằm ngoài `r7`;
- file runtime không ghi cổng 8879 (nếu thiếu, `deploy-upgrade` mặc định gọi 8765, tức production);
- scheduler đang chạy;
- có task "DemandForecast";
- production đang có job.

Mọi probe ghi chỉ tới đường dẫn không tồn tại của proxy diễn tập. **Không có job nào được chạy**: không training, D-1, D-0 hay lịch cuối ngày, và không gọi BigQuery.

| Bước | Kết quả |
|---|---|
| Bản sao | Backup API, nguồn mở `mode=ro`, 2,5 s. Schema 6, 7 forecast run, data-check `WARN` (có sẵn trên production) |
| 1.2.6 chính thức cài cách ly | `install.ps1 -NoShortcuts -NoStart`, rồi `start.ps1 -NoBrowser`. Data trong `r7`, scheduler tắt |
| Trước nâng cấp | BIGQUERY, forecast `FCR-20261019060524-9DE420`. Lịch: d1 03:00 / dự phòng 05:00; d0 08–18 mỗi 2 giờ, `LATEST_ONCE`; train 09:00 `SKIP`; eod 23:55 và close 23:59, Asia/Ho_Chi_Minh, đều ON |
| `deploy-upgrade -CheckOnly` | exit 0, không bảng nào đổi |
| `deploy-upgrade -ConfirmToken UPGRADE-1.2.7 -NoShortcuts` | exit 0, tổng **577 s**. Backup online `backup-20261019-134135-manual.zip` (SHA `578F35DE…A90D`) lấy **trước** bước xác nhận; `install.ps1` tạo thêm backup `cli`. Không có backup `pre-migration`, vì không có migration |
| Gián đoạn (proxy cục bộ, đo mỗi giây) | **183,8 s** (13:48:01 → 13:51:05), 61 lần 502, rồi 200 trên 1.2.7. Proxy giữ nguyên pid |
| Sau nâng cấp: dữ liệu | Schema 6; `schema_migrations` và trigger giống hệt. **Mọi bảng giống hệt**, trừ `audit_log` 166 → 167 (`BACKUP_CREATED`). Model và 6 JSON thiết lập giống hệt. data-check vẫn `WARN` |
| Sau nâng cấp: lịch | 5 lịch giữ nguyên công tắc và giờ; kế hoạch scheduler 1.2.7 = 1.2.6 |
| Status trước và sau | Giá trị **giống hệt**; 32,5 / 36,0 s → 4,2 / 4,3 s |
| Qua proxy | Health 1.2.7; status 200; `/summary` 200; ghi 405 ×4; admin 403 ×4; trang `/` có banner chỉ đọc và đúng bundle 1.2.7 |
| `rollback-version -To 1.2.6 -CheckOnly` | exit 0: "database schema 6; 1.2.6 supports up to 6", rollback được **không cần restore** |
| `rollback-version -To 1.2.6 -ConfirmToken ROLLBACK-1.2.6 -NoShortcuts` | exit 0, **9,7 s**; gián đoạn **3,1 s**. `current.txt` 1.2.6, chạy trên **cùng DB** |
| Sau rollback | **Mọi bảng giống hệt** trạng thái trên 1.2.7: không mất dữ liệu ghi sau nâng cấp. Thiết lập, model và lịch như trước nâng cấp. Status giống hệt (32 s); data-check `WARN` |
| Dọn dẹp | Chỉ dừng proxy 8878 (khớp command line) và app 8879. Production sống, vẫn 1.2.6. Hash hai gói không đổi |

**Lưu ý:** bước `install.ps1` trong `deploy-upgrade` tự gọi `start.ps1`, nên đã mở **một tab trình duyệt** tới `http://127.0.0.1:8879` (app diễn tập, nay đã dừng). Tab đó có thể đóng. Khi deploy thật, tab mở tới 8765, đúng như các lần deploy trước.

## H. Production safety (kiểm lần cuối lúc 14:00:40)

| Xác nhận | Trạng thái |
|---|---|
| Không deploy production | ĐÚNG: production vẫn 1.2.6, pid 13820 (khởi động 18/10 19:15:46) |
| Không rollback hay restart production | ĐÚNG: pid app, proxy và cloudflared không đổi |
| Không push, fetch hay pull | ĐÚNG |
| Không chạy training | ĐÚNG. Job training và promote hôm nay là của người vận hành (mục E) |
| Không xử lý lại D-1 | ĐÚNG. Không đọc log D-1, không chạy D-1 |
| Không chạy D-0 để thử | ĐÚNG. Slot 14:00 do scheduler production chạy như thường |
| Không sửa lịch hay dữ liệu production | ĐÚNG. Với production chỉ có GET; bản sao DB mở `mode=ro`. `storage.json` không đổi |
| Không tạo hay chạy deployment task | ĐÚNG. Không có task "Demand…" trước và sau |
| Không đổi Cloudflare Tunnel, proxy, cổng, firewall hay auth | ĐÚNG |
| Không xóa artifact, backup hay log | ĐÚNG. Prune chỉ dry run; backup production không đổi |

**Kiểm tra cuối (14:00:40, chỉ đọc):**

| Hạng mục | Kết quả |
|---|---|
| `/api/health` | 1.2.6 |
| `current.txt` | 1.2.6 |
| `storage.json` (SHA 16 ký tự) | `8D79DBDDC960B109`, giống lúc bắt đầu lượt |
| Tiến trình | app 13820 (18/10 19:15:46), proxy 26416 (18/10 10:09:03), cloudflared 18992 (19/10 10:36:39), đều không đổi |
| Cổng đang nghe | chỉ 8765, 8766 và 8767, cả ba trên `127.0.0.1`. Cổng diễn tập 8878 và 8879 đã đóng |
| cloudflared `/ready` | 200 |
| D-0 14:00 | `JOB-20261019070011-3080E6` SCHEDULE SUCCEEDED (14:00:11–14:00:22), audit 167 `D0_SNAPSHOT` |
| Job đang chạy | 0 |
| Audit sau promote của người vận hành | chỉ có dòng D-0 |
| Backup production | 50 zip, mới nhất vẫn `backup-20261018-191344-cli.zip`; không có file mới |
| Task "Demand…" | 0 |

## I. Việc cần anh/chị phê duyệt tiếp

| # | Việc | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | **Review release candidate** | Chờ anh/chị | Diff `git show ad9505c`; gói và SHA ở mục G; diễn tập ở mục G |
| 2 | **Chọn cửa sổ deploy** | Chờ anh/chị | Ngoài các slot lịch: D-0 08:00–18:00 mỗi 2 giờ, training 09:00, cuối ngày 23:55 / 23:59, D-1 từ 03:00 (dự phòng 05:00). Không có job đang chạy. Đề xuất **19:00–22:00**. Diễn tập cho thấy app ngừng phản hồi khoảng **3 phút**, tổng khoảng **10 phút**; trong lúc đó link xem từ xa trả 502 |
| 3 | **Phê duyệt deploy riêng** | Chờ anh/chị | Đường chạy: `scripts\deploy-upgrade.ps1 -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.7-win64-portable.zip" -ExpectedSha256 1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B -CheckOnly`, rồi chạy lại không có `-CheckOnly` và gõ `UPGRADE-1.2.7`. Rollback nếu cần: `scripts\rollback-version.ps1 -To 1.2.6` (không cần restore, khoảng 10 s). Proxy và tunnel **không** cần khởi động lại, vì allowlist đã có `/summary` |
| 4 | Kiểm tra sau deploy | Checklist sẵn | Version 1.2.7 ở `/api/health`, `current.txt` và tiến trình; `storage.json` không đổi; `data-check`; lịch không đổi; proxy 403/405 qua link; đo `/api/system/status` một lần cùng số lần đọc; mở Tổng quan qua link; theo dõi slot D-0 và cuối ngày kế tiếp |
| 5 | **Phê duyệt push riêng** (nếu cần) | Chờ anh/chị | 25 commit (1.2.0 → 1.2.7) chưa push. Theo `docs/GITHUB_WORKFLOW.md`; không force-push |
| 6 | Commit docs checkpoint (tùy chọn) | Chờ anh/chị | Thêm dòng 1.2.7 (SHA gói, diễn tập) vào `docs/CHECKPOINT.md` bằng commit docs riêng, như `bd52203` của 1.2.6. Commit đó nằm sau gói và không làm đổi gói |
| 7 | Sửa riêng (tùy chọn) | Đề xuất | (a) Số thứ tự trong `useAsync` cho race khi đổi horizon (B.4). (b) Index phủ `(scope_key, loaded_at)` để status không phụ thuộc kích thước bảng; cần migration, nên làm batch riêng (B.3) |

## J. Rủi ro còn lại

| Mức | Rủi ro | Xử lý đề xuất |
|---|---|---|
| **High** | Production 1.2.6 vẫn chậm: `/api/system/status` khoảng 33 s (10:53) và 32–36 s trên bản sao. Trang Tổng quan khoảng 60 s | Deploy 1.2.7 khi được duyệt (mục I) |
| **High** | Link xem từ xa là Quick Tunnel: URL tạm thời, không tự khởi động | Xem `reports/demandforecast_remote_access_recovery.md`; Named Tunnel cần quyết định riêng |
| Medium | Lần mở đầu tiên sau khi khởi động hoặc khi cache lạnh vẫn khoảng 20 s | Batch riêng (I.7b) |
| Medium | Model đang dùng (promote 13:05) có WAPE 0,799, cao hơn ngưỡng ví dụ 0,60; ngưỡng chưa được nghiệp vụ duyệt | Quyết định của chủ sở hữu; lượt này không đổi gate |
| Low | Quét toàn bảng tăng theo tổng số dòng mọi scope (B.3) | Theo dõi; index phủ ở I.7b |
| Low | Race có sẵn khi đổi horizon nhanh (B.4) | I.7a |
| Low | 25 commit chưa push | I.5 |
| Low | 7 test BigQuery thật không chạy | Không liên quan bản sửa |

---

## Phụ lục: lượt rà soát trước (10:35–11:05, trước khi nâng version)

Phần dưới giữ nguyên nội dung chính của bản trước (đã được thay bằng các mục A–J ở trên).

### P.1 Lệnh đã chạy (lượt trước)

| Lệnh | Mục đích | Exit / kết quả |
|---|---|---|
| `powershell -File scripts\remote\remote-access.ps1 start` (10:36:32–10:37:47) | Khôi phục tunnel bằng launcher có sẵn | 0 |
| `scratchpad\p9\verify_remote.ps1` (10:38:58) | Kiểm tra độc lập link mới: GET, cùng các probe ghi tới đường dẫn không tồn tại | 0, mọi kiểm tra đạt |
| `scratchpad\p9\prod_review.ps1` (10:41:45) | Rà soát production chỉ đọc (GET, hash file) | 0 |
| `GET http://127.0.0.1:8765/api/system/status`, **một lần** (10:53:38) | Thời gian phản hồi trên production | 200, 32.898 ms |
| `powershell -File scripts\run-tests.ps1` (10:39:35–10:52:11) | QA một lượt trên mã chưa commit | **0**: backend 497 passed / 7 skipped; vitest 123/123; log `tests_20261019_103936.log` |
| `p8\bench_app.ps1`, `p8\page_bench.mjs` (5 lần), `p9\io_page2.ps1` (2 lần) | Benchmark C2 (sau), rồi A3 (trước) | 0 |

### P.2 Benchmark chi tiết (bản sao DB lúc 08:46, cổng 8893, đo liền nhau 10:57–11:03)

| Chỉ số | A3: trước | C2: sau | Thay đổi |
|---|---|---|---|
| Khung trang (trung vị) | 396 ms | 413 ms | ≈ |
| Nội dung chính (trung vị, 5 lần) | 60.593 ms (54.629–64.846) | 3.537 ms (3.133–20.302) | −94,2% |
| Hoàn tất toàn trang (trung vị) | 60.593 ms | 5.259 ms (5.022–22.710) | −91,3% |
| Lần đầu sau khi khởi động server | 57.097 ms | 20.302 / 22.710 ms | −64% |
| `/api/system/status` trong lúc tải trang | 52,9–60,4 s (×2, chạy song song) | 2,7–3,1 s (×1) | |
| Số request API mỗi lần mở trang | 6 | 6 | trước gồm `/api/dashboard`, sau gồm `/summary` |
| Số lần tính status mỗi lần mở trang | 2 | 1 | |
| Số lần đọc của server mỗi lần mở trang | 3.095.850 (12.093,7 MB) | 107.554 (420,7 MB) | −96,5% |
| CPU của server mỗi lần mở trang | 81,7 / 84,9 s | 5,2 / 5,5 s | −93,6% |
| RAM (working set; peak) | 153–154 MB; 161–162 MB | 153 MB; 159 MB | ≈ |

Phiên đo sáng 19/10 (09:45–10:30) trên cùng bản sao: nội dung chính 23,6 s → 1,3 s. Không so chéo số tuyệt đối giữa hai phiên, vì tải máy khác nhau; tỷ lệ cải thiện trong mỗi phiên nhất quán (−94% tới −97%).

### P.3 Production 1.2.6 (chỉ đọc, 10:41–10:53)

| Hạng mục | Bằng chứng | Trạng thái |
|---|---|---|
| App | 1.2.6, pid 13820, cổng 8765, `/api/health` 200. `server.err.log` 0 byte | PASS |
| Proxy | pid 26416, cổng 8766; 403/405 đúng hợp đồng | PASS |
| `/api/system/status` | 32,9 s | FAIL (rủi ro mở; bản sửa chưa triển khai) |
| D-1 | Không điều tra lại theo yêu cầu. Job thủ công `JOB-20261019033144-51D4BD` SUCCEEDED lúc 10:35:14 | PASS (chỉ đọc) |
| D-0 08:00 / 10:00 | SUCCEEDED | PASS |
| Huấn luyện 09:00 | `SKIPPED MISSED_SLOT_NO_BACKFILL` lúc 10:35:20, chính sách `SKIP` | NOT RUN (theo chính sách) |
| Backup forecast cuối ngày 23:55 (18/10) | `COMPLETE ALL_7_DAYS`, 119.889 dòng = 17.127 series × 7 ngày | PASS |
| Chốt actual 23:59 (18/10) | revision 1 (D0, tổng 34.026) + **revision 2** `ACL-20261019033514-1FA2BB` (D1, tổng 57.832); `CLOSED_UNVERIFIED` | PASS |
| Actual thiếu không thành 0 | `actual=null`, `NO_ACTUAL FUTURE_DATE` | PASS |
| Timezone | `scheduled_for` +07:00 | PASS |
| Backup | 50 file; SHA của các backup ngày 18/10 khớp; `storage.json` không đổi | PASS |
