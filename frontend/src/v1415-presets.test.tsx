import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import PresetsCard from "./components/PresetsCard";

// 1.4.15 (lot 6): card "Cấu hình mẫu (preset)" of the page "Cấu hình dự báo". Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const TEXT = "AP-DUNG-PRESET-LGBM-CHOT-2026-11-23";
const PURCH = "DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-23";
const DESC = [
  { code: "PRESET_LGBM_CHOT_DESC", vi: "lgbm-chot (PHƯƠNG ÁN CHỐT 1.3.1): cấu hình mô hình và bật các luồng.", en: "lgbm-chot (FINAL 1.3.1 OPTION): model setup and flows on." },
  { code: "PRESET_NO_LOG_RETENTION", vi: "Bộ cấu hình không đổi số ngày lưu nhật ký.", en: "The preset does not change the log retention." },
];
const LIST = { presets: [{ name: "lgbm-chot", sections: { model: { num_threads: 4, feature_calendar: true }, sel2_pipeline: { enabled: true } }, flows: ["d1", "train"], confirm_text: TEXT, description: DESC }] };
const PREVIEW = {
  preset: "lgbm-chot",
  changes: [{ section: "model", key: "num_threads", from: 0, to: 4, risk: "PURCHASE", undoable: true },
    { section: "daily_forecast", key: "rounding_threshold", from: 0.3, to: 0.2, risk: "READONLY", undoable: false }],
  kept_higher: [{ section: "sel2_pipeline", key: "retention_days", current: 400, preset: 365 }],
  flows: [{ flow: "d1", from: false, to: true, ready: true, reasons: [] }, { flow: "train", from: true, to: true, ready: true, reasons: [] }],
  changed: true, ready: true, expected_hash: "hash1", confirm_text: TEXT, reason_min_length: 10,
  not_undoable: ["daily_forecast.rounding_threshold", "flow d1"], description: DESC, busy: { busy: false, window: null, jobs: [], stale_ignored: [] },
  needs_purchase_confirm: true, purchase_keys: ["model.num_threads"], confirm_purchase: PURCH,
  undo_warning: { code: "PRESET_UNDO_SETTINGS_ONLY", vi: "Hoàn tác chỉ đặt lại cài đặt; các luồng lịch đã bật bởi bộ cấu hình giữ nguyên, tắt ở trang Lịch chạy.", en: "An undo only restores settings; flows switched on stay on." },

};

interface Call { url: string; method: string; body: any }
function backend(o: { preview?: () => Response; apply?: () => Response } = {}) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (u === "/api/presets") return json(LIST);
    if (u === "/api/presets/lgbm-chot/preview") return o.preview ? o.preview() : json(PREVIEW);
    if (u === "/api/presets/lgbm-chot/apply") return o.apply ? o.apply() : json({ preset: "lgbm-chot", applied: [{ section: "model", key: "num_threads", from: 0, to: 4 }], kept_higher: PREVIEW.kept_higher,
      flows: [{ flow: "d1", from: false, to: true, ready: true, reasons: [] }, { flow: "train", from: true, to: true, ready: true, reasons: [] }], undo_audit_id: 77,
      not_undoable: ["daily_forecast.rounding_threshold", "flow d1"], partial: false, flow_errors: [], warnings: [], undo_warning: { code: "PRESET_UNDO_SETTINGS_ONLY", vi: "Hoàn tác chỉ đặt lại cài đặt; các luồng lịch đã bật bởi bộ cấu hình giữ nguyên, tắt ở trang Lịch chạy.", en: "An undo only restores settings; flows switched on stay on." } });
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const mount = async () => { await act(async () => { render(wrap(<PresetsCard />)); }); await screen.findByTestId("pr-row-lgbm-chot"); };
const preview = async () => { await act(async () => { fireEvent.click(screen.getByTestId("pr-preview-lgbm-chot")); }); await screen.findByTestId("pr-confirm-area"); };
const input = (id: string) => screen.getByTestId(id) as HTMLInputElement;

