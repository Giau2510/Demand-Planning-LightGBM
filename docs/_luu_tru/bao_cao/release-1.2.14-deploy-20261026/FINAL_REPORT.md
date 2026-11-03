# Release 1.2.14 và dọn link từ xa (26/10/2026, 14:55-16:15)

## Trạng thái: `READY`

| Phần | Kết quả |
|---|---|
| Release | Commit `af835b8` đã push lên `origin/main`. Gói 1.2.14 đã đóng và kiểm tra. **Production chạy 1.2.14 từ 15:45:52.** Smoke test đạt; rollback về 1.2.13 sẵn sàng, không cần khôi phục DB |
| Link từ xa | **Một URL duy nhất: `https://log-pc.tail12f031.ts.net`**, hostname không đổi. Link đã ngừng từ 25/10, nay chạy lại; kiểm tra qua Internet 14/14 và tự kiểm tra 30/30. Đã xóa 9 file cũ của link Cloudflare; mọi thành phần cần thiết vẫn giữ |
| Model | Không đổi: `MV-20261026-105345-C73F` đang dùng, C635 vẫn chờ duyệt. Không promote, không rollback, không huấn luyện |
| Repository | 9 mục ngoài phạm vi được bảo toàn từng byte. Không force-push, không xóa công việc của người dùng |

Còn hai điểm anh/chị cần biết; không điểm nào chặn release:
1. Link chạy trong **một cửa sổ Windows Terminal đang mở trên màn hình**. **Đừng đóng cửa sổ đó**: đóng nó là cách link đã ngừng ngày 25/10. Cách sửa ở mục 4.4.
2. Màn hình giải thích vẫn bị chặn với người xem từ xa (403), đúng yêu cầu. Trang mở được nhưng báo lỗi vì không đọc được dữ liệu.

Giờ trong báo cáo là giờ Việt Nam (UTC+7). Bằng chứng nằm trong `evidence/`; đề xuất kiểm soát promote ở `PROPOSAL-PROMOTION-CONTROL.md`.

## 1. Kiểm tra ban đầu (14:55)

| Mục | Kết quả |
|---|---|
| Repository | Nhánh `main`, HEAD `af835b8b619d4235341b9c0629e16113f6fb3093` (cây `43a90627…` = cây đã kiểm thử). Upstream `origin/main` = `72d7671`. Sau `fetch`: đi trước 38, đi sau 0, không có commit mới trên remote |
| Thay đổi chưa commit | Đúng 9 mục link từ xa như báo cáo trước; stash rỗng |
| Production | 1.2.13, PID 11964. `current.txt` 1.2.13, `storage.json` `8D79DBDD…`. Model `MV-20261026-105345-C73F`, run `FCR-20261026044021-330262`. Không có job đang chạy |
| Lịch chạy | D-1 08:00 (dự phòng 08:10); D-0 mỗi 2 giờ từ 08:00 đến 18:00; training 08:20; backup cuối ngày 23:55; chốt 23:59; tất cả ON |
| Backup | Bản chính thức `backup-20261026-113756-manual.zip` (đã xác minh trước đó) còn nguyên |
| URL | Funnel bật, hostname đúng. Proxy 8766 **không chạy**, nên URL trả **502** qua relay công khai (chứng chỉ TLS hợp lệ) |

## 2. Release 1.2.14

### 2.1 Bảo toàn 9 mục ngoài phạm vi trước khi đóng gói

`release.ps1` đòi cây làm việc sạch, nên tôi cất tạm 9 mục theo các bước sau:
1. Ghi manifest: đường dẫn, loại, trạng thái Git, kích thước, SHA-256 (`evidence/remote-items-manifest.json`).
2. Tạo bản sao ZIP `checkpoints/remote-link-items-before-stash-20261026.zip`, SHA-256 `B019DF5C…4269`.
3. Chạy `git stash push --include-untracked` **chỉ cho 9 đường dẫn đó**.
4. Kiểm tra stash chứa đủ 9/9 file đúng từng byte.

