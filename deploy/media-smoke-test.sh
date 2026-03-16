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
smoke_suffix="$(date +%s)-$$"
ffmpeg_pid=""

cleanup() {
  if [[ -n "${ffmpeg_pid}" ]] && kill -0 "${ffmpeg_pid}" >/dev/null 2>&1; then
    kill "${ffmpeg_pid}" >/dev/null 2>&1 || true
    wait "${ffmpeg_pid}" >/dev/null 2>&1 || true
  fi
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
    payload="$(curl_api "${base_url}/api/v1/admin/ingest-sessions?output_stream_id=${stream_id}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
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
    printf 'SMOKE_NGINX_OK=%q\n' "${nginx_ok}"
    printf 'SMOKE_RTMP_INGEST_OK=%q\n' "${rtmp_ingest_ok}"
    printf 'SMOKE_RTMP_PLAYBACK_BLOCKED=%q\n' "${rtmp_playback_blocked}"
    printf 'SMOKE_WHEP_ENDPOINT_OK=%q\n' "${whep_or_webrtc_endpoint_ok}"
    printf 'SMOKE_PLAYBACK_AUTH_OK=%q\n' "${playback_auth_ok}"
    printf 'SMOKE_TURN_REACHABLE=%q\n' "${turn_reachable}"
    printf 'SMOKE_MEDIA_ENCRYPTION_OK=%q\n' "${media_encryption_ok}"
    printf 'SMOKE_TRANSCODING_ENABLED=%q\n' "${ENABLE_FFMPEG_TRANSCODE}"
    printf 'SMOKE_TRANSCODING_VERIFIED=%q\n' "${transcoding_verified}"
    printf 'SMOKE_BROWSER_RENDERING_VERIFIED=%q\n' "false"
    printf 'SMOKE_MEDIA_NOTES=%q\n' "${media_notes}"
  } > "${state_file}"
}

nginx_ok=false
rtmp_ingest_ok=false
rtmp_playback_blocked=false
whep_or_webrtc_endpoint_ok=false
playback_auth_ok=false
turn_reachable=false
media_encryption_ok=false
transcoding_verified=false
media_notes="server-side media verification only; browser rendering not exercised"

stream_name="verify-main-${smoke_suffix}"
playback_name=""
user_id=""
stream_id=""
ingest_session_id=""
ingest_key=""
playback_token=""

info "creating verification user and stream"
user_id="$(json_post "${base_url}/api/v1/enroll" "{\"display_name\":\"Verification User ${smoke_suffix}\"}" | jq -r '.user_id')"
curl_api -X POST "${base_url}/api/v1/admin/users/${user_id}/approve" -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null

stream_payload="$(json_post "${base_url}/api/v1/admin/streams" "{\"name\":\"${stream_name}\",\"playback_name\":\"${stream_name}\"}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
stream_id="$(echo "${stream_payload}" | jq -r '.stream_id')"
playback_name="$(echo "${stream_payload}" | jq -r '.playback_name')"
json_post "${base_url}/api/v1/admin/streams/${stream_id}/grant-user" "{\"user_id\":\"${user_id}\"}" -H "X-Admin-Secret: ${ADMIN_SECRET}" >/dev/null

ingest_payload="$(json_post "${base_url}/api/v1/admin/ingest-sessions" "{\"output_stream_id\":\"${stream_id}\",\"publisher_label\":\"verification-publisher\",\"ingest_key\":\"${playback_name}\"}" -H "X-Admin-Secret: ${ADMIN_SECRET}")"
ingest_session_id="$(echo "${ingest_payload}" | jq -r '.ingest_session_id')"
ingest_key="$(echo "${ingest_payload}" | jq -r '.ingest_key')"
playback_token="$(json_post "${base_url}/api/v1/playback-token" "{\"user_id\":\"${user_id}\",\"stream_id\":\"${stream_id}\"}" | jq -r '.token')"

if curl_api "${base_url}/" >/dev/null 2>&1; then
  nginx_ok=true
fi

valid_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"whep\",\"query\":\"token=${playback_token}\"}")"
invalid_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"whep\",\"query\":\"token=invalid\"}")"
rtmp_code="$(compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/auth?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"action\":\"read\",\"path\":\"live/${playback_name}\",\"protocol\":\"rtmp\",\"query\":\"token=${playback_token}\"}")"
if [[ "${valid_code}" == "200" && "${invalid_code}" == "401" && "${rtmp_code}" == "401" ]]; then
  playback_auth_ok=true
fi

if check_turn_reachable; then
  turn_reachable=true
fi

info "publishing synthetic RTMP test stream"
ffmpeg -loglevel error -re \
  -f lavfi -i testsrc=size=640x360:rate=15 \
  -f lavfi -i sine=frequency=1000:sample_rate=48000 \
  -c:v libx264 -pix_fmt yuv420p \
  -c:a aac -b:a 128k \
  -shortest \
  -f flv "rtmp://127.0.0.1:${RTMP_PORT}/live/${ingest_key}" >/tmp/stream-platform-media-smoke-ffmpeg.log 2>&1 &
ffmpeg_pid="$!"

if poll_ingest_status "live"; then
  rtmp_ingest_ok=true
fi

if ! ffprobe -v error -rw_timeout 5000000 -show_entries stream=codec_type -of default=noprint_wrappers=1 "rtmp://127.0.0.1:${RTMP_PORT}/live/${playback_name}" >/dev/null 2>&1; then
  rtmp_playback_blocked=true
fi

if check_whep_http_semantics; then
  whep_or_webrtc_endpoint_ok=true
fi

if [[ "${ENABLE_TLS}" == "true" && "${whep_or_webrtc_endpoint_ok}" == "true" ]]; then
  media_encryption_ok=true
fi

cleanup
ffmpeg_pid=""
compose exec -T backend curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:8000/internal/media/publish-stop?secret=${INTERNAL_API_SECRET}" -H 'content-type: application/json' -d "{\"path\":\"live/${ingest_key}\"}" | grep -q '^200$' || true
poll_ingest_status "offline" || true

write_state

[[ "${nginx_ok}" == "true" ]] || fail "nginx did not answer during media verification"
[[ "${playback_auth_ok}" == "true" ]] || fail "playback auth path verification failed"
[[ "${rtmp_ingest_ok}" == "true" ]] || fail "synthetic RTMP ingest did not become live"
[[ "${rtmp_playback_blocked}" == "true" ]] || fail "direct RTMP playback was not blocked"
[[ "${whep_or_webrtc_endpoint_ok}" == "true" ]] || fail "WHEP/WebRTC endpoint did not expose expected auth/http semantics"
[[ "${turn_reachable}" == "true" ]] || fail "TURN service was not reachable on TCP port ${TURN_PORT}"

success "media smoke verification passed"
