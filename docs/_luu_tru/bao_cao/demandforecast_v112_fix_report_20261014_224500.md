# Báo cáo batch sửa lỗi Demand Forecasting 1.1.2

Thời điểm: 2026-10-14, 18:40 – 22:45 (giờ Việt Nam).

Phạm vi: định dạng số, ngày `DD/MM/YYYY`, lịch sử demand trong "Xem cách tính", tên phương pháp trong Excel.

**Kết quả:**
- Cả 4 nhóm yêu cầu đã được sửa và kiểm thử qua UI và Excel. Bằng chứng chạy trên bản sao DB thật và trên ứng dụng thật (chỉ đọc).
- **Đã cài 1.1.2 vào ứng dụng thật lúc 22:36** sau preflight và backup đã xác minh. Không cần migration (schema giữ nguyên 3).
- Một số mục chưa xác minh được trên máy thật, xem mục 7.

---

## 1. Các file chính đã thay đổi

**Backend**

| File | Thay đổi |
|---|---|
| `backend/app/ml/methods.py` | Tên LIGHTGBM: "Mô hình học máy (LightGBM)" / "Machine-learning model (LightGBM)". `label()` có fallback an toàn cho mã lạ ("Phương pháp chưa có mô tả (MÃ)") và ghi cảnh báo vào log. |
| `backend/app/export_i18n.py` | `DD/MM/YYYY` cho cả vi và en. Format version 4. Tiêu đề cột mã kỹ thuật rõ ràng. Hàm `fmt_dateish`. Nhãn vi/en cho export snapshot và báo cáo lỗi import. |
| `backend/app/api/ops_routes.py` | Export snapshot theo `lang`, ngày `DD/MM/YYYY`, giờ VN |
| `backend/app/data/excel_io.py`, `data/importer.py`, `api/data_routes.py` | Báo cáo lỗi import theo `lang`, ngày `DD/MM/YYYY`. Giá trị lỗi không đọc được giữ nguyên. |
| `backend/app/ml/explain.py` | Lịch sử đủ dài để chứa mọi cửa sổ quy tắc. Cờ `in_calc` cho từng ngày. Tổng đối chiếu `history.calc`. `fallback.matches_history`. |
| `backend/app/__init__.py` | Version 1.1.2 |

**Frontend**

| File | Thay đổi |
|---|---|
| `frontend/src/components/ui.tsx` | `fmtNum`/`fmtPct` bỏ số 0 thừa, theo ngôn ngữ. `fmtDate`, `fmtTime` (giờ VN), `fmtDateish`, `fmtDatesInText`, `parseDmy`. Component `DateInput` `DD/MM/YYYY`. Trục và tooltip biểu đồ dùng `DD/MM/YYYY`. Hook tooltip dùng chung. |
| `frontend/src/i18n.tsx` | Locale số theo ngôn ngữ giao diện; nhãn mới cho bảng lịch sử |
| `frontend/src/pages/ExplainPanel.tsx` | Mục 3 thành bảng Ngày \| Demand; số gọn; ô ngày `DD/MM/YYYY` |
| `Results`, `Dashboard`, `DataQuality`, `Batches`, `ImportPage`, `Performance`, `Snapshots`, `Jobs`, `System`, `Config`, `BigQuery` (`.tsx`) | Mọi ngày qua formatter. Ô chọn ngày dùng `DateInput`. Trang Chất lượng mô hình dùng registry phương pháp thay bộ nhãn trùng lặp. Link export truyền `lang`. |
| `frontend/src/styles.css` | Style bảng lịch sử và `DateInput` |
| `frontend/package.json` | Version 1.1.2 |

**Test:**
- Mới: `backend/tests/test_v112.py` (6 test), `frontend/src/v112.test.tsx` (10 test).
- Cập nhật: `backend/tests/test_v111.py`, `backend/tests/test_import.py`, `frontend/src/v111.test.tsx`, `frontend/src/test-fixtures/methods.json`.

**Tài liệu:** `docs/MO-HINH-VA-CHI-SO.md` (mục Định dạng hiển thị, Xuất Excel v4, bảng lịch sử) và `docs/HUONG-DAN-SU-DUNG.md`.

## 2. Nguyên nhân gốc

