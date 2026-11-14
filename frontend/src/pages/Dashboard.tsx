import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get, post } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { AssessmentBox, Bars, Card, Code, Empty, ErrorBox, JobProgress, LineChart, Loading, MethodLabel, OkBox, PageHeader, Pill, SourceBadge, Stat, Term, fmtDate, fmtNum, fmtPct, fmtSignedPct, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";
import ForecastInfoLine from "../components/ForecastInfoLine";
import LegacyDataBanner from "../components/LegacyDataBanner";

/** 1.4.6: estimateFrom (SEL2 run: 8) marks the periods that include the weekly-estimate days 8..20 of the daily Excel. */
export function HorizonPicker({ value, onChange, options, estimateFrom }: { value: number; onChange: (h: number) => void; options: number[]; estimateFrom?: number }) {
  const { t } = useI18n();
  return (
    <label className="row" title={t("fc.horizon_help")}>
      <span className="small">{t("fc.horizon")}</span>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))} data-testid="horizon-picker">
        {options.map((h) => <option key={h} value={h}>{h} {t("common.days")}{estimateFrom && h >= estimateFrom ? ` (${t("fc.estimate_tag")})` : ""}</option>)}
      </select>
    </label>
  );
}

/** 1.4.12: the SEL2 runs cover the 20 days of the daily Excel (1..7 SEL2, 8..20 weekly estimate); the summary refuses more. */
const SEL2_MAX_HORIZON = 20;

/** The SEL2 summary in the shape the forecast block renders (the 1.3.x summary): the numbers are the API's, unchanged.
 *  The method table has one row per "cach_tinh" (SEL2 days / weekly-estimate days) with the exact totals from the daily
 *  totals: the API gives the methods of the SKU x FC series only page by page, never counts over all series. */
function sel2View(d: any, horizon: number) {
  if (!d?.run || d.horizon !== horizon) return null;
  const by = new Map<string, number>();
  for (const x of d.daily ?? []) by.set(x.cach_tinh, (by.get(x.cach_tinh) ?? 0) + x.total);
  return {
    run_id: d.run.id, horizon: d.horizon, grand_total: d.grand_total, n_series: d.n_series, start_date: d.start_date, end_date: d.end_date,
    forecast_origin: d.run.forecast_date, data_as_of: d.run.data_as_of, data_source: d.run.data_source, actual: d.actual,
    daily: d.daily ?? [], series: (d.series ?? []).slice(0, 10),
    methods: Array.from(by, ([method, total]) => ({ method, n_series: d.n_series, total })),
  };
}

