import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, ErrorBox, Field, Loading, OkBox, PageHeader, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";
import { normReason, reasonLen, BusyNotice, RiskBadge, errParams, stable, useFmt, useTr, type BusyInfo, type Risk } from "../components/guardedShared";

// 1.4.15 (lot 2): "Cài đặt nâng cao" - every field of the registry (backend/app/settings_registry.py) that has no box of its own,
// by section: label, consequence, current value, code default, risk. Edit several fields -> preview (writes nothing) ->
// the confirmation of the highest risk -> apply (compare-and-set with the values read here) -> recent changes with undo.

interface Constraints { type?: string; ge?: number; gt?: number; le?: number; lt?: number; max_length?: number; min_length?: number; choices?: unknown[] }
interface AdvEntry {
  section: string; key: string; risk: Risk; editable: boolean; label_vi: string; label_en: string; desc_vi: string; desc_en: string;
  only_increase: boolean; path_rule: string | null; reason_code: string | null; own_path: string | null; exportable: boolean;
  constraints: Constraints; value: unknown; default: unknown;
}
interface AdvChange { section: string; key: string; risk: Risk; from: unknown; to: unknown; changed?: boolean }
interface AdvHistory {
  id: number; at: string; action: string; undone: boolean;
  details: { changes?: AdvChange[]; reason?: string | null; risk?: string; undo_of?: number };
}
interface AdvState {
  entries: AdvEntry[]; versions: Record<string, number>; confirm_texts: { HIGH: string; PURCHASE: string };
  reason_min_length: number; max_keys: number; history: AdvHistory[];
}
interface AdvPreview {
  changes: AdvChange[]; changed: string[]; max_risk: Risk | null; needs_confirm_text: boolean; needs_reason: boolean; needs_acknowledged: boolean;
  confirm_text: string | null; warnings: string[]; notes: string[]; busy: BusyInfo | null; versions?: Record<string, number>;
}
interface Pending { mode: "edit" | "undo"; preview: AdvPreview; row?: AdvHistory }
type Draft = { value: unknown; raw?: string; invalid?: boolean };

const SPIKE_KEYS = ["spike_cleaning", "spike_e4_n"];
const MAX_REASON = 500;
const DEFAULT_MIN_REASON = 10;
const k2 = (s: string, k: string) => `${s}.${k}`;

type Kind = "choice" | "bool" | "number" | "json" | "text";
function kindOf(e: AdvEntry): Kind {
  const c = e.constraints ?? {};
  if (c.choices?.length) return "choice";
  const t = c.type ?? "";
  if (/\b(list|dict|tuple|set)\b/.test(t)) return "json";
  if (/bool/.test(t)) return "bool";
  if (/\bint\b|\bfloat\b/.test(t)) return "number";
  if (/\bstr\b/.test(t)) return "text";
  if (typeof e.value === "boolean") return "bool";
  if (typeof e.value === "number") return "number";
  if (e.value && typeof e.value === "object") return "json";
  return "text";
}
const nullable = (e: AdvEntry) => /None|Optional/.test(e.constraints?.type ?? "") || e.value === null || e.default === null;
const isInt = (e: AdvEntry) => /\bint\b/.test(e.constraints?.type ?? "") && !/\bfloat\b/.test(e.constraints?.type ?? "");

/** client-side check of a draft (the server checks again and is the authority): the code of the problem, or null */
function problem(e: AdvEntry, d: Draft | undefined): string | null {
  if (!d) return null;
  if (d.invalid) return kindOf(e) === "json" ? "adv.bad_json" : "adv.bad_empty";
  const v = d.value;
  if (kindOf(e) === "number" && typeof v === "number") {
    const c = e.constraints;
    if (isInt(e) && !Number.isInteger(v)) return "adv.bad_number";
    if ((c.ge != null && v < c.ge) || (c.gt != null && v <= c.gt) || (c.le != null && v > c.le) || (c.lt != null && v >= c.lt)) return "adv.bad_range";
    if (e.only_increase && typeof e.value === "number" && v < e.value) return "adv.bad_decrease";
  }
  return null;
}

