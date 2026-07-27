#!/usr/bin/env bash
# Credential-free backup/restore drill using only synthetic rows and files.

set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="valor-backup-source-$$"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/valor-backup-smoke.XXXXXX")"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

docker run -d --name "$NAME" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=synthetic-only-password \
  -e POSTGRES_DB=valor \
  pgvector/pgvector:pg16 >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$NAME" psql -U postgres -d valor -Atqc \
      'SELECT 1' >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 1
done
[ "${READY:-false}" = "true" ] || { echo "synthetic source database did not become ready" >&2; exit 1; }

docker exec -i "$NAME" psql -v ON_ERROR_STOP=1 -U postgres -d valor >/dev/null <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE organizations (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  kind text NOT NULL,
  plan_tier text NOT NULL,
  status text NOT NULL
);
CREATE TABLE users (
  id uuid PRIMARY KEY,
  email text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  full_name text NOT NULL,
  email_verified boolean NOT NULL
);
CREATE TABLE documents (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), filename text NOT NULL);
CREATE TABLE analysis_runs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  workspace_id uuid NOT NULL REFERENCES organizations(id),
  status text NOT NULL,
  steps jsonb NOT NULL
);
CREATE TABLE analysis_jobs (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES analysis_runs(id),
  user_id uuid NOT NULL REFERENCES users(id),
  workspace_id uuid NOT NULL,
  status text NOT NULL
);
ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON analysis_runs
  USING (workspace_id = NULLIF(current_setting('app.current_workspace', true), '')::uuid)
  WITH CHECK (workspace_id = NULLIF(current_setting('app.current_workspace', true), '')::uuid);
INSERT INTO organizations VALUES (
  '00000000-0000-0000-0000-000000000004',
  'Synthetic smoke workspace',
  'synthetic-smoke',
  'personal',
  'free',
  'active'
);
INSERT INTO users VALUES (
  '00000000-0000-0000-0000-000000000001',
  'synthetic@example.test',
  'x',
  'Synthetic User',
  true
);
INSERT INTO documents VALUES (
  '00000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  'synthetic-record.txt'
);
INSERT INTO analysis_runs VALUES (
  '00000000-0000-0000-0000-000000000003',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000004',
  'completed',
  '[]'::jsonb
);
INSERT INTO analysis_jobs VALUES (
  '00000000-0000-0000-0000-000000000005',
  '00000000-0000-0000-0000-000000000003',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000004',
  'completed'
);
SQL

mkdir -p "$WORK_DIR/uploads/synthetic" "$WORK_DIR/backups"
printf 'synthetic-backup-canary\n' > "$WORK_DIR/uploads/synthetic/canary.txt"

VALOR_DB_CONTAINER="$NAME" \
VALOR_APP_CONTAINER="nonexistent-synthetic-app" \
VALOR_UPLOADS_SOURCE_DIR="$WORK_DIR/uploads" \
VALOR_BACKUP_LOCAL_DIR="$WORK_DIR/backups" \
VALOR_BACKUP_LOG="$WORK_DIR/backup.log" \
VALOR_BACKUP_SKIP_ENV=true \
VALOR_BACKUP_APP_VERSION=synthetic \
VALOR_BACKUP_RELEASE_ID=synthetic \
VALOR_BACKUP_RULE_VERSION=synthetic \
  "$ROOT/scripts/valor-backup.sh"

DB_DUMP="$(find "$WORK_DIR/backups" -name 'valor_db_*.dump' -print -quit)"
UPLOADS="$(find "$WORK_DIR/backups" -name 'valor_uploads_*.tar.gz' -print -quit)"
CHECKSUMS="$(find "$WORK_DIR/backups" -name 'valor_backup_*.sha256' -print -quit)"

# Prove archive validation fails before extraction when tar metadata could escape
# regular-file semantics. The restore verifier intentionally emits no member names.
mkdir -p "$WORK_DIR/unsafe"
ln -s synthetic/canary.txt "$WORK_DIR/unsafe/link"
UNSAFE_UPLOADS="$WORK_DIR/unsafe-uploads.tar.gz"
tar -C "$WORK_DIR/unsafe" -czf "$UNSAFE_UPLOADS" link
if "$ROOT/scripts/valor-restore-verify.sh" \
    --db-dump "$DB_DUMP" --uploads "$UNSAFE_UPLOADS" >/dev/null 2>&1; then
  echo "restore verifier accepted a synthetic symlink archive" >&2
  exit 1
