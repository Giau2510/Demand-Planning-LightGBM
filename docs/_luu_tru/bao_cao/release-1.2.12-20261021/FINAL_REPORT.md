# Báo cáo cuối - release 1.2.12 (21/10/2026 21:13 - 22/10/2026 11:40)

**Trạng thái hiện hành (22/10/2026 11:40):**
- **Release:** `READY_FOR_PRODUCTION`. Gói, kiểm thử, diễn tập, CheckOnly và backup đều đạt.
- **Chưa triển khai.** Lệnh deploy chính thức bị bộ phân loại quyền của Claude Code từ chối **lần thứ hai** (22/10 11:20:37;
  lần đầu 00:06). Production vẫn **1.2.11**.
- **D-1 ngày 21/10:** đã kiểm. SUCCEEDED, cửa sổ D-1 khớp nguồn tuyệt đối, dữ liệu đến 21/10 sẵn sàng.
- **Huấn luyện, forecast và quality gate trên production:** NOT STARTED, vì phụ thuộc deploy.
- **Model production:** không đổi.
- **Promote:** BLOCKED. **Link công khai:** `BLOCKED_EXTERNAL_SETUP`.

## 0. Lượt tiếp tục 22/10/2026 10:53-11:40 (deploy, huấn luyện production, forecast mới)

### 0.1 Kết quả theo yêu cầu

**1. D-1:**
- Job theo lịch 06:00 `JOB-20261021235733-F4FE52`: FAILED `SOURCE_INCOMPLETE` 4 / 4. Máy thức 06:57; nguồn chỉ làm mới lúc
  07:10:45.
- Người vận hành chạy tay `JOB-20261022001433-6BAF6C` (07:14-07:16): **SUCCEEDED**.
  - Watermark / mốc dữ liệu **21/10/2026**, cửa sổ 17/10-21/10.
  - Mới 3.151, cập nhật 123, xóa 10, giữ nguyên 11.862.
- Chạy lại `JOB-20261022002057-3545EE`: 0 thay đổi.
- Đối soát với nguồn (bản 22/10 07:10:45): cửa sổ D-1 **khớp tuyệt đối**. Ngày 21/10: 3.151 khóa, 96.247 đơn vị, 19.266 dòng.
- Không lỗi mapping, không trùng, không blocker mới.
- Hai phát hiện không chặn (chi tiết: `DATA_RECONCILIATION.md` mục 5):
  - nguồn đã sửa lịch sử 01/01-16/10 (841 khóa, ròng +1.303 đơn vị = 0,003 %), chưa nạp vì không backfill;
  - 4 ngày đã chốt (17-20/10) khác dữ liệu hiện tại do sửa muộn trong cửa sổ D-1. Đây là thiết kế: ngày đã chốt không sửa.

**2. Deploy:** **BLOCKED_WITH_EVIDENCE** (mục 0.2).
- Kiểm sau lúc từ chối: `/api/health` 1.2.11, `current.txt` 1.2.11, PID 7316 vẫn chạy.
- Không có thư mục cài 1.2.12; `storage.json` `8D79DBDD…E047` không đổi.

**3. Backup, gói, smoke, rollback:**
- **Gói:** SHA-256 `10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05`, đúng kỳ vọng.
  - Commit `a601f4c`, sạch; manifest 7.148 / 7.148 file khớp.
  - Có quy tắc 6 khóa, weekday, mã customer (OFF) và giao diện "Thứ 2 … Chủ nhật".
- **Backup mới:** `backups\backup-20261022-111140-manual.zip` (`A3564E18EBAEC29953334EFBC3BDF4F2EA72AD9EF1034F3345E84B865866AFD6`),
  xác minh độc lập PASS.
- **`-CheckOnly`:** PASS (exit 0, 11:18:33).
- **Smoke sau deploy:** chưa chạy (không có deploy). Diễn tập r13 hôm qua: smoke 200 toàn bộ.
- **Rollback:** 1.2.11 vẫn cài và đang chạy. Kế hoạch giữ nguyên: `rollback-version.ps1 -To 1.2.11`, cùng schema, không
  restore; diễn tập 14,8 s.

**4. Training ID / forecast ID mới:** không có (NOT STARTED).
- Lần huấn luyện theo lịch 07:00 hôm nay `JOB-20261022001636-B06CF0` dừng `OPEN_HOURS_INVALID`. Lý do: production 1.2.11 chưa
  có quy tắc 6 khóa.

**5. Feature thực tế:**

