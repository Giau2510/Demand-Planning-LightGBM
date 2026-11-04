# Demand Forecasting 1.1.8 — kiểm toán toàn diện + kiểm tra hậu push GitHub

Ngày 16/10/2026, 11:14–11:45 (giờ Việt Nam). Máy LOG-PC, tài khoản Windows `LOG-PC\Giau Vo`, thư mục
`D:\Buymed\Lightgbm AI`. Bản đang chạy: **1.1.8** (cài 08:34, pid 18608). Nguồn đang dùng: DEMO. Kiểm toán gồm đọc mã,
2 reviewer chỉ đọc (dữ liệu/ML; API/UI/vận hành/bảo mật), chạy test, clone thật từ GitHub, kiểm tra BigQuery thật chỉ
đọc. **Không commit, không push, không cài, không chạy job production, không ghi DB thật.**

## A. Executive Summary

**Tình trạng tổng thể:** mã nguồn, Git và bản cài 1.1.8 ở trạng thái tốt và nhất quán; test đầy đủ đạt. Lần đầu tiên,
đường xác thực của chính ứng dụng (ADC của tài khoản Windows này) **truy cập được bảng BigQuery thật**; dữ liệu thật
khớp các số liệu nền (8.885.547 dòng, 01/01–14/10/2026, 287 ngày, 1.345.228 tổ hợp). Luồng BigQuery **chưa sẵn sàng
production**: ánh xạ trường chưa lưu, chính sách trùng khóa chưa quyết định (dữ liệu thật sẽ bị chặn), quy tắc ngày
đầy đủ / giờ D-1 chưa chốt.

**Có đủ điều kiện chuyển sang *thiết kế* phương thức nhập dữ liệu:** **CÓ** — hợp đồng dữ liệu, schema, chất lượng và
chi phí của nguồn thật đã được đo; các rủi ro đã liệt kê kèm bằng chứng. **Chưa đủ điều kiện *triển khai* / bật
production** cho tới khi xử lý mục L.2 và có các quyết định ở L.3.

**5 rủi ro quan trọng nhất**
1. **Trùng khóa trong nguồn thật** (K-R1): 9.516 nhóm (so_code, sku_code, fc_code, ngày) có nhiều dòng (≈ 1 % số
   lượng), 432 nhóm giống hệt; cấu hình mặc định (CHẶN) sẽ từ chối đồng bộ — cần quyết định SUM / bỏ dòng y hệt / khóa khác.
2. **Ô thiếu thành 0** (K-R2): SKU × FC × ngày không có dòng được coi là nhu cầu 0 khi ngày đó có dữ liệu ở bất kỳ
   series nào; chưa kiểm độ đầy đủ theo FC-ngày; `open_date`, `total_open_*` không dùng — trái quy tắc "không tự coi
   ngày thiếu là 0" nếu chưa chốt định nghĩa "ngày đầy đủ".
3. **Độ mới / giờ chạy D-1** (K-R3): bảng nguồn được làm mới toàn bộ, ngày D có vào khoảng **trưa D+1**
   (`refresh_time` = `11:44:36 15/10/2026` cho mọi dòng, kiểu STRING); D-1 mặc định 01:00 → fallback 06:00 và huấn
   luyện 07:00 sẽ thấy dữ liệu đến D-2 hoặc ngày chưa đủ.
4. **Kết quả xấu bị che** (K-R4): huấn luyện REJECTED/FAILED được ghi là job *Thành công* (đã sửa phần hiển thị ở
   trang lịch, trong mã nguồn); các luồng bị tắt ngầm khi cấu hình BigQuery đổi (SKIPPED, không cảnh báo).
5. **Đọc rỗng xóa dữ liệu** (K-R8): D-1 nhận 0 dòng sẽ xóa toàn bộ cửa sổ — **đã sửa trong mã nguồn** (chưa có trong
   bản cài 1.1.8).

**Chưa thể xác minh:** đồng bộ D-1/D0 thật và huấn luyện trên dữ liệu BigQuery (không được phép chạy); hành vi OAuth
in-app (chưa có OAuth client — ADC thì đã đạt); E2E trình duyệt cho bản sửa (cần build/chạy bản nguồn); cài thật trên
một PC Windows khác (đã thay bằng clone + venv mới + build gói trong thư mục tạm).

## B. GitHub Post-push Verification

