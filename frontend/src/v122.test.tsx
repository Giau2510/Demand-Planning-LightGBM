import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { I18nProvider } from "./i18n";
import Config from "./pages/Config";
import Performance from "./pages/Performance";
import Results from "./pages/Results";

// 1.2.2 (P0 17/10/2026): BigQuery is the source shown everywhere; an old DEMO run is never the default; a result below
// the quality thresholds is shown as usable WITH a warning (never hidden, never "good").
const wrap = (el: React.ReactNode, path = "/") => <I18nProvider><MemoryRouter initialEntries={[path]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); });

type Call = { url: string; method: string; body: any };
function mock(route: (u: string, c: Call) => any) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const v = route(u, c);
    return new Response(JSON.stringify(v === undefined ? {} : v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const WARN_ASSESSMENT = {
  policy: "PUBLISH_WITH_WARNING", candidate: "LIGHTGBM", technical: { status: "OK", failed_checks: [] },
  quality: { status: "BELOW_THRESHOLD", failed_checks: ["WAPE_MAX"], checks: [
    { check: "WAPE_MAX", passed: false, value: 0.8074, threshold: 0.6 }, { check: "ABS_BIAS_MAX", passed: true, value: 0.0575, threshold: 0.2 }] },
  confidence: { level: "NORMAL", reasons: [] }, usage: { status: "USABLE_WITH_WARNING", reason: "BELOW_THRESHOLD" },
  selection: { rule: "LOWEST_POOLED_WAPE_ON_SAME_BACKTEST_POINTS", chosen: "LIGHTGBM", reason: "LIGHTGBM_LOWER_OR_EQUAL_WAPE",
    candidates: { LIGHTGBM: { available: true, metrics: { wape: 0.8074, bias: 0.0575, n_points: 3351605 } },
      BASELINE_MOVING_AVERAGE: { available: true, metrics: { wape: 0.8436, bias: 0.1244, n_points: 3351605 } } },
    rejected: [{ candidate: "BASELINE_MOVING_AVERAGE", reason: "NOT_LOWER_WAPE" }] },
};
const BQ = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm";
const run = (id: string, src: string, active: boolean, created: string, extra: any = {}) => ({
  id, created_at: created, data_source: src, scope_key: src === "BIGQUERY" ? BQ : "DEMO-20261016073211-24EC73", model_version: `MV-${id}`,
  horizons: [7, 15], max_horizon: 15, forecast_origin: "2026-10-17", data_as_of: "2026-10-16", active_scope: active,
  skus: [], fcs: [], horizon_coverage: { run_horizons: [7, 15], max_horizon: 15, configured: [7, 15], configured_missing_in_run: [], can_extend_without_retraining: false, cannot_extend_reason: null },
  ...extra });
const summary = { n_series: 0, grand_total: 0, start_date: "2026-10-17", end_date: "2026-10-23", series: [], daily: [], actual: null };

describe("v1.2.2 results page", () => {
  it("opens on the newest BIGQUERY run even when an old DEMO run is newer, with the quality warning", async () => {
    const demo = run("FCR-DEMO", "DEMO", false, "2026-10-17T11:00:00Z");
    const bq = run("FCR-BQ", "BIGQUERY", true, "2026-10-17T10:40:00Z", { assessment: WARN_ASSESSMENT,
      lineage: { data_source: "BIGQUERY", table: "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm", train_start: "2026-01-01", train_end: "2026-10-16",
        last_sync: { synced_at: "2026-10-17T01:28:31+00:00" } } });
    const calls = mock((u) => u.startsWith("/api/forecast-runs?") ? [{ ...demo }, { ...bq, assessment: { usage: "USABLE_WITH_WARNING" } }]
      : u.startsWith("/api/forecast-runs/FCR-BQ/summary") ? summary : u.startsWith("/api/forecast-runs/FCR-BQ/accuracy") ? null
      : u.startsWith("/api/forecast-runs/FCR-BQ") ? bq : u.startsWith("/api/forecast-runs/FCR-DEMO") ? demo : u.startsWith("/api/jobs/active") ? null : {});
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect((screen.getByTestId("run-select") as HTMLSelectElement).value).toBe("FCR-BQ"));
    expect(calls.some((c) => c.url.startsWith("/api/forecast-runs/FCR-DEMO"))).toBe(false);
    const opts = [...(screen.getByTestId("run-select") as HTMLSelectElement).options].map((o) => o.textContent ?? "");
    expect(opts[0]).toContain("DEMO (nguồn khác)");
    expect(opts[1]).toContain("⚠ dưới ngưỡng");
    const box = (await screen.findByTestId("assessment")).textContent ?? "";
    expect(box).toContain("Được dùng — kèm cảnh báo");
    expect(box).toContain("Dưới ngưỡng");
    expect(box).toContain("WAPE ≤ ngưỡng: 80,7% / 60%");                    // value / threshold
    expect(box).toContain("KHÔNG phải kết quả đạt chuẩn");
    expect(within(screen.getByTestId("as-candidates")).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByTestId("lineage").textContent).toContain("lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm");
    expect(screen.queryByTestId("no-run-active")).toBeNull();
  });

  it("never selects a run of another source by itself and says that no BIGQUERY forecast exists", async () => {
    const demo = run("FCR-DEMO", "DEMO", false, "2026-10-16T07:32:46Z");
    const calls = mock((u) => u.startsWith("/api/forecast-runs?") ? [demo] : u.startsWith("/api/jobs/active") ? null : {});
    await act(async () => { render(wrap(<Results />)); });
    expect((await screen.findByTestId("no-run-active")).textContent).toContain("Chưa có forecast nào từ nguồn dữ liệu đang dùng");
    expect((screen.getByTestId("run-select") as HTMLSelectElement).value).toBe("");
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(calls.some((c) => c.url.startsWith("/api/forecast-runs/FCR-DEMO"))).toBe(false);
  });
});

const STATUS = {
  version: "1.2.2", active_source: "BIGQUERY", scope: { scope_key: BQ, data_source: "BIGQUERY", label: "lakehouse" }, scope_error: null,
  bigquery_production_enabled: true, alerts: [], latest_jobs: {}, scheduler: { running: true, flows: {} }, latest_forecast_run: null,
  freshness: { max_date: "2026-10-16", lag_days: 1, stale: false }, data_window: { start: "2026-01-01", end: "2026-10-16" },
  forecast_state: { status: "NO_FORECAST_FOR_ACTIVE_SOURCE", data_source: "BIGQUERY", model_in_use: null, other_source_runs: 4,
    latest_attempt: { id: "TRN-20261017101340-EEDA47", status: "REJECTED", reject_reason: "QUALITY_GATE_FAILED", promotable: { ok: true, kind: "BELOW_THRESHOLD" } } },
};

describe("v1.2.2 dashboard and snapshots follow the active source", () => {
  it("dashboard explains that BIGQUERY has no forecast yet and never shows the DEMO runs as current", async () => {
    mock((u) => u.startsWith("/api/system/status") ? STATUS : u.startsWith("/api/dashboard") ? { system: STATUS, forecast: null }
      : u.startsWith("/api/settings") ? { horizons: { enabled: [7, 15] } } : u.startsWith("/api/jobs/active") ? null : {});
    await act(async () => { render(wrap(<App />)); });
    const box = (await screen.findByTestId("dash-no-forecast")).textContent ?? "";
    expect(box).toContain("Chưa có forecast từ nguồn BIGQUERY.");
    expect(box).toContain("TRN-20261017101340-EEDA47");
    expect(box).toContain("Dùng model này");
    expect(box).toContain("4 lần forecast của nguồn khác");
  });

  it("D-0 snapshot history opens on the BIGQUERY source and says when it has none", async () => {
    const calls = mock((u) => u.startsWith("/api/system/status") ? STATUS : u.startsWith("/api/snapshots") ? [] : {});
    await act(async () => { render(wrap(<App />, "/snapshots")); });
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/api/snapshots") && c.url.includes("data_source=BIGQUERY"))).toBe(true));
    expect((screen.getByTestId("snap-source") as HTMLSelectElement).value).toBe("BIGQUERY");
    expect(await screen.findByText(/Chưa có snapshot D-0 nào của nguồn BIGQUERY/)).toBeTruthy();
  });
});

describe("v1.2.2 model performance and settings", () => {
  it("a run below the thresholds can be put in use with an explicit warning; no exception form is needed", async () => {
    const tr = { id: "TRN-1", status: "REJECTED", reject_reason: "QUALITY_GATE_FAILED", data_source: "BIGQUERY", started_at: "2026-10-17T10:13:40Z",
      model_version: "MV-1", metrics: { wape: 0.8074, bias: 0.0575 }, assessment: { usage: "USABLE_WITH_WARNING" } };
    const det = { ...tr, quality_gate: { passed: false, checks: WARN_ASSESSMENT.quality.checks }, can_promote: true,
      promotable: { ok: true, kind: "BELOW_THRESHOLD" }, gate_exception: { eligible: true }, assessment: WARN_ASSESSMENT, in_use: false };
    const calls = mock((u, c) => c.method === "POST" ? { status: "PUBLISHED", forecast_run_id: "FCR-NEW" }
      : u.startsWith("/api/training-runs/TRN-1") ? det : u.startsWith("/api/training-runs") ? [tr] : {});
    await act(async () => { render(wrap(<Performance />)); });
    const btn = await screen.findByTestId("promote");
    expect(btn.textContent).toBe("Dùng model này (dưới ngưỡng — kèm cảnh báo)");
    expect(screen.queryByTestId("exc-release")).toBeNull();
    expect(screen.getByTestId("assessment").textContent).toContain("Được dùng — kèm cảnh báo");
    fireEvent.click(btn);
    expect((window.confirm as any).mock.calls[0][0]).toContain("CHƯA đạt ngưỡng chất lượng");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/training-runs/TRN-1/promote")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ confirm: true });
  });

  it("the policy below the thresholds is a visible, saved quality setting", async () => {
    const quality = { wape_max: 0.6, abs_bias_max: 0.2, min_backtest_points: 200, require_beat_baseline: false, mape_min_actual: 1,
      approved_by_business: false, below_threshold_policy: "PUBLISH_WITH_WARNING" };
    const calls = mock((u, c) => c.method === "PUT" ? c.body : u.startsWith("/api/settings") ? { quality, horizons: { enabled: [7], choices: [7], max_allowed_days: 365 },
      model: { feature_lags: true, feature_rolling: true, feature_price: true, forecast_strategy: "DIRECT" } } : {});
    await act(async () => { render(wrap(<Config />)); });
    const sel = (await screen.findByTestId("below-policy")) as HTMLSelectElement;
    expect(sel.value).toBe("PUBLISH_WITH_WARNING");
    fireEvent.change(sel, { target: { value: "BLOCK" } });
    fireEvent.click(within(sel.closest("section")!).getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url === "/api/settings/quality")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body.below_threshold_policy).toBe("BLOCK");
    expect(put.body.wape_max).toBe(0.6);                           // the thresholds themselves are not touched
  });
});
