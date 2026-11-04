# Nhật ký quyết định của chủ dự án

Mỗi mục ghi ngày, quyết định và phạm vi, theo đúng lời chủ dự án. Mục mới thêm ở cuối. Quyết định cũ không sửa; quyết
định thay thế ghi thành mục mới và nêu mục bị thay.

## 2026-11-02 – Đồng bộ lịch sử, cấu trúc tài liệu, dọn dung lượng, RAM

* **A. Đồng bộ lịch sử theo nguồn (FOLLOW_SOURCE).** Các dòng BI đã xoá là đơn huỷ / trả, không phải nhu cầu. Thứ tự:
  sao lưu + thử khôi phục -> xem trước 01/01–28/10 (khoá phiên bản nguồn trước và sau) -> chốt chặn -> áp dụng ->
  đối chiếu từng ngày × kho -> data-check (history_source_drift phải hết).
  * Chốt chặn: tổng đơn vị bị bỏ <= 0,2 %; không có khoá nguồn có mà DB thiếu; liệt kê ngày mất > 5 % (cho phép nếu nằm
    trong 1.273 khoá đã báo). Chốt chặn hỏng hoặc phiên bản nguồn đổi: KHÔNG áp dụng, báo.
  * Không chồng lên D3 hay job production; xong trước 23:45, ngoài 00:45–03:00, nếu không thì sau 03:00.
  * Kế hoạch 1.4.1: đồng bộ lại 120 ngày mỗi tuần sau D-1 Chủ nhật, ngoài giờ học; tổng <= 0,5 %, một ngày mất > 5 % thì
    dừng và báo; báo số dòng và đơn vị thay đổi.
* **B. Cấu trúc lại tài liệu .md** theo bảng 1.3 (reports\don-dep-20261102\BANG_1_3_FILE_MD.md), sau D3, trên branch
  feature/san-xuat-chon-mo-hinh-20261101, commit cục bộ, chạy lại test. AGENTS.md và CLAUDE.md ở gốc, trỏ tới
  docs\README.md; CLAUDE.md @import quy tắc dữ liệu từ docs\01_quy_tac. File .md của reports\ chuyển vào docs\; dữ liệu
  parquet/zip ở lại reports\ (ngoài Git). Không sửa migration đã áp dụng; để lại dòng "đã chuyển tới …" ở đường dẫn cũ.
  Mọi PREREGISTRATION.md giữ nguyên từng byte trong docs\_luu_tru, SHA ghi trong file gộp.
* **C. Dọn dung lượng** sau D3, không bao giờ xoá đệ quy qua junction: danh sách XOÁ NGAY; prereg-fast, prereg-v2,
  prereg-v3, backtest-20260601 xoá file dữ liệu (parquet, csv, zip, order_lines), giữ .md và file kết quả; checkpoints
  giữ 2 bản mới nhất; xoá 9 bản cài cũ, giữ 1.3.1 và 1.2.14; bản sao d3 xoá khi D3 đạt VÀ đã cài 1.4.0; giữ g1 tới khi
  xong 1.4.1; báo dung lượng trước / sau.
* **D. RAM (bảng O3)** mục 1, 3, 4, 6 vào 1.4.1, mỗi mục có chứng minh kết quả trùng. Không vào 1.4.0. (Mục 4 được thay
  bởi quyết định 2026-11-03 bên dưới.)
* **Học tay** TRAIN_PUBLISH JOB-20261102100511-ADE8A8 (17:05) do chủ dự án chạy. KHÔNG promote model của job này.
* **Lịch production giữ nguyên:** D-1 01:10, dự phòng D-1 01:15, học lại 01:20 (BI cập nhật dữ liệu lúc 01:00). Không
  tự đổi lịch; nếu lỗi chỉ báo nguyên nhân. 1.4.0 giữ đúng lịch này (so mục lịch trước / sau cài, phải trùng tuyệt đối);
  học lại hằng tuần thứ Hai ngay sau D-1; hạn xuất Excel 06:30.
