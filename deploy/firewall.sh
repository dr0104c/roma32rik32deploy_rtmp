#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"
setup_trap

ENV_FILE="${1:-${PROJECT_ROOT}/.env}"
[[ -f "${ENV_FILE}" ]] || fail "missing env file ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

info "installing and applying ufw firewall rules"
run_as_root apt-get update
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y ufw

run_as_root ufw --force reset
run_as_root ufw default deny incoming
run_as_root ufw default allow outgoing

run_as_root ufw allow "${SSH_PORT:-22}/tcp"
run_as_root ufw allow "${NGINX_HTTP_PORT}/tcp"
run_as_root ufw allow "${NGINX_HTTPS_PORT}/tcp"
run_as_root ufw allow "${RTMP_PORT}/tcp"
run_as_root ufw allow "${TURN_PORT}/tcp"
run_as_root ufw allow "${TURN_PORT}/udp"
run_as_root ufw allow "${TURN_TLS_PORT}/tcp"
run_as_root ufw allow "${TURN_TLS_PORT}/udp"
run_as_root ufw allow "${WEBRTC_ICE_PORT}/tcp"
run_as_root ufw allow "${WEBRTC_ICE_PORT}/udp"
run_as_root ufw allow "${TURN_MIN_PORT}:${TURN_MAX_PORT}/udp"
run_as_root ufw --force enable
run_as_root ufw status verbose
success "firewall rules applied"
