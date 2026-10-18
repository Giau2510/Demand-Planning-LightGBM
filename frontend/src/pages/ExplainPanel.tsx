import { useEffect, useMemo, useState, type ReactNode } from "react";
import { get, qs } from "../api";
import { useI18n } from "../i18n";
import ShapTrace from "./ShapTrace";
import { Icon } from "../components/icons";
import { DateInput, ErrorBox, Loading, MethodLabel, fmtDate, fmtNum, fmtPctX, fmtTime, fmtX, useAsync, useMethods, weekdayName } from "../components/ui";

function addDays(iso: string, n: number) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

const TOP_N = 8;

/** 1.2.4: how the backend checked that the data this run used is still the data in the database. A reload with the
 *  same values (SAME_CONTENT) is said explicitly; a change names the days; without a recorded identity nothing is guessed. */
export function DataCheck({ d }: { d: any }) {
  const { t } = useI18n();
  if (!d || d.status === "SAME_LOAD") return null;
  if (d.status === "SAME_CONTENT") {
    return (
      <div className="alert info small" data-testid="ex-data-check">
        {t("ex.dc.same_content").replace("{from}", fmtDate(d.window?.[0])).replace("{to}", fmtDate(d.window?.[1]))
          .replace("{rows}", fmtNum(d.rows)).replace("{sha}", String(d.sha256 ?? "").slice(0, 12))}
        {d.origin === "ATTESTED" && <> {t("ex.dc.attested")}</>}
      </div>
    );
  }
  if (d.status === "CHANGED") {
    const days = (d.changed_days ?? []).slice(0, 10).map((x: string) => fmtDate(x)).join(", ");
    return <div className="alert warn small" data-testid="ex-data-check">{t("ex.dc.changed").replace("{n}", fmtNum(d.n_changed_days)).replace("{days}", days)}</div>;
  }
  return <div className="alert warn small" data-testid="ex-data-check">{t("ex.dc.unverifiable")}</div>;
}

/** Collapsible block (closed blocks keep the screen readable; their content stays in the page for search/print). */
function Block({ title, open = false, children, testid }: { title: ReactNode; open?: boolean; children: ReactNode; testid?: string }) {
  return (
    <details className="exblock" open={open} data-testid={testid}>
      <summary><h4>{title}</h4></summary>
      <div className="exbody">{children}</div>
    </details>
  );
}

/** "How was this calculated?" for one SKU x FC x date of a published run. Three levels: summary for the operator,
 *  the calculation step by step, and the technical, verifiable details. Every number comes from the explanation API
 *  (backend/app/ml/explain.py), which only returns values it reproduced from the saved model and data. Numbers are
 *  shown with at most 2 decimals; the technical block shows the full precision used internally. */
