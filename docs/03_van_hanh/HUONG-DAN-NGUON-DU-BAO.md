# Hướng dẫn: nguồn dự báo theo SKU × FC và file Excel dự báo hằng ngày (1.4.0)

Dành cho người dùng nghiệp vụ (mua hàng / kế hoạch). Chi tiết kỹ thuật: [SCHEDULER.md](SCHEDULER.md) mục SEL2,
[MO-HINH-VA-CHI-SO.md](../04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md) mục SEL2, [DATA-DICTIONARY.md](../02_kien_truc_du_lieu/DATA-DICTIONARY.md) (bảng của
migration 0012).

## 1. Hai nguồn số dự báo

| Nguồn | Ý nghĩa |
|---|---|
| `AVG_DEMAND` | **Mặc định** cho mọi SKU × FC chưa cấu hình. Giá trị `avg_demand` của ngày D đọc từ BigQuery (chỉ đọc) `lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku` (bảng lịch sử `..._historical`). |
| `LIGHTGBM` | Số dự báo của luồng SEL2: mỗi ngày chọn theo từng SKU × FC trung bình 2 mô hình ứng viên tốt nhất (xem mục 5). |

Một SKU × FC **không có trong bảng cấu hình = AVG_DEMAND**. Mỗi thay đổi cần xác nhận và được ghi vào lịch sử (không
sửa, không xóa được). Khi luồng SEL2 đang tắt (công tắc khẩn cấp, mục 6) màn hình chỉ xem, không ghi được.

Lưu ý: khi một SKU × FC có nhiều dòng seller trong bảng AVG_DEMAND, quy tắc gộp (`sel2_pipeline.avg_seller_rule`)
**đang chờ chủ sở hữu duyệt** (mặc định `PENDING`): lúc đó ô AVG_DEMAND để trống (không bao giờ ghi 0). Một dòng seller
duy nhất thì dùng giá trị của dòng đó.

## 2. Đổi nguồn trên giao diện (màn hình "Nguồn dự báo", `/forecast-source`)

1. **Một SKU × FC:** nhập đúng mã SKU và mã FC → "Xem nguồn hiện tại" → chọn nguồn mới, ghi chú nếu cần → "Đổi nguồn"
   → xác nhận. Nguồn và ghi chú giống hiện tại thì không ghi gì.
2. **Danh sách:** bảng "SKU × FC đã cấu hình", tìm theo SKU / FC; "Tải cấu hình hiện tại" tải file `.xlsx` của bảng.
3. **Lịch sử:** mọi lần đổi (nguồn cũ → mới, ghi chú, người đổi, lúc đổi, kênh UI / UPLOAD / API, mã lô tải lên); tải
   được file `.xlsx`.

Thay đổi có hiệu lực từ **lần chạy sau** (số dự báo và file Excel của SKU × FC đó); file Excel đã ghi không bị sửa.

## 3. Đổi nhiều SKU × FC bằng file Excel

1. Lấy file mẫu [mau_cau_hinh_nguon_du_bao.xlsx](../mau/mau_cau_hinh_nguon_du_bao.xlsx) hoặc "Tải cấu hình hiện tại".
2. Cột bắt buộc `sku_code`, `fc_code`, `forecast_source` (`AVG_DEMAND` hoặc `LIGHTGBM`); cột `ghi_chu` tùy chọn. Dòng
   tiêu đề được tìm trong 10 dòng đầu (file tải về có một dòng ghi chú phía trên). **Xóa 2 dòng ví dụ** của file mẫu
   trước khi tải lên.
3. "Tải file Excel cấu hình" → **Xem trước**: không ghi gì; hiện số dòng, số dòng sẽ đổi / không đổi / lỗi (bản xem trước
   hết hạn sau 30 phút).
4. Chỉ áp dụng được khi **không còn dòng lỗi**. Áp dụng = một giao dịch, một mã lô (`batch_id`), kênh lịch sử `UPLOAD`.

| Lỗi dòng | Nghĩa |
|---|---|
| `MISSING_SKU_CODE` / `MISSING_FC_CODE` | thiếu mã SKU / FC |
| `MISSING_SOURCE` / `UNKNOWN_SOURCE` | thiếu nguồn / nguồn không phải AVG_DEMAND, LIGHTGBM |
| `DUPLICATE_IN_FILE` | một SKU × FC xuất hiện nhiều lần trong file (mọi lần đều báo lỗi) |

