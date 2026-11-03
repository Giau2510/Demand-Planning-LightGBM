# Lịch sử Forecast & Thực tế (1.2.5, bổ sung 1.2.6, 1.2.9)

Màn hình **Lịch sử Forecast & Thực tế** (`/forecast-history`) lưu forecast ngày hôm sau (D+1) của từng ngày chạy
forecast và so sánh với thực tế. Mã nguồn: `backend/app/forecast_history.py`, `backend/app/api/history_routes.py`,
`frontend/src/pages/ForecastHistory.tsx`; migration `0004_forecast_history.sql`. Test:
`backend/tests/test_v125_forecast_history.py`, `frontend/src/v125-history.test.tsx`.

1.2.6 thêm snapshot forecast cuối ngày (dự phòng 7 ngày), dùng cho ngày chạy không có phiên hợp lệ, và chốt thực tế
lúc 23:59 (mục 10–13), cùng chính sách lưu snapshot 90 ngày (mục 14). Hai lịch mới mặc định **TẮT**. Mã nguồn:
`backend/app/forecast_backup.py`, `backend/app/actual_close.py`, `backend/app/eod_retention.py`; migration
`0005_eod_backup_actual_close.sql`, `0006_eod_snapshot_retention.sql`. Test: `backend/tests/test_v126_eod_backup_close.py`,
`backend/tests/test_v126_retention_defaults.py`, `frontend/src/v126.test.tsx`.

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
| 1.2.9: T đã được **chốt** (mục 15) | Bản đóng băng của ngày T (`actual_final_values`), không đọc lại `demand_daily`. SKU × FC không có dòng = 0 (ngày đã được đọc trọn). | `COMPLETE` (`FINALIZED_D1`) |
| T đã được D-1 nạp vào `demand_daily` nhưng chưa chốt | Tổng theo SKU × FC của ngày đó. SKU × FC không có dòng trong một ngày đã nạp = 0, giống quy tắc của panel huấn luyện / backtest. | `PROVISIONAL` (`D1_NOT_FINALIZED`; trước 1.2.9: `COMPLETE` khi có tín hiệu hoàn tất, `D1_NO_COMPLETION_SIGNAL` nếu không) |
| D-1 đã chạy qua T nhưng T không có dòng nào | — | `NO_ACTUAL` (`DAY_WITHOUT_DATA`), không coi là 0 |
| D-1 chưa nạp T, có snapshot D0 thành công của T | Số lũy kế của snapshot D0 mới nhất (SKU × FC vắng = 0, vì snapshot đọc cả bộ dữ liệu) | `PROVISIONAL` (`D0_INTRADAY` cho hôm nay, `D0_LAST_READ` cho ngày đã qua) |
| Không có gì | — | `NO_ACTUAL` (`NO_D0_READ_TODAY` / `NOT_LOADED_YET`), không bao giờ thành 0 |

**1.2.9 (đợt 7, quy tắc của chủ sở hữu ngày 20/10/2026): "Đã hoàn tất" = đã chốt từ D-1.** Một ngày chỉ là
`COMPLETE` khi đã được chốt (đóng băng) từ lần D-1 thành công đã ghi ngày đó (mục 15). Từ đó con số không đổi nữa.

**Trước 1.2.9 (nguyên nhân màn hình mãi "Tạm tính").** Bằng chứng duy nhất được chấp nhận là `audit_log` `D1_SYNC`
có `mode = SIGNAL`, mà chế độ này chỉ có khi cấu hình `bigquery.completion_table`. Production chạy D-1 ở chế độ
`FALLBACK_TIME_VERIFIED` (kiểm tra đủ số dòng sau giờ dự phòng), nên không ngày nào thành "Đã hoàn tất": mọi ngày đã
qua mãi là "Tạm tính", hoặc "Đã chốt – cần xác minh" sau 23:59. Ngoài ra con số luôn đọc lại từ `demand_daily`, nên mỗi
lần D-1 nạp lại thì số của ngày cũ cũng đổi.

Ngày chưa chốt: nguồn cập nhật hồi tố (D-1 nạp lại trong cửa sổ late-data) thì thực tế hiển thị theo số mới. "Thực tế
tính đến" (`loaded_at` hoặc thời điểm snapshot) cho biết số đang thấy là của lần nạp nào. Ngày đã chốt: không bao giờ
đổi; ô thực tế ghi "đã chốt lúc".

## 4. KPI, sai lệch, WAPE

Tất cả tính trên **đúng tập dòng của bộ lọc**: phạm vi ngày chạy, FC, SKU / tên, trạng thái thực tế. KPI, biểu đồ,
bảng và Excel dùng chung truy vấn `forecast_history.Query`.

- **Forecast (1.2.9)** = số lượng dự báo **nguyên** của `app/qty.py`: làm tròn nửa lên giá trị đã lưu, không âm, cho
  phép 0. Là đúng số của trang Kết quả dự báo và Excel của run. Bảng, biểu đồ, KPI, sắp xếp và Excel dùng số này;
  `yhat` đã lưu không đổi, vẫn có trong API và khi di chuột lên ô Forecast. Trước 1.2.9 trang này dùng `yhat` (số lẻ).
  Chỉ số chất lượng mô hình (backtest, quality gate, thẻ accuracy của trang Kết quả) vẫn tính trên `yhat`.
