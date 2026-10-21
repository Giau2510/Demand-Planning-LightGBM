import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider, useI18n } from "./i18n";
import { fmtPctX, fmtX, weekdayName } from "./components/ui";
import ExplainPanel from "./pages/ExplainPanel";
import { TrainingExplain } from "./pages/TrainingExplain";

const REGISTRY = JSON.parse(readFileSync(join(__dirname, "test-fixtures", "methods.json"), "utf8"));
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

function Vi({ children }: { children: () => React.ReactNode }) {
  const { lang, setLang } = useI18n();
  if (lang !== "vi") { setLang("vi"); return null; }
  return <>{children()}</>;
}

describe("B. explanation numbers: at most 2 decimals, sign and magnitude kept", () => {
  it("formats positive, negative, zero, small, integer and percent values", () => {
    render(wrap(<Vi>{() => <span data-testid="n">{[fmtX(1.9888), fmtX(-0.0999), fmtX(1.8889), fmtX(6.612353), fmtX(7.2), fmtX(10), fmtX(0.5),
      fmtX(0), fmtX(0.003), fmtX(-0.003), fmtX(0.003, true), fmtX(0.1234, true), fmtX(2072), fmtX(1234.567), fmtPctX(0.192), fmtPctX(0.015, true), fmtPctX(-0.0676, true)].join("|")}</span>}</Vi>));
    expect(screen.getByTestId("n").textContent).toBe("1,99|-0,1|1,89|6,61|7,2|10|0,5|0|<0,01|-<0,01|+<0,01|+0,12|2.072|1.234,57|19,2%|+1,5%|-6,76%");
  });
  it("weekday comes from the calendar date itself", () => {
    // 1.2.12: the application's one Vietnamese form "Thứ 2" ... "Chủ nhật" (was "Thứ Tư" / "Chủ Nhật" here)
    expect(weekdayName("2026-10-14", "vi")).toBe("Thứ 4");
    expect(weekdayName("2026-10-18", "vi")).toBe("Chủ nhật");
    expect(weekdayName("2026-10-19", "en")).toBe("Monday");
  });
});

// one LightGBM row: base 1.9888, contributions summing to -0.0999 -> raw 1.8889 -> exp -> 6.6121 published
const contribs: [string, number, number | null, string][] = [
  ["roll_mean_7", 0.21, 6.5, "UP"], ["lag_1", -0.18, 3, "DOWN"], ["dow", -0.12, 6, "DOWN"], ["lag_7", 0.05, 8, "UP"],
  ["roll_mean_28", -0.04, 6.1, "DOWN"], ["zero_share_28", -0.0099, 0.1, "NEGLIGIBLE"], ["series_age", 0.002, 300, "NEGLIGIBLE"],
  ["price_last", -0.003, null, "NEGLIGIBLE"], ["lag_2", -0.009, 5, "DOWN"]];   // sums to -0.0999
