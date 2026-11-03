# Release 1.2.13, Customer ID, demand và forecast (22/10/2026)

## Lỗi bật Customer ID: `-Headers` nhận nhầm kết quả health (23/10 00:13; sửa và kiểm thử 00:20–01:00)

**Kết luận:**
- Lần chạy `OWNER_RELEASE` lúc 00:04 đã xong bước 1 (deploy 1.2.13, "DEPLOYED AND VERIFIED") và bước 2.
- Ở bước 3, `CUSTOMER-ON` được gõ đúng, nhưng `OWNER_CUSTOMER_ID` dừng (exit 1) **trước khi gửi yêu cầu ghi nào**: lỗi xảy ra ngay lúc PowerShell gán tham số cho `Invoke-RestMethod`.
- Release dừng fail-fast; bước 4 không chạy.
- **Customer ID đang OFF.** Không có job hay reload nào bắt đầu (kiểm tra chỉ đọc lúc 00:20 và 00:39).
- Đã sửa lỗi, thêm kiểm tra fail-fast và cho phép chạy lại an toàn.
  - Test giả lập: 27/27 test owner và 15/15 test `deploy-upgrade` đạt.
  - Với bản trước khi sửa: 12/14 FAIL, đúng lỗi của production.
- Chưa chạy lại bước Customer ID.

### File và dòng gây lỗi (bản 22/10 23:47)

| Vị trí | Nội dung |
|---|---|
| `OWNER_CUSTOMER_ID_1.2.13.ps1:33` | `$H = @{ "X-DF-Client" = "web" }`. App bắt buộc header này cho mọi POST/PUT (`backend/app/security.py:36-39`); thiếu thì trả 403 `CSRF_BLOCKED` |
| `:62` | `$h = Invoke-RestMethod "$BaseUrl/api/health"`. **Tên biến PowerShell không phân biệt hoa thường**, nên dòng này ghi đè `$H` bằng kết quả health `{ok, version, time}`, một `PSCustomObject` |
| `:52` (hàm `Send`, gọi từ `:76`) | `Invoke-RestMethod … -Headers $H` báo "Cannot bind parameter 'Headers'. Cannot convert the "@{ok=True; version=1.2.13; time=2026-10-22T17:13:43+00:00}" value of type PSCustomObject to type IDictionary". Đây đúng là đối tượng trong log `logs\runtime\owner-customer-id-1.2.13-20261023-001342.log` |
| `OWNER_RELEASE_1.2.13.ps1:32, 75, 93` | Cùng một cặp: `$H` (header của yêu cầu `TRAIN`, dòng 93) và `$h` (health ở bước 2, dòng 75). Bước 4 `TRAIN` cũng sẽ lỗi y hệt |

- **Nguồn gốc:** hai cặp biến này có từ bản script owner của master batch (chiều 22/10); bản sửa lúc 23:47 vẫn giữ nguyên.
- **Vì sao trước đây không bắt được:**
  - Diễn tập phase B gửi request bằng hàm riêng, với header viết thẳng (`evidence\iso1213r.ps1:45`).
  - Test owner của lượt trước luôn trả lời Enter ở `CUSTOMER-ON`, nên các bước ghi 3–7 chưa từng chạy.
- **Các `-Headers` khác** trong repo và thư mục release đều dùng bảng hash viết thẳng: `deploy-upgrade.ps1:114`, `stop.ps1:10`, `remote\remote-access.ps1:60/184` (`evidence\headers_scan_20261023.txt`).
- **Script diễn tập `evidence\iso1213r.ps1`:** bản quét thấy thêm 2 cặp biến chỉ khác hoa thường (`$tc/$tC`, `$tr/$tR`).
  - Biến nào cũng được dùng xong trước khi bị ghi đè, nên không ảnh hưởng kết quả diễn tập.
  - Không sửa, vì đó là bằng chứng của một lần chạy đã xong.

### Bản sửa

| File | Thay đổi |
|---|---|
| `OWNER_CUSTOMER_ID_1.2.13.ps1` | Đổi tên bảng header thành `$WebHeaders` (dòng 42; dùng ở dòng 62); kết quả health là `$health` (dòng 109). Thêm kiểm tra fail-fast và chạy lại an toàn (bên dưới). Lỗi HTTP in kèm câu trả lời của app, ví dụ `POST /api/bigquery/activate answered HTTP 409: {"code": "SOURCE_NOT_READY", …}` |
| `OWNER_RELEASE_1.2.13.ps1` | `$H` thành `$WebHeaders` (dòng 36, dùng ở dòng 97 cho `TRAIN`); không đổi gì khác |
| `backend/tests/test_v1213_deploy_preflight.py` | App giả từ chối POST/PUT thiếu `X-DF-Client` như app thật, ghi lại header của mỗi request. `/api/health` giả trả `{ok, version, time}` như app thật |
| `tests/test_owner_scripts.py` | +14 test (xem mục Test) |
| `CHANGELOG.md`, `docs/CHECKPOINT.md`, `RESUME_CHECKPOINT.md`, báo cáo này | Cập nhật |

**Kiểm tra fail-fast trong `OWNER_CUSTOMER_ID`:**
1. **Bước 1** (chỉ đọc, trước câu hỏi): kiểm tra version và không có job đang chạy.
   - Đọc trạng thái Customer ID từ `/api/settings`, `/api/features/registry` và `/api/bigquery/status`, rồi in ra: cột mapping, production mode, validation của mapping hiện tại, model setting, đã dùng cho training hay chưa.
   - Thiếu trường nào thì dừng: không hỏi, không ghi.
2. **Bước 3:** sau khi lưu mapping thì đọc lại. Phải có `customer_id_column` = `customer_id` **và** `field_mapping`/`reference_mapping` giống hệt trước khi lưu; nếu không thì dừng trước validation.
3. **Bước 5 và 6:** đọc lại production mode và `feature_customer` sau khi ghi.
4. **Bước 7** (ngay trước reload): kiểm tra lại không có job đang chạy và cả 3 điều kiện (cột, production mode, model setting).
   - Nếu app trả `already_active` (đã có D-1 đang chạy) thì dừng, không chạy D-1 thứ hai.

**Chạy lại an toàn (idempotency):**
- **Bước đã làm thì bỏ qua:**
  - Mapping đã là `customer_id`: **không gửi lại**, vì mỗi lần lưu mapping app lại tắt production mode (`ops_routes.py:460`).
  - Validation đã đạt cho mapping hiện tại: bỏ qua.
  - Production mode hoặc `feature_customer` đã ON: bỏ qua.
  - Đã ON đầy đủ: in "CUSTOMER ID ALREADY ON", exit 0, không hỏi, không ghi.
- **Mapping gửi đi:** đúng `field_mapping`/`reference_mapping` vừa đọc, chỉ thêm `customer_id_column`, rồi đọc lại để so sánh.
- **Dữ liệu** (test backend có sẵn, chạy mã app thật với DB tạm và BigQuery giả):
  - `test_v117.py:127`: D-1 chạy lại không tạo dòng trùng (`series_days_new == 0`, số dòng và tổng không đổi).
  - `test_v1213_six_key_reverify.py:165`: full reload sau khi map `customer_id` vẫn giữ quy tắc sáu khóa.
  - `test_v111.py:95`: gửi lại yêu cầu chạy job thì nhận lại đúng job đang chạy, không tạo job thứ hai.

### Test

| Bộ test | Loại | Trước khi sửa | Sau khi sửa |
|---|---|---|---|
| `tests/test_owner_scripts.py` (27; 14 test liên quan được chạy với bản 23:47) | integration: 3 script owner + `deploy-upgrade.ps1` thật, **app giả (mock)**, bản cài và gói giả 9.8.7, cách ly | 14 test chọn: **12 FAIL** / 2 đạt. Test bật Customer ID FAIL với đúng lỗi production "Cannot bind parameter 'Headers' … PSCustomObject …" | **27 passed** |
| Quét tĩnh `-Headers` (nằm trong bộ trên) | đọc cú pháp, không chạy script | 2 phát hiện ở mỗi script owner | không còn |
| `backend/tests/test_v1213_deploy_preflight.py` (15) | integration: `deploy-upgrade.ps1` thật, app giả | – | **15 passed** |
| `scripts\run-tests.ps1` (00:42, log `logs\development\tests_20261023_004229.log`) | unit + integration, DB tạm | – | backend **796 passed / 19 skipped / 1 failed**; vitest 159 passed; typecheck OK; build OK; lint chưa cấu hình |

Các ca test owner mới:
- bật Customer ID đủ 5 bước: mọi POST/PUT có header, đúng thứ tự, mỗi bước một lần, mapping gửi lại không đổi;
- chạy lại sau khi dừng ở 3 trạng thái: mapping đã lưu, đã validate, chỉ còn reload;
- đã ON đầy đủ: không làm gì;
- có job bắt đầu ngay trước reload: dừng, không reload;
- mapping không được lưu hoặc bị đổi: dừng trước validation;
- câu trả lời của app thiếu trường: dừng trước câu hỏi;
- app từ chối activate: in câu trả lời, không reload;
- chuỗi release đủ 4 bước kể cả `TRAIN`: yêu cầu training có header, không promote.

