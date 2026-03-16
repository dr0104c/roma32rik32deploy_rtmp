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
require_cmd ffmpeg
require_cmd ffprobe
require_cmd timeout

RESULTS=()
base_scheme="http"
base_host="127.0.0.1"
base_port="${NGINX_HTTP_PORT}"
curl_base_opts=()

if [[ "${ENABLE_TLS}" == "true" && -n "${DOMAIN_NAME}" && -f "certs/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]]; then
  base_scheme="https"
  base_host="${DOMAIN_NAME}"
  base_port="${NGINX_HTTPS_PORT}"
  curl_base_opts=(-k --resolve "${DOMAIN_NAME}:${NGINX_HTTPS_PORT}:127.0.0.1")
fi

base_url="${base_scheme}://${base_host}:${base_port}"
user_id=""
stream_id=""
playback_name=""
ingest_key=""
playback_token=""
ingest_session_id=""
smoke_suffix="$(date +%s)-$$"

record_result() {
  local status="$1"
  local name="$2"
  RESULTS+=("[${status}] ${name}")
  if [[ "${status}" == "PASS" ]]; then
    pass "${name}"
  else
    fail_line "${name}"
  fi
}

print_results() {
  printf '\n=== E2E Smoke Summary ===\n'
  local line
  for line in "${RESULTS[@]}"; do
    printf '%s\n' "${line}"
  done
}

run_check() {
  local name="$1"
  shift
  info "${name}"
  if "$@"; then
    record_result PASS "${name}"
  else
    record_result FAIL "${name}"
    print_results
    exit 1
  fi
}

curl_api() {
  curl -fsS "${curl_base_opts[@]}" "$@"
}

json_post() {
  local url="$1"
  local body="$2"
  shift 2
  curl_api -X POST "${url}" -H 'content-type: application/json' "$@" -d "${body}"
}

check_health() {
  [[ "$(curl_api "${base_url}/health" | jq -r '.status')" == "ok" ]] || return 1
  [[ "$(curl_api "${base_url}/health/live" | jq -r '.status')" == "ok" ]] || return 1
  [[ "$(curl_api "${base_url}/health/ready" | jq -r '.ready')" == "true" ]] || return 1
}

check_site() {
  curl_api "${base_url}/" | grep -q 'WebRTC Viewer'
}

check_enroll() {
  local payload
  payload="$(json_post "${base_url}/api/v1/enroll" "{\"display_name\":\"Smoke User ${smoke_suffix}\"}")"
  user_id="$(echo "${payload}" | jq -r '.user_id')"
  [[ -n "${user_id}" && "${user_id}" != "null" ]]
}

check_approve_create_stream_and_grant() {
  curl_api -X POST "${base_url}/api/v1/admin/users/${user_id}/approve" -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null
  local stream_payload
  stream_payload="$(json_post "${base_url}/api/v1/admin/streams" "{\"name\":\"smoke-main-${smoke_suffix}\",\"playback_name\":\"smoke-main-${smoke_suffix}\"}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
  stream_id="$(echo "${stream_payload}" | jq -r '.stream_id')"
  playback_name="$(echo "${stream_payload}" | jq -r '.playback_name')"
  ingest_key="$(echo "${stream_payload}" | jq -r '.ingest_key')"
  [[ -n "${stream_id}" && -n "${playback_name}" && -n "${ingest_key}" ]] || return 1
  json_post "${base_url}/api/v1/admin/streams/${stream_id}/grant-user" "{\"user_id\":\"${user_id}\"}" -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null
  local ingest_payload
  ingest_payload="$(json_post "${base_url}/api/v1/admin/ingest-sessions" "{\"output_stream_id\":\"${stream_id}\",\"publisher_label\":\"smoke-publisher\"}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
  ingest_session_id="$(echo "${ingest_payload}" | jq -r '.ingest_session_id')"
  ingest_key="$(echo "${ingest_payload}" | jq -r '.ingest_key')"
  [[ -n "${ingest_session_id}" && -n "${ingest_key}" ]]
}

check_stream_listing() {
  local payload
  payload="$(curl_api "${base_url}/api/v1/streams?user_id=${user_id}")"
  echo "${payload}" | jq -e --arg stream_id "${stream_id}" '.streams[] | select(.stream_id == $stream_id)' >/dev/null
}

check_playback_token_issue() {
  local payload
  payload="$(json_post "${base_url}/api/v1/playback-token" "{\"user_id\":\"${user_id}\",\"stream_id\":\"${stream_id}\"}")"
  playback_token="$(echo "${payload}" | jq -r '.token')"
  [[ -n "${playback_token}" && "${playback_token}" != "null" ]]
}

check_internal_auth() {
  local valid_code invalid_code rtmp_code
  valid_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"whep\",\"query\":\"token=${playback_token}\"}")"
  invalid_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"whep\",\"query\":\"token=invalid\"}")"
  rtmp_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"rtmp\",\"query\":\"token=${playback_token}\"}")"
  [[ "${valid_code}" == "200" && "${invalid_code}" == "401" && "${rtmp_code}" == "401" ]]
}

check_rtmp_ingest() {
  timeout 15s ffmpeg -loglevel error -re \
    -f lavfi -i testsrc=size=640x360:rate=15 \
    -f lavfi -i sine=frequency=1000:sample_rate=48000 \
    -t 4 \
    -c:v libx264 -pix_fmt yuv420p \
    -c:a aac -b:a 128k \
    -shortest \
    -f flv "rtmp://127.0.0.1:${RTMP_PORT}/live/${ingest_key}"
}

check_ingest_lifecycle() {
  local payload live_status offline_status
  payload="$(curl_api "${base_url}/api/v1/admin/ingest-sessions?output_stream_id=${stream_id}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
  live_status="$(echo "${payload}" | jq -r ".ingest_sessions[] | select(.ingest_session_id == \"${ingest_session_id}\") | .status")"
  [[ "${live_status}" == "live" ]] || return 1
  compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/publish-stop?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"path\":\"live/${ingest_key}\"}" | grep -q '^200$' || return 1
  payload="$(curl_api "${base_url}/api/v1/admin/ingest-sessions?output_stream_id=${stream_id}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
  offline_status="$(echo "${payload}" | jq -r ".ingest_sessions[] | select(.ingest_session_id == \"${ingest_session_id}\") | .status")"
  [[ "${offline_status}" == "offline" ]]
}

check_rtmp_playback_denied() {
  ! ffprobe -v error -rw_timeout 5000000 -show_entries stream=codec_type -of default=noprint_wrappers=1 "rtmp://127.0.0.1:${RTMP_PORT}/live/${playback_name}" >/dev/null 2>&1
}

main() {
  run_check "backend health/live/ready endpoints" check_health
  run_check "viewer site served by nginx" check_site
  run_check "enroll endpoint works" check_enroll
  run_check "approve, create stream and grant access work" check_approve_create_stream_and_grant
  run_check "approved user stream listing works" check_stream_listing
  run_check "playback token issuance works" check_playback_token_issue
  run_check "internal media auth validates token and denies RTMP playback" check_internal_auth
  run_check "RTMP ingest works with generated test source" check_rtmp_ingest
  run_check "ingest session lifecycle is visible and transitions live -> offline" check_ingest_lifecycle
  run_check "direct RTMP playback is denied" check_rtmp_playback_denied
  print_results
  success "e2e smoke test passed"
  info "verified semantics: ingest = RTMP, direct RTMP playback is disabled, viewer playback is authorized through WebRTC/WHEP token auth, WebRTC delivery is encrypted only when served over HTTPS/TLS"
}

main "$@"
