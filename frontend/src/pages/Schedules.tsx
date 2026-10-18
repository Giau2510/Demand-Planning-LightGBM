import { useEffect, useState, type ReactNode } from "react";
import { get, post, put } from "../api";
import { useI18n } from "../i18n";
import { Card, Code, ErrorBox, Field, JobProgress, Loading, OkBox, PageHeader, Pill, fmtDate, fmtTime, jobOutcome, useAction, useAsync } from "../components/ui";
import { Icon, type IconName } from "../components/icons";

/** Pill tone for the effective state reported by the backend (never computed from the form). */
const STATE_PILL: Record<string, string> = { OFF: "SKIPPED", ON: "OK", ON_NOT_READY: "RETRY_WAIT", ON_NOT_LOADED: "PENDING",
  ON_SCHEDULER_STOPPED: "FAILED" };
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

type FlowKey = "d1" | "d0" | "train" | "eod" | "close";

function Readiness({ r }: { r: any }) {
  const { t, pick } = useI18n();
  return (
    <div className="small" data-testid="readiness">
      {r.ready ? <Pill status="OK" label={t("sch.ready")} /> : <Pill status="INSUFFICIENT" label={t("sch.not_ready")} />}
      {r.reasons?.length > 0 && <ul className="small">{r.reasons.map((x: any) => <li key={x.code}>{pick(x)}{x.detail ? <span className="muted mono"> ({x.detail})</span> : null}</li>)}</ul>}
      {r.notes?.length > 0 && <ul className="small muted" data-testid="readiness-notes">{r.notes.map((x: any) => <li key={x.code}>{pick(x)}{x.detail ? <span className="mono"> ({x.detail})</span> : null}</li>)}</ul>}
    </div>
  );
}

/** A job can SUCCEED as a job while its result is FAILED / REJECTED (e.g. training rejected by the quality gate):
 *  show that outcome next to the job status, as the Jobs page does. */
function Outcome({ r }: { r: any }) {
  const { t } = useI18n();
  // 1.2.6 day-end jobs: an incomplete backup snapshot / a day closed without any actual is said as such
  if (r.status === "SUCCEEDED" && (r.result_status === "INCOMPLETE" || r.result_status === "NO_DATA"))
    return <span className="pill warn" data-testid="job-outcome">{t(`job.result.${r.result_status}`)}</span>;
  const oc = jobOutcome({ status: r.status, result: { result: { status: r.result_status } } });
  return r.status === "SUCCEEDED" && (oc === "bad" || oc === "warn")
    ? <span className={`pill ${oc}`} data-testid="job-outcome">{t(`job.outcome.${oc}`)}</span> : null;
}

function LastRun({ v }: { v: any }) {
  const { t } = useI18n();
  const lr = v.last_run;
  return (
    <div className="small" data-testid="last-run">
      <b>{t("sch.last_run")}:</b>{" "}
      {lr ? <>{fmtTime(lr.finished_at || lr.started_at || lr.created_at)} <Pill status={lr.status} /><Outcome r={lr} /> <Code code={lr.reason_code} />
        {lr.error ? <div className="bad-t">{lr.error}</div> : null}
        {Object.keys(lr.summary || {}).length > 0 && <span className="muted mono"> {Object.entries(lr.summary).map(([k, x]) => `${k}=${x}`).join(" · ")}</span>}</>
        : <span className="muted">{t("sch.never")}</span>}
      {v.last_skipped && <div className="muted">{t("sch.last_skipped")}: {fmtTime(v.last_skipped.scheduled_for || v.last_skipped.created_at)} — <Code code={v.last_skipped.reason_code} showCode={false} /></div>}
    </div>
  );
}

const FLOW_ICON: Record<FlowKey, IconName> = { d1: "calendar", d0: "clock", train: "model", eod: "fhistory", close: "actual" };

