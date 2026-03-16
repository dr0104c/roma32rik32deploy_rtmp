#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${PROJECT_ROOT}/.env}"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"
setup_trap

SSH_PORT_VALUE="22"
SSH_KEY_ONLY_VALUE="false"
if [[ -f "${ENV_FILE}" ]]; then
  SSH_PORT_VALUE="$(env_get SSH_PORT "${ENV_FILE}")"
  SSH_KEY_ONLY_VALUE="$(env_get SSH_KEY_ONLY "${ENV_FILE}")"
  [[ -n "${SSH_PORT_VALUE}" ]] || SSH_PORT_VALUE="22"
  [[ -n "${SSH_KEY_ONLY_VALUE}" ]] || SSH_KEY_ONLY_VALUE="false"
fi

info "applying host hardening"
run_as_root apt-get update
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl gnupg jq openssl fail2ban unattended-upgrades apt-listchanges

run_as_root systemctl enable --now fail2ban
run_as_root dpkg-reconfigure -f noninteractive unattended-upgrades || true

run_as_root install -d -m 0755 /etc/sysctl.d
cat <<'EOF' | run_as_root tee /etc/sysctl.d/99-stream-platform.conf >/dev/null
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
EOF
run_as_root sysctl --system >/dev/null

run_as_root install -d -m 0755 /etc/ssh/sshd_config.d
tmpfile="$(mktemp)"
{
  echo "PermitRootLogin no"
  echo "X11Forwarding no"
  echo "ClientAliveInterval 300"
  echo "ClientAliveCountMax 2"
  echo "LoginGraceTime 30"
  echo "MaxAuthTries 3"
  echo "Port ${SSH_PORT_VALUE}"
  if [[ "${SSH_KEY_ONLY_VALUE}" == "true" ]]; then
    echo "PasswordAuthentication no"
    echo "KbdInteractiveAuthentication no"
    echo "ChallengeResponseAuthentication no"
    echo "PubkeyAuthentication yes"
  fi
} > "${tmpfile}"

run_as_root mv "${tmpfile}" /etc/ssh/sshd_config.d/stream-platform-hardening.conf
run_as_root sshd -t
run_as_root systemctl reload ssh || run_as_root systemctl reload sshd

success "host hardening applied safely"
