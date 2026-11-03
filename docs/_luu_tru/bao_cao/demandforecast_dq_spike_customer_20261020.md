# Demand Forecasting: chất lượng dữ liệu giờ mở bán, cửa sổ huấn luyện, thí nghiệm spike và customer_id (1.2.9, đợt 3)

Thời gian: 20/10/2026, từ khoảng 09:40 đến khi tạo checkpoint (mục 14), giờ Asia/Ho_Chi_Minh.

Phạm vi: prompt "DATA QUALITY, SPIKE EXPERIMENTS & CUSTOMER_ID", rồi quyết định của chủ hệ thống sau S0–S5: bỏ S6, chạy lại test, tổng hợp báo cáo, tạo checkpoint.

Trong đợt này **không làm**:
- commit, push, đóng gói, cài đặt hay deploy;
- huấn luyện production, D-0 / D-1 / EOD / backfill production;
- đổi lịch hay cấu hình production;
- đổi Price hay bật `customer_id`;
- xóa dữ liệu, log hay scratchpad.

Production vẫn là **1.2.8**. Kiểm tra chỉ đọc lúc 12:16:
- health 1.2.8; `current.txt` 1.2.8;
- `storage.json` SHA-256 `8D79DBDD…E047`, không đổi so với 19/10;
- tiến trình app PID 10884 (khởi động 19/10 20:08).

Job production từ 00:00 ngày 20/10 đều do lịch chạy, đợt này không chạy job nào:
- D-0 08:00, 10:00, 12:00: SUCCEEDED.
- D-1 03:00: FAILED `SOURCE_INCOMPLETE`, vì nguồn chưa có dữ liệu ngày 19/10. Chỉ ghi nhận, không chạy lại.

**Trạng thái đề xuất: `BLOCKED_DATA_SAFETY`.** Mã nguồn đã sẵn sàng và đã kiểm thử, nhưng **chưa deploy**. Phần chặn còn lại:
- Cửa sổ theo giờ mở bán vẫn bị cổng `OPEN_HOURS_INVALID` chặn, do 2 dòng `MULTI_ITEM` ngày 26/08 cần quy tắc được duyệt.
- `customer_id` cần chủ dữ liệu cung cấp cột nguồn (phần này là `BLOCKED_EXTERNAL_SETUP`).
- Thí nghiệm spike chỉ là kết quả nghiên cứu. Không cấu hình nào được chấp nhận hay promote.

## Tóm tắt kết quả

| Hạng mục | Kết quả | Ghi chú ngắn |
|---|---|---|
| A. Giờ mở bán đúng hạt | **PASS** | Giờ mở bán đo theo item (listing theo miền bán) × ngày. 2 khóa ngày 26/08 là khác biệt hợp lệ giữa 2 item, nay có trạng thái `MULTI_ITEM` thay vì `CONFLICT`. Không có mâu thuẫn trong cùng item, không có lỗi JOIN. Không tự gộp MIN / MAX / AVG |
| B. Cửa sổ huấn luyện theo giờ mở bán | **PASS** (mã nguồn, đo trên bản sao) / quyết định còn mở | Quy tắc cấu hình được `OPEN_HOURS_COVERAGE`, mặc định giữ `WINDOW_START`. Bỏ tạm 01/01–18/03: 77 ngày, 32,2% nhu cầu, cả mùa Tết. Độ chính xác đo được không giảm (O1 so với E00) |
| C. Excel "0 giờ nhưng có đơn" | **PASS** | 2.592 / 2.592 dòng, đọc lại và đối chiếu từng trường. 718 khóa khớp; 4 khóa lệch do nguồn đổi giữa hai lần đọc. Không có lỗi xuất của ứng dụng |
| D. Thí nghiệm spike S0–S5 | **PASS** (đã chạy đủ, 30/30 fold) / kết luận **TRADE_OFF** | Mọi cấu hình giảm WAPE nhưng dự báo thiếu nhiều hơn và kém hơn trên ngày spike. Không cấu hình nào đạt tiêu chí "không đánh đổi" |
| D. S6 | **NOT RUN** | Chủ hệ thống quyết định bỏ trong lượt này. Không có số liệu S6 nào |
| E. `customer_id` | **PASS** (mã nguồn, mặc định TẮT) / **BLOCKED** (dữ liệu thật) | Nguồn không có cột khách hàng. Chỉ có test với dữ liệu giả lập; migration 0008 diễn tập 12/12 PASS trên bản sao |
| F. Price, lịch, hạt, forecast tối thiểu, target, `sku_system_status` | **PASS** (không đổi) | Không thay đổi cấu hình hay lịch nào |
| G. Test | **PASS** | Backend 618 passed / 9 skipped (BigQuery thật, opt-in) / 0 failed, exit 0 (12:15–12:28). vitest 149/149, typecheck và build đạt. Lint chưa cấu hình |

---

## 1. Trạng thái ban đầu và repository

- Nhánh `main`, HEAD `0da73b6` (Release 1.2.8), ahead 26 so với `origin/main` (ref local, không fetch).
- **Chưa commit** gì trong đợt này.
- Working tree sau đợt 3: 60 file sửa + 15 file mới = 75 file so với HEAD (`git diff --shortstat`: 1.925 dòng thêm, 217 dòng xóa, chưa tính file mới). Con số gồm cả đợt 1 và đợt 2 của 1.2.9.
- Production DB vẫn ở schema 6. Migration 0007 và 0008 chỉ chạy trên bản sao.
- Báo cáo các đợt trước:
  - `reports/weekday_total_open_hours_mapping_fix.md` (đợt 1);
  - `reports/demandforecast_comprehensive_upgrade_review.md` (đợt 2).

## 2. File đã sửa / thêm trong đợt này

**Backend**

| File | Thay đổi |
|---|---|
| `app/data/open_hours.py` | Trạng thái `MULTI_ITEM`; `coverage_start()`; ghi chú về giữ dữ liệu cuộn 7 tháng |
| `app/bq/connector.py` | Câu D-1 đếm item / số giá trị giờ theo item; tổng hợp khách hàng trong BigQuery khi đã chọn cột; mapping hash chỉ đổi khi chọn cột khách |
| `app/sync.py` | `row_cell`; cảnh báo `OPEN_HOURS_WOULD_BE_LOST` ở xem trước; bộ đếm `open_hours_lost`; ghi 3 cột khách hàng |
| `app/data/customers.py` (mới) | Kiểm tra cột khách (tồn tại, kiểu); lưu số đếm |
| `app/migrations/0008_customer_aggregates.sql` (mới) | 3 cột nullable của `demand_daily`, chỉ thêm |
| `app/settings_service.py` | `model.feature_customer = false`; `data_policy.training_start_rule = WINDOW_START`; `bigquery.customer_id_column = ""` |
| `app/data/demand.py` | `data_window()` theo quy tắc bắt đầu; `excluded_summary()`; `load_demand` đọc 3 cột mới |
| `app/ml/pipeline.py`, `app/data/quality.py`, `app/ml/feature_registry.py`, `app/api/ops_routes.py`, `app/jobs/flows.py` | Cùng một cửa sổ cho huấn luyện, backtest, báo cáo chất lượng, trang Feature, tổng quan; nhóm feature `customer`; lưu ánh xạ cột khách |
| `app/ml/features.py` | 3 feature khách hàng (chỉ đọc ngày đã biết trước mốc); chỉ cấp bộ nhớ khi có dữ liệu; `with_index` cho ma trận huấn luyện |
| `app/ml/model.py` | `train(..., weights=None)`. Chỉ thí nghiệm dùng; ứng dụng không truyền trọng số |
| `app/ml/spike_weights.py` (mới) | Phát hiện spike, phân loại đợt, tính trọng số (chỉ thí nghiệm) |
| `app/ml/feature_catalog.py`, `app/data/identity.py`, `app/data_checks.py` | Danh mục feature khách; danh tính dữ liệu của run; data-check `customer_counts_consistent`, `customer_counts_source_scope`; `MULTI_ITEM` hợp lệ |

**Test**
- Mới:
  - `tests/test_v129c_window_spike_customer.py` (20 hàm test, 30 test khi thu thập vì có tham số hóa);
  - `tests/test_v129c_real_bq_items_customers.py` (opt-in BigQuery thật, dữ liệu nhúng, 0 byte).
