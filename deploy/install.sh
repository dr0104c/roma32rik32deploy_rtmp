#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_ROOT="/opt/stream-platform"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

ensure_bookworm() {
  . /etc/os-release
  [[ "${ID:-}" == "debian" ]] || fail "unsupported OS: ${ID:-unknown}"
  [[ "${VERSION_CODENAME:-}" == "bookworm" ]] || fail "unsupported Debian codename: ${VERSION_CODENAME:-unknown}"
}

install_base_packages() {
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl gnupg jq ffmpeg rsync lsb-release
}

install_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    sudo install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
      curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      sudo chmod a+r /etc/apt/keyrings/docker.gpg
    fi
    if [[ ! -f /etc/apt/sources.list.d/docker.list ]]; then
      echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
        ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    fi
    sudo apt-get update
  fi

  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
  sudo usermod -aG docker "${USER}"
}

sync_project() {
  sudo mkdir -p "${TARGET_ROOT}"
  if [[ "${SOURCE_ROOT}" != "${TARGET_ROOT}" ]]; then
    sudo rsync -a --delete \
      --exclude '.git' \
      --exclude '.env' \
      --exclude '__pycache__' \
      "${SOURCE_ROOT}/" "${TARGET_ROOT}/"
  fi
  sudo chown -R "${USER}:${USER}" "${TARGET_ROOT}"
  chmod +x "${TARGET_ROOT}"/deploy/*.sh
}

validate_production_env() {
  cd "${TARGET_ROOT}"
  local enable_tls domain_name acme_email admin_secret playback_secret viewer_secret internal_secret pg_password turn_secret http_port https_port
  enable_tls="$(env_get ENABLE_TLS .env)"
  domain_name="$(env_get DOMAIN_NAME .env)"
  acme_email="$(env_get ACME_EMAIL .env)"
  admin_secret="$(env_get ADMIN_SECRET .env)"
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

  for item in "${admin_secret}" "${playback_secret}" "${viewer_secret}" "${internal_secret}" "${pg_password}" "${turn_secret}"; do
    [[ "${#item}" -ge 24 ]] || fail "detected weak secret in .env"
    [[ ! "${item}" =~ ^(change-me|REPLACE_STRONG_SECRET|example.com)$ ]] || fail "detected placeholder secret in .env"
  done
}

bootstrap_env() {
  cd "${TARGET_ROOT}"
  local template=".env.example"
  if [[ ! -f .env ]]; then
    cp "${template}" .env
  fi
  ./deploy/bootstrap-secrets.sh "${TARGET_ROOT}/.env" "${TARGET_ROOT}/${template}"

  local detected_host
  detected_host="$(hostname -I | awk '{print $1}')"
  [[ -n "${detected_host}" ]] || detected_host="127.0.0.1"

  grep -q '^PUBLIC_HOST=' .env || echo "PUBLIC_HOST=${detected_host}" >> .env
  grep -q '^VIEWER_SESSION_TTL_SECONDS=' .env || echo 'VIEWER_SESSION_TTL_SECONDS=86400' >> .env
  grep -q '^PLAYBACK_TOKEN_TTL_SECONDS=' .env || echo 'PLAYBACK_TOKEN_TTL_SECONDS=120' >> .env
  grep -q '^STREAM_LIST_POLL_INTERVAL_SECONDS=' .env || echo 'STREAM_LIST_POLL_INTERVAL_SECONDS=5' >> .env
  grep -q '^LOG_LEVEL=' .env || echo 'LOG_LEVEL=INFO' >> .env
  grep -q '^ACCESS_LOG_ENABLED=' .env || echo 'ACCESS_LOG_ENABLED=true' >> .env
  grep -q '^MEDIAMTX_LOG_LEVEL=' .env || echo 'MEDIAMTX_LOG_LEVEL=info' >> .env
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

  local pg_password postgres_user postgres_db enable_tls domain_name public_base_url webrtc_public_base_url stun_urls turn_urls
  pg_password="$(env_get POSTGRES_PASSWORD .env)"
  postgres_user="$(env_get POSTGRES_USER .env)"
  postgres_db="$(env_get POSTGRES_DB .env)"
  enable_tls="$(env_get ENABLE_TLS .env)"
  domain_name="$(env_get DOMAIN_NAME .env)"

  if [[ "${enable_tls}" == "true" && -n "${domain_name}" ]]; then
    public_base_url="https://${domain_name}"
    webrtc_public_base_url="https://${domain_name}/webrtc"
    stun_urls="stun:${domain_name}:3478"
    turn_urls="turn:${domain_name}:3478?transport=udp,turn:${domain_name}:3478?transport=tcp"
  else
    local http_port
    http_port="$(env_get NGINX_HTTP_PORT .env)"
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
  cd "${TARGET_ROOT}"
  mkdir -p certs/letsencrypt nginx/certbot/www
  sudo mkdir -p /var/log/stream-platform
  set -a
  source .env
  set +a

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

run_db_migrations() {
  cd "${TARGET_ROOT}"
  local pg_user pg_db
  pg_user="$(env_get POSTGRES_USER .env)"
  pg_db="$(env_get POSTGRES_DB .env)"
  compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${pg_user}" -d "${pg_db}" < sql/003_server_beta.sql
}

start_stack() {
  cd "${TARGET_ROOT}"
  compose up -d --build
  compose restart nginx
}

wait_ready() {
  cd "${TARGET_ROOT}"
  local scheme host port curl_opts=()
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

  local url="${scheme}://${host}:${port}/health/ready"
  local i
  for i in $(seq 1 90); do
    if curl -fsS "${curl_opts[@]}" "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "backend readiness check did not become ready"
}

setup_tls() {
  cd "${TARGET_ROOT}"
  if [[ "$(env_get ENABLE_TLS .env)" != "true" ]]; then
    log "tls disabled; staying in http bootstrap mode"
    return 0
  fi

  ./deploy/certbot-renew.sh
  render_nginx_mode
  compose restart nginx
}

install_ops_files() {
  cd "${TARGET_ROOT}"
  sudo install -d -m 0755 /var/log/stream-platform
  sudo install -d -m 0755 /etc/fail2ban/jail.d
  sudo install -m 0644 ops/fail2ban/jail.local.example /etc/fail2ban/jail.d/stream-platform.local
  sudo install -m 0644 ops/logrotate/stream-platform /etc/logrotate.d/stream-platform

  install_systemd_unit ops/systemd/stream-platform-backup.service
  install_systemd_unit ops/systemd/stream-platform-backup.timer
  install_systemd_unit ops/systemd/stream-platform-cert-renew.service
  install_systemd_unit ops/systemd/stream-platform-cert-renew.timer
  install_systemd_unit ops/systemd/stream-platform-healthcheck.service
  install_systemd_unit ops/systemd/stream-platform-healthcheck.timer
  sudo systemctl daemon-reload
  sudo systemctl enable --now \
    stream-platform-backup.timer \
    stream-platform-cert-renew.timer \
    stream-platform-healthcheck.timer
  sudo systemctl restart fail2ban
}

run_smoke_tests() {
  cd "${TARGET_ROOT}"
  ./deploy/smoke-test.sh
}

final_summary() {
  cd "${TARGET_ROOT}"
  ./deploy/health-summary.sh || true
}

main() {
  ensure_bookworm
  install_base_packages
  ./deploy/host-hardening.sh "${TARGET_ROOT}/.env" || true
  install_docker
  sync_project
  bootstrap_env
  ./deploy/host-hardening.sh "${TARGET_ROOT}/.env"
  render_runtime_configs
  start_stack
  run_db_migrations
  setup_tls
  ./deploy/firewall.sh "${TARGET_ROOT}/.env"
  install_ops_files
  wait_ready
  run_smoke_tests
  final_summary
  log "deploy completed successfully"
}

main "$@"
