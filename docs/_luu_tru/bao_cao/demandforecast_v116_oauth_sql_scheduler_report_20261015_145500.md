# Báo cáo batch 1.1.6: xác thực Google, SQL editor lịch sử/D0, job đồng bộ độc lập

Thời điểm: 15/10/2026, 13:20 – 14:55 (giờ Việt Nam). Máy: LOG-PC, tài khoản Windows `Giau Vo`.

## Kết luận: **BLOCKED**

**Phần đã hoàn thành.** Mọi phần làm được an toàn đã triển khai, kiểm thử và đóng gói, đúng yêu cầu:
- 1.1.6 **chưa** cài đè lên bản đang chạy;
- gói mới đã qua kiểm thử cô lập: cài mới, nâng cấp trên bản sao DB thật, quay về 1.1.5.

**Phần bị chặn** bởi yếu tố bên ngoài:
- **Kiểm chứng BigQuery thật và bật production.** Tài khoản Windows chạy ứng dụng chưa có thông tin xác thực Google, và chưa có OAuth client do quản trị Google Cloud cấp.
- **Chưa có truy vấn nào chạy thành công trên BigQuery.** Không có số liệu thật nào trong báo cáo này.
- Production, đồng bộ và huấn luyện nguồn BIGQUERY **vẫn bị chặn** đúng như thiết kế.

**Mức độ kiểm chứng:**

| Mức | Nội dung |
|---|---|
| Đã triển khai | OAuth trong ứng dụng, chẩn đoán danh tính, SQL editor (lịch sử/D0) có phiên bản, job D-1/D0 độc lập, khóa ứng viên, backfill, giao diện |
| Kiểm thử bằng mock/giả lập | OAuth (endpoint Google giả, callback loopback thật trên máy), BigQuery (fake client), toàn bộ test backend/frontend, E2E trên bản sao DB, kiểm thử gói cô lập |
| Kiểm thử logic SQL trên engine khác | DuckDB (chuyển từ SQL BigQuery) với dữ liệu tổng hợp: SQL D0 của người dùng + phần tổng hợp của ứng dụng, 10/10 |
| Đăng nhập Google thật | **Không** — chưa có OAuth client |
| Truy vấn BigQuery thật | **Không** — không có credentials hợp lệ cho tài khoản `Giau Vo` |

---

## 1. Phiên bản và trạng thái Git

| | Ban đầu | Cuối |
|---|---|---|
| Phiên bản đang chạy | 1.1.5 (pid 17220, `%LOCALAPPDATA%\Programs\DemandForecast\1.1.5`, chủ tiến trình `LOG-PC\Giau Vo`) | **vẫn 1.1.5**, không cài đè |
| Mã nguồn | 1.1.5 | **1.1.6** (`backend/app/__init__.py`, `frontend/package.json`) |
| Git | **Không phải Git repository** (`fatal: not a git repository`) | như cũ; không commit/push |

Vì không có Git, checkpoint mã nguồn được tạo bằng tệp:
- trước khi sửa: `checkpoints\source-1.1.5-before-1.1.6-20261015-133452.zip` (136 file, SHA256 `EC60B664…855BA0`) kèm manifest SHA256 từng file;
- diff cuối: `checkpoints\diff-1.1.5-to-1.1.6.patch` (31 file).

## 2. Nguyên nhân gốc đã xác minh

