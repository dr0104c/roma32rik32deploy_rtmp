# Stream Platform Production Hardening Pack

Single-operator production foundation for the existing streaming platform beta. This stage keeps the current backend, viewer API, web viewer site, MediaMTX, PostgreSQL, nginx, and coturn flow intact, and adds practical HTTPS, ACME, firewalling, host hardening, backup/restore, readiness checks, log rotation, and light observability.

## Deployment Modes

Two public deployment modes are supported.

- HTTP bootstrap mode: `ENABLE_TLS=false`. The stack serves HTTP only and is useful for first bootstrap, internal testing, or environments without DNS.
- HTTPS mode: `ENABLE_TLS=true`. The stack starts in HTTP bootstrap mode, obtains a Let's Encrypt certificate, switches nginx to TLS config, and serves the public site/API via HTTPS.

## Domain Requirements

For full HTTPS mode:

- `DOMAIN_NAME` must point to the VPS public IP
- port `80/tcp` must be reachable for ACME HTTP-01
- `ACME_EMAIL` must be set
- `NGINX_HTTP_PORT=80`
- `NGINX_HTTPS_PORT=443`

## Core Components

- `backend`: FastAPI admin/viewer/auth/lifecycle API
- `postgres`: persistent state
- `mediamtx`: RTMP ingest and WebRTC/WHEP
- `coturn`: TURN/STUN relay
- `nginx`: public static site, reverse proxy, TLS termination

## New Operational Files

- `deploy/bootstrap-secrets.sh`
- `deploy/host-hardening.sh`
- `deploy/firewall.sh`
- `deploy/certbot-renew.sh`
- `deploy/health-summary.sh`
- `deploy/backup-postgres.sh`
- `deploy/restore-postgres.sh`
- `ops/systemd/*.service|*.timer`
- `ops/fail2ban/jail.local.example`
- `ops/logrotate/stream-platform`

## Environment

Base env examples:

- `.env.example`: HTTP/bootstrap oriented
- `.env.production.example`: production/TLS oriented

Important variables:

- `DOMAIN_NAME`
- `ACME_EMAIL`
- `ENABLE_TLS`
- `PUBLIC_BASE_URL`
- `WEBRTC_PUBLIC_BASE_URL`
- `TURN_EXTERNAL_IP`
- `TURN_MIN_PORT`
- `TURN_MAX_PORT`
- `LOG_LEVEL`
- `ACCESS_LOG_ENABLED`
- `BACKUP_RETENTION`
- `SSH_KEY_ONLY`

`deploy/bootstrap-secrets.sh` creates `.env` when missing, generates strong secrets if placeholders remain, and enforces `0600`.

## Deploy Flow

Run on Debian Bookworm:

```bash
chmod +x install.sh
./install.sh
```

Top-level `install.sh` is the single entrypoint for clean-system deployment and delegates to [`deploy/install.sh`](/home/debian/codex/2rev/deploy/install.sh).

`install.sh` now does:

1. validates Debian Bookworm
2. installs base packages
3. applies safe host hardening
4. installs Docker and Compose
5. syncs the project into `/opt/stream-platform`
6. bootstraps `.env` and strong secrets
7. validates production/TLS settings
8. renders runtime configs for nginx, MediaMTX, and coturn
9. starts the Docker stack
10. applies SQL migrations
11. if `ENABLE_TLS=true`, runs certbot and switches nginx to HTTPS mode
12. applies firewall rules
13. installs systemd timers and logrotate/fail2ban config
14. waits for readiness
15. runs smoke tests
16. prints a health summary

The flow is idempotent as far as practical for a single-node VPS.

## HTTPS Bootstrap And Cert Renew

Initial HTTPS flow:

1. Set `ENABLE_TLS=true`, `DOMAIN_NAME`, `ACME_EMAIL`
2. `install.sh` starts nginx in HTTP bootstrap mode
3. `deploy/certbot-renew.sh` performs first `certbot certonly --webroot`
4. `install.sh` re-renders nginx active config from `nginx/conf.d/https.conf`
5. nginx is restarted and begins serving TLS

Renewal:

- `stream-platform-cert-renew.timer` runs twice daily
- `deploy/certbot-renew.sh` calls `certbot renew`
- nginx is restarted after renew

## Firewall Ports

The firewall script uses `ufw` and leaves open only:

- SSH `SSH_PORT/tcp`
- HTTP `NGINX_HTTP_PORT/tcp`
- HTTPS `NGINX_HTTPS_PORT/tcp`
- RTMP ingest `RTMP_PORT/tcp`
- TURN `TURN_PORT/tcp,udp`
- TURN TLS `TURN_TLS_PORT/tcp,udp`
- MediaMTX ICE `WEBRTC_ICE_PORT/tcp,udp`
- TURN relay range `TURN_MIN_PORT-TURN_MAX_PORT/udp`

Not exposed:

- PostgreSQL
- backend internal HTTP port
- internal callback paths

## Backup/Restore

Manual backup:

```bash
cd /opt/stream-platform
./deploy/backup-postgres.sh
```

Manual restore:

```bash
cd /opt/stream-platform
./deploy/restore-postgres.sh /var/backups/stream-platform/postgres/stream-platform-postgres-YYYYMMDDTHHMMSSZ.sql.gz
```

Behavior:

- backups are gzip-compressed SQL dumps
- stored under `/var/backups/stream-platform/postgres`
- retention is controlled by `BACKUP_RETENTION`
- automated by `stream-platform-backup.timer`

Persist these when rebuilding a VPS:

- `/opt/stream-platform/.env`
- `/opt/stream-platform/certs/letsencrypt`
- PostgreSQL backups in `/var/backups/stream-platform/postgres`

## Health Endpoints

- `GET /health`: basic health
- `GET /health/live`: process liveness
- `GET /health/ready`: DB/config readiness

Operational helper:

```bash
cd /opt/stream-platform
./deploy/health-summary.sh
```

It prints:

- container states
- backend live/ready responses
- disk usage
- last service log errors
- systemd timer state

## Troubleshooting

- nginx logs: `sudo docker logs stream-platform-nginx --tail 50`
- backend logs: `sudo docker logs stream-platform-backend --tail 50`
- MediaMTX logs: `sudo docker logs stream-platform-mediamtx --tail 50`
- coturn logs: `sudo docker logs stream-platform-coturn --tail 50`
- PostgreSQL logs: `sudo docker logs stream-platform-postgres --tail 50`
- stack status: `sudo docker compose --env-file .env -f docker/compose.yml ps`
- health summary: `./deploy/health-summary.sh`

## Operational Checklist After Deploy

- verify `/health/ready`
- verify viewer site `/`
- verify RTMP ingest
- verify WHEP/WebRTC playback
- verify backup timer: `systemctl status stream-platform-backup.timer`
- verify cert renew timer when TLS enabled
- verify `ufw status`
- verify `.env` permissions are `600`

## Rebuilding A 7-Day VPS

When the VPS is recreated:

1. restore project files
2. restore `.env`
3. restore `certs/letsencrypt` if HTTPS is already issued
4. restore latest PostgreSQL backup if state matters
5. run `./deploy/install.sh`

## Android Viewer Preparation

This stage still keeps the Android-facing backend path ready:

- viewer session token flow
- viewer config endpoint
- stream list/detail endpoints
- playback-session issuance
- TURN/STUN configuration
- lifecycle-aware stream state
