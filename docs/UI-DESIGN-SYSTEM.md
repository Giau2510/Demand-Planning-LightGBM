# UI design system (1.2.5)

One visual system for every page of the web UI (`frontend/`). The rules below are enforced by
`frontend/src/v125.test.tsx` where a test can check them; the rest are review rules. Changing a page means reusing these
pieces, not inventing new colours, sizes or icons.

## 1. Tokens (`frontend/src/styles.css`, `:root`)

| Group | Tokens | Rule |
|---|---|---|
| Neutrals | `--bg`, `--panel`, `--panel-2`, `--panel-3`, `--text`, `--text-strong`, `--muted`, `--subtle`, `--line`, `--line-strong` | Light neutral page, white cards. `--subtle` is decorative only (icons, placeholders), never for text that must be read. |
| Primary / forecast | `--brand`, `--brand-hover`, `--brand-2`, `--brand-line`, `--forecast` | Blue = the main action of a screen and the FORECAST series of every chart. |
| Actual | `--actual`, `--actual-text`, `--actual-bg` | Orange = the ACTUAL series / point of every chart. Never used for a warning. |
| States | `--ok*`, `--warn*`, `--bad*`, `--info*` (each: text, `-text`, `-bg`, `-line`) | Green success, amber warning / provisional / needs confirmation, red error / failure / destructive, blue information. |
| DEMO | `--demo`, `--demo-bg`, `--demo-line` | Purple, only for DEMO data. |
| Type | `--fs-xs` 11 · `--fs-sm` 12 · `--fs-base` 14 · `--fs-md` 15 · `--fs-lg` 18 · `--fs-xl` 22 px | Page title 22, card title 15, body 14, secondary 12. |
| Spacing | `--sp-1`..`--sp-6` (4 px grid) | Gaps between blocks 16, inside cards 12. |
| Radius / shadow | `--r-sm` 6, `--r-md` 8, `--r-lg` 12, `--shadow-1`, `--shadow-pop` | Cards 12, inputs and buttons 8; only pop-ups get a real shadow. |
| Icons | `--ic-xs` 12 · `--ic-sm` 14 · `--ic-md` 16 · `--ic-lg` 20 | Badges 12, small buttons 14, default 16, page headers 20. |

Contrast: every text token on its background is at least 4.5:1 (WCAG AA); the test computes the ratios from the
stylesheet. No gradients, no decorative animation; the only motion is the loading spinner and it stops under
`prefers-reduced-motion`.

## 2. Icons

* Library: **lucide-react 1.48.0** (ISC licence, pinned in `frontend/package.json`; bundled into the UI at build time,
  no network access at run time). No other icon set, no emoji as a functional icon (tested).
* Pages use the semantic names of `frontend/src/components/icons.tsx` (`<Icon name="export" />`), never lucide directly,
  so one meaning has one picture: e.g. `results` trending-up, `history` history, `schedules` calendar-clock, `jobs`
  list-checks, `bigquery` database, `sku` package, `fc` warehouse, `export` file-spreadsheet, `search`, `filter`,
  `refresh`, `ok` circle-check, `warn` triangle-alert, `bad` circle-x, `explain` chart-no-axes-combined, `prod`
  shield-alert; 1.2.5 history: `fhistory` git-compare-arrows (page), `actual` chart-column-big, `deviation` arrow-up-down,
  `percent` percent.
* Icons are decorative (`aria-hidden`). An icon always sits next to a text, or its button has an `aria-label` and the
  same text as tooltip (`IconButton`). A status is never shown by colour or icon alone.
* Status badges, alerts and banners draw their icon with a CSS mask of the same lucide artwork (`--ic-ok`, `--ic-warn`,
  ...), so every existing `.pill` / `.alert` gets it without markup changes.

## 3. Components (`frontend/src/components/ui.tsx`)

| Component | Use |
|---|---|
| `PageHeader` | Every page: icon, title (= sidebar label), one-line purpose, page actions. Kept while the page loads or fails. |
| `Card` (`icon`, `title`, `actions`) | Every content block. |
| `Stat` (`icon`, `tone`) | KPI card. `tone` adds a coloured edge and colours the value; the value text still says what it means. |
| `Pill` | Status badge: text + tone + icon. Usable-with-warning is amber, never red. |
| `YesNo` | Yes / no as icon + word (replaces bare ticks and crosses). |
| `SourceBadge` | DEMO / MANUAL_IMPORT / BIGQUERY with its icon. |
| `FilterBar` | Labelled filters, number of filters in effect, one "clear filters" action. |
| `SearchInput` | Search icon, clear button (and Escape) - only shown when there is something to clear. |
| `Pager` | Previous / next with "page x / y · n rows". |
| `IconButton` | Icon-only button with accessible name + tooltip. |
| `Empty` (`hint`, `action`) | What is missing and, when known, why / what to do next. |
| `Loading`, `ErrorBox`, `OkBox` | Loading spinner; backend error with code; success only after the backend confirmed it. |
| `Confirm` | Dialog labelled by its title, Escape cancels, warning icon on destructive confirmations. |
| `LineChart` | Forecast line (blue) + today's actual point (orange); drawn in real pixels, dates never overlap, last date always labelled, tooltip box. Never interpolates missing data. |
| `CompareChart` | Stored forecast (blue line + dots) against actual (orange squares) per date; a missing value is a gap (segments join only consecutive known values); provisional actual = hollow square on a dashed segment, complete = filled square; tooltip lines given by the page. |
| `Term`, `MethodLabel` | Plain-language tooltip for a technical term (hover, focus, tap). Tooltips add information, never replace a label. |

Buttons: default (secondary), `primary` (main action), `danger` (destructive: delete / replace), `ghost`, `link`,
`small`, `icon-btn`. **Production-affecting actions** (switch a schedule, run a job now, use a model, activate /
deactivate BigQuery production, backfill, save a mapping while production is on) add the class `prod` and the
`prod` shield icon with the tooltip "affects production"; their confirmation dialogs are unchanged.

## 4. Layout and navigation

* Sidebar: three groups, icon + label per page, the current page highlighted (background, accent bar, bold) and marked
  `aria-current="page"`. Desktop: can collapse to icons (labels stay for screen readers and as tooltips); the choice is
  a per-browser convenience in `localStorage` (`df.nav.collapsed`), the default is expanded when storage is blocked.
  Below 900 px: drawer opened by the menu button, closed by Escape, the overlay or navigation.
* Top bar (sticky): active source badge, dataset, source switch, language. "Skip to main content" link for keyboards.
* Tables: header row distinct and sticky, light row hover, numbers right-aligned in tabular figures, dates DD/MM/YYYY,
  SKU on one line, product names wrap in their column (`pname`), long tables scroll inside their frame.
* Below 700 px: one column, full-width filters, tables scroll horizontally inside the card, long status badges wrap.
* Wide tables (11 columns of the forecast history, `fh-tbl`): very long SKU codes may break at "-", the status badge wraps
  on two lines with a minimum width, numbers keep a minimum width, so the whole table fits at 1440 px.

## 5. Checks

* `npm test` (`v125.test.tsx`): every route renders inside the shell with its header, icon and active sidebar item;
  every button has a name; icons are hidden from screen readers; contrast of token pairs; no emoji icons; filter count
  and clear; sidebar collapse with and without storage; drawer; dialog; chart labels.
* Visual: headless Edge screenshots of every route before / after on a copy of the real database (see the batch
  report).
