import { useEffect, useRef, useState } from "react";
import { get, post, qs } from "../api";
import { useI18n } from "../i18n";
import { Card, DateInput, Field, OkBox, fmtBytes, fmtDate, fmtNum, useAction } from "./ui";
import { Icon } from "./icons";
import { normReason, reasonLen, DescriptionList, ErrorDetails, OpsLockLine, OtherTaskNotice, TaskBox, TypedConfirm, usePolledStatus, useServerConfirmText, type OtherTask, type TaskInfo } from "./guardedShared";

// 1.4.15 (lot 4): card "Đọc lại giờ mở bán" of the page "SQL nguồn & đồng bộ": reads again, from the configured BigQuery source
// (read-only), only the days of a range that have NO stored open hours. Never fills anything in: a day the source does not return
// stays MISSING. Plan (writes nothing) -> typed text + reason -> 202 background task with its status.

const MAX_DAYS = 60;
interface Desc { code?: string; vi?: string; en?: string }
interface Plan {
  start: string; end: string; days: number; days_stored: number; days_missing: number; stored_rows: number; missing_days: string[];
  reads: { start: string; end: string; estimated_bytes?: number | null }[]; signature: string | null; estimated_bytes: number | null;
  estimate_error: { code?: string; detail?: string | null } | null; max_days: number; confirm_text: string; reason_min_length: number;
  source_table?: string; seller_code?: string; ops_lock_checked: boolean; ops_lock_source?: string | null; ops_locks?: { env: string; path: string }[]; busy_other_task?: OtherTask | null; description: Desc[];
}
interface Status { task?: TaskInfo | null; running?: boolean; description?: Desc[] }

const daysBetween = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000) + 1;

