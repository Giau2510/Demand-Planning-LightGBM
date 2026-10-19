import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { get, post, put } from "./api";
import { useI18n } from "./i18n";
import { ErrorBox, SourceBadge, useAction } from "./components/ui";
import { Icon, type IconName } from "./components/icons";
import Dashboard from "./pages/Dashboard";
import Results from "./pages/Results";
import ForecastHistory from "./pages/ForecastHistory";
import Performance from "./pages/Performance";
import Config from "./pages/Config";
import Methodology from "./pages/Methodology";
import Snapshots from "./pages/Snapshots";
import ImportPage from "./pages/ImportPage";
import Batches from "./pages/Batches";
import DataQuality from "./pages/DataQuality";
import BigQuery from "./pages/BigQuery";
import Mapping from "./pages/Mapping";
import Features from "./pages/Features";
import SqlSources from "./pages/SqlSources";
import Jobs from "./pages/Jobs";
import Schedules from "./pages/Schedules";
import System from "./pages/System";

/** `reload` always asks again (after a change); `refresh` shares a request already running, so a page that opens while
 *  the shell is loading the status does not compute it a second time. */
type StatusCtx = { status: any; error: unknown; loading: boolean; reload: () => Promise<void>; refresh: () => Promise<void> };
const SystemContext = createContext<StatusCtx>({ status: null, error: null, loading: false, reload: async () => {}, refresh: async () => {} });
export const useSystem = () => useContext(SystemContext);

function useSystemStatus(): StatusCtx {
  const [st, setSt] = useState<{ status: any; error: unknown; loading: boolean }>({ status: null, error: null, loading: true });
  const seq = useRef(0);
  const running = useRef<Promise<void> | null>(null);
  const load = useCallback((share: boolean) => {
    if (share && running.current) return running.current;
    const my = ++seq.current;
    setSt((s) => ({ ...s, loading: true, error: null }));
    const p = get("/api/system/status").then(
      (status) => { if (my === seq.current) setSt({ status, error: null, loading: false }); },   // an older answer never wins
      (error) => { if (my === seq.current) setSt((s) => ({ ...s, error, loading: false })); },
    ).finally(() => { if (running.current === p) running.current = null; });
    running.current = p;
    return p;
  }, []);
  const reload = useCallback(() => load(false), [load]);
  const refresh = useCallback(() => load(true), [load]);
  useEffect(() => void refresh(), [refresh]);
  return { ...st, reload, refresh };
}

/** Sidebar: [route, label key, icon]. The page header of each route uses the same icon. */
const NAV: { group: string; items: [string, string, IconName][] }[] = [
  { group: "nav.group.forecast", items: [["/", "nav.dashboard", "dashboard"], ["/results", "nav.results", "results"],
    ["/forecast-history", "nav.fhistory", "fhistory"], ["/performance", "nav.performance", "performance"],
    ["/snapshots", "nav.snapshots", "snapshots"], ["/methodology", "nav.methodology", "methodology"]] },
  { group: "nav.group.data", items: [["/import", "nav.import", "import"], ["/batches", "nav.batches", "batches"], ["/quality", "nav.quality", "quality"]] },
  { group: "nav.group.admin", items: [["/config", "nav.config", "config"], ["/bigquery", "nav.bigquery", "bigquery"], ["/mapping", "nav.mapping", "mapping"],
    ["/sql", "nav.sql", "sql"], ["/features", "nav.features", "features"], ["/schedules", "nav.schedules", "schedules"], ["/jobs", "nav.jobs", "jobs"],
    ["/system", "nav.system", "system"]] },
];

/** Per-viewer convenience only (collapsed sidebar): storage may be unavailable, the default is "expanded". */
function readFlag(key: string): boolean {
  try { return localStorage.getItem(key) === "1"; } catch { return false; }
}
function writeFlag(key: string, on: boolean) {
  try { localStorage.setItem(key, on ? "1" : "0"); } catch { /* storage unavailable */ }
}

function SourceSwitcher() {
  const { t } = useI18n();
  const { status, reload } = useSystem();
  const act = useAction();
  if (!status) return null;
  const change = async (src: string) => {
    await act.run(() => put("/api/active-source", { source: src }));
    reload();
  };
  return (
    <div className="source-switch">
      <label>
        <span className="small">{t("source.active")}</span>
        <select value={status.active_source} onChange={(e) => change(e.target.value)} disabled={act.busy} aria-label={t("source.switch")}>
          {["DEMO", "MANUAL_IMPORT", "BIGQUERY"].map((s) => (
            <option key={s} value={s} disabled={s === "BIGQUERY" && !status.bigquery_production_enabled}>{t(`source.${s}`)}</option>
          ))}
        </select>
      </label>
      {act.error ? <ErrorBox error={act.error} /> : null}
    </div>
  );
}

