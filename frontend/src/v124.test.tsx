import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { DataCheck } from "./pages/ExplainPanel";
import Jobs from "./pages/Jobs";
import Results from "./pages/Results";

// 1.2.4: product name + keyword search on the results; the explanation says how the data was verified; D-1 / D-0
// switches on the Jobs page show only the state the backend saved.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); document.getElementById("df-remote-banner")?.remove(); });

type Call = { url: string; method: string; body: any };
function mock(route: (u: string, c: Call) => any, status: (u: string, c: Call) => number = () => 200) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const v = route(u, c);
    return new Response(JSON.stringify(v === undefined ? {} : v), { status: status(u, c), headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const BQ = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm";
const RUN = { id: "FCR-BQ", created_at: "2026-10-17T12:34:19Z", data_source: "BIGQUERY", scope_key: BQ, model_version: "MV-X",
  horizons: [7, 15], max_horizon: 15, forecast_origin: "2026-10-17", data_as_of: "2026-10-16", active_scope: true, skus: [], fcs: ["BD", "HN"],
  horizon_coverage: { run_horizons: [7, 15], max_horizon: 15, configured: [7, 15], configured_missing_in_run: [], can_extend_without_retraining: false, cannot_extend_reason: null },
  product_names: { source: "lakehouse-prod-394907.gold_buymed_vn2.dim_sku", fetched_at: "2026-10-17T14:00:00+00:00", skus_named: 9000, skus_local: 9661 } };
const SERIES = [
  { sku_id: "MEDX.DMTS-SAN-ALP-001", fc_id: "HN", total: 21972.6, method: "LIGHTGBM", product_name: "Hỗ trợ gan Simarin Plus Stella (H/30V)", actual_today: null },
  { sku_id: "MEDX.UNKNOWN-001", fc_id: "BD", total: 10, method: "FALLBACK_INTERMITTENT", product_name: null, actual_today: null },
];
const sum = (series: any[]) => ({ n_series: series.length, grand_total: series.reduce((a, s) => a + s.total, 0), start_date: "2026-10-17",
  end_date: "2026-10-23", series, daily: [], actual: null });

function resultsMock() {
  return mock((u) => {
    if (u.startsWith("/api/forecast-runs?")) return [{ ...RUN, assessment: null }];
    if (u.startsWith("/api/forecast-runs/FCR-BQ/summary")) {
      const q = new URL(u, "http://x").searchParams.get("q");
      return sum(q === "khong co" ? [] : q ? [SERIES[0]] : SERIES);
    }
    if (u.startsWith("/api/forecast-runs/FCR-BQ/accuracy")) return null;
    if (u.startsWith("/api/forecast-runs/FCR-BQ")) return RUN;
    if (u.startsWith("/api/jobs/active")) return null;
    return {};
  });
}

describe("v1.2.4 results: product name and search", () => {
  it("shows the name next to the SKU and exactly 'Chưa có tên sản phẩm' when there is none", async () => {
    resultsMock();
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect(screen.getAllByTestId("product-name")).toHaveLength(1));
    const heads = [...document.querySelectorAll("table.tbl thead th")].map((th) => th.textContent);
    expect(heads.slice(0, 3)).toEqual(["SKU", "Tên sản phẩm", "FC/kho"]);
    expect(screen.getByTestId("product-name").textContent).toBe("Hỗ trợ gan Simarin Plus Stella (H/30V)");
    expect(screen.getByTestId("product-name-missing").textContent).toBe("Chưa có tên sản phẩm");
    expect(screen.getByTestId("names-source").textContent).toContain("dim_sku");
  });

  it("sends the keyword (debounced), keeps the FC filter, says when nothing matches and clears back to everything", async () => {
    const calls = resultsMock();
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect(screen.getAllByTestId("product-name")).toHaveLength(1));
    fireEvent.change(screen.getByDisplayValue("Tất cả", { exact: false }) as HTMLSelectElement, { target: { value: "HN" } });
    fireEvent.change(screen.getByTestId("fc-search"), { target: { value: "ho tro GAN" } });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/summary") && c.url.includes("q=ho%20tro%20GAN"))).toBe(true), { timeout: 2000 });
    const last = calls.filter((c) => c.url.includes("/summary")).pop()!;
    expect(last.url).toContain("fc_id=HN");                                   // combined with the FC filter
    await waitFor(() => expect(screen.queryByTestId("product-name-missing")).toBeNull());
    fireEvent.change(screen.getByTestId("fc-search"), { target: { value: "khong co" } });
    expect((await screen.findByTestId("fc-no-results", {}, { timeout: 2000 })).textContent).toContain("khong co");
    fireEvent.click(screen.getByTestId("fc-search-clear"));
    await waitFor(() => expect(screen.queryByTestId("fc-no-results")).toBeNull(), { timeout: 2000 });
    expect((screen.getByTestId("fc-search") as HTMLInputElement).value).toBe("");
    expect(calls.filter((c) => c.url.includes("/summary")).pop()!.url).not.toContain("q=");
    expect(calls.some((c) => c.url.includes("FCR-DEMO"))).toBe(false);
  });
});

