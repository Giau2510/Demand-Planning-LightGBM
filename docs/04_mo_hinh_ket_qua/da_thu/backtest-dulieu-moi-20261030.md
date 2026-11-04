# Backtest phương án chốt trên dữ liệu nguồn mới (30/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\backtest-dulieu-moi-20261030\README.md` (MAIN) | 30/10/2026 | 6793 | `C173389CB151D2F117DCD027EE560401C3ED2DFE15CD2332B8920472942B3305` |
| 2 | `reports\backtest-dulieu-moi-20261030\PREREGISTRATION.md` (MAIN) | 30/10/2026 | 987 | `AB4356CF5217F012A8B87872B18E46C9A0A4F7D9DC8AC6A2CB6E8535EB03D894` |
| 3 | `reports\backtest-dulieu-moi-20261030\leakage_summary.md` (MAIN) | 30/10/2026 | 1174 | `1E63B0B93B69420F11C5D791EA4E4F7952E07E8E79EAACBBE1FEB0715243103D` |

## 1. Backtest phương án chốt trên dữ liệu nguồn mới (30/10/2026)

Nguồn: `reports\backtest-dulieu-moi-20261030\README.md` (worktree MAIN).

**Đăng ký trước:** `PREREGISTRATION.md`, chỉ đọc, SHA-256
`AB4356CF5217F012A8B87872B18E46C9A0A4F7D9DC8AC6A2CB6E8535EB03D894` (cũng ghi trong `PREREGISTRATION.sha256`). File được
ghi lúc 01:53 ngày 30/10, trước khi có dữ liệu và trước mọi lần chạy.

**Mục đích:** đo lại phương án chốt (= G2_lgbm của `reports\backtest-lgbm7-20261029`) khi bảng nguồn
`demand_planing_lightgbm` đã được BI dựng lại: hết dòng trùng, đã loại đơn hủy. Bảng sửa lần cuối lúc 01:16:41 ngày 30/10.
**Chưa chấm điểm**, theo yêu cầu bước 2.3.

### 1. Quyết định của chủ dự án (30/10/2026)

> Đơn bị BI loại khỏi bảng nguồn là đơn khách hủy (không còn nhu cầu / đặt nhầm) → KHÔNG phải demand. Dữ liệu app
> phải ĐỒNG BỘ THEO BẢNG NGUỒN, cả lịch sử lẫn các lần D-1 sau này.

Quyết định này thay quy tắc KEEP_OBSERVED_LINES ngày 22/10/2026. Thiết lập của app là
`data_policy.history_change_policy = FOLLOW_SOURCE`:
- trên bản sao của bước 1: lúc 02:03;
- trên production: lúc 02:21:33 giờ VN, `settings_history` 55 → 56, có ghi chú quyết định.

### 2. Dữ liệu (bước 1)

**Bản sao DB production** tạo 01:54 bằng backup API, nguồn mở `mode=ro`.
- SHA trước khi nạp: `F1D50EFCFFA5C15908A5A5DA2791257F6EE9582808AD08D4C0E54C81037445ED`.
- Nạp lại lịch sử 01/01–28/10 bằng đúng chức năng backfill có sẵn của app, với `FOLLOW_SOURCE`:
  - xem trước `BFP-20261029190327-E1B922`;
  - nạp `D1L-20261029191256-823B4E`.
- SHA sau khi nạp (dữ liệu của backtest): `874792C1907D96A5AF23439686B6B02C5B4C42C97B27253CCF36334DF6EEA434`.

**Đối soát** (`bang_doi_soat_backfill.xlsx`): 602/602 ô ngày×kho khớp nguồn: 1.377.958 cặp SKU×FC×ngày, 42.534.115 đơn
vị. So với dữ liệu cũ: −4.423 cặp, −131.762 đơn vị. Con số này đã gồm phần thêm của ngày 28/10, ngày mà dữ liệu cũ chưa có.

**Phần lớn chênh lệch là 196 chuỗi SKU×FC bị loại hẳn khỏi bảng mới** (239.855 đơn vị, 01/01–27/10), không phải đơn hủy lẻ.
Danh sách ở `evidence\b3\chuoi_bi_bo_hoac_giam.xlsx`.

### 3. Cách chạy (bước 2.1)

**Runner** `code\chot_runner.py`:
- Mỗi lô là chính hàm `lgbm7_runner.run_batch(data, "G2", …)` của `reports\backtest-lgbm7-20261029\code`, không chép, không
  sửa.
