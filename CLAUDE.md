# CLAUDE.md

@AGENTS.md

## Quy tắc dữ liệu bắt buộc

@docs/01_quy_tac/quy_tac_du_lieu.md

## QUY TẮC CỐ ĐỊNH forecast_used (quyết định cuối của chủ dự án 05/11/2026 – mọi phiên tuân theo, KHÔNG hỏi lại)

Cột `forecast_used` của file Excel hằng ngày (số cuối cùng dùng để mua hàng):

* Cấu hình LIGHTGBM và có `lightgbm_forecast` (kể cả = 0) -> dùng `lightgbm_forecast`. KHÔNG thay số 0 bằng Avg (kiểm
  theo từng SKU tháng 10: thay bằng Avg làm 54,5 % SKU lệch nhiều hơn, chỉ 5 % đúng hơn; tổng lệch tăng từ 18.971 lên
  81.439).
* Cấu hình LIGHTGBM, SKU × FC ngoài phạm vi lần chạy (không có `lightgbm_forecast`) -> **0** với MỌI tiền tố mã (MEDX và
  mã khác), `fallback_reason` = `NGOAI_PHAM_VI_GAN_0`.
* Lần chạy SEL2 hôm nay lỗi / cũ (không có lần chạy của ngày D), hoặc SKU × FC trong phạm vi thiếu số (bổ sung của chủ
  dự án 05/11/2026, thay quy tắc "-> Avg" trước đó): lấy `lightgbm_forecast` của LẦN CHẠY SEL2 THÀNH CÔNG GẦN NHẤT có số
  cho đúng `target_date` đó, với điều kiện lần chạy đó cách `forecast_date` hôm nay KHÔNG QUÁ 3 NGÀY;
  `fallback_reason` = `DUNG_SO_LAN_CHAY_TRUOC`, ngày của lần chạy đã dùng ghi trong `flags`. Không có lần chạy nào trong
  3 ngày có số đó -> `avg_demand` (`STALE` / `KHONG_CO_SO`).
* Ngày lần chạy hôm nay lỗi (chủ dự án sửa 05/11/2026): dùng PHẠM VI của lần chạy SEL2 thành công gần nhất trong 3 ngày
  – mã TRONG phạm vi đó -> số của lần chạy đó (`DUNG_SO_LAN_CHAY_TRUOC`); mã NGOÀI phạm vi đó -> 0
  (`NGOAI_PHAM_VI_GAN_0`), giống ngày bình thường. CHỈ khi KHÔNG có lần chạy thành công nào trong 3 ngày mới dùng Avg cho
  toàn bộ (`STALE`).
* Cấu hình AVG_DEMAND (mã mới mặc định Avg): dùng `avg_demand`; không có `avg_demand` nhưng có `lightgbm_forecast` ->
  dùng `lightgbm_forecast`.
* `forecast_used` LUÔN làm tròn: < 0,2 -> 0, còn lại làm tròn LÊN; KHÔNG BAO GIỜ trống (không có số nào -> 0,
  `KHONG_CO_SO_NAO`). `lightgbm_forecast` và `avg_demand` giữ số gốc để đối chiếu.

## Claude Code specifics

* Shared rules are in `AGENTS.md` (imported above); this file adds only what is specific to Claude Code.
* Project subagents in `.claude/agents/`, all pinned to `model: opus` (owner decision 2026-10-26): `repo-scout`
  (read-only search), `data-reviewer` (read-only data/migration review), `coder` (implements an approved task),
  `tester` (test files only) and `reviewer` (read-only diff review). Use them only under the task contract in
  [docs/01_quy_tac/GOVERNANCE.md](docs/01_quy_tac/GOVERNANCE.md); at most two specialists at a time; do not pass a per-call
  `model` override except for a recorded escalation.
* Project settings `.claude/settings.json` deny file-tool edits of the live data, backups and the per-user storage
  configuration, and reads of Google credential files. They do not stop shell commands; the rules in `AGENTS.md`
  section 4 still apply to PowerShell/Bash.
* Temporary scripts, DB copies and test outputs go to the session scratchpad, never into the repository or the data
  folders. Name scratchpad files to the user with their full absolute path.
* The shell is Windows PowerShell 5.1 (and Git Bash). `Set-Location` fails on 8.3 short paths containing `~`; use the
  long path. `python -I` ignores `PYTHONUTF8`; use `-X utf8` for UTF-8 console output.