- Cập nhật kỳ vọng, không nới lỏng kiểm tra: `test_v129_weekday_open_hours.py`, `test_v129_backfill_history_patterns.py`, `test_v117.py`, `test_v115_bigquery_features.py`, `test_v120_features.py`, `test_v126_eod_backup_close.py`, `test_v126_retention_defaults.py`. Lý do: số cột, số migration, khóa mới trong dict.

**Frontend**
- `pages/Config.tsx`: quy tắc bắt đầu, công tắc nhóm khách hàng.
- `pages/Dashboard.tsx`: ghi chú cửa sổ.
- `pages/Mapping.tsx`: chọn cột khách, chỉ STRING / INTEGER.
- `pages/SqlSources.tsx`: cảnh báo mất giờ mở bán.
- `i18n.tsx`.
- `v129c.test.tsx` (mới, 4 test).

**Tài liệu**
- `CHANGELOG.md` (mục "Third batch").
- `docs/data/DATA-DICTIONARY.md`, `docs/data/DATA-MODEL.md`, `docs/BIGQUERY.md` (§11c), `docs/MO-HINH-VA-CHI-SO.md`.
- `docs/CHECKPOINT.md` (mục đợt 3).

Không đổi: lịch D-0 / D-1 / huấn luyện, Price, hạt dự báo, forecast tối thiểu, target `order_qty` / `demand_quantity`, vai trò của `sku_system_status` (không làm feature).

## 3. Giờ mở bán theo đúng grain (Hạng mục A)

**Nguồn:** `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`.
- 17 cột, không phân vùng.
- Bản làm mới lúc **20/10 00:10 UTC**, 8.939.819 dòng.

Mọi truy vấn chỉ đọc: dry run trước, giới hạn byte, không DML/DDL, không bảng tạm. Đợt này quét khoảng 3,4 GB (3 truy vấn 2,96 GB và hồ sơ theo ngày 0,40 GB). Mã đơn và mã item chỉ ở trong file Excel nội bộ; báo cáo này chỉ có số đếm.

**Các trường xác định khóa trong bảng nguồn:**

| Khái niệm | Trường trong nguồn | Kết luận (kiểm chỉ đọc) |
|---|---|---|
| Ngày | `created_date` (DATE) | ngày của dòng đơn; D-1 dùng làm `order_date` |
| SKU | `sku_code` | |
| FC | `fc_code` | kho xuất hàng (BD, HN) |
| Item | `item_code` = `<sku_code>.<số>` | listing của SKU; 17.114 item, không item nào thuộc 2 SKU; 130 item từng xuất hiện ở 2 FC |
| Miền bán | **không có cột** | suy ra được qua item: mỗi item thường thuộc một FC (vd. `.1` ở BD, `.2` ở HN) |
| Giờ mở bán | `total_open_hours` | **đo theo item × ngày**: 108 item-ngày xuất hiện ở 2 FC trong cùng ngày, giờ luôn giống nhau. Trong một item × FC × ngày không có hai giá trị |

**Kết luận về hai nhóm 26/08 (FC BD).**
- Ngày đó FC BD xuất hàng cho đơn của **item vùng HN** (`.2`, thường ở HN). Vì vậy khóa SKU × FC × ngày có 2 item của 2 miền bán.
- 101 khóa có nhiều item, chỉ xuất hiện trong tháng 2 (35), tháng 3 (55) và ngày 26/08 (11).
  - 9 trong 11 khóa ngày 26/08 có giờ bằng nhau, nên trạng thái OK.
  - 2 khóa có giờ khác nhau: `MEDX.COU-STR-001` (23,72 / 24) và `MEDX.D6TABCV8` (22,85 / 18,22).
- Mỗi item có đúng một giá trị trong ngày. Đây là **khác biệt hợp lệ giữa miền bán**, không phải lỗi dữ liệu và không phải lỗi JOIN:
  - không có dòng trùng;
  - không có nhiều seller;
  - không có nhiều `open_date`.

**Phân loại theo yêu cầu (mục 3.3):**

| Loại | Trên dữ liệu thật | Xử lý |
|---|---|---|
| 1. Khác giờ giữa các miền bán (item) | 2 khóa (26/08). Từ đợt này có trạng thái **`MULTI_ITEM`** riêng thay vì `CONFLICT` | Hợp lệ. Không gắn cờ lỗi; vẫn không có giá trị ở hạt SKU × FC vì chưa có quy tắc gộp được duyệt (không tự chọn MIN/MAX/AVG) |
| 2. Khác giờ giữa các FC | Mọi chuỗi SKU × FC giữ giờ riêng theo FC (hạt dự báo đã có FC) | Giữ nguyên |
| 3. Mâu thuẫn trong cùng khóa nghiệp vụ (cùng item, cùng ngày, hai giá trị) | **0** | `CONFLICT` chỉ còn cho trường hợp này hoặc khi dòng không có item |
| 4. Thiếu / không hợp lệ | NULL toàn bộ trước **20/03** (bản 20/10; bản 19/10 là trước 19/03); 0 dòng âm hay > 24; 2.592 dòng = 0 nhưng có đơn (mục 6) | `MISSING`; giá trị 0 giữ là 0 (OK), cần chủ dữ liệu giải thích |
| 5. Lỗi JOIN / aggregation | Không có lỗi JOIN (D-1 không JOIN; nguồn không có dòng trùng). Lỗi **nhãn** của pipeline: khác biệt hợp lệ giữa item bị ghi `CONFLICT` | Đã sửa trong pipeline (trạng thái `MULTI_ITEM`), không sửa dữ liệu nguồn |

**Hai phát hiện mới về nguồn (ảnh hưởng vận hành):**
1. **Giờ mở bán chỉ giữ cuộn khoảng 7 tháng.**
   - Bản 19/10 có giờ từ 19/03; bản 20/10 chỉ từ 20/03 (ngày 19/03 thành NULL).
   - Mốc trùng với "ngày làm mới − 7 tháng"; cần chủ dữ liệu xác nhận.
   - Hệ quả: mỗi ngày chưa nạp, nguồn mất thêm một ngày giờ mở bán đầu kỳ. Một lần nạp lại / backfill các ngày cũ sẽ thay giá trị đã lưu bằng `MISSING`.
   - Đã thêm cảnh báo `OPEN_HOURS_WOULD_BE_LOST` và bộ đếm `open_hours_lost`.
2. **Nguồn sửa lịch sử ở mỗi lần làm mới.**
   - So với bản sao nạp tối 19/10: 276/291 ngày có tổng số lượng khác, −12.313 đơn vị trên 41,9 triệu.
   - Số dòng bảng: 8.942.586 → 8.939.819.
   - D-1 gia tăng chỉ đọc lại 3 ngày gần nhất, nên dữ liệu đã lưu lệch dần so với nguồn (rất nhỏ, nhưng có thật).

## 4–5. Cửa sổ huấn luyện tạm thời theo giờ mở bán (Hạng mục B)

**Mã nguồn.**
- Thêm `data_policy.training_start_rule`, giá trị `WINDOW_START` hoặc `OPEN_HOURS_COVERAGE`. Mặc định `WINDOW_START`, nên production không đổi.
- Chọn ở Cấu hình > Chính sách dữ liệu.
- Với `OPEN_HOURS_COVERAGE`, ngày bắt đầu = **ngày đầu tiên đã lưu có giờ mở bán**, tính lại từ dữ liệu ở mỗi lần dùng. Không có ngày nào được nhúng trong mã.
- Cùng một quy tắc cho huấn luyện, backtest, panel dự báo, kiểm tra giờ mở bán, báo cáo chất lượng dữ liệu, trang Feature và data-check.
- Ngày trước mốc vẫn lưu và vẫn được D-1 / backfill đọc (mốc đọc vẫn là `window_start_date`). Mapping hash không đổi.
- Mỗi lần huấn luyện lưu `data_window.excluded_summary`: số ngày, số dòng, số chuỗi, chuỗi chỉ có trong phần bị loại, số lượng và tỷ lệ.

**Số liệu** (bản sao DB production 19/10 + lần nạp diễn tập; hàm của ứng dụng; chỉ đọc):

