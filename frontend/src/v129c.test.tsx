import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import Config, { FeatureGroups } from "./pages/Config";
import Mapping from "./pages/Mapping";
import { BackfillPreview } from "./pages/SqlSources";

// 1.2.9 (third batch): the model-input start rule is a visible data-policy setting (default = window start); the
// customer group is OFF by default and says when it has no data; the customer column is optional on the mapping page
// (only identifier-type columns offered); the backfill preview names the stored open hours a reload would lose.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); window.confirm = vi.fn(() => true); });

type Call = { url: string; method: string; body: any };
function mock(route: (u: string, c: Call) => any) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    const c = { url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const v = route(u, c);
    return new Response(JSON.stringify(v === undefined ? {} : v), { status: 200, headers: { "content-type": "application/json" } });
  }) as any;
  return calls;
}

describe("v1.2.9c model-input start rule", () => {
  it("defaults to the window start; the old card shows it read-only and the change goes through the guarded card (text + reason)", async () => {
    const data_policy = { stale_check_sources: ["BIGQUERY"], max_data_lag_days: 2, late_data_lookback_days: 3, min_date: null,
      price_outlier_factor: 10, window_start_date: "2026-01-01" };
    const gfields = { window_start_date: "2026-01-01", history_change_policy: "FOLLOW_SOURCE", history_day_check: true, source_time_travel_hours: 160,
      training_start_rule: "WINDOW_START" };
    const CONFIRM = "DOI-CHINH-SACH-DU-LIEU-2026-11-23";
    const calls = mock((u, c) => {
      if (u === "/api/data-policy/guarded/preview") return { before: { training_start_rule: "WINDOW_START" }, after: c.body.patch, changed: ["training_start_rule"],
        high_risk: true, needs_confirm_text: true, needs_acknowledged: false, impact: null, impacts: [], notes: [], warnings: [], busy: { busy: false } };
      if (u === "/api/data-policy/guarded" && c.method === "POST") return { applied: c.body.patch, version: 2 };
      if (u === "/api/data-policy/guarded") return { fields: gfields, defaults: { ...gfields, history_change_policy: "KEEP_OBSERVED_LINES" }, version: 1,
        confirm_text: CONFIRM, high_risk_fields: ["history_change_policy", "window_start_date", "training_start_rule"], reason_min_length: 10,
        locked_fields: ["window_start_date"], history: [] };
      if (c.method === "PUT") return c.body;
      return u.startsWith("/api/settings") ? { data_policy,
        quality: {}, horizons: { enabled: [7], choices: [7], max_allowed_days: 365 }, model: { feature_lags: true, feature_rolling: true,
          feature_price: true, forecast_strategy: "DIRECT" } } : {};
    });
    await act(async () => { render(wrap(<Config />)); });
    const sel = (await screen.findByTestId("cfg-training-start-rule")) as HTMLSelectElement;
    expect(sel.value).toBe("WINDOW_START");                              // never saved = the rule before
    expect(sel.disabled).toBe(true);                                     // the old card only shows it
    expect(document.body.textContent).toContain("Ngày đầu tiên có giờ mở bán (tạm thời)");
    // the old Save with nothing changed sends nothing (the rule is not part of what that card writes)
    fireEvent.click(within(sel.closest("section")!).getByRole("button", { name: "Lưu" }));
    await act(async () => { await Promise.resolve(); });
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    // the change itself: guarded card, preview, typed text + reason, apply
    fireEvent.click(await screen.findByTestId("gp-tsr-OPEN_HOURS_COVERAGE"));
    await act(async () => { fireEvent.click(screen.getByTestId("gp-preview")); });
    fireEvent.change(screen.getByTestId("gp-confirm-input"), { target: { value: CONFIRM } });
    fireEvent.change(screen.getByTestId("gp-reason"), { target: { value: "dung gio mo ban lam moc" } });
    await act(async () => { fireEvent.click(screen.getByTestId("gp-apply")); });
    const post = calls.find((c) => c.method === "POST" && c.url === "/api/data-policy/guarded")!;
    expect(post.body).toMatchObject({ patch: { training_start_rule: "OPEN_HOURS_COVERAGE" }, expected: { training_start_rule: "WINDOW_START" }, confirm_text: CONFIRM });
    expect(calls.some((c) => c.method === "PUT" && c.url === "/api/settings/data_policy")).toBe(false);
  });
});