- **Tổng forecast đã lưu** = Σ forecast của mọi dòng (không đổi).
- **1.2.9 (đợt 7) — KPI chính chỉ trên dòng đã chốt** (`kpi.basis = FINALIZED_ONLY`):
  - **Thực tế đã hoàn tất** = Σ thực tế của các dòng có trạng thái `COMPLETE`;
  - **Sai lệch (đã chốt)** = Σ forecast − Σ thực tế, trên cùng các dòng đó;
  - **WAPE (đã chốt)** = Σ|forecast − thực tế| / Σ thực tế, và **bias** = (Σ F − Σ T) / Σ T, trên cùng các dòng đó;
    đúng công thức của `ml/metrics.py` (công thức không đổi, chỉ đổi tập dòng).
  - Không có dòng đã chốt: các thẻ ghi "Chưa có actual đã chốt" (`notes = NO_FINAL_ACTUAL`, `status = NO_ACTUAL`).
    Tổng thực tế đã chốt = 0: WAPE không tính (`SUM_ACTUAL_ZERO`).
- **Dòng chưa chốt tính riêng:** `kpi.provisional` (`PROVISIONAL`) và `kpi.closed` (`CLOSED`, đã chốt 23:59 nhưng chưa
  chốt từ D-1), mỗi nhóm có số dòng, số ngày, tổng thực tế, forecast cùng dòng, sai lệch, WAPE, bias. Màn hình hiện
  chúng ở thẻ "Thực tế chưa chốt — xem riêng, không phải chất lượng mô hình". Không bao giờ gộp vào KPI chính.
- **Cơ sở so sánh** (`kpi.coverage`): số dòng / ngày đã hoàn tất, tạm tính, đã chốt cuối ngày, chưa có thực tế (không
  tính 0). `kpi.n_zero_absent`: số dòng đã hoàn tất = 0 vì SKU × FC không có dòng trong ngày (ngày đã đọc trọn).
- **WAPE dòng** = |F − T| / T, chỉ khi T > 0 (không đổi).
- Trước 1.2.9: KPI gộp mọi dòng có thực tế và chỉ gắn nhãn "Tạm tính" / "Đã chốt – cần xác minh" / "Đã hoàn tất".
- **1.2.6 — WAPE trong ngày giữ nguyên.** Mỗi lần D-0 cập nhật, WAPE được tính lại theo đúng công thức trên, kể cả
  khi thực tế đang là số lũy kế còn forecast là số cả ngày (chủ sở hữu đã chấp nhận). Bản chốt 23:59 chỉ đổi nhãn
  trạng thái, không đổi con số (test và bản sao DB: cùng WAPE khi có / không có lớp chốt). Từ 1.2.9 WAPE trong ngày
  nằm ở nhóm tạm tính, không ở KPI chính.
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
| `/api/history/export.xlsx?…&lang=vi\|en` | Excel (định dạng H2 từ 1.2.6; H3 từ 1.2.9: cột Forecast là số nguyên) |

1.2.6 chỉ **thêm** trường và tham số (`forecast_source=PRIMARY|SNAPSHOT`, `actual_status` thêm `CLOSED`); trường cũ
giữ nguyên. Đường dẫn không đổi, nên allowlist của proxy chỉ đọc không cần sửa.

1.2.9 (đợt 7) thêm: `overview.finalization` (`finalized_days`, `blocked_days`, `last_finalized_date`, `applicable`);
`summary.kpi.basis`, `provisional`, `closed`, `coverage`, `n_zero_absent`; mỗi ngày `actual_final` (provenance của bản
đóng băng), `actual_finalization` (lý do chưa chốt được), `n_zero_absent`; mỗi dòng `actual_present`, và
`actual_source = FINAL` cho ngày đã chốt. **Đổi nghĩa:** `kpi.actual_total`, `deviation`, `wape`, `bias`,
`n_rows_compared`, `days_compared`, `status` giờ chỉ của dòng đã chốt.

`q` tìm theo một phần SKU / tên, không phân biệt hoa thường, không cần dấu. Mặc định là 30 ngày chạy, kết thúc ở ngày
chạy mới nhất có lịch sử; tối đa 400 ngày mỗi yêu cầu.

## 7. Excel

Gồm 4 sheet: Thông tin (bộ lọc, KPI, quy tắc), Phiên forecast, Theo ngày, Chi tiết SKU × FC.

- Xuất **toàn bộ** dòng khớp bộ lọc, không chỉ trang đang xem.
- Ghi bằng openpyxl write-only.
- Quá 1.000.000 dòng thì từ chối với lỗi `HISTORY_EXPORT_TOO_LARGE`, không bao giờ cắt bớt.
- Thực tế trống nghĩa là chưa có dữ liệu, không phải 0.
- Trạng thái ghi bằng chữ: "Tạm tính" / "Đã chốt - cần xác minh" / "Đã hoàn tất" / "Chưa có dữ liệu thực tế".
- 1.2.9 (định dạng H3): vị trí cột không đổi. Cột Forecast của sheet chi tiết, tổng theo ngày, sai lệch và WAPE dùng
  số lượng nguyên (mục 4); "Cách tính" ở sheet Thông tin ghi rõ quy tắc.
