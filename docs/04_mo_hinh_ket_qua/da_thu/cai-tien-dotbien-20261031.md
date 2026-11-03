# Đánh dấu đơn đột biến theo khách: V38a / V38b (31/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\cai-tien-dotbien-20261031\README.md` (MAIN) | 31/10/2026 | 8185 | `A67F76EA52D10DC8D484A71B504DD7C656ADC61583B881EDE1BF7732524FB7E8` |
| 2 | `reports\cai-tien-dotbien-20261031\data_checks.md` (MAIN) | 31/10/2026 | 948 | `1973456D81E3641C3DEBD9580CABA62619A7E7DF10D75E2C5DD699EB85A862EC` |
| 3 | `reports\cai-tien-dotbien-20261031\leakage_summary.md` (MAIN) | 31/10/2026 | 750 | `9D40F368F2B54531029CA30B3AB2E50B73C1DB8DEA384E3A0AAFA6155480BE48` |

## 1. Đánh dấu đơn đột biến theo khách: V38a / V38b (31/10/2026)

Nguồn: `reports\cai-tien-dotbien-20261031\README.md` (worktree MAIN).

Thư mục ngoài Git. Production 1.3.1 không bị đụng tới. Không commit, không push.

### Cách làm

- Code mới chỉ có `code\spike_orders.py`. Toàn bộ phần còn lại dùng nguyên vẹn code của `reports\cai-tien-20261031\code`:
  - bộ chạy `ct_run.py`, biến `ct_feat.py`;
  - `scoring.py` (làm tròn: dưới 0,2 thành 0, còn lại làm tròn lên), `ct_select.py` (SEL2), `ct_package.py`.
- Cách gắn code mới: bọc trong bộ nhớ các hàm `ct_run.origin_block` và `ct_feat.Features.origin / target / origin_names /
  target_names`. Không file cũ nào bị sửa.
