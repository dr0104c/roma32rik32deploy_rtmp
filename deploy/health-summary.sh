#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="/var/log/stream-platform"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

sudo mkdir -p "${LOG_DIR}"
sudo touch "${LOG_DIR}/health-summary.log"
sudo chown "${USER}:${USER}" "${LOG_DIR}/health-summary.log"
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
  log "container status"
  compose ps
  log "backend live"
  curl -fsS "${curl_opts[@]}" "${base_url}/health/live" || true
  echo
  log "backend ready"
  curl -fsS "${curl_opts[@]}" "${base_url}/health/ready" || true
  echo
  log "disk usage"
  df -h /
  for service in backend nginx mediamtx postgres coturn; do
    log "last errors for ${service}"
    docker_host logs "stream-platform-${service}" --tail 20 2>&1 | tail -n 20
  done
  log "systemd timers"
  systemctl list-timers --all 'stream-platform-*' || true
} | tee -a "${LOG_DIR}/health-summary.log"
