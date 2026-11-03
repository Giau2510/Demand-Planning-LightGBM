# Báo cáo sẵn sàng triển khai 1.1.6 (1.1.5 → 1.1.6, Google OAuth / BigQuery)

Thời điểm: 15/10/2026, 15:25 – 17:15 (giờ Việt Nam). Máy LOG-PC, tài khoản Windows `Giau Vo`.

## Trạng thái cuối: **READY_FOR_EXTERNAL_SETUP**

**Phần nội bộ đã xong:** gói, test tự động, nâng cấp/quay về trên bản sao, backup/khôi phục, script triển khai.

**Chưa thể đánh dấu READY_FOR_DEPLOYMENT**, vì đăng nhập Google thật và truy vấn BigQuery thật chưa được xác minh. Các mục đó ở trạng thái **BLOCKED_EXTERNAL_SETUP** (mục 6): máy chưa có OAuth client do quản trị cấp và tài khoản `Giau Vo` chưa có credentials Google.

**Theo yêu cầu, batch này không:**
- cài 1.1.6;
- dừng 1.1.5;
- chạy migration hay ghi vào DB thật;
- bật lịch D0.

**Checkpoint** (ghi trong `docs/CHECKPOINT.md`, có thể tiếp tục sau gián đoạn):

| Checkpoint | Trạng thái |
|---|---|
| A — Trạng thái & bảo toàn dữ liệu | xong |
| B — OAuth | xong (code); đăng nhập thật BLOCKED_EXTERNAL_SETUP |
| C — BigQuery thật | BLOCKED_EXTERNAL_SETUP |
| D — SQL lịch sử/D0 | xong (đề xuất SQL D0, chưa kích hoạt) |
| E — Kiểm thử | xong |
| F — Đóng gói & kế hoạch triển khai | xong, không cài lên máy thật |

---

## 1. HEAD trước/sau và file thay đổi

**Không phải Git repository** (`fatal: not a git repository`), nên không có HEAD/branch; không commit. Checkpoint mã nguồn:
- trước 1.1.6: `checkpoints\source-1.1.5-before-1.1.6-20261015-133452.zip` + manifest;
- diff 1.1.5 → 1.1.6 (lượt trước): `checkpoints\diff-1.1.5-to-1.1.6.patch`.

**File thay đổi trong batch này** (bổ sung cho 1.1.6):

| File | Lý do |
|---|---|
| `backend/app/bq/connector.py` | `access_check()`: các cổng kiểm tra riêng (xác thực → API + dataset → location → metadata bảng → query job → schema/ánh xạ), dừng ở cổng lỗi đầu tiên; mã lỗi `BQ_API_DISABLED` |
| `backend/app/bq/sql_sources.py`, `settings_service.py`, `sync.py`, `jobs/runner.py`, `api/bq_routes.py`, `messages.py` | **Công tắc lịch D0 BigQuery, mặc định TẮT**; chỉ bật được khi SQL D0 đã kiểm tra đạt. Lượt theo lịch khi tắt được ghi nhận *bỏ qua* (`D0_SCHEDULE_DISABLED`). API `POST /api/bigquery/access-check`. |
| `backend/app/bq/d0_proposed_v2_20261015.sql` (mới) | Đề xuất hiệu chỉnh SQL D0, nạp sẵn làm **phiên bản 2, chưa kiểm tra, không kích hoạt** |
| `frontend/src/pages/GoogleAuth.tsx`, `SqlSources.tsx`, `i18n.tsx` | Nút *Kiểm tra quyền BigQuery* + bảng cổng + tóm tắt (đủ quyền / thiếu quyền / lỗi mạng / hết hạn); công tắc lịch D0 |
| `scripts/install.ps1` | 3 lỗi đã sửa, xem mục 4 |
| `scripts/deploy-upgrade.ps1`, `scripts/rollback-version.ps1` (mới) | Triển khai / quay về có kiểm soát |
| `scripts/build-package.ps1` | Đưa 2 script mới vào gói; không để `__pycache__` của lần kiểm tra runtime lọt vào gói; sinh manifest + `.sha256` |
| Test | `backend/tests/test_v116.py` (+11 test), `test_bigquery.py`, `frontend/src/v116.test.tsx` (+1) |
| Tài liệu | `docs/TRIEN-KHAI-1.1.6.md` (mới), `docs/BIGQUERY.md`, `docs/VAN-HANH.md`, `docs/CHECKPOINT.md` |

## 2. Phiên bản và gói

