import { useEffect, useState } from "react";
import { ApiError, get, post, type ApiErrorBody } from "../api";
import { DICT, useI18n } from "../i18n";
import { Card, ErrorBox, Field, Loading, OkBox, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "./ui";
import { Icon } from "./icons";
import { normReason, reasonLen } from "./guardedShared";

// 1.4.15 (GD-L1, lot 1b): the five data_policy items that the old "Chính sách dữ liệu" card (Save / Reset to defaults) must never
// overwrite. Compare-and-set per field: preview (nothing written) -> confirmation -> apply; no reset button, no shortcut.

export type Policy = "FOLLOW_SOURCE" | "KEEP_OBSERVED_LINES";
export type TrainingRule = "WINDOW_START" | "OPEN_HOURS_COVERAGE";
export interface GuardedFields {
  window_start_date: string;
  history_change_policy: Policy;
  history_day_check: boolean;
  source_time_travel_hours: number;
  training_start_rule: TrainingRule;
}
/** values = the fields right AFTER the row, previous_values = right BEFORE it (the first row: the code defaults);
 *  changed_fields = the fields that row changed (undo restores only those) */
export interface GuardedHistory {
  id: number; changed_at: string; note?: string | null; values: GuardedFields; previous_values?: GuardedFields; changed_fields?: string[];
}
export interface GuardedState {
  fields: GuardedFields;
  defaults: GuardedFields;
  version: number;
  confirm_text: string;
  high_risk_fields: string[];
  reason_min_length?: number;
  locked_fields?: string[];          // window_start_date: shown read-only, never in patch / expected
  locked_reason_code?: string;
  history: GuardedHistory[];
}
/** kind HELD_LINES: active_held_lines / capped; kind TRAINING_START: the effective start of the model input now and after */
export interface GuardedImpact {
  kind?: string; active_held_lines?: number | null; capped?: boolean; applies_from?: string;
  window_start_date?: string | null; coverage_start?: string | null; effective_current?: string | null; effective_after?: string | null; delta_days?: number | null;
}
/** the server's busy check at preview time: busy = Apply is refused now; window = night window; jobs = running jobs;
 *  stale_ignored = overdue jobs that were left out of the check */
export interface GuardedBusy { busy: boolean; detail?: string | null; window?: unknown; jobs?: unknown; stale_ignored?: unknown }
export interface GuardedPreview {
  before: Partial<GuardedFields>;
  after: Partial<GuardedFields>;
  changed: string[];
  high_risk: boolean;
  needs_confirm_text: boolean;
  needs_acknowledged?: boolean;
  confirm_text?: string;   // the text of the Vietnam day at the moment of the preview (a preview can be days-boundary away from the GET)
  impact: GuardedImpact | null;     // the first estimate (kept for older servers)
  impacts?: GuardedImpact[];        // every estimate: a patch of policy + training start rule has both kinds here
  busy?: GuardedBusy | null;
  notes?: string[];        // codes: APPLIES_AT_NEXT_D1, FOLLOW_SOURCE_DROPS_REMOVED_LINES, KEEP_OBSERVED_LINES_HOLDS_REMOVED_LINES, UNDO_SETTINGS_ONLY
  warnings: string[];      // codes: "NO_CHANGE", "NO_IMPACT_ESTIMATE:a,b" (older servers: plain sentences, shown as they are)
}
export interface GuardedApplyBody {
  patch: Partial<GuardedFields>;
  expected: Partial<GuardedFields>;
  confirm_text?: string;
  reason?: string;
  acknowledged?: boolean;
}

export const getGuardedPolicy = () => get<GuardedState>("/api/data-policy/guarded");
export const previewGuardedPolicy = (patch: Partial<GuardedFields>) =>
  post<GuardedPreview>("/api/data-policy/guarded/preview", { patch });
export const applyGuardedPolicy = (body: GuardedApplyBody) =>
  post<{ applied: Partial<GuardedFields>; version: number }>("/api/data-policy/guarded", body);

// the fields the form can change; window_start_date is locked in this version (shown read-only, the server refuses it)
const KEYS: (keyof GuardedFields)[] = ["history_change_policy", "history_day_check", "source_time_travel_hours", "training_start_rule"];
const DEFAULT_MIN_REASON = 10;   // the server sends reason_min_length; this is only the fallback
const MAX_REASON = 500;
const GP_CODES = ["DATA_POLICY_BUSY", "DATA_POLICY_FIELD_LOCKED", "DATA_POLICY_CONFIRM_REQUIRED", "DATA_POLICY_UNKNOWN_FIELD", "DATA_POLICY_EXPECTED_REQUIRED", "DATA_POLICY_INVALID_VALUE", "NO_CHANGE"];

/** params of the error body of the guarded endpoints (SETTINGS_CHANGED_ELSEWHERE: current + version;
 *  DATA_POLICY_CONFIRM_REQUIRED: confirm_text). api.ts types the body without params, hence this small guard. */
interface ErrParams { current?: Record<string, unknown>; version?: number; confirm_text?: string }
function errParams(e: unknown): ErrParams {
  if (!(e instanceof ApiError)) return {};
  const raw = (e.body as ApiErrorBody & { params?: unknown }).params;
  if (!raw || typeof raw !== "object") return {};
  const r = raw as Record<string, unknown>;
  return {
    current: r.current && typeof r.current === "object" ? (r.current as Record<string, unknown>) : undefined,
    version: typeof r.version === "number" ? r.version : undefined,
    confirm_text: typeof r.confirm_text === "string" && r.confirm_text ? r.confirm_text : undefined,
  };
}

/** names out of a list the server sends (strings, or objects with a job type / name / id): never raw JSON */
function names(x: unknown): string[] {
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

const validHours = (n: unknown) => typeof n === "number" && Number.isInteger(n) && n >= 1 && n <= 168;

/** the fields of `draft` that differ from the loaded (running) values: this is the patch that is sent */
function diff(loaded: GuardedFields, draft: GuardedFields): Partial<GuardedFields> {
  const p: Record<string, unknown> = {};
  for (const k of KEYS) if (draft[k] !== loaded[k]) p[k] = draft[k];   // KEYS never has the locked window_start_date
  return p as Partial<GuardedFields>;
}

export default function DataPolicyGuarded() {
  const { t } = useI18n();
  const remote = useAsync(getGuardedPolicy, []);
  const [draft, setDraft] = useState<GuardedFields | null>(null);
  const [preview, setPreview] = useState<GuardedPreview | null>(null);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [filled, setFilled] = useState(false);
  const [serverText, setServerText] = useState<string | null>(null);   // confirm_text given back by DATA_POLICY_CONFIRM_REQUIRED
  const act = useAction();
  const state = remote.data;

  const resetConfirm = () => { setPreview(null); setTyped(""); setReason(""); setAck(false); setServerText(null); };
  // a fresh load (first load, "Tải lại", after an applied change) refills the form with the running values
  useEffect(() => {
    if (state) { setDraft(state.fields); resetConfirm(); }
  }, [state]);
  // the day changed (midnight) between the preview and Apply: the server answers DATA_POLICY_CONFIRM_REQUIRED with the text of
  // today: show it and ask the user to type it again (never re-sent by itself)
  useEffect(() => {
    const e = act.error;
    if (e instanceof ApiError && e.body.code === "DATA_POLICY_CONFIRM_REQUIRED") {
      const c = errParams(e).confirm_text;
      if (c) { setServerText(c); setTyped(""); }
    }
  }, [act.error]);

  if (remote.error) {
    return (
      <Card title={t("gp.title")} actions={<button onClick={() => remote.reload()}><Icon name="refresh" />{t("gp.reload")}</button>}>
        <ErrorBox error={remote.error} />
      </Card>
    );
  }
  if (!state || !draft) return <Card title={t("gp.title")}><Loading /></Card>;

  const loaded = state.fields;
  const patch = diff(loaded, draft);
  const changed = Object.keys(patch).length > 0;
  const formValid = validHours(draft.source_time_travel_hours);
  const edit = (p: Partial<GuardedFields>) => { setDraft({ ...draft, ...p }); resetConfirm(); setFilled(false); act.setOk(null); act.setError(null); };

  const doPreview = async () => {
    setFilled(false);
    const r = await act.run(() => previewGuardedPolicy(patch));
    if (r) { setPreview(r); setTyped(""); setReason(""); setAck(false); setServerText(null); }
  };

  const minReason = state.reason_min_length ?? DEFAULT_MIN_REASON;
  const needsText = !!preview?.needs_confirm_text;
  const needsAck = !!preview && (preview.needs_acknowledged ?? !preview.needs_confirm_text);
  // the text to type: the one of the newest answer (error params > latest preview > GET)
  const confirmText = serverText ?? preview?.confirm_text ?? state.confirm_text;
  const reasonOk = reasonLen(reason) >= minReason;
  // high-risk field: typed text of the day + reason >= reason_min_length; any other field: the "I understand" box
  const busyNow = !!preview?.busy?.busy;   // the server's busy check: a busy system refuses Apply, so the button is locked with the reason
  const canApply = !!preview && !act.busy && !busyNow && (!needsText || (typed.trim() === confirmText && reasonOk)) && (!needsAck || ack);

  const doApply = async () => {
    if (!preview) return;
    // expected = the values loaded with this page, for every field being changed (the server compares type and value:
    // true is not 1, 160.0 is not 160; the values come from the JSON of the GET and are sent back untouched)
    const expected: Record<string, unknown> = {};
    for (const k of Object.keys(patch)) expected[k] = loaded[k as keyof GuardedFields];
    const body: GuardedApplyBody = { patch, expected: expected as Partial<GuardedFields> };
    if (needsText) body.confirm_text = typed.trim();
    if (needsAck) body.acknowledged = ack;
    if (normReason(reason)) body.reason = normReason(reason).slice(0, MAX_REASON);
    const r = await act.run(() => applyGuardedPolicy(body), t("gp.applied"));
    if (r) await remote.reload();
  };
  // a 409 SETTINGS_CHANGED_ELSEWHERE never overwrites: the current values (params.current, params.version of the error body)
  // are shown and the user reloads. DATA_POLICY_CONFIRM_REQUIRED is also a 409 but keeps the form and the preview.
  const err = act.error;
  const code = err instanceof ApiError ? err.body.code : null;
  const is409 = err instanceof ApiError && err.status === 409 && code === "SETTINGS_CHANGED_ELSEWHERE";
  const eparams = errParams(err);
  const current = is409 ? eparams.current ?? null : null;
  const gpErr = err instanceof ApiError && code && GP_CODES.includes(code) ? err : null;

  // undo = the values BEFORE that log row (its previous_values), through the same preview + confirmation
  // (only the fields of changed_fields of that row; the locked window_start_date is never touched)
  const undo = (h: GuardedHistory) => {
    const prev = h.previous_values;
    if (!prev) return;
    const src: string[] = h.changed_fields?.length ? h.changed_fields : KEYS;
    const keys = src.filter((k) => (KEYS as string[]).includes(k)) as (keyof GuardedFields)[];
    const next: Record<string, unknown> = { ...draft };
    for (const k of keys) if (prev[k] !== undefined) next[k] = prev[k];
    setDraft(next as unknown as GuardedFields);
    resetConfirm(); setFilled(true); act.setOk(null); act.setError(null);
  };

  const noteText = (c: string) => (`gp.note.${c}` in DICT ? t(`gp.note.${c}`) : c);
  const polLabel = (p: string) => (p === "FOLLOW_SOURCE" || p === "KEEP_OBSERVED_LINES" ? t(`gp.policy.short.${p}`) : String(p));
  const show = (k: string, v: unknown): string => {
    if (v === null || v === undefined) return "—";
    if (k === "history_change_policy") return polLabel(String(v));
    if (k === "window_start_date") return fmtDate(String(v));
    if (k === "history_day_check") return v ? t("gp.on") : t("gp.off");
    if (k === "training_start_rule") return `cfg.tsr.${v}` in DICT ? t(`cfg.tsr.${v}`) : String(v);
    return String(v);
  };
  const label = (k: string) => ({
    history_change_policy: t("gp.policy"), window_start_date: t("gp.window"), history_day_check: t("gp.day_check"), source_time_travel_hours: t("gp.hours"),
    training_start_rule: t("gp.tsr"),
  } as Record<string, string>)[k] ?? k;
  const warnText = (w: string) => {
    const i = w.indexOf(":");
    const base = i < 0 ? w : w.slice(0, i);
    const arg = i < 0 ? "" : w.slice(i + 1);
    return `gp.warn.${base}` in DICT ? t(`gp.warn.${base}`).replace("{f}", arg.split(",").map((f) => label(f.trim())).join(", ")) : w;
  };
  const trainImpact = (im: GuardedImpact) => {
    if (!im.effective_current || !im.effective_after) return t("gp.train_unknown");
    const days = im.delta_days != null ? Math.abs(im.delta_days) : Math.round(Math.abs(Date.parse(im.effective_after) - Date.parse(im.effective_current)) / 86400000);
    const head = t("gp.train_eff").replace("{a}", fmtDate(im.effective_current)).replace("{b}", fmtDate(im.effective_after));
    if (im.effective_after === im.effective_current) return `${head} ${t("gp.train_same")}`;
    return `${head} ${t(im.effective_after < im.effective_current ? "gp.train_longer" : "gp.train_shorter").replace("{n}", fmtNum(days))}`;
  };
  // every estimate of the preview (impacts); older servers send only `impact`
  const impacts: GuardedImpact[] = preview?.impacts?.length ? preview.impacts : preview?.impact ? [preview.impact] : [];
  const heldImpact = impacts.find((i) => i.kind === "HELD_LINES");
  const trainingImpact = impacts.find((i) => i.kind === "TRAINING_START");
  const busyJobs = names(preview?.busy?.jobs);
  const staleJobs = names(preview?.busy?.stale_ignored);
  const polFull = (p: string) => `${polLabel(p)} (${p})`;
  const policyRunning = (
    <span className="small muted" data-testid="gp-running-history_change_policy">
      {t("gp.policy_running").replace("{d}", polFull(state.defaults?.history_change_policy)).replace("{r}", polFull(loaded.history_change_policy))}
      {loaded.history_change_policy === "FOLLOW_SOURCE" && <> {t("gp.policy_decision")}</>}
    </span>
  );
  const running = (k: keyof GuardedFields) => (
    <span className="small muted" data-testid={`gp-running-${k}`}>
      {t("gp.running")}: <b>{show(k, loaded[k])}</b> · {t("gp.default")}: {show(k, state.defaults?.[k])}
    </span>
  );

  return (
    <Card title={t("gp.title")} className="guarded-policy">
      <p className="small muted">{t("gp.intro")}</p>
      <div className="form-grid">
        <div className="full" data-testid="gp-policy">
          <b>{t("gp.policy")}</b>
          <div className="stack tight">
            {(["FOLLOW_SOURCE", "KEEP_OBSERVED_LINES"] as Policy[]).map((p) => (
              <label key={p} className="row small">
                <input type="radio" name="gp-policy" value={p} data-testid={`gp-policy-${p}`} checked={draft.history_change_policy === p}
                  onChange={() => edit({ history_change_policy: p })} />{t(`gp.policy.${p}`)}
              </label>
            ))}
          </div>
          {policyRunning}
        </div>
        <div className="full" data-testid="gp-window">
          <b>{t("gp.window")}</b>
          <div className="row small"><span className="mono" data-testid="gp-window-value">{fmtDate(loaded.window_start_date)}</span>
            <span className="pill muted">{t("gp.locked")}</span></div>
          <div className="small muted" data-testid="gp-window-locked">{t("gp.window_locked")}</div>
          {running("window_start_date")}
          <details className="hist" data-testid="gp-window-why">
            <summary>{t("gp.why_title")}</summary>
            <ul className="small">
              {["gp.why_1", "gp.why_2", "gp.why_3", "gp.why_4"].map((k) => <li key={k}>{t(k)}</li>)}
            </ul>
          </details>
        </div>
        <div className="full" data-testid="gp-tsr">
          <b>{t("gp.tsr")}</b>
          <div className="stack tight">
            {(["WINDOW_START", "OPEN_HOURS_COVERAGE"] as TrainingRule[]).map((r) => (
              <label key={r} className="row small">
                <input type="radio" name="gp-tsr" value={r} data-testid={`gp-tsr-${r}`} checked={draft.training_start_rule === r}
                  onChange={() => edit({ training_start_rule: r })} />{t(`cfg.tsr.${r}`)}
              </label>
            ))}
          </div>
          <div className="small muted" data-testid="gp-tsr-desc">{t("gp.tsr_desc")}</div>
          {running("training_start_rule")}
        </div>
        <Field label={t("gp.day_check")} help={running("history_day_check")}>
          <label className="row small">
            <input type="checkbox" role="switch" data-testid="gp-day-check" checked={!!draft.history_day_check}
              onChange={(e) => edit({ history_day_check: e.target.checked })} />{draft.history_day_check ? t("gp.on") : t("gp.off")}
          </label>
        </Field>
        <Field label={t("gp.hours")} help={running("source_time_travel_hours")}>
          <input type="number" min={1} max={168} step={1} data-testid="gp-hours" value={draft.source_time_travel_hours ?? ""}
            onChange={(e) => edit({ source_time_travel_hours: e.target.value === "" ? (null as any) : Number(e.target.value) })} />
        </Field>
        {!validHours(draft.source_time_travel_hours) && <div className="full alert error small" data-testid="gp-hours-invalid">{t("gp.hours_invalid")}</div>}
      </div>

      <div className="row wrap">
        <button className="primary" data-testid="gp-preview" onClick={doPreview} disabled={!changed || !formValid || act.busy}>
          <Icon name="search" />{t("gp.preview")}
        </button>
        {!changed && <span className="small muted" data-testid="gp-nochange">{t("gp.no_change")}</span>}
      </div>
      {filled && <div className="alert info small" data-testid="gp-filled">{t("gp.undo_filled")}</div>}

      <ErrorBox error={is409 || gpErr ? null : err} />
      {gpErr && (
        <div className="alert error" role="alert" data-testid="gp-error">
          <b>{t(`gp.err.${gpErr.body.code}`)}</b><code className="code">{gpErr.body.code}</code>
          {gpErr.body.detail && <div className="small" data-testid="gp-error-detail">{gpErr.body.detail}</div>}
        </div>
      )}
      <OkBox text={act.ok} />
      {is409 && (
        <div className="alert warn" role="alert" data-testid="gp-conflict">
          <b>{t("gp.conflict")}</b>
          <code className="code">SETTINGS_CHANGED_ELSEWHERE</code>
          <div className="small">{t("gp.conflict_help")}</div>
          {current && (
            <div className="small" data-testid="gp-conflict-current">{t("gp.current")}{eparams.version != null ? ` (v${eparams.version})` : ""}:
              <ul>{Object.entries(current).map(([k, v]) => <li key={k}>{label(k)}: <b>{show(k, v)}</b></li>)}</ul>
            </div>
          )}
          <div className="row"><button onClick={() => { act.setError(null); remote.reload(); }}><Icon name="refresh" />{t("gp.reload")}</button></div>
        </div>
      )}

      {preview && !is409 && (
        <div className="stack tight" data-testid="gp-confirm-area">
          <b>{t("gp.preview_title")}</b>
          <div className="scroll">
            <table className="tbl small">
              <thead><tr><th>{t("gp.col_field")}</th><th>{t("gp.col_before")}</th><th>{t("gp.col_after")}</th></tr></thead>
              <tbody>
                {(preview.changed?.length ? preview.changed : Object.keys(patch)).map((k) => (
                  <tr key={k} data-testid={`gp-diff-${k}`}><td>{label(k)}</td><td>{show(k, preview.before?.[k as keyof GuardedFields])}</td><td>{show(k, preview.after?.[k as keyof GuardedFields])}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.warnings?.length > 0 && (
            <div className="alert warn small" data-testid="gp-warnings"><b>{t("gp.warnings")}</b>
              <ul>{preview.warnings.map((w, i) => <li key={i}>{warnText(w)}</li>)}</ul>
            </div>
          )}
          {(impacts.length > 0 || !!preview.notes?.length) && (
            <div data-testid="gp-impact">
              <b className="small">{t("gp.impact")}</b>
              <ul className="small">
                {heldImpact && (
                  <li data-testid="gp-impact-held">
                    {t(heldImpact.applies_from === "NEXT_D1" || !heldImpact.applies_from ? "gp.note.APPLIES_AT_NEXT_D1" : "gp.note.APPLIES_LATER")}{" "}
                    {heldImpact.active_held_lines == null
                      ? t("gp.held_unknown")
                      : t("gp.held_n").replace("{n}", fmtNum(heldImpact.active_held_lines)).replace("{plus}", heldImpact.capped ? "+" : "")}
                  </li>
                )}
                {trainingImpact && (
                  <li data-testid="gp-impact-train">{t(trainingImpact.applies_from === "NEXT_DATA_WINDOW_READ" || !trainingImpact.applies_from ? "gp.note.APPLIES_AT_NEXT_DATA_WINDOW_READ" : "gp.note.APPLIES_LATER")} {trainImpact(trainingImpact)}</li>
                )}
                {(preview.notes ?? []).filter((c) => c !== "UNDO_SETTINGS_ONLY" && !(c === "APPLIES_AT_NEXT_D1" && !!heldImpact) && !(c === "APPLIES_AT_NEXT_DATA_WINDOW_READ" && !!trainingImpact)).map((c) => (
                  <li key={c} data-testid={`gp-note-${c}`}>{noteText(c)}</li>
                ))}
              </ul>
            </div>
          )}
          {busyNow && preview?.busy && (
            <div className="alert warn small" data-testid="gp-busy">
              <b>{t("gp.busy_title")}</b>
              <ul>
                {!!preview.busy.window && (
                  <li data-testid="gp-busy-window">{typeof preview.busy.window === "string" ? t("gp.busy_window").replace("{w}", preview.busy.window) : t("gp.busy_window_generic")}</li>
                )}
                {busyJobs.length > 0 && <li data-testid="gp-busy-jobs">{t("gp.busy_jobs").replace("{j}", busyJobs.join(", "))}</li>}
              </ul>
            </div>
          )}
          {staleJobs.length > 0 && (
            <div className="alert info small" data-testid="gp-stale-ignored">{t("gp.stale_ignored").replace("{j}", staleJobs.join(", "))}</div>
          )}
          <div className="small muted" data-testid="gp-undo-note-preview">{t("gp.note.UNDO_SETTINGS_ONLY")}</div>
          <div className={preview.high_risk ? "alert error small" : "alert info small"}>{preview.high_risk ? t("gp.high_risk") : t("gp.low_risk")}</div>
          {needsText && (
            <div className="form-grid">
              <Field label={t("gp.type_confirm")} help={<code className="code" data-testid="gp-confirm-text">{confirmText}</code>}>
                <input type="text" data-testid="gp-confirm-input" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
              </Field>
              <Field label={t("gp.reason_required")} help={t("gp.reason_help").replace("{n}", String(reasonLen(reason))).replace("{m}", String(minReason)).replace("{x}", String(MAX_REASON))}>
                <textarea rows={2} maxLength={MAX_REASON} data-testid="gp-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
            </div>
          )}
          {needsAck && (
            <div className="form-grid">
              <label className="row small full">
                <input type="checkbox" data-testid="gp-ack" checked={ack} onChange={(e) => setAck(e.target.checked)} />{t("gp.ack")}
              </label>
              {!needsText && (
                <Field label={t("gp.reason_optional")}>
                  <textarea rows={2} maxLength={MAX_REASON} data-testid="gp-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              )}
            </div>
          )}
          <div className="row">
            <button className="primary" data-testid="gp-apply" onClick={doApply} disabled={!canApply}><Icon name="save" />{t("gp.apply")}</button>
          </div>
        </div>
      )}

      <b>{t("gp.log")}</b>
      <div className="small muted" data-testid="gp-undo-note-log">{t("gp.note.UNDO_SETTINGS_ONLY")}</div>
      {state.history?.length ? (
        <div className="scroll" data-testid="gp-log">
          <table className="tbl small">
            <thead><tr>
              <th>{t("gp.col_id")}</th><th>{t("gp.col_time")}</th><th>{t("gp.col_note")}</th>
              <th>{t("gp.policy")}</th><th>{t("gp.window")}</th><th>{t("gp.day_check")}</th><th>{t("gp.hours")}</th><th>{t("gp.tsr")}</th><th />
            </tr></thead>
            <tbody>
              {state.history.slice(0, 5).map((h) => (
                <tr key={h.id} data-testid={`gp-log-${h.id}`}>
                  <td>{h.id}</td><td className="nowrap">{fmtTime(h.changed_at)}</td><td>{h.note}</td>
                  <td>{show("history_change_policy", h.values?.history_change_policy)}</td>
                  <td className="nowrap">{show("window_start_date", h.values?.window_start_date)}</td>
                  <td>{show("history_day_check", h.values?.history_day_check)}</td>
                  <td>{show("source_time_travel_hours", h.values?.source_time_travel_hours)}</td>
                  <td>{show("training_start_rule", h.values?.training_start_rule)}</td>
                  <td><button className="small" data-testid={`gp-undo-${h.id}`} onClick={() => undo(h)} disabled={act.busy || !h.previous_values}><Icon name="reset" />{t("gp.undo")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="small muted">{t("gp.log_empty")}</p>}
    </Card>
  );
}
