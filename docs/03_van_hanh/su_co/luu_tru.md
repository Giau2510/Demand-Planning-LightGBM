# Sự cố lưu trữ (storage.json, di chuyển dữ liệu)

Điều tra storage.json, sửa lưu trữ, nâng cấp an toàn và dọn lưu trữ 14–16/10/2026.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\demandforecast_fix_storage_report_20261014_102811.md` (MAIN) | 14/10/2026 | 16982 | `E2D5AE37A3D661831FDAC23FE0190DE3BA047C0F55D6E8907BDF79CEFB9FC6E6` |
| 2 | `reports\demandforecast_storage_release_20261016.md` (MAIN) | 16/10/2026 | 7278 | `20DBD319917B65691AA72EEF6B012517A8D4E6EDCC19A7EC866A843988FA2AA3` |
| 3 | `reports\storage_cleanup_plan_20261016.md` (MAIN) | 16/10/2026 | 5060 | `A960398922F9608BCEA4D73315A6735C3235B573EFF7C6C334169C6A9B54A3BC` |
| 4 | `reports\storage_json_investigation_20261014_121904.md` (MAIN) | 14/10/2026 | 10552 | `E63438932071E54977F827C85E57E63BDB447B50ADCCD4DA79B4DBF8B59D20B3` |
| 5 | `reports\upgrade_storage_fix_report_20261014_144908.md` (MAIN) | 14/10/2026 | 13385 | `A081984AD874EBE0797B0F24666B44EF4C2E577A67DA486129AD2B69CD02B53F` |

## 1. Báo cáo: sửa lỗi tạo Demo + chuẩn hóa lưu trữ + di chuyển dữ liệu (v1.1.0)

Nguồn: `reports\demandforecast_fix_storage_report_20261014_102811.md` (worktree MAIN).

Ngày: 2026-10-14 · Phiên bản: 1.0.0 → **1.1.0** · Thư mục dự án: `D:\Buymed\Lightgbm AI`

**Kết luận:** các tiêu chí nghiệm thu đã đạt, có bằng chứng từ lệnh đã chạy thật (mục 9).
Trong quá trình làm có **một sự cố do tôi gây ra**: test đã ghi nhầm vào database thật. Sự cố đã được khôi phục
hoàn toàn, không mất dữ liệu (mục 0).

---

### 0. Sự cố trong lúc thực hiện (đã khắc phục)

- **10:09**: tôi chạy smoke test E2E của gói 1.1.0. Tôi chỉ cô lập `DF_STORAGE_CONFIG` mà quên rằng thư mục dữ liệu
  mặc định vẫn là `%LOCALAPPDATA%\DemandForecast`. Kết quả là test đã ghi vào **database thật**: đổi nguồn,
  tạo Demo 2 lần, huấn luyện và publish 1 forecast.
- Bản kiểm kê đầu phiên của tôi báo nhầm "app không chạy". Thực tế bản 1.0.0 của bạn **đang chạy** (pid 19024,
  từ 09:19). Trong lúc test có hai server cùng mở một DB, và `runtime.json` của bản 1.0.0 bị ghi đè.
- **Khắc phục:**
  1. Dừng bản 1.0.0. Không tắt êm qua API được vì token tắt đã bị ghi đè; SQLite WAL vẫn an toàn khi dừng tiến trình.
  2. Đối chiếu ba trạng thái: bản kiểm kê A, backup tự động `backup-20261014-100928-pre-migration-v1.zip`
     (ứng dụng tự tạo ngay trước khi nâng schema) và DB hiện tại. Kết quả: **mọi thay đổi sau 03:09:28Z đều do test**.
     Các thay đổi của bạn trước mốc đó đều nằm trong backup: cấu hình horizons lúc 02:41, schedule lúc 03:03,
     snapshot D0 lúc 10:00.
  3. Khôi phục backup đó bằng `app.cli restore`. Trước khi khôi phục đã tạo bản an toàn
     `backup-20261014-101210-pre-restore.zip`. Sau khôi phục, mọi bảng **giống hệt từng dòng** so với backup
     (khác duy nhất: thêm dòng `schema_migrations` v2). `integrity_check` ok, `foreign_key_check` rỗng.
  4. File mô hình do test tạo được chuyển (không xóa) vào
     `%LOCALAPPDATA%\DemandForecast\backups\quarantine-test-artifacts-20261014\`.
- **Chặn tái diễn:**
  - Phase ghi dữ liệu của `smoke_test.py` giờ bắt buộc `--test-data-dir` và phải khớp với thư mục dữ liệu của app.
  - `serve` từ chối khởi động nếu đã có instance khác dùng cùng thư mục dữ liệu (`ALREADY_RUNNING`).
  - `stop.ps1` chỉ dừng tiến trình python.
  - Các lần E2E sau được cô lập bằng cách đổi `LOCALAPPDATA` sang thư mục tạm.

### 1. Nguyên nhân gốc lỗi `FOREIGN KEY constraint failed`

**Bằng chứng:**
- `logs\server.err.log` (bản 1.0.0): lần tạo Demo đầu lúc 02:21:18 thành công; lần thứ hai lúc 02:22:57 lỗi tại `demo.py:125`.
- Schema: `PRAGMA foreign_key_list(import_batches)` cho thấy `replaced_by_batch_id → import_batches.id`.
  Ràng buộc này được kiểm tra **ngay** khi ghi (không deferred).
- Tái hiện bằng chính mã 1.0.0 đã cài, trên DB tạm: `1st OK`, `2nd FAILED: IntegrityError FOREIGN KEY constraint failed`.

**Cơ chế:** khi đã có một lô DEMO ACTIVE, `create_demo_batch` chạy
`UPDATE … SET replaced_by_batch_id = <ID lô mới>` **trước khi** `INSERT` lô mới. Lúc đó khóa ngoại trỏ tới một
dòng chưa tồn tại, nên lỗi xảy ra ở mọi lần tạo Demo **từ lần thứ hai**. Lần đầu không lỗi vì chưa có lô cũ.
Test 1.0.0 không có kịch bản tạo Demo hai lần. Transaction đã rollback đúng, nên DB thật vẫn nhất quán
(integrity ok, fk rỗng, 1 lô DEMO ACTIVE).

**`NO_ACTIVE_DATASET`:** lúc khởi động (02:19:56), khi chưa có dữ liệu, scheduler chạy job catch-up D0 và TRAIN.
Runner coi `NO_ACTIVE_DATASET` là lỗi cứng nên ghi job FAILED và tạo 2 cảnh báo ERROR. Các cảnh báo này
**ở lại trên dashboard** kể cả khi đã có dữ liệu.

### 2. File đã sửa / thêm

| File | Mục đích |
|---|---|
| `backend/app/data/demo.py` | Thứ tự cha-trước: INSERT lô mới (chưa ACTIVE) → dòng + `demand_daily` → đánh dấu lô cũ REPLACED → ACTIVE lô mới. Kiểm tra trong transaction: đúng 1 lô DEMO ACTIVE và `foreign_key_check` rỗng, sai thì rollback. Ghi `replaces_batch_id`. |
| `backend/app/migrations/0002_one_active_demo.sql` | Unique index một phần: tối đa 1 lô DEMO ACTIVE, ràng buộc ngay trong DB |
| `backend/app/db.py` | `ConsistencyError`, `fk_violations`, `health_check`; `connect()` không bao giờ tự tạo DB trống; `migrate()` gọi `ensure_storage()` |
| `backend/app/jobs/runner.py` | `NO_ACTIVE_DATASET` / `ACTIVE_DATASET_INCONSISTENT` / chưa cấu hình → SKIPPED, không tạo alert ERROR |
| `backend/app/data/demand.py` | Phân biệt "chưa có dữ liệu" với "cấu hình trỏ tới lô không còn hoạt động" (không tự chọn lô khác) |
| `backend/app/messages.py` | Mã lỗi DB/lưu trữ/nội bộ ổn định, song ngữ, có `category` |
| `backend/app/main.py` | Handler: `sqlite3.Error`, `ConsistencyError`, `StorageError`; có `request_id`; không trả traceback; log ghi đường dẫn hiệu lực lúc khởi động |
| `backend/app/paths.py` | **Nguồn đường dẫn duy nhất**: env > `storage.json` > mặc định; kiểm tra quyền ghi; chặn DB trống |
| `backend/app/storage_migrate.py` | Kiểm kê, backup đã xác minh, sao chép bằng SQLite Backup API, xác minh, chuyển cấu hình, lưu trữ DB cũ, rollback |
| `backend/app/diagnostics.py` | Báo cáo chẩn đoán không chứa secret |
| `backend/app/backup.py` | Backup đọc DB ở chế độ read-only (URI an toàn với khoảng trắng); xác minh integrity trước khi chấp nhận |
| `backend/app/logging_setup.py` | Tự lùi về chỉ ghi console khi thư mục log không khả dụng; `reset_logging` |
| `backend/app/cli.py` | Lệnh `paths`, `diagnose`, `storage-inventory`, `storage-migrate`, `storage-rollback`, `storage-init`; kiểm tra env/DB; chặn chạy trùng instance |
| `backend/app/api/ops_routes.py` | `/api/system/paths`, `/health-check`, `/diagnostics(.md)`, `/diagnostics/save` |
| `backend/app/data/importer.py` | Dọn file tải lên tạm quá 24 giờ |
| `scripts/_common.ps1`, `start.ps1`, `stop.ps1`, `install.ps1` | Dùng bộ phân giải của backend (bỏ logic đường dẫn trùng lặp); `install -DataDir`; giữ autostart |
| `scripts/migrate-storage.ps1`, `rollback-storage.ps1`, `diagnose.ps1`, `run-tests.ps1`, `build-package.ps1`, `smoke_test.py` | Quy trình di chuyển/rollback/chẩn đoán; log test vào `logs\development\`; gói thêm `Diagnose.bat` |
| `frontend/src/components/ui.tsx`, `App.tsx`, `pages/System.tsx`, `i18n.tsx`, `api.ts` | ErrorBox theo category (ẩn chi tiết DB/nội bộ, hiện request ID và hướng dẫn chẩn đoán); banner hướng dẫn khi chưa có dữ liệu; trang Hệ thống hiển thị đường dẫn, kiểm tra toàn vẹn, tải/lưu báo cáo chẩn đoán; bản dịch Việt/Anh |
| Tests: `tests/test_demo_regression.py`, `tests/test_storage.py`, `tests/test_db.py`, `tests/conftest.py`, `frontend/src/app.test.tsx` | Regression tests |
| Docs: `docs/02_kien_truc_du_lieu/LUU-TRU.md` (mới), `README.md`, `docs/03_van_hanh/VAN-HANH.md`, `docs/02_kien_truc_du_lieu/KIEN-TRUC.md`, `docs/03_van_hanh/CHECKPOINT.md`, `.gitignore` | Tài liệu |

### 3. Logic Demo và active dataset sau khi sửa

- Mỗi lần **Tạo dữ liệu Demo** chạy trong một transaction. Lô mới được tạo đầy đủ trước; sau đó lô cũ chuyển REPLACED
  với `replaced_by_batch_id` trỏ tới lô mới (dòng này đã tồn tại); cuối cùng lô mới thành ACTIVE.
  Lỗi ở bất kỳ bước nào → rollback toàn bộ, lô Demo cũ vẫn dùng được.
- Database cũng ràng buộc: không thể có hai lô DEMO ACTIVE.
- Dashboard: nguồn DEMO lấy lô DEMO ACTIVE duy nhất; nguồn MANUAL_IMPORT lấy lô được chọn.
  - Chưa có dữ liệu → banner *"Chưa có dữ liệu"*, kèm nút **Tạo dữ liệu Demo** hoặc liên kết Import.
  - Cấu hình trỏ tới lô không còn hoạt động → cảnh báo `ACTIVE_DATASET_INCONSISTENT`. Hệ thống không tự chọn lô khác.

### 4. Đường dẫn trước và sau

| Mục | Trước (1.0.0) | Sau (1.1.0, đang dùng) |
|---|---|---|
| Database | `%LOCALAPPDATA%\DemandForecast\db\app.db` | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` |
| Mô hình | `…\DemandForecast\models` | `D:\Buymed\Lightgbm AI\data\runtime\models` |
| Log runtime (nguồn chính duy nhất) | `…\DemandForecast\logs` | `D:\Buymed\Lightgbm AI\logs\runtime` (log cũ được **sao chép** vào `legacy-20261014_102304\`) |
| Backup | `…\DemandForecast\backups` | `D:\Buymed\Lightgbm AI\backups` |
| Báo cáo chẩn đoán | — | `D:\Buymed\Lightgbm AI\reports` |
| Log phát triển/test | — | `D:\Buymed\Lightgbm AI\logs\development` |
| File xuất | tải qua trình duyệt | tải qua trình duyệt (máy chủ không lưu) |
| Cấu hình đường dẫn | — | `%LOCALAPPDATA%\DemandForecast\storage.json` (vị trí cố định theo người dùng; không chứa secret) |

Chạy từ shortcut, từ script, từ thư mục cài đặt, từ repo, hay từ một CWD khác đều dùng **cùng một** DB (đã kiểm thử).

### 5. Database chính hiện tại

`D:\Buymed\Lightgbm AI\data\runtime\db\app.db`: schema v2, `integrity_check` ok, FK 0, 1 lô DEMO ACTIVE
`DEMO-20261014022115-402AB7`, 93 157 dòng đơn hàng. Ứng dụng **1.1.0 đang chạy** tại http://127.0.0.1:8765.

DB cũ đã được **đổi tên** (không xóa) thành `%LOCALAPPDATA%\DemandForecast\db.migrated-20261014_102304\`.
Tại chỗ cũ có một **file** tên `db`; nếu lỡ chạy bản 1.0.0, nó sẽ báo lỗi chứ không tạo DB trống (đã kiểm chứng).

### 6. Dữ liệu đã / chưa di chuyển

- **Đã di chuyển:** database (sao chép bằng Backup API, số dòng mọi bảng + danh sách bảng/index/trigger + schema version
  khớp 100%). `models\` trống nên không có file mô hình để chuyển. `app.env` không tồn tại.
- **Chỉ sao chép:** log cũ, sang `logs\runtime\legacy-20261014_102304`.
- **Giữ nguyên ở chỗ cũ:**
  - các backup cũ trong `%LOCALAPPDATA%\DemandForecast\backups`: `pre-migration-v1`, `pre-restore`, `cli`, thư mục cách ly;
  - thư mục `logs`, `models`, `uploads` (trống) ở vị trí cũ.

### 7. Backup và cách xác minh

| Backup | Xác minh |
|---|---|
| `D:\Buymed\Lightgbm AI\backups\backup-20261014-102304-pre-storage-migration.zip` | Giải nén → `integrity_check` = ok → số dòng mọi bảng, schema version và danh sách đối tượng khớp với nguồn (`counts_match: true`, `diffs: []`) |
| `%LOCALAPPDATA%\DemandForecast\backups\backup-20261014-102159-cli.zip` (trước khi cài 1.1.0) | integrity kiểm tra lúc tạo |
| `…\backup-20261014-100928-pre-migration-v1.zip` | Đã dùng để khôi phục sau sự cố (so khớp từng dòng) |
| `…\backup-20261014-101210-pre-restore.zip` | Trạng thái DB bị test ghi nhầm, giữ lại để truy vết |

Từ 1.1.0, mọi backup đều được kiểm tra integrity trước khi ghi zip. Không backup nào bị xóa.

### 8. Rollback

`scripts\rollback-storage.ps1` (trong `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0`), các bước:
1. Dừng app.
2. Xóa file chặn `db`, đổi tên `db.migrated-20261014_102304` → `db`.
3. Xóa `storage.json` (trước đó dùng vị trí mặc định).
4. Đánh dấu `NOT-PRIMARY` cho thư mục D: (giữ nguyên, không xóa).
5. Kiểm tra integrity và số dòng.

Rollback đã được kiểm thử tự động trên thư mục tạm; **chưa chạy trên dữ liệu thật** (không cần).
Quay về bản chương trình 1.0.0: thư mục `…\Programs\DemandForecast\1.0.0` vẫn còn, nhưng chỉ dùng được sau rollback
**và** khôi phục backup `…-102159-cli.zip`, vì 1.0.0 từ chối DB schema v2.

### 9. Kiểm thử đã chạy (kết quả thực tế)

| Bộ test | Lệnh | Kết quả |
|---|---|---|
| Backend (tổng) | `scripts\run-tests.ps1` → `logs\development\tests_20261014_102520.log` | **93 passed**, 0 failed |
| — trong đó Demo/DB (mục 1–10 của yêu cầu) | `tests/test_demo_regression.py` | 8 passed |
| — trong đó đường dẫn/migration/rollback/secrets (mục 11–20, 26) | `tests/test_storage.py` | 13 passed (có test trên thư mục thật ở ổ D, đường dẫn có khoảng trắng) |
| Frontend typecheck / vitest / build | cùng lệnh | OK / **9 passed** / OK |
| Tái hiện lỗi bằng mã 1.0.0 | embedded python 1.0.0, DB tạm | 2nd FAILED: IntegrityError (lỗi tái hiện đúng) |
| Demo ×3 trên **bản sao** DB thật bằng mã 1.1.0 | script tạm | 3/3 OK, 1 ACTIVE, FK rỗng, dashboard nhận đúng lô |
| E2E gói portable 1.1.0, cô lập, DB ở `D:\…\data\e2e test runtime` (có khoảng trắng), CWD = `C:\Windows` | `smoke_test.py --test-data-dir …` | **24 passed**; sau restart **4 passed**; instance thứ hai → `ALREADY_RUNNING`; xóa thư mục cấu hình → `start.ps1` báo `STORAGE_NOT_FOUND`, không tạo DB |
| Cài đặt 1.1.0 trên máy | `install.ps1 -NoStart` | OK; backup trước; check-env OK; shortcut → 1.1.0 |
| Di chuyển thật | `migrate-storage.ps1 -DryRun`, rồi chạy thật | SUCCEEDED, mọi bước ok, `diffs: []` |
| Xác minh chỉ đọc trên dữ liệu thật | `smoke_test.py --phase readonly` | **7 passed** |
| Khóa an toàn bản 1.0.0 | `1.0.0 … app.cli info` | Lỗi `FileExistsError`, không tạo DB |

Thất bại còn tồn đọng: không có.
Skipped: rollback trên dữ liệu thật (chủ ý không chạy).
Blocked: BigQuery thật (chưa có dataset/credentials, không thuộc phạm vi đợt này).

### 10. Build & gói phát hành

- `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.0-win64-portable.zip` (96,6 MB)
- `dist\DemandForecast-1.1.0\` — có runtime Python nhúng, đã tự kiểm tra LightGBM huấn luyện/dự báo được
- Đã cài vào `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0`. Bản 1.0.0 giữ nguyên bên cạnh để rollback.
- **Chưa** kiểm tra trên một máy Windows sạch thật; mới kiểm tra trên máy này với thư mục cô lập.

### 11. Giới hạn còn tồn tại

- Dữ liệu vận hành nằm trong thư mục project ở ổ D. Nếu xóa/dọn thư mục project (vd. `git clean -x`) sẽ mất dữ liệu;
  `data\`, `logs\`, `backups\` đã được đưa vào `.gitignore`.
- `storage.json` và DB cũ đã lưu trữ vẫn ở `%LOCALAPPDATA%\DemandForecast`. File cấu hình là bắt buộc: nó là điểm
  bắt đầu cố định, không phụ thuộc nơi chạy.
- Nếu ổ D không có mặt, ứng dụng **không khởi động** (cố ý). Cách xử lý: cắm lại ổ hoặc chạy `rollback-storage.ps1`.
- Job huấn luyện theo lịch hôm nay đã chạy lúc khởi động (02:20) khi chưa có dữ liệu. Với mã mới, các trường hợp như
  vậy được ghi là SKIPPED, và job sẽ không tự chạy lại trong cùng ngày. Bấm **Huấn luyện & dự báo ngay** nếu cần.
- Hai cảnh báo ERROR `NO_ACTIVE_DATASET` cũ (từ 1.0.0) vẫn nằm trong lịch sử. Có thể bấm *Đánh dấu đã đọc tất cả*.
- Log được giới hạn theo dung lượng (10 MB × 5 file), chưa có giới hạn theo thời gian.

### 12. Khởi động và kiểm tra Demo

1. Ứng dụng đang chạy. Nếu không, mở shortcut **Demand Forecasting** trên Desktop (trỏ tới 1.1.0).
2. Mở http://127.0.0.1:8765 → **Tổng quan** → **Tạo dữ liệu Demo** (bấm hai lần để kiểm tra lỗi cũ) →
   **Huấn luyện & dự báo ngay**.
3. Xem **Hệ thống & sao lưu → Vị trí lưu trữ đang dùng**: database phải ở `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`.
   Bấm *Kiểm tra toàn vẹn database*.

### 13. Xác nhận về xóa dữ liệu

- Không xóa database, backup hay dữ liệu import nào của bạn. DB cũ được đổi tên và giữ lại; mọi backup được giữ.
- Những gì đã xóa:
  - các thư mục test tạm do tôi tạo (`data\test-tmp *`, `data\e2e test runtime`, bản sao tạm trong scratchpad);
  - file tạm `app.db.migrating` sau khi đã xác minh và đổi tên.
- Thay đổi duy nhất lên dữ liệu thật ngoài phạm vi được giao là sự cố ở mục 0. Sự cố đã được khôi phục bằng backup,
  có đối chiếu từng dòng; trạng thái bị ghi nhầm được giữ trong `…-101210-pre-restore.zip`.

## 2. Dọn lưu trữ, chuẩn hóa phát hành và chuẩn bị VPS — 16/10/2026 (13:55–15:00, giờ Việt Nam)

Nguồn: `reports\demandforecast_storage_release_20261016.md` (worktree MAIN).

Không commit, không push, không triển khai. Không đổi nghiệp vụ dự báo, BigQuery, LightGBM hay lịch chạy.
Thay đổi mã ứng dụng duy nhất là nhánh Linux của `app.cli._pid_alive`.

### 1. Dung lượng

| | Trước | Sau |
|---|---|---|
| Project `D:\Buymed\Lightgbm AI` | **6.875,6 MB** (163.971 file) | **988,1 MB** (20.108 file) |
| `dist\` | 3.873,0 MB | 191,5 MB (gói 1.1.8 + 1.1.6 + `.cache`) |
| `release\` | 2.208,0 MB | không còn |
| `.venv\` / `backups\` / `frontend\` / `data\` | 434,3 / 209,3 / 87,8 / 54,2 MB | không đổi |

Ngoài project (không động tới): `%LOCALAPPDATA%\Programs\DemandForecast` 2.533,6 MB (9 bản đã cài).

### 2. Đã xóa (đều đã kiểm nội dung trước khi xóa)

**Đợt 1 — 4.650,2 MB.** Gồm 10 thư mục staging `dist\DemandForecast-{1.0.0, 1.1.0–1.1.8}\` và 7 bản giải nén
`release\DemandForecast-{1.1.1–1.1.6, 1.1.6-build1-superseded}\`.
- Mọi file đều có trong ZIP tương ứng, cùng đường dẫn, kích thước và CRC32. Khác biệt duy nhất là bytecode `.pyc`.
- Cả 12 ZIP đều qua `testzip`.

Đợt này **đã chạy trước khi người dùng yêu cầu rà soát lại chính sách** giữ phiên bản. Các ZIP vẫn còn nên không có gì bị
mất. Nhật ký: scratchpad `delete_log.json`.

**Đợt 2 — 1.239,3 MB**, theo chính sách mới (giữ bản đang chạy + một bản rollback). Danh sách chính xác (đường dẫn,
phiên bản, dung lượng, SHA-256, lý do) được xuất **trước khi xóa** ra `reports\storage_cleanup_plan_20261016.md` / `.json`:
- ZIP 1.0.0, 1.1.0, 1.1.1, 1.1.2, 1.1.3, 1.1.4, 1.1.5: phiên bản cũ, không chạy, không phải rollback. Các bản cài vẫn
  còn trong `Programs`.
- ZIP 1.1.1-build1-superseded và 1.1.6-build1-superseded: bản build bị thay thế.
- ZIP + `.sha256` + manifest 1.1.7: chưa từng cài; 1.1.8 đã gồm 1.1.7; mã nguồn còn trong checkpoint
  `source-1.1.7-before-1.1.8`.
- `release\DemandForecast-1.1.0`: một build 1.1.0 trung gian (14/10 10:14), khác ZIP 1.1.0 cuối cùng; phiên bản lỗi thời.
- Thư mục `release\` (đã rỗng).

### 3. Giữ lại và bằng chứng khôi phục

| Giữ | Vì sao | Bằng chứng |
|---|---|---|
| Gói 1.1.8 (`0DFDEC86…5EE0`) | bản **đang chạy** = bản mới nhất đã kiểm thử | `current.txt`, tiến trình chạy từ `Programs\…\1.1.8`, `/api/health`; ZIP tái tạo đúng 7.115/7.115 file của bản cài |
| Gói 1.1.6 (`A2E0345C…9561`) | bản **ổn định gần nhất để rollback** (production 15/10 18:05 → 16/10 08:34) | ZIP tái tạo đúng 7.106/7.106 file; `rollback-version.ps1 -To 1.1.6 -CheckOnly`: OK, không cần khôi phục DB (schema 3) |
| `dist\.cache` (12 MB) | Python embedded 3.14.7 cho build | — |
| DB, model, cấu hình, `storage.json`, 25 backup, 9 checkpoint, logs, reports | dữ liệu người dùng / bằng chứng | so sánh trước–sau xóa: **giống hệt** |
| Bản cài 1.0.0–1.1.5 trong `Programs` (≈ 2 GB) | ngoài project; **đề xuất gỡ**, chờ người dùng quyết định | — |
| Backup | **đề xuất** chính sách giữ (`docs/01_quy_tac/PHAT-TRIEN-QA-PHAT-HANH.md` mục 7); không xóa | — |

Lúc 14:32 trong ứng dụng có thao tác thủ công: tạo lại bộ DEMO (`DEMO-20261016073211-24EC73`) và một lần huấn luyện
`MANUAL`. Tôi không thực hiện thao tác này (với ứng dụng thật tôi chỉ gửi GET). Ảnh chụp trạng thái để so sánh được lấy
sau thời điểm đó.

### 4. Cấu trúc sau chuẩn hóa

Một bộ mã nguồn duy nhất (Git, gồm `backend\`, `frontend\`, `scripts\`, `scripts\vps\`, `docs\`, `config\` mẫu); `dist\`
chỉ chứa artifact phát hành. Dữ liệu runtime của máy này giữ nguyên ở `data\runtime` (Git bỏ qua, do `storage.json`
trỏ tới, không di chuyển). Chi tiết: `docs/01_quy_tac/PHAT-TRIEN-QA-PHAT-HANH.md` mục 2.

### 5. Quy trình QA → phát hành → VPS

1. QA trên máy này: `scripts\run-tests.ps1`.
2. Commit → `scripts\release.ps1`:
   - chặn khi cây làm việc còn thay đổi chưa commit;
   - QA lỗi ⇒ không tạo gói;
   - gói được định danh bằng version + commit + dấu vân tay nguồn trong `BUILD-INFO.json`;
   - cùng nguồn ⇒ không build lại;
   - không ghi đè gói cùng phiên bản (`-Force` đổi tên gói cũ, không xóa);
   - kiểm SHA-256, `VERSION`, `BUILD-INFO.json`.
3. Dọn: `scripts\prune-artifacts.ps1 -Keep <bản rollback>`:
   - chỉ lập kế hoạch nếu không có `-Apply`;
   - chỉ xóa thư mục khi mọi file trùng SHA-256 với gói.
4. Máy này: `deploy-upgrade.ps1` như trước.
5. VPS Linux: `scripts\vps\build-vps-artifact.ps1`, rồi trên VPS chạy `install-server.sh` (một lần), `deploy.sh`,
   `rollback.sh` (`docs/03_van_hanh/TRIEN-KHAI-VPS.md`).

### 6. Test và build

| Loại | Kết quả |
|---|---|
| Backend toàn bộ (unit / fake) | 300 đạt, 2 bỏ qua (BigQuery thật, opt-in), exit 0 |
| `_pid_alive` trên Linux (os.kill giả lập) | 2/2 |
| Frontend typecheck / build | đạt / đạt (không đổi mã frontend trong đợt này; vitest lần trước 61/61) |
| `build-package.ps1` trên clone scratchpad | từ chối cây có thay đổi; từ chối ghi đè gói cũ; `-Force` giữ gói cũ dạng superseded + build mới, xóa staging; build lại cùng nguồn ⇒ "Up to date" |
| `release.ps1` trên clone | QA lỗi (test ổ D đã biết của `d87c315`) ⇒ không tạo gói; sau khi chép bản sửa test: QA 275 + 52 đạt ⇒ "Up to date" ⇒ kiểm gói OK |
| `prune-artifacts.ps1` | trên clone: chạy thử / `-Apply` đúng; gói giả lập: thư mục trùng ⇒ xóa, khác 1 file ⇒ giữ |
| Artifact Linux (tạo trên clone, chạy thử trên Windows) | `sha256sum -c` OK; 76 file, không DB/`.env`/khóa; app chạy từ artifact: health OK, UI 200, Host proxy OK, Host lạ 403, backup API OK |
| Wheel Linux | `pip --dry-run`: 52/52 gói có wheel Linux x86_64 cp314; cần glibc ≥ 2.28 |
| Script `.sh` | `bash -n` đạt; **chưa chạy trên Linux** |
| Lint | chưa cấu hình |

### 7. Thông tin còn thiếu để triển khai VPS

Xem `docs/03_van_hanh/TRIEN-KHAI-VPS.md` mục 9:
- OS / phiên bản / glibc, cấu hình CPU–RAM–đĩa;
- quyền SSH có sudo;
- tên miền + DNS, chứng chỉ TLS;
- cách đăng nhập (ứng dụng không có đăng nhập riêng);
- service account Google chỉ đọc do quản trị cấp;
- VPS dùng DB mới hay chuyển dữ liệu từ máy này;
- máy nào chạy lịch sau khi chuyển;
- nơi lưu backup ngoài VPS.

### 8. Kết luận

Kết quả: `READY_FOR_EXTERNAL_SETUP`. Lưu trữ, quy trình phát hành và bộ triển khai VPS đã xong. Còn thiếu thông tin
VPS, và bộ Linux cần được xác minh lần đầu trên VPS thật.

Dữ liệu, model, lịch chạy, thông tin xác thực và dữ liệu runtime giữ nguyên. Ứng dụng 1.1.8 chạy bình thường (health ok,
UI 200, scheduler chạy, lịch không đổi).

## 3. storage_cleanup_plan_20261016.md

Nguồn: `reports\storage_cleanup_plan_20261016.md` (worktree MAIN).

| Quyết định | Đường dẫn | Phiên bản | Dung lượng | Lý do |
|---|---|---|---|---|
| KEEP | `dist\.cache` | - | 12.1 MB | cache đầu vào của build (Python embedded 3.14.7 tải từ python.org), không phải bản build ứng dụng; tránh tải lại |
| DELETE | `dist\DemandForecast-1.0.0-win64-portable.zip` | 1.0.0 | 97.6 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.0.0 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.0-win64-portable.zip` | 1.1.0 | 96.6 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.1.0 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.1-build1-superseded-win64-portable.zip` | 1.1.1-build1-superseded | 96.6 MB | bản build bị thay thế, chưa từng là bản phát hành của phiên bản đó |
| DELETE | `dist\DemandForecast-1.1.1-win64-portable.zip` | 1.1.1 | 96.6 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.1.1 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.2-win64-portable.zip` | 1.1.2 | 96.7 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.1.2 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.3-win64-portable.zip` | 1.1.3 | 96.7 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.1.3 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.4-win64-portable.zip` | 1.1.4 | 96.7 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.1.4 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.5-win64-portable.zip` | 1.1.5 | 96.7 MB | phiên bản cũ, không chạy, không phải bản rollback; bản cài 1.1.5 vẫn còn trong Programs (không động tới) |
| DELETE | `dist\DemandForecast-1.1.6-build1-superseded-win64-portable.zip` | 1.1.6-build1-superseded | 96.8 MB | bản build bị thay thế, chưa từng là bản phát hành của phiên bản đó |
| KEEP | `dist\DemandForecast-1.1.6-win64-portable.manifest.json` | 1.1.6 | 2.0 MB | bản ỔN ĐỊNH GẦN NHẤT để rollback (chạy production 15/10 18:05 → 16/10 08:34); ZIP tái tạo đúng 7.106/7.106 file của bản cài; rollback-version.ps1 -To 1.1.6 -CheckOnly: OK, không cần khôi phục DB; SHA-256 khớp |
| KEEP | `dist\DemandForecast-1.1.6-win64-portable.zip` | 1.1.6 | 87.7 MB | bản ỔN ĐỊNH GẦN NHẤT để rollback (chạy production 15/10 18:05 → 16/10 08:34); ZIP tái tạo đúng 7.106/7.106 file của bản cài; rollback-version.ps1 -To 1.1.6 -CheckOnly: OK, không cần khôi phục DB; SHA-256 khớp |
| KEEP | `dist\DemandForecast-1.1.6-win64-portable.zip.sha256` | 1.1.6 | 0.0 MB | bản ỔN ĐỊNH GẦN NHẤT để rollback (chạy production 15/10 18:05 → 16/10 08:34); ZIP tái tạo đúng 7.106/7.106 file của bản cài; rollback-version.ps1 -To 1.1.6 -CheckOnly: OK, không cần khôi phục DB; SHA-256 khớp |
| DELETE | `dist\DemandForecast-1.1.7-win64-portable.manifest.json` | 1.1.7 | 2.0 MB | chưa từng cài (build 15/10, 1.1.8 đã gồm toàn bộ 1.1.7); không phải bản rollback; mã nguồn còn trong checkpoints\source-1.1.7-before-1.1.8-20261016-000339.zip |
| DELETE | `dist\DemandForecast-1.1.7-win64-portable.zip` | 1.1.7 | 87.8 MB | chưa từng cài (build 15/10, 1.1.8 đã gồm toàn bộ 1.1.7); không phải bản rollback; mã nguồn còn trong checkpoints\source-1.1.7-before-1.1.8-20261016-000339.zip |
| DELETE | `dist\DemandForecast-1.1.7-win64-portable.zip.sha256` | 1.1.7 | 0.0 MB | chưa từng cài (build 15/10, 1.1.8 đã gồm toàn bộ 1.1.7); không phải bản rollback; mã nguồn còn trong checkpoints\source-1.1.7-before-1.1.8-20261016-000339.zip |
| KEEP | `dist\DemandForecast-1.1.8-win64-portable.manifest.json` | 1.1.8 | 2.0 MB | bản ĐANG CHẠY (Programs\1.1.8, current.txt, /api/health) = bản mới nhất đã kiểm thử thành công; ZIP tái tạo đúng 7.115/7.115 file của bản cài; SHA-256 khớp .sha256 |
| KEEP | `dist\DemandForecast-1.1.8-win64-portable.zip` | 1.1.8 | 87.8 MB | bản ĐANG CHẠY (Programs\1.1.8, current.txt, /api/health) = bản mới nhất đã kiểm thử thành công; ZIP tái tạo đúng 7.115/7.115 file của bản cài; SHA-256 khớp .sha256 |
| KEEP | `dist\DemandForecast-1.1.8-win64-portable.zip.sha256` | 1.1.8 | 0.0 MB | bản ĐANG CHẠY (Programs\1.1.8, current.txt, /api/health) = bản mới nhất đã kiểm thử thành công; ZIP tái tạo đúng 7.115/7.115 file của bản cài; SHA-256 khớp .sha256 |
| DELETE | `release\DemandForecast-1.1.0` | 1.1.0 (build sớm 14/10 10:14) | 278.6 MB | bản giải nén của một build 1.1.0 trung gian (khác ZIP 1.1.0 cuối cùng); phiên bản lỗi thời, không chạy, không phải rollback |

Xóa: 1,239.3 MB; giữ: 191.5 MB.

## 4. Điều tra "thiếu storage.json" sau khi cài DemandForecast 1.1.0

Nguồn: `reports\storage_json_investigation_20261014_121904.md` (worktree MAIN).

Ngày: 2026-10-14 12:19 (giờ VN).

**Phạm vi:**
- Các bước điều tra đều chỉ đọc.
- Không tạo hay ghi đè `storage.json`, không tạo hay sửa database, không động vào dữ liệu Demo.
- Không chạy bản 1.0.0, không di chuyển dữ liệu lần nữa.
- Không dừng ứng dụng đang chạy: pid 10100, chạy liên tục từ 10:23:09.

### 1. Kết luận

| Câu hỏi | Kết luận |
|---|---|
| `storage.json` có thực sự bị thiếu không? | **Không.** File tồn tại và hợp lệ tại `C:\Users\Giau Vo\AppData\Local\DemandForecast\storage.json`: 399 byte, ghi lúc 10:23:06 bởi lần di chuyển 20261014_102304, SHA-256 `8D79DBDD…FDE047`. Xác nhận độc lập bằng `Test-Path`, `cmd dir /a`, .NET `File.Exists`, và bằng API của chính ứng dụng đang chạy (`storage_config_exists=true`, mọi `sources = storage.json`). |
| Lỗi cài đặt? | **Không.** `install.ps1` không đọc, ghi hay xóa `storage.json`. |
| Lỗi di chuyển dữ liệu? | **Không.** Lần di chuyển đã ghi `storage.json`, và lịch sử ghi nhận trạng thái `SUCCEEDED`. |
| Lỗi phân giải đường dẫn? | **Không** với trạng thái hiện tại: ứng dụng đang dùng đúng `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`. Tuy nhiên tôi tìm thấy **một lỗ hổng tiềm ẩn** cho trường hợp file *thật sự* bị mất (mục 3), và đã sửa. |
| Cấu hình có trỏ đúng 4 đường dẫn yêu cầu không? | **Có.** data `D:\Buymed\Lightgbm AI\data\runtime`, logs `…\logs\runtime`, backups `…\backups`, reports `…\reports`. |

**Lý do có thể khiến bạn không tìm thấy file** (chưa xác minh được lý do nào là đúng):
- `storage.json` theo thiết kế **chỉ** nằm ở `%LOCALAPPDATA%\DemandForecast`, không nằm trong thư mục runtime trên ổ D,
  không nằm trong project hay thư mục cài đặt. Thư mục runtime chỉ chứa `storage-id.json`, `runtime.json` và
  `storage-migration-*.json`; danh sách 3 file trong mô tả lỗi khớp đúng với thư mục runtime, nên nhiều khả năng
  bạn đã tìm ở đó.
- Thư mục `AppData` bị ẩn trong Explorer.
- Một công cụ chạy với tài khoản hoặc `LOCALAPPDATA` khác. Tôi đã kiểm tra: không có bản ảo hóa nào trong `Packages\*\LocalCache`.

### 2. Đối chiếu chéo (chỉ đọc)

| Kiểm tra | Kết quả |
|---|---|
| `storage.json.storage_id` | `6cff0821634b0447` |
| `D:\…\data\runtime\storage-id.json` | `storage_id = 6cff0821634b0447` (khớp), `migrated_from = C:\Users\Giau Vo\AppData\Local\DemandForecast` (khớp nguồn của lần di chuyển), `created_at = 2026-10-14T03:23:06Z` (bằng `finished_at` của lần di chuyển) |
| `storage-migrations.json` (cạnh `storage.json`) | 1 sự kiện: `20261014_102304 SUCCEEDED`; đích trùng đúng 4 đường dẫn yêu cầu |
| `storage-migration-20261014_102304.json` (ở đích) | Trùng `stamp`, `status` và `target` với lịch sử |
| `runtime.json` | pid 10100, port 8765 (khớp tiến trình đang chạy); token tắt máy **không được in ra** |
| Database (mở `?mode=ro`) | `integrity_check = ok`, 0 vi phạm FK, schema v2, lô ACTIVE `DEMO-20261014042925-CB692D`, 93 157 dòng đơn hàng |
| Vị trí cũ | `db.migrated-20261014_102304\app.db` còn nguyên; file chặn `db` vẫn còn |
| Biến môi trường `DF_DATA_DIR`, `DF_STORAGE_CONFIG`, `DF_LOGS_DIR` | Không đặt ở cả Process, User và Machine |
| `app.cli storage-verify` (lệnh mới) | `ok: true`, `problems: []` |

Vì mọi điểm đều khớp và file đang tồn tại, tôi **không** tạo lại hay ghi đè `storage.json`.
`storage-repair --dry-run` trên hệ thống thật từ chối như mong đợi: *"storage.json exists - nothing to repair"*.

### 3. Lỗ hổng tiềm ẩn tìm thấy và đã sửa

Tôi tái hiện trên thư mục tạm, chạy mã 1.1.0 trước khi sửa: di chuyển dữ liệu, rồi xóa `storage.json`.
- **Còn file chặn `db`:** ứng dụng crash với `FileExistsError` thô, không có hướng dẫn xử lý.
- **Không có file chặn** (ví dụ file chặn đã bị xóa): `ensure_storage()` + `migrate()` **tạo database trống ở vị trí
  mặc định** và ứng dụng sẽ chạy trên đó. Dữ liệu thật ở ổ D vẫn an toàn nhưng bị "bỏ quên"; người dùng sẽ tưởng
  dữ liệu đã mất.

**Bản sửa tối thiểu**, giữ đúng kiến trúc hiện có:
- `paths.ensure_storage()` gọi thêm `_check_config_not_lost()`. Khi đang dùng vị trí mặc định mà không có
  `storage.json`, nếu lịch sử cho thấy lần di chuyển cuối thành công (hoặc vị trí `db` cũ là file chặn) thì báo
  **`STORAGE_CONFIG_MISSING`**, nêu rõ dữ liệu đã chuyển đi đâu và cách khôi phục. Không tạo gì cả.
- Lệnh mới `app.cli storage-verify`, chỉ đọc: đối chiếu `storage.json` ↔ `storage-id.json` ↔ lịch sử ↔ database.
- Lệnh mới `app.cli storage-repair [--dry-run]` và script `scripts\repair-storage.ps1 [-Apply]`. Chỉ ghi lại
  `storage.json` khi **mọi** bằng chứng khớp; **không đoán** `storage_id` mà lấy từ `storage-id.json` của thư mục đích,
  sau khi đã xác minh:
  - sự kiện cuối trong lịch sử là `SUCCEEDED`;
  - `storage_id` của bản ghi lịch sử khớp, nếu bản ghi có trường này;
  - với bản ghi cũ không có `storage_id`: `created_at` của marker phải bằng `finished_at` của lần di chuyển;
  - `migrated_from` khớp nguồn;
  - bản ghi `storage-migration-<stamp>.json` ở đích khớp lịch sử;
  - database tồn tại và qua `integrity_check`.

  Lệnh từ chối nếu `storage.json` đang tồn tại, nếu sự kiện cuối là ROLLBACK, hoặc nếu bất kỳ điểm nào lệch.
- Từ nay, lịch sử di chuyển ghi kèm `storage_id`, để lần sửa chữa sau có thể đối chiếu 3 chiều.
- `install.ps1` chạy `storage-verify` **trước mọi thay đổi**. Nếu cấu hình lưu trữ có vấn đề, script dừng với exit 3,
  không sao chép, không chạy migration, không tạo DB.
- `rollback()`: ghi sự kiện ROLLBACK vào lịch sử *trước khi* phân giải lại đường dẫn. Phép kiểm tra mới đã làm lộ
  lỗi thứ tự này qua test; nay đã sửa.

### 4. File đã sửa / thêm

| File | Thay đổi |
|---|---|
| `backend/app/paths.py` | `HISTORY_FILE`, `history_path()`, `last_storage_event()`, `_check_config_not_lost()`; gọi trong `ensure_storage()` |
| `backend/app/storage_migrate.py` | Dùng chung `paths.history_path()`; ghi `storage_id` vào lịch sử; `verify_storage()`, `repair_storage_config()`; sửa thứ tự trong `rollback()` |
| `backend/app/cli.py` | Lệnh `storage-verify`, `storage-repair [--dry-run]` |
| `backend/app/messages.py` | Mã `STORAGE_CONFIG_MISSING`, song ngữ |
| `scripts/install.ps1` | Kiểm tra `storage-verify` trước khi thay đổi bất cứ gì |
| `scripts/repair-storage.ps1` (mới), `scripts/build-package.ps1` | Script khôi phục; được đóng vào gói |
| `backend/tests/test_storage.py` | 6 test hồi quy mới (mục 5) |
| `docs/02_kien_truc_du_lieu/LUU-TRU.md`, `docs/03_van_hanh/VAN-HANH.md` | Vị trí của `storage.json`, cách kiểm tra và khôi phục, dòng khắc phục sự cố |

### 5. Kiểm thử

| Bộ test | Kết quả |
|---|---|
| Backend, toàn bộ (`scripts\run-tests.ps1` → `logs\development\tests_20261014_120505.log`) | **99 passed**, 0 failed |
| — 6 test mới: mất `storage.json` mà DB runtime vẫn còn → `STORAGE_CONFIG_MISSING`, không tạo DB trống (kể cả khi không còn file chặn); thiếu lịch sử nhưng còn file chặn → vẫn chặn; repair khôi phục đúng 4 đường dẫn + `storage_id`; repair từ chối khi `storage_id` lệch / thiếu DB / thiếu bản ghi ở đích; bản ghi cũ không có `storage_id` cần marker khớp; repair từ chối sau rollback; verify phát hiện cấu hình lệch | Pass |
| Frontend typecheck / vitest / build | OK / 9 passed / OK |
| Gói 1.1.0 đã build lại, chạy trong `LOCALAPPDATA` tạm cô lập: di chuyển → xóa `storage.json` → `install.ps1` | exit 3, không tạo thư mục chương trình, không tạo DB trống |
| Cùng môi trường: `repair-storage.ps1` (dry-run), rồi `-Apply` | Dry-run không ghi gì; `-Apply` khôi phục `storage.json` với `storage_id` khớp marker |
| Cùng môi trường: `install.ps1` lần 2 | Cài đặt và migration chạy được. `check-env` của bản cài **trong thư mục test** báo numpy không nạp được DLL: đường dẫn ~284 ký tự, vượt giới hạn 260 của Windows (`LongPathsEnabled = 0`). Đây là giới hạn của môi trường test; bản cài thật dùng đường dẫn 135 ký tự và vẫn chạy bình thường. |
| Hệ thống thật: `storage-verify` | `ok: true`; hash `storage.json` không đổi trước và sau |

### 6. Gói phát hành

- `dist\DemandForecast-1.1.0-win64-portable.zip` (96,6 MB) đã được build lại với bản sửa. **Số phiên bản vẫn là
  1.1.0** theo yêu cầu, nên bản đang cài tại `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0` (cài lúc 10:22) **chưa
  có** bản sửa này.
- Tôi **không** cài lại, vì cài lại sẽ dừng rồi khởi động lại ứng dụng đang chạy, và hệ thống hiện tại đang nhất quán.

### 7. Khởi động an toàn

- Ứng dụng đang chạy bình thường tại http://127.0.0.1:8765, dùng DB trên ổ D.
- Lần khởi động sau: dùng shortcut **Demand Forecasting** (trỏ tới bản 1.1.0) hoặc
  `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0\Start.bat`. **Không** chạy bản 1.0.0.
- Muốn áp dụng bản sửa: chạy `dist\DemandForecast-1.1.0\Install.bat`. Script sẽ chạy `storage-verify`, dừng app,
  backup, cài đè, chạy migration (không có thay đổi schema) rồi khởi động lại.
- Kiểm tra bất cứ lúc nào (chỉ đọc):
  `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0\python\python.exe -m app.cli storage-verify`
  (lệnh này có sau khi cài bản sửa; trước đó dùng Python của repo). Hoặc xem trang **Hệ thống & sao lưu → Vị trí lưu trữ đang dùng**.

## 5. Báo cáo nâng cấp an toàn — Demand Forecasting 1.1.0 (bản sửa lỗi storage.json)

Nguồn: `reports\upgrade_storage_fix_report_20261014_144908.md` (worktree MAIN).

Thời gian: 2026-10-14, 13:50 → 14:49 (giờ VN). Máy: Windows 11, người dùng hiện tại.

### Kết luận

**THÀNH CÔNG CÓ ĐIỀU KIỆN.** Bản cài đã được nâng cấp lên bản 1.1.0 build lại và trùng 100% với gói phân phối.
Mọi kiểm tra an toàn dữ liệu đều đạt, ứng dụng đang chạy trên đúng database ở ổ D, và dữ liệu trước/sau giống hệt.

"Có điều kiện" vì còn ba điểm chưa đạt hoặc chưa kiểm được (chi tiết ở mục 8):
1. Không thể rollback về **bản chương trình** 1.1.0 trước khi sửa, vì cài đè cùng số phiên bản đã thay thế nó.
   Rollback dữ liệu và rollback lưu trữ thì đã được xác minh.
2. Chưa thử trên một máy Windows khác thật.
3. Ứng dụng chịu giới hạn đường dẫn 260 ký tự khi máy tắt Long Paths.

---

### 1. Phiên bản

| | Trước | Sau |
|---|---|---|
| Phiên bản | 1.1.0, cài lúc 10:22, **chưa có** bản sửa `storage.json` | 1.1.0 build lại 14:43, **có** đủ bản sửa (cài lần cuối 14:44) |
| Tiến trình | pid 10100 (từ 10:23:09) | pid 28096 (từ 14:45:52) |
| Thư mục cài | `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0` | như trước. So hash từng file `backend`, `scripts`, `web`, `docs`, `python` với gói: **trùng 100%** |
| Schema DB | v2 | v2 (không có migration mới) |

Quá trình chạy **3 vòng cài** theo đúng quy trình chính thức. Sau mỗi vòng tôi kiểm thử và phát hiện thêm lỗi, sửa trong
mã nguồn, build lại gói, rồi cài lại:

- **Vòng 1 (13:54):** cài các bản sửa đã có (`STORAGE_CONFIG_MISSING`, `storage-verify`, `storage-repair`, thứ tự rollback).
  Trước vòng này đã thêm 2 sửa nhỏ: `storage-repair` (CLI) mặc định chỉ chạy thử, chỉ ghi khi có `--apply`; và
  installer dừng nếu chương trình còn đang chạy.
- **Vòng 2 (14:28):** test cô lập phát hiện 3 lỗi, đã sửa:
  - đọc `storage.json` / `storage-id.json` có BOM (do Notepad hoặc PowerShell 5.1 ghi) → trước đây bị từ chối;
  - marker không phải JSON hợp lệ → trước đây `storage-repair` crash thay vì từ chối gọn;
  - kiểm tra marker của bản ghi cũ đòi `created_at` == `finished_at` → test bấp bênh; nay là điều kiện
    "marker được tạo trong khoảng thời gian của lần di chuyển".
- **Vòng 3 (14:44):** chốt chặn "chương trình đang chạy" của installer được làm lại. Bản trước so đường dẫn không
  chuẩn hóa (trượt với tên 8.3) và có thêm phép thử đổi tên thư mục, nhưng Windows **vẫn cho phép** đổi tên khi chương
  trình đang chạy nên phép thử đó vô hiệu. Nay chuẩn hóa cả hai vế đường dẫn và thử mở `python.exe` với quyền ghi
  độc quyền (thất bại nếu file đang chạy).

### 2. Các bản sửa đã xác minh (mã nguồn ↔ gói ↔ bản cài)

| # | Yêu cầu | Bằng chứng |
|---|---|---|
| 1 | Thiếu `storage.json` → `STORAGE_CONFIG_MISSING`, không tạo DB rỗng, không dùng đường dẫn mặc định | `backend/app/paths.py` `_check_config_not_lost()`. Kịch bản cô lập với bản cài: `paths --check` exit 3; không có `app.db` ở vị trí mặc định; `serve` từ chối (exit 3). Unit test `test_lost_storage_json_is_detected_and_never_creates_empty_db`. |
| 2 | Installer từ chối khi thiếu cấu hình lưu trữ | `scripts/install.ps1` chạy `storage-verify` trước mọi thay đổi. Kịch bản cô lập: exit 3, không tạo thư mục `Programs`. |
| 3 | `storage-verify` kiểm tra cấu hình, marker, lịch sử và database | `storage_migrate.verify_storage()`. Hệ thống thật: `ok`, 0 vấn đề. Cô lập: phát hiện thiếu cấu hình (exit 1) và lệch `storage_id` (exit 1). |
| 4 | `storage-repair` chỉ ghi khi có `-Apply` và chỉ khi bằng chứng nhất quán | Script: `-Apply`. CLI: `--apply` (mặc định chạy thử). Cô lập: không `-Apply` → không ghi; `-Apply` → khôi phục đúng `storage_id`, `data_dir`, `logs_dir`. Unit test `test_repair_cli_writes_only_with_apply`. |
| 5 | Từ chối ghi đè, từ chối sau rollback, từ chối khi bằng chứng lệch | Cô lập: ghi đè → exit 2, hash không đổi; marker lệch → exit 2, không ghi; sau rollback → exit 2 ("ROLLBACK"). Unit test cho thiếu DB, thiếu bản ghi đích, bản ghi cũ không có `storage_id`, marker hỏng. |
| 6 | Sửa thứ tự trong rollback | `rollback()` ghi sự kiện ROLLBACK trước khi phân giải lại đường dẫn. Cô lập: rollback thành công, sau đó vị trí mặc định là chính. |
| 7 | Gói chứa đúng bản sửa và gọi đúng script cài | Hash `backend/app` của gói == repo; zip == thư mục (56 mục). `Install.bat` → `scripts\install.ps1`. Bản cài == gói. |
| 8 | Installer backup trước, không tạo/ghi đè DB runtime trên ổ D | `install.ps1`: `storage-verify` → `stop.ps1` → kiểm tra chương trình đang chạy (exit 4) → `app.cli backup` (dừng nếu backup lỗi) → thay **thư mục chương trình** → `migrate`. Thư mục chương trình không chứa dữ liệu hay cấu hình (đã kiểm tra). Sau mỗi vòng: `storage.json` cùng hash, DB cùng kích thước, không có `app.db` mới. |

### 3. Backup

Backup chủ động trước mỗi vòng, đều được xác minh: giải nén → `integrity_check` → so số dòng và đối tượng schema với
DB thật → đọc lại lô ACTIVE và tổng số lượng.

| File (trong `D:\Buymed\Lightgbm AI\backups\`) | Tạo bởi | Xác minh |
|---|---|---|
| `backup-20261014-135327-cli.zip` (8,6 MB) | tôi, trước vòng 1 | integrity ok; số dòng và đối tượng khớp; đọc lại: ACTIVE `CB692D`, 93 157 dòng, tổng 1 015 057 |
| `backup-20261014-135442-cli.zip` | `install.ps1` vòng 1 | integrity kiểm tra lúc tạo |
| `backup-20261014-142806-cli.zip` | tôi, trước vòng 2 | `verify_backup_zip` ok, `diffs: []` |
| `backup-20261014-142840-cli.zip` | `install.ps1` vòng 2 | integrity kiểm tra lúc tạo |
| `backup-20261014-144428-cli.zip` | tôi, trước vòng 3 | `verify_backup_zip` ok |
| `backup-20261014-144455-cli.zip` | `install.ps1` vòng 3 | integrity kiểm tra lúc tạo |

Không xóa backup nào. Các backup cũ khác vẫn nguyên.

### 4. Kết quả kiểm thử

| Bộ test | Pass | Fail | Skip |
|---|---|---|---|
| Backend, toàn bộ (`logs\development\tests_20261014_142547.log`) | 102 | 0 | 0 |
| Frontend vitest | 9 | 0 | 0 |
| Typecheck / build frontend | OK | — | — |
| Hồi quy storage/DB/scheduler/demo trước vòng 2 | 48 | 0 | 0 |
| Kịch bản cô lập dùng **bản đã cài** (`LOCALAPPDATA` tạm), lần chạy cuối | 20 | 0 | 0 |
| Smoke chỉ đọc trên dữ liệu thật, sau mỗi vòng | 7 | 0 | 0 |

Diễn biến các lần chạy kịch bản cô lập:
- Lần 1: hỏng do script test của tôi. Hàm `Cli` trùng alias `cli` = `Clear-Item`, và hàm `R` trùng alias `Invoke-History`.
  Đã kiểm tra: cả 32 lệnh `Clear-Item` thất bại vì đích không tồn tại, không file nào bị tác động.
- Lần 2: 15/19.
- Lần 3: 18/19. Kịch bản 8 FAIL do fixture của tôi: tiến trình giả thoát ngay.
- Lần cuối: 20/20.

Một lần chạy toàn bộ backend có **1 FAIL bấp bênh** (101/102), do kiểm tra thời gian quá chặt. Đã sửa; chạy lại
storage 3 lần liên tiếp 22/22, toàn bộ 102/102.

### 5. Bằng chứng ứng dụng dùng đúng database thật

- `GET /api/system/paths`: `db_path = D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, mọi nguồn = `storage.json`.
- Log khởi động 07:45:52Z: `version 1.1.0`, cùng `db_path`, `path_sources = storage.json`, `db_created_now = false`.
- Smoke chỉ đọc: database dự kiến, integrity + FK, lô ACTIVE không đổi, lịch sử forecast không đổi, diagnostics, UI —
  7/7 đạt.
- Chỉ có 2 file `app.db` trên các vị trí liên quan: DB thật trên ổ D và bản lưu trữ có chủ đích
  `…\DemandForecast\db.migrated-20261014_102304\app.db`.
- Không có dòng `ERROR` trong `logs\runtime\app.log` kể từ 13:50; `server.err.log` = 0 byte.
- Scheduler chạy được: slot D0 14:00 thành công (snapshot `SNP-20261014070022-D80BF9`).

### 6. Cấu hình, storage ID, integrity, FK, schema

| Mục | Giá trị |
|---|---|
| `%LOCALAPPDATA%\DemandForecast\storage.json` | data `…\data\runtime`, logs `…\logs\runtime`, backups `…\backups`, reports `…\reports`, `allow_create = false`. SHA-256 `8D79DBDD…FDE047`, **không đổi** suốt quá trình. |
| `storage_id` (cấu hình / marker `data\runtime\storage-id.json`) | `6cff0821634b0447` / `6cff0821634b0447` |
| Lịch sử di chuyển | `20261014_102304 SUCCEEDED`, khớp bản ghi ở đích; marker được tạo trong khoảng thời gian 03:23:04–03:23:06Z |
| `storage-verify` (bản đã cài) | `ok: true`, 0 vấn đề |
| `integrity_check` / FK / schema | ok / 0 / v2 (`0001`, `0002`) |
| `runtime.json` | pid/port khớp tiến trình đang chạy; token **không ghi vào báo cáo** |

### 7. Dữ liệu trước/sau

So với ảnh chụp trước mỗi vòng: **không thay đổi** số dòng của bất kỳ bảng nào, đối tượng schema, các lô, dữ liệu
dòng hay cấu hình ứng dụng.

| Mục | Hiện tại |
|---|---|
| Lô ACTIVE | `DEMO-20261014042925-CB692D` (1 lô DEMO ACTIVE) |
| `import_batches` | 5 (1 ACTIVE + 4 REPLACED) |
| `order_lines` / `demand_daily` | 93 157 / 38 533 (tổng 1 015 057) |
| `d0_snapshots` | 3. Tăng từ 2 lên 3 lúc 14:00 do scheduler, ngoài các khoảng cài đặt; đây là hoạt động bình thường. |
| `forecast_runs` / `training_runs` | 0 / 0 |

### 8. Lỗi còn tồn tại, rủi ro, rollback

**Rollback đã xác minh:**
- **Dữ liệu:** các backup ở mục 3 đã được giải nén và đọc lại được. Khôi phục bằng `scripts\stop.ps1` rồi
  `scripts\restore.ps1 -File <backup>`; restore kiểm tra integrity và tạo bản `pre-restore` trước khi thay. Luồng này
  có test backend; tôi **không** chạy restore trên dữ liệu thật vì không cần.
- **Lưu trữ:** `rollback-storage.ps1` và `storage-rollback` chạy đúng trong môi trường cô lập với bản đã cài.

**Rủi ro và giới hạn còn lại:**
1. **Không rollback được bản chương trình cũ.** Cài cùng số phiên bản 1.1.0 nên thư mục bản trước đã bị thay thế
   (đúng thiết kế của `install.ps1`). Dữ liệu không bị ảnh hưởng (schema không đổi). Khuyến nghị: lần phát hành sau
   tăng số phiên bản (vd. 1.1.1) để bản cũ được giữ song song.
2. **Chưa thử trên máy Windows khác.** Gói portable tự chứa Python và thư viện; đã cài và chạy thử trong môi trường
   cô lập trên máy này.
3. **Giới hạn đường dẫn:** nếu thư mục cài quá dài (> ~120 ký tự) trên máy tắt Long Paths, numpy không nạp được DLL.
   Đường dẫn cài mặc định trên máy này dài 135 ký tự tính tới file sâu nhất và chạy bình thường.
4. Bản 1.0.0 vẫn còn cài, nhưng không mở được DB schema v2. File chặn `db` ngăn nó tạo DB rỗng. **Không chạy 1.0.0.**
5. Mỗi vòng cài dừng ứng dụng khoảng 1–2 phút. Không có job nào đang chạy lúc dừng, và việc dừng dùng API chính thức.

### 9. Việc cần người dùng làm

Không bắt buộc. Ứng dụng đang chạy tại http://127.0.0.1:8765. Lần sau khởi động bằng shortcut **Demand Forecasting**
(trỏ tới `…\Programs\DemandForecast\1.1.0\Start.bat`).

Tùy chọn: kiểm tra bất kỳ lúc nào bằng
`%LOCALAPPDATA%\Programs\DemandForecast\1.1.0\python\python.exe -m app.cli storage-verify`
(chỉ đọc; exit 0 = nhất quán).

### Phụ lục — file đã kiểm tra hoặc sửa trong lượt này

- **Đã kiểm tra:** `backend/app/paths.py`, `storage_migrate.py`, `cli.py`, `messages.py`; `scripts/install.ps1`,
  `_common.ps1`, `start.ps1`, `stop.ps1`, `repair-storage.ps1`, `build-package.ps1`; `backend/tests/test_storage.py`
  (và các test DB, scheduler, demo); `reports/storage_json_investigation_20261014_121904.md`; `dist/…/Install.bat`.
- **Đã sửa trong lượt này:**
  - `backend/app/cli.py`: `--apply`.
  - `backend/app/paths.py`, `storage_migrate.py`: đọc BOM, marker hỏng → từ chối, cửa sổ thời gian marker.
  - `scripts/install.ps1`: chốt chặn khi chương trình đang chạy.
  - `scripts/repair-storage.ps1`: chuyển `--apply`.
  - `docs/02_kien_truc_du_lieu/LUU-TRU.md`.
  - `backend/tests/test_storage.py`: thêm 3 test.
- **Log:** `logs\development\upgrade_install_20261014_135440.log`, `upgrade2_install_*.log`, `upgrade3_install_*.log`,
  `tests_20261014_142547.log`. Output của các bước Python trong installer hiển thị ra console nên không có trong các
  file log `upgrade*_install`.
