# CLAUDE.md

@AGENTS.md

## Quy tắc dữ liệu bắt buộc

@docs/01_quy_tac/quy_tac_du_lieu.md

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
