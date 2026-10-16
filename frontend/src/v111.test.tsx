import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { ALGORITHMS, GROUPS } from "./algorithms";
import { JobProgress, LineChart, MethodLabel, jobOutcome } from "./components/ui";
import Methodology from "./pages/Methodology";
import Results from "./pages/Results";

// Registry exported from backend/app/ml/methods.py (the same JSON /api/methods returns).
const REGISTRY = JSON.parse(readFileSync(join(__dirname, "test-fixtures", "methods.json"), "utf8"));
const BACKEND_ANCHORS = [...readFileSync(join(__dirname, "..", "..", "backend", "app", "ml", "methods.py"), "utf8")
  .matchAll(/"anchor":\s*"([^"]+)"/g)].map((m) => m[1]).sort();

const SETTINGS = {
  model: { min_total_history_days: 56, min_series_history_days: 28, intermittent_zero_share: 0.8, inactive_days: 60, fallback_window_days: 28,
    backtest_folds: 3, backtest_horizon_days: 14, backtest_step_days: 7, objective: "tweedie", num_boost_round: 300, learning_rate: 0.05, num_leaves: 31, max_train_days: 730 },
  quality: { wape_max: 0.6, abs_bias_max: 0.2, min_backtest_points: 200, require_beat_baseline: false, mape_min_actual: 1, approved_by_business: false },
  data_policy: { max_data_lag_days: 2, stale_check_sources: ["BIGQUERY"] },
  schedule: { d0_times: ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"], slot_grace_minutes: 20, train_time: "07:00",
    retry_base_seconds: 60, retry_max_seconds: 1800, max_attempts: 4, timeout_seconds: 3600 },
  horizons: { enabled: [7, 15] },
};

