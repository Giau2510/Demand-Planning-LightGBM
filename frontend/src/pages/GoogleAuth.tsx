import { useEffect, useState } from "react";
import { get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, Code, ErrorBox, Field, OkBox, Pill, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

const PILL: Record<string, string> = { SIGNED_IN: "OK", IN_PROGRESS: "RUNNING", NOT_SIGNED_IN: "PENDING", CANCELLED: "SKIPPED",
  BLOCKED: "FAILED", ERROR: "FAILED", TIMEOUT: "FAILED", REVOKED: "FAILED", CLIENT_CHANGED: "FAILED" };

/** One-line verdict of the access check: sign-in problems vs permission problems vs network. */
function summaryKey(g: any): string {
  if (g.passed) return "ga.summary.ok";
  const c = g.first_failure?.code;
  if (["BQ_PERMISSION_DENIED", "BQ_NOT_FOUND", "BQ_API_DISABLED"].includes(c)) return "ga.summary.perm";
  if (c === "OAUTH_SCOPE_NOT_GRANTED") return "ga.summary.scope";
  if (["BQ_UNAVAILABLE", "BQ_TIMEOUT", "BQ_QUOTA"].includes(c)) return "ga.summary.network";
  if (c === "BQ_AUTH_EXPIRED") return "ga.summary.expired";
  if (["BQ_AUTH_MISSING", "OAUTH_NOT_CONFIGURED", "OAUTH_CLIENT_INVALID", "OAUTH_CLIENT_CHANGED"].includes(c)) return "ga.summary.signin";
  return "ga.summary.fail";
}

/** Plain-text request for the Google Cloud administrator, built from the real values of this machine. */
function adminChecklist(lang: string, d: any): string {
  const tg = d.target ?? {};
  const who = d.oauth?.email || (lang === "vi" ? "<email Google của người dùng>" : "<user's Google e-mail>");
  const vi = [
    "Yêu cầu cấp quyền Google Cloud cho ứng dụng Demand Forecasting (chỉ đọc BigQuery)",
    "1. Tạo OAuth client loại \"Desktop app\" (OAuth consent screen: Internal), scopes: openid, email, https://www.googleapis.com/auth/bigquery. Gửi file JSON của client qua kênh an toàn.",
    `2. Bật BigQuery API trên project ${tg.project || "<project>"} và trên project chứa OAuth client.`,
    `3. Cấp cho tài khoản ${who}:`,
    `   - roles/bigquery.jobUser trên project ${tg.project || "<project>"}`,
    `   - roles/bigquery.dataViewer trên dataset ${tg.project || "<project>"}.${tg.dataset || "<dataset>"} (location ${tg.location || "<location>"})`,
    `4. Bảng nguồn: ${tg.project || "<project>"}.${tg.dataset || "<dataset>"}.${tg.table || "<table>"}`,
    "Không cần gửi mật khẩu, token hay khóa service account.",
    `Máy: ${d.runtime?.computer ?? "?"} — tài khoản Windows: ${d.runtime?.windows_user ?? "?"}`,
  ];
  const en = [
    "Google Cloud access request for the Demand Forecasting app (BigQuery read-only)",
    "1. Create an OAuth client of type \"Desktop app\" (OAuth consent screen: Internal), scopes: openid, email, https://www.googleapis.com/auth/bigquery. Send the client JSON file through a secure channel.",
    `2. Enable the BigQuery API on project ${tg.project || "<project>"} and on the project that owns the OAuth client.`,
    `3. Grant the account ${who}:`,
    `   - roles/bigquery.jobUser on project ${tg.project || "<project>"}`,
    `   - roles/bigquery.dataViewer on dataset ${tg.project || "<project>"}.${tg.dataset || "<dataset>"} (location ${tg.location || "<location>"})`,
    `4. Source table: ${tg.project || "<project>"}.${tg.dataset || "<dataset>"}.${tg.table || "<table>"}`,
    "No password, token or service-account key is needed.",
    `Machine: ${d.runtime?.computer ?? "?"} — Windows account: ${d.runtime?.windows_user ?? "?"}`,
  ];
  return (lang === "vi" ? vi : en).join("\n");
}

/** Google authentication: who runs the backend, where ADC is looked up, and the in-app 'Sign in with Google'. */
export default function GoogleAuth({ onChange }: { onChange?: () => void }) {
  const { t, pick, lang } = useI18n();
  const id = useAsync(() => get("/api/bigquery/identity"), []);
  const act = useAction();
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [gates, setGates] = useState<any>(null);
  const o = id.data?.oauth;
  const r = id.data?.runtime;
  useEffect(() => { if (o && !clientId) setClientId(o.client_id ?? ""); }, [o?.client_id]);
  useEffect(() => {                       // poll while the browser sign-in is pending
    if (o?.status !== "IN_PROGRESS") return;
    const h = setInterval(() => id.reload(), 2000);
    return () => clearInterval(h);
  }, [o?.status]);
  useEffect(() => { if (o) onChange?.(); }, [o?.status]);
  if (!id.data) return id.error ? <ErrorBox error={id.error} /> : null;
  const run = async (path: string, body?: any, ok?: string) => { await act.run(() => post(path, body), ok); id.reload(); };
  const importFile = async (f: File | undefined) => {
    if (!f) return;
    // read in the browser, sent once, never stored by the app as a file (FileReader where Blob.text() is missing)
    const content = typeof (f as any).text === "function" ? await f.text() : await new Promise<string>((res, rej) => {
      const rd = new FileReader();
      rd.onload = () => res(String(rd.result ?? ""));
      rd.onerror = () => rej(rd.error);
      rd.readAsText(f);
    });
    await run("/api/bigquery/oauth/client-file", { content }, t("ga.client_file_ok"));
  };
  return (
    <Card icon="key" title={t("ga.title")}>
      <div data-testid="ga-identity" className="small">
        <p>{t("ga.runtime")}: <b className="mono">{r.windows_user}</b>{r.computer ? <> @ {r.computer}</> : null} · {t("ga.method")}: <b>{t(`ga.method.${r.effective_method}`)}</b></p>
        <p>{t("ga.adc_checked")}: <span className="mono">{r.adc_path_checked}</span> — <b>{r.adc_exists ? t("ga.exists") : t("ga.missing")}</b>
          {" · "}{t("ga.gac")}: {r.google_application_credentials_set ? t("ga.exists") : t("ga.missing")}
          {" · "}{t("ga.gcloud")}: {r.gcloud_on_path ? t("ga.exists") : t("ga.missing")}</p>
        <p className="muted">{pick(r.note)}</p>
      </div>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <div className="row wrap" data-testid="ga-status">
        <Pill status={PILL[o.status] ?? "PENDING"} label={t(`ga.state.${o.status}`)} />
        {o.email && <b className="mono">{o.email}</b>}
        {o.signed_in_at && o.status === "SIGNED_IN" && <span className="small muted">{fmtTime(o.signed_in_at)}</span>}
        {o.status === "SIGNED_IN" && (
          <span className="small" data-testid="ga-verified">{o.verified_at ? `${t("ga.verified_at")} ${fmtTime(o.verified_at)}` : t("ga.not_verified")}</span>
        )}
        {o.error && o.status !== "SIGNED_IN" && <span className="small bad-t"><Code code={o.error.code} />{o.error.detail ? ` — ${o.error.detail}` : ""}</span>}
      </div>
      <div className="row wrap">
        <button className="primary" data-testid="ga-signin" disabled={act.busy || !o.configured || o.status === "IN_PROGRESS"}
          onClick={() => run("/api/bigquery/oauth/start")}><Icon name="signin" />{t("ga.signin")}</button>
        {o.status === "IN_PROGRESS" && <button onClick={() => run("/api/bigquery/oauth/cancel")}>{t("ga.cancel")}</button>}
        <button data-testid="ga-signout" disabled={act.busy || o.status !== "SIGNED_IN" && o.status !== "REVOKED"}
          onClick={() => run("/api/bigquery/oauth/logout")}><Icon name="signout" />{t("ga.signout")}</button>
        {o.auth_url && <a href={o.auth_url} target="_blank" rel="noreferrer" className="small">{t("ga.open_link")} <Icon name="open" size={14} /></a>}
      </div>
      {o.status === "IN_PROGRESS" && <p className="small muted">{t("ga.redirect_hint")}</p>}
      {!o.configured && <div className="alert warn small" data-testid="ga-not-configured">{t("ga.not_configured")}</div>}
      <div className="row wrap">
        <button data-testid="ga-access" disabled={act.busy} onClick={async () => { setGates(null); const r = await act.run(() => post("/api/bigquery/access-check")); if (r) setGates(r); id.reload(); }}>
          <Icon name={act.busy ? "running" : "quality"} className={act.busy ? "spin" : undefined} />{act.busy ? t("ga.checking") : t("ga.access")}</button>
        {gates && <b className="small" data-testid="ga-access-summary">{t(summaryKey(gates))}</b>}
      </div>
      {gates && (
        <table className="tbl small" data-testid="ga-gates"><tbody>
          {gates.gates.map((g: any) => (
            <tr key={g.gate} data-status={g.status}><td>{t(`ga.gate.${g.gate}`)}</td>
              <td>{g.status === "PASS" ? <Pill status="OK" /> : g.status === "FAIL" ? <Pill status="FAILED" /> : <span className="muted">{t("ga.gate.NOT_RUN")}</span>}</td>
              <td>{g.status === "FAIL" ? <span data-testid={`ga-fix-${g.gate}`}><Code code={g.code} /></span>
                : g.gate === "auth" && g.account ? <span className="mono">{g.account}</span> : null}
                {g.detail ? <div className="mono muted">{`${typeof g.detail === "string" ? g.detail : JSON.stringify(g.detail)}`.slice(0, 200)}</div> : null}</td></tr>
          ))}
        </tbody></table>
      )}
      <details className="small" data-testid="ga-admin">
        <summary>{t("ga.admin_checklist")}</summary>
        <pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>{adminChecklist(lang, id.data)}</pre>
      </details>
      <details className="small">
        <summary>{t("ga.client")}</summary>
        <Field label={t("ga.client_file")}>
          <input type="file" accept=".json,application/json" data-testid="ga-client-file" disabled={act.busy}
            onChange={(e) => { importFile(e.target.files?.[0]); e.target.value = ""; }} />
        </Field>
        <p className="small muted">{t("ga.client_or_manual")}</p>
        <div className="form-grid">
          <Field label={t("ga.client_id")}><input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="xxxx.apps.googleusercontent.com" /></Field>
          <Field label={<>{t("ga.client_secret")} — {o.client_secret_set ? t("ga.secret_set") : t("ga.secret_not_set")}</>}>
            <input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} data-testid="ga-secret" />
          </Field>
        </div>
        <button disabled={act.busy || !clientId} onClick={async () => {
          await run("/api/bigquery/oauth/client", { client_id: clientId, client_secret: secret || null }, t("common.saved"));
          setSecret("");
        }}><Icon name="save" />{t("ga.save_client")}</button>
      </details>
    </Card>
  );
}
