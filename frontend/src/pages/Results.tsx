import { useEffect, useState } from "react";
import { get, post, qs } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { AssessmentBox, Card, DateInput, Empty, ErrorBox, Field, JobProgress, LineChart, Loading, MethodLabel, SourceBadge, Stat, Term, fmtDate, fmtNum, fmtPct, fmtSignedPct, fmtTime, useAction, useAsync } from "../components/ui";
import { HorizonPicker } from "./Dashboard";
import ExplainPanel from "./ExplainPanel";

const PAGE = 100;

export function ActualCell({ value, actual }: { value: number | null | undefined; actual: any }) {
  const { t } = useI18n();
  if (value === null || value === undefined) return <span className="muted small" title={actual ? t(`actual.status.${actual.status}`) : ""}>—</span>;
  return (
    <span title={`${t("actual.as_of")} ${fmtTime(actual?.as_of)} · ${t(`actual.status.${actual?.status}`)}${actual?.is_demo ? " · DEMO" : ""}`}>
      {fmtNum(value, 1)}{actual?.status === "STALE" && <span className="warn-t"> *</span>}
    </span>
  );
}

/** 1.2.4: product name next to the SKU, or exactly "no product name yet" (never another SKU's name). */
export function ProductName({ name }: { name?: string | null }) {
  const { t } = useI18n();
  return name ? <span data-testid="product-name">{name}</span> : <span className="muted small" data-testid="product-name-missing">{t("fc.no_product_name")}</span>;
}

export function ActualNotice({ actual, run }: { actual: any; run?: any }) {
  const { t } = useI18n();
  if (!actual) return null;
  if (actual.status === "NOT_APPLICABLE") return <p className="small muted">{t("actual.status.NOT_APPLICABLE")}</p>;
  if (actual.status === "NO_DATA_TODAY") return <p className="small muted">{t("actual.none_today")}</p>;
  return (
    <div className={`alert ${actual.status === "STALE" ? "warn" : "info"} small`}>
      <b>{t("actual.title")}</b>: {t("actual.as_of")} <b>{fmtTime(actual.as_of)}</b> {t("common.vn_time")} ({t(`actual.status.${actual.status}`)})
      {actual.is_demo && <> · <span className="src src-DEMO">DEMO</span> {t("actual.demo_note")}</>}
      {actual.source_updated_max && <> · {t("actual.source_updated")}: {fmtTime(actual.source_updated_max)}</>}
      <br />{t("actual.partial_warning")}
      {run && run.data_as_of && actual.date && run.forecast_origin !== actual.date && actual.in_horizon && (
        <><br /><span className="warn-t">{t("actual.old_run_warning")} ({t("fc.data_as_of")}: {fmtDate(run.data_as_of)})</span></>
      )}
      {actual.in_horizon === false && <><br />{t("actual.not_in_horizon")}</>}
    </div>
  );
}

