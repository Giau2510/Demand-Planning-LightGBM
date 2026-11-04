# Demand Forecasting 1.2.5 — Lịch sử Forecast D+1 và UI redesign (18/10/2026)

**Trạng thái: READY_FOR_PRODUCTION — đã deploy và xác minh trên production.**

Còn hai việc chờ chủ sở hữu quyết định, xem mục 14. Bằng chứng "forecast bất biến khi actual cập nhật" ở mục 13.

## 1. Phiên bản và thời điểm deploy

| | |
|---|---|
| Trước | 1.2.4, chạy production từ 17/10 22:59 |
| Sau | **1.2.5**. Deploy ngày 18/10/2026 từ **10:00:33 đến 10:08:30** (giờ VN), sau D-0 10:00, lúc không có job nào đang chạy. Proxy khởi động lại lúc 10:09. |
| Mã nguồn | 2 commit cục bộ, **không push**:<br>• `dadf77c`: release;<br>• `c15f767`: sửa 3 lỗi nhỏ sau rà soát độc lập. |
| Gói đã cài | `dist\DemandForecast-1.2.5-win64-portable.zip`, SHA-256 `F502042C3F332CAAB4B47855C4D374FECF5D6F93CDEB3649B09D17E42DBCC58E`, build từ commit `c15f767`, source `BB49C7CF48E82B47` |
| Gói không dùng | Bản build từ `dadf77c` chưa cài ở đâu. Nó được giữ lại với tên `DemandForecast-1.2.5-superseded-20261018-092944-…`, không bị xóa. |
| Thư mục `dist\` | Không dọn, không xóa gói nào. Retention trong `release.ps1` chỉ chạy thử (dry run). |

## 2. Schema và migration

- **Migration `0004_forecast_history.sql`** (schema 3 → 4) **chỉ thêm 3 bảng**, không sửa hay xóa dòng có sẵn nào:
  - `forecast_history_sessions`: mọi forecast run, kèm quyết định lúc ghi nhận. Bất biến.
  - `forecast_history_values`: giá trị D+1 của phiên được chọn. Bất biến.
  - `forecast_history_days`: phiên chính thức của mỗi scope × ngày chạy. Chỉ con trỏ được đổi, và mỗi lần đổi đều ghi `audit_log`.
- **Trigger** chặn sửa hoặc xóa lịch sử, và chặn con trỏ trỏ tới phiên không hợp lệ hoặc thuộc ngày khác.
- **Số dòng trên production trước và sau:**
  - Các bảng cũ không đổi. `forecast_runs` vẫn 5, `forecast_values` vẫn 262.503.
  - Các bảng thay đổi trong ngày là do job theo lịch và lần D-1 thủ công của anh/chị, không phải do deploy (xem mục 12).
  - Bảng mới: sessions 5, values 17.461, days 3.
- Migration được rehearse trên bản sao DB thật, xem mục 9.

## 3. Lưu D+1 và chọn phiên (đã triển khai)

- **Phiên** = một lần forecast **đã publish thành công** (một `forecast_runs`). Lần chạy thất bại hoặc đang chạy không tạo run nào, nên không bao giờ thành lịch sử.
- **Ngày chạy** = ngày theo giờ VN của lúc job bắt đầu; không có job thì lấy lúc publish.
- **Chỉ lưu D+1**: lưu `target_date = ngày chạy + 1`. D+7/D+15/D+30 vẫn chỉ nằm trong `forecast_values`, không đổi.
- **Phiên chính thức** = phiên hợp lệ mới nhất theo (giờ bắt đầu phiên, giờ publish, thứ tự ghi).
  - Phiên bắt đầu sớm hơn nhưng xong muộn hơn **không** thay phiên mới hơn.
  - Run không có giá trị D+1 là `NOT_ELIGIBLE` và không thay gì.
  - Ngày khác không bao giờ đụng tới ngày này.
- **Thời điểm ghi:** ngay sau khi publish đã commit, trong transaction riêng, nên lỗi ghi lịch sử không thể làm mất forecast. Khi lỗi, hệ thống tạo alert `FORECAST_HISTORY_CAPTURE_FAILED`.
- **Thử lại idempotent**, đọc lại từ forecast đã lưu: ở lần publish sau, khi khởi động lại, hoặc bằng `app.cli history-reconcile`.
- **Ghi đồng thời** không tạo trùng hay chọn sai, nhờ `BEGIN IMMEDIATE` và khóa chính.
- **Production:** 5 run đã publish trước 1.2.5 được ghi nhận từ giá trị đã lưu (`RECOVERED`). **Không có forecast giả** cho ngày nào chưa từng có run.
  - BIGQUERY: ngày chạy 17/10 → dự báo 18/10, `FCR-20261017123417-FCC0EB`, 17.125 dòng, tổng 71.993,5.
  - DEMO: 14/10 (3 phiên; phiên 18:18 là chính thức) và 16/10.

## 4. Nguồn actual và cách xác định ngày hoàn tất

| Trường hợp | Nguồn | Trạng thái |
|---|---|---|
| Ngày đã được D-1 nạp | `demand_daily`. SKU × FC không có dòng trong ngày đã nạp = 0, giống quy tắc của panel huấn luyện / backtest. | "Đã hoàn tất" chỉ khi D-1 nạp ngày đó theo **tín hiệu hoàn tất** của nguồn (audit `D1_SYNC` mode `SIGNAL`). Còn lại là "Tạm tính". |
| D-1 chưa nạp | Số lũy kế của snapshot D0 mới nhất | "Tạm tính" |
| Không có gì / ngày chưa tới / ngày đã nạp nhưng không có dòng | — | "Chưa có dữ liệu thực tế". **Không bao giờ thành 0.** |

- **Production chưa cấu hình bảng tín hiệu hoàn tất** (`bigquery.completion_table` trống). D-1 chạy sau giờ dự phòng 06:00 và chỉ kiểm tra số dòng; truy vấn thành công hay đã qua nửa đêm **không** được coi là bằng chứng. Vì vậy hiện **mọi số thực tế là "Tạm tính"**, và màn hình nói rõ lý do. Tôi không tự đặt quy tắc mới.
- Actual được đọc lúc hiển thị và không lưu chung với forecast, nên cập nhật actual không sửa forecast và không tạo phiên mới.
- Khi nguồn cập nhật hồi tố, actual hiển thị số mới kèm "thực tế tính đến".

## 5. Sai lệch và WAPE

- **Phạm vi:** tính trên đúng tập dòng của bộ lọc. KPI, biểu đồ, bảng và Excel dùng chung một truy vấn.
- **Tổng forecast đã lưu:** tính trên mọi dòng.
- **Thực tế, sai lệch và WAPE:** chỉ tính trên các dòng **đã có thực tế**.
  - Sai lệch = Σ F − Σ T.
  - WAPE = Σ|F − T| / Σ T, đúng công thức của `ml/metrics.py` (test đối chiếu trực tiếp).
  - Không tính khi Σ T = 0, hoặc khi chưa có thực tế.
- **WAPE dòng** = |F − T| / T, chỉ khi T > 0.
- **Nhãn "Tạm tính":** gắn trên thẻ Thực tế, Sai lệch và WAPE khi có dòng tạm tính.

## 6. API và frontend mới

**API (chỉ GET):**
- `/api/history/overview`, `/summary`, `/rows` (phân trang, sắp xếp phía server), `/export.xlsx`.
- Mở trang không tạo job, không huấn luyện, không forecast, không ghi DB; test có so số dòng các bảng trước và sau.

**Trang `/forecast-history` "Lịch sử Forecast & Thực tế":**
- Mục menu riêng ngay dưới "Kết quả dự báo". Không gộp vào trang cũ.
- **Bộ lọc** (kết hợp được với nhau, có nút "Xóa bộ lọc"):
  - ngày chạy forecast: một ngày, 7 hoặc 30 ngày, tất cả, hoặc tự chọn khoảng;
  - FC;
  - SKU / tên sản phẩm (một phần, không phân biệt hoa thường, không cần dấu);
  - trạng thái thực tế.
- **Ngày chạy và ngày được dự báo** luôn hiển thị tách riêng.
- **KPI:** 4 thẻ.
- **Biểu đồ:** forecast màu xanh, thực tế màu cam, ô vuông rỗng là thực tế tạm tính. Ngày không có dữ liệu để trống, không nội suy. Tooltip gồm ngày, forecast, thực tế, sai lệch và trạng thái.
- **Bảng "Phiên forecast được chọn"**: có truy vết các phiên khác trong ngày.
- **Bảng SKU × FC:** 11 cột, phân trang. Thiếu tên thì ghi "Chưa có tên sản phẩm".
- **Thông báo:** "Chưa có forecast hợp lệ" / "Chưa có lịch sử forecast được lưu cho ngày này".
- **Link xem từ xa:** proxy chỉ đọc được nâng lên phiên bản 1.2.5, cho phép đúng 4 đường dẫn GET này.

## 7. Excel

- Gồm 4 sheet: Thông tin (bộ lọc, KPI, quy tắc), Phiên forecast, Theo ngày, Chi tiết SKU × FC (15 cột, gồm run ID, model version, ngày chạy, ngày dự báo, trạng thái thực tế).
- Xuất **toàn bộ dòng khớp bộ lọc**. Test: 117 dòng khớp bộ lọc ra đủ 117 dòng, trong khi màn hình chỉ hiện trang 50 dòng. Không có dòng ngoài bộ lọc.
- Ô thực tế trống nghĩa là chưa có dữ liệu, không phải 0. Trạng thái ghi bằng chữ "Tạm tính" / "Đã hoàn tất".
- Quá 1.000.000 dòng thì từ chối, không cắt bớt. Có cả bản tiếng Việt và tiếng Anh.
- Production qua link: 17.125 dòng, 1,46 MB, khoảng 13 giây.
- Excel ở các trang khác không đổi.

## 8. Giao diện được giữ lại hoặc cập nhật

- **Phạm vi B (redesign) giữ nguyên toàn bộ:**
  - lucide-react 1.48.0 với bộ icon dùng chung;
  - design tokens, các component dùng chung, sidebar, responsive;
  - bảng có header cố định; biểu đồ có tooltip;
  - trạng thái luôn có icon kèm chữ.
- **Chỉ bổ sung để tích hợp màn hình lịch sử:**
  - icon `fhistory`, `actual`, `deviation`, `percent`;
  - component `CompareChart`;
  - tone cho `COMPLETE` / `PROVISIONAL` / `NO_ACTUAL`;
  - CSS bảng 11 cột `fh-tbl`.
- Không xóa component, test hay tài liệu nào. Không thêm thư viện mới.
- 17/17 trang (16 trang cũ + trang mới) hiển thị đúng header và icon trong Edge. **0 lỗi console**; chỉ có các thông báo INFO có sẵn của React Router, kèm 1 INFO về trường mật khẩu ở trang BigQuery.

## 9. Kết quả kiểm thử

| Nhóm | Kết quả | Loại bằng chứng |
|---|---|---|
| Backend (release QA, commit `c15f767`) | **PASS** — 439 đạt, 7 bỏ qua (test BigQuery thật cần bật riêng), 0 lỗi | unit + integration trên DB tạm cách ly (fake BigQuery) |
| — trong đó lịch sử | **PASS** 21/21 | Gồm: chỉ D+1; phiên cuối ngày; phiên lỗi hoặc không hợp lệ giữ phiên trước; phiên mới thay; phiên cũ xong muộn không thay; ghi đồng thời và retry không trùng; ghi lỗi không mất forecast; bất biến; actual cập nhật không đổi forecast; ghép SKU × FC × ngày không nhân dòng; thiếu actual ≠ 0; trạng thái theo tín hiệu thật; WAPE (cả actual = 0 và thiếu actual); lọc, phân trang, Excel; API chỉ đọc; scope mặc định; publish thật ghi lịch sử; migration v3 → v4; allowlist proxy |
| Frontend | **PASS** 106/106 (97 test cũ giữ nguyên, 9 test mới); typecheck OK; build OK | jsdom, backend giả lập |
| Lint | **Chưa cấu hình** | — |
| Bản sao DB thật (01:16) | **PASS** | Số dòng cũ không đổi, data-check (WARN có từ trước + 5 kiểm tra lịch sử OK). API: summary 0,10 s, rows 0,06 s, Excel 3,8 s |
| Rà soát code độc lập | 4 điểm | 3 đã sửa trong `c15f767`, 1 giữ theo thiết kế (mục 5) |
| Diễn tập nâng cấp | **PASS 28/28** | Bản 1.2.4 chính thức trên bản sao, proxy giống production, tunnel Cloudflare riêng: nâng cấp; lịch sử qua URL sau khi chỉ khởi động lại proxy; ghi trả 405, quản trị trả 403; rollback (`-CheckOnly` từ chối, rồi khôi phục backup và quay về 1.2.4 thành công) |
| Production sau deploy | **PASS** | Xem mục 12. Kiểm tra tự động là 17/18; mục còn lại báo nhầm job D-1 thủ công lúc 08:56 (trước deploy), từ lúc deploy không có job mới. |

## 10. Ảnh chụp

- `reports\ui-redesign-125-20261018\index.html`: trước / sau của 17 trang (1440 px), kèm điện thoại 390 px và máy tính bảng 1024 px của trang mới.
- Ảnh trang mới chụp qua link production: thư mục scratchpad `…\scratchpad\p2\shots125h\prod\forecast-history.png`.

## 11. Backup, rollback và Git

- **Backup** (`D:\Buymed\Lightgbm AI\backups\`):
  - `backup-20261018-100109-manual.zip`: online, trước nâng cấp, SHA-256 `FCAEC813451F481C7EA22EE65835532E348F9749A9E3DFD68EB1127F0A59CDD6`;
  - `backup-20261018-100456-pre-migration-v3.zip`;
  - `backup-20261018-100541-cli.zip`.
- **Rollback** (đã diễn tập):
  - `rollback-version -To 1.2.4` sẽ **từ chối** vì schema 4.
  - Cách làm: dừng app → `…\1.2.4\scripts\restore.ps1 -File <đường dẫn đầy đủ của backup-20261018-100109-manual.zip>` → `rollback-version.ps1 -To 1.2.4 -ConfirmToken ROLLBACK-1.2.4`.
  - Cách này mất dữ liệu ghi sau 10:01 (job, snapshot D0). Dữ liệu D-1 nạp lại được.
  - Cách hạ schema có kiểm soát mô tả ở `docs/LICH-SU-FORECAST.md` mục 9.
- **Git:**
  - `dadf77c`, `c15f767` và commit docs (ghi ở mục 15) đều cục bộ, **không push**.
  - Các commit cũ chưa push vẫn giữ nguyên.
  - Không reset, không xóa commit.
- **Checkpoint:** `checkpoints/checkpoint-20261018-v125-history-before.zip` (SHA-256 `03D2C59B…D11A`) và `checkpoint-20261017-v125-ui-before.zip`.

## 12. Xác minh production (chỉ đọc)

**Hệ thống và link:**
- App 1.2.5, `current.txt` = 1.2.5, `storage.json` không đổi (`8D79DBDD…`).
- **URL giữ nguyên:** `https://volumes-jean-angels-configurations.trycloudflare.com`, trả về 1.2.5.
- **cloudflared vẫn là tiến trình cũ (31076).**
- **Readonly proxy:** chỉ khởi động lại proxy (pid 13024 → 26416) để nạp allowlist 1.2.5, cùng cổng 8766 và cùng tham số như launcher. Mất 1,2 giây, 0 lỗi qua link. App không mở trực tiếp ra Internet.
- Link bị ngắt (502) từ 10:04:55 đến 10:07:42, lúc app khởi động lại.
- Qua link: ghi trả 405, quản trị trả 403; các trang cũ trả 200.

