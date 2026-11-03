# Sự cố giờ mở bán và MULTI_ITEM

Thứ trong tuần / total_open_hours, 931 khoá giờ mở bán = 0, MULTI_ITEM 19–21/10/2026.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\demandforecast_multi_item_overforecast_20261020.md` (MAIN) | 20/10/2026 | 42924 | `CE38458A19C5610AA6382D087732FB0632F9D8409DBA53408ED13098661AA98B` |
| 2 | `reports\demandforecast_zero_hours_followup_audit_20261020.md` (MAIN) | 20/10/2026 | 31599 | `DBDCD674127A168347009EBBF192461460C95DA165BFCD7BFC26B64D6A1BB53F` |
| 3 | `reports\multi-item-d1-20261021\DATA_RECONCILIATION.md` (MAIN) | 21/10/2026 | 7344 | `0FDB2C521DD034A59308D5A33F5723DBAF8A502FB815C56FC733C2A0BAD3DFAC` |
| 4 | `reports\multi-item-d1-20261021\FINAL_REPORT.md` (MAIN) | 21/10/2026 | 9675 | `BDCD06274271C735D73F85A699400D774596825DCE09947EF153D411E405D51F` |
| 5 | `reports\multi-item-d1-20261021\RESUME_CHECKPOINT.md` (MAIN) | 21/10/2026 | 4373 | `4C16D4BDD6779DBAD46F3B9F9AC9D49EA1F39A74FC0366E463B990DBE38E985C` |
| 6 | `reports\multi-item-d1-20261021\TEST_RESULTS.md` (MAIN) | 21/10/2026 | 6769 | `CEEB935E9693A3CA01FBF77A10141725A45776EECCC28FFFC185466B049C1A70` |
| 7 | `reports\weekday_total_open_hours_mapping_fix.md` (MAIN) | 19/10/2026 | 20999 | `B0F937C59F7B1E25DB6ABED46EF4E070E5A657871BF1A55A41B4EF92BD4764A3` |

## 1. Demand Forecasting: kiểm tra MULTI_ITEM và dự báo dư ngày thường (1.2.9, đợt 4)

Nguồn: `reports\demandforecast_multi_item_overforecast_20261020.md` (worktree MAIN).

Thời gian: 20/10/2026, từ 12:44 đến khoảng 14:00 (tạo checkpoint cuối), giờ Asia/Ho_Chi_Minh.

Phạm vi: prompt "MULTI_ITEM DATA REVIEW & NORMAL-DAY OVERFORECAST OPTIMIZATION".
- P0: xuất Excel MULTI_ITEM.
- P1: dự báo dư ngày thường.
- P2 (spike) để sau.

Trong đợt này **không làm**:
- commit, push, đóng gói hay deploy;
- huấn luyện, backfill hay D-0 / D-1 / EOD trên production;
- đổi lịch hay cấu hình;
- promote;
- tắt Price hay bật `customer_id`;
- sửa hay xóa dòng MULTI_ITEM;
- xóa dữ liệu, log hay checkpoint.

Thí nghiệm S0–S6 không chạy lại; S0 dùng lại kết quả đã lưu.

**Production** (kiểm tra chỉ đọc qua `/api/health` và `/api/jobs`):
- Vẫn là 1.2.8, PID 10884; `storage.json` không đổi (`8D79DBDD…`).
- Sau báo cáo đợt 3 (kiểm tra job lúc 12:16), production có thêm 3 job. **Claude không khởi động job nào**:

| Lúc | Job | Trigger | Kết quả |
|---|---|---|---|
| 12:29:54 | D-1 | MANUAL | SUCCEEDED: 91.713 dòng, 107 s |
| 12:31:46 | huấn luyện theo lịch | SCHEDULE | SKIPPED `MISSED_SLOT_NO_BACKFILL` |
| 12:43:39 | huấn luyện | MANUAL | SUCCEEDED lúc 13:16:01: ứng viên `TRN-20261020054540-D7EEF6`, `PROMOTION_REVIEW_REQUIRED` (chưa promote, model đang dùng không đổi) |

- Hai job MANUAL được khởi động từ giao diện ứng dụng. Job D-1 đọc 91.713 dòng BigQuery thật trong 107 s; test của Claude chạy với DB tạm và client giả, không làm được điều đó.
- **Đính chính báo cáo đợt 3:** câu "hôm nay chỉ có các job do lịch tự chạy" chỉ đúng tới lần kiểm tra 12:16.

**Trạng thái đề xuất: `BLOCKED_DATA_SAFETY`** (không đổi so với đợt 3). Quy tắc cho các khóa MULTI_ITEM vẫn chờ chủ hệ thống quyết định. Kết quả thí nghiệm của đợt này chỉ là nghiên cứu.

### A. Tóm tắt

| Hạng mục | Trạng thái | Tóm tắt |
|---|---|---|
| P0. Excel MULTI_ITEM | **PASS** (đã xuất và kiểm tra) | `D:\Buymed\Lightgbm AI\reports\demandforecast_multi_item_review_20261020.xlsx`, SHA-256 `0C4C7ADA…DEADA`, 7 sheet (Detail 15 dòng, Summary 27). Dữ kiện: 2 khóa cùng FC BD, 2 listing (`.1` / `.2`), đơn khác nhau; hai dòng `.2` cùng một đơn. Giả thuyết `.2` = listing miền HN: **cần chủ hệ thống xác nhận**; quy tắc gộp chờ quyết định |
| P1. Kiểm tra chỉ số | **PASS** | Tái lập đúng +19,4% của báo cáo trước. Đó là **bias có dấu**; theo công thức B (chỉ phần dư) ngày thường là **48,6%** (giữ lại 41,7%) |
| P1. Nguyên nhân | **PASS** (có bằng chứng) | (1) Toàn bộ bias dương ngày thường là forecast trên các ngày actual = 0 (71,6% điểm ngày thường). (2) Nhu cầu giảm từ 161k xuống 86k / ngày qua các fold: 66% phần dư ở chuỗi đang giảm, chuỗi ổn định chỉ +1,5%. Không có lỗi grain / gộp / làm tròn |
| P1. Mục tiêu 1–5% | **Không đạt (6/6 FAIL)** | Gần nhất là K5 (trung vị): 28,1%, nhưng tổng thiếu 27% (giữ lại 48%). Hiệu chỉnh K2 / K6 cải thiện sàng lọc nhưng quá tay ở fold giữ lại (−23%). Theo công thức B ở hạt ngày, < 5% chỉ đạt khi forecast còn khoảng 20% |
| Lỗi phát hiện khi chạy test | **Đã sửa** | Kiểm tra lại bản xem trước backfill (mã đợt 2) không nhận ra lần nạp D-1 trong cùng giây (dấu thời gian 1 giây); thêm `load_id` và test cố định thời gian |
| Production | Không đụng | 1.2.8; mọi job sau 12:16 do người dùng hoặc lịch |

**Blocker và quyết định cần chủ hệ thống:**
1. Quy tắc giờ mở bán cho khóa MULTI_ITEM; xác nhận `.2` = listing miền HN và đơn `SOBD38271068`.
2. **Định nghĩa mục tiêu dự báo dư đo được**: chỉ số (bias có dấu hay chỉ phần dư), mức tổng hợp (ngày × chuỗi, tổng 30 ngày, toàn mạng), tập ngày (ngày thường hay mọi ngày).
3. Nguyên nhân nhu cầu giảm từ tháng 7, và ngày không đơn có phải do listing đóng / hết hàng không. Nguồn không có giờ mở bán cho ngày không đơn.

### B. Kiểm tra dữ liệu MULTI_ITEM (P0)

**File Excel:** `D:\Buymed\Lightgbm AI\reports\demandforecast_multi_item_review_20261020.xlsx`
- 35.650 byte.
- SHA-256 `0C4C7ADAC663681B570463CB37532659A4C4B1A22FC88FC40FAC62B3FB8DEADA`.
- Nằm ngoài Git, không upload đi đâu.

| Sheet | Số dòng dữ liệu | Nội dung |
|---|---|---|
| `MULTI_ITEM_Detail` | 15 | Mọi dòng nguồn của 2 SKU ngày 26/08, mọi FC: 12 dòng thuộc 2 khóa MULTI_ITEM (FC BD), 3 dòng FC HN để đối chiếu. Cột gốc của nguồn và cột suy ra: dòng hợp lệ D-1, khóa nghiệp vụ, trạng thái theo code hiện tại, số dòng của item ở BD / HN cả kỳ, FC chính của item, cờ thuộc đơn `SOBD38271068` |
| `Summary` | 27 | Thời điểm trích xuất, nguồn, phạm vi, điều kiện lọc, số dòng / khóa / item / giá trị giờ, kết quả kiểm tra, dữ kiện / giả thuyết / việc cần quyết định |
| `Key_Aggregation` | 3 | Hạt của pipeline (ngày × SKU × FC): tính lại từ dòng nguồn so với giá trị đã lưu trong bản sao DB |
| `Item_FC_History` | 6 | Item × FC cả kỳ: số dòng, số ngày, số lượng, tỷ lệ, ngày đầu / cuối |
| `Item_Day_Hours` | 574 | Item × ngày × FC cả kỳ: số dòng, số lượng, số giá trị giờ khác nhau, giờ |
| `Order_SOBD38271068` | 11 | Mọi dòng của đơn chứa 2 dòng item `.2` ở BD |
| `Source_Trace` | 11 | Câu SQL, bảng nguồn, ánh xạ cột → pipeline, quy tắc dòng hợp lệ, tổng hợp D-1, quy tắc trạng thái giờ, artifact đối chiếu |

**Nguồn và truy vấn** (chỉ SELECT, dry run trước, giới hạn 3 GiB, không DML/DDL, không bảng tạm):

| | Giá trị |
|---|---|
| Bảng | `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`, 17 cột, không phân vùng |
| Bản nguồn | Làm mới 20/10 **12:29:24** (`refresh_time`; bảng sửa lúc 05:29:33 UTC), trích xuất 12:46:37 |
| Truy vấn 1 | Mọi dòng của `MEDX.COU-STR-001` và `MEDX.D6TABCV8`, mọi FC, 01/01–19/10: 2.115 dòng, 1,43 GB |
| Truy vấn 2 | Mọi dòng của đơn `SOBD38271068`: 11 dòng, 0,89 GB |

Không đọc `sku_system_status`. Nguồn không có cột khách hàng.

**Kiểm tra lại workbook** (`scratchpad\p19\verify_multi_item.py`):
- Detail có 15 dòng = 15 dòng truy vấn; tập dòng khớp từng trường.
- Kiểu đúng: ngày là ngày, `so_code` là chữ, số lượng là số nguyên, giờ khớp đến số lẻ.
- Không có dòng tổng hợp giả.
- Tổng dòng và số lượng của `Item_Day_Hours` / `Item_FC_History` = 2.115 dòng / 6.791 đơn vị của truy vấn.
- Sheet đơn hàng khớp truy vấn 2.
- Trích xuất không có dòng trùng hoàn toàn và không có khóa (đơn, SKU, FC, ngày) lặp lại.

**Dữ kiện đã xác minh:**

| Khóa (26/08, FC BD) | Item | Dòng / đơn | Số lượng | Giờ mở bán | Item bán ở đâu cả kỳ |
|---|---|---|---|---|---|
| `MEDX.COU-STR-001` | `.1` | 7 / 7 | 40 | 23,72 | chỉ BD (1.600 dòng, 257 ngày) |
| | `.2` | 1 / 1 | 2 | 24,00 | HN 249 dòng; BD **1 dòng: chính ngày 26/08** |
| `MEDX.D6TABCV8` | `.1` | 3 / 3 | 3 | 22,85 | chỉ BD (168 dòng, 93 ngày) |
| | `.2` | 1 / 1 | 1 | 18,22 | HN 96 dòng; BD **1 dòng: chính ngày 26/08** |

- Giờ mở bán đo theo **item × ngày**: mọi item-ngày chỉ có 1 giá trị, kể cả khi item bán ở 2 FC trong cùng ngày. Ví dụ `MEDX.D6TABCV8.2` ngày 26/08 có 18,22 ở cả BD và HN.
- Trong mỗi khóa, 2 item thuộc **2 tập đơn khác nhau** (0 đơn chung).
- Cả 2 item cùng FC BD, cùng seller (`MEDX`, INTERNAL); `open_date` = `created_date`.
- Dòng `.2` ở BD của **cả hai** khóa thuộc **cùng một đơn `SOBD38271068`**.
  - Đơn này có 11 dòng, 11 SKU, toàn item `.2` / `.3`, không có item `.1`.
  - 9 trong 11 khóa nhiều item của FC BD ngày 26/08 có dòng của đơn này.
- Tổng hợp của pipeline đúng (D-1 không JOIN). Số lượng / số đơn tính lại từ dòng nguồn bằng giá trị đã lưu trong bản sao: 42 / 8 và 4 / 4 ở BD; 7 / 3 ở HN.
- Trạng thái của 2 khóa:
  - trên bản sao là `CONFLICT` (nạp 19/10 bằng code cũ);
  - theo code hiện tại (`open_hours.cell`) là `MULTI_ITEM`;
  - khóa HN của `D6TABCV8` là `OK` (18,22).
- Giá trị ngày 26/08 của 2 SKU ở bản nguồn 12:29 giống bản 00:10 UTC (đối chiếu `bq_a.json` sáng 20/10).

**Trả lời 4 câu hỏi của mục 3.1:**

| Câu hỏi | Kết luận |
|---|---|
| Hai miền bán khác nhau? | **Giả thuyết, chưa xác minh.** Nguồn không có cột miền bán. Item `.1` chỉ bán qua BD, item `.2` bán qua HN 99,0–99,6% số dòng, nên `.2` có vẻ là listing của miền phía Bắc. Cần chủ hệ thống xác nhận |
| Hai FC khác nhau? | **Không**: cả 2 item đều `fc_code = BD` |
| Hai item cùng một đơn? | **Không** trong mỗi khóa. Nhưng 2 dòng `.2` của 2 khóa là cùng một đơn `SOBD38271068` |
| Cùng khóa nghiệp vụ, giờ khác nhau? | **Cùng khóa ngày × SKU × FC.** Mỗi item có đúng 1 giá trị giờ, nên giá trị khác nhau là giữa 2 listing, không phải mâu thuẫn trong một listing |

**Cần chủ hệ thống quyết định.** Ứng dụng không tự chọn. Phương án ví dụ cho giờ mở bán ở hạt SKU × FC khi một khóa có nhiều item khác giờ:
- giờ của item thuộc chính FC đó;
- trung bình theo số lượng;
- MAX;
- để trống (NaN).

Câu hỏi phụ: đơn `SOBD38271068` (đặt trên listing miền HN, xuất từ BD) có phải trường hợp bình thường không?

Ghi chú: 469 dòng của 2 SKU (trước khoảng 20/03) có `seller_class`, `open_date`, `total_open_hours`, `total_open_days` cùng NULL. Điều này khớp với giới hạn khoảng 7 tháng của giờ mở bán đã báo ở đợt 3.

### C. Kiểm tra baseline và chỉ số (P1)

**Baseline S0** dùng lại kết quả đã lưu của đợt 3, không huấn luyện lại:

| Thành phần | Giá trị |
|---|---|
| Model | Cài đặt production: tweedie 1,2; 300 vòng; 31 lá; lr 0,05; DIRECT; Price BẬT; giờ mở bán BẬT; thứ ISO |
| Cửa sổ | 19/03–18/10 |
| Fold | 4 fold sàng lọc (mốc 22/05, 21/06, 21/07, 20/08) + fold giữ lại 19/09, mỗi fold 30 ngày |
| Dữ liệu | 16.578 chuỗi; bản sao `p18\e8` |

Tham chiếu: E00 (cấu hình production, cửa sổ từ 01/01, bản lưu đợt 2) cho kết quả gần như giống hệt (bảng C3).

**Công thức** (đúng mục 4.2, cài trong `backend/app/ml/overforecast.py`, có test). Trên **cùng một tập quan sát**, mỗi quan sát là 1 SKU × FC × ngày có thực tế:
- Bias = Σ(F − A) / ΣA
- Overforecast (chỉ phần dư) = Σmax(F − A, 0) / ΣA
- Underforecast = Σmax(A − F, 0) / ΣA
- WAPE = Σ|F − A| / ΣA (= over + under)
- Tỷ lệ = ΣF / ΣA

Quy ước:
- ΣA = 0 thì mọi tỷ lệ là "không xác định"; không bỏ quan sát nào.
- Dùng tổng có trọng số (tỷ lệ của các tổng), không lấy trung bình các tỷ lệ.
- F tính hai cách:
  - **RAW**: `yhat` lưu, đầu vào của mọi chỉ số trong ứng dụng;
  - **INT**: làm tròn lên từ 0,5, không âm (`app/qty.py`) = số production xuất ra. Đây là số dùng để xét mục tiêu.

**Đã xác minh:**
- Forecast và actual cùng panel, cùng khóa SKU × FC, cùng ngày đích (`panel.Y[:, mốc : mốc + 30]`).
- Actual = 0 là ngày không có đơn sau ngày bán đầu tiên của chuỗi. Actual = NaN (chuỗi chưa bắt đầu, ngày trống toàn hệ thống) bị loại khỏi mọi chỉ số.
- Khóa duy nhất; không có forecast NaN hay âm.
- **Tổng actual từng ngày đánh giá bằng đúng tổng `demand_daily` của bản sao** (chênh lệch lớn nhất 0, cả 4 fold).

**Phân loại ngày:**
- **ND_OLD** (định nghĩa của báo cáo trước, tái lập được):
  - spike = actual > ngưỡng của chuỗi; ngưỡng `demand_patterns` tính từ 91 ngày **trước** mốc;
  - normal = phần còn lại.
  - Ngưỡng không dùng thông tin tương lai, nhưng nhãn cần actual của chính ngày đó. Vì vậy nhãn chỉ dùng **sau khi có actual** (đánh giá); không bao giờ làm feature (có test).
  - Nhãn không dựa trên việc actual lớn hơn forecast.
- **ALL**: mọi ngày. Đây là cách chia duy nhất không cần thông tin sau thời điểm dự báo: ứng dụng không có lịch sự kiện / lễ đáng tin cậy, và trang Feature ghi "chưa có nguồn".

**Tái lập (ND_OLD, 4 fold sàng lọc):**
- RAW: bias **+19,40%**, over 48,97%, under 29,57%. Khớp bảng 7.5 của báo cáo trước.
- INT: bias +18,98%, over **48,56%**, under 29,59%.

> **Khác biệt quan trọng với cách đọc "19%".** Con số 19% của báo cáo trước là **bias có dấu** (công thức A). Theo **công thức B** (chỉ phần dư) mà prompt chọn làm chỉ số chính, ngày thường của S0 là **48,6%** (INT, sàng lọc) và **41,7%** (fold giữ lại). Báo cáo ghi cả hai, không sửa số cũ.

**C1. Theo fold** (S0, INT):

| Fold | Bias ngày thường | Over ngày thường | Bias mọi ngày | Nhu cầu / ngày: kỳ đánh giá so với 28 ngày trước mốc |
|---|---|---|---|---|
| 22/05 | +4,2% | 35,3% | −11,4% | 161k so với 154k |
| 21/06 | +12,4% | 41,2% | −3,0% | 145k so với 163k |
| 21/07 | +26,1% | 52,5% | +10,1% | 123k so với 144k |
| 20/08 | **+48,5%** | **81,6%** | +19,9% | **86k so với 123k** |
| 19/09 (giữ lại) | +5,9% | 41,7% | −10,1% | 82k so với 85k |

**C2. Theo mức tổng hợp** (S0, INT; sàng lọc / giữ lại):

| Tập | Mức | Bias | Over | Under |
|---|---|---|---|---|
| Ngày thường | SKU × FC × ngày (chính) | +18,98% / +5,86% | **48,56% / 41,70%** | 29,59% / 35,84% |
| Ngày thường | tổng 30 ngày mỗi chuỗi | +18,98% / +5,86% | 33,60% / 28,66% | 14,63% / 22,80% |
| Ngày thường | tổng toàn mạng mỗi ngày | +18,98% / +5,86% | 20,50% / 8,51% | 1,52% / 2,65% |
| Mọi ngày | SKU × FC × ngày | +1,32% / −10,07% | 40,38% / 34,25% | 39,06% / 44,32% |
| Mọi ngày | tổng toàn mạng mỗi ngày | +1,32% / −10,07% | 7,86% / 1,71% | 6,54% / 11,79% |

Bias không đổi theo mức tổng hợp; over càng nhỏ khi tổng hợp càng lớn, vì dư và thiếu bù trừ nhau trong tổng.

**C3. Cấu hình production E00 (tham chiếu, INT):**
- Ngày thường: over 48,37% / 41,35%, bias +18,59% / +5,15%.
- Mọi ngày: bias +1,16% / −10,91%.

Vấn đề không riêng cấu hình 1.2.9.

**C4. Mục tiêu 1–5% có khả thi không?** Nhân đều mọi forecast của S0 với k (4 fold sàng lọc, INT):

| k | Over ngày thường | Bias ngày thường | Under ngày thường | Bias mọi ngày | Under mọi ngày |
|---|---|---|---|---|---|
| 1,00 | 48,6% | +19,0% | 29,6% | +1,3% | 39,1% |
| 0,85 | 36,9% | **+1,0%** | 35,9% | −14,0% | 44,7% |
| 0,50 | 15,6% | −40,9% | 56,6% | −49,7% | 62,7% |
| 0,20 | **4,1%** | −76,9% | 81,0% | −80,3% | 83,7% |
| 0,10 | 1,6% | −88,8% | 90,4% | −90,5% | 91,8% |

- Theo **công thức B ở hạt SKU × FC × ngày**, over chỉ xuống dưới 5% khi forecast còn khoảng 20% mức hiện tại; khi đó thiếu 81% nhu cầu ngày thường.
- Lý do: nhu cầu từng ngày của phần lớn chuỗi là gián đoạn (71,6% điểm ngày thường có actual = 0). Bất kỳ dự báo trung bình nào cũng dư ở những ngày đó.
- Theo **bias có dấu**, ngày thường vào khoảng 1–5% khi k ≈ 0,85–0,87, nhưng tổng mọi ngày thiếu khoảng 14%.
- Đây là phân tích khả thi trên baseline, **không phải** cấu hình ứng viên.

### D. Nguyên nhân dự báo dư ngày thường

Số liệu S0, 4 fold sàng lọc, RAW, trừ khi ghi khác.

**D1. Toàn bộ bias dương của ngày thường nằm ở các ngày actual = 0.**
- 1.310.886 điểm ngày thường có actual = 0 (71,6%) nhận 2,49 triệu đơn vị forecast = **19,4% nhu cầu ngày thường**. Đúng bằng bias.
- Trên các ngày thường có đơn, bias **+0,04%** (fold giữ lại −6,9%). Over 29,6% và under 29,6% ở đó cân nhau, tức là sai số hai chiều của từng ngày.
- Cơ chế (dữ kiện):
  - dự báo trung bình của chuỗi gián đoạn rải lượng kỳ vọng lên mọi ngày;
  - tách spike ra khỏi "ngày thường" bỏ 16,9% nhu cầu nhưng chỉ bỏ 2,4% forecast (S0 dự báo được 14,5% lượng spike).
- Vì vậy, khi không biết trước ngày nào có đơn và ngày nào spike, bias ngày thường dương là **hệ quả của cách chia ngày**, không chỉ là lỗi model.

**D2. Mức nhu cầu giảm (level shift) là nguyên nhân lớn nhất trong phần còn lại.**
- Nhu cầu toàn mạng giảm qua các fold (bảng C1). Bias mọi ngày đi từ −11% lên +20% khi nhu cầu giảm, rồi về −10% khi ổn định.
- Bias ngày thường tăng theo ngày trong kỳ: ngày 1–7 +14,6%, 8–15 +16,2%, 16–30 +23,3%.
- Tỷ lệ ngày không đơn: kỳ đánh giá 65→82%, so với 51→66% của 28 ngày trước.
- Theo chuỗi, chia theo tỷ lệ nhu cầu kỳ đánh giá / 28 ngày trước mốc. Cách chia này **dùng actual**, chỉ để chẩn đoán:

| Tỷ lệ | Phần nhu cầu ngày thường | Phần của tổng over | F − A (đơn vị) | Bias |
|---|---|---|---|---|
| < 0,5 (giảm mạnh) | 8,1% | **41,2%** | +2.385.749 | +230% |
| 0,5–0,8 | 21,6% | **25,1%** | +1.062.266 | +38,3% |
| 0,8–1,25 (ổn định) | 43,2% | 23,9% | +81.679 | **+1,5%** |
| 1,25–2 | 17,8% | 7,2% | −434.498 | −19,0% |
| ≥ 2 | 8,7% | 2,7% | −533.679 | −47,6% |

- Ở fold giữ lại, chuỗi ổn định có bias +7,6%.
- Nguyên nhân giảm từ tháng 7 (đã ghi nhận từ 16/10, khoảng 160–200k xuống khoảng 80k / ngày) **chưa được giải thích** bằng dữ liệu hiện có.

**D3. Tập trung:**
- 1% chuỗi-fold chiếm 40,6% tổng over; 10% chiếm 78,4%.
- Nhóm 10% này:
  - 57% HIGH_VOLUME;
  - theo nhóm nhu cầu: ERRATIC 49%, SMOOTH 25%, LUMPY 21%;
  - trung vị tỷ lệ kỳ đánh giá / 28 ngày trước = 0,63 (đang giảm);
  - giữ 71% nhu cầu ngày thường.
- Theo nhóm (bias / over ngày thường):

| Nhóm | Bias | Over |
|---|---|---|
| SMOOTH | +6,0% | 28,7% |
| ERRATIC | +27,2% | 55,5% |
| LUMPY | +52,2% | 104,3% |
| INTERMITTENT | +6,8% | 71,1% |
| HIGH_VOLUME | +16,2% | 41,5% |
| LOW_VOLUME | +35,8% | 80,2% |

**D4. Các yếu tố khác đã kiểm tra:**

| Yếu tố | Kết quả | Kết luận |
|---|---|---|
| Thứ trong tuần | Bias ngày thường +15,4% (thứ 7) đến +22,6% (thứ 4). Mọi ngày: thứ 6 −6,6%, chủ nhật +8,2% | Có lệch nhẹ, không phải nguyên nhân chính |
| Lag / rolling | Theo tỷ lệ TB 7 / TB 28 ngày trước mốc (biết trước): ≥ 2 → +52,6%; 1,25–2 → +34,4%; 0,8–1,25 → +11,6%; < 0,5 → +27,4% | Sau một đợt tăng gần đây forecast còn cao; phần nhu cầu nhỏ (≥ 2: 3%) |
| Giờ mở bán | Chỉ biết ở ngày **có đơn**. Mở đủ 24 h: bias −0,5% (12,3 triệu đơn vị). < 12 h: +58% (0,14 triệu); 0 h: +247% (9.253 đơn vị) | Mở một phần làm dư nhưng quy mô nhỏ. **Ngày không có đơn không có giờ mở bán**, nên không tách được "listing đóng" khỏi "không có nhu cầu" (giới hạn dữ liệu) |
| Giá (chỉ phân tích, Price giữ BẬT) | Giá kỳ đánh giá / giá cuối trước mốc > 1,05: bias +58% (0,44 triệu đơn vị); < 0,95: +22%; ổn định: +16,6% | Tăng giá đi kèm dư nhiều hơn; quy mô nhỏ |
| Làm tròn số nguyên | INT giảm bias +19,40% → +18,98% | Không phải nguyên nhân |
| Grain / gộp / trùng | Khóa duy nhất; actual = tổng của bản sao; forecast không NaN / âm | Không có lỗi |
| `sku_system_status` | Không có trong danh sách feature và không có trong `app/ml` (test) | Không phải feature |

**Giả thuyết chưa xác nhận:**
- lý do nhu cầu giảm từ tháng 7;
- ngày không đơn có phải do listing đóng / hết hàng không;
- đơn đặt trên listing miền khác (như `SOBD38271068`) có làm lệch chuỗi không.

### E. Kết quả thí nghiệm

**Đặt trước:** `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p19\plan_od.json`.
- Ghi lúc 13:15, sau phần chẩn đoán S0 và **trước** mọi kết quả ứng viên.
- Một sửa cấu trúc trước khi chạy: thêm danh sách `folds`, `configured_start`, `end` mà harness cần. Không đổi cấu hình, quy tắc hay ngưỡng nào.

**Các cấu hình** (tối đa 6 ngoài baseline; dùng đủ 6):

| Cấu hình | Loại | Cách làm | Giả thuyết |
|---|---|---|---|
| K1_cal_total | Hậu xử lý S0 | 1 hệ số / fold = ΣA / ΣF mọi ngày của các fold **trước** | Hiệu chỉnh mức tổng |
| K2_cal_normal3 | Hậu xử lý S0 | 1,03 × ΣA / ΣF ngày thường của các fold trước (nhắm bias ngày thường +3%), nhân cho mọi ngày | Hiệu chỉnh thẳng vào mục tiêu |
| K3_cal_segment | Hậu xử lý S0 | Hệ số theo mức khối lượng × nhóm nhu cầu, co về hệ số chung (5.000 đơn vị), nhóm < 500 đơn vị dùng hệ số chung | Dư khác nhau theo phân đoạn |
| K4_recency | Huấn luyện (bản sao) | Trọng số dòng huấn luyện 0,5^(tuổi / 30 ngày) | Mức nhu cầu giảm (D2) |
| K5_l1 | Huấn luyện (bản sao) | Objective `regression_l1` (dự báo trung vị) | Phần dư nằm ở ngày actual = 0 (D1) |
| K6_recency_cal_normal3 | Hậu xử lý K4 | Quy tắc K2 trên dự báo K4 | Sửa mức + hiệu chỉnh phần còn lại |

**Quy tắc chung:**
- Hệ số hiệu chỉnh chỉ học từ fold trước. Fold 22/05 không có fold trước nên không hiệu chỉnh được; vì vậy trạng thái xét trên 3 fold 21/06, 21/07, 20/08 (S234).
- Mọi cấu hình đánh giá trên cùng điểm, cùng nhãn ngày của S0.
- Target, actual và dữ liệu không đổi; không clip; không forecast tối thiểu; Price BẬT; customer OFF.

**Chạy** (`scratchpad\p19\od_harness.py`, bản sao `p18\e8`, cùng guard với đợt 3):
- **13:07** khởi động. Harness chờ vì production đang chạy huấn luyện MANUAL của người dùng, và RAM trống xuống 0,49–0,58 GB.
- **13:14** Claude dừng harness bằng file `STOP` để không tranh RAM với job production (chưa fold nào chạy; file đổi tên `STOP.used-131414`, log giữ ở `run_console_1_stopped.txt`).
- **13:17** chạy lại, sau khi job production kết thúc lúc 13:16.
- **13:19–13:36**: **10/10 lượt huấn luyện fold**, 0,33 giờ.
  - Không tạm dừng; RAM trống thấp nhất 1,17 GB.
  - Không có job production chạy lúc bắt đầu mỗi fold.

Kết quả gốc trong `scratchpad\p19\`:
- `run\*.npz`, `run\summary.jsonl`, `run\harness.log`;
- `od_eval.json` (đánh giá, chỉ đọc);
- `od_tables.md` (bảng dưới đây, sinh tự động từ `od_eval.json`).

"Over" = công thức B; ND = ngày thường (ND_OLD).

**3 fold sàng lọc 21/06, 21/07, 20/08 (tập xét trạng thái)** (INT = số nguyên công bố)

| Cấu hình | Over ngày thường | Bias ngày thường | Under ngày thường | WAPE ngày thường | Bias mọi ngày | Under mọi ngày | WAPE mọi ngày | Tỷ lệ mọi ngày | WAPE ngày spike | Under ngày spike | Chuỗi-fold tốt / kém / bằng S0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 54,5% | +25,6% | 28,9% | 0,8344 | +7,1% | 38,4% | 0,8386 | 1,071 | 0,8593 | 85,8% | — |
| K1_cal_total | 61,7% | +35,7% | 26,1% | 0,8777 | +15,7% | 35,8% | 0,8728 | 1,157 | 0,8482 | 84,6% | 2.261 / 14.404 / 21.648 |
| K2_cal_normal3 | 50,0% | +19,3% | 30,7% | 0,8065 | +1,7% | 40,0% | 0,8163 | 1,017 | 0,8658 | 86,4% | 13.085 / 2.483 / 22.745 |
| K3_cal_segment | 61,5% | +35,4% | 26,1% | 0,8764 | +15,5% | 35,9% | 0,8719 | 1,155 | 0,8491 | 84,7% | 7.820 / 9.763 / 20.730 |
| K4_recency | 53,4% | +24,4% | 29,1% | 0,8248 | +6,1% | 38,5% | 0,8302 | 1,061 | 0,8572 | 85,6% | 9.444 / 6.979 / 21.890 |
| K5_l1 | 28,1% | −14,3% | 42,4% | 0,7043 | −27,0% | 50,4% | 0,7385 | 0,730 | 0,9096 | 91,0% | 16.403 / 3.859 / 18.051 |
| K6_recency_cal_normal3 | 48,3% | +17,1% | 31,1% | 0,7943 | −0,1% | 40,3% | 0,8060 | 0,999 | 0,8647 | 86,4% | 12.827 / 4.724 / 20.762 |

**fold giữ lại 19/09 (không dùng để chọn)** (INT = số nguyên công bố)

| Cấu hình | Over ngày thường | Bias ngày thường | Under ngày thường | WAPE ngày thường | Bias mọi ngày | Under mọi ngày | WAPE mọi ngày | Tỷ lệ mọi ngày | WAPE ngày spike | Under ngày spike | Chuỗi-fold tốt / kém / bằng S0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 41,7% | +5,9% | 35,8% | 0,7754 | −10,1% | 44,3% | 0,7857 | 0,899 | 0,8327 | 83,1% | — |
| K1_cal_total | 40,4% | +4,0% | 36,5% | 0,7687 | −11,7% | 44,9% | 0,7807 | 0,883 | 0,8354 | 83,3% | 1.439 / 691 / 8.466 |
| K2_cal_normal3 | 32,3% | −9,1% | 41,3% | 0,7361 | −22,7% | 49,2% | 0,7575 | 0,773 | 0,8551 | 85,4% | 2.311 / 992 / 7.293 |
| K3_cal_segment | 40,1% | +3,6% | 36,5% | 0,7666 | −12,0% | 44,9% | 0,7788 | 0,880 | 0,8349 | 83,3% | 2.005 / 1.305 / 7.286 |
| K4_recency | 40,6% | +4,4% | 36,3% | 0,7688 | −11,4% | 44,8% | 0,7817 | 0,886 | 0,8407 | 83,9% | 1.483 / 1.522 / 7.591 |
| K5_l1 | 15,5% | −38,4% | 53,8% | 0,6927 | −48,2% | 60,9% | 0,7355 | 0,518 | 0,9312 | 93,1% | 2.226 / 1.242 / 7.128 |
| K6_recency_cal_normal3 | 31,5% | −10,1% | 41,6% | 0,7313 | −23,7% | 49,6% | 0,7546 | 0,763 | 0,8613 | 86,0% | 2.170 / 1.203 / 7.223 |

**4 fold sàng lọc (chỉ cấu hình không cần fold trước)** (INT = số nguyên công bố)

| Cấu hình | Over ngày thường | Bias ngày thường | Under ngày thường | WAPE ngày thường | Bias mọi ngày | Under mọi ngày | WAPE mọi ngày | Tỷ lệ mọi ngày | WAPE ngày spike | Under ngày spike | Chuỗi-fold tốt / kém / bằng S0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 48,6% | +19,0% | 29,6% | 0,7815 | +1,3% | 39,1% | 0,7945 | 1,013 | 0,8581 | 85,7% | — |
| K4_recency | 48,1% | +18,6% | 29,5% | 0,7762 | +1,0% | 39,0% | 0,7898 | 1,010 | 0,8567 | 85,5% | 12.257 / 9.825 / 28.770 |
| K5_l1 | 24,9% | −18,0% | 43,0% | 0,6789 | −30,3% | 51,1% | 0,7178 | 0,697 | 0,9092 | 90,9% | 21.536 / 5.530 / 23.786 |

**Trạng thái theo quy tắc đặt trước** (tập S234, INT, ngày thường, công thức B):

| Cấu hình | Trạng thái | Hệ số theo fold (21/06, 21/07, 20/08 / giữ lại) |
|---|---|---|
| S0 | BASELINE | — |
| K1_cal_total | FAIL (P not lower) | 1,125, 1,077, 1,021, 0,984 |
| K2_cal_normal3 | FAIL (P moved toward the target) | 0,985, 0,950, 0,905, 0,863 |
| K3_cal_segment | FAIL (P not lower) | 1,125, 1,077, 1,021, 0,984 |
| K4_recency | FAIL (P moved toward the target) | — |
| K5_l1 | FAIL (P moved toward the target) | — |
| K6_recency_cal_normal3 | FAIL (P moved toward the target) | 0,970, 0,941, 0,909, 0,865 |

**Mức tổng hợp khác** (INT; S234 / giữ lại): Over ngày thường theo tổng 30 ngày mỗi chuỗi và theo tổng toàn mạng mỗi ngày; WAPE / under tổng 7, 15, 30 ngày mọi ngày

| Cấu hình | Over ND tổng chuỗi | Over ND tổng mạng | Bias ND tổng mạng | Tổng 7 ngày (WAPE / under) | Tổng 15 ngày | Tổng 30 ngày |
|---|---|---|---|---|---|---|
| S0 | 38,8% / 28,7% | 26,4% / 8,5% | +25,6% / +5,9% | 0,519 / 25,9% ; 0,511 / 31,4% | 0,503 / 23,1% ; 0,510 / 33,4% | 0,504 / 21,7% ; 0,479 / 29,0% |
| K1_cal_total | 46,2% / 27,5% | 35,9% / 7,1% | +35,7% / +4,0% | 0,542 / 23,0% ; 0,510 / 32,2% | 0,527 / 20,2% ; 0,511 / 34,2% | 0,532 / 18,8% ; 0,477 / 29,7% |
| K2_cal_normal3 | 34,3% / 20,2% | 20,2% / 1,4% | +19,3% / −9,1% | 0,509 / 27,9% ; 0,516 / 37,9% | 0,487 / 24,9% ; 0,528 / 40,2% | 0,489 / 23,6% ; 0,482 / 35,5% |
| K3_cal_segment | 46,1% / 27,3% | 35,7% / 6,9% | +35,4% / +3,6% | 0,543 / 23,2% ; 0,509 / 32,2% | 0,529 / 20,3% ; 0,509 / 34,2% | 0,534 / 19,0% ; 0,478 / 29,9% |
| K4_recency | 37,8% / 27,2% | 24,9% / 7,9% | +24,4% / +4,4% | 0,515 / 26,6% ; 0,500 / 30,5% | 0,498 / 23,2% ; 0,498 / 32,7% | 0,499 / 21,9% ; 0,470 / 29,2% |
| K5_l1 | 16,1% / 7,2% | 1,7% / 0,0% | −14,3% / −38,4% | 0,526 / 41,0% ; 0,636 / 57,8% | 0,501 / 38,3% ; 0,617 / 55,5% | 0,511 / 39,1% ; 0,588 / 53,5% |
| K6_recency_cal_normal3 | 32,7% / 19,2% | 17,9% / 1,6% | +17,1% / −10,1% | 0,505 / 29,0% ; 0,502 / 36,7% | 0,482 / 25,4% ; 0,518 / 39,5% | 0,482 / 24,1% ; 0,477 / 35,7% |

**Phân phối bias ngày thường theo SKU × FC** (chuỗi-fold có nhu cầu ngày thường, INT, S234): tỷ lệ số chuỗi / tỷ lệ nhu cầu theo khoảng

| Cấu hình | < 0 | 0–1% | **1–5%** | > 5% | Trung vị |
|---|---|---|---|---|---|
| S0 | 53,2% / 48,8% | 0,7% / 1,0% | 1,5% / 4,0% | 44,6% / 46,2% | −9,3% |
| K1_cal_total | 49,7% / 38,0% | 0,6% / 1,7% | 1,3% / 4,8% | 48,3% / 55,5% | +0,0% |
| K2_cal_normal3 | 55,9% / 53,1% | 0,7% / 0,7% | 1,5% / 3,5% | 41,9% / 42,6% | −16,4% |
| K3_cal_segment | 50,5% / 37,7% | 0,7% / 1,0% | 1,3% / 5,1% | 47,5% / 56,1% | −2,1% |
| K4_recency | 54,2% / 47,4% | 0,7% / 2,5% | 1,4% / 3,5% | 43,7% / 46,5% | −11,8% |
| K5_l1 | 80,4% / 73,8% | 0,4% / 0,8% | 0,8% / 2,2% | 18,4% / 23,2% | −100,0% |
| K6_recency_cal_normal3 | 57,3% / 54,1% | 0,7% / 0,7% | 1,4% / 3,5% | 40,6% / 41,8% | −19,4% |

**Theo phân đoạn** (bias ngày thường, INT, S234)

| Cấu hình | HIGH_VOLUME | LOW_VOLUME | SMOOTH | ERRATIC | INTERMITTENT | LUMPY | T2 | T3 | T4 | T5 | T6 | T7 | CN | ngày 1–7 | ngày 8–15 | ngày 16–30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | +23,3% | +38,5% | +12,7% | +34,6% | −1,1% | +55,3% | +24,9% | +25,6% | +27,4% | +24,7% | +27,2% | +26,3% | +23,1% | +17,6% | +26,3% | +29,1% |
| K1_cal_total | +33,1% | +49,5% | +21,5% | +45,6% | +6,8% | +67,1% | +35,4% | +35,6% | +37,3% | +34,2% | +37,0% | +36,5% | +33,3% | +27,1% | +36,2% | +39,5% |
| K2_cal_normal3 | +17,2% | +31,0% | +7,0% | +28,2% | −8,3% | +46,8% | +19,1% | +19,3% | +20,8% | +18,1% | +20,5% | +20,0% | +17,2% | +11,8% | +19,8% | +22,7% |
| K3_cal_segment | +35,2% | +40,5% | +23,4% | +47,2% | +26,8% | +49,2% | +35,2% | +35,4% | +37,0% | +34,0% | +36,9% | +36,2% | +33,1% | +26,9% | +35,9% | +39,2% |
| K4_recency | +22,1% | +36,9% | +12,6% | +32,9% | −3,2% | +51,0% | +23,9% | +24,5% | +24,5% | +24,3% | +26,6% | +24,4% | +22,1% | +15,4% | +26,5% | +27,6% |
| K5_l1 | −9,5% | −29,8% | −8,8% | −8,9% | −53,1% | −50,1% | −19,0% | −16,2% | −15,8% | −16,6% | −16,1% | −8,6% | −4,0% | −16,7% | −10,5% | −15,0% |
| K6_recency_cal_normal3 | +15,1% | +28,5% | +6,1% | +25,4% | −10,9% | +41,6% | +17,0% | +17,3% | +17,2% | +16,8% | +19,0% | +17,2% | +15,2% | +8,6% | +19,1% | +20,2% |

**Nhận định:**
1. **Không cấu hình nào đạt 1–5%** theo chỉ số chính (over ngày thường, công thức B, SKU × FC × ngày, INT). Cả 6 là `FAIL`; K2, K4, K5, K6 có giảm P.
2. **K5 (trung vị)** giảm P nhiều nhất (54,5% → 28,1%; giữ lại 41,7% → 15,5%) bằng cách dự báo 0 ở phần lớn ngày / chuỗi:
   - tổng dự báo thiếu 27% (giữ lại 48%);
   - under mọi ngày 50,4% (so với 38,4%);
   - WAPE ngày spike 0,910 (so với 0,859);
   - trung vị bias theo chuỗi −100%.
   Không dùng được làm dự báo bổ sung hàng. Đây đúng là cơ chế ở bảng C4: giảm dư ngày không đơn thì thiếu ngày có đơn.
3. **K2 / K6 (hiệu chỉnh về +3%)**:
   - Trên S234 giảm bias ngày thường về +19,3% / +17,1%, đưa bias mọi ngày về khoảng 0, WAPE mọi ngày 0,816 / 0,806 (S0 0,839). Under mọi ngày tăng 1,6–1,9 điểm.
   - **Ở fold giữ lại hiệu chỉnh quá tay**: bias mọi ngày −22,7% / −23,7%, bias ngày thường −9,1% / −10,1%. Hệ số học trong giai đoạn nhu cầu giảm (0,86) vẫn áp khi nhu cầu đã ổn định.
   - Hiệu chỉnh walk-forward đuổi theo một độ lệch thay đổi theo thời gian; **rủi ro cao** nếu đưa vào ứng dụng.
4. **K1 / K3 (hiệu chỉnh về bias tổng 0)** **làm xấu hơn**: các fold đầu dự báo thiếu (fold 22/05 −11%) nên hệ số > 1 đúng lúc nhu cầu giảm.
5. **K4 (ưu tiên dữ liệu gần)** cải thiện nhỏ nhưng nhất quán:
   - over 54,5% → 53,4%; WAPE mọi ngày 0,839 → 0,830; 4 fold 0,795 → 0,790; giữ lại 0,786 → 0,782;
   - chuỗi-fold tốt hơn / kém hơn 9.444 / 6.979.
   Chưa đủ để xử lý việc giảm mức.
6. **Theo SKU × FC**: chỉ 0,8–1,5% chuỗi-fold có bias ngày thường trong 1–5%, tùy cấu hình. Mục tiêu theo từng chuỗi không thực tế ở hạt ngày.
7. **Mức tổng hợp**: theo tổng toàn mạng mỗi ngày, over ngày thường của K2 / K6 ở fold giữ lại là 1,4% / 1,6%. Nhưng đó là fold mà các cấu hình này thiếu tổng 23%, nên không phải "đạt mục tiêu".
8. **Ngày spike** (theo dõi): mọi cấu hình hạ mức đều làm ngày spike kém hơn (K5 nhiều nhất).

**Kết luận nghiên cứu (không triển khai, không promote):**
- Với định nghĩa hiện tại (over chỉ phần dư, từng SKU × FC × ngày), mục tiêu 1–5% **không đạt được** nếu không làm hỏng dự báo tổng. Lý do là phần lớn ngày của chuỗi không có đơn.
- Phần dư điều khiển được là **việc giảm mức nhu cầu** (D2): K4 chỉ xử lý được rất ít; hiệu chỉnh hậu xử lý không ổn định qua thời gian.
- Đề xuất để chủ hệ thống chọn **định nghĩa mục tiêu đo được** trước vòng sau. Ví dụ:
  - bias có dấu của ngày thường (hoặc mọi ngày) ở mức tổng 30 ngày mỗi chuỗi hay tổng toàn mạng;
  - một chỉ số mức phục vụ / chi phí tồn kho.
- Hướng nghiên cứu tiếp theo cần duyệt riêng:
  - feature hay chu kỳ huấn luyện bắt kịp đổi mức;
  - tìm nguyên nhân nhu cầu giảm (dữ liệu / nghiệp vụ);
  - dự báo hai phần "có đơn hay không" × "bao nhiêu" cho chuỗi gián đoạn.
- Không cấu hình nào được chấp nhận; `overforecast.py` chỉ dùng để đánh giá.

### F. Kiểm thử và artifact

**Kiểm thử** (unit / integration với fake, DB tạm cô lập; không test nào chạm DB thật):

| Lần chạy | Lệnh | Kết quả |
|---|---|---|
| Backend đầy đủ, lần 1 (13:37:32–13:44:23) | `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -rs` | exit 1: **627 passed, 1 failed, 9 skipped**. Test lỗi: `test_the_preview_is_checked_again_under_the_write_lock` (mã đợt 2, không phải mã đợt này). Nguyên nhân: J1, bản xem trước và J2 chạy trong cùng một giây, nên `synced_at` (độ phân giải 1 giây) của J1 = J2 và lần nạp J2 không bị nhận ra. Test đã đạt ở lần chạy 12:15 |
| Sửa | `app/sync.py`: thêm `load_id` duy nhất cho mỗi lần nạp D-1; bản xem trước lưu và lần kiểm tra lại so sánh cả hai. Test mới cố định thời gian: chứng minh hai lần nạp cùng `synced_at` và lần nạp sau vẫn bị chặn | Không nới lỏng hay xóa test nào |
| Test liên quan | `test_v129_backfill_history_patterns.py`, `test_v129c_window_spike_customer.py`, `test_v129d_overforecast.py` | 55 passed. Hai test thời gian chạy lại 3 lần: 2 passed mỗi lần |
| **Backend đầy đủ, lần cuối (13:47:31–13:53:33)** | như trên | **exit 0: 629 passed, 0 failed, 9 skipped, 0 blocked**. 9 skipped đều là test BigQuery thật opt-in (`DF_REAL_BQ=1`). Log: `scratchpad\p19\pytest_full2.txt` |

Ghi chú:
- Test mới: `test_v129d_overforecast.py` (10 test):
  - công thức, ΣA = 0, NaN;
  - làm tròn = `app/qty.py`, forecast 0 hợp lệ;
  - nhãn ngày thường không đọc ngày sau / ngoài cửa sổ;
  - hệ số walk-forward chỉ dùng kỳ trước, nhóm nhỏ dùng hệ số chung;
  - ứng dụng không dùng module;
  - Price BẬT / customer TẮT / hạt SKU × FC / không feature trạng thái.
- Thêm 1 test trong `test_v129_backfill_history_patterns.py`.
- Frontend: không sửa trong đợt này, nên không chạy lại. Lần gần nhất 10:52: vitest 149/149, typecheck và build đạt.
- Lint: **chưa cấu hình**.
- Đuôi dòng 77 file so với HEAD: 0 lỗi (`MO-HINH-VA-CHI-SO.md` giữ CRLF). Không có file PS1 thay đổi.
- Quét bí mật file mới và phần sửa `sync.py`: 0.

**File trong repo thay đổi ở đợt này** (chưa commit):

| File | Thay đổi |
|---|---|
| `backend/app/ml/overforecast.py` | Mới |
| `backend/app/sync.py` | Sửa `load_id` |
| `backend/tests/test_v129d_overforecast.py` | Mới |
| `backend/tests/test_v129_backfill_history_patterns.py` | +1 test |
| `CHANGELOG.md` | Mục "Fourth batch" |
| `docs/04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md` | Mục chỉ số dư / thiếu |
| `docs/02_kien_truc_du_lieu/BIGQUERY.md` | §11c, phát hiện MULTI_ITEM |
| `docs/03_van_hanh/CHECKPOINT.md` | Mục đợt 4 |

Working tree: 77 file so với HEAD `0da73b6`.

**Ngoài repo:**
- `reports/demandforecast_multi_item_review_20261020.xlsx`;
- báo cáo này.

**Artifact** (`C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p19\`):

| Nhóm | File |
|---|---|
| Truy vấn | `bq_multi_item.py` / `.json`, `bq_order.py` / `.json` |
| Workbook | `multi_item_xlsx.py`, `verify_multi_item.py` / `.json` |
| Chẩn đoán | `od_diag.py`, `od_diag_screen.json` / `.txt`, `od_diag_holdout.json` / `.txt` |
| Thí nghiệm | `plan_od.json`, `od_harness.py`, `run\` (10 `.npz`, `summary.jsonl`, `harness.log`, `STOP.used-131414`), `run_console.txt`, `run_console_1_stopped.txt` |
| Đánh giá | `od_eval.py`, `od_eval.json`, `od_tables.py` / `.md` |
| Test | `pytest_full.txt`, `pytest_full2.txt` |
| Checkpoint | `src_checkpoint.py` |

**Checkpoint:**
- Trước khi sửa: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129d-before.zip`, 704.269 byte, 12:45:45, SHA-256 `F9B72DDD6FBF9ABEF0D69EB2AB53967833CDFB1AEABDEF80AF279E103ADEDA5E` (75 file, đã kiểm tra).
- Sau khi xong: mục "Checkpoint cuối" ở cuối báo cáo.

