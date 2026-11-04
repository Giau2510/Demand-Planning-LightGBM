# Báo cáo nghiệm thu Demand Forecasting 1.1.1 trên máy thật

- Thời điểm: 2026-10-14, 16:35 – 17:55 (giờ Việt Nam)
- Máy: Windows 11 Pro 10.0.26200 (máy đang chạy ứng dụng). **Chưa thử trên máy Windows khác.**

**Kết luận: ĐÃ NÂNG CẤP THÀNH CÔNG lên 1.1.1. Toàn bộ hạng mục A–G đạt trên ứng dụng thật với dữ liệu DEMO.**

- **Đủ điều kiện** để bắt đầu thử nghiệm với dữ liệu thật **qua Import Excel**.
- **Chưa đủ điều kiện** cho nguồn BigQuery: kết nối vẫn bị chặn, chưa nghiệm thu.
- Ngưỡng quality gate (WAPE ≤ 60%, |Bias| ≤ 20%) vẫn là **giá trị ví dụ, chưa được nghiệp vụ phê duyệt**.

---

## 1. Phiên bản và trạng thái nâng cấp

| | Trước | Sau |
|---|---|---|
| Phiên bản chạy ở `http://127.0.0.1:8765` | 1.1.0 (pid 28096) | **1.1.1** (pid 11300, `%LOCALAPPDATA%\Programs\DemandForecast\1.1.1`) |
| Schema database | 2 | **3** (migration `0003_job_stages_explainability`) |
| Thư mục chương trình | 1.0.0, 1.1.0 | 1.0.0, 1.1.0 (giữ để rollback), 1.1.1; `current.txt` = 1.1.1 |
| Scheduler | chạy | chạy (khởi động 10:35:43Z) |

Cài lúc 17:34–17:35 bằng `scripts\install.ps1` của gói, sau khi preflight đạt:
- không có job chờ/chạy;
- scheduler không có tác vụ dở;
- không có biến `DF_*` ghi đè đường dẫn;
- không có tác vụ autostart.

Installer tự dừng 1.1.0 trước khi chép file, cập nhật shortcut Desktop/Start Menu và khởi động 1.1.1.

## 2. Gói cài đặt

