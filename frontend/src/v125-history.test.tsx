import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";
import ForecastHistory, { addDays } from "./pages/ForecastHistory";
import { CompareChart } from "./components/ui";

// 1.2.5 "Forecast & actual history": separate page and menu entry; run date and forecast date shown apart; filters
// combine and reach every request (KPI, chart, table, Excel); provisional / missing actual never shown as final or 0.
const wrap = (el: React.ReactNode, at = "/") => <I18nProvider><MemoryRouter initialEntries={[at]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); document.getElementById("df-remote-banner")?.remove(); });

type Call = { url: string; method: string };
function mock(route: (u: string) => any, status: (u: string) => number = () => 200) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    calls.push({ url: u, method: init?.method ?? "GET" });
    const v = route(u);
    if (v instanceof Promise) return v;
    return new Response(JSON.stringify(v === undefined ? {} : v), { status: status(u), headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}
const param = (u: string, k: string) => new URL(u, "http://x").searchParams.get(k);

const BQ = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm";
const DAYS = [
  { run_date: "2026-10-18", target_date: "2026-10-19", forecast_run_id: "FCR-B", session_started_at: "2026-10-18T02:00:00+00:00",
    published_at: "2026-10-18T02:10:00+00:00", model_version: "MV-B", n_rows: 3, capture_mode: "AT_PUBLISH", sessions_count: 2 },
  { run_date: "2026-10-17", target_date: "2026-10-18", forecast_run_id: "FCR-A", session_started_at: "2026-10-17T12:34:19+00:00",
    published_at: "2026-10-17T12:34:19+00:00", model_version: "MV-A", n_rows: 3, capture_mode: "RECOVERED", sessions_count: 1 },
];
const OVERVIEW = { scope_key: BQ, data_source: "BIGQUERY", active_scope_key: BQ, today: "2026-10-18", today_session: DAYS[0],
  scopes: [{ scope_key: BQ, data_source: "BIGQUERY", n_days: 2, active: true }], days: DAYS, fcs: ["BD", "HN"], completion_signal_configured: false,
  finalization: { finalized_days: 0, blocked_days: 1, last_finalized_date: null, applicable: true } };
const DAILY = [
  { run_date: "2026-10-16", target_date: "2026-10-17", has_history: false, n_rows: 0, forecast: null, actual: null, deviation: null, actual_status: null },
  { run_date: "2026-10-17", target_date: "2026-10-18", has_history: true, n_rows: 3, forecast: 120, actual: 80, deviation: 40,
    actual_status: "PROVISIONAL", actual_reason: "D0_INTRADAY" },
  { run_date: "2026-10-18", target_date: "2026-10-19", has_history: true, n_rows: 3, forecast: 130, actual: null, deviation: null,
    actual_status: "NO_ACTUAL", actual_reason: "FUTURE_DATE" },
];
const SUMMARY = { scope_key: BQ, data_source: "BIGQUERY", today: "2026-10-18", matching_skus: null, daily: DAILY,
  // 1.2.9 (seventh batch): no finalized actual - the provisional rows are a group of their own
  kpi: { n_rows: 6, n_rows_compared: 0, days_with_history: 2, days_compared: 0, forecast_total: 250, actual_total: null, forecast_compared: null,
    deviation: null, abs_error: null, wape: null, bias: null, status: "NO_ACTUAL", notes: ["NO_FINAL_ACTUAL"], basis: "FINALIZED_ONLY", n_zero_absent: 0,
    provisional: { n_rows: 3, days: 1, n_zero_absent: 0, actual_total: 80, forecast_compared: 120, deviation: 40, abs_error: 44, wape: 0.55, bias: 0.5 },
    closed: { n_rows: 0, days: 0, n_zero_absent: 0, actual_total: null, forecast_compared: null, deviation: null, abs_error: null, wape: null, bias: null },
    coverage: { rows_total: 6, rows_final: 0, rows_provisional: 3, rows_closed: 0, rows_no_actual: 3, days_final: 0, days_provisional: 1,
      days_closed: 0, days_no_actual: 1 } },
  sessions: [{ ...DAYS[0], official: 1, decision: "SELECTED" }, { ...DAYS[0], forecast_run_id: "FCR-OLD", official: 0, decision: "OLDER_THAN_SELECTED",
    session_started_at: "2026-10-18T01:00:00+00:00" }, { ...DAYS[1], official: 1, decision: "SELECTED" }] };
const ROWS = [
  { run_date: "2026-10-17", target_date: "2026-10-18", sku_id: "SKU-1", fc_id: "HN", yhat: 50, forecast_qty: 50, actual: 30, deviation: 20, row_wape: 0.6667,
    actual_status: "PROVISIONAL", actual_reason: "D0_INTRADAY", product_name: "Thuốc hạ sốt", forecast_run_id: "FCR-A", model_version: "MV-A",
    session_started_at: "2026-10-17T12:34:19+00:00", actual_as_of: "2026-10-18T01:00:00+00:00" },
  { run_date: "2026-10-18", target_date: "2026-10-19", sku_id: "SKU-2", fc_id: "BD", yhat: 40, forecast_qty: 40, actual: null, deviation: null, row_wape: null,
    actual_status: "NO_ACTUAL", actual_reason: "FUTURE_DATE", product_name: null, forecast_run_id: "FCR-B", model_version: "MV-B",
    session_started_at: "2026-10-18T02:00:00+00:00", actual_as_of: null },
];
function backend(over: Record<string, any> = {}, total = 2) {
  return mock((u) => {
    if (u.startsWith("/api/system/status")) return { version: "1.2.5", active_source: "BIGQUERY", scope: { scope_key: BQ, label: "BQ" }, alerts: [] };
    if (u.startsWith("/api/history/overview")) return { ...OVERVIEW, ...over };
    if (u.startsWith("/api/history/summary")) return SUMMARY;
    if (u.startsWith("/api/history/rows")) return { total, rows: ROWS };
    if (u.startsWith("/api/forecast-runs")) return [];
    return {};
  });
}

describe("v1.2.5 Forecast & actual history page", () => {
  it("has its own menu entry next to the results (the old pages are unchanged) and opens the page", async () => {
    backend();
    const r = await act(async () => render(wrap(<App />, "/results")));
    const links = [...r.container.querySelectorAll(".side a")].map((a) => a.getAttribute("href"));
    expect(links.slice(0, 4)).toEqual(["/", "/results", "/forecast-history", "/performance"]);
    await act(async () => { fireEvent.click(r.container.querySelector(".side a[href='/forecast-history']")!); });
    await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Lịch sử Forecast & Thực tế"));
    expect(r.container.querySelector(".side a[aria-current=page]")?.textContent).toBe("Lịch sử Forecast & Thực tế");
  });

  it("shows run date and forecast date apart, provisional figures apart from the finalized KPI, gaps instead of invented points, missing actual as '—'", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-kpi")).toBeTruthy());
    expect(screen.getByTestId("fh-today").textContent).toContain("Hôm nay (18/10/2026): phiên chính thức lúc 18/10/2026 09:00, dự báo cho 19/10/2026");
    const range = screen.getByTestId("fh-range").textContent!;
    expect(range).toContain("Ngày chạy forecast: 19/09/2026 → 18/10/2026");      // default: last 30 run dates
    expect(range).toContain("Ngày được dự báo: 20/09/2026 (Chủ nhật) → 19/10/2026 (Thứ 2)");   // 1.2.12: + weekday
    const kpi = within(screen.getByTestId("fh-kpi"));
    expect(kpi.getByText("250")).toBeTruthy();
    // 1.2.9 (seventh batch): the main cards are finalized rows only - here none, said plainly; the provisional figures apart
    expect(kpi.queryByText("Tạm tính")).toBeNull();
    expect(kpi.queryByText("55%")).toBeNull();
    expect(screen.getByTestId("fh-no-final").textContent).toBe("Chưa có actual đã chốt");
    const prov = within(screen.getByTestId("fh-prov"));
    expect(prov.getByText("Tạm tính")).toBeTruthy();
    expect(prov.getByText("80")).toBeTruthy();
    expect(prov.getByText("55%")).toBeTruthy();
    expect(prov.getByText("3 dòng · 1 ngày")).toBeTruthy();
    expect(screen.getByTestId("fh-coverage").textContent).toBe("Cơ sở so sánh: 0 dòng đã hoàn tất (0 ngày) · 3 dòng tạm tính · 0 dòng đã "
      + "chốt cuối ngày – cần xác minh · 3 dòng chưa có thực tế (không tính 0)");
    // chart: x = forecast date, one forecast dot per stored day, the actual only where it exists (provisional = hollow)
    expect(r.container.querySelectorAll("[data-testid=cmp-forecast-pt]")).toHaveLength(2);
    const act_ = r.container.querySelectorAll("[data-testid=cmp-actual-pt]");
    expect(act_).toHaveLength(1);
    expect(act_[0].getAttribute("data-status")).toBe("provisional");
    expect(screen.getByTestId("fh-missing-days").textContent).toContain("1 ngày chạy");
    // table: the 11 columns, the run date and forecast date of each row, missing actual is "—" (never 0)
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    const head = [...screen.getByTestId("fh-rows").querySelectorAll("th")].map((th) => th.textContent);
    expect(head).toEqual(["SKU", "Tên sản phẩm", "FC/kho", "Ngày chạy forecast", "Ngày được dự báo", "Phiên được chọn lúc", "Forecast",
      "Thực tế", "Sai lệch (F − T)", "WAPE dòng", "Trạng thái thực tế"]);
    const body = [...screen.getByTestId("fh-rows").querySelectorAll("tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent));
    expect(body[0]).toEqual(["SKU-1", "Thuốc hạ sốt", "HN", "17/10/2026", "18/10/2026 (Chủ nhật)", "19:34", "50", "30", "+20", "66,7%", "Tạm tính"]);   // 1.2.12: + weekday of the forecast date
    expect(body[1]).toEqual(["SKU-2", "Chưa có tên sản phẩm", "BD", "18/10/2026", "19/10/2026 (Thứ 2)", "09:00", "40", "—", "—", "—", "Chưa có dữ liệu thực tế"]);
    // sessions: official one per run date, the other session of the day is traced
    const ses = screen.getByTestId("fh-sessions").textContent!;
    expect(ses).toContain("FCR-B");
    expect(ses).toContain("2 phiên · cũ hơn phiên đã chọn");
    expect(screen.getByTestId("fh-final-state").textContent).toBe("Đã chốt 0 ngày thực tế (mới nhất: —); 1 ngày chưa chốt được — xem lý do ở trạng thái từng ngày.");
    expect(calls.every((c) => c.method === "GET")).toBe(true);                 // the page only reads
    expect(calls.some((c) => /\/api\/(training|jobs|forecast-runs)/.test(c.url))).toBe(false);
  });

  it("filters combine, reach summary + rows + Excel, a single run date shows that day, and clearing resets", async () => {
    const calls = backend();
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    fireEvent.change(screen.getByTestId("fh-run-date"), { target: { value: "2026-10-17" } });
    fireEvent.change(screen.getByTestId("fh-fc"), { target: { value: "HN" } });
    fireEvent.change(screen.getByTestId("fh-status"), { target: { value: "PROVISIONAL" } });
    await act(async () => { fireEvent.change(screen.getByTestId("fh-search"), { target: { value: "thuoc ha" } }); });
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/api/history/rows") && param(c.url, "q") === "thuoc ha")).toBe(true), { timeout: 2000 });
    for (const ep of ["summary", "rows"]) {
      const last = [...calls].reverse().find((c) => c.url.startsWith(`/api/history/${ep}`))!;
      expect([param(last.url, "run_from"), param(last.url, "run_to"), param(last.url, "fc_id"), param(last.url, "actual_status"), param(last.url, "q"),
        param(last.url, "scope_key")]).toEqual(["2026-10-17", "2026-10-17", "HN", "PROVISIONAL", "thuoc ha", BQ]);
    }
    expect(screen.getByTestId("fh-range").textContent).toContain("Ngày chạy forecast: 17/10/2026 · Ngày được dự báo: 18/10/2026");
    const href = screen.getByTestId("fh-export").getAttribute("href")!;
    expect([param(href, "run_from"), param(href, "run_to"), param(href, "fc_id"), param(href, "actual_status"), param(href, "q"), param(href, "lang"),
      param(href, "limit"), param(href, "offset")]).toEqual(["2026-10-17", "2026-10-17", "HN", "PROVISIONAL", "thuoc ha", "vi", null, null]);
    expect(screen.getByTestId("filter-state").textContent).toContain("4");
    await act(async () => { fireEvent.click(screen.getByTestId("filter-clear")); });
    await waitFor(() => {
      const last = [...calls].reverse().find((c) => c.url.startsWith("/api/history/summary"))!;
      expect([param(last.url, "run_from"), param(last.url, "fc_id"), param(last.url, "actual_status"), param(last.url, "q")]).toEqual(["2026-09-19", null, null, null]);
    });
  });

  it("pages through the rows of the same filter and sorts on the server", async () => {
    const calls = backend({}, 250);
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByText(/Trang 1 \/ 3/)).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Sau/ })); });
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/api/history/rows") && param(c.url, "offset") === "100")).toBe(true));
    await act(async () => { fireEvent.change(screen.getByTestId("fh-sort"), { target: { value: "abs_error" } }); });
    await waitFor(() => {
      const last = [...calls].reverse().find((c) => c.url.startsWith("/api/history/rows"))!;
      expect([param(last.url, "sort"), param(last.url, "offset")]).toEqual(["abs_error", "0"]);    // new sort -> first page
    });
  });

  it("empty: no stored history -> says so, invents nothing, and no valid forecast today", async () => {
    const calls = backend({ days: [], today_session: null, scopes: [] });
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByText("Chưa có lịch sử forecast được lưu")).toBeTruthy());
    expect(screen.getByTestId("fh-today").textContent).toContain("Hôm nay (18/10/2026): chưa có forecast hợp lệ. Một phiên forecast chỉ được tạo khi");
    expect(screen.queryByTestId("fh-export")).toBeNull();
    expect(screen.queryByTestId("compare-chart")).toBeNull();
    expect(calls.some((c) => c.url.startsWith("/api/history/summary"))).toBe(false);
  });

  it("loading and error states keep the page header", async () => {
    let release: (v: Response) => void = () => {};
    mock((u) => (u.startsWith("/api/history/overview") ? new Promise<Response>((res) => { release = res; }) : {}));
    const r = await act(async () => render(wrap(<ForecastHistory />)));
    expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Lịch sử Forecast & Thực tế");
    expect(r.container.querySelector(".loading")).toBeTruthy();
    await act(async () => release(new Response(JSON.stringify({ code: "DATABASE_ERROR", vi: "Lỗi cơ sở dữ liệu", en: "Database error" }),
      { status: 500, headers: { "content-type": "application/json" } })));
    await waitFor(() => expect(r.container.querySelector(".alert")).toBeTruthy());
    expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Lịch sử Forecast & Thực tế");
  });
});

