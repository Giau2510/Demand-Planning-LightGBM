# Điều tra MODEL_PROMOTED và chuẩn bị release 1.2.14 (26/10/2026, 14:00-14:50)

## Trạng thái: `READY_FOR_RELEASE_REVIEW`

| Giai đoạn | Kết quả |
|---|---|
| 1. Điều tra `MODEL_PROMOTED` | Đã xác định đủ thời điểm, model trước/sau, run nguồn và đường gọi. **Người thực hiện không được ghi lại**: ứng dụng không lưu người dùng, client hay request ID. Không có cơ chế tự động nào; không phải agent; không đi qua link từ xa |
| 2. Rà soát mã nguồn | 22 file trong phạm vi được commit. 9 mục của công cụ link từ xa nằm ngoài phạm vi: để nguyên, không commit, đã xác minh còn nguyên từng byte |
| 3. Kiểm thử trên đúng nội dung commit | Backend 833 đạt / 19 bỏ qua / 0 lỗi; frontend 165 đạt; typecheck, build OK; dữ liệu thật 36/36 khớp |
| 4. Commit local | **`af835b8b619d4235341b9c0629e16113f6fb3093`**. Cây đã kiểm thử = cây đã commit (`43a90627…`) |
| 5. Giới hạn | Không push, không đóng gói, không deploy, không rollback, không promote, không đổi lịch, không đụng link công khai |

Giờ trong báo cáo là giờ Việt Nam (UTC+7); bằng chứng gốc ghi theo UTC (`Z`).

## 1. Sự kiện `MODEL_PROMOTED`

### 1.1 Đã xác minh

| # | Câu hỏi | Kết quả | Bằng chứng (`evidence/`) |
|---|---|---|---|
| 1 | Thời điểm | Quyết định ghi `promoted_at` **11:40:21**. Run forecast tạo lúc 11:40:27. Audit `MODEL_PROMOTED` (id 607) lúc **11:40:31**. Log ghi "candidate promoted" lúc 11:40:34. Lúc bắt đầu request không được ghi; việc tính forecast trước đó mất vài phút | `audit-20261026.json`, `training-runs-promotion.json`, `app-log-0945-1149-vn.txt` |
| 2 | Model trước / sau | **Trước:** `TRN-20261024090507-1EEA7D` / `MV-20261024-163642-EA7D` / `FCR-20261024163842-4EEFD8` (chính model này được promote qua ứng dụng 24/10 23:38). **Sau:** `TRN-20261026031942-53C73F` / `MV-20261026-105345-C73F` / `FCR-20261026044021-330262` (257.250 giá trị, 17.150 chuỗi, trong đó 4.256 chuỗi LightGBM) | `forecast-runs-latest.json`, audit 606-608 |
| 3 | Run nguồn | Job huấn luyện `JOB-20261026031846-CE1653`, trigger **MANUAL**, 10:18:46-10:53:46, dữ liệu 01/01-25/10. Kết luận so sánh `EQUAL`: cùng WAPE 0,7896 với model đang dùng trên cùng 8 fold (baseline 0,8180). Được giữ chờ duyệt (`PROMOTION_REVIEW_REQUIRED`); trạng thái dùng `USABLE_WITH_WARNING` (WAPE_MAX) | `jobs-20261026.json`, `training-runs-promotion.json` |
| 4 | Actor, request ID, process, endpoint | **Endpoint:** `POST /api/training-runs/{id}/promote` với `confirm=true`, là đường duy nhất. Dấu hiệu: `job_id` rỗng, `derived_from` rỗng, audit là `MODEL_PROMOTED` (không phải `MODEL_RELEASED_WITH_GATE_EXCEPTION`). **Actor, request ID, client: không được ghi lại.** `audit_log` không có cột người thực hiện, chi tiết audit không có người dùng, ứng dụng không ghi log truy cập HTTP | code; `audit-20261026.json` |
| 4b | Nguồn request (loại trừ) | Request đến từ một client **trên chính máy này**: ứng dụng chỉ nhận Host 127.0.0.1/localhost và header `X-DF-Client: web` (`backend/app/security.py`). Request **không đi qua link từ xa**: proxy chỉ chuyển GET/HEAD, các method khác trả 405, và proxy không chạy. Request **không phải do agent**: log phiên Claude Code từ 09:45 đến 11:41 chỉ có một lệnh POST là backup lúc 11:37:54, không có lệnh promote; không có log Codex. Phiên Windows duy nhất là `giau vo` (console, đăng nhập từ 24/10 20:39) | `agent-logs-*.txt` |
| 5 | Đường gọi trong mã nguồn | Trang *Chất lượng mô hình* (`Performance.tsx:67-73`): nút "Dùng model này (publish forecast mới)", hoặc "(dưới ngưỡng — kèm cảnh báo)" với model dưới ngưỡng → hộp `window.confirm` → `POST …/promote {confirm:true}` → `forecast_routes.promote_training_run` → `pipeline.promote_candidate`. Hàm này kiểm tra `promotable`, không có run ACCEPTED mới hơn, không có job TRAIN/EXTEND đang chạy, fingerprint dữ liệu và SHA của model, rồi tính forecast và ghi trong một giao dịch: trạng thái ACCEPTED + publish + audit | `pipeline.py:701-809` |
| 6 | Logic tự động | **Không có.** `promote_candidate` chỉ được route trên gọi. Scheduler, jobs và runner không gọi nó; không có setting tự promote. Tác vụ Windows duy nhất của app là `DemandForecastLink` (chỉ GET). Script diễn tập `iso1213r.ps1` chỉ promote trên cổng cách ly 8879 | grep code, tác vụ Windows |
| 7 | Liên hệ với C635 | **Không.** C635 (`TRN-20261025152426-A4C635`, huấn luyện 25/10 22:24-22:57) vẫn `REJECTED` / `PROMOTION_REVIEW_REQUIRED`, chưa có forecast run. C635 và C73F đều là candidate so với model EA7D | `training-runs-promotion.json` |
| 8 | Production hiện tại | Run đang dùng `FCR-20261026044021-330262`, model `MV-20261026-105345-C73F` (`in_use: true`). Từ 11:40 không có promote, training hay publish nào khác; audit chỉ có D-0 lúc 12:00 và 14:00. App 1.2.13, PID 11964 | `audit-20261026.json` |

