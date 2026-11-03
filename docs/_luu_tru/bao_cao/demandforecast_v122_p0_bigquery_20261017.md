# Demand Forecasting 1.2.2 — P0: dashboard dùng BigQuery thật, quality gate thành đánh giá, chọn ứng viên tốt nhất

Ngày 17/10/2026, 17:32–19:15 (giờ Việt Nam). Máy: PC Windows của chủ dự án. Link đã gửi sếp (giữ nguyên):
`https://volumes-jean-angels-configurations.trycloudflare.com`.

Trạng thái theo AGENTS.md §11: **READY_FOR_PRODUCTION — còn 1 thao tác của chủ dự án**. Production đã chạy 1.2.2.
Việc publish forecast BigQuery bị bộ phân loại quyền của Claude Code chặn. Chủ dự án chỉ cần bấm một nút trên máy (mục 6).

## 1. Nguyên nhân gốc (đã xác minh trên DB production, chỉ đọc)

| Hiện tượng | Nguyên nhân | Bằng chứng |
|---|---|---|
| Không có forecast BIGQUERY nào | Quality gate là **công tắc publish**: mọi lần huấn luyện BIGQUERY đều `REJECTED / QUALITY_GATE_FAILED` vì WAPE > 0,60 | `TRN-20261016095451-697A11`, `TRN-20261016103616-3FCDDB` (WAPE 1,017); `TRN-20261017101340-EEDA47` (huấn luyện thủ công 17:12, WAPE 0,807, bias +0,058 — tốt hơn baseline 0,844 / +0,124 nhưng vẫn bị chặn). Bảng `forecast_runs`: 4 lần, **cả 4 là DEMO** |
| Trang *Kết quả dự báo* hiện `DEMO`, mã `DEMO-...` | Trang mở **lần forecast mới nhất của mọi nguồn**, không lọc theo nguồn đang dùng → `FCR-20261016073246-E18059` (DEMO, 16/10) | Edge headless qua link công khai lúc 18:2x: huy hiệu DEMO và run `FCR-20261016073246-E18059`; trang Tổng quan: "Chưa có forecast nào được publish" |
| *Lịch sử Snapshot D-0* chỉ thấy DEMO | Trang mở mọi nguồn. Chưa từng có snapshot BIGQUERY: D-0 tắt, SQL chưa được xác nhận trên production | `d0_snapshots`: 17 bản, đều DEMO |
| Backend có fallback DEMO? | **Không**: chọn nguồn, huấn luyện, D-1, D-0 đều báo lỗi cụ thể khi BigQuery chưa sẵn sàng và không đổi nguồn | `data/demand.py::resolve_scope`; test `test_bigquery_not_ready_is_an_error_never_a_silent_demo_fallback` |
| D-0 vẫn "chưa xác nhận SQL" sau 1.2.1 | Lần xác nhận BigQuery hôm trước chạy trên **bản sao DB**. DB production chưa từng lưu phiên bản SQL bảng D-0 và chưa có bản ghi xác nhận (v1/v2 cũ chưa kiểm tra) | `/api/sql-sources`: `active_version_id=null`, v1/v2 `validation=null` |