| Kiểm tra | Kết quả | Bằng chứng |
|---|---|---|
| Repository | `Giau2510/Demand-Planning-LightGBM`, owner User `Giau2510`, **Private**, default branch `main`, quyền admin/push | GitHub API (credential trong Git Credential Manager, không in) |
| Remote `origin` | `https://github.com/Giau2510/Demand-Planning-LightGBM.git` (fetch/push), không nhúng token | `git remote -v` |
| Commit | local HEAD = `origin/main` = `ls-remote refs/heads/main` = `d87c315c3e9d450c967a44298fca8fbf08c24f94`; 1 commit; nhánh duy nhất `main` | `git rev-parse`, `git ls-remote` |
| Working tree trước audit | sạch (`## main...origin/main`, không staged/unstaged/untracked) | `git status --short --branch` |
| File theo dõi | **173** (backend 85, frontend 43, scripts 19, docs 16 gồm `docs/data/`, `.claude` 3, config 1, gốc 6); 169 blob | `git ls-files`, `git ls-tree -r HEAD` |
| Submodule / LFS | không có `.gitmodules`; 0 file có filter LFS | `git check-attr filter` |
| `.gitignore` | 31/31 đường dẫn phải loại đều bị loại (DB/WAL/SHM, models, backups, checkpoints, logs, reports, dist, release, node_modules, .venv, pycache, frontend/dist, tsbuildinfo, .env*, client_secret*, service-account*, ADC, *.pem/.p12, xlsx/csv, templates, settings.local); 11/11 đường dẫn phải giữ **không** bị loại (`backend/app/data/*`, `docs/data/*`, `config/app.env.example`, migrations, D0 SQL, scripts, lock, `.claude/settings.json`, workflow doc); 0 file đang theo dõi khớp quy tắc loại trừ | `git check-ignore --no-index`, `git ls-files -ci` |
| `.gitattributes` | `* -text`: không chuyển đổi xuống dòng; 53 CRLF + 113 LF + 2 trộn lẫn (`backend/app/export_i18n.py`, `backend/tests/test_storage.py`, có từ trước, giữ nguyên); index = working tree | `git ls-files --eol` |
| Secret — lịch sử | 1 commit, 169 blob, commit message: **0 secret thật**. 4 kết quả dạng `GOCSPX-…` đều là fixture giả `GOCSPX-FAKE-SECRET-0001` trong `backend/tests/test_v117.py:335-355` (test khẳng định secret chỉ vào kho bộ nhớ của test và **không** xuất hiện trong DB/API). Email: chỉ `planner@buymed.example`, `p@b.example` (test). Định danh môi trường (không phải secret): project `lakehouse-prod-394907` (25 lần, 12 file: mặc định cấu hình, 2 file SQL D0, tài liệu, test), đường dẫn `C:\Users\Giau Vo` / `LOG-PC` (≈ 9 lần trong tài liệu/test) | scratchpad `git_history_scan.py` |
| Clone máy khác (mô phỏng) | `git clone` vào thư mục tạm trên ổ C: (máy có `core.autocrlf=true`): 173/173 file **trùng từng byte** với nguồn | so SHA-256 từng file |
| Clone — frontend | `npm ci` (Node 24.18 / npm 11.16) đạt, typecheck đạt, **52/52** test, build đạt; cảnh báo npm 11 `allow-scripts` cho `esbuild` (không ảnh hưởng) | log tác vụ |
| Clone — backend | `py -3.14 -m venv` mới + `pip install -r requirements-dev.txt` đạt, `pip check` sạch; pytest **274 đạt, 1 lỗi + 1 error** ở `test_storage.py::test_configured_d_drive_location_all_files_land_there` (test giả định dự án nằm trên ổ D:) → đã sửa test (J), chạy lại trong clone **22/22** | log tác vụ |
| Clone — đóng gói | `build-package.ps1` chạy trong clone: **đạt**; mã ứng dụng, giao diện, scripts trong gói **trùng từng byte** với gói 1.1.8 đã phát hành → phát hành tái lập được từ Git | mục I |

**Vấn đề cần xử lý (Git):** không có vấn đề chặn. P3: test phụ thuộc ổ D: (đã sửa); 2 file trộn xuống dòng (giữ
nguyên, không chuyển đổi hàng loạt); `GITHUB_WORKFLOW.md` thiếu điều kiện cài đặt máy mới (đã bổ sung).

## C. Application Architecture

**Kiến trúc thực tế:** một tiến trình Python (FastAPI + uvicorn, chỉ nghe `127.0.0.1:8765`) phục vụ API và giao diện
React đã build; scheduler chạy trong cùng tiến trình (tick 30 s); SQLite (WAL, schema 3) tại vị trí do
`storage.json` chỉ định; model LightGBM là file trong `<data>\models`; gói portable có Python embedded.

**Luồng dữ liệu đầu cuối**
- *Excel:* upload `.xlsx` → `excel_io` (chặn macro, zip-bomb, 50 MB / 2 triệu dòng) → `validation` (ngày giờ VN, grain
  đơn × SKU × FC, lỗi theo dòng) → lô PENDING_REVIEW → xác nhận → `order_lines` → `aggregate_batch` → `demand_daily`
  (scope = lô ACTIVE).
- *BigQuery:* `connector._run` (dry-run → `maximum_bytes_billed` → truy vấn, timeout + retry có giới hạn) →
  `fetch_daily` (lọc NULL_SKU / NULL_FC / NULL_TARGET / NEGATIVE_TARGET, chính sách trùng, `SUM(qty)` theo ngày × SKU
  × FC) → `sync.run_d1_sync` (xóa + chèn cửa sổ trong **một** transaction, đối soát số dòng + tổng) → `demand_daily`
  (scope BIGQUERY). D0: `run_d0_snapshot` → `d0_snapshots` / `d0_snapshot_values` (bất biến), không bao giờ vào lịch sử.
- *ML:* `resolve_scope` → `data_window` (01/01/2026 → hôm qua VN) → `load_demand` → `build_panel` (lag ≥ 1, rolling
  `[t−w, t)`, lịch, giá/khuyến mãi t−1) → LightGBM (seed 7, deterministic) + walk-forward 12 × 30 ngày → quality gate →
  publish (một transaction) hoặc model **chờ duyệt** khi đã có model đang dùng → `forecast_runs` / `forecast_values`
  (bất biến) + lineage (`training_runs`, SHA-256 model, fingerprint dữ liệu).
- *Điều phối:* `scheduler.plan` (theo công tắc từng luồng, `*_enabled_at`) → `runner.execute` (idempotency key,
  lease lock theo loại job, retry, timeout) → handler.

