import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DICT, I18nProvider, useI18n } from "./i18n";
import { GLOSSARY } from "./glossary";
import { ApiError } from "./api";
import { ErrorBox, Pill, SourceBadge } from "./components/ui";
import App from "./App";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f: string) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : /\.tsx?$/.test(f) && !f.includes(".test.") ? [p] : [];
  });
}

beforeEach(() => localStorage.clear());

describe("i18n", () => {
  it("every dictionary entry has both Vietnamese and English text", () => {
    for (const [k, [vi, en]] of Object.entries(DICT)) {
      expect(vi.trim(), k).not.toBe("");
      expect(en.trim(), k).not.toBe("");
    }
  });

  it("every literal t('key') used in the source exists in the dictionary", () => {
    const missing: string[] = [];
    for (const file of walk(join(__dirname))) {
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(/\bt\("([a-z0-9_.]+)"\)/gi)) if (!DICT[m[1]]) missing.push(`${file}: ${m[1]}`);
    }
    expect(missing).toEqual([]);
  });

  it("glossary covers the required terms in both languages", () => {
    const ids = GLOSSARY.map((g) => g.id);
    for (const id of ["wape", "mae", "bias", "mape", "backtesting", "model_version", "snapshot", "freshness", "leakage", "retry", "idempotency", "origin", "features"]) {
      expect(ids).toContain(id);
    }
    for (const g of GLOSSARY) {
      for (const l of ["vi", "en"] as const) {
        for (const f of ["name", "meaning", "purpose", "example"] as const) expect(g[l][f].trim().length, `${g.id}.${l}.${f}`).toBeGreaterThan(2);
      }
    }
  });

  it("language toggle switches visible text", () => {
    function Probe() {
      const { t, lang, setLang } = useI18n();
      return <button onClick={() => setLang(lang === "vi" ? "en" : "vi")}>{t("nav.dashboard")}</button>;
    }
    render(<I18nProvider><Probe /></I18nProvider>);
    expect(screen.getByRole("button").textContent).toBe("Tổng quan");
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button").textContent).toBe("Dashboard");
  });
});

describe("components", () => {
  it("shows the backend's bilingual error message and code", () => {
    const err = new ApiError(415, { code: "NOT_XLSX", vi: "Chỉ chấp nhận .xlsx", en: "Only .xlsx" });
    render(<I18nProvider><ErrorBox error={err} /></I18nProvider>);
    expect(screen.getByRole("alert").textContent).toContain("Chỉ chấp nhận .xlsx");
    expect(screen.getByRole("alert").textContent).toContain("NOT_XLSX");
  });

  it("labels data sources and statuses", () => {
    render(<I18nProvider><SourceBadge source="DEMO" /><Pill status="REJECTED" /></I18nProvider>);
    expect(screen.getByText("DEMO")).toBeTruthy();
    expect(screen.getByText("Không đạt chất lượng")).toBeTruthy();
  });
});

describe("app shell", () => {
  const status = {
    version: "1.0.0", active_source: "DEMO", data_dir: "C:\\x", db_version: 1, scope: { scope_key: "DEMO-1", data_source: "DEMO", label: "DEMO (DEMO-1)" },
    scope_error: null, freshness: { max_date: "2026-10-13", lag_days: 1, stale: false }, latest_forecast_run: null, latest_accepted_training: null,
    latest_training_attempt: null, latest_jobs: { D1_SYNC: null, D0_SYNC: null, TRAIN_PUBLISH: null }, alerts: [], scheduler: { running: true },
    bigquery_production_enabled: false,
  };
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (url: any) => {
      const u = String(url);
      const body = u.startsWith("/api/system/status") ? status
        : u.startsWith("/api/dashboard") ? { system: status, forecast: null }
        : u.startsWith("/api/settings") ? { horizons: { enabled: [7, 15, 30] } }
        : u.startsWith("/api/messages") ? {} : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as any;
  });

  it("marks DEMO data clearly and never as production; BigQuery option disabled until activated", async () => {
    await act(async () => {
      render(<I18nProvider><MemoryRouter><App /></MemoryRouter></I18nProvider>);
    });
    await waitFor(() => expect(screen.getAllByText(/DỮ LIỆU DEMO/).length).toBeGreaterThan(0));
    const opt = screen.getByRole("option", { name: /BIGQUERY/ }) as HTMLOptionElement;
    expect(opt.disabled).toBe(true);
    await waitFor(() => expect(screen.getByText(/Chưa có forecast nào được publish/)).toBeTruthy());
  });
});

describe("error handling v1.1", () => {
  it("database errors hide internals and point at the diagnostic report", () => {
    const err = new ApiError(409, { code: "DATABASE_CONSTRAINT", category: "DATABASE", vi: "Thao tác bị cơ sở dữ liệu từ chối", en: "refused", detail: "FOREIGN KEY constraint failed", request_id: "abc123" });
    render(<I18nProvider><MemoryRouter><ErrorBox error={err} /></MemoryRouter></I18nProvider>);
    const txt = screen.getByRole("alert").textContent ?? "";
    expect(txt).toContain("Cơ sở dữ liệu");
    expect(txt).toContain("abc123");
    expect(txt).not.toContain("FOREIGN KEY");
  });

  it("NO_ACTIVE_DATASET shows guidance with a Generate DEMO button", async () => {
    const status = {
      version: "1.1.0", active_source: "DEMO", scope: null, bigquery_production_enabled: false, alerts: [], latest_jobs: {},
      scope_error: { code: "NO_ACTIVE_DATASET", category: "CONFIG", vi: "Chưa có bộ dữ liệu cho nguồn đang chọn.", en: "No dataset" },
      scheduler: { running: true },
    };
    globalThis.fetch = vi.fn(async (url: any) => {
      const u = String(url);
      const body = u.startsWith("/api/system/status") ? status : u.startsWith("/api/dashboard") ? { system: status, forecast: null }
        : u.startsWith("/api/settings") ? { horizons: { enabled: [7] } } : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as any;
    await act(async () => {
      render(<I18nProvider><MemoryRouter><App /></MemoryRouter></I18nProvider>);
    });
    await waitFor(() => expect(screen.getByText("Chưa có dữ liệu.")).toBeTruthy());
    expect(screen.getAllByRole("button", { name: "Tạo dữ liệu Demo" }).length).toBeGreaterThan(0);
  });
});