| Lỗi / vấn đề | Nguyên nhân (bằng chứng) |
|---|---|
| "Máy này chưa có thông tin xác thực Google…" | Tiến trình backend (pid 17220) chạy dưới `LOG-PC\Giau Vo`. `google.auth.default()` tìm ADC tại `C:\Users\Giau Vo\AppData\Roaming\gcloud\application_default_credentials.json`: **không tồn tại**. ADC có trong hồ sơ `C:\Users\Administrator`, nhưng tài khoản `Giau Vo` **không có quyền đọc** hồ sơ đó (kiểm tra trả về "no access"). gcloud không có trên PATH của `Giau Vo`. Biến môi trường của cửa sổ PowerShell Administrator không ảnh hưởng tiến trình chạy dưới tài khoản khác. |
| Thông báo lỗi chung chung về ADC | 1.1.5 chỉ báo "thiếu ADC", không cho biết backend chạy dưới tài khoản nào và tìm file ở đâu. 1.1.6 hiển thị chẩn đoán và phân biệt rõ lỗi đăng nhập / IAM / bảng / location / SQL / chi phí. |
| Job D0_SYNC và TRAIN_PUBLISH **FAILED** `NO_ACTIVE_DATASET` (14/10, 09:19 VN) | Chạy bù khi chưa có dữ liệu DEMO, trên bản 1.0.0. Từ 1.1.x mã này được ghi nhận là *SKIPPED (cần cấu hình)*, có test `test_scheduled_job_without_dataset_is_skipped_not_failed`. Lỗi **không tái hiện**. |
| SQL D0 do người dùng cung cấp | Xem mục 9: có dấu phẩy trước `FROM`, `LEFT JOIN` + `WHERE` trên bảng phải, `DATE(created_at)` không có múi giờ. Chỉ dry-run BigQuery xác định được có lỗi cú pháp hay không; SQL **không** bị sửa. |

## 3. Lỗi đã sửa, không tái hiện, còn tồn tại

**Đã sửa / bổ sung trong 1.1.6:**
1. **Xác thực Google trực tiếp trong ứng dụng** (OAuth 2.0 cho ứng dụng cài đặt), không cần Google Cloud CLI:
   - loopback `127.0.0.1` cổng ngẫu nhiên, `state` 256 bit, PKCE S256, hết hạn 5 phút;
   - refresh token **và** client secret chỉ lưu trong **Windows Credential Manager** của tài khoản đang chạy ứng dụng (DPAPI);
   - có đăng xuất (thu hồi token tại Google + xóa) và đăng nhập lại;
   - phát hiện token hết hạn/bị thu hồi (`BQ_AUTH_EXPIRED`, trạng thái `REVOKED`);
   - luồng ADC cũ giữ nguyên.
2. **Chẩn đoán danh tính:** tài khoản Windows của backend, đường dẫn ADC được tìm (chỉ đường dẫn), `GOOGLE_APPLICATION_CREDENTIALS`, gcloud trên PATH, phương thức đang dùng.
3. **Phân loại lỗi BigQuery bổ sung:**
   - `BQ_SQL_ERROR` (lỗi cú pháp, kèm vị trí);
   - `BQ_SCHEMA_CHANGED` (cột không tồn tại);
   - trạng thái OAuth: `NOT_SIGNED_IN`, `IN_PROGRESS`, `SIGNED_IN`, `CANCELLED`, `BLOCKED`, `ERROR`, `TIMEOUT`, `REVOKED`.
4. **SQL editor riêng cho lịch sử và D0:**
   - mỗi lần lưu tạo phiên bản mới; phiên bản chỉ được dùng sau khi **dry-run BigQuery đạt**;
   - phiên bản lỗi không thay phiên bản đang dùng; khôi phục được phiên bản trước;
   - bộ lọc tĩnh chỉ cho phép một câu `SELECT`/`WITH`;
   - xem trước giới hạn dòng; mỗi job chụp SQL lúc bắt đầu.
5. **SQL D0 của người dùng** được lưu **nguyên văn** làm phiên bản 1, chưa kích hoạt.
6. **Job D0 đọc từ SQL D0** (tổng hợp theo SKU × FC trong truy vấn ngoài):
   - không lọc thêm theo ngày, nhưng báo cáo các ngày xuất hiện trong kết quả;
   - **retry không tạo snapshot thứ hai** (kiểm tra theo `job_id`). Trước đây, một lần chạy D0 hết thời gian rồi được thử lại có thể ghi hai snapshot.
7. **Khóa duy nhất ứng viên** (mặc định lấy từ ánh xạ: đơn + SKU + FC + ngày; sửa được):
   - kiểm tra trùng khóa ngay trong truy vấn;
   - nếu chưa chứng minh được khóa duy nhất thì **chặn ghi** (`BQ_KEY_NOT_UNIQUE`), trừ khi người dùng chọn rõ "Cộng tất cả dòng".
