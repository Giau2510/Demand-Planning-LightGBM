import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider, useI18n } from "./i18n";
import { DateInput, LineChart, fmtDate, fmtDateish, fmtDatesInText, fmtNum, fmtPct, fmtTime, parseDmy } from "./components/ui";
import ExplainPanel from "./pages/ExplainPanel";

const REGISTRY = JSON.parse(readFileSync(join(__dirname, "test-fixtures", "methods.json"), "utf8"));
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => localStorage.clear());

/** Renders `children()` once the UI language is `lang` (formatters read the language during render). */
function InLang({ lang, children }: { lang: "vi" | "en"; children: () => React.ReactNode }) {
  const { lang: cur, setLang } = useI18n();
  if (cur !== lang) { setLang(lang); return null; }
  return <>{children()}</>;
}

describe("A. numbers without trailing zeros", () => {
  it("Vietnamese UI: comma decimal, no meaningless zeros, significant decimals kept", () => {
    render(wrap(<InLang lang="vi">{() => <span data-testid="n">{[fmtNum(7.2, 6), fmtNum(10.0, 6), fmtNum(0.5, 4), fmtNum(7.2345, 4), fmtNum(72, 2), fmtNum(1234.5, 2), fmtPct(0.1333, 1)].join("|")}</span>}</InLang>));
    expect(screen.getByTestId("n").textContent).toBe("7,2|10|0,5|7,2345|72|1.234,5|13,3%");
  });
  it("English UI: point decimal", () => {
    render(wrap(<InLang lang="en">{() => <span data-testid="n">{[fmtNum(7.2, 6), fmtNum(1234.5, 2)].join("|")}</span>}</InLang>));
    expect(screen.getByTestId("n").textContent).toBe("7.2|1,234.5");
  });
  it("formatting never changes the number used for calculations; significant decimals kept up to the limit", () => {
    render(wrap(<InLang lang="vi">{() => <span data-testid="n">{fmtNum(46.947368421, 6)}</span>}</InLang>));
    const v = 7.2;
    fmtNum(v, 6);
    expect(v).toBe(7.2);
    expect(screen.getByTestId("n").textContent).toBe("46,947368");
  });
});

describe("B. dates are DD/MM/YYYY everywhere", () => {
  it("calendar dates are never shifted by time zones", () => {
    expect(fmtDate("2026-10-14")).toBe("14/10/2026");
    expect(fmtDate("2026-01-01")).toBe("01/01/2026");
  });
  it("timestamps are shown in Vietnam time with the date in DD/MM/YYYY, also across midnight", () => {
    expect(fmtTime("2026-10-14T11:00:00+00:00")).toBe("14/10/2026 18:00");
    expect(fmtTime("2026-10-14T17:30:00Z")).toBe("15/10/2026 00:30");
    expect(fmtDate("2026-10-14T17:30:00Z")).toBe("15/10/2026");
    expect(fmtTime("2026-10-14")).toBe("14/10/2026");
  });
  it("raw values and free text: dates converted, anything unparseable kept as is", () => {
    expect(fmtDateish("2026-10-14 08:30:00")).toBe("14/10/2026 08:30");
    expect(fmtDateish("2026-10-14 08:30:15")).toBe("14/10/2026 08:30:15");
    expect(fmtDateish("14/13/2026")).toBe("14/13/2026");
    expect(fmtDateish("abc")).toBe("abc");
    expect(fmtDatesInText("data_as_of 2026-10-13 differs (run 2026-10-14T08:06:21+00:00)")).toBe("data_as_of 13/10/2026 differs (run 14/10/2026 15:06)");
    expect(fmtDatesInText("JOB-20261014103641-8A59D5 backup-20261014-173421-manual.zip")).toBe("JOB-20261014103641-8A59D5 backup-20261014-173421-manual.zip");
  });
  it("DD/MM/YYYY input parsing rejects impossible dates", () => {
    expect(parseDmy("05/11/2026")).toBe("2026-11-05");
    expect(parseDmy("5/1/2026")).toBe("2026-01-05");
    expect(parseDmy("31/02/2026")).toBeNull();
    expect(parseDmy("2026-11-05")).toBeNull();
  });
  it("date picker shows DD/MM/YYYY, returns ISO and rejects dates outside the allowed range", () => {
    function Host() {
      const [v, setV] = useState("2026-10-14");
      return <><DateInput value={v} onChange={setV} min="2026-10-01" max="2026-10-31" ariaLabel="d" /><span data-testid="iso">{v}</span></>;
    }
    render(wrap(<Host />));
    const input = screen.getByLabelText("d") as HTMLInputElement;
    expect(input.value).toBe("14/10/2026");
    fireEvent.change(input, { target: { value: "20/10/2026" } });
    expect(screen.getByTestId("iso").textContent).toBe("2026-10-20");
    fireEvent.change(input, { target: { value: "20/11/2026" } });
    fireEvent.blur(input);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("iso").textContent).toBe("2026-10-20");
  });
  it("chart axis uses DD/MM/YYYY", () => {
    const { container } = render(wrap(<LineChart points={[{ x: "2026-10-14", y: 1 }, { x: "2026-10-15", y: 2 }]} />));
    const labels = [...container.querySelectorAll("text.axis")].map((e) => e.textContent ?? "").filter((x) => x.includes("/"));
    expect(labels).toEqual(["14/10/2026", "15/10/2026"]);
  });
});

