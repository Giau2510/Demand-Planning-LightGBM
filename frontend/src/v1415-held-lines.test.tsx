import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import HeldLinesCard from "./components/HeldLinesCard";

// 1.4.15 (lot 3): card "Dòng bị giữ" of the page "Chất lượng dữ liệu". Backend mocked (unit, fake fetch, no network): the card shows
// what the API says, previews before any write (the preview writes nothing), asks the typed text + reason and sends the release.
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
afterEach(() => { vi.useRealTimers(); });

const GB = 1024 ** 3;
const TEXT = "NHA-DONG-GIU-2026-11-23";
const HELD = {
  configured: true, ops_lock_checked: true, policy: "FOLLOW_SOURCE", limits: { max_lines: 450, max_units: 6000 }, scope_key: "BIGQUERY:p.d.t",
  summary: { status: "COMPLETE", active_lines: 120, units: 345.5, keys: 80, days: 30, first_day: "2026-10-01", last_day: "2026-11-20",
    by_cause: { ORDER_GONE: { lines: 100, units: 300 }, QTY_REDUCED: { lines: 20, units: 45.5 } } },
  rows: [{ sku_id: "MEDX.A", fc_id: "BD", lines: 60, units: 200, first_day: "2026-10-01", last_day: "2026-11-01" },
    { sku_id: "MEDX.B", fc_id: "HN", lines: 40, units: 100, first_day: "2026-10-05", last_day: "2026-11-02" }],
  total_groups: 45, task: null, recent_releases: [],
};
const PREVIEW = {
  holds: 30, units: 90, keys: 20, by_cause: { ORDER_GONE: 30 }, signature: "sig1", releasable: true, warnings: [], confirm_text: TEXT, reason_min_length: 10,
  keys_detail: [{ order_date: "2026-10-02", sku_id: "MEDX.A", fc_id: "BD", lines: 3, release_units: 9, stored_qty: 20, qty_after: 11, row_removed: false },
    { order_date: "2026-10-03", sku_id: "MEDX.A", fc_id: "BD", lines: 1, release_units: 4, stored_qty: 4, qty_after: null, row_removed: true }],
  ops_lock_checked: true, ops_lock_source: "env", ops_locks: [], limits: { max_lines: 450, max_units: 6000 }, busy_other_task: null,
  daily: { releases_used: 1, releases_left: 2, lines_used: 100, lines_left: 1250, max_releases: 3, max_lines: 1350 },
  description: [{ code: "HELD_RELEASE_TOUCHES_FINAL_ACTUALS", vi: "Lưu ý: nhả có thể đổi số bán đã lưu của các ngày đã chốt thực tế.", en: "Note: a release can change the stored sales of days whose actuals are final." }],
  disk: { ok: true, need_bytes: 3 * GB, free_bytes: 10 * GB, missing_bytes: 0, backup_dir: "D:\\backups" },
};
const IDLE = { task: null, running: false, recent_releases: [], backups: { release_backups: 0 }, scope_key: "BIGQUERY:p.d.t" };

