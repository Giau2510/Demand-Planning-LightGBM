# Đối soát dữ liệu - release 1.2.12 (21-22/10/2026)

Mọi truy vấn BigQuery đều chỉ đọc (dry run trước, có giới hạn byte, không DML/DDL). Mọi đối soát chạy trên bản sao DB (backup
API, nguồn mở `mode=ro`). Báo cáo không chứa `customer_id` thô.

## 1. Nguồn và độ mới

- Bảng: `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`.
- Sửa lần cuối 2026-10-21 00:10:38 UTC (07:10:38 giờ Việt Nam), 8.979.752 dòng.
- Ngày lớn nhất 2026-10-20 (18.208 dòng); ngày 21/10: 0 dòng lúc 21:20.
- Mọi lần đọc trong đợt này cùng một bản: `same_snapshot = true` ở cả `bq_six` và `cust_bq`.
- **D-1:** lần cuối là `JOB-20261021111824-17023B` (Run now, 18:18-18:20 ngày 21/10), SUCCEEDED, 0 thay đổi, cửa sổ
  17/10-20/10. Từ đó không có D-1 hay backfill nào.
  - Dữ liệu đã đối soát khớp nguồn (mục 2), nên **không** chạy lại D-1 / backfill: không cần thiết, theo yêu cầu.
  - D-1 theo lịch 22/10 06:00 sẽ nạp 21/10. Việc đó ngoài phạm vi release.

## 2. Dữ liệu huấn luyện = nguồn

- Bản sao production lúc 21:53 ngày 21/10 (`p29\x`), so với tổng hợp nguồn độc lập của cùng bản 07:10:38 (`recon_d1.py`).
- Cửa sổ 2026-01-01..2026-10-20.

| Chỉ số | Nguồn | Ứng dụng |
|---|---:|---:|
| Khóa ngày × SKU × FC | 1.360.913 | 1.360.913 |
| Số lượng | 42.088.223 | 42.088.223 |
| Dòng nguồn | 8.979.752 | - |
| Khóa mới / bị loại / đổi số lượng | - | 0 / 0 / 0 |
| `n_orders` khác | - | 0 |
| Trạng thái giờ mở bán (theo quy tắc nguồn / đang lưu) | OK 1.360.907, MULTI_ITEM 6 | OK 1.360.907, MULTI_ITEM 6 |

- Kết quả: `match = true`.
- Bản sao dùng để huấn luyện candidate (`p29\t`, 00:06 ngày 22/10, sau job 23:55 và 23:59) có cùng 1.360.913 dòng /
  42.088.223 đơn vị, hash từng dòng `b037cc39dea09550…` giống bản 21:53.
- 293 ngày đã chốt đến 20/10.
- **Không loại dòng nào khỏi đầu vào:**
  - quy tắc cửa sổ `WINDOW_START`, nên mọi dòng của cửa sổ là đầu vào;
  - series dự phòng (không hoạt động / gián đoạn / mới) vẫn được dự báo theo quy tắc dự phòng và vẫn được chấm trong
    backtest;
  - không có cờ chất lượng nào làm bỏ dòng.

## 3. Sáu khóa và quy tắc MAX đã duyệt

| Khóa | Ngày | FC | SKU | Dòng | Đơn | Số lượng | Listing 1 | Listing 2 | MAX |
|---|---|---|---|---:|---:|---:|---|---|---:|
| K1 | 2026-02-09 | HN | MEDX.DMTS-HOA-BAO-002 | 4 | 4 | 8 | .1 = 23,92 | .2 = 24 | **24** |
| K2 | 2026-02-10 | HN | MEDX.2LJ61PGE | 2 | 2 | 11 | .1 = 21,16 | .3 = 24 | **24** |
| K3 | 2026-03-02 | BD | MEDX.DMTS-STA-LOS-002 | 18 | 18 | 88 | .1 = 5,0 | .2 = 24 | **24** |
| K4 | 2026-03-02 | BD | MEDX.SOP-NEO-001 | 3 | 3 | 3 | .1 = 1,7 | .2 = 24 | **24** |
| K5 | 2026-08-26 | BD | MEDX.COU-STR-001 | 8 | 8 | 42 | .1 = 23,72 | .2 = 24 | **24** |
| K6 | 2026-08-26 | BD | MEDX.D6TABCV8 | 4 | 4 | 4 | .1 = 22,85 | .2 = 18,22 | **22,85** |

**Kiểm tra giá trị listing:**
- 12 / 12 giá trị có mặt, là số, hữu hạn, trong 0..24.
- Mỗi listing đúng một giá trị trong ngày; không dòng nào thiếu giờ hay thiếu item_code.
- Trạng thái đơn: COMPLETED (K5 .1 có thêm DELIVERED).

