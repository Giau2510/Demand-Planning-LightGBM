# Báo cáo batch 1.1.5: tích hợp BigQuery `demand_planing_lightgbm` và kiến trúc feature mở rộng

Thời điểm: 15/10/2026, khoảng 10:45 – 12:25 (giờ Việt Nam). Máy: máy Windows đang chạy ứng dụng (không thử trên máy khác).

**Kết quả:**
- **Đã triển khai và đã cài 1.1.5 vào ứng dụng thật lúc 12:18.** Không migration (schema 3). Không đổi `storage.json`, storage ID, đường dẫn D:, nguồn dữ liệu (vẫn DEMO), dữ liệu kinh doanh hay model đang dùng.
- **BigQuery CHƯA được kiểm chứng với bảng thật.** Máy này không có thông tin xác thực Google:
  - không có file ADC, không có Google Cloud CLI, không có `GOOGLE_APPLICATION_CREDENTIALS`;
  - lần kiểm tra của chính người dùng lúc 23:16 ngày 14/10 cũng báo `BQ_AUTH_MISSING`.

  Vì vậy:
  - schema thật chưa được đọc;
  - chưa có truy vấn nào chạy trên bảng nguồn;
  - **không có số liệu thật nào của bảng nguồn trong báo cáo này.**
- Phần tích hợp được kiểm thử bằng fake client. Ngoài ra SQL do ứng dụng sinh ra đã **chạy thật** (chuyển sang DuckDB) trên dữ liệu tổng hợp có các trường hợp biên, và mọi con số khớp với tính toán độc lập.

**Mức độ kiểm chứng:**

| Mức | Nội dung |
|---|---|
| Đã triển khai | ánh xạ cho bảng mới, kiểm tra dữ liệu toàn kỳ, đối chiếu, chính sách dòng trùng, phân loại lỗi và retry có giới hạn, feature registry, chặn feature không có dữ liệu, lineage, giao diện |
| Đã kiểm thử bằng mock/fixture | 32 test backend mới, 3 test giao diện mới, E2E trên bản sao DB, kiểm thử gói cô lập (cài mới, nâng cấp, quay về 1.1.4) |
| Đã chạy SQL thật trên engine khác | DuckDB (qua sqlglot) trên dữ liệu tổng hợp: 27/27 + 18/18 kiểm tra |
| Đã kiểm chứng với BigQuery thật | **Không có** |
| Chưa kiểm chứng | xác thực, quyền, location, kiểu cột thật, số liệu thật, chi phí và thời gian truy vấn thật, phương ngữ BigQuery trên bảng thật |

---

## 1. Tóm tắt thay đổi và phiên bản

| | |
|---|---|
| Trước | 1.1.4 (pid 27956), nguồn DEMO, scope `DEMO-20261014080556-5342EB`, schema 3, không có job đang chạy |
| Sau | **1.1.5** (`backend/app/__init__.py`, `frontend/package.json`, `VERSION` trong gói), pid 17220 |

**Thay đổi chính:**
1. Ánh xạ cho bảng `demand_planing_lightgbm`:
   - nút **Gợi ý** chỉ điền cột có thật trong schema, không tự lưu;
   - **trường tham chiếu** (11 trường) tách khỏi trường khóa/target;
   - `order_date` phải là DATE/DATETIME: TIMESTAMP không bị tự quy đổi múi giờ.
2. **Kiểm tra dữ liệu toàn kỳ** từ `history_start_date` (mặc định 01/01/2026) đến hôm nay:
   - đối chiếu số dòng và tổng target, dòng bị loại theo lý do, dòng trùng;
   - ngày thiếu, FC thiếu ngày;
   - phân bố `order_status`/`sku_status`, độ đầy đủ trường tham chiếu, Σ outbound / Σ demand.

   Kết quả gắn với *mã ánh xạ*. Chế độ sản xuất, đồng bộ D-1 và huấn luyện BIGQUERY chỉ chạy khi kết quả cho ánh xạ hiện tại là **Đạt**.