**1 test backend FAIL, không do lượt này:** `test_v128_fixes.py::test_training_and_forecast_with_weekday_off_share_one_feature_list` ("the demo run has LightGBM series").
- Test đạt ở lần chạy 22/10 23:52 và bắt đầu FAIL khi ngày đổi sang 23/10.
- Chẩn đoán bằng một plugin pytest ghim `today_vn` (không sửa repo): ghim 21/10, 22/10 hoặc 24/10 thì đạt; ghim 23/10 thì FAIL.
- Lý do: dữ liệu demo được sinh tới ngày hôm qua (`app/data/demo.py:84`). Riêng với cửa sổ kết thúc 22/10, cấu hình tắt thứ trong tuần không có chuỗi LightGBM nào.
- Test này không dùng file nào bị sửa; không có file nào trong `backend/app` thay đổi.
- Không sửa và không nới test; cần xử lý riêng. Bằng chứng: `evidence\full_suite_20261023.txt`.

**Test nào chạy trên ứng dụng thật:**
- **Không có** test nào trong lượt này chạy script trên một bản cài thật.
- Tên các trường mà script dựa vào đã được đối chiếu trên **production thật** bằng GET chỉ đọc (`evidence\prod_customer_id_state_20261023.json`).
- Các yêu cầu ghi của bước 3–7, với cùng cách dựng payload, đã chạy và đạt trên **bản cài 1.2.13 thật của một bản sao production** trong diễn tập phase B ngày 22/10. Theo `evidence\iso1213r_result_r14.json`: mapping, validation, activation, `feature_customer` và D-1 full reload đều đạt. Diễn tập dùng hàm gửi riêng nên không gặp lỗi tên biến.
- Idempotency ở mức dữ liệu do các test backend có sẵn kiểm tra (mã app thật, DB tạm, BigQuery giả).

### Trạng thái production (chỉ đọc, 00:20–00:45)

- **Hệ thống:** 1.2.13, PID 22004 (khởi động 00:12:23), schema 10, nguồn BIGQUERY. `storage.json` `8D79DBDD…E047` không đổi.
- **Customer ID: OFF.**
  - `customer_id_column` rỗng.
  - `feature_customer` False.
  - Registry `customer.used` False (`TOGGLE_OFF`, coverage 0).
- **BigQuery:**
  - Production mode ON.
  - Validation đạt và đúng mapping hiện tại (`bc5fcb06…`); activation ready.
  - Lịch sử cài đặt `bigquery` và `model`: lần sửa mới nhất là 17/10, tức không có lần lưu nào sau lỗi.
- **Job / reload: chưa có.**
  - Job mới nhất là `ACTUAL_CLOSE` lúc 23:59, trước deploy.
  - Không có job nào sau khi nâng cấp, không có job đang chạy.
  - `app.log` sau nâng cấp chỉ có dòng backup và "app starting".
- **Kiểm tra sau deploy của script (bước 5):** data-check WARN 2 mục, không liên quan Customer ID, chưa điều tra thêm.
  - `forecast_series_meta`: đã có từ 1.2.11.
  - `finalized_days_changed`: kiểm tra mới của 1.2.13. Ngày đã chốt có tổng demand khác số thực tế đã đóng băng; chỉ mang tính thông tin.
- **Chưa chạy:** kiểm tra chỉ đọc đầy đủ sau deploy `post_verify.py A`.

### Lệnh tiếp theo (chỉ khi anh/chị quyết định)

Chạy riêng bước Customer ID. **Không** chạy lại `OWNER_RELEASE`: bước 1 của nó sẽ hỏi `UPGRADE-1.2.13` và cài lại 1.2.13.

Điều kiện: tài khoản `Giau Vo`, khung 00:05–05:00 (trước D-1 06:00) hoặc 18:30–21:45, khi không có job. Mất khoảng 15–20 phút.

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\reports\release-1.2.13-20261022\OWNER_CUSTOMER_ID_1.2.13.ps1"
```

- Bước 1 in trạng thái hiện tại; bước nào đã làm thì bỏ qua. Chỉ gõ `CUSTOMER-ON` khi câu hỏi đã hiện.
- Exit code:
  - 0: Customer ID ON và đã kiểm tra;
  - 1: dừng trước hoặc giữa các bước, in rõ bước và câu trả lời của app; chạy lại được;
  - 4: không xác nhận;
  - 5: reload đã chạy nhưng kiểm tra cuối không đạt.
- Sau đó việc huấn luyện chạy theo lịch 07:00 (hoặc bấm "Chạy ngay" trên trang Hiệu năng model) và không tự promote. Báo Claude để chạy kiểm tra chỉ đọc `post_verify.py` A/B/C và đánh giá.

## Lỗi xác nhận và luồng điều khiển của script owner (lần chạy 22/10 23:10; sửa và kiểm thử 23:15–00:15)

**Kết luận:**
- Lần chạy `OWNER_RELEASE_1.2.13.ps1` lúc 23:10 dùng đúng tài khoản `Giau Vo`. Nó qua CheckOnly và backup, rồi dừng ở câu hỏi xác nhận của `deploy-upgrade`: câu trả lời `Read-Host` nhận được **không phải** `UPGRADE-1.2.13`.
  - Không có gì bị dừng hay cài.
  - Chỉ có thêm backup `backups\backup-20261022-231056-manual.zip`: giữ nguyên, SHA-256 `105BEA65…E8E1` khớp, có `db/app.db`.
- `OWNER_DEPLOY` **không kiểm tra exit code** của lần deploy, nên chạy tiếp phần kiểm tra 1.2.13 và lỗi ở `Push-Location`.
  - Lỗi này làm cả `OWNER_RELEASE` dừng, nên Customer ID và training không chạy.
  - Tức là script dừng vì gặp lỗi, không phải vì đã kiểm tra.
- Đã sửa 3 script owner và nhánh hỏi xác nhận của `deploy-upgrade.ps1`.
  - 30 test chạy trên bản cài, gói và app giả lập cách ly: **30/30 đạt**.
  - Với bản trước khi sửa: 5/15 và 15/15 FAIL.
- **Production không bị thay đổi.**

### Nguyên nhân "not confirmed"

| Bằng chứng | Nội dung |
|---|---|
| Đường đi của từ xác nhận (bản cũ) | `OWNER_RELEASE` dòng 26 gọi `OWNER_DEPLOY` trong cùng tiến trình (`&`). `OWNER_DEPLOY` dòng 39 gọi `deploy-upgrade.ps1` **không có `-ConfirmToken`**. `deploy-upgrade` dòng 122 hỏi bằng `Read-Host`, **sau** prechecks và backup trực tuyến (khoảng 1,5–2 phút). Dòng 123 so sánh `-ne "UPGRADE-$newVersion"`: không phân biệt hoa thường, **không bỏ khoảng trắng**. `$newVersion` = `1.2.13`, đọc từ `VERSION` trong gói |
| `logs\runtime\deploy-20261022-231056.log` (bản sao: `evidence\`) | Host Application = `powershell.exe -ExecutionPolicy Bypass -File …OWNER_RELEASE_1.2.13.ps1`, PID 37244, `LOG-PC\Giau Vo`. Ngay sau `== confirmation ==` là `UPGRADE STOPPED: not confirmed`. Không có dòng câu hỏi, không có câu trả lời |
| Lần đầu xác nhận bằng cách gõ | Trong 18 log `deploy-*.log` từ 15/10, mọi lần deploy thành công đều truyền `-ConfirmToken UPGRADE-<v>` trên dòng lệnh. 4 lần "not confirmed" khác là các lần chủ ý chỉ lấy backup (`-ConfirmToken NOT-CONFIRMED-BACKUP-CHECK`). Lần 23:10 là lần **duy nhất** đi nhánh `Read-Host`: nhánh này chưa từng chạy thật trên máy này |
| Transcript không ghi `Read-Host` | Thử nghiệm cách ly (`evidence\probe_readhost_transcript_stderr.txt`): transcript của PowerShell 5.1 không ghi câu hỏi lẫn câu trả lời của `Read-Host`, khớp với log trên. `Read-Host` không bỏ khoảng trắng: `"  ABC-1.2.3 "` trả về 12 ký tự. Vì vậy **không có log nào ghi lại câu trả lời đã nhận** |
| Thời điểm | `app.log`: "backup created" 16:12:20 UTC (23:12:20). Đo lại các bước còn lại trước câu hỏi: kiểm tra zip 0,02 s, hash 0,19 s, `GET /api/system/status` 8,7 s. Vậy câu hỏi hiện khoảng 23:12:29 và transcript kết thúc 23:12:32: `Read-Host` trả về **trong khoảng 3 giây** |
| Không có gì can thiệp `Read-Host` | Lệnh của chủ hệ thống không có `-NoProfile`, nhưng không có PowerShell profile nào ở cả 4 vị trí |

**Kết luận về nguyên nhân:** câu trả lời nhận được khác `UPGRADE-1.2.13`. Vì không log nào ghi lại, **không xác định được chính xác đó là gì**.
- **Khả năng phù hợp nhất với mốc 3 giây:** phím đã nằm sẵn trong bộ đệm bàn phím trước khi câu hỏi hiện.
  - `OWNER_DEPLOY` in "type UPGRADE-1.2.13 when asked" khoảng 1,5–2 phút trước câu hỏi, trong lúc màn hình đứng yên chờ prechecks và backup.
  - Một phím Enter, hoặc chữ gõ sớm chưa kèm Enter rồi gõ lại, sẽ bị đọc ngay khi câu hỏi hiện.
- **Khả năng khác:** gõ sai, hoặc dán kèm khoảng trắng hay dấu `` ` ``.
- **Cách đối chiếu:** nếu cửa sổ PowerShell của lần chạy còn mở, dòng câu hỏi trong đó có kèm đúng câu trả lời đã nhận.

### Lỗi luồng điều khiển (cùng loại, tìm thấy khi viết test)