export default function Dashboard() {
  const { t, pick } = useI18n();
  const sys = useSystem();
  const settings = useAsync(() => get("/api/settings"), []);
  const [h, setH] = useState<number | null>(null);
  const enabled: number[] = settings.data?.horizons?.enabled ?? [7, 15, 30];
  const horizon = h ?? enabled[0];
  // 1.2.7: the page renders at once and each part fills in as its data arrives. The system status is the shell's,
  // asked again when the page opens (sharing the shell's request while it runs, never computed twice); the forecast
  // card loads the run's summary on its own (same figures as /api/dashboard: horizon capped at the run's maximum).
  const [statusReady, setStatusReady] = useState(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { sys.refresh().finally(() => setStatusReady(true)); }, []);
  const s = statusReady && !sys.error ? sys.status : null;
  const run = s?.latest_forecast_run;
  const hRun = run ? Math.min(horizon, run.max_horizon) : null;
  // 1.4.12: with a published SEL2 run (detected exactly as the Results page does: the list of SEL2 runs is not empty) every
  // forecast number of the block comes from the SEL2 summary = forecast_used of the daily Excel; the legacy run is only
  // asked for when there is no SEL2 run (DEMO / manual import / before the first SEL2 run)
  // asked again whenever the status is (sys.reload after a job / action); sel2Pending = the first answer is not in yet
  const sel2Runs = useAsync(() => get("/api/daily-forecast/sel2-runs?limit=1").catch(() => []), [s]);
  const sel2Pending = sel2Runs.loading && !sel2Runs.data;
  const sel2 = Array.isArray(sel2Runs.data) && sel2Runs.data.length > 0;
  const sel2Run: any = sel2 ? (sel2Runs.data as any[])[0] : null;
  const sel2H = Math.min(horizon, SEL2_MAX_HORIZON);
  const fc = useAsync(() => (run && !settings.loading && !sel2Pending && !sel2
    ? get(`/api/forecast-runs/${encodeURIComponent(run.id)}/summary?horizon=${hRun}&limit=10`) : Promise.resolve(null)),
    [run?.id, hRun, settings.loading, s, sel2Pending, sel2]);
  const sf = useAsync(() => (sel2 && !settings.loading
    ? get(`/api/daily-forecast/sel2-summary?horizon=${sel2H}&limit=10`) : Promise.resolve(null)),
    [sel2, sel2H, settings.loading, s]);
  const act = useAction();
  const [force, setForce] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobActive, setJobActive] = useState(false);
  const [alreadyActive, setAlreadyActive] = useState(false);
  useEffect(() => {   // after a reload, re-attach to a job that is still queued/running on the backend
    get("/api/jobs/active?job_type=TRAIN_PUBLISH").then((j) => { if (j?.id) { setJobId(j.id); setJobActive(true); } }).catch(() => {});
  }, []);

  const train = async () => {
    const r = await act.run(() => post("/api/training/run", { force }));
    if (r) { setJobId(r.id); setJobActive(true); setAlreadyActive(!!r.already_active); }   // UI reacts as soon as the backend has accepted the job
  };
  const onJobDone = () => {
    setJobActive(false);
    sys.reload();
  };
  const demo = async () => {
    await act.run(() => post("/api/demo/generate", {}), t("common.saved"));
    sys.reload();
  };
  const ackAll = async () => {
    await act.run(() => post("/api/alerts/ack-all"));
    sys.reload();
  };

  // a part that needs the status: loading while this visit's status (or a newer request) is on its way; "not available"
  // only once loading stopped without a status (the shell shows the error)
  const waiting = statusReady && !sys.loading ? <Empty text={t("common.not_available")} /> : <Loading />;
  const f = sel2 ? sel2View(sf.data, sel2H) : fc.data && fc.data.run_id === run?.id ? fc.data : null;
  const shownRun: any = sel2Pending ? null : sel2 ? sel2Run : run;   // the run of the "model version" card ("—" until SEL2 is known)
  const fresh = s?.freshness;
  const latest = s?.latest_training_attempt;
  const accepted = s?.latest_accepted_training;
  const fs = s?.forecast_state;
  const rejectedLatest = latest && run && latest.status !== "ACCEPTED" && latest.id !== run.training_run_id;

  return (
    <div className="stack">
      <PageHeader icon="dashboard" title={t("nav.dashboard")} desc={t("page.dashboard.desc")} actions={<>
        {s?.active_source === "DEMO" && <button onClick={demo} disabled={act.busy}><Icon name="demo" />{t("dash.generate_demo")}</button>}
        <label className="row small"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />{t("dash.train_force")}</label>
        <button className="primary" onClick={train} disabled={act.busy || jobActive || !s?.scope}>
          <Icon name={jobActive ? "running" : "model"} className={jobActive ? "spin" : undefined} />{jobActive ? t("common.running") : t("dash.train_now")}</button>
      </>} />
      {/* 1.4.12: no banner once the figures are the SEL2 ones; while the SEL2 run list is still loading none either (no flicker) */}
      {!sel2 && !sel2Pending && <LegacyDataBanner />}
      <ForecastInfoLine />
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      {jobId && alreadyActive && jobActive && <div className="alert info small">{t("job.already_active")}</div>}
      {jobId && <JobProgress jobId={jobId} onDone={onJobDone} />}

      {!s ? waiting : (
        <div className="grid4">
          <Stat icon="bigquery" label={t("common.source")} value={<SourceBadge source={s.active_source} />} sub={s.scope?.label ?? t("source.no_dataset")} />
          <Stat icon="calendar" label={<Term id="freshness">{t("dash.data_latest")}</Term>} value={fmtDate(fresh?.max_date)}
            sub={fresh?.lag_days !== undefined ? `${t("dash.lag")}: ${fresh.lag_days} ${t("common.days")}` : undefined} />
          <Stat icon="quality" label={t("dash.data_status")}
            value={!s.scope ? <Pill status="NEEDS_CONFIG" /> : fresh?.stale ? <Pill status="STALE" /> : <Pill status="FRESH" />}
            sub={fresh?.stale && !fresh?.stale_enforced ? (t("common.source") + ": " + s.active_source + " — " + (pick({ vi: "không chặn publish", en: "does not block publishing" }))) : undefined} tone={fresh?.stale ? "warn" : ""} />
          <Stat icon="model" label={<Term id="model_version">{t("fc.model_version")}</Term>} value={<span className="mono small">{shownRun?.model_version ?? "—"}</span>}
            sub={shownRun ? `${t("fc.run_at")}: ${fmtTime(shownRun.created_at)}` : undefined} />
        </div>
      )}

      {s?.data_window && (
        <p className="small muted" data-testid="dash-window">
          {t("dash.window")}: <b>{fmtDate(s.data_window.start)} → {fmtDate(s.data_window.end)}</b>
          {fresh?.window_rows !== undefined ? ` · ${fmtNum(fresh.window_rows)} ${t("common.rows")}` : ""} — {t("dash.window_rule")}
          {s.data_window.start_rule === "OPEN_HOURS_COVERAGE" && <span data-testid="dash-window-rule"> {t("dash.window_open_hours")}</span>}
        </p>
      )}

      {rejectedLatest && latest.reject_reason === "PROMOTION_REVIEW_REQUIRED" ? (
        <div className="alert info" data-testid="dash-candidate">
          <b>{t("dash.candidate_waiting")}</b> <Link to="/performance">{t("dash.review_candidate")}</Link>
        </div>
      ) : rejectedLatest && (
        <div className="alert warn">
          <b>{t("dash.kept_previous")}</b> {t("perf.reject_reason")}: <Code code={latest.reject_reason || latest.status} />
        </div>
      )}

      <Card icon="results" title={t("dash.latest_run")} actions={f && (sel2
        ? <HorizonPicker value={sel2H} onChange={setH} estimateFrom={sf.data?.run?.estimate_from ?? 8} options={Array.from(new Set([...enabled.map((x) => Math.min(x, SEL2_MAX_HORIZON)), sel2H])).sort((a, b) => a - b)} />
        : <HorizonPicker value={Math.min(horizon, run?.max_horizon ?? horizon)} onChange={setH} options={Array.from(new Set([...(run?.horizons ?? []), run?.max_horizon].filter(Boolean))).sort((a: any, b: any) => a - b) as number[]} />)}>
        {!s ? waiting : sel2Pending ? <Loading /> : sel2 && sf.error ? <ErrorBox error={sf.error} />
        : sel2 && !f ? (sf.loading || !sf.data ? <Loading /> : <Empty text={t("dash.no_run")} hint={t("dash.no_run_hint")} />)
        : !sel2 && !run && fs?.status === "NO_FORECAST_FOR_ACTIVE_SOURCE" ? (
          <div className="alert warn" data-testid="dash-no-forecast">
            <b>{t("dash.no_fc_active").replace("{src}", s.active_source ?? "—")}</b>
            {fs.latest_attempt && (
              <p className="small">{t("dash.no_fc_last")}: <span className="mono">{fs.latest_attempt.id}</span> <Pill status={fs.latest_attempt.status} />{" "}
                {fs.latest_attempt.reject_reason && <Code code={fs.latest_attempt.reject_reason} />}</p>
            )}
            {fs.latest_attempt?.promotable?.ok && <p className="small">{t("dash.no_fc_promotable")} <Link to="/performance">{t("nav.performance")} →</Link></p>}
            <p className="small">{t("dash.no_fc_train").replace("{src}", s.active_source ?? "—")}</p>
            {fs.other_source_runs > 0 && <p className="small muted">{t("dash.no_fc_other").replace("{n}", String(fs.other_source_runs))}</p>}
          </div>
        ) : !sel2 && !run ? <Empty text={t("dash.no_run")} hint={t("dash.no_run_hint")} />
          : !sel2 && fc.error ? <ErrorBox error={fc.error} />
          : !f ? <Loading /> : (
          <>
            {sel2 ? <div className="alert info small" data-testid="assessment-sel2">{t("fc.sel2_no_quality")}</div>
              : fs?.model_in_use && <AssessmentBox a={fs.model_in_use} compact />}
            <div className="grid4">
              <Stat icon="chart" label={`${t("dash.horizon_total")} (${f.horizon} ${t("common.days")})`} value={fmtNum(f.grand_total)} sub={`${fmtNum(f.n_series)} ${t("common.series")}`} />
              <Stat icon="calendar" label={`${t("fc.start")} → ${t("fc.end")}`} value={<span className="small">{fmtDate(f.start_date)} → {fmtDate(f.end_date)}</span>} />
              <Stat icon="clock" label={<Term id="origin">{t("fc.origin")}</Term>} value={fmtDate(f.forecast_origin)} sub={`${t("fc.data_as_of")}: ${fmtDate(f.data_as_of)}`} />
              <Stat icon="file" label={t("fc.run_id")} value={<span className="mono small">{f.run_id}</span>} sub={<SourceBadge source={f.data_source} />} />
            </div>
            {!sel2 && run && enabled.some((x) => x > run.max_horizon) && (
              <div className="alert warn small">{t("hz.missing").replace("{h}", enabled.filter((x) => x > run.max_horizon).join(", "))} <Link to="/results">{t("nav.results")} →</Link></div>
            )}
            <h4>{t("dash.trend")}</h4>
            {f.actual && f.actual.status !== "NO_DATA_TODAY" && f.actual.status !== "NOT_APPLICABLE" && (
              <p className="small">{t("actual.title")}: {t("actual.as_of")} <b>{fmtTime(f.actual.as_of)}</b> {t("common.vn_time")} ({t(`actual.status.${f.actual.status}`)}){f.actual.is_demo ? " · DEMO" : ""} — {t("actual.partial_warning")}</p>
            )}
            {f.actual?.status === "NO_DATA_TODAY" && <p className="small muted">{t("actual.none_today")}</p>}
            {f.forecast_origin !== f.actual?.date && f.actual?.in_horizon && <p className="small warn-t">{t("actual.old_run_warning")} ({t("fc.data_as_of")}: {fmtDate(f.data_as_of)})</p>}
            <LineChart points={f.daily.map((d: any) => ({ x: d.target_date, y: d.total }))} label={t("dash.trend")} forecastLegend={t("chart.forecast_legend")}
              actual={f.actual?.total != null ? { x: f.actual.date, y: f.actual.total, legend: t("chart.actual_legend"), tooltip: `${t("actual.as_of")} ${fmtTime(f.actual.as_of).slice(11)}` } : null} />
            <div className="grid2">
              <div>
                <h4>{t("dash.top_series")}</h4>
                <Bars items={f.series.map((x: any) => ({ label: `${x.sku_id} · ${x.fc_id}${x.product_name ? ` · ${x.product_name}` : ""}`, value: x.total }))} />
              </div>
              <div>
                <h4><Term id="fallback">{t("dash.methods")}</Term></h4>
                <table className="tbl">
                  <thead><tr><th>{sel2 ? t("fc.cach_tinh") : t("fc.method")}</th><th className="num">{t("common.series")}</th><th className="num">{t("fc.total")}</th></tr></thead>
                  <tbody>
                    {f.methods.map((m: any) => (
                      <tr key={m.method}><td>{sel2 ? <span data-testid="dash-cach-tinh">{t(`fc.cach.${m.method}`)}</span> : <MethodLabel code={m.method} />}</td><td className="num">{fmtNum(m.n_series)}</td><td className="num">{fmtNum(m.total)}</td></tr>
                    ))}
                  </tbody>
                </table>
                <p><Link to="/results">{t("nav.results")} →</Link></p>
              </div>
            </div>
          </>
        )}
      </Card>

      <div className="grid2">
        <Card icon="performance" title={<Term id="quality_gate">{t("dash.model_quality")}</Term>}>
          {!s ? waiting : !accepted ? <Empty text={t("common.not_available")} hint={t("dash.no_model_hint")} /> : (
            <div className="grid3">
              <Stat label={<Term id="wape">WAPE</Term>} value={fmtPct(accepted.metrics?.wape)} />
              <Stat label={<Term id="mae">MAE</Term>} value={fmtNum(accepted.metrics?.mae, 2)} />
              <Stat label={<Term id="bias">Bias</Term>} value={fmtSignedPct(accepted.metrics?.bias)} />
            </div>
          )}
          {latest && (
            <p className="small">
              {t("dash.last_attempt")}: <Pill status={latest.status} /> {fmtTime(latest.started_at)} {latest.reject_reason && <Code code={latest.reject_reason} />}
              {" "}<Link to="/performance">{t("common.details")} →</Link>
            </p>
          )}
        </Card>
        <Card icon="jobs" title={t("dash.jobs")}>
          {!s ? waiting : (
            <>
              <table className="tbl">
                <thead><tr><th>{t("job.type")}</th><th>{t("common.status")}</th><th>{t("job.finished")}</th><th>{t("job.reason")}</th></tr></thead>
                <tbody>
                  {Object.entries(s.latest_jobs ?? {}).map(([jt, j]: [string, any]) => (
                    <tr key={jt}>
                      <td>{t(`job.${jt}`)}</td>
                      <td>{j ? <Pill status={j.status} /> : "—"}</td>
                      <td className="small">{j ? fmtTime(j.finished_at || j.created_at) : ""}</td>
                      <td className="small"><Code code={j?.reason_code} showCode={false} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">{s.scheduler?.running ? t("job.sched_running") : t("job.sched_stopped")} · <Link to="/jobs">{t("nav.jobs")} →</Link></p>
            </>
          )}
        </Card>
      </div>

      <Card icon="alerts" title={t("dash.alerts")} actions={s?.alerts?.length ? <button onClick={ackAll}><Icon name="ack" />{t("dash.ack_all")}</button> : null}>
        {!s ? waiting : !s.alerts?.length ? <Empty icon="ok" text={t("dash.no_alerts")} /> : (
          <ul className="alerts">
            {s.alerts.map((a: any) => (
              <li key={a.id} className={`lvl-${a.level}`}>
                <span className="small">{fmtTime(a.created_at)}</span> <Pill status={a.level} /> <Code code={a.code} />
                <span className="small mono"> {a.entity_id ?? ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
