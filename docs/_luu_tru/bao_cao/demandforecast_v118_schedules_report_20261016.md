# Demand Forecasting 1.1.8 — tách lịch chạy D-1 / D-0 (audit + triển khai)

Ngày: 16/10/2026 (giờ Việt Nam). Máy LOG-PC, tài khoản Windows `LOG-PC\Giau Vo`. Thư mục `D:\Buymed\Lightgbm AI`
(không phải Git repository: không commit/push). Bản đang chạy vẫn là **1.1.6** — batch này không cài gì lên máy, không
bật lịch nào, không chạy job production. Gói 1.1.7 giữ nguyên (SHA-256 `7D05CE49…F45B`) để đối chiếu.

> **Cập nhật 16/10/2026 (Phần II, cuối báo cáo):** 1.1.8 đã được cài thật lên máy lúc 08:31–08:34 theo yêu cầu của người
> dùng, D-0 DEMO đã được bật lại (mỗi 2 giờ) và một lần chạy D-0 thủ công đã được kiểm thử. Phần I (mục 1–13) giữ nguyên
> nội dung lúc build; bản gốc trước khi cập nhật: `checkpoints\report-v118-schedules-before-deploy-update-20261016.md`
> (SHA-256 `93767DFC…EA56`).

## Kết luận

UI, backend và scheduler đã đồng bộ: mỗi luồng (D-1, D-0, huấn luyện hằng ngày) có công tắc, giờ chạy, trạng thái, lần
chạy gần nhất/tiếp theo, nhật ký và kiểm tra sẵn sàng riêng, cấu hình tại trang mới **Quản trị → Lịch chạy dữ liệu**.
D-1 và D-0 mặc định **TẮT**. Gói `DemandForecast-1.1.8-win64-portable.zip` đã build và kiểm thử cô lập; **chưa cài**.

## 1. Kết quả audit (đối chiếu với source code và test, trước khi sửa)

| # | Câu hỏi | Thực tế trong 1.1.7 (code) |
|---|---|---|
| 1 | Loại job | `D1_SYNC`, `D0_SYNC`, `TRAIN_PUBLISH` (theo lịch) và `FORECAST_EXTEND` (chỉ thủ công) — `jobs/runner.py` |
| 2 | D-1 và D-0 dùng chung job? | **Đã tách** ở mức job: loại job, khóa idempotency (`D1_SYNC:<ngày>`, `D0_SYNC:<ngày>T<giờ>`), lease-lock theo loại job, hàm chạy (`sync.run_d1_sync`, `sync.run_d0_snapshot`) và giờ chạy riêng |
| 3 | Cấu hình lịch riêng từng luồng? | Giờ: có riêng (`d0_times`; `d1_signal_poll_start`/`d1_fallback_time`; `train_time`). **Bật/tắt: KHÔNG** — một công tắc chung `schedule.enabled` cho cả D0, D-1 và huấn luyện. Riêng D0 BigQuery có thêm cờ `sql_sources.d0.schedule_enabled` |
| 4 | API đọc/ghi cấu hình | Chỉ có API chung `GET /api/settings`, `PUT /api/settings/schedule` (ghi cả công tắc, không kiểm tra sẵn sàng), `GET /api/scheduler/status`, `GET /api/sync/status`, `POST /api/scheduler/tick`, `POST /api/jobs/run`; công tắc D0 BigQuery qua `PUT /api/sql-sources/d0/options` |
| 5 | UI quản lý lịch | **Có nhưng rải rác**: *Cấu hình dự báo → Lịch chạy* (công tắc chung + các giờ), *Job & Scheduler* (trạng thái, chạy ngay), *SQL nguồn & đồng bộ* (công tắc D0 BigQuery, bảng trạng thái D-1/D0). Không có chỗ nào bật/tắt riêng D-1 hay D-0 → đúng như người dùng phản ánh |
| 6 | D-0 tự chạy theo lịch? | **Có**: với nguồn DEMO, D0 (snapshot tổng hợp) chạy mỗi mốc 08–18 giờ khi công tắc chung bật — đang chạy trên máy thật (1.1.6). Với BigQuery bị chặn bởi `sql_sources.d0.schedule_enabled=false` (job ghi *bỏ qua*) |
| 7 | Khôi phục sau restart | Có: scheduler đọc cấu hình từ DB ở mỗi lượt (30 s), không giữ gì trong bộ nhớ; job dở dang → `INTERRUPTED` |
| 8 | Chống trùng / chồng / log | Có: `idempotency_key` UNIQUE, lease-lock `job:<loại>`, tập `inflight`, nhóm loại trừ khi chạy tay, retry có backoff, lịch sử `job_runs` + log JSON + cảnh báo |
| 9 | UTC thay vì giờ VN? | Không có lỗi: lịch tính bằng `now_vn()`/`vn_slot` (Asia/Ho_Chi_Minh); timestamp lưu UTC theo thiết kế; D-1 đọc tới `today_vn()-1`, D0 đọc `today_vn()` |
| 10 | Bật một luồng có thể bật luồng kia? | **Có**: bật công tắc chung bật đồng thời D0 (DEMO), D-1 (khi BigQuery production) và huấn luyện; tắt nó để dừng D0 cũng dừng D-1 và huấn luyện. Ngoài ra bật D0 lúc giữa ngày khiến các mốc đã qua bị coi là "lỡ" và chính sách `LATEST_ONCE` chụp bù ngay → thao tác cấu hình gây chạy job |

## 2. Thay đổi (1.1.8)

