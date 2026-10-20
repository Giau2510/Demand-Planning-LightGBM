import { act, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import ForecastHistory from "./pages/ForecastHistory";

// 1.2.9 (seventh batch): the history page's main cards use the FINALIZED (frozen) actual only; provisional and end-of-day
// closed rows are shown apart with their own counts; the evaluation base is visible; both languages; chart semantics.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });

function mock(route: (u: string) => any) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    calls.push(u);
    return new Response(JSON.stringify(route(u) ?? {}), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const BQ = "BIGQUERY:p.d.t";
const DAY = { run_date: "2026-10-18", target_date: "2026-10-19", forecast_run_id: "FCR-B", session_started_at: "2026-10-18T02:00:00+00:00",
  published_at: "2026-10-18T02:00:00+00:00", model_version: "MV-B", n_rows: 3, capture_mode: "AT_PUBLISH", sessions_count: 1 };
const DAY0 = { ...DAY, run_date: "2026-10-17", target_date: "2026-10-18", forecast_run_id: "FCR-A", model_version: "MV-A" };
const OVERVIEW = { scope_key: BQ, data_source: "BIGQUERY", active_scope_key: BQ, today: "2026-10-20", today_session: null,
  scopes: [{ scope_key: BQ, data_source: "BIGQUERY", n_days: 2, active: true }], days: [DAY, DAY0], backup_days: [], fcs: ["BD", "HN"],
  completion_signal_configured: false, finalization: { finalized_days: 1, blocked_days: 0, last_finalized_date: "2026-10-18", applicable: true } };
const FINAL = { id: "AFN-1", finalized_at: "2026-10-18T22:10:00+00:00", d1_load_id: "D1L-1", d1_job_id: "JOB-1",
  d1_synced_at: "2026-10-18T22:05:00+00:00", d1_mode: "FALLBACK_TIME_VERIFIED", d1_backfill: 0, n_rows: 2, total_qty: 35 };
const SUMMARY = { scope_key: BQ, data_source: "BIGQUERY", today: "2026-10-20", matching_skus: null, backup_days: [],
  daily: [
    { run_date: "2026-10-17", target_date: "2026-10-18", has_history: true, forecast_source: "PRIMARY", forecast_run_id: "FCR-A", snapshot: null,
      n_rows: 3, forecast: 36, actual: 35, deviation: 1, actual_status: "COMPLETE", actual_reason: "FINALIZED_D1", actual_final: FINAL,
      actual_close: null, n_zero_absent: 1 },
    { run_date: "2026-10-18", target_date: "2026-10-19", has_history: true, forecast_source: "PRIMARY", forecast_run_id: "FCR-B", snapshot: null,
      n_rows: 3, forecast: 36, actual: 7, deviation: 29, actual_status: "PROVISIONAL", actual_reason: "D1_NOT_FINALIZED", actual_final: null,
      actual_close: null, n_zero_absent: 0 }],
  kpi: { n_rows: 6, n_rows_compared: 3, days_with_history: 2, days_primary: 2, days_backup: 0, days_compared: 1, forecast_total: 72,
    basis: "FINALIZED_ONLY", actual_total: 35, forecast_compared: 36, deviation: 1, abs_error: 37, wape: 37 / 35, bias: 1 / 35,
    n_zero_absent: 1, status: "COMPLETE", notes: [],
    provisional: { n_rows: 3, days: 1, n_zero_absent: 0, actual_total: 7, forecast_compared: 36, deviation: 29, abs_error: 29, wape: 29 / 7, bias: 29 / 7 },
    closed: { n_rows: 0, days: 0, n_zero_absent: 0, actual_total: null, forecast_compared: null, deviation: null, abs_error: null, wape: null, bias: null },
    coverage: { rows_total: 6, rows_final: 3, rows_provisional: 3, rows_closed: 0, rows_no_actual: 0, days_final: 1, days_provisional: 1,
      days_closed: 0, days_no_actual: 0 } },
  sessions: [{ ...DAY, official: 1, decision: "SELECTED" }, { ...DAY0, official: 1, decision: "SELECTED" }] };
const ROWS = [
  { run_date: "2026-10-17", target_date: "2026-10-18", sku_id: "S1", fc_id: "HN", yhat: 10.5, forecast_qty: 11, actual: 5, deviation: 6, row_wape: 1.2,
    actual_status: "COMPLETE", actual_reason: "FINALIZED_D1", actual_source: "FINAL", product_name: null, forecast_run_id: "FCR-A",
    model_version: "MV-A", session_started_at: "2026-10-17T02:00:00+00:00", actual_as_of: "2026-10-18T22:10:00+00:00", forecast_source: "PRIMARY" },
  { run_date: "2026-10-18", target_date: "2026-10-19", sku_id: "S1", fc_id: "HN", yhat: 10.5, forecast_qty: 11, actual: 4, deviation: 7, row_wape: 1.75,
    actual_status: "PROVISIONAL", actual_reason: "D1_NOT_FINALIZED", actual_source: "D1", product_name: null, forecast_run_id: "FCR-B",
    model_version: "MV-B", session_started_at: "2026-10-18T02:00:00+00:00", actual_as_of: "2026-10-19T22:05:00+00:00", forecast_source: "PRIMARY" },
];
const backend = () => mock((u) => {
  if (u.startsWith("/api/history/overview")) return OVERVIEW;
  if (u.startsWith("/api/history/summary")) return SUMMARY;
  if (u.startsWith("/api/history/rows")) return { total: 2, rows: ROWS };
  return {};
});

describe("v1.2.9 finalized actual on the forecast history page", () => {
  it("shows the finalized figures in the main cards, the provisional ones apart, and the evaluation base", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    const kpi = within(screen.getByTestId("fh-kpi"));
    expect(kpi.getByText("Thực tế đã hoàn tất")).toBeTruthy();
    expect(kpi.getByText("35")).toBeTruthy();                                       // finalized only (not 35 + 7)
    expect(kpi.getByText("105,7%")).toBeTruthy();                                   // WAPE of the finalized rows
    expect(kpi.getByText("Bias +2,86%")).toBeTruthy();
    expect(kpi.getByText("trên 3 dòng · 1 ngày đã chốt")).toBeTruthy();
    expect(kpi.queryByText("Tạm tính")).toBeNull();
    expect(screen.queryByTestId("fh-no-final")).toBeNull();
    expect(screen.getByTestId("fh-coverage").textContent).toBe("Cơ sở so sánh: 3 dòng đã hoàn tất (1 ngày) · 3 dòng tạm tính · 0 dòng đã chốt "
      + "cuối ngày – cần xác minh · 0 dòng chưa có thực tế (không tính 0) · 1 dòng đã hoàn tất = 0 vì SKU × FC không có đơn trong ngày");
    const prov = [...screen.getByTestId("fh-prov").querySelectorAll("tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent));
    expect(prov).toEqual([["Tạm tính", "3 dòng · 1 ngày", "7", "36", "+29", "414,3%"]]);   // separate, labelled
    // chart: the finalized day is a full point, the other one provisional
    expect([...r.container.querySelectorAll("[data-testid=cmp-actual-pt]")].map((e) => e.getAttribute("data-status"))).toEqual(["complete", "provisional"]);
    expect(r.container.textContent).toContain("Thực tế chưa chốt (tạm tính / chốt cuối ngày)");
    // table: status per row, the finalized cell says when it was frozen
    const body = [...screen.getByTestId("fh-rows").querySelectorAll("tbody tr")];
    expect(body.map((tr) => tr.querySelectorAll("td")[10].textContent)).toEqual(["Đã hoàn tất", "Tạm tính"]);
    expect(body[0].querySelectorAll("td")[7].getAttribute("title")).toBe("đã chốt lúc 19/10/2026 05:10");
    expect(screen.getAllByTestId("actual-status")[0].getAttribute("title")).toBe("Đã chốt từ lần D-1 thành công — bản đóng băng, không đổi nữa");
    expect(screen.getByTestId("fh-final-state").textContent).toBe("Đã chốt 1 ngày thực tế (mới nhất: 18/10/2026); 0 ngày chưa chốt được — xem lý do ở trạng thái từng ngày.");
    expect(screen.getByTestId("fh-rules").textContent).toContain("đóng băng");
    expect(calls.every((u) => u.startsWith("/api/history/"))).toBe(true);           // read-only page
  });

  it("speaks English with the same rules", async () => {
    localStorage.setItem("df.lang", "en");
    backend();
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    const kpi = within(screen.getByTestId("fh-kpi"));
    expect(kpi.getByText("Complete actual")).toBeTruthy();
    expect(kpi.getByText("WAPE (finalized)")).toBeTruthy();
    expect(screen.getByTestId("fh-coverage").textContent).toContain("Evaluation base: 3 rows with a complete actual (1 days)");
    expect(within(screen.getByTestId("fh-prov")).getByText("Provisional")).toBeTruthy();
    expect(screen.getByTestId("fh-final-state").textContent).toContain("1 days of actual finalized");
  });

  it("without any finalized actual says so instead of showing a provisional figure as final", async () => {
    mock((u) => {
      if (u.startsWith("/api/history/overview")) return { ...OVERVIEW, data_source: "DEMO", finalization: { finalized_days: 0, blocked_days: 0, last_finalized_date: null, applicable: false } };
      if (u.startsWith("/api/history/summary")) return { ...SUMMARY, daily: SUMMARY.daily.slice(1),
        kpi: { ...SUMMARY.kpi, actual_total: null, forecast_compared: null, deviation: null, abs_error: null, wape: null, bias: null, n_rows_compared: 0,
          days_compared: 0, n_zero_absent: 0, status: "NO_ACTUAL", notes: ["NO_FINAL_ACTUAL"],
          coverage: { ...SUMMARY.kpi.coverage, rows_final: 0, days_final: 0 } } };
      if (u.startsWith("/api/history/rows")) return { total: 1, rows: ROWS.slice(1) };
      return {};
    });
    await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(screen.getByTestId("fh-rows")).toBeTruthy());
    expect(screen.getByTestId("fh-no-final").textContent).toBe("Chưa có actual đã chốt");
    const kpi = within(screen.getByTestId("fh-kpi"));
    expect(kpi.queryByText("7")).toBeNull();                                        // the provisional 7 is not shown as final
    expect(kpi.getAllByText("—").length).toBe(3);
    expect(within(screen.getByTestId("fh-prov")).getByText("7")).toBeTruthy();
    expect(screen.getByTestId("fh-final-state").textContent).toContain("không bao giờ được chốt");
  });
});