* **D3 chậm – chọn phương án B:** đọc giờ mở bán bằng quét tuần tự (`NOT INDEXED`) và tính nhóm cố định trước; điều
  kiện: đọc cũ / mới trùng từng ô trên bản sao D3, sau D3 vẫn giữ ngưỡng gốc, ghi thời gian nạp và đỉnh bộ nhớ, có test,
  tester và reviewer trước khi đóng gói.

## 2026-11-03 – Kế hoạch chốt cài 1.4.0 sáng 04/11

Thay mọi kế hoạch ưu tiên trước. Giữ nguyên: các quyết định đã duyệt của kế hoạch 1.4.0 (B1–B10, T1–T10), lịch
production (D-1 01:10, dự phòng 01:15, học lại 01:20), quy tắc dữ liệu trong CLAUDE.md.

* **Dừng D3 lúc 00:06** (duyệt 03/11): replay 15/07 phình khoảng 9,8 GB mỗi lần, bị dừng vì bộ nhớ và chạy lại từ đầu
  19 lần, không tiến. Giữ model 7 mốc và dự báo ứng viên đã lưu.
* **Quy tắc vận hành.**
  * Khung tránh thao tác tay trên production: 23:45–00:15 và 00:45–03:00.
  * Việc nặng (học mô hình, replay / chọn mô hình, đo bộ nhớ quy mô đầy đủ, đồng bộ lịch sử, bộ test đầy đủ): mỗi lúc
    một. Việc nhẹ (xoá / di chuyển file, sửa .md, đọc / viết code, truy vấn chỉ đọc nhỏ): được song song với 1 việc nặng.
  * Bắt đầu việc nặng khi commit trống >= 3 GB; commit < 1,5 GB thì dừng ở điểm dừng; dừng vì bộ nhớ quá 3 lần liên
    tiếp ở cùng một bước: dừng hẳn và báo, không lặp.
  * Mọi lệnh chờ chạy nền phải báo khi xong, khi dừng và khi lỗi.
  * Chậm hơn mốc giờ quá 1 giờ: báo ngay kèm phương án. Báo tiến độ ngắn mỗi 60 phút và sau mỗi bước.
* **Lịch làm (giờ VN).**
  * B0 ngay: dừng D3. B1 03:00–03:45: kiểm tra lịch production đêm qua; đồng bộ lịch sử (quyết định A).
  * B2 03:45–07:00: học trước 12 mốc còn lại của D3 (15/09, 15/10), dùng lại 7 mốc của 15/07, CHỈ NẾU code học không bị
    bản sửa bộ nhớ B4 đụng tới; nếu có thì bỏ B2 và học lại sau B4. Điểm dừng sau mỗi mốc.
  * B3 song song, xong trước 10:00: dọn dung lượng (mục tiêu <= 12 GB; giữ DB production, sao lưu theo quy tắc giữ, g1,
    model / dự báo ứng viên của D3, reports\cai-tien-20261031\package\ và runner/code cho D3, bản cài 1.3.1 và 1.2.14,
    code, docs); quy tắc tự dọn scripts\ops\don_dep_dinh_ky.ps1 (mặc định chạy thử, Chủ nhật 22:00: sao lưu theo quy
    tắc giữ, Excel hằng ngày 90 ngày, log 30 ngày nén trước khi xoá, bản sao DB tạm xoá ngay khi xong, thử nghiệm đã
    đóng gói chỉ giữ package\ và .md; bản sao DB tạm từ nay ở D:\Buymed\tmp\); cấu trúc .md theo bảng 1.3 + docs\README.md;
    đề xuất seller_code của Avg Demand gửi trước 10:00.
  * B4 07:00–13:00: sửa bộ nhớ SEL2 (bắt buộc): log tiến độ, đo từng bước trên mẫu nhỏ rồi quy mô đầy đủ; đỉnh < 3 GB,
    kết quả trùng tuyệt đối với code cũ; gộp mục 4 bảng O3 (thay quyết định D cho mục này); đo sel2-day quy mô production
    trên g1 (đỉnh < 3 GB, xuất Excel < 60 phút); test + tester + reviewer; áp dụng giống hệt cho bản chụp D3 và worktree
    1.4.0. Mục 1, 3, 6 vẫn ở 1.4.1.
  * B5 13:00–17:00: sửa driver D3 (đủ khung tránh, điểm dừng giữa các bước, dừng hẳn khi lặp lỗi bộ nhớ); chọn mô hình +
    đối chiếu 15/07, 15/09, 15/10 bằng code cuối; báo từng ngày. Ngưỡng <= 1e-4 (LightGBM), <= 1e-9 (còn lại),
    model_used trùng.
  * B6 17:00–22:00 (sau D3 đạt và seller_code được duyệt): áp dụng seller_code, bộ test đầy đủ (1 tiến trình), đối
    chiếu D4 (công tắc khẩn cấp cho hành vi y hệt 1.3.1), commit cục bộ, đóng gói 1.4.0. KHÔNG cài.
  * B7 04/11 07:00–09:00, chỉ khi chủ dự án trả lời "CÀI": E1 (sao lưu -pre-1.4.0 + thử khôi phục, cài, health,
    data-check, lịch sau cài trùng tuyệt đối), E2 (học các mô hình LightGBM, chạy lại 35 ngày), E3 (xuất Excel đầu
    tiên). Không cài tự động ban đêm. Không đạt điều kiện nào: dừng, giữ 1.3.1, báo.

