import { useEffect, useState, type ReactNode } from "react";
import { get, qs } from "../api";
import { useI18n } from "../i18n";
import { ErrorBox, Loading, fmtDate, fmtNum, fmtX, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

/** Technical numbers (levels B and C): up to 6 decimals, trailing zeros removed; the exports keep every digit. */
const fx6 = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "—" : (v > 0 ? "+" : "") + fmtNum(v, 6));
const fsci = (v: number) => (v === 0 ? "0" : v.toExponential(2));

function Details({ title, open = false, children, testid }: { title: ReactNode; open?: boolean; children: ReactNode; testid?: string }) {
  return (
    <details className="exblock" open={open} data-testid={testid}>
      <summary><h4>{title}</h4></summary>
      <div className="exbody">{children}</div>
    </details>
  );
}

/** "Why does this feature have this contribution?" — TreeSHAP audit trace of one feature of one published value.
 *  Everything comes from /api/forecast-runs/{id}/shap-trace (backend ml/shap_audit.py + ml/treeshap_trace.py). */
export default function ShapTrace({ runId, sku, fc, date, feature, onClose }: {
  runId: string; sku: string; fc: string; date: string; feature: string; onClose: () => void;
}) {
  const { lang } = useI18n();
  const vi = lang === "vi";
  const L = (a: string, b: string) => (vi ? a : b);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<"impact" | "tree">("impact");
  const [tree, setTree] = useState<number | null>(null);
  const base = { sku_id: sku, fc_id: fc, target_date: date };
  const tr = useAsync(() => get(`/api/forecast-runs/${runId}/shap-trace${qs({ ...base, feature, page, page_size: 20, sort })}`), [runId, sku, fc, date, feature, page, sort]);
  const tt = useAsync(() => (tree === null ? Promise.resolve(null) : get(`/api/forecast-runs/${runId}/shap-trace/tree${qs({ ...base, feature, tree })}`)), [tree, feature]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [onClose]);
  const d = tr.data;
  const fv = d?.feature_view;
  const f = fv?.feature;
  const s = fv?.summary;
  const dl = (fmt: string, feat: string | null) => `/api/forecast-runs/${runId}/shap-trace.${fmt}${qs({ ...base, feature: feat, lang })}`;
  const statusBox = d && (
    d.status === "VERIFIED" ? <span className="pill ok" data-testid="trace-status">{L("Đã xác minh: khớp tuyệt đối với LightGBM", "Verified: matches LightGBM exactly")}</span>
      : d.status === "FAILED" ? <div className="alert bad small" data-testid="trace-status">{L("Đối soát thất bại — trace KHÔNG được coi là chính xác. Kiểm tra không đạt:", "Reconciliation failed — the trace is NOT presented as exact. Failing checks:")} {(d.checks ?? []).filter((c: any) => !c.passed).map((c: any) => c.check).join(", ")}</div>
        : <div className="alert warn small" data-testid="trace-status">{L("Không đủ dữ liệu để tái hiện chính xác", "Not enough data to reproduce exactly")} ({d.reason}). {L("Không dùng mô hình khác để thay thế.", "No other model is used instead.")}</div>
  );
  return (
    <div className="modal-bg nested" role="dialog" aria-modal="true" aria-label="TreeSHAP" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()} data-testid="shap-trace">
        <div className="row between">
          <h3>{L("Vì sao feature này có đóng góp như vậy?", "Why does this feature contribute this much?")} <span className="mono">{feature}</span></h3>
          <button className="icon-btn ghost" onClick={onClose} aria-label={L("Đóng", "Close")} title={L("Đóng", "Close")}><Icon name="close" /></button>
        </div>
        <p className="small muted">{sku} · {fc} · {fmtDate(date)} · <span className="mono">{runId}</span></p>
        {tr.loading && !d && <Loading />}
        <ErrorBox error={tr.error} />
        {d && statusBox}
        {d && d.status !== "NOT_REPRODUCIBLE" && fv && (
          <div className="stack">
            {/* ---------------------------------------------------------------- level A */}
            <section className="exsummary" data-testid="trace-level-a">
              <p><b>{f.catalog?.[lang]?.name ?? feature}</b> <span className="mono muted">({feature})</span></p>
              <table className="tbl small"><tbody>
                <tr><td>{L("Giá trị đầu vào (chính xác)", "Input value (exact)")}</td><td className="mono">{f.value === null ? L("thiếu (NaN)", "missing (NaN)") : String(f.value)}</td></tr>
                <tr><td>{L("Định nghĩa", "Definition")}</td><td>{f.catalog?.[lang]?.formula} {f.catalog?.[lang]?.unit && <span className="muted">({f.catalog[lang].unit})</span>}</td></tr>
                <tr><td>{L("Khoảng ngày", "Days used")}</td><td>{f.window ? (f.window.from === f.window.to ? fmtDate(f.window.from) : `${fmtDate(f.window.from)} → ${fmtDate(f.window.to)}`) : "—"}</td></tr>
                <tr><td><b>SHAP</b></td><td><b className={f.shap_engine > 0 ? "ok-t" : f.shap_engine < 0 ? "bad-t" : ""}>{fmtX(f.shap_engine, true)}</b> <span className="mono small muted">({f.shap_engine})</span></td></tr>
              </tbody></table>
              <p className="small">{L(
                `Đây là đóng góp vào ĐIỂM THÔ (thang log của mô hình), không cộng trực tiếp vào số lượng dự báo: forecast = exp(giá trị nền + tổng SHAP của 33 feature). Đóng góp này là tổng của ${fmtNum(s.n_terms)} thành phần nằm trong ${fmtNum(s.n_trees_with_terms)} cây — đúng các cây có ít nhất một lần tách theo ${feature} (${fmtNum(s.n_trees_splitting_on_feature)}/${fmtNum(s.n_trees_model)} cây); TreeSHAP chỉ cộng cho một feature tại các nút tách theo chính feature đó.`,
                `This is a contribution to the RAW SCORE (the model's log scale), not added directly to the forecast quantity: forecast = exp(base value + sum of the 33 SHAP values). It is the sum of ${fmtNum(s.n_terms)} terms in ${fmtNum(s.n_trees_with_terms)} trees — exactly the trees with at least one split on ${feature} (${fmtNum(s.n_trees_splitting_on_feature)}/${fmtNum(s.n_trees_model)} trees); TreeSHAP only adds to a feature at nodes that split on that feature.`)}</p>
              <p className="small" data-testid="trace-signs">{L("Thành phần dương", "Positive terms")}: <b className="ok-t">{fmtX(s.sum_positive_terms, true)}</b> · {L("thành phần âm", "negative terms")}: <b className="bad-t">{fmtX(s.sum_negative_terms, true)}</b> · {L("tổng", "total")}: <b>{fmtX(s.total, true)}</b>
                {Math.abs(s.sum_negative_terms) > 0.05 * Math.abs(s.sum_positive_terms) && <> — {L("các thành phần ngược dấu triệt tiêu một phần nhau.", "terms of opposite sign partly cancel each other.")}</>}
                <br />{L("Theo cây", "By tree")}: {L("tổng các cây có đóng góp dương", "trees with a positive sum")} {fmtX(s.sum_positive_trees, true)} · {L("cây có đóng góp âm", "trees with a negative sum")} {fmtX(s.sum_negative_trees, true)}.</p>
            </section>

            {/* ---------------------------------------------------------------- level B */}
            <Details title={L("Cấp B — chi tiết tính toán theo cây và theo lá", "Level B — calculation by tree and by leaf")} open testid="trace-level-b">
              <p className="small muted">{L("Số kỹ thuật hiển thị tối đa 6 chữ số thập phân; file tải về giữ đủ mọi chữ số.", "Technical numbers show up to 6 decimals; downloads keep every digit.")}</p>
              <div className="row small">{L("Sắp xếp", "Sort")}: <button className="link" disabled={sort === "impact"} onClick={() => { setSort("impact"); setPage(1); }}>{L("theo độ lớn", "by size")}</button> · <button className="link" disabled={sort === "tree"} onClick={() => { setSort("tree"); setPage(1); }}>{L("theo số cây", "by tree index")}</button></div>
              <div className="scroll">
                <table className="tbl small" data-testid="trace-trees">
                  <thead><tr><th>{L("Cây", "Tree")}</th><th className="num">{L("Tổng trong cây", "Tree sum")}</th><th className="num">{L("Phần dương", "Positive")}</th><th className="num">{L("Phần âm", "Negative")}</th><th className="num">{L("Số thành phần", "Terms")}</th><th>{L("Các lần tách theo feature (ngưỡng → dòng này đi)", "Splits on the feature (threshold → this row goes)")}</th><th></th></tr></thead>
                  <tbody>{fv.trees.items.map((t: any) => (
                    <tr key={t.tree} className={tree === t.tree ? "sel" : ""}><td>{t.tree}</td><td className="num">{fx6(t.sum)}</td><td className="num ok-t">{fx6(t.positive)}</td><td className="num bad-t">{fx6(t.negative)}</td><td className="num">{t.n_terms}</td>
                      <td className="small mono">{(t.splits ?? []).map((sp: any) => `${sp.split.split(" (")[0]} → ${sp.row_goes === "left" ? L("trái", "left") : L("phải", "right")}`).join(" · ")}</td>
                      <td><button className="link" onClick={() => setTree(t.tree)} data-testid={`trace-open-tree-${t.tree}`}>{L("Xem lá", "Leaves")}</button></td></tr>
                  ))}</tbody>
                </table>
              </div>
              <div className="row small">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)}>←</button>
                <span>{L("Trang", "Page")} {page} / {Math.max(1, Math.ceil(fv.trees.total / fv.trees.page_size))} · {fmtNum(fv.trees.total)} {L("cây", "trees")}</span>
                <button disabled={page * fv.trees.page_size >= fv.trees.total} onClick={() => setPage(page + 1)}>→</button>
              </div>
              {tree !== null && (
                <div className="calc" data-testid="trace-leaves">
                  {tt.loading && <Loading />}
                  <ErrorBox error={tt.error} />
                  {tt.data && (
                    <>
                      <p className="small"><b>{L("Cây", "Tree")} {tt.data.tree}</b>: {L("giá trị kỳ vọng của cây", "tree expected value")} {fx6(tt.data.expected_value)} · {L("số dòng huấn luyện ở gốc", "training rows at the root")} {fmtNum(tt.data.root_count)} · {L("dòng này rơi vào lá", "this row reaches leaf")} {tt.data.actual_leaf} · {L("tổng thành phần của", "sum of terms of")} {feature} = <b>{fx6(tt.data.sum)}</b></p>
                      <div className="scroll">
                        <table className="tbl small mono">
                          <thead><tr><th>{L("Lá", "Leaf")}</th><th className="num">{L("Giá trị lá v", "Leaf value v")}</th><th className="num">{L("Số dòng", "Rows")}</th><th>{L("Dòng này tới lá?", "Row reaches?")}</th><th className="num">one</th><th className="num">zero</th><th className="num">w</th><th className="num">{L("Thành phần", "Term")} = w·(one−zero)·v</th><th>{L("Đường đi", "Route")}</th></tr></thead>
                          <tbody>{tt.data.items.map((it: any) => (
                            <tr key={it.leaf} className={it.row_reaches_leaf ? "incalc" : ""}>
                              <td>{it.leaf}</td><td className="num">{fx6(it.leaf_value)}</td><td className="num">{fmtNum(it.leaf_count)}</td><td>{it.row_reaches_leaf ? "✓" : ""}</td>
                              <td className="num">{it.one_fraction}</td><td className="num">{fmtNum(it.zero_fraction, 6)}</td><td className="num">{fmtNum(it.weight, 6)}</td>
                              <td className={`num ${it.term > 0 ? "ok-t" : it.term < 0 ? "bad-t" : ""}`}>{Math.abs(it.term) < 5e-7 && it.term !== 0 ? fsci(it.term) : fx6(it.term)}</td>
                              <td className="small"><details><summary>{it.route.length} {L("bước", "steps")}</summary>{it.route.map((st: any, i: number) => (
                                <div key={i} className={st.is_feature ? "b" : ""}>{st.split.split(" (")[0]} → {st.went === "left" ? L("trái", "left") : L("phải", "right")} {st.row_goes_this_way ? "" : L("(dòng này KHÔNG đi)", "(row does NOT go)")} · {L("tỷ lệ cover", "cover")} {fmtNum(st.cover_fraction, 4)}</div>
                              ))}</details></td>
                            </tr>
                          ))}</tbody>
                        </table>
                      </div>
                      <p className="small muted">{L(
                        "one = 1 nếu giá trị của dòng này đi đúng mọi nhánh tách theo feature trên đường tới lá, ngược lại 0. zero = tích các tỷ lệ cover (số dòng huấn luyện của nhánh ÷ của nút) ở các lần tách theo feature: phần dữ liệu đi đường này khi KHÔNG biết feature. w = trọng số Shapley của feature trên đường đi (tổng theo mọi tổ hợp của các feature khác trên đường đi). Lá dòng này không tới vẫn có thành phần (one = 0): chúng biểu diễn trường hợp 'không biết feature' và thường làm giảm/triệt tiêu.",
                        "one = 1 if this row's value takes every split on the feature along the route to the leaf, else 0. zero = product of cover fractions (training rows of the branch ÷ of the node) at the splits on the feature: the share of data taking this way when the feature is NOT known. w = Shapley weight of the feature on the route (sum over all coalitions of the other features on the route). Leaves the row does not reach still contribute (one = 0): they represent the 'feature unknown' case and usually reduce/cancel.")}</p>
                    </>
                  )}
                </div>
              )}
            </Details>

            {/* ---------------------------------------------------------------- level C */}
            <Details title={L("Cấp C — thuật toán, giá trị nền và đối soát", "Level C — algorithm, base value and reconciliation")} testid="trace-level-c">
              <div className="small stack">
                <p className="formula">φ<sub>f</sub> = Σ<sub>{L("cây", "trees")} t</sub> Σ<sub>{L("lá", "leaves")} ℓ ∈ t, f ∈ P(ℓ)</sub> w<sub>f,ℓ</sub> · (one<sub>f,ℓ</sub> − zero<sub>f,ℓ</sub>) · v<sub>ℓ</sub></p>
                <ul>
                  <li>{L("P(ℓ): các feature được tách trên đường từ gốc tới lá ℓ (mỗi feature một lần — lần tách lặp lại được gộp: one nhân, zero nhân).", "P(ℓ): features split on the path from the root to leaf ℓ (each once — repeated splits are merged: one multiplied, zero multiplied).")}</li>
                  <li>{L("w: trọng số Shapley = Σ trên mọi tập con S của các feature khác trong P(ℓ) của |S|!(d−|S|−1)!/d! × Π one (S) × Π zero (phần còn lại); được tính bằng phép đệ quy đa thức ExtendPath/UnwoundPathSum, không liệt kê từng tập con.", "w: Shapley weight = sum over subsets S of the other features in P(ℓ) of |S|!(d−|S|−1)!/d! × Π one (S) × Π zero (rest); computed by the polynomial ExtendPath/UnwoundPathSum recursion, without enumerating subsets.")}</li>
                  <li>{L("Feature 'đã xét' (có trong S) dùng giá trị thật của dòng (one); feature 'chưa xét' dùng phân phối dữ liệu huấn luyện theo cover của cây (zero) — biến thể 'path-dependent' của TreeSHAP.", "Features 'present' (in S) use the row's real value (one); features 'absent' use the training-data distribution through the tree's cover (zero) — the 'path-dependent' TreeSHAP variant.")}</li>
                  <li>{L("Giá trị nền = Σ cây của giá trị kỳ vọng của cây = Σ lá (số dòng của lá ÷ số dòng ở gốc của cây) × giá trị lá. Số dòng là số dòng huấn luyện LightGBM ghi trong file mô hình cho chính cây đó (bagging 90% ⇒ mỗi cây một mẫu con), và lá của cây đầu tiên đã chứa điểm khởi đầu (boost_from_average). Vì vậy đây KHÔNG đúng bằng trung bình điểm thô trên toàn bộ dữ liệu huấn luyện.", "Base value = sum over trees of each tree's expected value = sum over leaves (leaf rows ÷ root rows of that tree) × leaf value. The rows are the training rows LightGBM recorded in the model file for that very tree (90% bagging ⇒ each tree its own sub-sample), and the first tree's leaves already contain the starting score (boost_from_average). So it is NOT exactly the mean raw score over the whole training data.")}</li>
                  <li>{L("Cộng qua cây theo đúng thứ tự LightGBM (cây 0 → cây cuối, đệ quy nhánh dòng này đi trước, nhánh còn lại sau) bằng số thực double; điểm thô = giá trị nền + Σ φ.", "Summed over trees in LightGBM's order (tree 0 → last, the row's branch first, the other branch next) in double precision; raw score = base value + Σ φ.")}</li>
                </ul>
                <table className="tbl small mono" data-testid="trace-checks">
                  <thead><tr><th>{L("Đối soát", "Check")}</th><th>{L("Kết quả", "Result")}</th><th>{L("Sai lệch tuyệt đối", "Abs. difference")}</th><th>{L("Dung sai", "Tolerance")}</th></tr></thead>
                  <tbody>{(d.checks ?? []).map((c: any) => (
                    <tr key={c.check}><td>{c.check}</td><td className={c.passed ? "ok-t" : "bad-t"}>{c.passed ? "PASS" : "FAIL"}</td><td>{c.max_abs_diff ?? c.abs_diff ?? ""}</td><td>{c.tolerance ?? ""}</td></tr>
                  ))}</tbody>
                </table>
                <table className="tbl small mono"><tbody>
                  <tr><td>base value (engine / LightGBM)</td><td>{d.values.base_value} / {d.values.base_value_lightgbm}</td></tr>
                  <tr><td>Σ SHAP</td><td>{d.values.sum_shap}</td></tr>
                  <tr><td>raw score = base + Σ SHAP</td><td>{d.values.raw_score_from_attribution}</td></tr>
                  <tr><td>raw score (LightGBM predict raw_score)</td><td>{d.values.raw_score_from_model}</td></tr>
                  <tr><td>{d.identity.link === "exp" ? "exp(raw score)" : "raw score"} / LightGBM output</td><td>{d.values.link_of_raw} / {d.values.model_output}</td></tr>
                  <tr><td>max(0, output) → {L("làm tròn 4 chữ số", "rounded to 4 decimals")}</td><td>{d.values.clipped} → {d.values.rounded_4}</td></tr>
                  <tr><td>{L("giá trị đã publish", "published value")}</td><td>{d.values.published}</td></tr>
                  <tr><td>model sha256 · feature row sha256</td><td className="small">{d.identity.model_sha256_file} · {d.identity.feature_row_hash}</td></tr>
                </tbody></table>
                <p>{L("Nguồn đã đối chiếu", "Verified references")}: <a href="https://github.com/microsoft/LightGBM/blob/v4.7.0/src/io/tree.cpp" target="_blank" rel="noreferrer">LightGBM v4.7.0 src/io/tree.cpp (TreeSHAP)</a> · <a href="https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.Booster.html" target="_blank" rel="noreferrer">Booster.predict(pred_contrib=True)</a> · <a href="https://arxiv.org/abs/1802.03888" target="_blank" rel="noreferrer">Lundberg, Erion & Lee (2018), Algorithm 2</a></p>
              </div>
            </Details>

            <p className="small" data-testid="trace-downloads">{L("Tải trace", "Download trace")}: <a href={dl("xlsx", feature)}>{feature} (Excel)</a> · <a href={dl("csv", feature)}>{feature} (CSV)</a> · <a href={dl("xlsx", null)}>{L("cả 33 feature (Excel)", "all 33 features (Excel)")}</a> · <a href={dl("csv", null)}>{L("cả 33 feature (CSV)", "all 33 features (CSV)")}</a></p>
          </div>
        )}
      </div>
    </div>
  );
}
