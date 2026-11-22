"""1.4.15 (lot 2B): settings export / import (JSON file "df-settings", format_version 1).

Export (read-only): the whitelisted sections (EXPORT_SECTIONS) with every key that is not excluded: VISIBLE keys, the
editable registry keys and the fixed rules (settings_registry.exportable), the 10 data_policy keys. Never: secrets
(they are not in app_settings at all), OAuth, BigQuery connection / mapping / paths, sql_sources, general, flow switches
and *_enabled_at, d0_paused_*, trial_mode, production_enabled, schema_snapshot, feature_table (the `excluded` list of
the file names them). sha256 = hash of the canonical JSON of `sections` (sorted keys, no spaces, UTF-8).

Import, step 1 `preview` (never writes): the WHOLE file is refused for a wrong format, a newer format_version, a wrong
sha256, an unknown / excluded key, a value of the wrong type, a read-only key (fixed rule) whose value differs, a
window_start_date that differs (locked, lot 1); per section: current / file values, risk, its errors (a retention
decrease, a path, a section that does not validate) and `expected` = hash of the current section JSON. Sections with
a HIGH / PURCHASE key are not selected by default.
Step 2 `apply`: ONE transaction, all or nothing: busy gate (as /api/settings-advanced), expected hash of every selected
section (409 SETTINGS_CHANGED_ELSEWHERE), typed NHAP-CAI-DAT-<Vietnam day> + reason >= 10 characters, every selected
section validated as a whole, one settings-history row per changed section (note "nhap tu tep <short hash>") and the
audit SETTINGS_IMPORTED {import_id, sha256, entries:[{section, history_id_before, keys:{k:{from,to}}}]}. The guarded
data_policy fields (except window_start_date) are imported by this action (its typed text is the gate).
`undo`: puts back the keys of one import only where the current value is still its `to` (else 409 with the list).
"""
from __future__ import annotations

import hashlib
import json
import secrets

from pydantic import ValidationError

from . import __version__, db
from . import settings_registry as reg
from . import settings_service as ss
from .messages import AppError
from .timeutil import now_iso, now_vn, today_vn

FORMAT = "df-settings"
FORMAT_VERSION = 1
EXPORT_SECTIONS = ("data_policy", "model", "quality", "horizons", "import", "schedule", "daily_forecast",
                   "sel2_pipeline", "bigquery")
REASON_MIN = 10
REASON_MAX = 500
LOCKED = ("window_start_date",)                                     # data_policy: must equal the current value
# import risk of the keys outside the registry (data-reviewer L2-DREV): data_policy guarded fields that change the
# stored demand / the model input = PURCHASE; VISIBLE keys by section (a section absent here: LOW)
DP_PURCHASE = ("history_change_policy", "training_start_rule")
DP_HIGH = ("window_start_date",)
VISIBLE_RISK = {"model": "PURCHASE", "horizons": "PURCHASE", "schedule": "HIGH", "bigquery": "HIGH", "quality": "HIGH",
                "import": "HIGH"}
UNDO_ACTION = "SETTINGS_IMPORT_UNDONE"


# ------------------------------------------------------------------ whitelist
def _kind(section: str, key: str) -> str:
    """EDIT (importable), READONLY (allowed only with the current value) or EXCLUDED."""
    if section not in EXPORT_SECTIONS or (section, key) in reg.EXCLUDED:
        return "EXCLUDED"
    if section == "data_policy":
        return "READONLY" if key in LOCKED else "EDIT"
    if (section, key) in reg.VISIBLE:
        return "EDIT"
    e = reg.entry(section, key)
    if e is None:
        return "EXCLUDED"
    if reg.editable(e):
        return "EDIT"
    if reg.risk(e) == "READONLY" and reg.reason_code(e) == "REG_FIXED_RULE":
        return "READONLY"
    return "EXCLUDED"


def export_keys(section: str) -> list[str]:
    return [k for k in ss.SECTIONS[section].model_fields if _kind(section, k) != "EXCLUDED" and
            (section == "data_policy" or (section, k) in reg.VISIBLE or reg.exportable(reg.entry(section, k)))]


def excluded_keys() -> list[str]:
    out = [f"{s}.*" for s in ss.SECTIONS if s not in EXPORT_SECTIONS]
    for s in EXPORT_SECTIONS:
        keep = set(export_keys(s))
        out += [f"{s}.{k}" for k in ss.SECTIONS[s].model_fields if k not in keep]
    return sorted(out)


