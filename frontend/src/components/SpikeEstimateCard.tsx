import { useState } from "react";
import { post } from "../api";
import { useI18n } from "../i18n";
import { Card, DateInput, Field, fmtBytes, fmtDate, fmtNum, useAction } from "./ui";
import { Icon } from "./icons";
import { DescriptionList, ErrorDetails } from "./guardedShared";

// 1.4.15 (lot 6): card "Ước lượng spike-lines" of the page "Job & Scheduler": the BigQuery DRY RUN of the SO-line read only (bytes
// and the cap). It never reads rows and never writes; the real run stays with the runner / CLI.

interface Estimate {
  business_date: string; scope_key?: string; cache_first_day?: string; read_start: string; read_end: string; initial: boolean; reflag: boolean; status?: string;
  estimated_bytes: number; cap_bytes: number; estimated_gb?: number; rows_estimated?: number | null; description?: { code?: string; vi?: string; en?: string }[]; run_with?: string;
}

export default function SpikeEstimateCard() {
  const { t } = useI18n();
  const act = useAction();
  const [date, setDate] = useState("");
  const [initial, setInitial] = useState(false);
  const [reflag, setReflag] = useState(false);
  const [est, setEst] = useState<Estimate | null>(null);

  const run = async () => {
    const r = await act.run(() => post<Estimate>("/api/spike-lines/estimate", { ...(date ? { date } : {}), initial, reflag: initial ? reflag : false }));
    setEst(r ?? null);
  };
  const over = !!est && est.estimated_bytes > est.cap_bytes;

  return (
    <Card icon="chart" title={t("spk.title")}>
      <div className="stack">
        <p className="small muted" data-testid="spk-intro">{t("spk.intro")}</p>
        <div className="alert info small" data-testid="spk-run-with"><b>{t("spk.real_run")}</b></div>
        <div className="form-grid">
          <Field label={t("spk.date")} help={t("spk.date_help")}><DateInput value={date} onChange={setDate} ariaLabel={t("spk.date")} /></Field>
          <label className="row small"><input type="checkbox" data-testid="spk-initial" checked={initial} onChange={(e) => { setInitial(e.target.checked); if (!e.target.checked) setReflag(false); }} />{t("spk.initial")}</label>
          <label className="row small"><input type="checkbox" data-testid="spk-reflag" checked={reflag} disabled={!initial} onChange={(e) => setReflag(e.target.checked)} />{t("spk.reflag")}</label>
        </div>
        <div className="row wrap"><button className="primary" data-testid="spk-estimate" onClick={run} disabled={act.busy}><Icon name="search" />{t("spk.estimate")}</button></div>
        <ErrorDetails error={act.error} />
        {est && (
          <div className="stack tight" data-testid="spk-result">
            <div className="small" data-testid="spk-range">{t("spk.range").replace("{d}", fmtDate(est.business_date)).replace("{a}", fmtDate(est.read_start)).replace("{b}", fmtDate(est.read_end))}</div>
            <div className="small" data-testid="spk-bytes">{t("spk.bytes").replace("{b}", fmtBytes(est.estimated_bytes)).replace("{n}", fmtNum(est.estimated_bytes)).replace("{cap}", fmtBytes(est.cap_bytes))}</div>
            {over && <div className="alert bad small" data-testid="spk-over">{t("spk.over_cap")}</div>}
            <div className="small muted" data-testid="spk-no-rows">{t("spk.no_rows")}</div>
            {est.run_with && <div className="small" data-testid="spk-cli">{t("spk.run_with")}: <span className="mono">{est.run_with}</span></div>}
            <DescriptionList items={est.description} testid="spk-description" />
          </div>
        )}
      </div>
    </Card>
  );
}
