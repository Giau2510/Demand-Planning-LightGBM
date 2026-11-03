import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";
import DailyForecast, { isSel2Run, rowSourceKind } from "./pages/DailyForecast";
import ForecastSource from "./pages/ForecastSource";

// 1.4.0 SEL2 UI: forecast source page (search, one change with confirmation, upload preview / apply, history), the
// daily Excel export (versions, download, new export with confirmation) and the per-SKU source label of the daily
// forecast. The backend is mocked; the API rules are tested in backend/tests/test_v140_*.py.
const wrap = (el: React.ReactNode, path = "/forecast-source") => <I18nProvider><MemoryRouter initialEntries={[path]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

type Call = { url: string; method: string; body?: any };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const SYS = {
  version: "1.4.0", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 12, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-10-31", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};
const CFG_ROW = { sku_code: "MEDX.A", fc_code: "BD", forecast_source: "LIGHTGBM", ghi_chu: "thử", updated_by: "giau", updated_at: "2026-11-01T01:00:00+00:00" };
const CFG = { total: 1, limit: 100, offset: 0, items: [CFG_ROW], default_source: "AVG_DEMAND", configured_by_source: { AVG_DEMAND: 0, LIGHTGBM: 1 } };
const HIST = { total: 1, limit: 100, offset: 0, items: [{ id: 1, sku_code: "MEDX.A", fc_code: "BD", old_source: null, new_source: "LIGHTGBM",
  ghi_chu: "thử", changed_by: "giau", changed_at: "2026-11-01T01:00:00+00:00", channel: "UPLOAD", batch_id: "SCU-1" }] };
const PREVIEW_ERR = {
  preview_id: "SCP-1", filename: "nguon.xlsx", counts: { rows: 4, changed: 1, unchanged: 1, errors: 2 }, has_ghi_chu: false,
  expires_at: "2026-11-01T02:00:00+00:00", errors_truncated: false, changes_truncated: false, can_apply: false,
  errors: [{ row: 3, sku_code: "MEDX.B", fc_code: null, forecast_source: "LIGHTGBM", ghi_chu: null, reason: "MISSING_FC_CODE" },
    { row: 4, sku_code: "MEDX.C", fc_code: "HN", forecast_source: "XGB", ghi_chu: null, reason: "UNKNOWN_SOURCE" }],
  changes: [{ row: 2, sku_code: "MEDX.D", fc_code: "BD", old_source: null, effective_old_source: "AVG_DEMAND", new_source: "LIGHTGBM", old_ghi_chu: null, ghi_chu: null }],
};
const PREVIEW_OK = { ...PREVIEW_ERR, preview_id: "SCP-2", counts: { rows: 2, changed: 1, unchanged: 1, errors: 0 }, errors: [], can_apply: true };

const LABEL = { vi: "Chạy thử – chưa dùng để mua hàng", en: "Trial run – not yet used for purchasing" };
const RUN = { id: "FRR-9", forecast_date: "2026-11-01", data_as_of: "2026-10-31", created_at: "2026-11-01T00:30:00+00:00", model_version: "MV-9",
  training_run_id: "TR-9", n_series: 2, n_lightgbm: 1, n_fallback: 1, horizon: 7, config_version: "SEL2:v1", trial_mode: true, trigger: "SCHEDULE" };
const STATUS = {
  enabled: true, trial_mode: true, trial_label: LABEL, refresh_enabled: true, refresh_deadline: "12:00", today: "2026-11-01",
  last_run: RUN, made_on: "2026-11-01", data_to: "2026-10-31", message: { vi: "m", en: "m" }, stale: false, stale_code: null, stale_since: null,
  outdated: false, last_report: null, trial_confirm_text: "TAT-CHAY-THU-2026-11-01",
};
const row = (sku: string, method: string) => ({ forecast_date: "2026-11-01", target_date: "2026-11-01", horizon: 1, fc_code: "BD", sku_code: sku,
  product_name: null, group_code: "B", lgb_raw: 1.2, final_qty: 2, method, flags: null });
const EXPORT_RUNS = { forecast_date: "2026-11-01", items: [
  { id: "EXP-2", forecast_date: "2026-11-01", version: 2, path: "x", sha256: "abcdef0123456789", n_rows: 14, is_stale: 0, flags: null,
    refresh_run_id: "FRR-9", trigger: "MANUAL", job_id: null, created_at: "2026-11-01T03:00:00+00:00", summary: null },
  { id: "EXP-1", forecast_date: "2026-11-01", version: 1, path: "y", sha256: "1111", n_rows: 14, is_stale: 1, flags: "STALE",
    refresh_run_id: null, trigger: "STALE", job_id: null, created_at: "2026-11-01T01:00:00+00:00", summary: null }] };

// 1.4.0 S5: POST /api/sel2/export answers with a FORECAST_EXPORT job; GET /api/jobs/{id} gives its end and result
const EXPORT_JOB = { id: "JOB-EXP3", job_type: "FORECAST_EXPORT", trigger: "MANUAL", status: "PENDING", stage: "QUEUED" };
const EXPORT_JOB_DONE = { ...EXPORT_JOB, status: "SUCCEEDED", stage: "DONE", reason_code: null,
  result: { params: { business_date: "2026-11-01", mode: "MANUAL" }, result: { status: "DONE", mode: "MANUAL", version: 3, n_rows: 14, is_stale: false } } };

function backend(over: { preview?: any; run?: any; lgbmFails?: boolean; exportForbidden?: boolean; exportActive?: boolean } = {}) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();
    const raw = init?.body;
    const body = typeof raw === "string" ? JSON.parse(raw) : raw;
    calls.push({ url: u, method, body });
    if (u.startsWith("/api/system/status")) return json(SYS);
    if (u.startsWith("/api/methods")) return json({ methods: {}, reasons: {} });
    if (u.startsWith("/api/sel2/source-config/history")) return json(HIST);
    if (u === "/api/sel2/source-config/upload" && method === "POST") return json(over.preview ?? PREVIEW_ERR);
    if (u === "/api/sel2/source-config/apply" && method === "POST") return json({ batch_id: "SCU-2", applied: 1, counts: PREVIEW_OK.counts });
    if (u.startsWith("/api/sel2/source-config?")) {
      if (over.lgbmFails) return json({ code: "HTTP_500" }, 500);
      return json(CFG);
    }
    if (u.startsWith("/api/sel2/source-config/") && method === "PUT") {
      const after = { ...CFG_ROW, forecast_source: body.forecast_source, ghi_chu: body.ghi_chu, configured: true };
      return json({ changed: true, before: { ...CFG_ROW, configured: true }, after });
    }
    if (u.startsWith("/api/sel2/source-config/")) return json({ ...CFG_ROW, configured: true });
    if (u === "/api/sel2/export" && method === "POST") return json({ ...EXPORT_JOB, already_active: !!over.exportActive });
    if (u === `/api/jobs/${EXPORT_JOB.id}`) return json(EXPORT_JOB_DONE);
    if (u.startsWith("/api/sel2/export/")) return over.exportForbidden ? json({ code: "READ_ONLY_REMOTE" }, 403) : json(EXPORT_RUNS);
    if (u.startsWith("/api/daily-forecast/status")) return json(STATUS);
    if (u.startsWith("/api/daily-forecast/runs")) return json([over.run ?? RUN]);
    if (u.startsWith("/api/daily-forecast/values")) return json({ run: over.run ?? RUN, total: 2, page: 0, page_size: 100, horizons: [1],
      rows: [row("MEDX.A", "LIGHTGBM"), row("MEDX.Z", "AVG_DEMAND")] });
    if (u.startsWith("/api/accuracy-reports")) return json([]);
    if (u.startsWith("/api/jobs/active")) return json({});
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const of = (calls: Call[], method: string, prefix: string) => calls.filter((c) => c.method === method && c.url.startsWith(prefix));
const modalButton = (name: string) => screen.getAllByRole("button", { name }).find((b) => b.closest(".modal"))! as HTMLButtonElement;

describe("1.4.0 forecast source page", () => {
  it("has its menu entry and route", async () => {
    backend();
    const r = await act(async () => render(wrap(<App />, "/forecast-source")));
    await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Nguồn dự báo"));
    expect(r.container.querySelector(".side a[aria-current=page]")?.getAttribute("href")).toBe("/forecast-source");
    r.unmount();
  });

  it("lists the configured rows with counts, history and download links; the search sends sku_code / fc_code / source", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<ForecastSource />)));
    await waitFor(() => expect(screen.getByTestId("fsrc-table")).toBeTruthy());
    expect(of(calls, "GET", "/api/sel2/source-config?")[0].url).toBe("/api/sel2/source-config?limit=100&offset=0");
    expect(screen.getByTestId("fsrc-table").textContent).toContain("MEDX.A");
    expect(screen.getByTestId("fsrc-history").textContent).toContain("SCU-1");
    expect(screen.getByTestId("fsrc-history").textContent).toContain("File tải lên");
    expect(screen.getByTestId("fsrc-download").getAttribute("href")).toBe("/api/sel2/source-config/download");
    expect(screen.getByTestId("fsrc-history-xlsx").getAttribute("href")).toBe("/api/sel2/source-config/history?format=xlsx");
    fireEvent.change(screen.getByTestId("fsrc-q-sku"), { target: { value: "medx" } });
    fireEvent.change(screen.getByTestId("fsrc-q-fc"), { target: { value: "BD" } });
    fireEvent.change(screen.getByTestId("fsrc-q-source"), { target: { value: "LIGHTGBM" } });
    await waitFor(() => expect(of(calls, "GET", "/api/sel2/source-config?").map((c) => c.url))
      .toContain("/api/sel2/source-config?sku_code=medx&fc_code=BD&source=LIGHTGBM&limit=100&offset=0"));
    r.unmount();
  });

  it("changes one SKU x FC only after the confirmation dialog (PUT with confirm=true)", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<ForecastSource />)));
    fireEvent.change(screen.getByTestId("fsrc-one-sku"), { target: { value: "MEDX.A" } });
    fireEvent.change(screen.getByTestId("fsrc-one-fc"), { target: { value: "BD" } });
    await act(async () => { fireEvent.click(screen.getByTestId("fsrc-lookup")); });
    expect(of(calls, "GET", "/api/sel2/source-config/MEDX.A/BD")).toHaveLength(1);
    await waitFor(() => expect(screen.getByTestId("fsrc-effective")).toBeTruthy());
    expect((screen.getByTestId("fsrc-new-source") as HTMLSelectElement).value).toBe("AVG_DEMAND");   // the other source
    await act(async () => { fireEvent.click(screen.getByTestId("fsrc-change")); });
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByTestId("fsrc-confirm-body").textContent).toContain("LightGBM → AVG_DEMAND");
    expect(of(calls, "PUT", "/api/sel2/")).toHaveLength(0);
    await act(async () => { fireEvent.click(modalButton("Đổi nguồn")); });
    expect(of(calls, "PUT", "/api/sel2/").map((c) => [c.url, c.body]))
      .toEqual([["/api/sel2/source-config/MEDX.A/BD", { forecast_source: "AVG_DEMAND", ghi_chu: "thử", confirm: true }]]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByTestId("fsrc-page").textContent).toContain("Đã đổi nguồn dự báo.");
    r.unmount();
  });

  it("a row switch also waits for the dialog; cancel sends nothing", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<ForecastSource />)));
    await waitFor(() => expect(screen.getByTestId("fsrc-toggle-MEDX.A-BD")).toBeTruthy());
    fireEvent.click(screen.getByTestId("fsrc-toggle-MEDX.A-BD"));
    fireEvent.click(screen.getByRole("button", { name: "Hủy" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByTestId("fsrc-toggle-MEDX.A-BD"));
    await act(async () => { fireEvent.click(modalButton("Đổi nguồn")); });
    expect(of(calls, "PUT", "/api/sel2/").map((c) => c.body)).toEqual([{ forecast_source: "AVG_DEMAND", ghi_chu: "thử", confirm: true }]);
    r.unmount();
  });

  it("an upload shows the preview counts and the error rows with their reasons; apply stays disabled", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<ForecastSource />)));
    const file = new File(["x"], "nguon.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    fireEvent.change(screen.getByTestId("fsrc-file"), { target: { files: [file] } });
    await act(async () => { fireEvent.click(screen.getByTestId("fsrc-preview")); });
    const up = of(calls, "POST", "/api/sel2/source-config/upload");
    expect(up).toHaveLength(1);
    expect((up[0].body as FormData).get("file")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("fsrc-preview-result")).toBeTruthy());
    const counts = screen.getByTestId("fsrc-preview-counts").textContent!;
    for (const x of ["Số dòng4", "Sẽ thay đổi1", "Không đổi1", "Dòng lỗi2"]) expect(counts).toContain(x);
    const errors = screen.getByTestId("fsrc-errors").textContent!;
    expect(errors).toContain("Thiếu mã FC");
    expect(errors).toContain("MISSING_FC_CODE");
    expect(errors).toContain("Nguồn không hợp lệ");
    expect(screen.getByTestId("fsrc-changes").textContent).toContain("MEDX.D");
    expect((screen.getByTestId("fsrc-apply") as HTMLButtonElement).disabled).toBe(true);
    expect(of(calls, "POST", "/api/sel2/source-config/apply")).toHaveLength(0);
    r.unmount();
  });

  it("a clean preview is applied after the dialog with its preview_id and confirm=true", async () => {
    const calls = backend({ preview: PREVIEW_OK });
    const r = await act(async () => render(wrap(<ForecastSource />)));
    fireEvent.change(screen.getByTestId("fsrc-file"), { target: { files: [new File(["x"], "nguon.xlsx")] } });
    await act(async () => { fireEvent.click(screen.getByTestId("fsrc-preview")); });
    await waitFor(() => expect((screen.getByTestId("fsrc-apply") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("fsrc-apply"));
    expect(screen.getByTestId("fsrc-apply-body").textContent).toContain("Ghi 1 thay đổi");
    expect(of(calls, "POST", "/api/sel2/source-config/apply")).toHaveLength(0);
    await act(async () => { fireEvent.click(modalButton("Áp dụng")); });
    expect(of(calls, "POST", "/api/sel2/source-config/apply").map((c) => c.body)).toEqual([{ preview_id: "SCP-2", confirm: true }]);
    await waitFor(() => expect(screen.getByTestId("fsrc-page").textContent).toContain("Đã áp dụng 1 thay đổi. · SCU-2"));
    r.unmount();
  });
});

