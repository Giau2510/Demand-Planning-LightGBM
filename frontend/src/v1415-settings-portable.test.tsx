import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import SettingsPortable from "./components/SettingsPortable";

// 1.4.15 (lot 2B): card "Cài đặt: xuất / nhập" of the page "Hệ thống & sao lưu". Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const NHAP = "NHAP-CAI-DAT-2026-11-23";
const PURCHASE = "DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-23";
const HIGH = "DOI-CAI-DAT-AN-2026-11-23";
const DOC = { format: "df-settings", format_version: 1, app_version: "1.4.14", schema_version: 13, exported_at: "2026-11-22T10:00:00+00:00", sha256: "abc",
  sections: { daily_forecast: { report_subdir: "bao_cao" }, model: { feature_calendar: false }, horizons: { max_forecast_rows: 300000 }, import: { log_retention_days: 30 } } };
const row = (key: string, current: unknown, file: unknown, risk: string, changed = true) => ({ key, current, file, risk, changed });
const sec = (section: string, rows: any[], extra: any = {}) => ({ section, rows, changed: rows.filter((r) => r.changed).map((r) => r.key), max_risk: null, purchase_keys: [], high_keys: [],
  errors: [], selectable: true, default_selected: true, expected: `hash-${section}`, ...extra });
const PREVIEW = {
  sections: [
    sec("daily_forecast", [row("report_subdir", "reports", "bao_cao", "LOW")], { max_risk: "LOW" }),
    sec("model", [row("feature_calendar", true, false, "PURCHASE")], { max_risk: "PURCHASE", purchase_keys: ["model.feature_calendar"], default_selected: false }),
    sec("horizons", [row("max_forecast_rows", 200000, 300000, "HIGH")], { max_risk: "HIGH", high_keys: ["horizons.max_forecast_rows"], default_selected: false }),
    sec("import", [row("log_retention_days", 90, 30, "HIGH")], { max_risk: "HIGH", errors: ["RETENTION_DECREASE_NOT_ALLOWED: log_retention_days 90 -> 30"], selectable: false, default_selected: false }),
    sec("sel2_pipeline", [row("spike_e4_n", 5, 5, "PURCHASE", false)], { max_risk: null, selectable: false, default_selected: false }),
  ],
  sha256: "abc", file: { app_version: "1.4.14", schema_version: 13, exported_at: "2026-11-22T10:00:00+00:00", format_version: 1 },
  current: { app_version: "1.4.15", schema_version: 13 }, warnings: ["SETTINGS_IMPORT_APP_VERSION_DIFFERS", "SPIKE_NOT_TRANSFERRED"], notes: ["APPLIES_FROM_NEXT_RUN", "UNDO_SETTINGS_ONLY"],
  confirm_text: NHAP, reason_min_length: 10, needs_purchase_confirm: true, purchase_keys: ["model.feature_calendar"], confirm_purchase: PURCHASE,
  needs_high_confirm: true, high_keys: ["horizons.max_forecast_rows"], confirm_high: HIGH, spike_current: { spike_cleaning: true, spike_e4_n: 5 },
};
const HIST = [
  { id: 12, at: "2026-11-22T09:00:00+00:00", action: "SETTINGS_IMPORTED", entity_id: "IMP-aaa", undone: false,
    details: { import_id: "IMP-aaa", reason: "may moi cua tech", entries: [{ section: "daily_forecast", keys: { report_subdir: { from: "reports", to: "bao_cao" } } }] } },
  { id: 11, at: "2026-11-21T09:00:00+00:00", action: "SETTINGS_IMPORTED", entity_id: "IMP-bbb", undone: true,
    details: { import_id: "IMP-bbb", reason: "da hoan tac", entries: [{ section: "import", keys: { log_retention_days: { from: 30, to: 90 } } }] } },
  { id: 13, at: "2026-11-22T10:00:00+00:00", action: "SETTINGS_IMPORT_UNDONE", entity_id: "IMP-bbb", undone: false,
    details: { import_id: "IMP-bbb", reason: "hoan tac", entries: [], skipped: [{ section: "import", key: "log_retention_days", reason: "UNDO_SKIPPED_RETENTION_DECREASE", value: 90 }] } },
];

