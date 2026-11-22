import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import SyncRollbackCard from "./components/SyncRollbackCard";

// 1.4.15 (lot 5): card "Quay lại lần đồng bộ" of the page "SQL nguồn & đồng bộ". Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
afterEach(() => { vi.useRealTimers(); });

const GB = 1024 ** 3;
const TEXT = "QUAY-LAI-DONG-BO-2026-11-23";
const DESC = [
  { code: "SYNC_ROLLBACK_RESTORES_DEMAND", vi: "Hoàn tác trả lại ĐÚNG các dòng số bán lịch sử của lần đó.", en: "Restores exactly the stored demand rows of that run." },
  { code: "SYNC_ROLLBACK_NOT_MODELS", vi: "KHÔNG trả lại mô hình hay số dự báo đã học / đã công bố trên dữ liệu đã đổi.", en: "Does NOT undo models or forecasts already trained / published." },
  { code: "ROLLBACK_ONLY_BEFORE_NEXT_WRITE", vi: "Quay lại chỉ chắc chắn khi chưa có lần ghi nào khác.", en: "A rollback is only safe before the next write." },
  { code: "SYNC_ROLLBACK_LATER_WRITES", vi: "Chỉ hoàn tác được khi chưa có lần ghi sau nào đổi các dòng đó.", en: "Only possible when no later write changed those rows." },
];
const run = (id: string, kind: string, status: string, rollbackable: boolean | null, reason: string | null, extra: any = {}) => ({
  id, kind, status, started_at: "2026-11-22T20:00:00+00:00", window_start: "2026-11-10", window_end: "2026-11-21", summary: { rows_written: 120, holds: 3 }, rollbackable, reason, ...extra });
const RUNS = { configured: true, scope_key: "BIGQUERY:p.d.t", description: DESC, max_entries: 20000, task: null, runs: [
  run("SR-OK", "D1_SYNC", "COMMITTED", true, null),
  run("SR-LATER", "BACKFILL", "COMMITTED", false, "CHANGED_BY_A_LATER_WRITE", { conflicts: 4 }),
  run("SR-DONE", "HOLD_RELEASE", "ROLLED_BACK", false, "ALREADY_ROLLED_BACK"),
  run("SR-KIND", "PREVIEW_X", "COMMITTED", false, "KIND_NOT_ROLLBACKABLE"),
  run("SR-NC", "D1_SYNC", "COMMITTED", null, "NOT_CHECKED"),
  run("SR-BIG", "BACKFILL", "COMMITTED", false, "TOO_LARGE_FOR_THE_UI"),
] };
const PREVIEW = { sync_run_id: "SR-OK", kind: "D1_SYNC", entries: 150, rows_inserted_by_run: 100, rows_updated_by_run: 40, rows_deleted_by_run: 10, units_now: 900.5, units_after_rollback: 700,
  first_day: "2026-11-10", last_day: "2026-11-21", days: 12, finalized_days: 2, holds_to_release: 3, holds_to_restore: 1, holds_of_run_already_released: 0, signature: "sigSR",
  confirm_text: TEXT, reason_min_length: 10, busy: { busy: false, window: null, window_soon: null, schedule_times: [], jobs: [], stale_ignored: [] },
  disk: { ok: true, need_bytes: 3 * GB, free_bytes: 10 * GB, missing_bytes: 0, backup_dir: "D:\\backups" }, ops_lock_checked: true, ops_lock_source: "env", ops_locks: [], busy_other_task: null, description: DESC };
const IDLE = { task: null, running: false, description: DESC };