- `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.1-win64-portable.zip`, 101 336 734 byte.
- SHA256 `9F53FF657CEDCD63A2E7B250BFB28E9385B1F244EFA01A1969F9048120D58C5B`.
- Đã giải nén vào `release\DemandForecast-1.1.1\`. Đối chiếu: 61 file chương trình (backend, migration, giao diện, script cài đặt) trùng khớp tuyệt đối với mã nguồn đã test. 3 script chỉ dùng cho phát triển cố ý không đóng gói.
- Gói 1.1.1 build trước (SHA256 `52A79792…DE89`, nêu trong báo cáo phát triển) **chưa từng được cài ở đâu**. Gói đó được thay vì các lỗi tìm thấy khi nghiệm thu (mục 6). Tôi giữ nguyên file, chỉ đổi tên thành `DemandForecast-1.1.1-build1-superseded-win64-portable.zip`.

## 3. Backup trước nâng cấp

| File (trong `D:\Buymed\Lightgbm AI\backups`) | Tạo bởi | Kiểm tra |
|---|---|---|
| `backup-20261014-173421-manual.zip` (SHA256 `0B3A2FF2…E774`) | Tôi, qua chức năng sao lưu của 1.1.0 | Mở được (DB + 2 file mô hình). integrity ok, khóa ngoại 0, schema 2. Mọi số liệu khớp DB đang chạy. |
| `backup-20261014-173454-pre-migration-v2.zip` (SHA256 `3F172AEA…406C`) | Ứng dụng, tự động ngay trước migration | Mở được. Dữ liệu nghiệp vụ khớp. Chênh duy nhất là `audit_log` 15→16, do chính lần sao lưu thủ công ở trên. |
| `backup-20261014-173455-cli.zip` | Bước "sao lưu trước nâng cấp" của installer | Là bản **sau** migration (schema 3), xem mục 9. |

Mọi bản backup có sẵn được giữ nguyên (không xóa file nào).

## 4. Database, lưu trữ, toàn vẹn

- Database: `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`. Ứng dụng báo nguồn đường dẫn là `storage.json`.
- `storage.json`: SHA256 `8D79DBDD…E047`, **giống hệt trước nâng cấp**. Không sửa tay, không chạy `storage-repair --apply`.
- `storage_id` = marker = `6cff0821634b0447`. `storage-verify` của 1.1.1: `ok: true`, schema 3, integrity ok, khóa ngoại 0.
- Số liệu sau nâng cấp, đối chiếu chỉ đọc với trước nâng cấp:
  - 93 157 dòng đơn, 38 533 dòng nhu cầu ngày, tổng 1 015 057 — không đổi;
  - lô ACTIVE `DEMO-20261014080556-5342EB` — không đổi;
  - run `FCR-20261014080621-8D88F1` 588 dòng, tổng 10 395,456 — không đổi;
  - 1 lần huấn luyện được chấp nhận — không đổi.
- Thay đổi do nâng cấp: thêm bảng `forecast_series_meta`, thêm 1 dòng `schema_migrations`, thêm 1 dòng `audit_log`.
- Log `logs\runtime` (app.log, server.err.log) từ lúc cài: **không có ERROR hay Traceback**.

## 5. Bảng nghiệm thu A–G

Bằng chứng "E2E thật" là kịch bản trình duyệt Chrome headless điều khiển qua DevTools Protocol trên **ứng dụng thật** đã nâng cấp: bấm nút thật, chạm cảm ứng giả lập, tải Excel từ đúng link trên giao diện, chụp màn hình. Kết quả 46/46 đạt; console trình duyệt không có lỗi và không có API nào lỗi.

| # | Hạng mục | Kết quả | Bằng chứng |
|---|---|---|---|
| A1 | Bấm huấn luyện → báo tiếp nhận ngay | PASS | Khung tiến trình hiện ngay "Đang chạy · Công đoạn: Đang chờ" |
| A2 | Bước đang chạy, giờ bắt đầu, thời gian chạy, **không phần trăm** | PASS | Job thật `JOB-20261014103708-0FE2DE`: QUEUED → STARTED → VALIDATING_DATA → SKIPPED. Không có trường hay chuỗi phần trăm nào. |
| A3 | Phân biệt chờ/chạy/thành công/thất bại/bỏ qua | PASS | Thực tế đã có "Bỏ qua" và "Hoàn tất". Thất bại và không đạt chất lượng được kiểm bằng test backend/frontend. |
| A4 | Khi xong: kết quả, **giờ kết thúc**, lý do | PASS (sửa trong batch) | "Kết thúc: 2026-10-14 17:37"; "Kết quả huấn luyện: Bị bỏ qua · Kết quả publish: Không publish"; mã `NO_NEW_DATA` |
| A5 | Tải lại trang khi job đang chạy → khôi phục | PASS trên bản sao DB | Trên máy thật không có job đủ dài để thử mà không phải huấn luyện lại thật. Đã thử trên bản sao DB với huấn luyện force: sau reload khung tiến trình gắn lại, nút huấn luyện bị khóa. |
| A6 | Không tạo job trùng khi bấm liên tiếp | PASS | Bấm đúp nút huấn luyện → 1 job. Bấm đúp nút bổ sung → 1 job. |
| A7 | Hủy job | NOT APPLICABLE | Ứng dụng không có chức năng hủy job đang chạy (đã ghi trên trang Thuật toán) |
| B1 | Chọn 7 và 15 ngày | PASS | Cấu hình hiện tại [7, 15]. Run mới cho chọn 7/15. |
| B2 | Run cũ: thông báo thiếu khoảng + nút "Bổ sung khoảng dự báo" | PASS | Run `8D88F1` chỉ cho chọn "7 ngày"; thông báo nêu rõ lý do |
| B3 | Bổ sung: đủ ngày, không trùng, đúng ngày đầu/cuối | PASS | Job `JOB-20261014103641-8A59D5` (VERIFYING_MODEL → … → DONE) tạo run `FCR-20261014103642-9A7544`: 1 260 dòng = 84 chuỗi × 15 ngày, 0 trùng, 14/10 → 28/10. 588 giá trị 7 ngày đầu trùng khớp tuyệt đối với run gốc. Run gốc không đổi. |
| B4 | UI = API = truy vấn = Excel | PASS | Tổng từng SKU×FC trên bảng UI = API = sheet Tổng. 1 260 dòng sheet Chi tiết = API từng giá trị. |
| C1 | "Xem cách tính" dòng LightGBM | PASS | DEMO-SKU-008 · FC-HCM · 14/10. Có run id, model version, phương pháp, lý do, lịch sử 56 ngày, công thức `exp(1,9888 + Σ 1,9168) = 49,6819`, bảng đóng góp SHAP thật. |
| C2 | Dòng dự phòng | PASS | DEMO-SKU-023: `892 ÷ 19 = 46,947368`, làm tròn 4 số = 46,9474 = giá trị publish |
| C3 | Quy tắc làm tròn; số cuối = bảng = Excel | PASS (sửa trong batch) | Dòng "Làm tròn: max(0; x) → 4 chữ số thập phân = … · giá trị đã publish (bảng dự báo, Excel)" |
| C4 | Run cũ không lưu lý do | PASS | Hiển thị "tính lại từ cùng dữ liệu và quy tắc của lần huấn luyện" và vẫn khớp. Dữ liệu đổi → báo không tái tạo được, không bịa số (test backend). |
| C5 | Đổi ngày trong modal | PASS | "Ngày sau" → 15/10, giải thích lại và vẫn khớp |
| C6 | Giải thích ngày thứ 15 (đệ quy) của run bổ sung | PASS | Lý do lưu sẵn (STORED), tái tạo khớp, bước đệ quy 15 |
| D1 | Tooltip: di chuột, bàn phím, chạm | PASS (sửa trong batch) | Chuột: rê vào mở, ra đóng. Chạm cảm ứng (giả lập trong Chrome): chạm mở, chạm lần nữa đóng. |
| D2 | Link tới trang Thuật toán | PASS | `/methodology#method-fallback-intermittent` cuộn đúng tới mục |
| D3 | Mọi method code đang dùng đều có giải thích, ví dụ số, cách đọc | PASS | 4 mã trong kết quả (LIGHTGBM, 3 FALLBACK_*). FALLBACK_MODEL_UNAVAILABLE ghi "chỉ trong backtest". Bảng kết quả không hiện mã trần. |
| E1 | Excel vi/en: sheet, cột, phương pháp, trạng thái, chú thích | PASS | vi: Thông tin / Tổng 15 ngày / Chi tiết theo ngày. en: Info / Totals 15d / Daily. |
| E2 | Ngày/giờ theo ngôn ngữ | PASS (sửa trong batch) | Ngày là ô ngày Excel: `DD/MM/YYYY` (vi), `YYYY-MM-DD` (en). "14/10/2026 17:36 (giờ Việt Nam, UTC+7)". |
| E3 | Mã định danh không bị dịch; số khớp UI | PASS | Run id, model version, SKU, FC giữ nguyên; số khớp UI/API |
| F1 | Thực tế trong ngày, giờ cập nhật, giờ VN | PASS (sửa nhãn trong batch) | "tính đến 2026-10-14 16:00 (giờ VN) (Đang cập nhật trong ngày)" + cảnh báo "chưa phải tổng cả ngày" |
| F2 | DEMO được đánh dấu | PASS | Nhãn DEMO + "(dữ liệu mô phỏng, không phải thực tế kinh doanh)" |
| F3 | Chỉ ngày hôm nay có giá trị; tương lai trống | PASS | UI, API và cả hai file Excel |
| F4 | Không cộng trùng nhiều snapshot trong ngày | PASS | Mục 5a: dữ liệu thật (chỉ đọc), test tự động, bản sao DB |
| F5 | Bộ lọc áp dụng cho thực tế | PASS | Lọc FC-HCM: API 508 = tính tay từ snapshot 508 |
| F6 | Chưa có dữ liệu → "chưa có dữ liệu", không lấy forecast thay | PASS (test) | Trạng thái `NO_DATA_TODAY`, ô trống (test backend, frontend) |
| G1 | Trang Thuật toán: tách nhóm | PASS (sửa trong batch) | 7 nhóm: quy trình; feature; thuật toán & phương pháp dự báo; phương pháp đánh giá; quy tắc chất lượng dữ liệu; quy tắc chất lượng mô hình & publish; quy tắc vận hành |
| G2 | LightGBM, Tweedie, backtest, quality gate, WAPE/MAE/Bias/MAPE, baseline, fallback | PASS | Mỗi mục có mục đích, đầu vào, các bước, công thức, ví dụ số, ý nghĩa, giới hạn. Ngưỡng đọc trực tiếp từ cấu hình. Ví dụ số được test tính lại bằng mã thật. |
| G3 | Không mô tả tính năng không tồn tại | PASS | Ghi rõ: không có hủy job, không có lịch khuyến mãi tương lai, không có dữ liệu tồn kho |
| — | Các trang khác: Chất lượng mô hình, Snapshot D0, Import, Lô import, Chất lượng dữ liệu, Cấu hình, Hệ thống & sao lưu | PASS | Hiển thị không có hộp lỗi; ảnh chụp lưu lại |

