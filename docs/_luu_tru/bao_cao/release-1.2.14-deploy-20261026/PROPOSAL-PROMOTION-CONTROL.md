# Đề xuất: kiểm soát việc đưa model vào sử dụng (promote)

Trạng thái: **ĐỀ XUẤT, chưa triển khai.** Không nằm trong 1.2.14. Cần anh/chị duyệt trước khi làm, dự kiến cho bản 1.2.15.

## Vì sao

Ngày 26/10/2026 lúc 11:40:21, model `MV-20261026-105345-C73F` được đưa vào sử dụng qua nút "Dùng model này" trên trang
*Chất lượng mô hình*. Kết quả là run `FCR-20261026044021-330262`, thay cho `MV-20261024-163642-EA7D`.

Điều tra (`reports/release-1.2.14-prep-20261026/FINAL_REPORT.md`) **không xác định được ai bấm**:
- `audit_log` không có người thực hiện;
- ứng dụng không ghi request ID, địa chỉ client hay user agent;
- không có log truy cập cho các request ghi.

Ngoài ra, candidate C635 đã bị một model mới hơn thay thế nhưng API vẫn trả `can_promote: true`, nên nút vẫn hiện. Backend
sẽ từ chối, nhưng giao diện gây hiểu nhầm.

## Đề xuất

| # | Thay đổi | Nơi sửa | Ghi chú |
|---|---|---|---|
| 1 | **Audit đầy đủ cho `MODEL_PROMOTED`** (và `MODEL_RELEASED_WITH_GATE_EXCEPTION`): người duyệt (bắt nhập), tài khoản Windows chạy app, địa chỉ client, user agent, request ID, thời điểm bắt đầu / kết thúc, training run và model **trước / sau**, forecast run mới, lý do | `pipeline.promote_candidate`, `forecast_routes.promote_training_run` | Ghi vào `details_json` có sẵn: **không cần migration** |
| 2 | **Request ID cho mọi request ghi**: middleware sinh UUID, trả header `X-Request-ID`, ghi một dòng log (method, path, status, thời gian, client) | `main.py` / `security.py` | Ghi thêm log, không đổi dữ liệu |
| 3 | **Bắt nhập cụm xác nhận**: `PROMOTE-<model_version>` kèm "người duyệt" và "lý do". Backend so khớp chính xác; thiếu hoặc sai trả 422 `CONFIRMATION_MISMATCH` | `PromoteBody`, `Performance.tsx` | Giống quy trình gate exception đã có (`EXCEPTION-<run>`) |
| 4 | **Candidate đã bị thay thế không còn nút promote**: `promotable()` trả `SUPERSEDED` khi có run ACCEPTED mới hơn, và `DATA_CHANGED` khi fingerprint dữ liệu khác. Khi đó `can_promote: false` và nút ẩn hoặc vô hiệu, kèm lý do | `pipeline.promotable` | Backend **đã** từ chối trong `promote_candidate`; đây là sửa cho kết quả kiểm tra khớp với thực tế |
| 5 | **Backend là chốt chặn duy nhất**: mọi điều kiện (mục 3, 4, không có job đang chạy, SHA của model, fingerprint) kiểm tra ở backend; giao diện chỉ phản ánh | route + pipeline | Ẩn nút không thay cho kiểm tra |
| 6 | Tùy chọn: hiện "đã promote lúc … bởi …" trên trang *Chất lượng mô hình* và Dashboard | frontend | Đọc từ audit |

## Ảnh hưởng

- **Không đổi:** schema DB, model, forecast đã lưu, lịch chạy, quy tắc chất lượng.
- **Thay đổi cách làm việc:** người promote phải gõ cụm xác nhận, tên người duyệt và lý do.
- **Script tự động:** hiện không script nào promote trên production. Script diễn tập `iso1213r.ps1` (cổng cách ly) phải gửi thêm trường xác nhận.

## Kiểm thử cần có

**Backend:**
1. Promote thiếu hoặc sai cụm xác nhận → 422, không ghi gì.
2. Promote đúng → audit có đủ trường.
3. Request ID xuất hiện trong header, log và audit.
4. Candidate bị thay thế → `can_promote: false`, lý do `SUPERSEDED`; gọi promote vẫn trả 409.
5. Fingerprint dữ liệu khác → `DATA_CHANGED`.
6. Gate exception được ghi audit như promote.

**Frontend:**
- nút ẩn hoặc vô hiệu kèm lý do;
- hộp nhập cụm xác nhận.

## Chưa làm trong batch này

Không sửa mã, không promote, không rollback, không đổi model đang dùng (`MV-20261026-105345-C73F`) hay C635.
