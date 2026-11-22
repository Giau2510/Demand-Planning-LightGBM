# scripts\ops - operations tooling (owner PC)

Scripts that run around the installed app on the owner's Windows PC: Scheduled Tasks, the step runner and the release
install chains. They are not part of the app package (`scripts\build-package.ps1` does not ship them). Every script
documents itself in its header; this file is the overview.

## Owner rules they implement

* **Operations lock** `<main working tree>\run\OPS_LOCK` (JSON `session`, `job`, `started_at`, `run`): a writer of the DB,
  an install or an app stop goes on only when there is no lock or the lock names its own run
  (`runner\common.ops_lock_block`). Never remove another session's lock.
* **Blocked windows** (Vietnam time) 23:45-00:15 and 00:45-03:00 (runner default) / 03:45 (night catch-up, install):
  nothing starts inside them; `"window_kills": false` checks them only at the start of a step (an install is never
  killed midway).
* **Notifications**: Windows toast (`toast.ps1`) + phone push through ntfy (`runner\notify.py`). The topic is generated
  once into `runner\notify_config.json` (local, kept out of Git, never logged). Messages failed offline are queued
  (`notify_queue*.json`) and sent later as one summary. Texts hold status only: no data values, SKU / customer ids or
  credentials.
* Memory guard (runner: start at free commit >= 3 GB, stop < 1.5 GB), keep-awake while a run is active ONLY on AC power
  (owner 06/11: on battery the request is dropped so a closed lid sleeps; a step that stops the app still requires AC),
  battery alert.

## Scripts

| File | What it does |
|---|---|
| `runner\runner.py` | Step runner: runs `plan.json` steps in order, resumable, preconditions / gates, retries, windows, memory guard, STATUS.md + status.json, notifications. |
| `runner\watchdog.py` | Read-only check of a run dir (runner alive, progress in 15 min, production jobs); alerts. |
| `runner\common.py`, `runner\notify.py` | Shared helpers (mutex, atomic JSON, OPS_LOCK, power, network); notifications. |
| `runner\register-runner.ps1`, `runner\register-watchdog.ps1` | Register the tasks `DemandForecastRunner` / `DemandForecastRunnerWatchdog` (logon + every 5 min). |
| `excel20.py`, `register-excel20.ps1` | Task `DemandForecastExcel20` (every 5 min): rewrites only the latest copy of the daily Excel into the 20-day layout. Read-only on the DB. |
| `night_catchup.py`, `register-night-catchup.ps1` | Task `DemandForecastNightCatchup` (every 10 min): app watch + one manual D-1 / refresh / export catch-up after a failed night D-1. Fail-closed. |
| `cai_141.py` .. `cai_144.py` | Install chains of 1.4.1-1.4.4 run through the runner (release, backup, restore test, deploy, postcheck, export). Kept as the template of the next chain; version, day and run name are fixed in each file. |
| `e1_backup.py`, `e1_restore.py`, `fs_restore_verify.py` | Online backup with the installed code + restore test in an isolated temporary copy (used by the cai_14x chains). |
| `status_monitor.py` | Read-only STATUS.md / toast monitor of the 03/11 E2 / E3 runs (historical). |
| `toast.ps1` | Windows toast (built-in WinRT API). |
| `don_dep_dinh_ky.ps1`, `register-don-dep-task.ps1` | Weekly cleanup (dry run unless `-Apply`); see its header and the rules below. |
| `don_dep_current.ps1` | Stable entry point of the cleanup: runs `don_dep_dinh_ky.ps1` of the INSTALLED version (`current.txt`); exit 2 when `current.txt` or that script is missing. |
| `don_dep_giu.txt`, `don_dep_ket_luan.txt` | `reports\` folders kept entirely / concluded experiments (read next to the script that runs). |
| `<project>\docs\quy-tac\keep_list.txt` | Master keep list of the cleanup (`-KeepListMaster`, owner 18/11/2026): paths / wildcard patterns never deleted by any group. |
| `ops_config.py` | Machine paths of all the Python scripts above (next section). |
| `tests\` | Isolated tests (temporary folders, fake ntfy / app servers, no production access). |

## Register (current Windows user; `-PlanOnly` prints the definition, `-Unregister` removes it)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\register-excel20.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\register-night-catchup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\runner\register-runner.ps1 -Plan <plan.json> -RunDir <run dir> -StatusCopy <project root>\STATUS.md
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\runner\register-watchdog.ps1 -RunDir <run dir>
```

