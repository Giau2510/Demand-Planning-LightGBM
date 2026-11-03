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
  sàng thì cần named tunnel (tài khoản và tên miền Cloudflare) hoặc VPS; xem `docs/03_van_hanh/TRIEN-KHAI-VPS.md`. Bước này chưa làm.
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

## Phụ lục gộp (03/11/2026): link Tailscale, sự cố và cách dựng link

Phần trên là hướng dẫn của branch này (Cloudflare Quick Tunnel, `scripts\remote\remote-access.ps1`). Link đang chạy trên máy thật dùng Tailscale Funnel; công cụ của nó (`Setup-DemandForecast-Link.bat`, `scripts\remote\link_supervisor.py`, `link-watchdog.ps1` …) hiện chỉ có trong worktree `D:\Buymed\Lightgbm AI` (chưa commit), nên mục 1 dưới đây chép bản hướng dẫn của worktree đó. Các mục sau chép nguyên văn các báo cáo sự cố / triển khai link. Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `REMOTE_ACCESS_GUIDE.md` (MAIN) | 26/10/2026 | 12153 | `2B72AF4D5C537B7670C342E335D38259DD539ADC6A2637ECF7438AA7E8A5922A` |
| 2 | `reports\demandforecast_remote_access_recovery.md` (MAIN) | 19/10/2026 | 8169 | `A8C40E6B252B47A5E34D1F30C56C07E67493E44C71F2C57A8A07E3495C2843D4` |
| 3 | `reports\remote-link-20261024\REPORT.md` (MAIN) | 25/10/2026 | 13418 | `D095E692A5C2F7542A12D35D7F712011D605CA77FA14CFD4036B102E395C57B1` |
| 4 | `reports\remote-link-20261024\REPORT-TAILSCALE-20261025.md` (MAIN) | 25/10/2026 | 7431 | `E89D1D771AB75A2EA9926C366D50108A353B2E5F7B5B462A319559430E963C7D` |

### 1. Link xem từ xa cố định (chỉ đọc)

Nguồn: `REMOTE_ACCESS_GUIDE.md` (worktree MAIN).

Tài liệu này dành cho người vận hành máy Windows chạy Demand Forecasting.

**Mục đích:** một link HTTPS **cố định** để sếp mở dashboard bằng trình duyệt.
- Người xem không cài gì.
- Người xem chỉ **xem** được, không sửa được gì.
- Link tự bật khi ứng dụng chạy và tự tắt khi ứng dụng tắt.

**Có hai cách tạo link:**

| Cách | Link | Chi phí | Cần gì |
|---|---|---|---|
| **Tailscale Funnel** (khuyến nghị nếu chưa có tên miền) | `https://<tên máy>.<tailnet>.ts.net` | Miễn phí (gói Personal) | Cài Tailscale (cần quyền quản trị Windows một lần), một tài khoản Tailscale |
| **Cloudflare Tunnel** | `https://<tên con>.<tên miền của bạn>` | Miễn phí nếu đã có tên miền | Tài khoản Cloudflare có tên miền, hoặc token tunnel do IT cấp |

**Có hai mức quyền người xem:**
- **Công khai, chỉ đọc** (mặc định khi chọn Tailscale): ai có link đều xem được, không cần đăng nhập.
- **Đăng nhập:** tài khoản `viewer` với mật khẩu ngẫu nhiên.

Cả hai cách đều chỉ cho máy này **kết nối ra ngoài**: không mở cổng router, không mở firewall chiều vào. Link luôn đi
qua proxy chỉ đọc ở `127.0.0.1:8766`, không bao giờ trỏ thẳng vào cổng 8765 của ứng dụng.

### 0. Điều kiện an toàn (bắt buộc trước khi mở link)

Ngày 24/10/2026 máy có một mục tự khởi động *Green Christmas Tree*. Nó chạy một file `.exe` giải nén từ
`quà giáng sinh.zip` trong thư mục Temp.
- Ngày 25/10 file đã không còn và không chạy.
- Microsoft Defender chưa từng phát hiện file này.
- Nhưng chưa xác minh được là an toàn.

Vì vậy Setup **từ chối mở link ra Internet** cho tới khi đủ ba điều kiện. Setup chỉ kiểm tra, không thay đổi gì:

1. Không còn mục tự khởi động nào chạy file trong thư mục Temp đang **bật**.
   - Cách làm: Task Manager → *Startup apps* → chọn mục đó → *Disable*. Hoặc nhờ IT kiểm tra và gỡ.
2. Có một lần **quét toàn bộ (Full scan)** của Microsoft Defender kết thúc sau ngày 24/10/2026.
   - Cách làm: *Windows Security* → *Virus & threat protection* → *Scan options* → *Full scan* → *Scan now*.
   - Quét mất vài giờ. Không cần quyền quản trị.
3. Defender **không phát hiện** mối đe dọa nào kể từ 24/10/2026, và chế độ bảo vệ thời gian thực đang bật.

**Cập nhật 25/10/2026:** chủ máy xác nhận *Green Christmas Tree* là chương trình tự cài.
- Xác nhận được ghi trong `%LOCALAPPDATA%\DemandForecastRemote\config\security-ack.json`.
- Mục được liệt kê trong file đó không còn chặn, và yêu cầu full scan gắn với phát hiện này được bỏ.
- Điều kiện 3 vẫn được kiểm tra.
- Mục tự khởi động được **giữ nguyên**.

### 1. Cài đặt một lần

1. Bấm đúp **`Setup-DemandForecast-Link.bat`** trong `D:\Buymed\Lightgbm AI`, hoặc mở Start Menu → *Demand Forecasting
   Link* → *Link xem tu xa - cai dat lai*.
2. Setup kiểm tra điều kiện an toàn (mục 0). Nếu chưa đạt, nó in việc cần làm rồi dừng; chưa có gì được cài hay mở ra
   Internet.
