# Demand Forecasting 1.2.1 (mã nguồn) — Link dashboard từ xa, sửa BigQuery D-0 / D-1, sẵn sàng huấn luyện

Ngày 17/10/2026, 15:25–16:40 (giờ Việt Nam). Máy: PC Windows của chủ dự án.

Trạng thái theo AGENTS.md §11: **READY_FOR_PRODUCTION** — mã đã sửa và kiểm thử. Còn chờ chủ dự án cho phép commit, đóng
gói và deploy 1.2.1; lô này được yêu cầu không commit.

Production vẫn chạy **1.2.0** và không bị thay đổi:
- fingerprint DB và cấu hình trước/sau giống hệt nhau;
- thao tác ghi duy nhất là một bản sao lưu online.

## A. Link xem từ xa

| Mục | Kết quả |
|---|---|
| File | `Start-DemandForecast-Remote.bat`, `Stop-DemandForecast-Remote.bat` (thư mục dự án), `scripts\remote\remote-access.ps1`, `scripts\remote\readonly_proxy.py`, `REMOTE_ACCESS_GUIDE.md` |
| Kiến trúc | Cloudflare Quick Tunnel (miễn phí, không tài khoản, không VPS) → **proxy chỉ đọc** `127.0.0.1:8766` → ứng dụng `127.0.0.1:8765`. Tunnel không bao giờ trỏ thẳng vào cổng ứng dụng. Ứng dụng giữ chặn Host lạ (chống DNS rebinding) và chặn CSRF |
| Frontend | Gọi API bằng đường dẫn tương đối, không có `localhost` cố định, không SSE/WebSocket → chạy qua HTTPS không cần sửa |
| Quyền | Chỉ cho GET/HEAD. Mọi thao tác ghi trả **405** `REMOTE_READ_ONLY`; trang quản trị trả **403** `REMOTE_FORBIDDEN` (đường dẫn, chẩn đoán, backup, audit, danh tính Google, trạng thái BigQuery, OpenAPI). JSON ra ngoài được xóa đường dẫn local và trường danh tính. Giới hạn 300 yêu cầu/phút mỗi người xem, 6 yêu cầu đồng thời |
| cloudflared | 2026.10.1, tải từ `github.com/cloudflare/cloudflared`. SHA-256 khớp trang phát hành, chữ ký Cloudflare **Valid**. Lưu ở `%LOCALAPPDATA%\DemandForecastRemote\bin`; mỗi lần chạy đều kiểm tra lại |
| Link thật | Đã tạo và kiểm tra **2 link thật**: `https://development-builder-apartments-participating.trycloudflare.com` và `https://attended-about-mainstream-techrepublic.trycloudflare.com`. **Cả hai đã dừng** sau kiểm tra (trả 530/502). Link Quick Tunnel đổi mỗi lần khởi động; chủ dự án bấm Start để lấy link gửi sếp |

