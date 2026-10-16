import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import Features from "./pages/Features";
import Mapping from "./pages/Mapping";
import { ValidationView } from "./pages/BigQuery";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

function mock(routes: Record<string, any>) {
  const calls: { url: string; body: any }[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    calls.push({ url: u, body: init?.body ? JSON.parse(init.body) : null });
    const key = Object.keys(routes).find((k) => u.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

const lbl = (vi: string) => ({ vi, en: vi });
const STATUS_LBL: Record<string, any> = { ACTIVE: lbl("Đang sử dụng"), DISABLED: lbl("Có dữ liệu nhưng chưa kích hoạt"), PLANNED: lbl("Đang lên kế hoạch"), UNAVAILABLE: lbl("Thiếu dữ liệu") };
const entry = (key: string, status: string, kind = "MODEL", extra: any = {}) => ({
  feature_key: key, kind, feature_group: kind === "MODEL" ? "DEMAND_HISTORY" : "PRICE_PROMOTION", display_name: lbl(key),
  availability_status: status, status_label: STATUS_LBL[status], reason: "X", reason_label: lbl("lý do"), source_column: null,
  default_or_missing_policy: null, aggregation_rule: null, in_active_model: kind === "MODEL" ? status === "ACTIVE" : false, ...extra,
});
const registry = {
  registry_version: "2026-10-15.1", feature_code_version: "fe-1", source: "BIGQUERY", scope: { label: "p.d.t" },
  coverage: { rows: 30, avg_unit_price: 0, avg_discount_rate: 0, promo_share: 0 },
  decisions: { promotion: { used: false, reason: "NO_DATA", coverage: 0, min_coverage: 0.5 } },
  next_training: { features: ["sku_code", "lag_1"], n_features: 28, feature_set_version: "FS-fe-1-abc" },
  active_model: { model_version: "MV-1", features: ["sku_code"], feature_set_version: "FS-fe-1-old", feature_set_version_stored: false },
  groups: { DEMAND_HISTORY: lbl("Nhu cầu lịch sử"), PRICE_PROMOTION: lbl("Giá & khuyến mãi"), SKU_AVAILABILITY: lbl("SKU"), FUTURE: lbl("Tương lai") },
  statuses: { ACTIVE: lbl("Đang sử dụng"), DISABLED: lbl("Có dữ liệu nhưng chưa kích hoạt"), PLANNED: lbl("Đang lên kế hoạch"), UNAVAILABLE: lbl("Thiếu dữ liệu") },
  counts: { ACTIVE: 1, DISABLED: 1, PLANNED: 1, UNAVAILABLE: 1 },
  entries: [entry("lag_1", "ACTIVE"), entry("promo_last", "UNAVAILABLE"), entry("deal_flag", "PLANNED", "PLANNED"),
    entry("open_hours", "DISABLED", "PLANNED", { source_column: "total_open_hours" })],
};

describe("v1.1.5 feature registry + BigQuery validation + mapping", () => {
  it("feature page: real statuses, planned features never shown as in use, next feature set version", async () => {
    mock({ "/api/features/registry": registry });
    await act(async () => { render(wrap(<Features />)); });
    await waitFor(() => expect(screen.getByTestId("feat-table")).toBeTruthy());
    const rows = [...document.querySelectorAll("[data-testid=feat-table] tbody tr")] as HTMLElement[];
    const st = Object.fromEntries(rows.map((r) => [r.querySelector(".mono")!.textContent, r.dataset.status]));
    expect(st).toEqual({ lag_1: "ACTIVE", promo_last: "UNAVAILABLE", deal_flag: "PLANNED", open_hours: "DISABLED" });
    const deal = rows.find((r) => r.textContent!.includes("deal_flag"))!;
    expect(deal.textContent).toContain("Đang lên kế hoạch");
    expect(deal.textContent).toContain("chưa quyết định");                       // no missing-value rule invented
    expect(screen.getByTestId("feat-next").textContent).toContain("FS-fe-1-abc");
    expect(screen.getByTestId("feat-active-model").textContent).toContain("tính lại");
    fireEvent.click(screen.getByText(/Thiếu dữ liệu/, { selector: "button" }));
    expect(document.querySelectorAll("[data-testid=feat-table] tbody tr").length).toBe(1);
  });

  it("validation view: numbers, reconciliation, blocking issues and stale result", () => {
    const v = {
      passed: false, checked_at: "2026-10-15T05:00:00+00:00", mapping_hash: "abc", estimated_bytes: 1024,
      range: { start: "2026-01-01", end: "2026-10-15" },
      stats: { n_sku: 120, n_fc: 3, n_series: 300, n_days: 287, min_date: "2026-01-01", max_date: "2026-10-14" },
      reconciliation: { rows_read: 1000, rows_valid: 990, rows_excluded: 10, qty_read: 5000, qty_valid: 4980, rows_ok: true, qty_ok: true, rows_null_date_outside_range: 0 },
      exclusions: { NULL_SKU: { rows: 10, qty: 20 } }, blocking_issues: [{ code: "EXACT_DUPLICATES", detail: { rows: 4 } }],
      warnings: [{ code: "MISSING_DAYS", detail: { count: 1 } }], missing_days: { count: 1, days: ["2026-01-15"] },
      categories: { order_status: [{ value: "DELIVERED", rows: 900, qty_valid: 4500 }] }, reference_completeness: {},
      outbound_vs_demand: { sum_outbound_valid: 4900, sum_demand_valid: 4980, ratio_outbound_to_demand: 0.9839 },
    };
    render(wrap(<ValidationView v={v} current={false} />));
    const txt = screen.getByTestId("bq-validation").textContent!;
    expect(txt).toContain("Không đạt");
    expect(txt).toContain("1.000");                    // vi number format
    expect(txt).toContain("Dòng trùng hoàn toàn");
    expect(txt).toContain("15/01/2026");
    expect(txt).toContain("ánh xạ/khoảng ngày cũ");
    expect(screen.getByTestId("bq-blocking").textContent).toContain("EXACT_DUPLICATES");
  });

  it("mapping: suggestion fills key and reference fields (not saved), save posts both mappings", async () => {
    const fm = { order_qty: { column: "demand_quantity", usage: "REQUIRED" }, sku_id: { column: "sku_code", usage: "REQUIRED" } };
    const calls = mock({
      "/api/bigquery/status": { settings: { dataset_id: "d", source_table: "t", field_mapping: {}, reference_mapping: {}, schema_snapshot: [] } },
      "/api/bigquery/suggest-mapping": { columns: [{ name: "demand_quantity", type: "FLOAT64" }, { name: "sku_code", type: "STRING" }, { name: "outbound_quantity", type: "FLOAT64" }],
        field_mapping: fm, reference_mapping: { outbound_qty: { column: "outbound_quantity", usage: "OPTIONAL" } },
        check: { ok: true, errors: [], warnings: [] }, notes: [{ field: "unit_price", code: "LEFT_UNMAPPED_NEEDS_BUSINESS_RULE" }] },
      "/api/bigquery/mapping": { check: { ok: true, errors: [], warnings: [] } },
    });
    await act(async () => { render(wrap(<Mapping />)); });
    await waitFor(() => expect(screen.getByTestId("map-suggest")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByTestId("map-suggest")); });
    await waitFor(() => expect(screen.getByTestId("map-notes")).toBeTruthy());
    expect((screen.getByLabelText("column-order_qty") as HTMLSelectElement).value).toBe("demand_quantity");
    expect((screen.getByLabelText("column-outbound_qty") as HTMLSelectElement).value).toBe("outbound_quantity");
    expect(screen.getByTestId("map-notes").textContent).toContain("LEFT_UNMAPPED_NEEDS_BUSINESS_RULE");
    expect(calls.some((c) => c.url.includes("/api/bigquery/mapping"))).toBe(false);        // nothing saved yet
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    const save = calls.find((c) => c.url.includes("/api/bigquery/mapping"))!;
    expect(save.body.field_mapping.order_qty.column).toBe("demand_quantity");
    expect(save.body.reference_mapping.outbound_qty.column).toBe("outbound_quantity");
  });
});
