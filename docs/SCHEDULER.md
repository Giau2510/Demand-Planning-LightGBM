# Scheduler (chạy trong backend trên máy Windows)

Scheduler là một luồng bên trong tiến trình backend, kiểm tra lịch mỗi 30 giây (`DF_TICK_SECONDS`). Không có scheduler
hay worker trên cloud. **Máy tắt hoặc ứng dụng không chạy thì không job nào chạy** — nên bật tự khởi động khi đăng nhập:
`scripts\register-autostart.ps1` (gỡ: `scripts\unregister-autostart.ps1`).

Mọi giờ là giờ Việt Nam (`Asia/Ho_Chi_Minh`, UTC+7). Từ 1.1.8 cấu hình tại trang **Lịch chạy dữ liệu** (menu Quản trị,
`/schedules`): mỗi luồng một thẻ riêng, **công tắc riêng**, giờ chạy, trạng thái sẵn sàng, lần chạy gần nhất/tiếp theo và
nhật ký riêng. Không còn công tắc chung cho mọi job.

| Job (luồng, công tắc) | Mặc định | Áp dụng cho |
|---|---|---|
| `D0_SYNC` — D-0, ngày hiện tại (`schedule.d0_enabled`, mặc định **TẮT**) | 08:00, 10:00, 12:00, 14:00, 16:00, 18:00 | DEMO (mô phỏng, gắn nhãn DEMO), BIGQUERY. MANUAL_IMPORT: *bị bỏ qua* (dữ liệu tĩnh) |
| `D1_SYNC` — D-1, ngày đã đóng (`schedule.d1_enabled`, mặc định **TẮT**) | chờ tín hiệu từ 01:00, kiểm tra mỗi 30 phút; giờ dự phòng 06:00 | chỉ BIGQUERY |
| `TRAIN_PUBLISH` — huấn luyện hằng ngày (`schedule.train_enabled`, giữ trạng thái công tắc chung cũ) | 07:00 | mọi nguồn; với BIGQUERY chỉ chạy sau khi D-1 hôm nay thành công (theo lịch hoặc chạy tay, 1.2.1) |
| `EOD_FORECAST_SNAPSHOT` — 1.2.6, snapshot forecast cuối ngày, 7 ngày kế tiếp (`schedule.eod_enabled`, mặc định **TẮT**) | 23:55 (cho phép 20:00–23:59) | mọi nguồn có bộ dữ liệu; chỉ sao chép dữ liệu cục bộ, chờ job huấn luyện / forecast đang chạy |
| `ACTUAL_CLOSE` — 1.2.6, chốt thực tế của ngày + đối soát dữ liệu đến muộn (`schedule.close_enabled`, mặc định **TẮT**) | 23:59 (cho phép 20:00–23:59) | DEMO, BIGQUERY; MANUAL_IMPORT *bị bỏ qua*; chờ lần đọc D-0 đang chạy |

1.2.6: hai job cuối ngày mang **ngày nghiệp vụ của mốc** (`params.business_date`, ngày Việt Nam), nên chạy sau nửa đêm
(grace, retry, chạy bù) vẫn cho đúng ngày đó. Mốc của hôm qua bị lỡ được chạy bù một lần; ngày cũ hơn ghi
`MISSED_SLOT_NO_BACKFILL`. Mốc trước lần đầu scheduler của phiên bản này thấy flow (`sync_state` `flows_first_seen`)
không bao giờ chạy. Quy tắc dữ liệu: [LICH-SU-FORECAST.md](LICH-SU-FORECAST.md) mục 10–14.

Hai luồng cuối ngày mặc định **TẮT** (chủ sở hữu quyết định 18/10/2026: bật trên trang Lịch chạy dữ liệu chỉ sau khi
kiểm tra sau deploy đạt). Thiết lập đã lưu mà thiếu khóa `eod_enabled` / `close_enabled` (nâng cấp từ 1.2.5) cũng đọc
là TẮT; migration không ghi thiết lập. Khi TẮT, scheduler không lên lịch job cuối ngày nào. Lỗi kiểm tra bản sao
snapshot (`EOD_SNAPSHOT_VERIFY_FAILED`) kết thúc job ở **FAILED** kèm alert ERROR, **không tự thử lại** (chỉ lỗi
BigQuery và lỗi không phải `AppError` được thử lại). Dọn snapshot quá 90 ngày là thao tác tay, không có lịch
(`scripts\eod-retention.ps1`, dry run trước).

