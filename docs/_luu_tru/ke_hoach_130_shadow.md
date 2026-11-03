# Kế hoạch triển khai: dự báo mới chạy song song (SHADOW)

> **QUYẾT ĐỊNH CỦA CHỦ DỰ ÁN, 28/10/2026 khoảng 17:10 giờ VN: ĐÓNG BĂNG bản 1.3.0.**
> - Không làm C6: không đóng gói, không cài đặt, không promote `MV-20261028-165730-1A9F`.
> - Hai commit cục bộ `969ebe2` và `3701f8b` được giữ làm tài liệu tham khảo, **không push**.
> - **Lý do:** hướng dự báo đổi sang LightGBM thuần:
>   - không kết hợp Avg, không hệ số 2,2, không làm tròn cộng dồn;
>   - dự báo làm tròn ROUNDUP;
>   - đánh giá theo Đúng / Thiếu / Dư so với demand thực từng ngày.
> - Các câu hỏi về nguồn Avg, B7 và 7 điểm ở mục 3 **không còn áp dụng**.
> - Việc duy nhất còn lại: lập [thanh_phan_tai_su_dung.md](thanh_phan_tai_su_dung.md), chỉ đọc code.
> - Không chạy tác vụ nặng nào (huấn luyện, tái lập, backtest) trong lúc backtest LGBM7 đang chạy.

- **Branch:** `feature/du-bao-moi-20261028`, tách từ `main` @ `f82c890`.
- **Ngày lập:** 28/10/2026, giờ VN.
- **Trạng thái:** **KẾ HOẠCH, CHỜ CHỦ DỰ ÁN XÁC NHẬN.** Chưa sửa code, chưa đụng DB thật, chưa đụng production.
- **Bổ sung 28/10/2026 09:54 (giờ VN):** xem **mục 9**. Mục này thay một số điểm ở mục 1, 2, 3, 4b, 8. **C6 vẫn chưa làm** cho đến khi chủ dự án xác nhận kế hoạch.

