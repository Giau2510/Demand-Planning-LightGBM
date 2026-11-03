# Demand Forecasting 1.2.7: kiểm tra trước triển khai (CheckOnly)

## 1. Kết luận

**Kết quả: `READY FOR DEPLOY APPROVAL`.**

- Cả 9 cổng bắt buộc đều PASS (mục 4).
- `deploy-upgrade.ps1 -CheckOnly` cho exit 0, `PRECHECK OK`, và không thay đổi gì trên production.

**Chưa deploy.** Kết quả này **không** tự cấp quyền triển khai: việc deploy cần anh/chị phê duyệt riêng, kèm khung giờ (mục 10).

**Điều kiện kèm theo:**
- Backup production hiện có còn toàn vẹn nhưng **cũ khoảng 19 giờ**: bản mới nhất lúc 18/10 19:13.
- Các thay đổi từ đó tới nay chỉ được bảo vệ bằng backup mà `deploy-upgrade` **bắt buộc** tạo và kiểm tra ngay trước khi dừng app. Các thay đổi đó gồm model đang dùng (promote lúc 13:05 hôm nay) và dữ liệu D-1 / D-0 ngày 19/10.
- Rollback 1.2.7 → 1.2.6 **không cần** restore (mục 6).

## 2. Thời điểm và môi trường

