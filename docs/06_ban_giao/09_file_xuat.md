# 09 – File Excel dự báo hằng ngày (bản 1.4.3)

Đặc tả file mà bộ phận mua hàng dùng mỗi ngày. Code: `backend/app/ml/sel2/export.py` (gọi tắt `export.py`), ghi bằng
bộ ghi luồng `backend/app/ml/sel2/xlsx_stream.py`. Logic tạo con số: xem `03_logic_du_bao.md`. Mọi giá trị ví dụ là
**giả**.

---

## 1. Vị trí, tên file, phiên bản

Thư mục: `<DATA_DIR>\exports\du_bao\YYYYMMDD\` (`sel2_pipeline.export_subdir` = `exports\du_bao`, luôn nằm trong thư mục
dữ liệu, kiểm tra ở `export.py:82-90`). `YYYYMMDD` = ngày dự báo D (giờ Việt Nam).

| File | Ý nghĩa | Code |
|---|---|---|
| `du_bao_YYYYMMDD_vN.xlsx` | Phiên bản N (1, 2, …). Mỗi lần xuất tạo **một phiên bản mới**; không bao giờ ghi đè hay sửa sau đó. 1.4.5: khi có phiên bản mới, các phiên bản trước của cùng ngày được đổi tên `du_bao_YYYYMMDD_vK_bo.xlsx` (không xoá, nội dung giữ nguyên; `export_runs.path` cập nhật cùng giao dịch ghi phiên bản mới); file đang mở trong Excel thì giữ tên cũ, phiên bản mới có cờ `OLD_VERSION_RENAME_FAILED`. Một dòng `export_runs` / phiên bản (đường dẫn tương đối, SHA-256, số dòng, `is_stale`, cờ, tóm tắt JSON). | `export.py:3-5`, `export.py:356-473` |
| `du_bao_YYYYMMDD.xlsx` | **Bản mới nhất**: bản sao của phiên bản cao nhất (ghi file tạm rồi thay thế). Người dùng mở file này. | `export.py:173-212` |
| `du_bao_YYYYMMDD_TAM.xlsx` | **Bản tạm** chỉ của lần khởi động đầu (`sel2-bootstrap`): số LightGBM = ứng viên `V33_L112` cho mọi SKU × FC (chưa chọn mô hình), `model_used = V33_L112`. Không phải phiên bản, không phải bản mới nhất, không ghi `export_runs` (chỉ nhật ký `SEL2_EXPORT_TEMP_WRITTEN`); chạy lại bootstrap cùng ngày thì ghi đè. | `export.py:31-33`, `export.py:486-613` |
| `.du_bao_YYYYMMDD_vN.reserved`, `.du_bao_*.tmp` | File khoá số phiên bản / file tạm (ẩn). Tạo độc quyền (O_EXCL); bản bỏ lại > 1 giờ được xoá trước lần xuất sau. | `export.py:7-11`, `export.py:130-170` |

Quy tắc phiên bản: số = `MAX(version)` trong `export_runs` của ngày + 1, bỏ qua số đã có file / bản ghi / khoá (một tiến
trình chết để lại khoảng trống số, không bao giờ trùng) (`export.py:149-170`). Bảng `export_runs` có ràng buộc
`UNIQUE (forecast_date, version)` (`backend/app/migrations/0012_sel2_pipeline.sql:134-149`).

Khi nào có phiên bản mới trong ngày:

| Trigger | Khi nào | Code |
|---|---|---|
| Sau mỗi lần công bố SEL2 | Cuối `run_day` (lịch, chạy lại `RERUN`, chạy tay) | `backend/app/ml/sel2/pipeline.py:320-329`, `pipeline.py:361` |
| `STALE` | 06:30 (`export_deadline`) nếu hôm nay chưa công bố và chưa có file | `backend/app/ml/sel2/jobs.py:356-364` |
| `MANUAL` | Nút xuất trên trang Dự báo hằng ngày / `POST /api/sel2/export` / CLI | `jobs.py:351-355` |
| `AVG_REEXPORT` | Từ `avg_reexport_time` khi bảng AVG_DEMAND đổi sau lần đọc đã dùng (**đang tắt**: `null`) | `jobs.py:365-379` |

Ngày 04/11/2026 có 2 phiên bản; `v1` được ghi khi chưa đọc xong AVG_DEMAND, `v2` là bản chính thức. Danh sách việc
bản sau 1.4.2 (đã chốt, chưa làm): mỗi ngày chỉ giữ 1 file cuối cùng (bản trước đổi tên hoặc xoá) để không nhầm.

---

## 2. Cấu trúc file

Từ **1.4.4** (quyết định chủ dự án tối 05/11/2026; app ghi trực tiếp, giá trị trùng từng ô với script vận hành
`scripts/ops/excel20.py` đã viết lại bản mới nhất của 1.4.3 từ sáng 06/11): các sheet theo thứ tự `DU_BAO_<fc_code>` (một
sheet mỗi kho, sắp theo `fc_code`, ví dụ `DU_BAO_BD`, `DU_BAO_HN`), rồi `TOM_TAT`, `CONFIG` (`export._write_book`). Tên
sheet: ký tự Excel không nhận (`[ ] : * ? / \ '`) → `_`, tối đa 31 ký tự, `fc_code` trống → `DU_BAO_KHONG_FC`
(`export.sheet_name`). Không có SKU × FC nào → chỉ có `TOM_TAT`, `CONFIG`. Đến 1.4.3: một sheet `DU_BAO` 7 ngày. Mọi sheet:
dòng tiêu đề in đậm, cố định dòng tiêu đề và có bộ lọc (autofilter). Kiểu ô (`xlsx_stream.py:1-15`): chuỗi = inline string
(một ghi chú bắt đầu bằng `=` vẫn là chữ, không thành công thức); số nguyên / số thực = number (số thực ghi đủ chữ số);
ngày = số sê-ri Excel định dạng `yyyy-mm-dd`; `None` = ô trống (không có ô).