export default function Results() {
  const { t, lang } = useI18n();
  const runs = useAsync(() => get("/api/forecast-runs?limit=100"), []);
  const [runId, setRunId] = useState<string>("");
  const [h, setH] = useState<number>(7);
  const [sku, setSku] = useState("");
  const [fc, setFc] = useState("");
  const [q, setQ] = useState("");          // 1.2.4: keyword search (part of SKU / product name), sent once typing pauses
  const [qd, setQd] = useState("");
  useEffect(() => { const id = setTimeout(() => setQd(q.trim()), 300); return () => clearTimeout(id); }, [q]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState<"totals" | "daily">("totals");
  const [explain, setExplain] = useState<{ sku: string; fc: string; date: string } | null>(null);
  const [extendJob, setExtendJob] = useState<string | null>(null);
  const act = useAction();

  const { status: sys } = useSystem();
  // 1.2.2: the default run is the newest run of the ACTIVE source's scope - never a newer run of another source
  // (e.g. an old DEMO run while the source is BIGQUERY); such runs stay selectable, clearly labelled
  const activeRuns = (runs.data ?? []).filter((x: any) => x.active_scope !== false);
  useEffect(() => {
    if (!runId && activeRuns.length) setRunId(activeRuns[0].id);
  }, [runs.data, runId]);
  const run = useAsync(() => (runId ? get(`/api/forecast-runs/${runId}`) : Promise.resolve(null)), [runId]);
  useEffect(() => {
    if (run.data) setH(run.data.horizons?.[0] ?? run.data.max_horizon);
  }, [run.data?.id]);
  useEffect(() => setPage(0), [runId, h, sku, fc, qd, from, to, tab]);
  useEffect(() => {   // resume tracking an extension started before a reload
    get("/api/jobs/active?job_type=FORECAST_EXTEND").then((j) => { if (j?.id) setExtendJob(j.id); }).catch(() => {});
  }, []);

  const filters = { horizon: h, sku_id: sku, fc_id: fc, q: qd };
  const summary = useAsync(() => (runId ? get(`/api/forecast-runs/${runId}/summary${qs({ ...filters, limit: PAGE, offset: page * PAGE })}`) : Promise.resolve(null)),
    [runId, h, sku, fc, qd, page]);
  const daily = useAsync(() => (runId && tab === "daily" ? get(`/api/forecast-runs/${runId}/values${qs({ ...filters, date_from: from, date_to: to, limit: PAGE, offset: page * PAGE })}`) : Promise.resolve(null)),
    [runId, h, sku, fc, qd, from, to, page, tab]);
  const acc = useAsync(() => (runId ? get(`/api/forecast-runs/${runId}/accuracy`) : Promise.resolve(null)), [runId]);

  const extend = async () => {
    const j = await act.run(() => post(`/api/forecast-runs/${runId}/extend`));
    if (j) setExtendJob(j.id);
  };
  const onExtendDone = (j: any) => {
    runs.reload();
    const newId = j.result?.result?.forecast_run_id;
    if (newId) setRunId(newId);
  };

  if (runs.loading && !runs.data) return <Loading />;   // a reload must not unmount the page (job progress)
  if (!runs.data?.length) return <div className="stack"><h2>{t("nav.results")}</h2><Empty text={t("dash.no_run")} /></div>;
  const r = run.data;
  const s = summary.data;
  const cov = r?.horizon_coverage;
  const horizonOptions: number[] = cov?.run_horizons ?? (r ? [r.max_horizon] : []);
  const total = tab === "totals" ? s?.n_series ?? 0 : daily.data?.total ?? 0;
  const actual = s?.actual;
  const today = actual?.date;

  return (
    <div className="stack">
      <h2>{t("nav.results")}</h2>
      <ErrorBox error={runs.error || run.error || summary.error || daily.error || act.error} />
      {!activeRuns.length && (
        <div className="alert warn" data-testid="no-run-active">{t("fc.no_run_active").replace("{src}", sys?.active_source ?? "—")}</div>
      )}
      {r && r.active_scope === false && (
        <div className="alert warn" data-testid="other-source-run">
          {t("fc.other_source_warn").replace("{run}", r.data_source).replace("{active}", sys?.active_source ?? "—")}
        </div>
      )}
      <Card>
        <div className="row wrap">
          <Field label={t("fc.select_run")}>
            <select value={runId} onChange={(e) => setRunId(e.target.value)} data-testid="run-select">
              {!runId && <option value="">{t("fc.pick_run")}</option>}
              {runs.data.map((x: any) => (
                <option key={x.id} value={x.id}>{fmtTime(x.created_at)} · {x.data_source}{x.active_scope === false ? ` (${t("fc.other_source")})` : ""} · {x.model_version} · {(x.horizons ?? []).join("/")} {t("common.days")}{x.derived_from_run_id ? ` · ${t("fc.extended")}` : ""}{x.assessment?.usage === "USABLE_WITH_WARNING" ? ` · ⚠ ${t("fc.below_tag")}` : ""}</option>
              ))}
            </select>
          </Field>
          {r && <HorizonPicker value={h} onChange={setH} options={horizonOptions} />}
          <Field label={t("fc.search")}>
            <span className="row">
              <input data-testid="fc-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("fc.search_ph")} aria-label={t("fc.search")} />
              {q && <button className="small" data-testid="fc-search-clear" onClick={() => setQ("")} aria-label={t("fc.search_clear")}>✕</button>}
            </span>
          </Field>
          <Field label={t("fc.sku")}>
            <input list="skus" value={sku} onChange={(e) => setSku(e.target.value)} placeholder={t("common.all")} />
            <datalist id="skus">{r?.skus?.map((x: string) => <option key={x} value={x} />)}</datalist>
          </Field>
          <Field label={t("fc.fc")}>
            <select value={fc} onChange={(e) => setFc(e.target.value)}>
              <option value="">{t("common.all")}</option>
              {r?.fcs?.map((x: string) => <option key={x} value={x}>{x}</option>)}
            </select>
          </Field>
          {tab === "daily" && (
            <>
              <Field label={t("common.from")}><DateInput value={from} onChange={setFrom} ariaLabel={t("common.from")} /></Field>
              <Field label={t("common.to")}><DateInput value={to} onChange={setTo} ariaLabel={t("common.to")} /></Field>
            </>
          )}
          {r && <a className="btn" href={`/api/forecast-runs/${runId}/export.xlsx?horizon=${h}&lang=${lang}`}>{t("fc.export")} ({lang.toUpperCase()})</a>}
        </div>
        <p className="small muted">{t("fc.horizon_help")}</p>
        {cov && (
          <div className="small">
            {t("hz.in_run")}: <b>{cov.run_horizons.join(", ")} {t("common.days")}</b> · {t("hz.configured")}: <b>{cov.configured.join(", ")} {t("common.days")}</b>
          </div>
        )}
        {cov && cov.configured_missing_in_run.length > 0 && (
          <div className="alert warn small" data-testid="horizon-missing">
            {t("hz.missing").replace("{h}", cov.configured_missing_in_run.join(", "))}
            {cov.can_extend_without_retraining
              ? <> {t("hz.can_extend")} <button className="primary" onClick={extend} disabled={act.busy || !!extendJob}>{t("hz.extend_btn")}</button></>
              : <> <span>{t("hz.cannot_extend")}</span> <code className="code">{cov.cannot_extend_reason}</code></>}
          </div>
        )}
        {extendJob && <JobProgress jobId={extendJob} onDone={onExtendDone} />}
      </Card>

      {r && s && (
        <div className="grid4">
          <Stat label={`${t("fc.total")} (${h} ${t("common.days")})`} value={fmtNum(s.grand_total)} sub={`${fmtDate(s.start_date)} → ${fmtDate(s.end_date)}`} />
          <Stat label={<Term id="model_version">{t("fc.model_version")}</Term>} value={<span className="mono small">{r.model_version}</span>} sub={`${t("fc.run_id")}: ${r.id}`} />
          <Stat label={t("common.source")} value={<SourceBadge source={r.data_source} />} sub={<span className="mono small">{r.scope_key}</span>} />
          <Stat label={<Term id="origin">{t("fc.origin")}</Term>} value={fmtDate(r.forecast_origin)} sub={`${t("fc.data_as_of")}: ${fmtDate(r.data_as_of)} · ${t("fc.run_at")}: ${fmtTime(r.created_at)}`} />
        </div>
      )}
      {r?.lineage && (
        <p className="small muted" data-testid="lineage">
          {t("fc.lineage")}: <SourceBadge source={r.lineage.data_source} /> {r.lineage.table ?? r.lineage.batch_id ?? r.scope_key}
          {" · "}{fmtDate(r.lineage.train_start)} → {fmtDate(r.lineage.train_end)}
          {r.lineage.last_sync?.synced_at ? ` · ${t("fc.lineage_sync")} ${fmtTime(r.lineage.last_sync.synced_at)}` : ""}
        </p>
      )}
      {r?.assessment && <AssessmentBox a={r.assessment} />}

      {s && (
        <Card title={t("dash.trend")}>
          <ActualNotice actual={actual} run={r} />
          <LineChart points={s.daily.map((d: any) => ({ x: d.target_date, y: d.total }))} forecastLegend={t("chart.forecast_legend")}
            actual={actual?.total != null && today ? { x: today, y: actual.total, legend: t("chart.actual_legend"), tooltip: `${t("actual.as_of")} ${fmtTime(actual.as_of).slice(11)}` } : null} />
        </Card>
      )}

      <Card>
        <div className="tabs">
          <button className={tab === "totals" ? "tab active" : "tab"} onClick={() => setTab("totals")}>{t("fc.totals")}</button>
          <button className={tab === "daily" ? "tab active" : "tab"} onClick={() => setTab("daily")}>{t("fc.daily_detail")}</button>
        </div>
        {r && (
          <p className="small muted" data-testid="names-source">
            {r.data_source !== "BIGQUERY" ? t("fc.names_not_bq")
              : r.product_names?.fetched_at ? t("fc.names_source").replace("{src}", r.product_names.source).replace("{at}", fmtTime(r.product_names.fetched_at))
                .replace("{n}", fmtNum(r.product_names.skus_named)).replace("{m}", fmtNum(r.product_names.skus_local))
              : t("fc.names_never")}
          </p>
        )}
        {total === 0 && (qd || sku || fc) && (tab === "totals" ? s : daily.data) && (
          <div className="alert info small" data-testid="fc-no-results">{qd ? t("fc.no_results").replace("{q}", qd) : t("fc.no_results_filter")}</div>
        )}
        {tab === "totals" && s && (
          <div className="scroll">
            <table className="tbl">
              <thead><tr><th>{t("fc.sku")}</th><th>{t("fc.product_name")}</th><th>{t("fc.fc")}</th><th className="num">{t("fc.total")} ({h} {t("common.days")})</th>
                <th className="num" title={t("actual.col_help")}>{t("actual.col_today")}{today ? ` (${today.slice(5)})` : ""}</th><th>{t("fc.method")}</th><th></th></tr></thead>
              <tbody>
                {s.series.map((x: any) => (
                  <tr key={x.sku_id + x.fc_id}><td>{x.sku_id}</td><td><ProductName name={x.product_name} /></td><td>{x.fc_id}</td><td className="num">{fmtNum(x.total, 1)}</td>
                    <td className="num"><ActualCell value={x.actual_today} actual={actual} /></td>
                    <td className="small"><MethodLabel code={x.method} /></td>
                    <td><button className="link" onClick={() => setExplain({ sku: x.sku_id, fc: x.fc_id, date: s.start_date })}>{t("ex.open")}</button></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "daily" && daily.data && (
          <div className="scroll">
            <table className="tbl">
              <thead><tr><th>{t("fc.sku")}</th><th>{t("fc.product_name")}</th><th>{t("fc.fc")}</th><th>{t("fc.date")}</th><th className="num">{t("fc.day_n")}</th><th className="num">{t("fc.qty")}</th>
                <th className="num" title={t("actual.col_help")}>{t("actual.col_so_far")}</th><th>{t("fc.method")}</th><th></th></tr></thead>
              <tbody>
                {daily.data.rows.map((x: any) => (
                  <tr key={x.sku_id + x.fc_id + x.target_date}><td>{x.sku_id}</td><td><ProductName name={x.product_name} /></td><td>{x.fc_id}</td><td>{fmtDate(x.target_date)}</td><td className="num">{x.horizon_day}</td><td className="num">{fmtNum(x.yhat, 2)}</td>
                    <td className="num"><ActualCell value={x.actual_today} actual={daily.data.actual} /></td>
                    <td className="small"><MethodLabel code={x.method} /></td>
                    <td><button className="link" onClick={() => setExplain({ sku: x.sku_id, fc: x.fc_id, date: x.target_date })}>{t("ex.open")}</button></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="row pager">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>← {t("common.prev")}</button>
          <span className="small">{t("common.page")} {page + 1} / {Math.max(1, Math.ceil(total / PAGE))} · {fmtNum(total)} {tab === "totals" ? t("common.series") : t("common.rows")}</span>
          <button disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>{t("common.next")} →</button>
        </div>
      </Card>

      <Card title={t("fc.accuracy")}>
        {!acc.data?.available ? <Empty text={t("fc.no_actuals")} /> : (
          <table className="tbl">
            <thead><tr><th>{t("fc.horizon")}</th><th className="num"><Term id="wape">WAPE</Term></th><th className="num"><Term id="mae">MAE</Term></th><th className="num"><Term id="bias">Bias</Term></th><th className="num">{t("perf.points")}</th></tr></thead>
            <tbody>
              {acc.data.by_horizon.map((m: any) => (
                <tr key={m.horizon}><td>{m.horizon} {t("common.days")}</td><td className="num">{fmtPct(m.wape)}</td><td className="num">{fmtNum(m.mae, 2)}</td><td className="num">{fmtSignedPct(m.bias)}</td><td className="num">{m.n_points}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {explain && r && <ExplainPanel runId={r.id} sku={explain.sku} fc={explain.fc} date={explain.date} maxHorizon={r.max_horizon}
        origin={r.forecast_origin} onClose={() => setExplain(null)} />}
    </div>
  );
}
