import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { isoWeekday, weekdayLabel } from "./components/ui";
import Mapping, { SourceColumns, WeekdayCard } from "./pages/Mapping";
import Results from "./pages/Results";
import { FeatureGroups } from "./pages/Config";

// 1.2.9: one weekday convention (1 = Thứ 2 ... 7 = Chủ nhật) in the daily forecast table; roles of every D-1 column and
// the mandatory open hours on the mapping page; the day-of-week switch saved for real (and "not saved" said).
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

describe("v1.2.9 weekday formatter", () => {
  it("labels 1..7 as Thứ 2 ... Chủ nhật and refuses anything else", () => {
    expect([1, 2, 3, 4, 5, 6, 7].map((n) => weekdayLabel(n, "vi"))).toEqual(["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]);
    expect(weekdayLabel(7, "en")).toBe("Sunday");
    for (const bad of [0, 8, -1, 2.5, NaN, null, undefined]) expect(weekdayLabel(bad as any, "vi")).toBe("—");
  });

  it("computes the weekday from the calendar date itself, whatever the browser time zone", () => {
    expect(["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"].map(isoWeekday))
      .toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(isoWeekday("2026-12-31")).toBe(4);           // year end
    expect(isoWeekday("2027-01-01")).toBe(5);
    expect(isoWeekday("2028-02-29")).toBe(2);           // leap day
    expect(isoWeekday("2026-10-25T23:30:00+07:00")).toBe(7);   // the date part only: no shift to the next / previous day
    expect(isoWeekday("2026-02-30")).toBeNull();        // impossible date: no guessed weekday
    expect(isoWeekday("")).toBeNull();
    expect(isoWeekday(null)).toBeNull();
  });
});

const RUN = { id: "FCR-1", created_at: "2026-10-19T12:00:00Z", data_source: "BIGQUERY", scope_key: "BIGQUERY:p.d.t", model_version: "MV-1",
  horizons: [7], max_horizon: 7, forecast_origin: "2026-10-20", data_as_of: "2026-10-19", active_scope: true, skus: [], fcs: ["HN"],
  horizon_coverage: { run_horizons: [7], max_horizon: 7, configured: [7], configured_missing_in_run: [], can_extend_without_retraining: false, cannot_extend_reason: null } };
const DAYS = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26"];
const ROWS = DAYS.map((d, i) => ({ sku_id: "S1", fc_id: "HN", target_date: d, horizon_day: i + 1, yhat: 1.4, forecast_qty: 1,
  method: "LIGHTGBM", product_name: null, actual_today: null, weekday: ((i + 1) % 7) + 1 }));       // 20/10/2026 = Tuesday = 2

describe("v1.2.9 daily forecast table: weekday names", () => {
  it("shows Thứ 3 ... Thứ 2 for 20/10 ... 26/10 (the weekday of each date, not the position in the period)", async () => {
    mock((u) => {
      if (u.startsWith("/api/forecast-runs?")) return [{ ...RUN, assessment: null }];
      if (u.startsWith("/api/forecast-runs/FCR-1/values")) return { total: ROWS.length, rows: ROWS, horizon: 7, actual: null, qty_rule: "ROUND_HALF_UP_NON_NEGATIVE" };
      if (u.startsWith("/api/forecast-runs/FCR-1/summary")) return { n_series: 1, grand_total: 7, start_date: "2026-10-20", end_date: "2026-10-26", series: [], daily: [], actual: null };
      if (u.startsWith("/api/forecast-runs/FCR-1/accuracy")) return null;
      if (u.startsWith("/api/forecast-runs/FCR-1")) return RUN;
      return {};
    });
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect(screen.getByText("Dự báo chi tiết từng ngày")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByText("Dự báo chi tiết từng ngày")); });
    await waitFor(() => expect(screen.getAllByTestId("fc-weekday")).toHaveLength(7));
    const cells = screen.getAllByTestId("fc-weekday");
    expect(cells.map((c) => c.textContent)).toEqual(["Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật", "Thứ 2"]);
    expect(cells[0].getAttribute("title")).toBe("Ngày thứ 1");             // the position in the period stays available
    expect(cells[6].getAttribute("title")).toBe("Ngày thứ 7");
    const heads = [...document.querySelectorAll("table.tbl thead th")].map((th) => th.textContent);
    expect(heads).toContain("Thứ");
    expect(heads).not.toContain("Ngày thứ");
  });

  it("falls back to the date when an older backend sends no weekday, and never guesses a broken value", async () => {
    mock((u) => {
      if (u.startsWith("/api/forecast-runs?")) return [{ ...RUN, assessment: null }];
      if (u.startsWith("/api/forecast-runs/FCR-1/values")) return { total: 2, horizon: 7, actual: null,
        rows: [{ ...ROWS[0], weekday: undefined }, { ...ROWS[1], weekday: 9 }] };
      if (u.startsWith("/api/forecast-runs/FCR-1/summary")) return { n_series: 1, grand_total: 2, series: [], daily: [], actual: null };
      if (u.startsWith("/api/forecast-runs/FCR-1/accuracy")) return null;
      if (u.startsWith("/api/forecast-runs/FCR-1")) return RUN;
      return {};
    });
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect(screen.getByText("Dự báo chi tiết từng ngày")).toBeTruthy());
    await act(async () => { fireEvent.click(screen.getByText("Dự báo chi tiết từng ngày")); });
    await waitFor(() => expect(screen.getAllByTestId("fc-weekday")).toHaveLength(2));
    expect(screen.getAllByTestId("fc-weekday").map((c) => c.textContent)).toEqual(["Thứ 3", "—"]);
  });
});