8. **D-1:**
   - báo số dòng SKU×FC×ngày mới / cập nhật / không đổi / bị bỏ;
   - backfill có kiểm soát (trong khoảng đọc, tối đa 400 ngày, không gồm hôm nay, cần đã đồng bộ thường với ánh xạ hiện tại);
   - API/giao diện trạng thái riêng cho từng job: lịch, lần chạy tiếp theo, lần chạy gần nhất, số dòng, phiên bản SQL, retry, lỗi.
9. **Lỗi phát hiện và sửa trong lúc làm:**
   - bộ lọc tĩnh báo nhầm `CURRENT_DATE('Asia/Ho_Chi_Minh')` là "không có múi giờ";
   - `shutdown()` của server loopback có thể treo luồng phụ;
   - khóa mặc định viết cứng tên cột (đổi sang lấy từ ánh xạ).

**Không tái hiện** (đã có code + test chứng minh): xem bảng regression ở mục 5.

**Còn tồn tại / chưa giải quyết được:**
- kiểm chứng BigQuery thật;
- đăng nhập Google thật;
- ý nghĩa nghiệp vụ của SQL D0;
- khóa duy nhất thật của dữ liệu;
- ngưỡng WAPE/Bias chưa được duyệt.

Chi tiết ở mục 13–14.

## 4. File thay đổi và lý do

31 file; diff ở `checkpoints\diff-1.1.5-to-1.1.6.patch`.

| File | Lý do |
|---|---|
| `backend/app/bq/oauth.py` (mới) | Luồng OAuth loopback + PKCE + state, trạng thái, đăng xuất/thu hồi, credentials từ refresh token, chẩn đoán danh tính |
| `backend/app/bq/secret_store.py` (mới) | Windows Credential Manager qua `advapi32` (CredWrite/CredRead/CredDelete), không thêm thư viện |
| `backend/app/bq/sql_guard.py` (mới) | Kiểm tra tĩnh chỉ-đọc, ghi chú các điểm cần dry-run quyết định, lồng SQL thành truy vấn con không sửa nội dung |
| `backend/app/bq/sql_sources.py` (mới) | Phiên bản SQL, kích hoạt chỉ khi đạt, khôi phục, khóa hiệu lực, bản chụp cho job |
| `backend/app/bq/d0_user_sql_20261015.sql` (mới) | SQL D0 nguyên văn của người dùng |
| `backend/app/bq/connector.py` | Credentials OAuth/ADC, nguồn = bảng hoặc SQL người dùng, kiểm tra khóa, đường D0 theo SQL, dry-run lấy kiểu câu lệnh/schema, kiểm tra/xem trước/kiểm tra dữ liệu theo phiên bản, mã lỗi mới |
| `backend/app/sync.py` | Bản chụp SQL, backfill, đếm mới/cập nhật, D0 không ghi trùng khi retry |
| `backend/app/api/bq_routes.py` (mới), `main.py`, `ops_routes.py`, `data_routes.py` | API danh tính/OAuth/SQL/đồng bộ; chặn sửa `sql_sources` và `oauth_enabled` qua API cấu hình chung |
| `backend/app/settings_service.py` | Khóa cấu hình mới ở cấp trên cùng (`oauth_enabled`, `oauth_client_id`) và mục mới `sql_sources`. Bản 1.1.5 bỏ qua cả hai nên vẫn quay về được. |
| `backend/app/jobs/runner.py`, `messages.py` | `SQL_NOT_VALIDATED`/`OAUTH_NOT_CONFIGURED` → *bỏ qua, cần cấu hình*; thông điệp Việt/Anh mới |
| `frontend/src/pages/GoogleAuth.tsx`, `SqlSources.tsx` (mới), `BigQuery.tsx`, `App.tsx`, `i18n.tsx`, `styles.css` | Thẻ xác thực Google, trang *SQL nguồn & đồng bộ* |
| Test | `backend/tests/test_v116.py` (30 test), `frontend/src/v116.test.tsx` (3). `fake_bq.py`, `test_bigquery.py`, `test_v115_bigquery_features.py` cập nhật theo hành vi mới (lỗi cú pháp → `BQ_SQL_ERROR`; D0 mặc định theo SQL; khóa phải được chứng minh). |
| Tài liệu | `docs/BIGQUERY.md` (mục 2, 9, 10, 11), `HUONG-DAN-SU-DUNG.md`, `VAN-HANH.md`, `CHECKPOINT.md` |