**Backend**
- `settings_service.ScheduleSettings`: công tắc riêng `d1_enabled` (mặc định TẮT), `d0_enabled` (TẮT), `train_enabled`
  (thiếu trong cấu hình cũ → lấy giá trị công tắc chung cũ); thời điểm bật `d1_enabled_at`/`d0_enabled_at`/
  `train_enabled_at`; kiểm tra giờ (`HH:MM`, ≤ 24 mốc D0, D0 bật thì phải có giờ). `enabled` cũ giữ lại chỉ để quay về
  bản cũ, không dùng để lập lịch.
- `jobs/flows.py` (mới): nguồn sự thật cho 3 luồng — sẵn sàng (chỉ dùng trạng thái cục bộ, không gọi Google), trạng thái
  hiệu lực, lần chạy gần nhất/tiếp theo, nhật ký, lưu từng luồng (không đụng luồng khác, không chạy job), chạy ngay.
- `jobs/scheduler.py`: chỉ lập lịch luồng đang BẬT; mốc trước thời điểm bật không chạy và không bị coi là lỡ; không retry
  luồng đã TẮT; `reload()` + trạng thái `loaded` để xác nhận scheduler đang chạy đã nạp cấu hình.
- `jobs/runner.py`: lần chạy theo lịch / chạy bù / retry của luồng đang TẮT được ghi *bỏ qua* (`D1_SCHEDULE_DISABLED`,
  `D0_SCHEDULE_DISABLED`, `TRAIN_SCHEDULE_DISABLED`), không thực thi; chạy tay vẫn được.
- `sync.py`: kiểm tra D0 theo lịch dùng công tắc D-0 mới (mọi nguồn).
- `api/schedule_routes.py` (mới): `GET /api/schedules`, `GET|PUT /api/schedules/{d1|d0|train}`,
  `POST /api/schedules/{flow}/run`; `main.py` đăng ký router.
- `api/data_routes.py`: `PUT /api/settings/schedule` và *khôi phục mặc định* không đổi được công tắc
  (`SCHEDULE_SWITCH_VIA_FLOW_API`). `bq/sql_sources.py`: công tắc D0 cũ ánh xạ vào cùng công tắc D-0.
  `api/ops_routes.py`, `api/bq_routes.py`: trạng thái theo từng luồng. `messages.py`: thông báo song ngữ mới.
- Audit `SCHEDULE_CHANGED` (thay đổi + giá trị trước) cho mỗi lần lưu.

**Frontend**
- `pages/Schedules.tsx` (mới), route `/schedules`, mục menu *Lịch chạy dữ liệu*; `pages/Config.tsx` (bỏ công tắc chung
  và các giờ, thay bằng liên kết); `pages/Jobs.tsx` (trạng thái từng luồng + liên kết); `pages/SqlSources.tsx` (bỏ nút
  bật D0 trùng lặp, chỉ hiển thị trạng thái + liên kết); `i18n.tsx`.

**Test**: `backend/tests/test_v118.py` (mới, 22), `backend/tests/test_scheduler.py` (4 test bật rõ luồng cần kiểm vì
mặc định đổi), `frontend/src/v118.test.tsx` (mới, 4), `frontend/src/v116.test.tsx` (trang SQL không còn nút bật D0).

**Tài liệu**: `docs/SCHEDULER.md`, `docs/TRIEN-KHAI-1.1.8.md` (mới), `docs/VAN-HANH.md`, `CHANGELOG.md`. Phiên bản 1.1.8
(`backend/app/__init__.py`, `frontend/package.json`).

## 3. Cấu trúc UI và đường dẫn

Menu **Quản trị → Lịch chạy dữ liệu** (`http://127.0.0.1:8765/schedules`):
- Dòng đầu: scheduler đang chạy/không, giờ hiện tại (Asia/Ho_Chi_Minh), lượt kiểm tra gần nhất, nguồn dữ liệu.
- **Thẻ A — D-1: Dữ liệu ngày đã đóng**: trạng thái, ngày bắt đầu 01/01/2026, kết thúc = hôm qua (giờ VN), múi giờ,
  sẵn sàng + lý do, giờ bắt đầu chờ tín hiệu, giờ dự phòng, chu kỳ kiểm tra, lần chạy gần nhất + kết quả, lần chạy tiếp
  theo, nhật ký, nút *Lưu giờ chạy*, *Bật/Tắt luồng này*, *Chạy ngay 1 lần*.
- **Thẻ B — D-0: Dữ liệu ngày hiện tại**: như trên, với các giờ chụp snapshot và chính sách khi lỡ mốc; bật có hộp xác nhận.
- **Thẻ C — Huấn luyện hằng ngày** (dùng dữ liệu ngày đã đóng): giờ huấn luyện, chính sách khi lỡ giờ.
- Thẻ *Khi ứng dụng tắt đúng giờ chạy*: quy tắc cho từng luồng.
Không có nút bật chung. Nút bật/chạy bị khóa (kèm lý do) khi luồng chưa sẵn sàng; nút *Bật* yêu cầu lưu thay đổi giờ trước.

## 4. Cách cấu hình

1. Sửa giờ trong thẻ → **Lưu giờ chạy** (chỉ lưu luồng đó; không chạy job; thông báo "Đã lưu giờ chạy (không chạy job nào)").
2. **Bật luồng này** khi thẻ báo *Sẵn sàng* → trạng thái chuyển *Đang bật — scheduler đã nạp* (backend xác nhận).
3. **Tắt luồng này** bất cứ lúc nào.
4. API tương đương: `PUT /api/schedules/d1 {"time":"02:30","fallback_time":"06:30","poll_interval_minutes":30}`,
   `PUT /api/schedules/d0 {"times":["09:00","15:00"],"catchup_policy":"SKIP"}`, `PUT /api/schedules/d0 {"enabled":true}`
   (header `X-DF-Client: web`).

## 5. Mặc định và sẵn sàng

