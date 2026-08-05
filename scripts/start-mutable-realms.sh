#!/usr/bin/env bash
# Boot-time launcher for the Mutable Realms application server.
#
# Runs from the container entrypoint alongside the Hermes agent: applies
# idempotent migrations, seeds the deterministic ward world when absent, builds
# the frontend bundle only when it is missing, then serves the application on
# the configured port (default 8790). Safe to run on every container start.
set -euo pipefail

REPO_DIR="${MUTABLE_REALMS_REPO_DIR:-/myfiles/workspace/mutable-realms}"
export MUTABLE_REALMS_DB_PATH="${MUTABLE_REALMS_DB_PATH:-/myfiles/state/mutable-realms/world.sqlite3}"
export MUTABLE_REALMS_PORT="${MUTABLE_REALMS_PORT:-8790}"

export UV_PROJECT_ENVIRONMENT="/opt/mutable-realms-venv"

cd "$REPO_DIR"

echo "[mutable-realms] migrating database at $MUTABLE_REALMS_DB_PATH"
uv run --no-sync python -m backend.cli migrate

echo "[mutable-realms] seeding deterministic ward world if absent"
uv run --no-sync python -m backend.cli seed

if [ ! -f frontend/dist/index.html ]; then
  echo "[mutable-realms] building frontend bundle"
  if [ -x node_modules/.bin/vite ]; then
    npm run frontend-build
  else
    echo "[mutable-realms] frontend toolchain unavailable; serving API only"
  fi
fi

echo "[mutable-realms] serving on 0.0.0.0:$MUTABLE_REALMS_PORT"
exec uv run --no-sync uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port "$MUTABLE_REALMS_PORT" \
  --workers 1