Ghi chú: `connector.py`, `sync.py`, `fake_bq.py` được ghi lại với kết thúc dòng CRLF thay vì LF. Python xử lý hai kiểu như nhau; repository vốn đã có cả hai kiểu.

## 5. Kết quả kiểm thử

| Nhóm | PASS | FAIL | SKIP |
|---|---|---|---|
| Backend `pytest` toàn bộ (`logs\development\tests_20261015_135912.log`) | **214** | 0 | 0 |
| — trong đó mới (`test_v116.py`): OAuth và Credential Manager (10, gồm 4 trường hợp hủy/chặn/lỗi), chẩn đoán/ADC (2), SQL D0 nguyên văn và bộ lọc SQL (9, gồm 7 câu lệnh bị từ chối), SQL editor/D0/job/khóa/backfill (9) | 30 | 0 | 0 |
| Frontend `vitest` | **45** | 0 | 0 |
| TypeScript + build | đạt | | |
| Logic SQL D0 trên DuckDB (dữ liệu tổng hợp) | 10 | 0 | |
| E2E trình duyệt trên **bản sao DB thật** (cổng 8879) | **122** | 0 | |
| Gói cô lập — cài mới | 24 + 43 | 0 | |
| Gói cô lập — nâng cấp trên bản sao DB thật | 26 | 0 | |
| Gói cô lập — **quay về 1.1.5** trên cùng dữ liệu, không khôi phục DB | 4 + 7 | 0 | |
| Đăng nhập Google thật / truy vấn BigQuery thật | — | — | **SKIP** (không có OAuth client / credentials) |
| Máy Windows khác | — | — | **SKIP** (không thực hiện; chỉ mô phỏng bằng hồ sơ `LOCALAPPDATA` cô lập) |

**Phạm vi theo nhóm của yêu cầu:**
- **OAuth:**
  - thành công: kiểm tra PKCE (challenge = SHA256(verifier)), `state` ≥ 32 ký tự, không gửi secret trong URL;
  - người dùng hủy (`access_denied`), bị chặn (`admin_policy_enforced`, `org_internal`), lỗi máy chủ;
  - `state` sai (không đổi mã), hết thời gian, lỗi mạng, `invalid_client`;
  - làm mới token thành công và thất bại (`invalid_grant` → `BQ_AUTH_EXPIRED` + `REVOKED`);
  - đăng xuất (thu hồi + xóa);
  - **không lộ bí mật:** refresh token, client secret, access token, mã xác thực không xuất hiện trong DB, `settings_history`, `sync_state`, `audit_log` hay API;
  - ghi/đọc/xóa Credential Manager thật bằng mục thử, đã xóa ngay sau test.
- **BigQuery:**
  - ADC hợp lệ (luồng cũ vẫn chạy), thiếu ADC;
  - lỗi được phân loại: thiếu IAM, không tìm thấy, sai location, lỗi cú pháp, sai schema, vượt chi phí, timeout (đã có từ 1.1.5 và được giữ);
  - dry-run trước mọi truy vấn.
- **SQL editor:**
  - lưu, phiên bản, khôi phục;
  - phiên bản lỗi không thay phiên bản đang dùng;
  - xem trước giới hạn dòng;
  - chặn `DELETE`/`UPDATE`/`DROP`/nhiều câu lệnh/`EXECUTE IMMEDIATE`;
  - job dùng đúng bản chụp SQL dù người dùng kích hoạt phiên bản khác giữa chừng.
- **Scheduler:**
  - D-1 và D0 độc lập (D0 không gọi truy vấn lịch sử);
  - không chạy chồng (đã có `test_lock_prevents_overlap`);
  - retry D0 không ghi trùng;
  - khóa trùng thì chặn ghi;
  - đồng bộ không tạo job huấn luyện;
  - SQL chưa đạt thì job được ghi nhận *bỏ qua* với lý do.

**Regression** (đã có test, tất cả PASS trong lần chạy trên):

