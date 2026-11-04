# Resume checkpoint - release 1.2.13 (cập nhật 23/10/2026 01:00)

## Trạng thái hiện tại (sau lần chạy owner 00:04)

| Bước | Trạng thái | Bằng chứng / ghi chú |
|---|---|---|
| Production | **1.2.13** (PID 22004 từ 00:12:23), schema 10, `storage.json` `8D79DBDD…E047` (không đổi) | Kiểm tra chỉ đọc 00:20–00:45 |
| Phase A: deploy | **DONE** 00:06–00:12 (chủ hệ thống chạy `OWNER_RELEASE`) | `logs\runtime\deploy-20261023-000655.log`: "UPGRADE OK: 1.2.11 -> 1.2.13". Kiểm tra sau deploy: "DEPLOYED AND VERIFIED" (data-check WARN 2 mục, training gate mở, sáu khóa 6/6). Bước 2 verification PASS. Backup: `backup-20261023-000655-manual.zip`, `…-001008-pre-migration-v9.zip`, `…-001039-cli.zip` |
| Phase B: Customer ID | **DỪNG trước mọi thay đổi** (00:13, exit 1) | `CUSTOMER-ON` đã gõ đúng. Bước 3 lỗi "Cannot bind parameter 'Headers'" (lỗi tên biến trong script), nên yêu cầu lưu mapping **chưa được gửi**. Chỉ đọc 00:39: Customer ID **OFF**, production mode ON, không có job hay reload nào. `evidence\prod_customer_id_state_20261023.json` |
| Script owner | **ĐÃ SỬA (00:20–01:00), chưa chạy lại** | Mục đầu của `FINAL_REPORT.md` |
| Phase C: training | NOT RUN | Lịch 07:00 sẽ huấn luyện candidate (không promote). Nếu lúc đó Customer ID vẫn OFF, candidate không có đặc trưng khách hàng |

**Không chạy lại `OWNER_RELEASE`:** bước 1 của nó sẽ hỏi `UPGRADE-1.2.13` và cài lại 1.2.13. Bước tiếp theo chỉ là `OWNER_CUSTOMER_ID_1.2.13.ps1` (lệnh ở mục "Cập nhật 23/10 00:13" bên dưới).

## Cập nhật 23/10 00:13 – 01:00: bước Customer ID dừng ở lỗi `-Headers`, script đã sửa

- **Nguyên nhân:** `OWNER_CUSTOMER_ID` dòng 33 (`$H` = bảng header `X-DF-Client`) bị dòng 62 (`$h = <kết quả /api/health>`) ghi đè, vì tên biến PowerShell không phân biệt hoa thường. Dòng 52 (`-Headers $H`, gọi từ dòng 76) lỗi khi gán tham số, trước khi gửi request. `OWNER_RELEASE` có cùng cặp biến (dòng 32/75/93, yêu cầu `TRAIN`).
- **Đã sửa:** bảng header đổi tên thành `$WebHeaders` trong cả hai script. `OWNER_CUSTOMER_ID` thêm:
  - đọc và in trạng thái Customer ID; thiếu trường cần thiết thì dừng trước câu hỏi;
  - đọc lại sau mỗi bước ghi;
  - bỏ qua bước đã làm, nên chạy lại an toàn;
  - kiểm tra lần cuối trước reload (không có job, đủ trạng thái);
  - không chạy D-1 thứ hai khi đã có một D-1 đang chạy;
  - lỗi HTTP in kèm câu trả lời của app.
