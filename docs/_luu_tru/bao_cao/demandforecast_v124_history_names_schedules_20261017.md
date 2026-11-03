# DemandForecast 1.2.4 — lịch sử forecast, tên sản phẩm + tìm kiếm, công tắc D-0/D-1 (17/10/2026, 20:55–)

Giờ Việt Nam (UTC+7) trừ khi ghi UTC. Chỉ id, số đếm, hash; không có bí mật. Trạng thái: **READY_FOR_PRODUCTION**
(đã deploy và xác minh trực tiếp trên production).

## 1. Hiện trạng trước khi sửa (20:55)

* Production 1.2.3 (app pid 24100), proxy chỉ đọc pid 13024, cloudflared pid 31076, link
  https://volumes-jean-angels-configurations.trycloudflare.com trả 1.2.3. Git sạch tại aaecb52 (local, chưa push).
* Forecast `FCR-20261017123417-FCC0EB` (BIGQUERY), model TRN-20261017101340-EEDA47; `production_enabled=true`;
  D-1 TẮT, D-0 TẮT, huấn luyện BẬT 09:00 (SKIP).

## 2. "Forecast được tạo ra như thế nào?" và "Lịch sử demand và xuất Excel"

**Nguyên nhân (đã xác minh trên production):** API giải thích của forecast hiện tại trả `reproduction=DATA_CHANGED`,
`history=DATA_CHANGED`, `lightgbm=DATA_CHANGED` (chuỗi MEDX.DMTS-SAN-ALP-001 / HN). Phép kiểm tra "dữ liệu còn như lúc
huấn luyện" dùng `demand.fingerprint` = (số dòng, tổng, ngày đầu, ngày cuối, **MAX(loaded_at)**). Lần D-1 chạy tay
19:58 (tôi chạy theo yêu cầu P0 trước) nạp lại toàn kỳ: ghi lại 1.349.388 dòng **giá trị y hệt** (0 mới / 0 cập nhật /
0 xóa) nhưng `loaded_at` mới → fingerprint đổi → hai khu vực bị khóa. Phần "Phương pháp" vẫn hiện (metadata lưu lúc
publish).

**Bằng chứng dữ liệu không đổi:** bản sao DB lúc 19:37 (trước D-1) có fingerprint `e2385893ed061e39` = đúng fingerprint
lưu của TRN-…EEDA47; hash nội dung (9 cột mô hình đọc: ngày, SKU, FC, qty, n_orders, giá, giảm giá, khuyến mãi, voucher;
không có loaded_at) của bản sao đó và của DB live hiện tại **bằng nhau** `c47771523275a866…` trên 1.349.388 dòng
01/01–16/10.

**Cách sửa (1.2.4):** danh tính nội dung (`data/identity.py`): SHA-256 của giá trị mô hình đọc, theo ngày và theo cửa
sổ, không dùng loaded_at. Mỗi lần huấn luyện mới lưu danh tính của đúng cửa sổ dữ liệu nó dùng
(`feature_config_json.data_identity`). Giải thích (cách tạo forecast, lịch sử + Excel, trace TreeSHAP, điểm backtest)
chấp nhận dữ liệu khi fingerprint không đổi **hoặc** nội dung cửa sổ trùng khớp (`SAME_CONTENT`); nếu một ngày trong
cửa sổ thay đổi → `CHANGED` kèm tên ngày, không tái tạo, không ước đoán; lần huấn luyện cũ không có danh tính →
`UNVERIFIABLE` (thông báo cũ được giữ). Run cũ chỉ có danh tính qua **xác thực từ backup** mà fingerprint trùng
fingerprint lưu của run (`app.cli attest-training-data`, ghi một lần, có audit). Không lưu bản sao dữ liệu đầu vào cho
mỗi lần chạy (chỉ hash ~10 KB/run). Hiệu năng: panel của run dựng một lần cho mọi chuỗi (khóa theo hash nội dung).

