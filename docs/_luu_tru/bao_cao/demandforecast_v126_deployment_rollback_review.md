# Rà soát kế hoạch deploy và rollback — Demand Forecasting 1.2.6

Ngày: 18/10/2026, rà soát lúc 12:53–13:05 (giờ Việt Nam). Chỉ đọc: không deploy, không khởi động lại, không chạy job,
không sửa mã, không push.

## Kết luận: **BLOCKED**

Kế hoạch chưa sẵn sàng để chủ sở hữu duyệt. Có hai quyết định đã duyệt mà bản 1.2.6 hiện tại chưa đáp ứng:

1. **Lưu giữ snapshot 90 ngày chưa được cài đặt.** Trigger của migration 0005 còn **cấm mọi lệnh xóa** snapshot.
   Xem B1.
2. **Hai lịch mới mặc định BẬT ngay khi deploy.** Quyết định là chỉ bật sau khi kiểm tra deploy đạt. Xem B2.

Ngoài ra còn ba việc phải làm trước khi deploy: chưa có gói 1.2.6, chưa diễn tập deploy/rollback 1.2.6 trên bản sao,
và còn một sai lệch nhỏ giữa tài liệu và mã về việc retry (F1).

Lộ trình gỡ chặn ngắn nhất ở mục 13.

| # | Tiêu chí (prompt) | Kết quả |
|---|---|---|
| 1 | Commit, working tree, phiên bản, nội dung gói | **BLOCKED** — commit và working tree đạt; chưa có gói 1.2.6 nên chưa kiểm được nội dung gói |
| 2 | Script deploy có ghi trước bước xác nhận không | **PASS (có ghi chú)** — `-CheckOnly` không ghi; chế độ thật **có ghi trước xác nhận**: log, file backup và 1 dòng `audit_log` (không phá hủy) |
| 3 | Bước backup trước deploy và kiểm tra toàn vẹn | **PASS** — 3 lớp backup, mỗi bản đều chạy `PRAGMA integrity_check` |
| 4 | Restore đã thử trên bản sao chưa | **BLOCKED** — đã thử cho 1.2.4↔1.2.5; **chưa** thử cho 1.2.6 |
| 5 | Migration tương thích ngược / rollback | **PASS (có điều kiện)** — 0005 chỉ thêm và đã kiểm trên bản sao; 1.2.5 **từ chối** DB schema 5 |
| 6 | Rollback mã có giữ được DB sau deploy không | **FAIL** — không có cách được kiểm chứng: rollback phải khôi phục backup trước nâng cấp |
| 7 | Snapshot / revision sau deploy được giữ thế nào khi rollback | **PASS (một phần)** — được giữ trong file `pre-restore` tự tạo, nhưng không còn trên hệ thống 1.2.5 |
| 8 | Scheduler: múi giờ, duy nhất, retry, idempotent, khởi động lại | **PASS** — có một sai lệch tài liệu về retry (F1) |
| 9 | Retention chỉ xóa snapshot hết hạn, có dry-run | **FAIL** — chưa có code retention; trigger cấm xóa |
| 10 | Kiểm tra sau deploy chỉ đọc | **PASS** |
| 11 | Checklist deploy có điểm dừng | **PASS** (mục 10) — chỉ thực hiện được sau khi gỡ B1–B4 |
| 12 | Checklist rollback bằng lệnh đã kiểm trong repo | **PASS** (mục 11) |
| 13 | Blocker và giả định | Mục 12 |
| 14 | Không ghi production, không deploy | **PASS** (mục 14) |

## 1. Nguồn bằng chứng

| Nguồn | Ghi chú |
|---|---|
| `reports/demandforecast_v125_eod_backup_actual_finalization.md` | Báo cáo triển khai 1.2.6; có tồn tại |
| Báo cáo **phát hành** 1.2.6 | **Không tồn tại**: 1.2.6 chưa được đóng gói hay phát hành. Không có nội dung nào được suy đoán thay thế. |
| Git | `ba74335` (tài liệu) ← `581fcdc` (mã + test) ← `d60f81e` (tài liệu 1.2.5, production) ← `c15f767` (gói 1.2.5 đang chạy). `main` đi trước `origin/main` 18 commit, sau 0; working tree sạch. `git diff d60f81e ba74335 -- scripts/` rỗng: script deploy, rollback và proxy không đổi. |
| Migration | `backend/app/migrations/0005_eod_backup_actual_close.sql`; 0001–0004 đã có trên production (schema 4) |
| Script | `scripts/deploy-upgrade.ps1`, `install.ps1`, `release.ps1`, `build-package.ps1`, `restore.ps1`, `backup.ps1`, `rollback-version.ps1`, `_common.ps1` |
| Mã | `backend/app/backup.py`, `db.py` (migrate), `cli.py` (backup / restore / data-check / storage-verify), `api/ops_routes.py` (POST backups), `jobs/scheduler.py`, `jobs/runner.py`, `settings_service.py`, `storage_migrate.py` |
| Log deploy 1.2.5 | `D:\Buymed\Lightgbm AI\logs\runtime\deploy-20261018-100109.log` (đọc) |
| Production (chỉ GET) | `/api/health`, `/api/system/status`, `/api/schedules`, `/api/jobs`, `/api/forecast-runs`, `/api/settings`; link: GET `/api/health`, `/api/history/overview`, `/api/schedules`, `/schedules`, `/api/system/backups`; POST/PUT chỉ để xác nhận proxy chặn (mục 14) |