- 1.2.9 đợt 7 (định dạng H4): các dòng Tổng thực tế / Sai lệch / WAPE của sheet Thông tin là của dòng **đã chốt**;
  nối thêm vào cuối sheet Thông tin: cơ sở tính, số dòng theo nhóm, tổng và WAPE riêng của nhóm tạm tính và nhóm đã
  chốt cuối ngày, số dòng = 0 vì không có đơn, quy tắc thực tế đã hoàn tất. Vị trí các dòng / cột cũ không đổi.
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
- **1.2.9:** thực tế chỉ "Đã hoàn tất" khi đã chốt từ D-1 (mục 15); trước 1.2.9 không ngày nào đạt vì production không
  có tín hiệu hoàn tất (mục 3).
- **1.2.6 — dung lượng snapshot dự phòng.** Mỗi snapshot hoàn chỉnh lưu 7 × số chuỗi SKU × FC. Đo trên bản sao DB
  ngày 18/10/2026: 119.889 dòng, khoảng 11,8 MB mỗi ngày, tức khoảng 4,3 GB mỗi năm nếu chạy mỗi ngày. Chủ sở hữu
  quyết định lưu **90 ngày** (18/10/2026): khoảng 90 × 11,8 MB ≈ 1,1 GB khi dọn đều đặn. Dọn bằng tay, dry run trước
  (mục 14). Sau khi một snapshot quá 90 ngày bị xóa, ngày chạy chỉ có forecast dự phòng từ snapshot đó sẽ trống trên
  màn hình (không có số, không điền 0).

## 9. Rollback

**1.2.6 (schema 6):** bản 1.2.5 từ chối DB schema 5 và 6, nên rollback = khôi phục bản sao lưu trước nâng cấp (bản
`deploy-upgrade` tạo trước khi hỏi xác nhận, hoặc bản `pre-migration-v4` tự tạo khi nâng cấp) **bằng `restore.ps1` của
thư mục 1.2.5** (bản của 1.2.6 sẽ migrate lại DB vừa khôi phục lên schema 6), rồi `rollback-version.ps1 -To 1.2.5`. Mất
snapshot cuối ngày, bản chốt, bản ghi dọn snapshot và mọi dữ liệu khác ghi sau thời điểm sao lưu (job, snapshot D0,
D-1, forecast publish sau nâng cấp). DB schema 6 lúc khôi phục vẫn được giữ trong file `backup-…-pre-restore.zip` tự
tạo. Cách hạ schema thủ công (`DROP TABLE` các bảng của 0005/0006) là thao tác phá hủy, cần phê duyệt riêng.

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

Job `EOD_FORECAST_SNAPSHOT`, flow `eod` trên trang Lịch chạy dữ liệu, giờ mặc định **23:55** (giờ Việt Nam), mặc định
**TẮT**. Chủ sở hữu quyết định (18/10/2026): chỉ bật trên trang Lịch chạy dữ liệu sau khi kiểm tra sau deploy đạt và
được cho phép. Thiết lập đã lưu mà không có khóa `eod_enabled` (mọi bản cài nâng cấp từ 1.2.5) cũng đọc là TẮT;
migration không ghi thiết lập nào. Lựa chọn đã lưu của người vận hành không bị ghi đè.

| Quy tắc | Cách triển khai |
|---|---|
| Ngày nghiệp vụ S | Ngày Việt Nam của mốc lịch (`params.business_date`). Chạy lại sau nửa đêm (grace, retry, chạy bù) vẫn là S. Chạy thủ công lấy mốc gần nhất **đã qua**: trước 23:55 là hôm qua, không bao giờ snapshot một ngày chưa kết thúc. |
| Phiên nguồn | Phiên chính thức (`forecast_history_days`) của **ngày chạy mới nhất ≤ S**, đúng quy tắc chọn phiên hiện có. Trước khi chụp, job ghi nhận các run đã publish mà lịch sử chưa có (`forecast_history.reconcile()`, idempotent, như lúc khởi động). Không huấn luyện, không forecast, không publish, không đọc BigQuery. |
| Phạm vi 7 ngày | Ngày được dự báo S+1 … S+7 (D+1 = ngày chạy + 1, như lịch sử D+1). Grain SKU × FC × ngày, đúng dòng của `forecast_values` (kèm `horizon_day` trong run nguồn). |
| `COMPLETE` | Chỉ khi run nguồn có **mọi** chuỗi của nó ở **cả 7 ngày**. Bản sao được kiểm lại số dòng và tổng trong cùng transaction. Lệch thì cả transaction rollback, không lưu snapshot nào (kể cả dòng đầu mục), và job kết thúc **FAILED** với alert ERROR `EOD_SNAPSHOT_VERIFY_FAILED`. Lỗi này **không tự thử lại**: `jobs/runner.py` chỉ thử lại lỗi tạm thời (`Retryable`, `TIMEOUT`), lỗi không phải `AppError` và `BQ_ERROR` / `BQ_AUTH_MISSING`; mốc lịch của ngày đó cũng không được lên lịch lại. Người vận hành kiểm tra rồi chạy lại bằng tay ("Chạy ngay"). |
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

