# Demand Forecasting 1.2.6: xử lý blocker, phát hành và diễn tập deploy / rollback

- **Ngày:** 18/10/2026, 13:00–15:20 giờ Việt Nam.
- **Phạm vi:**
  - B1: lưu snapshot 90 ngày (migration 0006);
  - B2: hai lịch mới mặc định TẮT;
  - F1: sửa mô tả lỗi kiểm tra bản sao;
  - QA, build gói bằng `release.ps1`, diễn tập 1.2.5 ↔ 1.2.6 trên bản sao cách ly.
- **Không làm:** deploy, push, ghi production, chạy job production.
- **Kết luận: `READY FOR OWNER APPROVAL`.** Production vẫn ở 1.2.5 cho tới khi chủ sở hữu duyệt deploy.

## A. Tóm tắt

| Blocker (bản rà soát 12:57) | Trạng thái | Bằng chứng chính |
|---|---|---|
| B1 – chưa có lưu giữ 90 ngày | **Đã xử lý** | migration 0006 + `eod_retention.py` + `scripts\eod-retention.ps1`; 15 test mới; 2 bản sao DB production; diễn tập xóa thật trên bản sao |
| B2 – hai lịch mới mặc định BẬT | **Đã xử lý** | mặc định `false`; thiết lập 1.2.5 thiếu khóa đọc là TẮT; sau nâng cấp trên bản sao cả hai TẮT; kế hoạch scheduler 1.2.6 trùng hệt 1.2.5 |
| B3 – chưa có gói 1.2.6 | **Đã xử lý** | `dist\DemandForecast-1.2.6-win64-portable.zip`, SHA-256 `BBD73386D698A789A2A75DBECDC252ABCD7B1A5E26B98D8B3E35970A9A7F09C3` |
| B4 – chưa diễn tập 1.2.6 | **Đã xử lý** | diễn tập lần 2: **43/43 PASS** (lần 1: 38/40, 2 FAIL do phép đo, mục E) |
| F1 – tài liệu nói lỗi verify "tự thử lại" | **Đã sửa** | messages.py, LICH-SU-FORECAST.md, SCHEDULER.md, VAN-HANH.md, CHANGELOG; test chứng minh FAILED, không retry |

Không còn blocker kỹ thuật. Việc còn lại thuộc chủ sở hữu:

1. Duyệt deploy, kèm khung giờ.
2. Sau khi kiểm tra sau deploy đạt, quyết định bật hai lịch.
3. Khoảng 90 ngày sau khi bật `eod`, duyệt lần chạy dọn đầu tiên.

## B. Code và migration

**Commit (cục bộ, chưa push):**

- `6a65fa2`: code và test.
- `d05ff97`: tài liệu.
- Cả hai nằm trên `ba74335` → `581fcdc`. Không amend, không reset.

Message của `6a65fa2` ghi "16" test mới. Thực tế file có **15** test. Commit không được sửa lại.

**File đã đổi:**

- **Backend:**
  - mới: `backend/app/eod_retention.py`, `backend/app/migrations/0006_eod_snapshot_retention.sql`;
  - sửa: `cli.py` (lệnh `eod-retention`), `data_checks.py` (3 kiểm tra), `settings_service.py` (mặc định), `messages.py` (F1 + 4 mã mới), `jobs/flows.py`, `jobs/scheduler.py` (docstring).
- **Script:**
  - mới: `scripts/eod-retention.ps1`, ASCII, CRLF;
  - sửa: `scripts/build-package.ps1`, thêm script trên vào danh sách đóng gói.
- **Test:**
  - mới: `backend/tests/test_v126_retention_defaults.py`;
  - sửa: `test_v126_eod_backup_close.py`, `test_v118.py`, `frontend/src/v126.test.tsx`.
- **Tài liệu:** `docs/LICH-SU-FORECAST.md` (mục 14 mới, mục 8–13), `SCHEDULER.md`, `VAN-HANH.md`, `data/DATA-MODEL.md`, `data/DATA-DICTIONARY.md`, `AGENTS.md`, `CHANGELOG.md`, `CHECKPOINT.md`.