- **Lệnh tiếp theo** (chỉ khi anh/chị quyết định): tài khoản `Giau Vo`, khung 00:05–05:00 (trước D-1 06:00), khi không có job. Mất khoảng 15–20 phút: validation vài phút, full reload khoảng 14 phút.

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\reports\release-1.2.13-20261022\OWNER_CUSTOMER_ID_1.2.13.ps1"
```

## Trạng thái trước lần chạy owner 00:04 (lưu lại)

| Bước | Trạng thái | Bằng chứng / ghi chú |
|---|---|---|
| Production | **1.2.11** (PID 7316), schema 9, `storage.json` `8D79DBDD…E047` | Kiểm tra chỉ đọc 23:20–23:57; không có job đang chạy, không có thư mục 1.2.13 |
| Source / gói | READY | Commit `1b00c42` (release) và `e682cf3` (docs), chưa push, đi trước origin 37. Gói SHA-256 `ABE0C9B1631095F86BFA5F8549F53DC9C25C308C433F8EAD53D5DB37E58B8469`, không build lại. Sửa script trong repo **chưa commit** (`deploy-upgrade.ps1`, test, tài liệu) |
| Script owner | **ĐÃ SỬA, chưa chạy lại** | Sửa 23:15–00:15 (mục đầu của `FINAL_REPORT.md`). 30/30 test giả lập đạt; toàn bộ `run-tests.ps1`: backend 797 passed / 19 skipped / 0 failed, vitest 159, typecheck + build OK. Bản cũ: `checkpoints\release-1.2.13-master-batch-20261022.zip` và `checkpoints\release-1.2.13-owner-scripts-20261023.zip` (`before/`) |
| Backup | VERIFIED | `backup-20261022-231056-manual.zip` (do lần chạy 23:10 tạo) SHA-256 `105BEA65…E8E1`, có `db/app.db`. Bản trước: `backup-20261022-111140-manual.zip` `A3564E18…AFD6` |
| CheckOnly | **PASS** | 21:24 (`evidence\checkonly_1213_2124.txt`) và trong lần chạy owner 23:10 |
| Phase A: deploy | **NOT RUN** (dừng ở xác nhận) | 23:10, chủ hệ thống chạy `OWNER_RELEASE` bằng đúng tài khoản: CheckOnly PASS, backup, rồi `deploy-upgrade` dừng "not confirmed". Không dừng app, không cài gì. Trước đó, 21:25: Claude bị bộ phân loại quyền từ chối lần thứ 4 |
| Phase B: Customer ID | NOT RUN | Cần phase A trước |
| Phase C: training | NOT RUN | Cần phase A và B trước |
| Phase D: đánh giá | NOT RUN trên production | Tham chiếu từ bản sao: mục D của `FINAL_REPORT.md` |
| Đã thay đổi production | **Không có gì**, ngoài 1 backup trực tuyến lúc 23:10–23:12 | `logs\runtime\deploy-20261022-231056.log` |

## Cập nhật 22/10 23:10 – 23/10 00:15: lần chạy owner dừng ở xác nhận, script đã sửa

- **Lỗi 1:** câu trả lời mà `deploy-upgrade` nhận được không phải `UPGRADE-1.2.13`.
  - Câu hỏi hiện **sau** backup, khoảng 1,5–2 phút sau dòng "type UPGRADE-1.2.13 when asked".
  - `Read-Host` trả về trong khoảng 3 giây.
  - Không log nào ghi lại câu trả lời (transcript không ghi `Read-Host`).
  - Khả năng cao nhất: phím đã gõ sẵn (ví dụ Enter) trước khi câu hỏi hiện.
- **Lỗi 2:** `OWNER_DEPLOY` không kiểm tra exit code của lần deploy, nên chạy tiếp kiểm tra 1.2.13 và lỗi `Push-Location`.
- **Đã sửa:**
  - Từ xác nhận được hỏi ngay sau CheckOnly, trước backup; phím gõ trước bị bỏ; tối đa 3 lần; câu hỏi và câu trả lời có trong log.
  - Mọi exit code ≠ 0 dừng ngay với đúng exit code đó.
  - Kiểm tra job đúng cách trong PowerShell 5.1.
  - Log `logs\runtime\owner-*-1.2.13-<thời điểm>.log`.
- **Test:** `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider reports\release-1.2.13-20261022\tests backend\tests\test_v1213_deploy_preflight.py`, kết quả 30 passed.
- **Chưa chạy lại `OWNER_RELEASE`:** chờ anh/chị xem xét và quyết định.

## Cập nhật 22/10 khoảng 22:50: CheckOnly của chủ hệ thống FAIL do chạy từ tài khoản Administrator

- **Nguyên nhân:** script chạy bằng tài khoản Windows `Administrator`. Tài khoản này có bản 1.1.0 cũ riêng, với `current.txt`, CLI và `storage.json` riêng. Trong khi đó app trên cổng 8765 là 1.2.11 của tài khoản `Giau Vo`.
- **Kết quả:** precheck chặn đúng, không thay đổi gì.
- **Đã sửa** `scripts/deploy-upgrade.ps1` (chưa commit):
  - kiểm tra app trên cổng có phải bản cài của chính tài khoản này;
  - CLI luôn chạy từ thư mục `backend` của bản cài;
  - CLI không trả đường dẫn thì dừng ngay.
- 6 test mới. CheckOnly PASS trên bản cài 1.2.11 thật của bản sao cách ly `r14`.
- Chi tiết ở mục đầu tiên của `FINAL_REPORT.md`.
- **Lệnh tiếp theo:** CheckOnly chạy trong cửa sổ PowerShell của **Giau Vo** (`whoami` = `log-pc\giau vo`), lệnh ở mục đó.
- Chỉ khi PASS mới chạy `OWNER_RELEASE_1.2.13.ps1`, cũng bằng Giau Vo.

## Việc người dùng cần làm (một trong hai cách)

**Cách 1 (đề nghị, đủ cả 3 bước): chủ hệ thống tự chạy**
- Mở cửa sổ PowerShell thường, bằng tài khoản Windows đang chạy app (`whoami` = `log-pc\giau vo`).
- Khung giờ: 18:30–21:45 hoặc 00:05–05:00, khi không có job. Ngoài khung, script hỏi `CONTINUE`.
- Cả batch mất khoảng 55 phút: deploy khoảng 5, Customer ID khoảng 15, training khoảng 35. Phải xong trước D-1 06:00, nên nếu bắt đầu sau khoảng 05:00 thì bỏ `TRAIN` (bấm Enter).

```powershell
powershell -ExecutionPolicy Bypass -File "D:\Buymed\Lightgbm AI\reports\release-1.2.13-20261022\OWNER_RELEASE_1.2.13.ps1"
```

Gõ từng từ **chỉ khi câu hỏi của nó đã hiện** (phím gõ trước bị bỏ). Mỗi câu hỏi cho tối đa 3 lần; Enter là dừng:
1. `UPGRADE-1.2.13`: hỏi ngay sau CheckOnly, khoảng 30 giây sau khi chạy, trước backup. Sau đó deploy-upgrade chính thức chạy backup online, cài, rồi kiểm tra sau deploy.
2. `CUSTOMER-ON`: mapping, validation, bật production mode, bật `feature_customer`, D-1 nạp lại toàn bộ.
3. `TRAIN`: huấn luyện ngay. Enter là để lịch 07:00 huấn luyện.

Script dừng ở bước đầu tiên không đạt, với exit code của bước đó. Dòng cuối ghi các bước đã xong và đường dẫn log. Script không promote. Xong thì báo Claude để chạy `post_verify.py` A/B/C và đánh giá.

**Cách 2 (chủ hệ thống duyệt để Claude chạy bước deploy).** Theo tài liệu chính thức của Claude Code (`code.claude.com/docs/en/auto-mode-config`, `/permissions`, `/permission-modes`), có ba cách. Cả ba đều do người dùng quyết định; Claude không tự đổi cài đặt.
- **2a.** Gõ `/permissions` → *Recently denied* → chọn lệnh `deploy-upgrade` bị từ chối lúc 21:25 → bấm `r`. Claude Code báo cho Claude được chạy lại đúng lệnh đó.
- **2b.** Chuyển chế độ quyền sang *Manual* (VS Code: bấm chỉ báo chế độ ở cuối ô nhập), rồi bảo Claude chạy lại. Anh/chị duyệt lệnh khi được hỏi.
- **2c.** Thêm quy tắc **`ask`** cho đúng lệnh vào `D:\Buymed\Lightgbm AI\.claude\settings.local.json` (`permissions.ask`). File này đã có trong `.gitignore` và có hiệu lực ngay, không cần khởi động lại.
  - Quy tắc phải khớp chính xác văn bản lệnh.
  - Tài liệu không nói rõ cách xử lý `&` và dấu nháy.
  - `allow` sẽ chạy không hỏi lại, nên không khuyến nghị cho lệnh có `-ConfirmToken`.

Sau khi Claude deploy và kiểm tra xong (`post_verify.py A`), anh/chị **không** chạy `OWNER_RELEASE` nữa: `deploy-upgrade` sẽ cài lại 1.2.13 một lần nữa. Thay vào đó:
1. Chạy `OWNER_CUSTOMER_ID_1.2.13.ps1` và gõ `CUSTOMER-ON`. Claude kiểm tra B.
2. Bấm *Chạy ngay* trên trang *Hiệu năng model* (huấn luyện). Claude kiểm tra C và đánh giá.

`CUSTOMER-ON` và `TRAIN` là xác nhận `Read-Host` trong script owner, nên Claude không gõ thay.

## Tiếp tục ở phiên Claude Code mới, sau khi deploy đã chạy

Không chạy lại các bước đã thành công. Thứ tự:

1. Kiểm tra trạng thái:
   - `GET http://127.0.0.1:8765/api/health`
   - `%LOCALAPPDATA%\Programs\DemandForecast\current.txt`
   - `/api/jobs`