def _risk(section: str, key: str) -> str:
    if section == "data_policy":
        return "PURCHASE" if key in DP_PURCHASE else ("HIGH" if key in DP_HIGH else "LOW")
    e = reg.entry(section, key)
    if e is not None:
        return reg.risk(e)
    return VISIBLE_RISK.get(section, "LOW")         # a VISIBLE key (edited on its own page)


def purchase_text() -> str:
    return f"DOI-CAI-DAT-ANH-HUONG-MUA-HANG-{today_vn().isoformat()}"


def high_text() -> str:
    return f"DOI-CAI-DAT-AN-{today_vn().isoformat()}"


def _confirm_high(keys: list[str], text: str | None) -> None:
    """A changed HIGH key (no PURCHASE key needed for it) also needs the HIGH text of the advanced settings."""
    if keys and (text or "").strip() != high_text():
        raise AppError("SETTINGS_IMPORT_HIGH_CONFIRM_REQUIRED", 409, detail=", ".join(keys), keys=keys,
                       confirm_high=high_text())


def _confirm_purchase(keys: list[str], text: str | None) -> None:
    """A changed PURCHASE key also needs the purchase text of the advanced settings (same gate as there)."""
    if keys and (text or "").strip() != purchase_text():
        raise AppError("SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED", 409, detail=", ".join(keys), keys=keys,
                       confirm_purchase=purchase_text())


