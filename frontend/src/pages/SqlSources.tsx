import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { useI18n } from "../i18n";
import { Card, DateInput, ErrorBox, Field, Loading, OkBox, PageHeader, Pill, fmtBytes, fmtNum, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

function vstatus(v: any) {
  return v?.validation?.status ?? "UNCHECKED";
}

/** Blocking reasons + notes exactly as the backend reports them (code, text, detail). */
export function ReasonList({ reasons, notes }: { reasons?: any[]; notes?: any[] }) {
  const { pick } = useI18n();
  return (
    <>
      {(reasons ?? []).length > 0 && <ul className="small" data-testid="reasons">{reasons!.map((x: any) => <li key={x.code} className="bad-t">{pick(x)} <code className="code">{x.code}</code>{x.detail ? <span className="mono"> ({x.detail})</span> : null}</li>)}</ul>}
      {(notes ?? []).length > 0 && <ul className="small muted" data-testid="notes">{notes!.map((x: any) => <li key={x.code}>{pick(x)}{x.detail ? <span className="mono"> ({x.detail})</span> : null}</li>)}</ul>}
    </>
  );
}

const D0_ESSENTIAL = ["sku_id", "fc_id", "order_qty"];
const D0_DATE_FIELDS = ["order_date", "created_at"];

function d0Body(fields: any[], m: Record<string, any>) {
  return Object.fromEntries(fields.map((x: any) => {
    const col = (m[x.field]?.usage === "UNUSED" ? null : m[x.field]?.column) || null;
    return [x.field, { column: col, usage: col ? (D0_ESSENTIAL.includes(x.field) ? "REQUIRED" : "OPTIONAL") : (D0_DATE_FIELDS.includes(x.field) ? "UNUSED" : "OPTIONAL") }];
  }));
}

/** 1.2.1: the D-0 feed's own mapping (output column names of the D-0 SQL / table; never the D-1 mapping). */
export function D0Mapping({ d0, reload, sqlVersionId }: { d0: any; reload: () => void; sqlVersionId?: number | null }) {
  const { t } = useI18n();
  const act = useAction();
  const [m, setM] = useState<Record<string, any>>(d0.mapping);
  const [cols, setCols] = useState<string[]>([]);
  const saved = JSON.stringify(d0.mapping);
  useEffect(() => { setM(d0.mapping); }, [saved]);
  const setCol = (f: string, column: string) => setM({ ...m, [f]: { column: column.trim() || null, usage: "OPTIONAL" } });
  const suggest = async (source: string) => {
    const r = await act.run(() => post("/api/bigquery/d0-mapping/suggest", { source }));
    if (r) { setM(r.mapping); setCols((r.columns ?? []).map((c: any) => `${c.name}`)); act.setOk(t("d0m.suggested")); }
  };
  const dirty = JSON.stringify(d0Body(d0.fields, m)) !== JSON.stringify(d0Body(d0.fields, d0.mapping));
  return (
    <div className="stack" data-testid="d0-mapping">
      <b className="small">{t("d0m.title")}</b>
      <p className="small muted">{t("d0m.help")}</p>
      <div className="small" data-testid="d0-readiness">
        {d0.ready ? <Pill status="OK" label={t("d0m.ready")} /> : <Pill status="INSUFFICIENT" label={t("d0m.not_ready")} />}
        <ReasonList reasons={d0.reasons} notes={d0.notes} />
      </div>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <table className="tbl small">
        <thead><tr><th>{t("d0m.field")}</th><th>{t("d0m.column")}</th><th>{t("d0m.types")}</th></tr></thead>
        <tbody>
          {d0.fields.map((x: any) => (
            <tr key={x.field}>
              <td>{t(`d0m.f.${x.field}`)}{x.essential ? " *" : ""} <span className="mono muted">{x.field}</span></td>
              <td><input list="d0-columns" aria-label={`d0-col-${x.field}`} value={(m[x.field]?.usage === "UNUSED" ? "" : m[x.field]?.column) ?? ""} onChange={(e) => setCol(x.field, e.target.value)} /></td>
              <td className="mono muted">{x.types.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <datalist id="d0-columns">{cols.map((c) => <option key={c} value={c} />)}</datalist>
      <div className="row wrap small">
        <button className="primary" disabled={act.busy || !dirty} data-testid="d0m-save"
          onClick={async () => { if (await act.run(() => put("/api/bigquery/d0-mapping", { mapping: d0Body(d0.fields, m) }), t("d0m.saved"))) reload(); }}><Icon name="save" />{t("d0m.save")}</button>
        <button disabled={act.busy} data-testid="d0m-suggest-table" onClick={() => suggest("table")}>{t("d0m.suggest_table")}</button>
        {sqlVersionId ? <button disabled={act.busy} data-testid="d0m-suggest-sql" onClick={() => suggest(`sql:${sqlVersionId}`)}>{t("d0m.suggest_sql")} v{sqlVersionId}</button> : null}
        <span className="muted">{t("d0m.key")}: <span className="mono">{(d0.key_columns ?? []).join(" + ") || "—"}</span> · {t("d0m.hash")} <span className="mono">{d0.mapping_hash}</span></span>
      </div>
      {d0.missing.length > 0 && <div className="bad-t small" data-testid="d0m-missing">{t("d0m.missing")}: <span className="mono">{d0.missing.join(", ")}</span></div>}
    </div>
  );
}

function Execution({ ex }: { ex: any }) {
  const { t } = useI18n();
  if (!ex) return null;
  return (
    <div className="small" data-testid="sql-execution">
      <b>{t("sql.exec")}</b> {ex.day}: {t("sql.exec.rows")} {fmtNum(ex.rows_read)} · {t("sql.exec.valid")} {fmtNum(ex.rows_valid)} · {t("sql.exec.error")} {fmtNum(ex.rows_error)} · {t("sql.exec.other_day")} {fmtNum(ex.rows_other_day)} · SKU×FC {fmtNum(ex.n_series)} · {t("sql.exec.qty")} {fmtNum(ex.qty_valid)} · {fmtBytes(ex.estimated_bytes)}
      {(ex.blocking_issues ?? []).length > 0 && <div className="bad-t" data-testid="sql-execution-issues">{t("sql.exec.issues")}: {ex.blocking_issues.map((i: any) => `${i.code} ${JSON.stringify(i.detail)}`).join("; ")}</div>}
      {(ex.warnings ?? []).length > 0 && <div className="muted">{ex.warnings.map((w: any) => `${w.code} ${JSON.stringify(w.detail)}`).join("; ")}</div>}
    </div>
  );
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
    <Card icon={kind === "d0" ? "clock" : "calendar"} title={t(`sql.${kind}`)}>
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
        {kind === "d0" && data.d0 && <D0Mapping d0={data.d0} reload={reload} sqlVersionId={sel} />}
        <ErrorBox error={act.error} />
        <OkBox text={act.ok} />
        <b className="small">{t("sql.editor")}</b>
        <textarea className="mono sql-editor" rows={14} value={text} spellCheck={false} aria-label={`editor-${kind}`}
          onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
        <div className="row wrap">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("sql.note")} aria-label={t("sql.note")} />
          <button className="primary" disabled={act.busy || !text.trim()} data-testid={`sql-save-${kind}`}
            onClick={async () => { const r = await call(t("sql.save"), () => post(`/api/sql-sources/${kind}/versions`, { sql: text, note: note || null }), t("common.saved")); if (r) { setSel(r.saved_version_id); setNote(""); } }}><Icon name="save" />{t("sql.save")}</button>
        </div>
        {cur && (
          <div className="small" data-testid={`sql-static-${kind}`}>
            <b>{t("sql.static")} (v{cur.id}):</b>{" "}
            {cur.static_check.ok ? <Pill status="OK" /> : <Pill status="FAILED" />}
            <ul>
              {cur.static_check.errors.map((e: any, i: number) => <li key={`e${i}`} className="bad-t">{e.code}{e.detail ? ` — ${e.detail}` : ""}</li>)}
              {cur.static_check.notes.map((n: any, i: number) => <li key={`n${i}`}><span className="mono">{n.code}</span>{n.line ? ` (${t("sql.line")} ${n.line})` : ""} — {n.detail}</li>)}
            </ul>
          </div>
        )}
        <b className="small">{t("sql.versions")}</b>
        <div className="scroll">
          <table className="tbl small" data-testid={`sql-versions-${kind}`}>
            <thead><tr><th>v</th><th>sha256</th><th>{t("sql.note")}</th><th>{t("sql.saved_at")}</th><th>{t("common.status")}</th><th /></tr></thead>
            <tbody>
              {data.versions.map((v: any) => (
                <tr key={v.id} className={v.id === data.active_version_id ? "row-ok" : ""} data-status={vstatus(v)}>
                  <td className="nowrap"><b>v{v.id}</b>{v.id === data.active_version_id ? <> <span className="pill ok">{t("sql.active_short")}</span></> : ""}</td>
                  <td className="mono">{v.sha256.slice(0, 12)}</td>
                  <td>{v.note ?? ""}</td>
                  <td className="nowrap">{v.saved_at ? fmtTime(v.saved_at) : "—"}</td>
                  <td><Pill status={vstatus(v) === "VALID" ? "OK" : vstatus(v) === "INVALID" ? "FAILED" : "PENDING"} label={t(`sql.status.${vstatus(v)}`)} />
                    {kind === "d0" && vstatus(v) === "VALID" && v.validated_for_current_mapping === false && <div className="bad-t" data-testid={`sql-stale-${v.id}`}>{t("d0m.stale")}</div>}
                    {v.validation?.checked_at && <div className="muted">{fmtTime(v.validation.checked_at)}</div>}
                    {v.validation?.error && <div className="bad-t">{v.validation.error.code}{v.validation.error.detail ? ` — ${String(v.validation.error.detail).slice(0, 300)}` : ""}</div>}</td>
                  <td className="row wrap">
                    <button className="small" onClick={() => { setSel(v.id); setText(v.sql); }}>{t("sql.load")}</button>
                    <button className="small" disabled={act.busy} data-testid={`sql-validate-${kind}-${v.id}`} onClick={() => call(`${t("sql.validate")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/validate`))}>{t("sql.validate")}</button>
                    <button className="small" disabled={act.busy} onClick={() => call(`${t("sql.preview")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/preview`, { limit: 20 }))}>{t("sql.preview")}</button>
                    <button className="small" disabled={act.busy} onClick={() => call(`${t("sql.test")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/test`))}>{t("sql.test")}</button>
                    {v.id !== data.active_version_id && <button className="small" disabled={act.busy} onClick={() => call(`${t("sql.restore")} v${v.id}`, () => post(`/api/sql-sources/${kind}/versions/${v.id}/restore`))}>{t("sql.restore")}</button>}
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
            {out.r?.validation?.execution && <Execution ex={out.r.validation.execution} />}
            {out.r?.validation?.mapping_check?.errors?.length > 0 && <ul className="small bad-t">{out.r.validation.mapping_check.errors.map((e: any, i: number) => <li key={i}>{e.field}: {e.code}{e.column ? ` (${e.column}${e.type ? ` ${e.type}` : ""})` : ""}</li>)}</ul>}
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
    <Card icon="refresh" title={t("sync.title")}>
      <p className="small muted">{pick(d.notes)} · {d.timezone}</p>
      <table className="tbl small" data-testid="sync-status">
        <thead><tr><th>{t("job.type")}</th><th>{t("sync.times")}</th><th>{t("sync.next")}</th><th>{t("sync.last")}</th><th>{t("sync.rows")}</th><th>{t("sync.new_upd")}</th><th>{t("sync.sql_version")}</th></tr></thead>
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
        <DateInput value={bf.start} onChange={(v) => setBf({ ...bf, start: v })} ariaLabel={t("common.from")} />
        <DateInput value={bf.end} onChange={(v) => setBf({ ...bf, end: v })} ariaLabel={t("common.to")} />
        <button className="prod" title={t("common.prod_action")} disabled={act.busy || !bf.start || !bf.end || !d.bigquery_production_enabled} onClick={async () => { await act.run(() => post("/api/sync/backfill", bf)); st.reload(); }}><Icon name="prod" />{t("sync.backfill")}</button>
      </div>
    </Card>
  );
}

export default function SqlSources() {
  const { t } = useI18n();
  const s = useAsync(() => get("/api/sql-sources"), []);
  const header = <PageHeader icon="sql" title={t("nav.sql")} desc={t("sql.help")} />;
  if (!s.data) return <div className="stack">{header}{s.error ? <ErrorBox error={s.error} /> : <Loading />}</div>;
  return (
    <div className="stack">
      {header}
      <SyncStatus />
      <Feed kind="history" data={s.data.history} reload={s.reload} />
      <Feed kind="d0" data={s.data.d0} reload={s.reload} />
    </div>
  );
}
