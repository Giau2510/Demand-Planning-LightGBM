# Demand Forecasting 1.2.6: xác minh trạng thái sau lần deploy tự động

**Trạng thái chính: `DEPLOYED_AND_VERIFIED`. Độ tin cậy: cao.**

- Task Windows chạy lúc 19:05 ngày 18/10/2026 và nâng production từ 1.2.5 lên 1.2.6, hoàn tất lúc 19:16:33.
- Sáng 19/10 tôi kiểm tra lại độc lập, trên production đang chạy, không dựa vào file task tự ghi:
  - app 1.2.6 phản hồi bình thường ở cả ba điểm: cổng nội bộ, proxy chỉ đọc và link công khai;
  - proxy vẫn chặn ghi (405) và trang quản trị (403);
  - lịch D-1, D-0 và huấn luyện giữ nguyên cấu hình;
  - backup trước deploy đọc được;
  - hai lịch mới đã thực sự chạy: backup forecast cuối ngày lúc 23:55 và chốt actual cuối ngày lúc 23:59 ngày 18/10, cả hai `SUCCEEDED`.
- Không phát hiện lỗi nghiêm trọng, job trùng hay job treo.

Còn một số việc chưa thể xác minh vì chưa tới giờ chạy (mục 9). Không mục nào cần rollback.

Quy ước trong các bảng:

| Ký hiệu | Nghĩa |
|---|---|
| `PASS` | Đã kiểm tra, đạt |
| `FAIL` | Đã kiểm tra, không đạt |
| `UNKNOWN` | Có kiểm tra nhưng chưa đủ bằng chứng để kết luận |
| `NOT_CHECKED` | Chưa kiểm tra, có nêu lý do |

`UNKNOWN` và `NOT_CHECKED` không được tính là `PASS`.

## 1. Kết luận theo tiêu chí `DEPLOYED_AND_VERIFIED`

| Tiêu chí | Kết quả | Bằng chứng độc lập (19/10, giờ VN) |
|---|---|---|
| Production đang chạy 1.2.6 | PASS | Ba điểm đều trả về `{"ok":true,"version":"1.2.6"}`: `GET /api/health` tại 127.0.0.1:8765, proxy 8766 và link công khai. `current.txt` = 1.2.6. Tiến trình app pid 13820 chạy từ `...\Programs\DemandForecast\1.2.6\python\python.exe`, khởi động 18/10 19:15:46. `db_version` = 6. |
| Health check và các lớp bảo vệ | PASS | Health 200 ở cả ba điểm. Proxy và link: trang quản trị `/api/system/paths` và `/api/system/backups` trả 403; POST/PUT/DELETE trả 405. |
| Backup trước deploy đọc được | PASS | Đọc lại lúc 03:45 (mục 6): CRC đúng, `integrity_check ok`, schema 4, SHA-256 khớp số liệu lúc deploy. |
| Lịch hiện hữu không đổi | PASS | Cấu hình D-1, D-0 và huấn luyện giống hệt baseline lúc 19:05 (mục 7). |
| Hai lịch mới được scheduler nạp, cấu hình đúng | PASS | Cả hai `ON`, `loaded_by_scheduler=true`, runtime `REGISTERED`, đúng 23:55 / 23:59 `Asia/Ho_Chi_Minh`. Cả hai đã chạy thật một lần và `SUCCEEDED` (mục 8). |
| Không có lỗi nghiêm trọng hoặc job trùng | PASS | `server.err.log` rỗng; `server.out.log` có 0 dòng ERROR/WARNING kể từ khi deploy. Không có idempotency key trùng. Job duy nhất đang hoạt động là D-1 ngày 19/10 ở trạng thái chờ tín hiệu, đúng thiết kế (`stale=false`). |

## 2. Thời gian kiểm tra

- Ngày 2026-10-19, từ 03:40:06 đến khoảng 03:47 giờ máy.
- Timezone Windows là `SE Asia Standard Time` (UTC+07:00), trùng giờ Việt Nam; lúc 03:40:06 VN là 2026-10-18 20:40:06 UTC.
- Mốc thời gian lấy từ API là UTC; các mốc trong báo cáo đã đổi sang giờ VN, trừ chỗ ghi rõ UTC.

## 3. Task Scheduler