Cấu hình hai luồng cuối ngày (card riêng trên trang Lịch chạy dữ liệu): công tắc, giờ, múi giờ (chỉ
`Asia/Ho_Chi_Minh`), mặc định, lần cập nhật cấu hình, trạng thái runtime và nút **Chạy thử (không ghi)**. Hai luồng không
được cùng một phút. Bật chỉ được giữ khi scheduler đang chạy xác nhận đã nạp (`SCHEDULE_NOT_REGISTERED` nếu không).
Chi tiết: [LICH-SU-FORECAST.md](LICH-SU-FORECAST.md) mục 13.

## Công tắc từng luồng (1.1.8)

- **Một công tắc cho mỗi luồng**: bật D-1 không bật D-0 và ngược lại; huấn luyện có công tắc riêng. Công tắc chỉ đổi
  qua `PUT /api/schedules/{d1|d0|train}` (trang Lịch chạy dữ liệu); trình sửa cấu hình chung và nút *Khôi phục mặc
  định* không đổi được công tắc. Công tắc lịch D0 cũ ở trang SQL nguồn nay chỉ hiển thị trạng thái và dẫn tới trang mới.
- **Chỉ bật được khi sẵn sàng** (409 `FLOW_NOT_READY` kèm lý do), tắt thì luôn được:
  - D-1: nguồn đang dùng là BIGQUERY, chế độ production đã bật, kiểm tra dữ liệu toàn kỳ đạt cho ánh xạ hiện tại, SQL
    lịch sử (nếu dùng SQL) đã được BigQuery xác nhận. Với DEMO/Excel: *Chưa sẵn sàng* — dữ liệu ngày đã đóng đến từ lô.
  - D-0: DEMO (snapshot tổng hợp, có nhãn) sẵn sàng khi có lô DEMO; MANUAL_IMPORT không áp dụng; BIGQUERY cần
    production và — ở chế độ SQL (mặc định) — một phiên bản SQL D-0 đã được BigQuery xác nhận (SQL v2 đề xuất không bao giờ tự được dùng).
    1.2.1: ánh xạ D-0 riêng đủ trường thiết yếu (`D0_MAPPING_INCOMPLETE`) và lần xác nhận được làm cho đúng ánh xạ/khóa
    D-0 hiện tại (`D0_REVALIDATE_REQUIRED`); chi tiết lý do ghi rõ trạng thái từng phiên bản (xem BIGQUERY.md mục 15).
  - Huấn luyện: có bộ dữ liệu; với BIGQUERY cần production + kiểm tra đạt, và **D-1 hôm nay thành công** (1.2.1): lần D-1
    theo lịch hoặc **chạy tay** (không phải bổ sung khoảng), kết thúc thành công trong ngày và nạp đến hôm qua. Chưa có lần
    nào như vậy và luồng D-1 tắt → `TRAIN_WAITS_FOR_D1`; luồng D-1 bật nhưng D-1 hôm nay chưa thành công → ghi chú
    `TRAIN_WAITING_FOR_TODAY_D1` (kèm trạng thái job D-1 hôm nay); đã thành công → ghi chú `D1_TODAY_SUCCEEDED` (job, giờ,
    dữ liệu đến ngày nào). Trước 1.2.1 chỉ lần D-1 *theo lịch* được tính: D-1 chạy tay thành công (ví dụ 17/10/2026 08:30)
    vẫn để huấn luyện báo "chờ D-1 hôm nay thành công".
- **Lưu không chạy job**: lưu giờ chạy hoặc bật một luồng không chạy gì. Thời điểm bật được lưu (`*_enabled_at`); các mốc
  TRƯỚC thời điểm bật không được chạy và không bị tính là "bị lỡ" (không có chạy bù do bật).