Không mục nào được tham chiếu bởi gói release. Ba file đang chạy link nằm ở `%LOCALAPPDATA%\DemandForecastRemote\app`, giống hệt bản trong repo và không bị đụng tới.

### 2.2 Push

- Trước khi push, quét toàn bộ 38 commit sẽ đẩy lên (37 commit release trước đó chưa từng push + `af835b8`):
  - 254 file;
  - không có file trong thư mục dữ liệu, backup, log hay `dist`;
  - không có mẫu secret;
  - không có file nhị phân.
  - Mẫu `/data/` khớp 11 file mã nguồn `backend/app/data/*.py` và `docs/data/*.md`; các thư mục này đã có trên remote.
- `git push origin main`: `72d7671..af835b8`, fast-forward, **không force**.
- Sau push: `ls-remote` = `af835b8b…`, cây remote = `43a90627…`, đi trước / đi sau 0 / 0.

### 2.3 Đóng gói (`release.ps1`, 15:00-15:22)

| Mục | Kết quả |
|---|---|
| QA trên cây sạch | Backend 833 đạt / 19 bỏ qua / 0 lỗi; vitest 165; typecheck và build OK |
| Gói | `dist\DemandForecast-1.2.14-win64-portable.zip`, 92.467.947 byte |
| SHA-256 | `5295173F4C8957DFA786DD434DE7F8963A2313EA0864CB2BC044D775427DDB14` |
| Danh tính | VERSION 1.2.14, commit `af835b8`, `dirty=False`, source `95167625E95583D1`; runtime nhúng kiểm tra OK |
| Nội dung (7.177 mục) | Không có DB, log, credential, model, `__pycache__` hay công cụ link. Có màn hình explainer, `_deploy_staging.ps1` và giao diện `web/` (bundle `index-Dboe0o6m.js` = bản đã kiểm thử). Các file khớp mẫu chỉ là chứng chỉ gốc công khai của thư viện, CSV test của numpy/scipy và 3 mẫu Excel nhập liệu do build tạo ra |
| Dọn `dist` | Chỉ lập kế hoạch (dry run), không xóa gì |

### 2.4 Deploy

| Bước | Kết quả |
|---|---|
| Kiểm tra trước (CheckOnly, 15:25) | **PRECHECK OK**: SHA và version gói đúng, không có credential trong gói, `storage-verify` OK, app trên cổng 8765 là bản cài của tài khoản Giau Vo, không có job đang chạy, đủ dung lượng |
| Deploy thật (15:26:15-15:46:01) | `scripts\deploy-upgrade.ps1 -ConfirmToken UPGRADE-1.2.14`. Backup trực tuyến `backup-20261026-152806-manual.zip` (SHA-256 `10864BD8…5E99`). Không có migration (schema 10 → 10). Integrity ok, 0 lỗi khóa ngoại. **UPGRADE OK: 1.2.13 → 1.2.14** |
| Thời gian app ngừng | Chỉ lúc chuyển phiên bản; 1.2.14 khởi động 15:45:52 |
| Thư mục giải nén | Lần chạy thật đầu tiên của cơ chế mới: tạo ở `%TEMP%\DemandForecast-deploy\20261026-152806`, **tự xóa** sau khi kiểm tra sau nâng cấp đạt. Thư mục gốc hiện rỗng |
| Sau deploy | App PID 29408 chạy từ `Programs\DemandForecast\1.2.14`. `current.txt` 1.2.14. `storage.json` `8D79DBDD…` không đổi. 1.2.13 vẫn được cài để rollback |
| Rollback | `rollback-version.ps1 -To 1.2.13 -CheckOnly`: "rollback possible without restoring the database" |
| Log | `evidence/deploy-20261026-152806.log`, `evidence/deploy-1.2.14-console.txt` |

### 2.5 Smoke test sau deploy