| | Theo dữ liệu đã lưu (giờ mở bán từ 19/03) | Nếu nạp lại với nguồn 20/10 (từ 20/03) |
|---|---|---|
| Khoảng dùng cho mô hình | 19/03 – 18/10, 214 ngày | 20/03 – 18/10, 213 ngày |
| Khoảng bị loại tạm thời | 01/01 – 18/03, 77 ngày | 01/01 – 19/03, 78 ngày |
| Dòng ngày × SKU × FC bị loại | 400.082 (29,5%) | 405.527 (29,9%) |
| Nhu cầu bị loại | 13,49 triệu (**32,2%**) | 13,70 triệu (32,7%) |
| Chuỗi có dữ liệu trong phần bị loại | 14.138 | 14.171 |
| Chuỗi **chỉ** có trong phần bị loại | 550 | 558 |
| Dòng trong cửa sổ / không OK | 954.891 / **2** (26/08) | — |

**Lưu ý quan trọng:** quy tắc này **không tự gỡ được chặn huấn luyện**. Trong cửa sổ còn 2 khóa ngày 26/08: trên bản sao đang là `CONFLICT`; khi nạp lại bằng mã mới sẽ thành `MULTI_ITEM`. Cổng `OPEN_HOURS_INVALID` vẫn dừng huấn luyện BigQuery cho tới khi chủ hệ thống duyệt cách xử lý 2 dòng này. Ví dụ:
- coi là "không biết" (NaN);
- lấy giờ của item thuộc chính FC đó;
- MAX.

**Tết 2026 (13–21/02) nằm trọn trong phần bị loại.**
- 20.300 dòng, 265.726 đơn vị.
- Nhu cầu mỗi ngày giảm từ khoảng 280 nghìn (09/02) xuống 11–17 nghìn (14–18/02), rồi về khoảng 237 nghìn (23/02).
- Không fold backtest nào chứa Tết. Vì vậy **không đo được** ảnh hưởng lên dự báo Tết 2027 (khoảng 06/02/2027) bằng backtest.
- Rủi ro: cửa sổ cuộn 7 tháng của nguồn sẽ không bao giờ chứa Tết trước tháng 9/2027, trừ khi ứng dụng giữ các ngày đã nạp (D-1 gia tăng giữ) và không nạp lại toàn kỳ.
- Tháng 1–3 cũng có nhu cầu bình quân / ngày cao nhất năm: 179 / 161 / 198 nghìn, so với 79 nghìn của tháng 10.

**So sánh cửa sổ trên bản sao** (kết quả đã lưu của 19/10, cùng điểm đánh giá, không huấn luyện lại):
- E00: cửa sổ từ 01/01, không giờ mở bán.
- O0: từ 19/03, không giờ mở bán.
- O1: từ 19/03 + giờ mở bán; tái lập bit-for-bit hôm nay thành S0.

| | E00 sàng lọc | O0 sàng lọc | O1 sàng lọc | E00 giữ lại | O0 giữ lại | O1 giữ lại |
|---|---|---|---|---|---|---|
| WAPE | 0,7972 | 0,7963 | 0,7977 | 0,7983 | 0,8061 | **0,7959** |
| Bias | +1,5% | +1,7% | +1,7% | −9,6% | −7,9% | −8,8% |
| Phần nhu cầu bị thiếu (under) | 39,1% | 39,0% | 39,1% | 44,7% | 44,3% | 44,2% |
| WAPE tổng 30 ngày / chuỗi | 0,477 | 0,474 | 0,477 | 0,486 | 0,491 | **0,476** |
| Under tổng 30 ngày | 23,1% | 22,9% | 23,0% | 29,1% | 28,5% | 28,2% |
| Ngày spike / ngày thường | 0,855 / 0,786 | 0,854 / 0,785 | 0,856 / 0,786 | 0,845 / 0,788 | 0,846 / 0,797 | 0,832 / 0,788 |
| SMOOTH / ERRATIC | 0,528 / 0,839 | 0,529 / 0,837 | 0,532 / 0,836 | 0,440 / 0,886 | 0,438 / 0,901 | 0,432 / 0,893 |
| Ngày 1–7 / 16–30 | 0,713 / 0,835 | 0,707 / 0,835 | 0,710 / 0,837 | 0,743 / 0,833 | 0,746 / 0,848 | 0,735 / 0,837 |
| Chuỗi tốt hơn / kém hơn E00 | — | 15.262 / 13.970 | 13.938 / 15.294 | — | 2.106 / 2.666 | 2.537 / 2.235 |

Fold sàng lọc: 4 fold 30 ngày (22/05, 21/06, 21/07, 20/08), 51.012 chuỗi-fold có nhu cầu. Fold giữ lại: 19/09–18/10.

**Kết luận:**
- Rút cửa sổ về giai đoạn có giờ mở bán (O1) **không làm giảm độ chính xác đo được**: bằng E00 khi sàng lọc, tốt hơn chút ở fold giữ lại, ít dự báo thiếu hơn chút.
- Trên fold giữ lại, rút cửa sổ mà không có giờ mở bán (O0) kém hơn.
- Độ ổn định theo chuỗi: khi sàng lọc, số chuỗi kém hơn E00 nhỉnh hơn số chuỗi tốt hơn (15.294 so với 13.938); ở fold giữ lại thì ngược lại.
- Chi phí chưa đo được: mất mùa Tết và đầu năm; 550 chuỗi chỉ có trong phần bị loại.

## 6. Excel kiểm tra "giờ mở bán = 0 nhưng có đơn" (Hạng mục C)

**File:** `D:\Buymed\Lightgbm AI\reports\zero_open_hours_orders_20261020.xlsx`
- SHA-256 `67FA5E809CD6F3A20F353B6A0B02E212FD73F792C60341433FA8147E15399EAD`.
- Nằm ngoài Git, không upload đi đâu.

**Nguồn và điều kiện:**
- Truy vấn chỉ đọc trên BigQuery (bản 20/10 00:10 UTC): `created_date BETWEEN '2026-01-01' AND '2026-10-19' AND total_open_hours = 0 AND demand_quantity > 0`.
- 1,30 GB quét (một trong 3 truy vấn ở mục 3).
- Target = `demand_quantity`, đúng semantics của pipeline (số lượng lúc tạo đơn); không thay bằng số đã xuất.

| Sheet | Nội dung |
|---|---|
| `Summary` | thời điểm trích xuất, nguồn và phiên bản bảng, điều kiện lọc chính xác, số dòng truy vấn / trong file, số SKU / FC / item / đơn / ngày / khóa, tổng số lượng, phân bố theo tháng / FC / `order_status` / `seller_class`, kết quả đối chiếu, giới hạn |
| `Zero_Hours_Orders` | 2.592 dòng đơn × item với cột gốc của nguồn: `created_date`, `fc_code`, `sku_code`, `product_id`, `item_code`, `seller_class`, `so_code`, `order_status`, `demand_quantity`, `outbound_quantity`, `open_date`, `total_open_hours`, `total_open_days`, `refresh_time`. Thêm: `d1_valid_line`; trạng thái / giá trị / số lượng của khóa trong pipeline; `check_notes` theo quy tắc rõ ràng |
| `Keys_SKU_FC_Day` | 722 khóa ngày × SKU × FC (hạt của pipeline): số dòng, đơn, item, số lượng từ nguồn và từ pipeline, kết quả khớp |
| `By_Day` | 184 ngày: số dòng, số lượng, khóa, tỷ trọng trong nhu cầu của ngày |

File không có cột khách hàng (nguồn không có) và không có dữ liệu cá nhân. Mã đơn (`so_code`) và mã item là mã nội bộ, chỉ nằm trong file này.

**Kết quả** (đọc lại workbook bằng `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\verify_xlsx.py`):
- **2.592 / 2.592 dòng**; mọi dòng đúng điều kiện (giờ = 0 và số lượng > 0).
- Kiểu dữ liệu đúng: ngày là ngày, `so_code` là chữ, số lượng là số nguyên.
- Từng trường khớp truy vấn; tổng 20.987 = 20.987.

