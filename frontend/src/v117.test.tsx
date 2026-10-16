import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import GoogleAuth from "./pages/GoogleAuth";
import Performance from "./pages/Performance";

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

const CATALOG = {
  PROMOTION_REVIEW_REQUIRED: { code: "PROMOTION_REVIEW_REQUIRED", vi: "Model mới KHÔNG tự thay model đang dùng", en: "x" },
  BQ_PERMISSION_DENIED: { code: "BQ_PERMISSION_DENIED", vi: "THIẾU QUYỀN: cần roles/bigquery.jobUser", en: "x" },
};
const m = (wape: number) => ({ wape, mae: 1, bias: 0.01, mape: 0.2, mape_points: 90, n_points: 100 });

describe("v1.1.7 incumbent protection + Google access", () => {
  it("a candidate is shown as awaiting review with the same-fold comparison; promoting needs an explicit click", async () => {
    const cand = { id: "TRN-C", status: "REJECTED", reject_reason: "PROMOTION_REVIEW_REQUIRED", model_version: "MV-C", data_source: "DEMO",
      started_at: "2026-10-15T07:00:00+00:00", metrics: m(0.2), can_promote: true, in_use: false, incumbent_training_run_id: "TRN-I",
      train_start: "2026-01-01", train_end: "2026-10-14",
      quality_gate: { passed: true, checks: [], thresholds_approved_by_business: false,
        promotion: { decision: "REVIEW_REQUIRED", verdict: "BETTER", candidate: m(0.2), incumbent: m(0.3), incumbent_model_version: "MV-I" } },
      backtest: { reliable: true, config: { folds: 12, folds_evaluated: 7, horizon_days: 30, span_days: 210, first_day: "2026-03-20", last_day: "2026-10-15" },
        metrics: { pooled: m(0.2), baseline: m(0.4), by_method: {} }, folds: [], notes: [] } };
    window.confirm = vi.fn(() => true);
    const calls = mock({ "/api/messages": CATALOG, "/api/training-runs?limit": [cand], "/api/training-runs/TRN-C/promote": { status: "PUBLISHED" },
      "/api/training-runs/TRN-C": cand });
    await act(async () => { render(wrap(<Performance />)); });
    await waitFor(() => expect(screen.getByTestId("promotion-verdict")).toBeTruthy());
    expect(document.body.textContent).toContain("Chờ duyệt thay model");
    expect(screen.getByTestId("promotion-verdict").textContent).toContain("TỐT HƠN");
    expect(screen.getByTestId("bt-span").textContent).toContain("7 × 30");
    expect(screen.getByTestId("bt-span").textContent).toContain("210");
    expect(calls.some((c) => c.method === "POST")).toBe(false);          // nothing is promoted by opening the page
    await act(async () => { fireEvent.click(screen.getByTestId("promote")); });
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.includes("/promote"))).toBe(true));
    expect(calls.find((c) => c.url.includes("/promote"))!.body).toEqual({ confirm: true });
  });

  it("Google page: imports the client JSON once, shows the action for a failed gate and an administrator checklist", async () => {
    const runtime = { windows_user: "Giau Vo", computer: "LOG-PC", appdata: "C:\\x", adc_path_checked: "C:\\x\\adc.json", adc_exists: false,
      google_application_credentials_set: false, google_application_credentials_exists: false, gcloud_on_path: false,
      effective_method: "OAUTH_USER", note: { vi: "n", en: "n" } };
    const ident = { runtime, target: { project: "lakehouse-prod-394907", location: "asia-southeast1", dataset: "gold_buymed_vn2", table: "demand_planing_lightgbm" },
      oauth: { configured: true, client_id: "1-a.apps.googleusercontent.com", client_secret_set: true, status: "SIGNED_IN", email: "planner@buymed.example",
        signed_in_at: "2026-10-15T07:00:00+00:00", verified_at: "2026-10-15T07:05:00+00:00", error: null } };
    const gates = { passed: false, first_failure: { gate: "query_job", code: "BQ_PERMISSION_DENIED" },
      gates: [{ gate: "auth", status: "PASS", account: "planner@buymed.example" }, { gate: "api_and_dataset", status: "PASS" }, { gate: "location", status: "PASS" },
        { gate: "table_metadata", status: "PASS" }, { gate: "query_job", status: "FAIL", code: "BQ_PERMISSION_DENIED", detail: "bigquery.jobs.create denied" },
        { gate: "schema_mapping", status: "NOT_RUN" }] };
    const calls = mock({ "/api/messages": CATALOG, "/api/bigquery/identity": ident, "/api/bigquery/access-check": gates,
      "/api/bigquery/oauth/client-file": ident.oauth });
    await act(async () => { render(wrap(<GoogleAuth />)); });
    await waitFor(() => expect(screen.getByTestId("ga-verified")).toBeTruthy());
    const file = new File(['{"installed": {"client_id": "1-a.apps.googleusercontent.com", "client_secret": "S"}}'], "client.json", { type: "application/json" });
    await act(async () => { fireEvent.change(screen.getByTestId("ga-client-file"), { target: { files: [file] } }); });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/oauth/client-file"))).toBe(true));
    expect(calls.find((c) => c.url.includes("/oauth/client-file"))!.body.content).toContain("installed");
    await act(async () => { fireEvent.click(screen.getByTestId("ga-access")); });
    await waitFor(() => expect(screen.getByTestId("ga-access-summary").textContent).toContain("THIẾU QUYỀN"));
    expect(screen.getByTestId("ga-fix-query_job").textContent).toContain("roles/bigquery.jobUser");
    const admin = screen.getByTestId("ga-admin").textContent!;
    expect(admin).toContain("roles/bigquery.dataViewer");
    expect(admin).toContain("lakehouse-prod-394907.gold_buymed_vn2");
    expect(admin).toContain("planner@buymed.example");
    expect(admin).not.toMatch(/secret\s*:/i);
  });
});