/** 1.2.6 day-end flows: the scheduler runtime state reported by the backend (never derived from the form). */
const RUNTIME_PILL: Record<string, string> = { REGISTERED: "OK", NOT_REGISTERED: "SKIPPED", PENDING: "PENDING",
  RUNNING: "RUNNING", RETRY_WAIT: "RETRY_WAIT" };
const DAY_END_FLOWS: FlowKey[] = ["eod", "close"];

/** Dry run of a day-end flow: what the next run would record today, computed by the backend; nothing is written. */
function Preview({ p }: { p: any }) {
  const { t } = useI18n();
  const status = p.snapshot_status ?? p.close_status;
  const total = p.total_yhat ?? p.total_qty;
  return (
    <div className="alert info small" data-testid={`preview-${p.flow}`}>
      <b>{t("sch.preview.title")}</b> — {t("sch.preview.nothing_written")}
      <ul className="small">
        <li>{t("sch.preview.day")}: <b>{fmtDate(p.business_date)}</b> · {t("sch.preview.slot")}: {fmtTime(p.slot)} ({p.timezone})</li>
        <li>{t("sch.preview.status")}: <Pill status={status === "COMPLETE" || status === "CLOSED_VERIFIED" ? "OK" : status === "CLOSED_UNVERIFIED" ? "INFO" : "INSUFFICIENT"}
          label={t(`sch.preview.st.${status}`)} /> <span className="muted mono">{p.status_reason}</span></li>
        <li>{t("sch.preview.rows")}: <b>{p.rows}</b> · {t("sch.preview.total")}: <b>{total == null ? t("sch.preview.no_value") : total}</b></li>
        {p.flow === "eod" && <li>{t("sch.preview.source_run")}: <span className="mono">{p.source_run_id ?? "—"}</span> ({p.source_run_date ?? "—"}) · {t("sch.preview.targets")}: {p.first_target_date} → {p.last_target_date}
          {p.missing_dates?.length > 0 && <> · {t("sch.preview.missing")}: {p.missing_dates.length}</>}</li>}
        {p.flow === "close" && <li>{t("sch.preview.source")}: <b>{p.source ?? "—"}</b> <span className="muted mono">{p.source_ref ?? ""}</span>
          · {t("sch.preview.revisions")}: <b>{p.revisions_pending?.length ?? 0}</b>/{p.closed_days_checked}</li>}
        <li>{p.would_write ? t("sch.preview.would_write") : t("sch.preview.exists")}</li>
      </ul>
    </div>
  );
}

