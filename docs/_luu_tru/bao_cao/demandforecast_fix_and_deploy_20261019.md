# Demand Forecasting 1.2.8: sửa các vấn đề tồn đọng và triển khai có kiểm soát tối 19/10/2026

> **Cập nhật 19/10/2026 23:15 — trạng thái cuối: DEPLOYED_AND_VERIFIED (1.2.6 → 1.2.8, 20:02:50–20:08:24).**
> Báo cáo này được viết lúc 19:50, khi lần thử đầu bị chặn ở Gate 2. Sau đó chủ hệ thống cho phép khởi động lại link
> xem từ xa (19:53) và lần deploy thứ hai chạy đủ các cổng rồi thành công. Phân biệt bốn trạng thái:
>
> | Thời điểm | Trạng thái | Bằng chứng |
> |---|---|---|
> | 19:41 (trước deploy) | **BLOCKED** ở Gate 2: tunnel bị Cloudflare xóa khi máy ngủ; không có gì được ghi | `p15\state\launcher.log` dòng `STOP (33)`; mục D bên dưới (giữ nguyên) |
> | 20:02–20:08 (deploy) | **DEPLOYED**: `deploy-upgrade` exit 0 trong 334,6 s, không retry | `launcher.log`, `deploy_run.txt`, log `logs\runtime\deploy-20261019-200306.log` |
> | 20:51–20:53 (hậu kiểm) | **VERIFIED**: 14/15 PASS; mục FAIL là dương tính giả (xem mục F) | `p15\state\post128_console.txt`, `post128.json` |
> | Còn tồn tại | Các giới hạn ở mục F.4 | — |
>
> Chi tiết ở **mục F**. Các mục A–E bên dưới giữ nguyên nội dung lúc 19:50 làm lịch sử, không viết lại.

**Trạng thái lúc 19:50 (lịch sử, đã được thay bằng mục F): BLOCKED.** Gate 2 (sức khỏe production) FAIL lúc 19:41:34 vì **link xem từ xa đã mất**: Cloudflare
đã xóa Quick Tunnel trong lúc máy ngủ (standby 18:41–19:12). Phục hồi cần khởi động lại tunnel, tức thay đổi tunnel, nằm
ngoài quyền của task. **Production giữ nguyên 1.2.6, không có thao tác ghi nào**: chưa tạo backup, chưa gọi
`deploy-upgrade`, chưa dừng gì. Gói 1.2.8 vẫn sẵn sàng (xem mục D).

Thời gian: 15:15 – 19:50 ngày 19/10/2026, giờ Asia/Ho_Chi_Minh (Windows "SE Asia Standard Time", UTC+07:00).

Phiên bản 1.2.8 = mọi thay đổi của 1.2.7 (bản đã đóng gói nhưng chưa từng triển khai) cộng các sửa của lượt này.

**Kết quả từng hạng mục:**

| # | Hạng mục | Kết quả |
|---|---|---|
| A1 | Dung lượng ổ đĩa | **Đã xử lý.** Ổ C: trống 10,2 GB → 43,4 GB. Chỉ xóa bản sao tạm của chính các phiên làm việc |
| A2 | Trang Tổng quan | **Đã xử lý trong 1.2.7, nằm trong 1.2.8.** Status 21–24 s → 1,6 s trên gói chính thức |
| A3 | Trang Kết quả dự báo | **Đã xử lý.** Thẻ accuracy 4,6–26 s → 0,05–0,13 s; race khi đổi khoảng dự báo |
| A4 | Modal "Xem cách tính" | **Đã xử lý.** Hết chờ vô hạn; lần đầu 125 s → 37–70 s; mở lặp 77,6 s → 1,5–3,3 s; timeout 180 s và nút thử lại |
| A5 | Dự báo số nguyên | **Một phần.** Đã làm: trang Kết quả, Tổng quan, API, Excel và modal. Trang Lịch sử forecast & thực tế chờ quyết định nghiệp vụ |
| A6 | Feature thứ trong tuần | **Đã xử lý.** Công tắc riêng `feature_weekday` trong UI và backend |
| A7 | `total_open_hours` bắt buộc | **BLOCKED.** Thiếu định nghĩa nghiệp vụ, cần migration và nạp lại D-1 |
| A8 | Mapping mọi cột D-1 | **BLOCKED.** Cần quyết định nơi lưu, đổi truy vấn D-1 và nạp lại |

---

## A. Kết quả sửa lỗi

### Môi trường đo

- Bản sao DB production lúc 13:32, lấy bằng SQLite backup API với nguồn mở `mode=ro` (`scratchpad\r7`).
- Backend chạy trên cổng 8894 với `DF_DISABLE_SCHEDULER=1`; dữ liệu và `LOCALAPPDATA` cách ly.
- Cùng máy với production, nên production chạy song song trong lúc đo.
- So sánh trước và sau trong cùng phiên đo:
  - "trước" = mã 1.2.7, xuất bằng `git archive ad9505c`;
  - "sau" = mã 1.2.8.
- Diễn tập dùng gói chính thức trên bản sao lúc 16:13 (`scratchpad\r8`).