interface Call { url: string; method: string; body: any }
let lastCalls: Call[] = [];
const calls = () => lastCalls;
function backend(o: { held?: any; statuses?: any[]; preview?: () => Response; release?: () => Response } = {}) {
  const calls: Call[] = [];
  lastCalls = calls;
  let n = 0;
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (u.startsWith("/api/held-lines/release-status")) { const s = (o.statuses ?? [IDLE]); return json(s[Math.min(n++, s.length - 1)]); }
    if (u === "/api/held-lines/release-preview") return o.preview ? o.preview() : json(PREVIEW);
    if (u === "/api/held-lines/release") return o.release ? o.release() : json({ accepted: true, task: { status: "RUNNING", task_id: "HLT-1" } }, 202);
    if (u.startsWith("/api/held-lines")) return json(o.held ?? HELD);
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const gets = (calls: Call[], prefix: string) => calls.filter((c) => c.method === "GET" && c.url.startsWith(prefix));
const mount = async () => { await act(async () => { render(wrap(<HeldLinesCard />)); }); await screen.findByTestId("hl-summary"); };
const preview = async () => { await act(async () => { fireEvent.click(screen.getByTestId("hl-preview")); }); await screen.findByTestId("hl-confirm-area"); };
const input = (id: string) => screen.getByTestId(id) as HTMLInputElement;

describe("1.4.15 held lines card", () => {
  it("shows the summary, the groups, the prominent warning, and the undo hint; nothing is written", async () => {
    const calls = backend();
    await mount();
    expect(gets(calls, "/api/held-lines?")[0].url).toBe("/api/held-lines?view=sku_fc&limit=20&offset=0");
    expect(screen.getByTestId("hl-active").textContent).toMatch(/120/);
    expect(screen.getByTestId("hl-by-cause").textContent).toContain("Đơn biến mất khỏi nguồn");
    expect(screen.getAllByTestId("hl-row")).toHaveLength(2);
    const w = screen.getByTestId("hl-warning").textContent!;
    for (const x of ["sao lưu CSDL tự động", "≥ 1,5 lần", "đổi dữ liệu nhu cầu lịch sử", "số dự báo", "không trả lại model đã học", "Quay lại lần đồng bộ"]) expect(w, x).toContain(x);
    expect(screen.getByTestId("hl-undo-hint").querySelector("a")!.getAttribute("href")).toBe("/sql");
    expect(screen.queryByTestId("hl-lock-unchecked")).toBeNull();
    expect(posts(calls)).toEqual([]);
  });

  it("says when the operations lock is not checked on this machine, and when the summary is partial", async () => {
    backend({ held: { ...HELD, ops_lock_checked: false, summary: { ...HELD.summary, status: "CAPPED" } } });
    await mount();
    expect(screen.getByTestId("hl-lock-unchecked").textContent).toContain("Khóa vận hành không được kiểm trên máy này");
    expect(screen.getByTestId("hl-partial").textContent).toContain("giới hạn đọc");
  });

  it("filters by SKU, cause and day range through the query of the API; the preview uses the same filter and sends only what is set", async () => {
    const calls = backend();
    await mount();
    fireEvent.change(input("hl-f-sku"), { target: { value: "MEDX.A" } });
    fireEvent.change(screen.getByTestId("hl-f-cause"), { target: { value: "ORDER_GONE" } });
    const [dStart, dEnd] = screen.getAllByPlaceholderText("DD/MM/YYYY");                  // the two day boxes: from, to
    fireEvent.change(dStart, { target: { value: "01/10/2026" } });
    fireEvent.change(dEnd, { target: { value: "31/10/2026" } });
    await act(async () => { fireEvent.click(screen.getByTestId("hl-filter-apply")); });
    await waitFor(() => expect(gets(calls, "/api/held-lines?").length).toBe(2));
    expect(gets(calls, "/api/held-lines?")[1].url).toBe("/api/held-lines?view=sku_fc&sku_id=MEDX.A&cause=ORDER_GONE&start=2026-10-01&end=2026-10-31&limit=20&offset=0");
    await preview();
    expect(posts(calls)[0]).toMatchObject({ url: "/api/held-lines/release-preview", body: { sku_id: "MEDX.A", cause: "ORDER_GONE", start: "2026-10-01", end: "2026-10-31" } });
  });

  it("changing the view and the page asks the API again (lines view lists the lines)", async () => {
    const calls = backend();
    await mount();
    fireEvent.change(screen.getByTestId("hl-view"), { target: { value: "lines" } });
    await waitFor(() => expect(gets(calls, "/api/held-lines?").length).toBe(2));
    expect(gets(calls, "/api/held-lines?")[1].url).toBe("/api/held-lines?view=lines&limit=20&offset=0");
    await act(async () => { fireEvent.click(screen.getByText("Sau")); });
    await waitFor(() => expect(gets(calls, "/api/held-lines?").length).toBe(3));
    expect(gets(calls, "/api/held-lines?")[2].url).toBe("/api/held-lines?view=lines&limit=20&offset=20");
  });

  it("preview: counts, keys before / after, the disk in GB and the warning again; then the typed text + reason before the release, and the body", async () => {
    const calls = backend();
    await mount();
    await preview();
    expect(posts(calls)).toHaveLength(1);                                                   // only the preview
    expect(screen.getByTestId("hl-preview-counts").textContent).toContain("30 dòng");
    expect(screen.getByTestId("hl-preview-keys").textContent).toContain("xóa dòng lưu");
    expect(screen.getByTestId("hl-disk").textContent).toMatch(/3[.,]00 GB/);
    expect(screen.getByTestId("hl-disk").textContent).toMatch(/10[.,]00 GB/);
    expect(screen.getByTestId("hl-warning-confirm").textContent).toContain("sao lưu CSDL tự động");
    expect(screen.getByTestId("hl-text").textContent).toBe(TEXT);
    const go = screen.getByTestId("hl-release") as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(input("hl-input"), { target: { value: TEXT.toLowerCase() } });
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
    expect(go.disabled).toBe(true);                                                          // wrong text
    fireEvent.change(input("hl-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "ngan" } });
    expect(go.disabled).toBe(true);                                                          // reason too short
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
    expect(go.disabled).toBe(false);
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls)[1]).toMatchObject({ url: "/api/held-lines/release", body: { signature: "sig1", confirm_text: TEXT, reason: "nha dong theo yeu cau chu du an" } });
    expect(await screen.findByText(/Đã nhận yêu cầu: việc chạy nền/)).toBeTruthy();
    expect(screen.queryByTestId("hl-confirm-area")).toBeNull();
    await waitFor(() => expect(gets(calls, "/api/held-lines/release-status").length).toBeGreaterThanOrEqual(2));   // the status is read again
  });

  it("nothing to release and a disk that is too small both stop the release button", async () => {
    backend({ preview: () => json({ ...PREVIEW, holds: 0, units: 0, keys: 0, releasable: false, signature: null, keys_detail: [], warnings: ["HELD_RELEASE_NOTHING"] }) });
    await mount();
    await preview();
    expect(screen.getByTestId("hl-nothing")).toBeTruthy();
    expect(screen.queryByTestId("hl-release")).toBeNull();
    backend({ preview: () => json({ ...PREVIEW, disk: { ok: false, need_bytes: 30 * GB, free_bytes: 10 * GB, missing_bytes: 20 * GB, backup_dir: "D:\\backups" } }) });
    await act(async () => { fireEvent.click(screen.getByTestId("hl-preview")); });
    await screen.findByTestId("hl-disk");
    fireEvent.change(input("hl-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
    expect((screen.getByTestId("hl-release") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("hl-disk").textContent).toMatch(/Thiếu 20[.,]00 GB/);
  });

  it("over the limit (422 HELD_RELEASE_TOO_LARGE): the server message, the numbers, the largest groups and how to narrow; no confirm area", async () => {
    backend({ preview: () => json({ code: "HELD_RELEASE_TOO_LARGE", vi: "Lựa chọn quá lớn (máy chủ)", en: "Too large", detail: "600 lines",
      params: { holds: 600, units: 7000, capped: false, limits: { max_lines: 450, max_units: 6000 },
        by_sku_fc: [{ sku_id: "MEDX.A", fc_id: "BD", lines: 400, units: 5000 }], by_day: [{ order_date: "2026-10-02", lines: 300, units: 3000 }] } }, 422) });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("hl-preview")); });
    expect(await screen.findByText("Lựa chọn quá lớn (máy chủ)")).toBeTruthy();
    const tl = screen.getByTestId("bg-toolarge").textContent!;
    expect(tl).toContain("600 dòng");
    expect(tl).toContain("450 dòng");
    expect(tl).toContain("thu hẹp theo SKU, khoảng ngày hoặc nguyên nhân");
    expect(screen.getByTestId("bg-groups-sku").textContent).toContain("MEDX.A / BD");
    expect(screen.getByTestId("bg-groups-day").textContent).toContain("2026-10-02");
    expect(screen.queryByTestId("hl-confirm-area")).toBeNull();
  });

  it("409 errors read well: disk (needed / free / missing in GB), busy window + schedule times, stale preview, confirm text of today", async () => {
    let which = 0;
    const errs = [
      () => json({ code: "HELD_RELEASE_DISK_SPACE", vi: "Không đủ chỗ trống (máy chủ)", en: "Disk", detail: "x",
        params: { need_bytes: 30 * GB, free_bytes: 10 * GB, missing_bytes: 20 * GB, backup_dir: "D:\\backups" } }, 409),
      () => json({ code: "HELD_RELEASE_BUSY", vi: "Đang bận (máy chủ)", en: "Busy", detail: "x",
        params: { window: null, window_soon: "23:45-00:15", schedule_times: [{ setting: "schedule.d1_fallback_time", time: "06:10" }], jobs: [{ job_type: "D1_SYNC" }], stale_ignored: [], start_margin_minutes: 60 } }, 409),
      () => json({ code: "HELD_RELEASE_PREVIEW_STALE", vi: "Các dòng đã đổi sau lần xem trước", en: "Stale", detail: "x" }, 409),
      () => json({ code: "OPERATIONS_LOCK_HELD", vi: "Đang có khóa vận hành", en: "Locked", detail: "x", params: { locks: [{ env: "DF_OPS_LOCK", path: "D:\\run\\OPS_LOCK" }] } }, 409),
    ];
    backend({ release: () => errs[which]() });
    await mount();
    await preview();
    const run = async () => {
      fireEvent.change(input("hl-input"), { target: { value: TEXT } });
      fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
      await act(async () => { fireEvent.click(screen.getByTestId("hl-release")); });
    };
    await run();
    expect(await screen.findByText("Không đủ chỗ trống (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-disk").textContent).toMatch(/cần 30[.,]00 GB · có 10[.,]00 GB · thiếu 20[.,]00 GB/);
    expect(screen.getByTestId("hl-confirm-area")).toBeTruthy();                                // the form is kept
    which = 1; await run();
    expect(await screen.findByText("Đang bận (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-soon").textContent).toContain("23:45-00:15");
    expect(screen.getByTestId("bg-sched").textContent).toContain("schedule.d1_fallback_time 06:10");
    expect(screen.getByTestId("gp-busy-jobs").textContent).toContain("D1_SYNC");
    which = 2; await run();
    expect(await screen.findByText("Các dòng đã đổi sau lần xem trước")).toBeTruthy();
    which = 3; await run();
    expect(await screen.findByText("Đang có khóa vận hành")).toBeTruthy();
    expect(screen.getByTestId("bg-locks").textContent).toContain("DF_OPS_LOCK = D:\\run\\OPS_LOCK");
  });

  it("HELD_RELEASE_CONFIRM_REQUIRED with the text of today shows it, clears the typed text and does not resend", async () => {
    const NEXT = "NHA-DONG-GIU-2026-11-24";
    const calls = backend({ release: () => json({ code: "HELD_RELEASE_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirm", detail: `type ${NEXT}`, params: { confirm_text: NEXT, reason_min_length: 10 } }, 409) });
    await mount();
    await preview();
    fireEvent.change(input("hl-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
    await act(async () => { fireEvent.click(screen.getByTestId("hl-release")); });
    await waitFor(() => expect(screen.getByTestId("hl-text").textContent).toBe(NEXT));
    expect(input("hl-input").value).toBe("");
    expect((screen.getByTestId("hl-release") as HTMLButtonElement).disabled).toBe(true);
    expect(posts(calls).filter((c) => c.url.endsWith("/release"))).toHaveLength(1);
  });

  it("the status polls every 5 s ONLY while RUNNING; it stops when done and the summary is read again; the result lists the backup and the undo command", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const RUNNING = { task: { task_id: "HLT-1", status: "RUNNING", started_at: "2026-11-23T04:00:00+00:00" }, running: true, recent_releases: [] };
    const DONE = { task: { task_id: "HLT-1", status: "SUCCEEDED", started_at: "2026-11-23T04:00:00+00:00", finished_at: "2026-11-23T04:05:00+00:00",
      result: { sync_run_id: "SR-9", holds: 30, units: 90, keys: 20, backup_file: "backup-x.zip", backup_path: "D:\\backups\\backup-x.zip", backup_bytes: 1.5 * GB,
        rollback: { cli: "app.cli sync-rollback --run SR-9" } } }, running: false, recent_releases: [] };
    const calls = backend({ statuses: [RUNNING, DONE] });
    await mount();
    expect((await screen.findByTestId("hl-task-status")).textContent).toBe("Đang chạy");
    expect(gets(calls, "/api/held-lines/release-status")).toHaveLength(1);
    const before = gets(calls, "/api/held-lines?").length;
    await act(async () => { vi.advanceTimersByTime(5000); });
    await waitFor(() => expect(screen.getByTestId("hl-task-status").textContent).toBe("Xong"));
    expect(gets(calls, "/api/held-lines/release-status")).toHaveLength(2);
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(gets(calls, "/api/held-lines/release-status")).toHaveLength(2);                   // not RUNNING any more: no more polling
    await waitFor(() => expect(gets(calls, "/api/held-lines?").length).toBeGreaterThan(before));
    expect(screen.getByTestId("hl-task-backup").textContent).toContain("D:\\backups\\backup-x.zip");
    expect(screen.getByTestId("hl-task-backup").textContent).toMatch(/1[.,]50 GB/);
    expect(screen.getByTestId("hl-task-result").textContent).toContain("app.cli sync-rollback --run SR-9");
  });

  it("an interrupted task is told as such (committed or not) and a failed one shows its error; 'Làm mới' asks once", async () => {
    const calls = backend({ statuses: [{ task: { task_id: "HLT-2", status: "INTERRUPTED", committed: true, result: { sync_run_id: "SR-8", holds: 5, units: 10, keys: 4, backup_file: "b.zip" } }, running: false, recent_releases: [] }] });
    await mount();
    expect((await screen.findByTestId("hl-task-status")).textContent).toBe("Bị gián đoạn");
    expect(screen.getByTestId("hl-task-interrupted").textContent).toContain("đã được lưu");
    const n = gets(calls, "/api/held-lines/release-status").length;
    await act(async () => { fireEvent.click(screen.getByTestId("hl-task-refresh")); });
    await waitFor(() => expect(gets(calls, "/api/held-lines/release-status").length).toBe(n + 1));
    backend({ statuses: [{ task: { task_id: "HLT-3", status: "FAILED", error: { code: "HELD_RELEASE_FAILED", detail: "disk" } }, running: false, recent_releases: [] }] });
    await act(async () => { fireEvent.click(screen.getByTestId("hl-task-refresh")); });
    await waitFor(() => expect(screen.getByTestId("hl-task-status").textContent).toBe("Lỗi"));
    expect(screen.getByTestId("hl-task-error").textContent).toContain("HELD_RELEASE_FAILED");
  });

  it("preview: the lock source, the allowance left today and the final-actuals warning are shown", async () => {
    backend();
    await mount();
    await preview();
    expect(screen.getByTestId("hl-pv-lock-checked").textContent).toBe("Khóa vận hành đã kiểm (nguồn: biến môi trường).");
    expect(screen.getByTestId("hl-daily").textContent).toMatch(/Hôm nay còn 2 lần và 1[.,]?250 dòng nhả/);
    expect(screen.queryByTestId("hl-daily-blocked")).toBeNull();
    expect(screen.getByTestId("hl-preview-description-HELD_RELEASE_TOUCHES_FINAL_ACTUALS-warn").textContent).toContain("đã chốt thực tế");
  });

  it("another write button running, an operations lock file, or today's allowance used up each lock the release button with the reason", async () => {
    const lock = async (over: any, check: () => void) => {
      backend({ preview: () => json({ ...PREVIEW, ...over }) });
      await act(async () => { fireEvent.click(screen.getByTestId("hl-preview")); });
      await screen.findByTestId("hl-confirm-area");
      fireEvent.change(input("hl-input"), { target: { value: TEXT } });
      fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
      expect((screen.getByTestId("hl-release") as HTMLButtonElement).disabled).toBe(true);
      check();
    };
    backend();
    await mount();
    await lock({ busy_other_task: { button: "OPEN_HOURS_REREAD", state: "open_hours_reread", task_id: "OHR-9", started_at: "2026-11-23T04:00:00+00:00" } },
      () => expect(screen.getByTestId("hl-other-task").textContent).toContain("Đang chạy việc khác: Đọc lại giờ mở bán"));
    await lock({ ops_locks: [{ env: "DF_OPS_LOCK", path: "D:\\run\\OPS_LOCK" }] },
      () => expect(screen.getByTestId("hl-pv-locks").textContent).toBe("Đang có khóa vận hành: DF_OPS_LOCK=D:\\run\\OPS_LOCK; nút bị từ chối."));
    await lock({ daily: { releases_used: 3, releases_left: 0, lines_used: 500, lines_left: 850, max_releases: 3, max_lines: 1350 } },
      () => expect(screen.getByTestId("hl-daily-blocked").textContent).toContain("vượt hạn mức hôm nay"));
    await lock({ daily: { releases_used: 1, releases_left: 2, lines_used: 1330, lines_left: 20, max_releases: 3, max_lines: 1350 } },    // 30 lines > 20 left
      () => expect(screen.getByTestId("hl-daily-blocked")).toBeTruthy());
  });

  it("409 HELD_RELEASE_DAILY_LIMIT shows used / left; 409 HEAVY_WRITE_ANOTHER_RUNNING names the other button", async () => {
    let which = 0;
    const errs = [
      () => json({ code: "HELD_RELEASE_DAILY_LIMIT", vi: "Đã hết hạn mức nhả hôm nay (máy chủ)", en: "Daily limit", detail: "x",
        params: { releases_used: 3, releases_left: 0, lines_used: 400, lines_left: 950, max_releases: 3, max_lines: 1350, holds: 30 } }, 409),
      () => json({ code: "HEAVY_WRITE_ANOTHER_RUNNING", vi: "Đang có một nút ghi khác chạy (máy chủ)", en: "Another running", detail: "x",
        params: { button: "SYNC_ROLLBACK", state: "sync_rollback", task_id: "SRT-3", started_at: "2026-11-23T04:00:00+00:00" } }, 409),
    ];
    backend({ release: () => errs[which]() });
    await mount();
    await preview();
    const go = async () => {
      fireEvent.change(input("hl-input"), { target: { value: TEXT } });
      fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
      await act(async () => { fireEvent.click(screen.getByTestId("hl-release")); });
    };
    await go();
    expect(await screen.findByText("Đã hết hạn mức nhả hôm nay (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-daily-limit").textContent).toContain("đã dùng 3/3 lần và 400/1350 dòng");
    expect(screen.getByTestId("bg-daily-limit").textContent).toContain("còn 0 lần và 950 dòng");
    which = 1; await go();
    expect(await screen.findByText("Đang có một nút ghi khác chạy (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-other-running").textContent).toContain("Đang chạy việc khác: Quay lại lần đồng bộ");
  });

  it("a filter that was edited but not applied locks the preview; the preview prints the filter it was made with", async () => {
    backend();
    await mount();
    const btn = screen.getByTestId("hl-preview") as HTMLButtonElement;
    fireEvent.change(input("hl-f-sku"), { target: { value: "MEDX.A" } });
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("hl-filter-dirty").textContent).toContain("bấm Lọc trước khi xem trước");
    await act(async () => { fireEvent.click(screen.getByTestId("hl-filter-apply")); });
    await waitFor(() => expect(btn.disabled).toBe(false));
    expect(screen.queryByTestId("hl-filter-dirty")).toBeNull();
    await preview();
    expect(screen.getByTestId("hl-preview-filter").textContent).toContain("sku_id=MEDX.A");
  });

  it("the reason is counted like the server does (white space collapsed): extra spaces do not unlock the button", async () => {
    backend();
    await mount();
    await preview();
    fireEvent.change(input("hl-input"), { target: { value: TEXT } });
    const go = screen.getByTestId("hl-release") as HTMLButtonElement;
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "abcd        efgh" } });     // 14 characters, 9 once collapsed
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "abcd        efgh x" } });   // 11 collapsed
    expect(go.disabled).toBe(false);
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls())[1].body.reason).toBe("abcd efgh x");                                       // and it is sent collapsed
  });

  it("the confirmation text given back by a 409 is dropped when the preview is made again", async () => {
    const NEXT = "NHA-DONG-GIU-2026-11-24";
    backend({ release: () => json({ code: "HELD_RELEASE_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirm", detail: `type ${NEXT}`, params: { confirm_text: NEXT } }, 409) });
    await mount();
    await preview();
    fireEvent.change(input("hl-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("hl-reason"), { target: { value: "nha dong theo yeu cau chu du an" } });
    await act(async () => { fireEvent.click(screen.getByTestId("hl-release")); });
    await waitFor(() => expect(screen.getByTestId("hl-text").textContent).toBe(NEXT));
    await act(async () => { fireEvent.click(screen.getByTestId("hl-preview")); });
    await waitFor(() => expect(screen.getByTestId("hl-text").textContent).toBe(TEXT));      // the text of the new preview, not the old answer
  });

  it("not configured: a plain message, no table", async () => {
    backend({ held: { configured: false, ops_lock_checked: true, summary: null, rows: [], task: null, recent_releases: [] } });
    await act(async () => { render(wrap(<HeldLinesCard />)); });
    expect((await screen.findByTestId("hl-not-configured")).textContent).toContain("Chưa cấu hình bảng nguồn BigQuery");
    expect(screen.queryByTestId("hl-rows")).toBeNull();
  });
});
