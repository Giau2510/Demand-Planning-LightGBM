import { useEffect, useState } from "react";
import { get, post, put, qs, upload } from "../api";
import { useI18n } from "../i18n";
import { Card, Confirm, Empty, ErrorBox, Field, FilterBar, Loading, OkBox, PageHeader, Pager, Pill, SearchInput, Stat, fmtNum,
  fmtTime, useAction, useAsync } from "../components/ui";
import { Icon } from "../components/icons";

const PAGE = 100;
const SOURCES = ["AVG_DEMAND", "LIGHTGBM"];
const SOURCE_PILL: Record<string, string> = { LIGHTGBM: "OK", AVG_DEMAND: "INFO" };

const list = (x: unknown): any[] => (Array.isArray(x) ? x : []);
const other = (src: string) => (src === "LIGHTGBM" ? "AVG_DEMAND" : "LIGHTGBM");
const keyPath = (sku: string, fc: string) => `${encodeURIComponent(sku)}/${encodeURIComponent(fc)}`;

/** A change waiting for the confirmation dialog: the effective source before it and the source / note asked. */
type Pending = { sku_code: string; fc_code: string; from: string; configured: boolean; to: string; ghi_chu: string };

/** 1.4.0 "Nguồn dự báo": the forecast source of each SKU x FC (AVG_DEMAND, the default for a SKU x FC without a row,
 *  or LIGHTGBM), one change at a time or from an Excel file (preview first, apply after), with the change history.
 *  Every write needs the confirmation dialog (confirm=true); the backend refuses them while the SEL2 pipeline is off. */
