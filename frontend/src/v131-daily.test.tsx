import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import App from "./App";
import DailyForecast from "./pages/DailyForecast";
import Features from "./pages/Features";
import Schedules from "./pages/Schedules";
import { FeatureImportance } from "./pages/TrainingExplain";

// 1.3.1 "LightGBM chốt" UI: global trial banner, daily forecast page (status, STALE, values, export, reports, typed
// trial-off confirmation), feature table (B11), feature importance (B10), refresh / report schedule cards. The backend
// is mocked; the API rules are tested in backend/tests/test_v131_*.py.
const wrap = (el: React.ReactNode, path = "/daily-forecast") => <I18nProvider><MemoryRouter initialEntries={[path]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const LABEL = { vi: "Chạy thử – chưa dùng để mua hàng", en: "Trial run – not yet used for purchasing" };
const SYS = {
  version: "1.3.1", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 11, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-10-28", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};
const RUN = { id: "FRR-1", forecast_date: "2026-10-28", data_as_of: "2026-10-27", created_at: "2026-10-28T00:30:00+00:00", model_version: "MV-1",
  training_run_id: "TR-1", n_series: 2, n_lightgbm: 2, n_fallback: 0, horizon: 7, config_version: 3, trial_mode: true, trigger: "SCHEDULE" };
const STATUS = {
  enabled: true, trial_mode: true, trial_label: LABEL, refresh_enabled: true, refresh_deadline: "12:00", today: "2026-10-29",
  last_run: RUN, made_on: "2026-10-28", data_to: "2026-10-27",
  message: { vi: "Số dự báo lập ngày 28/10/2026, dữ liệu đến ngày 27/10/2026", en: "Forecast made on 28/10/2026, data up to 27/10/2026" },
  stale: true, stale_code: "STALE_FORECAST", stale_since: "2026-10-29T05:00:00+00:00", outdated: true,
  last_report: { id: "AR-1", run_kind: "SCHEDULED", run_date: "2026-10-27", period_start: "2026-10-01", period_end: "2026-10-26", n_cells: 120,
    status: "DONE", report_path_name: "bao-cao-do-chinh-xac-x.xlsx", created_at: "2026-10-27T02:30:00+00:00" },
  trial_confirm_text: "TAT-CHAY-THU-2026-10-29",
};
const VALUES = {
  run: RUN, total: 1, page: 0, page_size: 100, horizons: [1, 2, 3, 4, 5, 6, 7],
  rows: [{ forecast_date: "2026-10-28", target_date: "2026-10-28", horizon: 1, fc_code: "BD", sku_code: "MEDX.A", product_name: "Thuốc A",
    group_code: "C", lgb_raw: 0.19, final_qty: 0, method: "LIGHTGBM", flags: null }],
};
const REPORTS = [{ ...STATUS.last_report, error: null }];

type Call = { url: string; method: string; body?: any };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** Mocked backend of the daily forecast; `state` changes with the trial-mode POST like the real one. */
function backend(over: any = {}, opts: { dailyFails?: boolean; alreadyActive?: boolean } = {}) {
  const calls: Call[] = [];
  const state: any = { ...STATUS, ...over };
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method, body });
    if (u.startsWith("/api/system/status")) return json(SYS);
    if (u.startsWith("/api/methods")) return json({ methods: {}, reasons: {} });
    if (u.startsWith("/api/daily-forecast/") && opts.dailyFails) return json({ code: "HTTP_404" }, 404);
    if (u.startsWith("/api/daily-forecast/status")) return json(state);
    if (u.startsWith("/api/daily-forecast/runs")) return json(state.last_run ? [state.last_run] : []);
    if (u.startsWith("/api/daily-forecast/values")) return json(state.last_run ? VALUES : { run: null, rows: [], total: 0, page: 0, page_size: 100, horizons: [] });
    if (u === "/api/daily-forecast/trial-mode" && method === "POST") {
      state.trial_mode = body.trial_mode;
      state.trial_label = state.enabled && body.trial_mode ? LABEL : null;
      return json({ changed: true, trial_mode: state.trial_mode, trial_label: state.trial_label });
    }
    const active = opts.alreadyActive ? { already_active: true, status: "RUNNING" } : {};
    if (u === "/api/daily-forecast/refresh" && method === "POST") return json({ id: "J-1", job_type: "FORECAST_REFRESH", status: "PENDING", ...active });
    if (u === "/api/accuracy-reports/run" && method === "POST") return json({ id: "J-2", job_type: "ACCURACY_REPORT", status: "PENDING", ...active });
    if (u.startsWith("/api/accuracy-reports")) return json(REPORTS);
    if (u.startsWith("/api/jobs/active")) return json({});
    if (u.startsWith("/api/jobs/J-")) return json({ id: u.slice(10), job_type: u.endsWith("1") ? "FORECAST_REFRESH" : "ACCURACY_REPORT", status: "SUCCEEDED", stage: "DONE" });
    return json({ code: "TEST_UNAVAILABLE", vi: "Không có dữ liệu thử", en: "No test data" }, 503);
  }) as any;
  return { calls, state };
}
const count = (calls: Call[], prefix: string, method = "GET") => calls.filter((c) => c.method === method && c.url.startsWith(prefix)).length;

