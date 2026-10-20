# Nguồn BigQuery (từ 1.1.5; xác thực Google, SQL editor và job độc lập từ 1.1.6)

> **Trạng thái kiểm chứng (15/10/2026, bản 1.1.6):**
> - Đã triển khai; kiểm thử bằng fake client / OAuth giả lập. Logic SQL (lịch sử và D0) đã chạy trên DuckDB với dữ liệu tổng hợp.
> - **Chưa kiểm chứng với BigQuery thật và chưa đăng nhập Google thật.**
>   - Tài khoản Windows chạy ứng dụng (`Giau Vo`) không có ADC.
>   - ADC nằm trong hồ sơ `Administrator`, tài khoản `Giau Vo` không đọc được.
>   - Chưa có OAuth client do quản trị Google Cloud cấp.
> - Production, đồng bộ và huấn luyện nguồn BIGQUERY vẫn bị chặn cho đến khi kiểm tra dữ liệu thật đạt.

## 1. Bảng nguồn và nguyên tắc

| Mục | Giá trị |
|---|---|
| Project | `lakehouse-prod-394907` |
| Dataset / bảng | `gold_buymed_vn2.demand_planing_lightgbm` |
| Location dự kiến | `asia-southeast1`. Ứng dụng so với location thật của dataset và báo `BQ_LOCATION_MISMATCH` nếu khác. |
| Cột partition (đã cấu hình) | `created_date` |

**SQL tạo bảng và bản thân bảng do người dùng quản lý và đã xác nhận đúng. Ứng dụng:**
- chỉ **đọc**: không tạo, sửa hay xóa bảng, view, materialized view hay scheduled query, và không ghi gì vào BigQuery;
- không sửa và không viết lại SQL nguồn: mọi truy vấn của ứng dụng là truy vấn đọc độc lập, đặt lên trên bảng;
- không dùng `SELECT *` trên bảng nguồn mà chỉ đọc các cột đã ánh xạ;
- mỗi truy vấn chạy *dry-run* trước để ước tính bytes. Vượt `maximum_bytes_billed` (mặc định 20 GB) thì không chạy (`BQ_QUERY_TOO_EXPENSIVE`);
- khi lỗi, không bao giờ tự chuyển sang DEMO hay MANUAL_IMPORT. Kiểm tra kết nối hay kiểm tra dữ liệu không bao giờ kích hoạt huấn luyện và không đổi dự báo đang dùng.

## 2. Xác thực Google (theo từng tài khoản Windows)

**Nguyên nhân lỗi "Máy này chưa có thông tin xác thực Google"** (đã xác minh 15/10/2026):
- Backend chạy dưới tài khoản Windows `LOG-PC\Giau Vo`.
- Thư viện Google chỉ tìm ADC tại `%APPDATA%\gcloud\application_default_credentials.json` **của chính tài khoản đó**, tức `C:\Users\Giau Vo\AppData\Roaming\...`. File này không có.
- ADC đã tạo trong hồ sơ `Administrator` không bao giờ được backend dùng: tài khoản `Giau Vo` không có quyền đọc hồ sơ đó.
- Biến môi trường của cửa sổ PowerShell khác không ảnh hưởng đến backend.

Trang **Kết nối BigQuery** hiển thị thông tin chẩn đoán (chỉ đường dẫn, không đọc nội dung file):
- tài khoản Windows đang chạy backend;
- đường dẫn ADC được tìm, có hay không;
- `GOOGLE_APPLICATION_CREDENTIALS`;
- gcloud trên PATH;
- phương thức xác thực đang dùng.

**Có 3 cách xác thực**, đều không lưu credential trong gói cài đặt:

1. **Đăng nhập Google trong ứng dụng (OAuth, từ 1.1.6)** — không cần Google Cloud CLI.
   - Quản trị Google Cloud tạo **OAuth client loại "Desktop app"**:
     - màn hình đồng ý OAuth loại *Internal* cho tổ chức;
     - bật BigQuery API;
     - nếu Workspace giới hạn ứng dụng bên thứ ba thì thêm client vào danh sách tin cậy.

     Sau đó gửi Client ID và Client secret.
   - Nhập client ở thẻ *Xác thực Google* — cách nhanh nhất (1.1.7): chọn **file JSON OAuth client** tải từ Google Cloud
     Console. Ứng dụng chỉ nhận client loại *Desktop app* (`installed`); file loại *Web application* bị từ chối với lý do
     rõ ràng (`OAUTH_CLIENT_WRONG_TYPE`), vì client Web không dùng được đăng nhập loopback (Google báo
     `redirect_uri_mismatch`). Nội dung file chỉ được đọc trong bộ nhớ, không lưu thành file, không ghi log.
     Hoặc nhập thủ công Client ID/secret:
     - secret được lưu vào **Windows Credential Manager** của tài khoản Windows đang chạy ứng dụng (DPAPI);
     - không lưu trong DB, log, giao diện hay báo cáo.
   - Bấm **Đăng nhập Google**:
     - trình duyệt mặc định mở trang Google;
     - Google trả về một cổng loopback tạm thời trên `127.0.0.1` (dùng `state` và PKCE S256, hết hạn sau 5 phút);
     - ứng dụng chỉ lưu **refresh token** vào Credential Manager và hiển thị email đã đăng nhập.
   - Trạng thái hiển thị: chưa đăng nhập / đang chờ / đã đăng nhập / người dùng hủy / bị chặn bởi chính sách / lỗi / hết thời gian / hết hạn hoặc bị thu hồi / client đã đổi.
   - *Đã đăng nhập* chỉ được hiển thị sau khi Google thực sự cấp token; thời điểm Google xác nhận gần nhất được hiển
     cạnh email (*Google xác nhận phiên đăng nhập lúc …*). Cổng `auth` của *Kiểm tra quyền BigQuery* xin access token
     mới thật sự từ Google mỗi lần chạy (1.1.7) — trước đây chỉ tạo client nên token bị thu hồi bị báo nhầm ở cổng dataset.
   - Đổi OAuth client: phiên đăng nhập của client cũ được thu hồi và gỡ (`OAUTH_CLIENT_CHANGED`) → đăng nhập lại.
   - Mỗi mã lỗi có hướng dẫn hành động trong ứng dụng: thiếu/sai client (`OAUTH_CLIENT_INVALID`), chưa cấp quyền
     BigQuery trên trang đồng ý (`OAUTH_SCOPE_NOT_GRANTED`, khác với thiếu IAM), phiên hết hạn/thu hồi (`BQ_AUTH_EXPIRED`),
     mạng (`OAUTH_NETWORK`, `BQ_UNAVAILABLE`), thiếu IAM (`BQ_PERMISSION_DENIED`), API chưa bật (`BQ_API_DISABLED`).
   - **Đăng xuất** thu hồi token tại Google và xóa khỏi Credential Manager.
2. **ADC của chính tài khoản Windows chạy ứng dụng** (không bắt buộc; chỉ dùng khi không dùng đăng nhập trong ứng dụng).
   - Mở PowerShell **bằng tài khoản đó** (không "Run as Administrator" bằng tài khoản khác).
   - Chạy `gcloud auth application-default login`.
   - Luồng này vẫn được giữ nguyên.
3. **File service account.** Chỉ lưu *đường dẫn*; file phải nằm ngoài thư mục ứng dụng.

**Quyền IAM cần có:**
- `roles/bigquery.dataViewer` trên dataset `gold_buymed_vn2`, hoặc trên các bảng dùng tới:
  - `demand_planing_lightgbm`;
  - `fact_order`, `fact_order_item`, `adhoc_pm_master_sku` cho SQL D0.
- `roles/bigquery.jobUser` trên project chạy truy vấn.

**Kiểm tra quyền BigQuery** (thẻ *Xác thực Google*, hoặc dòng lệnh `python -m app.cli bq-check` của cùng tài khoản
Windows — in JSON không có secret, mã thoát 0 = đạt, 1 = có cổng lỗi): các cổng chạy theo thứ tự và dừng ở cổng đầu
tiên lỗi. Thẻ *Nội dung gửi quản trị Google Cloud* tạo sẵn danh sách cần cấp (client Desktop app, API, 2 vai trò IAM,
email tài khoản, project/dataset/location thật) để sao chép.

| Cổng | Kiểm tra | Lỗi điển hình |
|---|---|---|
| Xác thực | lấy được credentials | `BQ_AUTH_MISSING` / `BQ_AUTH_EXPIRED` |
| API + dataset | BigQuery API bật, đọc được dataset | `BQ_API_DISABLED`, `BQ_PERMISSION_DENIED` |
| Location | location dataset đúng | `BQ_LOCATION_MISMATCH` |
| Metadata bảng | đọc được metadata bảng | `BQ_NOT_FOUND`, `BQ_PERMISSION_DENIED` |
| Query job | dry-run trên bảng (quyền `bigquery.jobs.create` + đọc) và một job thật `SELECT 1` (0 byte) | `BQ_PERMISSION_DENIED` |
| Schema khớp ánh xạ | schema thật khớp ánh xạ đã lưu | `BQ_MAPPING_INVALID` |

Cổng *dữ liệu đủ điều kiện* là **Kiểm tra dữ liệu toàn kỳ** (mục 5).

**Lỗi được phân biệt:**
- `OAUTH_NOT_CONFIGURED`, `OAUTH_CANCELLED`, `OAUTH_BLOCKED`;
- `BQ_AUTH_MISSING`, `BQ_AUTH_EXPIRED`;
- `BQ_PERMISSION_DENIED` (đăng nhập được nhưng thiếu IAM);
- `BQ_NOT_FOUND`, `BQ_LOCATION_MISMATCH`;
- `BQ_SQL_ERROR`, `BQ_SCHEMA_CHANGED`;
- `BQ_QUERY_TOO_EXPENSIVE`, `BQ_TIMEOUT`, `BQ_QUOTA`, `BQ_UNAVAILABLE`.

## 3. Ánh xạ trường

Trang **Ánh xạ trường** có nút **Gợi ý cho bảng demand_planing_lightgbm**:
- gợi ý chỉ điền những cột **có trong schema thật** với kiểu tương thích;
- chưa lưu cho đến khi người dùng bấm *Kiểm tra & lưu ánh xạ*.

