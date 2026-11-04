import { useEffect, useState } from "react";
import { get, put } from "../api";
import { useI18n } from "../i18n";
import { Card, Confirm, ErrorBox, Field, FilterBar, Loading, OkBox, PageHeader, Pill, SourceBadge, YesNo, fmtNum, fmtPct, fmtTime, useAction,
  useAsync } from "../components/ui";
import { Icon } from "../components/icons";

const STATUS_PILL: Record<string, string> = { ACTIVE: "OK", DISABLED: "PENDING", PLANNED: "NEEDS_CONFIG", UNAVAILABLE: "FAILED" };
const ORDER = ["ACTIVE", "DISABLED", "UNAVAILABLE", "PLANNED"];

/** Read-only rows of the feature table: sku_code is switched by the model configuration (B1, never stored in the
 *  table), horizon is required (the DIRECT model's day number). */
const LOCKED: Record<string, string> = { sku_code: "ftab.sku_code_note", horizon: "ftab.horizon_note" };
type Rule = { enabled: boolean; contri: string };
const contriOk = (s: string) => s.trim() !== "" && Number.isFinite(Number(s)) && Number(s) > 0 && Number(s) <= 10;
const asForm = (rows: any[]): Record<string, Rule> =>
  Object.fromEntries(rows.map((r) => [r.feature, { enabled: !!r.enabled, contri: String(r.contri) }]));

/** 1.3.1 (B11) feature table: a switch and a priority coefficient (LightGBM feature_contri) per feature. Saved only
 *  after a confirmation showing the fingerprint note; it takes effect at the next training. The whole table is sent
 *  (the backend stores only the rows away from the default, and nothing when nothing changed). */
function FeatureTable() {
  const { t, pick } = useI18n();
  const tab = useAsync(() => get("/api/feature-table"), []);
  const act = useAction();
  const [form, setForm] = useState<Record<string, Rule>>({});
  const [ask, setAsk] = useState(false);
  const [note, setNote] = useState("");
  const d: any = tab.data;
  useEffect(() => { if (Array.isArray(d?.rows)) setForm(asForm(d.rows)); }, [d]);
  if (tab.loading && !d) return <Card icon="features" title={t("ftab.title")}><Loading /></Card>;
  if (!Array.isArray(d?.rows)) return <Card icon="features" title={t("ftab.title")}><ErrorBox error={tab.error} /></Card>;
  const rows: any[] = d.rows;
  const base = asForm(rows);
  const cur = (n: string) => form[n] ?? base[n];
  const set = (n: string, p: Partial<Rule>) => setForm((f) => ({ ...f, [n]: { ...(f[n] ?? base[n]), ...p } }));
  const dirty = rows.some((r) => JSON.stringify(cur(r.feature)) !== JSON.stringify(base[r.feature]));
  const invalid = rows.some((r) => !LOCKED[r.feature] && !contriOk(cur(r.feature).contri));
  const away = rows.filter((r) => r.feature !== "sku_code" && (!cur(r.feature).enabled || Number(cur(r.feature).contri) !== 1)).length;
  const save = async () => {
    const features = Object.fromEntries(rows.filter((r) => r.feature !== "sku_code")
      .map((r) => [r.feature, { enabled: cur(r.feature).enabled, contri: Number(cur(r.feature).contri) }]));
    const r = await act.run(() => put("/api/feature-table", { features, confirm: true, note: note.trim() || null }));
    if (r) {
      setAsk(false);
      setNote("");
      tab.setData(r);
      act.setOk(r.saved ? t("ftab.saved") : t("ftab.not_saved"));
    }
  };
  const history: any[] = Array.isArray(d.history) ? d.history : [];
  return (
    <Card icon="features" title={t("ftab.title")}>
      <div className="stack tight" data-testid="ftab">
        <p className="small muted">{t("ftab.help")}</p>
        <div className="alert info small" data-testid="ftab-fp-note">{pick(d.fingerprint_note)}</div>
        <p className="small">{t("ftab.effective")} · {t("ftab.updated")}: {d.updated_at ? fmtTime(d.updated_at) : "—"}</p>
        {!ask && <ErrorBox error={act.error} />}
        <OkBox text={act.ok} />
        <div className="scroll">
          <table className="tbl small" data-testid="ftab-table">
            <thead><tr><th>{t("ftab.feature")}</th><th>{t("ftab.group")}</th><th>{t("ftab.enabled")}</th><th className="num">{t("ftab.contri")}</th><th></th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const c = cur(r.feature);
                const locked = LOCKED[r.feature];
                const ok = !!locked || contriOk(c.contri);
                return (
                  <tr key={r.feature} data-testid={`ftab-row-${r.feature}`}>
                    <td className="mono">{r.feature}</td>
                    <td>{r.feature_group}</td>
                    <td><input type="checkbox" checked={c.enabled} disabled={!!locked || act.busy} data-testid={`ftab-on-${r.feature}`}
                      aria-label={`${t("ftab.enabled")} ${r.feature}`} onChange={(e) => set(r.feature, { enabled: e.target.checked })} /></td>
                    <td className="num">
                      <input type="number" min={0.01} max={10} step={0.1} value={c.contri} disabled={!!locked || act.busy} data-testid={`ftab-contri-${r.feature}`}
                        aria-label={`${t("ftab.contri")} ${r.feature}`} aria-invalid={!ok} onChange={(e) => set(r.feature, { contri: e.target.value })} />
                      {!ok && <div className="small bad-t">{t("ftab.contri_invalid")}</div>}
                    </td>
                    <td>{locked ? <span className="small muted">{t(locked)}</span>
                      : c.enabled && Number(c.contri) === 1 ? <span className="pill muted">{t("ftab.default")}</span>
                        : <span className="pill warn">{t("ftab.changed")}</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="row wrap">
          <button className="primary prod" data-testid="ftab-save" disabled={act.busy || !dirty || invalid} title={t("common.prod_action")}
            onClick={() => { act.setError(null); act.setOk(null); setAsk(true); }}><Icon name="save" />{t("ftab.save")}</button>
          <button data-testid="ftab-discard" disabled={act.busy || !dirty} onClick={() => setForm(base)}><Icon name="reset" />{t("ftab.discard")}</button>
          {dirty && <span className="small warn-t">{t("ftab.unsaved")}</span>}
        </div>
        <details className="small" data-testid="ftab-history">
          <summary>{t("ftab.history")} ({history.length})</summary>
          {history.length === 0 ? <p className="small muted">{t("ftab.no_history")}</p> : (
            <table className="tbl small">
              <thead><tr><th>{t("ftab.changed_at")}</th><th>{t("ftab.note_col")}</th></tr></thead>
              <tbody>{history.map((x, i) => <tr key={`${x.changed_at}-${i}`}><td className="nowrap">{fmtTime(x.changed_at)}</td><td>{x.note ?? "—"}</td></tr>)}</tbody>
            </table>
          )}
        </details>
      </div>
      <Confirm open={ask} title={t("ftab.confirm_title")} onCancel={() => setAsk(false)} onConfirm={save} confirmLabel={t("ftab.save")}
        disabled={act.busy}>
        <p data-testid="ftab-confirm-note">{pick(d.fingerprint_note)}</p>
        <p className="small">{t("ftab.n_changed")}: <b data-testid="ftab-away">{away}</b></p>
        <Field label={t("ftab.note")}>
          <input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} data-testid="ftab-note" />
        </Field>
        <ErrorBox error={act.error} />
      </Confirm>
    </Card>
  );
}

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
      <FeatureTable />
    </div>
  );
}