Line ending của từng file được giữ nguyên; PS1 chỉ chứa ASCII; quét secret trên diff không có kết quả.

**Checkpoint trước khi sửa:** `checkpoints/checkpoint-20261018-v126-blockers-before.zip`, là git archive của `ba74335`, SHA-256 `DC5F177F97425DF4284CF9E6329F0376FFDA11D1653E03934412AF2A3871EA33`.

### Migration 0006 (schema 5 → 6)

- **Bảng mới `forecast_eod_snapshot_retention`.**
  - Mỗi dòng vừa là phiếu cho phép xóa (`DELETING`), vừa là nhật ký vĩnh viễn của snapshot đã xóa (`DELETED`).
  - Nhật ký giữ: id, scope, ngày, trạng thái, run nguồn, số dòng, sha256, tổng, ngày cắt, bản sao lưu, thời điểm.
  - Không có khóa ngoại tới snapshot, vì dòng này tồn tại lâu hơn snapshot.
- **Thay trigger có kiểm soát, trong cùng transaction của migration.**
  - `DROP TRIGGER trg_fes_no_delete` và `DROP TRIGGER trg_fes_values_no_delete`, thay bằng `trg_fes_delete_retention_only` và `trg_fes_values_delete_retention_only`.
  - Đây là thay đổi trigger được chủ sở hữu phê duyệt trong B1; không có dữ liệu nào bị sửa hay xóa.
  - Nếu migration lỗi giữa chừng, cả file rollback và DB vẫn ở schema 5 với trigger của 0005. Đã test bằng một 0006 hỏng ở câu lệnh cuối.
- **Điều kiện để một DELETE được phép.** Mọi DELETE khác đều bị từ chối.
  - Có phiếu `DELETING` cho đúng snapshot (id, scope, ngày).
  - Phiếu phải là INSERT gần nhất của chính connection đang xóa (`seq = last_insert_rowid()`). Mỗi phiếu có `seq` ngẫu nhiên 62 bit.
  - `business_date` phải trước ngày cắt của phiếu **và** trước `date('now','+7 hours','-90 days')`, do chính SQLite tính.
  - Giá trị phải xóa trước đầu mục.
- **Phiếu.**
  - Chỉ ghi được khi không có phiếu nào khác đang mở.
  - Không bao giờ bị xóa.
  - Chỉ đổi một lần, `DELETING` → `DELETED`, khi snapshot đã hết dòng.
- **Chặn REPLACE** (phát hiện của data-reviewer).
  - `INSERT OR REPLACE` xóa dòng trùng khóa mà không kích hoạt trigger xóa, vì ứng dụng không bật `recursive_triggers`.
  - 0006 thêm 5 trigger `*_no_replace` cho các bảng `forecast_eod_snapshots`, `forecast_eod_snapshot_values`, `actual_closes`, `actual_close_values` và bảng phiếu.
  - Test xác nhận trigger BEFORE INSERT chạy trước bước REPLACE: fingerprint không đổi.
  - Bảng lịch sử D+1 của 0004 (đã phát hành ở 1.2.5) vẫn còn lỗ hổng REPLACE cũ. Ứng dụng không dùng REPLACE trên các bảng đó. Ngoài phạm vi lần này.
- **Migration không xóa gì.** Bản sao DB production: 23 bảng hiện có giữ nguyên fingerprint; các bảng mới rỗng.

### Chính sách 90 ngày (`docs/LICH-SU-FORECAST.md` mục 14)

- **Gốc tính tuổi:** ngày nghiệp vụ `business_date` theo giờ Việt Nam. Không dùng giờ tạo UTC, không dùng tuổi file.
- **Hết hạn:** `business_date < hôm nay (VN) − 90 ngày`. Snapshot **đúng 90 ngày được giữ**.
  - Ví dụ 18/10/2026: ngày cắt là 20/07, nên 19/07 bị xóa, 20/07 được giữ.
  - Snapshot của ngày 18/10/2026 có thể xóa từ 17/01/2027.