Kiểm tra qua HTTPS thật, dữ liệu production:
- `/`, `/results`, JS 543 KB và CSS tải được, có banner "CHỈ ĐỌC" và `noindex`.
- `/api/health` và `/api/dashboard` trả dữ liệu thật: nguồn BIGQUERY, dữ liệu 01/01–16/10/2026, 1.349.388 dòng.
- Edge headless (hồ sơ tạm) hiển thị SPA đầy đủ, không có lỗi mixed content hay CORS.
- 5 thao tác ghi → 405. 6 trang quản trị → 403.
- Không lộ đường dẫn `D:\`/`C:\`.
- Log truy cập chỉ có máy này.

Giới hạn vận hành:
- máy bật, có Internet, không ngủ;
- link đổi khi khởi động lại;
- ai có link đều xem được;
- Quick Tunnel không cam kết uptime, không tương đương dịch vụ cloud độc lập.

## B. BigQuery D-0

**Nguyên nhân gốc rễ** của `d0: no D-0 SQL version validated by BigQuery`, kiểm tra trên production:
1. Luồng D-0 ở chế độ SQL. Hai phiên bản ngày 15/10 (v1 là SQL người dùng, v2 là bản đề xuất) **chưa từng được gửi BigQuery
   xác nhận**, nên `active_version_id = null` → `SQL_NOT_VALIDATED`.
2. Lỗi thiết kế: D-0 mượn **ánh xạ D-1**.
   - Cột bắt buộc, khóa mặc định và cột ngày đều theo tên D-1.
   - Ở chế độ TABLE, bảng D-0 phải có mọi cột nội bộ D-1 ánh xạ (gồm `sales_price`) và cột phân vùng của D-1.
3. Ở chế độ SQL không có lọc ngày: dòng của ngày khác vẫn bị **cộng** vào snapshot, chỉ có cảnh báo.

**Schema D-0 thật** (metadata BigQuery 17/10, 12 cột):
`fc_code STRING, created_date DATE, so_code STRING, order_status STRING, product_id INTEGER, sku_code STRING,
item_code STRING, seller_code STRING, sku_system_status STRING, demand_quantity INTEGER, outbound_quantity INTEGER,
sales_price FLOAT`. Bảng có 8.454 dòng, location `asia-southeast1`.

**Đã sửa (1.2.1):**
- **Ánh xạ D-0 riêng** `bigquery.d0_mapping`:
  - mặc định theo schema thật: `sku_id←sku_code`, `fc_id←fc_code`, `order_qty←demand_quantity`, `order_date←created_date`,
    `order_id←so_code`;
  - có trang sửa và nút gợi ý đọc schema thật;
  - không đụng ánh xạ, hash hay chế độ sản xuất của D-1.
- **Xác nhận SQL D-0** gồm dry-run, đối chiếu schema với ánh xạ D-0, rồi **chạy thật** phép tổng hợp của hôm nay (không ghi gì).
  - Kết quả lưu sha256 SQL và mã ánh xạ D-0.
  - Đổi SQL, ánh xạ hoặc khóa thì phải xác nhận lại (`D0_REVALIDATE_REQUIRED`).
  - Lỗi được nêu cụ thể theo trường/cột.
- **Job D-0:**
  - chỉ tính ngày hôm nay theo giờ Việt Nam;
  - đếm dòng khác ngày, thiếu ngày, thiếu SKU, FC hoặc số lượng, số lượng âm;
  - đo trùng trên dòng hôm nay;
  - ghi `forecast_match` (chuỗi/số lượng chưa có dự báo); dòng không có dự báo vẫn giữ trong snapshot;
  - không ghi `demand_daily`, không chuyển sang bảng D-1.

**Kết quả trên BigQuery thật** (code 1.2.1, bản sao DB production):

| Phiên bản / kiểm tra | Kết quả |
|---|---|
| Kiểm tra bảng D-0 với ánh xạ D-0 | **PASSED**; 7 cột không cần được bỏ qua |
| v1 (SQL người dùng) | Dry-run đạt: SELECT, đọc `fact_order` / `fact_order_item` / `adhoc_pm_master_sku`, khoảng 831 MB mỗi lần |
| v2 (đề xuất) | **BigQuery từ chối**: `No matching signature for function DATE`. `DATE(a.created_at, 'Asia/Ho_Chi_Minh')` không hợp với kiểu của `created_at` |
| Phiên bản mới `SELECT * FROM \`lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0\` WHERE created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')` | **VALID**: dry-run khoảng 1 MB, chạy thật ngày 17/10 cho 8.454 dòng, 2.142 SKU×FC, tổng 34.618; 0 lỗi, 0 khác ngày, 0 trùng hoàn toàn, **48 dòng trùng khóa** (`so_code, sku_code, fc_code, created_date`) |
| Chạy D-0 với chính sách khóa hiện tại `BLOCK` | Bị chặn `BQ_KEY_NOT_UNIQUE`, không ghi gì. Kiểm tra nghiệp vụ được giữ |
| Chạy D-0 với `SUM_ALL` (chỉ trên bản sao) | Snapshot 2.142 SKU×FC. Chạy lại cùng khóa → `ALREADY_SUCCEEDED`. Chưa có dự báo hôm nay cho phạm vi BigQuery nên 2.142/2.142 chuỗi được ghi nhận "chưa đối chiếu được" |

**Readiness D-0 cuối cùng:**
- **Production (1.2.0):** chưa sẵn sàng, `SQL_NOT_VALIDATED`, luồng **TẮT**.
- **Bản sao chạy 1.2.1:** sau khi xác nhận phiên bản mới thì **sẵn sàng**, luồng vẫn **TẮT**; có ghi chú vấn đề dữ liệu
  (trùng khóa).

Lịch D-0 (08:00–18:00 mỗi 2 giờ, chạy bù `LATEST_ONCE`) không đổi.

## C. D-1 và huấn luyện

**Nguyên nhân chặn:** luồng D-1 **TẮT** (`d1_enabled=false`, lịch 03:00 / dự phòng 06:00 không đổi). Huấn luyện BigQuery chỉ
chấp nhận job **D-1 theo lịch** `D1_SYNC:<ngày>`.
- D-1 hôm nay thật sự đã **thành công**: `JOB-20261017012623-2A31B7`, chạy tay 08:26–08:30, nạp dữ liệu đến 16/10, 1.349.388
  ngày-chuỗi. Đây không phải lỗi hiển thị.
