import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import GoogleAuth from "./GoogleAuth";
import { Card, DateInput, ErrorBox, Field, Loading, OkBox, Pill, fmtBytes, fmtDate, fmtNum, fmtPct, fmtTime, useAction, useAsync } from "../components/ui";

function Issues({ items, tone }: { items: any[]; tone: "bad" | "warn" }) {
  const { t } = useI18n();
  if (!items?.length) return null;
  return (
    <ul className={`small ${tone === "bad" ? "bad-t" : ""}`}>
      {items.map((x: any, i: number) => (
        <li key={i}><b>{t(`bq.code.${x.code}`)}</b> <span className="mono muted">{x.code}</span>
          {x.detail !== undefined && x.detail !== null && <span className="muted"> — {typeof x.detail === "object" ? JSON.stringify(x.detail) : String(x.detail)}</span>}</li>
      ))}
    </ul>
  );
}

export function ValidationView({ v, current }: { v: any; current: boolean }) {
  const { t } = useI18n();
  if (!v) return null;
  if (v.error) return <div className="alert bad" data-testid="bq-validation">{t("bq.failed")}: {v.error.code} — {v.error.detail ?? ""} ({fmtTime(v.checked_at)})</div>;
  const s = v.stats ?? {};
  const rec = v.reconciliation ?? {};
  return (
    <div className="stack" data-testid="bq-validation">
      <div className="row wrap">
        {v.passed ? <Pill status="OK" label={t("bq.passed")} /> : <Pill status="FAILED" label={t("bq.failed")} />}
        <span className="small">{t("bq.last_checked")}: <b>{fmtTime(v.checked_at)}</b> · {t("bq.range")}: <b>{fmtDate(v.range?.start)} – {fmtDate(v.range?.end)}</b> · {t("bq.est_bytes")}: {fmtBytes(v.estimated_bytes)} · {t("bq.mapping_hash")} <span className="mono">{v.mapping_hash}</span></span>
      </div>
      {!current && <div className="alert warn">{t("bq.validation_stale")}</div>}
      <table className="tbl small" data-testid="bq-validation-stats">
        <tbody>
          <tr><td>{t("bq.rows_read")}</td><td className="num">{fmtNum(rec.rows_read)}</td><td>{t("bq.rows_valid")}</td><td className="num">{fmtNum(rec.rows_valid)}</td><td>{t("bq.rows_excluded")}</td><td className="num">{fmtNum(rec.rows_excluded)}</td></tr>
          <tr><td>{t("bq.qty_read")}</td><td className="num">{fmtNum(rec.qty_read, 2)}</td><td>{t("bq.qty_valid")}</td><td className="num">{fmtNum(rec.qty_valid, 2)}</td><td>{t("bq.reconciliation")}</td><td>{rec.rows_ok && rec.qty_ok ? <Pill status="OK" /> : <Pill status="FAILED" />}</td></tr>
          <tr><td>{t("bq.n_sku")}</td><td className="num">{fmtNum(s.n_sku)}</td><td>{t("bq.n_fc")}</td><td className="num">{fmtNum(s.n_fc)}</td><td>{t("bq.n_series")}</td><td className="num">{fmtNum(s.n_series)}</td></tr>
          <tr><td>{t("bq.n_days")}</td><td className="num">{fmtNum(s.n_days)}</td><td>min</td><td>{fmtDate(s.min_date)}</td><td>max</td><td>{fmtDate(s.max_date)}</td></tr>
        </tbody>
      </table>
      {v.duplicate_check && <div><b className="small">{t("bq.code.EXACT_DUPLICATES")}</b><DupCounts d={v.duplicate_check} /></div>}
      <div>
        <b className="small">{t("bq.exclusions")}</b>
        <table className="tbl small"><tbody>
          {Object.entries(v.exclusions ?? {}).map(([k, x]: [string, any]) => (
            <tr key={k}><td>{t(`bq.code.${k}`)}</td><td className="mono">{k}</td><td className="num">{fmtNum(x.rows)}</td><td className="num">{fmtNum(x.qty, 2)}</td></tr>
          ))}
          <tr><td>{t("bq.code.NULL_DATE")}</td><td className="mono">NULL_DATE</td><td className="num">{fmtNum(rec.rows_null_date_outside_range)}</td><td /></tr>
        </tbody></table>
      </div>
      {v.blocking_issues?.length > 0 && <div className="alert bad" data-testid="bq-blocking"><b>{t("bq.blocking")}</b><Issues items={v.blocking_issues} tone="bad" /></div>}
      {v.warnings?.length > 0 && <div className="alert warn"><b>{t("bq.warnings")}</b><Issues items={v.warnings} tone="warn" /></div>}
      {v.missing_days?.count > 0 && <p className="small">{t("bq.missing_days")}: <b>{v.missing_days.count}</b> — {v.missing_days.days.slice(0, 31).map((d: string) => fmtDate(d)).join(", ")}{v.missing_days.count > 31 ? " …" : ""}</p>}
      {v.fc_gaps?.length > 0 && <p className="small">{t("bq.fc_gaps")}: {v.fc_gaps.slice(0, 10).map((g: any) => `${g.fc_id} (${g.days_without_rows})`).join(", ")}</p>}
      {v.outbound_vs_demand && <p className="small">{t("bq.outbound")}: Σ outbound <b>{fmtNum(v.outbound_vs_demand.sum_outbound_valid, 2)}</b> / Σ demand <b>{fmtNum(v.outbound_vs_demand.sum_demand_valid, 2)}</b> = <b>{fmtPct(v.outbound_vs_demand.ratio_outbound_to_demand)}</b></p>}
      {Object.keys(v.categories ?? {}).length > 0 && (
        <div className="row wrap">
          {Object.entries(v.categories).map(([f, items]: [string, any]) => (
            <table key={f} className="tbl small"><thead><tr><th colSpan={3}>{t("bq.categories")}: {f}</th></tr></thead><tbody>
              {items.slice(0, 15).map((c: any, i: number) => <tr key={i}><td className="mono">{c.value ?? "NULL"}</td><td className="num">{fmtNum(c.rows)}</td><td className="num">{fmtNum(c.qty_valid, 2)}</td></tr>)}
            </tbody></table>
          ))}
        </div>
      )}
      {Object.keys(v.reference_completeness ?? {}).length > 0 && (
        <table className="tbl small"><thead><tr><th colSpan={3}>{t("bq.refs")}</th></tr></thead><tbody>
          {Object.entries(v.reference_completeness).map(([f, r]: [string, any]) => (
            <tr key={f}><td className="mono">{f} ← {r.column}</td><td className="num">{fmtNum(r.non_null)}</td><td className="num">{fmtPct(r.share)}</td></tr>
          ))}
        </tbody></table>
      )}
    </div>
  );
}