Job `ACTUAL_CLOSE`, flow `close`, giờ mặc định **23:59** (giờ Việt Nam), mặc định **TẮT** như flow `eod` (mục 10).
Giờ của cả hai flow phải trong khoảng 20:00–23:59, vì chúng đại diện cho cuối ngày.

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

- **Lịch.** Hai flow mới có công tắc và giờ riêng trên trang Lịch chạy dữ liệu (`/api/schedules/eod|close`), mặc định
  TẮT. Bật/tắt chỉ qua trang này (`SCHEDULE_SWITCH_VIA_FLOW_API`). Khi bật, thời điểm bật được lưu (`eod_enabled_at` /
  `close_enabled_at`): mốc trước thời điểm đó không bao giờ chạy. Khi TẮT, scheduler không lên lịch job nào và một job
  theo lịch / thử lại của flow TẮT bị bỏ qua (`EOD_SCHEDULE_DISABLED` / `CLOSE_SCHEDULE_DISABLED`). Không đổi giờ D-0 /
  D-1 / huấn luyện.
- **Cấu hình (card riêng cho từng flow).** Mỗi flow lưu `enabled`, giờ (`eod_time` / `close_time`), múi giờ
  (`eod_timezone` / `close_timezone`) và thời điểm bật trong thiết lập `schedule` (có lịch sử thiết lập và audit
  `SCHEDULE_CHANGED`). Giá trị mặc định chỉ định nghĩa một chỗ (`ScheduleSettings`): TẮT, 23:55 / 23:59,
  `Asia/Ho_Chi_Minh`; API trả kèm `defaults` và `config_updated`. Scheduler, job và UI đọc cùng thiết lập này; không có
  giờ nào viết cứng trong logic (giờ cắt của bản chốt lấy từ `close_time`).
  - **Kiểm tra khi lưu (422, không lưu gì):** giờ phải là HH:MM từ 20:00 tới 23:59; múi giờ chỉ được là
    `Asia/Ho_Chi_Minh` (ngày nghiệp vụ là ngày Việt Nam); hai flow không được cùng một phút.
  - **Bật phải được scheduler xác nhận.** Bật `eod` / `close` chỉ khi scheduler đang chạy trong tiến trình app; sau
    khi lưu, `Scheduler.reload()` phải xác nhận flow đã nạp. Không xác nhận (hoặc lỗi) thì công tắc được trả về TẮT
    (audit ghi lý do) và API trả 409 `SCHEDULE_NOT_REGISTERED`: UI không bao giờ báo BẬT giả.
  - **Trạng thái runtime** (`runtime.state`): `REGISTERED` (bật và scheduler đã nạp, chờ giờ chạy), `PENDING` /
    `RUNNING` / `RETRY_WAIT` (có job của flow đang xử lý), `NOT_REGISTERED` (tắt hoặc chưa nạp: không có lần chạy).
  - **Chạy thử** `GET /api/schedules/eod|close/preview`: tính kết quả lần chạy tới cho ngày hôm nay (snapshot:
    trạng thái, run nguồn, số dòng, ngày thiếu; chốt: nguồn, trạng thái, số dòng, tổng, ngày sẽ có revision mới) bằng
    đúng quy tắc của job, chỉ đọc: không tạo job, không ghi bảng nào, không gọi BigQuery. Link từ xa trả 403 cho
    endpoint này (proxy không đổi).
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
- **`data-check`** có thêm 6 kiểm tra:
  - `eod_snapshot_complete`: đầu mục COMPLETE đủ 7 ngày × chuỗi; đếm giá trị trong 14 ngày gần nhất; snapshot khác không có giá trị;
  - `eod_snapshot_values_match_source`: 14 ngày gần nhất, giá trị bằng forecast đã publish;
  - `actual_close_revisions`: revision 1..n liên tiếp, đủ số dòng;
  - `eod_snapshot_retention_due` (WARN): còn snapshot quá 90 ngày chờ dọn, đúng kế hoạch của dry run; snapshot được
    giữ vì còn là dự phòng trong 90 ngày không bị liệt kê (mục 14);
  - `eod_backup_protection_triggers` (FAIL): thiếu một trigger bảo vệ của 0005 / 0006;
  - `eod_snapshot_retention_records` (FAIL): bản ghi dọn còn ở `DELETING`, snapshot đã ghi xóa vẫn còn, hoặc số dòng
    xóa khác số dòng ghi nhận.

**Bảng (migration 0005, chỉ thêm):**