### 1.2 Giả thuyết chưa xác minh

**Khả năng cao nhất:** có người dùng ứng dụng trong trình duyệt trên máy này đã bấm "Dùng model này" cho candidate 10:18, rồi xác nhận hộp thoại.
- **Ủng hộ:**
  - cùng buổi sáng, một client cục bộ (không phải agent) đã chạy D-1 thủ công lúc 09:58 và training thủ công lúc 10:18;
  - nút này là đường duy nhất trên giao diện;
  - phiên Windows tương tác duy nhất là của chủ máy.
- **Chưa chứng minh được** ai bấm và bấm từ đâu: ứng dụng không ghi lại.

**Khả năng khác:** một script hoặc công cụ cục bộ tự gửi header. Không tìm thấy dấu vết trong `scripts/`, các script trong `reports/`, tác vụ Windows hay log agent.

Tôi không suy luận danh tính người thực hiện.

### 1.3 Không còn lưu hoặc không truy xuất được

- Danh tính người thực hiện, client, user agent, request ID, thời điểm bắt đầu request: ứng dụng chưa bao giờ ghi.
- Lịch sử đăng nhập Windows trong Security log: cần quyền admin, chưa kiểm tra.
- Lịch sử trình duyệt trên máy: không đọc vì là dữ liệu cá nhân. Anh/chị có thể tự xem nếu cần.

### 1.4 Đề xuất ngăn tái diễn (chưa áp dụng, cần phê duyệt)

1. **Ghi người và kênh thực hiện:** địa chỉ client, user agent, tài khoản Windows của app và một request ID vào audit `MODEL_PROMOTED` (và các thao tác ghi khác). Ghi một dòng log cho mỗi POST.
2. **Xác nhận bằng chữ khi promote**, ví dụ gõ `PROMOTE-<model_version>` kèm người duyệt và lý do, giống quy trình gate exception. Đây là quyết định nghiệp vụ.
3. **Sửa `promotable()`:** trả `SUPERSEDED` khi đã có run ACCEPTED mới hơn, và `DATA_CHANGED` khi fingerprint dữ liệu đã khác. Khi đó nút promote không còn hiện cho những candidate chắc chắn bị từ chối, như C635 lúc này.
4. Tùy chọn: thông báo mỗi khi có promote.

