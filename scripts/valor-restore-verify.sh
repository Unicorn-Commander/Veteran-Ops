#!/usr/bin/env bash
# Restore a backup into a disposable PostgreSQL container and validate critical
# schema/RLS/upload invariants without printing veteran rows or file names.

set -euo pipefail
umask 077

DB_DUMP=""
UPLOADS=""
CHECKSUMS=""
IMAGE="${VALOR_RESTORE_IMAGE:-pgvector/pgvector:pg16}"
EXPECT_SYNTHETIC=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --db-dump) DB_DUMP="$2"; shift 2 ;;
    --uploads) UPLOADS="$2"; shift 2 ;;
    --checksums) CHECKSUMS="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    --expect-synthetic) EXPECT_SYNTHETIC=true; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -f "$DB_DUMP" ] || { echo "database dump is required" >&2; exit 2; }
[ -f "$UPLOADS" ] || { echo "uploads archive is required" >&2; exit 2; }

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

if [ -n "$CHECKSUMS" ]; then
  [ -f "$CHECKSUMS" ] || { echo "checksum inventory not found" >&2; exit 2; }
  CHECKSUM_DIR="$(cd "$(dirname "$CHECKSUMS")" && pwd)"
  DB_CHECKED=false
  UPLOADS_CHECKED=false
  while read -r expected filename; do
    filename="${filename#\*}"
    case "$filename" in ""|*/*|..*) echo "unsafe checksum entry" >&2; exit 1 ;; esac
    [ "${#expected}" -eq 64 ] || { echo "invalid checksum entry" >&2; exit 1; }
    case "$expected" in *[!0-9a-fA-F]*) echo "invalid checksum entry" >&2; exit 1 ;; esac
    candidate="${CHECKSUM_DIR}/${filename}"
    [ -f "$candidate" ] || { echo "checksum artifact missing" >&2; exit 1; }
    [ "$(checksum "$candidate")" = "$expected" ] || {
      echo "checksum validation failed" >&2; exit 1;
    }
    [ "$filename" = "$(basename "$DB_DUMP")" ] && DB_CHECKED=true
    [ "$filename" = "$(basename "$UPLOADS")" ] && UPLOADS_CHECKED=true
  done < "$CHECKSUMS"
  [ "$DB_CHECKED" = "true" ] && [ "$UPLOADS_CHECKED" = "true" ] || {
    echo "checksum inventory does not cover the selected restore artifacts" >&2
    exit 1
  }
fi

UNSAFE_ENTRY="$(tar -tzf "$UPLOADS" | awk '/^\// || /(^|\/)\.\.($|\/)/ { print "unsafe"; exit }')"
[ -z "$UNSAFE_ENTRY" ] || { echo "uploads archive contains an unsafe path" >&2; exit 1; }
UNSAFE_TYPE="$(tar -tvzf "$UPLOADS" | awk '
  { type=substr($1,1,1) }
  type != "-" && type != "d" { print "unsafe"; exit }
')"
[ -z "$UNSAFE_TYPE" ] || {
  echo "uploads archive contains a link, device, or other non-regular member" >&2
  exit 1
}

NAME="valor-restore-verify-$$"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/valor-restore-verify.XXXXXX")"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

docker run -d --name "$NAME" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=restore-only-password \
  -e POSTGRES_DB=valor_restore \
  "$IMAGE" >/dev/null

for _ in $(seq 1 60); do
  # pg_isready only proves that the server is accepting connections; during
  # first boot it can succeed before POSTGRES_DB has created valor_restore.
  if docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
      'SELECT 1' >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 1
done
[ "${READY:-false}" = "true" ] || { echo "restore database did not become ready" >&2; exit 1; }

docker exec -i "$NAME" pg_restore -U postgres -d valor_restore \
  --no-owner --no-acl --exit-on-error < "$DB_DUMP" >/dev/null

CRITICAL_COUNT="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SELECT count(*) FROM pg_class WHERE relkind='r' AND relname IN ('organizations','users','documents','analysis_runs','analysis_jobs')")"
[ "$CRITICAL_COUNT" = "5" ] || { echo "restore is missing critical tables" >&2; exit 1; }

RLS_STATE="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SELECT relrowsecurity::text || '|' || relforcerowsecurity::text FROM pg_class WHERE relname='analysis_runs'")"
[ "$RLS_STATE" = "true|true" ] || { echo "analysis_runs FORCE-RLS was not restored" >&2; exit 1; }

POLICY_COUNT="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid WHERE c.relname='analysis_runs' AND p.polname='workspace_isolation'")"
[ "$POLICY_COUNT" = "1" ] || { echo "analysis_runs workspace policy was not restored" >&2; exit 1; }

# Catalog flags are not enough: create two synthetic tenants only inside this
# disposable restore, assume a NOBYPASSRLS runtime role, and prove it sees exactly
# one tenant at a time and no rows under a third workspace. No row content is output.
docker exec -i "$NAME" psql -v ON_ERROR_STOP=1 -U postgres -d valor_restore >/dev/null <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='valor_restore_probe') THEN
    CREATE ROLE valor_restore_probe NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO valor_restore_probe;
GRANT SELECT ON analysis_runs TO valor_restore_probe;
INSERT INTO organizations (id,name,slug,kind,plan_tier,status) VALUES
  ('ffffffff-0000-0000-0000-000000000001','Synthetic restore A','restore-probe-a','personal','free','active'),
  ('ffffffff-0000-0000-0000-000000000002','Synthetic restore B','restore-probe-b','personal','free','active');
INSERT INTO users (id,email,password_hash,full_name,email_verified) VALUES
  ('ffffffff-0000-0000-0000-000000000011','restore-a@example.test','x','Synthetic A',true),
  ('ffffffff-0000-0000-0000-000000000012','restore-b@example.test','x','Synthetic B',true);
INSERT INTO analysis_runs (id,user_id,workspace_id,status,steps) VALUES
  ('ffffffff-0000-0000-0000-000000000021','ffffffff-0000-0000-0000-000000000011','ffffffff-0000-0000-0000-000000000001','completed','[]'::jsonb),
  ('ffffffff-0000-0000-0000-000000000022','ffffffff-0000-0000-0000-000000000012','ffffffff-0000-0000-0000-000000000002','completed','[]'::jsonb);
SQL

VISIBLE_A="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SET ROLE valor_restore_probe; SELECT set_config('app.current_workspace','ffffffff-0000-0000-0000-000000000001',false); SELECT count(*) FROM analysis_runs WHERE id IN ('ffffffff-0000-0000-0000-000000000021','ffffffff-0000-0000-0000-000000000022');" | tail -1)"
VISIBLE_B="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SET ROLE valor_restore_probe; SELECT set_config('app.current_workspace','ffffffff-0000-0000-0000-000000000002',false); SELECT count(*) FROM analysis_runs WHERE id IN ('ffffffff-0000-0000-0000-000000000021','ffffffff-0000-0000-0000-000000000022');" | tail -1)"
VISIBLE_NONE="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SET ROLE valor_restore_probe; SELECT set_config('app.current_workspace','ffffffff-0000-0000-0000-000000000099',false); SELECT count(*) FROM analysis_runs WHERE id IN ('ffffffff-0000-0000-0000-000000000021','ffffffff-0000-0000-0000-000000000022');" | tail -1)"
[ "$VISIBLE_A" = "1" ] && [ "$VISIBLE_B" = "1" ] && [ "$VISIBLE_NONE" = "0" ] || {
  echo "runtime NOBYPASSRLS tenant-isolation probe failed" >&2
  exit 1
}

mkdir -p "$WORK_DIR/uploads"
tar -xzf "$UPLOADS" -C "$WORK_DIR/uploads"
UPLOAD_FILE_COUNT="$(find "$WORK_DIR/uploads" -type f | wc -l | tr -d ' ')"
if [ "$EXPECT_SYNTHETIC" = "true" ]; then
  SENTINEL="$WORK_DIR/uploads/synthetic/canary.txt"
  [ -f "$SENTINEL" ] || { echo "synthetic upload sentinel missing" >&2; exit 1; }
  [ "$(tr -d '\r\n' < "$SENTINEL")" = "synthetic-backup-canary" ] || {
    echo "synthetic upload sentinel mismatch" >&2; exit 1;
  }
fi

TABLE_COUNT="$(docker exec "$NAME" psql -U postgres -d valor_restore -Atqc \
  "SELECT count(*) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace")"
printf 'restore verification passed: tables=%s upload_files=%s force_rls=ok\n' \
  "$TABLE_COUNT" "$UPLOAD_FILE_COUNT"
