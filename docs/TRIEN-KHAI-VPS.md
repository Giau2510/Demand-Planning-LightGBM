# Triển khai lên VPS (chuẩn bị 16/10/2026 — CHƯA triển khai, CHƯA kiểm thử trên Linux)

Chưa có thông tin VPS (mục 9). Bộ script `scripts/vps/` sẵn sàng dùng nhưng **chưa từng chạy trên Linux**: máy phát
triển không có WSL/Docker. Lần đầu phải làm đúng thứ tự mục 4 và dừng ở bất kỳ bước nào báo lỗi.

## 1. Ứng dụng thực sự gồm những gì

- **Một tiến trình** Python: FastAPI + uvicorn (1 worker) phục vụ cả API lẫn giao diện đã build (`web/`).
- **Scheduler chạy bên trong tiến trình đó** (D-1, D-0, huấn luyện 07:00): chỉ được có **một** instance trên một bộ dữ
  liệu. Không chạy 2 service, 2 worker hay 2 bản app trỏ cùng dữ liệu.
- SQLite (WAL) + file model trên đĩa; backup trực tuyến qua API của app (`POST /api/system/backups`).
- Migration DB chạy khi app khởi động (chỉ thêm, có thứ tự).
- BigQuery chỉ đọc, qua thông tin xác thực Google của máy chạy app.
- **Không có đăng nhập người dùng**: chỉ có chặn Host + CSRF. Trên VPS bắt buộc đặt sau reverse proxy có TLS **và**
  xác thực (hoặc chỉ truy cập qua VPN / SSH tunnel). App luôn nghe `127.0.0.1`.

## 2. Phương án đã chọn: Linux + systemd + venv từ lockfile (không Docker)

- Một service systemd, code mỗi phiên bản trong `/opt/demandforecast/releases/<release>/` (venv riêng, cài từ
  `backend/requirements.lock.txt`, chỉ wheel nhị phân), symlink `current` / `previous` để chuyển và rollback nhanh.
- Dữ liệu ngoài code: `/var/lib/demandforecast/{data,logs,backups,reports}`; cấu hình `/etc/demandforecast/app.env`.
- Không Docker: một tiến trình + một file SQLite không cần orchestration; thêm một lớp image/volume không làm việc vận
  hành đơn giản hơn, và không thể kiểm thử Docker trên máy phát triển này.
- Đã kiểm tra (16/10/2026, `pip --dry-run`, không cài): **cả 52 gói khóa phiên bản có wheel Linux x86_64 cho
  CPython 3.14**; yêu cầu cao nhất manylinux 2.28 ⇒ **glibc ≥ 2.28** (Ubuntu 20.04+, Debian 10+). LightGBM cần
  `libgomp1`.
- Phương án thay thế khi VPS chạy **Windows Server**: dùng nguyên gói `...-win64-portable.zip` và quy trình đã kiểm thử
  trên máy này (`install.ps1`, `deploy-upgrade.ps1`, `rollback-version.ps1`, `docs/VAN-HANH.md`); vẫn cần reverse proxy
  có xác thực nếu truy cập từ xa.

| Trên VPS | Đường dẫn |
|---|---|
| Code các release (chỉ đọc với service) | `/opt/demandforecast/releases/<DemandForecast-version-commit-linux-src>/` |
| Release đang chạy / trước đó | `/opt/demandforecast/current`, `/opt/demandforecast/previous` |
| Công cụ | `/opt/demandforecast/bin/deploy.sh`, `rollback.sh` |
| Dữ liệu, log, backup, báo cáo | `/var/lib/demandforecast/...` (chủ sở hữu `demandforecast`) |
| Cấu hình + file khóa Google | `/etc/demandforecast/app.env`, `/etc/demandforecast/bq-reader.json` (640, root:demandforecast) |
| Service | `demandforecast.service` (`journalctl -u demandforecast`) |

## 3. Python 3.14 trên VPS

Lockfile được tạo cho CPython 3.14. Trình thông dịch phải đọc được bởi user `demandforecast` (không nằm trong `/root`):
- Ubuntu: `apt install python3.14 python3.14-venv` (PPA deadsnakes nếu bản phân phối chưa có), hoặc
- `uv`: `UV_PYTHON_INSTALL_DIR=/opt/python uv python install 3.14.7`, rồi `export PYTHON_BIN=$(UV_PYTHON_INSTALL_DIR=/opt/python uv python find 3.14.7)`
  trước khi chạy `deploy.sh`.

## 4. Lần đầu

Trên máy này (commit đã được xem xét, QA đạt):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\release.ps1                  # QA + gói Windows (tùy chọn)
powershell -ExecutionPolicy Bypass -File scripts\vps\build-vps-artifact.ps1   # dist\DemandForecast-<v>-<commit7>-linux-src.tar.gz + .sha256
scp dist\DemandForecast-<v>-<commit7>-linux-src.tar.gz* <user>@<vps>:/tmp/
```
Trên VPS:
```bash
sha256sum -c /tmp/DemandForecast-<v>-<commit7>-linux-src.tar.gz.sha256
tar -xzf /tmp/DemandForecast-<v>-<commit7>-linux-src.tar.gz -C /tmp
sudo bash /tmp/DemandForecast-<v>-<commit7>-linux-src/scripts/vps/install-server.sh
sudo nano /etc/demandforecast/app.env          # DF_ALLOWED_HOSTS = tên miền; đường dẫn file khóa Google
sudo install -m 640 -o root -g demandforecast bq-reader.json /etc/demandforecast/bq-reader.json
sudo bash /opt/demandforecast/bin/deploy.sh /tmp/DemandForecast-<v>-<commit7>-linux-src.tar.gz <sha256>
```
Reverse proxy: `scripts/vps/Caddyfile.example` (TLS tự động + `basic_auth`), hoặc nginx tương đương với
`auth_basic` và `proxy_pass http://127.0.0.1:8765`. Tường lửa: chỉ mở 22, 80, 443; **không** mở 8765.

