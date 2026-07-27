#!/usr/bin/env bash
# Reject raw agent transcripts and common credential material in release files.
# Findings report paths only so a CI log never repeats a candidate secret.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FILES=()
while IFS= read -r -d '' file; do
  [ "$file" = "scripts/release-hygiene.sh" ] || FILES+=("$file")
done < <(git ls-files --cached --others --exclude-standard -z)

[ "${#FILES[@]}" -gt 0 ] || exit 0

FAILED=0
GREP_BIN="${VALOR_HYGIENE_GREP_BIN:-grep}"
scan_paths() {
  local label="$1"
  local pattern="$2"
  local file status
  local found=false
  for file in "${FILES[@]}"; do
    if "$GREP_BIN" -IqE -- "$pattern" "$file" 2>/dev/null; then
      if [ "$found" = "false" ]; then
        printf 'release hygiene failed: %s detected in:\n' "$label" >&2
        found=true
      fi
      printf '%s\n' "$file" >&2
      continue
    else
      status=$?
    fi
    if [ "$status" -gt 1 ]; then
      printf 'release hygiene scanner error while reading: %s\n' "$file" >&2
      FAILED=1
      return 2
    fi
  done
  if [ "$found" = "true" ]; then
    FAILED=1
  fi
  return 0
}

TRANSCRIPT_PATTERN='parentUuid|sessionId|task-notification|deferred_tools_delta'
TOKEN_PATTERN='AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[0-9A-Za-z]{30,}|glpat-[0-9A-Za-z_-]{20,}|xox[baprs]-[0-9A-Za-z-]{20,}|sk_live_[0-9A-Za-z]{16,}|sk-[0-9A-Za-z_-]{20,}'
AWS_ASSIGNMENT_PATTERN="(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY)[[:space:]]*=[[:space:]]*[\"']?[0-9A-Za-z/+=_.-]{16,}"
PRIVATE_KEY_PATTERN='-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'

scan_paths "raw agent transcript marker" "$TRANSCRIPT_PATTERN"
scan_paths "credential token" "$TOKEN_PATTERN"
scan_paths "embedded AWS credential" "$AWS_ASSIGNMENT_PATTERN"
scan_paths "private key" "$PRIVATE_KEY_PATTERN"

exit "$FAILED"
