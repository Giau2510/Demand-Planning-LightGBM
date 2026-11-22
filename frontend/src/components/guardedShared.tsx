import { useEffect, useState, type ReactNode } from "react";
import { ApiError, get } from "../api";
import { DICT, numberLocale, useI18n } from "../i18n";
import { Code, ErrorBox, Field, fmtTime, useAsync } from "./ui";
import { Icon } from "./icons";

// 1.4.15 (lot 2): small helpers shared by the "Cài đặt nâng cao" page and the "Cài đặt: xuất / nhập" card
// (compare-and-set with a preview, typed confirmation and a busy check; see AdvancedSettings.tsx / SettingsPortable.tsx).

export type Risk = "LOW" | "HIGH" | "PURCHASE" | "READONLY" | "OWN_PATH";

/** The busy check of the server: busy = a write is refused now; jobs = running jobs; stale_ignored = overdue job rows that
 *  were left out of the check. Also the shape of the params of a 409 SETTINGS_ADVANCED_BUSY. */
export interface BusyInfo { busy?: boolean; detail?: string | null; window?: unknown; jobs?: unknown; stale_ignored?: unknown; stale_ignored_total?: number }

/** params of the error body (api.ts types the body without them): window / jobs / current / confirm_text ... */
export function errParams(e: unknown): Record<string, unknown> {
  if (!(e instanceof ApiError)) return {};
  const raw = (e.body as unknown as { params?: unknown }).params;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
}

/** names out of a list the server sends (strings, or objects with a job type / name / id): never raw JSON */
export function names(x: unknown): string[] {
  if (!Array.isArray(x)) return [];
  return x.map((i) => {
    if (typeof i === "string") return i;
    if (i && typeof i === "object") {
      const o = i as Record<string, unknown>;
      for (const k of ["job_type", "type", "name", "id", "job_id"]) if (typeof o[k] === "string" || typeof o[k] === "number") return String(o[k]);
    }
    return "?";
  });
}

/** translation of a server code: `${prefix}.${code}`; a code without a translation is shown as it is */
export function useTr() {
  const { t } = useI18n();
  return (prefix: string, code: string) => (`${prefix}.${code}` in DICT ? t(`${prefix}.${code}`) : code);
}

/** stable JSON (sorted keys): equal values compare equal whatever the key order; true is not 1 */
export function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${stable(o[k])}`).join(",")}}`;
  }
  return JSON.stringify(v) ?? "null";
}

/** a value for a table cell: no raw JSON for the simple ones */
export function useFmt() {
  const { t } = useI18n();
  return (v: unknown): string => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "boolean") return v ? t("gp.on") : t("gp.off");
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  };
}

const RISK_CLASS: Record<string, string> = { LOW: "ok", HIGH: "warn", PURCHASE: "bad", READONLY: "muted", OWN_PATH: "muted" };

/** the risk level: colour AND text (never colour alone) */
export function RiskBadge({ risk }: { risk: string | null | undefined }) {
  const { t } = useI18n();
  if (!risk) return null;
  return <span className={`pill ${RISK_CLASS[risk] ?? "muted"}`} data-testid={`risk-${risk}`} title={`adv.risk_help.${risk}` in DICT ? t(`adv.risk_help.${risk}`) : undefined}>{t(`adv.risk.${risk}`)}</span>;
}

/** why a write is locked now (night window, running jobs) and which overdue jobs were left out of the check */
export function BusyNotice({ busy }: { busy: BusyInfo | null | undefined }) {
  const { t } = useI18n();
  if (!busy) return null;
  const jobs = names(busy.jobs);
  const stale = names(busy.stale_ignored);
  return (
    <>
      {busy.busy && (
        <div className="alert warn small" data-testid="gp-busy">
          <b>{t("gp.busy_title")}</b>
          <ul>
            {!!busy.window && (
              <li data-testid="gp-busy-window">{typeof busy.window === "string" ? t("gp.busy_window").replace("{w}", busy.window) : t("gp.busy_window_generic")}</li>
            )}
            {jobs.length > 0 && <li data-testid="gp-busy-jobs">{t("gp.busy_jobs").replace("{j}", jobs.join(", "))}</li>}
          </ul>
        </div>
      )}
      {stale.length > 0 && <div className="alert info small" data-testid="gp-stale-ignored">{t("gp.stale_ignored").replace("{j}", stale.join(", "))}</div>}
    </>
  );
}

