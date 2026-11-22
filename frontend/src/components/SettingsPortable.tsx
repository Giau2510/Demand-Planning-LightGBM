import { useEffect, useState } from "react";
import { ApiError, get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, ErrorBox, Field, Loading, OkBox, fmtTime, useAction, useAsync } from "./ui";
import { Icon } from "./icons";
import { normReason, reasonLen, BusyNotice, RiskBadge, errParams, useFmt, useTr, type Risk } from "./guardedShared";

// 1.4.15 (lot 2B): card "Cài đặt: xuất / nhập" of the page "Hệ thống & sao lưu". Export = a plain download of
// GET /api/settings-export. Import = choose a file -> preview (writes nothing; the file is sent as `document`, at most 2 MB)
// -> choose sections (a section with a HIGH / PURCHASE key is NOT selected by default) -> typed text + reason -> apply;
// history of the imports with "undo of an import".

interface PRow { key: string; current: unknown; file: unknown; risk: string; changed: boolean }
interface PSection {
  section: string; rows: PRow[]; changed: string[]; max_risk: Risk | null; purchase_keys: string[]; high_keys: string[]; errors: string[];
  selectable: boolean; default_selected: boolean; expected: string;
}
interface PPreview {
  sections: PSection[]; sha256: string; file?: { app_version?: string; schema_version?: number; exported_at?: string; format_version?: number };
  current?: { app_version?: string; schema_version?: number }; warnings: string[]; notes: string[]; confirm_text: string; reason_min_length?: number;
  needs_purchase_confirm?: boolean; purchase_keys?: string[]; confirm_purchase?: string; needs_high_confirm?: boolean; high_keys?: string[]; confirm_high?: string;
  spike_current?: Record<string, unknown>;
}
interface PSkipped { section: string; key: string; reason: string; value: unknown }
interface PHist {
  id: number; at: string; action: string; entity_id: string; undone: boolean;
  details: { import_id?: string; reason?: string | null; entries?: { section: string; keys: Record<string, { from: unknown; to: unknown }> }[]; skipped?: PSkipped[] };
}

const MAX_FILE = 2 * 1024 * 1024;
const MAX_REASON = 500;
const DEFAULT_MIN_REASON = 10;

/** the file text: Blob.text() where it exists, FileReader otherwise (as the Google sign-in box does) */
async function readText(f: File): Promise<string> {
  if (typeof (f as unknown as { text?: unknown }).text === "function") return f.text();
  return new Promise<string>((res, rej) => {
    const rd = new FileReader();
    rd.onload = () => res(String(rd.result ?? ""));
    rd.onerror = () => rej(rd.error);
    rd.readAsText(f);
  });
}

// risk of a key for the undo of an import (as settings_portable._risk): the registry gives its own keys; the other sections by rule
const VISIBLE_RISK: Record<string, string> = { model: "PURCHASE", horizons: "PURCHASE", schedule: "HIGH", bigquery: "HIGH", quality: "HIGH", import: "HIGH" };
function guessRisk(section: string, key: string, reg: Record<string, string>): string {
  if (reg[`${section}.${key}`]) return reg[`${section}.${key}`];
  if (section === "data_policy") return ["history_change_policy", "training_start_rule"].includes(key) ? "PURCHASE" : key === "window_start_date" ? "HIGH" : "LOW";
  return VISIBLE_RISK[section] ?? "LOW";
}