| Bảng | Vai trò | Khóa |
|---|---|---|
| `forecast_eod_snapshots` | Đầu mục snapshot: ngày nghiệp vụ, khoảng ngày, run / phiên / model nguồn, số dòng, số ngày bao phủ, ngày thiếu, tổng, sha256, trạng thái + lý do, múi giờ, job, số lần thử, thời điểm tạo / cập nhật | PK `id`; UNIQUE `(scope_key, business_date)` |
| `forecast_eod_snapshot_values` | Giá trị 7 ngày (SKU, FC, ngày, horizon, forecast, method); chỉ cho snapshot COMPLETE; bất biến | PK `(snapshot_id, target_date, sku_id, fc_id)`, WITHOUT ROWID |
| `actual_closes` | Bản chốt và các revision: nguồn, tham chiếu, thời điểm đọc nguồn, số dòng, tổng, sha256, trạng thái, revision trước, tổng trước, số đổi / thêm / bớt, giờ cắt, thời điểm chốt, job; bất biến | PK `id`; UNIQUE `(scope_key, business_date, revision)` |
| `actual_close_values` | SKU × FC × số lượng của từng revision; bất biến | PK `(close_id, sku_id, fc_id)`, WITHOUT ROWID |

## 14. Lưu snapshot cuối ngày 90 ngày (1.2.6, migration 0006)

Chủ sở hữu quyết định (18/10/2026): snapshot forecast cuối ngày được lưu **90 ngày**. Mã nguồn `backend/app/eod_retention.py`,
lệnh `app.cli eod-retention`, script `scripts\eod-retention.ps1`.

| Quy tắc | Cách triển khai |
|---|---|
| Tuổi | Theo **ngày nghiệp vụ** của snapshot (`business_date`, ngày Việt Nam mà snapshot đại diện). Không theo giờ tạo UTC, không theo tuổi file. |
| Hết hạn | `business_date < ngày cắt`, với ngày cắt = hôm nay (giờ Việt Nam) − 90 ngày. Snapshot **đúng 90 ngày** được giữ. Ví dụ ngày 18/10/2026: ngày cắt 20/07/2026, snapshot 19/07 bị xóa, 20/07 được giữ. Snapshot của ngày nghiệp vụ 18/10/2026 (nếu có) được giữ tới hết 16/01/2027 và có thể xóa từ 17/01/2027. |
| Mọi trạng thái | `COMPLETE`, `INCOMPLETE`, `NO_SOURCE` hết hạn như nhau. Hai loại sau chỉ có dòng đầu mục, không có giá trị. |
| Giữ lại | Snapshot COMPLETE đã hết hạn nhưng **còn là dự phòng hiển thị** cho một ngày chạy trong 90 ngày (không có snapshot mới hơn ở giữa) được giữ, lý do `SERVES_BACKUP_INSIDE_WINDOW`, tới khi ngày chạy đó ra khỏi cửa sổ. Snapshot có số giá trị khác dòng đầu mục cũng được giữ (`VALUES_DO_NOT_MATCH_HEADER`, data-check báo). Nếu có bảng khác tham chiếu bảng snapshot thì từ chối cả lần chạy (`EOD_RETENTION_UNKNOWN_REFERENCE`). |
| Không bao giờ xóa | `forecast_values`, lịch sử D+1, bản chốt thực tế, log, job hay bảng khác. |
| Dry run | Mặc định của lệnh. Mở DB chỉ đọc, in kế hoạch: số snapshot, số dòng, khoảng ngày, theo trạng thái, danh sách từng snapshot, các snapshot được giữ và lý do, số còn lại, `plan_id`. Không ghi gì. |
| Xóa thật | Chỉ khi có `--apply --plan <plan_id>` của lần dry run đã duyệt. Kế hoạch đổi (thêm/bớt snapshot) thì `plan_id` đổi và lệnh từ chối (`EOD_RETENTION_PLAN_CHANGED`). Trước khi xóa tạo một bản sao lưu đã kiểm tra (`backup-…-pre-eod-retention.zip`, `integrity_check`). |
| Transaction | Mỗi snapshot một transaction `BEGIN IMMEDIATE`: ghi phiếu xóa `DELETING` → xóa giá trị → xóa đầu mục → phiếu thành `DELETED`, kiểm lại không còn dòng nào trước khi commit. Lỗi ở một snapshot thì snapshot đó rollback trọn vẹn, lần chạy dừng, ghi `audit_log` và alert ERROR `EOD_RETENTION_FAILED`; các snapshot đã xóa trước đó vẫn có bản ghi. Chạy lại thì tiếp tục, không xóa hai lần. |
| Nhật ký | Mỗi snapshot đã xóa có một dòng vĩnh viễn trong `forecast_eod_snapshot_retention` (id, ngày, trạng thái, run nguồn, số dòng, sha256, tổng, ngày cắt, bản sao lưu, thời điểm). Mỗi lần chạy có `audit_log` `EOD_SNAPSHOT_RETENTION_STARTED` (trước lần xóa đầu: kế hoạch, bản sao lưu) và `EOD_SNAPSHOT_RETENTION` (sau cùng: số dự kiến và thực tế, khoảng ngày, thời điểm, kết quả). |
| Không tự động | Migration 0006 **không xóa gì**. Không có lịch tự dọn; scheduler không bao giờ chạy việc này. |

**Bảo vệ ở database (trigger 0006).** Migration 0006 thay hai trigger cấm xóa của 0005 trong cùng một transaction, nên
không có lúc nào bảng mất bảo vệ. Lệnh DELETE trên `forecast_eod_snapshots` / `forecast_eod_snapshot_values` vẫn bị từ
chối, trừ khi đủ cả các điều kiện sau:

- có phiếu `DELETING` cho đúng snapshot đó (id, scope, ngày), và phiếu là lần INSERT gần nhất của **chính connection
  đang xóa** (`seq = last_insert_rowid()`). `eod_retention.py` cấp cho mỗi phiếu một `seq` ngẫu nhiên 62 bit, nên trên
  thực tế không INSERT nào vào bảng khác trùng được: connection khác không dùng được phiếu, và một INSERT khác sau
  phiếu làm phiếu mất hiệu lực;
- ngày nghiệp vụ trước ngày cắt của phiếu **và** trước `date('now', '+7 hours', '-90 days')` do chính SQLite tính.
  Việt Nam là UTC+7, không đổi giờ mùa hè. Snapshot chưa đủ 90 ngày không thể bị xóa, dù ứng dụng tính sai;
- giá trị phải xóa trước; đầu mục còn giá trị thì bị từ chối.

Phiếu chỉ ghi được khi không có phiếu nào khác đang mở. Phiếu không bao giờ bị xóa và chỉ đổi được một lần, từ
`DELETING` sang `DELETED`, khi snapshot đã hết dòng.

`INSERT OR REPLACE` xóa dòng bị trùng khóa mà không kích hoạt trigger xóa, vì SQLite chỉ kích hoạt khi bật
`PRAGMA recursive_triggers`, và ứng dụng không bật. Vì vậy 0006 thêm trigger từ chối mọi INSERT trùng khóa trên cả năm
bảng của 1.2.6 (`*_no_replace`), trước khi xung đột được giải quyết. Ứng dụng không dùng REPLACE trên các bảng này;
một INSERT trùng thường vốn đã lỗi. Chỉ lệnh DDL (xóa trigger hoặc bảng) mới vượt được các bảo vệ này; `data-check`
`eod_backup_protection_triggers` báo FAIL khi thiếu trigger.

**Phiếu `DELETING` còn sót.** Ứng dụng không thể để sót phiếu: phiếu và việc xóa nằm trong cùng một transaction, lỗi
thì rollback cả hai. Phiếu sót chỉ có thể do SQL gõ tay. Khi đó `data-check` báo FAIL, mọi lần dọn sau bị từ chối
(không ghi được phiếu mới), và phiếu không dùng được cho connection khác. Không sửa DB để gỡ. Dừng dọn, giữ nguyên, và
xin phê duyệt một bước bảo trì riêng: khôi phục bản sao lưu trước đó, hoặc gỡ phiếu có kiểm soát.

**Dung lượng.** Xóa không làm file DB nhỏ đi: SQLite giữ các trang đã giải phóng để dùng lại cho snapshot mới (không
chạy `VACUUM`). Đo trên bản sao 18/10/2026: xóa 119.889 dòng mất khoảng 2 giây. Mỗi lần `-Apply` có việc cần xóa tạo
thêm một bản sao lưu (DB + model, khoảng 76 MB). Thư mục `backups` không tự dọn.

**Vận hành** (sau khi bật 1.2.6; lần đầu có snapshot hết hạn khoảng 90 ngày sau ngày bật flow `eod`):

```powershell
scripts\eod-retention.ps1                          # dry run: đọc kế hoạch, ghi lại plan_id
scripts\eod-retention.ps1 -Apply -Plan <plan_id>   # xóa đúng kế hoạch đó (tự sao lưu trước)
```

Sau khi xóa, ngày chạy chỉ có forecast dự phòng từ snapshot đó sẽ trống trên màn hình: không có số, không điền 0, KPI
không tính ngày đó.

| Bảng (migration 0006, thêm) | Vai trò | Khóa |
|---|---|---|
| `forecast_eod_snapshot_retention` | Phiếu xóa và nhật ký vĩnh viễn của mỗi snapshot đã xóa: lần chạy, snapshot, scope, ngày, khoảng ngày, trạng thái snapshot, run nguồn, số dòng, sha256, tổng, ngày tạo snapshot, số ngày chính sách, ngày cắt, trạng thái phiếu, số dòng đã xóa, người yêu cầu, bản sao lưu, thời điểm | PK `seq` AUTOINCREMENT; UNIQUE `snapshot_id` |

## 15. Thực tế đã hoàn tất: chốt từ D-1 và đóng băng (1.2.9, đợt 7)

Quy tắc của chủ sở hữu (20/10/2026): thực tế của một ngày đã qua được chốt từ lần D-1 thành công và không bao giờ đổi
nữa. Mã nguồn `backend/app/actual_final.py`; migration `0009_actual_finalization.sql`; test
`backend/tests/test_v129g_actual_final.py`, `frontend/src/v129g-final.test.tsx`.

