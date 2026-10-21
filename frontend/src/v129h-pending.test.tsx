import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { DupCounts } from "./pages/BigQuery";

// Master audit (21/10/2026), owner rule: WAIT_TO_CONFIRM orders have no so_code yet; such rows are never exact
// duplicates. The duplicate panel shows them apart (rows kept, of which identical in every compared column) with the
// rule, only when there are some; the duplicate counts themselves are unchanged.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });

const BASE = { rows_checked: 8961545, duplicate_groups: 0, duplicate_rows: 0, extra_duplicate_rows: 0,
  columns: [{ field: "order_id", alias: "order_id", column: "so_code" }], not_compared: ["customer_id"] };

describe("1.2.9h pending orders without order code", () => {
  it("shows the pending rows, the identical ones and the rule", () => {
    render(wrap(<DupCounts d={{ ...BASE, pending_no_order_code: { applies: true, statuses: ["WAIT_TO_CONFIRM"], rows: 307,
      qty: 6505, identical_groups: 18, identical_rows: 67 } }} />));
    const row = screen.getByTestId("bq-dup-pending").textContent!;
    expect(row).toContain("307");
    expect(row).toContain("67");
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("WAIT_TO_CONFIRM");
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("không tính là trùng");
  });

  it("fix 7.1: pending rows identical in every source column are shown as blocking duplicates", () => {
    render(wrap(<DupCounts d={{ ...BASE, duplicate_groups: 1, duplicate_rows: 2, extra_duplicate_rows: 1,
      pending_no_order_code: { applies: true, rows: 5, identical_groups: 1, identical_rows: 3, duplicate_groups: 1,
        duplicate_rows: 2 } }} />));
    expect(screen.getByTestId("bq-dup-pending-whole").textContent).toContain("mọi cột nguồn");
    expect(screen.getByTestId("bq-dup-pending-whole").textContent).toContain("2");
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("toàn bộ dòng nguồn");
  });

  it("shows nothing extra when there is no pending row or the result predates the rule", () => {
    const { rerender } = render(wrap(<DupCounts d={{ ...BASE, pending_no_order_code: { applies: true, rows: 0,
      identical_groups: 0, identical_rows: 0 } }} />));
    expect(screen.queryByTestId("bq-dup-pending")).toBeNull();
    expect(screen.queryByTestId("bq-dup-pending-whole")).toBeNull();
    rerender(wrap(<DupCounts d={BASE} />));
    expect(screen.queryByTestId("bq-dup-pending")).toBeNull();
    expect(screen.getByTestId("bq-dup-check").textContent).not.toContain("WAIT_TO_CONFIRM");
  });
});
