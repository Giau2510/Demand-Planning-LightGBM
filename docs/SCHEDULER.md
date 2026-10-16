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
| `TRAIN_PUBLISH` — huấn luyện hằng ngày (`schedule.train_enabled`, giữ trạng thái công tắc chung cũ) | 07:00 | mọi nguồn; với BIGQUERY chỉ chạy sau khi D-1 hôm nay thành công |

## Công tắc từng luồng (1.1.8)

- **Một công tắc cho mỗi luồng**: bật D-1 không bật D-0 và ngược lại; huấn luyện có công tắc riêng. Công tắc chỉ đổi
  qua `PUT /api/schedules/{d1|d0|train}` (trang Lịch chạy dữ liệu); trình sửa cấu hình chung và nút *Khôi phục mặc
  định* không đổi được công tắc. Công tắc lịch D0 cũ ở trang SQL nguồn nay chỉ hiển thị trạng thái và dẫn tới trang mới.
- **Chỉ bật được khi sẵn sàng** (409 `FLOW_NOT_READY` kèm lý do), tắt thì luôn được:
  - D-1: nguồn đang dùng là BIGQUERY, chế độ production đã bật, kiểm tra dữ liệu toàn kỳ đạt cho ánh xạ hiện tại, SQL
    lịch sử (nếu dùng SQL) đã được BigQuery xác nhận. Với DEMO/Excel: *Chưa sẵn sàng* — dữ liệu ngày đã đóng đến từ lô.
  - D-0: DEMO (snapshot tổng hợp, có nhãn) sẵn sàng khi có lô DEMO; MANUAL_IMPORT không áp dụng; BIGQUERY cần
    production và — ở chế độ SQL (mặc định) — một phiên bản SQL D-0 đã được BigQuery xác nhận (SQL v2 đề xuất không bao giờ tự được dùng).
  - Huấn luyện: có bộ dữ liệu; với BIGQUERY cần production + kiểm tra đạt và luồng D-1 bật (huấn luyện chờ D-1).
- **Lưu không chạy job**: lưu giờ chạy hoặc bật một luồng không chạy gì. Thời điểm bật được lưu (`*_enabled_at`); các mốc
  TRƯỚC thời điểm bật không được chạy và không bị tính là "bị lỡ" (không có chạy bù do bật).
- **Scheduler đọc cấu hình đã lưu ở mỗi lượt** (30 s): không có gì phải "đăng ký" trong bộ nhớ, khởi động lại là khôi
  phục ngay. Sau khi lưu, API gọi `Scheduler.reload()` để xác nhận scheduler đang chạy đã nạp trạng thái mới; trang hiển
  thị *Đang bật — scheduler đã nạp*, hoặc rõ ràng *Đã lưu bật nhưng scheduler KHÔNG chạy* (`SCHEDULER_NOT_RUNNING`).
- Lần chạy theo lịch, chạy bù hay thử lại của một luồng đang TẮT không bao giờ thực thi: được ghi *bỏ qua* với
  `D1_SCHEDULE_DISABLED` / `D0_SCHEDULE_DISABLED` / `TRAIN_SCHEDULE_DISABLED`. *Chạy ngay 1 lần* (thủ công) vẫn có thể
  khi luồng sẵn sàng.
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

## Retry, timeout, khóa, idempotency

- **Idempotency key** cho mỗi lần chạy theo lịch (vd. `D0_SYNC:2026-10-14T10:00`, `TRAIN_PUBLISH:2026-10-14`):
  job đã thành công/bị bỏ qua không bao giờ chạy lại.
- **Khóa** theo loại job (có thời hạn) — hai job cùng loại không chạy chồng.
- **Retry** exponential backoff: chờ `retry_base_seconds × 2^(lần−1)`, tối đa `retry_max_seconds`, tối đa `max_attempts`
  lần (mặc định 60 s, 1800 s, 4 lần). Hết lượt → *Thất bại* + cảnh báo `RETRIES_EXHAUSTED`.
- **Timeout** mỗi job (mặc định 3600 s): quá hạn → job bị đánh dấu `TIMEOUT`, huấn luyện bị hủy trước bước publish.
  D-1 / D-0 không có cơ chế hủy: lần đọc đang chạy có thể chạy nốt sau khi job đã bị đánh dấu `TIMEOUT` (dữ liệu vẫn
  nhất quán vì mỗi lần ghi là một transaction có đối soát).
- **Kết quả huấn luyện ≠ trạng thái job:** model *không đạt chất lượng* (`REJECTED`) hoặc *lỗi huấn luyện* (`FAILED`)
  là kết quả của model; job vẫn ghi *Thành công*, cảnh báo nằm ở trang *Tổng quan*, không thử lại trong cùng ngày
  (khóa `TRAIN_PUBLISH:<ngày>`). Trang *Job & Scheduler* và (từ mã nguồn sau 1.1.8) trang *Lịch chạy dữ liệu* hiển
  thị thêm nhãn kết quả.
- Lịch sử job: trang **Job & Scheduler** (trạng thái, lý do, số lần thử, thời điểm thử lại, lỗi, kết quả).

## Công đoạn job (tiến trình thật, không có phần trăm)

Mỗi job lưu `stage`, `stage_updated_at` và lịch sử công đoạn (`stage_history_json`, migration 0003). Công đoạn chỉ
được ghi khi code thực sự bước sang bước đó (`backend/app/jobs/progress.py`):

| Job | Công đoạn |
|---|---|
| `TRAIN_PUBLISH` | QUEUED → STARTED → VALIDATING_DATA → PREPARING_DATA → BACKTESTING → TRAINING → QUALITY_GATE → FORECASTING → PUBLISHING → DONE |
| `FORECAST_EXTEND` | QUEUED → STARTED → VERIFYING_MODEL → PREPARING_DATA → FORECASTING → PUBLISHING → DONE |
| `D0_SYNC`, `D1_SYNC` | QUEUED → STARTED → SYNCING → DONE |

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
