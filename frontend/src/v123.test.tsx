import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import Jobs from "./pages/Jobs";
import Mapping from "./pages/Mapping";
import Schedules from "./pages/Schedules";

// 1.2.3 (P0 17/10/2026): manual trainings were skipped with SOURCE_NOT_READY while the Jobs page said "On - loaded by
// the scheduler" for the training flow; BigQuery production mode had been switched off by a mapping save at 17:32.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); });

type Call = { url: string; method: string; body: any };
function mock(routes: Record<string, any>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length)
      .find((k) => (k.includes(" ") ? c.method === k.split(" ")[0] && u.includes(k.split(" ")[1]) : u.includes(k)));
    let v = key ? routes[key] : {};
    if (typeof v === "function") v = v(c);
    return new Response(JSON.stringify(v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const DETAIL = "bigquery.production_enabled=false since 2026-10-17 17:32 (Vietnam), switched off by: field mapping saved; "
  + "fix: BigQuery page -> run the full-period validation -> enable production mode";
const SNR = { code: "SOURCE_NOT_READY", vi: "Nguồn BigQuery chưa sẵn sàng", en: "BigQuery source not ready", detail: DETAIL };
const WAITS = { code: "TRAIN_WAITS_FOR_D1", vi: "Huấn luyện theo lịch chờ D-1", en: "x", detail: "no successful D-1 today and the D-1 flow is OFF" };
const notReady = { ready: false, reasons: [SNR], notes: [] };

describe("v1.2.3 Jobs page: effective flow state", () => {
  it("never says 'On - loaded' for a flow that is on but not ready, and shows why", async () => {
    mock({
      "/api/scheduler/status": { running: true, heartbeat: { at: "2026-10-17T12:20:00+00:00" },
        config: { d1_enabled: false, d0_enabled: false, train_enabled: true, d1_signal_poll_start: "03:00", d0_times: ["08:00"], train_time: "09:00" },
        flow_states: { d1: { enabled: false, state: "OFF", readiness: notReady }, d0: { enabled: false, state: "OFF", readiness: notReady },
          train: { enabled: true, state: "ON_NOT_READY", readiness: notReady } } },
      "/api/jobs": [],
    });
    await act(async () => { render(wrap(<Jobs />)); });
    await waitFor(() => expect(screen.getByTestId("jobs-flow-train")).toBeTruthy());
    const train = screen.getByTestId("jobs-flow-train").textContent ?? "";
    expect(train).not.toContain("Đang bật — scheduler đã nạp");
    expect(train).toContain("Đã bật nhưng hiện chưa sẵn sàng");
    const why = screen.getByTestId("jobs-flow-why-train");
    expect(why.textContent).toContain("SOURCE_NOT_READY");
    expect(why.getAttribute("title")).toContain("field mapping saved");
    expect(screen.queryByTestId("jobs-flow-why-d1")).toBeNull();                  // an OFF flow is just 'Off'
    expect(screen.getByTestId("jobs-flow-d1").textContent).toContain("Tắt");
  });

  it("shows 'On - loaded' only when the backend says the flow is ON", async () => {
    mock({
      "/api/scheduler/status": { running: true, heartbeat: null,
        config: { d1_enabled: true, d0_enabled: false, train_enabled: true, d1_signal_poll_start: "03:00", d0_times: ["08:00"], train_time: "09:00" },
        flow_states: { d1: { enabled: true, state: "ON", readiness: { ready: true, reasons: [], notes: [] } },
          d0: { enabled: false, state: "OFF", readiness: notReady }, train: { enabled: true, state: "ON", readiness: { ready: true, reasons: [], notes: [] } } } },
      "/api/jobs": [],
    });
    await act(async () => { render(wrap(<Jobs />)); });
    await waitFor(() => expect(screen.getByTestId("jobs-flow-train")).toBeTruthy());
    expect(screen.getByTestId("jobs-flow-train").textContent).toContain("Đang bật — scheduler đã nạp");
    expect(screen.queryByTestId("jobs-flow-why-train")).toBeNull();
  });
});

describe("v1.2.3 schedule page: a manual run is not blocked by schedule-only conditions", () => {
  it("enables 'run once now' for training when only the schedule waits for today's D-1", async () => {
    const fl = (f: string, enabled: boolean, config: any, readiness: any, manual: any) => ({ flow: f, enabled,
      state: enabled ? (readiness.ready ? "ON" : "ON_NOT_READY") : "OFF", enabled_at: null, config, timezone: "Asia/Ho_Chi_Minh",
      readiness: { source: "BIGQUERY", ...readiness }, manual_readiness: { source: "BIGQUERY", ...manual }, next_runs: [],
      last_run: null, last_skipped: null, history: [] });
    mock({ "/api/schedules": { timezone: "Asia/Ho_Chi_Minh", now_vn: "2026-10-18T10:00:00+07:00", active_source: "BIGQUERY",
      data_window: { start: "2026-01-01", end: "2026-10-17" }, scheduler: { running: true, last_tick: null, loaded: null }, policy: {},
      flows: {
        d1: fl("d1", false, { time: "03:00", fallback_time: "06:00", poll_interval_minutes: 30 }, notReady, notReady),
        d0: fl("d0", false, { times: ["08:00"], catchup_policy: "LATEST_ONCE" }, notReady, notReady),
        train: fl("train", true, { time: "09:00", catchup_policy: "SKIP" }, { ready: false, reasons: [WAITS], notes: [] },
          { ready: true, reasons: [], notes: [] }),
      } } });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("schedules-page")).toBeTruthy());
    expect((screen.getByTestId("run-train") as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByTestId("run-d1") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("flow-d1").textContent).toContain("switched off by: field mapping saved");
  });
});

describe("v1.2.3 mapping page: saving switches production mode off - said before and after", () => {
  const status = (prod: boolean) => ({ settings: { dataset_id: "d", source_table: "t", production_enabled: prod,
    field_mapping: { order_qty: { column: "demand_quantity", usage: "REQUIRED" }, unit_price: { column: "sales_price", usage: "OPTIONAL" } },
    reference_mapping: {}, schema_snapshot: [{ name: "demand_quantity", type: "INTEGER" }, { name: "sales_price", type: "FLOAT" }] } });

  it("asks for confirmation while production is on; cancel saves nothing, confirm saves and says it is off", async () => {
    const calls = mock({ "/api/bigquery/status": status(true),
      "POST /api/bigquery/mapping": { check: { ok: true, errors: [], warnings: [] }, production_switched_off: true } });
    await act(async () => { render(wrap(<Mapping />)); });
    await waitFor(() => expect(screen.getByTestId("map-prod-state")).toBeTruthy());
    expect(screen.getByTestId("map-prod-state").textContent).toContain("đang BẬT");
    window.confirm = vi.fn(() => false);
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(String((window.confirm as any).mock.calls[0][0])).toContain("TẮT chế độ sản xuất BigQuery");
    expect(calls.some((c) => c.method === "POST" && c.url.includes("/api/bigquery/mapping"))).toBe(false);
    window.confirm = vi.fn(() => true);
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.includes("/api/bigquery/mapping"))).toBe(true));
    await waitFor(() => expect(document.body.textContent).toContain("chế độ sản xuất BigQuery đã TẮT"));
  });

  it("does not ask when production is already off, and says what is blocked", async () => {
    const calls = mock({ "/api/bigquery/status": status(false),
      "POST /api/bigquery/mapping": { check: { ok: true, errors: [], warnings: [] }, production_switched_off: false } });
    await act(async () => { render(wrap(<Mapping />)); });
    await waitFor(() => expect(screen.getByTestId("map-prod-state")).toBeTruthy());
    expect(screen.getByTestId("map-prod-state").textContent).toContain("SOURCE_NOT_READY");
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    expect(window.confirm).not.toHaveBeenCalled();
    expect(calls.some((c) => c.method === "POST" && c.url.includes("/api/bigquery/mapping"))).toBe(true);
  });
});
