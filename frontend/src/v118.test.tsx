import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import Schedules from "./pages/Schedules";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); });

type Call = { url: string; method: string; body: any; headers: any };
/** fetch mock: route -> body or (call) => [status, body] */
function mock(routes: Record<string, any>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null, headers: init?.headers ?? {} };
    calls.push(c);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length)
      .find((k) => (k.startsWith("PUT ") ? c.method === "PUT" && u.includes(k.slice(4)) : u.includes(k)));
    let v = key ? routes[key] : {};
    let status = 200;
    if (typeof v === "function") { const r = v(c); if (Array.isArray(r)) { [status, v] = r; } else v = r; }
    return new Response(JSON.stringify(v), { status, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const reason = (code: string, vi: string) => ({ code, vi, en: vi, detail: null });
function flow(f: string, enabled: boolean, ready: boolean, config: any, extra: any = {}) {
  return { flow: f, job_type: { d1: "D1_SYNC", d0: "D0_SYNC", train: "TRAIN_PUBLISH" }[f], enabled, state: enabled ? "ON" : "OFF",
    enabled_at: enabled ? "2026-10-16T00:10:00+07:00" : null, config, timezone: "Asia/Ho_Chi_Minh",
    readiness: { ready, reasons: ready ? [] : [reason("D1_SOURCE_NOT_BIGQUERY", "D-1 chỉ đồng bộ ngày đã đóng từ BigQuery.")], notes: f === "d0" ? [reason("D0_DEMO_SYNTHETIC", "Nguồn DEMO: dữ liệu tổng hợp.")] : [], source: "DEMO" },
    next_runs: enabled ? ["2026-10-16T07:00:00+07:00"] : [], last_run: null, last_skipped: null, history: [], ...extra };
}
function overview(d1cfg = { time: "01:00", fallback_time: "06:00", poll_interval_minutes: 30 }, d0: any = null) {
  return { timezone: "Asia/Ho_Chi_Minh", now_vn: "2026-10-16T00:20:00+07:00", active_source: "DEMO",
    data_window: { start: "2026-01-01", end: "2026-10-15" }, scheduler: { running: true, last_tick: "2026-10-15T17:19:30+00:00", loaded: null },
    policy: { slot_grace_minutes: 20 },
    flows: { d1: flow("d1", false, false, d1cfg),
             d0: d0 ?? flow("d0", false, true, { times: ["08:00", "10:00"], catchup_policy: "LATEST_ONCE" }),
             train: flow("train", true, true, { time: "07:00", catchup_policy: "RUN_ONCE" }, { last_run: { id: "J1", status: "SKIPPED", reason_code: "NO_NEW_DATA", created_at: "2026-10-15T00:00:03+00:00", summary: {} } }) } };
}

describe("v1.1.8 data schedules page", () => {
  it("shows three separate flows from the backend; D-1 cannot be switched on while not ready", async () => {
    mock({ "/api/schedules": overview() });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("schedules-page")).toBeTruthy());
    for (const f of ["d1", "d0", "train"]) expect(screen.getByTestId(`flow-${f}`)).toBeTruthy();
    expect(screen.getByTestId("d1-window").textContent).toContain("01/01/2026");
    expect(screen.getByTestId("d1-window").textContent).toContain("15/10/2026");
    expect(screen.getByTestId("state-d1").textContent).toContain("Tắt");
    expect(screen.getByTestId("state-d1").textContent).toContain("Asia/Ho_Chi_Minh");
    expect(screen.getByTestId("state-train").textContent).toContain("Đang bật");
    expect(screen.getByTestId("flow-d1").textContent).toContain("Chưa sẵn sàng");
    expect(screen.getByTestId("flow-d1").textContent).toContain("D-1 chỉ đồng bộ ngày đã đóng từ BigQuery");
    expect((screen.getByTestId("toggle-d1") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("run-d1") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("toggle-d0") as HTMLButtonElement).disabled).toBe(false);    // D-0 is ready (DEMO)
    expect(screen.getByTestId("next-d0").textContent).toContain("luồng đang tắt");
    expect(screen.queryAllByText(/Bật lịch|Bật scheduler/).length).toBe(0);                    // no common switch
  });

  it("saving D-1 times sends only D-1 fields, runs nothing, and the page shows what the backend saved", async () => {
    let saved = { time: "01:00", fallback_time: "06:00", poll_interval_minutes: 30 };
    const calls = mock({
      "PUT /api/schedules/d1": (c: Call) => { saved = { ...saved, ...c.body }; return { ...flow("d1", false, false, saved), saved: true }; },
      "/api/schedules": () => overview(saved),
    });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("d1-time")).toBeTruthy());
    expect((screen.getByTestId("save-d1") as HTMLButtonElement).disabled).toBe(true);           // nothing changed yet
    fireEvent.change(screen.getByTestId("d1-time"), { target: { value: "2:30" } });
    expect((screen.getByTestId("save-d1") as HTMLButtonElement).disabled).toBe(true);           // invalid HH:MM
    fireEvent.change(screen.getByTestId("d1-time"), { target: { value: "02:30" } });
    await act(async () => { fireEvent.click(screen.getByTestId("save-d1")); });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts.map((c) => c.url)).toEqual(["/api/schedules/d1"]);
    expect(puts[0].body).toEqual({ time: "02:30", fallback_time: "06:00", poll_interval_minutes: 30 });
    expect(puts[0].headers["X-DF-Client"]).toBe("web");
    expect(calls.some((c) => c.method === "POST")).toBe(false);                                  // no job started
    await waitFor(() => expect((screen.getByTestId("d1-time") as HTMLInputElement).value).toBe("02:30"));   // re-read
  });

  it("switching D-0 on asks for confirmation and sends only the D-0 switch; a backend refusal is shown", async () => {
    const calls = mock({
      "PUT /api/schedules/d0": () => [409, { code: "FLOW_NOT_READY", vi: "Luồng chưa sẵn sàng nên không thể bật", en: "x", detail: "SOURCE_NOT_READY",
        params: { reasons: [reason("SOURCE_NOT_READY", "Nguồn BigQuery chưa sẵn sàng")] } }],
      "/api/schedules": overview(),
    });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("toggle-d0")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("toggle-d0")); });
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("flow-d0").textContent).toContain("Luồng chưa sẵn sàng nên không thể bật"));
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts).toHaveLength(1);
    expect(puts[0].url).toBe("/api/schedules/d0");
    expect(puts[0].body).toEqual({ enabled: true });
    expect(screen.getByTestId("state-d0").textContent).toContain("Tắt");                         // still the backend state
  });

  it("D-0 not ready: switch and run are disabled with the reason; loading and error states", async () => {
    const d0 = { ...flow("d0", false, false, { times: ["08:00"], catchup_policy: "SKIP" }),
      readiness: { ready: false, reasons: [reason("D0_SOURCE_MANUAL_IMPORT", "MANUAL_IMPORT không có dữ liệu trong ngày")], notes: [], source: "MANUAL_IMPORT" } };
    mock({ "/api/schedules": overview(undefined, d0) });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("flow-d0")).toBeTruthy());
    expect((screen.getByTestId("toggle-d0") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("run-d0") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("flow-d0").textContent).toContain("MANUAL_IMPORT không có dữ liệu trong ngày");

    mock({ "/api/schedules": () => [503, { code: "STORAGE_NOT_FOUND", vi: "Không tìm thấy thư mục dữ liệu", en: "x" }] });
    let r: any;
    await act(async () => { r = render(wrap(<Schedules />)); });
    await waitFor(() => expect(r.container.textContent).toContain("Không tìm thấy thư mục dữ liệu"));
    expect(r.container.querySelector("[data-testid=schedules-page]")).toBeNull();
  });
});