- **Giữ lại (held):**
  - snapshot COMPLETE đã hết hạn nhưng còn là dự phòng đang hiển thị cho một ngày chạy trong 90 ngày, lý do `SERVES_BACKUP_INSIDE_WINDOW`;
  - snapshot có số giá trị lệch với đầu mục.
- **Từ chối cả lần chạy** nếu có bảng khác tham chiếu tới bảng snapshot.
- **Mọi trạng thái hết hạn như nhau.** `INCOMPLETE` / `NO_SOURCE` chỉ có đầu mục, không có giá trị.
- **Vận hành:**
  - Dry run là mặc định: mở DB chỉ đọc, in kế hoạch và `plan_id`.
  - `-Apply -Plan <plan_id>` chỉ xóa đúng kế hoạch đã duyệt. `plan_id` đổi khi tập snapshot, trạng thái hoặc số dòng đổi.
  - Trước khi xóa, tự sao lưu và kiểm `integrity_check`.
  - Mỗi snapshot một transaction.
  - Audit `EOD_SNAPSHOT_RETENTION_STARTED` trước, `EOD_SNAPSHOT_RETENTION` sau.
  - Lỗi thì rollback snapshot đó, dừng lần chạy, phát alert ERROR `EOD_RETENTION_FAILED`.
- **Không có lịch tự dọn.** Scheduler không bao giờ chạy việc này.
- **Sau khi xóa:** ngày chạy chỉ có dự phòng từ snapshot đó hiển thị trống (`has_history = false`, forecast `null`, KPI không tính). Có test riêng xác nhận.

**Dry run trên bản sao production** (copyB, 13:49): `today 2026-10-18`, `cutoff_date 2026-07-20`, `delete 0`, `kept 1 snapshot / 119.889 dòng`, `plan_id b11813d5e661dcec`, `written false`; fingerprint không đổi. Với một snapshot hết hạn giả lập cỡ thật: `delete 1 / 119.889 dòng`, `first = last = 2026-07-10`, `by_status COMPLETE 1`, plan `ad012a15ffa17c3b`. Apply xóa trong khoảng 2 giây, cộng khoảng 60 giây sao lưu. Các bảng khác giữ nguyên.

### B2: lịch mặc định

- `ScheduleSettings.eod_enabled` / `close_enabled` mặc định `False`.
- Production lưu thiết lập `schedule` dưới dạng JSON không có khóa này. Đã xác nhận trên bản sao: `schedule_raw_has_eod_keys = false`. Vì vậy 1.2.6 đọc ra TẮT.
- Migration không ghi thiết lập: JSON `schedule` trên bản sao có hash `97757e22a9d85247`, giữ nguyên trước và sau.
- Khi flow TẮT:
  - `scheduler.plan` không lên lịch;
  - runner bỏ qua lần chạy theo lịch hoặc thử lại (`EOD_SCHEDULE_DISABLED` / `CLOSE_SCHEDULE_DISABLED`).
- Bật chỉ qua `/api/schedules`, và thời điểm bật được lưu (`*_enabled_at`); mốc trước thời điểm đó không chạy. Lựa chọn đã lưu không bị ghi đè.
- UI hiển thị đúng trạng thái backend trả về: test vitest với flow TẮT; khi hiển thị trang không có lệnh PUT nào.

### F1

Hành vi thật (`jobs/runner.py`, khoảng dòng 189–203 và `_fail`):

- `EOD_SNAPSHOT_VERIFY_FAILED` là `AppError` và không thuộc `NEEDS_CONFIG_CODES`, nên đi vào `_fail(..., retry=False)`.
- Kết quả: job FAILED ngay lần đầu, alert ERROR mang chính mã đó, không đặt `next_attempt_at`.
- Mốc lịch không được lên lại, vì khóa idempotency đã tồn tại ở trạng thái FAILED.
- Transaction rollback nên không có cả dòng đầu mục.
- Chỉ các lỗi sau được thử lại: `Retryable`, `TIMEOUT`, lỗi không phải `AppError`, `BQ_ERROR` và `BQ_AUTH_MISSING`.