| Hạng mục | Giá trị |
|---|---|
| Thời gian | 19/10/2026, 14:10:33 – 14:26:18, giờ VN (UTC+07:00, Windows "SE Asia Standard Time") |
| Máy | Máy production Windows 11 Pro, cũng là máy build |
| Repository | `D:\Buymed\Lightgbm AI`, nhánh `main` |
| Cách làm | Chỉ đọc: GET tới `127.0.0.1:8765` / `8766` / `8767`, một GET `/api/health` qua link công khai, đọc metadata và hash file, mở zip ở chế độ đọc. Script nằm trong `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p12\` |

## 3. Kỳ vọng và thực tế

| Hạng mục | Kỳ vọng | Thực tế | Khớp |
|---|---|---|---|
| Version production | 1.2.6 | `/api/health` 1.2.6; `current.txt` 1.2.6; pid 13820 khởi động 18/10 19:15:46 | ✔ |
| Version release candidate | 1.2.7 | `VERSION` 1.2.7; `BUILD-INFO.version` 1.2.7; manifest 1.2.7 | ✔ |
| Commit | `ad9505c9275a6b39b44d5614e981baed33c019e9` | HEAD = `ad9505c9275a6b39b44d5614e981baed33c019e9`; `BUILD-INFO.commit` và manifest cùng giá trị; `dirty=false` | ✔ |
| Gói | `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.7-win64-portable.zip` | Có: 92.253.195 byte, sửa lần cuối 19/10 13:30:04 | ✔ |
| SHA-256 | `1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B` | Tự tính bằng `Get-FileHash`: `1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B`. File `.sha256` và `zip_sha256` của manifest cùng giá trị | ✔ |
| Script | `D:\Buymed\Lightgbm AI\deploy-upgrade.ps1` | **Không tồn tại ở đó.** Đường dẫn đúng là `D:\Buymed\Lightgbm AI\scripts\deploy-upgrade.ps1` (SHA-256 bắt đầu `c8ed93ff98153ee8`), **giống hệt** bản trong gói 1.2.7 và 1.2.6. Cú pháp tham số đúng như mô tả | sai lệch về đường dẫn (mục 8) |

## 4. Các cổng

| # | Cổng | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | SHA-256 của gói | **PASS** | Mục 3 |
| 2 | Toàn vẹn gói và version | **PASS** | (a) |
| 3 | HEAD và nguồn gốc release | **PASS** | (b) |
| 4 | CheckOnly an toàn và đạt | **PASS** | Mục 5 |
| 5 | Production health | **PASS** | Mục 7 |
| 6 | Backup production và rollback | **PASS**, có điều kiện | Mục 6 |
| 7 | Xung đột lịch hoặc job | **PASS** | Mục 7 |
| 8 | Điều kiện bất biến | **PASS** | Mục 7 |
| 9 | Không có lỗi nghiêm trọng hay UNKNOWN ảnh hưởng an toàn | **PASS** | Mục 8 |

**(a) Toàn vẹn gói và version:**
- `testzip` sạch; 7.158 entry, 7.136 file.
- **118/118** file có trong Git giống hệt từng byte blob của `ad9505c`.
- 0 file `backend/app` hay script nằm ngoài Git; 0 file Git bị thiếu.
- `web/` 3/3 file giống bản build của QA.
- **0 file cấm**: không DB, `storage.json`, credential, `.env`, log, backup, model hay `__pycache__`.
- Bundle giao diện không còn gọi `/api/dashboard`.
- Migrations trong gói: `0001`–`0006`, **giống hệt** gói 1.2.6, tức không có migration mới.

**(b) HEAD và nguồn gốc release:**
- HEAD đúng commit kỳ vọng; working tree sạch.
- Ahead 25 / behind 0 so với `origin/main` (ref local, **không fetch**).
- `BUILD-INFO` ghi cùng commit, `dirty=false`, source fingerprint `15990653C86D9DD1…`.
- 7 script vận hành (`deploy-upgrade`, `rollback-version`, `install`, `restore`, `backup`, `start`, `stop`) trong gói giống hệt repo.

## 5. CheckOnly

**Rà soát mã trước khi chạy.** File: `scripts\deploy-upgrade.ps1`, dòng 1–77; lệnh `exit 0` của CheckOnly nằm ở dòng 77. Trước dòng đó, script chỉ:

| Thao tác | Tính chất |
|---|---|
| Tính SHA-256 gói; mở zip `OpenRead` để đọc `VERSION` và tìm file giống credential | Chỉ đọc |
| Đọc `current.txt` | Chỉ đọc |
| `python -m app.cli paths` của bản 1.2.6 đã cài | `paths.describe()`, hàm thuần, "creates nothing". Không có `--check`, nên **không** gọi `ensure_storage` (hàm này mới tạo thư mục) |
| `python -m app.cli storage-verify` | `verify_storage()`: đọc `storage.json`, lịch sử storage và `storage-id.json`; mở DB bằng `?mode=ro` để chạy `integrity_check`, `foreign_key_check` và đọc schema. Cả hai lệnh CLI đều trả về **trước** bước bật log ra file (`setup_logging`) |
| Hash `storage.json`, đọc `runtime.json` | Chỉ đọc |
| `GET /api/health`, `GET /api/jobs?limit=50` | Chỉ đọc |
| Đọc kích thước DB và dung lượng trống của ổ | Chỉ đọc |

Transcript, backup online (`POST /api/system/backups`), bước xác nhận `UPGRADE-<version>`, `install.ps1`, stop / start và hậu kiểm đều nằm **sau** dòng 77.

Bằng chứng phụ: chính script này ở chế độ CheckOnly đã chạy trên production ngày 18/10 cho bản 1.2.6 (`reports/v126-deploy-evidence/prod_state/deploy_check.txt`) và cho `PRECHECK OK`.

**Lệnh đã chạy** (14:14:21–14:15:48; 86,8 s; **exit 0**):

```
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\scripts\deploy-upgrade.ps1" -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.7-win64-portable.zip" -ExpectedSha256 "1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B" -CheckOnly
```

**Output** (nguyên văn, không có secret):

```
== Demand Forecasting - kiem tra truoc nang cap / upgrade prechecks ==
  [OK]   package SHA256 1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B
  [OK]   package version 1.2.7
  [OK]   no credential files in the package
  [..]   installed version: 1.2.6
  [..]   database: D:\Buymed\Lightgbm AI\data\runtime\db\app.db
  [OK]   database present (drive reachable)
  [OK]   storage-verify ok
  [..]   storage.json: C:\Users\Giau Vo\AppData\Local\DemandForecast\storage.json sha256 8D79DBDDC960B10964F3B137F352D9AD54D39F08C52EF841418781ED00FDE047
  [OK]   running app 1.2.6 on port 8765
  [OK]   no active job
  [OK]   free space on D: ok
