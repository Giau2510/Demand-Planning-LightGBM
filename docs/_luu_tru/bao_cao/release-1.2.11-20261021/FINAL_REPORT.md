# Báo cáo cuối - release 1.2.11: sửa grain item_code, quy tắc trùng theo trạng thái, D-1, huấn luyện, link công khai (21/10/2026, 16:02-18:30)

**Trạng thái:**

| Phần | Trạng thái |
|---|---|
| Release 1.2.11 | **READY_FOR_PRODUCTION** (đã deploy và xác minh trên production) |
| Huấn luyện | **BLOCKED_DATA_SAFETY**: quy tắc giờ mở bán SKU × FC của 6 khóa nhiều listing chưa được xác lập |
| Link công khai ổn định | **BLOCKED_EXTERNAL_SETUP**: cần chọn nhà cung cấp và tài khoản cho URL cố định |

Không push. Không đổi lịch, Price, `customer_id`, target hay model đang dùng.

## 1. Nguyên nhân gốc và thay đổi mã

**item_code / MULTI_ITEM.**

- `item_code` **chưa từng** là khóa: khóa là `sku_code` × `fc_code` × ngày ở D-1, ở mọi bảng tiêu thụ và trên dữ liệu thật.
- `MULTI_ITEM` không chặn chỉ vì có nhiều item code. 95 / 101 khóa nhiều item có cùng giờ và đều `OK`.
- 6 khóa bị chặn vì **giờ mở bán khác nhau giữa hai listing của hai miền bán cùng xuất từ một FC**. Không có giá trị SKU × FC.
  Bỏ thông tin item cũng không làm các khóa này hợp lệ, vì khi đó chúng thành `CONFLICT`.
- Đã thêm test chứng minh: chặn hay không không phụ thuộc số item (`test_whether_a_key_blocks_never_depends_on_its_item_codes`).
- `item_code` vẫn được giữ làm bằng chứng nguồn: đếm item, nhãn `MULTI_ITEM`, báo cáo.

**Quy tắc giờ mở bán SKU × FC (đã điều tra, chưa xác lập):**

- Giờ của một item = thời gian ở trạng thái `NORMAL` hoặc `LIMIT` trong ngày. Dựng lại từ nhật ký trạng thái khớp 2.190 / 2.191
  item-ngày.
- Không có quy tắc gộp nhiều listing đã được xác minh hay phê duyệt.
- Bảng `fact_classification_sku_history` gắn một listing cho mỗi FC × SKU × tháng nhưng không dùng được làm quy tắc:
  - thiếu 1-43% khóa mỗi tháng;
  - 184 trường hợp gắn listing của miền kia;
  - dùng nó sẽ đổi giá trị của 19 khóa một item.
- Không áp dụng MAX, MIN, trung bình hay hợp khoảng. Không điền 24.

**Quy tắc trùng theo trạng thái (thay sửa 7.1), `backend/app/bq/connector.py`:**

- **WAIT_TO_CONFIRM** (có hoặc chưa có `so_code`) được **miễn** kiểm tra trùng (`PENDING_STATUSES`, `_pending_cond` chỉ cần
  `order_status`):
  - không chặn, `DROP_EXACT` không loại, giữ đủ dòng và số lượng;
  - đếm riêng trong `pending_orders`, kể cả dòng giống mọi cột nguồn (chỉ để theo dõi, có thể là nhân dòng do join).
- **Trạng thái khác:** giữ bảo vệ trên các cột ánh xạ **trừ `item_code`** (`DUP_NOT_COMPARED_FIELDS`):
  - dòng đơn bị nhân theo item thì chặn;
  - nhóm không trộn trạng thái;
  - `customer_id` không là khóa.
- Cùng một quy tắc được dùng ở 4 chỗ: cổng trùng (`_dup_sql`), kiểm tra toàn kỳ, dòng kiểm soát D-1 (`_exact_dup_rows_expr`)
  và `DROP_EXACT` (`ROW_NUMBER` theo cột so sánh).
- Truy vấn tổng hợp D-1 không còn đọc toàn dòng nguồn: 1,35 GB thay vì 1,70 GB.

**Các file khác:**

- `dup_report.py`: văn bản quy tắc, `compared_on`.
- `BigQuery.tsx` / `i18n.tsx`: dòng WAIT_TO_CONFIRM "miễn kiểm tra trùng".
- `scripts/remote/readonly_proxy.py` (mục 7).
- Tài liệu: `docs/BIGQUERY.md` §4, §11f, §13; `DATA-MODEL.md`; CHANGELOG.

