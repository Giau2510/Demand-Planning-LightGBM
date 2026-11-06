import { get } from "../api";
import { useI18n } from "../i18n";
import { fmtDate, useAsync } from "./ui";

/** 1.4.4: one line on every forecast page - "Nguồn: <SEL2 run id | LightGBM cũ | Avg> - làm mới lúc <time VN> - dữ
 *  liệu đến <data cut-off date>" (GET /api/forecast-info: newest SEL2 run of the active scope, else the newest 1.3.x
 *  run, else the newest AVG_DEMAND read). Read-only; renders nothing while loading or on an error. `info` given (the
 *  history page: GET /api/history/overview carries it) -> no request of its own. */
export default function ForecastInfoLine({ info: given }: { info?: any }) {
  const { t } = useI18n();
  const info = useAsync(() => (given !== undefined ? Promise.resolve(null) : get("/api/forecast-info")), [given === undefined]);
  const i: any = given !== undefined ? given : info.data;
  if (!i) return null;
  if (!i.source) return <p className="small muted" data-testid="forecast-info">{t("finfo.source")}: {t("finfo.none")}</p>;
  const src = i.source === "SEL2" ? `${t("finfo.src.SEL2")} ${i.run_id}` : t(`finfo.src.${i.source}`);
  return (
    <p className="small muted" data-testid="forecast-info">
      {t("finfo.source")}: <b className="mono">{src}</b>
      {" - "}{t("finfo.refreshed")} {i.refreshed_at ?? "—"}
      {" - "}{t("finfo.data_to")} {i.data_cutoff_date ? fmtDate(i.data_cutoff_date) : "—"}
      {i.config_flag && <span className="warn-t" data-testid="forecast-info-flag">{" - "}{t("finfo.config_incomplete")}</span>}
    </p>
  );
}