3. Chọn cách tạo link: `1` = Tailscale Funnel, `2` = Cloudflare (đăng nhập), `3` = Cloudflare (token).
4. Chọn quyền người xem: `1` = công khai, chỉ đọc; `2` = cần đăng nhập.
5. **Với Tailscale**, setup dừng ở ba bước cần bạn:
   1. **Quyền quản trị Windows:** cài bộ cài chính thức Tailscale. Bộ cài đã kiểm SHA-256 và chữ ký *Tailscale Inc.*.
      - Tài khoản Windows này không phải quản trị, nên Windows hỏi mật khẩu của tài khoản quản trị (`LOG-PC\Administrator`).
      - Nếu không có mật khẩu đó, nhờ IT.
   2. **Đăng nhập Tailscale:** trang `login.tailscale.com` mở trong trình duyệt. Đăng nhập bằng tài khoản của bạn
      (Google / Microsoft / GitHub …).
   3. **Cho phép HTTPS và Funnel** (chỉ lần đầu): trang Tailscale mở ra; bấm cho phép, rồi quay lại cửa sổ Setup và bấm
      Enter.
6. Setup bật link và **tự kiểm tra qua Internet**:
   - đi qua DNS công cộng, đúng đường mà người xem dùng;
   - chứng chỉ TLS, phiên bản ứng dụng;
   - các thao tác ghi bị chặn, các trang quản trị bị chặn;
   - tắt Funnel rồi xác nhận nó tự bật lại với cùng tên máy.
7. Cuối cùng Setup in link và chép **riêng link** vào clipboard. Không bao giờ chép mật khẩu.

Không gửi mật khẩu quản trị Windows hay mật khẩu Tailscale cho bất kỳ ai, kể cả trợ lý AI. Script không lưu chúng.

### 2. Hằng ngày: không phải làm gì

| Việc của bạn | Link |
|---|---|
| Mở ứng dụng như thường lệ (*Demand Forecasting* trong Start Menu, hoặc `Start.bat`) | Tự bật trong khoảng 10–60 giây |
| Đóng ứng dụng (`Stop.bat`) | Tự tắt sau 60 giây. Với Tailscale: Funnel được **tắt**. Ứng dụng khởi động lại nhanh thì link không bị ngắt |
| Khởi động lại máy, đăng nhập Windows | Tác vụ `DemandForecastLink` tự chạy; link bật khi ứng dụng chạy |
| Mất mạng, Funnel hoặc tunnel bị tắt | Tự bật lại, thử lại tăng dần 5 giây … 5 phút, tối đa 12 lần/giờ. **Cùng tên miền** |
| Cài bản ứng dụng mới bằng `deploy-upgrade.ps1`, hoặc rollback | Link tự phục vụ bản đang chạy theo `current.txt`. Không sửa link |

Shortcut trong Start Menu → *Demand Forecasting Link*:

| Shortcut | Việc |
|---|---|
| *thong tin* | Trạng thái và link (chép link vào clipboard) |
| *tam dung* | Ngừng chia sẻ cho tới khi bật lại, kể cả sau khi khởi động lại máy |
| *bat lai* | Chia sẻ lại |
| *cai dat lai* | Chạy lại Setup |

### 3. Người xem làm được gì

- **Xem** được các trang dữ liệu:
  - Tổng quan, Kết quả dự báo, Lịch sử dự báo & thực tế;
  - Chất lượng mô hình, Snapshot, Feature, Phương pháp.
- **Tải** được Excel kết quả dự báo, snapshot và lịch sử.
- **Không làm được bất kỳ thao tác ghi nào** (`405 REMOTE_READ_ONLY`; ứng dụng không hề nhận yêu cầu):
  - huấn luyện, dự báo, chạy lịch, đồng bộ;
  - nhập hoặc xóa dữ liệu, lưu cấu hình, sao lưu, tắt ứng dụng.
- **Không mở được** (`403 REMOTE_FORBIDDEN`):
  - đường dẫn lưu trữ, chẩn đoán, sao lưu, audit, lịch sử cấu hình;
  - danh tính Google/BigQuery, tài liệu API.
- **Chế độ công khai còn chặn thêm** (403):
  - SQL nguồn, cấu hình BigQuery, lô nhập, danh sách job, lịch chạy, trạng thái đồng bộ;
  - các giải thích SHAP tính theo yêu cầu (nặng: người lạ không làm máy chậm được).
- **Dữ liệu trả ra trong chế độ công khai:**
  - đã xóa đường dẫn trên máy;
  - đã xóa tên project / dataset / bảng BigQuery;
  - đã ẩn nội dung lỗi;
  - `/api/settings` không còn phần `bigquery`, `sql_sources`, `import`.
- **Lưu ý chế độ công khai:**
  - Ai có link đều xem được dữ liệu dự báo, và link có thể bị chuyển tiếp cho người khác.
  - Không thu hồi được cho từng người.
  - Muốn ngừng: *tam dung*. Muốn đổi link Tailscale: đổi tên máy trong trang quản trị Tailscale, rồi chạy lại Setup.

### 4. Bảo mật

| Lớp | Cách làm |
|---|---|
| Chỉ đọc | Proxy chỉ chuyển GET thuộc danh sách cho phép; mọi phương thức khác trả 405 |
| Chỉ bản production | Link chỉ bật khi tiến trình trên cổng 8765 là runtime **đã cài** của `current.txt` và nguồn dữ liệu không phải DEMO |
| Đăng nhập (nếu chọn) | Mật khẩu băm PBKDF2-SHA256 (600.000 vòng); cookie ký HMAC `HttpOnly; Secure; SameSite=Lax`, hết hạn sau 12 giờ; sai 5 lần thì khóa 15 phút |
| Chống quá tải | 300 yêu cầu/phút cho mỗi người xem, tối đa 6 yêu cầu đồng thời tới ứng dụng |
| Bí mật | Mật khẩu người xem và token tunnel lưu bằng Windows DPAPI. Log không ghi mật khẩu, cookie hay token (self-test có kiểm tra). Clipboard chỉ nhận link |
| Không khóa thư mục ứng dụng | Bộ giám sát chạy bằng bản Python riêng trong `%LOCALAPPDATA%\DemandForecastRemote\runtime`. `install.ps1` từ chối cài khi có `python.exe` chạy trong thư mục đích, nên link không được chạy từ đó |

### 5. Trạng thái

Xem trạng thái: shortcut *thong tin*, hoặc `scripts\remote\remote-access.ps1 status`.