export default function ForecastSource() {
  const { t } = useI18n();
  const [sku, setSku] = useState("");
  const [fc, setFc] = useState("");
  const [src, setSrc] = useState("");
  const [skuD, setSkuD] = useState("");
  const [fcD, setFcD] = useState("");
  useEffect(() => { const id = setTimeout(() => { setSkuD(sku.trim()); setFcD(fc.trim()); }, 300); return () => clearTimeout(id); }, [sku, fc]);
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [skuD, fcD, src]);
  const cfg = useAsync(() => get(`/api/sel2/source-config${qs({ sku_code: skuD, fc_code: fcD, source: src, limit: PAGE, offset: page * PAGE })}`),
    [skuD, fcD, src, page]);
  const [hPage, setHPage] = useState(0);
  const hist = useAsync(() => get(`/api/sel2/source-config/history${qs({ limit: PAGE, offset: hPage * PAGE })}`), [hPage]);

  // one SKU x FC: look up its effective source, then change it
  const [oneSku, setOneSku] = useState("");
  const [oneFc, setOneFc] = useState("");
  const [eff, setEff] = useState<any>(null);
  const [newSrc, setNewSrc] = useState("LIGHTGBM");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const act = useAction();
  // upload: preview, then apply
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const up = useAction();

  const reloadAll = () => { cfg.reload(); hist.reload(); };
  const lookup = async () => {
    const s = oneSku.trim(), f = oneFc.trim();
    if (!s || !f) return;
    const r = await act.run(() => get(`/api/sel2/source-config/${keyPath(s, f)}`));
    if (r) { setEff(r); setNewSrc(other(r.forecast_source)); setNote(r.ghi_chu ?? ""); }
  };
  const ask = (p: Pending) => { act.setError(null); act.setOk(null); setPending(p); };
  const save = async () => {
    if (!pending) return;
    const r = await act.run(() => put(`/api/sel2/source-config/${keyPath(pending.sku_code, pending.fc_code)}`,
      { forecast_source: pending.to, ghi_chu: pending.ghi_chu.trim() || null, confirm: true }));
    if (r) {
      setPending(null);
      act.setOk(r.changed ? t("fsrc.saved") : t("fsrc.unchanged"));
      if (eff && eff.sku_code === pending.sku_code && eff.fc_code === pending.fc_code) {
        setEff(r.after); setNewSrc(other(r.after.forecast_source)); setNote(r.after.ghi_chu ?? "");
      }
      reloadAll();
    }
  };
  const doPreview = async () => {
    if (!file) return;
    setPreview(null);
    const r = await up.run(() => upload("/api/sel2/source-config/upload", file));
    if (r) setPreview(r);
  };
  const apply = async () => {
    if (!preview) return;
    const r = await up.run(() => post("/api/sel2/source-config/apply", { preview_id: preview.preview_id, confirm: true }));
    if (r) {
      setApplyOpen(false);
      setPreview(null);
      up.setOk(t("fsrc.applied").replace("{n}", fmtNum(r.applied)) + (r.batch_id ? ` · ${r.batch_id}` : ""));
      reloadAll();
    }
  };

  const c = cfg.data;
  const counts = c?.configured_by_source ?? {};
  const nFilters = [sku.trim(), fc.trim(), src].filter(Boolean).length;
  const clear = () => { setSku(""); setFc(""); setSrc(""); setSkuD(""); setFcD(""); };
  const pc = preview?.counts;
  const srcLabel = (s: string | null | undefined) => (s ? t(`fsrc.src.${s}`) : "—");

  return (
    <div className="stack" data-testid="fsrc-page">
      <PageHeader icon="model" title={t("nav.fsource")} desc={t("fsrc.desc")}
        actions={<a className="btn" href="/api/sel2/source-config/download" data-testid="fsrc-download"><Icon name="download" />{t("fsrc.download")}</a>} />
      <ErrorBox error={pending ? null : act.error} />
      <OkBox text={pending ? null : act.ok} />

      <Card icon="model" title={t("fsrc.one")}>
        <p className="small muted">{t("fsrc.one_help")}</p>
        <div className="row wrap">
          <Field label={t("fc.sku")}>
            <input value={oneSku} onChange={(e) => { setOneSku(e.target.value); setEff(null); }} data-testid="fsrc-one-sku" aria-label={t("fc.sku")} />
          </Field>
          <Field label={t("fc.fc")}>
            <input value={oneFc} onChange={(e) => { setOneFc(e.target.value); setEff(null); }} data-testid="fsrc-one-fc" aria-label={t("fc.fc")} />
          </Field>
          <button onClick={lookup} disabled={act.busy || !oneSku.trim() || !oneFc.trim()} data-testid="fsrc-lookup"><Icon name="search" />{t("fsrc.lookup")}</button>
        </div>
        {eff && (
          <div className="stack" data-testid="fsrc-effective">
            <p className="small"><span className="mono">{eff.sku_code}</span> × <span className="mono">{eff.fc_code}</span>: {" "}
              <Pill status={SOURCE_PILL[eff.forecast_source] ?? "INFO"} label={srcLabel(eff.forecast_source)} />{" "}
              {eff.configured ? `${t("fsrc.updated")} ${fmtTime(eff.updated_at)} · ${eff.updated_by ?? "—"}` : t("fsrc.default_note")}</p>
            <div className="row wrap">
              <Field label={t("fsrc.new_source")}>
                <select value={newSrc} onChange={(e) => setNewSrc(e.target.value)} data-testid="fsrc-new-source" aria-label={t("fsrc.new_source")}>
                  {SOURCES.map((s) => <option key={s} value={s}>{srcLabel(s)}</option>)}
                </select>
              </Field>
              <Field label={t("fsrc.note")}>
                <input value={note} onChange={(e) => setNote(e.target.value)} data-testid="fsrc-note" aria-label={t("fsrc.note")} />
              </Field>
              <button className="prod" title={t("common.prod_action")} disabled={act.busy} data-testid="fsrc-change"
                onClick={() => ask({ sku_code: eff.sku_code, fc_code: eff.fc_code, from: eff.forecast_source, configured: !!eff.configured, to: newSrc, ghi_chu: note })}>
                <Icon name="save" />{t("fsrc.change")}</button>
            </div>
          </div>
        )}
      </Card>

      <Card icon="results" title={t("fsrc.list")}>
        <div className="grid4">
          <Stat icon="model" label={t("fsrc.src.LIGHTGBM")} value={fmtNum(counts.LIGHTGBM ?? 0)} sub={t("fsrc.configured_rows")} />
          <Stat icon="chart" label={t("fsrc.src.AVG_DEMAND")} value={fmtNum(counts.AVG_DEMAND ?? 0)} sub={t("fsrc.configured_rows")} />
        </div>
        <p className="small muted">{t("fsrc.default_help")}</p>
        <FilterBar active={nFilters} onClear={clear}>
          <Field label={t("fc.sku")}>
            <SearchInput value={sku} onChange={setSku} label={t("fsrc.search_sku")} clearLabel={t("fc.search_clear")} testid="fsrc-q-sku" />
          </Field>
          <Field label={t("fc.fc")}>
            <SearchInput value={fc} onChange={setFc} label={t("fsrc.search_fc")} clearLabel={t("fc.search_clear")} testid="fsrc-q-fc" />
          </Field>
          <Field label={t("fsrc.source")}>
            <select value={src} onChange={(e) => setSrc(e.target.value)} aria-label={t("fsrc.source")} data-testid="fsrc-q-source">
              <option value="">{t("common.all")}</option>
              {SOURCES.map((s) => <option key={s} value={s}>{srcLabel(s)}</option>)}
            </select>
          </Field>
        </FilterBar>
        <ErrorBox error={cfg.error} />
        {cfg.loading && !c && <Loading />}
        {c && list(c.items).length === 0 && <Empty text={t("fsrc.none")} hint={t("fsrc.default_help")} />}
        {c && list(c.items).length > 0 && (
          <div className="scroll">
            <table className="tbl" data-testid="fsrc-table">
              <thead><tr><th>{t("fc.sku")}</th><th>{t("fc.fc")}</th><th>{t("fsrc.source")}</th><th>{t("fsrc.note")}</th>
                <th>{t("fsrc.updated_by")}</th><th>{t("fsrc.updated_at")}</th><th></th></tr></thead>
              <tbody>
                {list(c.items).map((r: any) => (
                  <tr key={`${r.sku_code}|${r.fc_code}`}>
                    <td className="sku">{r.sku_code}</td><td className="nowrap">{r.fc_code}</td>
                    <td><Pill status={SOURCE_PILL[r.forecast_source] ?? "INFO"} label={srcLabel(r.forecast_source)} /></td>
                    <td>{r.ghi_chu ?? ""}</td><td>{r.updated_by ?? "—"}</td><td className="nowrap">{fmtTime(r.updated_at)}</td>
                    <td><button className="ghost small prod" title={t("common.prod_action")} disabled={act.busy}
                      data-testid={`fsrc-toggle-${r.sku_code}-${r.fc_code}`}
                      onClick={() => ask({ sku_code: r.sku_code, fc_code: r.fc_code, from: r.forecast_source, configured: true,
                        to: other(r.forecast_source), ghi_chu: r.ghi_chu ?? "" })}>
                      {t("fsrc.switch_to").replace("{s}", srcLabel(other(r.forecast_source)))}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} total={c?.total ?? 0} size={PAGE} unit={t("common.rows")} onPage={setPage} />
      </Card>

      <Card icon="upload" title={t("fsrc.upload")}>
        <p className="small muted">{t("fsrc.upload_help")}</p>
        <div className="row wrap">
          <input type="file" aria-label={t("imp.only_xlsx")} data-testid="fsrc-file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => { setPreview(null); up.setError(null); up.setOk(null); setFile(e.target.files?.[0] ?? null); }} />
          <button className="primary" onClick={doPreview} disabled={!file || up.busy} data-testid="fsrc-preview"><Icon name="upload" />{t("fsrc.preview")}</button>
        </div>
        <ErrorBox error={applyOpen ? null : up.error} />
        <OkBox text={up.ok} />
        {preview && (
          <div className="stack" data-testid="fsrc-preview-result">
            <p className="small">{t("fsrc.preview_of")} <b>{preview.filename ?? "—"}</b> · {t("fsrc.expires")} {fmtTime(preview.expires_at)}</p>
            <div className="grid4" data-testid="fsrc-preview-counts">
              <Stat icon="file" label={t("fsrc.p_rows")} value={fmtNum(pc?.rows)} />
              <Stat icon="ok" label={t("fsrc.p_changed")} value={fmtNum(pc?.changed)} tone={pc?.changed ? "ok" : undefined} />
              <Stat icon="muted" label={t("fsrc.p_unchanged")} value={fmtNum(pc?.unchanged)} />
              <Stat icon="bad" label={t("fsrc.p_errors")} value={fmtNum(pc?.errors)} tone={pc?.errors ? "bad" : undefined} />
            </div>
            {list(preview.errors).length > 0 && (
              <>
                <div className="alert bad small" role="alert">{t("fsrc.has_errors")}</div>
                <div className="scroll">
                  <table className="tbl small" data-testid="fsrc-errors">
                    <thead><tr><th className="num">{t("fsrc.row")}</th><th>{t("fc.sku")}</th><th>{t("fc.fc")}</th><th>{t("fsrc.source")}</th>
                      <th>{t("fsrc.reason")}</th></tr></thead>
                    <tbody>
                      {list(preview.errors).map((r: any) => (
                        <tr key={r.row}>
                          <td className="num">{r.row}</td><td className="sku">{r.sku_code ?? "—"}</td><td className="nowrap">{r.fc_code ?? "—"}</td>
                          <td>{r.forecast_source ?? "—"}</td><td>{t(`fsrc.reason.${r.reason}`)} <code className="code">{r.reason}</code></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {preview.errors_truncated && <p className="small muted">{t("fsrc.truncated")}</p>}
              </>
            )}
            {list(preview.changes).length > 0 && (
              <>
                <div className="scroll">
                  <table className="tbl small" data-testid="fsrc-changes">
                    <thead><tr><th className="num">{t("fsrc.row")}</th><th>{t("fc.sku")}</th><th>{t("fc.fc")}</th><th>{t("fsrc.from")}</th>
                      <th>{t("fsrc.to")}</th><th>{t("fsrc.note")}</th></tr></thead>
                    <tbody>
                      {list(preview.changes).map((r: any) => (
                        <tr key={r.row}>
                          <td className="num">{r.row}</td><td className="sku">{r.sku_code}</td><td className="nowrap">{r.fc_code}</td>
                          <td>{srcLabel(r.effective_old_source)}</td><td><b>{srcLabel(r.new_source)}</b></td><td>{r.ghi_chu ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {preview.changes_truncated && <p className="small muted">{t("fsrc.truncated")}</p>}
              </>
            )}
            {!pc?.errors && !pc?.changed && <p className="small muted" data-testid="fsrc-no-change">{t("fsrc.no_change")}</p>}
            <div className="row wrap">
              <button className="prod" title={t("common.prod_action")} disabled={up.busy || !preview.can_apply} data-testid="fsrc-apply"
                onClick={() => { up.setError(null); setApplyOpen(true); }}><Icon name="save" />{t("fsrc.apply")}</button>
            </div>
          </div>
        )}
      </Card>

      <Card icon="history" title={t("fsrc.history")}
        actions={<a className="btn" href="/api/sel2/source-config/history?format=xlsx" data-testid="fsrc-history-xlsx">
          <Icon name="export" />{t("fsrc.history_xlsx")}</a>}>
        <ErrorBox error={hist.error} />
        {hist.loading && !hist.data && <Loading />}
        {hist.data && list(hist.data.items).length === 0 && <Empty text={t("fsrc.no_history")} />}
        {hist.data && list(hist.data.items).length > 0 && (
          <div className="scroll">
            <table className="tbl small" data-testid="fsrc-history">
              <thead><tr><th>{t("fsrc.updated_at")}</th><th>{t("fc.sku")}</th><th>{t("fc.fc")}</th><th>{t("fsrc.from")}</th><th>{t("fsrc.to")}</th>
                <th>{t("fsrc.note")}</th><th>{t("fsrc.updated_by")}</th><th>{t("fsrc.channel")}</th><th>{t("fsrc.batch")}</th></tr></thead>
              <tbody>
                {list(hist.data.items).map((r: any) => (
                  <tr key={r.id}>
                    <td className="nowrap">{fmtTime(r.changed_at)}</td><td className="sku">{r.sku_code}</td><td className="nowrap">{r.fc_code}</td>
                    <td>{r.old_source ? srcLabel(r.old_source) : t("fsrc.from_default")}</td><td>{srcLabel(r.new_source)}</td>
                    <td>{r.ghi_chu ?? ""}</td><td>{r.changed_by ?? "—"}</td><td>{t(`fsrc.channel.${r.channel}`)}</td>
                    <td className="mono small">{r.batch_id ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={hPage} total={hist.data?.total ?? 0} size={PAGE} unit={t("common.rows")} onPage={setHPage} />
      </Card>

      <Confirm open={pending !== null} title={t("fsrc.confirm_title")} onCancel={() => setPending(null)} onConfirm={save}
        confirmLabel={t("fsrc.change")} disabled={act.busy}>
        {pending && (
          <p data-testid="fsrc-confirm-body"><span className="mono">{pending.sku_code}</span> × <span className="mono">{pending.fc_code}</span>:{" "}
            {srcLabel(pending.from)}{pending.configured ? "" : ` (${t("fsrc.default")})`} → <b>{srcLabel(pending.to)}</b></p>
        )}
        <p className="small muted">{t("fsrc.confirm_body")}</p>
        <ErrorBox error={act.error} />
      </Confirm>
      <Confirm open={applyOpen} title={t("fsrc.apply_title")} onCancel={() => setApplyOpen(false)} onConfirm={apply}
        confirmLabel={t("fsrc.apply")} disabled={up.busy}>
        <p data-testid="fsrc-apply-body">{t("fsrc.apply_body").replace("{n}", fmtNum(pc?.changed))}</p>
        <ErrorBox error={up.error} />
      </Confirm>
    </div>
  );
}
