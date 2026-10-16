#!/usr/bin/env bash
# Switch the VPS back to an installed release:  sudo bash rollback.sh [<release-name>]   (default: the previous one)
# Code only: the database is NOT restored. Refused when the database schema is newer than the target release
# supports (then restore a backup first, docs/TRIEN-KHAI-VPS.md). An online backup is taken before switching.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/demandforecast}
ENV_FILE=${ENV_FILE:-/etc/demandforecast/app.env}
SERVICE=${SERVICE:-demandforecast}

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || die "run as root (sudo)"
set -a; . "$ENV_FILE"; set +a
PORT=${DF_PORT:-8765}
if [[ -n "${1:-}" ]]; then target="$APP_DIR/releases/$1"; else target=$(readlink -f "$APP_DIR/previous" 2>/dev/null || true); fi
[[ -n "$target" && -d "$target" ]] || die "no such release; installed: $(ls "$APP_DIR/releases" | tr '\n' ' ')"
cur=$(readlink -f "$APP_DIR/current" 2>/dev/null || true)
[[ "$target" != "$cur" ]] || die "$(basename "$target") is already current"
version=$(tr -d '[:space:]' < "$target/VERSION")

db="${DF_DATA_DIR:?DF_DATA_DIR missing in $ENV_FILE}/db/app.db"
if [[ -f "$db" ]]; then
    read -r dbv tv < <("$target/.venv/bin/python" - "$db" "$target/backend/app/migrations" <<'PY'
import pathlib, sqlite3, sys
c = sqlite3.connect(pathlib.Path(sys.argv[1]).as_uri() + "?mode=ro", uri=True)
v = c.execute("select coalesce(max(version), 0) from schema_migrations").fetchone()[0]
print(v, max(int(p.name.split("_")[0]) for p in pathlib.Path(sys.argv[2]).glob("*.sql")))
PY
)
    (( dbv <= tv )) || die "database schema $dbv is newer than $(basename "$target") supports ($tv): restore a backup first"
fi

health() { curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true; }
if systemctl is-active --quiet "$SERVICE" && [[ -n "$(health)" ]]; then
    b=$(curl -fsS --max-time 600 -X POST -H "X-DF-Client: web" "http://127.0.0.1:$PORT/api/system/backups") \
        || die "online backup failed: nothing switched"
    echo "OK   backup $b"
fi
ln -sfn "$target" "$APP_DIR/current.new" && mv -T "$APP_DIR/current.new" "$APP_DIR/current"
[[ -n "$cur" ]] && ln -sfn "$cur" "$APP_DIR/previous"
systemctl restart "$SERVICE"
for _ in $(seq 1 30); do
    sleep 2
    h=$(health)
    if [[ "$h" == *"\"ok\":true"* && "$h" == *"\"version\":\"$version\""* ]]; then
        echo "DONE $(basename "$target") (version $version) is live"; exit 0
    fi
done
journalctl -u "$SERVICE" -n 40 --no-pager >&2 || true
die "$(basename "$target") did not answer the health check"