const sum = contribs.reduce((a, c) => a + c[1], 0);
const lgEx = {
  identity: { run_id: "FCR-1", model_version: "MV-1", data_source: "DEMO", scope_key: "DEMO-1", target_date: "2026-10-14", horizon_day: 1,
    data_as_of: "2026-10-13", run_created_at: "2026-10-14T08:06:21Z", training_run_id: "TRN-1" },
  result: { method: "LIGHTGBM", yhat: 6.6121 },
  selection: { source: "STORED", reason_code: "LIGHTGBM_ELIGIBLE", series_start_date: "2025-12-18", age_days: 300, zero_share: 0.1, zero_days: 5,
    zero_known_days: 50, recent_sum: 400, fallback_window: { days: 28 }, rule: { min_series_history_days: 28, zero_share_window_days: 56, intermittent_zero_share: 0.8, inactive_days: 60 } },
  history: { status: "OK", window_start: "2026-10-12", window_end: "2026-10-13", window_days: 2,
    days: [{ date: "2026-10-12", weekday: 0, qty: 5, status: "ORDERS", in_calc: true, used_by: ["lag_2", "roll_mean_7", "days_since_last_sale"] },
      { date: "2026-10-13", weekday: 1, qty: 3, status: "ORDERS", in_calc: true, used_by: ["lag_1", "roll_mean_7", "days_since_last_sale"] }],
    summary: { ORDERS: 2, ZERO_ORDERS: 0, NO_DATA: 0, BEFORE_START: 0, total_qty: 8 },
    calc: { kind: "LIGHTGBM_FEATURE_WINDOWS", from: "2026-10-12", to: "2026-10-13", known_days: 2, sum: 8, recursive_days: 0, last_sale_window_days: 180 } },
  lightgbm: { status: "OK", objective: "tweedie", link: "exp", bias: 1.9888, contrib_sum: sum, raw_score: 1.9888 + sum, model_output: Math.exp(1.9888 + sum),
    model_output_matches_link: true, clipped: Math.exp(1.9888 + sum), clip_applied: false, n_features: contribs.length, n_features_used_in_trees: contribs.length,
    attribution_method: "TREE_SHAP (LightGBM predict(pred_contrib=True))", prediction_before_clip: Math.exp(1.9888 + sum), reproduced_yhat: 6.6121,
    published_yhat: 6.6121, matches_published: true, n_trees: 300, recursive_step: 1, uses_forecast_inputs: false,
    features: contribs.map(([name, c, v, eff]) => ({ name, value: v, contribution: c, effect: eff, source: "ACTUAL", used_in_trees: true, missing: v === null,
      group: "ROLLING", window: { from: "2026-10-07", to: "2026-10-13" }, includes_target_day: false,
      catalog: { vi: { name: `TÊN ${name}`, formula: `CÔNG THỨC ${name}`, meaning: "ý nghĩa", unit: "đv", missing: "thiếu" }, en: { name, formula: "f", meaning: "m", unit: "u", missing: "x" } } })),
    global_importance: [{ feature: "lag_1", gain: 10 }] },
  quality: { training_status: "ACCEPTED", backtest_id: "BT-1", backtest_config: { horizon_days: 14, folds: 3, step_days: 7 }, folds_overlap: true,
    backtest_folds: [{ fold: 1, origin: "2026-08-20", end: "2026-09-02", train_days: 300, n_points: 1176 }],
    quality_gate: { passed: true, thresholds_approved_by_business: false, checks: [
      { check: "BACKTEST_RELIABLE", passed: true, value: 3, threshold: null }, { check: "MIN_BACKTEST_POINTS", passed: true, value: 3528, threshold: 200 },
      { check: "WAPE_MAX", passed: true, value: 0.192, threshold: 0.6 }, { check: "ABS_BIAS_MAX", passed: true, value: 0.015, threshold: 0.2 }] },
    backtest_this_method: { n_points: 2072, wape: 0.192, bias: 0.015, sum_actual: 10000, sum_forecast: 10150, sum_abs_error: 1920, mae: 1920 / 2072 } },
  notes: [],
};

describe("A. LightGBM calculation shown step by step", () => {
  it("base value, contributions, sum, raw score, exp and published value chain; summary and full feature table", async () => {
    globalThis.fetch = vi.fn(async (url: any) => new Response(JSON.stringify(String(url).startsWith("/api/methods") ? REGISTRY : lgEx),
      { status: 200, headers: { "content-type": "application/json" } })) as any;
    await act(async () => { render(wrap(<ExplainPanel runId="FCR-1" sku="A" fc="F" date="2026-10-14" maxHorizon={7} origin="2026-10-14" onClose={() => {}} />)); });
    await waitFor(() => expect(screen.getByTestId("lgb-steps")).toBeTruthy());
    const steps = screen.getByTestId("lgb-steps").textContent ?? "";
    expect(steps).toContain("Giá trị nền (base value) = 1,99");
    expect(steps).toContain("Tổng đóng góp = -0,1");
    expect(steps).toContain("Điểm thô (raw score) = 1,99 − 0,1 = 1,89");
    expect(steps).toContain("exp(1,89) = 6,61");
    expect(steps).toContain("Forecast đã publish = 6,61");
    expect(steps).toContain(`Mô hình dùng ${contribs.length} feature`);
    // summary: at most 8 rows split into raise / lower; negligible contributions keep their sign
    const top = [...document.querySelectorAll("[data-testid=features-top] tbody tr")];
    expect(top.length).toBeLessThanOrEqual(8);
    expect(top.map((r) => r.getAttribute("data-feature"))).toContain("roll_mean_7");
    expect(steps).not.toMatch(/\d,\d{3,}/);                                // never more than 2 decimals in the steps
    fireEvent.click(screen.getByTestId("toggle-all-features"));
    const all = [...document.querySelectorAll("[data-testid=features-all] tbody tr")];
    expect(all.length).toBe(contribs.length);
    const pl = all.find((r) => r.getAttribute("data-feature") === "price_last")!.textContent ?? "";
    expect(pl).toContain("-<0,01");                                        // tiny negative contribution: sign kept, not "0"
    expect(pl).toContain("thiếu (NaN)");                                   // missing input value, not 0
    expect(pl).toContain("CÔNG THỨC price_last");
    // technical level keeps full precision
    expect(screen.getByTestId("tech-table").textContent).toContain(String(1.9888 + sum));
  });

  it("quality: WAPE / Bias with their own sums, points definition, gate thresholds, not-approved warning", async () => {
    globalThis.fetch = vi.fn(async (url: any) => new Response(JSON.stringify(String(url).startsWith("/api/methods") ? REGISTRY : lgEx),
      { status: 200, headers: { "content-type": "application/json" } })) as any;
    await act(async () => { render(wrap(<ExplainPanel runId="FCR-1" sku="A" fc="F" date="2026-10-14" maxHorizon={7} origin="2026-10-14" onClose={() => {}} />)); });
    await waitFor(() => expect(screen.getByTestId("quality-metrics")).toBeTruthy());
    const m = screen.getByTestId("quality-metrics").textContent ?? "";
    expect(m).toContain("= 1.920 ÷ 10.000 = 19,2%");
    expect(m).toContain("(10.150 − 10.000) ÷ 10.000 = +1,5%");
    expect(m).toContain("CAO hơn tổng thực tế 1,5%");
    expect(m).toContain("2.072");
    expect(m).toContain("Không phải 2.072 ngày");
    expect(m).toContain("đếm 2 lần");
    expect(screen.getByTestId("gate-table").textContent).toContain("≤ 60%");
    expect(screen.getByTestId("gate-not-approved")).toBeTruthy();
    expect(screen.getByTestId("backtest-xlsx").getAttribute("href")).toBe("/api/training-runs/TRN-1/backtest-points.xlsx?lang=vi");
    const hist = screen.getByTestId("history-xlsx").getAttribute("href") ?? "";
    expect(hist).toContain("/api/forecast-runs/FCR-1/explain/history.xlsx");
    expect(hist).toContain("target_date=2026-10-14");
    const wd = [...document.querySelectorAll("[data-testid=history-table] tbody tr")].map((tr) => tr.querySelectorAll("td")[1].textContent);
    expect(wd).toEqual(["Thứ 2", "Thứ 3"]);
  });
});

