import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { I18nProvider } from "./i18n";

// 1.2.7 (slow-dashboard hotfix on top of 1.2.6): the page shows its header at once and each part when its own data arrives; the system
// status is asked ONCE for the shell and the page together; the forecast card loads /api/forecast-runs/{id}/summary on
// its own (never /api/dashboard, which computed the status a second time); a slow or failing part never blanks the
// page and never stands in for data with 0 or "needs configuration".
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter initialEntries={["/"]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });

type Call = { url: string; method: string };
type Reply = { status?: number; body: any };
function mockD(route: (u: string, c: Call) => Reply | Promise<Reply>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const c = { url: String(url), method: init?.method ?? "GET" };
    calls.push(c);
    const r = await route(c.url, c);
    return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}
function later() {
  let resolve!: (r: Reply) => void;
  const p = new Promise<Reply>((r) => (resolve = r));
  return { p, resolve };
}
const param = (u: string, k: string) => new URL(u, "http://x").searchParams.get(k);
const count = (calls: Call[], prefix: string, method = "GET") => calls.filter((c) => c.method === method && c.url.startsWith(prefix)).length;

const BQ = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm";
const RUN = { id: "FCR-20261018043737-798B4D", training_run_id: "TRN-1", model_version: "MV-20261018-092617-2DB8",
  created_at: "2026-10-18T04:37:45+00:00", max_horizon: 7, horizons: [7], data_source: "BIGQUERY" };
const STATUS = {
  version: "1.2.6", active_source: "BIGQUERY", scope: { scope_key: BQ, data_source: "BIGQUERY", label: "lakehouse" }, scope_error: null,
  bigquery_production_enabled: true, data_window: { start: "2026-01-01", end: "2026-10-18" },
  freshness: { max_date: "2026-10-17", lag_days: 2, stale: false, window_rows: 1352355 },
  latest_forecast_run: RUN, latest_accepted_training: { id: "TRN-1", metrics: { wape: 0.8, mae: 1.2, bias: 0.05 } },
  latest_training_attempt: { id: "TRN-1", status: "ACCEPTED", started_at: "2026-10-18T02:00:09+00:00" },
  forecast_state: { status: "OK", data_source: "BIGQUERY", model_in_use: null, latest_attempt: null, other_source_runs: 0 },
  latest_jobs: { D1_SYNC: { id: "J1", status: "FAILED", reason_code: "SOURCE_INCOMPLETE", created_at: "2026-10-18T20:00:19+00:00",
    finished_at: "2026-10-18T22:09:07+00:00" }, D0_SYNC: null, TRAIN_PUBLISH: null, FORECAST_EXTEND: null },
  alerts: [{ id: 16, level: "ERROR", code: "RETRIES_EXHAUSTED", created_at: "2026-10-18T22:09:07+00:00", entity_id: "J1" }],
  scheduler: { running: true },
};
const FC = {
  run_id: RUN.id, horizon: 7, start_date: "2026-10-19", end_date: "2026-10-25", grand_total: 1234.5, n_series: 2, data_source: "BIGQUERY",
  forecast_origin: "2026-10-19", data_as_of: "2026-10-18", model_version: RUN.model_version, created_at: RUN.created_at, scope_key: BQ, q: null,
  actual: { status: "NOT_APPLICABLE", date: "2026-10-19", in_horizon: true, total: null, n_series: 2 },
  daily: [{ target_date: "2026-10-19", total: 600, actual_today: null }, { target_date: "2026-10-20", total: 634.5, actual_today: null }],
  series: [{ sku_id: "SKU1", fc_id: "HN", total: 1000, method: "LGBM", product_name: "A" },
    { sku_id: "SKU2", fc_id: "HCM", total: 234.5, method: "LGBM", product_name: null }],
  methods: [{ method: "LGBM", n_series: 2, total: 1234.5 }],
};
const SETTINGS = { horizons: { enabled: [7, 15, 30] } };
const forecastCard = () => screen.getByText("Lần dự báo đã publish gần nhất").closest("section") as HTMLElement;

