import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "./i18n";
import { DupCounts } from "./pages/BigQuery";

// Owner rule 21/10/2026 (1.2.11, supersedes the master audit / fix 7.1 texts): WAIT_TO_CONFIRM rows (with or without
// so_code) are exempt from the duplicate check. The duplicate panel shows them apart (rows kept, of which identical in
// every compared column, and identical in every source column - informative, not blocking) with the rule, only when
// there are some; the duplicate counts themselves are the non-pending rows only.
const wrap = (el: React.ReactNode) => <I18nProvider><MemoryRouter>{el}</MemoryRouter></I18nProvider>;
beforeEach(() => { localStorage.clear(); });

const BASE = { rows_checked: 8961545, duplicate_groups: 0, duplicate_rows: 0, extra_duplicate_rows: 0,
  columns: [{ field: "order_id", alias: "order_id", column: "so_code" }], not_compared: ["customer_id", "item_code"] };

describe("1.2.11 pending orders exempt from the duplicate check", () => {
  it("shows the pending rows, the identical ones and the exemption", () => {
    render(wrap(<DupCounts d={{ ...BASE, pending_orders: { applies: true, exempt: true, statuses: ["WAIT_TO_CONFIRM"],
      rows: 307, qty: 6505, without_order_code_rows: 300, identical_groups: 18, identical_rows: 67, whole_row_groups: 0,
      whole_row_rows: 0 } }} />));
    const row = screen.getByTestId("bq-dup-pending").textContent!;
    expect(row).toContain("307");
    expect(row).toContain("67");
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("WAIT_TO_CONFIRM");
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("miễn kiểm tra trùng");
    expect(screen.getByTestId("bq-dup-check").textContent).toContain("item_code không phải tiêu chí");
    expect(screen.queryByTestId("bq-dup-pending-whole")).toBeNull();
  });

  it("pending rows identical in every source column are shown, as not blocking", () => {
    render(wrap(<DupCounts d={{ ...BASE, pending_orders: { applies: true, exempt: true, rows: 5, identical_groups: 1,
      identical_rows: 3, whole_row_groups: 1, whole_row_rows: 2 } }} />));
    expect(screen.getByTestId("bq-dup-pending-whole").textContent).toContain("mọi cột nguồn");
    expect(screen.getByTestId("bq-dup-pending-whole").textContent).toContain("không chặn");
    expect(screen.getByTestId("bq-dup-pending-whole").textContent).toContain("2");
  });

  it("shows nothing extra when there is no pending row or the result predates the rule", () => {
    const { rerender } = render(wrap(<DupCounts d={{ ...BASE, pending_orders: { applies: true, rows: 0,
      identical_groups: 0, identical_rows: 0 } }} />));
    expect(screen.queryByTestId("bq-dup-pending")).toBeNull();
    expect(screen.queryByTestId("bq-dup-pending-whole")).toBeNull();
    rerender(wrap(<DupCounts d={BASE} />));
    expect(screen.queryByTestId("bq-dup-pending")).toBeNull();
    expect(screen.getByTestId("bq-dup-check").textContent).not.toContain("WAIT_TO_CONFIRM");
    // a stored 1.2.10 result (old key) is not shown with the new wording
    rerender(wrap(<DupCounts d={{ ...BASE, pending_no_order_code: { applies: true, rows: 9, identical_rows: 3 } } as any} />));
    expect(screen.queryByTestId("bq-dup-pending")).toBeNull();
  });
});