**Khác biệt tài liệu ↔ mã đã xác minh** (đã sửa tài liệu, mục J): tải lại toàn kỳ chỉ thay từ đầu cửa sổ; `BQ_AUTH_MISSING`
có retry ở mức job; D-1 "chỉ quét vài ngày" chỉ đúng với bảng có phân vùng (bảng thật **không** phân vùng);
`NO_NEW_DATA` không xảy ra với BigQuery (fingerprint có `loaded_at`); quy tắc đơn hủy cho BigQuery đã được xác nhận;
kết quả huấn luyện khác trạng thái job; D-1 ngày bị lỡ được đọc lại; dòng bảng `STORAGE_NOT_FOUND` bị gãy (ký tự `\r`).
Còn lại (chưa sửa, P3): `VAN-HANH.md` / `KIEN-TRUC.md` ghi đường dẫn mặc định thay vì ổ D: của máy này; `LUU-TRU.md`
nói upload tạm xóa sau 24 h (thực tế chỉ dọn khi khởi động); `main.py` nhắc `scripts\build-frontend.ps1` không tồn tại.
Phát hiện "AGENTS.md vẫn ghi không phải Git" của reviewer B là **sai** (đã cập nhật trong commit) — loại bỏ.

## D. BigQuery & Data Contract

**Xác thực (kiểm tra thật 11:20):** `bq-check` của ứng dụng (bản cài 1.1.8, trên **bản sao DB** trong thư mục cô lập):
`auth` đạt qua **ADC** của tài khoản Windows này (tài khoản Google @buymed.com), `api_and_dataset`, `location`
(`asia-southeast1`), `table_metadata` (8.885.547 dòng), `query_job` (dry-run 0 byte + `SELECT 1`) đạt;
`schema_mapping` **chưa đạt** vì DB chưa lưu ánh xạ. OAuth in-app chưa cấu hình (không cần khi dùng ADC). DB thật
vẫn hiển thị trạng thái cũ `BQ_AUTH_MISSING` (15/10) cho tới khi người dùng bấm *Kiểm tra quyền BigQuery*.

**Schema thật vs ánh xạ** (đề xuất tự động `suggest_mapping` của ứng dụng khớp quy tắc nghiệp vụ):

| Trường nguồn | Kiểu thật | Trường nội bộ | Bắt buộc | Chuyển đổi | Nơi dùng |
|---|---|---|---|---|---|
| `created_date` | DATE | `order_date` | có | `DATE(col)`, không đổi múi giờ | ngày của grain |
| `sku_code` | STRING | `sku_id` | có | CAST STRING; NULL → loại `NULL_SKU` | khóa series, feature |
| `fc_code` | STRING | `fc_id` | có | CAST STRING; NULL → loại `NULL_FC` | khóa series, feature |
| `demand_quantity` | INTEGER | `order_qty` → `demand_daily.qty` | có (target) | `SUM` theo ngày × SKU × FC; NULL → `NULL_TARGET`; < 0 → `NEGATIVE_TARGET`; 0 giữ | target duy nhất |
| `so_code` | STRING | `order_id` | không | `COUNT(DISTINCT)` → `n_orders`; thành phần khóa trùng | lưu, không dùng trong model |
| `refresh_time` | **STRING** | (`source_updated_at` cần TIMESTAMP/DATETIME) | không | không dùng được trực tiếp | — |
| `order_status`, `product_id`, `item_code`, `seller_code`, `sku_system_status`, `outbound_quantity`, `sales_price`, `seller_class`, `open_date`, `total_open_hours`, `total_open_days` | xem docs/BIGQUERY.md §12 | `reference_mapping` (`ref_*`) | không | chỉ thống kê / đối chiếu | **không** lọc, **không** là feature |

Không có cột giả định ngoài danh sách (chỉ `price_after_discount` được gợi ý và báo thiếu, vô hại). Không có lọc
`order_status` trong ứng dụng (SQL D0 v1 của người dùng có `NOT IN ('CANCEL')`, làm rơi cả status NULL).

**Target / grain:** mã thực hiện đúng `SUM(demand_quantity)` theo `created_date × sku_code × fc_code`; cùng một đơn ở
nhiều SKU/FC không bị đếm hai lần; đồng bộ lại cùng cửa sổ là idempotent (xóa + chèn + đối soát).

**Dữ liệu thật (16/10 11:21):** 287/287 ngày có dữ liệu, mỗi ngày đủ 2 FC; không NULL ngày/SKU/FC/số lượng, không âm,
không 0; tổng 41.654.787; 9.669 SKU; 693 dòng `so_code` NULL (đúng bằng số dòng WAIT_TO_CONFIRM); không có trạng thái
hủy; ngày thấp: 13–19/02 (Tết), 01/09. Trùng khóa: 9.516 nhóm / 9.769 dòng dư / tối đa 5 dòng; cùng item/seller/product/
status trong mọi nhóm; 432 nhóm giống hệt (445 dòng). Chi tiết: docs/BIGQUERY.md §12.

**Chi phí:** 7 truy vấn audit (dry-run trước, trần 2 GiB): ≈ **3,34 GB** quét (≈ 0,003 TiB, ước tính < 0,03 USD theo giá
on-demand công bố). Bảng **không phân vùng** → mọi truy vấn đồng bộ quét toàn bộ các cột được chọn (0,2–0,7 GB mỗi
truy vấn, tăng theo thời gian); trần mỗi truy vấn trong cấu hình là 20 GiB, không có ngân sách theo ngày.

**Đồng bộ & đối soát:** khóa theo loại job; đối soát số dòng + tổng số lượng trước commit; lineage lưu cửa sổ,
mapping_hash, SQL id + sha256, số dòng mới/cập nhật/không đổi/bị bỏ; `production_enabled` được kiểm ở mọi đường ghi
(D-1, D0, huấn luyện, readiness, chuyển nguồn) — các đường chỉ đọc kiểm tra (access/preview/validate/dry-run) cố ý không
cần nhưng luôn qua dry-run + trần bytes. Điểm yếu: K-R1, K-R3, K-R8, K-R9, K-R10, K-R14.

## E. Excel Import & Batch Management

