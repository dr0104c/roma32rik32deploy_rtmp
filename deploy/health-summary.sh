#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="/var/log/stream-platform"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"
setup_trap

run_as_root mkdir -p "${LOG_DIR}"
run_as_root touch "${LOG_DIR}/health-summary.log"
if [[ -n "${SUDO_USER:-}" ]]; then
  run_as_root chown "${SUDO_USER}:${SUDO_USER}" "${LOG_DIR}/health-summary.log"
fi

cd "${PROJECT_ROOT}"
set -a
source .env
set +a

base_url="http://127.0.0.1:${NGINX_HTTP_PORT}"
curl_opts=()
if [[ "${ENABLE_TLS}" == "true" && -n "${DOMAIN_NAME}" && -f "${PROJECT_ROOT}/certs/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]]; then
  base_url="https://${DOMAIN_NAME}:${NGINX_HTTPS_PORT}"
  curl_opts=(-k --resolve "${DOMAIN_NAME}:${NGINX_HTTPS_PORT}:127.0.0.1")
fi

{
  info "container status"
  compose ps
  info "backend live"
  curl -fsS "${curl_opts[@]}" "${base_url}/health/live" || true
  echo
  info "backend ready"
  curl -fsS "${curl_opts[@]}" "${base_url}/health/ready" || true
  echo
  info "disk usage"
  df -h /
  info "ingest lifecycle summary"
  compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A -c "SELECT COUNT(*) FROM ingest_sessions WHERE status = 'live';" 2>/dev/null | sed 's/^/live_ingest_sessions=/'
  compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A -c "SELECT COALESCE(MAX(updated_at)::text, 'none') FROM ingest_sessions;" 2>/dev/null | sed 's/^/last_ingest_event=/'
  compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A -c "SELECT COUNT(*) FROM audit_logs WHERE actor_type = 'media' AND action IN ('publish_denied','media_auth_denied','rtmp_playback_denied') AND created_at >= NOW() - INTERVAL '1 hour';" 2>/dev/null | sed 's/^/media_auth_failures_last_hour=/'
  for service in backend nginx mediamtx postgres coturn; do
    info "last log lines for ${service}"
    docker_host logs "stream-platform-${service}" --tail 20 2>&1
  done
  info "systemd timers"
  systemctl list-timers --all 'stream-platform-*' || true
} | tee -a "${LOG_DIR}/health-summary.log"
