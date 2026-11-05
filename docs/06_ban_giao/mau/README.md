# File Excel mẫu (dữ liệu giả) – bản 1.4.3

Hai file có **đúng cấu trúc** của file dự báo hằng ngày production `du_bao_YYYYMMDD.xlsx` (3 sheet `DU_BAO`, `TOM_TAT`,
`CONFIG`; cùng tên cột, thứ tự cột, kiểu ô, các khoá của `TOM_TAT`) nhưng **mọi giá trị nhận diện và mọi con số đều là
giả**. Hai file được ghi bằng chính code 1.4.3 (`export._rows` → `export._summary_rows` → `export._write_book`) với dữ
liệu giả, không đọc database: số `forecast_used` và `fallback_reason` là kết quả thật của **quy tắc cố định 05/11/2026**
(`01_tai_lieu\03_logic_du_bao.md` mục 10, `01_tai_lieu\09_file_xuat.md` mục 3.1). Mã lần học trong `model_version` là mã
thật của 3 lần học tuần 03/11 (khớp `05_mo_hinh\`), không phải dữ liệu kinh doanh.

| File | Ngày | Tình huống |
|---|---|---|
| `du_bao_MAU_20261105.xlsx` | ngày bình thường | có lần chạy SEL2 của ngày D (05/11) |
| `du_bao_MAU_NGAY_LOI_20261105.xlsx` | ngày lỗi | không có lần chạy của D; lần chạy tham chiếu = lần chạy thành công 04/11 (`is_stale = 1`, cờ file `STALE`) |

6 SKU × FC giả (`MEDX.MAU-01..06`, `MEDX_E.MAU-02`), mỗi SKU × FC 7 dòng (horizon 1..7):

| SKU giả | Cấu hình | Ngày bình thường | Ngày lỗi |
|---|---|---|---|
| MEDX.MAU-01 × FC-A | `LIGHTGBM`, trong phạm vi | `forecast_used` = `lightgbm_forecast` (5, **0**, 3, 7, **0**, 1, 3): số 0 giữ nguyên, không thay bằng Avg 4,3 | h1..h6 = số lần chạy 04/11 (`DUNG_SO_LAN_CHAY_TRUOC`, cờ `LAN_CHAY_TRUOC:2026-11-04`); h7 (= horizon 8 của lần chạy 04/11) → Avg 4,3 làm tròn lên = 5 (`STALE`) |
| MEDX_E.MAU-02 × FC-B | `LIGHTGBM`, **ngoài phạm vi**, tiền tố không phải MEDX | **0** (`NGOAI_PHAM_VI_GAN_0`), dù Avg = 29,76 | **0** (ngoài phạm vi lần chạy tham chiếu) |
| MEDX.MAU-03 × FC-A | `LIGHTGBM`, trong phạm vi, lần chạy hôm nay thiếu h6, h7 | h6 = số lần chạy 04/11 (`DUNG_SO_LAN_CHAY_TRUOC`); h7: không lần chạy nào có → Avg 1,4 → **2** (`KHONG_CO_SO`) | h1..h6 số lần chạy 04/11; h7 → 2 (`STALE`) |
| BML_E.MAU-04 × FC-B | không cấu hình = `AVG_DEMAND` (mã mới) | Avg 0,15 < 0,2 → **0** (cột `avg_demand` vẫn 0.15; số LightGBM hiện để đối chiếu) | 0 |
| MEDX.MAU-05.B × FC-A | `AVG_DEMAND`, không có Avg (`AVG_AVG_DEMAND_NULL`) | số LightGBM (`KHONG_CO_AVG_DUNG_LIGHTGBM`) | số LightGBM của lần chạy 04/11 (cờ `LAN_CHAY_TRUOC`); h7 không có số nào → **0** (`KHONG_CO_SO_NAO`) |
| MAU06KHONGCHAM × FC-B | `AVG_DEMAND`, không có Avg, ngoài phạm vi | không có số nào → **0** (`KHONG_CO_SO_NAO`) | 0 (`KHONG_CO_SO_NAO`) |

Mọi ô `forecast_used` là **số nguyên ≥ 0, không trống**. Cột `seller_code` / `product_code` (ngay sau `ten_san_pham`, cả sheet `CONFIG`): `sku_code` tách tại dấu chấm **đầu tiên** – `MEDX.MAU-01` → `MEDX` / `MAU-01`; `MEDX.MAU-05.B` (nhiều dấu chấm) → `MEDX` / `MAU-05.B`; `MAU06KHONGCHAM` (không có dấu chấm) → `seller_code` trống, `product_code` = nguyên mã. Sheet `TOM_TAT` có số dòng theo từng `fallback_reason`
(`rows_fallback_reason:<lý do>`) và dòng `previous_runs`. File thật ngày 04/11/2026 có 410.137 dòng (58.591 SKU × FC ×
7 ngày), khoảng 23 MB. Đặc tả từng cột: `01_tai_lieu\09_file_xuat.md`.

Hai file `.xlsx` **không nằm trong Git** (quy định của repo: `.gitignore` loại `*.xlsx` – file dữ liệu kinh doanh); bản
có sẵn nằm trong bộ tài liệu bàn giao nháp. Tạo lại (sau khi đổi code): gọi `app.ml.sel2.export._rows` với dữ liệu giả
rồi `_summary_rows` và `_write_book` (không cần database).

`03_ma_nguon\docs\mau\mau_cau_hinh_nguon_du_bao.xlsx` là file mẫu để tải lên cấu hình nguồn dự báo (không phải file
xuất).
