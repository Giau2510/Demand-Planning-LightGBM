import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import DataPolicyGuarded from "./components/DataPolicyGuarded";
import Config from "./pages/Config";

// 1.4.15 (GD-L1): card "Chính sách đồng bộ lịch sử (thay đổi có xác nhận)" on the forecast configuration page.
// Backend mocked (unit, fake fetch, no network): the card only shows what the API says and sends compare-and-set requests.
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const FIELDS = { window_start_date: "2026-01-01", history_change_policy: "FOLLOW_SOURCE", history_day_check: true, source_time_travel_hours: 160 };
const DEFAULTS = { window_start_date: "2026-01-01", history_change_policy: "KEEP_OBSERVED_LINES", history_day_check: true, source_time_travel_hours: 160 };
const CONFIRM = "DOI-CHINH-SACH-DU-LIEU-2026-11-22";
const HIST = [
  { id: 56, changed_at: "2026-10-30T02:21:00+00:00", note: "OWNER DECISION KEEP_OBSERVED_LINES -> FOLLOW_SOURCE", values: { ...FIELDS },
    previous_values: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES" } },
  { id: 40, changed_at: "2026-10-01T02:21:00+00:00", note: "older", values: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES", source_time_travel_hours: 72 },
    previous_values: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES", source_time_travel_hours: 48 } },
];
const state = (over: any = {}) => ({ fields: FIELDS, defaults: DEFAULTS, version: 56, confirm_text: CONFIRM, reason_min_length: 10,
  high_risk_fields: ["history_change_policy", "window_start_date"], locked_fields: ["window_start_date"],
  locked_reason_code: "WINDOW_START_CHANGES_RELOAD", history: HIST, ...over });

interface Call { url: string; method: string; body: any }
/** answers: GET state; preview: function of the patch; apply: response / status. Every call is recorded. */
function backend(o: { state?: any; preview?: (patch: any) => any; apply?: () => Response } = {}) {
  const calls: Call[] = [];
  let st = o.state ?? state();
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method, body });
    if (u === "/api/data-policy/guarded" && method === "GET") return json(st);
    if (u === "/api/data-policy/guarded/preview") {
      const patch = body.patch;
      if (o.preview) return json(o.preview(patch));
      const high = "history_change_policy" in patch || "window_start_date" in patch;
      return json({ before: Object.fromEntries(Object.keys(patch).map((k) => [k, (st.fields as any)[k]])), after: patch, changed: Object.keys(patch),
        high_risk: high, needs_confirm_text: high, needs_acknowledged: Object.keys(patch).some((k) => k !== "history_change_policy" && k !== "window_start_date"),
        impact: null, warnings: [] });
    }
    if (u === "/api/data-policy/guarded" && method === "POST") {
      if (o.apply) return o.apply();
      st = state({ fields: { ...st.fields, ...body.patch }, version: st.version + 1 });
      return json({ applied: body.patch, version: st.version });
    }
    if (u === "/api/settings") return json({ data_policy: { stale_check_sources: ["DEMO"], max_data_lag_days: 1, late_data_lookback_days: 3, min_date: null,
      training_start_rule: "WINDOW_START", price_outlier_factor: 5 } });
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const mount = async () => { const r = await act(async () => render(wrap(<DataPolicyGuarded />))); await screen.findByTestId("gp-preview"); return r; };

describe("1.4.15 guarded data-policy card", () => {
  it("shows the values of GET /api/data-policy/guarded with the running value and the code default beside each control", async () => {
    const calls = backend();
    await mount();
    expect(calls[0]).toMatchObject({ url: "/api/data-policy/guarded", method: "GET" });
    expect(screen.getByText("Chính sách đồng bộ lịch sử (thay đổi có xác nhận)")).toBeTruthy();
    expect((screen.getByTestId("gp-policy-FOLLOW_SOURCE") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByTestId("gp-day-check") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("gp-hours") as HTMLInputElement).value).toBe("160");
    // window_start_date: read-only value with the explanation, no input
    expect(screen.getByTestId("gp-window-value").textContent).toBe("01/01/2026");
    expect(screen.queryByLabelText("Ngày bắt đầu cửa sổ dữ liệu mô hình")).toBeNull();
    expect(screen.getByTestId("gp-window-locked").textContent).toBe("Chưa cho đổi ở bản này: đổi ngày này làm D-1 dùng cho kiểm tra lại nguồn rồi nạp lại toàn bộ dữ liệu từ ngày mới (có thể ghi đè dữ liệu 2025). Cần quy trình riêng có chủ dự án duyệt.");
    expect(screen.queryByText(/dữ liệu trước ngày này vẫn được lưu/i)).toBeNull();
    // policy label: code default first (never shown as the standard value), then the running value and the 30/10 decision
    const run = screen.getByTestId("gp-running-history_change_policy").textContent!;
    expect(run).toContain("Mặc định của mã: Giữ dòng đã thấy (KEEP_OBSERVED_LINES). Đang chạy: Theo nguồn (FOLLOW_SOURCE).");
    expect(run).toContain("Đang áp dụng theo quyết định chủ dự án 30/10.");
    // no reset button, nothing sent yet
    expect(screen.queryByText("Khôi phục mặc định")).toBeNull();
    expect(posts(calls)).toEqual([]);
    // log table with undo buttons
    expect(screen.getByText("Nhật ký 5 dòng gần nhất")).toBeTruthy();
    expect(screen.getByTestId("gp-log-56").textContent).toContain("OWNER DECISION");
    expect(screen.getByTestId("gp-undo-40").textContent).toContain("Đặt lại giá trị trước đó");
  });

  it("loading and load-error states", async () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {})) as any;
    const r = render(wrap(<DataPolicyGuarded />));
    expect(r.container.querySelector(".loading")).toBeTruthy();
    r.unmount();
    globalThis.fetch = vi.fn(async () => json({ code: "INTERNAL_ERROR", vi: "Lỗi máy chủ", en: "Server error" }, 500)) as any;
    await act(async () => { render(wrap(<DataPolicyGuarded />)); });
    expect(await screen.findByText("Lỗi máy chủ")).toBeTruthy();
    expect(screen.getByText("Tải lại")).toBeTruthy();
  });

  it("no change disables the preview; a change sends exactly {patch} with only the changed fields", async () => {
    const calls = backend();
    await mount();
    const btn = screen.getByTestId("gp-preview") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("gp-nochange")).toBeTruthy();
    fireEvent.click(screen.getByTestId("gp-day-check"));
    expect(btn.disabled).toBe(false);
    fireEvent.change(screen.getByTestId("gp-hours"), { target: { value: "200" } });   // out of 1..168
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("gp-hours-invalid")).toBeTruthy();
    fireEvent.change(screen.getByTestId("gp-hours"), { target: { value: "120" } });
    await act(async () => { fireEvent.click(btn); });
    const pv = posts(calls)[0];
    expect(pv.url).toBe("/api/data-policy/guarded/preview");
    expect(pv.body).toEqual({ patch: { history_day_check: false, source_time_travel_hours: 120 } });
    expect(screen.getByTestId("gp-diff-source_time_travel_hours").textContent).toContain("120");
  });

  it("window_start_date is never editable and never in the patch / expected, even when an undo row carries another date", async () => {
    const hist = [{ id: 60, changed_at: "2026-11-01T02:21:00+00:00", note: "x", values: { ...FIELDS },
      previous_values: { ...FIELDS, window_start_date: "2025-06-01", source_time_travel_hours: 100 } }];
    const calls = backend({ state: state({ history: hist }) });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("gp-undo-60")); });
    expect(screen.getByTestId("gp-window-value").textContent).toBe("01/01/2026");
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(posts(calls)[0].body).toEqual({ patch: { source_time_travel_hours: 100 } });
  });

  it("the 30/10 decision line shows only when the running value is FOLLOW_SOURCE; the default is never shown as the standard value", async () => {
    backend({ state: state({ fields: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES" } }) });
    await mount();
    const run = screen.getByTestId("gp-running-history_change_policy").textContent!;
    expect(run).toContain("Đang chạy: Giữ dòng đã thấy (KEEP_OBSERVED_LINES)");
    expect(run).not.toContain("quyết định chủ dự án 30/10");
  });

  it("a high-risk field needs the exact confirm text of the day and a reason of at least 10 characters before Apply is enabled", async () => {
    const calls = backend({ preview: (patch) => ({ before: { history_change_policy: "FOLLOW_SOURCE" }, after: patch, changed: ["history_change_policy"],
      high_risk: true, needs_confirm_text: true, needs_acknowledged: false, impact: { kind: "HELD_LINES", active_held_lines: 12345, capped: true, applies_from: "NEXT_D1" },
      notes: ["APPLIES_AT_NEXT_D1", "KEEP_OBSERVED_LINES_HOLDS_REMOVED_LINES", "UNDO_SETTINGS_ONLY"], warnings: ["Se giu lai dong nguon bo"] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(calls.filter((c) => c.method === "POST")[0].body).toEqual({ patch: { history_change_policy: "KEEP_OBSERVED_LINES" } });
    expect(screen.getByTestId("gp-warnings").textContent).toContain("Se giu lai dong nguon bo");
    // impact + notes as sentences (never raw JSON)
    const imp = screen.getByTestId("gp-impact").textContent!;
    expect(imp).toContain("Áp dụng từ lần D-1 kế tiếp. Đang giữ 12.345+ dòng.");
    expect(imp).toContain("Nếu đặt Giữ dòng đã thấy: dòng nguồn bỏ vẫn được giữ.");
    expect(imp).not.toContain("{");
    expect(screen.getByTestId("gp-undo-note-preview").textContent).toBe("Hoàn tác chỉ trả lại cài đặt, không trả lại dữ liệu đã ghi (dữ liệu cần sync-rollback).");
    expect(screen.getByTestId("gp-undo-note-log").textContent).toContain("Hoàn tác chỉ trả lại cài đặt");
    expect(screen.getByTestId("gp-confirm-text").textContent).toBe(CONFIRM);
    expect(screen.queryByTestId("gp-ack")).toBeNull();
    const apply = screen.getByTestId("gp-apply") as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM.toLowerCase() } });
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "quyet dinh chu du an" } });
    expect(apply.disabled).toBe(true);                                                    // wrong text
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "ngan" } });
    expect(apply.disabled).toBe(true);                                                    // reason too short
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "quyet dinh chu du an" } });
    expect(apply.disabled).toBe(false);
    await act(async () => { fireEvent.click(apply); });
    const ap = posts(calls).find((c) => c.url === "/api/data-policy/guarded")!;
    expect(ap.body).toMatchObject({ patch: { history_change_policy: "KEEP_OBSERVED_LINES" }, expected: { history_change_policy: "FOLLOW_SOURCE" },
      confirm_text: CONFIRM, reason: "quyet dinh chu du an" });
    expect(await screen.findByText("Đã áp dụng (backend xác nhận).")).toBeTruthy();
    // reloaded: the form shows the new running value, the confirmation area is gone
    await waitFor(() => expect(screen.queryByTestId("gp-confirm-area")).toBeNull());
    expect((screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES") as HTMLInputElement).checked).toBe(true);
  });

  it("a low-risk field only needs the 'Tôi hiểu thay đổi này' box; the reason is optional", async () => {
    const calls = backend();
    await mount();
    fireEvent.click(screen.getByTestId("gp-day-check"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(screen.queryByTestId("gp-confirm-input")).toBeNull();
    expect(screen.getByText("Lý do (tùy chọn)")).toBeTruthy();
    const apply = screen.getByTestId("gp-apply") as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("gp-ack"));
    expect(apply.disabled).toBe(false);
    await act(async () => { fireEvent.click(apply); });
    const ap = posts(calls).find((c) => c.url === "/api/data-policy/guarded")!;
    expect(ap.body).toEqual({ patch: { history_day_check: false }, expected: { history_day_check: true }, acknowledged: true });
  });

  it("409 SETTINGS_CHANGED_ELSEWHERE shows the message and params.current / params.version, does not overwrite, and 'Tải lại' reloads", async () => {
    const calls = backend({ apply: () => json({ code: "SETTINGS_CHANGED_ELSEWHERE", vi: "Đã đổi ở nơi khác", en: "Changed elsewhere", detail: "history_day_check",
      params: { current: { ...FIELDS, history_day_check: false }, version: 57 } }, 409) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-day-check"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.click(screen.getByTestId("gp-ack"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
    expect(await screen.findByText("Chính sách đã bị đổi ở nơi khác")).toBeTruthy();
    const cur = screen.getByTestId("gp-conflict-current").textContent!;
    expect(cur).toContain("(v57)");
    expect(cur).toContain("Kiểm lại ngày cũ sau mỗi lần nạp D-1: Tắt");
    expect(screen.queryByTestId("gp-confirm-area")).toBeNull();
    // exactly one write attempt (the refused apply); nothing was retried or forced
    expect(posts(calls).filter((c) => c.url === "/api/data-policy/guarded")).toHaveLength(1);
    const gets = () => calls.filter((c) => c.method === "GET").length;
    const before = gets();
    await act(async () => { fireEvent.click(screen.getByText("Tải lại")); });
    await waitFor(() => expect(gets()).toBe(before + 1));
    await waitFor(() => expect(screen.queryByTestId("gp-conflict")).toBeNull());
    expect(posts(calls).filter((c) => c.url === "/api/data-policy/guarded")).toHaveLength(1);
  });

  it("DATA_POLICY_CONFIRM_REQUIRED (409, detail) is shown by code, keeps the form and the preview, and is not the 'changed elsewhere' message", async () => {
    backend({ apply: () => json({ code: "DATA_POLICY_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirmation required", detail: "acknowledged = true", params: {} }, 409) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-day-check"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.click(screen.getByTestId("gp-ack"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
    expect((await screen.findByTestId("gp-error")).textContent).toContain("DATA_POLICY_CONFIRM_REQUIRED");
    expect(screen.getByTestId("gp-error-detail").textContent).toBe("acknowledged = true");
    expect(screen.queryByTestId("gp-conflict")).toBeNull();
    expect(screen.getByTestId("gp-confirm-area")).toBeTruthy();
  });

  it.each([["DATA_POLICY_INVALID_VALUE", 422, "Giá trị mới không hợp lệ"], ["DATA_POLICY_EXPECTED_REQUIRED", 422, "Thiếu giá trị cũ"],
    ["DATA_POLICY_UNKNOWN_FIELD", 422, "không thuộc 4 mục"], ["DATA_POLICY_BUSY", 409, "Hệ thống đang chạy job hoặc trong khung đêm 23:45-00:15 / 00:45-03:45; thử lại sau"],
    ["DATA_POLICY_FIELD_LOCKED", 422, "đang bị khóa"], ["NO_CHANGE", 400, "giống hệt giá trị đang chạy"]])(
    "%s (%i) is shown by its code with its own text", async (code, status, text) => {
      backend({ apply: () => json({ code, vi: "x", en: "x", detail: "d", params: {} }, status) });
      await mount();
      fireEvent.click(screen.getByTestId("gp-day-check"));
      await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
      fireEvent.click(screen.getByTestId("gp-ack"));
      await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
      const box = await screen.findByTestId("gp-error");
      expect(box.textContent).toContain(code);
      expect(box.textContent).toContain(text);
    });

  it("a mixed patch (high-risk + other field) needs the text, the reason AND the box; types are kept (boolean stays boolean, integer stays integer)", async () => {
    const calls = backend();
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    fireEvent.click(screen.getByTestId("gp-day-check"));
    fireEvent.change(screen.getByTestId("gp-hours"), { target: { value: "96" } });
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    const apply = screen.getByTestId("gp-apply") as HTMLButtonElement;
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "dong y chu du an roi" } });
    expect(apply.disabled).toBe(true);                       // the "I understand" box is still needed (needs_acknowledged)
    fireEvent.click(screen.getByTestId("gp-ack"));
    expect(apply.disabled).toBe(false);
    await act(async () => { fireEvent.click(apply); });
    const ap = posts(calls).find((c) => c.url === "/api/data-policy/guarded")!;
    expect(ap.body.patch).toEqual({ history_change_policy: "KEEP_OBSERVED_LINES", history_day_check: false, source_time_travel_hours: 96 });
    expect(ap.body.expected).toEqual({ history_change_policy: "FOLLOW_SOURCE", history_day_check: true, source_time_travel_hours: 160 });
    expect(typeof ap.body.expected.history_day_check).toBe("boolean");
    expect(typeof ap.body.patch.history_day_check).toBe("boolean");
    expect(Number.isInteger(ap.body.patch.source_time_travel_hours)).toBe(true);
    expect(ap.body.acknowledged).toBe(true);
    expect(ap.body.confirm_text).toBe(CONFIRM);
  });

  it("DATA_POLICY_BUSY keeps the form, the preview and what was typed (nothing is cleared)", async () => {
    backend({ apply: () => json({ code: "DATA_POLICY_BUSY", vi: "Bận", en: "Busy", detail: "job", params: {} }, 409) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-hours"));
    fireEvent.change(screen.getByTestId("gp-hours"), { target: { value: "100" } });
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.click(screen.getByTestId("gp-ack"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
    await screen.findByTestId("gp-error");
    expect(screen.queryByTestId("gp-conflict")).toBeNull();
    expect(screen.getByTestId("gp-confirm-area")).toBeTruthy();
    expect((screen.getByTestId("gp-hours") as HTMLInputElement).value).toBe("100");
    expect((screen.getByTestId("gp-ack") as HTMLInputElement).checked).toBe(true);
  });

  it("impact with no count (active_held_lines null) says so, not 0", async () => {
    backend({ preview: (patch) => ({ before: {}, after: patch, changed: ["history_change_policy"], high_risk: true, needs_confirm_text: true, needs_acknowledged: false,
      impact: { kind: "HELD_LINES", active_held_lines: null, capped: false, applies_from: "NEXT_D1" }, notes: [], warnings: [] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(screen.getByTestId("gp-impact-held").textContent).toBe("Áp dụng từ lần D-1 kế tiếp. Chưa ước tính được số dòng đang giữ.");
  });

  it("the minimum reason length comes from reason_min_length of the GET, and the reason is limited to 500 characters", async () => {
    backend({ state: state({ reason_min_length: 15 }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });
    const apply = screen.getByTestId("gp-apply") as HTMLButtonElement;
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "12345678901234" } });   // 14 < 15
    expect(apply.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "123456789012345" } });  // 15
    expect(apply.disabled).toBe(false);
    expect((screen.getByTestId("gp-reason") as HTMLTextAreaElement).maxLength).toBe(500);
  });

  it("'Đặt lại giá trị trước đó' fills the form with previous_values, writes nothing, and still needs the preview and the confirmation", async () => {
    const calls = backend();
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("gp-undo-40")); });
    expect(posts(calls)).toEqual([]);
    expect((screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("gp-hours") as HTMLInputElement).value).toBe("48");        // previous_values (48), not values (72)
    expect(screen.getByTestId("gp-filled")).toBeTruthy();
    expect(screen.queryByTestId("gp-apply")).toBeNull();                                  // no shortcut: apply only after the preview
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(posts(calls)[0]).toMatchObject({ url: "/api/data-policy/guarded/preview", body: { patch: { history_change_policy: "KEEP_OBSERVED_LINES", source_time_travel_hours: 48 } } });
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(true);   // high risk: text + reason still needed
    expect(posts(calls)).toHaveLength(1);
  });

  it("undo of the newest row (values = the running values) fills the values BEFORE it, so something changes and the preview is enabled", async () => {
    backend();
    await mount();
    expect((screen.getByTestId("gp-preview") as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { fireEvent.click(screen.getByTestId("gp-undo-56")); });
    expect((screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("gp-policy-FOLLOW_SOURCE") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByTestId("gp-preview") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("gp-nochange")).toBeNull();
  });

  it("the confirmation text shown and matched is the confirm_text of the newest preview (a preview after midnight), not the one of the GET", async () => {
    const NEXT = "DOI-CHINH-SACH-DU-LIEU-2026-11-23";
    const calls = backend({ preview: (patch) => ({ before: { history_change_policy: "FOLLOW_SOURCE" }, after: patch, changed: ["history_change_policy"], high_risk: true,
      needs_confirm_text: true, needs_acknowledged: false, confirm_text: NEXT, impact: null, warnings: [] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(screen.getByTestId("gp-confirm-text").textContent).toBe(NEXT);
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "quyet dinh chu du an" } });
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });   // the old day's text
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: NEXT } });
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(false);
    await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
    expect(posts(calls).find((c) => c.url === "/api/data-policy/guarded")!.body.confirm_text).toBe(NEXT);
  });

  it("DATA_POLICY_CONFIRM_REQUIRED with params.confirm_text updates the text to type, clears what was typed and does not resend by itself", async () => {
    const NEXT = "DOI-CHINH-SACH-DU-LIEU-2026-11-23";
    const calls = backend({ apply: () => json({ code: "DATA_POLICY_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirmation required",
      detail: `type ${NEXT}`, params: { confirm_text: NEXT } }, 409) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "quyet dinh chu du an" } });
    await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
    await screen.findByTestId("gp-error");
    await waitFor(() => expect(screen.getByTestId("gp-confirm-text").textContent).toBe(NEXT));
    expect((screen.getByTestId("gp-confirm-input") as HTMLInputElement).value).toBe("");
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("gp-confirm-area")).toBeTruthy();
    expect(posts(calls).filter((c) => c.url === "/api/data-policy/guarded")).toHaveLength(1);   // not resent
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: NEXT } });
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(false);
  });

  it("the old 'Chính sách dữ liệu' card of the Config page has the note, and the new card sits right below it", async () => {
    backend();
    const r = await act(async () => render(wrap(<Config />)));
    const note = await screen.findByTestId("cfg-guarded-note");
    expect(note.textContent).toBe("4 mục chính sách đồng bộ chỉnh ở thẻ bên dưới");
    const oldCard = note.closest("section")!;
    expect(oldCard.textContent).toContain("Chính sách dữ liệu");
    const next = oldCard.nextElementSibling!;
    expect(next.textContent).toContain("Chính sách đồng bộ lịch sử (thay đổi có xác nhận)");
    // the old card still has its six fields and its own Save / Reset
    expect(oldCard.textContent).toContain("Khôi phục mặc định");
    expect(r.container.querySelectorAll(".guarded-policy")).toHaveLength(1);
  });
});
