#!/usr/bin/env bash
set -Eeuo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_REPO_ROOT="${SELF_DIR}"
REPO_URL="${REPO_URL:-https://gitlab.roma32rik.ru/roman1/server_deploy.git}"
REPO_REF="${REPO_REF:-main}"
TARGET_DIR="${TARGET_DIR:-/opt/stream-platform}"

info() {
  printf '[%s] [INFO] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

success() {
  printf '[%s] [ OK ] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

error() {
  printf '[%s] [ERROR] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

fail() {
  error "$*"
  exit 1
}

trap 'fail "bootstrap failed at line ${LINENO}: ${BASH_COMMAND}"' ERR

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "run as root or via sudo"
  fi
}

check_os() {
  [[ -r /etc/os-release ]] || fail "cannot detect OS"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "debian" ]] || fail "unsupported OS: ${ID:-unknown}"
  [[ "${VERSION_CODENAME:-}" == "bookworm" ]] || fail "unsupported Debian codename: ${VERSION_CODENAME:-unknown}"
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl git sudo
}

prepare_repo_url() {
  if [[ -n "${GITLAB_TOKEN:-}" && "${REPO_URL}" == https://* ]]; then
    printf '%s' "${REPO_URL/https:\/\//https:\/\/oauth2:${GITLAB_TOKEN}@}"
  else
    printf '%s' "${REPO_URL}"
  fi
}

is_local_checkout() {
  [[ -f "${LOCAL_REPO_ROOT}/install.sh" && -f "${LOCAL_REPO_ROOT}/deploy/install.sh" ]]
}

sync_repo() {
  local effective_repo_url
  effective_repo_url="$(prepare_repo_url)"

  if [[ -d "${TARGET_DIR}/.git" ]]; then
    info "updating repository in ${TARGET_DIR}"
    git -C "${TARGET_DIR}" remote set-url origin "${effective_repo_url}"
    git -C "${TARGET_DIR}" fetch origin --prune
    git -C "${TARGET_DIR}" checkout -f "${REPO_REF}"
    git -C "${TARGET_DIR}" reset --hard "origin/${REPO_REF}"
  else
    info "cloning repository into ${TARGET_DIR}"
    rm -rf "${TARGET_DIR}"
    git clone --branch "${REPO_REF}" "${effective_repo_url}" "${TARGET_DIR}"
  fi

  if [[ -n "${GITLAB_TOKEN:-}" ]]; then
    git -C "${TARGET_DIR}" remote set-url origin "${REPO_URL}"
  fi
}

run_project_install() {
  local repo_root="$1"
  info "running project installer from ${repo_root}"
  chmod +x "${repo_root}/install.sh" "${repo_root}"/deploy/*.sh
  cd "${repo_root}"
  exec ./install.sh
}

main() {
  require_root
  check_os
  install_base_packages

  if is_local_checkout; then
    info "local checkout detected at ${LOCAL_REPO_ROOT}"
    run_project_install "${LOCAL_REPO_ROOT}"
  fi

  sync_repo
  success "repository ready in ${TARGET_DIR}"
  run_project_install "${TARGET_DIR}"
}

main "$@"
