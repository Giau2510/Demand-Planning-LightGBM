import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import DataPolicyGuarded from "./components/DataPolicyGuarded";
import Config from "./pages/Config";

// 1.4.15 (GD-L1): card "Chính sách đồng bộ lịch sử (thay đổi có xác nhận)" on the forecast configuration page.
// Backend mocked (unit, fake fetch, no network): the card only shows what the API says and sends compare-and-set requests.
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const FIELDS = { window_start_date: "2026-01-01", history_change_policy: "FOLLOW_SOURCE", history_day_check: true, source_time_travel_hours: 160,
  training_start_rule: "WINDOW_START" };
const DEFAULTS = { window_start_date: "2026-01-01", history_change_policy: "KEEP_OBSERVED_LINES", history_day_check: true, source_time_travel_hours: 160,
  training_start_rule: "WINDOW_START" };
const CONFIRM = "DOI-CHINH-SACH-DU-LIEU-2026-11-22";
const HIST = [
  { id: 56, changed_at: "2026-10-30T02:21:00+00:00", note: "OWNER DECISION KEEP_OBSERVED_LINES -> FOLLOW_SOURCE", values: { ...FIELDS },
    previous_values: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES" } },
  { id: 40, changed_at: "2026-10-01T02:21:00+00:00", note: "older", values: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES", source_time_travel_hours: 72 },
    previous_values: { ...FIELDS, history_change_policy: "KEEP_OBSERVED_LINES", source_time_travel_hours: 48 } },
];
const state = (over: any = {}) => ({ fields: FIELDS, defaults: DEFAULTS, version: 56, confirm_text: CONFIRM, reason_min_length: 10,
  high_risk_fields: ["history_change_policy", "window_start_date", "training_start_rule"], locked_fields: ["window_start_date"],
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
      const HIGH = ["history_change_policy", "window_start_date", "training_start_rule"];
      const high = Object.keys(patch).some((k) => HIGH.includes(k));
      return json({ before: Object.fromEntries(Object.keys(patch).map((k) => [k, (st.fields as any)[k]])), after: patch, changed: Object.keys(patch),
        high_risk: high, needs_confirm_text: high, needs_acknowledged: Object.keys(patch).some((k) => !HIGH.includes(k)),
        impact: null, warnings: [] });
    }
    if (u === "/api/data-policy/guarded" && method === "POST") {
      if (o.apply) return o.apply();
      st = state({ fields: { ...st.fields, ...body.patch }, version: st.version + 1 });
      return json({ applied: body.patch, version: st.version });
    }
    if (u === "/api/settings/data_policy" && method === "PUT") return json(body);
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
    expect(screen.getByTestId("gp-window-locked").textContent).toBe("Chưa cho đổi ở bản này: đổi ngày này làm D-1 dừng chờ kiểm tra lại nguồn rồi nạp lại toàn bộ dữ liệu từ ngày mới (có thể ghi đè dữ liệu 2025). Cần quy trình riêng có chủ dự án duyệt.");
    expect(screen.queryByText(/dữ liệu trước ngày này vẫn được lưu/i)).toBeNull();
    // why it is locked and how to change it: plain words, with the verified facts
    const why = screen.getByTestId("gp-window-why").textContent!;
    expect(why).toContain("Vì sao khóa và cách đổi khi cần");
    for (const fact of ["BQ_VALIDATION_REQUIRED", "Kiểm tra dữ liệu toàn kỳ", "1,4–1,7 GB", "735 giây", "1,27 GB", "MUỘN hơn", "SỚM hơn", "GHI ĐÈ", "dữ liệu 2025", "MISSING",
      "báo phiên điều phối", "sao lưu trước", "ngoài khung đêm", "ghi lại giá trị cũ"]) expect(why, fact).toContain(fact);
    // the fifth field: the model-input start rule
    expect((screen.getByTestId("gp-tsr-WINDOW_START") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId("gp-running-training_start_rule")).toBeTruthy();
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
    const un = screen.getByTestId("gp-undo-note-preview").textContent!;
    expect(un).toContain("Hoàn tác chỉ trả lại cài đặt, không trả lại dữ liệu đã ghi.");
    expect(un).toContain('thẻ "Quay lại lần đồng bộ"');                      // the card by its real name (no "sync-rollback" jargon)
    expect(un).toContain("chỉ chắc chắn khi chưa có lần ghi nào sau đó");
    expect(un).not.toContain("sync-rollback");
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
    ["DATA_POLICY_UNKNOWN_FIELD", 422, "không thuộc 5 mục"], ["DATA_POLICY_BUSY", 409, "Hệ thống đang chạy job hoặc trong khung đêm 23:45-00:15 / 00:45-03:45; thử lại sau"],
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

  it("training_start_rule: running value + default, plain description, high-risk (text + reason), impact as sentences with the effective dates", async () => {
    const calls = backend({ preview: (patch) => ({ before: { training_start_rule: "WINDOW_START" }, after: patch, changed: ["training_start_rule"], high_risk: true,
      needs_confirm_text: true, needs_acknowledged: false, busy: { busy: false },
      impact: { kind: "TRAINING_START", window_start_date: "2026-01-01", coverage_start: "2026-03-05", effective_current: "2026-01-01", effective_after: "2026-03-05",
        delta_days: 63, applies_from: "NEXT_DATA_WINDOW_READ" },
      notes: ["TRAINING_START_CHANGES_MODEL_INPUT"], warnings: [] }) });
    await mount();
    const run = screen.getByTestId("gp-running-training_start_rule").textContent!;
    expect(run).toContain("Đang chạy: Ngày bắt đầu cửa sổ dữ liệu (mặc định)");
    expect(run).toContain("Mặc định của mã: Ngày bắt đầu cửa sổ dữ liệu (mặc định)");
    const desc = screen.getByTestId("gp-tsr-desc").textContent!;
    expect(desc).toContain("Đổi cửa sổ dữ liệu ĐẦU VÀO");
    expect(desc).toContain("KHÔNG xóa dữ liệu đã lưu");
    expect(desc).toContain("NGAY ở lần đọc cửa sổ dữ liệu kế tiếp");
    expect(desc).toContain("KHÔNG đổi số dự báo SEL2 đang dùng");
    expect(desc).toContain("model đang dùng không bị học lại");
    expect((screen.getByTestId("gp-tsr-WINDOW_START") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByTestId("gp-tsr-OPEN_HOURS_COVERAGE"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(posts(calls)[0].body).toEqual({ patch: { training_start_rule: "OPEN_HOURS_COVERAGE" } });
    expect(screen.getByTestId("gp-impact-train").textContent).toBe(
      "Có hiệu lực ngay ở lần đọc cửa sổ dữ liệu kế tiếp (không cần chờ học lại). Ngày hiệu lực của cửa sổ đầu vào: 01/01/2026 → 05/03/2026. Cửa sổ ngắn hơn 63 ngày.");
    expect(screen.getByTestId("gp-note-TRAINING_START_CHANGES_MODEL_INPUT").textContent).toContain("đổi cửa sổ dữ liệu đầu vào");
    // high risk: the typed text + a reason are needed
    const apply = screen.getByTestId("gp-apply") as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "chu du an dong y doi" } });
    expect(apply.disabled).toBe(false);
    await act(async () => { fireEvent.click(apply); });
    const ap = posts(calls).find((c) => c.url === "/api/data-policy/guarded")!;
    expect(ap.body).toMatchObject({ patch: { training_start_rule: "OPEN_HOURS_COVERAGE" }, expected: { training_start_rule: "WINDOW_START" }, confirm_text: CONFIRM });
  });

  it("training_start_rule impact without an estimate (coverage_start / effective dates null) says it cannot be estimated", async () => {
    backend({ preview: (patch) => ({ before: {}, after: patch, changed: ["training_start_rule"], high_risk: true, needs_confirm_text: true, needs_acknowledged: false,
      impact: { kind: "TRAINING_START", window_start_date: "2026-01-01", coverage_start: null, effective_current: "2026-01-01", effective_after: null, delta_days: null,
        applies_from: "NEXT_DATA_WINDOW_READ" },
      notes: ["NO_ESTIMATE_TIMEOUT", "NO_ESTIMATE_ERROR"], warnings: [] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-tsr-OPEN_HOURS_COVERAGE"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(screen.getByTestId("gp-impact-train").textContent).toBe("Có hiệu lực ngay ở lần đọc cửa sổ dữ liệu kế tiếp (không cần chờ học lại). Không ước tính được ngày hiệu lực, có thể do quá lâu.");
    expect(screen.getByTestId("gp-note-NO_ESTIMATE_TIMEOUT").textContent).toContain("Không ước tính được tác động");
    expect(screen.getByTestId("gp-note-NO_ESTIMATE_ERROR").textContent).toContain("Ước tính tác động bị lỗi");
    // the raw English busy detail is not shown any more
    expect(screen.queryByTestId("gp-busy-detail")).toBeNull();
  });

  it("a patch of policy + training start rule shows both estimates from impacts (the training one is only there; impact is the first)", async () => {
    const held = { kind: "HELD_LINES", active_held_lines: 7, capped: false, applies_from: "NEXT_D1" };
    const train = { kind: "TRAINING_START", window_start_date: "2026-01-01", coverage_start: "2026-03-05", effective_current: "2026-01-01", effective_after: "2026-03-05",
      delta_days: 63, applies_from: "NEXT_DATA_WINDOW_READ" };
    backend({ preview: (patch) => ({ before: {}, after: patch, changed: ["history_change_policy", "training_start_rule"], high_risk: true, needs_confirm_text: true,
      needs_acknowledged: false, impact: held, impacts: [held, train], notes: [], warnings: [], busy: { busy: false } }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-policy-KEEP_OBSERVED_LINES"));
    fireEvent.click(screen.getByTestId("gp-tsr-OPEN_HOURS_COVERAGE"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(screen.getByTestId("gp-impact-held").textContent).toBe("Áp dụng từ lần D-1 kế tiếp. Đang giữ 7 dòng.");
    expect(screen.getByTestId("gp-impact-train").textContent).toContain("Cửa sổ ngắn hơn 63 ngày.");
  });

  it("impact null with the estimate only in impacts is still shown (and impact alone still works for older servers)", async () => {
    const train = { kind: "TRAINING_START", window_start_date: "2026-01-01", coverage_start: "2026-03-05", effective_current: "2026-01-01", effective_after: "2026-03-05",
      delta_days: 63, applies_from: "NEXT_DATA_WINDOW_READ" };
    backend({ preview: (patch) => ({ before: {}, after: patch, changed: ["training_start_rule"], high_risk: true, needs_confirm_text: true, needs_acknowledged: false,
      impact: null, impacts: [train], notes: [], warnings: [] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-tsr-OPEN_HOURS_COVERAGE"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(screen.getByTestId("gp-impact-train").textContent).toContain("05/03/2026");
    expect(screen.queryByTestId("gp-impact-held")).toBeNull();
  });

  it("a busy preview locks Apply and shows why (night window, running jobs, overdue jobs left out); warning codes are sentences", async () => {
    backend({ preview: (patch) => ({ before: {}, after: patch, changed: ["history_day_check"], high_risk: false, needs_confirm_text: false, needs_acknowledged: true,
      busy: { busy: true, detail: "night window", window: "23:45-00:15", jobs: [{ id: "J-1", job_type: "D1_SYNC", status: "RUNNING", last_mark: "2026-11-23T00:50:00Z" }, { id: "J-2", job_type: "TRAIN", status: "RUNNING" }],
      stale_ignored: [{ id: "J-0", job_type: "OLD_JOB", status: "RUNNING" }] },
      impact: null, notes: [], warnings: ["NO_IMPACT_ESTIMATE:history_change_policy,training_start_rule", "NO_CHANGE"] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-day-check"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.click(screen.getByTestId("gp-ack"));
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(true);        // locked although the box is ticked
    expect(screen.getByTestId("gp-busy-window").textContent).toBe("Đang trong khung đêm: 23:45-00:15.");
    expect(screen.getByTestId("gp-busy-jobs").textContent).toBe("Job đang chạy: D1_SYNC, TRAIN.");
    expect(screen.getByTestId("gp-stale-ignored").textContent).toBe("Job quá hạn được bỏ qua khi kiểm tra bận: OLD_JOB.");
    const w = screen.getByTestId("gp-warnings").textContent!;
    expect(w).toContain("Chưa có ước tính ảnh hưởng cho: Khi nguồn bỏ một dòng đơn đã nạp, Quy tắc ngày bắt đầu dữ liệu cho mô hình.");
    expect(w).toContain("Giá trị mới giống hệt giá trị đang chạy.");
    expect(w).not.toContain("NO_CHANGE");
  });

  it("a preview that is not busy leaves Apply enabled, and overdue jobs left out are still told", async () => {
    backend({ preview: (patch) => ({ before: {}, after: patch, changed: ["history_day_check"], high_risk: false, needs_confirm_text: false, needs_acknowledged: true,
      busy: { busy: false, window: null, jobs: [], stale_ignored: ["OLD_JOB"] }, impact: null, notes: [], warnings: [] }) });
    await mount();
    fireEvent.click(screen.getByTestId("gp-day-check"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.click(screen.getByTestId("gp-ack"));
    expect((screen.getByTestId("gp-apply") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("gp-busy")).toBeNull();
    expect(screen.getByTestId("gp-stale-ignored")).toBeTruthy();
  });

  it("undo restores only the fields in changed_fields of that row", async () => {
    const hist = [{ id: 70, changed_at: "2026-11-02T02:21:00+00:00", note: "x", values: { ...FIELDS }, changed_fields: ["history_day_check"],
      previous_values: { ...FIELDS, history_day_check: false, source_time_travel_hours: 50 } }];
    const calls = backend({ state: state({ history: hist }) });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("gp-undo-70")); });
    expect((screen.getByTestId("gp-day-check") as HTMLInputElement).checked).toBe(false);         // restored
    expect((screen.getByTestId("gp-hours") as HTMLInputElement).value).toBe("160");               // not in changed_fields: untouched
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    expect(posts(calls)[0].body).toEqual({ patch: { history_day_check: false } });
  });

  it("the old card: training_start_rule is display only and points to the new card; the note lists the 5 items that Save / Reset never change", async () => {
    backend();
    await act(async () => { render(wrap(<Config />)); });
    const note = await screen.findByTestId("cfg-guarded-note");
    const oldCard = note.closest("section") as HTMLElement;
    const sel = within(oldCard).getByTestId("cfg-training-start-rule") as HTMLSelectElement;
    expect(sel.disabled).toBe(true);
    expect(within(oldCard).getByTestId("cfg-tsr-moved").textContent).toContain("Sửa ở thẻ");
    const box = within(oldCard).getByTestId("cfg-guarded-reset-note");
    expect(box.textContent).toContain("KHÔNG đặt lại");
    const items = Array.from(box.querySelectorAll("li")).map((li) => li.textContent);
    expect(items).toHaveLength(5);
    for (const name of ["Khi nguồn bỏ một dòng đơn đã nạp", "Ngày bắt đầu cửa sổ dữ liệu mô hình", "Kiểm lại ngày cũ sau mỗi lần nạp D-1",
      "Số giờ lùi tối đa khi đối chiếu bản cũ của nguồn", "Quy tắc ngày bắt đầu dữ liệu cho mô hình"]) {
      expect(items.some((i) => i!.includes(name) && i!.includes("sửa ở thẻ bên dưới")), name).toBe(true);
    }
  });

  it("the old card: Save shows 'field: old -> new' in a confirmation box and sends only after it; no change = nothing is sent", async () => {
    const calls = backend();
    await act(async () => { render(wrap(<Config />)); });
    const note = await screen.findByTestId("cfg-guarded-note");
    const oldCard = note.closest("section") as HTMLElement;
    const save = () => within(oldCard).getByRole("button", { name: "Lưu" });
    const puts = () => calls.filter((c) => c.method === "PUT");
    // nothing changed: nothing is sent, the user is told
    await act(async () => { fireEvent.click(save()); });
    expect(puts()).toHaveLength(0);
    expect(screen.getByText("Không có thay đổi nào để lưu (chưa gửi gì lên máy chủ).")).toBeTruthy();
    expect(screen.queryByTestId("cfg-save-diff")).toBeNull();
    // a real change: the box lists it; Cancel sends nothing
    const lag = within(oldCard).getAllByRole("spinbutton")[0] as HTMLInputElement;
    expect(lag.value).toBe("1");
    fireEvent.change(lag, { target: { value: "5" } });
    await act(async () => { fireEvent.click(save()); });
    expect(screen.getByTestId("cfg-save-diff").textContent).toBe("Độ trễ dữ liệu tối đa (ngày): 1 → 5");
    await act(async () => { fireEvent.click(screen.getByText("Hủy")); });
    expect(puts()).toHaveLength(0);
    expect(screen.queryByTestId("cfg-save-diff")).toBeNull();
    // confirm: now it is sent
    await act(async () => { fireEvent.click(save()); });
    await act(async () => { fireEvent.click(screen.getByText("Lưu các thay đổi này")); });
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toMatchObject({ url: "/api/settings/data_policy" });
    expect(puts()[0].body.max_data_lag_days).toBe(5);
  });

  it("the old 'Chính sách dữ liệu' card of the Config page has the note, and the new card sits right below it", async () => {
    backend();
    const r = await act(async () => render(wrap(<Config />)));
    const note = await screen.findByTestId("cfg-guarded-note");
    expect(note.textContent).toBe("5 mục chính sách đồng bộ chỉnh ở thẻ bên dưới");
    expect(screen.getByTestId("cfg-old-undo-note").textContent).toContain("chưa có nút hoàn tác trong 1.4.15");     // 1.4.15 lot 6
    const oldCard = note.closest("section")!;
    expect(oldCard.textContent).toContain("Chính sách dữ liệu");
    const next = oldCard.nextElementSibling!;
    expect(next.textContent).toContain("Chính sách đồng bộ lịch sử (thay đổi có xác nhận)");
    // the old card still has its six fields and its own Save / Reset
    expect(oldCard.textContent).toContain("Khôi phục mặc định");
    expect(r.container.querySelectorAll(".guarded-policy")).toHaveLength(1);
  });
});
