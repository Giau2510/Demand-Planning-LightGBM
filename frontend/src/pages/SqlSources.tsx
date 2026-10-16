import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { useI18n } from "../i18n";
import { Card, DateInput, ErrorBox, Field, Loading, OkBox, Pill, fmtBytes, fmtNum, fmtTime, useAction, useAsync } from "../components/ui";

function vstatus(v: any) {
  return v?.validation?.status ?? "UNCHECKED";
}

function Feed({ kind, data, reload }: { kind: "history" | "d0"; data: any; reload: () => void }) {
  const { t, pick } = useI18n();
  const act = useAction();
  const latest = data.versions[0];
  const [sel, setSel] = useState<number | null>(latest?.id ?? null);
  const [text, setText] = useState<string>(latest?.sql ?? "");
  const [note, setNote] = useState("");
  const [keys, setKeys] = useState<string>((data.key_columns ?? []).join(", "));
  const [policy, setPolicy] = useState<string>(data.key_duplicate_policy);
  const [out, setOut] = useState<{ title: string; r: any } | null>(null);
  useEffect(() => { setKeys((data.key_columns ?? []).join(", ")); setPolicy(data.key_duplicate_policy); }, [data.key_columns, data.key_duplicate_policy]);
  const cur = data.versions.find((v: any) => v.id === sel) ?? latest;
  const call = async (title: string, fn: () => Promise<any>, ok?: string) => {
    setOut(null);
    const r = await act.run(fn, ok);
    if (r) setOut({ title, r });
    reload();
    return r;
  };
  return (
    <Card title={t(`sql.${kind}`)}>
      <div data-testid={`sql-${kind}`} className="stack">
        <div className="row wrap small">
          <Field label={t("sql.mode")}>
            <select value={data.mode} aria-label={`mode-${kind}`} onChange={(e) => call(t("sql.save_options"), () => put(`/api/sql-sources/${kind}/options`, { mode: e.target.value }), t("common.saved"))}>
              {["TABLE", "SQL"].map((m) => <option key={m} value={m}>{t(`sql.mode.${m}`)}</option>)}
            </select>
          </Field>
          <span data-testid={`sql-active-${kind}`}>
            {t("sql.active")}: {data.active ? <><b>v{data.active.id}</b> <span className="mono">{data.active.sha256.slice(0, 12)}</span> · {fmtTime(data.active.validation?.checked_at)} · {fmtBytes(data.active.validation?.estimated_bytes)}</> :
              data.mode === "SQL" ? <span className="bad-t">{t("sql.none_active")}</span> : <span>—</span>}
          </span>
        </div>
        {kind === "d0" && (
          <div className="row wrap small" data-testid="sql-schedule-d0">
            <b>{t("sql.schedule")}:</b> {data.schedule_enabled ? <Pill status="OK" label={t("sql.schedule_state_on")} /> : <span>{t("sql.schedule_state_off")}</span>}
            <Link to="/schedules">{t("sql.schedule_where")} →</Link>
          </div>
        )}
        <ErrorBox error={act.error} />
        <OkBox text={act.ok} />
        <b className="small">{t("sql.editor")}</b>
        <textarea className="mono sql-editor" rows={14} value={text} spellCheck={false} aria-label={`editor-${kind}`}
          onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
        <div className="row wrap">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("sql.note")} />
          <button className="primary" disabled={act.busy || !text.trim()} data-testid={`sql-save-${kind}`}
            onClick={async () => { const r = await call(t("sql.save"), () => post(`/api/sql-sources/${kind}/versions`, { sql: text, note: note || null }), t("common.saved")); if (r) { setSel(r.saved_version_id); setNote(""); } }}>{t("sql.save")}</button>
        </div>
        {cur && (
          <div className="small" data-testid={`sql-static-${kind}`}>
            <b>{t("sql.static")} (v{cur.id}):</b>{" "}
            {cur.static_check.ok ? <Pill status="OK" /> : <Pill status="FAILED" />}
            <ul>
              {cur.static_check.errors.map((e: any, i: number) => <li key={`e${i}`} className="bad-t">{e.code}{e.detail ? ` — ${e.detail}` : ""}</li>)}
              {cur.static_check.notes.map((n: any, i: number) => <li key={`n${i}`}><span className="mono">{n.code}</span>{n.line ? ` (dòng ${n.line})` : ""} — {n.detail}</li>)}
            </ul>
          </div>
        )}
        <b className="small">{t("sql.versions")}</b>
        <div className="scroll">
          <table className="tbl small" data-testid={`sql-versions-${kind}`}>
            <thead><tr><th>v</th><th>sha256</th><th>{t("sql.note")}</th><th>saved</th><th>status</th><th /></tr></thead>
            <tbody>
              {data.versions.map((v: any) => (
                <tr key={v.id} className={v.id === data.active_version_id ? "row-ok" : ""} data-status={vstatus(v)}>
                  <td><b>v{v.id}</b>{v.id === data.active_version_id ? " ✓" : ""}</td>
                  <td className="mono">{v.sha256.slice(0, 12)}</td>
                  <td>{v.note ?? ""}</td>
                  <td>{v.saved_at ? fmtTime(v.saved_at) : "—"}</td>
                  <td><Pill status={vstatus(v) === "VALID" ? "OK" : vstatus(v) === "INVALID" ? "FAILED" : "PENDING"} label={t(`sql.status.${vstatus(v)}`)} />
                    {v.validation?.error && <div className="bad-t">{v.validation.error.code}{v.validation.error.detail ? ` — ${String(v.validation.error.detail).slice(0, 160)}` : ""}</div>}</td>
                  <td className="row wrap">
                    <button onClick={() => { setSel(v.id); setText(v.sql); }}>{t("sql.load")}</button>
                    <button disabled={act.busy} data-testid={`sql-validate-${kind}-${v.id}`} onClick={() => call(`${t("sql.validate")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/validate`))}>{t("sql.validate")}</button>
                    <button disabled={act.busy} onClick={() => call(`${t("sql.preview")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/preview`, { limit: 20 }))}>{t("sql.preview")}</button>
                    <button disabled={act.busy} onClick={() => call(`${t("sql.test")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/test`))}>{t("sql.test")}</button>
                    {v.id !== data.active_version_id && <button disabled={act.busy} onClick={() => call(`${t("sql.restore")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/restore`))}>{t("sql.restore")}</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row wrap small">
          <Field label={t("sql.keys")}><input value={keys} onChange={(e) => setKeys(e.target.value)} placeholder={(data.effective_key_columns ?? []).join(", ")} /></Field>
          <Field label={t("sql.key_policy")}>
            <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
              {["BLOCK", "SUM_ALL"].map((p) => <option key={p} value={p}>{t(`sql.key.${p}`)}</option>)}
            </select>
          </Field>
          <button disabled={act.busy} onClick={() => call(t("sql.save_options"), () => put(`/api/sql-sources/${kind}/options`, {
            key_columns: keys.split(",").map((x) => x.trim()).filter(Boolean), key_duplicate_policy: policy }), t("common.saved"))}>{t("sql.save_options")}</button>
          <span className="muted">→ {(data.effective_key_columns ?? []).join(" + ") || "—"}</span>
        </div>
        {out && (
          <div data-testid={`sql-result-${kind}`}>
            <b className="small">{t("sql.result")}: {out.title}</b>
            {out.r?.validation && <p className="small">{out.r.validation.status === "VALID" ? <Pill status="OK" label={t("sql.status.VALID")} /> : <Pill status="FAILED" label={t("sql.status.INVALID")} />}
              {" "}{out.r.validation.statement_type} · {fmtBytes(out.r.validation.estimated_bytes)} · {(out.r.validation.columns ?? []).map((c: any) => c.name).join(", ")}
              {out.r.validation.error && <span className="bad-t"> — {pick(out.r.validation.error)} {out.r.validation.error.detail ?? ""}</span>}</p>}
            {Array.isArray(out.r?.rows) && out.r.rows.length > 0 && typeof out.r.rows[0] === "object" && (
              <div className="scroll"><table className="tbl small"><thead><tr>{Object.keys(out.r.rows[0]).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                <tbody>{out.r.rows.map((row: any, i: number) => <tr key={i}>{Object.values(row).map((x: any, j) => <td key={j}>{x === null ? "" : typeof x === "object" ? JSON.stringify(x) : String(x)}</td>)}</tr>)}</tbody></table></div>
            )}
            {!out.r?.validation && <pre className="pre small">{JSON.stringify({ ...out.r, rows: undefined, versions: undefined }, null, 1).slice(0, 4000)}</pre>}
          </div>
        )}
      </div>
    </Card>
  );
}