function ownLink(own: string | null): string | null {
  if (!own) return null;
  if (/Schedules\.tsx|\/api\/schedules/.test(own)) return "/schedules";
  if (/BigQuery\.tsx|bigquery/.test(own)) return "/bigquery";
  if (/Mapping\.tsx/.test(own)) return "/mapping";
  if (/feature-table|Features/.test(own)) return "/features";
  return null;
}

function Control({ e, d, set }: { e: AdvEntry; d: Draft | undefined; set: (x: Draft | null) => void }) {
  const { t } = useI18n();
  const id = `adv-in-${k2(e.section, e.key)}`;
  const kind = kindOf(e);
  const eff = d ? d.value : e.value;
  const same = (v: unknown) => set(stable(v) === stable(e.value) ? null : { value: v });
  const bad = problem(e, d);
  let box: JSX.Element;
  if (kind === "choice") {
    const ch = e.constraints.choices ?? [];
    const idx = ch.findIndex((c) => stable(c) === stable(eff));
    box = (
      <select data-testid={id} value={idx < 0 ? "" : String(idx)} onChange={(ev) => same(ev.target.value === "" ? null : ch[Number(ev.target.value)])}>
        {(nullable(e) || idx < 0) && <option value="">—</option>}
        {ch.map((c, i) => <option key={i} value={String(i)}>{String(c)}</option>)}
      </select>
    );
  } else if (kind === "bool" && nullable(e)) {
    box = (
      <select data-testid={id} value={eff === null || eff === undefined ? "" : String(eff)} onChange={(ev) => same(ev.target.value === "" ? null : ev.target.value === "true")}>
        <option value="">{t("adv.unset")}</option>
        <option value="true">{t("gp.on")}</option>
        <option value="false">{t("gp.off")}</option>
      </select>
    );
  } else if (kind === "bool") {
    box = (
      <label className="row small">
        <input type="checkbox" role="switch" data-testid={id} checked={!!eff} onChange={(ev) => same(ev.target.checked)} />{eff ? t("gp.on") : t("gp.off")}
      </label>
    );
  } else if (kind === "number") {
    const c = e.constraints;
    const min = c.ge ?? c.gt;
    box = (
      <input type="number" data-testid={id} min={e.only_increase && typeof e.value === "number" ? e.value : min} max={c.le ?? c.lt} step={isInt(e) ? 1 : "any"}
        value={eff === null || eff === undefined ? "" : String(eff)}
        onChange={(ev) => {
          if (ev.target.value === "") { nullable(e) ? same(null) : set({ value: null, invalid: true }); return; }
          same(Number(ev.target.value));
        }} />
    );
  } else if (kind === "json") {
    box = (
      <textarea rows={3} data-testid={id} className="mono" value={d?.raw ?? JSON.stringify(e.value ?? null)}
        onChange={(ev) => {
          try { const v = JSON.parse(ev.target.value); set(stable(v) === stable(e.value) ? null : { value: v, raw: ev.target.value }); }
          catch { set({ value: e.value, raw: ev.target.value, invalid: true }); }
        }} />
    );
  } else {
    box = (
      <input type="text" data-testid={id} maxLength={e.constraints.max_length} value={eff === null || eff === undefined ? "" : String(eff)}
        onChange={(ev) => same(ev.target.value === "" && nullable(e) ? null : ev.target.value)} />
    );
  }
  return (
    <div className="stack tight">
      {box}
      {bad && <span className="small bad-t" data-testid={`adv-bad-${k2(e.section, e.key)}`}>{t(bad)}</span>}
    </div>
  );
}