3. **Đồng bộ D-1:**
   - đối chiếu trước và sau khi ghi; không khớp thì không ghi gì;
   - đổi ánh xạ thì tải lại toàn kỳ, không trộn dữ liệu của ánh xạ cũ;
   - không đọc trước `history_start_date`;
   - chính sách dòng trùng: `BLOCK` (mặc định), `KEEP`, `DROP_EXACT`.
4. **Phân loại lỗi:**
   - `BQ_AUTH_MISSING` / `BQ_AUTH_EXPIRED`, `BQ_PERMISSION_DENIED`;
   - `BQ_NOT_FOUND` / `BQ_LOCATION_MISMATCH`, `BQ_TIMEOUT` (job bị hủy, không thử lại);
   - `BQ_QUOTA` / `BQ_UNAVAILABLE` (thử lại tối đa 2 lần, giãn 2–4 giây);
   - `BQ_SCHEMA_CHANGED`, `BQ_QUERY_TOO_EXPENSIVE` (dry-run trước mọi truy vấn).
5. **Feature registry** (`ml/feature_registry.py`) và trang **Quản lý feature**:
   - 33 feature hiện có và 15 biến dự kiến, với trạng thái tính từ dữ liệu thật;
   - nhóm giá/chiết khấu/khuyến mãi **chỉ vào mô hình khi nguồn có dữ liệu** (độ phủ ≥ 50%); không điền 0, không điền giả;
   - `disc_last` có công tắc riêng, nhưng cấu hình cũ vẫn cho đúng 33 feature như trước.
6. **Truy vết mỗi lần huấn luyện** (trong `training_runs.feature_config_json`, không cần migration):
   - `feature_set_version`, công tắc người dùng, công tắc đã áp dụng kèm lý do;
   - `lineage`: nguồn, bảng/lô, mã ánh xạ, khoảng ngày, số dòng, thời điểm lấy dữ liệu, kết quả kiểm tra, target mapping, grain.

   Trang *Thuật toán → Huấn luyện* hiển thị các thông tin này.

## 2. Các file chính đã sửa

| File | Nội dung |
|---|---|
| `backend/app/bq/connector.py` | Gợi ý ánh xạ, kiểm tra ánh xạ (tham chiếu, TIMESTAMP, một cột cho nhiều khóa), `validate_source`, mã ánh xạ, lỗi + retry + hủy job khi timeout, SQL tải ngày có lý do loại / dòng trùng / chặn dưới theo `history_start_date`, kích hoạt cần kiểm tra toàn kỳ |
| `backend/app/sync.py` | D-1 cần kiểm tra toàn kỳ; đối chiếu số ghi = số đọc; tải lại toàn kỳ khi đổi ánh xạ |
| `backend/app/settings_service.py` | `reference_mapping`, `history_start_date`, `exact_duplicate_policy`, `max_retries`, `max_null_share` (khóa cấp trên cùng, bản 1.1.4 bỏ qua được); `feature_discount`, `feature_min_coverage` |
| `backend/app/ml/feature_registry.py` (mới) | Registry, trạng thái, `resolve` (chặn feature thiếu dữ liệu), phiên bản feature set |
| `backend/app/ml/features.py` | `disc_last` theo công tắc riêng (mặc định đi theo giá như cũ) |
| `backend/app/ml/pipeline.py` | Áp dụng registry, lineage, chặn huấn luyện BIGQUERY chưa kiểm tra, metadata file mô hình |
| `backend/app/ml/training_explain.py` | Trả feature set + lineage |
| `backend/app/api/*.py`, `messages.py` | `POST /api/bigquery/validate`, `POST /api/bigquery/suggest-mapping`, `GET /api/features/registry`, ánh xạ tham chiếu, mã lỗi mới |
| `frontend/src/pages/BigQuery.tsx`, `Mapping.tsx`, `Features.tsx` (mới), `TrainingExplain.tsx`, `App.tsx`, `i18n.tsx` | Giao diện Việt/Anh |
| Test | `backend/tests/test_v115_bigquery_features.py` (32), `frontend/src/v115.test.tsx` (3); `test_bigquery.py` cập nhật theo quy tắc mới |
| Tài liệu | `docs/BIGQUERY.md` (viết lại), `docs/MO-HINH-VA-CHI-SO.md`, `docs/HUONG-DAN-SU-DUNG.md`, `docs/CHECKPOINT.md` |

