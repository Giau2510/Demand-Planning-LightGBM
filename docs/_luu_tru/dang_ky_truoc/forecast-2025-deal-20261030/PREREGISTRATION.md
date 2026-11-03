MỤC ĐÍCH: cho mô hình LightGBM học thêm dữ liệu 2025 và dữ liệu deal, dự báo 01/06–22/10/2026, đóng gói để Claude so với demand thực tế. KHÔNG chấm điểm trong thư mục này.
CẤU HÌNH: như E2 của reports\backtest-2025-deal-20261030\PREREGISTRATION.md, tức phương án chốt (35 biến, bỏ sku_code, trọng số horizon, Tweedie 1.2, 300 vòng, lr 0.05, 31 lá, seed 7, không luật dự phòng) + 4 biến cùng kỳ năm trước + 12 biến deal (chỉ dùng deal đã bắt đầu chạy tại thời điểm dự báo). Lô 7 ngày từ 01/06/2026; mỗi ngày D dự báo D..D+6 bằng dữ liệu đến D-1; ngày dự báo cuối 22/10/2026.
CODE: dùng lại runner và code tính biến E2 của reports\backtest-2025-deal-20261030\ (lgbm7_e.py, deal_lib.py, không sửa), không dùng code app mới.
DỮ LIỆU: 2026 từ bản sao g1 (= production sau khi nạp lại, nguồn phiên bản 10:03:48 ngày 30/10/2026), chỉ đọc; 2025 và bảng deal từ BigQuery, dry-run trước, trần 5 GB mỗi truy vấn.
KIỂM TRA RÒ RỈ: như lần trước, bắt buộc; không đạt thì dừng.
