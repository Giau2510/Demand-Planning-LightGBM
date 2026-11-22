import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { get, post, qs } from "../api";
import { useI18n } from "../i18n";
import { Card, DateInput, Field, Loading, OkBox, Pager, Stat, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "./ui";
import { Icon } from "./icons";
import { normReason, reasonLen, DescriptionList, ErrorDetails, OpsLockLine, OtherTaskNotice, TaskBox, TypedConfirm, fmtGB, usePolledStatus, useServerConfirmText, useTr, type OtherTask, type TaskInfo } from "./guardedShared";

// 1.4.15 (lot 3): card "Dòng bị giữ" of the page "Chất lượng dữ liệu": the ACTIVE held lines (GET /api/held-lines), the choice of
// the set to release (the filters of release_holds: SKU, day range, cause), a preview that writes nothing, then the typed text +
// reason and the release (202: it runs in the background: a backup of the database first), with the status of that task.

const PAGE = 20;
const CAUSES = ["ORDER_GONE", "LINE_GONE", "PENDING_GONE", "QTY_REDUCED", "NO_EVIDENCE"];
type View = "sku_fc" | "day" | "cause" | "lines";
interface Filter { sku_id: string; cause: string; start: string; end: string }
const EMPTY: Filter = { sku_id: "", cause: "", start: "", end: "" };
const body = (f: Filter) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));   // empty = no filter (the API forbids other keys)

interface Summary {
  status: string; active_lines?: number; units?: number; keys?: number; days?: number; first_day?: string | null; last_day?: string | null;
  by_cause?: Record<string, { lines: number; units: number }>;
}
interface HeldResponse {
  configured: boolean; ops_lock_checked: boolean; ops_lock_source?: string | null; policy?: string; limits?: { max_lines: number; max_units: number }; summary: Summary | null;
  rows: Record<string, any>[]; total_groups?: number | null; task?: TaskInfo | null; recent_releases?: Release[];
}
interface Release {
  sync_run_id: string; status: string; started_at: string; holds?: number; units?: number; keys?: number; backup_file?: string | null;
  rolled_back_by?: string | null; rolled_back_at?: string | null; rollback?: { cli?: string } | null;
}
interface Daily { releases_used: number; releases_left: number; lines_used: number; lines_left: number; max_releases: number; max_lines: number }
interface Preview {
  holds: number; units: number; keys: number; by_cause?: Record<string, number>; keys_detail: Record<string, any>[]; signature: string | null;
  releasable: boolean; warnings: string[]; confirm_text: string; reason_min_length: number; ops_lock_checked: boolean; ops_lock_source?: string | null; ops_locks?: { env: string; path: string }[];
  busy_other_task?: OtherTask | null; daily?: Daily; description?: { code?: string; vi?: string; en?: string }[];
  disk?: { ok: boolean; need_bytes: number; free_bytes: number; missing_bytes: number; backup_dir: string }; limits?: { max_lines: number; max_units: number };
}
interface Status { task?: TaskInfo | null; running?: boolean; recent_releases?: Release[]; backups?: { release_backups?: number }; scope_key?: string | null }

