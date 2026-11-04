# Xác minh dữ liệu Demo đã được lưu bền vững — DemandForecast 1.1.0

Thời điểm kiểm tra: 2026-10-14 11:32 (giờ VN).

**Phương thức: chỉ đọc**
- Database mở bằng SQLite URI `?mode=ro`. Đã thử một lệnh ghi và bị từ chối với lỗi
  `attempt to write a readonly database`, xác nhận kết nối thực sự chỉ đọc.
- Đường dẫn được phân giải bằng `paths.resolve_all()`, là hàm thuần, không tạo gì.
- Chỉ gọi các API GET.
- Không tạo Demo, không huấn luyện, không chạy migration, không sửa cấu hình, không dừng hay khởi động lại ứng dụng.

## Tóm tắt kết luận

| Mục | Kết luận |
|---|---|
| Đường dẫn database | **ĐÚNG**: `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` |
| Lô `DEMO-20261014042842-EA2CFA` | **CÓ TỒN TẠI**, trạng thái **REPLACED**. Đây không còn là lô hiện hành. |
| Dữ liệu nghiệp vụ Demo | **ĐÃ GHI**, thuộc lô ACTIVE hiện tại `DEMO-20261014042925-CB692D`: 93 157 dòng đơn hàng, 38 533 dòng nhu cầu ngày |
| Integrity | **OK** (`integrity_check` = ok, qua cả kết nối chỉ đọc và API của ứng dụng đang chạy) |
| Khóa ngoại | **OK** (`foreign_key_check` rỗng; chuỗi thay thế liên kết hai chiều đúng; không có bản ghi mồ côi) |
| Lưu bền vững | **Đủ bằng chứng**: dữ liệu đã nằm trong file DB chính, đọc lại được từ tiến trình khác khi app đang chạy |

## 1. Đường dẫn hiệu lực

- `backend\app\paths.py` ưu tiên theo thứ tự: biến môi trường `DF_DATA_DIR` → `storage.json` → mặc định
  `%LOCALAPPDATA%\DemandForecast`.
- `%LOCALAPPDATA%\DemandForecast\storage.json`: `data_dir = D:\Buymed\Lightgbm AI\data\runtime`,
  `storage_id = 6cff0821634b0447`, `allow_create = false`.
- `data\runtime\storage-id.json` có cùng `storage_id` `6cff0821634b0447`, nên thư mục khớp với cấu hình.
- Tiến trình đang chạy: pid 10100, `…\Programs\DemandForecast\1.1.0\python\python.exe -m app.cli serve --port 8765`,
  khởi động lúc 10:23:09.
- API của chính tiến trình đó (`GET /api/system/paths`) báo `db_path = D:\Buymed\Lightgbm AI\data\runtime\db\app.db`;
  tất cả nguồn đường dẫn đều là `storage.json`; file log đang ghi là `D:\Buymed\Lightgbm AI\logs\runtime\app.log`.
- Log khởi động lúc 03:23:10Z ghi `path_sources = storage.json` và `db_created_now: false`, tức app mở database có sẵn,
  không tạo mới.

**Kết luận:** đường dẫn đúng. Ứng dụng đang dùng đúng file dự kiến.

## 2. Integrity và khóa ngoại

- `PRAGMA integrity_check` → `ok` (kết nối chỉ đọc). Kiểm tra lại qua app đang chạy
  (`GET /api/system/health-check?full=true`) → integrity ok, 0 vi phạm FK.
- `PRAGMA foreign_key_check` → rỗng.
- `schema_migrations`: v1 `0001_initial.sql`, v2 `0002_one_active_demo.sql`. Journal mode: WAL.

## 3. Schema liên quan (đọc trực tiếp, không giả định)

- `import_batches`
  - Các cột chính: `id`, `data_source`, `status`, `replaces_batch_id`, `replaced_by_batch_id`, `total_rows`,
    `valid_rows`, `created_at`, `confirmed_at`, `closed_at`, …
  - Khóa ngoại: `replaced_by_batch_id → import_batches.id` và `replaces_batch_id → import_batches.id`.
  - Index: `ux_import_batches_one_active_demo` (unique), giới hạn tối đa một lô DEMO ACTIVE.
- `order_lines`: khóa ngoại `batch_id → import_batches.id`.
- `demand_daily`: khóa là `scope_key` (mã lô) cùng `data_source`; bảng này **không có khóa ngoại** khai báo,
  nên tôi kiểm tra mồ côi thủ công ở mục 6.
- Nguồn dữ liệu đang hoạt động: bảng `app_settings` **không có** dòng `general`, nên ứng dụng dùng giá trị mặc định
  `DEMO`. API xác nhận `active_source = DEMO`.

