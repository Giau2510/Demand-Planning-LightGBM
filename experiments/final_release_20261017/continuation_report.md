# Báo cáo tiếp tục 1.2.0 — 17/10/2026 08:11–08:55 (giờ Việt Nam)

Tiếp nối `final_report.md` (bản xuyên đêm). Bằng chứng nằm trong `production_20261017/` và các file log ghi bên dưới.

## A. Tổng trạng thái: `PARTIAL`

| Hạng mục | Trạng thái |
|---|---|
| App 1.2.0 trên production | **Đã deploy và xác minh** (08:13–08:18) |
| BigQuery → giá trên production | **Xong**: mapping `unit_price ← sales_price`, kiểm tra toàn kỳ, bật sản xuất, D-1 nạp lại toàn kỳ đến 16/10, độ phủ giá 99,98 % |
| Huấn luyện ứng viên có Giá trên production | **Bị chặn**: hệ thống quyền Claude Code từ chối (08:32, "Production Deploy"). Không thử lách |
| Ứng viên trên bản sao DB production mới nhất | Huấn luyện xong; inference độc lập đạt; phát hành ngoại lệ chạy trên **bản sao** |
| Phát hành model production | **Chưa**: không có ứng viên trên production. Phạm vi BIGQUERY vẫn chưa có model đang dùng |

## B. Deploy

| Mục | Giá trị |
|---|---|
| SHA-256 thực tế | `2343261C8C921AAC0B831760DEC22C029F2C52BF1783900CD142854BAC37F666`, khớp với `.sha256` và giá trị dự kiến |
| Backup | Online trước deploy: `D:\Buymed\Lightgbm AI\backups\backup-20261017-081320-manual.zip` (SHA `46E3FA7F…C827`). Lúc cài: `…\backup-20261017-081557-cli.zip`. Trước khi đổi mapping và nạp lại: `…\backup-20261017-082018-manual.zip`. Cả ba đọc được và có `db/app.db` |
| Deploy | `scripts\deploy-upgrade.ps1 … -ConfirmToken UPGRADE-1.2.0` → exit 0, "UPGRADE OK: 1.1.9 -> 1.2.0"; log `D:\Buymed\Lightgbm AI\logs\runtime\deploy-20261017-081320.log` |
| Version thực tế | `/api/health` 1.2.0, `current.txt` 1.2.0, pid 23632, cổng 8765 |
| DB / storage | Sau deploy: fingerprint DB **không đổi** (dữ liệu, run, settings); `storage.json` vẫn `8D79DBDD…`; đường dẫn DB `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`; integrity ok. `data-check` = WARN chỉ do một forecast run DEMO tạo trước migration 0003 (đã có từ trước) |
| Settings | Giống hệt trước deploy, chỉ thêm khóa mặc định mới `bigquery.d0_table_id` |
| Rollback | Còn thư mục 1.1.9 và 1.1.8. `rollback-version.ps1 -To 1.1.9 -CheckOnly` → "rollback possible without restoring the database" |

## C. BigQuery

- **Bảng (metadata thật, 08:20):**
  - D-1 `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`: 8.910.595 dòng, 17 cột, cập nhật lần cuối 08:08 ngày 17/10.
  - D-0 `…_D0`: 662 dòng, 12 cột, cập nhật lần cuối 08:08 ngày 17/10.
  - Kiểm tra bảng trên production: cả hai PASSED.
- **Ngày cuối:** D-1 có đến **16/10** (18.912 dòng, tổng 92.866, 2.424 SKU, 2 FC). D-0 chỉ có 17/10 (662 dòng).
- **Giá ở nguồn:** ngày 16/10 có 138 dòng thiếu giá; 0 dòng giá 0, 0 dòng giá âm. D-0 có 1 dòng thiếu giá.
- **Mapping** `unit_price ← sales_price`: đã lưu trên production, đọc lại khớp; các trường khác không đổi.
  - App tự tắt chế độ sản xuất khi lưu mapping.
  - Kiểm tra toàn kỳ đạt: 8.910.595 dòng / 41.808.940; 3,49 GB; 46 s; không có lỗi chặn. Ba cảnh báo đã biết:
    - `KEY_NOT_UNIQUE`: 7.348 dòng, cộng dồn theo quy tắc SUM_ALL.
    - `MISSING_DAYS`: chỉ thiếu 17/10, tức hôm nay.
    - `TARGET_OUTLIER`.
  - Mọi điều kiện kích hoạt đều đạt, nên chế độ sản xuất đã được bật lại.