**Dữ liệu và lịch chạy:**
- Nguồn đang dùng **BIGQUERY**. Forecast đang dùng `FCR-20261017123417-FCC0EB` không đổi; vẫn 5 forecast run; không có model mới nào được đưa vào dùng.
- **D-1 03:00 (dự phòng 06:00), D-0 08–18h, training 09:00 vẫn BẬT** như trước deploy. Scheduler đang chạy.
- **Không có job nào phát sinh từ deploy hay từ màn hình mới.**
- `data-check` (chỉ đọc): WARN có từ trước (`forecast_series_meta`); 5 kiểm tra lịch sử OK.

**Màn hình mới qua link:**
- Ngày chạy 17/10 → dự báo 18/10, 17.125 dòng.
- Thực tế 18/10 đến 10:00 (snapshot D0) là **3.764, "Tạm tính"**.
- Excel tải được.

**Bất biến khi actual cập nhật:** xem mục 13.

## 13. Forecast bất biến khi Actual cập nhật

**Kết luận:**
- Trên production, forecast D+1 đã lưu **không đổi** qua 2 lần actual cập nhật thật. Bằng chứng là fingerprint trước/sau trên toàn bộ 17.125 dòng.
- Actual cập nhật theo dữ liệu nguồn mới (0 → 3.764).
- Forecast và actual được lưu và truy xuất độc lập.
- Việc kiểm tra không tạo job, training, forecast hay publish nào.
- Còn một phần chờ (mức 3b): bản sao trong bảng lịch sử (ghi lúc 10:07:44) **chưa trải qua** lần cập nhật actual nào trên production. Lần đầu sẽ là D-0 12:00.

