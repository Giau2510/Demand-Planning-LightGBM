import { useEffect, useState } from "react";
import { get, qs } from "../api";
import { useI18n } from "../i18n";
import { DateInput, Empty, ErrorBox, Field, FilterBar, LineChart, Loading, MethodLabel, Pager, Pill, SearchInput, SourceBadge, Stat, Term,
  fmtDate, fmtNum, fmtTime, useAsync } from "./ui";
import { ActualCell, ActualNotice, ProductName } from "./forecastCells";
import { HorizonPicker } from "../pages/Dashboard";

const PAGE = 100;

/** 1.4.14: the "Tổng theo SKU × kho" view of a published SEL2 run - what the Results page showed in SEL2 mode (horizon
 *  picker, cards, daily trend, totals per SKU x FC with search / filters / pages), now a tab of the daily forecast page.
 *  Same API (GET /api/daily-forecast/sel2-summary) and same rendering, so the numbers are unchanged: forecast_used of the
 *  run, total over days 1..horizon (days from estimate_from are the weekly estimate, marked). `runId` = the run shown on
 *  the daily page; empty = the newest published SEL2 run. */
export default function Sel2Totals({ runId: runIdProp }: { runId?: string }) {
  const { t } = useI18n();
  const newest = useAsync(() => (runIdProp ? Promise.resolve(null) : get("/api/daily-forecast/sel2-runs?limit=1").catch(() => [])), [runIdProp]);
  const runId: string = runIdProp || (Array.isArray(newest.data) ? newest.data[0]?.id ?? "" : "");
  const [h, setH] = useState<number>(7);
  const [sku, setSku] = useState("");
  const [fc, setFc] = useState("");
  const [q, setQ] = useState("");          // keyword search (part of SKU / product name), sent once typing pauses
  const [qd, setQd] = useState("");
  useEffect(() => { const id = setTimeout(() => setQd(q.trim()), 300); return () => clearTimeout(id); }, [q]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [runId, h, sku, fc, qd, from, to]);

  const summary = useAsync(() => (!runId ? Promise.resolve(null)
    : get(`/api/daily-forecast/sel2-summary${qs({ run_id: runId, horizon: h, sku_id: sku, fc_id: fc, q: qd, date_from: from, date_to: to, limit: PAGE, offset: page * PAGE })}`)),
    [runId, h, sku, fc, qd, from, to, page]);

  const s = summary.data;
  const r = s?.run ?? null;
  if (!runId && (newest.loading || !newest.data)) return <Loading />;
  if (!runId) return <Empty text={t("dash.no_run")} hint={t("dash.no_run_hint")} />;

  const cov = r?.horizon_coverage;
  const horizonOptions: number[] = cov?.run_horizons ?? r?.horizons ?? [];
  const actual = s?.actual;
  const today = actual?.date;
  const estFrom: number | undefined = r?.sel2 ? r.estimate_from : undefined;
  const nFilters = [q.trim(), sku, fc, from, to].filter(Boolean).length;
  const clearFilters = () => { setQ(""); setQd(""); setSku(""); setFc(""); setFrom(""); setTo(""); };

  return (
    <div className="stack" data-testid="sel2-totals">
      <ErrorBox error={summary.error} />
      <div className="row wrap">
        {r && <HorizonPicker value={h} onChange={setH} options={horizonOptions} estimateFrom={estFrom} />}
        <span className="small muted">{t("fc.horizon_help")}</span>
      </div>
      {cov && (
        <div className="small">
          {t("hz.in_run")}: <b>{cov.run_horizons.join(", ")} {t("common.days")}</b> · {t("hz.configured")}: <b>{cov.configured.join(", ")} {t("common.days")}</b>
        </div>
      )}
      {estFrom && <p className="small" data-testid="estimate-note"><Pill status="WARNING" label={t("fc.cach.UOC_TINH_THEO_TUAN")} /> {t("fc.estimate_note")}</p>}

      {r && s && (
        <div className="grid4">
          <Stat icon="chart" label={`${t("fc.total")} (${h} ${t("common.days")}${estFrom && h >= estFrom ? ` · ${t("fc.estimate_tag")}` : ""})${nFilters ? ` · ${t("fc.filtered")}` : ""}`} value={fmtNum(s.grand_total)} sub={`${fmtDate(s.start_date)} → ${fmtDate(s.end_date)}`} />
          <Stat icon="model" label={<Term id="model_version">{t("fc.model_version")}</Term>} value={<span className="mono small">{r.model_version}</span>} sub={`${t("fc.run_id")}: ${r.id}`} />
          <Stat icon="bigquery" label={t("common.source")} value={<SourceBadge source={r.data_source} />} sub={<span className="mono small">{r.scope_key}</span>} />
          <Stat icon="clock" label={<Term id="origin">{t("fc.origin")}</Term>} value={fmtDate(r.forecast_origin)} sub={`${t("fc.data_as_of")}: ${fmtDate(r.data_as_of)} · ${t("fc.run_at")}: ${fmtTime(r.created_at)}`} />
        </div>
      )}
      {r?.lineage && (
        <p className="small muted" data-testid="lineage">
          {t("fc.lineage")}: <SourceBadge source={r.lineage.data_source} /> {r.lineage.table ?? r.lineage.batch_id ?? r.scope_key}
          {(!r.sel2 || r.lineage.train_start || r.lineage.train_end) && <>{" · "}{fmtDate(r.lineage.train_start)} → {fmtDate(r.lineage.train_end)}</>}
          {r.lineage.last_sync?.synced_at ? ` · ${t("fc.lineage_sync")} ${fmtTime(r.lineage.last_sync.synced_at)}` : ""}
        </p>
      )}

      {/* a SEL2 run has no WAPE assessment of this kind - the box keeps its place with a neutral text (no number) */}
      {r?.sel2 && <div className="alert info small" data-testid="assessment-sel2">{t("fc.sel2_no_quality")}</div>}

      {s && (
        <>
          <h4>{t("dash.trend")}</h4>
          <ActualNotice actual={actual} run={r} />
          <LineChart points={s.daily.map((d: any) => ({ x: d.target_date, y: d.total }))} forecastLegend={t("chart.forecast_legend")}
            actual={actual?.total != null && today ? { x: today, y: actual.total, legend: t("chart.actual_legend"), tooltip: `${t("actual.as_of")} ${fmtTime(actual.as_of).slice(11)}` } : null} />
        </>
      )}

      <FilterBar active={nFilters} onClear={clearFilters}>
        <Field label={t("fc.search")}>
          <SearchInput value={q} onChange={setQ} label={t("fc.search")} placeholder={t("fc.search_ph")} clearLabel={t("fc.search_clear")}
            testid="fc-search" clearTestid="fc-search-clear" />
        </Field>
        <Field label={t("fc.sku")}>
          <input list="sel2-skus" value={sku} onChange={(e) => setSku(e.target.value)} placeholder={t("common.all")} aria-label={t("fc.sku")} />
          <datalist id="sel2-skus">{r?.skus?.map((x: string) => <option key={x} value={x} />)}</datalist>
        </Field>
        <Field label={t("fc.fc")}>
          <select value={fc} onChange={(e) => setFc(e.target.value)} aria-label={t("fc.fc")}>
            <option value="">{t("common.all")}</option>
            {r?.fcs?.map((x: string) => <option key={x} value={x}>{x}</option>)}
          </select>
        </Field>
        <Field label={t("common.from")}><DateInput value={from} onChange={setFrom} ariaLabel={t("common.from")} /></Field>
        <Field label={t("common.to")}><DateInput value={to} onChange={setTo} ariaLabel={t("common.to")} /></Field>
      </FilterBar>
      {r && (
        <p className="small muted" data-testid="names-source">
          {r.data_source !== "BIGQUERY" ? t("fc.names_not_bq")
            : r.product_names?.fetched_at ? t("fc.names_source").replace("{src}", r.product_names.source).replace("{at}", fmtTime(r.product_names.fetched_at))
              .replace("{n}", fmtNum(r.product_names.skus_named)).replace("{m}", fmtNum(r.product_names.skus_local))
              : t("fc.names_never")}
        </p>
      )}
      {s && s.n_series === 0 && (qd || sku || fc) && (
        <div className="alert info small" data-testid="fc-no-results">{qd ? t("fc.no_results").replace("{q}", qd) : t("fc.no_results_filter")}
          {" "}<button className="link" onClick={clearFilters}>{t("filter.clear")}</button></div>
      )}
      {summary.loading && !s && <Loading />}
      {s && (
        <div className="scroll">
          <table className="tbl" data-testid="sel2-totals-table">
            <thead><tr><th>{t("fc.sku")}</th><th>{t("fc.product_name")}</th><th>{t("fc.fc")}</th><th className="num">{t("fc.total")} ({h} {t("common.days")})</th>
              <th className="num" title={t("actual.col_help")}>{t("actual.col_today")}{today ? ` (${today.slice(5)})` : ""}</th><th>{t("fc.method")}</th></tr></thead>
            <tbody>
              {s.series.map((x: any) => (
                <tr key={x.sku_id + x.fc_id}><td className="sku">{x.sku_id}</td><td className="pname"><ProductName name={x.product_name} /></td><td className="nowrap">{x.fc_id}</td><td className="num">{fmtNum(x.total)}</td>
                  <td className="num"><ActualCell value={x.actual_today} actual={actual} /></td>
                  <td className="small method-c"><MethodLabel code={x.method} /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={page} total={s?.n_series ?? 0} size={PAGE} unit={t("common.series")} onPage={setPage} />
    </div>
  );
}