| # | Lỗi (bản cũ) | Bằng chứng |
|---|---|---|
| 1 | `OWNER_DEPLOY` chạy tiếp sau khi `deploy-upgrade` thất bại | Dòng 39–48 cũ: in exit code rồi `Push-Location …\1.2.13\backend`. Test với bản cũ: `PathNotFound`, giống hệt lần 23:10. Khi bản mới đã cài nhưng post-check FAIL, nó còn chạy `data-check` của bản mới |
| 2 | Lỗi bị biến thành PASS | `OWNER_DEPLOY` bước 4 không đạt: chỉ in vàng "CHECK THE RESULT ABOVE", exit 0. `OWNER_CUSTOMER_ID` cũng vậy |
| 3 | Exit code không được giữ | CheckOnly exit 3 thành exit 1 (`throw`). "Không xác nhận" chỉ hiện ra như exit 1 của một lỗi khác |
| 4 | Kiểm tra job của `OWNER_DEPLOY` và `OWNER_CUSTOMER_ID` không thấy job đang chạy | PowerShell 5.1 đưa cả danh sách JSON của `Invoke-RestMethod` xuống pipeline như **một** đối tượng; lần liệt kê job production 23:2x cho thấy đúng vậy (mọi ID trên một dòng). Test với bản cũ: 2 job, 1 đang chạy, `OWNER_CUSTOMER_ID` in "no job" rồi hỏi `CUSTOMER-ON`. `deploy-upgrade` vẫn bắt được job đang chạy (gán biến trước khi lọc), nên bước deploy không thiếu kiểm tra này; bước Customer ID thì không có lớp bảo vệ nào khác |
| 5 | `OWNER_CUSTOMER_ID` đợi mãi khi job D-1 bị hủy | Vòng đợi chỉ dừng ở SUCCEEDED / FAILED / SKIPPED, thiếu CANCELLED |
| 6 | `data-check` sau deploy có thể dừng nhầm (nguy cơ) | Được gọi với `$ErrorActionPreference = "Stop"` và `2>$null`. Thử nghiệm cách ly: một dòng stderr làm script dừng, dù stdout có JSON hợp lệ. Chưa kiểm tra `data-check` thật có ghi stderr hay không |

### Cách sửa

| File | Thay đổi |
|---|---|
| `scripts/deploy-upgrade.ps1` (repo, chưa commit) | Chỉ sửa nhánh hỏi xác nhận: bỏ phím đã gõ trước câu hỏi (`FlushInputBuffer`); in câu hỏi bằng `Write-Host` để có trong log; bỏ khoảng trắng hai đầu; nếu từ chối thì in câu trả lời đã nhận và số ký tự; nếu xác nhận thì ghi `confirmed: UPGRADE-<v>`. **Không đổi:** từ xác nhận, phép so sánh, thứ tự (backup → hỏi → cài) và `-ConfirmToken` |
| `OWNER_DEPLOY_1.2.13.ps1` | Hỏi `UPGRADE-1.2.13` ngay sau CheckOnly, **trước** backup và mọi thay đổi; tối đa 3 lần, Enter là dừng; log ghi câu hỏi và từng câu trả lời. Chuyển **đúng từ chủ hệ thống đã gõ** sang `deploy-upgrade -ConfirmToken`; `deploy-upgrade` kiểm tra lại với version trong gói. Exit code ≠ 0 của `deploy-upgrade`: dừng ngay với cùng exit code, không kiểm tra bản mới. Kiểm tra bản mới chỉ chạy khi version, `current.txt` và thư mục bản mới đều khớp. Exit code: 0 xong, 1 lỗi hoặc deploy dừng, 2–3 CheckOnly không đạt, 4 không xác nhận, 5 đã cài nhưng kiểm tra không đạt. Log `owner-deploy-1.2.13-<thời điểm>.log` |
| `OWNER_RELEASE_1.2.13.ps1` | Kiểm tra exit code của từng bước trước khi chạy bước sau, và dừng với đúng exit code đó. Dòng cuối liệt kê các bước đã xong. `CONTINUE` và `TRAIN` hỏi theo cùng cách. Training không thành công: exit 6. Log `owner-release-1.2.13-<thời điểm>.log` |
| `OWNER_CUSTOMER_ID_1.2.13.ps1` | Kiểm tra job đúng cách; `CUSTOMER-ON` hỏi theo cùng cách; CANCELLED kết thúc vòng đợi; kiểm tra cuối không đạt: exit 5. Log `owner-customer-id-1.2.13-<thời điểm>.log` |
| `backend/tests/test_v1213_deploy_preflight.py` | +9 test cho toàn bộ quá trình nâng cấp, tổng 15 |
| `tests/test_owner_scripts.py` (mới, trong thư mục báo cáo này, ngoài git) | 15 test cho chuỗi owner |
| `docs/VAN-HANH.md`, `CHANGELOG.md`, `docs/CHECKPOINT.md` | Cách trả lời câu hỏi xác nhận; mục "Unreleased"; checkpoint |

**Giữ nguyên:**
- Cả ba từ xác nhận vẫn do **chủ hệ thống tự gõ**. Script owner không có tham số nào để bỏ qua câu hỏi.
- Lệnh chạy của chủ hệ thống không đổi. Các tham số mới của script owner (`-Package`, `-ExpectedSha256`, `-Version`, `-BaseUrl`) mặc định là release thật và chỉ dùng để test trỏ vào bản giả.
- Gói 1.2.13 không build lại.

**Rollback:** bản trước lượt này của 3 script owner và `deploy-upgrade.ps1` nằm trong `checkpoints\release-1.2.13-owner-scripts-20261023.zip` (thư mục `before/`).

### Test (môi trường giả lập cách ly)

- Mỗi test chạy script PowerShell thật với:
  - `LOCALAPPDATA` và `TEMP` tạm;
  - CLI giả, chỉ dùng stdlib;
  - app giả trên cổng ngẫu nhiên (không bao giờ 8765);
  - gói giả 9.8.7, có `install.ps1` chỉ báo "stop/start" về app giả.
- Vì version là 9.8.7, không câu trả lời nào trong test xác nhận được gói thật.
- Không test nào trả lời `CUSTOMER-ON` hay `TRAIN`.
- Test gõ câu trả lời qua stdin, nên việc bỏ phím gõ sớm (cần console thật) **không** được test tự động.

| Bộ test | Trước khi sửa | Sau khi sửa |
|---|---|---|
| `backend/tests/test_v1213_deploy_preflight.py` (15): `deploy-upgrade.ps1` thật | 10 passed / **5 failed**: không bỏ khoảng trắng; không in câu trả lời bị từ chối | **15 passed** |
| `tests/test_owner_scripts.py` (15): 3 script owner + `deploy-upgrade.ps1` thật | **15 failed**. Bản cũ chỉ được đổi giá trị production thành tham số; script trong `scratchpad\p36\make_before.py` kiểm tra không còn 8765, hash hay đường dẫn gói thật | **15 passed** |
| `scripts\run-tests.ps1` (toàn bộ; unit + integration, 23:52–00:02, log `logs\development\tests_20261022_235218.log`) | - | backend **797 passed / 19 skipped / 0 failed** (788 + 9 test mới; 1 cảnh báo deprecation có sẵn của `starlette`); vitest 26 file / **159 passed**; typecheck OK; build OK |
| Lint | - | không cấu hình |

Với bản cũ:
- **11 test FAIL vì lỗi thật:**
  - chạy tiếp sau deploy thất bại (2 test `OWNER_DEPLOY`, 2 test `OWNER_RELEASE`);
  - không xác nhận hoặc không có console thì vẫn backup rồi lỗi (3 test);
  - exit 0 khi kiểm tra không đạt;
  - exit 3 thành 1;
  - không thấy job đang chạy (2 test; test của Customer ID được chạy lại với danh sách 2 job).
- **4 test FAIL chỉ vì tính năng mới:** log của script owner, hỏi lại tối đa 3 lần, exit code 4.
- Kết quả: `evidence\tests_before_fix_*.txt`, `evidence\tests_after_fix_*.txt`.

Chạy lại (khoảng 1 phút), từ `D:\Buymed\Lightgbm AI`:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider reports\release-1.2.13-20261022\tests backend\tests\test_v1213_deploy_preflight.py
```

### Production không bị thay đổi trong lượt này

- **Chỉ đọc:**
  - `GET /api/health`, `/api/system/paths`, `/api/jobs`, `/api/system/status`;
  - `current.txt`, hash `storage.json`;
  - log deploy và `app.log`;
  - hash của backup 23:10.
- **Kết quả** (kiểm tra cuối lúc 23:59:14):
  - 1.2.11, PID 7316 (khởi động 21/10 18:08:10), `current.txt` 1.2.11;
  - không có thư mục 1.2.13;
  - `storage.json` `8D79DBDD…E047`;
  - không có job đang chạy;
  - 3 backup ngày 22/10 vẫn đủ.
  - Job mới nhất là `ACTUAL_CLOSE` 23:59 do lịch của chính app chạy, SUCCEEDED; không liên quan lượt này.
- **Không chạy:** deploy, CheckOnly production, Customer ID, reload, training, forecast. Không sửa lịch, không push, không xóa backup, dữ liệu hay artifact.

### Lệnh tiếp theo (chỉ sau khi anh/chị xem xét và quyết định tiếp tục)

*(Đã chạy lúc 00:04 ngày 23/10: bước 1–2 đạt, bước 3 dừng. Lệnh tiếp theo hiện tại nằm ở mục đầu báo cáo; **không** chạy lại lệnh dưới đây.)*

Chạy bằng tài khoản `Giau Vo` (`whoami` = `log-pc\giau vo`), trong khung 18:30–21:45 hoặc 00:05–05:00, khi không có job:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\reports\release-1.2.13-20261022\OWNER_RELEASE_1.2.13.ps1"
```

