import { useState } from "react";
import { get } from "../api";
import { useI18n } from "../i18n";
import { Card, ErrorBox, FilterBar, Loading, PageHeader, Pill, SourceBadge, YesNo, fmtNum, fmtPct, useAsync } from "../components/ui";

const STATUS_PILL: Record<string, string> = { ACTIVE: "OK", DISABLED: "PENDING", PLANNED: "NEEDS_CONFIG", UNAVAILABLE: "FAILED" };
const ORDER = ["ACTIVE", "DISABLED", "UNAVAILABLE", "PLANNED"];

export default function Features() {
  const { t, pick, lang } = useI18n();
  const [source, setSource] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [group, setGroup] = useState<string>("");
  const reg = useAsync(() => get(`/api/features/registry${source ? `?source=${source}` : ""}`), [source]);
  const header = <PageHeader icon="features" title={t("nav.features")} desc={t("feat.help")} />;
  if (reg.loading && !reg.data) return <div className="stack">{header}<Loading /></div>;
  if (reg.error) return <div className="stack">{header}<ErrorBox error={reg.error} /></div>;
  const d = reg.data;
  const L = (x: any) => (x ? x[lang] ?? x.vi : "");
  const entries = (d.entries as any[]).filter((e) => (!status || e.availability_status === status) && (!group || e.feature_group === group))
    .sort((a, b) => ORDER.indexOf(a.availability_status) - ORDER.indexOf(b.availability_status));
  return (
    <div className="stack">
      {header}
      <Card>
        <FilterBar active={[source, status, group].filter(Boolean).length} onClear={() => { setSource(""); setStatus(""); setGroup(""); }}>
          <label className="field">
            <span className="field-l">{t("feat.source")}</span>
            <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="feature-source">
              <option value="">{d.source} ({t("feat.active_source")})</option>
              {["DEMO", "MANUAL_IMPORT", "BIGQUERY"].map((s) => <option key={s} value={s}>{t(`source.${s}`)}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-l">{t("feat.group")}</span>
            <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="feature-group">
              <option value="">{t("feat.group")}: {t("feat.all")}</option>
              {Object.entries(d.groups).map(([k, v]: [string, any]) => <option key={k} value={k}>{L(v)}</option>)}
            </select>
          </label>
          <div className="field">
            <span className="field-l">{t("feat.status")}</span>
            <div className="row wrap" data-testid="feat-counts">
              {ORDER.map((s) => (
                <button key={s} className={status === s ? "primary" : ""} aria-pressed={status === s} onClick={() => setStatus(status === s ? "" : s)}>
                  {L(d.statuses[s])}: <b>{d.counts[s]}</b>
                </button>
              ))}
            </div>
          </div>
        </FilterBar>
        <div className="row wrap small mid sep">
          <SourceBadge source={d.source} />
          {d.scope && <span className="mono">{d.scope.label}</span>}
          {d.scope_error && <span className="bad-t">{pick(d.scope_error)}</span>}
          <span>{t("feat.coverage")}: {t("feat.cov_price")} {fmtPct(d.coverage?.avg_unit_price)} · {t("feat.cov_discount")} {fmtPct(d.coverage?.avg_discount_rate)} · {t("feat.cov_promo")} {fmtPct(d.coverage?.promo_share)} ({fmtNum(d.coverage?.rows ?? 0)} {t("feat.cov_rows")})</span>
        </div>
      </Card>
      <div className="grid2">
        <Card icon="model" title={t("feat.next")}>
          <p className="small" data-testid="feat-next">{t("feat.version")}: <span className="mono">{d.next_training.feature_set_version}</span> · {d.next_training.n_features} feature</p>
          <p className="small mono muted">{d.next_training.features.join(", ")}</p>
          {Object.entries(d.decisions ?? {}).map(([g, x]: [string, any]) => (
            <p key={g} className="small">{g}: {x.used ? <Pill status="OK" label={L(d.statuses.ACTIVE)} /> : <Pill status="FAILED" label={x.reason} />} {t("feat.coverage")} {fmtPct(x.coverage)} (≥ {fmtPct(x.min_coverage)})</p>
          ))}
        </Card>
        <Card icon="ok" title={t("feat.active_model")}>
          {d.active_model ? (
            <div className="small" data-testid="feat-active-model">
              <p><span className="mono">{d.active_model.model_version}</span> · {d.active_model.features.length} feature</p>
              <p>{t("feat.version")}: <span className="mono">{d.active_model.feature_set_version}</span> {!d.active_model.feature_set_version_stored && <span className="muted">{t("feat.recomputed")}</span>}</p>
            </div>
          ) : <p className="small muted">—</p>}
        </Card>
      </div>
      <Card icon="features" title={t("feat.registry")}>
        <div className="scroll">
          <table className="tbl small" data-testid="feat-table">
            <thead><tr><th>{t("feat.key")}</th><th>{t("feat.group")}</th><th>{t("feat.status")}</th><th>{t("feat.reason")}</th><th>{t("feat.column")}</th><th>{t("feat.missing")}</th><th>{t("feat.agg")}</th><th>{t("feat.in_model")}</th></tr></thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.feature_key} data-status={e.availability_status}>
                  <td><span className="mono">{e.feature_key}</span><div className="muted">{L(e.display_name)}</div></td>
                  <td>{L(d.groups[e.feature_group])}</td>
                  <td><Pill status={STATUS_PILL[e.availability_status]} label={L(e.status_label)} /></td>
                  <td>{L(e.reason_label)}</td>
                  <td className="mono">{e.source_column ?? "—"}{e.reference_field ? <div className="muted">ref: {e.reference_field}</div> : null}</td>
                  <td>{e.default_or_missing_policy ? L(e.default_or_missing_policy) : <span className="muted">{t("feat.undecided")}</span>}</td>
                  <td>{e.aggregation_rule ?? <span className="muted">{t("feat.undecided")}</span>}</td>
                  <td><YesNo v={e.in_active_model} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">Registry {d.registry_version} · code {d.feature_code_version}</p>
      </Card>
    </div>
  );
}