| Luồng | Mặc định sau nâng cấp | Sẵn sàng khi | Trên máy hiện tại (nguồn DEMO) |
|---|---|---|---|
| D-1 | TẮT | nguồn BIGQUERY + production bật + kiểm tra toàn kỳ đạt (+ SQL lịch sử đã xác nhận nếu dùng SQL) | *Chưa sẵn sàng* — `D1_SOURCE_NOT_BIGQUERY` |
| D-0 | TẮT | DEMO có lô (snapshot tổng hợp, có nhãn) / BIGQUERY production + SQL D-0 đã được BigQuery xác nhận (chế độ SQL) | *Sẵn sàng* (DEMO) nhưng TẮT; BigQuery: *Chưa sẵn sàng* (`SOURCE_NOT_READY`, `SQL_NOT_VALIDATED`) |
| Huấn luyện | giữ công tắc chung cũ (đang BẬT) | có bộ dữ liệu; BIGQUERY cần production + D-1 bật | *Sẵn sàng*, BẬT |

SQL D-0 v2 (đề xuất) không bao giờ được dùng trừ khi người dùng kiểm tra và BigQuery xác nhận; quy tắc đơn hủy không
được thay đổi.

## 6. Khi ứng dụng tắt đúng giờ chạy

- D-1: mở lại sau giờ bắt đầu → chạy một lần cho hôm đó; đọc ngày đã đóng tăng dần từ watermark (không trùng); ngày bị bỏ
  lỡ hoàn toàn ghi *bỏ qua*.
- D-0: mốc lỡ ghi *bỏ qua* (`MISSED_SLOT_NO_BACKFILL`), không tạo snapshot giả; chỉ chạy bù khi chính sách là
  *Chạy bù 1 lần* (1 snapshot hôm nay, ghi giờ thật); không chạy bù ngày cũ. Máy hiện tại đang lưu chính sách
  `LATEST_ONCE` — hiển thị và đổi được ở thẻ D-0.
- Huấn luyện: theo *Khi lỡ giờ huấn luyện* (`RUN_ONCE`/`SKIP`).
- Bật một luồng không gây chạy bù: chỉ các mốc sau thời điểm bật mới chạy.

## 7. Kết quả kiểm thử

| Kiểm thử | Loại | Đạt | Lỗi | Bỏ qua | Bằng chứng |
|---|---|---|---|---|---|
| Backend pytest (toàn bộ) | unit + integration (BigQuery giả) | **275** | 0 | 0 | `logs\development\pytest_118_20261016_002441.log` |
| — trong đó mới (1.1.8) | độc lập, sẵn sàng, validation, không chạy khi lưu/bật, restart, trùng, chồng, lỗi, retry, biên ngày VN, nâng cấp cấu hình | 22 | 0 | 0 | `tests/test_v118.py` |
| Frontend vitest | unit (API mock) | **52** | 0 | 0 | `logs\development\frontend_118_20261016_002447.log` (mới `v118.test.tsx`: 4) |
| Typecheck / build UI | tĩnh / build | OK / OK | — | — | log trên; build trong `build_118_*.log` |
| Lint | — | chưa cấu hình | | | |
| E2E trình duyệt trang Lịch chạy (bản sao DB, scheduler chạy thật) | thật, trên bản sao | **17** | 0 | 0 | scratchpad `e2e_sched.py` |
| Khởi động lại app cô lập (bản sao) | thật | cấu hình giữ nguyên, scheduler nạp lại, 0 job | — | — | mục 8 |
| Gói 1.1.8: cài 1.1.6 → nâng cấp 1.1.8 → kiểm tra → quay về 1.1.6 (bản sao DB thật) | gói thật, cô lập | **25** | 0 | 0 | scratchpad `iso118d.ps1` (gồm E2E chỉ đọc 90/0, model chờ duyệt + duyệt, rollback) |
| Kiểm tra nội dung gói, drift, secret | tất định | OK (drift 0, không dữ liệu/secret/cache) | 0 | — | |
| BigQuery / OAuth thật | — | không kiểm (ngoài phạm vi; vẫn thiếu OAuth client + IAM) | | | `bq-check` của gói 1.1.8: `BQ_AUTH_MISSING` |

Ghi chú: 4 test scheduler cũ được sửa để bật rõ luồng chúng kiểm tra (mặc định đổi theo yêu cầu); test frontend 1.1.6
về nút bật D0 ở trang SQL được đổi sang kiểm tra liên kết tới trang mới. Lần chạy đầu của kịch bản cô lập có 1 lỗi do bộ
E2E dùng chung (scratchpad) còn tìm nút đã bị gỡ — đã sửa bộ kiểm tra cho cả hai thiết kế và chạy lại toàn bộ: 25/25.

## 8. Bằng chứng hai lịch độc lập

- Test backend `test_saving_one_flow_never_changes_the_other`: lưu giờ D-1 → mọi khóa không thuộc D-1 giữ nguyên; lưu
  giờ D-0 (vẫn TẮT) → D-1 giữ giờ và trạng thái; bật D-0 → D-1 và huấn luyện không đổi; tắt D-0 → xóa thời điểm bật.
- `test_d1_with_a_ready_bigquery_source_is_independent_of_d0`: BigQuery sẵn sàng (client giả) → bật D-1, D-0 vẫn TẮT,
  không có lần chạy tiếp theo.
- `test_scheduler_plans_only_flows_that_are_on`: chỉ D-0 bật → kế hoạch chỉ có `D0_SYNC`; chỉ D-1 bật → chỉ `D1_SYNC`;
  không luồng nào → kế hoạch rỗng.
