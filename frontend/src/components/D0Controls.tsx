import { useState } from "react";
import { get, post } from "../api";
import { useI18n } from "../i18n";
import { Card, Confirm, ErrorBox, Field, Loading, OkBox, useAction, useAsync } from "./ui";
import { Icon } from "./icons";

// 1.4.15 (lot 6): D-0 maintenance pause on the page "Lịch chạy dữ liệu": GET /api/d0/pause (status), POST /api/d0/pause {hours 1..6},
// POST /api/d0/resume. The API asks for no typed text. The pause ends by itself; D-0 is a side task (monitoring only).

interface D0Status { paused: boolean; until: string | null; until_vn: string | null; by: string; remaining_minutes: number; max_hours: number }

export default function D0Controls() {
  const { t } = useI18n();
  const st = useAsync(() => get<D0Status>("/api/d0/pause"), []);
  const act = useAction();
  const [hours, setHours] = useState("6");
  const [askResume, setAskResume] = useState(false);
  const d = st.data;
  const max = d?.max_hours ?? 6;
  const n = Number(hours);
  const valid = hours.trim() !== "" && Number.isFinite(n) && n >= 1 && n <= max;

  const pause = async () => {
    const r = await act.run(() => post<D0Status>("/api/d0/pause", { hours: n, by: "UI" }), t("d0c.paused_ok"));
    if (r) st.setData(r);
  };
  // a pause that this button did not set (an install chain, another party) is ended only after a confirmation
  const otherOwner = !!d?.paused && !!d.by && d.by !== "UI";
  const resume = async () => {
    setAskResume(false);
    const r = await act.run(() => post<D0Status>("/api/d0/resume", { by: "UI" }), t("d0c.resumed_ok"));
    if (r) st.setData(r);
  };

  return (
    <Card icon="clock" title={t("d0c.title")} actions={<button onClick={() => void st.reload()} disabled={st.loading}><Icon name="refresh" />{t("bg.refresh")}</button>}>
      <div className="stack">
        <p className="small muted" data-testid="d0c-intro">{t("d0c.intro")}</p>
        {st.error ? <ErrorBox error={st.error} /> : !d ? <Loading /> : (
          <>
            <div className={`alert ${d.paused ? "warn" : "info"}`} data-testid="d0c-status">
              {d.paused
                ? <>{t("d0c.paused").replace("{until}", d.until_vn ?? d.until ?? "").replace("{m}", String(d.remaining_minutes))}{d.by ? ` ${t("d0c.by").replace("{by}", d.by)}` : ""}</>
                : t("d0c.running")}
            </div>
            {otherOwner && <div className="alert warn small" data-testid="d0c-other-owner">{t("d0c.other_owner").replace("{by}", d.by)}</div>}
            <div className="row wrap">
              <Field label={t("d0c.hours").replace("{max}", String(max))}>
                <input type="number" min={1} max={max} step={0.5} data-testid="d0c-hours" value={hours} onChange={(e) => setHours(e.target.value)} />
              </Field>
              <button className="primary" data-testid="d0c-pause" onClick={pause} disabled={!valid || act.busy}><Icon name="power" />{t("d0c.pause")}</button>
              <button data-testid="d0c-resume" onClick={() => (otherOwner ? setAskResume(true) : void resume())} disabled={!d.paused || act.busy}><Icon name="run" />{t("d0c.resume")}</button>
            </div>
            {!valid && <div className="small bad-t" data-testid="d0c-hours-bad">{t("d0c.hours_bad").replace("{max}", String(max))}</div>}
            <div className="small muted" data-testid="d0c-auto">{t("d0c.auto").replace("{h}", valid ? String(n) : String(max))}</div>
          </>
        )}
        <ErrorBox error={act.error} />
        <OkBox text={act.ok} />
        <Confirm open={askResume} title={t("d0c.resume")} confirmLabel={t("d0c.resume_confirm")} onCancel={() => setAskResume(false)} onConfirm={() => void resume()}>
          <p className="small" data-testid="d0c-resume-confirm">{t("d0c.other_owner").replace("{by}", d?.by ?? "")}</p>
        </Confirm>
      </div>
    </Card>
  );
}
