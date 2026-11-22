import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import BigQuery from "./pages/BigQuery";

// 1.4.15 (lot 6): BigQuery page - the reset puts back only the non-connection part and lists the kept keys; after a source table is
// saved the connection card reads its values again (so its next Save is not refused with 409 SETTINGS_FIELD_GUARDED).
// Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const SETTINGS = { dataset_id: "d", source_table: "t_old", project_id: "p", location: "asia-southeast1", partition_column: "", created_at_is_utc: true, auth_method: "ADC",
  maximum_bytes_billed: 1000, initial_history_days: 730, history_start_date: "2026-01-01", exact_duplicate_policy: "BLOCK", completion_table: "old_completion",
  completion_date_column: "", completion_status_column: "", completion_status_value: "", field_mapping: {}, reference_mapping: {}, schema_snapshot: [] };
const IDENT = { runtime: { windows_user: "u", computer: "PC", appdata: "C:\\x", adc_path_checked: "C:\\x\\adc.json", adc_exists: true, google_application_credentials_set: false,
  google_application_credentials_exists: false, gcloud_on_path: false, effective_method: "ADC", note: { vi: "x", en: "x" } },
  oauth: { configured: false, client_id: "", client_secret_set: false, status: "NOT_SIGNED_IN", email: null, error: null } };
const TABLES = { d1: { table_id: "p.d.t_old", production_enabled: false, optional: false, last_check: null }, d0: { table_id: "p.d.d0", mode: "SNAPSHOT", optional: false, last_check: null } };

interface Call { url: string; method: string; body: any }
// afterSave: the settings the status gives once the source table was saved (the page also reads the status on its own at load, so the answer depends on the save, not on the call count)
function backend(o: { afterSave?: any; reset?: () => Response; putSettings?: () => Response } = {}) {
  const calls: Call[] = [];
  let saved = false;
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (u === "/api/bigquery/status") return json({ settings: saved && o.afterSave ? o.afterSave : SETTINGS, checks: {}, activation: { requirements: {}, ready: false } });
    if (u === "/api/bigquery/identity") return json(IDENT);
    if (u === "/api/bigquery/source-tables" && method === "GET") return json(TABLES);
    if (u === "/api/bigquery/source-tables/d1" && method === "PUT") { saved = true; return json({ ok: true }); }
    if (u === "/api/settings/bigquery/reset") return o.reset ? o.reset() : json({ ...SETTINGS, max_retries: 3, kept_keys: ["dataset_id", "maximum_bytes_billed", "project_id", "source_table", "field_mapping"] });
    if (u === "/api/settings/bigquery" && method === "PUT") return o.putSettings ? o.putSettings() : json(JSON.parse(init.body));
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const mount = async () => { await act(async () => { render(wrap(<BigQuery />)); }); await screen.findByTestId("bq-reset"); };
const field = (label: string) => screen.getByDisplayValue(label) as HTMLInputElement;

describe("1.4.15 BigQuery page: reset and source-table reload", () => {
  it("the reset button says it keeps the connection (confirmation box), posts the reset and then lists the kept keys", async () => {
    const calls = backend();
    await mount();
    expect(screen.getByTestId("bq-reset").textContent).toContain("Đặt lại phần không phải kết nối");
    await act(async () => { fireEvent.click(screen.getByTestId("bq-reset")); });
    expect(screen.getByTestId("bq-reset-help").textContent).toContain("Dự án, dataset, bảng, ánh xạ cột, đăng nhập Google");
    expect(screen.getByTestId("bq-reset-help").textContent).toContain("GIỮ NGUYÊN");
    expect(screen.getByTestId("bq-reset-help").textContent).toContain("trần chi phí BigQuery");
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);                       // the confirmation box has not been confirmed yet
    await act(async () => { fireEvent.click(screen.getByText("Đặt lại")); });
    expect(calls.filter((c) => c.url === "/api/settings/bigquery/reset" && c.method === "POST")).toHaveLength(1);
    expect(await screen.findByText("Đã đặt lại phần không phải kết nối (backend xác nhận).")).toBeTruthy();
    expect(screen.getByTestId("bq-reset-kept").textContent).toContain("dataset_id, maximum_bytes_billed, project_id, source_table, field_mapping");
    expect(field("d").value).toBe("d");                                                  // the connection is still shown
  });

  it("cancelling the confirmation box posts nothing", async () => {
    const calls = backend();
    await mount();
    await act(async () => { fireEvent.click(screen.getByTestId("bq-reset")); });
    await act(async () => { fireEvent.click(screen.getByText("Hủy")); });
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
    expect(screen.queryByTestId("bq-reset-help")).toBeNull();
  });

  it("after a source table is saved the page reads the status again: the card shows the new value and the next Save sends it, not the old one", async () => {
    const NEW = { ...SETTINGS, source_table: "t_new", completion_table: "new_completion" };
    const calls = backend({ afterSave: NEW });
    await mount();
    expect(field("t_old")).toBeTruthy();
    const before = calls.filter((c) => c.url === "/api/bigquery/status").length;
    await screen.findByTestId("table-d1-save");
    await act(async () => { fireEvent.click(screen.getByTestId("table-d1-save")); });
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/bigquery/status").length).toBeGreaterThan(before));
    await waitFor(() => expect(field("t_new")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Lưu" })); });                 // the Save of the connection card
    const put = calls.find((c) => c.url === "/api/settings/bigquery" && c.method === "PUT")!;
    expect(put.body.source_table).toBe("t_new");
    expect(put.body.completion_table).toBe("new_completion");
  });

  it("an edit in progress in the card is kept when the status is read again after a source table was saved", async () => {
    const NEW = { ...SETTINGS, source_table: "t_new" };
    backend({ afterSave: NEW });
    await mount();
    fireEvent.change(field("asia-southeast1"), { target: { value: "US" } });             // the user edits the location
    await screen.findByTestId("table-d1-save");
    await act(async () => { fireEvent.click(screen.getByTestId("table-d1-save")); });
    await waitFor(() => expect(field("t_new")).toBeTruthy());                           // the untouched field took the new value
    expect(field("US")).toBeTruthy();                                                    // the edit stayed
  });
});