const STEP_PILL: Record<string, string> = { PASSED: "OK", FAILED: "FAILED", BLOCKED: "FAILED", NOT_RUN: "PENDING", SKIPPED: "SKIPPED", WARNING: "WARNING" };
const RUN_PILL: Record<string, string> = { READY: "OK", SOURCE_INCOMPLETE: "WARNING", BLOCKED: "FAILED", FAILED: "FAILED" };
const reportUrl = (name: string) => `/api/bigquery/duplicate-reports/${encodeURIComponent(name)}`;

/** Duplicate report file(s) of a duplicate check: the .xlsx, or the CSV fallback when the workbook could not be written. */
export function DupReport({ rep }: { rep: any }) {
  const { t } = useI18n();
  if (!rep) return null;
  const files: string[] = rep.file ? [rep.file] : rep.files ?? [];
  return (
    <div className="stack small" data-testid="bq-dup-report">
      {rep.format === "csv" && <div className="alert warn">{t("bq.dup_report_csv")}: {rep.xlsx_error}</div>}
      {!files.length && <div className="alert bad">{t("bq.dup_report_failed")}: {rep.error ?? rep.xlsx_error}</div>}
      <div className="row wrap">{files.map((f) => <a key={f} className="btn" href={reportUrl(f)}>{t("bq.dup_report")}: {f}</a>)}</div>
    </div>
  );
}