| Hạng mục | Bằng chứng |
|---|---|
| `NO_ACTIVE_DATASET` | `test_no_active_dataset_only_in_the_right_conditions`, `test_scheduled_job_without_dataset_is_skipped_not_failed` |
| `IntegrityError` / FOREIGN KEY khi dùng DEMO | `test_first_second_and_many_generations_succeed_with_one_active`, `test_database_rejects_two_active_demo_batches`, `test_failed_generation_rolls_back_and_previous_demo_stays_usable` |
| Lỗi không hiển thị rõ | `test_database_errors_return_stable_code_without_traceback` |
| Silent fallback sang DEMO | `test_failed_bigquery_query_changes_nothing`; 1.1.6: BigQuery/SQL lỗi không đổi nguồn (E2E + kiểm thử gói) |
| Trùng DB / sai đường dẫn / thiếu ổ D: | `test_missing_configured_location_is_an_error_not_a_new_empty_db`, `test_lost_storage_json_is_detected_and_never_creates_empty_db`, `test_configured_d_drive_location_all_files_land_there`, `test_restart_keeps_the_same_database` |
| Đổi phiên bản mất dữ liệu/cấu hình | `test_upgrade_from_v1_database_keeps_data_and_relations`, `test_newer_db_version_is_refused`; kiểm thử gói nâng cấp + quay về 1.1.5 |
| Scheduler chạy trùng / retry | `test_idempotency_key_prevents_duplicate_runs`, `test_lock_prevents_overlap`, `test_retry_exponential_backoff_then_failed_with_alert`, `test_interrupted_jobs_recovered_at_startup` |
| Import Excel và thay lô | `test_replace_batch_only_affects_selected_batch`, `test_invalid_replacement_keeps_old_batch`, `test_reimport_same_file_creates_independent_batch_without_double_counting`, `test_csv_and_bad_files_rejected` (vẫn chỉ nhận .xlsx) |
| Không dùng dữ liệu tương lai | `test_backtest_forecast_unchanged_when_future_changes` |
| Model/forecast cũ được giữ khi model mới không đạt | `test_quality_gate_failure_keeps_previous_forecast`, `test_training_crash_keeps_previous_forecast` |

## 6. Trạng thái OAuth

- **Mới chỉ kiểm thử bằng mock** (endpoint Google giả, callback loopback thật trên máy). **Chưa đăng nhập Google thật**: chưa có OAuth client loại Desktop app.
- Trên bản sao DB và gói cô lập:
  - thẻ *Xác thực Google* hiển thị đúng `Giau Vo` và đường dẫn ADC không tồn tại;
  - nút *Đăng nhập Google* bị khóa kèm hướng dẫn cần OAuth client.
- **Không tạo OAuth client giả và không mượn client của công cụ khác** (ví dụ client của gcloud).

## 7. Trạng thái BigQuery

**BLOCKED — chưa kiểm chứng.**
- Không có credentials hợp lệ cho tài khoản `Giau Vo` và chưa có OAuth client.
- Chưa chạy truy vấn thật nào (kể cả dry-run).
- Trên bản sao DB: *Kiểm tra dữ liệu toàn kỳ* và *Kiểm tra (dry-run)* SQL D0 đều được ghi nhận **Không đạt — `BQ_AUTH_MISSING`**, đúng lý do thật. Chế độ sản xuất vẫn khóa.

## 8. Schema, số dòng, trùng lặp, thiếu dữ liệu, đối chiếu, chi phí dry-run

**Chưa thực hiện được** trên dữ liệu thật (bị chặn ở mục 7).

Các kiểm tra đã sẵn sàng và sẽ chạy khi có quyền:
- schema thật (metadata);
- số dòng và tổng `demand_quantity` theo ngày và toàn kỳ;
- phân bố `order_status`;
- ngày thiếu, FC thiếu ngày;
- trùng hoàn toàn và trùng khóa ứng viên;
- NULL ở cột bắt buộc;
- số lượng/giá âm hoặc bất thường;
- dòng bị loại theo từng lý do;
- ngày xuất hiện trong kết quả D0 (đối chiếu múi giờ);
- đối chiếu số dòng/tổng số lượng giữa nguồn và kết quả chuẩn hóa;
- bytes ước tính của từng truy vấn (dry-run).

