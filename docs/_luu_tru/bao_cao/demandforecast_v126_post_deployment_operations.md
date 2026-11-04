# Demand Forecasting 1.2.6: hậu triển khai, hiệu năng trang Tổng quan và dọn dẹp an toàn

**Trạng thái kết thúc: `OPTIMIZED_AND_TESTED_LOCAL`.**

Nguyên nhân trang Tổng quan chậm đã được xác định bằng đo đạc. Bản sửa đã làm và test trên mã nguồn local cùng một bản sao cách ly của DB production. Bản sửa **chưa** được đóng gói, commit hay đưa lên production. Production không bị thay đổi gì trong task này, ngoài việc gỡ task triển khai một lần đã hoàn tất.

Còn một giới hạn: lần mở đầu tiên sau một thời gian máy để nhàn rỗi (cache hệ điều hành đã bị đẩy ra) vẫn mất khoảng 17 s trên bản sao. Muốn giảm thêm phải đổi schema, nằm ngoài phạm vi an toàn (xem mục D7). Hiệu quả trên production chỉ đo được sau khi bản sửa được phê duyệt và triển khai.

Phát hiện mới, nằm ngoài bản sửa: **link xem từ xa đã chết từ 09:39 ngày 19/10** vì Cloudflare xóa Quick Tunnel sau khi máy mất mạng (mục A4).

Kiểm tra từ 08:40 đến 10:20 ngày 19/10/2026, giờ máy `SE Asia Standard Time` (UTC+07:00, trùng giờ Việt Nam).

Quy ước trong các bảng:

| Ký hiệu | Nghĩa |
|---|---|
| `PASS` | Đã kiểm tra, đạt |
| `FAIL` | Đã kiểm tra, không đạt |
| `UNKNOWN` | Có kiểm tra nhưng chưa đủ bằng chứng để kết luận |
| `NOT_CHECKED` | Chưa kiểm tra, có nêu lý do |
| `NOT_DUE` | Chưa tới giờ chạy |
| `NOT_RUN` | Không chạy (có nêu lý do) |

## A. Hậu triển khai (chỉ đọc)

Production được kiểm tra hai lần, lúc 08:42 và 10:18. Script kiểm tra nhẹ `verification/prod_light.ps1` (trong thư mục bằng chứng) **không** gọi `/api/system/status` và **không** chạy `data-check`, để không gây tải lên production.

### A1. Phiên bản, tiến trình, cấu hình