| Chỉ số | Giá trị |
|---|---|
| Dòng đơn × item | 2.592 (mọi dòng đều hợp lệ theo quy tắc D-1) |
| Khóa ngày × SKU × FC | 718 từ nguồn hôm nay; 722 trong bản sao nạp tối 19/10 |
| Đối chiếu khóa | **718 khớp hoàn toàn** (giờ = 0, trạng thái OK, cùng số lượng). 4 khóa chỉ còn trong bản sao (19/03 và 31/07, 38 đơn vị): nguồn đã đổi sáng 20/10 |
| Tổng số lượng | 20.987 (nguồn hôm nay) / 21.025 (bản sao) |
| Đơn đã xuất hàng (`outbound_quantity` > 0) | **1.398 / 2.592 dòng** |
| `open_date` ≠ `created_date` | 0 |
| `total_open_days` ≠ 0 | 0 |

**Kết luận:**
- **Không có lỗi xuất của ứng dụng.** Mọi khóa của pipeline khớp đúng dòng nguồn; 4 khóa lệch là do nguồn thay đổi giữa hai lần đọc.
- Giờ = 0 có thật trong nguồn, và hơn nửa số dòng đã được xuất hàng. Vậy "0 giờ mở bán" mâu thuẫn với việc đã bán, ít nhất theo nghĩa "không mở bán lúc nào trong ngày". Một số cách hiểu khả dĩ, **chưa xác minh**:
  - đơn tạo qua kênh không qua listing;
  - giờ mở tính theo một mốc khác ngày đơn;
  - lỗi tính ở nguồn.
- Cần chủ dữ liệu giải thích trước khi đặt quy tắc. Ứng dụng giữ 0 là 0, không đổi thành "thiếu".

## 7. Thí nghiệm spike S0–S5 (Hạng mục D)

### 7.1 Thiết kế (ghi trước khi chạy)