- **Scheduler đọc cấu hình đã lưu ở mỗi lượt** (30 s): không có gì phải "đăng ký" trong bộ nhớ, khởi động lại là khôi
  phục ngay. Sau khi lưu, API gọi `Scheduler.reload()` để xác nhận scheduler đang chạy đã nạp trạng thái mới; trang hiển
  thị *Đang bật — scheduler đã nạp*, hoặc rõ ràng *Đã lưu bật nhưng scheduler KHÔNG chạy* (`SCHEDULER_NOT_RUNNING`).
- Lần chạy theo lịch, chạy bù hay thử lại của một luồng đang TẮT không bao giờ thực thi: được ghi *bỏ qua* với
  `D1_SCHEDULE_DISABLED` / `D0_SCHEDULE_DISABLED` / `TRAIN_SCHEDULE_DISABLED`. *Chạy ngay 1 lần* (thủ công) vẫn có thể
  khi luồng sẵn sàng.
- 1.2.3: *Chạy ngay 1 lần* xét `manual_readiness` = điều kiện của nguồn, **không** xét điều kiện chỉ dành cho lịch
  (`TRAIN_WAITS_FOR_D1` phụ thuộc công tắc D-1). Huấn luyện thủ công (Tổng quan, Chất lượng mô hình, Job & Scheduler)
  trên nguồn BigQuery chưa sẵn sàng bị từ chối ngay (409 + lý do, không tạo job bị bỏ qua). Trang *Job & Scheduler* và
  `/api/scheduler/status` (`flow_states`) hiển thị trạng thái hiệu lực: luồng bật nhưng nguồn chưa sẵn sàng là *Đã bật
  nhưng hiện chưa sẵn sàng* kèm lý do — không bao giờ *Đang bật — scheduler đã nạp* chỉ vì công tắc đang bật.
- 1.2.4: trang *Job & Scheduler* có công tắc riêng cho D-1 và D-0 (cùng API `PUT /api/schedules/{d1|d0}`, cùng kiểm
  tra readiness). Ô công tắc luôn hiển thị trạng thái ĐÃ LƯU: sau mỗi lần backend trả lời (đồng ý hay từ chối) trang đọc
  lại `/api/scheduler/status`; lỗi được hiển thị và công tắc giữ trạng thái đã lưu. Trên link xem từ xa (proxy chỉ đọc)
  công tắc bị vô hiệu. Một luồng đã tắt không bao giờ tự bật lại. Bật D-1 / D-0 trên production: 17/10/2026 sau deploy
  1.2.4 (yêu cầu của chủ hệ thống), giờ chạy giữ nguyên (D-1 03:00, fallback 06:00; D-0 08–18 giờ, 2 giờ/lần).
- Nâng cấp từ 1.1.7 trở về trước: D-1 và D-0 **TẮT**; huấn luyện giữ trạng thái của công tắc chung cũ. Không luồng nào
  từ TẮT chuyển sang BẬT. (Với nguồn DEMO, snapshot D0 tổng hợp trước đây chạy theo công tắc chung sẽ dừng cho tới khi
  bật D-0.)
- Cửa sổ ngày: D-1 chỉ đọc đến **hôm qua** (giờ VN, từ đầu cửa sổ dữ liệu 01/01/2026); D-0 chỉ đọc **hôm nay** và chỉ ghi
  bảng snapshot, không bao giờ ghi lịch sử ngày đã đóng.

## D-1: tín hiệu và giờ dự phòng

1. Từ giờ bắt đầu, job kiểm tra *tín hiệu hoàn tất* (bảng trạng thái cấu hình ở trang BigQuery). Chưa có tín hiệu →
   trạng thái *Chờ thử lại* (`WAITING_FOR_SIGNAL`), không tính vào số lần thử.
2. Sau **giờ dự phòng** (người dùng cấu hình, không hard-code) mà vẫn chưa có tín hiệu (hoặc không cấu hình tín hiệu),
   hệ thống **vẫn kiểm tra** nguồn: số dòng của D-1 phải ≥ tỷ lệ cấu hình × trung bình 7 ngày trước. Không đạt →
   `SOURCE_INCOMPLETE`, retry với backoff. Không bao giờ coi dữ liệu là đủ chỉ vì đã đến giờ.