| Trường nội bộ | Cột gợi ý | Vai trò |
|---|---|---|
| `order_qty` | `demand_quantity` | **Target**. Không bao giờ tự thay bằng `outbound_quantity`. |
| `order_date` | `created_date` | Ngày nhu cầu. Phải là DATE/DATETIME. Nếu là TIMESTAMP thì gợi ý chuyển sang `created_at` và phải chọn rõ múi giờ, không tự đổi. |
| `sku_id` | `sku_code` | Khóa SKU |
| `fc_id` | `fc_code` | Khóa FC/kho |
| `order_id` | `so_code` | Đếm số đơn, kiểm tra trùng (đơn × SKU × FC × ngày) |
| `source_updated_at` | `refresh_time` | Metadata độ mới của nguồn; không phải feature |

**Trường tham chiếu** chỉ dùng để kiểm tra, đối chiếu và cho feature tương lai. Chúng không phải target và không phải đầu vào mô hình
(trừ `open_hours`, xem dưới):

| Trường tham chiếu | Cột gợi ý | Dùng để |
|---|---|---|
| `product_id`, `item_code` | `product_id`, `item_code` | Định danh, giữ nguyên ý nghĩa |
| `outbound_qty` | `outbound_quantity` | Đối chiếu Σ xuất với Σ nhu cầu |
| `order_status` | `order_status` | Thống kê phân bố. **Không** dùng để lọc thêm dòng. |
| `sales_price`, `price_after_discount` | cùng tên | Độ đầy đủ; feature giá tương lai |
| `seller_code`, `sku_status` | `seller_code`, `sku_system_status` | Độ đầy đủ; feature tương lai |
| `open_date`, `open_days` | `open_date`, `total_open_days` | Độ đầy đủ; feature khả dụng tương lai |
| `open_hours` | `total_open_hours` | **1.2.9: đặc trưng BẮT BUỘC** (xem dưới) |

### Vai trò của trường và của mọi cột nguồn (1.2.9)

Mỗi trường có một vai trò cố định (`settings_service.FIELD_ROLES`, hiển thị ở cột *Vai trò*):

| Vai trò | Trường |
|---|---|
| Khóa dữ liệu | `order_date` / `created_at` (ngày), `sku_id`, `fc_id` (grain SKU × FC × ngày); `order_id` (khóa dòng nguồn, dùng phát hiện trùng) |
| Target | `order_qty` |
| Đặc trưng bắt buộc | `open_hours` (`total_open_hours`) |
| Đặc trưng tùy chọn | `unit_price`, `discount_amount`, `promotion_flag` (bật/tắt ở Cấu hình mô hình) |
| Tham chiếu / metadata | mọi trường còn lại (`promotion_id`, `voucher_*`, `source_updated_at`, `batch_id` và các trường tham chiếu khác) |

- Thẻ **Tất cả cột của nguồn D-1** liệt kê mọi cột của schema đã đọc: cột có trường dùng mang vai trò của trường đó; cột không
  trường nào dùng là **Chưa phân loại** cho tới khi người dùng đánh dấu **Tham chiếu** (`bigquery.extra_reference_columns`,
  lưu cùng ánh xạ, D-1 không đọc, mô hình không dùng, không thuộc mapping hash). Không cột nào tự thành khóa, target hay đặc
  trưng chỉ vì có trong bảng.
- Kiểm tra: thiếu trường bắt buộc (`REQUIRED_NOT_MAPPED`, kể cả `open_hours`); một cột vừa là khóa/target vừa là đặc trưng,
  hoặc hai đặc trưng cùng một cột (`COLUMN_ROLE_CONFLICT`); hai khóa cùng một cột (`SAME_COLUMN_FOR_SEVERAL_KEYS`); cột tham
  chiếu bổ sung đã được trường khác dùng (`EXTRA_REFERENCE_ALREADY_MAPPED`) hoặc không còn trong nguồn (cảnh báo). Một trường
  tham chiếu đọc chung cột với một đặc trưng (vd. `sales_price`) chỉ là cảnh báo `COLUMN_USED_TWICE`.
- `open_hours` được giữ trong `reference_mapping` như trước 1.2.9 để ánh xạ đã lưu và **mapping hash không đổi** (production
  không phải kiểm tra lại toàn kỳ vì nâng cấp).

### Giờ mở bán `total_open_hours` (1.2.9, đặc trưng bắt buộc)

Định nghĩa (chủ hệ thống, 19/10/2026): số giờ trong một ngày SKU được mở để bán. Miền 0–24 suy từ định nghĩa và đúng với
bảng thật (profile chỉ đọc 01/01–18/10/2026: min 0, max 24, không âm, không > 24; NULL toàn bộ trước **19/03/2026**, không
NULL từ ngày đó; các dòng cùng ngày × SKU × FC bằng nhau, trừ **2 khóa tháng 8**). Quy tắc (`backend/app/data/open_hours.py`):

| Dòng đơn của ngày × SKU × FC | Lưu `open_hours` / `open_hours_status` |
|---|---|
| mọi dòng có giá trị, bằng nhau, trong 0–24 | giá trị / `OK` (0 là giá trị hợp lệ) |
| có dòng NULL | NULL / `MISSING` |
| có giá trị < 0 hoặc > 24 | NULL / `OUT_OF_RANGE` |
| các dòng khác nhau, nhưng mỗi item một giá trị (1.2.9b, cần ánh xạ `item_code`) | NULL / `MULTI_ITEM`: giờ mở bán đo theo item (`item_code` của SKU; hậu tố `.1`, `.2` là thứ tự mở bán ở các miền, không phải mã miền), chưa có quy tắc gộp về SKU × FC |
| các dòng khác nhau, không giải thích được bằng item (cùng item hai giá trị, hoặc dòng không có item) | NULL / `CONFLICT` (cần điều tra) |

Không bao giờ thay bằng 0, giá trị ngày bên cạnh hay giá trị ước lượng. Dòng nạp trước 1.2.9 không có trạng thái
(`NOT_LOADED`); D-1 gia tăng chỉ đọc lại vài ngày gần nhất, nên cần **nạp lại D-1 toàn kỳ** để đọc cột cho lịch sử. Kiểm tra
toàn kỳ báo `OPEN_HOURS_MISSING` / `OPEN_HOURS_OUT_OF_RANGE` dạng cảnh báo (không chặn D-1 nạp nhu cầu); **huấn luyện nguồn
BIGQUERY dừng** với `OPEN_HOURS_INVALID` (số dòng và khoảng ngày theo từng trạng thái) khi còn bất kỳ dòng nào của cửa sổ dữ
liệu không `OK`. Trên dữ liệu thật hiện tại, mở khóa cần quyết định của chủ hệ thống: quy tắc cho ngày thiếu (01/01–18/03) và
cho 2 khóa xung đột, hoặc dời `data_policy.window_start_date` và sửa nguồn.

1.2.9b: `data_policy.training_start_rule = OPEN_HOURS_COVERAGE` (trang Cấu hình > Chính sách dữ liệu; mặc định
`WINDOW_START` như cũ) cho mô hình bắt đầu từ **ngày đầu tiên đã lưu có giờ mở bán**, tính lại từ dữ liệu ở mỗi lần dùng.
Ngày trước đó vẫn lưu và vẫn được D-1 / backfill đọc (mốc đọc = `window_start_date`, mapping hash không đổi). Nguồn chỉ giữ
giờ mở bán khoảng **7 tháng gần nhất** (mục 11c): đọc lại ngày cũ hơn sẽ thay giá trị đã lưu bằng `MISSING`; bản xem trước
backfill cảnh báo `OPEN_HOURS_WOULD_BE_LOST`, kết quả nạp đếm `open_hours_lost`.

### Mã khách hàng `customer_id` (1.2.9b, tùy chọn, mặc định không dùng)

`bigquery.customer_id_column` (thẻ *Mã khách hàng* trên trang Ánh xạ; "" = không dùng). Khi có cột, D-1 tính **ngay trong
BigQuery** cho mỗi ngày × SKU × FC: `customer_count` (số khách khác nhau), `repeat_customer_count` (khách đã đặt cùng
SKU × FC trong 90 ngày trước), `repeat_interval_days_sum` (tổng số ngày từ lần đặt trước của họ). Câu truy vấn đọc thêm 90
ngày trước khoảng nạp chỉ để tính số này; mã rỗng / NULL không tính là khách nhưng nhu cầu của dòng vẫn tính đủ. Mã khách
**không bao giờ** được lấy về, lưu, ghi log hay xuất; ngày không có mã = NULL (không phải 0). Cột phải tồn tại ở nguồn với
kiểu STRING / INTEGER (`COLUMN_NOT_FOUND` / `TYPE_NOT_ALLOWED`). Lưu cột này đổi mapping hash (như mọi thay đổi ánh xạ):
production tắt cho tới khi kiểm tra toàn kỳ và kích hoạt lại; để trống thì hash không đổi. Mô hình chỉ dùng khi bật nhóm
*Hành vi mua lại của khách* (`model.feature_customer`, mặc định tắt) và dữ liệu đủ độ phủ (MO-HINH-VA-CHI-SO.md).

`unit_price`, `discount_amount`, `promotion_flag`, `voucher_*` **không được ánh xạ tự động**. Để ánh xạ, cần quyết định nghiệp vụ, ví dụ `sales_price` có phải đơn giá lúc đặt hàng hay không. Khi các trường này chưa có dữ liệu, các feature giá, chiết khấu và khuyến mãi **không được dùng** (xem MO-HINH-VA-CHI-SO.md, mục Feature registry).

## 4. Các phép biến đổi ở lớp ứng dụng

Toàn bộ quy tắc nằm ở đây; không có quy tắc nào khác.

1. **Khoảng đọc:** từ **cửa sổ dữ liệu** `data_policy.window_start_date` (mặc định **2026-01-01**; một
   `history_start_date` muộn hơn vẫn được tôn trọng, sớm hơn thì không) đến hôm nay. Từ 1.1.7 không còn tải lùi 730
   ngày (`initial_history_days` không còn dùng). Lần nạp lại toàn bộ chỉ thay phần từ đầu cửa sổ; dòng đã lưu trước
   cửa sổ được giữ nguyên (`rows_kept_before_window`) và không bao giờ được dùng cho mô hình. Bộ lọc nằm trong truy vấn của ứng dụng (`DATE(created_date) BETWEEN …`), không nằm trong SQL nguồn. Bộ lọc partition được nới thêm 1 ngày mỗi phía.