interface Call { url: string; method: string; body: any }
function backend(o: { preview?: () => Response; run?: () => Response; statuses?: any[]; runs?: any } = {}) {
  const calls: Call[] = [];
  let n = 0;
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (u === "/api/sync-rollback/status") { const s = o.statuses ?? [IDLE]; return json(s[Math.min(n++, s.length - 1)]); }
    if (u === "/api/sync-runs") return json(o.runs ?? RUNS);
    if (u === "/api/sync-rollback/preview") return o.preview ? o.preview() : json(PREVIEW);
    if (u === "/api/sync-rollback") return o.run ? o.run() : json({ accepted: true, task: { status: "RUNNING" } }, 202);
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const gets = (calls: Call[], u: string) => calls.filter((c) => c.method === "GET" && c.url === u);
const mount = async () => { await act(async () => { render(wrap(<SyncRollbackCard />)); }); await screen.findByTestId("sr-runs"); };
const preview = async (id = "SR-OK") => { await act(async () => { fireEvent.click(screen.getByTestId(`sr-preview-${id}`)); }); await screen.findByTestId("sr-confirm-area"); };
const input = (id: string) => screen.getByTestId(id) as HTMLInputElement;

describe("1.4.15 sync rollback card", () => {
  it("lists the sync runs with whether each can be rolled back and the reason when not; the consequences are written before anything is asked", async () => {
    const calls = backend();
    await mount();
    expect(screen.getByTestId("sr-can-SR-OK").textContent).toBe("Có");
    expect(screen.getByTestId("sr-can-SR-LATER").textContent).toContain("Không");
    expect(screen.getByTestId("sr-can-SR-LATER").textContent).toContain("đã có lần ghi sau làm đổi các dòng này (4)");
    expect(screen.getByTestId("sr-can-SR-DONE").textContent).toContain("đã quay lại rồi");
    expect(screen.getByTestId("sr-can-SR-KIND").textContent).toContain("loại này không quay lại được");
    expect(screen.getByTestId("sr-can-SR-NC").textContent).toContain("Chưa kiểm");
    expect((screen.getByTestId("sr-preview-SR-LATER") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("sr-preview-SR-DONE") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("sr-preview-SR-OK") as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByTestId("sr-preview-SR-NC") as HTMLButtonElement).disabled).toBe(false);     // not checked: the preview checks it
    const d = screen.getByTestId("sr-description").textContent!;
    expect(d).toContain("KHÔNG trả lại mô hình hay số dự báo");
    expect(posts(calls)).toEqual([]);
  });

  it("preview (no write): rows / units / days / holds, the consequences, the disk in GB; then the typed text + reason and the body of the rollback", async () => {
    const calls = backend();
    await mount();
    await preview();
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/sync-rollback/preview", body: { sync_run_id: "SR-OK" } });
    const c = screen.getByTestId("sr-preview-counts").textContent!;
    expect(c).toContain("150 dòng thay đổi");
    expect(c).toContain("thêm 100, sửa 40, xóa 10");
    expect(c).toContain("12 ngày");
    expect(c).toContain("2 ngày đã chốt");
    expect(c).toContain("nhả 3, giữ lại 1");
    expect(screen.getByTestId("sr-consequences").textContent).toContain("KHÔNG trả lại mô hình hay số dự báo");
    expect(screen.getByTestId("sr-disk").textContent).toMatch(/3[.,]00 GB/);
    expect(screen.getByTestId("sr-disk").textContent).toContain("D:\\backups");
    expect(screen.getByTestId("sr-text").textContent).toBe(TEXT);
    const go = screen.getByTestId("sr-run") as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(input("sr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("sr-reason"), { target: { value: "ngan" } });
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("sr-reason"), { target: { value: "nhap nham ngay 22 can quay lai" } });
    expect(go.disabled).toBe(false);
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls)[1]).toMatchObject({ url: "/api/sync-rollback", body: { sync_run_id: "SR-OK", signature: "sigSR", confirm_text: TEXT, reason: "nhap nham ngay 22 can quay lai" } });
    expect(await screen.findByText(/Đã nhận yêu cầu: việc chạy nền/)).toBeTruthy();
    expect(screen.queryByTestId("sr-confirm-area")).toBeNull();
  });

  it("a busy system (or a production time near) locks the rollback button and says why, with the overdue jobs left out", async () => {
    backend({ preview: () => json({ ...PREVIEW, busy: { busy: true, detail: "x", window: "23:45-00:15", window_soon: null, schedule_times: [{ setting: "schedule.train_time", time: "07:00" }],
      jobs: [{ job_type: "SEL2_RUN" }], stale_ignored: [{ job_type: "OLD_JOB" }] } }) });
    await mount();
    await preview();
    fireEvent.change(input("sr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("sr-reason"), { target: { value: "nhap nham ngay 22 can quay lai" } });
    expect((screen.getByTestId("sr-run") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("gp-busy-window").textContent).toContain("23:45-00:15");
    expect(screen.getByTestId("gp-busy-jobs").textContent).toContain("SEL2_RUN");
    expect(screen.getByTestId("gp-stale-ignored").textContent).toContain("OLD_JOB");
    expect(screen.getByTestId("bg-sched").textContent).toContain("schedule.train_time 07:00");
    expect(screen.getByTestId("sr-busy-locked").textContent).toContain("nút quay lại bị khóa");
  });

  it("not enough disk for the backup locks the button and shows needed / free / missing in GB", async () => {
    backend({ preview: () => json({ ...PREVIEW, disk: { ok: false, need_bytes: 30 * GB, free_bytes: 10 * GB, missing_bytes: 20 * GB, backup_dir: "D:\\backups" } }) });
    await mount();
    await preview();
    fireEvent.change(input("sr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("sr-reason"), { target: { value: "nhap nham ngay 22 can quay lai" } });
    expect((screen.getByTestId("sr-run") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("sr-disk").textContent).toMatch(/30[.,]00 GB/);
    expect(screen.getByTestId("sr-disk").textContent).toMatch(/Thiếu 20[.,]00 GB/);
  });

  it("409 errors read well: refused because of a later write (keys listed), stale preview, disk, lock, and the confirm text of today", async () => {
    let which = 0;
    const NEXT = "QUAY-LAI-DONG-BO-2026-11-24";
    const errs = [
      () => json({ code: "SYNC_ROLLBACK_PREVIEW_STALE", vi: "Lần đồng bộ đã đổi sau lần xem trước (máy chủ)", en: "Stale", detail: "x" }, 409),
      () => json({ code: "SYNC_ROLLBACK_DISK_SPACE", vi: "Không đủ chỗ trống (máy chủ)", en: "Disk", detail: "x", params: { need_bytes: 30 * GB, free_bytes: 10 * GB, missing_bytes: 20 * GB, backup_dir: "D:\\backups" } }, 409),
      () => json({ code: "OPERATIONS_LOCK_HELD", vi: "Đang có khóa vận hành", en: "Locked", detail: "x", params: { locks: [{ env: "DF_OPS_LOCK", path: "D:\\run\\OPS_LOCK" }] } }, 409),
      () => json({ code: "SYNC_ROLLBACK_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirm", detail: `type ${NEXT}`, params: { confirm_text: NEXT } }, 409),
    ];
    const calls = backend({ run: () => errs[which]() });
    await mount();
    await preview();
    const go = async () => {
      fireEvent.change(input("sr-input"), { target: { value: TEXT } });
      fireEvent.change(screen.getByTestId("sr-reason"), { target: { value: "nhap nham ngay 22 can quay lai" } });
      await act(async () => { fireEvent.click(screen.getByTestId("sr-run")); });
    };
    await go();
    expect(await screen.findByText("Lần đồng bộ đã đổi sau lần xem trước (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("sr-confirm-area")).toBeTruthy();
    which = 1; await go();
    expect(await screen.findByText("Không đủ chỗ trống (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-disk").textContent).toMatch(/thiếu 20[.,]00 GB/);
    which = 2; await go();
    expect(await screen.findByText("Đang có khóa vận hành")).toBeTruthy();
    expect(screen.getByTestId("bg-locks").textContent).toContain("DF_OPS_LOCK = D:\\run\\OPS_LOCK");
    which = 3; await go();
    await waitFor(() => expect(screen.getByTestId("sr-text").textContent).toBe(NEXT));
    expect(input("sr-input").value).toBe("");
    expect(posts(calls).filter((c) => c.url === "/api/sync-rollback")).toHaveLength(4);
  });

  it("a preview refused because a later write changed the keys shows the server message and the keys; no confirm area", async () => {
    backend({ preview: () => json({ code: "SYNC_ROLLBACK_REFUSED", vi: "Không hoàn tác được: có khóa bị lần ghi sau đổi (máy chủ)", en: "Refused", detail: "2 keys",
      params: { n_conflicts: 2, keys: [{ order_date: "2026-11-12", sku_id: "MEDX.A", fc_id: "BD" }, { order_date: "2026-11-13", sku_id: "MEDX.B", fc_id: "HN" }] } }, 409) });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("sr-preview-SR-OK")); });
    expect(await screen.findByText("Không hoàn tác được: có khóa bị lần ghi sau đổi (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-keys").textContent).toContain("2026-11-12 MEDX.A / BD");
    expect(screen.queryByTestId("sr-confirm-area")).toBeNull();
  });

  it("the maximum size comes from the API (not written in the screen); the 'only before the next write' note is a prominent box", async () => {
    backend();
    await mount();
    expect(screen.getByTestId("sr-can-SR-BIG").textContent).toMatch(/tối đa 20[.,]000 dòng thay đổi/);
    expect(screen.getByTestId("sr-description-ROLLBACK_ONLY_BEFORE_NEXT_WRITE-warn").textContent).toContain("chỉ chắc chắn khi chưa có lần ghi nào khác");
    backend({ preview: () => json({ code: "SYNC_ROLLBACK_TOO_LARGE", vi: "Lần đồng bộ quá lớn (máy chủ)", en: "Too large", detail: "x", params: { entries: 25000, max_entries: 20000 } }, 422) });
    await act(async () => { fireEvent.click(screen.getByTestId("sr-preview-SR-NC")); });
    expect(await screen.findByText("Lần đồng bộ quá lớn (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-entries-too-large").textContent).toMatch(/25000 dòng thay đổi, vượt mức tối đa 20000/);
  });

  it("another write button running or an operations lock file locks the rollback button with the reason; the lock source is shown", async () => {
    backend({ preview: () => json({ ...PREVIEW, busy_other_task: { button: "OPEN_HOURS_REREAD", state: "open_hours_reread", task_id: "OHR-1", started_at: "2026-11-23T04:00:00+00:00" },
      ops_locks: [{ env: "DF_OPS_LOCK", path: "D:\\run\\OPS_LOCK" }] }) });
    await mount();
    await preview();
    fireEvent.change(input("sr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("sr-reason"), { target: { value: "nhap nham ngay 22 can quay lai" } });
    expect((screen.getByTestId("sr-run") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("sr-other-task").textContent).toContain("Đang chạy việc khác: Đọc lại giờ mở bán");
    expect(screen.getByTestId("sr-locks").textContent).toContain("DF_OPS_LOCK=D:\\run\\OPS_LOCK; nút bị từ chối");
    expect(screen.getByTestId("sr-lock-checked").textContent).toContain("biến môi trường");
  });

  it("the status: RUNNING polls every 5 s and stops when done (the list is read again); the result lists the backup path in GB and the rollback run", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const RUNNING = { task: { task_id: "SRT-1", status: "RUNNING", started_at: "2026-11-23T04:00:00+00:00" }, running: true, description: DESC };
    const DONE = { task: { task_id: "SRT-1", status: "SUCCEEDED", finished_at: "2026-11-23T04:09:00+00:00",
      result: { sync_run_id: "SR-OK", rollback_run: "SR-RB1", entries: 150, holds_released: 3, holds_restored: 1, backup_file: "backup-y.zip", backup_path: "D:\\backups\\backup-y.zip", backup_bytes: 1.25 * GB } }, running: false, description: DESC };
    const calls = backend({ statuses: [RUNNING, DONE] });
    await mount();
    expect((await screen.findByTestId("sr-task-status")).textContent).toBe("Đang chạy");
    const before = gets(calls, "/api/sync-runs").length;
    await act(async () => { vi.advanceTimersByTime(5000); });
    await waitFor(() => expect(screen.getByTestId("sr-task-status").textContent).toBe("Xong"));
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(gets(calls, "/api/sync-rollback/status")).toHaveLength(2);
    await waitFor(() => expect(gets(calls, "/api/sync-runs").length).toBeGreaterThan(before));
    expect(screen.getByTestId("sr-task-backup").textContent).toContain("D:\\backups\\backup-y.zip");
    expect(screen.getByTestId("sr-task-backup").textContent).toMatch(/1[.,]25 GB/);
    expect(screen.getByTestId("sr-task-result").textContent).toContain("SR-RB1");
  });
});