Sau khi chạy: mở trang qua tên miền ⇒ cấu hình nguồn dữ liệu, BigQuery và lịch trong giao diện như trên máy này. Lịch
trên VPS mặc định theo dữ liệu của VPS (DB mới thì các lịch đều TẮT cho tới khi bật).

## 5. Các lần triển khai sau

```bash
sudo bash /opt/demandforecast/bin/deploy.sh /tmp/<artifact>.tar.gz <sha256>
```
`deploy.sh` theo thứ tự:
1. kiểm SHA-256;
2. giải nén (không ghi đè release đã có);
3. tạo venv từ lockfile và tự kiểm tra runtime;
4. **chặn nếu schema DB mới hơn release**;
5. backup trực tuyến qua app đang chạy;
6. chuyển `current` và khởi động lại;
7. kiểm tra `/api/health` đúng phiên bản. Hỏng thì tự quay về release trước;
8. chỉ sau đó mới dọn release cũ: giữ 3 bản, luôn giữ bản đang chạy và bản trước.

Không chạy trong giờ có lịch (D-0 08:00–18:00 mỗi 2 giờ, D-1 từ 01:00, huấn luyện 07:00) hoặc khi đang có job.

## 6. Rollback

```bash
sudo bash /opt/demandforecast/bin/rollback.sh                 # về release trước
sudo bash /opt/demandforecast/bin/rollback.sh <release-name>  # về một release cụ thể còn trong /opt/demandforecast/releases
```
Chỉ đổi code; bị từ chối khi schema DB mới hơn release đích. Khi đó khôi phục backup trước (app phải dừng):
```bash
sudo systemctl stop demandforecast
cd /opt/demandforecast/current/backend
sudo -u demandforecast bash -c 'set -a; . /etc/demandforecast/app.env; set +a; ../.venv/bin/python -m app.cli restore /var/lib/demandforecast/backups/<backup>.zip'
sudo bash /opt/demandforecast/bin/rollback.sh <release-name>
```

## 7. Vận hành

- Sức khỏe: `curl -s http://127.0.0.1:8765/api/health`; log: `journalctl -u demandforecast` và `/var/lib/demandforecast/logs`.
- Backup: nút trong giao diện hoặc `curl -X POST -H "X-DF-Client: web" http://127.0.0.1:8765/api/system/backups`;
  sao chép backup ra ngoài VPS định kỳ; giữ theo `docs/PHAT-TRIEN-QA-PHAT-HANH.md` mục 7.
- Kiểm tra dữ liệu: `sudo -u demandforecast bash -c 'set -a; . /etc/demandforecast/app.env; set +a; cd /opt/demandforecast/current/backend; ../.venv/bin/python -m app.cli data-check'`.

## 8. Một bộ dữ liệu, một scheduler

- Khi VPS là môi trường production, **tắt các lịch trên máy này** (hoặc dừng app trên máy này) để cùng một job không
  chạy hai nơi (chi phí BigQuery gấp đôi, hai bộ kết quả khác nhau). Dev/QA trên máy này luôn chạy với
  `DF_DISABLE_SCHEDULER=1` và dữ liệu cô lập.
- Chuyển dữ liệu từ máy này sang VPS (nếu muốn giữ lịch sử, model, dự báo): tạo backup trên máy này, chép file `.zip`
  vào `/var/lib/demandforecast/backups/`, dừng service, `app.cli restore` (mục 6), khởi động. Chỉ làm khi người dùng
  quyết định; không tự động.

## 9. Thông tin còn thiếu để triển khai

| Cần | Vì sao |
|---|---|
| Hệ điều hành + phiên bản, kiến trúc (x86_64?), glibc ≥ 2.28 | chọn Linux/systemd hay Windows Server; wheel nhị phân |
| CPU / RAM / đĩa | huấn luyện LightGBM + một lần D-1 nạp ≈ 1,35 triệu dòng vào bộ nhớ; nên ≥ 4 GB RAM, ≥ 20 GB đĩa |
| Quyền truy cập: SSH (user có sudo, khóa) | chạy `install-server.sh`, `deploy.sh` |
| Tên miền + DNS, chứng chỉ TLS (Let's Encrypt tự động hay chứng chỉ sẵn có) | reverse proxy |
| Cách người dùng đăng nhập (basic auth, SSO/OAuth proxy, VPN) | app không có đăng nhập riêng |
| Thông tin xác thực Google cho VPS: service account chỉ đọc (BigQuery Data Viewer trên dataset + Job User trên project) | ADC trên Linux; quản trị Google Cloud cấp, không dùng tài khoản cá nhân |
| VPS dùng DB mới hay chuyển dữ liệu từ máy này | mục 8 |
| Máy nào chạy lịch sau khi chuyển | mục 8 |
| Nơi lưu backup ngoài VPS | khôi phục khi mất VPS |

## 10. Giới hạn đã biết trên Linux (chưa kiểm thử)

- Đăng nhập Google trong ứng dụng ("Sign in with Google") lưu token bằng Windows Credential Manager; trên Linux token
  chỉ nằm trong bộ nhớ và mất khi khởi động lại ⇒ trên VPS dùng ADC / file service account (`app.env`).
- Các script `.ps1` và lệnh `app.cli stop` chỉ dành cho Windows; trên Linux dùng systemd và `scripts/vps/*.sh`.
- Mọi bước trong tài liệu này phải được xác minh trên VPS thật ở lần đầu (health check, backup, rollback, một lần chạy
  thử D-0 DEMO) trước khi bật BigQuery production.
