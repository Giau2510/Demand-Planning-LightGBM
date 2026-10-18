# Lịch sử Forecast & Thực tế (1.2.5, bổ sung 1.2.6)

Màn hình **Lịch sử Forecast & Thực tế** (`/forecast-history`) lưu forecast ngày hôm sau (D+1) của từng ngày chạy
forecast và so sánh với thực tế. Mã nguồn: `backend/app/forecast_history.py`, `backend/app/api/history_routes.py`,
`frontend/src/pages/ForecastHistory.tsx`; migration `0004_forecast_history.sql`. Test:
`backend/tests/test_v125_forecast_history.py`, `frontend/src/v125-history.test.tsx`.

1.2.6 thêm snapshot forecast cuối ngày (dự phòng 7 ngày), dùng cho ngày chạy không có phiên hợp lệ, và chốt thực tế
lúc 23:59 (mục 10–13). Mã nguồn: `backend/app/forecast_backup.py`, `backend/app/actual_close.py`; migration
`0005_eod_backup_actual_close.sql`. Test: `backend/tests/test_v126_eod_backup_close.py`, `frontend/src/v126.test.tsx`.

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

**Production 18/10/2026:** chưa cấu hình bảng tín hiệu hoàn tất. Vì vậy không ngày nào "Đã hoàn tất": trong ngày là
"Tạm tính", từ 1.2.6 ngày đã chốt lúc 23:59 là "Đã chốt – cần xác minh" (`CLOSED`, mục 12). Màn hình nói rõ lý do.
Muốn có "Đã hoàn tất" thì cấu hình tín hiệu hoàn tất có sẵn trong thiết lập BigQuery. Đó là quyết định nghiệp vụ; ứng
dụng không tự đặt quy tắc mới.

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
  hoàn tất; còn lại (1.2.6: có dòng đã chốt nhưng chưa xác minh) là "Đã chốt – cần xác minh".
- **1.2.6 — WAPE trong ngày giữ nguyên.** Mỗi lần D-0 cập nhật, WAPE được tính lại theo đúng công thức trên, kể cả
  khi thực tế đang là số lũy kế còn forecast là số cả ngày (chủ sở hữu đã chấp nhận). Bản chốt 23:59 chỉ đổi nhãn
  trạng thái, không đổi con số (test và bản sao DB: cùng WAPE khi có / không có lớp chốt).
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
| `/api/history/overview?scope_key=` | scope có lịch sử, ngày chạy + phiên chính thức, FC, phiên hôm nay, đã cấu hình tín hiệu hoàn tất chưa; 1.2.6: `backup_days`, `today_backup` |
| `/api/history/summary?scope_key&run_from&run_to&fc_id&q&actual_status&forecast_source` | KPI, một điểm mỗi ngày chạy (ngày không có forecast là khoảng trống), các phiên của khoảng ngày (cả phiên không được chọn); 1.2.6: `backup_days`, `forecast_source` / `snapshot` / `actual_close` mỗi ngày, `days_primary` / `days_backup` |
| `/api/history/rows?…&sort=date\|abs_error\|forecast\|actual\|sku&limit<=1000&offset` | bảng SKU × FC có phân trang; 1.2.6: `forecast_source`, `snapshot_id`, `snapshot_business_date`, `snapshot_created_at` |
| `/api/history/export.xlsx?…&lang=vi\|en` | Excel (định dạng H2 từ 1.2.6) |

1.2.6 chỉ **thêm** trường và tham số (`forecast_source=PRIMARY|SNAPSHOT`, `actual_status` thêm `CLOSED`); trường cũ
giữ nguyên. Đường dẫn không đổi, nên allowlist của proxy chỉ đọc không cần sửa.

`q` tìm theo một phần SKU / tên, không phân biệt hoa thường, không cần dấu. Mặc định là 30 ngày chạy, kết thúc ở ngày
chạy mới nhất có lịch sử; tối đa 400 ngày mỗi yêu cầu.

## 7. Excel

Gồm 4 sheet: Thông tin (bộ lọc, KPI, quy tắc), Phiên forecast, Theo ngày, Chi tiết SKU × FC.

- Xuất **toàn bộ** dòng khớp bộ lọc, không chỉ trang đang xem.
- Ghi bằng openpyxl write-only.
- Quá 1.000.000 dòng thì từ chối với lỗi `HISTORY_EXPORT_TOO_LARGE`, không bao giờ cắt bớt.
- Thực tế trống nghĩa là chưa có dữ liệu, không phải 0.
- Trạng thái ghi bằng chữ: "Tạm tính" / "Đã chốt - cần xác minh" / "Đã hoàn tất" / "Chưa có dữ liệu thực tế".
- 1.2.6 (định dạng H2): cột mới được **nối vào cuối**, vị trí cột cũ giữ nguyên.
  - Sheet "Chi tiết SKU x FC": Nguồn forecast, Mã snapshot dự phòng, Ngày nghiệp vụ của snapshot, Snapshot tạo lúc.
  - Sheet "Theo ngày": Nguồn forecast, Mã snapshot dự phòng, Ngày nghiệp vụ của snapshot.
  - Sheet "Thông tin": lọc nguồn forecast, số ngày dùng forecast chính / snapshot dự phòng, quy tắc dự phòng, quy tắc chốt.