**Hạn chế:**
- S0 dùng lại dự báo đã lưu, sinh bằng mã trước lần sửa `features.py` lúc 10:36 (chỉ bỏ cấp bộ nhớ cho mảng khách hàng khi không có dữ liệu). K4 / K5 chạy bằng mã cuối.
- Fold 22/05 không hiệu chỉnh được (không có fold trước). Chỉ có 1 fold giữ lại.
- Dữ liệu là bản sao ngày 19/10 (tới 18/10). Kết quả hiệu chỉnh phụ thuộc giai đoạn nhu cầu giảm.
- Nhãn ngày thường cần actual. Giờ mở bán không có ở ngày không đơn.
- Miền bán của item chỉ suy ra được (không có cột).

### G. Cam kết an toàn

| Cam kết | Trạng thái | Bằng chứng |
|---|---|---|
| Không huấn luyện / backfill / chạy job production | Tuân thủ | Mọi job sau 12:16 có trigger SCHEDULE hoặc MANUAL từ giao diện của người dùng (bảng đầu báo cáo). Thí nghiệm chỉ trên bản sao `p18\e8`; harness tự chờ khi production có job và đã dừng hẳn khi RAM thấp |
| Không deploy / đóng gói / migration production | Tuân thủ | health / `current.txt` = 1.2.8; không chạy script release / deploy |
| Không commit / push | Tuân thủ | HEAD vẫn `0da73b6` |
| Không đổi lịch D-0 / D-1 / huấn luyện | Tuân thủ | Không gọi API ghi nào trên app production |
| Không đổi model đang dùng, không promote | Tuân thủ | Ứng viên production `TRN-20261020054540-D7EEF6` (người dùng tạo) vẫn `PROMOTION_REVIEW_REQUIRED` |
| Không tắt Price | Tuân thủ | Thí nghiệm giữ `feature_price = true`; mặc định trong mã vẫn BẬT (test) |
| Không bật `customer_id` | Tuân thủ | Mặc định `feature_customer = false`, `customer_id_column = ""` (test) |
| Không sửa / xóa dòng MULTI_ITEM, không tạo dữ liệu giả | Tuân thủ | Workbook chỉ từ dòng thật, đã đối chiếu; không ghi gì vào nguồn hay DB |
| Không xóa dữ liệu lịch sử, log, checkpoint, scratchpad | Tuân thủ | Checkpoint cũ giữ nguyên; file `STOP` đổi tên, không xóa; log lần chạy dừng giữ lại |
| BigQuery chỉ đọc | Tuân thủ | 2 truy vấn SELECT, dry run trước, giới hạn 3 GiB; tổng 2,32 GB |