function FlowCard({ flow, v, title, intro, children, onSaved, confirmOn, conflictTime }: {
  flow: FlowKey; v: any; title: string; intro: ReactNode; children: (form: any, set: (p: any) => void) => ReactNode;
  onSaved: () => void; confirmOn?: string; conflictTime?: string;
}) {
  const { t, pick } = useI18n();
  const act = useAction();
  const dayEnd = DAY_END_FLOWS.includes(flow);
  const [form, setForm] = useState<any>(v.config);
  const [runId, setRunId] = useState<string | null>(null);     // job started by "run once now", followed until it ends
  const [running, setRunning] = useState(false);
  const [warn, setWarn] = useState<string | null>(null);
  const [preview, setPreview] = useState<any>(null);
  useEffect(() => { setForm(v.config); }, [JSON.stringify(v.config)]);       // always the backend's saved values
  const set = (p: any) => setForm((f: any) => ({ ...f, ...p }));
  const dirty = JSON.stringify(form) !== JSON.stringify(v.config);
  const conflict = dayEnd && !!conflictTime && form.time === conflictTime;   // the two day-end flows never share a minute
  const invalid = Object.entries(form).some(([k, x]) => (k === "time" || k === "fallback_time") && !HHMM.test(String(x)))
    || (form.times && (!Array.isArray(form.times) || form.times.some((x: string) => !HHMM.test(x)))) || conflict;
  const save = async (body: any, ok: string) => {
    setWarn(null);
    const r = await act.run(() => put(`/api/schedules/${flow}`, body), ok);
    if (r?.warning) act.setOk(`${ok} — ${pick(r.warning)}`);
    // a day-end flow is said ON only when the running scheduler confirmed it (state ON, registered)
    if (r && dayEnd && body.enabled === true && !(r.state === "ON" && r.registered === true)) {
      act.setOk(null);
      setWarn(t("sch.not_confirmed"));
    }
    onSaved();
  };
  return (
    <Card icon={FLOW_ICON[flow]} title={title}>
      <div data-testid={`flow-${flow}`} className="stack tight">
        <p className="small muted">{intro}</p>
        <ErrorBox error={act.error} />
        <OkBox text={act.ok} />
        <div className="row wrap" data-testid={`state-${flow}`}>
          <b>{t("sch.state")}:</b> <Pill status={STATE_PILL[v.state] ?? "PENDING"} label={t(`sch.state.${v.state}`)} />
          {v.enabled && v.enabled_at && <span className="small muted">{t("sch.enabled_at")} {fmtTime(v.enabled_at)}</span>}
          <span className="small muted">{t("sch.timezone")}: <span className="mono">{v.timezone}</span></span>
        </div>
        {dayEnd && v.runtime && (
          <div className="row wrap small" data-testid={`runtime-${flow}`}>
            <b>{t("sch.runtime")}:</b> <Pill status={RUNTIME_PILL[v.runtime.state] ?? "PENDING"} label={t(`sch.runtime.${v.runtime.state}`)} />
            {v.runtime.job_id && <span className="mono muted">{v.runtime.job_id}</span>}
          </div>
        )}
        {dayEnd && (
          <div className="small muted" data-testid={`config-meta-${flow}`}>
            {v.defaults && <>{t("sch.defaults")}: <span className="mono">{v.defaults.time}</span> · <span className="mono">{v.defaults.timezone}</span> · {t(v.defaults.enabled ? "sch.state.ON" : "sch.state.OFF")}</>}
            {" · "}{t("sch.config_updated")}: {v.config_updated ? fmtTime(v.config_updated.at) : t("sch.config_never")}
          </div>
        )}
        {warn && <div className="alert warn small" role="alert" data-testid={`warn-${flow}`}>{warn}</div>}
        <Readiness r={v.readiness} />
        <div className="form-grid">{children(form, set)}</div>
        <div className="row wrap">
          <button data-testid={`save-${flow}`} disabled={act.busy || !dirty || invalid}
            onClick={() => save(form, t("sch.saved_times"))}><Icon name="save" />{t("sch.save_times")}</button>
          {v.enabled
            ? <button className="prod" data-testid={`toggle-${flow}`} disabled={act.busy} title={t("common.prod_action")}
                onClick={() => save({ enabled: false }, t("sch.saved_off"))}><Icon name="power" />{t("sch.turn_off")}</button>
            : <button className="primary prod" data-testid={`toggle-${flow}`} disabled={act.busy || dirty || !v.readiness.ready}
                title={!v.readiness.ready ? t("sch.cannot_enable") : dirty ? t("sch.save_first") : t("common.prod_action")}
                onClick={() => { if (confirmOn && !window.confirm(confirmOn)) return; save({ enabled: true }, t("sch.saved_on")); }}><Icon name="power" />{t("sch.turn_on")}</button>}
          <button className="prod" data-testid={`run-${flow}`} disabled={act.busy || running || !(v.manual_readiness ?? v.readiness).ready}
            title={!(v.manual_readiness ?? v.readiness).ready ? t("sch.cannot_run") : t("common.prod_action")}
            onClick={async () => {
              if (!window.confirm(t("sch.run_confirm"))) return;
              const r = await act.run(() => post(`/api/schedules/${flow}/run`));
              if (r) {
                act.setOk(`${t(r.already_active ? "sch.run_already_active" : "sch.run_started")}: ${r.id}`);
                setRunId(r.id);
                setRunning(true);
              }
              onSaved();
            }}><Icon name="run" />{t("sch.run_now")}</button>
          {dayEnd && (
            <button data-testid={`preview-btn-${flow}`} disabled={act.busy} title={t("sch.preview.help")}
              onClick={async () => {
                setPreview(null);
                const r = await act.run(() => get(`/api/schedules/${flow}/preview`));
                if (r) setPreview(r);
              }}><Icon name="search" />{t("sch.preview.button")}</button>
          )}
        </div>
        {preview && <Preview p={preview} />}
        {runId && <JobProgress jobId={runId} onDone={() => { setRunning(false); onSaved(); }} />}
        {conflict && <div className="alert warn small" role="alert" data-testid={`conflict-${flow}`}>{t("sch.time_conflict")}</div>}
        {dirty && <div className="alert warn small">{t("sch.unsaved")}</div>}
        <div className="small" data-testid={`next-${flow}`}>
          <b>{t("sch.next_run")}:</b> {v.next_runs?.length ? v.next_runs.map((x: string) => fmtTime(x)).join(" · ") : <span className="muted">{t("sch.no_next")}</span>}
        </div>
        <LastRun v={v} />
        {v.history?.length > 0 && (
          <details className="small"><summary>{t("sch.history")}</summary>
            <table className="tbl small"><tbody>
              {v.history.map((h: any) => (
                <tr key={h.id}><td>{fmtTime(h.created_at)}</td><td>{t(`job.trigger.${h.trigger}`)}</td><td><Pill status={h.status} /><Outcome r={h} /></td>
                  <td><Code code={h.reason_code} showCode={false} /></td></tr>
              ))}
            </tbody></table>
          </details>
        )}
      </div>
    </Card>
  );
}

