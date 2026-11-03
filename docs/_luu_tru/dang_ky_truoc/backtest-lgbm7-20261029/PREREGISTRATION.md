MỤC ĐÍCH: đo độ chính xác của LightGBM thuần khi dự báo 7 ngày, so với demand thực của đúng từng ngày; kiểm tra tác dụng của biến mã SKU.
NỀN: bản sao DB vòng 1; lô huấn luyện 7 ngày bắt đầu 01/06/2026; mỗi ngày D từ 01/06 đến 22/10/2026 dự báo 7 ngày D..D+6 bằng dữ liệu đến D-1; seed 7; siêu tham số production; trọng số mẫu 3.0 cho horizon <= 7 (cấu hình V1).
BIẾN THỂ:
G0 = V1 (36 biến như production).
G2 = V1 bỏ biến sku_code (35 biến).
(G1 = V1 + biến deal/voucher sẽ được đăng ký và chạy ở lần sau, so với G0 của lần này, cùng cách chấm dưới đây.)
CHẤM ĐIỂM (Claude chấm): dự báo = ROUNDUP(giá trị LightGBM, 0); chỉ ngày total_open_hours > 0; so với demand thực của đúng ngày đó, không bù giữa các ngày; lệch = dự báo − thực. Đúng: |lệch| <= 3 sp (nhóm A, B) hoặc <= 1 sp (nhóm C), hoặc |lệch| / thực <= 20%. Ít: 20% < |lệch| / thực <= 50%. Nhiều: > 50% (kể cả thực = 0 và vượt ngưỡng sp). Thiếu khi lệch < 0, dư khi lệch > 0. Nhóm (dữ liệu 01/06-31/08, ngày mở bán): A = trung bình > 20 sp/ngày và ngày không có đơn <= 20%; C = trung bình <= 5 sp/ngày và ngày không có đơn > 20%; B = còn lại. Báo cáo theo tháng, theo nhóm, theo ngày thứ 1-7 của dự báo: Qty lệch từng loại (Đúng, Thiếu ít, Thiếu nhiều, Dư ít, Dư nhiều) và % so với tổng demand thực.
SO SÁNH BIẾN THỂ: chỉ số chính = tổng Qty lệch mọi loại / tổng demand thực, ở ngày thứ 1 và tổng 7 ngày; chỉ số phụ = Qty (Thiếu nhiều + Dư nhiều) / tổng demand. Biến thể được coi là tốt hơn G0 khi chỉ số chính thấp hơn ở CẢ ngày thứ 1 VÀ tổng 7 ngày.
GIỚI HẠN: dữ liệu lịch sử là bản đã ổn định.
