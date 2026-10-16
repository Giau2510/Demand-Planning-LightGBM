# Quy trình Git / GitHub — Demand Forecasting

## 1. Repository

| Mục | Giá trị |
|---|---|
| URL | `https://github.com/Giau2510/Demand-Planning-LightGBM` (clone: `https://github.com/Giau2510/Demand-Planning-LightGBM.git`) |
| Chế độ | **Private** — chỉ người được mời mới xem được |
| Nhánh chính | `main` |
| Thư mục làm việc trên máy hiện tại | `D:\Buymed\Lightgbm AI` |
| CI / tự động triển khai | **không có** — không có workflow GitHub Actions, không có hook tự push, không tự cài lên máy |

Repository chỉ chứa **mã nguồn và tài liệu** để xây dựng lại ứng dụng. Dữ liệu, model, cấu hình chạy thật, backup và gói
phát hành luôn nằm ngoài Git.

### Được quản lý trong Git

| Đường dẫn | Nội dung |
|---|---|
| `backend/app/`, `backend/tests/`, `backend/requirements*.txt` | backend FastAPI, migration SQL, test |
| `frontend/src/`, `frontend/index.html`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts` | giao diện React/TypeScript |
| `scripts/` | cài đặt, nâng cấp, quay về, backup, build gói, test |
| `docs/`, `README.md`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md`, `.claude/` | tài liệu, quy tắc kỹ thuật |
| `config/app.env.example` | mẫu cấu hình môi trường (không có secret) |
| `.gitignore`, `.gitattributes` | quy tắc loại trừ; giữ nguyên ký tự xuống dòng của từng file (`* -text`) |

### Không bao giờ commit

| Loại | Ví dụ / quy tắc trong `.gitignore` |
|---|---|
| Dữ liệu chạy thật | `data/` (database `app.db`, `-wal`, `-shm`, model, upload), `*.db`, `*.sqlite*` |
| Backup, checkpoint, log | `backups/`, `checkpoints/`, `logs/`, `*.log` |
| Báo cáo runtime | `reports/` (thư mục báo cáo của ứng dụng, chứa thông tin riêng của máy) |
| Gói phát hành, build | `dist/`, `release/`, `*.zip`, `*.sha256`, `frontend/dist/`, `node_modules/`, `.venv/`, `__pycache__/` |
| Dữ liệu nghiệp vụ | `*.xlsx`, `*.xls`, `*.csv`, `templates/` (mẫu Excel được `scripts/build-package.ps1` sinh lại khi build) |
| Thông tin xác thực | `.env*`, `client_secret*.json`, `service-account*.json`, `application_default_credentials.json`, `*.key`, `*.pem`, `*.p12`, `*.pfx` |
| Cấu hình riêng của máy | `%LOCALAPPDATA%\DemandForecast\storage.json`, `app.env` thật — nằm ngoài thư mục dự án |

OAuth client secret và refresh token chỉ nằm trong Windows Credential Manager (xem `docs/BIGQUERY.md`); không bao giờ
đưa vào mã, test, tài liệu hay commit.

## 2. Mỗi lần cập nhật mã nguồn

Mở PowerShell tại `D:\Buymed\Lightgbm AI`.

```powershell
git status                      # 1. những gì đã đổi; không được có data/, backups/, *.db, *.xlsx, .env...
git diff                        # 2. đọc lại thay đổi chưa stage
```

3. Chạy test phù hợp (AGENTS.md mục 6):

```powershell
cd backend;  ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider; cd ..
cd frontend; npm test; npm run typecheck; npm run build; cd ..
# hoặc cả hai, có log:
powershell -ExecutionPolicy Bypass -File scripts\run-tests.ps1
```

4. Stage **từng đường dẫn có chủ đích**, không `git add .` khi chưa xem `git status`:

```powershell
git add backend/app/... frontend/src/... docs/...
git status                      # kiểm tra lại danh sách đã stage
git diff --cached --stat        # tổng quan
git diff --cached               # đọc lại toàn bộ
```

5. Kiểm tra secrets và file cấm trong phần đã stage (phải không ra kết quả nào; nếu có, bỏ stage và xử lý trước):

```powershell
git diff --cached --name-only | Select-String -Pattern '(^|/)(data|backups|checkpoints|logs|reports|dist|release)/|\.(db|sqlite3?|xlsx|xls|csv|zip|pem|key|p12|pfx)$|(^|/)\.env|client_secret|service-account|application_default_credentials'
git diff --cached -U0 | Select-String -Pattern 'ghp_[A-Za-z0-9]{20,}|github_pat_|gho_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|GOCSPX-|ya29\.[0-9A-Za-z_-]+|1//0[0-9A-Za-z_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|"type":\s*"service_account"|xox[abpr]-'
```

6. Commit với mô tả rõ ràng, rồi push lên đúng repository:

```powershell
git commit -m "Mo ta ngan gon thay doi"
git push                        # nhánh main -> origin/main
```

Không dùng `git push --force` / `--force-with-lease`, không viết lại lịch sử đã push. Không push thay đổi chưa được
người phụ trách xem xét.