export default function AdvancedSettings() {
  const { t, lang } = useI18n();
  const tr = useTr();
  const fmt = useFmt();
  const remote = useAsync(() => get<AdvState>("/api/settings-advanced"), []);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [pending, setPending] = useState<Pending | null>(null);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [serverText, setServerText] = useState<string | null>(null);   // confirm_text given back by SETTINGS_ADVANCED_CONFIRM_REQUIRED
  const act = useAction();
  const state = remote.data;

  const clearConfirm = () => { setPending(null); setTyped(""); setReason(""); setAck(false); setServerText(null); };
  useEffect(() => {
    if (state) { setDrafts({}); clearConfirm(); }
  }, [state]);
  // the day changed between the preview and Apply: the server gives back the text of today; the user types it again
  useEffect(() => {
    const e = act.error;
    if (e instanceof ApiError && e.body.code === "SETTINGS_ADVANCED_CONFIRM_REQUIRED") {
      const c = errParams(e).confirm_text;
      if (typeof c === "string" && c) { setServerText(c); setTyped(""); }
    }
  }, [act.error]);

  if (remote.error) {
    return (
      <div className="stack">
        <PageHeader icon="config" title={t("nav.advanced")} desc={t("page.advanced.desc")} />
        <Card title={t("nav.advanced")} actions={<button onClick={() => remote.reload()}><Icon name="refresh" />{t("gp.reload")}</button>}><ErrorBox error={remote.error} /></Card>
      </div>
    );
  }
  if (!state) return <div className="stack"><PageHeader icon="config" title={t("nav.advanced")} desc={t("page.advanced.desc")} /><Card title={t("nav.advanced")}><Loading /></Card></div>;

  const byKey = new Map(state.entries.map((e) => [k2(e.section, e.key), e]));
  const label = (s: string, k: string) => { const e = byKey.get(k2(s, k)); return e ? (lang === "vi" ? e.label_vi : e.label_en) : k2(s, k); };
  const sections = Array.from(new Set(state.entries.map((e) => e.section)));
  const changedKeys = Object.keys(drafts).filter((k) => {
    const e = byKey.get(k);
    return e && (drafts[k].invalid || stable(drafts[k].value) !== stable(e.value));   // an invalid draft counts: it blocks the preview
  });
  const anyBad = changedKeys.some((k) => problem(byKey.get(k)!, drafts[k]));
  const tooMany = changedKeys.length > state.max_keys;
  const minReason = state.reason_min_length ?? DEFAULT_MIN_REASON;
  const setDraft = (e: AdvEntry, x: Draft | null) => {
    const next = { ...drafts };
    if (x) next[k2(e.section, e.key)] = x; else delete next[k2(e.section, e.key)];
    setDrafts(next); clearConfirm(); act.setOk(null); act.setError(null);
  };

  const doPreview = async () => {
    const changes = changedKeys.map((k) => { const e = byKey.get(k)!; return { section: e.section, key: e.key, value: drafts[k].value }; });
    const r = await act.run(() => post<AdvPreview>("/api/settings-advanced/preview", { changes }));
    if (r) { clearConfirm(); setPending({ mode: "edit", preview: r }); }
  };
  // undo = the same preview of the values BEFORE that apply, then the same confirmation; the server undoes by audit id
  const startUndo = async (row: AdvHistory) => {
    const changes = (row.details.changes ?? []).map((c) => ({ section: c.section, key: c.key, value: c.from }));
    const r = await act.run(() => post<AdvPreview>("/api/settings-advanced/preview", { changes }));
    if (r) { clearConfirm(); setPending({ mode: "undo", preview: r, row }); }
  };

  const pv = pending?.preview ?? null;
  const needsText = !!pv?.needs_confirm_text;
  const needsAck = !!pv?.needs_acknowledged;
  const confirmText = serverText ?? pv?.confirm_text ?? "";
  const reasonOk = reasonLen(reason) >= minReason;
  const busyNow = !!pv?.busy?.busy;
  const nothing = !!pv && pv.changed.length === 0;
  const canApply = !!pv && !act.busy && !busyNow && !nothing && (!needsText || (typed.trim() === confirmText && reasonOk)) && (!needsAck || ack);

  const doApply = async () => {
    if (!pending) return;
    const common: Record<string, unknown> = {};
    if (needsText) common.confirm_text = typed.trim();
    if (needsAck) common.acknowledged = ack;
    if (normReason(reason)) common.reason = normReason(reason).slice(0, MAX_REASON);
    let r: unknown;
    if (pending.mode === "undo" && pending.row) {
      r = await act.run(() => post("/api/settings-advanced/undo", { audit_id: pending.row!.id, ...common }), t("adv.undone"));
    } else {
      const changes = changedKeys.map((k) => { const e = byKey.get(k)!; return { section: e.section, key: e.key, value: drafts[k].value }; });
      const expected: Record<string, Record<string, unknown>> = {};   // the values read with this page, for every key that changes
      for (const k of changedKeys) { const e = byKey.get(k)!; (expected[e.section] ??= {})[e.key] = e.value; }
      r = await act.run(() => post("/api/settings-advanced/apply", { changes, expected, ...common }), t("adv.applied"));
    }
    if (r) await remote.reload();
  };

  const err = act.error;
  const code = err instanceof ApiError ? err.body.code : null;
  const conflict = err instanceof ApiError && err.status === 409 && code === "SETTINGS_CHANGED_ELSEWHERE";
  const busyErr = code === "SETTINGS_ADVANCED_BUSY";
  const eparams = errParams(err);
  const conflictKeys = conflict && err instanceof ApiError && err.body.detail ? err.body.detail.split(",").map((x) => x.trim()).filter(Boolean) : [];
  const currentBySection = (conflict && eparams.current && typeof eparams.current === "object" ? eparams.current : {}) as Record<string, Record<string, unknown>>;
  const spikeChanged = (pv?.changed ?? []).some((c) => SPIKE_KEYS.includes(c.split(".")[1] ?? ""));

  return (
    <div className="stack">
      <PageHeader icon="config" title={t("nav.advanced")} desc={t("page.advanced.desc")} />
      <div className="alert info small" data-testid="adv-intro">
        {t("adv.intro")}
        <div data-testid="adv-window-note">{t("adv.window_note")} <Link to="/config">{t("nav.config")} →</Link></div>
      </div>
      <ErrorBox error={conflict || busyErr ? null : err} />
      <OkBox text={act.ok} />
      {busyErr && (
        <>
          <ErrorBox error={err} />
          <BusyNotice busy={{ busy: true, window: eparams.window, jobs: eparams.jobs, stale_ignored: eparams.stale_ignored }} />
        </>
      )}
      {conflict && (
        <div className="alert warn" role="alert" data-testid="adv-conflict">
          <b>{t("adv.conflict_title")}</b><code className="code">SETTINGS_CHANGED_ELSEWHERE</code>
          <div className="small">{t("adv.conflict_help")}</div>
          <ul className="small" data-testid="adv-conflict-keys">
            {conflictKeys.map((ck) => {
              const [s, k] = [ck.split(".")[0], ck.split(".").slice(1).join(".")];
              const cur = currentBySection[s]?.[k];
              return <li key={ck}>{label(s, k)}{cur !== undefined || (currentBySection[s] && k in currentBySection[s]) ? <>: {t("adv.current_now")} <b>{fmt(cur)}</b></> : null}</li>;
            })}
          </ul>
          <div className="row"><button onClick={() => { act.setError(null); remote.reload(); }}><Icon name="refresh" />{t("gp.reload")}</button></div>
        </div>
      )}

      {sections.map((s) => (
        <Card key={s} title={tr("adv.section", s)}>
          {s === "sel2_pipeline" && (
            <div className="alert warn" data-testid="adv-spike-box"><b>{t("adv.spike_box")}</b></div>
          )}
          <div className="scroll">
            <table className="tbl small">
              <thead><tr><th>{t("adv.col_field")}</th><th>{t("adv.col_current")}</th><th>{t("adv.col_default")}</th><th>{t("adv.col_edit")}</th></tr></thead>
              <tbody>
                {state.entries.filter((e) => e.section === s).map((e) => {
                  const kk = k2(e.section, e.key);
                  const link = ownLink(e.own_path);
                  return (
                    <tr key={kk} data-testid={`adv-row-${kk}`}>
                      <td>
                        <b>{lang === "vi" ? e.label_vi : e.label_en}</b> <RiskBadge risk={e.risk} />
                        <div className="mono small muted">{kk}</div>
                        <div className="small">{lang === "vi" ? e.desc_vi : e.desc_en}</div>
                        {e.only_increase && <div className="small bad-t" data-testid={`adv-incr-${kk}`}>{t("adv.only_increase")}</div>}
                        {!e.editable && (
                          <div className="small" data-testid={`adv-why-${kk}`}>
                            <b>{t("adv.why_readonly")}:</b> {e.reason_code ? tr("adv.reason", e.reason_code) : t("adv.readonly")}
                            {e.own_path && <> · {t("adv.own_path")}: {link ? <Link to={link}>{e.own_path}</Link> : <span className="mono">{e.own_path}</span>}</>}
                          </div>
                        )}
                        {e.editable && e.own_path && <div className="small muted">{t("adv.own_path")}: <span className="mono">{e.own_path}</span></div>}
                      </td>
                      <td className="mono" data-testid={`adv-cur-${kk}`}>{fmt(e.value)}</td>
                      <td className="mono">{fmt(e.default)}</td>
                      <td>{e.editable ? <Control e={e} d={drafts[kk]} set={(x) => setDraft(e, x)} /> : <span className="small muted">{t("adv.readonly")}</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ))}

      <Card title={t("adv.review_title")}>
        <div className="row wrap">
          <button className="primary" data-testid="adv-preview" onClick={doPreview} disabled={!changedKeys.length || anyBad || tooMany || act.busy}>
            <Icon name="search" />{t("adv.preview")}
          </button>
          <span className="small muted" data-testid="adv-count">{changedKeys.length ? t("adv.n_changed").replace("{n}", String(changedKeys.length)).replace("{m}", String(state.max_keys)) : t("gp.no_change")}</span>
          {tooMany && <span className="small bad-t" data-testid="adv-too-many">{t("adv.too_many").replace("{m}", String(state.max_keys))}</span>}
        </div>

        {pv && !conflict && (
          <div className="stack tight" data-testid="adv-confirm-area">
            <b>{pending?.mode === "undo" ? t("adv.undo_title").replace("{id}", String(pending.row?.id)) : t("gp.preview_title")}</b>
            <div className="scroll">
              <table className="tbl small">
                <thead><tr><th>{t("gp.col_field")}</th><th>{t("adv.risk_col")}</th><th>{t("gp.col_before")}</th><th>{t("gp.col_after")}</th></tr></thead>
                <tbody>
                  {pv.changes.map((c) => (
                    <tr key={k2(c.section, c.key)} data-testid={`adv-diff-${k2(c.section, c.key)}`} className={c.changed === false ? "muted" : ""}>
                      <td>{label(c.section, c.key)}{c.changed === false && <> ({t("adv.unchanged")})</>}</td>
                      <td><RiskBadge risk={c.risk} /></td><td className="mono">{fmt(c.from)}</td><td className="mono"><b>{fmt(c.to)}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="small" data-testid="adv-max-risk">{t("adv.max_risk")}: <RiskBadge risk={pv.max_risk} /></div>
            {(spikeChanged || pv.warnings.includes("SPIKE_OWNER_DECISION")) && (
              <div className="alert warn" data-testid="adv-spike-warning"><b>{t("adv.spike_box")}</b></div>
            )}
            <BusyNotice busy={pv.busy} />
            {(pv.warnings.filter((w) => w !== "SPIKE_OWNER_DECISION").length > 0 || pv.notes.length > 0) && (
              <div className="alert info small" data-testid="adv-notes">
                <ul>
                  {pv.warnings.filter((w) => w !== "SPIKE_OWNER_DECISION").map((w) => <li key={w} data-testid={`adv-warn-${w}`}>{tr("adv.warn", w)}</li>)}
                  {pv.notes.map((n) => <li key={n} data-testid={`adv-note-${n}`}>{tr("adv.note", n)}</li>)}
                </ul>
              </div>
            )}
            {needsText && (
              <div className="form-grid">
                <Field label={t("gp.type_confirm")} help={<code className="code" data-testid="adv-confirm-text">{confirmText}</code>}>
                  <input type="text" data-testid="adv-confirm-input" value={typed} autoComplete="off" onChange={(ev) => setTyped(ev.target.value)} />
                </Field>
                <Field label={t("gp.reason_required")} help={t("gp.reason_help").replace("{n}", String(reasonLen(reason))).replace("{m}", String(minReason)).replace("{x}", String(MAX_REASON))}>
                  <textarea rows={2} maxLength={MAX_REASON} data-testid="adv-reason" value={reason} onChange={(ev) => setReason(ev.target.value)} />
                </Field>
              </div>
            )}
            {needsAck && (
              <div className="form-grid">
                <label className="row small full">
                  <input type="checkbox" data-testid="adv-ack" checked={ack} onChange={(ev) => setAck(ev.target.checked)} />{t("gp.ack")}
                </label>
                {!needsText && (
                  <Field label={t("gp.reason_optional")}>
                    <textarea rows={2} maxLength={MAX_REASON} data-testid="adv-reason" value={reason} onChange={(ev) => setReason(ev.target.value)} />
                  </Field>
                )}
              </div>
            )}
            <div className="row">
              <button className="primary" data-testid="adv-apply" onClick={doApply} disabled={!canApply}>
                <Icon name="save" />{pending?.mode === "undo" ? t("adv.undo") : t("gp.apply")}
              </button>
              <button data-testid="adv-cancel" onClick={() => { clearConfirm(); act.setError(null); }}>{t("common.cancel")}</button>
            </div>
          </div>
        )}
      </Card>

      <Card title={t("adv.recent")}>
        <div className="small muted">{t("gp.note.UNDO_SETTINGS_ONLY")}</div>
        {state.history.length === 0 ? <p className="small muted">{t("adv.recent_empty")}</p> : (
          <div className="scroll" data-testid="adv-history">
            <table className="tbl small">
              <thead><tr><th>{t("gp.col_id")}</th><th>{t("gp.col_time")}</th><th>{t("adv.col_action")}</th><th>{t("adv.col_changes")}</th><th>{t("adv.col_reason")}</th><th /></tr></thead>
              <tbody>
                {state.history.map((h) => (
                  <tr key={h.id} data-testid={`adv-log-${h.id}`}>
                    <td>{h.id}</td><td className="nowrap">{fmtTime(h.at)}</td><td>{tr("adv.action", h.action)}{h.details.undo_of != null && <> (#{h.details.undo_of})</>}</td>
                    <td>
                      <ul>{(h.details.changes ?? []).map((c) => (
                        <li key={k2(c.section, c.key)}>{label(c.section, c.key)}: {fmt(c.from)} → <b>{fmt(c.to)}</b> <RiskBadge risk={c.risk} /></li>
                      ))}</ul>
                    </td>
                    <td>{h.details.reason}</td>
                    <td>
                      {h.action === "SETTINGS_ADVANCED_APPLIED" && (h.undone
                        ? <span className="pill muted">{t("adv.undone_flag")}</span>
                        : <button className="small" data-testid={`adv-undo-${h.id}`} onClick={() => startUndo(h)} disabled={act.busy}><Icon name="reset" />{t("adv.undo")}</button>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
