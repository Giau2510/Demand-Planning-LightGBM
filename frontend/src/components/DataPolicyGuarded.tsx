import { useEffect, useState } from "react";
import { ApiError, get, post, type ApiErrorBody } from "../api";
import { DICT, useI18n } from "../i18n";
import { Card, ErrorBox, Field, Loading, OkBox, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "./ui";
import { Icon } from "./icons";

// 1.4.15 (GD-L1): the four data_policy items that the old "Chính sách dữ liệu" card (Save / Reset to defaults) must never
// overwrite. Compare-and-set per field: preview (nothing written) -> confirmation -> apply; no reset button, no shortcut.

export type Policy = "FOLLOW_SOURCE" | "KEEP_OBSERVED_LINES";
export interface GuardedFields {
  window_start_date: string;
  history_change_policy: Policy;
  history_day_check: boolean;
  source_time_travel_hours: number;
}
/** values = the four fields right AFTER the row, previous_values = right BEFORE it (the first row: the code defaults) */
export interface GuardedHistory { id: number; changed_at: string; note?: string | null; values: GuardedFields; previous_values?: GuardedFields }
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
export interface GuardedImpact { kind?: string; active_held_lines?: number | null; capped?: boolean; applies_from?: string }
export interface GuardedPreview {
  before: Partial<GuardedFields>;
  after: Partial<GuardedFields>;
  changed: string[];
  high_risk: boolean;
  needs_confirm_text: boolean;
  needs_acknowledged?: boolean;
  confirm_text?: string;   // the text of the Vietnam day at the moment of the preview (a preview can be days-boundary away from the GET)
  impact: GuardedImpact | null;
  notes?: string[];        // codes: APPLIES_AT_NEXT_D1, FOLLOW_SOURCE_DROPS_REMOVED_LINES, KEEP_OBSERVED_LINES_HOLDS_REMOVED_LINES, UNDO_SETTINGS_ONLY
  warnings: string[];
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
const KEYS: (keyof GuardedFields)[] = ["history_change_policy", "history_day_check", "source_time_travel_hours"];
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
  const reasonOk = reason.trim().length >= minReason;
  // high-risk field: typed text of the day + reason >= reason_min_length; any other field: the "I understand" box
  const canApply = !!preview && !act.busy && (!needsText || (typed.trim() === confirmText && reasonOk)) && (!needsAck || ack);

  const doApply = async () => {
    if (!preview) return;
    // expected = the values loaded with this page, for every field being changed (the server compares type and value:
    // true is not 1, 160.0 is not 160; the values come from the JSON of the GET and are sent back untouched)
    const expected: Record<string, unknown> = {};
    for (const k of Object.keys(patch)) expected[k] = loaded[k as keyof GuardedFields];
    const body: GuardedApplyBody = { patch, expected: expected as Partial<GuardedFields> };
    if (needsText) body.confirm_text = typed.trim();
    if (needsAck) body.acknowledged = ack;
    if (reason.trim()) body.reason = reason.trim().slice(0, MAX_REASON);
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
  const undo = (h: GuardedHistory) => { if (!h.previous_values) return; setDraft({ ...draft, ...h.previous_values, window_start_date: loaded.window_start_date }); resetConfirm(); setFilled(true); act.setOk(null); act.setError(null); };

  const noteText = (c: string) => (`gp.note.${c}` in DICT ? t(`gp.note.${c}`) : c);
  const polLabel = (p: string) => (p === "FOLLOW_SOURCE" || p === "KEEP_OBSERVED_LINES" ? t(`gp.policy.short.${p}`) : String(p));
  const show = (k: string, v: unknown): string => {
    if (v === null || v === undefined) return "—";
    if (k === "history_change_policy") return polLabel(String(v));
    if (k === "window_start_date") return fmtDate(String(v));
    if (k === "history_day_check") return v ? t("gp.on") : t("gp.off");
    return String(v);
  };
  const label = (k: string) => ({
    history_change_policy: t("gp.policy"), window_start_date: t("gp.window"), history_day_check: t("gp.day_check"), source_time_travel_hours: t("gp.hours"),
  } as Record<string, string>)[k] ?? k;
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
              <ul>{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          {(preview.impact?.kind === "HELD_LINES" || !!preview.notes?.length) && (
            <div data-testid="gp-impact">
              <b className="small">{t("gp.impact")}</b>
              <ul className="small">
                {preview.impact?.kind === "HELD_LINES" && (
                  <li data-testid="gp-impact-held">
                    {t(preview.impact.applies_from === "NEXT_D1" || !preview.impact.applies_from ? "gp.note.APPLIES_AT_NEXT_D1" : "gp.note.APPLIES_LATER")}{" "}
                    {preview.impact.active_held_lines == null
                      ? t("gp.held_unknown")
                      : t("gp.held_n").replace("{n}", fmtNum(preview.impact.active_held_lines)).replace("{plus}", preview.impact.capped ? "+" : "")}
                  </li>
                )}
                {(preview.notes ?? []).filter((c) => c !== "UNDO_SETTINGS_ONLY" && !(c === "APPLIES_AT_NEXT_D1" && preview.impact?.kind === "HELD_LINES")).map((c) => (
                  <li key={c} data-testid={`gp-note-${c}`}>{noteText(c)}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="small muted" data-testid="gp-undo-note-preview">{t("gp.note.UNDO_SETTINGS_ONLY")}</div>
          <div className={preview.high_risk ? "alert error small" : "alert info small"}>{preview.high_risk ? t("gp.high_risk") : t("gp.low_risk")}</div>
          {needsText && (
            <div className="form-grid">
              <Field label={t("gp.type_confirm")} help={<code className="code" data-testid="gp-confirm-text">{confirmText}</code>}>
                <input type="text" data-testid="gp-confirm-input" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
              </Field>
              <Field label={t("gp.reason_required")} help={t("gp.reason_help").replace("{n}", String(reason.trim().length)).replace("{m}", String(minReason)).replace("{x}", String(MAX_REASON))}>
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
              <th>{t("gp.policy")}</th><th>{t("gp.window")}</th><th>{t("gp.day_check")}</th><th>{t("gp.hours")}</th><th />
            </tr></thead>
            <tbody>
              {state.history.slice(0, 5).map((h) => (
                <tr key={h.id} data-testid={`gp-log-${h.id}`}>
                  <td>{h.id}</td><td className="nowrap">{fmtTime(h.changed_at)}</td><td>{h.note}</td>
                  <td>{show("history_change_policy", h.values?.history_change_policy)}</td>
                  <td className="nowrap">{show("window_start_date", h.values?.window_start_date)}</td>
                  <td>{show("history_day_check", h.values?.history_day_check)}</td>
                  <td>{show("source_time_travel_hours", h.values?.source_time_travel_hours)}</td>
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