| Quy tắc | Cách triển khai |
|---|---|
| Ngày được chốt | Ngày nghiệp vụ Việt Nam T (= `demand_daily.order_date`, tức `created_date` của nguồn). Không bao giờ là hôm nay hay ngày tương lai. D-1 chạy ngày 20/10 nạp tới 19/10 (`today_vn() - 1`), nên T = 19/10 được chốt ngay sau lần đó. |
| Bằng chứng | Một lần D-1 ghi trọn các ngày trong cửa sổ của nó trong một transaction, mọi dòng cùng `loaded_at` = `synced_at` của lần nạp, và `audit_log` `D1_SYNC` của lần nạp nằm trong cùng transaction. T chỉ được chốt khi: mọi dòng của T có cùng một `loaded_at`; có đúng một `D1_SYNC` của scope với `synced_at` đó; chế độ là `SIGNAL`, `FALLBACK_TIME_VERIFIED` hoặc `BACKFILL` (quy tắc kiểm tra nguồn đủ dữ liệu sẵn có: tín hiệu hoàn tất, hoặc sau giờ dự phòng với số dòng ≥ tỷ lệ × trung bình 7 ngày, hoặc backfill có preview READY); cửa sổ của lần nạp bao trùm T; ngày Việt Nam của lần nạp sau T; mọi dòng có SKU, FC, số lượng ≥ 0. D-1 thất bại không commit gì nên không bao giờ dẫn tới chốt. |
| Chưa chốt được | Ghi `BLOCKED` kèm lý do (`NO_VERIFIED_D1_LOAD`, `MIXED_LOADS`, `LOAD_WINDOW_DOES_NOT_COVER_DAY`, `LOADED_BEFORE_DAY_ENDED`, `D1_MODE_NOT_ELIGIBLE`, `AMBIGUOUS_D1_LOAD`, `INVALID_ROWS`); ngày đó vẫn hiện số sống, trạng thái tạm tính / đã chốt 23:59. Một lần nạp hợp lệ sau đó có thể chốt nó (`BLOCKED` → `FINALIZED`, không bao giờ ngược lại). Ngày không có dòng nào không phải ứng viên (màn hình ghi "chưa có dữ liệu thực tế", không tính 0). |
| Đóng băng | Mỗi ngày một transaction `BEGIN IMMEDIATE`: đầu mục + toàn bộ SKU × FC (số lượng, số đơn) + provenance (load id, job, `synced_at`, chế độ, cửa sổ, watermark, mapping hash, preview), số dòng, tổng, sha256; kiểm lại số dòng và tổng (so với chính nó và với `demand_daily`) rồi mới niêm phong (`sealed = 1`). Sai thì cả ngày rollback, không còn dòng nào. |
| Bất biến | Trigger 0009: không xóa, không đổi khóa, không `INSERT OR REPLACE`; ngày `FINALIZED` chỉ được niêm phong một lần, sau đó không cột nào đổi; giá trị không sửa / xóa được và không thêm được sau niêm phong; niêm phong bị từ chối khi số dòng / tổng không khớp. Lần D-1 sau báo số khác, nguồn sửa lịch sử, đơn hủy, SKU × FC vắng, nạp lại hay huấn luyện lại đều không đổi bản đóng băng. Sửa một ngày đã chốt cần một quy trình riêng có kiểm soát và audit — chưa có, không tự động. |
| Idempotent, thử lại | Ngày đã chốt không bao giờ được xét lại; chạy lại với cùng dữ liệu không ghi gì; ngày `BLOCKED` chỉ ghi lại khi lý do hoặc lần nạp đổi. Một ngày lỗi giữa chừng rollback riêng (alert ERROR `ACTUAL_FINALIZE_FAILED`), các ngày khác vẫn chốt; lần chạy sau (sau D-1 kế tiếp, hoặc lệnh dưới đây) thử lại. |
| Khi nào chạy | Ngay sau mỗi lần D-1 thành công đã commit (`sync._after_d1`), không bao giờ làm D-1 thất bại. Lệnh `python -m app.cli actual-finalize` = chạy thử chỉ đọc (cả trên DB trước migration 0009, để đo tác động nâng cấp; `--db <file>` cho một bản sao); `--apply` = chốt trên DB đang cấu hình. Không gọi BigQuery, không ghi `demand_daily`, forecast, lịch sử D+1 hay bản chốt 23:59. |
| Phạm vi | Chỉ nguồn BIGQUERY (D-1). DEMO / Excel không có D-1: không bao giờ chốt (màn hình nói rõ). |
| Chốt 23:59 | Giữ nguyên quy tắc 1.2.6 (mục 12), kể cả `CLOSED_VERIFIED` theo tín hiệu và revision khi dữ liệu đến muộn. Ngày đã chốt từ D-1 hiện "Đã hoàn tất" và số của bản đóng băng; `actual_close.current` không áp dụng (`null`). |

**Dữ liệu cũ khi nâng cấp.** Migration 0009 chỉ tạo bảng rỗng, không gán trạng thái cho dòng nào. Ngày cũ chỉ được chốt
ở lần chạy đầu tiên sau nâng cấp (D-1 kế tiếp hoặc `--apply`), và chỉ khi các dòng của nó truy được về một lần D-1 đã
xác minh như trên; không ngày nào được coi là chốt chỉ vì đã qua. Đo trên bản sao DB production lúc 20:19 ngày
20/10/2026 (schema 6 → 9):

