# Demand Forecasting 1.1.8 — lịch chạy D-1 / D-0 riêng: ghi chú phát hành, nâng cấp, quay về

Gói: `DemandForecast-1.1.8-win64-portable.zip` (SHA-256 trong file `.sha256` cạnh gói và trong báo cáo phát hành).
Bao gồm toàn bộ thay đổi của 1.1.7 (chưa từng được cài) và phần lịch chạy dưới đây. Schema cơ sở dữ liệu **không đổi
(3)**: không có migration; quay về 1.1.6 không cần khôi phục DB.

## Người dùng sẽ thấy gì

Menu **Quản trị → Lịch chạy dữ liệu** (`/schedules`), ba thẻ độc lập:

| Thẻ | Nội dung | Mặc định sau nâng cấp |
|---|---|---|
| **D-1: Dữ liệu ngày đã đóng** | đồng bộ ngày đã đóng từ BigQuery, giờ bắt đầu chờ tín hiệu, giờ dự phòng, chu kỳ kiểm tra; cửa sổ 01/01/2026 → hôm qua (giờ VN) | **TẮT**; với nguồn DEMO/Excel hiển thị *Chưa sẵn sàng* (chỉ áp dụng cho BigQuery) |
| **D-0: Dữ liệu ngày hiện tại** | các giờ chụp snapshot hôm nay, chính sách khi lỡ mốc | **TẮT** |
| **Huấn luyện hằng ngày** | giờ huấn luyện, chính sách khi lỡ giờ | giữ như trước (BẬT nếu công tắc chung cũ đang bật) |

Mỗi thẻ: trạng thái thật từ backend (*Tắt*, *Đang bật — scheduler đã nạp*, *Đã bật nhưng chưa sẵn sàng*, *Đã lưu bật —
scheduler không chạy*), sẵn sàng/chưa và lý do, múi giờ `Asia/Ho_Chi_Minh`, lần chạy gần nhất và kết quả, lần chạy tiếp
theo, nhật ký gần đây, các nút **Lưu giờ chạy**, **Bật/Tắt luồng này**, **Chạy ngay 1 lần**. Nút bật/chạy bị khóa khi
luồng chưa sẵn sàng. Bật D-0 có hộp xác nhận.

Quy tắc: lưu giờ không chạy job nào; bật một luồng không bật luồng khác; chỉ các mốc giờ **sau** thời điểm bật mới chạy.

## Cấu hình D-1 và D-0

1. Mở *Lịch chạy dữ liệu*. Sửa giờ trong thẻ cần đổi → **Lưu giờ chạy** (luồng giữ nguyên trạng thái bật/tắt).
2. Bật: **Bật luồng này** (chỉ khi thẻ báo *Sẵn sàng*).
   - D-1 sẵn sàng khi: nguồn BIGQUERY, production BigQuery đã bật, *Kiểm tra dữ liệu toàn kỳ* đạt.
   - D-0 sẵn sàng khi: DEMO (snapshot tổng hợp) hoặc BIGQUERY production + SQL D-0 đã được BigQuery xác nhận.
3. Tắt: **Tắt luồng này** (luôn được).

## Khi ứng dụng tắt đúng giờ chạy

- D-1: khi mở lại (sau giờ bắt đầu) chạy một lần cho hôm đó; chỉ đọc ngày đã đóng, tăng dần theo watermark nên không
  trùng; ngày bị bỏ lỡ hoàn toàn được ghi *bỏ qua*.
- D-0: mốc đã lỡ được ghi *bỏ qua*; chạy bù chỉ khi chọn *Chạy bù 1 lần* (một snapshot của hôm nay, ghi giờ thật);
  không bao giờ chạy bù ngày cũ.
- Huấn luyện: theo lựa chọn *Khi lỡ giờ huấn luyện*.

## Nâng cấp (máy đang chạy 1.1.6)

Ngoài các mốc lịch, khi không có job đang chạy:

```powershell
cd "D:\Buymed\Lightgbm AI"
powershell -ExecutionPolicy Bypass -File scripts\deploy-upgrade.ps1 -Package dist\DemandForecast-1.1.8-win64-portable.zip -ExpectedSha256 <SHA256> -CheckOnly
powershell -ExecutionPolicy Bypass -File scripts\deploy-upgrade.ps1 -Package dist\DemandForecast-1.1.8-win64-portable.zip -ExpectedSha256 <SHA256>
```

Gõ `UPGRADE-1.1.8` khi được hỏi. Sau nâng cấp: snapshot D0 DEMO (trước đây chạy mỗi 2 giờ theo công tắc chung) **dừng**
cho tới khi bật D-0 ở trang mới; huấn luyện 07:00 giữ nguyên. Các thay đổi 1.1.7 (cửa sổ dữ liệu, backtest, model chờ
duyệt, đăng nhập Google) cũng có hiệu lực — xem `docs/TRIEN-KHAI-1.1.7.md`.

## Quay về 1.1.6

```powershell
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.1.8\scripts\rollback-version.ps1" -To 1.1.6
```

Gõ `ROLLBACK-1.1.6`. Không cần khôi phục DB. 1.1.6 bỏ qua các công tắc mới và dùng lại công tắc chung cũ (thường đang
bật), nên lịch chạy trở lại như trước 1.1.8.
