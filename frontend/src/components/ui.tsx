import type React from "react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api";
import { numberLocale, useI18n } from "../i18n";
import { TERM_BY_ID } from "../glossary";
import { Icon, type IconName } from "./icons";

// ---------------------------------------------------------------- formatting
// Display only: values used for calculations are never rounded here. Numbers follow the UI language (vi: 7,2 /
// 1.204 · en: 7.2 / 1,204) and never show trailing zeros (7,2000 -> 7,2; 10,0000 -> 10). Calendar dates are always
// DD/MM/YYYY; timestamps are converted to Vietnam time (Asia/Ho_Chi_Minh) and shown as DD/MM/YYYY HH:mm.

/** Up to `d` decimals, trailing zeros removed. */
export const fmtNum = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString(numberLocale(), { maximumFractionDigits: d, minimumFractionDigits: 0 });
export const fmtPct = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toLocaleString(numberLocale(), { maximumFractionDigits: d, minimumFractionDigits: 0 })}%`;
/** Explanation numbers: at most 2 decimals, no trailing zeros. A non-zero value that would round to 0 is shown as
 *  "<0,01" (with its sign) so sign and order of magnitude are never lost. `signed` adds "+" to positive values. */
export function fmtX(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (v === 0) return "0";
  const sign = v < 0 ? "-" : signed ? "+" : "";
  if (Math.abs(v) < 0.005) return `${sign}<${fmtNum(0.01, 2)}`;
  return `${sign}${fmtNum(Math.abs(v), 2)}`;
}
/** Percentages in explanations: at most 2 decimals, no trailing zeros. */
export const fmtPctX = (v: number | null | undefined, signed = false) =>
  v === null || v === undefined ? "—" : `${v > 0 && signed ? "+" : v < 0 ? "-" : ""}${fmtNum(Math.abs(v) * 100, 2)}%`;

/** Weekday of a calendar date (YYYY-MM-DD) computed from the date itself, never from a row position. 1.2.12: the one
 * Vietnamese form of the application, "Thứ 2" ... "Chủ nhật" (weekdayLabel), also where the explanation panel used
 * "Thứ Hai" ... "Chủ Nhật"; "—" for a missing or impossible date. */
export function weekdayName(iso: string, lang: "vi" | "en"): string {
  return weekdayLabel(isoWeekday(iso), lang);
}

/** 1.2.12: a forecast (target) date with its weekday: "20/10/2026 (Thứ 3)". */
export function fmtDateWd(iso: string | null | undefined, lang: "vi" | "en"): string {
  const n = isoWeekday(iso);
  return n === null ? fmtDate(iso) : `${fmtDate(iso)} (${weekdayLabel(n, lang)})`;
}

/** 1.2.9: the application's one weekday convention (backend app/weekday.py): 1 = Monday ... 7 = Sunday, from the
 * calendar date itself. YYYY-MM-DD is read as a UTC calendar day, so the browser's time zone can never move the day;
 * an impossible date (2026-02-30) gives null. */
export function isoWeekday(iso: string | null | undefined): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  if (d.getUTCFullYear() !== +m[1] || d.getUTCMonth() !== +m[2] - 1 || d.getUTCDate() !== +m[3]) return null;
  return ((d.getUTCDay() + 6) % 7) + 1;
}
const WEEKDAY_LABELS = { vi: ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"],
  en: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] };
/** "Thứ 2" ... "Chủ nhật" (en: Monday ... Sunday) for 1..7; "—" for a missing or invalid value (never guessed). */
export function weekdayLabel(n: number | null | undefined, lang: "vi" | "en"): string {
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || n > 7) return "—";
  return WEEKDAY_LABELS[lang][n - 1];
}

export const fmtSignedPct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${fmtPct(v)}`);

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DT = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;
const VN_PARTS = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function vnParts(d: Date) {
  const p: Record<string, string> = {};
  for (const x of VN_PARTS.formatToParts(d)) p[x.type] = x.value;
  return p;
}

/** Calendar date -> DD/MM/YYYY. A plain date is never shifted by time zones; a timestamp gives its Vietnam date. */
export function fmtDate(v: string | null | undefined): string {
  if (!v) return "—";
  const m = ISO_DATE.exec(v);
  if (m) return `${m[3]}/${m[2]}/${m[1]}`;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  const p = vnParts(d);
  return `${p.day}/${p.month}/${p.year}`;
}

/** Timestamp -> DD/MM/YYYY HH:mm in Vietnam time. A plain date -> DD/MM/YYYY. */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (ISO_DATE.test(iso)) return fmtDate(iso);
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = vnParts(d);
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`;
}

/** Any value that may be a date (e.g. raw import cells): ISO date -> DD/MM/YYYY; timestamp with a zone -> Vietnam
 *  time; timestamp without a zone -> same wall-clock time. Anything else (an unparseable raw input) is unchanged. */
export function fmtDateish(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v !== "string") return String(v);
  const t = v.trim();
  if (ISO_DATE.test(t)) return fmtDate(t);
  const m = ISO_DT.exec(t);
  if (!m) return v;
  if (m[7]) return fmtTime(t);
  return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}${m[6] && m[6] !== "00" ? `:${m[6]}` : ""}`;
}