describe("A + C. explanation: compact numbers and dated history", () => {
  // demand differs every day so a wrong date <-> demand pairing is detected
  const days = [
    { date: "2026-10-04", qty: null, status: "BEFORE_START", in_calc: false },
    { date: "2026-10-05", qty: 5, status: "ORDERS", in_calc: true },
    { date: "2026-10-06", qty: 0, status: "ZERO_ORDERS", in_calc: true },
    { date: "2026-10-07", qty: 12, status: "ORDERS", in_calc: true },
    { date: "2026-10-08", qty: null, status: "NO_DATA", in_calc: false },
    { date: "2026-10-09", qty: 7, status: "ORDERS", in_calc: true },
    { date: "2026-10-10", qty: 9, status: "ORDERS", in_calc: true },
    { date: "2026-10-11", qty: 3, status: "ORDERS", in_calc: true },
    { date: "2026-10-12", qty: 20, status: "ORDERS", in_calc: true },
    { date: "2026-10-13", qty: 16, status: "ORDERS", in_calc: true },
  ];   // 8 known days, total 72 -> 9 per day
  const ex = {
    identity: { run_id: "FCR-1", model_version: "MV-1", data_source: "DEMO", scope_key: "DEMO-1", target_date: "2026-10-14", horizon_day: 1,
      data_as_of: "2026-10-13", run_created_at: "2026-10-14T08:06:21Z" },
    result: { method: "FALLBACK_NEW_SERIES", yhat: 9 },
    selection: { source: "STORED", reason_code: "NEW_SERIES", series_start_date: "2026-10-05", age_days: 9, zero_share: 0.125, zero_days: 1,
      zero_known_days: 8, recent_sum: 72, fallback_window: { days: 28 }, rule: { min_series_history_days: 28, zero_share_window_days: 56,
        intermittent_zero_share: 0.8, inactive_days: 60 } },
    history: { status: "OK", window_start: "2026-10-04", window_end: "2026-10-13", window_days: 10, days,
      summary: { ORDERS: 7, ZERO_ORDERS: 1, NO_DATA: 1, BEFORE_START: 1, total_qty: 72 },
      calc: { from: "2026-10-05", to: "2026-10-13", known_days: 8, sum: 72 } },
    fallback: { kind: "FALLBACK_NEW_SERIES", known_days: 8, sum: 72, rate: 9, value_rounded: 9, matches_published: true, matches_history: true },
    quality: {}, notes: [],
  };
  it("72 ÷ 8 = 9 without trailing zeros; each demand sits next to its own date, oldest first; rows add up to the formula", async () => {
    globalThis.fetch = vi.fn(async (url: any) => new Response(JSON.stringify(String(url).startsWith("/api/methods") ? REGISTRY : ex),
      { status: 200, headers: { "content-type": "application/json" } })) as any;
    await act(async () => { render(wrap(<ExplainPanel runId="FCR-1" sku="A" fc="F" date="2026-10-14" maxHorizon={7} origin="2026-10-14" onClose={() => {}} />)); });
    await waitFor(() => expect(screen.getByTestId("history-table")).toBeTruthy());
    const modal = document.querySelector(".modal.wide")!.textContent ?? "";
    expect(modal).toContain("72 ÷ 8 = 9");
    expect(screen.getByTestId("rounding").textContent).toContain("max(0; 9)");
    expect(modal).not.toMatch(/\d,\d*0(?!\d)/);                    // no "9,0", "7,20", "72,00"
    expect(modal).not.toMatch(/\d{4}-\d{2}-\d{2}/);                 // no ISO dates in the panel
    const rows = [...document.querySelectorAll("[data-testid=history-table] tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent));
    expect(rows.map((r) => r[0])).toEqual(days.map((d) => fmtDate(d.date)));                           // chronological, DD/MM/YYYY
    expect(rows.map((r) => r[1])).toEqual(["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật", "Thứ Hai", "Thứ Ba"]);   // 04/10/2026 = Sunday
    expect(rows.map((r) => r[2])).toEqual(days.map((d) => (d.qty == null ? "—" : String(d.qty))));     // paired demand
    expect(rows[2][2]).toBe("0");                                    // a real zero ...
    expect(rows[4][2]).toBe("—");                                    // ... is not "no data"
    const used = rows.filter((r) => r[4] === "✓");
    expect(used.length).toBe(8);
    expect(used.reduce((a, r) => a + Number(r[2]), 0)).toBe(72);
    expect(screen.getByTestId("hist-calc").textContent).toContain("05/10/2026 → 13/10/2026");
    expect(screen.getByTestId("hist-calc").textContent).toContain("khớp");
  });
});