* Long-running commands (backend suite about 2.5 min, package build) run in the background; do not poll.
* Memory: durable facts about this installation live in the user's Claude memory; do not duplicate code facts there.

## Quy trình làm việc (orchestrator + subagents)

Set up 2026-10-26 at the owner's request. It runs inside the rules of `AGENTS.md` (data safety first) and
[docs/01_quy_tac/GOVERNANCE.md](docs/01_quy_tac/GOVERNANCE.md) (task contract, at most two specialists at a time, bounded
retries).

* The main session is the orchestrator. Always answer the user in Vietnamese.
* **Discuss.** When the user describes a requirement or a bug: read the relevant code (`repo-scout` for broad
  searches) and propose an approach, with alternatives and risks where they exist. Do not edit code in this phase.
* **Plan.** Split the work into small tasks; each states its objective, the files involved (read / owned) and the done
  criteria. Wait for the user's confirmation ("làm đi", "ok", "triển khai") before any edit.
* **Implement.** Per task: `coder`, then `tester`, then `reviewer`. Independent tasks that own disjoint files may run in
  parallel, at most two agents at a time. Subagents do not see the conversation: every delegation carries a full task
  contract (GOVERNANCE.md section 3) with the requirement, verified facts, owned files, constraints, commands to run
  and done criteria. Schema or data-handling changes also go to `data-reviewer` and are checked by the orchestrator on
  a DB copy (`AGENTS.md` section 4). The orchestrator checks each result itself (diff, targeted tests) before relying
  on it.
* **Fix loop.** A Critical finding from `reviewer` (nghiêm trọng) goes back to `coder`, then `tester` and `reviewer`
  again; at most two rounds, then ask the user. Should-fix (nên sửa) and Suggestion (gợi ý) findings are listed for
  the user in the summary.
* **Reviewer changed nothing.** Record `git status --porcelain` and `git diff --stat` before each `reviewer` run and
  run them again after it. Any unexpected difference: stop and report it to the user before doing anything else.
* **Turn limit.** A subagent that stops at its `maxTurns` (result not DONE) is continued with `SendMessage`, or the
  remaining work is split into a smaller task contract; tell the user either way.
* **Summary** (short): what was done, changed files, test results with counts and kind, review result, what remains.
  Release-level batches still follow `AGENTS.md` sections 10 and 11.
* The orchestrator edits code itself only for very small changes (a few lines). Commit, push and deployment still need
  the user's explicit approval (`AGENTS.md` section 8); subagents never do them.

## Chế độ vận hành (chủ dự án 03/11/2026, áp dụng cho mọi việc)

* **Tự chạy liên tục** mọi bước đã duyệt: xong bước này tự sang bước sau, không hỏi lại. Chỉ dừng hỏi khi (1) chốt
  an toàn không đạt; (2) phải xoá / ghi đè dữ liệu ngoài danh sách đã duyệt; (3) thay đổi ảnh hưởng mua hàng (cấu hình
  forecast_source, tắt chạy thử). Khi phải chờ: nói rõ đang chờ gì trong chat VÀ bật thông báo Windows
  (`scripts\ops\toast.ps1`).
* **Báo trạng thái liên tục:** `D:\Buymed\Lightgbm AI\STATUS.md` cập nhật mỗi 10 phút (giờ, bước, x/y, dự kiến xong,
  RAM / commit trống, lỗi gần nhất); chat báo ngắn sau mỗi bước và ít nhất mỗi 30 phút; thông báo Windows khi xong bước
  lớn, khi lỗi, khi dừng, khi cần chủ dự án.
* **Chống kẹt:** mọi việc nặng có lệnh chờ nền báo khi xong / dừng / lỗi + giám sát; 15 phút không có tiến độ mới hoặc
  tiến trình chết -> báo ngay (chat + thông báo). Lỗi tạm (mạng, bộ nhớ) -> tự thử lại 1 lần rồi báo. Không bao giờ để
  phiên đứng yên im lặng.