Đúng yêu cầu: không rollback, không đổi model.

## 2. Model production hiện hành và Candidate C635

| | Training run | Model | Trạng thái | WAPE (fold của chính run) | Ghi chú |
|---|---|---|---|---|---|
| **Đang dùng** | `TRN-20261026031942-53C73F` | `MV-20261026-105345-C73F` | ACCEPTED, `in_use` | 0,7896 (baseline 0,8180) | run `FCR-20261026044021-330262` |
| Trước đó | `TRN-20261024090507-1EEA7D` | `MV-20261024-163642-EA7D` | ACCEPTED | 0,7907 | run `FCR-20261024163842-4EEFD8`, vẫn được giữ |
| C635 | `TRN-20261025152426-A4C635` | `MV-20261025-225737-C635` | REJECTED, `PROMOTION_REVIEW_REQUIRED` | 0,7849 (fold đến 24/10, không so trực tiếp được) | không có forecast run |

**C635 hiện không thể promote.** API vẫn trả `can_promote: true`, nên giao diện vẫn hiện nút. Nhưng `promote_candidate` sẽ từ chối với 409 `PROMOTION_NOT_ALLOWED: superseded by TRN-20261026031942-53C73F`, vì C73F là run ACCEPTED mới hơn. Fingerprint dữ liệu của C635 cũng đã cũ.

Tôi không thử bấm promote để chứng minh. Kết luận này đọc từ mã (`pipeline.py:740-743`).

## 3. Rà soát mã nguồn trước commit

**Đã commit: 22 file.**

| Nhóm | File |
|---|---|
| Màn hình giải thích (backend) | `backend/app/ml/forecast_explainer.py` (mới), `backend/app/api/explainer_routes.py` (mới), `backend/app/main.py` (+router) |
| Màn hình giải thích (frontend) | `frontend/src/explainer.ts` (mới, định dạng số tối đa 2 chữ số thập phân, số nguyên), `frontend/src/pages/ForecastExplainer.tsx` (mới), `frontend/src/App.tsx` (menu + route), `frontend/src/i18n.tsx` |
| Dọn thư mục staging | `scripts/_deploy_staging.ps1` (mới), `scripts/deploy-upgrade.ps1`, `scripts/build-package.ps1` (thêm helper vào gói) |
| Test | `backend/tests/test_v1214_forecast_explainer.py` (12), `backend/tests/test_v1214_deploy_staging.py` (24), `backend/tests/test_v1213_deploy_preflight.py` (15), `frontend/src/v1214.test.tsx` (6), `frontend/src/v125.test.tsx` (danh sách route) |
| Phiên bản 1.2.14 | `backend/app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json` (chỉ dòng version) |
| Tài liệu | `CHANGELOG.md` (chỉ mục 1.2.14), `docs/MO-HINH-VA-CHI-SO.md`, `docs/VAN-HANH.md`, `docs/CHECKPOINT.md` |

**Một phần ngoài phạm vi màn hình nhưng vẫn commit: bản sửa preflight và xác nhận của `deploy-upgrade.ps1` (22-23/10).**
- Bản sửa nằm cùng file với phần staging.
- Nó đã chạy từ repo trong lần deploy 1.2.13 ngày 23/10.
- Test staging dùng lại harness `test_v1213_deploy_preflight.py`.
- Nguồn gốc ghi ở `reports/release-1.2.13-20261022/FINAL_REPORT.md`; CHANGELOG có mục con riêng cho nó trong 1.2.14.

**Ngoài phạm vi, để nguyên, không commit (9 mục): công cụ link từ xa của các lô 24-25/10** (`reports/remote-link-20261024/`).
- Các file:
  - `REMOTE_ACCESS_GUIDE.md`, `Start-DemandForecast-Remote.bat`, `Stop-DemandForecast-Remote.bat`, `Setup-DemandForecast-Link.bat`;
  - `scripts/remote/readonly_proxy.py`, `scripts/remote/remote-access.ps1`, `scripts/remote/link_supervisor.py`;
  - `backend/tests/test_remote_link.py` (46 test);
  - hai mục "Unreleased" về link từ xa trong `CHANGELOG.md`.