## 9. SQL lịch sử/D0 và scheduler độc lập

- **SQL lịch sử:** chế độ mặc định **Bảng** (`gold_buymed_vn2.demand_planing_lightgbm`), không đổi so với 1.1.5. Có thể chuyển sang SQL do người dùng quản lý; SQL này phải dry-run đạt và kiểm tra dữ liệu toàn kỳ đạt lại.
- **SQL D0:** lưu nguyên văn làm phiên bản 1, SHA256 `b9d6d9f56a091d8630b69df623c7ef1a5997a41ee3857dba758383e87a1e3f58`, **chưa kích hoạt**. Job D0 nguồn BIGQUERY được ghi nhận *bỏ qua — SQL_NOT_VALIDATED* cho đến khi dry-run đạt.
- **Các điểm của SQL D0 cần người dùng xác nhận** (không tự sửa):
  1. Có dấu phẩy sau `b.sales_price` ngay trước `FROM` (dòng 12). Chỉ dry-run BigQuery quyết định đây có phải lỗi cú pháp; DuckDB chấp nhận.
  2. `LEFT JOIN … adhoc_pm_master_sku c` kết hợp `WHERE c.seller_code IN ('MEDX') AND c.sku_system_status IN (…)` loại các dòng không có bản ghi master, tương đương `INNER JOIN`. Đã xác nhận bằng DuckDB với dữ liệu tổng hợp.
  3. `DATE(a.created_at) AS created_date` không có múi giờ. Nếu `created_at` là TIMESTAMP thì đây là ngày **UTC**, trong khi lọc theo `b.created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')`. Đơn từ 00:00–07:00 giờ VN sẽ mang ngày hôm trước (đã thấy trên DuckDB). Ứng dụng báo các ngày trong kết quả (`D0_DATES_OTHER_THAN_TODAY`), không lọc thêm.
  4. Nếu `sub_sku_code` lặp trong `adhoc_pm_master_sku` thì join **nhân đôi** nhu cầu. Trên DuckDB, SKU-C ra 8 thay vì 4; kiểm tra khóa phát hiện và **chặn ghi**.
  5. Cần kiểm tra trên dữ liệu thật:
     - `b.created_date` có tồn tại trong `fact_order_item` không;
     - ý nghĩa chính xác của `demand_quantity`;
     - khóa ổn định của một dòng D0 (mặc định đang kiểm tra `so_code` + `sku_code` + `fc_code` + `created_date`; có thể cần thêm `item_code`).
- **Scheduler:**
  - D-1: 1 lần/ngày từ 01:00 (chờ tín hiệu, dự phòng 06:00);
  - D0: 08:00, 10:00, 12:00, 14:00, 16:00, 18:00;
  - múi giờ `Asia/Ho_Chi_Minh`;
  - khóa theo loại job; retry tối đa 4 lần, giãn 60 giây → 30 phút;
  - đồng bộ không kích hoạt huấn luyện.

  Lịch hiện tại không thay đổi.

## 10. Feature registry, backtesting và production gate

- **Feature registry** (từ 1.1.5) không đổi. Trên DEMO: 33 feature đang dùng, 15 dự kiến, 0 bị tự kích hoạt.
- Đổi SQL D0 không làm đổi danh sách feature của lần huấn luyện tiếp theo (`test_d0_sql_does_not_change_features_or_training_data`).
- Dữ liệu D0 nằm trong bảng snapshot riêng, **không** vào dữ liệu huấn luyện.
- **Backtesting:** walk-forward 3 lần × bước 7 ngày × tầm 14 ngày, theo cấu hình hiện tại (khoảng 5 tuần lịch sử đánh giá).
  - Có thể mở rộng lên 6–12 tháng bằng cấu hình (`backtest_folds` tối đa 12, `backtest_step_days` tối đa 90).
  - **Không tự đổi** vì không có lỗi và đây là quyết định nghiệp vụ.
  - Chất lượng theo từng điểm/ngày có trong Excel "điểm backtest"; giao diện chưa có bảng tổng hợp theo ngày.