Kế hoạch đặt trước: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\exp\plan_spike.json` (ghi trước lần chạy đầu, không sửa sau đó).

**Dữ liệu**
- Bản sao `scratchpad\p18\e8`: DB production 19/10 22:38 + lần nạp diễn tập D-1 có giờ mở bán, nâng schema 8.
- Chỉ đọc; không publish gì; không model nào của production được dùng hay thay.
- Môi trường cô lập: `DF_DATA_DIR`, `LOCALAPPDATA` riêng, `DF_DISABLE_SCHEDULER=1`.

**Cửa sổ**
- `OPEN_HOURS_COVERAGE`: 19/03–18/10, 214 ngày, 16.578 chuỗi, 954.889 ngày có giờ mở bán.
- Cài đặt model của production; giờ mở bán BẬT; 33 feature; Price giữ nguyên.

**Fold**
- 4 fold sàng lọc, mốc 22/05, 21/06, 21/07, 20/08 (30 ngày mỗi fold).
- 1 fold giữ lại, mốc 19/09 (19/09–18/10).
- Fold giữ lại chỉ để báo cáo, **không dùng để chọn**.

**Cách hạ trọng số** (giả thuyết của chủ hệ thống, không phải quy tắc nghiệp vụ):
- Chỉ đổi trọng số của dòng huấn luyện trong hàm mất mát LightGBM. **Không** sửa, cắt, winsorize hay xóa giá trị nhu cầu nào.
- Một ngày là spike khi:
  - ≥ 10 đơn vị;
  - lớn hơn cả 3 × trung vị ngày dương và trung vị + 5 × 1,4826 × MAD của chính chuỗi đó;
  - tính trên 91 ngày trước (ngưỡng của `demand_patterns`).
- "Rolling": ngưỡng của ngày t chỉ dùng các ngày trước t. "Cutoff" (S4): ngưỡng từ 91 ngày trước mốc fold.
- Trọng số chỉ tính từ dữ liệu trước mốc. Đợt spike còn "mở" (chưa biết ngày sau) được phân loại theo những gì đã biết tại mốc.
- Phân loại đợt spike:
  - `SINGLE`: 1 ngày, ngày sau bình thường;
  - `OPEN_SINGLE`: spike ở ngày cuối đã biết;
  - `DOUBLE_OPEN`: 2 ngày, ngày thứ 3 chưa biết;
  - `DOUBLE_CLOSED`: 2 ngày, ngày thứ 3 bình thường;
  - `LONG`: ≥ 3 ngày liên tiếp.

| Cấu hình | Trọng số | Phát hiện | Ý nghĩa |
|---|---|---|---|
| S0_base | không | — | Baseline = O1 của 19/10 (tái lập bit-for-bit) |
| S1_single | SINGLE / OPEN_SINGLE 0,25 | rolling | Chỉ hạ spike 1 ngày |
| S2_repeat_light | SINGLE / OPEN_SINGLE 0,25; DOUBLE_OPEN / DOUBLE_CLOSED 0,6 | rolling | Spike 2 ngày hạ nhẹ |
| S3_day3_restore | SINGLE / OPEN_SINGLE 0,25; DOUBLE_OPEN 0,6; DOUBLE_CLOSED 0,25 | rolling | Đúng giả thuyết: 1 ngày hạ; ngày 2 lặp lại thì học; ngày 3 mất thì hạ lại; ≥ 3 ngày giữ 1,0 |
| S4_day3_cutoff | như S3 | cutoff | Như S3, ngưỡng tính trước mốc fold |
| S5_soft | mọi ngày spike = ngưỡng / giá trị | rolling | Hạ mềm: ngày spike tính như một ngày đúng bằng ngưỡng |

**Quy tắc chọn** (nguyên văn trong kế hoạch, dịch): so với S0 **chỉ trên 4 fold sàng lọc**. Một cấu hình là "không đánh đổi" khi thỏa cả 3 điều kiện:
- WAPE gộp **thấp hơn**;
- phần thiếu của tổng 30 ngày **không cao hơn**;
- WAPE ngày spike **không cao hơn quá 0,01**.

Nếu không thỏa, cấu hình là "đánh đổi" (TRADE_OFF). Fold giữ lại được báo cáo cho mọi cấu hình nhưng không dùng để chọn. Không promote, không áp dụng gì.

**Ngân sách:**
- tối đa 36 lượt huấn luyện fold, 3,5 giờ, RAM trống tối thiểu 0,6 GB, 8 luồng;
- tạm dừng trong các khung quanh lịch production (dẫn trước 4 phút);
- dừng ngay khi có job production đang chạy.

### 7.2 Thực hiện

- **Lần chạy 1** (09:56): tạm dừng đúng trong khung 09:50–10:10, rồi lỗi ở fold đầu.
  - Nguyên nhân: `np.vstack` trên danh sách chỉ số rỗng khi không yêu cầu chỉ số (lỗi trong `_stack` của mã mới).
  - Đã sửa trước khi chạy lại.
  - Log giữ ở `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\exp\run_console_1_failed.txt`.
- **Lần chạy 2:** 10:17:37 – 11:27:38.
  - **30/30 lượt huấn luyện fold**, 1,17 giờ.
  - Không tạm dừng; RAM trống thấp nhất 1,45 GB (mẫu ghi sau mỗi fold).
  - Không có job production chạy trong thời gian đó.
- **S0 tái lập O1 bit-for-bit** (cùng dự báo): mã mới và bản sao `e8` cho đúng kết quả của ngày 19/10.

**Kết quả gốc (giữ nguyên, không ghi đè)** trong `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\exp\`:
- `run\*.npz`: 30 file, dự báo / thực tế từng chuỗi, 102 MB.
- `run\summary.jsonl`, `run\harness.log`.
- `screen_analysis.json` và `holdout_analysis.json`: đọc lại các npz bằng `spike_analyze.py`, không huấn luyện.

Mọi số dưới đây lấy từ các file này. Đã đối chiếu lại lúc 12:20: số trong báo cáo khớp artifact.

### 7.3 Kết quả 4 fold sàng lọc

Phạm vi: 1.849.670 điểm có thực tế, 15,45 triệu đơn vị. Trong đó ngày spike là 17.541 điểm, 2,61 triệu đơn vị (**16,9%** nhu cầu).

| Cấu hình | WAPE | Bias | Phần thiếu (under) | MAE | WAPE ngày spike | WAPE ngày thường | Dự báo / thực tế | Kết luận theo quy tắc |
|---|---|---|---|---|---|---|---|---|
| S0 | 0,7977 | +1,67% | 39,05% | 6,666 | 0,8582 | 0,7855 | 1,017 | baseline |
| S1 | 0,7709 | −3,50% | 40,29% | 6,441 | 0,8684 | 0,7510 | 0,965 | TRADE_OFF |
| S2 | 0,7686 | −3,75% | 40,30% | 6,422 | 0,8685 | 0,7482 | 0,963 | TRADE_OFF |
| S3 | **0,7658** | −4,86% | 40,72% | **6,398** | 0,8715 | **0,7443** | 0,951 | TRADE_OFF |
| S4 | 0,7669 | −4,10% | 40,39% | 6,407 | 0,8711 | 0,7456 | 0,959 | TRADE_OFF |
| S5 | 0,7738 | −2,24% | 39,81% | 6,465 | 0,8685 | 0,7545 | 0,978 | TRADE_OFF |

**Tổng theo chuỗi trong 7 / 15 / 30 ngày đầu** (lượng một lần đặt hàng phải phủ), dạng WAPE / phần thiếu. Chuỗi-fold so với S0 tính theo tổng sai số tuyệt đối của chuỗi trong fold, trên 51.012 chuỗi-fold có nhu cầu.

| Cấu hình | Tổng 7 ngày | Tổng 15 ngày | Tổng 30 ngày | Bias tổng 30 ngày | Chuỗi-fold tốt hơn / kém hơn / bằng S0 |
|---|---|---|---|---|---|
| S0 | 0,4908 / 25,44% | 0,4785 / 24,95% | 0,4765 / **22,99%** | +1,67% | — |
| S1 | 0,4699 / 26,91% | 0,4586 / 26,46% | 0,4570 / 24,60% | −3,50% | 20.515 / 8.007 / 22.490 |
| S2 | 0,4667 / 27,20% | 0,4574 / 26,56% | 0,4563 / 24,69% | −3,75% | 20.182 / 8.340 / 22.490 |
| S3 | 0,4689 / 27,58% | 0,4569 / 27,08% | **0,4543** / 25,15% | −4,86% | 20.333 / 8.189 / 22.490 |
| S4 | 0,4696 / 27,22% | 0,4569 / 26,55% | 0,4549 / 24,79% | −4,10% | 20.575 / 7.947 / 22.490 |
| S5 | 0,4721 / 26,46% | 0,4592 / 25,87% | 0,4575 / 24,00% | −2,24% | 18.714 / 9.808 / 22.490 |

**Theo quy tắc chọn:**
- Mọi cấu hình đạt điều kiện 1 (WAPE thấp hơn).
- Mọi cấu hình **trượt** điều kiện 2: phần thiếu tổng 30 ngày tăng từ 22,99% lên 24,00–25,15%.
- Mọi cấu hình **trượt** điều kiện 3: WAPE ngày spike tăng 0,0102–0,0133 so với S0. S1 cao hơn 0,0102, chỉ vừa vượt ngưỡng 0,01.
- Kết quả: **không cấu hình nào "không đánh đổi"**.

**WAPE ngày spike theo loại** (đại diện từ số đơn trong ngày; nguồn không có trường khuyến mãi / đơn sỉ):

| Cấu hình | BULK_LIKE (≤ 2 đơn) | BROAD (≥ 3 đơn và ≥ 2 × trung vị số đơn) | OTHER |
|---|---|---|---|
| Số điểm / đơn vị | 6.782 / 291.737 | 8.093 / 996.524 | 2.666 / 1.324.274 |
| S0 | 0,9079 | 0,8558 | 0,8490 |
| S1 | 0,9226 | 0,8653 | 0,8588 |
| S2 | 0,9239 | 0,8656 | 0,8585 |
| S3 | 0,9250 | 0,8685 | 0,8620 |
| S4 | 0,9249 | 0,8676 | 0,8619 |
| S5 | 0,9197 | 0,8656 | 0,8594 |

**Theo nhóm nhu cầu và ngày trong kỳ** (WAPE):

| Cấu hình | SMOOTH | ERRATIC | INTERMITTENT | LUMPY | HIGH_VOLUME | Ngày 1–7 | Ngày 8–15 | Ngày 16–30 |
|---|---|---|---|---|---|---|---|---|
| S0 | 0,5305 | 0,8429 | 1,2905 | 1,3860 | 0,6969 | 0,7100 | 0,8011 | 0,8372 |
| S1 | 0,5223 | 0,8119 | 1,2785 | 1,3030 | 0,6763 | 0,6826 | 0,7758 | 0,8097 |
| S2 | 0,5219 | 0,8080 | 1,2788 | 1,3000 | 0,6740 | 0,6797 | 0,7732 | 0,8079 |
| S3 | 0,5225 | 0,8030 | 1,2756 | 1,2940 | 0,6718 | 0,6808 | 0,7696 | 0,8036 |
| S4 | 0,5209 | 0,8052 | 1,2744 | 1,3008 | 0,6729 | 0,6808 | 0,7718 | 0,8047 |
| S5 | 0,5258 | 0,8144 | 1,2786 | 1,3065 | 0,6773 | 0,6872 | 0,7773 | 0,8126 |

**WAPE từng fold** (mọi điểm của fold, từ `summary.jsonl`):

| Cấu hình | 22/05 | 21/06 | 21/07 | 20/08 | 19/09 (giữ lại) |
|---|---|---|---|---|---|
| S0 | 0,7002 | 0,7269 | 0,7993 | 1,0969 | 0,7959 |
| S1 | 0,6820 | 0,7096 | 0,7662 | 1,0467 | 0,7805 |
| S2 | 0,6778 | 0,7069 | 0,7640 | 1,0485 | 0,7667 |
| S3 | 0,6778 | 0,7038 | 0,7591 | 1,0440 | 0,7626 |
| S4 | 0,6783 | 0,7072 | 0,7560 | 1,0483 | 0,7603 |
| S5 | 0,6835 | 0,7076 | 0,7716 | 1,0568 | 0,7662 |

- Mọi cấu hình có WAPE thấp hơn S0 ở cả 5 fold.
- Bias của S0 theo fold: −11,1%, −2,7%, +10,4%, +20,4%, −8,8%.
- Fold 20/08 (20/08–18/09) có WAPE > 1 với mọi cấu hình; S0 dự báo dư 20,4% ở fold này. Nguyên nhân chưa phân tích trong đợt này.

**Số ngày spike phát hiện / hạ trọng số / giữ 1,0** (tổng của 4 fold sàng lọc). Mỗi fold tính lại từ dữ liệu trước mốc của nó, nên một ngày có thể được đếm ở nhiều fold.

| Cấu hình | Ngày spike phát hiện | Hạ trọng số | Giữ 1,0 |
|---|---|---|---|
| S1 | 76.300 | 62.150 | 14.150 |
| S2 | 76.300 | 70.530 | 5.770 |
| S3 | 76.300 | 70.530 | 5.770 |
| S4 (cutoff) | 75.481 | 67.560 | 7.921 |
| S5 | 76.300 | 76.300 | 0 |

Phân loại theo số ngày spike (rolling), dạng ngày / đợt:
- SINGLE 61.656
- OPEN_SINGLE 494
- DOUBLE_OPEN 82 / 41 đợt
- DOUBLE_CLOSED 8.298 / 4.149 đợt
- LONG 5.770 / 1.374 đợt

Theo cutoff (S4):
- SINGLE 58.740
- OPEN_SINGLE 452
- DOUBLE_OPEN 66
- DOUBLE_CLOSED 8.302
- LONG 7.921

Ngày spike chiếm 14,4% nhu cầu đã biết của các panel huấn luyện (9,93 / 68,96 triệu, rolling).

Chỉ 0,65–1,35% số dòng huấn luyện có trọng số < 1. Tổng trọng số giảm 0,26–0,93%.

### 7.4 Kết quả fold giữ lại (19/09–18/10, không dùng để chọn)

Phạm vi: 493.379 điểm, 2,46 triệu đơn vị. Ngày spike: 4.016 điểm, 18,0% nhu cầu.

| Cấu hình | WAPE | Bias | Under | MAE | WAPE ngày spike | WAPE ngày thường | Tổng 7 ngày (WAPE / under) | Tổng 30 ngày (WAPE / under) | Chuỗi tốt hơn / kém hơn / bằng S0 |
|---|---|---|---|---|---|---|---|---|---|
| S0 | 0,7959 | −8,79% | 44,19% | 3,976 | 0,8324 | 0,7879 | 0,5158 / 31,06% | 0,4758 / 28,19% | — |
| S1 | 0,7805 | −11,93% | 44,99% | 3,899 | 0,8450 | 0,7663 | 0,5202 / 31,58% | 0,4752 / 29,73% | 2.703 / 2.026 / 5.919 |
| S2 | 0,7667 | −15,05% | 45,86% | 3,830 | 0,8552 | 0,7474 | 0,5147 / 34,02% | 0,4659 / 30,82% | 2.831 / 1.898 / 5.919 |
| S3 | 0,7626 | −14,98% | 45,62% | 3,810 | 0,8518 | 0,7430 | 0,5090 / 33,45% | 0,4591 / 30,45% | 3.115 / 1.614 / 5.919 |
| S4 | **0,7603** | −15,08% | 45,55% | 3,799 | 0,8525 | 0,7401 | 0,5019 / 33,90% | **0,4505** / 30,06% | 2.928 / 1.801 / 5.919 |
| S5 | 0,7662 | −13,95% | 45,28% | 3,828 | 0,8458 | 0,7487 | 0,5000 / 33,15% | 0,4516 / 29,55% | 2.793 / 1.936 / 5.919 |

Trên fold giữ lại:
- Hướng giống sàng lọc: WAPE giảm, phần thiếu và WAPE ngày spike tăng.
- Bias âm thêm 3,1–6,3 điểm phần trăm.
- Dự báo / thực tế: S0 0,912, S3 0,850.
- Với S1, WAPE tổng 7 ngày còn kém S0 (0,5202 so với 0,5158).

### 7.5 Vì sao WAPE giảm nhưng dự báo spike kém đi (trade-off)

Ở S0, mô hình **dư trên ngày thường và thiếu nặng trên ngày spike** (sàng lọc):

| Loại ngày | Bias | Ghi chú |
|---|---|---|
| Ngày thường (83% nhu cầu) | +19,4% | |
| Ngày spike | −85,5% | Dự báo chỉ phủ khoảng 14,5% lượng spike |

**Hạ trọng số spike làm mức dự báo chung thấp xuống:**
- Bias ngày thường: +19,4% → +11,8% (S3).
- Phần dư (over) của ngày thường: 49,0% → 43,1%.
- Do ngày thường chiếm phần lớn nhu cầu, WAPE gộp giảm.

Phần nhu cầu spike là **nhu cầu thật**. Mức thấp hơn nên phần thiếu tăng ở mọi thước đo:
- ngày spike: under 85,7% → 87,1%;
- tổng 30 ngày theo chuỗi: 23,0% → 25,2%; ở fold giữ lại 28,2% → 30,5%;
- dự báo / thực tế: 1,017 → 0,951.

**Hệ quả:**
- Phần lớn mức giảm WAPE đến từ **dự báo ít đi**, không phải từ dự báo spike tốt hơn.
- Về tồn kho, đó là rủi ro hết hàng cao hơn, trừ khi tồn kho an toàn bù lại.

Một quan sát (không phải kết luận nhân quả đã kiểm chứng): chỉ khoảng 1% dòng huấn luyện bị hạ trọng số mà tổng dự báo giảm 3,8–6,5% (dự báo / thực tế 1,017 → 0,951–0,978). Ngày spike có giá trị lớn nên ảnh hưởng mạnh tới mức mô hình học.

**Về giả thuyết của chủ hệ thống:**
- **Spike 1 ngày là nhiễu (S1)?**
  - Hạ riêng spike 1 ngày đã cho phần lớn mức giảm WAPE: 0,7977 → 0,7709.
  - Nhưng mọi loại ngày spike đều dự báo kém hơn, kể cả loại giống đơn lẻ / đơn sỉ (BULK_LIKE 0,908 → 0,923).
  - Dữ liệu không cho thấy nhóm nào "an toàn để bỏ qua".
- **Ngày 3 mất thì hạ lại (S3 so với S2, chỉ khác DOUBLE_CLOSED 0,25 so với 0,6):**
  - WAPE thấp hơn: 0,7658 so với 0,7686.
  - Thiếu nhiều hơn: tổng 30 ngày 25,15% so với 24,69%.
  - Vẫn là cùng một đánh đổi.
- **Cách phát hiện (S4 cutoff so với S3 rolling):** khác rất ít khi sàng lọc. Ở fold giữ lại S4 có WAPE thấp nhất, nhưng bias cũng âm nhất.
- **Hạ mềm (S5):** thay đổi nhỏ nhất theo cả hai chiều (WAPE 0,7738, thiếu tổng 30 ngày 24,00%).
- **So với đợt 2:** cùng hướng với cách chặn spike khi huấn luyện của đợt 2 (E14: WAPE giảm, bias 30 ngày −16,4%). Không so trực tiếp được vì khác cửa sổ (từ 01/01) và tham số (63 lá).

### 7.6 S6: chưa chạy

**Quy tắc chọn S6** (đặt trước khi chạy, trong `plan_spike.json`):
- Nếu cấu hình tốt nhất trong S1–S5 (WAPE sàng lọc thấp nhất) có bias tổng 30 ngày âm hơn S0 quá 2 điểm phần trăm, S6 = cấu hình đó với mọi trọng số 0,25 đổi thành 0,5.
- Nếu không, S6 = cấu hình đó + 63 lá.

**Áp dụng quy tắc:**
- Tốt nhất là S3.
- Bias tổng 30 ngày −4,86% so với +1,67%, chênh 6,5 điểm.
- Vậy S6 *sẽ là* S3 với trọng số 0,5: `SINGLE` / `OPEN_SINGLE` / `DOUBLE_CLOSED` 0,5, `DOUBLE_OPEN` 0,6, `LONG` 1,0, rolling.

**S6 không chạy.**
- Quyết định của chủ hệ thống ngày 20/10, sau khi xem S0–S5: bỏ S6 trong lượt này, không huấn luyện thêm.
- Lý do: mọi cấu hình hiện có đều đánh đổi WAPE với dự báo thiếu, chưa cấu hình nào đạt tiêu chí chọn.

Không có số liệu, ước lượng hay suy đoán nào cho S6. `plan_spike.json` không có mục S6; thư mục `run\` không có file S6.

Nếu sau này được duyệt chạy, S6 cần 5 lượt huấn luyện fold (khoảng 10–20 phút) trên cùng bản sao. Ngân sách còn 6 lượt.

### 7.7 Kết luận nghiên cứu (không phải quyết định triển khai)

- Hạ trọng số spike **giảm WAPE ổn định**:
  - −2,4 đến −3,2 điểm khi sàng lọc;
  - −1,5 đến −3,6 điểm ở fold giữ lại;
  - ở cả 5 fold;
  - số chuỗi-fold tốt hơn gấp 2,4–2,6 lần số kém hơn (S1–S4; S5 1,9 lần).
- Cái giá là **dự báo thiếu nhiều hơn** và **kém hơn trên ngày spike**. Theo quy tắc đặt trước, **không cấu hình nào được chọn**.
- **Không model nào được chấp nhận hay promote.** S3 / S4 **không** phải model được phép dùng. `spike_weights.py` và `model.train(weights=...)` chỉ dành cho thí nghiệm: huấn luyện của ứng dụng không truyền trọng số (có test `test_the_application_training_never_passes_spike_weights`).
- Nếu muốn đi tiếp, đây là quyết định nghiệp vụ, không phải kỹ thuật: chấp nhận thêm 1,0–2,2 điểm phần trăm dự báo thiếu của tổng 30 ngày khi sàng lọc (1,4–2,6 điểm ở fold giữ lại) để đổi lấy WAPE thấp hơn. Nên đánh giá bằng chi phí hết hàng / tồn kho hoặc mức phục vụ, không chỉ WAPE.
- Muốn tách spike "nhiễu" khỏi spike "thật" cần trường nguồn (khuyến mãi, đơn sỉ, kênh), hiện không có.

## 8. customer_id (Hạng mục E): sẵn sàng, mặc định TẮT

**Thiết kế** (giữ hạt dự báo SKU × FC; mã khách không bao giờ rời BigQuery):

| Phần | Cách làm |
|---|---|
| Cột nguồn | `bigquery.customer_id_column`, mặc định trống. Chọn trên trang Ánh xạ (chỉ cột STRING / INTEGER). Kiểm tra cột tồn tại ở nguồn khi lưu và trước mỗi lần nạp (`COLUMN_NOT_FOUND` / `TYPE_NOT_ALLOWED`) |
| Mapping hash | Chỉ đổi khi đặt cột. Để trống thì hash giữ nguyên `bc5fcb06327569fb` (đã kiểm trên bản sao): sau deploy không phải kiểm tra lại, không phải nạp lại toàn kỳ |
| Tổng hợp | Trong câu D-1, theo ngày × SKU × FC: `customer_count` (khách khác nhau), `repeat_customer_count` (đã đặt cùng SKU × FC trong 90 ngày trước), `repeat_interval_days_sum` (tổng số ngày từ lần đặt trước). Đọc thêm 90 ngày trước khoảng nạp chỉ để tính số này. Mã rỗng / khoảng trắng / NULL không tính là khách, nhưng nhu cầu của dòng vẫn tính đủ |
| Lưu | Migration **0008**: 3 cột nullable của `demand_daily`. NULL = chưa biết, không phải 0 |
| Feature | `cust_mean_28`, `cust_repeat_share_28`, `cust_repeat_interval_28`: các ngày **đã biết** trong 28 ngày trước ngày dự báo / mốc dự báo |
| Công tắc | `model.feature_customer = false`. Chỉ dùng khi bật **và** độ phủ ≥ `feature_min_coverage`; nếu không, nhóm bị bỏ khỏi lần huấn luyện đó và các feature khác không đổi |
| Truy vết | Cấu hình đã phân giải lưu cùng mỗi lần huấn luyện; danh tính dữ liệu của run dùng nhóm này băm thêm 3 cột; giải thích dùng đúng danh sách feature của model |
| Kiểm tra dữ liệu | data-check `customer_counts_consistent`, `customer_counts_source_scope` |

**Chống rò rỉ:**
- Số của ngày d chỉ dùng đơn tới ngày d.
- Feature tại mốc T chỉ đọc các ngày trước T.
- Test: đổi mọi số từ ngày T trở đi thì feature tại T không đổi; đổi ngày T−1 thì feature đổi.

**Bảo mật:**
- Câu SELECT cuối chỉ có số đếm.
- Bảng ứng dụng không có cột mã khách.
- Kết quả job không nêu cột mã khách.
- Test BigQuery thật trên dữ liệu nhúng: không chuỗi mã nào trả về.

Đếm chỉ giữ mã khách ngoài ứng dụng; đó **không** phải ẩn danh hóa nguồn.

**Đánh giá ON/OFF:** không làm được trên dữ liệu thật, vì bảng nguồn **không có cột khách hàng** (17 cột, kiểm lại 20/10). Chỉ có test với **dữ liệu giả lập**, ghi rõ là giả lập:
- bật thì có 3 feature và giải thích khớp;
- tắt thì backtest và dự báo **giống hệt** lần chưa có số khách;
- hạt SKU × FC không đổi.

Chưa có bằng chứng nào về hiệu quả thực tế.

**Diễn tập migration 0008** trên bản sao mới `scratchpad\p18\e8` (DB production 19/10 + lần nạp diễn tập, schema 7 → 8): **12/12 PASS**.
- Số dòng mọi bảng giống hệt; chỉ `schema_migrations` +1.
- Giá trị cũ của `demand_daily` giống hệt (hash); trạng thái giờ mở bán giống hệt.
- Settings / runs / jobs / sync_state giống hệt (hash).
- 3 cột mới thêm cuối, đều NULL; trigger không đổi; `integrity_check` ok.
- Chạy lần 2 không làm gì.
- App khởi động; 6 API GET trả 200.
- Mapping hash không đổi; validation vẫn hợp lệ.
- 30,9 s, kể cả backup tự động `backup-20261020-101416-pre-migration-v7.zip` (83 MB, SHA-256 `6A9F4F9F…B11B`).
- data-check: FAIL `accepted_model_files` chỉ vì bản sao không có file model (như lần trước).

**Rollback:** 1.2.8 từ chối schema > 6, nên quay về = khôi phục backup trước nâng cấp. Câu lệnh đảo ngược của 0008 (chỉ cho bản sao) có trong file migration và đã chạy trong test.

## 9. Kiểm thử

**Backend: lần chạy cuối, trên mã cuối của đợt**

- Lệnh: `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` (gọi qua Git Bash).
- Log: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\pytest_full2.txt`.
- 12:15:16 – 12:28:47 (13 phút 28 giây), **exit code 0**.

