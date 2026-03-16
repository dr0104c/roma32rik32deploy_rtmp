#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

backup_file="${1:-}"
[[ -n "${backup_file}" ]] || fail "usage: restore-postgres.sh <backup.sql.gz>"
[[ -f "${backup_file}" ]] || fail "backup file not found: ${backup_file}"

cd "${PROJECT_ROOT}"
set -a
source .env
set +a

compose stop backend mediamtx nginx
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
gunzip -c "${backup_file}" | compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
compose up -d backend mediamtx nginx
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" < sql/003_server_beta.sql
log "postgres restore completed from ${backup_file}"