## 3. Đồng bộ và làm việc trên máy khác

Trước khi bắt đầu sửa:

```powershell
git pull --ff-only              # lấy thay đổi mới từ GitHub; chỉ tua tới, không tạo merge ngầm
```

Máy mới (cần quyền truy cập repository private). Cần cài sẵn: Git, Python **3.14** (lệnh `py -3.14` phải chạy được),
Node.js ≥ 18 (đã kiểm với Node 24 / npm 11), kết nối Internet (pip, npm; `build-package.ps1` còn tải Python embedded từ
python.org). npm 11 có thể cảnh báo `allow-scripts` cho `esbuild` — build vẫn chạy (đã kiểm 16/10/2026).

```powershell
git clone https://github.com/Giau2510/Demand-Planning-LightGBM.git "D:\Buymed\Lightgbm AI"
cd "D:\Buymed\Lightgbm AI"
git config user.name  "<Tên>"
git config user.email "<email đã xác nhận>"
powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1   # tạo .venv, cài node_modules
```

Clone chỉ có mã nguồn: không có database, model hay backup. Dữ liệu của máy chạy thật không được chép qua Git.
`frontend\dist` (giao diện đã build) và `templates\` (mẫu Excel) không nằm trong Git: `setup-dev.ps1` build giao diện,
`build-package.ps1` sinh lại mẫu Excel. Chạy ứng dụng từ mã nguồn khi chưa build giao diện chỉ thấy thông báo JSON.

## 4. Xử lý xung đột (cơ bản)

Khi `git pull --ff-only` báo lịch sử đã tách nhánh:

```powershell
git fetch origin
git merge origin/main           # Git đánh dấu file xung đột bằng <<<<<<< ======= >>>>>>>
git status                      # liệt kê file xung đột
# sửa từng file, giữ đúng nội dung cần thiết, xóa các dấu xung đột
git add <file đã sửa>
# chạy lại test (mục 2), rồi:
git commit                      # hoàn tất merge
git push
```

Muốn hủy merge đang dở: `git merge --abort`. Khi không chắc, dừng lại và hỏi người phụ trách; không xóa commit của người
khác, không force-push.

## 5. Xem và khôi phục phiên bản mã cũ

```powershell
git log --oneline -20                       # lịch sử
git show <commit>                           # nội dung một commit
git diff <commit> -- backend/app/sync.py    # so một file với bản cũ
git restore --source <commit> -- <file>     # lấy lại một file như ở <commit> (sau đó commit như thường)
git revert <commit>                         # tạo commit mới đảo ngược <commit> (an toàn với lịch sử đã push)
```

Gợi ý: đánh dấu mỗi bản phát hành bằng tag, ví dụ `git tag v1.1.8 <commit>` rồi `git push origin v1.1.8`.

Khôi phục **mã** không khôi phục dữ liệu. Phiên bản chương trình trên máy chạy thật đổi bằng `deploy-upgrade.ps1` /
`rollback-version.ps1` (mục 6), dữ liệu bằng backup (`docs/VAN-HANH.md`).

## 6. Phát hành và nâng cấp ứng dụng (không mất database, cấu hình)

1. Mã đã commit + push.
2. `powershell -ExecutionPolicy Bypass -File scripts\release.ps1`: QA (test + build giao diện) rồi mới build gói
   `dist\DemandForecast-<version>-win64-portable.zip` + `.sha256` + manifest, ghi commit trong `BUILD-INFO.json`
   (`docs/PHAT-TRIEN-QA-PHAT-HANH.md`). Thư mục `dist/` bị Git bỏ qua: **không commit ZIP, file thực thi hay dữ liệu**.
   VPS: `docs/TRIEN-KHAI-VPS.md`.
3. Nâng cấp máy chạy thật đúng theo `AGENTS.md` mục 7 và `docs/VAN-HANH.md`: `scripts\deploy-upgrade.ps1 -Package <zip>
   -ExpectedSha256 <sha> -CheckOnly`, rồi chạy thật với xác nhận `UPGRADE-<version>` (script tự backup, giữ nguyên DB,
   model, `storage.json`, lịch chạy). Quay về: `rollback-version.ps1 -To <version>`.
4. Database, model, backup, `storage.json` nằm ngoài repository nên `git pull`, `git checkout`, `git restore` không bao
   giờ chạm vào chúng.

## 7. Bảo vệ repository private và thông tin đăng nhập

- Đăng nhập GitHub qua Git Credential Manager (lưu trong Windows Credential Manager của tài khoản Windows). Không ghi
  token vào URL remote (`git remote -v` chỉ được hiện `https://github.com/...` thuần), không dán token vào chat, tài liệu,
  script hay commit.
- Chỉ mời người cần thiết vào repository; không đổi repository sang Public.
- Nếu lỡ commit secret: dừng, **không** tự viết lại lịch sử; thu hồi/đổi secret ngay (GitHub, Google Cloud) rồi báo người
  phụ trách để quyết định cách xử lý lịch sử.
