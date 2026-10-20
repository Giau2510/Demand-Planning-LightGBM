import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { useI18n } from "../i18n";
import { Card, ErrorBox, Loading, OkBox, PageHeader, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

const FIELDS = ["order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price", "discount_amount",
  "promotion_flag", "promotion_id", "voucher_flag", "voucher_amount", "source_updated_at", "batch_id"];
const REF_FIELDS = ["product_id", "item_code", "outbound_qty", "order_status", "sales_price", "price_after_discount",
  "seller_code", "sku_status", "open_date", "open_hours", "open_days"];
/** 1.2.9: role of every field - the same table as the backend (settings_service.FIELD_ROLES); the backend's own copy
 *  (/api/bigquery/status field_roles) wins when it is there. */
const DEFAULT_ROLES: Record<string, string> = {
  order_id: "KEY", created_at: "KEY", order_date: "KEY", sku_id: "KEY", fc_id: "KEY", order_qty: "TARGET",
  unit_price: "OPTIONAL_FEATURE", discount_amount: "OPTIONAL_FEATURE", promotion_flag: "OPTIONAL_FEATURE",
  promotion_id: "REFERENCE", voucher_flag: "REFERENCE", voucher_amount: "REFERENCE", source_updated_at: "REFERENCE",
  batch_id: "REFERENCE", product_id: "REFERENCE", item_code: "REFERENCE", outbound_qty: "REFERENCE",
  order_status: "REFERENCE", sales_price: "REFERENCE", price_after_discount: "REFERENCE", seller_code: "REFERENCE",
  sku_status: "REFERENCE", open_date: "REFERENCE", open_hours: "REQUIRED_FEATURE", open_days: "REFERENCE",
};
const ROLE_ORDER = ["KEY", "TARGET", "REQUIRED_FEATURE", "OPTIONAL_FEATURE", "REFERENCE"];
type FM = Record<string, { column: string | null; usage: string }>;
type Col = { name: string; type: string };

function RoleBadge({ role }: { role: string | null }) {
  const { t } = useI18n();
  const cls = { KEY: "pill info", TARGET: "pill ok", REQUIRED_FEATURE: "pill warn" }[role ?? ""] ?? "pill";
  return <span className={cls} data-role={role ?? "UNCLASSIFIED"}>{t(`map.role.${role ?? "UNCLASSIFIED"}`)}</span>;
}

function MappingTable({ fields, m, setM, cols, types, check, reference, roles }: {
  fields: string[]; m: FM; setM: (x: FM) => void; cols: Col[]; types: Record<string, string>;
  check: any; reference?: boolean; roles: Record<string, string>;
}) {
  const { t } = useI18n();
  const usages = reference ? ["OPTIONAL", "UNUSED"] : ["REQUIRED", "OPTIONAL", "UNUSED"];
  return (
    <table className="tbl" data-testid={reference ? "map-ref" : "map-key"}>
      <thead><tr><th>{t("imp.field")}</th><th>{t("map.role")}</th><th>{t("map.usage")}</th><th>{t("imp.column")}</th><th>{t("map.type")}</th></tr></thead>
      <tbody>
        {fields.map((f) => {
          const cur = m[f] ?? { column: null, usage: "OPTIONAL" };
          const err = check?.errors?.find((e: any) => e.field === f && !!e.reference === !!reference);
          // a mandatory model input (SKU open hours) cannot be switched off: only its column is chosen here
          const mandatory = reference && roles[f] === "REQUIRED_FEATURE";
          return (
            <tr key={f} className={err ? "row-bad" : ""} data-testid={`map-row-${f}`}>
              <td><span className="mono">{f}</span><div className="small muted">{t(`mapf.${f}`)}</div></td>
              <td><RoleBadge role={roles[f] ?? null} /></td>
              <td>
                {mandatory
                  ? <span className="small" data-testid={`usage-locked-${f}`}>{t("map.usage.MANDATORY")}</span>
                  : <select aria-label={`usage-${f}`} value={cur.usage} onChange={(e) => setM({ ...m, [f]: { ...cur, usage: e.target.value } })}>
                      {usages.map((u) => <option key={u} value={u}>{t(`map.usage.${u}`)}</option>)}
                    </select>}
              </td>
              <td>
                <select aria-label={`column-${f}`} value={cur.column ?? ""} disabled={!mandatory && cur.usage === "UNUSED"}
                  onChange={(e) => setM({ ...m, [f]: { column: e.target.value || null, usage: mandatory && cur.usage === "UNUSED" ? "OPTIONAL" : cur.usage } })}>
                  <option value="">{t("imp.not_used")}</option>
                  {cols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  {cur.column && !types[cur.column] && <option value={cur.column}>{cur.column} (?)</option>}
                </select>
              </td>
              <td className="small mono">{cur.column ? types[cur.column] ?? "?" : ""} {err && <span className="bad-t">{err.code}{err.expected ? ` (${err.expected.join("/")})` : ""}</span>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** 1.2.9: every column of the D-1 source with the role it plays. A column no field uses is "not classified" until the
 *  user marks it as a reference column (shown, never read by D-1, never a model input); nothing becomes a key, the
 *  target or a model input because it exists. One column feeding two of key / target / model input is a conflict. */
export function SourceColumns({ cols, m, refM, extra, setExtra, roles }: {
  cols: Col[]; m: FM; refM: FM; extra: string[]; setExtra: (x: string[]) => void; roles: Record<string, string>;
}) {
  const { t } = useI18n();
  const used: Record<string, string[]> = {};
  for (const fm of [m, refM]) {
    for (const [f, v] of Object.entries(fm)) {
      if (v && v.column && v.usage !== "UNUSED") (used[v.column] ??= []).push(f);
    }
  }
  const names = new Set(cols.map((c) => c.name));
  const rows = [...cols.map((c) => ({ ...c, missing: false })),
    ...Object.keys(used).filter((n) => !names.has(n)).map((n) => ({ name: n, type: "", missing: true }))];
  const counts: Record<string, number> = {};
  return (
    <table className="tbl" data-testid="map-columns">
      <thead><tr><th>{t("imp.column")}</th><th>{t("map.type")}</th><th>{t("map.role")}</th><th>{t("map.col_fields")}</th></tr></thead>
      <tbody>
        {rows.map((c) => {
          const fs = used[c.name] ?? [];
          const fieldRoles = fs.map((f) => roles[f] ?? "REFERENCE");
          const role = fs.length ? ROLE_ORDER.find((r) => fieldRoles.includes(r)) ?? "REFERENCE"
            : extra.includes(c.name) ? "REFERENCE" : null;
          const modelRoles = fieldRoles.filter((r) => r !== "REFERENCE");
          const conflict = modelRoles.length > 1;
          counts[role ?? "UNCLASSIFIED"] = (counts[role ?? "UNCLASSIFIED"] ?? 0) + 1;
          return (
            <tr key={c.name} className={conflict || c.missing ? "row-bad" : ""} data-testid={`map-col-${c.name}`}>
              <td className="mono">{c.name}</td>
              <td className="small mono">{c.missing ? t("map.col_missing") : c.type}</td>
              <td>
                {fs.length ? <RoleBadge role={role} /> : (
                  <select aria-label={`classify-${c.name}`} value={extra.includes(c.name) ? "REFERENCE" : ""}
                    onChange={(e) => setExtra(e.target.value ? [...extra, c.name] : extra.filter((x) => x !== c.name))}>
                    <option value="">{t("map.role.UNCLASSIFIED")}</option>
                    <option value="REFERENCE">{t("map.role.EXTRA_REFERENCE")}</option>
                  </select>
                )}
                {conflict && <div className="bad-t small" data-testid={`map-conflict-${c.name}`}>{t("map.col_conflict")}</div>}
              </td>
              <td className="small">{fs.length ? fs.map((f) => <span key={f} className="mono">{f} </span>) : <span className="muted">—</span>}</td>
            </tr>
          );
        })}
      </tbody>
      <tfoot><tr><td colSpan={4} className="small muted" data-testid="map-col-counts">
        {[...ROLE_ORDER, "UNCLASSIFIED"].filter((r) => counts[r]).map((r) => `${t(`map.role.${r}`)}: ${counts[r]}`).join(" · ")}
      </td></tr></tfoot>
    </table>
  );
}

/** 1.2.9: day of week as a model input - the SAME setting as the Model configuration page (model.feature_weekday),
 *  shown here next to the date column it is computed from. Saved only with its own button; an unsaved change says so. */
export function WeekdayCard() {
  const { t } = useI18n();
  const s = useAsync(() => get("/api/settings"), []);
  const act = useAction();
  const model = s.data?.model;
  const saved: boolean | null = model ? (model.feature_weekday ?? model.feature_calendar ?? true) : null;
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => { if (saved !== null) setOn(saved); }, [saved]);
  if (!model) return s.loading ? <Card icon="calendar" title={t("map.weekday_title")}><Loading /></Card> : null;
  const dirty = on !== null && on !== saved;
  const save = async () => {
    const r = await act.run(() => put("/api/settings/model", { ...model, feature_weekday: on }), t("common.saved"));
    if (r) s.reload();
  };
  return (
    <Card icon="calendar" title={t("map.weekday_title")} actions={
      <button className="primary" onClick={save} disabled={act.busy || !dirty} data-testid="map-weekday-save"><Icon name="save" />{t("common.save")}</button>}>
      <ErrorBox error={act.error} />
      <OkBox text={act.ok} />
      <label className="row">
        <input type="checkbox" data-testid="map-weekday" checked={!!on} onChange={(e) => setOn(e.target.checked)} />
        <b>{t("map.weekday_label")}</b>
      </label>
      <p className="small muted">{t("map.weekday_desc")}</p>
      <p className="small" data-testid="map-weekday-state">
        {dirty ? <span className="warn-t">{t("map.weekday_unsaved")}</span>
          : t(saved ? "map.weekday_saved_on" : "map.weekday_saved_off")}
        {model.feature_weekday === null || model.feature_weekday === undefined ? ` ${t("map.weekday_default")}` : ""}
      </p>
    </Card>
  );
}

export default function Mapping() {
  const { t } = useI18n();
  const st = useAsync(() => get("/api/bigquery/status"), []);
  const [cols, setCols] = useState<Col[]>([]);
  const [drift, setDrift] = useState<any>(null);
  const [m, setM] = useState<FM>({});
  const [ref, setRef] = useState<FM>({});
  const [extra, setExtra] = useState<string[]>([]);
  const [customer, setCustomer] = useState<string>("");
  const [check, setCheck] = useState<any>(null);
  const [notes, setNotes] = useState<any[] | null>(null);
  const act = useAction();
  useEffect(() => {
    if (st.data) {
      setM(st.data.settings.field_mapping);
      setRef(st.data.settings.reference_mapping ?? {});
      setCols(st.data.settings.schema_snapshot ?? []);
      setExtra(st.data.settings.extra_reference_columns ?? []);
      setCustomer(st.data.settings.customer_id_column ?? "");
    }
  }, [st.data]);
  const header = <PageHeader icon="mapping" title={t("nav.mapping")} desc={t("map.help")} />;
  if (st.loading) return <div className="stack">{header}<Loading /></div>;
  const roles: Record<string, string> = { ...DEFAULT_ROLES, ...(st.data?.field_roles ?? {}) };
  const configured = st.data?.settings?.dataset_id && st.data?.settings?.source_table;
  const readSchema = async () => {
    const r = await act.run(() => post("/api/bigquery/schema"));
    if (r) { setCols(r.columns); setDrift(r.drift); setCheck(r.mapping_check); }
  };
  const suggest = async () => {
    const r = await act.run(() => post("/api/bigquery/suggest-mapping"));
    if (r) { setCols(r.columns); setM(r.field_mapping); setRef(r.reference_mapping); setCheck(r.check); setNotes(r.notes); }
  };
  // 1.2.3: saving a mapping always switches BigQuery production mode off until a new full-period validation and
  // activation - say it BEFORE (confirm) and AFTER (warning), the 17/10 SOURCE_NOT_READY came from a silent switch-off
  const prodOn = !!st.data?.settings?.production_enabled;
  const save = async () => {
    if (prodOn && !window.confirm(t("map.save_prod_confirm"))) return;
    const r = await act.run(() => post("/api/bigquery/mapping", { field_mapping: m, reference_mapping: ref, extra_reference_columns: extra, customer_id_column: customer }), t("common.saved"));
    if (r) {
      setCheck(r.check);
      if (r.production_switched_off) act.setOk(`${t("common.saved")} — ${t("map.prod_switched_off")}`);
      st.reload();
    }
  };
  const types = Object.fromEntries(cols.map((c) => [c.name, c.type]));
  const hasDrift = drift && (drift.removed.length || drift.added.length || drift.type_changed.length);
  return (
    <div className="stack">
      {header}
      {!configured && <div className="alert warn">{t("bq.not_configured")} {t("bq.blocked_note")}</div>}
      {configured && <div className="alert warn small" data-testid="map-prod-state">
        {prodOn ? t("map.prod_on_note") : t("map.prod_off_note")}</div>}
      <ErrorBox error={act.error || st.error} />
      <OkBox text={act.ok} />
      {hasDrift ? <div className="alert bad">{t("map.drift")}: {JSON.stringify(drift)}</div> : null}
      <Card icon="mapping" title={t("map.key_fields")} actions={<>
        <button onClick={readSchema} disabled={act.busy || !configured}><Icon name="bigquery" />{t("bq.schema")}</button>
        <button onClick={suggest} disabled={act.busy || !configured} data-testid="map-suggest"><Icon name="mapping" />{t("map.suggest")}</button>
        <button className={prodOn ? "primary prod" : "primary"} onClick={save} disabled={act.busy || !configured} title={prodOn ? t("map.save_prod_confirm") : undefined}>
          {prodOn ? <Icon name="prod" /> : <Icon name="save" />}{t("map.save")}</button>
      </>}>
        <p className="small muted">{t("map.suggest_note")}</p>
        <p className="small muted">{t("map.roles_note")}</p>
        {!cols.length && <p className="small muted">{t("map.read_schema_first")}</p>}
        <MappingTable fields={FIELDS} m={m} setM={setM} cols={cols} types={types} check={check} roles={roles} />
      </Card>
      <Card icon="file" title={t("map.ref_fields")}>
        <MappingTable fields={REF_FIELDS} m={ref} setM={setRef} cols={cols} types={types} check={check} reference roles={roles} />
      </Card>
      {check && !check.ok && <div className="alert bad">{t("map.errors")}: {check.errors.map((e: any) => `${e.field}: ${e.code}${e.column ? ` (${e.column})` : ""}`).join("; ")}</div>}
      {check?.warnings?.length > 0 && <p className="small muted">{check.warnings.map((w: any) => `${w.field}: ${w.code}`).join("; ")}</p>}
      <Card icon="features" title={t("map.columns_title")}>
        <p className="small muted">{t("map.columns_note")}</p>
        {cols.length ? <SourceColumns cols={cols} m={m} refM={ref} extra={extra} setExtra={setExtra} roles={roles} />
          : <p className="small muted">{t("map.read_schema_first")}</p>}
      </Card>
      <Card icon="file" title={t("map.customer_title")}>
        <p className="small muted">{t("map.customer_note")}</p>
        <select data-testid="map-customer" value={customer} onChange={(e) => setCustomer(e.target.value)}>
          <option value="">{t("map.customer_none")}</option>
          {cols.filter((c) => ["STRING", "INTEGER", "INT64"].includes(String(c.type).toUpperCase()) || c.name === customer)
            .map((c) => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}
        </select>
      </Card>
      <WeekdayCard />
      {notes && notes.length > 0 && (
        <Card icon="info" title={t("map.notes")}>
          <ul className="small" data-testid="map-notes">
            {notes.map((n, i) => <li key={i}><span className="mono">{n.field}</span>: {n.code}{n.column ? ` (${n.column}${n.type ? ` ${n.type}` : ""})` : ""}</li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}
