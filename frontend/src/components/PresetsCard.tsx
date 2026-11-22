import { useState } from "react";
import { get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, Code, ErrorBox, Field, Loading, OkBox, useAction, useAsync } from "./ui";
import { Icon } from "./icons";
import { normReason, reasonLen, BusyNotice, DescriptionList, ErrorDetails, OpsLockLine, RiskBadge, TypedConfirm, errParams, useFmt, useServerConfirmText, useTr, type BusyInfo } from "./guardedShared";

// 1.4.15 (lot 6): card "Cấu hình mẫu (preset)" of the page "Cấu hình dự báo" (CLI `apply-preset`): the presets, a preview that writes
// nothing (old -> new keys, keys kept higher, the flows that would be switched ON and whether they are ready), then the typed text +
// reason and the apply. It changes forecast / purchase numbers and switches flows ON; a retention is never lowered.

interface Desc { code?: string; vi?: string; en?: string }
interface PresetItem { name: string; sections: Record<string, Record<string, unknown>>; flows: string[]; confirm_text: string; description: Desc[] }
interface PChange { section: string; key: string; from: unknown; to: unknown; risk: string | null; undoable: boolean }
interface Kept { section: string; key: string; current: unknown; preset: unknown }
interface PFlow { flow: string; from: boolean; to: boolean; ready: boolean; reasons?: { code?: string; detail?: string | null }[] }
interface PPreview {
  preset: string; changes: PChange[]; kept_higher: Kept[]; flows: PFlow[]; changed: boolean; ready: boolean; expected_hash: string; confirm_text: string;
  reason_min_length: number; not_undoable: string[]; description: Desc[]; busy?: BusyInfo;
  needs_purchase_confirm?: boolean; purchase_keys?: string[]; confirm_purchase?: string; undo_warning?: Desc;
  window_soon?: string | null; schedule_times?: { setting: string; time: string }[]; ops_lock_checked?: boolean; ops_lock_source?: string | null; ops_locks?: { env: string; path: string }[];
}
interface PResult {
  preset: string; applied: { section: string; key: string; from: unknown; to: unknown }[]; kept_higher: Kept[]; flows: PFlow[]; undo_audit_id: number | null; not_undoable: string[];
  partial?: boolean; flow_errors?: { flow: string; code?: string; detail?: string | null }[]; warnings?: string[]; undo_warning?: Desc;
}