describe("v1.2.9c customer group", () => {
  it("is off by default, switches only on an explicit click and says when the source has no customer counts", async () => {
    mock((u) => u.includes("/api/features/registry") ? { decisions: { customer: { used: false, reason: "NO_DATA" } } } : {});
    const set = vi.fn();
    const base = { feature_lags: true, feature_rolling: true, feature_price: true, feature_calendar: true };
    const r = await act(async () => render(wrap(<FeatureGroups v={base} set={set} />)));
    const box = screen.getByTestId("fg-customer") as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(screen.queryByTestId("fg-customer-nodata")).toBeNull();
    fireEvent.click(box);
    expect(set).toHaveBeenCalledWith({ feature_customer: true });
    r.unmount();
    await act(async () => { render(wrap(<FeatureGroups v={{ ...base, feature_customer: true }} set={set} />)); });
    await waitFor(() => expect(screen.getByTestId("fg-customer-nodata")).toBeTruthy());
    expect((screen.getByTestId("fg-price") as HTMLInputElement).checked).toBe(true);   // price stays as it is
  });

  it("mapping page: no customer column by default, only identifier-type columns offered, saved with the mapping", async () => {
    const COLS = [{ name: "so_code", type: "STRING" }, { name: "created_date", type: "DATE" }, { name: "sku_code", type: "STRING" },
      { name: "fc_code", type: "STRING" }, { name: "demand_quantity", type: "INTEGER" }, { name: "sales_price", type: "FLOAT" },
      { name: "total_open_hours", type: "FLOAT" }, { name: "customer_code", type: "STRING" }];
    const FMAP = { order_id: { column: "so_code", usage: "OPTIONAL" }, order_date: { column: "created_date", usage: "REQUIRED" },
      sku_id: { column: "sku_code", usage: "REQUIRED" }, fc_id: { column: "fc_code", usage: "REQUIRED" },
      order_qty: { column: "demand_quantity", usage: "REQUIRED" } };
    const RMAP = { open_hours: { column: "total_open_hours", usage: "OPTIONAL" } };
    const calls = mock((u) => {
      if (u.includes("/api/bigquery/status")) return { settings: { dataset_id: "d", source_table: "t", production_enabled: false,
        field_mapping: FMAP, reference_mapping: RMAP, schema_snapshot: COLS, extra_reference_columns: [], customer_id_column: "" },
        field_roles: {} };
      if (u.includes("/api/bigquery/mapping")) return { check: { ok: true, errors: [], warnings: [] }, production_switched_off: false };
      return {};
    });
    await act(async () => { render(wrap(<Mapping />)); });
    const sel = (await screen.findByTestId("map-customer")) as HTMLSelectElement;
    expect(sel.value).toBe("");
    const offered = Array.from(sel.options).map((o) => o.value);
    expect(offered).toContain("customer_code");
    expect(offered).not.toContain("sales_price");                       // FLOAT / DATE are not identifiers
    expect(offered).not.toContain("created_date");
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    expect(calls.find((c) => c.method === "POST" && c.url.includes("/api/bigquery/mapping"))!.body.customer_id_column).toBe("");
    fireEvent.change(sel, { target: { value: "customer_code" } });
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    const posts = calls.filter((c) => c.method === "POST" && c.url.includes("/api/bigquery/mapping"));
    expect(posts[posts.length - 1].body.customer_id_column).toBe("customer_code");
  });
});

describe("v1.2.9c backfill preview", () => {
  it("names the stored open hours a reload would lose, with rows and days", () => {
    const p = { preview_id: "BFP-3", status: "READY", checked_at: "2026-10-20T03:00:00+00:00", written: false,
      window: { start: "2026-01-01", end: "2026-10-18", days: 291 }, read: { rows_read: 10, rows_valid: 10, rows_error: 0, qty_valid: 9 },
      compare: { rows_stored_in_window: 10, qty_stored_in_window: 9, series_days_new: 0, series_days_updated: 0, series_days_unchanged: 10,
        series_days_removed: 0, days_with_changes: 0 },
      open_hours: { would_write: { OK: 5, MISSING: 5 }, stored_now: { OK: 10 },
        stored_ok_not_kept: { rows: 5, first_day: "2026-03-19", last_day: "2026-03-19", now_missing: 5, removed: 0 } },
      effects: { closed_days_in_window: 0, closed_days_with_changes: 0, not_written: [] },
      warnings: [{ code: "OPEN_HOURS_WOULD_BE_LOST", rows: 5, first_day: "2026-03-19", last_day: "2026-03-19", now_missing: 5, removed: 0 }] };
    render(wrap(<BackfillPreview p={p} />));
    const w = screen.getByTestId("bf-warning").textContent!;
    expect(w).toContain("làm mất giờ mở bán đã lưu");
    expect(w).toContain("5");
    expect(w).toContain("2026-03-19");
  });
});