describe("1.3.1 global trial banner", () => {
  it("is shown on every page while the backend answers a trial label", async () => {
    backend();
    const r = await act(async () => render(wrap(<App />, "/")));
    await waitFor(() => expect(screen.getByTestId("trial-banner")).toBeTruthy());
    expect(screen.getByTestId("trial-banner").textContent).toBe("Chạy thử – chưa dùng để mua hàng");
    expect(screen.getByTestId("trial-banner").className).toContain("warn");
    r.unmount();
  });

  it("is not shown without a label (feature off) nor when the endpoint fails", async () => {
    const a = backend({ enabled: false, trial_label: null });
    let r = await act(async () => render(wrap(<App />, "/")));
    await waitFor(() => expect(count(a.calls, "/api/daily-forecast/status")).toBe(1));
    expect(screen.queryByTestId("trial-banner")).toBeNull();
    r.unmount();
    const b = backend({}, { dailyFails: true });
    r = await act(async () => render(wrap(<App />, "/")));
    await waitFor(() => expect(count(b.calls, "/api/daily-forecast/status")).toBe(1));
    expect(screen.queryByTestId("trial-banner")).toBeNull();
    r.unmount();
  });

  it("the daily forecast page has its route, sidebar entry and page header", async () => {
    backend();
    const r = await act(async () => render(wrap(<App />, "/daily-forecast")));
    await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Dự báo hằng ngày"));
    const active = r.container.querySelector(".side a[aria-current=page]");
    expect(active?.textContent).toBe("Dự báo hằng ngày");
    expect(active?.getAttribute("href")).toBe("/daily-forecast");
    r.unmount();
  });
});