// ---------------------------------------------------------------- 1.4.15 lot 3: background tasks (held-lines release, open-hours re-read, sync rollback)
/** the reason as the server counts it: runs of white space collapsed to one space, trimmed (the minimum is checked on this) */
export const normReason = (s: string) => s.split(/\s+/).join(" ").trim();
export const reasonLen = (s: string) => normReason(s).length;
export const GB = 1024 ** 3;
/** bytes -> "1,50 GB" (the server gives needed / free / missing in bytes) */
export function fmtGB(b: unknown): string {
  return typeof b === "number" && Number.isFinite(b)
    ? `${(b / GB).toLocaleString(numberLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} GB` : "—";
}

export interface TaskInfo {
  task_id?: string; status?: string; started_at?: string | null; finished_at?: string | null; heartbeat_at?: string | null;
  error?: { code?: string; detail?: string | null } | null; result?: Record<string, any> | null; progress?: Record<string, any>[] | null;
  committed?: boolean; reason?: string | null;
}
const TASK_TONE: Record<string, string> = { RUNNING: "info", SUCCEEDED: "ok", FAILED: "bad", INTERRUPTED: "warn" };

/** GET `path` ({task, ...}); while the task is RUNNING and the page is open it asks again every 5 s - never otherwise */
export function usePolledStatus<T extends { task?: TaskInfo | null }>(path: string, everyMs = 5000) {
  const st = useAsync(() => get<T>(path), [path]);
  const running = st.data?.task?.status === "RUNNING";
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => { if (typeof document === "undefined" || document.visibilityState !== "hidden") void st.reload(); }, everyMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, everyMs]);
  return st;
}

/** status of a background task: running / done / failed / interrupted, its error (translated by code) and a refresh button */
export function TaskBox({ task, onRefresh, busy, testid, children }: { task: TaskInfo | null | undefined; onRefresh: () => void; busy?: boolean; testid: string; children?: ReactNode }) {
  const { t } = useI18n();
  if (!task || !task.status) {
    return <div className="small muted" data-testid={`${testid}-none`}>{t("bg.no_task")} <button className="small" onClick={onRefresh} disabled={busy}><Icon name="refresh" />{t("bg.refresh")}</button></div>;
  }
  return (
    <div className="stack tight" data-testid={testid}>
      <div className="row wrap">
        <span className={`pill ${TASK_TONE[task.status] ?? "muted"}`} data-testid={`${testid}-status`}>{`bg.status.${task.status}` in DICT ? t(`bg.status.${task.status}`) : task.status}</span>
        {task.started_at && <span className="small muted">{t("bg.started")}: {fmtTime(task.started_at)}</span>}
        {task.finished_at && <span className="small muted">{t("bg.finished")}: {fmtTime(task.finished_at)}</span>}
        <button className="small" data-testid={`${testid}-refresh`} onClick={onRefresh} disabled={busy}><Icon name="refresh" />{t("bg.refresh")}</button>
        {task.status === "RUNNING" && <span className="small muted">{t("bg.auto_refresh")}</span>}
      </div>
      {task.status === "INTERRUPTED" && (
        <div className="alert warn small" data-testid={`${testid}-interrupted`}>
          {task.committed === true ? t("bg.interrupted_committed") : task.committed === false ? t("bg.interrupted_not_committed") : t("bg.interrupted")}
        </div>
      )}
      {task.error && (
        <div className="alert bad small" role="alert" data-testid={`${testid}-error`}>
          <Code code={task.error.code} />{task.error.detail ? <div className="mono small">{task.error.detail}</div> : null}
        </div>
      )}
      {children}
    </div>
  );
}

/** description codes that are warnings (shown as a prominent box): SEL2 / KPI numbers change, final actuals touched, rollback only before the next write */
const WARN_CODES = ["OH_REREAD_CHANGES_SEL2_NUMBERS", "HELD_RELEASE_TOUCHES_FINAL_ACTUALS", "ROLLBACK_ONLY_BEFORE_NEXT_WRITE"];