- `test_locks_and_failures_are_per_flow`: khóa của D-0 không chặn huấn luyện; D-0 lỗi → chỉ thẻ D-0 báo FAILED.
- `test_retries_and_scheduled_rows_of_a_flow_switched_off_never_execute`, `test_switching_on_never_runs_anything...`.
- E2E trình duyệt (bản sao DB, scheduler chạy thật, chu kỳ 5 s): lưu giờ D-1 → API xác nhận, D-0 không đổi; lưu giờ D-0
  khi TẮT → D-1 giữ giờ riêng; tải lại trang → cả hai cấu hình hiển thị đúng; trang chỉ gửi đúng 2 lệnh `PUT`
  (`/api/schedules/d1`, `/api/schedules/d0`), không lệnh chạy/bật nào; 0 job được tạo (kiểm tra qua API và trực tiếp
  trong DB); nhật ký audit có hai mục `SCHEDULE_CHANGED` riêng cho `d1` và `d0`.
- Khởi động lại app cô lập trên cùng bản sao: D-1 02:15 (TẮT), D-0 09:30/15:30 (TẮT), huấn luyện BẬT; scheduler đã nạp
  `{"d1": false, "d0": false, "train": true}`; không có job mới.

## 9. Không bật lịch production

- Không cài bản mới lên máy; 1.1.6 vẫn chạy (pid 36892), không bị dừng.
- Không bật D-0 hay D-1 ở đâu (kể cả bản sao): mọi thao tác bật chỉ chạy trong test tự động trên DB tạm.
- Không có truy vấn BigQuery thật (không có thông tin xác thực; các test BigQuery dùng client giả).
- E2E trên bản sao với scheduler chạy thật: không job nào được tạo (kiểm tra cả qua API và trực tiếp trong DB).

## 10. DB, model, cấu hình, backup — trước / sau

| Mục | Đầu batch (23:59 15/10) | Cuối batch (00:50 16/10) |
|---|---|---|
| Bản đang chạy | 1.1.6, pid 36892 từ 18:05, `current.txt` 1.1.6 | giống hệt (không dừng, không cài lại) |
| `storage.json` | SHA-256 8D79DBDD…E047 | giống hệt |
| DB (bản sao chỉ đọc) | schema 3, integrity ok, 0 lỗi FK, 38.533 dòng nhu cầu / 1.015.057 đơn vị, 3 forecast run | số dòng mọi bảng giống hệt, forecast run giống hệt |
| Cấu hình lịch trên máy thật | `schedule` lưu 14/10, `enabled=true`, chưa có khóa mới | giống hệt (không ghi) |
| Model | `MV-20261014-150621-DF32.txt` EC507FD6…, `.json` 62F11674… | giống hệt |
| Backup | 23 | 23 |
| Gói 1.1.6 / 1.1.7 | A2E0345C… / 7D05CE49… | giống hệt (không ghi đè) |

Mọi thao tác ghi đều chạy trên bản sao trong scratchpad với `LOCALAPPDATA` riêng.

## 11. Gói phát hành

- Gói: `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.8-win64-portable.zip` — 92.036.945 byte, manifest
  `DemandForecast-1.1.8-win64-portable.manifest.json`.
- **SHA-256: `0DFDEC86042767AB5E8A8545C990BEF5D2E8B87AB465A970F1642D4DB9F15EE0`** (cũng trong file `.sha256`).
- Gồm mọi thay đổi 1.1.7 (chưa từng được cài) + lịch chạy 1.1.8; tài liệu `docs/TRIEN-KHAI-1.1.8.md`, CHANGELOG.
- Không chứa DB, `storage.json`, model, credential, token hay `__pycache__` của ứng dụng; mã trong gói trùng mã nguồn.
- Checkpoint mã nguồn trước batch: `checkpoints\source-1.1.7-before-1.1.8-20261016-000339.zip`.
- **Chưa cài lên máy.**

## 12. Cài đặt và quay về

Chi tiết: `docs/TRIEN-KHAI-1.1.8.md`. Tóm tắt:
1. Ngoài giờ lịch, không có job đang chạy: `scripts\deploy-upgrade.ps1 -Package dist\DemandForecast-1.1.8-win64-portable.zip
   -ExpectedSha256 <SHA-256 ở mục 11> -CheckOnly`, rồi chạy lại không có `-CheckOnly` và gõ `UPGRADE-1.1.8`.
2. Sau nâng cấp: mở *Lịch chạy dữ liệu*; D-1 và D-0 TẮT, huấn luyện như cũ. Snapshot D0 DEMO (trước chạy mỗi 2 giờ)
   dừng cho tới khi bật D-0.
3. Quay về: `%LOCALAPPDATA%\Programs\DemandForecast\1.1.8\scripts\rollback-version.ps1 -To 1.1.6`, gõ
   `ROLLBACK-1.1.6`; không cần khôi phục DB; 1.1.6 dùng lại công tắc chung cũ.

## 13. Hạn chế / quyết định còn chờ

- D-1 chỉ có ý nghĩa với BigQuery; chưa thể bật trên máy này cho tới khi có OAuth client + IAM và BigQuery production
  (xem báo cáo 1.1.7).
- D-0 BigQuery chờ: schema thật (`created_at`), chọn SQL v1/v2, quy tắc đơn hủy (nghiệp vụ).
- Có muốn bật lại D-0 DEMO (snapshot tổng hợp mỗi 2 giờ) sau nâng cấp hay không — người dùng quyết định ở trang mới.
- Chính sách chạy bù D-0 trên máy hiện tại là `LATEST_ONCE` (đã lưu từ trước); đổi sang `SKIP` nếu không muốn chạy bù.
- Trang không có đăng nhập riêng: ứng dụng chỉ nghe `127.0.0.1` và chặn ghi không có header `X-DF-Client` (như các trang khác).
- `schedule.enabled` cũ vẫn nằm trong cấu hình (để quay về 1.1.6); 1.1.8 không dùng nó.

---

# Phần II — Triển khai thật 1.1.8 và kiểm thử D-0 DEMO (16/10/2026)