## 2026-10-17 – 2026-11-02 – Quyết định cũ chép từ CHECKPOINT.md (chép ngày 03/11/2026)

Chép nguyên văn (tiếng Anh như bản gốc) các quyết định / quy tắc của chủ dự án ghi trong
[03_van_hanh/CHECKPOINT.md](03_van_hanh/CHECKPOINT.md), theo dòng GIỮ + TÁCH của bảng 1.3. CHECKPOINT.md giữ nguyên các
mục này làm lịch sử batch; mục nào đã có quyết định mới hơn ở trên thì quyết định mới hơn được áp dụng.

* **2026-10-17, 1.2.1:** "owner asked to deploy: train catch-up policy SKIP set first (PUT /api/schedules/train)".
* **2026-10-17, 1.2.3:** sau sự cố một test ghi vào DB thật (`bigquery.production_enabled=true`): "owner chose to keep it
  ON".
* **2026-10-18, 1.2.6 blocker resolution:** "decisions B1 retention 90 days, B2 new flows OFF by default, F1 docs match
  runner.py".
* **2026-10-20, 1.2.9 đợt 3:** "the owner decision after S0-S5: skip S6, no more training, rerun the backend tests,
  report, checkpoint"; "customer_id not enabled"; S6 NOT RUN (owner decision).
* **2026-10-20, 1.2.9 đợt 5:** "Owner rule: the item_code suffix is the opening order across regions, not a region."
* **2026-10-20, 1.2.9 đợt 7:** "Owner rule: the actual of a completed day is finalized from the successful D-1 load and
  never changes."
* **2026-10-20, 1.2.9 đợt 8:** "Owner decisions: backfill first, then the first finalization; check data impact and
  provenance before finalizing; rehearse 6 -> 9 in isolation; report, commit is a separate step."
* **2026-10-20 tối, phát hành 1.2.9:** "plan A: upgrade -> preview -> backfill -> finalize the same evening. Commit
  authorized for the release scope only; no push. Price ON, customer_id OFF, D-0 schedule unchanged."; lịch "D-1 06:00 /
  fallback 06:30 / poll 30 min (owner change ~23:05, was 03:00 / 05:00)" (đã được thay bởi lịch ở mục 2026-11-02).
* **2026-10-21, MULTI_ITEM:** "training candidate allowed only when every gate passes, no promotion" – huấn luyện bị chặn
  ở Gate D (`OPEN_HOURS_INVALID`).
