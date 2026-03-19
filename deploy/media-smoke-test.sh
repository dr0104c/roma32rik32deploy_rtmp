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

state_file="${1:-${SCRIPT_DIR}/.media-smoke-state}"
tmp_dir="$(mktemp -d /tmp/stream-platform-media-smoke.XXXXXX)"
ffmpeg_log="${tmp_dir}/ffmpeg.log"
rm -f "${state_file}"

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
smoke_duration="${MEDIA_SMOKE_TEST_DURATION_SEC:-12}"
smoke_stream_prefix="${MEDIA_SMOKE_TEST_STREAM_NAME:-verification-smoke}"
smoke_suffix="$(date +%s)-$$"
ffmpeg_pid=""

stop_publisher() {
  if [[ -n "${ffmpeg_pid}" ]] && kill -0 "${ffmpeg_pid}" >/dev/null 2>&1; then
    kill "${ffmpeg_pid}" >/dev/null 2>&1 || true
    wait "${ffmpeg_pid}" >/dev/null 2>&1 || true
  fi
  ffmpeg_pid=""
}

cleanup() {
  stop_publisher
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

curl_api() {
  curl -fsS "${curl_base_opts[@]}" "$@"
}

json_post() {
  local url="$1"
  local body="$2"
  shift 2
  curl_api -X POST "${url}" -H 'content-type: application/json' "$@" -d "${body}"
}

admin_json_post() {
  local url="$1"
  local body="$2"
  shift 2
  json_post "${url}" "${body}" -H "Authorization: Bearer ${admin_access_token}" "$@"
}

admin_api() {
  curl_api -H "Authorization: Bearer ${admin_access_token}" "$@"
}

check_turn_reachable() {
  timeout 3 bash -lc ":</dev/tcp/127.0.0.1/${TURN_PORT}" >/dev/null 2>&1
}

check_whep_http_semantics() {
  local sdp valid_code invalid_code
  sdp=$'v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=stream-platform-smoke\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\nc=IN IP4 0.0.0.0\r\na=mid:0\r\na=sendrecv\r\n'
  invalid_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" -X POST "${base_url}/webrtc/live/${playback_name}/whep?token=invalid" -H 'content-type: application/sdp' --data-binary "${sdp}")"
  valid_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" -X POST "${base_url}/webrtc/live/${playback_name}/whep?token=${playback_token}" -H 'content-type: application/sdp' --data-binary "${sdp}")"
  [[ "${invalid_code}" == "401" ]] || return 1
  case "${valid_code}" in
    201|400|406|415)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

poll_ingest_status() {
  local expected="$1"
  local payload current
  local attempt
  for attempt in $(seq 1 20); do
    payload="$(admin_api "${base_url}/api/v1/admin/ingest-sessions?current_output_stream_id=${stream_id}")"
    current="$(echo "${payload}" | jq -r ".ingest_sessions[] | select(.ingest_session_id == \"${ingest_session_id}\") | .status")"
    if [[ "${current}" == "${expected}" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

write_state() {
  {
    printf 'SMOKE_BASE_URL=%q\n' "${base_url}"
    printf 'SMOKE_TLS_ENABLED=%q\n' "${ENABLE_TLS}"
    printf 'SMOKE_PLAYBACK_TRANSPORT=%q\n' "${base_scheme}"
    printf 'SMOKE_USER_ID=%q\n' "${user_id}"
    printf 'SMOKE_STREAM_ID=%q\n' "${stream_id}"
    printf 'SMOKE_STREAM_NAME=%q\n' "${stream_name}"
    printf 'SMOKE_PLAYBACK_NAME=%q\n' "${playback_name}"
    printf 'SMOKE_INGEST_SESSION_ID=%q\n' "${ingest_session_id}"
    printf 'SMOKE_INGEST_KEY=%q\n' "${ingest_key}"
    printf 'SMOKE_PLAYBACK_TOKEN=%q\n' "${playback_token}"
    printf 'SMOKE_ADMIN_AUTH_OK=%q\n' "${admin_auth_ok}"
    printf 'SMOKE_ADMIN_UI_OK=%q\n' "${admin_ui_ok}"
    printf 'SMOKE_LEGACY_ADMIN_SECRET_MODE=%q\n' "${LEGACY_ADMIN_SECRET_ENABLED}"
    printf 'SMOKE_USER_MODERATION_OK=%q\n' "${user_moderation_ok}"
    printf 'SMOKE_GROUP_ACL_OK=%q\n' "${group_acl_ok}"
    printf 'SMOKE_NGINX_OK=%q\n' "${nginx_ok}"
    printf 'SMOKE_RTMP_INGEST_OK=%q\n' "${rtmp_ingest_ok}"
    printf 'SMOKE_RTMP_PLAYBACK_BLOCKED=%q\n' "${rtmp_playback_blocked}"
    printf 'SMOKE_VIEWER_API_HIDES_INGEST_KEY=%q\n' "${viewer_api_hides_ingest_key}"
    printf 'SMOKE_PLAYBACK_TOKEN_REJECTS_INGEST_KEY=%q\n' "${playback_token_rejects_ingest_key}"
    printf 'SMOKE_RTMP_READ_BLOCKED_ON_INGEST_PATH=%q\n' "${rtmp_read_blocked_on_ingest_path}"
    printf 'SMOKE_RTMP_READ_BLOCKED_ON_OUTPUT_PATH=%q\n' "${rtmp_read_blocked_on_output_path}"
    printf 'SMOKE_PLAYBACK_PATH_IS_DISTINCT_FROM_INGEST_KEY=%q\n' "${playback_path_is_distinct_from_ingest_key}"
    printf 'SMOKE_WHEP_URL_USES_PLAYBACK_PATH=%q\n' "${whep_url_uses_playback_path}"
    printf 'SMOKE_WHEP_ENDPOINT_OK=%q\n' "${whep_or_webrtc_endpoint_ok}"
    printf 'SMOKE_PLAYBACK_AUTH_OK=%q\n' "${playback_auth_ok}"
    printf 'SMOKE_TURN_REACHABLE=%q\n' "${turn_reachable}"
    printf 'SMOKE_MEDIA_ENCRYPTION_OK=%q\n' "${media_encryption_ok}"
    printf 'SMOKE_TRANSCODING_ENABLED=%q\n' "${ENABLE_FFMPEG_TRANSCODE}"
    printf 'SMOKE_TRANSCODING_VERIFIED=%q\n' "false"
    printf 'SMOKE_BROWSER_RENDERING_VERIFIED=%q\n' "false"
    printf 'SMOKE_MEDIA_NOTES=%q\n' "${media_notes}"
  } > "${state_file}"
}

nginx_ok=false
admin_auth_ok=false
admin_ui_ok=false
user_moderation_ok=false
group_acl_ok=false
rtmp_ingest_ok=false
rtmp_playback_blocked=false
viewer_api_hides_ingest_key=false
playback_token_rejects_ingest_key=false
rtmp_read_blocked_on_ingest_path=false
rtmp_read_blocked_on_output_path=false
playback_path_is_distinct_from_ingest_key=false
whep_url_uses_playback_path=false
whep_or_webrtc_endpoint_ok=false
playback_auth_ok=false
turn_reachable=false
media_encryption_ok=false
media_notes="server-side media verification only; browser-level rendering not exercised; encrypted playback and transcoding are reported separately"

stream_name="${smoke_stream_prefix}-${smoke_suffix}"
playback_name=""
user_id=""
stream_id=""
ingest_session_id=""
ingest_key=""
playback_token=""
playback_url=""
user_client_code=""
admin_access_token=""

info "checking admin auth and admin ui"
invalid_admin_login_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" -X POST "${base_url}/api/v1/admin/auth/login" -H 'content-type: application/json' -d '{"username":"invalid","password":"invalid"}')"
admin_login_payload="$(json_post "${base_url}/api/v1/admin/auth/login" "{\"username\":\"${ADMIN_BOOTSTRAP_USERNAME}\",\"password\":\"${ADMIN_BOOTSTRAP_PASSWORD}\"}")"
admin_access_token="$(echo "${admin_login_payload}" | jq -r '.access_token // empty')"
admin_me_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" "${base_url}/api/v1/admin/auth/me" -H "Authorization: Bearer ${admin_access_token}")"
protected_admin_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" "${base_url}/api/v1/admin/users?limit=1" -H "Authorization: Bearer ${admin_access_token}")"
if [[ -n "${admin_access_token}" && "${invalid_admin_login_code}" == "401" && "${admin_me_code}" == "200" && "${protected_admin_code}" == "200" ]]; then
  admin_auth_ok=true
fi

admin_ui_html="$(curl_api "${base_url}/admin/")"
if echo "${admin_ui_html}" | grep -qi 'Admin Console'; then
  admin_ui_ok=true
fi

legacy_admin_expected="${LEGACY_ADMIN_SECRET_ENABLED:-true}"
legacy_admin_code="$(curl -s -o /dev/null -w '%{http_code}' "${curl_base_opts[@]}" "${base_url}/api/v1/admin/users?limit=1" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
if [[ "${legacy_admin_expected}" == "true" ]]; then
  [[ "${legacy_admin_code}" == "200" ]] || fail "legacy admin secret mode expected to be enabled"
else
  [[ "${legacy_admin_code}" == "401" ]] || fail "legacy admin secret mode expected to be disabled"
fi

info "checking user moderation and group ACL flows"
moderation_payload="$(json_post "${base_url}/api/v1/enroll" "{\"display_name\":\"Moderation User ${smoke_suffix}\"}")"
moderation_user_id="$(echo "${moderation_payload}" | jq -r '.user_id')"
reject_status="$(admin_json_post "${base_url}/api/v1/admin/users/${moderation_user_id}/reject" '{}' | jq -r '.status')"
approve_status="$(admin_json_post "${base_url}/api/v1/admin/users/${moderation_user_id}/approve" '{}' | jq -r '.status')"
block_status="$(admin_json_post "${base_url}/api/v1/admin/users/${moderation_user_id}/block" '{}' | jq -r '.status')"
unblock_status="$(admin_json_post "${base_url}/api/v1/admin/users/${moderation_user_id}/unblock" '{}' | jq -r '.status')"
if [[ "${reject_status}" == "rejected" && "${approve_status}" == "approved" && "${block_status}" == "blocked" && "${unblock_status}" == "approved" ]]; then
  user_moderation_ok=true
fi

group_user_payload="$(json_post "${base_url}/api/v1/enroll" "{\"display_name\":\"Group User ${smoke_suffix}\"}")"
group_user_id="$(echo "${group_user_payload}" | jq -r '.user_id')"
group_user_client_code="$(echo "${group_user_payload}" | jq -r '.client_code')"
admin_json_post "${base_url}/api/v1/admin/users/${group_user_id}/approve" '{}' >/dev/null
group_payload="$(admin_json_post "${base_url}/api/v1/admin/groups" "{\"name\":\"group-${smoke_suffix}\"}")"
group_id="$(echo "${group_payload}" | jq -r '.group_id')"
admin_api -X POST "${base_url}/api/v1/admin/users/${group_user_id}/groups/${group_id}" >/dev/null
group_stream_payload="$(admin_json_post "${base_url}/api/v1/admin/output-streams" "{\"name\":\"group-${stream_name}\",\"public_name\":\"group-${stream_name}\",\"title\":\"group-${stream_name}\",\"playback_path\":\"group-${stream_name}\"}")"
group_stream_id="$(echo "${group_stream_payload}" | jq -r '.output_stream_id')"
admin_json_post "${base_url}/api/v1/admin/output-streams/${group_stream_id}/grant-group" "{\"group_id\":\"${group_id}\"}" >/dev/null
group_streams_payload="$(curl_api "${base_url}/api/v1/streams?user_id=${group_user_id}")"
group_playback_payload="$(json_post "${base_url}/api/v1/playback-token" "{\"user_id\":\"${group_user_id}\",\"output_stream_id\":\"${group_stream_id}\"}")"
if echo "${group_streams_payload}" | jq -e --arg stream_id "${group_stream_id}" '.output_streams | map(.output_stream_id) | index($stream_id) != null' >/dev/null \
  && [[ "$(echo "${group_playback_payload}" | jq -r '.output_stream_id')" == "${group_stream_id}" ]]; then
  group_acl_ok=true
fi

info "creating verification user and stream"
user_payload="$(json_post "${base_url}/api/v1/enroll" "{\"display_name\":\"Verification User ${smoke_suffix}\"}")"
user_id="$(echo "${user_payload}" | jq -r '.user_id')"
user_client_code="$(echo "${user_payload}" | jq -r '.client_code')"
admin_json_post "${base_url}/api/v1/admin/users/${user_id}/approve" '{}' >/dev/null

stream_payload="$(admin_json_post "${base_url}/api/v1/admin/output-streams" "{\"name\":\"${stream_name}\",\"public_name\":\"${stream_name}\",\"title\":\"${stream_name}\",\"playback_path\":\"${stream_name}\"}")"
stream_id="$(echo "${stream_payload}" | jq -r '.output_stream_id')"
playback_name="$(echo "${stream_payload}" | jq -r '.playback_path')"
admin_json_post "${base_url}/api/v1/admin/output-streams/${stream_id}/grant-user" "{\"user_id\":\"${user_id}\"}" >/dev/null

ingest_payload="$(admin_json_post "${base_url}/api/v1/admin/ingest-sessions" "{\"current_output_stream_id\":\"${stream_id}\",\"source_label\":\"verification-publisher\"}")"
ingest_session_id="$(echo "${ingest_payload}" | jq -r '.ingest_session_id')"
ingest_key="$(echo "${ingest_payload}" | jq -r '.ingest_key')"

if [[ "${playback_name}" != "${ingest_key}" ]]; then
  playback_path_is_distinct_from_ingest_key=true
fi

public_streams_payload="$(curl_api "${base_url}/api/v1/streams?user_id=${user_id}")"
viewer_session_payload="$(json_post "${base_url}/api/v1/viewer/session" "{\"client_code\":\"${user_client_code}\"}")"
viewer_token="$(echo "${viewer_session_payload}" | jq -r '.viewer_token // empty')"
viewer_streams_payload="$(curl_api "${base_url}/api/v1/viewer/streams" -H "Authorization: Bearer ${viewer_token}")"
if echo "${public_streams_payload}" | jq -e --arg stream_id "${stream_id}" --arg playback_path "${playback_name}" '
  (.output_streams | length) == 1
  and .output_streams[0].output_stream_id == $stream_id
  and .output_streams[0].playback_path == $playback_path
  and (. | tostring | contains("ingest_key") | not)
  and (. | tostring | contains("source_ingest_session_id") | not)
' >/dev/null \
  && echo "${viewer_streams_payload}" | jq -e --arg stream_id "${stream_id}" --arg playback_path "${playback_name}" '
  (.streams | length) == 1
  and .streams[0].output_stream_id == $stream_id
  and .streams[0].playback_path == $playback_path
  and (. | tostring | contains("ingest_key") | not)
  and (. | tostring | contains("source_ingest_session_id") | not)
' >/dev/null; then
  viewer_api_hides_ingest_key=true
fi

playback_token_payload="$(json_post "${base_url}/api/v1/playback-token" "{\"user_id\":\"${user_id}\",\"output_stream_id\":\"${stream_id}\"}")"
playback_token="$(echo "${playback_token_payload}" | jq -r '.token')"
playback_url="$(echo "${playback_token_payload}" | jq -r '.playback_url')"
json_post "${base_url}/api/v1/playback-token" "{\"user_id\":\"${user_id}\",\"playback_path\":\"${playback_name}\"}" >/dev/null

if [[ "${playback_url}" == *"/live/${playback_name}/whep?token="* && "${playback_url}" != *"${ingest_key}"* ]]; then
  whep_url_uses_playback_path=true
fi

reject_body_file="${tmp_dir}/playback-token-reject.json"
reject_code="$(curl -s -o "${reject_body_file}" -w '%{http_code}' "${curl_base_opts[@]}" -X POST "${base_url}/api/v1/playback-token" -H 'content-type: application/json' -d "{\"user_id\":\"${user_id}\",\"playback_path\":\"${ingest_key}\"}")"
if [[ "${reject_code}" == "400" ]] && jq -e '.error.code == "ingest_key_not_playback_identifier"' "${reject_body_file}" >/dev/null; then
  playback_token_rejects_ingest_key=true
fi

if curl_api "${base_url}/" >/dev/null 2>&1; then
  nginx_ok=true
fi

valid_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"whep\",\"query\":\"token=${playback_token}\"}")"
invalid_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"whep\",\"query\":\"token=invalid\"}")"
rtmp_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"rtmp\",\"query\":\"token=${playback_token}\"}")"
if [[ "${valid_code}" == "200" && "${invalid_code}" == "401" && "${rtmp_code}" == "401" ]]; then
  playback_auth_ok=true
fi

if [[ "${VERIFY_TURN:-true}" == "true" ]]; then
  if check_turn_reachable; then
    turn_reachable=true
  fi
else
  media_notes="${media_notes}; TURN verification skipped by config"
fi

info "publishing deterministic synthetic RTMP test stream for ${smoke_duration}s"
ffmpeg -loglevel error -re \
  -f lavfi -i "testsrc=size=640x360:rate=15,format=yuv420p" \
  -f lavfi -i "sine=frequency=1000:sample_rate=48000:beep_factor=2" \
  -c:v libx264 -pix_fmt yuv420p \
  -c:a aac -b:a 128k \
  -t "${smoke_duration}" \
  -f flv "rtmp://127.0.0.1:${RTMP_PORT}/live/${ingest_key}" >"${ffmpeg_log}" 2>&1 &
ffmpeg_pid="$!"

if poll_ingest_status "live" && kill -0 "${ffmpeg_pid}" >/dev/null 2>&1; then
  rtmp_ingest_ok=true
fi

if [[ "${VERIFY_RTMP_PLAYBACK_BLOCK:-true}" == "true" ]]; then
  if ! ffprobe -v error -rw_timeout 5000000 -show_entries stream=codec_type -of default=noprint_wrappers=1 "rtmp://127.0.0.1:${RTMP_PORT}/live/${ingest_key}" >/dev/null 2>&1; then
    rtmp_read_blocked_on_ingest_path=true
  fi
  if ! ffprobe -v error -rw_timeout 5000000 -show_entries stream=codec_type -of default=noprint_wrappers=1 "rtmp://127.0.0.1:${RTMP_PORT}/live/${playback_name}" >/dev/null 2>&1; then
    rtmp_read_blocked_on_output_path=true
  fi
  if [[ "${rtmp_read_blocked_on_ingest_path}" == "true" && "${rtmp_read_blocked_on_output_path}" == "true" ]]; then
    rtmp_playback_blocked=true
  fi
else
  media_notes="${media_notes}; RTMP playback block verification skipped by config"
fi

if [[ "${VERIFY_BROWSERLESS_WHEP:-true}" == "true" ]]; then
  if check_whep_http_semantics; then
    whep_or_webrtc_endpoint_ok=true
  fi
else
  media_notes="${media_notes}; browserless WHEP verification skipped by config"
fi

if [[ "${ENABLE_TLS}" == "true" && "${whep_or_webrtc_endpoint_ok}" == "true" ]]; then
  media_encryption_ok=true
fi

stop_publisher
compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/publish-stop?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"path\":\"live/${ingest_key}\"}" | grep -q '^200$' || true
poll_ingest_status "ended" || true

if [[ "${rtmp_ingest_ok}" != "true" && -s "${ffmpeg_log}" ]]; then
  media_notes="${media_notes}; ffmpeg_publish_log=$(tr '\n' ' ' < "${ffmpeg_log}" | cut -c1-240)"
fi

write_state

[[ "${admin_auth_ok}" == "true" ]] || fail "admin auth verification failed"
[[ "${admin_ui_ok}" == "true" ]] || fail "admin ui verification failed"
[[ "${user_moderation_ok}" == "true" ]] || fail "user moderation verification failed"
[[ "${group_acl_ok}" == "true" ]] || fail "group acl verification failed"
[[ "${nginx_ok}" == "true" ]] || fail "nginx did not answer during media verification"
[[ "${viewer_api_hides_ingest_key}" == "true" ]] || fail "viewer-facing API leaked ingest linkage or omitted output_stream playback mapping"
[[ "${playback_token_rejects_ingest_key}" == "true" ]] || fail "playback token endpoint accepted ingest key semantics"
[[ "${playback_path_is_distinct_from_ingest_key}" == "true" ]] || fail "playback_path must stay distinct from ingest_key"
[[ "${whep_url_uses_playback_path}" == "true" ]] || fail "WHEP playback URL did not use output_stream.playback_path"
[[ "${playback_auth_ok}" == "true" ]] || fail "playback auth path verification failed"
[[ "${rtmp_ingest_ok}" == "true" ]] || fail "synthetic RTMP ingest did not become live"
if [[ "${VERIFY_RTMP_PLAYBACK_BLOCK:-true}" == "true" ]]; then
  [[ "${rtmp_read_blocked_on_ingest_path}" == "true" ]] || fail "RTMP read was not blocked on ingest path"
  [[ "${rtmp_read_blocked_on_output_path}" == "true" ]] || fail "RTMP read was not blocked on output path"
  [[ "${rtmp_playback_blocked}" == "true" ]] || fail "direct RTMP playback was not blocked"
fi
if [[ "${VERIFY_BROWSERLESS_WHEP:-true}" == "true" ]]; then
  [[ "${whep_or_webrtc_endpoint_ok}" == "true" ]] || fail "WHEP/WebRTC endpoint did not expose expected auth/http semantics"
fi
if [[ "${VERIFY_TURN:-true}" == "true" ]]; then
  [[ "${turn_reachable}" == "true" ]] || fail "TURN service was not reachable on TCP port ${TURN_PORT}"
fi

success "media smoke verification passed"
