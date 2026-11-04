# Resume checkpoint - release 1.2.11 (21/10/2026, ~18:30)

## Trạng thái

### Production

- Phiên bản **1.2.11**, schema 9, `http://127.0.0.1:8765`, PID 7316, từ 18:08.
- Thư mục cài đặt `%LOCALAPPDATA%\Programs\DemandForecast\1.2.11`, `current.txt` 1.2.11. Thư mục 1.2.10 giữ nguyên để rollback.
- `storage.json` SHA-256 `8D79DBDD…E047`, không đổi.

### Dữ liệu BIGQUERY

- 01/01-20/10 = nguồn snapshot 21/10 07:10:38: 1.360.913 khóa / 42.088.223 đơn vị.
- 293 ngày đã chốt. D-1 1.2.11 `JOB-20261021111824-17023B` không có thay đổi.

### Quy tắc mới

- WAIT_TO_CONFIRM được miễn kiểm tra trùng.
- `item_code` không được so khi kiểm tra trùng.
- Proxy chặn `GET /api/data-quality` và HEAD `/api`.

### Huấn luyện BIGQUERY

- Bị chặn `OPEN_HOURS_INVALID` do 6 khóa `MULTI_ITEM`; quy tắc giờ SKU × FC chưa có.
- Model `TRN-20261020054540-D7EEF6` và forecast `FCR-20261020082402-A42C91` không đổi.

### Lịch (không đổi)

| Luồng | Giờ |
|---|---|
| D-1 | 06:00 / dự phòng 06:30 |
| D-0 | 08-18 h, mỗi 2 h |
| Huấn luyện | 07:00 (SKIP khi lỡ) |
| EOD | 23:55 |
| Close | 23:59 |

### Link công khai

- Chưa có URL cố định.
- Quick Tunnel cũ đã chết (cloudflared 35236 `/ready` 503); proxy cũ 16144 chỉ nghe 127.0.0.1.

### Git

- `main` = `9ee5a4a` (release) + commit tài liệu, **chưa push** (vượt origin 31+).

## Hiện vật

| Hiện vật | Vị trí | SHA-256 |
|---|---|---|
| Gói 1.2.11 | `dist\DemandForecast-1.2.11-win64-portable.zip` | `5A7A73AA6283F45E49378BAE0509348477CD73C14A12204F38D8E6F0BB580886` |
| Gói 1.2.10 (rollback) | `dist\DemandForecast-1.2.10-win64-portable.zip` | `326E358799B911607C84E693374212839B5BC86F259798AE08D18A5B37724E62` |
| Backup xác minh trước deploy | `backups\backup-20261021-180216-manual.zip` | `EEEC86E677B7A77CEE1029D610D76FA13F28D0B696741C8AB679830D5F465CEB` |
| Backup của deploy-upgrade | `backups\backup-20261021-180400-manual.zip` | `29DC5902ADFBF42EC56664ED939DBBAC804D3EF48C519678982080F9B0EF43D3` |
| Checkpoint trước release | `checkpoints\checkpoint-20261021-release1211-prerelease.zip` | `86FE721D5D0F42252B78BB593DFA7B1D2519AF54D908598A390BC9449A5B267B` |
| Checkpoint sau (báo cáo, workbook, script, kết quả, state) | `checkpoints\checkpoint-20261021-release1211-after.zip` | `96084B02FD550A3FD37931DF8BE612B66F438B13F3A72C7107B8DB33AF51B5F1` (bản tạo trước khi ghi dòng SHA này) |
| Workbook bất thường | `reports\release-1.2.11-20261021\demandforecast_release_1211_anomalies_20261021.xlsx` | `516E659F9923AA059C0F8B66F67CD5701BD8DD34783BFEABFC1C9A5481E7B0B5` |
| Scratchpad | `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p28\` (+ `r12` diễn tập; bản sao DB `dbcopy_before` / `dbcopy_after` khoảng 1 GB mỗi bản, không đưa vào checkpoint) | - |

## Rollback (chỉ khi cần)

```powershell
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.11\scripts\rollback-version.ps1" -To 1.2.10 -CheckOnly    # exit 0
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.11\scripts\rollback-version.ps1" -To 1.2.10 -ConfirmToken ROLLBACK-1.2.10
```

- Cùng schema 9, không cần restore. Diễn tập: 14 s, gián đoạn 6 s.
- Quay về 1.2.10 nghĩa là quay về sửa 7.1: dòng WAIT_TO_CONFIRM giống mọi cột nguồn lại bị chặn. Với nguồn hiện tại không có
  dòng nào như vậy.

## Lệnh kiểm tra nhanh (chỉ đọc)

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health                        # 1.2.11
Invoke-RestMethod "http://127.0.0.1:8765/api/jobs?limit=5"
Invoke-RestMethod http://127.0.0.1:8765/api/history/overview               # 293 ngày chốt (+ ngày mới sau D-1)
cd "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.11\backend"; ..\python\python.exe -m app.cli data-check   # WARN, không FAIL
```

## Việc tiếp theo (chủ hệ thống)

1. Quy tắc giờ mở bán SKU × FC cho khóa nhiều listing, hoặc nguồn tự cung cấp giờ ở hạt SKU × FC. Sau đó: bản mới, preview +
   backfill 4 ngày, rồi huấn luyện candidate.
2. Lịch D-1 / huấn luyện, hoặc SLA nguồn (số liệu ở `DATA_RECONCILIATION.md` mục 6).
3. Link công khai:
   - nhà cung cấp URL cố định và tài khoản;
   - kiểm soát truy cập;
   - cho phép tự khởi động;
   - dừng tunnel / proxy cũ.
4. Duyệt push.