export default function PresetsCard() {
  const { t, lang } = useI18n();
  const fmt = useFmt();
  const tr = useTr();
  const list = useAsync(() => get<{ presets: PresetItem[] }>("/api/presets"), []);
  const act = useAction();
  const [pv, setPv] = useState<PPreview | null>(null);
  const [result, setResult] = useState<PResult | null>(null);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [typedP, setTypedP] = useState("");          // the text of the purchase level: asked when a PURCHASE key changes
  const serverText = useServerConfirmText(act.error, "PRESET_CONFIRM_REQUIRED", () => setTyped(""));
  const serverPurchase = useServerConfirmText(act.error, "PRESET_PURCHASE_CONFIRM_REQUIRED", () => setTypedP(""), "confirm_purchase");
  const needsPurchase = !!pv?.needs_purchase_confirm;
  const purchaseText = serverPurchase ?? pv?.confirm_purchase ?? "";
  const confirmText = serverText ?? pv?.confirm_text ?? "";
  const minReason = pv?.reason_min_length ?? 10;
  const notReady = (pv?.flows ?? []).filter((f) => !f.ready);
  // the preview locks Apply: a busy system, a production window / saved schedule time near, or an operations lock file
  const busyNow = !!pv?.busy?.busy || !!pv?.window_soon || (pv?.schedule_times ?? []).length > 0 || (pv?.ops_locks ?? []).length > 0;
  const canApply = !!pv && pv.changed && notReady.length === 0 && !busyNow && !act.busy && typed.trim() === confirmText && reasonLen(reason) >= minReason
    && (!needsPurchase || typedP.trim() === purchaseText);
  const err = act.error;
  const flowsErr = (errParams(err).flows ?? []) as PFlow[];

  const preview = async (name: string) => {
    setTyped(""); setTypedP(""); setReason(""); setResult(null);
    const r = await act.run(() => post<PPreview>(`/api/presets/${encodeURIComponent(name)}/preview`));
    setPv(r ?? null);
  };
  const apply = async () => {
    if (!pv) return;
    const r = await act.run(() => post<PResult>(`/api/presets/${encodeURIComponent(pv.preset)}/apply`, { expected_hash: pv.expected_hash, confirm_text: typed.trim(), reason: normReason(reason), ...(needsPurchase ? { confirm_purchase: typedP.trim() } : {}) }),
      t("pr.applied"));
    if (r) { setResult(r); setPv(null); setTyped(""); setTypedP(""); setReason(""); }
  };

  return (
    <Card icon="config" title={t("pr.title")}>
      <div className="stack">
        <p className="small muted">{t("pr.intro")}</p>
        <div className="alert warn" data-testid="pr-warning"><b>{t("pr.warning")}</b></div>
        {list.error ? <ErrorBox error={list.error} /> : !list.data ? <Loading /> : (
          <div className="scroll"><table className="tbl small" data-testid="pr-list">
            <thead><tr><th>{t("pr.col_name")}</th><th>{t("pr.col_what")}</th><th>{t("pr.col_flows")}</th><th /></tr></thead>
            <tbody>
              {(list.data.presets ?? []).map((p) => (
                <tr key={p.name} data-testid={`pr-row-${p.name}`}>
                  <td className="mono">{p.name}</td>
                  <td><DescriptionList items={p.description} testid={`pr-desc-${p.name}`} />
                    <div className="small muted">{t("pr.n_keys").replace("{n}", String(Object.values(p.sections ?? {}).reduce((a, s) => a + Object.keys(s).length, 0)))}</div></td>
                  <td>{(p.flows ?? []).join(", ") || "—"}</td>
                  <td><button className="small" data-testid={`pr-preview-${p.name}`} onClick={() => void preview(p.name)} disabled={act.busy}><Icon name="search" />{t("pr.preview")}</button></td>
                </tr>
              ))}
              {(list.data.presets ?? []).length === 0 && <tr><td colSpan={4} className="muted">{t("pr.none")}</td></tr>}
            </tbody>
          </table></div>
        )}
        <ErrorDetails error={err} />
        {flowsErr.length > 0 && (
          <div className="alert bad small" data-testid="pr-flows-error">{t("pr.flows_not_ready")}
            <ul>{flowsErr.map((f) => <li key={f.flow}><b>{f.flow}</b>: {(f.reasons ?? []).map((r, i) => <span key={i}><Code code={r.code} /> </span>)}</li>)}</ul></div>
        )}
        <OkBox text={act.ok} />

        {result && (
          <div className="stack tight" data-testid="pr-result">
            <b>{t("pr.result_title").replace("{name}", result.preset)}</b>
            {result.partial && (
              <div className="alert bad" role="alert" data-testid="pr-partial">
                <b>{t("pr.partial")}</b>
                <ul className="small" data-testid="pr-flow-errors">{(result.flow_errors ?? []).map((f) => (
                  <li key={f.flow}><b>{f.flow}</b>: <Code code={f.code} />{f.detail ? <span className="mono small"> {f.detail}</span> : null}</li>
                ))}</ul>
                {(result.warnings ?? []).map((w) => <div key={w} className="small" data-testid={`pr-warn-${w}`}>{tr("pr.warn", w)}</div>)}
              </div>
            )}
            <ul className="small">{result.applied.map((x) => <li key={`${x.section}.${x.key}`} className="mono">{x.section}.{x.key}: {fmt(x.from)} → {fmt(x.to)}</li>)}</ul>
            {result.flows.length > 0 && (
              <ul className="small" data-testid="pr-result-flows">{result.flows.map((f) => (
                <li key={f.flow}><b>{f.flow}</b>: {f.to ? t("pr.flow_on") : <span className="bad-t">{t("pr.flow_not_on")} {(f.reasons ?? []).map((r) => r.code).join(", ")}</span>}</li>
              ))}</ul>
            )}
            {result.not_undoable.length > 0 && <div className="small muted" data-testid="pr-result-notundo">{t("pr.not_undoable")}: <span className="mono">{result.not_undoable.join(", ")}</span></div>}
            <div className="alert info small" data-testid="pr-undo-guide">{t("pr.undo_guide")}{result.undo_audit_id != null ? ` ${t("pr.undo_id").replace("{id}", String(result.undo_audit_id))}` : ""}</div>
            {result.undo_warning && <div className="alert warn small" data-testid="pr-undo-warning">{lang === "vi" ? result.undo_warning.vi : result.undo_warning.en}</div>}
          </div>
        )}

        {pv && (
          <div className="stack tight" data-testid="pr-confirm-area">
            <b>{t("pr.preview_title").replace("{name}", pv.preset)}</b>
            <DescriptionList items={pv.description} testid="pr-preview-desc" />
            {pv.changes.length === 0 ? <div className="small muted" data-testid="pr-no-keys">{t("pr.no_keys")}</div> : (
              <div className="scroll"><table className="tbl small" data-testid="pr-changes">
                <thead><tr><th>{t("gp.col_field")}</th><th>{t("adv.risk_col")}</th><th>{t("gp.col_before")}</th><th>{t("gp.col_after")}</th></tr></thead>
                <tbody>{pv.changes.map((c) => (
                  <tr key={`${c.section}.${c.key}`} data-testid={`pr-change-${c.section}.${c.key}`}>
                    <td className="mono">{c.section}.{c.key}</td><td>{c.risk ? <RiskBadge risk={c.risk} /> : "—"}</td><td className="mono">{fmt(c.from)}</td><td className="mono"><b>{fmt(c.to)}</b></td></tr>
                ))}</tbody>
              </table></div>
            )}
            {pv.kept_higher.length > 0 && (
              <div className="alert info small" data-testid="pr-kept">{t("pr.kept_higher")}
                <ul>{pv.kept_higher.map((k) => <li key={`${k.section}.${k.key}`} className="mono">{k.section}.{k.key}: {t("pr.kept_item").replace("{cur}", fmt(k.current)).replace("{pre}", fmt(k.preset))}</li>)}</ul></div>
            )}
            <div className="scroll"><table className="tbl small" data-testid="pr-flows">
              <thead><tr><th>{t("pr.flow")}</th><th>{t("pr.flow_state")}</th><th>{t("pr.flow_ready")}</th></tr></thead>
              <tbody>{pv.flows.map((f) => (
                <tr key={f.flow} data-testid={`pr-flow-${f.flow}`}><td><b>{f.flow}</b></td>
                  <td>{f.from ? t("pr.flow_already_on") : t("pr.flow_will_on")}</td>
                  <td>{f.ready ? <span className="pill ok">{t("pr.ready")}</span> : <><span className="pill bad">{t("pr.not_ready")}</span> {(f.reasons ?? []).map((r, i) => <span key={i}><Code code={r.code} /> </span>)}</>}</td></tr>
              ))}</tbody>
            </table></div>
            {pv.not_undoable.length > 0 && <div className="small muted" data-testid="pr-notundo">{t("pr.not_undoable")}: <span className="mono">{pv.not_undoable.join(", ")}</span></div>}
            <div className="alert info small" data-testid="pr-undo-guide-preview">{t("pr.undo_guide")}</div>
            {pv.undo_warning && <div className="alert warn small" data-testid="pr-undo-warning-preview">{lang === "vi" ? pv.undo_warning.vi : pv.undo_warning.en}</div>}
            <BusyNotice busy={pv.busy} />
            {pv.window_soon && <div className="alert warn small" data-testid="pr-window-soon">{t("bg.window_soon").replace("{w}", pv.window_soon).replace("{m}", "60")}</div>}
            {(pv.schedule_times ?? []).length > 0 && <div className="alert warn small" data-testid="pr-sched">{t("bg.sched_near")} {(pv.schedule_times ?? []).map((x) => `${x.setting} ${x.time}`).join(", ")}</div>}
            <OpsLockLine checked={pv.ops_lock_checked} source={pv.ops_lock_source} locks={pv.ops_locks} prefix="pr" />
            {notReady.length > 0 && <div className="alert bad small" data-testid="pr-blocked">{t("pr.blocked")}</div>}
            {!pv.changed && <div className="alert info small" data-testid="pr-already">{t("pr.already")}</div>}
            {pv.changed && (
              <>
                <div className="alert warn" data-testid="pr-warning-confirm"><b>{t("pr.warning")}</b></div>
                <TypedConfirm id="pr" text={confirmText} minReason={minReason} typed={typed} setTyped={setTyped} reason={reason} setReason={setReason} />
                {needsPurchase && (
                  <div className="stack tight" data-testid="pr-purchase-area">
                    <div className="alert warn small"><b>{t("pr.purchase_keys")}</b>
                      <ul data-testid="pr-purchase-keys">{(pv.purchase_keys ?? []).map((k) => <li key={k} className="mono">{k}</li>)}</ul></div>
                    <Field label={t("pr.type_purchase")} help={<code className="code" data-testid="pr-purchase-text">{purchaseText}</code>}>
                      <input type="text" data-testid="pr-purchase-input" autoComplete="off" value={typedP} onChange={(e) => setTypedP(e.target.value)} />
                    </Field>
                  </div>
                )}
              </>
            )}
            <div className="row">
              <button className="primary" data-testid="pr-apply" onClick={apply} disabled={!canApply}><Icon name="save" />{t("pr.apply")}</button>
              <button data-testid="pr-cancel" onClick={() => { setPv(null); act.setError(null); }}>{t("common.cancel")}</button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
