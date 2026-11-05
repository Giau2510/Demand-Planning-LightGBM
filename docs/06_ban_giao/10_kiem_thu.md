# 10 – Kiểm thử

## 1. Bộ test có sẵn

| Bộ | Vị trí | Công cụ | Ghi chú |
|---|---|---|---|
| Backend | `03_ma_nguon\backend\tests\` (≈ 100 file `test_*.py`) | pytest | unit + tích hợp với BigQuery giả (`fake_bq.py`), SQLite thật trong thư mục tạm; mỗi test tự cô lập dữ liệu (`conftest.py`) |
| Frontend | `03_ma_nguon\frontend\src\*.test.tsx` | Vitest + Testing Library | giao diện với API giả |
| Kiểu (TypeScript) | `frontend` | `tsc -b --noEmit` | |
| Smoke end-to-end | `03_ma_nguon\scripts\smoke_test.py` | requests | chạy với **app đang chạy** (HTTP thật, SQLite thật, LightGBM thật): health, giao diện, CSRF, tạo DEMO, học, dự báo, sao lưu… |

Một số test SEL2 cần bộ mẫu dữ liệu thật `backend\tests\fixtures\sel2\` (lấy từ production). Bộ mẫu này **không**
nằm trong Git / gói bàn giao (quy định của chủ dự án 04/11/2026), nên các test đó **tự bỏ qua** (`pytest.skip(
"tests/fixtures/sel2 is not in this checkout")`). Phần logic tương ứng vẫn được kiểm bằng các test dữ liệu tổng hợp của
cùng module.

Test của các thay đổi sau 1.4.0: `backend\tests\test_v142_open_hours_backup.py` (1.4.2: đọc giờ mở bán trong
`FORECAST_REFRESH`, sao lưu / khôi phục `models\sel2`, chặn đường dẫn lạ); `backend\tests\test_v143_forecast_used_rounding.py`
và `test_v140_t6_export.py`, `test_v140_b6_bootstrap.py`, `test_v140_t5t6_edges.py` (1.4.3: quy tắc cố định
`forecast_used`, mục 1.1); `backend\tests\test_v143_deploy_verified_backup.py` (1.4.3: cài không sao lưu lặp lại).

### 1.1 Test quy tắc cố định `forecast_used` (1.4.3, chủ dự án 05/11/2026)

Loại: unit (hàm `_rows` với dữ liệu tổng hợp) + tích hợp với dữ liệu giả (DB SQLite tạm, ghi file Excel thật rồi đọc
lại). Không dùng dữ liệu production.

| Trường hợp | Kết quả kiểm |
|---|---|
| R1 `LIGHTGBM` có số hôm nay | dùng số đó; số **0** với Avg 5 → 0 (không thay bằng Avg) |
| R2 ngoài phạm vi lần chạy | **0** + `NGOAI_PHAM_VI_GAN_0` cho 6 tiền tố mã × 4 giá trị Avg (`MEDX`, `MEDX_E`, `BML_INT`, `TAYAU_E`, `BML_E`, khác) |
| (a) hôm nay lỗi, hôm qua thành công | số lần chạy hôm qua cho đúng ngày đích, `DUNG_SO_LAN_CHAY_TRUOC` + cờ `LAN_CHAY_TRUOC:<D-1>`; số 0 của hôm qua vẫn là 0 |
| ngày lỗi, mã ngoài phạm vi lần chạy trước | **0** + `NGOAI_PHAM_VI_GAN_0` (không phải Avg) |
| (b) lỗi 4 ngày liên tiếp (lần chạy gần nhất D-4) | Avg cho mọi dòng `LIGHTGBM` (`STALE`), cờ file `NO_RUN_3_DAYS`, không dùng số D-4, không ghi 0 |
| ranh giới cửa sổ | lần chạy D-3 được dùng, D-4 không; nhiều lần chạy cùng ngày → lần mới nhất; khác `scope_key` / không phải SEL2 / ngày sau D → bỏ qua; ngày theo giờ Việt Nam |
| (c) thiếu số 1 SKU trong phạm vi | số lần chạy trước gần nhất có số của SKU đó |
| (d) lần chạy trước không có SKU đó | Avg (`KHONG_CO_SO`) |
| ngày lỗi, lần chạy tham chiếu thiếu ngày đích (D+6) | lần chạy cũ hơn trong 3 ngày nếu có, không có → Avg (`STALE`) |
| R4 `AVG_DEMAND` | Avg; không có Avg + có số LightGBM (hôm nay hoặc lần chạy trước) → số LightGBM (`KHONG_CO_AVG_DUNG_LIGHTGBM`) |
| R5 làm tròn / không trống | 0,15 → 0; 0,2 → 1; 1,01 → 2; 3,0 → 3; 2,0000000001 → 2; số âm → 0; NaN / vô cực → 0 `KHONG_CO_SO_NAO`; **mọi dòng `forecast_used` là số nguyên ≥ 0, không trống** |
| nguồn gốc dòng | dòng dùng số lần chạy trước mang `model_version` / `data_cutoff_date` của chính lần chạy đó; không có lần chạy tham chiếu → trống |
| thống kê | số dòng theo lý do trong `DU_BAO` = `TOM_TAT` = `export_runs.summary_json`; file tạm khởi động (`write_temp_export`) theo cùng quy tắc |
| hiệu năng | chỉ đọc tối đa 3 lần chạy (mới nhất mỗi ngày D-3 .. D-1), chỉ các SKU × FC cần tra |

Kết quả (05/11/2026, máy phát triển, code nhánh `github/1.4.3`): 4 file test trên **159 đạt, 0 lỗi, 0 bỏ qua**
(bên giao chạy lại độc lập, 181 giây). Đã qua tester (thêm 18 test), reviewer (không lỗi nghiêm trọng) và
data-reviewer (an toàn có điều kiện; điều kiện: xuất thử trên bản sao DB thật – kết quả ở mục 5).

## 2. Cách chạy

Từ mã nguồn (sau [CAI_DAT.md](../02_cai_dat/CAI_DAT.md) mục 3, venv ở `03_ma_nguon\.venv` có `requirements-dev.txt`):

```powershell
cd "<THU_MUC_GIAI_NEN>\03_ma_nguon\backend"
$env:DF_DISABLE_SCHEDULER = "1"
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider        # ~3-5 min