### 5a. Không cộng trùng khi có nhiều snapshot trong cùng ngày

Quy tắc: snapshot D0 là số **lũy kế**. Thực tế trong ngày lấy **duy nhất snapshot thành công mới nhất** của đúng bộ dữ liệu trong ngày VN hiện tại; không bao giờ cộng các snapshot với nhau. Kiểm chứng bằng ba lớp, không sửa hay xóa dữ liệu thật:

| Lớp | Cách làm | Kết quả |
|---|---|---|
| 1. Dữ liệu thật có sẵn, **chỉ đọc** | DB thật có lô `DEMO-20261014042925-CB692D` với 2 snapshot thành công ngày 14/10: 05:00Z (61 dòng, tổng 549) và 07:00Z (63 dòng, tổng 907). Chạy chính hàm `actual_today`/`value_for` của 1.1.1 trên kết nối `mode=ro`. | **9/9 PASS.** Dùng snapshot 07:00Z; tổng **907** (cộng trùng sẽ là 1456). Từng SKU×FC = giá trị lũy kế mới nhất. Ngày tương lai trống. Thời điểm = giờ đọc thật 07:00:22Z, không phải "bây giờ". Đọc sau 5 giờ → "Có thể đã cũ", giữ nguyên thời điểm. Ngày VN kế tiếp → "chưa có dữ liệu". |
| 2. Regression test tự động | `test_two_snapshots_same_day_are_never_added_together`: hai lần đồng bộ D0 lúc 10:05 và 12:05 cùng ngày, kiểm tổng hệ thống, từng dòng bảng tổng, bảng theo ngày, bảng chi tiết và cột thực tế trong Excel | PASS. Kiểm đột biến: cho mã lấy snapshot cũ nhất thì test **thất bại**, nên test bắt được lỗi thật. |
| 3. Bản sao DB thật, chạy mã 1.1.1 | Lô đang hoạt động `5342EB`: 1 snapshot thật (16:00 VN, 1204) + 2 lần đồng bộ D0 mới trên **bản sao** (cổng 8879) = 3 snapshot trong ngày | PASS. API tổng = tổng các dòng bảng = bảng chi tiết = Excel = **1343** (snapshot mới nhất). Cộng trùng sẽ là 3890. 0 dòng tương lai có giá trị. |

