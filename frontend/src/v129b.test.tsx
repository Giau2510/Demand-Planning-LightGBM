import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import SqlSources, { BackfillPreview } from "./pages/SqlSources";
import ForecastHistory from "./pages/ForecastHistory";

// 1.2.9 (second batch): the controlled backfill needs a read-only preview of exactly the dates entered before it can run
// (and says what would change); the history page shows the whole-number forecast with its deviation, zero allowed.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); document.getElementById("df-remote-banner")?.remove(); });

type Call = { url: string; method: string; body: any };
function mock(route: (u: string, c: Call) => any) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const v = route(u, c);
    return new Response(JSON.stringify(v === undefined ? {} : v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const SYNC = { timezone: "Asia/Ho_Chi_Minh", active_source: "BIGQUERY", bigquery_production_enabled: true, notes: { vi: "n", en: "n" },
  flows_enabled: {}, jobs: {}, retry: {} };
const PREVIEW = { preview_id: "BFP-1", status: "READY", checked_at: "2026-10-19T16:00:00+00:00", written: false,
  window: { start: "2026-03-19", end: "2026-10-18", days: 214 }, read: { rows_read: 5000, rows_valid: 5000, rows_error: 0, qty_valid: 900 },
  compare: { rows_stored_in_window: 100, qty_stored_in_window: 910, series_days_new: 0, series_days_updated: 7, series_days_unchanged: 90,
    series_days_removed: 3, days_with_changes: 2, first_changed_day: "2026-08-01", last_changed_day: "2026-10-18" },
  open_hours: { would_write: { OK: 95, MISSING: 0, OUT_OF_RANGE: 0, CONFLICT: 2, NOT_READ: 0 }, stored_now: { NOT_LOADED: 100 } },
  effects: { closed_days_in_window: 2, closed_days_with_changes: 1, not_written: ["d0_snapshots"] } };

function sqlBackend(preview: any) {
  return mock((u, c) => {
    if (u.startsWith("/api/sync/status")) return SYNC;
    if (u.startsWith("/api/sql-sources")) return { history: { kind: "history", mode: "TABLE", versions: [] }, d0: { kind: "d0", mode: "TABLE", versions: [] } };
    if (u === "/api/sync/backfill/preview" && c.method === "GET") return { status: "NONE" };
    if (u === "/api/sync/backfill/preview" && c.method === "POST") return preview;
    if (u === "/api/sync/backfill" && c.method === "POST") return { id: "JOB-1", status: "PENDING" };
    return {};
  });
}

const setDates = (r: any, start: string, end: string) => {
  const inputs = r.container.querySelectorAll("input[type=date]");
  fireEvent.change(inputs[inputs.length - 2], { target: { value: start } });
  fireEvent.change(inputs[inputs.length - 1], { target: { value: end } });
};

describe("v1.2.9 controlled backfill", () => {
  it("cannot re-read before a READY preview of the same dates, shows what would change, then sends the preview id", async () => {
    window.confirm = vi.fn(() => true);
    const calls = sqlBackend(PREVIEW);
    const r = await act(async () => render(wrap(<SqlSources />)));
    await waitFor(() => expect(screen.getByTestId("bf-preview-btn")).toBeTruthy());
    setDates(r, "2026-03-19", "2026-10-18");
    expect((screen.getByTestId("bf-run") as HTMLButtonElement).disabled).toBe(true);           // no preview yet
    await act(async () => { fireEvent.click(screen.getByTestId("bf-preview-btn")); });
    await waitFor(() => expect(screen.getByTestId("bf-preview-table")).toBeTruthy());
    expect(screen.getByTestId("bf-changes").textContent).toBe("0 / 7 / 90 / 3");
    expect(screen.getByTestId("bf-oh").textContent).toContain("CONFLICT 2");
    expect(calls.filter((c) => c.url === "/api/sync/backfill").length).toBe(0);              // a preview never runs the load
    // other dates than the preview: the load stays disabled
    setDates(r, "2026-03-20", "2026-10-18");
    expect((screen.getByTestId("bf-run") as HTMLButtonElement).disabled).toBe(true);
    setDates(r, "2026-03-19", "2026-10-18");
    expect((screen.getByTestId("bf-run") as HTMLButtonElement).disabled).toBe(false);
    await act(async () => { fireEvent.click(screen.getByTestId("bf-run")); });
    expect(window.confirm).toHaveBeenCalled();
    expect(String((window.confirm as any).mock.calls[0][0])).toContain("7");
    const run = calls.find((c) => c.url === "/api/sync/backfill" && c.method === "POST")!;
    expect(run.body).toEqual({ start: "2026-03-19", end: "2026-10-18", preview_id: "BFP-1" });
  });

  it("does nothing when the confirmation is cancelled and shows a failed preview without a run button", async () => {
    window.confirm = vi.fn(() => false);
    const calls = sqlBackend(PREVIEW);
    const r = await act(async () => render(wrap(<SqlSources />)));
    await waitFor(() => expect(screen.getByTestId("bf-preview-btn")).toBeTruthy());
    setDates(r, "2026-03-19", "2026-10-18");
    await act(async () => { fireEvent.click(screen.getByTestId("bf-preview-btn")); });
    await waitFor(() => expect((screen.getByTestId("bf-run") as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(screen.getByTestId("bf-run")); });
    expect(calls.filter((c) => c.url === "/api/sync/backfill").length).toBe(0);
    const f = render(wrap(<BackfillPreview p={{ preview_id: "BFP-2", status: "FAILED", error: { code: "BQ_AGGREGATE_INVALID", detail: "x" } }} />));
    expect(f.container.textContent).toContain("BQ_AGGREGATE_INVALID");
    expect(f.container.querySelector("[data-testid=bf-preview-table]")).toBeNull();
    const w = render(wrap(<BackfillPreview p={{ ...PREVIEW, warnings: [{ code: "YESTERDAY_NOT_CONFIRMED", day: "2026-10-18" }] }} />));
    expect(w.container.querySelector("[data-testid=bf-warning]")?.textContent).toContain("chưa có tín hiệu hoàn tất");
  });
});

const BQ = "BIGQUERY:p.d.t";
const DAY = { run_date: "2026-10-18", target_date: "2026-10-19", forecast_run_id: "FCR-B", session_started_at: "2026-10-18T02:00:00+00:00",
  published_at: "2026-10-18T02:10:00+00:00", model_version: "MV-B", n_rows: 2, capture_mode: "AT_PUBLISH", sessions_count: 1 };
const HROWS = [
  { run_date: "2026-10-18", target_date: "2026-10-19", sku_id: "SKU-1", fc_id: "HN", yhat: 2.6, forecast_qty: 3, actual: 2, deviation: 1, row_wape: 0.5,
    actual_status: "PROVISIONAL", actual_reason: "D0_INTRADAY", product_name: null, forecast_run_id: "FCR-B", model_version: "MV-B",
    session_started_at: "2026-10-18T02:00:00+00:00", actual_as_of: "2026-10-19T01:00:00+00:00" },
  { run_date: "2026-10-18", target_date: "2026-10-19", sku_id: "SKU-2", fc_id: "HN", yhat: 0.4, forecast_qty: 0, actual: 1, deviation: -1, row_wape: 1,
    actual_status: "PROVISIONAL", actual_reason: "D0_INTRADAY", product_name: null, forecast_run_id: "FCR-B", model_version: "MV-B",
    session_started_at: "2026-10-18T02:00:00+00:00", actual_as_of: "2026-10-19T01:00:00+00:00" },
];

describe("v1.2.9 history page: whole-number forecast", () => {
  it("shows the whole number (zero allowed), its deviation, the stored model value on hover and the rule", async () => {
    mock((u) => {
      if (u.startsWith("/api/history/overview")) return { scope_key: BQ, data_source: "BIGQUERY", active_scope_key: BQ, today: "2026-10-19",
        today_session: DAY, scopes: [{ scope_key: BQ, data_source: "BIGQUERY", n_days: 1, active: true }], days: [DAY], fcs: ["HN"],
        completion_signal_configured: false };
      if (u.startsWith("/api/history/summary")) return { scope_key: BQ, data_source: "BIGQUERY", today: "2026-10-19", matching_skus: null,
        daily: [{ ...DAY, has_history: true, n_rows: 2, forecast: 3, actual: 3, deviation: 0, actual_status: "PROVISIONAL" }],
        kpi: { n_rows: 2, n_rows_compared: 2, days_with_history: 1, days_compared: 1, forecast_total: 3, actual_total: 3, forecast_compared: 3,
          deviation: 0, abs_error: 2, wape: 0.6667, bias: 0, status: "PROVISIONAL", notes: [] }, sessions: [] };
      if (u.startsWith("/api/history/rows")) return { total: 2, rows: HROWS };
      return {};
    });
    const r = await act(async () => render(wrap(<ForecastHistory />)));
    await waitFor(() => expect(r.container.querySelectorAll("[data-testid=fh-forecast-qty]").length).toBe(2));
    const cells = [...r.container.querySelectorAll("[data-testid=fh-forecast-qty]")];
    expect(cells.map((c) => c.textContent)).toEqual(["3", "0"]);
    expect(cells[0].getAttribute("title")).toContain("2,6");
    const rows = [...r.container.querySelectorAll("tbody tr")].map((tr) => tr.textContent ?? "");
    expect(rows.some((t) => t.includes("+1"))).toBe(true);
    expect(rows.some((t) => t.includes("2,6"))).toBe(false);                                   // no decimal in the table
    expect(screen.getByTestId("fh-rules").textContent).toContain("số lượng nguyên");
  });
});