* **2026-10-21, 1.2.12:** "owner approved the MAX rule for the six blocked keys; deploy when every gate passes; no push,
  no schedule / target / Price / customer_id / promotion change".
* **2026-10-22, 1.2.13 đồng bộ lịch sử:** "target = gross demand at order creation; never reduce history only because an
  order disappears" (đã được thay bởi FOLLOW_SOURCE, mục 2026-11-02 A).
* **2026-11-02, 1.4.0:** "Kế hoạch T0–T10 rồi E1–E4 (chủ dự án duyệt 2026-11-02)."

## 2026-11-03 – Quyết định trong ngày (sau kế hoạch chốt)

* **03:28 – Đồng bộ lịch sử:** chốt "không mất giờ mở bán" sửa thành: số dòng mất giờ mở bán = đúng số dòng bị xoá VÀ
  không dòng nào còn lại bị mất giờ mở bán (now_missing = 0); các chốt khác giữ nguyên. Nguồn đổi -> xem trước lại.
* **~08:00 – Nguồn BI:** chủ dự án quên đặt giờ làm mới; từ nay BI dựng bảng lúc 01:00. Bảng nhu cầu phải được dựng
  SAU openhours_by_sku (bản dựng 04:10 trước bản giờ mở bán 07:10 làm ngày 02/11 trống giờ mở bán toàn bộ). Chạy tay D-1
  một lần (FOLLOW_SOURCE) và làm mới dự báo một lần bằng model đang dùng; KHÔNG học lại 1.3.1.
* **~08:40 – Mới, xong trong hôm nay:**
  * seller_code: bỏ đề xuất. Bảng Avg dùng một seller_code cho mỗi SKU × kho – lấy avg_demand theo SKU × kho như bảng
    đang có; một SKU × kho có hơn 1 dòng thì báo ngay, không tự chọn (1.4.0: cảnh báo AVG_DEMAND_MULTI_SELLER, SKU × kho
    đó không có số).
  * D3: chỉ đối chiếu 15/07 và 15/10 (bỏ 15/09); học các mốc cho 15/10 ngay khi B4 xong. Lệch ngưỡng ở bất kỳ ngày nào:
    DỪNG, không đóng gói.
  * Bộ test đầy đủ (1 tiến trình), tester, reviewer được chạy cùng lúc với D3 khi commit trống >= 5 GB (dưới 5 GB tạm
    dừng test, ưu tiên D3). Chuẩn bị sẵn gói trong lúc D3 chạy; chỉ còn bước đóng gói cuối khi D3 đạt.
  * Cài ngay hôm nay khi D3 đạt và gói sẵn sàng, sau khi chủ dự án trả lời "cài": E1 -> E2 -> E3 liền. Không cài trong
    23:45–00:15 và 00:45–03:00; E2 tới 00:45 chưa xong thì dừng ở điểm lưu, làm tiếp sau 03:00.
  * Điều kiện an toàn khi cài giữ nguyên: toàn bộ test đạt; sao lưu + thử khôi phục đạt; health và data-check sau cài
    đạt; lịch chạy sau cài trùng tuyệt đối trước cài. Không đạt: DỪNG, giữ 1.3.1, báo.
* **~10:00 – Khởi động lại app (cho phép riêng lần này):** job TRAIN_PUBLISH chạy tay JOB-20261103020545-364580 (09:05)
  dừng bằng cách khởi động lại app (1.3.1 không có lệnh dừng job; lý do: bộ nhớ căng, 1.4.0 sẽ thay quy trình học).
  Dừng 10:03:23 bằng scripts\stop.ps1 của bản cài, bật lại bằng scripts\remote\start-app-current.ps1 (PID 21968 ->
  27932); job ghi FAILED INTERRUPTED; health 1.3.1 OK; lịch chạy trùng tuyệt đối trước / sau (sha d419d8c947ba63c9);
  model đang dùng giữ MV-20261102-173855-6221; link xem từ xa HTTP 200; commit trống 7,2 GB.