- Chạy thử trước migration: 292/292 ngày (01/01–19/10) truy được về lần nạp đã xác minh; 0 ngày bị chặn.
  - 285 ngày đến từ lần D-1 nạp lại toàn bộ (`JOB-20261017125803-0ED367`, 17/10 20:00 giờ VN,
    `FALLBACK_TIME_VERIFIED`, `full_reload`).
  - 7 ngày (13/10–19/10) đến từ các lần D-1 tăng dần (18/10, 19/10, 20/10).
  - Các lần nạp của 1.2.8 không ghi `load_id`; provenance của chúng là `synced_at` + `job_id` (cùng audit `D1_SYNC`).
- Migration 28,6 giây (kèm sao lưu `pre-migration-v6`). Chỉ thêm hai bảng rỗng. `demand_daily` chỉ thêm cột NULL của
  0007 / 0008; không bảng nào khác đổi.
- Chốt 292 ngày:
  - 1.358.317 dòng, 42.023.217 đơn vị;
  - khoảng 38 giây ghi, cộng khoảng 35 giây lập kế hoạch ở lần đầu;
  - DB tăng khoảng 81 MB;
  - 100% dòng của bản đóng băng bằng `demand_daily` tại thời điểm chốt.
- Chạy lại: không ghi gì, 0,3 giây.
- `data-check`: `actual_final_sealed` và `actual_final_protection_triggers` đều OK.
- Màn hình (cùng bản sao): 18/10 và 19/10 chuyển từ "Đã chốt – cần xác minh" sang "Đã hoàn tất".
  - KPI đã chốt: WAPE 73,0%, bias +14,8% trên 34.252 dòng.
  - 20/10 (hôm nay) vẫn tạm tính và nằm ở nhóm riêng.

Hệ quả cần biết: các ngày cũ được chốt theo số mà lần nạp đã xác minh gần nhất của ngày đó ghi (với production: lần nạp
lại toàn bộ ngày 17/10, cộng các lần nạp tăng dần sau đó). Nguồn đã sửa lịch sử khoảng −0,03% từ đó (báo cáo đợt 5).
Nếu muốn các ngày cũ phản ánh nguồn mới nhất, backfill có preview phải chạy **trước** lần chốt đầu tiên. Đây là quyết định
phát hành (thứ tự backfill / chốt), không phải quy tắc code.

**Quyết định của chủ hệ thống (20/10/2026 tối): backfill trước, rồi mới chốt lần đầu.** Diễn tập trên bản sao cô lập của DB
production lúc 21:22 (đợt 8, báo cáo `reports/demandforecast_upgrade_backfill_rehearsal_20261020.md`):

- **Nâng cấp 6 → 9:** 89,8 giây, gần như toàn bộ là sao lưu `pre-migration-v6`. Chỉ thêm 2 bảng và 10 trigger; mọi bảng cũ
  giữ nguyên nội dung trên các cột cũ.
- **Backfill 01/01–19/10:** preview READY mất 483 giây, ghi mất 804 giây.
  - Nguồn khác số đang lưu: 344 khóa mới, 213 khóa đổi số, 772 khóa nguồn đã bỏ; tổng −12.109 (−0,029%).
  - Sau backfill, 292/292 ngày truy về đúng một lần nạp `BACKFILL`; 0 ngày bị chặn.
- **Chốt:** 292 ngày, 1.357.889 dòng, 42.011.108 đơn vị; DB tăng khoảng 81 MB.
  - Đường CLI (`--apply`) và đường production (hook sau backfill) cho cùng giá trị và cùng sha256 từng ngày.
- **Khôi phục:** khôi phục bản sao lưu bằng mã 1.2.8 đưa DB về đúng trạng thái trước nâng cấp.

Lưu ý vận hành: **code không tự giữ thứ tự này.**

- Lần đầu tiên một D-1 (theo lịch hoặc bấm tay) hoặc một backfill chạy xong sau khi nâng cấp, hook sau D-1 chốt ngay mọi
  ngày truy được.
- Backfill tự chốt ngay sau khi ghi, không có khoảng dừng để xem lại. Phần xem trước tác động là preview của backfill.
- Vì vậy phải chạy preview + backfill **trước** lần D-1 kế tiếp sau nâng cấp. Nếu không, các ngày cũ sẽ bị chốt theo các
  lần nạp cũ.

| Bảng (migration 0009, chỉ thêm) | Vai trò | Khóa |
|---|---|---|
| `actual_finals` | Đầu mục mỗi scope × ngày: `FINALIZED` (niêm phong) hoặc `BLOCKED` + lý do; provenance của lần D-1; số dòng, tổng, số đơn, sha256; người / job chạy; số lần thử; thời điểm | PK `id`; UNIQUE `(scope_key, business_date)` |
| `actual_final_values` | SKU × FC × số lượng, số đơn của ngày đã chốt; bất biến | PK `(final_id, sku_id, fc_id)`, WITHOUT ROWID |

`data-check` thêm `actual_final_sealed` (đầu mục đã niêm phong, đủ số dòng / tổng; sha256 của 14 ngày gần nhất; ngày
`BLOCKED` không có giá trị) và `actual_final_protection_triggers` (đủ 10 trigger). Rollback về 1.2.8: khôi phục bản sao
lưu trước nâng cấp như với 0004–0008.