**Đối chiếu dòng lưu:**
- Số lượng và số đơn trùng nguồn ở cả 6 khóa.
- Dòng lưu là `MULTI_ITEM`, `open_hours` NULL, `loaded_at` 2026-10-21T05:36:47Z (backfill `JOB-20261021052939-2D9CCE`, đọc
  đúng bản 07:10:38).

**Trước / sau** (khóa nào được phủ chỉ quyết định khi đọc, dữ liệu lưu không đổi):

| Nơi | Quy tắc | Dòng | OK | Phủ bởi quy tắc | Không OK | Cổng huấn luyện |
|---|---|---:|---:|---:|---|---|
| Bản sao production | 1.2.11 | 1.360.913 | 1.360.907 | 0 | MULTI_ITEM 6 (09/02-26/08) | `OPEN_HOURS_INVALID` |
| Bản sao production | 1.2.12 | 1.360.913 | 1.360.907 | 6 | không còn | mở |
| Production (vẫn 1.2.11, 00:06 ngày 22/10) | 1.2.11 | 1.360.913 | 1.360.907 | 0 | MULTI_ITEM 6 | `OPEN_HOURS_INVALID` |
| Diễn tập r13, sau rollback 1.2.11 | 1.2.11 | - | - | 0 | MULTI_ITEM 6 | `OPEN_HOURS_INVALID` (đảo ngược được) |

- `demand_daily` trước = sau khi kiểm (cùng số dòng, cùng SHA-256).
- Data-check của bản sao: không FAIL. 5 kiểm tra giờ mở bán OK, trong đó `open_hours_window_ready` và
  `open_hours_owner_override`. Trạng thái tổng WARN đã có từ trước (`forecast_series_meta`).
- Không phát hiện lỗi dữ liệu mới. Hai lần bấm huấn luyện trên production 1.2.11 (không phải Claude) đều dừng ở cổng
  `OPEN_HOURS_INVALID`, không ghi gì:
  - 16:35 ngày 21/10, `JOB-20261021093556-37D600`;
  - 21:23 ngày 21/10, `JOB-20261021142345-C21767`.

## 4. customer_id (chỉ đánh giá offline)

- **Cột:** `customer_id` INTEGER.
- **01/01-20/10:** 8.979.752 dòng, 0 NULL, 0 rỗng.
- **Quy mô:** 35.075 khách hàng, 971.340 đơn.
- **Có ở mọi ngày:** khách hàng có dữ liệu từ 01/01 đến 20/10.
- **Không phải khóa đơn hàng:**
  - 0 đơn có nhiều khách (mỗi đơn đúng 1 khách);
  - 33.110 / 35.075 khách có nhiều đơn (trung vị 16, tối đa 12.822).

| Tháng | Dòng | Khách | Đơn | Khóa ngày × SKU × FC (có khách / tất cả) |
|---|---:|---:|---:|---|
| 01 | 1.236.672 | 26.358 | 114.547 | 169.563 / 169.563 |
| 02 | 974.851 | 24.940 | 83.327 | 130.843 / 130.843 |
| 03 | 1.194.879 | 26.596 | 116.488 | 168.802 / 168.802 |
| 04 | 966.411 | 25.201 | 101.000 | 148.537 / 148.537 |
| 05 | 1.026.713 | 25.434 | 105.522 | 155.294 / 155.294 |
| 06 | 996.749 | 25.410 | 102.964 | 152.089 / 152.089 |
| 07 | 955.214 | 25.325 | 104.085 | 158.312 / 158.312 |
| 08 | 735.332 | 24.554 | 94.479 | 130.510 / 130.510 |
| 09 | 519.122 | 23.834 | 86.850 | 84.064 / 84.064 |
| 10 (đến 20) | 373.809 | 21.633 | 62.078 | 62.899 / 62.899 |

**Tổng hợp theo SQL của chính ứng dụng** (`connector._customer_ctes`, đúng cái D-1 sẽ lưu nếu ánh xạ cột khách hàng):
- 1.360.913 khóa, khớp 100 % số dòng và số lượng của dữ liệu huấn luyện; 0 khóa thừa.
- Định danh không rời BigQuery: chỉ đếm theo ngày × SKU × FC (khách phân biệt, khách quay lại trong 90 ngày, tổng số ngày
  từ lần mua trước).
- Cài đặt production **không đổi**: `customer_id_column` rỗng, `feature_customer` false.

## 5. Cập nhật 22/10/2026 - D-1 ngày 21/10, kiểm trước deploy

Mọi truy vấn BigQuery chỉ đọc (dry run trước, giới hạn 2 GiB). Đối soát chạy trên bản sao DB lấy lúc 10:57:59 ngày 22/10
(backup API, nguồn `mode=ro`), sau mọi job D-1 và huấn luyện của sáng nay.