/** Free text that may contain ISO dates/timestamps (error details, job messages, technical JSON): every date in it
 *  is shown as DD/MM/YYYY (timestamps with a zone in Vietnam time). Display only. */
export function fmtDatesInText(s: string | null | undefined): string {
  if (!s) return "";
  return String(s).replace(/(?<![\w-])\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?(?![\d-])/g, (m) => fmtDateish(m));
}

/** DD/MM/YYYY -> ISO YYYY-MM-DD (null if not a real calendar date). */
export function parseDmy(s: string): string | null {
  const m = /^\s*(\d{1,2})\/(\d{1,2})\/(\d{4})\s*$/.exec(s);
  if (!m) return null;
  const iso = `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  const d = new Date(iso + "T00:00:00Z");
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === iso ? iso : null;
}

/** Date field that always shows and accepts DD/MM/YYYY (the native date input follows the browser locale, e.g.
 *  MM/DD/YYYY). The value in and out stays ISO YYYY-MM-DD; the calendar button opens the native picker. */
export function DateInput({ value, onChange, min, max, ariaLabel }: {
  value: string; onChange: (iso: string) => void; min?: string; max?: string; ariaLabel?: string;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(value ? fmtDate(value) : "");
  const [bad, setBad] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => { setText(value ? fmtDate(value) : ""); setBad(false); }, [value]);
  const commit = (s: string) => {
    if (!s.trim()) { setBad(false); onChange(""); return; }
    const iso = parseDmy(s);
    const ok = !!iso && (!min || iso >= min) && (!max || iso <= max);
    setBad(!ok);
    if (ok) onChange(iso!);
  };
  return (
    <span className="dateinput">
      <input type="text" inputMode="numeric" placeholder="DD/MM/YYYY" value={text} aria-label={ariaLabel} aria-invalid={bad}
        className={bad ? "invalid" : ""} onChange={(e) => { setText(e.target.value); if (parseDmy(e.target.value)) commit(e.target.value); }}
        onBlur={(e) => commit(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") commit((e.target as HTMLInputElement).value); }} />
      <button type="button" className="cal" aria-label={t("common.pick_date")} title={t("common.pick_date")} onClick={() => {
        const el = picker.current as any;
        if (el?.showPicker) el.showPicker(); else el?.click();
      }}><Icon name="calendar" /></button>
      <input ref={picker} type="date" className="native" tabIndex={-1} aria-hidden value={value} min={min} max={max}
        onChange={(e) => onChange(e.target.value)} />
    </span>
  );
}
export const fmtBytes = (b: number | null | undefined) =>
  b === null || b === undefined ? "—" : b > 1e9 ? `${fmtNum(b / 1e9, 2)} GB` : b > 1e6 ? `${fmtNum(b / 1e6, 1)} MB` : `${fmtNum(b / 1e3, 0)} KB`;

// ---------------------------------------------------------------- data loading
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);
  const reload = useCallback(async () => {
    // 1.2.8: only the newest request sets the state - an older answer arriving later (horizon changed twice quickly,
    // another day chosen) never replaces the newer one, and loading stays on until the newest one answered
    const my = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const d = await fnRef.current();
      if (my === seq.current) setData(d);
    } catch (e) {
      if (my === seq.current) setError(e);
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void reload(), deps);
  return { data, error, loading, reload, setData };
}

/** Run an action, track busy state and keep the backend's confirmed result / error. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      const r = await fn();
      if (okMsg) setOk(okMsg);
      return r;
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, ok, run, setError, setOk };
}

// ---------------------------------------------------------------- building blocks
export function Card({ title, children, actions, className, icon }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string; icon?: IconName }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <header className="card-h">
          <h3>{icon && <Icon name={icon} />}{title}</h3>
          <div className="row">{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

/** KPI card: label (+ icon), main value, secondary line. `tone` adds a coloured edge AND colours the value; it is
 *  only used together with a value that already says what it means. */
export function Stat({ label, value, sub, tone, icon }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: string; icon?: IconName }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="stat-l">{icon && <Icon name={icon} size={14} />}{label}</div>
      <div className="stat-v">{value}</div>
      {sub && <div className="stat-s">{sub}</div>}
    </div>
  );
}

const TONE: Record<string, string> = {
  SUCCEEDED: "ok", ACCEPTED: "ok", PUBLISHED: "ok", ACTIVE: "ok", OK: "ok", FRESH: "ok",
  FAILED: "bad", REJECTED: "warn", RUNNING: "info", PENDING: "muted", PENDING_REVIEW: "info", CANDIDATE: "info",
  RETRY_WAIT: "warn", SKIPPED: "muted", REPLACED: "muted", DELETED: "muted", CANCELLED: "muted",
  STALE: "bad", NEEDS_CONFIG: "warn", INSUFFICIENT: "warn",
  ERROR: "bad", WARNING: "warn", INFO: "info", DUPLICATE: "muted",
  USABLE: "ok", USABLE_WITH_WARNING: "warn", NOT_USABLE: "bad", PASS: "ok", BELOW_THRESHOLD: "warn",
  NOT_EVALUATED: "muted", LOW: "warn", NORMAL: "ok",
  COMPLETE: "ok", PROVISIONAL: "warn", NO_ACTUAL: "muted",          // 1.2.5 actual status (forecast history)
  CLOSED: "info", SNAPSHOT: "info",                                 // 1.2.6 closed at the end of the day / backup forecast
};

export function Pill({ status, label }: { status: string; label?: string }) {
  const { t } = useI18n();
  const key = `status.${status}`;
  const text = label ?? (t(key) !== key ? t(key) : t(`sev.${status}`) !== `sev.${status}` ? t(`sev.${status}`) : status);
  return <span className={`pill ${TONE[status] ?? "muted"} st-${status}`}>{text}</span>;
}

const SOURCE_ICON: Record<string, IconName> = { DEMO: "demo", MANUAL_IMPORT: "export", BIGQUERY: "bigquery" };

export function SourceBadge({ source }: { source?: string | null }) {
  if (!source) return null;
  return <span className={`src src-${source}`} title={source}>{SOURCE_ICON[source] && <Icon name={SOURCE_ICON[source]} size={12} />}{source}</span>;
}

/** Yes / no with an icon AND the word (never a bare tick or cross). */
export function YesNo({ v, yes, no }: { v: boolean | null | undefined; yes?: string; no?: string }) {
  const { t } = useI18n();
  if (v === null || v === undefined) return <span className="muted">—</span>;
  return <span className={`yn ${v ? "ok-t" : "bad-t"}`}><Icon name={v ? "ok" : "bad"} size={14} />{v ? yes ?? t("common.yes") : no ?? t("common.no")}</span>;
}

const checkValue = (c: any) => {
  const f = (v: any) => (typeof v !== "number" ? "—" : c.check.includes("POINTS") || c.check === "BACKTEST_RELIABLE" ? fmtNum(v) : c.check === "ABS_BIAS_MAX" ? fmtSignedPct(v) : fmtPct(v));
  return c.threshold === null || c.threshold === undefined ? f(c.value) : `${f(c.value)} / ${f(c.threshold)}`;
};

/** 1.2.2: the separate statements about the model behind a forecast - technical, quality vs the configured
 * thresholds, evaluation confidence, usage under the policy - and the candidate that was selected. A result below
 * the thresholds is shown as a warning: never hidden, never presented as "good". */
export function AssessmentBox({ a, compact = false }: { a: any; compact?: boolean }) {
  const { t } = useI18n();
  if (!a) return null;
  const usage = a.usage?.status;
  const failed = (a.quality?.checks ?? []).filter((c: any) => !c.passed);
  const sel = a.selection;
  const cands = sel?.candidates ? Object.entries(sel.candidates) as [string, any][] : [];
  return (
    <div className={`alert ${usage === "NOT_USABLE" ? "error" : usage === "USABLE_WITH_WARNING" ? "warn" : "info"} small`} data-testid="assessment">
      <div className="row wrap">
        <span>{t("as.usage")}: <Pill status={usage ?? "NOT_EVALUATED"} /></span>
        <span>{t("as.quality")}: <Pill status={a.quality?.status ?? "NOT_EVALUATED"} /></span>
        <span>{t("as.confidence")}: <Pill status={a.confidence?.level ?? "NOT_EVALUATED"} /></span>
        <span>{t("as.technical")}: <Pill status={a.technical?.status === "FAILED" ? "FAILED" : "OK"} /></span>
        {a.candidate && <span>{t("as.candidate")}: <b data-testid="as-candidate">{t(`as.cand.${a.candidate}`)}</b></span>}
      </div>
      {failed.length > 0 && (
        <div data-testid="as-failed">{failed.map((c: any) => `${t(`perf.check.${c.check}`)}: ${checkValue(c)}`).join(" · ")}</div>
      )}
      {a.confidence?.level === "LOW" && <div>{t("as.low_conf")}: {(a.confidence.reasons ?? []).map((r: string) => t(`perf.check.${r}`)).join(", ")}</div>}
      {usage === "USABLE_WITH_WARNING" && <div data-testid="as-warning">{a.exception ? t("as.exception_text") : t("as.warn_text")}</div>}
      {usage === "NOT_USABLE" && <div>{t(`as.usage_reason.${a.usage?.reason ?? "QUALITY_GATE_FAILED"}`)}</div>}
      {!compact && cands.length > 0 && (
        <table className="tbl small" data-testid="as-candidates">
          <thead><tr><th>{t("as.candidate")}</th><th className="num">WAPE</th><th className="num">Bias</th><th className="num">{t("perf.points")}</th><th></th></tr></thead>
          <tbody>
            {cands.map(([k, c]) => (
              <tr key={k}><td>{t(`as.cand.${k}`)}</td><td className="num">{fmtPct(c.metrics?.wape)}</td><td className="num">{fmtSignedPct(c.metrics?.bias)}</td>
                <td className="num">{fmtNum(c.metrics?.n_points)}</td>
                <td>{k === sel.chosen ? <Pill status="OK" label={t("as.chosen")} /> : <Pill status="SKIPPED" label={t("as.rejected")} />}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {!compact && sel?.reason && <div className="muted">{t("as.rule")} — {t(`as.reason.${sel.reason}`)}</div>}
      {!compact && a.policy && <div className="muted">{t(`as.policy.${a.policy}`)}</div>}
    </div>
  );
}

/** Open/close behaviour shared by all explanation tooltips: mouse hover, keyboard focus (Enter/Space/Escape) and
 *  touch tap. A tap fires focus + click (and an emulated hover), so the click decides from the state captured at
 *  pointer-down instead of blindly toggling (which closed the tooltip right after it opened on touch screens). */
export function useTooltip() {
  const [open, setOpen] = useState(false);
  const pointer = useRef<{ type: string; wasOpen: boolean }>({ type: "mouse", wasOpen: false });
  const isMouse = (e: { pointerType?: string }) => (e.pointerType || "mouse") === "mouse";
  const handlers = {
    onPointerDown: (e: React.PointerEvent) => { pointer.current = { type: e.pointerType || "mouse", wasOpen: open }; },
    onPointerEnter: (e: React.PointerEvent) => { if (isMouse(e)) setOpen(true); },
    onPointerLeave: (e: React.PointerEvent) => { if (isMouse(e)) setOpen(false); },
    onFocus: () => setOpen(true),
    onBlur: () => setOpen(false),
    onClick: () => setOpen(pointer.current.type === "mouse" ? true : !pointer.current.wasOpen),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen((o) => !o); }
    },
  };
  return { open, setOpen, handlers };
}

/** Technical term with a plain-language explanation on hover/focus/click. */
export function Term({ id, children }: { id: string; children?: ReactNode }) {
  const { lang } = useI18n();
  const { open, handlers } = useTooltip();
  const term = TERM_BY_ID[id];
  if (!term) return <>{children}</>;
  const tt = term[lang];
  return (
    <span className="term" tabIndex={0} role="button" aria-expanded={open} {...handlers}>
      {children ?? tt.name}
      <span className="term-i" aria-hidden>?</span>
      {open && (
        <span className="term-pop" role="tooltip">
          <b>{tt.name}</b>
          <span>{tt.meaning}</span>
          {tt.read && <em>{tt.read}</em>}
        </span>
      )}
    </span>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const { lang, t } = useI18n();
  if (!error) return null;
  let title = t("common.error");
  let detail: string | null | undefined = null;
  let category: string | undefined;
  let requestId: string | undefined;
  if (error instanceof ApiError) {
    title = (lang === "vi" ? error.body.vi : error.body.en) || error.body.code;
    detail = error.body.detail;
    category = error.body.category;
    requestId = error.body.request_id;
  } else if (error instanceof Error) {
    title = t("err.backend_unreachable");
    detail = error.message;
  }
  // database / storage / internal errors: never show internals, point at the diagnostic report instead
  const showDetail = detail && !["DATABASE", "INTERNAL"].includes(category ?? "");
  return (
    <div className="alert bad" role="alert">
      {category && <span className="pill bad">{t(`errcat.${category}`)}</span>} <b>{title}</b>
      {error instanceof ApiError && <code className="code">{error.body.code}</code>}
      {showDetail && <div className="small">{fmtDatesInText(detail)}</div>}
      {["DATABASE", "INTERNAL", "STORAGE"].includes(category ?? "") && (
        <div className="small">{t("err.diag_hint")} <a href="/system">{t("nav.system")}</a>{requestId ? ` · request ID: ${requestId}` : ""}</div>
      )}
    </div>
  );
}

export function OkBox({ text }: { text: string | null }) {
  return text ? <div className="alert ok" role="status">{text}</div> : null;
}

export function Loading() {
  const { t } = useI18n();
  return <div className="loading" aria-busy="true"><Icon name="running" className="spin" />{t("common.loading")}</div>;
}

/** Empty state: what is missing, optionally why / what to do next (`hint`) and an action. */
export function Empty({ text, hint, icon = "empty", action }: { text: string; hint?: ReactNode; icon?: IconName; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} size={28} />
      <div className="empty-t">{text}</div>
      {hint && <div className="empty-h">{hint}</div>}
      {action}
    </div>
  );
}

/** Page title block shared by every page: icon, title, one-line purpose, page-level actions. */
export function PageHeader({ icon, title, desc, actions }: { icon: IconName; title: ReactNode; desc?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-h">
      <div className="page-h-main">
        <span className="page-ic" aria-hidden="true"><Icon name={icon} size={20} /></span>
        <div className="page-h-text">
          <h2>{title}</h2>
          {desc && <p className="page-desc">{desc}</p>}
        </div>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

/** Icon-only button: the label is both the accessible name and the tooltip. */
export function IconButton({ icon, label, onClick, disabled, className, testid }: {
  icon: IconName; label: string; onClick: () => void; disabled?: boolean; className?: string; testid?: string;
}) {
  return (
    <button type="button" className={`icon-btn ${className ?? ""}`} aria-label={label} title={label} onClick={onClick} disabled={disabled} data-testid={testid}>
      <Icon name={icon} />
    </button>
  );
}

/** Text search with a search icon and a clear button (shown only when there is something to clear; Escape clears). */
export function SearchInput({ value, onChange, label, placeholder, clearLabel, testid, clearTestid }: {
  value: string; onChange: (v: string) => void; label: string; placeholder?: string; clearLabel: string; testid?: string; clearTestid?: string;
}) {
  return (
    <span className="search">
      <Icon name="search" size={14} />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label} data-testid={testid}
        onKeyDown={(e) => { if (e.key === "Escape" && value) onChange(""); }} />
      {value && <IconButton icon="close" label={clearLabel} className="ghost small" testid={clearTestid} onClick={() => onChange("")} />}
    </span>
  );
}

/** Filter area: labelled fields, the number of filters in effect and one "clear filters" action. */
export function FilterBar({ children, active = 0, onClear, extra }: { children: ReactNode; active?: number; onClear?: () => void; extra?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="filterbar-w" role="group" aria-label={t("filter.title")}>
      <div className="filterbar-h">
        <span className="filterbar-t" data-testid="filter-state">
          <Icon name="filter" size={14} />{t("filter.title")}
          {active > 0 ? <span className="badge" title={t("filter.active").replace("{n}", String(active))}>{active}</span>
            : <span className="small muted">· {t("filter.none")}</span>}
        </span>
        <span className="row">
          {extra}
          {onClear && active > 0 && (
            <button type="button" className="ghost small" onClick={onClear} data-testid="filter-clear"><Icon name="clearFilter" size={14} />{t("filter.clear")}</button>
          )}
        </span>
      </div>
      <div className="filterbar">{children}</div>
    </div>
  );
}

/** Previous / next pager with "page x / y · n rows". */
export function Pager({ page, total, size, unit, onPage }: { page: number; total: number; size: number; unit: string; onPage: (p: number) => void }) {
  const { t } = useI18n();
  return (
    <div className="row pager">
      <button disabled={page === 0} onClick={() => onPage(page - 1)}><Icon name="prev" size={14} />{t("common.prev")}</button>
      <span className="pager-info">{t("common.page")} {page + 1} / {Math.max(1, Math.ceil(total / size))} · {fmtNum(total)} {unit}</span>
      <button disabled={(page + 1) * size >= total} onClick={() => onPage(page + 1)}>{t("common.next")}<Icon name="next" size={14} /></button>
    </div>
  );
}

// ---------------------------------------------------------------- charts (dependency-free SVG)
export interface ChartActual { x: string; y: number; tooltip: string; legend: string }

/** Forecast line + (optionally) ONE actual point for today. The actual is never drawn as a line into the future. */
export function LineChart({ points, height = 240, label, actual, forecastLegend }: {
  points: { x: string; y: number }[]; height?: number; label?: string; actual?: ChartActual | null; forecastLegend?: string;
}) {
  const { lang } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  useEffect(() => {   // draw in real pixels so labels keep their size on any screen (no ResizeObserver in tests: 760)
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const w = Math.round(e.contentRect.width); if (w > 0) setWidth(Math.max(320, w)); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [points.length > 0]);
  if (!points.length) return null;
  const ai = actual ? points.findIndex((p) => p.x === actual.x) : -1;
  const max = Math.max(...points.map((p) => p.y), ai >= 0 ? actual!.y : 0, 1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  // left margin sized to the longest value label, so large totals are never cut off
  const W = width, H = height, P = { l: Math.max(44, Math.max(...ticks.map((v) => fmtNum(v).length)) * 7 + 16), r: 16, t: 14, b: 30 };
  const x = (i: number) => P.l + (points.length === 1 ? (W - P.l - P.r) / 2 : (i * (W - P.l - P.r)) / (points.length - 1));
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / max);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(" ");
  const n = points.length;
  const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((W - P.l - P.r) / 84))));   // a DD/MM/YYYY label needs ~84 px
  // the last date is always labelled; a regular label too close to it is dropped (labels never overlap), and the
  // first / last labels are anchored inside the plot so they are never cut off
  const showLabel = (i: number) => i === n - 1 || (i % step === 0 && n - 1 - i >= step);
  const anchor = (i: number) => (n > 1 && i === n - 1 ? "end" : n > 1 && i === 0 ? "start" : "middle");
  // 1.2.12: the forecast date of the hovered day with its weekday (axis labels keep the date only, for space)
  const tipLines = hover === null ? [] : [`${fmtDateWd(points[hover].x, lang)}: ${fmtNum(points[hover].y, 1)}`,
    ...(hover === ai ? [`${actual!.tooltip}: ${fmtNum(actual!.y, 1)}`] : [])];
  const tipW = Math.max(0, ...tipLines.map((s) => s.length)) * 7 + 16;
  const tipX = hover === null ? 0 : x(hover) + 12 + tipW > W - P.r ? x(hover) - 12 - tipW : x(hover) + 12;
  return (
    <div className="chart" ref={box}>
      {(forecastLegend || ai >= 0) && (
        <div className="legend small">
          {forecastLegend && <span><i className="lg-line" /> {forecastLegend}</span>}
          {ai >= 0 && <span><i className="lg-actual" /> {actual!.legend}</span>}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className="grid" />
            <text x={P.l - 6} y={y(v) + 4} textAnchor="end" className="axis">{fmtNum(v)}</text>
          </g>
        ))}
        {points.map((p, i) => showLabel(i) && (
          <text key={p.x} x={x(i)} y={H - 8} textAnchor={anchor(i)} className="axis">{fmtDate(p.x)}</text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={P.t} y2={H - P.b} className="guide" />}
        <path d={path} className="line" />
        {points.length <= 45 && points.map((p, i) => <circle key={p.x} cx={x(i)} cy={y(p.y)} r={2.5} className="pt" />)}
        {ai >= 0 && <rect x={x(ai) - 5} y={y(actual!.y) - 5} width={10} height={10} rx={2} className="actual-pt" data-testid="actual-point" />}
        {points.map((_p, i) => (
          <rect key={i} x={x(i) - (W / points.length) / 2} y={P.t} width={W / points.length} height={H - P.t - P.b}
            fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        {hover !== null && (
          <g pointerEvents="none">
            <circle cx={x(hover)} cy={y(points[hover].y)} r={4.5} className="dot" />
            <rect x={tipX} y={P.t} width={tipW} height={tipLines.length * 18 + 10} rx={6} className="tipbox" />
            {tipLines.map((s, k) => (
              <text key={k} x={tipX + 8} y={P.t + 19 + k * 18} className={k === 1 ? "tip actual-t" : "tip"}>{s}</text>
            ))}
          </g>
        )}
      </svg>
    </div>
  );
}

export interface ComparePoint { x: string; forecast: number | null; actual: number | null; provisional?: boolean; backup?: boolean; tip: string[] }

/** 1.2.5: stored forecast (blue line + dots) against actual (orange squares) per date. A missing value stays a gap -
 *  nothing is interpolated or invented to join the line. A provisional actual is a hollow square on a dashed segment,
 *  a complete one a filled square; the tooltip says which. 1.2.6: a forecast taken from the end-of-day backup is a
 *  tinted dot on a dashed segment. Same pixel / label rules as LineChart. */
export function CompareChart({ points, height = 260, label, legend }: {
  points: ComparePoint[]; height?: number; label?: string; legend: { forecast: string; actual: string; provisional: string; backup?: string };
}) {
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const w = Math.round(e.contentRect.width); if (w > 0) setWidth(Math.max(320, w)); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [points.length > 0]);
  if (!points.length) return null;
  const vals = points.flatMap((p) => [p.forecast, p.actual]).filter((v): v is number => v !== null && v !== undefined);
  const max = Math.max(...vals, 1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const W = width, H = height, P = { l: Math.max(44, Math.max(...ticks.map((v) => fmtNum(v).length)) * 7 + 16), r: 16, t: 14, b: 30 };
  const n = points.length;
  const x = (i: number) => P.l + (n === 1 ? (W - P.l - P.r) / 2 : (i * (W - P.l - P.r)) / (n - 1));
  const y = (v: number) => P.t + (H - P.t - P.b) * (1 - v / max);
  const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((W - P.l - P.r) / 84))));
  const showLabel = (i: number) => i === n - 1 || (i % step === 0 && n - 1 - i >= step);
  const anchor = (i: number) => (n > 1 && i === n - 1 ? "end" : n > 1 && i === 0 ? "start" : "middle");
  // only consecutive known values are joined: a gap in the data is a gap in the line
  const segs = (get: (p: ComparePoint) => number | null, flag: (p: ComparePoint) => boolean | undefined) => points.slice(1).map((p, k) => {
    const a = get(points[k]), b = get(p);
    return a === null || a === undefined || b === null || b === undefined ? null
      : { i: k + 1, d: `M${x(k).toFixed(1)},${y(a).toFixed(1)} L${x(k + 1).toFixed(1)},${y(b).toFixed(1)}`, prov: !!(flag(points[k]) || flag(p)) };
  }).filter(Boolean) as { i: number; d: string; prov: boolean }[];
  const tip = hover === null ? [] : points[hover].tip;
  const tipW = Math.max(0, ...tip.map((s) => s.length)) * 7 + 16;
  const tipX = hover === null ? 0 : x(hover) + 12 + tipW > W - P.r ? x(hover) - 12 - tipW : x(hover) + 12;
  const anyProv = points.some((p) => p.actual !== null && p.provisional);
  const anyBackup = points.some((p) => p.forecast !== null && p.backup);
  return (
    <div className="chart" ref={box} data-testid="compare-chart">
      <div className="legend small">
        <span><i className="lg-line" /> {legend.forecast}</span>
        {anyBackup && legend.backup && <span><i className="lg-line bk" /> {legend.backup}</span>}
        <span><i className="lg-actual" /> {legend.actual}</span>
        {anyProv && <span><i className="lg-actual prov" /> {legend.provisional}</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className="grid" />
            <text x={P.l - 6} y={y(v) + 4} textAnchor="end" className="axis">{fmtNum(v)}</text>
          </g>
        ))}
        {points.map((p, i) => showLabel(i) && (
          <text key={p.x} x={x(i)} y={H - 8} textAnchor={anchor(i)} className="axis">{fmtDate(p.x)}</text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={P.t} y2={H - P.b} className="guide" />}
        {segs((p) => p.forecast, (p) => p.backup).map((s) => <path key={`f${s.i}`} d={s.d} className={s.prov ? "line bk" : "line"} />)}
        {segs((p) => p.actual, (p) => p.provisional).map((s) => <path key={`a${s.i}`} d={s.d} className={s.prov ? "actual-line prov" : "actual-line"} />)}
        {points.map((p, i) => p.forecast !== null && (
          <circle key={`fp${p.x}`} cx={x(i)} cy={y(p.forecast)} r={3} className={p.backup ? "pt bk" : "pt"} data-testid="cmp-forecast-pt"
            data-source={p.backup ? "backup" : "primary"} />
        ))}
        {points.map((p, i) => p.actual !== null && (
          <rect key={`ap${p.x}`} x={x(i) - 5} y={y(p.actual) - 5} width={10} height={10} rx={2}
            className={p.provisional ? "actual-pt prov" : "actual-pt"} data-testid="cmp-actual-pt" data-status={p.provisional ? "provisional" : "complete"} />
        ))}
        {points.map((_p, i) => (
          <rect key={i} x={x(i) - (W / n) / 2} y={P.t} width={W / n} height={H - P.t - P.b} fill="transparent"
            onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} />
        ))}
        {hover !== null && (
          <g pointerEvents="none">
            <rect x={tipX} y={P.t} width={tipW} height={tip.length * 18 + 10} rx={6} className="tipbox" />
            {tip.map((s, k) => <text key={k} x={tipX + 8} y={P.t + 19 + k * 18} className="tip">{s}</text>)}
          </g>
        )}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------- forecast method registry (backend /api/methods)
let _methods: any = null;
let _methodsPending: Promise<void> | null = null;

export function useMethods() {
  const [, force] = useState(0);
  useEffect(() => {
    if (_methods) return;
    _methodsPending = _methodsPending ?? fetch("/api/methods").then((r) => r.json()).then((m) => { _methods = m; })
      .catch(() => { _methods = { methods: {}, reasons: {} }; });
    _methodsPending.then(() => force((n) => n + 1));
  }, []);
  return _methods as { methods: Record<string, any>; reasons: Record<string, { vi: string; en: string }> } | null;
}

/** Business-friendly method name with an explanation on hover, keyboard focus or tap, linking to the docs. */
export function MethodLabel({ code, showCode = false }: { code?: string | null; showCode?: boolean }) {
  const { lang, t } = useI18n();
  const reg = useMethods();
  const { open, handlers } = useTooltip();
  if (!code) return null;
  const m = reg?.methods?.[code];
  if (!m) return <span className="mono small">{code}</span>;
  const d = m[lang];
  return (
    <span className="term method" tabIndex={0} role="button" aria-expanded={open} aria-label={d.name} {...handlers}>
      {d.name}{showCode && <code className="code">{code}</code>}
      <span className="term-i" aria-hidden>?</span>
      {open && (
        <span className="term-pop" role="tooltip">
          <b>{d.name}</b>
          <span>{d.short}</span>
          <em>{t("method.when")}: {d.when}</em>
          <a href={`/methodology#${m.anchor}`} onMouseDown={(e) => e.preventDefault()}>{t("method.read_more")} →</a>
          <span className="mono">{code}</span>
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------- job progress (real stages, no fake percentage)
const TERMINAL = ["SUCCEEDED", "FAILED", "SKIPPED"];

export function jobOutcome(job: any): "running" | "ok" | "warn" | "bad" | "skipped" | "unknown" {
  if (!job) return "unknown";
  if (!TERMINAL.includes(job.status)) return job.stale ? "unknown" : "running";
  if (job.status === "FAILED") return "bad";
  if (job.status === "SKIPPED") return "skipped";
  const r = job.result?.result;
  if (r?.status === "FAILED") return "bad";
  if (r?.status === "REJECTED") return "warn";
  if (r?.status === "SKIPPED") return "skipped";
  return "ok";
}

/** Polls GET /api/jobs/{id} until the job is terminal. A polling error is shown as "connection lost" - it never
 *  marks the job as failed. */
export function JobProgress({ jobId, onDone }: { jobId: string | null; onDone?: (job: any) => void }) {
  const { t } = useI18n();
  const [job, setJob] = useState<any>(null);
  const [lost, setLost] = useState(false);
  const doneRef = useRef(false);
  useEffect(() => {
    if (!jobId) return;
    doneRef.current = false;
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const r = await fetch(`/api/jobs/${jobId}`);
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        if (stop) return;
        setJob(j);
        setLost(false);
        if (TERMINAL.includes(j.status)) {
          if (!doneRef.current) { doneRef.current = true; onDone?.(j); }
          return;
        }
      } catch {
        if (!stop) setLost(true);
      }
      if (!stop) timer = window.setTimeout(tick, 2000);
    };
    tick();
    return () => { stop = true; if (timer) window.clearTimeout(timer); };
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!jobId) return null;
  if (!job) return <div className="jobbox"><span className="small">{lost ? t("job.connection_lost") : t("job.accepted")}</span></div>;
  const outcome = jobOutcome(job);
  const r = job.result?.result;
  const tone = { running: "info", ok: "ok", warn: "warn", bad: "bad", skipped: "muted", unknown: "warn" }[outcome];
  return (
    <div className={`jobbox ${tone}`} role="status" aria-live="polite">
      <div className="row wrap">
        <span className={`pill ${tone}`}>{t(`job.outcome.${outcome}`)}</span>
        <b>{t(`job.${job.job_type}`)}</b>
        <span className="small">{t("job.stage")}: {t(`stage.${job.stage ?? "QUEUED"}`)}</span>
        {job.elapsed_seconds != null && <span className="small">· {t("job.elapsed")}: {fmtDuration(job.elapsed_seconds)}</span>}
        {job.started_at && <span className="small">· {t("job.started")}: {fmtTime(job.started_at)}</span>}
        {job.finished_at && TERMINAL.includes(job.status) && <span className="small">· {t("job.finished")}: {fmtTime(job.finished_at)}</span>}
        <a className="small" href={`/jobs?job=${job.id}`}>{t("common.details")} →</a>
      </div>
      {lost && <div className="small warn-t">{t("job.connection_lost")}</div>}
      {job.stale && <div className="small warn-t">{t("job.stale")}</div>}
      {outcome !== "running" && job.job_type === "TRAIN_PUBLISH" && r && (
        <div className="small">
          {t("job.training_result")}: <b>{r.status === "PUBLISHED" ? t("status.ACCEPTED") : r.status === "REJECTED" ? t("status.REJECTED") : r.status === "FAILED" ? t("status.FAILED") : t("status.SKIPPED")}</b>
          {" · "}{t("job.publish_result")}: <b>{r.status === "PUBLISHED" ? t("status.PUBLISHED") : t("job.not_published")}</b>
          {r.failed_stage && <> · {t("job.failed_at")}: {t(`stage.${r.failed_stage}`)}</>}
        </div>
      )}
      {outcome !== "running" && (job.reason_code || r?.reason_code) && <div className="small"><Code code={r?.reason_code || job.reason_code} /></div>}
      {job.error && <div className="small bad-t">{fmtDatesInText(job.error)}</div>}
    </div>
  );
}