* **Model MV-20261102-173855-6221:** do chủ dự án promote trên giao diện lúc đổi lịch chiều 02/11 (audit 18:04:37) –
  giữ nguyên. Không promote hay thay model nào thêm cho tới khi cài 1.4.0.
* **Đồng bộ lịch sử:** hoãn tới sau khi cài 1.4.0 (khi production rảnh), không chặn 1.4.0. Lượt 2 (08:08) dừng ở thử
  khôi phục vì job làm mới dự báo 08:12 ghi vào DB thật trong lúc sao lưu (số dòng lệch đúng phần job đó ghi).
* **Từ giờ tới khi cài xong 1.4.0:** chủ dự án không chạy tay job nào trên production; thấy job chạy tay mới thì báo
  ngay.
* **15:38 – Kết quả D3 (tái lập trên bản sao g1, code cuối 1.4.0):** ĐẠT cả 2 ngày theo ngưỡng gốc (LightGBM <= 1e-4,
  mô hình khác <= 1e-9, model_used trùng). 15/07: 103.502 dòng, sai khác lớn nhất 0,0 / 0,0, model_used lệch 0, 6 ứng
  viên sai khác 0,0. 15/10 (học mới 8 mốc 24/08–12/10): 104.307 dòng, sai khác 0,0 / 0,0, model_used lệch 0, 6 ứng viên
  sai khác 0,0. Bộ nhớ: replay 15/07 đỉnh 1.562 MB (trước sửa > 9,8 GB, không xong); D3 15/10 đỉnh 2.961 MB (lúc học
  V36). Mục 4 bảng O3 (khoá category) bỏ: tăng đỉnh bộ nhớ khi duyệt dòng. D3 15/10 dừng hẳn 1 lần lúc 11:56 (3 lần
  commit < 1,5 GB vì ứng dụng khác chiếm khoảng 18 GB); chạy lại 12:46 theo lệnh chủ dự án.
* **15:46 – sel2-day quy mô production** (bản sao, ngày 15/10, code 85625db): 441 s tổng, đỉnh bộ nhớ riêng 1.654 MB;
  nạp 172 s, 6 ứng viên 97 s, chọn + công bố 136 s, xuất Excel 104.307 dòng 5,4 s. Đạt (đỉnh < 3 GB, Excel < 60 phút).
* **~17:00–18:00 – Cài 1.4.0 (chủ dự án trả lời "CÀI"):** sao lưu backup-20261103-170118-pre-140.zip (không ghi trong lúc
  sao lưu) + thử khôi phục đạt; deploy-upgrade.ps1 UPGRADE OK 1.3.1 -> 1.4.0 (migration 0012); health 1.4.0, lịch chạy
  trùng tuyệt đối (sha d419d8c947ba63c9), storage.json không đổi. E2 bị chậm 2,5 giờ vì phiên điều phối không đặt lệnh
  chờ cho CANDIDATE_TRAIN (xong 18:21).
* **~21:00 – Chế độ vận hành mới (áp dụng cho mọi việc sau này; ghi cả trong CLAUDE.md):** tự chạy liên tục mọi bước đã
  duyệt, chỉ dừng hỏi khi chốt an toàn không đạt / phải xoá-ghi đè ngoài danh sách đã duyệt / thay đổi ảnh hưởng mua hàng;
  STATUS.md mỗi 10 phút, chat sau mỗi bước và >= mỗi 30 phút, thông báo Windows; chống kẹt (15 phút không tiến độ hoặc
  tiến trình chết -> báo; lỗi tạm thử lại 1 lần).
* **~21:00 – Đêm 03/11:** tạm tắt làm mới dự báo + xuất Excel tự động sau D-1 (D-1 01:10 vẫn chạy); E2 (giờ mở bán từ
  01/01 -> _TAM -> 4 mốc -> 28 ngày, nghỉ trong 23:45–00:15 và 00:45–03:00); E3 (SEL2 + Excel chính thức + bật lại lịch,
  lịch trùng tuyệt đối trước khi tắt, trước 06:30); 05:30 E2 chưa xong -> bật lại lịch, xuất bằng lịch sử đã có, báo.
  Sau đó: đăng ký lịch dọn định kỳ (thử -Apply trên thư mục mẫu trước), đồng bộ lịch sử khi production rảnh.
