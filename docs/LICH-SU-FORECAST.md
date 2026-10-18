# Lịch sử Forecast & Thực tế (1.2.5)

Màn hình **Lịch sử Forecast & Thực tế** (`/forecast-history`) lưu forecast ngày hôm sau (D+1) của từng ngày chạy
forecast và so sánh với thực tế. Mã nguồn: `backend/app/forecast_history.py`, `backend/app/api/history_routes.py`,
`frontend/src/pages/ForecastHistory.tsx`; migration `0004_forecast_history.sql`. Test:
`backend/tests/test_v125_forecast_history.py`, `frontend/src/v125-history.test.tsx`.

## 1. Quy tắc nghiệp vụ (chủ sở hữu đã xác nhận, 18/10/2026)

| Quy tắc | Cách triển khai |
|---|---|
| Phiên forecast | Một lần forecast **đã publish thành công** (một dòng `forecast_runs`). Lần chạy đang chạy hoặc thất bại không tạo dòng nào, nên không bao giờ thành lịch sử. Các đường publish: huấn luyện & publish khi scope chưa có model đang dùng, "Dùng model này" (ứng viên), phát hành ngoại lệ, mở rộng khoảng dự báo. |
| Thời điểm phiên, ngày chạy | Thời điểm bắt đầu của job tạo ra phiên (`job_runs.started_at`); nếu không có job (dùng model ứng viên, ngoại lệ) thì là thời điểm publish. Ngày chạy = ngày theo giờ Việt Nam của thời điểm đó. |
| Chỉ lưu D+1 | Chỉ copy giá trị có `target_date = ngày chạy + 1` sang `forecast_history_values`. Các ngày khác (D+7/D+15/D+30) vẫn chỉ nằm trong `forecast_values`, không đổi. |
| Phiên chính thức của ngày | Phiên hợp lệ mới nhất theo (thời điểm phiên, thời điểm publish, thứ tự ghi). Phiên bắt đầu sớm hơn nhưng xong muộn hơn **không** thay phiên mới hơn. Phiên không có giá trị D+1 là `NOT_ELIGIBLE` và không thay gì. Phiên hợp lệ mới hơn của **cùng ngày chạy** thì thay. Phiên của ngày khác không bao giờ đụng tới ngày này. |
| Bất biến | `forecast_history_sessions` và `forecast_history_values` không bao giờ bị sửa hay xóa (trigger). Chỉ con trỏ "phiên chính thức" trong `forecast_history_days` được đổi, và mỗi lần đổi đều có `audit_log` `FORECAST_HISTORY_SELECTED` (kèm phiên bị thay). Trigger buộc con trỏ chỉ trỏ tới phiên hợp lệ của đúng ngày chạy đó. |
| Không có phiên hợp lệ | Màn hình ghi "Chưa có forecast hợp lệ" (hôm nay) hoặc "Chưa có lịch sử forecast được lưu cho ngày này". Không tạo số thay thế, không nội suy. |
| Forecast và thực tế độc lập | Thực tế **không** lưu trong các bảng lịch sử. Nó được đọc lúc hiển thị từ dữ liệu thực tế, nên cập nhật thực tế không bao giờ sửa forecast và không tạo phiên mới. |

Ví dụ: phiên chạy 17/10 lúc 19:34 (giờ VN) lưu forecast của 18/10. Nếu 17/10 có phiên khác lúc 21:00 thì phiên 21:00
thành chính thức. Phiên của 18/10 không ảnh hưởng tới 17/10.

## 2. Ghi lịch sử và thử lại

- Ghi lịch sử ngay sau khi transaction publish đã commit, trong một transaction `BEGIN IMMEDIATE` riêng. Lỗi ghi lịch sử
  **không thể** làm mất forecast đã publish. Lỗi được ghi log và tạo alert ERROR `FORECAST_HISTORY_CAPTURE_FAILED`.
- Thử lại không cần forecast mới, vì `reconcile()` đọc lại các forecast run bất biến. Lần thử lại chạy tự động ở:
  - lần publish kế tiếp;
  - lần khởi động ứng dụng;
  - lệnh `python -m app.cli history-reconcile`.
- Việc ghi là idempotent: khóa chính theo run, ghi lần hai không tạo gì. Hai tiến trình ghi cùng lúc được SQLite xếp
  hàng (`BEGIN IMMEDIATE`), nên không có hai phiên chính thức.
- `capture_mode` ghi rõ cách phiên được ghi nhận:
  - `AT_PUBLISH`: ngay khi publish;
  - `RECOVERED`: ghi sau, từ forecast đã publish và lưu trước đó, ví dụ các phiên publish trước 1.2.5.
  - Cả hai trường hợp đều dùng đúng giá trị đã publish lúc đó (không chạy lại model, không giả lập).
- Mở màn hình lịch sử chỉ đọc (GET). Không tạo job, không huấn luyện, không forecast. Test kiểm tra số dòng các bảng
  trước và sau.

## 3. Thực tế (actual)

Nguồn của ngày được dự báo T, theo thứ tự:

| Trường hợp | Nguồn | Trạng thái |
|---|---|---|
| T chưa tới | — | `NO_ACTUAL` (`FUTURE_DATE`) |
| T đã được D-1 nạp vào `demand_daily` | Tổng theo SKU × FC của ngày đó. SKU × FC không có dòng trong một ngày đã nạp = 0, giống quy tắc của panel huấn luyện / backtest. | `COMPLETE` nếu lần D-1 nạp ngày T chạy theo **tín hiệu hoàn tất** của nguồn; nếu không thì `PROVISIONAL` (`D1_NO_COMPLETION_SIGNAL`) |
| D-1 đã chạy qua T nhưng T không có dòng nào | — | `NO_ACTUAL` (`DAY_WITHOUT_DATA`), không coi là 0 |
| D-1 chưa nạp T, có snapshot D0 thành công của T | Số lũy kế của snapshot D0 mới nhất (SKU × FC vắng = 0, vì snapshot đọc cả bộ dữ liệu) | `PROVISIONAL` (`D0_INTRADAY` cho hôm nay, `D0_LAST_READ` cho ngày đã qua) |
| Không có gì | — | `NO_ACTUAL` (`NO_D0_READ_TODAY` / `NOT_LOADED_YET`), không bao giờ thành 0 |

**Tín hiệu hoàn tất.** Bằng chứng duy nhất được chấp nhận là `audit_log` `D1_SYNC` có `mode = SIGNAL` cho đúng ngày đó.
Chế độ này chỉ có khi cấu hình `bigquery.completion_table` / `completion_date_column`. D-1 chạy sau giờ dự phòng với
kiểm tra số dòng (`FALLBACK_TIME_VERIFIED`), backfill, truy vấn thành công hay đã qua nửa đêm đều **không** phải bằng
chứng.

**Production 18/10/2026:** chưa cấu hình bảng tín hiệu hoàn tất. Vì vậy mọi số thực tế là "Tạm tính", và màn hình nói
rõ lý do. Muốn có "Đã hoàn tất" thì cấu hình tín hiệu hoàn tất có sẵn trong thiết lập BigQuery. Đó là quyết định
nghiệp vụ; ứng dụng không tự đặt quy tắc mới.

Nguồn cập nhật hồi tố (D-1 nạp lại trong cửa sổ late-data) thì thực tế hiển thị theo số mới. "Thực tế tính đến"
(`loaded_at` hoặc thời điểm snapshot) cho biết số đang thấy là của lần nạp nào. Giá trị cũ còn trong bản sao lưu.

## 4. KPI, sai lệch, WAPE

Tất cả tính trên **đúng tập dòng của bộ lọc**: phạm vi ngày chạy, FC, SKU / tên, trạng thái thực tế. KPI, biểu đồ,
bảng và Excel dùng chung truy vấn `forecast_history.Query`.

- **Tổng forecast đã lưu** = Σ forecast của mọi dòng.
- **Tổng thực tế hiện có** = Σ thực tế của các dòng **đã có thực tế** (dòng thiếu thực tế bị loại, không tính 0).
- **Sai lệch** = Σ forecast − Σ thực tế, trên cùng các dòng có thực tế.
- **WAPE** = Σ|forecast − thực tế| / Σ thực tế, trên cùng các dòng đó; đúng công thức của `ml/metrics.py` (test
  đối chiếu). Không tính khi tổng thực tế = 0 (`SUM_ACTUAL_ZERO`) hoặc chưa có thực tế (`NO_ACTUAL`).
- **WAPE dòng** = |F − T| / T, chỉ khi T > 0.
- **Trạng thái KPI:** "Tạm tính" khi có dòng tạm tính trong tập so sánh; "Đã hoàn tất" chỉ khi mọi dòng so sánh đã
  hoàn tất.
- Ghi chú: `/api/forecast-runs/{id}/accuracy` (có từ trước) chỉ ghép các ngày có dòng trong `demand_daily` (inner join).
  Màn hình lịch sử theo quy tắc panel (ngày đã nạp, không có đơn = 0). Không sửa endpoint cũ.

## 5. Lưu trữ (migration 0004, chỉ thêm bảng)

| Bảng | Vai trò | Khóa / chỉ mục |
|---|---|---|
| `forecast_history_sessions` | Mọi forecast run đã thấy + quyết định lúc ghi nhận: `SELECTED` / `OLDER_THAN_SELECTED` / `NOT_ELIGIBLE`, lý do, mô hình, nguồn, thời điểm phiên / publish / ghi nhận, số dòng D+1, đánh giá sử dụng. Bất biến. | PK `forecast_run_id`; `(scope_key, run_date)` |
| `forecast_history_values` | Giá trị D+1 của phiên được chọn lúc ghi nhận: SKU, FC, forecast, method, tên sản phẩm lúc ghi. Bất biến. | PK `(forecast_run_id, sku_id, fc_id)`; `(scope_key, target_date, sku_id, fc_id)`; `(scope_key, fc_id, target_date)` |
| `forecast_history_days` | Phiên chính thức của mỗi `(scope_key, run_date)`. Chỉ cột `forecast_run_id` / `selected_at` được đổi; không xóa. | PK `(scope_key, run_date)` |

