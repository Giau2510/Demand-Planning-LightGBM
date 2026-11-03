# Demand Forecasting 1.2.6: UI cấu hình hai lịch mới, release, diễn tập và deploy tự động trong khung đã duyệt

> **Kết luận tại thời điểm viết (18/10/2026 17:55 VN): `READY_TO_WAIT`.**
> Production vẫn là **1.2.5**, chưa có gì bị thay đổi.
> Đã đăng ký **một** task Windows `DemandForecast-Deploy-1.2.6`, kích hoạt **19:05**. Task:
> - chờ job D-0 18:00 thành công;
> - chạy lại toàn bộ gate;
> - tạo backup mới và kiểm tra đọc được;
> - deploy bằng `deploy-upgrade.ps1 -ConfirmToken UPGRADE-1.2.6` (chậm nhất bắt đầu 21:30);
> - hậu kiểm;
> - **chỉ khi hậu kiểm đạt** mới bật hai lịch mới qua API chính thức.
>
> Kết quả thật của lần deploy được task tự ghi vào **mục K** ở cuối báo cáo này.

Lịch sử phiên: lượt "FINAL RELEASE GATE" (15:20) đã cho 12/12 gate PASS với gói `BBD73386…09C3`. Lúc 15:45 chủ sở hữu đổi quyết định: hoàn thiện UI cấu hình hai lịch, build lại, diễn tập, rồi deploy một lần bằng cơ chế chờ bền vững. Gói `BBD73386…` chưa từng deploy và đã được thay bằng gói mới bên dưới.

## A. Khảo sát trước khi sửa (đọc source thực tế)

**Hai lịch mới đã có sẵn trên trang Lịch chạy dữ liệu:**
- card riêng `eod` (snapshot dự phòng) và `close` (chốt actual);
- công tắc, ô giờ, hiển thị timezone, trạng thái (OFF / ON / ON_NOT_READY / ON_NOT_LOADED / ON_SCHEDULER_STOPPED);
- lần chạy tới, lần chạy gần nhất kèm lỗi, lịch sử, nút lưu, cảnh báo "chưa lưu", hộp lỗi, nút "Chạy ngay 1 lần".

**Backend đã có:**
- `PUT /api/schedules/{flow}` có validation, lịch sử thiết lập, audit `SCHEDULE_CHANGED`, `Scheduler.reload()`;
- mặc định tập trung trong `ScheduleSettings` (TẮT, 23:55 / 23:59);
- scheduler và UI đọc cùng một thiết lập;
- chống job trùng bằng khóa idempotency theo ngày (`EOD_FORECAST_SNAPSHOT:<ngày>`, `ACTUAL_CLOSE:<ngày>`);
- giờ bị giới hạn trong 20:00–23:59.

**Còn thiếu hoặc hard-code (đã xử lý ở mục B):**
1. Timezone không phải cấu hình lưu trữ; API không kiểm tra timezone.
2. Hai lịch có thể đặt trùng một phút.
3. Bật ON không cần scheduler xác nhận: UI có thể báo "Đã bật luồng" dù scheduler chưa nạp.
4. Chưa có trạng thái runtime (đã đăng ký / đang chạy / chưa đăng ký), giá trị mặc định và thời điểm cập nhật cấu hình.
5. Chưa có chạy thử không ghi dữ liệu.
6. `actual_close.close_day(..., hhmm="23:59")` hard-code trong logic, cùng chữ "23:59" trong tiêu đề, thông báo, trang lịch sử và Excel.

## B. Thay đổi (commit `89d2f6a`, cục bộ, chưa push)