/** a description list given by the server ([{code, vi, en}]) in the language of the page */
export function DescriptionList({ items, testid }: { items: { code?: string; vi?: string; en?: string }[] | null | undefined; testid: string }) {
  const { lang } = useI18n();
  if (!items?.length) return null;
  return (
    <ul className="small" data-testid={testid}>{items.map((d, i) => (
      <li key={d.code ?? i} data-testid={`${testid}-${d.code ?? i}`}>
        {d.code && WARN_CODES.includes(d.code) ? <div className="alert warn small" data-testid={`${testid}-${d.code}-warn`}><b>{lang === "vi" ? d.vi : d.en}</b></div> : (lang === "vi" ? d.vi : d.en)}
      </li>
    ))}</ul>
  );
}

/** the server's own bilingual message for the error + its figures made readable: bytes needed / free / missing as GB,
 *  the blocking window / saved schedule times / running jobs, the operations lock files, the groups of a too-large selection */
export function ErrorDetails({ error }: { error: unknown }) {
  const { t } = useI18n();
  const tr = useTr();
  if (!error) return null;
  const p = errParams(error);
  const code = error instanceof ApiError ? error.body.code : "";
  const num = (k: string) => (typeof p[k] === "number" ? (p[k] as number) : null);
  const list = (k: string) => (Array.isArray(p[k]) ? (p[k] as Record<string, unknown>[]) : []);
  const sched = list("schedule_times");
  const locks = list("locks");
  const bySku = list("by_sku_fc");
  const byDay = list("by_day");
  const keys = list("keys");
  const limits = (p.limits && typeof p.limits === "object" ? p.limits : null) as Record<string, number> | null;
  return (
    <>
      <ErrorBox error={error} />
      {num("need_bytes") !== null && (
        <div className="alert bad small" data-testid="bg-disk">
          {t("bg.disk").replace("{need}", fmtGB(p.need_bytes)).replace("{free}", fmtGB(p.free_bytes)).replace("{missing}", fmtGB(p.missing_bytes))}
          {typeof p.backup_dir === "string" && <> <span className="mono">{p.backup_dir}</span></>}
        </div>
      )}
      {code === "HEAVY_WRITE_ANOTHER_RUNNING" && (
        <div className="alert warn small" data-testid="bg-other-running">{t("bg.other_running").replace("{b}", tr("bg.button", String(p.button ?? "?")))}{typeof p.task_id === "string" ? ` (${p.task_id})` : ""}</div>
      )}
      {code === "HELD_RELEASE_DAILY_LIMIT" && num("max_releases") !== null && (
        <div className="alert warn small" data-testid="bg-daily-limit">
          {t("bg.daily_limit").replace("{ru}", String(num("releases_used"))).replace("{mr}", String(num("max_releases"))).replace("{lu}", String(num("lines_used")))
            .replace("{ml}", String(num("max_lines"))).replace("{rl}", String(num("releases_left"))).replace("{ll}", String(num("lines_left")))}
        </div>
      )}
      {code === "SYNC_ROLLBACK_TOO_LARGE" && num("max_entries") !== null && (
        <div className="alert warn small" data-testid="bg-entries-too-large">{t("bg.entries_too_large").replace("{n}", String(num("entries") ?? "?")).replace("{m}", String(num("max_entries")))}</div>
      )}
      {code.endsWith("_BUSY") && <BusyNotice busy={{ busy: true, window: p.window, jobs: p.jobs, stale_ignored: p.stale_ignored }} />}
      {typeof p.window_soon === "string" && <div className="alert warn small" data-testid="bg-soon">{t("bg.window_soon").replace("{w}", p.window_soon).replace("{m}", String(num("start_margin_minutes") ?? 60))}</div>}
      {sched.length > 0 && (
        <div className="alert warn small" data-testid="bg-sched">{t("bg.sched_near")}
          <ul>{sched.map((x, i) => <li key={i}><span className="mono">{String(x.setting)}</span> {String(x.time)}</li>)}</ul></div>
      )}
      {locks.length > 0 && (
        <div className="alert warn small" data-testid="bg-locks">{t("bg.locks")}
          <ul>{locks.map((x, i) => <li key={i} className="mono">{String(x.env)} = {String(x.path)}</li>)}</ul></div>
      )}
      {code === "HELD_RELEASE_TOO_LARGE" && (
        <div className="alert warn small" data-testid="bg-toolarge">
          {t("bg.too_large").replace("{n}", String(num("holds") ?? "?")).replace("{u}", String(num("units") ?? "?"))
            .replace("{ml}", String(limits?.max_lines ?? 450)).replace("{mu}", String(limits?.max_units ?? 6000))}
          {bySku.length > 0 && <><b className="small"> {t("bg.largest_sku")}</b>
            <ul data-testid="bg-groups-sku">{bySku.slice(0, 10).map((g, i) => <li key={i} className="mono">{String(g.sku_id)} / {String(g.fc_id)}: {String(g.lines)} · {String(g.units)}</li>)}</ul></>}
          {byDay.length > 0 && <><b className="small"> {t("bg.largest_day")}</b>
            <ul data-testid="bg-groups-day">{byDay.slice(0, 10).map((g, i) => <li key={i} className="mono">{String(g.order_date)}: {String(g.lines)} · {String(g.units)}</li>)}</ul></>}
        </div>
      )}
      {keys.length > 0 && keys[0] && typeof keys[0] === "object" && "order_date" in keys[0] && (
        <div className="alert bad small" data-testid="bg-keys">{t("bg.keys")}
          <ul>{keys.slice(0, 20).map((x, i) => <li key={i} className="mono">{String(x.order_date)} {String(x.sku_id)} / {String(x.fc_id)}</li>)}</ul></div>
      )}
    </>
  );
}