2. **Một dòng nguồn được giữ nguyên ý nghĩa.** Dòng bị loại, theo thứ tự ưu tiên:
   - `NULL_SKU`;
   - `NULL_FC`;
   - `NULL_TARGET`: **không đổi NULL thành 0**;
   - `NEGATIVE_TARGET`.

   Mỗi lý do có số dòng và tổng số lượng riêng. Dòng thiếu ngày nằm ngoài mọi khoảng ngày nên được đếm riêng (`NULL_DATE`).
3. **Tổng hợp về SKU × FC × ngày:** `qty = Σ demand_quantity` của các dòng hợp lệ. `n_orders = số so_code khác nhau`. Không cộng cột số nào khác; giá không được cộng.
4. **Dòng trùng hoàn toàn** là dòng giống nhau ở **mọi cột đã ánh xạ**. Chính sách xử lý (`exact_duplicate_policy`):
   - `BLOCK` (mặc định): báo cáo và chặn kiểm tra/đồng bộ;
   - `KEEP`: cộng như dữ liệu nguồn;
   - `DROP_EXACT`: loại bỏ và báo cáo số dòng đã loại.
5. **Đối chiếu bắt buộc:**
   - số dòng đọc = hợp lệ + bị loại (+ trùng đã loại);
   - tổng số lượng đọc = hợp lệ + bị loại;
   - sau khi ghi, Σ qty trong ứng dụng = Σ hợp lệ đọc được.

   Không khớp thì **không ghi gì** (`BQ_SYNC_RECONCILIATION_FAILED`).
6. **Ngày thiếu:**
   - Ngày lịch không có dòng nào trong toàn bảng là *thiếu dữ liệu* (NaN), **không** coi là nhu cầu 0.
   - Một SKU×FC không có dòng trong một ngày *có* dữ liệu thì là 0 (không có đơn).
   - FC không có dòng trong ngày mà FC khác có được liệt kê để người dùng kiểm tra.

## 5. Kiểm tra dữ liệu toàn kỳ

Nút **Kiểm tra dữ liệu toàn kỳ**: kết quả gắn với *mã ánh xạ* hiện tại. Mọi thay đổi ánh xạ, khoảng ngày hay chính sách trùng đều làm kết quả cũ hết hiệu lực.

**Thống kê:**
- khoảng ngày, số dòng đọc/hợp lệ/bị loại theo lý do, tổng target;
- số SKU, FC, chuỗi, số ngày có dữ liệu;
- dòng trùng hoàn toàn và trùng đơn × SKU × FC × ngày;
- ngày thiếu, FC thiếu ngày;
- giá trị bất thường (max > 100 × p99);
- phân bố `order_status` / `sku_status`;
- độ đầy đủ trường tham chiếu;
- Σ outbound / Σ demand;
- độ mới dữ liệu.

**Vấn đề chặn:**
- không có dữ liệu;
- ánh xạ sai;
- cột đã ánh xạ bị đổi hoặc xóa;
- tỷ lệ thiếu SKU/FC/target/ngày hoặc target âm > `max_null_share` (mặc định 5%);
- dòng trùng hoàn toàn khi chính sách là `BLOCK` (kèm số nhóm / số dòng / số dòng dư và file báo cáo `.xlsx`, mục 13);
- đối chiếu không khớp.

Chế độ sản xuất, đồng bộ D-1 và huấn luyện nguồn BIGQUERY **chỉ chạy khi kết quả kiểm tra của ánh xạ hiện tại là Đạt** (`BQ_VALIDATION_REQUIRED`).

## 6. Thứ tự bật nguồn BIGQUERY

1. Kiểm tra xác thực.
2. Kiểm tra kết nối (metadata, không tốn phí truy vấn).
3. Đọc schema (metadata).
4. Ánh xạ trường: dùng gợi ý, xem lại, rồi lưu.
5. Xem trước: tối đa `preview_rows` dòng của 7 ngày gần nhất.
6. Kiểm tra dữ liệu (30 ngày).
7. **Kiểm tra dữ liệu toàn kỳ.**
7b. **Kiểm tra trùng & thử tổng hợp (không ghi)** — các bước của lần D-1 kế tiếp, không ghi dữ liệu (mục 13).
8. Kích hoạt chế độ sản xuất.
9. Chọn nguồn `BIGQUERY` ở góc trên. Đây là thao tác của người dùng; ứng dụng không tự đổi nguồn.
10. Đồng bộ D-1 (theo lịch, hoặc *Job & Scheduler* → chạy D1_SYNC).
11. Huấn luyện.

**Lưu ý về đồng bộ:**
- Lần đồng bộ đầu tiên, hoặc khi mã ánh xạ thay đổi, sẽ **tải lại toàn kỳ**: dữ liệu BIGQUERY từ ngày bắt đầu cửa sổ dữ
  liệu (`window_start_date`) được thay; dữ liệu lưu trước cửa sổ được giữ nguyên.
- Các lần sau chỉ đọc lại từ watermark − `late_data_lookback_days` ngày.
- Nguồn trả về **0 dòng** trong khi ứng dụng đang có dữ liệu cho khoảng đó (bảng đang được dựng lại, view/SQL rỗng, mất
  quyền): job **không xóa gì**, báo `SOURCE_INCOMPLETE` (lý do `EMPTY_READ`), thử lại rồi *Thất bại* kèm cảnh báo. (Sửa
  trong mã nguồn sau 1.1.8, kiểm toán 16/10/2026; bản cài 1.1.8 chưa có chốt này.)
- Ảnh chụp D0: vì `created_date` là ngày, không có giờ, ảnh chụp là tổng *đến lúc đọc* của ngày hôm nay theo dữ liệu hiện có trong bảng; độ mới xem ở `refresh_time`.

## 7. Lỗi được phân loại

| Mã | Ý nghĩa | Thử lại tự động |
|---|---|---|
| `BQ_AUTH_MISSING` | Chưa có credentials | Job được thử lại theo `max_attempts` của lịch chạy (giãn `retry_base_seconds` × 2^n), rồi *Thất bại* |
| `BQ_AUTH_EXPIRED` | Credentials hết hạn / bị thu hồi | Không |
| `BQ_PERMISSION_DENIED` | Thiếu quyền | Không |
| `BQ_NOT_FOUND` / `BQ_LOCATION_MISMATCH` | Sai project/dataset/table hoặc location | Không |
| `BQ_TIMEOUT` | Vượt `query_timeout_seconds`; job bị hủy | Không (tránh nhân chi phí) |
| `BQ_QUOTA` / `BQ_UNAVAILABLE` | Quota/rate limit, dịch vụ tạm lỗi | Có, tối đa `max_retries` lần (mặc định 2), giãn 2–4 giây |
| `BQ_QUERY_TOO_EXPENSIVE` | Dry-run vượt giới hạn bytes | Không |
| `BQ_SCHEMA_CHANGED` / `BQ_MAPPING_INVALID` | Schema không còn khớp ánh xạ | Không |
| `BQ_DATA_DUPLICATES` / `BQ_SYNC_RECONCILIATION_FAILED` | Dữ liệu trùng (chính sách CHẶN) / đối chiếu không khớp | Không; không ghi dữ liệu |

## 8. Chi phí

BigQuery tính phí theo bytes quét:
- **Kiểm tra toàn kỳ** chạy 4 truy vấn trên các cột đã ánh xạ của khoảng ngày đọc; tổng ước tính hiển thị trên trang.
- **Đồng bộ D-1** sau lần đầu chỉ quét vài ngày **khi bảng nguồn được phân vùng theo cột ngày** (chế độ TABLE có
  `partition_column`). Kiểm tra thật 16/10/2026: bảng `demand_planing_lightgbm` **không phân vùng**, nên mỗi truy vấn quét
  toàn bộ các cột được chọn bất kể khoảng ngày (khoảng 0,2–0,7 GB mỗi truy vấn với 8,9 triệu dòng, tăng dần theo thời
  gian). Ở chế độ SQL lịch sử, bộ lọc phân vùng không được áp dụng.

Ứng dụng không tạo scheduler mới. D-1/D0 chỉ chạy khi nguồn đang dùng là BIGQUERY và chế độ sản xuất đã bật.

## 9. SQL nguồn: lịch sử và D0 (từ 1.1.6)

Trang **SQL nguồn & đồng bộ** quản lý hai nguồn độc lập:
- **Lịch sử** (D-1 trở về trước, chạy 1 lần/ngày): mặc định đọc **bảng** đã cấu hình. Có thể chuyển sang **SQL do người dùng quản lý**.
- **D0** (hôm nay, chạy theo các giờ D0): mặc định là SQL do người dùng cung cấp ngày 15/10/2026, lưu **nguyên văn** là phiên bản 1, **chưa kiểm tra**.

**Quy tắc:**
- Lưu SQL tạo **phiên bản mới**. Phiên bản chỉ được scheduler dùng sau khi **BigQuery dry-run** xác nhận:
  - câu lệnh là `SELECT`;
  - có đủ cột cần thiết (SKU, FC, số lượng, ngày cho lịch sử) và cột khóa;
  - chi phí dưới giới hạn.
- Phiên bản lỗi không thay phiên bản đang dùng. Job mới bị chặn (`SQL_NOT_VALIDATED`, ghi nhận là *bỏ qua — cần cấu hình*) nếu chưa có phiên bản đạt. Không bao giờ âm thầm dùng truy vấn khác.
- Khôi phục: phiên bản đã đạt được kích hoạt lại; phiên bản chưa đạt được sao thành phiên bản mới và phải kiểm tra lại. Tối đa 50 phiên bản mỗi nguồn.
- **Chỉ đọc.** Kiểm tra tĩnh từ chối:
  - nhiều câu lệnh;
  - câu không bắt đầu bằng `SELECT`/`WITH`;
  - từ khóa ghi/xóa/DDL/script (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, `EXECUTE`, `DECLARE`, `SET`, `BEGIN`…), bỏ qua phần nằm trong chuỗi, comment hay tên trong dấu nháy ngược.

  Ứng dụng chỉ chạy SQL dưới dạng truy vấn con `SELECT … FROM ( <SQL người dùng> )` và **không tự sửa SQL**. Dấu `;` cuối câu được bỏ khi lồng vào.