const ROLES = { order_id: "KEY", created_at: "KEY", order_date: "KEY", sku_id: "KEY", fc_id: "KEY", order_qty: "TARGET",
  unit_price: "OPTIONAL_FEATURE", open_hours: "REQUIRED_FEATURE", sales_price: "REFERENCE", product_id: "REFERENCE" };
const COLS = [{ name: "so_code", type: "STRING" }, { name: "created_date", type: "DATE" }, { name: "sku_code", type: "STRING" },
  { name: "fc_code", type: "STRING" }, { name: "demand_quantity", type: "INTEGER" }, { name: "sales_price", type: "FLOAT" },
  { name: "total_open_hours", type: "FLOAT" }, { name: "seller_class", type: "STRING" }, { name: "refresh_time", type: "STRING" }];
const FMAP = { order_id: { column: "so_code", usage: "OPTIONAL" }, order_date: { column: "created_date", usage: "REQUIRED" },
  sku_id: { column: "sku_code", usage: "REQUIRED" }, fc_id: { column: "fc_code", usage: "REQUIRED" },
  order_qty: { column: "demand_quantity", usage: "REQUIRED" }, unit_price: { column: "sales_price", usage: "OPTIONAL" } };
const RMAP = { sales_price: { column: "sales_price", usage: "OPTIONAL" }, open_hours: { column: "total_open_hours", usage: "OPTIONAL" } };

