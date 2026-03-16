#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=deploy/lib.sh
source "${SCRIPT_DIR}/lib.sh"

ENV_FILE="${1:-${PROJECT_ROOT}/.env}"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl gnupg jq openssl fail2ban unattended-upgrades apt-listchanges

sudo systemctl enable --now fail2ban
sudo dpkg-reconfigure -f noninteractive unattended-upgrades || true

sudo install -d -m 0755 /etc/sysctl.d
cat <<'EOF' | sudo tee /etc/sysctl.d/99-stream-platform.conf >/dev/null
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
EOF
sudo sysctl --system >/dev/null

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
else
  SSH_PORT=22
  SSH_KEY_ONLY=false
fi

sudo install -d -m 0755 /etc/ssh/sshd_config.d
tmpfile="$(mktemp)"
{
  echo "PermitRootLogin no"
  echo "ChallengeResponseAuthentication no"
  echo "UsePAM yes"
  echo "X11Forwarding no"
  echo "AllowTcpForwarding yes"
  echo "ClientAliveInterval 300"
  echo "ClientAliveCountMax 2"
  echo "Port ${SSH_PORT:-22}"
  if [[ "${SSH_KEY_ONLY:-false}" == "true" ]]; then
    echo "PasswordAuthentication no"
    echo "KbdInteractiveAuthentication no"
  fi
} > "${tmpfile}"
sudo mv "${tmpfile}" /etc/ssh/sshd_config.d/stream-platform-hardening.conf
sudo sshd -t
sudo systemctl reload ssh || sudo systemctl reload sshd
log "host hardening applied safely"