export default function ExplainPanel({ runId, sku, fc, date, maxHorizon, origin, onClose }: {
  runId: string; sku: string; fc: string; date: string; maxHorizon: number; origin: string; onClose: () => void;
}) {
  const { t, lang } = useI18n();
  const vi = lang === "vi";
  const L = (a: string, b: string) => (vi ? a : b);
  const reg = useMethods();
  const [d, setD] = useState(date);
  const [allFeatures, setAllFeatures] = useState(false);
  const [sortBy, setSortBy] = useState<"impact" | "name">("impact");
  const [traceFeature, setTraceFeature] = useState<string | null>(null);
  useEffect(() => setD(date), [date, sku, fc]);
  const ex = useAsync(() => get(`/api/forecast-runs/${runId}/explain${qs({ sku_id: sku, fc_id: fc, target_date: d })}`), [runId, sku, fc, d]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !traceFeature) onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, traceFeature]);
  const last = addDays(origin, maxHorizon - 1);
  const e = ex.data;
  const sel = e?.selection;
  const reason = sel?.reason_code ? reg?.reasons?.[sel.reason_code]?.[lang] : null;
  const lg = e?.lightgbm?.status === "OK" ? e.lightgbm : null;
  const feats: any[] = lg?.features ?? [];
  const sorted = useMemo(() => [...feats].sort((a, b) => (sortBy === "impact" ? Math.abs(b.contribution) - Math.abs(a.contribution) : a.name.localeCompare(b.name))), [feats, sortBy]);
  const top = useMemo(() => [...feats].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, TOP_N), [feats]);
  const ups = top.filter((f) => f.contribution > 0);
  const downs = top.filter((f) => f.contribution < 0);
  const q = e?.quality;
  const bm = q?.backtest_this_method;
  const gate = q?.quality_gate;
  const histUrl = `/api/forecast-runs/${runId}/explain/history.xlsx${qs({ sku_id: sku, fc_id: fc, target_date: d, lang })}`;
  const srcLabel = (s: string) => t(`ex.src.${s}`);
  const effect = (f: any) => (f.effect === "UP" ? L("làm tăng", "raises") : f.effect === "DOWN" ? L("làm giảm", "lowers") : L("không đáng kể", "negligible"));
  const windowText = (f: any) => (!f.window ? "—" : f.window.from === f.window.to ? fmtDate(f.window.from) : `${fmtDate(f.window.from)} → ${fmtDate(f.window.to)}`);
  const featName = (f: any) => f.catalog?.[lang]?.name ?? f.name;

  const FeatureRows = ({ rows, detail }: { rows: any[]; detail: boolean }) => (
    <table className="tbl small" data-testid={detail ? "features-all" : "features-top"}>
      <thead><tr><th>{L("Yếu tố (feature)", "Feature")}</th><th className="num">{L("Giá trị đầu vào", "Input value")}</th>
        <th>{L("Nguồn dữ liệu", "Data source")}</th><th className="num">{L("Đóng góp", "Contribution")}</th><th>{L("Ảnh hưởng", "Effect")}</th>
        {detail && <><th>{L("Cách tính", "How it is computed")}</th><th>{L("Khoảng ngày dùng", "Days used")}</th><th>{L("Dữ liệu thiếu", "Missing data")}</th></>}<th></th></tr></thead>
      <tbody>
        {rows.map((f) => (
          <tr key={f.name} data-feature={f.name}>
            <td><b>{featName(f)}</b><div className="mono muted">{f.name}</div></td>
            <td className="num">{f.missing ? <span className="muted">{L("thiếu (NaN)", "missing (NaN)")}</span> : fmtX(f.value)}</td>
            <td className="small">{srcLabel(f.source)}</td>
            <td className={`num ${f.contribution > 0 ? "ok-t" : f.contribution < 0 ? "bad-t" : ""}`}>{fmtX(f.contribution, true)}</td>
            <td className="small">{effect(f)}{!f.used_in_trees && <div className="muted">{L("không cây nào dùng", "unused by the trees")}</div>}</td>
            {detail && <><td className="small">{f.catalog?.[lang]?.formula}<div className="muted">{f.catalog?.[lang]?.meaning}</div></td>
              <td className="small">{windowText(f)}{f.includes_target_day && <div className="muted">{L("(chính ngày dự báo)", "(the target day itself)")}</div>}</td>
              <td className="small">{f.catalog?.[lang]?.missing}</td></>}
            <td><button className="link" data-testid={`why-${f.name}`} onClick={() => setTraceFeature(f.name)}>{L("Vì sao?", "Why?")}</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-label={t("ex.title")} onClick={onClose}>
      <div className="modal wide" onClick={(ev) => ev.stopPropagation()}>
        <div className="row between">
          <h3>{t("ex.title")}: {sku} · {fc}</h3>
          <button className="icon-btn ghost" onClick={onClose} aria-label={t("common.close")} title={t("common.close")}><Icon name="close" /></button>
        </div>
        <div className="row wrap">
          <button disabled={d <= origin} onClick={() => setD(addDays(d, -1))}>← {t("ex.prev_day")}</button>
          <DateInput value={d} min={origin} max={last} onChange={(v) => v && setD(v)} ariaLabel={t("fc.date")} />
          <button disabled={d >= last} onClick={() => setD(addDays(d, 1))}>{t("ex.next_day")} →</button>
        </div>
        {ex.loading && <Loading />}
        <ErrorBox error={ex.error} />
        {e && !ex.loading && (
          <div className="stack ex">
            {/* ---------------------------------------------------------------- level 1: summary */}
            <section className="exsummary" data-testid="ex-summary">
              <p className="big"><b>{fmtX(e.result.yhat)}</b> {t("ex.unit")} · {fmtDate(e.identity.target_date)} ({weekdayName(e.identity.target_date, lang)}) · <MethodLabel code={e.result.method} /></p>
              {lg && (
                <p className="small">{L("Ảnh hưởng mạnh nhất", "Strongest drivers")}: {top.slice(0, 3).map((f, i) => (
                  <span key={f.name}>{i > 0 && " · "}{featName(f)} <b className={f.contribution > 0 ? "ok-t" : "bad-t"}>{fmtX(f.contribution, true)}</b></span>
                ))}</p>
              )}
              {e.fallback && e.fallback.rate !== undefined && (
                <p className="small">{e.fallback.kind === "FALLBACK_INACTIVE_ZERO" ? L("Không có đơn trong thời gian dài → dự báo 0.", "No orders for a long time → forecast 0.")
                  : L(`Trung bình mỗi ngày: ${fmtX(e.fallback.sum)} ÷ ${fmtNum(e.fallback.known_days)} ngày = ${fmtX(e.fallback.rate)}.`, `Daily average: ${fmtX(e.fallback.sum)} ÷ ${fmtNum(e.fallback.known_days)} days = ${fmtX(e.fallback.rate)}.`)}</p>
              )}
              {gate?.checks && (
                <p className="small">{t("perf.gate")}: <b>{gate.passed ? L("Đạt (theo cấu hình hiện tại)", "Passed (current configuration)") : L("Không đạt", "Failed")}</b>
                  {bm && <> · {L("backtest của phương pháp này", "backtest of this method")}: WAPE {fmtPctX(bm.wape)}, Bias {fmtPctX(bm.bias, true)}, {fmtNum(bm.n_points)} {L("điểm đánh giá", "evaluation points")}</>}
                  {!gate.thresholds_approved_by_business && <span className="warn-t"> · {L("ngưỡng chưa được nghiệp vụ phê duyệt", "thresholds not business-approved")}</span>}</p>
              )}
              {lg?.uses_forecast_inputs && <div className="alert info small">{t("ex.lgb_recursive").replace("{h}", String(lg.recursive_step))}</div>}
              {lg?.forecast_strategy === "DIRECT" && <div className="alert info small" data-testid="ex-direct">{t("ex.direct")}</div>}
              <DataCheck d={e.reproduction?.data_check} />
            </section>

            <Block title={`1. ${t("ex.identity")}`} open>
              <table className="tbl small"><tbody>
                <tr><td>{t("fc.date")}</td><td><b>{fmtDate(e.identity.target_date)}</b> ({weekdayName(e.identity.target_date, lang)} · {t("fc.day_n")} {e.identity.horizon_day})</td></tr>
                <tr><td>{t("fc.data_as_of")}</td><td>{fmtDate(e.identity.data_as_of)}</td></tr>
                <tr><td>{t("fc.run_id")}</td><td className="mono">{e.identity.run_id}{e.identity.derived_from_run_id ? ` (${t("fc.extended")} ← ${e.identity.derived_from_run_id})` : ""}</td></tr>
                <tr><td>{t("fc.model_version")}</td><td className="mono">{e.identity.model_version}</td></tr>
                <tr><td>{t("common.source")}</td><td>{e.identity.data_source} · <span className="mono">{e.identity.scope_key}</span></td></tr>
              </tbody></table>
            </Block>

            <Block title={`2. ${t("ex.method")}`} open>
              <p><MethodLabel code={e.result.method} showCode /></p>
              {sel?.source === "MISSING" ? <div className="alert warn small">{t("ex.selection_missing")}</div> : (
                <>
                  <p className="small">{t("ex.reason")}: <b>{reason ?? sel?.reason_code}</b>{sel?.source === "RECOMPUTED" && <span className="muted"> ({t("ex.recomputed")})</span>}</p>
                  <table className="tbl small"><tbody>
                    <tr><td>{t("ex.series_start")}</td><td>{fmtDate(sel.series_start_date)} · {t("ex.age")}: {fmtNum(sel.age_days)} {t("common.days")} ({t("ex.rule_min")} {fmtNum(sel.rule.min_series_history_days)})</td></tr>
                    <tr><td>{t("ex.zero_share")}</td><td>{fmtPctX(sel.zero_share)} = {fmtNum(sel.zero_days)}/{fmtNum(sel.zero_known_days)} {t("ex.known_days")} ({t("ex.window")} {fmtNum(sel.rule.zero_share_window_days)} {t("common.days")}; {t("ex.threshold")} {fmtPctX(sel.rule.intermittent_zero_share)})</td></tr>
                    <tr><td>{t("ex.recent_sum")}</td><td>{fmtX(sel.recent_sum)} ({t("ex.window")} {fmtNum(sel.rule.inactive_days)} {t("common.days")})</td></tr>
                  </tbody></table>
                </>
              )}
            </Block>

            {/* ---------------------------------------------------------------- level 2: calculation */}
            <Block title={`4–5. ${L("Forecast được tạo ra như thế nào?", "How was the forecast produced?")}`} open testid="ex-calc">
              {e.fallback && (
                e.fallback.rate === undefined ? <div className="alert warn small">{t("ex.selection_missing")}</div> : (
                  <div className="calc">
                    {e.fallback.kind === "FALLBACK_INACTIVE_ZERO" ? (
                      <p>{t("ex.calc_inactive").replace("{n}", String(sel?.rule?.inactive_days)).replace("{s}", fmtX(e.fallback.sum))}</p>
                    ) : (
                      <>
                        <p>{e.fallback.kind === "FALLBACK_NEW_SERIES" ? t("ex.calc_new") : t("ex.calc_inter").replace("{n}", String(sel?.fallback_window?.days))}</p>
                        <p className="formula">{fmtX(e.fallback.sum)} ÷ {fmtNum(e.fallback.known_days)} = <b>{fmtX(e.fallback.rate)}</b></p>
                        <p className="small muted">{L("Tổng và số ngày lấy từ đúng các dòng có dấu ✓ ở mục 3 (Lịch sử).", "The sum and day count are exactly the ✓ rows of section 3 (History).")}</p>
                      </>
                    )}
                    <p className="small" data-testid="rounding">{t("ex.rounding")}: max(0; {fmtX(e.fallback.rate)}) → {L("lưu 4 chữ số thập phân, hiển thị tối đa 2", "stored with 4 decimals, shown with up to 2")} = <b>{fmtX(e.fallback.value_rounded)}</b> · {t("ex.published")}: <b>{fmtX(e.result.yhat)}</b></p>
                    <p className="small">{e.fallback.matches_published ? t("ex.matches") : <span className="bad-t">{t("ex.not_matches")}</span>}</p>
                  </div>
                )
              )}
              {e.lightgbm && (!lg ? <div className="alert warn small">{t(`ex.lgb.${e.lightgbm.status}`)}</div> : (
                <div className="calc">
                  <div className="valtypes small">
                    <b>{L("Các loại giá trị", "Kinds of values")}:</b> <i>{L("giá trị đầu vào", "input value")}</i> = {L("số liệu của feature", "the feature's data")};{" "}
                    <i>{L("đóng góp", "contribution")}</i> = {L("phần feature cộng/trừ vào điểm thô", "what the feature adds to/subtracts from the raw score")};{" "}
                    <i>{L("giá trị nền", "base value")}</i>, <i>{L("điểm thô", "raw score")}</i> = {L("thang log của mô hình", "the model's log scale")};{" "}
                    <i>{L("đầu ra mô hình", "model output")}</i>, <i>{L("forecast đã publish", "published forecast")}</i> = {L("số lượng đặt/ngày", "ordered units/day")}.
                  </div>
                  <ol className="steps calcsteps" data-testid="lgb-steps">
                    <li><b>{L("Giá trị nền (base value)", "Base value")} = {fmtX(lg.bias)}</b> — {L("điểm xuất phát chung của mô hình, ở thang log (chưa phải số lượng): tổng qua các cây của giá trị kỳ vọng của từng cây = giá trị các lá có trọng số theo số dòng huấn luyện LightGBM ghi trong file mô hình cho chính cây đó (mỗi cây dùng mẫu bagging ~90%; cây đầu tiên chứa điểm khởi đầu). Không phải đúng trung bình điểm thô trên toàn bộ dữ liệu huấn luyện. Giống nhau cho mọi dòng của mô hình này.", "the model's common starting point, on the log scale (not units yet): the sum over trees of each tree's expected value = leaf values weighted by the training rows LightGBM recorded in the model file for that tree (each tree uses a ~90% bagging sample; the first tree holds the starting score). It is not exactly the mean raw score over the whole training data. The same for every row of this model.")}</li>
                    <li><b>{L("Đóng góp của từng feature", "Contribution of each feature")}</b> — {L(`mỗi feature cộng hoặc trừ vào điểm thô tùy giá trị của nó ở dòng này (TreeSHAP chính xác của LightGBM: dương = làm tăng, âm = làm giảm). Mô hình dùng ${lg.n_features} feature; bảng dưới hiển thị ${Math.min(TOP_N, feats.length)} feature có đóng góp lớn nhất — các feature khác vẫn được dùng nhưng đóng góp nhỏ hơn.`, `each feature adds to or subtracts from the raw score depending on its value in this row (LightGBM's exact TreeSHAP: positive = raises, negative = lowers). The model uses ${lg.n_features} features; the table shows the ${Math.min(TOP_N, feats.length)} largest — the others are still used, with smaller contributions.`)}
                      <div className="cols2">
                        <div><div className="small ok-t"><b>{L("Làm tăng dự báo", "Raise the forecast")}</b></div><FeatureRows rows={ups} detail={false} /></div>
                        <div><div className="small bad-t"><b>{L("Làm giảm dự báo", "Lower the forecast")}</b></div><FeatureRows rows={downs} detail={false} /></div>
                      </div>
                      <button className="link" data-testid="toggle-all-features" onClick={() => setAllFeatures((x) => !x)}>
                        {allFeatures ? L("Thu gọn", "Collapse") : L(`Xem toàn bộ ${lg.n_features} feature`, `Show all ${lg.n_features} features`)}</button>
                      {allFeatures && (
                        <div className="scroll">
                          <div className="row small">{L("Sắp xếp", "Sort")}: <button className="link" onClick={() => setSortBy("impact")} disabled={sortBy === "impact"}>{L("theo độ lớn đóng góp", "by size of contribution")}</button> · <button className="link" onClick={() => setSortBy("name")} disabled={sortBy === "name"}>{L("theo tên", "by name")}</button></div>
                          <FeatureRows rows={sorted} detail />
                        </div>
                      )}
                    </li>
                    <li><b>{L("Tổng đóng góp", "Sum of contributions")} = {fmtX(lg.contrib_sum, true)}</b> — {L(`cộng đủ ${lg.n_features} đóng góp (giá trị đầy đủ). Cộng các số đã làm tròn trên màn hình có thể lệch vài phần trăm đơn vị do làm tròn hiển thị.`, `sum of all ${lg.n_features} contributions (full precision). Adding the rounded numbers on screen can differ by a few hundredths because of display rounding.`)}</li>
                    <li><b>{L("Điểm thô (raw score)", "Raw score")} = {fmtX(lg.bias)} {lg.contrib_sum < 0 ? "−" : "+"} {fmtX(Math.abs(lg.contrib_sum))} = {fmtX(lg.raw_score)}</b> — {L("tổng giá trị nền và mọi đóng góp, vẫn ở thang log.", "base value plus every contribution, still on the log scale.")}</li>
                    <li><b>{lg.link === "exp" ? <>{L("Hàm liên kết", "Link function")}: exp({fmtX(lg.raw_score)}) = {fmtX(lg.model_output)}</> : <>{L("Không có hàm liên kết", "No link function")}: {L("đầu ra", "output")} = {fmtX(lg.model_output)}</>}</b> — {lg.link === "exp"
                      ? L(`objective ${lg.objective} học trên thang log để dự báo luôn dương và phù hợp số lượng nhiều ngày bằng 0; exp đưa điểm thô về đơn vị sản phẩm/ngày. Đây là đầu ra của mô hình (LightGBM tự tính, khớp exp của điểm thô).`, `the ${lg.objective} objective learns on a log scale so the forecast is always positive and suits zero-heavy quantities; exp turns the raw score back into units/day. This is the model output (computed by LightGBM, equal to exp of the raw score).`)
                      : L(`objective ${lg.objective} dự báo trực tiếp trên thang số lượng.`, `the ${lg.objective} objective predicts directly in units.`)}</li>
                    <li><b>{L("Xử lý sau mô hình", "Post-processing")}</b> — {L("cắt về ≥ 0", "clip at ≥ 0")}{lg.clip_applied ? L(" (đã áp dụng: đầu ra âm → 0)", " (applied: negative output → 0)") : L(" (không cần, đầu ra đã dương)", " (not needed, output already positive)")}; {L("lưu với 4 chữ số thập phân", "stored with 4 decimals")}.</li>
                    <li className="small muted">{L("Bấm \"Vì sao?\" ở một feature để xem trace TreeSHAP theo từng cây và từng lá, có đối soát với LightGBM.", "Click \"Why?\" on a feature to see its TreeSHAP trace per tree and per leaf, reconciled with LightGBM.")}</li>
                  <li data-testid="rounding"><b>{L("Forecast đã publish", "Published forecast")} = {fmtX(lg.published_yhat)}</b> {L("(bảng dự báo, Excel)", "(forecast table, Excel)")} · {lg.matches_published ? <span className="ok-t">{t("ex.matches")}</span> : <span className="bad-t">{t("ex.not_matches")}</span>}</li>
                  </ol>
                  <p className="small muted">{t("ex.shap_note")}</p>
                </div>
              ))}
            </Block>

            <Block title={`3. ${L("Lịch sử demand và xuất Excel", "Demand history and Excel export")}`} testid="ex-history">
              {e.history.status !== "OK" ? <div className="alert warn small">{t(`ex.hist.${e.history.status}`)}</div> : (
                <>
                  <p className="small">{t("ex.hist_range").replace("{n}", String(e.history.window_days ?? e.history.days.length))}: <b>{fmtDate(e.history.window_start)} → {fmtDate(e.history.window_end)}</b> · {t("ex.hist_orders")}: {e.history.summary.ORDERS} · {t("ex.hist_zero")}: {e.history.summary.ZERO_ORDERS} · {t("ex.hist_nodata")}: {e.history.summary.NO_DATA} · {t("ex.hist_before")}: {e.history.summary.BEFORE_START}
                    {" "}<a className="btn small" href={histUrl} data-testid="history-xlsx">{L("Xuất Excel lịch sử", "Export history to Excel")}</a></p>
                  {e.history.calc && e.history.calc.kind !== "LIGHTGBM_FEATURE_WINDOWS" && (
                    <p className="small" data-testid="hist-calc">{t("ex.hist_calc").replace("{from}", fmtDate(e.history.calc.from)).replace("{to}", fmtDate(e.history.calc.to))
                      .replace("{n}", fmtNum(e.history.calc.known_days)).replace("{s}", fmtX(e.history.calc.sum))}
                      {e.fallback?.matches_history === true && <span className="ok-t"> · {t("ex.hist_matches")}</span>}
                      {e.fallback?.matches_history === false && <span className="bad-t"> · {t("ex.hist_not_matches")}</span>}</p>
                  )}
                  {e.history.calc?.kind === "LIGHTGBM_FEATURE_WINDOWS" && (
                    <p className="small" data-testid="hist-calc">{L(`Các ngày ✓ được feature của ngày dự báo đọc (cột "Feature dùng ngày này"); lag/rolling xét tối đa 56 ngày, days_since_last_sale xét ${e.history.calc.last_sale_window_days} ngày.`, `✓ days are read by the target day's features (column "Features reading this day"); lags/rolling look back at most 56 days, days_since_last_sale ${e.history.calc.last_sale_window_days} days.`)}
                      {e.history.calc.recursive_days > 0 && <> {L(`Các ngày ${fmtDate(e.history.calc.recursive_from)} → ${fmtDate(e.history.calc.recursive_to)} sau ngày dữ liệu cuối dùng chính dự báo của mô hình (đệ quy) và không có trong bảng này.`, `Days ${fmtDate(e.history.calc.recursive_from)} → ${fmtDate(e.history.calc.recursive_to)} after the last data day use the model's own forecasts (recursion) and are not in this table.`)}</>}</p>
                  )}
                  <div className="scroll histtable">
                    <table className="tbl small" data-testid="history-table">
                      <thead><tr><th>{t("ex.hist_date")}</th><th>{L("Thứ", "Weekday")}</th><th className="num">{t("ex.hist_demand")}</th><th>{t("ex.hist_status")}</th>
                        {e.history.calc && <th>{t("ex.hist_used")}</th>}{lg && <th>{L("Feature dùng ngày này", "Features reading this day")}</th>}</tr></thead>
                      <tbody>
                        {e.history.days.map((x: any) => (
                          <tr key={x.date} className={x.in_calc ? "incalc" : ""} data-date={x.date}>
                            <td>{fmtDate(x.date)}</td>
                            <td>{weekdayName(x.date, lang)}</td>
                            <td className="num">{x.qty == null ? <span className="muted">—</span> : fmtX(x.qty)}</td>
                            <td className={`small hd-${x.status}`}>{t(`ex.day.${x.status}`)}</td>
                            {e.history.calc && <td>{x.in_calc ? "✓" : ""}</td>}
                            {lg && <td className="small mono">{(x.used_by ?? []).join(", ")}</td>}
                          </tr>
                        ))}
                      </tbody>
                      {e.history.calc && e.history.calc.kind !== "LIGHTGBM_FEATURE_WINDOWS" && (
                        <tfoot><tr><td colSpan={2}><b>{t("ex.hist_used_total")}</b></td><td className="num"><b>{fmtX(e.history.calc.sum)}</b></td>
                          <td colSpan={2} className="small">{fmtNum(e.history.calc.known_days)} {t("ex.known_days")}</td></tr></tfoot>
                      )}
                    </table>
                  </div>
                  <p className="small muted">{t("ex.hist_legend")}</p>
                </>
              )}
            </Block>

            <Block title={`6. ${L("Chất lượng dự báo", "Forecast quality")}`} testid="ex-quality">
              {!bm ? <p className="small muted">{L("Không có dữ liệu backtest để xác minh.", "No backtest data to verify.")}</p> : (
                <>
                  <p className="small">{L(`Đánh giá bằng backtest walk-forward của lần huấn luyện tạo ra mô hình này (backtest ${q.backtest_id}): mô hình được huấn luyện lại chỉ với dữ liệu trước mỗi mốc, dự báo ${q.backtest_config?.horizon_days} ngày tiếp theo rồi so với thực tế đã biết. Số liệu dưới đây là của phương pháp ${reg?.methods?.[e.result.method]?.vi?.name ?? e.result.method} trong backtest.`, `Evaluated by the walk-forward backtest of the training run that produced this model (backtest ${q.backtest_id}): the model is retrained with data before each cutoff only, forecasts the next ${q.backtest_config?.horizon_days} days and is compared with known actuals. Figures below are for this method in the backtest.`)}</p>
                  <table className="tbl small" data-testid="quality-metrics"><tbody>
                    <tr><td><b>WAPE</b></td><td>Σ|{L("thực tế", "actual")} − {L("dự báo", "forecast")}| ÷ Σ{L("thực tế", "actual")} = {fmtX(bm.sum_abs_error)} ÷ {fmtX(bm.sum_actual)} = <b>{fmtPctX(bm.wape)}</b></td>
                      <td className="small">{L("Sai số tuyệt đối so với tổng nhu cầu; càng thấp càng tốt. Là con số gộp: không có nghĩa mọi SKU×FC đều dự báo tốt như vậy.", "Absolute error relative to total demand; lower is better. A pooled figure: it does not mean every SKU×FC is that accurate.")}</td></tr>
                    <tr><td><b>Bias</b></td><td>(Σ{L("dự báo", "forecast")} − Σ{L("thực tế", "actual")}) ÷ Σ{L("thực tế", "actual")} = ({fmtX(bm.sum_forecast)} − {fmtX(bm.sum_actual)}) ÷ {fmtX(bm.sum_actual)} = <b>{fmtPctX(bm.bias, true)}</b></td>
                      <td className="small">{bm.bias > 0 ? L(`Dương: tổng dự báo CAO hơn tổng thực tế ${fmtPctX(bm.bias)} (quy ước của code: dương = dự báo dư, âm = dự báo thiếu).`, `Positive: total forecast is ${fmtPctX(bm.bias)} ABOVE total actual (code convention: positive = over-forecast).`)
                        : L(`Âm: tổng dự báo THẤP hơn tổng thực tế ${fmtPctX(Math.abs(bm.bias))} (quy ước của code: dương = dự báo dư, âm = dự báo thiếu).`, `Negative: total forecast is ${fmtPctX(Math.abs(bm.bias))} BELOW total actual (code convention: positive = over-forecast).`)}{" "}
                        {L("Khác WAPE: Bias có hướng; sai lệch ngược chiều giữa các SKU×FC có thể bù trừ nên Bias tổng gần 0 không có nghĩa từng SKU×FC đều đúng.", "Unlike WAPE it has a direction; opposite errors of different SKU×FCs can cancel out, so a total Bias near 0 does not mean each SKU×FC is right.")}</td></tr>
                    <tr><td><b>{L("Số điểm đánh giá", "Evaluation points")}</b></td><td><b>{fmtNum(bm.n_points)}</b></td>
                      <td className="small">{L(`Mỗi điểm là một cặp (thực tế, dự báo) của một SKU×FC×ngày trong một fold; ngày không rõ thực tế bị loại; thực tế = 0 vẫn được tính. Không phải ${fmtNum(bm.n_points)} ngày.`, `Each point is one (actual, forecast) pair of one SKU×FC×date in one fold; days without a known actual are excluded; actual = 0 is included. Not ${fmtNum(bm.n_points)} days.`)}
                        {q.folds_overlap && <> {L("Các fold chồng ngày nhau nên một SKU×FC×ngày có thể được đếm 2 lần (do 2 mô hình khác nhau dự báo).", "Folds overlap, so one SKU×FC×date can be counted twice (forecast by 2 different models).")}</>}</td></tr>
                  </tbody></table>
                  <p className="small">{L("Các fold", "Folds")}: {(q.backtest_folds ?? []).map((f: any) => `#${f.fold} ${fmtDate(f.origin)} → ${fmtDate(f.end)} (${fmtNum(f.n_points)} ${L("điểm, tất cả phương pháp", "points, all methods")})`).join(" · ")}
                    {e.identity.training_run_id && <> · <a href={`/api/training-runs/${e.identity.training_run_id}/backtest-points.xlsx?lang=${lang}`} data-testid="backtest-xlsx">{L("Tải các điểm backtest (Excel)", "Download backtest points (Excel)")}</a></>}</p>
                  {gate?.checks && (
                    <>
                      <table className="tbl small" data-testid="gate-table">
                        <thead><tr><th>{L("Điều kiện", "Check")}</th><th className="num">{L("Giá trị", "Value")}</th><th className="num">{L("Ngưỡng", "Threshold")}</th><th>{L("Kết quả", "Result")}</th></tr></thead>
                        <tbody>
                          {gate.checks.map((c: any) => (
                            <tr key={c.check}><td>{t(`perf.check.${c.check}`)}</td>
                              <td className="num">{c.check === "WAPE_MAX" ? fmtPctX(c.value) : c.check === "ABS_BIAS_MAX" ? `|${fmtPctX(c.value, true)}|` : fmtNum(c.value)}</td>
                              <td className="num">{c.threshold == null ? "—" : c.check === "WAPE_MAX" ? `≤ ${fmtPctX(c.threshold)}` : c.check === "ABS_BIAS_MAX" ? `≤ ${fmtPctX(c.threshold)}` : c.check === "BEAT_BASELINE" ? `< ${fmtPctX(c.threshold)}` : `≥ ${fmtNum(c.threshold)}`}</td>
                              <td className={c.passed ? "ok-t" : "bad-t"}>{c.passed ? L("Đạt", "Pass") : L("Không đạt", "Fail")}</td></tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="small">{L(`Kết quả chung: ${gate.passed ? "ĐẠT — mọi điều kiện đạt" : "KHÔNG ĐẠT — có điều kiện không đạt"}. Pooled (mọi phương pháp) dùng cho quality gate; so sánh trên giá trị đầy đủ, không làm tròn. Ngưỡng lấy từ cấu hình lúc huấn luyện.`, `Overall: ${gate.passed ? "PASSED — all checks pass" : "FAILED — at least one check fails"}. The gate uses pooled metrics (all methods), compared at full precision. Thresholds come from the configuration at training time.`)}</p>
                      {!gate.thresholds_approved_by_business && (
                        <div className="alert warn small" data-testid="gate-not-approved">{L("Ngưỡng chất lượng hiện là giá trị ví dụ, CHƯA được nghiệp vụ phê duyệt: \"Đạt\" chỉ có nghĩa là đạt theo cấu hình hiện tại, không bảo đảm forecast chính xác cho mọi SKU×FC.", "Quality thresholds are example values, NOT business-approved: \"Passed\" only means passed under the current configuration and does not guarantee accuracy for every SKU×FC.")}</div>
                      )}
                    </>
                  )}
                </>
              )}
              <p className="small"><a href="/methodology#training">{L("Mô hình đã học từ dữ liệu nào? Quy trình huấn luyện và kiểm định →", "What data did the model learn from? Training and validation →")}</a></p>
            </Block>

            {/* ---------------------------------------------------------------- level 3: technical, verifiable */}
            <Block title={L("Chi tiết kỹ thuật (độ chính xác đầy đủ)", "Technical details (full precision)")} testid="ex-tech">
              {lg ? (
                <table className="tbl small mono" data-testid="tech-table"><tbody>
                  <tr><td>objective / link</td><td>{lg.objective} / {lg.link}</td></tr>
                  <tr><td>{L("phương pháp đóng góp", "attribution")}</td><td>{lg.attribution_method}</td></tr>
                  <tr><td>{L("số cây", "trees")}</td><td>{lg.n_trees} · {L("feature", "features")} {lg.n_features} ({lg.n_features_used_in_trees} {L("được cây dùng", "used by trees")})</td></tr>
                  <tr><td>base value</td><td>{lg.bias}</td></tr>
                  <tr><td>Σ contributions</td><td>{lg.contrib_sum}</td></tr>
                  <tr><td>raw score</td><td>{lg.raw_score}</td></tr>
                  <tr><td>model output (LightGBM predict)</td><td>{lg.model_output}</td></tr>
                  <tr><td>max(0, output)</td><td>{lg.clipped}</td></tr>
                  <tr><td>{L("làm tròn 4 chữ số (tái lập)", "rounded to 4 decimals (reproduced)")}</td><td>{lg.reproduced_yhat}</td></tr>
                  <tr><td>{L("giá trị đã publish (DB)", "published value (DB)")}</td><td>{lg.published_yhat}</td></tr>
                </tbody></table>
              ) : e.fallback && (
                <table className="tbl small mono"><tbody>
                  <tr><td>sum / known_days</td><td>{e.fallback.sum} / {e.fallback.known_days}</td></tr>
                  <tr><td>rate</td><td>{e.fallback.rate}</td></tr>
                  <tr><td>{L("làm tròn 4 chữ số", "rounded to 4 decimals")}</td><td>{e.fallback.value_rounded}</td></tr>
                  <tr><td>{L("giá trị đã publish (DB)", "published value (DB)")}</td><td>{e.result.yhat}</td></tr>
                </tbody></table>
              )}
              {lg?.global_importance?.length > 0 && (
                <p className="small muted">{L("Mức quan trọng toàn mô hình (gain, cả tập huấn luyện — KHÔNG phải đóng góp của dòng này)", "Model-wide importance (gain over the whole training set — NOT this row's contribution)")}: {lg.global_importance.slice(0, 8).map((g: any) => g.feature).join(", ")}</p>
              )}
              <p className="small muted">{t("ex.limits")} · {t("fc.run_at")}: {fmtTime(e.identity.run_created_at)}</p>
            </Block>
          </div>
        )}
      </div>
      {traceFeature && <ShapTrace runId={runId} sku={sku} fc={fc} date={d} feature={traceFeature} onClose={() => setTraceFeature(null)} />}
    </div>
  );
}
