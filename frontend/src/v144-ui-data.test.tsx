import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";
import ForecastInfoLine from "./components/ForecastInfoLine";

// 1.4.4 T2: the info line of the forecast pages (source - refresh time - data cut-off) and the Results page in SEL2 mode
// (same title, tabs, cards and tables; numbers of the daily Excel). The backend is mocked; the API rules are tested in
// backend/tests/test_v144_ui_data.py.
const wrap = (el: React.ReactNode, path = "/results") => <I18nProvider><MemoryRouter initialEntries={[path]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const SYS = {
  version: "1.4.4", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 12, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-11-04", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};
const INFO = { source: "SEL2", run_id: "FRR-44", refreshed_at: "2026-11-05 06:30:00", data_cutoff_date: "2026-11-04", forecast_date: "2026-11-05" };
const RUN = { id: "FRR-44", forecast_date: "2026-11-05", data_as_of: "2026-11-04", created_at: "2026-11-04T23:30:00+00:00", model_version: "MV-44",
  config_version: "SEL2:abc", trial_mode: false };
const SRUN = { id: "FRR-44", model_version: "MV-44", data_source: "BIGQUERY", scope_key: "BIGQUERY:p.d.t", forecast_origin: "2026-11-05",
  forecast_date: "2026-11-05", data_as_of: "2026-11-04", created_at: "2026-11-04T23:30:00+00:00", max_horizon: 7, horizons: [1, 2, 3, 4, 5, 6, 7],
  fcs: ["BD"], sel2: true };
const SUMMARY = { run: SRUN, start_date: "2026-11-05", end_date: "2026-11-11", horizon: 7, grand_total: 31, n_series: 1, actual: null,
  daily: [3, 4, 5, 4, 5, 5, 5].map((y, i) => ({ target_date: `2026-11-${String(5 + i).padStart(2, "0")}`, total: y })),
  series: [{ sku_id: "MEDX.A", fc_id: "BD", product_name: "Thuoc A", total: 31, method: "MOC+DOW4", model_used: "MOC+DOW4", forecast_source: "LIGHTGBM" }] };
const VALUES = { run: SRUN, total: 1, actual: null, rows: [{ sku_id: "MEDX.A", sku_code: "MEDX.A", fc_id: "BD", fc_code: "BD", product_name: "Thuoc A",
  target_date: "2026-11-05", horizon: 1, horizon_day: 1, weekday: 4, forecast_used: 6, forecast_qty: 6, lightgbm_forecast: 2, avg_demand: 5.4,
  forecast_source: "AVG_DEMAND", fallback_reason: "KHONG_CO_AVG_DUNG_LIGHTGBM", model_used: "MOC", method: "MOC" }] };

function backend(info: any = INFO) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    calls.push(u);
    if (u.startsWith("/api/system/status")) return json(SYS);
    if (u.startsWith("/api/methods")) return json({ methods: {}, reasons: {} });
    if (u.startsWith("/api/forecast-info")) return json(info);
    if (u.startsWith("/api/forecast-runs")) return json([]);
    if (u.startsWith("/api/daily-forecast/sel2-runs")) return json([RUN]);
    if (u.startsWith("/api/daily-forecast/sel2-summary")) return json(SUMMARY);
    if (u.startsWith("/api/daily-forecast/sel2-values")) return json(VALUES);
    if (u.startsWith("/api/jobs/active")) return json({});
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}

describe("1.4.4 forecast info line", () => {
  it("shows source, refresh time (VN) and data cut-off of the newest SEL2 run", async () => {
    backend();
    render(wrap(<ForecastInfoLine />));
    const el = await screen.findByTestId("forecast-info");
    expect(el.textContent).toBe("Nguồn: SEL2 FRR-44 - làm mới lúc 2026-11-05 06:30:00 - dữ liệu đến 04/11/2026");
  });

  it("labels the 1.3.x pipeline and the absence of any forecast", async () => {
    backend({ source: "LIGHTGBM_CU", run_id: "FR-1", refreshed_at: "2026-11-02 08:00:00", data_cutoff_date: "2026-11-01", forecast_date: null });
    const r = render(wrap(<ForecastInfoLine />));
    expect((await screen.findByTestId("forecast-info")).textContent).toContain("LightGBM cũ (1.3.x)");
    r.unmount();
    backend({ source: null, run_id: null, refreshed_at: null, data_cutoff_date: null, forecast_date: null });
    render(wrap(<ForecastInfoLine />));
    expect((await screen.findByTestId("forecast-info")).textContent).toBe("Nguồn: chưa có số dự báo");
  });

  it("uses the info it is given without a request (history page)", async () => {
    const calls = backend();
    render(wrap(<ForecastInfoLine info={INFO} />));
    expect(screen.getByTestId("forecast-info").textContent).toContain("SEL2 FRR-44");
    expect(calls.some((u) => u.startsWith("/api/forecast-info"))).toBe(false);
  });
});

describe("1.4.4 Results page in SEL2 mode", () => {
  it("keeps title, tabs and table, reads the SEL2 summary and shows the info line", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<App />, "/results")));
    await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Kết quả dự báo"));
    await waitFor(() => expect(screen.getByText("MEDX.A")).toBeTruthy());
    expect(screen.getAllByRole("tab").length).toBe(2);
    expect(screen.getByTestId("forecast-info").textContent).toContain("SEL2 FRR-44");
    expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-summary") && u.includes("run_id=FRR-44"))).toBe(true);
    expect(calls.some((u) => /\/api\/forecast-runs\/[^?]/.test(u))).toBe(false);     // no 1.3.x run detail / accuracy
    const row = screen.getByText("MEDX.A").closest("tr")!;
    // the 1.4.3 columns only (no SEL2 column added); the total is the sum of forecast_used
    const head = Array.from(row.closest("table")!.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(head).toEqual(["SKU", "Tên sản phẩm", "FC/kho", "Tổng trong khoảng (7 ngày)", "Thực tế hôm nay", "Phương pháp", ""]);
    const cells = Array.from(row.querySelectorAll("td")).map((td) => td.textContent);
    expect(cells.length).toBe(head.length);
    expect(cells[3]).toBe("31");
    expect(row.textContent).not.toContain("LIGHTGBM");
    expect((screen.getByTestId("run-select") as HTMLSelectElement).value).toBe("FRR-44");
    expect(r.container.querySelector(`a[href="/api/sel2/export/2026-11-05"]`)).not.toBeNull();
  });

  it("daily detail tab keeps the 1.4.3 columns, the quantity is forecast_used", async () => {
    const calls = backend();
    await act(async () => render(wrap(<App />, "/results")));
    await waitFor(() => expect(screen.getByText("MEDX.A")).toBeTruthy());
    await act(async () => { screen.getAllByRole("tab")[1].click(); });
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/daily-forecast/sel2-values") && u.includes("run_id=FRR-44"))).toBe(true));
    const row = await waitFor(() => {
      const tr = screen.getByText("MEDX.A").closest("tr")!;
      expect(tr.closest("table")!.querySelectorAll("thead th").length).toBe(9);
      return tr;
    });
    const head = Array.from(row.closest("table")!.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(head).toEqual(["SKU", "Tên sản phẩm", "FC/kho", "Ngày", "Thứ", "Số lượng dự báo", "Thực tế đến hiện tại", "Phương pháp", ""]);
    const cells = Array.from(row.querySelectorAll("td")).map((td) => td.textContent);
    expect(cells.length).toBe(head.length);
    expect(cells[5]).toBe(String(VALUES.rows[0].forecast_used));
    expect(row.textContent).not.toContain("AVG_DEMAND");
    expect(row.textContent).not.toContain("KHONG_CO_AVG_DUNG_LIGHTGBM");
  });
});
