# Hướng dẫn sử dụng giao diện

Mở `http://127.0.0.1:8765` (hoặc shortcut *Demand Forecasting*). Nút **English / Tiếng Việt** ở góc trên phải
đổi ngôn ngữ toàn bộ giao diện. Ô **Nguồn đang hoạt động** chọn DEMO / MANUAL_IMPORT / BIGQUERY
(BIGQUERY bị khóa cho đến khi được kích hoạt). Khi dùng DEMO luôn có dải màu tím
“Đang dùng DỮ LIỆU DEMO”. Mọi thuật ngữ có dấu **?** — rê chuột hoặc bấm để xem giải thích.

Giờ hiển thị theo giờ Việt Nam (UTC+7). Mọi thông báo “thành công” chỉ hiện sau khi backend xác nhận.

## Nhóm Dự báo

| Trang | Dùng để |
|---|---|
| **Tổng quan** | Nguồn dữ liệu, ngày dữ liệu mới nhất, trạng thái dữ liệu (mới/cũ), forecast đã publish gần nhất, model version, tổng dự báo theo *Khoảng thời gian muốn dự báo*, biểu đồ theo ngày, top 10 tổ hợp, phương pháp (LightGBM/dự phòng), chất lượng mô hình, job gần nhất, cảnh báo. Nút **Huấn luyện & dự báo ngay**. |
| **Kết quả dự báo** | Chọn lần dự báo (forecast run), khoảng ngày, lọc SKU/FC/ngày. Tab *Tổng theo SKU × FC* và *Dự báo chi tiết từng ngày*. Hiển thị model version, nguồn, data-as-of, forecast origin, thời điểm chạy. **Xuất Excel** theo ngôn ngữ đang chọn. Cột *Thực tế hôm nay* (chỉ ngày hôm nay, số lũy kế đến lần đọc gần nhất — không phải tổng cả ngày). Nút **Xem cách tính** ở mỗi dòng: phương pháp, lý do, lịch sử đã dùng, phép tính dự phòng hoặc đóng góp SHAP của LightGBM. Nếu run được tạo trước khi bật thêm khoảng dự báo, trang báo khoảng còn thiếu và (khi an toàn) cho **Bổ sung khoảng dự báo** từ cùng mô hình. Phần *Độ chính xác thực tế* xuất hiện khi đã có số liệu cuối ngày cho các ngày được dự báo. |
| **Chất lượng mô hình** | Danh sách các lần huấn luyện (được chấp nhận / không đạt / lỗi, kèm lý do), kiểm tra ngưỡng chất lượng, backtest walk-forward theo fold, so sánh baseline, chỉ số theo phương pháp, mức quan trọng feature. |
| **Lịch sử Snapshot D0** | Snapshot tự động sau mỗi lần đồng bộ D0 thành công; lọc theo ngày, SKU, FC, nguồn. Chi tiết hiển thị riêng 3 cột: *thực tế lũy kế đến thời điểm snapshot*, *dự báo đầu ngày cho cả ngày*, *thực tế cuối ngày* (khi đã có). |
| **Thuật toán & thuật ngữ** | Mục lục theo nhóm (quy trình, feature, mô hình & phương pháp, đánh giá, publish, dữ liệu & snapshot); mỗi mục có mục đích, đầu vào, các bước, công thức, ví dụ số (đã kiểm tra bằng test), ý nghĩa, giới hạn; bảng ngưỡng đọc trực tiếp từ Cấu hình. Tooltip tên phương pháp ở mọi trang dẫn tới đây. Quy trình mô hình, giới hạn hiện tại, bảng giải thích WAPE, MAE, bias, MAPE, backtesting, model version, snapshot, data freshness, data leakage, retry, idempotency, forecast origin, feature engineering… |

**Định dạng:** mọi ngày hiển thị `DD/MM/YYYY` (cả khi giao diện tiếng Anh), ngày giờ theo giờ Việt Nam
`DD/MM/YYYY HH:mm`; ô chọn ngày nhập theo `DD/MM/YYYY` (nút 📅 để chọn trên lịch). Số không có số 0 thừa (`7,2`, `10`).
Trong *Xem cách tính*: phần tóm tắt (forecast, yếu tố ảnh hưởng mạnh nhất, chất lượng) luôn hiện; *Forecast được tạo ra
như thế nào?* trình bày từng bước (giá trị nền → đóng góp → điểm thô → exp → forecast đã publish) với bảng yếu tố làm
tăng/giảm và nút *Xem toàn bộ feature*; mục 3 là bảng **Ngày | Thứ | Demand** (cũ → mới) có nút *Xuất Excel lịch sử*;
mục 6 giải thích WAPE, Bias, số điểm đánh giá, quality gate và cho tải các điểm backtest; *Chi tiết kỹ thuật* hiện độ
chính xác đầy đủ. Trang *Thuật toán & thuật ngữ* có thêm *Mô hình được huấn luyện như thế nào?* và *Danh mục feature*.

**Khoảng thời gian muốn dự báo**: chọn 7 ngày nghĩa là dự báo từng ngày trong 7 ngày tiếp theo, bắt đầu từ ngày sau ngày
dữ liệu cuối cùng (forecast origin). Ví dụ dữ liệu đến 13/10/2026 → 7 ngày = 14/10/2026–20/10/2026.

## Nhóm Dữ liệu

