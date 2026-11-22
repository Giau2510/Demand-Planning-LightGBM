import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import OpenHoursReread from "./components/OpenHoursReread";

// 1.4.15 (lot 4): card "Đọc lại giờ mở bán" of the page "SQL nguồn & đồng bộ". Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
afterEach(() => { vi.useRealTimers(); });

const TEXT = "DOC-LAI-GIO-MO-BAN-2026-11-23";
const DESC = [
  { code: "OH_REREAD_SOLVES_EMPTY_DAYS", vi: "Giải quyết: các ngày CHƯA có dòng giờ mở bán đã lưu.", en: "Solves: days with NO stored open-hours row." },
  { code: "OH_REREAD_NOT_PARTIAL_DAYS", vi: "Không giải quyết: ngày đã có MỘT PHẦN dữ liệu không được bổ sung.", en: "Does not solve: a partly stored day is not completed." },
  { code: "OH_REREAD_CHANGES_SEL2_NUMBERS", vi: "Lưu ý: SEL2 đọc giờ mở bán trực tiếp — số dự báo và KPI của ngày cũ có thể đổi.", en: "Note: SEL2 reads open hours directly - old forecast numbers and KPIs can change." },
  { code: "OH_REREAD_NOT_SOURCE_MISSING", vi: "Không giải quyết: ngày nguồn không có số — giữ MISSING, không điền 0.", en: "Does not solve: a day the source has no number for stays MISSING, never 0." },
];
const PLAN = { start: "2026-10-01", end: "2026-10-20", mode: "FILL_MISSING_DAYS_ONLY", days: 20, days_stored: 14, days_missing: 6, stored_rows: 5000,
  missing_days: ["2026-10-03", "2026-10-04", "2026-10-05", "2026-10-10", "2026-10-11", "2026-10-12"],
  reads: [{ start: "2026-10-03", end: "2026-10-05", estimated_bytes: 2_000_000 }, { start: "2026-10-10", end: "2026-10-12", estimated_bytes: 3_000_000 }],
  signature: "sigOH", estimated_bytes: 5_000_000, estimate_error: null, max_days: 60, read_days: 15, confirm_text: TEXT, reason_min_length: 10,
  ops_lock_checked: true, ops_lock_source: "derived", ops_locks: [], busy_other_task: null, description: DESC };
const IDLE = { task: null, running: false, description: DESC };

