#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_ROOT="/opt/stream-platform"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"
setup_trap

SUMMARY_LINES=()

record_pass() {
  SUMMARY_LINES+=("[PASS] $*")
  pass "$*"
}

record_fail() {
  SUMMARY_LINES+=("[FAIL] $*")
  fail_line "$*"
}

print_summary() {
  printf '\n=== Deploy Summary ===\n'
  local line
  for line in "${SUMMARY_LINES[@]}"; do
    printf '%s\n' "${line}"
  done
}

ensure_bookworm() {
  . /etc/os-release
  [[ "${ID:-}" == "debian" ]] || fail "unsupported OS: ${ID:-unknown}"
  [[ "${VERSION_CODENAME:-}" == "bookworm" ]] || fail "unsupported Debian codename: ${VERSION_CODENAME:-unknown}"
}

install_base_packages() {
  info "installing base packages"
  run_as_root apt-get update
  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl gnupg jq ffmpeg rsync lsb-release sudo python3 python3-venv
}

bootstrap_local_python_venv() {
  info "bootstrapping local python venv for server-side tests and utilities"
  cd "${TARGET_ROOT}"
  python3 -m venv --clear .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r backend/requirements.txt
}

install_docker() {
  info "installing docker and compose"
  if ! command -v docker >/dev/null 2>&1; then
    run_as_root install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
      curl -fsSL https://download.docker.com/linux/debian/gpg | run_as_root gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      run_as_root chmod a+r /etc/apt/keyrings/docker.gpg
    fi
    if [[ ! -f /etc/apt/sources.list.d/docker.list ]]; then
      echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
        ${VERSION_CODENAME} stable" | run_as_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    fi
    run_as_root apt-get update
  fi

  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  run_as_root systemctl enable --now docker
  if [[ -n "${SUDO_USER:-}" ]]; then
    run_as_root usermod -aG docker "${SUDO_USER}" || true
  fi
}