| Trang | Dùng để |
|---|---|
| **Import dữ liệu lịch sử** | Tải file mẫu, tải lên `.xlsx`, chọn sheet, ánh xạ cột, kiểm tra, xem trước, tải báo cáo lỗi, xác nhận hoặc hủy. Có chế độ *Thay thế toàn bộ lô*. Xem [IMPORT-EXCEL.md](IMPORT-EXCEL.md). |
| **Lịch sử lô import** | Tất cả lô (cả lô đã thay thế/xóa — để truy vết). Nút *Dùng làm bộ dữ liệu*, *Thay thế lô này*, *Xóa lô* (phải gõ đúng mã lô). |
| **Chất lượng dữ liệu** | Số dòng đọc/hợp lệ/bị loại, trùng, ngày dữ liệu gần nhất, độ dài lịch sử, SKU/FC mới, chuỗi ngắn/gián đoạn/ngừng bán, ngày thiếu, dữ liệu cũ; *Được phép huấn luyện* / *Được phép publish*. |

## Nhóm Quản trị

| Trang | Dùng để |
|---|---|
| **Cấu hình dự báo** | Khoảng dự báo (bật/tắt, thêm số ngày tùy chỉnh, giới hạn an toàn, khôi phục mặc định), ngưỡng chất lượng (có cảnh báo *chưa được phê duyệt nghiệp vụ*), nhóm feature, quy tắc dự phòng, backtest, tham số LightGBM, chính sách dữ liệu cũ, chính sách import, lịch chạy, retry/timeout. Mỗi mục có **Lịch sử thay đổi**. |
| **Kết nối BigQuery** | Thẻ *Xác thực Google*: tài khoản Windows đang chạy ứng dụng, nơi tìm ADC, nút **Đăng nhập Google** / đăng xuất (cần OAuth client do quản trị cấp). Project ID (điền sẵn `lakehouse-prod-394907`), Dataset ID, location, bảng, ngày bắt đầu đọc (mặc định 01/01/2026), chính sách dòng trùng, xác thực, kiểm tra kết nối/schema/xem trước/kiểm tra dữ liệu 30 ngày, **kiểm tra dữ liệu toàn kỳ** (đối chiếu số dòng & tổng target, dòng bị loại theo lý do, ngày thiếu, trùng, phân bố trạng thái), ước tính bytes, kích hoạt chế độ sản xuất. Xem [BIGQUERY.md](BIGQUERY.md). |
| **Ánh xạ trường** | Ánh xạ cột bảng BigQuery → trường nội bộ (khóa & target) và trường tham chiếu (chỉ để kiểm tra/đối chiếu). Nút *Gợi ý cho bảng demand_planing_lightgbm* điền sẵn theo schema thật, chưa lưu cho đến khi bấm *Kiểm tra & lưu ánh xạ*. |
| **SQL nguồn & đồng bộ** | SQL lịch sử và SQL D0 (soạn, lưu phiên bản, kiểm tra bằng dry-run BigQuery, xem trước giới hạn dòng, kiểm tra dữ liệu, khôi phục phiên bản), khóa duy nhất ứng viên, trạng thái hai job đồng bộ độc lập (lịch, lần chạy gần nhất, số dòng, phiên bản SQL) và backfill có kiểm soát. Chỉ phiên bản đã kiểm tra đạt mới được scheduler dùng. Xem [BIGQUERY.md](BIGQUERY.md). |
| **Quản lý feature** | Mọi biến đầu vào với trạng thái thật: Đang sử dụng / Có dữ liệu nhưng chưa kích hoạt / Đang lên kế hoạch / Thiếu dữ liệu; feature set của lần huấn luyện tiếp theo và của mô hình đang dùng (phiên bản `FS-…`). Biến chưa có dữ liệu không bao giờ được tự tạo giá trị. Xem [MO-HINH-VA-CHI-SO.md](MO-HINH-VA-CHI-SO.md). |
| **Job & Scheduler** | Trạng thái scheduler, lịch sử job (thành công/thất bại/đang chạy/chờ thử lại/bị bỏ qua + lý do), chạy job thủ công, *Kiểm tra lịch ngay*. |
| **Hệ thống & sao lưu** | Phiên bản, thư mục dữ liệu, phiên bản schema DB, sao lưu ngay, danh sách bản sao lưu, nhật ký kiểm toán. |

## Trạng thái thường gặp

| Nhãn | Ý nghĩa | Việc nên làm |
|---|---|---|
| Không đạt chất lượng (`QUALITY_GATE_FAILED`) | Mô hình mới không đạt ngưỡng → **không publish**, forecast cũ được giữ | Xem *Chất lượng mô hình* → kiểm tra dữ liệu hoặc điều chỉnh ngưỡng (sau khi nghiệp vụ duyệt) |
| `DATA_NOT_TRAINABLE` | Lịch sử quá ngắn / không có dữ liệu | Import thêm lịch sử (tối thiểu cấu hình: 56 ngày) |
| `STALE_DATA_BLOCKED` | Dữ liệu cũ hơn ngưỡng cho nguồn bị kiểm tra (mặc định chỉ BIGQUERY) | Kiểm tra đồng bộ D-1 |
| `NO_NEW_DATA` (bị bỏ qua) | Dữ liệu không đổi kể từ lần huấn luyện được chấp nhận | Bình thường; tick *Huấn luyện lại dù dữ liệu không đổi* nếu muốn |
| `MISSED_SLOT_NO_BACKFILL` | Mốc lịch bị lỡ do máy tắt | Bình thường; không có snapshot giả cho mốc đã qua |
| `NOT_APPLICABLE_FOR_SOURCE` | Job không áp dụng cho nguồn hiện tại (vd. D-1 khi dùng DEMO) | Không cần làm gì |
