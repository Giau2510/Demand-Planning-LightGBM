import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { ApiError, get } from "./api";
import { useAsync } from "./components/ui";
import { I18nProvider } from "./i18n";
import { FeatureGroups } from "./pages/Config";
import ExplainPanel, { EXPLAIN_TIMEOUT_MS } from "./pages/ExplainPanel";

// 1.2.8: the "how is this calculated" modal never spins endlessly (timeout with a clear error and "Try again", a closed
// modal or another day cancels the request and ignores its late answer), the forecast is a whole number, an older answer
// never replaces a newer one (horizon / day changed quickly), and the day-of-week switch.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });
afterEach(() => { vi.useRealTimers(); });

const REGISTRY = { methods: {}, reasons: {} };
const ex = (yhat: number, qty: number, day = "2026-10-20") => ({
  identity: { run_id: "FCR-1", model_version: "MV-1", data_source: "DEMO", scope_key: "DEMO-1", target_date: day, horizon_day: 1,
    data_as_of: "2026-10-19", run_created_at: "2026-10-20T08:06:21Z" },
  result: { method: "FALLBACK_NEW_SERIES", yhat, forecast_qty: qty, qty_rule: "ROUND_HALF_UP_NON_NEGATIVE" },
  selection: { source: "MISSING" }, history: { status: "DATA_CHANGED" }, reproduction: { status: "DATA_CHANGED" },
  quality: {}, notes: [],
});
const json = (body: any, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
type Pending = { url: string; signal?: AbortSignal; resolve: (r: Response) => void };
/** fetch whose explain answers are released by the test; /api/methods answers at once */
function mockExplain() {
  const pending: Pending[] = [];
  globalThis.fetch = vi.fn((url: any, init?: any) => {
    const u = String(url);
    if (u.startsWith("/api/methods")) return Promise.resolve(json(REGISTRY));
    return new Promise<Response>((resolve, reject) => {
      pending.push({ url: u, signal: init?.signal, resolve });
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    });
  }) as any;
  return pending;
}
const panel = (onClose = () => {}) => <ExplainPanel runId="FCR-1" sku="A" fc="F" date="2026-10-20" maxHorizon={7} origin="2026-10-20" onClose={onClose} />;
const day = (u: string) => new URL(u, "http://x").searchParams.get("target_date");

describe("v1.2.8 explanation modal", () => {
  it("success: the headline is the whole-number forecast; the stored model value only in the technical block", async () => {
    const p = mockExplain();
    await act(async () => { render(wrap(panel())); });
    expect(screen.getByTestId("ex-wait")).toBeTruthy();
    await act(async () => { p[0].resolve(json(ex(2.5, 3))); });
    expect(screen.getByTestId("ex-qty").textContent).toBe("3");
    expect(screen.queryByTestId("ex-wait")).toBeNull();
  });

  it("no data (404): the backend message, no spinner, and 'Try again' asks again", async () => {
    const p = mockExplain();
    await act(async () => { render(wrap(panel())); });
    await act(async () => { p[0].resolve(json({ code: "BATCH_NOT_FOUND", vi: "Không tìm thấy dòng dự báo.", en: "Not found." }, 404)); });
    expect(screen.getByRole("alert").textContent).toContain("Không tìm thấy dòng dự báo.");
    expect(screen.queryByTestId("ex-wait")).toBeNull();
    await act(async () => { fireEvent.click(screen.getByTestId("ex-retry")); });
    expect(p).toHaveLength(2);
    await act(async () => { p[1].resolve(json(ex(7.49, 7))); });
    expect(screen.getByTestId("ex-qty").textContent).toBe("7");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("backend error (500): a clear error and a retry, never an endless spinner", async () => {
    const p = mockExplain();
    await act(async () => { render(wrap(panel())); });
    await act(async () => { p[0].resolve(json({ code: "INTERNAL_ERROR", vi: "Lỗi hệ thống.", en: "Internal error.", category: "INTERNAL" }, 500)); });
    expect(screen.getByRole("alert").textContent).toContain("Lỗi hệ thống.");
    expect(screen.getByTestId("ex-retry")).toBeTruthy();
    expect(screen.queryByTestId("ex-wait")).toBeNull();
  });

  it("timeout: after EXPLAIN_TIMEOUT_MS the request is aborted and REQUEST_TIMEOUT is shown with 'Try again'", async () => {
    vi.useFakeTimers();
    const p = mockExplain();
    await act(async () => { render(wrap(panel())); });
    expect(screen.getByTestId("ex-wait")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(EXPLAIN_TIMEOUT_MS + 10); });
    expect(p[0].signal?.aborted).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Máy chủ chưa trả lời sau 180 giây");
    expect(screen.getByRole("alert").textContent).toContain("REQUEST_TIMEOUT");
    expect(screen.queryByTestId("ex-wait")).toBeNull();
    expect(screen.getByTestId("ex-retry")).toBeTruthy();
  });

  it("closing the modal while the request runs cancels it; its late answer changes nothing", async () => {
    const p = mockExplain();
    let r: ReturnType<typeof render>;
    await act(async () => { r = render(wrap(panel())); });
    await act(async () => { r.unmount(); });
    expect(p[0].signal?.aborted).toBe(true);
    await act(async () => { p[0].resolve(json(ex(4, 4))); });      // no error, nothing rendered
    expect(document.querySelector("[data-testid=ex-qty]")).toBeNull();
  });

  it("days chosen quickly one after another: each earlier request is cancelled, only the newest answer is shown", async () => {
    const p = mockExplain();
    await act(async () => { render(wrap(panel())); });
    await act(async () => { fireEvent.click(screen.getByText(/Ngày sau/)); });
    await act(async () => { fireEvent.click(screen.getByText(/Ngày sau/)); });
    expect(p.map((x) => day(x.url))).toEqual(["2026-10-20", "2026-10-21", "2026-10-22"]);
    expect(p[0].signal?.aborted && p[1].signal?.aborted).toBe(true);
    await act(async () => { p[2].resolve(json(ex(5.2, 5, "2026-10-22"))); });
    await act(async () => { p[0].resolve(json(ex(9, 9))); p[1].resolve(json(ex(8, 8, "2026-10-21"))); });
    expect(screen.getByTestId("ex-qty").textContent).toBe("5");
  });
});

describe("v1.2.8 api.get timeout / cancel", () => {
  it("without options a request is exactly as before (no signal)", async () => {
    const f = vi.fn(async () => json({ ok: 1 }));
    globalThis.fetch = f as any;
    expect(await get("/api/x")).toEqual({ ok: 1 });
    expect((f.mock.calls[0] as any[])[1]).toEqual({ headers: { Accept: "application/json" } });
  });
  it("timeout -> ApiError REQUEST_TIMEOUT; an answer in time passes through", async () => {
    mockExplain();
    const err = await get("/api/slow", { timeoutMs: 20 }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.body.code).toBe("REQUEST_TIMEOUT");
    globalThis.fetch = vi.fn(async () => json({ ok: 2 })) as any;
    expect(await get("/api/fast", { timeoutMs: 1000 })).toEqual({ ok: 2 });
  });
});

describe("v1.2.8 useAsync: an older answer never replaces a newer one (horizon changed twice quickly)", () => {
  it("shows the newest horizon's figures and keeps loading until the newest answered", async () => {
    const waits: Record<number, (v: string) => void> = {};
    function Host() {
      const [h, setH] = useState(7);
      const a = useAsync(() => new Promise<string>((r) => { waits[h] = r; }), [h]);
      return <><button onClick={() => setH(15)}>h15</button><button onClick={() => setH(30)}>h30</button>
        <span data-testid="v">{a.loading ? "loading" : a.data}</span></>;
    }
    await act(async () => { render(<Host />); });
    await act(async () => { fireEvent.click(screen.getByText("h15")); });
    await act(async () => { fireEvent.click(screen.getByText("h30")); });
    await act(async () => { waits[30]("total-30"); });
    expect(screen.getByTestId("v").textContent).toBe("total-30");
    await act(async () => { waits[15]("total-15"); waits[7]("total-7"); });       // late, older answers
    expect(screen.getByTestId("v").textContent).toBe("total-30");
    await act(async () => { fireEvent.click(screen.getByText("h15")); });
    expect(screen.getByTestId("v").textContent).toBe("loading");
  });
});

describe("v1.2.8 day-of-week switch", () => {
  it("not saved yet = on (as before); unticking saves feature_weekday=false", async () => {
    globalThis.fetch = vi.fn(async () => json({ decisions: {} })) as any;
    const set = vi.fn();
    await act(async () => { render(wrap(<FeatureGroups v={{ feature_lags: true, feature_rolling: true, feature_price: true, feature_calendar: true, feature_weekday: null }} set={set} />)); });
    const box = screen.getByTestId("fg-weekday") as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(set).toHaveBeenCalledWith({ feature_weekday: false });
    await waitFor(() => expect(screen.getByText(/NGÀY DỰ BÁO/)).toBeTruthy());
  });
});