| Kết quả | Số lượng |
|---|---|
| PASS | **618** |
| FAIL / ERROR | **0** |
| SKIPPED | 9: toàn bộ là test BigQuery thật opt-in, cần `DF_REAL_BQ=1` (`test_bq_real_semantics.py` 2, `test_v121_d0_real_bq.py` 5, `test_v129_real_bq_open_hours.py` 1, `test_v129c_real_bq_items_customers.py` 1). Lý do skip đã kiểm lại bằng `-rs` |
| BLOCKED | 0 |
| Cảnh báo | 1 `StarletteDeprecationWarning` (httpx trong TestClient), có sẵn, không liên quan |

- Loại test: unit và integration với fake (BigQuery giả, OAuth giả, `MemoryStore`), mỗi test có DB tạm cô lập. Không test nào chạm DB thật.
- Lần chạy đầy đủ trước đó (10:25–10:47, chạy song song với harness): 606 passed / 12 failed / 8 skipped.
  - Cả 12 lỗi **liên quan trực tiếp tới thay đổi đợt này**: kỳ vọng cũ về số feature, nhóm feature `customer`, số migration (8), khóa mới của `data_window`.
  - Đã cập nhật kỳ vọng, không nới lỏng hay xóa test; các file liên quan chạy lại 183 passed.
  - Lần chạy cuối có thêm 1 test (627 so với 626): file opt-in mới `test_v129c_real_bq_items_customers.py` (skipped).