describe("v1.2.4 explanation: how the data was checked", () => {
  it("says the data was reloaded but verified identical, and names changed days otherwise", () => {
    const { rerender } = render(wrap(<DataCheck d={{ status: "SAME_CONTENT", origin: "ATTESTED", window: ["2026-01-01", "2026-10-16"], rows: 1349388, sha256: "c47771523275a866ffff" }} />));
    const t1 = screen.getByTestId("ex-data-check").textContent ?? "";
    expect(t1).toContain("TRÙNG KHỚP");
    expect(t1).toContain("01/01/2026");
    expect(t1).toContain("1.349.388");
    expect(t1).toContain("c47771523275");
    expect(t1).toContain("backup");
    rerender(wrap(<DataCheck d={{ status: "CHANGED", changed_days: ["2026-10-13"], n_changed_days: 1 }} />));
    expect(screen.getByTestId("ex-data-check").textContent).toContain("13/10/2026");
    rerender(wrap(<DataCheck d={{ status: "UNVERIFIABLE" }} />));
    expect(screen.getByTestId("ex-data-check").textContent).toContain("không thể xác minh");
    rerender(wrap(<DataCheck d={{ status: "SAME_LOAD" }} />));
    expect(screen.queryByTestId("ex-data-check")).toBeNull();
  });
});

const flowState = (enabled: boolean, ready = true) => ({ enabled, state: enabled ? "ON" : "OFF", readiness: { ready, reasons: ready ? [] : [{ code: "SOURCE_NOT_READY" }] } });
function jobsMock(state: { d1: boolean; d0: boolean }, failPut = false) {
  return mock((u, c) => {
    if (u.startsWith("/api/scheduler/status")) return { running: true, heartbeat: null,
      config: { d1_enabled: state.d1, d0_enabled: state.d0, train_enabled: true, d1_signal_poll_start: "03:00", d0_times: ["08:00", "10:00"], train_time: "09:00" },
      flow_states: { d1: flowState(state.d1), d0: flowState(state.d0), train: flowState(true) } };
    if (c.method === "PUT" && u.startsWith("/api/schedules/")) {
      if (failPut) return { code: "FLOW_NOT_READY", vi: "Luồng chưa sẵn sàng", en: "x", detail: "SOURCE_NOT_READY" };
      const fl = u.split("/").pop() as "d1" | "d0";
      state[fl] = c.body.enabled;
      return { flow: fl, enabled: c.body.enabled, saved: true };
    }
    if (u.startsWith("/api/jobs")) return [];
    return {};
  }, (_u, c) => (failPut && c.method === "PUT" ? 409 : 200));
}

describe("v1.2.4 Jobs page: D-1 / D-0 switches", () => {
  it("turns each flow on and off through the backend; the box follows the saved state after a re-read", async () => {
    const state = { d1: false, d0: false };
    const calls = jobsMock(state);
    await act(async () => { render(wrap(<Jobs />)); });
    const d1 = await screen.findByTestId("jobs-switch-d1") as HTMLInputElement;
    expect(d1.checked).toBe(false);
    await act(async () => { fireEvent.click(d1); });
    await waitFor(() => expect((screen.getByTestId("jobs-switch-d1") as HTMLInputElement).checked).toBe(true));
    expect(calls.find((c) => c.method === "PUT")).toMatchObject({ url: "/api/schedules/d1", body: { enabled: true } });
    await act(async () => { fireEvent.click(screen.getByTestId("jobs-switch-d0")); });
    await waitFor(() => expect((screen.getByTestId("jobs-switch-d0") as HTMLInputElement).checked).toBe(true));
    expect(window.confirm).toHaveBeenCalled();                                // D-0 on asks first, like the schedule page
    expect(state).toEqual({ d1: true, d0: true });
    await act(async () => { fireEvent.click(screen.getByTestId("jobs-switch-d0")); });
    await waitFor(() => expect((screen.getByTestId("jobs-switch-d0") as HTMLInputElement).checked).toBe(false));
    expect(state).toEqual({ d1: true, d0: false });                            // independent switches
  });

  it("a refused switch stays as saved and shows the error", async () => {
    const state = { d1: false, d0: false };
    jobsMock(state, true);
    await act(async () => { render(wrap(<Jobs />)); });
    const d1 = await screen.findByTestId("jobs-switch-d1") as HTMLInputElement;
    await act(async () => { fireEvent.click(d1); });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("FLOW_NOT_READY"));
    expect((screen.getByTestId("jobs-switch-d1") as HTMLInputElement).checked).toBe(false);
    expect(state).toEqual({ d1: false, d0: false });
  });

  it("the read-only remote view (proxy banner) offers no switch", async () => {
    const banner = document.createElement("div");
    banner.id = "df-remote-banner";
    document.body.appendChild(banner);
    const calls = jobsMock({ d1: true, d0: false });
    await act(async () => { render(wrap(<Jobs />)); });
    const d1 = await screen.findByTestId("jobs-switch-d1") as HTMLInputElement;
    expect(d1.disabled).toBe(true);
    expect(d1.checked).toBe(true);                                             // still shows the saved state
    expect((screen.getByTestId("jobs-switch-d0") as HTMLInputElement).disabled).toBe(true);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});