**Commit cục bộ:** `9ee5a4a` "Release 1.2.11" (22 file, gồm cả test / tài liệu chưa commit của đợt trước).

## 2. Bằng chứng item_code không tạo khóa hay MULTI_ITEM giả

- **Test:**
  - `test_item_code_is_never_a_compared_column`;
  - `test_whether_a_key_blocks_never_depends_on_its_item_codes`;
  - `test_v129h` (SQL không đọc hậu tố; FC chỉ từ `fc_code`);
  - `test_v1210_*` (6 mẫu thật).
- **Dữ liệu thật:**
  - 101 khóa nhiều item: 95 `OK`, 6 `MULTI_ITEM`; 101 / 101 khóa lưu đúng trạng thái và đúng số lượng;
  - 7 / 7 bảng tiêu thụ có khóa SKU × FC duy nhất, không có cột item;
  - preview toàn kỳ: `MULTI_ITEM` đúng 6, không có khóa nào khác.

## 3. Bằng chứng WAIT_TO_CONFIRM được miễn và trùng thật vẫn bị bắt

**BigQuery thật trên dòng inline: 14 passed.**

- Dòng WAIT_TO_CONFIRM giống mọi cột nguồn, có mã, hoặc cùng khách: qua cổng, giữ đủ số lượng.
- Đơn COMPLETED trùng: chặn. NULL `so_code` ở trạng thái khác trùng: chặn.
- Dòng nhân theo `item_code`: chặn.
- Trạng thái trộn: không gộp nhóm.
- DROP_EXACT bỏ đúng 2 dòng.

**Trên bảng thật:**

- 0 nhóm trùng ngoài WAIT_TO_CONFIRM.
- 904 dòng WAIT_TO_CONFIRM được miễn (46 nhóm / 136 dòng giống ở cột so sánh, mỗi dòng một khách, 0 giống mọi cột).

## 4. D-1 toàn kỳ và đối soát

Chi tiết: `DATA_RECONCILIATION.md`.

| Bước | Kết quả |
|---|---|
| Preview toàn kỳ `BFP-20261021110908-3FC80A` (01/01-20/10) | READY; 8.979.752 dòng, 0 trùng, 0 khóa mới / đổi / bị loại; giờ mở bán OK 1.360.907 / MULTI_ITEM 6 |
| Đối soát độc lập trước D-1 | app = nguồn: 1.360.913 khóa / 42.088.223 đơn vị |
| D-1 dry run | READY |
| D-1 `JOB-20261021111824-17023B` ("Chạy ngay") | SUCCEEDED 18:18:24-18:20:04; cửa sổ 17-20/10; 11.995 khóa, 0 thay đổi |
| Đối soát sau D-1 | khớp tuyệt đối toàn kỳ, 0 lệch giờ mở bán |
| Chốt actual | 293 ngày FINALIZED, 0 chặn |
| Trước đó trong ngày, trên 1.2.10 | D-1 `JOB-20261021081102-643FC7` nạp 20/10 (3.037 khóa / 78.266 đơn vị) |

Không backfill (không cần: 0 khác biệt). Không ngày lịch sử nào bị ghi lại.

## 5. Huấn luyện

**Không chạy trên production**, nên không có training ID mới, metric hay so sánh baseline.

- Lý do: cổng bắt buộc `OPEN_HOURS_INVALID` - 6 dòng `MULTI_ITEM` (09/02-26/08) trên 1.360.913 dòng của cửa sổ.
- Không có giá trị giờ mở bán SKU × FC đã xác lập cho 6 khóa; huấn luyện với giá trị bịa là trái yêu cầu.
- Bằng chứng cổng vẫn chặn:
  - diễn tập r12 trên bản sao 1.2.11: job `JOB-20261021103524-7A3984` FAILED `OPEN_HOURS_INVALID`, không có model;
  - production: lúc 16:35:56 có người bấm "Chạy ngay" huấn luyện trên trang Lịch (`POST /api/schedules/train/run`, không phải
    tôi). Job `JOB-20261021093556-37D600` FAILED `OPEN_HOURS_INVALID` sau 6 s, không tạo training run, không đổi model.
- Lịch 07:00 hôm nay: SKIPPED.

## 6. Phiên bản production và kiểm tra sau deploy

**Trước / sau:**