describe("1.3.1 daily forecast page", () => {
  it("shows the made-on / data-to message, the STALE flag, the outdated notice, values, export and reports", async () => {
    backend();
    const r = await act(async () => render(wrap(<DailyForecast />)));
    await waitFor(() => expect(screen.getByTestId("daily-table")).toBeTruthy());
    expect(screen.getByTestId("daily-message").textContent).toBe("Số dự báo lập ngày 28/10/2026, dữ liệu đến ngày 27/10/2026");
    // a short note only: the label itself is the shell banner (not repeated on the page)
    expect(screen.getByTestId("daily-trial").textContent).toContain("Chế độ chạy thử đang bật");
    expect(screen.getByTestId("daily-page").textContent).not.toContain("Chạy thử – chưa dùng để mua hàng");
    expect(screen.getByTestId("daily-table").querySelector("td[title='0.19']")?.textContent).toBe("0,190");
    const stale = screen.getByTestId("daily-stale").textContent!;
    expect(stale).toContain("STALE_FORECAST");
    expect(stale).toContain("12:00");
    expect(screen.getByTestId("daily-outdated").textContent).toContain("28/10/2026");
    expect(screen.getByTestId("daily-outdated").textContent).toContain("29/10/2026");
    const table = screen.getByTestId("daily-table").textContent!;
    for (const x of ["MEDX.A", "Thuốc A", "BD", "0,190", "LightGBM"]) expect(table).toContain(x);
    expect(screen.getByTestId("daily-export").getAttribute("href")).toBe("/api/daily-forecast/export.xlsx?run_id=FRR-1");
    expect(screen.getByTestId("daily-report-dl-AR-1").getAttribute("href")).toBe("/api/accuracy-reports/AR-1/download");
    expect(screen.getByTestId("daily-reports").textContent).toContain("Theo lịch");
    expect((screen.getByTestId("daily-refresh") as HTMLButtonElement).disabled).toBe(false);
    r.unmount();
  });

  it("no run yet = empty state, no stale / outdated notice; refresh disabled with the reason when the feature is off", async () => {
    backend({ enabled: false, trial_label: null, last_run: null, message: null, stale: false, stale_code: null, stale_since: null, outdated: false, last_report: null });
    const r = await act(async () => render(wrap(<DailyForecast />)));
    await waitFor(() => expect(screen.getByTestId("daily-page")).toBeTruthy());
    expect(screen.queryByTestId("daily-message")).toBeNull();
    expect(screen.queryByTestId("daily-stale")).toBeNull();
    expect(screen.queryByTestId("daily-outdated")).toBeNull();
    expect(screen.queryByTestId("daily-trial")).toBeNull();
    expect(screen.getByTestId("daily-page").textContent).toContain("Chưa có lần làm mới nào");
    const btn = screen.getByTestId("daily-refresh") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain("daily_forecast.enabled");
    expect((screen.getByTestId("daily-report-run") as HTMLButtonElement).disabled).toBe(true);
    r.unmount();
  });

  it("the refresh button submits the job, follows it and reloads the status when it ends", async () => {
    const { calls } = backend();
    const r = await act(async () => render(wrap(<DailyForecast />)));
    await waitFor(() => expect(screen.getByTestId("daily-refresh")).toBeTruthy());
    const before = count(calls, "/api/daily-forecast/status");
    await act(async () => { fireEvent.click(screen.getByTestId("daily-refresh")); });
    expect(count(calls, "/api/daily-forecast/refresh", "POST")).toBe(1);
    await waitFor(() => expect(count(calls, "/api/jobs/J-1")).toBeGreaterThan(0));
    await waitFor(() => expect(count(calls, "/api/daily-forecast/status")).toBeGreaterThan(before));
    expect(screen.getByTestId("daily-page").textContent).toContain("Đã gửi job: J-1");
    r.unmount();
  });

  it("a refresh / report already running is said as such (no new job) and followed", async () => {
    const { calls } = backend({}, { alreadyActive: true });
    const r = await act(async () => render(wrap(<DailyForecast />)));
    await waitFor(() => expect(screen.getByTestId("daily-refresh")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("daily-refresh")); });
    const page = () => screen.getByTestId("daily-page").textContent!;
    expect(page()).toContain("Luồng này đang có job chạy — không tạo job mới; đang theo dõi job: J-1");
    expect(page()).not.toContain("Đã gửi job");
    await waitFor(() => expect(count(calls, "/api/jobs/J-1")).toBeGreaterThan(0));
    await waitFor(() => expect((screen.getByTestId("daily-report-run") as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(screen.getByTestId("daily-report-run")); });
    expect(page()).toContain("Luồng này đang có job chạy — không tạo job mới; đang theo dõi job: J-2");
    await waitFor(() => expect(count(calls, "/api/jobs/J-2")).toBeGreaterThan(0));
    r.unmount();
  });

  it("the shell banner follows the status the daily page loads (a label switched on while the tab stayed open)", async () => {
    const { state } = backend({ trial_label: null, trial_mode: false });
    const r = await act(async () => render(wrap(<App />, "/")));
    await waitFor(() => expect(r.container.querySelector(".side a[href='/daily-forecast']")).toBeTruthy());
    expect(screen.queryByTestId("trial-banner")).toBeNull();
    state.trial_mode = true;                       // changed elsewhere; the shell has not asked again
    state.trial_label = LABEL;
    await act(async () => { fireEvent.click(r.container.querySelector(".side a[href='/daily-forecast']")!); });
    await waitFor(() => expect(screen.getByTestId("trial-banner").textContent).toBe("Chạy thử – chưa dùng để mua hàng"));
    // shown once: the page itself keeps a short note only
    expect(document.body.textContent!.split("Chạy thử – chưa dùng để mua hàng").length - 1).toBe(1);
    r.unmount();
  });

  it("opening the trial-off dialog reloads the status, so the confirmation text is today's", async () => {
    const { calls, state } = backend();
    const r = await act(async () => render(wrap(<DailyForecast />)));
    await waitFor(() => expect(screen.getByTestId("daily-trial-off")).toBeTruthy());
    const before = count(calls, "/api/daily-forecast/status");
    state.trial_confirm_text = "TAT-CHAY-THU-2026-10-30";          // the page stayed open past midnight
    await act(async () => { fireEvent.click(screen.getByTestId("daily-trial-off")); });
    expect(count(calls, "/api/daily-forecast/status")).toBe(before + 1);
    await waitFor(() => expect(screen.getByTestId("daily-expected").textContent).toBe("TAT-CHAY-THU-2026-10-30"));
    const confirm = screen.getAllByRole("button", { name: "Tắt chế độ chạy thử" }).find((b) => b.closest(".modal"))! as HTMLButtonElement;
    fireEvent.change(screen.getByTestId("daily-confirm-input"), { target: { value: "TAT-CHAY-THU-2026-10-29" } });
    expect(confirm.disabled).toBe(true);                             // yesterday's text no longer matches
    fireEvent.change(screen.getByTestId("daily-confirm-input"), { target: { value: "TAT-CHAY-THU-2026-10-30" } });
    expect(confirm.disabled).toBe(false);
    r.unmount();
  });

  it("switches the trial mode off only after the exact typed text, then the global banner goes", async () => {
    const { calls } = backend();
    const r = await act(async () => render(wrap(<App />, "/daily-forecast")));
    await waitFor(() => expect(screen.getByTestId("daily-trial-off")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("trial-banner")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("daily-trial-off")); });     // opening reloads the status
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByTestId("daily-expected").textContent).toBe("TAT-CHAY-THU-2026-10-29");
    const confirm = screen.getAllByRole("button", { name: "Tắt chế độ chạy thử" }).find((b) => b.closest(".modal"))! as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(screen.getByLabelText(/TAT-CHAY-THU-2026-10-29/)).toBe(screen.getByTestId("daily-confirm-input"));
    fireEvent.change(screen.getByTestId("daily-confirm-input"), { target: { value: "TAT-CHAY-THU-2026-10-28" } });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("daily-confirm-input"), { target: { value: "tat-chay-thu-2026-10-29" } });
    expect(confirm.disabled).toBe(true);
    expect(count(calls, "/api/daily-forecast/trial-mode", "POST")).toBe(0);
    fireEvent.change(screen.getByTestId("daily-confirm-input"), { target: { value: "TAT-CHAY-THU-2026-10-29" } });
    expect(confirm.disabled).toBe(false);
    await act(async () => { fireEvent.click(confirm); });
    const post = calls.filter((c) => c.method === "POST" && c.url === "/api/daily-forecast/trial-mode");
    expect(post.map((c) => c.body)).toEqual([{ trial_mode: false, confirm_text: "TAT-CHAY-THU-2026-10-29" }]);
    await waitFor(() => expect(screen.queryByTestId("trial-banner")).toBeNull());
    await waitFor(() => expect(screen.getByTestId("daily-trial-on")).toBeTruthy());
    expect(screen.queryByRole("dialog")).toBeNull();
    r.unmount();
  });

  it("switches the trial mode back on without typing, and the global banner comes back", async () => {
    const { calls } = backend({ trial_mode: false, trial_label: null });
    const r = await act(async () => render(wrap(<App />, "/daily-forecast")));
    await waitFor(() => expect(screen.getByTestId("daily-trial-on")).toBeTruthy());
    expect(screen.queryByTestId("trial-banner")).toBeNull();
    fireEvent.click(screen.getByTestId("daily-trial-on"));
    expect(screen.queryByTestId("daily-confirm-input")).toBeNull();
    const confirm = screen.getAllByRole("button", { name: "Bật lại chế độ chạy thử" }).find((b) => b.closest(".modal"))! as HTMLButtonElement;
    expect(confirm.disabled).toBe(false);
    await act(async () => { fireEvent.click(confirm); });
    expect(calls.filter((c) => c.url === "/api/daily-forecast/trial-mode").map((c) => c.body)).toEqual([{ trial_mode: true, confirm_text: null }]);
    await waitFor(() => expect(screen.getByTestId("trial-banner").textContent).toBe("Chạy thử – chưa dùng để mua hàng"));
    r.unmount();
  });
});

