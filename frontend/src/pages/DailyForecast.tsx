import { useEffect, useState } from "react";
import { get, post, qs } from "../api";
import { numberLocale, useI18n } from "../i18n";
import { useDailyStatus } from "../App";
import { Card, Confirm, DateInput, Empty, ErrorBox, Field, FilterBar, JobProgress, Loading, MethodLabel, OkBox, PageHeader, Pager, Pill,
  SearchInput, Stat, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";
import ForecastInfoLine from "../components/ForecastInfoLine";

const PAGE = 100;
const GROUPS = ["A", "B", "C"];
const REPORT_PILL: Record<string, string> = { DONE: "OK", FAILED: "FAILED" };

/** LightGBM value before publishing: always 3 decimals (the published quantity next to it is the integer). */
const fmt3 = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "—"
    : v.toLocaleString(numberLocale(), { minimumFractionDigits: 3, maximumFractionDigits: 3 });

const list = (x: unknown): any[] => (Array.isArray(x) ? x : []);

/** 1.4.0: a run published by the SEL2 pipeline (config_version "SEL2:..."); only its rows follow the forecast source. */
export const isSel2Run = (run: any): boolean => typeof run?.config_version === "string" && run.config_version.startsWith("SEL2:");

const SRC_PAGE = 1000;
const SRC_MAX_PAGES = 50;
/** The SKU x FC configured LIGHTGBM ("sku|fc"); null when they cannot all be read (too many): the per-row source is
 *  then unknown and no row label is shown. A SKU x FC without a row is AVG_DEMAND (the default). */
export async function loadLightgbmKeys(): Promise<Set<string> | null> {
  const keys = new Set<string>();
  for (let i = 0; i < SRC_MAX_PAGES; i++) {
    const r = await get(`/api/sel2/source-config${qs({ source: "LIGHTGBM", limit: SRC_PAGE, offset: i * SRC_PAGE })}`);
    list(r?.items).forEach((x: any) => keys.add(`${x.sku_code}|${x.fc_code}`));
    if ((i + 1) * SRC_PAGE >= (r?.total ?? 0)) return keys;
  }
  return null;
}

/** Row label of the daily forecast: "LIGHTGBM" (configured LIGHTGBM: the number is in use), "OTHER" (keeps the trial
 *  label) or null (not a SEL2 run, or the configuration is unknown: nothing is renamed). */
export function rowSourceKind(run: any, lgbmKeys: Set<string> | null | undefined, sku: string, fc: string): "LIGHTGBM" | "OTHER" | null {
  if (!isSel2Run(run) || !lgbmKeys) return null;
  return lgbmKeys.has(`${sku}|${fc}`) ? "LIGHTGBM" : "OTHER";
}

/** 1.3.1 "Dự báo hằng ngày": the forecast refreshed every morning with the model in use (B5), its values (B3 / B8),
 *  the export, the weekly accuracy reports (B9) and the trial mode (B12). Nothing here changes the Results page or its
 *  exports. The trial mode is switched only here: off needs the typed text TAT-CHAY-THU-<today>, back on needs none;
 *  both refresh the global banner of the shell. */
export default function DailyForecast() {
  const { t, pick } = useI18n();
  const daily = useDailyStatus();
  const status = useAsync(() => get("/api/daily-forecast/status"), []);
  const runs = useAsync(() => get("/api/daily-forecast/runs?limit=30"), []);
  const reports = useAsync(() => get("/api/accuracy-reports?limit=50"), []);
  const [runId, setRunId] = useState("");
  const [date, setDate] = useState("");
  const [h, setH] = useState("");
  const [group, setGroup] = useState("");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  useEffect(() => { const id = setTimeout(() => setQd(q.trim()), 300); return () => clearTimeout(id); }, [q]);
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [runId, date, h, group, qd]);
  // a chosen run wins over the forecast date (the backend does the same)
  const values = useAsync(() => get(`/api/daily-forecast/values${qs({ run_id: runId, forecast_date: runId ? "" : date, horizon: h, group, q: qd, page })}`),
    [runId, date, h, group, qd, page]);
  // 1.4.0 forecast source per SKU x FC (read only for a SEL2 run) and the daily Excel of the forecast day
  const sel2 = isSel2Run(values.data?.run);
  const lgbm = useAsync(() => (sel2 ? loadLightgbmKeys().catch(() => null) : Promise.resolve(null)), [sel2]);
  const [expDay, setExpDay] = useState("");
  const exportDay: string = expDay || values.data?.run?.forecast_date || status.data?.today || "";
  const expRuns = useAsync(() => (exportDay ? get(`/api/sel2/export/${encodeURIComponent(exportDay)}/runs`) : Promise.resolve(null)), [exportDay]);
  const [expOpen, setExpOpen] = useState(false);
  const exp = useAction();
  const [expJob, setExpJob] = useState<string | null>(null);     // the FORECAST_EXPORT job, followed like the refresh
  const [expRunning, setExpRunning] = useState(false);
  const [dialog, setDialog] = useState<"OFF" | "ON" | null>(null);
  const [typed, setTyped] = useState("");
  const [refreshJob, setRefreshJob] = useState<string | null>(null);     // followed until it ends, then kept on screen
  const [refreshRunning, setRefreshRunning] = useState(false);
  const [reportJob, setReportJob] = useState<string | null>(null);
  const [reportRunning, setReportRunning] = useState(false);
  const act = useAction();
  // a refresh already running (the schedule, another tab) is followed like one started here
  useEffect(() => {
    get("/api/jobs/active?job_type=FORECAST_REFRESH").then((j) => { if (j?.id) { setRefreshJob(j.id); setRefreshRunning(true); } }).catch(() => {});
  }, []);
  // the shell banner follows what this page reads: a long-lived tab never misses a label switched meanwhile
  useEffect(() => {
    if (!status.data) return;
    if (JSON.stringify(status.data.trial_label ?? null) !== JSON.stringify(daily.trialLabel ?? null)) daily.reload();
  }, [status.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = status.data;
  const v = values.data;
  const header = <PageHeader icon="daily" title={t("nav.daily")} desc={t("daily.desc")}
    actions={<button onClick={() => { status.reload(); runs.reload(); reports.reload(); values.reload(); daily.reload(); }} disabled={status.loading}>
      <Icon name="refresh" />{t("common.refresh")}</button>} />;
  if (status.loading && !s) return <div className="stack">{header}<Loading /></div>;
  if (!s) return <div className="stack">{header}<ErrorBox error={status.error} /></div>;

  const expected: string = s.trial_confirm_text ?? "";
  const lr = s.last_run;
  const rep = s.last_report;
  const runList = list(runs.data);
  const repList = list(reports.data);
  const run = v?.run;
  const openDialog = (m: "OFF" | "ON") => {
    setTyped(""); act.setError(null); act.setOk(null); setDialog(m);
    if (m === "OFF") status.reload();       // the confirmation text is of today (a page left open past midnight)
  };
  const switchTrial = async () => {
    const off = dialog === "OFF";
    const r = await act.run(() => post("/api/daily-forecast/trial-mode", { trial_mode: !off, confirm_text: off ? typed.trim() : null }));
    if (r) {
      setDialog(null);
      act.setOk(r.changed ? t("daily.trial_saved") : t("daily.trial_unchanged"));
      status.reload();
      daily.reload();
    }
  };
  const refresh = async () => {
    const j = await act.run(() => post("/api/daily-forecast/refresh"));
    if (j?.id) { act.setOk(`${t(j.already_active ? "sch.run_already_active" : "daily.job_started")}: ${j.id}`); setRefreshJob(j.id); setRefreshRunning(true); }
  };
  const runReport = async () => {
    const j = await act.run(() => post("/api/accuracy-reports/run"));
    if (j?.id) { act.setOk(`${t(j.already_active ? "sch.run_already_active" : "daily.job_started")}: ${j.id}`); setReportJob(j.id); setReportRunning(true); }
  };
  const exportNow = async () => {
    // 1.4.0 S5: the export is a background job (an export already queued / running is followed instead of a second one)
    const j = await exp.run(() => post("/api/sel2/export", { date: exportDay, confirm: true }));
    if (j?.id) {
      setExpOpen(false);
      exp.setOk(`${t(j.already_active ? "sch.run_already_active" : "daily.job_started")}: ${j.id}`);
      setExpJob(j.id); setExpRunning(true);
    }
  };
  const exportDone = (j: any) => {
    setExpRunning(false); expRuns.reload();
    const r = j?.result?.result;
    if (j?.status === "SUCCEEDED" && r?.version != null) exp.setOk(t("dexp.done").replace("{v}", String(r.version)).replace("{n}", fmtNum(r.n_rows)));
  };
  const expList = list(expRuns.data?.items);
  // the read-only remote link refuses the export routes (403): the card is not shown there
  const expForbidden = (expRuns.error as { status?: number } | null | undefined)?.status === 403;
  const trig = (x: string) => {
    for (const k of [`job.trigger.${x}`, `dexp.trigger.${x}`]) if (t(k) !== k) return t(k);
    return x;
  };
  const lgbmKeys = lgbm.data;
  // 1.4.4: the rows of the daily Excel (final_qty = forecast_used; the source column = the file's forecast_source);
  // the columns stay those of 1.4.3
  const sel2Rows = !!v?.sel2;
  const showSource = isSel2Run(run) && !!lgbmKeys;
  const nFilters = [runId, date, h, group, q.trim()].filter(Boolean).length;
  const clear = () => { setRunId(""); setDate(""); setH(""); setGroup(""); setQ(""); setQd(""); };

  return (
    <div className="stack" data-testid="daily-page">
      {header}
      <ForecastInfoLine />
      <ErrorBox error={status.error} />
      {/* the label itself is the shell banner above; here only what it means for this page */}
      {s.trial_label && <p className="small warn-t" data-testid="daily-trial">{t("daily.trial_note")}</p>}
      {s.stale && (
        <div className="alert bad" role="alert" data-testid="daily-stale">
          <Pill status="STALE" label={s.stale_code ?? "STALE_FORECAST"} /> {t("daily.stale").replace("{d}", s.refresh_deadline)}
          {s.stale_since ? ` (${t("daily.stale_since")} ${fmtTime(s.stale_since)})` : ""}
        </div>
      )}
      {!s.enabled && <div className="alert info small" data-testid="daily-disabled">{t("daily.disabled")}</div>}
      <ErrorBox error={dialog ? null : act.error} />
      <OkBox text={dialog ? null : act.ok} />

      <Card icon="daily" title={t("daily.state")}>
        {lr ? <p data-testid="daily-message"><b>{pick(s.message)}</b></p>
          : <Empty text={t("daily.no_run")} hint={s.enabled ? t("daily.no_run_hint") : t("daily.disabled")} />}
        {s.outdated && lr && (
          <div className="alert warn small" data-testid="daily-outdated">
            {t("daily.outdated").replace("{d}", fmtDate(lr.forecast_date)).replace("{today}", fmtDate(s.today))}
          </div>
        )}
        <div className="grid4">
          <Stat icon="power" label={t("daily.state")} value={s.enabled ? t("daily.on") : t("daily.off")}
            sub={s.trial_mode ? t("daily.trial_on") : t("daily.trial_off")} />
          <Stat icon="schedules" label={t("daily.schedule")} value={s.refresh_enabled ? t("daily.on") : t("daily.off")}
            sub={`${t("daily.deadline")} ${s.refresh_deadline ?? "—"}`} />
          <Stat icon="clock" label={t("daily.last_run")} value={lr ? fmtDate(lr.forecast_date) : "—"}
            sub={lr ? `${fmtTime(lr.created_at)} · ${fmtNum(lr.n_series)} ${t("common.series")}` : t("daily.no_run")} />
          <Stat icon="report" label={t("daily.last_report")} value={rep ? fmtDate(rep.run_date) : "—"}
            sub={rep ? t(`daily.report_st.${rep.status}`) : t("daily.no_reports")} />
        </div>
        {lr && (
          <p className="small muted" data-testid="daily-model">{t("daily.model")}: <span className="mono">{lr.model_version}</span>
            {" · "}<span className="mono">{lr.training_run_id}</span> · config v{lr.config_version}</p>
        )}
        <div className="row wrap">
          <button className="prod" onClick={refresh} disabled={act.busy || !s.enabled || refreshRunning} data-testid="daily-refresh"
            title={s.enabled ? t("common.prod_action") : t("daily.disabled")}><Icon name="refresh" />{t("daily.refresh")}</button>
          <span className="small muted">{s.enabled ? t("daily.refresh_help") : t("daily.disabled")}</span>
        </div>
        {refreshJob && <JobProgress jobId={refreshJob} onDone={() => {
          setRefreshRunning(false); status.reload(); runs.reload(); values.reload(); daily.reload();
        }} />}
      </Card>

      <Card icon="history" title={t("daily.runs")}>
        <ErrorBox error={runs.error} />
        {runList.length > 0 ? (
          <div className="scroll">
            <table className="tbl small" data-testid="daily-runs">
              <thead><tr><th>{t("daily.made_on")}</th><th>{t("daily.created_at")}</th><th>{t("daily.data_to")}</th><th>{t("daily.model")}</th>
                <th className="num">{t("daily.n_series")}</th><th className="num">{t("daily.n_lgb_fb")}</th><th className="num">{t("daily.horizon_days")}</th>
                <th>{t("daily.trial")}</th><th>{t("job.trigger")}</th><th></th></tr></thead>
              <tbody>
                {runList.map((r: any) => (
                  <tr key={r.id} aria-current={run?.id === r.id ? "true" : undefined}>
                    <td className="nowrap">{fmtDate(r.forecast_date)}</td><td className="nowrap">{fmtTime(r.created_at)}</td>
                    <td className="nowrap">{fmtDate(r.data_as_of)}</td><td className="mono">{r.model_version}</td>
                    <td className="num">{fmtNum(r.n_series)}</td><td className="num">{fmtNum(r.n_lightgbm)} / {fmtNum(r.n_fallback)}</td>
                    <td className="num">{r.horizon}</td>
                    <td>{r.trial_mode ? <Pill status="WARNING" label={t("daily.trial")} /> : "—"}</td>
                    <td>{t(`job.trigger.${r.trigger}`)}</td>
                    <td><button className="ghost small" onClick={() => setRunId(r.id)} data-testid={`daily-view-${r.id}`}
                      aria-label={`${t("daily.view")} ${r.id}`}>{t("daily.view")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !runs.loading && <p className="small muted">{t("daily.no_run")}</p>}
      </Card>

      <Card icon="results" title={t("daily.values")}
        actions={run ? <a className="btn" href={`/api/daily-forecast/export.xlsx${qs({ run_id: run.id })}`} data-testid="daily-export">
          <Icon name="export" />{t("daily.export")}</a> : undefined}>
        {run && (
          <p className="small" data-testid="daily-run">{t("daily.run")}: <span className="mono">{run.id}</span> · {t("daily.made_on")} {fmtDate(run.forecast_date)}
            {" · "}{t("daily.data_to")} {fmtDate(run.data_as_of)} · {t("daily.model")}: <span className="mono">{run.model_version}</span>
            {run.trial_mode ? <> · <Pill status="WARNING" label={t("daily.trial")} /></> : null}</p>
        )}
        <FilterBar active={nFilters} onClear={clear}>
          <Field label={t("daily.run")}>
            <select value={runId} onChange={(e) => setRunId(e.target.value)} aria-label={t("daily.run")} data-testid="daily-run-select">
              <option value="">{t("daily.run_latest")}</option>
              {runList.map((r: any) => <option key={r.id} value={r.id}>{fmtDate(r.forecast_date)} · {fmtTime(r.created_at)} · {r.id}</option>)}
            </select>
          </Field>
          <Field label={t("daily.forecast_date")}>
            <DateInput value={date} onChange={(x) => { setDate(x); setRunId(""); }} ariaLabel={t("daily.forecast_date")} />
          </Field>
          <Field label={t("daily.day_n")}>
            <select value={h} onChange={(e) => setH(e.target.value)} aria-label={t("daily.day_n")} data-testid="daily-horizon">
              <option value="">{t("common.all")}</option>
              {list(v?.horizons).map((x: number) => <option key={x} value={x}>{x}</option>)}
            </select>
          </Field>
          <Field label={t("daily.group")}>
            <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label={t("daily.group")} data-testid="daily-group">
              <option value="">{t("common.all")}</option>
              {GROUPS.map((g) => <option key={g} value={g}>{t(`daily.group.${g}`)}</option>)}
            </select>
          </Field>
          <Field label={t("daily.search")}>
            <SearchInput value={q} onChange={setQ} label={t("daily.search")} placeholder={t("daily.search_ph")} clearLabel={t("fc.search_clear")} />
          </Field>
        </FilterBar>
        <ErrorBox error={values.error} />
        {values.loading && !v && <Loading />}
        {v && !run && <Empty text={t("daily.no_values")} hint={lr ? undefined : t("daily.no_run_hint")} />}
        {run && (
          <div className="scroll">
            <table className="tbl" data-testid="daily-table">
              <thead><tr><th>{t("daily.made_on")}</th><th>{t("fc.date")}</th><th className="num">{t("daily.day_n")}</th><th>{t("fc.fc")}</th>
                <th>{t("fc.sku")}</th><th>{t("fc.product_name")}</th><th>{t("daily.group")}</th><th className="num">{t("daily.lgb_raw")}</th>
                <th className="num">{t("daily.final_qty")}</th><th>{t("fc.method")}</th>{showSource && <th>{t("dexp.source_col")}</th>}
                <th>{t("daily.flags")}</th></tr></thead>
              <tbody>
                {list(v.rows).map((x: any) => {
                  const kind = sel2Rows && x.forecast_source ? (x.forecast_source === "LIGHTGBM" ? "LIGHTGBM" : "OTHER")
                    : rowSourceKind(run, lgbmKeys, x.sku_code, x.fc_code);
                  return (
                  <tr key={`${x.fc_code}|${x.sku_code}|${x.horizon}`}>
                    <td className="nowrap">{fmtDate(x.forecast_date)}</td><td className="nowrap">{fmtDate(x.target_date)}</td>
                    <td className="num">{x.horizon}</td><td className="nowrap">{x.fc_code}</td><td className="sku">{x.sku_code}</td>
                    <td className="pname">{x.product_name ?? "—"}</td>
                    <td className="nowrap" title={x.group_code ? t(`daily.group.${x.group_code}`) : undefined}>{x.group_code ?? "—"}</td>
                    <td className="num" title={x.lgb_raw === null || x.lgb_raw === undefined ? undefined : String(x.lgb_raw)}>{fmt3(x.lgb_raw)}</td><td className="num"><b>{fmtNum(x.final_qty)}</b></td>
                    <td><MethodLabel code={x.method} /></td>
                    {showSource && <td className="nowrap" data-testid={`daily-src-${x.fc_code}-${x.sku_code}-${x.horizon}`}>
                      {kind === "LIGHTGBM" ? <Pill status="OK" label={t("dexp.using_lgbm")} />
                        : s.trial_label ? <Pill status="WARNING" label={pick(s.trial_label)} /> : <Pill status="INFO" label={t("fsrc.src.AVG_DEMAND")} />}</td>}
                    <td className="small mono">{x.flags ?? ""}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} total={v?.total ?? 0} size={v?.page_size ?? PAGE} unit={t("common.rows")} onPage={setPage} />
      </Card>

      {!expForbidden && <Card icon="export" title={t("dexp.title")}
        actions={<button className="prod" onClick={() => { exp.setError(null); exp.setOk(null); setExpOpen(true); }} disabled={exp.busy || expRunning || !exportDay}
          data-testid="dexp-run" title={t("common.prod_action")}><Icon name="export" />{t("dexp.run")}</button>}>
        <p className="small muted">{t("dexp.help")}</p>
        <div className="row wrap">
          <Field label={t("dexp.day")}>
            <DateInput value={exportDay} onChange={(x) => setExpDay(x)} ariaLabel={t("dexp.day")} />
          </Field>
          {expList.length > 0 && (
            <a className="btn" href={`/api/sel2/export/${encodeURIComponent(exportDay)}`} data-testid="dexp-download">
              <Icon name="download" />{t("dexp.download").replace("{v}", String(expList[0].version))}</a>
          )}
        </div>
        <ErrorBox error={expOpen ? null : exp.error} />
        <OkBox text={exp.ok} />
        {expJob && <JobProgress jobId={expJob} onDone={exportDone} />}
        <ErrorBox error={expRuns.error} />
        {expList.length > 0 ? (
          <div className="scroll">
            <table className="tbl small" data-testid="dexp-runs">
              <thead><tr><th className="num">{t("dexp.version")}</th><th>{t("daily.created_at")}</th><th className="num">{t("common.rows")}</th>
                <th>{t("dexp.state")}</th><th>{t("daily.flags")}</th><th>{t("job.trigger")}</th><th>{t("dexp.sha")}</th></tr></thead>
              <tbody>
                {expList.map((r: any) => (
                  <tr key={r.id}>
                    <td className="num">v{r.version}</td><td className="nowrap">{fmtTime(r.created_at)}</td><td className="num">{fmtNum(r.n_rows)}</td>
                    <td>{r.is_stale ? <Pill status="STALE" label={t("dexp.stale")} /> : <Pill status="OK" label={t("dexp.fresh")} />}</td>
                    <td className="small mono">{r.flags ?? ""}</td><td>{trig(r.trigger)}</td>
                    <td className="small mono" title={r.sha256 ?? undefined}>{r.sha256 ? String(r.sha256).slice(0, 12) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !expRuns.loading && !expRuns.error && <p className="small muted" data-testid="dexp-none">{t("dexp.none")}</p>}
      </Card>}

      <Card icon="report" title={t("daily.reports")}
        actions={<button className="prod" onClick={runReport} disabled={act.busy || !s.enabled || reportRunning} data-testid="daily-report-run"
          title={s.enabled ? t("common.prod_action") : t("daily.disabled")}><Icon name="run" />{t("daily.report_run")}</button>}>
        <p className="small muted">{t("daily.reports_help")}</p>
        {reportJob && <JobProgress jobId={reportJob} onDone={() => { setReportRunning(false); reports.reload(); status.reload(); }} />}
        <ErrorBox error={reports.error} />
        {repList.length > 0 ? (
          <div className="scroll">
            <table className="tbl small" data-testid="daily-reports">
              <thead><tr><th>{t("daily.created_at")}</th><th>{t("daily.report_kind")}</th><th>{t("daily.report_date")}</th><th>{t("daily.report_period")}</th>
                <th className="num">{t("daily.report_cells")}</th><th>{t("daily.state")}</th><th>{t("daily.report_file")}</th></tr></thead>
              <tbody>
                {repList.map((r: any) => (
                  <tr key={r.id}>
                    <td className="nowrap">{fmtTime(r.created_at)}</td><td>{t(`daily.report_kind.${r.run_kind}`)}</td>
                    <td className="nowrap">{fmtDate(r.run_date)}</td>
                    <td className="nowrap">{r.period_start ? `${fmtDate(r.period_start)} → ${fmtDate(r.period_end)}` : "—"}</td>
                    <td className="num">{fmtNum(r.n_cells)}</td>
                    <td><Pill status={REPORT_PILL[r.status] ?? "PENDING"} label={t(`daily.report_st.${r.status}`)} />
                      {r.error ? <div className="small bad-t">{r.error}</div> : null}</td>
                    <td>{r.report_path_name
                      ? <a href={`/api/accuracy-reports/${encodeURIComponent(r.id)}/download`} data-testid={`daily-report-dl-${r.id}`}>
                          <Icon name="download" size={14} />{r.report_path_name}</a>
                      : <span className="small muted">{t("daily.no_file")}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !reports.loading && <Empty text={t("daily.no_reports")} />}
      </Card>

      <Card icon="prod" title={t("daily.trial_title")}>
        <div className="row wrap" data-testid="daily-trial-state">
          <Pill status={s.trial_mode ? "WARNING" : "OK"} label={s.trial_mode ? t("daily.trial_on") : t("daily.trial_off")} />
          <span className="small">{s.trial_mode ? t("daily.trial_is_on") : t("daily.trial_is_off")}</span>
        </div>
        {!s.enabled && <p className="small muted">{t("daily.trial_only_enabled")}</p>}
        <div className="row wrap">
          {s.trial_mode
            ? <button className="danger" onClick={() => openDialog("OFF")} data-testid="daily-trial-off"><Icon name="prod" />{t("daily.trial_off_btn")}</button>
            : <button onClick={() => openDialog("ON")} data-testid="daily-trial-on"><Icon name="reset" />{t("daily.trial_on_btn")}</button>}
        </div>
      </Card>

      <Confirm open={dialog !== null} danger={dialog === "OFF"} title={dialog === "OFF" ? t("daily.trial_off_title") : t("daily.trial_on_title")}
        onCancel={() => setDialog(null)} onConfirm={switchTrial} confirmLabel={dialog === "OFF" ? t("daily.trial_off_btn") : t("daily.trial_on_btn")}
        disabled={act.busy || (dialog === "OFF" && (status.loading || !expected || typed.trim() !== expected))}>
        {dialog === "OFF" ? (
          <>
            <p>{t("daily.trial_off_body")}</p>
            <Field label={<>{t("daily.trial_type")} <code className="code" data-testid="daily-expected">{expected}</code></>}>
              <input id="daily-confirm-input" value={typed} onChange={(e) => setTyped(e.target.value)} data-testid="daily-confirm-input"
                autoComplete="off" aria-label={`${t("daily.trial_type")} ${expected}`} />
            </Field>
          </>
        ) : <p>{t("daily.trial_on_body")}</p>}
        <ErrorBox error={act.error} />
      </Confirm>
      <Confirm open={expOpen} title={t("dexp.confirm_title")} onCancel={() => setExpOpen(false)} onConfirm={exportNow}
        confirmLabel={t("dexp.run")} disabled={exp.busy || expRunning || !exportDay}>
        <p data-testid="dexp-confirm-body">{t("dexp.confirm_body").replace("{d}", fmtDate(exportDay))}</p>
        <ErrorBox error={exp.error} />
      </Confirm>
    </div>
  );
}
