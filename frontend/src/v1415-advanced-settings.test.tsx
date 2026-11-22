import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import AdvancedSettings from "./pages/AdvancedSettings";

// 1.4.15 (lot 2): page "Cài đặt nâng cao". Backend mocked (unit, fake fetch, no network): the page shows what GET
// /api/settings-advanced says, previews before every write, asks the confirmation of the highest risk and sends
// compare-and-set requests (changes + expected + confirm_text + reason + acknowledged).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const TEXTS = { HIGH: "DOI-CAI-DAT-AN-2026-11-23", PURCHASE: "DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-23" };
const e = (section: string, key: string, risk: string, label: string, value: unknown, constraints: any, extra: any = {}) => ({
  section, key, risk, editable: ["LOW", "HIGH", "PURCHASE"].includes(risk), label_vi: label, label_en: `${label} (en)`, desc_vi: `Mô tả ${label}`, desc_en: `Desc ${label}`,
  only_increase: false, path_rule: null, reason_code: null, own_path: null, exportable: true, constraints, value, default: value, ...extra,
});
const ENTRIES = [
  e("horizons", "max_forecast_rows", "HIGH", "Số dòng dự báo tối đa", 200000, { type: "int", ge: 1000, le: 5000000 }),
  e("model", "num_threads", "PURCHASE", "Số luồng CPU khi học", 0, { type: "int", ge: 0, le: 64 }),
  e("model", "feature_discount", "PURCHASE", "Đặc trưng giảm giá", null, { type: "bool | None" }),
  e("model", "feature_open_hours", "READONLY", "Giờ mở bán làm đầu vào", true, { type: "bool" }, { reason_code: "REG_SET_BY_TRAINING", own_path: "training run" }),
  e("import", "column_aliases", "HIGH", "Tên cột thay thế", { sku: ["ma"] }, { type: "dict[str, list[str]]" }),
  e("schedule", "report_weekday", "LOW", "Thứ chạy báo cáo", 1, { type: "int", ge: 1, le: 7 }),
  e("schedule", "report_time", "LOW", "Giờ chạy báo cáo", "08:00", { type: "str" }),
  e("schedule", "d1_enabled", "OWN_PATH", "Bật D-1", true, { type: "bool" }, { reason_code: "REG_FLOW_SWITCH", own_path: "PUT /api/schedules/{flow} (Schedules.tsx:237)" }),
  e("daily_forecast", "log_retention_days", "HIGH", "Số ngày giữ nhật ký", 90, { type: "int", ge: 7 }, { only_increase: true }),
  e("daily_forecast", "report_subdir", "LOW", "Thư mục báo cáo", "reports", { type: "str" }, { path_rule: "NAME" }),
  e("sel2_pipeline", "spike_cleaning", "PURCHASE", "Lọc đơn đột biến", true, { type: "bool" }),
  e("sel2_pipeline", "spike_e4_n", "PURCHASE", "Ngưỡng N đơn đột biến", 5, { type: "int", ge: 1, le: 100 }),
  e("sel2_pipeline", "export_mode", "LOW", "Kiểu xuất", "A", { type: "Literal['A', 'B']", choices: ["A", "B"] }),
];
const HIST = [
  { id: 5, at: "2026-11-22T02:00:00+00:00", action: "SETTINGS_ADVANCED_APPLIED", undone: false,
    details: { changes: [{ section: "schedule", key: "report_weekday", risk: "LOW", from: 4, to: 1 }], reason: "doi thu bao cao", risk: "LOW" } },
  { id: 4, at: "2026-11-21T02:00:00+00:00", action: "SETTINGS_ADVANCED_APPLIED", undone: true,
    details: { changes: [{ section: "horizons", key: "max_forecast_rows", risk: "HIGH", from: 100000, to: 200000 }], reason: "da hoan tac", risk: "HIGH" } },
];
const state = (over: any = {}) => ({ entries: ENTRIES, versions: { schedule: 3 }, confirm_texts: TEXTS, reason_min_length: 10, max_keys: 10, history: HIST, ...over });