### Checkpoint cuối

ZIP `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129d-worktree.zip`, tạo sau khi test và báo cáo hoàn tất. Gồm:
- 77 file working tree + patch so với HEAD;
- báo cáo này;
- script, kế hoạch, kết quả và log của `scratchpad\p19`.

Không gồm:
- workbook Excel (đã có SHA-256 ở mục B);
- bản sao DB;
- credentials.

SHA-256 của ZIP ghi ở file `.sha256` cạnh ZIP và ở `docs/03_van_hanh/CHECKPOINT.md`; bản báo cáo trong ZIP không có dòng hash.

**Kết quả** (thêm sau khi tạo; bản trong ZIP không có phần này):

| | Giá trị |
|---|---|
| Tạo lúc | 20/10/2026 13:55:56 (+07:00) |
| Kích thước | 31.797.325 byte |
| SHA-256 | `3E2DFAB783724DEC9EB75143E08AA78D7587ACCD94DA46BC74F58998246BFAF7` |
| Số mục | 122: `source/` 78 (77 file + patch), `reports/` 1, `scratchpad-p19/` 42 (gồm 10 `.npz`), `MANIFEST.json` |

Đã kiểm tra:
- CRC mọi mục đúng; danh sách khớp manifest; hash từng mục khớp.
- Hash ZIP tính lại bằng PowerShell khớp file `.sha256`.
- Không có tên file dạng credentials / DB / `storage.json` / `.xlsx`.
- Checkpoint cũ giữ nguyên.
- Phân tích K4 / K5 cần thêm dự báo S0 của `p18`; chúng đã có trong `checkpoint-20261020-v129c-worktree.zip`.

## 2. Demand Forecasting – 931 khóa giờ mở bán = 0 có đơn và các hạng mục audit độc lập (đợt 6, 20/10/2026)

Nguồn: `reports\demandforecast_zero_hours_followup_audit_20261020.md` (worktree MAIN).

| | |
|---|---|
| Thời gian | 20/10/2026, 17:38 – 19:35 (giờ Việt Nam; máy ở Modern Standby 17:50–19:14) |
| Yêu cầu | "EXPORT 931 ZERO-OPEN-HOURS KEYS + CONTINUE OTHER AUDIT WORK" (nhánh A + B1–B6) |
| Trạng thái chung | **`BLOCKED_BUSINESS_RULE`** (6 khóa `MULTI_ITEM`), kèm **`BLOCKED_USER_REVIEW`** (931 khóa, chờ bạn xem Excel). Không phải PASS. |
| Production | Không bị thay đổi. Chỉ đọc qua GET và đọc hash `storage.json`. |
| Người đọc | Chủ hệ thống và người duyệt nghiệp vụ |

### 1. Tóm tắt

1. **File Excel 931 khóa:** `D:\Buymed\Lightgbm AI\reports\demandforecast_zero_open_hours_with_orders_20261020.xlsx`
   - SHA-256 `A9640616318B5BA75C941750AA9A1CCBB1CCA308A6247A65F0DEE95525301025`.
   - Có **931 khóa duy nhất / 3.017 dòng nguồn / 25.542 đơn vị**, khớp tuyệt đối với audit đợt 5.
   - Đã kiểm tra độc lập: mở lại bằng openpyxl và pandas, đối chiếu từng khóa với dữ liệu BigQuery. Mọi kiểm tra đạt.
2. **Ngày 28/08 – tiền đề của yêu cầu chưa đúng.**
   - Dòng 71.834 đơn vị (BD, `MEDX.9DCBBCV8`, đơn `SOBD38282435`) có `total_open_hours` = **19,25**, không phải 0. Khóa này **không** thuộc 931 khóa.
   - Câu trả lời trước của tôi đặt "931 khóa giờ = 0" và "dòng 71.834" chung một gạch đầu dòng, dễ gây hiểu nhầm. Tôi đính chính ở đây.
   - Đây là một đơn 1 dòng, đã giao đủ 71.834, giá khớp các đơn khác của SKU. Không phải bản trùng.
   - Cùng chuỗi SKU × BD này có giờ = 0 trên các ngày có đơn từ 04/09 đến 14/09 và 07/10. Các ngày đó nằm trong 931 khóa.
