# Nhóm feature Giá — quyết định bật, xác minh và kế hoạch thử nghiệm (17/10/2026)

**Trạng thái phát hành: `PARTIAL`**
- Mã nguồn, test và tài liệu cho giá đã xong.
- Chưa commit, chưa build, chưa diễn tập, chưa deploy 1.2.0.
- Production chưa có dữ liệu giá và chưa có model nào học từ giá.

## 1. Quyết định

Chủ dự án yêu cầu nhóm Giá **bật** trong cấu hình phát hành (`model.feature_price = true`, lưu tường minh). Quyết định này
thay thế chỉ dẫn trước đó trong batch (giữ Giá tắt).
- Metric xấu đi không tự động tắt nhóm Giá.
- Mọi thay đổi trái với quyết định này phải chờ chủ dự án phê duyệt.

## 2. Giá đã bật ở những tầng nào

Thời điểm kiểm tra: 01:10–01:40 ngày 17/10/2026. Nguồn của cột production 1.1.9: các lệnh API GET chỉ đọc. Nguồn của cột bản 1.2.0: test và bản sao cô lập.

| Tầng | Production 1.1.9 (đang chạy) | Bản 1.2.0 (chưa commit) | Bằng chứng |
|---|---|---|---|
| UI (Cấu hình → Nhóm feature → Giá) | Công tắc bật | Công tắc bật; cảnh báo khi bật mà nguồn không có giá | `frontend/src/v120.test.tsx` |
| Config (`app_settings.model`) | `feature_price = true`, nhưng **chỉ là mặc định của code**: mục `model` chưa từng được lưu (lịch sử 0 bản ghi) | Bước phát hành lưu tường minh `feature_price = true`, `forecast_strategy = DIRECT` | `GET /api/settings`, `GET /api/settings/model/history` |
| Mapping nguồn | `unit_price` **chưa ánh xạ** (column = null) | Ánh xạ `unit_price ← sales_price` qua `POST /api/bigquery/mapping` | `GET /api/settings` |
| Dữ liệu (`demand_daily.avg_unit_price`) | Độ phủ **0,0** | Bản sao sau khi nạp lại: độ phủ 99,98 % | registry; `price_verify.json` |
| Feature registry | `used = false`, lý do `NO_DATA`: lần huấn luyện kế tiếp **không** có giá | `DATA_OK`, `price_last` và `price_rel_28` có trong danh sách feature | `GET /api/features/registry`; bản sao |
| Training | Không có model nào học từ giá; phạm vi BIGQUERY chưa có model được chấp nhận | Lần chạy ghi `feature_groups.price = {switch_on: true, used: true}`; file model có 2 feature giá; cây có tách theo giá | `test_v120_price.py` |
| Inference (dự báo, kéo dài, giải thích) | — | Dựng lại từ cấu hình đã lưu của lần chạy; đọc giá cuối đã biết; giải thích ghi nguồn *thực tế* | `test_v120_price.py` |
| Release | Chưa | Chưa | — |

**Kết luận:** chỉ bật công tắc thì chưa đủ. Phải nạp dữ liệu giá thì lần huấn luyện phát hành mới thật sự dùng giá.
Production hiện chưa đủ điều kiện, nên không được nói rằng model đã học từ giá.

## 3. Đường đi cấu hình (đã đọc code)

1. **UI.** `Config.tsx` → `PUT /api/settings/model` → `settings_service.save` (có kiểm tra và giữ lịch sử).
   - Không đổi được cả ba nhóm thành tắt (`FEATURE_GROUPS_EMPTY`).
   - Lưu mục khác, khởi động lại hoặc chạy D-1 đều không động tới mục `model`.
2. **Nạp dữ liệu (BigQuery D-1).**
   - `connector._daily_sql` tính `SAFE_DIVIDE(SUM(unit_price × SL), SUM(IF(unit_price IS NULL, NULL, SL)))`.
   - Ngày-chuỗi không có giá → `NULL`, không bao giờ là 0.
   - `sync.run_d1_sync` ghi vào `demand_daily.avg_unit_price`.
3. **Training.** `pipeline.train_and_publish` → `feature_registry.coverage` (trên toàn phạm vi) → `resolve`: bật và độ phủ
   ≥ 0,5 thì `used`.
   - Cấu hình **đã quyết định** được lưu trong `feature_config_json.config`, cùng `feature_groups`, `feature_decisions`
     và `settings_switches`.
   - `_save_model` ghi danh sách feature vào file meta.