| | Trước | Sau |
|---|---|---|
| Phiên bản | 1.2.10 | **1.2.11** |
| PID | 30096 | 7316 |
| Gói | | `dist\DemandForecast-1.2.11-win64-portable.zip`, SHA-256 `5A7A73AA6283F45E49378BAE0509348477CD73C14A12204F38D8E6F0BB580886` |

Gói build từ commit `9ee5a4a`, dirty=false, source fingerprint `88A501578BD3CEA7`.

**Deploy:**

- Gates PASS (18:00:51); backup chính thức đã xác minh (18:03).
- `deploy-upgrade -ConfirmToken UPGRADE-1.2.11`: 18:03:42-18:08:17, exit 0, 275 s, "UPGRADE OK".
- Diễn tập cùng gói: gián đoạn 266 s.
- Không migration (schema 9).

**Kiểm tra sau deploy: 7/7 PASS.**

- health 1.2.11.
- 22 GET đều 200: 5 trang giao diện, dashboard, status, registry, lịch sử + Excel, forecast, sync, trùng, lịch.
- Trang BigQuery có trường `pending_orders`.
- data-check WARN, không FAIL: `open_hours_window_ready` (6 MULTI_ITEM) và `forecast_series_meta` có từ trước.
- `rollback-version -To 1.2.10 -CheckOnly` exit 0.
- Scheduler chạy.
- Lịch, thiết lập, forecast `FCR-20261020082402-A42C91`, model `TRN-20261020054540-D7EEF6`: giống hệt trước deploy.
- `storage.json` không đổi.

## 7. Link công khai chỉ đọc cho lãnh đạo

**Kết quả: BLOCKED_EXTERNAL_SETUP.** Chưa có URL cố định. Không công bố link tạm.

**Hiện trạng:**

- Quick Tunnel cũ (cloudflared PID 35236, chạy từ 19/10) đã mất kết nối: `/ready` 503.
- Proxy cũ (PID 16144, mã trước 1.2.11, chạy bằng python của bản 1.2.6) chỉ nghe 127.0.0.1:8766.
- Hiện **không có gì công khai**.
- Máy không có tài khoản Cloudflare đăng nhập (`~/.cloudflared` không có), không có Tailscale hay ngrok.
- URL Quick Tunnel đổi mỗi lần khởi động lại, nên không đạt yêu cầu "ổn định".

**Đã làm:**

1. Kiểm toán mọi endpoint mà proxy cho phép (agent đọc mã). Phát hiện `GET /api/data-quality` **ghi** một dòng
   `validation_reports` khi chưa có cache (`data_routes.py:203-210`, `quality.py:123-143`). HEAD trên `/api` có thể chạy
   handler.
2. Sửa proxy (trong 1.2.11, file `scripts/remote/readonly_proxy.py`):
   - chặn `/api/data-quality` (`/api/data-quality/history` vẫn mở);
   - từ chối HEAD trên `/api`;
   - test `test_v121_remote_proxy.py` 44 passed.
3. Kiểm chứng cục bộ trước production trên cổng tạm 8896, không tunnel: 28/29 PASS.
   - Đọc được: 200.
   - Bị từ chối: 6 ghi (405), HEAD `/api` (405), data-quality (403), 7 API quản trị (403).
   - Không lộ đường dẫn.
   - Kill rồi khởi động lại: phục hồi.
   - 1 FAIL là do PowerShell chuẩn hóa `../`. Gửi nguyên văn bằng `curl --path-as-is` nhận 400; đường dẫn đã chuẩn hóa chỉ trả
     `index.html`.

**Kiến trúc đề xuất (chưa triển khai, chờ quyết định):**

```text
lãnh đạo → https://<tên cố định>
         → [Cloudflare Named Tunnel, Windows service, tự khởi động / tự nối lại]
         → 127.0.0.1:8766 read-only proxy
           (tác vụ khởi động cùng Windows, tự khởi động lại; script đặt ở thư mục cố định ngoài thư mục phiên bản)
         → 127.0.0.1:8765 = phiên bản production hiện hành
```

- Nâng cấp hoặc rollback app không đổi URL, và link tự phục vụ phiên bản mới.
- Kiểm soát truy cập: Cloudflare Access (OTP theo email lãnh đạo, miễn phí tới 50 người) cộng proxy chỉ đọc.
- Khi máy tắt, link không phục vụ.

**Quyết định cần chủ hệ thống:**