- Excel ở các trang khác không đổi.

## 8. Giới hạn

- **Phiên forecast không chạy hằng ngày.** Pipeline hiện tại chỉ tạo forecast run khi publish (xem mục 1). Lần huấn
  luyện 09:00 khi đã có model đang dùng chỉ tạo **ứng viên chờ duyệt**, không có forecast. Vì vậy lịch sử chỉ có ngày
  ở những ngày có publish. Muốn có lịch sử D+1 mỗi ngày thì cần một quyết định nghiệp vụ mới, ví dụ forecast hằng ngày
  bằng model đang dùng sau D-1. 1.2.5 không tự thêm quy trình đó.
- **Ngày quá khứ trước khi có forecast run:** không có lịch sử. Các run đã publish trước 1.2.5 được ghi nhận từ giá
  trị đã lưu (`RECOVERED`).
- **Chưa có tín hiệu hoàn tất** nên không có thực tế nào "Đã hoàn tất" (mục 3).
- **1.2.6 — dung lượng snapshot dự phòng.** Mỗi snapshot hoàn chỉnh lưu 7 × số chuỗi SKU × FC. Đo trên bản sao DB
  ngày 18/10/2026: 119.889 dòng, khoảng 11,8 MB mỗi ngày, tức khoảng 4,3 GB mỗi năm nếu chạy mỗi ngày. Chưa có chính
  sách lưu giữ: không xóa snapshot nào, vì trigger cấm xóa. Cần chủ sở hữu quyết định thời hạn lưu trước khi DB quá
  lớn; việc dọn sẽ cần một migration riêng được phê duyệt.

## 9. Rollback

**1.2.6 (schema 5):** bản 1.2.5 từ chối DB schema 5, nên rollback = khôi phục bản sao lưu `pre-migration-v4` (tự tạo
khi nâng cấp) hoặc bản backup trước deploy, rồi `rollback-version.ps1 -To 1.2.5`. Mất snapshot cuối ngày và bản chốt
ghi sau nâng cấp, cùng mọi dữ liệu khác ghi sau thời điểm đó. Cách hạ schema thủ công (`DROP TABLE` 4 bảng của 0005)
là thao tác phá hủy, cần phê duyệt riêng.

**1.2.5 (schema 4):**

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

## 10. Snapshot forecast cuối ngày (1.2.6)

Job `EOD_FORECAST_SNAPSHOT`, flow `eod` trên trang Lịch chạy dữ liệu, mặc định **BẬT lúc 23:55** (giờ Việt Nam).

| Quy tắc | Cách triển khai |
|---|---|
| Ngày nghiệp vụ S | Ngày Việt Nam của mốc lịch (`params.business_date`). Chạy lại sau nửa đêm (grace, retry, chạy bù) vẫn là S. Chạy thủ công lấy mốc gần nhất **đã qua**: trước 23:55 là hôm qua, không bao giờ snapshot một ngày chưa kết thúc. |
| Phiên nguồn | Phiên chính thức (`forecast_history_days`) của **ngày chạy mới nhất ≤ S**, đúng quy tắc chọn phiên hiện có. Trước khi chụp, job ghi nhận các run đã publish mà lịch sử chưa có (`forecast_history.reconcile()`, idempotent, như lúc khởi động). Không huấn luyện, không forecast, không publish, không đọc BigQuery. |
| Phạm vi 7 ngày | Ngày được dự báo S+1 … S+7 (D+1 = ngày chạy + 1, như lịch sử D+1). Grain SKU × FC × ngày, đúng dòng của `forecast_values` (kèm `horizon_day` trong run nguồn). |
| `COMPLETE` | Chỉ khi run nguồn có **mọi** chuỗi của nó ở **cả 7 ngày**. Bản sao được kiểm lại số dòng và tổng trong cùng transaction; lệch thì rollback (`EOD_SNAPSHOT_VERIFY_FAILED`, job thử lại). |
| `INCOMPLETE` / `NO_SOURCE` | Run nguồn thiếu ngày, hoặc không có phiên hợp lệ. Chỉ lưu dòng đầu mục (lý do, ngày thiếu), **không** lưu giá trị nào (trigger cấm). Có alert WARNING `EOD_SNAPSHOT_INCOMPLETE` / `EOD_NO_VALID_FORECAST`. Job: kết quả `INCOMPLETE`, hoặc `SKIPPED`. Không dùng demo, không điền 0. |
| Idempotent | Một snapshot cho mỗi (scope, ngày nghiệp vụ) (UNIQUE). Snapshot `COMPLETE` không bao giờ đổi (trigger). Lần chạy sau chỉ có thể hoàn thành dòng `INCOMPLETE` / `NO_SOURCE` của cùng ngày (`attempts` + 1). Hai job đồng thời: transaction `BEGIN IMMEDIATE` + khóa job, nên chỉ một bản. |
| Phụ thuộc | Nếu đang có job `TRAIN_PUBLISH` / `FORECAST_EXTEND` chạy thì chờ (`WAITING_FOR_FORECAST_JOB`, kiểm lại mỗi 5 phút, không tốn lượt thử), tối đa tới 06:00 ngày S+1; sau đó chụp và ghi `forecast_job_still_running`. |