describe("audit 16/10/2026: job outcome and 'run once now' follow-up on the schedules page", () => {
  it("a training job that SUCCEEDED as a job but was REJECTED / FAILED is not shown as a plain success", async () => {
    const ov: any = overview();
    const at = "2026-10-15T00:00:20+00:00";
    ov.flows.train.last_run = { id: "J7", trigger: "SCHEDULE", status: "SUCCEEDED", result_status: "REJECTED",
      reason_code: "QUALITY_GATE_FAILED", created_at: at, finished_at: at, summary: {} };
    ov.flows.train.history = [ov.flows.train.last_run, { id: "J6", trigger: "MANUAL", status: "SUCCEEDED",
      result_status: "FAILED", reason_code: "TRAINING_FAILED", created_at: at, summary: {} },
      { id: "J5", trigger: "SCHEDULE", status: "SUCCEEDED", result_status: "PUBLISHED", reason_code: "FORECAST_PUBLISHED", created_at: at, summary: {} }];
    mock({ "/api/schedules": ov });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("flow-train")).toBeTruthy());
    const card = screen.getByTestId("flow-train");
    expect(card.querySelector("[data-testid=last-run]")!.textContent).toContain("Hoàn tất — không đạt chất lượng");
    const outcomes = [...card.querySelectorAll("[data-testid=job-outcome]")].map((e) => e.textContent);
    expect(outcomes).toEqual(["Hoàn tất — không đạt chất lượng", "Hoàn tất — không đạt chất lượng", "Thất bại"]);   // last run + 2 history rows; PUBLISHED has none
  });

  it("'run once now' follows the job until it ends, blocks a second click meanwhile, then re-reads the page", async () => {
    let polls = 0, reads = 0;
    const calls = mock({
      "/api/schedules/d0/run": () => ({ id: "J9", job_type: "D0_SYNC", status: "PENDING", already_active: false }),
      "/api/jobs/J9": () => { polls++; const done = polls >= 2;
        return { id: "J9", job_type: "D0_SYNC", status: done ? "SUCCEEDED" : "RUNNING", stage: done ? "DONE" : "SYNCING",
          result: { result: { status: "SUCCEEDED" } } }; },
      "/api/schedules": () => { reads++; return overview(); },
    });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("run-d0")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("run-d0")); });
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("flow-d0").textContent).toContain("Đã tạo job: J9"));
    expect((screen.getByTestId("run-d0") as HTMLButtonElement).disabled).toBe(true);            // job still running
    const readsBefore = reads;
    await waitFor(() => expect(polls).toBeGreaterThanOrEqual(2), { timeout: 6000 });
    await waitFor(() => expect(reads).toBeGreaterThan(readsBefore));                            // page re-read after the end
    await waitFor(() => expect((screen.getByTestId("run-d0") as HTMLButtonElement).disabled).toBe(false));
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/schedules/d0/run"]);
  }, 15000);

  it("an already running job is reported as such, not as a new job", async () => {
    mock({
      "/api/schedules/d0/run": () => ({ id: "J8", job_type: "D0_SYNC", status: "RUNNING", already_active: true }),
      "/api/jobs/J8": () => ({ id: "J8", job_type: "D0_SYNC", status: "SUCCEEDED", stage: "DONE", result: { result: { status: "SUCCEEDED" } } }),
      "/api/schedules": () => overview(),
    });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("run-d0")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("run-d0")); });
    await waitFor(() => expect(screen.getByTestId("flow-d0").textContent).toContain("đang có job chạy"));
    expect(screen.getByTestId("flow-d0").textContent).not.toContain("Đã tạo job");
  });
});
