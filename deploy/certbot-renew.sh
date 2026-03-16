#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

cd "${PROJECT_ROOT}"
set -a
source .env
set +a

[[ "${ENABLE_TLS}" == "true" ]] || { log "tls disabled; skipping certbot"; exit 0; }
[[ -n "${DOMAIN_NAME}" ]] || fail "DOMAIN_NAME is required for TLS mode"
[[ -n "${ACME_EMAIL}" ]] || fail "ACME_EMAIL is required for TLS mode"

mkdir -p certs/letsencrypt nginx/certbot/www

issue_args=()
if [[ ! -f "certs/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]]; then
  issue_args=(certonly --webroot -w "${PROJECT_ROOT}/nginx/certbot/www" -d "${DOMAIN_NAME}" --email "${ACME_EMAIL}" --agree-tos --non-interactive)
else
  issue_args=(renew --webroot -w "${PROJECT_ROOT}/nginx/certbot/www" --non-interactive)
fi

docker run --rm \
  -v "${PROJECT_ROOT}/certs/letsencrypt:/etc/letsencrypt" \
  -v "${PROJECT_ROOT}/nginx/certbot/www:/var/www/certbot" \
  certbot/certbot:latest "${issue_args[@]}"

log "certbot operation completed"