- **D-1 thử khô** (chỉ đọc, 211 s, 1,27 GB): mọi bước PASSED; không ghi gì.
- **D-1 thật** `JOB-20261017012623-2A31B7` (khóa MANUAL, không đụng lịch): SUCCEEDED, 240 s, nạp lại toàn kỳ 01/01–16/10.
  - Đọc 8.910.595 dòng, ghi 1.349.388 ngày-chuỗi; 0 dòng trùng hoàn toàn.
  - Mới 3.136 (tất cả ngày 16/10, tổng 92.866).
  - Sửa 131 (09–15/10, giảm từ 47.413 xuống 45.659).
  - Không đổi 1.346.121.
  - **Mất 1.094** (rải ở mọi tháng, tổng 4.807 = 0,0115 % lịch sử, thuộc 19 SKU; 78 % trong số đó không còn trong nguồn).
  - Nguồn đã tự sửa hoặc xóa các dòng này trong lần làm mới 08:08. Trạng thái trước nằm trong backup 08:20.
- **Độ phủ giá sau khi nạp:** 99,982 % (1.349.148/1.349.388). 240 NULL và 83 giá bình quân bằng 0 được giữ nguyên, không thay bằng giá giả. 0 giá âm. Theo tháng: 99,96–100 %.
- **Tác động lên production:** chỉ ghi phạm vi BIGQUERY. DEMO giữ nguyên (38.568 dòng). Run huấn luyện và forecast không đổi. Đối chiếu chi tiết: `production_20261017/reload_diff_result.json`.

## D. Model

| Mục | Ứng viên trên **bản sao** DB production 08:3x |
|---|---|
| Run / model | `TRN-20261017013431-F2F32B` / `MV-20261017-084542-F32B`, 712 s (backtest 569 s) |
| Dữ liệu | 01/01–16/10/2026; 17.125 chuỗi; 5.201.046 dòng huấn luyện |
| Cấu hình | `feature_price = true`, DIRECT (12 mốc × 7 ngày), lags và rolling bật; fingerprint `7caa9472f4e78535` |
| `feature_groups.price` | `{switch_on: true, used: true}`, `DATA_OK`, độ phủ 0,99982 |
| Feature | 31 feature, gồm `price_last` và `price_rel_28` |
| Backtest (7 fold, 3.351.605 điểm) | **WAPE 0,807444, bias +0,057540, MAE 6,7267**. Baseline 0,843571 / +0,124355 / 7,0277 |
| Quality gate chuẩn | Trượt **chỉ** `WAPE_MAX` (0,807 > 0,60); bias đạt; đủ điều kiện ngoại lệ. Ngưỡng chuẩn không đổi |
| Inference (bản sao) | 256.875 giá trị (17.125 × 15), 0 NaN / Inf / số âm; tái lập sai khác 0,0; nạp lại giống hệt; grain không trùng; ngày 17/10–31/10 |
| Độ nhạy giá (bản sao) | Giá cuối +10 % → đổi 4.170/4.277 chuỗi LightGBM, 0 chuỗi fallback |
| Giải thích | 4 giá trị lớn nhất: OK, khớp số đã publish, DIRECT, không dùng giá trị dự báo làm đầu vào, `price_last` là đầu vào thực tế và được cây sử dụng |
| Leakage | Test đơn vị (QA 324 đạt) và kiểm tra nguồn đầu vào của phần giải thích |
| Trạng thái | **Chỉ là ứng viên trên bản sao.** Không có trên production. Phát hành ngoại lệ chỉ diễn tập trên bản sao (`FCR-20261017014610-6B8D3E`) |

