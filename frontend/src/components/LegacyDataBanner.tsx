import { Link } from "react-router-dom";
import { useI18n } from "../i18n";

/** 1.4.11: "being updated" notice at the top of the pages whose figures are still the legacy (pre-SEL2) ones
 *  (Dashboard, Forecast explainer, Model quality). Warning style, not dismissible; points to the official numbers. */
export default function LegacyDataBanner() {
  const { t } = useI18n();
  return (
    <div className="alert warn" role="status" data-testid="legacy-banner">
      {t("legacy.banner_before")}
      <Link to="/daily-forecast" data-testid="legacy-banner-link">{t("nav.daily")}</Link>
      {t("legacy.banner_after")}
    </div>
  );
}