3. **Sáu khóa `MULTI_ITEM`:**
   - Đã đối chiếu đủ 6 khóa và tính giá trị theo 6 phương án gộp. Không chọn phương án nào.
   - 4 khóa chênh ít (dưới 5 giờ). 2 khóa ngày 02/03 tại BD chênh lớn (5,0 / 24 và 1,7 / 24).
   - Nếu train 1.2.9 hôm nay, các khóa này chỉ chạm tới một giá trị `open_hours_mean_7` ở một mốc (01/09) và vài mốc backtest. Dù vậy, cả 6 khóa vẫn **chặn toàn bộ** training BIGQUERY của 1.2.9.
   - Vẫn chờ bạn quyết định quy tắc gộp.
4. **Dữ liệu khả năng bán cho ngày không có đơn:**
   - **Không có** trong ứng dụng hay trong bảng nguồn hiện tại. Bảng nguồn chỉ có dòng đơn; `open_date` luôn bằng ngày đơn; `total_open_days` = giờ ÷ 24.
   - **Có** bảng ứng viên trong cùng dataset BigQuery: `fact_product_sku_status`, từ 01/04/2026, theo item × FC × ngày. 92–96% số dòng của bảng là ngày không có đơn.
   - Bảng này khớp chiều với giờ mở bán: ngày giờ = 0 thì 619/621 dòng là `OUT_OF_STOCK`; ngày giờ = 24 chỉ có 19 dòng `OUT_OF_STOCK`.
   - **Ý nghĩa chưa được xác nhận**, chưa dùng cho model.
5. **Nhu cầu giảm từ tháng 7:**
   - Số đơn/ngày giảm ít: BD −8%, HN −26%.
   - Kích thước đơn giảm mạnh: số dòng/đơn khoảng −35% đến −39%, số lượng/đơn khoảng −33% đến −39%.
   - Dấu hiệu khả năng bán giảm: tỷ lệ dòng có giờ < 24 tăng gấp 2,6–3,8 lần; tỷ lệ `OUT_OF_STOCK` của bảng tham chiếu từ 19–23% lên 28–31%.
   - Đơn lớn không phải nguyên nhân. Không có dấu hiệu lỗi pipeline.
   - Nguồn chỉ có một seller (`MEDX`, `INTERNAL`). Nếu nhu cầu chuyển sang kênh khác thì bảng này không thấy được.
6. **Model production đang dùng** (đã xác minh bằng GET và file model):
   - `TRN-20261020054540-D7EEF6` / `MV-20261020-131556-EEF6`, promote lúc 15:24:14 hôm nay.
   - 31 feature, không có giờ mở bán, không có customer; Price ON.
   - Dữ liệu nó đã học có fingerprint `e4a56ce6592d4834`, đúng bằng fingerprint bản sao DB 15:25.
   - Audit không ghi người thực hiện. Phiên của tôi chỉ gọi GET.
7. **Phát hành 1.2.9 + backfill (chỉ lập kế hoạch):**
   - Preview trên bản sao, vẫn đúng với production lúc 17:41: mới 344, sửa 213, xóa 772 SKU × ngày; tổng số lượng −12.109 (−0,03%); 272 ngày có thay đổi.
   - Blocker:
     - 6 khóa `MULTI_ITEM`: sau khi phát hành, mọi lần training BIGQUERY sẽ dừng ở `OPEN_HOURS_INVALID`;
     - chưa có quyết định commit / đóng gói / phát hành;
     - rollback cần khôi phục backup (schema 8).
   - 931 khóa **không** chặn về kỹ thuật, nhưng ảnh hưởng ý nghĩa của feature giờ mở bán.
8. **Làm được ngay, không cần chờ bạn:** xem mục 12.
9. **Phải chờ bạn:**
   - kết quả xem Excel 931 khóa;
   - quy tắc `MULTI_ITEM`;
   - ý nghĩa bảng `fact_product_sku_status`;
   - xác nhận đơn 71.834;
   - phạm vi seller của nguồn;
   - quyết định phát hành.

### 2. Trạng thái từng hạng mục

| Hạng mục | Trạng thái | Phụ thuộc kết quả xem 931 khóa? |
|---|---|---|
| A. Excel 931 khóa (tạo, đối chiếu, kiểm tra) | `PASS` | – |
| A. Ý nghĩa nghiệp vụ của 931 khóa | `BLOCKED_USER_REVIEW` | – (chính là việc bạn xem) |
| B1. Truy vết dòng 71.834 ngày 28/08 | `PASS` (dữ liệu) | Độc lập. Chỉ các ngày giờ = 0 của cùng chuỗi (từ 04/09) chờ xem Excel. |
| B1. Đơn 71.834 là nhu cầu thật hay đơn đặc biệt | `NOT_VERIFIED` | Độc lập. Cần hệ thống đơn hàng hoặc bạn xác nhận. |
| B2. Sáu khóa `MULTI_ITEM` | `BLOCKED_BUSINESS_RULE` | Độc lập |
| B3. Nguyên nhân nhu cầu giảm | `NOT_VERIFIED` (đã có bằng chứng từng giả thuyết, chưa có kết luận) | Độc lập |
| B3. Nguồn khả năng bán cho ngày không có đơn | Tìm thấy bảng ứng viên; dùng được hay không: `BLOCKED_USER_REVIEW` | Độc lập |
| B4. Xác minh production read-only | `PASS` | Độc lập |
| B5. Kế hoạch phát hành 1.2.9 + backfill preview | Kế hoạch: xong. Phát hành: `BLOCKED_BUSINESS_RULE` | 931 khóa không chặn kỹ thuật |
| B6. Thí nghiệm offline tiếp theo | Kế hoạch: xong, chưa chạy. D1/D2: `BLOCKED_USER_REVIEW`; D3: chờ Excel; D4: độc lập | Một phần |
| Test backend | `PASS` (634 passed / 10 skipped / 0 failed) | – |

### 3. Nhánh A – Excel 931 khóa

**Định nghĩa** (lấy nguyên từ audit đợt 5; truy vấn import đúng đoạn SQL của `p20/bq_oh.py`, không chép lại):
- Khóa = `created_date` × `fc_code` × `sku_code`.
- Chỉ tính dòng hợp lệ D-1: có SKU, có FC, `demand_quantity` có giá trị và ≥ 0.
- Lấy mọi khóa có ít nhất một dòng `total_open_hours = 0`.
- Kết quả: 931 khóa, tất cả có trạng thái `OK` với giá trị 0 (mọi dòng của khóa đều = 0) và `order_qty > 0`.
- Không có khóa `MULTI_ITEM` / `CONFLICT` nào chứa dòng giờ 0.
- Hậu tố `item_code` không được đọc.

**Snapshot:**
- Bảng `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`, `refresh_time` 15:05:19 20/10, bảng tạo lúc 08:05:30 UTC.
- Kiểm tra metadata trước, trong và sau mọi truy vấn (17:4x, 19:2x): bảng không đổi, 8.961.566 dòng. Đây đúng là snapshot của audit đợt 5 và bản sao e9.
- Không trộn với file đợt 3 `reports/zero_open_hours_orders_20261020.xlsx` (bản làm mới 07:10, 2.592 dòng). File đó được giữ nguyên.

| Chỉ tiêu | Kết quả | Audit đợt 5 | Đối chiếu |
|---|---|---|---|
| Khóa / khóa duy nhất | 931 / 931 | 931 | KHỚP, 0 trùng |
| Tổng `order_qty` | 25.542 | 25.542 | KHỚP |
| Dòng nguồn | 3.017 (fingerprint đều khác nhau) | 3.017 | KHỚP |
| Chuỗi SKU × FC / SKU / FC | 133 / 104 / 2 (BD 577 khóa, HN 354) | 133 | KHỚP |
| Ngày đầu / cuối | 01/01/2026 / 18/10/2026 | – | – |
| Đơn duy nhất | 2.847 (cộng theo khóa: 2.997; một đơn có thể thuộc nhiều khóa) | – | – |
| Dataset e9 (D-1 1.2.9 đã lưu) | 931 khóa MATCH (giờ 0, `OK`, cùng số lượng và số đơn) | – | KHỚP |
| DB production (bản sao 15:25) | 930 MATCH, 1 lệch | – | Xem dưới |

- **Khóa lệch duy nhất:** 06/10 BD `MEDX.AMP-SOS-001`. Production ghi 106 đơn vị / 81 đơn; nguồn ghi 105 / 80. Nguyên nhân là độ trễ lịch sử đã biết: D-1 chỉ đọc lại 3 ngày. Backfill sẽ đồng bộ khóa này.
- Đặc điểm khác của các dòng: seller `INTERNAL` (`MEDX`); `open_date` = `created_date` ở mọi dòng; `total_open_days` = 0 ở mọi dòng.
- Trạng thái đơn: `COMPLETED` 2.936, `DELIVERED` 73, `DELIVERING` 7, `CONFIRMED` 1.
- `sku_system_status` là trạng thái **hiện tại**, chỉ để tham khảo: `OUT_OF_STOCK` 1.832, `NORMAL` 998, `LIMIT` 187 dòng.

**Các sheet:**
- `Summary`: định nghĩa, snapshot, phiên bản dataset, SHA của code xuất, đối chiếu, bảng theo tháng × FC.
- `Keys_For_Review`: 931 dòng. Có `weekday` (Thứ Hai = 1 … Chủ nhật = 7, tính từ ngày), danh sách **đầy đủ** `so_code` (dài nhất 1.118 ký tự). `review_status` = `PENDING_USER_REVIEW`; hai cột `user_decision` / `user_notes` để trống, tô vàng.
- `Source_Evidence`: 3.017 dòng nguồn với đủ 17 cột cùng fingerprint dòng.
- `Model_Feature_Evidence`: xem bên dưới.
- `Availability_Reference`: 933 dòng item của bảng tham chiếu chưa xác nhận.
- `Availability_vs_Hours`: 17 nhóm.

**Định dạng:** mã SKU, FC, đơn, `product_id` lưu dạng text; ngày là ngày thật; filter và freeze header; không gộp ô; NULL giữ là trống, không đổi thành 0.

**Model_Feature_Evidence** (một dòng mỗi khóa, có bằng chứng ở từng bước):

| Bước | Kết quả |
|---|---|
| Model production đang dùng (đọc file `MV-20261020-131556-EEF6.txt`) | 31 feature, **không** có giờ mở bán → `NOT_USED_BY_ACTIVE_MODEL`. Số lượng của khóa thì có vào model, làm mục tiêu và lag. |
| Dữ liệu model production đã học | Fingerprint bản sao DB 15:25 = `e4a56ce6592d4834` = `data_fingerprint` của model |
| Dataset e9 (1.2.9 D-1 lưu `open_hours`) | 931/931 MATCH |
| Panel 1.2.9 (`build_panel`) | 931/931 giá trị 0 (MATCH) |
| Mảng giờ lưu lúc chạy B0 (npz đợt 5) | 830 MATCH; 101 nằm ngoài cửa sổ đã lưu (`NOT_IN_SAVED_WINDOW`); 0 MISMATCH |
| Feature của 5 model B0 offline (`origin_features`, đúng code 1.2.9) | 795 khóa đã đi vào `open_hours_last` / `open_hours_mean_7` (1.861 lần, ghi rõ fold, mốc và giá trị). Kiểm tra: `open_hours_last` luôn bằng giờ của ngày trước mốc. |
| Model 1.2.9 production | `NOT_AVAILABLE`: chưa có. Training BIGQUERY 1.2.9 bị chặn bởi 6 khóa `MULTI_ITEM`. |

- 136 khóa không vào feature B0 vì nằm ngoài cửa sổ 7 ngày trước mọi mốc: 65 khóa tháng 1, 36 khóa tháng 2, 4 khóa tháng 9, 31 khóa tháng 10.

**Không lấy được:**
- khách hàng (nguồn không có cột);
- trạng thái SKU theo từng ngày trong bảng nguồn;
- giờ mở bán theo khung giờ (nguồn chỉ có tổng giờ của ngày).

**Tham chiếu chưa xác nhận** (`fact_product_sku_status`, ghép đúng `item_code` × `fc_code` × ngày):
- Từ 01/04: 619 trong 656 item-ngày là `OUT_OF_STOCK`, 2 là `LIMIT`, 35 không có dòng.
- Trước 01/04: 277 item-ngày, bảng chưa có dữ liệu.
- Tôi **không** kết luận khóa nào sai.

### 4. B1 – Ngày 28/08/2026

| Sự kiện | Giá trị |
|---|---|
| Khóa 28/08 × BD × `MEDX.9DCBBCV8` | 4 dòng, 4 đơn, **71.947** đơn vị, 1 item; `total_open_hours` = **19,25** ở cả 4 dòng (`OK`) |
| Dòng lớn | đơn `SOBD38282435`, `DELIVERED`, 71.834 đơn vị, xuất kho 71.834, giá 19.000; đơn chỉ có 1 dòng |
| 3 dòng còn lại | 108 + 3 + 2 đơn vị, giá 19.000 / 20.100, thuộc 3 đơn khác |
| Lưu ở production / e9 | 71.947 / 4 đơn ở cả hai, đúng như nguồn |
| BD ngày 28/08 | 130.950 đơn vị, 2.439 đơn; bỏ SKU này thì còn **59.003** (trung bình các ngày 21/08–04/09 khác: 56.702) |
| HN ngày 28/08 | 30.720 đơn vị, không có dòng giờ 0 |
| SKU này theo tháng tại BD | tháng 8: 87.557 đơn vị (08/08 1.920; 20/08 4.800; 26/08 6.400; 28/08 71.834); các tháng khác ≤ 6.620 |
| Ngày giờ = 0 của cùng SKU | 14 khóa / 288 đơn vị: 04/09–14/09 và 07/10 tại BD; 28/06, 30/06 tại HN. **Thuộc 931 khóa** |
| Dòng ≥ 1.000 đơn vị (toàn bảng) | 438 dòng / 888.585 đơn vị. Giờ: 387 dòng = 24, 49 dòng 0–24, 2 dòng = 0. 376/438 xuất kho = đặt. |

**Ảnh hưởng tới model:**
- B0 offline, fold 20/08: chuỗi này chiếm 3,3% actual và 3,0% sai số tuyệt đối. WAPE của fold là 1,1030 có chuỗi, 1,1064 nếu bỏ chuỗi.
- B0 offline, fold 19/09: dự báo 3.062 so với thực tế 1, chiếm 0,16% sai số. WAPE 0,7811 so với 0,7798.
- Production (FCR-20261020082402-A42C91): BD 0,16–0,54/ngày (số nguyên 0–1, LIGHTGBM); HN 0 (`FALLBACK_INTERMITTENT`).

| Giả thuyết | Bằng chứng ủng hộ | Bằng chứng phản bác | Kết luận |
|---|---|---|---|
| Trùng dữ liệu | – | Đơn 1 dòng; fingerprint duy nhất; toàn bảng 0 dòng trùng hoàn toàn (đợt 5); production và e9 đều 71.947 | Bác bỏ |
| Lỗi giờ mở bán = 0 | – | Giờ 19,25 trên cả 4 dòng | Bác bỏ (tiền đề sai) |
| Gõ nhầm số lượng | – | Xuất kho = 71.834; giá bình thường | `NOT_VERIFIED` (cần hệ thống đơn hàng) |
| Đơn số lượng lớn có thật (mua sỉ / nội bộ) | `DELIVERED` đủ; SKU có nhiều đơn lớn trong tháng 8 | Không có thông tin khách hàng / kênh | Cần bạn xác nhận; không sửa hay loại dòng |

### 5. B2 – Sáu khóa `MULTI_ITEM` (156 đơn vị, chờ quy tắc)

Giá trị mỗi phương án được tính cho minh bạch, **không chọn**. Mỗi item có đúng một giá trị giờ trong ngày.

| Ngày / FC / SKU | Item: dòng / số lượng / giờ | R1 item số lượng lớn nhất | R2 MAX | R3 MIN | R4 TB theo số lượng | Giờ đã lưu của chuỗi ±7 ngày |
|---|---|---|---|---|---|---|
| 09/02 HN DMTS-HOA-BAO-002 (8) | .1: 1 / 2 / 23,92; .2: 3 / 6 / 24 | 24 | 24 | 23,92 | 23,98 | 24 gần như mọi ngày |
| 10/02 HN 2LJ61PGE (11) | .1: 1 / 1 / 21,16; .3: 1 / 10 / 24 | 24 | 24 | 21,16 | 23,74 | 24; 06–07/02: 9,67 / 8,44 |
| 02/03 BD DMTS-STA-LOS-002 (88) | .1: 17 / 78 / 5,0; .2: 1 / 10 / 24 | 5,0 | 24 | 5,0 | 7,16 | 01/03 11,11; 05/03 1,1; 06/03 14,08 |
| 02/03 BD SOP-NEO-001 (3) | .1: 2 / 2 / 1,7; .2: 1 / 1 / 24 | 1,7 | 24 | 1,7 | 9,13 | 0,49–12,44 (thấp) |
| 26/08 BD COU-STR-001 (42) | .1: 7 / 40 / 23,72; .2: 1 / 2 / 24 | 23,72 | 24 | 23,72 | 23,73 | 10,76–24 |
| 26/08 BD D6TABCV8 (4) | .1: 3 / 3 / 22,85; .2: 1 / 1 / 18,22 | 22,85 | 22,85 | 18,22 | 21,69 | 12,33–24 |

- R0 (để trống như hiện nay) và R5 (trung bình theo số dòng) có trong `p21/b2_multi.json`.
- Cùng ngày, có item của các SKU này xuất hiện ở FC khác. Đó chỉ là dữ kiện, tôi không suy ra miền.

**Tác động** (DIRECT 12 mốc × 7 ngày; backtest 12 fold × 30 ngày, đúng cấu hình đang lưu):

| Phương án | Tác động |
|---|---|
| **Giữ trạng thái hiện tại** | Mọi lần training BIGQUERY của 1.2.9 dừng ở `OPEN_HOURS_INVALID`, với cả hai quy tắc ngày bắt đầu (cửa sổ từ 01/01 chứa cả 6 khóa). Model 1.2.8 tiếp tục được dùng. |
| **R0 cho phép giờ trống ở đúng 6 khóa** | Cần sửa gate. Feature của các ngày đó là NaN; `mean_7` tính trên các ngày còn lại. |
| **R1–R5** | Cần sửa code D-1/gộp. Các phương án chỉ khác nhau rõ ở 2 khóa 02/03 BD: 5,0 / 1,7 (R1, R3) so với 24 (R2) so với 7–9 (R4/R5). |
| **Nguồn sửa** | Bên dữ liệu cung cấp một giá trị SKU × FC × ngày. Không cần đổi code. |

Phạm vi feature bị chạm nếu train hôm nay: hai khóa 26/08 chỉ vào `open_hours_mean_7` của mốc 01/09 và một mốc backtest (fold 12); bốn khóa tháng 2–3 chỉ vào mốc của backtest fold 6–8. Phạm vi ảnh hưởng tới số liệu là rất nhỏ; tác động chính là việc chặn training.

**Bạn cần chọn:** một trong R0 … R5, hoặc yêu cầu nguồn sửa, hoặc một quy tắc khác. Khi có quyết định, tôi sẽ thêm code, test và kiểm tra trên bản sao.

### 6. B3 – Nhu cầu giảm từ tháng 7