Script và kết quả nằm trong `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\`:
- `p13\` (bench, `exbench.py`, `apit.py`, kiểm kê đĩa, script dọn);
- `p14\` (diễn tập);
- `p15\` (launcher deploy, hậu kiểm).

### A1. Dung lượng ổ đĩa

**Kiểm kê trước** (15:43, chỉ đọc, `p13\disk_audit_before.json`):

| Vị trí | Dung lượng | Phân loại |
|---|---|---|
| Ổ C: | trống **10,2 GB** / dùng 364,6 GB | — |
| Ổ D: | trống 76,4 GB | — |
| Scratchpad của các phiên Claude (`%TEMP%\claude\…\scratchpad`) | **42.658 MB**, 344.705 file | Bản sao **tạm** tái tạo được: bản sao DB production (525 file, 24,95 GB), zip backup của bản sao và bản copy gói (71 file, 2,76 GB), bản cài diễn tập, gói giải nén, `.venv` và `node_modules` sao chép, bản copy model (70 cây, 9,65 GB) |
| `backups\` của dự án | 1.567,8 MB, 50 zip | **Cần giữ** (backup production) |
| `dist\` | 1.269,7 MB | **Chưa đủ căn cứ để xóa trong lượt này.** Gói cũ: kế hoạch `prune-artifacts` (chạy thử) đề xuất bỏ khoảng 1 GB, nhưng chính sách là chỉ giữ bản đang chạy cộng một bản rollback, và chủ sở hữu quyết định |
| `data\runtime` (DB 613 MB, model 18 MB) | 631 MB | **Cần giữ** |
| `.venv` 434 MB, `frontend\node_modules` 120 MB | 554 MB | Tái tạo được nhưng cần cho build; giữ |
| `logs\`, `reports\`, `checkpoints\` | 1,1 / 8,4 / 9,1 MB | **Cần giữ** (audit) |
| `__pycache__` trong `backend\` | 4 MB | Tái tạo được; quá nhỏ, giữ |
| Các bản đã cài `%LOCALAPPDATA%\Programs\DemandForecast` 1.0.0–1.2.6 | 4.795 MB (17 bản × khoảng 282 MB) | **Chưa đủ căn cứ để xóa.** Bản đang chạy cộng bản rollback là bắt buộc; các bản cũ do chủ sở hữu quyết định |
| Phần khác trên C: (không thuộc ứng dụng) | ví dụ `%TEMP%\odis_download_dest` 3 GB, `Rar$EXa…` 2,1 GB, nhiều file `ns*.tmp` | Không phải của ứng dụng; **không động tới** |

Ổ C: giảm từ 23,4 GB lúc 14:18 xuống 10,2 GB lúc 15:43. Scratchpad chỉ tăng 1 MB trong khoảng đó, nên phần giảm đến từ các chương trình khác trên máy.

**Đã dọn:** chỉ scratchpad của phiên, bằng script `p13\scratch_cleanup.py`. Script chạy thử trước rồi mới `--apply`; nó từ chối mọi đường dẫn ngoài scratchpad.
- Đã xóa: bản sao DB (`*.db`, `-wal`, `-shm`), zip và cây chương trình hoặc gói giải nén.
- Giữ lại: mọi script, JSON kết quả, log, CSV và văn bản (bằng chứng được dẫn trong các báo cáo).
- Không xóa thư mục đang dùng (`r7`, `p11`, `p12`, `p13`).
- Trước khi xóa đã kiểm: không có tiến trình nào dùng các file này.
- Kết quả: 666 mục, **0 lỗi**.

**Sau** (16:27): **ổ C: trống 43,4 GB**, scratchpad 7.248 MB. Phần còn lại chủ yếu là hai môi trường của lượt này: bench `r7` và diễn tập `r8`, sẽ dọn sau deploy.
- Không xóa DB, model, backup, log hay cấu hình production nào.
- Không đổi chính sách lưu giữ.

### A2. Trang Tổng quan

**Nguyên nhân** (đã sửa trong 1.2.7, chưa từng lên production):
- `system_status()` đọc lại từng dòng `demand_daily` qua index khóa;
- trang tính status hai lần.

**Cách sửa:**
- Một lần quét `NOT INDEXED`;
- trang dùng chung status của khung app và đọc `/summary`.
- File: `backend/app/api/ops_routes.py`, `frontend/src/App.tsx`, `frontend/src/pages/Dashboard.tsx`.

**Đo:**

| Phép đo | Trước | Sau |
|---|---|---|
| Benchmark trang 1.2.7 (Edge headless, bản sao): nội dung chính | 60,6 s | 3,5 s |
| Benchmark trang 1.2.7: hoàn tất trang | 60,6 s | 5,3 s |
| Lượt này, gói chính thức: `/api/system/status` | 1.2.6: 21,0 / 24,2 s | 1.2.8: **1,6 / 1,6 s**, cùng giá trị |
| Lượt này, API của trang, cùng phiên, mã 1.2.7 so với 1.2.8 | status 0,74 / 0,74 s; `/summary` 0,47–0,71 s | như nhau (±0,1 s); cách tính số nguyên không làm chậm |

**Lượt này không đổi gì thêm ở trang Tổng quan.** Phần tải chậm còn lại là lần mở đầu tiên khi cache lạnh, khoảng 20 s; muốn giảm cần index mới, tức migration (đề xuất riêng).

### A3. Trang Kết quả dự báo

**Đo baseline** (mã 1.2.7) cho từng API của trang:

| API | Thời gian |
|---|---|
| danh sách run | 0,01–0,18 s |
| chi tiết run | 0,15–1,9 s |
| `/summary` | 0,5–1,9 s |
| `/values` | 0,07–0,22 s |
| **`/accuracy`** | **25,9 s; 13,1 s; 8,0 s; 4,6 s** (trả về 43 byte) |

**Nguyên nhân:** SQLite chọn `demand_daily` làm vòng ngoài của phép join (`SEARCH d … order_date<?`). Nó duyệt mọi dòng của scope trước hôm nay, mỗi dòng đọc lại bản ghi, rồi mới dò sang `forecast_values`.

**Cách sửa** (`backend/app/api/forecast_routes.py`):
- `CROSS JOIN` là cùng một inner join, nhưng buộc các dòng của run làm vòng ngoài và dò khóa sang `demand_daily`.
- Đối chiếu trên bản sao với cả 7 run và hai mốc "hôm nay": **số dòng giống hệt**; 8,9–14 s → 0,1–0,8 s.
- WAPE và bias vẫn tính từ `yhat` đã lưu.

**Kết quả:**
- Cùng phiên: `/accuracy` 8,0 / 4,6 s → **0,053 / 0,048 s**.
- Gói chính thức trong diễn tập: 0,13 s.

**Race khi đổi khoảng dự báo liên tục:** `useAsync` dùng chung (`frontend/src/components/ui.tsx`) giờ có số thứ tự.
- Chỉ request mới nhất được cập nhật dữ liệu, lỗi và trạng thái loading.
- Câu trả lời cũ đến muộn bị bỏ qua.
- Trạng thái loading giữ tới khi câu trả lời mới nhất về.
- Có test: đổi 7 → 15 → 30, các câu trả lời về ngược thứ tự, kết quả luôn là 30.

Không đổi forecast ID, dữ liệu đã publish hay quy tắc chọn model.

### A4. Modal "Xem cách tính"

**Tái hiện trên bản sao** (1.2.7, một chuỗi LightGBM của run `FCR-20261019060524-9DE420`):

| Lần gọi | Thời gian |
|---|---|
| Lần đầu | **125 s** (vượt giới hạn 100 s của link xem từ xa) |
| 3 request cùng lúc (ngày khác của cùng chuỗi) | **77,6 s mỗi request** |
| Đã có cache | **30,7 s** |

**Nguyên nhân thực tế:**
1. Mọi request, kể cả khi đã có cache, đều tính `fingerprint()` của dữ liệu trước. Hàm này dùng `SUM(qty)` và `MAX(loaded_at)` qua index khóa, phải đọc lại từng dòng: **42,6 s** trên 1,35 triệu dòng.
2. Khóa trong `_run_inputs` chỉ bảo vệ bước tra cache, không bảo vệ bước dựng. Nhiều request cùng lúc (mở lại modal, bấm ngày trước/sau) dựng song song cùng một panel (khoảng 40 s, nhiều RAM) và chạy model nhiều lần. Production chỉ còn 1,6–1,9 GB RAM trống, nên dễ rơi vào swap; điều này khớp với triệu chứng chờ hơn 30 phút.
3. Frontend gọi `fetch` không có timeout, nên chờ vô hạn nếu backend không trả lời.

**Cách sửa:**

| File | Thay đổi |
|---|---|
| `backend/app/data/demand.py` | `fingerprint()` quét `NOT INDEXED` một lần: 42,6 s → 0,87 s. **Cùng giá trị băm**, trùng `data_fingerprint` đã lưu của lần huấn luyện mới nhất (`f60af410c76acef6`). Mọi `qty` là số nguyên (0 dòng lẻ), nên tổng chính xác bất kể thứ tự. Nếu một scope có số lẻ, hàm tự dùng lại đúng câu lệnh cũ theo thứ tự khóa, nên giá trị băm luôn như trước. Lợi ích thêm cho huấn luyện và kiểm tra promote. Đánh đổi: scope DEMO nhỏ 0,06 s → 1,8 s, chỉ khi DEMO là nguồn đang dùng |
| `backend/app/ml/explain.py` | Mỗi lúc chỉ **một** lần tái tạo (`_build_lock`); request đến sau chờ rồi dùng cache. Đọc cache có khóa riêng, nên request đã có cache trả lời ngay. Không tính lại hay publish gì |
| `frontend/src/api.ts` | `get(path, { timeoutMs, signal })` hủy request quá hạn bằng lỗi `REQUEST_TIMEOUT` song ngữ. Không truyền tùy chọn thì request y như cũ (có test) |
| `frontend/src/pages/ExplainPanel.tsx` | Timeout `EXPLAIN_TIMEOUT_MS` = 180 s, kèm thông báo "lần đầu có thể mất 1–2 phút". Lỗi hiện rõ và có nút **Thử lại**. Đóng modal hoặc chọn ngày khác thì **hủy** request cũ và bỏ qua câu trả lời đến muộn. Thử lại chỉ khi người dùng bấm, không tự retry |

**Kết quả trên bản sao** (mã 1.2.8, cùng chuỗi, cùng phiên):

| Lần gọi | Trước | Sau |
|---|---|---|
| Lần đầu | 125 s | **69,9 s** |
| 3 request cùng lúc | 77,6 s mỗi request | **3,3 s** |
| Đã có cache | 30,7 s | **2,45 s** |

Trên gói chính thức trong diễn tập: lần đầu **37,5 s**, ngày kế tiếp **1,5 s**.

**Test:**
- Backend: 4 lần gọi đồng thời chỉ dựng panel **1** lần và chạy model **1** lần; tái tạo khớp giá trị đã publish.
- Frontend: thành công, không có dữ liệu (404), backend lỗi (500), timeout (đồng hồ giả, 180 s), đóng modal khi đang chạy, đổi ngày liên tiếp.

### A5. Dự báo theo ngày là số nguyên

**Truy vết luồng:**
- Model trả giá trị thực, đã cắt ≥ 0, rồi lưu `forecast_values.yhat` (REAL).
- Các API `/values`, `/summary` (Kết quả và Tổng quan), Excel và giải thích đều trả `yhat` hoặc tổng của `yhat`, nên hiện số lẻ.
- WAPE và bias (`ml/metrics.py`) tính từ `yhat`.

**Quy tắc duy nhất** (`backend/app/qty.py`): **làm tròn nửa lên của giá trị đã lưu, không nhỏ hơn 0**.
- Python `floor(max(yhat, 0) + 0,5)`; SQL `CAST(MAX(yhat, 0) + 0.5 AS INTEGER)`; test chứng minh hai dạng cho cùng kết quả.
- 2,5 → 3; 2,49 → 2; 0,5 → 1; 0,49 → 0; 0 → 0 (không ép lên 1); số âm → 0. Vì giá trị đã lưu luôn được cắt ≥ 0, nhánh số âm chỉ là chốt an toàn.
- `None` và `NaN` giữ là thiếu.

**Áp dụng:**
- `/values` thêm `forecast_qty`, giữ `yhat` gốc.
- `/summary`: tổng theo ngày, theo chuỗi, theo phương pháp và tổng kỳ đều **cộng từ số nguyên theo ngày**; sắp xếp theo tổng nguyên, thêm khóa phụ SKU/FC.
- Excel của run: sheet theo ngày và sheet tổng.
- Giao diện: bảng và biểu đồ trang Kết quả, thẻ trang Tổng quan, tiêu đề modal. Giá trị thô của model chỉ còn ở khối kỹ thuật của modal, kèm dòng "số lượng hiển thị".

**Không đổi:**
- `yhat` trong DB (test so toàn bộ giá trị trước và sau);
- WAPE, bias, quality gate;
- actual và dữ liệu lịch sử.

**Chưa làm:** trang **Lịch sử forecast & thực tế** và Excel H2 của trang đó. Trang hiển thị forecast cạnh *độ lệch* và *WAPE theo dòng*, cả hai tính từ giá trị đã lưu. Nếu chỉ làm tròn số forecast thì độ lệch hiện ra sẽ không khớp với hai số bên cạnh; còn đổi độ lệch/WAPE sang số nguyên là đổi công thức đánh giá, mà prompt cấm tự ý làm. **Cần anh/chị quyết định.**

**Test:**
- 11 cặp giá trị biên (Python = SQL);
- `None` / `NaN`;
- `/values`, `/summary`, Excel (theo ngày và tổng) và tiêu đề giải thích khớp nhau trên một run thật có giá trị lẻ;
- DB không đổi.

`test_v111.py` cập nhật: Excel trả **đúng số nguyên hiển thị** thay cho số gốc. Kiểm tra chặt hơn, không phải nới lỏng.

### A6. Feature thứ trong tuần cấu hình được

**Hiện trạng:**
- `dow` (0 = Thứ Hai) và `is_weekend` đã có sẵn, nằm chung công tắc `feature_calendar`, và công tắc này không hiện trong UI.
- Giá trị lấy từ **ngày dự báo**: với lịch sử là `order_date` (ngày Việt Nam, lấy từ cột `created_date` đã ánh xạ ở production); với tương lai là ngày mục tiêu.
- Không dùng thời điểm tạo bản ghi.
- `order_date` là `NOT NULL`; dòng thiếu hoặc sai ngày đã bị loại ở bước nhập và validation hiện có.

**Cách sửa:**

| File | Thay đổi |
|---|---|
| `settings_service.py` | `ModelSettings.feature_weekday: bool \| None = None`. `None` (mọi cấu hình trước 1.2.8) = đi cùng nhóm Lịch như cũ |
| `ml/features.py` | `weekday_on()` và `calendar_names()` dùng chung cho tên feature, `features_at` (huấn luyện, backtest, dự báo đệ quy) và `direct_extra` (DIRECT). Khi cả hai công tắc bật, thứ tự cột giống hệt trước |
| `feature_registry.py` | `dow` và `is_weekend` gắn công tắc `feature_weekday` |
| `pipeline.py` | Ghi công tắc vào `settings_switches` của lần huấn luyện |
| `Config.tsx`, `i18n.tsx` | Ô "Thứ trong tuần" trong Cấu hình, mô tả rõ ngày nguồn |

Không có dữ liệu tương lai rò vào feature: thứ là thông tin lịch biết trước.

**Tương thích:**
- Model đang dùng và model cũ giữ đúng danh sách feature. Test so với chính hàm của 1.2.7 cho cả RECURSIVE và DIRECT, kể cả cấu hình lưu trước 1.2.8.
- Đổi công tắc chỉ có hiệu lực từ lần huấn luyện **kế tiếp**.
- Production chưa lưu khóa này, nên lần huấn luyện 09:00 ngày 20/10 dùng **đúng** bộ feature như hôm nay.

**Test:**
- Thứ của ngày biên năm và tháng (31/12/2026 = 3, 01/01/2027 = 4, 02/01/2027 = 5, 03/01/2027 = 6, 28/02/2026 = 5, 01/03/2026 = 6, 02/03/2026 = 0);
- tắt công tắc, hoặc chỉ bật riêng công tắc thứ;
- huấn luyện DEMO với công tắc tắt: danh sách feature của run không có `dow`, và giải thích tái tạo **đúng** giá trị đã publish (dự báo dùng cùng danh sách với huấn luyện);
- registry;
- UI.

### A7. `total_open_hours` thành feature bắt buộc: **BLOCKED**

Đã xác minh (chỉ đọc):
- Cột nguồn `total_open_hours` đã ánh xạ làm cột **tham chiếu** `open_hours` (OPTIONAL).
- Registry báo `DISABLED / HAS_SOURCE_DATA_NOT_ACTIVATED`: nguồn có dữ liệu nhưng chưa có quy tắc tổng hợp hoặc quy tắc giá trị thiếu được duyệt.
- `demand_daily` **không có** cột này; D-1 không lưu nó.

**Thiếu để làm đúng nghĩa:**
1. **Định nghĩa nghiệp vụ:** "giờ mở bán của SKU tại kho trong ngày" có giống nhau trên mọi dòng đơn của SKU × FC × ngày không, và tổng hợp bằng MAX, trung bình hay giá trị đầu tiên.
2. **Giá trị cho ngày tương lai:** khi dự báo không biết số giờ mở của ngày mục tiêu. Có thể dùng giá trị hôm trước, giờ kế hoạch, hoặc giả định đủ giờ; mỗi cách là một quyết định chống rò rỉ.
3. **Lưu trữ:** cần migration thêm cột hoặc bảng, và **nạp lại toàn bộ D-1** từ BigQuery để có lịch sử. Cả hai đều bị cấm trong lượt này.
4. **Tác động:** nếu đánh dấu bắt buộc trước khi có dữ liệu, lần huấn luyện 09:00 sẽ bị chặn.

Không bịa công thức hay giá trị.

### A8. Mapping mọi cột D-1 theo vai trò: **BLOCKED**

**Hiện trạng:**
- Mapping gồm 14 trường nội bộ (khóa, ngày, mục tiêu, giá…) và 11 trường tham chiếu, kiểm tra kiểu theo `COMPATIBLE` / `REF_COMPATIBLE` (`bq/connector.py`).
- Production ánh xạ 6 trường nội bộ và 10 trường tham chiếu.

**Thiếu:**
- Nơi lưu giá trị của cột tùy ý theo ngày: bảng mới hoặc cột mới (migration).
- Truy vấn D-1 phải đọc thêm các cột đó, tức đổi truy vấn nguồn production, và cần nạp lại lịch sử.
- Quy tắc tổng hợp và chống rò rỉ cho từng cột trước khi dùng làm feature.

Làm phần UI mà backend không dùng tới thì không đạt yêu cầu "không chỉ sửa giao diện". Đề xuất thiết kế làm batch riêng: bảng vai trò cột (khóa / mục tiêu / feature bắt buộc / tùy chọn / tham khảo / metadata / cấm), validation backend dùng chung, migration bổ sung, và nạp lại D-1 có kế hoạch.

### Test (lượt cuối, đúng cây mã được build)

| # | Lệnh | Kết quả |
|---|---|---|
| 1 | `scripts\run-tests.ps1`, trước commit (15:53:11–15:58:19), hash cây `74b9c0f332bbef31` không đổi trong lúc chạy | **exit 0**. Backend **526 passed, 7 skipped**; vitest **20 file, 133/133**; typecheck 0; build 0. Log `logs\development\tests_20261019_155312.log` |
| 2 | `scripts\release.ps1` trên commit `0da73b6` (16:00:21–16:12:26) | **exit 0**. Backend 526 passed / 7 skipped; vitest 133/133; build và kiểm tra gói đạt |

- Test mới: backend `test_v128_fixes.py` (**29**), frontend `v128.test.tsx` (**10**).
- 7 test bị bỏ qua đều cần BigQuery thật (`DF_REAL_BQ=1`); không gọi dịch vụ thật.
- Lint: **NOT CONFIGURED**.
- Cảnh báo: 1 `StarletteDeprecationWarning` (test client) và các cảnh báo React Router trong stderr của vitest. Cả hai đều có sẵn từ trước, không ảnh hưởng release.
- Bộ test có sẵn bao phủ import `.xlsx`, mapping, API và lưu trữ; tất cả đạt.
- Lượt này không chạy huấn luyện hay tạo forecast thật; các test huấn luyện chạy trên dữ liệu DEMO trong thư mục cách ly.

### Rủi ro còn lại

| Mức | Rủi ro | Xử lý |
|---|---|---|
| Medium | Giải thích **lần đầu** của mỗi run vẫn 37–70 s, gần giới hạn 100 s của link xem từ xa khi máy bận | Đã có timeout, lỗi rõ ràng và nút thử lại; lần sau dùng cache. Giảm thêm cần cache dự báo toàn run (batch riêng) |
| Medium | Trang Lịch sử forecast vẫn hiện số lẻ (A5 một phần) | Chờ quyết định về độ lệch và WAPE theo dòng |
| Low | Rollback về 1.2.6 khi đã có model huấn luyện với `feature_weekday=false` và model đó đang được dùng: 1.2.6 không hiểu công tắc này, nên phần giải thích và mở rộng khoảng dự báo của model đó sẽ lệch | Chỉ xảy ra nếu tắt công tắc, huấn luyện, promote rồi rollback. Rollback ngay sau deploy thì không ảnh hưởng (cấu hình chưa lưu) |
| Low | Đọc toàn bảng cho `fingerprint` và status tăng theo tổng số dòng mọi scope | Index phủ `(scope_key, loaded_at)` = migration riêng |
| Low | Lần mở Tổng quan đầu tiên khi cache lạnh khoảng 20 s | Như trên |

---

## B. Git và release artifact

| Hạng mục | Giá trị |
|---|---|
| Nhánh / HEAD trước | `main` / `ad9505c9275a6b39b44d5614e981baed33c019e9`; working tree **sạch**; ahead 25 / behind 0 (ref local, không fetch) |
| Commit mới | **`0da73b6e68dc379cc4498a50f60172ea933572e1`** "Release 1.2.8: explanation timeout and single build, fast Results accuracy, whole-number forecasts, weekday switch" (không amend) |
| File trong commit (22) | `CHANGELOG.md`, `backend/app/__init__.py`, `api/forecast_routes.py`, `data/demand.py`, `ml/explain.py`, `ml/feature_registry.py`, `ml/features.py`, `ml/pipeline.py`, `qty.py` (mới), `settings_service.py`, `tests/test_v111.py`, `tests/test_v128_fixes.py` (mới), `docs/MO-HINH-VA-CHI-SO.md`, `frontend/package.json`, `package-lock.json`, `src/api.ts`, `components/ui.tsx`, `i18n.tsx`, `pages/Config.tsx`, `pages/ExplainPanel.tsx`, `pages/Results.tsx`, `src/v128.test.tsx` (mới). 687 dòng thêm, 52 dòng xóa |
| Stage và quét | `git add --` từng đường dẫn. Quét secret: 0. Quét tên file cấm chỉ trúng `backend/app/data/demand.py`, do mẫu không neo gốc khớp nhầm thư mục mã nguồn `app/data/`, không phải thư mục dữ liệu `/data` |
| Sau | HEAD `0da73b6`, working tree **sạch**, ahead **26** / behind 0. **Không push**; không fetch hay pull |
| Version | 1.2.8 (`__init__.py`, `package.json`, `package-lock.json` ×2) |
| Gói | `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.8-win64-portable.zip`, 92.258.519 byte, build 16:06:31 |
| **SHA-256** | **`E6493895AACCCA1555C7452EA1528606B38347F520F78E55A717A46FB58B9EA2`**. Tự tính bằng `Get-FileHash` = file `.sha256` = `zip_sha256` trong manifest |
| Nguồn gốc | `BUILD-INFO.json`: 1.2.8, commit `0da73b6…`, `dirty=false`, fingerprint `F8C4446E39262172…`. Runtime nhúng: `embedded runtime OK, app 1.2.8 lightgbm 4.7.0` |
| Nội dung | `testzip` sạch; 7.137 file. **119/119** file có trong Git giống hệt từng byte blob của `0da73b6`. 0 file ngoài Git trong `backend/app` hay script, 0 file thiếu. `web/` 3/3 giống bản build của QA. **0 file cấm** (DB, `storage.json`, credential, `.env`, log, backup, model, `__pycache__` / `.pyc` của app). Migrations 0001–0006, giống 1.2.6 |
| Gói cũ | 1.2.6 `0464EEDA…`, 1.2.7 `1351C920…` còn nguyên. Dọn artifact chỉ chạy thử |

**Diễn tập cách ly 1.2.6 → 1.2.8 → 1.2.6: 44/44 PASS** (16:13:17–16:25:49).
- Script `p14\iso128r.ps1`; kết quả `p14\iso128r_result.json`.
- Môi trường: bản sao mới, cổng 8879, scheduler tắt, proxy 8878, không có tunnel, không có job, không dùng Windows task.

| Bước | Kết quả |
|---|---|
| Nâng cấp bằng `deploy-upgrade` | `-CheckOnly` rồi `UPGRADE-1.2.8`: exit 0, **244,6 s**; app không phản hồi **88,8 s**. Backup online được lấy trước bước xác nhận |
| Dữ liệu | Không có migration (schema 6, trigger như cũ). **Mọi bảng giống hệt**, trừ `audit_log` +1. Model và 6 JSON cấu hình giống hệt. data-check vẫn WARN (có sẵn) |
| Lịch | 5 lịch và kế hoạch scheduler giống hệt 1.2.6 |
| Status | Cùng giá trị; 21 / 24,2 s → 1,6 / 1,6 s |
| Proxy | health 1.2.8; ghi 405 ×4; admin 403 ×4; giao diện là bundle mới |
| Tính năng mới | Số nguyên: 500/500 dòng (230 dòng có giá trị lẻ), tổng kỳ = tổng theo ngày. `/accuracy` 0,13 s. Công tắc thứ chưa lưu nên `dow` vẫn ACTIVE. Giải thích 37,5 s, rồi 1,5 s |
| Rollback | `rollback-version -To 1.2.6 -CheckOnly` cho "không cần restore". Rollback thật: **8,8 s**, gián đoạn **3,1 s**, cùng DB; mọi bảng giữ nguyên (không mất dữ liệu ghi trên 1.2.8) |

---

## C. Lịch deploy

**Không tạo Windows Task Scheduler task hay dịch vụ nào.**
- Deploy chạy **trong phiên làm việc** bằng launcher một lần `p15\deploy128.ps1`, theo khung đã duyệt (19:00–22:00, mục tiêu 19:30, sau slot D-0 18:00).
- Không trùng lịch production. Lịch tiếp theo sau 18:00 là backup forecast cuối ngày 23:55 và chốt actual 23:59; D-1 03:00 và D-0 08:00 ngày 20/10. Launcher từ chối nếu slot gần nhất cách dưới 45 phút.
- Launcher **không sửa** `deploy-upgrade.ps1` và **không bỏ qua** bước kiểm tra nào. Nó tự dừng ở cổng đầu tiên không đạt.

| Chế độ | Việc làm |
|---|---|
| `-Mode gates` | Kiểm tra khung giờ, múi giờ và chạy-một-lần. Toàn vẹn gói (SHA, `.sha256`, `VERSION`, `BUILD-INFO`, HEAD = commit, cây sạch, không có file cấm, script deploy = bản trong gói). Production (1.2.6, 3 tiến trình, `/ready`, proxy, `storage.json`). Không job, không slot trong 45 phút, Price bật. Ghi lại bất biến. `deploy-upgrade -CheckOnly` |
| `-Mode backup` | Như trên, rồi gọi `deploy-upgrade` với token **cố ý không khớp**. Script tạo **backup online chính thức** và tự kiểm (`integrity_check`, có `db/app.db`), rồi dừng ở bước xác nhận: "not confirmed - nothing was stopped or installed". Launcher kiểm production vẫn 1.2.6 cùng pid, rồi kiểm backup độc lập bằng `verify_b.py`: SHA bằng giá trị in ra; CRC; `integrity_check`; schema 6; có forecast, huấn luyện, job và audit mới nhất của hôm nay; **đủ file model đang dùng với cùng SHA** |
| `-Mode deploy` | Chỉ chạy khi có backup đã kiểm trong 20 phút gần nhất và chưa tới 22:00. Ghi marker `deploy.started` (**không bao giờ tự chạy lại**). Gọi `deploy-upgrade -ConfirmToken UPGRADE-1.2.8`, token chính thức; script tự tạo thêm backup online trước bước xác nhận. Không retry |

Chạy thử `-Mode gates -PreWindow` lúc 16:26–16:27: **mọi cổng đạt**, CheckOnly exit 0. Chế độ `-PreWindow` chỉ cho phép `gates`.

Bổ sung lúc 19:40, sau khi phát hiện máy đã standby: launcher xin Windows giữ máy thức trong lúc nó chạy
(`SetThreadExecutionState`, chỉ có hiệu lực cho chính tiến trình đó, tự hết khi thoát). Nếu không xin được thì launcher
dừng, mã 14. Không đổi cấu hình nguồn điện của máy.

**Vô hiệu hóa:** không có task nên không có gì phải gỡ. Marker `p15\state\deploy.started` chặn mọi lần chạy lại; launcher tự từ chối ngoài 19:00–22:00 ngày 19/10/2026.

**Lệnh thủ công tương đương** (nếu cần làm tay):

```
scripts\deploy-upgrade.ps1 -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.8-win64-portable.zip" -ExpectedSha256 E6493895AACCCA1555C7452EA1528606B38347F520F78E55A717A46FB58B9EA2 -CheckOnly
```

Sau đó chạy lại không có `-CheckOnly` và gõ `UPGRADE-1.2.8`.

---

## D. Deploy

**Kết quả: BLOCKED. Chưa deploy.** Production trước và sau đều là **1.2.6**. Không có backup mới, không có marker
`deploy.started`, không có transcript deploy.

### Diễn biến

| Giờ | Sự kiện | Bằng chứng |
|---|---|---|
| 18:07 | Slot D-0 18:00 xong (`JOB-20261019110029-D00C27`, SUCCEEDED 18:00:29–18:00:40). Bắt đầu chờ tới 19:24 | `/api/jobs` |
| 18:32:17 | Lần cuối tunnel đăng ký kết nối thành công (edge sin08) | log cloudflared |
| 18:41:31 | Máy vào Modern Standby. Từ 18:41:35 cloudflared báo mạng không tới được | System log Kernel-Power 506; log cloudflared |
| 19:12:51 | Máy thức lại | Kernel-Power 507 |
| 19:12:58 | Cloudflare trả `Unauthorized: Tunnel not found`. Lặp 114 lần tới 19:43, cloudflared tự thử lại vô ích | log cloudflared |
| 19:40 | Phát hiện tác vụ chờ chưa dậy: `Start-Sleep` không tính thời gian standby, nên đã dừng nó. Production 1.2.6 khỏe, không job | health, `current.txt`, pid, `/api/jobs` |
| 19:41:33 | `deploy128.ps1 -Mode backup`: G0 PASS, G1 PASS, **G2 FAIL** (`/ready` của cloudflared trả 503), STOP exit 33 | `p15\state\launcher.log`, `backup_console.txt` |
| 19:42–19:44 | Chẩn đoán chỉ đọc (xem dưới). Xác nhận không có gì được ghi | xem dưới |

Chẩn đoán (chỉ đọc):
- `/ready` trả 503 sáu lần liên tiếp trong một phút.
- Hostname của link trả **NXDOMAIN** trên DNS mặc định, 1.1.1.1 và 8.8.8.8.
- Internet chung bình thường: DNS các tên khác phân giải được, HTTPS tới Cloudflare trả 200.
- Proxy chỉ đọc 8766 vẫn khỏe (`ok`, `upstream: true`).

Quick Tunnel bị Cloudflare xóa là **vĩnh viễn**, chờ thêm không tự hết. Link xem từ xa ngừng hoạt động từ 18:41, độc lập
với việc deploy.

### Các cổng

| Gate | Kết quả | Ghi chú |
|---|---|---|
| 1. Toàn vẹn release | **PASS** 19:41:34 | SHA `E6493895…9EA2` = `.sha256`; VERSION / BUILD-INFO 1.2.8 `0da73b6`, `dirty=false`; HEAD = commit, cây sạch; không file cấm; script deploy = bản trong gói |
| 2. Sức khỏe production | **FAIL** | App 1.2.6, `current.txt`, 3 pid, proxy, `storage.json` và job đều đạt. **Tunnel và link từ xa hỏng**, mà prompt yêu cầu "proxy/tunnel và remote URL hoạt động … Nếu production không khỏe hoặc trạng thái không xác định: dừng" |
| 3. Backup tự động | **Không chạy** | Chỉ chạy sau khi cổng 1, 2, 5 và 6 đạt. Không có backup mới: `backups\` vẫn 50 file, mới nhất `backup-20261018-191344-cli.zip` |
| 4. Sẵn sàng rollback | Không chạy lại tối nay | Diễn tập 16:24: rollback không cần restore (cùng schema 6) PASS |
| 5. Lịch và bất biến | Launcher không chạy tới cổng này | Đã kiểm riêng, chỉ đọc, lúc 19:45: không đổi (mục E) |
| 6. CheckOnly | Không chạy tối nay | Lần chạy thử 16:27 exit 0 |

### Vì sao không tiếp tục

1. Cổng 2 FAIL theo đúng định nghĩa của prompt.
2. Cách sửa duy nhất là khởi động lại tunnel, sẽ ra link mới. Prompt cấm tự ý sửa tunnel/proxy.
3. Không có cách nào bỏ qua cổng mà vẫn đúng yêu cầu. Production được giữ nguyên.

### Việc cần làm tiếp (chủ hệ thống)

1. **Mở lại link xem từ xa**: bấm đúp `Stop-DemandForecast-Remote.bat` rồi `Start-DemandForecast-Remote.bat` (thư mục dự
   án; xem `docs/VAN-HANH.md`). Link sẽ đổi; gửi link mới cho người xem. App không bị dừng.
2. **Deploy 1.2.8**, tối nay hoặc lần sau, chỉ khi được giao lại:
   - Cập nhật trong launcher pid mới của proxy và cloudflared (sau khi kiểm proxy mới đúng là proxy chỉ đọc). Nếu deploy
     ngày khác, cập nhật cả khung giờ.
   - Chạy `-Mode backup` → `-Mode deploy` → `post128.ps1`.
   - Thời gian cần khoảng 15–20 phút: backup và kiểm 3–5 phút, deploy khoảng 4–5 phút (diễn tập 244,6 s, gián đoạn
     88,8 s), kiểm sau deploy 3–5 phút.
   - Tối nay muốn kịp phải bắt đầu trước khoảng **21:30**.
3. **Tránh lặp lại**: đây là lần thứ hai trong ngày link mất sau khi mạng bị ngắt (lần trước 09:39 sáng 19/10). Tắt
   chế độ ngủ của máy chủ, hoặc đổi sang tunnel có tên cố định. Đây là quyết định của chủ hệ
   thống; task này không đổi cài đặt nguồn điện.

---

## E. Xác nhận bất biến

Kiểm chỉ đọc lúc 19:44–19:45, so với bản ghi `p15\state\invariants_gates.json` lúc 16:26.

| Bất biến | Kết quả |
|---|---|
| Version production | 1.2.6; `current.txt` 1.2.6; pid app 13820, proxy 26416, cloudflared 18992 vẫn như cũ |
| D-0 / D-1 / EOD / training | Không chạy lại và không kích hoạt tay. Job mới duy nhất từ 16:26 là D-0 18:00 do **lịch** tự chạy (`JOB-20261019110029-D00C27`, SUCCEEDED). Không có job đang chạy |
| Lịch | 5 lịch có cấu hình giống hệt 16:26. Lần chạy tới: EOD 23:55 và chốt actual 23:59 ngày 19/10; D-1 03:00, D-0 08:00, training 09:00 ngày 20/10 |
| Quality gate, WAPE/bias, SKIP, model, Price | JSON `quality`, `model` và `schedule` giống hệt; `feature_price = true` |
| Model và forecast đang dùng | `FCR-20261019060524-9DE420` từ `TRN-20261019043033-A761C1` (ACCEPTED, `MV-20261019-120018-61C1`), như 16:26 |
| Nguồn dữ liệu | BIGQUERY, không đổi |
| `storage.json` | SHA-256 `8D79DBDD…E047`, không đổi |
| Schema / migration | Không chạy migration nào (`deploy-upgrade` không được gọi tối nay) |
| Backup, dữ liệu, log | Không xóa gì; `backups\` vẫn 50 file |
| Tunnel / proxy | Không động vào. Cloudflared vẫn chạy cùng pid và tự thử lại; link mất do Cloudflare (mục D) |
| Audit | Bản ghi mới nhất 18:00:40 của job D-0. Phiên này không tạo bản ghi nào |
| Git | HEAD `0da73b6`, cây sạch, ahead 26. **Không push** |
| Tác vụ nền | Không tạo scheduled task. Tác vụ chờ đã dừng; không còn tiến trình launcher nào |

---

## F. Cập nhật sau triển khai (bổ sung 19/10/2026 23:15, chỉ ghi lại bằng chứng có sẵn)

### F.1 Diễn biến sau 19:50

| Giờ | Sự kiện | Bằng chứng |
|---|---|---|
| 19:53 | Chủ hệ thống cho phép khởi động lại link xem từ xa. `remote-access.ps1 stop` rồi `start`: link mới `https://communications-letters-glance-occasions.trycloudflare.com`, proxy pid 16144, cloudflared pid 35236. App 1.2.6 (pid 13820) không bị dừng | `p15\state\remote_stop.txt`, `remote_start.txt` |
| 19:56:25–20:01:49 | `deploy128.ps1 -Mode backup`: G0, G1, G2, G5 PASS; G6 CheckOnly exit 0; backup chính thức `backup-20261019-195719-manual.zip` (SHA-256 `8ABBBE68…5665`), kiểm độc lập: integrity ok, schema 6 | `launcher.log`, `backup_verify.json` |
| 20:02:32–20:02:49 | `-Mode deploy`: kiểm lại G0, G1, G2, G5, G6, tất cả PASS | `launcher.log` |
| 20:02:50 | `deploy-upgrade -ConfirmToken UPGRADE-1.2.8`. Script tự tạo backup `backup-20261019-200306-manual.zip` (SHA-256 `02F00EFF…B4F4`) trước bước xác nhận; bản cài tạo thêm `backup-20261019-200655-cli.zip` | `deploy_run.txt` |
| 20:08:24 | `deploy-upgrade` exit 0 sau 334,6 s, không retry. Migration: không có (schema 6 → 6). App mới pid 10884 chạy từ thư mục 1.2.8 | `deploy_run.txt`, `launcher.log`, `deploy.finished` |
| 20:51–20:53 | Hậu kiểm `post128.ps1`: 14/15 PASS | `post128_console.txt`, `post128.json` |