- App được import từ bản trích cố định `af835b8` của thư mục đó. Runner tự kiểm tra; không import gì từ thư mục làm việc.

**Công thức:**
- 35 biến (bỏ `sku_code`), mã cấu hình `8468ebe66d1706f7`.
- Trọng số mẫu 3,0 cho horizon ≤ 7.
- Tweedie 1,2, 300 vòng, lr 0,05, 31 lá, seed 7.
- Cửa sổ nhãn như production.
- 21 lô 7 ngày từ 01/06; mỗi ngày D dự báo D..D+6 từ dữ liệu < D; ngày dự báo cuối 22/10.

**`CHOT_lgbm`:** giá trị LightGBM của MỌI chuỗi, cắt ở 0, không làm tròn (= `value_lgbm`, như G2_lgbm), không áp luật dự phòng.
Cột `method` là phân loại của app, chỉ để tham khảo.

**Chạy thử** 01/06–03/06 (`smoke\smoke_report.json`):
- Kiểm tra theo lô và theo ngày: đạt.
- T1–T3 của vòng 1 (model app): đạt.
- T6–T8 của phương án chốt ở cả 7 horizon: đạt 3/3.
  - T6: dữ liệu từ D được đổi và thêm chuỗi giả, nhưng model và dự báo giống hệt.
  - T7: đổi ngày D-1 thì 5.070 chuỗi đổi ở mỗi horizon.
  - T8: dựng lại panel cho kết quả giống hệt.

**Chạy đủ** (02:36–03:09, **33,1 phút**):
- 21/21 lô DONE, mỗi lô 84–115 giây; không lần tạm dừng nào vì RAM.
- Checkpoint sau mỗi lô.
- 16.495.192 dòng (144 ngày dự báo × 7 horizon), không NaN, không âm.
- MANIFEST 5 tháng khớp.
- SHA bản sao trước và sau khi chạy không đổi.

**Rò rỉ: 171/171 đạt** (`leakage_summary.md`):
- theo lô 21/21;
- theo ngày 144/144, đủ 7 horizon;
- T1–T3: 3/3;
- T6–T8: 3/3.

### 4. Gói (bước 2.2)

Gói do `code\package_chot.py` tạo, sau bước tổng hợp `chot_runner.py --mode assemble`. Hàm `package` cũ của runner không dùng,
để SHA của runner giữ đúng như lúc chạy.

**`package\goi1_hoso.zip`:**
- `README.md`, `PREREGISTRATION.md`
- `bang_doi_soat_backfill.xlsx`
- `feature_gain.csv`, `train_log.csv`
- `leakage_summary.md`

**`package\goi2_dulieu_2026-MM.zip`** (theo tháng của `target_date`):
- `eval_lgbm_2026-MM.parquet`: `sku_code`, `fc_code`, `forecast_date`, `horizon`, `target_date`, `CHOT_lgbm` (float64, không làm
  tròn), `method`;
- `MANIFEST.csv` của tháng: số dòng và tổng chính xác so với file kết quả từng lô.

**Kèm theo:**
- `actuals_2026-06_10.parquet`: `sku_code`, `fc_code`, `date`, `qty`. Lấy từ bản sao sau khi nạp lại (dữ liệu mới), 01/06–28/10,
  ngày có dòng.
- `actuals_cu_2026-06_10.parquet`: cùng cột, lấy từ bản sao TRƯỚC khi nạp lại (= production lúc 01:54), 01/06–27/10.
- `open_hours_2026-06_10.parquet`: `sku_code`, `fc_code`, `date`, `total_open_hours`. Lấy từ `openhours_by_sku`, người bán MEDX,
  MAX theo SKU×FC×ngày như app đọc, 01/06–28/10, giữ cả 0.
- `MANIFEST.csv` tổng: mọi file, SHA, số dòng, tổng.

### 5. Điểm khác giả định

- **Đ1. Thứ tự làm.** Nhiệm vụ ghi thứ tự 1 → 2 → 3; tôi làm 1 → 3 → 2. Lý do: bước 3 (production) phải xong trước cửa sổ lịch
  04:50–06:40, còn backtest chỉ chạy trên bản sao.
- **Đ2. Chính sách lịch sử trên bản sao.** Bản xem trước với chính sách cũ `KEEP_OBSERVED_LINES` không khớp nguồn: app sẽ giữ
  259.196 đơn vị. Bản sao dùng `FOLLOW_SOURCE` theo quyết định của chủ dự án.