- Nhưng vì chạy tay nên không được tính, và giao diện vẫn báo "chờ D-1 hôm nay thành công".

**Đã sửa:**
- "D-1 hôm nay thành công" = một lần D1_SYNC **thành công trong ngày (giờ VN)**, theo lịch, thử lại hoặc chạy tay; không phải
  bổ sung khoảng; nạp đến hôm qua. Lần chạy tay đi qua đúng kiểm tra tín hiệu/đủ dữ liệu như lần theo lịch.
- Readiness ghi rõ:
  - `D1_TODAY_SUCCEEDED`: job nào, giờ nào, dữ liệu đến ngày nào;
  - `TRAIN_WAITING_FOR_TODAY_D1`: kèm trạng thái job D-1 hôm nay;
  - `TRAIN_WAITS_FOR_D1`: luồng D-1 tắt và chưa có D-1 thành công.
- D-1 thất bại thì huấn luyện không chạy (đã test).

**Trạng thái:**
- D-1: thành công hôm nay (chạy tay). Luồng D-1 TẮT, không đổi.
- Huấn luyện:
  - Production 1.2.0 vẫn báo chờ D-1.
  - Bản sao 1.2.1 báo **sẵn sàng**, scheduler lập kế hoạch `TRAIN_PUBLISH:2026-10-17` chạy bù một lần (`RUN_ONCE`).
  - **Không chạy huấn luyện** trong lô này.
- Quality gate: ngưỡng không đổi (WAPE ≤ 0,60, |bias| ≤ 0,20). Lần huấn luyện trước `QUALITY_GATE_FAILED` vẫn là kết quả
  đánh giá hợp lệ; model không đạt thì không publish.

## D. Kiểm thử

| Loại | Kết quả |
|---|---|
| Unit + tích hợp backend (BigQuery giả lập), toàn bộ | **391 passed**, 0 failed, 0 skipped (gồm 17 test D-0/D-1 mới, 43 test proxy) — `logs\development\tests_20261017_161413.log` |
| BigQuery **thật** (opt-in `DF_REAL_BQ=1`, chỉ đọc) | 5/5 test D-0 mới (lọc ngày VN, TIMESTAMP→ngày VN, lý do loại dòng, trùng, bảng D-0 thật, phân loại lỗi) + 2/2 test cũ — nằm trong 391 ở trên |
| Frontend | typecheck đạt; vitest **69/69** (3 test mới); build đạt |
| Bản sao DB production + BigQuery thật | Mục B/C. Bằng chứng: `reports/demandforecast_v121_iso_real_bq_20261017.json` |
| Tunnel thật qua HTTPS | Mục A. Các tình huống: chạy lại không trùng; dừng → link chết, ứng dụng vẫn chạy; khởi động lại → link mới; ứng dụng chậm 21 giây; ứng dụng không khởi động; không tải được cloudflared; dịch vụ tunnel không trả lời; file cloudflared bị sửa → từ chối; ZIP giải nén nơi khác chạy được |
| Chưa làm được | Deploy 1.2.1 lên production (cần commit — bị cấm trong lô này). Mở link trên máy của sếp (chỉ kiểm tra từ máy này và Edge headless). Kịch bản "launcher khởi động ứng dụng production đang tắt" chỉ thử bằng ứng dụng giả lập, vì không được dừng ứng dụng production |
| Lint | Chưa cấu hình |

Các test cũ được **cập nhật theo yêu cầu mới**:
- `test_v116`: dòng khác ngày nay bị loại, trước chỉ cảnh báo;
- `test_v120_sources`: đổi ánh xạ D-1 không còn làm hỏng kiểm tra D-0;
- `test_v118` và `test_bigquery`: định dạng kết quả D-0 mới và kiểm tra bảng trước khi chạy.

Không test nào bị xóa hay làm yếu đi.

**File đã sửa** (24 file đã có, 10 file mới; chưa commit):
- Backend:
  - sửa: `settings_service.py`, `bq/connector.py`, `bq/sql_sources.py`, `bq/source_tables.py`, `jobs/flows.py`,
    `jobs/scheduler.py`, `jobs/runner.py`, `sync.py`, `messages.py`, `api/bq_routes.py`, `__init__.py` (1.2.1);
  - mới: `bq/d0_feed.py`.
