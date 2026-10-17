# E0 — Phân rã sai số của model phát hành (DIRECT, Giá BẬT) — 17/10/2026

Chỉ phân tích, không chọn hay tinh chỉnh gì. **Không chạy E2, E3, E4.**

## Phạm vi và cách làm

| Mục | Giá trị |
|---|---|
| Dữ liệu | Bản sao cô lập DB thật. BigQuery 01/01–15/10/2026: 1.347.346 ngày × SKU × FC, 17.137 chuỗi, 9.661 SKU, 2 FC. Độ phủ giá 99,98 % |
| Cấu hình | Model phát hành: DIRECT, nhóm Giá bật (31 feature). So sánh với cùng cấu hình chỉ nhu cầu |
| Walk-forward | Giống hệt backtest production: 7 fold × 30 ngày; mốc 20/03, 19/04, 19/05, 18/06, 18/07, 17/08, 16/09. Mỗi model chỉ học dữ liệu trước mốc của nó |
| Điểm đánh giá | 3.353.298 (cùng tập điểm cho hai cấu hình). Đơn vị: số lượng đặt hàng / ngày / SKU × FC |
| Tái lập | WAPE có giá **0,808117** và chỉ nhu cầu **0,805953**, trùng tuyệt đối với `price_backtest.json` (00:59) và với lần huấn luyện diễn tập 1.2.0 |
| Thời gian, tài nguyên | 1.254 s (21 phút), một tiến trình, chạy lúc không có job nặng nào khác |
| Kết quả | `e0_results.json` (tổng hợp theo nhóm); `e0_error_analysis.py` (mã). Dự báo từng điểm nằm ở thư mục tạm của phiên (`e0_points.npz`, 34 MB, không commit) |

**Định nghĩa nhóm:**
- *Trước mốc dự báo:* các nhóm sau chỉ tính từ dữ liệu **trước** mốc, nên model có thể biết:
  - loại cầu theo tỷ lệ ngày = 0 trong 28 ngày;
  - mức bán trung bình 56 ngày;
  - giá cuối so với trung bình giá 28 ngày;
  - tần suất đổi giá trong 28 ngày.
- *Sau mốc dự báo:* nhóm "giá ngày đích so với giá đã biết tại mốc" chỉ để **mô tả**. Model không biết giá trị này và
  nó không bao giờ là đầu vào.
- *Quy ước phân tích:* nhóm có ≥ 5.000 điểm và ≥ 5.000 đơn vị thì đủ mẫu. Đây không phải ngưỡng nghiệp vụ. Mọi nhóm dưới
  đây đều đủ mẫu theo quy ước này, nhưng tác động nhỏ hơn khoảng 0,005 WAPE vẫn được coi là **chưa đủ bằng chứng**,
  vì dao động giữa các fold lớn hơn mức đó.

Chú thích các cột trong các bảng dưới:
- *Có giá* là WAPE của model phát hành (DIRECT, Giá bật).
- *Chỉ NC* là WAPE của cùng cấu hình chỉ dùng nhu cầu.
- *Bias* là bias của model có giá.

## Kết quả tổng

| | WAPE | Bias | MAE |
|---|---|---|---|
| Có giá (model phát hành) | 0,8081 | +0,072 | 6,752 |
| Chỉ nhu cầu | 0,8060 | +0,069 | 6,734 |
| Baseline | 0,8390 | +0,119 | — |

64 % số điểm bị dự báo dư. Phần lớn là các số dư nhỏ ở ngày thực tế bằng 0.

## Sai số tập trung ở đâu (đủ bằng chứng)

