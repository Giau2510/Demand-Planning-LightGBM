# Deal biết trước + mức giảm giá: ứng viên V37_deal (31/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\cai-tien-deal-20261031\README.md` (MAIN) | 31/10/2026 | 7428 | `5BB07FA699826AD0F7E80240DECA4736AC2B5B9BE84DA6F145CBCEE09B999C81` |
| 2 | `reports\cai-tien-deal-20261031\data_checks.md` (MAIN) | 31/10/2026 | 3302 | `CDC143C1944C420FBC2814F18CBAAAC05BB74DF027015F54D581DAE4BB95CDE8` |
| 3 | `reports\cai-tien-deal-20261031\leakage_summary.md` (MAIN) | 31/10/2026 | 807 | `4FA3DF4C23DFC4602629E511A19EFE538C5FDB2504FD776672DBECA20C7BF4D7` |

## 1. Deal biết trước + mức giảm giá: ứng viên V37_deal (31/10/2026)

Nguồn: `reports\cai-tien-deal-20261031\README.md` (worktree MAIN).

Thư mục ngoài Git. Production 1.3.1 không bị đụng tới. Không commit, không push. BigQuery chỉ đọc, chạy dry-run trước,
trần 5 GB mỗi truy vấn.

### Cách làm

- Code mới chỉ có `code\deal_planned.py`. Toàn bộ phần còn lại dùng nguyên vẹn code của `reports\cai-tien-20261031\code`:
  - `ct_run.py`, `ct_feat.py` (đối tượng `Features`);
  - `scoring.py`, `keep_rule.py`, `ct_select.py`, `ct_package.py`.
- Các file cũ không bị sửa. Biến `plan_*` được gắn thêm trong bộ nhớ, bằng cách bọc hàm `ct_feat.target_names` và
  `Features.target`.
