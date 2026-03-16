#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://gitlab.roma32rik.ru/roman1/server_deploy.git}"
REPO_REF="${REPO_REF:-main}"
TARGET_DIR="${TARGET_DIR:-/opt/server_deploy_src}"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "run as root" >&2
    exit 1
  fi
}

check_os() {
  if [[ ! -r /etc/os-release ]]; then
    echo "cannot detect OS" >&2
    exit 1
  fi

  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "debian" || "${VERSION_CODENAME:-}" != "bookworm" ]]; then
    echo "this bootstrap script supports Debian Bookworm only" >&2
    exit 1
  fi
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl git
}

prepare_repo_url() {
  if [[ -n "${GITLAB_TOKEN:-}" && "${REPO_URL}" == https://* ]]; then
    printf '%s' "${REPO_URL/https:\/\//https:\/\/oauth2:${GITLAB_TOKEN}@}"
  else
    printf '%s' "${REPO_URL}"
  fi
}

sync_repo() {
  local effective_repo_url
  effective_repo_url="$(prepare_repo_url)"

  if [[ -d "${TARGET_DIR}/.git" ]]; then
    log "updating repository in ${TARGET_DIR}"
    git -C "${TARGET_DIR}" remote set-url origin "${effective_repo_url}"
    git -C "${TARGET_DIR}" fetch origin --prune
    git -C "${TARGET_DIR}" checkout -f "${REPO_REF}"
    git -C "${TARGET_DIR}" reset --hard "origin/${REPO_REF}"
  else
    log "cloning repository into ${TARGET_DIR}"
    rm -rf "${TARGET_DIR}"
    git clone --branch "${REPO_REF}" "${effective_repo_url}" "${TARGET_DIR}"
  fi

  if [[ -n "${GITLAB_TOKEN:-}" ]]; then
    git -C "${TARGET_DIR}" remote set-url origin "${REPO_URL}"
  fi
}

run_project_install() {
  log "running project install"
  chmod +x "${TARGET_DIR}/install.sh" "${TARGET_DIR}"/deploy/*.sh
  cd "${TARGET_DIR}"
  exec ./install.sh
}

main() {
  require_root
  check_os
  install_base_packages
  sync_repo
  run_project_install
}

main "$@"