### 2.1 Sheet `DU_BAO_<fc_code>` – một dòng mỗi SKU × FC × ngày đích (20 ngày)

Tập SKU × FC = **hợp** của (a) các SKU × FC trong lần chạy SEL2 đang dùng và (b) các SKU × FC có dòng AVG_DEMAND của
ngày D; mỗi sheet chứa các SKU × FC của **một kho**, sắp theo `sku_code`; mỗi SKU × FC đúng **20 dòng liền nhau**,
horizon 1..20, ngày đích D .. D+19. Thứ tự cột = `COLUMNS` + cột cuối `cach_tinh` (`export.COLUMNS20`). Horizon 1..7
(`cach_tinh = SEL2`) = các dòng 7 ngày như trước (`export._rows`); horizon 8..20 ở mục 2.1.1. Bảng cột (horizon 1..7):

| # | Cột | Kiểu | Ý nghĩa | Ví dụ (giả) |
|---:|---|---|---|---|
| 1 | `sku_code` | chuỗi | Mã SKU | `SKU-DEMO-001` |
| 2 | `ten_san_pham` | chuỗi / trống | Tên sản phẩm: `product_name` của AVG_DEMAND ngày D, ghi đè bởi danh mục tên sản phẩm của app nếu có (`export.py:265-273`) | `Sản phẩm demo 001` |
| 3 | `seller_code` | chuỗi / trống | (1.4.3) Phần của `sku_code` **trước dấu chấm đầu tiên**; trống khi `sku_code` không có dấu chấm | `MEDX` |
| 4 | `product_code` | chuỗi | (1.4.3) Phần của `sku_code` **sau dấu chấm đầu tiên** (mã có nhiều dấu chấm chỉ tách ở dấu đầu: `A.B.C` → `A` / `B.C`); không có dấu chấm → nguyên `sku_code` | `ABC-ABC-010` |
| 5 | `fc_code` | chuỗi | Mã kho | `FC-A` |
| 6 | `nhom` | chuỗi / trống | Nhóm A / B / C của lần chạy SEL2 (B7, 90 ngày); trống khi SKU × FC không có trong lần chạy | `B` |
| 7 | `forecast_date` | ngày | Ngày dự báo D (cả khi file dùng lần chạy cũ) | `2026-11-10` |
| 8 | `target_date` | ngày | Ngày đích D + h − 1 | `2026-11-12` |
| 9 | `horizon` | số nguyên 1..20 | Vị trí ngày đích tính **từ D** (1 = D) | `3` |
| 10 | `lightgbm_forecast` | số nguyên / trống | Số công bố SEL2 (`final_qty`: làm tròn 6 số; < 0,2 → 0; còn lại làm tròn lên) của lần chạy hôm nay; khi dòng dùng số của lần chạy trước (`DUNG_SO_LAN_CHAY_TRUOC`) là số của lần chạy đó (ngày ở cờ `LAN_CHAY_TRUOC:<ngày>`); trống khi không lần chạy nào có số | `3` |
| 11 | `avg_demand` | số thực / trống | Giá trị AVG_DEMAND của **ngày D** (cùng một số cho cả 7 dòng), không làm tròn; trống khi không có (lý do ở `flags`) | `4.3` |
| 12 | `forecast_source` | chuỗi | Nguồn cấu hình: `LIGHTGBM` hoặc `AVG_DEMAND` (không có dòng cấu hình = `AVG_DEMAND`) | `LIGHTGBM` |
| 13 | `forecast_used` | **số nguyên ≥ 0, KHÔNG BAO GIỜ trống** | **Số dùng** theo quy tắc cố định 05/11/2026 (1.4.3): số LightGBM của hôm nay (kể cả 0) khi nguồn `LIGHTGBM`; ngoài phạm vi lần chạy → `0` (mọi tiền tố mã); thiếu số / hôm nay lỗi → số của lần chạy thành công gần nhất trong 3 ngày; không có → `avg_demand`; nguồn `AVG_DEMAND` → `avg_demand`, không có Avg → số LightGBM; **luôn làm tròn** (< 0,2 → 0, còn lại làm tròn lên); không có số nào → `0` (`export.py:367-430`, mục 3.1) | `3` |
| 14 | `fallback_reason` | chuỗi / trống | Trống = dùng đúng nguồn đã cấu hình; ý nghĩa từng giá trị ở mục 3.1 | `NGOAI_PHAM_VI_GAN_0` |
| 15 | `model_used` | chuỗi / trống | Mô hình SEL2 của dòng: `<A>+<B>` hoặc `FALLBACK:V33_L112` (file tạm: `V33_L112`) | `V33_L112+DOW4` |
| 16 | `raw_value` | số thực / trống | Giá trị SEL2 thô trước làm tròn (`lgb_raw`) | `2.925` |
| 17 | `model_version` | chuỗi / trống | `SEL2 MOC=<id> V33_L112=<id> V36_two_stage=<id>` (3 lần học) của lần chạy cấp số dòng đó (dòng `LAN_CHAY_TRUOC`: của lần chạy trước); trống khi không có lần chạy tham chiếu (cờ file `NO_RUN_3_DAYS`); file tạm: `TAM V33_L112=<id>` | `SEL2 MOC=CTR-… V33_L112=CTR-… V36_two_stage=CTR-…` |
| 18 | `data_cutoff_date` | ngày / trống | Ngày dữ liệu cuối của lần chạy cấp số dòng đó (D-1 của lần chạy đó); trống khi không có lần chạy tham chiếu | `2026-11-09` |
| 19 | `is_stale` | 0 / 1 | 1 = file không có lần chạy SEL2 của chính ngày D (mục 4) | `0` |
| 20 | `flags` | chuỗi / trống | Cờ của dòng, cách nhau bằng dấu phẩy: cờ lần chạy + `LAN_CHAY_TRUOC:<ngày>` (khi dùng số lần chạy trước) + `AVG_<lý do>` (mục 3.2) | `OPEN_HOURS_LAG,AVG_NO_ROW` |
| 21 | `cach_tinh` | chuỗi | (1.4.4) `SEL2` (horizon 1..7) hoặc `UOC_TINH_THEO_TUAN` (horizon 8..20) | `SEL2` |

