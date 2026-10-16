# Vận hành: sao lưu, khôi phục, nâng cấp, rollback, khắc phục sự cố

Các lệnh dưới đây chạy trong thư mục chương trình (gói cài: `%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản>`),
bằng PowerShell: `powershell -ExecutionPolicy Bypass -File scripts\<tên>.ps1`.

## Khởi động / dừng

| Việc | Lệnh |
|---|---|
| Khởi động (mở trình duyệt) | `Start.bat` hoặc `scripts\start.ps1` (`-NoBrowser` để không mở trình duyệt) |
| Dừng an toàn | `Stop.bat` hoặc `scripts\stop.ps1` (gọi API tắt có token cục bộ, sau đó dừng tiến trình nếu cần) |
| Kiểm tra môi trường | `Check-Environment.bat` hoặc `scripts\check-env.ps1` |
| Tự chạy khi đăng nhập | `scripts\register-autostart.ps1` / gỡ `scripts\unregister-autostart.ps1` |

Đổi cổng: tạo `%LOCALAPPDATA%\DemandForecast\app.env` (mẫu `config\app.env.example`) với `DF_PORT=8770`.

## Sao lưu

- Giao diện: **Hệ thống & sao lưu → Sao lưu ngay**; hoặc `Backup.bat` / `scripts\backup.ps1`. An toàn khi ứng dụng đang chạy
  (SQLite online backup). Kết quả: `%LOCALAPPDATA%\DemandForecast\backups\backup-<thời gian>-<lý do>.zip`
  (gồm `db\app.db` + thư mục `models\`).
- Tự động: trước mỗi migration làm thay đổi schema, trước mỗi lần khôi phục, và trước khi `install.ps1` nâng cấp.
- Nên chép thư mục `backups\` sang ổ khác/định kỳ. Ứng dụng không tự xóa bản sao lưu cũ.

## Khôi phục

```powershell
scripts\stop.ps1
scripts\restore.ps1 -File backup-20261014-070000-manual.zip   # tên file trong thư mục backups, hoặc đường dẫn đầy đủ
scripts\start.ps1
```

`restore` từ chối chạy khi ứng dụng đang chạy, kiểm tra `PRAGMA integrity_check`, tạo bản sao lưu an toàn
`…-pre-restore.zip` của DB hiện tại trước khi thay, rồi chạy migration nếu cần.

## Nâng cấp phiên bản

1. Giải nén gói mới → chạy `Install.bat` của gói mới. Script sẽ: dừng ứng dụng → **sao lưu dữ liệu** → cài vào
   `%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản mới>` (phiên bản cũ **giữ nguyên** bên cạnh) → chạy migration →
   cập nhật shortcut → kiểm tra môi trường → khởi động.
2. Cấu hình, lô import, snapshot, lịch sử forecast nằm trong `%LOCALAPPDATA%\DemandForecast` nên **không bị ảnh hưởng**.
   Không bước nào xóa database.
3. Migration chạy trong transaction; lỗi → rollback, DB giữ ở phiên bản cũ và báo đường dẫn bản sao lưu.

### Nâng cấp 1.1.0 → 1.1.1 (một quy trình duy nhất)

1. Mở trang **Job & Scheduler**: chờ không còn job *Đang chạy* (huấn luyện/đồng bộ).
2. Giải nén `DemandForecast-1.1.1-win64-portable.zip` vào một thư mục tạm → chạy `Install.bat` **của gói 1.1.1**.
   Script dừng 1.1.0, sao lưu DB, cài vào `%LOCALAPPDATA%\Programs\DemandForecast\1.1.1` (thư mục 1.1.0 giữ nguyên),
   giữ nguyên `storage.json` (DB thật vẫn là `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`), khởi động 1.1.1.
3. Lần khởi động đầu chạy migration `0003_job_stages_explainability` (schema 2 → 3): chỉ **thêm** cột
   (`job_runs.stage…`, `forecast_runs.derived_from_run_id`) và bảng `forecast_series_meta`; không sửa/xóa dữ liệu cũ.
   Trước migration ứng dụng tự tạo bản sao lưu `pre-migration` trong thư mục backups.
4. Kiểm tra: trang **Hệ thống** hiển thị phiên bản 1.1.1, đúng đường dẫn DB trên ổ D, schema 3; trang **Kết quả dự báo**
   vẫn thấy các forecast run cũ.
5. Run cũ (tạo bởi 1.1.0) không có bảng lý do phương pháp; *Xem cách tính* sẽ tính lại từ cùng dữ liệu nếu dữ liệu
   không đổi, ngược lại báo không xác định được.

Quay lại 1.1.0: 1.1.0 **từ chối** DB schema 3, nên phải dừng ứng dụng → khôi phục bản sao lưu `pre-migration` (bằng
`scripts\restore.ps1` của bản 1.1.0) → chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.1.0\Start.bat`. Dữ liệu phát sinh
sau khi nâng cấp (job, forecast mới) sẽ không có trong bản khôi phục.

### Rollback

- Migration lỗi: DB chưa đổi. Chạy lại phiên bản cũ: `%LOCALAPPDATA%\Programs\DemandForecast\<bản cũ>\Start.bat`.
- Đã nâng cấp nhưng muốn quay về bản cũ: dừng ứng dụng → `scripts\restore.ps1 -File <bản sao lưu tạo lúc nâng cấp>`
  **bằng script của phiên bản cũ** → chạy phiên bản cũ. (Phiên bản cũ từ chối mở DB có schema mới hơn — thông báo
  `MigrationError … newer than this app supports` — nên phải khôi phục bản sao lưu trước.)

### Nâng cấp / rollback có kiểm soát (từ 1.1.6)

- `scripts\deploy-upgrade.ps1 -Package <zip> -ExpectedSha256 <sha> [-CheckOnly]`: kiểm tra trước, backup trực tuyến, xác nhận `UPGRADE-<phiên bản>`, cài, kiểm tra sau, log.
- `scripts\rollback-version.ps1 -To <phiên bản> [-CheckOnly]`: kiểm tra schema DB tương thích, xác nhận `ROLLBACK-<phiên bản>`, chuyển phiên bản, health check.

Chi tiết: [TRIEN-KHAI-1.1.6.md](TRIEN-KHAI-1.1.6.md).

`install.ps1` (1.1.6):
- dừng nếu thư mục dữ liệu nằm trong thư mục chương trình sẽ bị thay;
- tự khởi động lại phiên bản trước nếu dừng giữa chừng sau khi đã tắt ứng dụng;
- chỉ cập nhật `current.txt` sau khi migration thành công.

### Rollback từ 1.2.0

- 1.2.0 không đổi schema (vẫn 3), nên `scripts\rollback-version.ps1 -To 1.1.9` (hoặc `1.1.8`) **không cần khôi phục DB**.
- Một model DIRECT phát hành bằng 1.2.0 vẫn được bản cũ *hiển thị*, gồm forecast và chỉ số. Tuy vậy, bản cũ không *giải
  thích* hay *kéo dài* được model đó: nó báo lỗi số feature, không trả số sai.
- Muốn bỏ hẳn model DIRECT đã phát hành thì làm theo thứ tự:
  1. dừng ứng dụng;
  2. `scripts\restore.ps1 -File <bản sao lưu tạo ngay trước khi phát hành>`;
  3. chạy lại D-1 thủ công nếu dữ liệu đã được nạp thêm sau thời điểm sao lưu.

## Gỡ cài đặt (giữ nguyên dữ liệu)

1. `Stop.bat` (hoặc `scripts\stop.ps1`); nếu đã bật tự khởi động: `scripts\unregister-autostart.ps1`.
2. Xóa thư mục phiên bản không dùng nữa trong `%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản>`. Muốn gỡ hẳn thì xóa
   cả thư mục `%LOCALAPPDATA%\Programs\DemandForecast`, rồi xóa các shortcut "Demand Forecasting" trên Desktop / Start
   Menu.
3. **Không xóa** thư mục dữ liệu, là nơi `%LOCALAPPDATA%\DemandForecast\storage.json` trỏ tới. Trên máy này đó là
   `D:\Buymed\Lightgbm AI\data\runtime`, gồm DB, model và cấu hình, cùng với thư mục `backups\`. Cài lại bất kỳ phiên bản
   nào cũng dùng lại đúng dữ liệu đó.
4. Nếu đường dẫn dữ liệu đã cấu hình không còn (ví dụ ổ D bị rút), ứng dụng **từ chối khởi động** với `STORAGE_NOT_FOUND`.
   Nó không tạo DB trống thay thế. Cắm lại ổ, hoặc khôi phục bản sao lưu bằng `scripts\restore.ps1`.

## Chuyển sang máy Windows khác

1. Máy mới: giải nén gói → `Install.bat`.
2. Muốn mang dữ liệu: máy cũ tạo bản sao lưu → chép file `.zip` → máy mới `scripts\stop.ps1`, `scripts\restore.ps1 -File …`.
3. **Phụ thuộc từng máy**: đăng nhập Google (nhập lại file JSON OAuth client rồi *Đăng nhập Google*), quyền BigQuery của
   tài khoản, VC++ Redistributable, tác vụ tự khởi động, file `app.env`.

### Xác thực Google trên máy mới

Credentials không bao giờ nằm trong gói. Mỗi tài khoản Windows dùng ứng dụng tự xác thực, theo một trong hai cách:
- **Đăng nhập Google trong ứng dụng (khuyến nghị, không cần cài thêm công cụ):** chọn file JSON OAuth client (Desktop app) do quản trị cấp, rồi bấm *Đăng nhập Google*. Refresh token được lưu trong Windows Credential Manager của tài khoản đó; kiểm tra bằng nút *Kiểm tra quyền BigQuery* hoặc `python -m app.cli bq-check`.
- **ADC (tùy chọn):** chạy `gcloud auth application-default login` **trong chính tài khoản Windows chạy ứng dụng**.

ADC của tài khoản Windows khác (ví dụ Administrator) không dùng được. Xem [BIGQUERY.md](BIGQUERY.md) mục 2.

## Chẩn đoán & vị trí lưu trữ

- Báo cáo chẩn đoán (không chứa secret): **Hệ thống & sao lưu → Tải / Lưu báo cáo chẩn đoán**, hoặc
  `Diagnose.bat` / `scripts\diagnose.ps1 [-OutDir <thư mục>]` (mặc định: thư mục báo cáo đã cấu hình).
- Kiểm tra toàn vẹn database (chỉ đọc): **Kiểm tra toàn vẹn database** hoặc `GET /api/system/health-check?full=true`.
- Đổi/di chuyển thư mục dữ liệu, rollback: [LUU-TRU.md](LUU-TRU.md).

## Log

`<thư mục log>\app.log` (xem vị trí ở trang Hệ thống; JSON mỗi dòng, xoay vòng 10 MB × 5 ≈ tối đa 60 MB). Lỗi API có `request_id` (cũng hiển thị trên giao diện) để đối chiếu. Mỗi dòng có `ctx` với `job_id`,
`batch_id`, `snapshot_id`, `training_run_id`, `forecast_run_id` khi phù hợp. Không ghi secret (có lọc từ khóa
`token/password/private_key…`) và không ghi toàn bộ dữ liệu đơn hàng. Lỗi khởi động: `logs\server.err.log`.

## Khắc phục sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| `start.ps1` báo *failed to start* | Xem `logs\server.err.log`. Chạy `check-env.ps1`. |
| `check-env` báo thiếu `vcomp140.dll` / LightGBM lỗi | `winget install Microsoft.VCRedist.2015+.x64` |
| Cổng 8765 bị chiếm | Đặt `DF_PORT` trong `app.env` |
| “Running scripts is disabled on this system” | Dùng các file `.bat` hoặc `powershell -ExecutionPolicy Bypass -File …` |
| Trình duyệt báo không kết nối | Ứng dụng chưa chạy (máy vừa khởi động?) → `Start.bat` |
| Giao diện báo “Cannot reach the backend” | Backend dừng giữa chừng → `Start.bat`, xem log |
| Không thấy job chạy theo giờ | Ứng dụng phải đang chạy lúc đó; mở *Lịch chạy dữ liệu*: luồng đó đã **bật** chưa, có *Sẵn sàng* không, trạng thái có phải *Đang bật — scheduler đã nạp*; bật tự khởi động |
| `DATA_NOT_TRAINABLE` | Lịch sử < 56 ngày hoặc không có dữ liệu |
| `QUALITY_GATE_FAILED` | Xem *Chất lượng mô hình*; dữ liệu nhiễu/ngắn; ngưỡng ví dụ có thể quá chặt |
| BigQuery `BQ_AUTH_MISSING` | Thẻ *Xác thực Google*: nhập file JSON OAuth client rồi *Đăng nhập Google* (hoặc ADC của chính tài khoản Windows này) |
| `PROMOTION_REVIEW_REQUIRED` | Model mới chờ duyệt: trang *Hiệu năng model* → xem so sánh → *Dùng model này* nếu đồng ý |
| BigQuery `BQ_QUERY_TOO_EXPENSIVE` | Thêm cột partition, giảm số ngày tải lần đầu, hoặc tăng giới hạn bytes (cân nhắc chi phí) |
| Import báo `MACRO_NOT_ALLOWED` | Lưu lại file dưới dạng *Excel Workbook (.xlsx)* |
| `STORAGE_NOT_FOUND` khi khởi động | Ổ/thư mục dữ liệu đã cấu hình không có mặt. Cắm lại ổ, hoặc `scripts\rollback-storage.ps1`. Ứng dụng cố ý không tạo database trống. |
| `STORAGE_CONFIG_MISSING` khi khởi động/cài đặt | `storage.json` (ở `%LOCALAPPDATA%\DemandForecast`) bị mất sau khi đã di chuyển dữ liệu. Chạy `scripts\repair-storage.ps1`, rồi `-Apply` — chỉ khôi phục khi mọi bằng chứng khớp. Xem [LUU-TRU.md](LUU-TRU.md). |
| `DATABASE_CONSTRAINT` / `DATA_CONSISTENCY` | Thao tác bị từ chối và đã rollback; không mất dữ liệu. Tạo báo cáo chẩn đoán. Không xóa database. |
| Lỡ tay xóa/thay lô | Khôi phục bản sao lưu gần nhất (forecast đã publish vẫn còn dù lô bị xóa) |

Không cần (và không nên) sửa SQLite bằng tay.
