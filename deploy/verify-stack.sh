#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"
setup_trap

cd "${PROJECT_ROOT}"
set -a
source .env
set +a

require_cmd curl
require_cmd jq

state_file="${SCRIPT_DIR}/.verification-state"
media_state_file="${SCRIPT_DIR}/.media-smoke-state"
rm -f "${state_file}" "${media_state_file}"

RESULTS=()
FAILED_CHECKS=()

record_result() {
  local ok="$1"
  local name="$2"
  if [[ "${ok}" == "true" ]]; then
    RESULTS+=("[PASS] ${name}")
    pass "${name}"
  else
    RESULTS+=("[FAIL] ${name}")
    FAILED_CHECKS+=("${name}")
    fail_line "${name}"
  fi
}

print_results() {
  printf '\n=== Verification Summary ===\n'
  local line
  for line in "${RESULTS[@]}"; do
    printf '%s\n' "${line}"
  done
}

base_scheme="http"
base_host="127.0.0.1"
base_port="${NGINX_HTTP_PORT}"
curl_base_opts=()
verify_tls_enabled=false
if [[ "${ENABLE_TLS}" == "true" && -n "${DOMAIN_NAME}" && -f "certs/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]]; then
  base_scheme="https"
  base_host="${DOMAIN_NAME}"
  base_port="${NGINX_HTTPS_PORT}"
  curl_base_opts=(-k --resolve "${DOMAIN_NAME}:${NGINX_HTTPS_PORT}:127.0.0.1")
  verify_tls_enabled=true
fi
base_url="${base_scheme}://${base_host}:${base_port}"

containers_ok=true
for service in postgres backend mediamtx coturn nginx; do
  if ! wait_for_compose_service "${service}" running 1 1; then
    containers_ok=false
  fi
done
record_result "${containers_ok}" "containers running"

backend_ready=false
if [[ "$(curl -fsS "${curl_base_opts[@]}" "${base_url}/health/ready" | jq -r '.ready')" == "true" ]]; then
  backend_ready=true
fi
record_result "${backend_ready}" "backend readiness endpoint"

if ./deploy/media-smoke-test.sh "${media_state_file}"; then
  :
else
  warn "media smoke script reported failure"
fi

if [[ ! -f "${media_state_file}" ]]; then
  fail "media smoke state file was not created"
fi

set -a
source "${media_state_file}"
set +a

record_result "${SMOKE_NGINX_OK}" "nginx public endpoint"
record_result "${SMOKE_RTMP_INGEST_OK}" "RTMP ingest endpoint"
record_result "${SMOKE_RTMP_PLAYBACK_BLOCKED}" "RTMP playback blocked"
record_result "${SMOKE_WHEP_ENDPOINT_OK}" "WHEP/WebRTC endpoint semantics"
record_result "${SMOKE_PLAYBACK_AUTH_OK}" "playback auth callback path"
record_result "${SMOKE_TURN_REACHABLE}" "TURN service reachable"

overall_status="pass"
if [[ "${verify_tls_enabled}" == "true" ]]; then
  record_result "${SMOKE_MEDIA_ENCRYPTION_OK}" "protected playback channel"
else
  RESULTS+=("[PASS] protected playback channel check skipped in HTTP bootstrap mode")
  pass "protected playback channel check skipped in HTTP bootstrap mode"
fi

if (( ${#FAILED_CHECKS[@]} > 0 )); then
  overall_status="fail"
fi

failed_checks_json="$(printf '%s\n' "${FAILED_CHECKS[@]:-}" | jq -R . | jq -s 'map(select(length > 0))')"
failed_checks_text='- none'
if (( ${#FAILED_CHECKS[@]} > 0 )); then
  failed_checks_text="$(printf '%s\n' "${FAILED_CHECKS[@]}" | sed 's/^/- /')"
fi

{
  printf 'VERIFY_TLS_ENABLED=%q\n' "${verify_tls_enabled}"
  printf 'VERIFY_CONTAINERS_OK=%q\n' "${containers_ok}"
  printf 'VERIFY_BACKEND_READY=%q\n' "${backend_ready}"
  printf 'VERIFY_OVERALL_STATUS=%q\n' "${overall_status}"
  printf 'VERIFY_FAILED_CHECKS_JSON=%q\n' "${failed_checks_json}"
  printf 'VERIFY_FAILED_CHECKS_TEXT=%q\n' "${failed_checks_text}"
} > "${state_file}"
./deploy/write-verification-report.sh "${state_file}"

print_results
if [[ "${overall_status}" != "pass" ]]; then
  fail "verification failed"
fi

success "stack verification passed"