function SyncStatus() {
  const { t, pick } = useI18n();
  const st = useAsync(() => get("/api/sync/status"), []);
  const act = useAction();
  const [bf, setBf] = useState({ start: "", end: "" });
  if (!st.data) return st.error ? <ErrorBox error={st.error} /> : <Loading />;
  const d = st.data;
  return (
    <Card title={t("sync.title")}>
      <p className="small muted">{pick(d.notes)} · {d.timezone}</p>
      <table className="tbl small" data-testid="sync-status">
        <thead><tr><th>Job</th><th>{t("sync.times")}</th><th>{t("sync.next")}</th><th>{t("sync.last")}</th><th>{t("sync.rows")}</th><th>{t("sync.new_upd")}</th><th>{t("sync.sql_version")}</th></tr></thead>
        <tbody>
          {Object.entries(d.jobs).map(([jt, j]: [string, any]) => {
            const lr = j.last_run;
            const r = lr?.result ?? {};
            return (
              <tr key={jt}>
                <td><b>{t(`job.${jt}`)}</b>{!j.applies && <div className="muted">{t("sync.not_applicable")}</div>}</td>
                <td className="mono">{j.schedule.times.join(", ")}</td>
                <td>{j.next_runs.map((x: string) => fmtTime(x)).join(" · ") || "—"}</td>
                <td>{lr ? <><Pill status={lr.status} /> <span className="mono">{lr.id}</span><div>{fmtTime(lr.started_at)} → {fmtTime(lr.finished_at)} · {lr.attempt}/{lr.max_attempts}</div>
                  {lr.reason_code && <div className="bad-t">{lr.reason_code}{lr.error ? ` — ${String(lr.error).slice(0, 140)}` : ""}</div>}</> : "—"}</td>
                <td>{lr ? `${fmtNum(r.rows_read)} / ${fmtNum(r.rows_valid)} / ${fmtNum(r.rows_error)}` : "—"}</td>
                <td>{jt === "D1_SYNC" ? (lr ? `${fmtNum(r.series_days_new)} / ${fmtNum(r.series_days_updated)} / ${fmtNum(r.series_days_removed)}` : "—") : (lr ? `${fmtNum(r.series_rows_new ?? r.series)} / — / —` : "—")}</td>
                <td>{j.feed.mode === "SQL" ? (j.feed.active_version_id ? <>v{j.feed.active_version_id} <span className="mono">{(j.feed.active_sha256 ?? "").slice(0, 12)}</span></> : <span className="bad-t">{t("sql.none_active")}</span>) : t("sql.mode.TABLE")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <div className="row wrap small">
        <b>{t("sync.backfill")}</b>
        <DateInput value={bf.start} onChange={(v) => setBf({ ...bf, start: v })} />
        <DateInput value={bf.end} onChange={(v) => setBf({ ...bf, end: v })} />
        <button disabled={act.busy || !bf.start || !bf.end || !d.bigquery_production_enabled} onClick={async () => { await act.run(() => post("/api/sync/backfill", bf)); st.reload(); }}>{t("sync.backfill")}</button>
      </div>
    </Card>
  );
}

export default function SqlSources() {
  const { t } = useI18n();
  const s = useAsync(() => get("/api/sql-sources"), []);
  if (!s.data) return s.error ? <ErrorBox error={s.error} /> : <Loading />;
  return (
    <div className="stack">
      <h2>{t("nav.sql")}</h2>
      <p className="small">{t("sql.help")}</p>
      <SyncStatus />
      <Feed kind="history" data={s.data.history} reload={s.reload} />
      <Feed kind="d0" data={s.data.d0} reload={s.reload} />
    </div>
  );
}
