#!/usr/bin/env bash
# One-time preparation of a Linux (systemd) VPS:  sudo bash install-server.sh
# Creates the service user, the folders (code / data / configuration kept apart), the configuration file from the
# example (no secret in it), the systemd unit (enabled, NOT started: there is no release yet) and the server copy of
# deploy.sh / rollback.sh. Idempotent: an existing configuration file is never overwritten.
#   /opt/demandforecast/releases/<release>/   code + venv of each release (read-only for the service)
#   /opt/demandforecast/current, previous     symlinks
#   /opt/demandforecast/bin/                  deploy.sh, rollback.sh
#   /var/lib/demandforecast/{data,logs,backups,reports}   runtime data (DB, models, backups), owned by the service user
#   /etc/demandforecast/app.env               configuration (+ the Google credential file, chmod 640)
set -euo pipefail

APP_DIR=/opt/demandforecast
DATA_ROOT=/var/lib/demandforecast
CONF_DIR=/etc/demandforecast
APP_USER=demandforecast
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

[[ $(id -u) -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required" >&2; exit 1; }
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_ROOT" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 755 "$APP_DIR" "$APP_DIR/releases" "$APP_DIR/bin"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$DATA_ROOT" "$DATA_ROOT/data" "$DATA_ROOT/logs" "$DATA_ROOT/backups" "$DATA_ROOT/reports"
install -d -m 750 -o root -g "$APP_USER" "$CONF_DIR"
if [[ ! -f "$CONF_DIR/app.env" ]]; then
    install -m 640 -o root -g "$APP_USER" "$here/app.env.example" "$CONF_DIR/app.env"
    echo "created $CONF_DIR/app.env: set DF_ALLOWED_HOSTS (domain) and the Google credential before the first deploy"
fi
install -m 755 "$here/deploy.sh" "$here/rollback.sh" "$APP_DIR/bin/"
install -m 644 "$here/demandforecast.service" /etc/systemd/system/demandforecast.service
systemctl daemon-reload
systemctl enable demandforecast.service >/dev/null

echo "== checks"
for c in "${PYTHON_BIN:-python3.14}" curl tar sha256sum; do
    command -v "$c" >/dev/null && echo "OK   $c" || echo "MISSING $c"
done
ldconfig -p 2>/dev/null | grep -q libgomp && echo "OK   libgomp (LightGBM)" || echo "MISSING libgomp (LightGBM): e.g. apt install libgomp1"
echo "Next: edit $CONF_DIR/app.env, then  sudo bash $APP_DIR/bin/deploy.sh <artifact.tar.gz> <sha256>"