Ví dụ 7 dòng của một SKU × FC (giả, khớp ví dụ tính tay của `03_logic_du_bao.md`; ẩn cột 2–4, 17):

| sku_code | fc_code | nhom | forecast_date | target_date | horizon | lightgbm_forecast | avg_demand | forecast_source | forecast_used | fallback_reason | model_used | raw_value | data_cutoff_date | is_stale | flags |
|---|---|---|---|---|---:|---:|---:|---|---:|---|---|---:|---|---:|---|
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-10 | 1 | 5 | 4.3 | LIGHTGBM | 5 | | V33_L112+DOW4 | 4.935 | 2026-11-09 | 0 | |
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-11 | 2 | 0 | 4.3 | LIGHTGBM | 0 | | V33_L112+DOW4 | 0.175 | 2026-11-09 | 0 | |
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-12 | 3 | 3 | 4.3 | LIGHTGBM | 3 | | V33_L112+DOW4 | 2.925 | 2026-11-09 | 0 | |
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-13 | 4 | 7 | 4.3 | LIGHTGBM | 7 | | V33_L112+DOW4 | 6.17 | 2026-11-09 | 0 | |
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-14 | 5 | 0 | 4.3 | LIGHTGBM | 0 | | V33_L112+DOW4 | 0.06 | 2026-11-09 | 0 | |
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-15 | 6 | 1 | 4.3 | LIGHTGBM | 1 | | V33_L112+DOW4 | 0.2 | 2026-11-09 | 0 | |
| SKU-DEMO-001 | FC-A | B | 2026-11-10 | 2026-11-16 | 7 | 3 | 4.3 | LIGHTGBM | 3 | | V33_L112+DOW4 | 2.855 | 2026-11-09 | 0 | |