| Mục | Giá trị | Kết quả |
|---|---|---|
| Task `DemandForecast-Deploy-1.2.6` | Còn tồn tại; là task DemandForecast duy nhất trên máy | PASS |
| State | `Ready` (không bị disabled) | PASS |
| LastRunTime | 2026-10-18 19:05:00 | PASS |
| LastTaskResult | 0 (0x0) | PASS |
| NextRunTime | Trống: trigger chỉ chạy một lần, mốc đã qua | PASS |
| NumberOfMissedRuns | 0 | PASS |
| Trigger | Một lần, `2026-10-18T19:05:00+07:00`, enabled | PASS |
| Action | `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ...\scratchpad\p6\deploytask126.ps1`, có `-Target prod -Sha 0464EEDA...6171 -Day 2026-10-18 -WindowStart 19:00 -WindowEnd 22:00 -DeployDeadline 21:30 -D0Slot 18:00`. Tham số không chứa token hay credential. Working directory là `...\scratchpad\p6`. | PASS |
| Script thực tế | Vẫn còn; SHA-256 `350F754B7B32A659E34276B2AF1F4A8145A37045FB718AD3717711ABA684B70E`, sửa lần cuối 18/10 16:59:10. Khớp bản đã diễn tập đạt (lần 3). | PASS |
| Điều kiện chạy | User Giau Vo, Interactive, Limited; IgnoreNew; StartWhenAvailable; không đánh thức máy; giới hạn 4 giờ | PASS |
| Tiến trình deploy còn chạy | Không có (0 tiến trình PowerShell liên quan đến deploy, install, restore, rollback hay poller) | PASS |
| Event log `Microsoft-Windows-TaskScheduler/Operational` | 0 sự kiện cho task này (lịch sử task có vẻ chưa được bật trên máy) | UNKNOWN |

Task không thể tự chạy lại:
- trigger chỉ chạy một lần và đã qua;
- script tự từ chối khi khác ngày `-Day 2026-10-18`;
- script dừng nếu `done.json` đã tồn tại.

## 4. Nguồn bằng chứng

| Nguồn | Có tìm thấy | Nội dung chính |
|---|---|---|
| `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p6\prod_state\result.json` | Có (25,308 byte, 19:20:27) | `status: DEPLOYED_AND_VERIFIED`; mọi bước `ok`; `failed: []`; `issues: []` |
| `...\p6\prod_state\task.log` | Có | Diễn biến (giờ VN) ở bảng ngay dưới |
| `...\p6\prod_state\done.json` | Có | `DEPLOYED_AND_VERIFIED`, `finished_vn 2026-10-18 19:20:27` |
| `...\p6\prod_state\deploy_run.txt` | Có | Precheck OK → backup online → xác nhận → install 1.2.6 (migration 5 và 6) → `doctor` OK → `UPGRADE OK: 1.2.5 -> 1.2.6` |
| `D:\Buymed\Lightgbm AI\logs\runtime\deploy-20261018-190932.log` (transcript chính thức của `deploy-upgrade.ps1`, nằm ngoài TEMP) | Có (108 dòng, kết thúc 20261018191633) | Cùng nội dung với `deploy_run.txt` |
| Mục K của `reports\demandforecast_v126_final_release_and_deploy.md` | Có | Task tự ghi lúc 19:20; khớp với `result.json` |
| `poll_app.csv`, `poll_link.csv` | Có | Thời gian gián đoạn (mục 9) |
| `pre.json`, `post.json`, `final.json` cùng các bản sao `pre.db`, `post.db`, `final.db` | Có | Fingerprint DB trước, sau và cuối cùng |
| Event log của Task Scheduler | Không có sự kiện | Xem mục 3 |

Diễn biến trong `task.log`:

| Giờ (VN) | Sự kiện |
|---|---|
| 19:05:01 | Bắt đầu. Job D-0 18:00 (`JOB-20261018110020-382382`) đã `SUCCEEDED`. |
| 19:05:31 | Gate PASS |
| 19:08:24 | Backup đã kiểm tra |
| 19:09:01 → 19:16:33 | `deploy-upgrade -ConfirmToken UPGRADE-1.2.6`, exit 0 sau 451.3 s |
| 19:19:00 | Hậu kiểm PASS; bật eod và close, cả hai `verified=true` |
| 19:20:27 | Kết thúc: `FINAL DEPLOYED_AND_VERIFIED (0)` |