**Production:** TRN-…EEDA47 được xác thực từ `backup-20261017-193147-manual.zip` (fingerprint backup `e2385893ed061e39` =
fingerprint huấn luyện) → danh tính `cbd943c0…e3cf` (289 ngày, 1.349.388 dòng), dữ liệu live `SAME_CONTENT`. Giải thích
3 chuỗi: tái tạo OK, lịch sử 60 ngày, đóng góp LightGBM = giá trị publish (1682,8637 / 2448,0858 / 3010,6012); lần đầu
33,8 s, sau đó ~8,5 s; qua link 7,7 s và 8,7 s; Excel lịch sử qua link 200. Giao diện hiển thị dòng "Dữ liệu đã được nạp
lại sau lần huấn luyện, nhưng giá trị … đã được xác minh TRÙNG KHỚP (SHA-256 …) — (xác lập từ bản backup …)".

**Giới hạn:** chỉ tái tạo được khi giá trị trong cửa sổ huấn luyện không đổi; D-1 tra lại 3 ngày gần nhất (late data) —
nếu nguồn sửa số của các ngày đó, giải thích của forecast cũ sẽ báo đúng ngày thay đổi và không hiển thị.

## 3. Tên sản phẩm, tìm kiếm, Excel

* Nguồn: `lakehouse-prod-394907.gold_buymed_vn2.dim_sku` (bảng D-1 không có tên). Kiểm tra thật: 298.517 dòng =
  298.517 `sku_code` khác nhau, 0 tên rỗng → khóa duy nhất, không thể nhân bản dòng. Ánh xạ là từ điển SKU → 1 tên; SKU
  có nhiều tên trong nguồn → không gán (0 trường hợp); SKU không có → "Chưa có tên sản phẩm".
* Production 23:04: đọc 298.517 dòng (22,9 MB), **9.657 / 9.657 SKU có tên**, 0 mơ hồ. Tự làm mới sau mỗi D-1 thành công
  (lỗi đọc tên không làm hỏng D-1).
* Số dòng trước/sau: 17.125 chuỗi, tổng 7 ngày 624.167,85 — **không đổi**; Excel 119.875 dòng chi tiết = 17.125 × 7.
* Tìm kiếm (`q`): một phần SKU hoặc tên, không phân biệt hoa/thường, **không dấu** ("ho tro gan" = "Hỗ trợ gan"), nhiều
  từ = tất cả phải khớp; kết hợp bộ lọc FC/SKU; tổng và phân trang theo đúng bộ lọc; không có kết quả → thông báo rõ;
  xóa từ khóa → toàn bộ. Qua link: "simarin" 1 chuỗi, "ho tro gan"+HN 22, "MEDX.DMTS-SAN" 12, từ không tồn tại 0 (<1 s).
* Excel forecast (định dạng 5): cột "Tên sản phẩm" ngay sau SKU, sheet Thông tin ghi nguồn + giờ đọc tên; Excel vẫn
  xuất **toàn bộ** lần dự báo như trước (không theo bộ lọc — hành vi cũ giữ nguyên).

## 4. D-1, D-0 và công tắc

| Luồng | Trạng thái thực tế | Giờ / múi giờ | Lần chạy kế tiếp |
|---|---|---|---|
| D-1 | **BẬT**, scheduler đã nạp (`ON`) | bắt đầu 03:00, fallback 06:00, Asia/Ho_Chi_Minh; chỉ ngày đã đóng | 18/10/2026 03:00 |
| D-0 | **BẬT**, scheduler đã nạp (`ON`) | 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, Asia/Ho_Chi_Minh; chỉ hôm nay | 18/10/2026 08:00 |

* Bật qua API chính thức (kiểm tra readiness: production, validation, SQL D-0 v3 đều đạt); thử tắt → bật lại từng luồng:
  mỗi lần đọc lại trạng thái đã lưu và trạng thái scheduler đều khớp; settings lưu bền trong DB (scheduler đọc mỗi lượt,
  khởi động lại khôi phục — test `test_v118::test_restart_restores_the_saved_state`, `test_v124…`). Bật lúc 23:06 → các
  mốc trước đó không chạy bù; không có job nào phát sinh.