interface Call { url: string; method: string; body: any }
function backend(o: { plan?: () => Response; run?: () => Response; statuses?: any[] } = {}) {
  const calls: Call[] = [];
  let n = 0;
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (u === "/api/open-hours-reread/status") { const s = o.statuses ?? [IDLE]; return json(s[Math.min(n++, s.length - 1)]); }
    if (u.startsWith("/api/open-hours-reread/plan")) return o.plan ? o.plan() : json(PLAN);
    if (u === "/api/open-hours-reread" && method === "POST") return o.run ? o.run() : json({ accepted: true, task: { status: "RUNNING" } }, 202);
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const gets = (calls: Call[], prefix: string) => calls.filter((c) => c.method === "GET" && c.url.startsWith(prefix));
const mount = async () => { await act(async () => { render(wrap(<OpenHoursReread />)); }); await screen.findByTestId("oh-plan"); };
const setRange = (a: string, b: string) => {
  const [s, e] = screen.getAllByPlaceholderText("DD/MM/YYYY");
  fireEvent.change(s, { target: { value: a } });
  fireEvent.change(e, { target: { value: b } });
};
const plan = async () => { await act(async () => { fireEvent.click(screen.getByTestId("oh-plan")); }); await screen.findByTestId("oh-plan-box"); };
const input = (id: string) => screen.getByTestId(id) as HTMLInputElement;

describe("1.4.15 open hours re-read card", () => {
  it("tells what it solves and does not solve (server descriptions) before anything is asked; the plan button needs a valid range", async () => {
    const calls = backend();
    await mount();
    const d = await screen.findByTestId("oh-description");
    expect(d.textContent).toContain("Giải quyết: các ngày CHƯA có dòng giờ mở bán đã lưu.");
    expect(d.textContent).toContain("MỘT PHẦN dữ liệu không được bổ sung");
    expect(d.textContent).toContain("giữ MISSING, không điền 0");
    const btn = screen.getByTestId("oh-plan") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    setRange("01/10/2026", "20/10/2026");
    expect(btn.disabled).toBe(false);
    expect(posts(calls)).toEqual([]);
  });

  it("a range over 60 days or reversed is refused in the screen with the reason", async () => {
    backend();
    await mount();
    setRange("01/08/2026", "31/10/2026");                      // 92 days
    expect(screen.getByTestId("oh-range-bad").textContent).toContain("92 ngày vượt giới hạn 60 ngày");
    expect((screen.getByTestId("oh-plan") as HTMLButtonElement).disabled).toBe(true);
    setRange("20/10/2026", "01/10/2026");
    expect(screen.getByTestId("oh-range-bad").textContent).toContain("Ngày bắt đầu phải trước");
  });

  it("the plan (GET, no write) shows stored / missing days, the reads with the estimated bytes and the 'MISSING, never 0' rule", async () => {
    const calls = backend();
    await mount();
    setRange("01/10/2026", "20/10/2026");
    await plan();
    expect(gets(calls, "/api/open-hours-reread/plan")[0].url).toBe("/api/open-hours-reread/plan?start=2026-10-01&end=2026-10-20&estimate=true");
    expect(posts(calls)).toEqual([]);
    expect(screen.getByTestId("oh-plan-counts").textContent).toContain("20 ngày");
    expect(screen.getByTestId("oh-plan-counts").textContent).toContain("còn thiếu 6 ngày");
    expect(screen.getByTestId("oh-missing").textContent).toContain("03/10/2026");
    expect(screen.getByTestId("oh-reads").querySelectorAll("tbody tr")).toHaveLength(2);
    expect(screen.getByTestId("oh-estimate").textContent).toContain("lần chạy thử, chưa tính phí");
    expect(screen.getByText(/không điền 0 và không suy đoán/)).toBeTruthy();
  });

  it("nothing missing: says so and offers no run; an estimate that failed is told without blocking", async () => {
    backend({ plan: () => json({ ...PLAN, days_stored: 20, days_missing: 0, missing_days: [], reads: [], signature: null, estimated_bytes: null }) });
    await mount();
    setRange("01/10/2026", "20/10/2026");
    await plan();
    expect(screen.getByTestId("oh-nothing").textContent).toContain("không được bổ sung ở đây");
    expect(screen.queryByTestId("oh-run")).toBeNull();
    backend({ plan: () => json({ ...PLAN, estimated_bytes: null, estimate_error: { code: "BQ_DRY_RUN_FAILED", detail: "x" } }) });
    await act(async () => { fireEvent.click(screen.getByTestId("oh-plan")); });
    await waitFor(() => expect(screen.getByTestId("oh-estimate").textContent).toContain("BQ_DRY_RUN_FAILED"));
    expect(screen.getByTestId("oh-run")).toBeTruthy();
  });

  it("typed text + reason, then POST with start / end / signature / text / reason", async () => {
    const calls = backend();
    await mount();
    setRange("01/10/2026", "20/10/2026");
    await plan();
    expect(screen.getByTestId("oh-text").textContent).toBe(TEXT);
    const go = screen.getByTestId("oh-run") as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(input("oh-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("oh-reason"), { target: { value: "ngan" } });
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("oh-reason"), { target: { value: "bu gio mo ban thang 10" } });
    expect(go.disabled).toBe(false);
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls)[0]).toMatchObject({ url: "/api/open-hours-reread", body: { start: "2026-10-01", end: "2026-10-20", signature: "sigOH", confirm_text: TEXT, reason: "bu gio mo ban thang 10" } });
    expect(await screen.findByText(/Đã nhận yêu cầu: việc chạy nền/)).toBeTruthy();
    expect(screen.queryByTestId("oh-plan-box")).toBeNull();
  });

  it("409 errors read well: busy (night window / schedule time / jobs), stale plan, running, lock held, and the confirm text of today", async () => {
    let which = 0;
    const NEXT = "DOC-LAI-GIO-MO-BAN-2026-11-24";
    const errs = [
      () => json({ code: "OPEN_HOURS_REREAD_BUSY", vi: "Đang bận (máy chủ)", en: "Busy", detail: "x",
        params: { window: "00:45-03:45", window_soon: null, schedule_times: [{ setting: "schedule.refresh_deadline", time: "11:30" }], jobs: [{ job_type: "TRAIN" }], stale_ignored: [{ job_type: "OLD" }] } }, 409),
      () => json({ code: "OPEN_HOURS_REREAD_PLAN_STALE", vi: "Các ngày thiếu đã đổi (máy chủ)", en: "Stale", detail: "x" }, 409),
      () => json({ code: "OPEN_HOURS_REREAD_RUNNING", vi: "Đang có một lần đọc lại chạy", en: "Running", detail: "x" }, 409),
      () => json({ code: "OPERATIONS_LOCK_HELD", vi: "Đang có khóa vận hành", en: "Locked", detail: "x", params: { locks: [{ env: "DF_HEAVY_LOCK", path: "D:\\run\\HEAVY_LOCK" }] } }, 409),
      () => json({ code: "OPEN_HOURS_REREAD_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirm", detail: `type ${NEXT}`, params: { confirm_text: NEXT } }, 409),
    ];
    const calls = backend({ run: () => errs[which]() });
    await mount();
    setRange("01/10/2026", "20/10/2026");
    await plan();
    const run = async () => {
      fireEvent.change(input("oh-input"), { target: { value: TEXT } });
      fireEvent.change(screen.getByTestId("oh-reason"), { target: { value: "bu gio mo ban thang 10" } });
      await act(async () => { fireEvent.click(screen.getByTestId("oh-run")); });
    };
    await run();
    expect(await screen.findByText("Đang bận (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("gp-busy-window").textContent).toContain("00:45-03:45");
    expect(screen.getByTestId("bg-sched").textContent).toContain("schedule.refresh_deadline 11:30");
    expect(screen.getByTestId("gp-stale-ignored").textContent).toContain("OLD");
    expect(screen.getByTestId("oh-plan-box")).toBeTruthy();                       // the form is kept
    which = 1; await run();
    expect(await screen.findByText("Các ngày thiếu đã đổi (máy chủ)")).toBeTruthy();
    which = 2; await run();
    expect(await screen.findByText("Đang có một lần đọc lại chạy")).toBeTruthy();
    which = 3; await run();
    expect(await screen.findByText("Đang có khóa vận hành")).toBeTruthy();
    expect(screen.getByTestId("bg-locks").textContent).toContain("DF_HEAVY_LOCK = D:\\run\\HEAVY_LOCK");
    which = 4; await run();
    await waitFor(() => expect(screen.getByTestId("oh-text").textContent).toBe(NEXT));
    expect(input("oh-input").value).toBe("");
    expect(posts(calls).filter((c) => c.url === "/api/open-hours-reread")).toHaveLength(5);   // never resent by itself
  });

  it("the status shows the progress and the result while it runs, polls every 5 s only while RUNNING, and the plan is dropped when it ends", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const RUNNING = { task: { task_id: "OHR-1", status: "RUNNING", started_at: "2026-11-23T04:00:00+00:00",
      progress: [{ start: "2026-10-03", end: "2026-10-05", rows_read: 100, inserted: 90, skipped_existing: 10 }] }, running: true, description: DESC };
    const DONE = { task: { task_id: "OHR-1", status: "SUCCEEDED", finished_at: "2026-11-23T04:02:00+00:00",
      result: { rows_read: 250, inserted: 240, skipped_existing: 10, loaded_at: "2026-11-23T04:00:00+00:00", undo: { loaded_at: "2026-11-23T04:00:00+00:00" } } }, running: false, description: DESC };
    const calls = backend({ statuses: [RUNNING, DONE] });
    await mount();
    expect((await screen.findByTestId("oh-task-status")).textContent).toBe("Đang chạy");
    expect(screen.getByTestId("oh-progress").textContent).toContain("đọc 100 dòng, thêm 90");
    await act(async () => { vi.advanceTimersByTime(5000); });
    await waitFor(() => expect(screen.getByTestId("oh-task-status").textContent).toBe("Xong"));
    expect(screen.getByTestId("oh-task-result").textContent).toContain("đọc 250 dòng · thêm 240 · bỏ qua 10");
    expect(screen.getByTestId("oh-task-result").textContent).toContain("2026-11-23T04:00:00+00:00");
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(gets(calls, "/api/open-hours-reread/status")).toHaveLength(2);
  });

  it("the progress lists the days skipped because rows were stored meanwhile; a config change stops the task with its own hint", async () => {
    backend({ statuses: [{ task: { task_id: "OHR-3", status: "FAILED", error: { code: "OPEN_HOURS_REREAD_CONFIG_CHANGED", detail: "daily_forecast.openhours_table changed" },
      progress: [{ start: "2026-10-03", end: "2026-10-05", rows_read: 90, inserted: 80, skipped_existing: 10, skipped_days_stored_meanwhile: ["2026-10-04"] },
        { start: "2026-10-10", end: "2026-10-12", skipped_days_stored_meanwhile: ["2026-10-11", "2026-10-12"] }] }, running: false, description: DESC }] });
    await mount();
    expect((await screen.findByTestId("oh-task-status")).textContent).toBe("Lỗi");
    const sk = screen.getAllByTestId("oh-skipped-meanwhile").map((e) => e.textContent);
    expect(sk[0]).toContain("04/10/2026");
    expect(sk[1]).toContain("11/10/2026, 12/10/2026");
    expect(screen.getByTestId("oh-task-error").textContent).toContain("OPEN_HOURS_REREAD_CONFIG_CHANGED");
    expect(screen.getByTestId("oh-config-changed").textContent).toContain("Hãy xem kế hoạch lại");
  });

  it("the SEL2 / KPI warning is a prominent box; the lock source is shown", async () => {
    backend();
    await mount();
    expect((await screen.findByTestId("oh-description-OH_REREAD_CHANGES_SEL2_NUMBERS-warn")).textContent).toContain("SEL2 đọc giờ mở bán trực tiếp");
    setRange("01/10/2026", "20/10/2026");
    await plan();
    expect(screen.getByTestId("oh-lock-checked").textContent).toBe("Khóa vận hành đã kiểm (nguồn: suy ra từ thư mục dữ liệu).");
  });

  it("another write button running or an operations lock file locks 'Đọc lại' with the reason; HEAVY_WRITE_ANOTHER_RUNNING is explained", async () => {
    const OTHER = { button: "HELD_LINES_RELEASE", state: "held_lines_release", task_id: "HLT-4", started_at: "2026-11-23T04:00:00+00:00" };
    backend({ plan: () => json({ ...PLAN, busy_other_task: OTHER, ops_locks: [{ env: "DF_HEAVY_LOCK", path: "D:\\run\\HEAVY_LOCK" }] }) });
    await mount();
    setRange("01/10/2026", "20/10/2026");
    await plan();
    fireEvent.change(input("oh-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("oh-reason"), { target: { value: "bu gio mo ban thang 10" } });
    expect((screen.getByTestId("oh-run") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("oh-other-task").textContent).toContain("Đang chạy việc khác: Nhả dòng bị giữ");
    expect(screen.getByTestId("oh-locks").textContent).toContain("DF_HEAVY_LOCK=D:\\run\\HEAVY_LOCK; nút bị từ chối");
    backend({ run: () => json({ code: "HEAVY_WRITE_ANOTHER_RUNNING", vi: "Đang có một nút ghi khác chạy (máy chủ)", en: "Another running", detail: "x", params: OTHER }, 409) });
    await act(async () => { fireEvent.click(screen.getByTestId("oh-plan")); });                      // a plan without the lock
    await waitFor(() => expect(screen.queryByTestId("oh-other-task")).toBeNull());
    fireEvent.change(input("oh-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("oh-reason"), { target: { value: "bu gio mo ban thang 10" } });
    await act(async () => { fireEvent.click(screen.getByTestId("oh-run")); });
    expect(await screen.findByText("Đang có một nút ghi khác chạy (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-other-running").textContent).toContain("Đang chạy việc khác: Nhả dòng bị giữ");
  });

  it("an interrupted re-read is told as such and does not block a new plan", async () => {
    backend({ statuses: [{ task: { task_id: "OHR-2", status: "INTERRUPTED", committed: false }, running: false, description: DESC }] });
    await mount();
    expect((await screen.findByTestId("oh-task-status")).textContent).toBe("Bị gián đoạn");
    expect(screen.getByTestId("oh-task-interrupted").textContent).toContain("không có gì được ghi");
    setRange("01/10/2026", "20/10/2026");
    expect((screen.getByTestId("oh-plan") as HTMLButtonElement).disabled).toBe(false);
  });
});
