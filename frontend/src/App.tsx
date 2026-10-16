import { createContext, useContext, type ReactNode } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { get, post, put } from "./api";
import { useI18n } from "./i18n";
import { ErrorBox, SourceBadge, useAction, useAsync } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Results from "./pages/Results";
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

type StatusCtx = { status: any; reload: () => void };
const SystemContext = createContext<StatusCtx>({ status: null, reload: () => {} });
export const useSystem = () => useContext(SystemContext);

const NAV: { group: string; items: [string, string][] }[] = [
  { group: "nav.group.forecast", items: [["/", "nav.dashboard"], ["/results", "nav.results"], ["/performance", "nav.performance"], ["/snapshots", "nav.snapshots"], ["/methodology", "nav.methodology"]] },
  { group: "nav.group.data", items: [["/import", "nav.import"], ["/batches", "nav.batches"], ["/quality", "nav.quality"]] },
  { group: "nav.group.admin", items: [["/config", "nav.config"], ["/bigquery", "nav.bigquery"], ["/mapping", "nav.mapping"], ["/sql", "nav.sql"], ["/features", "nav.features"], ["/schedules", "nav.schedules"], ["/jobs", "nav.jobs"], ["/system", "nav.system"]] },
];

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
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="brand-t">{t("app.title")}</div>
          <div className="brand-s">{t("app.subtitle")}</div>
        </div>
        <nav>
          {NAV.map((g) => (
            <div key={g.group} className="nav-g">
              <div className="nav-gt">{t(g.group)}</div>
              {g.items.map(([to, key]) => (
                <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "nav-i active" : "nav-i")}>{t(key)}</NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-f small">v{status?.version ?? "…"}</div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="row">
            <SourceBadge source={status?.active_source} />
            <span className="small muted">{status?.scope?.label ?? ""}</span>
          </div>
          <div className="row">
            <SourceSwitcher />
            <button className="lang" onClick={() => setLang(lang === "vi" ? "en" : "vi")} aria-label="language">{t("lang.toggle")}</button>
          </div>
        </div>
        <SourceBanner />
        <div className="content">{children}</div>
      </main>
    </div>
  );
}

export default function App() {
  const st = useAsync(() => get("/api/system/status"), []);
  return (
    <SystemContext.Provider value={{ status: st.data, reload: st.reload }}>
      <Shell>
        {st.error ? <ErrorBox error={st.error} /> : null}
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/results" element={<Results />} />
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