- **Nguồn sự thật:**
  - forecast: `forecast_values` (bất biến), lịch sử là bản chụp D+1 lấy từ đó;
  - thực tế: `demand_daily` (D-1) và `d0_snapshots` (D0).
  - Snapshot D0 **không** phải forecast D+1.
- **Dữ liệu theo scope:** mỗi scope (DEMO / Excel / BIGQUERY) có lịch sử riêng. Màn hình mặc định là scope của nguồn
  đang dùng, kể cả khi scope đó chưa có lịch sử. Không tự hiện lịch sử của nguồn khác.
- **Tên sản phẩm:** ưu tiên mapping hiện tại (`dim_sku`, chỉ BIGQUERY), sau đó tên lúc ghi nhận. Thiếu cả hai thì ghi
  "Chưa có tên sản phẩm". Tra theo dict nên không bao giờ nhân bản dòng.
- **`data-check` (chỉ đọc)** có thêm 5 kiểm tra:
  - giá trị lịch sử = giá trị đã publish;
  - chỉ có D+1;
  - phiên được chọn đủ dòng;
  - phiên chính thức là phiên mới nhất;
  - mọi run đã được ghi nhận (WARN).

## 6. API (GET, chỉ đọc; link từ xa cho phép)

| Endpoint | Nội dung |
|---|---|
| `/api/history/overview?scope_key=` | scope có lịch sử, ngày chạy + phiên chính thức, FC, phiên hôm nay, đã cấu hình tín hiệu hoàn tất chưa |
| `/api/history/summary?scope_key&run_from&run_to&fc_id&q&actual_status` | KPI, một điểm mỗi ngày chạy (ngày không có lịch sử là khoảng trống), các phiên của khoảng ngày (cả phiên không được chọn) |
| `/api/history/rows?…&sort=date\|abs_error\|forecast\|actual\|sku&limit<=1000&offset` | bảng SKU × FC có phân trang |
| `/api/history/export.xlsx?…&lang=vi\|en` | Excel (định dạng H1) |

`q` tìm theo một phần SKU / tên, không phân biệt hoa thường, không cần dấu. Mặc định là 30 ngày chạy, kết thúc ở ngày
chạy mới nhất có lịch sử; tối đa 400 ngày mỗi yêu cầu.

## 7. Excel

Gồm 4 sheet: Thông tin (bộ lọc, KPI, quy tắc), Phiên forecast, Theo ngày, Chi tiết SKU × FC.

- Xuất **toàn bộ** dòng khớp bộ lọc, không chỉ trang đang xem.
- Ghi bằng openpyxl write-only.
- Quá 1.000.000 dòng thì từ chối với lỗi `HISTORY_EXPORT_TOO_LARGE`, không bao giờ cắt bớt.
- Thực tế trống nghĩa là chưa có dữ liệu, không phải 0.
- Trạng thái ghi bằng chữ: "Tạm tính" / "Đã hoàn tất" / "Chưa có dữ liệu thực tế".
- Excel ở các trang khác không đổi.

## 8. Giới hạn

- **Phiên forecast không chạy hằng ngày.** Pipeline hiện tại chỉ tạo forecast run khi publish (xem mục 1). Lần huấn
  luyện 09:00 khi đã có model đang dùng chỉ tạo **ứng viên chờ duyệt**, không có forecast. Vì vậy lịch sử chỉ có ngày
  ở những ngày có publish. Muốn có lịch sử D+1 mỗi ngày thì cần một quyết định nghiệp vụ mới, ví dụ forecast hằng ngày
  bằng model đang dùng sau D-1. 1.2.5 không tự thêm quy trình đó.
- **Ngày quá khứ trước khi có forecast run:** không có lịch sử. Các run đã publish trước 1.2.5 được ghi nhận từ giá
  trị đã lưu (`RECOVERED`).
- **Chưa có tín hiệu hoàn tất** nên mọi thực tế là "Tạm tính" (mục 3).

## 9. Rollback

Schema 4 mới hơn 1.2.4, nên `rollback-version.ps1 -To 1.2.4` sẽ từ chối. Có hai cách:

1. **Khôi phục bản sao lưu** chụp trước khi nâng cấp (`deploy-upgrade` tự tạo), rồi rollback. Dữ liệu ghi sau lúc
   nâng cấp sẽ mất: job, snapshot D0, D-1 (D-1 nạp lại được từ BigQuery).
2. **Hạ schema có kiểm soát, cần phê duyệt riêng.** Đây là thao tác phá hủy trên DB thật:
   - sao lưu trước;
   - `DROP TABLE` ba bảng `forecast_history_*` và các trigger của chúng;
   - xóa dòng `schema_migrations` version 4;
   - sau đó `rollback-version.ps1 -To 1.2.4`.

   Mất lịch sử D+1 đã ghi, nhưng phiên nào publish trước lúc hạ schema sẽ được ghi lại từ forecast run khi nâng cấp
   lại.