PRECHECK OK (check-only: nothing was changed).
```

Không có lỗi hay cảnh báo. Không nhập `UPGRADE-1.2.7`; nhánh triển khai không được gọi.

**Chứng minh không thay đổi.** Ảnh chụp chỉ đọc lúc 14:13:35 (trước), 14:16:00 (sau CheckOnly) và 14:24:30 (cuối lượt). Giữ nguyên ở cả ba thời điểm:
- `storage.json`: SHA-256 `8D79DBDD…E047`, 399 byte, sửa lần cuối 14/10;
- `storage-migrations.json`;
- `runtime.json`, `storage-id.json`;
- 10 file model (theo hash);
- 50 backup;
- cấu hình (6 mục) và lịch sử cấu hình;
- audit (dòng cuối vẫn là 167, D-0 14:00);
- danh sách job;
- tiến trình và cổng;
- dấu vân tay thư mục cài 1.2.6 (`28B5409E367B807C`, 7.136 file);
- số file `.pyc` (62; CheckOnly không sinh thêm bytecode);
- kích thước DB 642.715.648 byte.

Chỉ đổi những thứ do app production tự cập nhật:
- mtime của `app.db`: trùng thời điểm heartbeat mỗi phút của scheduler;
- `last_tick`;
- working set của tiến trình.

`server.out.log` có dòng cuối là job D-0 lúc 14:00:22, tức không có dòng nào từ lúc chạy CheckOnly. File: `scratchpad\p12\prod_snapshot_*.json`, `snapdiff.py`.

## 6. Backup production và rollback

**Backup hiện có** (`D:\Buymed\Lightgbm AI\backups`, chỉ đọc):
- Tổng: 50 zip, 1.643.956.836 byte, từ `backup-20261014-102304-pre-storage-migration.zip` tới `backup-20261018-191344-cli.zip`.
- Định dạng (`backup.py` của 1.2.6): `db/app.db` lấy bằng SQLite backup API (nguồn mở `mode=ro`), **được kiểm `integrity_check` trước khi ghi zip**, cùng mọi file trong `models/`.
- Không có manifest hay checksum trong zip. Checksum bên ngoài là SHA-256 đã ghi ở báo cáo trước.

| Backup | Byte | SHA-256 | CRC (`testzip`) | Nội dung | Ghi chú |
|---|---|---|---|---|---|
| `backup-20261018-191344-cli.zip` (18/10 19:14, do `install.ps1` 1.2.6 tạo sau migrate) | 76.274.150 | `C8BE1316…F168` | OK | `db/app.db` (560.431.104 byte) + 8 model | Giải nén DB ra scratchpad rồi mở **chỉ đọc**: `integrity_check` **ok**, 0 vi phạm khóa ngoại, **schema 6**, 29 bảng; `demand_daily` 1.390.923 dòng, 6 forecast run, 6 training run, 54 job, 24 snapshot D-0. Dữ liệu tới: audit cuối 18/10 19:09:52, demand tới 17/10. Bản sao đã xóa sau khi kiểm |
| `backup-20261018-191235-pre-migration-v4.zip` | 76.269.611 | `800B1D9A…FBA9` | OK | DB + 8 model | schema 4 (trước migrate) |
| `backup-20261018-190932-manual.zip` (backup online của deploy 1.2.6) | 76.269.536 | `52788C13…A091` | OK | DB + 8 model | **khớp** SHA đã ghi ở `demandforecast_v126_deployment_state_recovery.md` |
| `backup-20261018-190701-cli.zip` | 76.269.536 | `C8F38FD3…E38D` | OK | DB + 8 model | **khớp** SHA đã ghi |

**Độ phủ và giới hạn (RPO):**
- Backup mới nhất dừng ở 18/10 19:13. Nó **không** chứa:
  - D-1 ngày 19/10 (dữ liệu 18/10);
  - backup forecast cuối ngày và các revision chốt actual sau 19:13;
  - snapshot D-0 ngày 19/10 lúc 08, 10, 12 và 14 giờ (không đọc lại được từ BigQuery);
  - training, model **`MV-20261019-120018-61C1` đang dùng** (2 file model **chưa có trong backup nào**), forecast `FCR-20261019060524-9DE420`;
  - job và audit ngày 19/10.
- Backup chứa DB (gồm cấu hình, lịch sử, job, audit) và model. **Không** chứa:
  - `storage.json` (399 byte, nằm ngoài; không đổi từ 14/10; hash đã ghi);
  - `storage-id.json` và bản ghi migration storage trong thư mục data (không đổi từ 14/10);
  - log;
  - secret trong Windows Credential Manager (theo thiết kế);
  - thư mục chương trình (mỗi version được giữ song song);
  - proxy và tunnel (file repo và `%LOCALAPPDATA%\DemandForecastRemote`).

**Backup mới khi deploy (bắt buộc theo script, cần làm trong bước deploy được duyệt):**
1. `deploy-upgrade.ps1` bước 2 gọi backup online qua app đang chạy (`POST /api/system/backups`). Backup được kiểm `integrity_check` khi tạo, rồi script kiểm có `db/app.db` trong zip. Script in `backup: <file> sha256 <hash>` **trước** bước xác nhận. Nếu bước này lỗi, script dừng mà chưa dừng app.
2. Sau khi dừng app, `install.ps1` chạy thêm `app.cli backup` (đã kiểm). Nếu lỗi, cài đặt bị hủy và không có gì thay đổi.
3. Theo diễn tập: 2 file khoảng 86–95 MB. Ổ D còn trống 76,4 GB.

Lượt này **không** tạo backup, đúng phạm vi CheckOnly.

**Rollback 1.2.7 → 1.2.6:**

| Kiểm tra | Kết quả |
|---|---|
| Gói rollback 1.2.6 | `DemandForecast-1.2.6-win64-portable.zip`, SHA-256 `0464EEDA…6171`, khớp `.sha256` và manifest; `testzip` sạch |
| Bản 1.2.6 đã cài (thứ `rollback-version` thực sự dùng) | `%LOCALAPPDATA%\Programs\DemandForecast\1.2.6`: **7.136/7.136 file giống hệt từng byte** gói 1.2.6; 0 file thiếu, 0 file khác; ngoài ra chỉ có 1.323 file cache `.pyc`. Việc cài 1.2.7 vào thư mục riêng và giữ nguyên 1.2.6 |
| `scripts\rollback-version.ps1 -To 1.2.6 -CheckOnly` | **exit 0**, 1,1 s, "database schema 6; 1.2.6 supports up to 6 / [OK] rollback possible without restoring the database". Nhánh `-CheckOnly` chỉ đọc `current.txt`, gọi `app.cli paths`, mở DB `mode=ro` để đọc schema và **thoát ở dòng 27**, trước bước stop (dòng 31). Sau lệnh, `current.txt` vẫn 1.2.6 và health vẫn 1.2.6 |
| Schema sau khi deploy | 1.2.7 không có migration, nên vẫn schema 6. Rollback không cần restore |
| Diễn tập (bản sao, không thay bằng chứng production) | 38/38 PASS lúc 13:32–13:56: rollback 9,7 s, gián đoạn 3,1 s, mọi bảng giữ nguyên (`reports/demandforecast_v127_readiness_review.md`, mục G) |

**Quy trình rollback nếu cần:** `scripts\rollback-version.ps1 -To 1.2.6 -CheckOnly`, rồi `-ConfirmToken ROLLBACK-1.2.6`. Lệnh này dừng 1.2.7, khởi động 1.2.6 trên **cùng DB** và đặt `current.txt` = 1.2.6.

**Rủi ro khi rollback:**
- trang Tổng quan chậm trở lại;
- link xem từ xa trả 502 trong vài giây;
- không mất dữ liệu.

Restore backup chỉ cần khi DB hỏng, và khi đó sẽ mất những gì ghi sau backup được dùng.

## 7. Production và lịch (chỉ đọc)

| Hạng mục | Thực tế | Trạng thái |
|---|---|---|
| App | 1.2.6, pid 13820, `127.0.0.1:8765`, `/api/health` 200 (35–65 ms) | PASS |
| Proxy chỉ đọc | pid 26416, `127.0.0.1:8766`, `/__remote/health` `ok, upstream: true` | PASS |
| Tunnel | cloudflared pid 18992 → `http://127.0.0.1:8766`; metrics `127.0.0.1:8767` `/ready` 200; hostname `automated-speak-rehabilitation-available.trycloudflare.com`. `GET https://…/api/health` 200, 1.2.6 (5,0 s) | PASS |
| Cổng đang nghe | Chỉ 8765, 8766 và 8767, cả ba trên `127.0.0.1`. Cổng diễn tập 8878 và 8879 không mở | PASS |
| `storage.json` | Có, đọc được, 399 byte; SHA-256 `8D79DBDD…E047` trước = sau. Chỉ ghi tên khóa, không in nội dung. `storage-verify` ok | PASS |
| DB production | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, 642.715.648 byte. Integrity ok (qua `storage-verify`). Hai file `app.db.migrating-shm` / `-wal` từ 14/10 còn sót lại từ lần chuyển storage; không động tới | PASS |
| Scheduler | `running: true`, heartbeat mỗi phút, không có job đang chạy dở; cả 5 lịch được scheduler nạp | PASS |
| Job đang chạy | 0 PENDING / RUNNING / RETRY_WAIT. Job gần nhất: D-0 14:00 SUCCEEDED (14:00:11–14:00:22) | PASS |
| Slot kế tiếp | D-0 **16:00**, **18:00**; backup forecast cuối ngày **23:55**; chốt actual **23:59**; D-1 **03:00** (dự phòng 05:00); training **09:00** ngày 20/10 | — |
| Task Windows "Demand…" | 0 | PASS |

