# Kiểm tra hiện trạng so với PHƯƠNG ÁN CHỐT (C0), 28/10/2026 23:15

**Cách kiểm tra:** chỉ đọc.
- Code production: commit `af835b8` (Release 1.2.14), đọc qua `git grep` / `git show` và worktree của branch mới `feature/lgbm-chot-20261029` (tạo từ `af835b8`, chưa sửa gì).
- DB thật: mở `file:///D:/Buymed/Lightgbm AI/data/runtime/db/app.db?mode=ro` với `PRAGMA query_only=1`, chỉ `SELECT`.
- Không đọc bảng / cấu hình chứa thông tin đăng nhập Google.

## 1. Bản cài, model, git

| Mục | Giá trị |
|---|---|
| Bản cài đang chạy | 1.2.14 (`%LOCALAPPDATA%\Programs\DemandForecast\current.txt`), PID 29408, `python -m app.cli serve --port 8765`, `/api/health` ok |
| `storage.json` | SHA-256 `8D79DBDD…E047` (không đổi so với 26/10) |
| Schema DB | migration 10 (`0010_history_sync.sql`) |
| Model đang dùng | `MV-20261026-105345-C73F` (lần huấn luyện `TRN-20261026031942-53C73F`), promote 26/10 11:40 |
| Biến của model | 36 biến, **có `sku_code`**; fingerprint `8468ebe66d1706f7` |
| Tham số | tweedie 1,2; lr 0,05; 31 lá; 300 vòng; seed 7; DIRECT, 12 mốc × 7 ngày |
| Lần dự báo hiện hành | `FCR-20261026044021-330262`: lập 26/10 11:40, mốc 26/10, dữ liệu đến 25/10, 15 ngày, 17.150 chuỗi |
| Phương pháp của lần đó | LIGHTGBM 4.256; FALLBACK_INTERMITTENT 9.047; FALLBACK_INACTIVE_ZERO 3.667; FALLBACK_NEW_SERIES 180 (**75,2 % chuỗi đi luật dự phòng**) |
| Lịch đang lưu | D-1 dò từ 05:00, mỗi 30 phút, mốc dự phòng 06:10; huấn luyện 05:20 (`train_catchup_policy` SKIP); D-0 08:00–18:00 mỗi 2 giờ; sao lưu cuối ngày 23:55; chốt thực bán 23:59 |
| D-1 gần nhất | 28/10 09:40 chạy tay (`JOB-20261028024003-CC1012`), dữ liệu đến 27/10. Huấn luyện theo lịch 28/10: SKIPPED `MISSED_SLOT_NO_BACKFILL` |
| Git (working tree chính) | branch `feature/du-bao-moi-20261028` (đóng băng), HEAD `3701f8b`. 8 file sửa và 5 file mới chưa commit: các file truy cập từ xa, `CHANGELOG.md`, `docs/CHECKPOINT.md`, `docs/ke_hoach_trien_khai.md`, cùng 2 tài liệu căn cứ `docs/project_map.md`, `docs/thanh_phan_tai_su_dung.md` |
| Branch mới | `feature/lgbm-chot-20261029` từ `af835b8`, ở worktree riêng `D:\Buymed\lgbm-chot-20261029`; working tree chính không bị đụng tới |

## 2. Đối chiếu B1–B12