- Validation: ngày giờ không múi giờ = giờ VN; có offset thì đổi; chỉ ngày = 00:00 VN; số serial Excel không được đọc
  (báo `INVALID_DATETIME`); thiếu cột bắt buộc → `MISSING_REQUIRED_COLUMNS`; cột thừa bỏ qua; macro bị chặn.
- **Cô lập lô: đạt.** Mỗi lần import là một lô; xác nhận / thay / xóa theo `batch_id` / `scope_key`, nguyên tử, có xác
  nhận gõ chữ; chỉ một lô ACTIVE nên không cộng trùng.
- Nhập lại cùng file: tạo lô ACTIVE mới (lưu sha256, không cảnh báo) — P3. Dòng của lô PENDING_REVIEW không bị dọn nếu
  bỏ dở — P3. `GRAIN_CONFLICT` ở chế độ ERROR loại cả nhóm (có tài liệu) — P3.
- DEMO: lô gắn nhãn "DEMO synthetic", `data_source='DEMO'`, file mẫu ghi "synthetic"; giá / khuyến mãi DEMO là dữ liệu
  tổng hợp nhưng được dùng làm feature (độ phủ 100 %) — không thể nhầm với BigQuery (khác scope/nguồn).
- Ngữ nghĩa target khác nguồn: Excel/DEMO không trừ đơn hủy, BigQuery đã loại đơn hủy ở nguồn (K-R6).

## F. ML & Backtesting

- **Leakage: không phát hiện.** Feature chỉ dùng thông tin trước t (lag ≥ 1, rolling `[t−w, t)`, giá/khuyến mãi t−1,
  lịch tại t); test `test_backtest_forecast_unchanged_when_future_changes` khóa điều này. Rò rỉ nhẹ không phải target:
  siêu tham số và quyết định độ phủ giá/khuyến mãi dùng toàn bộ dữ liệu.
- **Cửa sổ huấn luyện:** `load_demand(window.start, window.end)` = 01/01/2026 → hôm qua.
- **Walk-forward:** huấn luyện lại mỗi fold trên dữ liệu trước gốc; đánh giá một horizon 30 ngày gộp; 7/15 ngày không
  được chấm riêng (K-R11); series chưa sinh ở gốc fold bị chấm như dự báo 0 (bi quan, không phải leakage).
- **Chỉ số:** WAPE/bias trả `None` khi tổng thực tế = 0 và gate coi là không đạt. API *độ chính xác sau công bố* dùng
  INNER JOIN nên bỏ các ngày nhu cầu 0 → WAPE bị đánh giá thấp (K-R12, phụ thuộc quyết định K-R2).
- **Ngưỡng gate** là ví dụ, `approved_by_business=false` (K-R13).
- **Promotion / rollback:** model mới khi đã có model đang dùng luôn chờ duyệt; huấn luyện lỗi không chạm model đang dùng
  (publish một transaction); **không có đường quay lại model ACCEPTED cũ hơn** (K-R15). Fingerprint chứa `loaded_at` →
  với BigQuery model chờ duyệt hết hạn sau lần D-1 kế tiếp (K-R5).
- **Lineage / tái lập:** forecast → training run → SHA-256 model + fingerprint + mapping_hash + cửa sổ; `extend_forecast`
  kiểm tra tái lập chính xác. Huấn luyện và D-1 có thể chạy song song, đọc fingerprint và dữ liệu ở các kết nối khác nhau
  → lineage có thể lệch (an toàn vì extend/promote từ chối) (K-R9).

## G. API, Frontend, Scheduler, Database

- **API:** chỉ `127.0.0.1`, kiểm Host, `X-DF-Client` + Origin cho POST/PUT/DELETE, token tắt máy theo phiên; lỗi trả
  JSON có request_id, không stack trace, không secret. Một số GET có ghi/tốn CPU (báo cáo chất lượng, tính lại backtest)
  không cần header — P3. `/api/bigquery/estimate` trả 500 với ngày sai; `limit` không chặn trên — P3.
- **Trạng thái UI:** đã sửa (mã nguồn) trang *Lịch chạy dữ liệu*: hiện kết quả thật của job, theo dõi job "Chạy ngay"
  tới khi xong, chặn bấm lặp, báo job đang chạy sẵn. Còn lại: *Đồng bộ lại khoảng ngày* (backfill) không phản hồi
  (P2); không có huy hiệu cảnh báo toàn cục, Jobs/Snapshots không tự cập nhật (P2); đổi nguồn không xác nhận (P2).
- **Scheduler:** công tắc từng luồng hoạt động đúng (đã kiểm thật hôm nay: D-0 chạy 10:00 đúng lịch); idempotency key +
  lease lock; timeout của D-1/D0 không hủy được luồng đọc trong khi khóa đã nhả (P2); D-1 và huấn luyện không loại trừ
  nhau (P2); các luồng bị SKIPPED không cảnh báo khi cấu hình BigQuery thay đổi tắt production (K-R4); không có watchdog
  khi ứng dụng sập (chỉ tự chạy khi đăng nhập) (P2).
- **Database:** WAL, foreign_keys ON, busy_timeout 30 s, BEGIN IMMEDIATE; migration bổ sung có thứ tự, sao lưu trước,
  từ chối schema mới hơn; khởi động **từ chối** tạo DB rỗng khi ổ/DB cấu hình không có (chỉ tạo ở vị trí mặc định /
  DF_DATA_DIR / allow_create). `data-check` DB thật: 12 OK + 1 WARN đã biết.