- **Production gate:**
  - huấn luyện/đồng bộ BIGQUERY cần chế độ sản xuất và kết quả *kiểm tra dữ liệu toàn kỳ* đạt cho ánh xạ hiện tại;
  - với SQL lịch sử: thêm điều kiện phiên bản SQL đã dry-run đạt;
  - model mới chỉ thay model cũ khi qua quality gate;
  - ngưỡng WAPE/Bias **vẫn là giá trị mẫu**, chưa được nghiệp vụ duyệt.

## 11. Bảo toàn database / cấu hình / model / import

| | Đầu batch | Cuối batch |
|---|---|---|
| Ứng dụng đang chạy | 1.1.5, pid 17220 | như cũ (không cài, không dừng) |
| DB | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, schema 3, integrity ok | như cũ |
| SHA256 `storage.json` / storage ID | `8D79DBDD…00FDE047` / `6cff0821634b0447` | như cũ |
| Nguồn / scope | DEMO / `DEMO-20261014080556-5342EB` | như cũ |
| Model | `MV-20261014-150621-DF32`, SHA256 `EC507FD6…49BD6C26` | như cũ |
| Lô import / demand / forecast | 6 lô, 38.533 dòng demand, 3 run / 4.368 giá trị | như cũ |
| Mục `sql_sources` trong DB thật | không có | không có (batch không ghi gì vào DB thật) |
| Windows Credential Manager | không có mục DemandForecast | không có |

Thay đổi duy nhất trong DB thật là của chính ứng dụng 1.1.5 đang chạy: lượt D0 theo lịch lúc 14:00 VN trên DEMO (job `JOB-20261015070002-5D5041`, snapshot `SNP-20261015070003-A5EAA3`, 1 dòng audit). Đây là hoạt động bình thường, không phải do batch này.

**Kiểm tra backup:** `backups\backup-20261015-121828-manual.zip` (SHA256 `D0B99A6B…DAF22`) được khôi phục **bằng chính hàm `restore_backup()` của ứng dụng** vào một thư mục cô lập, không bao giờ vào dữ liệu thật:
- integrity ok, 0 lỗi khóa ngoại, schema 3, không cần migration;
- SHA256 của model khôi phục khớp model đang dùng;
- so với DB thật chỉ khác 1 dòng `audit_log` (ghi sau thời điểm backup).

## 12. Gói portable mới

| | |
|---|---|
| Gói | `dist\DemandForecast-1.1.6-win64-portable.zip`, 101.454.383 byte |
| SHA256 (tính 2 lần, trùng nhau) | `E2CFB67D3BBF3D0B7E4E873160A2295E21E0295FD8C40ED870504C5CAD66B3FF` |
| Đã giải nén để kiểm thử | `release\DemandForecast-1.1.6` (8.240 file). `backend/app`, `web`, `docs` trùng mã nguồn. Runtime nhúng: Python 3.14.7, LightGBM 4.7.0. |
| Bí mật trong gói | không có: không có file credentials/service account/client secret, không có chuỗi token |
| Gói 1.1.5 | không đổi, SHA256 `C122B075…76AA56` |

Lần build đầu bị gián đoạn khi phiên làm việc trước kết thúc (zip 0 byte; tiến trình build mồ côi vẫn giữ file). Tiến trình đó đã được dừng; zip và thư mục giải nén dở dang đã bị xóa; gói được build lại sạch từ đầu.

### Nâng cấp lên 1.1.6 (khi quyết định cài)

1. Dừng ứng dụng.
2. Tạo backup: *Hệ thống & sao lưu* → *Sao lưu*.
3. Giải nén gói.
4. Chạy `Install.bat` (hoặc `scripts\install.ps1`). Trình cài kiểm tra cấu hình lưu trữ, giữ dữ liệu trên D:, giữ thư mục 1.1.5 để quay về.

Không cần migration: schema vẫn 3.

### Quay về 1.1.5 (đã kiểm thử trên dữ liệu cô lập)

1. `%LOCALAPPDATA%\Programs\DemandForecast\1.1.6\Stop.bat`.
2. `%LOCALAPPDATA%\Programs\DemandForecast\1.1.5\Start.bat`.