| Chỉ tiêu | BD tháng 4–6 | BD 01/09–19/10 | HN tháng 4–6 | HN 01/09–19/10 |
|---|---|---|---|---|
| Số lượng / ngày | 108.660 | 60.242 (−45%) | 46.634 | 23.072 (−51%) |
| Đơn / ngày | 2.591 | 2.374 (−8%) | 810 | 602 (−26%) |
| Dòng / đơn | 9,62 | 5,89 (−39%) | 9,80 | 6,41 (−35%) |
| Số lượng / đơn | 41,9 | 25,4 (−39%) | 57,5 | 38,3 (−33%) |
| SKU có đơn / tháng (tháng 9) | 6.577 (TB) | 5.685 | 5.983 (TB) | 5.684 |
| Tỷ lệ dòng có giờ < 24 | 2,2% | 5,8% | 1,9% | 7,3% |
| Tỷ lệ số lượng từ dòng ≥ 1.000 | 1,35% | 3,87% | 0,96% | 3,35% |

Bảng tham chiếu `fact_product_sku_status` (mọi item × FC × ngày, ý nghĩa chưa xác nhận):

| Tháng | 4 | 5 | 6 | 7 | 8 | 9 | 10 (19 ngày) |
|---|---|---|---|---|---|---|---|
| `OUT_OF_STOCK` | 23,1% | 22,1% | 19,1% | 19,6% | 23,2% | 30,5% | 28,2% |
| `NORMAL` | 48,1% | 48,8% | 50,5% | 49,6% | 39,2% | 35,4% | 40,2% |
| `is_active` | 87,0% | 86,9% | 87,1% | 87,2% | 87,3% | 83,9% | 79,0% |

| Giả thuyết | Ủng hộ | Phản bác / giới hạn | Trạng thái |
|---|---|---|---|
| Ít khách / ít đơn hơn | HN −26% đơn/ngày | BD chỉ −8% đơn, nhưng số lượng −45% | Một phần |
| Giỏ hàng nhỏ hơn (ít SKU/đơn, ít số lượng/đơn) | −35% đến −39% ở cả hai FC; trung vị số lượng/đơn 27 → 14,5 (BD) | Không biết vì sao (giá, khách, sản phẩm) | Ủng hộ mạnh về số học |
| Khả năng bán giảm (hết hàng, giờ mở bán) | Giờ < 24 tăng 2,6–3,8 lần; `OUT_OF_STOCK` 19–23% → 28–31%; `is_active` 87% → 79%; chuỗi giảm > 50%: giờ trên ngày có đơn 23,6 → 20,0 (đợt 5) | Giờ chỉ quan sát được ở ngày có đơn (thiên lệch chọn mẫu); ý nghĩa bảng tham chiếu chưa xác nhận | Ủng hộ, chưa xác nhận |
| Đơn lớn làm cao mức nền tháng 4–6 | – | Tỷ lệ dòng ≥ 1.000 lại **tăng** ở tháng 9–10 | Bác bỏ là nguyên nhân chính |
| Lỗi dữ liệu / pipeline | – | Số đơn ổn định; không có đơn hủy; lịch sử bị viết lại chỉ −0,03% | Không có bằng chứng |
| Nhu cầu chuyển sang seller / kênh khác | Nguồn chỉ có seller `MEDX` / `INTERNAL` mọi tháng | Không có dữ liệu kênh khác | `NOT_VERIFIED`, cần bạn |

**Nguồn khả năng bán cho ngày không có đơn:**

| Nguồn | Có cho ngày không có đơn? | Ghi chú |
|---|---|---|
| Ứng dụng, bảng `demand_daily` | Không | Chỉ có dòng ngày có đơn |
| Bảng nguồn D-1 | Không | Mỗi dòng là một dòng đơn (số lượng tối thiểu 1); `open_date` = `created_date` ở 8.961.566/8.961.566 dòng; `total_open_days` = round(giờ ÷ 24, 2) ở mọi dòng |
| `fact_product_sku_status` | Có, từ 01/04/2026 | item × `fc_code` × ngày, 13,8 triệu dòng; `web_status`, `is_active`, `product_afs` |
| `fact_sku_is_active_day_by_date`, `fact_sku_status_day_by_date` | Có, từ 02/07 và 20/07/2026 | Dùng `sales_region_code`, không phải `fc_code`; cần quy tắc ánh xạ |
| `staging_sku_status_history`, `staging_sku_is_active_history` | Có (dạng sự kiện), từ 06/01/2025 | Mỗi dòng là một lần thay đổi trạng thái |
| `fact_seller_oos` | Có (ảnh chụp theo ngày), từ 21/01/2025 | Có `fc_code`, `qty_available` |

Chỉ dùng an toàn trong backtest khi:
- giá trị thuộc **ngày trước mốc dự báo** (dùng làm lag);
- biết thời điểm chụp của bảng;
- bạn xác nhận ý nghĩa và cách ánh xạ.

Trạng thái của các ngày tương lai không biết được lúc dự báo, nên không dùng làm feature của ngày đích. Tôi không tạo nhãn "nhu cầu tiềm ẩn" và không điền dữ liệu.

### 7. B4 – Production (chỉ GET, 17:41 và 19:32)

| Hạng mục | Kết quả | Trạng thái |
|---|---|---|
| Phiên bản | 1.2.8 (`/api/health`, `current.txt`), DB schema 6 | `PASS` |
| `storage.json` | `8D79DBDD…E047`, không đổi | `PASS` |
| Model đang dùng | `TRN-20261020054540-D7EEF6`, `in_use` = true, `MV-20261020-131556-EEF6`, file SHA `cd5f4ce5…456b`; forecast `FCR-20261020082402-A42C91` (PUBLISHED, 17.138 chuỗi, ngày dự báo 20/10) | `PASS` |
| Promotion | Audit 184 `MODEL_PROMOTED` lúc 08:24:14 UTC (15:24:14 giờ VN), từ `PROMOTION_REVIEW_REQUIRED`, thay `TRN-20261019043033-A761C1`. Audit không ghi người thực hiện. Phiên của tôi chỉ gọi GET. | `PASS` (dữ kiện) |
| Tương thích | Model 1.2.8 dùng 31 feature (không giờ mở bán, không customer). Code 1.2.9 giữ nguyên danh sách feature của model cũ. | `PASS` |
| Price / customer | `feature_price` = true (model có `price_last`, `price_rel_28`); bản 1.2.8 không có nhóm customer, nên customer coi như OFF | `PASS` |
| Job / lịch | Không có job đang chạy; D-1 03:00 (dự phòng 05:00), training 09:00, D-0 08–18 giờ mỗi 2 giờ, EOD 23:55, chốt 23:59 – không đổi | `PASS` |
| So sánh 17:41 → 19:32 | Cùng phiên bản, `storage.json`, model, forecast, cấu hình `model` / `data_policy`; DB vẫn 1.358.317 dòng, `loaded_at` 05:30:05. Chỉ thêm audit 188 `D0_SNAPSHOT` (lượt 18:00 chạy bù lúc 19:14, 2.664 dòng) | `PASS` |
| Máy ngủ | Nhật ký Windows: Modern Standby 17:50:22 → 19:14:12. Lượt D-0 18:00 bị lỡ, scheduler chạy bù (`CATCH_UP`, `LATEST_ONCE`). Lượt D-1 03:00, EOD 23:55 và chốt 23:59 cũng cần máy thức. | Rủi ro vận hành (đã biết từ 19/10) |

### 8. B5 – Kế hoạch phát hành 1.2.9 và backfill preview (chưa thực hiện)

**Nội dung 1.2.9:**
- Có 79 file chưa commit, cộng thêm 1 file test của đợt này.
- Các thay đổi chính:
  - thứ trong tuần mã 1–7;
  - giờ mở bán bắt buộc với BIGQUERY, có trạng thái `MULTI_ITEM`;
  - migration 0007 / 0008 (bổ sung cột, schema 8);
  - quy tắc ngày bắt đầu training;
  - `customer_id` mặc định OFF;
  - preview bắt buộc trước backfill, kèm backup;
  - sửa lỗi kiểm tra lại backfill.
- Thay đổi độc lập với 931 khóa và 6 khóa: toàn bộ, trừ gate giờ mở bán. Gate này **phụ thuộc** quy tắc `MULTI_ITEM`.

**Preview** (`BFP-20261020082746-E6B4D7` trên bản sao DB 15:25; vẫn đúng với production lúc 17:41 vì cùng 1.358.317 dòng và cùng `loaded_at` 05:30:05):

| | Giá trị |
|---|---|
| Dòng nguồn đọc / hợp lệ | 8.961.566 / 8.961.566; 0 dòng trùng hoàn toàn; 7.203 dòng lặp khóa D-1 (cộng dồn theo SUM_ALL) |
| SKU × ngày | mới 344, sửa 213, xóa 772, giữ nguyên 1.357.332 |
| Tổng số lượng | 42.023.217 → 42.011.108 (−12.109) |
| Ngày có thay đổi | 272 (01/01–19/10) |
| Giờ mở bán ghi vào | `OK` 1.357.883, `MULTI_ITEM` 6 |
| Tác dụng phụ (trên bản sao) | chốt thực tế (actual close) có thêm 1 bản sửa; dữ liệu cửa sổ khớp nguồn 292/292 ngày |

**Trước phát hành:**
1. Bạn quyết định quy tắc `MULTI_ITEM` (hoặc chấp nhận training bị chặn).
2. Bạn cho phép commit; chạy `scripts\release.ps1`, gồm QA và đóng gói.
3. Diễn tập trên `LOCALAPPDATA` riêng với bản sao DB: nâng cấp 6 → 8, preview, backfill, `data-check`, rollback.
4. Chọn khung giờ ngoài lịch chạy (ví dụ 19:00–22:00, sau D-0 18:00), không có job đang chạy.
5. `deploy-upgrade.ps1 -CheckOnly`.

**Sau phát hành:**
1. `/api/health` = 1.2.9; schema 8; `storage.json` không đổi.
2. Tạo preview mới. Preview hết hạn sau 6 giờ, và nguồn có thể đã làm mới.
3. Backfill 01/01 → hôm qua.
4. Đối chiếu từng ngày với nguồn; `data-check`.
5. Model 1.2.8 vẫn được dùng; dự báo vẫn xuất bản.

**Điều kiện PASS:**
- preview `READY`, số mới/sửa/xóa khớp lúc diễn tập (± thay đổi của nguồn);
- 0 dòng giờ mở bán bị mất;
- ngày khớp nguồn = 100%;
- `data-check` không có FAIL;
- model đang dùng không đổi.

**Điều kiện FAIL / dừng:**
- preview không `READY`, hoặc có lỗi đọc;
- số dòng mới/sửa/xóa vượt diễn tập mà không giải thích được;
- schema hoặc `storage.json` thay đổi ngoài dự kiến;
- có job chạy chồng.

**Blocker:**

| Blocker | Loại |
|---|---|
| 6 khóa `MULTI_ITEM` → training BIGQUERY dừng mỗi ngày ở `OPEN_HOURS_INVALID` | `BLOCKED_BUSINESS_RULE` |
| Ý nghĩa giờ = 0 có đơn (931 khóa) → ý nghĩa của feature | `BLOCKED_USER_REVIEW` (không chặn kỹ thuật) |
| Commit / đóng gói / phát hành | Cần bạn cho phép |
| Rollback về 1.2.8 cần khôi phục backup (schema 8) | Bạn cần chấp nhận |

Tôi không tuyên bố sẵn sàng phát hành.

### 9. B6 – Thí nghiệm offline tiếp theo (đã chuẩn bị, chưa chạy)

- Kế hoạch ghi trước khi có kết quả: `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p21\plan_next.json`.
- Tối đa 4 cấu hình, 15 lần train, 2 giờ. Cùng fold, chỉ số và quy tắc trạng thái như đợt 5. Price ON, customer OFF.

| Cấu hình | Nội dung | Cần trước khi chạy |
|---|---|---|
| D1 | Chẩn đoán: tách sai số B0 theo `web_status` của ngày (không train) | Bạn xác nhận ý nghĩa `fact_product_sku_status` |
| D2 | B0 + tỷ lệ ngày `OUT_OF_STOCK` trong 7 / 28 ngày **trước mốc** | D1, thời điểm chụp bảng, kiểm tra leakage |
| D3 | Xử lý 931 khóa theo đúng quyết định của bạn | Kết quả xem Excel |
| D4 | Tham số tweedie 1,5 (code thí nghiệm riêng) | Không phụ thuộc gì; chạy khi bạn muốn |

Lý do chưa chạy:
- 7 cấu hình của đợt 5 đều không cải thiện.
- Các giả thuyết có khả năng tác động lớn nhất (D1–D3) cần xác nhận nghiệp vụ.
- Thử các quy tắc `MULTI_ITEM` không đáng một lần chạy, vì chúng chạm rất ít feature.

### 10. Code và test

- Code ứng dụng: **không sửa**.
- Thêm `backend/tests/test_v129f_zero_open_hours.py` (2 test):
  - D-1 lưu giờ 0 có đơn là `0` / `OK` (kể cả khóa 2 item cùng giờ 0); gate cửa sổ không chặn;
  - feature nhận 0, tính 0 vào trung bình, không mang 0 sang ngày không có giá trị.
- Kết quả test:
  - backend toàn bộ: lần 1 (trước khi thêm test) 632 passed / 10 skipped / 0 failed, 307 giây; lần 2 (sau khi thêm test): **634 passed / 10 skipped / 0 failed**, 294 giây, xong lúc 19:31;
  - file test mới: 2 passed.
- Loại kiểm tra: unit / tích hợp với FakeBQ và DB tạm. Kiểm tra trên bản sao DB và BigQuery thật chỉ đọc là bằng chứng dữ liệu, không phải test tự động.
- Frontend không đổi, không chạy. Lint chưa được cấu hình.
- Tài liệu: `CHANGELOG.md` (mục đợt 6), `docs/03_van_hanh/CHECKPOINT.md` (dòng đợt 6), `docs/02_kien_truc_du_lieu/BIGQUERY.md` (§11e, các bảng ứng viên).

### 11. An toàn dữ liệu

