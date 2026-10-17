"""User-managed SQL for the two BigQuery feeds: HISTORY (D-1 and older) and D0 (today, several times a day).

Rules:
* Saving a text creates a new version; it is NOT used until a BigQuery validation of THAT version succeeds
  (dry run: statement type SELECT, required output columns present, cost under the limit). The active version is the
  last validated one; an invalid new version never replaces it.
* The text is never rewritten. It runs as `SELECT <app columns> FROM ( <user sql> )`.
* A job captures the active version (id + sha256 + text) when it starts and uses that snapshot until it ends.
* Changing SQL never makes a new column a model feature (feature registry decides, see ml/feature_registry.py).
* 1.2.1: the D0 feed has its OWN mapping (bigquery.d0_mapping, see d0_feed.py): its output only needs SKU, FC,
  quantity and the day, under its own column names - never the D-1 columns.
"""
from __future__ import annotations

from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso
from . import sql_guard

KINDS = ("history", "d0")
# output columns the app needs from the history SQL feed (names come from the D-1 field mapping); the D0 feed's
# columns come from the D-0 mapping (d0_feed.used)
NEEDED = {"history": ("order_date|created_at", "sku_id", "fc_id", "order_qty")}


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"unknown SQL feed {kind}")
    return kind


def config() -> ss.SqlSourcesSettings:
    return ss.get("sql_sources")


def source(kind: str) -> ss.SqlSource:
    return getattr(config(), _kind(kind))


def _save(cfg: ss.SqlSourcesSettings, note: str) -> None:
    ss.save("sql_sources", cfg, note=note)


def version(src: ss.SqlSource, vid: int) -> ss.SqlVersion:
    v = next((x for x in src.versions if x.id == vid), None)
    if v is None:
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"SQL version {vid}")
    return v


def effective_keys(src: ss.SqlSource, kind: str = "history") -> list[str]:
    """Candidate unique key actually checked: the user's list, else the mapped order / SKU / FC / date columns (of
    the D-1 mapping for history, of the D-0 mapping for D0)."""
    if src.key_columns:
        return list(src.key_columns)
    bq = ss.get("bigquery")
    if kind == "d0":
        from . import d0_feed
        return d0_feed.key_columns(src, bq)
    out: list[str] = []
    for f in ("order_id", "sku_id", "fc_id", "order_date", "created_at"):
        m = bq.field_mapping.get(f)
        if m and m.column and m.usage != "UNUSED" and m.column not in out:
            out.append(m.column)
    return out


def view(kind: str) -> dict:
    src = source(kind)
    active = next((v for v in src.versions if v.id == src.active_version_id), None)
    out = {"kind": kind, "mode": src.mode, "active_version_id": src.active_version_id,
            "active": _v(active) if active else None, "key_columns": src.key_columns,
            "effective_key_columns": effective_keys(src, kind),
            "key_duplicate_policy": src.key_duplicate_policy,
            # D-0 schedule = the D-0 flow switch (schedule.d0_enabled); the history feed is scheduled by the D-1 flow
            "schedule_enabled": ss.get("schedule").d0_enabled if kind == "d0" else ss.get("schedule").d1_enabled,
            "versions": [_v(v) for v in sorted(src.versions, key=lambda x: -x.id)],
            "needed_outputs": required_columns(kind)}
    if kind == "d0":
        from . import d0_feed
        out["d0"] = d0_feed.view()
        h = out["d0"]["mapping_hash"]
        for v in out["versions"]:        # a validation proves only the mapping / key it was made for
            val = v.get("validation") or {}
            v["validated_for_current_mapping"] = val.get("status") == "VALID" and val.get("d0_mapping_hash") == h
    return out


def _v(v: ss.SqlVersion) -> dict:
    return {**v.model_dump(), "static_check": sql_guard.check(v.sql)}


def required_columns(kind: str) -> list[str]:
    bq = ss.get("bigquery")
    if kind == "d0":
        from . import d0_feed
        u = d0_feed.used(bq)
        df = d0_feed.date_field(u)
        out = [u.get(f) or f"<{f}: chưa ánh xạ>" for f in ("sku_id", "fc_id", "order_qty")]
        return out + [u[df] if df else "<order_date|created_at: chưa ánh xạ>"]
    out = []
    for need in NEEDED[kind]:
        cols = [bq.field_mapping[f].column for f in need.split("|")
                if bq.field_mapping.get(f) and bq.field_mapping[f].column and bq.field_mapping[f].usage != "UNUSED"]
        out.append(cols[0] if cols else f"<{need}: chưa ánh xạ>")
    return out