| # | Kiểm tra | Kết quả |
|---|---|---|
| 1 | Production chạy 1.2.14 | `/api/health` 1.2.14; tiến trình chạy từ thư mục 1.2.14 |
| 2 | Khởi động và các route hiện có | `smoke_test.py --phase readonly`: **6/6** (health, đúng DB, integrity + khóa ngoại, lịch sử forecast vẫn 10 run, chẩn đoán, giao diện). 15 API đọc của các màn hình cũ + 18 route trang: **33/33** trả 200 |
| 3 | `/forecast-explainer` mở được | Trang trả 200; ảnh chụp và DOM từ headless Edge (`evidence/prod-explainer-page.png`) |
| 4 | SKU, FC, ngày, model, run | MEDX.DMTS-DON-SIL-001 × BD, 26/10, horizon 1, `MV-20261026-105345-C73F`, `FCR-20261026044021-330262`: cả bốn hiển thị trên trang |
| 5 | Forecast cuối khớp giá trị đã lưu | Điểm thô = LightGBM; 1859,2754 = đã lưu → **1859**; 36/36 feature, 300 cây, 9/9 kiểm tra. Mẫu ngẫu nhiên 12 chuỗi (6 BD, 6 HN) × horizon 1 / 7 / 15: **36/36 khớp**, trung bình 2,2 s mỗi lần gọi. Chuỗi dự phòng trả `NOT_LIGHTGBM` |
| 6 | Tối đa 2 chữ số thập phân, định dạng Việt Nam | 466 ô số, **0 ô** có hơn 2 chữ số thập phân |
| 7 | Forecast cuối là số nguyên | Trang hiện "1.859", có ghi chú "Khớp forecast đã lưu", không có cảnh báo lệch |
| 8 | Explainer chỉ đọc | POST / PUT / PATCH / DELETE trên cả hai endpoint, kể cả có header của app: **405** |
| 9 | Không lộ thông tin nội bộ | Phản hồi explainer không có scope key, tên BigQuery, đường dẫn hay chuỗi bí mật |
| 10 | Màn hình forecast cũ | Dashboard, kết quả, giá trị, độ chính xác, lịch sử forecast, chất lượng mô hình, snapshot: 200. "Xem cách tính" của cả run không gọi trên production vì phải dựng lại toàn bộ dữ liệu (40-70 s, tốn RAM); test backend đã phủ |
| 11 | Log | `app.log` từ lúc khởi động: 0 WARNING / ERROR. Job D-0 16:00 (lịch) **thành công** trên 1.2.14 |

Đã đối chiếu thêm: lịch chạy y hệt trước deploy; model C73F đang dùng; C635 vẫn `PROMOTION_REVIEW_REQUIRED`; vẫn 10 forecast run; audit từ 15:00 chỉ có backup của deploy.

`data-check` (chỉ đọc) sau deploy: xem mục 6.

## 3. Model

- **Đang dùng:** `MV-20261026-105345-C73F` (`TRN-20261026031942-53C73F`), run `FCR-20261026044021-330262`.
- **C635** (`TRN-20261025152426-A4C635`): vẫn `REJECTED` / `PROMOTION_REVIEW_REQUIRED`, không bị xóa. Promote C635 sẽ bị backend từ chối vì đã có model mới hơn.
- **Không:** promote, rollback, huấn luyện, tinh chỉnh, đổi lịch D-0 / D-1.
- Sự kiện `MODEL_PROMOTED` ngày 26/10 11:40 vẫn **chưa xác định được người thực hiện** vì audit không ghi actor hay request ID. Đề xuất kiểm soát nằm ở `PROPOSAL-PROMOTION-CONTROL.md` (ghi actor, timestamp, request ID, model trước/sau; bắt nhập cụm xác nhận; ẩn nút cho candidate bị thay thế; backend là chốt chặn). **Không triển khai trong 1.2.14.**

## 4. Link từ xa

### 4.1 URL duy nhất và trạng thái trước / sau

