import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider, useI18n } from "./i18n";
import { fmt2, fmtInt, roundingGap } from "./explainer";
import ForecastExplainer from "./pages/ForecastExplainer";

// 1.2.14: "Giải thích cách tính Forecast" - display rules and the five steps of the page (backend values are mocked
// here; their exactness against LightGBM is tested in backend/tests/test_v1214_forecast_explainer.py)
const wrap = (el: React.ReactNode, at = "/forecast-explainer") =>
  <I18nProvider><MemoryRouter initialEntries={[at]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

function Vi({ children }: { children: () => React.ReactNode }) {
  const { lang, setLang } = useI18n();
  if (lang !== "vi") { setLang("vi"); return null; }
  return <>{children()}</>;
}

describe("number display of the explainer", () => {
  it("at most 2 decimals, Vietnamese format, whole numbers without decimals, tiny values marked", () => {
    render(wrap(<Vi>{() => <span data-testid="n">{[fmt2(2.045674), fmt2(125.4), fmt2(-0.35), fmt2(2669), fmt2(0.003), fmt2(-0.001), fmt2(0),
      fmt2(null), fmt2(2627.285644), fmtInt(2429), fmtInt(125)].join("|")}</span>}</Vi>));
    expect(screen.getByTestId("n").textContent).toBe("2,05|125,40|-0,35|2.669|≈0,00|≈0,00|0|—|2.627,29|2.429|125");
  });
  it("tells when rounded parts do not add up to the rounded total (never adjusts the parts)", () => {
    expect(roundingGap([1.004, 1.004], 2.008)).toBe(true);     // 1,00 + 1,00 = 2,00 shown, total 2,01
    expect(roundingGap([1.88222, 5.91293], 7.79515)).toBe(true); // the real case: 1,88 + 5,91 = 7,79 shown, total 7,80
    expect(roundingGap([1.5, 2.25], 3.75)).toBe(false);
  });
});

const STEPS = [{ node: 0, feature: "roll_mean_28", feature_index: 2, value: 2627.28564453125, goes: "right", kind: "numerical", threshold: 21.01785755157471,
  missing_type: "None", default_left: true, nan_as_zero: false, rule: "GT" },
{ node: 7, feature: "sku_code", feature_index: 0, value: 3221, goes: "left", kind: "categorical", rule: "IN_SET", n_categories: 32, in_set: true,
  categories_sample: [195, 816, 3221] },
{ node: 9, feature: "lag_7", feature_index: 1, value: null, goes: "left", kind: "numerical", threshold: 3.5, missing_type: "NaN", default_left: true,
  nan_as_zero: false, rule: "DEFAULT" }];

function payload(over: any = {}) {
  return {
    status: "OK", reason: null, verified: true, cache: "MISS", computed_at: "2026-10-26T05:00:00+00:00",
    selection: { sku_id: "MEDX.DMTS-DON-SIL-001", fc_id: "BD", target_date: "2026-10-26", auto: true, horizon_day: 3, rule: "AUTO" },
    run: { forecast_run_id: "FCR-20261024163842-4EEFD8", model_version: "MV-20261024-163642-EA7D", training_run_id: "TRN-X", forecast_origin: "2026-10-24",
      data_as_of: "2026-10-23", run_created_at: "2026-10-24T16:38:52+00:00", max_horizon: 15, data_source: "BIGQUERY", train_start: "2026-01-01",
      train_end: "2026-10-23", strategy: "DIRECT", objective: "tweedie" },
    data: { rows_in_window: 296, first_order_date: "2026-01-01", last_loaded_at: "2026-10-26T02:58:46+00:00", scope_days_with_data: 296,
      unknown_days_in_window: 0, origin: "2026-10-24", override_applied: false,
      changes_after_run: { status: "SAME_INPUTS", unchanged: true, rows_loaded_after_run: 4, run_created_at: "2026-10-24T16:38:52+00:00",
        records: [{ date: "2026-10-22", action: "UPDATE", sync_run: "D1L-1", at: "2026-10-25T15:16:18+00:00", model_input: false, changed: { n_orders: { before: 261, after: 262 } } }] },
      history: [{ date: "2026-10-23", state: "ROW", qty_row: 2669, y: 2669, n_orders: 223, price_row: 20065.417759, price_used: 20065.417759, open_hours: 24, customers: 180 }] },
    features: [
      { name: "sku_code", index: 0, value: 3221, kind: "category_code", params: { key: "MEDX.DMTS-DON-SIL-001" }, inputs: [], recomputed: 3221, verified: true },
      { name: "lag_7", index: 1, value: null, kind: "lag", params: { k: 7 }, inputs: [], recomputed: null, verified: true },
      { name: "roll_mean_28", index: 2, value: 2627.28564453125, kind: "mean", params: { w: 28, n_known: 2, sum: 5254.5714 },
        inputs: [{ date: "2026-10-22", value: 3302 }, { date: "2026-10-23", value: 1952.5714 }], recomputed: 2627.2857, verified: true },
      { name: "price_rel_28", index: 3, value: 0.9999953508377075, kind: "ratio_to_mean", params: { numerator: 20065.4178, mean: 20065.5111, w: 28 }, inputs: [], recomputed: 0.99999533, verified: true },
    ],
    trees: { count: 3, tree0_shrinkage: 1, tree0_value: 1.8822196267371198, rest_sum: 5.912928278516787, positive_sum: 7.83, negative_sum: -0.03,
      top: [{ index: 0, leaf: 3, leaf_value: 1.8822196267371198 }],
      summary: [{ index: 0, leaf: 3, leaf_value: 1.8822196267371198, depth: 3 }, { index: 1, leaf: 25, leaf_value: 0.2420122280460706, depth: 5 },
        { index: 2, leaf: 3, leaf_value: 5.670916050470716, depth: 4 }] },
    aggregation: { objective: "tweedie", link: "log", raw_sum: 7.795147905253907, raw_lightgbm: 7.795147905253907, prediction: 2428.788628512767,
      prediction_lightgbm: 2428.788628512767, tweedie_variance_power: 1.2 },
    result: { clipped: 2428.788628512767, published: 2428.7886, stored_yhat: 2428.7886, difference: 0, match: true, forecast_qty: 2429,
      forecast_qty_recomputed: 2429, qty_rule: "ROUND_HALF_UP_NON_NEGATIVE", method: "LIGHTGBM" },
    checks: [{ check: "TREE_LEAVES_EQUAL_LIGHTGBM", ok: true, detail: "3 trees" }, { check: "PUBLISHED_EQUALS_STORED", ok: true, detail: 0 }],
    ...over,
  };
}

function backend(main: any) {
  const calls: { url: string; method: string }[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    calls.push({ url: u, method: (init?.method ?? "GET").toUpperCase() });
    const body = u.startsWith("/api/forecast-explainer/trees")
      ? { status: "OK", total: 3, offset: 0, limit: 20, trees: [{ index: 0, leaf: 3, leaf_value: 1.8822196267371198, depth: 3, steps: STEPS }] }
      : main;
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

describe("the page", () => {
  it("shows the five steps for the real SKU, with formulas, values and the final whole number; GET only", async () => {
    const calls = backend(payload());
    const r = await act(async () => render(wrap(<Vi>{() => <ForecastExplainer />}</Vi>)));
    await waitFor(() => expect(screen.getByTestId("fexp-page")).toBeTruthy());
    const txt = r.container.textContent ?? "";
    for (const s of ["Bước 1 — Dữ liệu nguồn", "Bước 2 — Tạo 4 feature", "Bước 3 — Đi qua 3 cây quyết định", "Bước 4 — Tổng hợp kết quả từ model",
      "Bước 5 — Kết quả forecast cuối cùng", "MV-20261024-163642-EA7D", "FCR-20261024163842-4EEFD8", "MEDX.DMTS-DON-SIL-001"]) expect(txt).toContain(s);
    expect(screen.getByTestId("fexp-final").textContent).toBe("2.429");
    expect(screen.getByTestId("fexp-final-2").textContent).toBe("2.429");
    const rm = r.container.querySelector("[data-feature=roll_mean_28]")!.textContent!;
    expect(rm).toContain("(3.302 + 1.952,57) / 2 = 5.254,57 / 2 = 2.627,29");
    expect(r.container.querySelector("[data-feature=lag_7]")!.textContent).toContain("NaN");
    expect(screen.getByTestId("fexp-sum").textContent).toBe("điểm thô = 1,88 + 5,91 = 7,80");
    expect(screen.getByTestId("fexp-link").textContent).toBe("dự đoán = e^7,80 = 2.428,79");
    expect(screen.getByTestId("fexp-match")).toBeTruthy();
    expect(screen.getByTestId("fexp-changes").textContent).toContain("n_orders: 261 → 262");
    const nums = [...r.container.querySelectorAll(".num")].map((e) => e.textContent ?? "");
    expect(nums.length).toBeGreaterThan(10);
    for (const n of nums) expect(n, n).not.toMatch(/,\d{3,}/);           // never more than 2 decimals on screen
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(calls.some((c) => c.url.startsWith("/api/forecast-explainer/trees?offset=0&limit=20"))).toBe(true);
    r.unmount();
  });

  it("opens the path of a tree: feature, threshold, real value and branch", async () => {
    backend(payload());
    const r = await act(async () => render(wrap(<Vi>{() => <ForecastExplainer />}</Vi>)));
    await waitFor(() => expect(r.container.querySelector("[data-tree='0']")).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByLabelText("tree-0")));
    const path = await waitFor(() => screen.getByTestId("fexp-path-0"));
    expect(path.textContent).toContain("roll_mean_28: 2.627,29 > 21,02 → nhánh phải");
    expect(path.textContent).toContain("sku_code = 3.221 thuộc tập 32 mã (195, 816, 3221, …) → nhánh trái");
    expect(path.textContent).toContain("lag_7 không có giá trị → theo hướng mặc định của nút → nhánh trái");
    expect(path.textContent).toContain("Lá 3: giá trị 1,88");
    r.unmount();
  });

  it("a recomputation that differs from the stored forecast is shown as a warning, never adjusted", async () => {
    backend(payload({ verified: false, result: { ...payload().result, published: 2500.12, match: false, forecast_qty_recomputed: 2500 } }));
    const r = await act(async () => render(wrap(<Vi>{() => <ForecastExplainer />}</Vi>)));
    const alert = await waitFor(() => screen.getByTestId("fexp-mismatch"));
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toContain("tính lại 2.500,12 (số nguyên 2.500), đã lưu 2.428,79 (số nguyên 2.429)");
    expect(screen.getByTestId("fexp-final").textContent).toBe("2.429");     // the stored whole number stays the result
    r.unmount();
  });

  it("without a forecast to explain: a state with its reason, no crash", async () => {
    backend({ status: "NO_FORECAST", reason: "DEMO_SOURCE: the forecast in use is built on demo data" });
    const r = await act(async () => render(wrap(<Vi>{() => <ForecastExplainer />}</Vi>)));
    await waitFor(() => expect(r.container.textContent).toContain("Chưa có forecast thật nào đang được dùng để giải thích."));
    expect(r.container.textContent).toContain("DEMO_SOURCE");
    r.unmount();
  });
});