## 4. Lô `DEMO-20261014042842-EA2CFA`

| Thuộc tính | Giá trị |
|---|---|
| Tồn tại | Có (1 dòng) |
| Trạng thái | **REPLACED** |
| Tạo / xác nhận / đóng (UTC) | 04:28:42 / 04:28:46 / 04:29:29 (tức 11:28:42 → 11:29:29 giờ VN) |
| `total_rows` / `valid_rows` / `error_rows` | 93 157 / 93 157 / 0 |
| Khoảng ngày | 2024-10-14 → 2026-10-13 |
| `replaces_batch_id` | `DEMO-20261014040208-906051` (tồn tại) |
| `replaced_by_batch_id` | `DEMO-20261014042925-CB692D` (tồn tại) |
| Số dòng `order_lines` / `demand_daily` hiện còn | **0 / 0** |

Lô này đã được lưu đầy đủ lúc tạo, gồm 93 157 dòng. 43 giây sau, một lần tạo Demo khác đã thay thế nó.
Theo quy tắc nghiệp vụ đã thiết kế, khi lô Demo bị thay thế thì dòng dữ liệu của nó bị xóa và chỉ giữ lại
metadata và lịch sử kiểm toán. Vì vậy hiện tại lô này **không còn dữ liệu nghiệp vụ**. Đây là hành vi đúng thiết kế,
không phải mất dữ liệu.

## 5. Các lần tạo Demo: tạo lô mới hay cập nhật lô cũ?

Mỗi lần tạo Demo đều **tạo một lô mới** và **đánh dấu lô trước là REPLACED**. Không có lô nào bị ghi đè hay cập nhật
tại chỗ.

| # | Lô | Tạo lúc (UTC) | Trạng thái | Thay cho | Bị thay bởi |
|---|---|---|---|---|---|
| 1 | `DEMO-20261014022115-402AB7` | 02:21:15 (bản 1.0.0) | REPLACED | — | `…040132-CCE92D` |
| 2 | `DEMO-20261014040132-CCE92D` | 04:01:32 | REPLACED | `…022115-402AB7` | `…040208-906051` |
| 3 | `DEMO-20261014040208-906051` | 04:02:08 | REPLACED | `…040132-CCE92D` | `…042842-EA2CFA` |
| 4 | `DEMO-20261014042842-EA2CFA` | 04:28:42 | REPLACED | `…040208-906051` | `…042925-CB692D` |
| 5 | `DEMO-20261014042925-CB692D` | 04:29:25 | **ACTIVE** | `…042842-EA2CFA` | — |

- Từ khi chạy 1.1.0 đã có **4 lần tạo Demo**, tất cả thành công. Lô `EA2CFA` là lần thứ 3; lần thứ 4 đã thay nó.
- Liên kết hai chiều `replaced_by` ↔ `replaces` đúng ở cả 4 cặp.
- Hiện chỉ có đúng 1 lô DEMO ACTIVE.

Lưu ý về chữ "lần tạo Demo thứ hai" trong yêu cầu: nếu hiểu là lần bấm thứ hai trong lượt thử lúc 11:28–11:29
thì đó là lô `CB692D`. Nó đã tạo lô mới và thay thế `EA2CFA`.

## 6. Số bản ghi nghiệp vụ, tách theo nhóm

| Nhóm | Bảng | Số dòng | Ghi chú |
|---|---|---|---|
| **Demo**, lô ACTIVE `CB692D` | `order_lines` | 93 157 | tổng `order_qty` = 1 015 057 |
| **Demo**, lô ACTIVE `CB692D` | `demand_daily` | 38 533 | 2024-10-14 → 2026-10-13, tổng `qty` = 1 015 057 (khớp với `order_lines`) |
| Demo, 4 lô REPLACED | `order_lines` / `demand_daily` | 0 / 0 | đã xóa theo quy tắc thay thế; còn 4 dòng metadata trong `import_batches` |
| **Import Excel** (MANUAL_IMPORT) | `import_batches` / `order_lines` | 0 / 0 | chưa từng import |
| Lỗi import | `import_row_errors` | 0 | |
| **Dự báo** | `training_runs` / `forecast_runs` / `forecast_values` / `backtest_runs` | 0 / 0 / 0 / 0 | chưa huấn luyện hay publish trên DB này |
| Snapshot D0 | `d0_snapshots` / `d0_snapshot_values` | 1 / 56 | tạo lúc 03:00Z (slot 10:00) cho lô Demo cũ `402AB7`; giữ làm lịch sử |
| Vận hành | `job_runs` 5, `alerts` 2, `audit_log` 9, `settings_history` 3 | | |

