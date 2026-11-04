# Demand Forecasting 1.2.9 – Phát hành tối 20/10/2026: kết quả thực tế

| | |
|---|---|
| Thời gian | 20/10/2026 22:55 – 21/10/2026 00:10 (giờ Việt Nam) |
| Yêu cầu | "CLAUDE CODE — DEMANDFORECASTING 1.2.9: RELEASE TỐI NAY, BACKFILL CÓ KIỂM SOÁT VÀ SẴN SÀNG SỬ DỤNG NGÀY MAI" (phương án A) |
| Kết luận | **PARTIAL – dừng ở cổng backfill (Gate 3) vì dữ liệu nguồn.** Gói 1.2.9 đã commit, build, kiểm tra và diễn tập đạt. **Production chưa nâng cấp, vẫn 1.2.8.** Chưa backfill, chưa chốt actual, chưa training. Lý do ở mục 1. |
| Phân loại (AGENTS.md mục 11) | `BLOCKED_DATA_SAFETY` (nguồn D-1 có dòng bị coi là trùng hoàn toàn từ lần tạo lại 22:18) |
| Người đọc | Chủ hệ thống và người duyệt nghiệp vụ |

## 1. Tóm tắt

| Trạng thái | Kết quả |
|---|---|
| 1. Ứng dụng đã triển khai | **Chưa.** Production vẫn 1.2.8 (schema 6). Gói 1.2.9 sẵn sàng: commit `15d4f4b`, gói `B705F3DF…62BB`, precheck production đạt, diễn tập gói 33/34 (kiểm tra còn lại khác ở một trường mới, giải thích ở mục 5). |
| 2. Backfill / đối soát / chốt actual | **Chưa chạy trên production.** Preview của bảng nguồn hiện tại bị chặn `BQ_DATA_DUPLICATES`. |
| 3. Training production | **BLOCKED:** 6 khóa `MULTI_ITEM` chưa có quy tắc; sau nâng cấp, giờ mở bán còn chưa nạp cho tới khi backfill. |
| 4. Model mới được promote | **Không.** Model đang dùng giữ nguyên. |

**Vì sao dừng.** Bảng nguồn `demand_planing_lightgbm` được tạo lại lúc **22:18:39** tối nay, sau buổi diễn tập. Bảng mới:

- có thêm cột `customer_id`; còn 8.961.545 dòng (ít hơn 21 dòng);
- có **307 dòng `WAIT_TO_CONFIRM` không có `so_code`** (12/07, 15/10, 16/10, 18/10, 19/10);
- trên 16/10 và 19/10, 67 dòng trong số này giống nhau ở **mọi cột đã ánh xạ**: 18 nhóm, 49 dòng thừa.

Kiểm tra chỉ đọc cho thấy mỗi dòng trong một nhóm thuộc một `customer_id` khác nhau. Như vậy đây là đơn của các khách hàng khác nhau, chỉ "trùng" vì thiếu mã đơn. Theo quy tắc đã duyệt (dòng giống nhau ở mọi cột ánh xạ thì chặn, báo cáo, sửa tại nguồn), **mọi lần đọc có 16/10 hoặc 19/10 đều bị chặn, không ghi gì.** Điều này áp dụng cho:

- backfill 01/01–19/10 tối nay;
- **D-1 06:00 sáng mai** (cửa sổ 16–20/10), dù chạy 1.2.8 hay 1.2.9.

Nâng cấp mà không backfill được thì phương án A không còn giữ được:

- Lần D-1 thành công đầu tiên (ví dụ sau khi nguồn được sửa sáng mai) sẽ chốt toàn bộ lịch sử theo các lần nạp cũ.
- Để tránh, phải tắt D-1.
- Ngày mai thẻ KPI chính sẽ trống ("Chưa có actual đã chốt").
- Training bị chặn vì giờ mở bán chưa nạp.

Tức là kém dùng hơn 1.2.8 hiện tại. Vì vậy tôi **không nâng cấp tối nay**: không đổi lịch, không tắt D-1, không đổi quy tắc chặn hay ánh xạ. Bảng nguồn vẫn đang được theo dõi tới 04:15 (mục 3); nếu nguồn được sửa kịp, tôi kiểm lại cổng rồi mới quyết định.

**Việc cần làm để phát hành:** sửa nguồn sao cho các dòng `WAIT_TO_CONFIRM` có mã đơn (hoặc một khóa phân biệt được), rồi chạy chuỗi ở mục 15. Toàn bộ chuỗi mất khoảng 1 giờ và phải xong trước lần D-1 kế tiếp.

