import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { get, post } from "../api";
import { useI18n } from "../i18n";
import { Bars, Card, Code, Empty, ErrorBox, Loading, MethodLabel, OkBox, Pill, SourceBadge, Stat, Term, fmtDate, fmtNum, fmtPct, fmtSignedPct, fmtTime, useAction, useAsync } from "../components/ui";

function MetricsRow({ label, m }: { label: ReactNode; m: any }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num">{fmtPct(m?.wape)}</td>
      <td className="num">{fmtNum(m?.mae, 2)}</td>
      <td className="num">{fmtSignedPct(m?.bias)}</td>
      <td className="num">{fmtPct(m?.mape)} <span className="small muted">({m?.mape_points ?? 0}/{m?.n_points ?? 0})</span></td>
      <td className="num">{fmtNum(m?.n_points)}</td>
    </tr>
  );
}

function MetricsHead() {
  const { t } = useI18n();
  return (
    <thead>
      <tr>
        <th></th><th className="num"><Term id="wape">WAPE</Term></th><th className="num"><Term id="mae">MAE</Term></th>
        <th className="num"><Term id="bias">Bias</Term></th><th className="num"><Term id="mape">MAPE</Term></th><th className="num">{t("perf.points")}</th>
      </tr>
    </thead>
  );
}

const PENDING = "PROMOTION_REVIEW_REQUIRED";
/** A candidate kept for review is stored as REJECTED + PROMOTION_REVIEW_REQUIRED (schema unchanged): show it as such. */
const shownStatus = (r: any) => (r?.reject_reason === PENDING ? "CANDIDATE" : r?.status);

/** Same-fold comparison of a candidate with the model in use, and the explicit "use this model" decision. */
function Promotion({ d, onPromoted }: { d: any; onPromoted: () => void }) {
  const { t } = useI18n();
  const act = useAction();
  const p = d?.quality_gate?.promotion;
  if (!p) return null;
  return (
    <Card title={t("perf.promotion")}>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <p className="small" data-testid="promotion-decision">
        {d.in_use ? <Pill status="OK" label={t("perf.in_use")} /> : d.can_promote ? <Pill status="CANDIDATE" /> : null}{" "}
        {p.decision ? t(`perf.decision.${p.decision}`) : null}
      </p>
      {p.verdict && (
        <>
          <p data-testid="promotion-verdict"><b>{t(`perf.verdict.${p.verdict}`)}</b>{p.reason ? <span className="small muted"> — <Code code={p.reason} /></span> : null}</p>
          {p.incumbent && (
            <table className="tbl small">
              <MetricsHead />
              <tbody>
                <MetricsRow label={t("perf.candidate")} m={p.candidate} />
                <MetricsRow label={<>{t("perf.incumbent")} <span className="mono">{p.incumbent_model_version}</span></>} m={p.incumbent} />
              </tbody>
            </table>
          )}
          <p className="small muted">{t("perf.compare_method")}</p>
        </>
      )}
      {d.can_promote && (
        <button className="primary" data-testid="promote" disabled={act.busy}
          onClick={async () => {
            if (!window.confirm(t("perf.promote_confirm"))) return;
            const r = await act.run(() => post(`/api/training-runs/${d.id}/promote`, { confirm: true }), t("perf.promoted"));
            if (r) onPromoted();
          }}>{t("perf.promote")}</button>
      )}
    </Card>
  );
}

/** 1.2.0: documented quality-gate exception for ONE training run. The standard thresholds are never changed; the
 * approver restates the run's real WAPE / bias and types EXCEPTION-<run id>. Shown for runs the backend marks eligible
 * (rejected only on the metric thresholds, model file kept), and as a record once released. */