describe("v1.2.7: dashboard loads part by part, the status once", () => {
  it("shows the status parts before the forecast summary arrives; the forecast card waits with a loading state, never with numbers", async () => {
    const sum = later();
    mockD((u) => u.startsWith("/api/system/status") ? { body: STATUS } : u.startsWith("/api/settings") ? { body: SETTINGS }
      : u.includes("/summary") ? sum.p : { body: u.startsWith("/api/jobs/active") ? null : {} });
    await act(async () => { render(wrap(<App />)); });
    expect(await screen.findByTestId("dash-window")).toBeTruthy();
    expect(screen.getByText("Đồng bộ lịch sử D-1")).toBeTruthy();                 // jobs card is there already
    expect(screen.getByText("RETRIES_EXHAUSTED")).toBeTruthy();                   // alerts card is there already
    const card = forecastCard();
    expect(within(card).getByText("Đang tải…")).toBeTruthy();
    expect(card.querySelectorAll(".bars .bar-row").length).toBe(0);
    expect(within(card).queryByText(RUN.id)).toBeNull();
    await act(async () => { sum.resolve({ body: FC }); });
    await waitFor(() => expect(forecastCard().querySelectorAll(".bars .bar-row").length).toBe(2));
    expect(within(forecastCard()).getByText(RUN.id)).toBeTruthy();
    expect(within(forecastCard()).queryByText("Đang tải…")).toBeNull();
  });

  it("asks the status once for the shell and the page, never calls /api/dashboard, asks the summary once", async () => {
    const calls = mockD((u) => u.startsWith("/api/system/status") ? { body: STATUS } : u.startsWith("/api/settings") ? { body: SETTINGS }
      : u.includes("/summary") ? { body: FC } : { body: u.startsWith("/api/jobs/active") ? null : {} });
    await act(async () => { render(wrap(<App />)); });
    await waitFor(() => expect(forecastCard().querySelectorAll(".bars .bar-row").length).toBe(2));
    expect(count(calls, "/api/system/status")).toBe(1);
    expect(count(calls, "/api/dashboard")).toBe(0);
    const sums = calls.filter((c) => c.url.includes("/summary"));
    expect(sums.length).toBe(1);
    expect(sums[0].url.startsWith(`/api/forecast-runs/${RUN.id}/summary`)).toBe(true);
    expect(param(sums[0].url, "horizon")).toBe("7");
    expect(param(sums[0].url, "limit")).toBe("10");
  });

  it("caps the horizon at the run's maximum and waits for the settings before asking (one summary request)", async () => {
    const st = later();
    const calls = mockD((u) => u.startsWith("/api/system/status") ? { body: STATUS } : u.startsWith("/api/settings") ? st.p
      : u.includes("/summary") ? { body: FC } : { body: u.startsWith("/api/jobs/active") ? null : {} });
    await act(async () => { render(wrap(<App />)); });
    expect(await screen.findByTestId("dash-window")).toBeTruthy();
    expect(calls.filter((c) => c.url.includes("/summary")).length).toBe(0);
    await act(async () => { st.resolve({ body: { horizons: { enabled: [15, 30] } } }); });
    await waitFor(() => expect(forecastCard().querySelectorAll(".bars .bar-row").length).toBe(2));
    const sums = calls.filter((c) => c.url.includes("/summary"));
    expect(sums.length).toBe(1);
    expect(param(sums[0].url, "horizon")).toBe("7");                               // min(15, run max 7), as /api/dashboard did
  });

  it("a failing forecast summary shows its error inside the forecast card only; the other parts stay", async () => {
    mockD((u) => u.startsWith("/api/system/status") ? { body: STATUS } : u.startsWith("/api/settings") ? { body: SETTINGS }
      : u.includes("/summary") ? { status: 500, body: { code: "INTERNAL_ERROR", vi: "Lỗi hệ thống", en: "Internal error" } }
      : { body: u.startsWith("/api/jobs/active") ? null : {} });
    await act(async () => { render(wrap(<App />)); });
    await waitFor(() => expect(within(forecastCard()).getByRole("alert").textContent).toContain("Lỗi hệ thống"));
    expect(within(forecastCard()).queryByText("Đang tải…")).toBeNull();
    expect(screen.getByTestId("dash-window")).toBeTruthy();
    expect(screen.getByText("Đồng bộ lịch sử D-1")).toBeTruthy();
    expect(screen.getByText("RETRIES_EXHAUSTED")).toBeTruthy();
  });

  it("while the status is slow the page shows its header and loading states, never 'needs configuration' or empty stats", async () => {
    const s = later();
    mockD((u) => u.startsWith("/api/system/status") ? s.p : u.startsWith("/api/settings") ? { body: SETTINGS }
      : u.includes("/summary") ? { body: FC } : { body: u.startsWith("/api/jobs/active") ? null : {} });
    let view!: ReturnType<typeof render>;
    await act(async () => { view = render(wrap(<App />)); });
    expect(screen.getByRole("heading", { name: /Tổng quan/ })).toBeTruthy();
    expect(view.container.querySelectorAll(".content .loading").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText("Cần cấu hình")).toBeNull();
    expect(view.container.querySelectorAll(".content .stat").length).toBe(0);
    expect(screen.queryByTestId("dash-window")).toBeNull();
    await act(async () => { s.resolve({ body: STATUS }); });
    expect(await screen.findByTestId("dash-window")).toBeTruthy();
    await waitFor(() => expect(forecastCard().querySelectorAll(".bars .bar-row").length).toBe(2));
  });

  it("a failed status shows the shell's error and 'not available' in the parts, never stale or invented figures", async () => {
    mockD((u) => u.startsWith("/api/system/status") ? { status: 500, body: { code: "INTERNAL_ERROR", vi: "Lỗi hệ thống", en: "Internal error" } }
      : u.startsWith("/api/settings") ? { body: SETTINGS } : { body: u.startsWith("/api/jobs/active") ? null : {} });
    let view!: ReturnType<typeof render>;
    await act(async () => { view = render(wrap(<App />)); });
    await waitFor(() => expect(screen.getAllByRole("alert").some((a) => (a.textContent ?? "").includes("Lỗi hệ thống"))).toBe(true));
    expect(view.container.querySelectorAll(".content .loading").length).toBe(0);
    expect(screen.getAllByText("Chưa có").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText("Cần cấu hình")).toBeNull();
    expect(view.container.querySelectorAll(".content .stat").length).toBe(0);
  });

  it("after 'acknowledge all' the status is asked again with a new request and the forecast card follows", async () => {
    const calls = mockD((u, c) => c.method === "POST" ? { body: { ok: true } }
      : u.startsWith("/api/system/status") ? { body: STATUS } : u.startsWith("/api/settings") ? { body: SETTINGS }
      : u.includes("/summary") ? { body: FC } : { body: u.startsWith("/api/jobs/active") ? null : {} });
    await act(async () => { render(wrap(<App />)); });
    await waitFor(() => expect(forecastCard().querySelectorAll(".bars .bar-row").length).toBe(2));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Đánh dấu đã đọc tất cả/ })); });
    await waitFor(() => expect(count(calls, "/api/system/status")).toBe(2));
    expect(count(calls, "/api/alerts/ack-all", "POST")).toBe(1);
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/summary")).length).toBe(2));
    expect(count(calls, "/api/dashboard")).toBe(0);
  });
});