| Trạng thái | Ý nghĩa |
|---|---|
| `ONLINE` | Đã kiểm tra qua Internet |
| `NOT_CONFIGURED` | Chưa chạy Setup |
| `WAITING_APP` / `APP_GRACE` | Ứng dụng chưa chạy hoặc vừa tắt |
| `PAUSED` | Bạn đã tạm dừng |
| `NOT_PRODUCTION` | Cổng 8765 không phải bản production đã cài, hoặc đang dùng nguồn DEMO. Link cố ý tắt |
| `TAILSCALE_DOWN` | Tailscale chưa chạy hoặc chưa đăng nhập trên máy này |
| `FUNNEL_NOT_ALLOWED` | Tailnet chưa cho phép HTTPS/Funnel. Mở link trong cột lý do và bấm cho phép |
| `NO_TAILSCALE` | Chưa cài Tailscale |
| `CONNECTING` / `BACKOFF` / `COOLDOWN` | Đang kết nối hoặc chờ thử lại |
| `DEGRADED` | Đã bật nhưng chưa mở được qua Internet. Sau 3 lần lỗi, Funnel hoặc tunnel được bật lại (tối đa 1 lần / 30 phút) |

Log nằm trong `%LOCALAPPDATA%\DemandForecastRemote\logs\`:
- `link-supervisor.log`, `link-task.log`, `cloudflared-link.log`;
- `proxy-access.log`: không ghi IP, mật khẩu hay cookie;
- `selftest-*.json`.

### 6. Giới hạn cần biết

- Máy phải **bật, có Internet, không ngủ**; bạn phải **đăng nhập Windows**; ứng dụng phải chạy.
- Tailscale phải chạy và đã đăng nhập. Link phụ thuộc dịch vụ Tailscale hoặc Cloudflare.
- **Tailscale trên máy này chạy ở chế độ unattended.** Nếu không, Tailscale chỉ giữ kết nối khi ứng dụng khay đang mở.
  Ở chế độ này nó tự kết nối như dịch vụ, kể cả sau khi khởi động lại máy.
- **Khóa máy Tailscale hết hạn sau 180 ngày** theo mặc định; khi đó link tắt cho tới khi đăng nhập lại.
  - Muốn link chạy lâu dài: trang quản trị Tailscale → *Machines* → `log-pc` → *Disable key expiry*.
- **Funnel gói miễn phí:**
  - băng thông có giới hạn, Tailscale không công bố con số;
  - chỉ cổng 443 / 8443 / 10000;
  - tên link gắn với tên máy và tailnet.
- Funnel dùng cổng 443 của máy trong tailnet. Nếu bạn tự cấu hình `tailscale serve/funnel` khác trên cổng 443, bộ giám
  sát sẽ thay thế cấu hình đó.

### 7. File và gỡ bỏ

| Loại | Vị trí |
|---|---|
| Nút bấm | `Setup-DemandForecast-Link.bat`, `Start-DemandForecast-Remote.bat` (bật lại), `Stop-DemandForecast-Remote.bat` (tạm dừng) |
| Mã nguồn | `scripts\remote\remote-access.ps1`, `link_supervisor.py`, `readonly_proxy.py` |
| Bản đang chạy | `%LOCALAPPDATA%\DemandForecastRemote\` gồm `app\`, `runtime\`, `bin\` (cloudflared, bộ cài Tailscale đã xác minh), `config\`, `run\`, `logs\` |
| Tác vụ | Task Scheduler `DemandForecastLink`: chạy khi đăng nhập, không chạy trùng, tự chạy lại nếu lỗi |

Gỡ bỏ: `remote-access.ps1 uninstall`. Thêm `-Purge` để xóa luôn cấu hình và bí mật.
- Bước này tắt Funnel nhưng **không gỡ chương trình Tailscale**.
- Muốn gỡ Tailscale: *Settings → Apps*, cần quyền quản trị.

### 2. Demand Forecasting: khôi phục link xem từ xa (Cloudflare Quick Tunnel)

Nguồn: `reports\demandforecast_remote_access_recovery.md` (worktree MAIN).

**Kết quả: `PASS`.**

Link xem từ xa chỉ đọc đã hoạt động lại tại:

**https://automated-speak-rehabilitation-available.trycloudflare.com**

URL này lấy từ output thật của launcher và từ endpoint `/quicktunnel` của cloudflared, không phải tự đặt ra. Nó đã được kiểm tra qua HTTPS từ máy production lúc 10:39 ngày 19/10/2026 (giờ VN, UTC+07:00).

Kiến trúc giữ nguyên:

```
Internet → Cloudflare Quick Tunnel → readonly proxy 127.0.0.1:8766 → app 127.0.0.1:8765
```

Không khởi động lại hay sửa cấu hình app, proxy, xác thực hoặc logic nghiệp vụ. Chỉ thay tiến trình cloudflared đã chết bằng một tiến trình mới.

### 1. Trạng thái trước (10:18–10:36)

| Thành phần | Bằng chứng | Trạng thái |
|---|---|---|
| App 1.2.6 | pid 13820, nghe `127.0.0.1:8765`, `/api/health` 200 | PASS |
| Readonly proxy | pid 26416 (python 1.2.1, `scripts\remote\readonly_proxy.py`, `--upstream-port 8765 --listen-port 8766`), nghe `127.0.0.1:8766`. `/__remote/health` 200; admin `/api/system/paths` 403; `POST /api/__readonly_probe` 405 | PASS |
| File proxy đang chạy | `readonly_proxy.py` sửa lần cuối 18/10 01:05:16 (commit `dadf77c`), trước lúc proxy khởi động (18/10 10:09:03), nên mã đang chạy chính là file trong repo | PASS |
| cloudflared cũ | pid 31076, `--url http://127.0.0.1:8766`, metrics `127.0.0.1:8767`. `/ready` 503; log ghi 144 lần `Unauthorized: Tunnel not found` từ 09:39:15 | FAIL (tunnel bị Cloudflare xóa) |
| Link cũ `volumes-jean-angels-configurations.trycloudflare.com` | DNS: `DNS name does not exist` | FAIL |
| Cơ chế khởi chạy | `Start-DemandForecast-Remote.bat` gọi `scripts\remote\remote-access.ps1 start`. Trạng thái lưu ở `%LOCALAPPDATA%\DemandForecastRemote\run\tunnel.json` và `proxy.json`. Không có Windows task hay service nào cho app hoặc tunnel, không tự khởi động | — |