| Yêu cầu | Nguyên nhân |
|---|---|
| A. Số 0 thừa | `fmtNum(v, d)` đặt `minimumFractionDigits = maximumFractionDigits = d`, nên luôn ép đủ d chữ số (`7,200000`). Số luôn định dạng `vi-VN`, kể cả giao diện tiếng Anh. |
| B. Ngày lẫn định dạng | Khoảng 30 vị trí in thẳng chuỗi ISO từ API vào giao diện. `fmtTime` trả `YYYY-MM-DD HH:mm`. Trục biểu đồ dùng `MM-DD`. Ô `<input type="date">` hiển thị theo locale trình duyệt (vd. `10/14/2026`). Excel tiếng Anh dùng `YYYY-MM-DD`. Export snapshot và báo cáo lỗi import chưa theo ngôn ngữ. Chi tiết lỗi, lỗi job, JSON kỹ thuật in nguyên chuỗi ISO. |
| C. Lịch sử khó đọc | Mục 3 là một dải ô chỉ có số; ngày chỉ nằm trong tooltip. Không đánh dấu ngày nào được dùng trong phép tính. Lịch sử 56 ngày ngắn hơn cửa sổ 60 ngày của quy tắc "ngừng bán". |
| D. Phương pháp trong Excel | Tên tiếng Việt của `LIGHTGBM` trong registry là "LightGBM", trùng mã kỹ thuật, nên cột phương pháp trông như chưa dịch. Cột mã nằm ngay cạnh với tiêu đề "Mã phương pháp", dễ nhầm. Frontend có thêm bộ nhãn `method.*` riêng (trang Chất lượng mô hình), lệch với registry. |

## 3. Thay đổi đã thực hiện

**Formatter (chỉ ở lớp hiển thị):**
- Không đổi precision tính toán, quy tắc làm tròn (4 chữ số khi publish) hay dữ liệu lưu trữ.
- Số không có số 0 thừa: `7,2`, `10`, `0,5`; giữ `7,2345`.
- Dấu thập phân theo ngôn ngữ: vi `1.234,5`, en `1,234.5`. Phần trăm 1 chữ số thập phân (`13,3%`).

**Ngày:**
- Lịch: `DD/MM/YYYY` ở mọi nơi.
- Ngày giờ: chuyển UTC sang giờ VN (`Asia/Ho_Chi_Minh`), hiển thị `DD/MM/YYYY HH:mm`, kể cả khi qua nửa đêm: `17:30Z` → `15/10/2026 00:30`.
- Ngày thuần không bị lệch múi giờ.
- Ô chọn ngày nhập và hiển thị `DD/MM/YYYY`, từ chối ngày không tồn tại hoặc ngoài khoảng; nút 📅 mở lịch của trình duyệt.
- API và DB giữ định dạng chuẩn.
- **Ngoại lệ có chủ đích:** mã định danh chứa ngày (khóa idempotency `TRAIN_PUBLISH:2026-10-14`) và các trường `*_utc` trong Excel.

**Xem cách tính:**
- Phép tính: `892 ÷ 19 = 46,947368`.
- Dòng làm tròn: `max(0; 46,947368) → làm tròn 4 chữ số thập phân = 46,9474 · giá trị đã publish (bảng dự báo, Excel): 46,9474`.
- Cùng một đại lượng hiển thị cùng số chữ số ở mọi bước.

**Lịch sử (mục 3):**
- Bảng Ngày | Demand | Trạng thái | Dùng trong phép tính, theo thứ tự cũ → mới.
- Độ dài = max(56, 2 × cửa sổ dự phòng, số ngày ngừng bán) = 60 ngày với cấu hình hiện tại. Có ghi rõ khoảng ngày.
- "—" = không có dữ liệu hoặc trước khi chuỗi bắt đầu; 0 = có dữ liệu, không có đơn.
- Các ngày được dùng có dấu ✓ và dòng tổng.
- Backend tự đối chiếu tổng và số ngày của các dòng ✓ với phép tính (`matches_history`).

**Excel:**
- Cột *Phương pháp* lấy tên theo ngôn ngữ từ registry duy nhất.
- Cột cuối *Mã kỹ thuật phương pháp (không dịch)* giữ nguyên mã.
- Mã lạ: nhãn fallback và cảnh báo trong log; export không hỏng.
- Export không ghi gì vào DB (có test).

## 4. Kết quả kiểm thử