| | |
|---|---|
| Đang chạy (không đổi) | **1.1.5**, pid 17220, `%LOCALAPPDATA%\Programs\DemandForecast\1.1.5\python\python.exe`, cổng 8765, health OK |
| Gói mới | `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.6-win64-portable.zip` — 91.974.664 byte, 7.106 file |
| **SHA256** (tính 2 lần, trùng nhau) | **`A2E0345CEB654A281557BA1DA825E31E4DFD0A1DCA6C851166B9C144B3A19561`** |
| Manifest | `dist\DemandForecast-1.1.6-win64-portable.manifest.json` (đường dẫn, kích thước, SHA256 từng file) và `…zip.sha256` |
| Bản build trước được giữ | `dist\DemandForecast-1.1.6-build1-superseded-win64-portable.zip` (SHA256 `E2CFB67D…B3FF`) + `release\DemandForecast-1.1.6-build1-superseded` |
| Gói 1.1.5 | không đổi (SHA256 `C122B075…76AA56`) |

**Ghi chú về các lần build trung gian:**
- build 2 và 3 bị loại vì thiếu hoặc mang bản cũ của script triển khai; không phân phối.
- So với build 3 (đã qua kiểm thử cài mới/nâng cấp), build 4 chỉ khác:
  - `scripts/deploy-upgrade.ps1` (bản sửa);
  - `docs/CHECKPOINT.md`;
  - các file sinh không tất định của pip (launcher `.exe`, `RECORD`) và mẫu Excel (dấu thời gian).

  `backend/app` và `web` giống hệt.

## 3. Backup, toàn vẹn và khôi phục

**Bản sao DB thật** (sao chép bằng SQLite backup API, mở nguồn chỉ-đọc):
- `integrity_check` ok, `foreign_key_check` 0 lỗi;
- schema 3, 20 bảng, migration còn thiếu cho 1.1.6: **không có**.

**Số bản ghi:**

| Bảng | Số dòng |
|---|---|
| `import_batches` | 6 |
| `order_lines` | 93.157 |
| `demand_daily` | 38.533 |
| `training_runs` | 1 |
| `forecast_runs` | 3 |
| `forecast_values` | 4.368 |
| `d0_snapshots` | 9 |

**20 file backup ZIP** trong `D:\Buymed\Lightgbm AI\backups` đều **đạt**:
- kiểm tra ZIP, SHA256;
- SQLite `integrity_check` ok, 0 lỗi khóa ngoại;
- schema 2 hoặc 3;
- model mở được bằng LightGBM (300 cây) ở các bản có model.

**Backup mới** theo quy trình chính thức (`POST /api/system/backups`, sao lưu trực tuyến, không dừng ứng dụng):
- file `backups\backup-20261015-153315-manual.zip`, 9.104.288 byte, SHA256 `59F1802111D36FA991D5F93B9C8125B1645185B00B8C96BF97588F1A6013C6C2`;
- **khôi phục thử** bằng chính hàm `restore_backup()` của ứng dụng vào thư mục cô lập:
  - integrity ok, 0 lỗi khóa ngoại, schema 3, không cần migration;
  - SHA256 model khớp model đang dùng (`EC507FD6…`);
  - so với DB thật chỉ khác 1 dòng `audit_log` (ghi sau thời điểm backup).

**Tương thích 1.1.5 ↔ 1.1.6:** cùng schema 3, 1.1.6 không có migration. Dữ liệu mới của 1.1.6 nằm ở khóa cấu hình cấp trên cùng và mục `sql_sources`, đều được 1.1.5 bỏ qua. Quay về 1.1.5 **không cần khôi phục DB** (đã kiểm thử, mục 8).

## 4. Rà soát installer / rollback

`install.ps1` (1.1.5) đã kiểm tra trước khi thay đổi:
- `storage-verify`;
- VC++;
- không thay file đang chạy;
- backup đã xác minh trước nâng cấp;
- migration có backup;
- không xóa dữ liệu.

Phát hiện **3 vấn đề**, đã sửa trong 1.1.6:
1. Ứng dụng bị dừng **trước** bước backup. Nếu backup hoặc migration lỗi thì cài đặt thoát mà **để ứng dụng ở trạng thái dừng**. Nay installer tự **khởi động lại phiên bản trước**.
2. `current.txt` được ghi **trước** migration. Nay chỉ ghi sau khi migration thành công.
3. Khi cài lại cùng phiên bản, thư mục chương trình bị xóa (`Remove-Item $dest`) mà không kiểm tra dữ liệu có nằm trong đó không. Nay installer **dừng** nếu thư mục dữ liệu/backup/log/báo cáo nằm trong thư mục chương trình.