// ------------------------------------------------------------------ feature table (B11)
const REG = {
  source: "BIGQUERY", scope: null, scope_error: null, entries: [], groups: {}, coverage: { rows: 0 }, decisions: {}, active_model: null,
  statuses: { ACTIVE: { vi: "Đang dùng", en: "Active" }, DISABLED: { vi: "Tắt", en: "Disabled" }, UNAVAILABLE: { vi: "Không có", en: "Unavailable" },
    PLANNED: { vi: "Dự kiến", en: "Planned" } },
  counts: { ACTIVE: 0, DISABLED: 0, UNAVAILABLE: 0, PLANNED: 0 },
  next_training: { feature_set_version: "fs-1", n_features: 5, features: ["fc_code"] }, registry_version: "r1", feature_code_version: "c1",
};
const FP = { vi: "Thay đổi làm đổi fingerprint và chỉ có hiệu lực ở lần huấn luyện sau", en: "A change alters the configuration fingerprint" };
const FTAB = {
  rows: [
    { feature: "sku_code", feature_group: "IDENTITY", enabled: true, contri: 1, is_default: true },
    { feature: "fc_code", feature_group: "IDENTITY", enabled: true, contri: 1, is_default: true },
    { feature: "lag_1", feature_group: "LAG", enabled: true, contri: 1, is_default: true },
    { feature: "price_last", feature_group: "PRICE", enabled: false, contri: 1, is_default: false },
    { feature: "horizon", feature_group: "DIRECT", enabled: true, contri: 1, is_default: true },
  ],
  updated_at: "2026-10-29T01:00:00+00:00", effective: "NEXT_TRAINING", fingerprint_note: FP,
  history: [{ changed_at: "2026-10-29T01:00:00+00:00", note: "OWNER_CONFIRMED tat gia", value_json: "{}" }],
};
function featureBackend(putAnswer: () => Response) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (u.startsWith("/api/features/registry")) return json(REG);
    if (u === "/api/feature-table" && method === "PUT") return putAnswer();
    if (u === "/api/feature-table") return json(FTAB);
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}

