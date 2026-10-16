# CLAUDE.md

@AGENTS.md

## Claude Code specifics

* Shared rules are in `AGENTS.md` (imported above); this file adds only what is specific to Claude Code.
* Project subagents: `.claude/agents/repo-scout.md` (read-only search, `haiku`) and `.claude/agents/data-reviewer.md`
  (read-only data/migration review, `sonnet`). Use them only under the task contract in
  [docs/agents/GOVERNANCE.md](docs/agents/GOVERNANCE.md); at most two specialists at a time; do not pass a per-call
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
