import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import SpikeEstimateCard from "./components/SpikeEstimateCard";

// 1.4.15 (lot 6): card "Ước lượng spike-lines" of the page "Job & Scheduler": a BigQuery dry run only (bytes and cap).
// Backend mocked (unit, fake fetch, no network).
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const GB = 1e9;
const RES = { business_date: "2026-11-22", scope_key: "BIGQUERY:p.d.t", cache_first_day: "2026-01-01", read_start: "2026-11-20", read_end: "2026-11-22", initial: false, reflag: false,
  status: "DRY_RUN", estimated_bytes: 1.5 * GB, cap_bytes: 10 * GB, estimated_gb: 1.5, rows_estimated: null,
  description: [{ code: "SPIKE_ESTIMATE_ONLY", vi: "Chỉ ƯỚC LƯỢNG: chạy thử BigQuery (dry run) cho lần đọc dòng đơn SO.", en: "Estimate only." }],
  run_with: "runner / CLI: spike-lines --date D [--initial --reflag] --yes" };

interface Call { url: string; method: string; body: any }
function backend(o: { estimate?: (b: any) => Response } = {}) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method, body });
    if (u === "/api/spike-lines/estimate") return o.estimate ? o.estimate(body) : json(RES);
    return json({ code: "TEST_UNAVAILABLE" }, 503);
  }) as any;
  return calls;
}
const run = async () => { await act(async () => { fireEvent.click(screen.getByTestId("spk-estimate")); }); };

describe("1.4.15 spike-lines estimate card", () => {
  it("says it only estimates and the real run stays with the runner / CLI; nothing is sent until the button is pressed", async () => {
    const calls = backend();
    render(wrap(<SpikeEstimateCard />));
    expect(screen.getByTestId("spk-intro").textContent).toContain("không đọc dòng nào, không ghi gì, không chạy thật");
    expect(screen.getByTestId("spk-run-with").textContent).toContain("Chạy thật vẫn qua runner / CLI");
    expect(calls).toEqual([]);
  });

  it("estimate with no date: body {initial:false, reflag:false}; shows the range, the bytes against the cap, no row count, the server note and the CLI", async () => {
    const calls = backend();
    render(wrap(<SpikeEstimateCard />));
    await run();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({ url: "/api/spike-lines/estimate", method: "POST", body: { initial: false, reflag: false } });
    expect(screen.getByTestId("spk-range").textContent).toContain("22/11/2026");
    expect(screen.getByTestId("spk-range").textContent).toContain("20/11/2026");
    expect(screen.getByTestId("spk-bytes").textContent).toMatch(/trần cho phép/);
    expect(screen.getByTestId("spk-no-rows").textContent).toContain("không đếm được số dòng");
    expect(screen.getByTestId("spk-cli").textContent).toContain("spike-lines --date D");
    expect(screen.getByTestId("spk-description").textContent).toContain("Chỉ ƯỚC LƯỢNG");
    expect(screen.queryByTestId("spk-over")).toBeNull();
  });

  it("with a day: the day is sent in ISO form", async () => {
    const calls = backend();
    render(wrap(<SpikeEstimateCard />));
    fireEvent.change(screen.getByPlaceholderText("DD/MM/YYYY"), { target: { value: "20/11/2026" } });
    await run();
    expect(calls[0].body).toEqual({ date: "2026-11-20", initial: false, reflag: false });
  });

  it("initial mode (+ reflag only when initial is on): the body carries them; an estimate over the cap is flagged", async () => {
    const calls = backend({ estimate: () => json({ ...RES, initial: true, reflag: true, estimated_bytes: 20 * GB, cap_bytes: 10 * GB }) });
    render(wrap(<SpikeEstimateCard />));
    const reflag = screen.getByTestId("spk-reflag") as HTMLInputElement;
    expect(reflag.disabled).toBe(true);                                  // reflag only goes with initial
    fireEvent.click(screen.getByTestId("spk-initial"));
    expect(reflag.disabled).toBe(false);
    fireEvent.click(reflag);
    await run();
    expect(calls[0].body).toEqual({ initial: true, reflag: true });
    expect(screen.getByTestId("spk-over").textContent).toContain("vượt trần byte");
    // turning initial off clears reflag
    fireEvent.click(screen.getByTestId("spk-initial"));
    expect(reflag.checked).toBe(false);
  });

  it("409 SPIKE_LINES_REFLAG_REQUIRED and 422 invalid day show the server's bilingual message; no result is kept", async () => {
    let which = 0;
    const errs = [
      () => json({ code: "SPIKE_LINES_REFLAG_REQUIRED", vi: "Phạm vi này đã có dấu đột biến: initial cần reflag", en: "Reflag required", detail: "x" }, 409),
      () => json({ code: "SPIKE_ESTIMATE_INVALID_DATE", vi: "Ngày không đúng dạng YYYY-MM-DD.", en: "Bad date", detail: "x" }, 422),
    ];
    backend({ estimate: () => errs[which]() });
    render(wrap(<SpikeEstimateCard />));
    await run();
    expect(await screen.findByText("Phạm vi này đã có dấu đột biến: initial cần reflag")).toBeTruthy();
    expect(screen.queryByTestId("spk-result")).toBeNull();
    which = 1; await run();
    expect(await screen.findByText("Ngày không đúng dạng YYYY-MM-DD.")).toBeTruthy();
    expect(screen.queryByTestId("spk-result")).toBeNull();
  });
});