def _norm(obj):
    """An integral float is written as an integer (10.0 -> 10): a browser re-serialising the file (JSON.parse /
    JSON.stringify) drops the '.0', and the hash must stay the same."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    return obj


def canonical(obj) -> bytes:
    return json.dumps(_norm(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def _schema_version(c) -> int:
    try:
        return int(c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0)
    except Exception:  # noqa: BLE001 - no migration table
        return 0


def confirm_text() -> str:
    return f"NHAP-CAI-DAT-{today_vn().isoformat()}"


def file_name() -> str:
    return f"cai_dat_{now_vn().strftime('%Y%m%d_%H%M')}.json"


# ------------------------------------------------------------------ export
def export_doc(c) -> dict:
    sections = {}
    for s in EXPORT_SECTIONS:
        cur = ss.get(s, c).model_dump(mode="json")
        sections[s] = {k: cur[k] for k in export_keys(s)}
    return {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": __version__,
            "schema_version": _schema_version(c), "exported_at": now_iso(), "sections": sections,
            "excluded": excluded_keys(), "sha256": sha256(sections)}


# ------------------------------------------------------------------ import: checks
def _refuse(code: str, detail: str, status: int = 422, **params):
    raise AppError(code, status, detail=detail, **params)


def _check_file(doc) -> dict:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        _refuse("SETTINGS_IMPORT_INVALID_FILE", f"format must be {FORMAT}")
    fv = doc.get("format_version")
    if not isinstance(fv, int) or isinstance(fv, bool) or fv < 1:
        _refuse("SETTINGS_IMPORT_INVALID_FILE", "format_version must be a positive integer")
    if fv > FORMAT_VERSION:
        _refuse("SETTINGS_IMPORT_VERSION_NEWER", f"format_version {fv} > {FORMAT_VERSION}")
    sections = doc.get("sections")
    if not isinstance(sections, dict) or not sections or not all(isinstance(v, dict) for v in sections.values()):
        _refuse("SETTINGS_IMPORT_INVALID_FILE", "sections must be an object of section objects")
    if doc.get("sha256") != sha256(sections):
        _refuse("SETTINGS_IMPORT_HASH_MISMATCH", "sha256 of sections does not match")
    unknown, excluded = [], []
    for s, keys in sections.items():
        fields = ss.SECTIONS[s].model_fields if s in ss.SECTIONS else {}
        for k in keys:
            if k not in fields:
                unknown.append(f"{s}.{k}")
            elif _kind(s, k) == "EXCLUDED":
                excluded.append(f"{s}.{k}")
    if unknown:
        _refuse("SETTINGS_IMPORT_UNKNOWN_KEY", ", ".join(sorted(unknown)), keys=sorted(unknown))
    if excluded:
        _refuse("SETTINGS_IMPORT_EXCLUDED_KEY", ", ".join(sorted(excluded)), keys=sorted(excluded))
    return sections


def _validated(section: str, cur, patch: dict):
    ctx = {"stored": True} if section == "schedule" else None
    return ss.SECTIONS[section].model_validate({**cur.model_dump(), **patch}, context=ctx)


def _plan(c, doc) -> dict:
    """File checks + the per-section plan; raises for a file-level refusal. Never writes."""
    sections = _check_file(doc)
    out, bad_type, ro_diff = [], [], []
    for s in EXPORT_SECTIONS:
        if s not in sections:
            continue
        patch = sections[s]
        cur_model = ss.get(s, c)
        cur = cur_model.model_dump(mode="json")
        errors: list[str] = []
        try:
            after = _validated(s, cur_model, patch).model_dump(mode="json")
        except ValidationError as e:
            after = None
            errors.append("SETTINGS_IMPORT_INVALID_VALUE: " + "; ".join(
                f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
        rows = []
        for k, v in patch.items():
            if after is not None and not reg.same(after[k], v):
                bad_type.append(f"{s}.{k}")         # coerced by the model ("5" for 5): the file is not this app's
            if _kind(s, k) == "READONLY" and not reg.same(cur[k], v):
                ro_diff.append(f"{s}.{k}")
            to = after[k] if after is not None else v
            changed = not reg.same(cur[k], to)
            e = reg.entry(s, k)
            if changed and e is not None and e.only_increase and isinstance(to, (int, float)) and to < cur[k]:
                errors.append(f"RETENTION_DECREASE_NOT_ALLOWED: {k} {cur[k]} -> {to}")
            if changed and e is not None and e.path_rule and not reg.path_ok(e, to):
                errors.append(f"SETTINGS_PATH_INVALID: {k}")
            rows.append({"key": k, "current": cur[k], "file": v, "risk": _risk(s, k), "changed": changed})
        changed_rows = [r for r in rows if r["changed"]]
        top = reg.risk_max(r["risk"] for r in changed_rows)
        out.append({"section": s, "rows": rows, "changed": [r["key"] for r in changed_rows], "max_risk": top,
                    "purchase_keys": [f"{s}.{r['key']}" for r in changed_rows if r["risk"] == "PURCHASE"],
                    "high_keys": [f"{s}.{r['key']}" for r in changed_rows if r["risk"] == "HIGH"],
                    "errors": errors, "selectable": bool(changed_rows) and not errors,
                    "default_selected": bool(changed_rows) and not errors and top not in ("HIGH", "PURCHASE"),
                    "expected": sha256(cur)})
    if bad_type:
        _refuse("SETTINGS_IMPORT_INVALID_VALUE", ", ".join(bad_type), keys=bad_type)
    if ro_diff:
        locked = [k for k in ro_diff if k == "data_policy.window_start_date"]
        _refuse("SETTINGS_IMPORT_WINDOW_START_DIFFERS" if locked else "SETTINGS_IMPORT_READONLY_DIFFERS",
                ", ".join(ro_diff), keys=ro_diff)
    return {"sections": out, "sha256": doc["sha256"]}


def preview(c, doc) -> dict:
    plan = _plan(c, doc)
    warnings = []
    if doc.get("app_version") != __version__:
        warnings.append("SETTINGS_IMPORT_APP_VERSION_DIFFERS")
    if doc.get("schema_version") != _schema_version(c):
        warnings.append("SETTINGS_IMPORT_SCHEMA_VERSION_DIFFERS")
    if not any(p["changed"] for p in plan["sections"]):
        warnings.append("NO_CHANGE")
    purchase = [k for p in plan["sections"] for k in p["purchase_keys"]]
    high = [k for p in plan["sections"] for k in p["high_keys"]]
    spike_cur = ss.get("sel2_pipeline", c)
    in_file = doc["sections"].get("sel2_pipeline", {})
    if "sel2_pipeline" in doc["sections"] and not all(k in in_file for k in reg.SPIKE_KEYS):
        # an older file without spike_cleaning / spike_e4_n: this machine keeps its own values (shown in spike_current)
        warnings.append("SPIKE_NOT_TRANSFERRED")
    return {**plan, "file": {k: doc.get(k) for k in ("app_version", "schema_version", "exported_at", "format_version")},
            "current": {"app_version": __version__, "schema_version": _schema_version(c)}, "warnings": warnings,
            "notes": ["APPLIES_FROM_NEXT_RUN", "UNDO_SETTINGS_ONLY"], "confirm_text": confirm_text(),
            "reason_min_length": REASON_MIN, "needs_purchase_confirm": bool(purchase), "purchase_keys": purchase,
            "confirm_purchase": purchase_text(), "needs_high_confirm": bool(high), "high_keys": high,
            "confirm_high": high_text(),
            "spike_current": {k: getattr(spike_cur, k) for k in reg.SPIKE_KEYS}}


# ------------------------------------------------------------------ import: write
def _busy(c) -> dict:
    from .api.data_policy_routes import _busy_state
    from .jobs import runner
    st = _busy_state(c, runner.JOB_TYPES)
    if st["busy"]:
        raise AppError("SETTINGS_ADVANCED_BUSY", 409, detail=st["detail"], window=st["window"], jobs=st["jobs"],
                       stale_ignored=st["stale_ignored"], stale_ignored_total=st["stale_ignored_total"])
    return st


def _confirm(text: str | None, reason: str | None) -> str:
    r = " ".join((reason or "").split())
    if len(r) > REASON_MAX:
        _refuse("SETTINGS_IMPORT_INVALID_FILE", f"reason longer than {REASON_MAX} characters")
    want = confirm_text()
    if (text or "").strip() != want or len(r) < REASON_MIN:
        raise AppError("SETTINGS_IMPORT_CONFIRM_REQUIRED", 409, detail=f"type {want} + a reason of at least "
                                                                       f"{REASON_MIN} characters", confirm_text=want)
    return r


def _history_id(c, section: str) -> int:
    return int(c.execute("SELECT MAX(id) FROM settings_history WHERE section=?", (section,)).fetchone()[0] or 0)


def _stale(busy: dict) -> dict:
    return {"stale_ignored": [{k: j[k] for k in ("id", "job_type", "status")} for j in busy["stale_ignored"]],
            "stale_ignored_total": busy["stale_ignored_total"]}


def _write(c, section: str, keys: dict, note: str) -> dict:
    """keys = {k: {from, to}}; the whole section validated with the new values; returns the audit entry."""
    before = _history_id(c, section)
    try:
        new = _validated(section, ss.get(section, c), {k: v["to"] for k, v in keys.items()})
    except ValidationError as e:
        raise AppError("SETTINGS_IMPORT_INVALID_VALUE", 422, detail=f"{section}: " + "; ".join(
            f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from None
    ss.save(section, new, note=note, conn=c)
    return {"section": section, "history_id_before": before, "history_id_after": _history_id(c, section),
            "keys": keys}


def _note(prefix: str, section: str, keys: dict, reason: str) -> str:
    return f"{prefix} {section}: " + "; ".join(
        f"{k} {json.dumps(v['from'], ensure_ascii=False)} -> {json.dumps(v['to'], ensure_ascii=False)}"
        for k, v in keys.items()) + f": {reason}"


def apply(c, doc, sections: list[str], expected: dict, confirm: str | None, reason: str | None,
          confirm_purchase: str | None = None, confirm_high: str | None = None) -> dict:
    """Inside the caller's db.tx(): all selected sections or nothing."""
    busy = _busy(c)
    plan = {p["section"]: p for p in _plan(c, doc)["sections"]}
    if not sections or len(set(sections)) != len(sections):
        _refuse("SETTINGS_IMPORT_NO_SECTION", "select at least one section, each once")
    for s in sections:
        p = plan.get(s)
        if p is None:
            _refuse("SETTINGS_IMPORT_NO_SECTION", f"{s} is not in the file")
        if p["errors"]:
            _refuse("SETTINGS_IMPORT_SECTION_INVALID", f"{s}: " + "; ".join(p["errors"]), section=s, errors=p["errors"])
    missing = [s for s in sections if s not in (expected or {})]
    if missing:
        _refuse("SETTINGS_ADVANCED_EXPECTED_REQUIRED", ", ".join(missing))
    stale = [s for s in sections if expected[s] != plan[s]["expected"]]
    if stale:
        raise AppError("SETTINGS_CHANGED_ELSEWHERE", 409, detail=", ".join(stale),
                       current={s: plan[s]["expected"] for s in stale})
    if not any(plan[s]["changed"] for s in sections):
        raise AppError("NO_CHANGE", 400)
    r = _confirm(confirm, reason)
    _confirm_purchase([k for s in sections for k in plan[s]["purchase_keys"]], confirm_purchase)
    _confirm_high([k for s in sections for k in plan[s]["high_keys"]], confirm_high)
    sha = doc["sha256"]
    import_id = f"IMP-{secrets.token_hex(6)}"
    entries = []
    for s in sections:
        keys = {row["key"]: {"from": row["current"], "to": row["file"]} for row in plan[s]["rows"] if row["changed"]}
        if keys:
            entries.append(_write(c, s, keys, _note(f"nhap tu tep {sha[:12]} ({import_id})", s, keys, r)))
    db.audit(c, "SETTINGS_IMPORTED", "settings_import", import_id,
             {"import_id": import_id, "sha256": sha, "reason": r, "entries": entries, **_stale(busy)})
    audit_id = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    return {"import_id": import_id, "audit_id": audit_id, "entries": entries}


