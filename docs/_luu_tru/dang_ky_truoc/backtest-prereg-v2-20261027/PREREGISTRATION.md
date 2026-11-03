MỤC ĐÍCH: xác định các cải tiến LightGBM có làm dự báo ngày D tốt hơn mô hình hiện tại và tốt hơn Avg hay không, bằng kết quả không thể chỉnh sửa sau khi xem.

DỮ LIỆU: bản sao DB backtest 23/10 (SHA 8ABD356D…); giờ mở bán từ lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku (gom SKU x FC x ngày, MAX theo item); lô huấn luyện 7 ngày bắt đầu 01/06/2026, ngày dự báo cuối 22/10/2026; seed 7; siêu tham số production (Tweedie 1.2, 300 vòng, lr 0.05, 31 lá, 36 biến).

BIẾN THỂ:
V0 = cấu hình hiện tại (fingerprint 8468ebe66d1706f7).
V1 = V0 + trọng số mẫu 3.0 cho horizon <= 7, 1.0 cho phần còn lại.
V2 = V1 + ngày đóng bán là "chưa biết" (NaN) trong panel dùng cho biến đầu vào và nhãn; biến open_hours_last, open_hours_mean_7 lấy giờ từ openhours_by_sku cho mọi ngày; luật FALLBACK tính trên panel CHƯA che (giữ nguyên luật cũ).
V3 = V2 + luật FALLBACK chỉ đếm ngày mở bán, theo thứ tự: INACTIVE khi tổng demand trên ngày mở bán trong 60 ngày = 0 VÀ có >= 30 ngày mở bán -> dự báo 0; REOPEN (mã FALLBACK_REOPEN) khi số ngày mở bán trong 56 ngày < 14 -> trung bình demand ngày mở bán trong 180 ngày (không có ngày mở bán nào thì xét luật tiếp theo); NEW khi số ngày mở bán từ đầu chuỗi < 28 -> trung bình demand ngày mở bán từ đầu chuỗi; INTERMITTENT khi tỷ lệ ngày mở bán có demand = 0 trong 56 ngày >= 0.80 -> trung bình demand ngày mở bán trong 28 ngày (không có thì 56 ngày); còn lại -> LightGBM.
V4 = V1 + direct_origins = 24 (cửa sổ nhãn 168 ngày).

ĐỊNH NGHĨA: ngày mở bán = total_open_hours > 0 HOẶC có đơn. Ngày đóng bán = total_open_hours = 0 VÀ không có đơn. Thiếu dòng giờ mở bán = chưa biết: không dùng để học; cảnh báo nếu > 20 cặp SKU x FC hoặc > 1% demand trong cửa sổ huấn luyện, vẫn chạy tiếp.

ĐẦU RA: mỗi ngày D, dữ liệu đến D-1, dự báo h = 1 (ngày D) và h = 2 (ngày D+1).
CHỈ SỐ CHÍNH: h = 1 (vận hành dự kiến: dữ liệu D-1 có lúc 04:10, app lấy lúc 05:00, dự báo được làm mới bằng mô hình đã duyệt trước 06:00). h = 2 là chỉ số phụ, đại diện cho ngày làm mới thất bại.
MỐC SO SÁNH: avg_demand_history (tính lúc 02:00 ngày D, dữ liệu đến D-1, tức cũng là h = 1).

CHẤM ĐIỂM (Claude chấm độc lập): chỉ các ngày total_open_hours > 0; dự báo làm tròn nửa lên; lệch = tổng |dự báo - thực| / tổng thực; thừa/thiếu = tổng dự báo / tổng thực - 1; nhóm A (TB > 20 sp/ngày và <= 20% ngày mở bán không có đơn), B (TB <= 5 sp/ngày và > 20% ngày không có đơn), C (còn lại), xác định bằng dữ liệu 01/06-31/08.

CHỌN MÔ HÌNH TỐI ƯU: chỉ dùng 01/06-31/08, h = 1, nhóm A: biến thể V1-V4 có lệch thấp nhất trong các biến thể có |thừa/thiếu| không lớn hơn của V1; nếu không biến thể nào có lệch thấp hơn V1 thì chọn V1.

KẾT LUẬN: dùng 01/09-22/10, h = 1, báo cáo kèm h = 2. Theo từng nhóm, mô hình tối ưu so với Avg: tốt hơn ở cả lệch và |thừa/thiếu|, và khoảng tin cậy 95% (bootstrap theo SKU x FC) của chênh lệch "lệch" không chứa 0 -> nên đổi; kém hơn ở cả hai -> giữ Avg; mỗi bên hơn một chỉ số -> chưa đủ cơ sở, cần business xác định chi phí thiếu hàng so với dư hàng.

GIỚI HẠN CÔNG BỐ TRƯỚC: (1) ý tưởng V2-V3 xuất phát từ quan sát T9-T10 nên giai đoạn kết luận không hoàn toàn độc lập; (2) dữ liệu lịch sử là bản đã ổn định, không phải đúng như tại thời điểm dự báo; (3) hiện app chưa có tác vụ làm mới dự báo hằng ngày nên kết quả h = 1 là khả năng đạt được khi vận hành đúng thiết kế; (4) Avg tính lúc 02:00 có thể dùng dữ liệu D-1 chưa đầy đủ bằng dữ liệu 04:10. Kết luận cuối cùng cần chạy song song từ 27/10.