### F.2 Hậu kiểm

PASS: version 1.2.8 (health, `current.txt`, tiến trình); proxy và cloudflared giữ nguyên, `/ready` 200; link HTTPS từ
xa (health 1.2.8, admin 403, ghi 405); `storage.json` không đổi (`8D79DBDD…`); cài đặt quality gate, lịch, model
không đổi; 5 lịch không đổi; model đang dùng và forecast đã publish không đổi (`FCR-20261019060524-9DE420`); không job
nào chạy do deploy; data-check không có FAIL (schema 6); API Tổng quan / Kết quả trả lời (status 1,6 s); số lượng dự
báo là số nguyên; công tắc thứ có mặt nhưng chưa lưu; "Xem cách tính" lần đầu 2,96 s; backup trước nâng cấp của script
được kiểm lại (SHA, CRC, integrity, dữ liệu hôm nay, model).

FAIL duy nhất, "không có ERROR mới trong log runtime", là **dương tính giả**. Kiểm lại lúc 23:12 (chỉ đọc
`logs\runtime\app.log`): cả 6 dòng `ERROR` đều có trước khi deploy bắt đầu (13:02:50 UTC):
- 3 dòng `scheduler tick failed` ngày 16/10;
- 3 dòng `job failed SOURCE_INCOMPLETE` của D-1 lúc 17/10 23:08 UTC, 18/10 22:09 UTC và 19/10 03:21 UTC.