- **Xem trước** tối đa `preview_rows` dòng (≤ 500), sau khi dry-run. **Kiểm tra dữ liệu** chạy thống kê trên dữ liệu thật mà không ghi gì.
- Mỗi job **chụp** phiên bản SQL (id + sha256 + nội dung) lúc bắt đầu và dùng bản chụp đó đến khi kết thúc. Phiên bản được ghi trong kết quả job; với D0, phiên bản cũng nằm trong `source_batch_id` của snapshot.
- **Đổi SQL không đổi feature của mô hình.** Feature registry quyết định riêng.
- Đổi SQL lịch sử hoặc tùy chọn khóa làm mã ánh xạ thay đổi: phải kiểm tra dữ liệu toàn kỳ lại và chế độ sản xuất tự tắt.
- Lưu ánh xạ trường (kể cả chỉ đổi *Bắt buộc/Tùy chọn*, ví dụ `unit_price` OPTIONAL → REQUIRED lúc 17:32 ngày
  17/10/2026) luôn **tắt chế độ sản xuất** và đổi mapping hash. `REQUIRED` chỉ có nghĩa "phải được ánh xạ tới một cột có
  thật, đúng kiểu"; dòng thiếu giá trị của trường đó **không** bị loại khỏi nhu cầu. Từ 1.2.3 trang Ánh xạ hỏi xác nhận
  trước khi lưu và báo sau khi lưu; `SOURCE_NOT_READY` ghi rõ tắt từ lúc nào, do thay đổi nào, cách khắc phục (*Kiểm tra
  dữ liệu toàn kỳ* → *Kích hoạt chế độ sản xuất*). *Tắt chế độ sản xuất* giữ nguyên nguồn đang dùng (trước 1.2.3 nút này
  tự chuyển sang DEMO).
- **Tên sản phẩm (1.2.4).** Bảng D-1 không có tên sản phẩm. Tên lấy từ `<project>.<dataset>.dim_sku`
  (`bigquery.product_names_table`, khóa `sku_code`, cột `product_name`; kiểm tra thật 17/10/2026: 298.517 dòng =
  298.517 `sku_code` khác nhau, 0 tên rỗng), đọc 2 cột (~23 MB/lần, dry-run trước, giới hạn byte), chỉ giữ SKU có trong
  dữ liệu BIGQUERY cục bộ. SKU có nhiều tên khác nhau → không gán tên; SKU không có trong bảng → "Chưa có tên sản phẩm".
  Tự làm mới sau mỗi lần D-1 thành công; làm tay: `POST /api/bigquery/product-names/refresh` hoặc
  `app.cli product-names-refresh`. Tên chỉ để hiển thị / tìm kiếm / Excel, không đổi số lượng hay chỉ số nào.

## 10. SQL D0 do người dùng cung cấp — các điểm cần xác nhận

SQL được lưu nguyên văn (sha256 `b9d6d9f56a091d86…`). Kiểm tra tĩnh **không** coi đây là lỗi, chỉ ghi chú.

**Ghi chú từ kiểm tra tĩnh** (chưa xác nhận trên BigQuery):
- `TRAILING_COMMA_BEFORE_FROM`: có dấu phẩy sau `b.sales_price` ngay trước `FROM`. Chỉ dry-run BigQuery quyết định đây có phải lỗi cú pháp. DuckDB chấp nhận cú pháp này.
- `LEFT_JOIN_WITH_WHERE`: điều kiện `c.seller_code`, `c.sku_system_status` trong `WHERE` loại các dòng không có bản ghi master SKU, tức tương đương `INNER JOIN`.
- `DATE_OF_TIMESTAMP_WITHOUT_TIMEZONE`: `DATE(a.created_at)` không có múi giờ. Nếu `created_at` là TIMESTAMP thì đây là ngày **UTC**, trong khi điều kiện lọc là `CURRENT_DATE('Asia/Ho_Chi_Minh')`. Ứng dụng **không** lọc thêm theo ngày cho D0; ngày xuất hiện trong kết quả được báo cáo (`D0_DATES_OTHER_THAN_TODAY`).

**Kiểm thử logic trên DuckDB** (dữ liệu tổng hợp, không phải BigQuery) cho thấy:
- đơn tạo lúc 02:00 giờ VN mang `created_date` của ngày hôm trước;
- mã `sub_sku_code` lặp trong `adhoc_pm_master_sku` **nhân đôi** nhu cầu.

Khóa ứng viên (mặc định: `so_code` + `sku_code` + `fc_code` + `created_date` theo ánh xạ) bị trùng thì **chặn ghi** (`BQ_KEY_NOT_UNIQUE`). Chỉ khi người dùng chọn rõ "Cộng tất cả dòng" thì mới ghi.

**Phiên bản 2 — đề xuất hiệu chỉnh** (chưa xác nhận nghiệp vụ, chưa kiểm tra, **không** tự kích hoạt; file `backend/app/bq/d0_proposed_v2_20261015.sql`):
1. bỏ dấu phẩy thừa;
2. `LEFT JOIN` → `JOIN`: kết quả giống bản gốc, vì `WHERE` đã loại dòng không khớp;
3. điều kiện master đưa vào CTE `master` + `DISTINCT`, nên dòng master trùng hoàn toàn không còn nhân đôi nhu cầu;
4. `DATE(a.created_at, 'Asia/Ho_Chi_Minh')`: **chỉ đúng nếu** `created_at` là TIMESTAMP (UTC); nếu là DATETIME giờ VN thì giữ như bản gốc.

Trên DuckDB với dữ liệu tổng hợp, phiên bản 2 cho cùng các dòng và số lượng như bản gốc, ngày theo giờ VN, và không nhân đôi khi master trùng hoàn toàn.

**Lịch D0 BigQuery mặc định TẮT.** Lịch chỉ bật được khi phiên bản SQL D0 đang dùng đã kiểm tra đạt. Lượt chạy theo lịch khi đang tắt được ghi nhận *bỏ qua* (`D0_SCHEDULE_DISABLED`); chạy tay vẫn được nếu SQL đã đạt.

**Cần xác nhận trên dữ liệu thật:**
- cột `b.created_date` có trong `fact_order_item` không;
- quan hệ join có nhân dòng không;
- ý nghĩa `demand_quantity`;
- múi giờ của `created_at`/`created_date`;
- khóa ổn định của một dòng D0.

## 11. Job đồng bộ độc lập

- **Hai job độc lập:**
  - `D1_SYNC` chạy một lần/ngày từ `d1_signal_poll_start` (chờ tín hiệu hoàn tất hoặc mốc dự phòng);
  - `D0_SYNC` chạy theo danh sách giờ D0 (mặc định 08:00…18:00).

  D0 không bao giờ gọi truy vấn lịch sử và ngược lại.
- **Không chạy chồng:** khóa theo loại job. **Retry** có giới hạn. Retry D0 không tạo snapshot thứ hai (kiểm tra theo `job_id`).
- **D-1 ghi theo cửa sổ ngày** (xóa rồi chèn trong một giao dịch) và đối chiếu số đã ghi với số đọc được.
  - Báo cáo số dòng SKU×FC×ngày mới / cập nhật / không đổi / bị bỏ, và dòng bị loại theo lý do.
  - Đổi mã ánh xạ thì tải lại toàn kỳ.
- **Backfill có kiểm soát** (người dùng yêu cầu):
  - chỉ cho khoảng trong `[đầu khoảng đọc, hôm qua]`, tối đa 400 ngày;
  - cần chế độ sản xuất và kiểm tra dữ liệu đạt;
  - cần đã có một lần đồng bộ thường với ánh xạ hiện tại.
  - 1.2.9: **bắt buộc xem trước** (`POST /api/sync/backfill/preview`, nút "Xem trước (không ghi)"). Bước này dùng
    cùng kiểm tra và cùng lần đọc BigQuery với lần nạp: chỉ đọc, dry-run trước, giới hạn byte, kiểm trùng lặp.
    Nó báo số dòng mới / đổi số / giữ nguyên / bị xóa, tổng số lượng trước và sau, trạng thái giờ mở bán sẽ ghi, và số
    ngày đã chốt 23:59 sẽ có bản chốt bổ sung. Không ghi `demand_daily`; kết quả lưu ở `sync_state`
    `bq_backfill_preview` và audit `D1_BACKFILL_PREVIEW`.
  - 1.2.9: `POST /api/sync/backfill` cần `preview_id` của bản xem trước `READY`, đúng khoảng ngày, cùng mapping hash và
    cùng SQL nguồn, không quá 6 giờ (`BACKFILL_PREVIEW_MAX_AGE_HOURS`). Mỗi bản xem trước dùng được **một lần**
    (`USED`). Sai thì `BACKFILL_PREVIEW_REQUIRED`; API kiểm trước khi tạo job, job kiểm lại lần nữa.
  - 1.2.9: ngay trước khi thay dữ liệu, job tạo **backup online đã kiểm** (`backup-…-pre-backfill.zip`, gồm DB và model)
    và ghi tên file vào kết quả job. Không tạo được backup thì `BACKFILL_BACKUP_FAILED` và không ghi gì.
  - 1.2.9: trong chính giao dịch ghi, trước khi xóa, job kiểm lại ba điều:
    - bản xem trước vẫn `READY` (chưa job nào khác dùng);
    - không có lần D-1 thường nào chạy sau bản xem trước;
    - số dòng mới / đổi / bị xóa đúng bằng số đã xem trước.

    Sai một điều thì `BACKFILL_PREVIEW_REQUIRED`, không ghi gì, cần xem trước lại.
  - Đọc rỗng khi đang có dữ liệu thì bản xem trước là `BLOCKED` (lần nạp cũng từ chối).
  - Khoảng có ngày hôm qua mà nguồn chưa có tín hiệu hoàn tất thì bản xem trước có cảnh báo `YESTERDAY_NOT_CONFIRMED`.
  - Chỉ thay các dòng `demand_daily` của scope trong khoảng đã chọn, giống nguồn hiện tại. Không đổi snapshot D-0,
    forecast, model, lịch sử forecast, bản sao cuối ngày, mốc `last_d1_sync`; không kích hoạt huấn luyện
    (`flows.d1_success_today` bỏ qua backfill). Ngày đã chốt 23:59 có thực tế thay đổi được thêm bản chốt mới; các bản
    chốt trước giữ nguyên.
  - Diễn tập trên bản sao DB production ngày 19/10/2026 (đọc BigQuery thật, ghi bản sao): khoảng 01/01–18/10 mất
    735 s, đọc 1,27 GB, RAM của tiến trình khoảng 1,9 GB. Nên chia backfill lớn theo tháng, ngoài giờ D-1 / D-0 /
    huấn luyện. Chi tiết trong `reports/demandforecast_comprehensive_upgrade_review.md`.