- Liên kết junction, chỉ đọc:
  - `prep\` và `runs\{MOC, V33_L112, V36_two_stage, TSB, DOW4, AVG7, FINAL2}` trỏ sang thư mục cũ;
  - `runs\S62` (SEL2 6 ứng viên = CUOI trên tháng 10, đã kiểm tra trùng khớp với SEL2 cũ) trỏ sang
    `reports\cai-tien-deal-20261031`.
- Dữ liệu: `data\order_lines.parquet` của thư mục cũ. Mỗi dòng = 1 đơn (so_code) × SKU × kho, gồm customer_id, ngày đặt
  (giờ VN) và số lượng. Có 22.816.394 dòng từ 01/01/2025 đến 28/10/2026, dòng nào cũng có customer_id. Customer_id giống
  nhau là cùng một khách. Mọi đánh dấu làm theo từng khách và từng dòng đơn.

### A. Đánh dấu (chỉ dùng dữ liệu trước ngày của dòng / trước ngày dự báo)

**A1. Mức mua thường.** Với mỗi dòng của khách × SKU × kho, lấy các dòng trong 180 ngày trước đó và tính:
- n: số dòng;
- trung vị số lượng mỗi dòng;
- trung vị khoảng cách giữa các ngày mua;
- mức dùng mỗi ngày = trung vị số lượng ÷ khoảng cách trung vị.

**A2. Dòng đột biến** khi thoả một trong hai điều kiện:
- n ≥ 3 và số lượng ≥ 3 × trung vị của chính khách;
- n < 3 và số lượng ≥ 2 × med28 và ≥ 5 sản phẩm (nhóm C: ≥ 3).

Trong đó:
- med28 là trung vị lượng bán ngày của SKU × kho trong 28 ngày mở bán trước (cần ít nhất 14 ngày).
- Năm 2025 không có giờ mở bán, nên mọi ngày đều được coi là ngày mở bán.
- Nhóm là B7 tính tại ngày 1 của tháng; năm 2025 dùng nhóm B.

**A3. Xếp loại tại thời điểm t** (chỉ dùng các dòng đột biến trước t):
- CÓ CHU KỲ: có ít nhất 3 dòng đột biến, và thoả một trong ba điều kiện:
  - hệ số biến thiên của khoảng cách giữa các ngày đột biến ≤ 0,5 (cần ít nhất 2 khoảng cách);
  - ít nhất 50 % rơi vào cùng một thứ trong tuần;
  - ít nhất 50 % rơi vào cùng một khoảng ngày trong tháng (1–5, 6–10, 11–15, 16–20, 21–25, 26–31).
- KHÔNG LẶP LẠI: các trường hợp còn lại.

**A4. Phần vượt** = số lượng − trung vị của khách (n < 3: trừ med28), không âm. Chỉ trừ khi khách đang ở loại KHÔNG LẶP LẠI.

### B. Biến mới

**B1. Demand nền tại mốc t** = Y − phần vượt của các dòng KHÔNG LẶP LẠI (ngày < t).
- Mọi biến của mốc t đều tính trên demand nền: lag, trung bình, trung vị, phân vị, hồ sơ ngày, và cả biến chịu đột biến
  của V33_L112.
- Nhãn học vẫn là demand thực (B3).

**B2. Biến "khách còn hàng"** (chỉ có ở V38b).

Biến tại mốc:
- `sp_days_since`: số ngày kể từ dòng đột biến gần nhất của SKU × kho.
- `sp_last_ratio`: số lượng của dòng đó ÷ mức tham chiếu.

Biến cho ngày đích T:
- Mỗi khách có dòng KHÔNG LẶP LẠI trong 60 ngày qua được coi là còn đủ hàng đến ngày = ngày mua + phần vượt ÷ mức dùng
  mỗi ngày. Nếu khách chưa có mức dùng thì dùng med28 của SKU.
- `sp_cov_n`: số khách còn đủ hàng tại T.
- `sp_cov_qty`: tổng lượng mua thường (trung vị mỗi dòng) của các khách đó.

**Hai ứng viên:**
- V38a = V33_L112 tính trên demand nền.
- V38b = V38a cộng biến B2.

**Rò rỉ** (`leak_spike.json`, tại 20/07 và 12/10):
- Đổi số lượng, xoá hoặc thêm dòng đơn từ ngày D trở đi: dấu đột biến, demand nền và biến B2 của mốc D không đổi.
- Đổi dòng đơn ngày D−1: cả ba đổi theo.
- Cả 4 phép kiểm tra đều đạt.

### Tài nguyên

- `spike_orders.py drive / rest` canh tài nguyên trong suốt thời gian chạy:
  - pin < 15 % mà đang dùng pin: dừng ngay ở checkpoint gần nhất (một lô chỉ được coi là xong khi đã ghi file kết quả và
    SHA), cắm sạc lại thì chạy tiếp;
  - commit < 1,5 GB: tạm dừng, chạy tiếp khi commit ≥ 2,5 GB;
  - không chạy trong khung giờ production 04:45–06:40.
- Mỗi lúc chỉ một việc nặng. Chấm điểm và chọn theo SKU là việc nhẹ.

### Tiến trình

| Giờ | Bước |
|---|---|
| 16:04–16:06 | A: đánh dấu và `danh_dau_don_dot_bien.xlsx` |
| 16:08 | Rò rỉ đạt 4/4 |
| 16:09–16:41 | V38a, lô 14–21 |
| 16:41–17:14 | V38b, lô 14–21 |
| 17:14–17:17 | Cổng 1 |

- Máy cắm sạc suốt thời gian chạy, nên không lần nào phải tạm dừng vì pin hay bộ nhớ.
- Kiểm tra rò rỉ theo lô và theo ngày: 16 lô, tất cả đạt.

### Kết quả A (dòng đơn năm 2026, 01/01–28/10)

Có 9.092.187 dòng; 398.125 dòng bị đánh dấu đột biến (4,38 %).

| | % lượng bị đánh dấu | % phần vượt (KHÔNG LẶP LẠI) |
|---|---:|---:|
| Tổng | 19,64 % | 12,36 % |
| Nhóm A | 16,83 % | 9,90 % |
| Nhóm B | 20,72 % | 13,49 % |
| Nhóm C | 48,76 % | 37,18 % |
| Kho BD | 15,78 % | 9,95 % |
| Kho HN | 28,69 % | 18,03 % |

- 37 % số dòng đột biến được bắt theo mức mua của chính khách (n ≥ 3).
- 15 % số dòng đột biến thuộc loại CÓ CHU KỲ.

### Kết quả cổng 1 (ngày dự báo 01–22/10; đơn vị %)

N1 = ngày thứ 1, 7N = 7 ngày.

| Phương án | Đúng N1 | Đúng S2 N1 | Thiếu N1 | Dư N1 | Lệch N1 | Đúng 7N | Đúng S2 7N | Thiếu 7N | Lệch 7N |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V33_L112 | 70,07 | 41,19 | 31,74 | 33,95 | 65,69 | 69,95 | 40,18 | 33,60 | 68,02 |
| V38a | 68,81 | 41,15 | 31,90 | 33,65 | 65,54 | 68,68 | 39,24 | 33,42 | 68,02 |
| V38b | 69,57 | 41,04 | 32,18 | 33,48 | 65,66 | 69,46 | 39,33 | 33,64 | 68,05 |
| SEL2 6 ứng viên (S62 = CUOI) | 73,83 | 44,82 | 31,98 | 34,53 | 66,52 | 73,97 | 43,50 | 33,80 | 69,13 |
| (2) V38b THAY V33_L112 (R62) | 74,07 | 45,22 | 32,03 | 33,94 | 65,97 | 74,17 | **43,35** | 33,76 | 68,63 |
| (3) V38b THÊM, 7 ứng viên (A72) | 74,07 | **44,31** | 32,02 | 34,02 | 66,04 | 74,17 | **42,89** | 33,82 | 68,60 |

**Quy tắc giữ** (không nới): ở cả N1 và 7N, Đúng và Đúng S2 đều phải cao hơn, thiếu không tăng quá 1 điểm, lệch không tăng
quá 2 điểm.

- (1) V38a so với V33_L112: Đúng −1,26 / −1,27 điểm. KHÔNG GIỮ.
- (1) V38b so với V33_L112: Đúng −0,49 / −0,49 điểm, Đúng S2 −0,15 / −0,85 điểm. KHÔNG GIỮ.
- (2) R62 so với S62:
  - Đúng +0,23 / +0,20 điểm;
  - Đúng S2 +0,40 ở N1 nhưng **−0,15 ở 7N**;
  - thiếu +0,05 / −0,04 điểm; lệch −0,55 / −0,50 điểm.
  - KHÔNG GIỮ, chỉ vì Đúng S2 ở 7N.
- (3) A72 so với S62: Đúng +0,24 / +0,20 điểm, Đúng S2 **−0,51 / −0,61** điểm. KHÔNG GIỮ.

**Quyết định:** không có phương án đạt, nên DỪNG sau cổng 1 và không chạy phần D (toàn kỳ). Không có goi2_CUOI3.

**Riêng các ô có đơn đột biến KHÔNG LẶP LẠI trong 14 ngày trước** (79.843 ô N1; nhóm A 10.397 ô):
- R62 so với S62:
  - toàn bộ các ô này: Đúng N1 +0,69 điểm, 7N +0,54 điểm, nhưng Đúng S2 −0,30 / −0,46 điểm;
  - riêng nhóm A: Đúng +0,09 / +0,05 điểm, Đúng S2 gần như không đổi.
- V38a làm Đúng S2 của các ô này tăng so với V33_L112 (24,11 so với 21,71 ở N1), nhưng Đúng chung của nó lại giảm.

## 2. data_checks

Nguồn: `reports\cai-tien-dotbien-20261031\data_checks.md` (worktree MAIN).

```json
{
 "flags": {
  "lines": 22816394,
  "spike_lines": 832898,
  "spike_pairs": 511435,
  "seconds": 54
 },
 "summaryA": {
  "tong_2026": {
   "index": "TONG_2026",
   "so_dong": 9092187,
   "luong_ban": 42532490.0,
   "dong_dot_bien": 398125,
   "luong_dot_bien": 8351689.0,
   "phan_vuot": 5258042.0,
   "dong_khong_lap_lai": 338524,
   "pct_dong_dot_bien": 4.378759477780209,
   "pct_luong_bi_danh_dau": 19.63602178005567,
   "pct_phan_vuot": 12.362412828404826
  },
  "by_group": {
   "A": {
    "pct_dong_dot_bien": 2.0,
    "pct_luong_bi_danh_dau": 16.83,
    "pct_phan_vuot": 9.9
   },
   "B": {
    "pct_dong_dot_bien": 4.57,
    "pct_luong_bi_danh_dau": 20.72,
    "pct_phan_vuot": 13.49
   },
   "C": {
    "pct_dong_dot_bien": 20.91,
    "pct_luong_bi_danh_dau": 48.76,
    "pct_phan_vuot": 37.18
   }
  },
  "rule_n_ge_3_share": 37.19,
  "periodic_share": 14.97
 }
}
```

## 3. leakage_summary

Nguồn: `reports\cai-tien-dotbien-20261031\leakage_summary.md` (worktree MAIN).

Spike marks / base demand / B2 columns (leak_spike.json): passed = True

- 2026-07-20 doi_dong_tu_ngay_D_tro_di: passed=True
- 2026-07-20 doi_dong_ngay_D-1: passed=True
- 2026-10-12 doi_dong_tu_ngay_D_tro_di: passed=True
- 2026-10-12 doi_dong_ngay_D-1: passed=True

Runner per-batch / per-day checks (data < D, targets D..D+6, scope): 122 checks, 122 passed (V38a 14, V38a 15, V38a 16, V38a 17, V38a 18, V38a 19, V38a 20, V38a 21, V38b 14, V38b 15, V38b 16, V38b 17, V38b 18, V38b 19, V38b 20, V38b 21)
Runtime guard (Spikes.excess_cells): every excess subtracted at origin t has day < t; the class of a pair at t uses
its spike lines < t only; each line's own statistics use the pair's lines in [day-180, day-1] only.
