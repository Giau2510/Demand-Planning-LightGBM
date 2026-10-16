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

**Trường tham chiếu** chỉ dùng để kiểm tra, đối chiếu và cho feature tương lai. Chúng không phải target và không phải đầu vào mô hình:

| Trường tham chiếu | Cột gợi ý | Dùng để |
|---|---|---|
| `product_id`, `item_code` | `product_id`, `item_code` | Định danh, giữ nguyên ý nghĩa |
| `outbound_qty` | `outbound_quantity` | Đối chiếu Σ xuất với Σ nhu cầu |
| `order_status` | `order_status` | Thống kê phân bố. **Không** dùng để lọc thêm dòng. |
| `sales_price`, `price_after_discount` | cùng tên | Độ đầy đủ; feature giá tương lai |
| `seller_code`, `sku_status` | `seller_code`, `sku_system_status` | Độ đầy đủ; feature tương lai |
| `open_date`, `open_hours`, `open_days` | `open_date`, `total_open_hours`, `total_open_days` | Độ đầy đủ; feature khả dụng tương lai |

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
- **Đồng bộ không kích hoạt huấn luyện.** Huấn luyện có lịch riêng; với BIGQUERY còn chờ D-1 thành công và kiểm tra dữ liệu đạt.
- **Dữ liệu D0** nằm trong bảng snapshot riêng, không bao giờ được dùng làm dữ liệu huấn luyện lịch sử.
- **Múi giờ lịch chạy:** `Asia/Ho_Chi_Minh` (múi giờ duy nhất ứng dụng hỗ trợ), hiển thị trên trang.

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
