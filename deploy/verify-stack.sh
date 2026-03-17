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
mkdir -p "${PROJECT_ROOT}/${VERIFY_REPORT_DIR:-deploy}"

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

record_info() {
  local name="$1"
  local detail="$2"
  RESULTS+=("[INFO] ${name}: ${detail}")
  info "${name}: ${detail}"
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
record_result "${containers_ok}" "containers_ok"

backend_ready=false
if [[ "$(curl -fsS "${curl_base_opts[@]}" "${base_url}/health/ready" | jq -r '.ready')" == "true" ]]; then
  backend_ready=true
fi
record_result "${backend_ready}" "backend_ready"

if ./deploy/media-smoke-test.sh "${media_state_file}"; then
  :
else
  warn "media smoke script reported failure"
fi

[[ -f "${media_state_file}" ]] || fail "media smoke state file was not created"

set -a
source "${media_state_file}"
set +a

record_result "${SMOKE_NGINX_OK}" "nginx_ok"
record_result "${SMOKE_RTMP_INGEST_OK}" "rtmp_ingest_ok"
record_result "${SMOKE_VIEWER_API_HIDES_INGEST_KEY}" "viewer_api_hides_ingest_key"
record_result "${SMOKE_PLAYBACK_TOKEN_REJECTS_INGEST_KEY}" "playback_token_rejects_ingest_key"
record_result "${SMOKE_PLAYBACK_PATH_IS_DISTINCT_FROM_INGEST_KEY}" "playback_path_is_distinct_from_ingest_key"
record_result "${SMOKE_WHEP_URL_USES_PLAYBACK_PATH}" "whep_url_uses_playback_path"
if [[ "${VERIFY_RTMP_PLAYBACK_BLOCK:-true}" == "true" ]]; then
  record_result "${SMOKE_RTMP_READ_BLOCKED_ON_INGEST_PATH}" "rtmp_read_blocked_on_ingest_path"
  record_result "${SMOKE_RTMP_READ_BLOCKED_ON_OUTPUT_PATH}" "rtmp_read_blocked_on_output_path"
  record_result "${SMOKE_RTMP_PLAYBACK_BLOCKED}" "rtmp_playback_blocked"
else
  record_info "rtmp_playback_blocked" "false because verification was skipped by config"
fi
if [[ "${VERIFY_BROWSERLESS_WHEP:-true}" == "true" ]]; then
  record_result "${SMOKE_WHEP_ENDPOINT_OK}" "whep_or_webrtc_endpoint_ok"
else
  record_info "whep_or_webrtc_endpoint_ok" "false because verification was skipped by config"
fi
record_result "${SMOKE_PLAYBACK_AUTH_OK}" "playback_auth_ok"
if [[ "${VERIFY_TURN:-true}" == "true" ]]; then
  record_result "${SMOKE_TURN_REACHABLE}" "turn_reachable"
else
  record_info "turn_reachable" "false because verification was skipped by config"
fi

if [[ "${verify_tls_enabled}" == "true" ]]; then
  record_result "${SMOKE_MEDIA_ENCRYPTION_OK}" "media_encryption_ok"
else
  record_info "media_encryption_ok" "false in HTTP bootstrap mode because playback signaling is not under TLS"
fi

overall_status="passed"
if (( ${#FAILED_CHECKS[@]} > 0 )); then
  overall_status="failed"
fi

failed_checks_json="$(printf '%s\n' "${FAILED_CHECKS[@]:-}" | jq -R . | jq -s 'map(select(length > 0))')"
failed_checks_text='- none'
if (( ${#FAILED_CHECKS[@]} > 0 )); then
  failed_checks_text="$(printf '%s\n' "${FAILED_CHECKS[@]}" | sed 's/^/- /')"
fi

{
  printf 'VERIFY_TLS_ENABLED=%q\n' "${verify_tls_enabled}"
  printf 'VERIFY_DOMAIN=%q\n' "${DOMAIN_NAME}"
  printf 'VERIFY_CONTAINERS_OK=%q\n' "${containers_ok}"
  printf 'VERIFY_BACKEND_READY=%q\n' "${backend_ready}"
  printf 'VERIFY_OVERALL_STATUS=%q\n' "${overall_status}"
  printf 'VERIFY_FAILED_CHECKS_JSON=%q\n' "${failed_checks_json}"
  printf 'VERIFY_FAILED_CHECKS_TEXT=%q\n' "${failed_checks_text}"
} > "${state_file}"
./deploy/write-verification-report.sh "${state_file}"

print_results
if [[ "${overall_status}" != "passed" ]]; then
  fail "verification failed"
fi

success "stack verification passed"