Không cần khôi phục DB. Phiên bản SQL và OAuth client ID lưu bởi 1.1.6 được 1.1.5 bỏ qua. Mục Credential Manager (nếu đã đăng nhập) vô hại; có thể xóa bằng *Đăng xuất* trước khi quay về.

### Máy Windows khác

- Giải nén, chạy `Install.bat`. Không cần cài Python hay Google Cloud CLI.
- Xác thực theo **tài khoản Windows dùng ứng dụng**: *Đăng nhập Google* (cần OAuth client do quản trị cấp), hoặc `gcloud auth application-default login` trong chính tài khoản đó.
- Dữ liệu, cấu hình và Credential Manager riêng theo máy và theo tài khoản.

## 13. Thao tác bắt buộc người dùng / IT thực hiện

**Quản trị Google Cloud (để dùng *Đăng nhập Google* trong ứng dụng):**
1. Trong một project của công ty, cấu hình **OAuth consent screen loại Internal**.
2. Bật **BigQuery API**.
3. Tạo **OAuth client ID loại "Desktop app"**.
4. Nếu Workspace giới hạn ứng dụng bên thứ ba, đưa client vào danh sách tin cậy.
5. Gửi Client ID + Client secret qua kênh an toàn.

**Quyền IAM** cho tài khoản Google sẽ dùng:
- `roles/bigquery.dataViewer` trên dataset `lakehouse-prod-394907.gold_buymed_vn2` (hoặc các bảng `demand_planing_lightgbm`, `fact_order`, `fact_order_item`, `adhoc_pm_master_sku`);
- `roles/bigquery.jobUser` trên project dùng để chạy truy vấn.

**Hoặc, không cần IT:** đăng nhập Windows bằng **tài khoản `Giau Vo`** (tài khoản chạy ứng dụng), cài Google Cloud CLI, chạy `gcloud auth application-default login`. ADC trong hồ sơ Administrator không dùng được.

**Người dùng, sau khi có quyền** (trên 1.1.6, khi quyết định cài):
1. Kết nối BigQuery → Kiểm tra xác thực → Kiểm tra kết nối → Đọc schema → Gợi ý ánh xạ → Kiểm tra dữ liệu toàn kỳ.
2. SQL nguồn → D0 → *Kiểm tra (dry-run)* phiên bản 1. Nếu BigQuery báo lỗi cú pháp ở dấu phẩy trước `FROM`, lưu phiên bản đã sửa **do người dùng tự sửa**.
3. Trả lời các điểm cần xác nhận ở mục 9 (múi giờ, `LEFT JOIN` + `WHERE`, nhân dòng do join, khóa duy nhất, ý nghĩa `demand_quantity`).
4. Duyệt ngưỡng WAPE/Bias và độ dài backtest (6–12 tháng hay giữ như hiện tại).
5. Quyết định thời điểm cài 1.1.6 vào máy thật.

## 14. Giới hạn còn lại

- Không có kiểm chứng BigQuery thật, không đăng nhập Google thật (mục 7). Mọi kết quả liên quan BigQuery là kiểm thử bằng mock hoặc kiểm thử logic trên DuckDB.
- OAuth phụ thuộc chính sách Google Workspace của công ty: client có thể bị chặn (ứng dụng báo `BLOCKED`).
- Scope OAuth dùng `bigquery` (chạy truy vấn cần quyền tạo job). Tính chỉ-đọc được bảo đảm bằng bộ lọc SQL, việc chỉ chạy truy vấn con, dry-run `statement_type = SELECT` và vai trò IAM `dataViewer`.
- **Bộ lọc SQL tĩnh** là lớp phòng vệ thận trọng: có thể từ chối nhầm SQL có tên cột trùng từ khóa mà không đặt trong dấu nháy ngược (ví dụ cột `delete`). Khi đó đặt tên cột trong dấu `` ` ``.
- D0 chỉ đọc theo SQL. Thời điểm cắt trong ngày phụ thuộc dữ liệu nguồn (`created_date` không có giờ).
- Múi giờ lịch chạy cố định `Asia/Ho_Chi_Minh` (múi giờ duy nhất ứng dụng hỗ trợ).
- Chưa thử trên máy Windows khác. Giao diện chưa có bảng chất lượng backtest tổng hợp theo ngày.