2. Kiểm tra sau deploy (chỉ đọc). `<thời điểm bắt đầu>` là giờ địa phương ISO, ví dụ `2026-10-22T21:55:00`:

   ```
   .venv\Scripts\python.exe -X utf8 <scratchpad>\p34\post_verify.py A <scratchpad>\p34\post_A.json <scratchpad>\p34 <thời điểm bắt đầu>
   ```

3. Sau khi `CUSTOMER-ON` xong: chạy `post_verify.py B …`. Kiểm tra gồm:
   - job D-1 full reload SUCCEEDED, không dòng lỗi;
   - coverage Customer ID;
   - đúng 6 khóa được lần nạp xác minh trong `sync-runs`, tất cả khớp;
   - `held-lines`.
4. Sau khi `TRAIN` xong: chạy `post_verify.py C …`. Kiểm tra gồm:
   - candidate, feature, so sánh trên cùng fold;
   - model và forecast đang dùng không đổi.
5. Đánh giá theo SKU × FC trên bản sao:
   - Sao DB production bằng SQLite backup API (nguồn mở `mode=ro`) vào `<scratchpad>\r14\data\db\app.db`, thay bản cũ. Sao thêm `models\` và `storage-id.json`.
   - Chạy `p34\eval_series2.py` hai lần (như khi huấn luyện, rồi `customer_off`).
   - Chạy `p33\wb_quality.py` để có workbook.
   - Nếu `model_sha256` của candidate production trùng `c3f8d18a…c441` (candidate trên bản sao), forecast và workbook đã có áp dụng nguyên vẹn.
6. Không promote. Không đổi lịch. Không push.

`<scratchpad>` = `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad`. Ổ C: chỉ còn khoảng 5 GB trống.

## Rollback (nếu cần sau deploy)

DB sau nâng cấp ở schema 10. Dừng app, rồi chạy:
1. `%LOCALAPPDATA%\Programs\DemandForecast\1.2.11\scripts\restore.ps1 -File <backup do deploy-upgrade in ra>`
2. `%LOCALAPPDATA%\Programs\DemandForecast\1.2.13\scripts\rollback-version.ps1 -To 1.2.11`

Đã diễn tập trên bản sao (phase D, 4/5; mục FAIL đã giải thích).
