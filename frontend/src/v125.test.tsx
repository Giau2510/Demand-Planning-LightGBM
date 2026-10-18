import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DICT, I18nProvider } from "./i18n";
import App from "./App";
import Results from "./pages/Results";
import { Confirm, LineChart, Pill, YesNo } from "./components/ui";

// 1.2.5 design system: one shell, one page header, one icon set, one colour scale for every page. These tests check
// the rules of the redesign; the business behaviour of each page keeps its own tests (v111 - v124).
const wrap = (el: React.ReactNode, at = "/") => <I18nProvider><MemoryRouter initialEntries={[at]}>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); document.getElementById("df-remote-banner")?.remove(); });

const STATUS = {
  version: "1.2.5", active_source: "BIGQUERY", data_dir: "C:\\x", db_version: 3, bigquery_production_enabled: true,
  scope: { scope_key: "BIGQUERY:p.d.t", data_source: "BIGQUERY", label: "BIGQUERY (p.d.t)" }, scope_error: null,
  freshness: { max_date: "2026-10-16", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
  latest_training_attempt: null, latest_jobs: {}, alerts: [], scheduler: { running: true },
};

/** Only the system status answers; every other endpoint fails, so each page shows its error / empty state. */
function failingBackend() {
  globalThis.fetch = vi.fn(async (url: any) => {
    const u = String(url);
    if (u.startsWith("/api/system/status")) return new Response(JSON.stringify(STATUS), { status: 200, headers: { "content-type": "application/json" } });
    return new Response(JSON.stringify({ code: "TEST_UNAVAILABLE", vi: "Không có dữ liệu thử", en: "No test data" }),
      { status: 503, headers: { "content-type": "application/json" } });
  }) as any;
}

const ROUTES: [string, string][] = [["/", "nav.dashboard"], ["/results", "nav.results"], ["/forecast-history", "nav.fhistory"], ["/performance", "nav.performance"],
  ["/snapshots", "nav.snapshots"], ["/methodology", "nav.methodology"], ["/import", "nav.import"], ["/batches", "nav.batches"],
  ["/quality", "nav.quality"], ["/config", "nav.config"], ["/bigquery", "nav.bigquery"], ["/mapping", "nav.mapping"], ["/sql", "nav.sql"],
  ["/features", "nav.features"], ["/schedules", "nav.schedules"], ["/jobs", "nav.jobs"], ["/system", "nav.system"]];

describe("v1.2.5 shell and page frame", () => {
  it("every route renders in the shell with its page header, page icon and the matching active sidebar item", async () => {
    for (const [path, key] of ROUTES) {
      failingBackend();
      const r = await act(async () => render(wrap(<App />, path)));
      const title = DICT[key][0];
      // (a title that is also a glossary term carries the term's "?" marker after it)
      await waitFor(() => expect(r.container.querySelector(".page-h h2")?.textContent?.replace(/\?$/, "")).toBe(title));
      expect(r.container.querySelector(".page-h .page-ic svg")).toBeTruthy();
      const active = r.container.querySelector(".side a[aria-current=page]");
      expect(active?.textContent, path).toBe(title);
      expect(active?.querySelector("svg"), path).toBeTruthy();
      // icon-only controls keep a name; icons themselves are decorative
      for (const b of r.container.querySelectorAll("button")) {
        const name = (b.getAttribute("aria-label") ?? "").trim() || (b.textContent ?? "").trim();
        expect(name, `${path}: ${b.outerHTML.slice(0, 120)}`).not.toBe("");
      }
      for (const svg of r.container.querySelectorAll("svg.ic")) expect(svg.getAttribute("aria-hidden")).toBe("true");
      r.unmount();
    }
  }, 30000);

  it("the sidebar collapses to icons (names kept for screen readers and as tooltips) and remembers it per browser", async () => {
    failingBackend();
    const r = await act(async () => render(wrap(<App />)));
    const shell = r.container.querySelector(".shell")!;
    fireEvent.click(screen.getByRole("button", { name: "Thu gọn thanh điều hướng" }));
    expect(shell.classList.contains("collapsed")).toBe(true);
    expect(localStorage.getItem("df.nav.collapsed")).toBe("1");
    const link = r.container.querySelector(".side a[href='/results']")!;
    expect(link.textContent).toBe("Kết quả dự báo");
    expect(link.getAttribute("title")).toBe("Kết quả dự báo");
    r.unmount();
    const again = await act(async () => render(wrap(<App />)));
    expect(again.container.querySelector(".shell")!.classList.contains("collapsed")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Mở rộng thanh điều hướng" }));
    expect(again.container.querySelector(".shell")!.classList.contains("collapsed")).toBe(false);
  });

  it("works when browser storage is unavailable (private window): defaults to expanded, toggling never throws", async () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    try {
      failingBackend();
      const r = await act(async () => render(wrap(<App />)));
      expect(r.container.querySelector(".shell")!.classList.contains("collapsed")).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "Thu gọn thanh điều hướng" }));
      expect(r.container.querySelector(".shell")!.classList.contains("collapsed")).toBe(true);
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });

  it("small screens: the menu button opens the navigation drawer; Escape and navigating close it", async () => {
    failingBackend();
    const r = await act(async () => render(wrap(<App />)));
    const shell = r.container.querySelector(".shell")!;
    fireEvent.click(screen.getByRole("button", { name: "Menu điều hướng" }));
    expect(shell.classList.contains("nav-open")).toBe(true);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(shell.classList.contains("nav-open")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Menu điều hướng" }));
    await act(async () => { fireEvent.click(r.container.querySelector(".side a[href='/jobs']")!); });
    expect(shell.classList.contains("nav-open")).toBe(false);
    expect(r.container.querySelector(".page-h h2")?.textContent).toBe("Job & Scheduler");
  });
});

