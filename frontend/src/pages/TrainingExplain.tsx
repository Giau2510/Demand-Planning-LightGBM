import { useState, type ReactNode } from "react";
import { get, qs } from "../api";
import { useI18n } from "../i18n";
import { Code, ErrorBox, Loading, MethodLabel, fmtDate, fmtNum, fmtPctX, fmtTime, fmtX, useAsync } from "../components/ui";

/** Source badge: every figure on this page says where it comes from. */
function Src({ children }: { children: ReactNode }) {
  return <span className="srcbadge">{children}</span>;
}

function Sec({ id, title, children, open = false }: { id?: string; title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="exblock" id={id} open={open}>
      <summary><h4>{title}</h4></summary>
      <div className="exbody">{children}</div>
    </details>
  );
}

/** "How was the model trained?" — read-only, from the training run, the saved model file and the backtest. */
export function TrainingExplain() {
  const { lang, t } = useI18n();
  const vi = lang === "vi";
  const L = (a: string, b: string) => (vi ? a : b);
  const [runId, setRunId] = useState<string | null>(null);
  const o = useAsync(() => get(`/api/model/training-explain${qs({ training_run_id: runId })}`), [runId]);
  if (o.loading && !o.data) return <Loading />;
  if (o.error) return <ErrorBox error={o.error} />;
  const d = o.data;
  if (!d || !d.active) return <p className="muted">{L("Không có dữ liệu để xác minh.", "No data to verify.")}</p>;
  const tr = d.training_run;
  const act = d.active;
  const isDemo = tr?.data_source === "DEMO";
  const p = d.params ?? {};
  const c = d.config ?? {};
  const bt = d.backtest;
  const gate = d.quality_gate;
  const fromRun = <Src>{L("Nguồn: training run", "Source: training run")} {tr?.id}</Src>;
  return (
    <div className="stack" data-testid="training-explain">
      {!act.has_dataset && (
        <div className="alert warn small" data-testid="no-dataset">{L(
          `Nguồn đang hoạt động ${act.active_source} chưa có bộ dữ liệu nên CHƯA huấn luyện được cho nguồn này (cần: import file Excel, kiểm tra và xác nhận lô dữ liệu, rồi chạy huấn luyện). Thông tin dưới đây là của một lần huấn luyện đã có trước đó.`,
          `The active source ${act.active_source} has no dataset, so the model CANNOT be trained for it yet (needed: import an Excel file, validate and confirm the batch, then train). The information below belongs to an earlier training run.`)}</div>
      )}
      {!tr ? <p className="muted">{L("Chưa có lần huấn luyện nào được chấp nhận — chưa có mô hình.", "No accepted training run yet — there is no model.")}</p> : (
        <>
          <div className="row wrap small">
            <label className="row">{L("Lần huấn luyện", "Training run")}:
              <select value={tr.id} onChange={(e) => setRunId(e.target.value)} data-testid="training-run-select">
                {d.runs.map((r: any) => <option key={r.id} value={r.id}>{fmtTime(r.started_at)} · {r.id} · {r.data_source} · {t(`status.${r.status}`)}</option>)}
              </select></label>
            <span>{L("Trạng thái", "Status")}: <b>{t(`status.${tr.status}`)}</b>{tr.reject_reason && <> · <Code code={tr.reject_reason} /></>}</span>
          </div>
          {isDemo && <div className="alert info small" data-testid="demo-model">{L("Mô hình này được huấn luyện trên dữ liệu DEMO (mô phỏng), KHÔNG phải dữ liệu kinh doanh thật.", "This model was trained on DEMO (simulated) data, NOT on real business data.")}</div>}

          <Sec title={L("1. Dữ liệu dùng để huấn luyện", "1. Training data")} open>
            <table className="tbl small"><tbody>
              <tr><td>{L("Nguồn / bộ dữ liệu", "Source / dataset")}</td><td>{tr.data_source} · <span className="mono">{tr.scope_key}</span> {fromRun}</td></tr>
              <tr><td>{L("Khoảng dữ liệu", "Data range")}</td><td>{fmtDate(tr.train_start)} → {fmtDate(tr.train_end)} · {L("mốc cắt dữ liệu (cutoff)", "data cutoff")}: <b>{fmtDate(tr.train_end)}</b> {L(`(tối đa ${fmtNum(c.max_train_days)} ngày gần nhất)`, `(at most the last ${fmtNum(c.max_train_days)} days)`)}</td></tr>
              <tr><td>{L("Số hàng huấn luyện", "Training rows")}</td><td><b>{fmtNum(tr.n_rows)}</b> {L("— mỗi hàng là một cặp (SKU×FC, ngày) có nhu cầu đã biết, từ ngày thứ 7 của dữ liệu và sau ngày chuỗi bắt đầu; tối đa 4 triệu hàng (giữ ngày gần nhất)", "— each row is one (SKU×FC, day) with a known demand, from the 7th data day on and after the series started; at most 4 million rows (latest days kept)")}</td></tr>
              <tr><td>{L("Số chuỗi / SKU / FC", "Series / SKUs / FCs")}</td><td>{fmtNum(tr.n_series)} / {d.artifact.n_sku == null ? L("không có dữ liệu để xác minh", "no data to verify") : fmtNum(d.artifact.n_sku)} / {d.artifact.n_fc == null ? "—" : fmtNum(d.artifact.n_fc)} <Src>{L("Nguồn: training run + file mô hình", "Source: training run + model file")}</Src></td></tr>
              <tr><td>{L("Mục tiêu (target) mô hình học", "Target the model learns")}</td><td>{L("Số lượng đặt hàng mỗi ngày của từng SKU×FC (tổng order_qty theo ngày lịch Việt Nam; không trừ hủy). Đơn vị: sản phẩm/ngày.", "Ordered quantity per day of each SKU×FC (sum of order_qty per Vietnam calendar day; cancellations not subtracted). Unit: units/day.")}</td></tr>
              <tr><td>{L("Xử lý dữ liệu", "Data handling")}</td><td>{L("Ngày có dữ liệu nhưng không có đơn = 0. Ngày toàn hệ thống không có đơn nào hoặc trước khi chuỗi bắt đầu = không rõ (NaN): không dùng làm target, không coi là 0. Dòng lỗi bị loại khi import; dòng trùng chỉ tính một lần.", "A known day without orders = 0. A day without any order in the whole system, or before the series started = unknown (NaN): never a target, never 0. Error rows are dropped at import; duplicates count once.")}</td></tr>
              <tr><td>{L("Thời gian huấn luyện", "Training time")}</td><td>{fmtTime(tr.started_at)} → {fmtTime(tr.finished_at)}</td></tr>
              <tr><td>{L("Dữ liệu đã đổi sau lần huấn luyện?", "Data changed since training?")}</td><td>{d.data_unchanged_since_training ? L("Không (dấu vân tay dữ liệu giống lúc huấn luyện)", "No (data fingerprint unchanged)") : L("Có — dữ liệu đã thay đổi", "Yes — data changed")}</td></tr>
              <tr data-testid="feature-set-version"><td>{t("feat.version")}</td><td><span className="mono">{d.feature_set?.version}</span> · {d.features.length} feature {!d.feature_set?.stored && <span className="muted">{t("feat.recomputed")}</span>}
                {d.feature_set?.decisions && <div className="small">{Object.entries(d.feature_set.decisions).map(([g, x]: [string, any]) => `${g}: ${x.used ? "✓" : `✗ ${x.reason}`}`).join(" · ")}</div>}</td></tr>
              {d.lineage && (
                <tr data-testid="lineage"><td>{t("feat.lineage")}</td><td className="small">
                  {d.lineage.source_ref?.table && <div>BigQuery: <span className="mono">{d.lineage.source_ref.table}</span> · {L("ánh xạ", "mapping")} <span className="mono">{d.lineage.source_ref.mapping_hash}</span> · {L("đọc từ", "read from")} {fmtDate(d.lineage.source_ref.history_start_date)}</div>}
                  {d.lineage.source_ref?.file_name && <div>{L("Lô dữ liệu", "Batch")}: <span className="mono">{d.lineage.source_ref.id}</span> · {d.lineage.source_ref.file_name} · {fmtNum(d.lineage.source_ref.valid_rows)}/{fmtNum(d.lineage.source_ref.total_rows)} {L("dòng hợp lệ", "valid rows")}</div>}
                  <div>Target: <span className="mono">{d.lineage.target_mapping?.field} ← {d.lineage.target_mapping?.column ?? "—"}</span> · {d.lineage.grain}</div>
                  <div>{L("Dữ liệu nhu cầu", "Demand data")}: {fmtNum(d.lineage.demand_daily?.rows)} {L("dòng SKU×FC×ngày", "SKU×FC×day rows")}, {fmtDate(d.lineage.demand_daily?.min_date)} → {fmtDate(d.lineage.demand_daily?.max_date)} · {L("lấy lúc", "fetched")} {fmtTime(d.lineage.fetched_at)}</div>
                </td></tr>
              )}
            </tbody></table>
          </Sec>

          <Sec title={L("2. Các nhóm trong mô hình", "2. Groups in the model")}>
            <ul className="small">
              <li><b>{L("Một mô hình LightGBM chung", "One shared LightGBM model")}</b> {L("cho mọi SKU×FC; KHÔNG có mô hình riêng cho từng SKU, FC hay nhóm sản phẩm. SKU và FC là hai feature dạng danh mục để mô hình học khác biệt giữa chúng.", "for every SKU×FC; there is NO separate model per SKU, FC or product group. SKU and FC are two categorical features so the model can learn their differences.")}</li>
              <li><b>{L("Nhóm phương pháp theo từng chuỗi", "Method group per series")}</b> {L("(quy tắc trước khi dự báo): LightGBM hoặc một phương pháp dự phòng. Ở lần dự báo đầu tiên của run này:", "(rule applied before forecasting): LightGBM or a fallback method. In this run's first forecast:")}{" "}
                {(d.method_counts ?? []).map((m: any, i: number) => <span key={m.method}>{i > 0 && " · "}<MethodLabel code={m.method} /> {fmtNum(m.n_series)}</span>)}</li>
              <li><b>{L("Nhóm feature", "Feature groups")}</b>: {L("định danh, lag, rolling, lịch, giá, khuyến mãi (xem Danh mục feature).", "identity, lag, rolling, calendar, price, promotion (see Feature catalogue).")}</li>
              <li><b>{L("Khoảng dự báo (horizon)", "Horizons")}</b>: {L("không có mô hình riêng cho 7/15/30 ngày; cùng một mô hình dự báo từng ngày nối tiếp (đệ quy).", "no separate model per 7/15/30 days; the same model forecasts day after day (recursively).")}</li>
              <li><b>{L("Nhóm báo cáo đánh giá", "Evaluation groups")}</b>: {L("chỉ số backtest gộp (dùng cho quality gate) và tách theo phương pháp (chỉ để đọc). Bộ lọc SKU/FC trên giao diện chỉ là lọc hiển thị.", "pooled backtest metrics (used by the quality gate) and split by method (information only). SKU/FC filters in the UI only filter the display.")}</li>
            </ul>
          </Sec>

          <Sec title={L("3. LightGBM học như thế nào (cấu hình thực tế)", "3. How LightGBM learns (actual configuration)")}>
            <ol className="small steps">
              <li>{L(`Mỗi hàng huấn luyện = feature của một SKU×FC tại một ngày (chỉ từ dữ liệu TRƯỚC ngày đó) + target là số lượng thật của ngày đó. Ma trận feature có ${d.features.length} cột.`, `Each training row = the features of one SKU×FC on one day (built only from data BEFORE that day) + the target, the real quantity of that day. The feature matrix has ${d.features.length} columns.`)}</li>
              <li>{L(`LightGBM xây lần lượt ${fmtNum(c.num_boost_round)} cây quyết định (mỗi cây tối đa ${fmtNum(c.num_leaves)} lá); mỗi cây mới học phần sai còn lại của các cây trước, nhân với tốc độ học ${p.learning_rate}. Điểm thô của một dòng = tổng giá trị lá của mọi cây.`, `LightGBM builds ${fmtNum(c.num_boost_round)} decision trees one after another (at most ${fmtNum(c.num_leaves)} leaves each); each new tree learns the remaining error of the previous ones, scaled by the learning rate ${p.learning_rate}. A row's raw score = the sum of its leaf values over all trees.`)}</li>
              <li>{L(`Objective: ${p.objective}${p.tweedie_variance_power ? ` (variance power ${p.tweedie_variance_power})` : ""}; hàm liên kết: ${d.link === "exp" ? "exp (dự báo = exp(điểm thô), luôn dương)" : "không có (dự báo = điểm thô)"}.`, `Objective: ${p.objective}${p.tweedie_variance_power ? ` (variance power ${p.tweedie_variance_power})` : ""}; link: ${d.link === "exp" ? "exp (forecast = exp(raw score), always positive)" : "none (forecast = raw score)"}.`)}</li>
              <li>{L("KHÔNG có tập validation riêng và KHÔNG dùng early stopping: số cây cố định. Chất lượng được đo bằng backtest walk-forward (mục 5), không phải bằng một tập validation.", "There is NO separate validation set and NO early stopping: the number of trees is fixed. Quality is measured by the walk-forward backtest (section 5), not by a validation set.")}</li>
              <li>{L("Dữ liệu chuỗi thời gian phải giữ thứ tự thời gian: feature của ngày t chỉ đọc các ngày trước t, backtest chỉ học dữ liệu trước mốc — để không 'nhìn trước' tương lai (rò rỉ dữ liệu).", "Time order is respected: day t's features only read days before t, and the backtest only learns data before its cutoff — so the future is never 'seen' (leakage).")}</li>
            </ol>
            <table className="tbl small mono" data-testid="training-params"><tbody>
              {Object.entries(p).map(([k, v]) => <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>)}
              <tr><td>num_boost_round</td><td>{c.num_boost_round}</td></tr>
            </tbody></table>
            <p className="small"><Src>{L("Nguồn: params_json + feature_config_json của training run", "Source: the training run's params_json + feature_config_json")}</Src></p>
            <table className="tbl small"><tbody>
              <tr><td>{L("File mô hình", "Model file")}</td><td className="mono">{d.artifact.file} · {d.artifact.model_version}</td></tr>
              <tr><td>sha256</td><td className="mono small">{d.artifact.sha256} · {d.artifact.exists ? (d.artifact.sha256_matches ? L("✓ khớp file hiện có", "✓ matches the file on disk") : L("✗ không khớp", "✗ mismatch")) : L("không tìm thấy file", "file not found")}</td></tr>
              <tr><td>{L("Số cây trong file", "Trees in the file")}</td><td>{d.artifact.n_trees == null ? L("không có dữ liệu để xác minh", "no data to verify") : fmtNum(d.artifact.n_trees)}</td></tr>
            </tbody></table>
            <p className="small">{L("Khi nào không huấn luyện / không publish:", "When nothing is trained / published:")} {(d.skip_fail_rules ?? []).map((r: any, i: number) => <span key={r.code}>{i > 0 && " · "}<Code code={r.code} /></span>)}</p>
          </Sec>

          <Sec title={L("4. Từ mô hình đến forecast", "4. From model to forecast")}>
            <ol className="small steps" data-testid="pipeline-steps">
              <li><b>{L("Kiểm tra dữ liệu", "Validate data")}</b> — {L("đủ lịch sử, không cũ (với nguồn bị kiểm tra); dữ liệu không đổi so với lần được chấp nhận gần nhất → bỏ qua (NO_NEW_DATA).", "enough history, not stale (for checked sources); data unchanged since the last accepted run → skipped (NO_NEW_DATA).")}</li>
              <li><b>{L("Chuẩn bị dữ liệu", "Prepare data")}</b> — {L("nhu cầu ngày → ma trận SKU×FC×ngày (ngày không rõ = NaN).", "daily demand → SKU×FC×day matrix (unknown days = NaN).")}</li>
              <li><b>Backtest walk-forward</b> — {L("đo chất lượng (mục 5).", "measure quality (section 5).")}</li>
              <li><b>{L("Huấn luyện", "Train")}</b> — {L("trên toàn bộ dữ liệu đến mốc cắt.", "on all data up to the cutoff.")}</li>
              <li><b>Quality gate</b> — {L("không đạt → không publish, giữ forecast hợp lệ trước đó.", "failed → nothing published, the previous valid forecast stays.")}</li>
              <li><b>{L("Chọn phương pháp từng chuỗi", "Pick a method per series")}</b> — {L("ngừng bán / chuỗi mới / gián đoạn → dự phòng; còn lại → LightGBM.", "inactive / new / intermittent → fallback; otherwise → LightGBM.")}</li>
              <li><b>{L("Dự báo", "Forecast")}</b> — {L("tạo feature ngày 1 → mô hình → exp(điểm thô) → cắt ≥ 0; dự báo ngày 1 được dùng làm 'lịch sử' cho ngày 2 (đệ quy)…", "build day-1 features → model → exp(raw score) → clip ≥ 0; day 1's forecast becomes 'history' for day 2 (recursion)…")}</li>
              <li><b>Publish</b> — {L("lưu mô hình (sha256) và forecast run bất biến, làm tròn 4 chữ số, trong một transaction.", "store the model (sha256) and an immutable forecast run, rounded to 4 decimals, in one transaction.")}
                {" "}{(d.forecast_runs ?? []).map((f: any) => <span key={f.id} className="mono small"> {f.id}{f.derived_from_run_id ? ` (← ${f.derived_from_run_id})` : ""}</span>)}</li>
            </ol>
          </Sec>

          <Sec title={L("5. Kiểm định mô hình (backtest walk-forward)", "5. Model validation (walk-forward backtest)")}>
            {!bt ? <p className="small muted">{L("Không có dữ liệu để xác minh.", "No data to verify.")}</p> : (
              <>
                <p className="small">{L(`Backtest ${bt.id}: ${bt.config?.folds} fold × ${bt.config?.horizon_days} ngày, bước ${bt.config?.step_days} ngày. Mỗi fold: cắt dữ liệu tại mốc → huấn luyện mô hình riêng chỉ với dữ liệu trước mốc → dự báo ${bt.config?.horizon_days} ngày → so với thực tế đã biết.`, `Backtest ${bt.id}: ${bt.config?.folds} folds × ${bt.config?.horizon_days} days, step ${bt.config?.step_days} days. Each fold: cut the data at the cutoff → train a separate model on data before it only → forecast ${bt.config?.horizon_days} days → compare with known actuals.`)}
                  {bt.config?.step_days < bt.config?.horizon_days && L(" Các fold chồng ngày nhau.", " Folds overlap in time.")}</p>
                <table className="tbl small" data-testid="training-folds">
                  <thead><tr><th>Fold</th><th>{L("Học đến trước", "Trained before")}</th><th>{L("Dự báo", "Forecast")}</th><th className="num">{L("Điểm", "Points")}</th><th className="num">WAPE</th><th className="num">Bias</th></tr></thead>
                  <tbody>{(bt.folds ?? []).map((f: any) => (
                    <tr key={f.fold}><td>{f.fold}</td><td>{fmtDate(f.origin)}</td><td>{fmtDate(f.origin)} → {fmtDate(f.end)}</td><td className="num">{fmtNum(f.metrics?.n_points)}</td>
                      <td className="num">{fmtPctX(f.metrics?.wape)}</td><td className="num">{fmtPctX(f.metrics?.bias, true)}</td></tr>
                  ))}</tbody>
                </table>
                {d.metrics && (
                  <p className="small" data-testid="training-metrics">{L("Gộp mọi fold", "All folds pooled")}: WAPE = Σ|A−F| ÷ ΣA = {fmtX((d.metrics.mae ?? 0) * (d.metrics.n_points ?? 0))} ÷ {fmtX(d.metrics.sum_actual)} = <b>{fmtPctX(d.metrics.wape)}</b> · Bias = (ΣF − ΣA) ÷ ΣA = <b>{fmtPctX(d.metrics.bias, true)}</b> {L("(dương = dự báo dư)", "(positive = over-forecast)")} · {fmtNum(d.metrics.n_points)} {L("điểm", "points")} · baseline WAPE {fmtPctX(d.baseline_metrics?.wape)}
                    {" "}· <a href={`/api/training-runs/${tr.id}/backtest-points.xlsx?lang=${lang}`}>{L("Tải các điểm backtest (Excel)", "Download backtest points (Excel)")}</a></p>
                )}
                {gate?.checks && (
                  <p className="small">Quality gate: <b>{gate.passed ? L("Đạt", "Passed") : L("Không đạt", "Failed")}</b> — {gate.checks.map((ch: any) => `${t(`perf.check.${ch.check}`)}: ${ch.passed ? "✓" : "✗"}`).join(" · ")}.
                    {!gate.thresholds_approved_by_business && <span className="warn-t"> {L("Ngưỡng chưa được nghiệp vụ phê duyệt.", "Thresholds not business-approved.")}</span>}
                    {" "}{L("Không đạt → mô hình mới không được publish; mô hình và forecast hợp lệ trước đó vẫn được dùng.", "Failed → the new model is not published; the previous valid model and forecast remain in use.")}</p>
                )}
              </>
            )}
          </Sec>
        </>
      )}
    </div>
  );
}