/** Exact-duplicate counts (identical in every mapped column) + compared columns + report link. */
export function DupCounts({ d }: { d: any }) {
  const { t } = useI18n();
  if (!d) return null;
  return (
    <div className="stack" data-testid="bq-dup-check">
      <table className="tbl small"><tbody>
        <tr><td>{t("bq.dup_rows_checked")}</td><td className="num">{fmtNum(d.rows_checked)}</td><td>{t("bq.dup_groups")}</td><td className="num">{fmtNum(d.duplicate_groups)}</td></tr>
        <tr><td>{t("bq.dup_rows")}</td><td className="num">{fmtNum(d.duplicate_rows)}</td><td>{t("bq.dup_extra")}</td><td className="num">{fmtNum(d.extra_duplicate_rows)}</td></tr>
      </tbody></table>
      <p className="small muted">{t("bq.dup_compared")} ({d.columns?.length ?? 0}): <span className="mono">{(d.columns ?? []).map((c: any) => c.column).join(", ")}</span>
        {d.not_compared?.length > 0 && <> · {t("bq.dup_not_compared")}: <span className="mono">{d.not_compared.join(", ")}</span></>}</p>
      <DupReport rep={d.report} />
    </div>
  );
}

/** Result of "check duplicates & trial aggregation": every step of the next D-1 load, nothing written. */
export function IngestCheckView({ r }: { r: any }) {
  const { t, pick } = useI18n();
  if (!r) return null;
  const by: Record<string, any> = Object.fromEntries((r.steps ?? []).map((s: any) => [s.step, s]));
  const w = by.window ?? {}, a = by.aggregate ?? {}, rec = by.reconciliation ?? {}, cmp = by.compare ?? {};
  const dup = r.duplicate_check ?? (by.duplicates?.status === "PASSED" ? by.duplicates : null);
  const info = (s: any): string => {
    switch (["PASSED", "SKIPPED", "WARNING"].includes(s.status) ? s.step : "") {
      case "auth": return s.account ?? "";
      case "completeness": return s.completion_signal ? `${fmtDate(s.day)}: ${t("bq.ing.signal")}`
        : `${fmtDate(s.day)}: ${fmtNum(s.sufficiency?.rows_for_day)} ${t("bq.ing.rows")} (${t("bq.ing.avg7")} ${fmtNum(s.sufficiency?.avg_previous_7d, 0)}; ${t("bq.ing.min_ratio")} ${fmtPct(s.sufficiency?.ratio_required)})`;
      case "window": return `${fmtDate(s.start)} – ${fmtDate(s.end)}${s.full_reload ? ` · ${t("bq.ing.full")}` : ""}`;
      case "mapping": return `${s.compared_columns?.length ?? 0} ${t("bq.ing.cols")}`;
      case "duplicates": return s.status === "SKIPPED" ? `${t("bq.dup_policy")}: ${s.policy}` : `${fmtNum(s.duplicate_groups)} ${t("bq.dup_groups").toLowerCase()} · ${fmtNum(s.rows_checked)} ${t("bq.ing.rows")}`;
      case "aggregate": return `${fmtNum(s.rows_aggregated)} ${t("bq.ing.rows")} · Σ ${fmtNum(s.qty_total, 2)}`;
      case "reconciliation": return `${fmtNum(s.rows_read)} = ${fmtNum(s.rows_valid)} + ${fmtNum(s.rows_excluded)}`;
      default: return "";
    }
  };
  return (
    <div className="stack" data-testid="bq-ingest-result">
      <div className="row wrap">
        <Pill status={RUN_PILL[r.status] ?? "FAILED"} label={t(`bq.ing.${r.status}`)} />
        <span className="small">{t("bq.last_checked")}: <b>{fmtTime(r.checked_at)}</b> · <span className="mono">{r.table}</span>
          {w.start && <> · {t("bq.range")}: <b>{fmtDate(w.start)} – {fmtDate(w.end)}</b> ({t("bq.ing.today_excluded")} {fmtDate(w.today_excluded)})</>}</span>
      </div>
      <div className={`alert ${r.status === "READY" ? "info" : r.status === "BLOCKED" ? "bad" : "warn"} small`} data-testid="bq-ingest-note">{t(`bq.ing.${r.status}.note`)}</div>
      <table className="tbl small" data-testid="bq-ingest-steps"><tbody>
        {(r.steps ?? []).map((s: any) => (
          <tr key={s.step}>
            <td>{t(`bq.step.${s.step}`)}</td>
            <td><Pill status={STEP_PILL[s.status] ?? "PENDING"} label={t(`bq.stepst.${s.status}`)} /></td>
            <td>{s.error ? <span className="bad-t">{pick(s.error)}{s.error.detail ? <span className="muted"> — {s.error.detail}</span> : null}</span> : info(s)}</td>
          </tr>
        ))}
      </tbody></table>
      {dup && <DupCounts d={dup} />}
      {a.status === "PASSED" && (
        <table className="tbl small" data-testid="bq-ingest-numbers"><tbody>
          <tr><td>{t("bq.rows_read")}</td><td className="num">{fmtNum(rec.rows_read)}</td><td>{t("bq.rows_excluded")}</td><td className="num">{fmtNum(rec.rows_excluded)}</td></tr>
          <tr><td>{t("bq.ing.rows_aggregated")}</td><td className="num">{fmtNum(a.rows_aggregated)}</td><td>{t("bq.ing.qty_total")}</td><td className="num">{fmtNum(a.qty_total, 2)}</td></tr>
          {cmp.status === "PASSED" && <tr><td>{t("bq.ing.compare")}</td><td className="num" colSpan={3}>{fmtNum(cmp.series_days_new)} / {fmtNum(cmp.series_days_updated)} / {fmtNum(cmp.series_days_unchanged)} / {fmtNum(cmp.series_days_removed)}</td></tr>}
        </tbody></table>
      )}
      {r.readiness && <p className="small muted">{t("bq.ing.readiness")}: {t("bq.ing.r.source")} <b>{r.readiness.active_source}</b> · {t("bq.ing.r.production")} <b>{r.readiness.production_enabled ? "✔" : "✘"}</b> · {t("bq.ing.r.validation")} <b>{r.readiness.validation_current ? "✔" : "✘"}</b> · D-1 <b>{r.readiness.d1_schedule_enabled ? "ON" : "OFF"}</b></p>}
    </div>
  );
}