- Sau commit, cả 8 file giống từng byte với bản sao trước commit. CHANGELOG chỉ còn khác commit đúng hai mục đó (+74 dòng, 0 dòng bị xóa).
- Bản sao an toàn trước khi sửa bất cứ gì: `checkpoints/worktree-before-commit-1.2.14-20261026.zip`, SHA-256
  `7F1EEA1E9BCA4FA6E74A1AA7459CB1601FC5D9D2E02672A8CA3B0DB9FB488D5A` (27 file chưa commit + diff).

**Kiểm tra đặc biệt:**

| # | Kiểm tra | Kết quả |
|---|---|---|
| 1 | Dữ liệu cá nhân, credentials, token, file tạm | Quét đường dẫn cấm và mẫu secret của `docs/GITHUB_WORKFLOW.md` mục 5 trên phần đã stage: 0 kết quả. Không có tên project / bảng BigQuery hay đường dẫn máy trong phần thêm mới. Có tên tài khoản Windows "Giau Vo" trong `CHECKPOINT.md`, như các commit trước |
| 2 | DB, backup ZIP, model, báo cáo | Không có; file lớn nhất là `i18n.tsx` 162 KB |
| 3 | File generated hoặc build | Không có (`dist/`, `__pycache__/`, `node_modules/` bị bỏ qua) |
| 4 | Logic forecast production | Không đổi (`model.py`, `pipeline.py`, `features.py`, `qty.py` không có trong commit); explainer chỉ đọc |
| 5 | Proxy công khai / Tailscale | Không đổi: file proxy không có trong commit; bản đã cài 2.1.0 vẫn chặn explainer (GET → 403, POST → 405) |
| 6 | Schema, migration, cấu hình ứng dụng | Không có migration, settings hay `storage.json`; schema vẫn 10 |
| 7 | Thay đổi chưa commit của người dùng | Không ghi đè: CHANGELOG được stage bằng một bản riêng, file trên đĩa giữ nguyên hai mục link từ xa. Không dùng `reset` / `checkout` / `stash` |
| — | PowerShell ASCII | `_deploy_staging.ps1`, `deploy-upgrade.ps1`, `build-package.ps1`: 0 byte ngoài ASCII |

## 4. Kết quả kiểm thử

Kiểm thử chạy trên **đúng nội dung commit**: một git worktree riêng = HEAD + phần đã stage, không có thay đổi ngoài phạm vi. Hash cây của worktree = hash cây của commit (`43a90627c0bb90b49abcb0d4f560043eb1f50fc6`).

| Bộ | Loại | Kết quả |
|---|---|---|
| Backend toàn bộ (`pytest -q -p no:cacheprovider`, 14:20-14:34) | unit + integration với fake | **833 passed / 19 skipped / 0 failed** (`evidence/backend-tests-commit-tree.log`) |
| Trong đó, explainer | integration: model LightGBM DIRECT thật trên dữ liệu tổng hợp | 12 / 12 |
| Trong đó, staging | PowerShell thật, bản cài giả cách ly | 24 / 24 |
| Trong đó, preflight / xác nhận deploy | như trên | 15 / 15 |
| Frontend `npm test` | unit, backend được mock | **165 / 165** (27 file) |
| `npm run typecheck`, `npm run build` | | OK, OK |
| Lint | | chưa cấu hình |
| Đối chiếu với LightGBM thật (14:35-14:38) | instance cách ly chạy mã commit (1.2.14) trên bản sao chỉ đọc của DB sống (backup API, `mode=ro`, `quick_check ok`) | Xem bên dưới |

**Kết quả đối chiếu trên dữ liệu thật:**
- **Run đang dùng** C73F, MEDX.DMTS-DON-SIL-001 × BD, 26/10, horizon 1:
  - điểm thô 7,527942146475376 = LightGBM;
  - dự đoán 1859,2754475280374 = LightGBM;
  - lưu 1859,2754 = giá trị đã lưu → **1859**;
  - 36/36 feature, 300 cây, 9/9 kiểm tra.