Kiểm tra mồ côi:
- 0 dòng `order_lines` không có lô cha.
- 0 dòng `demand_daily` có `scope_key` không trỏ tới lô nào.
- 0 dòng dữ liệu thuộc lô không ACTIVE.

## 7. Đọc lại database khi ứng dụng đang chạy

- Kết nối chỉ đọc từ một tiến trình riêng (Python của repo) đọc được toàn bộ dữ liệu trong lúc server 1.1.0
  (pid 10100) đang chạy và vẫn ghi heartbeat scheduler mỗi 30 giây (heartbeat gần nhất 11:32:17).
- `GET /api/system/status` của app đang chạy trả `scope = DEMO-20261014042925-CB692D`, `rows = 38533`,
  `max_date = 2026-10-13`, `db_version = 2`, không có `scope_error`. Khớp với kết quả truy vấn trực tiếp.

## 8. Đối chiếu log runtime (`D:\Buymed\Lightgbm AI\logs\runtime\app.log`)

```
03:23:10Z INFO app starting      version 1.1.0, path_sources=storage.json, db_created_now=false
04:01:36Z INFO demo generated    DEMO-20261014040132-CCE92D rows 93157
04:02:13Z INFO demo generated    DEMO-20261014040208-906051 rows 93157
04:28:46Z INFO demo generated    DEMO-20261014042842-EA2CFA rows 93157
04:29:30Z INFO demo generated    DEMO-20261014042925-CB692D rows 93157
```

- Không có dòng `ERROR` nào kể từ khi 1.1.0 khởi động. `server.err.log` = 0 byte.
- Dòng `demo generated` được ghi **sau** khi transaction đã COMMIT (nằm ngoài khối `with db.tx()`
  trong `demo.py`), và `audit_log` có đủ 4 sự kiện `DEMO_GENERATED` tương ứng.
- **Chưa xác minh được:** mã phản hồi HTTP của từng lần bấm, vì access log của uvicorn đang tắt
  (`log_level=warning`). Bằng chứng thành công dựa trên log ứng dụng, `audit_log` và dữ liệu trong DB, không dựa
  trên log HTTP.

## 9. Độ bền lưu trữ

- Không có file `app.db-wal` vào thời điểm kiểm tra, nghĩa là mọi giao dịch đã được checkpoint vào file chính
  `app.db` (55 791 616 byte, ghi gần nhất 11:32:47 do heartbeat scheduler).
- Header file: `SQLite format 3`, phiên bản ghi/đọc = 2/2 (WAL).
- Dữ liệu được đọc lại từ một tiến trình khác bằng kết nối chỉ đọc, và khớp với những gì ứng dụng báo qua API.

**Kết luận:** đủ bằng chứng khẳng định dữ liệu Demo của lô ACTIVE hiện tại `CB692D` đã được lưu bền vững trong
`D:\Buymed\Lightgbm AI\data\runtime\db\app.db`. Lô `EA2CFA` được lưu bền vững lúc tạo; dữ liệu dòng của nó đã bị
xóa đúng quy tắc khi bị thay thế, metadata vẫn còn.

**Chưa kiểm chứng trong lần này:** tôi không khởi động lại ứng dụng (theo yêu cầu), nên chưa có bằng chứng "đọc lại
sau restart" cho riêng các lô tạo lúc 11:01–11:29. Việc đọc thành công từ một tiến trình khác và việc dữ liệu đã nằm
trong file chính là bằng chứng tương đương mạnh, nhưng không phải là phép thử restart.

## Ghi nhận phụ (không thay đổi gì)

- Trong `data\runtime\db\` còn 2 file tạm `app.db.migrating-shm` (32 KB) và `app.db.migrating-wal` (0 byte), sót lại
  từ bước xác minh khi di chuyển lúc 10:23. Ứng dụng không dùng chúng. Có thể xóa tay khi app đã dừng; tôi không xóa
  vì lần này chỉ đọc.
- Kích thước DB tăng từ 27,8 MB lên 55,8 MB vì 4 lần tạo lại Demo để lại trang trống. Dữ liệu không bị nhân đôi:
  chỉ có 93 157 dòng thuộc lô ACTIVE. `VACUUM` có thể thu nhỏ file nhưng chưa thực hiện.
- Snapshot D0 duy nhất vẫn trỏ tới lô Demo cũ `402AB7`. Đây là lịch sử bất biến; bảng snapshot không có khóa ngoại
  tới `import_batches`.