Hai yêu cầu của người dùng trong ngày: (1) *Triển khai 1.1.8 — cài đặt có kiểm soát*, khôi phục snapshot D-0 DEMO mỗi
2 giờ; (2) *Hoàn tất kiểm thử 1.1.8 — chạy D-0 thủ công* (dữ liệu hiện tại là dữ liệu test, cho phép chạy D-0 DEMO
một lần). Môi trường: máy LOG-PC, ứng dụng thật `http://127.0.0.1:8765`, nguồn **DEMO**
(`DEMO-20261014080556-5342EB`), không có quyền Google (BigQuery bị chặn ở cổng `auth`).

## Kết luận Phần II

| Hạng mục | Kết luận |
|---|---|
| Triển khai 1.1.8 | **THÀNH CÔNG** — 1.1.8 chạy trên DB cũ, dữ liệu/model/backup giữ nguyên, D-0 DEMO bật lại đúng giờ cũ, các kiểm tra bắt buộc đạt |
| Kiểm thử D-0 thủ công | **PASS** — job thành công, snapshot khớp nguồn 20/20 kiểm tra, không trùng/thiếu/sai ngày/sai phạm vi, lịch định kỳ giữ nguyên |
| Sai lệch đã giải thích | Sau *Chạy ngay*, thẻ D-0 vẫn ghi "Đang chạy" cho tới khi bấm *Làm mới* (trang không tự làm mới) — lỗi hiển thị, không ảnh hưởng dữ liệu (mục II.9) |
| Mốc lịch 10:00 | **đã xác minh riêng**: job theo lịch SUCCEEDED, snapshot khớp nguồn 20/20 (mục II.12) |

## II.1 Phiên bản, gói, CheckOnly và triển khai thật

| Mục | Giá trị |
|---|---|
| Trước | 1.1.6, pid 36892 (khởi động 15/10 18:05), `current.txt` = 1.1.6 |
| Sau | **1.1.8**, `current.txt` = 1.1.8; pid 37508 (08:34), khởi động lại có chủ đích lúc 09:17 → pid 18608 (II.5) |
| Gói | `dist\DemandForecast-1.1.8-win64-portable.zip`, 92.036.945 byte, SHA-256 thực tế `0DFDEC86042767AB5E8A8545C990BEF5D2E8B87AB465A970F1642D4DB9F15EE0` = kỳ vọng = file `.sha256` |
| Thời điểm | 08:29 kiểm tra: D0 08:00 đã xong (`JOB-20261016010019-460309` SUCCEEDED), huấn luyện 07:00 SKIPPED `NO_NEW_DATA`, không job PENDING/RUNNING, `job_locks` rỗng; mốc kế tiếp 10:00 |
| `-CheckOnly` (08:31:15) | `PRECHECK OK`: SHA-256, VERSION 1.1.8, không file credential, DB có, `storage-verify` ok, app 1.1.6 chạy, không job, đủ dung lượng |
| Triển khai thật | `deploy-upgrade.ps1 ... -ConfirmToken UPGRADE-1.1.8` (xác nhận không tương tác của chính script, chỉ được so sau khi prechecks + backup đạt); 08:31:36 → 08:34:33, exit 0, `UPGRADE OK: 1.1.6 -> 1.1.8`; log `logs\runtime\deploy-20261016-083136.log` |
| Migration | 3 → 3, không áp migration nào; `db_created_now: false` |
| Thời gian dừng | ~1 phút (08:33:28 dừng 1.1.6 → 08:34:33 1.1.8 sẵn sàng) |

Script đã được đọc trước khi chạy (`deploy-upgrade.ps1`, `install.ps1`, `rollback-version.ps1`, `start.ps1`, `stop.ps1`):
hành vi khớp tài liệu. Một điểm khác: `start.ps1` ghi đè `server.out.log`/`server.err.log` khi khởi động — bản của 1.1.6
được chép trước vào scratchpad (`logs_116_before_118`).

## II.2 DB runtime, storage, dữ liệu, model, backup