| Phần | Thay đổi |
|---|---|
| `settings_service.py` | `eod_timezone` / `close_timezone` (mặc định và chỉ chấp nhận `Asia/Ho_Chi_Minh`, vì ngày nghiệp vụ là ngày Việt Nam); hai lịch không được cùng phút; hằng `DAY_END_TIMEZONE` |
| `jobs/flows.py` | timezone là trường chỉnh được; `defaults`, `config_updated` (từ audit), `runtime.state` (`REGISTERED` / `NOT_REGISTERED` / `PENDING` / `RUNNING` / `RETRY_WAIT`). Bật `eod` / `close` chỉ khi scheduler đang chạy; sau khi lưu, `Scheduler.reload()` phải xác nhận, nếu không thì **tự trả về TẮT** (có audit lý do) và trả 409 `SCHEDULE_NOT_REGISTERED`. Hàm `preview()` |
| `api/schedule_routes.py` | `GET /api/schedules/{eod\|close}/preview`: chạy thử chỉ đọc |
| `forecast_backup.py` | `preview()`: run nguồn, trạng thái COMPLETE / INCOMPLETE / NO_SOURCE, số dòng, tổng, ngày thiếu (không có giá trị thì 0 dòng, không bao giờ điền 0) |
| `actual_close.py` | `preview()` và `changed_days()` (tách từ `reconcile`, dùng chung); `close_day` / `reconcile` đọc `close_time` từ cấu hình thay vì `"23:59"` |
| `messages.py`, `export_i18n.py`, `i18n.tsx` | mã `SCHEDULE_NOT_REGISTERED`; "23:59" → "cuối ngày" / "end of the day" (nói rõ "mặc định 23:59" ở chỗ cần) |
| `Schedules.tsx` | trên hai card: ô timezone, trạng thái scheduler runtime, mặc định và lần cập nhật cấu hình, cảnh báo trùng phút (chặn lưu), nút **Chạy thử (không ghi)** với kết quả, cảnh báo khi scheduler không xác nhận (không bao giờ báo "Đã bật" giả). Card D-1 / D-0 / huấn luyện giữ nguyên |
| Test | backend `test_v126_schedule_config.py` (mới, 21 trường hợp); hai test 1.2.6 cũ chỉnh theo quy tắc "bật phải được xác nhận" (không xóa assertion); test phủ proxy liệt kê chạy thử là "chỉ dùng trên máy" (proxy không đổi); frontend `v126.test.tsx` +5 |
| Tài liệu | `LICH-SU-FORECAST.md` mục 13, `SCHEDULER.md`, `CHANGELOG.md`, `CHECKPOINT.md` |

Chạy thử bị proxy chỉ đọc trả 403, nên không dùng được qua link từ xa. Đây là chủ đích: proxy không đổi; thao tác vận hành chỉ làm trên máy.

## C. Cấu hình hai lịch

| | Snapshot dự phòng (`eod`) | Chốt actual (`close`) |
|---|---|---|
| Mặc định (code, `ScheduleSettings`) | TẮT, 23:55, Asia/Ho_Chi_Minh | TẮT, 23:59, Asia/Ho_Chi_Minh |
| Ngay sau nâng cấp | TẮT (production không lưu khóa nào của hai lịch; migration không ghi thiết lập) | TẮT |
| Sau khi hậu kiểm đạt (task) | BẬT qua `PUT /api/schedules/eod`, scheduler phải xác nhận; lần chạy đầu 23:55 hôm nay | BẬT qua `PUT /api/schedules/close`, scheduler phải xác nhận; lần chạy đầu 23:59 hôm nay |
| Nếu hậu kiểm không đạt | giữ TẮT, `POST_DEPLOY_BLOCKED` | giữ TẮT |

Bật một lịch không chạy job ngay. Task kiểm tra điều này sau một tick scheduler: không có job cuối ngày nào được tạo. Snapshot và chốt giữ nguyên semantics:
- snapshot chỉ COMPLETE khi đủ mọi SKU × FC trong cả 7 ngày;
- thiếu actual không thành 0;
- chưa có tín hiệu hoàn tất thì trạng thái là "Đã chốt – cần xác minh";
- dữ liệu D-1 đến muộn tạo revision mới, không sửa đè;
- giữ retention 90 ngày, không có lịch dọn, không chạy `-Apply`.

## D. QA và gói phát hành

