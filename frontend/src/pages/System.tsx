import { useState } from "react";
import { get, post } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { Card, Empty, ErrorBox, OkBox, PageHeader, fmtBytes, fmtDatesInText, fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

export default function System() {
  const { t } = useI18n();
  const { status } = useSystem();
  const backups = useAsync(() => get("/api/system/backups"), []);
  const audit = useAsync(() => get("/api/audit?limit=200"), []);
  const paths = useAsync(() => get("/api/system/paths"), []);
  const act = useAction();
  const [health, setHealth] = useState<any>(null);
  const runCheck = async () => {
    const r = await act.run(() => get("/api/system/health-check?full=true"));
    if (r) setHealth(r);
  };
  const saveDiag = async () => {
    const r = await act.run(() => post("/api/system/diagnostics/save"));
    if (r) act.setOk(`${t("sys.diag_saved")}: ${r.dir} / ${r.file}`);
  };
  const backup = async () => {
    const r = await act.run(() => post("/api/system/backups"));
    if (r) act.setOk(`${t("common.saved")} ${r.file}`);
    backups.reload();
  };
  return (
    <div className="stack">
      <PageHeader icon="system" title={t("nav.system")} desc={t("page.system.desc")} />
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <Card icon="info" title={t("sys.install")}>
        <table className="tbl">
          <tbody>
            <tr><td>{t("sys.version")}</td><td>{status?.version}</td></tr>
            <tr><td>{t("sys.data_dir")}</td><td className="mono">{status?.data_dir}</td></tr>
            <tr><td>{t("sys.db_version")}</td><td>{status?.db_version}</td></tr>
          </tbody>
        </table>
      </Card>
      <Card icon="disk" title={t("sys.paths")} actions={<button onClick={paths.reload}><Icon name="refresh" />{t("common.refresh")}</button>}>
        <p className="small muted">{t("sys.paths_help")}</p>
        {paths.data && (
          <table className="tbl small">
            <thead><tr><th>{t("sys.item")}</th><th>{t("sys.path")}</th><th>{t("sys.from")}</th></tr></thead>
            <tbody>
              {[["sys.p.db", "db_path", "data_dir"], ["sys.p.data", "data_dir", "data_dir"], ["sys.p.logs", "logs_dir", "logs_dir"],
                ["sys.p.active_log", "active_log_file", "logs_dir"], ["sys.p.backups", "backups_dir", "backups_dir"],
                ["sys.p.reports", "reports_dir", "reports_dir"], ["sys.p.models", "models_dir", "data_dir"],
                ["sys.p.uploads", "uploads_dir", "data_dir"], ["sys.p.config", "storage_config", ""]].map(([label, k, src]) => (
                <tr key={k}><td>{t(label)}</td><td className="mono">{paths.data[k] ?? "—"}</td>
                  <td className="small">{src ? t(`sys.src.${String(paths.data.sources?.[src] ?? "").split(":")[0]}`) : (paths.data.storage_config_exists ? t("common.yes") : t("common.no"))}</td></tr>
              ))}
              <tr><td>{t("sys.p.exports")}</td><td colSpan={2} className="small">{t("sys.exports_note")}</td></tr>
            </tbody>
          </table>
        )}
        <p className="small muted">{t("sys.paths_change")}</p>
      </Card>
      <Card icon="quality" title={t("sys.diag")} actions={<>
        <button onClick={runCheck} disabled={act.busy}><Icon name="quality" />{t("sys.health_check")}</button>
        <a className="btn" href="/api/system/diagnostics.md"><Icon name="download" />{t("sys.diag_download")}</a>
        <button className="primary" onClick={saveDiag} disabled={act.busy}><Icon name="save" />{t("sys.diag_save")}</button>
      </>}>
        <p className="small muted">{t("sys.diag_help")}</p>
        {health && (
          <p>{health.integrity === "ok" && health.foreign_key_violations === 0
            ? <span className="pill ok">{t("sys.health_ok")}</span>
            : <span className="pill bad">{t("sys.health_bad")}: integrity={String(health.integrity)}, FK={health.foreign_key_violations}</span>}</p>
        )}
      </Card>
      <Card icon="backup" title={t("sys.backups")} actions={<button className="primary" onClick={backup} disabled={act.busy}><Icon name="backup" />{t("sys.backup_now")}</button>}>
        <p className="small mono">{backups.data?.dir}</p>
        {backups.data && !backups.data.files?.length ? <Empty text={t("sys.no_backups")} /> : (
          <div className="scroll">
            <table className="tbl small">
              <thead><tr><th>{t("sys.backup_file")}</th><th className="num">{t("sys.size")}</th></tr></thead>
              <tbody>{(backups.data?.files ?? []).map((f: any) => <tr key={f.file}><td className="mono">{f.file}</td><td className="num">{fmtBytes(f.size_bytes)}</td></tr>)}</tbody>
            </table>
          </div>
        )}
        <p className="small muted">{t("sys.restore_help")}</p>
      </Card>
      <Card icon="file" title={t("sys.audit")}>
        <div className="scroll">
          <table className="tbl small">
            <thead><tr><th>{t("common.created")}</th><th>{t("sys.action")}</th><th>{t("sys.entity")}</th><th></th></tr></thead>
            <tbody>
              {(audit.data ?? []).map((a: any) => (
                <tr key={a.id}><td className="nowrap">{fmtTime(a.at)}</td><td className="mono">{a.action}</td><td className="mono">{a.entity_type}:{a.entity_id}</td><td className="mono">{fmtDatesInText(JSON.stringify(a.details ?? {}).slice(0, 160))}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