* **~21:15 – Bộ chạy độc lập:** scripts\ops\runner\ (Scheduled Task, plan.json, điểm dừng, watchdog mỗi 5 phút, STATUS.md +
  status.json mỗi 5 phút, ntfy.sh + thông báo Windows); test trên plan mẫu trước; chỉ giao E3 cho runner sau khi test
  đạt, nếu chưa sẵn sàng khi E2 xong thì phiên chat tự chạy E3.
* **~21:20 – Nhánh 05:30:** KHÔNG làm bản vá. Nếu kích hoạt: giữ file gốc, chép thêm 1 bản du_bao_YYYYMMDD_LICH_SU_THIEU.xlsx
  và tạo du_bao_YYYYMMDD_GHI_CHU.txt cùng thư mục (lịch sử có bao nhiêu ngày / 28; số SKU × kho dùng mô hình dự phòng
  V33_L112); báo qua chat + thông báo Windows + ntfy. **Danh sách 1.4.1:** dòng ghi chú "lịch sử chưa đủ 28 ngày" trong
  TOM_TAT.
* **22:07 – E3 giao cho runner** (scripts\ops\runner, test 34/34, review chấp thuận sau 3 vòng sửa): task
  DemandForecastRunner (plan reports\e3-20261104\plan.json, 6 bước: chờ E2 hoặc nhánh 05:30 -> chờ D-1 hôm nay ->
  sel2-day + Excel chính thức (03:00–06:25) -> nhánh 05:30 -> bật lại làm mới/xuất tự động, lịch trùng tuyệt đối ->
  data-check) + DemandForecastRunnerWatchdog (mỗi 5 phút; bỏ qua sel2-bootstrap / sel2-openhours-backfill của E2).
  Báo qua thông báo Windows + ntfy (chủ dự án xác nhận nhận được tin trên điện thoại 21:36). Phiên chat từ giờ chỉ đọc
  STATUS.md và báo lại E3. File tạm du_bao_20261103_TAM.xlsx (410.137 dòng) có lúc 21:55.

### 04/11/2026

* **03:45 – E3 xong (runner):** SEL2 04/11 + Excel chính thức du_bao_20261104.xlsx (v2, 410.137 dòng) lúc 03:23; bật lại
  làm mới/xuất tự động, lịch trùng tuyệt đối (sha d419d8c9…); data-check không có ERROR. Nhánh 05:30 không cần.
* **06:33 – Đồng bộ lịch sử DỪNG ở chốt chặn:** 1.091 khoá thay đổi ngoài 1.273 khoá đã báo 02/11 (1.039 dòng BI xoá thêm
  sau 02/11 + 52 khoá giảm số lượng, khoảng 22.578 đơn vị); không ghi gì vào production. Danh sách:
  reports\dong-bo-lich-su-20261102\khoa_moi_ngoai_1273_20261104.csv.
* **~07:35 – Chủ dự án: ÁP DỤNG ĐỒNG BỘ 2.364 KHOÁ** (gồm 1.091 khoá mới – đơn huỷ / trả BI xoá thêm sau 02/11), chạy ngay,
  được phép trùng lượt D0. Dùng bản xem trước BFP-20261103232209-00CECF nếu nguồn chưa đổi; nguồn đổi thì xem trước lại,
  chốt chặn giữ nguyên trừ chốt "chỉ trong 1.273 khoá", thay bằng: mọi thay đổi là xoá hoặc giảm số lượng, KHÔNG có khoá
  mới phía nguồn, tổng bỏ <= 0,2 %. Áp dụng -> đối soát theo ngày × kho -> data-check (hết history_source_drift).
  **Danh sách 1.4.1:** job đồng bộ hằng tuần dùng chốt theo TỶ LỆ (tổng bỏ <= 0,5 %, ngày bỏ > 5 % thì liệt kê, không có
  khoá mới phía nguồn), KHÔNG dùng danh sách khoá cố định.