## 3. Xác nhận SQL và bảng nguồn không bị chỉnh sửa

- Ứng dụng không chứa và không sửa SQL tạo bảng của người dùng. SQL đó không có trong repo; ứng dụng chỉ đọc *bảng kết quả*.
- Mọi truy vấn của ứng dụng là `SELECT` đọc độc lập trên bảng, chỉ lấy các cột đã ánh xạ. Test kiểm tra không có `SELECT *` trên bảng nguồn.
- Không có lệnh tạo/sửa/xóa bảng, view, materialized view hay scheduled query. Không có lệnh ghi nào tới BigQuery.
- Không truy vấn nào chạm tới BigQuery trong batch này, vì không có credentials.
- `demand_quantity` không bị thay bằng `outbound_quantity`. `created_date`, `open_date`, `total_open_hours` giữ nguyên ý nghĩa.

## 4. Schema nguồn thực tế đã đọc được

**Chưa đọc được** (`BQ_AUTH_MISSING`).

**Danh sách cột** (theo người dùng): `fc_code`, `created_date`, `product_id`, `sku_code`, `item_code`, `demand_quantity`, `outbound_quantity`, `order_status`, `sales_price`, `price_after_discount`, `seller_code`, `sku_system_status`, `open_date`, `total_open_hours`, `total_open_days`, `so_code`, `refresh_time`.

**Kiểu dùng trong kiểm thử là giả định:**
- `created_date` DATE;
- `refresh_time` TIMESTAMP;
- số lượng/giá FLOAT64;
- mã STRING.

Khi đọc được schema thật, ứng dụng tự kiểm tra kiểu và báo lỗi nếu không tương thích; không có gì bị đoán.

## 5. Ánh xạ trường và quy tắc xử lý dữ liệu

| Trường nội bộ | Cột | Vai trò |
|---|---|---|
| `order_qty` | `demand_quantity` | **Target** |
| `order_date` | `created_date` | Ngày nhu cầu |
| `sku_id` / `fc_id` | `sku_code` / `fc_code` | Khóa dự báo |
| `order_id` | `so_code` | Đếm đơn, kiểm tra trùng |
| `source_updated_at` | `refresh_time` | Metadata |
| Tham chiếu | `product_id`, `item_code`, `outbound_quantity`, `order_status`, `sales_price`, `price_after_discount`, `seller_code`, `sku_system_status`, `open_date`, `total_open_hours`, `total_open_days` | Chỉ kiểm tra/đối chiếu/feature tương lai |

**Không ánh xạ tự động:** `unit_price`, `discount_amount`, `promotion_flag`, `voucher_*`. Cần quyết định nghiệp vụ.

**Quy tắc ở lớp ứng dụng** (đầy đủ trong `docs/BIGQUERY.md` mục 4):
- **Khoảng đọc:** `DATE(created_date)` từ 01/01/2026 đến hôm nay.
- **Dòng bị loại**, mỗi lý do có số dòng và tổng số lượng riêng:
  - `NULL_SKU`, `NULL_FC`;
  - `NULL_TARGET`: không đổi thành 0;
  - `NEGATIVE_TARGET`;
  - dòng thiếu ngày được đếm riêng.
- **Tổng hợp:** `qty = Σ demand_quantity` theo `created_date × sku_code × fc_code`. Không cộng cột số khác, không cộng giá.
- **Không lọc theo `order_status`.** SQL nguồn đã quyết định dòng nào có mặt.
- **Ngày không có dòng nào** là thiếu dữ liệu (NaN), không phải 0.
- **Dòng trùng hoàn toàn** (giống nhau ở mọi cột đã ánh xạ): mặc định chặn và báo cáo.