Nguyên nhân, theo log cloudflared:
- 09:39:02: máy mất mạng (`wsasendto: ... unreachable network`).
- 09:39:15: khi kết nối lại, Cloudflare báo `Tunnel not found`. Quick Tunnel cũ đã bị xóa ở phía Cloudflare và không thể phục hồi.

### 2. Điều kiện kiểm tra trước khi tạo tunnel mới (10:36:11)

1. App và proxy hoạt động bình thường: health 200 ở cả 8765 và 8766.
2. Proxy vẫn chặn đúng hợp đồng: admin 403 (`REMOTE_FORBIDDEN`), ghi 405 (`REMOTE_READ_ONLY`). Trong mã, `do_POST/PUT/PATCH/DELETE/OPTIONS/TRACE/CONNECT = _refuse`, tức trả 405 và **không bao giờ chuyển tới app**.
3. Không còn tunnel hợp lệ nào: `/ready` 503 và DNS NXDOMAIN.
4. Không cần khởi động lại app: launcher chỉ khởi động lại app hoặc proxy khi chúng không phản hồi. `proxy.json` khớp pid 26416.
5. URL lấy được từ `/quicktunnel` hoặc log của tiến trình mới.

### 3. Thao tác đã làm

Đúng **một** lệnh, dùng cơ chế có sẵn của repo:

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote\remote-access.ps1 start
```

Chạy từ 10:36:32 tới 10:37:47, exit 0. Output của launcher:

```
Ung dung dang chay: http://127.0.0.1:8765 (giu nguyen, khong khoi dong lai).
Proxy chi-doc dang chay: http://127.0.0.1:8766 (pid 26416).
cloudflared: 2026.10.1 (da xac minh: chu ky Valid, SHA-256 4d2490e74082...).
Tunnel dang chay (pid 31076) - kiem tra link cu...
Link cu khong con phan hoi - tao link moi.
Da nhan link https://automated-speak-rehabilitation-available.trycloudflare.com - dang kiem tra qua HTTPS ...
Da kiem tra tu may nay qua HTTPS: dashboard mo duoc, thao tac ghi bi chan.
```

Launcher chỉ dừng cloudflared **của chính nó**, khớp theo đường dẫn exe (pid 31076, tiến trình đã chết), rồi chạy một cloudflared mới trỏ tới proxy 8766. Nó không đụng tới app hay proxy. Bản cloudflared 2026.10.1 đã có chữ ký Cloudflare hợp lệ và SHA-256 khớp với trang phát hành; không tải lại.

### 4. Kiểm tra sau (10:38:58–10:39:08, độc lập với launcher)

| Kiểm tra | Kết quả | Trạng thái |
|---|---|---|
| Số tunnel | Đúng **1** tiến trình cloudflared: pid 18992, khởi động 10:36:39, `--url http://127.0.0.1:8766`. pid 31076 không còn | PASS |
| App và proxy không khởi động lại | app 13820 (khởi động 18/10 19:15:46), proxy 26416 (khởi động 18/10 10:09:03), không đổi | PASS |
| Cổng | 8765 (pid 13820), 8766 (pid 26416), 8767 (pid 18992), đều chỉ nghe trên `127.0.0.1` | PASS |
| cloudflared `/ready` | 200, `readyConnections: 1` | PASS |
| `/quicktunnel` và DNS | Hostname `automated-speak-rehabilitation-available.trycloudflare.com`, DNS phân giải ra IPv6 của Cloudflare | PASS |
| App `/api/health` (localhost) | 200, 1.2.6, 90 ms | PASS |
| Proxy `/api/health` (localhost) | 200, 1.2.6, 84 ms | PASS |
| Link `/api/health` (HTTPS) | 200, 1.2.6, 961 ms | PASS |
| Link `GET /` | 200, có banner chỉ đọc `df-remote-banner` | PASS |
| Link `GET /api/schedules` (đọc được phép) | 200 | PASS |
| Link admin: `/api/system/paths`, `/api/system/backups`, `/api/system/diagnostics`, `/api/audit` | 403 cả 4 (proxy localhost cũng 403) | PASS |
| Link ghi: `POST/PUT/PATCH/DELETE /api/__readonly_probe` | 405 cả 4 (proxy localhost cũng 405). Đường dẫn này không tồn tại, nên kể cả khi bị chuyển tiếp nhầm cũng không ghi được gì. | PASS |
| Không có request đi vòng | `proxy-access.log` ghi đủ các request của link, với mã 200/403/405 khớp. App chỉ nghe trên `127.0.0.1`, và cloudflared chỉ trỏ tới 8766 | PASS |
| Lệnh ghi thử của launcher | `POST /api/training/run` qua link bị proxy trả `405 REMOTE_READ_ONLY` lúc 10:37:47. Job huấn luyện mới nhất vẫn là `JOB-20261019033520-5DE1DA`, do scheduler tạo lúc 10:35:20, trước khi tunnel khởi động; không có job mới | PASS |

Địa chỉ người xem trong log proxy đã được che (`<client>`) trong bằng chứng. Không có token hay secret nào trong báo cáo này.

