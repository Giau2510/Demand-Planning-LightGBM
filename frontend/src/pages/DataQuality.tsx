import { useState } from "react";
import { get } from "../api";
import { useI18n } from "../i18n";
import { Card, Code, ErrorBox, Loading, Pill, SourceBadge, Stat, Term, fmtDate, fmtDateish, fmtNum, fmtPct, fmtTime, useAsync } from "../components/ui";

export default function DataQuality() {
  const { t } = useI18n();
  const [n, setN] = useState(0);
  const rep = useAsync(() => get(`/api/data-quality${n ? "?refresh=true" : ""}`), [n]);
  if (rep.loading && !rep.data) return <Loading />;
  const r = rep.data;
  const s = r?.stats ?? {};
  return (
    <div className="stack">
      <div className="row between">
        <h2>{t("nav.quality")}</h2>
        <button onClick={() => setN(n + 1)}>{t("dq.recheck")}</button>
      </div>
      <ErrorBox error={rep.error} />
      {r && (
        <>
          <div className="grid4">
            <Stat label={t("common.source")} value={<SourceBadge source={r.scope?.data_source} />} sub={<span className="mono small">{s.batch_id ?? r.scope?.scope_key}</span>} />
            <Stat label={t("dq.checked_at")} value={<span className="small">{fmtTime(r.checked_at)}</span>} />
            <Stat label={t("dq.can_train")} value={r.can_train ? <Pill status="OK" label={t("common.yes")} /> : <Pill status="FAILED" label={t("common.no")} />} />
            <Stat label={t("dq.can_publish")} value={r.can_publish ? <Pill status="OK" label={t("common.yes")} /> : <Pill status="FAILED" label={t("common.no")} />} />
          </div>
          <div className="grid4">
            <Stat label={t("dq.rows_read")} value={fmtNum(s.rows_read)} />
            <Stat label={t("dq.rows_valid")} value={fmtNum(s.rows_valid)} />
            <Stat label={t("dq.rows_rejected")} value={fmtNum(s.rows_rejected)} tone={s.rows_rejected ? "warn" : ""} />
            <Stat label={t("dq.duplicates")} value={fmtNum(s.duplicate_rows)} />
          </div>
          <div className="grid4">
            <Stat label={<Term id="freshness">{t("dq.latest_date")}</Term>} value={fmtDate(s.max_date)} sub={s.data_lag_days !== undefined ? `${t("dash.lag")}: ${s.data_lag_days} ${t("common.days")}` : undefined} />
            <Stat label={t("dq.history")} value={`${fmtNum(s.history_days)} ${t("common.days")}`} sub={`${fmtDate(s.min_date)} → ${fmtDate(s.max_date)}`} />
            <Stat label="SKU / FC" value={`${fmtNum(s.n_skus)} / ${fmtNum(s.n_fcs)}`} sub={`${fmtNum(s.n_series)} ${t("common.series")}`} />
            <Stat label={t("dq.zero_share")} value={fmtPct(s.zero_demand_share)} />
          </div>
          <Card title={t("dq.checks")}>
            <p className="small muted">{t("dq.explain")}</p>
            <table className="tbl">
              <thead><tr><th>{t("imp.severity")}</th><th>{t("imp.explain")}</th><th className="num">#</th><th></th></tr></thead>
              <tbody>
                {r.checks.map((c: any, i: number) => (
                  <tr key={i}>
                    <td><Pill status={c.severity} /></td>
                    <td><Code code={c.code} /> {c.row_level && <span className="small muted">{t("dq.row_level")}</span>}</td>
                    <td className="num">{fmtNum(c.count)}</td>
                    <td className="small mono">{(c.examples ?? []).slice(0, 6).map((x: any) => fmtDateish(x)).join(", ")}{c.required ? ` (min ${c.required})` : ""}{c.max_allowed ? ` (max ${c.max_allowed})` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
