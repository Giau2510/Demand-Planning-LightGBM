import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { SourceTables } from "./pages/BigQuery";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });

type Call = { url: string; method: string; body: any };
function mock(routes: Record<string, any>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    calls.push({ url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : undefined });
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => u.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const P = "lakehouse-prod-394907.gold_buymed_vn2.";
const base = {
  d1: { table_id: P + "demand_planing_lightgbm", ok: true, production_enabled: false, last_check: null },
  d0: { table_id: P + "demand_planing_lightgbm_D0", ok: false, mode: "SQL", last_check: null },
};
const REQUIRED: Record<string, string> = { openhours: P + "openhours_by_sku", avg_demand: P + "fact_avg_demand_sku",
  avg_demand_hist: P + "fact_avg_demand_sku_historical" };
const status = (names: { table_id: string; ok: boolean; optional?: boolean }) => ({
  ...base,
  ...Object.fromEntries(Object.entries(REQUIRED).map(([k, v]) => [k, { table_id: v, ok: false, last_check: null }])),
  product_names: { last_check: null, ...names },
});

describe("v1.4.10 product names table is optional", () => {
  it("shows the 'not used' label when the table is optional and its id is empty", async () => {
    mock({ "/api/bigquery/source-tables": status({ table_id: "", ok: true, optional: true }) });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-product_names-id")).toBeTruthy());
    expect((screen.getByTestId("table-product_names-id") as HTMLInputElement).value).toBe("");
    expect(screen.getByTestId("table-product_names-unused").textContent).toBe("không dùng");
    // the other tables never show it (required: no optional flag)
    for (const k of Object.keys(REQUIRED)) expect(screen.queryByTestId(`table-${k}-unused`)).toBeNull();
    expect(screen.queryByTestId("table-d1-unused")).toBeNull();
    expect(screen.queryByTestId("table-d0-unused")).toBeNull();
  });

  it("does not show the label when the id is set, and follows what the user types", async () => {
    mock({ "/api/bigquery/source-tables": status({ table_id: P + "dim_sku", ok: false, optional: true }) });
    render(wrap(<SourceTables />));
    await waitFor(() => expect((screen.getByTestId("table-product_names-id") as HTMLInputElement).value).toBe(P + "dim_sku"));
    expect(screen.queryByTestId("table-product_names-unused")).toBeNull();
    fireEvent.change(screen.getByTestId("table-product_names-id"), { target: { value: "" } });
    expect(screen.getByTestId("table-product_names-unused")).toBeTruthy();
    fireEvent.change(screen.getByTestId("table-product_names-id"), { target: { value: "   " } });      // blank = empty
    expect(screen.getByTestId("table-product_names-unused")).toBeTruthy();
    fireEvent.change(screen.getByTestId("table-product_names-id"), { target: { value: "company-prod-01.ref.sku_names" } });
    expect(screen.queryByTestId("table-product_names-unused")).toBeNull();
  });

  it("a table that is not optional never shows the label, even with an empty id", async () => {
    const st: any = status({ table_id: P + "dim_sku", ok: false, optional: true });
    st.openhours = { table_id: "", ok: false, last_check: null };
    mock({ "/api/bigquery/source-tables": st });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-openhours-id")).toBeTruthy());
    expect((screen.getByTestId("table-openhours-id") as HTMLInputElement).value).toBe("");
    expect(screen.queryByTestId("table-openhours-unused")).toBeNull();
  });

  it("an older backend without the optional flag shows no label (nothing else changes)", async () => {
    mock({ "/api/bigquery/source-tables": status({ table_id: "", ok: false }) });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-product_names-id")).toBeTruthy());
    expect(screen.queryByTestId("table-product_names-unused")).toBeNull();
  });

  it("the description says the table is optional and the Avg Demand tables come first; saving an empty id calls PUT", async () => {
    const calls = mock({ "/api/bigquery/source-tables": status({ table_id: "", ok: true, optional: true }) });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-product_names-desc")).toBeTruthy());
    const d = screen.getByTestId("table-product_names-desc").textContent!;
    expect(d).toContain("không bắt buộc");
    expect(d).toContain("Avg Demand");
    expect(d).toContain("để trống");
    fireEvent.click(screen.getByTestId("table-product_names-save"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/source-tables/product_names") && c.body.table_id === "")).toBe(true));
  });

  it("English text of the label and of the description", async () => {
    localStorage.setItem("df.lang", "en");
    mock({ "/api/bigquery/source-tables": status({ table_id: "", ok: true, optional: true }) });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-product_names-desc")).toBeTruthy());
    expect(screen.getByTestId("table-product_names-unused").textContent).toBe("not used");
    const d = screen.getByTestId("table-product_names-desc").textContent!;
    expect(d).toContain("optional");
    expect(d).toContain("Avg Demand tables first");
  });
});
