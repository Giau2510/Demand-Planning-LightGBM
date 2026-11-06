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
* Memory guard (runner: start at free commit >= 3 GB, stop < 1.5 GB), keep-awake while a run is active, battery alert.

## Scripts

| File | What it does |
|---|---|
| `runner\runner.py` | Step runner: runs `plan.json` steps in order, resumable, preconditions / gates, retries, windows, memory guard, STATUS.md + status.json, notifications. |
| `runner\watchdog.py` | Read-only check of a run dir (runner alive, progress in 15 min, production jobs); alerts. |
| `runner\common.py`, `runner\notify.py` | Shared helpers (mutex, atomic JSON, OPS_LOCK, power, network); notifications. |
| `runner\register-runner.ps1`, `runner\register-watchdog.ps1` | Register the tasks `DemandForecastRunner` / `DemandForecastRunnerWatchdog` (logon + every 5 min). |
| `excel20.py`, `register-excel20.ps1` | Task `DemandForecastExcel20` (every 5 min): rewrites only the latest copy of the daily Excel into the 20-day layout. Read-only on the DB. |
| `night_catchup.py`, `register-night-catchup.ps1` | Task `DemandForecastNightCatchup` (every 10 min): app watch + one manual D-1 / refresh / export catch-up after a failed night D-1. Fail-closed. |
| `cai_141.py`, `cai_142.py`, `cai_143.py` | Install chains of 1.4.1-1.4.3 run through the runner (release, backup, restore test, deploy, postcheck, export). Kept as the template of the next chain; version, day and run name are fixed in each file. |
| `e1_backup.py`, `e1_restore.py`, `fs_restore_verify.py` | Online backup with the installed code + restore test in an isolated temporary copy (used by the cai_14x chains). |
| `status_monitor.py` | Read-only STATUS.md / toast monitor of the 03/11 E2 / E3 runs (historical). |
| `toast.ps1` | Windows toast (built-in WinRT API). |
| `don_dep_dinh_ky.ps1`, `register-don-dep-task.ps1` | Weekly cleanup (dry run unless `-Apply`); see its header. |
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
```

`tests\ops_test_env.py` points every `DF_OPS_*` path into a fresh temporary folder before the scripts are imported
(removed after a passing run, kept after a failure). Each script prints PASS / FAIL lines and exits 1 on any failure.