describe("1.4.0 daily Excel export", () => {
  it("lists the versions of the forecast day, links the latest file and exports a new one only after the dialog", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<DailyForecast />, "/daily-forecast")));
    await waitFor(() => expect(screen.getByTestId("dexp-runs")).toBeTruthy());
    expect(of(calls, "GET", "/api/sel2/export/2026-11-01/runs").length).toBeGreaterThan(0);
    expect(screen.getByTestId("dexp-download").getAttribute("href")).toBe("/api/sel2/export/2026-11-01");
    expect(screen.getByTestId("dexp-download").textContent).toContain("v2");
    const runs = screen.getByTestId("dexp-runs").textContent!;
    for (const x of ["v2", "v1", "Thủ công", "Xuất số cũ", "abcdef012345"]) expect(runs).toContain(x);
    fireEvent.click(screen.getByTestId("dexp-run"));
    expect(screen.getByTestId("dexp-confirm-body").textContent).toContain("01/11/2026");
    expect(of(calls, "POST", "/api/sel2/export")).toHaveLength(0);
    const before = of(calls, "GET", "/api/sel2/export/2026-11-01/runs").length;
    await act(async () => { fireEvent.click(modalButton("Xuất file mới")); });
    expect(of(calls, "POST", "/api/sel2/export").map((c) => c.body)).toEqual([{ date: "2026-11-01", confirm: true }]);
    // the job is followed until it ends; then the versions are read again and the written version is shown
    await waitFor(() => expect(screen.getByTestId("daily-page").textContent).toContain("Đã xuất phiên bản v3 (14 dòng)."));
    expect(of(calls, "GET", "/api/jobs/JOB-EXP3").length).toBeGreaterThan(0);
    expect(of(calls, "GET", "/api/sel2/export/2026-11-01/runs").length).toBeGreaterThan(before);
    expect(screen.getByTestId("daily-page").textContent).toContain("Xuất file Excel dự báo");
    r.unmount();
  });

  it("follows an export already queued or running instead of starting a second one", async () => {
    const calls = backend({ exportActive: true });
    const r = await act(async () => render(wrap(<DailyForecast />, "/daily-forecast")));
    await waitFor(() => expect(screen.getByTestId("dexp-runs")).toBeTruthy());
    fireEvent.click(screen.getByTestId("dexp-run"));
    await act(async () => { fireEvent.click(modalButton("Xuất file mới")); });
    expect(of(calls, "POST", "/api/sel2/export")).toHaveLength(1);
    await waitFor(() => expect(of(calls, "GET", "/api/jobs/JOB-EXP3").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId("daily-page").textContent).toContain("Đã xuất phiên bản v3 (14 dòng)."));
    r.unmount();
  });

  it("hides the export card when the export routes are refused (read-only remote link, 403)", async () => {
    const calls = backend({ exportForbidden: true });
    const r = await act(async () => render(wrap(<DailyForecast />, "/daily-forecast")));
    await waitFor(() => expect(of(calls, "GET", "/api/sel2/export/2026-11-01/runs").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId("daily-table")).toBeTruthy());
    expect(screen.queryByTestId("dexp-run")).toBeNull();
    expect(screen.queryByTestId("dexp-none")).toBeNull();
    r.unmount();
  });
});