| Bộ | Kết quả |
|---|---|
| Backend pytest (`logs\development\tests_20261014_222229.log`) | **126 đạt**, 0 lỗi, 0 bỏ qua |
| Frontend vitest | **31 đạt** |
| Typecheck `tsc -b` / production build | Đạt / Đạt |
| Lint | Dự án không cấu hình công cụ lint |
| E2E trình duyệt, mã nguồn 1.1.2 trên bản sao DB thật (nguồn DEMO đặt trên bản sao) | **75/75** |
| Gói 1.1.2 cô lập: cài mới | 24/24 + 30/30 |
| Gói 1.1.2 cô lập: nâng cấp trên bản sao DB thật (schema 3, không migration) | 13/13 |
| **E2E trình duyệt chỉ đọc trên ứng dụng thật 1.1.2** | **50/50**, không có request ghi |

**Regression test theo yêu cầu:**

| Nhóm | Nội dung đã kiểm |
|---|---|
| Số | `7.2 → 7,2`, `10 → 10`, `0.5 → 0,5`, `7.2345 → 7,2345`. Giá trị gốc không đổi. Phần giải thích không còn số 0 thừa. Metric giữ 1 chữ số %. |
| Ngày | `DD/MM/YYYY` ở UI, trục biểu đồ, ô chọn ngày, ngày trong câu chữ. Giờ VN qua nửa đêm. Excel vi/en, export snapshot, báo cáo lỗi import. |
| Lịch sử | Chuỗi 10 ngày với demand khác nhau từng ngày; ghép ngày–demand đúng thứ tự; "0" khác "—"; tổng các dòng ✓ = 72 = tử số. Backend: trên DEMO đối chiếu từng ngày với `demand_daily`, không ngày tương lai. |
| Excel | Mọi mã có tên vi/en; mã lạ có fallback và log; dữ liệu forecast trong DB không đổi sau export. |

**Kiểm tra đột biến:** test lịch sử/E2E và test trang Kết quả đều **thất bại trên mã cũ** và đạt trên mã mới.

**Sự cố trong lúc chạy E2E (đã xử lý):**
- Lần chạy E2E đầu trên bản sao DB không treo nhưng chờ hết thời gian 900 s ở bước huấn luyện. Bản sao lấy từ DB thật mang nguồn MANUAL_IMPORT chưa có lô dữ liệu, nên nút huấn luyện bị khóa.
- Audit log ghi việc đổi nguồn lúc **18:29 giờ VN** qua giao diện, ngoài các phiên kiểm thử của tôi.
- Tôi đã dừng lần chạy đó (kết quả không được tính) và sửa script để báo lỗi ngay khi nút bị khóa.
- Chỉ trên bản sao, tôi đặt nguồn DEMO rồi chạy lại.
- Lần chạy lại phát hiện thêm một lỗi thật: thẻ "Mốc dự báo" ở trang Kết quả còn ngày ISO. Lỗi đã được sửa, có regression test, chạy lại đạt 75/75.

## 5. Bằng chứng trên dữ liệu DEMO

E2E dùng Chrome headless, bấm, chạm và gõ thật trên giao diện, đối chiếu với API và file Excel tải về:

- **Giải thích (bản sao DB thật):** DEMO-SKU-023 · FC-HCM · 14/10/2026 (dự phòng chuỗi mới) và DEMO-SKU-008 · FC-HCM (LightGBM).
  - Không có số 0 thừa, không có ngày ISO.
  - Bảng lịch sử 60 ngày khớp từng dòng với API.
  - 19 dòng ✓, tổng 892 = phép tính.
  - Số cuối = giá trị publish = bảng.
- **Ứng dụng thật (chỉ đọc):** run `FCR-20261014111845-8B81D1` (30 ngày, 14/10/2026 → 12/11/2026).
  - Ngày `DD/MM/YYYY` ở 10 trang và ở cả giao diện tiếng Anh.
  - Bảng chi tiết và bộ lọc ngày gõ `16/10/2026` lọc đúng.
  - Sau khi tải lại trang vẫn đúng.
  - Excel vi/en: tên phương pháp theo ngôn ngữ, mọi ô ngày `DD/MM/YYYY`, tổng = UI = API, chi tiết = giá trị publish.
  - Export snapshot vi/en dùng `DD/MM/YYYY`.
  - Không lỗi console.
- Ảnh chụp lưu trong thư mục scratchpad của phiên, kèm file `e2e_results.json`.

## 6. Gói phân phối và cài đặt