**Lịch đã chốt ngày 17/10/2026: D-1 bắt đầu 03:00, dự phòng 06:00, huấn luyện 09:00.** Khi so với giờ làm mới của nguồn
(16/10/2026: bảng D-1 làm mới lúc 14:08 nhưng ngày mới nhất vẫn là 15/10, tức ngày D có vào khoảng 12:00–14:10 ngày D+1),
diễn biến hằng ngày như sau:
- Từ 03:00 đến 06:00, job chờ tín hiệu (chưa cấu hình bảng tín hiệu hoàn tất).
- Lúc 06:00, kiểm tra thấy ngày hôm qua có 0 dòng, nên trả `SOURCE_INCOMPLETE`.
- Job thử lại sau 60, 120 rồi 240 giây và *Thất bại* (`RETRIES_EXHAUSTED`) vào khoảng 06:08.
- Lượt huấn luyện 09:00 trên BIGQUERY chờ D-1 của ngày đó thành công, nên **sẽ không chạy**.
- 1.2.1: nếu sau đó người vận hành **chạy tay D-1** khi nguồn đã đủ và lần đó thành công, lượt huấn luyện của ngày được
  chạy theo chính sách chạy bù đang chọn (`RUN_ONCE`: chạy một lần ngay ở lượt scheduler kế tiếp; `SKIP`: bỏ qua). Quality
  gate vẫn áp dụng: model không đạt thì không publish, forecast đã publish giữ nguyên.

Muốn luồng hằng ngày chạy được cần **một quyết định của chủ dự án**, chọn một trong ba hướng: dời giờ dự phòng hoặc giờ D-1
sau giờ làm mới của nguồn, cấu hình bảng tín hiệu hoàn tất, hoặc tăng số lần thử / khoảng chờ. Ứng dụng không tự đổi giờ.

## Retry, timeout, khóa, idempotency

- **Idempotency key** cho mỗi lần chạy theo lịch (vd. `D0_SYNC:2026-10-14T10:00`, `TRAIN_PUBLISH:2026-10-14`):
  job đã thành công/bị bỏ qua không bao giờ chạy lại.
- **Khóa** theo loại job (có thời hạn) — hai job cùng loại không chạy chồng.
- **Database bận (1.2.0):** một transaction ghi dài (ví dụ nạp lại toàn kỳ D-1 khoảng 1,35 triệu dòng) có thể giữ khóa
  SQLite lâu hơn `busy_timeout` (30 s).
  - Trước 1.2.0, lượt tick đó ghi lỗi ERROR `database is locked`.
  - Từ 1.2.0, lượt tick đó được **hoãn** với cảnh báo WARNING `SCHEDULER_TICK_DEFERRED`. Lượt sau (60 s) lập lịch lại đúng
    các slot đó; idempotency key ngăn chạy trùng. Các lỗi khác vẫn là ERROR.
- **Retry** exponential backoff: chờ `retry_base_seconds × 2^(lần−1)`, tối đa `retry_max_seconds`, tối đa `max_attempts`
  lần (mặc định 60 s, 1800 s, 4 lần). Hết lượt → *Thất bại* + cảnh báo `RETRIES_EXHAUSTED`. Chỉ được thử lại: lỗi tạm
  thời (`Retryable`), `TIMEOUT`, lỗi không phải `AppError` (`JOB_ERROR`) và `BQ_ERROR` / `BQ_AUTH_MISSING`
  (`jobs/runner.py`). Một `AppError` khác, ví dụ `EOD_SNAPSHOT_VERIFY_FAILED`, kết thúc *Thất bại* ngay ở lần đầu, kèm
  cảnh báo ERROR mang chính mã lỗi đó.
- **Timeout** mỗi job (mặc định 3600 s): quá hạn → job bị đánh dấu `TIMEOUT`, huấn luyện bị hủy trước bước publish.
  D-1 / D-0 không có cơ chế hủy: lần đọc đang chạy có thể chạy nốt sau khi job đã bị đánh dấu `TIMEOUT` (dữ liệu vẫn
  nhất quán vì mỗi lần ghi là một transaction có đối soát).
  - Từ 1.2.13, luồng job còn chạy sau timeout **giữ khóa** của loại job đó đến khi thật sự kết thúc (khóa gia hạn mỗi
    60 s). Lần thử lại chờ, không chạy chồng.
  - Trước 1.2.13 khóa được nhả ngay. Lần thử lại có thể chạy song song với luồng cũ, ví dụ hai lần huấn luyện cùng lúc,
    gấp đôi bộ nhớ.
