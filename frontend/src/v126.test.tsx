import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import ForecastHistory from "./pages/ForecastHistory";
import Schedules from "./pages/Schedules";
import { CompareChart } from "./components/ui";

// 1.2.6: a run date without an official session shows its end-of-day backup (labelled, with snapshot day / time made /
// source run); the 23:59 close shows "Đã chốt – cần xác minh", never "Đã hoàn tất" without a signal; the forecast source
// filter reaches summary, rows and Excel; the two day-end flows have their own cards on the schedules page.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); });

type Call = { url: string; method: string; body: any };
function mock(route: (u: string, c: Call) => any) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const c = { url: String(url), method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const v = route(c.url, c);
    return new Response(JSON.stringify(v === undefined ? {} : v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}
const param = (u: string, k: string) => new URL(u, "http://x").searchParams.get(k);

const BQ = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm";
const DAY = { run_date: "2026-10-17", target_date: "2026-10-18", forecast_run_id: "FCR-A", session_started_at: "2026-10-17T12:34:19+00:00",
  published_at: "2026-10-17T12:34:19+00:00", model_version: "MV-A", n_rows: 2, capture_mode: "AT_PUBLISH", sessions_count: 1 };
const BACKUP = { run_date: "2026-10-18", target_date: "2026-10-19", snapshot_id: "FES-1", snapshot_business_date: "2026-10-17",
  snapshot_created_at: "2026-10-17T16:55:04+00:00", forecast_run_id: "FCR-A", source_run_date: "2026-10-17",
  session_started_at: "2026-10-17T12:34:19+00:00", published_at: "2026-10-17T12:34:19+00:00", model_version: "MV-A" };
const OVERVIEW = { scope_key: BQ, data_source: "BIGQUERY", active_scope_key: BQ, today: "2026-10-18", today_session: null, today_backup: BACKUP,
  scopes: [{ scope_key: BQ, data_source: "BIGQUERY", n_days: 1, active: true }], days: [DAY], backup_days: [BACKUP], fcs: ["HN"],
  completion_signal_configured: false };
const CLOSE = { id: "ACL-1", revision: 1, status: "CLOSED_UNVERIFIED", closed_at: "2026-10-18T16:59:02+00:00", cutoff_at: "2026-10-18T16:59:00+00:00",
  source: "D0", total_qty: 30, current: true };
const SUMMARY = { scope_key: BQ, data_source: "BIGQUERY", today: "2026-10-18", matching_skus: null, backup_days: [BACKUP],
  daily: [
    { run_date: "2026-10-17", target_date: "2026-10-18", has_history: true, forecast_source: "PRIMARY", forecast_run_id: "FCR-A", snapshot: null,
      n_rows: 2, forecast: 100, actual: 30, deviation: 70, actual_status: "CLOSED", actual_reason: "CLOSED_D0", actual_close: CLOSE },
    { run_date: "2026-10-18", target_date: "2026-10-19", has_history: true, forecast_source: "SNAPSHOT", forecast_run_id: "FCR-A",
      snapshot: { snapshot_id: "FES-1", snapshot_business_date: "2026-10-17" }, n_rows: 2, forecast: 110, actual: null, deviation: null,
      actual_status: "NO_ACTUAL", actual_reason: "FUTURE_DATE", actual_close: null }],
  kpi: { n_rows: 4, n_rows_compared: 2, days_with_history: 2, days_primary: 1, days_backup: 1, days_compared: 1, forecast_total: 210,
    actual_total: 30, forecast_compared: 100, deviation: 70, abs_error: 70, wape: 2.3333, bias: 2.3333, status: "CLOSED", notes: [] },
  sessions: [{ ...DAY, official: 1, decision: "SELECTED" }] };
const ROWS = [
  { run_date: "2026-10-18", target_date: "2026-10-19", sku_id: "SKU-1", fc_id: "HN", yhat: 55, actual: null, deviation: null, row_wape: null,
    actual_status: "NO_ACTUAL", actual_reason: "FUTURE_DATE", product_name: "Thuốc hạ sốt", forecast_run_id: "FCR-A", model_version: "MV-A",
    session_started_at: "2026-10-17T12:34:19+00:00", actual_as_of: null, forecast_source: "SNAPSHOT", snapshot_id: "FES-1",
    snapshot_business_date: "2026-10-17", snapshot_created_at: "2026-10-17T16:55:04+00:00" },
  { run_date: "2026-10-17", target_date: "2026-10-18", sku_id: "SKU-1", fc_id: "HN", yhat: 50, actual: 30, deviation: 20, row_wape: 0.6667,
    actual_status: "CLOSED", actual_reason: "CLOSED_D0", product_name: "Thuốc hạ sốt", forecast_run_id: "FCR-A", model_version: "MV-A",
    session_started_at: "2026-10-17T12:34:19+00:00", actual_as_of: "2026-10-18T11:00:00+00:00", forecast_source: "PRIMARY", snapshot_id: null,
    snapshot_business_date: null, snapshot_created_at: null },
];
const history = () => mock((u) => {
  if (u.startsWith("/api/history/overview")) return OVERVIEW;
  if (u.startsWith("/api/history/summary")) return SUMMARY;
  if (u.startsWith("/api/history/rows")) return { total: 2, rows: ROWS };
  return {};
});

describe("v1.2.6 forecast history: backup snapshot and 23:59 close", () => {
  it("labels the backup day everywhere and never shows a closed day as complete", async () => {
    const calls = history();
    const r = await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    expect(screen.getByTestId("fh-today-backup").textContent).toContain("Đang dùng snapshot dự phòng cuối ngày 17/10/2026 (tạo lúc 17/10/2026 23:55, run nguồn FCR-A) cho ngày 19/10/2026");
    expect([...screen.getByTestId("fh-run-date").querySelectorAll("option")].map((o) => o.textContent)).toContain("18/10/2026 → 19/10/2026 (Dự phòng)");
    const kpi = within(screen.getByTestId("fh-kpi"));
    expect(kpi.getAllByText("Đã chốt – cần xác minh")).toHaveLength(3);          // actual, deviation, WAPE: not final
    expect(kpi.queryByText("Đã hoàn tất")).toBeNull();
    expect(screen.getByTestId("fh-kpi-backup").textContent).toContain("1 ngày dùng snapshot dự phòng");
    // chart: the backup forecast point is marked and the legend says so
    expect([...r.container.querySelectorAll("[data-testid=cmp-forecast-pt]")].map((e) => e.getAttribute("data-source"))).toEqual(["primary", "backup"]);
    expect(r.container.querySelector(".lg-line.bk")).toBeTruthy();
    expect(r.container.querySelector("[data-testid=cmp-actual-pt]")!.getAttribute("data-status")).toBe("provisional");
    // the backups used: snapshot day, time made, source run, snapshot id
    const bk = screen.getByTestId("fh-backups").textContent!;
    for (const s of ["18/10/2026", "19/10/2026", "17/10/2026 23:55", "FCR-A (17/10/2026)", "FES-1", "MV-A"]) expect(bk).toContain(s);
    // table: same 11 columns, the backup row says "Dự phòng" with its snapshot day, the closed row its status
    const body = [...screen.getByTestId("fh-rows").querySelectorAll("tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent));
    expect(body[0][5]).toBe("Dự phòng 17/10");
    expect(screen.getByTestId("fh-backup").getAttribute("title")).toContain("run nguồn FCR-A");
    expect(body[1][5]).toBe("19:34");
    expect(body[1][10]).toBe("Đã chốt – cần xác minh");
    expect(body[0][7]).toBe("—");                                                 // no actual yet: never 0
    expect(screen.getByTestId("fh-rules").textContent).toContain("snapshot cuối ngày hoàn chỉnh mới nhất");
    expect(screen.getByTestId("fh-rules").textContent).toContain("23:59");
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("the forecast source and 'closed' status filters reach summary, rows and the Excel link", async () => {
    const calls = history();
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    expect([...screen.getByTestId("fh-status").querySelectorAll("option")].map((o) => o.getAttribute("value"))).toContain("CLOSED");
    await act(async () => { fireEvent.change(screen.getByTestId("fh-source"), { target: { value: "SNAPSHOT" } }); });
    await act(async () => { fireEvent.change(screen.getByTestId("fh-status"), { target: { value: "CLOSED" } }); });
    await waitFor(() => {
      for (const ep of ["summary", "rows"]) {
        const last = [...calls].reverse().find((c) => c.url.startsWith(`/api/history/${ep}`))!;
        expect([param(last.url, "forecast_source"), param(last.url, "actual_status")]).toEqual(["SNAPSHOT", "CLOSED"]);
      }
    });
    const href = screen.getByTestId("fh-export").getAttribute("href")!;
    expect([param(href, "forecast_source"), param(href, "actual_status")]).toEqual(["SNAPSHOT", "CLOSED"]);
    expect(screen.getByTestId("filter-state").textContent).toContain("2");
  });
});

describe("v1.2.6 compare chart", () => {
  it("a backup forecast is a dashed segment with a tinted dot, the official one stays solid", () => {
    const { container } = render(wrap(<CompareChart legend={{ forecast: "F", actual: "A", provisional: "P", backup: "B" }} points={[
      { x: "2026-10-01", forecast: 10, actual: 8, tip: [] }, { x: "2026-10-02", forecast: 11, actual: null, tip: [] },
      { x: "2026-10-03", forecast: 12, actual: null, backup: true, tip: [] }]} />));
    expect(container.querySelectorAll("path.line")).toHaveLength(2);
    expect(container.querySelectorAll("path.line.bk")).toHaveLength(1);           // 02 -> 03 touches the backup day
    expect(container.querySelectorAll("circle.pt.bk")).toHaveLength(1);
    expect(container.querySelector(".legend")!.textContent).toContain("B");
  });
});

const reason = (code: string, vi: string) => ({ code, vi, en: vi, detail: null });
function flow(f: string, jt: string, config: any, extra: any = {}) {
  return { flow: f, job_type: jt, enabled: true, state: "ON", enabled_at: null, config, timezone: "Asia/Ho_Chi_Minh",
    readiness: { ready: true, reasons: [], notes: [], source: "BIGQUERY" }, manual_readiness: { ready: true, reasons: [], notes: [] },
    next_runs: ["2026-10-18T23:55:00+07:00"], last_run: null, last_skipped: null, history: [], ...extra };
}
function schedules() {
  const off = (f: string, jt: string, cfg: any) => ({ ...flow(f, jt, cfg), enabled: false, state: "OFF", next_runs: [],
    readiness: { ready: false, reasons: [reason("SOURCE_NOT_READY", "Chưa sẵn sàng")], notes: [] } });
  return { timezone: "Asia/Ho_Chi_Minh", now_vn: "2026-10-18T12:00:00+07:00", active_source: "BIGQUERY",
    data_window: { start: "2026-01-01", end: "2026-10-17" }, scheduler: { running: true, last_tick: "2026-10-18T05:00:00+00:00", loaded: null },
    policy: { slot_grace_minutes: 20 },
    flows: { d1: off("d1", "D1_SYNC", { time: "01:00", fallback_time: "06:00", poll_interval_minutes: 30 }),
      d0: off("d0", "D0_SYNC", { times: ["08:00"], catchup_policy: "LATEST_ONCE" }),
      train: off("train", "TRAIN_PUBLISH", { time: "09:00", catchup_policy: "RUN_ONCE" }),
      eod: flow("eod", "EOD_FORECAST_SNAPSHOT", { time: "23:55" }, { last_run: { id: "J1", trigger: "SCHEDULE", status: "SUCCEEDED",
        result_status: "INCOMPLETE", reason_code: "EOD_SNAPSHOT_INCOMPLETE", created_at: "2026-10-17T16:55:00+00:00", finished_at: "2026-10-17T16:55:03+00:00", summary: { business_date: "2026-10-17", days_covered: 4 } } }),
      close: flow("close", "ACTUAL_CLOSE", { time: "23:59" }, { next_runs: ["2026-10-18T23:59:00+07:00"] }) } };
}

describe("v1.2.6 schedules page: end-of-day backup and actual close", () => {
  it("shows both day-end flows with their time, an incomplete snapshot said as such, and saves only that flow", async () => {
    const calls = mock((_u, c) => (c.method === "PUT" ? { ...schedules().flows.eod, config: { time: "23:50" }, saved: true } : schedules()));
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("flow-eod")).toBeTruthy());
    const page = screen.getByTestId("schedules-page").textContent!;
    expect(page).toContain("Snapshot forecast cuối ngày (dự phòng 7 ngày)");
    expect(page).toContain("Chốt thực tế cuối ngày (23:59)");
    expect(screen.getByTestId("flow-close").textContent).toContain("Đã chốt – cần xác minh");
    expect((screen.getByTestId("eod-time") as HTMLInputElement).value).toBe("23:55");
    expect((screen.getByTestId("close-time") as HTMLInputElement).value).toBe("23:59");
    expect(screen.getByTestId("flow-eod").querySelector("[data-testid=job-outcome]")!.textContent).toContain("KHÔNG đầy đủ 7 ngày");
    expect(screen.getByTestId("offline-rules").textContent).toContain("mốc của hôm qua bị lỡ được chạy bù một lần");
    fireEvent.change(screen.getByTestId("eod-time"), { target: { value: "23:50" } });
    await act(async () => { fireEvent.click(screen.getByTestId("save-eod")); });
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/schedules/eod");
    expect(put.body).toEqual({ time: "23:50" });
  });

  it("shows both day-end flows OFF exactly as the backend reports them (1.2.6 default) and switches one on only on request", async () => {
    const offFlows = () => {
      const s = schedules();
      const off = (v: any) => ({ ...v, enabled: false, state: "OFF", next_runs: [], last_run: null });
      return { ...s, flows: { ...s.flows, eod: off(s.flows.eod), close: off(s.flows.close) } };
    };
    const calls = mock((_u, c) => (c.method === "PUT" ? { ...offFlows().flows.eod, enabled: true, state: "ON", saved: true } : offFlows()));
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("flow-eod")).toBeTruthy());
    for (const f of ["eod", "close"]) {
      expect(screen.getByTestId(`state-${f}`).textContent).toContain("Tắt");
      expect(screen.getByTestId(`toggle-${f}`).textContent).toContain("Bật luồng này");
      expect(screen.getByTestId(`next-${f}`).textContent).not.toContain("23:5");
    }
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);       // showing the page never switches a flow on
    await act(async () => { fireEvent.click(screen.getByTestId("toggle-eod")); });
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/schedules/eod");
    expect(put.body).toEqual({ enabled: true });
  });
});