| Hạng mục | Hiện trạng (file:hàm / giá trị) | Đúng / Chưa |
|---|---|---|
| **B1** Model 35 biến, bỏ `sku_code`, trọng số 3,0 cho horizon ≤ 7 | `ml/features.py:187` `feature_names()` luôn bắt đầu bằng `sku_code`, `fc_code`, `series_age`. `ml/model.py:72` `lgb.Dataset(..., categorical_feature=["sku_code","fc_code"])`. `ml/model.py:47-50` `train()`: trọng số mẫu chỉ dành cho thí nghiệm, app không truyền. Model đang dùng có 36 biến, gồm `sku_code` | **Chưa** |
| **B2** Tắt luật dự phòng (`fallback_enabled = false`) | `ml/model.py:83` `classify_series()` / `classification_details()` luôn áp INACTIVE → NEW_SERIES → INTERMITTENT. Không có cấu hình tắt. Lần dự báo hiện hành: 75,2 % chuỗi FALLBACK | **Chưa** |
| **B3** Số công bố = 0 nếu < 0,2, ngược lại ROUNDUP; lưu thêm giá trị gốc | `qty.py:12-17`: `ROUND_HALF_UP_NON_NEGATIVE` (làm tròn nửa lên). `forecast_values.yhat` lưu `round(yhat, 4)` (`ml/pipeline.py:250` `_publish_run`). Không có `rounding_threshold` | **Chưa** |
| **B4** Khung dự báo như app (tối thiểu 7 ngày) | `horizons.enabled = [7, 15]` (DB). DIRECT huấn luyện tới 30 ngày | **Đúng** |
| **B5** Làm mới dự báo sau D-1, nút tay, model đang promote, không huấn luyện, hạn chót 12:00, STALE_FORECAST | `jobs/runner.py:32` `JOB_TYPES` không có tác vụ làm mới. Số dự báo chỉ tạo khi publish / promote / `FORECAST_EXTEND` (`ml/pipeline.py:727` `promote_candidate`). Lần dự báo hiện hành vẫn là của 26/10 (dữ liệu đến 25/10) | **Chưa** |
| **B6** Đọc `openhours_by_sku` vào `open_hours_daily`, tăng dần | Giờ mở bán chỉ lấy từ cột `total_open_hours` của bảng D-1 (`bq/connector.py:62`), chỉ có cho ngày có đơn. Không có bảng `open_hours_daily` (DB có 36 bảng, không có bảng này) | **Chưa** |
| **B7** Phân nhóm A / B / C hằng tháng (chỉ để báo cáo) | Không có code, không có bảng `sku_group` | **Chưa** |
| **B8** Nhật ký ngày 1–7 của mỗi lần làm mới + thực bán; lưu 120 ngày | Có lịch sử D+1 (`forecast_history.py:166` `capture_after_publish`) và bản sao cuối ngày, nhưng chỉ chép số của lần publish. Không có giá trị LightGBM gốc, số công bố, nhóm hay phiên bản cấu hình theo từng lần làm mới. Không có thời hạn lưu cấu hình được | **Chưa** |
| **B9** Báo cáo độ chính xác Đúng / Dư / Thiếu hằng tuần + nút tay, .xlsx vào `reports\theo-doi\` | Không có | **Chưa** |
| **B10** Tỷ trọng biến sau mỗi lần huấn luyện (gain, số lần chia nhánh, %, nhóm biến, .xlsx) | Chỉ lưu gain của 30 biến đầu vào `training_runs.feature_importance_json` (`ml/model.py:77-78`, `ml/pipeline.py:497`). Không lưu số lần chia nhánh (chỉ màn hình giải thích đọc tạm, `ml/explain.py:374`), không có %, nhóm biến, file .xlsx | **Chưa** (một phần) |
| **B11** Bảng cấu hình biến (Bật/tắt, hệ số `feature_contri`) | Chỉ có công tắc theo nhóm biến trong `ModelSettings` (`settings_service.py:100`), không có cấu hình từng biến hay `feature_contri` | **Chưa** |
| **B12** Chế độ chạy thử + nhãn "Chạy thử – chưa dùng để mua hàng" | Không có | **Chưa** |

**Kết luận C0:** 11 / 12 mục chưa đúng (chỉ B4 đúng). Làm tiếp C1 → C7 cho B1–B3 và B5–B12.

## 3. Các sự thật dùng cho bước sau

**Định nghĩa B9 đã chứng minh bằng số.**
- Dò trước, chỉ đọc. Nguồn: `G2_lgbm` ngày thứ 1 của `reports\backtest-lgbm7-20261029\eval_lgbm\`, demand của bản sao DB backtest, giờ mở bán `reports\backtest-prereg-v2-20261027\openhours.parquet`.
- Định nghĩa dùng:
  - ngày mở bán = giờ mở bán > 0;
  - thực bán của ngày không có dòng demand = 0;
  - nhóm tính trên 01/06–31/08, chỉ ngày mở bán, < 14 ngày mở bán thì vào nhóm B;
  - số công bố = luật B3.
- Kết quả: 11.587,1 SKU bq/ngày; Qty lệch 10.813.068; tổng demand 16.710.161; nhóm A Đúng 220,0 SKU (25,3 %), Qty lệch 353.194.
- So với kỳ vọng 353.356: lệch 0,05 %, trong ngưỡng 0,1 %.

**Lịch D-1 hiện tại** thường xong muộn: 27/10 và 28/10 D-1 theo lịch thất bại, phải chạy tay. Hạn chót làm mới mặc định 12:00 theo B5.