export default function HeldLinesCard() {
  const { t } = useI18n();
  const tr = useTr();
  const [draft, setDraft] = useState<Filter>(EMPTY);
  const [applied, setApplied] = useState<Filter>(EMPTY);
  const [view, setView] = useState<View>("sku_fc");
  const [page, setPage] = useState(0);
  const data = useAsync(() => get<HeldResponse>(`/api/held-lines${qs({ view, ...applied, limit: PAGE, offset: page * PAGE })}`), [view, applied, page]);
  const status = usePolledStatus<Status>("/api/held-lines/release-status");
  const act = useAction();
  const [pv, setPv] = useState<Preview | null>(null);
  const [pvFilter, setPvFilter] = useState<Filter>(EMPTY);   // the filter the preview was made with (printed in the preview)
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const serverText = useServerConfirmText(act.error, "HELD_RELEASE_CONFIRM_REQUIRED", () => setTyped(""));

  // a task that was RUNNING and is not any more: the summary is read again (the lines changed)
  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    const now = status.data?.task?.status;
    if (prev.current === "RUNNING" && now && now !== "RUNNING") void data.reload();
    prev.current = now;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.data?.task?.status]);

  const d = data.data;
  const sum = d?.summary ?? null;
  const total = view === "lines" ? sum?.active_lines ?? 0 : d?.total_groups ?? 0;
  const task = status.data?.task ?? d?.task ?? null;
  const releases = status.data?.recent_releases ?? d?.recent_releases ?? [];
  const confirmText = serverText ?? pv?.confirm_text ?? "";
  const minReason = pv?.reason_min_length ?? 10;
  // the preview locks the button: another write button is running, a lock file exists, or today's allowance (releases / lines) is used
  const dailyBlocked = !!pv?.daily && (pv.daily.releases_left < 1 || pv.holds > pv.daily.lines_left);
  const lockedOut = !!pv?.busy_other_task || (pv?.ops_locks ?? []).length > 0 || dailyBlocked;
  const canRelease = !!pv && !lockedOut && pv.releasable && !!pv.signature && !act.busy && typed.trim() === confirmText && reasonLen(reason) >= minReason && pv.disk?.ok !== false;

  const applyFilter = () => { setApplied({ ...draft }); setPage(0); setPv(null); act.setError(null); act.setOk(null); };
  const doPreview = async () => {
    setTyped(""); setReason("");
    const r = await act.run(() => post<Preview>("/api/held-lines/release-preview", body(applied)));
    setPv(r ?? null);
    setPvFilter({ ...applied });
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(applied);     // edited but "Lọc" not pressed: the table and the preview would not match the boxes
  const doRelease = async () => {
    if (!pv?.signature) return;
    const r = await act.run(() => post("/api/held-lines/release", { ...body(applied), signature: pv.signature, confirm_text: typed.trim(), reason: normReason(reason) }), t("hl.accepted"));
    if (r) { setPv(null); setTyped(""); setReason(""); void status.reload(); }
  };
  const refresh = () => { void status.reload(); void data.reload(); };
  const result = (task?.result ?? null) as Record<string, any> | null;

  return (
    <Card icon="quality" title={t("hl.title")} actions={<button onClick={refresh} disabled={data.loading || status.loading}><Icon name="refresh" />{t("bg.refresh")}</button>}>
      <div className="stack">
        <p className="small muted">{t("hl.intro")}</p>
        <div className="alert warn" data-testid="hl-warning"><b>{t("hl.warning")}</b></div>
        {d && <OpsLockLine checked={d.ops_lock_checked} source={d.ops_lock_source} prefix="hl" />}
        {data.error ? <ErrorDetails error={data.error} /> : !d ? <Loading /> : !d.configured ? <p className="small muted" data-testid="hl-not-configured">{t("hl.not_configured")}</p> : (
          <>
            {sum?.status === "NO_INDEX" && <div className="alert warn small">{t("hl.no_index")}</div>}
            {sum && sum.status !== "NO_INDEX" && (
              <>
                <div className="grid4" data-testid="hl-summary">
                  <Stat label={t("hl.active_lines")} value={<span data-testid="hl-active">{fmtNum(sum.active_lines)}</span>} sub={sum.status !== "COMPLETE" ? <span data-testid="hl-partial">{t(`hl.status.${sum.status}`)}</span> : undefined} tone={sum.status !== "COMPLETE" ? "warn" : ""} />
                  <Stat label={t("hl.units")} value={<span data-testid="hl-units">{fmtNum(sum.units, 2)}</span>} />
                  <Stat label={t("hl.keys")} value={fmtNum(sum.keys)} sub={`${t("hl.days")}: ${fmtNum(sum.days)}`} />
                  <Stat label={t("hl.range")} value={<span className="small">{fmtDate(sum.first_day)} → {fmtDate(sum.last_day)}</span>} />
                </div>
                {sum.by_cause && Object.keys(sum.by_cause).length > 0 && (
                  <div className="small" data-testid="hl-by-cause">{t("hl.by_cause")}: {Object.entries(sum.by_cause).map(([c, v]) => `${tr("hl.cause", c)} ${fmtNum(v.lines)} / ${fmtNum(v.units, 2)}`).join(" · ")}</div>
                )}
              </>
            )}

            <div className="form-grid" data-testid="hl-filter">
              <Field label={t("hl.f_sku")}><input type="text" data-testid="hl-f-sku" value={draft.sku_id} onChange={(e) => setDraft({ ...draft, sku_id: e.target.value })} /></Field>
              <Field label={t("hl.f_cause")}>
                <select data-testid="hl-f-cause" value={draft.cause} onChange={(e) => setDraft({ ...draft, cause: e.target.value })}>
                  <option value="">{t("hl.all")}</option>
                  {CAUSES.map((c) => <option key={c} value={c}>{tr("hl.cause", c)}</option>)}
                </select>
              </Field>
              <Field label={t("hl.f_start")}><DateInput value={draft.start} onChange={(v) => setDraft({ ...draft, start: v })} ariaLabel={t("hl.f_start")} /></Field>
              <Field label={t("hl.f_end")}><DateInput value={draft.end} onChange={(v) => setDraft({ ...draft, end: v })} ariaLabel={t("hl.f_end")} /></Field>
              <Field label={t("hl.view")}>
                <select data-testid="hl-view" value={view} onChange={(e) => { setView(e.target.value as View); setPage(0); }}>
                  {(["sku_fc", "day", "cause", "lines"] as View[]).map((v) => <option key={v} value={v}>{t(`hl.view.${v}`)}</option>)}
                </select>
              </Field>
            </div>
            <div className="row wrap">
              <button data-testid="hl-filter-apply" onClick={applyFilter}><Icon name="filter" />{t("hl.filter")}</button>
              <button className="primary" data-testid="hl-preview" onClick={doPreview} disabled={act.busy || dirty || !sum || (sum.active_lines ?? 0) === 0}><Icon name="search" />{t("hl.preview")}</button>
              {dirty && <span className="small bad-t" data-testid="hl-filter-dirty">{t("hl.filter_dirty")}</span>}
            </div>

            <div className="scroll" data-testid="hl-rows">
              <table className="tbl small">
                <thead>
                  {view === "lines"
                    ? <tr><th>ID</th><th>{t("hl.col_day")}</th><th>SKU</th><th>FC</th><th>{t("hl.col_order")}</th><th>{t("hl.col_cause")}</th><th className="num">{t("hl.col_qty")}</th><th>{t("hl.col_detected")}</th></tr>
                    : <tr>{view === "sku_fc" && <><th>SKU</th><th>FC</th></>}{view === "day" && <th>{t("hl.col_day")}</th>}{view === "cause" && <th>{t("hl.col_cause")}</th>}
                      <th className="num">{t("hl.col_lines")}</th><th className="num">{t("hl.col_qty")}</th><th>{t("hl.col_first")}</th><th>{t("hl.col_last")}</th></tr>}
                </thead>
                <tbody>
                  {(d.rows ?? []).map((r, i) => view === "lines" ? (
                    <tr key={r.id ?? i}><td>{r.id}</td><td className="nowrap">{fmtDate(r.order_date)}</td><td className="mono">{r.sku_id}</td><td className="mono">{r.fc_id}</td><td className="mono">{r.order_id}</td>
                      <td>{tr("hl.cause", r.cause)}</td><td className="num">{fmtNum(r.qty, 2)}</td><td className="nowrap">{fmtTime(r.detected_at)}</td></tr>
                  ) : (
                    <tr key={i} data-testid="hl-row">{view === "sku_fc" && <><td className="mono">{r.sku_id}</td><td className="mono">{r.fc_id}</td></>}
                      {view === "day" && <td className="nowrap">{fmtDate(r.order_date)}</td>}{view === "cause" && <td>{tr("hl.cause", r.cause)}</td>}
                      <td className="num">{fmtNum(r.lines)}</td><td className="num">{fmtNum(r.units, 2)}</td><td className="nowrap">{fmtDate(r.first_day)}</td><td className="nowrap">{fmtDate(r.last_day)}</td></tr>
                  ))}
                  {(d.rows ?? []).length === 0 && <tr><td colSpan={8} className="muted">{t("hl.none")}</td></tr>}
                </tbody>
              </table>
            </div>
            <Pager page={page} total={total} size={PAGE} unit={view === "lines" ? t("hl.unit_lines") : t("hl.unit_groups")} onPage={setPage} />
          </>
        )}

        <ErrorDetails error={act.error} />
        <OkBox text={act.ok} />

        {pv && (
          <div className="stack tight" data-testid="hl-confirm-area">
            <b>{t("hl.preview_title")}</b>
            <div className="small" data-testid="hl-preview-filter">{t("hl.preview_filter")}: {Object.entries(body(pvFilter)).map(([k, v]) => `${k}=${v}`).join(", ") || t("hl.all")}</div>
            {!pv.releasable ? <div className="alert info small" data-testid="hl-nothing">{t("hl.nothing")}</div> : (
              <>
                <div className="small" data-testid="hl-preview-counts">{t("hl.preview_counts").replace("{h}", fmtNum(pv.holds)).replace("{u}", fmtNum(pv.units, 2)).replace("{k}", fmtNum(pv.keys))
                  .replace("{ml}", String(pv.limits?.max_lines ?? 450)).replace("{mu}", fmtNum(pv.limits?.max_units ?? 6000))}</div>
                {pv.by_cause && <div className="small muted">{t("hl.by_cause")}: {Object.entries(pv.by_cause).map(([c, n]) => `${tr("hl.cause", c)} ${n}`).join(" · ")}</div>}
                <div className="scroll">
                  <table className="tbl small" data-testid="hl-preview-keys">
                    <thead><tr><th>{t("hl.col_day")}</th><th>SKU</th><th>FC</th><th className="num">{t("hl.col_lines")}</th><th className="num">{t("hl.release_units")}</th><th className="num">{t("hl.stored_now")}</th><th className="num">{t("hl.after")}</th></tr></thead>
                    <tbody>{pv.keys_detail.map((k, i) => (
                      <tr key={i}><td className="nowrap">{fmtDate(k.order_date)}</td><td className="mono">{k.sku_id}</td><td className="mono">{k.fc_id}</td><td className="num">{k.lines}</td>
                        <td className="num">{fmtNum(k.release_units, 2)}</td><td className="num">{fmtNum(k.stored_qty, 2)}</td><td className="num">{k.row_removed ? t("hl.row_removed") : fmtNum(k.qty_after, 2)}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
                {pv.keys > pv.keys_detail.length && <div className="small muted">{t("hl.listed_limit").replace("{n}", String(pv.keys_detail.length))}</div>}
                {pv.disk && (
                  <div className={`alert ${pv.disk.ok ? "info" : "bad"} small`} data-testid="hl-disk">
                    {t("bg.disk_info").replace("{need}", fmtGB(pv.disk.need_bytes)).replace("{free}", fmtGB(pv.disk.free_bytes))}{!pv.disk.ok && <> {t("bg.disk_missing").replace("{missing}", fmtGB(pv.disk.missing_bytes))}</>}
                  </div>
                )}
                <OpsLockLine checked={pv.ops_lock_checked} source={pv.ops_lock_source} locks={pv.ops_locks} prefix="hl-pv" />
                <OtherTaskNotice other={pv.busy_other_task} testid="hl-other-task" />
                {pv.daily && (
                  <div className={`alert ${dailyBlocked ? "bad" : "info"} small`} data-testid="hl-daily">
                    {t("hl.daily").replace("{rl}", fmtNum(pv.daily.releases_left)).replace("{ll}", fmtNum(pv.daily.lines_left)).replace("{ru}", fmtNum(pv.daily.releases_used))
                      .replace("{lu}", fmtNum(pv.daily.lines_used)).replace("{mr}", fmtNum(pv.daily.max_releases)).replace("{ml}", fmtNum(pv.daily.max_lines))}
                    {dailyBlocked && <b data-testid="hl-daily-blocked"> {t("hl.daily_blocked")}</b>}
                  </div>
                )}
                <DescriptionList items={pv.description} testid="hl-preview-description" />
                <div className="alert warn" data-testid="hl-warning-confirm"><b>{t("hl.warning")}</b></div>
                <TypedConfirm id="hl" text={confirmText} minReason={minReason} typed={typed} setTyped={setTyped} reason={reason} setReason={setReason} />
                <div className="row">
                  <button className="primary" data-testid="hl-release" onClick={doRelease} disabled={!canRelease}><Icon name="prod" />{t("hl.release")}</button>
                  <button data-testid="hl-cancel" onClick={() => { setPv(null); act.setError(null); }}>{t("common.cancel")}</button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="stack tight">
          <b>{t("hl.task_title")}</b>
          <TaskBox task={task} onRefresh={refresh} busy={status.loading} testid="hl-task">
            {result && (
              <ul className="small" data-testid="hl-task-result">
                <li>{t("hl.res_counts").replace("{h}", fmtNum(result.holds)).replace("{u}", fmtNum(result.units, 2)).replace("{k}", fmtNum(result.keys))}</li>
                {result.sync_run_id && <li>{t("hl.res_run")}: <span className="mono">{result.sync_run_id}</span></li>}
                {result.backup_file && <li data-testid="hl-task-backup">{t("hl.res_backup")}: <span className="mono">{result.backup_path ?? result.backup_file}</span> ({fmtGB(result.backup_bytes)})</li>}
                {result.rollback?.cli && <li className="mono">{result.rollback.cli}</li>}
              </ul>
            )}
          </TaskBox>
          <div className="small muted" data-testid="hl-undo-hint">{t("hl.undo_hint")} <Link to="/sql">{t("nav.sql")} →</Link></div>
          {releases.length > 0 && (
            <div className="scroll"><table className="tbl small" data-testid="hl-releases">
              <thead><tr><th>{t("gp.col_time")}</th><th>{t("hl.res_run")}</th><th>{t("adv.col_action")}</th><th className="num">{t("hl.col_lines")}</th><th className="num">{t("hl.col_qty")}</th></tr></thead>
              <tbody>{releases.map((r) => (
                <tr key={r.sync_run_id}><td className="nowrap">{fmtTime(r.started_at)}</td><td className="mono">{r.sync_run_id}</td>
                  <td>{r.rolled_back_at ? t("hl.rolled_back") : r.status}</td><td className="num">{fmtNum(r.holds)}</td><td className="num">{fmtNum(r.units, 2)}</td></tr>
              ))}</tbody></table></div>
          )}
        </div>
      </div>
    </Card>
  );
}