* **07:55 – Chủ dự án: TẮT NHÃN "Chạy thử – chưa dùng để mua hàng".** Tắt bằng API có sẵn POST
  /api/daily-forecast/trial-mode (cụm xác nhận TAT-CHAY-THU-2026-11-04); lịch sử cấu hình id 65 "OWNER_CONFIRMED
  trial_mode=false", nhật ký TRIAL_MODE_CHANGED. Sao lưu cấu hình trước/sau: reports\tat-chay-thu-20261104\. Chỉ
  daily_forecast.trial_mode đổi (true -> false); 11 nhóm cấu hình còn lại (lịch chạy, nguồn dự báo…) không đổi. Từ giờ
  số dự báo làm mới được coi là số dùng để mua hàng. Chữ còn nằm cứng trong code (không tắt bằng cấu hình): câu kết quả
  DAILY_FORECAST_PUBLISHED (backend/app/messages.py:407) hiện ở trang Lịch chạy / Job -> bản vá nhỏ ở 1.4.1.
  **Danh sách 1.4.1:** mỗi ngày chỉ giữ 1 file Excel cuối cùng (bản trước đổi tên _bo hoặc xoá), để không nhầm với file
  chưa đọc xong Avg Demand như _v1.
* **09:00 – Đồng bộ lịch sử ÁP DỤNG XONG** (job JOB-20261104004153-919540, lần đồng bộ D1L-20261104011004-7EF84D,
  FOLLOW_SOURCE 01/01–28/10, nguồn 2026-11-03T18:10:23Z không đổi; job tự sao lưu backup-20261104-074646-pre-backfill.zip):
  đối soát 0 khoá lệch, 602 / 602 ô ngày × kho khớp nguồn, tổng 42.470.559 đơn vị (bỏ 58.009); history_source_drift
  300 -> 1 ngày.
* **~11:50 – Chủ dự án: ĐÓNG ĐỒNG BỘ.** Ngày còn lệch nằm ngoài khoảng đã duyệt: **29/10/2026**, DB 2.993 SKU × kho /
  74.759 đơn vị, nguồn 2.996 / 74.806 (nguồn nhiều hơn 3 dòng, +47 đơn vị), ghi nhận ở lần kiểm tra của D-1 lúc
  2026-11-03T18:42:55Z. Để nguyên; **job đồng bộ hằng tuần của 1.4.1 xử lý.**
* **~11:50 – FALLBACK (file 04/11: 36,8 % SKU × kho; D3 15/10 41,3 %; backtest tháng 10 43,7 % cùng cách đếm, 16,6 %
  khi chỉ đếm ô có thực bán):** nguyên nhân chính là ngày không mở bán (5.336 / 5.428 SKU × kho FALLBACK có < 14 ngày mở
  bán trong 28 ngày, 3.427 có 0 ngày). **Danh sách 1.4.1: làm a + b, KHÔNG làm c.** (a) TOM_TAT ghi tỷ lệ FALLBACK theo 2
  mẫu số (tất cả SKU × kho / SKU × kho có mở bán); (b) SKU × kho 0 ngày mở bán trong 28 ngày có lý do riêng, tách khỏi
  FALLBACK thiếu ngày. (c) đổi luật số ngày tối thiểu: không làm.
* **~11:50 – Git:** code 1.4.0 đã lên GitHub (chủ dự án cho phép push lần này): branch
  feature/san-xuat-chon-mo-hinh-20261101 = 1 commit d63ee22 trên main, tag v1.4.0; mẫu dữ liệu thật
  tests/fixtures/sel2 và bộ truy cập từ xa giữ ngoài Git. **Từ nay mọi thay đổi làm trên branch github/1.4.0**
  (worktree D:\Buymed\ban-1.4); bản 1.4.1 tách từ branch này. Merge vào main: chủ dự án quyết sau.
