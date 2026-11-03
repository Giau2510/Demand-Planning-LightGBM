# Data reconciliation - release 1.2.11 (21/10/2026)

## Phạm vi và cách đối soát

- **Nguồn:** `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`.
  - Mô tả bảng: `PIC:giau.vo`, `refresh 07h00`.
  - Một snapshot duy nhất: dựng lại **21/10/2026 07:10:38** (giờ VN), 8.979.752 dòng.
  - Metadata được kiểm lại trước / sau mỗi truy vấn và trước mỗi bước của chuỗi production: không đổi.
- **Truy vấn BigQuery:** chỉ SELECT, dry run trước, trần 2 GiB mỗi truy vấn. Tổng ~11,5 GB, gồm:
  - cổng trùng của app trên bảng thật;
  - tổng hợp nguồn toàn kỳ;
  - các danh sách bất thường;
  - bảng phân loại / trạng thái item.
- **Phía app:** bản sao DB production bằng SQLite backup API (nguồn `mode=ro`) trong scratchpad p28:
  - `dbcopy_before`: 18:17, sau deploy, trước D-1;
  - `dbcopy_after`: 18:21, sau D-1.
- **Dữ liệu khách hàng:** không có `customer_id` thô (chỉ số khách khác nhau).
- **Workbook:** `demandforecast_release_1211_anomalies_20261021.xlsx`, 13 sheet, SHA-256
  `516E659F9923AA059C0F8B66F67CD5701BD8DD34783BFEABFC1C9A5481E7B0B5`.

## 1. Hạt dữ liệu và item_code

| Kiểm chứng | Kết quả |
|---|---|
| Khóa D-1 / mô hình | `sku_code` × `fc_code` × `created_date`; FC chỉ từ `fc_code`; không có hàm chuỗi nào đọc hậu tố (test) |
| Khóa ngày × SKU × FC có > 1 `item_code` (01/01-20/10) | **101** (tháng 2: 35, tháng 3: 55, 26/08: 11) |
| Trong đó cùng một giờ mở bán | **95** → `OK` trong app; nhiều item không bao giờ tự chặn |
| Trong đó giờ khác nhau giữa các listing | **6** → `MULTI_ITEM` (giờ SKU × FC chưa có quy tắc); 101 / 101 khóa lưu đúng trạng thái kỳ vọng (sheet `Multi_Item_Keys_All`) |
| Số lượng của 101 khóa trong app = nguồn | có, cả 101 |
| Mọi bảng tiêu thụ (demand_daily, forecast_values, actual_final_values, actual_close_values, forecast_history_values, forecast_eod_snapshot_values, d0_snapshot_values) | khóa SKU × FC (× ngày / run / snapshot) duy nhất, không bảng nào có cột item (`grain_check_after.json`) |

## 2. Quy tắc trùng theo trạng thái trên bảng thật (SQL của app 1.2.11, 01/01-20/10)

| Chỉ số | Giá trị |
|---|---:|
| Dòng / số lượng kiểm tra | 8.979.752 / 42.088.223 |
| Nhóm trùng (trạng thái khác WAIT_TO_CONFIRM, so mọi cột ánh xạ trừ `item_code`) | **0** |
| Dòng WAIT_TO_CONFIRM (miễn) / số lượng | 904 / 12.933 |
| Trong đó chưa có `so_code` | 904 |
| Nhóm / dòng WAIT_TO_CONFIRM giống nhau ở mọi cột so sánh | 46 / 136; mỗi nhóm mỗi dòng một khách khác nhau (0 nhóm trùng khách) |
| Dòng WAIT_TO_CONFIRM giống nhau ở mọi cột nguồn | 0 |
| So thêm cả `item_code` (cách cũ) | nhóm ngoài WAIT_TO_CONFIRM: 0 → bỏ `item_code` không đổi kết quả |

## 3. Preview toàn kỳ và đối soát độc lập (production 1.2.11)

| Chỉ số (01/01-20/10) | Preview `BFP-20261021110908-3FC80A` | Nguồn (SQL độc lập) | App trước D-1 (bản sao 18:17) |
|---|---:|---:|---:|
| Dòng nguồn đọc | 8.979.752 | 8.979.752 | - |
| Trùng hoàn toàn | 0 | - | - |
| Khóa | 1.360.913 | 1.360.913 | 1.360.913 |
| Số lượng | 42.088.223 | 42.088.223 | 42.088.223 |
| Khóa mới / đổi / bị loại | 0 / 0 / 0 | - | 0 / 0 / 0 |
| Chênh số lượng | 0 | - | 0 |
| Giờ mở bán | OK 1.360.907, MULTI_ITEM 6 | kỳ vọng như vậy | 0 lệch |

