import { useEffect, useState } from "react";
import { get, qs } from "../api";
import { useI18n } from "../i18n";
import { Card, CompareChart, DateInput, Empty, ErrorBox, Field, FilterBar, Loading, PageHeader, Pager, Pill, SearchInput, SourceBadge, Stat, fmtDate, fmtNum, fmtPct, fmtTime, useAsync } from "../components/ui";
import { Icon } from "../components/icons";
import { ProductName } from "./Results";

const PAGE = 100;
const MAX_RANGE_DAYS = 400;     // same limit as the API (forecast_history.MAX_RANGE_DAYS)
const STATUSES = ["COMPLETE", "CLOSED", "PROVISIONAL", "NO_ACTUAL"];
const SOURCES = ["PRIMARY", "SNAPSHOT"];       // 1.2.6 official session / end-of-day backup snapshot
const SORTS = ["date", "abs_error", "forecast", "actual", "sku"];

/** YYYY-MM-DD + n days (calendar arithmetic, no time zone involved); "" when there is no valid date yet. */
export function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00Z");
  if (!iso || Number.isNaN(d.getTime())) return "";
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

const signed = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${fmtNum(v, d)}`);

/** Actual status as text + tone + icon; the reason (where the number comes from) is the tooltip. */
export function ActualStatus({ status, reason }: { status?: string | null; reason?: string | null }) {
  const { t } = useI18n();
  if (!status) return <span className="muted">—</span>;
  return <span title={reason ? t(`fh.reason.${reason}`) : undefined} data-testid="actual-status"><Pill status={status} label={t(`fh.st.${status}`)} /></span>;
}

/** 1.2.6: where a run date's forecast comes from - its official session, or the end-of-day backup snapshot (with the
 *  snapshot day, its creation time and the source run in the tooltip). */
export function ForecastSource({ r }: { r: any }) {
  const { t } = useI18n();
  if (r.forecast_source !== "SNAPSHOT")
    return <span title={`${fmtTime(r.session_started_at)} · ${t("fh.run_id")}: ${r.forecast_run_id} · ${r.model_version}`}>{fmtTime(r.session_started_at).slice(11)}</span>;
  return (
    <span data-testid="fh-backup" title={t("fh.backup_tip").replace("{d}", fmtDate(r.snapshot_business_date)).replace("{t}", fmtTime(r.snapshot_created_at))
      .replace("{run}", r.forecast_run_id).replace("{m}", r.model_version ?? "")}>
      <Pill status="SNAPSHOT" label={t("fh.src.SNAPSHOT_short")} /> <span className="small muted">{fmtDate(r.snapshot_business_date).slice(0, 5)}</span>
    </span>
  );
}

/** 1.2.5 "Forecast & actual history": for each run date the stored D+1 forecast of its official session, compared with
 *  the actual of that day; 1.2.6: a run date without a session shows its end-of-day backup, labelled as such. Read-only
 *  page: it never starts a job, a training or a forecast. */
export default function ForecastHistory() {
  const { t, lang } = useI18n();
  const [scopeKey, setScopeKey] = useState("");
  const ov = useAsync(() => get(`/api/history/overview${qs({ scope_key: scopeKey })}`), [scopeKey]);
  const [mode, setMode] = useState("last30");          // last30 | last7 | all | custom | <a run date>
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [fc, setFc] = useState("");
  const [status, setStatus] = useState("");
  const [fsrc, setFsrc] = useState("");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  useEffect(() => { const id = setTimeout(() => setQd(q.trim()), 300); return () => clearTimeout(id); }, [q]);
  const [sort, setSort] = useState("date");
  const [page, setPage] = useState(0);

  const o = ov.data;
  // run dates with a stored forecast: official sessions and (1.2.6) days covered by the end-of-day backup, newest first
  const days: any[] = [...(o?.days ?? []).map((d: any) => ({ ...d, source: "PRIMARY" })),
    ...(o?.backup_days ?? []).map((d: any) => ({ ...d, source: "SNAPSHOT" }))].sort((a, b) => (a.run_date < b.run_date ? 1 : -1));
  const latest = days[0]?.run_date ?? o?.today ?? "";
  const oldest = days[days.length - 1]?.run_date ?? latest;
  const range = mode === "last30" ? [addDays(latest, -29), latest] : mode === "last7" ? [addDays(latest, -6), latest]
    : mode === "all" ? [oldest > addDays(latest, 1 - MAX_RANGE_DAYS) ? oldest : addDays(latest, 1 - MAX_RANGE_DAYS), latest] : mode === "custom" ? [from || addDays(latest, -29), to || latest] : [mode, mode];
  const [runFrom, runTo] = range[0] <= range[1] ? range : [range[1], range[0]];
  const f = { scope_key: o?.scope_key, run_from: runFrom, run_to: runTo, fc_id: fc, q: qd, actual_status: status, forecast_source: fsrc };
  const ready = !!o?.scope_key && days.length > 0;      // nothing stored -> nothing to ask for
  useEffect(() => setPage(0), [o?.scope_key, runFrom, runTo, fc, qd, status, fsrc, sort]);
  const summary = useAsync(() => (ready ? get(`/api/history/summary${qs(f)}`) : Promise.resolve(null)),
    [o?.scope_key, runFrom, runTo, fc, qd, status, fsrc]);
  const rows = useAsync(() => (ready ? get(`/api/history/rows${qs({ ...f, sort, limit: PAGE, offset: page * PAGE })}`) : Promise.resolve(null)),
    [o?.scope_key, runFrom, runTo, fc, qd, status, fsrc, sort, page]);

  const exportHref = `/api/history/export.xlsx${qs({ ...f, sort, lang })}`;
  const header = (
    <PageHeader icon="fhistory" title={t("nav.fhistory")} desc={t("page.fhistory.desc")}
      actions={ready && days.length > 0 && (
        <a className="btn" href={exportHref} title={t("fh.export_help")} data-testid="fh-export"><Icon name="export" />{t("fh.export")} ({lang.toUpperCase()})</a>
      )} />
  );
  if (ov.loading && !o) return <div className="stack">{header}<Loading /></div>;
  if (ov.error) return <div className="stack">{header}<ErrorBox error={ov.error} /></div>;
  if (!o?.scope_key) return <div className="stack">{header}<Empty text={t("fh.empty")} hint={t("fh.empty_hint")} /></div>;

  const s = summary.data;
  const k = s?.kpi;
  const nFilters = [fc, qd, status, fsrc, mode !== "last30" ? "1" : ""].filter(Boolean).length;
  const clear = () => { setFc(""); setQ(""); setQd(""); setStatus(""); setFsrc(""); setMode("last30"); setFrom(""); setTo(""); };
  const official = (s?.sessions ?? []).filter((x: any) => x.official);
  const backups: any[] = s?.backup_days ?? [];
  const missing = (s?.daily ?? []).filter((d: any) => !d.has_history).length;
  // the KPI says when its actual is not final: provisional (intraday / not closed) or closed but not verified
  const provTag = k?.status === "PROVISIONAL" || k?.status === "CLOSED" ? <> <Pill status={k.status} label={t(`fh.st.${k.status}`)} /></> : null;
  const tb = o.today_backup;
  const scopeChoices = [...(o.scopes ?? [])];
  if (o.active_scope_key && !scopeChoices.some((x: any) => x.scope_key === o.active_scope_key))
    scopeChoices.unshift({ scope_key: o.active_scope_key, data_source: o.active_data_source ?? o.data_source, n_days: 0, active: true });

  return (
    <div className="stack">
      {header}
      <ErrorBox error={summary.error || rows.error} />
      <div className="alert info small" data-testid="fh-today">
        {o.today_session
          ? t("fh.today_session").replace("{d}", fmtDate(o.today)).replace("{t}", fmtTime(o.today_session.session_started_at))
            .replace("{target}", fmtDate(o.today_session.target_date))
          : tb ? <span data-testid="fh-today-backup">{t("fh.no_valid_today").replace("{d}", fmtDate(o.today))} {t("fh.today_backup")
              .replace("{s}", fmtDate(tb.snapshot_business_date)).replace("{t}", fmtTime(tb.snapshot_created_at))
              .replace("{run}", tb.forecast_run_id).replace("{target}", fmtDate(tb.target_date))}</span>
          : <>{t("fh.no_valid_today").replace("{d}", fmtDate(o.today))} {t("fh.sessions_when")}</>}
      </div>

      {days.length === 0 ? (
        <Card>
          <Empty text={t("fh.empty")} hint={t("fh.empty_hint")} icon="fhistory" />
          {scopeChoices.length > 1 && <ScopePicker value={o.scope_key} choices={scopeChoices} onChange={setScopeKey} />}
        </Card>
      ) : (
        <>
          <FilterBar active={nFilters} onClear={clear}>
            {scopeChoices.length > 1 && <ScopePicker value={o.scope_key} choices={scopeChoices} onChange={(v) => { setScopeKey(v); clear(); }} />}
            <Field label={t("fh.run_date")}>
              <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label={t("fh.run_date")} data-testid="fh-run-date">
                <option value="last30">{t("fh.last30")}</option>
                <option value="last7">{t("fh.last7")}</option>
                <option value="all">{t("fh.all")}</option>
                <option value="custom">{t("fh.custom")}</option>
                <optgroup label={t("fh.one_day")}>
                  {days.map((d) => <option key={d.run_date} value={d.run_date}>{fmtDate(d.run_date)} → {fmtDate(d.target_date)}{d.source === "SNAPSHOT" ? ` (${t("fh.src.SNAPSHOT_short")})` : ""}</option>)}
                </optgroup>
              </select>
            </Field>
            {mode === "custom" && (
              <>
                <Field label={t("fh.from")}><DateInput value={from || runFrom} onChange={setFrom} ariaLabel={t("fh.from")} /></Field>
                <Field label={t("fh.to")}><DateInput value={to || runTo} onChange={setTo} ariaLabel={t("fh.to")} /></Field>
              </>
            )}
            <Field label={t("fc.fc")}>
              <select value={fc} onChange={(e) => setFc(e.target.value)} aria-label={t("fc.fc")} data-testid="fh-fc">
                <option value="">{t("common.all")}</option>
                {(o.fcs ?? []).map((x: string) => <option key={x} value={x}>{x}</option>)}
              </select>
            </Field>
            <Field label={t("fc.search")}>
              <SearchInput value={q} onChange={setQ} label={t("fc.search")} placeholder={t("fc.search_ph")} clearLabel={t("fc.search_clear")} testid="fh-search" />
            </Field>
            <Field label={t("fh.status")}>
              <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t("fh.status")} data-testid="fh-status">
                <option value="">{t("common.all")}</option>
                {STATUSES.map((x) => <option key={x} value={x}>{t(`fh.st.${x}`)}</option>)}
              </select>
            </Field>
            <Field label={t("fh.src")}>
              <select value={fsrc} onChange={(e) => setFsrc(e.target.value)} aria-label={t("fh.src")} data-testid="fh-source">
                <option value="">{t("common.all")}</option>
                {SOURCES.map((x) => <option key={x} value={x}>{t(`fh.src.${x}`)}</option>)}
              </select>
            </Field>
          </FilterBar>
          <p className="small muted" data-testid="fh-range">
            {t("fh.run_date")}: <b>{fmtDate(runFrom)}</b>{runTo !== runFrom && <> → <b>{fmtDate(runTo)}</b></>} · {t("fh.target_date")}: <b>{fmtDate(addDays(runFrom, 1))}</b>
            {runTo !== runFrom && <> → <b>{fmtDate(addDays(runTo, 1))}</b></>} · <SourceBadge source={o.data_source} />
            {s?.matching_skus != null && <> · {t("fh.matching").replace("{n}", fmtNum(s.matching_skus))}</>}
          </p>

          {summary.loading && !s ? <Loading /> : k && (
            <div className="grid4" data-testid="fh-kpi">
              <Stat icon="chart" label={t("fh.kpi.forecast")} value={fmtNum(k.forecast_total)}
                sub={<>{t("fh.kpi.rows").replace("{n}", fmtNum(k.n_rows)).replace("{d}", fmtNum(k.days_with_history))}
                  {k.days_backup > 0 && <span data-testid="fh-kpi-backup"> · {t("fh.kpi.backup_days").replace("{n}", fmtNum(k.days_backup))}</span>}</>} />
              <Stat icon="actual" label={t("fh.kpi.actual")} value={<>{k.actual_total === null ? "—" : fmtNum(k.actual_total)}{provTag}</>}
                sub={k.actual_total === null ? t("fh.kpi.no_actual") : t("fh.kpi.on_rows").replace("{n}", fmtNum(k.n_rows_compared))} />
              <Stat icon="deviation" label={t("fh.kpi.deviation")} value={<>{signed(k.deviation, 0)}{k.deviation !== null && provTag}</>}
                sub={k.deviation === null ? t("fh.kpi.no_actual") : t("fh.kpi.forecast_cmp").replace("{v}", fmtNum(k.forecast_compared))} />
              <Stat icon="percent" label={t("fh.kpi.wape")} value={<>{k.wape === null ? "—" : fmtPct(k.wape)}{k.wape !== null && provTag}</>}
                sub={k.wape !== null ? t("fh.kpi.on_rows").replace("{n}", fmtNum(k.n_rows_compared))
                  : (k.notes ?? []).includes("SUM_ACTUAL_ZERO") ? t("fh.kpi.zero") : t("fh.kpi.no_actual")} />
            </div>
          )}

          {s && (
            <Card icon="chart" title={t("fh.chart")}>
              <CompareChart label={t("fh.chart")} legend={{ forecast: t("fh.legend.forecast"), actual: t("fh.legend.actual"), provisional: t("fh.legend.prov"), backup: t("fh.legend.backup") }}
                points={s.daily.map((d: any) => ({
                  x: d.target_date, forecast: d.has_history && d.n_rows ? d.forecast : null, actual: d.actual,
                  provisional: d.actual_status === "PROVISIONAL" || d.actual_status === "CLOSED", backup: d.forecast_source === "SNAPSHOT",
                  tip: [`${t("fh.target_date")}: ${fmtDate(d.target_date)}`, `${t("fh.run_date")}: ${fmtDate(d.run_date)}`,
                    !d.has_history ? t("fh.no_history_day") : `${t("fh.tip.forecast")}: ${d.n_rows ? fmtNum(d.forecast, 1) : t("fh.filtered_out")}`,
                    ...(d.forecast_source === "SNAPSHOT" ? [`${t("fh.src")}: ${t("fh.src.SNAPSHOT")} ${fmtDate(d.snapshot.snapshot_business_date)} · ${d.forecast_run_id}`] : []),
                    ...(d.has_history && d.n_rows ? [d.actual === null ? `${t("fh.tip.actual")}: ${t("fh.st.NO_ACTUAL")}`
                      : `${t("fh.tip.actual")}: ${fmtNum(d.actual, 1)} (${t(`fh.st.${d.actual_status}`)})`] : []),
                    ...(d.deviation !== null && d.deviation !== undefined ? [`${t("fh.tip.dev")}: ${signed(d.deviation)}`] : [])],
                }))} />
              {missing > 0 && <p className="small muted" data-testid="fh-missing-days">{t("fh.days_without").replace("{n}", String(missing))}</p>}
            </Card>
          )}

          {s && (
            <Card icon="history" title={t("fh.sessions")}>
              {official.length === 0 ? (backups.length === 0 && <Empty text={t("fh.no_history_day")} />) : (
                <div className="scroll">
                  <table className="tbl" data-testid="fh-sessions">
                    <thead><tr><th>{t("fh.run_date")}</th><th>{t("fh.target_date")}</th><th>{t("fh.session_time")}</th><th>{t("fh.run_id")}</th>
                      <th>{t("fc.model_version")}</th><th>{t("fh.capture")}</th><th className="num">{t("fh.rows")}</th><th>{t("fh.sessions_day")}</th></tr></thead>
                    <tbody>
                      {official.map((x: any) => {
                        const all = (s.sessions ?? []).filter((y: any) => y.run_date === x.run_date);
                        return (
                          <tr key={x.forecast_run_id}>
                            <td className="nowrap">{fmtDate(x.run_date)}</td><td className="nowrap">{fmtDate(x.target_date)}</td>
                            <td className="nowrap" title={`${t("fh.published_at")}: ${fmtTime(x.published_at)}`}>{fmtTime(x.session_started_at)}</td>
                            <td className="mono small nowrap">{x.forecast_run_id}</td><td className="mono small">{x.model_version}</td>
                            <td className="small">{t(`fh.capture.${x.capture_mode}`)}</td><td className="num">{fmtNum(x.n_rows)}</td>
                            <td className="small" title={all.map((y: any) => `${fmtTime(y.session_started_at)} ${y.forecast_run_id}: ${t(`fh.decision.${y.decision}`)}`).join("\n")}>
                              {t("fh.sessions_count").replace("{n}", String(all.length))}
                              {all.length > 1 && <> · {all.filter((y: any) => !y.official).map((y: any) => t(`fh.decision.${y.decision}`)).join(", ")}</>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {backups.length > 0 && (
                <div className="stack tight" data-testid="fh-backups">
                  <p className="small"><b>{t("fh.backups")}</b> — <span className="muted">{t("fh.backups_help")}</span></p>
                  <div className="scroll">
                    <table className="tbl">
                      <thead><tr><th>{t("fh.run_date")}</th><th>{t("fh.target_date")}</th><th>{t("fh.snap_day")}</th><th>{t("fh.snap_created")}</th>
                        <th>{t("fh.src_run")}</th><th>{t("fc.model_version")}</th><th>{t("fh.snap_id")}</th></tr></thead>
                      <tbody>
                        {backups.map((x: any) => (
                          <tr key={x.run_date}>
                            <td className="nowrap">{fmtDate(x.run_date)}</td><td className="nowrap">{fmtDate(x.target_date)}</td>
                            <td className="nowrap">{fmtDate(x.snapshot_business_date)}</td><td className="nowrap">{fmtTime(x.snapshot_created_at)}</td>
                            <td className="mono small nowrap" title={`${t("fh.session_time")}: ${fmtTime(x.session_started_at)}`}>{x.forecast_run_id} ({fmtDate(x.source_run_date)})</td>
                            <td className="mono small">{x.model_version}</td><td className="mono small nowrap">{x.snapshot_id}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </Card>
          )}

          <Card icon="sku" title={t("fh.table")} actions={
            <Field label={t("fh.sort")}>
              <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("fh.sort")} data-testid="fh-sort">
                {SORTS.map((x) => <option key={x} value={x}>{t(`fh.sort.${x}`)}</option>)}
              </select>
            </Field>}>
            {rows.loading && !rows.data ? <Loading /> : !rows.data?.total ? (
              <Empty text={t("fh.no_rows")} action={nFilters ? <button className="link" onClick={clear}>{t("filter.clear")}</button> : undefined} />
            ) : (
              <>
                <div className="scroll">
                  <table className="tbl fh-tbl" data-testid="fh-rows">
                    <thead><tr><th>{t("fc.sku")}</th><th>{t("fh.col.name")}</th><th>{t("fc.fc")}</th><th>{t("fh.run_date")}</th><th>{t("fh.target_date")}</th>
                      <th className="w-time">{t("fh.col.session_at")}</th><th className="num">{t("fh.col.forecast")}</th><th className="num">{t("fh.col.actual")}</th>
                      <th className="num">{t("fh.col.deviation")}</th><th className="num">{t("fh.col.wape")}</th><th>{t("fh.status")}</th></tr></thead>
                    <tbody>
                      {rows.data.rows.map((r: any) => (
                        <tr key={`${r.run_date}|${r.sku_id}|${r.fc_id}`}>
                          <td className="sku">{r.sku_id}</td><td className="pname"><ProductName name={r.product_name} /></td><td>{r.fc_id}</td>
                          <td className="nowrap">{fmtDate(r.run_date)}</td><td className="nowrap">{fmtDate(r.target_date)}</td>
                          <td className="src-cell"><ForecastSource r={r} /></td>
                          <td className="num">{fmtNum(r.yhat, 1)}</td>
                          <td className="num" title={r.actual === null ? t("fh.st.NO_ACTUAL") : `${t("actual.as_of")} ${fmtTime(r.actual_as_of)}`}>
                            {r.actual === null ? <span className="muted">—</span> : fmtNum(r.actual, 1)}</td>
                          <td className="num">{signed(r.deviation)}</td>
                          <td className="num">{r.row_wape === null ? <span className="muted" title={r.actual === null ? t("fh.st.NO_ACTUAL") : t("fh.wape_row_na")}>—</span> : fmtPct(r.row_wape)}</td>
                          <td className="st"><ActualStatus status={r.actual_status} reason={r.actual_reason} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager page={page} total={rows.data.total} size={PAGE} unit={t("common.rows")} onPage={setPage} />
              </>
            )}
          </Card>
        </>
      )}

      <Card icon="info" title={t("fh.rule")}>
        <ul className="small" data-testid="fh-rules">
          <li>{t("fh.rule_d1")}</li>
          <li>{t("fh.rule_actual")}</li>
          <li>{t("fh.rule_backup")}</li>
          <li>{t("fh.rule_close")}</li>
          <li>{o.completion_signal_configured ? t("fh.signal_ok") : o.data_source === "BIGQUERY" ? t("fh.signal_missing") : t("fh.signal_none")}</li>
        </ul>
      </Card>
    </div>
  );
}

function ScopePicker({ value, choices, onChange }: { value: string; choices: any[]; onChange: (v: string) => void }) {
  const { t } = useI18n();
  return (
    <Field label={t("fh.scope")}>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={t("fh.scope")} data-testid="fh-scope">
        {choices.map((x: any) => (
          <option key={x.scope_key} value={x.scope_key}>{x.data_source} · {String(x.scope_key).replace(/^BIGQUERY:/, "")}{x.active ? "" : ` (${t("fh.other_scope")})`} · {x.n_days} {t("fh.days_short")}</option>
        ))}
      </select>
    </Field>
  );
}