def save_version(kind: str, sql: str, note: str | None = None) -> dict:
    """Store a new version (never activates it). Rejected only when the static guard finds a non-query/write text."""
    cfg = config()
    src = getattr(cfg, _kind(kind))
    chk = sql_guard.check(sql)
    if not chk["ok"]:
        raise AppError("SQL_REJECTED", 422, detail="; ".join(f"{e['code']}{':' + str(e['detail']) if e.get('detail') else ''}"
                                                           for e in chk["errors"]))
    vid = max([v.id for v in src.versions] or [0]) + 1
    src.versions.append(ss.SqlVersion(id=vid, sql=sql, sha256=ss._sha(sql), saved_at=now_iso(), note=note))
    # keep at most MAX_SQL_VERSIONS, never dropping the active one
    while len(src.versions) > ss.MAX_SQL_VERSIONS:
        old = next(v for v in sorted(src.versions, key=lambda x: x.id) if v.id != src.active_version_id)
        src.versions.remove(old)
    _save(cfg, f"{kind} SQL version {vid} saved")
    return {**view(kind), "saved_version_id": vid}


def set_options(kind: str, mode: str | None = None, key_columns: list[str] | None = None,
                key_duplicate_policy: str | None = None, schedule_enabled: bool | None = None) -> dict:
    cfg = config()
    src = getattr(cfg, _kind(kind))
    if mode is not None:
        if mode not in ("TABLE", "SQL"):
            raise AppError("VALIDATION_ERROR", 422, detail=mode)
        src.mode = mode
    if key_columns is not None:
        src.key_columns = key_columns
    if key_duplicate_policy is not None:
        src.key_duplicate_policy = key_duplicate_policy
    if schedule_enabled is not None and kind != "d0":
        raise AppError("VALIDATION_ERROR", 422, detail="only the D-0 feed has a schedule switch here; D-1 is on the schedule page")
    if mode is not None or key_columns is not None or key_duplicate_policy is not None:
        _save(ss.SqlSourcesSettings.model_validate(cfg.model_dump()), f"{kind} SQL options changed")
    if schedule_enabled is not None:
        # 1.1.8: ONE switch for D-0 = schedule.d0_enabled (same readiness rules as the schedule page)
        from ..jobs import flows
        if schedule_enabled:
            act = next((v for v in src.versions if v.id == src.active_version_id), None)
            if src.mode == "SQL" and not (act and (act.validation or {}).get("status") == "VALID"):
                raise AppError("SQL_NOT_VALIDATED", 409, detail=f"{kind}: validate a SQL version before enabling the schedule")
        flows.update_flow("d0", {"enabled": bool(schedule_enabled)})
    return view(kind)


def record_validation(kind: str, vid: int, result: dict) -> dict:
    """Store the BigQuery validation of a version; activate it only when VALID."""
    cfg = config()
    src = getattr(cfg, _kind(kind))
    v = version(src, vid)
    v.validation = result
    if result.get("status") == "VALID":
        src.active_version_id = vid
    _save(cfg, f"{kind} SQL version {vid} validated: {result.get('status')}")
    return view(kind)


def restore(kind: str, vid: int) -> dict:
    """Re-activate an older version. Only a version that passed validation can be active; any other version is
    copied as a NEW version that must be validated first."""
    cfg = config()
    src = getattr(cfg, _kind(kind))
    v = version(src, vid)
    if (v.validation or {}).get("status") == "VALID":
        src.active_version_id = vid
        _save(cfg, f"{kind} SQL version {vid} restored as active")
        return {**view(kind), "restored": vid, "needs_validation": False}
    res = save_version(kind, v.sql, note=f"Khôi phục từ phiên bản {vid}")
    return {**res, "restored": vid, "needs_validation": True}


def snapshot(kind: str) -> dict:
    """What a job uses from start to end. TABLE mode -> {'mode': 'TABLE'}; SQL mode -> the active validated text.
    D0 (1.2.1): d0_feed.snapshot - also refused when the validation was made for another D-0 mapping / key."""
    if _kind(kind) == "d0":
        from . import d0_feed
        return d0_feed.snapshot()
    src = source(kind)
    if src.mode == "TABLE":
        return {"mode": "TABLE", "kind": kind, "key_columns": effective_keys(src),
                "key_duplicate_policy": src.key_duplicate_policy}
    active = next((v for v in src.versions if v.id == src.active_version_id), None)
    if active is None or (active.validation or {}).get("status") != "VALID":
        raise AppError("SQL_NOT_VALIDATED", 409, detail=f"{kind}: no validated SQL version")
    return {"mode": "SQL", "kind": kind, "version_id": active.id, "sha256": active.sha256, "sql": active.sql,
            "key_columns": effective_keys(src), "key_duplicate_policy": src.key_duplicate_policy, "taken_at": now_iso()}


def public_snapshot(snap: dict) -> dict:
    return {k: v for k, v in snap.items() if k != "sql"}
