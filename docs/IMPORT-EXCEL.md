# Import dữ liệu lịch sử bằng Excel

Chỉ chấp nhận **`.xlsx`**. Không hỗ trợ CSV, `.xls`, `.xlsm` (macro). File không bao giờ được chạy macro hay công thức
(chỉ đọc giá trị đã lưu).

## File mẫu

Trên trang **Import dữ liệu lịch sử** (hoặc thư mục `templates\` trong gói cài):

| File | Mục đích |
|---|---|
| `mau-nhap-du-lieu-lich-su.xlsx` | File mẫu: sheet `Instructions` (hướng dẫn), `Fields` (mô tả trường), `Data` (tiêu đề + 21 dòng ví dụ) |
| `du-lieu-mau-hop-le.xlsx` | 6 tháng dữ liệu tổng hợp hợp lệ — để thử trọn quy trình import → huấn luyện → dự báo |
| `du-lieu-mau-co-loi.xlsx` | File có lỗi cố ý — để thử kiểm định và báo cáo lỗi |

## Trường dữ liệu (schema tạm thời)

| Trường | Bắt buộc | Định dạng |
|---|---|---|
| `created_at` | Có (hoặc `order_date`) | `YYYY-MM-DD HH:MM[:SS]`, `DD/MM/YYYY HH:MM`, hoặc ô Date của Excel. Không ghi múi giờ = giờ Việt Nam. Có `Z`/`+07:00` thì quy đổi. |
| `order_date` | Không | `YYYY-MM-DD`. Để trống → lấy ngày của `created_at` theo giờ Việt Nam. |
| `sku_id` | Có | Văn bản (giữ số 0 ở đầu) |
| `fc_id` | Có | Văn bản |
| `order_qty` | Có | Số ≥ 0. **Số lượng khách đặt lúc tạo đơn — không trừ hủy.** |
| `order_id` | Khuyến nghị | Dùng phát hiện trùng và xác định grain đơn × SKU × FC |
| `unit_price`, `discount_amount`, `voucher_amount` | Không | Số ≥ 0, dấu chấm thập phân (`1,234.5` cũng được) |
| `promotion_flag`, `voucher_flag` | Không | `1/0`, `TRUE/FALSE`, `Y/N`, `Có/Không` |
| `promotion_id`, `batch_id` | Không | Văn bản |
| `source_updated_at` | Không | Như `created_at`; dùng phát hiện dữ liệu đến muộn |

Giá/giảm giá/khuyến mãi phải là thông tin **đã biết tại thời điểm đặt hàng**.

Tên cột khác? Không sao: ở bước 2 bạn chọn cột của mình cho từng trường. Hệ thống chỉ tự gợi ý khi tên trùng khớp
(không phân biệt hoa/thường, dấu cách) hoặc nằm trong danh sách bí danh cấu hình; **không đoán theo tên gần giống**.

## Các bước

1. **Chọn file `.xlsx`** → *Tải lên & đọc cấu trúc*. Lỗi ngay nếu: không phải `.xlsx` (`NOT_XLSX`), file hỏng
   (`CORRUPT_FILE`), có macro (`MACRO_NOT_ALLOWED`), quá dung lượng (`FILE_TOO_LARGE`, mặc định 50 MB).
2. **Chọn sheet** (tự chọn sheet tên `Data`, hoặc sheet duy nhất; nếu mơ hồ bạn phải chọn) và **ánh xạ cột**.
3. **Kiểm tra dữ liệu** → hệ thống tạo lô ở trạng thái *Chờ xác nhận* (chưa dùng cho bất kỳ tính toán nào) và hiển thị:
   tổng dòng, dòng hợp lệ, dòng lỗi (bị loại), dòng trùng (tính 1 lần), ngày thiếu, trường có vấn đề,
   bảng lỗi/cảnh báo theo mã, xem trước 50 dòng hợp lệ, và nút **Tải báo cáo lỗi (Excel)**.
4. **Xác nhận lưu** (nếu có dòng lỗi phải tick xác nhận rằng các dòng lỗi sẽ bị loại) hoặc **Hủy import**
   (không ghi gì). Kết quả trả về **mã lô** (`IMP-…`). Lưu diễn ra trong một transaction: lỗi giữa chừng không để lại dữ liệu dở dang.

### Mức độ kiểm tra

| Mức | Ý nghĩa | Ví dụ |
|---|---|---|
| Lỗi | Dòng bị loại, có lý do | thiếu SKU/FC, ngày không hợp lệ, số lượng âm/không phải số/trống, ngày tương lai, ngày trước *min date* cấu hình, xung đột grain |
| Trùng | Trùng hoàn toàn dòng trước → chỉ tính 1 lần | import cùng một dòng 2 lần trong file |
| Cảnh báo | Giữ dòng; ô có thể bị để trống (luôn được ghi rõ) | giá không phải số, cờ không hợp lệ, giảm giá > giá trị dòng, giá bất thường |
| Thông tin | Hợp lệ nhưng đặc biệt | số lượng = 0, dữ liệu đến muộn |

**Grain**: một dòng = đơn × SKU × FC. Nếu cùng `order_id × sku_id × fc_id` xuất hiện nhiều lần với giá trị khác nhau:
chính sách mặc định `ERROR` loại các dòng đó; có thể đổi sang `SUM` (cộng dồn — khi đó là các dòng chi tiết hợp lệ)
trong *Cấu hình dự báo → Import Excel*.

## Lô import độc lập — thay thế, xóa

- Mỗi lần import tạo **một lô mới, độc lập**. Hệ thống **không gộp** các lô; import lại cùng file tạo một lô khác,
  không cộng trùng vào lô cũ.
- **Bộ dữ liệu hoạt động** của nguồn `MANUAL_IMPORT` là **một lô** do bạn chọn (*Lịch sử lô import → Dùng làm bộ dữ liệu*).
  Huấn luyện chỉ dùng đúng lô đó.
- **Thay thế lô**: *Lịch sử lô import → Thay thế lô này* (hoặc chọn *Thay thế toàn bộ lô* khi import). Sau khi kiểm tra
  và xác nhận (có hộp thoại xác nhận riêng), dữ liệu lô cũ được thay bằng dữ liệu mới trong một transaction; lô cũ
  chuyển trạng thái *Đã bị thay thế* (vẫn hiện trong lịch sử, có liên kết sang lô mới). Nếu file mới không hợp lệ,
  lô cũ **giữ nguyên**. Các lô khác, DEMO và BigQuery **không bị ảnh hưởng**.
- **Xóa lô**: phải gõ đúng mã lô. Xóa dữ liệu dòng đơn hàng của lô; thông tin lô, nhật ký kiểm toán và **forecast đã
  publish vẫn được giữ** (forecast lưu bất biến, có thể truy xuất theo run ID và model version).
- Thay/xóa một lô **không thay đổi** nội dung các forecast run đã lưu trước đó.

## Sau khi import

Đổi nguồn sang `MANUAL_IMPORT` → trang **Chất lượng dữ liệu** để xem kết quả kiểm tra tổng thể → **Tổng quan →
Huấn luyện & dự báo ngay**. Cần tối thiểu 56 ngày lịch sử (cấu hình được); nếu ngắn hơn, hệ thống báo
`DATA_NOT_TRAINABLE` thay vì ép mô hình.