interface Call { url: string; method: string; body: any }
const ORDER: Record<string, number> = { LOW: 1, HIGH: 2, PURCHASE: 3 };
function backend(o: { state?: any; busy?: any; apply?: () => Response; undo?: () => Response } = {}) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method, body });
    if (u === "/api/settings-advanced" && method === "GET") return json(o.state ?? state());
    if (u === "/api/settings-advanced/preview") {
      const rows = body.changes.map((c: any) => {
        const en = ENTRIES.find((x) => x.section === c.section && x.key === c.key)!;
        return { section: c.section, key: c.key, risk: en.risk, from: en.value, to: c.value, changed: JSON.stringify(en.value) !== JSON.stringify(c.value) };
      });
      const changed = rows.filter((r: any) => r.changed);
      const top = changed.reduce((a: string | null, r: any) => (!a || ORDER[r.risk] > ORDER[a] ? r.risk : a), null);
      const spike = changed.some((r: any) => r.section === "sel2_pipeline" && ["spike_cleaning", "spike_e4_n"].includes(r.key));
      return json({ changes: rows, changed: changed.map((r: any) => `${r.section}.${r.key}`), max_risk: top, needs_confirm_text: top === "HIGH" || top === "PURCHASE",
        needs_reason: top === "HIGH" || top === "PURCHASE", needs_acknowledged: changed.some((r: any) => r.risk === "LOW"), confirm_text: top ? (TEXTS as any)[top] ?? null : null,
        warnings: [...(changed.length ? [] : ["NO_CHANGE"]), ...(top === "PURCHASE" ? ["PURCHASE_NUMBERS_CHANGE"] : []), ...(spike ? ["SPIKE_OWNER_DECISION"] : [])],
        notes: ["APPLIES_FROM_NEXT_RUN", "UNDO_SETTINGS_ONLY"], busy: o.busy ?? { busy: false, window: null, jobs: [], stale_ignored: [] }, versions: {} });
    }
    if (u === "/api/settings-advanced/apply") return o.apply ? o.apply() : json({ applied: body.changes, versions: {}, audit_id: 9 });
    if (u === "/api/settings-advanced/undo") return o.undo ? o.undo() : json({ undone: [], versions: {}, audit_id: 10 });
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const mount = async () => { const r = await act(async () => render(wrap(<AdvancedSettings />))); await screen.findByTestId("adv-preview"); return r; };
const row = (k: string) => screen.getByTestId(`adv-row-${k}`);
const input = (k: string) => screen.getByTestId(`adv-in-${k}`) as HTMLInputElement;
const preview = async () => { await act(async () => { fireEvent.click(screen.getByTestId("adv-preview")); }); };
const apply = () => screen.getByTestId("adv-apply") as HTMLButtonElement;