| Hạng mục | Kết quả | Loại |
|---|---|---|
| Backend (QA trong `release.ps1`, commit `89d2f6a`) | **493 passed, 7 skipped, 0 failed**. 7 skip = 2 `test_bq_real_semantics.py` + 5 `test_v121_d0_real_bq.py` (BigQuery thật, chỉ chạy khi `DF_REAL_BQ=1`) | unit / integration trên DB cách ly |
| Frontend | vitest **116/116** (18 file), typecheck 0, build 0 | unit (jsdom) / build |
| Lint | **NOT CONFIGURED** | — |
| Gói mới | `dist\DemandForecast-1.2.6-win64-portable.zip`, 92.248.384 byte, **SHA-256 `0464EEDA8B767909000974A30718663F6558872F8372604235F72E2BB36C6171`** (`Get-FileHash` = `.sha256`) | |
| Nội dung gói | BUILD-INFO: commit `89d2f6a9a6e2…`, `dirty=false`, fingerprint `82847749…6891F`, built_at 16:06:27; 118/118 file nguồn trùng blob Git `89d2f6a`; 0 file cấm (dữ liệu, credential, `__pycache__`) | |
| Gói cũ | `BBD73386…09C3` (`d05ff97`, chưa từng deploy) được giữ, đổi tên `DemandForecast-1.2.6-superseded-20261018-160552-win64-portable.zip`; kế hoạch dọn artifact chỉ dry run, không xóa gì | |

## E. Diễn tập (môi trường cách ly `scratchpad\s`)

**Môi trường:**
- bản sao DB production lấy bằng SQLite backup API, nguồn mở `mode=ro`;
- gói 1.2.5 chính thức cài vào `LOCALAPPDATA` cách ly, cổng 8879;
- proxy cục bộ 8878, chạy đúng file proxy của production; không có tunnel.

**Task Windows thật** chạy chính script deploy với `-Target iso`. Ba lần chạy:

| Lần | Kết quả | Ghi chú |
|---|---|---|
| 1 (16:23) | deploy exit 0 (457,7 s), rồi **BLOCKED** | lỗi script: trình đo gián đoạn `url_poll.ps1` không nằm cạnh script nên CSV không có. Đã sửa: chép file; thiếu file phụ trợ thì BLOCKED ngay từ đầu; phép đo thiếu không làm hỏng quy trình |
| 2 (16:40) | deploy exit 0 (466 s), hậu kiểm đạt, **hai lịch bật và được xác nhận**, rồi **BLOCKED** | lỗi script: `$r` ghi đè `$R` (PowerShell không phân biệt hoa thường), nên `result.json` bị ghi đè. Đã đổi tên mọi biến trùng, kiểm tự động không còn cặp nào |
| 3 (17:01) | **DEPLOYED_AND_VERIFIED, exit 0** | đủ các bước, ghi báo cáo đúng. Script này (SHA `350F754B…B70E`, sửa lần cuối 16:59:10) là đúng bản task production sẽ chạy |

Cả hai lỗi đều dừng an toàn: không bật lịch nào ngoài kế hoạch và không rollback mù. Sau mỗi lần, môi trường được rollback bằng **`restore.ps1` của 1.2.5**: 47,8 s / 48,8 s / 158,6 s, đều về schema 4 và **mọi bảng giống hệt baseline trước nâng cấp**.

**Lần 3 chi tiết:**

| Bước | Kết quả |
|---|---|
| D-0 16:00 (thay cho 18:00 trên bản sao) | `JOB-20261018090011-BF0E57` SUCCEEDED |
| Gate | đạt: 1.2.5, SHA, script deploy trùng gói, 0 job, lịch cũ đúng, proxy 200/403/405, data-check WARN (có sẵn) + integrity OK, đĩa đủ |
| Backup mới (`backup.ps1` của 1.2.5) | `backup-20261018-170417-cli.zip`, CRC đạt, integrity ok, schema 4 |
| `-CheckOnly`, rồi deploy | exit 0 / exit 0, 1063 s; app không phản hồi **464 s** (máy đang tải nặng; lần đầu chiều nay chỉ 116 s) |
| Hậu kiểm | 1.2.6, schema 6, BIGQUERY, forecast `FCR-…798B4D` không đổi, `storage.json` không đổi |
| Hậu kiểm: dữ liệu | 20/23 bảng cũ giống hệt; chỉ đổi `schema_migrations` (+5, +6), `audit_log` (+1 `BACKUP_CREATED`), `sync_state` (heartbeat, `flows_first_seen`); 5 bảng mới rỗng; model giống hệt; thiết lập không có khóa cuối ngày |
| Hậu kiểm: lịch, proxy, log, rollback | lịch cũ nguyên; eod/close TẮT trước khi bật; proxy: ghi 405, `PUT /api/schedules/eod` 405, admin 403; log 0 lỗi; `rollback-version -CheckOnly` exit 3 (đúng: cần restore) |
| Bật hai lịch | eod: ON, registered, REGISTERED, lần tới 23:55; close: ON, registered, lần tới 23:59; sau một tick vẫn ON/REGISTERED, 0 job cuối ngày, lịch cũ nguyên |