const MAX_REASON_SHARED = 500;
/** the typed text + reason fields of a write that needs them (ids: `${id}-text`, `${id}-input`, `${id}-reason`) */
export function TypedConfirm({ id, text, minReason, typed, setTyped, reason, setReason }: {
  id: string; text: string; minReason: number; typed: string; setTyped: (v: string) => void; reason: string; setReason: (v: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="form-grid">
      <Field label={t("gp.type_confirm")} help={<code className="code" data-testid={`${id}-text`}>{text}</code>}>
        <input type="text" data-testid={`${id}-input`} autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
      </Field>
      <Field label={t("gp.reason_required")} help={t("gp.reason_help").replace("{n}", String(reasonLen(reason))).replace("{m}", String(minReason)).replace("{x}", String(MAX_REASON_SHARED))}>
        <textarea rows={2} maxLength={MAX_REASON_SHARED} data-testid={`${id}-reason`} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </div>
  );
}

/** a 409 CONFIRM_REQUIRED carries the text of today (the day changed since the preview): the text to show, null when none came */
export function useServerConfirmText(error: unknown, code: string, onNew: () => void, param = "confirm_text"): string | null {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    if (error instanceof ApiError && error.body.code === code) {
      const c = errParams(error)[param];
      if (typeof c === "string" && c) { setText(c); onNew(); }
    } else if (!error) setText(null);     // a new preview / action clears the error: the text of the old answer goes with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);
  return text;
}

/** the operations-lock line of a preview: where the lock files were looked for (or "not checked on this machine") and, when a lock file
 *  exists, which one (the button is then refused). ids: `${prefix}-lock-checked`, `${prefix}-lock-unchecked`, `${prefix}-locks` */
export function OpsLockLine({ checked, source, locks, prefix }: { checked: boolean | undefined; source?: string | null; locks?: { env: string; path: string }[] | null; prefix: string }) {
  const { t } = useI18n();
  const held = (locks ?? []).map((x) => `${x.env}=${x.path}`);
  return (
    <>
      {checked === false && <div className="alert info small" data-testid={`${prefix}-lock-unchecked`}>{t("hl.lock_unchecked")}</div>}
      {checked === true && <div className="small muted" data-testid={`${prefix}-lock-checked`}>{t("bg.lock_checked").replace("{s}", source && `bg.lock_src.${source}` in DICT ? t(`bg.lock_src.${source}`) : "—")}</div>}
      {held.length > 0 && <div className="alert warn small" data-testid={`${prefix}-locks`}>{t("bg.locks_denied").replace("{names}", held.join(", "))}</div>}
    </>
  );
}

/** another background write button is running: this one is locked until it ends */
export interface OtherTask { button?: string; state?: string; task_id?: string; started_at?: string | null }
export function OtherTaskNotice({ other, testid }: { other: OtherTask | null | undefined; testid: string }) {
  const { t } = useI18n();
  const tr = useTr();
  if (!other) return null;
  return <div className="alert warn small" data-testid={testid}>{t("bg.other_running").replace("{b}", tr("bg.button", other.button ?? "?"))}{other.started_at ? ` (${fmtTime(other.started_at)})` : ""}</div>;
}