- Câu hỏi `UPGRADE-1.2.13` giờ hiện **ngay sau CheckOnly** (khoảng 30 giây sau khi chạy), trước backup.
  - Chỉ gõ khi câu hỏi đã hiện; phím gõ trước sẽ bị bỏ.
  - Tối đa 3 lần. Enter là dừng; ở câu `TRAIN`, Enter nghĩa là không huấn luyện ngay.
- Nếu dừng giữa chừng:
  - dòng cuối ghi các bước đã xong và đường dẫn log `logs\runtime\owner-release-1.2.13-<thời điểm>.log`;
  - exit code cho biết lý do (0 xong, 1 lỗi hoặc deploy dừng, 2–3 CheckOnly, 4 không xác nhận, 5 kiểm tra không đạt, 6 training không thành công).

## Điều tra lỗi CheckOnly do chủ hệ thống chạy (22/10, khoảng 22:00–22:50)

**Kết luận:**
- CheckOnly chạy từ **tài khoản Windows `Administrator`**, không phải tài khoản `Giau Vo` đang chạy app.
- Script đã chặn đúng và **không thay đổi gì**.
- Có thêm 1 lỗi tiềm ẩn của preflight (CLI bị che bởi thư mục hiện tại); lỗi này đã được sửa và có test.
- Production không bị chạm tới trong lượt này.

| # | Lỗi quan sát | Nguyên nhân gốc (bằng chứng) |
|---|---|---|
| 1 | `storage-verify` không có trong CLI | `deploy-upgrade.ps1` lấy thư mục cài từ `%LOCALAPPDATA%` **của tài khoản đang chạy script** (dòng 17). Từ `current.txt` của thư mục đó, nó chạy `…\<version>\python\python.exe -m app.cli` với `PYTHONPATH=…\<version>\backend` (dòng 41–47). Ở tài khoản Administrator đó là một **bản 1.1.0 cũ, riêng**. Danh sách lệnh mà chủ hệ thống thấy (không có `storage-verify`, `storage-repair`) là của một bản 1.1.0 có trước bản sửa lưu trữ ngày 14/10. Đây là suy luận, vì không đọc được bản cài trong profile Administrator. Bản 1.1.0 build lại 14:45 (có trong profile Giau Vo) **đã có** `storage-verify`, cũng như mọi bản từ 1.1.1 đến 1.2.11. `storage-verify` là kiểm tra đúng nghĩa: chỉ đọc, đối chiếu `storage.json`, `storage-id.json`, lịch sử migration và DB (`storage_migrate.py:360`). Không thay bằng `storage-inventory` |
| 2 | `current.txt` = 1.1.0, app = 1.2.11 | Mỗi tài khoản có `current.txt` riêng (do `install.ps1` / `rollback-version.ps1` của tài khoản đó ghi). Bản production: `C:\Users\Giau Vo\AppData\Local\Programs\DemandForecast\current.txt` = **1.2.11**, đúng. PID 7316 chạy với `LOG-PC\Giau Vo` từ `…\Giau Vo\…\1.2.11\python\python.exe` (`tasklist /V`). Cổng 8765 dùng chung cả máy, nên phiên Administrator gọi trúng app 1.2.11 của Giau Vo. Không sửa `current.txt` nào |
| 3 | DB / `storage.json` dưới `C:\Users\Administrator` | Đúng kiến trúc: cấu hình lưu trữ theo từng tài khoản. Production dùng `C:\Users\Giau Vo\AppData\Local\DemandForecast\storage.json` → dữ liệu ở `D:\Buymed\Lightgbm AI\data\runtime` (`GET /api/system/paths`). Thư mục DemandForecast dưới profile Administrator tồn tại, nhưng tài khoản Giau Vo không đọc được ("Permission denied"); không đọc nội dung |
| 4 | "nothing was changed" | Đúng: precheck dừng ở `exit 3` trước mọi bước ghi (dòng 74 cũ). Production vẫn là 1.2.11, `storage.json` không đổi |
| 5 (mới) | CLI có thể bị thay bằng mã ở thư mục hiện tại | `python -m app.cli` đặt **thư mục hiện tại** lên đầu `sys.path`. Nếu người chạy đứng ở thư mục có package `app` (ví dụ `backend` của repo), precheck chạy mã đó thay vì CLI của bản cài. Test hồi quy phát hiện lỗi này (trace chạy `D:\Buymed\Lightgbm AI\backend\app\cli.py`) |
| 6 (mới) | CLI không trả đường dẫn thì vẫn chạy tiếp | Script cũ chạy tiếp với đường dẫn rỗng và mặc định cổng 8765, tức gọi vào app thật. Khi kiểm chứng test trên script cũ, việc này đã gây 2 lần GET chỉ đọc (`/api/health`, `/api/jobs`) vào production; không ghi gì |

**Thay đổi** (chưa commit; rollback: `git restore scripts/deploy-upgrade.ps1 docs/VAN-HANH.md CHANGELOG.md` và xóa file test mới):

| File | Thay đổi |
|---|---|
| `scripts/deploy-upgrade.ps1` | Dòng thông tin: tài khoản Windows và thư mục cài. Kiểm tra mới: app trên cổng phải là **bản cài của tài khoản này**, tức cùng DB và cùng `storage.json` theo `GET /api/system/paths`; nếu không thì FAIL "run the upgrade as the Windows user that runs the app". CLI chạy từ thư mục `backend` của bản cài (`Push-Location`). CLI không trả đường dẫn thì dừng ngay (`exit 2`). Gợi ý rõ khi thiếu `storage-verify`. **Không bỏ hay nới kiểm tra nào**; vẫn chỉ dùng ASCII và LF |
| `backend/tests/test_v1213_deploy_preflight.py` (mới, 6 test) | Chạy `deploy-upgrade.ps1 -CheckOnly` thật trong `LOCALAPPDATA` tạm, với CLI giả (chỉ stdlib) và app giả trên cổng ngẫu nhiên (không bao giờ 8765). Các ca: (1) tài khoản khác có bản 1.1.0 cũ → BLOCKED, nêu nguyên nhân, không ghi gì; (2) tài khoản khác cùng version → BLOCKED (script cũ cho PASS); (3) **lệch version ở đúng tài khoản → vẫn BLOCKED**; (4) đứng ở thư mục có `app` giả → dùng CLI của bản cài; (5) CLI không trả đường dẫn → dừng, không gọi app; (6) bản cài nhất quán → PASS, không ghi gì |
| `docs/VAN-HANH.md`, `CHANGELOG.md` | Phải chạy bằng đúng tài khoản Windows đang chạy app; mục "Unreleased - deploy preflight" |
| Script owner | **Không đổi.** Bước 2 của `OWNER_DEPLOY` gọi CheckOnly của script trong repo, nên tự có kiểm tra mới |

Gói 1.2.13 **không build lại**: `deploy-upgrade.ps1` chạy từ repo.

**Test:**

| Lần chạy | Loại | Kết quả |
|---|---|---|
| `test_v1213_deploy_preflight.py` | integration: script PowerShell thật + bản cài giả, cách ly | **6 passed** |
| Cùng các test, chạy với script cũ (`HEAD`) | kiểm chứng test bắt được lỗi | 5/5 FAIL như dự kiến (test số 6 không chạy với script cũ vì nó sẽ gọi cổng 8765 thật) |
| `scripts\run-tests.ps1` toàn bộ (22:29), log `logs\development\tests_20261022_222909.log` | unit + integration, DB tạm cách ly | backend **788 passed / 19 skipped / 0 failed**; vitest 26 file / **159 passed**; typecheck OK; build OK |
| Lint | - | không cấu hình |

**CheckOnly trong môi trường an toàn: PASS.**
- Script đã sửa chạy với bản cài **1.2.11 thật** của bản sao cách ly `r14`: CLI thật, `storage-verify` thật, app thật ở cổng 8879, scheduler tắt.
- Chạy từ thư mục trung lập: exit 0.
- Chạy từ `D:\Buymed\Lightgbm AI\backend` (ca bị che CLI): exit 0, vẫn dùng CLI của bản cài.
- Cả hai lần đều có "[OK] running app = this account's installation".
- Sau đó app diễn tập đã dừng; production vẫn là 1.2.11.

**Chưa xác minh trên production:**
- Script đã sửa **chưa chạy CheckOnly trên production** (lượt này giới hạn ở môi trường kiểm thử).
- Chưa đọc được nội dung bản cài trong profile Administrator (không có quyền), nên phiên bản 1.1.0 ở đó dựa trên log của chủ hệ thống.
- Deploy, Customer ID và training vẫn **NOT RUN**.

**Lệnh duy nhất cần chạy tiếp theo** (sau khi xem xét). *(Đã xong: CheckOnly này PASS trong lần chạy owner 23:10, bằng tài khoản Giau Vo. Lệnh tiếp theo hiện tại nằm ở mục đầu báo cáo.)* Chạy trong cửa sổ PowerShell của **tài khoản Giau Vo**; lệnh `whoami` phải ra `log-pc\giau vo`. CheckOnly chỉ đọc:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\scripts\deploy-upgrade.ps1" -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.13-win64-portable.zip" -ExpectedSha256 ABE0C9B1631095F86BFA5F8549F53DC9C25C308C433F8EAD53D5DB37E58B8469 -CheckOnly
```

Kết quả đúng phải có:
- `Windows account: Giau Vo`
- `[OK] running app = this account's installation`
- `PRECHECK OK`