**Chưa kiểm chứng trên dữ liệu thật:** snapshot D0 lúc 18:00 do **scheduler 1.1.1** tự tạo cho lô đang hoạt động `5342EB`. Lúc phát hành báo cáo, lô này mới có 1 snapshot thật (16:00 VN, do 1.1.0 tạo). Quy tắc lấy snapshot mới nhất đã được chứng minh ở ba lớp trên. Việc scheduler 1.1.1 chạy đúng mốc 18:00 trên máy thật thì chưa được quan sát.

## 6. Lỗi tìm thấy khi nghiệm thu, nguyên nhân, cách sửa, regression test

Tất cả được tìm thấy **trước khi cài lên máy thật**, khi chạy mã nguồn trên bản sao DB thật với E2E trình duyệt. Gói build1 vì vậy không được cài.

| # | Lỗi | Nguyên nhân gốc | Sửa | Regression test |
|---|---|---|---|---|
| 1 | Sau khi bổ sung khoảng, trang Kết quả kẹt "Đang tải…" | Tải lại danh sách run thay cả trang bằng "Đang tải…". Khung tiến trình bị gỡ rồi gắn lại, gọi `onDone` lần nữa, gây vòng lặp. | Chỉ hiện "Đang tải…" khi chưa có dữ liệu (`Results.tsx`, `Performance.tsx`) | `v111.test.tsx` "no reload loop" (có độ trễ mạng). Đã xác nhận test **lỗi trên mã cũ**, đạt trên mã mới. |
| 2 | Tooltip phương pháp/thuật ngữ đóng ngay khi chạm trên màn hình cảm ứng | Chạm sinh ra focus (mở) rồi click (đảo trạng thái → đóng) | Hook dùng chung `useTooltip`: chuột rê để mở; click/chạm quyết định theo trạng thái lúc nhấn; Enter/Space/Esc | Test chạm/chuột (frontend) + E2E chạm thật trong Chrome |
| 3 | Excel ghi giờ dạng ISO UTC, ngày là chuỗi, không theo ngôn ngữ | Thiết kế v2 chỉ dịch nhãn | Định dạng v3: ngày là ô ngày Excel theo ngôn ngữ; giờ chạy và giờ đọc thực tế theo giờ VN (giữ bản UTC) | `test_excel_follows_ui_language_and_keeps_numbers` mở rộng |
| 4 | Khung job không hiện giờ kết thúc | Thiếu trường | Thêm "Kết thúc" | Test JobProgress |
| 5 | "Xem cách tính" không nêu quy tắc làm tròn | Thiếu | Dòng "Làm tròn: max(0; x) → 4 chữ số = … = giá trị publish" | E2E đối chiếu số trong modal với bảng |
| 6 | Thời điểm thực tế không ghi múi giờ | Thiếu nhãn | "(giờ VN)" ở Tổng quan và Kết quả | E2E |
| 7 | Trang Thuật toán: chưa tách quy tắc vận hành/chất lượng dữ liệu; chưa có mục Tweedie; method code chưa có ví dụ số và cách đọc | Thiếu nội dung | Thêm 2 nhóm, mục Tweedie, mục Job/lịch/thử lại; thêm `example` và `read` cho 5 method code trong registry | `test_method_registry_examples_are_computed_by_the_code`, `test_documented_examples_are_correct` (Tweedie 4^1,2, thử lại 60/120/240 s), test trang |