/** today in Vietnam (yyyy-mm-dd): only the first guess of the text to type in the undo box; the server's text replaces it */
function vnToday(): string {
  try { return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" }); } catch { return new Date().toISOString().slice(0, 10); }
}

export default function SettingsPortable() {
  const { t } = useI18n();
  const tr = useTr();
  const fmt = useFmt();
  const history = useAsync(() => get<PHist[]>("/api/settings-import/history"), []);
  const actImp = useAction();
  const actUndo = useAction();
  const [fileName, setFileName] = useState("");
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PPreview | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [typed, setTyped] = useState("");
  const [typedPurchase, setTypedPurchase] = useState("");
  const [typedHigh, setTypedHigh] = useState("");
  const [reason, setReason] = useState("");
  const [serverText, setServerText] = useState<{ main?: string; purchase?: string; high?: string }>({});
  const [result, setResult] = useState<{ import_id: string; entries: PHist["details"]["entries"] } | null>(null);
  // undo of an import
  const [undoRow, setUndoRow] = useState<PHist | null>(null);
  const [uTyped, setUTyped] = useState("");
  const [uPurchase, setUPurchase] = useState("");
  const [uHigh, setUHigh] = useState("");
  const [uReason, setUReason] = useState("");
  const [uTexts, setUTexts] = useState<{ main?: string; purchase?: string; high?: string }>({});
  const [uReg, setUReg] = useState<Record<string, string>>({});
  const [uResult, setUResult] = useState<{ skipped: PSkipped[] } | null>(null);

  const resetImport = () => {
    setPreview(null); setSelected({}); setTyped(""); setTypedPurchase(""); setTypedHigh(""); setReason(""); setServerText({});
  };
  // a confirm-required answer carries the text of today: show it and ask for it again (never re-sent by itself)
  useEffect(() => {
    const e = actImp.error;
    if (!(e instanceof ApiError)) return;
    const p = errParams(e);
    if (e.body.code === "SETTINGS_IMPORT_CONFIRM_REQUIRED" && typeof p.confirm_text === "string") { setServerText((s) => ({ ...s, main: p.confirm_text as string })); setTyped(""); }
    if (e.body.code === "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED" && typeof p.confirm_purchase === "string") { setServerText((s) => ({ ...s, purchase: p.confirm_purchase as string })); setTypedPurchase(""); }
    if (e.body.code === "SETTINGS_IMPORT_HIGH_CONFIRM_REQUIRED" && typeof p.confirm_high === "string") { setServerText((s) => ({ ...s, high: p.confirm_high as string })); setTypedHigh(""); }
  }, [actImp.error]);
  useEffect(() => {
    const e = actUndo.error;
    if (!(e instanceof ApiError)) return;
    const p = errParams(e);
    if (e.body.code === "SETTINGS_IMPORT_CONFIRM_REQUIRED" && typeof p.confirm_text === "string") { setUTexts((s) => ({ ...s, main: p.confirm_text as string })); setUTyped(""); }
    if (e.body.code === "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED" && typeof p.confirm_purchase === "string") { setUTexts((s) => ({ ...s, purchase: p.confirm_purchase as string })); setUPurchase(""); }
    if (e.body.code === "SETTINGS_IMPORT_HIGH_CONFIRM_REQUIRED" && typeof p.confirm_high === "string") { setUTexts((s) => ({ ...s, high: p.confirm_high as string })); setUHigh(""); }
  }, [actUndo.error]);

  const runPreview = async (document: Record<string, unknown>) => {
    const r = await actImp.run(() => post<PPreview>("/api/settings-import/preview", { document }));
    if (r) {
      resetImport();
      setPreview(r);
      setSelected(Object.fromEntries(r.sections.map((s) => [s.section, s.default_selected])));
    }
  };
  const onFile = async (f: File | undefined) => {
    setResult(null); setLocalError(null); actImp.setError(null); actImp.setOk(null); resetImport(); setDoc(null);
    if (!f) return;
    setFileName(f.name);
    if (f.size > MAX_FILE) { setLocalError("sp.too_large"); return; }
    let parsed: unknown;
    try { parsed = JSON.parse(await readText(f)); } catch { setLocalError("sp.invalid_json"); return; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { setLocalError("sp.invalid_json"); return; }
    setDoc(parsed as Record<string, unknown>);
    await runPreview(parsed as Record<string, unknown>);
  };

  const chosen = (preview?.sections ?? []).filter((s) => selected[s.section]);
  const needsPurchase = chosen.some((s) => s.purchase_keys.length > 0);
  const needsHigh = chosen.some((s) => s.high_keys.length > 0);
  const anyChange = chosen.some((s) => s.changed.length > 0);
  const minReason = preview?.reason_min_length ?? DEFAULT_MIN_REASON;
  const textMain = serverText.main ?? preview?.confirm_text ?? "";
  const textPurchase = serverText.purchase ?? preview?.confirm_purchase ?? "";
  const textHigh = serverText.high ?? preview?.confirm_high ?? "";
  const canApply = !!preview && !!doc && !actImp.busy && chosen.length > 0 && anyChange && typed.trim() === textMain && reasonLen(reason) >= minReason
    && (!needsPurchase || typedPurchase.trim() === textPurchase) && (!needsHigh || typedHigh.trim() === textHigh);

  const doApply = async () => {
    if (!preview || !doc) return;
    const body: Record<string, unknown> = {
      document: doc, sections: chosen.map((s) => s.section), expected: Object.fromEntries(chosen.map((s) => [s.section, s.expected])),
      confirm_text: typed.trim(), reason: normReason(reason).slice(0, MAX_REASON),
    };
    if (needsPurchase) body.confirm_purchase = typedPurchase.trim();
    if (needsHigh) body.confirm_high = typedHigh.trim();
    const r = await actImp.run(() => post<{ import_id: string; entries: PHist["details"]["entries"] }>("/api/settings-import/apply", body));
    if (r) {
      setResult({ import_id: r.import_id, entries: r.entries });
      actImp.setOk(t("sp.imported").replace("{id}", r.import_id));
      resetImport(); setDoc(null); setFileName("");
      history.reload();
    }
  };

  const startUndo = (h: PHist) => {
    setUndoRow(h); setUTyped(""); setUPurchase(""); setUHigh(""); setUReason(""); setUTexts({}); setUReg({}); setUResult(null); actUndo.setError(null); actUndo.setOk(null);
    // the registry risk of the keys, to know which texts the undo needs before the first click (a failed read: the rule by section is used)
    get<{ entries?: { section: string; key: string; risk: string }[] }>("/api/settings-advanced")
      .then((r) => setUReg(Object.fromEntries((r.entries ?? []).map((e) => [`${e.section}.${e.key}`, e.risk]))))
      .catch(() => undefined);
  };
  const uMain = uTexts.main ?? preview?.confirm_text ?? `NHAP-CAI-DAT-${vnToday()}`;
  const uKeys = (undoRow?.details.entries ?? []).flatMap((en) => Object.keys(en.keys).map((k) => `${en.section}.${k}`));
  const uRisk = (full: string) => guessRisk(full.split(".")[0], full.split(".").slice(1).join("."), uReg);
  const uShowHigh = uKeys.some((k) => uRisk(k) === "HIGH") || uTexts.high !== undefined;
  const uShowPurchase = uKeys.some((k) => uRisk(k) === "PURCHASE") || uTexts.purchase !== undefined;
  const uHighText = uTexts.high ?? `DOI-CAI-DAT-AN-${vnToday()}`;                              // a first guess; the server's text replaces it
  const uPurchaseText = uTexts.purchase ?? `DOI-CAI-DAT-ANH-HUONG-MUA-HANG-${vnToday()}`;
  const uCanApply = !!undoRow && !actUndo.busy && uTyped.trim() === uMain && reasonLen(uReason) >= DEFAULT_MIN_REASON
    && (!uShowPurchase || uPurchase.trim() === uPurchaseText) && (!uShowHigh || uHigh.trim() === uHighText);
  const doUndo = async () => {
    if (!undoRow) return;
    const body: Record<string, unknown> = { import_id: undoRow.entity_id, confirm_text: uTyped.trim(), reason: normReason(uReason).slice(0, MAX_REASON) };
    if (uShowPurchase) body.confirm_purchase = uPurchase.trim();
    if (uShowHigh) body.confirm_high = uHigh.trim();
    const r = await actUndo.run(() => post<{ import_id: string; skipped: PSkipped[] }>("/api/settings-import/undo", body), t("sp.undone"));
    if (r) { setUResult({ skipped: r.skipped ?? [] }); setUndoRow(null); history.reload(); }
  };

  // errors of the two actions: SETTINGS_ADVANCED_BUSY shows why (night window, running jobs); SETTINGS_CHANGED_ELSEWHERE gets its own panel
  const errView = (err: unknown, refresh?: () => void) => {
    if (!err) return null;
    const code = err instanceof ApiError ? err.body.code : null;
    const p = errParams(err);
    const keys = Array.isArray(p.keys) ? (p.keys as unknown[]).map(String) : [];
    return (
      <>
        {err instanceof ApiError && err.status === 413 ? <div className="alert bad" role="alert" data-testid="sp-too-large">{t("sp.too_large")}</div> : <ErrorBox error={err} />}
        {keys.length > 0 && <div className="alert bad small" data-testid="sp-refused-keys"><b>{t("sp.refused_keys")}</b> <span className="mono">{keys.join(", ")}</span></div>}
        {code === "SETTINGS_ADVANCED_BUSY" && <BusyNotice busy={{ busy: true, window: p.window, jobs: p.jobs, stale_ignored: p.stale_ignored }} />}
        {code === "SETTINGS_CHANGED_ELSEWHERE" && (
          <div className="alert warn" data-testid="sp-conflict">
            <b>{t("sp.conflict")}</b> <span className="mono">{err instanceof ApiError ? err.body.detail : ""}</span>
            {refresh && <div className="row"><button onClick={refresh}><Icon name="refresh" />{t("sp.preview_again")}</button></div>}
          </div>
        )}
      </>
    );
  };

  const errText = (e: string) => {
    const i = e.indexOf(":");
    const code = i < 0 ? e : e.slice(0, i);
    return /^[A-Z_]+$/.test(code) ? `${tr("sp.err", code)}${i < 0 ? "" : `:${e.slice(i + 1)}`}` : e;
  };

  return (
    <Card icon="file" title={t("sp.title")}>
      <div className="stack">
        <div>
          <div className="row wrap">
            <a className="btn primary" href="/api/settings-export" download data-testid="sp-export"><Icon name="download" />{t("sp.export")}</a>
          </div>
          <p className="small muted" data-testid="sp-export-note">{t("sp.export_note")}</p>
          <p className="small muted" data-testid="sp-excluded">{t("sp.excluded")}</p>
        </div>

        <div>
          <b>{t("sp.import")}</b>
          <Field label={t("sp.choose_file")}>
            <input type="file" accept=".json,application/json" data-testid="sp-file" disabled={actImp.busy} onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
          </Field>
          {fileName && <div className="small muted" data-testid="sp-file-name">{fileName}</div>}
          {localError && <div className="alert bad" role="alert" data-testid="sp-local-error">{t(localError)}</div>}
          {errView(actImp.error, doc ? () => { actImp.setError(null); void runPreview(doc); } : undefined)}
          <OkBox text={actImp.ok} />
          {result && (
            <ul className="small" data-testid="sp-result">
              {(result.entries ?? []).map((en) => <li key={en.section}>{tr("adv.section", en.section)}: {Object.keys(en.keys).length}</li>)}
            </ul>
          )}

          {preview && (
            <div className="stack tight" data-testid="sp-preview">
              <b>{t("sp.preview_title")}</b>
              <div className="small muted" data-testid="sp-versions">
                {t("sp.file_version")}: {preview.file?.app_version ?? "—"} (schema {preview.file?.schema_version ?? "—"}) · {t("sp.this_version")}: {preview.current?.app_version ?? "—"} (schema {preview.current?.schema_version ?? "—"})
              </div>
              {preview.warnings.length > 0 && (
                <div className="alert warn small" data-testid="sp-warnings">
                  <ul>{preview.warnings.map((w) => <li key={w} data-testid={`sp-warn-${w}`}>{tr("sp.warn", w)}</li>)}</ul>
                  {preview.warnings.includes("SPIKE_NOT_TRANSFERRED") && preview.spike_current && (
                    <div className="small">{t("sp.spike_current")}: {Object.entries(preview.spike_current).map(([k, v]) => `${k} = ${fmt(v)}`).join(", ")}</div>
                  )}
                </div>
              )}
              <div className="scroll">
                <table className="tbl small">
                  <thead><tr><th>{t("sp.col_select")}</th><th>{t("sp.col_section")}</th><th>{t("adv.risk_col")}</th><th>{t("sp.col_changed")}</th><th>{t("sp.col_problems")}</th></tr></thead>
                  <tbody>
                    {preview.sections.map((s) => (
                      <tr key={s.section} data-testid={`sp-sec-${s.section}`}>
                        <td><input type="checkbox" data-testid={`sp-pick-${s.section}`} aria-label={tr("adv.section", s.section)} checked={!!selected[s.section]} disabled={!s.selectable}
                          onChange={(e) => setSelected({ ...selected, [s.section]: e.target.checked })} /></td>
                        <td>
                          <b>{tr("adv.section", s.section)}</b> <span className="mono small muted">{s.section}</span>
                          <details>
                            <summary className="small">{t("sp.keys")}</summary>
                            <table className="tbl small"><thead><tr><th>{t("gp.col_field")}</th><th>{t("sp.cur")}</th><th>{t("sp.in_file")}</th><th>{t("adv.risk_col")}</th></tr></thead>
                              <tbody>{s.rows.map((r) => (
                                <tr key={r.key} className={r.changed ? "" : "muted"}><td className="mono">{r.key}</td><td className="mono">{fmt(r.current)}</td>
                                  <td className="mono">{r.changed ? <b>{fmt(r.file)}</b> : fmt(r.file)}</td><td><RiskBadge risk={r.risk} /></td></tr>
                              ))}</tbody></table>
                          </details>
                        </td>
                        <td>{s.max_risk ? <RiskBadge risk={s.max_risk} /> : <span className="small muted">{t("sp.no_change")}</span>}</td>
                        <td>{s.changed.length}</td>
                        <td data-testid={`sp-err-${s.section}`}>
                          {s.errors.length > 0 ? <ul className="small bad-t">{s.errors.map((er, i) => <li key={i}>{errText(er)}</li>)}</ul> : "—"}
                          {s.max_risk && ["HIGH", "PURCHASE"].includes(s.max_risk) && !s.default_selected && s.selectable && <div className="small muted">{t("sp.not_selected_default")}</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="form-grid">
                <Field label={t("sp.type_import")} help={<code className="code" data-testid="sp-confirm-text">{textMain}</code>}>
                  <input type="text" data-testid="sp-confirm-input" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
                </Field>
                {needsHigh && (
                  <Field label={t("sp.type_high")} help={<code className="code" data-testid="sp-high-text">{textHigh}</code>}>
                    <input type="text" data-testid="sp-high-input" autoComplete="off" value={typedHigh} onChange={(e) => setTypedHigh(e.target.value)} />
                  </Field>
                )}
                {needsPurchase && (
                  <Field label={t("sp.type_purchase")} help={<code className="code" data-testid="sp-purchase-text">{textPurchase}</code>}>
                    <input type="text" data-testid="sp-purchase-input" autoComplete="off" value={typedPurchase} onChange={(e) => setTypedPurchase(e.target.value)} />
                  </Field>
                )}
                <Field label={t("gp.reason_required")} help={t("gp.reason_help").replace("{n}", String(reasonLen(reason))).replace("{m}", String(minReason)).replace("{x}", String(MAX_REASON))}>
                  <textarea rows={2} maxLength={MAX_REASON} data-testid="sp-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              </div>
              <div className="small muted">{t("gp.note.UNDO_SETTINGS_ONLY")}</div>
              <div className="row">
                <button className="primary" data-testid="sp-apply" onClick={doApply} disabled={!canApply}><Icon name="save" />{t("sp.apply")}</button>
                <button data-testid="sp-cancel" onClick={() => { resetImport(); setDoc(null); setFileName(""); actImp.setError(null); }}>{t("common.cancel")}</button>
              </div>
            </div>
          )}
        </div>

        <div>
          <b>{t("sp.history")}</b>
          {history.error ? <ErrorBox error={history.error} /> : !history.data ? <Loading /> : history.data.length === 0 ? <p className="small muted">{t("sp.history_empty")}</p> : (
            <div className="scroll" data-testid="sp-history">
              <table className="tbl small">
                <thead><tr><th>{t("gp.col_time")}</th><th>{t("adv.col_action")}</th><th>{t("sp.col_import")}</th><th>{t("adv.col_changes")}</th><th>{t("adv.col_reason")}</th><th /></tr></thead>
                <tbody>
                  {history.data.map((h) => (
                    <tr key={h.id} data-testid={`sp-hist-${h.id}`}>
                      <td className="nowrap">{fmtTime(h.at)}</td><td>{tr("sp.action", h.action)}</td><td className="mono">{h.entity_id}</td>
                      <td>
                        <ul>{(h.details.entries ?? []).map((en) => <li key={en.section}>{tr("adv.section", en.section)}: {Object.keys(en.keys).join(", ")}</li>)}</ul>
                        {(h.details.skipped ?? []).length > 0 && (
                          <ul className="small bad-t" data-testid={`sp-skipped-${h.id}`}>{(h.details.skipped ?? []).map((k) => <li key={`${k.section}.${k.key}`}>{k.section}.{k.key}: {tr("sp.err", k.reason)}</li>)}</ul>
                        )}
                      </td>
                      <td>{h.details.reason}</td>
                      <td>
                        {h.action === "SETTINGS_IMPORTED" && (h.undone
                          ? <span className="pill muted">{t("adv.undone_flag")}</span>
                          : <button className="small" data-testid={`sp-undo-${h.id}`} onClick={() => startUndo(h)} disabled={actUndo.busy}><Icon name="reset" />{t("sp.undo")}</button>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {errView(actUndo.error)}
          <OkBox text={actUndo.ok} />
          {uResult && uResult.skipped.length > 0 && (
            <div className="alert warn small" data-testid="sp-undo-skipped">
              <b>{t("sp.skipped_title")}</b>
              <ul>{uResult.skipped.map((k) => <li key={`${k.section}.${k.key}`}>{k.section}.{k.key}: {tr("sp.err", k.reason)} ({fmt(k.value)})</li>)}</ul>
            </div>
          )}
          {undoRow && (
            <div className="stack tight" data-testid="sp-undo-area">
              <b>{t("sp.undo_title").replace("{id}", undoRow.entity_id)}</b>
              {uKeys.length > 0 && <div className="small" data-testid="sp-undo-keys">{t("sp.undo_keys")}: <span className="mono">{uKeys.join(", ")}</span></div>}
              <div className="form-grid">
                <Field label={t("sp.type_import")} help={<code className="code" data-testid="sp-undo-text">{uMain}</code>}>
                  <input type="text" data-testid="sp-undo-input" autoComplete="off" value={uTyped} onChange={(e) => setUTyped(e.target.value)} />
                </Field>
                {uShowHigh && (
                  <Field label={t("sp.type_high")} help={<code className="code" data-testid="sp-undo-high-text">{uHighText}</code>}>
                    <input type="text" data-testid="sp-undo-high-input" autoComplete="off" value={uHigh} onChange={(e) => setUHigh(e.target.value)} />
                  </Field>
                )}
                {uShowPurchase && (
                  <Field label={t("sp.type_purchase")} help={<code className="code" data-testid="sp-undo-purchase-text">{uPurchaseText}</code>}>
                    <input type="text" data-testid="sp-undo-purchase-input" autoComplete="off" value={uPurchase} onChange={(e) => setUPurchase(e.target.value)} />
                  </Field>
                )}
                <Field label={t("gp.reason_required")} help={t("gp.reason_help").replace("{n}", String(reasonLen(uReason))).replace("{m}", String(DEFAULT_MIN_REASON)).replace("{x}", String(MAX_REASON))}>
                  <textarea rows={2} maxLength={MAX_REASON} data-testid="sp-undo-reason" value={uReason} onChange={(e) => setUReason(e.target.value)} />
                </Field>
              </div>
              <div className="small muted">{t("sp.undo_note")}</div>
              <div className="row">
                <button className="primary" data-testid="sp-undo-apply" onClick={doUndo} disabled={!uCanApply}><Icon name="reset" />{t("sp.undo")}</button>
                <button data-testid="sp-undo-cancel" onClick={() => { setUndoRow(null); actUndo.setError(null); }}>{t("common.cancel")}</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