4. **Feature.**
   - `build_panel`: giá → ma trận S×T, lấy giá ngày có giá gần nhất cho ngày không có đơn; trước giá đầu tiên là NaN.
   - `features_at` / `origin_features`: `price_last = price[t0−1]`, `price_rel_28 = price_last / mean(price[t0−28..t0−1])`.
   - Chỉ dùng các cột trước t0.
5. **Inference.** `extend_forecast`, `release_with_gate_exception` và `explain` đều dựng `ModelSettings` từ
   `feature_config_json.config` của lần chạy. Model giữ đúng danh sách feature của nó.

## 4. Test chứng minh giá thật sự được dùng

Đều là test đơn vị / tích hợp với BigQuery giả, không phải BigQuery thật.

`backend/tests/test_v120_price.py` (3 test, đạt):
- **Giá vào `demand_daily`.**
  - Sau khi ánh xạ `unit_price ← sales_price`, SQL nạp có biểu thức giá; khi chưa ánh xạ thì là `CAST(NULL ...)`.
  - Mapping hash đổi nhưng phạm vi dữ liệu giữ nguyên.
  - Giá thiếu được lưu là NULL. Registry trả `DATA_OK`.
  - Chạy D-1 không làm thay đổi cấu hình model.
- **Huấn luyện DIRECT học từ giá.**
  - Lần chạy ghi `price {switch_on: true, used: true}`.
  - File model và file meta có `price_last` và `price_rel_28`; số lần tách cây theo giá > 0.
  - Dự báo đọc đúng giá cuối đã biết. Đổi giá cuối thì dự báo đổi; đổi giá cũ hơn không làm thay đổi `price_last`.
  - Phần giải thích tái lập đúng số đã publish, với `price_last` là đầu vào *thực tế*.
  - **Đối chứng:** cùng dữ liệu nhưng tắt giá thì đổi giá không làm dự báo thay đổi.
- **Công tắc giữ trạng thái bật** sau khi lưu mục khác, đổi mapping BigQuery và khởi động lại app.
  - Settings do 1.1.9 ghi (thiếu các trường 1.2.0) được đọc đúng như đã lưu (true vẫn là true, false vẫn là false) và
    không bị ghi lại.

`test_v120_features.py`:
- `test_price_features_never_read_the_origin_day_or_later`: giá từ t0 trở đi bị thay bằng 9e9 mà feature tại t0 không
  đổi (cả RECURSIVE và DIRECT).
- `test_price_on_without_price_data_is_left_out_and_recorded`: bật mà không có dữ liệu thì không dùng và có ghi lại.
- `test_feature_group_switches_decide_the_trained_features`.

Nâng cấp phiên bản trên gói thật sẽ được kiểm ở bước diễn tập cô lập `iso120.ps1`:
- settings không đổi qua deploy;
- lưu mapping;
- kiểm tra toàn kỳ;
- nạp lại toàn kỳ;
- huấn luyện có giá.

Bước này **chưa chạy**.

## 5. Dữ liệu giá thật

Bản sao cô lập (`price_verify.py` trong thư mục này, mở DB chỉ đọc; BigQuery thật lúc nạp):

| Kiểm tra | Kết quả |
|---|---|
| Nạp lại 01/01–15/10 | Đọc 8.893.414 dòng → 1.347.346 ngày × SKU × FC; **cả 1.347.346 không đổi số lượng**; mới/sửa/mất = 0; tổng 41.722.635 |
| Độ phủ giá | 99,982 % (239 ngày-chuỗi NULL; 83 ngày-chuỗi bình quân = 0; không có giá âm) |
| Kiểu dữ liệu | REAL cho mọi giá trị khác NULL |
| Tại mốc dự báo 16/10 | `price_last` có cho 100 % trong 17.137 chuỗi, đúng bằng giá cuối đã biết |
| `price_rel_28` | Phân vị 1 %, 25 %, 50 %, 75 %, 99 % = 0,869 / 1,000 / 1,000 / 1,010 / 1,272 |
| Biến động | Trung vị 37 % số ngày có giá đổi > 1 % so với ngày có giá trước đó (do cơ cấu đơn, xem §6) |

`sales_price` là **đơn giá** của dòng đơn, không phải thành tiền. Kiểm tra ngày 16/10: trung vị 105.100 khi SL ≤ 1, 41.100 khi
SL 6–20.

## 6. Giới hạn dữ liệu và rủi ro rò rỉ còn lại