Đã sửa văn bản tại `messages.py` (vi/en), `LICH-SU-FORECAST.md` mục 10, `SCHEDULER.md` (quy tắc retry), `VAN-HANH.md` và `CHANGELOG`. Không đổi logic retry. Test `test_a_verify_failure_ends_failed_with_an_alert_no_retry_and_nothing_stored` chứng minh:

- FAILED, `attempt 1`, `next_attempt_at null`;
- alert ERROR;
- 0 snapshot, 0 audit;
- scheduler không lên lại mốc;
- gọi lại trả về `RETRIES_EXHAUSTED`;
- chạy tay sau đó thành công.

## C. QA

| Hạng mục | Kết quả | Loại bằng chứng |
|---|---|---|
| Backend (QA của `release.ps1`, commit `d05ff97`) | **472 passed, 7 skipped, 0 failed**. Cả 7 skip là test BigQuery thật (`DF_REAL_BQ=1`); không chạy vì nhiệm vụ không dùng dịch vụ ngoài | unit / integration trên DB cách ly |
| Frontend vitest | **111/111** (18 file; 1 test mới) | unit (jsdom, API giả) |
| Typecheck / build | `typecheck=0`, `build=0` (vite 6,6 s) | build |
| Lint | **chưa cấu hình** (không tính là đạt) | — |
| Test mới (`test_v126_retention_defaults.py`, 15) | đạt: migration 4→6 và 5→6, migration hỏng giữa chừng, dry run mặc định / biên 90 ngày, apply đúng kế hoạch + backup, giữ snapshot đang làm dự phòng, trigger chặn xóa trái phép, chặn REPLACE + data-check trigger, lỗi giữa chừng, ngày VN vs UTC, lịch sử trống sau khi xóa, mặc định TẮT (thiết lập 1.2.5), restart không tạo job, lựa chọn đã lưu giữ nguyên, nâng cấp v4, F1 | integration trên DB cách ly, đồng hồ thật |
| Test hồi quy đã sửa | 8 test của `test_v126_eod_backup_close.py` bật flow tường minh (`_day_end_on()`) vì đang kiểm hành vi khi BẬT; mục tiêu migration 4→6; `test_v118` trạng thái nạp lại (eod/close False). Không xóa assertion nào | — |
| DB copy (`integ126b.py`, copyA 13:38, copyB 13:49) | schema 4→6, 23 bảng giữ nguyên, kế hoạch scheduler 5 mốc không có job cuối ngày (D-1/D-0/train như nhau dù flow mới bật hay tắt), snapshot thật 18/10 COMPLETE 119.889 dòng trong 3,0 s, xóa snapshot giả lập 119.889 dòng | bản sao DB production |
| Review độc lập (data-reviewer) | SAFE WITH CONDITIONS, không có blocker; đã sửa: REPLACE, `seq` ngẫu nhiên, kiểm tra trigger, snapshot đang giữ không bị báo "cần dọn", audit lúc bắt đầu, `plan_id` gồm trạng thái / số dòng; ghi chú còn lại ở mục F | đọc code |

Không chạy được hoặc không chạy:

- 7 test BigQuery thật.
- Tunnel Cloudflare thật: diễn tập chỉ dùng proxy cục bộ.
- Scheduler tick thật trong app diễn tập (`DF_DISABLE_SCHEDULER=1`, để không gọi BigQuery). Đã thay bằng `plan()` của chính bản cài và test `Scheduler.tick` trên DB cách ly.

## D. Gói phát hành