fi

"$ROOT/scripts/valor-restore-verify.sh" \
  --db-dump "$DB_DUMP" \
  --uploads "$UPLOADS" \
  --checksums "$CHECKSUMS" \
  --expect-synthetic

# Exercise both remote-copy branches with a no-op CLI. In particular, stock
# macOS Bash 3.2 aborts under `set -u` when an empty array is expanded, so the
# no-endpoint case must be covered rather than inferred from syntax checking.
for REMOTE_CASE in no-endpoint custom-endpoint; do
  REMOTE_BACKUPS="$WORK_DIR/backups-$REMOTE_CASE"
  mkdir -p "$REMOTE_BACKUPS"
  if [ "$REMOTE_CASE" = "custom-endpoint" ]; then
    REMOTE_ENDPOINT="https://synthetic-object-store.invalid"
  else
    REMOTE_ENDPOINT=""
  fi
  VALOR_DB_CONTAINER="$NAME" \
  VALOR_APP_CONTAINER="nonexistent-synthetic-app" \
  VALOR_UPLOADS_SOURCE_DIR="$WORK_DIR/uploads" \
  VALOR_BACKUP_LOCAL_DIR="$REMOTE_BACKUPS" \
  VALOR_BACKUP_LOG="$WORK_DIR/backup-$REMOTE_CASE.log" \
  VALOR_BACKUP_SKIP_ENV=true \
  VALOR_BACKUP_REMOTE_URI="s3://synthetic-only/valor" \
  VALOR_BACKUP_S3_ENDPOINT="$REMOTE_ENDPOINT" \
  VALOR_AWS_BIN=/usr/bin/true \
  VALOR_BACKUP_APP_VERSION=synthetic \
  VALOR_BACKUP_RELEASE_ID=synthetic \
  VALOR_BACKUP_RULE_VERSION=synthetic \
    "$ROOT/scripts/valor-backup.sh" >/dev/null
  find "$REMOTE_BACKUPS" -name 'valor_backup_*.sha256' -print -quit | grep -q .
done

# If encryption is actually attempted, its failure is fatal even when the
# environment artifact was not configured as required. A partial set must not
# be published locally or remotely under an apparent success status.
mkdir -p "$WORK_DIR/fake-bin" "$WORK_DIR/backups-age-failure"
ln -s /usr/bin/false "$WORK_DIR/fake-bin/age"
printf 'synthetic-environment-only\n' > "$WORK_DIR/synthetic.env"
printf 'age1syntheticrecipientonly\n' > "$WORK_DIR/age-recipient.txt"
if PATH="$WORK_DIR/fake-bin:$PATH" \
  VALOR_DB_CONTAINER="$NAME" \
  VALOR_APP_CONTAINER="nonexistent-synthetic-app" \
  VALOR_UPLOADS_SOURCE_DIR="$WORK_DIR/uploads" \
  VALOR_BACKUP_LOCAL_DIR="$WORK_DIR/backups-age-failure" \
  VALOR_BACKUP_LOG="$WORK_DIR/backup-age-failure.log" \
  VALOR_ENV_SRC="$WORK_DIR/synthetic.env" \
  VALOR_BACKUP_AGE_RECIPIENT_FILE="$WORK_DIR/age-recipient.txt" \
  VALOR_BACKUP_APP_VERSION=synthetic \
  VALOR_BACKUP_RELEASE_ID=synthetic \
  VALOR_BACKUP_RULE_VERSION=synthetic \
    "$ROOT/scripts/valor-backup.sh" >/dev/null; then
  echo "backup accepted an attempted environment-encryption failure" >&2
  exit 1
fi
if find "$WORK_DIR/backups-age-failure" -type f -print -quit | grep -q .; then
  echo "backup published artifacts after environment-encryption failure" >&2
  exit 1
fi
