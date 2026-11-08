import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";

// 1.4.6 C4: the forecast pages show the 20 days of the daily Excel (days 8..20 marked as the weekly estimate, column
// cach_tinh) and a target-date filter FROM - TO; the history page always shows its FROM - TO. Backend mocked (unit, no
// network); the page == Excel rules are tested in backend/tests/test_v146_ui20.py.
const wrap = (path: string) => <I18nProvider><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const SYS = {
  version: "1.4.6", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 12, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-11-04", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};
const INFO = { source: "SEL2", run_id: "FRR-46", refreshed_at: "2026-11-05 06:30:00", data_cutoff_date: "2026-11-04", forecast_date: "2026-11-05" };
const RUN = { id: "FRR-46", forecast_date: "2026-11-05", data_as_of: "2026-11-04", created_at: "2026-11-04T23:30:00+00:00", model_version: "MV-46",
  config_version: "SEL2:abc", trial_mode: false, horizon: 7, n_series: 1, n_lightgbm: 1, n_fallback: 0, trigger: "SCHEDULE" };
const H20 = Array.from({ length: 20 }, (_, i) => i + 1);
const SRUN = { id: "FRR-46", model_version: "MV-46", data_source: "BIGQUERY", scope_key: "BIGQUERY:p.d.t", forecast_origin: "2026-11-05",
  forecast_date: "2026-11-05", data_as_of: "2026-11-04", created_at: "2026-11-04T23:30:00+00:00", max_horizon: 20, horizons: H20,
  estimate_from: 8, fcs: ["BD"], sel2: true, horizon_coverage: { run_horizons: H20, max_horizon: 20, configured: [7, 15, 30], configured_missing_in_run: [] } };
const day = (h: number) => `2026-11-${String(4 + h).padStart(2, "0")}`;
const SUMMARY = { run: SRUN, start_date: "2026-11-05", end_date: "2026-11-11", horizon: 7, grand_total: 31, n_series: 1, actual: null,
  daily: [3, 4, 5, 4, 5, 5, 5].map((y, i) => ({ target_date: day(i + 1), total: y, cach_tinh: "SEL2" })),
  series: [{ sku_id: "MEDX.A", fc_id: "BD", product_name: "Thuoc A", total: 31, method: "MOC", model_used: "MOC", forecast_source: "LIGHTGBM" }] };
const row = (h: number) => ({ sku_id: "MEDX.A", sku_code: "MEDX.A", fc_id: "BD", fc_code: "BD", product_name: "Thuoc A", ten_san_pham: "Thuoc A",
  forecast_date: "2026-11-05", target_date: day(h), horizon: h, horizon_day: h, weekday: 4, forecast_used: 10 + h, forecast_qty: 10 + h, final_qty: 10 + h,
  lightgbm_forecast: 10 + h, lgb_raw: 9.6 + h, raw_value: 9.6 + h, avg_demand: 5.4, forecast_source: "LIGHTGBM", fallback_reason: null, model_used: "MOC",
  method: "MOC", group_code: "A", nhom: "A", flags: null, cach_tinh: h <= 7 ? "SEL2" : "UOC_TINH_THEO_TUAN" });
const VALUES = { run: SRUN, total: 2, actual: null, rows: [row(7), row(8)] };
const DAILY = { run: RUN, rows: [row(7), row(8)], total: 2, page: 0, page_size: 100, horizons: H20, sel2: true, estimate_from: 8 };
const STATUS = { enabled: true, trial_mode: false, trial_label: null, refresh_enabled: true, refresh_deadline: "12:00", today: "2026-11-05",
  last_run: RUN, made_on: "2026-11-05", data_to: "2026-11-04", message: null, stale: false, outdated: false, last_report: null, trial_confirm_text: "" };
const OVERVIEW = { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", active_scope_key: "BIGQUERY:p.d.t", active_data_source: "BIGQUERY",
  scopes: [{ scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", n_days: 2 }], today: "2026-11-06", days: [], backup_days: [],
  sel2_from: "2026-11-04", forecast_info: INFO,
  sel2_days: [{ run_date: "2026-11-05", target_date: "2026-11-05", forecast_run_id: "FRR-46", source: "SEL2" },
    { run_date: "2026-11-04", target_date: "2026-11-04", forecast_run_id: "FRR-45", source: "SEL2" }],
  finalization: { applicable: true }, fcs: [] };

function backend() {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    calls.push(u);
    if (u.startsWith("/api/system/status")) return json(SYS);
    if (u.startsWith("/api/methods")) return json({ methods: {}, reasons: {} });
    if (u.startsWith("/api/forecast-info")) return json(INFO);
    if (u.startsWith("/api/forecast-runs")) return json([]);
    if (u.startsWith("/api/daily-forecast/sel2-runs")) return json([RUN]);
    if (u.startsWith("/api/daily-forecast/sel2-summary")) return json(SUMMARY);
    if (u.startsWith("/api/daily-forecast/sel2-values")) return json(VALUES);
    if (u.startsWith("/api/daily-forecast/values")) return json(DAILY);
    if (u.startsWith("/api/daily-forecast/runs")) return json([RUN]);
    if (u.startsWith("/api/daily-forecast/status")) return json(STATUS);
    if (u.startsWith("/api/sel2/source-config")) return json({ items: [], total: 0 });
    if (u.startsWith("/api/accuracy-reports")) return json([]);
    if (u.startsWith("/api/history/overview")) return json(OVERVIEW);
    if (u.startsWith("/api/history/summary")) return json({ daily: [], kpi: {}, filters: {} });
    if (u.startsWith("/api/history/rows")) return json({ total: 0, rows: [] });
    if (u.startsWith("/api/jobs/active")) return json({});
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}

const typeDate = async (label: string, value: string) => {
  const input = screen.getAllByLabelText(label).find((x) => x.tagName === "INPUT" && (x as HTMLInputElement).type === "text") as HTMLInputElement;
  await act(async () => { fireEvent.change(input, { target: { value } }); });
};

describe("1.4.6 Results page: 20 days, estimate marked, date filter", () => {
  it("offers 1..20 days (default 7), marks 8..20 as estimate and explains it", async () => {
    backend();
    await act(async () => render(wrap("/results")));
    await waitFor(() => expect(screen.getByText("MEDX.A")).toBeTruthy());
    const picker = screen.getByTestId("horizon-picker") as HTMLSelectElement;
    expect(picker.value).toBe("7");
    const opts = Array.from(picker.options).map((o) => o.textContent);
    expect(opts.length).toBe(20);
    expect(opts[6]).toBe("7 ngày");
    expect(opts[7]).toBe("8 ngày (có ngày ước tính)");
    expect(opts[19]).toBe("20 ngày (có ngày ước tính)");
    expect(screen.getByTestId("estimate-note").textContent).toContain("Ngày 8–20: ƯỚC TÍNH theo tuần");
  });

  it("sends the horizon and the target-date range to the summary (totals tab) and the detail", async () => {
    const calls = backend();
    await act(async () => render(wrap("/results")));
    await waitFor(() => expect(screen.getByText("MEDX.A")).toBeTruthy());
    await act(async () => { fireEvent.change(screen.getByTestId("horizon-picker"), { target: { value: "20" } }); });
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-summary") && u.includes("horizon=20"))).toBe(true));
    await typeDate("Từ ngày", "08/11/2026");
    await typeDate("Đến ngày", "15/11/2026");
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-summary") && u.includes("date_from=2026-11-08")
      && u.includes("date_to=2026-11-15") && u.includes("horizon=20"))).toBe(true));
    await act(async () => { screen.getAllByRole("tab")[1].click(); });
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-values") && u.includes("date_from=2026-11-08")
      && u.includes("date_to=2026-11-15"))).toBe(true));
  });

  it("daily detail marks the estimate rows in the column Cách tính", async () => {
    backend();
    await act(async () => render(wrap("/results")));
    await waitFor(() => expect(screen.getByText("MEDX.A")).toBeTruthy());
    await act(async () => { screen.getAllByRole("tab")[1].click(); });
    const est = await screen.findByTestId("cach-tinh-estimate");
    const table = est.closest("table")!;
    const head = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(head).toContain("Cách tính");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    expect(rows.length).toBe(2);
    expect(rows[0].querySelector("[data-testid=cach-tinh]")?.textContent).toBe("SEL2");
    expect(rows[0].querySelector("[data-testid=cach-tinh-estimate]")).toBeNull();
    expect(rows[1].querySelector("[data-testid=cach-tinh-estimate]")?.textContent).toBe("Ước tính theo tuần");
    expect(rows[1].textContent).toContain("18");                      // forecast_used of day 8 as given
  });
});