| | Model đang dùng `MV-20261020-131556-EEF6` | Candidate bản sao `MV-20261022-003132-8EB8` | Huấn luyện production kế tiếp (1.2.12) |
|---|---|---|---|
| Số feature | 31 | 33 = 31 + `open_hours_last`, `open_hours_mean_7` | Như candidate: cùng mã, cùng cấu hình |
| `feature_weekday` | `dow`, `is_weekend`; mã hóa cũ 0..6 (Thứ 2 = 0) | `dow` ISO 1..7 (Thứ 2 = 1 … Chủ nhật = 7), `is_weekend`; 0 sai lệch trên 5.206.698 dòng | ISO 1..7 |
| `customer_id` | OFF | OFF | OFF (`feature_customer` false, `customer_id_column` rỗng) |
| Price | `price_last`, `price_rel_28` | như bên trái | ON |
| `sku_system_status` | không dùng | không dùng | không dùng |

**6. Chất lượng:**
- Chưa có candidate production mới để chấm.
- Candidate cũ trên bản sao (`TRN-20261021170704-F58EB8`, dữ liệu đến 20/10), cùng 7 fold:
  - WAPE 0,80535 so với 0,80555 của model đang dùng; bias +0,0624;
  - WAPE_MAX FAIL (> 0,6), không promote.
- Model đang phục vụ: `TRN-20261020054540-D7EEF6`, forecast `FCR-20261020082402-A42C91` (dữ liệu đến 19/10). Không đổi.

**7.** Bảng mục 0.3. **8.** Blocker và bước tiếp theo: mục 0.4.

**Lưu ý về "chạy forecast":**
- Khi đã có model đang dùng, huấn luyện chỉ giữ candidate chờ duyệt và **không tạo forecast** trên production.
- Trên production, forecast của candidate chỉ tạo được qua "Dùng model này" (promote). Bước đó cần chủ hệ thống duyệt.
- Vì vậy, sau lần huấn luyện production, forecast mới để duyệt sẽ được tạo trên **bản sao** bằng đúng chức năng đó, như
  `FCR-20261021173318-869CF1`. Forecast production giữ nguyên tới khi có quyết định promote.

### 0.2 Lệnh bị từ chối

Chạy đúng như yêu cầu, ở chế độ nền, ghi output ra file:

```powershell
Set-Location "D:\Buymed\Lightgbm AI"
.\scripts\deploy-upgrade.ps1 `
  -Package "dist\DemandForecast-1.2.12-win64-portable.zip" `
  -ExpectedSha256 "10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05" `
  -ConfirmToken "UPGRADE-1.2.12"