- **Không rò rỉ theo thời gian.**
  - Feature giá chỉ dùng ngày trước t0.
  - Giá ngày D có trong nguồn vào khoảng 12:00–14:10 ngày D+1 và được nạp cùng số lượng của ngày D, nên tại t0 giá của
    t0−1 đã biết.
  - Không dùng giá kế hoạch hay giá tương lai.
- **Giá thực bán, không phải giá niêm yết.**
  - Trong cùng SKU × FC × ngày có trung bình 5,6 mức giá.
  - Giá bình quân theo số lượng phụ thuộc vào cơ cấu đơn: đơn lớn thường có giá thấp hơn, nên giá bình quân và số lượng
    có quan hệ ngược chiều.
  - Đây là nguồn nhiễu, có thể là lý do 2 feature hiện có không giúp ích.
- **Chỉ biết giá vào ngày có đơn.** Giá đổi trong những ngày không bán được thì không quan sát được (phải lấy giá ngày
  trước).
- **83 ngày-chuỗi có giá bình quân = 0.** Đây là dữ liệu nguồn và được giữ nguyên. Cần quy tắc nghiệp vụ (hàng tặng?)
  trước khi coi là thiếu.
- **Không có lịch sử theo đúng thời điểm.** Backtest dùng giá theo lần nạp mới nhất. Số lượng cũng vậy.
- **Khoảng trống lịch D-1.**
  - D-1 lúc 03:00 sẽ thất bại vì ngày hôm qua chỉ có trong nguồn sau khoảng 12:00 (rủi ro vận hành đã báo).
  - Không có dữ liệu mới thì cả giá lẫn số lượng đều cũ một ngày.

## 7. Metric backtest (giữ nguyên số đo)

Điều kiện: bản sao, 01/01–15/10/2026, 7 fold, 3.353.298 điểm, DIRECT, cùng tập điểm và cùng baseline.

| | WAPE | Bias | MAE | Thời gian |
|---|---|---|---|---|
| Chỉ nhu cầu | 0,805953 | +0,068976 | 6,7337 | 683,7 s |
| Nhu cầu + giá (`price_last`, `price_rel_28`) | 0,808117 | +0,071829 | 6,7517 | 836,7 s |
| Baseline | 0,839037 | +0,118760 | | |

WAPE theo fold (chỉ nhu cầu → có giá):

| Fold | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|
| Chỉ nhu cầu | 0,8334 | 0,7456 | 0,7113 | 0,7564 | 0,8230 | 1,1057 | 0,7935 |
| Có giá | 0,8518 | 0,7362 | 0,7175 | 0,7556 | 0,8195 | 1,1014 | 0,7959 |

Theo FC và giai đoạn (WAPE, chỉ nhu cầu → có giá):

| Nhóm | Chỉ nhu cầu | Có giá |
|---|---|---|
| FC BD | 0,7418 | 0,7437 |
| FC HN | 0,9560 | 0,9586 |
| Trước tháng 7 | 0,7584 | 0,7635 |
| Từ tháng 7 | 0,8754 | 0,8732 |

**Kết luận đúng phạm vi:** hai feature giá trong cấu hình hiện tại **chưa cải thiện metric tổng**. Điều này không có nghĩa
mọi feature giá đều vô ích, và không phải lý do để tắt nhóm Giá.

**Ước tính khi bật giá (suy từ số đo, chưa đo trực tiếp):**
- một job huấn luyện đầy đủ mất khoảng 16–17 phút (chỉ nhu cầu: 13–14 phút);
- RAM đỉnh khoảng 2,1 GB (thêm 2 cột float32 × 5,2 triệu dòng, khoảng 42 MB).

## 8. Thử nghiệm cải thiện giá đề xuất (CHƯA chạy, chờ duyệt)

Điều kiện chung:
- Chạy trên bản sao cô lập đã có giá (thư mục tạm của phiên, 419 MB; tạo lại được bằng `price_experiment.py load`).
- Mỗi lần một tiến trình; không chạy trùng với job production (D-1, huấn luyện 09:00).
- Máy hiện còn trống khoảng 4,3 GB RAM.
- Đơn giá thời gian: một backtest 7 fold có giá mất khoảng 14 phút, RAM khoảng 2,1–2,3 GB.