- **Backup / restore:** backup online + `integrity_check` trên bản sao; không có giới hạn số bản, zip không kiểm thử lại,
  cùng ổ dữ liệu (P2). `restore.ps1` tìm tên file trong `<data>\backups` — máy này cấu hình `D:\Buymed\Lightgbm AI\backups`
  nên phải dùng đường dẫn đầy đủ (P2, chưa sửa vì không kiểm thử an toàn được). Lệnh `check-env` / `backup` của CLI tự
  chạy migrate (P2).

## H. Security & Packaging

- **Secrets:** không có trong Git; OAuth secret/refresh token chỉ trong Windows Credential Manager; log có lọc; chẩn đoán
  được che. ADC nằm ở `%APPDATA%\gcloud` của tài khoản Windows (ngoài dự án; nội dung không được đọc trong audit).
- **Phơi bày dịch vụ:** chỉ localhost; không CORS; chưa có header bảo mật (CSP, X-Frame-Options) — P3; scope OAuth
  `bigquery` (đọc-ghi) dù ứng dụng chỉ đọc — P3.
- **Phụ thuộc:** backend ghim chính xác + lock 52 gói (không hash); frontend ghim chính xác + lock; Python 3.14 / pandas 3 /
  numpy 2.5 rất mới (rủi ro wheel); `pip install --upgrade pip` không ghim; Node không ghim; build tải Python embedded
  không kiểm SHA-256 (P2).
- **Windows portable:** gói có Python embedded + wheel + backend + web + scripts + docs + mẫu Excel sinh lại; máy đích chỉ
  cần VC++ 2015-2022 x64 (installer tự cài qua winget nếu có — có thể cần quyền admin). Nâng cấp giữ DB / cấu hình / log
  / backup (đã chứng minh trong lần cài 1.1.8 sáng nay). Rollback: autostart không được trỏ lại, không tự khôi phục nếu
  bản đích không khởi động được (P2).

## I. Test Results

| Test / lệnh | Kết quả | Bằng chứng | Ghi chú |
|---|---|---|---|
| `scripts\run-tests.ps1` (trước khi sửa) | **PASS** — backend 275 passed (1 warning thư viện), typecheck 0, vitest 52/52, build 0 | `logs\development\tests_20261016_111531.log` | unit + integration với fake, DB tạm |
| `scripts\run-tests.ps1` (sau khi sửa) | **PASS** — backend **279** passed (275 + 4 mới), typecheck 0, vitest **55/55** (52 + 3 mới), build 0 | `logs\development\tests_20261016_113308.log` | `test_storage.py` sửa sau đó chạy lại riêng: 22/22 (ổ D:) |
| `test_v118_audit.py` (mới) | **PASS** 4/4 | pytest | đột biến: tắt chốt → 2 test **FAIL** (đúng kỳ vọng) |
| `v118.test.tsx` (3 test mới) | **PASS** 7/7 | vitest | chạy với `Schedules.tsx` cũ → 3 **FAIL** (đúng kỳ vọng) |
| Clone: `npm ci` + typecheck + vitest + build | **PASS** (52/52) | log tác vụ | thư mục tạm, ổ C: |
| Clone: venv mới + `pip install` + `pip check` | **PASS** | log tác vụ | Python 3.14 qua `py` |
| Clone: pytest backend | **FAIL → PASS sau sửa test**: 274 passed + 1 failed + 1 error (giả định ổ D:) → `test_storage.py` 22/22 | log tác vụ | lỗi môi trường test, không phải lỗi ứng dụng |
| build-package (clone) | **PASS** — tải Python embedded 3.14.7, cài wheel, tự kiểm runtime (LightGBM 4.7.0), gói 87,8 MB, 7.116 file. So với gói 1.1.8 đã phát hành (7.115 file): `backend/app`, `web/`, `scripts/`, `config/` **trùng từng byte**; khác: `docs/GITHUB_WORKFLOW.md` (mới), `CHANGELOG.md`, `docs/CHECKPOINT.md` (sửa sau build), 10 launcher `.exe` của pip + `RECORD` (nhúng đường dẫn máy build), 3 mẫu Excel (giá trị ô giống hệt, chỉ khác metadata) | manifest hai gói | không chạy trong dự án (sẽ ghi đè `dist\...1.1.8`); gói thật không đổi |
| `app.cli bq-check` (bản sao DB) | **5/6 cổng PASS**, `schema_mapping` FAIL (chưa có ánh xạ) | JSON trong scratchpad | **BigQuery thật**, ADC |
| Profile BigQuery (7 truy vấn tổng hợp) | **PASS** (đọc được, số liệu ở mục D) | ≈ 3,34 GB quét | **BigQuery thật**, chỉ đọc |
| `app.cli data-check` DB thật | **PASS** (12 OK, 1 WARN đã biết) | exit 0 | chỉ đọc |
| Git: check-ignore / eol / history scan / clone byte-compare | **PASS** | mục B | |
| Lint | **NOT CONFIGURED** | — | dự án không có linter |
| Đồng bộ D-1 / D0 BigQuery thật, huấn luyện production | **NOT RUN** | — | không được phép trong nhiệm vụ |
| E2E trình duyệt cho bản sửa | **NOT RUN** | — | bản sửa chưa build/cài; đã có unit test + đột biến |
| OAuth in-app với Google thật | **BLOCKED** | — | chưa có OAuth Desktop client (ADC đã đạt) |

## J. Files Changed (chưa commit)

