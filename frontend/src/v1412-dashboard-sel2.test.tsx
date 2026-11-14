import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";

// 1.4.12 (unit, fetch mocked): with a published SEL2 run the Dashboard forecast block shows the numbers of
// /api/daily-forecast/sel2-summary (forecast_used of the daily Excel), without the legacy banner; without a SEL2 run
// the legacy 1.3.x summary and the banner stay as before.

const status = {
  version: "1.4.12", active_source: "BIGQUERY", scope: { label: "BQ test" }, alerts: [], latest_jobs: {}, scheduler: { running: true },
  freshness: { max_date: "2026-11-13", lag_days: 1 },
  latest_forecast_run: { id: "FCR-LEGACY", model_version: "MV-LEGACY", created_at: "2026-11-02T04:00:00Z", max_horizon: 30, horizons: [7, 15, 30], training_run_id: "TR-1" },
  forecast_state: {},
};
const legacySummary = {
  run_id: "FCR-LEGACY", horizon: 7, grand_total: 501096, n_series: 2, start_date: "2026-11-03", end_date: "2026-11-09",
  forecast_origin: "2026-11-02", data_as_of: "2026-11-01", data_source: "BIGQUERY", actual: null,
  daily: [{ target_date: "2026-11-03", total: 71000 }], series: [{ sku_id: "LEGACY-SKU", fc_id: "HN", product_name: null, total: 300000 }],
  methods: [{ method: "LIGHTGBM", n_series: 2, total: 501096 }],
};
const sel2Run = { id: "RF-SEL2-1", forecast_date: "2026-11-14", data_as_of: "2026-11-13", model_version: "SEL2-V9", created_at: "2026-11-14T01:30:00Z", data_source: "BIGQUERY", estimate_from: 8 };
const sel2Summary = {
  run: sel2Run, horizon: 7, start_date: "2026-11-14", end_date: "2026-11-20", n_series: 12345, grand_total: 576999, actual: null,
  daily: [{ target_date: "2026-11-14", total: 82000, cach_tinh: "SEL2", actual_today: null }, { target_date: "2026-11-15", total: 83000, cach_tinh: "SEL2", actual_today: null }],
  series: Array.from({ length: 10 }, (_, i) => ({ sku_id: `SEL2-SKU-${i}`, fc_id: "BD", product_name: null, total: 1000 - i, method: "LIGHTGBM" })),
};