1. Chọn nhà cung cấp URL cố định:
   - (a) **Cloudflare Named Tunnel** trên tên miền công ty đã nằm ở Cloudflare: miễn phí; quản trị Cloudflare tạo tunnel + hostname
     và cấp token;
   - (b) **Tailscale Funnel**: miễn phí; cài Tailscale (quyền admin), đăng nhập; URL `*.ts.net`;
   - (c) **ngrok** tên miền tĩnh miễn phí: có trang cảnh báo trước khi vào.
2. Công khai hoàn toàn hay giới hạn theo email.
3. Cho phép đăng ký tự khởi động: service cho tunnel và tác vụ cho proxy.
4. Dừng tunnel / proxy cũ: `scripts\remote\remote-access.ps1 stop`.

## 8. Test

Chi tiết: `TEST_RESULTS.md`.

| Bộ test | Kết quả |
|---|---|
| Backend QA trên commit | 686 passed / 19 skipped / 0 failed (19 skipped là test opt-in BigQuery thật) |
| BigQuery thật, dòng inline | 14 passed |
| Frontend | vitest 155 passed; typecheck và build OK |
| Diễn tập r12 | 36/36 |
| Kiểm tra proxy | 28/29 (1 FAIL do client, đã giải thích) |
| Kiểm tra sau deploy | 7/7 |
| Lint | not configured |

## 9. Backup, rollback, checkpoint

**Backup và checkpoint:**

| Hiện vật | Vị trí | SHA-256 |
|---|---|---|
| Backup xác minh trước deploy | `backups\backup-20261021-180216-manual.zip` | `EEEC86E677B7A77CEE1029D610D76FA13F28D0B696741C8AB679830D5F465CEB` (schema 9, integrity ok, có D-0 18:00) |
| Backup do deploy-upgrade tạo | `backups\backup-20261021-180400-manual.zip` | `29DC5902ADFBF42EC56664ED939DBBAC804D3EF48C519678982080F9B0EF43D3` |
| Backup trước D-1 buổi chiều | `backups\backup-20261021-145525-cli.zip` | `8DB29115…D0F2` |
| Checkpoint trước release (cây làm việc) | `checkpoints\checkpoint-20261021-release1211-prerelease.zip` | `86FE721D5D0F42252B78BB593DFA7B1D2519AF54D908598A390BC9449A5B267B` |
| Checkpoint sau | xem `RESUME_CHECKPOINT.md` | |

**Rollback về 1.2.10:**

- Lệnh: `rollback-version.ps1 -To 1.2.10`. Không restore (cùng schema 9).
- `-CheckOnly` trên production exit 0.
- Diễn tập: 14 s, gián đoạn 6 s, dữ liệu giữ nguyên.
- Rollback dữ liệu (nếu cần): restore backup 180216.

## 10. Git và thay đổi chưa commit

- `main`: `9ee5a4a` (release) cộng commit tài liệu CHECKPOINT (xem `git log`).
- **Chưa push** (vượt origin 31+ commit).
- Thay đổi chưa commit: không có, ngoài báo cáo / checkpoint vốn không đưa vào Git.

## 11. Quyết định còn cần người dùng

1. **Quy tắc giờ mở bán SKU × FC cho khóa nhiều listing.** Đây là điều kiện để huấn luyện. Ví dụ hai lựa chọn:
   - "SKU mở khi ít nhất một listing bán qua FC đó mở" (hợp khoảng; 6 khóa = 24, 24, 24, 24, 24, 22,85);
   - "listing của miền FC đó" (24, 24, 5,0, 1,7, 23,72, 22,85).

   Hoặc nguồn tự cung cấp giờ ở hạt SKU × FC. Sau khi có quy tắc: phát hành bản mới, preview + backfill 4 ngày, rồi huấn luyện
   candidate (không promote).
2. **Lịch D-1 / huấn luyện:**
   - 4/4 D-1 theo lịch thất bại vì nguồn dựng lại khoảng 07:10;
   - huấn luyện 07:00 bị SKIP khi D-1 thành công muộn;
   - nên dời D-1 sau 07:15 và huấn luyện sau D-1, hoặc nguồn cam kết sẵn sàng trước 06:00.
3. **Lịch huấn luyện 22/10 07:00** sẽ dừng `OPEN_HOURS_INVALID` nếu D-1 thành công trước đó. Giữ hay tạm tắt.
4. **Link công khai:** nhà cung cấp + tài khoản, kiểm soát truy cập, cho phép tự khởi động (mục 7).
5. **Duyệt push** `main`.
