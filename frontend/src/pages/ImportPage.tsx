import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, post, upload } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { Card, Code, Confirm, ErrorBox, Field, OkBox, Pill, Stat, fmtDate, fmtDateish, fmtNum, useAction, useAsync } from "../components/ui";

export default function ImportPage() {
  const { t, lang } = useI18n();
  const sys = useSystem();
  const [params] = useSearchParams();
  const fields = useAsync(() => get("/api/schema/fields"), []);
  const batches = useAsync(() => get("/api/imports"), []);
  const [mode, setMode] = useState<"new" | "replace">(params.get("replace") ? "replace" : "new");
  const [replaceId, setReplaceId] = useState(params.get("replace") ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [up, setUp] = useState<any>(null);
  const [sheet, setSheet] = useState<string>("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [batch, setBatch] = useState<any>(null);
  const [ack, setAck] = useState(false);
  const [setActive, setSetActive] = useState(true);
  const [askReplace, setAskReplace] = useState(false);
  const [done, setDone] = useState<any>(null);
  const act = useAction();
  const active = (batches.data ?? []).filter((b: any) => b.status === "ACTIVE");

  const reset = () => {
    setFile(null); setUp(null); setSheet(""); setHeaders([]); setMapping({}); setBatch(null); setAck(false); setDone(null);
    act.setError(null); act.setOk(null);
  };

  const doUpload = async () => {
    if (!file) return;
    setBatch(null);
    const r = await act.run(() => upload("/api/imports/upload", file, mode === "replace" && replaceId ? { replace_batch_id: replaceId } : {}));
    if (!r) return;
    setUp(r);
    const s = r.suggested_sheet ?? "";
    setSheet(s);
    if (s) {
      setHeaders(r.sheets.find((x: any) => x.name === s)?.headers ?? []);
      setMapping(r.suggested_mapping ?? {});
    }
  };

  useEffect(() => {
    if (!up || !sheet || sheet === up.suggested_sheet) return;
    act.run(() => get(`/api/imports/uploads/${up.upload_id}/sheets/${encodeURIComponent(sheet)}`)).then((r: any) => {
      if (r) { setHeaders(r.headers); setMapping(r.suggested_mapping); }
    });
  }, [sheet]); // eslint-disable-line react-hooks/exhaustive-deps

  const validate = async () => {
    const r = await act.run(() => post(`/api/imports/uploads/${up.upload_id}/validate`, { sheet, mapping }));
    if (r) { setBatch(r); setAck(false); }
  };
  const confirm = async () => {
    setAskReplace(false);
    const r = await act.run(() => post(`/api/imports/${batch.id}/confirm`, { accept_row_errors: ack, set_active: setActive }));
    if (r) { setDone(r); batches.reload(); sys.reload(); }
  };
  const cancel = async () => {
    const r = await act.run(() => post(`/api/imports/${batch.id}/cancel`), t("imp.cancelled"));
    if (r) { setBatch(null); setUp(null); setFile(null); }
  };

  const fieldName = (f: any) => (lang === "vi" ? f.vi : f.en);
  const requiredOk = mapping.sku_id && mapping.fc_id && mapping.order_qty && (mapping.created_at || mapping.order_date);

  if (done) {
    return (
      <div className="stack">
        <h2>{t("nav.import")}</h2>
        <div className="alert ok"><b>{t("imp.done")}</b>: <span className="mono">{done.id}</span> — <Pill status={done.status} /> · {fmtNum(done.valid_rows)} {t("common.rows")}
          {done.replaces_batch_id && <> · {t("bat.replaces")} <span className="mono">{done.replaces_batch_id}</span></>}
        </div>
        <div className="row"><Link className="btn" to="/batches">{t("nav.batches")}</Link><Link className="btn" to="/quality">{t("nav.quality")}</Link><Link className="btn primary" to="/">{t("nav.dashboard")}</Link><button onClick={reset}>{t("imp.start_over")}</button></div>
      </div>
    );
  }

  return (
    <div className="stack">
      <h2>{t("nav.import")}</h2>
      <Card title={t("imp.step1")}>
        <p className="small">{t("imp.only_xlsx")}</p>
        <div className="row wrap">
          <a className="btn" href="/api/templates/import-template.xlsx">{t("imp.template")}</a>
          <a className="btn" href="/api/templates/sample-history.xlsx">{t("imp.sample_ok")}</a>
          <a className="btn" href="/api/templates/sample-with-errors.xlsx">{t("imp.sample_err")}</a>
        </div>
        <div className="row wrap">
          <label className="row"><input type="radio" checked={mode === "new"} onChange={() => setMode("new")} /> {t("imp.new_batch")}</label>
          <label className="row"><input type="radio" checked={mode === "replace"} onChange={() => setMode("replace")} disabled={!active.length} /> {t("imp.replace_mode")}</label>
          {mode === "replace" && (
            <select value={replaceId} onChange={(e) => setReplaceId(e.target.value)}>
              <option value="">—</option>
              {active.map((b: any) => <option key={b.id} value={b.id}>{b.id} · {b.file_name}</option>)}
            </select>
          )}
        </div>
        {mode === "replace" && <div className="alert warn small">{t("imp.replace_help")}</div>}
        <div className="row">
          <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => { reset(); setFile(e.target.files?.[0] ?? null); }} />
          <button className="primary" onClick={doUpload} disabled={!file || act.busy || (mode === "replace" && !replaceId)}>{t("imp.upload")}</button>
        </div>
      </Card>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />

      {up && (
        <Card title={t("imp.step2")}>
          <Field label={t("imp.sheet")}>
            <select value={sheet} onChange={(e) => setSheet(e.target.value)}>
              <option value="">{t("imp.choose_sheet")}</option>
              {up.sheets.map((s: any) => <option key={s.name} value={s.name}>{s.name} ({s.headers.length} cols)</option>)}
            </select>
          </Field>
          {!sheet && <Code code="SHEET_NOT_FOUND" />}
          {sheet && (
            <table className="tbl">
              <thead><tr><th>{t("imp.field")}</th><th>{t("imp.column")}</th><th></th></tr></thead>
              <tbody>
                {(fields.data ?? []).map((f: any) => (
                  <tr key={f.name}>
                    <td><b className="mono">{f.name}</b> <span className={f.required ? "pill warn" : "pill muted"}>{f.required || f.name === "order_date" ? t("imp.required") : t("imp.optional")}</span>
                      {f.name === "order_date" && <span className="small muted"> (created_at | order_date)</span>}</td>
                    <td>
                      <select value={mapping[f.name] ?? ""} onChange={(e) => setMapping({ ...mapping, [f.name]: e.target.value || null })}>
                        <option value="">{t("imp.not_used")}</option>
                        {headers.map((h) => <option key={h} value={h}>{h}</option>)}
                      </select>
                    </td>
                    <td className="small muted">{fieldName(f)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button className="primary" onClick={validate} disabled={!sheet || !requiredOk || act.busy}>{act.busy ? t("common.running") : t("imp.validate")}</button>
          {sheet && !requiredOk && <Code code="MISSING_REQUIRED_COLUMNS" />}
        </Card>
      )}

      {batch && (
        <>
          <Card title={t("imp.step3")}>
            <div className="grid4">
              <Stat label={t("imp.total")} value={fmtNum(batch.total_rows)} />
              <Stat label={t("imp.valid")} value={fmtNum(batch.valid_rows)} tone="ok" />
              <Stat label={t("imp.errors")} value={fmtNum(batch.error_rows)} tone={batch.error_rows ? "bad" : ""} />
              <Stat label={t("imp.dups")} value={fmtNum(batch.duplicate_rows)} tone={batch.duplicate_rows ? "warn" : ""} />
            </div>
            <div className="grid3">
              <Stat label={t("imp.date_range")} value={<span className="small">{fmtDate(batch.min_order_date)} → {fmtDate(batch.max_order_date)}</span>} />
              <Stat label={t("imp.missing_dates")} value={fmtNum(batch.validation?.missing_dates_count)} sub={(batch.validation?.missing_dates ?? []).slice(0, 5).map((x: string) => fmtDate(x)).join(", ")} />
              <Stat label={t("imp.problem_fields")} value={<span className="small">{(batch.validation?.fields_with_problems ?? []).join(", ") || t("common.none")}</span>} />
            </div>
            <table className="tbl small">
              <thead><tr><th>{t("imp.severity")}</th><th>{t("imp.code")}</th><th className="num">#</th><th>{t("imp.explain")}</th></tr></thead>
              <tbody>
                {(batch.validation?.issues_by_code ?? []).map((i: any) => (
                  <tr key={i.code}><td><Pill status={i.severity} /></td><td className="mono">{i.code}</td><td className="num">{fmtNum(i.count)}</td><td><Code code={i.code} showCode={false} /></td></tr>
                ))}
              </tbody>
            </table>
            {batch.issue_count > 0 && <a className="btn" href={`/api/imports/${batch.id}/errors.xlsx?lang=${lang}`}>{t("imp.error_report")}</a>}
            <h4>{t("imp.preview")}</h4>
            <div className="scroll">
              <table className="tbl small">
                <thead><tr>{["row_number", "order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>
                  {batch.preview.map((r: any) => (
                    <tr key={r.row_number}>{["row_number", "order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price"].map((h) => <td key={h}>{h === "created_at" || h === "order_date" ? fmtDateish(r[h]) : r[h] ?? ""}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
            {batch.issues_sample?.length > 0 && (
              <>
                <h4>{t("imp.issues")}</h4>
                <div className="scroll">
                  <table className="tbl small">
                    <thead><tr><th>{t("imp.row")}</th><th>{t("imp.field")}</th><th>{t("imp.severity")}</th><th>{t("imp.raw")}</th><th>{t("imp.explain")}</th></tr></thead>
                    <tbody>
                      {batch.issues_sample.map((i: any, k: number) => (
                        <tr key={k}><td>{i.row_number}</td><td className="mono">{i.field}</td><td><Pill status={i.severity} /></td><td className="mono">{i.field === "created_at" || i.field === "order_date" ? fmtDateish(i.raw_value) : i.raw_value ?? ""}</td><td><Code code={i.code} /></td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Card>
          <Card title={t("imp.step4")}>
            {batch.requires_error_ack && (
              <label className="row"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> {t("imp.ack_errors")}</label>
            )}
            <label className="row"><input type="checkbox" checked={setActive} onChange={(e) => setSetActive(e.target.checked)} /> {t("imp.set_active")}</label>
            <div className="row">
              <button onClick={cancel} disabled={act.busy}>{t("imp.cancel_import")}</button>
              <button className={batch.replaces_batch_id ? "danger" : "primary"} disabled={!batch.can_confirm || (batch.requires_error_ack && !ack) || act.busy}
                onClick={() => (batch.replaces_batch_id ? setAskReplace(true) : confirm())}>
                {batch.replaces_batch_id ? `${t("imp.confirm_replace")} ${batch.replaces_batch_id}` : t("imp.confirm")}
              </button>
            </div>
            {!batch.can_confirm && <Code code="NO_VALID_ROWS" />}
          </Card>
          <Confirm open={askReplace} title={t("imp.confirm_replace")} danger onCancel={() => setAskReplace(false)} onConfirm={confirm}>
            <p>{t("imp.replace_help")}</p>
            <p className="mono">{batch.replaces_batch_id} → {batch.id}</p>
          </Confirm>
        </>
      )}
    </div>
  );
}