- **Đồng bộ không kích hoạt huấn luyện.** Huấn luyện có lịch riêng; với BIGQUERY còn chờ D-1 thành công và kiểm tra dữ liệu đạt.
- **Dữ liệu D0** nằm trong bảng snapshot riêng, không bao giờ được dùng làm dữ liệu huấn luyện lịch sử.
- **Múi giờ lịch chạy:** `Asia/Ho_Chi_Minh` (múi giờ duy nhất ứng dụng hỗ trợ), hiển thị trên trang.

## 11b. Giờ mở bán và trạng thái SKU trong nguồn thật (kiểm tra chỉ đọc ngày 19/10/2026)

- `total_open_hours` chỉ có từ **19/03/2026**. Các dòng trước đó đều NULL, nên D-1 ghi `MISSING` cho mọi ngày
  01/01–18/03 (400.082 dòng ngày × SKU × FC).
- Hai nhóm `CONFLICT` (26/08/2026, FC `BD`) đều có **hai `item_code`** của cùng SKU và cùng seller. Mỗi item có giờ mở
  bán riêng và nhất quán (23,72 / 24 và 18,22 / 22,85). Nghĩa là nguồn tính giờ mở bán theo **item**, còn D-1 gộp theo
  SKU × FC. Từ 19/03: 954.891 nhóm ngày × SKU × FC, chỉ 11 nhóm có nhiều item, 2 trong số đó lệch giờ. Không có nhóm
  nào nhiều seller hay nhiều `open_date`.
- 722 dòng ngày × SKU × FC có giờ mở bán = 0 dù có đơn (ví dụ tháng 8: 669 dòng đơn). Không tự diễn giải: ghi `OK`
  với giá trị 0, khác với "thiếu".
- `sku_system_status` (`NORMAL` / `OUT_OF_STOCK` / `LIMIT`) gần như không đổi theo ngày: chỉ 35 trong 17.128 cặp
  SKU × FC có hơn một giá trị trong 01/01–18/10. Đây là **trạng thái hiện tại** được chép vào mọi dòng lịch sử, không
  phải trạng thái của ngày đó, nên **không được dùng làm feature** (rò rỉ thông tin tương lai).
- Không có cột khách hàng (`customer_id`) trong bảng nguồn (17 cột, kiểm metadata ngày 19/10/2026).
- `order_status` không có giá trị huỷ trong 01/01–18/10. Gồm COMPLETED, DELIVERED, DELIVERING, CONFIRMED,
  WAIT_TO_DELIVER, WAIT_TO_CONFIRM và PROCESSING.

## 11c. Kiểm tra chỉ đọc ngày 20/10/2026 (bảng làm mới lúc 00:10 UTC; khoảng 3,4 GB quét)

- **Giờ mở bán đo theo item và ngày.** 108 item-ngày xuất hiện ở hai FC trong cùng ngày: giờ mở bán luôn giống nhau; trong
  một item × FC × ngày không có hai giá trị. `item_code` = `<sku_code>.<số thứ tự>`; phần lớn dòng của một item đi qua
  một FC. 130 / 17.114 item từng xuất hiện ở hai FC; không item nào thuộc hai SKU.
- **Khóa nhiều item** (ngày × SKU × FC): 101 khóa, chỉ trong tháng 2 (35), tháng 3 (55) và ngày 26/08 (11); ngày 26/08:
  9/11 khóa cùng giờ (OK), 2 khóa khác giờ; 1.2.9b gọi là `MULTI_ITEM`. Bảng nguồn không có cột miền bán.
- **Đính chính (đợt 5, 20/10/2026):** câu cũ "`.1` ở BD, `.2` ở HN", "item vùng HN" và "khác biệt giữa miền bán" đã bị
  rút lại. Hậu tố `.1`, `.2`, `.3` là **thứ tự SKU được mở bán ở các miền**, không phải mã miền (chủ hệ thống xác nhận):
  không suy ra miền, FC hay giờ mở bán từ hậu tố. Số dòng theo `fc_code` ở trên vẫn là dữ kiện.
- **Nguồn giữ giờ mở bán cuộn khoảng 7 tháng**: bản 19/10 có giá trị từ 19/03, bản 20/10 từ 20/03 (19/03 thành NULL). Mốc
  này đi theo ngày làm mới (ngày làm mới − 7 tháng); cần chủ dữ liệu xác nhận.
- **Nguồn sửa lịch sử ở mỗi lần làm mới**: so với bản sao nạp tối 19/10, 276 / 291 ngày có tổng số lượng khác (−12.313 đơn
  vị trên 41,9 triệu); số dòng bảng 8.942.586 → 8.939.819. D-1 gia tăng chỉ đọc lại 3 ngày gần nhất.
- **Giờ mở bán = 0 nhưng có đơn**: 2.592 dòng đơn (20.987 đơn vị), 718 khóa ngày × SKU × FC; 1.398 dòng đã xuất hàng
  (`outbound_quantity` > 0). Workbook kiểm tra: `reports/zero_open_hours_orders_20261020.xlsx` (ngoài Git).
- **Hai khóa `MULTI_ITEM` ngày 26/08** (kiểm tra chỉ đọc lần 2, bản làm mới 12:29 ngày 20/10, ~2,3 GB): cùng FC `BD`, hai
  item (`.1` chỉ có dòng ở FC BD; `.2` có 99–99,6% số dòng ở FC HN, ở BD đúng 1 dòng là ngày đó), đơn khác nhau trong mỗi khóa;
  hai dòng `.2` ở BD cùng thuộc một đơn (11 dòng, 11 SKU, toàn item `.2` / `.3`), đơn này có mặt ở 9/11 khóa nhiều item
  của BD ngày 26/08. Mỗi item một giá trị giờ / ngày. Workbook: `reports/demandforecast_multi_item_review_20261020.xlsx`
  (ngoài Git). Quy tắc giá trị ở hạt SKU × FC vẫn chờ chủ hệ thống quyết định.

## 11d. Kiểm tra chỉ đọc sau khi chủ dữ liệu bổ sung giờ mở bán (bản làm mới 15:05:19 ngày 20/10/2026; ~8 GB quét)

- Bảng được tạo lại lúc 08:05:30 UTC; `refresh_time` = `15:05:19 20/10/2026` trên mọi dòng; 8.961.566 dòng,
  01/01–19/10/2026, đủ 292 ngày, 2 FC (BD, HN). Mọi dòng hợp lệ theo quy tắc D-1 (0 thiếu SKU / FC / số lượng, 0 âm).
- **`total_open_hours` có giá trị trên mọi dòng** (bản 07:10 cùng ngày còn 2.946.849 dòng NULL, toàn bộ 01/01–19/03).
  0 NaN / Inf / âm / > 24; 8.682.210 dòng = 24 giờ, 276.339 dòng trong (0, 24), 3.017 dòng = 0 (đều có số lượng > 0).
- Ở hạt ngày × SKU × FC (1.357.889 khóa): 1.357.883 `OK`, **6 `MULTI_ITEM`** (09/02 HN, 10/02 HN, 02/03 BD × 2,
  26/08 BD × 2; 156 đơn vị), 0 `MISSING` / `CONFLICT` / `OUT_OF_RANGE`. 931 khóa `OK` có giờ = 0 nhưng có đơn (25.542
  đơn vị, 0,06%): không tự diễn giải.
- 0 dòng trùng hoàn toàn (17 cột). 7.203 dòng lặp khóa D-1 (so_code, sku_code, fc_code, ngày): luôn cùng item, khác
  số lượng và/hoặc giá, được cộng theo quy tắc SUM_ALL đã duyệt. Không item nào thuộc hai SKU; mọi `item_code` bắt đầu bằng
  `<sku_code>.`; 0 item × FC × ngày có hai giá trị giờ.
- Preview backfill của 1.2.9 trên bản sao (01/01–19/10) cho đúng các số trên. So với DB production (nạp tăng dần): 344
  khóa mới, 213 khóa đổi số lượng, 772 khóa nguồn không còn, −12.109 đơn vị (−0,03%) - nguồn sửa lịch sử ở mỗi lần làm mới.

## 11e. Giờ = 0 có đơn và dữ liệu khả năng bán (kiểm tra chỉ đọc 20/10/2026 tối; cùng bản làm mới 15:05:19; ~11,6 GB quét)

- 931 khóa `OK` có giờ = 0 và có đơn = 3.017 dòng, 25.542 đơn vị, 133 chuỗi SKU × FC, 01/01–18/10; mọi dòng của các khóa
  đó đều = 0 (không khóa `MULTI_ITEM` / `CONFLICT` nào chứa dòng giờ 0). Ứng dụng lưu đúng `0` / `OK`, gate training
  không chặn, feature nhận 0 (test `test_v129f_zero_open_hours.py`). Ý nghĩa nghiệp vụ: chủ hệ thống xem workbook
  `reports/demandforecast_zero_open_hours_with_orders_20261020.xlsx` (không versioned).
- `open_date` = `created_date` trên mọi dòng; `total_open_days` = round(`total_open_hours` / 24, 2) trên mọi dòng: hai cột
  này **không** cho biết gì về ngày không có đơn. Bảng nguồn chỉ có dòng đơn (số lượng tối thiểu 1).
- Dòng lớn nhất (71.834, 28/08 BD `MEDX.9DCBBCV8`) có giờ 19,25 (không phải 0); đơn 1 dòng, xuất kho đủ.
- Cùng dataset có bảng theo ngày, kể cả ngày không có đơn (chỉ đọc metadata / tổng hợp; **ý nghĩa chưa được chủ dữ liệu
  xác nhận, không dùng cho model**): `fact_product_sku_status` (item × `fc_code` × ngày từ 01/04/2026; `web_status`,
  `is_active`, `product_afs`; ở ngày có đơn với giờ = 0 thì 619/621 dòng có dòng tương ứng là `OUT_OF_STOCK`, giờ = 24 thì
  19 dòng), `fact_sku_is_active_day_by_date` / `fact_sku_status_day_by_date` (từ 02/07 và 20/07/2026, theo
  `sales_region_code`), `staging_sku_status_history` / `staging_sku_is_active_history` (sự kiện từ 06/01/2025),
  `fact_seller_oos` (ảnh chụp theo ngày từ 21/01/2025, có `fc_code`). Dùng trong model chỉ khi đã xác nhận ý nghĩa, ánh
  xạ và thời điểm chụp, và chỉ với ngày trước mốc dự báo.
