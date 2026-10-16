# Phát triển, QA, phát hành và lưu trữ (Single Source of Truth, từ 16/10/2026)

## 1. Nguyên tắc

- `D:\Buymed\Lightgbm AI` (Git, nhánh `main`, GitHub private `Giau2510/Demand-Planning-LightGBM`) là **bộ mã nguồn
  duy nhất**. Không tạo bản sao source hay repository cho từng phiên bản: phiên bản = commit (+ tag khi phát hành).
- Máy này (Development/QA) và VPS chạy **cùng một source/phiên bản**. Cấu hình, thông tin xác thực, database và dữ liệu
  runtime thì riêng cho từng môi trường và không bao giờ nằm trong Git hay trong gói phát hành.
- Gói phát hành (artifact) chỉ được tạo khi phát hành / kiểm thử đóng gói / triển khai, không tạo sau mỗi lần sửa.
- `dist\` chỉ chứa artifact có thể tạo lại; không dùng làm nơi lưu dữ liệu.

## 2. Thư mục

| Đường dẫn | Loại | Git | Ghi chú |
|---|---|---|---|
| `backend\app`, `backend\tests`, `backend\requirements*.txt` | mã nguồn, test, lockfile | có | `requirements.lock.txt` = phiên bản cố định cho gói và VPS |
| `frontend\src`, `frontend\package*.json`, cấu hình Vite/TS | mã nguồn giao diện | có | `package-lock.json` = lockfile |
| `scripts\` | cài đặt, nâng cấp, build, phát hành, `scripts\vps\` triển khai Linux | có | PS1 chỉ ASCII; `.sh` dùng LF |
| `docs\`, `README.md`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md` | tài liệu | có | |
| `config\app.env.example`, `scripts\vps\app.env.example` | cấu hình **mẫu**, không có secret | có | |
| `.venv\`, `frontend\node_modules\` | phụ thuộc phát triển, cài lại được | không | `scripts\setup-dev.ps1` |
| `frontend\dist\` | giao diện đã build | không | `npm run build` |
| `dist\` | artifact phát hành + `dist\.cache` (Python embedded tải về) | không | xem mục 5–6 |
| `release\` | bản giải nén để kiểm tra gói (cách làm cũ, 1.1.0–1.1.6) | không | không tạo thêm; kiểm gói bằng `scripts\release.ps1` |
| `data\runtime\` | **dữ liệu thật của máy này** (DB, model) | không | do `storage.json` chỉ tới (di chuyển 14/10/2026); **không di chuyển** bằng tay — chỉ qua `scripts\migrate-storage.ps1` (`docs/LUU-TRU.md`) |
| `backups\`, `logs\`, `reports\` | backup, log, báo cáo runtime của máy này | không | |
| `checkpoints\` | ZIP mã nguồn trước mỗi đợt sửa lớn | không | nhỏ (< 5 MB) |
| `templates\` | mẫu Excel do build sinh lại | không | |
| `%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản>\` | bản **đã cài** đang chạy + bản rollback | — | ngoài project; `current.txt` = bản đang dùng |
| `%LOCALAPPDATA%\DemandForecast\storage.json` | con trỏ tới thư mục dữ liệu | — | không sửa tay |

Dữ liệu runtime của máy này nằm *trong* thư mục project (`data\`, `backups\`...) nhưng bị Git bỏ qua; đây là lựa chọn
lưu trữ đã thực hiện ngày 14/10/2026 và được giữ nguyên. Trên VPS, dữ liệu luôn nằm ngoài thư mục mã
(`/var/lib/demandforecast`, `docs/TRIEN-KHAI-VPS.md`).

## 3. Phát triển trên máy này

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1     # .venv + node_modules (một lần)
cd frontend; npm run dev                                             # giao diện dev
```

- Chạy backend từ mã nguồn **chỉ với dữ liệu cô lập**: bản sao DB (SQLite backup API, nguồn `mode=ro`) +
  `DF_DATA_DIR`, `LOCALAPPDATA` riêng và `DF_DISABLE_SCHEDULER=1` (AGENTS.md mục 4). Không bao giờ trỏ mã nguồn vào
  `data\runtime` của ứng dụng đang chạy.
- Ứng dụng thật trên máy này là **bản đã cài** (`%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản>`), không phải mã
  nguồn đang sửa.

