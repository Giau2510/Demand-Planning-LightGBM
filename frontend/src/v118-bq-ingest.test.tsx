import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import BigQuery, { IngestCheckView, ValidationView } from "./pages/BigQuery";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });

type Call = { url: string; method: string; headers: any };
function mock(routes: Record<string, any>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    calls.push({ url: u, method: init?.method ?? "GET", headers: init?.headers ?? {} });
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => u.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const REPORT = "bq-trung-lap_2026-01-01_2026-10-15_20261016-140000.xlsx";
const DUP = { rows_checked: 1300000, duplicate_groups: 432, duplicate_rows: 877, extra_duplicate_rows: 445,
  columns: [{ column: "so_code" }, { column: "demand_quantity" }, { column: "sales_price" }], not_compared: ["seller_class", "refresh_time"],
  report: { format: "xlsx", file: REPORT }, ingest_status: "BLOCKED" };
const step = (s: string, status: string, extra: any = {}) => ({ step: s, status, ...extra });
const blocked = {
  status: "BLOCKED", checked_at: "2026-10-16T07:00:00+00:00", table: "p.d.t", written: false, duplicate_check: DUP,
  readiness: { active_source: "DEMO", production_enabled: false, validation_current: false, d1_schedule_enabled: false },
  steps: [step("auth", "PASSED", { account: "user@example.com" }),
    step("window", "PASSED", { start: "2026-01-01", end: "2026-10-15", today_excluded: "2026-10-16", full_reload: true }),
    step("mapping", "PASSED", { compared_columns: ["so_code", "demand_quantity", "sales_price"] }),
    step("duplicates", "BLOCKED", { error: { code: "BQ_DATA_DUPLICATES", vi: "Nguồn có dòng trùng hoàn toàn — đã chặn", en: "dups", detail: "groups=432" } }),
    ...["aggregate", "output_checks", "reconciliation", "compare", "write"].map((s) => step(s, "NOT_RUN"))],
};
const ready = {
  ...blocked, status: "READY", duplicate_check: undefined,
  steps: [step("auth", "PASSED"), step("window", "PASSED", { start: "2026-01-01", end: "2026-10-15", today_excluded: "2026-10-16" }),
    step("mapping", "PASSED", { compared_columns: [] }),
    step("duplicates", "PASSED", { ...DUP, duplicate_groups: 0, duplicate_rows: 0, extra_duplicate_rows: 0, report: undefined }),
    step("aggregate", "PASSED", { rows_aggregated: 812345, qty_total: 9876543.5 }), step("output_checks", "PASSED"),
    step("reconciliation", "PASSED", { rows_read: 1300000, rows_valid: 1299990, rows_excluded: 10 }),
    step("compare", "PASSED", { series_days_new: 812345, series_days_updated: 0, series_days_unchanged: 0, series_days_removed: 0 }),
    step("write", "NOT_RUN", { reason: "DRY_RUN" })],
};

describe("BigQuery ingest: duplicate gate and trial aggregation", () => {
  it("blocked: shows groups / rows / extra rows, the report download and the steps that did not run", () => {
    render(wrap(<IngestCheckView r={blocked} />));
    const txt = screen.getByTestId("bq-ingest-result").textContent!;
    expect(txt).toContain("Bị chặn do dòng trùng hoàn toàn");
    expect(txt).toContain("Tải báo cáo dòng trùng");
    const counts = screen.getByTestId("bq-dup-check").textContent!;
    for (const n of ["432", "877", "445", "1.300.000"]) expect(counts).toContain(n);
    expect(counts).toContain("seller_class, refresh_time");
    const link = screen.getByTestId("bq-dup-report").querySelector("a")!;
    expect(link.getAttribute("href")).toBe(`/api/bigquery/duplicate-reports/${REPORT}`);
    const steps = screen.getByTestId("bq-ingest-steps").textContent!;
    expect(steps).toContain("Bị chặn");
    expect(steps).toContain("Chưa chạy");
    expect(steps).toContain("Dòng trùng hoàn toàn (dữ liệu gốc, trước tổng hợp)");
    expect(txt).toContain("16/10/2026");                                      // today excluded, Vietnam date
    expect(screen.queryByTestId("bq-ingest-numbers")).toBeNull();             // nothing aggregated
  });

  it("ready: shows rows after aggregation, total demand and that nothing was written", () => {
    render(wrap(<IngestCheckView r={ready} />));
    const nums = screen.getByTestId("bq-ingest-numbers").textContent!;
    expect(nums).toContain("812.345");
    expect(nums).toContain("9.876.543,5");
    expect(screen.getByTestId("bq-ingest-result").textContent).toContain("Chưa ghi gì");
  });

  it("yesterday not in the source yet: warning, a real D-1 would not write", () => {
    const r = { ...ready, status: "SOURCE_INCOMPLETE",
      steps: [...ready.steps.slice(0, 2), step("completeness", "WARNING", { day: "2026-10-15", completion_signal: null,
        sufficiency: { ok: false, rows_for_day: 0, avg_previous_7d: 18817.1, ratio_required: 0.5 } }), ...ready.steps.slice(2)] };
    render(wrap(<IngestCheckView r={r} />));
    expect(screen.getByTestId("bq-ingest-result").textContent).toContain("Nguồn chưa đủ dữ liệu ngày hôm qua");
    expect(screen.getByTestId("bq-ingest-note").textContent).toContain("KHÔNG ghi");
    const steps = screen.getByTestId("bq-ingest-steps").textContent!;
    expect(steps).toContain("Chưa đủ");
    expect(steps).toContain("15/10/2026: 0 dòng");
    expect(steps).toContain("18.817");
  });

  it("a CSV fallback is shown when the .xlsx could not be written", () => {
    const r = { ...blocked, duplicate_check: { ...DUP, report: { format: "csv", files: ["a_Summary.csv", "a_Duplicate_Rows.csv"], xlsx_error: "OSError: disk full" } } };
    render(wrap(<IngestCheckView r={r} />));
    const rep = screen.getByTestId("bq-dup-report");
    expect(rep.textContent).toContain("disk full");
    expect(rep.querySelectorAll("a")).toHaveLength(2);
  });

  it("full-period validation shows the duplicate counts and the report", () => {
    const v = { passed: false, checked_at: "2026-10-16T07:00:00+00:00", range: { start: "2026-01-01", end: "2026-10-16" },
      stats: {}, reconciliation: { rows_ok: true, qty_ok: true }, exclusions: {}, duplicate_check: DUP,
      blocking_issues: [{ code: "EXACT_DUPLICATES", detail: { rows: 445, groups: 432 } }], warnings: [] };
    render(wrap(<ValidationView v={v} current={true} />));
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("445");
    expect(screen.getByTestId("bq-dup-report").querySelector("a")!.getAttribute("href")).toContain(REPORT);
  });

  it("the BigQuery page runs the check with the protection header and lists recent reports", async () => {
    const calls = mock({
      "/api/bigquery/status": { settings: { dataset_id: "d", source_table: "t", project_id: "p", location: "asia-southeast1", partition_column: "",
        created_at_is_utc: true, auth_method: "ADC", maximum_bytes_billed: 1, initial_history_days: 730, history_start_date: "2026-01-01",
        exact_duplicate_policy: "BLOCK", completion_table: "", completion_date_column: "", completion_status_column: "", completion_status_value: "",
        field_mapping: {}, reference_mapping: {}, schema_snapshot: [] }, checks: {}, activation: { requirements: {}, ready: false },
        ingest_check: blocked, duplicate_reports: [{ name: REPORT, size: 2048, modified: "2026-10-16T07:00:00+00:00" }] },
      "/api/bigquery/ingest-check": blocked,
      "/api/bigquery/identity": { runtime: { windows_user: "user", computer: "PC", appdata: "C:\\x", adc_path_checked: "C:\\x\\adc.json",
        adc_exists: true, google_application_credentials_set: false, google_application_credentials_exists: false, gcloud_on_path: false,
        effective_method: "ADC", note: { vi: "x", en: "x" } },
        oauth: { configured: false, client_id: "", client_secret_set: false, status: "NOT_SIGNED_IN", email: null, error: null } },
    });
    await act(async () => { render(wrap(<BigQuery />)); });
    await waitFor(() => expect(screen.getByTestId("bq-ingest-check")).toBeTruthy());
    expect(screen.getByTestId("bq-dup-reports").textContent).toContain(REPORT);
    expect(screen.getByTestId("bq-ingest-result")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByTestId("bq-ingest-check")); });
    const post = calls.find((c) => c.url.includes("/api/bigquery/ingest-check") && c.method === "POST")!;
    expect(post.headers["X-DF-Client"]).toBe("web");
  });
});
