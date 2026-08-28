#!/bin/sh
# Regenerate the dashboard snapshot, then serve it while refreshing on an interval.
set -eu

REFRESH="${DASHBOARD_REFRESH_SECONDS:-600}"
SRC_DB="/app/data/factors.db"

# The data dir is mounted read-only and the db is in WAL mode, so SQLite cannot
# open it in place (it needs to create -shm/-wal). Use immutable=1: SQLite then
# assumes the file never changes mid-connection and skips -shm/-wal entirely.
# Small staleness window vs. the host writer is acceptable for a snapshot view;
# each refresh cycle opens a fresh connection, picking up the latest state.
DB_URI="file:${SRC_DB}?mode=ro&immutable=1"

generate() {
  python3 core/tools/generate_factor_dashboard.py --db "$DB_URI" --output /app/serving/factor_dashboard.html || {
    echo "[entrypoint] generation failed; keeping previous snapshot"
    return 1
  }
}

mkdir -p /app/serving
export DASHBOARD_HTML="/app/serving/factor_dashboard.html"

# First generation must succeed before we start serving; retry a few times.
i=0
until generate; do
  i=$((i + 1))
  if [ "$i" -ge 5 ]; then
    echo "[entrypoint] initial generation failed 5 times, starting server anyway"
    break
  fi
  sleep 5
done

# Background refresh loop: snapshot stays fresh while the host research loop
# keeps writing to the mounted factors.db.
(
  while true; do
    sleep "$REFRESH"
    generate || true
  done
) &

exec python3 /app/serve.py