### 13.1 Mức 1 — regression test trên DB cách ly: PASS

| Test | Kết quả |
|---|---|
| `test_fp_immutability.py` (scratchpad `…\scratchpad\p2\iso_tests\`, chạy bằng fixture cách ly của repo `backend/tests/conftest.py`; test khẳng định đường dẫn DB là DB tạm, không phải `data\runtime\db\app.db`) | **1 passed** (18/10, khoảng 10:30) |
| `backend/tests/test_v125_forecast_history.py` (trong repo, commit `c15f767`) | **21 passed** (18/10, khoảng 10:30) |

Kịch bản trong `test_fp_immutability.py`:
1. Lưu forecast D+1 (run date 18/10 → 19/10, 4 dòng).
2. Lấy fingerprint sha256 trên mọi dòng đã lưu + giá trị đã publish + con trỏ phiên chính thức.
3. Cập nhật actual 4 lần:
   - D0 08:00 (0 dòng);
   - D0 10:00;
   - D-1 nạp ngày đó, có tín hiệu hoàn tất;
   - nạp lại hồi tố.
4. Sau **mỗi** lần cập nhật, đọc lại forecast và so fingerprint: **giống hệt**.
5. Actual lần lượt là **0 → 5 → 19 → 22**; trạng thái Tạm tính → Tạm tính → Đã hoàn tất → Đã hoàn tất.
6. Số dòng của forecast_runs, forecast_values, training_runs, job_runs, các bảng lịch sử và audit `FORECAST_HISTORY_SELECTED` **không đổi**.
7. `capture` / `reconcile` chạy lại 3 lần: không tạo dòng trùng, fingerprint không đổi.

Các test trong repo đã kiểm tra thêm:
- `test_actual_updates_never_change_the_stored_forecast_nor_create_a_session`: so từng dòng trước/sau một lần nạp lại hồi tố;
- `test_retry_and_reconcile_are_idempotent`;
- `test_concurrent_recording_picks_the_newest_and_never_duplicates`;
- `test_history_rows_are_immutable`: trigger chặn UPDATE / DELETE.

### 13.2 Mức 2 — bản sao dữ liệu production: PASS

- Bản sao 01:16 và diễn tập 09:40 (28/28).
- Lịch sử được ghi nhận từ forecast đã lưu. Kiểm tra `forecast_history_values_unchanged` OK: mọi giá trị lịch sử bằng giá trị đã publish.

### 13.3 Mức 3 — production thực tế (chỉ đọc): PASS cho dữ liệu forecast đã lưu

Kiểm tra lúc **18/10/2026 10:29:06 (giờ VN)**.

**Đối tượng:**
- Run `FCR-20261017123417-FCC0EB`, model `MV-20261017-172653-DA47`, nguồn BIGQUERY.
- Ngày chạy 17/10/2026 (phiên 19:34) → ngày dự báo **18/10/2026**.
- **17.125 dòng** SKU × FC.

**Fingerprint:** sha256 của các dòng `sku|fc|target_date|repr(forecast)|method`, sắp xếp, không phụ thuộc thứ tự.

| Thời điểm / nguồn (đều là trạng thái production thật) | Actual 18/10 trên 17.125 khóa | Số dòng | Tổng forecast | Fingerprint |
|---|---|---|---|---|
| A. `backup-20261017-225247-manual.zip` (17/10 22:52, sau publish 19:34) | chưa có snapshot nào | 17.125 | 71.993,5037 | `b43dda4f310c2b8e193ed76359e3702760765cc0398480997d3d7b447e704754` |
| B. `backup-20261018-100109-manual.zip` (18/10 10:01) | D0 08:00 `SNP-20261018010007-60732B`: 0 dòng đọc → **0**<br>D0 10:00 `SNP-20261018030018-3EF59C`: 1.022 dòng → **3.764** | 17.125 | 71.993,5037 | `b43dda4f…4754` (giống A) |
| C1. Production live, giá trị đã publish (`/api/forecast-runs/…/values`, GET) | — | 17.125 | 71.993,5037 | `b43dda4f…4754` (giống A) |
| C2. Production live, bản sao lịch sử D+1 (`/api/history/rows`, GET; ghi lúc 10:07:44) | actual hiện tại **3.764**, "Tạm tính", nguồn D0, đọc lúc 10:00:15 | 17.125 | 71.993,5037 | `b43dda4f…4754` (giống A) |

**Kết quả:**
- Giữa A và B, actual của 18/10 cập nhật thật hai lần trên production (D0 08:00 rồi 10:00, từ 0 lên 3.764). Forecast D+1 **giống hệt từng dòng**: cùng fingerprint, cùng số dòng, cùng tổng.
- Bản sao lịch sử trên production trùng khớp với giá trị đã publish.
- Actual được đọc từ D0 / D-1 lúc hiển thị, không lưu chung với forecast.

**Phương pháp chỉ đọc:**
- Giải nén **bản sao** `db/app.db` từ hai file backup vào scratchpad, mở bằng `mode=ro`. File backup gốc không bị sửa.
- Production chỉ được truy vấn bằng GET.
- Không chạy D-0 thủ công, không tạo dữ liệu, không ghi gì vào production. Script `…\scratchpad\p2\prod_fp_evidence.py`, kết quả `prod_fp_evidence.json`.

### 13.4 Phần còn chờ (không tạo sự kiện để lấp)

- **Mức 3b — bản sao lịch sử trên production:** chưa xác minh được bằng sự kiện cập nhật actual thực tế.
  - Bảng `forecast_history_values` được tạo lúc deploy (10:07:44). Từ đó tới lúc kiểm tra chưa có lần cập nhật actual nào (D-0 10:00 chạy trước, lúc 10:00:15).
  - Lần cập nhật kế tiếp là **D-0 12:00 theo lịch**. Một kiểm tra chỉ đọc đang chờ sự kiện đó (`…\scratchpad\p2\prod_after_d0_125.ps1`): so tổng, so từng dòng đầu tiên và chạy `data-check`.
  - Mức 1 và mức 3 ở trên đã đủ để kết luận về tính bất biến; mức 3b chỉ là bằng chứng bổ sung.
- **Cập nhật 12:02 — mức 3b: PASS (chỉ đọc).**
  - D-0 12:00 theo lịch chạy thành công (`JOB-20261018050022-4B6AF2`, xong 12:00:35). Nguồn actual của 18/10 chuyển từ `SNP-20261018030018-3EF59C` (10:00) sang `SNP-20261018050026-A83982` (12:00). Tổng actual vẫn 3.764 vì nguồn trả cùng tổng.
  - Đọc lại qua GET lúc 12:02:44: bản D+1 đã lưu của ngày chạy 17/10 có **17.125 dòng, tổng 71.993,5037, sha256 `b43dda4f…4754`** — trùng khớp từng dòng với trước cập nhật. Run duy nhất: FCC0EB. Script `…\scratchpad\p3\prod_fp_after_1200.py`.
  - `data-check` (chỉ đọc): 5 kiểm tra `forecast_history_*` đều OK.
  - Script tự động `prod_after_d0_125.ps1` báo "unchanged: False". **Đây là do script so sai phạm vi, không phải forecast bị đổi.** Script so tổng của khoảng ngày mặc định, và khoảng này nay có thêm phiên ngày chạy 18/10 (71.993,5 + 99.334,0 = 171.327,5).
  - Phiên 18/10 do chủ sở hữu tạo qua UI, không do đợt kiểm tra:
    - 11:37:47 duyệt model ứng viên `TRN-20261018020140-642DB8` (`MODEL_PROMOTED`).
    - Cùng lúc publish `FCR-20261018043737-798B4D` (có cảnh báo). Lịch sử ghi nhận ngay (`AT_PUBLISH`).
    - 11:40:57 lưu thay đổi lịch D-1.

**Trạng thái production trước / sau đợt kiểm tra (10:27:35 → 10:31:47):**

| Mục | Kết quả |
|---|---|
| Phiên bản | 1.2.5 |
| D-1 / D-0 / training | BẬT / BẬT / BẬT, scheduler đang chạy (không đổi) |
| Job mới | Không có. Mới nhất vẫn là `JOB-20261018030014-E7197B` (D-0 10:00 theo lịch). |
| Forecast run | Vẫn 5, forecast đang dùng FCC0EB |
| Training / publish | Không có training hay publish nào do kiểm tra. Training mới nhất vẫn là ứng viên `TRN-20261018020140-642DB8` của lượt 09:00 theo lịch (`PROMOTION_REVIEW_REQUIRED`). |
| URL / proxy | Giữ nguyên; proxy 1.2.5 (pid 26416), cloudflared 31076 |

## 14. Giới hạn và việc cần quyết định

1. **Phiên forecast không chạy hằng ngày.**
   - Pipeline hiện chỉ tạo forecast khi publish. Lượt training 09:00 khi đã có model đang dùng chỉ tạo **model ứng viên chờ duyệt** (hôm nay: `PROMOTION_REVIEW_REQUIRED`).
   - Vì vậy lịch sử D+1 chỉ có ngày ở những ngày có publish. Hiện có **1 ngày BIGQUERY (17/10)**.
   - Muốn có lịch sử mỗi ngày thì cần quyết định nghiệp vụ mới, ví dụ forecast hằng ngày bằng model đang dùng sau D-1. 1.2.5 không tự thêm quy trình đó.
2. **Ngày quá khứ** trước 17/10 (BIGQUERY) không có lịch sử. Màn hình ghi "Chưa có lịch sử forecast được lưu cho ngày này"; không tạo số giả.
3. **Chưa có tín hiệu hoàn tất ngày**, nên mọi thực tế là "Tạm tính" (mục 4). Muốn có "Đã hoàn tất" thì cấu hình `completion_table` trong thiết lập BigQuery; đây là quyết định của chủ sở hữu.
4. **WAPE trong ngày (cần quyết định):**
   - Thực tế của ngày đang diễn ra là số lũy kế D0 đến giờ đọc. Nó được hiển thị và tính vào WAPE với nhãn "Tạm tính", đúng chữ của yêu cầu.
   - Vì so ngày chưa trọn với forecast cả ngày, WAPE lúc 10:00 hôm nay hiện **1.832% "Tạm tính"**, dễ gây hiểu lầm.
   - Nếu muốn, bản 1.2.6 có thể chỉ hiện thực tế trong ngày mà **không** tính sai lệch / WAPE cho tới khi D-1 nạp ngày đó. Tôi không tự đổi quy tắc và không deploy lần hai.
5. **Sự cố production hôm nay, không liên quan tới thay đổi của tôi:**
   - D-1 lịch 03:00 **FAILED** lúc 06:08 với `SOURCE_INCOMPLETE`: nguồn có 0 dòng của 17/10, so với trung bình 7 ngày là 19.002. Bảng nguồn được làm mới khoảng trưa D+1.
   - 08:56 có người chạy D-1 thủ công, thành công. Training 09:00 tạo model ứng viên.
   - Giờ chạy D-1 so với giờ nguồn sẵn sàng là quyết định mở từ trước (R3).
6. **Endpoint cũ khác cách tính:** `/api/forecast-runs/{id}/accuracy` (có từ trước) chỉ ghép các ngày có dòng trong `demand_daily`. Màn hình lịch sử theo quy tắc panel. Không sửa endpoint cũ.

## 15. Việc tiếp theo nhỏ nhất

| Ai | Việc |
|---|---|
| Chủ sở hữu | Quyết định mục 14.4 (WAPE trong ngày) và mục 14.1 (có forecast hằng ngày hay không). Push các commit cục bộ khi đồng ý. |
| Kỹ sư | Không cần làm gì thêm cho 1.2.5. |

**Commit docs sau deploy:** `d60f81e` (cục bộ, không push).

- Commit gồm `docs/CHECKPOINT.md` (deploy + bằng chứng bất biến) và `CHANGELOG.md` (tham chiếu báo cáo).
- **Báo cáo này không nằm trong Git:** `/reports/` được `.gitignore` bỏ qua theo quy định dự án (`docs/GITHUB_WORKFLOW.md`: báo cáo runtime chứa thông tin riêng của máy). Bước kiểm tra trước commit cũng chặn mọi file `reports/`.
- Nhánh `main` đang đi trước `origin/main` 16 commit, chưa push.