def undo(c, import_id: str, confirm: str | None, reason: str | None, confirm_purchase: str | None = None,
         confirm_high: str | None = None) -> dict:
    """Same gates as an apply; like /api/settings-advanced/undo, a key that is no longer importable (READONLY,
    OWN_PATH) refuses the WHOLE undo (422 SETTINGS_ADVANCED_NOT_EDITABLE)."""
    busy = _busy(c)
    row = db.one(c, "SELECT id, details_json FROM audit_log WHERE action='SETTINGS_IMPORTED' AND entity_id=?",
                 (import_id,))
    if row is None:
        raise AppError("SETTINGS_IMPORT_NOT_FOUND", 404, detail=import_id)
    if db.one(c, f"SELECT id FROM audit_log WHERE action='{UNDO_ACTION}' AND entity_id=?", (import_id,)):
        raise AppError("SETTINGS_ADVANCED_ALREADY_UNDONE", 409, detail=import_id)
    entries = json.loads(row["details_json"] or "{}").get("entries") or []
    moved, back, purchase, high, skipped = [], [], [], [], []
    for en in entries:
        cur = ss.get(en["section"], c).model_dump(mode="json")
        keys = {}
        for k, v in en["keys"].items():
            if _kind(en["section"], k) != "EDIT":
                raise AppError("SETTINGS_ADVANCED_NOT_EDITABLE", 422, detail=f"{en['section']}.{k}")
            e = reg.entry(en["section"], k)
            if e is not None and e.only_increase and v["from"] < v["to"]:
                # the import raised a retention: undoing it would shorten it (= delete data) -> key left as it is
                skipped.append({"section": en["section"], "key": k, "reason": "UNDO_SKIPPED_RETENTION_DECREASE",
                                "value": cur[k]})
                continue
            if _risk(en["section"], k) == "PURCHASE":
                purchase.append(f"{en['section']}.{k}")
            elif _risk(en["section"], k) == "HIGH":
                high.append(f"{en['section']}.{k}")
            if not reg.same(cur[k], v["to"]):
                moved.append(f"{en['section']}.{k}")
            keys[k] = {"from": v["to"], "to": v["from"]}
        back.append((en["section"], keys))
    if moved:
        raise AppError("SETTINGS_CHANGED_ELSEWHERE", 409, detail=", ".join(moved), keys=moved)
    r = _confirm(confirm, reason)
    _confirm_purchase(purchase, confirm_purchase)
    _confirm_high(high, confirm_high)
    done = [_write(c, s, keys, _note(f"hoan tac nhap {import_id}", s, keys, r)) for s, keys in back if keys]
    db.audit(c, UNDO_ACTION, "settings_import", import_id,
             {"import_id": import_id, "reason": r, "entries": done, "skipped": skipped, **_stale(busy)})
    return {"import_id": import_id, "entries": done, "skipped": skipped}


def history(c, limit: int = 20) -> list[dict]:
    rows = db.rows(c, "SELECT id, at, action, entity_id, details_json FROM audit_log WHERE action IN "
                      f"('SETTINGS_IMPORTED', '{UNDO_ACTION}') ORDER BY id DESC LIMIT ?", (limit,))
    undone = {r["entity_id"] for r in db.rows(c, f"SELECT entity_id FROM audit_log WHERE action='{UNDO_ACTION}'")}
    for r in rows:
        r["details"] = json.loads(r.pop("details_json") or "{}")
        r["undone"] = r["action"] == "SETTINGS_IMPORTED" and r["entity_id"] in undone
    return rows