Chỉ khi đạt mới chạy `OWNER_RELEASE_1.2.13.ps1`, cũng bằng tài khoản Giau Vo. Release **chưa** được coi là sẵn sàng triển khai cho tới khi CheckOnly này PASS trên production.

## Trạng thái thực thi release (cập nhật 22/10 21:47)

| # | Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|---|
| 1 | Version production thực tế | **1.2.11** | `/api/health` và `current.txt` = 1.2.11, PID 7316 (kiểm tra 21:22, 21:26, 21:34, 21:43); `storage.json` `8D79DBDD…E047` không đổi |
| 2 | Deploy 1.2.13 + migration 0010 | **BLOCKED** | CheckOnly chính thức PASS lúc 21:24, không thay đổi gì (`evidence\checkonly_1213_2124.txt`). Lệnh `deploy-upgrade … -ConfirmToken UPGRADE-1.2.13` bị bộ phân loại quyền từ chối lúc 21:25 (`[Production Deploy]`, lần thứ 4). Lệnh không chạy, không có gì được cài, migration không chạy |
| 3 | Backup / rollback | **PASS** (chuẩn bị) / **NOT RUN** (production) | Backup gần nhất `backup-20261022-111140-manual.zip`: SHA-256 `A3564E18…AFD6` khớp, `testzip` OK, có `db/app.db` và model. Đường rollback đã diễn tập trên bản sao (phase D). `deploy-upgrade` sẽ tự tạo backup trước khi cài |
| 4 | Customer ID + full reload | **NOT RUN** | Cần 1.2.13 chạy trước. Production: `customer_id_column` rỗng, `feature_customer` OFF |
| 5 | Sáu khóa `total_open_hours` | **NOT RUN** trên production; **PASS** trên bản sao | Production 1.2.11 vẫn chặn huấn luyện bằng `OPEN_HOURS_INVALID`. Bản sao: 6/6 được áp dụng sau nạp lại, `not_applied` rỗng |
| 6 | Training / model / forecast ID | **NOT RUN** trên production | Model và forecast đang dùng: `MV-20261020-131556-EEF6` / `FCR-20261020082402-A42C91`. Tham chiếu từ bản sao: `TRN-20261022125113-487BFA` / `MV-20261022-202359-7BFA` / `FCR-20261022132426-A8126A` |
| 7 | WAPE / bias | **NOT RUN** trên production; **PASS** trên bản sao (mục D) | Bản sao: WAPE 0,806, bias +6,1 %; model đang dùng trên cùng fold 0,807; baseline 0,849 |
| 8 | Model / forecast production có đổi không | **Không đổi** | Lần huấn luyện cuối vẫn là `TRN-20261020054540-D7EEF6` (đang dùng); forecast mới nhất vẫn là `FCR-20261020082402-A42C91` |
| 9 | Cổng quyền | **BLOCKED** | Không có quy tắc quyền nào được thêm sau lần từ chối (đã đọc `.claude/settings.json`, không có `settings.local.json`, cài đặt người dùng không có `permissions`). Không lặp lại lệnh bị từ chối |
| 10 | Gross demand / lịch D-1 | **BLOCKED** (ngoài phạm vi release) | Mục E2 và E3, không đổi |
| 11 | Việc người dùng cần làm | một thao tác | Chủ hệ thống chạy `OWNER_RELEASE_1.2.13.ps1` trong cửa sổ PowerShell của mình và tự gõ `UPGRADE-1.2.13`, `CUSTOMER-ON`, `TRAIN` (mục F, cách 1). Cả ba xác nhận đều là `Read-Host`, nên Claude không được gõ thay. Cách 2 (duyệt qua `/permissions` → *Recently denied* → `r`, chế độ *Manual*, hoặc quy tắc `ask`) chỉ mở được bước deploy cho Claude; `CUSTOMER-ON` và `TRAIN` vẫn cần chủ hệ thống |

**Đã chuẩn bị để tiếp tục ngay sau khi deploy chạy** (không tác động production):
- `scratchpad\p34\post_verify.py <A|B|C>`: kiểm tra chỉ đọc sau từng bước, gồm:
  - version, PID, `storage.json`, schema 10 và trigger;
  - cài đặt, lịch chạy, model và forecast đang dùng giữ nguyên;
  - backup do deploy tạo;
  - sáu khóa và audit trail của lần nạp;
  - coverage Customer ID, candidate, so sánh trên cùng fold.
- Đã chạy thử trên 1.2.11 lúc 21:43: các kiểm tra "giữ nguyên" PASS; các kiểm tra riêng của 1.2.13 FAIL đúng như dự kiến.
- `scratchpad\p34\eval_series2.py`: đánh giá theo SKU × FC trên bản sao, thêm 3 nhóm:
  - **ngày bị giới hạn giờ mở bán** (24 h / một phần / 0 h / không có giá trị);
  - **tháng** (để xem đợt giảm 8–9);
  - **FC**.

  Giới hạn: giờ mở bán chỉ có ở ngày có đơn.
- **Ổ C: chỉ còn 5,1 GB trống** (99 %). Bản sao để đánh giá sẽ thay thế bản sao `r14` cũ (DB production 848 MB), không chiếm thêm chỗ.

## A. RELEASE

**Status: BLOCKED ở bước triển khai production (cổng quyền). Bản phát hành 1.2.13 đã READY** (theo AGENTS.md: `READY_FOR_PRODUCTION`, chờ chủ hệ thống triển khai).
- QA, CheckOnly trên production và diễn tập trên bản sao production đều đạt.
- Trong batch này, dữ liệu production chỉ được đọc, không được ghi.

**Production trước / sau batch: 1.2.11 / 1.2.11.** Kiểm tra chỉ đọc lúc 17:59 và 20:53 ngày 22/10:
- `/api/health` và `current.txt` đều là 1.2.11 (PID 7316).
- `storage.json` có SHA-256 `8D79DBDD…E047`, không đổi.
- DB ở schema 9; `data-check` WARN với 2 cảnh báo cũ: `open_hours_window_ready` 6 và `forecast_series_meta` 1. Không có FAIL.
- Không có job đang chạy; log app không có ERROR từ 17:00.

**Version đích: 1.2.13.** Lý do:
- 1.2.13 chứa toàn bộ 1.2.12 (quy tắc MAX cho sáu khóa, tên thứ trong tuần). Ngoài ra nó có:
  - đồng bộ lịch sử giữ tổng cầu;
  - xác minh lại sáu khóa ở mỗi lần nạp;
  - Customer ID sẵn sàng bật;
  - giới hạn tài nguyên của job.
- 1.2.12 không đủ để đưa Customer ID lên production:
  - Bật Customer ID làm đổi mapping, nên D-1 kế tiếp nạp lại toàn bộ.
  - Ở 1.2.12, sáu khóa chỉ hợp lệ với đúng lần nạp đã duyệt. Sau lần nạp lại, chúng thành `RELOADED_SINCE_APPROVAL`, nên huấn luyện lại bị chặn bởi `OPEN_HOURS_INVALID`.
  - 1.2.13 thay điều kiện đó bằng một phép xác minh: mỗi lần nạp, nó so nguồn với bằng chứng đã duyệt.
- Không cần qua 1.2.12 làm bước trung gian:
  - 1.2.12 không có migration.
  - Từ 1.2.11 lên 1.2.13 chỉ chạy `0010_history_sync.sql`: thêm 5 bảng, không sửa bảng cũ.
  - Diễn tập nâng cấp thẳng 1.2.11 → 1.2.13 đã đạt.
- Lý do chọn không phải phần tối ưu RAM. Không bỏ thay đổi nào để thu nhỏ bản phát hành.

**Commit, gói và hash:**
- Commit trên `main`, chỉ ở máy này, không push:
  - `1b00c42`: release, gói được build từ commit này;
  - `e682cf3`: chỉ tài liệu, là bản ghi checkpoint của batch này;
  - đi trước `origin/main` 37 commit;
  - cây làm việc sạch.
- Gói `dist\DemandForecast-1.2.13-win64-portable.zip`:
  - SHA-256 `ABE0C9B1631095F86BFA5F8549F53DC9C25C308C433F8EAD53D5DB37E58B8469`;
  - 92.430.463 byte;
  - kèm `.sha256` và manifest.
- QA chính thức (`scripts\release.ps1`):

| Kiểm tra | Loại | Kết quả |
|---|---|---|
| Backend | unit + integration với BigQuery giả, DB tạm cách ly | **782 passed / 19 skipped / 0 failed** |
| Frontend vitest | unit UI | 26 file, **159 passed** |
| Typecheck, build | tĩnh / build | OK |
| Lint | - | không cấu hình |

- 19 bài skipped gồm các test cần BigQuery thật. Bằng chứng với nguồn thật lấy từ các lần diễn tập dưới đây.

**Deploy: chưa thực hiện.**
- `deploy-upgrade.ps1 -CheckOnly` trên production lúc 18:10:35 cho `PRECHECK OK` và không thay đổi gì. Các mục OK:
  - hash và version của gói;
  - gói không chứa credential;
  - `storage-verify`;
  - app 1.2.11 đang chạy;
  - không có job;
  - ổ D còn đủ chỗ.
