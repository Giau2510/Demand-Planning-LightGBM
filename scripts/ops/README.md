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
