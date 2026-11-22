import { useEffect, useRef, useState } from "react";
import { get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, ErrorBox, Loading, OkBox, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "./ui";
import { Icon } from "./icons";
import { normReason, reasonLen, BusyNotice, DescriptionList, ErrorDetails, OpsLockLine, OtherTaskNotice, TaskBox, TypedConfirm, fmtGB, usePolledStatus, useServerConfirmText, useTr, type BusyInfo, type OtherTask, type TaskInfo } from "./guardedShared";

// 1.4.15 (lot 5): card "Quay lại lần đồng bộ" of the page "SQL nguồn & đồng bộ": the sync runs (GET /api/sync-runs) with whether each
// can be rolled back and why not, a preview (writes nothing), the typed text + reason, then the rollback (202, background, a backup
// first) with its status. The rollback restores the stored demand rows only: models and forecasts already made are NOT undone.

interface Desc { code?: string; vi?: string; en?: string }
interface Run {
  id: string; kind: string; status: string; window_start?: string | null; window_end?: string | null; started_at?: string; finished_at?: string | null;
  summary?: Record<string, any>; rollbackable: boolean | null; reason: string | null; conflicts?: number; rolled_back_by?: string | null; rolled_back_at?: string | null;
}
interface RunsResponse { configured: boolean; runs: Run[]; description: Desc[]; task?: TaskInfo | null; max_entries?: number }
interface Preview {
  sync_run_id: string; kind: string; entries: number; rows_inserted_by_run: number; rows_updated_by_run: number; rows_deleted_by_run: number;
  units_now: number; units_after_rollback: number; first_day: string | null; last_day: string | null; days: number; finalized_days: number;
  holds_to_release: number; holds_to_restore: number; holds_of_run_already_released: number; signature: string; confirm_text: string; reason_min_length: number;
  busy: BusyInfo & { window_soon?: string | null; schedule_times?: { setting: string; time: string }[] };
  disk?: { ok: boolean; need_bytes: number; free_bytes: number; missing_bytes: number; backup_dir: string };
  ops_lock_checked: boolean; ops_lock_source?: string | null; ops_locks?: { env: string; path: string }[]; busy_other_task?: OtherTask | null; description: Desc[];
}
interface Status { task?: TaskInfo | null; running?: boolean; description?: Desc[] }

export default function SyncRollbackCard() {
  const { t } = useI18n();
  const tr = useTr();
  const runs = useAsync(() => get<RunsResponse>("/api/sync-runs"), []);
  const status = usePolledStatus<Status>("/api/sync-rollback/status");
  const act = useAction();
  const [pv, setPv] = useState<Preview | null>(null);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const serverText = useServerConfirmText(act.error, "SYNC_ROLLBACK_CONFIRM_REQUIRED", () => setTyped(""));

  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    const now = status.data?.task?.status;
    if (prev.current === "RUNNING" && now && now !== "RUNNING") void runs.reload();
    prev.current = now;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.data?.task?.status]);

  const task = status.data?.task ?? null;
  const result = (task?.result ?? null) as Record<string, any> | null;
  const busyNow = !!pv?.busy?.busy || !!pv?.busy?.window_soon || (pv?.busy?.schedule_times ?? []).length > 0;
  const confirmText = serverText ?? pv?.confirm_text ?? "";
  const minReason = pv?.reason_min_length ?? 10;
  const lockedOut = !!pv?.busy_other_task || (pv?.ops_locks ?? []).length > 0;
  const canRun = !!pv && !act.busy && !lockedOut && !busyNow && pv.disk?.ok !== false && typed.trim() === confirmText && reasonLen(reason) >= minReason;

  const doPreview = async (id: string) => {
    setTyped(""); setReason("");
    const r = await act.run(() => post<Preview>("/api/sync-rollback/preview", { sync_run_id: id }));
    setPv(r ?? null);
  };
  const doRun = async () => {
    if (!pv) return;
    const r = await act.run(() => post("/api/sync-rollback", { sync_run_id: pv.sync_run_id, signature: pv.signature, confirm_text: typed.trim(), reason: normReason(reason) }), t("sr.accepted"));
    if (r) { setPv(null); setTyped(""); setReason(""); void status.reload(); }
  };

  const d = runs.data;
  const desc = pv?.description ?? d?.description ?? status.data?.description ?? [];
  return (
    <Card icon="batches" title={t("sr.title")} actions={<button onClick={() => { void runs.reload(); void status.reload(); }} disabled={runs.loading}><Icon name="refresh" />{t("bg.refresh")}</button>}>
      <div className="stack">
        <p className="small muted">{t("sr.intro")}</p>
        <div className="alert warn small" data-testid="sr-description-box"><b>{t("sr.what")}</b><DescriptionList items={desc} testid="sr-description" /></div>
        {runs.error ? <ErrorBox error={runs.error} /> : !d ? <Loading /> : !d.configured ? <p className="small muted">{t("hl.not_configured")}</p> : (
          <div className="scroll">
            <table className="tbl small" data-testid="sr-runs">
              <thead><tr><th>{t("sr.col_run")}</th><th>{t("sr.col_kind")}</th><th>{t("sr.col_status")}</th><th>{t("gp.col_time")}</th><th>{t("sr.col_summary")}</th><th>{t("sr.col_can")}</th><th /></tr></thead>
              <tbody>
                {d.runs.map((r) => (
                  <tr key={r.id} data-testid={`sr-run-${r.id}`}>
                    <td className="mono">{r.id}</td><td>{r.kind}</td><td>{r.status}</td><td className="nowrap">{fmtTime(r.started_at)}</td>
                    <td className="small">{[r.summary?.rows_written != null ? `${t("sr.rows")} ${fmtNum(r.summary.rows_written)}` : null, r.summary?.holds != null ? `${t("sr.holds")} ${fmtNum(r.summary.holds)}` : null,
                      r.window_start ? `${fmtDate(r.window_start)} → ${fmtDate(r.window_end)}` : null].filter(Boolean).join(" · ")}</td>
                    <td data-testid={`sr-can-${r.id}`}>
                      <span className={`pill ${r.rollbackable === true ? "ok" : r.rollbackable === false ? "muted" : "warn"}`}>{r.rollbackable === true ? t("sr.can_yes") : r.rollbackable === false ? t("sr.can_no") : t("sr.can_unknown")}</span>
                      {r.reason && <div className="small muted">{tr("sr.reason", r.reason)}{r.conflicts ? ` (${r.conflicts})` : ""}{r.reason === "TOO_LARGE_FOR_THE_UI" && d.max_entries ? ` (${t("sr.max_entries").replace("{n}", fmtNum(d.max_entries))})` : ""}</div>}
                    </td>
                    <td><button className="small" data-testid={`sr-preview-${r.id}`} disabled={r.rollbackable === false || act.busy} onClick={() => void doPreview(r.id)}><Icon name="search" />{t("sr.preview")}</button></td>
                  </tr>
                ))}
                {d.runs.length === 0 && <tr><td colSpan={7} className="muted">{t("sr.none")}</td></tr>}
              </tbody>
            </table>
          </div>
        )}
        <ErrorDetails error={act.error} />
        <OkBox text={act.ok} />

        {pv && (
          <div className="stack tight" data-testid="sr-confirm-area">
            <b>{t("sr.preview_title").replace("{id}", pv.sync_run_id)}</b>
            <ul className="small" data-testid="sr-preview-counts">
              <li>{t("sr.p_entries").replace("{n}", fmtNum(pv.entries)).replace("{i}", fmtNum(pv.rows_inserted_by_run)).replace("{u}", fmtNum(pv.rows_updated_by_run)).replace("{d}", fmtNum(pv.rows_deleted_by_run))}</li>
              <li>{t("sr.p_units").replace("{a}", fmtNum(pv.units_now, 2)).replace("{b}", fmtNum(pv.units_after_rollback, 2))}</li>
              <li>{t("sr.p_days").replace("{n}", fmtNum(pv.days)).replace("{a}", fmtDate(pv.first_day)).replace("{b}", fmtDate(pv.last_day)).replace("{f}", fmtNum(pv.finalized_days))}</li>
              <li>{t("sr.p_holds").replace("{r}", fmtNum(pv.holds_to_release)).replace("{s}", fmtNum(pv.holds_to_restore))}</li>
            </ul>
            <div className="alert warn small" data-testid="sr-consequences"><b>{t("sr.what")}</b><DescriptionList items={pv.description} testid="sr-preview-description" /></div>
            {busyNow && (
              <>
                <BusyNotice busy={pv.busy} />
                {pv.busy.window_soon && <div className="alert warn small" data-testid="bg-soon">{t("bg.window_soon").replace("{w}", pv.busy.window_soon).replace("{m}", "60")   /* hl.START_MARGIN_MIN: the API gives start_margin_minutes only in the 409 params (shown by ErrorDetails) */}</div>}
                {(pv.busy.schedule_times ?? []).length > 0 && <div className="alert warn small" data-testid="bg-sched">{t("bg.sched_near")} {(pv.busy.schedule_times ?? []).map((x) => `${x.setting} ${x.time}`).join(", ")}</div>}
                <div className="small bad-t" data-testid="sr-busy-locked">{t("sr.busy_locked")}</div>
              </>
            )}
            {!busyNow && <BusyNotice busy={pv.busy} />}
            {pv.disk && (
              <div className={`alert ${pv.disk.ok ? "info" : "bad"} small`} data-testid="sr-disk">
                {t("bg.disk_info").replace("{need}", fmtGB(pv.disk.need_bytes)).replace("{free}", fmtGB(pv.disk.free_bytes))}{!pv.disk.ok && <> {t("bg.disk_missing").replace("{missing}", fmtGB(pv.disk.missing_bytes))}</>}
                {" "}<span className="mono">{pv.disk.backup_dir}</span>
              </div>
            )}
            <OpsLockLine checked={pv.ops_lock_checked} source={pv.ops_lock_source} locks={pv.ops_locks} prefix="sr" />
            <OtherTaskNotice other={pv.busy_other_task} testid="sr-other-task" />
            <TypedConfirm id="sr" text={confirmText} minReason={minReason} typed={typed} setTyped={setTyped} reason={reason} setReason={setReason} />
            <div className="row">
              <button className="primary" data-testid="sr-run" onClick={doRun} disabled={!canRun}><Icon name="reset" />{t("sr.run")}</button>
              <button data-testid="sr-cancel" onClick={() => { setPv(null); act.setError(null); }}>{t("common.cancel")}</button>
            </div>
          </div>
        )}

        <div className="stack tight">
          <b>{t("sr.task_title")}</b>
          <TaskBox task={task} onRefresh={() => { void status.reload(); void runs.reload(); }} busy={status.loading} testid="sr-task">
            {result && (
              <ul className="small" data-testid="sr-task-result">
                <li>{t("sr.res_entries").replace("{n}", fmtNum(result.entries)).replace("{r}", fmtNum(result.holds_released)).replace("{s}", fmtNum(result.holds_restored))}</li>
                {result.rollback_run && <li>{t("sr.res_run")}: <span className="mono">{result.rollback_run}</span></li>}
                {result.backup_file && <li data-testid="sr-task-backup">{t("hl.res_backup")}: <span className="mono">{result.backup_path ?? result.backup_file}</span> ({fmtGB(result.backup_bytes)})</li>}
              </ul>
            )}
          </TaskBox>
        </div>
      </div>
    </Card>
  );
}
