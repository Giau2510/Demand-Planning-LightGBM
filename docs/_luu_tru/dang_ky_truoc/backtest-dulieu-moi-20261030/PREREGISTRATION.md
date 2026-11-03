MỤC ĐÍCH: đo lại độ chính xác của phương án chốt khi dữ liệu nguồn đã loại đơn hủy và bỏ dòng trùng.
CẤU HÌNH (= G2_lgbm của reports\backtest-lgbm7-20261029): 35 biến (bỏ sku_code), trọng số mẫu 3.0 cho horizon <= 7, Tweedie 1.2, 300 vòng, lr 0.05, 31 lá, seed 7, cửa sổ nhãn như production, KHÔNG luật dự phòng; lô 7 ngày từ 01/06/2026; mỗi ngày D dự báo D..D+6 bằng dữ liệu đến D-1; ngày dự báo cuối 22/10/2026.
DỮ LIỆU: bản sao DB ở bước 1 (đã nạp lại lịch sử từ bảng mới).
CHẤM ĐIỂM (Claude chấm): như phương án chốt (dưới 0,2 coi là 0, từ 0,2 làm tròn lên; ngày mở bán; so với demand thực từng ngày; Đúng/Dư ít/Dư nhiều/Thiếu ít/Thiếu nhiều; theo tháng × nhóm × kho; Qty và %; thiếu/dư so với thực tế; so với Avg Demand trên cùng dòng). So sánh với kết quả trên dữ liệu cũ (G2_lgbm).