Cùng chuỗi nhưng không cấu hình (mặc định `AVG_DEMAND`): `forecast_source = AVG_DEMAND`, `forecast_used = 5` cả 7
dòng (Avg 4,3 làm tròn lên; cột `avg_demand` vẫn 4.3), `fallback_reason` trống; các cột LightGBM vẫn hiện để đối chiếu.
(Ví dụ trên ẩn cột `cach_tinh` = `SEL2`.)
Một SKU × FC chỉ có trong AVG_DEMAND (ngoài phạm vi dự báo): `nhom`, `lightgbm_forecast`, `model_used`, `raw_value`
trống; nếu cấu hình `LIGHTGBM` (production từ 04/11: mọi SKU × FC) thì `forecast_used = 0` (`NGOAI_PHAM_VI_GAN_0`) với
**mọi** tiền tố mã. Ngày lần chạy hôm nay lỗi, lần chạy D-1 có chuỗi này: 6 dòng đầu lấy số của lần chạy D-1
(`DUNG_SO_LAN_CHAY_TRUOC`, cờ `LAN_CHAY_TRUOC:2026-11-09`), dòng D+6 dùng Avg làm tròn lên (`STALE`).

#### 2.1.1 Horizon 8..20 (`cach_tinh = UOC_TINH_THEO_TUAN`, 1.4.4)

Mẫu = dòng cùng SKU × FC có horizon `((h − 1) % 7) + 1` (cùng thứ trong tuần: h 8 → mẫu h 1, h 14 → h 7, h 15 → h 1).
`target_date` = D + h − 1, `horizon` = h, `lightgbm_forecast` = `raw_value` của mẫu (1.4.5: làm tròn < 0,2 → 0, còn lại làm tròn lên; 1.4.4 không làm tròn; trống khi mẫu không
có `raw_value`); các cột khác chép từ mẫu (kể cả `avg_demand`, `model_used`, `raw_value`, `model_version`, `flags`).
`forecast_used` / `fallback_reason` tính lại theo quy tắc cố định (`export.derive_used`), luôn là số nguyên ≥ 0:

| Mẫu | `forecast_used` | `fallback_reason` |
|---|---|---|
| `NGOAI_PHAM_VI_GAN_0` | `0` | `NGOAI_PHAM_VI_GAN_0` |
| `LIGHTGBM`, có `raw_value` | `raw_value` làm tròn (< 0,2 → 0, còn lại làm tròn lên) | `DUNG_SO_LAN_CHAY_TRUOC` nếu mẫu có, còn lại trống |
| `LIGHTGBM`, không có `raw_value` | `forecast_used` của mẫu | lý do của mẫu |
| `AVG_DEMAND`, mẫu `KHONG_CO_AVG_DUNG_LIGHTGBM` và có `raw_value` | `raw_value` làm tròn | `KHONG_CO_AVG_DUNG_LIGHTGBM` |
| `AVG_DEMAND` khác | `forecast_used` của mẫu | lý do của mẫu |
| Lý do mẫu `KHONG_CO_SO_NAO` hoặc không có số | `0` | `KHONG_CO_SO_NAO` |

Giới hạn: một kho tối đa `MAX_SKU_FC` = 50.000 SKU × FC (50.000 × 20 dòng < 1.048.576 dòng của Excel). Vượt (hoặc hai
tên sheet trùng nhau): **không ghi file** (không có phiên bản, không có bản ghi `export_runs`), nhật ký lỗi có cờ
`TOO_MANY_SKU_FC` / `SHEET_NAME_CLASH`, lỗi `SEL2_EXPORT_WRITE_FAILED` (detail = cờ + số SKU × FC theo kho).
`export_runs.n_rows` và `n_rows` của kết quả = tổng số dòng các sheet `DU_BAO_*` (SKU × FC × 20). Bản tạm `_TAM` cùng
bố cục.

### 2.2 Sheet `TOM_TAT` – hai cột `muc`, `gia_tri`

Các dòng theo đúng thứ tự (`export.py:332-352`); dòng có tiền tố lặp lại cho từng giá trị gặp trong file, sắp chữ cái:

| `muc` | Ý nghĩa | Ví dụ (giả) |
|---|---|---|
| `forecast_date` | Ngày dự báo D | `2026-11-10` |
| `data_cutoff_date` | Ngày dữ liệu cuối của lần chạy dùng | `2026-11-09` |
| `export_version` | Số phiên bản N | `1` |
| `export_time_utc` / `export_time_vn` | Thời điểm ghi (UTC ISO / giờ VN) | `2026-11-09T20:25:13+00:00` / `2026-11-10 03:25:13` |
| `trigger` | Ai / cái gì tạo file (ví dụ `SCHEDULE`, `RETRY`, `MANUAL`, `STALE`, `AVG_REEXPORT`, `bootstrap`) | `SCHEDULE` |
| `is_stale` | 0 / 1 | `0` |
| `stale_reason` | `NO_RUN_FOR_DAY` (không có lần chạy hôm nay, có lần chạy trong 3 ngày), `NO_RUN_3_DAYS` (không có lần chạy thành công nào trong D-3 .. D-1: mọi dòng `LIGHTGBM` dùng Avg), `NO_SEL2_RUN`, `SCOPE_UNRESOLVED:<mã>` hoặc trống | |
| `file_flags` | Cờ cấp file (mục 3.3) | `AVG_NO_READ` |
| `refresh_run_id`, `run_forecast_date`, `model_version` | Lần chạy SEL2 của file, ngày dự báo của nó (khi `NO_RUN_3_DAYS`: chỉ để thông tin, không cấp số; `model_version` trống) | `FRR-…`, `2026-11-10`, `SEL2 MOC=…` |
| `previous_runs` | Các lần chạy D-3 .. D-1 đã xét cho quy tắc dùng số lần chạy trước (ngày + mã) | `2026-11-09:FRR-…` |
| `sku_fc_total` | Số SKU × FC trong file (= tổng số dòng / 20) | `58591` |
| `sku_fc_in_forecast_scope` | Số SKU × FC có trong lần chạy SEL2 | `14733` |
| `sku_fc_configured_lightgbm` | Số SKU × FC cấu hình `LIGHTGBM` | `58591` |
| `sku_fc_configured_lightgbm_not_in_file` | Số SKU × FC cấu hình `LIGHTGBM` nhưng không có dòng nào trong file | `0` |
| `rows_total` | Số dòng horizon 1..7 (`SEL2`) – giữ như file 7 ngày; tổng dòng từng sheet ở `rows:<sheet>` | `410137` |
| `rows_fallback_reason:<lý do>` | Số dòng horizon 1..7 theo `fallback_reason`; `(none)` = không có lý do | `rows_fallback_reason:(none)` = 410130 |
| `rows_flag:<cờ>` | Số dòng horizon 1..7 mang cờ đó | `rows_flag:AVG_NO_ROW` = 1050 |
| `sku_fc_avg_reason:<lý do>` | Số SKU × FC không có giá trị AVG_DEMAND, theo lý do | `sku_fc_avg_reason:NO_ROW` = 150 |
| `sku_fc_model_used:<mô hình>` | Số SKU × FC theo `model_used` (lấy theo horizon nhỏ nhất) | `sku_fc_model_used:FALLBACK:V33_L112` = 5428 |
| `fallback_window`, `sku_fc_fallback`, `fallback_pct_all_sku_fc`, `sku_fc_open_in_window`, `fallback_pct_open_sku_fc` | (1.4.5) Tỷ lệ FALLBACK (%) của lần chạy tham chiếu với 2 mẫu số: mọi SKU × FC trong phạm vi / chỉ SKU × FC có ngày mở bán (giờ mở > 0) trong cửa sổ chọn D-28 .. D-1 | `fallback_pct_all_sku_fc` = 9.3 |
| `sku_fc_fallback:khong_mo_ban_28_ngay`, `sku_fc_fallback:co_mo_ban_thieu_ngay` | (1.4.5) FALLBACK tách theo lý do: không mở bán ngày nào trong 28 ngày / có mở bán nhưng thiếu ngày (dưới `min_days` ngày có ô, hoặc ứng viên thứ hai không có số) | |
| `open_hours_lag_note` | (1.4.5, chỉ khi file có cờ `OPEN_HOURS_LAG`) Ngày giờ mở bán mới nhất, giờ build bảng giờ mở bán và bảng demand (giờ VN, theo lần đọc gần nhất app đã ghi), bảng nào build trước; không rõ → `khong ro` | |
| `avg_source_kind` | `CURRENT` hoặc `HISTORICAL` (trống nếu chưa đọc) | `CURRENT` |
| `avg_source_table` | Bảng AVG_DEMAND đã đọc | `lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku` |
| `avg_source_modified`, `avg_read_completed_at` | Thời điểm bảng nguồn sửa lần cuối; lúc đọc xong | `2026-11-09T…Z` |
| `avg_seller_rule` | Quy tắc gộp nhiều seller (`PENDING`, `SUM`, `MAX`, `SELLER:<mã>`) | `PENDING` |
| `layout` | (1.4.4) `20 ngay, tach sheet theo kho` | |
| `horizon_8_20` | (1.4.4) Ghi chú cách tính horizon 8..20 | `UOC_TINH_THEO_TUAN: lightgbm_forecast = raw_value …` |
| `rows:<sheet>` / `sku_fc:<sheet>` | (1.4.4) Số dòng / số SKU × FC của từng sheet `DU_BAO_<fc_code>` | `rows:DU_BAO_BD` = 600000 |
| `source` | (1.4.4) App đã ghi file: `Demand Forecast <phiên bản> (ghi truc tiep)` (file do script vận hành viết lại có `source_file` + `source_sha256` thay cho dòng này) | `Demand Forecast 1.4.4 (ghi truc tiep)` |
| `generated_at` | (1.4.4) Thời điểm ghi, giờ VN | `2026-11-10 03:25:13 (VN)` |

Các số trong cột ví dụ là minh hoạ; riêng `sku_fc_total`, `sku_fc_in_forecast_scope`, `rows_total` và
`sku_fc_model_used:FALLBACK:V33_L112` lấy theo file ngày 04/11/2026.

