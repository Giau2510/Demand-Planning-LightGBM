import { useEffect, useState } from "react";
import { get, post, qs } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { Card, Code, DateInput, Empty, ErrorBox, Field, FilterBar, Loading, OkBox, PageHeader, Pill, SourceBadge, Term, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

const SNAPSHOT_SOURCES = ["DEMO", "BIGQUERY"];   // MANUAL_IMPORT has no intraday source

export default function Snapshots() {
  const { t, pick, lang } = useI18n();
  const { status: sys } = useSystem();
  // 1.2.2: the list opens on the ACTIVE source (BIGQUERY snapshots while the source is BIGQUERY), not on every source
  const initial = SNAPSHOT_SOURCES.includes(sys?.active_source) ? sys.active_source : "";
  const [f, setF] = useState({ date_from: "", date_to: "", sku_id: "", fc_id: "", data_source: initial });
  const [applied, setApplied] = useState(f);
  const [touched, setTouched] = useState(false);
  useEffect(() => {      // the system status may arrive after the first render
    if (!touched && initial && applied.data_source !== initial) {
      setF((x) => ({ ...x, data_source: initial }));
      setApplied((x) => ({ ...x, data_source: initial }));
    }
  }, [initial]);
  const list = useAsync(() => get(`/api/snapshots${qs(applied)}`), [applied]);
  const [sel, setSel] = useState<string | null>(null);
  const det = useAsync(() => (sel ? get(`/api/snapshots/${sel}${qs({ sku_id: applied.sku_id, fc_id: applied.fc_id })}`) : Promise.resolve(null)), [sel, applied]);
  const act = useAction();
  const take = async () => {
    const r = await act.run(() => post("/api/jobs/run", { job_type: "D0_SYNC" }));
    if (r) act.setOk(`${t("job.D0_SYNC")}: ${t(`status.${r.status}`)}`);
    list.reload();
  };
  const d = det.data;
  const nApplied = [applied.date_from, applied.date_to, applied.sku_id, applied.fc_id, applied.data_source].filter(Boolean).length;
  const empty = { date_from: "", date_to: "", sku_id: "", fc_id: "", data_source: "" };
  return (
    <div className="stack">
      <PageHeader icon="snapshots" title={<Term id="snapshot">{t("nav.snapshots")}</Term>} desc={<>{t("snap.title_help")} {t("common.time_note")}</>}
        actions={<button className="prod" title={t("common.prod_action")} onClick={take} disabled={act.busy}><Icon name="run" />{t("snap.take_now")}</button>} />
      <ErrorBox error={act.error || list.error || det.error} />
      <OkBox text={act.ok} />
      <Card>
        <FilterBar active={nApplied} onClear={() => { setTouched(true); setF(empty); setApplied(empty); }}>
          <Field label={t("common.from")}><DateInput value={f.date_from} onChange={(v) => setF({ ...f, date_from: v })} ariaLabel={t("common.from")} /></Field>
          <Field label={t("common.to")}><DateInput value={f.date_to} onChange={(v) => setF({ ...f, date_to: v })} ariaLabel={t("common.to")} /></Field>
          <Field label={t("fc.sku")}><input value={f.sku_id} onChange={(e) => setF({ ...f, sku_id: e.target.value })} aria-label={t("fc.sku")} /></Field>
          <Field label={t("fc.fc")}><input value={f.fc_id} onChange={(e) => setF({ ...f, fc_id: e.target.value })} aria-label={t("fc.fc")} /></Field>
          <Field label={t("common.source")}>
            <select value={f.data_source} onChange={(e) => setF({ ...f, data_source: e.target.value })} data-testid="snap-source">
              <option value="">{t("common.all")}</option>
              <option>DEMO</option><option>BIGQUERY</option>
            </select>
          </Field>
          <button className="primary" onClick={() => { setTouched(true); setApplied(f); }}><Icon name="filter" />{t("common.filter")}</button>
        </FilterBar>
      </Card>
      <Card icon="snapshots" title={t("snap.list")}>
        {list.loading ? <Loading /> : !list.data?.length
          ? <Empty text={applied.data_source ? t("snap.empty_source").replace("{src}", applied.data_source) : t("snap.empty")} hint={t("snap.empty_hint")} /> : (
          <div className="scroll">
            <table className="tbl click">
              <thead><tr><th>{t("snap.at")}</th><th>{t("snap.order_date")}</th><th>{t("snap.slot")}</th><th>{t("common.source")}</th><th>{t("common.status")}</th><th className="num">{t("snap.read")}</th><th className="num">{t("snap.valid")}</th><th className="num">{t("snap.error")}</th><th>{t("snap.id")}</th></tr></thead>
              <tbody>
                {list.data.map((s: any) => (
                  <tr key={s.id} className={s.id === sel ? "sel" : ""} onClick={() => setSel(s.id)}>
                    <td className="nowrap">{fmtTime(s.snapshot_at)}</td><td className="nowrap">{fmtDate(s.order_date)}</td>
                    <td>{fmtTime(s.scheduled_slot)} {s.is_catch_up ? <Pill status="RETRY_WAIT" label={t("snap.catch_up")} /> : null}</td>
                    <td><SourceBadge source={s.data_source} /></td><td><Pill status={s.sync_status} /></td>
                    <td className="num">{fmtNum(s.rows_read)}</td><td className="num">{fmtNum(s.rows_valid)}</td><td className="num">{fmtNum(s.rows_error)}</td>
                    <td className="mono small">{s.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {d && (
        <Card icon="snapshots" title={`${t("snap.id")}: ${d.snapshot.id}`} actions={<a className="btn" href={`/api/snapshots/${d.snapshot.id}/export.xlsx?lang=${lang}`}><Icon name="export" />{t("fc.export")} ({lang.toUpperCase()})</a>}>
          <div className="alert warn">{t("snap.warning")} <br /><span className="small">{pick(d.measurement_note)}</span></div>
          <p className="small">
            {t("snap.at")}: <b>{fmtTime(d.snapshot.snapshot_at)}</b> · {t("snap.order_date")}: <b>{fmtDate(d.snapshot.order_date)}</b> ·{" "}
            {d.forecast_run ? <>{t("snap.from_run")}: <span className="mono">{d.forecast_run.id}</span> ({d.forecast_run.model_version})</> : <Code code="NO_DATA" showCode={false} />}
          </p>
          <div className="scroll">
            <table className="tbl">
              <thead><tr><th>{t("fc.sku")}</th><th>{t("fc.fc")}</th><th className="num">{t("snap.cum")}</th><th className="num">{t("snap.full_fc")}</th><th className="num">{t("snap.eod")}</th></tr></thead>
              <tbody>
                {d.values.map((v: any) => (
                  <tr key={v.sku_id + v.fc_id}><td className="sku">{v.sku_id}</td><td className="nowrap">{v.fc_id}</td><td className="num">{fmtNum(v.cumulative_qty)}</td>
                    <td className="num">{v.full_day_forecast == null ? "—" : fmtNum(v.full_day_forecast, 1)}</td>
                    <td className="num">{v.end_of_day_actual == null ? t("common.not_available") : fmtNum(v.end_of_day_actual)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