- **Đ3. actuals mới và actuals cũ khác khoảng ngày.** `actuals` có đến 28/10 (ngày nguồn mới nhất); `actuals_cu` có đến 27/10
  (ngày cũ mới nhất).
- **Đ4. Giờ mở bán.** Lấy từ `openhours_by_sku` (đọc lại, chỉ đọc, dry-run, 0,79 GB), vì bản sao chỉ có giờ mở bán của ngày có
  đơn.
  - 7.547.595 dòng, trong đó 2.004.545 dòng có giờ > 0.
  - Bảng giờ mở bán **chỉ có đến 27/10** (sửa lần cuối 29/10 04:10 giờ VN), nên ngày đích 28/10 không có giờ mở bán.
- **Đ5. Chuỗi bị loại khỏi bảng mới.** 196 chuỗi SKU×FC không còn trong dữ liệu mới, nên không có trong backtest. Dữ liệu cũ của
  các chuỗi này vẫn có trong `actuals_cu`.

## 2. PREREGISTRATION.md

Nguồn: `reports\backtest-dulieu-moi-20261030\PREREGISTRATION.md` (worktree MAIN). Bản đăng ký trước giữ nguyên từng byte: [PREREGISTRATION.md](../../_luu_tru/dang_ky_truoc/backtest-dulieu-moi-20261030/PREREGISTRATION.md), SHA-256 `AB4356CF5217F012A8B87872B18E46C9A0A4F7D9DC8AC6A2CB6E8535EB03D894` (987 byte, của bản gốc).

MỤC ĐÍCH: đo lại độ chính xác của phương án chốt khi dữ liệu nguồn đã loại đơn hủy và bỏ dòng trùng.
CẤU HÌNH (= G2_lgbm của reports\backtest-lgbm7-20261029): 35 biến (bỏ sku_code), trọng số mẫu 3.0 cho horizon <= 7, Tweedie 1.2, 300 vòng, lr 0.05, 31 lá, seed 7, cửa sổ nhãn như production, KHÔNG luật dự phòng; lô 7 ngày từ 01/06/2026; mỗi ngày D dự báo D..D+6 bằng dữ liệu đến D-1; ngày dự báo cuối 22/10/2026.
DỮ LIỆU: bản sao DB ở bước 1 (đã nạp lại lịch sử từ bảng mới).
CHẤM ĐIỂM (Claude chấm): như phương án chốt (dưới 0,2 coi là 0, từ 0,2 làm tròn lên; ngày mở bán; so với demand thực từng ngày; Đúng/Dư ít/Dư nhiều/Thiếu ít/Thiếu nhiều; theo tháng × nhóm × kho; Qty và %; thiếu/dư so với thực tế; so với Avg Demand trên cùng dòng). So sánh với kết quả trên dữ liệu cũ (G2_lgbm).

## 3. Rò rỉ – phương án chốt trên dữ liệu mới

Nguồn: `reports\backtest-dulieu-moi-20261030\leakage_summary.md` (worktree MAIN).

**Tổng: 171 / 171 kiểm tra đạt.**

| Nhóm kiểm tra | Đạt / tổng | Nội dung |
|---|---|---|
| Theo lô | 21 / 21 | dữ liệu, panel và nhãn của mỗi lô kết thúc trước ngày mốc |
| Theo ngày | 144 / 144 | mỗi ngày D: dữ liệu < D, panel kết thúc D-1, ngày đích đúng D .. D+6 (7 horizon: True) |
| Vòng 1 T1-T3 (chạy thử, mốc 2026-06-01, ngày 2026-06-03) | 3 / 3 | model của app: đổi dữ liệu từ D -> giống hệt; đổi D-1 -> đổi; dựng lại panel -> giống hệt |
| Phương án chốt T6-T8 (chạy thử, ngày 2026-06-03) | 3 / 3 | T6 đổi mọi dữ liệu từ D + chuỗi giả -> model và dự báo giống hệt ở cả 7 horizon; T7 đổi D-1 -> dự báo đổi ở cả 7 horizon; T8 dựng lại panel -> giống hệt |

Chi tiết:

- T6: model giống hệt True, dự báo theo horizon [True, True, True, True, True, True, True], dòng đổi 581,114, chuỗi giả 500
- T7: số chuỗi đổi theo horizon [5070, 5070, 5070, 5070, 5070, 5070, 5070]
- T8: [True, True, True, True, True, True, True]