**Điều kiện bất biến (kỳ vọng = thực tế):**

| Hạng mục | Thực tế |
|---|---|
| D-0 | ON, 08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00, `LATEST_ONCE` |
| D-1 | ON, 03:00, dự phòng 05:00, poll 30 phút |
| Training | ON, 09:00, bù `SKIP` |
| Cuối ngày | eod 23:55 và close 23:59, Asia/Ho_Chi_Minh, ON |
| Quality gate | `wape_max` 0,6; `abs_bias_max` 0,2; `min_backtest_points` 200; `require_beat_baseline` false; `approved_by_business` false; `PUBLISH_WITH_WARNING`. Lịch sử mục `quality` trống, tức chưa từng bị sửa |
| Feature Price | `feature_price` **true**. Lịch sử `model` sửa lần cuối 17/10 01:26 UTC |
| Lần sửa cuối của các mục cấu hình khác | `schedule` 18/10 19:19 (bật close), `bigquery` 17/10, `general` 16/10. **Không có thay đổi nào hôm nay** |
| Nguồn đang dùng | BIGQUERY |

## 8. Sai lệch và rủi ro

| Mức | Hạng mục | Chi tiết |
|---|---|---|
| Sai lệch (không chặn) | Đường dẫn script | `D:\Buymed\Lightgbm AI\deploy-upgrade.ps1` không tồn tại; đúng là `scripts\deploy-upgrade.ps1`. Tham số khớp. Không đoán: đã đối chiếu file trong repo giống hệt bản trong gói |
| Medium | Backup hiện có cũ khoảng 19 giờ | Model đang dùng (promote 13:05 hôm nay) và dữ liệu ngày 19/10 chưa có trong backup nào. Bước 2 của deploy sẽ chụp lại; nếu bước đó lỗi, deploy tự dừng. Muốn khép khoảng trống **trước** deploy thì cần tạo một backup production thủ công (phê duyệt riêng) |
| Medium | Gián đoạn khi deploy | Diễn tập trên bản sao: khoảng 184 s không phản hồi, tổng khoảng 577 s. Deploy 1.2.6 thật hôm 18/10: link không trả 200 trong 196,7 s, tổng 451 s. Trong lúc đó link xem từ xa trả 502 |
| Low | Bước cài mở tab trình duyệt | `install.ps1` gọi `start.ps1` không kèm `-NoBrowser`, nên sẽ mở một tab tới 8765 trên máy production, như các lần deploy trước |
| Low | Production vẫn chậm trước khi deploy | `/api/system/status` khoảng 33 s (đo 10:53); bản sửa nằm trong 1.2.7 |
| Low | Quick Tunnel | URL tạm thời, không tự khởi động. Deploy không động tới proxy hay tunnel |
| — | UNKNOWN ảnh hưởng an toàn | Không có. Những điều chưa biết (thời gian gián đoạn thật, tốc độ thật sau deploy) không ảnh hưởng an toàn dữ liệu |

