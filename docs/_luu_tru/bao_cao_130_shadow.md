# Báo cáo triển khai: dự báo mới chạy song song (1.3.0), 28/10/2026

**Trạng thái:** đã làm xong C0–C5 trên branch và bản sao. **Dừng trước C6** vì C1.3 không đạt và các quyết định của chủ dự án đang chờ. Production không bị đụng tới: vẫn bản 1.2.14, model đang dùng `MV-20261026-105345-C73F`.

Chi tiết thiết kế và kết quả: [ke_hoach_trien_khai.md](ke_hoach_trien_khai.md), mục 1, 6, 7, 8.

## 1. Phiên bản, bộ cài, sao lưu

| Mục | Kết quả |
|---|---|
| Phiên bản | 1.3.0, commit cục bộ `969ebe2` trên `feature/du-bao-moi-20261028`, **chưa push** |
| Bộ cài | **Chưa đóng gói, chưa cài** (C6 dừng); không có SHA bộ cài |
| Sao lưu DB | `D:\Buymed\Lightgbm AI\backups\backup-20261028-022138-pre-130-shadow.zip`, SHA `05FBCF1F…42C0`. Sao lưu trực tuyến, nguồn chỉ đọc, có kiểm tra integrity |
| Sao lưu cấu hình | `D:\Buymed\Lightgbm AI\backups\config-*-pre-130-shadow\`: `storage.json` (8D79DBDD…), `current.txt` |
| Thử khôi phục | **ĐẠT**: `app.cli restore` vào thư mục riêng; 35 bảng trùng số dòng, 20 / 20 model, integrity ok, `data-check` 34 OK / 3 WARN, giống DB thật |
| Checkpoint mã nguồn | `checkpoints\source-1.3.0-shadow-before-commit-20261028.zip` (50 file, SHA `98A21A35…EB0A`) |

## 2. Kết quả C1

| Bước | Kết quả |
|---|---|
| 1.1 Giờ mở bán khớp ngày có đơn của D-1 (90 ngày) | 98,92 %: **không đạt ≥ 99 %** vì ngày 26/10 chưa có trong `openhours_by_sku` (bảng làm mới 04:10 nhưng chỉ có đến D-2). Bỏ ngày đó: 301.309 / 301.310 |
| 1.2 Avg lịch sử so với CSV T09 | **100 %** (673.222 / 673.222), làm tròn kiểu SQL ROUND (0,5 làm tròn lên) |
| 1.3 Avg của ngày hôm nay lúc 05:00 | **KHÔNG ĐẠT** (mục 6) |

## 3. Kết quả test

| Test | Kết quả |
|---|---|
| Toàn bộ backend | **1.081 đạt / 19 bỏ qua / 0 lỗi** (unit + tích hợp với fake BigQuery) |
| Frontend | vitest 170 / 170; typecheck đạt; build đạt |
| Lint | chưa cấu hình |
| Công thức B4 | đạt: kết hợp 0,35; ngưỡng nhóm; thiếu Avg; làm tròn cộng dồn 0,3 × 2,2 × 10 ngày = 7; chạy lại cùng ngày cho kết quả giống hệt |
| Cấu hình tắt | đạt: fingerprint, model và lịch giữ nguyên như 1.2.14 |
| Rò rỉ | đạt: sửa dữ liệu từ ngày D trở đi thì dự báo không đổi; panel kết thúc đúng D-1 |
| Migration 0011 trên bản sao DB hôm nay | đạt: 10 → 11; bảng cũ giữ nguyên số dòng; `demand_daily` 17.234 khóa / 43.485.936 không đổi; `data-check` 42 OK / 3 WARN (3 WARN có sẵn) |
| BigQuery thật (chỉ đọc, bản sao) | đạt: giờ mở bán, Avg lịch sử, Avg hôm nay |

**TÁI LẬP** (bản sao DB backtest C7A663BE…, model V1 của lô, Avg ngày D):

| Ngày | Chuỗi | LightGBM so với `forecast_V1` | Dự báo cuối lệch |
|---|---|---|---|
| 15/09 | 16.872 | lệch ≤ 0,00005 | 12 chuỗi |
| 01/10 | 16.986 | lệch ≤ 0,00005 | 10 chuỗi |
| 20/10 | 17.132 | lệch ≤ 0,00005 | 19 chuỗi |

- 41 chuỗi lệch **đều ở biên 0,5**. Ví dụ LightGBM = 4/7, Avg = 2 → giá trị chính xác 1,5 → 2; tính từ CSV 4 chữ số (0,5714) ra 1,49999 → 1.
- Theo đặc tả "Lệch: DỪNG", đây được ghi là **điểm khác giả định**.

**Mô phỏng B8** (dữ liệu 01/08–22/10, đo 01/09–22/10; cùng 14.021 chuỗi và nhóm của file bằng chứng):

| Chỉ số | Kỳ vọng | Kết quả | Lệch |
|---|---|---|---|
| Mất bán/tuần, Avg | 202.144 | 204.979 | **+1,40 %** |
| Mất bán/tuần, Mới | 195.590 | 198.426 | **+1,45 %** |
| Hàng dư, Avg | 86.998 | 87.018 | +0,02 % |
| Hàng dư, Mới | 60.237 | 60.249 | +0,02 % |
| Tồn kho (ngày bán), Avg | 1,63 | 1,619 | −0,47 % |
| Tồn kho (ngày bán), Mới | 1,33 | 1,328 | −0,47 % |

- Mất bán vượt ngưỡng 0,5 %. Phần lệch bằng đúng phần lệch nhu cầu đầu vào ở 261 chuỗi. Ví dụ MEDX.YF9DEQ1P|BD: file bằng chứng 20.157, mọi nguồn trong máy 40.157.
- Nếu tự xếp nhóm theo 01/06–31/08 thì tập chuỗi khác (14.890 chuỗi): hàng dư Mới −11,8 %, tồn kho Mới −6,9 %.

**Review:**

| Lượt review | Kết quả | Ghi chú |
|---|---|---|
| reviewer R1 | APPROVE, 0 Critical | |
| data-reviewer | 0 Critical | đã sửa: cột phạm vi, mốc đọc hoàn tất, trigger chống sửa/xóa, chỉ tính lần chạy theo lịch |
| reviewer R2 | APPROVE, 0 Critical | 4 điểm "nên sửa", đã sửa |
| reviewer R3 | 0 Critical | 2 điểm "nên sửa", đã sửa |

Các lượt review đều được kiểm: `git status`, `git diff` và mã băm các file mới không đổi trước và sau review.

## 4. Model ứng viên V1 (C5, trên bản sao DB lúc 16:10, dữ liệu 01/01–27/10)

| Mục | Kết quả |
|---|---|
| Lần huấn luyện / model | `TRN-20261028092248-C31A9F` / `MV-20261028-165730-1A9F` (sha256 `682dda53…3185`), 36 biến, cấu hình B1 3,0 / 7, fingerprint `f5c0b9ec06ec0a03` |
| Backtest (8 lần thử) | WAPE 0,7974; bias −1,1 %; MAE 6,81. Đường cơ sở 28 ngày: WAPE 0,8303. Model đang dùng chạy lại trên cùng các lần thử: WAPE 0,7980 |
| Quality gate | BACKTEST_RELIABLE đạt; MIN_POINTS đạt; ABS_BIAS đạt; **WAPE_MAX không đạt** (0,797 > 0,60) → USABLE_WITH_WARNING |
| So với model đang dùng | BETTER (WAPE −0,0006) → **REVIEW_REQUIRED** |
| Biến quan trọng nhất | roll_mean_28, roll_mean_56, sku_code, roll_mean_14, roll_mean_7, lag_1 |

- **CHỜ chủ dự án promote.**
- Model này chỉ nằm trong bản sao (`scratchpad\c6`), không có trong production. Khi cài 1.3.0 và bật B1, lần huấn luyện kế tiếp ở production sẽ tạo ứng viên tương ứng.

## 5. Giờ chạy dự kiến (khi được bật; hiện mặc định TẮT)

**Làm mới dự báo (FORECAST_REFRESH):**
- Chạy ngay sau khi D-1 của ngày D thành công **và** có Avg của ngày D.
- Thử lại mỗi 10 phút đến 05:55. Quá hạn thì báo STALE_FORECAST một lần.
- Lịch D-1 hiện tại: dò tín hiệu từ 05:00, mốc dự phòng 06:10.

**Theo dõi tuần (SHADOW_MONITOR):** thứ 2 lúc 09:30; lỡ giờ thì chạy bù một lần trong ngày.

**Lịch hiện có không đổi:** D-0 08–18 giờ, 2 giờ một lần; D-1 05:00 / 06:10; huấn luyện 05:20; sao lưu cuối ngày 23:55; chốt thực bán 23:59.

## 6. Điểm khác giả định

1. **C1.3 không đạt.**
   - Lúc 05:00 ngày 28/10 không nguồn nào có Avg của ngày 28/10.
   - `fact_avg_demand_sku` được nạp lúc 00:15 với giá trị trùng 100 % bản ghi ngày 27/10.
   - `fact_avg_demand_sku_historical` được ghi khoảng 08:10 giờ VN. `transformed_at` hiển thị 15:10, nhiều khả năng là giờ VN lưu dưới dạng UTC.
2. **D-1 theo lịch thất bại ngày 27/10 và 28/10** (SOURCE_INCOMPLETE: nguồn 0 dòng lúc 06:38). D-1 sáng nay chỉ thành công nhờ chạy tay lúc 09:45. Vì vậy điều kiện "D-1 thành công trước 05:55" của B5 hiếm khi đạt.
3. **Giờ mở bán** chỉ có đến D-2 lúc 04:10 (C1.1 98,92 %).
4. **TÁI LẬP:** 41 chuỗi lệch ở biên 0,5 do file tham chiếu chỉ có 4 chữ số.
5. **B8:** mất bán lệch +1,4 % do nhu cầu đầu vào khác (nguồn nhu cầu của file bằng chứng chưa xác định).
6. **Avg trong công thức:** dùng **Avg đã làm tròn** như file bằng chứng (`blend_avg_value = ROUNDED`; có tùy chọn `RAW`).
7. **Luật 14 ngày:** áp dụng theo B3; file bằng chứng không có luật này. Với dữ liệu ngày 01/06–31/08 thì ảnh hưởng gần như không đáng kể.
8. **`actual_daily`** lấy từ `demand_daily` của app, không lấy từ bảng thực bán đã chốt.
9. **`sku_system_status`** không dùng ở bất kỳ đâu, kể cả để lọc Avg (chỉ lọc `seller_code`).
10. **Ý nghĩa của LIVE** đối với các màn hình và file xuất hiện có chưa được đặc tả. Hiện LIVE chỉ đổi cờ, có xác nhận gõ chữ và ghi lịch sử.

## 7. Phương án thay thế cho C1.3 (chưa áp dụng; không đổi công thức)

- **A. Bên dữ liệu tính Avg của ngày D lúc khoảng 02:00** vào một bảng có thời điểm tính trên ngày D. Sau đó khai bảng này vào `shadow.avg_today_table`. Code đã sẵn và không cần đổi gì.
- **B. Dời hạn làm mới** (`refresh_deadline`) sau giờ ghi bản ghi lịch sử (khoảng 08:10), ví dụ 09:30, và dùng nguồn lịch sử làm "Avg hôm nay".
  - Chỉ cần đổi cấu hình, nhưng số mới có muộn hơn trong buổi sáng.
  - Phù hợp với thực tế D-1 đang thành công muộn.
- **C. Dùng Avg của ngày D-1** (bản nạp 00:15).
  - Đây là đổi dữ liệu đầu vào của công thức đã kiểm chứng; backtest dùng Avg của ngày D.
  - Cần backtest lại trước khi dùng.
- **D. Vẫn chạy song song và chấp nhận các ngày STALE** cho tới khi có nguồn phù hợp.

## 8. Việc còn lại và quyết định chờ chủ dự án

1. Xác nhận kế hoạch, gồm 7 điểm ở mục 3 của kế hoạch, và chọn phương án cho C1.3. Sau đó mới đến C6 (đóng gói, cài) và C7 (chạy thử tác vụ làm mới trên production).
2. **Dung lượng `forecast_daily_log`** (khoảng 125 MB mỗi lần làm mới, chưa có thời gian lưu): chọn chuẩn hóa bảng, chỉ giữ h = 1, hoặc xuất ra file.
3. **Tự đổi tỷ lệ kết hợp hằng tháng (B7):** xác nhận trước khi bật theo dõi tuần. Cách hiểu "4 lần liên tiếp" hiện là 4 lần chạy theo lịch có kết quả liên tiếp.
4. **Cảnh báo Avg hôm nay trùng ngày trước** (AVG_TODAY_EQUALS_PREVIOUS_DAY, ≥ 99 %): hiện chỉ cảnh báo, có chặn hay không do chủ dự án quyết.
5. **Promote ứng viên:** chỉ chủ dự án thực hiện.
6. **Liên kết xem từ xa:** `scripts/remote/readonly_proxy.py` chưa mở `/api/shadow/*` (trả 403), nên trang mới chưa xem được qua liên kết từ xa.
7. **Tiến trình `python.exe` dư** (PID 28184, Python hệ thống, khởi động 03:53, khoảng 20 MB) do một agent bỏ lại. Việc dừng nó bị từ chối quyền; chủ dự án có thể tắt bằng tay.
8. **Đợt liên kết từ xa** (9 mục chưa commit, gồm 2 mục "Unreleased" trong CHANGELOG): vẫn để nguyên, không thuộc đợt này.