Từ lúc deploy tới lúc kiểm: **0** dòng ERROR mới. `server.err.log` 0 byte.

### F.3 Trạng thái production lúc 23:11 (chỉ đọc)

- `GET /api/health`: `{"ok": true, "version": "1.2.8"}`; `current.txt` = 1.2.8.
- Job mới nhất vẫn là `JOB-20261019110029-D00C27` (D-0 18:00, SUCCEEDED). Không có job nào đang chạy.
- Rollback về 1.2.6: `scripts\rollback-version.ps1 -To 1.2.6`, không cần restore vì cùng schema 6. Diễn tập trước deploy: 8,8 s.

### F.4 Giới hạn còn tồn tại sau deploy

| Hạng mục | Trạng thái |
|---|---|
| A5: trang Lịch sử forecast & thực tế vẫn hiện số lẻ | Còn trên production 1.2.8. Đã sửa trong mã nguồn 1.2.9 (chưa commit, chưa deploy); xem `reports/demandforecast_comprehensive_upgrade_review.md` |
| A7 / A8: `total_open_hours` bắt buộc, vai trò cột D-1 | Đã làm trong mã nguồn 1.2.9 (`reports/weekday_total_open_hours_mapping_fix.md`); chưa deploy; cần migration 0007, quyết định nghiệp vụ và backfill có kiểm soát |
| Link xem từ xa | Quick Tunnel đổi URL mỗi lần khởi động lại và mất khi máy ngủ (hai lần ngày 19/10). Muốn ổn định cần tắt chế độ ngủ hoặc dùng tunnel có tên cố định: quyết định của chủ hệ thống |
| "Xem cách tính" lần đầu khi máy bận | Vẫn có thể 37–70 s; đã có timeout, nút thử lại và cache |
| Công tắc thứ trong tuần | Có trên 1.2.8 nhưng chưa được lưu; model đang dùng vẫn có `dow` như trước |
| Tác vụ nền của phiên deploy | Tiến trình app 10884 giữ handle của pipe; tác vụ công cụ hiện "running" nhưng không làm gì. Không được dừng tác vụ đó, vì dừng có thể làm dừng app |
