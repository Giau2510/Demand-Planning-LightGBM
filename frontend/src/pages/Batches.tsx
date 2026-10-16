import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post } from "../api";
import { useSystem } from "../App";
import { useI18n } from "../i18n";
import { Card, Code, Confirm, Empty, ErrorBox, Loading, OkBox, Pill, SourceBadge, fmtDate, fmtNum, fmtTime, useAction, useAsync } from "../components/ui";

export default function Batches() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const sys = useSystem();
  const [showDemo, setShowDemo] = useState(false);
  const list = useAsync(() => get(`/api/imports?include_demo=${showDemo}`), [showDemo]);
  const [sel, setSel] = useState<string | null>(null);
  const det = useAsync(() => (sel ? get(`/api/imports/${sel}`) : Promise.resolve(null)), [sel]);
  const [del, setDel] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const act = useAction();

  const refresh = () => { list.reload(); det.reload(); sys.reload(); };
  const use = async (id: string) => { await act.run(() => post(`/api/imports/${id}/set-active`), t("common.saved")); refresh(); };
  const doDelete = async () => {
    const id = del!;
    setDel(null);
    await act.run(() => post(`/api/imports/${id}/delete`, { confirm_text: typed }), t("common.saved"));
    setTyped("");
    refresh();
  };
  const d = det.data;
  return (
    <div className="stack">
      <div className="row between">
        <h2>{t("nav.batches")}</h2>
        <label className="row small"><input type="checkbox" checked={showDemo} onChange={(e) => setShowDemo(e.target.checked)} /> DEMO</label>
      </div>
      <ErrorBox error={act.error || list.error} />
      <OkBox text={act.ok} />
      <Card>
        {list.loading ? <Loading /> : !list.data?.length ? <Empty text={t("bat.empty")} /> : (
          <div className="scroll">
            <table className="tbl click">
              <thead><tr><th>{t("imp.batch_id")}</th><th>{t("common.source")}</th><th>{t("imp.file")}</th><th>{t("common.status")}</th><th className="num">{t("imp.total")}</th><th className="num">{t("imp.valid")}</th><th className="num">{t("imp.errors")}</th><th className="num">{t("imp.dups")}</th><th>{t("imp.date_range")}</th><th>{t("common.created")}</th><th></th></tr></thead>
              <tbody>
                {list.data.map((b: any) => (
                  <tr key={b.id} className={b.id === sel ? "sel" : ""} onClick={() => setSel(b.id)}>
                    <td className="mono small">{b.id}</td><td><SourceBadge source={b.data_source} /></td><td>{b.file_name}</td>
                    <td><Pill status={b.status} /> {b.is_active_dataset && <Pill status="ACTIVE" label={t("bat.active_dataset")} />}</td>
                    <td className="num">{fmtNum(b.total_rows)}</td><td className="num">{fmtNum(b.valid_rows)}</td><td className="num">{fmtNum(b.error_rows)}</td><td className="num">{fmtNum(b.duplicate_rows)}</td>
                    <td className="small">{fmtDate(b.min_order_date)} → {fmtDate(b.max_order_date)}</td><td className="small">{fmtTime(b.created_at)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {b.status === "ACTIVE" && b.data_source === "MANUAL_IMPORT" && (
                        <div className="row">
                          {!b.is_active_dataset && <button onClick={() => use(b.id)}>{t("bat.use")}</button>}
                          <button onClick={() => nav(`/import?replace=${b.id}`)}>{t("bat.replace")}</button>
                          <button className="danger" onClick={() => setDel(b.id)}>{t("bat.delete")}</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {d && (
        <Card title={`${t("common.details")}: ${d.id}`} actions={d.issue_count > 0 ? <a className="btn" href={`/api/imports/${d.id}/errors.xlsx?lang=${lang}`}>{t("imp.error_report")}</a> : null}>
          <table className="tbl small">
            <tbody>
              <tr><td>{t("imp.file")}</td><td>{d.file_name} {d.sheet_name ? `· ${d.sheet_name}` : ""}</td></tr>
              <tr><td>{t("common.status")}</td><td><Pill status={d.status} /></td></tr>
              <tr><td>{t("common.created")}</td><td>{fmtTime(d.created_at)}</td></tr>
              <tr><td>{t("bat.confirmed")}</td><td>{fmtTime(d.confirmed_at)}</td></tr>
              {d.replaces_batch_id && <tr><td>{t("bat.replaces")}</td><td className="mono">{d.replaces_batch_id}</td></tr>}
              {d.replaced_by_batch_id && <tr><td>{t("bat.replaced_by")}</td><td className="mono">{d.replaced_by_batch_id}</td></tr>}
              <tr><td>{t("imp.column")}</td><td className="mono">{Object.entries(d.column_mapping ?? {}).filter(([, v]) => v).map(([k, v]) => `${k}←${v}`).join(", ")}</td></tr>
            </tbody>
          </table>
          <table className="tbl small">
            <tbody>
              {(d.validation?.issues_by_code ?? []).map((i: any) => (
                <tr key={i.code}><td><Pill status={i.severity} /></td><td className="num">{fmtNum(i.count)}</td><td><Code code={i.code} /></td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <Confirm open={!!del} danger title={`${t("bat.delete")}: ${del}`} onCancel={() => { setDel(null); setTyped(""); }} onConfirm={doDelete} disabled={typed !== del}>
        <p>{t("bat.delete_help")}</p>
        <p className="mono">{del}</p>
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
      </Confirm>
    </div>
  );
}
