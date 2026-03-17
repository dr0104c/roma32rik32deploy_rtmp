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

report_dir="${VERIFY_REPORT_DIR:-deploy}"
mkdir -p "${PROJECT_ROOT}/${report_dir}"
json_report="${PROJECT_ROOT}/${report_dir}/verification-report.json"
txt_report="${PROJECT_ROOT}/${report_dir}/verification-report.txt"
timestamp_utc="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
host_or_domain="${DOMAIN_NAME:-${PUBLIC_HOST}}"

if [[ "${1:-}" == "--skipped" ]]; then
  jq -n \
    --arg timestamp "${timestamp_utc}" \
    --arg host "${host_or_domain}" \
    --arg domain "${DOMAIN_NAME}" \
    --arg tls_enabled "${ENABLE_TLS}" \
    --arg transcoding_enabled "${ENABLE_FFMPEG_TRANSCODE}" \
    '{
      timestamp: $timestamp,
      host: $host,
      domain: $domain,
      tls_enabled: ($tls_enabled == "true"),
      containers_ok: false,
      backend_ready: false,
      nginx_ok: false,
      rtmp_ingest_ok: false,
      rtmp_playback_blocked: false,
      whep_or_webrtc_endpoint_ok: false,
      turn_reachable: false,
      playback_auth_ok: false,
      media_encryption_ok: false,
      transcoding_enabled: ($transcoding_enabled == "true"),
      transcoding_verified: false,
      browser_level_rendering_verified: false,
      overall_status: "skipped",
      failed_checks: ["automated_verification_skipped"],
      notes: {
        playback_transport: "WebRTC/WHEP",
        ingest_transport: "RTMP",
        browser_rendering_verified: false,
        transcoding: (if $transcoding_enabled == "true" then "requested but not implemented in current stack" else "absent / not configured" end),
        media_verification_scope: "automated verification disabled by ENABLE_AUTOMATED_MEDIA_VERIFY=false"
      }
    }' > "${json_report}"

  cat > "${txt_report}" <<EOF
Stream Platform Verification Report
Timestamp: ${timestamp_utc}
Host/Domain: ${host_or_domain}
Domain: ${DOMAIN_NAME}
Overall status: skipped
Reason: automated verification disabled by ENABLE_AUTOMATED_MEDIA_VERIFY=false
EOF
  success "verification reports written to ${json_report} and ${txt_report}"
  exit 0
fi

state_file="${1:-${SCRIPT_DIR}/.verification-state}"
[[ -f "${state_file}" ]] || fail "verification state file not found: ${state_file}"
set -a
source "${state_file}"
source "${SCRIPT_DIR}/.media-smoke-state"
set +a