| Mục | Giá trị |
|---|---|
| File | `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.6-win64-portable.zip` |
| Kích thước | 92.241.672 byte |
| SHA-256 (đo lại bằng hashlib và `Get-FileHash`) | `BBD73386D698A789A2A75DBECDC252ABCD7B1A5E26B98D8B3E35970A9A7F09C3` (= file `.sha256` = manifest) |
| Tạo lúc | 18/10/2026 14:12:25 (`built_at` 14:05:25) |
| VERSION / BUILD-INFO | `1.2.6`; commit `d05ff9736d90979058e5a6d09ce928a2d415f81f`, `dirty=false`, source fingerprint `A5A697BB05D6F6A2…6303`, Python 3.14.7 |
| Manifest | `dist\DemandForecast-1.2.6-win64-portable.manifest.json`: 7.136 file, zip 7.158 mục |
| Nội dung đã kiểm | migration 0001–0006; `eod_retention.py`; `scripts\eod-retention.ps1`; mặc định eod/close `False`; văn bản F1 (messages, tài liệu); `forecast_backup.py`, `actual_close.py`; `deploy-upgrade.ps1`, `restore.ps1`; tài liệu; runtime nhúng được build tự kiểm (LightGBM 4.7.0) |
| Không chứa | `__pycache__` / `.pyc`, file DB, `storage.json`, file giống credential, thư mục dữ liệu / log / backup |
| Dùng trong diễn tập | đúng gói này; SHA trước và sau diễn tập trùng nhau (cả 1.2.5 `F502042C…C58E`) |