/** Every feature of the current model configuration, with its exact definition (backend ml/feature_catalog.py). */
export function FeatureCatalogue() {
  const { lang } = useI18n();
  const vi = lang === "vi";
  const cat = useAsync(() => get("/api/features/catalog"), []);
  if (!cat.data) return cat.error ? <ErrorBox error={cat.error} /> : <Loading />;
  if (!cat.data.features || !cat.data.roles) return <p className="muted">{vi ? "Không có dữ liệu để xác minh." : "No data to verify."}</p>;
  const groups = Object.keys(cat.data.roles);
  return (
    <div className="stack" data-testid="feature-catalogue">
      <p className="small muted">{vi
        ? "t = ngày dự báo. Mọi feature lag/rolling/giá/khuyến mãi chỉ đọc các ngày TRƯỚC ngày dự báo; feature lịch mô tả chính ngày dự báo. Trung bình/độ lệch chuẩn/tỷ lệ tính trên các ngày đã biết (mẫu số = số ngày có dữ liệu)."
        : "t = target day. Every lag/rolling/price/promotion feature only reads days BEFORE the target day; calendar features describe the target day itself. Means/std/shares are over known days (denominator = number of days with data)."}</p>
      {groups.filter((g) => cat.data.features.some((f: any) => f.group === g)).map((g) => (
        <div key={g}>
          <h4>{g} — {cat.data.roles[g][lang]}</h4>
          <table className="tbl small">
            <thead><tr><th>{vi ? "Feature" : "Feature"}</th><th>{vi ? "Cách tính" : "How it is computed"}</th><th>{vi ? "Đơn vị" : "Unit"}</th><th>{vi ? "Dữ liệu thiếu / 0" : "Missing / 0"}</th><th>{vi ? "Ý nghĩa" : "Meaning"}</th></tr></thead>
            <tbody>{cat.data.features.filter((f: any) => f.group === g).map((f: any) => (
              <tr key={f.name} id={`feature-${f.name}`}><td><b>{f[lang].name}</b><div className="mono muted">{f.name}</div></td><td>{f[lang].formula}</td><td>{f[lang].unit}</td><td>{f[lang].missing}</td><td>{f[lang].meaning}</td></tr>
            ))}</tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

export const _unused = fmtX;