## 6. Kết quả kiểm tra ADC / quyền đọc / kết nối BigQuery

| Kiểm tra | Kết quả |
|---|---|
| File ADC `%APPDATA%\gcloud\application_default_credentials.json` | Không có |
| Google Cloud CLI (`gcloud`) | Chưa cài |
| `GOOGLE_APPLICATION_CREDENTIALS` | Không đặt |
| Nút *Kiểm tra xác thực* (người dùng, 14/10 23:16; E2E trên bản sao, 15/10 11:56) | `BQ_AUTH_MISSING`, kèm hướng dẫn `gcloud auth application-default login` |
| Kết nối, quyền đọc, location thật | **Chưa kiểm tra được** |

Ứng dụng xử lý đúng khi thiếu credentials:
- lỗi rõ ràng;
- kết quả kiểm tra được lưu là *Không đạt* kèm lý do;
- chế độ sản xuất vẫn khóa;
- **không** tự chuyển nguồn, **không** huấn luyện.

## 7. Khoảng ngày, số dòng, thống kê kiểm tra (bảng thật)

**Không có**, vì chưa truy vấn được bảng thật.

Số liệu có được là của dữ liệu tổng hợp trong kiểm thử SQL. Kiểm thử gồm 1.471 dòng trong khoảng 01–31/01/2026 với:
- 5 dòng thiếu SKU, 3 dòng thiếu FC, 4 dòng thiếu target, 6 dòng target âm;
- 3 dòng trùng hoàn toàn;
- 2 dòng thiếu ngày, 2 dòng ngoài khoảng;
- 1 ngày không có dòng nào, 1 FC thiếu một ngày.

Mọi con số do SQL trả về khớp tính toán Python độc lập:

| Kiểm tra | Kết quả |
|---|---|
| Dòng hợp lệ | 1.453 |
| Chuỗi-ngày | 780 |
| Tổng target hợp lệ | 10.039 |
| Ghi vào ứng dụng | đúng 780 dòng / 10.039 |

## 8. Kết quả kiểm thử

| Nhóm | Kết quả |
|---|---|
| Backend `pytest` toàn bộ (`logs\development\tests_20261015_114959.log`) | **183 PASS**, 0 FAIL, 0 SKIP |
| — trong đó mới `test_v115_bigquery_features.py` | 32 PASS (chi tiết bên dưới) |
| Frontend `vitest` | **42 PASS** (3 mới), 0 FAIL, 0 SKIP |
| TypeScript + `vite build` | đạt |
| SQL chạy trên DuckDB (scratchpad `sqlh`) | **27/27 PASS** (logic SQL) + **18/18 PASS** (xử lý của ứng dụng trên kết quả SQL, gồm đồng bộ D-1 ghi đúng tổng) |
| E2E trình duyệt trên **bản sao DB** (gồm huấn luyện trên bản sao) | **113 PASS**, 0 FAIL |
| Gói cô lập — cài mới | **24 + 37 PASS** |
| Gói cô lập — nâng cấp trên bản sao DB thật | **20 PASS** |
| Gói cô lập — **quay về 1.1.4** trên cùng dữ liệu, không khôi phục DB | **3 + 7 PASS** |
| E2E **chỉ đọc trên app thật** 1.1.5 | **82 PASS**, 0 FAIL; trình duyệt không gửi request ghi nào |
| Kiểm thử với BigQuery thật | **SKIP** (không có credentials) |
| Kiểm thử trên máy Windows khác | **SKIP** (không thực hiện) |

**Các nhóm trong 32 test backend mới:**
- *BigQuery:*
  - lỗi xác thực thiếu/hết hạn, thiếu quyền, sai location/bảng, timeout, quota, dịch vụ lỗi, vượt chi phí;
  - retry có giới hạn; schema đổi kiểu;
  - preview giới hạn ≤ 500 dòng, không `SELECT *`;
  - truy vấn lỗi không đổi nguồn/dữ liệu/huấn luyện.