- Mọi dòng của bảng nguồn có seller `MEDX` / `INTERNAL` (1 seller mỗi tháng).

## 12. Bảng nguồn thật — kiểm tra chỉ đọc ngày 16/10/2026 (11:20, giờ Việt Nam)

Đọc bằng đường xác thực của chính ứng dụng (ADC của tài khoản Windows chạy ứng dụng), trên bản sao DB; chỉ metadata và
truy vấn tổng hợp (dry-run trước, giới hạn 2 GiB), tổng khoảng 3,3 GB quét. Không có dữ liệu dòng nào được lưu.

| Hạng mục | Kết quả |
|---|---|
| Cổng truy cập (`bq-check`) | auth, API + dataset, location `asia-southeast1`, table metadata, query job: **đạt**; schema_mapping: chưa cấu hình ánh xạ (`BQ_MAPPING_INVALID`) |
| Schema (17 cột, đều NULLABLE) | `fc_code`, `so_code`, `order_status`, `sku_code`, `item_code`, `seller_code`, `sku_system_status`, `seller_class` STRING; `created_date`, `open_date` DATE; `product_id`, `demand_quantity`, `outbound_quantity` INTEGER; `sales_price`, `total_open_hours`, `total_open_days` FLOAT; `refresh_time` **STRING** (dạng `HH:MM:SS DD/MM/YYYY`) |
| Phân vùng | **không** (bảng thường, `TABLE`) |
| Dòng / khoảng ngày | 8.885.547 dòng; 01/01/2026 → 14/10/2026; 287 ngày lịch, **không thiếu ngày nào**; mỗi ngày đủ 2 FC |
| Grain `created_date × sku_code × fc_code` | 1.345.228 tổ hợp; 9.669 SKU; 2 FC; 953.397 `so_code` khác nhau |
| Giá trị | Không có NULL ở ngày / SKU / FC / `demand_quantity`; không có số âm; không có số lượng 0; tổng `demand_quantity` 41.654.787 (`outbound_quantity` 39.133.202); 693 dòng `so_code` NULL |
| `order_status` | COMPLETED 8.613.103 dòng; DELIVERED 237.960; DELIVERING 26.197; CONFIRMED 4.383; WAIT_TO_DELIVER 2.582; WAIT_TO_CONFIRM 693; PROCESSING 629; **không có trạng thái hủy** |
| Trùng khóa (`so_code, sku_code, fc_code, created_date`) | 9.516 nhóm có > 1 dòng (9.769 dòng dư, tối đa 5 dòng/khóa; 427 nghìn đơn vị là tổng số lượng *nằm trong* các nhóm, không phải số lượng bị trùng). Trong mọi nhóm: cùng `item_code`, `seller_code`, `product_id`, `order_status`. 432 nhóm có dòng **giống hệt** (445 dòng dư, 21 nhóm có `so_code` NULL); 9.084 nhóm còn lại **chỉ** khác ở `demand_quantity`, `outbound_quantity` hoặc `sales_price` — đó là các dòng khác nhau của cùng đơn, được **cộng dồn** (quy tắc nghiệp vụ xác nhận 16/10/2026, mục 13) |
| Độ mới | `refresh_time` giống nhau ở mọi dòng (`11:44:36 15/10/2026`): bảng được làm mới toàn bộ; ngày D có dữ liệu vào khoảng trưa ngày D+1 (cần cân nhắc giờ D-1 01:00 và huấn luyện 07:00) |
| Ngày thấp bất thường | 13–19/02/2026 (Tết), 01/09/2026 |

## 13. Đưa dữ liệu BigQuery vào ứng dụng: chốt dòng trùng hoàn toàn và tổng hợp (mã nguồn sau 1.1.8, 16/10/2026)

Chưa có trong bản cài 1.1.8; cần một bản phát hành mới (xem `CHANGELOG.md`, mục *Unreleased*).

**Quy tắc nghiệp vụ (đã xác nhận 16/10/2026):**
- Đầu ra: một dòng cho mỗi `created_date × sku_code × fc_code`, `qty = SUM(demand_quantity)` của mọi dòng hợp lệ.
- Nhiều dòng cùng `so_code × sku_code × fc_code × created_date` là bình thường và được **cộng dồn**: luồng lịch sử có
  mặc định `key_duplicate_policy = SUM_ALL` (cảnh báo `KEY_NOT_UNIQUE`, không chặn). Người dùng vẫn có thể chọn `BLOCK`
  ở trang SQL nguồn. Luồng D0 không đổi.
- Không loại dòng vì `so_code` NULL, không thêm bộ lọc `order_status`, không tự thêm 0 cho ngày/SKU-FC không có dòng.
- Chỉ dòng **trùng hoàn toàn** là lỗi dữ liệu: chính sách `exact_duplicate_policy = BLOCK` (mặc định). `KEEP` /
  `DROP_EXACT` là lựa chọn có sẵn từ 1.1.5, **không** được bật để vượt qua lỗi khi chưa có chính sách được duyệt.

**Thế nào là trùng hoàn toàn:**
- Bằng nhau ở **mọi cột đã ánh xạ** (trường nội bộ + trường tham chiếu). Với ánh xạ gợi ý của bảng thật là 15 cột:
  `so_code, created_date, sku_code, fc_code, demand_quantity, product_id, item_code, outbound_quantity, order_status,
  sales_price, seller_code, sku_system_status, open_date, total_open_hours, total_open_days`.
  `seller_class` (không có trường tham chiếu) và `refresh_time` (STRING, không ánh xạ được) không được so sánh; báo cáo
  ghi rõ danh sách này.
- So bằng BigQuery `GROUP BY` trên giá trị gốc, **không** chuyển sang chuỗi: NULL bằng NULL và khác mọi giá trị
  (NULL ≠ 0); số so theo giá trị trong đúng kiểu cột; ngày/giờ so theo giá trị, không đổi múi giờ; chuỗi so chính xác
  (phân biệt hoa thường, giữ khoảng trắng).
- Một cột đã ánh xạ không còn trong nguồn, hoặc thiếu trường bắt buộc: dừng với `BQ_MAPPING_INVALID` kèm danh sách trường
  (không âm thầm so ít cột hơn).
- Số đếm: `duplicate_groups` (số nhóm), `duplicate_rows` (tổng số dòng thuộc các nhóm), `extra_duplicate_rows`
  (số dòng dư nếu mỗi nhóm giữ 1).

**Thứ tự xử lý của D-1 (`sync.run_d1_sync` → `connector.fetch_daily`):**
1. Cấu hình + xác thực; chế độ sản xuất và kiểm tra toàn kỳ đạt cho ánh xạ hiện tại.
2. Phạm vi ngày: tối đa đến **hôm qua theo giờ Việt Nam** (hôm nay không bao giờ được nạp bởi D-1).
3. Ánh xạ so với schema nguồn hiện tại (metadata, không tốn phí).
4. **Chốt trùng hoàn toàn trên dữ liệu gốc, trước khi tổng hợp** (truy vấn `dup_check`). Có trùng: ghi báo cáo, báo
   `BQ_DATA_DUPLICATES`, **không đọc tiếp, không ghi gì**; job *Thất bại* không thử lại.
5. Tổng hợp ngày × SKU × FC trong BigQuery (truy vấn `daily`) + đối soát số dòng/tổng số lượng đọc = hợp lệ + bị loại.
6. Kiểm tra dữ liệu sau tổng hợp: đúng một dòng mỗi khóa, ngày hợp lệ, có SKU/FC, số lượng thật (không NULL/NaN/âm);
   không chuyển gì thành 0 (`BQ_AGGREGATE_INVALID`).
7. Ghi trong **một giao dịch**: xóa cửa sổ của phạm vi BIGQUERY rồi chèn; đối soát lại số đã ghi; lỗi ở bất kỳ bước nào
   thì rollback toàn bộ. Chạy lại cùng phạm vi thay đúng các dòng đó (không nhân đôi). Không chạm dữ liệu DEMO/Excel.