cd "<THU_MUC_GIAI_NEN>\03_ma_nguon\frontend"
npm ci
npm test                 # vitest run
npm run typecheck        # tsc -b --noEmit
npm run build            # tsc -b && vite build -> frontend\dist
```

Hoặc cả hai bộ, có log: `powershell -ExecutionPolicy Bypass -File scripts\run-tests.ps1` (từ `03_ma_nguon`).

Smoke test với một app chạy thử (thư mục dữ liệu riêng, cổng riêng, scheduler tắt – xem CAI_DAT mục B4):

```powershell
..\.venv\Scripts\python.exe ..\scripts\smoke_test.py --base http://127.0.0.1:<PORT> --phase full --test-data-dir <DATA_DIR_THU>
```

**Luôn truyền `--base` và `--test-data-dir`**: mặc định của smoke test là `http://127.0.0.1:8765` (cổng của app thật),
smoke test ghi nhiều thay đổi (tạo DEMO, học, đổi nguồn, đổi cấu hình, sao lưu) và chỉ chạy khi thư mục dữ liệu của app
trùng `--test-data-dir` (`scripts/smoke_test.py:138-144`; thiếu thì `REFUSED`, mã thoát 2).

Lint: **chưa cấu hình** trong dự án (không có ruff / eslint) – không báo là "đạt".

## 3. Phép tái lập (reproduction) số dự báo

Dùng để chứng minh code cho đúng số đã công bố / đã backtest của một ngày quá khứ, **chỉ trên bản sao DB**:

1. Sao chép DB bằng SQLite backup API (nguồn mở `mode=ro`), đặt file `copy_info.json` vào thư mục DB của bản sao.
2. `DF_DATA_DIR=<bản sao>`, `DF_DISABLE_SCHEDULER=1`, `LOCALAPPDATA` riêng.
3. `python -m app.cli sel2-replay --from D --to D --out <thư mục kết quả> --yes` (lệnh từ chối nếu thư mục DB không có
   dấu bản sao, trừ khi có `--copy-ok`). Kết quả là parquet của 6 ứng viên, lựa chọn SEL2 và số công bố; không công bố
   gì vào DB.