## 9. Thao tác đã thực hiện

| Thời gian | Thao tác | Tính chất |
|---|---|---|
| 14:10 | `git rev-parse`, `git status`, `git rev-list --left-right --count origin/main...HEAD` | Chỉ đọc, không fetch |
| 14:10–14:12 | Đọc mã `deploy-upgrade.ps1`, `cli.py`, `paths.py`, `storage_migrate.py`, `backup.py`, `rollback-version.ps1`, `install.ps1` (bản 1.2.6 đã cài và repo) | Chỉ đọc |
| 14:11–14:12 | `zipinfo127.py`, `pkgcheck127.py`, `Get-FileHash` hai gói | Mở zip để đọc |
| 14:13, 14:16, 14:24 | `prod_snapshot.ps1` (before / after_checkonly / final) | GET và metadata. Không gọi `/api/system/status`, `/api/dashboard` hay `/api/data-quality` (endpoint này có thể ghi) |
| 14:14:21 | `deploy-upgrade.ps1 … -CheckOnly` | exit 0, không thay đổi |
| 14:18 | `verify_backups.py`: đọc 4 zip, giải nén **một** `db/app.db` ra scratchpad, mở `mode=ro`, rồi xóa bản sao | Không ghi vào thư mục backups |
| 14:22 | `installed_vs_pkg.py` (thư mục 1.2.6 đã cài so với gói 1.2.6) | Chỉ đọc |
| 14:23:56 | `rollback-version.ps1 -To 1.2.6 -CheckOnly` | exit 0, thoát trước bước stop |
| 14:24 | `GET https://…trycloudflare.com/api/health` | Chỉ đọc |

