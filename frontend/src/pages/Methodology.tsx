import { Fragment, useEffect } from "react";
import { get } from "../api";
import { useI18n } from "../i18n";
import { GLOSSARY } from "../glossary";
import { ALGORITHMS, GROUPS, type AlgoItem } from "../algorithms";
import { Card, ErrorBox, PageHeader, fmtPct, useAsync, useMethods } from "../components/ui";
import { FeatureCatalogue, TrainingExplain } from "./TrainingExplain";

const LIMITS: { vi: string; en: string }[] = [
  { vi: "Không có dữ liệu tồn kho/hết hàng → mô hình dự báo nhu cầu đặt hàng, không điều chỉnh cho hết hàng.", en: "No stock/stock-out data → the model forecasts ordered demand, without stock-out correction." },
  { vi: "Không có lịch khuyến mãi tương lai → giả định không khuyến mãi trong khoảng dự báo; giá giữ ở mức đã biết gần nhất.", en: "No future promotion calendar → no promotion assumed over the forecast period; price held at the last known value." },
  { vi: "Mô hình không tự học từ sai số theo thời gian thực; nó chỉ được huấn luyện lại theo lịch hằng ngày (hoặc khi bấm chạy).", en: "The model does not learn from errors in real time; it is only retrained on the daily schedule (or on demand)." },
  { vi: "Dự báo đệ quy: sai số có thể tích lũy với khoảng dài (90–365 ngày) — hãy đọc kết quả dài hạn như xu hướng.", en: "Recursive forecasting: error can accumulate over long periods (90–365 days) — read long horizons as a trend." },
];

/** Live thresholds read from /api/settings, so the page never shows a value the code does not use. */
function thresholdRows(s: any, lang: "vi" | "en"): [string, string, string][] {
  const vi = lang === "vi";
  const m = s.model, q = s.quality, dp = s.data_policy, sc = s.schedule;
  const times = [...sc.d0_times].sort();
  let gap = 24 * 60;
  if (times.length > 1) {
    const mins = times.map((x: string) => Number(x.slice(0, 2)) * 60 + Number(x.slice(3, 5)));
    gap = Math.max(...mins.slice(1).map((v: number, i: number) => v - mins[i]));
  }
  return [
    [vi ? "Lịch sử tối thiểu để huấn luyện" : "Minimum history to train", "model.min_total_history_days", `${m.min_total_history_days} ${vi ? "ngày" : "days"}`],
    [vi ? "Lịch sử tối thiểu của một chuỗi (dưới mức này = Chuỗi mới)" : "Minimum series history (below = New series)", "model.min_series_history_days", `${m.min_series_history_days} ${vi ? "ngày" : "days"}`],
    [vi ? "Ngưỡng tỷ lệ ngày bằng 0 (Gián đoạn)" : "Zero-day share threshold (Intermittent)", "model.intermittent_zero_share", fmtPct(m.intermittent_zero_share, 0)],
    [vi ? "Cửa sổ trung bình dự phòng / cửa sổ tỷ lệ 0" : "Fallback mean window / zero-share window", "model.fallback_window_days", `${m.fallback_window_days} / ${m.fallback_window_days * 2} ${vi ? "ngày" : "days"}`],
    [vi ? "Số ngày không bán để coi là Ngừng bán" : "Days without sales for Inactive", "model.inactive_days", `${m.inactive_days} ${vi ? "ngày" : "days"}`],
    ["Backtest: folds × " + (vi ? "ngày" : "days") + " / " + (vi ? "bước" : "step"), "model.backtest_*", `${m.backtest_folds} × ${m.backtest_horizon_days} / ${m.backtest_step_days}`],
    ["LightGBM", "model.objective · num_boost_round · learning_rate · num_leaves", `${m.objective} · ${m.num_boost_round} · ${m.learning_rate} · ${m.num_leaves}`],
    [vi ? "Số ngày lịch sử tối đa dùng để huấn luyện" : "Maximum training history", "model.max_train_days", `${m.max_train_days} ${vi ? "ngày" : "days"}`],
    ["WAPE " + (vi ? "tối đa" : "max"), "quality.wape_max", fmtPct(q.wape_max, 0)],
    ["|Bias| " + (vi ? "tối đa" : "max"), "quality.abs_bias_max", fmtPct(q.abs_bias_max, 0)],
    [vi ? "Số điểm backtest tối thiểu" : "Minimum backtest points", "quality.min_backtest_points", String(q.min_backtest_points)],
    [vi ? "Bắt buộc tốt hơn baseline" : "Must beat the baseline", "quality.require_beat_baseline", q.require_beat_baseline ? (vi ? "Có" : "Yes") : (vi ? "Không" : "No")],
    [vi ? "MAPE chỉ tính khi thực tế ≥" : "MAPE only where actual ≥", "quality.mape_min_actual", String(q.mape_min_actual)],
    [vi ? "Ngưỡng đã được nghiệp vụ phê duyệt" : "Thresholds approved by business", "quality.approved_by_business", q.approved_by_business ? (vi ? "Có" : "Yes") : (vi ? "Chưa — giá trị ví dụ" : "No — example values")],
    [vi ? "Dữ liệu bị coi là cũ khi trễ hơn" : "Data is stale when older than", "data_policy.max_data_lag_days", `${dp.max_data_lag_days} ${vi ? "ngày" : "days"} (${dp.stale_check_sources.join(", ") || "—"})`],
    [vi ? "Mốc snapshot D0 (giờ VN)" : "D0 snapshot slots (VN time)", "schedule.d0_times", times.join(", ")],
    [vi ? "Giờ huấn luyện hằng ngày (giờ VN)" : "Daily training time (VN time)", "schedule.train_time", sc.train_time],
    [vi ? "Thử lại: chờ cơ sở / tối đa / số lần" : "Retry: base wait / max / attempts", "schedule.retry_base_seconds · retry_max_seconds · max_attempts", `${sc.retry_base_seconds} s / ${sc.retry_max_seconds} s / ${sc.max_attempts}`],
    [vi ? "Giới hạn thời gian một job" : "Job timeout", "schedule.timeout_seconds", `${sc.timeout_seconds} s`],
    [vi ? "'Thực tế hôm nay' có thể đã cũ sau" : "'Actual today' may be stale after", "max slot gap + schedule.slot_grace_minutes", `${gap} + ${sc.slot_grace_minutes} = ${gap + sc.slot_grace_minutes} ${vi ? "phút" : "min"}`],
  ];
}