**Mới:**
- `deploy-upgrade.ps1`:
  - kiểm tra trước: SHA256, `VERSION`, gói không chứa credential, phiên bản đang chạy khớp `current.txt`, `storage-verify`, DB, job đang chạy, dung lượng đĩa;
  - backup trực tuyến + kiểm tra file backup;
  - **xác nhận gõ `UPGRADE-1.1.6` trước khi dừng ứng dụng**;
  - chạy installer;
  - kiểm tra sau: phiên bản, thư mục dữ liệu, nguồn, `storage.json`;
  - log `deploy-*.log`;
  - chế độ `-CheckOnly` chỉ đọc.
- `rollback-version.ps1`:
  - kiểm tra schema DB không mới hơn phiên bản đích;
  - xác nhận `ROLLBACK-<phiên bản>`;
  - chuyển phiên bản, cập nhật `current.txt`/shortcut, health check.
- Cả hai có `-NoShortcuts`, dùng cho kiểm thử cô lập để không động vào shortcut thật.
- **Lỗi thật phát hiện nhờ kiểm thử cô lập:** `Compress-Archive` của PowerShell 5.1 ghi tên mục ZIP bằng `\`, làm bước kiểm tra `VERSION` báo sai. Đã sửa và kiểm thử lại.

## 5. OAuth: hiện trạng và cấu hình còn thiếu

**Đã có (1.1.6):**
- **Luồng:**
  - nút **Đăng nhập Google** mở trình duyệt mặc định;
  - OAuth 2.0 cho ứng dụng cài đặt: loopback `127.0.0.1` cổng ngẫu nhiên, `state` 256 bit, **PKCE S256**, hết hạn 5 phút;
  - xử lý hủy (`access_denied`), bị chặn bởi chính sách, `state` sai (không đổi mã), hết thời gian, lỗi mạng, client không hợp lệ.
- **Lưu trữ:**
  - refresh token và client secret chỉ nằm trong **Windows Credential Manager** của tài khoản đang chạy (DPAPI);
  - access token chỉ nằm trong bộ nhớ;
  - phát hiện token hết hạn/bị thu hồi (trạng thái `REVOKED`).
- **Đăng xuất:** thu hồi token tại Google và chỉ xóa các mục `DemandForecast/…`.
- **Backend tự kiểm tra:** cờ dùng OAuth không sửa được qua API cấu hình; credentials luôn lấy từ Credential Manager phía backend.
- **Không phụ thuộc ADC của tài khoản khác:** chẩn đoán hiển thị tài khoản Windows chạy backend và đường dẫn ADC được tìm.
- **Batch này bổ sung:** cổng *Kiểm tra quyền BigQuery* và trạng thái giao diện: đang kiểm tra, đủ quyền, thiếu quyền BigQuery, lỗi mạng, hết hạn.

**Còn thiếu** (do quản trị Google Cloud cung cấp; không tự tạo hay giả lập):
- **OAuth client ID loại "Desktop app"**: Client ID + Client secret;
- OAuth consent screen loại *Internal*, scope `openid`, `email`, `https://www.googleapis.com/auth/bigquery`;
- (nếu Workspace giới hạn) client được đưa vào danh sách *Trusted*.

## 6. BigQuery: từng cổng riêng

| Cổng | Trạng thái | Ghi chú |
|---|---|---|
| Đăng nhập OAuth thật | **BLOCKED_EXTERNAL_SETUP** | chưa có OAuth client |
| ADC của tài khoản `Giau Vo` | không có | ADC chỉ có trong hồ sơ Administrator (không đọc được); gcloud không có trên PATH |
| BigQuery API bật ở `lakehouse-prod-394907` | **BLOCKED_EXTERNAL_SETUP** | chưa xác minh (cần credentials) |
| IAM `bigquery.jobUser` (project), `bigquery.dataViewer` (dataset `gold_buymed_vn2`) | **BLOCKED_EXTERNAL_SETUP** | chưa xác minh; ứng dụng không tự cấp quyền |
| Location `asia-southeast1`, dataset, metadata bảng `demand_planing_lightgbm` | **BLOCKED_EXTERNAL_SETUP** | |
| Query job (dry-run + `SELECT 1`) | **BLOCKED_EXTERNAL_SETUP** | |
| Schema nguồn | **BLOCKED_EXTERNAL_SETUP** | |
| Dữ liệu đủ điều kiện (kiểm tra toàn kỳ) | **BLOCKED_EXTERNAL_SETUP** | |

