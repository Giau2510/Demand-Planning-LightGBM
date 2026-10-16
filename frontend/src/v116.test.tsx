import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import GoogleAuth from "./pages/GoogleAuth";
import SqlSources from "./pages/SqlSources";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

function mock(routes: Record<string, any>) {
  const calls: { url: string; method: string; body: any }[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    calls.push({ url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null });
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => u.includes(k));
    const v = key ? routes[key] : {};
    return new Response(JSON.stringify(typeof v === "function" ? v(u) : v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const runtime = { windows_user: "Giau Vo", computer: "LOG-PC", appdata: "C:\\Users\\Giau Vo\\AppData\\Roaming",
  adc_path_checked: "C:\\Users\\Giau Vo\\AppData\\Roaming\\gcloud\\application_default_credentials.json", adc_exists: false,
  google_application_credentials_set: false, google_application_credentials_exists: false, gcloud_on_path: false,
  effective_method: "ADC", note: { vi: "ADC của tài khoản Windows khác (ví dụ Administrator) không dùng được.", en: "x" } };

describe("v1.1.6 Google sign-in + SQL feeds", () => {
  it("shows which Windows account runs the app, where ADC is looked up, and that an OAuth client is missing", async () => {
    mock({ "/api/bigquery/identity": { runtime, oauth: { configured: false, client_id: "", client_secret_set: false, status: "NOT_SIGNED_IN", email: null, error: null } } });
    await act(async () => { render(wrap(<GoogleAuth />)); });
    await waitFor(() => expect(screen.getByTestId("ga-identity")).toBeTruthy());
    const txt = screen.getByTestId("ga-identity").textContent!;
    expect(txt).toContain("Giau Vo");
    expect(txt).toContain("application_default_credentials.json");
    expect(txt).toContain("không có");
    expect(txt).toContain("Administrator");
    expect(screen.getByTestId("ga-not-configured")).toBeTruthy();
    expect((screen.getByTestId("ga-signin") as HTMLButtonElement).disabled).toBe(true);
  });

  it("signed in: email shown, secret field is write-only and never prefilled", async () => {
    mock({ "/api/bigquery/identity": { runtime: { ...runtime, effective_method: "OAUTH_USER" },
      oauth: { configured: true, client_id: "1-a.apps.googleusercontent.com", client_secret_set: true, status: "SIGNED_IN",
        email: "planner@buymed.example", signed_in_at: "2026-10-15T07:00:00+00:00", error: null } } });
    await act(async () => { render(wrap(<GoogleAuth />)); });
    await waitFor(() => expect(screen.getByTestId("ga-status").textContent).toContain("planner@buymed.example"));
    expect(screen.getByTestId("ga-status").textContent).toContain("Đã đăng nhập");
    expect((screen.getByTestId("ga-secret") as HTMLInputElement).value).toBe("");
    expect((screen.getByTestId("ga-signout") as HTMLButtonElement).disabled).toBe(false);
    expect(document.body.textContent).toContain("đã lưu");
  });

  it("SQL page: the user's D0 SQL is shown as given, not active, with static notes; validate calls BigQuery dry-run endpoint", async () => {
    const d0sql = "SELECT\n  a.fc_code,\n  b.sales_price,\nFROM `p.d.fact_order` a";
    const view = (active: number | null, status: string | null) => ({
      kind: "d0", mode: "SQL", active_version_id: active, active: active ? { id: 1, sha256: "b9d6d9f56a091d86", validation: { status: "VALID", checked_at: "2026-10-15T07:00:00+00:00", estimated_bytes: 1000 } } : null,
      key_columns: [], effective_key_columns: ["so_code", "sku_code", "fc_code", "created_date"], key_duplicate_policy: "BLOCK", needed_outputs: [],
      versions: [{ id: 1, sql: d0sql, sha256: "b9d6d9f56a091d8630b6", saved_at: null, note: "SQL D0 do người dùng cung cấp",
        validation: status ? { status, error: status === "INVALID" ? { code: "BQ_SQL_ERROR", vi: "Lỗi cú pháp", en: "x", detail: "Syntax error at [4:1]" } : null } : null,
        static_check: { ok: true, errors: [], notes: [{ code: "TRAILING_COMMA_BEFORE_FROM", line: 3, detail: "Chỉ dry-run BigQuery xác định" }] } }],
    });
    const hist = { ...view(null, null), kind: "history", mode: "TABLE", versions: [] };
    let validated = false;
    const calls = mock({
      "/api/sql-sources/d0/versions/1/validate": () => { validated = true; return { ...view(null, "INVALID"), validation: { status: "INVALID", statement_type: null, error: { code: "BQ_SQL_ERROR", vi: "Lỗi cú pháp SQL", en: "x", detail: "Syntax error at [4:1]" } } }; },
      "/api/sql-sources": () => ({ history: hist, d0: validated ? view(null, "INVALID") : view(null, null) }),
      "/api/sync/status": { timezone: "Asia/Ho_Chi_Minh", notes: { vi: "độc lập", en: "x" }, bigquery_production_enabled: false,
        jobs: { D1_SYNC: { schedule: { times: ["01:00"] }, next_runs: ["2026-10-16T01:00:00+07:00"], applies: false, last_run: null, feed: { mode: "TABLE" } },
                D0_SYNC: { schedule: { times: ["08:00", "10:00"] }, next_runs: ["2026-10-15T16:00:00+07:00"], applies: true, last_run: null, feed: { mode: "SQL", active_version_id: null } } } },
    });
    await act(async () => { render(wrap(<SqlSources />)); });
    await waitFor(() => expect(screen.getByTestId("sql-d0")).toBeTruthy());
    expect((screen.getByLabelText("editor-d0") as HTMLTextAreaElement).value).toBe(d0sql);         // verbatim
    expect(screen.getByTestId("sql-active-d0").textContent).toContain("Chưa có phiên bản nào được kiểm tra đạt");
    expect(screen.getByTestId("sql-static-d0").textContent).toContain("TRAILING_COMMA_BEFORE_FROM");
    expect(screen.getByTestId("sync-status").textContent).toContain("08:00, 10:00");
    await act(async () => { fireEvent.click(screen.getByTestId("sql-validate-d0-1")); });
    await waitFor(() => expect(screen.getByTestId("sql-result-d0").textContent).toContain("Syntax error at [4:1]"));
    expect(calls.some((c) => c.method === "POST" && c.url.includes("/api/sql-sources/d0/versions/1/validate"))).toBe(true);
    expect(screen.getByTestId("sql-active-d0").textContent).toContain("Chưa có phiên bản nào được kiểm tra đạt");   // still not active
    const row = document.querySelector("[data-testid=sql-versions-d0] tbody tr") as HTMLElement;
    expect(row.dataset.status).toBe("INVALID");
    // the D0 schedule is OFF; 1.1.8: it can only be switched on the Data schedules page (readiness checked there),
    // so this page shows the state and a link, never a second switch
    const sched = screen.getByTestId("sql-schedule-d0");
    expect(sched.textContent).toContain("ĐANG TẮT");
    expect(sched.querySelector("button")).toBeNull();
    expect((sched.querySelector("a") as HTMLAnchorElement).getAttribute("href")).toBe("/schedules");
  });

  it("access check: gates are shown separately; signed in but missing BigQuery permission", async () => {
    mock({
      "/api/bigquery/identity": { runtime: { ...runtime, effective_method: "OAUTH_USER" },
        oauth: { configured: true, client_id: "1-a.apps.googleusercontent.com", client_secret_set: true, status: "SIGNED_IN", email: "p@b.example", error: null } },
      "/api/bigquery/access-check": { passed: false, first_failure: { gate: "query_job", code: "BQ_PERMISSION_DENIED" },
        gates: [{ gate: "auth", status: "PASS" }, { gate: "api_and_dataset", status: "PASS" }, { gate: "location", status: "PASS" },
          { gate: "table_metadata", status: "PASS" }, { gate: "query_job", status: "FAIL", code: "BQ_PERMISSION_DENIED", detail: "bigquery.jobs.create" },
          { gate: "schema_mapping", status: "NOT_RUN" }] },
    });
    await act(async () => { render(wrap(<GoogleAuth />)); });
    await waitFor(() => expect(screen.getByTestId("ga-access")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("ga-access")); });
    await waitFor(() => expect(screen.getByTestId("ga-gates")).toBeTruthy());
    expect(screen.getByTestId("ga-access-summary").textContent).toContain("THIẾU QUYỀN");
    const st = [...document.querySelectorAll("[data-testid=ga-gates] tr")].map((r) => (r as HTMLElement).dataset.status);
    expect(st).toEqual(["PASS", "PASS", "PASS", "PASS", "FAIL", "NOT_RUN"]);
    expect(screen.getByTestId("ga-gates").textContent).toContain("bigquery.jobs.create");
  });
});