type Route = (u: string) => any;   // may return a Promise (simulated network latency)
function mockFetch(route: Route) {
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    const body = u.startsWith("/api/methods") ? REGISTRY : u.startsWith("/api/settings") ? SETTINGS : await route(u);
    if (body instanceof Error) throw body;
    return new Response(JSON.stringify(body ?? null), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
}
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;

beforeEach(() => localStorage.clear());

describe("method registry & algorithm page", () => {
  it("the fixture is the backend registry: same anchors, only real production codes", () => {
    const anchors = Object.values(REGISTRY.methods).map((m: any) => m.anchor).sort();
    expect(anchors).toEqual(BACKEND_ANCHORS);
    const prod = Object.values(REGISTRY.methods).filter((m: any) => m.scope === "production").map((m: any) => m.code).sort();
    expect(prod).toEqual(["FALLBACK_INACTIVE_ZERO", "FALLBACK_INTERMITTENT", "FALLBACK_NEW_SERIES", "LIGHTGBM"]);
  });

  it("every method tooltip anchor exists on the algorithm page; backtest-only code is labelled as such", async () => {
    mockFetch(() => ({}));
    await act(async () => { render(wrap(<Methodology />)); });
    await waitFor(() => expect(document.getElementById("method-lightgbm")).toBeTruthy());
    for (const a of BACKEND_ANCHORS) expect(document.getElementById(a), a).toBeTruthy();
    expect(screen.getByTestId("doc-method-fallback-model-unavailable").textContent).toContain("Chỉ dùng trong backtest");
    expect(screen.getByTestId("doc-method-lightgbm").textContent).not.toContain("Chỉ dùng trong backtest");
    for (const m of Object.values(REGISTRY.methods) as any[]) {   // every method: worked example + how to read it
      const txt = screen.getByTestId(`doc-${m.anchor}`).textContent ?? "";
      expect(txt).toContain(m.vi.example);
      expect(txt).toContain(m.vi.read);
    }
    expect(document.getElementById("algo-tweedie")).toBeTruthy();
    expect(document.getElementById("algo-jobs")!.closest("[id^=group-]")!.id).toBe("group-ops");
    expect(document.getElementById("algo-data-checks")!.closest("[id^=group-]")!.id).toBe("group-dataquality");
    // every group and algorithm has an anchor, every "related" link resolves
    for (const g of GROUPS) expect(document.getElementById(`group-${g.id}`)).toBeTruthy();
    for (const a of ALGORITHMS) {
      expect(document.getElementById(a.id), a.id).toBeTruthy();
      for (const r of a.related) expect(document.getElementById(r), `${a.id} -> ${r}`).toBeTruthy();
    }
    // live thresholds come from configuration
    await waitFor(() => expect(screen.getByText("quality.wape_max")).toBeTruthy());
    expect(screen.getByText("120 + 20 = 140 phút")).toBeTruthy();
  });

  it("algorithm entries are complete in both languages", () => {
    for (const a of ALGORITHMS) {
      expect(GROUPS.map((g) => g.id)).toContain(a.group);
      for (const l of ["vi", "en"] as const) {
        for (const f of ["name", "purpose", "inputs", "meaning", "limits"] as const) expect(a[l][f].trim().length, `${a.id}.${l}.${f}`).toBeGreaterThan(0);
        expect(a[l].steps.length).toBe(a[l === "vi" ? "en" : "vi"].steps.length);
      }
    }
    const metrics = ALGORITHMS.find((a) => a.id === "algo-metrics")!;
    expect(metrics.en.example).toContain("A = [100, 120, 80], F = [110, 100, 90]");   // verified in backend test_v111
  });

  it("MethodLabel shows a business name, opens on keyboard focus and links to the algorithm anchor", async () => {
    mockFetch(() => ({}));
    await act(async () => { render(wrap(<><MethodLabel code="FALLBACK_INTERMITTENT" /><MethodLabel code="SOMETHING_ELSE" /></>)); });
    const el = await screen.findByRole("button", { name: "Dự phòng cho nhu cầu gián đoạn" });
    fireEvent.focus(el);
    const tip = screen.getByRole("tooltip");
    expect(tip.querySelector("a")!.getAttribute("href")).toBe("/methodology#method-fallback-intermittent");
    expect(tip.textContent).toContain("FALLBACK_INTERMITTENT");
    fireEvent.keyDown(el, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.click(el);   // touch
    expect(screen.getByRole("tooltip")).toBeTruthy();
    expect(screen.getByText("SOMETHING_ELSE")).toBeTruthy();   // unknown code is shown raw, never renamed
  });
});

describe("intraday actual on the chart", () => {
  const pts = [{ x: "2026-10-14", y: 10 }, { x: "2026-10-15", y: 12 }, { x: "2026-10-16", y: 9 }];
  it("draws exactly one actual point, for today only", () => {
    const { container } = render(wrap(<LineChart points={pts} forecastLegend="F" actual={{ x: "2026-10-14", y: 4, legend: "A", tooltip: "t" }} />));
    expect(container.querySelectorAll("[data-testid=actual-point]").length).toBe(1);
  });
  it("draws nothing when there is no actual or today is outside the period", () => {
    const a = render(wrap(<LineChart points={pts} actual={null} />));
    expect(a.container.querySelectorAll("[data-testid=actual-point]").length).toBe(0);
    const b = render(wrap(<LineChart points={pts} actual={{ x: "2026-10-20", y: 4, legend: "A", tooltip: "t" }} />));
    expect(b.container.querySelectorAll("[data-testid=actual-point]").length).toBe(0);
  });
});

describe("job progress", () => {
  it("a polling error is shown as lost connection, never as failed", async () => {
    mockFetch(() => new Error("network down"));
    await act(async () => { render(wrap(<JobProgress jobId="JOB-1" />)); });
    await waitFor(() => expect(screen.getByText(/Mất kết nối tới máy chủ/)).toBeTruthy());
    expect(screen.queryByText("Thất bại")).toBeNull();
  });

  it("shows the real stage; training result and publish result are separate", async () => {
    mockFetch(() => ({ id: "JOB-2", job_type: "TRAIN_PUBLISH", status: "SUCCEEDED", stage: "DONE", elapsed_seconds: 75,
      started_at: "2026-10-14T09:00:00Z", finished_at: "2026-10-14T09:01:15Z",
      result: { result: { status: "REJECTED", reason_code: "QUALITY_GATE_FAILED" } } }));
    const done = vi.fn();
    await act(async () => { render(wrap(<JobProgress jobId="JOB-2" onDone={done} />)); });
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1));
    const box = screen.getByRole("status").textContent ?? "";
    expect(box).toContain("Hoàn tất — không đạt chất lượng");
    expect(box).toContain("Kết quả huấn luyện: Không đạt chất lượng");
    expect(box).toContain("Kết quả publish: Không publish");
    expect(box).toContain("1 min 15 s");
    expect(box).toContain("Kết thúc: 14/10/2026 16:01");   // finish time, Vietnam time, DD/MM/YYYY
    expect(box).not.toMatch(/\d+\s?%/);   // no percentage anywhere
  });

  it("outcome mapping", () => {
    expect(jobOutcome({ status: "RUNNING" })).toBe("running");
    expect(jobOutcome({ status: "RUNNING", stale: true })).toBe("unknown");
    expect(jobOutcome({ status: "SUCCEEDED", result: { result: { status: "PUBLISHED" } } })).toBe("ok");
    expect(jobOutcome({ status: "SUCCEEDED", result: { result: { status: "FAILED" } } })).toBe("bad");
    expect(jobOutcome({ status: "FAILED" })).toBe("bad");
  });
});