Các file trong TEMP chỉ là bằng chứng phụ. Kết luận của báo cáo dựa trên kiểm tra live ở các mục 1, 5, 7 và 8.

## 5. Phiên bản production

| Kiểm tra | Giá trị | Kết quả |
|---|---|---|
| `GET /api/health` (nội bộ) | `version 1.2.6` | PASS |
| `GET /api/system/status` | version 1.2.6, `db_version` 6, nguồn `BIGQUERY`, forecast `FCR-20261018043737-798B4D` `PUBLISHED`, data dir `D:\Buymed\Lightgbm AI\data\runtime` | PASS |
| `current.txt` | 1.2.6 | PASS |
| Thư mục cài đặt | Có đủ 1.0.0 … 1.2.5 và 1.2.6. Bản 1.2.5 còn nguyên để rollback. | PASS |
| `storage.json` | SHA-256 `8D79DBDDC960B10964F3B137F352D9AD54D39F08C52EF841418781ED00FDE047`, không đổi so với trước deploy | PASS |
| DB | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, 572,317,696 byte, WAL 0 byte | PASS |
| `data-check` (1.2.6, mode=ro) | `WARN`, 24 kiểm tra. Chỉ một WARN, có từ trước: `forecast_series_meta` của run cũ `FCR-20261014080621-8D88F1`. | PASS (không có lỗi mới) |

## 6. Backup và checksum artifact

| Đối tượng | SHA-256 | Kiểm tra lại 19/10 03:45 | Kết quả |
|---|---|---|---|
| Gói `dist\DemandForecast-1.2.6-win64-portable.zip` (92,248,384 byte) | `0464EEDA8B767909000974A30718663F6558872F8372604235F72E2BB36C6171` | Khớp file `.sha256` và báo cáo release. Không build lại, không đổi tên. | PASS |
| `backups\backup-20261018-190701-cli.zip`: backup do task tạo bằng `backup.ps1` của 1.2.5 | `C8F38FD34E2679256694A13DB1C8E29E3CA24FE8F0EF58A0A308E1D9DBE5E38D` | CRC OK, 9 entry, 8 model, `integrity_check ok`, schema 4, 24 bảng | PASS |
| `backups\backup-20261018-190932-manual.zip`: backup online của `deploy-upgrade` trước khi xác nhận | `52788C13D5431C1F835C9F8C78A65426C26C29BB07EEFAFB0D16780810B2A091` | CRC OK, 9 entry, 8 model, `integrity_check ok`, schema 4, 24 bảng | PASS |
| `backups\backup-20261018-191235-pre-migration-v4.zip` (76,269,611 byte) | — | Có mặt. Do install tạo trước khi migrate. Không đọc lại. | NOT_CHECKED (không cần cho rollback) |
| `backups\backup-20261018-191344-cli.zip` (76,274,150 byte) | — | Có mặt. Do install tạo sau khi migrate (schema 6). Không đọc lại. | NOT_CHECKED |

- Thư mục backup có 50 file (khoảng 1,568 MB); không file nào bị xóa.
- Retention chưa từng chạy với `-Apply`.

## 7. Health, proxy và các lịch hiện hữu