describe("1.3.1 feature table", () => {
  it("validates the coefficient, keeps sku_code / horizon read-only and saves with confirm only after the dialog", async () => {
    const calls = featureBackend(() => json({ ...FTAB, saved: true }));
    const r = await act(async () => render(wrap(<Features />, "/features")));
    await waitFor(() => expect(screen.getByTestId("ftab-table")).toBeTruthy());
    expect((screen.getByTestId("ftab-on-sku_code") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("ftab-on-horizon") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("ftab-contri-horizon") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId("ftab-on-price_last") as HTMLInputElement).checked).toBe(false);
    expect(screen.getByTestId("ftab-row-lag_1").textContent).toContain("mặc định");
    expect(screen.getByTestId("ftab-row-price_last").textContent).toContain("đã đổi");
    expect(screen.getByTestId("ftab-history").textContent).toContain("OWNER_CONFIRMED tat gia");
    const save = screen.getByTestId("ftab-save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);                                           // nothing changed yet
    fireEvent.change(screen.getByTestId("ftab-contri-lag_1"), { target: { value: "0" } });
    expect(save.disabled).toBe(true);                                           // 0 < x <= 10
    expect(screen.getByTestId("ftab-row-lag_1").textContent).toContain("Hệ số phải lớn hơn 0");
    fireEvent.change(screen.getByTestId("ftab-contri-lag_1"), { target: { value: "10.5" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("ftab-contri-lag_1"), { target: { value: "2.5" } });
    fireEvent.click(screen.getByTestId("ftab-on-fc_code"));
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);           // the dialog first
    expect(screen.getByRole("dialog").textContent).toContain("Thay đổi làm đổi fingerprint và chỉ có hiệu lực ở lần huấn luyện sau");
    expect(screen.getByTestId("ftab-away").textContent).toBe("3");
    fireEvent.change(screen.getByTestId("ftab-note"), { target: { value: "thu he so" } });
    const confirm = screen.getAllByRole("button", { name: "Lưu bảng cấu hình biến" }).find((b) => b.closest(".modal"))!;
    await act(async () => { fireEvent.click(confirm); });
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toEqual({
      features: { fc_code: { enabled: false, contri: 1 }, lag_1: { enabled: true, contri: 2.5 }, price_last: { enabled: false, contri: 1 },
        horizon: { enabled: true, contri: 1 } },
      confirm: true, note: "thu he so",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("ftab").textContent).toContain("Đã lưu bảng cấu hình biến");
    r.unmount();
  });

  it("shows the API message when the save is refused, and keeps the dialog open", async () => {
    featureBackend(() => json({ code: "FEATURE_UNKNOWN", vi: "Tên biến không có trong danh sách biến của mô hình", en: "Unknown feature" }, 422));
    const r = await act(async () => render(wrap(<Features />, "/features")));
    await waitFor(() => expect(screen.getByTestId("ftab-table")).toBeTruthy());
    fireEvent.change(screen.getByTestId("ftab-contri-lag_1"), { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("ftab-save"));
    const confirm = screen.getAllByRole("button", { name: "Lưu bảng cấu hình biến" }).find((b) => b.closest(".modal"))!;
    await act(async () => { fireEvent.click(confirm); });
    await waitFor(() => expect(screen.getByRole("dialog").textContent).toContain("Tên biến không có trong danh sách biến của mô hình"));
    r.unmount();
  });
});

// ------------------------------------------------------------------ feature importance (B10)
describe("1.3.1 feature importance of a training run", () => {
  it("TABLE: rows, group summary and the .xlsx link; LEGACY_GAIN: split '—' and no file", async () => {
    globalThis.fetch = vi.fn(async (url: any) => String(url).includes("TR-OLD")
      ? json({ training_run_id: "TR-OLD", source: "LEGACY_GAIN",
        rows: [{ feature: "lag_1", feature_group: "LAG", gain: 30, split: null, gain_share: 0.75, split_share: null, rank: 1 }],
        groups: [{ feature_group: "LAG", n_features: 1, gain: 30, split: null, gain_share: 1, split_share: null }] })
      : json({ training_run_id: "TR-1", source: "TABLE",
        rows: [{ feature: "lag_1", feature_group: "LAG", gain: 60, split: 12, gain_share: 0.6, split_share: 0.4, rank: 1 },
          { feature: "dow", feature_group: "CALENDAR", gain: 40, split: 18, gain_share: 0.4, split_share: 0.6, rank: 2 }],
        groups: [{ feature_group: "LAG", n_features: 1, gain: 60, split: 12, gain_share: 0.6, split_share: 0.4 }] })) as any;
    let r = await act(async () => render(wrap(<FeatureImportance runId="TR-1" />)));
    await waitFor(() => expect(screen.getByTestId("fi-table")).toBeTruthy());
    expect(screen.getByTestId("fi-download").getAttribute("href")).toBe("/api/training-runs/TR-1/feature-importance.xlsx");
    expect(screen.getByTestId("fi-table").textContent).toContain("dow");
    expect(screen.getByTestId("fi-table").textContent).toContain("60%");
    expect(screen.getByTestId("fi-groups").textContent).toContain("LAG");
    r.unmount();
    r = await act(async () => render(wrap(<FeatureImportance runId="TR-OLD" />)));
    await waitFor(() => expect(screen.getByTestId("fi-legacy")).toBeTruthy());
    expect(screen.queryByTestId("fi-download")).toBeNull();
    const cells = Array.from(screen.getByTestId("fi-table").querySelectorAll("tbody td")).map((td) => td.textContent);
    expect(cells).toEqual(["1", "lag_1", "LAG", "30", "75%", "—", "—"]);
    r.unmount();
  });
});

// ------------------------------------------------------------------ schedules: refresh and report flows
function flow(f: string, jt: string, config: any, extra: any = {}) {
  return { flow: f, job_type: jt, enabled: false, state: "OFF", enabled_at: null, config, timezone: "Asia/Ho_Chi_Minh",
    readiness: { ready: true, reasons: [], notes: [], source: "BIGQUERY" }, manual_readiness: { ready: true, reasons: [], notes: [] },
    next_runs: [], last_run: null, last_skipped: null, history: [], ...extra };
}
const SCHED = { timezone: "Asia/Ho_Chi_Minh", now_vn: "2026-10-29T09:00:00+07:00", active_source: "BIGQUERY",
  data_window: { start: "2026-01-01", end: "2026-10-28" }, scheduler: { running: true, last_tick: "2026-10-29T02:00:00+00:00", loaded: null },
  flows: { d1: flow("d1", "D1_SYNC", { time: "05:00", fallback_time: "06:10", poll_interval_minutes: 30 }),
    d0: flow("d0", "D0_SYNC", { times: ["08:00"], catchup_policy: "LATEST_ONCE" }),
    train: flow("train", "TRAIN_PUBLISH", { time: "05:20", catchup_policy: "RUN_ONCE" }),
    refresh: flow("refresh", "FORECAST_REFRESH", { deadline: "12:00", retry_minutes: 10 }),
    report: flow("report", "ACCURACY_REPORT", { weekday: 1, time: "09:30" }, {
      readiness: { ready: false, reasons: [{ code: "DAILY_FORECAST_DISABLED", vi: "Làm mới dự báo hằng ngày đang TẮT", en: "off", detail: null }], notes: [] } }) } };
function mockSchedules() {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const c = { url: String(url), method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    return json(c.method === "PUT" ? { ...SCHED.flows.refresh, saved: true } : SCHED);
  }) as any;
  return calls;
}

describe("1.3.1 schedules: refresh and report cards", () => {
  it("render their fields and readiness, save only that flow, switch on after the confirmation", async () => {
    const confirm = vi.fn(() => false);
    window.confirm = confirm;
    const calls = mockSchedules();
    const r = await act(async () => render(wrap(<Schedules />, "/schedules")));
    await waitFor(() => expect(screen.getByTestId("flow-refresh")).toBeTruthy());
    const page = screen.getByTestId("schedules-page").textContent!;
    expect(page).toContain("Làm mới dự báo hằng ngày");
    expect(page).toContain("Báo cáo độ chính xác hằng tuần");
    expect((screen.getByTestId("refresh-deadline") as HTMLInputElement).value).toBe("12:00");
    expect((screen.getByTestId("refresh-retry") as HTMLInputElement).value).toBe("10");
    expect((screen.getByTestId("report-weekday") as HTMLSelectElement).value).toBe("1");
    const days = Array.from((screen.getByTestId("report-weekday") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(days).toEqual(["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]);
    expect((screen.getByTestId("report-time") as HTMLInputElement).value).toBe("09:30");
    expect(screen.getByTestId("flow-report").querySelector("[data-testid=readiness]")!.textContent).toContain("Làm mới dự báo hằng ngày đang TẮT");
    expect((screen.getByTestId("toggle-report") as HTMLButtonElement).disabled).toBe(true);     // not ready
    fireEvent.change(screen.getByTestId("refresh-deadline"), { target: { value: "25:00" } });
    expect((screen.getByTestId("save-refresh") as HTMLButtonElement).disabled).toBe(true);      // invalid HH:MM
    fireEvent.change(screen.getByTestId("refresh-deadline"), { target: { value: "11:30" } });
    for (const bad of ["0", "61", ""]) {
      fireEvent.change(screen.getByTestId("refresh-retry"), { target: { value: bad } });
      expect((screen.getByTestId("save-refresh") as HTMLButtonElement).disabled, bad).toBe(true);   // 1..60 minutes
    }
    fireEvent.change(screen.getByTestId("refresh-retry"), { target: { value: "15" } });
    await act(async () => { fireEvent.click(screen.getByTestId("save-refresh")); });
    let puts = calls.filter((c) => c.method === "PUT");
    expect(puts.map((c) => [c.url, c.body])).toEqual([["/api/schedules/refresh", { deadline: "11:30", retry_minutes: 15 }]]);
    fireEvent.change(screen.getByTestId("report-weekday"), { target: { value: "7" } });
    fireEvent.change(screen.getByTestId("report-time"), { target: { value: "10:00" } });
    await act(async () => { fireEvent.click(screen.getByTestId("save-report")); });
    puts = calls.filter((c) => c.method === "PUT");
    expect(puts[1]).toEqual({ url: "/api/schedules/report", method: "PUT", body: { weekday: 7, time: "10:00" } });
    r.unmount();
  });

  it("switching the refresh on asks first and sends only enabled: true", async () => {
    const confirm = vi.fn(() => false);
    window.confirm = confirm;
    const calls = mockSchedules();
    const r = await act(async () => render(wrap(<Schedules />, "/schedules")));
    await waitFor(() => expect(screen.getByTestId("toggle-refresh")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("toggle-refresh")); });
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
    confirm.mockReturnValue(true);
    await act(async () => { fireEvent.click(screen.getByTestId("toggle-refresh")); });
    expect(calls.filter((c) => c.method === "PUT").map((c) => [c.url, c.body])).toEqual([["/api/schedules/refresh", { enabled: true }]]);
    r.unmount();
  });
});