| | Trước (14:57) | Sau (16:00) |
|---|---|---|
| URL | `https://log-pc.tail12f031.ts.net` | **giữ nguyên** |
| Hostname / chứng chỉ | log-pc.tail12f031.ts.net, Let's Encrypt đến 22/01/2027 | **không đổi** |
| Cấu hình Funnel | Bật; cổng 443, `/` → `http://127.0.0.1:8766`; không có cổng hay handler nào khác | **không đổi** |
| Qua relay công khai (DoH 103.84.155.153 / .217) | **502**: proxy không chạy | **200**: app 1.2.14, `public-read-only` |
| Tác vụ `DemandForecastLink` | Ready, kết quả cuối 0xC000013A (25/10) | **Running**, một supervisor (PID 32872), proxy trên 8766 |
| Link khác | Không có: không tiến trình cloudflared hay ngrok, không credential Cloudflare, không tác vụ, dịch vụ hay mục tự khởi động nào khác | Không có |

### 4.2 Nguyên nhân link ngừng từ 25/10 và cách khôi phục

**Đã xác minh:**
- Lúc khoảng 09:57 ngày 25/10, tiến trình bọc của tác vụ (PowerShell) và supervisor **cùng kết thúc**. Không có dòng log dừng nào; tác vụ ghi 0xC000013A, mã của việc đóng cửa sổ console.
- Phiên Windows không đăng xuất.
- Cài đặt "khởi động lại 999 lần" của tác vụ chỉ áp dụng khi tác vụ không khởi động được, không áp dụng khi tiến trình tự kết thúc.
- Trên máy này, Windows Terminal là console mặc định ("Let Windows decide", build 26200), nên cửa sổ `-WindowStyle Hidden` vẫn **hiện ra**. Hôm nay sau khi khởi động lại, đã thấy đúng cửa sổ đó: Windows Terminal PID 34164, chứa tiến trình PowerShell 20240 của tác vụ.

**Chưa xác minh:** ai hoặc cái gì đã đóng cửa sổ ngày 25/10.

**Khôi phục:** chạy `remote-access.ps1 start`, đúng thao tác của shortcut "Link xem tu xa - bat lai", sau khi deploy xong. Thao tác này chỉ khởi động lại tác vụ có sẵn: **không đổi cấu hình, hostname hay quyền truy cập**.

Lưu ý: lệnh `start` in "ONLINE" ngay, nhưng đó là đọc từ file trạng thái cũ (25/10). Tôi chỉ ghi nhận thành công khi đã thấy trạng thái mới (**15:58:25**) và tự kiểm tra qua Internet.

### 4.3 Kiểm tra link sau khi dọn

| # | Kiểm tra | Kết quả |
|---|---|---|
| 1-2 | URL, HTTPS, hostname | Kiểm tra của tôi qua relay công khai (phân giải bằng DNS-over-HTTPS, TLS kiểm tra theo hostname): `/__remote/health` 200, chứng chỉ Let's Encrypt cho `log-pc.tail12f031.ts.net`, app **1.2.14** |
| 3-4 | Chỉ đọc; yêu cầu ghi bị từ chối | POST `/api/training/run`, promote, backups; DELETE; PUT settings: **405**. `/api/system/paths`, `/api/audit`, `/api/sql-sources`: **403** |
| — | Explainer từ xa | `/api/forecast-explainer` và `/trees`: **403**, giữ nguyên, không thêm vào allowlist |
| 5 | Không lộ thông tin | Không có tên BigQuery hay đường dẫn trong các trả lời dữ liệu |
| 6 | Không chạy trùng | Đúng một supervisor (khóa đơn tiến trình), một listener 8766, 0 cloudflared |
| 7 | Tác vụ và tự phục hồi | Tác vụ Running (khi đăng nhập, IgnoreNew, khởi động lại 999 × 1 phút). Supervisor tự bật lại Funnel / proxy khi rớt (đã thử thật ngày 25/10: Funnel 28 s, supervisor 15 s). **Không thử lại hôm nay** vì phải tắt Funnel và làm gián đoạn người xem |
| 8 | Hostname | Không đổi |
| 9-10 | Tính liên tục | URL **không** hoạt động trước khi dọn (đã ghi nhận 502). Sau khi khôi phục và dọn, URL hoạt động. Tự kiểm tra của công cụ (`remote-access.ps1 selftest`): **30/30 PASS** |