/** Explains why there is no usable dataset and offers the next safe action (never picks a dataset itself). */
function DatasetGuide({ err, source }: { err: any; source: string }) {
  const { t, pick } = useI18n();
  const { reload } = useSystem();
  const act = useAction();
  const demo = async () => {
    await act.run(() => post("/api/demo/generate", {}));
    reload();
  };
  const inconsistent = err.code === "ACTIVE_DATASET_INCONSISTENT";
  return (
    <div className={inconsistent ? "banner warn" : "banner info"} role="status">
      <b>{inconsistent ? t("ds.inconsistent_title") : t("ds.none_title")}</b> {pick(err)}
      {err.code === "NO_ACTIVE_DATASET" && source === "DEMO" && (
        <button className="primary" onClick={demo} disabled={act.busy} style={{ marginLeft: 8 }}>
          {act.busy ? t("common.running") : t("dash.generate_demo")}
        </button>
      )}
      {(source === "MANUAL_IMPORT" || inconsistent) && (
        <><NavLink to="/import" className="btn" style={{ marginLeft: 8 }}>{t("nav.import")}</NavLink>
          <NavLink to="/batches" className="btn" style={{ marginLeft: 8 }}>{t("nav.batches")}</NavLink></>
      )}
      {act.error ? <ErrorBox error={act.error} /> : null}
    </div>
  );
}

export function SourceBanner() {
  const { t } = useI18n();
  const { status } = useSystem();
  if (!status) return null;
  const src = status.active_source;
  return (
    <>
      {src === "DEMO" && <div className="banner demo">{t("source.demo_banner")}</div>}
      {src === "MANUAL_IMPORT" && <div className="banner import">{t("source.import_banner")}</div>}
      {status.scope_error && <DatasetGuide err={status.scope_error} source={src} />}
    </>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const { status } = useSystem();
  const [collapsed, setCollapsed] = useState(() => readFlag("df.nav.collapsed"));   // desktop: icons only
  const [navOpen, setNavOpen] = useState(false);                                    // small screens: drawer
  const loc = useLocation();
  useEffect(() => setNavOpen(false), [loc.pathname]);
  useEffect(() => {
    if (!navOpen) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setNavOpen(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [navOpen]);
  const toggle = () => { setCollapsed(!collapsed); writeFlag("df.nav.collapsed", !collapsed); };
  return (
    <div className={`shell${collapsed ? " collapsed" : ""}${navOpen ? " nav-open" : ""}`}>
      <a href="#main" className="skip">{t("nav.skip")}</a>
      <aside className="side" id="side-nav" aria-label={t("nav.menu")}>
        <div className="brand">
          <span className="brand-logo" aria-hidden="true"><Icon name="chart" size={18} /></span>
          <div className="brand-text">
            <div className="brand-t">{t("app.title")}</div>
            <div className="brand-s">{t("app.subtitle")}</div>
          </div>
        </div>
        <nav>
          {NAV.map((g) => (
            <div key={g.group} className="nav-g" role="group" aria-label={t(g.group)}>
              <div className="nav-gt" aria-hidden="true">{t(g.group)}</div>
              {g.items.map(([to, key, icon]) => (
                <NavLink key={to} to={to} end={to === "/"} title={collapsed ? t(key) : undefined}
                  className={({ isActive }) => (isActive ? "nav-i active" : "nav-i")}>
                  <Icon name={icon} size={18} /><span className="nav-t">{t(key)}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-f">
          <span className="side-ver">v{status?.version ?? "…"}</span>
          <button className="side-toggle icon-btn small" onClick={toggle} aria-expanded={!collapsed} aria-controls="side-nav"
            aria-label={t(collapsed ? "nav.expand" : "nav.collapse")} title={t(collapsed ? "nav.expand" : "nav.collapse")}>
            <Icon name={collapsed ? "expand" : "collapse"} />
          </button>
        </div>
      </aside>
      <button className="side-overlay" aria-label={t("common.close")} tabIndex={-1} onClick={() => setNavOpen(false)} />
      <main className="main">
        <div className="topbar">
          <div className="row">
            <button className="menu-btn icon-btn" onClick={() => setNavOpen(true)} aria-label={t("nav.menu")} title={t("nav.menu")}
              aria-expanded={navOpen} aria-controls="side-nav"><Icon name="menu" /></button>
            <SourceBadge source={status?.active_source} />
            <span className="small muted scope-label" title={status?.scope?.label ?? ""}>{status?.scope?.label ?? ""}</span>
          </div>
          <div className="row">
            <SourceSwitcher />
            <button className="lang" onClick={() => setLang(lang === "vi" ? "en" : "vi")} title={t("lang.switch")}>
              <Icon name="language" />{t("lang.toggle")}
            </button>
          </div>
        </div>
        <SourceBanner />
        <div className="content" id="main" tabIndex={-1}>{children}</div>
      </main>
    </div>
  );
}

export default function App() {
  const st = useSystemStatus();
  return (
    <SystemContext.Provider value={st}>
      <Shell>
        {st.error ? <ErrorBox error={st.error} /> : null}
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/results" element={<Results />} />
          <Route path="/forecast-history" element={<ForecastHistory />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/config" element={<Config />} />
          <Route path="/methodology" element={<Methodology />} />
          <Route path="/snapshots" element={<Snapshots />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/batches" element={<Batches />} />
          <Route path="/quality" element={<DataQuality />} />
          <Route path="/bigquery" element={<BigQuery />} />
          <Route path="/mapping" element={<Mapping />} />
          <Route path="/features" element={<Features />} />
          <Route path="/sql" element={<SqlSources />} />
          <Route path="/schedules" element={<Schedules />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/system" element={<System />} />
        </Routes>
      </Shell>
    </SystemContext.Provider>
  );
}