describe("1.4.6 Daily forecast page: 20 days, estimate marked, date filter", () => {
  it("lists horizons 1..20 with 8..20 marked, a Cách tính column and the note", async () => {
    backend();
    await act(async () => render(wrap("/daily-forecast")));
    const table = await screen.findByTestId("daily-table");
    await waitFor(() => expect(table.querySelectorAll("tbody tr").length).toBe(2));
    const opts = Array.from((screen.getByTestId("daily-horizon") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(opts.length).toBe(21);                                      // "Tất cả" + 20
    expect(opts[0]).toBe("Tất cả");
    expect(opts[7]).toBe("7");
    expect(opts[8]).toBe("8 (Ước tính theo tuần)");
    expect(Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent)).toContain("Cách tính");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    expect(rows[0].querySelector("[data-testid=cach-tinh-estimate]")).toBeNull();
    expect(rows[1].querySelector("[data-testid=cach-tinh-estimate]")?.textContent).toBe("Ước tính theo tuần");
    expect(screen.getByTestId("daily-estimate-note").textContent).toContain("UOC_TINH_THEO_TUAN");
  });

  it("sends the target-date range FROM - TO", async () => {
    const calls = backend();
    await act(async () => render(wrap("/daily-forecast")));
    await screen.findByTestId("daily-table");
    await typeDate("Từ ngày dự báo", "12/11/2026");
    await typeDate("Đến ngày dự báo", "20/11/2026");
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/daily-forecast/values") && u.includes("date_from=2026-11-12")
      && u.includes("date_to=2026-11-20"))).toBe(true));
  });
});

describe("1.4.6 History page: FROM - TO always shown", () => {
  it("shows the dates of the default range and a change becomes the custom range", async () => {
    const calls = backend();
    await act(async () => render(wrap("/forecast-history")));
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/history/summary"))).toBe(true));
    expect((screen.getByTestId("fh-run-date") as HTMLSelectElement).value).toBe("last30");
    const from = screen.getAllByLabelText("Từ ngày chạy").find((x) => (x as HTMLInputElement).type === "text") as HTMLInputElement;
    const to = screen.getAllByLabelText("Đến ngày chạy").find((x) => (x as HTMLInputElement).type === "text") as HTMLInputElement;
    expect(from.value).toBe("07/10/2026");                             // last 30 days up to the newest run date 05/11
    expect(to.value).toBe("05/11/2026");
    await typeDate("Từ ngày chạy", "01/11/2026");
    await waitFor(() => expect((screen.getByTestId("fh-run-date") as HTMLSelectElement).value).toBe("custom"));
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/history/summary") && u.includes("run_from=2026-11-01")
      && u.includes("run_to=2026-11-05"))).toBe(true));
  });
});