export default function OpenHoursReread() {
  const { t } = useI18n();
  const status = usePolledStatus<Status>("/api/open-hours-reread/status");
  const act = useAction();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const serverText = useServerConfirmText(act.error, "OPEN_HOURS_REREAD_CONFIRM_REQUIRED", () => setTyped(""));
  const range = start && end ? daysBetween(start, end) : 0;
  const rangeBad = !!start && !!end && (range < 1 || range > MAX_DAYS);
  const task = status.data?.task ?? null;
  const desc = plan?.description ?? status.data?.description ?? [];
  const confirmText = serverText ?? plan?.confirm_text ?? "";
  const minReason = plan?.reason_min_length ?? 10;
  const lockedOut = !!plan?.busy_other_task || (plan?.ops_locks ?? []).length > 0;
  const canRun = !!plan && !lockedOut && !!plan.signature && plan.days_missing > 0 && !act.busy && typed.trim() === confirmText && reasonLen(reason) >= minReason;

  // a task that was RUNNING and is not any more: the plan is outdated (days were stored), so it is dropped
  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    const now = status.data?.task?.status;
    if (prev.current === "RUNNING" && now && now !== "RUNNING") setPlan(null);
    prev.current = now;
  }, [status.data?.task?.status]);

  const doPlan = async () => {
    setTyped(""); setReason("");
    const r = await act.run(() => get<Plan>(`/api/open-hours-reread/plan${qs({ start, end, estimate: true })}`));
    setPlan(r ?? null);
  };
  const doRun = async () => {
    if (!plan?.signature) return;
    const r = await act.run(() => post("/api/open-hours-reread", { start: plan.start, end: plan.end, signature: plan.signature, confirm_text: typed.trim(), reason: normReason(reason) }), t("oh.accepted"));
    if (r) { setPlan(null); setTyped(""); setReason(""); void status.reload(); }
  };
  const result = (task?.result ?? null) as Record<string, any> | null;
  const progress = (task?.progress ?? []) as Record<string, any>[];

  return (
    <Card icon="bigquery" title={t("oh.title")} actions={<button onClick={() => void status.reload()} disabled={status.loading}><Icon name="refresh" />{t("bg.refresh")}</button>}>
      <div className="stack">
        <p className="small muted">{t("oh.intro")}</p>
        <div className="alert info small" data-testid="oh-description-box"><b>{t("oh.what")}</b><DescriptionList items={desc} testid="oh-description" /></div>
        <div className="form-grid">
          <Field label={t("oh.start")}><DateInput value={start} onChange={(v) => { setStart(v); setPlan(null); }} ariaLabel={t("oh.start")} /></Field>
          <Field label={t("oh.end")}><DateInput value={end} onChange={(v) => { setEnd(v); setPlan(null); }} ariaLabel={t("oh.end")} /></Field>
        </div>
        {rangeBad && <div className="alert bad small" data-testid="oh-range-bad">{range < 1 ? t("oh.range_order") : t("oh.too_many").replace("{m}", String(MAX_DAYS)).replace("{n}", String(range))}</div>}
        <div className="row wrap">
          <button className="primary" data-testid="oh-plan" onClick={doPlan} disabled={!start || !end || rangeBad || act.busy}><Icon name="search" />{t("oh.plan")}</button>
        </div>
        <ErrorDetails error={act.error} />
        <OkBox text={act.ok} />

        {plan && (
          <div className="stack tight" data-testid="oh-plan-box">
            <b>{t("oh.plan_title")}</b>
            <div className="small" data-testid="oh-plan-counts">{t("oh.plan_counts").replace("{d}", fmtNum(plan.days)).replace("{s}", fmtNum(plan.days_stored)).replace("{m}", fmtNum(plan.days_missing)).replace("{r}", fmtNum(plan.stored_rows))}</div>
            {plan.days_missing === 0 ? <div className="alert info small" data-testid="oh-nothing">{t("oh.nothing")}</div> : (
              <>
                <div className="small muted">{t("oh.missing_days")}: <span className="mono" data-testid="oh-missing">{plan.missing_days.map((d) => fmtDate(d)).join(", ")}</span></div>
                <table className="tbl small" data-testid="oh-reads">
                  <thead><tr><th>{t("oh.read")}</th><th className="num">{t("oh.bytes")}</th></tr></thead>
                  <tbody>{plan.reads.map((r, i) => <tr key={i}><td>{fmtDate(r.start)} → {fmtDate(r.end)}</td><td className="num">{r.estimated_bytes != null ? fmtBytes(r.estimated_bytes) : "—"}</td></tr>)}</tbody>
                </table>
                <div className="small" data-testid="oh-estimate">{plan.estimate_error ? t("oh.estimate_error").replace("{c}", String(plan.estimate_error.code ?? "")) : t("oh.estimate_total").replace("{b}", fmtBytes(plan.estimated_bytes))}</div>
                <div className="alert info small">{t("oh.no_fill")}</div>
                <OpsLockLine checked={plan.ops_lock_checked} source={plan.ops_lock_source} locks={plan.ops_locks} prefix="oh" />
                <OtherTaskNotice other={plan.busy_other_task} testid="oh-other-task" />
                <TypedConfirm id="oh" text={confirmText} minReason={minReason} typed={typed} setTyped={setTyped} reason={reason} setReason={setReason} />
                <div className="row">
                  <button className="primary" data-testid="oh-run" onClick={doRun} disabled={!canRun}><Icon name="bigquery" />{t("oh.run")}</button>
                  <button data-testid="oh-cancel" onClick={() => { setPlan(null); act.setError(null); }}>{t("common.cancel")}</button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="stack tight">
          <b>{t("oh.task_title")}</b>
          <TaskBox task={task} onRefresh={() => void status.reload()} busy={status.loading} testid="oh-task">
            {task?.error?.code === "OPEN_HOURS_REREAD_CONFIG_CHANGED" && <div className="alert warn small" data-testid="oh-config-changed">{t("oh.config_changed")}</div>}
            {progress.length > 0 && (
              <ul className="small" data-testid="oh-progress">{progress.map((p, i) => (
                <li key={i}>{fmtDate(p.start)} → {fmtDate(p.end)}{p.rows_read != null ? `: ${t("oh.p_rows").replace("{r}", fmtNum(p.rows_read)).replace("{i}", fmtNum(p.inserted)).replace("{s}", fmtNum(p.skipped_existing))}` : ""}
                  {Array.isArray(p.skipped_days_stored_meanwhile) && p.skipped_days_stored_meanwhile.length > 0 && (
                    <div className="muted" data-testid="oh-skipped-meanwhile">{t("oh.skipped_meanwhile").replace("{d}", p.skipped_days_stored_meanwhile.map((x: string) => fmtDate(x)).join(", "))}</div>
                  )}</li>
              ))}</ul>
            )}
            {result && (
              <div className="small" data-testid="oh-task-result">
                {t("oh.p_total").replace("{r}", fmtNum(result.rows_read)).replace("{i}", fmtNum(result.inserted)).replace("{s}", fmtNum(result.skipped_existing))}
                {result.undo?.loaded_at && <div className="muted">{t("oh.undo_info").replace("{l}", String(result.undo.loaded_at))}</div>}
              </div>
            )}
          </TaskBox>
        </div>
      </div>
    </Card>
  );
}