| File | Vấn đề | Thay đổi | Test xác minh |
|---|---|---|---|
| `backend/app/sync.py` | D-1 đọc 0 dòng xóa cả cửa sổ (K-R8) | dừng trước khi xóa: `Retryable("SOURCE_INCOMPLETE")`, lý do `EMPTY_READ` (+5 dòng) | `test_v118_audit.py` (2 kịch bản + scope rỗng); đột biến FAIL |
| `backend/app/jobs/flows.py` | trang lịch không biết kết quả thật của job | thêm `result_status` vào mỗi dòng job (+1) | `test_schedule_history_reports_the_result_status_of_each_job` |
| `frontend/src/pages/Schedules.tsx` | "Thành công" cho huấn luyện bị từ chối; "Chạy ngay" không cập nhật; không báo job đang chạy sẵn | nhãn kết quả (dùng lại `jobOutcome`), `JobProgress` theo dõi job, khóa nút khi đang chạy, thông báo `already_active` | 3 test mới trong `v118.test.tsx`; với bản cũ FAIL |
| `frontend/src/i18n.tsx` | — | khóa `sch.run_already_active` (vi/en) | vitest |
| `frontend/src/v118.test.tsx` | — | +3 test | vitest |
| `backend/tests/test_v118_audit.py` (mới) | — | 4 test | pytest |
| `backend/tests/test_storage.py` | test giả định dự án nằm trên ổ D: (đỏ trên clone ổ C:) | chỉ khẳng định tiền tố `D:` khi dự án ở ổ D:; dọn thư mục nếu có (giữ CRLF của đoạn này) | clone (ổ C:) 22/22; dự án (ổ D:) 22/22, không để lại thư mục tạm |
| `docs/BIGQUERY.md` | 3 điểm lệch mã; thiếu dữ kiện nguồn thật | sửa §6/§7/§8; thêm §12 dữ kiện bảng thật | đối chiếu mã |
| `docs/SCHEDULER.md` (CRLF) | timeout D-1/D0; kết quả huấn luyện vs job; D-1 ngày lỡ | bổ sung | đối chiếu mã |
| `docs/MO-HINH-VA-CHI-SO.md` (CRLF) | `NO_NEW_DATA` với BigQuery | ghi chú | đối chiếu mã |
| `docs/data/DATA-MODEL.md` | quy tắc đơn hủy BigQuery cũ | cập nhật theo xác nhận 16/10 | — |
| `docs/VAN-HANH.md` | dòng bảng `STORAGE_NOT_FOUND` gãy (ký tự `\r`) | nối lại | — |
| `docs/GITHUB_WORKFLOW.md` | thiếu điều kiện máy mới | bổ sung Python 3.14 / Node / Internet / `frontend\dist`, `templates\` | đối chiếu clone |
| `CHANGELOG.md`, `docs/CHECKPOINT.md` | — | mục *Unreleased*, mục audit | — |

Checkpoint trước khi sửa: `checkpoints\source-1.1.8-before-audit-fixes-20261016-112638.zip`
(SHA-256 `21362237…38A3`). Mọi file giữ nguyên kiểu xuống dòng (kiểm bằng `git ls-files --eol`).

## K. Risk Register

| ID | Mức | Vấn đề | Bằng chứng | Hậu quả | Hành động đề xuất |
|---|---|---|---|---|---|
| R1 | P1 | Trùng khóa trong nguồn thật; mặc định CHẶN | truy vấn thật: 9.516 nhóm, 432 y hệt; `sql_sources.py:55`, `connector.py:959-1002` | đồng bộ BigQuery bị từ chối / hoặc cộng trùng nếu chọn sai | **Quyết định nghiệp vụ:** cộng các dòng (SUM_ALL), bỏ dòng y hệt, hay khóa gồm cột khác; rồi kiểm tra lại |
| R2 | P1 | Ô thiếu = 0 khi ngày có dữ liệu; không kiểm FC-ngày; bỏ qua `open_*` | `features.py:76-93`; dữ liệu thật: đủ 2 FC mọi ngày | lag/WAPE lệch nếu một FC thiếu dữ liệu một ngày | **Quyết định:** định nghĩa "ngày đầy đủ" (theo FC-ngày?), dùng `open_*`/status làm mặt nạ? |
| R3 | P1 | Độ mới nguồn ~trưa D+1; giờ D-1/huấn luyện mặc định quá sớm; `refresh_time` là STRING; chưa có tín hiệu hoàn tất | `refresh_time` thật; `connector.py:1230-1243` (ngưỡng 50 % số dòng) | huấn luyện trên ngày chưa đủ hoặc trễ 1 ngày | **Quyết định:** giờ D-1/huấn luyện, tín hiệu hoàn tất (bảng/cột), giữ chờ thay vì thất bại sau 3 lần thử |
| R4 | P1 | Kết quả xấu bị che: huấn luyện REJECTED/FAILED = job Thành công; luồng bị SKIPPED không cảnh báo khi production bị tắt do đổi cấu hình | `runner.py:28-29,160-164,179-184`; `data_routes.py:43-44`, `ops_routes.py:391` | ngừng nhập/huấn luyện nhiều ngày không ai biết | đã sửa hiển thị trang lịch; còn: cảnh báo WARNING/ngày cho SKIPPED do cấu hình, huy hiệu cảnh báo toàn cục |
| R5 | P1 | Fingerprint có `MAX(loaded_at)` | `demand.py:119-122`, `sync.py:109,129` | với BigQuery: model chờ duyệt hết hạn sau D-1 kế tiếp (~18 h), extend thất bại | **Quyết định quy trình duyệt**; kỹ thuật: hash nội dung trong cửa sổ (thay đổi lớn) |
| R6 | P2 | Target khác nhau giữa nguồn (Excel/DEMO không trừ hủy; BigQuery đã loại hủy); D0 SQL v1 bỏ status NULL | `schema.py:27`; SQL D0 v1 | model/so sánh không cùng ngữ nghĩa | quyết định khi chọn phương thức nhập |
| R7 | P1 | Ánh xạ BigQuery chưa lưu; trạng thái BigQuery trong DB cũ (`BQ_AUTH_MISSING`) | `bq-check` thật | không thể kiểm tra toàn kỳ / bật production | người dùng: bấm *Kiểm tra quyền*, lưu ánh xạ đề xuất (sau quyết định R1) |
| R8 | P1 | D-1 đọc 0 dòng xóa cả cửa sổ | `sync.py:114-137` (bản 1.1.8) | mất dữ liệu cửa sổ tới lần đồng bộ tốt kế tiếp | **đã sửa trong mã nguồn**; cần phát hành bản mới trước khi bật production |
| R9 | P2 | Timeout D-1/D0 không hủy luồng, khóa nhả; D-1 và huấn luyện chạy song song; huấn luyện đọc fingerprint/dữ liệu khác kết nối | `runner.py:130,152-158,190-191`; `pipeline.py:184-260` | chạy chồng, chi phí gấp đôi, lineage lệch | giữ khóa tới khi luồng kết thúc; đọc một snapshot trong huấn luyện |
| R10 | P2 | Bảng không phân vùng; trần 20 GiB/truy vấn, không ngân sách ngày; `_run` nạp toàn bộ kết quả vào RAM | metadata thật; `connector.py:251,533` | chi phí tăng dần; tải lại toàn kỳ lớn | đề nghị nhóm dữ liệu phân vùng theo `created_date` hoặc dùng view có phân vùng; giới hạn số dòng / phân trang |
| R11 | P2 | Backtest chỉ chấm 1 horizon 30 ngày gộp | `model.py:180-207` | không biết chất lượng 7/15 ngày | chấm theo horizon (thay đổi lớn) |
| R12 | P2 | API độ chính xác bỏ ngày nhu cầu 0 | `forecast_routes.py:405-410` | WAPE sau công bố thấp hơn thực | sửa sau khi chốt R2 |
| R13 | P2 | Ngưỡng gate chưa được duyệt | `settings_service.py:58-66` | publish/từ chối theo ngưỡng ví dụ | **Quyết định nghiệp vụ** |
| R14 | P2 | D0: ngày khác hôm nay chỉ cảnh báo; chế độ TABLE không kiểm trùng; kích hoạt SQL D0 chỉ cần dry-run | `connector.py:1078-1120,1159-1185` | snapshot sai ngày / trùng | quyết định khi thiết kế D0 BigQuery |
| R15 | P2 | Không quay lại được model ACCEPTED cũ | `pipeline.py:442` | rollback model khó | thiết kế cùng quy tắc duyệt |
| R16 | P2 | Đổi nguồn không xác nhận, đổi đích của các luồng đang bật | `App.tsx:38-46`, `data_routes.py:81-91` | D-0 đang bật sẽ đọc BigQuery khi production bật | hộp xác nhận + liệt kê luồng đang bật |
| R17 | P2 | Rollback: autostart không trỏ lại; không khôi phục khi bản đích lỗi | `rollback-version.ps1:31-43`, `register-autostart.ps1:4` | sau khởi động lại chạy nhầm bản | sửa script (cần kiểm thử cô lập) |
| R18 | P2 | `restore.ps1` dùng `<data>\backups`; restore không xác nhận gõ chữ | `restore.ps1:8` | khôi phục theo tên file thất bại | dùng `backups_dir` từ `app.cli paths` (cần kiểm thử cô lập) |
| R19 | P2 | `check-env` / `backup` chạy migrate | `cli.py:69,196-197` | bản mới chạy kiểm tra có thể nâng schema DB thật | kiểm tra schema chỉ đọc |
| R20 | P2 | Backup không giới hạn số bản, zip không kiểm lại, cùng ổ; build không kiểm SHA-256 Python tải về | `backup.py:37-43`; `build-package.ps1:36-41` | đầy ổ; chuỗi cung ứng | chính sách lưu giữ; kiểm hash |
| R21 | P2 | Không watchdog; backfill UI không phản hồi; Jobs/Snapshots không tự cập nhật | `register-autostart.ps1`; `SqlSources.tsx:161` | sập = không job; người dùng không biết kết quả | tác vụ khởi động lại; JobProgress cho backfill |
| R22 | P3 | GET có ghi; thiếu header bảo mật; scope OAuth rộng; validation nhỏ (estimate 500, limit, tên file tải) | B-14, 18, 21, 23 | DoS cục bộ / clickjacking | gom vào một bản bảo trì |
| R23 | P3 | Tài liệu còn lệch (đường dẫn mặc định, dọn upload, build-frontend.ps1) | mục C | nhầm khi vận hành | sửa tài liệu |
| R24 | P3 | Phụ thuộc rất mới, lock không hash, Node/pip không ghim | requirements, package.json | cài trên máy mới có thể vỡ | ghim Node (`engines`), hash lock |

Không có rủi ro P0 (không lộ secret, không có đường làm hỏng dữ liệu đang chạy với cấu hình hiện tại).

## L. Decision Gate — trước khi thay đổi phương thức nhập dữ liệu

1. **Đã xác minh:** Git/GitHub đầy đủ và tái lập được từ clone; ứng dụng 1.1.8 đúng grain/target; nhập Excel cô lập
   theo lô; không leakage; truy cập BigQuery thật qua ADC; schema và chất lượng nguồn thật (mục D).
2. **Cần sửa trước khi bật production BigQuery:** phát hành bản có chốt đọc rỗng (R8); cảnh báo cho luồng bị bỏ qua và
   kết quả huấn luyện xấu (R4); khóa/timeout (R9); xác nhận khi đổi nguồn (R16); restore/rollback scripts (R17, R18).
3. **Quyết định nghiệp vụ còn thiếu:**
   - (a) chính sách trùng khóa (R1);
   - (b) định nghĩa ngày đầy đủ / ô thiếu (R2);
   - (c) tín hiệu hoàn tất D-1 và giờ chạy D-1 / huấn luyện (R3);
   - (d) quy trình duyệt model với dữ liệu thay đổi hằng ngày (R5);
   - (e) ngưỡng gate (R13);
   - (f) ngữ nghĩa target giữa các nguồn (R6);
   - (g) có dùng `open_*`, `sku_system_status`, `sales_price` làm feature / mặt nạ không;
   - (h) phân vùng bảng nguồn (R10).
4. **Có thể làm ngay ở giai đoạn thiết kế:** so sánh phương thức (bảng dưới); thiết kế hợp đồng dữ liệu (khóa, đầy đủ,
   độ mới); thiết kế lưu lineage theo lô cho BigQuery; ước tính chi phí theo bảng không phân vùng.
5. **Chưa được phép:** bật production BigQuery, đồng bộ / backfill thật, huấn luyện / phát hành model thật, đổi lịch
   chạy, đổi quy tắc nghiệp vụ, commit/push.
6. **Thứ tự đề xuất:** (i) chốt quyết định 3a–3c → (ii) chọn phương thức nhập → (iii) bản bảo trì gồm R8 (đã sửa), R4,
   R9, R16–R19 + test → (iv) lưu ánh xạ, kiểm tra toàn kỳ trên dữ liệu thật → (v) chạy thử D-1 trên bản sao → (vi) mới
   bật production.

**So sánh phương thức nhập (không triển khai)**

| Phương thức | Ưu điểm | Hạn chế | Rủi ro dữ liệu | Khả năng kiểm thử | Tác động kiến trúc |
|---|---|---|---|---|---|
| Excel `.xlsx` thủ công | đã có, cô lập theo lô, kiểm tra từng dòng, không cần Google | thủ công; 8,9 triệu dòng vượt giới hạn 2 triệu dòng/file; dễ lệch ngữ nghĩa (đơn hủy) | lỗi người dùng, thiếu ngày | tốt (đã có test) | không đổi |
| Đọc trực tiếp BigQuery mỗi lần huấn luyện | luôn mới nhất; không lưu trùng | phụ thuộc mạng/quyền; không tái lập nếu nguồn đổi; chi phí mỗi lần | dữ liệu quá khứ thay đổi âm thầm (bảng làm mới toàn bộ) | kém (cần BigQuery) | lớn (pipeline phụ thuộc kết nối) |
| Đồng bộ BigQuery → SQLite (hiện có) | tái lập (fingerprint, lineage); idempotent; đối soát; offline khi huấn luyện | cần quyết định R1–R3; bảng không phân vùng → quét toàn cột; lưu ~1,35 triệu dòng/9,5 tháng | đọc rỗng (đã sửa), ngày chưa đủ (R3) | tốt (fake BigQuery + bản sao DB) | nhỏ — đã có |
| Lô BigQuery có định danh (snapshot theo `refresh_time` / batch) | truy vết theo lô, nhập lại/so sánh lô như Excel, quay lại lô cũ | cần thiết kế lưu nhiều phiên bản; dung lượng | thấp nếu có kiểm lô | tốt | trung bình (bảng lô cho BIGQUERY) |

**Khuyến nghị (theo điều kiện hiện tại, chưa chọn thay người dùng):** giữ mô hình *đồng bộ vào SQLite* làm nền vì đã có
tái lập, idempotency và đối soát; bổ sung định danh lô theo lần làm mới của nguồn nếu cần nhập lại/so sánh; Excel giữ
cho nguồn ngoài BigQuery. Điều kiện tiên quyết: quyết định 3a–3c.

## M. Git Final State

```
## main...origin/main
 M CHANGELOG.md
 M backend/app/jobs/flows.py
 M backend/app/sync.py
 M backend/tests/test_storage.py
 M docs/BIGQUERY.md
 M docs/CHECKPOINT.md
 M docs/GITHUB_WORKFLOW.md
 M docs/MO-HINH-VA-CHI-SO.md
 M docs/SCHEDULER.md
 M docs/VAN-HANH.md
 M docs/data/DATA-MODEL.md
 M frontend/src/i18n.tsx
 M frontend/src/pages/Schedules.tsx
 M frontend/src/v118.test.tsx