export function fmtDuration(sec: number): string {
  if (sec < 60) return `${Math.round(sec)} s`;
  const m = Math.floor(sec / 60);
  return `${m} min ${Math.round(sec - m * 60)} s`;
}

export function Bars({ items }: { items: { label: string; value: number }[] }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="bars">
      {items.map((i) => (
        <div key={i.label} className="bar-row">
          <span className="bar-l" title={i.label}>{i.label}</span>
          <span className="bar-t"><span className="bar-f" style={{ width: `${(100 * i.value) / max}%` }} /></span>
          <span className="bar-v">{fmtNum(i.value, 1)}</span>
        </div>
      ))}
    </div>
  );
}

export function Confirm({ open, title, children, onCancel, onConfirm, confirmLabel, danger, disabled }: {
  open: boolean; title: ReactNode; children: ReactNode; onCancel: () => void; onConfirm: () => void;
  confirmLabel?: string; danger?: boolean; disabled?: boolean;
}) {
  const { t } = useI18n();
  useEffect(() => {   // Escape = cancel, as on every dialog
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, onCancel]);
  if (!open) return null;
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="modal">
        <h3 id="confirm-title">{danger && <Icon name="warn" size={20} className="modal-ic-danger" />}{title}</h3>
        <div>{children}</div>
        <div className="row end">
          <button onClick={onCancel}>{t("common.cancel")}</button>
          <button className={danger ? "danger" : "primary"} onClick={onConfirm} disabled={disabled}>{confirmLabel ?? t("common.confirm")}</button>
        </div>
      </div>
    </div>
  );
}

export function Field({ label, children, help }: { label: ReactNode; children: ReactNode; help?: ReactNode }) {
  return (
    <label className="field">
      <span className="field-l">{label}</span>
      {children}
      {help && <span className="field-h">{help}</span>}
    </label>
  );
}

// ---------------------------------------------------------------- backend message codes
let _catalog: Record<string, { vi: string; en: string }> | null = null;
let _pending: Promise<void> | null = null;

export function useCatalog() {
  const [, force] = useState(0);
  useEffect(() => {
    if (_catalog) return;
    _pending = _pending ?? fetch("/api/messages").then((r) => r.json()).then((c) => { _catalog = c; }).catch(() => { _catalog = {}; });
    _pending.then(() => force((n) => n + 1));
  }, []);
  return _catalog;
}

/** Shows the bilingual explanation for a backend code, with the code itself for traceability. */
export function Code({ code, showCode = true }: { code?: string | null; showCode?: boolean }) {
  const { lang } = useI18n();
  const cat = useCatalog();
  if (!code) return null;
  const m = cat?.[code];
  return (
    <span className="codetext">
      {m ? (lang === "vi" ? m.vi : m.en) : code}
      {showCode && m && <code className="code">{code}</code>}
    </span>
  );
}