- **Kết quả huấn luyện ≠ trạng thái job:** model *không đạt chất lượng* (`REJECTED`) hoặc *lỗi huấn luyện* (`FAILED`)
  là kết quả của model; job vẫn ghi *Thành công*, cảnh báo nằm ở trang *Tổng quan*, không thử lại trong cùng ngày
  (khóa `TRAIN_PUBLISH:<ngày>`). Trang *Job & Scheduler* và (từ mã nguồn sau 1.1.8) trang *Lịch chạy dữ liệu* hiển
  thị thêm nhãn kết quả.
- Lịch sử job: trang **Job & Scheduler** (trạng thái, lý do, số lần thử, thời điểm thử lại, lỗi, kết quả).

## Tài nguyên của job (1.2.13)

**Số liệu mỗi lần thử.** Mọi job ghi `resources` trong kết quả (`result_json`, xem qua `GET /api/jobs/{id}`) và một dòng
log `job resources` (`backend/app/jobs/resources.py`, không cần gói thêm):
- PID, thời gian chạy, CPU (user / kernel, % trên số luồng logic);
- bộ nhớ riêng (private bytes) và working set: lúc bắt đầu, đỉnh, trung bình, lúc kết thúc (lấy mẫu mỗi 2 s);
- số page fault, MB đọc / ghi;
- RAM trống và dung lượng commit còn lại của máy (mức thấp nhất trong lúc chạy);
- `other_jobs`: job khác chạy cùng lúc. Server chạy mọi job trong một tiến trình, nên số liệu là của cả tiến trình.

Mẫu lấy mỗi 2 s: đỉnh của job rất ngắn (vài giây) có thể thấp hơn thực tế. Dọn chung sau mỗi job (`gc.collect` + nén
heap) đã được đo trên bản sao (trả lại 0 MB sau huấn luyện, 6 MB sau D-1) nên không giữ; bộ nhớ được trả bằng cách
không giữ dữ liệu lớn quá lúc cần (xem CHANGELOG 1.2.13).

**Job nặng** gồm `TRAIN_PUBLISH`, `FORECAST_EXTEND` và backfill D-1.
- Không bao giờ có hai job nặng chạy cùng lúc trong một tiến trình, kể cả job theo lịch. Trước 1.2.13 chỉ nút chạy tay
  kiểm tra điều này.
- Job đến sau chờ (`RETRY_WAIT`, lý do `LOCKED`) và chạy khi job kia xong.

**Kiểm tra bộ nhớ trước job nặng.** Nhu cầu = mức tăng bộ nhớ riêng lớn nhất đo được ở 10 lần chạy gần nhất của cùng
loại job. Không có ngưỡng cố định: số liệu là của chính máy này.

| Điều kiện | Kết quả |
|---|---|
| Chưa có lần đo nào | `NO_BASELINE`: job chạy |
| Commit còn lại (RAM + page file) < 1,25 × nhu cầu | `INSUFFICIENT_MEMORY`: job **chưa chạy**, tính là một lần thử (backoff như retry; hết lượt → *Thất bại* + `RETRIES_EXHAUSTED`). Job sẽ hết bộ nhớ nếu chạy |
| RAM vật lý trống < nhu cầu | `PAGING_EXPECTED`: job **vẫn chạy**. Windows đẩy bộ nhớ của chương trình khác ra page file: chậm hơn, không lỗi |
| Còn lại | `OK` |

Trên máy hiện tại RAM trống thường chỉ khoảng 1 GB. Nếu hoãn theo RAM vật lý, huấn luyện sẽ bị chặn mãi.

**Cache giải thích.**
- Panel của một lần chạy (khoảng 190 MB trên dữ liệu production 22/10) và vết SHAP được trả lại sau 30 phút không có
  yêu cầu giải thích.
- Khi đổi lần chạy hoặc phiên bản dữ liệu, panel cũ được bỏ ngay.

## Công đoạn job (tiến trình thật, không có phần trăm)