| Kiểm tra | Kết quả đo | Kết quả |
|---|---|---|
| URL production | Link `https://volumes-jean-angels-configurations.trycloudflare.com` vẫn hoạt động, health 200, version 1.2.6 | PASS |
| Tiến trình | app 13820 (1.2.6, cổng 8765); proxy 26416 (python 1.2.1, `--upstream-port 8765 --listen-port 8766`, khởi động 18/10 10:09:03, không đổi); cloudflared 31076 (tunnel tới 8766, khởi động 17/10 16:54:45, không đổi) | PASS |
| `GET /__remote/health` của proxy | 200, `upstream: true`. Nhãn `proxy: "1.2.5"` giống lúc 17:47 trước deploy. | PASS |
| Proxy: trang quản trị | 403 cho `/api/system/paths` và `/api/system/backups`, qua cả proxy lẫn link | PASS |
| Proxy: ghi | 405 cho POST, PUT và DELETE, qua cả proxy lẫn link | PASS |
| D-1 | ON, 03:00, fallback 05:00, poll 30 phút. `enabled_at` vẫn 2026-10-17 23:06:27. Scheduler đã nạp. Khớp baseline `True 03:00 05:00 30`. | PASS |
| D-0 | ON, 08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00, `LATEST_ONCE`. `enabled_at` vẫn 2026-10-17 23:06:28. Đã nạp. Khớp baseline. | PASS |
| Huấn luyện | ON, 09:00, `SKIP`. Đã nạp. Khớp baseline. | PASS |
| Nguồn dữ liệu | `BIGQUERY`, scope `BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm` | PASS |
| Scheduler | `running=true`; tick gần nhất 03:43:25 VN; heartbeat 03:43:25; đã nạp cả năm flow d1, d0, train, eod, close | PASS |
| Job đang hoạt động | Một job: `JOB-20261018200019-DE2F7C`, `D1_SYNC:2026-10-19`, `RETRY_WAIT` `WAITING_FOR_SIGNAL`. Tạo 03:00:19 đúng lịch, lần poll gần nhất 03:30:23, `stale=false`. Không có tiến trình deploy chạy song song. | PASS (job đang chạy, xem mục 9) |
| Job trùng | 0 idempotency key trùng trong 60 job gần nhất. Cột này cũng có ràng buộc UNIQUE trong DB. | PASS |
| Log server kể từ deploy | `server.err.log` 0 byte. `server.out.log` có 21 dòng, 0 ERROR, 0 WARNING. | PASS |

## 8. Hai lịch mới

| Thuộc tính | Backup forecast cuối ngày (`eod`) | Chốt actual cuối ngày (`close`) |
|---|---|---|
| Cấu hình lưu trong DB | `enabled=true`, `23:55`, `Asia/Ho_Chi_Minh`, `enabled_at 2026-10-18T19:19:00+07:00` | `enabled=true`, `23:59`, `Asia/Ho_Chi_Minh`, `enabled_at 2026-10-18T19:19:00+07:00` |
| Giá trị mặc định | OFF / 23:55 / Asia/Ho_Chi_Minh | OFF / 23:59 / Asia/Ho_Chi_Minh |
| Lần sửa cấu hình gần nhất (audit) | 19:19:00: `eod_enabled`, `eod_enabled_at` (audit 149–150) | 19:19:00: `close_enabled`, `close_enabled_at` (audit 151–152) |
| Trạng thái flow | `ON` | `ON` |
| Đã được scheduler nạp | `loaded_by_scheduler=true`; scheduler `loaded.flows.eod=true` | `loaded_by_scheduler=true`; scheduler `loaded.flows.close=true` |
| Runtime | `REGISTERED` (không có job đang chạy) | `REGISTERED` (không có job đang chạy) |
| Lần chạy kế tiếp | 2026-10-19 23:55, 20/10 23:55, 21/10 23:55 | 2026-10-19 23:59, 20/10 23:59, 21/10 23:59 |
| Lần chạy gần nhất | `JOB-20261018165527-5877DF` `EOD_FORECAST_SNAPSHOT:2026-10-18`. Trigger `SCHEDULE`, 23:55:27 → 23:55:34, `SUCCEEDED`, 1 lần thử. | `JOB-20261018165927-FD233D` `ACTUAL_CLOSE:2026-10-18`. Trigger `SCHEDULE`, 23:59:27 → 23:59:28, `SUCCEEDED`, 1 lần thử. |
| Kết quả ghi | Snapshot `FES-20261018165531-ADB329`, `COMPLETE` (`ALL_7_DAYS`), nguồn `FCR-20261018043737-798B4D`, 119,889 dòng cho các ngày 19/10–25/10. Audit 153. | Close `ACL-20261018165927-46D45C` revision 1, `CLOSED_UNVERIFIED`, nguồn D0 `SNP-20261018110022-946C47` (slot 18:00), 2,071 dòng, tổng 34,026, cutoff 23:59. Đã đối chiếu 1 ngày, không có revision mới. Audit 154. |
| Đối chiếu số dòng | `data-check`: `forecast_eod_snapshots` 1 và `forecast_eod_snapshot_values` 119,889 | `data-check`: `actual_closes` 1 và `actual_close_values` 2,071 |
| Màn hình lịch sử | `/api/history/overview` thấy backup ngày 19/10 trỏ tới `FES-20261018165531-ADB329` | — |
| Kết quả | PASS | PASS (`CLOSED_UNVERIFIED` là trạng thái đúng thiết kế, xem mục 9) |