**BigQuery thật (opt-in, dịch vụ thật)**
- `test_v129c_real_bq_items_customers.py`: 1 passed sáng 20/10. Dữ liệu nhúng (`UNNEST`), 0 byte, không chuỗi mã khách nào trả về.
- Không chạy lại trong lượt cuối.

**Frontend** (10:52–10:54, sau lần sửa frontend cuối lúc 10:29; không chạy lại)
- vitest 23 file, 149/149 passed.
- `npm run typecheck`: exit 0.
- `npm run build`: exit 0 (JS 677 kB).

**Kiểm tra khác**
- Lint: **chưa cấu hình** (không tính là đạt).
- Đuôi dòng của 75 file so với HEAD: 0 lỗi.
- Không có file PS1 nào thay đổi.
- Quét bí mật trên mọi file đưa vào checkpoint: chỉ có tên định danh trong mã (`client_secret`, `refresh_token`…) và giá trị giả `GOCSPX-FAKE-SECRET-0001` của test (đã có từ HEAD); 0 bí mật thật. File scratchpad: 0 kết quả.

## 10. Tài nguyên đã dùng

| Loại | Lượng |
|---|---|
| BigQuery (chỉ đọc) | ~3,36 GB: 3 truy vấn 0,64 + 1,01 + 1,30 GB và hồ sơ theo ngày 0,40 GB. Dry run trước mỗi truy vấn, có giới hạn byte. Test BigQuery thật: 0 byte (dữ liệu nhúng) |
| Huấn luyện thí nghiệm | 30 lượt fold, 1,17 giờ (10:17–11:27), chỉ trên bản sao. Lần chạy 1 lỗi ở fold đầu, không có kết quả |
| Ổ đĩa (scratchpad) | Bản sao `e8` 620 MB; backup trước migration 80 MB; kết quả fold 102 MB |
| RAM | RAM trống thấp nhất 1,45 GB trong lúc chạy thí nghiệm |

## 11. Production, Git và giới hạn an toàn