File tạm `_TAM`: hai dòng đầu là `ghi_chu` = "bản tạm – chưa chọn mô hình theo SKU" và `trigger` = `BOOTSTRAP_TEMP`,
`export_version` = `TAM` (`export.py:486-487`, `export.py:609-613`).

### 2.3 Sheet `CONFIG` – các SKU × FC đang cấu hình `LIGHTGBM` lúc xuất

`export.py:62`, `export.py:276-278`, sắp theo (`sku_code`, `fc_code`):

| # | Cột | Kiểu | Ý nghĩa | Ví dụ (giả) |
|---:|---|---|---|---|
| 1 | `sku_code` | chuỗi | Mã SKU | `SKU-DEMO-001` |
| 2 | `fc_code` | chuỗi | Mã kho | `FC-A` |
| 3 | `ten_san_pham` | chuỗi / trống | Tên sản phẩm | `Sản phẩm demo 001` |
| 4 | `seller_code` | chuỗi / trống | (1.4.3) Phần của `sku_code` **trước dấu chấm đầu tiên**; trống khi `sku_code` không có dấu chấm | `MEDX` |
| 5 | `product_code` | chuỗi | (1.4.3) Phần của `sku_code` **sau dấu chấm đầu tiên** (mã có nhiều dấu chấm chỉ tách ở dấu đầu: `A.B.C` → `A` / `B.C`); không có dấu chấm → nguyên `sku_code` | `ABC-ABC-010` |
| 6 | `ghi_chu` | chuỗi / trống | Ghi chú lúc cấu hình | `thử LightGBM` |
| 7 | `updated_by` | chuỗi | Tài khoản Windows đã đổi | `<user>` |
| 8 | `updated_at` | chuỗi (UTC ISO) | Lúc đổi | `2026-11-05T02:10:00+00:00` |

SKU × FC không có trong bảng cấu hình = `AVG_DEMAND` (không liệt kê). Đổi cấu hình: màn hình "Nguồn dự báo"
(`/forecast-source`) hoặc tải lên `.xlsx` (`backend/app/ml/sel2/source_config.py:1-20`); có hiệu lực từ lần xuất sau,
file đã ghi không bị sửa.

---

## 3. Lý do, cờ dòng và cờ file

### 3.1 `fallback_reason` – ý nghĩa từng giá trị (quy tắc cố định 05/11/2026, 1.4.3)

`export.py:93-103` (hằng số), `export.py:367-430` (quy tắc). "Lần chạy tham chiếu" = lần chạy SEL2 của ngày D; nếu hôm nay
lỗi = lần chạy thành công gần nhất trong D-3 .. D-1. `forecast_used` **luôn là số nguyên ≥ 0, không bao giờ trống**.

| Giá trị | Điều kiện | `forecast_used` |
|---|---|---|
| (trống) | Dùng đúng nguồn đã cấu hình: `LIGHTGBM` có số của hôm nay (kể cả 0), hoặc `AVG_DEMAND` có giá trị Avg | số đó, làm tròn (< 0,2 → 0, còn lại lên) |
| `NGOAI_PHAM_VI_GAN_0` | Nguồn `LIGHTGBM`, SKU × FC **ngoài phạm vi lần chạy tham chiếu** – mọi tiền tố mã, kể cả ngày hôm nay lỗi | **0** |
| `DUNG_SO_LAN_CHAY_TRUOC` | Nguồn `LIGHTGBM`, trong phạm vi nhưng hôm nay không có số cho ngày đích này (hôm nay lỗi, hoặc thiếu số 1 SKU): dùng số của lần chạy thành công gần nhất trong D-3 .. D-1 có số đó; ngày lần chạy ở cờ `LAN_CHAY_TRUOC:<ngày>` | số lần chạy trước (kể cả 0), làm tròn |
| `STALE` | Nguồn `LIGHTGBM`, hôm nay không có lần chạy và không lần chạy nào trong 3 ngày có số đó (gồm mọi dòng khi cờ file `NO_RUN_3_DAYS`) | `avg_demand` làm tròn lên |
| `KHONG_CO_SO` | Nguồn `LIGHTGBM`, có lần chạy hôm nay nhưng không lần chạy nào trong 3 ngày có số đó; hoặc chưa từng có lần chạy SEL2 | `avg_demand` làm tròn lên |
| `KHONG_CO_AVG_DUNG_LIGHTGBM` | Nguồn `AVG_DEMAND` (mã mới), không có giá trị Avg nhưng có số LightGBM (hôm nay, hoặc lần chạy trước – có cờ) | số LightGBM, làm tròn |
| `KHONG_CO_SO_NAO` | Không có số nào (thay cho `STALE` / `KHONG_CO_SO` khi `avg_demand` cũng trống; hoặc `AVG_DEMAND` không có cả Avg lẫn LightGBM) | **0** |