Mỗi lịch có đúng một job cho ngày 18/10: lịch sử của cả hai flow chỉ có một dòng, và không có lần bị bỏ qua. Không có job day-end nào bị tạo lùi ngày cho các mốc trước 19:19.

## 9. Vấn đề, phần chưa xác minh và rủi ro còn lại

| # | Mục | Trạng thái | Chi tiết |
|---|---|---|---|
| 1 | D-1 ngày 19/10 | UNKNOWN (đang chạy) | Job tạo đúng 03:00:19 dưới 1.2.6, đang chờ tín hiệu hoàn tất của BigQuery (poll 30 phút, fallback 05:00). Hôm qua, khi còn chạy 1.2.5, D-1 theo lịch kết thúc `FAILED SOURCE_INCOMPLETE` lúc 06:08 VN (cảnh báo `RETRIES_EXHAUSTED`). Đó là vấn đề thời điểm có dữ liệu ở nguồn, có từ trước deploy. Nếu hôm nay lặp lại, huấn luyện 09:00 sẽ chờ D-1 (`TRAIN_WAITING_FOR_TODAY_D1`). |
| 2 | D-0 dưới 1.2.6 | NOT_CHECKED | Chưa có slot D-0 nào chạy trên 1.2.6; slot đầu là 19/10 08:00. |
| 3 | Huấn luyện dưới 1.2.6 | NOT_CHECKED | Slot đầu là 19/10 09:00. Huấn luyện chỉ chạy sau khi D-1 hôm nay thành công. |
| 4 | Chốt actual ngày 18/10 ở `CLOSED_UNVERIFIED` | Đúng thiết kế; việc đối chiếu chưa quan sát được (UNKNOWN) | Chốt từ D0 luôn là "Đã chốt – cần xác minh". Chỉ D-1 chạy theo tín hiệu hoàn tất mới cho `CLOSED_VERIFIED` (`docs/LICH-SU-FORECAST.md`). Production chưa cấu hình tín hiệu hoàn tất. Chưa thấy trên production bước D-1 đối chiếu lại một ngày đã chốt. |
| 5 | Gián đoạn khi deploy | Đã xảy ra, trong cửa sổ được phép | Link không trả 200 trong 196.7 s (19:12:35 → 19:15:51). App nội bộ không trả 200 trong 195.7 s. Từ 19:16:48 ổn định ở 1.2.6. |
| 6 | Rollback | Rủi ro mất dữ liệu nếu thực hiện | `rollback-version -To 1.2.5 -CheckOnly` trả exit 3 vì DB đã ở schema 6. Rollback chỉ làm được bằng cách restore `backup-20261018-190932-manual.zip` bằng `restore.ps1` của 1.2.5. Mọi thứ ghi sau 19:09:32 ngày 18/10 sẽ mất, gồm snapshot `FES-…ADB329`, close `ACL-…46D45C` và D-1 ngày 19/10 khi hoàn tất. Hiện không có lý do để rollback. |
| 7 | `GET /api/system/status` chậm | UNKNOWN (quan sát) | Mất 66.3 s; lúc 17:47 trên 1.2.5 là 44.8 s. Cloudflare cắt request ở 100 s. Chưa rõ nguyên nhân (tải máy, DB lớn hơn 12 MB). Health và các trang khác phản hồi bình thường. |
| 8 | Bằng chứng trong TEMP | Rủi ro mất bằng chứng | `result.json`, `task.log` và các file poll nằm trong thư mục scratchpad của phiên Claude dưới `%TEMP%`, có thể bị dọn. Transcript chính thức `logs\runtime\deploy-20261018-190932.log` và mục K của báo cáo release thì bền. |
| 9 | Task một lần vẫn còn đăng ký | Rủi ro thấp | `DemandForecast-Deploy-1.2.6` ở `Ready`, không có lần chạy kế tiếp. Ba lớp chặn chạy lại được nêu ở mục 3. Nên gỡ, cần chủ hệ thống đồng ý. |
| 10 | Git | Chưa push | HEAD `bd52203`, nhánh `main` đi trước `origin/main` 24 commit, cây làm việc sạch. `89d2f6a` và `bd52203` đều có. Message của `89d2f6a` có ký tự CR; không amend. |
| 11 | Event log của Task Scheduler | UNKNOWN | Không có bản ghi lịch sử. Bằng chứng task chỉ gồm `Get-ScheduledTaskInfo` và các file task tự ghi. |
| 12 | Cảnh báo cũ chưa xác nhận | Không liên quan đến deploy | 15 cảnh báo, mới nhất lúc 18/10 11:37 VN (trước deploy). Không có cảnh báo mới kể từ deploy. |