sync_project() {
  info "syncing project into ${TARGET_ROOT}"
  run_as_root mkdir -p "${TARGET_ROOT}"
  if [[ "${SOURCE_ROOT}" != "${TARGET_ROOT}" ]]; then
    run_as_root rsync -a --delete \
      --exclude '.git' \
      --exclude '.env' \
      --exclude '__pycache__' \
      "${SOURCE_ROOT}/" "${TARGET_ROOT}/"
  fi
  if [[ -n "${SUDO_USER:-}" ]]; then
    run_as_root chown -R "${SUDO_USER}:${SUDO_USER}" "${TARGET_ROOT}"
  fi
  chmod +x "${TARGET_ROOT}"/deploy/*.sh "${TARGET_ROOT}/install.sh" "${TARGET_ROOT}/bootstrap-install.sh"
}

validate_production_env() {
  cd "${TARGET_ROOT}"
  local enable_tls domain_name acme_email admin_secret admin_jwt_secret admin_bootstrap_password playback_secret viewer_secret internal_secret pg_password turn_secret http_port https_port
  enable_tls="$(env_get ENABLE_TLS .env)"
  domain_name="$(env_get DOMAIN_NAME .env)"
  acme_email="$(env_get ACME_EMAIL .env)"
  admin_secret="$(env_get ADMIN_SECRET .env)"
  admin_jwt_secret="$(env_get ADMIN_JWT_SECRET .env)"
  admin_bootstrap_password="$(env_get ADMIN_BOOTSTRAP_PASSWORD .env)"
  playback_secret="$(env_get PLAYBACK_TOKEN_SECRET .env)"
  viewer_secret="$(env_get VIEWER_SESSION_SECRET .env)"
  internal_secret="$(env_get INTERNAL_API_SECRET .env)"
  pg_password="$(env_get POSTGRES_PASSWORD .env)"
  turn_secret="$(env_get TURN_SHARED_SECRET .env)"
  http_port="$(env_get NGINX_HTTP_PORT .env)"
  https_port="$(env_get NGINX_HTTPS_PORT .env)"

  if [[ "${enable_tls}" == "true" ]]; then
    [[ -n "${domain_name}" ]] || fail "ENABLE_TLS=true requires DOMAIN_NAME"
    [[ -n "${acme_email}" ]] || fail "ENABLE_TLS=true requires ACME_EMAIL"
    [[ "${http_port}" == "80" ]] || fail "ENABLE_TLS=true requires NGINX_HTTP_PORT=80 for ACME bootstrap"
    [[ "${https_port}" == "443" ]] || fail "ENABLE_TLS=true requires NGINX_HTTPS_PORT=443"
  fi

  local item
  for item in "${admin_secret}" "${admin_jwt_secret}" "${admin_bootstrap_password}" "${playback_secret}" "${viewer_secret}" "${internal_secret}" "${pg_password}" "${turn_secret}"; do
    [[ "${#item}" -ge 24 ]] || fail "detected weak secret in .env"
    [[ ! "${item}" =~ ^(change-me|REPLACE_STRONG_SECRET|example.com)$ ]] || fail "detected placeholder secret in .env"
  done
}

bootstrap_env() {
  info "bootstrapping environment"
  cd "${TARGET_ROOT}"
  local template=".env.example"
  [[ -f .env ]] || cp "${template}" .env
  ./deploy/bootstrap-secrets.sh "${TARGET_ROOT}/.env" "${TARGET_ROOT}/${template}"

  local detected_host pg_password postgres_user postgres_db enable_tls domain_name public_base_url webrtc_public_base_url stun_urls turn_urls http_port
  detected_host="$(hostname -I | awk '{print $1}')"
  [[ -n "${detected_host}" ]] || detected_host="127.0.0.1"

  grep -q '^PUBLIC_HOST=' .env || echo "PUBLIC_HOST=${detected_host}" >> .env
  grep -q '^ADMIN_BOOTSTRAP_USERNAME=' .env || echo 'ADMIN_BOOTSTRAP_USERNAME=admin' >> .env
  grep -q '^ADMIN_ACCESS_TOKEN_TTL_SECONDS=' .env || echo 'ADMIN_ACCESS_TOKEN_TTL_SECONDS=3600' >> .env
  grep -q '^LEGACY_ADMIN_SECRET_ENABLED=' .env || echo 'LEGACY_ADMIN_SECRET_ENABLED=true' >> .env
  grep -q '^VIEWER_SESSION_TTL_SECONDS=' .env || echo 'VIEWER_SESSION_TTL_SECONDS=86400' >> .env
  grep -q '^PLAYBACK_TOKEN_TTL_SECONDS=' .env || echo 'PLAYBACK_TOKEN_TTL_SECONDS=120' >> .env
  grep -q '^STREAM_LIST_POLL_INTERVAL_SECONDS=' .env || echo 'STREAM_LIST_POLL_INTERVAL_SECONDS=5' >> .env
  grep -q '^LOG_LEVEL=' .env || echo 'LOG_LEVEL=INFO' >> .env
  grep -q '^ACCESS_LOG_ENABLED=' .env || echo 'ACCESS_LOG_ENABLED=true' >> .env
  grep -q '^MEDIAMTX_LOG_LEVEL=' .env || echo 'MEDIAMTX_LOG_LEVEL=info' >> .env
  grep -q '^INGEST_AUTH_MODE=' .env || echo 'INGEST_AUTH_MODE=open' >> .env
  grep -q '^INTERNAL_MEDIA_SECRET_REQUIRED=' .env || echo 'INTERNAL_MEDIA_SECRET_REQUIRED=true' >> .env
  grep -q '^MEDIAMTX_CONTROL_API_BASE_URL=' .env || echo 'MEDIAMTX_CONTROL_API_BASE_URL=http://mediamtx:9997/v3' >> .env
  grep -q '^ENABLE_FFMPEG_TRANSCODE=' .env || echo 'ENABLE_FFMPEG_TRANSCODE=false' >> .env
  grep -q '^ENABLE_AUTOMATED_MEDIA_VERIFY=' .env || echo 'ENABLE_AUTOMATED_MEDIA_VERIFY=true' >> .env
  grep -q '^VERIFY_TURN=' .env || echo 'VERIFY_TURN=true' >> .env
  grep -q '^VERIFY_BROWSERLESS_WHEP=' .env || echo 'VERIFY_BROWSERLESS_WHEP=true' >> .env
  grep -q '^VERIFY_RTMP_PLAYBACK_BLOCK=' .env || echo 'VERIFY_RTMP_PLAYBACK_BLOCK=true' >> .env
  grep -q '^VERIFY_REPORT_DIR=' .env || echo 'VERIFY_REPORT_DIR=deploy' >> .env
  grep -q '^MEDIA_SMOKE_TEST_DURATION_SEC=' .env || echo 'MEDIA_SMOKE_TEST_DURATION_SEC=12' >> .env
  grep -q '^MEDIA_SMOKE_TEST_STREAM_NAME=' .env || echo 'MEDIA_SMOKE_TEST_STREAM_NAME=verification-smoke' >> .env
  grep -q '^BACKUP_RETENTION=' .env || echo 'BACKUP_RETENTION=7' >> .env
  grep -q '^DOMAIN_NAME=' .env || echo 'DOMAIN_NAME=' >> .env
  grep -q '^ACME_EMAIL=' .env || echo 'ACME_EMAIL=' >> .env
  grep -q '^ENABLE_TLS=' .env || echo 'ENABLE_TLS=false' >> .env
  grep -q '^TURN_EXTERNAL_IP=' .env || echo "TURN_EXTERNAL_IP=${detected_host}" >> .env
  grep -q '^TURN_MIN_PORT=' .env || echo 'TURN_MIN_PORT=49160' >> .env
  grep -q '^TURN_MAX_PORT=' .env || echo 'TURN_MAX_PORT=49200' >> .env
  grep -q '^WEBRTC_ICE_PORT=' .env || echo 'WEBRTC_ICE_PORT=8189' >> .env
  grep -q '^SSH_PORT=' .env || echo 'SSH_PORT=22' >> .env
  grep -q '^SSH_KEY_ONLY=' .env || echo 'SSH_KEY_ONLY=false' >> .env
  grep -q '^NGINX_HTTPS_PORT=' .env || echo 'NGINX_HTTPS_PORT=8443' >> .env

  pg_password="$(env_get POSTGRES_PASSWORD .env)"
  postgres_user="$(env_get POSTGRES_USER .env)"
  postgres_db="$(env_get POSTGRES_DB .env)"
  enable_tls="$(env_get ENABLE_TLS .env)"
  domain_name="$(env_get DOMAIN_NAME .env)"
  http_port="$(env_get NGINX_HTTP_PORT .env)"

  if [[ "${enable_tls}" == "true" && -n "${domain_name}" ]]; then
    public_base_url="https://${domain_name}"
    webrtc_public_base_url="https://${domain_name}/webrtc"
    stun_urls="stun:${domain_name}:3478"
    turn_urls="turn:${domain_name}:3478?transport=udp,turn:${domain_name}:3478?transport=tcp"
  else
    public_base_url="http://${detected_host}:${http_port}"
    webrtc_public_base_url="http://${detected_host}:${http_port}/webrtc"
    stun_urls="stun:${detected_host}:3478"
    turn_urls="turn:${detected_host}:3478?transport=udp,turn:${detected_host}:3478?transport=tcp"
  fi

  sed -i "s|^DATABASE_URL=.*$|DATABASE_URL=postgresql+psycopg://${postgres_user}:${pg_password}@postgres:5432/${postgres_db}|" .env
  sed -i "s|^PUBLIC_HOST=.*$|PUBLIC_HOST=${domain_name:-${detected_host}}|" .env
  sed -i "s|^PUBLIC_BASE_URL=.*$|PUBLIC_BASE_URL=${public_base_url}|" .env
  sed -i "s|^WEBRTC_PUBLIC_BASE_URL=.*$|WEBRTC_PUBLIC_BASE_URL=${webrtc_public_base_url}|" .env
  sed -i "s|^STUN_URLS=.*$|STUN_URLS=${stun_urls}|" .env
  sed -i "s|^TURN_URLS=.*$|TURN_URLS=${turn_urls}|" .env
  chmod 600 .env
  validate_production_env
}

render_nginx_mode() {
  cd "${TARGET_ROOT}"
  local enable_tls domain_name server_name template cert_path
  enable_tls="$(env_get ENABLE_TLS .env)"
  domain_name="$(env_get DOMAIN_NAME .env)"
  server_name="${domain_name:-_}"
  cert_path="${TARGET_ROOT}/certs/letsencrypt/live/${domain_name}/fullchain.pem"
  template="nginx/conf.d/http.conf"
  if [[ "${enable_tls}" == "true" && -n "${domain_name}" && -f "${cert_path}" ]]; then
    template="nginx/conf.d/https.conf"
  fi

  sed \
    -e "s|__SERVER_NAME__|${server_name}|g" \
    -e "s|__DOMAIN_NAME__|${domain_name}|g" \
    "${template}" > nginx/conf.d/active.conf
}

render_runtime_configs() {
  info "rendering runtime configs"
  cd "${TARGET_ROOT}"
  mkdir -p certs/letsencrypt nginx/certbot/www
  run_as_root mkdir -p /var/log/stream-platform
  set -a
  source .env
  set +a
  mkdir -p "${VERIFY_REPORT_DIR:-deploy}"

  sed \
    -e "s|\${PUBLIC_HOST}|${PUBLIC_HOST}|g" \
    -e "s|\${TURN_SHARED_SECRET}|${TURN_SHARED_SECRET}|g" \
    -e "s|\${INTERNAL_API_SECRET}|${INTERNAL_API_SECRET}|g" \
    -e "s|\${MEDIAMTX_LOG_LEVEL}|${MEDIAMTX_LOG_LEVEL}|g" \
    mediamtx/mediamtx.yml > mediamtx/mediamtx.runtime.yml

  sed \
    -e "s|\${TURN_REALM}|${TURN_REALM}|g" \
    -e "s|\${TURN_SHARED_SECRET}|${TURN_SHARED_SECRET}|g" \
    -e "s|\${TURN_EXTERNAL_IP}|${TURN_EXTERNAL_IP}|g" \
    -e "s|\${TURN_MIN_PORT}|${TURN_MIN_PORT}|g" \
    -e "s|\${TURN_MAX_PORT}|${TURN_MAX_PORT}|g" \
    coturn/turnserver.conf > coturn/turnserver.runtime.conf

  render_nginx_mode
}

start_stack() {
  info "starting docker compose stack"
  cd "${TARGET_ROOT}"
  compose up -d --build
}

run_db_migrations() {
  info "applying database migrations"
  cd "${TARGET_ROOT}"
  local pg_user pg_db
  pg_user="$(env_get POSTGRES_USER .env)"
  pg_db="$(env_get POSTGRES_DB .env)"
  local migration
  local ordered_migrations=()
  [[ -f sql/001_init.sql ]] && ordered_migrations+=("sql/001_init.sql")
  [[ -f sql/002_seed.sql ]] && ordered_migrations+=("sql/002_seed.sql")
  [[ -f sql/003_server_beta.sql ]] && ordered_migrations+=("sql/003_server_beta.sql")
  [[ -f sql/004_product_model.sql ]] && ordered_migrations+=("sql/004_product_model.sql")
  [[ -f sql/005_product_model_hotfix.sql ]] && ordered_migrations+=("sql/005_product_model_hotfix.sql")
  [[ -f sql/006_admin_auth.sql ]] && ordered_migrations+=("sql/006_admin_auth.sql")
  for migration in "${ordered_migrations[@]}"; do
    compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${pg_user}" -d "${pg_db}" < "${migration}"
  done
}

setup_tls() {
  cd "${TARGET_ROOT}"
  if [[ "$(env_get ENABLE_TLS .env)" != "true" ]]; then
    info "tls disabled; staying in http bootstrap mode"
    return 0
  fi

  info "obtaining or renewing TLS certificate"
  ./deploy/certbot-renew.sh
  render_nginx_mode
  compose restart nginx
}

install_ops_files() {
  info "installing operational support files"
  cd "${TARGET_ROOT}"
  run_as_root install -d -m 0755 /var/log/stream-platform
  run_as_root install -d -m 0755 /etc/fail2ban/jail.d
  run_as_root install -m 0644 ops/fail2ban/jail.local.example /etc/fail2ban/jail.d/stream-platform.local
  run_as_root install -m 0644 ops/logrotate/stream-platform /etc/logrotate.d/stream-platform

  install_systemd_unit ops/systemd/stream-platform-backup.service
  install_systemd_unit ops/systemd/stream-platform-backup.timer
  install_systemd_unit ops/systemd/stream-platform-cert-renew.service
  install_systemd_unit ops/systemd/stream-platform-cert-renew.timer
  install_systemd_unit ops/systemd/stream-platform-healthcheck.service
  install_systemd_unit ops/systemd/stream-platform-healthcheck.timer
  run_as_root systemctl daemon-reload
  run_as_root systemctl enable --now \
    stream-platform-backup.timer \
    stream-platform-cert-renew.timer \
    stream-platform-healthcheck.timer
  run_as_root systemctl restart fail2ban
}

wait_ready() {
  info "waiting for stack readiness"
  cd "${TARGET_ROOT}"
  wait_for_compose_service postgres running 60 2 || fail "postgres did not become running"
  wait_for_compose_service backend running 60 2 || fail "backend did not become running"
  wait_for_compose_service nginx running 60 2 || fail "nginx did not become running"

  local scheme host port curl_opts=() url
  if [[ "$(env_get ENABLE_TLS .env)" == "true" && -f "${TARGET_ROOT}/certs/letsencrypt/live/$(env_get DOMAIN_NAME .env)/fullchain.pem" ]]; then
    scheme="https"
    host="$(env_get DOMAIN_NAME .env)"
    port="$(env_get NGINX_HTTPS_PORT .env)"
    curl_opts=(-k --resolve "${host}:${port}:127.0.0.1")
  else
    scheme="http"
    host="127.0.0.1"
    port="$(env_get NGINX_HTTP_PORT .env)"
  fi
  url="${scheme}://${host}:${port}/health/ready"

  local i
  for i in $(seq 1 90); do
    if curl -fsS "${curl_opts[@]}" "${url}" >/dev/null 2>&1; then
      success "backend readiness endpoint is healthy"
      return 0
    fi
    sleep 2
  done
  fail "backend readiness check did not become ready"
}

run_verification() {
  info "running post-deploy verification"
  cd "${TARGET_ROOT}"
  if [[ "$(env_get ENABLE_AUTOMATED_MEDIA_VERIFY .env)" != "true" ]]; then
    warn "ENABLE_AUTOMATED_MEDIA_VERIFY=false; writing skipped verification report"
    ./deploy/write-verification-report.sh --skipped
    return 0
  fi
  bootstrap_local_python_venv
  ./deploy/verify-stack.sh
}

final_summary() {
  cd "${TARGET_ROOT}"
  local tls_enabled public_base_url webrtc_base_url public_host rtmp_port transcoding_enabled report_dir report_json report_txt
  local deploy_status whep_available encrypted_playback rtmp_blocked overall_status
  tls_enabled="$(env_get ENABLE_TLS .env)"
  public_base_url="$(env_get PUBLIC_BASE_URL .env)"
  webrtc_base_url="$(env_get WEBRTC_PUBLIC_BASE_URL .env)"
  public_host="$(env_get PUBLIC_HOST .env)"
  rtmp_port="$(env_get RTMP_PORT .env)"
  transcoding_enabled="$(env_get ENABLE_FFMPEG_TRANSCODE .env)"
  report_dir="$(env_get VERIFY_REPORT_DIR .env)"
  [[ -n "${report_dir}" ]] || report_dir="deploy"
  report_json="${TARGET_ROOT}/${report_dir}/verification-report.json"
  report_txt="${TARGET_ROOT}/${report_dir}/verification-report.txt"
  overall_status="failed"
  whep_available="NO"
  encrypted_playback="NO"
  rtmp_blocked="NO"

  if [[ -f "${report_json}" ]]; then
    overall_status="$(jq -r '.overall_status // "failed"' "${report_json}")"
    [[ "$(jq -r '.whep_or_webrtc_endpoint_ok // false' "${report_json}")" == "true" ]] && whep_available="YES"
    [[ "$(jq -r '.media_encryption_ok // false' "${report_json}")" == "true" ]] && encrypted_playback="YES"
    [[ "$(jq -r '.rtmp_playback_blocked // false' "${report_json}")" == "true" ]] && rtmp_blocked="YES"
  fi

  if [[ "${overall_status}" == "passed" || "${overall_status}" == "skipped" ]]; then
    deploy_status="SUCCESS"
  else
    deploy_status="FAILED"
  fi

  printf '\n=== Final Summary ===\n'
  printf 'Deploy status: %s\n' "${deploy_status}"
  printf 'Backend URL: %s/health\n' "${public_base_url}"
  printf 'API URL: %s/api/\n' "${public_base_url}"
  printf 'Viewer/media URL: %s/\n' "${webrtc_base_url}"
  printf 'RTMP ingest endpoint: rtmp://%s:%s/live/{ingest_key}\n' "${public_host}" "${rtmp_port}"
  printf 'RTMP playback blocked: %s\n' "${rtmp_blocked}"
  printf 'WebRTC/WHEP playback available: %s\n' "${whep_available}"
  printf 'TLS enabled: %s\n' "$( [[ "${tls_enabled}" == "true" ]] && echo YES || echo NO )"
  printf 'Encrypted playback: %s\n' "${encrypted_playback}"
  printf 'Transcoding enabled: %s\n' "$( [[ "${transcoding_enabled}" == "true" ]] && echo YES || echo NO )"
  if [[ "${transcoding_enabled}" == "true" ]]; then
    printf 'Transcoding verification: NOT VERIFIED unless a real transcoding pipeline is added\n'
  else
    printf 'Transcoding verification: disabled / not configured\n'
  fi
  printf 'Verification report JSON: %s\n' "${report_json}"
  printf 'Verification report TXT: %s\n\n' "${report_txt}"

  info "printing operational summary"
  ./deploy/health-summary.sh || true
}

main() {
  ensure_bookworm
  record_pass "Debian Bookworm detected"

  install_base_packages
  record_pass "base packages installed"

  if ./deploy/host-hardening.sh "${TARGET_ROOT}/.env"; then
    record_pass "pre-sync host hardening applied safely"
  else
    warn "pre-sync host hardening was skipped"
  fi

  install_docker
  record_pass "docker and compose installed"

  sync_project
  record_pass "project synchronized to ${TARGET_ROOT}"

  bootstrap_env
  record_pass ".env prepared with strong secrets and 0600 permissions"

  ./deploy/host-hardening.sh "${TARGET_ROOT}/.env"
  record_pass "host hardening applied with final env"

  render_runtime_configs
  record_pass "runtime configs rendered"

  start_stack
  record_pass "docker compose stack started"

  run_db_migrations
  record_pass "database migrations applied"

  setup_tls
  record_pass "tls/bootstrap mode configured"

  ./deploy/firewall.sh "${TARGET_ROOT}/.env"
  record_pass "firewall applied"

  install_ops_files
  record_pass "systemd timers and ops files installed"

  wait_ready
  record_pass "stack readiness confirmed"

  run_verification
  record_pass "post-deploy verification passed"

  final_summary
  record_pass "final health summary generated"

  print_summary
  success "deploy completed successfully"
}

main "$@"
