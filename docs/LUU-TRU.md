# Lưu trữ: đường dẫn, cấu hình, di chuyển và rollback (từ v1.1.0)

Mọi đường dẫn do **một module duy nhất** quyết định: `backend\app\paths.py`. Backend, script PowerShell
(`scripts\_common.ps1` gọi `app.cli paths`), installer và giao diện đều đọc từ đây — không nơi nào tự ghép đường dẫn,
không phụ thuộc thư mục đang đứng (current working directory) hay tên tài khoản Windows.

## Thứ tự ưu tiên

| Vị trí | 1. Biến môi trường | 2. `storage.json` | 3. Mặc định |
|---|---|---|---|
| Thư mục dữ liệu | `DF_DATA_DIR` | `data_dir` | `%LOCALAPPDATA%\DemandForecast` |
| Log | `DF_LOGS_DIR` | `logs_dir` | `<dữ liệu>\logs` |
| Sao lưu | `DF_BACKUPS_DIR` | `backups_dir` | `<dữ liệu>\backups` |
| Báo cáo chẩn đoán | `DF_REPORTS_DIR` | `reports_dir` | `<dữ liệu>\reports` |

Cố định theo thư mục dữ liệu: database `db\app.db` (+ `-wal`, `-shm`), mô hình `models\`, file tải lên tạm `uploads\`
(tự xóa sau xác nhận/hủy hoặc sau 24 giờ), `runtime.json` (pid/cổng/token tắt — không bao giờ hiện trong báo cáo),
`app.env` (cấu hình không bí mật), `storage-id.json` (định danh thư mục lưu trữ).

**File xuất** (Excel kết quả, báo cáo lỗi import, báo cáo chẩn đoán tải xuống) được trình duyệt tải về thư mục
*Tải xuống* — máy chủ không lưu.

**File `storage.json`** nằm ở vị trí cố định cho mỗi người dùng: `%LOCALAPPDATA%\DemandForecast\storage.json`
(đổi bằng biến `DF_STORAGE_CONFIG`). Ví dụ:

```json
{
  "version": 1,
  "data_dir": "D:\\Buymed\\Lightgbm AI\\data\\runtime",
  "logs_dir": "D:\\Buymed\\Lightgbm AI\\logs\\runtime",
  "backups_dir": "D:\\Buymed\\Lightgbm AI\\backups",
  "reports_dir": "D:\\Buymed\\Lightgbm AI\\reports",
  "storage_id": "…",
  "allow_create": false
}
```

Chỉ chứa đường dẫn tuyệt đối — **không** đặt mật khẩu/API key vào file này.
Xem vị trí đang dùng: giao diện **Hệ thống & sao lưu → Vị trí lưu trữ đang dùng**, hoặc
`python -m app.cli paths`, hoặc API `GET /api/system/paths`. Log khởi động (`app starting`) ghi đủ các đường dẫn.

## An toàn: không bao giờ âm thầm tạo database trống

- Thư mục cấu hình trong `storage.json` không tồn tại (ổ D bị rút, thư mục bị đổi tên) hoặc không có database →
  ứng dụng **từ chối khởi động** với mã `STORAGE_NOT_FOUND` và nêu rõ đường dẫn. Không chuyển sang chỗ khác.
- `storage-id.json` phải khớp `storage_id` trong cấu hình (chống trỏ nhầm sang database của nơi khác).
- Không ghi được → `STORAGE_NOT_WRITABLE`. Cấu hình sai định dạng/đường dẫn tương đối → `STORAGE_CONFIG_INVALID`.
- Chỉ vị trí mặc định (lần chạy đầu), `DF_DATA_DIR`, hoặc `allow_create: true` (cài mới với `-DataDir`, tự chuyển về
  `false` ngay sau khi database đầu tiên được tạo) mới được phép tạo database mới.

## Chọn thư mục dữ liệu khi cài mới

```powershell
scripts\install.ps1 -DataDir "D:\DemandForecast\runtime" -LogsDir "D:\DemandForecast\logs"
```

Nếu máy đã có dữ liệu, `-DataDir` **không** di chuyển dữ liệu (để không bỏ sót) — dùng quy trình bên dưới.

## Di chuyển dữ liệu sang thư mục khác

```powershell
scripts\migrate-storage.ps1 -DataDir "D:\Buymed\Lightgbm AI\data\runtime" `
   -LogsDir "D:\Buymed\Lightgbm AI\logs\runtime" -BackupsDir "D:\Buymed\Lightgbm AI\backups" `
   -ReportsDir "D:\Buymed\Lightgbm AI\reports"