describe("results page: periods of an old run", () => {
  const run = { id: "FCR-1", created_at: "2026-10-14T08:06:21Z", data_source: "DEMO", scope_key: "DEMO-1", model_version: "MV-1",
    horizons: [7], max_horizon: 7, forecast_origin: "2026-10-14", data_as_of: "2026-10-13", skus: ["A"], fcs: ["F"],
    horizon_coverage: { run_horizons: [7], max_horizon: 7, configured: [7, 15], configured_missing_in_run: [15], can_extend_without_retraining: true, cannot_extend_reason: null } };
  it("never offers 15 days for a 7-day run; explains the gap and offers extension", async () => {
    mockFetch((u) => u.startsWith("/api/forecast-runs?") ? [run]
      : u.startsWith("/api/forecast-runs/FCR-1/summary") ? { n_series: 0, grand_total: 0, start_date: "2026-10-14", end_date: "2026-10-20", series: [], daily: [], actual: null }
      : u.startsWith("/api/forecast-runs/FCR-1/accuracy") ? null
      : u.startsWith("/api/forecast-runs/FCR-1") ? run
      : u.startsWith("/api/jobs/active") ? null : {});
    await act(async () => { render(wrap(<Results />)); });
    const notice = await screen.findByTestId("horizon-missing");
    expect(notice.textContent).toContain("15");
    expect(screen.getByRole("button", { name: "Bổ sung khoảng dự báo" })).toBeTruthy();
    const horizonOpts = [...document.querySelectorAll("option")].map((o) => o.textContent ?? "").filter((o) => /^\d+ ngày$/.test(o.trim()));
    expect(horizonOpts).toEqual(["7 ngày"]);
    // v1.1.2: every date on the page is DD/MM/YYYY (origin / data-as-of card included)
    await waitFor(() => expect(document.body.textContent).toContain("14/10/2026"));
    expect(document.body.textContent).toContain("13/10/2026");
    expect(document.body.textContent).not.toMatch(/(?<![:\w-])\d{4}-\d{2}-\d{2}/);
  });
});

// jsdom has no PointerEvent: without it pointerType is dropped and every pointer looks like a mouse
if (typeof (globalThis as any).PointerEvent === "undefined") {
  (globalThis as any).PointerEvent = class extends MouseEvent {
    pointerType: string;
    constructor(type: string, init: any = {}) { super(type, init); this.pointerType = init.pointerType ?? ""; }
  };
}

describe("acceptance regressions (v1.1.1 on the real machine)", () => {
  it("method tooltip opens on a touch tap and closes on the next tap; mouse hover opens and click keeps it open", async () => {
    mockFetch(() => ({}));
    await act(async () => { render(wrap(<MethodLabel code="LIGHTGBM" />)); });
    const el = await screen.findByRole("button", { name: "Mô hình học máy (LightGBM)" });
    // touch: pointerdown (touch) -> focus -> click, as a phone/tablet browser sends them
    fireEvent.pointerDown(el, { pointerType: "touch" });
    fireEvent.focus(el);
    fireEvent.click(el);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.pointerDown(el, { pointerType: "touch" });
    fireEvent.click(el);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.blur(el);
    // mouse: hover opens, click keeps it open, leaving closes
    fireEvent.pointerEnter(el, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.pointerDown(el, { pointerType: "mouse" });
    fireEvent.click(el);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.pointerLeave(el, { pointerType: "mouse" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("results page keeps the finished extension job visible (no reload loop, no endless 'loading')", async () => {
    const run = { id: "FCR-1", created_at: "2026-10-14T08:06:21Z", data_source: "DEMO", scope_key: "DEMO-1", model_version: "MV-1",
      horizons: [7], max_horizon: 7, forecast_origin: "2026-10-14", data_as_of: "2026-10-13", skus: ["A"], fcs: ["F"],
      horizon_coverage: { run_horizons: [7], max_horizon: 7, configured: [7, 15], configured_missing_in_run: [15], can_extend_without_retraining: true, cannot_extend_reason: null } };
    let jobPolls = 0;
    mockFetch((u) => {
      if (u.startsWith("/api/jobs/active")) return { id: "JOB-X", status: "RUNNING" };
      if (u.startsWith("/api/jobs/JOB-X")) {
        jobPolls += 1;
        return { id: "JOB-X", job_type: "FORECAST_EXTEND", status: "SUCCEEDED", stage: "DONE", elapsed_seconds: 3,
          started_at: "2026-10-14T09:51:21Z", finished_at: "2026-10-14T09:51:24Z", reason_code: "FORECAST_EXTENDED",
          result: { result: { status: "PUBLISHED", forecast_run_id: "FCR-1" } } };
      }
      return u.startsWith("/api/forecast-runs?") ? new Promise((r) => setTimeout(() => r([run]), 50))   // real latency
        : u.startsWith("/api/forecast-runs/FCR-1/summary") ? { n_series: 0, grand_total: 0, start_date: "2026-10-14", end_date: "2026-10-20", series: [], daily: [], actual: null }
        : u.startsWith("/api/forecast-runs/FCR-1/accuracy") ? null
        : u.startsWith("/api/forecast-runs/FCR-1") ? run : {};
    });
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Kết thúc"));
    await act(async () => { await new Promise((r) => setTimeout(r, 600)); });
    expect(screen.queryByText("Đang tải…")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Hoàn tất");
    expect(jobPolls).toBe(1);
  });
});