**Báo cáo dòng trùng:** `<reports_dir>\bigquery-duplicates\bq-trung-lap_<từ ngày>_<đến ngày>_<YYYYMMDD-HHMMSS>.xlsx`
(trên máy thật: `D:\Buymed\Lightgbm AI\reports\bigquery-duplicates\`), không bao giờ ghi đè (thêm `-2`, `-3`...).
- `Summary`: thời điểm, bảng nguồn, phạm vi ngày, số dòng nguồn đã kiểm tra, số nhóm, số dòng thuộc nhóm, số dòng dư,
  trạng thái `BLOCKED`, các cột được so sánh / không so sánh, quy tắc so sánh.
- `Duplicate_Rows`: **mọi** dòng của mọi nhóm, `duplicate_group_id` (`DUP-00001`..., theo thứ tự giá trị nên ổn định
  với cùng dữ liệu) và `duplicate_occurrence` (1..n), tên cột là tên cột nguồn.
- `Duplicate_Groups`: một dòng mỗi nhóm, số lần xuất hiện và các giá trị để tra cứu.
- Không ghi được `.xlsx`: ghi 3 file CSV (UTF-8) cùng tên gốc và nêu lỗi; không ghi được gì: nêu lỗi. Dữ liệu vẫn bị chặn.
- Tải ở trang **BigQuery** (thẻ *Báo cáo dòng trùng gần đây*, hoặc link trong kết quả kiểm tra). Kết quả kiểm tra gần
  nhất (không có dòng dữ liệu) nằm trong `sync_state.bq_duplicate_check`.

**Nút "Kiểm tra trùng & thử tổng hợp (không ghi)"** (`POST /api/bigquery/ingest-check`, `sync.d1_dry_run`): chạy các bước
1–6 cho lần D-1 kế tiếp, kiểm tra **ngày hôm qua đã có đủ trong nguồn chưa** (tín hiệu hoàn tất nếu có cấu hình, nếu không
thì phép kiểm số dòng của D-1 fallback) và so sánh *chỉ đọc* với dữ liệu đã lưu (mới / thay đổi / không đổi / bị bỏ);
bước ghi luôn `NOT_RUN`. Kết quả: `READY`, `SOURCE_INCOMPLETE` (hôm qua chưa đủ: D-1 lúc này sẽ chờ / thử lại, không
ghi), `BLOCKED` (dòng trùng) hoặc `FAILED`. Dùng được trước khi bật chế độ sản xuất. Mỗi lần quét khoảng 1,26 GB
(bảng không phân vùng).

**Giới hạn đã biết:**
- Chưa có tín hiệu hoàn tất ngày (`completion_table` trống). Sau giờ fallback, D-1 chỉ kiểm tra số dòng của hôm qua
  ≥ 50 % trung bình 7 ngày trước; bảng nguồn được làm mới toàn bộ vào khoảng trưa ngày D+1 (mục 12), nên một lần D-1
  chạy sớm có thể nạp hôm qua chưa đủ; lần chạy sau (cửa sổ watermark − 3 ngày) sẽ ghi đè bằng số mới.
- Kiểm tra toàn kỳ đọc đến **hôm nay** (dữ liệu dở dang của hôm nay có thể làm số trùng khác số của D-1).
- Một lần D-1 trả về toàn bộ dòng tổng hợp vào bộ nhớ (≈ 1,35 triệu dòng cho 01/01–15/10/2026).

**Kiểm thử thật 16/10/2026 13:23 (bản sao DB cô lập, ADC, chỉ đọc BigQuery):** 01/01–15/10/2026: 8.885.547 dòng nguồn,
**433 nhóm / 878 dòng / 445 dòng dư** trùng hoàn toàn → `BLOCKED`, báo cáo `.xlsx` đúng 878 dòng / 433 nhóm, không ghi
gì. Chỉ để đo (bản sao, chính sách tạm `KEEP`): 1.345.228 dòng ngày × SKU × FC, tổng demand 41.654.787 (gồm cả 445 dòng
trùng), đối soát khớp, 0 dòng bị loại. Ghi thử vào bản sao (giả lập ngày chạy 15/10 10:00 vì lúc 13:30 ngày 16/10 nguồn
**chưa có dòng nào của 15/10**): lần 1 nạp lại toàn kỳ 01/01–14/10 = 1.345.228 dòng, 41.654.787; chạy lại (11/10–14/10)
13.120 dòng không đổi, tổng giữ nguyên, không khóa nào lặp, dữ liệu DEMO không đổi. Dry-run cuối (13:39, BLOCK):
hôm qua `WARNING` (0 dòng; TB 7 ngày 18.817), trùng `BLOCKED`.

**Kiểm thử thật lại 16/10/2026 15:03, sau khi nguồn được sửa (bản sao DB mới, chính sách production `BLOCK`):**
- Nguồn 01/01–15/10/2026: 8.893.414 dòng, tổng demand 41.722.635. Ngày 15/10 có 18.992 dòng (TB 7 ngày trước 18.772),
  nên bước kiểm tra ngày đủ dữ liệu `PASSED`.
- Trùng hoàn toàn: **0 nhóm / 0 dòng** → `READY`.
- Tổng hợp: 1.347.346 dòng ngày × SKU × FC, tổng 41.722.635 = tổng nguồn, 0 dòng bị loại; 7.211 dòng lặp khóa đơn được
  cộng (`SUM_ALL`).
- Ghi thử vào bản sao (kiểm tra toàn kỳ đạt, kích hoạt đạt):
  - lần 1 nạp lại toàn kỳ: 1.347.346 dòng, 41.722.635;
  - chạy lại (12/10–15/10): 13.345 dòng không đổi, tổng giữ nguyên;
  - 0 khóa lặp; 9.661 SKU, 2 FC; dữ liệu DEMO không đổi.

**Trước khi đổi nguồn sang BIGQUERY:** công tắc luồng D-0 không tự tắt khi đổi nguồn. Nếu D-0 đang bật (ví dụ cho DEMO),
sau khi bật chế độ sản xuất nó sẽ chạy D-0 BigQuery theo lịch, mà D-0 BigQuery chưa được kiểm chứng. Hãy tắt D-0 ở trang
**Lịch chạy dữ liệu** trước. Huấn luyện tự động trên BIGQUERY chờ luồng D-1 được bật (`TRAIN_WAITS_FOR_D1`).

**Production từ 16/10/2026 (bản 1.1.9):** ánh xạ gợi ý (15 cột) đã lưu, 6 cổng truy cập đạt, chế độ sản xuất bật, nguồn
`BIGQUERY`.
- Nạp đầu 16:43–16:49: 01/01–15/10, 8.893.414 dòng nguồn → 1.347.346 dòng ngày × SKU × FC, tổng 41.722.635; 0 trùng,
  0 dòng bị loại. Đối soát từng ngày với BigQuery: 288/288 ngày khớp. Chạy lại 12/10–15/10: 13.345 dòng không đổi.
- D-0 BigQuery chưa bật vì SQL D-0 chưa được xác nhận (`SQL_NOT_VALIDATED`). D-1 tắt, nên dữ liệu chỉ cập nhật khi chạy
  D-1 thủ công; huấn luyện 07:00 chờ D-1 (`TRAIN_WAITS_FOR_D1`).
- Huấn luyện đầu trên dữ liệu thật bị quality gate từ chối (WAPE 1,017; bias +0,399; baseline 0,839 / +0,119); phạm vi
  BIGQUERY chưa có model đang dùng.

## 14. Bảng nguồn D-1 / D-0 (1.2.0)

Mỗi luồng đọc đúng **một** bảng, cấu hình bằng full table id `project.dataset.table` trên trang **BigQuery → Bảng nguồn D-1 / D-0**:

| Luồng | Bảng (mặc định) | Lưu ở | Dùng bởi |
|---|---|---|---|
| D-1 (ngày đã đóng) | `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm` | `bigquery.project_id / dataset_id / source_table` (khóa phạm vi dữ liệu, mapping hash) | `D1_SYNC`, kiểm tra toàn kỳ, *Kiểm tra trùng & thử tổng hợp* |
| D-0 (hôm nay) | `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0` | `bigquery.d0_table_id` | `D0_SYNC` khi luồng D-0 ở chế độ **TABLE** |

**Kiểm tra** (`POST /api/bigquery/source-tables/{d1|d0}/check`):
- Chỉ đọc metadata, không chạy query, không tốn phí.
- Bảng phải tồn tại, đọc được bằng tài khoản Windows đang chạy app và đúng location.
- Bảng phải có mọi cột mà luồng đó đọc, với kiểu dữ liệu tương thích:
  - D-1: mọi cột đã ánh xạ, gồm cả trường tham chiếu;
  - D-0: chỉ các trường nội bộ đã ánh xạ.
- Kết quả và thời điểm kiểm tra được lưu (`sync_state.bq_table_check:<luồng>`) và ghi vào nhật ký audit.

**Lưu** (`PUT /api/bigquery/source-tables/{d1|d0}`):
- Chỉ lưu sau khi kiểm tra **đạt** cho đúng mã bảng đó.
- Lỗi (không tìm thấy, thiếu quyền, sai location, thiếu cột) trả về `BQ_TABLE_CHECK_FAILED`; nguồn đang dùng giữ nguyên.
- App không tự tạo, đổi tên hay chuyển sang bảng khác.
- Bảng D-1 **không đổi được khi chế độ sản xuất đang bật** (`BQ_TABLE_CHANGE_NEEDS_PRODUCTION_OFF`). Đổi bảng D-1 là đổi
  phạm vi dữ liệu nên phải kiểm tra toàn kỳ lại.

**D-0 ở chế độ TABLE:**
- Trước 1.2.0, chế độ này đọc chính bảng D-1 với ngày = hôm nay. Bảng D-1 chỉ có ngày D vào khoảng trưa ngày D+1, nên cách
  đọc đó không có dữ liệu.
- Từ 1.2.0, chế độ TABLE đọc bảng D-0, không lọc theo phân vùng của bảng D-1.
- Luồng D-0 chỉ "sẵn sàng" khi bảng D-0 đã kiểm tra đạt (`D0_TABLE_NOT_CHECKED`).
- Chế độ SQL (SQL do người dùng viết) không đổi.
- 1.2.1: kiểm tra và đọc bảng D-0 dùng **ánh xạ D-0 riêng**, không còn dùng ánh xạ D-1; xem mục 15.

**Kiểm tra thật ngày 16/10/2026 23:5x** (chỉ đọc):
- Bảng D-0 có 12 cột: `fc_code, created_date, so_code, order_status, product_id, sku_code, item_code, seller_code,
  sku_system_status, demand_quantity, outbound_quantity, sales_price`. Tại thời điểm kiểm tra có 9.329 dòng, chỉ của ngày
  16/10; 1.809 SKU, 2 FC.
- Bảng D-0 **không có** các cột `open_date`, `total_open_hours`, `total_open_days`, `seller_class`, `refresh_time`. Vì vậy
  kiểm tra D-0 chỉ so các trường nội bộ, không so trường tham chiếu.
- Bảng D-1 được làm mới lúc 14:08 ngày 16/10 nhưng ngày mới nhất vẫn là 15/10. Ngày D có trong nguồn vào khoảng 12:00–14:10
  ngày D+1.

**Lịch D-1 03:00 với giờ làm mới của nguồn:** xem [SCHEDULER.md](SCHEDULER.md), mục *D-1: tín hiệu và giờ dự phòng*.

**`sales_price` (giá) — kiểm tra 16/10/2026:** đây là **đơn giá của dòng đơn**, đã gồm ảnh hưởng deal (theo chủ dự án),
không phải thành tiền. Bằng chứng:
- Trung vị `sales_price` giảm khi số lượng tăng: 105.100 khi SL ≤ 1, 70.100 khi SL 2–5, 41.100 khi SL 6–20.
- Trong cùng SKU × FC × ngày có trung bình 5,6 mức giá, và tương quan giá–số lượng có trung vị −0,05.

Nhóm feature **Giá** dùng đơn giá bình quân theo số lượng (`SUM(giá × SL) / SUM(SL có giá)`); dòng không có giá bị bỏ qua
trong phép tính giá, không coi là 0.

**Quyết định của chủ dự án ngày 17/10/2026: nhóm Giá BẬT cho model phát hành.** Bật công tắc thôi chưa đủ: nguồn chưa có
dữ liệu giá thì lần huấn luyện vẫn bỏ nhóm này ra (ghi `used: false`, lý do `NO_DATA`). Production 1.1.9 ngày 17/10 đang ở
trạng thái đó (công tắc bật, độ phủ giá 0). Các bước để giá thật sự vào model (ứng dụng làm, không sửa tay DB):
1. *Ánh xạ trường* (`POST /api/bigquery/mapping`): `unit_price ← sales_price`. Lưu mapping **tắt chế độ sản xuất** và đổi
   mapping hash; phạm vi dữ liệu giữ nguyên.
2. Kiểm tra toàn kỳ lại (ước tính đọc khoảng 3,5 GB), rồi bật lại chế độ sản xuất.
3. Chạy D-1: mapping hash mới nên D-1 **nạp lại toàn kỳ**. Chỉ chạy khi ngày hôm qua đã đủ trong nguồn (khoảng
   12:00–14:10); trước đó D-1 chờ/thử lại, không ghi gì.
4. Kiểm tra: độ phủ `avg_unit_price` ≥ `feature_min_coverage` (0,5) → registry `DATA_OK`. Sau khi huấn luyện, lần chạy phải
   có `feature_groups.price = {switch_on: true, used: true}` và file model có `price_last`, `price_rel_28`.

Đã làm thử trên **bản sao cô lập** (17/10/2026, code 1.2.0, BigQuery thật, chỉ đọc):
- Nạp lại 01/01–15/10: đọc 8.893.414 dòng; 1.347.346 ngày × SKU × FC, **cả 1.347.346 không đổi số lượng** (tổng
  41.722.635); không có dòng trùng hoàn toàn.
- Độ phủ giá 99,98 %: 239 ngày-chuỗi không có giá (lưu NULL), 83 ngày-chuỗi có giá bình quân = 0, không có giá âm; kiểu
  REAL.
- Tại mốc dự báo (16/10), `price_last` có cho 100 % trong 17.137 chuỗi và đúng bằng giá cuối đã biết.

Kết quả backtest (7 fold, cùng điểm): chỉ nhu cầu WAPE 0,805953 / bias +0,068976; nhu cầu + giá WAPE 0,808117 / bias
+0,071829. Hai feature giá hiện có chưa cải thiện metric tổng. Chi tiết, giới hạn và các thử nghiệm đề xuất ở
`experiments/final_release_20261017/`.

## 15. D-0 có ánh xạ riêng, xác nhận bằng BigQuery thật (1.2.1)

**Vì sao D-0 production báo `SQL_NOT_VALIDATED` ("d0: no D-0 SQL version validated by BigQuery")** — kiểm tra ngày
17/10/2026:
- Luồng D-0 ở chế độ **SQL**. Hai phiên bản SQL của ngày 15/10 chưa từng được gửi BigQuery để xác nhận:
  - v1 là SQL người dùng đưa;
  - v2 là bản đề xuất.
  Vì vậy không có phiên bản nào "đang dùng", và luồng D-0 không sẵn sàng.
- Đến bản 1.2.0, D-0 còn mượn **ánh xạ D-1**:
  - cột đầu ra bắt buộc, khóa mặc định và cột ngày đều lấy theo tên cột D-1;
  - ở chế độ TABLE, bảng D-0 phải có mọi cột nội bộ mà D-1 ánh xạ, kể cả `sales_price`, và cột phân vùng của D-1.
- Ở chế độ SQL, ứng dụng không lọc theo ngày: dòng của ngày khác chỉ gây cảnh báo nhưng **vẫn bị cộng** vào snapshot.

**Từ 1.2.1:**
- **Ánh xạ D-0 riêng** (`bigquery.d0_mapping`, trang *SQL nguồn & đồng bộ → D-0 → Ánh xạ D-0*;
  `GET/PUT /api/bigquery/d0-mapping`).
  - Trường thiết yếu: `sku_id`, `fc_id`, `order_qty`, và ngày của dòng: `order_date` (DATE/DATETIME) hoặc `created_at`
    (TIMESTAMP, đổi sang ngày theo giờ Việt Nam).
  - Trường tùy chọn: `order_id` (thuộc khóa mặc định), `source_updated_at`.
  - Cột khác của SQL/bảng D-0 được bỏ qua. D-0 có thể ít cột hơn, khác tên, khác cấu trúc so với D-1.
  - Lưu ánh xạ D-0 **không** đổi ánh xạ D-1, không đổi mapping hash D-1, không tắt chế độ sản xuất.
  - Giá trị điền sẵn khi nâng cấp lấy theo metadata thật của bảng `demand_planing_lightgbm_D0` ngày 17/10/2026:
    `sku_code`, `fc_code`, `demand_quantity`, `created_date`, `so_code`. Nút *Gợi ý từ schema thật*
    (`POST /api/bigquery/d0-mapping/suggest`) đọc lại metadata bảng hoặc kết quả dry-run của một phiên bản SQL, không lưu gì.
- **Xác nhận một phiên bản SQL D-0** (*Xác nhận với BigQuery*) là một vòng thật với BigQuery:
  1. dry-run kiểm tra cú pháp, quyền, bảng nguồn, loại câu lệnh và chi phí;
  2. đối chiếu schema đầu ra với ánh xạ D-0: cột có mặt, kiểu tương thích, cột khóa có mặt;
  3. **chạy thật** phép tổng hợp của hôm nay. Phép này không ghi gì, giới hạn bởi `maximum_bytes_billed`.

  Kết quả được lưu trong phiên bản đó: thời điểm, sha256 SQL, mã ánh xạ D-0, cột đầu ra, số liệu chạy thử, lỗi nếu có.
  - Chỉ VALID mới được dùng.
  - Lưu SQL không bao giờ tự xác nhận.
  - Đổi SQL thì tạo phiên bản mới chưa xác nhận.
  - Đổi ánh xạ hoặc khóa D-0 thì phiên bản đang dùng chuyển sang `D0_REVALIDATE_REQUIRED`, job bị bỏ qua có lý do.
  - Xác nhận do bản 1.2.0 ghi lại cũng phải làm lại, vì thiếu kiểu cột đầu ra.

  Chế độ TABLE áp dụng cùng quy tắc với metadata bảng D-0.
- **Job D-0** chỉ tính dòng có ngày = hôm nay (giờ Việt Nam, tham số `@day`). Mọi dòng khác đều được đếm theo lý do:
  `OTHER_DAY`, `NULL_DATE`, `NULL_SKU`, `NULL_FC`, `NULL_TARGET`, `NEGATIVE_TARGET`.
  - Trùng khóa và trùng hoàn toàn chỉ tính trên dòng của hôm nay.
  - Snapshot ghi vào `d0_snapshots` / `d0_snapshot_values`, **không** vào `demand_daily`. Huấn luyện và backtest không đọc
    hai bảng này.
  - Kết quả job ghi `forecast_match`: số SKU × FC có/không có dự báo cho hôm nay và tổng demand chưa đối chiếu được. Dòng
    không có dự báo vẫn được giữ trong snapshot.
  - D-0 lỗi không bao giờ chuyển sang đọc bảng D-1.

**Kiểm tra thật ngày 17/10/2026 15:5x–16:13** (code 1.2.1, BigQuery thật chỉ đọc, ghi trên bản sao DB production, DB thật
không đổi):
- **Metadata bảng D-0:** 12 cột, 8.454 dòng, location `asia-southeast1`. Kiểm tra bảng với ánh xạ D-0 **đạt**; 7 cột không
  cần được bỏ qua.
- **v1** (SQL người dùng, 15/10): dry-run **đạt**. Câu lệnh SELECT, đọc `fact_order`, `fact_order_item`,
  `adhoc_pm_master_sku`, ước tính khoảng 831 MB mỗi lần chạy.
- **v2** (đề xuất, 15/10): BigQuery **từ chối**, lỗi `No matching signature for function DATE`. `DATE(a.created_at,
  'Asia/Ho_Chi_Minh')` không dùng được với kiểu của `created_at`.
- **Phiên bản mới** `SELECT * FROM \`lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0\` WHERE created_date
  = CURRENT_DATE('Asia/Ho_Chi_Minh')`: **VALID**.
  - Dry-run khoảng 1 MB, rồi chạy thật cho ngày 17/10: 8.454 dòng, 2.142 SKU × FC, tổng 34.618.
  - 0 dòng lỗi, 0 dòng khác ngày, 0 dòng trùng hoàn toàn.
  - **48 dòng trùng khóa** (`so_code, sku_code, fc_code, created_date`), tức nhiều dòng đơn của cùng SKU trong một đơn.
- **Khóa trùng với chính sách D-0 hiện tại `BLOCK`:** snapshot bị chặn (`BQ_KEY_NOT_UNIQUE`) và không ghi gì. Với D-1, chủ dự
  án đã chọn `SUM_ALL` (cộng các dòng đơn, 16/10/2026). Áp dụng cho D-0 là quyết định nghiệp vụ, chọn ở *Khi khóa bị trùng*.
  Trên bản sao, với `SUM_ALL`: snapshot 2.142 SKU × FC; chạy lại cùng khóa job không ghi thêm.
- **Kiểm thử tự động trên BigQuery thật** (`tests/test_v121_d0_real_bq.py`, bật bằng `DF_REAL_BQ=1`, 5 test):
  - lọc đúng ngày Việt Nam;
  - TIMESTAMP đổi sang ngày VN;
  - đếm các lý do loại dòng;
  - tính trùng khóa và trùng hoàn toàn;
  - bảng D-0 thật đạt với ánh xạ mặc định;
  - phân loại lỗi cú pháp và lỗi bảng không tồn tại.

**Lỗi BigQuery "Not found: Table ... was not found in location X"** nay trả `BQ_NOT_FOUND`: bảng không tồn tại. Trước
1.2.1 lỗi này bị xếp nhầm thành `BQ_LOCATION_MISMATCH`. Dataset không có ở location đã cấu hình vẫn là
`BQ_LOCATION_MISMATCH`.