- Frontend: `pages/SqlSources.tsx`, `pages/Schedules.tsx`, `i18n.tsx`, `package.json` (1.2.1); mới `v121.test.tsx`.
- Test: mới `test_v121_d0.py`, `test_v121_d0_real_bq.py`, `test_v121_remote_proxy.py`; cập nhật `test_v116.py`,
  `test_v118.py`, `test_v120_sources.py`, `test_bigquery.py`.
- Remote (mới): `Start-DemandForecast-Remote.bat`, `Stop-DemandForecast-Remote.bat`, `scripts/remote/*`,
  `REMOTE_ACCESS_GUIDE.md`.
- Tài liệu: `docs/BIGQUERY.md` §15, `docs/SCHEDULER.md`, `docs/VAN-HANH.md`, `docs/CHECKPOINT.md`, `CHANGELOG.md`.
- Line ending từng file giữ nguyên; PS1 và BAT là ASCII; quét secret sạch.

## E. Bàn giao

| Mục | Đường dẫn |
|---|---|
| Launcher | `D:\Buymed\Lightgbm AI\Start-DemandForecast-Remote.bat` (dừng: `Stop-DemandForecast-Remote.bat`) |
| ZIP | `D:\Buymed\Lightgbm AI\dist\DemandForecast-RemoteAccess-1.2.1-20261017.zip`, SHA-256 `7EEC7A1F584E1B657AA6B872E8DC833753F10BB5C889C9A4497C59BFF936558B`. Gồm 5 file, không có ứng dụng, dữ liệu hay credentials |
| Báo cáo | File này; bằng chứng `reports/demandforecast_v121_iso_real_bq_20261017.json` |
| Checkpoint / backup | `checkpoints\source-1.2.0-before-1.2.1-d0-remote-20261017-153536.zip`; `backups\backup-20261017-153542-manual.zip` (SHA-256 421AA88F…C200) |

**Bước còn lại cho chủ dự án (tối đa 3):**
1. **Gửi link cho sếp ngay** (không cần chờ 1.2.1): bấm đúp `Start-DemandForecast-Remote.bat`, dán link (đã có trong
   clipboard).
2. **Cho phép commit, phát hành và deploy 1.2.1**, hoặc tự chạy `scripts\release.ps1` rồi `scripts\deploy-upgrade.ps1`.
   - Lưu ý: nếu deploy vào ngày đã có D-1 thành công (ví dụ hôm nay), huấn luyện theo lịch sẽ **chạy bù một lần ngay**
     (`RUN_ONCE`, khoảng 12 phút, vẫn qua quality gate).
   - Muốn tránh thì chọn chạy bù `SKIP` trước khi deploy.
3. Sau khi deploy, ở trang **SQL nguồn & đồng bộ → D-0**:
   - lưu SQL `SELECT * FROM \`lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0\` WHERE created_date =
     CURRENT_DATE('Asia/Ho_Chi_Minh')`;
   - bấm **Xác nhận với BigQuery**;
   - chọn **Khi khóa bị trùng**: `SUM_ALL` (như D-1, nếu nhiều dòng đơn cùng SKU là nhu cầu thật) hoặc giữ `BLOCK`.

   Bật luồng D-0 hay D-1 vẫn là quyết định riêng của chủ dự án.

---

## Phụ lục — Deploy 1.2.1 và link cho sếp (17/10/2026, 16:37–16:58)

Chủ dự án yêu cầu deploy 1.2.1 và tạo link. Chỉ cấm push Git và thay đổi D-0.