function Time({ value, onChange, testid }: { value: string; onChange: (v: string) => void; testid: string }) {
  return <input data-testid={testid} value={value} maxLength={5} placeholder="HH:MM" onChange={(e) => onChange(e.target.value.trim())} />;
}

/** Saved timezone of a day-end flow. Business dates are Vietnam dates: the backend accepts only Asia/Ho_Chi_Minh. */
function TimezoneField({ flow, form, set, v }: { flow: FlowKey; form: any; set: (p: any) => void; v: any }) {
  const { t } = useI18n();
  const value = form.timezone ?? v.timezone;
  const options = Array.from(new Set([v.defaults?.timezone ?? "Asia/Ho_Chi_Minh", value]));
  return (
    <Field label={t("sch.timezone")} help={t("sch.timezone_help")}>
      <select data-testid={`${flow}-timezone`} value={value} onChange={(e) => set({ timezone: e.target.value })}>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </Field>
  );
}

/** One page for the automatic data flows: D-1 (closed days), D-0 (today), daily training - each with its own switch. */
export default function Schedules() {
  const { t } = useI18n();
  const data = useAsync(() => get("/api/schedules"), []);
  const header = <PageHeader icon="schedules" title={t("nav.schedules")} desc={t("sch.intro")}
    actions={<button onClick={data.reload} disabled={data.loading}><Icon name="refresh" />{t("common.refresh")}</button>} />;
  if (data.loading && !data.data) return <div className="stack">{header}<Loading /></div>;
  if (data.error && !data.data) return (
    <div className="stack">{header}<ErrorBox error={data.error} /></div>
  );
  const d = data.data;
  if (!d) return null;
  const f = d.flows;
  const s = d.scheduler;
  return (
    <div className="stack" data-testid="schedules-page">
      {header}
      <p className="small row wrap mid" data-testid="sched-status">
        {s.running ? <Pill status="RUNNING" label={t("job.sched_running")} /> : <Pill status="FAILED" label={t("job.sched_stopped")} />}{" "}
        {t("sch.now")}: {fmtTime(d.now_vn)} ({d.timezone}) · {t("job.last_tick")}: {fmtTime(s.last_tick)} · {t("common.source")}: <b>{d.active_source}</b>
      </p>

      <FlowCard flow="d1" v={f.d1} title={t("sch.d1.title")} onSaved={data.reload}
        intro={<>{t("sch.d1.intro")} <span data-testid="d1-window">{t("sch.window_start")}: <b>{fmtDate(d.data_window.start)}</b> · {t("sch.window_end")}: <b>{fmtDate(d.data_window.end)}</b> ({t("sch.yesterday_vn")})</span></>}>
        {(form, set) => (<>
          <Field label={t("sch.d1.time")}><Time testid="d1-time" value={form.time} onChange={(x) => set({ time: x })} /></Field>
          <Field label={t("sch.d1.fallback")} help={t("cfg.d1_fallback_help")}><Time testid="d1-fallback" value={form.fallback_time} onChange={(x) => set({ fallback_time: x })} /></Field>
          <Field label={t("cfg.d1_poll_interval")}><input type="number" min={5} max={240} value={form.poll_interval_minutes}
            onChange={(e) => set({ poll_interval_minutes: Number(e.target.value) })} /></Field>
        </>)}
      </FlowCard>

      <FlowCard flow="d0" v={f.d0} title={t("sch.d0.title")} intro={t("sch.d0.intro")} onSaved={data.reload} confirmOn={t("sch.d0.confirm_on")}>
        {(form, set) => (<>
          <Field label={t("sch.d0.times")}><input data-testid="d0-times" value={(form.times ?? []).join(", ")}
            onChange={(e) => set({ times: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
          <Field label={t("cfg.d0_catchup")}>
            <select data-testid="d0-catchup" value={form.catchup_policy} onChange={(e) => set({ catchup_policy: e.target.value })}>
              {["SKIP", "LATEST_ONCE"].map((o) => <option key={o} value={o}>{t(`cfg.d0_catchup.${o}`)}</option>)}
            </select>
          </Field>
        </>)}
      </FlowCard>

      <FlowCard flow="train" v={f.train} title={t("sch.train.title")} intro={t("sch.train.intro")} onSaved={data.reload}>
        {(form, set) => (<>
          <Field label={t("cfg.train_time")}><Time testid="train-time" value={form.time} onChange={(x) => set({ time: x })} /></Field>
          <Field label={t("cfg.train_catchup")}>
            <select value={form.catchup_policy} onChange={(e) => set({ catchup_policy: e.target.value })}>
              {["RUN_ONCE", "SKIP"].map((o) => <option key={o} value={o}>{t(`cfg.train_catchup.${o}`)}</option>)}
            </select>
          </Field>
        </>)}
      </FlowCard>

      {f.eod && (
        <FlowCard flow="eod" v={f.eod} title={t("sch.eod.title")} intro={t("sch.eod.intro")} onSaved={data.reload}
          conflictTime={f.close?.config?.time}>
          {(form, set) => (<>
            <Field label={t("sch.eod.time")}><Time testid="eod-time" value={form.time} onChange={(x) => set({ time: x })} /></Field>
            <TimezoneField flow="eod" form={form} set={set} v={f.eod} />
          </>)}
        </FlowCard>
      )}

      {f.close && (
        <FlowCard flow="close" v={f.close} title={t("sch.close.title")} intro={t("sch.close.intro")} onSaved={data.reload}
          conflictTime={f.eod?.config?.time}>
          {(form, set) => (<>
            <Field label={t("sch.close.time")}><Time testid="close-time" value={form.time} onChange={(x) => set({ time: x })} /></Field>
            <TimezoneField flow="close" form={form} set={set} v={f.close} />
          </>)}
        </FlowCard>
      )}

      <Card icon="info" title={t("sch.offline.title")}>
        <ul className="small" data-testid="offline-rules">
          <li>{t("sch.offline.d1")}</li><li>{t("sch.offline.d0")}</li><li>{t("sch.offline.train")}</li><li>{t("sch.offline.dayend")}</li><li>{t("sch.offline.switch")}</li>
        </ul>
      </Card>
    </div>
  );
}
