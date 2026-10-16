import { useEffect, useState } from "react";
import { get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, ErrorBox, Loading, OkBox, useAction, useAsync } from "../components/ui";

const FIELDS = ["order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price", "discount_amount",
  "promotion_flag", "promotion_id", "voucher_flag", "voucher_amount", "source_updated_at", "batch_id"];
const REF_FIELDS = ["product_id", "item_code", "outbound_qty", "order_status", "sales_price", "price_after_discount",
  "seller_code", "sku_status", "open_date", "open_hours", "open_days"];
type FM = Record<string, { column: string | null; usage: string }>;

function MappingTable({ fields, m, setM, cols, types, check, reference }: {
  fields: string[]; m: FM; setM: (x: FM) => void; cols: { name: string; type: string }[]; types: Record<string, string>;
  check: any; reference?: boolean;
}) {
  const { t } = useI18n();
  const usages = reference ? ["OPTIONAL", "UNUSED"] : ["REQUIRED", "OPTIONAL", "UNUSED"];
  return (
    <table className="tbl" data-testid={reference ? "map-ref" : "map-key"}>
      <thead><tr><th>{t("imp.field")}</th><th>{t("map.usage")}</th><th>{t("imp.column")}</th><th>{t("map.type")}</th></tr></thead>
      <tbody>
        {fields.map((f) => {
          const cur = m[f] ?? { column: null, usage: "OPTIONAL" };
          const err = check?.errors?.find((e: any) => e.field === f && !!e.reference === !!reference);
          return (
            <tr key={f} className={err ? "row-bad" : ""}>
              <td><span className="mono">{f}</span><div className="small muted">{t(`mapf.${f}`)}</div></td>
              <td>
                <select aria-label={`usage-${f}`} value={cur.usage} onChange={(e) => setM({ ...m, [f]: { ...cur, usage: e.target.value } })}>
                  {usages.map((u) => <option key={u} value={u}>{t(`map.usage.${u}`)}</option>)}
                </select>
              </td>
              <td>
                <select aria-label={`column-${f}`} value={cur.column ?? ""} onChange={(e) => setM({ ...m, [f]: { ...cur, column: e.target.value || null } })} disabled={cur.usage === "UNUSED"}>
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

export default function Mapping() {
  const { t } = useI18n();
  const st = useAsync(() => get("/api/bigquery/status"), []);
  const [cols, setCols] = useState<{ name: string; type: string }[]>([]);
  const [drift, setDrift] = useState<any>(null);
  const [m, setM] = useState<FM>({});
  const [ref, setRef] = useState<FM>({});
  const [check, setCheck] = useState<any>(null);
  const [notes, setNotes] = useState<any[] | null>(null);
  const act = useAction();
  useEffect(() => {
    if (st.data) {
      setM(st.data.settings.field_mapping);
      setRef(st.data.settings.reference_mapping ?? {});
      setCols(st.data.settings.schema_snapshot ?? []);
    }
  }, [st.data]);
  if (st.loading) return <Loading />;
  const configured = st.data?.settings?.dataset_id && st.data?.settings?.source_table;
  const readSchema = async () => {
    const r = await act.run(() => post("/api/bigquery/schema"));
    if (r) { setCols(r.columns); setDrift(r.drift); setCheck(r.mapping_check); }
  };
  const suggest = async () => {
    const r = await act.run(() => post("/api/bigquery/suggest-mapping"));
    if (r) { setCols(r.columns); setM(r.field_mapping); setRef(r.reference_mapping); setCheck(r.check); setNotes(r.notes); }
  };
  const save = async () => {
    const r = await act.run(() => post("/api/bigquery/mapping", { field_mapping: m, reference_mapping: ref }), t("common.saved"));
    if (r) { setCheck(r.check); st.reload(); }
  };
  const types = Object.fromEntries(cols.map((c) => [c.name, c.type]));
  const hasDrift = drift && (drift.removed.length || drift.added.length || drift.type_changed.length);
  return (
    <div className="stack">
      <h2>{t("nav.mapping")}</h2>
      <p className="small">{t("map.help")}</p>
      {!configured && <div className="alert warn">{t("bq.not_configured")} {t("bq.blocked_note")}</div>}
      <ErrorBox error={act.error || st.error} />
      <OkBox text={act.ok} />
      {hasDrift ? <div className="alert bad">{t("map.drift")}: {JSON.stringify(drift)}</div> : null}
      <Card title={t("map.key_fields")} actions={<>
        <button onClick={readSchema} disabled={act.busy || !configured}>{t("bq.schema")}</button>
        <button onClick={suggest} disabled={act.busy || !configured} data-testid="map-suggest">{t("map.suggest")}</button>
        <button className="primary" onClick={save} disabled={act.busy || !configured}>{t("map.save")}</button>
      </>}>
        <p className="small muted">{t("map.suggest_note")}</p>
        {!cols.length && <p className="small muted">{t("map.read_schema_first")}</p>}
        <MappingTable fields={FIELDS} m={m} setM={setM} cols={cols} types={types} check={check} />
      </Card>
      <Card title={t("map.ref_fields")}>
        <MappingTable fields={REF_FIELDS} m={ref} setM={setRef} cols={cols} types={types} check={check} reference />
      </Card>
      {check && !check.ok && <div className="alert bad">{t("map.errors")}: {check.errors.map((e: any) => `${e.field}: ${e.code}`).join("; ")}</div>}
      {check?.warnings?.length > 0 && <p className="small muted">{check.warnings.map((w: any) => `${w.field}: ${w.code}`).join("; ")}</p>}
      {notes && notes.length > 0 && (
        <Card title={t("map.notes")}>
          <ul className="small" data-testid="map-notes">
            {notes.map((n, i) => <li key={i}><span className="mono">{n.field}</span>: {n.code}{n.column ? ` (${n.column}${n.type ? ` ${n.type}` : ""})` : ""}</li>)}
          </ul>
        </Card>
      )}
    </div>
  );
}