`release.ps1` chạy kế hoạch dọn artifact ở chế độ dry run và không xóa gì; `dist\` còn đủ mọi gói cũ và `-superseded`. Lần gọi `release.ps1` đầu tiên không chạy được vì đường dẫn có dấu cách chưa được bọc ngoặc kép trong lệnh khởi động; không có gì thực thi; lần gọi lại chạy đủ.

## E. Diễn tập deploy 1.2.5 → 1.2.6 (bản sao cách ly)

**Kịch bản:** `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p4\iso126r.ps1`. Kết quả: `…\scratchpad\p4\iso126r_result.json`, log: `…\scratchpad\p4\iso126r_console.txt`.

**Cách ly:**

- `LOCALAPPDATA`, `DF_DATA_DIR` / `LOGS` / `BACKUPS` / `REPORTS` / `STORAGE_CONFIG` đều trong `…\scratchpad\r`;
- `DF_PORT=8879`, `DF_DISABLE_SCHEDULER=1`;
- proxy cục bộ 8878 chạy đúng file `scripts\remote\readonly_proxy.py` mà production đang dùng, không có tunnel.

**Tự dừng nếu không đạt điều kiện:**

- `data_dir` không nằm trong thư mục diễn tập;
- file runtime không ghi cổng 8879. Nếu thiếu file này, `deploy-upgrade` và `rollback-version` mặc định gọi cổng 8765, tức production;
- có Scheduled Task "DemandForecast", vì `install.ps1` sẽ đăng ký lại task đó.

**Lần 1 (14:15): 38/40.** Hai FAIL đều do phép đo. Lần gọi `/api/system/status` đầu tiên của 1.2.5 ngay sau khởi động vượt timeout 60 s, nên giá trị "trước nâng cấp" bị rỗng; phép so sau rollback vì thế cũng sai. Khởi động lại 1.2.5 cách ly cho thấy API trả đúng `BIGQUERY` / `FCR-20261018043737-798B4D`. Đã sửa phép đo (timeout 300 s, thử lại), thêm theo dõi health mỗi giây, rồi chạy lại toàn bộ.

**Lần 2 (14:46–15:02): 43/43 PASS.**

| Bước | Kết quả |
|---|---|
| Bản sao | backup API, nguồn `mode=ro`, schema 4, 6 forecast run; data-check WARN (`forecast_series_meta` 1, có sẵn trên production) |
| Trước nâng cấp (1.2.5 chính thức cài cách ly) | BIGQUERY, `FCR-20261018043737-798B4D`; D-1 BẬT 03:00 / dự phòng 05:00; D-0 BẬT 08–18 mỗi 2 giờ; huấn luyện BẬT 09:00, chạy bù SKIP |
| `deploy-upgrade -CheckOnly` | exit 0; fingerprint không đổi (không ghi) |
| `deploy-upgrade -ConfirmToken UPGRADE-1.2.6` | exit 0, tổng 386,7 s. Backup online `backup-20261018-145209-manual.zip` (SHA `312F84CB…1040`), lấy **trước** bước xác nhận |
| Thời gian gián đoạn (proxy cục bộ, mỗi giây) | **116,4 s** (14:55:20 → 14:57:16), 39 lần 502, rồi 200 trên 1.2.6. Lần 1: tổng 694 s (đĩa lạnh) |
| Thứ tự migrate trong `install.ps1` | đã xác nhận: app dừng → `app.cli backup` của **1.2.6** tạo `pre-migration-v4` (14:55:23–49) → migrate 0005 + 0006 (14:55:49) → backup `cli` (14:56:12) → **sau đó** mới chép chương trình → migrate (không còn gì) → khởi động. Nghĩa là migrate diễn ra **trước** khi chép file chương trình |
| Sau nâng cấp | schema 6; data-check không FAIL; 6 kiểm tra cuối ngày OK. Chỉ đổi: 5 bảng mới (rỗng), `schema_migrations` 4→6, `audit_log` +1 (`BACKUP_CREATED` của backup online). 15 bảng forecast / model / lịch sử / demand / thiết lập giống hệt; file model giống hệt; JSON thiết lập BigQuery / model / schedule giống hệt |
| Lịch | `eod` TẮT 23:55, `close` TẮT 23:59; D-1 / D-0 / huấn luyện giữ nguyên công tắc và giờ; kế hoạch scheduler của 1.2.6 **trùng hệt** 1.2.5 ở 7 mốc (03:05, 05:05, 09:05, 16:05, 23:56, 23:59:30, 00:05); 0 job cuối ngày |
| Forecast đang dùng | vẫn `FCR-20261018043737-798B4D`, nguồn BIGQUERY |
| Proxy (file không đổi, cùng PID, không khởi động lại) | health 1.2.6 và history overview qua proxy; ghi trả 405 (gồm `PUT /api/schedules/eod`, `POST /api/schedules/eod/run`); `/api/system/paths` và `/api/system/backups` trả 403 |
| Dry run lưu giữ (script trong gói + CLI) | exit 0, 0 snapshot cần xóa, cutoff 20/07/2026, không ghi gì |
| Dữ liệu thử sau nâng cấp (chỉ trên bản sao) | chạy tay EOD → 17/10 COMPLETE 119.875 dòng (nguồn `FCR-20261017123417-FCC0EB`); chạy tay chốt → 17/10 `CLOSED_UNVERIFIED` từ D1, 2.983 dòng, tổng 68.598. Hai flow **vẫn TẮT** sau khi chạy tay |
| Xóa thật (snapshot giả lập `FES-SYNTHETIC-REHEARSAL-20260710`, ngày 10/07, 119.875 dòng, **dữ liệu thử chỉ có trên bản sao**) | dry run liệt kê đúng snapshot đó (plan `a2eddc169a9be4b4`); `-Apply` thiếu `-Plan` bị từ chối (exit 2); `-Apply -Plan` exit 0 trong 23,4 s, gồm backup `pre-eod-retention`. Chỉ 4 bảng đổi: snapshot 2→1, giá trị 239.750→119.875, phiếu 0→1, audit +2. Snapshot thật 17/10 còn nguyên; data-check OK |

## F. Diễn tập rollback 1.2.6 → 1.2.5

| Bước (lệnh thật) | Kết quả |
|---|---|
| `…\1.2.6\scripts\rollback-version.ps1 -To 1.2.5 -CheckOnly` | **từ chối**, exit 3 (schema 6 > 4) |
| `…\1.2.6\scripts\stop.ps1` | 1.2.6 dừng |
| `…\1.2.5\scripts\restore.ps1 -File …\backup-20261018-145209-manual.zip` (**restore.ps1 của 1.2.5**) | exit 0, 39,9 s; tự tạo `backup-20261018-150053-pre-restore.zip`; DB khôi phục ở **schema 4**: bản 1.2.5 không migrate lên |
| `…\1.2.6\scripts\rollback-version.ps1 -To 1.2.5 -ConfirmToken ROLLBACK-1.2.5 -NoShortcuts` | exit 0; 1.2.5 chạy trên DB đã khôi phục; `current.txt` 1.2.5 |
| Gián đoạn (từ lúc dừng tới khi 1.2.5 trả 200) | **55,1 s**; tổng các bước 61,3 s |
| Fingerprint sau rollback | **mọi bảng giống hệt** trạng thái ngay trước deploy; data-check không FAIL; forecast / model / lịch sử / thiết lập / file model như trước |
| Lịch sau rollback | 1.2.5 có `d1`, `d0`, `train` như trước; không có flow `eod` / `close` (1.2.5 không biết job này, nên không thể chạy); forecast vẫn `FCR-…798B4D`; proxy trả health 1.2.5 |
| File `pre-restore` | giống hệt DB schema 6 tại lúc rollback, nên dữ liệu sau nâng cấp còn nguyên trong đó |

**Dữ liệu mất trên DB đang chạy khi rollback** (đo trên bản sao, đều còn trong `pre-restore`):

- `forecast_eod_snapshots` +1, `forecast_eod_snapshot_values` +119.875;
- `actual_closes` +1, `actual_close_values` +2.983;
- `forecast_eod_snapshot_retention` +1;
- `job_runs` +2;
- `audit_log` +5, gồm dòng `BACKUP_CREATED` của chính bản sao lưu;
- schema 6 → 4.

Trên production, rollback mất **mọi thứ ghi sau bản backup online của `deploy-upgrade`**:

- snapshot D-0 trong ngày, không đọc lại được (D-0 là ảnh chụp theo giờ);
- D-1: đọc lại được từ BigQuery;
- job;
- forecast publish sau deploy;
- thay đổi thiết lập;
- snapshot / bản chốt / phiếu dọn của 1.2.6.

**Rủi ro còn lại nếu rollback production:**

1. Phải dùng `restore.ps1` của thư mục **1.2.5**. Bản của 1.2.6 sẽ migrate lại DB vừa khôi phục lên schema 6.
2. `install.ps1` migrate **trước** khi chép chương trình. Nếu cài lỗi sau bước migrate, `Stop-Install` khởi động lại 1.2.5 nhưng 1.2.5 từ chối schema 6, nên app không chạy cho tới khi khôi phục backup. Đường xử lý là rollback như trên.
3. `rollback-version.ps1` lấy cổng từ file runtime, mặc định 8765. Trên production đó chính là cổng thật nên đúng; chỉ cần lưu ý khi diễn tập.
4. Mỗi backup khoảng 76–79 MB; một lần deploy tạo 3 bản, cộng `pre-restore` nếu rollback. Thư mục `backups` không tự dọn. Ổ D còn khoảng 77 GB (đo 12:53).

## G. An toàn production

Đã xác minh bằng thao tác chỉ đọc (GET và đọc trạng thái tiến trình), trước và sau diễn tập:

- vẫn 1.2.5, pid 22024; proxy 26416 và cloudflared 31076 còn sống;
- link `https://volumes-jean-angels-configurations.trycloudflare.com/api/health` trả 200, 1.2.5;
- `db_version 4`, BIGQUERY, forecast đang dùng `FCR-20261018043737-798B4D`;
- lịch: D-1 BẬT 03:00 / 05:00, D-0 BẬT 08–18, huấn luyện BẬT 09:00 SKIP; không có flow `eod` / `close`;
- không có job đang chạy;
- `current.txt` 1.2.5; `storage.json` `8D79DBDD…E047` không đổi.