describe("v1.2.9 mapping: roles of every D-1 column", () => {
  it("lists every column with its role; unused ones are 'Chưa phân loại' until marked reference", () => {
    const setExtra = vi.fn();
    render(wrap(<SourceColumns cols={COLS} m={FMAP} refM={RMAP} extra={["seller_class"]} setExtra={setExtra} roles={ROLES} />));
    const role = (n: string) => screen.getByTestId(`map-col-${n}`).querySelector("[data-role]")?.getAttribute("data-role");
    expect(role("sku_code")).toBe("KEY");
    expect(role("demand_quantity")).toBe("TARGET");
    expect(role("total_open_hours")).toBe("REQUIRED_FEATURE");
    expect(role("sales_price")).toBe("OPTIONAL_FEATURE");                 // input + reference field: the input role wins
    expect((screen.getByLabelText("classify-seller_class") as HTMLSelectElement).value).toBe("REFERENCE");
    expect((screen.getByLabelText("classify-refresh_time") as HTMLSelectElement).value).toBe("");   // not classified
    fireEvent.change(screen.getByLabelText("classify-refresh_time"), { target: { value: "REFERENCE" } });
    expect(setExtra).toHaveBeenCalledWith(["seller_class", "refresh_time"]);
    expect(screen.getByTestId("map-col-counts").textContent).toContain("Chưa phân loại: 1");
    expect(screen.queryByTestId("map-conflict-demand_quantity")).toBeNull();
  });

  it("flags a column feeding a key/target and an input at once", () => {
    render(wrap(<SourceColumns cols={COLS} m={FMAP} refM={{ ...RMAP, open_hours: { column: "demand_quantity", usage: "OPTIONAL" } }}
      extra={[]} setExtra={() => {}} roles={ROLES} />));
    expect(screen.getByTestId("map-conflict-demand_quantity").textContent).toContain("Xung đột vai trò");
  });

  it("shows open hours as a mandatory input that cannot be switched off and saves the classification", async () => {
    const calls = mock((u) => {
      if (u.includes("/api/bigquery/status")) return { settings: { dataset_id: "d", source_table: "t", production_enabled: false,
        field_mapping: FMAP, reference_mapping: RMAP, schema_snapshot: COLS, extra_reference_columns: [] }, field_roles: ROLES };
      if (u.includes("/api/bigquery/mapping")) return { check: { ok: true, errors: [], warnings: [] }, production_switched_off: false };
      return {};
    });
    await act(async () => { render(wrap(<Mapping />)); });
    await waitFor(() => expect(screen.getByTestId("usage-locked-open_hours")).toBeTruthy());
    expect(screen.queryByLabelText("usage-open_hours")).toBeNull();                       // no way to set it "not used"
    expect(screen.getByTestId("usage-locked-open_hours").textContent).toContain("Bắt buộc");
    expect(screen.getByTestId("map-row-open_hours").querySelector("[data-role]")?.getAttribute("data-role")).toBe("REQUIRED_FEATURE");
    fireEvent.change(screen.getByLabelText("classify-seller_class"), { target: { value: "REFERENCE" } });
    await act(async () => { fireEvent.click(screen.getByText("Kiểm tra & lưu ánh xạ")); });
    const save = calls.find((c) => c.method === "POST" && c.url.includes("/api/bigquery/mapping"))!;
    expect(save.body.extra_reference_columns).toEqual(["seller_class"]);
    expect(save.body.reference_mapping.open_hours).toEqual({ column: "total_open_hours", usage: "OPTIONAL" });
  });
});

describe("v1.2.9 day-of-week switch", () => {
  const model = { feature_lags: true, feature_rolling: true, feature_calendar: true, feature_price: true, feature_weekday: null,
    feature_open_hours: null, weekday_encoding: null };

  it("mapping page: says 'not saved' until saved, then PUTs model.feature_weekday and reloads", async () => {
    let saved: any = { ...model };
    const calls = mock((u, c) => {
      if (u.includes("/api/settings/model") && c.method === "PUT") { saved = c.body; return saved; }
      if (u.includes("/api/settings")) return { model: saved };
      return {};
    });
    await act(async () => { render(wrap(<WeekdayCard />)); });
    await waitFor(() => expect(screen.getByTestId("map-weekday")).toBeTruthy());
    const box = screen.getByTestId("map-weekday") as HTMLInputElement;
    expect(box.checked).toBe(true);                                     // never saved = on, as every earlier model
    expect(screen.getByTestId("map-weekday-state").textContent).toContain("chưa từng lưu riêng");
    expect((screen.getByTestId("map-weekday-save") as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { fireEvent.click(box); });
    expect(screen.getByTestId("map-weekday-state").textContent).toContain("Chưa lưu");
    await act(async () => { fireEvent.click(screen.getByTestId("map-weekday-save")); });
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toContain("/api/settings/model");
    expect(put.body.feature_weekday).toBe(false);
    expect(put.body.feature_open_hours).toBeNull();                     // the mandatory input is never switched here
    await waitFor(() => expect(screen.getByTestId("map-weekday-state").textContent).toContain("Đã lưu: TẮT"));
  });

  it("configuration page: open hours shown as mandatory, never a switch", async () => {
    mock(() => ({}));
    const set = vi.fn();
    await act(async () => { render(wrap(<FeatureGroups v={model} set={set} />)); });
    const oh = screen.getByTestId("fg-open-hours") as HTMLInputElement;
    expect(oh.checked && oh.disabled).toBe(true);
    expect(document.body.textContent).toContain("Thứ 2 = 1");
    expect(document.body.textContent).toContain("Sử dụng thứ trong tuần khi dự báo");
  });
});