Mỗi job lưu `stage`, `stage_updated_at` và lịch sử công đoạn (`stage_history_json`, migration 0003). Công đoạn chỉ
được ghi khi code thực sự bước sang bước đó (`backend/app/jobs/progress.py`):

| Job | Công đoạn |
|---|---|
| `TRAIN_PUBLISH` | QUEUED → STARTED → VALIDATING_DATA → PREPARING_DATA → BACKTESTING → TRAINING → QUALITY_GATE → FORECASTING → PUBLISHING → DONE |
| `FORECAST_EXTEND` | QUEUED → STARTED → VERIFYING_MODEL → PREPARING_DATA → FORECASTING → PUBLISHING → DONE |
| `D0_SYNC`, `D1_SYNC` | QUEUED → STARTED → SYNCING → DONE |
| `EOD_FORECAST_SNAPSHOT` (1.2.6) | QUEUED → STARTED → SNAPSHOTTING → DONE |
| `ACTUAL_CLOSE` (1.2.6) | QUEUED → STARTED → CLOSING → DONE |

Kết thúc: DONE / FAILED / SKIPPED / WAITING_RETRY / INTERRUPTED. Với huấn luyện, **kết quả huấn luyện** (chấp nhận /
không đạt / lỗi, `failed_stage`) và **kết quả publish** được hiển thị tách riêng; lỗi trong bước PUBLISHING có mã
`PUBLISH_FAILED` và forecast cũ được giữ nguyên.

- Bấm chạy khi đã có job cùng nhóm (huấn luyện và bổ sung khoảng dùng chung một nhóm) đang chờ/chạy → trả về job đang
  có (`already_active`), không tạo job trùng.
- Giao diện (Tổng quan, Kết quả dự báo, Job & Scheduler) gắn lại vào job đang chạy sau khi tải lại trang
  (`GET /api/jobs/active?job_type=`), hỏi trạng thái mỗi 2 giây (`GET /api/jobs/{id}`). Lỗi khi hỏi = *mất kết nối*,
  không bao giờ hiển thị là job thất bại.
- Job RUNNING không cập nhật công đoạn quá `timeout_seconds + 60` giây → cờ `stale` ("không rõ, không còn cập nhật").

## Khi máy khởi động lại

1. Job đang chạy dở của phiên trước → *Chờ thử lại* (`INTERRUPTED`) hoặc *Thất bại* nếu hết lượt (job bấm tay chỉ có
   1 lượt nên thành *Thất bại*); công đoạn ghi `INTERRUPTED` kèm công đoạn đang dở; khóa cũ được giải phóng. Không
   job nào bị hiển thị "đang chạy" mãi.
2. Các mốc bị lỡ (kể cả nhiều ngày, tối đa 14 ngày gần nhất) được ghi là **Bị bỏ qua — `MISSED_SLOT_NO_BACKFILL`**.
   Với D-1, dữ liệu của các ngày bị lỡ vẫn được đọc ở lần D-1 thành công kế tiếp (lần đọc bắt đầu từ watermark −
   `late_data_lookback_days`).
   **Không tạo snapshot giả** cho mốc đã qua.
3. D0 (chính sách `LATEST_ONCE`): tối đa **một** lần chạy bù trong ngày, gắn nhãn *Chạy bù*, ghi **thời điểm đọc thực
   tế** (không lùi về giờ của mốc). Chính sách `SKIP`: không chạy bù.
4. Huấn luyện (`RUN_ONCE`): nếu hôm nay chưa chạy, chạy bù một lần. Mỗi lượt kiểm tra lịch chỉ chạy tối đa
   `max_catchup_jobs_per_tick` job chạy bù để không dồn tải.

## Publish

Chỉ publish khi: dữ liệu đạt kiểm tra, không cũ (với nguồn bị kiểm tra), backtest đủ tin cậy và đạt ngưỡng. Nếu không,
forecast hợp lệ trước đó vẫn là bản hiện hành và lý do được ghi vào lần huấn luyện, job và cảnh báo. Dữ liệu
không đổi → `NO_NEW_DATA` (bỏ qua, không huấn luyện thừa). Mở dashboard **không** kích hoạt huấn luyện.
