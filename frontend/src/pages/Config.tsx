import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { get, post, put } from "../api";
import { useI18n } from "../i18n";
import { Card, DateInput, ErrorBox, Field, Loading, OkBox, Term, fmtDatesInText, fmtPct, fmtTime, useAction, useAsync } from "../components/ui";

type Setter = (patch: Record<string, any>) => void;

function Section({ section, title, children, warning }: { section: string; title: ReactNode; warning?: ReactNode; children: (v: any, set: Setter) => ReactNode }) {
  const { t } = useI18n();
  const remote = useAsync(() => get("/api/settings"), []);
  const [v, setV] = useState<any>(null);
  const [showHist, setShowHist] = useState(false);
  const hist = useAsync(() => (showHist ? get(`/api/settings/${section}/history`) : Promise.resolve(null)), [showHist]);
  const act = useAction();
  useEffect(() => {
    if (remote.data) setV(remote.data[section]);
  }, [remote.data, section]);
  if (!v) return <Card title={title}><Loading /></Card>;
  const set: Setter = (patch) => setV({ ...v, ...patch });
  const save = async () => {
    const r = await act.run(() => put(`/api/settings/${section}`, v), t("common.saved"));
    if (r) {
      setV(r);
      hist.reload();
    }
  };
  const reset = async () => {
    const r = await act.run(() => post(`/api/settings/${section}/reset`), t("common.saved"));
    if (r) setV(r);
  };
  return (
    <Card title={title} actions={<>
      <button onClick={() => setShowHist(!showHist)}>{t("common.history")}</button>
      <button onClick={reset} disabled={act.busy}>{t("common.reset")}</button>
      <button className="primary" onClick={save} disabled={act.busy}>{t("common.save")}</button>
    </>}>
      {warning}
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <div className="form-grid">{children(v, set)}</div>
      {showHist && hist.data && (
        <details open className="hist">
          <summary>{t("common.history")}</summary>
          <table className="tbl small">
            <tbody>
              {hist.data.map((h: any) => (
                <tr key={h.id}><td>{fmtTime(h.changed_at)}</td><td className="mono">{fmtDatesInText(JSON.stringify(h.value).slice(0, 220))}</td><td>{h.note}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}

const Num = ({ v, k, set, step = 1, min }: { v: any; k: string; set: Setter; step?: number; min?: number }) => (
  <input type="number" step={step} min={min} value={v[k] ?? ""} onChange={(e) => set({ [k]: e.target.value === "" ? null : Number(e.target.value) })} />
);
const Bool = ({ v, k, set }: { v: any; k: string; set: Setter }) => (
  <input type="checkbox" checked={!!v[k]} onChange={(e) => set({ [k]: e.target.checked })} />
);

function HorizonEditor({ v, set }: { v: any; set: Setter }) {
  const { t } = useI18n();
  const [custom, setCustom] = useState("");
  const [err, setErr] = useState(false);
  const toggle = (h: number) => set({ enabled: v.enabled.includes(h) ? v.enabled.filter((x: number) => x !== h) : [...v.enabled, h].sort((a: number, b: number) => a - b) });
  const add = () => {
    const n = Number(custom);
    if (!Number.isInteger(n) || n < 1 || n > v.max_allowed_days) {
      setErr(true);
      return;
    }
    setErr(false);
    set({ choices: Array.from(new Set([...v.choices, n])).sort((a, b) => a - b), enabled: Array.from(new Set([...v.enabled, n])).sort((a, b) => a - b) });
    setCustom("");
  };
  return (
    <div className="full">
      <p className="small">{t("cfg.horizons_help")}</p>
      <div className="chips">
        {v.choices.map((h: number) => (
          <label key={h} className={v.enabled.includes(h) ? "chip on" : "chip"}>
            <input type="checkbox" checked={v.enabled.includes(h)} onChange={() => toggle(h)} /> {h} {t("common.days")}
          </label>
        ))}
      </div>
      <div className="row">
        <Field label={t("cfg.add_custom")} help={err ? <span className="bad-t">{t("cfg.invalid_int")}</span> : undefined}>
          <input type="number" min={1} step={1} value={custom} onChange={(e) => setCustom(e.target.value)} />
        </Field>
        <button onClick={add}>{t("cfg.add")}</button>
        <Field label={t("cfg.max_allowed")}><Num v={v} k="max_allowed_days" set={set} min={1} /></Field>
      </div>
    </div>
  );
}

/** 1.2.0 feature groups. Historical demand = lags + rolling statistics of the demand; price = quantity-weighted unit
 * price of the order lines. Calendar and SKU / FC codes are always part of the model. A group that is on but has no data
 * in the active source is left out of the next training (shown here). Changes apply to the NEXT training only: a model
 * in use keeps the exact feature list it was trained with. */
export function FeatureGroups({ v, set }: { v: any; set: Setter }) {
  const { t } = useI18n();
  const reg = useAsync(() => get("/api/features/registry"), []);
  const price = reg.data?.decisions?.price;
  const hist = !!(v.feature_lags || v.feature_rolling);
  const none = !v.feature_lags && !v.feature_rolling && !v.feature_price;
  return (
    <>
      <div className="full"><b>{t("cfg.feature_groups")}</b> <span className="small muted">{t("cfg.fg_note")}</span></div>
      <Field label={t("cfg.fg_history")}>
        <label className="row small">
          <input type="checkbox" data-testid="fg-history" checked={hist}
            onChange={(e) => set({ feature_lags: e.target.checked, feature_rolling: e.target.checked })} />{t("cfg.fg_history_desc")}
        </label>
      </Field>
      <Field label={t("cfg.fg_price")}>
        <label className="row small">
          <input type="checkbox" data-testid="fg-price" checked={!!v.feature_price} onChange={(e) => set({ feature_price: e.target.checked })} />{t("cfg.fg_price_desc")}
        </label>
        {v.feature_price && price && !price.used && (
          <div className="alert warn small" data-testid="fg-price-nodata">{t("cfg.fg_price_nodata").replace("{c}", fmtPct(price.coverage ?? 0))}</div>
        )}
      </Field>
      <div className="full small muted">{t("cfg.fg_always")}</div>
      {none && <div className="full alert error small" data-testid="fg-empty">{t("cfg.fg_empty")}</div>}
      <Field label={t("cfg.strategy")}>
        <select data-testid="strategy" value={v.forecast_strategy ?? "RECURSIVE"} onChange={(e) => set({ forecast_strategy: e.target.value })}>
          <option value="RECURSIVE">{t("cfg.strategy.RECURSIVE")}</option>
          <option value="DIRECT">{t("cfg.strategy.DIRECT")}</option>
        </select>
      </Field>
      {v.forecast_strategy === "DIRECT" && (
        <>
          <Field label={t("cfg.direct_origins")}><Num v={v} k="direct_origins" set={set} min={1} /></Field>
          <Field label={t("cfg.direct_origin_step_days")}><Num v={v} k="direct_origin_step_days" set={set} min={1} /></Field>
        </>
      )}
    </>
  );
}

export default function Config() {
  const { t } = useI18n();
  return (
    <div className="stack">
      <h2>{t("nav.config")}</h2>
      <Section section="horizons" title={t("cfg.horizons")}>{(v, set) => <HorizonEditor v={v} set={set} />}</Section>

      <Section section="quality" title={<Term id="quality_gate">{t("cfg.quality")}</Term>} warning={<div className="alert warn">{t("cfg.quality_warning")}</div>}>
        {(v, set) => (
          <>
            <Field label={<Term id="wape">{t("cfg.wape_max")}</Term>}><Num v={v} k="wape_max" set={set} step={0.01} /></Field>
            <Field label={<Term id="bias">{t("cfg.bias_max")}</Term>}><Num v={v} k="abs_bias_max" set={set} step={0.01} /></Field>
            <Field label={t("cfg.min_points")}><Num v={v} k="min_backtest_points" set={set} /></Field>
            <Field label={<Term id="mape">{t("cfg.mape_min")}</Term>}><Num v={v} k="mape_min_actual" set={set} step={0.5} /></Field>
            <Field label={t("cfg.beat_baseline")}><Bool v={v} k="require_beat_baseline" set={set} /></Field>
            <Field label={t("cfg.approved")}><Bool v={v} k="approved_by_business" set={set} /></Field>
          </>
        )}
      </Section>

      <Section section="model" title={<Term id="features">{t("cfg.model")}</Term>}>
        {(v, set) => (
          <>
            <FeatureGroups v={v} set={set} />
            <div className="full"><b><Term id="fallback">{t("cfg.fallback")}</Term></b></div>
            {["min_total_history_days", "min_series_history_days", "inactive_days", "fallback_window_days"].map((k) => (
              <Field key={k} label={t(`cfg.${k}`)}><Num v={v} k={k} set={set} /></Field>
            ))}
            <Field label={t("cfg.intermittent_zero_share")}><Num v={v} k="intermittent_zero_share" set={set} step={0.05} /></Field>
            <div className="full"><b><Term id="backtesting">{t("cfg.backtest")}</Term></b></div>
            {["backtest_folds", "backtest_horizon_days", "backtest_step_days"].map((k) => (
              <Field key={k} label={t(`cfg.${k}`)}><Num v={v} k={k} set={set} /></Field>
            ))}
            <div className="full"><b>{t("cfg.lgbm")}</b></div>
            <Field label={t("cfg.num_boost_round")}><Num v={v} k="num_boost_round" set={set} /></Field>
            <Field label={t("cfg.learning_rate")}><Num v={v} k="learning_rate" set={set} step={0.01} /></Field>
            <Field label={t("cfg.num_leaves")}><Num v={v} k="num_leaves" set={set} /></Field>
            <Field label={t("cfg.max_train_days")}><Num v={v} k="max_train_days" set={set} /></Field>
            <Field label={t("cfg.objective")}>
              <select value={v.objective} onChange={(e) => set({ objective: e.target.value })}>
                {["tweedie", "poisson", "regression", "regression_l1"].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
          </>
        )}
      </Section>

      <Section section="data_policy" title={t("cfg.data_policy")}>
        {(v, set) => (
          <>
            <Field label={<Term id="freshness">{t("cfg.stale_sources")}</Term>}>
              <div className="row">
                {["DEMO", "MANUAL_IMPORT", "BIGQUERY"].map((s) => (
                  <label key={s} className="row small">
                    <input type="checkbox" checked={v.stale_check_sources.includes(s)}
                      onChange={(e) => set({ stale_check_sources: e.target.checked ? [...v.stale_check_sources, s] : v.stale_check_sources.filter((x: string) => x !== s) })} />{s}
                  </label>
                ))}
              </div>
            </Field>
            <Field label={t("cfg.max_lag")}><Num v={v} k="max_data_lag_days" set={set} /></Field>
            <Field label={t("cfg.late_lookback")}><Num v={v} k="late_data_lookback_days" set={set} /></Field>
            <Field label={t("cfg.min_date")}><DateInput value={v.min_date ?? ""} onChange={(d) => set({ min_date: d || null })} /></Field>
            <Field label={t("cfg.price_outlier")}><Num v={v} k="price_outlier_factor" set={set} step={0.5} /></Field>
          </>
        )}
      </Section>

      <Section section="import" title={t("cfg.import")}>
        {(v, set) => (
          <>
            <Field label={t("cfg.max_file_mb")}><Num v={v} k="max_file_mb" set={set} /></Field>
            <Field label={t("cfg.max_rows")}><Num v={v} k="max_rows" set={set} /></Field>
            <Field label={t("cfg.grain_policy")}>
              <select value={v.grain_conflict_policy} onChange={(e) => set({ grain_conflict_policy: e.target.value })}>
                <option value="ERROR">{t("cfg.grain.ERROR")}</option>
                <option value="SUM">{t("cfg.grain.SUM")}</option>
              </select>
            </Field>
          </>
        )}
      </Section>

      <Section section="schedule" title={t("cfg.schedule")} warning={<p className="small muted">{t("job.offline_note")}</p>}>
        {(v, set) => (
          <>
            <div className="full alert info small" data-testid="cfg-schedules-link">
              {t("cfg.schedules_moved")} <Link to="/schedules">{t("nav.schedules")} →</Link>
            </div>
            <Field label={t("cfg.grace")}><Num v={v} k="slot_grace_minutes" set={set} /></Field>
            <div className="full"><b><Term id="retry">{t("cfg.retry")}</Term></b></div>
            <Field label={t("cfg.max_attempts")}><Num v={v} k="max_attempts" set={set} /></Field>
            <Field label={t("cfg.retry_base")}><Num v={v} k="retry_base_seconds" set={set} /></Field>
            <Field label={t("cfg.retry_max")}><Num v={v} k="retry_max_seconds" set={set} /></Field>
            <Field label={t("cfg.timeout")}><Num v={v} k="timeout_seconds" set={set} /></Field>
          </>
        )}
      </Section>
    </div>
  );
}
