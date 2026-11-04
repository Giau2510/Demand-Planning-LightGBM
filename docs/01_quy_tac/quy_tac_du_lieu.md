# Quy tắc dữ liệu bắt buộc

Tách ngày 03/11/2026 từ mục "Quy tắc dữ liệu bắt buộc" của `CLAUDE.md` (worktree `D:\Buymed\Lightgbm AI`) theo bảng 1.3.
`CLAUDE.md` import file này; các quy tắc an toàn dữ liệu chung ở `AGENTS.md` mục 4.

Owner rule 2026-10-31:

* QUY TẮC DỮ LIỆU BẮT BUỘC: Dữ liệu nguồn demand_planing_lightgbm là dữ liệu mức dòng SO, có customer_id (client_id),
  mã đơn, ngày đặt và số lượng từng SKU. Mọi phân tích và mô hình về đột biến, ôm hàng, chu kỳ mua phải dùng thông tin
  theo từng khách (customer_id) và từng đơn. Không được kết luận 'không biết khách nào mua' hay 'thiếu thông tin khách
  hàng'.
* Bổ sung 2026-10-31: dữ liệu mức dòng SO gồm customer_id, mã đơn, ngày đặt, sku_code, fc_code, số lượng; customer_id
  giống nhau là cùng một khách. Mọi đánh dấu (đột biến, ôm hàng, chu kỳ) làm theo TỪNG KHÁCH và TỪNG DÒNG ĐƠN.