## 11. Dùng snapshot khi không có forecast chính (1.2.6)

1. Ngày chạy R có phiên chính thức: luôn dùng phiên đó (`PRIMARY`).
2. Không có: dùng snapshot **`COMPLETE` mới nhất** có ngày nghiệp vụ ≤ R và còn bao phủ R+1 (`SNAPSHOT`).
3. Không snapshot nào bao phủ: ngày đó trống (khoảng trống trên biểu đồ, không có dòng). Không điền 0, không tạo số.
4. Snapshot thiếu một SKU × FC thì dòng đó không có, không thành 0.
5. Khi một phiên hợp lệ của R xuất hiện (publish muộn, ghi nhận lại), R trở về `PRIMARY` ngay. Snapshot không đổi.

Không fallback vì WAPE cao hay thấp; đây chỉ là cơ chế khi thiếu forecast hợp lệ. Việc chọn chỉ đọc, không tạo forecast
run, không publish, không ghi vào bảng lịch sử. Ngày chỉ xét tới hôm nay.

Hiển thị:
- ngày chạy có nhãn "(Dự phòng)" trong danh sách;
- dòng bảng có nhãn "Dự phòng dd/mm"; tooltip ghi snapshot của ngày nào, tạo lúc nào, run nguồn và model;
- bảng "Ngày dùng snapshot dự phòng" trong thẻ phiên;
- trên biểu đồ là đoạn nét đứt và chấm nhạt;
- KPI ghi "n ngày dùng snapshot dự phòng".

Có bộ lọc "Nguồn forecast" (tham số `forecast_source`), áp dụng cho KPI, biểu đồ, bảng và Excel.

## 12. Chốt thực tế 23:59 (1.2.6)

Job `ACTUAL_CLOSE`, flow `close`, mặc định **BẬT lúc 23:59** (giờ Việt Nam). Giờ của cả hai flow phải trong khoảng
20:00–23:59, vì chúng đại diện cho cuối ngày.

| Quy tắc | Cách triển khai |
|---|---|
| Ngày nghiệp vụ | Ngày Việt Nam của mốc lịch; không bao giờ là ngày UTC (00:00–06:59 giờ VN vẫn là ngày UTC hôm trước). Chốt trước giờ chốt bị từ chối (`ACTUAL_CLOSE_TOO_EARLY`). |
| Bản chốt (revision 1) | Bản sao độc lập của thực tế mà màn hình đang hiển thị, đúng quy tắc mục 3: D-1 nếu đã nạp, nếu chưa thì snapshot D0 cuối cùng của ngày. Chỉ copy các SKU × FC **có trong nguồn**; dòng vắng không lưu thành 0. Ngày không có dữ liệu thì `CLOSED_NO_DATA`, tổng NULL, kèm alert WARNING `ACTUAL_CLOSE_NO_DATA`. Lưu thời điểm chốt, giờ cắt (`cutoff_at`), nguồn, mã snapshot D0 / thời điểm nạp D-1, số dòng, tổng, sha256. |
| Trạng thái | `CLOSED_VERIFIED` chỉ khi D-1 của ngày đó chạy theo tín hiệu hoàn tất (quy tắc `COMPLETE` sẵn có). D0 hoặc D-1 không có tín hiệu thì là `CLOSED_UNVERIFIED`, hiển thị "Đã chốt – cần xác minh". Không tự tạo tín hiệu hoàn tất. Không bao giờ gọi một ngày là "Đã hoàn tất" chỉ vì đã qua 23:59. |
| Phụ thuộc | Nếu một lần đọc D-0 đang chạy thì chờ (`WAITING_FOR_D0_JOB`, tối đa 1 giờ sau giờ chốt). Không gọi BigQuery, không chạy D-0 / D-1 / huấn luyện / forecast. |
| Idempotent | UNIQUE (scope, ngày, revision). Kiểm tra và ghi trong cùng một transaction `BEGIN IMMEDIATE`, nên hai lần chốt đồng thời chỉ tạo một revision. Bản chốt và giá trị là bất biến (trigger). Revision phải liên tiếp (trigger). |
| Dữ liệu đến muộn | `reconcile()` so thực tế hiện tại với revision mới nhất của mỗi ngày đã chốt trong 14 ngày. Khác nguồn, khác giá trị hoặc khác trạng thái xác minh thì **thêm** revision mới. Revision ghi lý do (`D1_LOADED`, `D1_RELOADED`, `D0_LATE_READ`, `COMPLETION_SIGNAL_CONFIRMED`, `SOURCE_HAS_NO_DATA`), tổng trước / sau và số SKU × FC đổi / thêm / bớt. Không đổi thì không ghi. Chạy sau mỗi lần D-1 nạp thành công (sau commit, không làm D-1 thất bại) và trong mỗi job chốt. Revision cũ không bao giờ bị sửa. |
| Con số hiển thị | Vẫn đọc từ nguồn như mục 3, nên WAPE và sai lệch không đổi. Bản chốt chỉ thêm trạng thái `CLOSED` và dấu vết (`actual_close`: revision, thời điểm, nguồn, `current`). Ngày `CLOSED_NO_DATA` vẫn là "Chưa có dữ liệu thực tế". |