**Phát hiện thêm (không do Claude làm):** lúc **17:32:20**, ánh xạ BigQuery được lưu trực tiếp trên máy, không qua link (mọi lệnh ghi qua link đều trả 405). Thay đổi: `unit_price` OPTIONAL → **REQUIRED** (audit #95).
- Theo thiết kế, việc này **tắt chế độ production BigQuery** (`production_enabled=false`).
- Hệ quả: đồng bộ D-1, huấn luyện BIGQUERY mới và D-0 dừng với `SOURCE_NOT_READY` cho tới khi bật lại.
- Dữ liệu đã nạp không bị ảnh hưởng.
- Với REQUIRED, những dòng nguồn không có giá (khoảng 0,02%) sẽ bị loại ở lần D-1 sau. Đây là quyết định của chủ dự án.

## 2. Đã sửa trong mã (1.2.2, commit cục bộ `7053999`, chưa push)

| Hạng mục | Thay đổi |
|---|---|
| Chính sách chất lượng | Cài đặt mới `quality.below_threshold_policy`: `PUBLISH_WITH_WARNING` (mặc định — dùng dữ liệu thật kèm cảnh báo) hoặc `BLOCK` (hành vi cũ). Ngưỡng 0,60 / 0,20 **không đổi**; kết quả gate vẫn báo trung thực ("không đạt") |
| Chỉ chặn vì lý do kỹ thuật | Không có dữ liệu hoặc lịch sử quá ngắn (`DATA_NOT_TRAINABLE`), dữ liệu cũ theo data_policy, không tính được forecast, BigQuery chưa sẵn sàng. Không bao giờ chuyển sang DEMO |
| Chọn ứng viên | Mỗi lần huấn luyện chấm **LightGBM (+ quy tắc dự phòng)** và **baseline trung bình 28 ngày** trên **cùng các điểm backtest walk-forward**. WAPE gộp thấp hơn thắng; bằng nhau hoặc WAPE không xác định → giữ LightGBM. Không dùng sai số trên tập huấn luyện. Lưu ứng viên được chọn, ứng viên bị loại và lý do. Baseline được publish với phương pháp `BASELINE_MOVING_AVERAGE` (giải thích được, mở rộng kỳ được, không cần file model) |
| Ba trạng thái tách biệt | Lưu theo từng lần chạy: *Kỹ thuật* (OK / FAILED), *Chất lượng* (PASS / BELOW_THRESHOLD / NOT_EVALUATED), *Độ tin cậy* (NORMAL / LOW), *Sử dụng* (USABLE / USABLE_WITH_WARNING / NOT_USABLE). Hiện ở Tổng quan, Kết quả dự báo, Hiệu năng model |
| Model đang dùng | Không bao giờ bị thay hay xóa tự động (vẫn cần duyệt). Nút **Dùng model này** nay dùng được cả cho lần huấn luyện bị chặn trước 1.2.2 chỉ vì ngưỡng, khi dữ liệu chưa đổi — không cần huấn luyện lại |
| Giao diện | *Kết quả dự báo* mở lần forecast mới nhất **của nguồn đang dùng**; run DEMO chỉ còn để đối chiếu, gắn nhãn "nguồn khác". *Tổng quan* ghi rõ "Chưa có forecast từ nguồn BIGQUERY" kèm nguyên nhân. *Snapshot D-0* mở theo nguồn đang dùng. Trang *Cấu hình* có ô chọn chính sách |
| Truy vết | Forecast run kèm nguồn dữ liệu đã dùng: bảng, cửa sổ dữ liệu, lần đồng bộ, fingerprint |
| Không thay đổi | Schema DB (3), lịch D-0 / D-1 / huấn luyện, chính sách chạy bù `SKIP`, cổng 8765/8766, proxy chỉ đọc, cấu hình Cloudflare |

## 3. Kiểm thử

| Loại | Kết quả |
|---|---|
| Backend pytest — unit + integration (fake BigQuery), kèm **BigQuery thật** (`DF_REAL_BQ=1`) | **405 passed** (QA của release, `logs\development\tests_20261017_182031.log`). Mới: `test_v122_bigquery_policy.py` (14) |
| Frontend vitest / typecheck / build | **75 passed** / OK / OK. Mới: `v122.test.tsx` (6) |
| Test cũ đổi kỳ vọng (có lý do) | 4 test kiểm tra "gate chặn publish" nay ghi rõ `below_threshold_policy=BLOCK` — hành vi BLOCK vẫn được kiểm. 2 test danh mục phương pháp thêm `BASELINE_MOVING_AVERAGE`. Không xóa assertion nào |
| Bản sao DB production + code mới + **BigQuery thật** | "Dùng model này" trên `TRN-20261017101340-EEDA47` → forecast **BIGQUERY** `FCR-…CC4CD6` trong 44,6 giây: 17.125 chuỗi, kỳ 7/15 ngày, gốc 17/10, tổng 7 ngày 624.168. Phương pháp: LightGBM 4.277 chuỗi, gián đoạn 9.627, ngừng bán 3.008, chuỗi mới 213. Dashboard và danh sách mặc định chọn đúng run này; DB thật không đổi |
| Lint | Chưa cấu hình |

## 4. Triển khai production và link

| Bước | Kết quả |
|---|---|
| Diễn tập riêng có link thật | 1.2.1 chính thức trên bản sao DB, proxy chỉ đọc chạy từ python 1.2.1 (giống production), Quick Tunnel riêng; `deploy-upgrade` lên 1.2.2. **17/17 kiểm tra đạt**: proxy và cloudflared giữ nguyên PID, URL giữ nguyên và phục vụ 1.2.2, lệnh ghi 405, trang quản trị 403, khoảng 80 giây trả 502. Tiến trình diễn tập đã dừng |
| Gói | `dist\DemandForecast-1.2.2-win64-portable.zip`, SHA-256 `7AA7D910CDC8D9B56376BC64FCC2C95DA35BAD54CD1534BE33C5F9D374150F95` |
| Deploy 18:53–18:57 | `deploy-upgrade.ps1`: prechecks đạt → `UPGRADE OK: 1.2.1 -> 1.2.2`. Backup: `backups\backup-20261017-185319-manual.zip` (SHA-256 48E9DD94…76B7) và bản `-cli` |
| Bảo toàn dữ liệu | Fingerprint trước/sau: `demand_daily` (BIGQUERY 1.349.388 dòng / 41.808.940; DEMO 38.568), mọi section cấu hình, schema, integrity **giống hệt**; chỉ `audit_log` +1. `storage.json` 8D79DBDD không đổi. data-check: WARN (chỉ meta của run DEMO cũ, có từ trước). Rollback về 1.2.1 không cần khôi phục DB (kiểm tra thử OK) |
| Backup thêm | `backups\backup-20261017-190454-manual.zip` (SHA-256 973351D3…543A) |
| Link cũ | **Giữ nguyên**: cloudflared PID 31076 và proxy PID 13024 không đổi. Poll mỗi giây qua HTTPS: 1.2.1 tới 18:55:48, **502 "ứng dụng đang tắt" ~82 giây**, 1.2.2 từ 18:57:10, sau đó không có phản hồi chậm |
| Sau deploy, qua link | `/api/health` 1.2.2. Tổng quan: "Chưa có forecast từ nguồn BIGQUERY." (không còn DEMO). Kết quả: không tự mở run DEMO. Snapshot: lọc BIGQUERY. Hiệu năng model: có hộp đánh giá. 10 lệnh ghi → 405; 6 API quản trị → 403; 0 đường dẫn Windows trong JSON; Edge headless 4 trang, 0 lỗi console |
| Ghi nhận nhỏ | `/redoc` trả trang ReDoc rỗng (có từ trước). Trang này tải `/api/openapi.json` nhưng link chặn (403), nên không lộ mô tả API. Có thể tắt `/redoc` ở phiên bản sau |

## 5. D-0 (chưa ghi gì vào production)

- **SQL** `SELECT * FROM \`lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0\` WHERE created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')`: **VALID trên BigQuery thật**, kiểm trên bản sao DB lúc 18:07.
  - Gồm dry run, kiểm ánh xạ D-0 và chạy thật tổng hợp hôm nay.
  - Kết quả: 8.454 dòng, đều là ngày 17/10; 2.142 SKU×FC; tổng 34.618; 0 dòng bị loại; khoảng 1 MB quét.
- **Khóa trùng:** 48 dòng thừa trên 39 khóa (đơn × SKU × FC × ngày); **0 dòng giống hệt nhau**.
  - Cả 39 khóa khác nhau ở giá bán; 31 khóa khác nhau ở số lượng; không khác item, sản phẩm, trạng thái hay seller.
  - Đây là các dòng đơn hàng hợp lệ, không phải bản sao do lỗi nguồn — đúng trường hợp quy tắc R1 của D-1 cộng lại (`SUM_ALL`).
  - Với chính sách hiện tại `BLOCK`, snapshot sẽ bị chặn (`BQ_KEY_NOT_UNIQUE`). Đổi sang `SUM_ALL` là quyết định của chủ dự án.
- Lịch D-0 **giữ nguyên OFF**; không chạy snapshot production.

## 6. Việc chủ dự án cần làm (theo thứ tự)

1. **Đưa forecast BigQuery lên dashboard** (khoảng 1 phút, không huấn luyện lại).
   - Trên máy chạy ứng dụng (không dùng link từ xa vì link chỉ đọc), mở `http://127.0.0.1:8765/performance`.
   - Chọn lần huấn luyện 17/10 17:13 (`MV-20261017-172653-DA47`) → bấm **Dùng model này (dưới ngưỡng — kèm cảnh báo)** → xác nhận.
   - Kết quả mong đợi (như trên bản sao): forecast BIGQUERY 17.125 chuỗi, tổng 7 ngày ≈ 624 nghìn; nhãn "Được dùng — kèm cảnh báo"; WAPE 80,7% so với ngưỡng 60%.
   - Link của sếp tự hiện forecast này.
2. **Bật lại chế độ production BigQuery** — cần trước lần đồng bộ D-1 hoặc huấn luyện tự động tiếp theo.
   - Mở trang *Kết nối BigQuery* → *Kiểm tra toàn kỳ* → *Bật production*.
   - Trước đó, quyết định giữ `unit_price` là REQUIRED hay trả về OPTIONAL.
3. **D-0** — trang *SQL nguồn & đồng bộ* → D-0:
   - lưu SQL ở mục 5 → **Xác nhận với BigQuery**;
   - chọn chính sách khóa trùng (bằng chứng ở mục 5);
   - chạy một lượt **Chạy ngay** kiểm soát (chỉ ghi `d0_snapshots`, không đụng lịch sử);
   - đạt rồi mới bật lịch D-0.
4. Huấn luyện tự động: lịch 09:00 vẫn đợi D-1 của ngày (D-1 đang tắt); chính sách chạy bù vẫn `SKIP`.
5. Push Git (`7053999` + commit tài liệu) khi đồng ý.