export default function BigQuery() {
  const { t, pick } = useI18n();
  const sys = useSystem();
  const st = useAsync(() => get("/api/bigquery/status"), []);
  const [v, setV] = useState<any>(null);
  const [out, setOut] = useState<any>(null);
  const [est, setEst] = useState({ start: "", end: "" });
  const act = useAction();
  useEffect(() => {
    if (st.data) setV(st.data.settings);
  }, [st.data]);
  if (!v) return st.error ? <ErrorBox error={st.error} /> : <Loading />;
  const set = (p: any) => setV({ ...v, ...p });
  const save = async () => {
    const r = await act.run(() => put("/api/settings/bigquery", v), t("common.saved"));
    if (r) { setV(r); st.reload(); }
  };
  const call = async (path: string, body?: any) => {
    setOut(null);
    const r = await act.run(() => post(path, body));
    if (r) setOut({ path, r });
    st.reload();
    sys.reload();
  };
  const checks = st.data?.checks ?? {};
  const reqs = st.data?.activation?.requirements ?? {};
  const configured = v.dataset_id && v.source_table;
  const authErr = checks.auth?.error?.code;
  const needCreds = (!st.data?.adc_default_file_exists && !st.data?.adc_env_set && v.auth_method === "ADC" && st.data?.oauth?.status !== "SIGNED_IN")
    || authErr === "BQ_AUTH_MISSING" || authErr === "BQ_AUTH_EXPIRED";

  return (
    <div className="stack">
      <h2>{t("nav.bigquery")}</h2>
      {!configured && <div className="alert warn"><b>{t("bq.not_configured")}</b><br />{t("bq.blocked_note")}</div>}
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <GoogleAuth onChange={() => st.reload()} />
      <Card title={t("nav.bigquery")} actions={<button className="primary" onClick={save} disabled={act.busy}>{t("common.save")}</button>}>
        <div className="form-grid">
          <Field label={t("bq.project")}><input value={v.project_id} onChange={(e) => set({ project_id: e.target.value })} /></Field>
          <Field label={t("bq.dataset")}><input value={v.dataset_id} onChange={(e) => set({ dataset_id: e.target.value })} placeholder="(chưa có / not provided)" /></Field>
          <Field label={t("bq.location")}><input value={v.location} onChange={(e) => set({ location: e.target.value })} placeholder="asia-southeast1 / US / …" /></Field>
          <Field label={t("bq.table")}><input value={v.source_table} onChange={(e) => set({ source_table: e.target.value })} /></Field>
          <Field label={t("bq.partition")}><input value={v.partition_column} onChange={(e) => set({ partition_column: e.target.value })} /></Field>
          <Field label={t("bq.utc")}><input type="checkbox" checked={v.created_at_is_utc} onChange={(e) => set({ created_at_is_utc: e.target.checked })} /></Field>
          <Field label={t("bq.auth")}>
            <select value={v.auth_method} onChange={(e) => set({ auth_method: e.target.value })}>
              <option value="ADC">{t("bq.auth.ADC")}</option>
              <option value="SERVICE_ACCOUNT_FILE">{t("bq.auth.SERVICE_ACCOUNT_FILE")}</option>
            </select>
          </Field>
          {v.auth_method === "SERVICE_ACCOUNT_FILE" && (
            <Field label={t("bq.sa_file")}><input value={v.service_account_file} onChange={(e) => set({ service_account_file: e.target.value })} placeholder="C:\\keys\\bq-reader.json" /></Field>
          )}
          <Field label={t("bq.max_bytes")}><input type="number" value={v.maximum_bytes_billed} onChange={(e) => set({ maximum_bytes_billed: Number(e.target.value) })} /><span className="small">{fmtBytes(v.maximum_bytes_billed)}</span></Field>
          <Field label={t("bq.initial_days")}><input type="number" value={v.initial_history_days} onChange={(e) => set({ initial_history_days: Number(e.target.value) })} /></Field>
          <Field label={t("bq.history_start")}><input value={v.history_start_date ?? ""} onChange={(e) => set({ history_start_date: e.target.value })} placeholder="2026-01-01" /></Field>
          <Field label={t("bq.dup_policy")}>
            <select value={v.exact_duplicate_policy ?? "BLOCK"} onChange={(e) => set({ exact_duplicate_policy: e.target.value })}>
              {["BLOCK", "KEEP", "DROP_EXACT"].map((x) => <option key={x} value={x}>{t(`bq.dup.${x}`)}</option>)}
            </select>
          </Field>
          <div className="full"><b>{t("bq.completion")}</b></div>
          <Field label={t("bq.completion_table")}><input value={v.completion_table} onChange={(e) => set({ completion_table: e.target.value })} /></Field>
          <Field label={t("bq.completion_date")}><input value={v.completion_date_column} onChange={(e) => set({ completion_date_column: e.target.value })} /></Field>
          <Field label={t("bq.completion_status")}><input value={v.completion_status_column} onChange={(e) => set({ completion_status_column: e.target.value })} /></Field>
          <Field label={t("bq.completion_value")}><input value={v.completion_status_value} onChange={(e) => set({ completion_status_value: e.target.value })} /></Field>
        </div>
        <div className="alert info small">{t("bq.adc_help")}<br />ADC file: {st.data?.adc_default_file_exists ? "✔" : "✘"} · GOOGLE_APPLICATION_CREDENTIALS: {st.data?.adc_env_set ? "✔" : "✘"}</div>
        <p className="small muted">{t("bq.cost_note")}</p>
      </Card>

      <Card title={t("bq.checks")}>
        <div className="row wrap">
          <button onClick={() => call("/api/bigquery/check-auth")} disabled={act.busy}>{t("bq.check_auth")}</button>
          <button onClick={() => call("/api/bigquery/test-connection")} disabled={act.busy || !v.dataset_id}>{t("bq.test")}</button>
          <button onClick={() => call("/api/bigquery/schema")} disabled={act.busy || !configured}>{t("bq.schema")}</button>
          <button onClick={() => call("/api/bigquery/preview")} disabled={act.busy || !configured}>{t("bq.preview")}</button>
          <button onClick={() => call("/api/bigquery/profile", { days: 30 })} disabled={act.busy || !configured}>{t("bq.profile")}</button>
          <button className="primary" data-testid="bq-validate" onClick={() => call("/api/bigquery/validate")} disabled={act.busy || !configured}>{t("bq.validate")}</button>
          <button className="primary" data-testid="bq-ingest-check" onClick={() => call("/api/bigquery/ingest-check")} disabled={act.busy || !configured}>{t("bq.ingest_check")}</button>
        </div>
        <p className="small muted">{t("bq.flow")}</p>
        <p className="small muted">{t("bq.ingest_check_note")}</p>
        {needCreds && <div className="alert warn" data-testid="bq-no-creds">{t("bq.no_creds")}</div>}
        <table className="tbl">
          <tbody>
            {["auth", "connection", "schema", "mapping", "profile", "validation"].map((k) => (
              <tr key={k}>
                <td>{t(`bq.check.${k}`)}</td>
                <td>{checks[k] ? <Pill status={checks[k].ok ? "OK" : "FAILED"} /> : <Pill status="PENDING" label="—" />}</td>
                <td className="small">{checks[k] ? `${t("bq.last_checked")}: ${fmtTime(checks[k].checked_at)}` : ""}</td>
                <td className="small">{checks[k]?.error ? pick(checks[k].error) + (checks[k].error.detail ? ` — ${checks[k].error.detail}` : "") : checks[k]?.location ? `location: ${checks[k].location}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {Object.entries(checks.last_sync ?? {}).map(([k, s]: [string, any]) => (
          <p key={k} className="small">{t("bq.last_sync")}: <b>{fmtTime(s.synced_at)}</b> · watermark {s.watermark} · {s.rows_valid} rows · {fmtBytes(s.estimated_bytes)}</p>
        ))}
        <div className="row wrap">
          <DateInput value={est.start} onChange={(v) => setEst({ ...est, start: v })} />
          <DateInput value={est.end} onChange={(v) => setEst({ ...est, end: v })} />
          <button onClick={() => call("/api/bigquery/estimate", est)} disabled={act.busy || !configured || !est.start || !est.end}>{t("bq.estimate")}</button>
        </div>
      </Card>

      {st.data?.validation && (
        <Card title={t("bq.validation")}>
          <ValidationView v={st.data.validation} current={!!st.data.validation_current} />
        </Card>
      )}

      {st.data?.ingest_check && (
        <Card title={t("bq.ingest_title")}>
          <IngestCheckView r={st.data.ingest_check} />
        </Card>
      )}

      {st.data?.duplicate_reports?.length > 0 && (
        <Card title={t("bq.dup_reports")}>
          <ul className="small" data-testid="bq-dup-reports">
            {st.data.duplicate_reports.map((f: any) => <li key={f.name}><a href={reportUrl(f.name)}>{f.name}</a> · {fmtTime(f.modified)} · {fmtBytes(f.size)}</li>)}
          </ul>
        </Card>
      )}

      {out && out.path !== "/api/bigquery/validate" && out.path !== "/api/bigquery/ingest-check" && (
        <Card title={out.path}>
          {out.r.estimated_bytes !== undefined && <p>{t("bq.est_bytes")}: <b>{fmtBytes(out.r.estimated_bytes)}</b></p>}
          {out.r.rows ? (
            <div className="scroll">
              <table className="tbl small">
                <thead><tr>{Object.keys(out.r.rows[0] ?? {}).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                <tbody>{out.r.rows.map((row: any, i: number) => <tr key={i}>{Object.values(row).map((x: any, j) => <td key={j}>{String(x ?? "")}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : <pre className="pre">{JSON.stringify(out.r, null, 2)}</pre>}
        </Card>
      )}

      <Card title={t("bq.production")}>
        <table className="tbl">
          <tbody>
            {Object.entries(reqs).map(([k, ok]) => (
              <tr key={k}><td>{t(`bq.check.${k}`)}</td><td>{ok ? <Pill status="OK" /> : <Pill status="NEEDS_CONFIG" />}</td></tr>
            ))}
          </tbody>
        </table>
        <div className="row">
          {v.production_enabled ? <Pill status="ACTIVE" /> : <Pill status="NEEDS_CONFIG" />}
          <button className="primary" onClick={() => call("/api/bigquery/activate")} disabled={act.busy || !st.data?.activation?.ready || v.production_enabled}>{t("bq.activate")}</button>
          <button onClick={() => call("/api/bigquery/deactivate")} disabled={act.busy || !v.production_enabled}>{t("bq.deactivate")}</button>
        </div>
      </Card>
    </div>
  );
}