type Opts = { settings?: any; summary?: (u: URL) => any; summaryStatus?: number; sel2RunsPending?: boolean; status?: any };
function mockFetch(sel2Runs: any[], o: Opts = {}) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    calls.push(u);
    if (u.startsWith("/api/daily-forecast/sel2-runs") && o.sel2RunsPending) return new Promise<Response>(() => {});   // never answers
    let code = 200;
    let body: any = u.startsWith("/api/system/status") ? (o.status ?? status)
      : u.startsWith("/api/settings") ? (o.settings ?? { horizons: { enabled: [7, 15, 30] } })
      : u.startsWith("/api/daily-forecast/sel2-runs") ? sel2Runs
      : u.startsWith("/api/daily-forecast/sel2-summary") ? (o.summary ? o.summary(new URL(u, "http://x")) : { ...sel2Summary, horizon: Number(new URL(u, "http://x").searchParams.get("horizon")) })
      : u.startsWith("/api/forecast-runs/FCR-LEGACY/summary") ? legacySummary
      : {};
    if (u.startsWith("/api/daily-forecast/sel2-summary") && o.summaryStatus) {
      code = o.summaryStatus; body = { code: "INTERNAL", category: "INTERNAL", vi: "Lỗi", en: "Error" };
    }
    return new Response(JSON.stringify(body), { status: code, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}
const text = () => document.body.textContent ?? "";
const open = async () => { await act(async () => { render(<I18nProvider><MemoryRouter><App /></MemoryRouter></I18nProvider>); }); };

beforeEach(() => localStorage.clear());

describe("v1.4.12 Dashboard forecast numbers from SEL2", () => {
  it("SEL2 active: total, dates, origin, run id, chart, top 10 and model version come from sel2-summary; no banner", async () => {
    const calls = mockFetch([sel2Run]);
    await open();
    await waitFor(() => expect(text()).toContain("RF-SEL2-1"));
    expect(text()).toMatch(/576[.,\s]?999/);                       // grand_total of the SEL2 window
    expect(text()).not.toMatch(/501[.,\s]?096/);                   // never the legacy total
    expect(text()).toContain("12.345");                            // n_series
    expect(text()).toContain("14/11/2026");                        // start and origin (run.forecast_date)
    expect(text()).toContain("20/11/2026");                        // end
    expect(text()).toContain("13/11/2026");                        // data as of
    expect(text()).toContain("SEL2-V9");                           // model version card = the SEL2 run's
    expect(text()).not.toContain("MV-LEGACY");
    expect(text()).not.toContain("FCR-LEGACY");
    expect(screen.getAllByText(/SEL2-SKU-\d/)).toHaveLength(10);   // top 10 of the series
    expect(screen.queryByText(/LEGACY-SKU/)).toBeNull();
    expect(screen.getByTestId("dash-cach-tinh").textContent).toBe("SEL2");   // method table: one row, the SEL2 days
    expect(screen.getByTestId("assessment-sel2")).toBeTruthy();
    expect(screen.queryByTestId("legacy-banner")).toBeNull();
    expect(calls.some((c) => c.startsWith("/api/daily-forecast/sel2-summary?horizon=7&limit=10"))).toBe(true);
    expect(calls.some((c) => c.startsWith("/api/forecast-runs/"))).toBe(false);   // the legacy summary is not asked for
  });

  it("SEL2 not active: legacy summary as before and the banner stays", async () => {
    const calls = mockFetch([]);
    await open();
    await waitFor(() => expect(text()).toContain("FCR-LEGACY"));
    expect(text()).toMatch(/501[.,\s]?096/);
    expect(text()).toContain("MV-LEGACY");
    expect(text()).toContain("LEGACY-SKU");
    expect(text()).not.toMatch(/576[.,\s]?999/);
    expect(await screen.findByTestId("legacy-banner")).toBeTruthy();
    expect(screen.queryByTestId("assessment-sel2")).toBeNull();
    expect(calls.some((c) => c.startsWith("/api/daily-forecast/sel2-summary"))).toBe(false);
  });

  it("enabled horizon 30 is capped to the SEL2 maximum 20: request and picker", async () => {
    const calls = mockFetch([sel2Run], { settings: { horizons: { enabled: [30] } } });
    await open();
    await waitFor(() => expect(text()).toContain("RF-SEL2-1"));
    expect(calls.some((c) => c.startsWith("/api/daily-forecast/sel2-summary?horizon=20&limit=10"))).toBe(true);
    expect(calls.some((c) => c.includes("horizon=30"))).toBe(false);
    const picker = screen.getByTestId("horizon-picker") as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(["20"]);
    expect(picker.value).toBe("20");
  });

  it("sel2-summary error: error box, no numbers", async () => {
    mockFetch([sel2Run], { summaryStatus: 500 });
    await open();
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.queryByTestId("assessment-sel2")).toBeNull());
    expect(text()).not.toContain("RF-SEL2-1");
    expect(text()).not.toMatch(/576[.,\s]?999/);
    expect(screen.queryByTestId("dash-cach-tinh")).toBeNull();
    expect(screen.queryByTestId("legacy-banner")).toBeNull();
  });

  it("horizon >= 8: method table has the SEL2 row and the weekly-estimate row with exact totals", async () => {
    mockFetch([sel2Run], {
      settings: { horizons: { enabled: [15] } },
      summary: (u) => ({ ...sel2Summary, horizon: Number(u.searchParams.get("horizon")), end_date: "2026-11-28", grand_total: 1200000, n_series: 50,
        daily: [{ target_date: "2026-11-14", total: 800000, cach_tinh: "SEL2", actual_today: null },
                { target_date: "2026-11-22", total: 250000, cach_tinh: "UOC_TINH_THEO_TUAN", actual_today: null },
                { target_date: "2026-11-23", total: 150000, cach_tinh: "UOC_TINH_THEO_TUAN", actual_today: null }] }),
    });
    await open();
    await waitFor(() => expect(screen.getAllByTestId("dash-cach-tinh")).toHaveLength(2));
    const rows = screen.getAllByTestId("dash-cach-tinh").map((c) => c.closest("tr")!.textContent ?? "");
    expect(rows[0]).toContain("SEL2");
    expect(rows[0]).toMatch(/800[.,\s]?000/);
    expect(rows[1]).toContain("Ước tính theo tuần");
    expect(rows[1]).toMatch(/400[.,\s]?000/);
    expect(text()).toMatch(/1[.,\s]?200[.,\s]?000/);
  });

  it("while the SEL2 run list is loading: neither the legacy version, nor a legacy empty state, nor the banner", async () => {
    mockFetch([], { sel2RunsPending: true, status: { ...status, latest_forecast_run: null, forecast_state: { status: "NO_FORECAST_FOR_ACTIVE_SOURCE", other_source_runs: 0 } } });
    await open();
    await waitFor(() => expect(text()).toContain("BQ test"));         // the status has arrived
    expect(screen.queryByTestId("dash-no-forecast")).toBeNull();
    expect(screen.queryByTestId("legacy-banner")).toBeNull();
  });

  it("while the SEL2 run list is loading: the model version card does not show the legacy version", async () => {
    mockFetch([], { sel2RunsPending: true });
    await open();
    await waitFor(() => expect(text()).toContain("BQ test"));
    expect(text()).not.toContain("MV-LEGACY");
    expect(text()).not.toContain("FCR-LEGACY");
  });
});