## 7. Kết quả kiểm thử

| Bộ | Kết quả |
|---|---|
| Backend pytest (`logs\development\tests_20261014_175059.log`) | **120 đạt**, 0 lỗi, 0 bỏ qua (gồm test hai snapshot mới) |
| Frontend vitest | **21 đạt** |
| Typecheck `tsc -b` / production build | Đạt / Đạt |
| Lint/format | Không có công cụ được cấu hình trong dự án |
| Gói cuối, cô lập: cài mới (smoke chung + kiểm tra 1.1.1) | 24/24 + 30/30 |
| Gói cuối, cô lập: nâng cấp trên bản sao DB thật | 13/13 |
| E2E trình duyệt, mã nguồn trên bản sao DB thật (có huấn luyện force) | 48/48 |
| **E2E trình duyệt trên ứng dụng thật sau nâng cấp** | **46/46** |
| Kiểm tra chéo chỉ đọc trên DB thật (mục 4, B3, C6, F5) | Đạt |
| Không cộng trùng snapshot (mục 5a): dữ liệu thật chỉ đọc / bản sao DB | 9/9 / Đạt |

## 8. Tác động lên dữ liệu thật do nghiệm thu

Chỉ có các thao tác sau, đều nằm trong phạm vi yêu cầu (kiểm tra mục 5a chỉ đọc DB thật, không ghi):
- 1 job bổ sung khoảng `JOB-20261014103641-8A59D5`. Kết quả: run mới `FCR-20261014103642-9A7544`, nay là lần dự báo mới nhất trên Tổng quan. Run cũ vẫn còn, không đổi.
- 1 lần bấm huấn luyện (không force) `JOB-20261014103708-0FE2DE`. Dữ liệu không đổi nên bỏ qua: không huấn luyện lại, không model mới.
- 1 bản sao lưu thủ công cùng 1 dòng audit.
- Không tạo lô DEMO mới, không đổi nguồn đang hoạt động, không đổi cấu hình.
- Regression test mới chỉ thêm vào mã nguồn test, không thay đổi mã ứng dụng. Gói đã cài vẫn là gói đã được kiểm thử (SHA256 `9F53FF65…8C5B`).

## 9. Giới hạn và rủi ro còn lại