Giới hạn: file ≤ 20 MB, ≤ 200 000 dòng. Có cột `ghi_chu` thì ghi chú trong file thay ghi chú hiện tại (ô trống = xóa ghi
chú); không có cột thì giữ ghi chú cũ.

## 4. File Excel dự báo hằng ngày

Vị trí: `<thư mục dữ liệu>\exports\du_bao\YYYYMMDD\` (`sel2_pipeline.export_subdir`).

* `du_bao_YYYYMMDD_vN.xlsx`: mỗi lần xuất là **một phiên bản mới** (v1, v2, ...), không bao giờ ghi đè hay sửa.
* `du_bao_YYYYMMDD.xlsx`: bản sao của phiên bản mới nhất (mở file này khi cần số mới nhất).
* `du_bao_YYYYMMDD_TAM.xlsx` (chỉ lần khởi động đầu sau khi cài 1.4.0, `sel2-bootstrap`, mặc định 28 ngày quá
  khứ): **bản tạm** ghi ngay khi 3 mô hình LightGBM của tuần hôm nay huấn luyện xong, số LightGBM = `V33_L112` cho mọi
  SKU × FC (cùng quy tắc làm tròn: 0 khi dưới 0,2, còn lại làm tròn lên; SKU × FC cấu hình AVG_DEMAND vẫn dùng
  AVG_DEMAND); `model_used = V33_L112`, `TOM_TAT` ghi "bản tạm – chưa chọn mô hình theo SKU" và trigger
  `BOOTSTRAP_TEMP`. Không phải phiên bản vN, không phải file mới nhất, không công bố, không ghi vào danh sách phiên bản
  (`export_runs`; chỉ ghi nhật ký `SEL2_EXPORT_TEMP_WRITTEN`). Chạy lại bootstrap cùng ngày thì ghi đè file tạm (ngày đã
  công bố thì bỏ qua). Khi file chính thức `du_bao_YYYYMMDD_v1.xlsx` có thì dùng file chính thức; file tạm không bị xoá
  tự động. Lỗi ghi file tạm không làm hỏng bootstrap.
* Tải trong app: `GET /api/sel2/export/{ngày}` (danh sách phiên bản: `/api/sel2/export/{ngày}/runs`). Xuất lại bằng tay:
  `POST /api/sel2/export` hoặc `python -m app.cli sel2-export --date D --yes`.
* Nút xuất trên trang Dự báo hằng ngày: hỏi xác nhận, rồi chạy **job nền** `FORECAST_EXPORT` (mode `MANUAL`) và hiện
  tiến trình; nếu đã có một lần xuất đang chờ / đang chạy thì app theo dõi job đó, không tạo job thứ hai.
* `LATEST_COPY_LOCKED`: file `du_bao_YYYYMMDD.xlsx` đang mở (vd trong Excel) nên không thay được; phiên bản
  `du_bao_YYYYMMDD_vN.xlsx` vẫn được ghi và ghi nhận, file mới nhất được cập nhật ở lần xuất sau (đóng Excel trước).
* `AVG_NO_READ`: ngày D chưa có lần đọc AVG_DEMAND hoàn tất (cờ của cả file, trong `TOM_TAT` và danh sách phiên bản).
* Đọc AVG_DEMAND bằng tay: `sel2-avg-read --date` chỉ nhận **hôm nay** (`AVG_CURRENT_ONLY_TODAY`); ngày đã qua dùng
  `--hist-from D1 --hist-to D2` (bảng lịch sử).

Sheet `DU_BAO`: một dòng mỗi SKU × FC × ngày đích D .. D+6 (hợp của SKU × FC trong lần chạy SEL2 và SKU × FC có dòng
AVG_DEMAND của ngày D).

| Cột | Nghĩa |
|---|---|
| `sku_code`, `ten_san_pham`, `fc_code`, `nhom` | SKU, tên, FC, nhóm A / B / C |
| `forecast_date`, `target_date`, `horizon` | ngày dự báo D, ngày đích, 1 = D |
| `lightgbm_forecast` | số nguyên đã công bố của SEL2 (0 khi dưới 0,2, còn lại làm tròn lên) |
| `avg_demand` | giá trị AVG_DEMAND của ngày D (trống khi không có) |
| `forecast_source` | nguồn đã cấu hình của SKU × FC |
| `forecast_used` | **số dùng**: LightGBM khi cấu hình LIGHTGBM và lần chạy có số của ngày đó (kể cả 0). LIGHTGBM nhưng SKU × FC **ngoài phạm vi lần chạy** (quyết định chủ dự án 04/11/2026): mã tiền tố `MEDX` -> **0**; mã khác (`MEDX_E`, `BML_INT`, `TAYAU_E`, `BML_E`…) -> AVG_DEMAND (tạm thời). Còn lại AVG_DEMAND (trống khi không có, không bao giờ ghi 0) |
| `fallback_reason` | chỉ với LIGHTGBM khi không có số LightGBM: `NGOAI_PHAM_VI_GAN_0` (ngoài phạm vi, mã MEDX, ghi 0), `KHONG_CO_DU_LIEU_DEMAND` (ngoài phạm vi, mã không phải MEDX, dùng AVG_DEMAND), `STALE` (lần chạy cũ không có số của ngày đó), `KHONG_CO_SO` (trong phạm vi nhưng không có số, hoặc chưa có lần chạy SEL2 nào: dùng AVG_DEMAND, không ghi 0). `NGOAI_PHAM_VI` chỉ còn trong file xuất trước 04/11/2026 |
| `model_used`, `raw_value` | mô hình SEL2 đã dùng (vd `MOC+DOW4`, `FALLBACK:V33_L112`) và giá trị thô |
| `model_version`, `data_cutoff_date` | ba lần huấn luyện dùng; ngày dữ liệu cuối (D-1) |
| `is_stale`, `flags` | 1 = file dùng số cũ (mục 6); cờ (`MODEL_PREV_WEEK`, `OPEN_HOURS_LAG`, ...) |

Sheet `TOM_TAT`: số đếm của file (phạm vi, lý do dùng AVG_DEMAND, cờ, mô hình, lần đọc AVG_DEMAND). Sheet `CONFIG`: các
SKU × FC cấu hình LIGHTGBM lúc xuất.

## 5. SEL2 tóm tắt

* 6 ứng viên mỗi SKU × FC: `MOC`, `V33_L112`, `V36_two_stage@0.6` (LightGBM, huấn luyện lại mỗi thứ 2), `TSB`, `DOW4`,
  `AVG7`.
* Phạm vi ngày D: SKU × FC có ≥ 1 ngày bán và ≥ 1 ngày có giờ mở bán trong D-90 .. D-1.
* Chọn: trung bình 2 ứng viên có tỷ lệ "Đúng" cao nhất trên các ngày đích D-28 .. D-1 (bằng nhau → ứng viên thiếu hàng
  ít hơn); ít hơn 14 ngày đánh giá → dùng `V33_L112`.

## 6. Lịch hằng ngày và khi có sự cố

* Sau khi D-1 thành công: chạy SEL2 của hôm nay → công bố → ghi file Excel.
* **Thứ 2:** huấn luyện 3 mô hình LightGBM trước; tới **06:20** chưa xong thì chạy bằng mô hình tuần trước (cờ
  `MODEL_PREV_WEEK`), huấn luyện xong sẽ chạy lại một lần và ghi phiên bản Excel mới.
* **06:30:** chưa có lần chạy SEL2 nào của hôm nay và chưa có file → ghi một file **cũ** (`is_stale = 1`): số của lần chạy
  SEL2 gần nhất cho các ngày còn lại, không có thì toàn bộ AVG_DEMAND.
* Máy tắt / huấn luyện lỗi vào thứ 2: một lần huấn luyện bù trong tuần (cùng mốc thứ 2) sau khi file của ngày đã có hoặc
  từ 06:30.
* **Công tắc khẩn cấp:** `sel2_pipeline.enabled = False` (Cài đặt) đưa app về đúng cách chạy 1.3.1; không ghi gì vào các
  bảng SEL2.
