MỤC ĐÍCH: xác nhận, có đăng ký trước, phương án dự báo ngày D tốt nhất cho từng nhóm SKU (trả lời có/không); kiểm chứng chu kỳ đặt lại của khách có giúp dự báo không.

NỀN: bản sao DB vòng 1 (SHA C7A663BE…F073); lô 7 ngày từ 01/06/2026, ngày dự báo cuối 22/10/2026; seed 7; 12 mốc; 300 vòng; siêu tham số production; trọng số mẫu 3.0 cho horizon <= 7 (như V1); h = 1 chính, h = 2 phụ.

AVG VẬN HÀNH: Avg của ngày D = bản ghi fact_avg_demand_sku_historical có DATE(transformed_at, 'Asia/Ho_Chi_Minh') = D theo SKU x FC (tính 02:00 ngày D bằng dữ liệu đến D-1); không có bản ghi ngày D thì dùng bản ghi gần nhất trước D. Điều kiện dùng: hệ số phản ứng với demand ngày D không có ý nghĩa và hệ số D-1 dương có ý nghĩa; nếu có CSV thì trùng avg_demand_history >= 99% số dòng cùng khóa. Không đạt: mọi biến thể chạy KHÔNG có biến Avg và ghi rõ.

BIẾN MỚI (F1-F4): avg_d (Avg vận hành của mốc dự báo, dùng cho mọi horizon từ mốc), avg_ratio = avg_d / roll_mean_14, avg_age; ratio_7_28 = roll_mean_7 / roll_mean_28; ratio_1_7 = lag_1 / roll_mean_7; ewm_3, ewm_7. Mốc trước 26/02/2026: biến Avg để NaN.

BIẾN THEO KHÁCH (F3, F4): từ dòng đơn đã băm có created_date < mốc dự báo, cửa sổ 180 ngày, theo SKU x FC; một "lần đặt" = tổng lượng của một khách trong một ngày. n_orders_7, n_orders_28, n_customers_7, n_customers_28, avg_order_qty_28, max_order_qty_28, top_customer_share_28, days_since_big_order (lần đặt >= phân vị 90 cỡ lần đặt của SKU x FC trong 180 ngày; 181 nếu không có). Khách đều = >= 3 lần đặt trong 180 ngày và hệ số biến thiên khoảng cách giữa các lần đặt <= 0.5. Với khách đều: r = (số ngày từ lần đặt cuối đến mốc) / (trung vị khoảng cách). n_regular; n_due (r trong [0.8, 1.5]); n_overdue (r trong (1.5, 3]); due_qty, overdue_qty (tổng trung vị cỡ lần đặt của nhóm tương ứng); big_due_qty (due_qty của khách thuộc 10% lớn nhất theo lượng 180 ngày); expected_rate (tổng trung vị cỡ lần đặt / trung vị khoảng cách); min_days_to_due (nhỏ nhất của trung vị khoảng cách - số ngày từ lần đặt cuối; 999 nếu không có); regular_share_90 (tỷ trọng lượng 90 ngày từ khách đều).

CHẨN ĐOÁN KHÁCH HÀNG (chỉ dữ liệu 01/06-31/08, nhóm A): ngày đột biến = thực bán > 2 lần trung vị thực bán ngày mở bán của SKU x FC trong 01/06-31/08. Báo cáo: % lượng hàng nhóm A từ khách đều; % lượng hàng ngày đột biến từ khách đều và từ khách đến hạn (r trong [0.8, 1.5] tính bằng dữ liệu trước ngày đó); cùng chỉ số ở ngày thường.

BIẾN THỂ: R0 = V1 vòng 1 (dùng lại). F1 = V1 + biến mới, Tweedie 1.2. F2 = F1 với objective = l1. F3 = F1 + biến theo khách. F4 = F2 + biến theo khách.
KẾT HỢP (Claude tính): R0, F1-F4 kết hợp với avg_demand_history: w*mô hình + (1-w)*Avg, w thuộc {0.25, 0.5, 0.75}.

CHẤM: như vòng 1 (ngày total_open_hours > 0, làm tròn nửa lên, lệch = tổng |dự báo - thực| / tổng thực, thừa/thiếu = tổng dự báo / tổng thực - 1, nhóm A/B/C theo dữ liệu 01/06-31/08). Chỉ số chính: lệch theo ngày. Phụ: thừa/thiếu, lệch theo tuần.
CHỌN (01/06-31/08, h = 1, từng nhóm): trong {Avg, R0, F1-F4, các bản kết hợp}, phương án có lệch theo ngày thấp nhất trong số phương án có |thừa/thiếu| <= |thừa/thiếu của Avg|. Nếu F3, F4 chưa xong khi chấm lần đầu, chấm lần đầu trên các phương án đã có và chấm lại khi đủ.
XÁC NHẬN (01/09-22/10, h = 1, từng nhóm): phương án được chọn có lệch theo ngày cao hơn Avg và khoảng tin cậy 95% (bootstrap theo SKU x FC) không chứa 0 -> GIỮ Avg; ngược lại -> CHUYỂN.

GIỚI HẠN CÔNG BỐ TRƯỚC: (1) ý tưởng biến Avg, mục tiêu L1, biến theo khách, kết hợp và luật quyết định xuất phát từ phân tích sau khi xem kết quả 01/09-22/10 của vòng 1; (2) dữ liệu lịch sử là bản đã ổn định; (3) h = 1 giả định có tác vụ làm mới dự báo hằng ngày trước 06:00; (4) cần app lấy Avg mỗi ngày sau 02:00, và với F3, F4 cần app lưu dòng đơn đã băm. Quyết định cuối cùng cần chạy song song tối thiểu 2 tuần.