- **BigQuery:** chưa nghiệm thu (kết nối bị chặn). Thực tế trong ngày mới kiểm chứng với DEMO mô phỏng.
- **Scheduler 1.1.1 trên máy thật:** chưa quan sát một mốc lịch tự động nào (D0 18:00, huấn luyện 07:00). Scheduler đã khởi động và đang chạy; các lần đồng bộ thủ công trên bản sao DB đều thành công. Có thể kiểm tra lần chạy 18:00 ở trang *Job & Scheduler*.
- **Máy Windows khác:** chưa thử.
- **Thiết bị cảm ứng thật:** chưa thử. Chạm đã được kiểm bằng giả lập cảm ứng của Chrome.
- **Bước sao lưu của installer:** "sao lưu trước nâng cấp" chạy bằng Python của gói mới, nên migration xảy ra ngay trong bước này. Bản `-cli.zip` vì vậy là bản sau migration. An toàn dữ liệu vẫn được bảo đảm nhờ bản `pre-migration-v2` (đã kiểm tra) và bản sao lưu độc lập. Đây là hành vi có từ trước batch này; nên sửa ở bản sau để bản sao lưu của installer là bản trước migration.
- **Quay lại 1.1.0:** 1.1.0 không mở được schema 3. Quy trình đã kiểm thử trước đó: dừng app → khôi phục `backup-20261014-173454-pre-migration-v2.zip` bằng `scripts\restore.ps1` của 1.1.0 → chạy 1.1.0. Các thứ phát sinh sau nâng cấp sẽ mất: run bổ sung `9A7544`, 2 job nghiệm thu, các snapshot D0 từ 18:00.
- **Giải thích và bổ sung khoảng:** cần dữ liệu không đổi kể từ lúc huấn luyện. Khi dữ liệu thay đổi (import mới, đồng bộ D-1), run cũ chỉ còn kết quả và lý do đã lưu; muốn có khoảng mới thì phải huấn luyện mới.
- **Đóng góp SHAP** tính ở thang log; đọc như mô tả mô hình, không phải nhân quả.
- **Ô chọn ngày** trong modal hiển thị theo locale của trình duyệt.
- **Tài liệu trong gói:** `docs\MO-HINH-VA-CHI-SO.md` bên trong gói vẫn ghi "định dạng Excel phiên bản 2". Bản trong mã nguồn đã sửa thành 3. Ứng dụng không bị ảnh hưởng.

## 10. Hướng dẫn sử dụng ngắn

1. Mở **Demand Forecasting** từ shortcut trên Desktop (đã trỏ sang 1.1.1) hoặc vào `http://127.0.0.1:8765`.
2. **Tổng quan:** bấm *Huấn luyện & dự báo ngay*. Khung trạng thái cho biết bước đang chạy, giờ bắt đầu, giờ kết thúc và kết quả. Dữ liệu không đổi thì hệ thống tự bỏ qua.
3. **Kết quả dự báo:** chọn lần dự báo và khoảng 7/15 ngày.
   - Lần dự báo cũ thiếu khoảng: bấm *Bổ sung khoảng dự báo*.
   - Ở mỗi dòng: bấm *Xem cách tính* để xem số được tính ra sao.
   - Rê chuột hoặc chạm vào tên phương pháp để xem giải thích.
4. **Cột "Thực tế hôm nay":** là số đặt hàng lũy kế đến lần cập nhật gần nhất (giờ VN), chưa phải số cả ngày. Ngày tương lai để trống.
5. **Xuất Excel:** file theo ngôn ngữ đang chọn (nút *English/Tiếng Việt* góc trên phải).
6. **Thử với dữ liệu thật:** vào *Import dữ liệu lịch sử* → tải file mẫu → nhập file Excel thật → xác nhận → ở ô *Nguồn đang hoạt động* chọn *MANUAL_IMPORT — dữ liệu import Excel* → huấn luyện. Dữ liệu DEMO không bị mất.

## 11. Việc người dùng cần làm tiếp

- Không bắt buộc thao tác kỹ thuật nào.
- Khi muốn thử dữ liệu thật: làm theo mục 10.6.
- Cần quyết định nghiệp vụ về ngưỡng quality gate (hiện là giá trị ví dụ).
- Cung cấp quyền truy cập BigQuery khi muốn nghiệm thu nguồn này.
