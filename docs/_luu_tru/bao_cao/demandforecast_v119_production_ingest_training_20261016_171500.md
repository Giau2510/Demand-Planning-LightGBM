# Phát hành 1.1.9, nạp BigQuery production và huấn luyện trên dữ liệu thật

16/10/2026, 16:10–17:15 (giờ Việt Nam). Người dùng đã cho phép: commit/push, phát hành 1.1.9, nâng cấp, chuyển nguồn sang
BIGQUERY, ghi dữ liệu thật và huấn luyện.

## Kết luận

| Phần | Kết quả |
|---|---|
| Phát hành 1.1.9 và nâng cấp | **ĐẠT** |
| Đọc BigQuery thật, ghi dữ liệu thật vào DB, đối soát | **ĐẠT** |
| Huấn luyện trên dữ liệu thật | **ĐÃ CHẠY**; model mới **bị từ chối** bởi quality gate hiện có, không kích hoạt |
| Dự báo cho nguồn BIGQUERY | chưa có (không có model đang dùng) |
| Khôi phục D-0 | **chưa được**: app từ chối vì SQL D-0 cho BigQuery chưa được xác nhận |

Trạng thái theo AGENTS.md: dữ liệu và ứng dụng sẵn sàng; còn chờ người dùng quyết định về model (bị từ chối) và về các
lịch BigQuery (D-0, D-1).

## 1. Commit, push, gói

| Hạng mục | Giá trị |
|---|---|
| Commit phát hành | `9066427c63ba1ba2a6c81070f2dbfe17aa75535b` (nhánh `main`) |
| Nội dung commit | 43 file theo đường dẫn tường minh: 37 mục đã duyệt, trong đó thư mục `scripts/vps/` gồm 7 file |
| Quét secret | 0 khớp mạnh; email chỉ là placeholder trong test |
| Push | `main` `d87c315..9066427` OK; tag `v1.1.9` đã push. Không force-push |
| Checkpoint trước commit | `checkpoints/source-1.1.9-precommit-20261016-161233.zip`: status, diff, file mới; SHA-256 `0145A702…3871` |
| Gói | `dist/DemandForecast-1.1.9-win64-portable.zip` (87,8 MB) |
| SHA-256 gói | `F8311492670BE5293299E6980C74675B9011F3443138721ED4D5B12E0224DD46` |
| Định danh gói | `BUILD-INFO`: commit `9066427`, `dirty=False`, dấu vân tay nguồn `941BCFAB17A18D23` |
| Gói cũ | 1.1.8 và 1.1.6 giữ nguyên; kế hoạch dọn chỉ chạy thử, không xóa gì |

Commit tài liệu sau phát hành: xem mục 12.

## 2. QA

Chạy trên commit phát hành, qua `scripts/release.ps1` với `DF_REAL_BQ=1`.

| Loại | Kết quả |
|---|---|
| Backend (unit, integration với fake, và 2 test BigQuery thật dữ liệu nội tuyến) | **302 đạt**, 0 bỏ qua |
| Frontend vitest | **61/61** |
| Typecheck / build | đạt / đạt |
| Lint | chưa cấu hình |

Log: `logs/development/tests_20261016_161610.log`.

## 3. Ứng dụng đang chạy

- **1.1.9**, pid 29728, chạy từ `%LOCALAPPDATA%\Programs\DemandForecast\1.1.9\python\python.exe`. Chỉ một instance;
  `current.txt` = 1.1.9.
- `/api/health` ok; UI HTTP 200.
- Nâng cấp 16:27–16:37 bằng `deploy-upgrade.ps1`: precheck OK, xác nhận `UPGRADE-1.1.9`, không cần migration (schema 3).
  Log: `logs/runtime/deploy-20261016-162709.log`.
- DB vẫn ở `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`; `storage.json` không đổi (`8D79DBDD…`).
- Rollback: `scripts\rollback-version.ps1 -To 1.1.8`, hoặc `-To 1.1.6`.

## 4. BigQuery

Đọc thật, chỉ đọc, từ app 1.1.9 trên dữ liệu thật; mọi truy vấn đều dry-run trước và giới hạn 20 GiB.

| Bước | Kết quả |
|---|---|
| Ánh xạ | Gợi ý → kiểm tra → lưu, như trên giao diện. 15 cột (5 trường + 10 tham chiếu); `created_date` là ngày nghiệp vụ (DATE); không so sánh `seller_class`, `refresh_time` |
| 6 cổng truy cập | **PASS**: ADC, API/dataset, vùng `asia-southeast1`, metadata, query job, schema mapping |
| Kết nối | `TABLE` không phân vùng, 8.893.414 dòng |
| 30 ngày | đạt |
| Toàn kỳ | đạt; đối soát đọc = hợp lệ |
| Cảnh báo toàn kỳ (không chặn) | `KEY_NOT_UNIQUE`: 7.211 dòng, cộng theo `SUM_ALL` |
| | `MISSING_DAYS`: chỉ ngày 16/10, tức hôm nay, không thuộc lịch sử |
| | `TARGET_OUTLIER`: max 71.834, p99 40; không lọc |
| *Kiểm tra trùng & thử tổng hợp (không ghi)* | **READY** |
| Phạm vi nguồn | 01/01–15/10/2026 |
| Ngày 15/10 | 18.992 dòng; TB 7 ngày trước 18.772 → đủ dữ liệu |
| Chốt trùng hoàn toàn | 0 nhóm / 0 dòng trên 8.893.414 dòng |
| Tổng hợp | 1.347.346 dòng ngày × SKU × FC; tổng 41.722.635 = tổng nguồn; 0 dòng bị loại |