**Xác nhận không làm:**
- deploy, upgrade, rollback hay uninstall;
- push, fetch, commit hay sửa source;
- training, inference, promote hay rollback model;
- chạy job D-0 / D-1 / EOD / close hay kích hoạt scheduler;
- sửa lịch, task, proxy, tunnel, cổng, `storage.json`, BigQuery hay DB;
- xóa, di chuyển hay ghi đè gói, backup, log, DB hay model;
- cleanup;
- restart bất kỳ tiến trình nào;
- tạo task hay backup.

File tạo ra: chỉ báo cáo này, và các file kiểm tra trong `scratchpad\p12`.

## 10. Còn thiếu và cần anh/chị phê duyệt

1. **Phê duyệt deploy** 1.2.7 lên production (riêng, rõ ràng).
2. **Chọn khung giờ.** Đề xuất **hôm nay 19:00–22:00**: sau khi job D-0 18:00 xong, trước lịch cuối ngày 23:55. Khi bắt đầu, kiểm lại không có job đang chạy (script tự kiểm).
3. **Khi deploy:**
   - chạy lại `scripts\deploy-upgrade.ps1 -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.7-win64-portable.zip" -ExpectedSha256 1351C920F5C98E0B82503D8A3AE7FA2278D64B98F39A0875FCAF2F9BC1578C3B -CheckOnly`, rồi chạy không có `-CheckOnly`;
   - người vận hành gõ `UPGRADE-1.2.7`;
   - ghi lại tên và SHA-256 của backup online mà script in ra trước bước xác nhận.
4. **Hậu kiểm sau deploy:**
   - version 1.2.7 ở `/api/health` và `current.txt`;
   - `storage.json` không đổi;
   - `data-check` chỉ đọc;
   - 5 lịch giữ nguyên;
   - proxy trả 403/405 qua link;
   - đo `/api/system/status` một lần;
   - mở trang Tổng quan qua link;
   - theo dõi slot 23:55 / 23:59 và D-0 kế tiếp.
5. **Rollback nếu cần:** `scripts\rollback-version.ps1 -To 1.2.6` (không restore; khoảng 10 s).
6. **Tùy chọn:** tạo một backup production thủ công **trước** khung deploy, để khép khoảng trống 19 giờ ngay từ bây giờ. Đây là thao tác ghi, cần phê duyệt riêng.
7. **Push Git** (25 commit): phê duyệt riêng nếu cần.

Tôi dừng ở đây; không có thao tác deploy, push, training hay job nào được thực hiện hoặc lên lịch.