**Sau task (`post126s.ps1`): 20/21 PASS.**
- **Đạt:**
  - app tiếp tục chạy sau khi task kết thúc;
  - restart thì hai lịch vẫn ON và REGISTERED;
  - đổi giờ 23:50 → lần chạy tới đổi theo;
  - trùng phút, timezone UTC, giờ trước 20:00 đều bị từ chối (422), không đổi gì;
  - tắt riêng `eod` → NOT_REGISTERED, `close` vẫn ON; bật lại cả hai được xác nhận;
  - không job cuối ngày nào được tạo;
  - proxy: bật/chạy 405, chạy thử và admin 403;
  - rollback với `restore.ps1` 1.2.5: bảng giống baseline; file `pre-restore` schema 6 đọc được;
  - production không bị chạm; hash gói không đổi.
- **1 FAIL do lỗi đo:** lệnh đếm bảng trong script diễn tập bị hỏng vì lỗi escape (trả rỗng). Hai lệnh chạy thử vẫn trả 200, `written=false`. Đã thay bằng **bằng chứng trên bản sao DB**: lấy file `pre-restore` (schema 6, hai lịch ON, dữ liệu production hôm nay), gọi chạy thử cả hai lịch bằng code của gói → **0/28 bảng thay đổi**. Chạy thử cho kết quả: snapshot COMPLETE 119.889 dòng từ `FCR-…798B4D`; chốt `CLOSED_UNVERIFIED` từ D0, 1.848 dòng, tổng 27.541.
- **Cơ sở thời gian:** app diễn tập có scheduler đã dừng lúc 17:44, trước mốc D-0 18:00, nên không gọi BigQuery.

## F. Cơ chế chờ bền vững (Windows Task Scheduler)

**Task và lịch kích hoạt:**

| Mục | Giá trị |
|---|---|
| Task | `\DemandForecast-Deploy-1.2.6`: **duy nhất một task**; ba task diễn tập đã gỡ sau khi ghi kết quả (30, 30, 0) |
| Kích hoạt | một lần, **18/10/2026 19:05** (giờ máy = SE Asia Standard Time = giờ Việt Nam) |
| Tài khoản | `LOG-PC\Giau Vo`, Interactive (cần đang đăng nhập: app, credential và link thuộc phiên này), quyền thường |

**Thiết lập Task Scheduler:**
- giới hạn 4 giờ;
- `IgnoreNew` (không chạy chồng);
- `StartWhenAvailable` (lỡ giờ thì chạy khi có thể, script tự báo `MISSED_WINDOW`);
- không đánh thức máy;
- không dừng khi chuyển sang pin.

**Lệnh:**

`powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p6\deploytask126.ps1" -Target prod -Sha 0464EEDA…6171 -StateDir "…\scratchpad\p6\prod_state" -Day 2026-10-18 -WindowStart 19:00 -WindowEnd 22:00 -DeployDeadline 21:30 -D0Slot 18:00 -ReportFile "D:\Buymed\Lightgbm AI\reports\demandforecast_v126_final_release_and_deploy.md"`

**Chống chạy hai lần:**
- file khóa `task.lock` mở độc quyền;
- file `done.json` cho mọi kết cục: có file này thì không chạy lại.

**Khung giờ:**
- khác ngày 18/10, hoặc đã quá 21:30 / 22:00 → `MISSED_WINDOW`, không deploy;
- chờ `D0_SYNC:2026-10-18T18:00` **SUCCEEDED**: FAILED / SKIPPED, hoặc chưa xong lúc 21:30 → `BLOCKED`.

**Gate chạy lại ngay trước deploy:**
- production 1.2.5 (`current.txt`, health, `data_dir`, cổng 8765);
- SHA gói; script deploy trùng bản trong gói; có `-ConfirmToken` (không có thì `NEEDS_MANUAL_CONFIRMATION`);
- 0 job và 0 tiến trình deploy / cài / restore khác;
- lịch D-1 03:00 / 05:00, D-0 08–18, huấn luyện 09:00 SKIP;
- proxy và link: 200 / 403 / 405; PID proxy và cloudflared;
- `storage.json` `8D79DBDD…`;
- data-check không FAIL và integrity OK;
- đĩa đủ; trạng thái DB v4 và forecast.