4. So sánh với số đã công bố (`forecast_refresh_values`) hoặc với kết quả backtest.

Kết quả đã có (D3, 03/11/2026, trên bản sao, code 1.4.0; phần tính SEL2 không đổi ở 1.4.1 / 1.4.2): ngày 15/07/2026
(103.502 dòng) và 15/10/2026 (104.307
dòng) – sai khác lớn nhất **0,0**, `model_used` lệch 0 dòng, cả 6 ứng viên sai khác 0,0. Bộ dữ liệu của phép thử là dữ
liệu thật nên không kèm trong gói.

## 4. Tiêu chí đạt (trước khi phát hành / triển khai)

* Backend: 0 test lỗi (`failed`/`error` = 0); số `skipped` chỉ gồm các test cần fixture dữ liệu thật hoặc điều kiện
  môi trường đã biết.
* Frontend: `npm test`, `npm run typecheck`, `npm run build` đều thoát 0.
* Smoke test: mọi dòng `PASS`, mã thoát 0.
* `python -m app.cli data-check` trên DB đích: không có ERROR.
* Mọi thay đổi dữ liệu / migration: thử trên bản sao DB, so số dòng / số khoá trước-sau (`AGENTS.md` mục 4).
* Không làm yếu hay xoá test để cho qua.

## 5. Kết quả cài thử gói 1.4.3 – điền sau

**CHỖ ĐIỀN (bên giao điền sau khi cài thử):** kết quả cài thử gói `DemandForecast-1.4.3-ban-giao-20261105` – môi
trường, loại bằng chứng, bảng các bước, số test đạt / lỗi / bỏ qua, `/api/health` trả `1.4.3`; xuất thử trên bản sao DB thật theo quy tắc mới; kiểm 0 dòng sai quy tắc.

### 5.1 Tham khảo: kết quả cài thử gói bàn giao 1.4.0 (04/11/2026)

Các con số dưới đây là của gói 1.4.0 (cùng ngày), giữ lại để đối chiếu; không phải kết quả của gói 1.4.3.

**Môi trường.** Windows 11 Pro x64, 16 GB RAM, 12 luồng CPU; Python 3.14.7 (py launcher), Node 24.18.0, npm 11.16.0.
Đây là máy đang chạy production nên mọi bước chạy **cô lập**: `LOCALAPPDATA` riêng, thư mục dữ liệu riêng, cổng 8799
(gói cài sẵn) / 8798 (mã nguồn), `DF_DISABLE_SCHEDULER=1` (trừ một lần kiểm scheduler ghi bên dưới), không tạo
shortcut (`-NoShortcuts`). Trước và sau khi thử: production trả `/api/health` 1.4.0, SHA-256 của `storage.json` và
`current.txt` không đổi, không tác vụ nào bị sửa. Không có Windows Sandbox / máy Linux / Docker để thử ⇒ phần Linux và
Docker **chưa kiểm thử**.

Loại bằng chứng: cài đặt thật + unit / tích hợp với BigQuery giả + chạy app thật với dữ liệu **DEMO** (tổng hợp). Không
dùng BigQuery thật, không dùng dữ liệu thật.

