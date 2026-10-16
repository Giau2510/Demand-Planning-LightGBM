"""SQLite persistence with versioned migrations and a pre-migration backup."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .timeutil import now_iso, now_utc

log = logging.getLogger("df.db")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_init_lock = threading.Lock()


class MigrationError(RuntimeError):
    pass


def connect(path: Path | None = None, create: bool = False) -> sqlite3.Connection:
    target = Path(path) if path else paths.db_path()
    if not create and not target.exists():
        # sqlite3 would silently create an empty database here - never let that happen
        raise paths.StorageError("STORAGE_NOT_FOUND", f"database not found: {target}")
    conn = sqlite3.connect(str(target), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection | None = None):
    """Run a block inside one IMMEDIATE transaction (all-or-nothing)."""
    own = conn is None
    c = conn or connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        else:
            c.execute("COMMIT")
    finally:
        if own:
            c.close()


@contextmanager
def read():
    c = connect()
    try:
        yield c
    finally:
        c.close()


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def available_migrations() -> list[tuple[int, Path]]:
    out = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        out.append((int(p.name.split("_", 1)[0]), p))
    return out


def current_version(conn) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
                 "name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    r = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return r[0] or 0


def migrate(path: Path | None = None) -> dict:
    """Apply pending migrations. Takes a backup first when the DB already holds data."""
    with _init_lock:
        if path is None:
            paths.ensure_storage()   # raises instead of creating a database in an unexpected place
        target = path or paths.db_path()
        existed = target.exists() and target.stat().st_size > 0
        conn = connect(target, create=True)
        try:
            cur = current_version(conn)
            migs = available_migrations()
            latest = migs[-1][0] if migs else 0
            if cur > latest:
                raise MigrationError(
                    f"Database schema version {cur} is newer than this app supports ({latest}). "
                    "Install the newer app version or restore a backup.")
            pending = [(v, p) for v, p in migs if v > cur]
            backup_file = None
            if pending and existed and cur > 0:
                from .backup import backup_database
                backup_file = backup_database(reason=f"pre-migration-v{cur}")
            for v, p in pending:
                sql = p.read_text(encoding="utf-8")
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for stmt in _split_sql(sql):
                        conn.execute(stmt)
                    conn.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                                 (v, p.name, now_iso()))
                    conn.execute("COMMIT")
                except Exception as e:  # pragma: no cover - exercised via tests with a bad migration
                    conn.execute("ROLLBACK")
                    raise MigrationError(f"Migration {p.name} failed: {e}. Database left at version "
                                         f"{current_version(conn)}; backup: {backup_file}") from e
                log.info("migration applied", extra={"ctx": {"version": v, "name": p.name}})
            if path is None:
                paths.lock_storage_config()
            return {"from": cur, "to": current_version(conn), "applied": [p.name for _, p in pending],
                    "backup": str(backup_file) if backup_file else None}
        finally:
            conn.close()


def _split_sql(sql: str) -> list[str]:
    """Split a migration script into statements, keeping CREATE TRIGGER ... END; blocks intact."""
    out, buf, in_trigger = [], [], False
    for line in sql.splitlines():
        s = line.strip()
        if not buf and (not s or s.startswith("--")):
            continue
        buf.append(line)
        up = s.upper()
        if up.startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if up.endswith("END;"):
                out.append("\n".join(buf))
                buf, in_trigger = [], False
        elif s.endswith(";"):
            out.append("\n".join(buf))
            buf = []
    if buf and "".join(buf).strip():
        out.append("\n".join(buf))
    return out


def audit(conn, action: str, entity_type: str | None = None, entity_id: str | None = None,
          details: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_log(at, action, entity_type, entity_id, details_json) VALUES (?,?,?,?,?)",
                 (now_iso(), action, entity_type, entity_id, json.dumps(details or {}, default=str)))


def alert(conn, level: str, code: str, params: dict | None = None, entity_type: str | None = None,
          entity_id: str | None = None) -> None:
    conn.execute("INSERT INTO alerts(created_at, level, code, params_json, entity_type, entity_id) "
                 "VALUES (?,?,?,?,?,?)",
                 (now_iso(), level, code, json.dumps(params or {}, default=str), entity_type, entity_id))


def new_id(prefix: str) -> str:
    import secrets
    return f"{prefix}-{now_utc().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"


class ConsistencyError(RuntimeError):
    """Raised inside a transaction when a data invariant would be broken; the transaction rolls back."""


def fk_violations(conn, table: str | None = None) -> list[tuple]:
    sql = f"PRAGMA foreign_key_check({table})" if table else "PRAGMA foreign_key_check"
    return [tuple(r) for r in conn.execute(sql).fetchall()]


def health_check(conn, quick: bool = True) -> dict:
    """Read-only integrity + foreign-key check (safe on the live database)."""
    integ = conn.execute("PRAGMA quick_check" if quick else "PRAGMA integrity_check").fetchall()
    fks = fk_violations(conn)
    return {"integrity": "ok" if [r[0] for r in integ] == ["ok"] else [r[0] for r in integ][:20],
            "foreign_key_violations": len(fks), "foreign_key_examples": [list(x) for x in fks[:10]]}
