import { useI18n } from "../i18n";
import { Pill, fmtDate, fmtNum, fmtTime } from "./ui";

/** Cells and notices shared by the forecast pages (1.4.14: moved out of Results.tsx, which re-exports them, so the daily
 *  forecast page and the legacy Results page render exactly the same thing). */

export function ActualCell({ value, actual }: { value: number | null | undefined; actual: any }) {
  const { t } = useI18n();
  if (value === null || value === undefined) return <span className="muted small" title={actual ? t(`actual.status.${actual.status}`) : ""}>—</span>;
  return (
    <span title={`${t("actual.as_of")} ${fmtTime(actual?.as_of)} · ${t(`actual.status.${actual?.status}`)}${actual?.is_demo ? " · DEMO" : ""}`}>
      {fmtNum(value, 1)}{actual?.status === "STALE" && <span className="warn-t"> *</span>}
    </span>
  );
}

/** 1.2.4: product name next to the SKU, or exactly "no product name yet" (never another SKU's name). */
export function ProductName({ name }: { name?: string | null }) {
  const { t } = useI18n();
  return name ? <span data-testid="product-name">{name}</span> : <span className="muted small" data-testid="product-name-missing">{t("fc.no_product_name")}</span>;
}

/** 1.4.6: column cach_tinh of the daily Excel - SEL2 (days 1..7) or the weekly estimate (days 8..20, marked). */
export function CachTinh({ code }: { code?: string | null }) {
  const { t } = useI18n();
  if (!code) return <span className="muted small">—</span>;
  return code === "SEL2" ? <span className="small muted" data-testid="cach-tinh">{t("fc.cach.SEL2")}</span>
    : <span title={code} data-testid="cach-tinh-estimate"><Pill status="WARNING" label={t(`fc.cach.${code}`)} /></span>;
}

export function ActualNotice({ actual, run }: { actual: any; run?: any }) {
  const { t } = useI18n();
  if (!actual) return null;
  if (actual.status === "NOT_APPLICABLE") return <p className="small muted">{t("actual.status.NOT_APPLICABLE")}</p>;
  if (actual.status === "NO_DATA_TODAY") return <p className="small muted">{t("actual.none_today")}</p>;
  return (
    <div className={`alert ${actual.status === "STALE" ? "warn" : "info"} small`}>
      <b>{t("actual.title")}</b>: {t("actual.as_of")} <b>{fmtTime(actual.as_of)}</b> {t("common.vn_time")} ({t(`actual.status.${actual.status}`)})
      {actual.is_demo && <> · <span className="src src-DEMO">DEMO</span> {t("actual.demo_note")}</>}
      {actual.source_updated_max && <> · {t("actual.source_updated")}: {fmtTime(actual.source_updated_max)}</>}
      <br />{t("actual.partial_warning")}
      {run && run.data_as_of && actual.date && run.forecast_origin !== actual.date && actual.in_horizon && (
        <><br /><span className="warn-t">{t("actual.old_run_warning")} ({t("fc.data_as_of")}: {fmtDate(run.data_as_of)})</span></>
      )}
      {actual.in_horizon === false && <><br />{t("actual.not_in_horizon")}</>}
    </div>
  );
}
