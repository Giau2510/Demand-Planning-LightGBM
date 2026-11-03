MỤC ĐÍCH: tìm cho từng nhóm SKU phương án dự báo ngày D tốt nhất với câu trả lời có/không; kiểm chứng chu kỳ đặt lại của khách có dự đoán được ngày đột biến không.

NỀN: bản sao DB vòng 1 (SHA C7A663BE…F073); lô 7 ngày từ 01/06/2026, ngày dự báo cuối 22/10/2026; seed 7; siêu tham số production trừ khi biến thể ghi khác; h = 1 là chỉ số chính, h = 2 phụ.

DỮ LIỆU AVG LỊCH SỬ: lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku_historical, seller_code = MEDX, sku_system_status thuộc (OUT_OF_STOCK, LIMIT, NORMAL). Avg dùng cho ngày D = bản ghi có transformed_at (giờ Asia/Ho_Chi_Minh) mới nhất <= 06:00 ngày D, theo SKU x FC. Chỉ dùng nếu kiểm tra căn ngày xác nhận Avg đó không phản ứng với demand của chính ngày D; nếu kiểm tra cho thấy Avg chứa demand ngày D thì dịch lùi 1 ngày và ghi lại. Khi dự báo từ mốc D cho mọi horizon, chỉ dùng Avg đã có tại mốc D.

CHẨN ĐOÁN (chỉ dữ liệu 01/06-31/08): nhóm A như vòng 1. Ngày đột biến = thực bán > 2 lần trung vị thực bán ngày mở bán của SKU x FC trong 01/06-31/08. Khách đều tại ngày D = có >= 3 ngày đặt trong 180 ngày trước D và hệ số biến thiên khoảng cách giữa các lần đặt <= 0.5. Khách đến hạn tại ngày D = khách đều có (số ngày kể từ lần đặt cuối) / (trung vị khoảng cách) trong [0.8, 1.5], chỉ dùng dữ liệu trước D. Báo cáo: % lượng hàng nhóm A từ khách đều; % lượng hàng ngày đột biến từ khách đều và từ khách đến hạn; cùng các chỉ số đó ở ngày thường.

BIẾN THEO KHÁCH (chỉ dòng đơn có created_date < D, cửa sổ 180 ngày, theo SKU x FC): n_orders_7, n_orders_28, n_customers_7, n_customers_28, avg_order_qty_28, max_order_qty_28, top_customer_share_28, days_since_big_order (đơn >= phân vị 90 cỡ đơn của SKU x FC trong 180 ngày; 181 nếu không có), n_regular, n_due, n_overdue (tỷ lệ trong (1.5, 3]), due_qty (tổng trung vị cỡ đơn của khách đến hạn), overdue_qty, big_due_qty (due_qty của khách thuộc 10% lớn nhất theo lượng hàng 180 ngày), expected_rate (tổng của trung vị cỡ đơn / trung vị khoảng cách, trên khách đều), min_days_to_due (nhỏ nhất của trung vị khoảng cách trừ số ngày kể từ lần đặt cuối, trên khách đều; 999 nếu không có), regular_share_90 (tỷ trọng lượng hàng 90 ngày từ khách đều).
BIẾN XU HƯỚNG VÀ PHÂN LOẠI: ratio_7_28 = roll_mean_7 / roll_mean_28; ratio_1_7 = lag_1 / roll_mean_7; ewm_3, ewm_7 (trung bình mũ, chu kỳ bán rã 3 và 7 ngày, trên ngày mở bán); mean_open_90 và zero_share_open_90 (trên ngày mở bán 90 ngày trước D).

BIẾN THỂ:
R0 = V1 vòng 1 (dùng lại dự báo đã có, không chạy lại).
R1 = R0 + biến theo khách.
R2 = R1 + biến xu hướng và phân loại + che ngày đóng bán đúng như V2 vòng 1.
R3 = R2 + direct_origins = 24.
R4 = R3 + dừng sớm: tập kiểm định = 14 ngày nhãn cuối của cửa sổ huấn luyện mỗi lô (vẫn trước mốc lô); tối đa 1000 vòng; dừng sau 50 vòng không cải thiện WAPE trên dòng horizon <= 7; huấn luyện lại trên toàn cửa sổ với số vòng tìm được; 31 lá; Tweedie 1.2.
R5 = R4 với objective = l1.
R7 = R4 + biến avg_d (Avg đã có tại mốc dự báo) và avg_ratio = avg_d / roll_mean_14.
Dự phòng đăng ký trước: nếu 24 mốc gây thiếu RAM, R3, R4, R5, R7 dùng 12 mốc và ghi rõ.

KẾT HỢP (Claude tính khi chấm): mỗi R0-R5, R7 kết hợp với Avg: w*R + (1-w)*Avg, w thuộc {0.25, 0.5, 0.75}.

CHẤM: chỉ ngày total_open_hours > 0; dự báo làm tròn nửa lên; lệch = tổng |dự báo - thực| / tổng thực; thừa/thiếu = tổng dự báo / tổng thực - 1; lệch cộng dồn theo tuần = tổng theo SKU x FC x tuần của |tổng dự báo - tổng thực| / tổng thực; nhóm A/B/C như vòng 1, xác định bằng dữ liệu 01/06-31/08. Mốc so sánh: avg_demand_history như vòng 1. Chỉ số chính: lệch theo ngày.

CHỌN (chỉ 01/06-31/08, h = 1, từng nhóm): trong {Avg, R0-R5, R7, các bản kết hợp}, phương án có lệch theo ngày thấp nhất trong số phương án có |thừa/thiếu| <= |thừa/thiếu của Avg|.

XÁC NHẬN (01/09-22/10, h = 1, từng nhóm): nếu phương án được chọn có lệch theo ngày cao hơn Avg và khoảng tin cậy 95% (bootstrap theo SKU x FC) của chênh lệch không chứa 0 -> nhóm đó GIỮ Avg; ngược lại -> nhóm đó CHUYỂN sang phương án được chọn. Báo cáo kèm theo tháng, h = 2 và các chỉ số phụ.

GIỚI HẠN CÔNG BỐ TRƯỚC: (1) ý tưởng biến theo khách, mục tiêu L1, kết hợp và R7 xuất phát từ việc xem kết quả 01/09-22/10 của vòng 1, nên giai đoạn xác nhận không hoàn toàn độc lập; (2) dữ liệu lịch sử là bản đã ổn định; (3) app chưa có tác vụ làm mới dự báo hằng ngày; (4) kết hợp và R7 cần app lấy Avg mỗi ngày trước 06:00. Quyết định cuối cùng cần chạy song song tối thiểu 2 tuần.