## 5. Ghi dữ liệu thật và đối soát

- Trước khi ghi: tắt D-0; tạo backup `backups/backup-20261016-164254-manual.zip` và kiểm tra nó (integrity ok, số dòng
  khớp DB). Sau đó bật chế độ sản xuất, chuyển nguồn sang **BIGQUERY**, rồi chạy D-1 bằng *Chạy ngay*.
- Mọi thao tác qua API của app. Không ghi DB bằng script ngoài.

| Lần | Job | Phạm vi | Đọc | Ghi |
|---|---|---|---|---|
| 1 (nạp lại toàn kỳ) | `JOB-20261016094316-E3A4B7`, 6,4 phút | 01/01–15/10 | 8.893.414 dòng, 41.722.635 | 1.347.346 mới |
| 2 (chạy lại) | `JOB-20261016095109-511472` | 12/10–15/10 | 80.817 dòng, 362.367 | 13.345 **không đổi**; 0 mới / sửa / xóa |

Đối soát với truy vấn BigQuery độc lập theo từng ngày (DB mở chỉ đọc), làm cả sau lần 1 và sau lần 2:
- **288/288 ngày khớp** cả số dòng ngày × SKU × FC lẫn tổng demand;
- tổng 1.347.346 / 41.722.635, không đổi sau khi chạy lại;
- 9.661 SKU, 2 FC (BD, HN), 0 khóa lặp;
- `quick_check` ok; `data-check`: mọi kiểm tra OK, trừ WARN cũ `forecast_series_meta` của lần dự báo DEMO 14/10;
- dữ liệu DEMO giữ nguyên: 38.568 dòng / 1.014.720.

| `demand_daily` | Trước | Sau |
|---|---|---|
| Số dòng | 38.568 | 1.385.914 |
| Tổng | 1.014.720 | 42.737.355 |

## 6. Dữ liệu dùng để huấn luyện

Nguồn **BIGQUERY** (scope `BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`), 01/01–15/10/2026.
- 288 ngày liên tục, không thiếu ngày; **17.137 chuỗi SKU × FC**.
- Số ngày có đơn của mỗi chuỗi: trung vị 46. Chỉ 27,3 % ô (chuỗi × ngày) có đơn.
- Demand/ngày/chuỗi: trung vị 6, p99 409, max 71.947.

**Nhu cầu giảm mạnh theo thời gian:**

| Tháng | Đơn vị/ngày |
|---|---|
| 01–06 | ≈ 150–200 nghìn |
| 07 | ≈ 136 nghìn |
| 08 | ≈ 109 nghìn |
| 09 | ≈ 86 nghìn |
| 10 | ≈ 80 nghìn |

Số chuỗi-ngày giảm tương ứng. Tôi không xác định được đây là thay đổi kinh doanh thật hay thay đổi của bảng nguồn.

## 7. Huấn luyện và backtest

- Pipeline của app (`POST /api/training/run`, job `JOB-20261016095355-8A6423`, 10,3 phút), cấu hình hiện có, không đổi
  tham số: tweedie, 300 vòng, horizon 7/15.
- Training run `TRN-20261016095451-697A11`.
- Walk-forward 30 ngày, cấu hình 12 fold. **7 fold được đánh giá** (20/03–15/10, 210 ngày). 5 fold đầu bị bỏ vì chưa đủ
  56 ngày lịch sử.
- 3.353.298 điểm backtest.

| Chỉ số (pooled) | Model | Baseline của app |
|---|---|---|
| WAPE | **1,017** | 0,839 |
| Bias | **+0,399** (dự báo cao hơn thực tế 40 %) | +0,119 |
| MAE | 8,50 | 7,01 |

- WAPE theo fold: 1,11 / 0,98 / 0,81 / 0,86 / 1,03 / **1,56** (17/08–15/09) / 1,02. Bias dương ở mọi fold. Nguyên nhân
  khớp với mức nhu cầu giảm ở mục 6.
- Riêng phần LightGBM: WAPE 1,00, bias +0,42.
- Feature quan trọng nhất: `roll_mean_7`, `roll_mean_14`, `roll_mean_56`, `lag_1`.

## 8. Model