| Bước | Kết quả | Bằng chứng |
|---|---|---|
| Phiên bản trước / sau | 1.2.0 → **1.2.1** | `/api/health` 1.2.1, `current.txt` 1.2.1, tiến trình chạy từ `Programs\DemandForecast\1.2.1\python\python.exe` |
| Chạy bù huấn luyện | `RUN_ONCE` → **`SKIP`** (đặt và đọc lại trước khi deploy; chỉ đổi đúng trường này) | `PUT /api/schedules/train`, lịch sử cấu hình "schedule train: train_catchup_policy (UI)" |
| Commit / gói | Commit cục bộ `94fd17b` (34 file, **không push**). Gói `DemandForecast-1.2.1-win64-portable.zip`, SHA-256 `1BE9E270AC7830705FFF9359C80AF8087E2B15A66D0DCEC3D59052BC1A534DC7`. QA 391 (gồm BigQuery thật) + 69 vitest | `scripts\release.ps1` exit 0 |
| Deploy | `deploy-upgrade.ps1`: kiểm tra trước đạt, backup online `backups\backup-20261017-164813-manual.zip` (SHA-256 7AE1E5AD…9949) và `backup-20261017-165044-cli.zip`, migration 3→3 (không đổi schema), integrity ok → `UPGRADE OK` | `logs\runtime\deploy-20261017-164812.log` |
| Bảo toàn dữ liệu | Không đổi: `demand_daily` (BIGQUERY 1.349.388 / 41.808.940; DEMO 38.568), mọi section cấu hình (hash), run huấn luyện, forecast, snapshot D-0, trạng thái D-1. Chỉ thêm 1 job (huấn luyện SKIPPED) và 1 dòng audit. `data-check` = WARN cũ (forecast DEMO trước migration 0003). `storage.json` không đổi | fingerprint trước/sau (DB mở chỉ đọc) |
| Scheduler sau deploy | `TRAIN_PUBLISH:2026-10-17` **SKIPPED** (`MISSED_SLOT_NO_BACKFILL`), không có huấn luyện. D-1 TẮT, D-0 TẮT (`SQL_NOT_VALIDATED`, chi tiết "v2 UNCHECKED, v1 UNCHECKED"), huấn luyện BẬT (ghi chú D-1 hôm nay đã thành công) | `/api/schedules`, `/api/jobs` |
| Rollback | `rollback-version.ps1 -To 1.2.0 -CheckOnly`: khả thi, không cần khôi phục DB | |
| Link | **https://volumes-jean-angels-configurations.trycloudflare.com** (tạo bằng `Start-DemandForecast-Remote.bat`; **đang chạy**) | `%LOCALAPPDATA%\DemandForecastRemote\run\tunnel.json` |

Kiểm tra link:
- **Đường đi:** tunnel chỉ trỏ vào proxy `127.0.0.1:8766`; proxy chạy bằng Python của 1.2.1. Tên miền phân giải qua DNS
  công cộng (1.1.1.1 và 8.8.8.8 → 104.16.230/231.132, biên Cloudflare). Mọi yêu cầu HTTPS dưới đây đi từ máy này ra
  Internet tới Cloudflare rồi qua tunnel về.
- **Đọc:** `/`, `/results`, `/schedules`, JS, CSS và 8 API trả 200. Dữ liệu thật: BIGQUERY, 01/01–16/10, 1.349.388
  ngày-chuỗi, D-1 cuối `JOB-20261017012623-2A31B7`. Không lộ đường dẫn (`data_dir` = `<hidden>`).
- **Chặn:** 10 trang quản trị → 403. 10 thao tác ghi → 405, gồm chạy huấn luyện, chạy/bật D-0, sửa SQL/ánh xạ D-0, backup,
  tắt máy chủ. Log proxy xác nhận các yêu cầu này **không tới ứng dụng**; job trên production không đổi.
- **Trình duyệt:** Edge headless hiển thị 3 trang (Tổng quan, Lịch chạy dữ liệu, SQL nguồn), banner "CHỈ ĐỌC", **0 lỗi**
  mixed content, CORS hay JS.
- **Chưa làm được:** mở link từ một mạng khác hoặc máy khác (môi trường này chỉ có máy này; không gửi link cho dịch vụ bên
  thứ ba để thử).

**Lưu ý về `SKIP`:**
- Luồng D-1 đang tắt và nguồn chỉ có ngày hôm qua vào khoảng 08:00–14:00. Với `SKIP`, mốc huấn luyện 09:00 sẽ bị bỏ qua mỗi
  ngày nếu D-1 chưa xong trước 09:20; huấn luyện tự động thực tế không chạy.
- Huấn luyện tay trên giao diện vẫn làm được.
- Muốn huấn luyện tự chạy sau D-1 chạy tay thì đổi lại `RUN_ONCE`, hoặc quyết định lại giờ D-1 / huấn luyện.

**Các bước D-0 còn lại (chưa làm theo chỉ đạo):**
1. Trang *SQL nguồn & đồng bộ → D-0*: lưu SQL `SELECT * FROM
   \`lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0\` WHERE created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')`,
   rồi bấm **Xác nhận với BigQuery** (dry-run khoảng 1 MB + chạy thử hôm nay).
2. Chọn *Khi khóa bị trùng*: `SUM_ALL` (như D-1) hoặc giữ `BLOCK`. Với `BLOCK`, 48 dòng trùng khóa ngày 17/10 sẽ chặn
   snapshot.
3. Muốn chạy D-0 theo lịch thì bật luồng D-0 ở trang *Lịch chạy dữ liệu*. Bật không chạy ngay; mốc đã lỡ trong ngày chỉ chạy
   bù một lần theo `LATEST_ONCE`.