| # | Thử nghiệm | Mục đích | Chi phí ước tính |
|---|---|---|---|
| E0 | Chạy lại 2 cấu hình hiện có, **lưu dự báo từng điểm** | Phân rã sai số theo FC, SKU, kỳ (ngày 1–7 / 8–15 / 16–30), nhóm thay đổi giá (giá ổn định / giảm / tăng trong 28 ngày), loại chuỗi (đều / gián đoạn). Không cần huấn luyện thêm để phân tích sau | khoảng 30 phút; RAM ≤ 2,5 GB; khoảng 0,3 GB đĩa |
| E1 | Tính sẵn có của giá | Đo giờ nguồn có giá ngày D (đã biết: 12:00–14:10 ngày D+1). Bảng D-0 có `sales_price` của hôm nay, có thể là giá mới hơn trong tương lai (cần thiết kế riêng) | Vài phút, chỉ đọc metadata |
| E2 | Biến đổi giá (5 ứng viên, từng cái một): thay đổi ngắn hạn (giá cuối ÷ giá 8–14 ngày trước); giá so với trung bình 90 ngày; số ngày từ lần đổi giá > 2 %; giá thấp nhất 7 ngày (bớt nhiễu cơ cấu đơn); giá cùng SKU ở FC kia | Tìm dạng giá có tín hiệu | khoảng 75 phút (5 × 15 phút) |
| E3 | Tương tác giá × nhu cầu (`price_rel_28 × roll_mean_28`; độ co giãn theo SKU ước tính chỉ trên dữ liệu huấn luyện của fold). **Chỉ làm khi E2 có tín hiệu** | Kiểm tra quan hệ giá–nhu cầu theo SKU | khoảng 30 phút |
| E4 | Tham số LightGBM khi có giá, walk-forward lồng nhau: chọn trên fold 1–4 (trước tháng 7), đánh giá **một lần** trên fold 5–7. Lưới 8 cấu hình: `num_leaves` {31, 63}, `learning_rate` {0,05; 0,03}, `min_data_in_leaf` {50, 200} | Không chọn cấu hình dựa trên dữ liệu đánh giá | khoảng 1,5–2 giờ |
| E5 | Đối chiếu khi có dữ liệu 16/10–15/11 | Kiểm định độc lập thật (chưa có dữ liệu; không giả lập) | Sau 15/11 |

Mỗi ứng viên được ghi lại để tái lập:
- cấu hình và fingerprint;
- metric tổng, theo fold, theo FC, theo kỳ;
- thời gian chạy và RAM;
- lý do chọn hoặc loại.

**Tiêu chí chọn** (ví dụ: tổng tốt hơn và không fold nào xấu hơn quá X) **phải do chủ dự án duyệt trước khi chạy**. Báo
cáo này không tự đặt ngưỡng. Nếu chạy hết E0–E4, máy bận khoảng 4–4,5 giờ, tuần tự.

## 9. Việc còn lại để phát hành (theo thứ tự)

1. QA đầy đủ, commit cục bộ (không push), `scripts\release.ps1` → gói 1.2.0.
2. Sau khi nguồn có ngày 16/10 (khoảng 12:00–14:10 ngày 17/10): diễn tập `iso120.ps1` trên bản sao DB thật, gồm:
   - ánh xạ giá → kiểm tra toàn kỳ → bật sản xuất → D-1 nạp lại → huấn luyện DIRECT có giá (khoảng 17 phút) → ngoại lệ →
     giải thích → rollback.
3. Production:
   1. backup → `deploy-upgrade.ps1` (`-CheckOnly` trước);
   2. ánh xạ `unit_price ← sales_price` → kiểm tra toàn kỳ → bật sản xuất → kiểm tra lại bảng D-0;
   3. D-1 (nạp lại toàn kỳ);
   4. lưu tường minh `feature_price = true`, DIRECT;
   5. huấn luyện;
   6. **xác nhận `feature_groups.price.used = true`** trước khi phát hành;
   7. backup → phát hành với ngoại lệ;
   8. kiểm tra forecast và giải thích.
4. Nếu bất kỳ bước nào cho thấy giá không được dùng thì dừng trước khi phát hành và báo `BLOCKED` / `PARTIAL`.

Phê duyệt ngoại lệ hiện có được đưa cho L7_direct với WAPE 0,806 / bias +0,069.
- Model có giá sẽ có metric của chính lần chạy đó (backtest có giá trên bản sao: 0,808 / +0,072).
- Yêu cầu ngoại lệ ghi đúng metric của lần chạy.
- Đề nghị chủ dự án xác nhận phê duyệt áp dụng cho model **có giá**.
