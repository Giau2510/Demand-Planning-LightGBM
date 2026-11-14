import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import Dashboard from "./pages/Dashboard";
import ForecastExplainer from "./pages/ForecastExplainer";
import Performance from "./pages/Performance";
import Batches from "./pages/Batches";

const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => {
  localStorage.clear();
  globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "content-type": "application/json" } })) as any;
});

const VI = "Đang cập nhật: số liệu kiểu cũ, chưa cập nhật theo SEL2. Số chính thức xem ở trang Dự báo hằng ngày.";
const EN = "Being updated: legacy figures, not yet updated to SEL2. The official numbers are on the Daily forecast page.";

describe("v1.4.11 legacy data banner", () => {
  it.each([["Dashboard", Dashboard], ["ForecastExplainer", ForecastExplainer], ["Performance", Performance]] as const)(
    "%s shows one warning banner with a link to the daily forecast page", async (_n, Page) => {
      render(wrap(<Page />));
      const b = await screen.findByTestId("legacy-banner");
      expect(screen.getAllByTestId("legacy-banner")).toHaveLength(1);
      expect(b.className).toContain("warn");
      expect(b.textContent).toBe(VI);
      const a = screen.getByTestId("legacy-banner-link");
      expect(a.getAttribute("href")).toBe("/daily-forecast");
      expect(a.textContent).toBe("Dự báo hằng ngày");
      expect(b.querySelector("button")).toBeNull();            // not dismissible
    });

  it("English text", async () => {
    localStorage.setItem("df.lang", "en");
    render(wrap(<Performance />));
    expect((await screen.findByTestId("legacy-banner")).textContent).toBe(EN);
  });

  it("other pages have no banner", async () => {
    render(wrap(<Batches />));
    await screen.findAllByRole("heading");
    expect(screen.queryByTestId("legacy-banner")).toBeNull();
  });
});