# -DryRun: chỉ kiểm kê, không thay đổi
```

Các bước (lệnh `app.cli storage-migrate`):

1. Dừng ứng dụng (từ chối nếu vẫn đang chạy); từ chối nếu thư mục đích đã có database.
2. Kiểm kê nguồn: schema version, số dòng **mọi bảng**, `integrity_check`, `foreign_key_check`, danh sách bảng/index/trigger.
3. Backup bằng SQLite Online Backup API → giải nén thử → integrity + số dòng phải khớp (backup giữ vĩnh viễn).
4. Sao chép database bằng Backup API sang `app.db.migrating`, xác minh như trên, rồi đổi tên thành `app.db`.
5. Sao chép mô hình (đối chiếu sha256) và `app.env`; **sao chép** (không di chuyển) log cũ vào `<log>\legacy-<thời gian>\`.
6. Ghi `storage.json` (ghi nguyên tử) → kiểm tra lại qua bộ phân giải đường dẫn.
7. Đổi tên thư mục `db` cũ thành `db.migrated-<thời gian>` (**không xóa**) và đặt một *file* tên `db` để bản cũ
   (≤ 1.0.0) nếu lỡ chạy sẽ báo lỗi thay vì tạo database trống; ghi `MIGRATED-README.txt`.
8. Khởi động ứng dụng; nếu không lên được → tự động rollback.

Lỗi ở bất kỳ bước nào sau bước 6 → khôi phục `storage.json` cũ và thư mục `db` cũ; bản sao ở đích được đánh dấu
`NOT-PRIMARY-*.txt`. Lịch sử: `%LOCALAPPDATA%\DemandForecast\storage-migrations.json` và
`<đích>\storage-migration-<thời gian>.json`.

## Rollback

```powershell
scripts\rollback-storage.ps1
```

Dừng ứng dụng → đổi tên `db.migrated-<…>` về `db` → khôi phục cấu hình trước (hoặc xóa `storage.json` nếu trước đó
dùng mặc định) → đánh dấu thư mục đích `NOT-PRIMARY` (giữ nguyên, không xóa) → kiểm tra integrity + số dòng của
database đang dùng. Không bao giờ có hai database cùng được coi là chính.

## `storage.json` ở đâu — và khi bị mất

`storage.json` **chỉ** nằm ở `%LOCALAPPDATA%\DemandForecast\storage.json` (ví dụ
`C:\Users\<tên>\AppData\Local\DemandForecast\storage.json`). Nó **không** nằm trong thư mục dữ liệu ở ổ D,
trong project hay trong thư mục cài đặt — thư mục dữ liệu chỉ chứa `storage-id.json` (định danh) và
`storage-migration-<thời gian>.json` (bản sao lịch sử). `AppData` là thư mục ẩn trong Explorer.

Kiểm tra chỉ đọc: `python -m app.cli storage-verify` (đối chiếu `storage.json` ↔ `storage-id.json` ↔ lịch sử di chuyển
↔ database; exit 0 = nhất quán).

Nếu `storage.json` thật sự bị mất sau khi đã di chuyển dữ liệu: ứng dụng **từ chối khởi động** với
`STORAGE_CONFIG_MISSING` (không tạo database trống ở vị trí mặc định), `install.ps1` cũng dừng trước khi thay đổi gì.
Khôi phục:

```powershell
scripts\repair-storage.ps1          # chạy thử: chỉ kiểm tra và in cấu hình sẽ ghi
scripts\repair-storage.ps1 -Apply   # ghi storage.json sau khi kiểm tra lại
```

`storage-repair` mặc định chỉ kiểm tra và hiển thị (CLI: ghi chỉ khi có `--apply`; script: `-Apply`), và chỉ ghi khi **mọi** bằng chứng khớp: sự kiện cuối trong lịch sử là một lần di chuyển thành công;
thư mục đích tồn tại; `storage-id.json` có `storage_id`, `migrated_from` khớp nguồn và được tạo đúng bởi lần di chuyển
đó (hoặc khớp `storage_id` ghi trong lịch sử); bản ghi `storage-migration-<thời gian>.json` ở đích khớp lịch sử;
database tồn tại và qua `integrity_check`. Không khớp → từ chối, không ghi gì. Không bao giờ ghi đè `storage.json`
đang có, không tạo/di chuyển database.

## Lưu ý khi dữ liệu nằm trong thư mục project (ổ D)

`data\`, `logs\`, `backups\` đã nằm trong `.gitignore`. Đừng xóa/dọn thư mục project (vd. `git clean -x`) khi chưa
sao lưu. Thư mục `%LOCALAPPDATA%\DemandForecast` vẫn chứa `storage.json` (bắt buộc) và database cũ đã lưu trữ.
