#!/usr/bin/env bash
# Create locally verified Valor-Ops database/upload backups. Offsite upload is
# optional and uses the standard AWS credential chain; this file contains no secrets.

set -uo pipefail
umask 077

CONFIG_FILE="${VALOR_BACKUP_CONFIG:-${HOME}/.config/valor-ops/backup.env}"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/valor-backup-${TIMESTAMP}.XXXXXX")"
LOCAL_KEEP_DIR="${VALOR_BACKUP_LOCAL_DIR:-${HOME}/backups/valor-ops}"
LOG="${VALOR_BACKUP_LOG:-${HOME}/logs/valor-backup.log}"
DB_CONTAINER="${VALOR_DB_CONTAINER:-valor-ops-db}"
APP_CONTAINER="${VALOR_APP_CONTAINER:-valor-ops-backend}"
DB_NAME="${VALOR_DB_NAME:-valor}"
DB_USER="${VALOR_DB_USER:-postgres}"
UPLOADS_PATH="${VALOR_UPLOADS_PATH:-/app/uploads}"
UPLOADS_SOURCE_DIR="${VALOR_UPLOADS_SOURCE_DIR:-}"
ENV_SRC="${VALOR_ENV_SRC:-/srv/veteran-ops/valor-ops/infrastructure/.env}"
REMOTE_URI="${VALOR_BACKUP_REMOTE_URI:-}"
S3_ENDPOINT="${VALOR_BACKUP_S3_ENDPOINT:-}"
AWS_BIN="${VALOR_AWS_BIN:-$(command -v aws 2>/dev/null || true)}"

mkdir -p "$LOCAL_KEEP_DIR" "$(dirname "$LOG")"
chmod 700 "$LOCAL_KEEP_DIR"
touch "$LOG"
chmod 600 "$LOG"
trap 'rm -rf "$BACKUP_DIR"' EXIT

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
file_size() { wc -c < "$1" | tr -d ' '; }
checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

FAILED=0
ARTIFACTS=()
log "=== Valor-Ops backup starting ==="

DB_FILE="${BACKUP_DIR}/valor_db_${TIMESTAMP}.dump"
log "Creating custom-format PostgreSQL dump..."
if docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
    --no-owner --no-acl --format=custom --compress=6 > "$DB_FILE" 2>>"$LOG"; then
  DB_BYTES="$(file_size "$DB_FILE")"
  if [ "$DB_BYTES" -lt 1024 ] || ! docker exec -i "$DB_CONTAINER" \
      pg_restore --list < "$DB_FILE" >/dev/null 2>>"$LOG"; then
    log "ERROR: database dump failed structural validation; artifact withheld"
    FAILED=1
  else
    ARTIFACTS+=("$DB_FILE")
    log "Database dump validated (${DB_BYTES} bytes)"
  fi
else
  log "ERROR: pg_dump failed"
  FAILED=1
fi

UPLOAD_FILE="${BACKUP_DIR}/valor_uploads_${TIMESTAMP}.tar.gz"
log "Creating uploads archive..."
if [ -n "$UPLOADS_SOURCE_DIR" ]; then
  tar -C "$UPLOADS_SOURCE_DIR" -czf "$UPLOAD_FILE" . 2>>"$LOG"
  UPLOAD_RESULT=$?
else
  docker exec "$APP_CONTAINER" tar -C "$UPLOADS_PATH" -czf - . \
    > "$UPLOAD_FILE" 2>>"$LOG"
  UPLOAD_RESULT=$?
fi
if [ "$UPLOAD_RESULT" -eq 0 ] && tar -tzf "$UPLOAD_FILE" >/dev/null 2>>"$LOG"; then
  ARTIFACTS+=("$UPLOAD_FILE")
  log "Uploads archive validated ($(file_size "$UPLOAD_FILE") bytes)"
else
  log "ERROR: uploads archive failed structural validation; artifact withheld"
  FAILED=1
fi

ENV_ARTIFACT="none"
if [ "${VALOR_BACKUP_SKIP_ENV:-false}" != "true" ]; then
  AGE_RECIPIENT_FILE="${VALOR_BACKUP_AGE_RECIPIENT_FILE:-${HOME}/.config/valor-ops/backup-age-recipient.txt}"
  if [ -f "$ENV_SRC" ] && [ -f "$AGE_RECIPIENT_FILE" ] && command -v age >/dev/null 2>&1; then
    ENV_FILE="${BACKUP_DIR}/valor_env_${TIMESTAMP}.env.age"
    if age -r "$(tr -d '\r\n' < "$AGE_RECIPIENT_FILE")" \
        -o "$ENV_FILE" "$ENV_SRC" 2>>"$LOG"; then
      ARTIFACTS+=("$ENV_FILE")
      ENV_ARTIFACT="$(basename "$ENV_FILE")"
      log "Encrypted environment backup created"
    else
      # Once all prerequisites are present, an encryption attempt must never be
      # treated as an optional warning: publishing the remaining set could leave
      # operators believing the environment was protected when it was not.
      log "ERROR: environment encryption failed"
      FAILED=1
    fi
  else
    log "WARN: encrypted environment backup skipped (source, recipient, or age missing)"
    [ "${VALOR_BACKUP_REQUIRE_ENV:-false}" = "true" ] && FAILED=1
  fi
fi

