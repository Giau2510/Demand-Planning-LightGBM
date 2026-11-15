import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";

// 1.4.14 (owner order 15/11/2026, Task 8): "Kết quả dự báo" is merged into "Dự báo hằng ngày" (tab "Tổng theo SKU × kho"),
// removed from the menu; /results redirects there with a SEL2 run and still renders the legacy page without one.
// Backend mocked (unit, no network): the numbers are those of the sel2-summary API, shown unchanged.
function Where() { const l = useLocation(); return <span data-testid="where">{l.pathname}{l.search}</span>; }
const wrap = (path: string) => <I18nProvider><MemoryRouter initialEntries={[path]}><App /><Where /></MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const SYS = {
  version: "1.4.14", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 12, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-11-14", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};
const RUN = { id: "FRR-1414", forecast_date: "2026-11-15", data_as_of: "2026-11-14", created_at: "2026-11-14T23:30:00+00:00", model_version: "MV-1414",
  config_version: "SEL2:abc", trial_mode: false, horizon: 7, n_series: 2, n_lightgbm: 2, n_fallback: 0, trigger: "SCHEDULE" };
const SRUN = { id: "FRR-1414", model_version: "MV-1414", data_source: "BIGQUERY", scope_key: "BIGQUERY:p.d.t", forecast_origin: "2026-11-15",
  forecast_date: "2026-11-15", data_as_of: "2026-11-14", created_at: "2026-11-14T23:30:00+00:00", max_horizon: 7, horizons: [1, 2, 3, 4, 5, 6, 7],
  fcs: ["BD"], sel2: true };
const SUMMARY = { run: SRUN, start_date: "2026-11-15", end_date: "2026-11-21", horizon: 7, grand_total: 1234, n_series: 2, actual: null,
  daily: [100, 200, 300, 150, 150, 200, 134].map((y, i) => ({ target_date: `2026-11-${15 + i}`, total: y, cach_tinh: "SEL2" })),
  series: [{ sku_id: "MEDX.A", fc_id: "BD", product_name: "Thuoc A", total: 800, method: "MOC", model_used: "MOC", forecast_source: "LIGHTGBM" },
    { sku_id: "MEDX.B", fc_id: "BD", product_name: "Thuoc B", total: 434, method: "MOC", model_used: "MOC", forecast_source: "LIGHTGBM" }] };
const DVALUES = { run: RUN, total: 1, page: 0, page_size: 100, horizons: [1, 2, 3, 4, 5, 6, 7], sel2: true, rows: [{ forecast_date: "2026-11-15",
  target_date: "2026-11-15", horizon: 1, fc_code: "BD", sku_code: "MEDX.A", product_name: "Thuoc A", group_code: "A", lgb_raw: 2.2, final_qty: 3,
  method: "MOC", cach_tinh: "SEL2", forecast_source: "LIGHTGBM", flags: null }] };
const STATUS = { enabled: true, trial_mode: false, trial_label: null, refresh_enabled: true, refresh_deadline: "12:00", today: "2026-11-15",
  last_run: RUN, made_on: "2026-11-15", data_to: "2026-11-14", message: null, stale: false, outdated: false, last_report: null, trial_confirm_text: "" };
const LEGACY_RUN = { id: "FR-LEG", data_source: "MANUAL_IMPORT", active_scope: true, model_version: "MV-LEG", horizons: [7], max_horizon: 7,
  created_at: "2026-11-14T10:00:00+00:00", forecast_origin: "2026-11-14", data_as_of: "2026-11-14", scope_key: "MANUAL_IMPORT:b1", skus: [], fcs: [] };

const OLD = { ...RUN, id: "FRR-OLD", forecast_date: "2026-11-14", model_version: "MV-OLD" };
const OLD_SUMMARY = { ...SUMMARY, run: { ...SRUN, id: "FRR-OLD", model_version: "MV-OLD" }, grand_total: 999,
  series: [{ sku_id: "MEDX.Z", fc_id: "BD", product_name: "Thuoc Z", total: 999, method: "MOC", model_used: "MOC", forecast_source: "LIGHTGBM" }], n_series: 1 };

/** sel2Runs = the published SEL2 runs the mock answers with ([] = DEMO / manual import mode); dailyRuns = the refresh runs
 *  of the daily page (newest first). */
function backend(sel2Runs: any[], dailyRuns: any[] = [RUN, OLD]) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    calls.push(u);
    if (u.startsWith("/api/system/status")) return json(SYS);
    if (u.startsWith("/api/methods")) return json({ methods: {}, reasons: {} });
    if (u.startsWith("/api/forecast-info")) return json({ source: null, run_id: null, refreshed_at: null, data_cutoff_date: null, forecast_date: null });
    if (u.startsWith("/api/forecast-runs?")) return json(sel2Runs.length ? [] : [LEGACY_RUN]);
    if (u.startsWith("/api/daily-forecast/sel2-runs")) return json(sel2Runs);
    if (u.startsWith("/api/daily-forecast/sel2-summary")) return json(u.includes("run_id=FRR-OLD") ? OLD_SUMMARY : SUMMARY);
    if (u.startsWith("/api/daily-forecast/values")) return json(u.includes("run_id=FRR-OLD") ? { ...DVALUES, run: OLD } : { ...DVALUES, run: dailyRuns[0] });
    if (u.startsWith("/api/daily-forecast/runs")) return json(dailyRuns);
    if (u.startsWith("/api/daily-forecast/status")) return json(STATUS);
    if (u.startsWith("/api/sel2/source-config")) return json({ items: [], total: 0 });
    if (u.startsWith("/api/sel2/export")) return json({ items: [] });
    if (u.startsWith("/api/accuracy-reports")) return json([]);
    if (u.startsWith("/api/jobs/active")) return json({});
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}