Mã cũ chỉ còn trong file xuất trước 1.4.3: `KHONG_CO_DU_LIEU_DEMAND` (1.4.1 / 1.4.2, 04–05/11/2026: mã không phải MEDX
ngoài phạm vi → `avg_demand`) và `NGOAI_PHAM_VI` (1.4.0). Số dòng theo từng lý do có trong `TOM_TAT`
(`rows_fallback_reason:<lý do>`).

Vì sao giữ số 0 của LightGBM và ghi 0 cho mã ngoài phạm vi (kiểm tra của chủ dự án theo từng SKU, tháng 10/2026): thay
số 0 bằng Avg làm 54,5 % SKU lệch nhiều hơn, chỉ 5 % đúng hơn; tổng lệch tăng từ 18.971 lên 81.439 sản phẩm.

### 3.2 Cờ dòng (cột `flags`)

| Cờ | Ý nghĩa |
|---|---|
| `OPEN_HOURS_LAG` | Lần chạy đã điền giờ mở bán theo quy tắc trễ 2 ngày |
| `MODEL_PREV_WEEK` | Lần chạy dùng model LightGBM của tuần trước |
| `CONFIG_DRIFT` | Cấu hình phân giải ở mốc học khác bản backtest (ghi nhận, không lỗi) |
| `AVG_NO_ROW` | Không có dòng AVG_DEMAND của ngày D cho SKU × FC |
| `AVG_AVG_DEMAND_NULL` | Dòng AVG_DEMAND có `avg_demand` NULL |
| `AVG_SELLER_RULE_PENDING` | Nhiều dòng seller, quy tắc gộp chưa duyệt → không có số |
| `AVG_SELLER_NOT_FOUND` | Quy tắc `SELLER:<mã>` nhưng không có seller đó |

Cờ lần chạy lấy từ `forecast_refresh_values.flags`; cờ `AVG_*` thêm ở `export.py:312-315`
(lý do: `backend/app/ml/sel2/avg_demand.py:35-38`, `avg_demand.py:218-240`).

### 3.3 Cờ cấp file (`TOM_TAT.file_flags`, `export_runs.flags`)

| Cờ | Ý nghĩa | Code |
|---|---|---|
| `STALE` | Không có lần chạy SEL2 của D (hôm nay lỗi / chưa có) | `export.py` `write_daily_export` |
| `NO_RUN_3_DAYS` | (1.4.3) Không có lần chạy SEL2 thành công nào trong D-3 .. D-1: mọi dòng `LIGHTGBM` dùng Avg (`STALE`), `model_version` / `data_cutoff_date` trống | `export.py:103` |
| `NO_SEL2_RUN` | Không có lần chạy SEL2 nào; mọi dòng `LIGHTGBM` lấy AVG_DEMAND (`KHONG_CO_SO`) | `export.py:102` |
| `AVG_NO_READ` | Ngày D chưa có lần đọc AVG_DEMAND hoàn tất (cột `avg_demand` trống toàn bộ) | `export.py:69`, `export.py:393` |
| `LATEST_COPY_LOCKED` | Không thay được `du_bao_YYYYMMDD.xlsx` (đang mở trong Excel); phiên bản `vN` vẫn ghi và ghi nhận; bản mới nhất cập nhật ở lần xuất sau | `export.py:70`, `export.py:196-198`, `export.py:464-468` |
| `LATEST_COPY_FAILED` | Lỗi hệ điều hành khác khi chép bản mới nhất; phiên bản vẫn giữ | `export.py:199-201` |

`export_runs.flags` = cờ cấp file + mọi cờ dòng gặp trong file (`export.py:439`).

---

## 4. Chế độ cũ (stale) – 1.4.3

`export.py` (docstring "Stale mode", `_run_for`, `_previous_runs`, `_previous_values`, `write_daily_export`):

1. Có lần chạy SEL2 công bố cho D → lần chạy tham chiếu, `is_stale = 0`. SKU × FC trong phạm vi mà thiếu số của một
   ngày đích → số của lần chạy thành công gần nhất trong D-3 .. D-1 có số đó (`DUNG_SO_LAN_CHAY_TRUOC`), không có → Avg.
2. Không có (hôm nay lỗi) → lần chạy tham chiếu = lần chạy thành công **gần nhất trong D-3 .. D-1**: mã trong phạm vi
   của nó → số của các lần chạy D-3 .. D-1 cho đúng ngày đích (`horizon` tính lại từ D; `model_version` /
   `data_cutoff_date` của chính lần chạy cấp số); mã ngoài phạm vi → 0; `is_stale = 1`, cờ file `STALE`. Ngày đích D+6
   không lần chạy trước nào có (horizon 8) → Avg (`STALE`) hoặc 0 (ngoài phạm vi).