- *Mapping:*
  - gợi ý không tự lưu; cột thiếu được báo, không đoán;
  - TIMESTAMP không tự đổi múi giờ; một cột cho hai khóa bị chặn;
  - target NULL/âm, dòng trùng, ngày thiếu, đối chiếu.
- *Pipeline:*
  - D-1 và huấn luyện cần kiểm tra toàn kỳ; đối chiếu lỗi thì không ghi;
  - BIGQUERY không trộn với DEMO;
  - feature không có dữ liệu bị bỏ, không điền 0;
  - mô hình bỏ nhóm khuyến mãi/chiết khấu (30 feature) vẫn được giải thích TreeSHAP **VERIFIED**;
  - DEMO giữ đúng 33 feature;
  - cấu hình 1.1.4 cho đúng danh sách feature cũ.
- *Nâng cấp:* thiết lập mới 1.1.4 vẫn đọc được.

**Kiểm thử chống rò rỉ dữ liệu tương lai** dùng test có sẵn `test_backtest_forecast_unchanged_when_future_changes`, vẫn PASS.

**Lỗi tìm thấy và đã sửa trong batch:**
- `validate_mapping` lỗi `KeyError` khi nhận ánh xạ thiếu trường;
- "dòng trùng hoàn toàn" lúc kiểm tra và lúc tải từng tính trên hai tập cột khác nhau (nay cùng tính trên mọi cột đã ánh xạ);
- `NULL` không có kiểu trong SQL tải ngày (nay ép kiểu rõ).

## 9. Build và package

| | |
|---|---|
| Gói | `dist\DemandForecast-1.1.5-win64-portable.zip`, 101.420.553 byte |
| SHA256 (tính 2 lần, trùng nhau) | `C122B0757654D8EEA19315BC4F30E2C9066016D70F3F5EBB378E35113076AA56` |
| Đã giải nén | `release\DemandForecast-1.1.5` (8.234 file); `backend/app`, `web`, `docs`, `install.ps1` trùng mã nguồn |
| Credentials trong gói | Không có (quét file key / `private_key` / `refresh_token`: chỉ thấy quy tắc che log và tài liệu) |
| Gói 1.1.4 | không đổi, SHA256 vẫn `D4E66387EACB867DAFFBD74C06B36F0F9F6494F91959FD81B0038E87DB4538F7` |

## 10. Backup

| Backup | SHA256 | Xác minh |
|---|---|---|
| `backups\backup-20261015-121828-manual.zip` (độc lập, trước khi cài) | `D0B99A6B3C2614FEF630802DF113AF7A63B5D55295E4E7C8321035D312DDAF22` | Đã giải nén và đọc. Gồm `db\app.db` và model đang dùng `MV-20261014-150621-DF32`. Số liệu khớp DB thật. Integrity ok. Có thiết lập BigQuery của người dùng. |
| `backups\backup-20261015-121850-cli.zip` | — | Do trình cài tạo tự động |

## 11. DB, storage ID, storage config và nguồn dữ liệu trước/sau