Hai job D-0 lúc 12:00 và 14:00 do scheduler của chính production chạy, không phải do tôi.

Theo cách làm của nhiệm vụ:

- Không deploy, cài đặt hay khởi động lại production.
- Không migrate production; không ghi hay xóa dữ liệu production.
- Không đổi thiết lập hay lịch production.
- Không chạy D-0 / D-1 / huấn luyện / forecast / publish / snapshot / chốt trên production.
- Không đổi URL / proxy / tunnel. File proxy không đổi từ `c15f767`, nên không cần khởi động lại proxy khi deploy.
- Không push.
- Không xóa gói hay backup nào.

Thao tác duy nhất chạm DB production là **đọc** để tạo bản sao (SQLite backup API, `mode=ro`), lúc 13:38, 13:49, 14:15 và 14:46.

**Giới hạn:**

- Không gửi lại POST/PUT qua link để thử 405 trong nhiệm vụ này. Dựa vào việc PID và file proxy không đổi, cùng kết quả 405/403 của chính file đó trong diễn tập.
- `GET /api/system/status` trên production là lệnh đọc, nhưng có thể mất hơn 60 s.

## H. Git

- Branch `main`, HEAD `2070ff2`; working tree sạch.
- Commit mới, tất cả cục bộ:
  - `6a65fa2`: code và test;
  - `d05ff97`: tài liệu. **Gói được build từ commit này**;
  - `80f8a88`: chỉ `docs/CHECKPOINT.md`, ghi release và diễn tập. Nằm sau gói, không có trong gói;
  - `2070ff2`: sửa một byte CR lạc trong dòng "Release" của `CHECKPOINT.md`, do lỗi escape khi ghi file. Chính message của commit này cũng dính một CR ở chữ `scripts\release.ps1`.