### 5.1 Các job

| Job | Kích hoạt | Kết quả | Chi tiết |
|---|---|---|---|
| `JOB-20261021235733-F4FE52` (lịch 06:00) | lịch | FAILED `SOURCE_INCOMPLETE` 4 / 4 | Máy thức 06:57. Bốn lần thử 06:57-07:06, lần nào nguồn cũng có 0 dòng ngày 21/10 (trung bình 7 ngày trước 18.568, cần ≥ 50 %) |
| `JOB-20261022001433-6BAF6C` (07:14-07:16) | chạy tay (người vận hành, không phải Claude) | **SUCCEEDED** | Watermark **21/10**, cửa sổ 17/10-21/10, `FALLBACK_TIME_VERIFIED`. 91.282 dòng, 389.353 đơn vị. 15.136 khóa: mới 3.151 (ngày 21/10), cập nhật 123, giữ nguyên 11.862, xóa 10. Load `D1L-20261022001458-70B94F` |
| `JOB-20261022002057-3545EE` (07:20-07:22) | chạy tay | SUCCEEDED | Cửa sổ 18/10-21/10, 74.732 dòng, 321.303 đơn vị, 12.171 khóa, **0 thay đổi** (chạy lại không đổi gì) |
| `JOB-20261022001636-B06CF0` (huấn luyện lịch 07:00, chạy 07:16) | lịch | FAILED `OPEN_HOURS_INVALID` | Cửa sổ 01/01-21/10, 1.364.054 dòng, 6 `MULTI_ITEM`: đúng 6 khóa đã duyệt, vì production vẫn 1.2.11 |

- **Ánh xạ và trùng:**
  - mapping hash không đổi (`bc5fcb06327569fb`);
  - 0 dòng trùng tuyệt đối, 0 dòng bị loại;
  - 312-339 dòng trùng khóa được cộng dồn theo chính sách `SUM_ALL`, như mọi ngày.
- **Giờ mở bán:** mọi khóa vừa ghi đều OK. 10 dòng bị xóa (17-20/10) là khóa nguồn đã bỏ, không phải mất giờ mở bán.
- **D-1 theo lịch:** 5 / 5 lần từ 18/10 đều `SOURCE_INCOMPLETE` (18, 19, 20, 21 và 22/10). Ngày nào người vận hành cũng phải chạy
  tay sau khi nguồn làm mới.

### 5.2 Nguồn

- Bảng sửa lần cuối 2026-10-22 00:10:45 UTC (07:10:45 giờ Việt Nam), 9.000.299 dòng.
- Ngày lớn nhất 21/10 (19.266 dòng); ngày 22/10: 0 dòng.
- Đọc nhất quán một bản: `same_snapshot = true`.

### 5.3 Cửa sổ D-1 (17/10-21/10): khớp tuyệt đối

| Ngày | Khóa (nguồn = ứng dụng) | Đơn vị (nguồn = ứng dụng) | Dòng nguồn |
|---|---:|---:|---:|
| 17/10 | 2.965 | 68.050 | 16.550 |
| 18/10 | 2.661 | 57.312 | 15.619 |
| 19/10 | 3.326 | 89.512 | 21.650 |
| 20/10 | 3.033 | 78.232 | 18.197 |
| 21/10 | 3.151 | 96.247 | 19.266 |

Tổng 15.136 khóa, 389.353 đơn vị, 91.282 dòng: đúng các số job D-1 lúc 07:14 báo. **Ngày dữ liệu mới nhất: 21/10/2026.**

### 5.4 Toàn cửa sổ 01/01-21/10: nguồn đã sửa lịch sử (không chặn)

| Chỉ số | Nguồn | Ứng dụng |
|---|---:|---:|
| Khóa ngày × SKU × FC | 1.363.690 | 1.364.054 |
| Đơn vị | 42.185.357 | 42.184.054 |
| Dòng nguồn | 9.000.299 | - |

**Khác biệt:**
- 214 khóa chỉ có ở nguồn (+8.092 đơn vị);
- 578 khóa chỉ có ở ứng dụng (−6.600);
- 49 khóa đổi số lượng (−189); 71 khóa đổi số đơn;
- ròng +1.303 đơn vị (0,003 %); 841 khóa (0,06 %).

**Vị trí:** 238 ngày từ 01/01 đến 16/10, **không** ngày nào trong cửa sổ D-1.

**Tập trung ở vài SKU:**
- khóa mới thuộc 3 SKU (`MEDX.CRE-ROS-001` có 208 khóa);
- khóa bị bỏ thuộc 9 SKU (`MEDX.RIS-DNP-002` 215, `MEDX.HUY-JUI-001` 195, `MEDX.DAN-TAD-001` 67, …);
- 171 / 214 khóa mới cùng ngày × FC với một khóa bị bỏ. Có thể nguồn đã gán lại mã SKU cho đơn cũ; cần nhóm dữ liệu xác nhận.