- BigQuery chỉ đọc. Mọi truy vấn có dry run trước và mức trần mỗi truy vấn; không DML/DDL, không bảng tạm. Tổng 11,65 GB: 8,24 GB bảng nguồn, 3,41 GB bảng tham chiếu. Metadata (danh sách bảng, schema) không tính phí.
- Bảng nguồn không đổi trong suốt đợt (tạo lúc 08:05:30 UTC).
- Bản sao DB (`p21\livecopy`) được giải nén từ backup sẵn có của bản sao e9 trong scratchpad, mở `mode=ro`. Bản sao e9 chỉ đọc.
- Production chỉ GET. Không ghi, không train, không promote, không backfill, không deploy, không đổi lịch hay cấu hình, không commit, không push.
- Không xóa log, checkpoint, báo cáo hay artifact nào. Không ghi đè file nào; workbook tạo ở chế độ "x".
- Checkpoint trước: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129f-before.zip`, SHA `C9329CCBA12E016A7573B0101F24A0B6BA56918824F239DAE7FFE9CE8585AD9D`.
- Checkpoint cuối: `D:\Buymed\Lightgbm AI\checkpoints\checkpoint-20261020-v129f-worktree.zip`, SHA `8CD38C10AAE8030D8E4458A7AFF23B4D96C1B06BB775B657E37EFB70B71FDF02`, 1.577.137 byte, 116 mục: 81 file nguồn kèm patch, báo cáo, workbook, 32 file scratchpad p21; không gồm bản sao DB. Đã kiểm tra: CRC, danh sách = manifest, hash từng file, hash bằng PowerShell. Bản báo cáo trong zip còn 2 chỗ trống (giờ kết thúc và dòng này), được điền sau khi tạo zip.
- So với checkpoint trước, chỉ 4 file nguồn thay đổi: `CHANGELOG.md`, `docs/02_kien_truc_du_lieu/BIGQUERY.md`, `docs/03_van_hanh/CHECKPOINT.md`, `backend/tests/test_v129f_zero_open_hours.py`.

### 12. Việc tiếp theo

**Làm ngay được, không cần chờ bạn:**
1. Đối chiếu nhóm chuỗi "giảm > 50%" với `fact_product_sku_status`: tỷ lệ ngày `OUT_OF_STOCK` trước và sau tháng 7, chỉ đọc. Phải ghi rõ ý nghĩa bảng chưa xác nhận.
2. Kiểm tra lại snapshot ở lần làm mới nguồn tiếp theo, xem giờ trước tháng 3 có được giữ không (`p20/bq_oh.py`).
3. Chuẩn bị nhánh code R0–R5 cho `MULTI_ITEM` ở dạng tắt sẵn, chỉ bật theo quyết định của bạn.

**Phải chờ bạn:**
1. Kết quả xem Excel 931 khóa (`user_decision` / `user_notes`).
2. Quy tắc `MULTI_ITEM`.
3. Ý nghĩa và cách ánh xạ `fact_product_sku_status` (và các bảng ứng viên khác).
4. Đơn 71.834 ngày 28/08 là nhu cầu thường hay đơn đặc biệt.
5. Nguồn chỉ gồm seller `MEDX` / `INTERNAL` có đúng phạm vi mong muốn không.
6. Cho phép commit, đóng gói, phát hành 1.2.9 và backfill.

### 13. File tạo ra

| File | SHA-256 / ghi chú |
|---|---|
| `D:\Buymed\Lightgbm AI\reports\demandforecast_zero_open_hours_with_orders_20261020.xlsx` | `A9640616318B5BA75C941750AA9A1CCBB1CCA308A6247A65F0DEE95525301025` (579.162 byte) |
| `D:\Buymed\Lightgbm AI\reports\demandforecast_zero_hours_followup_audit_20261020.md` | báo cáo này |
| `D:\Buymed\Lightgbm AI\backend\tests\test_v129f_zero_open_hours.py` | test mới |
| Scratchpad `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p21\` | `bq_meta.py`, `bq_meta2.py`, `bq_zero.py`, `bq_avail.py` (truy vấn); `e9_zero.py` (bằng chứng feature); `build_xlsx.py`, `verify_xlsx.py` (workbook); `b1_effect.py`, `b2_multi.py`, `b13_numbers.py` (phân tích); `prod_get.py` (GET production); `plan_next.json`; kết quả `.json` cùng tên |

## 3. Data reconciliation - 6 khóa MULTI_ITEM và D-1 ngày 21/10/2026

Nguồn: `reports\multi-item-d1-20261021\DATA_RECONCILIATION.md` (worktree MAIN).

### Nguồn dữ liệu và cách đối soát

- **Bảng nguồn:** `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`.
  - Mô tả bảng: `PIC:giau.vo`, `created_date >= 2026-01-01`, `refresh 07h00`.
  - Snapshot dùng xuyên suốt: dựng lại **21/10/2026 07:10:38** (giờ VN), 8.979.752 dòng.
  - Metadata được đọc trước / sau mỗi bộ truy vấn và trước mỗi bước của chuỗi D-1: không đổi.
- **Truy vấn BigQuery:** chỉ đọc (SELECT), dry run trước, trần 2 GiB mỗi truy vấn. Tổng ~4,48 GB:
  - 3,72 GB cho 6 khóa và bảng trạng thái item;
  - 0,74 GB cho tổng hợp cửa sổ D-1;
  - 21 MB metadata.
- **Phía app:** bản sao DB production làm bằng SQLite backup API, nguồn mở `mode=ro`, đặt trong scratchpad p27.
  - `dbcopy_before`: 15:10:50, trước D-1.
  - `dbcopy_after`: 15:12:24, sau D-1.
- **Dữ liệu khách hàng:** không có `customer_id` thô (chỉ số khách khác nhau / cờ thiếu).

### 1. Sáu khóa MULTI_ITEM

| | Nguồn 21/10 07:10 (01/01-20/10) | App sau D-1 |
|---|---|---|
| Khóa nhiều giá trị giờ (mọi lý do) | 6 (09/02 HN, 10/02 HN, 02/03 BD × 2, 26/08 BD × 2); 0 ở 20/10 | 6 dòng `MULTI_ITEM`, `open_hours` NULL |
| Dòng / đơn vị | 39 / 156 | số lượng từng khóa = nguồn (8, 11, 88, 3, 42, 4) |
| Mỗi item một giá trị / ngày | có (2.191 / 2.191 item-ngày của 6 SKU năm 2026, giống nhau ở mọi FC) | - |
| Số dòng = số đơn (không nhân dòng) | có ở mọi item của 6 khóa | - |
| Giờ item dựng lại từ log trạng thái (`NORMAL` hoặc `LIMIT` = mở) | khớp 2.190 / 2.191 tới 0,01 h; 2.191 / 2.191 trong 0,02 h; 26/08 khớp cả bảng khoảng ngày | - |
| Miền bán của item (cột `sales_region_code`) | `.1` → MIENNAM, `.2` / `.3` → MIENBAC ở 6 SKU (đọc từ cột nguồn, không từ hậu tố) | - |
| Phân loại | nhiều item hợp lệ (listing của 2 miền, cùng FC) | giữ chặn (quyết định chủ hệ thống) |

Workbook bằng chứng: `demandforecast_multi_item_6keys_evidence_20261021.xlsx`, 10 sheet, SHA-256
`745CD884DC721767ED5E93403B12F6DE6FA8D5970D40B8D930C3DD1A4F6E0CFE`.

| Sheet | Nội dung |
|---|---|
| Summary | Tóm tắt kết quả |
| Six_Keys | Một dòng cho mỗi khóa |
| Source_Lines | 113 dòng nguồn của 6 SKU trong các ngày đó, mọi FC |
| Item_FC_Counts | Số dòng / đơn / khách theo item × FC |
| Classification | Kết quả theo 4 loại |
| Open_Hours_Definition | Kiểm tra các định nghĩa giờ mở |
| Item_Hours_Rebuilt | 2.191 item-ngày dựng lại |
| Status_Intervals_2608 | Khoảng trạng thái ngày 26/08 |
| Candidate_Values_INFO | Giá trị quy tắc ứng viên (không áp dụng) |
| App_State | Trạng thái lưu trong app |

### 2. Trước khi ghi: dry run và đối soát độc lập (cửa sổ D-1 16/10-20/10)

| Chỉ số | Dry run của app (`ingest-check` 15:10:40) | SQL độc lập + bản sao DB (15:10:50) |
|---|---:|---:|
| Dòng nguồn đọc | 91.039 | 91.039 |
| Khóa nguồn / số lượng | 15.115 / 385.502 | 15.115 / 385.502 |
| Khóa đang lưu trong cửa sổ / số lượng | 12.078 / 307.236 | 12.078 / 307.236 |
| Khóa mới | 3.037 | 3.037 (+78.266 đơn vị) |
| Khóa đổi số lượng | 0 | 0 |
| Khóa bị loại | 0 | 0 |
| Không đổi | 12.078 | 12.078 |
| Chênh số lượng | +78.266 (toàn bộ ngày 20/10) | +78.266 |
| Trùng hoàn toàn | 0 nhóm; 892 dòng chờ xác nhận không mã, 136 giống ở cột ánh xạ, 0 giống mọi cột | - |
| Giờ mở bán | OK 15.115 | kỳ vọng OK 15.115; 0 lệch ở khóa đang lưu |

**Nguồn đầy đủ cho ngày 20/10:**

- Bảng được dựng lại lúc 07:10:38 ngày 21/10, tức sau khi ngày 20/10 kết thúc.
- 18.208 dòng, bằng 97% trung bình 7 ngày trước (18.741); bước completeness của app PASSED.
- 78.266 đơn vị ≥ tổng chốt 23:59 của 20/10 từ nguồn D-0 (revision 1, 58.410). Tỉ lệ 1,34, như ngày 19/10 (89.862 /
  67.071).

### 3. D-1 thật và đối soát sau khi ghi

`JOB-20261021081102-643FC7`, chạy 15:11:02-15:11:58, SUCCEEDED; load `D1L-20261021081118-FE92FE`. Ghi 15.115 khóa: 3.037 mới,
0 đổi, 0 bị loại, 12.078 không đổi. Kết quả này bằng dry run.

| Chỉ số (16/10-20/10) | App | Nguồn | Chênh |
|---|---:|---:|---:|
| Khóa | 15.115 | 15.115 | 0 |
| Số lượng | 385.502 | 385.502 | 0 |
| Khóa mới / bị loại / đổi | - | - | 0 / 0 / 0 |
| Giờ mở bán lệch trạng thái / giá trị | - | - | 0 |

Theo ngày, app = nguồn:

| Ngày | Khóa | Đơn vị |
|---|---:|---:|
| 16/10 | 3.120 | 91.980 |
| 17/10 | 2.966 | 68.054 |
| 18/10 | 2.661 | 57.340 |
| 19/10 | 3.331 | 89.862 |
| 20/10 | 3.037 | 78.266 |

**Cả cửa sổ model 01/01-20/10, bản sao sau D-1:**

- 1.360.913 khóa = 1.357.876 (đối soát sau backfill sáng nay) + 3.037.
- 42.088.223 đơn vị, bằng tổng nguồn 01/01-20/10 cùng snapshot (cổng trùng 1.2.10 trên bảng thật cũng đọc 42.088.223).
- 293 ngày; trạng thái giờ: OK 1.360.907, `MULTI_ITEM` 6.

**Chốt actual (bất biến):**

- 293 ngày `FINALIZED` / `D1_LOAD` / sealed; trước D-1 là 292.
- 16-19/10 giữ load cũ `D1L-20261021054224-9918CF` (backfill), giá trị chốt = nguồn.
- 20/10 chốt từ load `D1L-20261021081118-FE92FE`: 3.037 khóa / 78.266 đơn vị.
- Không ngày nào bị chặn chốt.

**Close 23:59:**

- 20/10 thêm revision 2 `D1_LOADED` (78.266).
- Revision 1 `SCHEDULED_CLOSE` (58.410, nguồn D-0) giữ nguyên.
- 18/10 (r1-r4) và 19/10 (r1-r3) không đổi.

### 4. Cổng huấn luyện trên dữ liệu sau D-1

`open_hours.window_check` cho cửa sổ 01/01-20/10 (bản sao): 1.360.913 dòng, OK 1.360.907; `not_ok = {MULTI_ITEM: 6 dòng,
2026-02-09..2026-08-26}`. Kết quả là `OPEN_HOURS_INVALID`.

Chạy thử `train_and_publish` trên bản sao cô lập: HTTP 409 trong 6,7 s. Số dòng các bảng `training_runs`, `forecast_runs`,
`forecast_values`, `demand_daily`, `job_runs`, `audit_log` không đổi.

### 5. File kết quả (scratchpad p27)

`C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p27\`:

| File | Nội dung |
|---|---|
| `bq_def.json` | metadata bảng nguồn, các bảng liên quan |
| `bq_items.json` | 6 khóa, dòng nguồn, nhật ký trạng thái |
| `analysis_items.json` | định nghĩa giờ, dựng lại, phân loại |
| `src_agg_d1_1016_1020.json.gz` | tổng nguồn theo khóa |
| `state\ingest_check.json` | dry run |
| `state\recon_before.json`, `state\recon_after.json` | đối soát trước / sau khi ghi |
| `state\d1_job.json` | job D-1 |
| `state\window_facts.json` | cửa sổ, chốt, close |
| `state\app_keys_after.json` | 6 khóa trong app, cổng huấn luyện |
| `state\iso_gate.json` | chạy thử cổng trên bản sao cô lập |
| `state\prod_before.json`, `state\prod_after.json` | trạng thái production qua API |
| `state\backup_verify.json` | kiểm tra backup |
| `state\d1chain.log` | log chuỗi D-1 |

Các file này nằm trong checkpoint sau (xem `RESUME_CHECKPOINT.md`).

## 4. Báo cáo cuối - MULTI_ITEM open hours → D-1 → training (21/10/2026, 14:10-15:30)

Nguồn: `reports\multi-item-d1-20261021\FINAL_REPORT.md` (worktree MAIN).

**Trạng thái: `BLOCKED_DATA_SAFETY` ở Gate D (huấn luyện).** Gate A, B, C đạt: D-1 thật đã chạy thành công và đối soát khớp
tuyệt đối. Huấn luyện **không** chạy. Lý do: 6 khóa `MULTI_ITEM` vẫn làm cổng giờ mở bán chặn (`OPEN_HOURS_INVALID`). Nguồn
và repository không có quy tắc gộp, và chủ hệ thống quyết định **giữ chặn** trong phiên 21/10/2026, trước khi chạy D-1. Model và forecast
production giữ nguyên. Không push, không đổi lịch, cấu hình, target hay grain.

| Gate | Kết quả | Bằng chứng chính |
|---|---|---|
| A - kiểm tra trước | ĐẠT | production 1.2.10 (PID 30096, `current.txt` 1.2.10, `storage.json` `8D79DBDD…E047`); 0 job đang chạy; nguồn dựng lại 21/10 07:10:38, có 20/10; backup `backup-20261021-145525-cli.zip` đã xác minh; checkpoint trước |
| B - MULTI_ITEM | ĐẠT (phân loại theo bằng chứng); quy tắc gộp: KHÔNG có → giữ chặn | 6 khóa = nhiều item hợp lệ (listing của 2 miền bán, cùng FC); không có join fan-out, mâu thuẫn hay lỗi mapping; +22 test; backend 683 passed / 17 skipped; vitest 155; typecheck và build OK |
| C - D-1 | ĐẠT | `JOB-20261021081102-643FC7` SUCCEEDED, 16/10-20/10, 56 s; app = nguồn trên 15.115 khóa / 385.502 đơn vị; 20/10 đã chốt |
| D - huấn luyện | **CHẶN** (đúng thiết kế) | `OPEN_HOURS_INVALID`: 6 dòng `MULTI_ITEM` (09/02-26/08) trên 1.360.913 dòng của cửa sổ; chạy thử trên bản sao cô lập không ghi gì |

### 1. Nguyên nhân gốc và cách xử lý

- **Bản chất 6 khóa.** Mỗi khóa ngày × SKU × FC có 2 `item_code` của cùng `sku_code`. Theo cột nguồn `sales_region_code` (bảng
  `fact_sku_status_day_by_date`), mỗi item là listing của SKU ở **một miền bán** (MIENNAM / MIENBAC). Đơn của cả hai listing
  được xuất từ cùng một `fc_code` trong ngày. Miền lấy từ cột nguồn, **không** từ hậu tố `.1/.2/.3`.
- **Định nghĩa giờ của một item (đã xác minh).** `total_open_hours` = số giờ trong ngày (giờ VN) item ở trạng thái `NORMAL`
  hoặc `LIMIT`, theo nhật ký `staging_sku_status_history`. Dựng lại khớp 2.190 / 2.191 item-ngày năm 2026 tới 0,01 h, và
  2.191 / 2.191 trong 0,02 h. Ngày 26/08 cũng khớp với khoảng `start_at` / `end_at` của bảng ngày.
- **Phân loại theo 4 loại yêu cầu.**
  1. Join nhân dòng: **không** (số dòng = số đơn ở mọi item; cổng trùng 0 nhóm).
  2. Nhiều item hợp lệ trong cùng khóa: **có, cả 6**.
  3. Giờ mâu thuẫn: **không** (mỗi item một giá trị, giống nhau ở mọi FC).
  4. Lỗi mapping / khóa: **không**.
- **Không có tầng nào sai.** Source, mapping, JOIN, aggregation và validation đều đúng. Giờ mở bán đo theo listing, còn model ở
  hạt SKU × FC. Nguồn (mô tả bảng: `PIC:giau.vo`, `refresh 07h00`) và repository không định nghĩa cách gộp 2 listing của 2
  miền thành một giá trị.
- **Không sửa code, không thêm ngoại lệ.** Cổng validation chặn đúng thiết kế. Không áp dụng MAX, MIN, trung bình hay hợp
  khoảng. Thay đổi trong repository (chưa commit):
  - 2 file test hồi quy mới;
  - ghi chú trong `open_hours.py` (chỉ comment);
  - tài liệu `docs/02_kien_truc_du_lieu/BIGQUERY.md` §11f, `DATA-MODEL.md`, mục CHANGELOG "Unreleased".

### 2. Sáu khóa trước / sau

| Khóa | Ngày | FC | Dòng | Đơn vị | Giờ mỗi item | Cùng SKU ở FC kia | App trước / sau D-1 |
|---|---|---|---:|---:|---|---|---|
| K1 | 09/02 | HN | 4 | 8 | .1 23,92 · .2 24 | BD: .1 23,92 (OK) | MULTI_ITEM, NULL, 8 / không đổi |
| K2 | 10/02 | HN | 2 | 11 | .1 21,16 · .3 24 | BD: .1 21,16 (OK) | MULTI_ITEM / không đổi |
| K3 | 02/03 | BD | 18 | 88 | .1 5,0 · .2 24 | HN: .2 24 (OK) | MULTI_ITEM / không đổi |
| K4 | 02/03 | BD | 3 | 3 | .1 1,7 · .2 24 | HN: .2 24 (OK) | MULTI_ITEM / không đổi |
| K5 | 26/08 | BD | 8 | 42 | .1 23,72 · .2 24 | - | MULTI_ITEM / không đổi |
| K6 | 26/08 | BD | 4 | 4 | .1 22,85 · .2 18,22 | HN: .2 18,22 (OK) | MULTI_ITEM / không đổi |

- Tổng 39 dòng / 156 đơn vị; số lượng trong app = nguồn ở cả 6 khóa.
- Nguồn hiện tại (01/01-20/10) có đúng 6 khóa này; 20/10 không có khóa nào.
- Quy tắc giờ đã xác minh ở **mức item**. **Không** có quy tắc nào xác minh được ở mức SKU × FC.
- Giá trị các quy tắc ứng viên (hợp khoảng, MAX, MIN, item bán nhiều nhất, trung bình theo số lượng) có trong sheet
  `Candidate_Values_INFO`, chỉ để chủ hệ thống tham khảo, không áp dụng.

### 3. Test, typecheck và build

Chi tiết lệnh và log: `TEST_RESULTS.md`.

- **Backend:** 683 passed / 17 skipped / 0 failed. 663 → 683 nhờ +20 test offline; 15 → 17 skipped là 2 test BigQuery thật
  opt-in mới.
- **BigQuery thật trên dòng inline (0 byte):** 12 passed, gồm 2 test mới.
- **Frontend:** vitest 25 file / 155 passed; typecheck exit 0; build exit 0. Không có thay đổi frontend.
- **Lint:** chưa được cấu hình.

### 4. Phiên bản production

1.2.10 trước và sau, không deploy. PID 30096 giữ nguyên; `storage.json` không đổi; schema 9.

### 5. D-1

- **Job:** `JOB-20261021081102-643FC7`, `POST /api/schedules/d1/run`. Đây là cơ chế "Chạy ngay", dùng chung job, khóa và
  điều kiện sẵn sàng với lịch.
- **Thời gian:** 15:11:02-15:11:58 (56 s). Trạng thái **SUCCEEDED**, chế độ `FALLBACK_TIME_VERIFIED`.
- **Cửa sổ:** 16/10-20/10; load id `D1L-20261021081118-FE92FE`.
- **Đọc:** 91.039 dòng / 385.502 đơn vị; 0 trùng hoàn toàn; 366 dòng lặp khóa được cộng theo SUM_ALL.
- **Ghi:** 15.115 khóa (3.037 mới, 0 đổi, 0 bị loại, 12.078 không đổi). Giờ mở bán `OK` cả 15.115.
- **Dry run trước khi ghi (`ingest-check`):** READY, mọi bước PASSED, cùng các số trên.

### 6. Dòng, khóa, số lượng và đối soát

Chi tiết: `DATA_RECONCILIATION.md`.

- **Trước khi ghi:** đối soát độc lập (SQL riêng, cùng snapshot 07:10:38) = dry run. 3.037 khóa mới (+78.266, toàn bộ ngày
  20/10), 0 đổi, 0 bị loại.
- **Sau khi ghi:** app = nguồn trên 15.115 / 15.115 khóa và 385.502 / 385.502 đơn vị; 0 lệch giờ mở bán.
- **Cả cửa sổ model 01/01-20/10:** 1.360.913 khóa / 42.088.223 đơn vị / 293 ngày, bằng tổng nguồn.
- **Chốt actual:** 293 ngày, tất cả `FINALIZED` / sealed. Ngày 20/10 chốt từ load D-1 này, 3.037 khóa / 78.266 đơn vị.
- **Close:** 20/10 có revision 2 `D1_LOADED` (78.266); revision 1 (58.410, nguồn D-0) giữ nguyên. 16-19/10 không có revision
  mới.

### 7. Huấn luyện

**Không chạy**, nên không có training ID, metric hay so sánh model.

- Cổng `OPEN_HOURS_INVALID` chặn trước khi ghi bất cứ gì. Chạy thử `pipeline.train_and_publish(force=True)` trên bản sao cô
  lập của production sau D-1 trả HTTP 409, `not_ok = {MULTI_ITEM: 6 dòng, 2026-02-09..2026-08-26}`, 0 bản ghi mới.
- Lịch 07:00 hôm nay được scheduler ghi `SKIPPED MISSED_SLOT_NO_BACKFILL` (`JOB-20261021081219-4C2CF4`, policy SKIP), nên
  không có huấn luyện tự động.

### 8. Model production

Giữ nguyên:

- model đang dùng `TRN-20261020054540-D7EEF6` (`MV-20261020-131556-EEF6`, ACCEPTED);
- forecast `FCR-20261020082402-A42C91`.

Không promote; số `training_runs` và `forecast_runs` không đổi (so sánh trước / sau qua API).

### 9. Backup, checkpoint, rollback

- **Backup trước D-1:** `backups\backup-20261021-145525-cli.zip`, SHA-256
  `8DB291150A674DA242550EA652B4EF50F7699A365134074CF0C4526E88CCD0F2`. Đã kiểm tra: CRC, integrity ok, schema 9, model, job mới
  nhất.
- **Checkpoint trước:** `checkpoints\checkpoint-20261021-multiitem-d1-before.zip`, SHA-256
  `94FBBB7306F2A31971A389599D1E66765BB11D186D6842FF98A7168CB04C288F`.
- **Checkpoint sau:** xem `RESUME_CHECKPOINT.md`.
- **Rollback D-1 (không cần):** dừng app, rồi `restore.ps1` của 1.2.10 với backup 145525. Mất mọi thứ ghi sau 14:55.
- **Rollback phiên bản về 1.2.8:** như cũ, backup 121031.

### 10. Việc chưa hoàn thành và việc cần chủ hệ thống quyết định

1. **Huấn luyện BIGQUERY: CHẶN.**
   - Cần chủ hệ thống chọn một quy tắc giờ mở bán SKU × FC cho các khóa nhiều listing (hoặc nguồn tự cung cấp giá trị ở hạt
     này), rồi phát hành bản mới và nạp lại 4 ngày 09/02, 10/02, 02/03, 26/08.
   - Hoặc giữ chặn: model hiện hành vẫn dùng được, nhưng không có candidate mới.
2. **Lịch huấn luyện 22/10 07:00 sẽ thất bại `OPEN_HOURS_INVALID`** nếu D-1 06:00 thành công. Đây là hệ quả của quyết định giữ
   chặn; không tự tắt lịch. Tắt hay giữ lịch là quyết định của chủ hệ thống.
3. **Giờ dựng lại nguồn lệch với lịch D-1.**
   - Mô tả bảng nguồn ghi `refresh 07h00`, hôm nay dựng lại lúc 07:10.
   - D-1 06:00 / dự phòng 06:30 có thể lại dừng `SOURCE_INCOMPLETE`, như sáng 21/10.
   - Đề xuất: chủ hệ thống cân nhắc dời D-1 sau 07:15. Tôi chưa đổi lịch.
4. **Chưa commit / push.** Thay đổi gồm 2 test mới, ghi chú `open_hours.py` và tài liệu. Commit khi được duyệt.

## 5. Resume checkpoint - MULTI_ITEM / D-1 21/10/2026

Nguồn: `reports\multi-item-d1-20261021\RESUME_CHECKPOINT.md` (worktree MAIN).

### Trạng thái lúc ~15:30 ngày 21/10/2026

#### Production

- Phiên bản **1.2.10**, schema 9, `http://127.0.0.1:8765`, PID 30096; không deploy trong đợt này.
- `storage.json` SHA-256 `8D79DBDD…E047`, không đổi.
- Không còn job đang chạy.

