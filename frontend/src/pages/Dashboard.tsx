import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get, post } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { AssessmentBox, Bars, Card, Code, Empty, ErrorBox, JobProgress, LineChart, Loading, MethodLabel, OkBox, PageHeader, Pill, SourceBadge, Stat, Term, fmtDate, fmtNum, fmtPct, fmtSignedPct, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

export function HorizonPicker({ value, onChange, options }: { value: number; onChange: (h: number) => void; options: number[] }) {
  const { t } = useI18n();
  return (
    <label className="row" title={t("fc.horizon_help")}>
      <span className="small">{t("fc.horizon")}</span>
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {options.map((h) => <option key={h} value={h}>{h} {t("common.days")}</option>)}
      </select>
    </label>
  );
}

export default function Dashboard() {
  const { t, pick } = useI18n();
  const sys = useSystem();
  const settings = useAsync(() => get("/api/settings"), []);
  const [h, setH] = useState<number | null>(null);
  const enabled: number[] = settings.data?.horizons?.enabled ?? [7, 15, 30];
  const horizon = h ?? enabled[0];
  const dash = useAsync(() => get(`/api/dashboard?horizon=${horizon}`), [horizon]);
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
    dash.reload();
    sys.reload();
  };
  const demo = async () => {
    await act.run(() => post("/api/demo/generate", {}), t("common.saved"));
    dash.reload();
    sys.reload();
  };
  const ackAll = async () => {
    await act.run(() => post("/api/alerts/ack-all"));
    dash.reload();
  };

  if (dash.loading && !dash.data) return <div className="stack"><PageHeader icon="dashboard" title={t("nav.dashboard")} desc={t("page.dashboard.desc")} /><Loading /></div>;
  const s = dash.data?.system;
  const f = dash.data?.forecast;
  const fresh = s?.freshness;
  const latest = s?.latest_training_attempt;
  const accepted = s?.latest_accepted_training;
  const run = s?.latest_forecast_run;
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
      <ErrorBox error={act.error || dash.error} />
      <OkBox text={act.ok} />
      {jobId && alreadyActive && jobActive && <div className="alert info small">{t("job.already_active")}</div>}
      {jobId && <JobProgress jobId={jobId} onDone={onJobDone} />}

      <div className="grid4">
        <Stat icon="bigquery" label={t("common.source")} value={<SourceBadge source={s?.active_source} />} sub={s?.scope?.label ?? t("source.no_dataset")} />
        <Stat icon="calendar" label={<Term id="freshness">{t("dash.data_latest")}</Term>} value={fmtDate(fresh?.max_date)}
          sub={fresh?.lag_days !== undefined ? `${t("dash.lag")}: ${fresh.lag_days} ${t("common.days")}` : undefined} />
        <Stat icon="quality" label={t("dash.data_status")}
          value={!s?.scope ? <Pill status="NEEDS_CONFIG" /> : fresh?.stale ? <Pill status="STALE" /> : <Pill status="FRESH" />}
          sub={fresh?.stale && !fresh?.stale_enforced ? (t("common.source") + ": " + s?.active_source + " — " + (pick({ vi: "không chặn publish", en: "does not block publishing" }))) : undefined} tone={fresh?.stale ? "warn" : ""} />
        <Stat icon="model" label={<Term id="model_version">{t("fc.model_version")}</Term>} value={<span className="mono small">{run?.model_version ?? "—"}</span>}
          sub={run ? `${t("fc.run_at")}: ${fmtTime(run.created_at)}` : undefined} />
      </div>

      {s?.data_window && (
        <p className="small muted" data-testid="dash-window">
          {t("dash.window")}: <b>{fmtDate(s.data_window.start)} → {fmtDate(s.data_window.end)}</b>
          {fresh?.window_rows !== undefined ? ` · ${fmtNum(fresh.window_rows)} ${t("common.rows")}` : ""} — {t("dash.window_rule")}
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

      <Card icon="results" title={t("dash.latest_run")} actions={f && <HorizonPicker value={Math.min(horizon, run?.max_horizon ?? horizon)} onChange={setH} options={Array.from(new Set([...(run?.horizons ?? []), run?.max_horizon].filter(Boolean))).sort((a: any, b: any) => a - b) as number[]} />}>
        {!f && fs?.status === "NO_FORECAST_FOR_ACTIVE_SOURCE" ? (
          <div className="alert warn" data-testid="dash-no-forecast">
            <b>{t("dash.no_fc_active").replace("{src}", s?.active_source ?? "—")}</b>
            {fs.latest_attempt && (
              <p className="small">{t("dash.no_fc_last")}: <span className="mono">{fs.latest_attempt.id}</span> <Pill status={fs.latest_attempt.status} />{" "}
                {fs.latest_attempt.reject_reason && <Code code={fs.latest_attempt.reject_reason} />}</p>
            )}
            {fs.latest_attempt?.promotable?.ok && <p className="small">{t("dash.no_fc_promotable")} <Link to="/performance">{t("nav.performance")} →</Link></p>}
            <p className="small">{t("dash.no_fc_train").replace("{src}", s?.active_source ?? "—")}</p>
            {fs.other_source_runs > 0 && <p className="small muted">{t("dash.no_fc_other").replace("{n}", String(fs.other_source_runs))}</p>}
          </div>
        ) : !f ? <Empty text={t("dash.no_run")} hint={t("dash.no_run_hint")} /> : (
          <>
            {fs?.model_in_use && <AssessmentBox a={fs.model_in_use} compact />}
            <div className="grid4">
              <Stat icon="chart" label={`${t("dash.horizon_total")} (${f.horizon} ${t("common.days")})`} value={fmtNum(f.grand_total)} sub={`${fmtNum(f.n_series)} ${t("common.series")}`} />
              <Stat icon="calendar" label={`${t("fc.start")} → ${t("fc.end")}`} value={<span className="small">{fmtDate(f.start_date)} → {fmtDate(f.end_date)}</span>} />
              <Stat icon="clock" label={<Term id="origin">{t("fc.origin")}</Term>} value={fmtDate(f.forecast_origin)} sub={`${t("fc.data_as_of")}: ${fmtDate(f.data_as_of)}`} />
              <Stat icon="file" label={t("fc.run_id")} value={<span className="mono small">{run.id}</span>} sub={<SourceBadge source={f.data_source} />} />
            </div>
            {enabled.some((x) => x > run.max_horizon) && (
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
                  <thead><tr><th>{t("fc.method")}</th><th className="num">{t("common.series")}</th><th className="num">{t("fc.total")}</th></tr></thead>
                  <tbody>
                    {f.methods.map((m: any) => (
                      <tr key={m.method}><td><MethodLabel code={m.method} /></td><td className="num">{fmtNum(m.n_series)}</td><td className="num">{fmtNum(m.total)}</td></tr>
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
          {!accepted ? <Empty text={t("common.not_available")} hint={t("dash.no_model_hint")} /> : (
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
          <table className="tbl">
            <thead><tr><th>{t("job.type")}</th><th>{t("common.status")}</th><th>{t("job.finished")}</th><th>{t("job.reason")}</th></tr></thead>
            <tbody>
              {Object.entries(s?.latest_jobs ?? {}).map(([jt, j]: [string, any]) => (
                <tr key={jt}>
                  <td>{t(`job.${jt}`)}</td>
                  <td>{j ? <Pill status={j.status} /> : "—"}</td>
                  <td className="small">{j ? fmtTime(j.finished_at || j.created_at) : ""}</td>
                  <td className="small"><Code code={j?.reason_code} showCode={false} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">{s?.scheduler?.running ? t("job.sched_running") : t("job.sched_stopped")} · <Link to="/jobs">{t("nav.jobs")} →</Link></p>
        </Card>
      </div>

      <Card icon="alerts" title={t("dash.alerts")} actions={s?.alerts?.length ? <button onClick={ackAll}><Icon name="ack" />{t("dash.ack_all")}</button> : null}>
        {!s?.alerts?.length ? <Empty icon="ok" text={t("dash.no_alerts")} /> : (
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