* Việc nhiều bước chạy qua bộ chạy độc lập `scripts\ops\runner\` (Scheduled Task + watchdog + ntfy) khi đã test đạt;
  khi đã giao cho runner, phiên chat chỉ đọc STATUS.md và báo lại.

## Khoá vận hành và tên phiên (chủ dự án 05/11/2026)

* **Mọi báo cáo** (chat, file báo cáo, thông báo điện thoại) mở đầu bằng `[tên phiên]`.
* **Khoá vận hành** `D:\Buymed\Lightgbm AI\run\OPS_LOCK` (JSON: `session`, `job`, `started_at`, `run`): phiên nhận một
  thao tác production (ghi DB, cài, dừng app, sao lưu/khôi phục) tạo khoá TRƯỚC khi bắt đầu và xoá khi xong. Có khoá
  của phiên khác: không thao tác production, chỉ đọc và báo lại; không xoá khoá của phiên khác.
* Runner (`runner.py`, `common.ops_lock_block`) và mọi script vận hành (`scripts\ops\*.py`) kiểm tra khoá trước khi ghi
  DB / cài / dừng app; chỉ chạy khi không có khoá hoặc khoá ghi đúng `run` của nó. Lệnh vận hành chạy tay cũng phải
  kiểm tra khoá trước.
* Khung giờ chặn của bước cài chỉ xét lúc BẮT ĐẦU (`"window_kills": false`): không bao giờ dừng giữa chừng một bước
  cài. Runner giữ máy không ngủ trong lúc chạy (SetThreadExecutionState, không đổi cài đặt nguồn), báo điện thoại khi
  máy chạy pin, và với `"notify_all": true` báo mọi thay đổi trạng thái (bắt đầu, xong, chờ, dừng vì khung giờ, lỗi);
  watchdog báo khi 15 phút không có tiến độ.

## Quy tắc vận hành cố định (chủ dự án 06/11/2026 – thay mọi quy định giờ làm việc trước đó)

* **Bỏ giới hạn giờ làm việc:** mọi việc, kể cả việc nặng (test, backtest, cài đặt), chạy BẤT KỲ GIỜ NÀO, làm liền
  không chờ. Mỗi lúc 1 việc nặng; RAM / commit dưới ngưỡng thì chờ, không chạy chồng.
* Tránh khung lịch production **23:45–00:15** và **00:45–03:45**; cài đặt không trùng lượt D0 và làm mới dự báo.
* Giữ khoá vận hành OPS_LOCK; mọi báo cáo mở đầu bằng [tên phiên]; báo điện thoại MỖI bước, báo NGAY khi trễ quá 30 phút
  hoặc lỗi; giữ cơ chế chịu máy ngủ / mất mạng / chạy bù đêm. Quy tắc forecast_used cố định: KHÔNG thay đổi.
* **Tự duyệt tới 07:00 ngày 07/11/2026** (mỗi lần tự duyệt: ghi `docs\05_nhat_ky_quyet_dinh.md` + báo điện thoại "đã tự
  duyệt: …, căn cứ: …"), chỉ khi đạt đủ tiêu chí:
  - File 06/11: TOM_TAT phiên bản 1.4.3, dữ liệu đến 05/11, is_stale = 0 (hoặc ghi rõ dùng số lần chạy trước); 2 sheet
    BD/HN đủ SKU×kho × 20; 0 dòng sai quy tắc forecast_used; seller_code + product_code đúng 100 % → coi như chủ dự án đã
    xác nhận (chạy backtest ngày 8–20 và kiểm chứng học lại mỗi ngày).
  - Giao diện 1.4.4: bố cục, tên trang, menu giữ nguyên 100 % (so ảnh trước–sau); số trên trang khớp 100 % file Excel
    cùng ngày (mẫu 50 SKU×kho mỗi trang + tổng theo ngày) → được cài.
  - Cài 1.4.4: toàn bộ test đạt, reviewer không có lỗi nghiêm trọng, sao lưu + thử khôi phục đạt, kiểm tra sau cài đạt →
    được cài và push github/1.4.4 + tag v1.4.4. Lỗi bất kỳ bước nào: quay về 1.4.3, bảo đảm app chạy, báo.
  - Dọn thư mục: mục HỎI theo quy tắc chủ dự án 06/11 (worktree không có thay đổi cần giữ → nén vào archive\worktrees\
    rồi xoá; có → giữ và báo; bản sao g1: GIỮ).
* **KHÔNG tự duyệt** (chỉ chuẩn bị sẵn, chờ chủ dự án "đồng ý"): đổi cách dự báo ngày 8–20 trên production; bật học lại
  mỗi ngày trên production; mọi thay đổi quy tắc forecast_used, config nguồn dự báo, hoặc xoá dữ liệu trong DB production.