?? backend/tests/test_v118_audit.py
git diff --stat: 14 files changed, 167 insertions(+), 14 deletions(-)   (+ 1 file mới chưa theo dõi)
```

- Không stage, **không commit, không push**, không tạo nhánh: HEAD = `origin/main` = `d87c315c3e9d450c967a44298fca8fbf08c24f94`.
- Quét secret trên phần thay đổi chưa commit: 0 kết quả; không file PS1 nào bị đổi.
- Báo cáo này nằm ở `reports/` (bị Git bỏ qua, không đưa lên GitHub).
- **DB thật, model, cấu hình, lịch chạy, backup không đổi** (11:41): số dòng 20 bảng giống hệt lúc bắt đầu (schema 3);
  `app_settings` giống hệt; 2 file model cùng SHA-256; 25 backup cùng tên/kích thước; 0 job và 0 dòng audit mới từ
  lúc bắt đầu audit; `sync_state.bq_status` không bị ghi (vẫn 15/10); `storage.json` `8D79DBDD…E047`; `current.txt` 1.1.8;
  gói `dist\DemandForecast-1.1.8-win64-portable.zip` vẫn `0DFDEC86…5EE0`; ứng dụng 1.1.8 vẫn chạy.
- Ngoại lệ có chủ đích: các truy vấn BigQuery chỉ đọc (≈ 3,34 GB quét) và trạng thái kiểm tra ghi vào **bản sao** DB trong
  scratchpad; thư mục clone / venv / build tạm cũng trong scratchpad.