**Nguyên nhân:**
- bản làm mới 07:10 ngày 22/10 đã sửa dữ liệu cũ (bản 07:10 ngày 21/10 vẫn khớp tuyệt đối 1.360.913 khóa, mục 2);
- D-1 chỉ đọc lại cửa sổ gần (`late_data_lookback_days` = 3), nên thay đổi cũ hơn không được nạp. Đây là thiết kế hiện có.

**Xử lý:**
- **Không backfill**: theo yêu cầu, và không cần cho huấn luyện vì chỉ 0,003 % đơn vị.
- Danh sách đầy đủ: `TRAINING_FORECAST_REPORT.xlsx`, sheet `Source_drift_2026-10-22`.
- Cần chủ hệ thống quyết định: backfill có chủ đích, hoặc backfill định kỳ.

**Giờ mở bán:**
- nguồn (theo quy tắc): OK 1.363.684, `MULTI_ITEM` 6;
- đang lưu: OK 1.364.048, `MULTI_ITEM` 6;
- 0 khóa chung bị lệch.

### 5.5 Ngày đã chốt (finalized)

- 294 ngày FINALIZED (01/01-21/10).
- 21/10 chốt từ `D1L-20261022001458-70B94F`: 3.151 khóa / 96.247 đơn vị = nguồn.
- 4 ngày được chốt trước khi có sửa trong cửa sổ D-1, nên khác dữ liệu đang lưu (ở các ngày này ứng dụng = nguồn):

| Ngày | Đã chốt (khóa / đơn vị) | Hiện tại (khóa / đơn vị) | Lệch đơn vị |
|---|---|---|---:|
| 17/10 | 2.966 / 68.054 | 2.965 / 68.050 | −4 |
| 18/10 | 2.661 / 57.340 | 2.661 / 57.312 | −28 |
| 19/10 | 3.331 / 89.862 | 3.326 / 89.512 | −350 |
| 20/10 | 3.037 / 78.266 | 3.033 / 78.232 | −34 |

- Thêm 238 ngày khác bản nguồn hôm nay, do nguồn sửa lịch sử (mục 5.4).
- Đúng thiết kế 1.2.9 (quy tắc của chủ hệ thống, 20/10): ngày được chốt từ lần D-1 đầu tiên sau khi hết ngày và không sửa sau
  đó.
- Chỉ ảnh hưởng lịch sử forecast - thực tế / KPI; không ảnh hưởng huấn luyện (dùng `demand_daily`).
- Danh sách: sheet `Finalized_vs_now_2026-10-22`.

### 5.6 Sáu khóa và cổng 1.2.12

- **Sáu khóa trên bản nguồn 07:10:45 ngày 22/10:**
  - giống hệt bản đã duyệt ở mức khóa (số lượng, số dòng, số đơn) và từng listing (12 / 12 giá trị);
  - MAX không đổi: 24, 24, 24, 24, 24, 22,85;
  - không có khóa nhiều listing nào khác bị lệch giờ;
  - vì vậy không cần tính lại giờ listing.
- **Dòng lưu không đổi** (`MULTI_ITEM`, `loaded_at` 2026-10-21T05:36:47Z): D-1 hôm nay chỉ ghi 17/10-21/10.
- **Cổng trên bản sao 10:57** (dữ liệu đến 21/10, mã 1.2.12):
  - 1.2.11: chặn 6 dòng;
  - 1.2.12: mở, phủ đúng 6 dòng, `not_ok` rỗng;
  - `demand_daily` không đổi (1.364.054 dòng, hash `a653b6a2…1895`);
  - data-check giờ mở bán 5 / 5 OK.
- **Data-check của production 1.2.11** (chỉ đọc, trước deploy): 0 FAIL, 30 / 32 OK. Hai WARN:
  - `open_hours_window_ready`: 6 dòng, đúng 6 khóa;
  - `forecast_series_meta`: đã có từ trước.
- Bằng chứng: `OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx`, sheet `Recheck_2026-10-22` và `Gate_copy_2026-10-22`.

### 5.7 Kết luận

D-1 SUCCEEDED. Đối soát cửa sổ D-1 đạt và dữ liệu đến 21/10 đã sẵn sàng. Không có blocker mới:
- `SOURCE_INCOMPLETE` của job theo lịch đã được người vận hành chạy tay khắc phục;
- không có lỗi mapping;
- không có dòng trùng.

Đủ điều kiện deploy. Chênh lệch lịch sử ở mục 5.4 được ghi nhận, không xử lý.
