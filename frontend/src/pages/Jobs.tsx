import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, post, put, qs } from "../api";
import { useI18n } from "../i18n";
import { Card, Code, Empty, ErrorBox, Field, Loading, OkBox, Pill, Term, fmtDatesInText, fmtDuration, fmtTime, jobOutcome, useAction, useAsync } from "../components/ui";

const TYPES = ["D1_SYNC", "D0_SYNC", "TRAIN_PUBLISH"];
/** Pill tone per effective flow state (same as the schedule page). */
const STATE_PILL: Record<string, string> = { OFF: "SKIPPED", ON: "OK", ON_NOT_READY: "RETRY_WAIT", ON_NOT_LOADED: "PENDING",
  ON_SCHEDULER_STOPPED: "FAILED" };
const ALL_TYPES = [...TYPES, "FORECAST_EXTEND"];
/** The read-only remote link (scripts/remote/readonly_proxy.py) injects this banner: no write is offered there. */
const isRemote = () => typeof document !== "undefined" && !!document.getElementById("df-remote-banner");

export default function Jobs() {
  const { t } = useI18n();
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const jobs = useAsync(() => get(`/api/jobs${qs({ job_type: type, status, limit: 300 })}`), [type, status]);
  const sched = useAsync(() => get("/api/scheduler/status"), []);
  const act = useAction();
  const [params] = useSearchParams();
  const [open, setOpen] = useState<string | null>(params.get("job"));
  const run = async (jt: string) => {
    const r = await act.run(() => post("/api/jobs/run", { job_type: jt }));
    if (r) act.setOk(`${t(`job.${jt}`)}: ${t(`status.${r.status}`)}`);
    jobs.reload();
  };
  const tick = async () => {
    await act.run(() => post("/api/scheduler/tick"), t("common.saved"));
    jobs.reload();
    sched.reload();
  };
  // 1.2.4: D-1 / D-0 switches. The box is driven by the SAVED state only: after the backend answers (success or
  // refusal) the scheduler status is read again, so the switch never shows a state the backend did not confirm.
  const sw = useAction();
  const remote = isRemote();
  const toggle = async (fl: "d1" | "d0", on: boolean) => {
    if (!on && fl === "d0" && !window.confirm(t("sch.d0.confirm_on"))) return;
    await sw.run(() => put(`/api/schedules/${fl}`, { enabled: !on }), t(on ? "sch.saved_off" : "sch.saved_on"));
    sched.reload();
  };
  const s = sched.data;
  return (
    <div className="stack">
      <h2>{t("nav.jobs")}</h2>
      <ErrorBox error={act.error || jobs.error} />
      <OkBox text={act.ok} />
      <Card title={t("job.scheduler")} actions={<button onClick={tick} disabled={act.busy}>{t("job.evaluate")}</button>}>
        {s && (
          <p>
            {s.running ? <Pill status="RUNNING" label={t("job.sched_running")} /> : <Pill status="FAILED" label={t("job.sched_stopped")} />}{" "}
            <span className="small">{t("job.last_tick")}: {fmtTime(s.heartbeat?.at)}</span>
          </p>
        )}
        {s && (
          <p className="small" data-testid="jobs-flows">
            <b>{t("job.flows")}:</b>{" "}
            {([["d1_enabled", "D1_SYNC", s.config.d1_signal_poll_start, "d1"], ["d0_enabled", "D0_SYNC", s.config.d0_times.join(", "), "d0"],
               ["train_enabled", "TRAIN_PUBLISH", s.config.train_time, "train"]] as [string, string, string, string][]).map(([k, jt, times, fl]) => {
              // 1.2.3: the backend's EFFECTIVE state (switch + scheduler + readiness), never the switch alone
              const fs = s.flow_states?.[fl];
              const state = fs?.state ?? (s.config[k] ? "ON" : "OFF");
              const why = fs && !fs.readiness?.ready ? fs.readiness.reasons?.[0] : null;
              return (
                <span key={k} data-testid={`jobs-flow-${fl}`}>{t(`job.${jt}`)} <Pill status={STATE_PILL[state] ?? "PENDING"} label={t(`sch.state.${state}`)} />
                  {why && state !== "OFF" && <span className="small bad-t" title={why.detail ?? undefined} data-testid={`jobs-flow-why-${fl}`}> <Code code={why.code} /></span>}
                  {" "}<span className="muted">{times}</span> · </span>
              );
            })}
            <Link to="/schedules">{t("nav.schedules")} →</Link>
          </p>
        )}
        {s && (
          <div className="small" data-testid="jobs-switches">
            <ErrorBox error={sw.error} />
            <OkBox text={sw.ok} />
            {(["d1", "d0"] as const).map((fl) => {
              const fs = s.flow_states?.[fl];
              const on = !!fs?.enabled;
              const canOn = !!fs?.readiness?.ready;
              const why = !on && !canOn ? fs?.readiness?.reasons?.map((x: any) => x.code).join(", ") : "";
              const times = fl === "d1" ? s.config.d1_signal_poll_start : s.config.d0_times.join(", ");
              return (
                <label key={fl} className="row" title={remote ? t("job.switch_remote") : why || undefined}>
                  <input type="checkbox" role="switch" data-testid={`jobs-switch-${fl}`} checked={on}
                    disabled={remote || sw.busy || !fs || (!on && !canOn)} onChange={() => toggle(fl, on)} />
                  <b>{t(`job.switch.${fl}`)}</b>: {on ? t("job.switch_on") : t("job.switch_off")}
                  <span className="muted"> · {times} (Asia/Ho_Chi_Minh)</span>
                  {why && <span className="bad-t" data-testid={`jobs-switch-why-${fl}`}> · {why}</span>}
                </label>
              );
            })}
          </div>
        )}
        <p className="small muted">{t("job.offline_note")} <Term id="idempotency" /> <Term id="retry" /></p>
        <div className="row wrap">
          {TYPES.map((jt) => <button key={jt} onClick={() => run(jt)} disabled={act.busy}>{t("job.run_now")}: {t(`job.${jt}`)}</button>)}
        </div>
      </Card>
      <Card>
        <div className="row wrap">
          <Field label={t("job.type")}>
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">{t("common.all")}</option>
              {ALL_TYPES.map((x) => <option key={x} value={x}>{t(`job.${x}`)}</option>)}
            </select>
          </Field>
          <Field label={t("common.status")}>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("common.all")}</option>
              {["SUCCEEDED", "FAILED", "RUNNING", "RETRY_WAIT", "SKIPPED", "PENDING"].map((x) => <option key={x} value={x}>{t(`status.${x}`)}</option>)}
            </select>
          </Field>
          <button onClick={jobs.reload}>{t("common.refresh")}</button>
        </div>
        {jobs.loading ? <Loading /> : !jobs.data?.length ? <Empty text={t("common.none")} /> : (
          <div className="scroll">
            <table className="tbl click">
              <thead><tr><th>{t("common.created")}</th><th>{t("job.type")}</th><th>{t("job.trigger")}</th><th>{t("job.scheduled_for")}</th><th>{t("common.status")}</th><th>{t("job.stage")}</th><th>{t("job.elapsed")}</th><th>{t("job.attempt")}</th><th>{t("job.reason")}</th><th>{t("job.next_attempt")}</th></tr></thead>
              <tbody>
                {jobs.data.map((j: any) => (
                  <Fragment key={j.id}>
                    <tr onClick={() => setOpen(open === j.id ? null : j.id)}>
                      <td className="small">{fmtTime(j.created_at)}</td><td>{t(`job.${j.job_type}`)}</td><td>{t(`job.trigger.${j.trigger}`)}</td>
                      <td className="small">{fmtTime(j.scheduled_for)}</td><td><Pill status={j.status} />{["bad", "warn"].includes(jobOutcome(j)) && j.status === "SUCCEEDED" && <span className={`pill ${jobOutcome(j)}`}>{t(`job.outcome.${jobOutcome(j)}`)}</span>}{j.stale && <span className="pill warn">{t("job.outcome.unknown")}</span>}</td>
                      <td className="small">{t(`stage.${j.stage ?? "QUEUED"}`)}</td><td className="small">{j.elapsed_seconds != null ? fmtDuration(j.elapsed_seconds) : ""}</td><td>{j.attempt}/{j.max_attempts}</td>
                      <td className="small"><Code code={j.reason_code} /></td><td className="small">{fmtTime(j.next_attempt_at)}</td>
                    </tr>
                    {open === j.id && (
                      <tr id={`job-${j.id}`}><td colSpan={10}>
                        <div className="small mono">{j.id} · {j.idempotency_key}</div>
                        {j.error && <div className="alert bad small">{fmtDatesInText(j.error)}</div>}
                        {j.stage_history?.length > 0 && (<>
                          <div className="small"><b>{t("job.stage_history")}</b></div>
                          <ol className="stages small">
                            {j.stage_history.map((h: any, i: number) => <li key={i}><b>{t(`stage.${h.stage}`)}</b> · {fmtTime(h.at)}{h.message ? ` · ${fmtDatesInText(h.message)}` : ""}</li>)}
                          </ol>
                        </>)}
                        {j.result && <pre className="pre">{fmtDatesInText(JSON.stringify(j.result, null, 2))}</pre>}
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
