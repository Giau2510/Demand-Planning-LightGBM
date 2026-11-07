import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";

// 1.4.4 T2 (tester): the info line on Dashboard / Daily forecast / Forecast history, page titles unchanged, the Daily
// forecast table of a SEL2 run (the 1.4.3 columns, forecast_used as the published number) and the SEL2 run dates of
// the history page. Backend mocked (unit, no network).
const wrap = (path: string) => <I18nProvider><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const SYS = {
  version: "1.4.4", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 12, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-11-04", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};
const INFO = { source: "SEL2", run_id: "FRR-44", refreshed_at: "2026-11-06 00:30:00", data_cutoff_date: "2026-11-05", forecast_date: "2026-11-06" };
const RUN = { id: "FRR-44", forecast_date: "2026-11-06", data_as_of: "2026-11-05", created_at: "2026-11-05T17:30:00+00:00", model_version: "MV-44",
  config_version: "SEL2:abc", trial_mode: false, horizon: 7, n_series: 1, n_lightgbm: 1, n_fallback: 0, trigger: "SCHEDULE" };
const ROW = { forecast_date: "2026-11-06", target_date: "2026-11-06", horizon: 1, fc_code: "BD", sku_code: "MEDX.A", product_name: "Thuoc A",
  ten_san_pham: "Thuoc A", group_code: "A", nhom: "A", lgb_raw: 2.4, raw_value: 2.4, lightgbm_forecast: 2, avg_demand: 1.25,
  forecast_source: "AVG_DEMAND", forecast_used: 7, final_qty: 7, fallback_reason: "KHONG_CO_AVG_DUNG_LIGHTGBM", model_used: "MOC", method: "MOC", flags: null };
const STATUS = { enabled: true, trial_mode: false, trial_label: null, refresh_enabled: true, refresh_deadline: "12:00", today: "2026-11-06",
  last_run: RUN, made_on: "2026-11-06", data_to: "2026-11-05", message: null, stale: false, outdated: false, last_report: null, trial_confirm_text: "" };
const OVERVIEW = { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", active_scope_key: "BIGQUERY:p.d.t", active_data_source: "BIGQUERY",
  scopes: [{ scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", n_days: 2 }], today: "2026-11-06",
  days: [{ run_date: "2026-11-04", target_date: "2026-11-05", forecast_run_id: "FCR-OLD4" }, { run_date: "2026-11-03", target_date: "2026-11-04", forecast_run_id: "FCR-OLD3" }],
  backup_days: [], sel2_from: "2026-11-04", forecast_info: INFO,
  sel2_days: [{ run_date: "2026-11-05", target_date: "2026-11-06", forecast_run_id: "FRR-43", source: "SEL2" },
    { run_date: "2026-11-04", target_date: "2026-11-05", forecast_run_id: "FRR-42", source: "SEL2" }],
  finalization: { applicable: true }, fcs: [] };

function backend() {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    calls.push(u);
    if (u.startsWith("/api/system/status")) return json(SYS);
    if (u.startsWith("/api/methods")) return json({ methods: {}, reasons: {} });
    if (u.startsWith("/api/forecast-info")) return json(INFO);
    if (u.startsWith("/api/daily-forecast/values")) return json({ run: RUN, rows: [ROW], total: 1, page: 0, page_size: 100, horizons: [1, 2, 3, 4, 5, 6, 7], sel2: true });
    if (u.startsWith("/api/daily-forecast/runs")) return json([RUN]);
    if (u.startsWith("/api/daily-forecast/status")) return json(STATUS);
    if (u.startsWith("/api/accuracy-reports")) return json([]);
    if (u.startsWith("/api/history/overview")) return json(OVERVIEW);
    if (u.startsWith("/api/forecast-runs")) return json([]);
    if (u.startsWith("/api/jobs/active")) return json({});
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}

const TEXT = "Nguồn: SEL2 FRR-44 - làm mới lúc 2026-11-06 00:30:00 - dữ liệu đến 05/11/2026";

describe("1.4.4 info line and unchanged titles on every forecast page", () => {
  it.each([["/", "Tổng quan"], ["/daily-forecast", "Dự báo hằng ngày"], ["/forecast-history", "Lịch sử Forecast & Thực tế"]])(
    "%s keeps its title and shows the info line once", async (path, title) => {
      backend();
      const r = await act(async () => render(wrap(path)));
      await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe(title));
      await waitFor(() => expect(screen.getAllByTestId("forecast-info").length).toBe(1));
      expect(screen.getByTestId("forecast-info").textContent).toBe(TEXT);
    });

  it("history page uses the overview info (no request of its own), lists SEL2 run dates and drops the 1.3.x day they replace", async () => {
    const calls = backend();
    await act(async () => render(wrap("/forecast-history")));
    await waitFor(() => expect(screen.getByTestId("forecast-info").textContent).toBe(TEXT));
    expect(calls.some((u) => u.startsWith("/api/forecast-info"))).toBe(false);
    const opts = Array.from(document.querySelectorAll("optgroup option")).map((o) => (o as HTMLOptionElement).value);
    expect(opts).toEqual(["2026-11-05", "2026-11-04", "2026-11-03"]);           // 04/11 once (SEL2), 03/11 kept
    const o4 = Array.from(document.querySelectorAll("optgroup option")).find((o) => (o as HTMLOptionElement).value === "2026-11-04")!;
    expect(o4.textContent).toContain("(SEL2)");
    expect(calls.some((u) => u.startsWith("/api/history/summary") && u.includes("run_to=2026-11-05"))).toBe(true);
  });

  it("daily page keeps the 1.4.3 columns for a SEL2 run, with forecast_used as the published number", async () => {
    backend();
    await act(async () => render(wrap("/daily-forecast")));
    const cell = await screen.findByText("MEDX.A");
    const row = cell.closest("tr")!;
    const head = Array.from(row.closest("table")!.querySelectorAll("thead th")).map((th) => th.textContent);
    // the header of 1.4.3 (the source column needs the LIGHTGBM key list, unavailable in this mock) + 1.4.6 Cách tính
    expect(head).toEqual(["Ngày lập", "Ngày", "Ngày thứ", "FC/kho", "SKU", "Tên sản phẩm", "Nhóm", "LightGBM gốc", "Số công bố",
      "Phương pháp", "Cách tính", "Cờ"]);
    const cells = Array.from(row.querySelectorAll("td")).map((td) => td.textContent);
    expect(cells.length).toBe(head.length);                                       // header and row stay aligned
    expect(cells[head.indexOf("Số công bố")]).toBe(String(ROW.forecast_used));    // page number = forecast_used
    expect(cells).not.toContain("AVG_DEMAND");
    expect(cells).not.toContain("KHONG_CO_AVG_DUNG_LIGHTGBM");
  });
});