- Bộ phân loại quyền của Claude Code đã từ chối lệnh triển khai chính thức `[Production Deploy]` lần thứ 3: 22/10 lúc 00:06, 11:20 và khoảng 18:11. Không có cách làm vòng nào.
- **Cập nhật 21:25:** chủ hệ thống yêu cầu triển khai bằng văn bản.
  - CheckOnly lại PASS lúc 21:24.
  - `deploy-upgrade -ConfirmToken UPGRADE-1.2.13` bị từ chối lần thứ 4 (`[Production Deploy]`).
  - Đã dừng đúng cổng.
  - Kiểm tra lúc 21:26: production vẫn là 1.2.11 (PID 7316), `storage.json` không đổi, không có backup mới, lệnh không chạy.
- Đã diễn tập trên bản sao production. Dữ liệu cách ly ở `scratchpad\r14`, scheduler tắt, BigQuery thật chỉ đọc:

| Phase | Kết quả |
|---|---|
| A. Nâng cấp 1.2.11 → 1.2.13 bằng `deploy-upgrade` | **20/21 PASS**. Mục FAIL duy nhất là dòng migration mới trong `schema_migrations` 9 → 10; dòng này phải có. Thời gian: 299 s, trong đó app không phục vụ 135 s. Backup online được tạo trước khi cài. Gate huấn luyện mở và sáu khóa được áp dụng. Lịch, cài đặt và model không đổi |
| B. Bật Customer ID và nạp lại toàn bộ | **10/11 PASS**. Mục FAIL là lỗi đọc kết quả của script diễn tập (PowerShell 5.1); dữ liệu đúng khi kiểm trực tiếp (mục B) |
| C. Huấn luyện có Customer ID và forecast | **8/8 PASS**. Candidate dùng 36 feature, trong đó có 3 feature khách. Promote **chỉ trên bản sao**. Forecast và 2 file Excel được tạo (mục D). Thời gian huấn luyện 34 phút, RAM cao nhất 2,9 GB |
| D. Rollback | **4/5 PASS**. 1.2.13 từ chối `rollback-version` khi DB ở schema 10. Sau đó `restore.ps1` của 1.2.11 với backup trước nâng cấp đưa DB về schema 9, mọi bảng giống trước nâng cấp (141 s). Cuối cùng `rollback-version -To 1.2.11` chạy được 1.2.11. Mục FAIL là định nghĩa kiểm tra: 6/6 phần cài đặt và 12/12 file model cũ giống hệt; chỉ dư 2 file model của candidate phase C. `restore` cố ý không xóa file, và DB không tham chiếu tới chúng |

**Backup:**
- `deploy-upgrade` tự tạo backup online trước khi cài. Bước này đã được diễn tập.
- Backup production gần nhất là `D:\Buymed\Lightgbm AI\backups\backup-20261022-111140-manual.zip`. Nó đã được xác minh trong batch trước (SHA-256 `A3564E18…AFD6`).

**Rollback:** DB sau nâng cấp ở schema 10, nên 1.2.11 cần dùng lại backup. Các bước:
1. Dừng app.
2. Chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.2.11\scripts\restore.ps1 -File <backup do deploy-upgrade in ra>`.
3. Chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.2.13\scripts\rollback-version.ps1 -To 1.2.11`.

Dữ liệu ghi sau thời điểm backup sẽ mất. Phase D đã kiểm đường này.

## B. CUSTOMER_ID