describe("1.4.14 Results merged into the daily forecast page", () => {
  it("the menu has no 'Kết quả dự báo' (and no /results link)", async () => {
    backend([RUN]);
    const r = await act(async () => render(wrap("/")));
    const side = r.container.querySelector(".side")!;
    expect(side.textContent).not.toContain("Kết quả dự báo");
    expect(side.querySelector("a[href='/results']")).toBeNull();
    expect(side.querySelector("a[href='/daily-forecast']")?.textContent).toBe("Dự báo hằng ngày");
  });

  it("/results redirects to /daily-forecast?tab=tong in SEL2 mode and the tab shows grand_total, the daily trend and the series", async () => {
    const calls = backend([RUN]);
    const r = await act(async () => render(wrap("/results")));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/daily-forecast?tab=tong"));
    await waitFor(() => expect(screen.getByText("MEDX.B")).toBeTruthy());
    expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Dự báo hằng ngày");
    // the card with grand_total of sel2-summary (1.234 = locale grouping of 1234) and the run
    const totals = screen.getByTestId("sel2-totals");
    expect(totals.querySelector(".grid4")?.textContent).toMatch(/1[.,\s\u00a0]?234/);
    expect(totals.textContent).toContain("MV-1414");
    expect(totals.querySelector("svg")).toBeTruthy();                                   // daily trend chart
    const rows = Array.from(screen.getByTestId("sel2-totals-table").querySelectorAll("tbody tr")).map((tr) => tr.textContent);
    expect(rows.length).toBe(2);
    expect(rows[0]).toContain("MEDX.A");
    expect(rows[0]).toContain("800");
    expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-summary") && u.includes("run_id=FRR-1414") && u.includes("horizon=7"))).toBe(true);
    // the detail table of the other tab is not rendered at the same time
    expect(screen.queryByTestId("daily-table")).toBeNull();
  });

  it("the tab is switchable and the detail tab is the unchanged 'Số dự báo' table; ?tab=tong is kept in the address", async () => {
    backend([RUN]);
    await act(async () => render(wrap("/daily-forecast")));
    const table = await screen.findByTestId("daily-table");
    expect(screen.getByTestId("daily-tab-detail").getAttribute("aria-selected")).toBe("true");
    const head = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(head).toEqual(["Ngày lập", "Ngày", "Ngày thứ", "FC/kho", "SKU", "Tên sản phẩm", "Nhóm", "LightGBM gốc", "Số công bố", "Phương pháp", "Cách tính", "Nguồn", "Cờ"]);
    await act(async () => { fireEvent.click(screen.getByTestId("daily-tab-totals")); });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/daily-forecast?tab=tong"));
    await waitFor(() => expect(screen.getByText("MEDX.B")).toBeTruthy());
    expect(screen.queryByTestId("daily-table")).toBeNull();
    await act(async () => { fireEvent.click(screen.getByTestId("daily-tab-detail")); });
    await screen.findByTestId("daily-table");
    expect(screen.getByTestId("where").textContent).toBe("/daily-forecast");
  });

  it("without a SEL2 run (DEMO / manual import) /results keeps rendering the legacy page, no redirect, and the daily page has no tabs", async () => {
    backend([]);
    const r = await act(async () => render(wrap("/results")));
    await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Kết quả dự báo"));
    expect(screen.getByTestId("where").textContent).toBe("/results");
    expect(await screen.findByTestId("run-select")).toBeTruthy();                       // legacy run picker
    r.unmount();
    // a non-SEL2 run on the daily page: no totals tab (it needs a SEL2 run) even when asked for with ?tab=tong
    globalThis.fetch = vi.fn(async (url: any) => {
      const u = String(url);
      if (u.startsWith("/api/daily-forecast/values")) return json({ ...DVALUES, run: { ...RUN, config_version: "1" }, sel2: false });
      if (u.startsWith("/api/daily-forecast/runs")) return json([]);
      if (u.startsWith("/api/daily-forecast/status")) return json(STATUS);
      if (u.startsWith("/api/system/status")) return json(SYS);
      if (u.startsWith("/api/forecast-info")) return json({});
      if (u.startsWith("/api/accuracy-reports")) return json([]);
      if (u.startsWith("/api/jobs/active")) return json({});
      return json({ code: "TEST_UNAVAILABLE" }, 503);
    }) as any;
    await act(async () => render(wrap("/daily-forecast?tab=tong")));
    await screen.findByTestId("daily-table");
    expect(screen.queryByTestId("daily-tab-totals")).toBeNull();
    expect(screen.queryByTestId("sel2-totals")).toBeNull();
  });

  it("/results stays on the legacy page when the newest refresh run is not a SEL2 run", async () => {
    backend([RUN], [{ ...RUN, id: "FRR-NEW", config_version: "1.3.x" }, RUN]);
    const r = await act(async () => render(wrap("/results")));
    await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Kết quả dự báo"));
    expect(screen.getByTestId("where").textContent).toBe("/results");
  });

  it("an older run chosen on the daily page is the one the totals tab reads (run_id of sel2-summary, its numbers)", async () => {
    const calls = backend([RUN]);
    const r = await act(async () => render(wrap("/daily-forecast?tab=tong")));
    await waitFor(() => expect(screen.getByText("MEDX.B")).toBeTruthy());
    expect(r.container.querySelector("[data-testid=sel2-totals] .grid4")?.textContent).toContain("MV-1414");
    await act(async () => { fireEvent.click(screen.getByTestId("daily-view-FRR-OLD")); });   // "Xem" of the older run
    await waitFor(() => expect(screen.getByText("MEDX.Z")).toBeTruthy());
    expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-summary") && u.includes("run_id=FRR-OLD"))).toBe(true);
    const grid = r.container.querySelector("[data-testid=sel2-totals] .grid4")!.textContent!;
    expect(grid).toContain("MV-OLD");
    expect(grid).toMatch(/999/);
    expect(screen.queryByText("MEDX.B")).toBeNull();
  });

  it("the totals view keeps its horizon and search when the tab is switched away and back", async () => {
    const calls = backend([RUN]);
    await act(async () => render(wrap("/daily-forecast?tab=tong")));
    await waitFor(() => expect(screen.getByText("MEDX.B")).toBeTruthy());
    await act(async () => { fireEvent.change(screen.getByTestId("horizon-picker"), { target: { value: "5" } }); });
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-summary") && u.includes("horizon=5"))).toBe(true));
    await act(async () => { fireEvent.click(screen.getByTestId("daily-tab-detail")); });
    await screen.findByTestId("daily-table");
    await act(async () => { fireEvent.click(screen.getByTestId("daily-tab-totals")); });
    expect((screen.getByTestId("horizon-picker") as HTMLSelectElement).value).toBe("5");
  });

  it("the dashboard link of the forecast block goes to the daily page tab in SEL2 mode", async () => {
    backend([RUN]);
    const r = await act(async () => render(wrap("/")));
    await waitFor(() => expect(r.container.querySelector("a[href='/daily-forecast?tab=tong']")).not.toBeNull());
    expect(r.container.querySelector("a[href='/daily-forecast?tab=tong']")?.textContent).toBe("Dự báo hằng ngày →");
    expect(r.container.querySelector("main a[href='/results']")).toBeNull();
  });
});