Tổng hợp: kiểm tra của tôi 14/14 (`evidence/public-url-check-after.json`); tự kiểm tra của công cụ 30/30 (`evidence/link-selftest-20261026-160324.json`).

### 4.4 Phân loại thành phần

**Nhóm 1: bắt buộc giữ (giữ nguyên)**
- **Tailscale:** dịch vụ, node `log-pc`, cấu hình serve / Funnel (443 → 127.0.0.1:8766).
- **`%LOCALAPPDATA%\DemandForecastRemote`:**
  - `app\` (`readonly_proxy.py` 2.1.0, `link_supervisor.py`, `remote-access.ps1`, `MANIFEST.txt`);
  - `runtime\` (Python riêng);
  - `config\link.json` (funnel / public / hostname / cổng) và `config\security-ack.json`;
  - `run\link-status.json`;
  - log hiện tại: `link-supervisor.log`, `link-task.log`, `proxy-access.log`, `selftest-*.json`, và `cloudflared-link.log`, file rỗng mà supervisor tạo lại mỗi lần chạy.
- **Tác vụ `DemandForecastLink`** và 4 shortcut trong Start Menu "Demand Forecasting Link" (bật lại, tạm dừng, cài đặt lại, thông tin).
- **`bin\tailscale-setup-1.104.2-amd64.msi` + `.json`:** bộ cài đã xác minh chữ ký, dùng để khôi phục; tài khoản Giau Vo không có quyền admin.
- **Trong repo, 9 mục chưa commit:**
  - mã nguồn của bản đã cài (giống từng byte);
  - 3 file `.bat` gọi `start` / `stop` / `setup` của cùng công cụ;
  - `REMOTE_ACCESS_GUIDE.md` (đã mô tả Tailscale / Funnel);
  - `test_remote_link.py` (46 test);
  - 2 mục CHANGELOG.

**Nhóm 2: đã xóa (9 file, 7.943.076 byte).** Có kế hoạch dry run trước (`evidence/link-cleanup-plan.json`). Mỗi file được kiểm tra lại ngay trước khi xóa: tồn tại, SHA-256 khớp kế hoạch, không đang mở, tên không xuất hiện trong mã đang cài. Kết quả: `evidence/link-cleanup-result.json`.
- `run\proxy.json`: trạng thái của trình chạy proxy cũ (19/10, PID 16144 không còn).
- `run\tunnel.json`: trạng thái của **link Cloudflare ngẫu nhiên cũ** (`*.trycloudflare.com`, 19/10, PID 35236 không còn).
- `logs\cloudflared-20261017-160830.log`, `-161118.log`, `-165443.log`, `-20261019-103639.log`, `-20261019-195357.log`: log của link Cloudflare cũ.
- `logs\proxy.err.log`, `logs\proxy.out.log`: log của trình chạy proxy cũ.
- **Khôi phục:** `checkpoints/remote-link-cleanup-restore-20261026.zip`, SHA-256 `BD47006D398526D46DD9E3D100854B67F29E4E00BFDE22B97FE01C24E9B16E16`.

**Nhóm 3: chưa xóa, có lý do**
- **`bin\cloudflared.exe` (55 MB) + `cloudflared.json`.** Link Funnel không dùng file này (supervisor chỉ cần nó khi mode ≠ funnel). Nhưng thao tác cài đặt lại (`install` / `setup`) luôn gọi `Get-Cloudflared`: nếu file bị xóa, lần cài lại sẽ tải về lại, hoặc thất bại khi không có Internet. Muốn bỏ hẳn cần sửa script (đề xuất 4.5).
- **Phần mã Cloudflare** trong `remote-access.ps1` và `link_supervisor.py` (các mode named / token / quick): là mã, không phải file riêng; xóa cần thay đổi mã.

### 4.5 Đề xuất cho link (chưa làm)

1. **Chạy tác vụ không có cửa sổ**, để việc lỡ đóng cửa sổ không làm mất link. Ví dụ: action
   `conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File …\remote-access.ps1 run`.
   Phải sửa cả `Register-LinkTask` trong `remote-access.ps1`, nếu không lần cài lại sẽ đưa về như cũ, và thêm test. Trong lúc chờ: **đừng đóng cửa sổ Windows Terminal "powershell.exe" của link**.
2. **Lệnh `start` / `selftest` chỉ coi là ONLINE khi trạng thái có thời điểm mới hơn lúc bắt đầu**, không đọc file trạng thái cũ.
3. **`install` / `setup` bỏ qua cloudflared khi mode là funnel.** Sau đó mới xóa `bin\cloudflared.exe`.
4. Tùy chọn: nếu muốn người xem từ xa dùng màn hình giải thích, cần một phê duyệt riêng để thêm vào allowlist; hoặc ẩn menu đó ở chế độ xem từ xa để không hiện lỗi 403.

## 5. Repository

- **`git status` cuối:**
  - đúng 9 mục link từ xa như trước batch (giống từng byte với manifest);
  - `docs/CHECKPOINT.md` (thêm mục của batch này, chưa commit).
- **HEAD = `origin/main` = `af835b8`.** Stash rỗng: đã drop sau khi kiểm tra khôi phục 9/9.
- **Không** force-push, rebase, reset, clean, hay xóa thay đổi nào của người dùng.
- **Không tạo commit mới** trong batch này.
- **Bản sao an toàn:**
  - `checkpoints/remote-link-items-before-stash-20261026.zip`, SHA-256 `B019DF5C2B98EE271583A1BB8B98B6E6C05418855CE12AEFACCD7C15B6AA4269`;
  - `checkpoints/worktree-before-commit-1.2.14-20261026.zip`, SHA-256 `7F1EEA1E…8D5A`.

## 6. data-check sau deploy

`app.cli data-check` bằng runtime 1.2.14 đã cài, lúc 16:09 (`evidence/production-data-check-after-deploy.txt`).

- **34 OK / 3 WARN / 0 FAIL.** Ba WARN là các cảnh báo đã biết, giống hệt trước deploy: `forecast_series_meta` 1, `finalized_days_changed` 228, `history_source_drift` 291.
- **Số dòng giống trước deploy:** `demand_daily` 1.414.512, `forecast_runs` 10, `forecast_values` 1.547.868, `demand_change_log` 1.374.849.
- Chỉ `d0_snapshots` tăng từ 65 lên 68: ba lần chụp D-0 theo lịch lúc 12:00, 14:00 và 16:00.

## 7. Còn cần anh/chị quyết định

1. **Sửa tác vụ link chạy không cửa sổ** (4.5.1). Cho tới lúc đó, đừng đóng cửa sổ Windows Terminal của link.
2. **Commit công cụ link từ xa** (9 mục) thành một commit riêng, hoặc tiếp tục giữ ngoài Git. Lần release sau sẽ lại cần cất tạm như lần này.
3. **Đề xuất kiểm soát promote** (`PROPOSAL-PROMOTION-CONTROL.md`), dự kiến cho 1.2.15.
4. **Mở màn hình giải thích cho người xem từ xa:** cần phê duyệt riêng.
5. **Bỏ hẳn cloudflared** (4.5.3).

## Bằng chứng (`evidence/`)

- **Release:**
  - `release-1.2.14.log`, `deploy-1.2.14-console.txt`, `deploy-20261026-152806.log`;
  - `prod-explainer-smoke.json`, `prod-explainer-dom-check.json`, `prod-explainer-page.png`;
  - `prod-pages-smoke.json`, `production-data-check-after-deploy.txt`.
- **Bảo toàn:** `remote-items-manifest.json`.
- **Link:**
  - `public-url-before.json`, `public-url-check-after.json`, `link-selftest-20261026-160324.json`;
  - `link-cleanup-plan.json`, `link-cleanup-result.json`.
- **Script:** `script-*.py`.