**Thứ tự sau gate:**
1. Baseline: bản sao DB + fingerprint.
2. Backup mới bằng `backup.ps1` của 1.2.5, kiểm CRC, integrity và schema 4.
3. `deploy-upgrade -CheckOnly`, rồi `deploy-upgrade -ConfirmToken UPGRADE-1.2.6` (phương thức chính thức, không hỏi tương tác).
4. Hậu kiểm như ở mục E, thêm link công khai và việc PID proxy / cloudflared không đổi.
5. Bật hai lịch.

**Khi lỗi (không bao giờ):**
- không tự rollback;
- không chạy retention / D-0 / D-1 / huấn luyện / forecast;
- không đổi D-1 / D-0 / huấn luyện;
- không động proxy / tunnel;
- không xóa gì.

Lỗi deploy → `DEPLOY_FAILED`, giữ bằng chứng. Hậu kiểm không đạt → `POST_DEPLOY_BLOCKED`, hai lịch giữ TẮT. Một lịch không xác minh được → tắt lại lịch đó, `DEPLOYED_WITH_ISSUES`.

**Kết quả và bằng chứng:**
- `…\scratchpad\p6\prod_state\` gồm `task.log`, `result.json`, `done.json`, `deploy_run.txt`, các CSV đo gián đoạn, bản sao DB trước / sau;
- mục K tự ghi vào báo cáo này;
- mã thoát: 0 / 60 / 50 / 40 / 35 / 30 / 20 / 10.

## G. Gate trước khi đăng ký (17:47 VN, chỉ đọc), task sẽ chạy lại lúc deploy

| Gate | Kết quả |
|---|---|
| Production | 1.2.5, `current.txt` 1.2.5, pid app 22024, proxy 26416, cloudflared 31076, `data_dir` `D:\Buymed\Lightgbm AI\data\runtime`, DB 560.132.096 byte, `storage.json` `8D79DBDD…E047` |
| Job | 0 job đang chạy; D-0 16:00 SUCCEEDED; D-0 18:00 sắp tới (task sẽ chờ nó) |
| Lịch | D-1 BẬT 03:00 / 05:00; D-0 BẬT 08–18 mỗi 2 giờ; huấn luyện BẬT 09:00 SKIP; chưa có eod / close (1.2.5) |
| Forecast | BIGQUERY, `FCR-20261018043737-798B4D` PUBLISHED, db_version 4 |
| Proxy / link | proxy và `https://volumes-jean-angels-configurations.trycloudflare.com`: health 200; admin 403; ghi (POST / PUT / DELETE) 405 |
| DB | data-check WARN (`forecast_series_meta` 1, có sẵn), `sqlite_integrity` OK, `foreign_keys` OK |
| Đĩa | D 76,8 GB trống; C ~29 GB |
| Gói / QA / B1 / F1 / rollback | PASS (mục D, E; B1 và F1 không đổi so với lượt 15:20) |

## H. Rủi ro, giới hạn, việc chưa làm

1. **Deploy chưa chạy.** Mọi kết quả production sau 19:05 nằm ở mục K (task tự ghi) và `prod_state\result.json`. Máy tắt, ngủ hoặc người dùng đăng xuất lúc 19:05 thì task không chạy đúng giờ. Khi chạy muộn, task tự báo `MISSED_WINDOW` và không deploy.
2. **Thời gian gián đoạn** khi diễn tập dao động 116–466 s, tùy tải máy; deploy mất 386–1063 s. Trong lúc nâng cấp, link trả 502.
3. **Rollback** (chỉ làm tay, theo quyết định riêng):
   - `…\1.2.6\scripts\stop.ps1`;
   - `…\1.2.5\scripts\restore.ps1 -File "<backup-…-manual.zip của deploy>"`;
   - `…\1.2.6\scripts\rollback-version.ps1 -To 1.2.5 -ConfirmToken ROLLBACK-1.2.5`.

   Rollback làm mất mọi thứ ghi sau backup trên DB đang chạy: snapshot D-0, job, snapshot cuối ngày 23:55 và bản chốt 23:59 nếu đã chạy. Tất cả vẫn nằm trong file `pre-restore` tự tạo.