The tasks run `<project root>\.venv\Scripts\pythonw.exe` (override: `-Python`). Register them from the copy that
should run (normally the main project folder, not a release worktree).

## Configuration (`ops_config.py`)

Priority: env `DF_OPS_<KEY>` > `scripts\ops\ops_config.json` (optional, kept out of Git; template
`ops_config.example.json`) > default. With nothing set the defaults reproduce the owner's PC.

| Key | Default |
|---|---|
| `project_root` | repository root holding this folder |
| `localappdata` | `%LOCALAPPDATA%` |
| `storage_json` | `<localappdata>\DemandForecast\storage.json` (read only) |
| `progs` | `<localappdata>\Programs\DemandForecast` |
| `remote_dir` | `<localappdata>\DemandForecastRemote` |
| `venv` | `<project_root>\.venv\Scripts\python.exe` |
| `reports` | `<project_root>\reports` |
| `status_md` | `<project_root>\STATUS.md` |
| `tmp` | `<project_root>\..\tmp` (restore tests, watchdog ignore path) |
| `worktrees` / `ban` | `<project_root>\..` / `<worktrees>\ban-<version>` (cai_14x release worktree) |
| `ops_lock` | `<main working tree>\run\OPS_LOCK` (env `DF_OPS_LOCK` also accepted) |
| `data_dir`, `backups` | `data_dir` / `backups_dir` of storage.json |
| `live_db` | `<data_dir>\db\app.db` (opened `mode=ro`) |

The lock is `<main working tree>\run\OPS_LOCK`: a copy run from a git worktree of the same repository (e.g. a release
worktree `ban-<version>`) resolves the main working tree from its `.git` file and shares the live lock; a copy outside
the repository must set `DF_OPS_LOCK` / `ops_lock`. The PowerShell scripts compute their paths from `$PSScriptRoot`
(and `DF_OPS_TMP` for the watchdog ignore path); they do not read `ops_config.json`.

## Tests

```powershell
cd scripts\ops\tests
..\..\..\.venv\Scripts\python.exe -X utf8 -B test_night_catchup.py
..\..\..\.venv\Scripts\python.exe -X utf8 -B test_x20.py      # needs openpyxl; uses backend\app\ml\sel2\xlsx_stream.py
..\..\..\.venv\Scripts\python.exe -X utf8 -B test_resA.py     # runner / notify / cai_143 / night_catchup, several minutes
..\..\..\.venv\Scripts\python.exe -X utf8 -B test_awake.py    # keep-awake on AC only (fake power file)
```

`tests\ops_test_env.py` points every `DF_OPS_*` path into a fresh temporary folder before the scripts are imported
(removed after a passing run, kept after a failure). Each script prints PASS / FAIL lines and exits 1 on any failure.

## Cleanup rules (`don_dep_dinh_ky.ps1`, owner 03/11 + 08/11/2026)

Dry run unless `-Apply`; when in doubt an entry is KEPT and listed as `kept_uncertain`. current / previous version =
`current.txt` and the newest EXISTING version folder older than it.

