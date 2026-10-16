import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { FeatureGroups } from "./pages/Config";
import { SourceTables } from "./pages/BigQuery";
import { GateException } from "./pages/Performance";

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

describe("v1.2.0 feature groups", () => {
  it("historical demand switches lags and rolling together; price without data is flagged; strategy selectable", async () => {
    mock({ "/api/features/registry": { decisions: { price: { used: false, reason: "NO_DATA", coverage: 0 } } } });
    const set = vi.fn();
    const v = { feature_lags: true, feature_rolling: true, feature_price: true, forecast_strategy: "RECURSIVE" };
    render(wrap(<FeatureGroups v={v} set={set} />));
    await waitFor(() => expect(screen.getByTestId("fg-price-nodata")).toBeTruthy());
    fireEvent.click(screen.getByTestId("fg-history"));
    expect(set).toHaveBeenCalledWith({ feature_lags: false, feature_rolling: false });
    fireEvent.change(screen.getByTestId("strategy"), { target: { value: "DIRECT" } });
    expect(set).toHaveBeenCalledWith({ forecast_strategy: "DIRECT" });
  });

  it("all groups off is shown as an error; DIRECT shows its own parameters", async () => {
    mock({ "/api/features/registry": { decisions: {} } });
    render(wrap(<FeatureGroups v={{ feature_lags: false, feature_rolling: false, feature_price: false, forecast_strategy: "DIRECT", direct_origins: 12, direct_origin_step_days: 7 }} set={vi.fn()} />));
    expect(screen.getByTestId("fg-empty")).toBeTruthy();
    expect((screen.getAllByRole("spinbutton") as HTMLInputElement[]).map((x) => x.value)).toEqual(["12", "7"]);
  });
});

describe("v1.2.0 D-1 / D-0 source tables", () => {
  const D1 = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm";
  const D0 = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0";
  const status = {
    d1: { table_id: D1, ok: true, production_enabled: true, last_check: { status: "PASSED", checked_at: "2026-10-17T01:00:00+00:00", errors: [] } },
    d0: { table_id: D0, ok: false, mode: "SQL", last_check: null },
  };
  it("checks and saves each feed separately; the D-1 table is locked while production is on", async () => {
    const calls = mock({ "/api/bigquery/source-tables/d0/check": { kind: "d0", table_id: D0, status: "PASSED", checked_at: "2026-10-17T01:05:00+00:00", errors: [] },
      "/api/bigquery/source-tables": status });
    render(wrap(<SourceTables />));
    await waitFor(() => expect((screen.getByTestId("table-d0-id") as HTMLInputElement).value).toBe(D0));
    fireEvent.click(screen.getByTestId("table-d0-check"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/source-tables/d0/check") && c.body.table_id === D0)).toBe(true));
    fireEvent.click(screen.getByTestId("table-d0-save"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/source-tables/d0") && c.body.table_id === D0)).toBe(true));
    fireEvent.change(screen.getByTestId("table-d1-id"), { target: { value: "lakehouse-prod-394907.gold_buymed_vn2.other" } });
    expect((screen.getByTestId("table-d1-save") as HTMLButtonElement).disabled).toBe(true);
    expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/source-tables/d1"))).toBe(false);
  });
});

describe("v1.2.0 quality-gate exception", () => {
  it("sends the approval with the restated metrics for an eligible run", async () => {
    const calls = mock({ "/release-with-exception": { status: "PUBLISHED", forecast_run_id: "FCR-1" } });
    const done = vi.fn();
    render(wrap(<GateException d={{ id: "TRN-1", gate_exception: { eligible: true }, quality_gate: { checks: [] } }} onDone={done} />));
    fireEvent.change(screen.getByTestId("exc-by"), { target: { value: "Chu du an" } });
    fireEvent.change(screen.getByTestId("exc-review"), { target: { value: "2026-11-30" } });
    fireEvent.change(screen.getByTestId("exc-reason"), { target: { value: "Nhu cau bat on, chap nhan van hanh" } });
    fireEvent.change(screen.getByTestId("exc-wape"), { target: { value: "0.806" } });
    fireEvent.change(screen.getByTestId("exc-bias"), { target: { value: "0.069" } });
    fireEvent.change(screen.getByTestId("exc-confirm"), { target: { value: "EXCEPTION-TRN-1" } });
    fireEvent.click(screen.getByTestId("exc-release"));
    await waitFor(() => expect(done).toHaveBeenCalled());
    const c = calls.find((x) => x.url.endsWith("/api/training-runs/TRN-1/release-with-exception"))!;
    expect(c.method).toBe("POST");
    expect(c.body).toMatchObject({ approved_by: "Chu du an", review_by: "2026-11-30", acknowledged_wape: 0.806, acknowledged_bias: 0.069, confirm_text: "EXCEPTION-TRN-1" });
  });

  it("shows the record of a released exception and nothing for a non-eligible run", () => {
    mock({});
    const { rerender } = render(wrap(<GateException d={{ id: "TRN-2", quality_gate: { exception: { approved_by: "Chu du an", review_by: "2026-11-30", reason: "r", metrics: { wape: 0.806, bias: 0.069 } } } }} onDone={vi.fn()} />));
    expect(screen.getByTestId("exception-active").textContent).toContain("Chu du an");
    rerender(wrap(<GateException d={{ id: "TRN-3", gate_exception: { eligible: false }, quality_gate: {} }} onDone={vi.fn()} />));
    expect(screen.queryByTestId("exc-release")).toBeNull();
  });
});
