import { Navigate } from "react-router-dom";
import { get } from "../api";
import { Loading, useAsync } from "../components/ui";
import { isSel2Run } from "./DailyForecast";
import Results from "./Results";

/** 1.4.14: route /results. With published SEL2 runs (detected as the Results page and the dashboard do: the list of SEL2
 *  runs is not empty) AND the newest refresh run being a SEL2 run (the daily page then opens on it), the page lives in
 *  "Dự báo hằng ngày", tab "Tổng theo SKU × kho": old links and bookmarks land there. Otherwise (DEMO / manual import /
 *  before the first SEL2 run / a newer non-SEL2 run) the legacy Results page is still rendered, so nothing of the non-SEL2
 *  modes is lost (it is no longer in the menu; the dashboard links to it in those modes). */
export default function ResultsRoute() {
  const sel2Runs = useAsync(() => get("/api/daily-forecast/sel2-runs?limit=1").catch(() => []), []);
  const latest = useAsync(() => get("/api/daily-forecast/runs?limit=1").catch(() => null), []);
  if ((sel2Runs.loading && !sel2Runs.data) || (latest.loading && !latest.data)) return <Loading />;
  const sel2 = Array.isArray(sel2Runs.data) && sel2Runs.data.length > 0;
  const newest = Array.isArray(latest.data) && latest.data.length > 0 ? latest.data[0] : null;
  if (sel2 && (newest === null || isSel2Run(newest))) return <Navigate to="/daily-forecast?tab=tong" replace />;
  return <Results />;
}