## E. Các tác vụ đã chạy tay

| Tác vụ | Trạng thái | Run ID / log | Blocker |
|---|---|---|---|
| Checksum | Đạt | SHA khớp | — |
| Backup | Đạt (3 bản, đọc được) | §B | — |
| Deploy 1.2.0 | **Đạt** | `deploy-20261017-081320.log` | — |
| BigQuery D-1 | Đạt (metadata, truy vấn mới nhất, kiểm tra toàn kỳ, thử khô) | `bq_probe_0820.json` | — |
| BigQuery D-0 | Đạt (metadata, kiểm tra bảng, khoảng ngày). D-0 production **không chạy**: tắt, feed SQL chưa xác nhận, không đổi | `bq_probe_0820.json` | — |
| Mapping giá | **Đạt (production)** | settings history `bigquery` | — |
| D-1 sync | **Đạt (production)** | `JOB-20261017012623-2A31B7` | — |
| Training Price | Production: **BỊ CHẶN**. Bản sao: đạt | `train_on_copy_result.json` | Hệ thống quyền |
| Inference | Bản sao: đạt | `candidate_inference_check_result.json` | — |
| Model release | **Chưa** | — | Không có ứng viên production |
| Post-release smoke test | Chưa | — | Phụ thuộc bước trên |

## F. Các quyết định giữ nguyên

- Price bật ở mọi tầng: UI và settings production (`model` lưu tường minh), registry `DATA_OK`, ứng viên và metadata.
- Lịch D-0 không đổi: tắt, 08:00–18:00 mỗi 2 giờ. Feed D-0 của production (SQL) không bị động tới.
- D-1 03:00 (tắt) và training 09:00 (bật) không đổi.
  - Training 09:00 hôm nay **chờ** D-1 theo lịch (`TRAIN_WAITS_FOR_D1`).
  - D-1 chạy tay có khóa MANUAL nên không kích hoạt training theo lịch.
- Không push Git; chỉ commit cục bộ.
- Không lách quyền: bị từ chối khi deploy (02:34) và khi huấn luyện trên production (08:32); cả hai lần đều dừng đúng
  bước đó. Lần deploy 08:13 đã được hệ thống quyền cho phép.
- Không dùng dữ liệu giả. Không phát hành model khi thiếu ứng viên production.

## G. Tiếp tục

**Checkpoint cuối:** CP2 (BigQuery → giá) xong trên production. Đang dừng ở CP3 (huấn luyện trên production) vì bị chặn quyền.

**Để hoàn tất,** chủ dự án chọn một trong hai cách.

Cách 1 — trên giao diện (2 thao tác):
1. Bảng điều khiển → *Huấn luyện & dự báo ngay*. Mất khoảng 12 phút. Cấu hình DIRECT + Giá đã lưu sẵn.
2. Khi lần chạy bị quality gate từ chối (dự kiến WAPE khoảng 0,807), mở lần chạy đó ở trang *Chất lượng mô hình*, vào
   khung *Phát hành theo ngoại lệ quality gate* và bấm *Phát hành theo ngoại lệ*. Nhập:
   - người duyệt, lý do, ngày xem lại;
   - WAPE và bias đúng của lần chạy (3 chữ số);
   - `EXCEPTION-<mã lần chạy>`.

Cách 2 — cho phép Claude Code chạy huấn luyện và phát hành trên production (thêm quyền), rồi yêu cầu tiếp tục. Tôi sẽ:
1. huấn luyện;
2. xác nhận `feature_groups.price.used = true`;
3. backup;
4. phát hành ngoại lệ;
5. kiểm tra inference, giải thích và fingerprint.

**Hạn dữ liệu:** dữ liệu đang đến 16/10, nên còn được publish đến hết **18/10** (`max_data_lag_days` = 2). Từ 19/10 phải chạy D-1 (thủ công, vì luồng D-1 đang tắt) trước khi huấn luyện.