describe("1.4.15 presets card", () => {
  it("lists the presets with their description and flows, and the prominent warning; nothing is written", async () => {
    const calls = backend();
    await mount();
    expect(screen.getByTestId("pr-desc-lgbm-chot").textContent).toContain("PHƯƠNG ÁN CHỐT 1.3.1");
    expect(screen.getByTestId("pr-row-lgbm-chot").textContent).toContain("d1, train");
    expect(screen.getByTestId("pr-row-lgbm-chot").textContent).toContain("3 khóa cài đặt");
    const w = screen.getByTestId("pr-warning").textContent!;
    for (const x of ["Đổi số dự báo / mua hàng và bật luồng", "không ghi log_retention_days", "chỉ được tăng"]) expect(w, x).toContain(x);
    expect(posts(calls)).toEqual([]);
  });

  it("preview (POST, no write): old → new keys with the risk, the keys kept higher, the flows with their readiness, not_undoable and how to undo", async () => {
    const calls = backend();
    await mount();
    await preview();
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0].url).toBe("/api/presets/lgbm-chot/preview");
    const c = screen.getByTestId("pr-change-model.num_threads").textContent!;
    expect(c).toContain("0");
    expect(c).toContain("4");
    expect(c).toContain("Ảnh hưởng mua hàng");
    expect(screen.getByTestId("pr-change-daily_forecast.rounding_threshold").textContent).toContain("Chỉ xem");
    expect(screen.getByTestId("pr-kept").textContent).toContain("sel2_pipeline.retention_days: hiện 400, preset 365");
    expect(screen.getByTestId("pr-flow-d1").textContent).toContain("sẽ bật");
    expect(screen.getByTestId("pr-flow-d1").textContent).toContain("Sẵn sàng");
    expect(screen.getByTestId("pr-flow-train").textContent).toContain("đang bật");
    expect(screen.getByTestId("pr-notundo").textContent).toContain("daily_forecast.rounding_threshold, flow d1");
    expect(screen.getByTestId("pr-undo-guide-preview").textContent).toContain("Cài đặt nâng cao → Lần đổi gần đây → Hoàn tác");
    expect(screen.getByTestId("pr-warning-confirm")).toBeTruthy();
  });

  it("typed text + reason before Apply; the body is {expected_hash, confirm_text, reason}; the result shows the undo guide with the audit id", async () => {
    const calls = backend();
    await mount();
    await preview();
    expect(screen.getByTestId("pr-text").textContent).toBe(TEXT);
    const go = screen.getByTestId("pr-apply") as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(input("pr-input"), { target: { value: TEXT.toLowerCase() } });
    fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
    expect(go.disabled).toBe(true);
    fireEvent.change(input("pr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "ngan" } });
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
    expect(go.disabled).toBe(true);                                                          // a PURCHASE key changes: its own text is missing
    expect(screen.getByTestId("pr-purchase-keys").textContent).toContain("model.num_threads");
    expect(screen.getByTestId("pr-purchase-text").textContent).toBe(PURCH);
    fireEvent.change(input("pr-purchase-input"), { target: { value: TEXT } });                // the wrong one
    expect(go.disabled).toBe(true);
    fireEvent.change(input("pr-purchase-input"), { target: { value: PURCH } });
    expect(go.disabled).toBe(false);
    expect(screen.getByTestId("pr-undo-warning-preview").textContent).toContain("các luồng lịch đã bật bởi bộ cấu hình giữ nguyên");
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls)[1]).toEqual({ url: "/api/presets/lgbm-chot/apply", method: "POST", body: { expected_hash: "hash1", confirm_text: TEXT, reason: "phuong an chot 1.3.1 theo chu du an", confirm_purchase: PURCH } });
    expect(screen.queryByTestId("pr-partial")).toBeNull();
    expect(screen.getByTestId("pr-undo-warning").textContent).toContain("Hoàn tác chỉ đặt lại cài đặt");
    expect(await screen.findByText("Đã áp dụng preset (backend xác nhận).")).toBeTruthy();
    expect(screen.getByTestId("pr-undo-guide").textContent).toContain("Cài đặt nâng cao → Lần đổi gần đây → Hoàn tác");
    expect(screen.getByTestId("pr-undo-guide").textContent).toContain("lần đổi số 77");
    expect(screen.getByTestId("pr-result-notundo").textContent).toContain("flow d1");
    expect(screen.getByTestId("pr-result-flows").textContent).toContain("đã bật");
    expect(screen.queryByTestId("pr-confirm-area")).toBeNull();
  });

  it("a flow that is not ready blocks Apply and says why (before any write); a busy system locks it too", async () => {
    backend({ preview: () => json({ ...PREVIEW, ready: false, flows: [{ flow: "d1", from: false, to: true, ready: false, reasons: [{ code: "SQL_NOT_VALIDATED", detail: "d1 v2 UNCHECKED" }] }],
      busy: { busy: true, window: "23:45-00:15", jobs: [{ job_type: "TRAIN" }], stale_ignored: [] } }) });
    await mount();
    await preview();
    fireEvent.change(input("pr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
    expect((screen.getByTestId("pr-apply") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("pr-flow-d1").textContent).toContain("Chưa sẵn sàng");
    expect(screen.getByTestId("pr-flow-d1").textContent).toContain("SQL_NOT_VALIDATED");
    expect(screen.getByTestId("pr-blocked").textContent).toContain("chưa áp dụng được");
    expect(screen.getByTestId("gp-busy-window").textContent).toContain("23:45-00:15");
  });

  it("a production window / saved schedule time near, or an operations lock file, lock Apply with the reason; the lock source is shown", async () => {
    backend({ preview: () => json({ ...PREVIEW, window_soon: "23:45-00:15", schedule_times: [{ setting: "schedule.train_time", time: "07:00" }],
      ops_lock_checked: true, ops_lock_source: "derived", ops_locks: [{ env: "DF_OPS_LOCK", path: "D:\\run\\OPS_LOCK" }] }) });
    await mount();
    await preview();
    fireEvent.change(input("pr-purchase-input"), { target: { value: PURCH } });
    fireEvent.change(input("pr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
    expect((screen.getByTestId("pr-apply") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("pr-window-soon").textContent).toContain("23:45-00:15");
    expect(screen.getByTestId("pr-sched").textContent).toContain("schedule.train_time 07:00");
    expect(screen.getByTestId("pr-lock-checked").textContent).toContain("suy ra từ thư mục dữ liệu");
    expect(screen.getByTestId("pr-locks").textContent).toContain("DF_OPS_LOCK=D:\\run\\OPS_LOCK; nút bị từ chối");
  });

  it("409 PRESET_BUSY names the saved schedule time; 409 OPERATIONS_LOCK_HELD lists the lock file", async () => {
    let which = 0;
    const errs = [
      () => json({ code: "PRESET_BUSY", vi: "Đang bận (máy chủ)", en: "Busy", detail: "x", params: { window: null, window_soon: null, schedule_times: [{ setting: "schedule.refresh_deadline", time: "11:30" }], jobs: [], stale_ignored: [] } }, 409),
      () => json({ code: "OPERATIONS_LOCK_HELD", vi: "Đang có khóa vận hành", en: "Locked", detail: "x", params: { locks: [{ env: "DF_OPS_LOCK", path: "D:\\run\\OPS_LOCK" }] } }, 409),
    ];
    backend({ apply: () => errs[which]() });
    await mount();
    await preview();
    const go = async () => {
      // type the texts that are SHOWN now (a 409 may have replaced them with the text of today)
      fireEvent.change(input("pr-purchase-input"), { target: { value: screen.getByTestId("pr-purchase-text").textContent! } });
      fireEvent.change(input("pr-input"), { target: { value: screen.getByTestId("pr-text").textContent! } });
      fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
      await act(async () => { fireEvent.click(screen.getByTestId("pr-apply")); });
    };
    await go();
    expect(await screen.findByText("Đang bận (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("bg-sched").textContent).toContain("schedule.refresh_deadline 11:30");
    which = 1; await go();
    expect(await screen.findByText("Đang có khóa vận hành")).toBeTruthy();
    expect(screen.getByTestId("bg-locks").textContent).toContain("DF_OPS_LOCK = D:\\run\\OPS_LOCK");
  });

  it("already applied: says so and offers no typed text", async () => {
    backend({ preview: () => json({ ...PREVIEW, changed: false, changes: [], kept_higher: [], not_undoable: [], needs_purchase_confirm: false, purchase_keys: [], flows: [{ flow: "d1", from: true, to: true, ready: true, reasons: [] }] }) });
    await mount();
    await preview();
    expect(screen.getByTestId("pr-already")).toBeTruthy();
    expect(screen.getByTestId("pr-no-keys")).toBeTruthy();
    expect(screen.queryByTestId("pr-input")).toBeNull();
    expect((screen.getByTestId("pr-apply") as HTMLButtonElement).disabled).toBe(true);
  });

  it("409 errors read well: flow not ready (reasons), changed elsewhere, busy, confirm text of today (typed text cleared, not resent)", async () => {
    let which = 0;
    const NEXT = "AP-DUNG-PRESET-LGBM-CHOT-2026-11-24";
    const errs = [
      () => json({ code: "PRESET_FLOW_NOT_READY", vi: "Có luồng chưa sẵn sàng (máy chủ)", en: "Flow not ready", detail: "d1", params: { flows: [{ flow: "d1", ready: false, reasons: [{ code: "SQL_NOT_VALIDATED" }] }] } }, 409),
      () => json({ code: "SETTINGS_CHANGED_ELSEWHERE", vi: "Giá trị đã đổi sau lần xem trước (máy chủ)", en: "Changed", detail: "preset lgbm-chot" }, 409),
      () => json({ code: "PRESET_BUSY", vi: "Đang bận (máy chủ)", en: "Busy", detail: "x", params: { window: "00:45-03:45", jobs: [{ job_type: "D1_SYNC" }], stale_ignored: [] } }, 409),
      () => json({ code: "PRESET_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirm", detail: `type ${NEXT}`, params: { confirm_text: NEXT } }, 409),
      () => json({ code: "PRESET_PURCHASE_CONFIRM_REQUIRED", vi: "Cần chữ ảnh hưởng mua hàng", en: "Purchase text", detail: "x",
        params: { confirm_purchase: "DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-24", purchase_keys: ["model.num_threads"] } }, 409),
    ];
    const calls = backend({ apply: () => errs[which]() });
    await mount();
    await preview();
    const go = async () => {
      // type the texts that are SHOWN now (a 409 may have replaced them with the text of today)
      fireEvent.change(input("pr-purchase-input"), { target: { value: screen.getByTestId("pr-purchase-text").textContent! } });
      fireEvent.change(input("pr-input"), { target: { value: screen.getByTestId("pr-text").textContent! } });
      fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
      await act(async () => { fireEvent.click(screen.getByTestId("pr-apply")); });
    };
    await go();
    expect(await screen.findByText("Có luồng chưa sẵn sàng (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("pr-flows-error").textContent).toContain("d1");
    expect(screen.getByTestId("pr-flows-error").textContent).toContain("SQL_NOT_VALIDATED");
    expect(screen.getByTestId("pr-confirm-area")).toBeTruthy();                          // the form is kept
    which = 1; await go();
    expect(await screen.findByText("Giá trị đã đổi sau lần xem trước (máy chủ)")).toBeTruthy();
    which = 2; await go();
    expect(await screen.findByText("Đang bận (máy chủ)")).toBeTruthy();
    expect(screen.getByTestId("gp-busy-window").textContent).toContain("00:45-03:45");
    which = 3; await go();
    expect(await screen.findByText("Cần xác nhận")).toBeTruthy();
    expect(screen.getByTestId("pr-text").textContent).toBe(NEXT);
    expect(input("pr-input").value).toBe("");
    which = 4; await go();
    expect(await screen.findByText("Cần chữ ảnh hưởng mua hàng")).toBeTruthy();
    expect(screen.getByTestId("pr-purchase-text").textContent).toBe("DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-24");
    expect(input("pr-purchase-input").value).toBe("");
    expect((screen.getByTestId("pr-apply") as HTMLButtonElement).disabled).toBe(true);
    expect(posts(calls).filter((c) => c.url.endsWith("/apply"))).toHaveLength(5);              // never resent by itself
  });

  it("a flow that could not be switched on after the commit: 'partial' with the flow errors, the warning and the undo warning", async () => {
    backend({ apply: () => json({ preset: "lgbm-chot", applied: [{ section: "model", key: "num_threads", from: 0, to: 4 }], kept_higher: [],
      flows: [{ flow: "d1", from: false, to: false, ready: false, reasons: [{ code: "SQL_NOT_VALIDATED" }] }], undo_audit_id: 78, not_undoable: [],
      partial: true, flow_errors: [{ flow: "d1", code: "FLOW_NOT_READY", detail: "d1 not validated" }], warnings: ["PRESET_FLOWS_NOT_ALL_ON"], undo_warning: { code: "PRESET_UNDO_SETTINGS_ONLY", vi: "Hoàn tác chỉ đặt lại cài đặt; các luồng lịch đã bật bởi bộ cấu hình giữ nguyên, tắt ở trang Lịch chạy.", en: "An undo only restores settings; flows switched on stay on." } }) });
    await mount();
    await preview();
    fireEvent.change(input("pr-purchase-input"), { target: { value: PURCH } });
    fireEvent.change(input("pr-input"), { target: { value: TEXT } });
    fireEvent.change(screen.getByTestId("pr-reason"), { target: { value: "phuong an chot 1.3.1 theo chu du an" } });
    await act(async () => { fireEvent.click(screen.getByTestId("pr-apply")); });
    const p = await screen.findByTestId("pr-partial");
    expect(p.textContent).toContain("Cài đặt đã lưu nhưng có luồng chưa bật được");
    expect(screen.getByTestId("pr-flow-errors").textContent).toContain("d1");
    expect(screen.getByTestId("pr-flow-errors").textContent).toContain("FLOW_NOT_READY");
    expect(screen.getByTestId("pr-warn-PRESET_FLOWS_NOT_ALL_ON").textContent).toContain("Chưa bật hết các luồng");
    expect(screen.getByTestId("pr-result-flows").textContent).toContain("chưa bật được");
    expect(screen.getByTestId("pr-undo-warning")).toBeTruthy();
  });
});
