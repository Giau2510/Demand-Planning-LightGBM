# Triển khai 1.1.6 trên máy Windows (có kiểm soát)

Trạng thái khi phát hành (15/10/2026): **READY_FOR_EXTERNAL_SETUP**.
- Gói đã qua kiểm thử cô lập.
- Đăng nhập Google thật và truy vấn BigQuery thật **chưa** được xác minh: chưa có OAuth client và chưa có quyền IAM cho tài khoản dùng ứng dụng.
- Có thể nâng cấp lên 1.1.6 ngay: ứng dụng tiếp tục chạy với nguồn hiện tại (DEMO); mọi chức năng BigQuery vẫn khóa cho đến khi các bước 2–4 đạt.

## 1. Sao lưu và kiểm tra trước

1. Mở ứng dụng → **Hệ thống & sao lưu** → *Sao lưu*. File backup nằm trong `D:\Buymed\Lightgbm AI\backups`.
2. Kiểm tra gói: `Get-FileHash <zip> -Algorithm SHA256` phải bằng SHA256 công bố trong báo cáo.
3. Chạy kiểm tra chỉ-đọc (không dừng, không ghi gì):

   ```powershell
   powershell -ExecutionPolicy Bypass -File <thư mục gói>\scripts\deploy-upgrade.ps1 -Package <zip> -ExpectedSha256 <sha> -CheckOnly
   ```

   Kết quả phải là `PRECHECK OK`. Script kiểm tra:
   - SHA256 và `VERSION` của gói; gói không chứa file credential;
   - phiên bản đang chạy khớp `current.txt`;
   - `storage-verify`, database tồn tại (ổ D: truy cập được);
   - không có job đang chạy, đủ dung lượng đĩa.

## 2. Thông tin quản trị Google Cloud cần cung cấp (cho "Đăng nhập Google")

1. **Project** đặt OAuth client (có thể là `lakehouse-prod-394907` hoặc project nội bộ khác).
2. **OAuth consent screen** loại **Internal** (chỉ tài khoản công ty). Scope: `openid`, `email`, `https://www.googleapis.com/auth/bigquery`.
3. **OAuth client ID** loại **Desktop app**. Cần gửi:
   - **Client ID** (`…apps.googleusercontent.com`);
   - **Client secret**, gửi qua kênh an toàn và **không** gửi qua email/chat công khai.
4. Nếu Google Workspace giới hạn truy cập ứng dụng bên thứ ba: đưa client vào danh sách **Trusted**.
5. **BigQuery API** bật trong project chạy truy vấn.

## 3. Quyền IAM tối thiểu cho tài khoản Google dùng ứng dụng

- `roles/bigquery.jobUser` trên project chạy truy vấn (`lakehouse-prod-394907`).
- `roles/bigquery.dataViewer` trên dataset `lakehouse-prod-394907.gold_buymed_vn2`, hoặc trên các bảng:
  - `demand_planing_lightgbm`;
  - `fact_order`, `fact_order_item`, `adhoc_pm_master_sku` (cho SQL D0).

Ứng dụng **không** tự cấp quyền và không ghi gì lên BigQuery.

## 4. Nâng cấp

```powershell
powershell -ExecutionPolicy Bypass -File <thư mục gói>\scripts\deploy-upgrade.ps1 -Package <zip> -ExpectedSha256 <sha>
```

Script chạy theo thứ tự:
1. kiểm tra lại;
2. sao lưu trực tuyến qua ứng dụng và kiểm tra file backup;
3. **hỏi xác nhận**: gõ `UPGRADE-1.1.6`;
4. chạy `install.ps1`: dừng 1.1.5 → backup → cài → migration (1.1.6 không có migration, schema vẫn 3) → khởi động;
5. kiểm tra sau: phiên bản, thư mục dữ liệu, nguồn dữ liệu, `storage.json` không đổi.

Log nằm trong `logs\runtime\deploy-<thời điểm>.log`.

Nếu bất kỳ bước nào không đạt, script dừng. Nếu `install.ps1` đã dừng 1.1.5 rồi mới lỗi, nó tự khởi động lại 1.1.5.

## 5. Sau nâng cấp: đăng nhập và kiểm tra BigQuery (chỉ đọc)

1. **Kết nối BigQuery** → thẻ *Xác thực Google*:
   - nhập Client ID và Client secret → *Lưu OAuth client*;
   - bấm **Đăng nhập Google** và đăng nhập bằng tài khoản công ty.
2. Bấm **Kiểm tra quyền BigQuery**. Ứng dụng chạy các cổng theo thứ tự và dừng ở cổng đầu tiên lỗi:

   | Cổng | Ý nghĩa |
   |---|---|
   | Xác thực | lấy được credentials của tài khoản Windows này |
   | BigQuery API + dataset | API bật, đọc được dataset |
   | Location | đúng `asia-southeast1` |
   | Metadata bảng | đọc được metadata bảng nguồn |
   | Query job | dry-run trên bảng + `SELECT 1` (0 byte) |
   | Schema khớp ánh xạ | schema thật khớp ánh xạ đã lưu |

   Mọi cổng phải **Đạt**.
3. Ánh xạ trường → *Gợi ý cho bảng demand_planing_lightgbm* → xem lại → *Kiểm tra & lưu*.
4. **Kiểm tra dữ liệu toàn kỳ**: phải **Đạt**. Đây là cổng "dữ liệu đủ điều kiện cho pipeline".
5. SQL nguồn & đồng bộ → D0:
   - *Kiểm tra (dry-run)* phiên bản 1 (SQL gốc) và phiên bản 2 (đề xuất);
   - chọn phiên bản đúng nghiệp vụ;
   - *Kiểm tra dữ liệu* phải không có lỗi khóa trùng.

## 6. Điều kiện được bật D0 BigQuery

Chỉ bật **Lịch D0 BigQuery** (trang SQL nguồn, mặc định TẮT) khi đủ các điều kiện:
- mọi cổng ở bước 5.2 đạt;
- phiên bản SQL D0 đang dùng đã dry-run đạt;
- *Kiểm tra dữ liệu* D0 không có `KEY_NOT_UNIQUE` / `EXACT_DUPLICATES`, hoặc người dùng đã chọn rõ chính sách;
- các ngày trong kết quả D0 đúng là hôm nay;
- nguồn BIGQUERY đã kích hoạt chế độ sản xuất.

## 7. Rollback về 1.1.5

```powershell
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\DemandForecast\1.1.6\scripts\rollback-version.ps1" -To 1.1.5 -CheckOnly
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\DemandForecast\1.1.6\scripts\rollback-version.ps1" -To 1.1.5
```

Script làm các bước sau:
1. kiểm tra schema DB không mới hơn 1.1.5 (schema 3 = 3: không cần khôi phục DB);
2. hỏi xác nhận `ROLLBACK-1.1.5`;
3. dừng 1.1.6, khởi động 1.1.5;
4. cập nhật `current.txt` và shortcut;
5. kiểm tra health.

**Kiểm tra sau rollback:**
- trang Tổng quan đúng nguồn/scope;
- trang Kết quả còn các forecast run;
- **Hệ thống & sao lưu** → *Kiểm tra sức khỏe DB* báo integrity ok.

Phiên bản SQL và OAuth client ID lưu bởi 1.1.6 được 1.1.5 bỏ qua. Nên bấm *Đăng xuất* trước khi rollback để xóa token khỏi Credential Manager.