- **Mẫu ngẫu nhiên** 12 chuỗi (6 BD, 6 HN) × horizon 1 / 7 / 15: **36/36 khớp**, giá trị từ 0,30 đến 71,10, trung bình 1,5 s mỗi lần gọi.
- Chuỗi dự phòng trả `NOT_LIGHTGBM`.
- Bằng chứng: `explainer-commit-code-*.json`.

**Kiểm tra chỉ đọc và không lộ thông tin:**
- POST / PUT / PATCH / DELETE trên cả hai endpoint, kể cả có header `X-DF-Client: web`: **405**.
- Không có chuỗi nội bộ trong phản hồi: scope key, tên BigQuery, đường dẫn, tên file model, token.
- Proxy đã cài: GET → 403 ở cả hai chế độ; POST → 405.

Toàn bộ suite trên cây làm việc trước đó (13:15) là 879 đạt; chênh 46 test so với 833 chính là `test_remote_link.py`, không có trong commit.

## 5. File đã commit

22 file liệt kê ở mục 3 (`git show --stat af835b8`: 22 file, +2935 / −19).

## 6. Commit

`af835b8b619d4235341b9c0629e16113f6fb3093`
- Message: "Release 1.2.14: LightGBM forecast explainer screen, managed deploy staging cleanup, deploy preflight and confirmation".
- Commit trên nhánh `main`, cha là `e682cf3`; nhánh đi trước `origin/main` 38 commit, **chưa push**.
- Chi tiết: `evidence/commit-af835b8.txt`.

## 7. Xác nhận

- **Không push** Git.
- **Không đóng gói, không deploy, không rollback.** Production vẫn 1.2.13, PID 11964.
- **Không promote** model nào và **không đổi** model đang dùng hay C635.
- **Không đổi** lịch D-0 / D-1 / training, settings, feature, SQL nguồn hay schema.
- **Không đụng** link công khai hay Tailscale.
- **Không sửa DB hay audit log.** Với production, phiên này chỉ đọc (GET) và tạo bản sao bằng backup API.
- **Dọn file tạm của chính phiên:** worktree kiểm thử (đã gỡ junction `node_modules` trước, `node_modules` thật còn nguyên) và bản sao DB 2,85 GB.

## 8. Rủi ro và quyết định còn cần phê duyệt

1. **Công cụ link từ xa chưa commit (9 mục).** `release.ps1` đòi cây làm việc sạch nên sẽ từ chối đóng gói 1.2.14 khi các mục này còn. Cần anh/chị chọn: commit chúng thành một commit riêng (không vào gói), hoặc cất tạm trước khi đóng gói.
2. **Push** commit `af835b8` và 37 commit trước đó: chờ anh/chị duyệt.
3. **Đóng gói và deploy 1.2.14:** chạy `release.ps1`, sau đó `deploy-upgrade.ps1 -CheckOnly`, rồi deploy ngoài khung giờ lịch chạy. Deploy là quyết định của anh/chị.
4. **Kiểm soát promote:** các đề xuất ở mục 1.4 (ghi người thực hiện, xác nhận bằng chữ, ẩn nút cho candidate đã bị thay thế) cần duyệt trước khi làm.
5. **C635:** giữ làm hồ sơ hay đánh dấu bỏ. Nút promote vẫn hiện nhưng sẽ bị từ chối.
6. **Model đang dùng C73F** được ghi trạng thái "dùng được, có cảnh báo" (WAPE_MAX). Kết quả bằng model trước trên cùng fold; giữ hay đổi là quyết định của anh/chị.
7. **Link công khai:** đã ngừng từ 25/10. Proxy chặn trang explainer; mở cho người xem từ xa cần anh/chị cho phép.

## Bằng chứng (`evidence/`)

**Điều tra promote:**
- `audit-20261026.json`, `jobs-20261026.json`, `forecast-runs-latest.json`, `training-runs-promotion.json`, `app-log-0945-1149-vn.txt` (scope BigQuery đã che);
- `agent-logs-promote-calls.txt`, `agent-logs-app-calls-0945-1141-vn.txt`.

**Kiểm thử và commit:**
- `backend-tests-commit-tree.log`, `explainer-commit-code-readonly-checks.json`, `explainer-commit-code-sample-match.json`;
- `commit-af835b8.txt`, `git-status-after-commit.txt`;
- các script `script-*.py` dùng để tạo bằng chứng.