#### Dữ liệu BIGQUERY

- 01/01-20/10 = nguồn snapshot 21/10 07:10:38: 1.360.913 khóa, 42.088.223 đơn vị, 293 ngày đã chốt.
- 20/10 nạp bởi D-1 `JOB-20261021081102-643FC7` lúc 15:11.

#### Huấn luyện BIGQUERY

- Bị chặn `OPEN_HOURS_INVALID` do 6 khóa `MULTI_ITEM`; chủ hệ thống quyết định giữ chặn.
- Model và forecast đang dùng không đổi: `TRN-20261020054540-D7EEF6` / `FCR-20261020082402-A42C91`.
- Lịch 07:00 hôm nay: SKIPPED (`MISSED_SLOT_NO_BACKFILL`).

#### Lịch (không đổi)

| Luồng | Giờ |
|---|---|
| D-1 | 06:00 / dự phòng 06:30 |
| D-0 | 08-18 h, mỗi 2 h |
| Huấn luyện | 07:00 (SKIP khi lỡ) |
| EOD | 23:55 |
| Close | 23:59 |

Huấn luyện 22/10 07:00 sẽ thất bại `OPEN_HOURS_INVALID` nếu D-1 06:00 thành công.

#### Git

- `main` tại `f0061c8`, chưa push.
- Thay đổi chưa commit:
  - test mới `backend/tests/test_v1210_multi_item_open_hours.py`, `backend/tests/test_v1210_real_bq_multi_item_regions.py`;
  - ghi chú `backend/app/data/open_hours.py` (chỉ comment);
  - tài liệu `docs/02_kien_truc_du_lieu/BIGQUERY.md` §11f, `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `CHANGELOG.md` (Unreleased), `docs/03_van_hanh/CHECKPOINT.md`.

### Hiện vật

| Hiện vật | Vị trí | SHA-256 |
|---|---|---|
| Backup trước D-1 (đã xác minh) | `backups\backup-20261021-145525-cli.zip` | `8DB291150A674DA242550EA652B4EF50F7699A365134074CF0C4526E88CCD0F2` |
| Checkpoint trước | `checkpoints\checkpoint-20261021-multiitem-d1-before.zip` | `94FBBB7306F2A31971A389599D1E66765BB11D186D6842FF98A7168CB04C288F` |
| Checkpoint sau (báo cáo, workbook, script, kết quả, state, diff) | `checkpoints\checkpoint-20261021-multiitem-d1-after.zip` | `F0B2B69B240E653B596B5284A8BB870BE56287972B8A9FA75AD55162C548A80B` (bản tạo trước khi ghi dòng SHA này vào file) |
| Workbook 6 khóa | `reports\multi-item-d1-20261021\demandforecast_multi_item_6keys_evidence_20261021.xlsx` | `745CD884DC721767ED5E93403B12F6DE6FA8D5970D40B8D930C3DD1A4F6E0CFE` |
| Điểm rollback về 1.2.8 (không đổi) | `backups\backup-20261021-121031-manual.zip` | `AEFEA751…601F` |
| Scratchpad | `C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p27\` | - |

Scratchpad p27 có các bản sao DB `dbcopy_before`, `dbcopy_after`, `iso_gate` (mỗi bản ~1 GB, không đưa vào checkpoint).

### Rollback (chỉ khi cần)

D-1 hôm nay chỉ thêm dữ liệu 20/10 và chốt ngày đó. Muốn bỏ D-1 này:

```powershell
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\scripts\stop.ps1"
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\scripts\restore.ps1" -File "D:\Buymed\Lightgbm AI\backups\backup-20261021-145525-cli.zip"
& "$env:LOCALAPPDATA\Programs\DemandForecast\1.2.10\scripts\start.ps1"
```

Mất mọi thứ ghi sau 14:55 (D-1 15:11, chốt 20/10, close r2 20/10, D-0 sau đó). Rollback phiên bản về 1.2.8 vẫn như trong
`reports\fix71-restore-d1-20261021\RESUME_CHECKPOINT.md`.

### Lệnh kiểm tra nhanh (chỉ đọc)

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod "http://127.0.0.1:8765/api/jobs?limit=5"
cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_v1210_multi_item_open_hours.py
$env:DF_REAL_BQ = "1"; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_v1210_real_bq_multi_item_regions.py
```

### Việc tiếp theo (chủ hệ thống)

1. Quy tắc giờ mở bán SKU × FC cho khóa nhiều listing. Có hai hướng:
   - chọn quy tắc (sheet `Candidate_Values_INFO` có giá trị từng phương án), rồi phát hành bản mới, preview và backfill 4
     ngày 09/02, 10/02, 02/03, 26/08, rồi huấn luyện candidate;
   - hoặc nguồn tự cung cấp giờ ở hạt SKU × FC.
2. Giữ hay tạm tắt lịch huấn luyện 07:00 trong thời gian chặn.
3. Cân nhắc dời D-1 sau giờ nguồn dựng lại (07:00-07:10).
4. Duyệt commit (và push) các thay đổi test và tài liệu.

## 6. Test results - MULTI_ITEM / D-1 21/10/2026

Nguồn: `reports\multi-item-d1-20261021\TEST_RESULTS.md` (worktree MAIN).

### Loại kết quả và nơi lưu log

| Nhãn | Nghĩa |
|---|---|
| unit | DB tạm của conftest, không gọi ra ngoài |
| integration-fake | FakeBQ / TestClient |
| real external | BigQuery thật trên dòng inline: 0 byte, không đọc bảng |
| DB copy | bản sao production cô lập |
| production | API thật của production |

Log nằm trong scratchpad
`C:\Users\GIAUVO~1\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p27\`.

### 1. Bộ test đầy đủ

| Lệnh | Thời điểm | Kết quả | Log |
|---|---|---|---|
| `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | 15:03-15:09 | **683 passed, 17 skipped, 0 failed** (381,5 s), 1 warning có từ trước (Starlette httpx) | `test_backend_full.log` |
| Lặp lại trên cây cuối, sau khi sửa comment `open_hours.py` và tài liệu | 15:15-15:20 | **683 passed, 17 skipped, 0 failed** (314,0 s) | `test_backend_full2.log` |
| `cd frontend; npm test; npm run typecheck; npm run build` | 15:02-15:05 | vitest **25 file, 155 passed**; typecheck exit 0; build exit 0 (`index-CWFdCJhm.js` 684,53 kB, giống gói 1.2.10 - không có thay đổi frontend) | `test_frontend.log` |
| Lint | - | **not configured** | - |

**So với đợt fix 7.1 (663 passed / 15 skipped):**

- +20 test offline mới.
- +2 test opt-in BigQuery thật. Đây là 2 test bỏ qua thêm trong bộ đầy đủ; chúng được chạy riêng ở mục 2.
- Không test nào bị xóa, sửa hay làm yếu.

### 2. BigQuery thật (opt-in)

Lệnh:

```powershell
$env:DF_REAL_BQ = "1"
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_v1210_real_bq_multi_item_regions.py tests\test_v129h_real_bq_pending_grain.py tests\test_v129e_real_bq_item_suffix.py tests\test_v129c_real_bq_items_customers.py tests\test_v129_real_bq_open_hours.py tests\test_bq_real_semantics.py
```

Loại: real external, dòng inline, 0 byte. Kết quả: **12 passed** (63,1 s): 10 test cũ + 2 test mới.

### 3. Test mới và 6 yêu cầu của đợt

**File `backend/tests/test_v1210_multi_item_open_hours.py`** (unit / integration-fake, 20 test):

| Test | Nội dung | Yêu cầu |
|---|---|---|
| `test_the_six_real_keys_have_no_value_and_no_aggregate_of_the_items_comes_out` (×6) | 6 mẫu thật → MULTI_ITEM; không ra MIN, MAX hay trung bình | (2), (6) |
| `test_the_other_fc_of_the_same_sku_and_day_keeps_its_one_item_value` (×5) | cùng SKU / ngày ở FC kia → OK đúng giá trị item | (1) |
| `test_valid_keys_give_exactly_one_value` | nhiều đơn một item, hai item cùng giờ, giờ 0 → một giá trị | (5) |
| `test_inconsistent_or_unattributable_hours_are_detected_and_get_no_value` (×6) | một item hai giá trị, dòng không mã item → CONFLICT; < 0 hoặc > 24 → OUT_OF_RANGE; thiếu → MISSING | (4) |
| `test_d1_keeps_the_demand_of_a_multi_item_key_and_each_fc_gets_its_own_status` | D-1 qua FakeBQ | (1), (2), (6) |
| `test_training_stops_on_one_multi_item_row_and_nothing_is_trained_or_replaced` | cổng huấn luyện | (6) |

- **Test D-1 qua FakeBQ** kiểm tra: mỗi FC một trạng thái; số lượng giữ đủ, không mất, không nhân đôi; `window_check` chỉ ra
  MULTI_ITEM.
- **Test cổng huấn luyện** kiểm tra:
  - `force=True` vẫn dừng `OPEN_HOURS_INVALID` với chi tiết MULTI_ITEM;
  - không có run hay forecast mới;
  - số lượng của khóa giữ nguyên, không bịa giờ.

**File `backend/tests/test_v1210_real_bq_multi_item_regions.py`** (real external, opt-in, 2 test). Dữ liệu inline mô phỏng 6
khóa thật: SKU tổng hợp, giờ và cấu trúc dòng thật, kể cả dòng ở FC kia.

| Test | Nội dung | Yêu cầu |
|---|---|---|
| `test_real_bigquery_multi_item_keys_get_no_value_and_every_other_key_exactly_one` | xem bên dưới | (1), (2), (4), (5) |
| `test_real_bigquery_customer_counts_join_never_changes_lines_quantities_or_open_hours` | bật join đếm khách: cùng khóa, số lượng, số dòng, trạng thái giờ | (3) |

Test đầu kiểm tra:

- FC lấy từ `fc_code`;
- 6 khóa → MULTI_ITEM; khóa FC kia → OK;
- nhiều đơn của một item hoặc hai item cùng giờ → OK;
- CONFLICT, OUT_OF_RANGE và MISSING được phát hiện;
- số lượng và số dòng mỗi khóa = tổng dòng inline;
- không có `item_code` nào rời BigQuery.

6 yêu cầu của đợt:

1. Hậu tố khác nhưng FC thực tế khác.
2. Nhiều item hợp lệ trong cùng ngày và FC.
3. JOIN không nhân dòng.
4. Phát hiện giờ không nhất quán.
5. Trường hợp hợp lệ cho đúng một giá trị.
6. Dữ liệu không đủ căn cứ bị chặn rõ.

### 4. Kiểm chứng production và bản sao

| Kiểm chứng | Loại | Kết quả | File |
|---|---|---|---|
| Trạng thái production trước / sau qua API GET (phiên bản, PID, `storage.json`, 5 luồng, thiết lập model / quality / data_policy / bigquery, forecast và training run) | production | giống hệt; 0 job đang chạy | `state\prod_before.json`, `state\prod_after.json` |
| Backup chính thức `backup.ps1` (1.2.10) + kiểm tra độc lập | production backup | `backup-20261021-145525-cli.zip` 151 s; CRC, integrity ok, schema 9, model, job mới nhất | `state\backup_run.txt`, `state\backup_verify.json` |
| D-1 dry run (`POST /api/bigquery/ingest-check`) | production + BigQuery thật | READY, mọi bước PASSED, không ghi | `state\ingest_check.json` |
| Đối soát độc lập trước / sau | DB copy + BigQuery thật | trước = dry run; sau: app = nguồn, 0 lệch giờ mở bán | `state\recon_before.json`, `state\recon_after.json` |
| D-1 thật (`POST /api/schedules/d1/run`) | production | SUCCEEDED trong 56 s, ghi bằng dry run | `state\d1_job.json`, `state\d1chain.log` |
| Cổng huấn luyện trên bản sao cô lập (`iso_gate.py`) | DB copy (isolated) | `OPEN_HOURS_INVALID` 409, 0 bản ghi mới | `state\iso_gate.json` |
| Dựng lại giờ item từ log trạng thái | real external (chỉ đọc) + offline | 2.190 / 2.191 khớp 0,01 h | `analysis_items.json` |

Lần dry run đầu dừng ở exit 22. Nguyên nhân là điều kiện của script quá chặt: bước `write` = NOT_RUN là đúng thiết kế của dry
run. Tôi đã sửa script và chạy lại. Lần chạy đầu không ghi gì.

### 5. Không làm để đạt PASS

- Không xóa hay làm yếu test.
- Không thêm ngoại lệ cho MULTI_ITEM, không tắt validation.
- Không chọn MAX, MIN, trung bình hay hợp khoảng.
- Không sửa dữ liệu nguồn.
- Không đổi cấu hình hay lịch.

## 7. Demand Forecasting — thứ trong tuần, `total_open_hours` bắt buộc, quản lý cột D-1 theo vai trò, tên thứ tiếng Việt

Nguồn: `reports\weekday_total_open_hours_mapping_fix.md` (worktree MAIN).

Ngày 19/10/2026 (giờ Asia/Ho_Chi_Minh), 21:13 – 22:26. Mã nguồn sau 1.2.8 (HEAD `0da73b6`), **chưa commit, chưa đóng gói,
chưa deploy, không push**. Production vẫn chạy 1.2.8 (deploy 20:08 hôm nay) và **không bị thay đổi**.

### 1. Kết luận

| Yêu cầu | Kết luận | Tóm tắt |
|---|---|---|
| A. Thứ trong tuần | **PASS** | Một hàm chuẩn 1–7 (Thứ 2 = 1 … Chủ nhật = 7) cho cả backend; model mới mã hóa `dow` 1–7, model cũ giữ mã 0–6 đã học; công tắc có trên trang Cấu hình và trang Ánh xạ trường, lưu bền vững (test qua API, đọc lại DB, khởi động app mới); đi xuyên huấn luyện / backtest / dự báo / giải thích |
| B. `total_open_hours` bắt buộc + vai trò cột D-1 | **PARTIAL** | Cơ chế **xong và kiểm chứng** (mapping bắt buộc, D-1 đọc và kiểm từng ngày × SKU × FC, cổng chặn huấn luyện, feature có trong ma trận và trong model, vai trò mọi cột, SQL đã chạy trên BigQuery thật với dữ liệu nhúng). **Chưa dùng được trên dữ liệu production**: (1) chưa deploy (migration 0007); (2) cần nạp lại D-1 toàn kỳ; (3) dữ liệu thật thiếu giờ mở bán 01/01–18/03/2026 và có 2 khóa xung đột tháng 8 — theo yêu cầu "không tự suy diễn", huấn luyện BigQuery sẽ **dừng** (`OPEN_HOURS_INVALID`) cho tới khi chủ hệ thống quyết định |
| C. Tên thứ trong bảng Dự báo chi tiết | **PASS** | Cột hiện "Thứ 2 … Chủ nhật" tính từ ngày dự báo (backend trả `weekday` 1–7); số cũ trong cột là `horizon_day` (ngày thứ N của kỳ dự báo), không phải thứ — vẫn giữ ở tooltip; Excel định dạng 6 thêm cột "Thứ trong tuần", giữ cột số "Ngày thứ" |

### 2. Nguyên nhân gốc

**A — `feature_weekday` "chưa được lưu / chưa áp dụng xuyên suốt"** (bằng chứng chỉ đọc trên production):
- Production chạy **1.2.6 tới 20:08 hôm nay**; 1.2.6 không có khóa `feature_weekday`, Pydantic v2 bỏ qua khóa lạ → không thể lưu.
- Sau deploy 1.2.8 chưa có lần lưu nào: `GET /api/settings/model/history` chỉ có **1 bản ghi (17/10 01:26)**, không có khóa này;
  `model.feature_weekday` hiện là `null` (= theo nhóm Lịch, đang bật).
- Trang **Ánh xạ trường** (nơi có cột `created_date`) không có công tắc; trang Cấu hình chỉ lưu khi bấm "Lưu" của thẻ, không báo "chưa lưu".
- Quy ước `dow` là 0 = Thứ Hai (khác quy ước 1–7 yêu cầu); `explain` trả `weekday` 0–6; hai nơi dùng `date.weekday()` riêng.
- Pipeline 1.2.8 **đã** dùng công tắc ở huấn luyện / backtest / dự báo (DIRECT + RECURSIVE) — đã kiểm lại bằng test.

**B — `total_open_hours` chỉ là trường tham chiếu:**
- Trường `open_hours` nằm trong `REFERENCE_FIELDS` (`settings_service.py`), loại "không bao giờ là đầu vào mô hình"; registry để ở
  `PLANNED` / `HAS_SOURCE_DATA_NOT_ACTIVATED` vì **chưa có quy tắc tổng hợp / giá trị thiếu**.
- D-1 có đọc cột (để so trùng) nhưng không tổng hợp, `demand_daily` không có cột chứa nó → không thể vào feature matrix.
- Không có khái niệm "vai trò" cho cột nguồn; cột không thuộc trường nào thì không hiện trên trang.

**C — cột "Ngày thứ":** hiển thị `x.horizon_day` (khóa i18n `fc.day_n` = "Day #"), tức vị trí trong kỳ dự báo. Với kỳ 7 ngày
nó chạy 1–7 nên trông như số thứ; ánh xạ thẳng 1 → "Thứ 2" sẽ **sai** (ngày dự báo đầu tiên 20/10/2026 là Thứ 3).

### 3. File / module đã thay đổi