| # | Bước (theo tài liệu) | Kết quả |
|---|---|---|
| 1 | Giải nén ZIP bàn giao, đối chiếu `SHA256SUMS.txt` | 388 / 388 file khớp |
| 2 | CAI_DAT B1–B2: venv Python 3.14 mới, `pip install -r requirements.lock.txt` + `requirements-dev.txt` | Đạt (≈ 5 phút). **Lần đầu lỗi** khi giải nén vào thư mục dài ≈ 150 ký tự: pip thiếu file vì vượt giới hạn 260 ký tự của Windows → đã thêm cảnh báo "giải nén vào đường dẫn ngắn" (CAI_DAT mục A1); làm lại ở đường dẫn ngắn thì đạt |
| 3 | CAI_DAT B3: `npm ci` | Đạt (33 s) |
| 4 | Gói cài sẵn – CAI_DAT A1–A4: giải nén, `install.ps1 -NoShortcuts -NoStart`, `start.ps1`, `/api/health`, `check-env.ps1` | Đạt: cài 62 s, khởi động 11 s, health `1.4.0`, check-env `KET QUA / RESULT: OK` |
| 5 | Gói cài sẵn – smoke test `--phase full` (khoi_tao_lan_dau mục 0.3): DEMO, học + công bố LightGBM, dự báo 7/15/30 ngày, xuất Excel, D0 DEMO, nhập Excel, chặn CSV, chặn BigQuery chưa xác minh, sao lưu | **24 / 24 PASS** (53 s). **Lần đầu bị từ chối** vì tài liệu thiếu `--test-data-dir` (chốt an toàn của smoke test) → đã sửa tài liệu |
| 6 | Gói cài sẵn – dừng (`stop.ps1`), khởi động lại, `--phase after-restart` | 3 / 4 PASS với `DF_DISABLE_SCHEDULER=1` (mục "scheduler running" cố ý tắt); chạy lại với scheduler bật: **4 / 4 PASS** |
| 7 | Gói cài sẵn – mở giao diện (Edge headless) | Đạt – ảnh [anh/cai_thu_du_bao_hang_ngay_demo.png](anh/cai_thu_du_bao_hang_ngay_demo.png) |
| 8 | Mã nguồn – `pytest` backend | Lần 1: dừng ở bước thu thập test (thiếu `pyarrow`, không có trong file requirements) → đã ghi vào CAI_DAT B2. Lần 2 (sau `pip install pyarrow==26.0.0`): **1.493 passed, 2 failed, 77 skipped** (25,5 phút trên máy đang chạy production). 2 test lỗi do chính bước che tên sản phẩm thật trong fixture của gói bàn giao; đã sửa cách che, chạy lại file đó: **13 / 13 passed** ⇒ 0 test lỗi |
| 9 | Mã nguồn – frontend `npm test` | **29 file, 193 / 193 test đạt**; chạy lại `v124.test.tsx` sau khi sửa cách che: 6 / 6 |
| 10 | Mã nguồn – `npm run typecheck`, `npm run build` | Đạt; bản build tạo `index-3c3awUCN.js` **trùng tên băm** với giao diện trong gói production ⇒ build tái lập được |
| 11 | Mã nguồn – CAI_DAT B4: `check-env`, `serve --port 8798`, smoke `full` / `after-restart` | Health `1.4.0`; smoke **24 / 24 PASS**; after-restart 3 / 4 (cùng lý do scheduler tắt) |
| 12 | Mã nguồn – giao diện | Đạt – ảnh [anh/cai_thu_tong_quan_demo.png](anh/cai_thu_tong_quan_demo.png) (dự báo LightGBM DEMO đã công bố) |

77 test bỏ qua gồm: cần fixture dữ liệu thật SEL2 (không kèm), cần BigQuery thật (`DF_REAL_BQ=1`), cần
`scripts\remote` (không kèm), test thủ công / tiền đồng bộ, tên ngắn 8.3 không có trên ổ.

**Chưa kiểm trong lần cài thử này** (cần làm ở môi trường của đội tech):

* Luồng **SEL2 đầu-cuối** (học 3 mô hình, 6 ứng viên, chọn, file Excel `du_bao_*.xlsx`) cần dữ liệu BigQuery thật + giờ
  mở bán; trên DEMO không chạy. Bằng chứng hiện có: unit test SEL2 với dữ liệu tổng hợp (trong 1.493 test đạt) và phép
  tái lập D3 trên bản sao DB production (mục 3).
* Kết nối BigQuery thật, `bq-check`, `khoi_tao_lan_dau.md` mục 1–11.
* `Install.bat` bản đầy đủ (có shortcut, autostart) trên máy sạch – đã chạy `install.ps1` với `-NoShortcuts -NoStart`
  để không đụng production.
* Linux / systemd / Docker.

**Sửa tài liệu sau cài thử:** đường dẫn ngắn (CAI_DAT A1), `pyarrow` (CAI_DAT B2, mục 2 ở trên), `--test-data-dir` và
ghi chú scheduler (khoi_tao_lan_dau mục 0.3), che tên sản phẩm trong 2 test.