jq -n \
  --arg timestamp "${timestamp_utc}" \
  --arg host "${host_or_domain}" \
  --arg domain "${DOMAIN_NAME}" \
  --arg tls_enabled "${VERIFY_TLS_ENABLED}" \
  --arg containers_ok "${VERIFY_CONTAINERS_OK}" \
  --arg backend_ready "${VERIFY_BACKEND_READY}" \
  --arg nginx_ok "${SMOKE_NGINX_OK}" \
  --arg rtmp_ingest_ok "${SMOKE_RTMP_INGEST_OK}" \
  --arg rtmp_playback_blocked "${SMOKE_RTMP_PLAYBACK_BLOCKED}" \
  --arg whep_or_webrtc_endpoint_ok "${SMOKE_WHEP_ENDPOINT_OK}" \
  --arg turn_reachable "${SMOKE_TURN_REACHABLE}" \
  --arg playback_auth_ok "${SMOKE_PLAYBACK_AUTH_OK}" \
  --arg media_encryption_ok "${SMOKE_MEDIA_ENCRYPTION_OK}" \
  --arg transcoding_enabled "${SMOKE_TRANSCODING_ENABLED}" \
  --arg transcoding_verified "${SMOKE_TRANSCODING_VERIFIED}" \
  --arg browser_level_rendering_verified "${SMOKE_BROWSER_RENDERING_VERIFIED}" \
  --arg overall_status "${VERIFY_OVERALL_STATUS}" \
  --arg media_notes "${SMOKE_MEDIA_NOTES}" \
  --argjson failed_checks "${VERIFY_FAILED_CHECKS_JSON}" \
  '{
    timestamp: $timestamp,
    host: $host,
    domain: $domain,
    tls_enabled: ($tls_enabled == "true"),
    containers_ok: ($containers_ok == "true"),
    backend_ready: ($backend_ready == "true"),
    nginx_ok: ($nginx_ok == "true"),
    rtmp_ingest_ok: ($rtmp_ingest_ok == "true"),
    rtmp_playback_blocked: ($rtmp_playback_blocked == "true"),
    whep_or_webrtc_endpoint_ok: ($whep_or_webrtc_endpoint_ok == "true"),
    turn_reachable: ($turn_reachable == "true"),
    playback_auth_ok: ($playback_auth_ok == "true"),
    media_encryption_ok: ($media_encryption_ok == "true"),
    transcoding_enabled: ($transcoding_enabled == "true"),
    transcoding_verified: ($transcoding_verified == "true"),
    browser_level_rendering_verified: ($browser_level_rendering_verified == "true"),
    overall_status: $overall_status,
    failed_checks: $failed_checks,
    notes: {
      playback_transport: "WebRTC/WHEP",
      ingest_transport: "RTMP",
      browser_rendering_verified: ($browser_level_rendering_verified == "true"),
      transcoding: (if $transcoding_enabled == "true" and $transcoding_verified != "true" then "requested but not implemented in current stack" elif $transcoding_enabled == "true" then "enabled and verified" else "absent / not configured" end),
      media_verification_scope: $media_notes
    }
  }' > "${json_report}"

cat > "${txt_report}" <<EOF
Stream Platform Verification Report
Timestamp: ${timestamp_utc}
Host/Domain: ${host_or_domain}
Domain: ${DOMAIN_NAME}
TLS enabled: ${VERIFY_TLS_ENABLED}
Containers OK: ${VERIFY_CONTAINERS_OK}
Backend ready: ${VERIFY_BACKEND_READY}
nginx OK: ${SMOKE_NGINX_OK}
RTMP ingest accepted: ${SMOKE_RTMP_INGEST_OK}
RTMP playback blocked: ${SMOKE_RTMP_PLAYBACK_BLOCKED}
WHEP/WebRTC endpoint OK: ${SMOKE_WHEP_ENDPOINT_OK}
TURN reachable: ${SMOKE_TURN_REACHABLE}
Playback auth OK: ${SMOKE_PLAYBACK_AUTH_OK}
Protected playback channel OK: ${SMOKE_MEDIA_ENCRYPTION_OK}
Transcoding enabled: ${SMOKE_TRANSCODING_ENABLED}
Transcoding verified: ${SMOKE_TRANSCODING_VERIFIED}
Browser-level rendering verified: ${SMOKE_BROWSER_RENDERING_VERIFIED}
Overall status: ${VERIFY_OVERALL_STATUS}

Media semantics:
- ingest accepted: ${SMOKE_RTMP_INGEST_OK}
- stream republished to WebRTC/WHEP: ${SMOKE_WHEP_ENDPOINT_OK}
- playback transport encrypted: ${SMOKE_MEDIA_ENCRYPTION_OK}
- transcoding enabled: ${SMOKE_TRANSCODING_ENABLED}
- transcoding verified: ${SMOKE_TRANSCODING_VERIFIED}
- browser rendering verified: ${SMOKE_BROWSER_RENDERING_VERIFIED}

Notes:
- ${SMOKE_MEDIA_NOTES}
- RTMP ingest is plain RTMP and not encrypted unless RTMPS is added later.
- Direct RTMP playback is intentionally blocked.
- If TLS is disabled, playback auth can still work while encrypted playback remains false.

Failed checks:
${VERIFY_FAILED_CHECKS_TEXT}
EOF

success "verification reports written to ${json_report} and ${txt_report}"