| Giới hạn | Trạng thái | Bằng chứng |
|---|---|---|
| Không huấn luyện / backfill / D-0 / D-1 / EOD trên production | Tuân thủ | Danh sách job 20/10 chỉ có job `trigger = SCHEDULE` (3 D-0 SUCCEEDED; D-1 03:00 FAILED `SOURCE_INCOMPLETE`) |
| Không đổi lịch, cấu hình, Price, nguồn BigQuery, `customer_id` | Tuân thủ | Không gọi API ghi nào trên app production; `storage.json` `8D79DBDD…E047` không đổi; mọi thay đổi cấu hình chỉ là giá trị mặc định trong mã nguồn chưa deploy (`feature_customer = false`, `training_start_rule = WINDOW_START`, `customer_id_column = ""`) |
| Không đổi model production / không promote | Tuân thủ | Thí nghiệm chỉ trên bản sao; không publish |
| Không deploy, đóng gói, migration production | Tuân thủ | health / `current.txt` = 1.2.8; DB production vẫn schema 6 |
| Không commit / push | Tuân thủ | HEAD vẫn `0da73b6`; 75 file chưa commit |
| Không xóa dữ liệu, log, checkpoint, scratchpad | Tuân thủ | Checkpoint cũ giữ nguyên; log lần chạy lỗi giữ lại |
| Không đưa PII vào báo cáo / Excel | Tuân thủ | Nguồn không có cột khách; báo cáo chỉ có số đếm và 2 mã SKU |

## 12. Sai lệch quy trình và điểm cần lưu ý

1. **Checkpoint trễ.** Không có checkpoint ZIP trước khi sửa mã của đợt 3. Checkpoint của đợt này tạo **sau** khi sửa và chạy test (mục 14). Trạng thái giữa đợt 2 và đợt 3 không có bản riêng. Gần nhất là `checkpoint-20261019-v129b-worktree.zip` lúc 19/10 23:22.
2. **Tên bản sao trong kế hoạch.** `plan_spike.json` và docstring của `spike_harness.py` ghi bản sao `p17\e`, nhưng harness chạy trên `p18\e8` (`isoenv.setup("e8")`).
   - `e8` là cùng dữ liệu đó, nâng schema 8 (3 cột mới đều NULL; diễn tập 12/12 PASS, giá trị giống hệt).
   - Phải đổi vì mã mới đọc 3 cột khách hàng nên không chạy được trên bản sao schema 7.
   - S0 tái lập O1 của `p17` bit-for-bit, xác nhận dữ liệu không khác.
3. **Mã đổi trong lúc harness chạy.** `app/ml/features.py` được sửa lúc 10:36 (chỉ cấp mảng khách hàng khi có dữ liệu), sau khi harness đã nạp module lúc 10:17.
   - Kết quả thí nghiệm dùng bản trước sửa đổi này.
   - Thay đổi không ảnh hưởng feature khi nhóm khách hàng tắt và không có dữ liệu khách (như thí nghiệm). Test cuối chạy trên mã cuối.
4. **Lỗi harness lần chạy 1** (mục 7.2) do lỗi trong mã mới (`_stack`), đã sửa. Lỗi đó cũng làm hỏng đường huấn luyện mặc định của mã chưa deploy; harness phát hiện ra nó trước lần chạy test đầy đủ đầu tiên.
5. **D-1 production 03:00 ngày 20/10 FAILED `SOURCE_INCOMPLETE`.** Nguồn chưa có ngày 19/10, không liên quan mã đợt này (production chạy 1.2.8). Danh sách job từ 00:00 không có job huấn luyện; lý do chưa kiểm tra. Không chạy lại theo giới hạn.

## 13. Rủi ro, việc còn mở và quyết định cần duyệt

| # | Việc | Ai quyết | Ghi chú |
|---|---|---|---|
| 1 | Quy tắc cho 2 dòng `MULTI_ITEM` ngày 26/08 (NaN / giờ item cùng FC / MAX…) | Chủ hệ thống | Đến khi có quy tắc, cổng `OPEN_HOURS_INVALID` chặn huấn luyện BigQuery khi bật quy tắc cửa sổ mới |
| 2 | Deploy 1.2.9 (migration 0007 + 0008), rồi backfill giờ mở bán sớm | Chủ hệ thống (phê duyệt deploy riêng) | Nguồn chỉ giữ giờ mở bán khoảng 7 tháng và mất 1 ngày mỗi ngày; backfill muộn thì mất thêm |
| 3 | Bật `OPEN_HOURS_COVERAGE` hay giữ `WINDOW_START` | Chủ hệ thống | Đánh đổi: không giảm độ chính xác đo được so với mất Tết / đầu năm và 550 chuỗi |
| 4 | Hạ trọng số spike: dừng ở kết quả nghiên cứu hay đánh giá thêm (S6, thước đo chi phí) | Chủ hệ thống / nghiệp vụ | Không promote; cần tiêu chí nghiệp vụ cho dự báo thiếu |
| 5 | Giải thích 2.592 dòng "0 giờ nhưng có đơn" | Chủ dữ liệu | Excel ở mục 6 |
| 6 | Cột khách hàng trong nguồn | Chủ dữ liệu | Khi có cột: chọn ở trang Ánh xạ, nạp lại, đánh giá ON/OFF trên bản sao trước |
| 7 | Xác nhận giữ cuộn 7 tháng và việc nguồn sửa lịch sử | Chủ dữ liệu | Mục 3 |
| 8 | D-1 20/10 thất bại `SOURCE_INCOMPLETE` | Vận hành | Chạy lại khi nguồn đủ; không thuộc phạm vi đợt này |

**Hành động nhỏ nhất tiếp theo:** chủ hệ thống chọn quy tắc cho 2 dòng `MULTI_ITEM` và quyết định có deploy 1.2.9 hay không, vì thời hạn backfill giờ mở bán ngắn dần mỗi ngày.

## 14. Checkpoint

ZIP: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129c-worktree.zip`. Tạo **sau** khi test và báo cáo hoàn tất. Checkpoint cũ giữ nguyên.

| Thư mục trong ZIP | Nội dung |
|---|---|
| `source/` | Bản working tree của 75 file đã sửa / mới so với HEAD `0da73b6`, và `tracked-changes-vs-HEAD.patch` (`git diff HEAD --binary`) |
| `reports/` | Báo cáo này |
| `scratchpad-p18/` | Kế hoạch thí nghiệm, script (harness, phân tích, BigQuery chỉ đọc, Excel, migration, môi trường cô lập), kết quả JSON, log harness, log test, 30 file kết quả fold `.npz` |
| `MANIFEST.json` | HEAD, `git status`, kích thước và SHA-256 từng file, danh sách loại trừ |

**Không đóng gói:**
- bản sao DB `e8` (dữ liệu người dùng, 620 MB) và backup của nó;
- Excel ở `reports/` (đã có SHA-256 ở mục 6);
- credentials, token hay bí mật nào.

SHA-256 của ZIP không thể nằm trong chính file ở trong ZIP. Hash ghi ở file `.sha256` cạnh ZIP và ở `docs/CHECKPOINT.md`.

**Kết quả** (thêm sau khi tạo ZIP; bản báo cáo và `docs/CHECKPOINT.md` bên trong ZIP không có phần này):

| | Giá trị |
|---|---|
| Đường dẫn | `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129c-worktree.zip` |
| Tạo lúc | 20/10/2026 12:30:37 (+07:00) |
| Kích thước | 106.047.154 byte (~101 MB; 110,7 MB trước nén) |
| SHA-256 | `EB7800C2E452BB8220E96D4A07599ADEFC43A11EEC3FC6AC81DF0B699AE73416`, cũng trong `checkpoint-20261020-v129c-worktree.zip.sha256` |
| Số mục | 142: `source/` 76 (75 file + patch), `reports/` 1, `scratchpad-p18/` 64 (gồm 30 `.npz`), `MANIFEST.json` 1 |

**Đã kiểm tra:**
- ZIP mở được; CRC của mọi mục đúng (`testzip`).
- Danh sách mục khớp manifest; không có mục trùng.
- SHA-256 của từng mục đọc lại từ ZIP khớp manifest.
- Hash của ZIP tính lại bằng PowerShell `Get-FileHash` khớp.
- Đọc lại danh sách bằng .NET `ZipFile`: không có tên file dạng credentials / token / DB / `storage.json` / `.xlsx`.
- Script tạo: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\make_checkpoint.py`.
- Kết quả kiểm tra: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p18\checkpoint_verify.json`.