The weekly task (`register-don-dep-task.ps1`, default since 08/11) runs `don_dep_current.ps1`, i.e. the cleanup script
of the INSTALLED version (`-Direct` registers this folder's script instead). The installed script reads
`don_dep_giu.txt` / `don_dep_ket_luan.txt` next to itself (the installed copy), except that the wrapper passes
`<ProjectRoot>\scripts\ops\don_dep_giu.txt` / `don_dep_ket_luan.txt` (`-KeepListFile` / `-ConcludedListFile`) when they
exist and the installed script has these parameters.

Master keep list (owner 18/11/2026): `<ProjectRoot>\docs\quy-tac\keep_list.txt` (`-KeepListMaster` overrides it), one
path or wildcard pattern (`*` `?`) per line, relative to `<ProjectRoot>`, `#` comment lines and ` #` end-of-line comments
(reason + date). It is checked right before every deletion of every group (`Test-KeepListBlocked`, also before
`prune-artifacts.ps1 -Apply`): a candidate that equals, lies inside or contains a kept path, or that (or a parent folder)
matches a pattern, or a folder holding (at any depth) an entry that matches a pattern (`contains kept (pattern)`; a folder
that cannot be listed counts as kept), is not deleted and logged as a `KEEP_LIST` line; a kept backup zip keeps its
companions. Missing, empty or unreadable list (one bad line is enough) -> fail-closed: nothing deleted, exit 1, with
`-Apply` one notice through `runner\notify.py` (`<ProjectRoot>\.venv` python): `notice_status` sent only when notify.py
exits 0, else `failed` (logged `BAO THAT BAI / notify FAILED`) and the next `-Apply` run tries again. Every run prints
the table `MUC BI KEEP_LIST CHAN`.

Plan lock (1.4.15, owner 19/11/2026). How to delete:
1. Dry run (no `-Apply`, the arguments you want, e.g. `-Groups tmp,claude_temp -TmpKeep ...`). It prints and records
   `PLAN_HASH` (report `plan_hash`; the hashed text is `logs\don_dep\don_dep-<stamp>.plan.txt`) and `KEEP_LIST_SHA256`
   (report `keep_list.sha256`: SHA-256 of the keep list bytes that were parsed).
2. Check the plan (`.txt` / `.plan.txt`: every candidate, every `KEEP_LIST` block) and approve it.
3. Run the SAME arguments + `-Apply -PlanHash <PLAN_HASH> -KeepListHash <KEEP_LIST_SHA256>` (directly or through
   `don_dep_current.ps1`, which passes both on). The plan is computed again; a missing / malformed hash or a different
   value -> exit 2, nothing archived or deleted, report `mode = APPLY_REFUSED` with the reasons (`keep_list changed after
   the plan`, `plan changed`). The plan changes with the arguments (groups, `-IncludeDist`, `-DistKeep`, `-TmpKeep`,
   `-ClaudeKeep`, ages, roots, keep list path), the group status, every candidate path (logs: also its archive zip) and
   every keep list block (no size, no time); entries also age into the plan (30 days, 7 days, 24 h): apply soon after the
   dry run, else make a new one.

With `-Apply`, `-KeepListMaster` must be empty or `<ProjectRoot>\docs\quy-tac\keep_list.txt` (else exit 2). A keep list
that is not usable keeps the fail-closed behaviour above (exit 1, notice), whatever the hashes. Right before a folder
candidate is deleted, a folder written at or after the start of the run (itself or anything in it) is skipped
(`changed after the plan`). `-IncludeDist`: `prune-artifacts.ps1 -Apply` (which computes its own list again) runs only
when its dry run (same `-Keep`) lists exactly the planned dist candidates that still exist (`dist_versions` may have
removed some); otherwise, or when its output cannot be read (needs the final `Dry run: nothing deleted.` line), it is not
run (error, exit 1); a `dist\` / `release\` entry that disappears during its run and is not planned -> error, exit 1.
`don_dep_current.ps1 -Apply` is refused (exit 2) when the INSTALLED script does not declare `-KeepListMaster`,
`-PlanHash` and `-KeepListHash` (versions 1.4.0 - 1.4.14); its dry run still runs. RISK: the old task
`DemandForecastCleanup` calls `...\1.4.0\scripts\ops\don_dep_dinh_ky.ps1 -Apply` directly, which knows neither the keep
list nor the plan lock: keep it DISABLED; before enabling it again (owner approval, after 1.4.15 is installed) back the
task up and point it at `don_dep_current.ps1` (a weekly task cannot pass the hash of a plan approved the same week).
`don_dep_current.ps1 -Groups a,b` (1.4.15) passes the groups on as one comma list; it is refused (exit 2, nothing run,
never the default groups instead) when `-Groups` is empty or the INSTALLED script has no `-Groups` parameter. The plan
hash depends on the groups chosen, so `-Apply` takes the same `-Groups` as the dry run:
`don_dep_current.ps1 -ProjectRoot "D:\Buymed\Lightgbm AI" -Groups backups` (dry run), then the same
`-Groups backups -Apply -PlanHash <PLAN_HASH> -KeepListHash <KEEP_LIST_SHA256>`.

Fail-closed apply (1.4.15, S-a): a keep list check that throws right before a deletion (or before
`prune-artifacts.ps1 -Apply`) deletes nothing for that entry (error `keep list check failed`, exit 1). An unexpected
error that is not handled per entry stops every further deletion (that group and the next ones; report
`apply_stopped`, `APPLY STOPPED` line, the group gets status `error`); the `.json` / `.txt` / `.plan.txt` are still
written (entries deleted before are listed) and the exit code is 1. Errors handled per entry (an entry that cannot be
deleted) and per archive (group `logs`) are only recorded and the next entry is still checked; the failed entry itself is
never deleted. A companion file of a backup (`.sha256`, `config-*`) is deleted only when its main zip is gone right
before; a zip that was not deleted keeps its companions (`main zip not deleted: companion kept`). The plan lists them per
zip candidate (`.txt` section `TEP DI KEM / companions`: `companions <zip>: <name> (<bytes> B), ...` or `none`;
`companion_kept <name>: kept - <reason>` for every `.sha256` / `config-*` kept, e.g. a config copy without a matching
backup); report `companions` / `companions_kept` of group `backups`. Display only: the matching rule and the plan hash
do not change.

Items log (1.4.15, only with `-Apply`, never in a dry run): `logs\don_dep\don_dep-<stamp>.items.jsonl` (same stamp as
the `.json` / `.txt`; report `items_log`, `.txt` line `ITEMS_LOG:`), UTF-8 without BOM, one JSON object per line,
appended and closed line by line (a run that dies still shows what it was deleting). Every line has `t` (local time),
`t_utc`, `seq`. Events: first `{"event":"start", plan_hash, keep_list_sha256, groups, mode}`, last (when the script gets
there) `{"event":"end", exit_code, deleted_count, deleted_bytes, error_count, apply_stopped}`; `prune_start` /
`prune_end` around `prune-artifacts.ps1 -Apply`. Entry lines: `phase` (`intent` | `result`), `group`, `path`, `kind`,
`bytes` (size right before the deletion), `action`, `reason`, `plan_hash`, `mode`. Each deletion by this script
(groups other than `dist`) = an `intent` / `deleting` line written BEFORE `Remove-Item`, then a `result` line `deleted`
or `error`; every other entry gets one `result` line `not_deleted`, `blocked` (keep list, protected), `skipped` (gone,
reparse point, changed after the plan, main zip not deleted, ...) or `error`. Group `logs` works per archive zip: the
files are added to the zip, one `archived` line for the zip, then each verified file is deleted as above (intent +
result). Group `dist` has no intent line per entry (`prune-artifacts.ps1 -Apply` deletes): `prune_start` (written BEFORE
the call; `entries` = lower-case long paths of the planned entries it is about to delete, `planned_existing` = their
count), `prune_end` after it, then one `result` line per planned entry (`deleted`, `not_deleted`, `skipped`). An
`intent` line without its `result`, or a `prune_start` without `prune_end`, = the run stopped during that deletion
(check the paths). Fail-closed: log not writable at the start -> nothing archived or deleted, exit 1; an intent line
(or `prune_start`) not written -> not deleted (error). Any other line not written -> error, exit 1 (an entry already
deleted gets action `deleted`, reason `items log write failed: ...`, when the fallback line can be written; a log that fails twice for the
same entry may leave an `error` line for an entry that was deleted: nothing is lost, only the log line, known limit 22/11/2026). Example:
`{"t":"2026-11-22T11:03:53","t_utc":"2026-11-22T04:03:53Z","seq":3,"phase":"result","group":"backups","path":"D:\\...\\backups\\backup-20261101-100000-manual.zip","kind":"file","bytes":1000,"action":"deleted","reason":"","plan_hash":"a3db...","mode":"APPLY"}`.
Read it with e.g. `Get-Content <file> -Encoding UTF8 | ConvertFrom-Json | Format-Table seq, phase, action, path`.

Keep list patterns (S1, 1.4.15): a backtick in a folder name before the first wildcard is escaped too.

| Group | Candidates |
|---|---|
| backups | `<project>\backups` zips (+ `.sha256` / `config-*`) except: newest overall, last 7 days, per current / previous version the newest `*-pre-<ver without dots>.zip`, the newest backup before its install and those within 20 min before it. |
| exports | day folders outside the 30 newest AND older than 30 days; `du_bao_<day>_v<K>_bo.xlsx` of kept days older than 3 days while a newer `du_bao_<day>_v<M>.xlsx` (M > K) exists (else kept_uncertain; a `_TAM` file does not count). |
| logs | files older than 30 days, archived to `logs-archive-YYYYMM.zip` first (unchanged). |
| tmp | `D:\Buymed\tmp` entries older than `-TmpMinAgeHours` (default 24) not used by a process (unchanged); names in `-TmpKeep` are kept. |
| deploy_temp | `%TEMP%\DemandForecast-deploy-*` older than 1 day, not on a process command line. |
| reports | packaged folders: data files outside `package*` (unchanged); folders in `don_dep_ket_luan.txt`: .parquet .pkl .npz .npy .log .tmp .feather and `_v<N>` files with a higher plain `_v<M>` (code / text .py .ps1 .sql .ipynb .sh .R .bat .md .json .txt .yaml .yml always kept; lettered `_v3b` variants and matches inside `package*` -> kept_uncertain); `don_dep_giu.txt` wins. |
| installs | version folders other than current / previous; newer than current, not x.y.z or named in a scheduled task action -> kept_uncertain; used by a process -> kept; current.txt re-read before each deletion. The whole group is skipped (nothing selected) when the scheduled tasks or the process list cannot be read. |
| dist_versions | `DemandForecast-<ver>*` in `<project>\dist` and `<project>\worktrees\*\dist` of versions older than current other than previous / `-DistKeep` (newer -> kept_uncertain). **Behaviour change 08/11: deleted with `-Apply` alone** (no `-IncludeDist` needed). |
| dist | `prune-artifacts.ps1` plan (deleted only with `-Apply -IncludeDist -DistKeep`), not in the totals. |
| claude_temp | only when named in `-Groups` (never in the default run / weekly task): `%TEMP%\claude\<project>\<GUID>` session folders of finished sessions = not in `-ClaudeKeep` (session id or a prefix of >= 8 characters) AND folder older than `-ClaudeMinAgeHours` (default 24) AND its transcript `%USERPROFILE%\.claude\projects\<project>\<id>.jsonl` / `<id>\**` (when present; `-ClaudeProjectsRoot`) older than that too AND not named (folder or session id) on a process command line AND no database file in use; re-checked right before deletion. `-ClaudeTempRoot` must be a folder named `claude`. |

`-Groups a,b` runs only the named groups (unknown name -> exit 2). A `-TmpKeep` / `-ClaudeKeep` entry that matches no
entry / session folder -> exit 2 (typo guard). tmp candidates are re-checked right before deletion (processes, age, DB in
use). Owner-approved run 08/11:
`don_dep_dinh_ky.ps1 -Groups tmp,claude_temp -TmpMinAgeHours 12 -TmpKeep src148 -ClaudeKeep 145cefda,85d15b29 -Apply`;
with `-Apply` the `.txt` report lists every candidate as `deleted <group> <GB> <path>` or
`NOT deleted <group> <path> - <reason>`.

Info only: `worktree_can_remove` lines for `<project>\worktrees\*` that are clean, on a remote-tracking branch, tagged
`v<version>` and installed (removal: `archive_worktree.py`). current.txt unreadable -> backups / installs / dist_versions
select nothing.