Bằng chứng nằm trong `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p9\`:
- `remote_start.txt`: output của launcher;
- `verify_remote.ps1`: script kiểm tra độc lập;
- `verify_remote_1.json`: kết quả kiểm tra.

### 5. Giới hạn còn tồn tại

- **Quick Tunnel là tạm thời:** không có cam kết dịch vụ, URL đổi mỗi lần tạo lại. Nếu máy mất mạng lâu, Cloudflare có thể xóa tunnel như lần 09:39. Đây **không** phải giải pháp production lâu dài.
- **Không tự khởi động:** tunnel và proxy là tiến trình thường. Không có task hay service nào; khởi động lại máy hoặc đăng xuất thì link mất. Muốn có link lại phải chạy `Start-DemandForecast-Remote.bat`, và sẽ được URL mới.
- Proxy vẫn chạy bằng python của bản 1.2.1 từ file repo `scripts\remote\readonly_proxy.py`. Nhãn của proxy là "1.2.5". Proxy hoạt động đúng; tôi giữ nguyên.
- Từ 09:39 tới 10:37, link không dùng được. Ai đang giữ URL cũ cần nhận URL mới.

### 6. Cần phê duyệt

1. Gửi URL mới cho người cần xem. Chỉ gửi cho người cần, vì ai có link đều xem được.
2. Nếu cần URL cố định và tự khởi động: dùng **Named Tunnel**. Việc này cần tài khoản Cloudflare, một domain, credential của tunnel, và (tùy chọn) một service hoặc task tự khởi động. Tôi chưa cấu hình gì, vì cần quyền và quyết định của anh/chị.
3. Nếu muốn link tự hồi phục sau khi mất mạng mà vẫn dùng Quick Tunnel: có thể thêm một task giám sát chạy lại launcher khi `/ready` khác 200. URL vẫn sẽ đổi mỗi lần tạo lại. Việc này cần phê duyệt riêng, vì là cơ chế tự khởi động mới.

### 3. Link HTTPS cố định cho Demand Forecasting: audit và triển khai (24–25/10/2026)

Nguồn: `reports\remote-link-20261024\REPORT.md` (worktree MAIN).

### Kết quả

- **Theo yêu cầu: `PARTIALLY_IMPLEMENTED_NEEDS_USER_AUTH`.**
  - Phần chạy trên máy đã xong và đã kiểm thử thật: proxy chỉ đọc có đăng nhập, bộ giám sát tự phục hồi, tự khởi động
    theo phiên Windows, Setup một lần.
  - Còn thiếu đúng một thứ: **tên miền trên Cloudflare** (đăng nhập của chủ máy) hoặc **token tunnel** do quản trị
    Cloudflare cấp.
- **Theo AGENTS.md: `READY_FOR_EXTERNAL_SETUP`.**
- **Chưa có link chính thức.** Các link `*.trycloudflare.com` trong báo cáo này chỉ để chẩn đoán và đều đã tắt.

### Thông tin sử dụng

| Mục | Giá trị |
|---|---|
| URL HTTPS chính thức | **Chưa có.** Setup sẽ tạo URL dạng `https://<tên con>.<tên miền của bạn>`, ví dụ `https://forecast.tencongty.com` |
| Gửi sếp ngay được không | **Chưa** |
| Bản production sẽ được phục vụ | 1.2.13 (commit `1b00c42`, `BUILD-INFO.json` của bản cài). Tiến trình PID 11964 chạy `…\Programs\DemandForecast\1.2.13\python\python.exe`, cổng 127.0.0.1:8765, nguồn BIGQUERY |
| Tự khởi động | Tác vụ `DemandForecastLink` chạy khi đăng nhập Windows (chống trùng, tự chạy lại nếu lỗi). Bộ giám sát theo dõi app: app chạy (mở bằng launcher thường, autostart hay deploy) thì link bật; app tắt thì link tắt sau 60 giây |
| Tự phục hồi | cloudflared chạy lại với backoff 5 giây … 5 phút, tối đa 12 lần/giờ, sau đó nghỉ 15 phút. Mất kết nối Cloudflare hơn 180 giây thì khởi động lại. Kiểm tra URL công khai mỗi 5 phút; lỗi 3 lần thì khởi động lại tunnel (tối đa 1 lần / 30 phút). Supervisor crash thì wrapper chạy lại; job object diệt cloudflared cũ nên không có tunnel trùng |
| Cập nhật theo release | Link trỏ vào cổng của app và đối chiếu `current.txt` mỗi phút. Sau `deploy-upgrade.ps1` hoặc `rollback-version.ps1`, bản mới chạy là link phục vụ bản mới, cùng URL. Link không bao giờ phục vụ server phát triển, bản khác `current.txt` hay nguồn DEMO |
| Chi phí | 0 đồng nếu đã có tên miền trên Cloudflare (Tunnel miễn phí). Nếu chưa có thì cần mua tên miền (phí hằng năm, cần bạn duyệt) hoặc xin IT một tên con. Không đăng ký dịch vụ trả phí nào |

### 1. Audit ban đầu

- **Project:**
  - thư mục `D:\Buymed\Lightgbm AI`;
  - Git `main`, commit cuối `e682cf3`.
- **Production đang chạy:**
  - phiên bản 1.2.13;
  - `current.txt` = 1.2.13;
  - PID 11964 `app.cli serve --port 8765`, chỉ nghe 127.0.0.1;
  - nguồn dữ liệu BIGQUERY;
  - lịch D-1 08:00, EOD/close bật.
- **Launcher thực tế:**
  - Start Menu *Demand Forecasting.lnk* → `…\1.2.13\Start.bat` → `scripts\start.ps1`;
  - `install.ps1` và `rollback-version.ps1` ghi lại shortcut này ở mỗi lần cài hoặc rollback;
  - không có tác vụ autostart của app.
- **Chia sẻ đã có:**
  - Quick Tunnel 1.2.1 (`Start-DemandForecast-Remote.bat`);
  - link ngẫu nhiên, **không đăng nhập**, phải bấm tay, mất khi khởi động lại;
  - link cuối `…trycloudflare.com` (19/10) đã chết: không còn tiến trình cloudflared hay proxy; log cloudflared dừng
    24/10 01:35;
  - không có tên miền, chứng chỉ Cloudflare (`.cloudflared`), Tailscale, ngrok, VPN hay reverse proxy.
- **Xác thực của app: không có.**
  - Chỉ có Host allow-list và header CSRF `X-DF-Client`.
  - Đưa thẳng cổng 8765 ra Internet là không chấp nhận được, nên chọn proxy chỉ đọc có đăng nhập.
- **Quyền Windows:** tài khoản không phải admin, nên loại phương án cần cài MSI như Tailscale. cloudflared chạy được ở
  quyền người dùng.
- **Rủi ro phát hiện khi thiết kế:** `install.ps1` từ chối cài khi có `python.exe` chạy từ thư mục đích.
  - Nếu link dùng Python của bản cài, nó có thể chặn cài lại hoặc rollback.
  - Cách xử lý: link dùng **bản chép Python riêng**, chỉ thư viện chuẩn, trong `%LOCALAPPDATA%\DemandForecastRemote\runtime`.
- **Audit API:**
  - không có thay đổi nào ở `backend/app/api`, `main.py`, `security.py` từ release 1.2.11, lần audit allow-list gần
    nhất;
  - allow-list chỉ thêm `/api/schedules/eod|close`, là view GET của 1.2.6.

### 2. Kiến trúc

