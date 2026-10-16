import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import ShapTrace from "./pages/ShapTrace";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

const checks = (ok = true) => [
  { check: "SHAP_ENGINE_VS_LIGHTGBM", passed: ok, max_abs_diff: ok ? 0 : 1e-6, tolerance: 1e-12 },
  { check: "RAW_SCORE_ATTRIBUTION_VS_MODEL", passed: true, abs_diff: 8.4e-15, tolerance: 1e-9 },
  { check: "PUBLISHED_VALUE", passed: true, abs_diff: 0, tolerance: 1e-9 },
];
const trace = (status = "VERIFIED") => ({
  status,
  identity: { run_id: "FCR-1", model_sha256_file: "ec50", feature_row_hash: "5c07", link: "exp", n_trees: 300 },
  checks: checks(status === "VERIFIED"),
  values: { base_value: 1.9888380316076457, base_value_lightgbm: 1.9888380316076457, sum_shap: 1.4698, raw_score_from_attribution: 3.458671978427447,
    raw_score_from_model: 3.4586719784274385, link_of_raw: 31.774750927933475, model_output: 31.774750927933475, clipped: 31.774750927933475, rounded_4: 31.7748, published: 31.7748 },
  features: [],
  feature_view: {
    feature: { name: "zero_share_28", value: 0, shap_engine: 0.8394028043306269, shap_lightgbm: 0.8394028043306269, abs_diff: 0,
      catalog: { vi: { name: "Tỷ lệ ngày không có đơn (28 ngày)", formula: "Số ngày ĐÃ BIẾT = 0 ÷ số ngày ĐÃ BIẾT", unit: "tỷ lệ 0–1" }, en: { name: "Zero share", formula: "f", unit: "u" } },
      window: { from: "2026-09-16", to: "2026-10-13" } },
    summary: { n_trees_model: 300, n_trees_splitting_on_feature: 172, n_trees_with_terms: 172, n_terms: 3195, sum_positive_terms: 1.3024073751898055,
      sum_negative_terms: -0.46300457085918045, sum_positive_trees: 0.8428584677322585, sum_negative_trees: -0.0034556634016334044, total: 0.8394028043306269 },
    trees: { total: 172, page: 1, page_size: 20, items: Array.from({ length: 20 }, (_, i) => ({ tree: 19 + i, sum: 0.016595 - i * 1e-4, positive: 0.016995, negative: -0.0004, n_terms: 31,
      splits: [{ split: "zero_share_28 <= 0.053571430966258056 (missing=None, default_left)", row_goes: "left" }], actual_leaf: 25 })) },
  },
});
const leaves = { status: "VERIFIED", tree: 19, feature: "zero_share_28", expected_value: -0.013495370311577591, root_count: 44373, actual_leaf: 25, sum: 0.01659461691473846,
  items: [
    { leaf: 1, leaf_value: -0.058367, leaf_count: 11380, row_reaches_leaf: false, one_fraction: 0, zero_fraction: 0.256462, weight: 1, term: 0.014969,
      route: [{ split: "zero_share_28 <= 0.0535 (x)", went: "right", row_goes_this_way: false, cover_fraction: 0.2565, is_feature: true }] },
    { leaf: 25, leaf_value: 0.01291, leaf_count: 523, row_reaches_leaf: true, one_fraction: 1, zero_fraction: 0.743538, weight: 0.295031, term: 0.000977,
      route: [{ split: "zero_share_28 <= 0.0535 (x)", went: "left", row_goes_this_way: true, cover_fraction: 0.7435, is_feature: true }] }] };

function mock(body: any) {
  const urls: string[] = [];
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    urls.push(u);
    const b = u.includes("/shap-trace/tree") ? leaves : body;
    return new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return urls;
}