**Nguồn** (BigQuery chỉ đọc, có dry run, 22/10):
- Bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`, cột `customer_id INTEGER NULLABLE`.
- 9.000.299 dòng từ 01/01 đến 21/10:
  - 0 NULL, 0 rỗng;
  - **35.092** khách khác nhau. Con số cũ là 35.075; nay tăng vì có thêm ngày;
  - 974.552 đơn, mỗi đơn đúng **1** khách;
  - 1.363.690 / 1.363.690 khóa ngày × SKU × FC có khách.

**Mapping:**
- Cài đặt `bigquery.customer_id_column = customer_id`.
- SQL tổng hợp theo đúng grain ngày × SKU × FC:
  - số khách khác nhau;
  - số khách mua lại trong 90 ngày;
  - tổng số ngày kể từ lần mua trước. `LAG` chỉ nhìn các ngày trước đó.
- `customer_id` không phải khóa đơn, không phải khóa chặn trùng, không thay `so_code`. Khóa vẫn là `so_code, sku_code, fc_code, created_date`.
- Bản thân ID khách không đi vào model, nên không có vấn đề khách mới hay khách chưa từng thấy. Khách mới chỉ làm tăng số khách của ngày đó.

**Feature và parity giữa huấn luyện và dự báo:**
- Ba feature:
  - `cust_mean_28`;
  - `cust_repeat_share_28`;
  - `cust_repeat_interval_28`.
- Cả ba tính từ 28 ngày **trước** ngày gốc dự báo, tức khoảng [t−28, t). Ngày không có dữ liệu là NaN, không bao giờ là 0.
- Huấn luyện, backtest và forecast dùng cùng một hàm (`backend/app/ml/features.py:236-304`):
  - Với chiến lược DIRECT, feature lấy tại ngày gốc.
  - Nếu model cần feature khách mà dữ liệu không có, app báo lỗi `CUSTOMER_NOT_IN_PANEL` thay vì chạy với cột rỗng.
- Bằng chứng parity:
  - Chạy lại backtest của candidate ngoài app cho WAPE gộp **đúng bằng** giá trị app đã lưu: 0,8058044 trên 3.364.320 điểm.
  - Model được nạp lại và forecast trên bản sao (mục D).

**Trạng thái trên production: TẮT.**
- 1.2.11 có `feature_customer` OFF, coverage 0, lý do `TOGGLE_OFF`.
- Model đang dùng `MV-20261020-131556-EEF6` **không** dùng Customer ID.
- Bật sau khi triển khai bằng `OWNER_CUSTOMER_ID_1.2.13.ps1` (đã nằm trong batch chung, xem mục F).

**Diễn tập bật Customer ID trên bản sao** (mapping → validation → activate → `feature_customer` ON → D-1):
- D-1 nạp lại toàn bộ mất 831 s:
  - đọc 9.000.299 dòng, 0 dòng lỗi;
  - ghi 1.364.268 khóa.
- 1.363.690 khóa có số khách. 578 khóa không có, và đó đúng là các khóa chỉ còn tồn tại nhờ "dòng giữ" (nguồn đã bỏ).
- Coverage 99,96 % (ngưỡng 0,5), nên `used: true`. Lần huấn luyện kế tiếp có 36 feature.
- Sáu khóa giờ mở bán vẫn được áp dụng (6/6), nhờ chính lần nạp đó xác minh lại.
- Candidate trên bản sao `TRN-20261022125113-487BFA` có đủ 3 feature `cust_*`. Mức đóng góp (gain) của chúng xếp hạng 14, 15 và 23 trên 36 feature (mục D).

**Test:**

| File | Số test | Nội dung |
|---|---|---|
| `test_v129c_window_spike_customer.py` | 30 | feature khách |
| `test_v1213_six_key_reverify.py` | 14 | nạp lại toàn bộ khi bật Customer ID, sau đó rollback |

- Hai file trên nằm trong 782 test đạt.
- Bài test với BigQuery thật (`test_v129c_real_bq_items_customers.py`) bị skip trong QA. Bằng chứng với nguồn thật lấy từ truy vấn hồ sơ ở trên và phase B.
- Không còn lỗi đã biết.

## C. DEMAND

**Tổng cầu (gross demand):**
- Nguồn D-1 là đơn **chưa hủy tại lúc bảng được dựng lại**. Bảng được dựng lại khoảng 07:10 mỗi sáng và không có trạng thái hủy.
- 1.2.13 áp dụng `KEEP_OBSERVED_LINES`:
  - dòng đơn đã từng thấy mà nguồn bỏ đi được giữ lại;
  - không tự trừ đơn hủy;
  - không dùng trạng thái hiện tại để sửa ngược lịch sử.
- Mỗi thay đổi có nhật ký trước/sau, có thể rollback, và có thể giải phóng dòng giữ.
- Diễn tập nạp lại toàn bộ:
  - giữ 871 dòng `LINE_GONE` (6.323 đơn vị) và 62 dòng `ORDER_GONE` (466 đơn vị);
  - thêm 214 khóa mới;
  - khớp đúng diễn tập lịch sử trước đó (933 dòng / 6.789 đơn vị).
- Lần nạp lại toàn bộ khi bật Customer ID cũng chính là lần đồng bộ lịch sử đầu tiên, nên không cần backfill riêng.
- **Phần không phục hồi được** (E2): đơn hủy **trước** lần nạp đầu không có trong nguồn. Ở 01–21/10, đơn hủy là 67.738 đơn vị, bằng 4,0 % nguồn (theo `fact_order_item`).

**Grain và FC:**
- Grain là `created_date × sku_code × fc_code`.
- FC lấy từ cột nguồn `fc_code`.
- Hậu tố .1/.2/.3 chỉ là nơi SKU được tạo, không bao giờ dùng để suy FC hay vùng (`test_v129e_item_suffix.py`).

**`WAIT_TO_CONFIRM`:**
- `so_code` NULL được phép: 880 dòng không có `so_code`, tất cả đều `WAIT_TO_CONFIRM`.
- Các dòng này được miễn chặn trùng, không bị gộp, không bị bỏ.
- Mọi trạng thái khác vẫn bị chặn trùng tuyệt đối (`connector.py:654-668`, `test_v129h_pending_orders_grain.py`, 16 test).

**`MULTI_ITEM` và `item_code`:**
- `item_code` không thuộc grain, không phải khóa gộp, không phải tiêu chí trùng (`DUP_NOT_COMPARED_FIELDS`).
- Cột này chỉ dùng cho audit, ví dụ giờ mở bán theo từng listing.
- Không tự mở rộng ngoại lệ nào.

**`total_open_hours`:**
- Là feature bắt buộc. Thiếu thì app phát hiện và cảnh báo theo từng trạng thái (MISSING / OUT_OF_RANGE / CONFLICT / MULTI_ITEM), **không bao giờ tự điền**.
- MAX chỉ áp dụng cho **đúng sáu khóa** đã duyệt, và chỉ khi nguồn còn khớp bằng chứng: số lượng, số đơn, giá trị của từng listing.
- Mỗi lần nạp, kết quả xác minh được ghi vào `demand_sync_runs.summary_json.open_hours_override` làm audit trail.
- Nếu một listing đổi giá trị, khóa đó thành `LISTING_VALUES_CHANGED` và không được áp dụng (có test). Rollback trả về trạng thái trước.
- Diễn tập: 1.363.684 khóa OK, 6 `MULTI_ITEM`, 6/6 áp dụng, `not_applied` rỗng.

**Weekday:**
- Thứ 2 = 1 … Chủ nhật = 7.
- Huấn luyện lấy từ `created_date`, forecast lấy từ ngày được dự báo.
- UI hiện tên thứ tiếng Việt, không đổi encoding (`test_v1212_weekday_parity.py`, 8 test).

**Price và các feature khác:**
- Giữ `unit_price ← sales_price`; `price_last` và `price_rel_28` bật.
- `sku_system_status` chỉ là cột tham chiếu, không phải input của model.
- Deal và voucher chưa có cột nguồn, nên chưa dùng.

**Đã hoàn tất:** mọi quy tắc trên có trong mã 1.2.13, có test và đã diễn tập với nguồn thật.

**Blocker:**
- Các quy tắc này chưa chạy trên production (E1).
- Đơn hủy trước lần nạp đầu không có trong nguồn (E2).

**Hiện tại trên production 1.2.11:**
- Huấn luyện **bị chặn** bởi `OPEN_HOURS_INVALID` (6 dòng `MULTI_ITEM`).
- Lần huấn luyện ngày 21/10 (2 lần) và 22/10 đều FAILED vì lý do này.

## D. FORECAST

**Đã chạy chưa:**
- **Production: chưa có forecast mới từ 20/10.**
  - Forecast production mới nhất là `FCR-20261020082402-A42C91`: model `MV-20261020-131556-EEF6`, gốc 20/10, dữ liệu đến 19/10, 17.138 series.
  - Các lần huấn luyện lúc 16:35 và 21:23 ngày 21/10, và 07:16 ngày 22/10 (giờ VN) đều FAILED `OPEN_HOURS_INVALID` trên 1.2.11.
  - Dữ liệu production đã có đến 21/10: D-1 chạy tay lúc 07:14 và 07:20 ngày 22/10 đều SUCCEEDED; D-0 18:00 SUCCEEDED.
- **Trên bản sao production (1.2.13, Customer ID bật): đã chạy để chủ hệ thống đánh giá.**

| Mục | Giá trị |
|---|---|
| Training run / model | `TRN-20261022125113-487BFA` / `MV-20261022-202359-7BFA` (SHA-256 `c3f8d18a…c441`) |
| Dữ liệu | 01/01 → **21/10** (cutoff), 17.134 series, 5.210.362 dòng huấn luyện, 36 feature |
| Forecast | `FCR-20261022132426-A8126A`, gốc 22/10, dữ liệu đến 21/10, horizon 7 và 15 ngày, FC BD và HN |
| Phương pháp theo series | LightGBM 4.215; quy tắc gián đoạn 9.397; không hoạt động = 0: 3.326; series mới 196. LightGBM chiếm 95,4 % tổng dự báo |
| Excel 7 ngày | `FORECAST_CANDIDATE_CUSTOMER_FCR-20261022132426-A8126A_7d_vi.xlsx` (17.134 SKU × FC, 119.938 dòng ngày), SHA-256 `CE24A92F…B9A1` |
| Excel 15 ngày | `…_15d_vi.xlsx` (17.134 SKU × FC, 257.010 dòng ngày), SHA-256 `85669AFC…202A` |
| Báo cáo chất lượng | `FORECAST_QUALITY_TRN-20261022125113-487BFA_20261022-2049.xlsx`, SHA-256 `0B44820F…3856`. 13 sheet: fold, nhóm nhu cầu, khối lượng, spike, horizon, tổng 7/15/30 ngày, phương pháp, so với model đang dùng, toàn bộ SKU × FC, A/B Customer ID, forecast. Mọi chênh lệch là công thức |

**Tổng dự báo so với thực tế gần nhất:**

| FC | 7 ngày tới | 7 ngày qua | Chênh lệch | 15 ngày tới | 15 ngày qua | Chênh lệch |
|---|---:|---:|---:|---:|---:|---:|
| BD | 403.409 | 418.829 | −3,7 % | 834.236 | 916.979 | −9,0 % |
| HN | 151.283 | 154.420 | −2,0 % | 309.490 | 308.190 | +0,4 % |

Dự báo có nhịp tuần:
- Thứ 7 và chủ nhật: 58.000–70.000 đơn vị/ngày.
- Phần lớn ngày thường: 79.000–88.000 đơn vị/ngày.
- Thứ 2 ngày 02/11 thấp hơn: 65.000.

**Độ chính xác.** Backtest walk-forward: 7 fold × 30 ngày, từ 26/03 đến 21/10, 3.364.320 điểm SKU × FC × ngày, 27,3 triệu đơn vị. Mỗi fold chỉ học từ các ngày trước gốc của nó.

| Chỉ số | Candidate (Customer ID) | Model đang dùng, huấn luyện lại trên cùng fold | Baseline 28 ngày |
|---|---:|---:|---:|
| WAPE ngày, SKU × FC | **0,806** | 0,807 | 0,849 |
| Bias | +6,1 % | +6,0 % | +12,9 % |
| So sánh | **BETTER**, nhưng chỉ −0,0016 WAPE (không đáng kể) | - | - |

- Quality gate: `WAPE_MAX` FAIL (0,806 > 0,6). Ngưỡng 0,6 **chưa được nghiệp vụ duyệt** (`thresholds_approved_by_business: false`). Các check còn lại PASS.
- Trạng thái sử dụng: `USABLE_WITH_WARNING`. Không promote trên production; quyết định thuộc chủ hệ thống.

**Theo horizon và tổng kỳ** (cùng các điểm trên):

| Horizon | WAPE ngày | Baseline | Tổng kỳ theo SKU × FC | WAPE tổng kỳ | Baseline |
|---|---:|---:|---|---:|---:|
| Ngày 1–7 | 0,748 | 0,794 | 7 ngày | **0,529** | 0,557 |
| Ngày 8–15 | 0,805 | 0,846 | 15 ngày | **0,489** | 0,518 |
| Ngày 16–30 | 0,834 | 0,878 | 30 ngày | **0,479** | 0,514 |

Tổng kỳ là sai số của **tổng số lượng** 7/15/30 ngày của mỗi SKU × FC, tức số lượng đặt hàng. Ở mức này sai số theo ngày bù trừ nhau một phần.

**Theo nhóm nhu cầu** (nhóm tính từ lịch sử trước gốc của mỗi fold):

| Nhóm | Điểm | Đơn vị (tỷ trọng) | WAPE | Baseline | Bias |
|---|---:|---:|---:|---:|---:|
| SMOOTH | 146.790 | 10,0 tr (37 %) | **0,510** | 0,539 | +3,1 % |
| ERRATIC | 360.960 | 12,7 tr (47 %) | 0,869 | 0,928 | +10,7 % |
| INTERMITTENT | 1.168.020 | 0,71 tr (3 %) | 1,251 | 1,289 | −13,2 % |
| LUMPY | 1.329.480 | 3,49 tr (13 %) | 1,295 | 1,326 | +4,9 % |
| SHORT_HISTORY (series mới) | 137.280 | 0,32 tr (1 %) | 1,241 | 1,241 | −16,4 % |
| INACTIVE | 221.790 | 0,02 tr | 1,000 | 1,000 | −100 % |
| Ngày đột biến (spike) | 30.827 | 4,49 tr (16 %) | 0,836 | 0,840 | **−82,9 %** |
| Ngày thường | 3.333.493 | 22,8 tr | 0,800 | 0,851 | **+23,7 %** |
| SKU × FC khối lượng cao | 254.760 | 21,5 tr (79 %) | 0,716 | 0,767 | +7,3 % |

**Theo fold.** Model tốt hơn baseline ở 6/7 fold.
- Kém hơn baseline ở fold đầu (26/03–24/04): WAPE 0,890 so với 0,858, bias +28 %. Fold này chỉ có 84 ngày lịch sử để học.
- Kém nhất ở fold 23/08–21/09: WAPE 1,044 (baseline 1,225), bias +14 %. Nhu cầu fold đó giảm còn 2,58 triệu đơn vị, so với 3,6–5,0 triệu ở 5 fold trước.
- Fold mới nhất (22/09–21/10, 2,44 triệu đơn vị): WAPE 0,855 (baseline 0,891), bias −0,6 %.

**Theo SKU × FC.** Backtest được chạy lại ngoài app trên cùng fold; WAPE gộp đúng bằng giá trị đã lưu.
- **BD:** 8.583 series, 19,2 triệu đơn vị, WAPE **0,738**, bias +3,6 %.
- **HN:** 8.551 series, 8,2 triệu đơn vị, WAPE **0,965**, bias **+12,1 %**. HN bị dự báo thừa nhiều hơn.
- **2.114 SKU × FC** (12 % số series) tạo 80 % sai số. Nhóm này chiếm 87 % đơn vị, có WAPE 0,741, và 1.491 series trong đó tốt hơn baseline.
- Chỉ 6.046 / 16.495 series có nhu cầu là tốt hơn baseline 28 ngày. Nhưng các series này chiếm **71,6 %** đơn vị.
- Danh sách đầy đủ ở sheet `Series_SKU_FC`: xếp theo sai số, có WAPE theo ngày 1–7 / 8–15 / 16–30.

**A/B Customer ID** (cùng dữ liệu, fold và điểm; chỉ tắt 3 feature khách):

| | Không có khách (33 feature) | Có khách (36 feature) | Chênh lệch |
|---|---:|---:|---:|
| WAPE gộp | 0,8074 | 0,8058 | **−0,0016** |
| Bias | +6,3 % | +6,1 % | −0,1 điểm % |
| WAPE ngày 1–7 / 8–15 / 16–30 | 0,7483 / 0,8053 / 0,8374 | 0,7481 / 0,8052 / 0,8343 | −0,0002 / −0,0001 / −0,0031 |
| Fold tốt hơn | - | 4/7 | **kém hơn ở 2 fold mới nhất**: 23/08–21/09 +0,010; 22/09–21/10 +0,013 |
| SKU × FC có sai số thấp hơn / cao hơn | - | 5.742 / 4.361 (49,5 % / 49,4 % đơn vị) | 7.031 không đổi (series dùng quy tắc dự phòng) |

**Kết luận về Customer ID:**
- Model thực sự dùng Customer ID: gain của 3 feature xếp hạng 14, 15 và 23.
- Trên toàn kỳ có cải thiện nhỏ, giống thí nghiệm ngày 21/10 (−0,0035), nhưng **không nhất quán**: kém hơn trong 2 tháng gần nhất.
- Vì vậy **không thể nói Customer ID làm forecast tốt hơn rõ rệt**.
- Theo yêu cầu đã chốt, Customer ID vẫn nằm trong release. Nếu chủ hệ thống muốn, có thể bật/tắt bằng công tắc model `feature_customer` mà không cần nạp lại dữ liệu.

**Nhóm chưa đạt và nguyên nhân đã kiểm chứng:**
1. **Gián đoạn / lumpy / series mới:** WAPE 1,24–1,30.
   - Nhóm này chiếm 2,6 triệu điểm nhưng chỉ 4,5 triệu đơn vị (17 %).
   - Khoảng một nửa số điểm này do quy tắc dự phòng dự báo: `FALLBACK_INTERMITTENT` có 1,32 triệu điểm, WAPE 1,504, bias −29 %.
   - Ở mức ngày, đơn lẻ tẻ gần như không đoán được. Ở mức tổng 7/15/30 ngày, sai số thấp hơn nhiều.
2. **Ngày đột biến:** dự báo thiếu 83 %.
   - Nguồn không có cột deal, voucher hay promotion; registry ghi "chưa có cột nguồn".
   - Vì vậy model không biết trước đợt đột biến. Đổi lại, nó dự báo thừa 24 % ở ngày thường.
3. **Mùa nhu cầu giảm tháng 8–9:** model trễ nhịp, bias +14 % ở fold đó.
4. **HN bị dự báo thừa** (bias +12,1 %, so với +3,6 % ở BD).
5. **Ngưỡng `WAPE_MAX` 0,6:** cả model đang dùng và candidate đều không đạt ở mức ngày SKU × FC. Ngưỡng này chưa được duyệt.

**Nhóm đạt mức khá:**
- Series SMOOTH: WAPE 0,510.
- SKU × FC khối lượng cao: WAPE 0,716.
- Tổng số lượng 7/15/30 ngày theo SKU × FC: WAPE 0,48–0,53.

So với baseline 28 ngày:
- Candidate tốt hơn hoặc bằng baseline ở mọi nhóm nhu cầu, khối lượng và horizon.
- Bằng nhau ở nhóm series mới và nhóm không hoạt động, vì hai bên dùng cùng quy tắc dự phòng.
- Candidate chỉ kém baseline ở fold đầu tiên.

## E. BLOCKERS

**E1. Triển khai production bị cổng quyền chặn** (chặn release).
- Bằng chứng:
  - Bộ phân loại quyền của Claude Code đã từ chối `[Production Deploy]` 3 lần (22/10 00:06, 11:20, ~18:11).
  - CheckOnly PASS lúc 18:10:35.
  - Production vẫn là 1.2.11.
- Hệ quả:
  - Production không huấn luyện được từ 21/10 (`OPEN_HOURS_INVALID`), nên forecast production dừng ở bản 20/10.
  - Customer ID và quy tắc tổng cầu chưa chạy trên production.
- Hành động: chủ hệ thống chạy một lệnh (mục F).

**E2. Nguồn chưa có tổng cầu đầy đủ** (giảm độ tin cậy của target; không chặn release).
- Bằng chứng:
  - Bảng D-1 được dựng lại mỗi sáng và không có trạng thái hủy.
  - Theo `fact_order_item`, đơn hủy 01–21/10 là 67.738 đơn vị, bằng 4,0 % nguồn; 92/92 dòng mẫu khớp SKU, FC, ngày và số lượng.
  - 1.2.13 chỉ giữ được những dòng app **đã từng thấy**. Đơn bị hủy trước lần nạp đầu thì không phục hồi được từ nguồn này.
- Hệ quả: target lịch sử là "đơn chưa hủy tại lúc làm mới". Mức thiếu chỉ đo được cho tháng 10 (khoảng 4 %).
- Hành động: chủ nguồn định nghĩa một nguồn tổng cầu có cả đơn hủy, ví dụ bảng hoặc SQL từ `fact_order_item` + `fact_order`, cùng phạm vi SKU/FC. Sau đó đối chiếu theo ngày với nguồn hiện tại (phần không hủy đã khớp 99,97 % trong 01–21/10). App không tự trừ hay tự dựng số liệu.

**E3. D-1 tự động chạy trước khi nguồn sẵn sàng** (chặn forecast hằng ngày tự động; không đổi vì cần phê duyệt).
- Bằng chứng:
  - D-1 theo lịch FAILED `SOURCE_INCOMPLETE` mỗi ngày 19–22/10, cả 4/4 lượt thử. Nguồn được làm mới khoảng 07:10, còn lịch D-1 là 06:00 (dự phòng 06:30). Lượt cuối hết lúc 06:38 ngày 21/10 và 07:06 ngày 22/10, đều trước giờ làm mới.
  - Dữ liệu 22/10 có được là nhờ D-1 chạy tay lúc 07:14 và 07:20.
  - Huấn luyện chờ D-1 của ngày.
- Hành động: chủ hệ thống duyệt giờ D-1 mới sau 07:10, ví dụ 07:30, trên trang lịch chạy. Batch này không đổi lịch.

## F. NEXT ACTION

1. **Cách 1 (đề nghị): chủ hệ thống chạy một lệnh** trong cửa sổ PowerShell của mình, khi không có job nào đang chạy.
   - Khung giờ: 18:30–21:45 hoặc 00:05–05:00. Ngoài khung, script hỏi `CONTINUE`; cả batch mất khoảng 55 phút và phải xong trước EOD 23:55.
   - Cách 2: chủ hệ thống duyệt để Claude chạy lại đúng lệnh `deploy-upgrade` bị từ chối. Có ba đường: `/permissions` → *Recently denied* → `r`; chế độ *Manual*; hoặc quy tắc `ask` trong `.claude\settings.local.json` (chi tiết trong `RESUME_CHECKPOINT.md`).
   - Sau cách 2, chỉ chạy `OWNER_CUSTOMER_ID_1.2.13.ps1` rồi bấm *Chạy ngay*, không chạy `OWNER_RELEASE` (nó sẽ cài lại 1.2.13). `CUSTOMER-ON` và `TRAIN` vẫn do chủ hệ thống xác nhận.

   ```powershell
   powershell -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\reports\release-1.2.13-20261022\OWNER_RELEASE_1.2.13.ps1"
   ```

   - Gõ `UPGRADE-1.2.13`: kiểm hash, CheckOnly, `deploy-upgrade` chính thức (có backup), rồi kiểm tra version, data-check và gate sáu khóa.
   - Gõ `CUSTOMER-ON`: ánh xạ `customer_id`, validation, bật production mode, bật `feature_customer`, rồi D-1 nạp lại toàn bộ. Diễn tập mất 14 phút. Sau bước này sẽ có cảnh báo `FULL_RELOAD_HELD_LINES`; mặc định là giữ.
   - Gõ `TRAIN` để huấn luyện ngay (diễn tập mất 34 phút), hoặc Enter để lịch 07:00 làm.
   - Script dừng ở bước đầu tiên không đạt. Cách rollback ở mục A.
2. **Xem candidate rồi quyết định promote** trên trang *Hiệu năng model*. Dùng kèm workbook chất lượng ở mục D để xem SKU × FC, nhóm nhu cầu, horizon và A/B Customer ID. Ngưỡng `WAPE_MAX` 0,6 chưa được duyệt, nên promote là quyết định của chủ hệ thống. Script không promote.
3. **Chủ nguồn:** nguồn tổng cầu gồm đơn hủy (E2) và giờ D-1 (E3).