| Kiểm tra | Kết quả | Trạng thái |
|---|---|---|
| Phiên bản | `/api/health` = 1.2.6, `current.txt` = 1.2.6, app pid 13820 chạy từ `...\Programs\DemandForecast\1.2.6\` (khởi động 18/10 19:15:46) | PASS |
| `storage.json` | SHA-256 `8D79DBDD…E047`, không đổi | PASS |
| Proxy 8766 (pid 26416) | Health 200, version 1.2.6. Trang quản trị trả 403; POST/PUT/DELETE trả 405 (kiểm tra cục bộ lúc 08:42 và 10:18) | PASS |
| Link công khai | 08:42: health 200, 403 / 405 như mong đợi. **10:18: tên miền không còn tồn tại** (mục A4) | FAIL (từ 09:39) |
| Scheduler | `running=true`, nạp đủ năm flow d1, d0, train, eod, close; tick gần nhất 10:18:17 | PASS |
| Lịch D-1 / D-0 / huấn luyện | 03:00 + fallback 05:00 + poll 30 phút / 08:00–18:00 mỗi 2 giờ, `LATEST_ONCE` / 09:00 `SKIP`. Không đổi; `enabled_at` vẫn như cũ | PASS |
| Hai lịch mới | eod `ON` 23:55, close `ON` 23:59, `Asia/Ho_Chi_Minh`, `REGISTERED`, lần chạy kế tiếp tối 19/10 | PASS |
| Job trùng | 0 idempotency key trùng | PASS |
| Log server | `server.err.log` 0 byte. `server.out.log`: 0 dòng ERROR mới ngoài lỗi `job failed` của D-1 (mục A3) | PASS |

### A2. Backup trước deploy

Hai backup trước deploy đã được đọc lại lúc 03:45 ngày 19/10, chi tiết trong `reports/demandforecast_v126_deployment_state_recovery.md`, mục 6:

| File | SHA-256 | Kết quả đọc lại |
|---|---|---|
| `backup-20261018-190932-manual.zip` | `52788C13…A091` | CRC OK, `integrity_check ok`, schema 4 |
| `backup-20261018-190701-cli.zip` | `C8F38FD3…E38D` | CRC OK, `integrity_check ok`, schema 4 |

Task này không đọc lại backup lần nữa.

### A3. Các job

Không job nào được chạy thủ công hoặc chạy bù trong task này.

| Job | Bằng chứng | Trạng thái |
|---|---|---|
| D-1 ngày 19/10, theo lịch | `JOB-20261018200019-DE2F7C` tạo lúc 03:00:19, poll tới mốc fallback 05:00. **FAILED `SOURCE_INCOMPLETE`** lúc 05:09:07 (4 lần thử): BigQuery có 0 dòng cho ngày 18/10. Cảnh báo `RETRIES_EXHAUSTED` (#16). Cùng kiểu với ngày 18/10, khi còn chạy 1.2.5. Đây là thời điểm dữ liệu ở nguồn, không phải lỗi của bản deploy. | FAIL (nguồn dữ liệu) |
| D-1 thủ công lúc 10:13 | `JOB-20261019031322-A37285`, trigger `MANUAL`, không do Claude tạo. Lúc 10:18: `RETRY_WAIT SOURCE_INCOMPLETE` (0 dòng ngày 18/10; trung bình 7 ngày trước 18.847 dòng) | UNKNOWN (đang chạy) |
| D-0 lần đầu trên 1.2.6 (08:00) | `JOB-20261019010027-E4E845` **SUCCEEDED**, snapshot `SNP-20261019010032-B760DD` (430 series, 747 dòng, 0 dòng lỗi) | PASS |
| D-0 10:00 | `JOB-20261019030005-0A6EA2` **SUCCEEDED**, `SNP-20261019030015-18EED9` | PASS |
| Huấn luyện 09:00 | Không có job `TRAIN_PUBLISH:2026-10-19`. Scheduler ghi `TRAIN_WAITING_FOR_TODAY_D1`: huấn luyện chờ D-1 hôm nay thành công, đúng thiết kế. Lần chạy kế tiếp hiện là 20/10 09:00. | NOT_RUN (chờ D-1) |
| Hai lịch mới, ngày 18/10 | eod `SUCCEEDED` (`FES-20261018165531-ADB329`, 119.889 dòng); close `SUCCEEDED` (`ACL-20261018165927-46D45C`, `CLOSED_UNVERIFIED` đúng thiết kế) | PASS |
| Hai lịch mới, ngày 19/10 | 23:55 và 23:59 tối nay | NOT_DUE |

### A4. Link xem từ xa ngừng hoạt động

Đây là sự cố production, không do task này gây ra và chưa được xử lý.

Bằng chứng trong log cloudflared `%LOCALAPPDATA%\DemandForecastRemote\logs\cloudflared-20261017-165443.log` (giờ VN):

| Thời điểm | Sự kiện |
|---|---|
| 09:39:02 | Máy mất mạng: `wsasendto: A socket operation was attempted to an unreachable network`; trước đó có lỗi `lookup region1.v2.argotunnel.com: i/o timeout` |
| 09:39:15 | Lần đăng ký lại đầu tiên nhận `Unauthorized: Tunnel not found`: Cloudflare đã xóa Quick Tunnel |
| Đến 10:19 | 144 lần đăng ký lại đều thất bại |

Trạng thái lúc kiểm tra:
- `/ready` của cloudflared trả 503; `/quicktunnel` vẫn trả hostname cũ.
- DNS: `volumes-jean-angels-configurations.trycloudflare.com : DNS name does not exist`.
- Tiến trình cloudflared (31076) và proxy (26416) vẫn sống, và vẫn tiếp tục thử lại.
- App cùng proxy cục bộ hoạt động bình thường.

Quick Tunnel là loại tạm thời và không có cam kết dịch vụ. Tên miền cũ không thể phục hồi; khởi động lại tunnel sẽ tạo **URL mới**. Prompt cấm đổi URL/tunnel, nên tôi không làm gì với tunnel. Cần anh/chị quyết định (mục H).

## B. Lưu bằng chứng và gỡ task một lần

**Bằng chứng** được chép từ `%TEMP%` sang `reports\v126-deploy-evidence\`. Đây là thư mục mới, không ghi đè thứ gì, không chép file `.db`:

| Thư mục con | Nội dung |
|---|---|
| `prod_state/` | 18 file trạng thái của task: `task.log`, `result.json`, `done.json`, `deploy_run.txt`, `pre/post/final.json`, `poll_app.csv`, `poll_link.csv`… |
| `task_scripts/` | 5 script task đã chạy |
| `verification/` | 7 file kiểm tra chỉ đọc. `dayend_check.compact.json` là bản **rút gọn** (`DERIVED`) của một file gốc 18 MB; bản gốc phình to vì PowerShell ghi kèm metadata. |
| `task_definition/` | XML của task và trạng thái task, xuất ra **trước khi** gỡ |

`manifest.json` và `MANIFEST.md` liệt kê 32 mục, mỗi mục có tên, nguồn, thời gian sửa, kích thước và SHA-256. SHA-256 nguồn và bản chép đã được so cho từng file. Quét secret: 0 kết quả.

Ghi nhận phụ: `deploy_run.txt` và `deploy_run.txt.err` vẫn bị app production (khởi động trong lúc deploy) giữ handle mở. Vì vậy thư mục scratchpad trong `%TEMP%` chưa thể xóa hết khi app còn chạy. Điều này vô hại.

**Gỡ task** `DemandForecast-Deploy-1.2.6` lúc **08:44:40**. Điều kiện đã kiểm lại ngay trước khi gỡ:
- trạng thái `Ready`, kết quả lần chạy cuối 0;
- không còn lần chạy nào sắp tới, không có trigger trong tương lai;
- không có tiến trình `deploytask126` đang chạy;
- `done.json` đã tồn tại.

Chỉ gỡ đúng task này: số task trên máy giảm từ 207 xuống 206, và chỉ thiếu `\DemandForecast-Deploy-1.2.6`.

## C. Dashboard Performance Investigation and Optimization

### C1. Luồng request của trang Tổng quan

**Trước (1.2.6 hiện tại):**

```
mở trang ─┬─ (khung app)  GET /api/system/status ── system_status()  ← 7,8 s (bản sao, cache ấm)
          ├─ (Tổng quan)  GET /api/settings                        ← 0,03 s
          ├─ (Tổng quan)  GET /api/dashboard?horizon=7 ── system_status() LẦN 2 + forecast_summary()  ← 11 s
          └─ (Tổng quan)  GET /api/jobs/active                     ← 0,01 s