- Không amend, không reset, không push; `main` đi trước `origin/main` 22 commit.
- Báo cáo này và `checkpoints/` nằm ngoài Git (`reports/` bị ignore theo quy định).
- Bằng chứng tạm nằm trong `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p4\`:
  - `integ126b_copyB.json`, `release126.log`;
  - `iso126r_result.json`, `iso126r_result_run1.json`.

## I. Đề xuất deploy, khi chủ sở hữu duyệt

1. **Khung giờ:** 19:00–22:00, sau mốc D-0 18:00 và trước 23:55. Không có job đang chạy. Dự kiến khoảng 7 phút, gián đoạn khoảng 2 phút (đo trên bản sao).
2. **Kiểm tra trước:**
   - `scripts\deploy-upgrade.ps1 -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.6-win64-portable.zip" -ExpectedSha256 BBD73386D698A789A2A75DBECDC252ABCD7B1A5E26B98D8B3E35970A9A7F09C3 -CheckOnly`, chạy từ thư mục gói 1.2.6.
   - Dừng nếu SHA sai, có job đang chạy, hoặc thiếu chỗ trống.
3. **Deploy thật** bằng cùng lệnh với `-ConfirmToken UPGRADE-1.2.6`. Bước này ghi một backup online và một dòng audit trước khi hỏi xác nhận.
4. **Sau deploy** (chỉ đọc):
   - health 1.2.6, `db_version 6`;
   - `data-check` không FAIL;
   - `eod` / `close` TẮT;
   - D-1 / D-0 / huấn luyện như trên;
   - forecast `FCR-…798B4D`;
   - link 200; proxy không cần khởi động lại.
5. **Bật hai lịch:** chỉ khi chủ sở hữu cho phép, trên trang Lịch chạy dữ liệu. Snapshot đầu tiên chạy lúc 23:55 cùng ngày bật.
6. **Rollback nếu cần:**
   - `…\1.2.6\scripts\stop.ps1`;
   - `…\1.2.5\scripts\restore.ps1 -File "<đường dẫn đầy đủ của backup online>"`;
   - `…\1.2.6\scripts\rollback-version.ps1 -To 1.2.5 -ConfirmToken ROLLBACK-1.2.5`.

**Việc tiếp theo nhỏ nhất:** chủ sở hữu đọc báo cáo này và duyệt (hoặc từ chối) deploy 1.2.6 kèm khung giờ.