```

Lỗi trả về (11:20:37): *"Permission for this action was denied by the Claude Code auto mode classifier. Reason: The server-side
auto mode classifier judged this action dangerous (it gave no explanation)."*

- Lệnh không chạy: file output không được tạo, production không đổi.
- Theo đúng yêu cầu, **không** thử cách khác: không wrapper, không đổi token, không đường dẫn khác, không tắt cơ chế bảo vệ.
- Một yêu cầu giữ máy thức tạm thời (cấp tiến trình, không đổi cài đặt nguồn điện) được bật lúc 11:19 cho deploy và huấn
  luyện, rồi tắt ngay sau khi bị từ chối.

### 0.3 Bảng DONE / BLOCKED / NOT STARTED

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Kiểm D-1 + đối soát nguồn đến 21/10 | **DONE** | `DATA_RECONCILIATION.md` mục 5; sheet `D1_2026-10-22` |
| Kiểm gói 1.2.12 | **DONE** | `TEST_RESULTS.md` mục 6 |
| Backup mới + xác minh | **DONE** | `backup-20261022-111140-manual.zip` (A3564E18…AFD6) |
| `deploy-upgrade -CheckOnly` | **DONE** (PASS) | exit 0, 11:18:33 |
| Sáu khóa: kiểm lại trên nguồn hôm nay | **DONE** | 12 / 12 giá trị listing không đổi; sheet `Recheck_2026-10-22` |
| Cổng 1.2.12 trên bản sao hôm nay | **DONE** | Phủ đúng 6 dòng; sheet `Gate_copy_2026-10-22` |
| **Deploy 1.2.12 lên production** | **BLOCKED_WITH_EVIDENCE** | Từ chối quyền lúc 11:20:37 (lần 2). Production 1.2.11 |
| Kiểm tra sau deploy, smoke, rollback `-CheckOnly` | NOT STARTED | Phụ thuộc deploy |
| Huấn luyện production ("Chạy ngay") | NOT STARTED | Phụ thuộc deploy; 1.2.11 vẫn chặn (job 07:16) |
| Forecast mới (để duyệt) | NOT STARTED | Phụ thuộc huấn luyện |
| Quality gate candidate production mới | NOT STARTED | Phụ thuộc huấn luyện |
| Model / forecast production | Không đổi | `TRN-20261020054540-D7EEF6` / `FCR-20261020082402-A42C91` |
| Quy tắc 6 khóa | `PASS_IMPLEMENTED_AND_USED` trên bản sao; production `BLOCKED_WITH_EVIDENCE` | Mục 2 |
| `feature_weekday` | `PASS_IMPLEMENTED_AND_USED` (candidate bản sao) | Mục 4 |
| `customer_id` | OFF trên production; chỉ thí nghiệm offline | Mục 5 |
| Promote | BLOCKED | WAPE_MAX không đạt, chưa được duyệt |
| Link công khai cho lãnh đạo | `BLOCKED_EXTERNAL_SETUP` | Không đổi tài khoản / hạ tầng |
| Lịch D-1 | Cần quyết định | 5 / 5 lần theo lịch từ 18/10 thất bại `SOURCE_INCOMPLETE` (nguồn làm mới khoảng 07:10). Không đổi lịch |
| Push Git | Cần duyệt | `fe4ca9b`, `a601f4c`, `24590d2` local; `main` vượt origin 35. Không push |
| Nguồn sửa lịch sử (841 khóa trước 17/10) | Cần quyết định | Không backfill. Sheet `Source_drift_2026-10-22` |
| Máy tự ngủ | Rủi ro vận hành | Modern Standby 01:53-06:57 và 07:27-10:42 (Kernel-Power 506 / 507). Bị lỡ D-0 08:00 và 10:00 (`MISSED_SLOT_NO_BACKFILL`) |

### 0.4 Việc chủ hệ thống cần làm

**1. Deploy.** Ngoài các khung D-0 giờ chẵn (12, 14, 16, 18 h), khi không có job đang chạy. Mất khoảng 5 phút, gián đoạn khoảng
2 phút. Mở PowerShell rồi chạy:

```powershell
Set-Location "D:\Buymed\Lightgbm AI"
.\scripts\deploy-upgrade.ps1 -Package "dist\DemandForecast-1.2.12-win64-portable.zip" -ExpectedSha256 "10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05" -CheckOnly
.\scripts\deploy-upgrade.ps1 -Package "dist\DemandForecast-1.2.12-win64-portable.zip" -ExpectedSha256 "10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05" -ConfirmToken "UPGRADE-1.2.12"
```

Hoặc thêm quy tắc quyền cho Claude Code rồi yêu cầu chạy tiếp.

**2. Báo Claude "đã deploy".** Claude sẽ làm tiếp:
- kiểm tra sau deploy (`scratchpad\p29\post1212.ps1`): health 1.2.12, smoke, cổng đúng 6 dòng, cấu hình và lịch không đổi,
  data-check, rollback `-CheckOnly`;
- huấn luyện qua nút "Chạy ngay 1 lần" ở trang Lịch → Huấn luyện, theo dõi tới khi xong;
- kiểm tra weekday, 6 khóa, Price ON, customer OFF;
- so sánh cùng fold, chi tiết theo SKU × FC và horizon;
- tạo forecast để duyệt trên bản sao;
- cập nhật báo cáo.

Chủ hệ thống cũng có thể tự bấm "Chạy ngay 1 lần".

**3. Giữ máy thức** trong khoảng 25-35 phút huấn luyện. Sáng nay máy đã tự ngủ hai lần khi không dùng.

**4. Quyết định:**
- promote;
- lịch D-1;
- backfill phần lịch sử nguồn đã sửa;
- link công khai;
- push.

Các mục 1-10 dưới đây là báo cáo của lượt 21/10 21:13 - 22/10 07:00, giữ nguyên làm hồ sơ. Trạng thái hiện hành ở mục 0.

## 1. Bảng trạng thái (lượt 21-22/10)

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Quy tắc MAX cho đúng 6 khóa (mã, test, tài liệu) | **DONE** | Phần 2. `test_v1212_open_hours_override.py` 22 passed. `OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx` |
| Weekday (Thứ 2 = 1 … Chủ nhật = 7) trong huấn luyện / backtest / suy luận / UI | **DONE** | Phần 4. Ma trận thật 5.206.698 dòng, 0 sai lệch |
| Thí nghiệm offline `customer_id` | **DONE** | Phần 5. `TRAINING_FORECAST_REPORT.xlsx` |
| Kiểm thử, đóng gói, diễn tập | **DONE** | `TEST_RESULTS.md`: backend 716 / 19 skip, vitest 159, BigQuery thật 14, r13 36 / 36 |
| Đối soát nguồn, D-1 | **DONE** | `DATA_RECONCILIATION.md`: dữ liệu = nguồn, D-1 không cần chạy lại |
| Gate triển khai + backup xác minh | **DONE** | Gate PASS 00:03:44. `backup-20261022-000431-manual.zip` (ED0F8EC6…E7A7) xác minh 00:05:30 |
| **Triển khai 1.2.12 lên production** | **BLOCKED_WITH_EVIDENCE** | Bộ phân loại quyền từ chối lệnh `deploy-upgrade -ConfirmToken UPGRADE-1.2.12` lúc 00:06. Không cài gì. Production vẫn 1.2.11 (PID 7316) |
| Candidate huấn luyện (bản sao production) | **DONE** | `TRN-20261021170704-F58EB8` / `MV-20261022-003132-8EB8`, phần 3 |
| Forecast candidate (bản sao, không publish) | **DONE** | `FCR-20261021173318-869CF1`: 15 ngày, 256.935 giá trị |
| Huấn luyện + forecast **trên production** | **NOT STARTED** (chờ triển khai) | Production 1.2.11 vẫn chặn `OPEN_HOURS_INVALID` (đã kiểm 00:06) |
| Promote model | **BLOCKED** | WAPE_MAX 0,8053 > 0,6. Không có quy tắc promote đã duyệt |
| Link công khai ổn định cho lãnh đạo | **BLOCKED_EXTERNAL_SETUP** | Phần 8 |
| Độ tin cậy lịch D-1 | **Cần quyết định** | Phần 8 |
| Push Git | **Cần duyệt** | Phần 9 |

Nhãn theo yêu cầu:

| Yêu cầu | Nhãn |
|---|---|
| Quy tắc 6 khóa | `PASS_IMPLEMENTED_AND_USED`: model candidate dùng 6 giá trị MAX. Trên production `BLOCKED_WITH_EVIDENCE` cho đến khi triển khai |
| `feature_weekday` | `PASS_IMPLEMENTED_AND_USED` |
| `customer_id` (thí nghiệm offline) | `PASS_IMPLEMENTED_AND_USED` trong thí nghiệm B. Production vẫn OFF theo yêu cầu |
| Huấn luyện / forecast production | `BLOCKED_WITH_EVIDENCE` (triển khai bị từ chối quyền) |

## 2. Quy tắc 6 khóa (chủ hệ thống duyệt 21/10)

**Quy tắc:** `total_open_hours` đại diện = **MAX** giờ mở bán hợp lệ của các listing cùng SKU × FC × ngày. Chỉ áp dụng cho 6
khóa:

| Khóa | MAX |
|---|---|
| 09/02 HN MEDX.DMTS-HOA-BAO-002 | 24 |
| 10/02 HN MEDX.2LJ61PGE | 24 |
| 02/03 BD MEDX.DMTS-STA-LOS-002 | 24 |
| 02/03 BD MEDX.SOP-NEO-001 | 24 |
| 26/08 BD MEDX.COU-STR-001 | 24 |
| 26/08 BD MEDX.D6TABCV8 | 22,85 |

Cài đặt: `backend/app/data/open_hours_override.py` (rule `OWNER_ADHOC_MAX_LISTING_OPEN_HOURS`, version 1.2.12).

**Phạm vi:**
- Khóa = scope × ngày × SKU × FC. `item_code` chỉ là nhãn của giá trị bằng chứng.
- Không phải quy tắc chung: khóa nhiều listing khác vẫn `MULTI_ITEM` và vẫn chặn.
- `demand_daily` và phân loại D-1 không đổi.
- `WAIT_TO_CONFIRM` vẫn được miễn kiểm tra trùng; quy tắc trùng của các trạng thái khác giữ nguyên (không so `item_code`).

**Kiểm tra mỗi lần dùng:**
- Giá trị listing có mặt, là số, hữu hạn, trong 0..24, ít nhất 2 listing.
- MAX tính trong code. Workbook đặt công thức Excel `=MAX()` cạnh giá trị của code.
- Dòng lưu phải còn `MULTI_ITEM`, không giá trị, cùng số lượng, số đơn và **cùng lần nạp** đã đối chiếu (`loaded_at`
  2026-10-21T05:36:47Z, đọc bản nguồn 07:10:38).
- Khung dữ liệu được kiểm lại khi gán.

Không khớp thì khóa đó vẫn chặn, kèm lý do:

| Lý do | Nghĩa |
|---|---|
| `CONTENT_CHANGED` | Số lượng hoặc số đơn đã đổi |
| `RELOADED_SINCE_APPROVAL` | Dòng đã được nạp lại sau lần đối chiếu |
| `STORED_STATUS_*` | Trạng thái lưu không còn là `MULTI_ITEM` |
| `LISTING_VALUE_*` | Giá trị listing không hợp lệ |

Khóa không còn dòng (`ROW_NOT_FOUND`): không gán gì, được ghi kèm lần huấn luyện.

**Truy vết:**
- Mỗi lần huấn luyện ghi `feature_decisions.open_hours.override`: giá trị từng listing, MAX, quy tắc, phiên bản, lý do, thời
  điểm, dòng lưu.
- Nhật ký `OPEN_HOURS_OVERRIDE_APPLIED`.
- Dựng lại panel của lần huấn luyện (promote, giải thích) dùng giá trị đã ghi.

**Đảo ngược:** xoá khóa trong bản sau, hoặc rollback 1.2.11. Diễn tập r13 chứng minh 1.2.11 chặn lại đúng 6 dòng, không phải
sửa dữ liệu.

**Đánh giá độc lập** (data-reviewer): SAFE WITH CONDITIONS. Các điều kiện S1-S4 đã xử lý (xem `TEST_RESULTS.md` mục 3).

## 3. Huấn luyện và forecast candidate

Vì lệnh triển khai bị từ chối, candidate được huấn luyện trên **bản sao cách ly của production**:
- bản sao lấy 00:06 ngày 22/10, sau job 23:55 và 23:59, cùng file model;
- mã 1.2.12 (`a601f4c`), gọi đúng `pipeline.train_and_publish` như nút "Chạy ngay";
- cấu hình đã lưu của production.

**Dữ liệu:**
- 2026-01-01..2026-10-20 (mốc dữ liệu 20/10).
- 1.360.913 dòng, 42.088.223 đơn vị, 17.129 series SKU × FC, 5.206.698 dòng huấn luyện DIRECT.
- Không loại dòng nào. Fingerprint `ab4e9288e09cf17b`.

**Cấu hình:**
- DIRECT, tweedie, 300 vòng, learning rate 0,05, 31 lá.
- **Price ON**, **customer_id OFF**, `sku_system_status` không dùng.
- Weekday ISO; giờ mở bán bắt buộc (6 khóa theo quy tắc MAX).
- 33 feature.
- Backtest 12 fold × 30 ngày, bước 30 (7 fold đủ lịch sử).
- Horizon 7/15, không đổi.

| | Candidate `TRN-20261021170704-F58EB8` | Model đang dùng `TRN-20261020054540-D7EEF6` |
|---|---|---|
| Model | `MV-20261022-003132-8EB8` (SHA-256 3073A16F…7D7D) | `MV-20261020-131556-EEF6` |
| Backtest cùng fold (7 fold, 3.360.851 điểm) | **WAPE 0,80535**, bias +0,0624, MAE 6,581 | WAPE 0,80555, bias +0,0620, MAE 6,583 (huấn luyện lại trên cùng fold) |
| So sánh | **BETTER**, nhưng chỉ −0,0002 WAPE (không đáng kể); bias +0,0005 | - |
| Quality gate (ngưỡng hiện có) | BACKTEST_RELIABLE PASS, MIN_POINTS PASS, **WAPE_MAX FAIL** (0,8053 > 0,6), ABS_BIAS PASS (0,062 ≤ 0,2) | (khi huấn luyện: WAPE 0,7972 FAIL) |
| Baseline 28 ngày, cùng điểm | WAPE 0,8485 | - |
| Theo horizon (1-7 / 8-15 / 16-30 ngày) | 0,740 / 0,813 / 0,834 | - |
| Kết luận | Giữ để duyệt (`PROMOTION_REVIEW_REQUIRED`), **không promote** | Vẫn đang dùng |

**Forecast candidate `FCR-20261021173318-869CF1`:**
- Chỉ trên bản sao, tạo bằng đường "Dùng model này" của ứng dụng; **không publish trên production**.
- Origin 21/10, dữ liệu đến 20/10, horizon 7/15.
- 17.129 series: 4.222 LightGBM, 3.263 không hoạt động, 9.446 gián đoạn, 198 mới.
- 256.935 giá trị (21/10-04/11), 1.108.720 đơn vị.
- So với forecast đang dùng `FCR-20261020082402-A42C91` trên 14 ngày trùng (21/10-03/11): 1.034.135 so với 1.065.368 đơn vị
  (thấp hơn 2,9 %; mỗi ngày thấp hơn 2-4 %).
- Lưu tại `candidate/`:
  - model `.txt` + `.json`;
  - file Excel xuất bởi ứng dụng;
  - giá trị `.csv.gz`.

Khi triển khai xong và bấm "Chạy ngay" huấn luyện trên production, cùng dữ liệu và mã sẽ cho cùng candidate (LightGBM
deterministic). Backtest của thí nghiệm A trùng candidate tới chữ số cuối.

## 4. Weekday - `PASS_IMPLEMENTED_AND_USED`

- **Nguồn ngày:** thứ tính từ chính ngày lịch: `order_date` = cột `created_date` đã ánh xạ ở lịch sử; ngày dự báo ở suy luận.
  Quy ước ISO, Thứ 2 = 1 … Chủ nhật = 7 (`app/weekday.py`).
- **Feature:** `dow` và `is_weekend` của **ngày mục tiêu**. Feature tại mốc chỉ dùng dữ liệu trước mốc. Thứ của ngày mục tiêu
  là lịch, không phải nhu cầu, nên không rò rỉ.
- **Bằng chứng trên model thật `MV-20261022-003132-8EB8`:**
  - Tên feature của booster = danh sách lưu = cấu hình = metadata (33, đúng thứ tự).
  - Ma trận huấn luyện 5.206.698 × 33: **0** dòng `dow` sai, **0** dòng `is_weekend` sai so với ngày mục tiêu. Đủ 7 giá trị
    1..7.
  - Suy luận: 45 dòng thực sự đưa vào `predict()` (3 series × 15 ngày), 0 sai lệch so với ngày dự báo.
  - Model dùng thật: `dow` gain 2,09 triệu (176 split), `is_weekend` 0,21 triệu (12 split).
  - Model đang dùng (huấn luyện bởi 1.2.8) giữ mã hóa cũ 0..6, cùng hàm tính thứ.
- **Test:** `test_v1212_weekday_parity.py` (8):
  - đủ 7 thứ;
  - biên tháng / năm / năm nhuận, mốc giờ muộn;
  - mọi dòng huấn luyện DIRECT và RECURSIVE;
  - mọi fold walk-forward (dòng huấn luyện trước mốc và từng ma trận đưa vào `predict()`);
  - suy luận; tên feature của booster.
- **UI:** một dạng duy nhất "Thứ 2" … "Chủ nhật" ở bảng dự báo, khung giải thích (trước là "Thứ Hai"), tooltip biểu đồ xu
  hướng, trang lịch sử, tiêu đề SHAP. Test `v1212-weekday.test.tsx` cùng 5 file test cũ cập nhật.

## 5. customer_id (thí nghiệm offline) - `PASS_IMPLEMENTED_AND_USED`; production OFF

**Dữ liệu:**
- `customer_id` INTEGER, 0 NULL / 0 rỗng trên 8.979.752 dòng (01/01-20/10).
- 35.075 khách. Có ở mọi tháng.
- Không phải khóa đơn: mỗi đơn đúng 1 khách; 33.110 khách có nhiều đơn.

**Đặc trưng:**
- Chỉ dùng tổng hợp theo ngày × SKU × FC từ SQL của ứng dụng; định danh không rời BigQuery.
- Không dùng `customer_id` làm cột hay biến phân loại.
- 3 feature:
  - `cust_mean_28`;
  - `cust_repeat_share_28`;
  - `cust_repeat_interval_28`.
- Phủ 100 % khóa.

**Kiểm tra:**
- Rò rỉ: trên panel thật, đổi mọi dữ liệu khách từ mốc 21/09 trở đi không đổi feature tại mốc.
- Khách mới ở suy luận chỉ là số đếm. 46-48 % ngày-khách trong mỗi cửa sổ đánh giá là khách mới với series đó; không có
  "nhóm chưa thấy".
- Cùng mã `features_at` cho huấn luyện, backtest và suy luận.

**Kết quả** (cùng panel, fold, mục tiêu, 3.360.851 điểm):

| | A = cấu hình production (weekday, giờ mở bán, Price; khách OFF) | B = A + 3 feature khách |
|---|---:|---:|
| WAPE gộp | 0,8053 | **0,8019** (−0,0035) |
| Bias | +0,0624 | +0,0643 (+0,0019) |
| Fold tốt hơn | - | 5 / 7 (xấu hơn ở fold 23/07 và fold mới nhất 21/09) |
| Horizon 1-7 / 8-15 / 16-30 | 0,740 / 0,813 / 0,834 | 0,733 / 0,810 / 0,832 |
| Series tốt hơn / xấu hơn | - | 5.788 / 4.334 |

**Kết luận:** cải thiện nhỏ, có đo được, không nhất quán ở fold mới nhất. Cả hai đều không đạt WAPE ≤ 0,6.

**Không bật trên production.** Lưu ý quan trọng nếu chủ hệ thống muốn bật: ánh xạ cột khách hàng đổi mapping hash, kéo theo
D-1 nạp lại toàn bộ. Khi đó 6 dòng được nạp lại và bị `RELOADED_SINCE_APPROVAL` chặn cho tới khi đối chiếu lại.

## 6. Kiểm thử, gói, backup, rollback

Chi tiết: `TEST_RESULTS.md`.

**Commit:**
- `fe4ca9b`: release.
- `a601f4c`: sửa `ROW_NOT_FOUND`. Lần QA đầu thất bại và không tạo gói nào.

**Gói:** `dist\DemandForecast-1.2.12-win64-portable.zip`, SHA-256
`10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05`.

**Diễn tập r13: 36 / 36.**
- Nâng cấp 286 s (gián đoạn 122 s), không migration.
- Rollback 1.2.11 14,8 s (gián đoạn 6,1 s), không restore.

**Backup:**
- `backups\backup-20261022-000431-manual.zip` (ED0F8EC680DAE8D216DAD8A46BA173A63A0FCD20C7418EC1228D8F99C916E7A7): backup
  trực tuyến chính thức của `deploy-upgrade`, dừng ở bước xác nhận và được xác minh độc lập (schema 9, integrity ok).
- Checkpoint trước release: `checkpoints\checkpoint-20261021-release1212-prerelease.zip` (F7AF84DB…5647).

**Rollback** (sau khi đã triển khai):

```
rollback-version.ps1 -To 1.2.11
```

- Cùng schema, không restore. 1.2.11 chặn lại 6 khóa.
- Dữ liệu không cần sửa: 1.2.12 không ghi gì vào `demand_daily`.

## 7. Việc chủ hệ thống cần làm để hoàn tất

**1. Triển khai.** Chạy ngoài khung lịch, khi không có job chạy (an toàn: trước 05:15, hoặc giữa các lần D-0):

```powershell
cd "D:\Buymed\Lightgbm AI"
.\scripts\deploy-upgrade.ps1 -Package "dist\DemandForecast-1.2.12-win64-portable.zip" -ExpectedSha256 10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05 -CheckOnly
.\scripts\deploy-upgrade.ps1 -Package "dist\DemandForecast-1.2.12-win64-portable.zip" -ExpectedSha256 10BF50BF4DBD207EE81D00A29306F5C536B0E330EFE9D93DA9F901F46EBA4C05 -ConfirmToken UPGRADE-1.2.12
```

Script tự lấy backup trực tuyến trước khi cài. Hoặc cho phép Claude Code chạy lệnh deploy.

**2. Kiểm tra sau triển khai** (chỉ đọc; 11 kiểm tra gồm cổng giờ mở bán, cấu hình, lịch, data-check, rollback `-CheckOnly`):

```
scratchpad\p29\post1212.ps1
```

**3. Huấn luyện production:** trang Lịch, "Huấn luyện", bấm "Chạy ngay" (khoảng 25-35 phút). Kết quả là candidate chờ duyệt;
model đang dùng không bị thay.

**Cập nhật 07:00 ngày 22/10:**
- Máy ngủ từ 01:53 đến 06:57 (Kernel-Power 42 / 506 / 507).
- D-1 theo lịch 06:00 (`JOB-20261021235733-F4FE52`) chạy sau khi máy thức. Lúc 07:00 đang `RETRY_WAIT` với
  `SOURCE_INCOMPLETE` (lần 2 / 4): nguồn chưa có ngày 21/10, đúng mẫu đã biết (làm mới khoảng 07:10).
- Hệ quả cho bước 1-3:
  - chờ job này kết thúc rồi mới triển khai (không triển khai khi có job đang chạy);
  - nếu D-1 nạp được 21/10, lần huấn luyện production sau triển khai dùng dữ liệu đến 21/10, khác candidate trên bản sao (đến
    20/10). Các chỉ số sẽ khác đôi chút;
  - 6 khóa không bị ảnh hưởng, vì D-1 chỉ đọc lại vài ngày cuối.

**4. Quyết định promote:** quality gate không đạt, nên cần quyết định riêng (`release-with-exception` hoặc giữ model hiện
tại).

## 8. Việc còn mở

| Việc | Trạng thái | Quyết định cần thiết |
|---|---|---|
| Link công khai ổn định cho lãnh đạo | `BLOCKED_EXTERNAL_SETUP` | Chọn nhà cung cấp và tài khoản (đề xuất Cloudflare named tunnel trên domain công ty; hoặc Tailscale Funnel / ngrok); giới hạn truy cập (email lãnh đạo); kiểm chứng truy cập từ ngoài; duyệt tự khởi động; dừng tunnel / proxy cũ đã chết (cloudflared 35236, proxy 16144). Không có gì thay đổi trong đợt này |
| Độ tin cậy D-1 | Cần quyết định | 4 / 4 D-1 theo lịch từ 18/10 thất bại `SOURCE_INCOMPLETE`: nguồn làm mới khoảng 07:10, D-1 chạy 06:00 / 06:30. Huấn luyện 07:00 rồi bị SKIP. Chọn: dời D-1 sau 07:15 và huấn luyện sau D-1, hoặc nguồn cam kết sẵn trước 06:00. Không đổi lịch nào |
| Push Git | Cần duyệt | Commit local `9ee5a4a`, `3d57293`, `fe4ca9b`, `a601f4c` + commit tài liệu đợt này. `main` vượt origin 34+ |
| Promote model | BLOCKED | WAPE 0,805 > 0,6. Cần quy tắc promote hoặc quyết định ngoại lệ |
| customer_id trên production | OFF | Phần 5 (lưu ý nạp lại toàn bộ) |
| Duy trì quy tắc 6 khóa | Ghi nhận | Nạp lại các ngày 09/02, 10/02, 02/03, 26/08 thì chặn tới khi đối chiếu lại. Khóa nhiều listing mới vẫn chặn |
| Ghi chú review | Ghi nhận | N2: nhật ký `OPEN_HOURS_OVERRIDE_APPLIED` ghi lúc bắt đầu, nên một lần huấn luyện thất bại về sau vẫn có dòng này (trạng thái lần chạy là nguồn sự thật). N3: data identity băm dữ liệu lưu, giá trị quy tắc nằm trong bản ghi lần chạy. N4: lần chạy 1.2.12 dựng lại bằng 1.2.11 sẽ thiếu 6 giá trị (xuất điểm backtest báo lệch; forecast không ảnh hưởng) |
| Bộ nhớ máy | Rủi ro vận hành | Commit RAM khoảng 88-95 % (trình duyệt, Excel, VS Code; một tiến trình python từ 14/10 giữ 4,2 GB, không rõ nguồn, không chạm tới). Huấn luyện production cần khoảng 3 GB trống |

## 9. Git và phạm vi thay đổi

**Commit:** `fe4ca9b` + `a601f4c`, cộng commit tài liệu `24590d2` (CHECKPOINT). **Chưa push** (`main` vượt origin 35, sau 0).
Cây làm việc sạch.

**File thay đổi:**
- Mã:
  - `backend/app/data/open_hours_override.py` (mới);
  - `open_hours.py`;
  - `demand.py`;
  - `ml/pipeline.py`;
  - `ml/feature_registry.py`;
  - `data_checks.py`.
- UI: `components/ui.tsx`, `pages/ForecastHistory.tsx`, `pages/ShapTrace.tsx`.
- Test: 3 file mới, 5 file frontend cập nhật kỳ vọng.
- Phiên bản 1.2.12.
- Tài liệu: CHANGELOG, `docs/BIGQUERY.md` 11f, `docs/data/DATA-MODEL.md`.

**Không đổi:**
- lịch D-0 / D-1 / huấn luyện / EOD / close;
- mục tiêu `demand_quantity`, Price ON, customer_id OFF, horizon;
- `storage.json`, nguồn đang dùng, IAM, BigQuery (chỉ đọc);
- trạng thái promote của model đang dùng.

Không push, không đổi hạ tầng hay tài khoản nhà cung cấp, không mở endpoint công khai.

## 10. Hiện vật

| Hiện vật | Vị trí | SHA-256 |
|---|---|---|
| Báo cáo | `FINAL_REPORT.md`, `TEST_RESULTS.md`, `DATA_RECONCILIATION.md`, `RESUME_CHECKPOINT.md` | - |
| Bằng chứng 6 khóa | `OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx` (12 sheet, thêm `Recheck_2026-10-22`, `Gate_copy_2026-10-22` ngày 22/10) | 594792F0C42BEED966580B82392D22E476662C4CBFEBE48625A260D14B73C2C8 |
| Huấn luyện / forecast / weekday / customer / D-1 22/10 | `TRAINING_FORECAST_REPORT.xlsx` (21 sheet, thêm `Status_2026-10-22`, `D1_2026-10-22`, `Source_drift_2026-10-22`, `Finalized_vs_now_2026-10-22`) | 4AFBC971984CB42836D4557EC55E75364D8583A0AA40D96F3210AF4F5A318D1D |
| Backup xác minh 22/10 (trước deploy) | `backups\backup-20261022-111140-manual.zip` | A3564E18EBAEC29953334EFBC3BDF4F2EA72AD9EF1034F3345E84B865866AFD6 |
| Checkpoint 22/10 (báo cáo + script / kết quả lượt 22/10) | `checkpoints\checkpoint-20261022-release1212-deploy-denied2-r2.zip`. Thay cho `…-deploy-denied2.zip` (BA52746B…D68D); hai bản chỉ khác giờ ghi trong báo cáo | xem file `.sha256` cùng tên |
| Model candidate | `candidate\MV-20261022-003132-8EB8.txt` (+ `.json`) | 3073A16FD147F5A9CAE19CD884DA67D6315F559370BC6268947D11AF77747D7D |
| Forecast candidate (15 ngày) | `candidate\candidate_forecast_FCR-20261021173318-869CF1_15d.xlsx` / `…_15d.csv.gz` | ADB11510…C33B / 32D11B02…AC06 |
| Gói | `dist\DemandForecast-1.2.12-win64-portable.zip` | 10BF50BF…4C05 |
| Backup xác minh | `backups\backup-20261022-000431-manual.zip` | ED0F8EC6…E7A7 |
| Checkpoint trước / sau | `checkpoints\checkpoint-20261021-release1212-prerelease.zip` / `…-after.zip` | F7AF84DB…5647 / xem `RESUME_CHECKPOINT.md` |