| | Trước | Sau cài + E2E chỉ đọc |
|---|---|---|
| DB | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` qua `storage.json` | như cũ |
| SHA256 `storage.json` | `8D79DBDD…00FDE047` | như cũ |
| storage ID | `6cff0821634b0447` | như cũ |
| Nguồn / scope | DEMO / `DEMO-20261014080556-5342EB` | như cũ (không tự đổi) |
| Forecast run / giá trị / demand / order lines | 3 / 4.368 / 38.533 / 93.157 | như cũ |
| Model đang dùng | `MV-20261014-150621-DF32`, SHA256 `EC507FD6…49BD6C26` | như cũ (không huấn luyện lại) |
| Thiết lập BigQuery của người dùng | `gold_buymed_vn2.demand_planing_lightgbm`, `asia-southeast1`, partition `created_date`, chưa ánh xạ, sản xuất tắt | như cũ; nhận thêm mặc định mới (đọc từ 01/01/2026, dòng trùng: CHẶN) |
| Thay đổi trong DB | — | 1 dòng `audit_log` `BACKUP_CREATED` của lần backup độc lập |

**Ràng buộc đã tuân thủ:**
- không xóa hoặc reset dữ liệu;
- không đổi storage;
- không chạy migration;
- không dùng DB dự phòng làm DB runtime;
- không commit Git;
- mọi kiểm thử có ghi đều chạy trên bản sao DB hoặc thư mục cô lập.

## 12. Giới hạn chưa xác minh

- **Toàn bộ phần chạm BigQuery thật:**
  - xác thực, quyền `bigquery.dataViewer`/`jobUser`, location thật;
  - kiểu cột thật; grain thật (một dòng = đơn × SKU × FC?);
  - số liệu, chi phí và thời gian truy vấn thật.
- **SQL:** đã chạy đúng trên DuckDB, nhưng **chưa chạy trên BigQuery**. Khác biệt phương ngữ, ví dụ `TO_JSON_STRING(row)` hay `APPROX_QUANTILES`, chỉ lộ ra khi chạy thật.
- **`created_date`:** chưa biết là ngày theo múi giờ nào trong SQL nguồn. Ứng dụng giữ nguyên giá trị, không quy đổi.
- **Ảnh chụp D0 từ BigQuery:** `created_date` không có giờ nên chỉ là "tổng đến lúc đọc" theo dữ liệu đang có trong bảng; độ mới xem ở `refresh_time`.
- **Rollback sang 1.1.4:** đã kiểm thử cho trường hợp DEMO đủ 33 feature. Mô hình huấn luyện bằng 1.1.5 mà *có giá nhưng không có chiết khấu* sẽ không được 1.1.4 giải thích đúng, vì 1.1.4 cho `disc_last` đi theo `feature_price`. Giá trị dự báo đã publish không bị ảnh hưởng.
- **Kiểm thử cô lập:** đường dẫn thư mục rất sâu nên vượt giới hạn 260 ký tự với vài file cache/test của thư viện. Không ảnh hưởng; đường dẫn cài thật ngắn hơn nhiều.
- **Ngưỡng WAPE/Bias:** vẫn là giá trị ví dụ, chưa được nghiệp vụ duyệt (không đổi trong batch này).

## 13. Danh sách feature

**Đang dùng — mô hình hiện tại, DEMO, 33 feature, `FS-fe-1-7e03c1d28cbe`:**
- `sku_code`, `fc_code`, `series_age`;
- `lag_1`…`lag_7`, `lag_14`, `lag_21`, `lag_28`;
- `roll_mean_7/14/28/56`, `roll_std_7/28`, `zero_share_28`, `days_since_last_sale`, `roll_max_28`;
- `dow`, `dom`, `month`, `weekofyear`, `is_weekend`, `days_to_month_end`;
- `price_last`, `price_rel_28`, `disc_last`, `promo_last`, `promo_mean_7`.

Phiên bản này được tính lại từ danh sách đã lưu, vì mô hình được huấn luyện trước 1.1.5.

**Khi chuyển sang BIGQUERY với ánh xạ gợi ý: 28 feature.** 5 feature giá/chiết khấu/khuyến mãi có trạng thái **Thiếu dữ liệu** và **không** vào mô hình cho đến khi có cột và quy tắc thật. Test xác nhận điều này với dữ liệu BIGQUERY mô phỏng.

**Dự kiến (15, chỉ là metadata, không vào mô hình):**

| Nhóm | Biến |
|---|---|
| Giá & khuyến mãi | giá lúc đặt (`sales_price`), giá sau chiết khấu (`price_after_discount`), tỷ lệ giảm giá dòng đơn, deal, promotion trên dòng đơn, loại deal/promotion, voucher |
| SKU & khả dụng | trạng thái SKU (`sku_system_status`), seller (`seller_code`), giờ mở bán (`total_open_hours`), ngày mở bán (`total_open_days`), số ngày từ `open_date` |
| Tương lai | ngày lễ/mùa vụ, chiến dịch, thuộc tính đơn |

Với BIGQUERY: biến có cột nguồn đã ánh xạ và có dữ liệu sẽ hiện **"Có dữ liệu nhưng chưa kích hoạt"**; biến chưa có cột hiện **"Đang lên kế hoạch"**.

## 14. Cài đặt trên máy khác và rollback

### Cài trên máy Windows khác

1. Chép `DemandForecast-1.1.5-win64-portable.zip` (SHA256 ở mục 9), giải nén, chạy `Install.bat`. Gói có sẵn Python; không cần cài Python hay Node.
2. Xác thực Google (mỗi máy một lần, credentials không nằm trong gói):
   - cài Google Cloud CLI;
   - chạy `gcloud auth application-default login` bằng tài khoản có `roles/bigquery.dataViewer` trên dataset `gold_buymed_vn2` và `roles/bigquery.jobUser` trên project chạy truy vấn.
3. Trong ứng dụng, chạy lần lượt:
   1. Kết nối BigQuery → *Kiểm tra xác thực* → *Kiểm tra kết nối* → *Đọc schema*;
   2. Ánh xạ trường → *Gợi ý…* → xem lại → *Kiểm tra & lưu*;
   3. *Xem trước* → *Kiểm tra dữ liệu (30 ngày)* → **Kiểm tra dữ liệu toàn kỳ**;
   4. *Kích hoạt chế độ sản xuất*;
   5. chọn nguồn BIGQUERY;
   6. đồng bộ D-1;
   7. huấn luyện.

### Rollback về 1.1.4 trên máy này

Đã kiểm thử trên bản sao; chưa chạy trên máy thật.

1. `%LOCALAPPDATA%\Programs\DemandForecast\1.1.5\Stop.bat`.
2. `%LOCALAPPDATA%\Programs\DemandForecast\1.1.4\Start.bat`. Muốn shortcut cũng trỏ 1.1.4 thì chạy `release\DemandForecast-1.1.4\DemandForecast-1.1.4\scripts\install.ps1`.
3. **Không cần khôi phục DB:** cùng schema 3; thiết lập mới được 1.1.4 bỏ qua. Không mất dữ liệu.

## 15. Việc cần người dùng quyết định

1. **Cấp quyền truy cập trên máy này** (bước 2, mục 14), rồi chạy các kiểm tra theo thứ tự. Đây là điều kiện để kiểm chứng phần BigQuery.
2. Sau khi đọc schema, **xác nhận kiểu cột**:
   - `created_date` là DATE? Nếu là TIMESTAMP thì múi giờ là gì?
   - `demand_quantity` là số?
3. **Khóa SKU:** `sku_code` có đúng là SKU dùng để dự báo (so với `product_id`/`item_code`) không?
4. **Target âm** (ví dụ trả hàng): hiện bị loại và báo cáo, và chặn nếu > 5%. Giữ quy tắc này hay đổi?
5. **Dòng trùng hoàn toàn:** nếu kiểm tra toàn kỳ phát hiện, chọn CHẶN / GIỮ / LOẠI.
6. **Giá/khuyến mãi:**
   - `sales_price` có phải đơn giá lúc đặt hàng không (để ánh xạ `unit_price`)?
   - quy tắc cho `price_after_discount`;
   - nguồn cho deal/promotion/voucher.
7. **Ngày bắt đầu đọc** (01/01/2026) và **giới hạn chi phí** mỗi truy vấn (20 GB).
8. **Bật nguồn BIGQUERY** cho dự báo: thao tác của người dùng sau khi mọi kiểm tra đạt. Ứng dụng không tự chuyển.
9. **Duyệt ngưỡng WAPE/Bias** cho quality gate (vẫn là giá trị ví dụ).