```
Sếp (trình duyệt) --HTTPS--> Cloudflare (tên miền cố định, chứng chỉ TLS)
      --> cloudflared (máy này, chỉ kết nối RA ngoài)
      --> proxy 127.0.0.1:8766 (đăng nhập + chỉ GET trong allow-list + xóa đường dẫn)
      --> app 127.0.0.1:8765 (production 1.2.13, không sửa gì)
Tác vụ DemandForecastLink (khi đăng nhập) -> remote-access.ps1 run -> link_supervisor.py
  (theo dõi app, bật/tắt proxy + cloudflared, backoff, kiểm tra URL công khai, ghi run\link-status.json)
```

### 3. Kiểm thử

Loại bằng chứng:
- **unit:** kiểm thử đơn vị;
- **local-fake:** tích hợp cục bộ với app giả;
- **isolated:** bản cài thật trên bản sao DB, cổng riêng;
- **real-ext:** đi qua Cloudflare thật, bằng Quick Tunnel tạm chỉ để chẩn đoán, gọi từ chính máy này;
- **prod:** máy thật, chỉ đọc.

| # | Kiểm tra | Kết quả | Loại | Bằng chứng |
|---|---|---|---|---|
| 1 | Local health của app | PASS: 1.2.13, PID 11964 | prod | `GET /api/health` |
| 2 | HTTPS công khai tới `/__remote/health`, đúng proxy của máy này, login bật | PASS | real-ext | `evidence\isolated-selftest-quick-29-pass.json` |
| 3 | Chứng chỉ TLS hợp lệ | PASS: Google Trust Services, TLSv1.3, tới 03/01/2027 (hostname trycloudflare.com) | real-ext | như trên |
| 4 | URL trả đúng bản production | PASS: version 1.2.13 = `current.txt`; tiến trình là runtime đã cài; nguồn BIGQUERY | real-ext + prod | như trên |
| 5 | Không trỏ vào DEMO hay server phát triển | PASS: link chỉ bật khi đạt kiểm tra production. Unit test: server phát triển (tiến trình test) và sai phiên bản đều bị từ chối | unit + real-ext | `test_production_identity_*` |
| 6 | Chưa đăng nhập | PASS: trang → 302 tới trang đăng nhập; API → 401; POST → 405; sai mật khẩu → 401, không có cookie | real-ext | selftest |
| 7 | Tài khoản xem không ghi được, không vào trang quản trị | PASS: 4 thao tác ghi → 405, không tới app; 4 trang quản trị → 403; không lộ đường dẫn; đăng xuất xóa cookie | real-ext | selftest |
| 8 | Dừng riêng cloudflared → tự kết nối lại | PASS: ONLINE lại sau 24 giây | real-ext | selftest restart test |
| 9 | Hostname **cố định** không đổi sau reconnect | **CHƯA XÁC MINH**: cần tunnel có tên. Setup tự chạy kiểm tra này. Quick Tunnel đổi tên như dự kiến | — | — |
| 10 | Mở lại app bằng launcher thường → link tự bật | PASS: `stop.ps1` → link tắt sau 60 giây (cloudflared + proxy dừng); `start.ps1` → ONLINE sau 20 giây | isolated (launcher 1.2.13 thật, bản sao DB, cổng 8775) | `evidence\isolated-link-supervisor.log` |
| 11 | Không trùng tiến trình, tunnel hay tác vụ | PASS: supervisor thứ hai thoát mã 3; `Start-ScheduledTask` lần 2 vẫn chỉ 1 wrapper + 1 supervisor; chỉ 1 cloudflared | isolated + prod | |
| 12 | Supervisor bị kill | PASS: cloudflared chết theo job object; wrapper chạy lại, ONLINE sau 21 giây | isolated + real-ext | `evidence\isolated-link-task.log` |
| 13 | Tạm dừng / bật lại | PASS: PAUSED (cloudflared + proxy tắt) → ONLINE | isolated + real-ext | |
| 14 | Log không lộ bí mật | PASS: selftest quét log (mật khẩu, cookie, token); quét thư mục `evidence` cho 0 kết quả | real-ext | |
| 15 | Launcher, release, rollback vẫn hoạt động | PASS phần kiểm được: shortcut app, file cài, `storage.json`, DB, lịch đều không đổi; ngoài app không có `python.exe` nào chạy từ thư mục cài. **Không chạy** deploy hay rollback thật (không được yêu cầu, sẽ dừng production) | prod | |
| 16 | Tác vụ production | PASS: `DemandForecastLink` đang chạy, `IgnoreNew`, RestartCount 999 / 1 phút, không giới hạn thời gian; trạng thái `NOT_CONFIGURED` (không mở gì ra Internet) | prod | `evidence\production-*` |
| 17 | Unit và tích hợp cục bộ | PASS 67/67: `test_remote_link.py` 23 + `test_v121_remote_proxy.py` 44 | unit + local-fake | pytest |
| 18 | Truy cập từ một mạng bên ngoài khác | **CHƯA XÁC MINH**: mọi kiểm tra công khai gọi từ chính máy này (đi qua Internet và Cloudflare thật, nhưng cùng mạng nguồn) | — | — |
| 19 | Mọi cờ CLI mà Setup dùng | PASS: có trong cloudflared 2026.10.1 (`--origincert`, `list --name --output`, `create --credentials-file`, `route dns`, `token --cred-file`, `run --token`/`TUNNEL_TOKEN`) | prod (help) | |
| 20 | Đăng nhập Cloudflare, tạo tunnel và DNS thật | **CHƯA CHẠY**: cần tài khoản hoặc token của bạn | — | — |

App production **không** bị khởi động lại khi kiểm thử. Lý do:
- lúc đó gần các lịch EOD 23:55 / close 23:59 đang bật;
- AGENTS.md cấm dừng app ngoài deploy/rollback;
- phép thử tương đương đã chạy trên instance cô lập với đúng launcher đã cài.

### 4. Thay đổi

