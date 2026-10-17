# Link xem dashboard từ xa (chỉ đọc)

Tài liệu này dành cho người vận hành máy Windows chạy Demand Forecasting.

Mục đích: tạo một link HTTPS để người khác, ví dụ sếp, mở dashboard bằng Chrome trên máy của họ. Người xem không cần cài
gì, không cần VPS, tên miền hay mở cổng router.

Link dùng **Cloudflare Quick Tunnel**: miễn phí, không cần tài khoản, tên miền dạng `https://<từ ngẫu nhiên>.trycloudflare.com`.

## 1. Cách dùng (3 bước)

1. Bấm đúp **`Start-DemandForecast-Remote.bat`**, nằm trong thư mục dự án `D:\Buymed\Lightgbm AI`.
2. Chờ cửa sổ in dòng `LINK GUI SEP (chi xem): https://....trycloudflare.com`. Lần đầu mất khoảng 1–2 phút.
   - Link đã được chép sẵn vào clipboard; dán (Ctrl+V) vào tin nhắn gửi sếp.
   - Cửa sổ có thể đóng. Link vẫn chạy cho tới khi dừng.
3. Muốn ngừng chia sẻ: bấm đúp **`Stop-DemandForecast-Remote.bat`**. Ứng dụng chính trên máy vẫn chạy bình thường.

Launcher tự làm các việc sau:

| Bước | Việc launcher làm |
|---|---|
| Kiểm tra ứng dụng | Gọi `http://127.0.0.1:8765/api/health`. Nếu ứng dụng chưa chạy, launcher mở bằng `scripts\start.ps1` của bản đã cài và chờ tối đa 150 giây. Nếu ứng dụng đang chạy, launcher không khởi động lại. |
| Proxy chỉ đọc | Chạy `scripts\remote\readonly_proxy.py` ở `127.0.0.1:8766`, dùng Python có sẵn trong ứng dụng. |
| cloudflared | Lần đầu tải `cloudflared-windows-amd64.exe` từ trang phát hành chính thức `github.com/cloudflare/cloudflared`. File chỉ được dùng khi **SHA-256 khớp trang phát hành** và **chữ ký số Cloudflare hợp lệ**; mỗi lần chạy sau đều kiểm tra lại. |
| Tunnel | Mở tunnel HTTPS, chỉ trỏ vào proxy chỉ đọc, **không bao giờ** trỏ thẳng vào cổng ứng dụng. |
| Kiểm tra link | Từ chính máy này, qua HTTPS: API trả lời, giao diện tải được, một thao tác ghi bị từ chối. Nếu đạt, cửa sổ ghi "Da kiem tra ... thao tac ghi bi chan". |
| Chạy lại | Bấm Start khi tunnel đang chạy thì dùng lại link cũ, không tạo tiến trình trùng. |

## 2. Người xem làm được gì

- **Xem** được mọi trang: Tổng quan, Kết quả dự báo, Chất lượng mô hình, Lịch sử Snapshot D0, Lịch chạy dữ liệu, Job,
  Chất lượng dữ liệu, Feature, Giải thích. Có thể tải file Excel kết quả dự báo và snapshot.
- **Không làm được** (trả mã `REMOTE_READ_ONLY`, ứng dụng không nhận được yêu cầu):
  - huấn luyện, dự báo, chạy hoặc bật/tắt lịch, đồng bộ BigQuery;
  - nhập hoặc xóa dữ liệu, lưu cấu hình, sao lưu, tắt ứng dụng.
  Cuối mỗi trang có dải chữ "Chế độ xem từ xa — CHỈ ĐỌC".
- **Không mở được** (trả mã `REMOTE_FORBIDDEN`):
  - đường dẫn lưu trữ, chẩn đoán, danh sách bản sao lưu, nhật ký audit, lịch sử cấu hình;
  - trạng thái và danh tính Google/BigQuery, file báo cáo trùng, tài liệu API;
  - lệnh "làm mới" nặng của trang chất lượng dữ liệu.
- Dữ liệu JSON trả ra ngoài đã được **xóa đường dẫn trên máy** (thư mục dữ liệu, model, log...) và các trường danh tính.
  Ứng dụng không bao giờ trả token, mật khẩu hay khóa; credentials Google vẫn chỉ nằm trong máy này.
- Proxy giới hạn 300 yêu cầu/phút cho mỗi người xem và 6 yêu cầu đồng thời tới ứng dụng.

## 3. Giới hạn vận hành (cần biết)

- Máy Windows này phải **bật, có Internet và không ngủ**. Ứng dụng và tunnel phải đang chạy.
  - Máy tắt, ngủ hay mất mạng thì người xem không mở được link.
  - Nên chỉnh Windows: Settings → System → Power → *Sleep: Never* khi đang cho xem.
- **Link đổi** mỗi lần tunnel khởi động lại: sau Stop/Start, sau khởi động lại máy, hoặc khi cloudflared bị dừng. Khi đó
  gửi link mới cho người xem.
- **Ai có link đều xem được**, không có đăng nhập. Chỉ gửi cho người cần xem; ngừng chia sẻ bằng Stop.
  - Link gồm các từ ngẫu nhiên và không tự xuất hiện trên công cụ tìm kiếm (`noindex`).
  - Nhưng link không phải là mật khẩu.
