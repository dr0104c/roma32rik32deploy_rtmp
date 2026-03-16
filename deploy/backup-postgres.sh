#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_ROOT="/var/backups/stream-platform/postgres"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

sudo mkdir -p "${BACKUP_ROOT}"
sudo chown "${USER}:${USER}" "${BACKUP_ROOT}"
cd "${PROJECT_ROOT}"
set -a
source .env
set +a

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
backup_file="${BACKUP_ROOT}/stream-platform-postgres-${timestamp}.sql.gz"

compose exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip -c > "${backup_file}"
chmod 600 "${backup_file}"

ls -1t "${BACKUP_ROOT}"/stream-platform-postgres-*.sql.gz 2>/dev/null | tail -n +$((BACKUP_RETENTION + 1)) | xargs -r rm -f

log "postgres backup created: ${backup_file}"
