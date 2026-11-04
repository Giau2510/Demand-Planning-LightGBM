# Resume checkpoint - release 1.2.12 (cập nhật 22/10/2026 11:40)

## Trạng thái

### Production (không đổi)

- Phiên bản **1.2.11**, schema 9, `http://127.0.0.1:8765`, PID 7316 (chạy từ 21/10 18:08).
- `current.txt` 1.2.11. `storage.json` SHA-256 `8D79DBDD…E047`, không đổi.
- Model đang dùng `TRN-20261020054540-D7EEF6` / `MV-20261020-131556-EEF6` (31 feature). Forecast `FCR-20261020082402-A42C91`
  (dữ liệu đến 19/10). Không đổi.
- **D-1:** dữ liệu đến **21/10**.
  - Job theo lịch 06:00 (`JOB-20261021235733-F4FE52`) thất bại `SOURCE_INCOMPLETE` 4 / 4.
  - Người vận hành chạy tay `JOB-20261022001433-6BAF6C` lúc 07:14: SUCCEEDED.
  - Cửa sổ 17-21/10 khớp nguồn tuyệt đối.
- **Huấn luyện theo lịch 07:00** (`JOB-20261022001636-B06CF0`, chạy 07:16): dừng `OPEN_HOURS_INVALID` (6 `MULTI_ITEM`), vì
  production vẫn là 1.2.11.
- **D-0:** lỡ khung 08:00 và 10:00 vì máy ngủ 07:27-10:42; lần chạy bù 10:42 SUCCEEDED.
- **Khung lịch kế tiếp:**
  - D-0: 12:00, 14:00, 16:00, 18:00;
  - EOD 23:55, close 23:59;
  - D-1 23/10 06:00; huấn luyện 23/10 07:00.

### Release 1.2.12: sẵn sàng, chưa triển khai

- Gói `dist\DemandForecast-1.2.12-win64-portable.zip`, SHA-256 `10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05`.
  Kiểm lại 22/10: commit `a601f4c`, manifest 7.148 / 7.148 file khớp.
- Backup mới đã xác minh: `backups\backup-20261022-111140-manual.zip`
  (`A3564E18EBAEC29953334EFBC3BDF4F2EA72AD9EF1034F3345E84B865866AFD6`).
- `deploy-upgrade -CheckOnly`: PASS lúc 11:18:33.
- Lệnh deploy chính thức bị bộ phân loại quyền của Claude Code từ chối **lần 2** lúc 11:20:37 (lần 1: 00:06). Không cài gì.
- Cổng 1.2.12 trên bản sao lấy 22/10 10:57 (dữ liệu đến 21/10): phủ đúng 6 dòng. Sáu khóa không đổi ở nguồn, kể cả từng
  listing.

### Candidate cũ (bản sao, dữ liệu đến 20/10)

- `TRN-20261021170704-F58EB8` / `MV-20261022-003132-8EB8`.
- WAPE 0,80535 so với 0,80555 của model đang dùng (cùng 7 fold). WAPE_MAX không đạt, nên không promote.
- Forecast `FCR-20261021173318-869CF1`: chỉ trên bản sao.

## Tiếp tục từ đây

### 1. Deploy (chủ hệ thống chạy, hoặc cho phép Claude Code chạy)

Chạy ngoài các khung D-0 giờ chẵn, khi không có job đang chạy:

```powershell
Set-Location "D:\Buymed\Lightgbm AI"
.\scripts\deploy-upgrade.ps1 -Package "dist\DemandForecast-1.2.12-win64-portable.zip" -ExpectedSha256 "10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05" -CheckOnly
.\scripts\deploy-upgrade.ps1 -Package "dist\DemandForecast-1.2.12-win64-portable.zip" -ExpectedSha256 "10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05" -ConfirmToken "UPGRADE-1.2.12"
```