interface Call { url: string; method: string; body: any }
function backend(o: { preview?: () => Response; apply?: () => Response; undo?: () => Response; hist?: any[] } = {}) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method, body });
    if (u === "/api/settings-import/history") return json(o.hist ?? HIST);
    if (u === "/api/settings-import/preview") return o.preview ? o.preview() : json(PREVIEW);
    if (u === "/api/settings-import/apply") return o.apply ? o.apply() : json({ import_id: "IMP-new", audit_id: 20, entries: [{ section: "daily_forecast", history_id_before: 1, history_id_after: 2, keys: { report_subdir: { from: "reports", to: "bao_cao" } } }] });
    if (u === "/api/settings-import/undo") return o.undo ? o.undo() : json({ import_id: "IMP-aaa", entries: [], skipped: [] });
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const mount = async () => { await act(async () => { render(wrap(<SettingsPortable />)); }); await screen.findByTestId("sp-file"); };
const pickFile = async (content: string, name = "cai_dat_20261122_1000.json", size?: number) => {
  const f = new File([content], name, { type: "application/json" });
  if (size !== undefined) Object.defineProperty(f, "size", { value: size });
  await act(async () => { fireEvent.change(screen.getByTestId("sp-file"), { target: { files: [f] } }); });
};
const box = (id: string) => screen.getByTestId(id) as HTMLInputElement;