Trang chỉ hiện "Đang tải…" cho tới khi /api/dashboard trả về; hai lần system_status() chạy song song, tranh nhau
CPU và I/O (đo đồng thời: 17,3 s).
```

**Sau (bản sửa local):**

```
mở trang ─┬─ (khung app + Tổng quan) GET /api/system/status  ← MỘT request dùng chung, ~1,1–1,3 s
          │        └─ khi về: các thẻ nguồn / độ mới / model, chất lượng, job, cảnh báo hiện ngay
          │             └─ GET /api/forecast-runs/{id}/summary?horizon=min(h, max)&limit=10  ← 0,6 s
          │                  └─ thẻ forecast hiện (có loading / lỗi riêng)
          ├─ GET /api/settings      (thẻ forecast chờ settings để chỉ hỏi summary một lần)
          └─ GET /api/jobs/active
Đầu trang hiện ngay; /api/dashboard không còn bị gọi (endpoint giữ nguyên cho nơi khác).
```

| Đặc điểm | Trước | Sau |
|---|---|---|
| Số request API khi mở trang | 6 (gồm `/api/methods` và `/api/messages` gọi sau) | 6 |
| Số lần tính `system_status()` | **2** (song song) | **1** |
| Request chặn hiển thị nội dung đầu tiên | `/api/dashboard` (status + forecast) | `/api/system/status` (một lần) |
| Request trùng hoặc polling | Status bị tính trùng; không có polling | Không có |
| BigQuery trong request | Không có | Không có |

### C2. Nguyên nhân (có số đo)

Profile trong tiến trình, trên bản sao DB production: `system_status()` mất 7,77 s với 23 câu SQL. Riêng một câu chiếm **7.387 ms (95%)**:

```sql
SELECT MAX(order_date), MIN(order_date), COUNT(*), MAX(loaded_at) FROM demand_daily WHERE scope_key=?
```

- Plan của câu này là `SEARCH demand_daily USING INDEX sqlite_autoindex_demand_daily_1 (scope_key=?)`.
- Index khóa chính `(scope_key, order_date, sku_id, fc_id)` không chứa `loaded_at`. Vì vậy SQLite phải tra ngược bảng cho từng dòng trong 1.352.355 dòng của scope BigQuery.
- Mỗi request mở một kết nối mới, với cache trang mặc định khoảng 2 MB. Kết quả là **1.521.548 lần `ReadFile` (6.232 MB đọc qua cache hệ điều hành, gấp 11 lần cả file DB 572 MB) cho mỗi lần tính status**.
- Trên production, máy chỉ còn khoảng 1,6/15,7 GB RAM trống, nên các lần đọc này rơi xuống đĩa: 44,8 s (1.2.5) và 66,3 s (1.2.6) đã đo trước đó.

Trang Tổng quan còn tính status **hai lần song song** (qua khung app và qua `/api/dashboard`), nên chờ còn lâu hơn.

`forecast_summary` của thẻ forecast chỉ mất 0,47 s (11 câu SQL). `/api/settings` và `/api/jobs/active` đều dưới 0,1 s. Không có truy vấn BigQuery nào trong luồng này.

### C3. Thay đổi (mã local, chưa commit)

| File | Thay đổi | Lý do |
|---|---|---|
| `backend/app/api/ops_routes.py` (CRLF giữ nguyên) | Gộp câu tổng hợp freshness và câu đếm cửa sổ dữ liệu thành **một lần quét tuần tự** `... FROM demand_daily NOT INDEXED WHERE scope_key=:k`. Các con số của cửa sổ dùng `COUNT/MIN/MAX(CASE WHEN order_date BETWEEN :s AND :e …)` | Bỏ hơn 1,35 triệu lần tra ngẫu nhiên và lượt quét index thứ hai. Giá trị giống hệt câu cũ. Không đổi schema, API hay quy tắc nghiệp vụ. |
| `frontend/src/App.tsx` (CRLF) | Status của khung app có `refresh()` (dùng chung request đang chạy) và `reload()` (luôn hỏi mới; chỉ áp dụng câu trả lời mới nhất). Context có thêm `loading` và `error`. | Trang mở cùng lúc với khung app không tính status lần thứ hai. Sau một thao tác ghi, status luôn được hỏi lại bằng request mới. |
| `frontend/src/pages/Dashboard.tsx` (CRLF) | Đầu trang hiện ngay. Các phần dựa trên status hiện khi status về. Thẻ forecast tự tải `/api/forecast-runs/{id}/summary`, chặn horizon ở mức tối đa của run như `/api/dashboard` vẫn làm, và có loading/lỗi riêng. Khi đang tải hoặc lỗi, các phần hiện "Đang tải…" hoặc "Chưa có", không bao giờ hiện 0 hay "Cần cấu hình". | Không chặn cả trang chỉ vì một phần chậm; bỏ tính trùng. Endpoint summary đã có sẵn trong allowlist của proxy chỉ đọc, nên link từ xa không bị ảnh hưởng. |
| `backend/tests/test_v126_status_perf.py` (mới) | 4 test, mô tả ở mục D | |
| `frontend/src/v126dash.test.tsx` (mới) | 7 test, mô tả ở mục D | |
| `backend/tests/test_v121_remote_proxy.py` | Một assertion kiểm tra sơ bộ bộ quét đường dẫn: thay `/api/dashboard` bằng `/api/forecast-runs/X1/summary`, vì trang không còn dùng `/api/dashboard` | Không nới lỏng test. Kiểm tra proxy cho `/api/dashboard` (danh sách endpoint và request thật) vẫn giữ nguyên. |
| `CHANGELOG.md` | Thêm mục "Unreleased - dashboard load hotfix" | |

Những gì **không** thay đổi:
- `/api/dashboard`, `/api/system/status` và hợp đồng dữ liệu của chúng;
- công thức KPI, forecast, actual, WAPE, bias;
- schema, quyền truy cập, proxy, lịch;
- không thêm cache, dependency hay background job.

### C4. Đo trước và sau, cùng môi trường

**Môi trường đo:**
- Cùng PC: Intel i5-1335U, 16 GB RAM, SSD NVMe; ổ C: và D: cùng nằm trên một đĩa.
- Bản sao DB production tạo lúc 08:46 ngày 19/10 bằng SQLite backup API, nguồn mở `mode=ro`. Kích thước 572.370.944 byte, `integrity_check ok`, schema 6, gồm 1.352.355 dòng demand của scope BigQuery.
- Backend chạy từ mã nguồn trên cổng 8893, với `DF_DISABLE_SCHEDULER=1`, `LOCALAPPDATA` và dữ liệu cách ly trong scratchpad.
- Trình duyệt: Edge headless qua CDP, tắt cache trình duyệt, mỗi lần đo là một tab mới.
- Các mốc đo theo `performance.now()` tính từ lúc điều hướng:

| Mốc | Điều kiện |
|---|---|
| Nội dung chính | Có `[data-testid=dash-window]` và ít nhất 4 thẻ `.stat` |
| Hoàn tất | Có thanh top series, không còn `.loading`, bảng job đã có dòng |

- Máy có tải nền thay đổi theo thời gian (production, RAM trống thấp). Vì vậy bản "trước" được đo **hai lần** (A lúc khoảng 09:45 và A2 lúc khoảng 10:10), xen kẽ với các phép đo "sau".

**Thời gian trong trình duyệt** (ms; trung vị, khoảng):

| Cấu hình | Số lần | Khung trang | Nội dung chính | Hoàn tất | Lần 1 (sau khi server khởi động / máy nhàn rỗi) |
|---|---|---|---|---|---|
| A: trước (backend và giao diện HEAD) | 5 | 266 | **23.573** (20.826–39.693) | 23.573 | 39.693 |
| A2: trước, đo lại để đối chứng | 5 | 341 | **39.827** (32.107–55.484) | 39.827 | 55.484 |
| B': chỉ sửa backend, giao diện cũ | 5 | 308 | 4.565 (2.671–18.970) | 4.565 | 18.970 |
| C: **sau** (backend và giao diện mới) | 9 | 226 | **1.319** (1.177–16.586) | **2.025** (1.867–17.680) | 16.586 / 17.680 |

So với A, nội dung chính nhanh hơn **22,3 s (−94,4%)**, thời điểm hoàn tất nhanh hơn **21,5 s (−91,4%)**. So với A2, nội dung chính nhanh hơn 38,5 s (−96,7%). Lần mở đầu tiên sau khi nhàn rỗi giảm từ 39,7–55,5 s xuống 16,6–17,7 s.

**Số lần đọc của tiến trình server cho mỗi lần mở trang** (`Win32_Process.ReadOperationCount`). Chỉ số này ổn định qua các lần đo, không phụ thuộc cache nóng hay lạnh:

| Cấu hình | Số lần đọc | Dữ liệu đọc |
|---|---|---|
| A2: trước | 3.095.850 | 12.093,7 MB |
| C: sau | 107.554 | 420,7 MB |
| Mức giảm | −96,5% | −96,5% |

**Thời gian từng API** (httpx, 5 lần, trung vị):

| API | Trước (A) | Sau |
|---|---|---|
| `/api/system/status` | 7.794 ms | 1.114 ms (B') / 1.307 ms (C) |
| `/api/dashboard?horizon=7` (không còn được trang dùng) | 11.081 ms | 1.724 ms (B') |
| `/api/forecast-runs/{id}/summary?horizon=7&limit=10` | — | 615 ms |
| Các request khi mở trang, gọi đồng thời | 17.274 ms | 2.252 ms (B', vẫn dùng `/api/dashboard`) / 1.401 ms (C) |

**Câu SQL freshness riêng** (trên bản sao, kết quả giống hệt nhau trong mọi trường hợp: scope BigQuery, scope DEMO, scope không có dòng):

| Dạng câu | Thời gian | Số lần đọc | Dữ liệu đọc |
|---|---|---|---|
| Câu cũ | 7,5 s; khoảng 20 s lúc máy tải nặng | 1.521.548 | 6.232 MB |
| Câu cũ + `NOT INDEXED`, câu window riêng | 0,8–0,9 s | 96.938 | 397 MB |
| **Một lần quét (bản sửa)** | 0,43–0,88 s | **54.898** | **225 MB** |

### C5. `/api/system/status`

- **Route:** `GET /api/system/status` → `ops_routes.system_status()`. Không gọi BigQuery hay scheduler; `SCHEDULER.status()` chỉ đọc bộ nhớ. Proxy chỉ chuyển tiếp (`proxy GET /api/health` mất 43 ms).
- **Phần tốn thời gian:** 95% nằm trong câu freshness trên SQLite (C2). Các câu còn lại tổng cộng khoảng 0,3 s, trong đó khoảng 0,3 s là câu đếm cửa sổ dữ liệu, nay đã gộp vào cùng một lần quét. Phần Python không đáng kể (profile: 0,016 s cho `settings_service`).
- **Vì sao 45 s thành 66 s sau deploy:** cùng một câu, nhưng DB lớn thêm khoảng 12 MB và RAM trống của máy rất thấp, nên nhiều lần đọc rơi xuống đĩa hơn. 1.2.6 không đổi câu này.
- **Có phải thông tin phụ đối với Tổng quan không?** Không hẳn. Ngày dữ liệu mới nhất, độ trễ, trạng thái và số dòng trong cửa sổ đều hiển thị ở hàng thẻ đầu tiên. Ngoài ra status còn cấp run đang dùng cho thẻ forecast. Vì vậy status vẫn được tải trước, nhưng chỉ một lần và chỉ chặn các phần cần nó.
- **Những gì không làm:** không tăng timeout, không trả trạng thái giả, không bỏ kiểm tra quyền.
- **Production:** không đo thêm, để tránh tạo tải. Các số 44,8 s / 66,3 s là mẫu đã có. Hiệu quả thật trên production chỉ đo được sau khi triển khai bản sửa.

### C6. Phần còn chậm và đề xuất (cần phê duyệt; tôi chưa làm)

1. **Lần mở đầu tiên khi cache lạnh** vẫn mất khoảng 17 s trên bản sao. Status phải quét bảng `demand_daily` (225 MB) để lấy `MAX(loaded_at)`, và thẻ forecast đọc khoảng 196 MB của `forecast_values`.
   Giảm thêm cần một trong hai cách, đều phải phê duyệt riêng vì đụng schema hoặc đường ghi:
   - (a) Bảng hoặc khóa `sync_state` lưu thống kê freshness theo scope, được cập nhật bởi **mọi** đường ghi `demand_daily` (D-1, import, demo).
   - (b) Index `(scope_key, loaded_at)`, kèm số dòng được duy trì sẵn.
2. **`forecast_summary`** quét các dòng của run 5 lần (5 câu `GROUP BY`). Gộp lại sẽ giảm I/O của thẻ forecast, nhưng phải chứng minh tổng số thực (float) không đổi. Endpoint này cũng phục vụ trang Kết quả. Nên làm thành một việc riêng.
3. **`scope_key`** là chuỗi 72 ký tự, lặp lại trong mỗi dòng và mỗi mục index của `demand_daily`. Đây là gốc của kích thước bảng; dài hạn nên chuyển sang id số (đổi schema).
4. **RAM trống của máy production thấp** (1,6/15,7 GB lúc 08:4x). Đây là vấn đề vận hành, ảnh hưởng mọi lần đọc DB.

## D. Kiểm thử hồi quy

| Kiểm thử | Loại | Kết quả |
|---|---|---|
| Toàn bộ backend: `pytest -q -p no:cacheprovider` | unit / tích hợp với dữ liệu tổng hợp | **PASS: 497 passed, 7 skipped** (493 cũ + 4 mới; 7 test bỏ qua là test BigQuery thật, chỉ chạy khi có `DF_REAL_BQ=1`), 506 s |
| `test_v126_status_perf.py`, 4 test (mới) | tích hợp với SQLite thật, dữ liệu DEMO | PASS 4/4 |
| `test_v121_remote_proxy.py`, kiểm tra proxy chặn 405/403 và allowlist | tích hợp | PASS (nằm trong lượt 47 passed cùng test perf) |
| Frontend vitest | jsdom, fetch giả lập | **PASS 123/123** (19 file; 116 test cũ + 7 test mới) |
| `v126dash.test.tsx`, 7 test (mới) | jsdom | PASS 7/7 |
| `npm run typecheck` | | PASS (exit 0) |
| `npm run build` | | PASS (exit 0); `index-DlMy_GsW.js` giống bản đã đo |
| Lint | | **NOT CONFIGURED** |
| Đo trước/sau trên bản sao DB production | DB copy, trình duyệt thật | Mục C4 |
| Production sau khi sửa | | NOT_RUN: bản sửa chưa được triển khai (cần phê duyệt) |

Bốn test backend mới (`test_v126_status_perf.py`):
1. Giá trị freshness và cửa sổ dữ liệu bằng đúng **câu SQL cũ**, với dữ liệu có thêm một scope khác, một `loaded_at` mới nhất nằm giữa thứ tự khóa, và các dòng nằm ngoài cửa sổ.
2. Scope không có dòng nào cho kết quả như cũ.
3. Chặn tái phát: status đọc `demand_daily` đúng **một** lần, plan là `SCAN demand_daily`, không bao giờ `SEARCH … USING INDEX`.
4. Thẻ forecast lấy từ `/summary` **bằng hệt** `forecast` của `/api/dashboard` với các horizon 7, 15, tối đa và tối đa + 30 (giá trị vượt tối đa được chặn lại).

Bảy test frontend mới (`v126dash.test.tsx`):
- phần status hiện trước forecast, và thẻ forecast chỉ hiện "Đang tải…", không hiện số;
- status được hỏi **1** lần cho cả khung app và trang, không gọi `/api/dashboard`, summary được hỏi đúng 1 lần với `horizon=7&limit=10`;
- horizon bị chặn theo tối đa của run, và trang chờ settings để chỉ gọi summary một lần;
- summary lỗi thì lỗi chỉ hiện trong thẻ forecast, các phần khác vẫn còn;
- status chậm thì trang hiện loading, không hiện "Cần cấu hình" và không có thẻ số;
- status lỗi thì hiện lỗi của khung app cùng "Chưa có", không có số;
- sau "Đánh dấu đã đọc tất cả", status được hỏi bằng request mới và thẻ forecast tải lại theo.

**Kiểm tra chéo trên mã gốc:**
- Cả 7 test frontend mới **thất bại** khi chạy trên `App.tsx` / `Dashboard.tsx` của HEAD.
- Test chặn tái phát của backend **thất bại** trên `ops_routes.py` của HEAD (plan là `SEARCH … USING INDEX`).
- Ba test tương đương giá trị đạt trên cả hai bản, đúng như dự kiến.
- Các file đã được khôi phục, hash khớp.

**Các mục kiểm thử theo yêu cầu:**
- Không đổi lịch D-1/D-0/huấn luyện: không file lịch hay scheduler nào bị sửa; các test lịch hiện có nằm trong bộ backend.
- Không đổi số liệu: test 1 và test 4 ở trên.
- Các màn hình khác dùng `useSystem` (Batches, BigQuery, Import, Results, Snapshots, System): bộ vitest hiện có, gồm test dựng mọi route, đều đạt.

## E. Rủi ro còn lại

- Cache lạnh vẫn chậm (C6.1). Hiệu quả trên production chưa đo được cho tới khi triển khai.
- Trang Tổng quan **ẩn** các phần dựa trên status khi status lỗi; trước đây trang vẫn hiện dữ liệu cũ kèm thông báo lỗi. Đây là lựa chọn có chủ đích để không hiện số liệu cũ như thể mới.
- `NOT INDEXED` chỉ có trong SQLite. Bản VPS cũng dùng SQLite nên không ảnh hưởng.
- Link xem từ xa đang chết (A4). D-1 thiếu dữ liệu nguồn hai ngày liên tiếp (A3).

## F. Production không thay đổi

Những gì **không** làm trong task này:
- deploy, rollback, restore, migration, retention, ghi BigQuery;
- chạy job thủ công;
- sửa lịch, model, URL, proxy hay tunnel;
- commit hoặc push.

Thay đổi duy nhất trên máy production là gỡ task một lần đã hoàn tất (B). Mọi phép đo hiệu năng chạy trên bản sao DB, trên cổng 8893, và server đo đã được dừng.

## G. Đề xuất cập nhật `docs/CHECKPOINT.md` (chưa sửa file, chưa commit)

> 19/10/2026: production 1.2.6 since 18/10 19:16 (deploy task removed 19/10 08:44; evidence `reports/v126-deploy-evidence/`). Dashboard hotfix in the working tree, NOT committed: `system_status()` one sequential scan of `demand_daily` (NOT INDEXED; 1.52 M -> 55 k page reads), dashboard reads the shell status once + `/api/forecast-runs/{id}/summary`; tests `test_v126_status_perf.py`, `v126dash.test.tsx`; measured on a DB copy 23.6 s -> 1.3 s. Remote quick tunnel deleted by Cloudflare 19/10 09:39 (URL dead). Next: owner approval -> 1.2.7 release + rehearsal + deploy window; tunnel restart (new URL).

## H. Cần phê duyệt (theo thứ tự đề xuất)

1. **Link xem từ xa:** khởi động lại Cloudflare Quick Tunnel để có **URL mới**, hoặc chuyển sang named tunnel nếu muốn URL cố định. Đây là thay đổi production URL, phải do anh/chị quyết định.
2. **Phát hành bản sửa:**
   - commit (theo `docs/GITHUB_WORKFLOW.md`) và tăng phiên bản (1.2.7);
   - `release.ps1`, rồi diễn tập nâng cấp/rollback trên bản sao;
   - `deploy-upgrade.ps1` trong một khung giờ được duyệt, ngoài các slot lịch;
   - đo lại trên production sau khi triển khai.
3. **D-1 thiếu dữ liệu nguồn:** BigQuery có 0 dòng ngày 18/10 lúc 05:09 và 10:13 ngày 19/10. Cần chủ dữ liệu xác nhận khi nào nguồn có đủ dữ liệu. Huấn luyện hôm nay sẽ chờ tới khi đó.
4. **Đề xuất C6** (schema hoặc đường ghi để cải thiện khi cache lạnh): mỗi đề xuất cần một batch riêng.
5. **Push** 24 commit đang đi trước `origin/main` (cùng commit của bản sửa nếu được duyệt).

## I. Cập nhật 19/10/2026, 10:35–11:05 (prompt "khôi phục remote access, hoàn thiện performance fix")

Kết quả lượt này:

| Hạng mục | Kết quả | Trạng thái |
|---|---|---|
| Link xem từ xa | Khôi phục bằng `scripts\remote\remote-access.ps1 start` lúc 10:37. URL mới **https://automated-speak-rehabilitation-available.trycloudflare.com**. Qua HTTPS: admin 403, ghi 405. Chỉ có 1 cloudflared (pid 18992); app và proxy không khởi động lại. Chi tiết: `reports/demandforecast_remote_access_recovery.md` | PASS |
| D-1 | Anh/chị đã tự xử lý (job thủ công `JOB-20261019033144-51D4BD` SUCCEEDED lúc 10:35:14). Không điều tra lại | PASS (chỉ đọc) |
| Huấn luyện 09:00 | `SKIPPED MISSED_SLOT_NO_BACKFILL` lúc 10:35:20, theo chính sách bù `SKIP`. Lần kế tiếp 20/10 09:00 | NOT RUN (theo chính sách) |
| Chốt actual ngày 18/10 | Revision 2 từ D1 (`ACL-20261019033514-1FA2BB`, tổng 57.832), vẫn `CLOSED_UNVERIFIED` vì chưa có tín hiệu hoàn tất | PASS |
| `/api/system/status` trên production | 32,9 s, 1.521.324 lần đọc lúc 10:53. Cùng nguyên nhân đã xác định; bản sửa chưa triển khai | FAIL (rủi ro mở) |
| Bản sửa Tổng quan | Thêm một sửa phòng ngừa trong `Dashboard.tsx`: "Chưa có" chỉ hiện khi status đã dừng tải. QA một lượt `run-tests.ps1`: backend 497 passed / 7 skipped (BigQuery thật), typecheck, vitest 123/123, build, tất cả exit 0. Benchmark cùng điều kiện: nội dung chính 60,6 s → 3,5 s, CPU mỗi lần mở trang 83 s → 5,3 s, số lần đọc −96,5% | PASS (local) |

Báo cáo sẵn sàng phát hành, gồm kế hoạch 1.2.7 và các cổng phê duyệt: `reports/demandforecast_v127_readiness_review.md`.