## 13. Lịch chạy, giám sát, kiểm tra (1.2.6)

- **Lịch.** Hai flow mới có công tắc và giờ riêng trên trang Lịch chạy dữ liệu (`/api/schedules/eod|close`). Bật/tắt
  chỉ qua trang này (`SCHEDULE_SWITCH_VIA_FLOW_API`). Không đổi giờ D-0 / D-1 / huấn luyện.
- **Chạy bù.** Mốc của hôm qua bị lỡ thì chạy bù một lần (trigger `CATCH_UP`, vẫn cho đúng ngày đó). Ngày cũ hơn ghi
  `MISSED_SLOT_NO_BACKFILL`. Mốc trước lần đầu scheduler của phiên bản này thấy flow (`sync_state`
  `flows_first_seen`) không bao giờ chạy: nâng cấp không tạo snapshot hay bản chốt cho ngày cũ.
- **Khởi động lại.** Idempotency key `EOD_FORECAST_SNAPSHOT:<ngày>` / `ACTUAL_CLOSE:<ngày>` cùng UNIQUE của bảng,
  nên khởi động lại hay chạy hai scheduler không tạo bản trùng.
- **Theo dõi.**
  - Lịch sử job ghi ngày nghiệp vụ, trạng thái snapshot, số ngày bao phủ, số dòng, trạng thái chốt và revision.
  - `audit_log` ghi `EOD_FORECAST_SNAPSHOT`, `ACTUAL_CLOSED` và `ACTUAL_CLOSE_REVISED`.
  - Alert WARNING khi snapshot không đủ 7 ngày, khi không có forecast hợp lệ, hoặc khi ngày không có thực tế để chốt.
  - Không gửi alert ra dịch vụ ngoài.
- **`data-check`** có thêm 3 kiểm tra:
  - `eod_snapshot_complete`: đầu mục COMPLETE đủ 7 ngày × chuỗi; đếm giá trị trong 14 ngày gần nhất; snapshot khác không có giá trị;
  - `eod_snapshot_values_match_source`: 14 ngày gần nhất, giá trị bằng forecast đã publish;
  - `actual_close_revisions`: revision 1..n liên tiếp, đủ số dòng.

**Bảng (migration 0005, chỉ thêm):**

| Bảng | Vai trò | Khóa |
|---|---|---|
| `forecast_eod_snapshots` | Đầu mục snapshot: ngày nghiệp vụ, khoảng ngày, run / phiên / model nguồn, số dòng, số ngày bao phủ, ngày thiếu, tổng, sha256, trạng thái + lý do, múi giờ, job, số lần thử, thời điểm tạo / cập nhật | PK `id`; UNIQUE `(scope_key, business_date)` |
| `forecast_eod_snapshot_values` | Giá trị 7 ngày (SKU, FC, ngày, horizon, forecast, method); chỉ cho snapshot COMPLETE; bất biến | PK `(snapshot_id, target_date, sku_id, fc_id)`, WITHOUT ROWID |
| `actual_closes` | Bản chốt và các revision: nguồn, tham chiếu, thời điểm đọc nguồn, số dòng, tổng, sha256, trạng thái, revision trước, tổng trước, số đổi / thêm / bớt, giờ cắt, thời điểm chốt, job; bất biến | PK `id`; UNIQUE `(scope_key, business_date, revision)` |
| `actual_close_values` | SKU × FC × số lượng của từng revision; bất biến | PK `(close_id, sku_id, fc_id)`, WITHOUT ROWID |