# Never publish a manifest/checksum marker for an incomplete required set. Optional
# environment encryption may remain `none`; when it is required, its failure set
# FAILED above and aborts the entire set here.
if [ "$FAILED" -ne 0 ]; then
  log "ERROR: required artifact validation failed; publishing no backup set"
  exit 1
fi

APP_VERSION="${VALOR_BACKUP_APP_VERSION:-unknown}"
RELEASE_ID="${VALOR_BACKUP_RELEASE_ID:-unknown}"
RULE_VERSION="${VALOR_BACKUP_RULE_VERSION:-unknown}"
if docker inspect "$APP_CONTAINER" >/dev/null 2>&1; then
  RELEASE_LINE="$(docker exec "$APP_CONTAINER" python -c \
    'from app import __version__; from app.release import release_inventory; r=release_inventory(); print(f"{__version__}|{r[\"release_id\"]}|{r[\"rule_version\"]}")' \
    2>/dev/null || true)"
  if [ -n "$RELEASE_LINE" ]; then
    IFS='|' read -r APP_VERSION RELEASE_ID RULE_VERSION <<< "$RELEASE_LINE"
  fi
fi

MANIFEST_FILE="${BACKUP_DIR}/valor_backup_${TIMESTAMP}.manifest"
printf '%s\n' \
  "format_version=1" \
  "created_at=${TIMESTAMP}" \
  "database_artifact=$(basename "$DB_FILE")" \
  "uploads_artifact=$(basename "$UPLOAD_FILE")" \
  "environment_artifact=${ENV_ARTIFACT}" \
  "app_version=${APP_VERSION}" \
  "release_id=${RELEASE_ID}" \
  "rule_version=${RULE_VERSION}" > "$MANIFEST_FILE"
ARTIFACTS+=("$MANIFEST_FILE")

CHECKSUM_FILE="${BACKUP_DIR}/valor_backup_${TIMESTAMP}.sha256"
for artifact in "${ARTIFACTS[@]}"; do
  printf '%s  %s\n' "$(checksum "$artifact")" "$(basename "$artifact")"
done > "$CHECKSUM_FILE"

# Payloads publish first; the checksum inventory is the completion marker. Remove
# this run's partial local payloads if any copy fails, and never publish the marker.
COPIED_LOCAL=()
for artifact in "${ARTIFACTS[@]}"; do
  if install -m 600 "$artifact" "$LOCAL_KEEP_DIR/"; then
    COPIED_LOCAL+=("${LOCAL_KEEP_DIR}/$(basename "$artifact")")
  else
    FAILED=1
    break
  fi
done
if [ "$FAILED" -eq 0 ]; then
  install -m 600 "$CHECKSUM_FILE" "$LOCAL_KEEP_DIR/" || FAILED=1
fi
if [ "$FAILED" -ne 0 ]; then
  if [ "${#COPIED_LOCAL[@]}" -gt 0 ]; then
    rm -f "${COPIED_LOCAL[@]}"
  fi
  rm -f "${LOCAL_KEEP_DIR}/$(basename "$CHECKSUM_FILE")"
  log "ERROR: local backup set could not be published atomically"
  exit 1
fi

remote_copy() {
  local artifact="$1"
  [ -n "$REMOTE_URI" ] || return 0
  if [ -z "$AWS_BIN" ]; then
    log "ERROR: remote backup configured but AWS CLI is unavailable"
    return 1
  fi
  # Bash 3.2 + `set -u` aborts when an empty array is expanded. Keep explicit
  # branches so the no-endpoint path remains portable to stock macOS Bash.
  if [ -n "$S3_ENDPOINT" ]; then
    "$AWS_BIN" s3 cp "$artifact" \
      "${REMOTE_URI%/}/$(basename "$artifact")" \
      --endpoint-url "$S3_ENDPOINT" >/dev/null 2>>"$LOG"
  else
    "$AWS_BIN" s3 cp "$artifact" \
      "${REMOTE_URI%/}/$(basename "$artifact")" >/dev/null 2>>"$LOG"
  fi
}

if [ -n "$REMOTE_URI" ]; then
  log "Uploading verified artifacts through the configured AWS credential chain..."
  for artifact in "${ARTIFACTS[@]}"; do
    if ! remote_copy "$artifact"; then
      FAILED=1
      break
    fi
  done
  # As with local publication, the checksum object is the remote completion marker.
  [ "$FAILED" -eq 0 ] && remote_copy "$CHECKSUM_FILE" || FAILED=1
else
  log "Remote copy disabled; artifacts retained locally only"
fi

{
  find "$LOCAL_KEEP_DIR" -name 'valor_db_*.dump' -mtime +30 -delete
  find "$LOCAL_KEEP_DIR" -name 'valor_uploads_*.tar.gz' -mtime +30 -delete
  find "$LOCAL_KEEP_DIR" -name 'valor_env_*.env.age' -mtime +30 -delete
  find "$LOCAL_KEEP_DIR" -name 'valor_backup_*.manifest' -mtime +30 -delete
  find "$LOCAL_KEEP_DIR" -name 'valor_backup_*.sha256' -mtime +30 -delete
} 2>>"$LOG"

if [ "$FAILED" -eq 0 ]; then
  log "=== Valor-Ops backup complete (verified) ==="
else
  log "=== Valor-Ops backup complete WITH ERRORS ==="
fi
exit "$FAILED"