describe("1.4.0 per-SKU source label of the daily forecast", () => {
  it("rowSourceKind: LIGHTGBM when configured, OTHER otherwise, null for a non-SEL2 run or an unknown configuration", () => {
    const keys = new Set(["MEDX.A|BD"]);
    expect(isSel2Run(RUN)).toBe(true);
    expect(isSel2Run({ config_version: 3 })).toBe(false);
    expect(rowSourceKind(RUN, keys, "MEDX.A", "BD")).toBe("LIGHTGBM");
    expect(rowSourceKind(RUN, keys, "MEDX.A", "HN")).toBe("OTHER");
    expect(rowSourceKind(RUN, null, "MEDX.A", "BD")).toBeNull();
    expect(rowSourceKind({ ...RUN, config_version: 3 }, keys, "MEDX.A", "BD")).toBeNull();
  });

  it("a SEL2 run shows 'đang dùng LightGBM' for a LIGHTGBM SKU x FC and keeps the trial label for the others", async () => {
    const calls = backend();
    const r = await act(async () => render(wrap(<DailyForecast />, "/daily-forecast")));
    await waitFor(() => expect(screen.getByTestId("daily-src-BD-MEDX.A-1")).toBeTruthy());
    expect(of(calls, "GET", "/api/sel2/source-config?")[0].url).toBe("/api/sel2/source-config?source=LIGHTGBM&limit=1000&offset=0");
    expect(screen.getByTestId("daily-src-BD-MEDX.A-1").textContent).toBe("đang dùng LightGBM");
    expect(screen.getByTestId("daily-src-BD-MEDX.Z-1").textContent).toBe("Chạy thử – chưa dùng để mua hàng");
    r.unmount();
  });

  it("no source column for a 1.3.1 run, nor when the configuration cannot be read", async () => {
    let calls = backend({ run: { ...RUN, config_version: 3 } });
    let r = await act(async () => render(wrap(<DailyForecast />, "/daily-forecast")));
    await waitFor(() => expect(screen.getByTestId("daily-table")).toBeTruthy());
    expect(screen.queryByTestId("daily-src-BD-MEDX.A-1")).toBeNull();
    expect(of(calls, "GET", "/api/sel2/source-config?")).toHaveLength(0);
    r.unmount();
    calls = backend({ lgbmFails: true });
    r = await act(async () => render(wrap(<DailyForecast />, "/daily-forecast")));
    await waitFor(() => expect(of(calls, "GET", "/api/sel2/source-config?").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId("daily-table")).toBeTruthy());
    expect(screen.queryByTestId("daily-src-BD-MEDX.A-1")).toBeNull();
    expect(screen.getByTestId("daily-table").textContent).not.toContain("đang dùng LightGBM");
    r.unmount();
  });
});