describe("E. training explanation", () => {
  const ov = {
    active: { active_source: "MANUAL_IMPORT", scope_key: null, has_dataset: false, reason_code: "NO_ACTIVE_DATASET" },
    runs: [{ id: "TRN-1", status: "ACCEPTED", data_source: "DEMO", scope_key: "DEMO-1", started_at: "2026-10-14T08:06:06Z" }],
    training_run: { id: "TRN-1", status: "ACCEPTED", data_source: "DEMO", scope_key: "DEMO-1", started_at: "2026-10-14T08:06:06Z", finished_at: "2026-10-14T08:06:21Z",
      train_start: "2024-10-14", train_end: "2026-10-13", n_series: 84, n_rows: 58000, reject_reason: null },
    data_unchanged_since_training: true, link: "exp", early_stopping: false, validation_set: false,
    config: { num_boost_round: 300, num_leaves: 31, max_train_days: 730 }, params: { objective: "tweedie", tweedie_variance_power: 1.2, learning_rate: 0.05 },
    features: [{ name: "lag_1", group: "LAG" }], artifact: { file: "MV-1.txt", model_version: "MV-1", sha256: "ab", exists: true, sha256_matches: true, n_trees: 300, n_sku: 28, n_fc: 3 },
    quality_gate: { passed: true, thresholds_approved_by_business: false, checks: [] }, metrics: { n_points: 3528, wape: 0.2, bias: 0.01, mae: 1, sum_actual: 100 },
    baseline_metrics: { wape: 0.3 }, forecast_runs: [{ id: "FCR-1", horizons: [7] }], method_counts: [{ method: "LIGHTGBM", n_series: 60 }],
    skip_fail_rules: [{ code: "NO_NEW_DATA", result: "SKIPPED" }], backtest: { id: "BT-1", config: { folds: 3, horizon_days: 14, step_days: 7 }, folds: [] },
  };
  it("says the active source cannot be trained yet, labels the DEMO model, shows real parameters and no early stopping", async () => {
    globalThis.fetch = vi.fn(async (url: any) => new Response(JSON.stringify(String(url).startsWith("/api/methods") ? REGISTRY : ov),
      { status: 200, headers: { "content-type": "application/json" } })) as any;
    await act(async () => { render(wrap(<TrainingExplain />)); });
    await waitFor(() => expect(screen.getByTestId("training-explain")).toBeTruthy());
    expect(screen.getByTestId("no-dataset").textContent).toContain("MANUAL_IMPORT");
    expect(screen.getByTestId("demo-model").textContent).toContain("DEMO");
    const txt = screen.getByTestId("training-explain").textContent ?? "";
    expect(txt).toContain("58.000");
    expect(txt).toContain("13/10/2026");
    expect(txt).toContain("KHÔNG dùng early stopping");
    expect(txt).toContain("Một mô hình LightGBM chung");
    expect(screen.getByTestId("training-params").textContent).toContain("tweedie_variance_power1.2");
  });
});
