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
const AUX: Record<string, string> = { openhours: P + "openhours_by_sku", avg_demand: P + "fact_avg_demand_sku",
  avg_demand_hist: P + "fact_avg_demand_sku_historical", product_names: P + "dim_sku" };
const full = { ...base, ...Object.fromEntries(Object.entries(AUX).map(([k, v]) => [k, { table_id: v, ok: false, last_check: null }])) };

describe("v1.4.9 auxiliary source tables", () => {
  it("shows the four tables with label, one-line description and both buttons after D-1 / D-0", async () => {
    mock({ "/api/bigquery/source-tables": full });
    const { container } = render(wrap(<SourceTables />));
    await waitFor(() => expect((screen.getByTestId("table-openhours-id") as HTMLInputElement).value).toBe(AUX.openhours));
    for (const [k, v] of Object.entries(AUX)) {
      expect((screen.getByTestId(`table-${k}-id`) as HTMLInputElement).value).toBe(v);
      expect(screen.getByTestId(`table-${k}-desc`).textContent).toBeTruthy();
      expect(screen.getByTestId(`table-${k}-check`).textContent).toContain("Kiểm tra");
      expect(screen.getByTestId(`table-${k}-save`).textContent).toContain("Kiểm tra & lưu");
    }
    expect(screen.getByTestId("table-product_names-desc").textContent).toContain("không bắt buộc");
    expect(screen.getByTestId("tables-aux")).toBeTruthy();
    // order: D-1, D-0, then the auxiliary tables
    const order = Array.from(container.querySelectorAll("[data-testid^='table-']")).map((e) => e.getAttribute("data-testid"))
      .filter((x) => /^table-[a-z_0-9]+$/.test(x!) && !x!.endsWith("-desc"));
    expect(order).toEqual(["table-d1", "table-d0", "table-openhours", "table-avg_demand", "table-avg_demand_hist", "table-product_names"]);
  });

  it("checks and saves one auxiliary table with its own id", async () => {
    const other = "company-prod-01.sales_dw.avg_today";
    const calls = mock({ "/api/bigquery/source-tables/avg_demand/check": { kind: "avg_demand", table_id: other, status: "FAILED", checked_at: "2026-11-08T14:00:00+00:00",
      errors: [{ code: "COLUMN_NOT_FOUND", field: "avg_demand", column: "ingest_time" }] },
      "/api/bigquery/source-tables": full });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-avg_demand-id")).toBeTruthy());
    fireEvent.change(screen.getByTestId("table-avg_demand-id"), { target: { value: other } });
    fireEvent.click(screen.getByTestId("table-avg_demand-check"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/source-tables/avg_demand/check") && c.body.table_id === other)).toBe(true));
    await waitFor(() => expect(screen.getByTestId("table-avg_demand").textContent).toContain("ingest_time"));
    fireEvent.click(screen.getByTestId("table-avg_demand-save"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/source-tables/avg_demand") && c.body.table_id === other)).toBe(true));
    expect(calls.some((c) => c.method === "PUT" && /source-tables\/(d1|d0|openhours)$/.test(c.url))).toBe(false);
  });

  it("a backend without the auxiliary tables shows the D-1 / D-0 section unchanged", async () => {
    mock({ "/api/bigquery/source-tables": base });
    render(wrap(<SourceTables />));
    await waitFor(() => expect(screen.getByTestId("table-d1-id")).toBeTruthy());
    expect(screen.queryByTestId("tables-aux")).toBeNull();
    expect(screen.queryByTestId("table-openhours")).toBeNull();
    expect(screen.queryByTestId("table-d1-desc")).toBeNull();
  });
});
