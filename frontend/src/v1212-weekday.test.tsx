import { fireEvent, render } from "@testing-library/react";
import { I18nProvider } from "./i18n";
import { LineChart, fmtDateWd, isoWeekday, weekdayLabel, weekdayName } from "./components/ui";

// 1.2.12 (owner requirement, weekday feature): ONE Vietnamese form "Thứ 2" ... "Chủ nhật" wherever a forecast date is
// shown, computed from the forecast (target) date itself - Monday = 1 ... Sunday = 7 like the model input (backend
// app/weekday.py). The explanation panel used "Thứ Hai" ... "Chủ Nhật"; the trend chart tooltip and the history page
// showed the date only.
beforeEach(() => { localStorage.clear(); });

const WEEK = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"];
const VI = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"];

describe("1.2.12 weekday names of forecast dates", () => {
  it("all seven weekdays, Monday = 1 ... Sunday = 7, in the one Vietnamese form", () => {
    expect(WEEK.map(isoWeekday)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(WEEK.map((d) => weekdayName(d, "vi"))).toEqual(VI);
    expect(WEEK.map((d) => weekdayLabel(isoWeekday(d), "vi"))).toEqual(VI);   // the two helpers can never disagree
    expect(weekdayName("2026-10-25", "en")).toBe("Sunday");
  });

  it("date boundaries: month / year end, leap day, a timestamp keeps its own date part, impossible dates get no name", () => {
    expect(weekdayName("2026-10-31", "vi")).toBe("Thứ 7");
    expect(weekdayName("2026-11-01", "vi")).toBe("Chủ nhật");
    expect(weekdayName("2026-12-31", "vi")).toBe("Thứ 5");
    expect(weekdayName("2027-01-01", "vi")).toBe("Thứ 6");
    expect(weekdayName("2028-02-29", "vi")).toBe("Thứ 3");
    expect(weekdayName("2026-10-25T23:30:00+07:00", "vi")).toBe("Chủ nhật");
    expect(weekdayName("2026-02-30", "vi")).toBe("—");
    expect(weekdayName("", "vi")).toBe("—");
  });

  it("fmtDateWd shows the date with its weekday, and nothing invented for a missing date", () => {
    expect(fmtDateWd("2026-10-20", "vi")).toBe("20/10/2026 (Thứ 3)");
    expect(fmtDateWd("2026-10-25", "vi")).toBe("25/10/2026 (Chủ nhật)");
    expect(fmtDateWd("2026-10-20", "en")).toBe("20/10/2026 (Tuesday)");
    expect(fmtDateWd(null, "vi")).toBe("—");
  });

  it("the forecast trend chart tooltip names the weekday of the hovered forecast date", () => {
    const points = WEEK.map((x, i) => ({ x, y: i + 1 }));
    const { container } = render(<I18nProvider><LineChart points={points} label="trend" /></I18nProvider>);
    const zones = [...container.querySelectorAll("svg rect[fill=transparent]")];
    expect(zones.length).toBe(7);
    fireEvent.mouseEnter(zones[6]);
    expect(container.querySelector("svg")!.textContent).toContain("25/10/2026 (Chủ nhật): 7");
    fireEvent.mouseEnter(zones[0]);
    expect(container.querySelector("svg")!.textContent).toContain("19/10/2026 (Thứ 2): 1");
  });
});