**Căn cứ:**
- `reports\backtest-prereg-v2-20261027\`: V1 = trọng số horizon 3.0 khi h ≤ 7.
- `reports\backtest-prereg-fast-20261028\`.
- File bằng chứng `C:\Users\Giau Vo\Downloads\So sánh model LightGBM và AVG demand.xlsx`: mô phỏng tồn kho, tỷ lệ 0,35, hệ số 2,2.
- Khảo sát code `docs\project_map.md` (mục 1–14), kiểm lại ngày 28/10.

Đường dẫn bên dưới tính từ `backend/app/`, trừ khi ghi khác.

## 1. Kết quả kiểm tra dữ liệu C1 (chỉ đọc; dry run trước; trần 2 GB mỗi truy vấn)

Nhật ký truy vấn và script nằm ở scratchpad phiên làm việc (`c1\bq_queries.json`, `c1\probe.py`).

| Bước | Kết quả | Đạt? |
|---|---|---|
| 1.1 `openhours_by_sku`: cấu trúc | `fc_code, product_id, sku_code, item_code, product_name, seller_code, seller_class, open_date DATE, total_open_hours FLOAT64, total_open_days FLOAT64` | – |
| 1.1 Phủ 90 ngày | 30/07–25/10: 88 ngày, 4.455.792 dòng, 50.634 cặp; 0 NULL, 0 âm, 0 > 24 giờ. Mỗi SKU × FC × ngày chỉ có 1 giá trị (gộp MAX theo item không đổi gì) | – |
| 1.1 Khớp giờ ngày có đơn (bảng D-1, 90 ngày) | **98,92 %** (301.309 / 304.607). Toàn bộ 3.297 khóa thiếu là ngày **26/10**: bảng giờ mở bán, làm mới lúc 04:10 ngày 27/10, chỉ có đến **25/10 (D-2)**. Bỏ ngày đó: 301.309 / 301.310 (lệch 1). | **Không** đạt ≥ 99 % nếu tính D-1 |
| 1.2 Avg lịch sử theo luật B2 so với CSV T09 | 673.222 / 673.222 = **100 %**, khi làm tròn kiểu SQL ROUND (0,5 làm tròn lên). Làm tròn kiểu "về số chẵn" chỉ được 98,49 %. | Đạt |
| 1.3 Nguồn Avg của ngày D trước 05:00 | Xem mục 1.1 bên dưới | **Đang chờ kiểm tra lúc 05:00** |

### 1.1 Nguồn Avg (C1.3)

`NGUON_AVG_HOM_NAY = "CO"` không phải tên bảng. Dataset `gold_buymed_vn2` có:
- `fact_avg_demand_sku`: bảng hiện hành, không có `transformed_at`, cột `ingest_time` dạng chuỗi.
  - Được tạo lại lúc **00:15:02 ngày 28/10** (giờ VN).
  - Giá trị trùng **hoàn toàn** với bản ghi lịch sử ngày 27/10 (22.822 / 22.822 cặp, sau khi lọc MEDX và trạng thái OUT_OF_STOCK / LIMIT / NORMAL).
- `fact_avg_demand_sku_historical`: mỗi ngày 1 lần chạy, `transformed_at` = **15:10** (giờ VN theo `DATE(..., 'Asia/Ho_Chi_Minh')`).
  - Nhưng `last_modified_time` của bảng là **01:10 UTC = 08:10 giờ VN** ngày 27/10.
  - Vậy `transformed_at` có vẻ là giờ VN ghi vào kiểu TIMESTAMP (UTC), lệch 7 giờ. Lần ghi thật khoảng 08:10 giờ VN.
- `agg_avg_demand_sku_item_l30d`: view, cột `sku_fc_key, avg_demand_l30d, avg_demand_l15d`, không có ngày.

Chưa thấy nguồn nào có "Avg của ngày D tính lúc 02:00". Lúc 05:00 sẽ đo lại `ingest_time` và so giá trị với bản ghi 27/10:
- **Không có Avg của ngày 28/10:** DỪNG theo C1.3. B4 và B5 không chạy được như đặc tả, vì cần Avg của ngày D trước 05:55.

## 2. Chỗ cần sửa (file:hàm) và cách giữ hành vi cũ khi tắt

| Hạng mục | Chỗ sửa | Hành vi khi tắt |
|---|---|---|
| B1 trọng số horizon | `ml/model.py:train` (47–80): tính `w = where(X[:, horizon] <= cutoff, short, 1.0)` trước `lgb.Dataset` (`:72`), chỉ với DIRECT. Thêm `horizon_weight_short`, `horizon_weight_cutoff` vào `ModelSettings` (`settings_service.py:100`), mặc định `None`. | `None` thì `weight=None`, như cũ. **Rủi ro:** thêm field vào `ModelSettings` đổi `config_fingerprint` của mọi lần chạy mới (`ml/pipeline.py:409`). Cách xử lý: chỉ đưa field vào bản băm khi khác `None`. |
| B2 nguồn mới | Migration `0011_shadow_forecast.sql` (chỉ thêm bảng): `open_hours_daily`, `avg_demand_daily`. Module mới `bq/aux_sources.py` dùng `connector._client` / `_run` (dry run + trần). | Không nối vào `load_demand`, `build_panel`, `demand.fingerprint`, `mapping_hash`, SQL D-1. Luồng giờ mở bán của model giữ nguyên (`demand_daily.open_hours`, `data/open_hours.py`). |
| B3 phân nhóm | Module mới `ml/sku_group.py`; bảng `sku_group`; tác vụ tháng (ngày 1) và lần đầu khi bật. | Tắt thì không chạy. |
| B4 dự báo cuối | Module thuần `ml/postprocess.py` (kết hợp; hệ số × làm tròn cộng dồn có trạng thái; âm/NaN thành 0). Bảng mới lưu số cuối, trạng thái cộng dồn của Bán chậm và cờ AVG_MISSING. Section cấu hình mới `postprocess` (`forecast_blend_weight`, `slow_mover_factor`, `forecast_output_mode`) trong `SECTIONS` (`settings_service.py:563`); lịch sử tự có qua `ss.save`. | **Không** ghi đè `forecast_values.yhat` và không đổi `qty.SQL`, vì `extend_forecast` (`pipeline.py:675-687`) và WAPE/gate dựa vào chúng. |
| B5 làm mới dự báo | Loại job mới `FORECAST_REFRESH` (`jobs/runner.py:24,32`; handler dict). Lập lịch riêng trong `jobs/scheduler.py:plan` (50–166): chạy sau D-1 thành công VÀ có Avg của D, thử lại mỗi 10 phút đến 05:55, không áp `train_catchup_policy`. Dùng model đang dùng (`incumbent`, `pipeline.py:185`); panel dữ liệu mới đến D-1; **phải dùng `sku_codes` / `fc_codes` lưu trong model** (`pipeline.py:621`), vì mã danh mục của panel mới khác (`features.py:125-128`). Cần thêm tham số tùy chọn cho `model.forecast` / `_forecast_direct`, mặc định `None`. Thêm loại job mới vào khóa promote/extend (`pipeline.py:744,864`). | Công tắc lịch mặc định TẮT, theo mẫu `*_enabled_at` / `flows_first_seen` của 1.2.6, để nâng cấp không tự chạy. |
| B6 lưu hằng ngày | Bảng `forecast_daily_log`, `actual_daily` (migration 0011). Nguồn thực bán: `actual_final` / `actual_close` hiện có. | Chỉ ghi khi tính năng bật. |
| B7 / B8 theo dõi tuần và mô phỏng | Module mới `ml/shadow_monitor.py`, `ml/inventory_sim.py`; xuất .xlsx bằng `data/excel_io.py`; tác vụ thứ 2. | Tắt thì không chạy. |
| B9 SHADOW / LIVE | `forecast_output_mode` mặc định SHADOW. Chặn đổi qua `PUT /api/settings/{section}` chung và qua reset (`api/data_routes.py:30-74`). Endpoint riêng có xác nhận gõ chữ, ghi `settings_history` + audit. Màn hình Kết quả (`frontend/src/pages/Results.tsx`), API values/summary/export (`api/forecast_routes.py:275-399`): thêm cột Avg, LightGBM gốc, dự báo mới, nhóm và dòng "chạy song song – chưa dùng để mua hàng". | SHADOW: mọi con số hiện có giữ y nguyên; chỉ thêm cột. |
| Phiên bản | `backend/app/__init__.py:3`, `frontend/package.json:4`, `CHANGELOG.md`: 1.3.0. | – |

## 3. Điểm khác giả định và việc cần chủ dự án quyết định trước khi code

1. **Nguồn Avg ngày D trước 05:00** (mục 1.1): chưa tìm thấy. Nếu lúc 05:00 không có thì DỪNG theo C1.3.
2. **Giờ mở bán chỉ có đến D-2 lúc 04:10** (C1.1 không đạt nếu tính D-1). Ảnh hưởng: phân nhóm B3 (90 ngày, chậm 1 ngày) và cột `total_open_hours` của `actual_daily`. Sẽ đo lại sau 04:10 hôm nay.
3. **Avg đưa vào công thức B4: số thực hay số nguyên?**
   - File bằng chứng dùng **Avg đã làm tròn** (số nguyên, = `avg_demand_history` trong CSV = ROUND số thực, 0,5 làm tròn lên).
   - Bảng BigQuery có số thực (ví dụ 72,5 so với 73).
   - TÁI LẬP (C4) và mô phỏng B8 chỉ trùng file bằng chứng nếu dùng đúng loại Avg mà file đã dùng.
4. **Luật nhóm:**
   - Đặc tả B3: 90 ngày gần nhất; thêm luật "< 14 ngày mở bán thì Còn lại".
   - File bằng chứng: 01/06–31/08, "có đơn ≥ 24/30 ngày", không có luật 14 ngày.
   - Test B8 dùng nhóm 01/06–31/08. Cần xác nhận test B8 áp luật 14 ngày hay không.
5. **B5 lưu ở đâu:**
   - (a) Một dòng `forecast_runs` mới, liên kết với lần chạy gốc. Dashboard, sao lưu cuối ngày và lịch sử D+1 sẽ thấy lần chạy mới. Không gia hạn (extend) được lần chạy đó.
   - (b) Bảng riêng, chỉ dùng cho SHADOW.
   - Đề xuất: **(b)** trong SHADOW, vì không đụng luồng hiện có.
6. **Thư mục báo cáo tuần:** `paths.reports_dir()` của app (`<data>\reports\theo-doi-tuan\`) hay `reports\` của repo. App chạy ở máy production nên đề xuất thư mục của app.
7. **Tự đổi tỷ lệ kết hợp hằng tháng (B7):** đặc tả cho phép khi đủ 4 điều kiện. Thay đổi ghi lịch sử với ghi chú "tự động B7".

## 4. Chia task (sau khi được xác nhận và C1.3 đạt)

| Task | Mục tiêu | File được sửa | Tiêu chí xong |
|---|---|---|---|
| T0 | Sao lưu DB + cấu hình vào `D:\Buymed\Lightgbm AI\backups\`, thử khôi phục trên bản sao | (không sửa code) | Bản sao lưu đúng SHA; khôi phục trên LOCALAPPDATA riêng chạy `data-check` đạt |
| T1 | Test viết trước: B4 (kết hợp, nhóm, thiếu Avg, cộng dồn 0,3 × 2,2 × 10 ngày = 7), B1 tắt/bật | `backend/tests/test_v130_*.py` | Test đỏ trước khi code |
| T2 | B1 + cấu hình | `ml/model.py`, `settings_service.py` | Tắt: fingerprint và model trùng byte với bản cũ; bật: trùng V1 của backtest |
| T3 | Migration 0011 + B2 + B3 | `migrations/0011_*.sql`, `bq/aux_sources.py`, `ml/sku_group.py` | Chạy trên bản sao DB: số dòng / khóa trước và sau, `data-check` đạt |
| T4 | B4 + B6 | `ml/postprocess.py`, bảng mới | Test B4 đạt; TÁI LẬP 15/09, 01/10, 20/10 trùng 100 % |
| T5 | B5 + lịch | `jobs/runner.py`, `jobs/scheduler.py`, `ml/pipeline.py`, `ml/model.py` (tham số mã danh mục) | Rò rỉ: chỉ dữ liệu ≤ D-1 + Avg của D; lịch cũ không đổi |
| T6 | B7 + B8 | `ml/shadow_monitor.py`, `ml/inventory_sim.py` | Mô phỏng ra 202.144 / 195.590; 86.998 → 60.237; 1,63 → 1,33 (sai khác ≤ 0,5 %) |
| T7 | B9 + giao diện + xuất file | `api/*`, `frontend/src/pages/Results.tsx`, `Config.tsx`, `i18n.tsx` | SHADOW: số cũ y nguyên; LIVE chỉ qua xác nhận |
| T8 | Toàn bộ test, build, đóng gói, huấn luyện ứng viên (C5) trên bản sao, commit cục bộ, cài đặt (C6), chạy thử (C7) | `CHANGELOG.md`, phiên bản | Theo AGENTS.md mục 6, 7, 10 |

Mỗi task: `coder`, rồi `tester`, rồi `reviewer`; schema đi qua thêm `data-reviewer`.

## 4b. Điều chỉnh của chủ dự án (28/10/2026)

- Làm ngay C2–C5 trên branch này và trên bản sao; không đụng production.
- C1.3 vẫn kiểm tra lúc 05:00.
- C6–C7 chỉ làm khi C1.3 đạt **và** chủ dự án đã xác nhận kế hoạch, gồm 7 điểm ở mục 3.
- Nếu C1.3 không đạt: dừng trước C6, báo phương án thay thế, không tự đổi công thức.

Phương án tạm dùng cho 7 điểm (đều sửa được qua cấu hình hoặc chưa ảnh hưởng production):

| Điểm | Phương án tạm | Lý do |
|---|---|---|
| 3. Avg trong công thức | `blend_avg_value = ROUNDED` (Avg làm tròn kiểu SQL ROUND), có tùy chọn `RAW` | File bằng chứng dùng Avg số nguyên; mô phỏng mục 6.4 chỉ khớp với số nguyên |
| 4. Luật 14 ngày | Áp dụng (theo đặc tả B3). Test B8 chạy cả hai cách và ghi chênh lệch. | Đặc tả B3 ghi rõ |
| 5. B5 lưu ở đâu | (b) bảng riêng, không tạo `forecast_runs` mới | Không đụng luồng hiện có |
| 6. Thư mục báo cáo tuần | `paths.reports_dir()\theo-doi-tuan\` | `reports_dir` trong `storage.json` của máy này = `D:\Buymed\Lightgbm AI\reports`, nên trùng với `reports\theo-doi-tuan\` của đặc tả |
| 1. Nguồn Avg hôm nay | Cấu hình `avg_today_table` mặc định **rỗng**: chưa cấu hình thì tác vụ làm mới không chạy (`AVG_SOURCE_NOT_CONFIGURED`), không đoán bảng | C1.3 |
| `sku_system_status` | Không dùng, kể cả để lọc Avg; chỉ lọc `seller_code = MEDX` | Ràng buộc A |
| LIVE | Chỉ chuyển cờ (có xác nhận, ghi lịch sử). Ý nghĩa với màn hình và file xuất hiện có sẽ định nghĩa ở đợt sau. | Đặc tả chưa mô tả |

## 6. Thiết kế chi tiết đã chốt cho C3 / C4

### 6.1 Làm tròn

`R(x) = sign(x) × floor(|round(x, 6)| + 0,5)`: ROUND(ROUND(x, 6), 0) kiểu Excel / SQL, 0,5 làm tròn ra xa 0. **Không** dùng `np.rint` hay `round()` của Python, vì chúng làm tròn 0,5 về số chẵn.

### 6.2 Dự báo cuối (B4)

Hàm thuần `ml/postprocess.py`, theo từng chuỗi, cho mọi `h` trong khung:
- `avg_used = R(avg)` nếu `ROUNDED`, `avg` nếu `RAW`. Avg là Avg của **ngày lập dự báo**, dùng cho mọi `h`.
- **Bán chạy / Còn lại:**
  - Có Avg: `final_h = R(w × lgb_h + (1 − w) × avg_used)`, quy tắc `BLEND`.
  - Thiếu Avg (NaN): `final_h = R(lgb_h)`, quy tắc `BLEND_AVG_MISSING`, cờ `AVG_MISSING`.
- **Bán chậm** (quy tắc `SLOW_CUMULATIVE`):
  - `raw_h = lgb_h × factor`, LightGBM NaN tính là 0.
  - `c_0` = cộng dồn thô đã lưu trong trạng thái. Bằng 0 khi chưa có trạng thái hoặc khi nhóm đã đổi.
  - `c_h = c_{h−1} + raw_h`; `final_h = R(c_h) − R(c_{h−1})`.
  - Trạng thái mới chỉ cộng `raw_1`.
  - Chạy lại cùng ngày lập dự báo dùng lại `c_0` cũ, nên kết quả giống hệt.
- Sau cùng `final_h` âm hoặc NaN thành 0.
- Chuỗi không có trong `sku_group` xếp vào **Còn lại**, cờ `GROUP_MISSING`.

### 6.3 Phân nhóm (B3)

- Cửa sổ: 90 ngày kết thúc ở D-1 của ngày tính.
- Chỉ đếm ngày có `open_hours_daily.total_open_hours > 0`. Nhu cầu lấy `demand_daily.qty` của phạm vi đang dùng; ngày mở bán không có dòng nhu cầu tính là 0.
- Chỉ số mỗi chuỗi: `n_open_days`, `qty`, `avg_per_open_day = qty / n_open_days`, `zero_days`, `zero_share = zero_days / n_open_days`.
- Luật:
  - `n_open_days < 14` → Còn lại;
  - `avg > 20` và `zero_share ≤ 0,20` → Bán chạy;
  - `avg ≤ 5` và `zero_share > 0,20` → Bán chậm;
  - còn lại → Còn lại.
- Tính vào ngày 1 hằng tháng và lần đầu khi bật: tác vụ làm mới tự tính nếu tháng hiện tại chưa có nhóm.

### 6.4 Mô phỏng tồn kho (B8)

Đã tái lập file bằng chứng trong scratchpad, `c4\b8_proto.py`. Mỗi chuỗi có một dãy **ngày mở bán** theo thứ tự ngày (dòng = ngày mở bán). Hai cách, mỗi cách có dự báo `f` riêng:
- Cách **Avg**: `f` = Avg đã làm tròn.
- Cách **Mới**: `f` = dự báo cuối h = 1.
- NaN thành 0.

Từng ngày `i`:
- `về_i = đặt_{i−3}`;
- `tồn_đầu_i = tồn_cuối_{i−1} + về_i`;
- `bán_i = min(nhu_cầu_i, tồn_đầu_i)`;
- `mất_i = nhu_cầu_i − bán_i`;
- `tồn_cuối_i = tồn_đầu_i − bán_i`;
- `đặt_i = max(3 × f_i − (tồn_cuối_i + đặt_{i−1} + đặt_{i−2}), 0)`;
- `dư_i = max(tồn_cuối_i − Σ nhu_cầu_{i+1..i+3}, 0)`.

Chỉ số trên kỳ đo:
- mất bán/tuần = Σ mất ÷ (số ngày lịch / 7);
- hàng dư = Σ dư ÷ số ngày lịch;
- tồn kho (ngày bán) = Σ tồn cuối ÷ Σ nhu cầu.

Kỳ chạy từ 01/08, đo 01/09–22/10. Kết quả tái lập:
- Ngày mở bán theo bảng giờ mở bán, nhu cầu theo `demand_daily` của bản sao DB backtest.
- Hàng dư 87.018 / 60.248 (file bằng chứng 86.998 / 60.237): lệch ≤ 0,02 %.
- Tồn kho 1,619 / 1,328 (file 1,626 / 1,334): lệch ≤ 0,5 %.
- Mất bán/tuần 204.979 / 198.426 (file 202.144 / 195.591): **lệch +1,4 %**.
- Từng chuỗi khớp tuyệt đối ở 98–99,8 % số chuỗi.
- Phần lệch mất bán bằng đúng phần lệch nhu cầu đầu vào ở 261 chuỗi. Ví dụ MEDX.YF9DEQ1P|BD: file bằng chứng 20.157, mọi nguồn có trong máy 40.157, thiếu một ngày 20.000 sp. Nguồn nhu cầu của file bằng chứng chưa xác định.

### 6.5 Bảng mới (migration `0011_shadow_forecast.sql`, chỉ thêm)

- `open_hours_daily(fc_code, sku_code, open_date, total_open_hours, n_items, loaded_at)`, khóa (fc_code, sku_code, open_date).
- `avg_demand_daily(fc_code, sku_code, date, avg_demand, source, source_asof, read_at)`, khóa (fc_code, sku_code, date, source).
  - `source` = `HISTORY` (từ `fact_avg_demand_sku_historical`, ngày = DATE(transformed_at, 'Asia/Ho_Chi_Minh')) hoặc `TODAY` (nguồn Avg hôm nay đã cấu hình).
- `sku_group(fc_code, sku_code, group_code, computed_for, window_start, window_end, n_open_days, qty, avg_per_open_day, zero_days, zero_share, rule_version, computed_at)`, khóa (fc_code, sku_code, computed_for).
- `slow_mover_state(fc_code, sku_code, group_computed_for, last_forecast_date, cum_raw_before, cum_raw_after, updated_at)`, khóa (fc_code, sku_code).
- `shadow_forecast_runs(id, forecast_date, status, training_run_id, model_version, data_as_of, avg_source, avg_asof, n_series, config_version, job_id, created_at, detail_json)`.
- `forecast_daily_log(run_id, forecast_date, target_date, horizon, fc_code, sku_code, group_code, lgb_raw, avg_demand, avg_used, final_qty, rule, flags, model_id, config_version, created_at)`, khóa (run_id, fc_code, sku_code, horizon).
- `actual_daily(date, fc_code, sku_code, demand, total_open_hours, updated_at)`, khóa (date, fc_code, sku_code).
- `shadow_monitor_runs(id, run_date, period_start, period_end, current_weight, best_weight, errors_json, decision, report_path, created_at)`.

## 7. Kết quả C2–C4 (28/10/2026, đến 04:10)

**C2 – Sao lưu và thử khôi phục: ĐẠT.**
- Sao lưu trực tuyến bằng `backup_database()` của bản 1.2.14: `backups\backup-20261028-022138-pre-130-shadow.zip`, SHA `05FBCF1F…42C0`.
- Cấu hình chép vào `backups\config-*-pre-130-shadow\`: `storage.json` 8D79DBDD…, `current.txt`.
- Khôi phục bằng `app.cli restore` vào LOCALAPPDATA và DF_DATA_DIR riêng: 35 bảng trùng số dòng, 20 / 20 file model, integrity ok. `data-check` 34 OK / 3 WARN, giống hệt DB thật.

**Migration 0011 trên bản sao DB hôm nay: ĐẠT.**
- Phiên bản 10 → 11. 8 bảng mới đều rỗng; mọi bảng cũ giữ nguyên số dòng.
- `demand_daily`: 17.234 khóa, tổng lượng 43.485.936, trước và sau như nhau.
- integrity ok; `data-check` 34 OK / 3 WARN, như trước.

**Truy vấn BigQuery thật trên bản sao (chỉ đọc):**

| Truy vấn | Kết quả |
|---|---|
| Giờ mở bán 120 ngày | 5,97 triệu dòng, 1,13 GB, dữ liệu đến 25/10 → T4b chuyển sang đọc tăng dần |
| Avg lịch sử 15 ngày | 37 MB, 0 xung đột |
| `fact_avg_demand_sku` khai làm nguồn Avg hôm nay | Code **nhận** làm Avg ngày 28/10 (ingest 00:15 ngày 28/10), nhưng giá trị trùng bản ghi lịch sử ngày 27/10 ở 52.878 / 54.830 cặp (các cặp còn lại không có lịch sử) → đúng rủi ro của C1.3. T4b thêm số đo và cảnh báo; quy tắc chặn là quyết định của chủ dự án. |

**Test:**
- Toàn bộ backend sau T4: 1.019 đạt / 19 bỏ qua / 0 lỗi.
- Test mới: postprocess / sku_group / inventory_sim 63; B1 + cấu hình + migration 50; làm mới 27.

**TÁI LẬP (C4), luồng làm mới của app trên bản sao DB backtest, model V1 của lô + Avg của ngày D:**

| Ngày | Chuỗi | LightGBM so với `forecast_V1` | Dự báo cuối lệch |
|---|---|---|---|
| 15/09 | 16.872 | lệch tối đa 0,00005 | 12 chuỗi |
| 01/10 | 16.986 | lệch tối đa 0,00005 | 10 chuỗi |
| 20/10 | 17.132 | lệch tối đa 0,00005 | 19 chuỗi |

- LightGBM tái lập đúng ở mọi chuỗi; mức lệch 0,00005 chỉ là do CSV làm tròn 4 chữ số.
- 41 chuỗi lệch dự báo cuối (0,24 ‰) **đều là điểm biên 0,5**. Ví dụ LightGBM = 4/7 = 0,571428…, Avg = 2: tính đúng 0,35 × 4/7 + 0,65 × 2 = 1,5 → 2; từ CSV (0,5714) ra 1,49999 → 1.
- Nghĩa là tham chiếu dựng từ CSV 4 chữ số không đủ chính xác ở biên 0,5; luồng của app dùng giá trị đầy đủ, như file bằng chứng (LightGBM dạng 11,5333003997803).
- Theo đặc tả "Lệch: DỪNG", **ghi là điểm khác giả định; không đi tiếp tới C6**.

**Mô phỏng B8 bằng module của app** (dữ liệu backtest 01/08–22/10, đo 01/09–22/10):
- Cùng 14.021 chuỗi và nhóm của file bằng chứng, so với file:
  - hàng dư +0,02 % / +0,02 %;
  - tồn kho −0,47 % / −0,47 %;
  - mất bán +1,40 % / +1,45 % (vượt ngưỡng 0,5 %).
  - Phần lệch mất bán bằng đúng phần lệch nhu cầu đầu vào (mục 6.4).
- Nhóm tự tính theo 01/06–31/08 (có luật 14 ngày): 14.890 chuỗi.
  - Hàng dư Mới −11,8 % và tồn kho Mới −6,9 % so với file, vì tập chuỗi và nhóm khác.
  - Không có luật 14 ngày thì gần như không đổi (hàng dư Mới −11,6 %).
  - File bằng chứng xếp nhóm cả 261 chuỗi mà dữ liệu trong máy không có ngày mở bán nào ở 01/06–31/08.

**Review C3-R1 (T2 / T3a / T4): APPROVE, 0 Critical.**
- Đã xác nhận reviewer không đổi gì: `git status`, `git diff --stat` và toàn bộ diff giống trước.
- 9 điểm "nên sửa": 7 điểm giao cho T4b. Điểm 1 (chặn Avg trùng ngày trước) và điểm 6 (dung lượng `forecast_daily_log`, khoảng 125 MB/ngày) là quyết định của chủ dự án.

## 8. Kết quả sau các vòng sửa (28/10/2026, đến 05:45)

**C1.3 lúc 05:00: KHÔNG ĐẠT.**
- `fact_avg_demand_sku` vẫn là bản nạp 00:15, trùng 100 % bản ghi ngày 27/10.
- Bảng lịch sử chưa có bản ghi ngày 28/10; lần ghi gần nhất 08:10 giờ VN ngày 27/10.
- Bảng giờ mở bán làm mới 04:10, dữ liệu chỉ đến 26/10 (D-2).
- → **Dừng trước C6**, không đổi công thức. Phương án thay thế: xem báo cáo `docs/bao_cao_trien_khai_20261028.md`.

**Review và vòng sửa:**

| Vòng | Phạm vi | Kết quả |
|---|---|---|
| R1 | T2, T3a, T4 | APPROVE, 0 Critical |
| T4b | sửa 7 điểm của R1 | đọc giờ mở bán tăng dần; phân nhóm ngoài khóa ghi; hoãn phân nhóm khi giờ mở bán trễ; cắt cửa sổ theo vùng dữ liệu; cờ `CODE_UNKNOWN`; cảnh báo Avg trùng ngày trước (không chặn); job theo dõi và công tắc |
| DR1 (data-reviewer) | migration 0011 + dữ liệu | an toàn cho dữ liệu cũ |
| T4c | sửa theo DR1 | thêm cột phạm vi cho mọi bảng; mốc đọc hoàn tất; trigger chống sửa/xóa; chỉ tính lần theo dõi theo lịch; khóa chính mới; `data-check` shadow; cờ `LGB_MISSING`; ghi `actual_daily` lỗi vẫn giữ PUBLISHED |
| R2 | T4b, T5, T4c | APPROVE, 0 Critical → T5b sửa: trạng thái trễ trùng luật lịch, xuất file write-only, thẻ lịch trên giao diện, cách chọn khi bằng điểm, báo cáo lỗi sau commit |
| R3 | T5b, T7, các sửa nhỏ | 0 Critical → orchestrator sửa: không xác định được phạm vi BIGQUERY thì không lập lịch và không báo trễ (+ test); số liệu tài liệu 125 MB/lần |

**Kiểm tra lại sau các vòng sửa:**
- Migration 0011 (9 bảng, 6 trigger) trên bản sao mới của DB hôm nay: 10 → 11, integrity ok, mọi bảng cũ giữ nguyên số dòng, `demand_daily` 17.234 khóa / 43.485.936 không đổi, `data-check` 42 OK / 3 WARN (3 WARN có sẵn), 8 kiểm tra shadow đều OK, 229 s (chủ yếu là sao lưu trước migration).
- Test cuối:

| Phần | Kết quả |
|---|---|
| Backend | 1.081 đạt / 19 bỏ qua / 0 lỗi |
| Vitest | 170 / 170 |
| Typecheck | đạt |
| Build | đạt |
| Lint | chưa cấu hình |

**Checkpoint:** `checkpoints\source-1.3.0-shadow-before-commit-20261028.zip` (50 file, SHA `98A21A35…EB0A`).

**Điểm khác đặc tả:** `actual_daily` lấy từ `demand_daily` của app (D-14..D-1, ghi lại mỗi lần làm mới), không lấy từ bảng thực bán đã chốt (`actual_final_values`). Báo cáo tuần cũ có thể không tái lập chính xác nếu dữ liệu nguồn được sửa sau đó.

## 5. Rủi ro chính

- Đổi `config_fingerprint` khi thêm field (xem B1).
- Mã danh mục SKU/FC lệch khi dự báo bằng model cũ trên panel mới (B5): **dự báo sai mà không báo lỗi** nếu không ánh xạ.
- `PUT /api/settings` hoặc reset vô tình chuyển LIVE (B9).
- Thêm lịch mới không được làm thay đổi lịch D0, D-1, huấn luyện.
- `settings_history` không có cột người thao tác, nên "chủ dự án chuyển LIVE" chỉ ghi được trong ghi chú và audit.
- Các thay đổi chưa commit về liên kết từ xa (remote link, 9 mục) đang nằm trong cây làm việc. Chúng **không** thuộc đợt này và sẽ không được commit cùng.

## 9. Bổ sung kế hoạch của chủ dự án (28/10/2026, ghi lúc 09:54 giờ VN)

**Phạm vi:**
- Ghi kế hoạch, không sửa code, không đụng production.
- **C6 vẫn chưa làm** cho đến khi chủ dự án xác nhận kế hoạch, gồm 7 điểm ở mục 3 và các quyết định ở mục 9.7.
- Hiện trạng lúc ghi (chỉ đọc):
  - app 1.2.14, model đang dùng `MV-20261026-105345-C73F`;
  - DB thật ở schema 10;
  - D-1 thành công gần nhất 26/10 10:01 (dữ liệu đến 25/10);
  - D-1 theo lịch ngày 27/10 và 28/10 đều FAILED `SOURCE_INCOMPLETE`.

**Các điểm bị thay** (giữ nguyên chữ cũ để đối chiếu):

| Chỗ cũ | Thay bằng |
|---|---|
| Mục 1 dòng "1.3" và mục 1.1 ("không có Avg của ngày 28/10: DỪNG theo C1.3") | 9.2 |
| Mục 2 dòng B5 ("thử lại mỗi 10 phút đến 05:55") | 9.1 |
| Mục 3 điểm 1 và mục 4b dòng "1. Nguồn Avg hôm nay" (`avg_today_table` rỗng) | 9.1 |
| Mục 4b gạch đầu dòng 3–4 và mục 8 ("C1.3 không đạt → dừng trước C6") | 9.2 |
| Mục 7 ("Lệch: DỪNG … không đi tiếp tới C6") | 9.3 |

### 9.1 Tác vụ Làm mới dự báo (`FORECAST_REFRESH`)

**Yêu cầu:**
1. **Nút chạy tay** trên giao diện, ngoài lịch tự động.
2. **Bỏ mốc cứng 05:55.**
   - Dùng cấu hình `refresh_deadline`, mặc định **12:00**.
   - Chỉ sau mốc này mới gắn cờ `STALE_FORECAST`.
3. **Điều kiện chạy:** D-1 hôm nay thành công **và** Avg trong `fact_avg_demand_sku` có **ngày = hôm nay**.
4. **Thiếu Avg của hôm nay:**
   - Không chạy, và hiện rõ **"Chưa có Avg ngày D"** trên giao diện.
   - Chỉ khi chủ dự án **bấm xác nhận** mới được dùng Avg gần nhất. Dự báo của ngày đó gắn cờ **`AVG_STALE`**.
5. **Mỗi lần chạy ghi lại:** giờ chạy, ngày dữ liệu D-1, ngày của Avg đã dùng.

**Đối chiếu với code đã stage trên branch** (chỉ đọc, chưa sửa):

| Yêu cầu | Hiện có | Phải thêm / đổi |
|---|---|---|
| Nút chạy tay | Đã có: `POST /api/shadow/refresh/run` (`api/shadow_routes.py:229-231`); nút trên `frontend/src/pages/ShadowForecast.tsx:43` | Kiểm lại nút hiển thị đúng lý do khi không chạy được (D-1 chưa xong / thiếu Avg) |
| `refresh_deadline` | Đã là cấu hình, mặc định `"05:55"` (`settings_service.py:266-285`). Lịch và cờ trễ dùng nó (`jobs/scheduler.py:213-261`, `api/shadow_routes.py:73-98`, `jobs/runner.py:233-243`) | Đổi mặc định thành `"12:00"`. Sửa mọi chỗ có chữ `05:55` (đếm lúc ghi, 13 lần ngoài file này): `settings_service.py` (1), `CHANGELOG.md` (1), `docs/SCHEDULER.md` (2), test `backend/tests/test_v130_b1_settings.py` (1), `test_v130_refresh.py` (2), `test_v130_shadow_api.py` (3), `frontend/src/v130-shadow.test.tsx` (3) |
| Điều kiện D-1 + Avg hôm nay | `fetch_avg_today` (`bq/aux_sources.py:194-226`): Avg ngày D chỉ khi **mọi dòng** có as-of (`avg_today_asof_column` = `ingest_time`) là giờ VN của ngày D, nếu không thì `AVG_NOT_FOR_TODAY`. `avg_today_table` mặc định rỗng (`settings_service.py:599-613`) → `AVG_SOURCE_NOT_CONFIGURED` | Cấu hình `avg_today_table = lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku`. **Cần quyết định ở 9.7 (a)** về "ngày của Avg" |
| "Chưa có Avg ngày D" + xác nhận + `AVG_STALE` | Chưa có. Hiện thiếu Avg thì job chờ và thử lại tới mốc, quá mốc thì `STALE_FORECAST`. Luật `BLEND_AVG_MISSING` / cờ `AVG_MISSING` là thiếu Avg **từng chuỗi**, khác với `AVG_STALE` | Endpoint xác nhận riêng (gõ chữ xác nhận, ghi audit, chỉ cho đúng ngày D); cờ `AVG_STALE` ở lần chạy và ở `forecast_daily_log.flags`; banner và nút trên `ShadowForecast.tsx`; văn bản `i18n.tsx`, `messages.py`; test. **Cần quyết định 9.7 (b)** |
| Ghi giờ chạy / ngày D-1 / ngày Avg | `shadow_forecast_runs` có `created_at`, `data_as_of`, `avg_source`, `avg_asof` (mục 6.5) | Thêm cột ngày Avg đã dùng (`avg_date`) và cờ của lần chạy. Migration 0011 **chưa** chạy trên production, nên còn sửa được trước khi phát hành. Phải qua `data-reviewer` và chạy lại trên bản sao (số dòng / khóa trước và sau, `data-check`) |

### 9.2 C1.3 không còn chặn cài đặt

- Bản 1.3.0 chạy ở **SHADOW** và kiểm Avg của ngày D **lúc chạy** (9.1). C1.3 vì vậy chuyển thành kiểm tra lúc chạy, **không** còn là điều kiện chặn C6.
- C6–C7 vẫn chỉ làm khi chủ dự án đã xác nhận kế hoạch.

### 9.3 Tiêu chí chấp nhận TÁI LẬP (C4)

**Tiêu chí:** chấp nhận khi **mọi** chỗ lệch thỏa cả hai điều kiện:
- lệch **đúng 1 đơn vị**;
- giá trị trước làm tròn (theo app) cách mốc x,5 **dưới 0,001**.

**Đánh giá theo bằng chứng có sẵn:**
- Nguồn: kết quả C4 `scratchpad\c4\tai_lap.json` của phiên kế hoạch; tính lại bằng `ml/postprocess.round_half_away` của code đã stage, không đọc DB.
- **41 / 41 chỗ lệch nằm trong 0,001 quanh x,5**: 15/09: 12/12; 01/10: 10/10; 20/10: 19/19. Phép kiểm "gần x,5" dùng LightGBM đầy đủ của app (`tai_lap.py:62`).
- **Mỗi chỗ lệch nhiều nhất 1 đơn vị, theo suy luận** (không đo trực tiếp):
  - LightGBM của app lệch CSV 4 số lẻ tối đa 5,0·10⁻⁵;
  - nên giá trị trước làm tròn lệch tối đa 0,35 × 5·10⁻⁵ = 1,75·10⁻⁵;
  - hai số lệch nhau dưới 1 thì sau làm tròn chỉ khác nhau tối đa 1.
- **Danh sách đầy đủ 41 chuỗi: CHƯA lập.** `tai_lap.json` chỉ lưu 5 ví dụ mỗi ngày.
  - Phải chạy lại `c4\tai_lap.py` trên bản sao DB backtest, sửa để xuất mọi chỗ lệch kèm giá trị trước làm tròn.
  - Lúc ghi, RAM trống chỉ 0,63 GB trong khi app production đang chạy, nên chưa chạy.
  - Việc này **bắt buộc** trước khi ký C4.
- **15 ví dụ đã có** (đều lệch đúng 1, giá trị trước làm tròn trúng x,5):

| Ngày | FC | SKU | LightGBM (đầy đủ) | Avg | R(Avg) | Trước làm tròn | Cuối (app) | Tham chiếu CSV | Lệch | Cách x,5 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15/09 | BD | MEDX.DMTS-QDM-BIO-001 | 0,571428571… (4/7) | 2,00 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 15/09 | BD | MEDX.JGBQ1PGE | 0,571428571… | 2,33 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 15/09 | BD | MEDX.THJPGEQ1 | 0,571428571… | 2,00 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 15/09 | BD | MEDX.V98HR2AX | 0,857142857… (6/7) | 7,67 | 8 | 5,5 | 6 | 5 | 1 | 0 |
| 15/09 | HN | MEDX.1RDT84FW | 0,571428571… | 2,00 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 01/10 | BD | MEDX.9LCW961P | 0,571428571… | 2,00 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 01/10 | BD | MEDX.BAY-AVE-002 | 0,571428571… | 2,29 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 01/10 | BD | MEDX.DMC-DPA-001 | 0,571428571… | 1,50 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 01/10 | BD | MEDX.JHT74FW9 | 0,571428571… | 1,75 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 01/10 | BD | MEDX.OPV-LOD-002 | 0,571428571… | 2,00 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 20/10 | BD | MEDX.ATT972AX | 0,571428571… | 1,98 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 20/10 | BD | MEDX.CPKHR2AX | 0,571428571… | 1,82 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 20/10 | BD | MEDX.DMC-HAT-001 | 0,571428571… | 2,29 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 20/10 | BD | MEDX.MKP-PAR-001 | 0,571428571… | 2,00 | 2 | 1,5 | 2 | 1 | 1 | 0 |
| 20/10 | BD | MEDX.NAM-DAI-003 | 0,571428571… | 2,29 | 2 | 1,5 | 2 | 1 | 1 | 0 |

Công thức: trước làm tròn = 0,35 × LightGBM + 0,65 × R(Avg), R = làm tròn nửa ra xa 0 (mục 6.1). Script tính lại: `scratchpad\s16\pre_round_examples.py` của phiên ghi bổ sung.

**Kết luận tạm:** theo bằng chứng có sẵn, tiêu chí **đạt**. Chính thức chỉ sau khi có danh sách 41 dòng.

### 9.4 Tách file truy cập từ xa khi commit

Các file sau **không** đưa vào 1.3.0:
- `REMOTE_ACCESS_GUIDE.md`;
- `Start-DemandForecast-Remote.bat`, `Stop-DemandForecast-Remote.bat`, `Setup-DemandForecast-Link.bat`;
- `scripts/remote/*` (`readonly_proxy.py`, `remote-access.ps1`, `link_supervisor.py`);
- `backend/tests/test_remote_link.py`;
- `docs/CHECKPOINT.md`.

Hiện trạng lúc ghi:
- Không file nào trong số trên đã được stage: chúng ở trạng thái sửa chưa stage hoặc chưa theo dõi.
- `CHANGELOG.md` vừa có phần đã stage vừa có phần sửa chưa stage. Khi commit **chỉ** dùng phần đã stage, và kiểm phần đó không chứa ghi chú truy cập từ xa.
- `docs/project_map.md` (khảo sát, chưa theo dõi) không có trong danh sách; chủ dự án quyết định có commit hay không.

### 9.5 C5: huấn luyện ứng viên V1

- Chỉ làm khi có dữ liệu D-1 mới (sau 25/10), trên **bản sao**.
- **KHÔNG promote.**
- Script đã có (`scratchpad\c5\train_candidate.py` của phiên kế hoạch, 05:07), chưa chạy, chưa có kết quả.

### 9.6 Lưu ý vận hành

- `demand_daily` chỉ có đến **25/10**.
- Ngưỡng trễ `max_data_lag_days` = 2. Nếu không có D-1 mới, huấn luyện trên production sẽ bị chặn `STALE_DATA_BLOCKED` (`data/quality.py:108-121`; `ml/pipeline.py:444-446`).
- **KHÔNG tự chạy D-1.** Chờ chủ dự án chạy tay.

### 9.7 Quyết định cần chủ dự án trước khi code 9.1

**(a) "Avg có ngày = hôm nay" tính theo đâu?**
- Hôm nay `fact_avg_demand_sku` có `ingest_time` = `00:15:02 28/10/2026`. Theo luật as-of hiện có (9.1), Avg được **nhận** là Avg ngày 28/10.
- Nhưng giá trị trùng 22.822 / 22.822 cặp với bản ghi lịch sử ngày 27/10 (C1.3 lúc 05:00).
- Vậy theo ngày nạp thì lần chạy sẽ diễn ra, dù Avg có thể là của hôm trước. Phải chọn một trong hai:
  - ngày theo `ingest_time`;
  - thêm điều kiện "khác bản ghi lịch sử gần nhất". Hiện code T4b chỉ **cảnh báo**, không chặn.

**(b) "Avg gần nhất" khi xác nhận `AVG_STALE` lấy từ đâu?**
- Bộ TODAY gần nhất đã lưu, hay bản ghi lịch sử (`fact_avg_demand_sku_historical`) gần nhất?
- Xác nhận có hiệu lực cho đúng một ngày D hay đến khi có Avg mới?

**(c) Sau 12:00 vẫn chưa chạy được:** giữ hành vi hiện có, tức gắn `STALE_FORECAST` một lần trong ngày và báo lỗi. Có cần thêm gì không?