- Quality gate hiện có (ngưỡng mẫu, chưa được kinh doanh phê duyệt): WAPE ≤ 0,60, |bias| ≤ 0,20.
- Kết quả: **REJECTED (`QUALITY_GATE_FAILED`)**, không lưu file model, không phát hành, không ép phát hành, không đổi ngưỡng.
- Phạm vi BIGQUERY **chưa có model đang dùng**, nên chưa có dự báo cho nguồn đang chọn.
- Model DEMO `MV-20261016-143246-6555` vẫn thuộc phạm vi DEMO, không bị động tới.
- Không tạo được dự báo từ model mới vì không có model được chấp nhận: bước kiểm tra tạo dự báo **NOT RUN**.

## 9. Trạng thái cuối

| Hạng mục | Trước batch | Sau batch |
|---|---|---|
| Nguồn | DEMO | **BIGQUERY** (sản xuất bật) |
| D-0 | ON (08–18, mỗi 2 giờ) | **OFF**, giờ giữ nguyên |
| D-1 | OFF | OFF (không tự bật) |
| Huấn luyện 07:00 | ON | ON nhưng **không sẵn sàng** (`TRAIN_WAITS_FOR_D1`) |

- D-0: app từ chối bật lại (`FLOW_NOT_READY: SQL_NOT_VALIDATED`), vì trên BigQuery D-0 cần SQL D-0 đã được xác nhận.
- Hệ quả: **hiện không có job tự động nào chạy**, và dữ liệu BigQuery chỉ được cập nhật khi chạy D-1 thủ công.
- Scheduler chạy; không có job đang chạy hay trùng.

## 10. Backup (trong `D:\Buymed\Lightgbm AI\backups`)

| File | Tạo lúc | Kiểm tra |
|---|---|---|
| `backup-20261016-162709-manual.zip` (SHA `F9FA1731…5A23`) | trước nâng cấp, bởi script deploy | integrity ok, khớp DB |
| `backup-20261016-162940-cli.zip` | trong lúc nâng cấp, bởi script deploy | — |
| `backup-20261016-164254-manual.zip` (SHA `C9D61E5E…115F`) | trước khi chuyển nguồn | integrity ok, khớp DB, đã có ánh xạ |

Cấu hình trước khi chuyển nguồn: `reports/config_before_bq_switch_20261016-161233.json`.

Không backup nào bị xóa hay sửa. Model, `storage.json`, cấu hình và checkpoint không đổi.

## 11. Pass / fail / chưa chạy

| Hạng mục | Trạng thái |
|---|---|
| QA, build, nâng cấp, health | PASS |
| Đọc BigQuery, ghi DB, đối soát, chạy lại không nhân đôi | PASS |
| Huấn luyện | chạy xong, model **FAIL quality gate** |
| Kích hoạt model mới, tạo dự báo trên dữ liệu thật | NOT RUN (model bị từ chối) |
| Khôi phục D-0 | NOT DONE (app chặn, cần SQL D-0 đã xác nhận) |
| D-0 BigQuery | chưa kiểm chứng |
| VPS | không triển khai |

**Người dùng cần quyết định:**
1. Mức nhu cầu giảm khoảng 50 % từ tháng 7 là thật hay do bảng nguồn? Xác nhận với chủ dữ liệu.
2. Model:
   - xem lại tiêu chí chất lượng (ngưỡng hiện tại chỉ là ví dụ);
   - hoặc cho phép điều chỉnh mô hình/phạm vi huấn luyện (ví dụ cửa sổ dữ liệu ngắn hơn) trong một đợt riêng;
   - không ép phát hành model hiện tại.
3. Lịch:
   - bật D-1, với giờ chạy sau khi nguồn làm mới (khoảng trưa D+1), để dữ liệu và huấn luyện hằng ngày chạy;
   - D-0 trên BigQuery cần xác nhận SQL D-0 ở trang **SQL nguồn** trước khi bật.
4. Muốn quay lại DEMO: trang BigQuery → *Tắt chế độ sản xuất* (nguồn tự về DEMO); dữ liệu BigQuery đã nạp vẫn được giữ.

## 12. Truy vết

- Báo cáo QA: `logs/development/tests_20261016_161610.log`. Log deploy: `logs/runtime/deploy-20261016-162709.log`.
- Job: `JOB-20261016094316-E3A4B7`, `JOB-20261016095109-511472` (D-1); `JOB-20261016095355-8A6423` (huấn luyện).
- Kết quả trung gian (scratchpad của phiên, tạm thời):
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseC_checks_119.txt`
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseD_switch_119.txt`
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseD_d1_run1_119.txt`
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseD_d1_run2_119.txt`
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\recon119_run1.json` (đối soát từng ngày)
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\recon119_run2.json` (đối soát từng ngày)
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseE_train_119.txt`
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseE_train_detail_119.txt`
  - `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\phaseF_schedules_119.txt`
- Commit tài liệu sau phát hành: `72d7671` (`CHANGELOG.md`, `docs/BIGQUERY.md`, `docs/CHECKPOINT.md`), đã push. Chỉ tài
  liệu, không có trong gói.