* Trang Job & Scheduler: công tắc riêng D-1 / D-0, chỉ hiển thị trạng thái backend đã lưu; lỗi → giữ trạng thái + báo
  lỗi; qua link chỉ đọc: hiển thị BẬT nhưng không bấm được (proxy cũng trả 405).
* Lưu ý: luồng huấn luyện vẫn BẬT 09:00 (từ trước). Từ sáng 18/10, nếu D-1 thành công, huấn luyện sẽ chạy và tạo **ứng
  viên chờ duyệt** (model đang dùng không bị thay tự động).
* D-1 không có bảng tín hiệu hoàn tất: job 03:00 chờ đến 06:00 rồi kiểm tra đủ dữ liệu ngày hôm qua (≥ 50 % trung bình 7
  ngày); nếu nguồn chưa đủ sẽ thử lại theo cơ chế sẵn có.

## 5. Kiểm thử

| Bộ | Kết quả | Loại |
|---|---|---|
| Backend pytest (release QA) | 418 PASS, 0 FAIL, 7 SKIP (BigQuery thật) | tích hợp, DB tạm + BigQuery giả |
| BigQuery thật (`DF_REAL_BQ=1`) | 7/7 PASS | dịch vụ thật, chỉ đọc |
| Frontend vitest | 86/86 PASS | unit (jsdom) |
| Typecheck / build | OK / OK | |
| Diễn tập nâng cấp (bản sao + tunnel riêng) | 34/34 PASS | cài đặt cách ly, BigQuery thật cho tên |
| Kiểm tra qua link production | 23/23 PASS; Edge 5 trang 0 lỗi | production |
| Lint | không cấu hình | — |

Test mới: `test_v124_history_names_schedules.py` (13), `v124.test.tsx` (6). Kỳ vọng đổi có lý do: vị trí cột Excel trong
`test_v111` / `test_v112` +1 (chèn "Tên sản phẩm" sau SKU, định dạng 5) — không bỏ assertion nào; thêm assertion tên
"Chưa có tên sản phẩm" cho DEMO. Cách ly DB test: mọi lần chạy, lịch sử settings production không đổi (id 32 / 25).

## 6. Production, dữ liệu, an toàn

* Phiên bản: trước 1.2.3 → sau **1.2.4** (`current.txt`, health nội bộ + qua link), app pid 35168.
* Link: **giữ nguyên URL**; proxy pid 13024 và cloudflared pid 31076 không đổi; gián đoạn **~130 s** (22:56:47–22:58:58)
  khi khởi động lại app.
* Backup: `backup-20261017-225247-manual.zip` (SHA-256 7190A5461C81…E13E4) + `backup-20261017-225648-cli.zip`.
* Thay đổi DB production: settings `schedule` (D-1/D-0 BẬT; 6 lần lưu gồm thử tắt/bật), `sync_state`
  `training_data_identity:TRN-20261017101340-EEDA47` + `product_names`, audit +15. `demand_daily`, forecast, model,
  snapshot, job cũ: **không đổi** (fingerprint). Không có job / training / forecast mới. data-check WARN (meta DEMO cũ).
  storage.json 8D79DBDD… không đổi. Rollback `-To 1.2.3 -CheckOnly`: OK, không cần khôi phục DB.
* Git: commit cục bộ addbfb9, 1750f8d, 3f35975 (cùng 7053999, 2ea4085, 87f6fce, aaecb52) — **không push**; cây sạch.
* Gói 1.2.4 đầu tiên (D2A13503…, commit addbfb9) chỉ dùng diễn tập, được giữ dưới tên `…-superseded-20261017-223024`.

## 7. Còn lại

* Push các commit cục bộ khi chủ hệ thống đồng ý.
* Gói superseded và các gói cũ trong `dist\`: dọn bằng `scripts\prune-artifacts.ps1 -Apply` khi chủ hệ thống quyết.