| Mục | Trước | Sau triển khai |
|---|---|---|
| DB | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db`, schema 3 | cùng file, schema 3, integrity ok |
| `storage.json` SHA-256 | `8D79DBDD…E047` | không đổi |
| storage id | `6cff0821634b0447` | không đổi |
| Số dòng (20 bảng) | 137.059 | 137.060: chỉ `audit_log` +1 (`BACKUP_CREATED`) |
| Model | `MV-20261014-150621-DF32.txt` `EC507FD6…6C26`, `.json` `62F11674…727B` | không đổi |
| Cấu hình (`app_settings`) | — | không đổi do nâng cấp |
| Backup | 23 file | 23 file cũ giữ nguyên (tên + kích thước) + 2 mới |
| `data-check` (trước) | exit 0; 1 WARN đã biết: `FCR-20261014080621-8D88F1` công bố trước migration 0003 nên không có dòng giải thích | — |

Backup mới (cả hai mở được, CRC zip đúng, `integrity_check` ok, schema 3, số dòng = trạng thái trước nâng cấp):

| File | Byte | SHA-256 | Tạo bởi |
|---|---|---|---|
| `backup-20261016-083136-manual.zip` | 9.103.592 | `BE05F2B12AB0BE929A63ADD08EC75D01AB5414C2C2A4BE971BC8FFE0EBE669EC` | `deploy-upgrade.ps1` (API, trực tuyến) |
| `backup-20261016-083328-cli.zip` | 9.103.617 | `28C2A02F03607ED3CC9966FB1EC50F823F7A7B8430780710AF3944BFD3D9E683` | `install.ps1` (sau khi dừng app) |

Rollback **không thực hiện** (không cần). Khả năng rollback đã kiểm tra: thư mục 1.1.6 còn nguyên;
`rollback-version.ps1 -To 1.1.6 -CheckOnly` từ bản 1.1.8 đã cài: `database schema 3; 1.1.6 supports up to 3 — rollback
possible without restoring the database`.

## II.3 Giao diện mới (trình duyệt thật, Chrome headless qua CDP)

| Bước | Kết quả |
|---|---|
| Kiểm tra chỉ đọc sau nâng cấp | **15/15**: menu *Quản trị → Lịch chạy dữ liệu* (`/schedules`), 3 thẻ D-1 / D-0 / Huấn luyện, mỗi thẻ có công tắc, Lưu giờ chạy, Chạy ngay 1 lần, trạng thái, lần chạy tiếp theo, nhật ký riêng; D-1 cửa sổ 01/01/2026 → 15/10/2026; D-1 *Tắt, Chưa sẵn sàng* (nút bị khóa, lý do BigQuery); D-0 *Tắt, Sẵn sàng*, ghi chú DEMO, giờ `08:00, 10:00, 12:00, 14:00, 16:00, 18:00`; Huấn luyện *Đang bật — scheduler đã nạp*, 07:00; trang không gửi request ghi; không lỗi console; không job phát sinh |
| Bật D-0 (09:16:47) | **14/14** (II.4) |
| Chạy ngay D-0 (09:23:10) | **7/8** — 1 kiểm tra hiển thị không đạt, đã giải thích (II.9) |
| Sau *Làm mới* | **9/9**: thẻ D-0 "16/10/2026 09:23 Thành công rows_read=151 · series=53 · snapshot_id=SNP-20261016022310-BE0AA7"; nhật ký "09:23 Thủ công Thành công", "08:00 Lịch Thành công"; trang *Lịch sử Snapshot D0* có dòng 09:23, mốc lịch "—", DEMO, 151/151/0 |

## II.4 D-0 DEMO bật lại; lịch sau kiểm thử

Bật tại thẻ D-0 bằng nút *Bật luồng này* (hộp xác nhận "Bật lịch D-0? Từ mốc giờ kế tiếp… Các mốc đã qua hôm nay không
được chạy bù."). Trang gửi đúng một request ghi `PUT /api/schedules/d0`. Không sửa DB/cấu hình trực tiếp.

| Luồng | Trạng thái sau kiểm thử |
|---|---|
| D-0 | **BẬT** từ 16/10/2026 09:16:47 (`d0_enabled_at`), scheduler đã nạp; giờ `08:00, 10:00, 12:00, 14:00, 16:00, 18:00` (không đổi so với trước nâng cấp); khi lỡ mốc `LATEST_ONCE` (không đổi); lần chạy tiếp theo 16/10 10:00 · 12:00 · 14:00 |
| D-1 | TẮT, *Chưa sẵn sàng* (`D1_SOURCE_NOT_BIGQUERY`), không có lần chạy tiếp theo |
| Huấn luyện | BẬT, 07:00, `RUN_ONCE`, lần tiếp theo 17/10/2026 07:00 (không đổi) |
| Scheduler | `loaded.flows = {d1: false, d0: true, train: true}`; heartbeat ghi cùng giá trị |

Thay đổi trong DB do thao tác bật: `app_settings.schedule` thêm `d0_enabled=true`, `d0_enabled_at`, `d1_enabled=false`,
`train_enabled=true` (công tắc chung cũ `enabled=true` giữ nguyên → quay về 1.1.6 vẫn chạy như cũ); `settings_history`
+1; `audit_log` +2 (`SETTINGS_SAVED`, `SCHEDULE_CHANGED` với giá trị trước/sau). Không job nào được tạo (đã chờ qua 1
nhịp scheduler). Chạy thủ công (II.6) không thay đổi `app_settings` (so sánh trước/sau: bằng nhau).

**Mốc lịch 10:00:** chạy đúng hạn và thành công — mục II.12.

## II.5 Khởi động lại ứng dụng

09:17:43, không job đang chạy: `stop.ps1` + `start.ps1 -NoBrowser` của 1.1.8 (cơ chế chính thức) → pid 18608, 1.1.8.
Sau khởi động: D-0 vẫn BẬT, `enabled_at` giữ nguyên 09:16:47, D-1 TẮT, huấn luyện BẬT 07:00; scheduler nạp đúng
trạng thái; **không job nào được tạo khi khởi động** (mốc 08:00 trước thời điểm bật → không chạy bù).

## II.6 Vòng kiểm tra nền trước khi chạy thủ công; D-0 chạy thủ công

Trước khi chạy (09:21–09:23): job D-0 mốc 10:00 **chưa chạy** (chưa đến hạn). Không job PENDING/RUNNING, `job_locks`
rỗng. Tiến trình nền duy nhất là `wait_d0_slot.py` (pid 37828, qua launcher venv pid 19656): chỉ gọi `GET /api/jobs` mỗi
30 giây, tìm khóa `D0_SYNC:2026-10-16T10:00`, hạn 10:40; không đọc bảng snapshot, không giữ khóa → không xung đột, để
chạy tiếp. Cơ chế chống trùng (đọc code): `background.submit` kiểm tra + chèn trong 1 transaction IMMEDIATE, trả về job
đang PENDING/RUNNING thay vì tạo job thứ hai; khóa thủ công `D0_SYNC:MANUAL:<ngẫu nhiên>` (không trùng khóa mốc lịch);
lease lock `job:D0_SYNC`; `idempotency_key` UNIQUE; job retry không ghi snapshot thứ hai (`job_id` đã có snapshot →
trả lại snapshot cũ).

Chạy bằng nút **Chạy ngay 1 lần** của thẻ D-0 (cùng handler `POST /api/schedules/d0/run` → `flows.run_now("d0")` →
kiểm tra sẵn sàng → `background.submit("D0_SYNC")`), một lần, sau hộp xác nhận "Chạy luồng này ngay một lần (ghi dữ liệu
như lần chạy theo lịch)?".

| Mục | Giá trị |
|---|---|
| Job | `JOB-20261016022310-A7374B`, khóa `D0_SYNC:MANUAL:1c0e3b63d439`, trigger MANUAL, lần thử 1/1 |
| Thời gian | tạo/bắt đầu 16/10/2026 09:23:10, kết thúc 09:23:10 (log `job finished` 09:23:11); stage QUEUED → STARTED → SYNCING → DONE |
| Kết quả | **SUCCEEDED**, không lỗi, `reason_code` rỗng |
| Đọc / hợp lệ / lỗi | 151 / 151 / 0 dòng nguồn |
| Ghi | 1 dòng `d0_snapshots` (`SNP-20261016022310-BE0AA7`) + 53 dòng `d0_snapshot_values` + 1 dòng `audit_log` (`D0_SNAPSHOT`) + 1 dòng `job_runs`; không bảng nào khác thay đổi |

## II.7 Đối chiếu nguồn ↔ snapshot

Nguồn DEMO D-0 là hàm tất định `demo_intraday_lines(ngày, seed=42)`: dòng đơn tổng hợp của hôm nay có `created_at` ≤
thời điểm đọc, cộng theo SKU × FC. Đã tính lại độc lập bằng Python + mã của bản 1.1.8 đã cài (`demo.py` = source), trong
`LOCALAPPDATA`/`DF_DATA_DIR` cô lập; DB thật chỉ mở `mode=ro`. Kết quả **20/20**.

| Chỉ tiêu | Nguồn (tính lại) | Snapshot `SNP-…BE0AA7` | Khớp |
|---|---|---|---|
| Ngày (giờ VN) | 16/10/2026 | `order_date` 2026-10-16; `snapshot_at` 09:23:10 (+07) | ✓ |
| Nguồn / phạm vi | DEMO, lô DEMO đang hoạt động | `data_source` DEMO, `scope_key` `DEMO-20261014080556-5342EB` (= lô ACTIVE duy nhất), `source_batch_id` `DEMO-B20261016` | ✓ |
| Số dòng nguồn | 151 | `rows_read` 151, `rows_valid` 151, `rows_error` 0 | ✓ |
| Số khóa SKU × FC | 53 | 53 dòng | ✓ |
| Khóa thiếu / thừa | — | 0 / 0 | ✓ |
| `cumulative_qty` từng khóa | 53 giá trị | khác biệt 0 | ✓ |
| Tổng số lượng | 151 | 151 | ✓ |
| NULL khóa / số lượng | — | 0; mọi số lượng > 0 và nguyên | ✓ |
| `source_updated_at` | DEMO không có | NULL ở cả 53 dòng | ✓ |
| Khóa ngoài lịch sử của scope | — | 0 (mọi SKU × FC có trong `demand_daily` của scope) | ✓ |
| Liên kết job | job MANUAL | `job_id` = `JOB-…A7374B`, `scheduled_slot` NULL, `is_catch_up` 0, thời điểm đọc nằm trong thời gian chạy job | ✓ |

## II.8 Trùng, thiếu, sai ngày, sai phạm vi; so với snapshot trước

| Kiểm tra | Kết quả |
|---|---|
| Trùng khóa trong snapshot | 0 (thêm khóa chính `snapshot_id, sku_id, fc_id`) |
| Số snapshot của job | đúng 1 |
| Snapshot trước cùng ngày `SNP-20261016010020-4304FC` (mốc 08:00, 67 dòng / 37 khóa / tổng 67) | tái tạo đúng từ nguồn; cùng ngày, scope, nguồn |
| Tính lũy kế | 37/37 khóa của 08:00 có mặt lúc 09:23, không khóa nào giảm; 24 khóa tăng, 16 khóa mới; dòng đọc 67 → 151 |
| Snapshot trong ngày | 2: 08:00 (Lịch), 09:23 (Thủ công) — không trùng thời điểm, không chạy bù |
| Sai ngày / sai phạm vi | không có |
| Ghi sang BigQuery / production | không: `data_source` DEMO ở cả 13 snapshot; không job BigQuery; `sync_state.bq_status` không đổi (lần kiểm tra cuối 15/10); log hôm nay không có dòng BigQuery/WARN/ERROR; `server.err.log` rỗng |

## II.9 Sai lệch phát hiện và nguyên nhân

Kiểm tra "thẻ D-0 hiển thị lần chạy thủ công trong 30 giây" **không đạt**: sau khi bấm *Chạy ngay*, thẻ hiện "Đã tạo
job: JOB-20261016022310-A7374B" và *Lần chạy gần nhất: 09:23 Đang chạy*, nhưng không tự cập nhật khi job xong. Nguyên nhân
(đọc `frontend/src/pages/Schedules.tsx`, dòng 79–83): nút gửi POST rồi tải lại dữ liệu **một lần** ngay sau đó, lúc job
còn chạy trong thread nền; trang không tự làm mới định kỳ. Backend đúng (API trả `last_run` = job thủ công, SUCCEEDED);
bấm *Làm mới* hiển thị đúng (9/9, II.3). Ảnh hưởng: chỉ hiển thị. **Không sửa** trong đợt này vì cần build/cài thêm một
bản (ngoài phạm vi). Đề xuất bản sau: tự làm mới vài giây/lần khi `last_run` đang PENDING/RUNNING.

## II.10 Không chạy D-1, không huấn luyện, không truy vấn BigQuery thật

- Job tạo từ lúc triển khai tới 10:01: đúng 2 — `D0_SYNC` MANUAL 09:23 và `D0_SYNC` SCHEDULE 10:00. Không job D-1, không job huấn luyện; thẻ Huấn luyện:
  lần chạy gần nhất vẫn 14/10/2026 15:06.
- BigQuery: `bigquery_production_enabled=false`; `/api/sync/status` `flows_enabled = {D1_SYNC: false, D0_SYNC: true}` với
  nguồn DEMO. Công tắc D-0 của 1.1.8 dùng chung cho mọi nguồn (trang *SQL nguồn* cũng hiện lịch D0 bật), nhưng D-0
  BigQuery **không thể chạy**: nguồn là DEMO; không thể chuyển nguồn sang BIGQUERY khi production chưa bật
  (`SOURCE_NOT_READY`); và D0 SQL chưa có phiên bản được kích hoạt (`SQL_NOT_VALIDATED`). Khi sau này chuyển sang
  BigQuery, kiểm tra thẻ D-0 trước (tắt nếu chưa muốn đọc D-0 từ BigQuery).
- Không sửa SQL, schema, logic nghiệp vụ, dữ liệu đầu vào; không nâng phiên bản; không chèn DB trực tiếp.

## II.11 Kiểm thử: đạt / không đạt / chưa thực hiện

| Kiểm thử | Loại | Kết quả |
|---|---|---|
| Prechecks + `-CheckOnly` + triển khai + post-checks của script | cài đặt thật | đạt |
| Đối chiếu trước/sau (số dòng 20 bảng, model, backup, cấu hình, storage) | DB thật, chỉ đọc | đạt |
| Backup mới đọc được | bản sao trong scratchpad | đạt 2/2 |
| `data-check` | DB thật, chỉ đọc | đạt (1 WARN đã biết) |
| Giao diện sau nâng cấp | trình duyệt, app thật, chỉ đọc | 15/15 |
| Bật D-0 qua giao diện | trình duyệt, app thật | 14/14 |
| Khởi động lại giữ cấu hình | app thật | đạt |
| Chạy D-0 thủ công qua giao diện | trình duyệt, app thật | 7/8 (II.9) |
| Giao diện sau *Làm mới*, trang Lịch sử Snapshot D0 | trình duyệt, app thật, chỉ đọc | 9/9 |
| Đối chiếu snapshot ↔ nguồn DEMO tính lại | DB thật `mode=ro` + tính lại cô lập | 20/20 |
| Chống chạy trùng / idempotency / lease lock / retry không ghi lần hai + toàn bộ test 1.1.8 | unit/integration, DB tạm cô lập | 26/26 (`logs\development\pytest_118_dedupe_20261016_092539.log`) |
| Rollback `-CheckOnly` | cài đặt thật, chỉ đọc | đạt |
| Mốc lịch D-0 10:00 sau nâng cấp + đối chiếu snapshot | app thật, DB `mode=ro` | đạt, 20/20 (II.12) |
| Chống trùng bằng cách bấm chạy lần hai trên app thật | — | **không thực hiện** (không tạo thêm snapshot thật; đã kiểm bằng code + test cô lập) |
| Rollback thật | — | không thực hiện (không cần) |
| BigQuery thật (D-1/D-0) | — | không thực hiện: chặn bởi thiếu OAuth client + IAM |
| Lint | — | chưa cấu hình |

## II.12 Mốc lịch D-0 10:00 (lần chạy theo lịch đầu tiên sau nâng cấp) — xác minh riêng

Vòng kiểm tra chỉ đọc kết thúc lúc 10:00 khi thấy job của mốc. Đối chiếu bằng cùng phương pháp II.7: **20/20**.

| Mục | Giá trị |
|---|---|
| Job | `JOB-20261016030003-935A2C`, khóa `D0_SYNC:2026-10-16T10:00`, trigger SCHEDULE, lần thử 1/4, **SUCCEEDED**, 10:00:03 → 10:00:04 |
| Snapshot | `SNP-20261016030004-13CC83`, DEMO, scope `DEMO-20261014080556-5342EB`, ngày 16/10/2026, `scheduled_slot` 10:00 (+07), `is_catch_up` 0 |
| Nguồn ↔ snapshot | 209 dòng nguồn = `rows_read`/`rows_valid` 209, lỗi 0; 59 khóa = 59 dòng; thiếu/thừa 0; số lượng lệch 0; tổng 209 = 209; NULL 0 |
| So với 09:23 (thủ công) | 53/53 khóa còn đủ, không khóa nào giảm; 28 khóa tăng, 6 khóa mới; 151 → 209 dòng |
| Snapshot trong ngày | 3: 08:00 (Lịch), 09:23 (Thủ công), 10:00 (Lịch) — mỗi job đúng 1 snapshot, không chạy bù, không trùng |
| Thay đổi DB | `job_runs` +1, `d0_snapshots` +1, `d0_snapshot_values` +59, `audit_log` +1; cấu hình, model, backup không đổi |
| Sau mốc | D-0 BẬT, lần tiếp theo 12:00 · 14:00; D-1 TẮT; huấn luyện BẬT 07:00 (17/10); scheduler `{d1: false, d0: true, train: true}`; log không WARN/ERROR/BigQuery; `server.err.log` rỗng |

Như vậy D-0 DEMO đã chạy lại đúng lịch mỗi 2 giờ sau nâng cấp.

## II.13 Còn lại / quyết định

- Lỗi hiển thị sau *Chạy ngay* (II.9): sửa ở bản sau nếu cần.
- D-1 / D-0 BigQuery: chờ quản trị Google cấp OAuth Desktop client + IAM; chọn D0 SQL v1/v2; quy tắc đơn hủy.
- Từ 1.1.8 (gồm 1.1.7): huấn luyện 07:00 khi đã có model đang dùng chỉ tạo **model ứng viên chờ duyệt**
  (`PROMOTION_REVIEW_REQUIRED`) — forecast không tự thay; công bố bằng nút duyệt (chờ quy tắc duyệt của nghiệp vụ).
