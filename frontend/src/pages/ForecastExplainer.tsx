import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get } from "../api";
import { useI18n } from "../i18n";
import { Card, Empty, ErrorBox, Loading, PageHeader, Stat, fmtDate, fmtDateWd, fmtTime, useAsync } from "../components/ui";
import { CHECK_TEXT, STATUS_TEXT, featureText, fmt2, fmtInt, isTiny, roundingGap } from "../explainer";

/** 1.2.14: how ONE value of the forecast in use was computed by the LightGBM model, from the source data to the whole
 *  number shown on the forecast screens. Read-only (GET /api/forecast-explainer); independent of the forecast pages. */
const PAGE = 20;
const API = "/api/forecast-explainer";
const TIMEOUT = 180_000;

type Lang = "vi" | "en";
const pick = (lang: Lang, vi: string, en: string) => (lang === "vi" ? vi : en);

function query(o: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** A number with at most 2 decimals; a non-zero value shown as ≈0,00 carries its exact value in the tooltip. */
function N({ v }: { v: number | null | undefined }) {
  if (isTiny(v)) return <span className="num" title={String(v)}>{fmt2(v)}</span>;
  return <span className="num">{fmt2(v)}</span>;
}

function terms(inputs: { date: string; value: number | null }[], lang: Lang): string {
  const known = inputs.filter((x) => x.value !== null);
  if (!known.length) return pick(lang, "không có ngày nào có dữ liệu", "no known day");
  const vals = known.map((x) => fmt2(x.value));
  return vals.length <= 6 ? vals.join(" + ") : `${vals.slice(0, 3).join(" + ")} + … + ${vals.slice(-2).join(" + ")}`;
}

function substitution(f: any, d: any, lang: Lang): string {
  const p = f.params ?? {};
  const v = f.value;
  const nan = pick(lang, "không có giá trị (NaN)", "no value (NaN)");
  const val = v === null ? nan : fmt2(v);
  switch (f.kind) {
    case "category_code": return pick(lang, `mã của ${p.key} = ${val}`, `code of ${p.key} = ${val}`);
    case "age": return `${fmtDate(p.origin)} − ${fmtDate(p.first_order_date)} = ${val} ${pick(lang, "ngày", "days")}`;
    case "lag": return f.inputs?.length ? `Y(${fmtDate(f.inputs[0].date)}) = ${val}` : `${pick(lang, "trước dữ liệu", "before the data")} → ${nan}`;
    case "mean": {
      if (!f.inputs?.length) return val;
      const n = p.n_known;
      return n ? `(${terms(f.inputs, lang)}) / ${n} = ${fmt2(p.sum)} / ${n} = ${val}` : `${pick(lang, "không có ngày có dữ liệu", "no known day")} → ${val}`;
    }
    case "std": return p.n_known > 1 ? `√(Σ(Y − ${fmt2(p.mean)})² / ${p.n_known}) = √(${fmt2(p.sum_sq_dev)} / ${p.n_known}) = ${val}`
      : `${pick(lang, "cần ít nhất 2 ngày có dữ liệu", "needs 2 known days")} → ${val}`;
    case "zero_share": return `${p.zeros} / ${p.n_known} = ${val}`;
    case "days_since": return p.last_sale_date ? `${fmtDate(d.data.origin)} − ${fmtDate(p.last_sale_date)} = ${val} ${pick(lang, "ngày", "days")}`
      : pick(lang, `không có ngày bán trong ${p.window} ngày → ${val}`, `no sale in ${p.window} days → ${val}`);
    case "max": return `max(${terms(f.inputs ?? [], lang)}) = ${val}`;
    case "last_known": return p.source_date
      ? pick(lang, `${p.column} ngày ${fmtDate(p.source_date)}${p.forward_filled ? ` (giữ nguyên đến ${fmtDate(p.day)})` : ""} = ${val}`,
        `${p.column} of ${fmtDate(p.source_date)}${p.forward_filled ? ` (carried to ${fmtDate(p.day)})` : ""} = ${val}`)
      : `${p.column} ${fmtDate(p.day)} = ${val}`;
    case "ratio_to_mean": return `${fmt2(p.numerator)} / ${fmt2(p.mean)} = ${val}`;
    case "value": return `${p.column} ${fmtDate(p.day)} = ${val}`;
    case "ratio_of_sums": return `${fmt2(p.sum_numerator)} / ${fmt2(p.sum_denominator)} = ${val} (${p.n_days} ${pick(lang, "ngày có đủ dữ liệu", "days with both values")})`;
    case "calendar": return `${f.name}(${fmtDate(p.target_date)}) = ${val}`;
    case "horizon": return `${fmtDate(p.target_date)} − ${fmtDate(p.origin)} + 1 = ${val}`;
    default: return val;
  }
}

function stepText(st: any, lang: Lang): string {
  const dir = (g: string) => (g === "left" ? pick(lang, "nhánh trái", "left branch") : pick(lang, "nhánh phải", "right branch"));
  if (st.kind === "categorical") {
    const set = `${st.n_categories} ${pick(lang, "mã", "codes")}${st.categories_sample?.length ? ` (${st.categories_sample.slice(0, 8).join(", ")}${st.n_categories > 8 ? ", …" : ""})` : ""}`;
    if (st.rule === "MISSING_RIGHT") return pick(lang, `${st.feature} không có giá trị → ${dir("right")}`, `${st.feature} has no value → ${dir("right")}`);
    return st.rule === "IN_SET"
      ? pick(lang, `${st.feature} = ${fmt2(st.value)} thuộc tập ${set} → ${dir(st.goes)}`, `${st.feature} = ${fmt2(st.value)} is in the set ${set} → ${dir(st.goes)}`)
      : pick(lang, `${st.feature} = ${fmt2(st.value)} không thuộc tập ${set} → ${dir(st.goes)}`, `${st.feature} = ${fmt2(st.value)} not in the set ${set} → ${dir(st.goes)}`);
  }
  if (st.rule === "DEFAULT") return st.value === null
    ? pick(lang, `${st.feature} không có giá trị → theo hướng mặc định của nút → ${dir(st.goes)}`, `${st.feature} has no value → the node's default direction → ${dir(st.goes)}`)
    : pick(lang, `${st.feature} = 0 → theo hướng mặc định cho giá trị 0 → ${dir(st.goes)}`, `${st.feature} = 0 → the node's default for zero → ${dir(st.goes)}`);
  const x = st.nan_as_zero ? pick(lang, "0 (không có giá trị, LightGBM dùng 0)", "0 (no value, LightGBM uses 0)") : fmt2(st.value);
  return st.rule === "LE" ? `${st.feature}: ${x} ≤ ${fmt2(st.threshold)} → ${dir(st.goes)}` : `${st.feature}: ${x} > ${fmt2(st.threshold)} → ${dir(st.goes)}`;
}

const STATE: Record<string, [string, string]> = {
  ROW: ["có dòng dữ liệu", "stored row"],
  NO_ROW_ZERO: ["không có dòng → 0 (phạm vi có dữ liệu ngày này)", "no row → 0 (the scope has data that day)"],
  UNKNOWN_DAY: ["cả phạm vi không có dữ liệu → không biết (NaN)", "no data in the whole scope → unknown (NaN)"],
  BEFORE_FIRST_ORDER: ["trước đơn đầu tiên → không biết (NaN)", "before the first order → unknown (NaN)"],
};

export default function ForecastExplainer() {
  const { t, lang } = useI18n();
  const [sp] = useSearchParams();
  const q = query({ sku_id: sp.get("sku_id"), fc_id: sp.get("fc_id"), target_date: sp.get("target_date") });
  const r = useAsync(() => get<any>(`${API}${q}`, { timeoutMs: TIMEOUT }), [q]);
  const header = <PageHeader icon="explain" title={t("nav.explainer")} desc={t("fexp.desc")} />;
  if (r.loading && !r.data) return <div className="stack">{header}<Loading /></div>;
  if (r.error) return <div className="stack">{header}<ErrorBox error={r.error} /></div>;
  const d = r.data;
  if (!d || d.status !== "OK") {
    const s = STATUS_TEXT[d?.status] ?? STATUS_TEXT.NO_FORECAST;
    return <div className="stack">{header}<Card><Empty text={s[lang]} hint={d?.reason ?? undefined} /></Card></div>;
  }
  return (
    <div className="stack" data-testid="fexp-page">
      {header}
      <Summary d={d} lang={lang} />
      <Step1 d={d} lang={lang} />
      <Step2 d={d} lang={lang} />
      <Step3 d={d} lang={lang} />
      <Step4 d={d} lang={lang} />
      <Step5 d={d} lang={lang} />
      <Checks d={d} lang={lang} />
    </div>
  );
}

function Summary({ d, lang }: { d: any; lang: Lang }) {
  const s = d.selection, run = d.run, res = d.result;
  return (
    <Card icon="explain">
      <div className="grid4" data-testid="fexp-summary">
        <Stat label="SKU" value={<span className="mono">{s.sku_id}</span>} />
        <Stat label="FC" value={<span className="mono">{s.fc_id}</span>} />
        <Stat label={pick(lang, "Ngày dự báo", "Forecast day")} value={fmtDateWd(s.target_date, lang)} sub={`horizon ${s.horizon_day}`} />
        <Stat label={pick(lang, "Forecast cuối cùng", "Final forecast")} value={<span data-testid="fexp-final">{fmtInt(res.forecast_qty)}</span>}
          tone={d.verified ? "ok" : "warn"} sub={d.verified ? pick(lang, "khớp forecast đã lưu", "matches the stored forecast") : pick(lang, "chưa khớp / chưa xác minh", "not matched / not verified")} />
      </div>
      <p className="small muted" data-testid="fexp-run">
        Model <span className="mono">{run.model_version}</span> · Forecast run <span className="mono">{run.forecast_run_id}</span> · {pick(lang, "dữ liệu đến", "data up to")} {fmtDate(run.data_as_of)} · {pick(lang, "tạo lúc", "created")} {fmtTime(run.run_created_at)} · {run.strategy} · objective {run.objective}
        {s.auto ? ` · ${pick(lang, "SKU được chọn tự động: chuỗi LightGBM có dữ liệu đầy đủ nhất", "SKU chosen automatically: the most complete LightGBM series")}` : ""}
      </p>
    </Card>
  );
}

function Step1({ d, lang }: { d: any; lang: Lang }) {
  const run = d.run, data = d.data, s = d.selection, ch = data.changes_after_run;
  return (
    <Card title={pick(lang, "Bước 1 — Dữ liệu nguồn", "Step 1 — Source data")} icon="import">
      <p className="small">
        {pick(lang,
          `Model dùng dữ liệu của SKU × FC này từ ${fmtDate(run.train_start)} đến ${fmtDate(run.data_as_of)} (cửa sổ dữ liệu của lần huấn luyện ${run.training_run_id}). Ngày gốc dự báo là ${fmtDate(data.origin)}; ngày dự báo ${fmtDate(s.target_date)} là ngày thứ ${s.horizon_day} kể từ ngày gốc. Chỉ dữ liệu trước ngày gốc được dùng.`,
          `The model uses this SKU × FC's data from ${fmtDate(run.train_start)} to ${fmtDate(run.data_as_of)} (data window of training run ${run.training_run_id}). The forecast origin is ${fmtDate(data.origin)}; ${fmtDate(s.target_date)} is day ${s.horizon_day} from the origin. Only data before the origin is used.`)}
      </p>
      <ul className="small">
        <li>{pick(lang, "Nguồn", "Source")}: {run.data_source} · {pick(lang, "số dòng của chuỗi trong cửa sổ", "rows of the series in the window")}: {fmtInt(data.rows_in_window)} · {pick(lang, "ngày có đơn đầu tiên", "first order day")}: {fmtDate(data.first_order_date)}</li>
        <li>{pick(lang, "Ngày cả phạm vi không có dữ liệu trong cửa sổ", "Days without any data in the scope")}: {data.unknown_days_in_window} · {pick(lang, "lần tải gần nhất", "last load")}: {fmtTime(data.last_loaded_at)}{data.override_applied ? ` · ${pick(lang, "có áp dụng quy tắc giờ mở bán của chủ hệ thống", "owner's open-hours rule applied")}` : ""}</li>
      </ul>
      <ChangesBox ch={ch} lang={lang} />
      <details open>
        <summary className="small">{pick(lang, `Dữ liệu ${data.history.length} ngày gần nhất trước ngày gốc (đầu vào của forecast đã lưu)`, `Last ${data.history.length} days before the origin (inputs of the stored forecast)`)}</summary>
        <div className="scroll">
          <table className="tbl small" data-testid="fexp-history">
            <thead><tr>
              <th>{pick(lang, "Ngày", "Day")}</th><th>{pick(lang, "Trạng thái", "State")}</th>
              <th className="num">{pick(lang, "Y dùng cho model ●", "Y used by the model ●")}</th>
              <th className="num">{pick(lang, "Giá dùng ●", "Price used ●")}</th><th className="num">{pick(lang, "Giờ mở bán ●", "Open hours ●")}</th>
              <th className="num">{pick(lang, "Số khách ●", "Customers ●")}</th>
              <th className="num">{pick(lang, "SL dòng gốc", "Stored qty")}</th><th className="num">{pick(lang, "Giá TB dòng", "Row price")}</th><th className="num">{pick(lang, "Số đơn", "Orders")}</th>
            </tr></thead>
            <tbody>
              {data.history.map((h: any) => (
                <tr key={h.date} data-state={h.state}>
                  <td>{fmtDateWd(h.date, lang)}</td><td>{STATE[h.state]?.[lang === "vi" ? 0 : 1] ?? h.state}</td>
                  <td className="num">{h.y === null ? "NaN" : fmt2(h.y)}</td><td className="num"><N v={h.price_used} /></td>
                  <td className="num"><N v={h.open_hours} /></td><td className="num"><N v={h.customers} /></td>
                  <td className="num"><N v={h.qty_row} /></td><td className="num"><N v={h.price_row} /></td><td className="num"><N v={h.n_orders} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">{pick(lang, "● = đầu vào của model. Các cột còn lại chỉ để giải thích (dòng dữ liệu gốc lưu trong ứng dụng).", "● = model input. The other columns only explain (the stored source rows).")}</p>
      </details>
    </Card>
  );
}

function ChangesBox({ ch, lang }: { ch: any; lang: Lang }) {
  if (!ch) return null;
  const head: Record<string, [string, string]> = {
    UNCHANGED: ["Dữ liệu của chuỗi không thay đổi từ khi tạo forecast.", "The series' data has not changed since the forecast was made."],
    SAME_INPUTS: ["Có dòng được tải lại hoặc thay đổi sau khi tạo forecast, nhưng không đổi đầu vào nào của model.", "Rows were reloaded or changed after the forecast, but no model input changed."],
    REVERTED_TO_RUN: ["Có đầu vào thay đổi sau khi tạo forecast: giải thích dùng giá trị lúc tạo forecast (theo nhật ký thay đổi).", "An input changed after the forecast: the explanation uses the values at the forecast (from the change log)."],
    UNKNOWN: ["Có dòng được tải lại sau khi tạo forecast và không có nhật ký thay đổi để đối chiếu.", "Rows were reloaded after the forecast and there is no change log to compare."],
  };
  const h = head[ch.status] ?? [ch.status, ch.status];
  return (
    <div className={`small ${ch.status === "UNKNOWN" ? "bad-t" : ""}`} data-testid="fexp-changes">
      <p>{h[lang === "vi" ? 0 : 1]} ({pick(lang, "dòng tải lại sau khi tạo forecast", "rows reloaded after the forecast")}: {ch.rows_loaded_after_run})</p>
      {ch.records?.length ? (
        <table className="tbl small">
          <thead><tr><th>{pick(lang, "Ngày", "Day")}</th><th>{pick(lang, "Thay đổi", "Change")}</th><th>{pick(lang, "Cột: trước → sau", "Column: before → after")}</th><th>{pick(lang, "Đầu vào model?", "Model input?")}</th><th>{pick(lang, "Lần đồng bộ", "Sync run")}</th></tr></thead>
          <tbody>
            {ch.records.map((x: any, i: number) => (
              <tr key={i}><td>{fmtDate(x.date)}</td><td>{x.action}</td>
                <td className="mono">{Object.entries(x.changed).map(([k, v]: [string, any]) => `${k}: ${v.before ?? "—"} → ${v.after ?? "—"}`).join("; ")}</td>
                <td>{x.model_input ? pick(lang, "có", "yes") : pick(lang, "không", "no")}</td><td className="mono">{x.sync_run}</td></tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function Step2({ d, lang }: { d: any; lang: Lang }) {
  return (
    <Card title={pick(lang, `Bước 2 — Tạo ${d.features.length} feature`, `Step 2 — Building the ${d.features.length} features`)} icon="features">
      <p className="small muted">{pick(lang, "Đúng thứ tự cột đưa vào model. Số hiển thị đã làm tròn tối đa 2 chữ số; model dùng giá trị gốc (float32).", "In the model's column order. Displayed numbers are rounded to at most 2 decimals; the model uses the exact values (float32).")}</p>
      <div className="scroll">
        <table className="tbl small" data-testid="fexp-features">
          <thead><tr><th>#</th><th>Feature</th><th>{pick(lang, "Công thức tổng quát", "General formula")}</th><th>{pick(lang, "Thay số", "With the values")}</th><th className="num">{pick(lang, "Giá trị vào model", "Model input")}</th><th>✓</th></tr></thead>
          <tbody>
            {d.features.map((f: any) => {
              const tx = featureText(f.name);
              return (
                <tr key={f.name} data-feature={f.name}>
                  <td>{f.index + 1}</td>
                  <td><span className="mono">{f.name}</span><div className="muted">{tx ? tx.meaning[lang] : ""}</div></td>
                  <td>{tx ? tx.formula[lang] : "—"}</td>
                  <td className="mono">{substitution(f, d, lang)}
                    {f.inputs?.length > 6 && (
                      <details><summary className="muted">{pick(lang, `${f.inputs.length} ngày`, `${f.inputs.length} days`)}</summary>
                        {f.inputs.map((x: any) => <div key={x.date}>{fmtDate(x.date)}: {x.value === undefined ? `${fmt2(x.customers)} / ${fmt2(x.repeat)} / ${fmt2(x.interval_sum)}` : (x.value === null ? "NaN" : fmt2(x.value))}</div>)}
                      </details>)}
                  </td>
                  <td className="num">{f.value === null ? "NaN" : <N v={f.value} />}</td>
                  <td>{f.verified ? "✓" : <span className="bad-t">{pick(lang, "chưa xác minh", "not verified")}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Step3({ d, lang }: { d: any; lang: Lang }) {
  const tr = d.trees;
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const pages = Math.ceil(tr.count / PAGE);
  const sel = d.selection;
  const q = query({ offset: page * PAGE, limit: PAGE, sku_id: sel.sku_id, fc_id: sel.fc_id, target_date: sel.target_date });
  const pg = useAsync(() => get<any>(`${API}/trees${q}`, { timeoutMs: TIMEOUT }), [q]);
  const rows = useMemo(() => tr.summary.slice(page * PAGE, page * PAGE + PAGE), [tr.summary, page]);
  const paths: Record<number, any> = {};
  for (const x of pg.data?.trees ?? []) paths[x.index] = x;
  return (
    <Card title={pick(lang, `Bước 3 — Đi qua ${tr.count} cây quyết định`, `Step 3 — Through the ${tr.count} decision trees`)} icon="model">
      <p className="small">{pick(lang,
        "Mỗi cây bắt đầu ở nút gốc. Tại mỗi nút: nếu giá trị feature ≤ ngưỡng thì đi nhánh trái, ngược lại đi nhánh phải. Feature không có giá trị đi theo hướng mặc định của nút; với sku_code / fc_code (biến phân loại) đi nhánh trái khi mã thuộc tập mã của nút. Cây dừng ở một lá; giá trị của lá là phần đóng góp của cây đó.",
        "Each tree starts at its root. At each node: if the feature value ≤ the threshold go left, otherwise go right. A feature without a value takes the node's default direction; for sku_code / fc_code (categorical) go left when the code is in the node's set. The tree ends in a leaf; the leaf value is that tree's contribution.")}</p>
      <ul className="small">
        <li>{pick(lang, "Cây 0", "Tree 0")} (shrinkage {fmt2(tr.tree0_shrinkage)}): {pick(lang, "lá", "leaf")} = <N v={tr.tree0_value} /> — {pick(lang, "đã gồm giá trị khởi tạo LightGBM cộng sẵn vào lá (boost_from_average)", "includes the initial score LightGBM adds to its leaves (boost_from_average)")}</li>
        <li>{pick(lang, `${tr.count - 1} cây còn lại`, `the other ${tr.count - 1} trees`)}: <N v={tr.rest_sum} /> · {pick(lang, "tổng lá dương", "positive leaves")} <N v={tr.positive_sum} /> · {pick(lang, "tổng lá âm", "negative leaves")} <N v={tr.negative_sum} /></li>
        <li>{pick(lang, "10 cây đóng góp lớn nhất", "10 largest contributions")}: {tr.top.map((x: any) => `#${x.index}: ${fmt2(x.leaf_value)}`).join(" · ")}</li>
      </ul>
      <div className="row wrap small">
        <button disabled={page === 0} onClick={() => { setPage(page - 1); setOpen(null); }} aria-label="previous-trees">{pick(lang, "‹ Trước", "‹ Previous")}</button>
        <span>{pick(lang, `Cây ${page * PAGE} – ${Math.min(tr.count, page * PAGE + PAGE) - 1} / ${tr.count}`, `Trees ${page * PAGE} – ${Math.min(tr.count, page * PAGE + PAGE) - 1} of ${tr.count}`)}</span>
        <button disabled={page >= pages - 1} onClick={() => { setPage(page + 1); setOpen(null); }} aria-label="next-trees">{pick(lang, "Sau ›", "Next ›")}</button>
      </div>
      <div className="scroll">
        <table className="tbl small" data-testid="fexp-trees">
          <thead><tr><th>{pick(lang, "Cây", "Tree")}</th><th>{pick(lang, "Số bước", "Steps")}</th><th>{pick(lang, "Lá", "Leaf")}</th><th className="num">{pick(lang, "Giá trị lá", "Leaf value")}</th><th></th></tr></thead>
          <tbody>
            {rows.map((x: any) => (
              <TreeRow key={x.index} x={x} path={paths[x.index]} open={open === x.index} loading={pg.loading}
                onToggle={() => setOpen(open === x.index ? null : x.index)} lang={lang} />
            ))}
          </tbody>
        </table>
      </div>
      {pg.error ? <ErrorBox error={pg.error} /> : null}
    </Card>
  );
}

function TreeRow({ x, path, open, loading, onToggle, lang }: { x: any; path: any; open: boolean; loading: boolean; onToggle: () => void; lang: Lang }) {
  return (
    <>
      <tr data-tree={x.index}>
        <td>#{x.index}</td><td>{x.depth}</td><td>{x.leaf}</td><td className="num"><N v={x.leaf_value} /></td>
        <td><button onClick={onToggle} aria-expanded={open} aria-label={`tree-${x.index}`}>{open ? pick(lang, "Ẩn đường đi", "Hide path") : pick(lang, "Xem đường đi", "Show path")}</button></td>
      </tr>
      {open && (
        <tr><td colSpan={5}>
          {path ? (
            <ol className="small" data-testid={`fexp-path-${x.index}`}>
              {path.steps.map((st: any) => (
                <li key={st.node} title={st.kind === "numerical" ? `value ${st.value} · threshold ${st.threshold}` : undefined}>
                  {pick(lang, "Nút", "Node")} {st.node}: {stepText(st, lang)}
                </li>
              ))}
              <li>{pick(lang, "Lá", "Leaf")} {path.leaf}: {pick(lang, "giá trị", "value")} <N v={path.leaf_value} /></li>
            </ol>
          ) : loading ? <span className="muted small">…</span> : <span className="muted small">—</span>}
        </td></tr>
      )}
    </>
  );
}

function Step4({ d, lang }: { d: any; lang: Lang }) {
  const a = d.aggregation, tr = d.trees;
  const log = a.link === "log";
  return (
    <Card title={pick(lang, "Bước 4 — Tổng hợp kết quả từ model", "Step 4 — Combining the model's output")} icon="chart">
      <p className="small"><b>{pick(lang, "Công thức", "Formula")}:</b> {pick(lang, `điểm thô = tổng giá trị lá của ${tr.count} cây`, `raw score = sum of the leaf values of the ${tr.count} trees`)}{log ? pick(lang, `; dự đoán = e^(điểm thô) (objective ${a.objective}, hàm liên kết log)`, `; prediction = e^(raw score) (objective ${a.objective}, log link)`) : pick(lang, "; dự đoán = điểm thô", "; prediction = raw score")}</p>
      <p className="small mono" data-testid="fexp-sum">{pick(lang, "điểm thô", "raw score")} = {fmt2(tr.tree0_value)} + {fmt2(tr.rest_sum)} = {fmt2(a.raw_sum)}</p>
      {log && <p className="small mono" data-testid="fexp-link">{pick(lang, "dự đoán", "prediction")} = e^{fmt2(a.raw_sum)} = {fmt2(a.prediction)}</p>}
      {roundingGap([tr.tree0_value, tr.rest_sum], a.raw_sum) && (
        <p className="small muted">{pick(lang, "Các số đã làm tròn khi hiển thị nên có thể không cộng đúng tới chữ số cuối; phép tính dùng giá trị gốc.", "Displayed numbers are rounded, so they may not add up in the last digit; the computation uses the exact values.")}</p>
      )}
      <p className="small muted">{pick(lang,
        `Đối chiếu LightGBM: điểm thô ${fmt2(a.raw_lightgbm)}, dự đoán ${fmt2(a.prediction_lightgbm)}.${a.tweedie_variance_power ? ` tweedie_variance_power ${fmt2(a.tweedie_variance_power)} chỉ dùng khi huấn luyện, không tham gia phép dự đoán.` : ""}`,
        `LightGBM check: raw score ${fmt2(a.raw_lightgbm)}, prediction ${fmt2(a.prediction_lightgbm)}.${a.tweedie_variance_power ? ` tweedie_variance_power ${fmt2(a.tweedie_variance_power)} is a training parameter, not part of the prediction.` : ""}`)}</p>
    </Card>
  );
}

function Step5({ d, lang }: { d: any; lang: Lang }) {
  const a = d.aggregation, res = d.result;
  return (
    <Card title={pick(lang, "Bước 5 — Kết quả forecast cuối cùng", "Step 5 — The final forecast")} icon="results">
      <ol className="small" data-testid="fexp-result">
        <li>{pick(lang, "Dự đoán thô của model (LightGBM)", "Raw model prediction (LightGBM)")}: <N v={a.prediction_lightgbm} /></li>
        <li>{pick(lang, "Biến đổi đầu ra", "Output transform")}: {a.link === "log" ? pick(lang, "e^(điểm thô) — đã tính ở bước 4", "e^(raw score) — computed in step 4") : pick(lang, "không có", "none")}</li>
        <li>{pick(lang, "Xử lý sau dự đoán", "Post-processing")}: max(0; <N v={a.prediction_lightgbm} />) = <N v={res.clipped} />; {pick(lang, "lưu với 4 chữ số thập phân", "stored with 4 decimals")} = <N v={res.published} /></li>
        <li>{pick(lang, "Quy tắc số nguyên (làm tròn nửa lên, không âm)", "Whole-number rule (round half up, never negative)")}: ⌊<N v={res.stored_yhat} /> + 0,5⌋ = {fmtInt(res.forecast_qty)}</li>
        <li><b>{pick(lang, "Forecast cuối cùng", "Final forecast")}: <span data-testid="fexp-final-2">{fmtInt(res.forecast_qty)}</span></b></li>
      </ol>
      {res.match ? (
        <p className="small ok-t" data-testid="fexp-match">{pick(lang, `Khớp forecast đã lưu (${fmt2(res.stored_yhat)} → ${fmtInt(res.forecast_qty)}).`, `Matches the stored forecast (${fmt2(res.stored_yhat)} → ${fmtInt(res.forecast_qty)}).`)}</p>
      ) : (
        <div className="small bad-t" role="alert" data-testid="fexp-mismatch">
          {pick(lang, `Không khớp forecast đã lưu: tính lại ${fmt2(res.published)} (số nguyên ${fmtInt(res.forecast_qty_recomputed)}), đã lưu ${fmt2(res.stored_yhat)} (số nguyên ${fmtInt(res.forecast_qty)}). Giá trị đã lưu không bị sửa.`,
            `Does not match the stored forecast: recomputed ${fmt2(res.published)} (whole ${fmtInt(res.forecast_qty_recomputed)}), stored ${fmt2(res.stored_yhat)} (whole ${fmtInt(res.forecast_qty)}). The stored value is not changed.`)}
          {" "}{pick(lang, "Nguyên nhân đã xác định: xem Bước 1 (dữ liệu thay đổi sau khi tạo forecast) và các kiểm tra bên dưới.", "Identified causes: see step 1 (data changed after the forecast) and the checks below.")}
        </div>
      )}
    </Card>
  );
}

function Checks({ d, lang }: { d: any; lang: Lang }) {
  return (
    <Card title={pick(lang, "Kiểm chứng", "Verification")} icon="ok">
      <ul className="small" data-testid="fexp-checks">
        {d.checks.map((c: any) => (
          <li key={c.check} data-ok={c.ok}>{c.ok ? "✓" : "✗"} {CHECK_TEXT[c.check]?.[lang] ?? c.check}
            {typeof c.detail === "string" ? <span className="muted"> — {c.detail}</span> : null}</li>
        ))}
      </ul>
      <p className="small muted">{pick(lang, "Màn hình chỉ đọc: không chạy lại forecast, không huấn luyện, không thay đổi dữ liệu.", "Read-only screen: no forecast is re-run, nothing is trained or changed.")} {fmtTime(d.computed_at)}</p>
    </Card>
  );
}