4. Task chạy từ thư mục scratchpad của phiên Claude (`%TEMP%`). Nếu thư mục bị dọn trước 19:05 thì task không chạy được và không có gì xảy ra.
5. Chạy thử và các nút ghi bị proxy chặn, nên không dùng được qua link từ xa (chủ đích).
6. Message commit `89d2f6a` lẫn ký tự CR do file message ghi CRLF. Không amend (theo quy định).
7. Chưa làm: deploy, bật hai lịch trên production, push Git, retention `-Apply`. Ngoài lần đọc bản sao (backup API, `mode=ro`), không có thao tác ghi nào lên production.

## I. Git

- Branch `main`, HEAD `bd52203`, working tree sạch.
  - `89d2f6a`: code + test + tài liệu của lượt này. **Gói được build từ commit này.**
  - `bd52203`: chỉ `docs/CHECKPOINT.md`, ghi release / diễn tập / task. Nằm sau gói, không có trong gói.
- Đi trước `origin/main` 24 commit. **Không push.** Không amend, reset hay rebase.
- `reports/`, `dist/`, `checkpoints/` nằm ngoài Git.

## J. Việc tiếp theo

- **Không cần thao tác** nếu chủ sở hữu giữ nguyên kế hoạch: để máy bật và đang đăng nhập lúc 19:00–22:00; task tự chạy.
- **Sau 19:30:** xem mục K. Nếu là `DEPLOYED_AND_VERIFIED`, hai lịch đã BẬT. Snapshot đầu tiên chạy 23:55 và bản chốt đầu tiên 23:59 hôm nay.
- **Muốn hủy trước 19:05:** `Unregister-ScheduledTask -TaskName "DemandForecast-Deploy-1.2.6"` (hoặc Disable trong Task Scheduler).

## K. Deploy task result (prod) - written automatically by the scheduled task