3. Lần chạy gần nhất cũ hơn D-3 → **không dùng số nào của nó**: mọi dòng `LIGHTGBM` lấy Avg (`STALE`), cờ file
   `STALE,NO_RUN_3_DAYS`, `stale_reason = NO_RUN_3_DAYS`.
4. Không có lần chạy nào → mọi dòng `LIGHTGBM` lấy AVG_DEMAND (`KHONG_CO_SO`), `is_stale = 1`, cờ file `NO_SEL2_RUN`.

Mọi trường hợp: `forecast_used` làm tròn và không bao giờ trống (không có số nào → 0, `KHONG_CO_SO_NAO`).

Lịch tự ghi file stale lúc 06:30 khi hôm nay chưa công bố và chưa có file (`backend/app/jobs/scheduler.py:392-399`).

---

## 5. Lỗi khi xuất

| Mã | Ý nghĩa |
|---|---|
| `SEL2_PIPELINE_DISABLED` | Công tắc khẩn cấp đang tắt SEL2: không ghi (`export.py:361-362`) |
| `SEL2_EXPORT_PATH_INVALID` | `export_subdir` hoặc đường dẫn lưu ra ngoài thư mục dữ liệu (`export.py:88-89`, `export.py:103-104`) |
| `SEL2_EXPORT_WRITE_FAILED` | Không ghi được file / bản ghi; file phiên bản chưa ghi nhận bị xoá (`export.py:402-403`, `export.py:451-458`) |
| `SEL2_EXPORT_NOT_FOUND` | Ngày chưa có phiên bản nào hoặc file đã mất (`export.py:629-640`) |
| `SEL2_EXPORT_CONFIRM_REQUIRED` | `POST /api/sel2/export` thiếu `confirm: true` |

Lỗi xuất **không làm hỏng** lần công bố (`pipeline.py:320-329`).

---

## 6. Kích thước thực tế

| Đại lượng | Ngày 04/11/2026 (file chính thức `v2`) |
|---|---|
| Số dòng `DU_BAO` | **410.137** (= 58.591 SKU × FC × 7) |
| SKU × FC trong lần chạy SEL2 | 14.733 (9.305 chọn 2 ứng viên, 5.428 `FALLBACK:V33_L112` = 36,8 %) |
| SKU × FC chỉ có AVG_DEMAND | 43.858 |
| File tạm `_TAM` ngày 03/11 | 410.137 dòng |
| Thời gian ghi | Bộ ghi luồng (openpyxl cũ mất khoảng 380 s cho 420 nghìn dòng, `export.py:324-325`); đo trên bản sao 15/10: 104.307 dòng trong 5,4 s; toàn bộ `sel2-day` 441 s |

App không tự xoá file xuất; quy tắc dọn định kỳ đã duyệt 03/11/2026 (Excel hằng ngày giữ 90 ngày) chạy bằng script
vận hành riêng, mặc định chạy thử.

---

## 7. API và CLI

| Cách | Lệnh | Ghi chú |
|---|---|---|
| Tải bản mới nhất | `GET /api/sel2/export/{YYYY-MM-DD}` | Trả file phiên bản cao nhất; header `X-DF-Export-Version`, `X-DF-Export-Sha256` (`backend/app/api/sel2_routes.py:115-122`) |
| Danh sách phiên bản | `GET /api/sel2/export/{YYYY-MM-DD}/runs` | Bản ghi `export_runs` mới nhất trước, kèm `summary` (`sel2_routes.py:125-129`) |
| Xuất lại (app) | `POST /api/sel2/export` body `{"date": "YYYY-MM-DD", "confirm": true}` | Tạo job nền `FORECAST_EXPORT` mode `MANUAL`; đang có job chờ / chạy thì trả job đó (`already_active`) (`sel2_routes.py:137-155`) |
| Xuất lại (CLI) | `python -m app.cli sel2-export --date YYYY-MM-DD --yes` | Không có `--yes`: chỉ in đường dẫn DB và kế hoạch |
| Chạy lại cả ngày | `python -m app.cli sel2-day --date YYYY-MM-DD --force --yes` | Ứng viên + SEL2 + công bố mới + phiên bản Excel mới |
| Đọc AVG_DEMAND | `python -m app.cli sel2-avg-read --date <hôm nay> --yes`; ngày đã qua: `--hist-from D1 --hist-to D2` | Bảng hiện tại chỉ nhận hôm nay (`AVG_CURRENT_ONLY_TODAY`) |
| Cấu hình nguồn | `GET /api/sel2/source-config/download`; tải lên `POST /api/sel2/source-config/upload` → `POST /api/sel2/source-config/apply` | Xem trước rồi áp dụng; lịch sử chỉ thêm, không sửa / xoá |

Mọi lệnh `sel2-*` ghi vào DB thật của bản cài: chỉ chạy khi được phép; thử nghiệm luôn làm trên bản sao DB.