describe("1.4.15 settings export / import card", () => {
  it("export is a plain download of GET /api/settings-export with the 'no secrets' note and the short list of what is left out", async () => {
    const calls = backend();
    await mount();
    const a = screen.getByTestId("sp-export") as HTMLAnchorElement;
    expect(a.getAttribute("href")).toBe("/api/settings-export");
    expect(a.hasAttribute("download")).toBe(true);
    expect(screen.getByTestId("sp-export-note").textContent).toContain("không chứa bí mật, kết nối hay đường dẫn");
    expect(screen.getByTestId("sp-excluded").textContent).toContain("Không xuất:");
    expect(screen.getByTestId("sp-excluded").textContent).toContain("bí mật");
    expect(posts(calls)).toEqual([]);
  });

  it("choosing a file posts {document} to the preview and shows the sections: LOW selected by default, HIGH / PURCHASE not, errors named, warnings translated", async () => {
    const calls = backend();
    await mount();
    await pickFile(JSON.stringify(DOC));
    await screen.findByTestId("sp-preview");
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]).toMatchObject({ url: "/api/settings-import/preview", body: { document: DOC } });
    expect(box("sp-pick-daily_forecast").checked).toBe(true);
    expect(box("sp-pick-model").checked).toBe(false);          // PURCHASE: off by default
    expect(box("sp-pick-horizons").checked).toBe(false);       // HIGH: off by default
    expect(screen.getByTestId("sp-sec-model").textContent).toContain("Ảnh hưởng mua hàng");
    expect(screen.getByTestId("sp-sec-horizons").textContent).toContain("Rủi ro cao");
    expect(screen.getByTestId("sp-sec-model").textContent).toContain("BỎ chọn");
    expect(box("sp-pick-import").disabled).toBe(true);         // the section with an error cannot be picked
    expect(screen.getByTestId("sp-err-import").textContent).toContain("Số ngày lưu giữ chỉ được tăng");
    expect(screen.getByTestId("sp-err-import").textContent).toContain("log_retention_days 90 -> 30");
    expect(box("sp-pick-sel2_pipeline").disabled).toBe(true);  // nothing changes there
    expect(screen.getByTestId("sp-warn-SETTINGS_IMPORT_APP_VERSION_DIFFERS").textContent).toBe("Tệp được xuất từ phiên bản ứng dụng khác.");
    expect(screen.getByTestId("sp-warn-SPIKE_NOT_TRANSFERRED").textContent).toContain("spike_cleaning");
    expect(screen.getByTestId("sp-warnings").textContent).toContain("spike_e4_n = 5");
    expect(screen.getByTestId("sp-versions").textContent).toContain("1.4.14");
    expect(screen.getByTestId("sp-versions").textContent).toContain("1.4.15");
  });

  it("a file over 2 MB or a file that is not JSON is refused in the browser with a message, nothing is sent", async () => {
    const calls = backend();
    await mount();
    await pickFile("{}", "big.json", 3 * 1024 * 1024);
    expect(screen.getByTestId("sp-local-error").textContent).toContain("tối đa 2 MB");
    await pickFile("not json at all");                           // read by a FileReader after the act(): wait for the message
    await waitFor(() => expect(screen.getByTestId("sp-local-error").textContent).toContain("không phải JSON hợp lệ"));
    expect(posts(calls)).toEqual([]);
  });

  it("413 from the server is shown as 'too large'; a refused file names the keys", async () => {
    backend({ preview: () => json({ code: "SETTINGS_IMPORT_TOO_LARGE", vi: "Quá lớn", en: "Too large" }, 413) });
    await mount();
    await pickFile(JSON.stringify(DOC));
    expect((await screen.findByTestId("sp-too-large")).textContent).toContain("tối đa 2 MB");
    expect(screen.queryByTestId("sp-preview")).toBeNull();
    backend({ preview: () => json({ code: "SETTINGS_IMPORT_EXCLUDED_KEY", vi: "Tệp có trường không bao giờ được nhập", en: "Excluded key", detail: "bigquery.project_id",
      params: { keys: ["bigquery.project_id", "schedule.d1_enabled"] } }, 422) });
    await pickFile(JSON.stringify(DOC));
    expect(await screen.findByText("Tệp có trường không bao giờ được nhập")).toBeTruthy();
    expect(screen.getByTestId("sp-refused-keys").textContent).toContain("bigquery.project_id, schedule.d1_enabled");
    expect(screen.queryByTestId("sp-preview")).toBeNull();
  });

  it("LOW sections only: the NHAP text + a reason of at least reason_min_length, then Apply sends document + sections + expected hashes + text + reason", async () => {
    const calls = backend();
    await mount();
    await pickFile(JSON.stringify(DOC));
    await screen.findByTestId("sp-preview");
    expect(screen.getByTestId("sp-confirm-text").textContent).toBe(NHAP);
    expect(screen.queryByTestId("sp-high-input")).toBeNull();
    expect(screen.queryByTestId("sp-purchase-input")).toBeNull();
    const apply = screen.getByTestId("sp-apply") as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.change(box("sp-confirm-input"), { target: { value: NHAP } });
    fireEvent.change(screen.getByTestId("sp-reason"), { target: { value: "ngan" } });
    expect(apply.disabled).toBe(true);                         // reason too short
    fireEvent.change(screen.getByTestId("sp-reason"), { target: { value: "may moi cua tech" } });
    expect(apply.disabled).toBe(false);
    await act(async () => { fireEvent.click(apply); });
    const ap = posts(calls).find((c) => c.url === "/api/settings-import/apply")!;
    expect(ap.body).toEqual({ document: DOC, sections: ["daily_forecast"], expected: { daily_forecast: "hash-daily_forecast" }, confirm_text: NHAP, reason: "may moi cua tech" });
    expect(await screen.findByText("Đã nhập (mã IMP-new).")).toBeTruthy();
    expect(screen.getByTestId("sp-result").textContent).toContain("1");
    expect(screen.queryByTestId("sp-preview")).toBeNull();
  });

  it("ticking a HIGH / PURCHASE section asks for its own text too; Apply stays locked until each one matches", async () => {
    const calls = backend();
    await mount();
    await pickFile(JSON.stringify(DOC));
    await screen.findByTestId("sp-preview");
    fireEvent.click(box("sp-pick-horizons"));
    fireEvent.click(box("sp-pick-model"));
    expect(screen.getByTestId("sp-high-text").textContent).toBe(HIGH);
    expect(screen.getByTestId("sp-purchase-text").textContent).toBe(PURCHASE);
    const apply = screen.getByTestId("sp-apply") as HTMLButtonElement;
    fireEvent.change(box("sp-confirm-input"), { target: { value: NHAP } });
    fireEvent.change(screen.getByTestId("sp-reason"), { target: { value: "chu du an dong y nhap" } });
    expect(apply.disabled).toBe(true);
    fireEvent.change(box("sp-high-input"), { target: { value: HIGH } });
    expect(apply.disabled).toBe(true);                         // the purchase text is still missing
    fireEvent.change(box("sp-purchase-input"), { target: { value: HIGH } });   // wrong one
    expect(apply.disabled).toBe(true);
    fireEvent.change(box("sp-purchase-input"), { target: { value: PURCHASE } });
    expect(apply.disabled).toBe(false);
    await act(async () => { fireEvent.click(apply); });
    const ap = posts(calls).find((c) => c.url === "/api/settings-import/apply")!;
    expect(ap.body.sections).toEqual(["daily_forecast", "model", "horizons"]);
    expect(ap.body.expected).toEqual({ daily_forecast: "hash-daily_forecast", model: "hash-model", horizons: "hash-horizons" });
    expect(ap.body).toMatchObject({ confirm_text: NHAP, confirm_high: HIGH, confirm_purchase: PURCHASE, reason: "chu du an dong y nhap" });
  });

  it("409 SETTINGS_CHANGED_ELSEWHERE on apply names the sections, writes nothing more, and 'Xem trước lại' previews again", async () => {
    const calls = backend({ apply: () => json({ code: "SETTINGS_CHANGED_ELSEWHERE", vi: "Đổi ở nơi khác", en: "Changed elsewhere", detail: "daily_forecast",
      params: { current: { daily_forecast: "hash-new" } } }, 409) });
    await mount();
    await pickFile(JSON.stringify(DOC));
    await screen.findByTestId("sp-preview");
    fireEvent.change(box("sp-confirm-input"), { target: { value: NHAP } });
    fireEvent.change(screen.getByTestId("sp-reason"), { target: { value: "may moi cua tech" } });
    await act(async () => { fireEvent.click(screen.getByTestId("sp-apply")); });
    expect((await screen.findByTestId("sp-conflict")).textContent).toContain("daily_forecast");
    expect(posts(calls).filter((c) => c.url.endsWith("/apply"))).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByText("Xem trước lại")); });
    await waitFor(() => expect(posts(calls).filter((c) => c.url.endsWith("/preview"))).toHaveLength(2));
    expect(posts(calls).filter((c) => c.url.endsWith("/apply"))).toHaveLength(1);
  });

  it("409 SETTINGS_ADVANCED_BUSY shows the night window / running jobs and keeps the preview", async () => {
    backend({ apply: () => json({ code: "SETTINGS_ADVANCED_BUSY", vi: "Đang bận", en: "Busy", detail: "x", params: { window: "23:45-00:15", jobs: [{ job_type: "D1_SYNC" }], stale_ignored: [] } }, 409) });
    await mount();
    await pickFile(JSON.stringify(DOC));
    await screen.findByTestId("sp-preview");
    fireEvent.change(box("sp-confirm-input"), { target: { value: NHAP } });
    fireEvent.change(screen.getByTestId("sp-reason"), { target: { value: "may moi cua tech" } });
    await act(async () => { fireEvent.click(screen.getByTestId("sp-apply")); });
    expect(await screen.findByText("Đang bận")).toBeTruthy();
    expect(screen.getByTestId("gp-busy-window").textContent).toBe("Đang trong khung đêm: 23:45-00:15.");
    expect(screen.getByTestId("sp-preview")).toBeTruthy();
  });

  it("the history lists imports and undos; only an import that is not undone has the undo button; skipped keys are listed", async () => {
    backend();
    await mount();
    await screen.findByTestId("sp-history");
    expect(screen.getByTestId("sp-hist-12").textContent).toContain("report_subdir");
    expect(screen.getByTestId("sp-undo-12")).toBeTruthy();
    expect(screen.queryByTestId("sp-undo-11")).toBeNull();
    expect(screen.getByTestId("sp-hist-11").textContent).toContain("Đã hoàn tác");
    expect(screen.queryByTestId("sp-undo-13")).toBeNull();     // an undo row is not undone again
    expect(screen.getByTestId("sp-skipped-13").textContent).toContain("import.log_retention_days");
    expect(screen.getByTestId("sp-skipped-13").textContent).toContain("Giữ nguyên");
  });

  it("undo of an import whose keys need the PURCHASE / HIGH text: the keys are listed and the boxes are there BEFORE the first click", async () => {
    const hist = [{ id: 21, at: "2026-11-22T09:00:00+00:00", action: "SETTINGS_IMPORTED", entity_id: "IMP-zzz", undone: false,
      details: { import_id: "IMP-zzz", reason: "x", entries: [{ section: "model", keys: { num_threads: { from: 0, to: 2 } } }, { section: "horizons", keys: { max_forecast_rows: { from: 1, to: 2 } } }] } }];
    const calls = backend({ hist });
    await mount();
    await screen.findByTestId("sp-history");
    await act(async () => { fireEvent.click(screen.getByTestId("sp-undo-21")); });
    expect(screen.getByTestId("sp-undo-keys").textContent).toContain("model.num_threads, horizons.max_forecast_rows");
    const main = screen.getByTestId("sp-undo-text").textContent!;
    const purchase = screen.getByTestId("sp-undo-purchase-text").textContent!;            // model + horizons = PURCHASE by the section rule
    expect(purchase).toMatch(/^DOI-CAI-DAT-ANH-HUONG-MUA-HANG-\d{4}-\d{2}-\d{2}$/);
    const go = screen.getByTestId("sp-undo-apply") as HTMLButtonElement;
    fireEvent.change(box("sp-undo-input"), { target: { value: main } });
    fireEvent.change(screen.getByTestId("sp-undo-reason"), { target: { value: "nhap nham tep" } });
    expect(go.disabled).toBe(true);                                                         // the purchase text is still missing
    fireEvent.change(box("sp-undo-purchase-input"), { target: { value: purchase } });
    expect(go.disabled).toBe(false);
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls).find((c) => c.url.endsWith("/undo"))!.body).toMatchObject({ import_id: "IMP-zzz", confirm_text: main, confirm_purchase: purchase });
  });

  it("undo of an import: the text + a reason, POST /undo by import_id; a PURCHASE / HIGH text is asked when the server says so; the result lists the skipped keys", async () => {
    let n = 0;
    const calls = backend({ undo: () => {
      n += 1;
      if (n === 1) return json({ code: "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED", vi: "Cần chữ ảnh hưởng mua hàng", en: "Purchase text", detail: "model.feature_calendar",
        params: { keys: ["model.feature_calendar"], confirm_purchase: PURCHASE } }, 409);
      return json({ import_id: "IMP-aaa", entries: [], skipped: [{ section: "daily_forecast", key: "log_retention_days", reason: "UNDO_SKIPPED_RETENTION_DECREASE", value: 120 }] });
    } });
    await mount();
    await screen.findByTestId("sp-history");
    await act(async () => { fireEvent.click(screen.getByTestId("sp-undo-12")); });
    const text = screen.getByTestId("sp-undo-text").textContent!;
    expect(text).toMatch(/^NHAP-CAI-DAT-\d{4}-\d{2}-\d{2}$/);
    const go = screen.getByTestId("sp-undo-apply") as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    fireEvent.change(box("sp-undo-input"), { target: { value: text } });
    fireEvent.change(screen.getByTestId("sp-undo-reason"), { target: { value: "nhap nham tep" } });
    expect(go.disabled).toBe(false);
    await act(async () => { fireEvent.click(go); });
    expect(posts(calls).filter((c) => c.url.endsWith("/undo"))[0].body).toEqual({ import_id: "IMP-aaa", confirm_text: text, reason: "nhap nham tep" });
    // the server asks for the purchase text: shown, asked again, never resent by itself
    expect((await screen.findByTestId("sp-undo-purchase-text")).textContent).toBe(PURCHASE);
    expect((screen.getByTestId("sp-undo-apply") as HTMLButtonElement).disabled).toBe(true);
    expect(posts(calls).filter((c) => c.url.endsWith("/undo"))).toHaveLength(1);
    fireEvent.change(box("sp-undo-purchase-input"), { target: { value: PURCHASE } });
    await act(async () => { fireEvent.click(screen.getByTestId("sp-undo-apply")); });
    expect(posts(calls).filter((c) => c.url.endsWith("/undo"))[1].body).toEqual({ import_id: "IMP-aaa", confirm_text: text, reason: "nhap nham tep", confirm_purchase: PURCHASE });
    const sk = await screen.findByTestId("sp-undo-skipped");
    expect(sk.textContent).toContain("daily_forecast.log_retention_days");
    expect(sk.textContent).toContain("trả lại số cũ là giảm");
    expect(screen.queryByTestId("sp-undo-area")).toBeNull();
  });
});
