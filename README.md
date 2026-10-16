# Ứng dụng Dự báo nhu cầu đặt hàng (SKU × FC · LightGBM)

Ứng dụng web chạy **trên một máy Windows**, dự báo số lượng khách đặt hàng theo ngày cho từng tổ hợp
**SKU × FC/kho** bằng **LightGBM**. Giao diện song ngữ Việt/Anh, mở bằng trình duyệt tại
`http://127.0.0.1:8765`. Không có thành phần chạy trên cloud; BigQuery chỉ là nguồn dữ liệu bên ngoài.

Ba nguồn dữ liệu độc lập, không bao giờ trộn lẫn:

| Nguồn | Dùng khi | Ghi chú |
|---|---|---|
| `DEMO` | Xem thử, kiểm thử toàn bộ quy trình | Dữ liệu tổng hợp, luôn gắn nhãn DEMO |
| `MANUAL_IMPORT` | Kiểm thử bằng dữ liệu lịch sử thật từ file Excel `.xlsx` | Mỗi lần import là một lô độc lập |
| `BIGQUERY` | Dữ liệu sản xuất | Chỉ bật được sau khi kết nối, schema, ánh xạ và kiểm tra dữ liệu đều đạt |

## 1. Cài đặt nhanh (gói portable — khuyến nghị)

Yêu cầu: Windows 10/11 64-bit. **Không cần cài Python hay Node** (đã đóng gói sẵn).

1. Giải nén `DemandForecast-<phiên bản>-win64-portable.zip` vào một thư mục bất kỳ.
2. Nhấp đúp **`Install.bat`** — cài cho người dùng hiện tại (không cần quyền admin) vào
   `%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản>`, tạo shortcut “Demand Forecasting” trên Desktop và Start Menu,
   kiểm tra môi trường rồi mở ứng dụng.
   - Muốn ứng dụng tự chạy khi đăng nhập Windows (để scheduler hoạt động):
     `powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Autostart`
3. Nếu máy thiếu *Microsoft Visual C++ Redistributable* (LightGBM cần `vcomp140.dll`), `Install.bat` sẽ cài
   qua `winget`; nếu không có `winget`, tải tại https://aka.ms/vs/17/release/vc_redist.x64.exe.

Không muốn cài? Có thể chạy trực tiếp từ thư mục giải nén: **`Start.bat`** (mở), **`Stop.bat`** (dừng),
**`Check-Environment.bat`** (kiểm tra môi trường), **`Backup.bat`** (sao lưu).

## 2. Chạy từ mã nguồn (dành cho kỹ thuật)

Yêu cầu: Python 3.14 (64-bit, có `py` launcher), Node.js 18+.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1   # tạo .venv, cài thư viện đã khóa phiên bản, build UI
powershell -ExecutionPolicy Bypass -File scripts\start.ps1       # chạy và mở trình duyệt
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1        # dừng an toàn
powershell -ExecutionPolicy Bypass -File scripts\run-tests.ps1   # chạy toàn bộ test
powershell -ExecutionPolicy Bypass -File scripts\build-package.ps1  # tạo gói portable trong dist\
```

## 3. Thử nhanh với dữ liệu DEMO (5 phút)

1. Mở ứng dụng → trang **Tổng quan**. Nguồn mặc định là `DEMO`.
2. Bấm **Tạo dữ liệu Demo** (≈ 2 năm, 30 SKU, 4 FC; có SKU ổn định, gián đoạn, mới, ngừng bán, ngày không có đơn).
3. Bấm **Huấn luyện & dự báo ngay**. Sau vài giây: forecast được publish, xem tổng 7/15/30 ngày, biểu đồ theo ngày.
4. Xem **Kết quả dự báo** (lọc SKU/FC/ngày, xuất Excel), **Chất lượng mô hình** (WAPE, MAE, bias, backtest),
   **Lịch sử Snapshot D0** (bấm *Chụp snapshot D0 ngay*), **Job & Scheduler**.

## 4. Thử với dữ liệu Excel của bạn

Xem chi tiết: [docs/IMPORT-EXCEL.md](docs/IMPORT-EXCEL.md). Tóm tắt: trang **Import dữ liệu lịch sử** → tải
**file Excel mẫu** → điền dữ liệu → tải lên → ánh xạ cột → **Kiểm tra dữ liệu** → xem lỗi/xem trước →
**Xác nhận lưu** → đổi nguồn thành `MANUAL_IMPORT` (ô chọn góc trên phải) → **Huấn luyện & dự báo ngay**.

## 5. Dữ liệu được lưu ở đâu

Mặc định ở `%LOCALAPPDATA%\DemandForecast`; có thể đặt ở thư mục khác (vd. ổ D) bằng `storage.json` —
xem [docs/LUU-TRU.md](docs/LUU-TRU.md). Vị trí thực tế luôn hiển thị ở **Hệ thống & sao lưu → Vị trí lưu trữ đang dùng**.

| Mục | Vị trí (tương đối với thư mục dữ liệu) |
|---|---|
| Database SQLite | `db\app.db` |
| Mô hình LightGBM | `models\` |
| Log JSON (xoay vòng 10 MB × 5 file) | `logs\` hoặc `logs_dir` đã cấu hình |
| Sao lưu `.zip` (đã xác minh) | `backups\` hoặc `backups_dir` đã cấu hình |
| Báo cáo chẩn đoán | `reports\` hoặc `reports_dir` đã cấu hình |

Thư mục dữ liệu **tách khỏi chương trình**: cài phiên bản mới không làm mất dữ liệu. Ứng dụng không bao giờ âm thầm
tạo database trống ở nơi khác khi thư mục đã cấu hình không khả dụng.

## 6. Tài liệu

- [Hướng dẫn sử dụng giao diện](docs/HUONG-DAN-SU-DUNG.md)
- [Import dữ liệu bằng Excel](docs/IMPORT-EXCEL.md)
- [Cấu hình BigQuery](docs/BIGQUERY.md)
- [Cấu hình scheduler](docs/SCHEDULER.md)
- [Mô hình & chỉ số chất lượng](docs/MO-HINH-VA-CHI-SO.md)
- [Lưu trữ: đường dẫn, di chuyển dữ liệu, rollback](docs/LUU-TRU.md)
- [Vận hành: sao lưu, khôi phục, nâng cấp, rollback, khắc phục sự cố](docs/VAN-HANH.md)
- [Kiến trúc & luồng dữ liệu](docs/KIEN-TRUC.md)
- [Checkpoint của batch triển khai](docs/CHECKPOINT.md)

## 7. Bảo mật (MVP)

- Chỉ nghe trên `127.0.0.1`; từ chối Host lạ (chống DNS rebinding); mọi API thay đổi dữ liệu yêu cầu header
  `X-DF-Client` (website khác không gửi được) — chưa có đăng nhập người dùng (hoãn khỏi MVP).
- Không lưu secret: BigQuery dùng Application Default Credentials của Windows; nếu dùng service account thì chỉ lưu
  **đường dẫn** file key (bắt buộc nằm ngoài thư mục ứng dụng).
- File import: chỉ `.xlsx`, giới hạn dung lượng/số dòng, chặn macro (`vbaProject.bin`), chống zip-bomb, không chạy công thức.