function AlgoEntry({ a, lang }: { a: AlgoItem; lang: "vi" | "en" }) {
  const g = a[lang];
  const other = a[lang === "vi" ? "en" : "vi"];
  const vi = lang === "vi";
  return (
    <article id={a.id} className="gl algo">
      <h4>{g.name} <span className="muted small">/ {other.name}</span></h4>
      <p className="small"><code className="code">{a.code}</code></p>
      <dl>
        <dt>{vi ? "Mục đích" : "Purpose"}</dt><dd>{g.purpose}</dd>
        <dt>{vi ? "Đầu vào" : "Inputs"}</dt><dd>{g.inputs}</dd>
        <dt>{vi ? "Các bước" : "Steps"}</dt><dd><ol className="steps">{g.steps.map((s, i) => <li key={i}>{s}</li>)}</ol></dd>
        {g.formula && <><dt>{vi ? "Công thức" : "Formula"}</dt><dd><span className="formula">{g.formula}</span></dd></>}
        {g.example && <><dt>{vi ? "Ví dụ" : "Example"}</dt><dd>{g.example}</dd></>}
        <dt>{vi ? "Ý nghĩa nghiệp vụ" : "Business meaning"}</dt><dd>{g.meaning}</dd>
        <dt>{vi ? "Giới hạn" : "Limitations"}</dt><dd>{g.limits}</dd>
        {a.related.length > 0 && (<><dt>{vi ? "Liên quan" : "Related"}</dt><dd>{a.related.map((r, i) => (
          <Fragment key={r}>{i > 0 && " · "}<a href={`#${r}`}>{ALGORITHMS.find((x) => x.id === r)?.[lang].name ?? r}</a></Fragment>
        ))}</dd></>)}
      </dl>
    </article>
  );
}

function MethodEntry({ m, lang }: { m: any; lang: "vi" | "en" }) {
  const d = m[lang];
  const other = m[lang === "vi" ? "en" : "vi"];
  const vi = lang === "vi";
  return (
    <article id={m.anchor} className="gl algo" data-testid={`doc-${m.anchor}`}>
      <h4>{d.name} <span className="muted small">/ {other.name}</span></h4>
      <p className="small"><code className="code">{m.code}</code>{m.scope !== "production" && <span className="pill muted">{vi ? "Chỉ dùng trong backtest — không có trong forecast đã publish" : "Backtest only — never in a published forecast"}</span>}</p>
      <dl>
        <dt>{vi ? "Tóm tắt" : "Summary"}</dt><dd>{d.short}</dd>
        <dt>{vi ? "Ý nghĩa" : "Meaning"}</dt><dd>{d.meaning}</dd>
        <dt>{vi ? "Khi nào được dùng" : "When it is used"}</dt><dd>{d.when}</dd>
        <dt>{vi ? "Cách tính" : "How it is computed"}</dt><dd>{d.how}</dd>
        {d.example && <><dt>{vi ? "Ví dụ" : "Example"}</dt><dd>{d.example}</dd></>}
        {d.read && <><dt>{vi ? "Cách đọc kết quả" : "How to read it"}</dt><dd>{d.read}</dd></>}
        <dt>{vi ? "Giới hạn" : "Limitations"}</dt><dd>{d.limits}</dd>
        <dt>{vi ? "Liên quan" : "Related"}</dt><dd><a href="#algo-method-selection">{ALGORITHMS.find((x) => x.id === "algo-method-selection")![lang].name}</a></dd>
      </dl>
    </article>
  );
}