Preview mất 448 s và không ghi gì; đối soát độc lập bằng preview.

## 4. D-1 production và đối soát sau khi ghi

**Trước khi ghi - dry run:** READY, mọi bước PASSED.

- Cửa sổ 17/10-20/10.
- 0 nhóm trùng; 855 dòng WAIT_TO_CONFIRM được miễn (124 giống ở cột so sánh, 0 giống mọi cột).
- Cột không so sánh: `customer_id`, `item_code`, `seller_class`, `refresh_time`.
- Dự kiến 0 mới / 0 đổi / 0 bị loại / 11.995 không đổi.

**Job:** `JOB-20261021111824-17023B` ("Chạy ngay", `POST /api/schedules/d1/run`), 18:18:24-18:20:04, **SUCCEEDED**.

- Đọc 72.153 dòng / 293.522 đơn vị, 0 trùng hoàn toàn.
- Ghi 11.995 khóa: 0 mới, 0 đổi, 0 bị loại, 11.995 không đổi. Kết quả này bằng dry run.
- Giờ mở bán `OK` 11.995.

| Chỉ số (01/01-20/10, bản sao 18:21) | App | Nguồn | Chênh |
|---|---:|---:|---:|
| Khóa | 1.360.913 | 1.360.913 | 0 |
| Số lượng | 42.088.223 | 42.088.223 | 0 |
| Khóa mới / bị loại / đổi | - | - | 0 / 0 / 0 |
| Giờ mở bán lệch | - | - | 0 |
| Ngày chốt actual | 293 FINALIZED (01/01-20/10), 0 bị chặn | - | - |

Không backfill, không ngày lịch sử nào bị ghi lại; các revision cũ giữ nguyên.

## 5. Bất thường khác (đã xuất Excel)

| Sheet | Nội dung |
|---|---|
| `Six_MULTI_ITEM`, `Six_Source_Lines` | 6 khóa, 113 dòng nguồn (mọi FC): SO khác nhau, mỗi item một giá trị giờ, 2 listing của 2 miền cùng FC |
| `Pending_Exempt_Rows` | 136 dòng WAIT_TO_CONFIRM giống ở cột so sánh (46 nhóm). Kỳ vọng 1.2.11: miễn, giữ. 1.2.10: giữ. 1.2.8: chặn |
| `Listing_Assoc_Other_Item` | 19 khóa chỉ có dòng của item không phải listing mà `fact_classification_sku_history` gắn với FC đó |
| `Listing_Assoc_Cross_Region` | 184 FC × SKU × tháng mà bảng phân loại gắn listing của miền kia |
| `Listing_Assoc_Coverage` | độ phủ theo tháng: 1-43% khóa D-1 không có liên kết |
| `D1_Schedule_Evidence` | lịch sử job D-1 / huấn luyện (mục 6) |
| `Proxy_Audit` | kết quả kiểm tra proxy chỉ đọc |
| `Recon_Diff_Rows` | trống (0 khác biệt) |

## 6. Giờ nguồn và lịch D-1 (số liệu)

**Lần chạy D-1 theo lịch: 4 / 4 thất bại `SOURCE_INCOMPLETE`**, mỗi lần dùng hết 4 lượt thử:

| Slot | Kết thúc (giờ VN) |
|---|---|
| 18/10 03:00 | 06:08 |
| 19/10 03:00 | 05:09 |
| 20/10 03:00 | 05:08 |
| 21/10 06:00 | 06:38 |

**Mọi lần nạp thành công đều chạy tay:**

| Ngày | Giờ (VN) |
|---|---|
| 18/10 | 08:56 |
| 19/10 | 10:31 (lần 10:13 thất bại) |
| 20/10 | 12:29 |
| 21/10 | 15:11 và 18:18 (+ backfill 12:29-12:46) |

**Bảng nguồn được dựng lại:**

- 20/10 07:10, 21/10 07:10:38 (mô tả bảng: "refresh 07h00");
- ngoài ra bản dựng tay 20/10 15:05 và 22:18.

**Hệ quả:**

- D-1 06:00 / dự phòng 06:30 luôn chạy trước khi nguồn sẵn sàng.
- Huấn luyện 07:00 (catch-up SKIP) chờ D-1 thành công trong ngày. Khi D-1 chỉ thành công sau 07:20, slot huấn luyện bị ghi SKIPPED. Hôm nay: `JOB-20261021081219-4C2CF4` SKIPPED `MISSED_SLOT_NO_BACKFILL`.

**Cần một trong hai điều chỉnh (chủ hệ thống quyết; tôi không đổi lịch):**

- dời D-1 sau 07:15 và dời giờ huấn luyện sau D-1;
- hoặc nguồn cam kết sẵn sàng trước 06:00.