describe("v1.2.5 compare chart", () => {
  it("never joins across a gap and marks provisional actuals", () => {
    const { container } = render(wrap(<CompareChart legend={{ forecast: "F", actual: "A", provisional: "P" }} points={[
      { x: "2026-10-01", forecast: 10, actual: 8, tip: [] }, { x: "2026-10-02", forecast: null, actual: null, tip: [] },
      { x: "2026-10-03", forecast: 12, actual: 11, provisional: true, tip: [] }, { x: "2026-10-04", forecast: 9, actual: null, tip: [] }]} />));
    expect(container.querySelectorAll("path.line")).toHaveLength(1);              // 03 -> 04 only: 01 -> 03 crosses the gap
    expect(container.querySelectorAll("path.actual-line")).toHaveLength(0);       // no two consecutive actuals
    expect([...container.querySelectorAll("[data-testid=cmp-actual-pt]")].map((e) => e.getAttribute("data-status"))).toEqual(["complete", "provisional"]);
    expect(container.querySelector(".lg-actual.prov")).toBeTruthy();
  });

  it("'all dates' never asks for more than the 400 run dates the API serves", async () => {
    const many = Array.from({ length: 450 }, (_, i) => ({ ...DAYS[1], run_date: addDays("2026-10-18", -i), target_date: addDays("2026-10-18", 1 - i) }));
    const calls = backend({ days: many });
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-run-date")).toBeTruthy());
    await act(async () => { fireEvent.change(screen.getByTestId("fh-run-date"), { target: { value: "all" } }); });
    await waitFor(() => {
      const last = [...calls].reverse().find((c) => c.url.startsWith("/api/history/summary"))!;
      expect([param(last.url, "run_from"), param(last.url, "run_to")]).toEqual([addDays("2026-10-18", -399), "2026-10-18"]);
    });
  });

  it("date helper is calendar arithmetic and never throws before the data is there", () => {
    expect(addDays("2026-10-01", -1)).toBe("2026-09-30");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("", -29)).toBe("");
  });
});