export default function Methodology() {
  const { t, lang } = useI18n();
  const vi = lang === "vi";
  const reg = useMethods();
  const settings = useAsync(() => get("/api/settings"), []);
  const methods = reg?.methods ? Object.values(reg.methods).sort((a: any, b: any) => (a.scope === b.scope ? 0 : a.scope === "production" ? -1 : 1)) : [];
  // anchors may only exist after the registry / settings have loaded -> scroll once they are rendered
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) document.getElementById(id)?.scrollIntoView({ block: "start" });
  }, [reg, settings.data]);
  return (
    <div className="stack methodology">
      <PageHeader icon="methodology" title={t("nav.methodology")} desc={vi
        ? "Mô tả các thuật toán thật sự đang chạy trong ứng dụng, theo đúng code hiện hành. Ngưỡng hiển thị được đọc trực tiếp từ cấu hình; ví dụ số được kiểm tra bằng test tự động."
        : "Describes the algorithms actually running in the app, as implemented. Thresholds are read live from configuration; numeric examples are verified by automated tests."} />
      <Card icon="methodology" title={vi ? "Mục lục" : "Contents"}>
        <nav className="toc" aria-label={vi ? "Mục lục" : "Contents"}>
          <ol>
            {GROUPS.map((g) => (
              <li key={g.id}><a href={`#group-${g.id}`}>{g[lang]}</a>
                <ul>
                  {ALGORITHMS.filter((a) => a.group === g.id).map((a) => <li key={a.id}><a href={`#${a.id}`}>{a[lang].name}</a></li>)}
                  {g.id === "methods" && methods.map((m: any) => <li key={m.anchor}><a href={`#${m.anchor}`}>{m[lang].name}</a></li>)}
                </ul>
              </li>
            ))}
            <li><a href="#training">{vi ? "Mô hình được huấn luyện như thế nào?" : "How was the model trained?"}</a></li>
            <li><a href="#feature-catalogue">{vi ? "Danh mục feature" : "Feature catalogue"}</a></li>
            <li><a href="#thresholds">{vi ? "Ngưỡng hiện hành" : "Current thresholds"}</a></li>
            <li><a href="#limits">{vi ? "Giới hạn hiện tại" : "Current limitations"}</a></li>
            <li><a href="#glossary">{vi ? "Giải thích thuật ngữ" : "Glossary"}</a></li>
          </ol>
        </nav>
      </Card>
      {GROUPS.map((g) => (
        <section key={g.id} id={`group-${g.id}`}>
          <Card title={g[lang]}>
            <div className="glossary">
              {ALGORITHMS.filter((a) => a.group === g.id).map((a) => <AlgoEntry key={a.id} a={a} lang={lang} />)}
              {g.id === "methods" && methods.map((m: any) => <MethodEntry key={m.anchor} m={m} lang={lang} />)}
            </div>
          </Card>
        </section>
      ))}
      <section id="training">
        <Card title={vi ? "Mô hình được huấn luyện như thế nào?" : "How was the model trained?"}>
          <TrainingExplain />
        </Card>
      </section>
      <section id="feature-catalogue">
        <Card title={vi ? "Danh mục feature (lấy từ mã nguồn)" : "Feature catalogue (from the code)"}>
          <FeatureCatalogue />
        </Card>
      </section>
      <section id="thresholds">
        <Card title={vi ? "Ngưỡng hiện hành (đọc từ Cấu hình)" : "Current thresholds (from Configuration)"}>
          <ErrorBox error={settings.error} />
          {settings.data && (
            <table className="tbl small">
              <thead><tr><th>{vi ? "Ngưỡng" : "Threshold"}</th><th>{vi ? "Tên cấu hình" : "Setting"}</th><th>{vi ? "Giá trị" : "Value"}</th></tr></thead>
              <tbody>{thresholdRows(settings.data, lang).map(([l, k, v]) => <tr key={k}><td>{l}</td><td className="mono">{k}</td><td><b>{v}</b></td></tr>)}</tbody>
            </table>
          )}
        </Card>
      </section>
      <section id="limits">
        <Card title={vi ? "Giới hạn hiện tại" : "Current limitations"}>
          <ul>{LIMITS.map((s, i) => <li key={i}>{s[lang]}</li>)}</ul>
        </Card>
      </section>
      <section id="glossary">
        <Card title={vi ? "Giải thích thuật ngữ" : "Glossary"}>
          <div className="glossary">
            {GLOSSARY.map((term) => {
              const g = term[lang];
              const other = term[lang === "vi" ? "en" : "vi"];
              return (
                <article key={term.id} id={term.id} className="gl">
                  <h4>{g.name} <span className="muted small">/ {other.name}</span></h4>
                  <dl>
                    <dt>{vi ? "Ý nghĩa" : "Meaning"}</dt><dd>{g.meaning}</dd>
                    <dt>{vi ? "Mục đích" : "Purpose"}</dt><dd>{g.purpose}</dd>
                    <dt>{vi ? "Ví dụ" : "Example"}</dt><dd>{g.example}</dd>
                    {g.read && (<><dt>{vi ? "Cách đọc" : "How to read"}</dt><dd>{g.read}</dd></>)}
                  </dl>
                </article>
              );
            })}
          </div>
        </Card>
      </section>
    </div>
  );
}
