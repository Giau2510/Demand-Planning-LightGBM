import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import Schedules from "./pages/Schedules";
import SqlSources, { D0Mapping } from "./pages/SqlSources";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); });

type Call = { url: string; method: string; body: any };
function mock(routes: Record<string, any>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length)
      .find((k) => (k.includes(" ") ? c.method === k.split(" ")[0] && u.includes(k.split(" ")[1]) : u.includes(k)));
    let v = key ? routes[key] : {};
    if (typeof v === "function") v = v(c);
    return new Response(JSON.stringify(v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const FIELDS = ["sku_id", "fc_id", "order_qty", "order_date", "created_at", "order_id", "source_updated_at"]
  .map((f) => ({ field: f, essential: ["sku_id", "fc_id", "order_qty", "order_date", "created_at"].includes(f), types: ["STRING"] }));
const MAPPING = { sku_id: { column: "sku_code", usage: "REQUIRED" }, fc_id: { column: "fc_code", usage: "REQUIRED" },
  order_qty: { column: "demand_quantity", usage: "REQUIRED" }, order_date: { column: "created_date", usage: "OPTIONAL" },
  created_at: { column: null, usage: "UNUSED" }, order_id: { column: "so_code", usage: "OPTIONAL" },
  source_updated_at: { column: null, usage: "OPTIONAL" } };
const NOT_VALIDATED = { code: "SQL_NOT_VALIDATED", vi: "Chưa có phiên bản SQL nào được BigQuery xác nhận cho nguồn này — job không chạy.",
  en: "x", detail: "d0: v2 UNCHECKED, v1 UNCHECKED" };
function d0view(extra: any = {}) {
  return { mapping: MAPPING, used: {}, fields: FIELDS, missing: [], key_columns: ["so_code", "sku_code", "fc_code", "created_date"],
    mapping_hash: "abc123", mode: "SQL", table_id: "p.d.t", ready: false, reasons: [NOT_VALIDATED], notes: [], ...extra };
}

describe("v1.2.1 D-0 mapping", () => {
  it("shows the precise reason, saves only the D-0 mapping and fills a suggestion from the real schema", async () => {
    const calls = mock({
      "PUT /api/bigquery/d0-mapping": (c: Call) => d0view({ mapping: c.body.mapping }),
      "POST /api/bigquery/d0-mapping/suggest": { mapping: { ...MAPPING, sku_id: { column: "ma_sku", usage: "REQUIRED" } },
        columns: [{ name: "ma_sku", type: "STRING" }, { name: "kho", type: "STRING" }], notes: [] },
    });
    const reload = vi.fn();
    await act(async () => { render(wrap(<D0Mapping d0={d0view()} reload={reload} sqlVersionId={3} />)); });
    const rd = screen.getByTestId("d0-readiness").textContent ?? "";
    expect(rd).toContain("Chưa có phiên bản SQL nào được BigQuery xác nhận");
    expect(rd).toContain("SQL_NOT_VALIDATED");
    expect(rd).toContain("v2 UNCHECKED, v1 UNCHECKED");
    expect((screen.getByTestId("d0m-save") as HTMLButtonElement).disabled).toBe(true);         // nothing changed yet
    fireEvent.change(screen.getByLabelText("d0-col-fc_id"), { target: { value: "kho" } });
    fireEvent.click(screen.getByTestId("d0m-save"));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/api/bigquery/d0-mapping"))).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body.mapping.fc_id).toEqual({ column: "kho", usage: "REQUIRED" });
    expect(put.body.mapping.created_at).toEqual({ column: null, usage: "UNUSED" });
    expect(Object.keys(put.body)).toEqual(["mapping"]);                                         // never the D-1 mapping
    expect(calls.some((c) => c.url.includes("/api/settings") || c.url.includes("/api/bigquery/mapping"))).toBe(false);
    await waitFor(() => expect(reload).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("d0m-suggest-table"));
    await waitFor(() => expect((screen.getByLabelText("d0-col-sku_id") as HTMLInputElement).value).toBe("ma_sku"));
    expect(calls.find((c) => c.url.endsWith("/suggest"))!.body).toEqual({ source: "table" });
  });

  it("lists missing essential fields and marks a version validated for another mapping", async () => {
    const version = (id: number, status: string | null, current: boolean) => ({ id, sha256: `${id}`.repeat(64), note: null, saved_at: null,
      sql: "SELECT 1", static_check: { ok: true, errors: [], notes: [] }, validated_for_current_mapping: current,
      validation: status ? { status, checked_at: "2026-10-17T08:00:00+00:00", estimated_bytes: 100,
        execution: { day: "2026-10-17", rows_read: 10, rows_valid: 9, rows_error: 1, rows_other_day: 0, n_series: 3, qty_valid: 20,
          estimated_bytes: 100, blocking_issues: [{ code: "KEY_NOT_UNIQUE", detail: { rows: "48" } }], warnings: [] } } : null });
    const feed = (kind: string, extra: any = {}) => ({ kind, mode: kind === "d0" ? "SQL" : "TABLE", active_version_id: kind === "d0" ? 3 : null,
      active: null, key_columns: [], effective_key_columns: [], key_duplicate_policy: "BLOCK", schedule_enabled: false,
      versions: kind === "d0" ? [version(3, "VALID", false), version(2, null, false)] : [], needed_outputs: [], ...extra });
    mock({
      "/api/sync/status": { timezone: "Asia/Ho_Chi_Minh", notes: { vi: "", en: "" }, jobs: {}, bigquery_production_enabled: true },
      "POST /api/sql-sources/d0/versions/3/validate": { ...feed("d0", { d0: d0view() }), validation: version(3, "VALID", true).validation },
      "/api/sql-sources": { history: feed("history"), d0: feed("d0", { d0: d0view({ missing: ["fc_id"], reasons: [
        { code: "D0_REVALIDATE_REQUIRED", vi: "SQL/bảng D-0 đã được xác nhận cho một ánh xạ hoặc khóa D-0 khác", en: "x", detail: "v3" }] }) }) },
    });
    await act(async () => { render(wrap(<SqlSources />)); });
    await waitFor(() => expect(screen.getByTestId("d0-mapping")).toBeTruthy());
    expect(screen.getByTestId("d0m-missing").textContent).toContain("fc_id");
    expect(screen.getByTestId("d0-readiness").textContent).toContain("D0_REVALIDATE_REQUIRED");
    expect(screen.getByTestId("sql-stale-3")).toBeTruthy();
    fireEvent.click(screen.getByTestId("sql-validate-d0-3"));
    await waitFor(() => expect(screen.getByTestId("sql-execution")).toBeTruthy());
    expect(screen.getByTestId("sql-execution").textContent).toContain("2026-10-17");
    expect(screen.getByTestId("sql-execution-issues").textContent).toContain("KEY_NOT_UNIQUE");
  });
});

describe("v1.2.1 training readiness shows today's D-1", () => {
  it("shows the note with its detail (which D-1 job, when, data up to)", async () => {
    const reason = (code: string, vi: string, detail: string | null = null) => ({ code, vi, en: vi, detail });
    const fl = (f: string, enabled: boolean, ready: boolean, config: any, readiness: any) => ({ flow: f, enabled, state: enabled ? (ready ? "ON" : "ON_NOT_READY") : "OFF",
      enabled_at: null, config, timezone: "Asia/Ho_Chi_Minh", readiness: { ready, source: "BIGQUERY", ...readiness }, next_runs: [], last_run: null, last_skipped: null, history: [] });
    mock({ "/api/schedules": { timezone: "Asia/Ho_Chi_Minh", now_vn: "2026-10-17T15:00:00+07:00", active_source: "BIGQUERY",
      data_window: { start: "2026-01-01", end: "2026-10-16" }, scheduler: { running: true, last_tick: null, loaded: null }, policy: {},
      flows: {
        d1: fl("d1", false, true, { time: "03:00", fallback_time: "06:00", poll_interval_minutes: 30 }, { reasons: [], notes: [] }),
        d0: fl("d0", false, false, { times: ["08:00"], catchup_policy: "LATEST_ONCE" }, { reasons: [reason("SQL_NOT_VALIDATED", "Chưa có phiên bản SQL", "d0: v2 UNCHECKED, v1 UNCHECKED")], notes: [] }),
        train: fl("train", true, true, { time: "09:00", catchup_policy: "RUN_ONCE" }, { reasons: [],
          notes: [reason("D1_TODAY_SUCCEEDED", "D-1 hôm nay đã thành công", "JOB-20261017012623-2A31B7 (MANUAL, 08:30, data to 2026-10-16)")] }),
      } } });
    await act(async () => { render(wrap(<Schedules />)); });
    await waitFor(() => expect(screen.getByTestId("schedules-page")).toBeTruthy());
    const train = screen.getByTestId("flow-train").textContent ?? "";
    expect(train).toContain("D-1 hôm nay đã thành công");
    expect(train).toContain("JOB-20261017012623-2A31B7 (MANUAL, 08:30, data to 2026-10-16)");
    expect(screen.getByTestId("flow-d0").textContent).toContain("d0: v2 UNCHECKED, v1 UNCHECKED");
    expect(screen.getByTestId("state-d0").textContent).toContain("Tắt");
  });
});