- Quick Tunnel là dịch vụ thử nghiệm miễn phí của Cloudflare:
  - không cam kết thời gian hoạt động;
  - tuân theo điều khoản sử dụng của Cloudflare.
  Đây **không** tương đương một dịch vụ production chạy độc lập trên cloud. Muốn link cố định, có đăng nhập và luôn sẵn
  sàng thì cần named tunnel (tài khoản và tên miền Cloudflare) hoặc VPS; xem `docs/TRIEN-KHAI-VPS.md`. Bước này chưa làm.
- Mạng công ty hoặc tường lửa chặn kết nối ra ngoài của cloudflared (cổng 443 và 7844) thì không tạo được link.

## 4. Lỗi thường gặp

Launcher in thông báo tiếng Việt không dấu, kèm dòng "Cach xu ly".

| Thông báo | Ý nghĩa và cách xử lý |
|---|---|
| `Khong tim thay ung dung Demand Forecasting da cai` | Chưa cài ứng dụng (thiếu `%LOCALAPPDATA%\Programs\DemandForecast\current.txt`). Cài bằng `Install.bat` của gói phát hành. |
| `Ung dung khong san sang sau 150 giay` | Ứng dụng không khởi động được. Mở `Start.bat` của ứng dụng để xem lỗi, hoặc đọc phần cuối `server.err.log` mà launcher in ra. |
| `Cong 8766 dang bi chuong trinh khac dung` | Đóng chương trình đang dùng cổng 8766, hoặc chạy `scripts\remote\remote-access.ps1 start -ProxyPort 8770`. |
| `Khong ket noi duoc GitHub de tai cloudflared` | Không có Internet hoặc proxy công ty chặn. Hoặc tải tay `cloudflared-windows-amd64.exe` từ trang phát hành, đổi tên thành `cloudflared.exe` và đặt vào `%LOCALAPPDATA%\DemandForecastRemote\bin\`. File chỉ được dùng khi có chữ ký Cloudflare hợp lệ. |
| `SHA-256 ... KHONG khop` hoặc `khong con dung ban da xac minh` | File cloudflared bị thay đổi hoặc hỏng, launcher từ chối dùng. Xóa file đó rồi chạy lại để tải bản chính thức. |
| `cloudflared da dung ... truoc khi co link` / `Khong nhan duoc link sau 90 giay` | Không có Internet, hoặc dịch vụ Quick Tunnel không trả lời. Kiểm tra mạng rồi chạy lại. |
| `CHUA xac minh duoc link` | Đã có link nhưng máy này chưa mở được qua HTTPS. Thử mở link sau 1–2 phút; nếu vẫn không được thì Stop rồi Start. |

Lệnh xem trạng thái: `powershell -ExecutionPolicy Bypass -File scripts\remote\remote-access.ps1 status`. Lệnh in link
hiện tại, tiến trình và kết quả kiểm tra link.

## 5. File và vị trí

| Loại | Vị trí | Ghi chú |
|---|---|---|
| Launcher | `Start-DemandForecast-Remote.bat`, `Stop-DemandForecast-Remote.bat` | Thư mục dự án |
| Logic | `scripts\remote\remote-access.ps1` | ASCII, PowerShell 5.1 |
| Proxy | `scripts\remote\readonly_proxy.py` | Chỉ dùng thư viện chuẩn Python |
| File chạy | `%LOCALAPPDATA%\DemandForecastRemote\` | Gồm `bin\cloudflared.exe` và `bin\cloudflared.json` (phiên bản, SHA-256, chữ ký); `run\*.json` (pid, link); `logs\` (log cloudflared, log truy cập của proxy: thời điểm, mã băm ngắn của người xem, đường dẫn, mã trả lời, không ghi IP) |

Thư mục này tách khỏi dữ liệu ứng dụng; xóa nó không ảnh hưởng ứng dụng.

Gỡ bỏ:
1. Stop.
2. Xóa thư mục `%LOCALAPPDATA%\DemandForecastRemote`.
3. Xóa hai file `.bat` và thư mục `scripts\remote`.

## 6. Đã kiểm tra thật (17/10/2026, trên máy này, ứng dụng 1.2.0)

- **Tải cloudflared:** cloudflared 2026.10.1 tải từ GitHub chính thức; SHA-256 khớp trang phát hành; chữ ký Cloudflare hợp lệ.
- **Hai link thật trên dashboard production, đều đã dừng:**
  - Qua HTTPS, `/api/health` và dashboard trả dữ liệu thật: nguồn BIGQUERY, dữ liệu 01/01–16/10/2026.
  - Giao diện tải đủ JS và CSS. Chạy trong trình duyệt Edge headless, giao diện hiển thị đúng; không có lỗi mixed content hay CORS.
  - 5 thao tác ghi bị chặn (405).
  - 6 trang quản trị bị chặn (403).
  - Không lộ đường dẫn trên máy.
- **Các tình huống khác:**
  - chạy lại khi tunnel đang chạy thì dùng lại link, không tạo tiến trình trùng;
  - Stop xong thì link cũ chết và ứng dụng vẫn chạy;
  - Start lại thì có link mới;
  - ứng dụng khởi động chậm (21 giây) thì launcher chờ được;
  - ứng dụng không khởi động được thì báo lỗi;
  - không tải được cloudflared thì báo lỗi;
  - dịch vụ tunnel không trả lời thì báo lỗi;
  - file cloudflared bị sửa thì launcher từ chối dùng.
