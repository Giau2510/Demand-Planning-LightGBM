# 11 – Lịch sử quyết định (tới 05/11/2026)

Tóm tắt để kỹ sư mới biết **vì sao** hệ thống như hiện nay. Nguồn đầy đủ: nhật ký quyết định của chủ dự án
(`03_ma_nguon\docs\05_nhat_ky_quyet_dinh.md` hoặc bản mới nhất kèm gói bàn giao) và các báo cáo trong
`03_ma_nguon\docs\04_mo_hinh_ket_qua\`. "Đúng" = % SKU × ngày "Đúng với demand" (định nghĩa: `03_logic_du_bao.md`
mục 8.2); N1 = ngày thứ 1, 7N = 7 ngày; "điểm" = điểm phần trăm.

## 1. Dòng thời gian các quyết định chính

| Ngày | Quyết định | Lý do / ghi chú |
|---|---|---|
| 17/10/2026 | Nhóm biến Giá đưa vào mô hình (`price_last`, `price_rel_28`) | Quyết định về nhóm feature Giá (`MO-HINH-VA-CHI-SO.md`) |
| 20/10/2026 | Hậu tố `.1/.2/.3` của mã hàng là thứ tự mở bán, **không phải vùng / kho**; vùng chỉ lấy từ cột nguồn | Tránh suy diễn sai FC / giờ mở bán |
| 20/10/2026 | Thực bán của một ngày đã đóng được chốt từ lần D-1 thành công và không đổi | Báo cáo độ chính xác ổn định |
| 22/10/2026 | Nhãn = nhu cầu gộp lúc tạo đơn, không giảm lịch sử khi đơn biến mất | **Đã thay** bởi FOLLOW_SOURCE (30/10) |
| 27/10/2026 | Huỷ F4 của backtest đăng ký trước | Quyết định trước khi F4 chạy (`backtest-prereg-fast-20261028.md`) |
| 28/10/2026 | **Đóng băng bản 1.3.0 (shadow)**; hướng mới: LightGBM thuần + làm tròn lên | Bước C1.3 của 1.3.0 không đạt; không bao giờ push / cài bản này |
| 29/10/2026 | **Phương án chốt 1.3.1** (áp 13:39): bỏ biến `sku_code` (35 biến), trọng số 3,0 cho h ≤ 7, tắt luật dự phòng (`fallback_enabled = false`), số công bố = 0 khi < 0,2 còn lại làm tròn lên, bật làm mới dự báo + báo cáo độ chính xác, nhãn "Chạy thử" bật | `cau_hinh_dang_dung.md` |
| 30/10/2026 | **Lịch sử theo nguồn (FOLLOW_SOURCE)**: dòng BI xoá là đơn huỷ / trả, không phải nhu cầu (production đổi 02:21) | Thay quy tắc 22/10 |
| 30/10/2026 | Dữ liệu 2025 (E1) và deal (E2) **không dùng** | Không tốt hơn G2 (bảng mục 2) |
| 31/10/2026 | **Chọn SEL2** (trung bình 2 ứng viên tốt nhất theo SKU × FC): Đúng cả kỳ 64,63 → 69,79 (+5,2 điểm) | `ket_qua_sel2_20261031.md` |
| 31/10/2026 | Học 112 ngày (V33_L112) thay vì 168 ngày; V37_deal, V38a/V38b không giữ; `num_threads` giữ mặc định | Bộ nhớ; không qua quy tắc giữ; đổi số luồng làm đổi model |
| 02/11/2026 | Lịch production giữ nguyên: D-1 01:10, dự phòng 01:15, học 01:20 (BI cập nhật lúc 01:00); 1.4.0 học lại **thứ Hai** ngay sau D-1; hạn Excel **06:30** | Lịch sau cài phải trùng tuyệt đối trước cài |
| 02/11/2026 | Kế hoạch đồng bộ lịch sử FOLLOW_SOURCE có chốt chặn (tổng bỏ ≤ 0,2 %); cấu trúc lại tài liệu; dọn dung lượng; mục RAM 1/3/6 sang 1.4.1 | Nhật ký 02/11 |
| 03/11/2026 | Tái lập D3 chỉ đối chiếu 15/07 và 15/10 (bỏ 15/09); lệch ngưỡng là dừng | Thời gian / bộ nhớ |
| 03/11/2026 | AVG_DEMAND: mỗi SKU × FC một seller; nhiều dòng thì **báo, không tự chọn** (cảnh báo `AVG_DEMAND_MULTI_SELLER`, không có số) | Tránh tự gộp sai |
| 03/11/2026 | BI dựng bảng lúc 01:00; bảng nhu cầu phải dựng **sau** bảng giờ mở bán | Ngày 02/11 bị trống giờ mở bán do thứ tự dựng |
| 03/11/2026 | D3 **ĐẠT** (15:38): sai khác lớn nhất 0,0, `model_used` lệch 0; bỏ mục 4 bảng O3 (khoá category) vì tăng đỉnh bộ nhớ | Điều kiện để cài |
| 03/11/2026 | **Cài 1.4.0** (~17:00–18:00): sao lưu + thử khôi phục đạt, migration 0012, lịch trùng tuyệt đối | Chủ dự án trả lời "CÀI" |
| 03/11/2026 | Chế độ vận hành: tự chạy liên tục bước đã duyệt, báo trạng thái định kỳ, bộ chạy độc lập + watchdog | Chống kẹt phiên |
| 04/11/2026 | File chính thức đầu tiên `du_bao_20261104.xlsx` (v2, 410.137 dòng) lúc 03:23 | E3 xong |
| 04/11/2026 | **Tắt nhãn "Chạy thử – chưa dùng để mua hàng"** (07:55): số dự báo làm mới là số dùng mua hàng | Chỉ `daily_forecast.trial_mode` đổi |
| 04/11/2026 | **Áp dụng đồng bộ lịch sử FOLLOW_SOURCE** 2.364 khoá (09:00): 602 / 602 ô ngày × kho khớp nguồn, bỏ 58.009 đơn vị; đóng đồng bộ 11:50, ngày 29/10 còn lệch +47 đơn vị để job đồng bộ hằng tuần xử lý (ghi "1.4.1", nay thuộc danh sách bản sau 1.4.2) | Đơn huỷ / trả BI xoá thêm |
| 04/11/2026 | FALLBACK 36,8 % SKU × FC (chủ yếu do ít ngày mở bán): làm (a) TOM_TAT ghi tỷ lệ theo 2 mẫu số, (b) lý do riêng cho SKU × FC 0 ngày mở bán; **không** đổi luật 14 ngày (c) | Danh sách 1.4.1 (nay: bản sau 1.4.2) |
| 04/11/2026 | Code 1.4.0 lên GitHub (tag `v1.4.0`); mọi thay đổi sau làm trên branch của 1.4.0, 1.4.1 tách từ đó | Merge vào `main`: chủ dự án quyết sau |
| 04/11/2026 | **Nguồn số dùng để mua = `LIGHTGBM` cho toàn bộ 58.591 SKU × FC** (12:59, tải lên hàng loạt, lô `SCU-20261104055942-4E9A1A`); cặp mới sau đó mặc định `AVG_DEMAND` | Chủ dự án chốt ~12:50 |
| 04/11/2026 | **Quy tắc `forecast_used` (bản vá = 1.4.1)**: có `lightgbm_forecast` (kể cả 0) → dùng; ngoài phạm vi lần chạy SEL2 + tiền tố `MEDX` → 0 (`NGOAI_PHAM_VI_GAN_0`); tiền tố khác → AVG_DEMAND (`KHONG_CO_DU_LIEU_DEMAND`, tạm thời); không có lần chạy / thiếu số trong phạm vi → AVG_DEMAND (`KHONG_CO_SO` / `STALE`), không ghi 0 | Chủ dự án xác nhận cách hiểu ~13:25; mọi mục "1.4.1" khác chuyển sang danh sách sau |
| 04/11/2026 | **1.4.2 làm trong ngày, chỉ 2 mục**: lần làm mới SEL2 hằng ngày tự đọc giờ mở bán (không chặn; lỗi → cờ `OPEN_HOURS_READ_FAILED`); sao lưu chứa `models\sel2` (khôi phục đúng thư mục con, chặn đường dẫn lạ). Các mục khác để bản sau | Chủ dự án ~16:42; trước đó giờ mở bán dừng ở 02/11, SEL2 ngày 06/11 sẽ `OPEN_HOURS_INVALID` |
| 04/11/2026 | Lần cài 1.4.1 dừng ở bước sao lưu trực tuyến (600 giây, DB ≈ 10 GB) – production không đổi; 1.4.2 nâng thời gian chờ lên 3.600 giây. Tối 04/11 đọc bù giờ mở bán 28/10–03/11 (354.942 dòng). 1.4.2 = bản được cài lên production (lịch cài 04–05/11) | Bộ chạy tự động |
| 04/11/2026 | Số "Avg cũ": dùng **36,5 %**, tái lập trên đúng 1.596.978 ô backtest ([01_tong_quan.md](01_tong_quan.md) mục 3.1); 42,2 % trước đây tính trên dữ liệu chưa sửa và tập ô khác, không dùng nữa | Chủ dự án chốt |
| 05/11/2026 | **Cài 1.4.2 trong giờ làm việc** (chủ dự án chọn "cài ngay" sau khi lần cài 05:33 bị dừng lúc 06:00 ở bước chỉ đọc vì hết khung 04:00–06:00) | Mỗi lần cài chạy storage-verify 3 lần + sao lưu 2 lần trên DB ≈ 10 GB → nhiều giờ, app dừng ~1 giờ |
| 05/11/2026 | **Khoá vận hành** `run\OPS_LOCK` (phiên, việc, giờ bắt đầu): runner và mọi script vận hành kiểm tra trước khi ghi DB / cài / dừng app; runner giữ máy không ngủ, báo khi chạy pin, báo mọi thay đổi trạng thái; khung giờ của bước cài chỉ xét lúc bắt đầu; mọi báo cáo mở đầu bằng [tên phiên] | Máy ngủ (Modern Standby) và lượt cài bị dừng giữa chừng sáng 05/11 |
| 05/11/2026 | **QUY TẮC CỐ ĐỊNH `forecast_used` (1.4.3, ghi trong `CLAUDE.md`, mọi phiên tuân theo):** (1) `LIGHTGBM` có số của hôm nay (kể cả 0) → số đó, không thay 0 bằng Avg; (2) ngoài phạm vi lần chạy tham chiếu → **0 với mọi tiền tố mã** (`NGOAI_PHAM_VI_GAN_0`; bỏ `KHONG_CO_DU_LIEU_DEMAND`); (3) thiếu số trong phạm vi / hôm nay lỗi → số của lần chạy SEL2 thành công gần nhất **≤ 3 ngày** có số cho đúng ngày đích (`DUNG_SO_LAN_CHAY_TRUOC`, cờ `LAN_CHAY_TRUOC:<ngày>`); ngày lỗi dùng **phạm vi** của lần chạy đó (ngoài phạm vi → 0); chỉ khi không có lần chạy nào trong 3 ngày → Avg (`STALE`); (4) `AVG_DEMAND` không có Avg mà có số LightGBM → số LightGBM (`KHONG_CO_AVG_DUNG_LIGHTGBM`); (5) **luôn làm tròn** (< 0,2 → 0, còn lại lên), **không bao giờ trống** (0, `KHONG_CO_SO_NAO`); giữ `lightgbm_forecast`, `avg_demand` gốc | Kiểm tra theo từng SKU tháng 10: thay 0 bằng Avg làm 54,5 % SKU lệch nhiều hơn, chỉ 5 % đúng hơn; tổng lệch 18.971 → 81.439. Một ngày lỗi không được làm mọi số thành 0 hay chuyển hết sang Avg |
| 05/11/2026 | **1.4.3 bỏ sao lưu lặp lại khi cài**: `deploy-upgrade.ps1 -VerifiedBackup <zip> -RestoreReport <json>` bỏ cả 2 lần sao lưu khi có bản sao lưu của chính DB đang chạy, đã thử khôi phục đạt (DB + model), ≤ 6 giờ, nằm trong thư mục backups; điểm khôi phục là bản đó | Chủ dự án 05/11; data-reviewer: an toàn có điều kiện (diễn tập trên bản sao DB) |
| 05/11/2026 | ZIP bàn giao **chỉ** đóng từ gói cài 1.4.3 thật (không dùng 1.4.2) | Chủ dự án 05/11 |

**Danh sách việc đã chốt cho bản sau 1.4.2 (chưa làm; ban đầu ghi "1.4.1"):** FALLBACK (a) + (b); job đồng bộ lịch sử
hằng tuần với chốt theo **tỷ lệ** (tổng bỏ ≤ 0,5 %, ngày bỏ > 5 % thì liệt kê, không có khoá mới phía nguồn), không
dùng danh sách khoá cố định; mỗi ngày chỉ giữ 1 file Excel cuối cùng; dòng ghi chú "lịch sử chưa đủ 28 ngày" trong
`TOM_TAT`; bỏ chữ "Chạy thử" còn nằm cứng trong câu kết quả `DAILY_FORECAST_PUBLISHED`; các mục RAM 1, 3, 4, 6 (bảng
O3); mỗi tuần báo danh sách SKU × FC đã có `lightgbm_forecast` mà cấu hình vẫn `AVG_DEMAND`; dọn
`forecast_refresh_values` / `actual_daily` (ưu tiên cao, 1.4.3); `pyarrow` đã thêm vào requirements ở 1.4.2. Quy tắc `forecast_used` cuối cùng
(quy tắc cố định 05/11/2026) có từ 1.4.3; 1.4.1 / 1.4.2 có quy tắc "trống + MEDX → 0, mã khác → Avg"; 1.4.0 không có.

## 2. Đã thử nhưng KHÔNG dùng

| Phương án | Kết quả (số) | Lý do loại | Tài liệu gốc |
|---|---|---|---|
| E1 – thêm dữ liệu cùng kỳ 2025 | Σ\|lệch\|/demand N1 65,22 % vs G2 65,18 % (+0,04); 7N 68,47 vs 68,35 (+0,11) – thấp hơn là tốt | Không tốt hơn mốc G2 | `03_ma_nguon\docs\04_mo_hinh_ket_qua\da_thu\backtest-2025-deal-20261030.md`, `da_thu\2025_va_deal.md`, `da_thu\forecast-2025-deal-20261030.md` |
| E2 – 2025 + biến deal | 65,64 % / 68,76 % (+0,45 / +0,41 so với G2) | Không tốt hơn E1 | như trên |
| G1 – biến deal / voucher (10 biến) | Chiếm 0,03–0,12 % tổng gain, xếp 36–46 / 46 biến | Gần như không đóng góp; không đưa vào | `da_thu\backtest-lgbm7-20261029.md` |
| V37_deal – deal biết trước (`created_time`) + mức giảm giá | Đúng N1 68,70 vs V33 70,07 (−1,37); 7N −1,57; SEL2 7 ứng viên kém 6 ứng viên −0,20 / −0,30 (hiệu chỉnh −0,02 / −0,09) | Không qua quy tắc giữ; deal chỉ biết trước vài giờ | `da_thu\cai-tien-deal-20261031.md` |
| V38a – đánh dấu đơn đột biến theo khách (mức dòng đơn, theo `customer_id`) | Đúng −1,26 / −1,27 so với V33 | Không giữ | `da_thu\cai-tien-dotbien-20261031.md` |
| V38b / R62 (V38b thay V33 trong SEL2) | R62 vs SEL2: Đúng +0,23 / +0,20; Đúng S2 N1 +0,40 nhưng **7N −0,15** | Trượt đúng 1 tiêu chí (Đúng S2 7N) | như trên |
| A72 (V38b thêm làm ứng viên thứ 7) | Đúng S2 −0,51 / −0,61 | Không giữ | như trên |
| Học 168 ngày (L168) | Đúng N1 70,51, 7N 70,36 (tốt hơn 112 ngày) nhưng RAM đỉnh 3,6–3,8 GB | Bộ nhớ (máy chỉ còn khoảng 6 GB commit) | `03_ma_nguon\docs\04_mo_hinh_ket_qua\ket_qua_sel2_20261031.md` (bước 3.3) |
| Học 364 ngày | Dừng sau lô đầu, RAM 4,9 GB | Bộ nhớ | như trên |
| Học 56 ngày; bộ khung b (+21/42/84), c (+112) | Đúng N1 68,99 / 69,26 / 69,25 (nền 69,55) | Kém hơn | như trên |
| Chu kỳ khách (3.4) | 69,98 vs 70,07 | Không tốt hơn | như trên |
| Chặn đột biến NHẤT THỜI (3.5a / 3.5b + ôm hàng) | Đúng 75,18 / 75,40 nhưng thiếu +4,3 điểm | Thiếu hàng tăng quá 1 điểm | như trên |
| Hai tầng làm cấu hình chính | Đúng +4,10 / +4,72, thiếu +2,08 / +2,26 | Thiếu tăng; chỉ giữ làm **ứng viên** V36 | như trên |
| TSB, Croston (SBA), TB 4 lần cùng thứ, TB 7 ngày làm cấu hình chính | Đúng N1 67,23 / 67,97 / 68,18 / 70,40 (TB 7 ngày thiếu +2,1) | Kém hoặc thiếu tăng; TSB / DOW4 / AVG7 giữ làm ứng viên | như trên |
| SEL – chỉ lấy 1 ứng viên tốt nhất | Đúng 75,06 / 75,24, thiếu +1,58 / +1,48 | Thiếu tăng quá 1 điểm → chọn SEL2 (trung bình 2) | như trên (bước 4) |
| `num_threads` = 10 thay mặc định | Model khác 11 / 6.080 dòng văn bản model | Làm đổi kết quả | như trên |
| Biến `sku_code` | ~9,3 nghìn mức, nhiều split nhất (5.968), gain 8,9 % → nguy cơ học thuộc | Bỏ từ 1.3.1 (B1); model 1.3.1 trùng từng byte biến thể G2 | `04_mo_hinh_ket_qua\dieu_tra_mo_hinh.md`, `cau_hinh_dang_dung.md`, `da_thu\backtest-lgbm7-20261029.md` |
| Luật dự phòng 1.3.1 (`fallback_enabled`: INACTIVE / NEW_SERIES / INTERMITTENT) | – | Tắt từ 1.3.1 (B2): mọi chuỗi dùng LightGBM; SEL2 có FALLBACK riêng (V33_L112) | `cau_hinh_dang_dung.md`, `MO-HINH-VA-CHI-SO.md` |
| Bản 1.3.0 shadow (chạy song song + trọng số horizon) | Dừng trước C6, C1.3 không đạt | Đóng băng 28/10; trọng số horizon được đưa vào 1.3.1 | `03_ma_nguon\docs\_luu_tru\bao_cao_130_shadow.md`, `_luu_tru\ke_hoach_130_shadow.md` |
| Khoá category (mục 4 bảng O3) | Đỉnh bộ nhớ tăng khi duyệt dòng | Bỏ (03/11) | Nhật ký quyết định 03/11 |
| Đổi luật số ngày tối thiểu (14 ngày) để giảm FALLBACK | – | Chủ dự án không làm (04/11, phương án c) | Nhật ký quyết định 04/11 |