export function GateException({ d, onDone }: { d: any; onDone: () => void }) {
  const { t } = useI18n();
  const act = useAction();
  const [f, setF] = useState({ approved_by: "", reason: "", review_by: "", acknowledged_wape: "", acknowledged_bias: "", confirm_text: "" });
  const exc = d?.quality_gate?.exception;
  if (exc) {
    return (
      <Card title={t("perf.exception_active")}>
        <div className="alert warn small" data-testid="exception-active">
          {t("perf.exception_by")}: <b>{exc.approved_by}</b> · {t("perf.exception_review")}: <b>{fmtDate(exc.review_by)}</b> · WAPE {fmtNum(exc.metrics?.wape, 3)} · bias {fmtNum(exc.metrics?.bias, 3)}
          <br />{t("perf.exception_reason")}: {exc.reason}
        </div>
      </Card>
    );
  }
  if (!d?.gate_exception?.eligible) return null;
  const s = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <Card title={t("perf.exception")}>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <p className="small">{t("perf.exception_note")}</p>
      <div className="form-grid">
        <label>{t("perf.exception_by")}<input data-testid="exc-by" value={f.approved_by} onChange={s("approved_by")} /></label>
        <label>{t("perf.exception_review")}<input data-testid="exc-review" type="date" value={f.review_by} onChange={s("review_by")} /></label>
        <label className="full">{t("perf.exception_reason")}<textarea data-testid="exc-reason" value={f.reason} onChange={s("reason")} /></label>
        <label>{t("perf.exception_ack")} — WAPE<input data-testid="exc-wape" value={f.acknowledged_wape} onChange={s("acknowledged_wape")} /></label>
        <label>bias<input data-testid="exc-bias" value={f.acknowledged_bias} onChange={s("acknowledged_bias")} /></label>
        <label className="full">{t("perf.exception_confirm")}: <code>EXCEPTION-{d.id}</code><input data-testid="exc-confirm" value={f.confirm_text} onChange={s("confirm_text")} /></label>
      </div>
      <button className="primary" data-testid="exc-release" disabled={act.busy}
        onClick={async () => {
          const body = { ...f, acknowledged_wape: Number(f.acknowledged_wape), acknowledged_bias: Number(f.acknowledged_bias) };
          const r = await act.run(() => post(`/api/training-runs/${d.id}/release-with-exception`, body), t("perf.exception_done"));
          if (r) onDone();
        }}>{t("perf.exception_btn")}</button>
    </Card>
  );
}

