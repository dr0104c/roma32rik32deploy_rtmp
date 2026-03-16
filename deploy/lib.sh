#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

env_get() {
  local key="$1"
  local file="${2:-.env}"
  awk -F= -v k="${key}" '$1==k {print substr($0, index($0, "=")+1)}' "${file}" | tail -n 1
}

wait_for_http() {
  local url="$1"
  local attempts="${2:-60}"
  local delay="${3:-2}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

compose() {
  docker_host compose --env-file .env -f docker/compose.yml "$@"
}

docker_host() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    sudo docker "$@"
  fi
}

rand_secret() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
}

install_systemd_unit() {
  local source_file="$1"
  local target_file="/etc/systemd/system/$(basename "${source_file}")"
  sudo install -m 0644 "${source_file}" "${target_file}"
}