## 4. QA

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-tests.ps1      # pytest + typecheck + vitest + vite build, log ở logs\development\
```

- Test thay đổi dữ liệu: trên bản sao DB, ghi số dòng/tổng trước–sau.
- BigQuery thật (chỉ đọc, dữ liệu nội tuyến, 0 byte): `$env:DF_REAL_BQ = "1"` rồi chạy `backend\tests\test_bq_real_semantics.py`.
- Lint chưa cấu hình: ghi "not configured", không ghi "passed".

## 5. Build và phát hành

```powershell
git status                                   # sạch: phát hành là một commit đã được xem xét
powershell -ExecutionPolicy Bypass -File scripts\release.ps1
```

`scripts\release.ps1`:
1. dừng nếu còn thay đổi chưa commit (`-AllowDirty` chỉ cho bản build thử, gói bị đánh dấu `dirty`);
2. QA (`run-tests.ps1`); lỗi bất kỳ ⇒ **không** tạo gói;
3. `build-package.ps1` ⇒ `dist\DemandForecast-<version>-win64-portable.zip` + `.sha256` + `.manifest.json`;
4. kiểm tra: SHA-256 khớp file `.sha256`; `VERSION`, `BUILD-INFO.json` trong gói đúng phiên bản và commit;
5. in kế hoạch giữ/xóa artifact (không xóa gì).

Định danh và chống build trùng (`build-package.ps1`):
- `BUILD-INFO.json` trong gói và manifest ghi `version`, `commit`, `dirty`, `source_fingerprint` (SHA-256 của mọi
  file đầu vào + cấu hình build).
- Cùng `source_fingerprint` và SHA-256 hợp lệ ⇒ **không build lại** ("Up to date").
- Đã có gói cùng phiên bản nhưng khác nguồn ⇒ **từ chối**: phải tăng phiên bản (`backend\app\__init__.py`), hoặc
  `-Force` (gói cũ được đổi tên `...-superseded-<thời điểm>...`, không bị xóa).
- Thư mục tạm `dist\DemandForecast-<version>\` bị xóa sau khi tạo ZIP (`-KeepFolder` để giữ).
- Gói không chứa DB, `.env`, thông tin xác thực hay dữ liệu: chỉ code, runtime nhúng, giao diện, script, tài liệu, mẫu
  Excel sinh lại.

Gói Linux cho VPS: `scripts\vps\build-vps-artifact.ps1` ⇒
`dist\DemandForecast-<version>-<commit7>-linux-src.tar.gz` + `.sha256` (cùng commit đã build ⇒ không build lại).

Sau phát hành: `git tag v<version> <commit>` rồi `git push origin v<version>` (khi được phép push,
`docs/GITHUB_WORKFLOW.md`).

Triển khai là bước riêng: máy này ⇒ `scripts\deploy-upgrade.ps1 -Package <zip> -ExpectedSha256 <sha> -CheckOnly`
rồi chạy thật (`docs/VAN-HANH.md`); VPS ⇒ `docs/TRIEN-KHAI-VPS.md`.

## 6. Chính sách giữ artifact

| Loại | Giữ | Công cụ |
|---|---|---|
| Gói của phiên bản **đang chạy** (`current.txt`) = bản mới nhất đã kiểm thử | luôn | `scripts\prune-artifacts.ps1` |
| Gói của **một** phiên bản ổn định gần nhất để rollback (đã chạy production, `rollback-version.ps1 -CheckOnly` OK) | luôn (`-Keep <phiên bản>`) | 〃 |
| Gói của phiên bản mới nhất (khi vừa build, chưa cài) | luôn (`-KeepLatest 1`) | 〃 |
| Gói cũ khác, gói `superseded`, gói chưa từng cài | xóa | 〃 `-Apply` |
| Thư mục tạm `dist\DemandForecast-<v>\`, bản giải nén `release\...` | xóa chỉ khi **mọi file trùng SHA-256** với gói; khác ⇒ giữ, người dùng quyết định | 〃 `-Apply` |
| `dist\.cache` (Python embedded) | giữ (tránh tải lại) | — |
| Bản đã cài trong `%LOCALAPPDATA%\Programs\DemandForecast` | bản đang chạy + bản rollback; bản khác chỉ gỡ khi người dùng quyết định | thủ công |
| Release trên VPS | 3 bản mới nhất, luôn giữ bản đang chạy và bản trước | `scripts/vps/deploy.sh` |

`prune-artifacts.ps1` mặc định chỉ in kế hoạch; chỉ xóa khi có `-Apply`. Không xóa release cũ trước khi release mới đã
chạy được (đã nâng cấp và kiểm tra). Ví dụ hiện tại: `scripts\prune-artifacts.ps1 -Keep 1.1.6` (đang chạy 1.1.8,
rollback 1.1.6).

Dọn ngày 16/10/2026: project 6.876 MB → 988 MB. Còn lại trong `dist\`: gói 1.1.8 (đang chạy) và 1.1.6 (rollback) + `.cache`.
Danh sách chính xác và bằng chứng: `reports\storage_cleanup_plan_20261016.md`,
`reports\demandforecast_storage_release_20261016.md`. Các bản đã cài 1.0.0–1.1.5 trong `Programs` (≈ 2 GB, ngoài project)
chưa xóa: chỉ gỡ khi người dùng quyết định.

## 7. Chính sách giữ backup (đề xuất — không có xóa tự động)

Backup là dữ liệu người dùng; ứng dụng không tự xóa backup. Đề xuất khi dọn thủ công:
- luôn giữ: backup trước mỗi lần nâng cấp/di chuyển lưu trữ/migration (`-pre-*`, backup do `deploy-upgrade.ps1` tạo),
  và backup mới nhất đã kiểm tra;
- giữ mọi backup của 14 ngày gần nhất, sau đó mỗi tuần một bản trong 3 tháng;
- bản sao ngoài máy (ổ khác / lưu trữ đám mây) cho backup trước nâng cấp;
- không xóa backup khi đang có sự cố hoặc ngay trước/sau một lần nâng cấp.