export default function Performance() {
  const { t } = useI18n();
  const runs = useAsync(() => get("/api/training-runs?limit=100"), []);
  const [sel, setSel] = useState("");
  useEffect(() => {
    if (!sel && runs.data?.length) setSel(runs.data[0].id);
  }, [runs.data, sel]);
  const det = useAsync(() => (sel ? get(`/api/training-runs/${sel}`) : Promise.resolve(null)), [sel]);
  if (runs.loading && !runs.data) return <Loading />;   // a reload must not unmount the page (job progress)
  const d = det.data;
  const bt = d?.backtest;
  const cfg = bt?.config;
  return (
    <div className="stack">
      <h2>{t("nav.performance")}</h2>
      <ErrorBox error={runs.error || det.error} />
      <Card title={t("perf.runs")}>
        {!runs.data?.length ? <Empty text={t("common.not_available")} /> : (
          <div className="scroll">
            <table className="tbl click">
              <thead><tr><th>{t("common.created")}</th><th>{t("common.status")}</th><th>{t("fc.model_version")}</th><th>{t("common.source")}</th><th className="num">WAPE</th><th className="num">Bias</th><th>{t("perf.reject_reason")}</th></tr></thead>
              <tbody>
                {runs.data.map((r: any) => (
                  <tr key={r.id} className={r.id === sel ? "sel" : ""} onClick={() => setSel(r.id)}>
                    <td>{fmtTime(r.started_at)}</td><td><Pill status={shownStatus(r)} /></td><td className="mono small">{r.model_version ?? "—"}</td>
                    <td><SourceBadge source={r.data_source} /></td><td className="num">{fmtPct(r.metrics?.wape)}</td><td className="num">{fmtSignedPct(r.metrics?.bias)}</td>
                    <td className="small"><Code code={r.reject_reason} showCode={false} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {d && (
        <>
          <div className="grid4">
            <Stat label={t("common.status")} value={<Pill status={shownStatus(d)} />} sub={d.reject_reason ? <Code code={d.reject_reason} /> : d.error} />
            <Stat label={t("perf.train_range")} value={<span className="small">{fmtDate(d.train_start)} → {fmtDate(d.train_end)}</span>} sub={`${fmtNum(d.n_series)} ${t("common.series")} · ${fmtNum(d.n_rows)} ${t("common.rows")}`} />
            <Stat label={t("fc.model_version")} value={<span className="mono small">{d.model_version ?? "—"}</span>} sub={d.model_path ? `${d.model_path} · sha256 ${String(d.model_sha256).slice(0, 12)}…` : undefined} />
            <Stat label={<Term id="backtesting">{t("perf.backtest")}</Term>} value={bt ? (bt.reliable ? <Pill status="OK" label={t("perf.reliable")} /> : <Pill status="INSUFFICIENT" label={t("perf.unreliable")} />) : "—"}
              sub={bt ? (cfg?.span_days !== undefined
                ? <span data-testid="bt-span">{cfg.folds_evaluated} × {cfg.horizon_days} {t("common.days")} · {fmtDate(cfg.first_day)} → {fmtDate(cfg.last_day)} ({cfg.span_days} {t("common.days")})</span>
                : `${cfg?.folds} × ${cfg?.horizon_days} ${t("common.days")}`) : undefined} />
          </div>
          {bt?.notes?.some((n: any) => n.code === "BACKTEST_SPAN_BELOW_6_MONTHS") && (
            <div className="alert warn small" data-testid="bt-short">{t("perf.span_short")}</div>
          )}
          <Promotion d={d} onPromoted={() => { det.reload(); runs.reload(); }} />
          <GateException d={d} onDone={() => { det.reload(); runs.reload(); }} />
          {d.quality_gate?.checks && (
            <Card title={<Term id="quality_gate">{t("perf.gate")}</Term>}>
              {!d.quality_gate.thresholds_approved_by_business && <div className="alert warn small">{t("cfg.quality_warning")}</div>}
              <table className="tbl">
                <thead><tr><th></th><th className="num">{t("perf.value")}</th><th className="num">{t("perf.threshold")}</th><th>{t("perf.passed")}</th></tr></thead>
                <tbody>
                  {d.quality_gate.checks.map((c: any) => (
                    <tr key={c.check}>
                      <td>{t(`perf.check.${c.check}`)}</td>
                      <td className="num">{typeof c.value === "number" ? (c.check.includes("POINTS") || c.check === "BACKTEST_RELIABLE" ? fmtNum(c.value) : fmtPct(c.value)) : String(c.value ?? "—")}</td>
                      <td className="num">{typeof c.threshold === "number" ? (c.check.includes("POINTS") ? fmtNum(c.threshold) : fmtPct(c.threshold)) : "—"}</td>
                      <td>{c.passed ? <Pill status="OK" label={t("common.yes")} /> : <Pill status="FAILED" label={t("common.no")} />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          {bt && (
            <Card title={<Term id="backtesting">{t("perf.backtest")}</Term>}>
              <table className="tbl">
                <MetricsHead />
                <tbody>
                  <MetricsRow label="LightGBM + fallback" m={bt.metrics?.pooled} />
                  <MetricsRow label={t("perf.baseline")} m={bt.metrics?.baseline} />
                </tbody>
              </table>
              <h4>{t("perf.fold")}</h4>
              <table className="tbl">
                <thead><tr><th>#</th><th>{t("fc.start")}</th><th>{t("fc.end")}</th><th className="num">WAPE</th><th className="num">MAE</th><th className="num">Bias</th><th className="num">{t("perf.baseline")} WAPE</th></tr></thead>
                <tbody>
                  {bt.folds.map((f: any) => (
                    <tr key={f.fold}><td>{f.fold}</td><td>{fmtDate(f.origin)}</td><td>{fmtDate(f.end)}</td><td className="num">{fmtPct(f.metrics.wape)}</td><td className="num">{fmtNum(f.metrics.mae, 2)}</td><td className="num">{fmtSignedPct(f.metrics.bias)}</td><td className="num">{fmtPct(f.baseline_metrics.wape)}</td></tr>
                  ))}
                </tbody>
              </table>
              <h4><Term id="fallback">{t("perf.by_method")}</Term></h4>
              <table className="tbl">
                <MetricsHead />
                <tbody>
                  {Object.entries(bt.metrics?.by_method ?? {}).map(([k, m]) => <MetricsRow key={k} label={<MethodLabel code={k} />} m={m} />)}
                </tbody>
              </table>
              {bt.notes?.length > 0 && <p className="small muted">{bt.notes.map((n: any) => n.code).join(", ")}</p>}
            </Card>
          )}
          {d.feature_importance?.length > 0 && (
            <Card title={<Term id="features">{t("perf.importance")}</Term>}>
              <Bars items={d.feature_importance.slice(0, 15).map((f: any) => ({ label: f.feature, value: f.gain }))} />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
