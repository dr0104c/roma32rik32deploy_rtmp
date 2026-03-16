#!/usr/bin/env bash
set -Eeuo pipefail

timestamp() {
  date -u +'%Y-%m-%dT%H:%M:%SZ'
}

info() {
  printf '[%s] [INFO] %s\n' "$(timestamp)" "$*"
}

warn() {
  printf '[%s] [WARN] %s\n' "$(timestamp)" "$*" >&2
}

error() {
  printf '[%s] [ERROR] %s\n' "$(timestamp)" "$*" >&2
}

success() {
  printf '[%s] [ OK ] %s\n' "$(timestamp)" "$*"
}

pass() {
  printf '[PASS] %s\n' "$*"
}

fail_line() {
  printf '[FAIL] %s\n' "$*"
}

log() {
  info "$@"
}

fail() {
  error "$*"
  exit 1
}

on_error() {
  local exit_code="$1"
  local line_no="$2"
  local command="${3:-unknown}"
  error "command failed at line ${line_no} with exit ${exit_code}: ${command}"
  exit "${exit_code}"
}

setup_trap() {
  trap 'on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

run_as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

docker_host() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    run_as_root docker "$@"
  fi
}

compose() {
  docker_host compose --env-file .env -f docker/compose.yml "$@"
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
  for i in $(seq 1 "${attempts}"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

wait_for_compose_service() {
  local service="$1"
  local expected="${2:-running}"
  local attempts="${3:-60}"
  local delay="${4:-2}"
  local status
  local i
  for i in $(seq 1 "${attempts}"); do
    status="$(compose ps --format json 2>/dev/null | jq -r --arg service "${service}" 'select(.Service == $service) | .State' | head -n 1)"
    if [[ "${status}" == "${expected}" ]]; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

rand_secret() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
}

install_systemd_unit() {
  local source_file="$1"
  local target_file="/etc/systemd/system/$(basename "${source_file}")"
  run_as_root install -m 0644 "${source_file}" "${target_file}"
}