| Nhóm | % điểm | % tổng sai số tuyệt đối | Có giá | Chỉ NC | Bias |
|---|---|---|---|---|---|
| Chuỗi bán ≥ 20/ngày (56 ngày trước mốc) | 7,5 % | **70,0 %** | 0,715 | 0,713 | +0,080 |
| Chuỗi bán 5–20/ngày | 12,1 % | 15,6 % | 1,030 | 1,027 | +0,130 |
| Chuỗi bán < 1/ngày | 55,9 % | 4,2 % | 1,449 | 1,450 | −0,316 |
| Chuỗi dùng LightGBM | 46,7 % | **93,6 %** | 0,785 | 0,782 | +0,084 |
| Chuỗi dùng fallback | 53,3 % | 6,4 % | 1,441 | 1,441 | −0,259 |

- **191 trong 9.661 SKU gây 50 % tổng sai số.** 1 % SKU lớn nhất gây 40,5 %, 10 % SKU lớn nhất gây 75,4 %. SKU lớn nhất,
  `MEDX.DMTS-SAN-ALP-001`, chiếm 2,0 %.
- Muốn cải thiện WAPE tổng, phải cải thiện **nhóm bán nhiều** (≥ 5/ngày). Nhóm bán ít có WAPE cao nhưng gần như không
  ảnh hưởng tới WAPE tổng.
- Ở các nhóm bán 1–5/ngày và 5–20/ngày, baseline ngang hoặc tốt hơn LightGBM một chút (1,306 so với 1,333; 1,026 so với
  1,030). LightGBM chỉ thắng rõ ở nhóm ≥ 20/ngày (0,715 so với 0,757).

## Theo FC, kỳ dự báo, thời gian

| Nhóm | Có giá | Chỉ NC | Bias | % sai số |
|---|---|---|---|---|
| BD | 0,744 | 0,742 | +0,054 | 64,5 % |
| HN | 0,959 | 0,956 | +0,113 | 35,5 % |
| Ngày 1–7 | 0,702 | 0,703 | +0,029 | 21,2 % |
| Ngày 8–15 | 0,837 | 0,837 | +0,096 | 26,6 % |
| Ngày 16–30 | 0,845 | 0,840 | +0,081 | 52,2 % |
| HN, ngày 8–15 | 1,016 | 1,014 | +0,163 | 9,5 % |

- **Theo ngày dự báo:** WAPE tăng từ 0,649 ở ngày 1 lên khoảng 0,82–0,89 từ ngày 8 trở đi. Model DIRECT không bị trôi bias
  theo kỳ dự báo, bias các ngày nằm trong khoảng −0,06 đến +0,16.
- **HN** kém hơn BD ở mọi kỳ dự báo và dư nhiều hơn.
- **Theo thời gian:** tháng 4 (WAPE 0,897, bias **+0,291**) và fold 6 (mốc 20/03: 0,852, +0,217) dư mạnh. Fold 11 (mốc
  17/08: **1,101**, bias +0,277) kém nhất. Tháng 9 có WAPE 0,981.
- Ở fold 6, fold 8, tháng 3 và tháng 4, **baseline tốt hơn model**. Đây là các giai đoạn nhu cầu đổi mức, model chưa theo
  kịp.

## Theo nhóm giá

**Trước mốc dự báo** (model có thể biết):

| Giá cuối so với trung bình 28 ngày | % điểm | Có giá | Chỉ NC | Chênh lệch | Bias |
|---|---|---|---|---|---|
| Rẻ hơn (< 0,97) | 8,5 % | 0,901 | 0,893 | +0,008 | +0,121 |
| 0,97–0,99 | 8,2 % | 0,885 | 0,882 | +0,003 | +0,110 |
| **Ổn định (0,99–1,01)** | **67,7 %** | 0,761 | 0,758 | +0,003 | +0,064 |
| 1,01–1,03 | 8,5 % | 0,943 | 0,938 | +0,005 | +0,123 |
| Đắt hơn (≥ 1,03) | 5,8 % | 0,882 | 0,895 | **−0,013** | +0,055 |