describe("TreeSHAP trace screen", () => {
  it("verified: level A explains raw-score scale, tree count, positive/negative terms; level B pages trees and opens leaf terms", async () => {
    const urls = mock(trace());
    await act(async () => { render(wrap(<ShapTrace runId="FCR-1" sku="A" fc="F" date="2026-10-14" feature="zero_share_28" onClose={() => {}} />)); });
    await waitFor(() => expect(screen.getByTestId("trace-level-a")).toBeTruthy());
    expect(screen.getByTestId("trace-status").textContent).toContain("Đã xác minh");
    const a = screen.getByTestId("trace-level-a").textContent ?? "";
    expect(a).toContain("+0,84");                                                     // 2 decimals at level A
    expect(a).toContain("ĐIỂM THÔ");
    expect(a).toContain("3.195 thành phần nằm trong 172 cây");
    expect(screen.getByTestId("trace-signs").textContent).toContain("+1,3");
    expect(screen.getByTestId("trace-signs").textContent).toContain("-0,46");
    expect(screen.getByTestId("trace-signs").textContent).toContain("triệt tiêu");
    expect(document.querySelectorAll("[data-testid=trace-trees] tbody tr").length).toBe(20);   // paged, never 172 rows at once
    expect(screen.getByTestId("trace-level-b").textContent).toContain("Trang 1 / 9");
    fireEvent.click(screen.getByTestId("trace-open-tree-19"));
    await waitFor(() => expect(screen.getByTestId("trace-leaves").textContent).toContain("44.373"));
    const leavesTxt = screen.getByTestId("trace-leaves").textContent ?? "";
    expect(leavesTxt).toContain("+0,014969");
    expect(leavesTxt).toContain("(dòng này KHÔNG đi)");
    expect(urls.some((u) => u.includes("/shap-trace/tree") && u.includes("tree=19") && u.includes("feature=zero_share_28"))).toBe(true);
    // level C: reconciliation with tolerances and full-precision values
    const c = screen.getByTestId("trace-level-c").textContent ?? "";
    expect(c).toContain("SHAP_ENGINE_VS_LIGHTGBM");
    expect(c).toContain("1e-12");
    expect(c).toContain("3.4586719784274385");
    expect(c).toContain("KHÔNG đúng bằng trung bình điểm thô");
    const dl = [...screen.getByTestId("trace-downloads").querySelectorAll("a")].map((x) => x.getAttribute("href") ?? "");
    expect(dl.some((h) => h.includes("shap-trace.xlsx") && h.includes("feature=zero_share_28"))).toBe(true);
    expect(dl.some((h) => h.includes("shap-trace.csv") && !h.includes("feature="))).toBe(true);
  });

  it("failed reconciliation is never shown as exact", async () => {
    mock(trace("FAILED"));
    await act(async () => { render(wrap(<ShapTrace runId="FCR-1" sku="A" fc="F" date="2026-10-14" feature="zero_share_28" onClose={() => {}} />)); });
    await waitFor(() => expect(screen.getByTestId("trace-status")).toBeTruthy());
    expect(screen.getByTestId("trace-status").textContent).toContain("Đối soát thất bại");
    expect(screen.getByTestId("trace-status").textContent).toContain("SHAP_ENGINE_VS_LIGHTGBM");
    expect(screen.getByTestId("trace-status").textContent).not.toContain("Đã xác minh");
  });

  it("missing artifact: says the trace cannot be reproduced and shows no numbers", async () => {
    mock({ status: "NOT_REPRODUCIBLE", reason: "MODEL_ARTIFACT_MISSING", identity: {} });
    await act(async () => { render(wrap(<ShapTrace runId="FCR-1" sku="A" fc="F" date="2026-10-14" feature="lag_1" onClose={() => {}} />)); });
    await waitFor(() => expect(screen.getByTestId("trace-status")).toBeTruthy());
    expect(screen.getByTestId("trace-status").textContent).toContain("Không đủ dữ liệu để tái hiện chính xác");
    expect(screen.queryByTestId("trace-level-a")).toBeNull();
  });
});
