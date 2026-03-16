#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

ENV_FILE="${1:-${PROJECT_ROOT}/.env}"
[[ -f "${ENV_FILE}" ]] || fail "missing env file ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ufw

sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow "${SSH_PORT:-22}/tcp"
sudo ufw allow "${NGINX_HTTP_PORT}/tcp"
sudo ufw allow "${NGINX_HTTPS_PORT}/tcp"
sudo ufw allow "${RTMP_PORT}/tcp"
sudo ufw allow "${TURN_PORT}/tcp"
sudo ufw allow "${TURN_PORT}/udp"
sudo ufw allow "${TURN_TLS_PORT}/tcp"
sudo ufw allow "${TURN_TLS_PORT}/udp"
sudo ufw allow "${WEBRTC_ICE_PORT}/tcp"
sudo ufw allow "${WEBRTC_ICE_PORT}/udp"
sudo ufw allow "${TURN_MIN_PORT}:${TURN_MAX_PORT}/udp"
sudo ufw --force enable
sudo ufw status verbose