### 2. Kiểm tra sau deploy (chỉ đọc)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p29\post1212.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p30\state_capture.ps1" -Out "C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p30\state\post_deploy_state.json"
```

Kỳ vọng `post1212.ps1` đạt 11 / 11:
- health 1.2.12; `storage.json` không đổi;
- smoke 200; forecast đang dùng không đổi;
- cổng giờ mở bán phủ đúng 6 dòng;
- cấu hình không đổi (Price ON, customer OFF, horizon 7/15, cửa sổ từ 01/01, huấn luyện 07:00 SKIP); lịch không đổi;
- data-check 1.2.12 không FAIL;
- rollback `-CheckOnly` đạt; scheduler đang chạy.

Đối chiếu `post_deploy_state.json` với `p30\state\pre_deploy_state.json`.

### 3. Huấn luyện production

Trang Lịch → Huấn luyện → "Chạy ngay 1 lần" (gọi `POST /api/schedules/train/run`).
- Mất khoảng 25-35 phút. Giữ máy thức trong lúc chạy.
- Kết quả: candidate chờ duyệt (REJECTED + `PROMOTION_REVIEW_REQUIRED`). Model đang dùng không bị thay.
- Dữ liệu đến 21/10, khác candidate cũ (đến 20/10).

### 4. Sau huấn luyện (Claude)

- Ghi lại:
  - training ID, mốc dữ liệu, số dòng và số khóa;
  - feature list từ metadata của model;
  - quyết định 6 khóa (`feature_decisions.open_hours.override`);
  - so sánh cùng fold.
- Forecast để duyệt: bản sao DB (backup API), rồi `promote_candidate` trên bản sao (như `p29\fc_copy.py`), xuất 15 ngày.
  Production không đổi.
- Cập nhật 6 hiện vật.

### 5. Quyết định của chủ hệ thống

- promote;
- lịch D-1 (5 / 5 lần chạy theo lịch thất bại vì nguồn làm mới khoảng 07:10);
- backfill phần lịch sử mà nguồn đã sửa (841 khóa trước 17/10);
- link công khai;
- push.

## Rollback (chỉ khi đã triển khai 1.2.12)

```powershell
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.12\scripts\rollback-version.ps1" -To 1.2.11 -CheckOnly
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.12\scripts\rollback-version.ps1" -To 1.2.11 -ConfirmToken ROLLBACK-1.2.11
```

- Cùng schema 9, không restore. Diễn tập: 14,8 s, gián đoạn 6,1 s.
- 1.2.11 chặn lại 6 khóa.

## Lệnh kiểm tra nhanh (chỉ đọc)

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod "http://127.0.0.1:8765/api/features/registry?source=BIGQUERY" | Select-Object -ExpandProperty next_training
Invoke-RestMethod "http://127.0.0.1:8765/api/jobs?limit=5"
```

## Hiện vật

| Hiện vật | Vị trí | SHA-256 |
|---|---|---|
| Gói 1.2.12 | `dist\DemandForecast-1.2.12-win64-portable.zip` | `10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05` |
| Gói 1.2.11 (đang chạy / rollback) | `dist\DemandForecast-1.2.11-win64-portable.zip` | `5A7A73AA6283F45E49378BAE0509348477CD73C14A12204F38D8E6F0BB580886` |
| Backup xác minh 22/10 (trước deploy) | `backups\backup-20261022-111140-manual.zip` | `A3564E18EBAEC29953334EFBC3BDF4F2EA72AD9EF1034F3345E84B865866AFD6` |
| Backup xác minh 22/10 00:04 | `backups\backup-20261022-000431-manual.zip` | `ED0F8EC680DAE8D216DAD8A46BA173A63A0FCD20C7418EC1228D8F99C916E7A7` |
| Checkpoint trước release | `checkpoints\checkpoint-20261021-release1212-prerelease.zip` | `F7AF84DBD21CD046DC43C85907FF7F6FB54127A3511A08E265F8D8F659715647` |
| Checkpoint cuối lượt đêm | `checkpoints\checkpoint-20261022-release1212-final.zip` | `84860D725A6E4F187CC4BB2DB88F1452481F4F5A07A98168F0B7FC654023C107` |
| Checkpoint lượt 22/10 (báo cáo, workbook, script và kết quả `p30`) | `checkpoints\checkpoint-20261022-release1212-deploy-denied2-r2.zip`. Thay cho `…-deploy-denied2.zip` (BA52746B…D68D); hai bản chỉ khác giờ ghi trong báo cáo | xem file `.sha256` cùng tên (tạo sau khi ghi dòng này) |
| Bằng chứng 6 khóa | `OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx` | `594792F0C42BEED966580B82392D22E476662C4CBFEBE48625A260D14B73C2C8` |
| Huấn luyện / forecast / weekday / customer / D-1 22/10 | `TRAINING_FORECAST_REPORT.xlsx` | `4AFBC971984CB42836D4557EC55E75364D8583A0AA40D96F3210AF4F5A318D1D` |
| Model candidate cũ | `candidate\MV-20261022-003132-8EB8.txt` | `3073A16FD147F5A9CAE19CD884DA67D6315F559370BC6268947D11AF77747D7D` |
| Forecast candidate cũ | `candidate\candidate_forecast_FCR-20261021173318-869CF1_15d.xlsx` | `ADB11510B39937595A324AFFAF3B0C0096420D86F401598076F4942DD213C33B` |
| Scratchpad lượt đêm | `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p29\` | - |
| Scratchpad lượt 22/10 | `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p30\` | - |

**Scratchpad `p30`:**
- script: `state_capture.ps1`, `pkg_check.py`, `src_agg_d1.py`, `recon_d1.py`, `bq_six.py`, `six_cmp.py`, `gate_copy.py`,
  `verify_b.py`, `wb_update_1022.py`, `keepawake.ps1`;
- `state\`: kết quả JSON, `checkonly.txt`, bản báo cáo trước khi sửa (`wb_before\`);
- `g\`: bản sao DB 10:57, khoảng 0,8 GB, không đưa vào checkpoint.
