# Cấu hình PHƯƠNG ÁN CHỐT trên production – trước / sau (29/10/2026)

Bản cài: 1.3.1 (commit 495384b, gói SHA EE99EBB0…D5D9D7). DB thật: schema 11.
Cách áp: CLI của bản cài `python -m app.cli apply-preset lgbm-chot` chạy thử (không ghi) rồi `--apply`, lúc
**29/10/2026 13:39:05 (giờ VN)**, không có job nào đang chạy. Mỗi section lưu một lần qua `settings_service` (có kiểm
tra hợp lệ); các tác vụ mới bật qua `flows.update_flow` (đúng đường của `PUT /api/schedules/{flow}`).
Ảnh chụp đọc bằng `mode=ro`: giá trị hiệu lực = giá trị đã lưu hoặc mặc định của bản 1.3.1.

## 1. Thay đổi (chỉ 5 khoá + 2 tác vụ mới)

| Mục | Khoá | Trước | Sau |
|---|---|---|---|
| B1 | `model.feature_sku_code` | true | **false** (bỏ sku_code) |
| B1 | `model.horizon_weight_short` | null (không trọng số) | **3.0** |
| B1 | `model.horizon_weight_cutoff` | null | **7** (horizon ≤ 7) |
| B2 | `model.fallback_enabled` | true | **false** |
| B5–B10 | `daily_forecast.enabled` | false (mặc định, chưa lưu) | **true** |
| B5 | `schedule.refresh_enabled` | false | **true** (bật 13:39:05) |
| B9 | `schedule.report_enabled` | false | **true** (bật 13:39:05) |

## 2. Giữ nguyên (đã đúng phương án chốt theo mặc định hoặc theo cấu hình cũ)

| Mục | Khoá | Giá trị |
|---|---|---|
| B1 | `model.forecast_strategy`, `objective`, `num_boost_round`, `learning_rate`, `num_leaves` | DIRECT, tweedie, 300, 0.05, 31 (Tweedie 1.2, seed 7 trong code) |
| B3 | `daily_forecast.rounding_threshold` | 0.2 (ROUNDUP trong code) |
| B4 | `horizons.enabled` | [7, 15] |
| B5 | `schedule.refresh_deadline`, `refresh_retry_minutes` | 12:00, 10 |
| B6 | `daily_forecast.openhours_table`, `seller_code` | lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku, MEDX |
| B8 | `daily_forecast.log_retention_days` | 120 |
| B9 | `schedule.report_weekday`, `report_time`, `daily_forecast.report_subdir` | 1 (thứ Hai), 09:30, theo-doi |
| B11 | `feature_table.features` | {} (mặc định = B1) |
| B12 | `daily_forecast.trial_mode` | **true** – nhãn "Chạy thử – chưa dùng để mua hàng" |

B7 (nhóm A/B/C) và B10 (báo cáo tỷ trọng biến) không có khoá riêng: chạy khi `daily_forecast.enabled = true`.

## 3. Lịch cũ không đổi (so sánh từng khoá trước/sau)

D0 08:00–18:00 mỗi 2 giờ; D-1 dò tín hiệu từ 05:00 mỗi 30 phút, mốc dự phòng 06:10; huấn luyện 05:20
(`train_catchup_policy` SKIP); sao lưu dự báo cuối ngày 23:55; chốt actual 23:59; `max_attempts` 4. So với ảnh chụp
trước khi cài 1.3.1: các section general, horizons, model, schedule, sql_sources không đổi; sau preset chỉ các khoá ở
mục 1 đổi.

## 4. Lịch sử thay đổi

`settings_history`: 51 → 55 dòng (cùng lúc 2026-10-29T06:39:05Z):

| Section | Ghi chú |
|---|---|
| model | PRESET lgbm-chot 1.3.1 (PHUONG AN CHOT) |
| daily_forecast | PRESET lgbm-chot 1.3.1 (PHUONG AN CHOT) |
| schedule | schedule refresh: refresh_enabled, refresh_enabled_at (UI) |
| schedule | schedule report: report_enabled, report_enabled_at (UI) |

Kèm một dòng audit `PRESET_APPLIED`. Ghi chú "(UI)" của hai dòng schedule là chữ cố định của `flows.update_flow`;
thực tế được bật bởi lệnh preset ở trên.

## 5. Hệ quả cần biết

* Cấu hình model áp dụng ở **lần huấn luyện kế tiếp**: lịch huấn luyện 05:20 chỉ chạy khi D-1 trong ngày thành công
  trước 05:40 (mốc + 20 phút ân hạn; trễ hơn thì bỏ qua theo `train_catchup_policy` SKIP, như trước) và sẽ tạo model
  theo B1. Model mới **không** tự thay model đang dùng (chỉ promote thủ công).
* Model đang dùng vẫn là MV-20261026-105345-C73F (huấn luyện với sku_code). Làm mới dự báo dùng model này cho tới
  khi có model B1 được promote.
* Làm mới dự báo chỉ chạy sau D-1 thành công trong ngày; quá 12:00 thì giữ số cũ và gắn STALE_FORECAST. Hôm nay
  29/10 tác vụ được bật sau 12:00 nên tự chạy từ **30/10** (hôm nay không tự chạy, không gắn STALE); nút làm mới
  thủ công vẫn dùng được. Báo cáo B9 tự chạy lần đầu thứ Hai 02/11 lúc 09:30.