| Phần | File |
|---|---|
| Mới | `backend/app/weekday.py` (hàm thứ chuẩn), `backend/app/data/open_hours.py` (quy tắc giờ mở bán), `backend/app/migrations/0007_open_hours.sql` |
| Backend | `settings_service.py` (vai trò trường, `extra_reference_columns`, `feature_open_hours`, `weekday_encoding`), `ml/features.py` (Panel.hours, feature, mã hóa dow), `bq/connector.py` (SQL D-1, kiểm tra mapping, `column_roles`, cảnh báo kiểm tra toàn kỳ), `sync.py` (ghi giá trị + trạng thái), `data/demand.py`, `data/identity.py`, `ml/pipeline.py` (cổng + lưu cấu hình theo run), `ml/feature_registry.py`, `ml/feature_catalog.py`, `ml/explain.py`, `explain_export.py`, `api/forecast_routes.py`, `api/ops_routes.py`, `api/data_routes.py`, `export_i18n.py`, `messages.py`, `data/demo.py`, `data_checks.py` (4 kiểm tra giờ mở bán) |
| Frontend | `components/ui.tsx` (`isoWeekday`, `weekdayLabel`), `pages/Results.tsx`, `pages/Mapping.tsx`, `pages/Config.tsx`, `i18n.tsx` |
| Test mới | `backend/tests/test_v129_weekday_open_hours.py`, `backend/tests/test_v129_real_bq_open_hours.py` (BigQuery thật, opt-in), `frontend/src/v129.test.tsx` |
| Test cũ cập nhật (fixture / kỳ vọng theo hành vi mới, không bỏ assertion) | `test_bigquery.py`, `test_bq_real_semantics.py`, `test_v111.py`, `test_v112.py`, `test_v113.py`, `test_v115_bigquery_features.py`, `test_v120_features.py`, `test_v120_price.py`, `test_v122_bigquery_policy.py`, `test_v124_history_names_schedules.py`, `test_v126_eod_backup_close.py`, `test_v126_retention_defaults.py`, `test_v128_fixes.py` |
| Tài liệu | `CHANGELOG.md` (Unreleased 1.2.9), `docs/02_kien_truc_du_lieu/BIGQUERY.md` (mục 3: vai trò, giờ mở bán), `docs/04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md`, `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `docs/02_kien_truc_du_lieu/DATA-DICTIONARY.md`, `docs/03_van_hanh/CHECKPOINT.md`; kiểm tra bất biến mới trong `backend/app/data_checks.py` |

### 4. Thay đổi UI và API / schema / cấu hình

- **Schema:** migration **0007** thêm `demand_daily.open_hours REAL` và `demand_daily.open_hours_status TEXT` (NULL được, không
  default, không ràng buộc, không trigger). Schema 6 → 7.
- **Cấu hình:** `bigquery.extra_reference_columns` (mặc định `[]`, ngoài mapping hash); `model.feature_open_hours`,
  `model.weekday_encoding` chỉ do huấn luyện ghi vào bản cấu hình lưu với từng run (`PUT /api/settings/model` từ chối
  `feature_open_hours` → `OPEN_HOURS_MANDATORY`, bỏ `weekday_encoding`). Không đổi giá trị cấu hình nào đang lưu.
- **API:** `/api/forecast-runs/{id}/values` thêm `weekday` (1–7) mỗi dòng + `weekday_rule`; `/api/bigquery/status` thêm `roles`,
  `field_roles`, `mandatory_reference_fields`, `column_roles`; `/api/bigquery/schema` thêm `column_roles`; `POST
  /api/bigquery/mapping` nhận `extra_reference_columns`; `/api/features/registry` có trạng thái giờ mở bán và
  `next_training.blocked_by`; mã lỗi mới `OPEN_HOURS_INVALID`, `OPEN_HOURS_MANDATORY`, `COLUMN_ROLE_CONFLICT`,
  `EXTRA_REFERENCE_ALREADY_MAPPED`; cảnh báo kiểm tra toàn kỳ `OPEN_HOURS_MISSING`, `OPEN_HOURS_OUT_OF_RANGE`.
- **Excel dự báo:** định dạng **6** — cột "Thứ trong tuần" / "Weekday" sau cột ngày; cột số "Ngày thứ" giữ nguyên.
- **UI:**
  - Ánh xạ trường: cột **Vai trò** cho mọi trường; `open_hours` hiện "Bắt buộc (luôn dùng, không tắt được)", không có lựa chọn
    "Không dùng"; thẻ **Tất cả cột của nguồn D-1 và vai trò** (Chưa phân loại / Tham chiếu, báo xung đột vai trò, đếm theo vai trò);
    thẻ **Thứ trong tuần (tính từ ngày created_date)** với ô "Sử dụng thứ trong tuần khi dự báo", mô tả cách tính, báo "Chưa lưu".
  - Cấu hình mô hình: mô tả thứ trong tuần theo quy ước 1–7; dòng "Giờ mở bán — bắt buộc" (không phải công tắc).
  - Kết quả dự báo → Dự báo chi tiết từng ngày: cột **Thứ** ("Thứ 2" … "Chủ nhật"), tooltip "Ngày thứ N".

### 5. Kết quả kiểm thử

| Nhóm | Lệnh | Kết quả | Loại |
|---|---|---|---|
| Backend toàn bộ | `cd backend; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **574 passed, 8 skipped, 0 failed** (9 phút 31 giây; 8 bỏ qua = test BigQuery thật, chỉ chạy khi `DF_REAL_BQ=1`) | unit + tích hợp với BigQuery giả, DB cô lập |
| Backend mới | `pytest tests\test_v129_weekday_open_hours.py` | **48 passed** | unit + tích hợp cô lập (dữ liệu tổng hợp) |
| BigQuery thật (opt-in) | `$env:DF_REAL_BQ="1"; pytest tests\test_v129_real_bq_open_hours.py tests\test_bq_real_semantics.py` | **3 passed** (0 byte quét, dữ liệu nhúng) | **dịch vụ thật** |
| BigQuery thật D-0 (opt-in) | `$env:DF_REAL_BQ="1"; pytest tests\test_v121_d0.py tests\test_v121_d0_real_bq.py` | **22 passed** | dịch vụ thật |
| Frontend | `cd frontend; npx vitest run` | **21 file, 142 passed** (9 mới) | unit / component (fetch giả) |
| Typecheck | `npm run typecheck` | exit 0 | — |
| Build | `npm run build` | exit 0 (1.929 module) | — |
| Migration trên bản sao DB production | `scratchpad\p16\mig_copy.py` | xem mục 11 | bản sao DB |
| Lint | — | **chưa cấu hình** (không tính là đạt) | — |

Lượt đầu (trước khi cập nhật fixture): 38 lỗi / 488 đạt — toàn bộ do hành vi mới đúng yêu cầu (mapping bắt buộc, cổng giờ
mở bán, định dạng Excel 6, schema 7, quy ước 1–7) **và 1 lỗi thật của mã mới** (cổng chặn cả khi cửa sổ rỗng, che mất lỗi kỹ
thuật có sẵn) — đã sửa trong `pipeline.py`.

### 6. Bằng chứng `feature_weekday` đi xuyên pipeline

- Một hàm: `app/weekday.iso_weekday` (date / datetime / Timestamp / chuỗi; ngày không hợp lệ → lỗi, không đoán). Dùng ở
  `features.calendar_row` / `dow_value` (huấn luyện, backtest, dự báo RECURSIVE, DIRECT `direct_extra`), `explain` (bảng ngày
  lịch sử), `explain_export`, `/values`, export Excel, DEMO.
- Test: 7 ngày liên tiếp 19–25/10/2026 → 1…7; cuối năm, ngày nhuận; nhãn sai (0, 8, 2.5, NaN, True, "x") → không nhãn.
- Lưu bền vững: `PUT` → `GET` → đọc trực tiếp DB → **app mới** (`create_app()`) vẫn trả cùng giá trị; tắt thì `dow`,
  `is_weekend` không có trong `feature_names`; bật lại thì có.
- Huấn luyện DEMO thật (cô lập): run lưu `weekday_encoding = "ISO"`; `booster.feature_name()` = danh sách feature lưu; giải thích
  tái tạo khớp giá trị công bố và `dow` = thứ ISO của **ngày dự báo**.
- Model cũ: cấu hình không có `weekday_encoding` → `dow` 0–6 như lúc huấn luyện; danh sách feature không đổi (test
  `test_new_models_encode_dow_1_to_7_old_models_keep_0_to_6`, các test 1.2.8 giữ nguyên).
- Ngày lịch sử = `order_date` = cột `created_date` của D-1 (mapping production `order_date ← created_date`, kiểu DATE).

### 7. Bằng chứng `total_open_hours` bắt buộc và có trong feature matrix

- Mapping: thiếu / "Không dùng" / cột biến mất / sai kiểu → lỗi (`REQUIRED_NOT_MAPPED`, `COLUMN_NOT_FOUND`, `TYPE_INCOMPATIBLE`).
- D-1 (SQL): `COUNTIF(ref_open_hours IS NULL)`, `MIN`, `MAX` theo ngày × SKU × FC; không có AVG hay COALESCE. **Chạy trên
  BigQuery thật** (dữ liệu nhúng): 24/24 → OK 24; 0 → OK 0; 13,85 → OK; một dòng NULL → MISSING; toàn NULL → MISSING; 19,37 và 24
  → CONFLICT; 25,5 và −1 → OUT_OF_RANGE; số lượng nhu cầu không đổi.
- Ghi D-1 (BigQuery giả): đúng giá trị / trạng thái cho 5 trường hợp, nhu cầu luôn được ghi.
- Cổng huấn luyện (DB cô lập, dữ liệu tổng hợp ở scope BIGQUERY): chưa nạp cột → `OPEN_HOURS_INVALID` (NOT_LOADED = mọi dòng),
  **không tạo training run**; 1 dòng CONFLICT → chặn với đúng ngày; đủ OK → huấn luyện PUBLISHED, cấu hình run
  `feature_open_hours = true`, `open_hours_last`, `open_hours_mean_7` có trong `booster.feature_name()` (= danh sách lưu) và
  trong `feature_importance`; nhận diện dữ liệu của run gồm cột `open_hours`; giải thích tái tạo khớp và `open_hours_last` = giờ
  mở bán của **ngày trước mốc dự báo** lấy từ DB.
- Không rò rỉ: đổi giá trị của ngày mục tiêu và các ngày sau → feature không đổi; DIRECT tính tại mốc; RECURSIVE sau mốc = NaN
  (không điền); backtest cắt `hours` theo fold.
- Model / cấu hình cũ: không có `feature_open_hours` → không có feature giờ mở bán.
- Dữ liệu thật (bản sao DB production, chỉ đọc sau khi chép): cửa sổ 01/01–18/10/2026 có **1.355.000** dòng BIGQUERY, tất cả
  **NOT_LOADED** → sau khi deploy, huấn luyện BigQuery sẽ dừng cho tới khi nạp lại D-1 toàn kỳ (và quyết định ở mục 10).

### 8. Bằng chứng các cột D-1 được quản lý theo vai trò

- `column_roles` trên schema 11 cột thử: `sku_code` / `fc_code` / `created_date` / `so_code` = Khóa; `demand_quantity` =
  Target; `total_open_hours` = Đặc trưng bắt buộc (`model_input`); `sales_price` = Đặc trưng tùy chọn (đọc chung bởi trường tham
  chiếu); `product_id` = Tham chiếu; `seller_class`, `refresh_time` = **Chưa phân loại** (không tự gán vai trò); đánh dấu tham
  chiếu → `EXTRA_REFERENCE`; cột đã ánh xạ nhưng biến mất → `MISSING_IN_SOURCE`.
- Xung đột: `open_hours ← demand_quantity` (Target + đặc trưng) và `unit_price ← sku_code` (Khóa + đặc trưng) →
  `COLUMN_ROLE_CONFLICT`; hai khóa cùng cột → `SAME_COLUMN_FOR_SEVERAL_KEYS` (quy tắc cũ giữ nguyên).
- Tương thích ngược: JSON BigQuery kiểu 1.2.8 (không có `extra_reference_columns`) đọc được; **mapping hash bằng đúng công
  thức 1.2.8** → production không bị tắt / phải kiểm tra lại toàn kỳ vì nâng cấp; phân loại cột tham chiếu không đổi hash.
- Schema nguồn thật (17 cột, từ snapshot đã lưu): 15 cột có trường dùng; `seller_class`, `refresh_time` hiện "Chưa phân loại".

### 9. Bằng chứng nhãn thứ tiếng Việt

- Backend `/values`: mọi dòng `weekday == iso_weekday(target_date)`; kỳ 7 ngày có đủ 1…7; `horizon_day` không đổi.
- Excel: cột "Thứ trong tuần" = nhãn của chính ngày, "Ngày thứ" vẫn là số; phiên bản định dạng "6".
- Frontend: 20/10…26/10/2026 → "Thứ 3, Thứ 4, Thứ 5, Thứ 6, Thứ 7, Chủ nhật, Thứ 2"; tooltip "Ngày thứ 1…7"; tiêu đề "Thứ"
  thay "Ngày thứ"; backend cũ không có `weekday` → tính từ ngày; giá trị hỏng (9) → "—"; ngày không tồn tại (30/02) → không
  nhãn; chuỗi có giờ +07:00 không bị đẩy sang ngày khác.

### 10. Phần chưa kiểm chứng được / điều kiện để hoàn thành B

1. **Quyết định nghiệp vụ (chủ hệ thống)** — không tự suy diễn:
   - 01/01–18/03/2026 nguồn **không có** `total_open_hours` (NULL toàn bộ; profile BigQuery chỉ đọc, ~497 MB quét). Lựa chọn:
     dời `data_policy.window_start_date` ≥ 2026-03-19, hoặc duyệt một quy tắc cho ngày thiếu, hoặc nguồn bổ sung dữ liệu.
   - **2 khóa ngày × SKU × FC tháng 8** có giá trị khác nhau (chênh tối đa 4,63 giờ): duyệt quy tắc tổng hợp (vd. MAX / MIN /
     theo số lượng) hoặc sửa nguồn.
2. **Deploy** bản có migration 0007 (theo quy trình deploy có backup), rồi **nạp lại D-1 toàn kỳ** (D-1 hằng ngày chỉ đọc lại vài
   ngày gần nhất).
3. Chưa chạy huấn luyện trên dữ liệu production thật có giờ mở bán (cần 1 và 2; không được chạy training production trong đợt này).
4. Nguồn DEMO / Excel không có cột giờ mở bán → giờ mở bán "không áp dụng" cho các nguồn đó (mẫu Excel không đổi).

### 11. Migration và yêu cầu triển khai (không tự triển khai)

Bản sao DB production (SQLite backup API, nguồn `mode=ro`; thư mục cô lập `scratchpad\p16\mc`), mã nguồn hiện tại:
- chép 3,3 s; `db.migrate` **92,9 s** (gần như toàn bộ là backup tự động trước migration — ALTER TABLE thêm cột là O(1));
- schema 6 → 7, áp dụng đúng `0007_open_hours.sql`; 28 bảng: số dòng **giống hệt**, chỉ `schema_migrations` +1;
  `demand_daily` 1.393.568 dòng: số khóa, số dòng theo scope và **băm toàn bộ giá trị cũ** giống hệt; 2 cột mới toàn NULL; trigger
  giống hệt; `integrity_check` ok;
- lệnh đảo ngược ghi trong đầu migration (DROP COLUMN ×2 + xóa bản ghi version 7) đưa bản sao về schema 6 với **giá trị y hệt**.
- Rollback chính thức về 1.2.8 = khôi phục backup trước nâng cấp (1.2.8 từ chối schema mới hơn 6), như 0004–0006.
- Review độc lập (agent `data-reviewer`, chỉ đọc): **SAFE WITH CONDITIONS** — migration chỉ bổ sung, mọi đường đọc/ghi
  `demand_daily` dùng danh sách cột tường minh, không đường nào tạo giá trị giả, không rò rỉ, nhận diện dữ liệu run cũ giữ nguyên.
  Đã xử lý: (1) kiểm lại giờ mở bán ngay sau `load_demand` (khe hở giữa kiểm và nạp → run FAILED `OPEN_HOURS_INVALID`, không
  forecast); (2) `features_at` báo lỗi thay vì điền NaN khi panel không có giờ mở bán; (3) thông báo lỗi chỉ đúng đường nạp
  lại (trang "SQL nguồn & đồng bộ", thẻ "Đọc lại lịch sử (backfill) có kiểm soát", tối đa 400 ngày — cửa sổ 01/01–18/10 là 291
  ngày); (4) bước chạy thử D-1 báo số trạng thái giờ mở bán; (5) 4 kiểm tra mới trong `data-check` (`open_hours_status_values`,
  `open_hours_value_matches_status`, `open_hours_source_scope` = FAIL nếu sai; `open_hours_window_ready` = WARN) + DATA-MODEL /
  DATA-DICTIONARY; (6) cảnh báo trong migration: lệnh đảo ngược chỉ dùng khi chưa có run do 1.2.9 huấn luyện (1.2.8 sẽ đưa dow
  0–6 vào model học 1–7). Còn lại (cần chủ hệ thống): quyết định ở mục 10; model RECURSIVE thiếu giờ mở bán "hôm trước" từ ngày
  dự báo thứ 2 (production dùng DIRECT) — so sánh WAPE / bias trước khi promote (ghi trong MO-HINH-VA-CHI-SO.md).

Khi chủ hệ thống quyết định triển khai: commit → `scripts\release.ps1` (gói 1.2.9) → diễn tập cô lập → `deploy-upgrade` trong
khung giờ được duyệt (thời gian thêm ~1,5 phút cho backup trước migration) → nạp lại D-1 toàn kỳ → (sau quyết định ở mục 10)
huấn luyện.

### 12. Git

- Nhánh `main`, HEAD **`0da73b6`** (Release 1.2.8), ahead 26 so với `origin/main` (chưa push từ trước). **Chưa commit**,
  không push. `git status`: **42 file sửa + 6 file mới** (48):
  - mới: `backend/app/weekday.py`, `backend/app/data/open_hours.py`, `backend/app/migrations/0007_open_hours.sql`,
    `backend/tests/test_v129_weekday_open_hours.py`, `backend/tests/test_v129_real_bq_open_hours.py`, `frontend/src/v129.test.tsx`;
  - sửa: 18 file `backend/app/…`, 13 file `backend/tests/…`, 5 file `frontend/src/…`, `CHANGELOG.md`, `docs/02_kien_truc_du_lieu/BIGQUERY.md`,
    `docs/04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md`, `docs/03_van_hanh/CHECKPOINT.md`, `docs/02_kien_truc_du_lieu/DATA-MODEL.md`, `docs/02_kien_truc_du_lieu/DATA-DICTIONARY.md`.
- Quét bí mật trên diff + file mới: 0. `reports/` không thuộc Git.
- Checkpoint trước khi sửa: `checkpoints/checkpoint-20261019-v129-before.zip` (git archive HEAD: backend/app, frontend/src, tài
  liệu), SHA-256 `0809B18F79FE690CC85DA82EC1503BCFE5AC6ABBE09131077FF8F109A60F8ACA`.
- Kiểu xuống dòng: mọi file giữ đúng CRLF / LF gốc, 0 file trộn.

### Phụ lục — số liệu BigQuery (chỉ đọc, 01/01–18/10/2026)

| Tháng | Dòng | NULL | min | max | = 24 | > 24 / < 0 | khóa | khóa khác giá trị |
|---|---|---|---|---|---|---|---|---|
| 01 | 1.236.952 | 1.236.952 | — | — | 0 | 0 | 169.585 | 0 |
| 02 | 975.050 | 975.050 | — | — | 0 | 0 | 130.859 | 0 |
| 03 | 1.195.302 | 699.443 | 0 | 24 | 481.050 | 0 | 168.873 | 0 |
| 04 | 966.804 | 0 | 0 | 24 | 946.370 | 0 | 148.609 | 0 |
| 05 | 1.026.983 | 0 | 0 | 24 | 1.005.294 | 0 | 155.336 | 0 |
| 06 | 997.072 | 0 | 0 | 24 | 975.381 | 0 | 152.135 | 0 |
| 07 | 955.603 | 0 | 0 | 24 | 925.535 | 0 | 158.367 | 0 |
| 08 | 735.564 | 0 | 0 | 24 | 684.863 | 0 | 130.547 | **2** |
| 09 | 519.187 | 0 | 0 | 24 | 484.891 | 0 | 84.092 | 0 |
| 10 | 334.069 | 0 | 0 | 24 | 316.120 | 0 | 56.570 | 0 |

Giá trị đầu tiên có dữ liệu: 2026-03-19. Không khóa nào "NULL một phần". Script: `scratchpad\p16\bqprof.py` (dry run trước, trần
2 GiB; 168 MB + 328 MB).