Trên bản sao DB, *Kiểm tra quyền BigQuery* dừng đúng ở cổng xác thực (`BQ_AUTH_MISSING`); các cổng sau ghi *chưa chạy*. **Không có truy vấn BigQuery thật nào được chạy; không có email/tài khoản thật nào được xác minh.**

## 7. SQL đã sửa và lý do

**SQL lịch sử** (bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`): không đổi. Mapping, múi giờ, khóa, khoảng ngày (từ 01/01/2026) và hành vi khi không có dữ liệu (`NO_DATA` → chặn) đã có từ 1.1.5/1.1.6.

**SQL D0:**
- Phiên bản 1 là SQL của người dùng, giữ **nguyên văn** (SHA256 `b9d6d9f5…`).
- Phiên bản 2 là **đề xuất**, chưa kích hoạt; người dùng chọn sau khi dry-run thật.

| # | Thay đổi so với bản gốc | Lý do |
|---|---|---|
| 1 | Bỏ dấu phẩy sau `b.sales_price` trước `FROM` | Có thể gây lỗi cú pháp. Chỉ BigQuery dry-run xác định được; bản gốc vẫn giữ để dry-run chứng minh. |
| 2 | `LEFT JOIN` → `JOIN` cho `b` và `c` | `WHERE` trên cột của `b` và `c` đã loại dòng không khớp. Kết quả **giống hệt** bản gốc; nay ý đồ rõ ràng. |
| 3 | Điều kiện `seller_code`/`sku_system_status` đưa vào CTE `master` + `DISTINCT` | Dòng master **trùng hoàn toàn** không còn nhân đôi nhu cầu. Nếu cùng `sub_sku_code` có nhiều trạng thái khác nhau thì vẫn nhân dòng → ứng dụng phát hiện và **chặn ghi** (khóa không duy nhất). |
| 4 | `DATE(a.created_at, 'Asia/Ho_Chi_Minh')` | **Chỉ đúng nếu** `created_at` là TIMESTAMP (UTC). Nếu là DATETIME giờ VN thì giữ như bản gốc. Phải xác minh bằng schema thật trước khi dùng. |

**Kiểm thử logic** (DuckDB, dữ liệu tổng hợp, **không phải BigQuery**): 5/5.
- Cùng dòng, cùng số lượng như bản gốc.
- Ngày theo giờ VN (đơn 02:00 VN không còn rơi vào ngày hôm trước).
- Master trùng hoàn toàn: bản gốc nhân đôi (6 thay vì 3), bản 2 không.

**Điều kiện kích hoạt D0:**
- SQL được version hóa, có dry-run, kiểm tra cột/kiểu/khóa, giới hạn chi phí;
- retry không ghi trùng;
- lịch **mặc định TẮT** và **chưa bật**;
- trên máy thật: chưa có cấu hình `sql_sources` nào được ghi.

## 8. Kết quả kiểm thử

| Nhóm | PASS | FAIL | SKIP | BLOCKED |
|---|---|---|---|---|
| Backend pytest toàn bộ (`logs\development\tests_20261015_154325.log`) | 224 | 0 | 0 | — |
| — trong đó `test_v116.py`: OAuth (callback hợp lệ/sai, `state` sai, timeout, hủy, bị chặn, lỗi mạng, `invalid_client`, refresh OK/thất bại, đăng xuất, thiếu cấu hình), Credential Manager thật, không lộ secret (DB/API/**file backup ZIP**), bộ lọc SQL, SQL editor/D0, scheduler (retry, backfill, idempotent, lịch tắt), cổng truy cập BigQuery | 40 | 0 | 0 | |
| — trong đó `test_v115_bigquery_features.py` + `test_bigquery.py`: phân loại lỗi (auth thiếu/hết hạn, thiếu IAM, sai location, không thấy bảng, timeout, quota, vượt chi phí, sai schema), retry có giới hạn, validation, đối chiếu, trùng, feature registry | 33 + 13 | 0 | 0 | |
| Frontend vitest | 46 | 0 | 0 | |
| TypeScript + build | đạt | | | |
| Lint frontend | — | — | **SKIP** (dự án không cấu hình ESLint/lint; dùng `tsc` strict) | |
| E2E trình duyệt trên bản sao DB | 125 | 0 | | |
| Gói cô lập — cài mới (build 3) | 24 + 43 | 0 | | |
| Gói cô lập — nâng cấp trên bản sao DB thật + quay về 1.1.5 (build 3) | 26 + 4 + 7 | 0 | | |
| Kịch bản triển khai cô lập (`deploy-upgrade` + `rollback-version`): script nguồn / script trong gói build 4 | 12 / 12 | 0 | | |
| Kiểm tra trước triển khai trên **máy thật** (`deploy-upgrade.ps1 -CheckOnly`, chỉ đọc) | PRECHECK OK | | | |
| Logic SQL D0 (DuckDB): bản gốc / so sánh bản đề xuất | 10 / 5 | 0 | | |
| Đăng nhập Google thật, IAM, API, location, dry-run và truy vấn BigQuery thật | | | | **8 mục** |

Kiểm thử gói đã bao gồm: đường dẫn có dấu cách (`C:\Users\Giau Vo\…`), đường dẫn Windows, log, khởi động và health endpoint. Trong thư mục thử rất sâu có cảnh báo vượt 260 ký tự (MAX_PATH) với vài file; không ảnh hưởng, vì đường dẫn cài thật ngắn hơn nhiều.

## 9. Không lộ secret

- **Gói:** không có file credentials/service account/client secret/`.env`; không có chuỗi token (`ya29.`, `GOCSPX-`, refresh token); không có DB, `storage.json`, `runtime.json`; không có `__pycache__` của ứng dụng.
- **Test:** refresh token, client secret, access token, mã xác thực không xuất hiện trong DB, `settings_history`, `sync_state`, `audit_log`, API `/api/settings`, `/api/bigquery/status`, `/api/bigquery/identity`, **file backup ZIP**.
- Log loopback OAuth tắt ghi URL. Báo cáo chẩn đoán chỉ chứa các trường BigQuery đã chọn, không có secret.
- Windows Credential Manager của máy thật: không có mục `DemandForecast` nào (không test nào ghi secret vào đó, trừ một mục thử tự xóa).

## 10. Dữ liệu thật trong batch

**Không đổi:**
- 1.1.5 vẫn chạy (pid 17220); `current.txt` = 1.1.5; shortcut Desktop → 1.1.5; 1.1.6 **chưa cài**;
- `storage.json` (SHA256 `8D79DBDD…00FDE047`), storage ID `6cff0821634b0447`;
- nguồn DEMO / scope `DEMO-20261014080556-5342EB`;
- model `EC507FD6…`, lô import, forecast;
- không có mục `sql_sources` trong DB thật.

**Thay đổi trong DB thật**, chỉ gồm:
- 1 backup chính thức do batch tạo (audit `BACKUP_CREATED`);
- 2 lượt D0 theo lịch lúc 14:00 và 16:00 VN của chính 1.1.5 trên DEMO (hoạt động bình thường).

## 11. Việc người dùng / quản trị viên cần làm tiếp

1. **Quản trị Google Cloud:**
   - tạo OAuth client **Desktop app** (consent screen Internal; scope `openid`, `email`, `bigquery`);
   - bật **BigQuery API**;
   - gửi **Client ID + Client secret** qua kênh an toàn.
2. **Quản trị IAM**, cho tài khoản Google sẽ dùng:
   - `roles/bigquery.jobUser` trên `lakehouse-prod-394907`;
   - `roles/bigquery.dataViewer` trên dataset `gold_buymed_vn2` (hoặc các bảng `demand_planing_lightgbm`, `fact_order`, `fact_order_item`, `adhoc_pm_master_sku`).
3. **Người dùng nâng cấp:** chạy `deploy-upgrade.ps1 -Package … -ExpectedSha256 A2E0345CEB654A281557BA1DA825E31E4DFD0A1DCA6C851166B9C144B3A19561`, gõ `UPGRADE-1.1.6` khi được hỏi. Hướng dẫn: `docs\TRIEN-KHAI-1.1.6.md`.
4. **Sau nâng cấp:**
   - nhập OAuth client → **Đăng nhập Google** → **Kiểm tra quyền BigQuery** (mọi cổng phải Đạt);
   - **Kiểm tra dữ liệu toàn kỳ**;
   - dry-run SQL D0 phiên bản 1 và 2, xác nhận phiên bản đúng nghiệp vụ và kiểu cột `created_at`.
5. **Chỉ sau khi bước 4 đạt:** kích hoạt chế độ sản xuất BIGQUERY và bật **Lịch D0 BigQuery**.
6. **Nếu cần quay về:** `rollback-version.ps1 -To 1.1.5`. Không cần khôi phục DB.
