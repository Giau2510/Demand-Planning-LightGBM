BỔ SUNG ĐĂNG KÝ – BIẾN THỂ G1 (tham chiếu PREREGISTRATION.md của G0/G2, cùng nền, cùng cách chấm, cùng cách so sánh)
G1 = V1 (G0) + 10 biến từ is_deal và is_voucher của bảng demand_planing_lightgbm, chỉ tính từ đơn có created_date < D, theo SKU x FC:
deal_share_1, deal_share_7, deal_share_28 = tổng demand_quantity của dòng is_deal = true / tổng demand_quantity, trong 1, 7, 28 ngày gần nhất (không có đơn: 0);
deal_days_7 = số ngày trong 7 ngày gần nhất có ít nhất một dòng is_deal = true;
days_since_deal = số ngày từ ngày gần nhất có dòng is_deal = true (181 nếu không có trong 180 ngày);
voucher_share_1, voucher_share_7, voucher_share_28, voucher_days_7, days_since_voucher: tương tự với is_voucher.
So với G0 của lần chạy G0/G2. G1 tốt hơn G0 khi chỉ số chính (tổng Qty lệch / tổng demand thực) thấp hơn ở CẢ ngày thứ 1 VÀ tổng 7 ngày.
GIỚI HẠN: biến deal/voucher chỉ biết đến hết ngày D-1, không biết đợt deal sắp bắt đầu; không dùng lịch deal.