describe("1.4.15 advanced settings page", () => {
  it("lists every registry field by section with label, consequence, current value, default and the risk as text", async () => {
    const calls = backend();
    await mount();
    expect(calls[0]).toMatchObject({ url: "/api/settings-advanced", method: "GET" });
    expect(screen.getAllByText("Cài đặt nâng cao").length).toBeGreaterThan(0);
    for (const sec of ["Khoảng dự báo", "Mô hình", "Import Excel", "Lịch chạy", "Dự báo hằng ngày", "SEL2 (số dùng để mua hàng)"]) expect(screen.getByText(sec), sec).toBeTruthy();
    const r = row("horizons.max_forecast_rows");
    expect(r.textContent).toContain("Số dòng dự báo tối đa");
    expect(r.textContent).toContain("Mô tả Số dòng dự báo tối đa");               // the consequence text
    expect(within(r).getByTestId("risk-HIGH").textContent).toBe("Rủi ro cao");   // text, not colour only
    expect(within(row("model.num_threads")).getByTestId("risk-PURCHASE").textContent).toBe("Ảnh hưởng mua hàng");
    expect(within(row("schedule.report_weekday")).getByTestId("risk-LOW").textContent).toBe("Rủi ro thấp");
    expect(screen.getByTestId("adv-cur-horizons.max_forecast_rows").textContent).toBe("200000");
    expect(screen.getByTestId("adv-cur-model.feature_discount").textContent).toBe("—");   // null is not shown as 0
    expect(screen.getByTestId("adv-cur-sel2_pipeline.spike_cleaning").textContent).toBe("Bật");
    expect(posts(calls)).toEqual([]);
  });

  it("read-only and own-path fields have no control, show the reason and where they are changed; the window start is pointed to", async () => {
    backend();
    await mount();
    expect(screen.queryByTestId("adv-in-model.feature_open_hours")).toBeNull();
    expect(screen.getByTestId("adv-why-model.feature_open_hours").textContent).toContain("Do lần học ghi — chỉ xem.");
    expect(screen.getByTestId("adv-why-model.feature_open_hours").textContent).toContain("training run");
    expect(within(row("model.feature_open_hours")).getByTestId("risk-READONLY").textContent).toBe("Chỉ xem");
    expect(screen.queryByTestId("adv-in-schedule.d1_enabled")).toBeNull();
    const why = screen.getByTestId("adv-why-schedule.d1_enabled");
    expect(why.textContent).toContain("Công tắc luồng: đổi ở trang Lịch chạy");
    expect(why.querySelector("a")!.getAttribute("href")).toBe("/schedules");
    expect(within(row("schedule.d1_enabled")).getByTestId("risk-OWN_PATH").textContent).toBe("Đổi ở nơi khác");
    const note = screen.getByTestId("adv-window-note");
    expect(note.textContent).toContain("window_start_date");
    expect(note.querySelector("a")!.getAttribute("href")).toBe("/config");
  });

  it("the spike fields: the warning box is in the SEL2 section and again in the preview", async () => {
    backend();
    await mount();
    expect(screen.getByTestId("adv-spike-box").textContent).toContain("áp dụng từ lượt học kế tiếp");
    expect(screen.getByTestId("adv-spike-box").textContent).toContain("hoàn tác chỉ trả cài đặt, không trả lại kết quả đã học");
    fireEvent.change(input("sel2_pipeline.spike_e4_n"), { target: { value: "6" } });
    await preview();
    expect(screen.getByTestId("adv-spike-warning").textContent).toContain("thay đổi dữ liệu học của mô hình");
    // PURCHASE: the purchase text, not the HIGH one
    expect(screen.getByTestId("adv-confirm-text").textContent).toBe(TEXTS.PURCHASE);
    expect(screen.getByTestId("adv-warn-PURCHASE_NUMBERS_CHANGE")).toBeTruthy();
    fireEvent.change(screen.getByTestId("adv-confirm-input"), { target: { value: TEXTS.HIGH } });
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "chu du an doi N" } });
    expect(apply().disabled).toBe(true);
  });

  it("LOW: edit -> preview (no write) -> the 'I understand' box -> Apply sends changes + expected + acknowledged", async () => {
    const calls = backend();
    await mount();
    const btn = screen.getByTestId("adv-preview") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "3" } });
    expect(btn.disabled).toBe(false);
    await preview();
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/settings-advanced/preview", body: { changes: [{ section: "schedule", key: "report_weekday", value: 3 }] } });
    expect(screen.getByTestId("adv-diff-schedule.report_weekday").textContent).toContain("3");
    expect(screen.getByTestId("adv-note-APPLIES_FROM_NEXT_RUN").textContent).toBe("Áp dụng từ lượt chạy kế tiếp.");
    expect(screen.queryByTestId("adv-confirm-input")).toBeNull();
    expect(apply().disabled).toBe(true);
    fireEvent.click(screen.getByTestId("adv-ack"));
    expect(apply().disabled).toBe(false);
    await act(async () => { fireEvent.click(apply()); });
    const ap = posts(calls).find((c) => c.url === "/api/settings-advanced/apply")!;
    expect(ap.body).toEqual({ changes: [{ section: "schedule", key: "report_weekday", value: 3 }], expected: { schedule: { report_weekday: 1 } }, acknowledged: true });
    expect(await screen.findByText("Đã áp dụng (backend xác nhận).")).toBeTruthy();
  });

  it("HIGH / PURCHASE: the exact text of the level (shown) and a reason of at least reason_min_length before Apply is enabled", async () => {
    const calls = backend();
    await mount();
    fireEvent.change(input("horizons.max_forecast_rows"), { target: { value: "300000" } });
    await preview();
    expect(screen.getByTestId("adv-confirm-text").textContent).toBe(TEXTS.HIGH);
    expect(screen.queryByTestId("adv-ack")).toBeNull();
    expect(screen.getByTestId("adv-max-risk").textContent).toContain("Rủi ro cao");
    fireEvent.change(screen.getByTestId("adv-confirm-input"), { target: { value: TEXTS.HIGH.toLowerCase() } });
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "chu du an dong y" } });
    expect(apply().disabled).toBe(true);                                      // wrong text
    fireEvent.change(screen.getByTestId("adv-confirm-input"), { target: { value: TEXTS.HIGH } });
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "ngan" } });
    expect(apply().disabled).toBe(true);                                      // reason too short
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "chu du an dong y" } });
    expect(apply().disabled).toBe(false);
    await act(async () => { fireEvent.click(apply()); });
    const ap = posts(calls).find((c) => c.url === "/api/settings-advanced/apply")!;
    expect(ap.body).toEqual({ changes: [{ section: "horizons", key: "max_forecast_rows", value: 300000 }], expected: { horizons: { max_forecast_rows: 200000 } },
      confirm_text: TEXTS.HIGH, reason: "chu du an dong y" });
  });

  it("a mixed change (LOW + HIGH) needs the text, the reason AND the box; a bool stays a bool, a number a number", async () => {
    const calls = backend();
    await mount();
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "2" } });
    fireEvent.change(input("horizons.max_forecast_rows"), { target: { value: "250000" } });
    fireEvent.click(input("sel2_pipeline.spike_cleaning"));
    await preview();
    fireEvent.change(screen.getByTestId("adv-confirm-input"), { target: { value: TEXTS.PURCHASE } });   // the highest level is PURCHASE
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "chu du an dong y" } });
    expect(apply().disabled).toBe(true);                                      // the box of the LOW field is missing
    fireEvent.click(screen.getByTestId("adv-ack"));
    expect(apply().disabled).toBe(false);
    await act(async () => { fireEvent.click(apply()); });
    const ap = posts(calls).find((c) => c.url === "/api/settings-advanced/apply")!;
    expect(ap.body.expected).toEqual({ schedule: { report_weekday: 1 }, horizons: { max_forecast_rows: 200000 }, sel2_pipeline: { spike_cleaning: true } });
    expect(typeof ap.body.expected.sel2_pipeline.spike_cleaning).toBe("boolean");
    expect(ap.body.changes.find((c: any) => c.key === "spike_cleaning").value).toBe(false);
    expect(ap.body.changes.find((c: any) => c.key === "report_weekday").value).toBe(2);
    expect(ap.body).toMatchObject({ confirm_text: TEXTS.PURCHASE, acknowledged: true });
  });

  it("a busy preview locks Apply and says why (night window, running jobs, overdue jobs left out)", async () => {
    backend({ busy: { busy: true, detail: "x", window: "23:45-00:15", jobs: [{ id: "J-1", job_type: "D1_SYNC", status: "RUNNING", last_mark: null }],
      stale_ignored: [{ id: "J-0", job_type: "OLD_JOB", status: "RUNNING" }] } });
    await mount();
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "2" } });
    await preview();
    fireEvent.click(screen.getByTestId("adv-ack"));
    expect(apply().disabled).toBe(true);
    expect(screen.getByTestId("gp-busy-window").textContent).toBe("Đang trong khung đêm: 23:45-00:15.");
    expect(screen.getByTestId("gp-busy-jobs").textContent).toBe("Job đang chạy: D1_SYNC.");
    expect(screen.getByTestId("gp-stale-ignored").textContent).toBe("Job quá hạn được bỏ qua khi kiểm tra bận: OLD_JOB.");
  });

  it("409 SETTINGS_CHANGED_ELSEWHERE names the field with its current value, writes nothing more, and 'Tải lại' reloads", async () => {
    const calls = backend({ apply: () => json({ code: "SETTINGS_CHANGED_ELSEWHERE", vi: "Đổi ở nơi khác", en: "Changed elsewhere", detail: "schedule.report_weekday",
      params: { current: { schedule: { report_weekday: 5 } }, versions: { schedule: 4 } } }, 409) });
    await mount();
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "3" } });
    await preview();
    fireEvent.click(screen.getByTestId("adv-ack"));
    await act(async () => { fireEvent.click(apply()); });
    expect(await screen.findByText("Cài đặt đã bị đổi ở nơi khác")).toBeTruthy();
    expect(screen.getByTestId("adv-conflict-keys").textContent).toBe("Thứ chạy báo cáo: hiện tại 5");
    expect(screen.queryByTestId("adv-confirm-area")).toBeNull();
    expect(posts(calls).filter((c) => c.url.endsWith("/apply"))).toHaveLength(1);
    const gets = () => calls.filter((c) => c.method === "GET").length;
    const before = gets();
    await act(async () => { fireEvent.click(screen.getByText("Tải lại")); });
    await waitFor(() => expect(gets()).toBe(before + 1));
    await waitFor(() => expect(screen.queryByTestId("adv-conflict")).toBeNull());
    expect(posts(calls).filter((c) => c.url.endsWith("/apply"))).toHaveLength(1);       // never forced
  });

  it("409 SETTINGS_ADVANCED_BUSY keeps the form and shows the window / jobs from params", async () => {
    backend({ apply: () => json({ code: "SETTINGS_ADVANCED_BUSY", vi: "Đang bận", en: "Busy", detail: "x",
      params: { window: "00:45-03:45", jobs: [{ job_type: "TRAIN" }], stale_ignored: [] } }, 409) });
    await mount();
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "3" } });
    await preview();
    fireEvent.click(screen.getByTestId("adv-ack"));
    await act(async () => { fireEvent.click(apply()); });
    expect(await screen.findByText("Đang bận")).toBeTruthy();
    expect(screen.getByTestId("gp-busy-window").textContent).toContain("00:45-03:45");
    expect(screen.getByTestId("gp-busy-jobs").textContent).toContain("TRAIN");
    expect(input("schedule.report_weekday").value).toBe("3");
    expect(screen.getByTestId("adv-confirm-area")).toBeTruthy();
  });

  it("SETTINGS_ADVANCED_CONFIRM_REQUIRED with params.confirm_text updates the text to type and clears what was typed", async () => {
    const NEXT = "DOI-CAI-DAT-AN-2026-11-24";
    const calls = backend({ apply: () => json({ code: "SETTINGS_ADVANCED_CONFIRM_REQUIRED", vi: "Cần xác nhận", en: "Confirmation required", detail: `type ${NEXT}`,
      params: { confirm_text: NEXT, risk: "HIGH" } }, 409) });
    await mount();
    fireEvent.change(input("horizons.max_forecast_rows"), { target: { value: "300000" } });
    await preview();
    fireEvent.change(screen.getByTestId("adv-confirm-input"), { target: { value: TEXTS.HIGH } });
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "chu du an dong y" } });
    await act(async () => { fireEvent.click(apply()); });
    await waitFor(() => expect(screen.getByTestId("adv-confirm-text").textContent).toBe(NEXT));
    expect((screen.getByTestId("adv-confirm-input") as HTMLInputElement).value).toBe("");
    expect(apply().disabled).toBe(true);
    expect(posts(calls).filter((c) => c.url.endsWith("/apply"))).toHaveLength(1);        // not resent by itself
  });

  it("422 from the server is shown with its own bilingual message", async () => {
    backend({ apply: () => json({ code: "SETTINGS_ADVANCED_INVALID_VALUE", vi: "Giá trị mới không hợp lệ (máy chủ)", en: "Invalid value (server)", detail: "schedule: x" }, 422) });
    await mount();
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "3" } });
    await preview();
    fireEvent.click(screen.getByTestId("adv-ack"));
    await act(async () => { fireEvent.click(apply()); });
    expect(await screen.findByText("Giá trị mới không hợp lệ (máy chủ)")).toBeTruthy();
    expect(screen.getByText("SETTINGS_ADVANCED_INVALID_VALUE")).toBeTruthy();
  });

  it("a retention can only be increased: the rule is written on the field and a decrease blocks the preview", async () => {
    const calls = backend();
    await mount();
    expect(screen.getByTestId("adv-incr-daily_forecast.log_retention_days").textContent).toContain("Chỉ được tăng");
    const btn = screen.getByTestId("adv-preview") as HTMLButtonElement;
    fireEvent.change(input("daily_forecast.log_retention_days"), { target: { value: "30" } });
    expect(screen.getByTestId("adv-bad-daily_forecast.log_retention_days").textContent).toBe("Chỉ được tăng, không được giảm.");
    expect(btn.disabled).toBe(true);
    fireEvent.change(input("daily_forecast.log_retention_days"), { target: { value: "120" } });
    expect(btn.disabled).toBe(false);
    await preview();
    expect(posts(calls)[0].body).toEqual({ changes: [{ section: "daily_forecast", key: "log_retention_days", value: 120 }] });
  });

  it("controls follow the type: out-of-range number, invalid JSON, choice list and a nullable boolean", async () => {
    const calls = backend();
    await mount();
    const btn = screen.getByTestId("adv-preview") as HTMLButtonElement;
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "9" } });      // le 7
    expect(screen.getByTestId("adv-bad-schedule.report_weekday").textContent).toBe("Ngoài khoảng cho phép.");
    expect(btn.disabled).toBe(true);
    fireEvent.change(input("schedule.report_weekday"), { target: { value: "1" } });      // back to the running value: no change
    expect(btn.disabled).toBe(true);
    expect(screen.getByTestId("adv-count").textContent).toBe("Chưa có thay đổi nào so với giá trị đang chạy.");
    fireEvent.change(input("import.column_aliases"), { target: { value: "{not json" } });
    expect(screen.getByTestId("adv-bad-import.column_aliases").textContent).toBe("Không đọc được: nhập JSON hợp lệ.");
    expect(btn.disabled).toBe(true);
    fireEvent.change(input("import.column_aliases"), { target: { value: "{\"sku\": [\"ma\", \"code\"]}" } });
    expect(btn.disabled).toBe(false);
    fireEvent.change(input("sel2_pipeline.export_mode"), { target: { value: "1" } });     // choice index 1 = "B"
    fireEvent.change(input("model.feature_discount"), { target: { value: "false" } });   // nullable bool: "", on, off
    await preview();
    expect(posts(calls)[0].body.changes).toEqual([
      { section: "import", key: "column_aliases", value: { sku: ["ma", "code"] } }, { section: "sel2_pipeline", key: "export_mode", value: "B" },
      { section: "model", key: "feature_discount", value: false },
    ]);
  });

  it("recent changes: undo goes through the preview (values before the change), the confirmation and POST /undo by audit_id; an undone row has no button", async () => {
    const calls = backend();
    await mount();
    expect(screen.getByTestId("adv-log-5").textContent).toContain("Thứ chạy báo cáo: 4 → 1");
    expect(screen.queryByTestId("adv-undo-4")).toBeNull();
    expect(screen.getByTestId("adv-log-4").textContent).toContain("Đã hoàn tác");
    await act(async () => { fireEvent.click(screen.getByTestId("adv-undo-5")); });
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/settings-advanced/preview", body: { changes: [{ section: "schedule", key: "report_weekday", value: 4 }] } });
    expect(screen.getByTestId("adv-confirm-area").textContent).toContain("Hoàn tác lần đổi 5");
    expect(apply().disabled).toBe(true);                                      // the same gate: the "I understand" box (LOW)
    fireEvent.click(screen.getByTestId("adv-ack"));
    await act(async () => { fireEvent.click(apply()); });
    const un = posts(calls).find((c) => c.url === "/api/settings-advanced/undo")!;
    expect(un.body).toEqual({ audit_id: 5, acknowledged: true });
    expect(posts(calls).some((c) => c.url.endsWith("/apply"))).toBe(false);
    expect(await screen.findByText("Đã hoàn tác cài đặt (backend xác nhận).")).toBeTruthy();
  });

  it("undo of a HIGH change needs the typed text and a reason", async () => {
    const hist = [{ id: 8, at: "2026-11-22T02:00:00+00:00", action: "SETTINGS_ADVANCED_APPLIED", undone: false,
      details: { changes: [{ section: "horizons", key: "max_forecast_rows", risk: "HIGH", from: 100000, to: 200000 }], reason: "x", risk: "HIGH" } }];
    const calls = backend({ state: state({ history: hist }) });
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("adv-undo-8")); });
    expect(apply().disabled).toBe(true);
    fireEvent.change(screen.getByTestId("adv-confirm-input"), { target: { value: TEXTS.HIGH } });
    fireEvent.change(screen.getByTestId("adv-reason"), { target: { value: "hoan tac vi sai" } });
    await act(async () => { fireEvent.click(apply()); });
    expect(posts(calls).find((c) => c.url.endsWith("/undo"))!.body).toEqual({ audit_id: 8, confirm_text: TEXTS.HIGH, reason: "hoan tac vi sai" });
  });

  it("load error: message and 'Tải lại'", async () => {
    globalThis.fetch = vi.fn(async () => json({ code: "INTERNAL_ERROR", vi: "Lỗi máy chủ", en: "Server error" }, 500)) as any;
    await act(async () => { render(wrap(<AdvancedSettings />)); });
    expect(await screen.findByText("Lỗi máy chủ")).toBeTruthy();
    expect(screen.getByText("Tải lại")).toBeTruthy();
  });
});
