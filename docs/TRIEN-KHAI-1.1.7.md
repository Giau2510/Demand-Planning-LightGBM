# Demand Forecasting 1.1.7 — ghi chú phát hành, nâng cấp và quay về

Gói: `DemandForecast-1.1.7-win64-portable.zip` (SHA-256 trong file `.sha256` cạnh gói và trong báo cáo phát hành).
Schema cơ sở dữ liệu **không đổi (3)**: nâng cấp không chạy migration nào; quay về 1.1.6 không cần khôi phục DB.

## Thay đổi người dùng sẽ thấy

1. **Cửa sổ dữ liệu từ 01/01/2026.** Mô hình (huấn luyện, backtest, forecast, báo cáo chất lượng) chỉ dùng các ngày đã
   đóng theo giờ Việt Nam từ `data_policy.window_start_date` (mặc định 2026-01-01) đến **hôm qua**. Hôm nay chỉ dùng cho
   D0; ngày tương lai không bao giờ dùng. Dữ liệu cũ hơn **vẫn được lưu** nhưng không dùng. Dashboard hiển thị cửa sổ.
   BigQuery không còn tải lùi 2 năm.
2. **Backtest dài hơn.** Tối đa 12 fold × 30 ngày (~12 tháng), tự rút ngắn theo dữ liệu thực có; trang *Hiệu năng model*
   hiển thị số fold, ngày đầu/cuối và số ngày thực tế. Dưới 6 tháng có cảnh báo `BACKTEST_SPAN_BELOW_6_MONTHS`.
3. **Model đang dùng được bảo vệ.** Khi đã có model đang dùng, model mới đạt quality gate **không tự thay thế**: nó ở
   trạng thái *Chờ duyệt thay model* kèm so sánh trên cùng các fold (WAPE, bias, MAE, MAPE; kết luận Tốt hơn / Kém hơn /
   Ngang nhau / Không đủ dữ liệu). Bấm **Dùng model này** ở trang *Hiệu năng model* để publish forecast từ model mới.
   Hệ quả vận hành: khi có dữ liệu mới, forecast chỉ đổi sau khi người dùng duyệt (cho tới khi nghiệp vụ phê duyệt một
   tiêu chí tự động).
4. **Đăng nhập Google hoàn chỉnh hơn.** Nhập file JSON OAuth client; cổng `auth` xin token thật từ Google; phân biệt
   rõ lỗi đăng nhập / client / scope / quyền IAM / mạng, mỗi lỗi có việc cần làm; thẻ *Nội dung gửi quản trị Google
   Cloud*; lệnh `python -m app.cli bq-check`.
5. **Sửa lỗi:** truy vấn "bản ghi mới nhất" xác định khi nhiều bản ghi cùng giây; giải thích forecast / tạo thêm
   forecast / xuất điểm backtest của run cũ luôn dựng lại đúng dữ liệu của run đó (trước đây phụ thuộc cấu hình hiện tại).
6. **Mới:** `python -m app.cli data-check` (kiểm tra bất biến dữ liệu, chỉ đọc).

Mặc định thay đổi (áp dụng ngay cho các mục cấu hình chưa từng lưu): `data_policy.window_start_date = 2026-01-01` (mới),
`model.backtest_folds 3→12`, `model.backtest_horizon_days 14→30`, `model.backtest_step_days 7→30`.

## Nâng cấp (máy đang chạy 1.1.6)

Làm ngoài các mốc lịch (D0 08:00–18:00 mỗi 2 giờ, D-1 từ 01:00, huấn luyện 07:00), khi không có job đang chạy.

```powershell
cd "D:\Buymed\Lightgbm AI"
powershell -ExecutionPolicy Bypass -File scripts\deploy-upgrade.ps1 -Package dist\DemandForecast-1.1.7-win64-portable.zip -ExpectedSha256 <SHA256> -CheckOnly
powershell -ExecutionPolicy Bypass -File scripts\deploy-upgrade.ps1 -Package dist\DemandForecast-1.1.7-win64-portable.zip -ExpectedSha256 <SHA256>
```

Lần chạy thứ hai: kiểm tra trước → sao lưu chính thức → hỏi xác nhận, gõ `UPGRADE-1.1.7` → dừng 1.1.6 → cài 1.1.7
(sao lưu thêm, không có migration) → khởi động → kiểm tra sau (phiên bản, thư mục dữ liệu, nguồn đang chọn,
`storage.json` không đổi). Log: `<logs>\deploy-<thời gian>.log`.

Sau nâng cấp: mở *Hiệu năng model* và Dashboard; cửa sổ dữ liệu hiển thị 01/01/2026 → hôm qua. Model/forecast đang
dùng không đổi cho tới lần huấn luyện kế tiếp có dữ liệu mới (khi đó có model chờ duyệt).

## Quay về 1.1.6

```powershell
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.1.7\scripts\rollback-version.ps1" -To 1.1.6 -CheckOnly
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.1.7\scripts\rollback-version.ps1" -To 1.1.6
```

Gõ `ROLLBACK-1.1.6`. Không cần khôi phục DB (schema 3). Lưu ý: model chờ duyệt do 1.1.7 tạo hiển thị trong 1.1.6 như một
lần huấn luyện *không đạt* (lý do `PROMOTION_REVIEW_REQUIRED`); 1.1.6 không có nút duyệt và sẽ tự publish model mới ở
lần huấn luyện sau như trước.

## Google / BigQuery — việc quản trị viên cần làm (không đổi so với 1.1.6)

1. OAuth client loại **Desktop app** (consent screen Internal; scopes `openid`, `email`,
   `https://www.googleapis.com/auth/bigquery`) → gửi file JSON client qua kênh an toàn.
2. Bật BigQuery API (project `lakehouse-prod-394907` và project chứa client).
3. Tài khoản Google của người dùng: `roles/bigquery.jobUser` trên `lakehouse-prod-394907`,
   `roles/bigquery.dataViewer` trên `lakehouse-prod-394907.gold_buymed_vn2` (location `asia-southeast1`).

Sau đó trong ứng dụng: *Xác thực Google* → chọn file JSON → *Đăng nhập Google* → *Kiểm tra quyền BigQuery* (6 cổng đạt)
→ ánh xạ cột → *Kiểm tra dữ liệu toàn kỳ* → thử SQL D0 v1/v2. Production BigQuery và lịch D0 vẫn **tắt** cho tới khi
các bước này đạt và nghiệp vụ xác nhận định nghĩa target (đơn hủy).