## 10. Hành động đã thực hiện trong lần xác minh này

Chỉ thao tác đọc:
- `Get-ScheduledTask` / `Get-ScheduledTaskInfo` và đọc event log;
- đọc file trong `prod_state`, mục K và transcript deploy;
- lệnh Git chỉ đọc;
- GET tới app tại 127.0.0.1:8765, proxy 8766 và link công khai;
- `app.cli paths` và `app.cli data-check` của bản cài 1.2.6 (mode=ro);
- tính SHA-256 của gói và hai backup;
- đọc hai file zip backup để kiểm tra CRC và integrity.

Probe ghi chỉ đi qua proxy và link, tới đường dẫn không tồn tại `/api/__readonly_probe`. Proxy chặn trước khi chuyển tiếp (405), nên không có request nào tới app.

File đã ghi:
- trong `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p7\`:
  - script `dayend_check.ps1`;
  - kết quả `prod_check_recovery.json`, `dayend_check.json`;
  - hai DB giải nén từ backup trong `bk\`, mỗi file khoảng 560 MB;
- báo cáo này;
- một đoạn bổ sung "K.1" ở cuối báo cáo release. Nội dung cũ, kể cả mục K, giữ nguyên.

Xác nhận những việc **không** làm:
- không deploy, không chạy lại hay sửa task, không tạo task mới;
- không rollback, không restore;
- không bật/tắt hay đổi lịch nào;
- không chạy job, migration hay retention;
- không ghi vào DB, `storage.json`, backup, BigQuery, forecast hay actual;
- không đổi URL, proxy hay cloudflared;
- không commit, push, amend hay sửa file trong Git;
- không xóa file nào.

Không có credential, token hay secret trong báo cáo này.

## 11. Bước tiếp theo đề xuất (tôi không tự thực hiện)

1. **Theo dõi sáng 19/10 (chỉ đọc, không cần phê duyệt):**
   - sau 05:10: D-1 ngày 19/10 (`JOB-20261018200019-DE2F7C`);
   - sau 08:10: slot D-0 08:00 đầu tiên dưới 1.2.6;
   - sau 09:30: huấn luyện 09:00.
   Nếu D-1 lại `FAILED SOURCE_INCOMPLETE` như hôm qua, đó là vấn đề thời điểm dữ liệu ở nguồn, không phải lỗi deploy. Việc chạy D-1 thủ công do chủ hệ thống quyết định.
2. **Gỡ task một lần đã hoàn tất (cần chủ hệ thống đồng ý):** `Unregister-ScheduledTask -TaskName "DemandForecast-Deploy-1.2.6" -Confirm:$false`. Lệnh này không ảnh hưởng production.
3. **Lưu bằng chứng bền (cần đồng ý vì tạo file ngoài scratchpad):** chép các file nhỏ trong `prod_state` sang một thư mục trong `reports\`, không chép các file `.db`. Gồm `result.json`, `task.log`, `done.json`, `deploy_run.txt`, `pre.json`, `post.json`, `final.json` và hai file poll CSV.
4. **Git (chủ hệ thống quyết định, theo `docs/GITHUB_WORKFLOW.md`):** cập nhật `docs/CHECKPOINT.md` với kết quả deploy bằng một commit mới, rồi push 24 commit đang đi trước `origin/main`.
5. **Chỉ khi phát hiện lỗi nghiêm trọng mới (hiện không có):** rollback bằng cách restore `backup-20261018-190932-manual.zip` với `restore.ps1` của 1.2.5, sau đó chạy `rollback-version -To 1.2.5`. Cách này mất dữ liệu ghi sau 19:09:32 ngày 18/10 và cần prompt phê duyệt riêng.