## 2. Trạng thái trước / sau

| | Trước (22:55) | Sau (21/10 00:00) |
|---|---|---|
| Production | 1.2.8, schema 6, app pid 10884, proxy 16144, tunnel 35236 | **Không đổi** (GET + precheck chỉ đọc) |
| `storage.json` | `8D79DBDDC960B10964F3B137F352D9AD54D39F08C52EF841418781ED00FDE047` | Như trước |
| DB production | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` | Chỉ được đọc bằng backup API (`mode=ro`) cho các bản sao |
| Repository | `main`, HEAD `0da73b6` (1.2.8), 86 file chưa commit | `main`, HEAD `a9486bb` (tài liệu) trên `15d4f4b` (Release 1.2.9). Working tree sạch. Đi trước `origin/main` 28 commit, **chưa push**. |
| Gói | – | `dist\DemandForecast-1.2.9-win64-portable.zip`, 92.343.940 byte, SHA-256 `B705F3DFB5F22C0947C558F7EBA4CC5BBB51D5B81D267E837227EB22A60162BB`, build 23:31 từ `15d4f4b` |

## 3. Lịch chạy (đọc từ production bằng GET `/api/schedules`, khớp bản scheduler đang nạp)

| Luồng | Trước (bản sao lúc 21:22) | Hiện tại (scheduler nạp lại 23:05–23:06) | Lần chạy kế tiếp |
|---|---|---|---|
| D-1 | thăm dò từ 03:00, dự phòng 05:00 | **06:00, dự phòng 06:30**; thăm dò mỗi 30 phút; tối đa 4 lần; trễ tối đa 20 phút | 21/10 06:00 |
| D-0 | 08–18 mỗi 2 giờ | Giữ nguyên | 21/10 08:00 |
| Training | 09:00, không chạy bù | Giữ nguyên | 21/10 09:00 |
| Sao lưu forecast cuối ngày / chốt cuối ngày | 23:55 / 23:59 | Giữ nguyên | 20/10 23:55 / 23:59 |

- Giờ là giờ Việt Nam. Ứng dụng không có lịch backfill riêng: backfill luôn chạy tay, sau một preview READY. "Lịch backfill mới" trên thực tế là D-1 được dời sang 06:00.
- **Cửa sổ an toàn:** từ khoảng 00:05 (sau lần chốt 23:59) tới trước 06:00. Diễn tập cho thấy toàn bộ chuỗi cần khoảng 1 giờ:
  - nâng cấp khoảng 6 phút;
  - preview khoảng 8 phút, backfill khoảng 13,5 phút, chốt khoảng 2,5 phút;
  - kiểm tra khoảng 15 phút.

  Cửa sổ đủ cho cả thời gian thử lại.
- **D-1 chạy trước backfill:** không xảy ra tối nay vì chưa nâng cấp. Bản 1.2.8 không chốt gì. D-1 lúc 06:00 sẽ bị chặn bởi các dòng trùng nếu nguồn chưa sửa.
- **Theo dõi nguồn:** một tác vụ chỉ đọc kiểm metadata bảng nguồn mỗi 5 phút (không truy vấn, không tốn byte) tới 04:15: tới 00:00 nguồn chưa được tạo lại (lần cuối 22:18:39). Nếu nguồn được tạo lại trước 04:15, tôi chạy lại preview chỉ đọc trên một bản sao mới. Chỉ khi preview READY và số liệu giải thích được, tôi mới nâng cấp và backfill (khoảng 1 giờ, xong trước 06:00). Nếu không, production giữ 1.2.8..

## 4. Backup và rollback

| Mục | Kết quả |
|---|---|
| Bản sao lưu production mới nhất | `D:\Buymed\Lightgbm AI\backups\backup-20261019-200655-cli.zip` (85.969.686 byte, SHA-256 `BFCF35CE19A1E5C4C6E26BED6487D864E73A3D9036DF57E9C3CD299731093132`): zip test OK, 11 mục, DB integrity `ok`, schema 6. Khi nâng cấp, `deploy-upgrade` tự tạo và kiểm thêm một bản mới. |
| Rollback 1.2.9 → 1.2.8 | Phải khôi phục bản sao lưu trước nâng cấp. 1.2.8 từ chối schema 9 (đã kiểm hai lần). Diễn tập bằng mã nguồn (đợt 8) và bằng gói (mục 5): restore bằng `restore.ps1` của 1.2.8 rồi `rollback-version -To 1.2.8`: DB giống hệt trước nâng cấp; app không phản hồi 180 giây |
| Checkpoint | Trước phát hành: `checkpoints\checkpoint-20261020-v129i-prerelease.zip`, SHA-256 `0A37954C4E1D1BBC850A63A2710061D7E240391E907835232D986F606A3D6C97`, 90 mục; đã giải nén và so từng byte với working tree. Cuối đợt: `checkpoints\checkpoint-20261021-v129-release-night.zip` (1.988.523 byte, 61 mục), SHA-256 `DF1711CE91BBA6677A87A155773590BE9D6DFE390476976776AC21EFC1DF2F0E`. Gồm git bundle của 28 commit chưa push (`git bundle verify` đạt), 2 báo cáo / CSV mới, script và kết quả của scratchpad p24, bằng chứng diễn tập r9. Không có DB, bản sao lưu hay chương trình cài đặt. Đã kiểm CRC, danh sách = manifest, hash từng file. |

## 5. Migration (diễn tập; production chưa chạy)

- **Bằng mã nguồn** (đợt 8, bản sao DB production lúc 21:22):
  - 6 → 9 trong 89,8 giây, gần như toàn bộ là sao lưu `pre-migration-v6`;
  - +2 bảng rỗng, +10 trigger;
  - mọi bảng cũ giữ nguyên nội dung trên các cột cũ; 5 cột mới của `demand_daily` đều NULL;
  - chạy lại không làm gì.
- **Bằng gói 1.2.9** (bản cài cô lập `scratchpad\r9`, cổng 8879, bản sao DB mới, scheduler tắt; cài gói 1.2.8 chính thức → `deploy-upgrade` 1.2.9 → rollback bằng restore): 

| Bước | Kết quả |
|---|---|
| Điều kiện trước | Production còn chạy (10884 / 16144 / 35236) và trả 1.2.8; không có job nào chạy; hash gói 1.2.8 và 1.2.9 đúng; bản sao DB schema 6, `data-check` không FAIL |
| Cài gói 1.2.8 chính thức (cô lập) | Chạy trên cổng 8879, thư mục dữ liệu nằm trong `r9`, scheduler tắt |
| `deploy-upgrade 1.2.9 -CheckOnly` | exit 0, không ghi gì |
| `deploy-upgrade 1.2.9 -ConfirmToken UPGRADE-1.2.9` | exit 0. Tổng 601,3 giây, **app không phản hồi 284,3 giây**. Có sao lưu online trước nâng cấp (`backup-20261020-234003-manual.zip`). |
| Sau nâng cấp | Schema 9. `actual_finals` / `actual_final_values` mới và rỗng; +10 trigger, không trigger nào bị xóa. Mọi bảng giữ nguyên nội dung trên các cột của schema 6 (chỉ `audit_log` +1, `schema_migrations` 6 → 9). 5 cột mới đều NULL. File model và mọi cấu hình JSON giữ nguyên; 5 luồng lịch chạy giữ nguyên (D-1 06:00 / 06:30). `data-check` WARN như trước. |
| Trạng thái hệ thống | Mọi giá trị giống 1.2.8, trừ một trường **mới** `data_window.start_rule = "WINDOW_START"`. Script đã so cả trường mới nên ghi FAIL; về nội dung là đạt. |
| Lịch sử / API | 0 ngày chốt, 0 ngày bị chặn ngay sau nâng cấp; KPI `NO_FINAL_ACTUAL` (tạm tính 58.299, chốt 23:59 148.270 ở nhóm riêng). Excel vi / en trả 200. Preview backfill = `NONE`. UI đóng gói là bản 1.2.9. |
| Rollback | `rollback-version -To 1.2.8 -CheckOnly` **từ chối** (exit 3, schema 9 > 6). Dừng 1.2.9 → `restore.ps1` của 1.2.8 (140,2 giây, có sao lưu an toàn `pre-restore`) → DB schema 6 → `rollback-version -To 1.2.8` (exit 0). Tổng 187,6 giây, app không phản hồi 180,4 giây. |
| Sau rollback | Mọi bảng **giống hệt** lúc ngay trước nâng cấp; model, cấu hình, lịch chạy và trạng thái như trước; `data-check` WARN |
| Dọn dẹp | Chỉ dừng app diễn tập; production còn chạy, vẫn 1.2.8; hash của hai gói không đổi |
| **Tổng** | **33/34 PASS**; kiểm tra còn lại khác ở đúng một trường mới (giải thích ở trên) |

## 6. Backfill

| | Diễn tập 21:48 (nguồn 15:05) | Nguồn hiện tại (22:18) |
|---|---|---|
| Kết quả preview 01/01–19/10 | READY: 8.961.566 dòng đọc, 0 trùng hoàn toàn; 1.357.889 khóa; tổng 42.011.108 (−12.109, −0,029% so với số đang lưu); 344 mới / 213 đổi / 772 bị nguồn bỏ | **BLOCKED `BQ_DATA_DUPLICATES`** (preview chỉ đọc trên bản sao cô lập `p23\n`, 23:09): 8.961.545 dòng; tổng 42.009.962; 18 nhóm / 67 dòng / 49 dòng thừa; không ghi gì |

- Phạm vi ngày đúng 01/01–19/10. Hôm nay không bao giờ nằm trong cửa sổ, vì D-1 / backfill chỉ đọc tới `today_vn() − 1`.
- Các dòng trùng đều có `so_code` NULL và `order_status = WAIT_TO_CONFIRM`:
  - 16/10 HN: 4 nhóm (3 dòng mỗi nhóm);
  - 19/10 BD / HN: 14 nhóm (2–8 dòng mỗi nhóm).
- Trong mọi nhóm, số `customer_id` khác nhau bằng số dòng của nhóm; `seller_class` và `refresh_time` giống nhau.
- Toàn bảng có 307 dòng không có `so_code`, đều `WAIT_TO_CONFIRM`: 19/10 250 dòng (3.555 đơn vị, 35 khách); 18/10 8; 16/10 37 (2.630 đơn vị); 15/10 6; 12/07 6.
- Kết quả truy vấn chỉ đọc `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p24\bq_dups.json` (cũng có trong checkpoint cuối) chứa mã `customer_id` dạng số của 18 nhóm để nhóm nguồn tra cứu. Đây là file local, không đưa vào Git hay báo cáo này.
- Báo cáo dòng trùng (.xlsx, do ứng dụng tạo): `C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p23\n_reports\bigquery-duplicates\bq-trung-lap_2026-01-01_2026-10-19_20261020-230907.xlsx`
- **Các cách gỡ (bạn quyết định; tôi không làm cách nào):**

| Cách | Tác động |
|---|---|
| **(1) Sửa nguồn (đề xuất):** các dòng `WAIT_TO_CONFIRM` có `so_code`, hoặc một mã đơn tạm phân biệt được | Không đổi gì ở ứng dụng; backfill và D-1 chạy như diễn tập |
| (2) Đưa `customer_id` vào ánh xạ như cột tham chiếu | Phá được "trùng" vì khách khác nhau. Nhưng là đổi ánh xạ: hash đổi, production mode tắt cho tới khi kiểm tra lại toàn kỳ, D-1 kế tiếp nạp lại toàn bộ. Không làm tối nay. |
| (3) Đổi quy tắc sang `DROP_EXACT` | **Không nên:** bỏ 49 dòng là đơn thật của khách khác nhau, làm thiếu nhu cầu |
| (4) Backfill 01/01–15/10, bỏ 16/10 và 19/10 | Lệch phương án A: 16–19/10 sẽ bị chốt theo lần nạp cũ 20/10 12:30, không theo nguồn hiện tại. Chỉ làm khi bạn chấp nhận. |

## 7. Chốt actual

- **Production:** chưa chạy (vẫn 1.2.8; 1.2.8 không chốt gì).
- **Diễn tập** (đợt 8, nguồn 15:05):
  - 292 ngày, 1.357.889 dòng, 42.011.108 đơn vị; mọi ngày truy về lần nạp backfill;
  - lần `--apply` thứ hai không ghi gì; đường CLI và đường hook cho kết quả giống hệt;
  - 14/14 thao tác sửa / xóa bị trigger chặn;
  - nguồn đổi số, D-1 lỗi, lỗi giữa chừng rồi chạy lại đều đúng thiết kế;
  - forecast và lịch sử không đổi; hôm nay vẫn tạm tính.

  Chi tiết trong `reports\demandforecast_upgrade_backfill_rehearsal_20261020.md`.
- Trên gói 1.2.9 vừa nâng cấp (chưa backfill), chạy thử chốt chỉ đọc: 292 ngày sẽ được chốt, 0 bị chặn. Đây là con số mà một D-1 chạy **trước** backfill sẽ chốt theo lần nạp cũ, nên thứ tự của phương án A là bắt buộc.

## 8. Dashboard / API / Excel

- **Diễn tập bằng mã nguồn** (đợt 8): KPI chỉ trên dòng đã chốt, khớp phép tính độc lập, kể cả khi lọc FC BD / HN. Tạm tính và chốt 23:59 ở nhóm riêng. Excel H4 vi / en. Có 4 ảnh chụp trong `reports\demandforecast_upgrade_backfill_rehearsal_20261020_screens\`.
- **Trên gói 1.2.9** (bản cài cô lập): API lịch sử, Excel vi / en, endpoint preview backfill và UI 1.2.9 hoạt động trên DB thật đã nâng cấp. KPI `NO_FINAL_ACTUAL` cho tới khi có ngày được chốt.
- **Production** vẫn hiển thị theo 1.2.8 (nhãn tạm tính / chốt 23:59, KPI trộn như trước).

## 9. Sáu khóa MULTI_ITEM

Xác minh lại trên bảng nguồn hiện tại (22:18) bằng truy vấn chỉ đọc. Kết quả khớp audit đợt 5 và bản sao đã chốt ở đợt 8.

- Mỗi khóa là SKU × FC × ngày có 2 item; mỗi item có một giá trị giờ mở bán riêng, khác nhau.
- Mọi dòng đều có giá trị (không dòng nào thiếu giờ); trạng thái `COMPLETED`, riêng COU-STR-001.1 có thêm `DELIVERED`.
- Provenance: bảng nguồn `demand_planing_lightgbm`, `refresh_time` 22:18:21 20/10.

| # | Ngày | FC | SKU | Item: số dòng / số đơn, số lượng, giờ | Tổng | MAX / MIN / TB theo số lượng / TB theo dòng (chỉ để tham khảo) |
|---|---|---|---|---|---|---|
| 1 | 09/02 | HN | `MEDX.DMTS-HOA-BAO-002` | .1: 1 / 1, 2, 23,92 h · .2: 3 / 3, 6, 24 h | 8 | 24 / 23,92 / 23,98 / 23,98 |
| 2 | 10/02 | HN | `MEDX.2LJ61PGE` | .1: 1 / 1, 1, 21,16 h · .3: 1 / 1, 10, 24 h | 11 | 24 / 21,16 / 23,74 / 22,58 |
| 3 | 02/03 | BD | `MEDX.DMTS-STA-LOS-002` | .1: 17 / 17, 78, 5 h · .2: 1 / 1, 10, 24 h | 88 | 24 / 5 / 7,16 / 6,06 |
| 4 | 02/03 | BD | `MEDX.SOP-NEO-001` | .1: 2 / 2, 2, 1,7 h · .2: 1 / 1, 1, 24 h | 3 | 24 / 1,7 / 9,13 / 9,13 |
| 5 | 26/08 | BD | `MEDX.COU-STR-001` | .1: 7 / 7, 40, 23,72 h · .2: 1 / 1, 2, 24 h | 42 | 24 / 23,72 / 23,73 / 23,75 |
| 6 | 26/08 | BD | `MEDX.D6TABCV8` | .1: 3 / 3, 3, 22,85 h · .2: 1 / 1, 1, 18,22 h | 4 | 22,85 / 18,22 / 21,69 / 21,69 |

**Phân loại:** `MULTI_ITEM` vì các dòng của khóa có giờ khác nhau, nhưng mỗi item chỉ có một giá trị và số giá trị bằng số item (`data/open_hours.cell`). Ứng dụng không tự chọn một giá trị.

**Tác động:**

- 6 dòng / 156 đơn vị trên 1.357.889 dòng / 42 triệu đơn vị.
- Kiểm tra giờ mở bán của cửa sổ huấn luyện không đạt, nên **training BIGQUERY dừng với `OPEN_HOURS_INVALID`** (đã kiểm trên bản sao sau backfill).
- Việc nạp D-1, việc chốt số lượng (cả 6 khóa đã được chốt trong diễn tập) và dashboard không bị chặn.

**Các lựa chọn (không chọn thay bạn):**

| Lựa chọn | Ưu | Nhược / tác động |
|---|---|---|
| 1. Khôi phục nguồn / ánh xạ để có một giá trị giờ cho mỗi SKU × FC × ngày | Đúng dữ liệu, không cần quy tắc trong app | Phụ thuộc nhóm nguồn |
| 2. Sửa logic nguồn nếu chứng minh được lỗi (ví dụ 5 h và 1,7 h ở item .1 ngày 02/03) | Sửa tận gốc | Cần bằng chứng từ hệ thống bán hàng |
| 3. Quy tắc nghiệp vụ do bạn duyệt (MAX, MIN, TB theo số lượng…) | Mở khóa training ngay | Mỗi quy tắc cho giá trị khác nhau: chênh nhiều nhất là khóa 3 (5–24 h) và khóa 4 (1,7–24 h); cần thêm code, test và một lần backfill lại |
| 4. Giữ trạng thái chặn và loại khỏi phạm vi training | Không bịa giá trị | Code hiện không loại riêng từng dòng. Cách duy nhất có sẵn là dời ngày bắt đầu cửa sổ sang 27/08: chỉ còn 54/292 ngày, 158.194/1.357.889 dòng (mất 88% lịch sử). Loại riêng 6 dòng cần code mới. |

## 10. 931 trường hợp nhu cầu qua combo SKU

- **Nguồn so khớp:** file audit `reports\demandforecast_zero_open_hours_with_orders_20261020.xlsx`; SHA-256 `A9640616…1025` đúng như đã báo cáo. Sheet Source_Evidence có 3.017 dòng nguồn, 2.847 đơn, 104 SKU.
- **Cách so khớp (truy vấn chỉ đọc):**
  - `fa_dim_order` để đổi `so_code` sang `order_id`: khớp 2.847/2.847 đơn;
  - `fact_fin_order_combo_unnested`: thành phần combo theo đơn (`main_sku_code`, `is_combo`, `quantity`).
- **Giới hạn của bảng combo:** bảng này dừng ở **09/07/2026** (lần ETL cuối 09/07).
- **Tín hiệu cho giai đoạn sau 09/07:** dùng `fact_order_item.combo_quantity` có giá trị và không có dòng trong `fact_order_item_sku_combo`. Tín hiệu này được hiệu chỉnh trên 937 dòng đã có nhãn (01/05–09/07) và khớp 100%: 893/893 dòng qua combo, 44/44 dòng trực tiếp (đều là quà tặng).

| Phân loại | Số dòng | Đơn vị | Số khóa | Bằng chứng |
|---|---|---|---|---|
| Qua combo (bảng combo, ≤ 09/07) | 1.865 | 15.299 | 713 (1 khóa có cả dòng trực tiếp) | Có `main_sku_code` khác SKU; 1.829 dòng có số lượng khớp đúng dòng nguồn, 36 dòng có số trong bảng combo lớn hơn |
| Qua combo (tín hiệu đã hiệu chỉnh, sau 09/07) | 975 | 9.796 | 175 | `combo_quantity` có giá trị, không có dòng SKU trực tiếp; mức tin cậy thấp hơn nhóm trên |
| Trực tiếp (≤ 09/07) | 112 | 364 | 25 (+1 khóa có cả hai) | `is_combo = 'no'`; trong 01/05–09/07 đều là quà tặng (GIFT) |
| Quà tặng (sau 09/07) | 43 | 43 | 12 | `item_type = GIFT` |
| Trực tiếp NORMAL / DEAL (sau 09/07) | 22 | 40 | 7 | Có dòng SKU trực tiếp, không có `combo_quantity` |
| Chưa đủ bằng chứng | 0 | 0 | 0 | – |
| **Tổng** | **3.017** | **25.542** | **931** | Mọi khóa đều có ít nhất một nhóm ở trên |

- **Bảng phân loại từng dòng:** `reports\demandforecast_combo_931_classification_20261020.csv`; 3.017 dòng; SHA-256 `6EE8FFF39F3B4C843F4E50042E3DE4EF594D2C8E9B9C0CE4FE65EEC8B522AB75`; có mã đơn, không có mã khách.
- **Kết luận dữ liệu:** khoảng **98%** đơn vị của 931 khóa (25.095/25.542) có bằng chứng là đến từ combo: 15.299 theo bảng combo, 9.796 theo tín hiệu đã hiệu chỉnh. Điều này khớp nhận định của bạn.
- **Phát hiện thêm:** nhu cầu qua combo không chỉ có ở các ngày giờ mở bán = 0. Ví dụ `MEDX.2110dcfad25e` nhận 181.806 đơn vị qua combo `MEDX.CJ4HR2AX` trong 04–23/06. Phạm vi của quy tắc combo (chỉ 931 khóa hay toàn bộ nhu cầu thành phần combo) là quyết định nghiệp vụ.
- **Thử nghiệm offline (loại phần qua combo khỏi target của candidate): CHƯA CHẠY.**
  - Phân loại đã sẵn sàng, nhưng tập dữ liệu của bản sao cần được nạp lại từ nguồn hiện tại, và việc nạp lại bị chặn bởi cùng các dòng trùng (mục 6).
  - Chạy trên tập dữ liệu cũ (nguồn 15:05) thì không nhất quán với `customer_id`.
  - Tối nay ưu tiên phát hành, và RAM trống thấp khi production đang chạy.
  - Không đổi target, nhãn hay actual nào.

## 11. customer_id

| Kiểm tra (chỉ đọc, chỉ đếm, không xuất mã khách) | Kết quả |
|---|---|
| Có trong nguồn | Có từ bản tạo lại 22:18, kiểu INTEGER. Bảng D0 chưa có cột này. |
| Độ phủ | 8.961.545/8.961.545 dòng có giá trị (0 NULL) |
| Số khách / số đơn | 35.055 khách, 968.275 đơn; **mỗi đơn đúng 1 khách** (0 đơn có hơn 1 khách) |
| Theo tháng | 21–26 nghìn khách hoạt động mỗi tháng; khách mới giảm từ 2.391 (02) còn 295 (01–19/10). Con số 26.358 của tháng 01 là do dữ liệu bắt đầu từ 01/01. |
| Theo SKU × FC × ngày | Trung vị 1–2 khách; 41,9% số ngày-chuỗi chỉ có 1 khách (5,5% tổng đơn vị); có ngày tới 759 khách |
| Lực lượng | 35 nghìn giá trị: không dùng được làm feature thô ở grain SKU × FC × ngày. Thiết kế của 1.2.9 (`data/customers.py`, tắt mặc định) chỉ dùng số đếm (`customer_count`, khách quay lại trong 90 ngày, khoảng cách ngày); mã khách không rời BigQuery. |
| Rò rỉ dữ liệu / sẵn có khi dự báo | Feature ở mốc T chỉ đọc các ngày trước T (`features.features_at`), nên không có đơn từ T trở đi. Số đếm của ngày d chỉ biết sau khi ngày d kết thúc, phù hợp với D-1. |
| Khách mới / chưa thấy | Feature là số đếm theo chuỗi, không phải danh mục khách, nên không có vấn đề "giá trị chưa thấy". Khách mới làm tăng `customer_count`, không tăng số khách quay lại. |
| Thử nghiệm baseline vs candidate | **CHƯA CHẠY:** cần nạp lại bản sao với ánh xạ `customer_id`, việc này bị chặn bởi cùng các dòng trùng (mục 6). Production: `customer_id` vẫn **OFF** (`customer_id_column` trống, `feature_customer = false`). |

## 12. Model

- **Price ON** (`feature_price = true` trong bản sao cấu hình production); `customer_id` OFF; không đổi feature hay ngưỡng nào.
- **Training production:** không chạy tối nay. Sau khi nâng cấp, training BIGQUERY bị chặn (`OPEN_HOURS_INVALID`) vì 6 khóa `MULTI_ITEM` (và vì giờ mở bán chưa nạp nếu chưa backfill).
- **Model đang dùng:** giữ nguyên (training `TRN-20261020054540-D7EEF6`, forecast `FCR-20261020082402-A42C91`, nguồn BIGQUERY; đọc bằng GET lúc 00:00). Không promote.

## 13. Test

| Loại | Kết quả |
|---|---|
| QA của `release.ps1` trên commit `15d4f4b` (unit + tích hợp với DB tạm / FakeBQ) | Backend **647 passed / 10 skipped / 0 failed** (466 giây); frontend **24 file / 152 passed**; typecheck và build đạt; gói được kiểm (SHA, VERSION, BUILD-INFO) |
| 10 test skipped | Test BigQuery thật, chỉ chạy khi đặt `DF_REAL_BQ=1`. Đọc BigQuery thật đã có trong các truy vấn chỉ đọc của đợt này. |
| Test tập trung (đợt 8) | 165 passed |
| Diễn tập bằng mã nguồn trên bản sao (đợt 8) | Đạt: migration, backfill, chốt, khôi phục, dashboard |
| Diễn tập bằng gói trên bản cài cô lập | **33/34 PASS**, 1 kiểm tra khác ở trường mới `data_window.start_rule` (mục 5) |
| Precheck production (`deploy-upgrade -CheckOnly`) | exit 0, "PRECHECK OK", không thay đổi gì (`storage.json` như trước) |
| Lint | Chưa được cấu hình |

## 14. Git và working tree

- **Nhánh `main`, commit local `15d4f4b`** ("Release 1.2.9: …"): 89 file, gồm 86 file nguồn của 8 đợt 1.2.9 và 3 file phiên bản (`backend/app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json`).
- **Kiểm tra trước commit:**
  - không có file dữ liệu, báo cáo hay bí mật (2 chuỗi giống bí mật là dữ liệu giả có sẵn trong test từ trước);
  - không file nào trộn kiểu xuống dòng; không có PS1 nào đổi;
  - message không có CR.
- **Commit local `a9486bb`** ("Docs: 1.2.9 release-night checkpoint …"): chỉ `docs/CHECKPOINT.md`. Gói vẫn là bản build từ `15d4f4b`.
- **Không push.** Nhánh `main` đi trước `origin/main` (con số trong mục 2). Không stash, không reset, không xóa file nào. Việc dọn gói cũ chỉ chạy thử (không xóa).

## 15. Việc còn tồn đọng

| # | Việc | Ai | Bước tiếp theo |
|---|---|---|---|
| 1 | Dòng `WAIT_TO_CONFIRM` không có `so_code` (bị coi là trùng) | Nhóm nguồn / chủ hệ thống | Sửa nguồn (mục 6, cách 1), hoặc chọn cách 2 / 4 |
| 2 | Nâng cấp 1.2.9 + backfill + chốt (phương án A) | Claude, sau khi nguồn sạch | Một lượt, ngoài 23:55 / 23:59 và trước D-1 06:00: precheck → `deploy-upgrade … -ConfirmToken UPGRADE-1.2.9` → preview → xem số → backfill (tự chốt) → kiểm tra (mục 7–8) |
| 3 | 6 khóa `MULTI_ITEM` | Chủ hệ thống | Chọn lựa chọn 1–4 (mục 9) |
| 4 | Quy tắc combo (phạm vi, áp dụng cho target của candidate) | Chủ hệ thống | Duyệt phân loại (mục 10), rồi chạy thử nghiệm offline |
| 5 | `customer_id` | Chủ hệ thống | Sau khi nguồn sạch: chạy thử nghiệm offline (baseline vs candidate, cùng các fold, Price ON) |
| 6 | D-1 06:00 sáng mai | – | Sẽ bị chặn `BQ_DATA_DUPLICATES` nếu nguồn chưa sửa (cả 1.2.8). Thực tế 20/10 vẫn tạm tính cho tới khi một D-1 thành công. |
| 7 | Hiển thị tiếng Anh "1 days" | Claude | Lỗi nhỏ, sửa ở bản sau |

## 16. Sử dụng ngày mai (21/10)

- **Ứng dụng: 1.2.8** như hôm nay.
  - Trên máy này: `http://127.0.0.1:8765`; kiểm tra sức khỏe `http://127.0.0.1:8765/api/health` trả `{"ok": true, "version": "1.2.8"}`.
  - Link xem từ xa giữ nguyên: tunnel 35236 không bị đụng tới.
- **Dữ liệu:**
  - Lịch sử đã nạp tới 19/10 (lần D-1 tay 20/10 12:30).
  - D-0 chạy như cũ từ 08:00.
  - D-1 06:00 sẽ thất bại nếu nguồn chưa sửa, khi đó dữ liệu vẫn dừng ở 19/10.
  - Training 09:00: chờ D-1 thành công trong ngày.
- **Màn hình "Lịch sử Forecast & Thực tế"** vẫn theo quy tắc 1.2.8:
  - 18/10 và 19/10 là "Đã chốt – cần xác minh"; 20/10 và 21/10 là "Tạm tính".
  - KPI 1.2.8 trộn các nhóm: dòng này **chưa** phải số đã chốt.
  - "Thực tế đã hoàn tất" (đóng băng) chỉ xuất hiện sau khi 1.2.9 được nâng cấp và backfill xong.