describe("v1.2.5 status, colour and icon rules", () => {
  it("a status badge always carries its text; the tone and the icon only add to it", () => {
    render(wrap(<><Pill status="FAILED" /><Pill status="RUNNING" /><Pill status="USABLE_WITH_WARNING" /><YesNo v={true} /><YesNo v={false} /></>));
    const pills = [...document.querySelectorAll(".pill")];
    expect(pills.map((p) => p.textContent)).toEqual(["Thất bại", "Đang chạy", "Được dùng — kèm cảnh báo"]);
    expect(pills[0].classList.contains("bad")).toBe(true);
    expect(pills[1].classList.contains("st-RUNNING")).toBe(true);
    expect(pills[2].classList.contains("warn")).toBe(true);           // usable with a warning is amber, never red
    expect([...document.querySelectorAll(".yn")].map((e) => e.textContent)).toEqual(["Có", "Không"]);
  });

  it("text / background token pairs of the stylesheet meet WCAG AA contrast (4.5:1)", () => {
    const css = readFileSync(join(__dirname, "styles.css"), "utf8");
    const root = css.slice(css.indexOf(":root {"), css.indexOf("\n}", css.indexOf(":root {")));
    const tok: Record<string, string> = {};
    for (const m of root.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)) tok[m[1]] = m[2];
    const lum = (hex: string) => {
      const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const v = (k: string) => (k.startsWith("#") ? k : tok[k]);
    const pairs: [string, string][] = [["text", "bg"], ["text", "panel"], ["muted", "panel"], ["muted", "panel-2"], ["muted", "bg"],
      ["ok-text", "ok-bg"], ["warn-text", "warn-bg"], ["bad-text", "bad-bg"], ["info-text", "info-bg"], ["demo", "demo-bg"],
      ["ok", "panel"], ["warn", "panel"], ["bad", "panel"], ["brand", "panel"], ["actual-text", "panel"], ["#ffffff", "brand"],
      ["#ffffff", "bad"], ["side-text", "side-bg"], ["side-muted", "side-bg"], ["brand", "brand-2"], ["ok-text", "panel"]];
    for (const [fg, bg] of pairs) {
      expect(v(fg), fg).toBeTruthy();
      expect(v(bg), bg).toBeTruthy();
      expect(ratio(v(fg), v(bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("no emoji or bare tick / cross glyph is used as a functional icon in the UI source", () => {
    const walk = (dir: string): string[] => readdirSync(dir).flatMap((f) => {
      const p = join(dir, f);
      return statSync(p).isDirectory() ? walk(p) : /\.tsx?$/.test(f) && !f.includes(".test.") ? [p] : [];
    });
    const bad: string[] = [];
    for (const f of walk(__dirname)) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/[\u{1F300}-\u{1FAFF}]|[✕✔✘]/gu)) bad.push(`${f}: ${m[0]}`);
    }
    expect(bad).toEqual([]);
  });

  it("a destructive confirmation shows a warning icon, is labelled by its title and closes with Escape", () => {
    const cancel = vi.fn();
    render(wrap(<Confirm open danger title="Xóa lô" onCancel={cancel} onConfirm={() => {}}><p>x</p></Confirm>));
    const dlg = screen.getByRole("dialog");
    expect(dlg.getAttribute("aria-labelledby")).toBe("confirm-title");
    expect(document.getElementById("confirm-title")!.querySelector("svg")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});

describe("v1.2.5 chart readability", () => {
  const days = Array.from({ length: 30 }, (_, i) => ({ x: `2026-10-${String(i + 1).padStart(2, "0")}`, y: 1000 + i * 10 }));
  it("the last date is always labelled and anchored inside the plot; labels never overlap", () => {
    const { container } = render(wrap(<LineChart points={days} />));
    const labels = [...container.querySelectorAll("text.axis")].filter((e) => (e.textContent ?? "").includes("/"));
    expect(labels[0].textContent).toBe("01/10/2026");
    expect(labels[0].getAttribute("text-anchor")).toBe("start");
    const last = labels[labels.length - 1];
    expect(last.textContent).toBe("30/10/2026");
    expect(last.getAttribute("text-anchor")).toBe("end");
    const xs = labels.map((e) => Number(e.getAttribute("x")));
    for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(84);
  });
  it("hovering a day shows a tooltip box with the date and the formatted value", () => {
    const { container } = render(wrap(<LineChart points={days.slice(0, 3)} />));
    fireEvent.mouseEnter(container.querySelectorAll("rect[fill=transparent]")[1]);
    expect(container.querySelector("rect.tipbox")).toBeTruthy();
    expect(container.querySelector("text.tip")!.textContent).toBe("02/10/2026: 1.010");
  });
});

describe("v1.2.5 filters on the results page", () => {
  const RUN = { id: "FCR-BQ", created_at: "2026-10-17T12:34:19Z", data_source: "BIGQUERY", scope_key: "BIGQUERY:p.d.t", model_version: "MV-X",
    horizons: [7], max_horizon: 7, forecast_origin: "2026-10-17", data_as_of: "2026-10-16", active_scope: true, skus: [], fcs: ["BD", "HN"],
    horizon_coverage: { run_horizons: [7], max_horizon: 7, configured: [7], configured_missing_in_run: [], can_extend_without_retraining: false, cannot_extend_reason: null } };
  const SERIES = [{ sku_id: "MEDX.A-001", fc_id: "HN", total: 12, method: "LIGHTGBM", product_name: "Một tên sản phẩm rất dài để kiểm tra việc xuống dòng trong bảng", actual_today: null }];
  it("shows how many filters apply, clears them in one click, and long product names sit in the wrapping column", async () => {
    const urls: string[] = [];
    globalThis.fetch = vi.fn(async (url: any) => {
      const u = String(url);
      urls.push(u);
      const body = u.startsWith("/api/forecast-runs?") ? [RUN] : u.includes("/summary") ? { n_series: 1, grand_total: 12, start_date: "2026-10-17",
        end_date: "2026-10-23", series: SERIES, daily: [], actual: null } : u.includes("/accuracy") ? null : u.startsWith("/api/forecast-runs/FCR-BQ") ? RUN : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as any;
    await act(async () => { render(wrap(<Results />)); });
    await waitFor(() => expect(screen.getByTestId("product-name")).toBeTruthy());
    expect(screen.getByTestId("product-name").closest("td")!.classList.contains("pname")).toBe(true);
    expect(screen.getByTestId("filter-state").textContent).toContain("chưa áp dụng bộ lọc nào");
    expect(screen.queryByTestId("filter-clear")).toBeNull();
    fireEvent.change(screen.getByTestId("fc-search"), { target: { value: "gan" } });
    fireEvent.change(screen.getByLabelText("FC/kho"), { target: { value: "HN" } });
    expect(screen.getByTestId("filter-state").querySelector(".badge")!.textContent).toBe("2");
    await waitFor(() => expect(urls.some((u) => u.includes("/summary") && u.includes("q=gan") && u.includes("fc_id=HN"))).toBe(true), { timeout: 2000 });
    const before = urls.length;
    await act(async () => { fireEvent.click(screen.getByTestId("filter-clear")); });
    expect((screen.getByTestId("fc-search") as HTMLInputElement).value).toBe("");
    expect(screen.queryByTestId("filter-clear")).toBeNull();
    await waitFor(() => expect(urls.slice(before).some((u) => u.includes("/summary") && !u.includes("q=") && !u.includes("fc_id="))).toBe(true));
  });
});