## 2. Phiên bản, commit, gói (tiêu chí 1)

- **Mã nguồn:**
  - `backend/app/__init__.py` = `1.2.6`; `frontend/package.json` = `1.2.6`.
  - `build-package.ps1:21` lấy phiên bản từ `app.__version__` và ghi file `VERSION` ở dòng 146.
- **Nội dung gói dự kiến** (`build-package.ps1:134-146`):
  - toàn bộ `backend/app` (gồm `forecast_backup.py`, `actual_close.py`, `migrations/0005_…sql`), bỏ `__pycache__`;
  - `frontend/dist` → `web`, `docs`, `config`, `CHANGELOG.md`, `VERSION`, `BUILD-INFO.json` (commit, dirty, fingerprint).
- **`dist\` không có gói 1.2.6.** Gói mới nhất là `DemandForecast-1.2.5-win64-portable.zip` (bản đang chạy). Vì vậy chưa
  kiểm được SHA-256, danh sách file, hay việc không có credential. Hai bước này nằm sẵn trong `release.ps1` và trong
  precheck của `deploy-upgrade.ps1:36-37`.
- **`release.ps1`** đòi working tree sạch, chạy `run-tests.ps1`, rồi `build-package.ps1 -SkipFrontend`. Sau đó nó kiểm
  `.sha256`, `VERSION` và `BUILD-INFO.commit`, và chạy `prune-artifacts.ps1` ở chế độ dry-run (không xóa gì).
  - Script **không** kiểm tra đã push hay chưa.
  - `docs/GITHUB_WORKFLOW.md` §"Phát hành" ghi "Mã đã commit + push". Chủ sở hữu quyết định có cần push trước khi
    build hay không.

## 3. Script deploy: có ghi trước bước xác nhận không (tiêu chí 2)

**Với `-CheckOnly`: không ghi gì.** Các lệnh chạy trước `deploy-upgrade.ps1:75` đều chỉ đọc:
- SHA-256 và VERSION của zip;
- `app.cli paths` (không `--check`; chạy trước `setup_logging`, `cli.py`);
- `app.cli storage-verify` (`storage_migrate.verify_storage`, docstring "Read-only", không có lệnh ghi);
- GET `/api/health`, `/api/jobs`;
- dung lượng trống.

**Ở chế độ thật, các bước sau ghi TRƯỚC khi hỏi `UPGRADE-<version>` (`deploy-upgrade.ps1:90-93`):**

| Dòng | Ghi gì | Tính chất |
|---|---|---|
| 80 | `Start-Transcript` → `<logs>\deploy-<time>.log` | file log |
| 84 | `POST /api/system/backups` → `backup.backup_database("manual")` tạo `backup-<time>-manual.zip`, **và** `ops_routes.py:171-176` chèn 1 dòng `audit_log` `BACKUP_CREATED` vào **DB đang chạy** | không phá hủy, thêm 1 dòng audit |
| 89 | GET `/api/system/status` | đọc |

Không có thao tác dừng, cài hay migrate trước bước xác nhận. Nếu người vận hành không xác nhận, chỉ còn lại file log,
1 bản backup và 1 dòng audit.

**Sau khi xác nhận (`install.ps1`), thứ tự thực tế:**
1. `install.ps1:30` storage-verify;
2. `:78` dừng app;
3. **`:104` `app.cli backup` của gói mới.** `cli.py:203-205` gọi `db.migrate()` *trước* khi backup:
   - `db.py:109` tạo `backup-<time>-pre-migration-v4.zip`;
   - `db.py:113-120` áp dụng 0005 trong một transaction;
   - sau đó tạo `backup-<time>-cli.zip`;
4. `:115-119` sao chép thư mục chương trình;
5. `:121` `migrate` (không còn gì để áp dụng);
6. `:126` ghi `current.txt`;
7. `:144` khởi động.

Log deploy 1.2.5 xác nhận đúng thứ tự này: `pre-migration-v3`, "migration applied 0004", `…-cli.zip`, rồi
`"applied": []`.

**Rủi ro R2 — schema đổi trước khi chép chương trình.** Nếu cài thất bại sau bước 3 (ví dụ khi chép file), `Stop-Install`
sẽ khởi động lại 1.2.5 (`install.ps1:53-63`). Nhưng 1.2.5 từ chối DB schema 5 (`db.py:101-104`), nên app sẽ **không lên**.
Khi đó phải đi theo checklist rollback ở mục 11. Đây là hành vi có sẵn từ các bản trước, không do 1.2.6 gây ra.

## 4. Backup trước deploy và kiểm tra toàn vẹn (tiêu chí 3)

| Bản backup | Tạo bởi | Kiểm tra |
|---|---|---|
| `backup-<time>-manual.zip` | `deploy-upgrade.ps1:84`, lúc app còn chạy (backup API, nguồn `mode=ro`) | `backup.py:29-35`: `PRAGMA integrity_check = ok` và số bảng > 0 trên bản sao, nếu không thì không ghi file. `deploy-upgrade.ps1:86-88`: zip phải có `db/app.db`, và script in SHA-256 |
| `backup-<time>-pre-migration-v4.zip` | `db.py:107-109`, ngay trước 0005 | như trên |
| `backup-<time>-cli.zip` | `cli.py:204-205`, sau migrate | như trên |

Mỗi zip chứa `db/app.db` và các file model. Hiện có 77,0 GB trống trên ổ D:, DB 534 MB, mỗi backup khoảng 65 MB;
precheck đòi tối thiểu 3 × DB + 2 × gói.

**Kiểm tra thêm (chỉ đọc) nên làm sau khi tạo:**
- ghi lại SHA-256 của `-manual.zip` và `-pre-migration-v4.zip`;
- mở bản `pre-migration-v4` vào thư mục scratch và chạy `PRAGMA integrity_check`, `schema_migrations` = 4, đếm dòng
  các bảng chính;
- so số dòng đó với mốc trước deploy.

## 5. Restore đã được thử trên bản sao chưa (tiêu chí 4)

- **1.2.4 ↔ 1.2.5: ĐÃ thử** (`docs/CHECKPOINT.md`, dòng "Rehearsal DONE 28/28"):
  - `rollback-version -CheckOnly` từ chối vì schema 4;
  - khôi phục backup trước nâng cấp bằng 1.2.4 rồi `rollback-version -To 1.2.4`: OK.
- **1.2.5 ↔ 1.2.6: CHƯA thử.** Kiểm thử tích hợp 1.2.6 trên bản sao chỉ chạy migrate 4→5 (bản `pre-migration-v4` được
  tạo và đạt `integrity_check`). Chưa restore bản đó, chưa chạy `deploy-upgrade` của gói 1.2.6, chưa chạy
  `rollback-version -To 1.2.5`. Đây là **B4**.

`restore` (`backup.py:56-90`, `cli.py:206-217`) làm theo thứ tự:
1. từ chối nếu app đang chạy;
2. **tự tạo `backup-<time>-pre-restore.zip` của DB hiện tại**;
3. giải nén vào `.restoring`;
4. `integrity_check`;
5. xóa `-wal` / `-shm` rồi thay DB;
6. ghi đè file model cùng tên (không xóa model mới);
7. `db.migrate()` **bằng phiên bản đang dùng để restore**.

Vì bước 7 nên **phải dùng `restore.ps1` của thư mục 1.2.5**. Nếu dùng `restore.ps1` của 1.2.6, DB vừa khôi phục sẽ bị
migrate lại lên schema 5.

## 6. Migration (tiêu chí 5)

- **Đã có trên production:** 0001–0004 (schema 4, GET `/api/system/status` `db_version`; bản sao 12:00:32). Chỉ 0005
  là mới.
- **0005 chỉ thêm:**
  - 4 bảng mới, 11 trigger (chỉ trên bảng mới), 1 chỉ mục;
  - không `ALTER` / `DROP`, không chạm bảng cũ;
  - chạy trong một transaction `BEGIN IMMEDIATE` (`db.py:113-120`): lỗi thì `ROLLBACK`, DB giữ schema 4, có backup.
- **Bằng chứng trên bản sao DB production (báo cáo 1.2.6, mục 7 và 9):**
  - fingerprint sha256 của 8 bảng giống hệt trước và sau;
  - migrate lần hai không áp dụng gì;
  - `data-check`: cùng kết quả WARN có sẵn (`forecast_series_meta`); 3 kiểm tra mới OK.
- **Không tương thích ngược với mã cũ:** 1.2.5 gặp DB schema 5 thì dừng (`MigrationError`, `db.py:101-104`), và
  `rollback-version.ps1:21-25` từ chối.
- **Settings:** khóa mới (`eod_*`, `close_*`) nằm trong JSON của `app_settings.schedule` *chỉ khi* một lần lưu lịch xảy
  ra dưới 1.2.6. 1.2.5 đọc bằng pydantic, mặc định bỏ qua khóa lạ (`settings_service.get`, không có
  `extra="forbid"`), nên không hỏng nếu DB đó được giữ.
- **Job / audit / alert:** dòng `job_runs` loại mới bị scheduler 1.2.5 bỏ qua khi retry (`runner.JOB_TYPES`). Mã alert
  và audit mới chỉ hiện dạng mã trên 1.2.5.

## 7. Rollback mã và dữ liệu sau deploy (tiêu chí 6, 7)

- **Rollback mã mà giữ nguyên DB sau deploy: KHÔNG có cách được kiểm chứng.** `rollback-version.ps1` từ chối khi schema
  5 > 4. Cách duy nhất có trong repo là khôi phục backup trước nâng cấp, nên **mất mọi dữ liệu ghi sau deploy**:

  | Dữ liệu ghi sau deploy | Lấy lại được không |
  |---|---|
  | Snapshot D-0 trong ngày | **Không** — đọc theo thời điểm, không đọc lại được |
  | Lần nạp D-1 | Có — D-1 / backfill từ BigQuery |
  | Huấn luyện, duyệt model, forecast publish sau deploy | Dòng DB **mất**; file model vẫn còn trong thư mục models (mồ côi) |
  | Thay đổi lịch hoặc thiết lập, job, audit, alert | Mất |
  | Lịch sử D+1 ghi sau deploy | Ghi lại được từ forecast run, nếu run còn trong DB |
  | Snapshot EOD và bản chốt thực tế | Mất khỏi DB đang chạy (xem dòng dưới) |

- **Snapshot và revision sau deploy được giữ ở đâu:** `restore` tự tạo `backup-<time>-pre-restore.zip` chứa **toàn bộ DB
  schema 5 ngay trước khi khôi phục** (`backup.py:69-70`). Không có gì bị xóa hẳn. Nhưng không có công cụ nào nhập lại
  hay hợp nhất dữ liệu đó vào DB 1.2.5. Chỉ có thể dùng lại bằng cách khôi phục cả file khi deploy lại 1.2.6, và khi
  đó dữ liệu ghi dưới 1.2.5 trong lúc chờ sẽ mất.
- **Cách hạ schema giữ dữ liệu khác** (`DROP` 4 bảng của 0005, xóa `schema_migrations` version 5): **không có script
  trong repo, chưa kiểm, là thao tác phá hủy**, cần phê duyệt riêng (`docs/LICH-SU-FORECAST.md` §9).
- **Mức xử lý nhẹ nhất khi lỗi chỉ nằm ở hai job mới:** tắt flow `eod` / `close` tại trang Lịch chạy dữ liệu. Không mất
  dữ liệu, giữ 1.2.6. Việc tắt là một lần ghi thiết lập production, cần chủ sở hữu duyệt lúc đó.

## 8. Scheduler (tiêu chí 8)

| Mục | Bằng chứng | Kết quả |
|---|---|---|
| Múi giờ | `vn_slot(d, hhmm)` dùng `ZoneInfo("Asia/Ho_Chi_Minh")`. Ngày nghiệp vụ = ngày của mốc (`params.business_date`, `scheduler.py:146-153`), được lưu trong `job_runs.result_json` và nạp lại khi retry. Test: 19/10 03:00 giờ VN (vẫn là 18/10 UTC) chốt ngày 18/10; 00:10 vẫn chốt ngày hôm trước. | PASS |
| Duy nhất | Mỗi tiến trình có một scheduler (`main.py:48`). Một thư mục dữ liệu chỉ có một server (`cli.py:192` `ALREADY_RUNNING`). Mỗi mốc là một khóa `job_runs.idempotency_key` UNIQUE (`get_or_create` trong `BEGIN IMMEDIATE`). Bảng có UNIQUE (scope, ngày) / (scope, ngày, revision). Test: hai scheduler cùng tick → 1 job; 4 luồng đồng thời → 1 snapshot / 1 revision. | PASS |
| Retry | Mặc định production: `max_attempts` 4, backoff 60 → 1.800 s, timeout 3.600 s, grace 20 phút, 1 lần chạy bù mỗi tick (GET `/api/settings`). Lỗi tạm thời (ví dụ DB bị khóa) → `JOB_ERROR` → retry. Chờ phụ thuộc (`Wait`) không tốn lượt thử và có giới hạn (EOD tới 06:00 hôm sau, chốt 1 giờ). | PASS — **F1:** `AppError` không retry trừ BQ (`runner.py:201`), nên `EOD_SNAPSHOT_VERIFY_FAILED` cho job FAILED kèm alert ERROR, **không** "thử lại" như `messages.py` và `LICH-SU-FORECAST.md:186` viết. Hành vi an toàn (không ghi gì), nhưng tài liệu sai. |
| Idempotent | Snapshot COMPLETE không đổi (trigger); bản chốt revision 1 chỉ một lần; đối soát không đổi thì không ghi. Có test. | PASS |
| Khởi động / khởi động lại | `recover_interrupted()`: job RUNNING → RETRY_WAIT hoặc FAILED. `flows_first_seen` (`scheduler.py:262`) ghi một lần, nên mốc trước lần tick đầu của 1.2.6 không bao giờ chạy và không tạo bản cho ngày cũ. Mốc hôm qua bị lỡ chạy bù một lần; ngày cũ hơn ghi `MISSED_SLOT_NO_BACKFILL`. Có test. | PASS |
| Không đụng lịch cũ | Test `plan()` của D-0 / D-1 / huấn luyện không đổi. Lịch production được giữ (mục 12). | PASS |
| Bật / tắt | Mặc định `eod_enabled = close_enabled = True` (`settings_service.py:188-193`). Production chưa lưu khóa này (`has_eod_keys = False`), nên **sau deploy, hai flow BẬT ngay**; lần chạy đầu là 23:55 / 23:59 của ngày deploy. **Mâu thuẫn với quyết định "bật sau khi kiểm tra đạt" → B2.** | FAIL so với quyết định |

**Thời điểm deploy an toàn** (lịch production hiện tại):
- tránh 08:00–18:05 mỗi 2 giờ (D-0);
- tránh 03:00–khoảng 06:00 (D-1 chờ tín hiệu, dự phòng 05:00, retry);
- tránh 09:00 (huấn luyện);
- sau deploy, tránh 23:55–00:15.

Khung gợi ý: **19:00–22:00**, sau khi job D-0 18:00 xong và không có job đang chạy.

## 9. Retention 90 ngày (tiêu chí 9) — **FAIL / chưa cài đặt**

- 1.2.6 **không có** mã xóa snapshot, không có chế độ dry-run / đếm, không có lịch dọn.
- Migration 0005 có `trg_fes_no_delete` (dòng 55) và `trg_fes_values_no_delete` (dòng 64): **mọi** `DELETE` đều bị chặn.
- `prune-artifacts.ps1` chỉ xử lý gói trong `dist\`, không liên quan DB.
- Cài retention cần một **migration mới (0006)** thay trigger cấm xóa bằng trigger có điều kiện, cùng mã dọn có dry-run.
  Đó là bản phát hành mới (1.2.7 hoặc 1.2.6 trước khi đóng gói), phải qua test và rà soát lại.
- **Yêu cầu tối thiểu cho thiết kế retention** (để đáp ứng tiêu chí "chỉ xóa snapshot hết hạn, không bao giờ xóa snapshot
  đang được tham chiếu hay forecast nguồn"):
  1. **Hết hạn:** `business_date < hôm nay − 90` (giờ VN).
  2. **"Đang tham chiếu":** snapshot S là nguồn dự phòng của các ngày chạy S…S+6 không có phiên chính. Để màn hình
     không mất dự phòng của ngày còn trong 90 ngày, chỉ xóa khi `business_date + 6 < hôm nay − 90`, hoặc chỉ xóa
     những snapshot không phải nguồn của bất kỳ ngày nào trong `fallback_days` ở khung 90 ngày.
  3. **Hệ quả nghiệp vụ cần chủ sở hữu chấp nhận:** ngày chạy cũ hơn khoảng 90 ngày từng dùng dự phòng sẽ thành **khoảng
     trống** trên màn hình lịch sử (khoảng ngày cho phép tới 400 ngày). Phương án giữ lại: trước khi xóa, chép riêng dòng
     D+1 đã dùng (khoảng 17 nghìn dòng / ngày thay vì 120 nghìn).
  4. Chỉ được chạm `forecast_eod_snapshot*`. `forecast_values` / `forecast_history_*` có trigger bất biến riêng, nên
     không xóa được dù có lỗi.
  5. Bắt buộc có chế độ đếm / dry-run (in danh sách snapshot sẽ xóa, số dòng, dung lượng); ghi `audit_log`; xóa trong
     một transaction; cập nhật `data-check`.
  6. Có quyết định cho dòng đầu mục: xóa hẳn, hay giữ với trạng thái `EXPIRED`. Giữ thì phải đổi CHECK status, tức
     phải dựng lại bảng.
- **Không deploy retention thì sao:** snapshot đầu tiên chỉ quá 90 ngày sau khoảng 3 tháng kể từ deploy, khoảng 11,8 MB
  mỗi ngày. Có thể **hoãn** retention sang bản sau nếu chủ sở hữu chấp nhận rõ ràng; khi đó B1 thành điều kiện có hạn
  chót.

## 10. Checklist deploy (chỉ chạy khi chủ sở hữu duyệt kế hoạch cuối)

Mỗi bước có điểm dừng: **gặp điều kiện dừng thì dừng hẳn, không làm tiếp, báo lại.**

**A. Trước ngày deploy**

1. **Gỡ B1, B2 và F1 bằng commit mới** (không amend):
   - mặc định `eod_enabled = close_enabled = False`;
   - sửa văn bản retry ở `messages.py` và `LICH-SU-FORECAST.md`;
   - retention 90 ngày có dry-run (hoặc chủ sở hữu ký hoãn).
   - Chạy QA đầy đủ và rà soát lại.
   - *Dừng nếu:* bất kỳ test nào lỗi.
2. **Build gói:** `powershell -ExecutionPolicy Bypass -File scripts\release.ps1`. Push trước khi build là quyết định của
   chủ sở hữu.
   - *Dừng nếu:* QA lỗi, `.sha256` lệch, `VERSION` hoặc `BUILD-INFO.commit` khác commit đã duyệt.
3. **Diễn tập trên bản sao chỉ đọc** (backup API `mode=ro`; `LOCALAPPDATA` / `DF_DATA_DIR` riêng; cổng khác 8765;
   scheduler tắt), giống cách diễn tập 1.2.5:
   - cài 1.2.5 chính thức;
   - `deploy-upgrade.ps1 -CheckOnly`, rồi deploy gói 1.2.6;
   - kiểm tra schema 5, số dòng và fingerprint không đổi, `data-check`, trang Lịch, lịch sử;
   - rollback: `rollback-version.ps1 -To 1.2.5 -CheckOnly` phải **từ chối**;
   - restore `pre-migration-v4` bằng `restore.ps1` **của 1.2.5**, rồi `rollback-version.ps1 -To 1.2.5`;
   - xác nhận 1.2.5 chạy với schema 4 và file `pre-restore` chứa schema 5.
   - *Dừng nếu:* bất kỳ bước nào không như trên.

**B. Ngày deploy** (khung 19:00–22:00, không có job đang chạy)

4. **Ghi mốc chỉ đọc:**
   - `GET /api/health` = 1.2.5; `current.txt` = 1.2.5; hash `storage.json`;
   - `GET /api/schedules` (5 giá trị ở mục 13), `GET /api/settings` (hash từng phần ở mục 13);
   - forecast mới nhất `FCR-20261018043737-798B4D`; `app.cli data-check`; tiến trình proxy và cloudflared;
   - link: GET 200, POST 405, `/api/system/backups` 403.
5. **Precheck:**
   `powershell -ExecutionPolicy Bypass -File scripts\deploy-upgrade.ps1 -Package "<dist>\DemandForecast-1.2.6-win64-portable.zip" -ExpectedSha256 <SHA> -CheckOnly`
   - *Dừng nếu:* bất kỳ dòng `[FAIL]` nào, hoặc có job PENDING / RUNNING.
6. **Deploy:** cùng lệnh, bỏ `-CheckOnly`, thêm `-ConfirmToken UPGRADE-1.2.6`.
   - Chạy bằng `Start-Process` và chuyển hướng ra file, **không pipe** (server mới kế thừa handle và làm treo).
   - Link sẽ trả 502 khoảng 1,5–3 phút.
   - *Dừng nếu:* `UPGRADE STOPPED`, hoặc app không lên. App không lên sau khi migrate (R2) thì đi ngay checklist
     rollback mục 11.
7. **Kiểm tra sau deploy, chỉ đọc** (mục 15):
   - phiên bản 1.2.6; `db_version` 5; `storage.json` cùng hash;
   - nguồn đang dùng BIGQUERY; forecast mới nhất không đổi;
   - lịch D-1 03:00 / 05:00, D-0 08–18, huấn luyện 09:00 giống mốc;
   - `data-check` không FAIL;
   - `/api/history/*` qua localhost và qua link; POST qua link 405;
   - proxy và cloudflared cùng PID (proxy không cần khởi động lại vì `readonly_proxy.py` không đổi);
   - `eod` / `close` đang **TẮT** (sau khi gỡ B2).
   - *Dừng nếu:* bất kỳ mục nào khác mốc. Tùy mức độ, rollback theo mục 11.

**C. Bật lịch (chỉ sau khi bước 7 đạt)**

8. Bật `eod`, rồi `close`, trên trang Lịch chạy dữ liệu **ở máy chủ** (qua link bị 405).
   - Đây là lần ghi thiết lập production, cần chủ sở hữu duyệt lúc đó.
   - Hệ thống ghi `eod_enabled_at` / `close_enabled_at` = thời điểm bật; chỉ các mốc sau thời điểm đó mới chạy.
   - Kiểm tra bằng `GET /api/schedules`: `state = ON`, lần chạy kế tiếp 23:55 / 23:59.
   - Lịch D-0 / D-1 / huấn luyện không đổi.
9. **Theo dõi đêm đầu (chỉ đọc):**
   - 23:55: job `EOD_FORECAST_SNAPSHOT:<ngày>` SUCCEEDED, snapshot `COMPLETE`, khoảng 119.889 dòng;
   - 23:59: `ACTUAL_CLOSE:<ngày>` SUCCEEDED, `CLOSED_UNVERIFIED`;
   - sáng hôm sau, màn hình lịch sử hiện "Đã chốt – cần xác minh";
   - sau khi D-1 thành công: revision `D1_LOADED`;
   - `data-check` 3 kiểm tra mới OK.
   - *Dừng / tắt flow nếu:* job FAILED, snapshot INCOMPLETE ngoài dự kiến, hoặc alert ERROR.

## 11. Checklist rollback (lệnh đã kiểm trong repo và thư mục 1.2.5 đã cài)

**Mức 0 — không mất dữ liệu.** Lỗi chỉ ở hai job mới: tắt `eod` và `close` tại trang Lịch chạy dữ liệu, giữ 1.2.6.

**Mức 1 — về 1.2.5, mất mọi dữ liệu ghi sau deploy** (mục 7):
1. Ghi mốc chỉ đọc: health, `GET /api/jobs` (không có job RUNNING), danh sách backup.
2. Chọn bản khôi phục: `backup-<time>-pre-migration-v4.zip` của lần deploy, hoặc `-manual.zip` (trước nâng cấp). Ghi
   SHA-256.
3. Dừng app: `& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.6\scripts\stop.ps1"`.
4. Khôi phục **bằng bản 1.2.5**, với đường dẫn đầy đủ:
   `& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.5\scripts\restore.ps1" -File "D:\Buymed\Lightgbm AI\backups\backup-<time>-pre-migration-v4.zip"`
   - Lệnh này tự tạo `backup-<time>-pre-restore.zip` chứa DB schema 5 (giữ snapshot và bản chốt).
   - *Dừng nếu:* lỗi `integrity_check`, hoặc báo app còn chạy.
5. Kiểm tra (`-CheckOnly` chỉ đọc DB, không ghi): `& "...\1.2.5\scripts\rollback-version.ps1" -To 1.2.5 -CheckOnly` →
   phải báo schema 4 / hỗ trợ 4, `[OK]`.
6. `& "...\1.2.5\scripts\rollback-version.ps1" -To 1.2.5 -ConfirmToken ROLLBACK-1.2.5`. Lệnh này khởi động 1.2.5, ghi
   `current.txt`, và kiểm `/api/health` = 1.2.5.
7. Kiểm tra chỉ đọc như mục 10 bước 7 (phiên bản 1.2.5, schema 4, lịch, link 200 / 405, `data-check`).
8. Lấy lại phần lấy lại được: D-1 bằng lần chạy D-1 kế tiếp hoặc backfill. Báo cho chủ sở hữu phần đã mất (D-0 trong
   ngày, forecast / duyệt model sau deploy).

**Mức 2 — hạ schema giữ dữ liệu khác:** chưa có script, chưa kiểm, cần phê duyệt riêng. Không đưa vào kế hoạch.

## 12. Giữ nguyên trạng thái production

Mốc đọc lúc 12:53–12:57:

| Mục | Mốc | Cách kiểm sau deploy |
|---|---|---|
| Phiên bản | 1.2.5 (`/api/health`, `current.txt`) | 1.2.6 sau deploy; 1.2.5 sau rollback |
| URL | `https://volumes-jean-angels-configurations.trycloudflare.com`: GET `/api/health` 200 | Như cũ; cloudflared PID 31076 không đổi |
| Proxy (8766) | pid 26416; POST `/api/history/summary` → 405, PUT `/api/schedules/eod` → 405, GET `/api/system/backups` → 403 | Như cũ; không khởi động lại proxy |
| App | cổng 8765, pid 22024, nguồn BIGQUERY, scope `…demand_planing_lightgbm` | Cùng cổng; nguồn và scope không đổi |
| Forecast / model | mới nhất `FCR-20261018043737-798B4D` (`MV-20261018-092617-2DB8`) | Không đổi |
| Lịch D-1 | BẬT 03:00, dự phòng 05:00, poll 30 phút, `enabled_at` 2026-10-17 23:06:27 | Không đổi |
| Lịch D-0 | BẬT 08/10/12/14/16/18:00, `LATEST_ONCE` | Không đổi |
| Huấn luyện | BẬT 09:00, `SKIP` | Không đổi |
| Chính sách | `max_attempts` 4, retry 60–1.800 s, timeout 3.600 s, grace 20 phút, 1 lần chạy bù / tick | Không đổi |
| Hash thiết lập (sha256 16 ký tự, GET `/api/settings`) | bigquery `79bd7627bd7c29ac`, data_policy `9a3a0ad94f963ff7`, general `5bc593cfd0c273e6`, horizons `de05a010dc626ed5`, import `a7f4e0919b1d5433`, model `f99df46563deab1a`, quality `f2951287cfd24c05`, sql_sources `252ed79fa3059ac6`, schedule `014bf900fc527dd1` | Mọi phần giống hệt, **trừ `schedule`**: 1.2.6 trả thêm khóa mặc định `eod_*` / `close_*`. Với `schedule`, so các khóa cũ. |
| `storage.json` | hash `8D79DBDD…` | Không đổi |
| Tín hiệu hoàn tất BigQuery | `completion_table` rỗng (chưa cấu hình) | Giữ nguyên; không tự tạo |

## 13. Blocker và giả định

**Blocker:**
- **B1 — Retention 90 ngày (đã duyệt) chưa có.** Cần migration 0006 + mã dọn có dry-run + test + rà soát (mục 9), hoặc
  chủ sở hữu ký **hoãn** có hạn chót (trước khi snapshot đầu tiên quá 90 ngày).
- **B2 — Hai flow mặc định BẬT.** Quyết định là chỉ bật sau khi kiểm tra đạt. Hai cách gỡ:
  - đổi mặc định sang TẮT (khuyến nghị);
  - hoặc chủ sở hữu chấp nhận bước "tắt ngay sau deploy rồi bật lại sau kiểm tra" — thêm 2 lần ghi thiết lập; mốc đầu
    23:55 nên không chạy gì nếu deploy ban ngày.
- **B3 — Chưa có gói 1.2.6.** Cần duyệt build (`release.ps1`) và quyết định có push trước hay không.
- **B4 — Chưa diễn tập deploy và rollback 1.2.6** trên bản sao (mục 10 bước 3).

**Rủi ro / điều kiện (không chặn nếu chủ sở hữu chấp nhận):**
- **R1 — `deploy-upgrade` ghi trước bước xác nhận:** 1 backup, 1 dòng audit `BACKUP_CREATED`, file log. Không phá hủy.
- **R2 — Schema đổi trước khi chép chương trình** (`install.ps1:104`). Cài lỗi sau đó thì 1.2.5 không tự lên lại; phải
  rollback mức 1.
- **R3 — Rollback mức 1 mất dữ liệu ghi sau deploy**, gồm D-0 trong ngày (không đọc lại được) và forecast / duyệt model
  sau deploy (mục 7).
- **R4 — Dung lượng:** khoảng 11,8 MB/ngày (đo trên bản sao). Với retention 90 ngày là khoảng 1,1 GB snapshot; backup
  lớn lên tương ứng (còn 77 GB trống).
- **R5 — "Dữ liệu sau 18:00 được đối soát qua D-1 hôm sau"** phụ thuộc D-1 thành công. Lịch D-1 03:00 / 05:00 của chủ
  sở hữu có thể gặp `SOURCE_INCOMPLETE` (nguồn từng được làm mới quanh trưa D+1, ngày 18/10). Khi đó revision chỉ có
  sau lần D-1 thành công (thủ công hoặc hôm sau). Cửa sổ đối soát là 14 ngày.
- **R6 — F1:** văn bản retry sai (mục 8). Sửa trong commit gỡ B2.
- **R7 —** Qua link chỉ đọc, trang và API Lịch xem được (GET 200), nên sẽ thấy 2 flow mới; mọi thay đổi bị chặn 405.

**Giả định:**
- Mỗi lần deploy chỉ có một người vận hành.
- Không có app thứ hai dùng cùng thư mục dữ liệu.
- Bản 1.2.5 trong `%LOCALAPPDATA%\Programs\DemandForecast\1.2.5` được giữ nguyên làm đích rollback (đã kiểm có
  `restore.ps1`, `stop.ps1`, `start.ps1`, `rollback-version.ps1` và migration 0001–0004).

**Lộ trình gỡ chặn ngắn nhất:**
1. Chủ sở hữu quyết định B1 (cài ngay hay hoãn có hạn chót) và B2 (đổi mặc định TẮT hay dùng bước tắt/bật).
2. Một commit mới cho B2, F1 và B1 (nếu cài ngay); QA; rà soát.
3. `release.ps1`.
4. Diễn tập trên bản sao (B4).
5. Rà soát lại kế hoạch này, cập nhật SHA-256 gói.
6. Chủ sở hữu duyệt deploy.

## 14. Xác nhận không ghi production, không deploy

- **Không có** deploy, khởi động lại, push, build hay xóa gói, sửa mã, chạy job (D-0, D-1, huấn luyện, forecast,
  publish, snapshot, chốt), hay sửa thiết lập / lịch / DB production.
- **Truy cập production chỉ gồm:**
  - GET localhost: `/api/health`, `/api/system/status`, `/api/schedules`, `/api/jobs`, `/api/forecast-runs`,
    `/api/settings`;
  - GET qua link: `/api/health`, `/api/history/overview`, `/api/schedules`, `/schedules`, `/api/system/backups`;
  - đọc file: log deploy 1.2.5, danh sách `backups\` và `dist\`, `current.txt`;
  - `python -c` của 1.2.5 chỉ gọi `paths.describe()`.
- **Hai yêu cầu ghi gửi tới proxy để xác nhận nó chặn:** `POST /api/history/summary` → 405, `PUT /api/schedules/eod`
  (không body) → 405.
  - Proxy phân loại và chặn trước khi chuyển tiếp (`readonly_proxy.classify`, test `test_remote_proxy_*`).
  - Kể cả nếu được chuyển tiếp, 1.2.5 cũng không có thao tác ghi tương ứng: `/api/history/summary` chỉ có GET;
    `/api/schedules/eod` không có flow `eod` nên trả 404 trước khi ghi.
- **File được tạo:** chỉ báo cáo này (`reports/`, không thuộc Git). Không commit.

## 15. Kiểm tra sau deploy (chỉ đọc, tiêu chí 10)

| Kiểm tra | Lệnh | Vì sao chỉ đọc |
|---|---|---|
| Phiên bản, sức khỏe | `GET /api/health`, `GET /api/system/status` | GET |
| Lịch, trạng thái flow | `GET /api/schedules` | GET (`flows.overview`, không chạy job) |
| Job | `GET /api/jobs?limit=20` | GET |
| Lịch sử, dự phòng, chốt | `GET /api/history/overview`, `/summary`, `/rows` | GET; tài liệu "không bao giờ ghi" được test xác nhận bằng đếm 14 bảng trước/sau |
| Bất biến dữ liệu | `& "<1.2.6>\python\python.exe" -X utf8 -m app.cli data-check` (với `PYTHONPATH=<1.2.6>\backend`) | `data_checks.run` mở DB `mode=ro`; lệnh chạy trước `setup_logging` (`cli.py`) |
| Lưu trữ | `app.cli storage-verify` | `verify_storage` chỉ đọc |
| Link / proxy | GET `/api/health` 200; POST 405; `/api/system/backups` 403 | Proxy chặn ghi |