- `prep\` và `runs\{MOC, V33_L112, V36_two_stage, TSB, DOW4, AVG7, FINAL2}` là liên kết junction, chỉ đọc, trỏ sang thư mục
  cũ. `data\keys.parquet` và `pham_vi.parquet` được chép sang (SHA giữ nguyên).
- Dữ liệu deal: `demand_planing_deal`, đọc lúc 14:04 ngày 31/10. Bảng sửa lần cuối lúc 16:38:53 UTC ngày 30/10, tức 23:38
  giờ VN.
- `created_time`, `ready_time` và `end_time` đều được hiểu là giờ VN. Lý do (kiểm tra A, `checkA.json`): trong 93.146 deal
  có đơn, không deal nào có đơn trước ngày tạo, còn nếu hiểu là UTC thì có 4.871 deal như vậy.

### Biến plan_* (mốc dự báo = 00:00 giờ VN ngày D; ngày đích T = D + h − 1)

**Deal "đã biết" tại D:**
- created_time trước D 00:00;
- nếu created_time trống: ready_time từ D 00:00 trở về trước.

**Cách dùng end_time:**
- Deal đã kết thúc trước D 00:00 thì dùng end_time của nó, nên deal đó không còn hoạt động ở bất kỳ T nào từ D trở đi.
- Deal chưa kết thúc tại D 00:00 thì không đọc end_time: coi như đang chạy với mọi T từ ngày bắt đầu trở đi.

| Biến | Ý nghĩa |
|---|---|
| plan_active | 1 nếu có deal đã biết, chưa kết thúc, đã bắt đầu trước hoặc đúng ngày T |
| plan_days_from_start | T − ngày bắt đầu của deal đang chạy bắt đầu gần nhất |
| plan_days_to_start | ngày bắt đầu gần nhất sau T của deal đã biết − T |
| plan_first3 | T nằm trong 3 ngày đầu của một deal đang chạy |
| plan_discount | discount_percent lớn nhất của các deal đang chạy |
| plan_n_deals | số deal đang chạy |
| plan_qty_ratio | max_quantity lớn nhất ÷ max(roll_mean_28 tại D, 0,1) |
| plan_lead_days | ngày bắt đầu − lúc tạo (tính bằng ngày) của deal đang chạy bắt đầu gần nhất |

Ứng viên **V37_deal** = V33_L112 (hồ sơ ngày, biến chịu đột biến, học 112 ngày) cộng các biến plan_*.

### Tiến trình và giới hạn (hạn chót cứng 15:45)

- 14:04–14:06: bước A, đọc bảng deal và các kiểm tra (`checkA.json`).
- 14:10: bước B. Kiểm tra rò rỉ (a)–(d) tại 20/07, 15/09 và 12/10: đạt 12/12 (`leak_plan.json`).
- 14:10: bắt đầu chạy V37_deal cho lô 14–21. Mỗi lô mất khoảng 12,8 phút, so với 3,8 phút của V33_L112 lúc 09:11. Nguyên nhân:
  - máy chạy bằng pin (BatteryStatus = 1, còn 67 %);
  - CPU i5-1335U có 2 nhân hiệu năng cao và 8 nhân tiết kiệm. Theo py-spy, phần lớn thời gian nằm ở `nanpercentile`
    (biến chịu đột biến của code cũ, chạy một luồng), không nằm ở biến plan_*.
  - Không thay đổi cài đặt nguồn của máy.
- Để kịp 15:45:
  - chỉ chạy lô 14, 15 và 18–21; bỏ lô 16–17 (ngày dự báo 14/09–27/09);
  - lịch sử để chọn của V37_deal trong tháng 10 vì thế thiếu khoảng ngày đích 20/09–27/09, nhưng mọi ngày tháng 10 vẫn có
    ít nhất 14 ngày lịch sử, nên không ngày nào bị chuyển sang V33_L112 vì thiếu lịch sử;
  - **phần D (toàn kỳ) không chạy**.
- Chấm điểm và chọn theo SKU là việc nhẹ, chạy sau khi phần học xong.

### Kết quả cổng 1 (ngày dự báo 01/10–22/10, chấm bằng scoring.py, quy tắc giữ không nới)

| Phương án | Đúng N1 | Thiếu N1 | Lệch N1 | Đúng 7N | Thiếu 7N | Lệch 7N |
|---|---:|---:|---:|---:|---:|---:|
| MOC | 69,29 | 31,67 | 66,45 | 69,39 | 33,59 | 69,05 |
| V33_L112 | 70,07 | 31,74 | 65,69 | 69,95 | 33,60 | 68,02 |
| **V37_deal** | 68,70 | 31,24 | 67,35 | 68,38 | 32,93 | 69,58 |
| SEL2 6 ứng viên (S62 = CUOI) | 73,83 | 31,98 | 66,52 | 73,97 | 33,80 | 69,13 |
| **SEL2 7 ứng viên (S72)** | 73,64 | 32,02 | 65,92 | 73,67 | 33,79 | 68,63 |
| S72 hiệu chỉnh (xem dưới) | 73,82 | 31,90 | 66,44 | 73,87 | 33,73 | 69,11 |

(N1 = ngày thứ 1, 7N = 7 ngày; đơn vị %)

**Bảng (1): V37_deal so với V33_L112.** Đúng N1 −1,37 điểm, Đúng 7N −1,57 điểm. KHÔNG GIỮ.

**Bảng (2): S72 so với S62.** Đúng N1 −0,20 điểm, Đúng 7N −0,30 điểm. KHÔNG GIỮ, nên DỪNG và không chạy phần D.

**Hiệu chỉnh** (`gate1_fix.json`, `env\gate1_fix.py`):
- Vì thiếu lô 16–17, S72 rơi về V33_L112 nhiều hơn S6 (164.745 so với 143.245 lượt SKU×kho×ngày).
- Ở 150.500 dòng mà S72 rơi về V33_L112 còn S62 thì không, ta dùng lại giá trị của S62.
- Kết quả vẫn **KHÔNG GIỮ**: Đúng N1 −0,02 điểm, 7N −0,09 điểm. Kết luận không đổi.

**Riêng các ô có plan_active = 1** (`gate1_subset.json`; 180.142 trên 202.623 ô N1, tức 89 %):
- V37_deal so với V33_L112: Đúng N1 −1,55 điểm, 7N −1,79 điểm.
- S72 so với S62: N1 −0,21 điểm, 7N −0,33 điểm.

Tức là ngay trên đúng nhóm ô có deal, biến deal cũng không giúp ích.

**Vì sao không giúp:**
1. Chỉ 0,24 % deal của giai đoạn 06–10 được tạo trước ngày bắt đầu từ 1 ngày trở lên, nên biến chỉ có thông tin cho ngày
   thứ 1.
2. Theo quy tắc không dùng end_time của deal chưa kết thúc, deal đang chạy được coi là kéo dài mãi. Cộng với việc gần như SKU
   nào cũng có deal, plan_active = 1 ở khoảng 89 % số ô, nên gần như không phân biệt được ô nào.
3. discount_percent chỉ có ở 1,5 % số deal biết trước.

Tổng độ lợi của 8 biến plan_* trong mô hình chỉ khoảng 0,4 % (`feature_gain.csv`).

**Rò rỉ:**
- Biến plan đạt (a)–(d) 12/12.
- Kiểm tra theo lô và theo ngày của bộ chạy: 6 lô (14, 15, 18–21), tất cả đạt.
- Bộ chạy tự kiểm tra ở mỗi lần gọi (`Plan.cols`): chỉ dùng deal tạo trước D 00:00 và không dùng deal đã kết thúc trước D.

### Ghi chú

- Các script phụ trợ phân tích nằm trong `env\` (`knownA.py`, `preview.py`, `gate1_fix.py`, `perf*.py`, `dbg.py`). Chúng chỉ
  đọc kết quả và không chứa code mô hình. Code mô hình mới chỉ nằm trong `code\deal_planned.py`.
- Hai việc chạy chồng lên giai đoạn học (để kịp hạn chót): SEL2 6 ứng viên (`pre6`) và phần chấm riêng các ô có plan_active
  cho 3 phương án cũ. Cả hai đều nhẹ, không học mô hình.
- Không gửi lại actuals, open_hours và pham_vi: SHA của chúng trùng với gói `reports\cai-tien-20261031\package` (xem
  MANIFEST.csv).
- Không có goi2_CUOI2 vì phần D không chạy (cổng 1 không đạt).

## 2. data_checks (A)

Nguồn: `reports\cai-tien-deal-20261031\data_checks.md` (worktree MAIN).

```json
{
 "rows": 355578,
 "deal_codes": 233578,
 "ready_min": "2025-01-01 00:00:00",
 "ready_max": "2026-10-31 00:00:00",
 "pct_created": 100.0,
 "pct_discount": 22.89,
 "pct_end": 100.0,
 "lead_all": {
  "n": 355578,
  "median_days": 0.208,
  "p10": -1.408,
  "p90": 0.312,
  "pct_ge_1d": 1.86,
  "pct_ge_3d": 0.71,
  "pct_negative": 43.82,
  "pct_lt_1h": 3.95
 },
 "discount_all": {
  "n": 81378,
  "q0": 0.0,
  "q10": 0.0,
  "q25": 0.0,
  "q50": 4.49,
  "q75": 11.11,
  "q90": 20.0,
  "q100": 75.0,
  "bins": {
   "(-1000000000.0, 0.0]": 23936,
   "(0.0, 5.0]": 20530,
   "(5.0, 10.0]": 15470,
   "(10.0, 15.0]": 6497,
   "(15.0, 20.0]": 8769,
   "(20.0, 30.0]": 4451,
   "(30.0, 50.0]": 1708,
   "(50.0, 1000000000.0]": 17
  }
 },
 "lead_start_2026_06_10": {
  "n": 251752,
  "median_days": 0.269,
  "p10": -0.756,
  "p90": 0.311,
  "pct_ge_1d": 0.24,
  "pct_ge_3d": 0.17,
  "pct_negative": 28.22,
  "pct_lt_1h": 4.41
 },
 "discount_start_2026_06_10": {
  "n": 19445,
  "q0": 0.01,
  "q10": 2.32,
  "q25": 3.31,
  "q50": 5.6,
  "q75": 12.0,
  "q90": 20.0,
  "q100": 75.0,
  "bins": {
   "(-1000000000.0, 0.0]": 0,
   "(0.0, 5.0]": 9158,
   "(5.0, 10.0]": 4450,
   "(10.0, 15.0]": 2078,
   "(15.0, 20.0]": 2346,
   "(20.0, 30.0]": 1094,
   "(30.0, 50.0]": 312,
   "(50.0, 1000000000.0]": 7
  }
 },
 "hour_created": {
  "0": 2.6,
  "1": 1.1,
  "2": 0.0,
  "3": 0.0,
  "5": 0.1,
  "6": 0.2,
  "7": 3.3,
  "8": 0.3,
  "9": 1.5,
  "10": 2.2,
  "11": 3.2,
  "12": 7.7,
  "13": 2.7,
  "14": 5.5,
  "15": 4.1,
  "16": 24.0,
  "17": 19.5,
  "18": 8.7,
  "19": 3.2,
  "20": 0.7,
  "21": 1.6,
  "22": 2.8,
  "23": 5.0
 },
 "hour_ready": {
  "0": 86.8,
  "1": 0.4,
  "3": 0.0,
  "4": 0.1,
  "5": 0.0,
  "6": 0.2,
  "7": 0.4,
  "8": 8.2,
  "9": 0.2,
  "10": 0.4,
  "11": 0.2,
  "12": 0.3,
  "13": 0.9,
  "14": 0.0,
  "15": 0.7,
  "16": 0.2,
  "17": 0.0,
  "18": 0.0,
  "19": 0.0,
  "20": 0.1,
  "21": 0.0,
  "22": 0.6,
  "23": 0.1
 },
 "hour_end": {
  "0": 4.1,
  "1": 0.2,
  "2": 0.0,
  "4": 0.0,
  "5": 0.1,
  "7": 0.0,
  "9": 0.0,
  "10": 0.5,
  "11": 0.5,
  "12": 0.0,
  "13": 0.7,
  "14": 0.1,
  "15": 0.4,
  "16": 0.4,
  "17": 0.1,
  "18": 0.1,
  "19": 0.1,
  "20": 0.2,
  "21": 0.0,
  "22": 0.6,
  "23": 92.0
 },
 "pct_ready_equals_created_minute": 0.03,
 "tz_check": {
  "VN": {
   "deals_with_orders": 93146,
   "orders_before_creation_day": 0,
   "first_order_same_day": 23605
  },
  "UTC": {
   "deals_with_orders": 93146,
   "orders_before_creation_day": 4871,
   "first_order_same_day": 31959
  },
  "ready_VN": {
   "orders_before_start_day": 131
  },
  "ready_UTC": {
   "orders_before_start_day": 234
  }
 },
 "known": {
  "deals_06_10": 251752,
  "known_at_D_minus_0": 70.97,
  "known_at_D_minus_1": 0.24,
  "known_at_D_minus_2": 0.21,
  "known_at_D_minus_3": 0.17,
  "known_at_D_minus_4": 0.14,
  "known_at_D_minus_5": 0.13,
  "known_at_D_minus_6": 0.12,
  "known_at_D_minus_7": 0.1,
  "known_by_start_only": 29.03,
  "disc_present_06_10": 7.72,
  "disc_present_known_D0": 1.5,
  "status": {
   "INACTIVE": 232912,
   "ACTIVE": 18840
  },
  "dur_days_median": 2.9993055555555554
 }
}
```

## 3. leakage_summary

Nguồn: `reports\cai-tien-deal-20261031\leakage_summary.md` (worktree MAIN).

Plan-feature tests (a)-(d), leak_plan.json: passed = True

- 2026-07-20 (a): passed=True
- 2026-07-20 (b): passed=True
- 2026-07-20 (c): passed=True
- 2026-07-20 (d): passed=True
- 2026-09-15 (a): passed=True
- 2026-09-15 (b): passed=True
- 2026-09-15 (c): passed=True
- 2026-09-15 (d): passed=True
- 2026-10-12 (a): passed=True
- 2026-10-12 (b): passed=True
- 2026-10-12 (c): passed=True
- 2026-10-12 (d): passed=True

Runner per-batch / per-day checks of V37_deal (data < D, targets D..D+6, scope): 45 checks, 45 passed, batches [14, 15, 18, 19, 20, 21]
Runtime guard in Plan.cols (every call): only deals with created_time < D 00:00 (or ready_time <= D 00:00 when created_time is empty) and not ended before D 00:00; end_time of a deal not ended at D is never read.