| Tần suất đổi giá trong 28 ngày | % điểm | Có giá | Chỉ NC | Chênh lệch |
|---|---|---|---|---|
| Không đổi | 38,2 % | 0,664 | 0,661 | +0,003 |
| < 25 % số ngày | 49,7 % | 0,858 | 0,857 | +0,000 |
| 25–50 % | 9,5 % | 0,938 | 0,935 | +0,003 |
| ≥ 50 % | 1,2 % | 0,883 | 0,866 | +0,017 |

**Sau mốc dự báo** (chỉ để mô tả; model không biết):

| Giá ngày đích so với giá tại mốc | % điểm | Có giá | Chỉ NC | Bias |
|---|---|---|---|---|
| Giảm > 3 % | 8,7 % | 0,881 | 0,878 | **−0,311** (dự báo thiếu) |
| Trong ±3 % | 82,8 % | 0,762 | 0,761 | +0,085 |
| Tăng > 3 % | 7,2 % | **1,200** | 1,183 | **+0,503** (dự báo dư) |

## Kết luận

**Đủ bằng chứng:**
1. Sai số tập trung ở chuỗi bán nhiều: ≥ 5/ngày chiếm 85,6 % sai số, và 191 SKU chiếm một nửa.
2. Sai số tăng theo kỳ dự báo: ngày 1–7 có WAPE 0,70, ngày 16–30 có 0,85. HN kém và dư nhiều hơn BD.
3. Giai đoạn đổi mức nhu cầu (tháng 3–4, fold 11 từ giữa tháng 8) là nơi model kém nhất và dư mạnh nhất. Ở một số giai
   đoạn, baseline tốt hơn.
4. Chuỗi có giá ổn định (67,7 % số điểm) dễ dự báo hơn hẳn chuỗi có giá thay đổi (0,76 so với 0,88–0,94).
5. Khi giá **sau mốc** tăng > 3 %, model dư mạnh (+0,50); khi giá giảm > 3 %, model thiếu (−0,31). Model không có thông
   tin về giá tương lai.

**Chưa đủ bằng chứng hoặc chỉ là tương quan:**
- Hai feature giá hiện có giúp ở nhóm "đắt hơn" (−0,013) nhưng hại ở nhóm "rẻ hơn" (+0,008) và nhóm đổi giá ≥ 50 %
  (+0,017). Các chênh lệch này nhỏ hơn dao động giữa các fold. **Không** kết luận được giá có ích hay có hại theo nhóm.
- Điểm 5 là **tương quan, không phải nhân quả.** Giá bình quân theo số lượng phụ thuộc cơ cấu đơn: ngày có đơn lớn thường
  có giá bình quân thấp và số lượng cao. Một phần mối liên hệ có thể đến từ chính cách đo giá này.

**Hạn chế:**
- Một lần chạy trên một giai đoạn 7 tháng. Không có dữ liệu ngoài mẫu 16/10–15/11 (chưa có, không giả lập).
- Giá theo lần nạp mới nhất, không phải giá đúng như tại từng thời điểm.
- 46.398 điểm của chuỗi chưa có lịch sử tại mốc được dự báo 0, nên bias = −1.

## Gợi ý cho quyết định tiếp theo (chưa làm, chờ duyệt)

Gợi ý dựa trên E0, không phải kết quả:
- E2 nên nhắm vào **nhóm bán nhiều** và **chuỗi có giá thay đổi**.
- Nên thử một giá ít nhiễu theo cơ cấu đơn, ví dụ giá thấp nhất hoặc trung vị trong ngày.
- Nên thử thông tin giá **mới nhất tại thời điểm dự báo**: bảng D-0 có `sales_price` của hôm nay.
- Việc model kém ở giai đoạn đổi mức (tháng 3–4, tháng 8–9) là vấn đề của lịch sử nhu cầu, không phải của giá. Nên xem
  xét riêng (E4: tham số, độ dài cửa sổ).

Theo yêu cầu, **không** chạy E2, E3, E4.
