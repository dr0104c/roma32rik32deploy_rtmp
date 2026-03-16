#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

target_env="${1:-${PROJECT_ROOT}/.env}"
template="${2:-${PROJECT_ROOT}/.env.production.example}"

[[ -f "${template}" ]] || fail "missing env template: ${template}"
mkdir -p "$(dirname "${target_env}")"
[[ -f "${target_env}" ]] || cp "${template}" "${target_env}"

set_secret_if_weak() {
  local key="$1"
  local current
  current="$(awk -F= -v k="${key}" '$1==k {print $2}' "${target_env}" | tail -n 1)"
  if [[ -z "${current}" || "${current}" =~ ^(change-me|REPLACE_STRONG_SECRET|example.com|ops@example.com)$ ]]; then
    if grep -q "^${key}=" "${target_env}"; then
      sed -i "s|^${key}=.*$|${key}=$(rand_secret)|" "${target_env}"
    else
      echo "${key}=$(rand_secret)" >> "${target_env}"
    fi
  fi
}

for key in POSTGRES_PASSWORD ADMIN_SECRET INTERNAL_API_SECRET PLAYBACK_TOKEN_SECRET VIEWER_SESSION_SECRET TURN_SHARED_SECRET; do
  set_secret_if_weak "${key}"
done

chmod 600 "${target_env}"
log "secrets bootstrapped into ${target_env}"
