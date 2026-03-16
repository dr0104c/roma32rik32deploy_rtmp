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

require_cmd docker
require_cmd curl
require_cmd jq
require_cmd ffmpeg
require_cmd ffprobe

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

curl_api() {
  curl -fsS "${curl_base_opts[@]}" "$@"
}

json_post() {
  local url="$1"
  local body="$2"
  shift 2
  curl_api -X POST "${url}" -H 'content-type: application/json' "$@" -d "${body}"
}

poll_json_field() {
  local url="$1"
  local jq_filter="$2"
  local expected_regex="$3"
  local attempts="${4:-20}"
  local delay="${5:-2}"
  local header="${6:-}"
  local value
  for _ in $(seq 1 "${attempts}"); do
    if [[ -n "${header}" ]]; then
      value="$(curl_api "${url}" -H "${header}" | jq -r "${jq_filter}")"
    else
      value="$(curl_api "${url}" | jq -r "${jq_filter}")"
    fi
    if [[ "${value}" =~ ${expected_regex} ]]; then
      echo "${value}"
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

log "checking docker access"
docker_host info >/dev/null

log "checking containers are running"
running_services="$(compose ps --services --filter status=running)"
for service in postgres backend mediamtx coturn nginx; do
  echo "${running_services}" | grep -qx "${service}" || fail "service ${service} is not running"
done

log "checking health endpoints"
[[ "$(curl_api "${base_url}/health" | jq -r '.status')" == "ok" ]] || fail "health failed"
[[ "$(curl_api "${base_url}/health/live" | jq -r '.status')" == "ok" ]] || fail "health/live failed"
[[ "$(curl_api "${base_url}/health/ready" | jq -r '.ready')" == "true" ]] || fail "health/ready failed"

if [[ "${ENABLE_TLS}" == "true" && -f "certs/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]]; then
  log "checking https mode"
  [[ -f "certs/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]] || fail "certificate missing"
  redirect_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${NGINX_HTTP_PORT}/health" -H "Host: ${DOMAIN_NAME}")"
  [[ "${redirect_code}" =~ ^(301|308)$ ]] || fail "http to https redirect missing"
fi

log "checking nginx site"
site_html="$(curl_api "${base_url}/")"
echo "${site_html}" | grep -q 'WebRTC Viewer' || fail "viewer site was not served"

log "checking secrets bootstrap"
for key in POSTGRES_PASSWORD ADMIN_SECRET INTERNAL_API_SECRET PLAYBACK_TOKEN_SECRET VIEWER_SESSION_SECRET TURN_SHARED_SECRET; do
  value="$(env_get "${key}" .env)"
  [[ "${#value}" -ge 24 ]] || fail "secret ${key} is too short"
done

log "checking enroll and pending viewer session"
pending_payload="$(json_post "${base_url}/api/v1/enroll" '{"name":"Pending User"}')"
pending_user_id="$(echo "${pending_payload}" | jq -r '.id')"
pending_client_code="$(echo "${pending_payload}" | jq -r '.client_code')"
pending_viewer="$(json_post "${base_url}/api/v1/viewer/session" "{\"client_code\":\"${pending_client_code}\"}")"
[[ "$(echo "${pending_viewer}" | jq -r '.viewer_token')" == "null" ]] || fail "pending user unexpectedly received viewer token"

log "checking approve endpoint"
curl_api -X POST "${base_url}/api/v1/admin/users/${pending_user_id}/approve" -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null

log "checking stream creation"
stream_payload="$(json_post "${base_url}/api/v1/streams" '{"name":"drone-main"}' -H "X-Admin-Secret: ${ADMIN_SECRET}")"
stream_id="$(echo "${stream_payload}" | jq -r '.id')"
stream_key="$(echo "${stream_payload}" | jq -r '.stream_key')"
[[ -n "${stream_id}" && -n "${stream_key}" ]] || fail "invalid stream response"
aux_stream_payload="$(json_post "${base_url}/api/v1/streams" '{"name":"drone-shadow"}' -H "X-Admin-Secret: ${ADMIN_SECRET}")"
aux_stream_id="$(echo "${aux_stream_payload}" | jq -r '.id')"
[[ "${aux_stream_id}" != "${stream_id}" ]] || fail "second stream creation failed"

log "checking grant endpoint"
grant_payload="$(curl_api -X POST "${base_url}/api/v1/streams/${stream_id}/grant-user/${pending_user_id}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
[[ "$(echo "${grant_payload}" | jq -r '.granted')" == "true" ]] || fail "grant endpoint failed"

log "checking viewer session and viewer/me"
viewer_session="$(json_post "${base_url}/api/v1/viewer/session" "{\"client_code\":\"${pending_client_code}\"}")"
viewer_token="$(echo "${viewer_session}" | jq -r '.viewer_token')"
[[ -n "${viewer_token}" && "${viewer_token}" != "null" ]] || fail "approved user did not receive viewer token"
viewer_me="$(curl_api "${base_url}/api/v1/viewer/me" -H "Authorization: Bearer ${viewer_token}")"
[[ "$(echo "${viewer_me}" | jq -r '.user.id')" == "${pending_user_id}" ]] || fail "viewer/me returned unexpected user"

log "checking viewer/streams ACL"
viewer_streams="$(curl_api "${base_url}/api/v1/viewer/streams" -H "Authorization: Bearer ${viewer_token}")"
[[ "$(echo "${viewer_streams}" | jq '.streams | length')" == "1" ]] || fail "viewer streams length mismatch"
[[ "$(echo "${viewer_streams}" | jq -r '.streams[0].id')" == "${stream_id}" ]] || fail "viewer streams returned unauthorized stream"

log "checking playback-session issuance"
playback_session="$(curl_api -X POST "${base_url}/api/v1/viewer/streams/${stream_id}/playback-session" -H "Authorization: Bearer ${viewer_token}")"
playback_token="$(echo "${playback_session}" | jq -r '.playback_token')"
[[ -n "${playback_token}" && "${playback_token}" != "null" ]] || fail "playback session token was not issued"

log "checking legacy playback token compatibility"
legacy_playback="$(json_post "${base_url}/api/v1/playback-token" "{\"user_id\":${pending_user_id},\"stream_id\":${stream_id}}")"
[[ "$(echo "${legacy_playback}" | jq -r '.expires_in')" == "${PLAYBACK_TOKEN_TTL_SECONDS}" ]] || fail "legacy playback-token ttl mismatch"

log "checking internal MediaMTX auth callback for publish"
publish_status="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/mediamtx/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"publish\",\"path\":\"live/${stream_key}\",\"protocol\":\"rtmp\"}")"
[[ "${publish_status}" == "200" ]] || fail "publish auth callback failed"

log "checking invalid playback token deny"
invalid_status="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/mediamtx/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${stream_key}\",\"protocol\":\"webrtc\",\"query\":\"token=invalid\"}")"
[[ "${invalid_status}" == "401" ]] || fail "invalid playback token was not rejected"

log "checking RTMP ingest"
ffmpeg -loglevel error -re -f lavfi -i testsrc=size=640x360:rate=15 -t 3 -c:v libx264 -pix_fmt yuv420p -f flv "rtmp://127.0.0.1:${RTMP_PORT}/live/${stream_key}"

log "checking lifecycle"
poll_json_field "${base_url}/api/v1/viewer/streams/${stream_id}" '.status' 'live|stalled|ended' 20 1 "Authorization: Bearer ${viewer_token}" >/dev/null || fail "stream did not enter live lifecycle"

log "checking RTMP playback deny"
if ffprobe -v error -rw_timeout 5000000 -show_entries stream=codec_type -of default=noprint_wrappers=1 "rtmp://127.0.0.1:${RTMP_PORT}/live/${stream_key}" >/dev/null 2>&1; then
  fail "rtmp playback unexpectedly succeeded"
fi

log "checking lifecycle after ingest stop"
poll_json_field "${base_url}/api/v1/viewer/streams/${stream_id}" '.status' 'ended|offline|stalled' 20 2 "Authorization: Bearer ${viewer_token}" >/dev/null || fail "stream did not transition after ingest stopped"

log "checking internal endpoints are denied"
internal_http_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" "${base_url}/internal/mediamtx/auth")"
[[ "${internal_http_code}" == "403" ]] || fail "public access to /internal is not denied"

log "checking blocked user cannot receive viewer session"
blocked_payload="$(json_post "${base_url}/api/v1/enroll" '{"name":"Blocked User"}')"
blocked_user_id="$(echo "${blocked_payload}" | jq -r '.id')"
blocked_client_code="$(echo "${blocked_payload}" | jq -r '.client_code')"
curl_api -X POST "${base_url}/api/v1/admin/users/${blocked_user_id}/approve" -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null
json_post "${base_url}/api/v1/admin/users/${blocked_user_id}/block" '{"reason":"manual block"}' -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null
blocked_viewer="$(json_post "${base_url}/api/v1/viewer/session" "{\"client_code\":\"${blocked_client_code}\"}")"
[[ "$(echo "${blocked_viewer}" | jq -r '.viewer_token')" == "null" ]] || fail "blocked user unexpectedly received viewer token"

log "checking backup script"
./deploy/backup-postgres.sh >/dev/null

log "checking health-summary script"
./deploy/health-summary.sh >/dev/null

log "checking firewall and timers"
sudo ufw status | grep -q 'Status: active' || fail "ufw is not active"
systemctl is-enabled stream-platform-backup.timer >/dev/null
systemctl is-enabled stream-platform-cert-renew.timer >/dev/null
systemctl is-enabled stream-platform-healthcheck.timer >/dev/null

log "checking rate limit config presence"
grep -R -q 'limit_req' nginx/conf.d nginx/nginx.conf || fail "nginx rate limiting missing"

log "smoke test passed"