- Gói: `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.2-win64-portable.zip`, 101 345 255 byte.
- SHA256 `1093BDA1B80D46D85932C3C28A92B420FA9A68BB4F1703FAD4F42C1D2ECAAB57`.
- Giải nén ra `release\DemandForecast-1.1.2\`: 61 file chương trình trùng khớp mã nguồn đã test; 3 script dành cho phát triển không đóng gói.

**Đã cài vào ứng dụng thật (22:36–22:37):**
- **Preflight:** không job chạy, `storage.json` không đổi, không biến `DF_*`, không autostart.
- **Backup độc lập:** `backups\backup-20261014-223619-manual.zip` (SHA256 `799D416A…DB96`). Đã mở và đối chiếu: integrity ok, schema 3, 3 run, số liệu khớp.
- **Cài đặt:** installer tạo thêm `backup-20261014-223636-cli.zip`. **Không có migration.**
- **Sau cài:**
  - phiên bản 1.1.2 (pid 13744, từ `Programs\DemandForecast\1.1.2`);
  - DB `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, nguồn đường dẫn = `storage.json`;
  - `storage.json` hash không đổi; marker `6cff0821634b0447` khớp; `storage-verify` ok; integrity ok, khóa ngoại 0;
  - dữ liệu nghiệp vụ không đổi (chỉ thêm 1 dòng audit của lần sao lưu);
  - log không có lỗi;
  - shortcut Desktop trỏ 1.1.2;
  - nguồn đang hoạt động MANUAL_IMPORT **được giữ nguyên**.
- **Quay lại 1.1.1** (cùng schema 3, không cần khôi phục DB): dừng ứng dụng → chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.1.1\Start.bat`. Bước này chưa được thực hiện thử.

## 7. Đã sửa và chưa xác minh được

**Đã sửa và xác minh:** cả 4 nhóm A–D; lỗi ngày ISO ở thẻ "Mốc dự báo" (phát hiện trong batch).

**Chưa xác minh được:**
- Trên **ứng dụng thật**, nguồn đang là MANUAL_IMPORT chưa có lô dữ liệu (do người dùng chọn), và tôi không được đổi nguồn. Vì vậy:
  - trang Chất lượng dữ liệu chỉ hiện thông báo hướng dẫn;
  - Tổng quan không có biểu đồ;
  - không bấm huấn luyện hay bổ sung trên máy thật.

  Các phần này đã đạt trên bản sao DB thật với nguồn DEMO.
- Lịch bật lên khi bấm nút 📅 (`showPicker` của trình duyệt) chưa được kiểm thử tự động; nhập `DD/MM/YYYY` đã được kiểm.
- Chạm trên thiết bị cảm ứng thật, máy Windows khác, BigQuery: chưa thử. BigQuery vẫn bị chặn.
- Ô ngày trong Excel hiển thị `DD/MM/YYYY` nhờ định dạng ô. Nếu người dùng tự đổi định dạng ô, Excel hiển thị theo lựa chọn đó.
- Quy trình quay lại 1.1.1 chưa chạy thử. Rủi ro thấp vì 1.1.1 và 1.1.2 cùng schema 3.

**Ghi nhận thêm (chỉ đọc, không thay đổi gì):**
- Scheduler 1.1.1 trên máy thật đã tự chạy mốc D0 18:00 thành công: `JOB-20261014110015-AF1C22`, 18:00:15. Đây là bằng chứng cho mục còn mở ở báo cáo nghiệm thu 1.1.1.
- Từ 18:17 đến 18:29, có thao tác trên giao diện thật: bấm huấn luyện (bỏ qua), bổ sung khoảng lên 30 ngày, lưu cấu hình khoảng dự báo, đổi nguồn sang MANUAL_IMPORT.

## 8. Hướng dẫn ngắn cho người dùng

1. Mở **Demand Forecasting** từ shortcut (đã là 1.1.2).
2. Mọi ngày hiển thị dạng **14/10/2026**. Ô chọn ngày gõ theo `DD/MM/YYYY` hoặc bấm 📅.
3. Số hiển thị gọn: `7,2` thay vì `7,2000`.
4. **Xem cách tính** ở mỗi dòng kết quả:
   - mục 3 là bảng ngày–demand;
   - các ngày có dấu ✓ là ngày dùng để tính;
   - dòng tổng khớp với phép chia ở mục 4–5.
5. **Xuất Excel** theo ngôn ngữ đang chọn. Cột *Phương pháp* là tên dễ hiểu; cột cuối giữ mã kỹ thuật để đối chiếu.
6. Nếu muốn xem lại dữ liệu DEMO trên Tổng quan: ở ô *Nguồn đang hoạt động* chọn *DEMO*. Hiện đang chọn MANUAL_IMPORT nhưng chưa có lô import.