**Repository** (chưa commit, chưa push):
- `scripts/remote/readonly_proxy.py`: sửa, thêm đăng nhập;
- `scripts/remote/link_supervisor.py`: mới;
- `scripts/remote/remote-access.ps1`: viết lại;
- `Setup-DemandForecast-Link.bat`: mới;
- `Start-DemandForecast-Remote.bat`, `Stop-DemandForecast-Remote.bat`: sửa;
- `REMOTE_ACCESS_GUIDE.md`: viết lại;
- `CHANGELOG.md`: thêm mục *Unreleased*;
- `backend/tests/test_remote_link.py`: mới;
- báo cáo này và `evidence\`.

**Trên máy:**
- `%LOCALAPPDATA%\DemandForecastRemote\`: mới `app\` (kèm `MANIFEST.txt`), `runtime\`, `run\link-status.json`,
  `logs\link-*.log`. `bin\cloudflared.exe` 2026.10.1 (chữ ký Cloudflare hợp lệ) **không đổi**; log và file trạng thái cũ
  giữ nguyên.
- Task Scheduler `DemandForecastLink`: mới.
- Start Menu → thư mục *Demand Forecasting Link*: 4 shortcut.

**Không đổi:** bản cài app, `current.txt`, `storage.json` (SHA-256 `8D79DBDD…`, ghi lần cuối 14/10), database, model,
forecast, lịch D-1 / D-0 / training / EOD / close, firewall, shortcut *Demand Forecasting.lnk*.

### 5. Sao lưu và rollback

- **Trước khi sửa:** `checkpoints\remote-link-before-20261024.zip` (+ `.sha256`). Các file đó cũng sạch trong Git.
- **Gỡ link khỏi máy:** `powershell -ExecutionPolicy Bypass -File scripts\remote\remote-access.ps1 uninstall`. Thêm
  `-Purge` để xóa luôn chứng chỉ, file xác thực tunnel và mật khẩu.
- **Trả mã nguồn về bản cũ:** `git checkout -- scripts/remote Start-DemandForecast-Remote.bat Stop-DemandForecast-Remote.bat REMOTE_ACCESS_GUIDE.md`,
  hoặc giải nén checkpoint.

### 6. Cách mở ứng dụng

Như cũ: Start Menu → *Demand Forecasting*, hoặc `Start.bat` của bản cài. Không có thao tác mới. Sau khi Setup xong,
link tự bật theo app.

### 7. Giới hạn còn lại

- Máy phải bật, có Internet, không ngủ (hiện *Sleep: Never* khi cắm điện), và bạn phải đăng nhập Windows.
- Tác vụ chạy theo phiên người dùng, không phải dịch vụ hệ thống.
- Đăng nhập dùng một tài khoản xem chung. Muốn đăng nhập theo email từng người thì bật thêm Cloudflare Access (tùy chọn,
  chưa cấu hình).
- Phần chưa xác minh: mục 9, 18 và 20 ở bảng trên.
- `deploy-upgrade.ps1` và `rollback-version.ps1` chưa chạy thử với link. Tính tương thích suy ra từ thiết kế:
  - link chỉ dựa vào cổng app và `current.txt`;
  - link không khóa thư mục cài.

### 8. Việc duy nhất còn cần bạn

Bấm đúp **`D:\Buymed\Lightgbm AI\Setup-DemandForecast-Link.bat`** và chọn một trong hai:

- **`1`, nếu bạn có tài khoản Cloudflare với một tên miền đang hoạt động:**
  1. nhập tên link, ví dụ `forecast.<tên miền>`;
  2. trên trang Cloudflare vừa mở, đăng nhập, chọn tên miền, bấm **Authorize**.
- **`2`, nếu IT hoặc quản trị Cloudflare cấp tunnel:**
  1. nhờ họ tạo tunnel với *Public hostname* = tên link và *Service* `HTTP 127.0.0.1:8766`;
  2. dán token họ gửi.

Setup tự làm phần còn lại và in **PASS/FAIL** của self-test qua Internet (gồm thử ngắt tunnel và xác nhận cùng tên
miền). Cuối cùng nó in link, tên đăng nhập và mật khẩu, đồng thời chép vào clipboard. Kết quả được lưu ở
`%LOCALAPPDATA%\DemandForecastRemote\logs\selftest-*.json`.

Nếu chưa có tên miền thì cần quyết định mua một tên miền (phí hằng năm) hoặc xin IT. Không bước nào ở đây tự phát sinh
chi phí.

### 4. Link công khai qua Tailscale Funnel: triển khai và kiểm thử (25/10/2026)

Nguồn: `reports\remote-link-20261024\REPORT-TAILSCALE-20261025.md` (worktree MAIN).

### Kết quả: `READY`

| Mục | Giá trị |
|---|---|
| URL HTTPS chính thức | **https://log-pc.tail12f031.ts.net** |
| Phiên bản production | 1.2.13 (commit `1b00c42`). Tiến trình PID 11964 chạy `…\Programs\DemandForecast\1.2.13\python\python.exe`, nguồn BIGQUERY. Forecast đang hiển thị `FCR-20261024163842-4EEFD8`, model `MV-20261024-163642-EA7D` |
| Quyền người xem | **Công khai, chỉ đọc**: không đăng nhập; mọi thao tác ghi bị chặn (405); trang quản trị và tác vụ nặng bị chặn (403); tên BigQuery và đường dẫn trên máy bị ẩn |
| Self-test qua Internet | **34/34 PASS**, hai lần: lúc Setup chạy và lần cuối 01:37 |
| Chi phí | 0 đồng (Tailscale gói Personal miễn phí) |

### 1. Diễn biến

1. **25/10 01:1x – cổng an toàn đạt.** Chủ máy xác nhận *Green Christmas Tree* là chương trình tự cài. Xác nhận được ghi
   trong `config\security-ack.json`. Mục tự khởi động **giữ nguyên**: không xóa, không tắt. Defender bật và không có
   phát hiện nào từ 24/10.
2. **Cài Tailscale 1.104.2.** Dùng bộ cài chính thức đã xác minh (SHA-256 khớp `pkgs.tailscale.com`, chữ ký
   *Tailscale Inc.*). Chủ máy nhập quyền quản trị ở hộp UAC.
3. **Đăng nhập Tailscale** trên trang chính thức (chủ máy thao tác).
4. **Sửa một vấn đề phát sinh.** Sau khi `tailscale up` kết thúc, Tailscale về `NoState`: trên Windows, nếu không có ứng
   dụng khay thì Tailscale không giữ kết nối. Đã bật **chế độ unattended** (`tailscale up --unattended`, dùng lại
   phiên đã đăng nhập). Tailscale giờ tự kết nối như một dịch vụ, kể cả sau khi khởi động lại máy.
5. **Cho phép HTTPS / Funnel** trên trang Tailscale (chủ máy thao tác). Supervisor tự thử lại và link ONLINE lúc 01:30:13.
6. **Self-test 34/34 PASS.** Sau đó cập nhật một sửa nhỏ về câu chữ log và cài lại; chạy thêm các phép thử ở mục 2.

### 2. Kiểm thử trên link production

Đường công khai được thử đúng như người xem dùng:
- phân giải `log-pc.tail12f031.ts.net` bằng **DNS công cộng** (1.1.1.1), ra `103.84.155.217`, là relay Funnel của
  Tailscale trên Internet;
- kết nối HTTPS tới địa chỉ đó, có kiểm chứng chỉ.

Không dùng đường tắt MagicDNS nội bộ của máy.

| Kiểm tra | Kết quả |
|---|---|
| Local health | PASS: 1.2.13 |
| HTTPS Funnel từ hostname công khai | PASS: HTTP 200, đúng proxy của máy này, `access: public-read-only` |
| Chứng chỉ TLS | PASS: Let's Encrypt, hết hạn 22/01/2027 (Tailscale tự gia hạn) |
| Không cần cài Tailscale hay đăng nhập để xem | PASS: giao diện và dữ liệu mở trực tiếp. Ảnh `evidence\funnel-public-dashboard.png`: Edge headless qua URL chính thức |
| Đúng bản production | PASS: version 1.2.13 = `current.txt`; tiến trình là runtime đã cài; nguồn BIGQUERY (không DEMO) |
| Thao tác ghi bị chặn | PASS: training, lưu cấu hình, tắt app, xóa lô nhập, backfill, chạy lịch đều trả 405 và app không nhận yêu cầu |
| Quản trị và tác vụ nặng bị chặn | PASS: 11 endpoint trả 403 (đường dẫn hệ thống, sao lưu, audit, danh tính BigQuery, SQL nguồn, job, lịch, đồng bộ, lô nhập, giải thích SHAP) |
| Không lộ dữ liệu nhạy cảm | PASS: 5 tên BigQuery không xuất hiện trên 7 endpoint; không có đường dẫn trên máy; settings không còn phần `bigquery` / `sql_sources` / `import` |
| Tắt Funnel đột ngột → tự phục hồi | PASS: bật lại sau 28 giây; hostname không đổi; public check đạt lại |
| Supervisor dừng hẳn (cài lại) | PASS: Funnel **tắt** khi dừng; bật lại sau 6 giây; ONLINE sau 16 giây; cùng URL |
| Kill supervisor (crash) | PASS: wrapper chạy lại; ONLINE sau 15 giây; cùng URL; HTTP 200 |
| Tạm dừng / bật lại | PASS. Tạm dừng: cấu hình Funnel rỗng, proxy tắt, URL công khai **không truy cập được**. Bật lại: ONLINE, cùng URL, HTTP 200. Đây cũng là nhánh supervisor dùng khi app tắt |
| Không trùng | PASS: chạy task thêm lần nữa vẫn chỉ 1 wrapper + 1 supervisor; 0 cloudflared; 1 task `DemandForecastLink` |
| Log không lộ bí mật | PASS: self-test quét log; thư mục bằng chứng không chứa cookie, token hay link đăng nhập một lần |
| Unit và tích hợp cục bộ | PASS 90/90 |

**Không đổi:**
- database, model, forecast;
- lịch D-1 / D-0 / training / EOD / close;
- quy trình release, `storage.json` (SHA-256 `8D79DBDD…`, ghi lần cuối 14/10), shortcut app;
- mục *Green Christmas Tree*.

Không commit, không push, không mua dịch vụ nào.

**Chưa chạy thật** (suy ra từ thiết kế và các phép thử tương đương):
- **Đóng/mở app production bằng launcher:** không làm, để không gián đoạn production. Nhánh tắt/bật Funnel đã thử qua
  tạm dừng/bật lại. Vòng đời theo launcher thật đã thử ngày 24/10 trên bản cô lập.
- **Deploy hoặc rollback thật.** URL gắn với tên máy Tailscale, không gắn với phiên bản app. Supervisor luôn đối chiếu
  `current.txt` và dùng Python riêng (không khóa thư mục cài).
- **Truy cập từ một mạng khác:** dùng phép thử đường công khai qua relay Funnel như mô tả ở trên.

### 3. Thay đổi so với báo cáo trước

**Trên máy:**
- Tailscale 1.104.2 đã cài (dịch vụ `Tailscale`, Automatic), unattended.
- Node `log-pc` trong tailnet `tail12f031`, HTTPS + Funnel được cho phép.
- `%LOCALAPPDATA%\DemandForecastRemote\config\link.json`: `mode funnel`, `access public`.
- `config\security-ack.json`: mới.

**Mã nguồn:**
- Cổng an toàn ghi nhận xác nhận của chủ máy.
- Setup tự chờ sau bước cho phép Funnel (không cần Enter).
- Bộ cài chạy với `TS_NOLAUNCH`.
- Log ghi "Funnel attempt" thay cho "cloudflared restart".

**Gỡ hoặc tắt:**
- Tạm dừng: Start Menu → *Demand Forecasting Link* → *tam dung*.
- Gỡ link: `remote-access.ps1 uninstall`.
- Gỡ Tailscale: *Settings → Apps*, cần quyền quản trị.

### 4. Giới hạn uptime

- Link chỉ chạy khi máy **bật, có Internet, không ngủ**, bạn **đã đăng nhập Windows** (supervisor chạy theo phiên) và
  **ứng dụng đang chạy**. App tắt quá 60 giây thì Funnel tắt.
- Phụ thuộc dịch vụ Tailscale. Gói miễn phí có giới hạn băng thông cho Funnel; Tailscale không công bố con số.
- **Khóa máy (node key) của Tailscale hết hạn sau 180 ngày** theo mặc định. Khi đó link tắt cho tới khi đăng nhập lại.
  Có thể tắt hết hạn: trang quản trị Tailscale → *Machines* → `log-pc` → *Disable key expiry*. Bước này chưa làm, cần
  chủ tài khoản.
- **Chế độ công khai:** ai có link đều xem được dữ liệu dự báo, và link có thể bị chuyển tiếp. Muốn ngừng thì tạm dừng.
  Muốn đổi URL thì đổi tên máy trong Tailscale rồi chạy lại Setup.
