#!/usr/bin/env bash
# Real-Postgres integration tier for valor-ops.
#
# The fast unit suite runs on SQLite, which has NO Row-Level Security, no SET LOCAL
# GUCs, and no triggers — so the RLS / tenancy layer (the defense-in-depth that keeps
# one veteran's C-file from ever crossing to another) is invisible to it. This script
# spins the PROD database image (pgvector/pgvector:pg16), runs the app's real init_db()
# against it as a NOBYPASSRLS role exactly like production, and runs the integration
# tests in tests/integration/ that prove RLS is genuinely enforced.
#
# Usage:  scripts/test-pg.sh [extra pytest args]
# Requires: docker + the backend .venv (make the venv the usual way first).
set -euo pipefail

NAME="valor-pg-it"
PORT="${VALOR_PG_IT_PORT:-55440}"
PW="itpass"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "▸ starting throwaway Postgres 16 (pgvector) on :$PORT ..."
docker run -d --name "$NAME" \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=valor \
  -p "$PORT:5432" pgvector/pgvector:pg16 >/dev/null

echo -n "▸ waiting for ready"
for _ in $(seq 1 60); do
  if docker exec "$NAME" psql -U postgres -d valor -Atqc \
      'SELECT 1' >/dev/null 2>&1; then ok=1; break; fi
  echo -n "."; sleep 1
done
echo
[ "${ok:-}" = 1 ] || { echo "✗ Postgres never became ready"; exit 1; }

export VALOR_PG_SUPERUSER_DSN="postgresql+asyncpg://postgres:${PW}@localhost:${PORT}/valor"
cd "$HERE/backend"
echo "▸ running tests/integration against real Postgres ..."
.venv/bin/python -m pytest tests/integration -q -p no:cacheprovider "$@"
