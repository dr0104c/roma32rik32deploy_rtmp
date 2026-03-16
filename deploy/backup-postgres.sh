#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_ROOT="/var/backups/stream-platform/postgres"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"
setup_trap

run_as_root mkdir -p "${BACKUP_ROOT}"
if [[ -n "${SUDO_USER:-}" ]]; then
  run_as_root chown "${SUDO_USER}:${SUDO_USER}" "${BACKUP_ROOT}"
fi

cd "${PROJECT_ROOT}"
set -a
source .env
set +a

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
backup_file="${BACKUP_ROOT}/stream-platform-postgres-${timestamp}.sql.gz"

info "creating postgres backup ${backup_file}"
compose exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip -c > "${backup_file}"
chmod 600 "${backup_file}"

ls -1t "${BACKUP_ROOT}"/stream-platform-postgres-*.sql.gz 2>/dev/null | tail -n +$((BACKUP_RETENTION + 1)) | xargs -r rm -f

success "postgres backup created: ${backup_file}"
