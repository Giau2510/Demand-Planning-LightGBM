#!/usr/bin/env bash
# Deploy ONE release artifact on the Linux VPS:  sudo bash deploy.sh <DemandForecast-...-linux-src.tar.gz> <sha256>
#
#  1. SHA-256 of the artifact must equal the published one
#  2. unpack to /opt/demandforecast/releases/<name>/ (a release directory is never overwritten)
#  3. venv of that release from the pinned lock (binary wheels only) + runtime self-test (imports, LightGBM)
#  4. schema guard: refuse a release older than the database schema
#  5. online backup through the RUNNING app (POST /api/system/backups), as on Windows
#  6. switch the 'current' symlink, restart the service (the app applies its migrations at start)
#  7. health check: /api/health answers with the new version; otherwise switch back to the previous release
#  8. only then: keep the newest $KEEP_RELEASES releases, never the current or the previous one removed
# Data, configuration and credentials live outside the release directories and are never touched here.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/demandforecast}
ENV_FILE=${ENV_FILE:-/etc/demandforecast/app.env}
SERVICE=${SERVICE:-demandforecast}
APP_USER=${APP_USER:-demandforecast}
PYTHON_BIN=${PYTHON_BIN:-python3.14}
KEEP_RELEASES=${KEEP_RELEASES:-3}

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || die "run as root (sudo)"
artifact=${1:-}; expected=${2:-}
[[ -f "$artifact" && -n "$expected" ]] || die "usage: deploy.sh <artifact.tar.gz> <expected-sha256>"
[[ -f "$ENV_FILE" ]] || die "$ENV_FILE missing: run install-server.sh first"
command -v "$PYTHON_BIN" >/dev/null || die "$PYTHON_BIN not found (see docs/TRIEN-KHAI-VPS.md, Python 3.14)"
set -a; . "$ENV_FILE"; set +a
PORT=${DF_PORT:-8765}

# 1. integrity
actual=$(sha256sum "$artifact" | cut -d' ' -f1)
[[ "${actual,,}" == "${expected,,}" ]] || die "SHA-256 mismatch: $actual (expected $expected)"
echo "OK   SHA-256 $actual"

# 2. unpack
name=$(basename "$artifact" .tar.gz)
dest="$APP_DIR/releases/$name"
[[ ! -e "$dest" ]] || die "$dest exists already (deployed before?). Use rollback.sh $name to switch to it."
tmp=$(mktemp -d "$APP_DIR/releases/.incoming.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
tar -xzf "$artifact" -C "$tmp"
[[ -f "$tmp/$name/VERSION" && -d "$tmp/$name/backend/app" && -f "$tmp/$name/web/index.html" ]] || die "unexpected artifact layout"
mv "$tmp/$name" "$dest"
version=$(tr -d '[:space:]' < "$dest/VERSION")
echo "OK   unpacked $name (version $version)"

# 3. runtime of this release
"$PYTHON_BIN" -m venv "$dest/.venv"
"$dest/.venv/bin/pip" install --quiet --disable-pip-version-check --no-compile --only-binary=:all: \
    -r "$dest/backend/requirements.lock.txt"
(cd "$dest/backend" && "$dest/.venv/bin/python" -B -c "import lightgbm, numpy as np, pandas, fastapi, google.cloud.bigquery, app
X = np.random.rand(200, 3); b = lightgbm.train({'verbose': -1}, lightgbm.Dataset(X, X[:, 0]), 5)
assert app.__version__ == '$version', app.__version__
print('OK   runtime: app', app.__version__, 'lightgbm', lightgbm.__version__, b.predict(X[:1]).shape)")
chown -R root:root "$dest"; chmod -R go-w "$dest"

# 4. schema guard (read-only)
db="${DF_DATA_DIR:?DF_DATA_DIR missing in $ENV_FILE}/db/app.db"
if [[ -f "$db" ]]; then
    read -r dbv newv < <("$dest/.venv/bin/python" - "$db" "$dest/backend/app/migrations" <<'PY'
import pathlib, sqlite3, sys
c = sqlite3.connect(pathlib.Path(sys.argv[1]).as_uri() + "?mode=ro", uri=True)
v = c.execute("select coalesce(max(version), 0) from schema_migrations").fetchone()[0]
print(v, max(int(p.name.split("_")[0]) for p in pathlib.Path(sys.argv[2]).glob("*.sql")))
PY
)
    (( dbv <= newv )) || die "database schema $dbv is newer than $name supports ($newv): not deployed"
    echo "OK   schema: database $dbv, release supports up to $newv"
fi

# 5. online backup by the running app (first deployment: nothing to back up)
health() { curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true; }
if systemctl is-active --quiet "$SERVICE" && [[ -n "$(health)" ]]; then
    b=$(curl -fsS --max-time 600 -X POST -H "X-DF-Client: web" "http://127.0.0.1:$PORT/api/system/backups") \
        || die "online backup failed: nothing switched"
    echo "OK   backup $b"
elif [[ -f "$db" ]]; then
    die "a database exists but the app is not running: start it (systemctl start $SERVICE) for the online backup first"
fi

# 6. switch + restart
prev=$(readlink -f "$APP_DIR/current" 2>/dev/null || true)
ln -sfn "$dest" "$APP_DIR/current.new" && mv -T "$APP_DIR/current.new" "$APP_DIR/current"
[[ -n "$prev" && "$prev" != "$dest" ]] && ln -sfn "$prev" "$APP_DIR/previous"
systemctl restart "$SERVICE"

# 7. health check (version must be the new one)
ok=""
for _ in $(seq 1 30); do
    sleep 2
    h=$(health)
    if [[ "$h" == *"\"ok\":true"* && "$h" == *"\"version\":\"$version\""* ]]; then ok=1; break; fi
done
if [[ -z "$ok" ]]; then
    echo "FAILED health check of $name; journal:" >&2
    journalctl -u "$SERVICE" -n 40 --no-pager >&2 || true
    if [[ -n "$prev" ]]; then
        ln -sfn "$prev" "$APP_DIR/current.new" && mv -T "$APP_DIR/current.new" "$APP_DIR/current"
        systemctl restart "$SERVICE"
        echo "Switched back to $(basename "$prev"). If $name applied a migration, restore the backup above (docs/TRIEN-KHAI-VPS.md)." >&2
    fi
    exit 1
fi
echo "OK   $name answers /api/health with version $version"
install -m 755 "$dest"/scripts/vps/*.sh "$APP_DIR/bin/"          # tools of the live release

# 8. retention: newest $KEEP_RELEASES, never current / previous
keep_cur=$(readlink -f "$APP_DIR/current"); keep_prev=$(readlink -f "$APP_DIR/previous" 2>/dev/null || true)
mapfile -t all < <(find "$APP_DIR/releases" -mindepth 1 -maxdepth 1 -type d ! -name '.incoming.*' -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
for i in "${!all[@]}"; do
    d=${all[$i]}
    if (( i >= KEEP_RELEASES )) && [[ "$d" != "$keep_cur" && "$d" != "$keep_prev" ]]; then
        rm -rf -- "$d" && echo "pruned old release $(basename "$d")"
    fi
done
echo "DONE $name is live. Rollback: sudo bash $APP_DIR/bin/rollback.sh"