| Item | Value |
|---|---|
| Status | **DEPLOYED_AND_VERIFIED** (exit 0) |
| Reason | upgraded to 1.2.6, post-checks PASS, eod and close ON and registered by the running scheduler |
| Task started / finished (VN) | 2026-10-18 19:05:01 / 2026-10-18 19:20:27 |
| D-0 slot job | D0_SYNC:2026-10-18T18:00 JOB-20261018110020-382382 SUCCEEDED, finished 2026-10-18T11:00:22+00:00 UTC, checked 2026-10-18 19:05:01 |
| Gate target | current=1.2.5 running=1.2.5 data=D:\Buymed\Lightgbm AI\data\runtime port=8765 app_pid=22024 |
| Gate package | sha=0464EEDA8B767909000974A30718663F6558872F8372604235F72E2BB36C6171 expected=0464EEDA8B767909000974A30718663F6558872F8372604235F72E2BB36C6171 deploy_script_identical=True |
| Gate jobs | active_jobs=0 other_deploy_processes=0 |
| Gate schedules | {"d1":"True 03:00 05:00 30","d0":"True 08:00,10:00,12:00,14:00,16:00,18:00 LATEST_ONCE","train":"True 09:00 SKIP"} day_end_flows_present=False |
| Gate proxy | health=200 via_proxy=1.2.5 admin=403 write=405 |
| Gate link | version=1.2.5 |
| Gate processes | proxy=26416 cloudflared=31076 |
| Gate storage_json | 8D79DBDDC960B10964F3B137F352D9AD54D39F08C52EF841418781ED00FDE047 |
| Gate data_check | status=WARN sqlite_integrity=OK |
| Gate disk | D=76.8 GB C=24.5 GB |
| Gate status | active_source=BIGQUERY forecast=FCR-20261018043737-798B4D db_version=4 |
| Gate failures | none |
| Baseline copy | schema 4, integrity ok, 560365568 bytes, 23 tables, 8 model files |
| New backup (backup.ps1 of 1.2.5) | D:\Buymed\Lightgbm AI\backups\backup-20261018-190701-cli.zip - SHA-256 C8F38FD34E2679256694A13DB1C8E29E3CA24FE8F0EF58A0A308E1D9DBE5E38D, CRC True, integrity ok, schema 4 |
| deploy-upgrade -CheckOnly | exit 0 |
| deploy-upgrade -ConfirmToken UPGRADE-1.2.6 | exit 0, 2026-10-18 19:09:01 -> 2026-10-18 19:16:33 VN (451.3 s) |
| Availability poll_link | 196.7 s without 200 (19:12:35.148 -> 19:15:51.810); versions 1.2.5=188 1.2.6=48; last 19:16:48.130 200 1.2.6 |
| Availability poll_app | 195.7 s without 200 (19:12:34.758 -> 19:15:50.476); versions 1.2.5=208 1.2.6=52; last 19:16:47.713 200 1.2.6 |
| New backups in the backups folder | backup-20261018-190932-manual.zip 76269536; backup-20261018-191235-pre-migration-v4.zip 76269611; backup-20261018-191344-cli.zip 76274150 |
| Post-check app | health=1.2.6 db_version=6 source=BIGQUERY forecast=FCR-20261018043737-798B4D current_txt=1.2.6 |
| Post-check storage_json_unchanged | True |
| Post-check data_check | status=WARN integrity=OK not_ok=forecast_series_meta=WARN |
| Post-check day_end | eod=False/OFF/23:55/Asia/Ho_Chi_Minh close=False/OFF/23:59/Asia/Ho_Chi_Minh scheduler_running=True |
| Post-check proxy | health=200 via_proxy=1.2.6 admin=403 write=405 put_eod=405 run_close=405 schedules=200 |
| Post-check link | version=1.2.6 |
| Post-check processes | proxy=26416 cloudflared=31076 |
| Post-check server_logs | files=server.err.log,server.out.log error_lines=0 |
| Post-check rollback_check_only | exit=3 (3 = refused: schema 6 needs the restore of the pre-upgrade backup with 1.2.5's restore.ps1) |
| Post-check D-1 / D-0 / training | True 03:00 05:00 30 / True 08:00,10:00,12:00,14:00,16:00,18:00 LATEST_ONCE / True 09:00 SKIP |
| Post-check data | ok=True; 20 existing tables identical; changed: ['audit_log', 'schema_migrations', 'sync_state']; problems: none |
| Pre-upgrade backup (deploy-upgrade) | D:\Buymed\Lightgbm AI\backups\backup-20261018-190932-manual.zip - SHA-256 52788C13D5431C1F835C9F8C78A65426C26C29BB07EEFAFB0D16780810B2A091, integrity ok, schema 4 |
| Post-check failures | none |
| Schedule eod | verified=True http=200 enabled=True state=ON registered=True runtime=REGISTERED next=2026-10-18T23:55:00+07:00 enabled_at=2026-10-18T19:19:00+07:00 |
| Schedule close | verified=True http=200 enabled=True state=ON registered=True runtime=REGISTERED next=2026-10-18T23:59:00+07:00 enabled_at=2026-10-18T19:19:00+07:00 |
| After one scheduler tick | tick 2026-10-18T12:18:53+00:00 -> 2026-10-18T12:19:23+00:00; eod ON/REGISTERED; close ON/REGISTERED; day-end jobs created: 0; D-1 / D-0 / training True 03:00 05:00 30 / True 08:00,10:00,12:00,14:00,16:00,18:00 LATEST_ONCE / True 09:00 SKIP |
| Issues | none |
| Evidence | `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p6\prod_state\result.json`, `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p6\prod_state\task.log`, deploy log `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p6\prod_state\deploy_run.txt` |


## K.1 Kiểm chứng độc lập sau deploy (19/10/2026 03:40–03:47 VN, chỉ đọc)

Mục K ở trên do task tự ghi lúc 19:20 ngày 18/10 và được giữ nguyên. Kiểm tra live sau đó xác nhận trạng thái **DEPLOYED_AND_VERIFIED**:

- production 1.2.6 trên cổng nội bộ, proxy và link (DB schema 6, `storage.json` không đổi);
- proxy trả 405 cho ghi và 403 cho trang quản trị;
- lịch D-1, D-0 và huấn luyện không đổi;
- hai backup trước deploy đọc lại được;
- `EOD_FORECAST_SNAPSHOT:2026-10-18` (23:55) và `ACTUAL_CLOSE:2026-10-18` (23:59) đều `SUCCEEDED`.

Chi tiết, phần chưa xác minh và đề xuất nằm trong `reports\demandforecast_v126_deployment_state_recovery.md`.
