# Stream Platform Single-Node Deploy

Production-like single-operator foundation for the streaming platform. The existing architecture is preserved:

- ingest = RTMP
- viewer delivery = WebRTC/WHEP
- viewer access = backend-issued tokens
- direct RTMP playback = disabled
- stack = nginx + backend + postgres + MediaMTX + coturn

No transcoder is included in this stack. The media server relays the ingested stream; it does not claim to transcode it.

## Backend MVP Domain

The backend now includes a minimal domain layer for:

- viewer enrollment
- admin moderation
- output stream registration
- direct user permissions
- prepared group permission tables
- playback token issuance
- internal media auth and ingest lifecycle events

Current persistent objects:

- `users`
- `user_status_history`
- `output_streams`
- `ingest_sessions`
- `stream_permissions_user`
- `groups`
- `group_members`
- `stream_permissions_group`
- `audit_logs`

## API Endpoints

Public:

- `POST /api/v1/enroll`
- `GET /api/v1/me/{user_id}`
- `GET /api/v1/streams?user_id=...`
- `POST /api/v1/playback-token`

Admin, protected by `X-Admin-Secret`:

- `GET /api/v1/admin/users?status=pending|approved|blocked|rejected`
- `POST /api/v1/admin/users/{id}/approve`
- `POST /api/v1/admin/users/{id}/reject`
- `POST /api/v1/admin/users/{id}/block`
- `POST /api/v1/admin/streams`
- `GET /api/v1/admin/streams`
- `POST /api/v1/admin/streams/{stream_id}/grant-user`
- `POST /api/v1/admin/streams/{stream_id}/revoke-user`

Internal:

- `POST /internal/media/auth`
- compatibility alias: `POST /internal/mediamtx/auth`

Legacy helper endpoints for the lightweight web viewer are still present:

- `POST /api/v1/viewer/session`
- `GET /api/v1/viewer/me`
- `GET /api/v1/viewer/config`
- `GET /api/v1/viewer/streams`
- `POST /api/v1/viewer/streams/{stream_id}/playback-session`

## Auth Model

- admin auth uses bootstrap shared secret `X-Admin-Secret`
- playback auth uses short-lived JWT `scope=playback`
- viewer helper auth uses short-lived JWT `scope=viewer`
- internal media auth uses `INTERNAL_API_SECRET`

This is still MVP auth. There is no full admin identity/RBAC system yet.

## Playback Token Semantics

Playback token is `HS256` JWT with:

- `sub` = user id
- `sid` = output stream id
- `scope` = `playback`
- `jti`
- `iat`
- `exp`

Validation checks:

- signature valid
- token not expired
- `scope=playback`
- requested `playback_name` matches token `sid`
- user still exists and is `approved`
- permission still exists at validation time

## User Lifecycle

- `pending`: created by enroll
- `approved`: can list streams and receive playback token
- `rejected`: denied access
- `blocked`: denied access

Critical moderation actions are written to `user_status_history` and `audit_logs`.

## Stream Lifecycle

- admin creates stream with `playback_name` and `ingest_key`
- publisher ingests to `rtmp://HOST:RTMP_PORT/live/{ingest_key}`
- MediaMTX publish auth marks the matching `ingest_session` as `live`
- publish stop marks it `offline`
- viewers access `live/{playback_name}` only through WebRTC/WHEP token auth

## Current MVP Limitations

- no RTMPS ingest yet
- no real admin identity provider yet
- no transcoding or adaptive bitrate pipeline
- group permission tables exist, but smoke currently exercises direct user grants
- WHEP test is auth-path verification, not full browser playback automation

## One-Command Deploy

Clean Debian Bookworm VPS:

```bash
curl -fsSL https://gitlab.roma32rik.ru/roman1/server_deploy/-/raw/main/bootstrap-install.sh -o bootstrap-install.sh
chmod +x bootstrap-install.sh
sudo ./bootstrap-install.sh
```

Local checkout on Debian Bookworm:

```bash
sudo ./bootstrap-install.sh
```

`bootstrap-install.sh` works in two modes:

- local checkout mode: if `install.sh` and `deploy/install.sh` are рядом, it uses the local repository
- bootstrap mode: if only the bootstrap script is present, it clones the repository into `/opt/stream-platform`

The deploy succeeds only if:

- packages are installed
- docker stack is healthy
- readiness checks pass
- end-to-end smoke checks pass

## Deployment Modes

- HTTP bootstrap mode: `ENABLE_TLS=false`
- HTTPS mode with ACME: `ENABLE_TLS=true`

HTTPS mode requires:

- `DOMAIN_NAME` pointing to the VPS
- `ACME_EMAIL`
- `NGINX_HTTP_PORT=80`
- `NGINX_HTTPS_PORT=443`

The installer starts nginx in HTTP bootstrap mode first, obtains the certificate, re-renders nginx runtime config, then switches public serving to HTTPS.

## What Gets Installed

The installer:

1. validates Debian Bookworm
2. installs base packages including `curl`, `git`, `sudo`, `jq`, `ffmpeg`
3. applies safe host hardening
4. installs Docker Engine and Docker Compose plugin
5. syncs the project into `/opt/stream-platform`
6. creates `.env` from `.env.example` if missing
7. generates strong secrets for unset placeholder values
8. enforces `chmod 600 /opt/stream-platform/.env`
9. renders runtime configs for nginx, MediaMTX, and coturn
10. starts the compose stack
11. applies SQL migrations
12. configures TLS if enabled
13. applies firewall rules
14. installs backup/cert-renew/health timers
15. waits for actual readiness
16. runs `deploy/e2e-smoke.sh`
17. prints a final PASS/FAIL summary

## Exact Ports

Default public ports:

- `8080/tcp` HTTP bootstrap nginx
- `8443/tcp` HTTPS nginx
- `1935/tcp` RTMP ingest
- `3478/tcp,udp` TURN/STUN
- `5349/tcp,udp` TURN TLS
- `8189/tcp,udp` MediaMTX WebRTC ICE
- `49160-49200/udp` TURN relay range

Internal-only:

- postgres `5432`
- backend `8000`
- MediaMTX auth callbacks through backend `/internal/*`

For full public HTTPS mode, set:

- `NGINX_HTTP_PORT=80`
- `NGINX_HTTPS_PORT=443`

## Security And Media Semantics

What is actually true in this stack:

- ingest uses plain RTMP
- plain RTMP ingest is not encrypted
- direct RTMP playback is disabled
- viewer playback goes through WebRTC/WHEP
- WebRTC transport is encrypted when served through HTTPS/TLS
- backend-issued playback tokens gate viewer playback
- internal backend endpoints are denied from public nginx access

What is not claimed:

- no transcoding is performed
- no claim that RTMP ingest is encrypted unless RTMPS is added later
- no claim of full real-browser playback automation inside smoke tests

## Smoke / E2E Verification

Main smoke entrypoint:

```bash
cd /opt/stream-platform
./deploy/e2e-smoke.sh
```

Compatibility wrapper:

```bash
cd /opt/stream-platform
./deploy/smoke-test.sh
```

The e2e test verifies:

- backend `/health`, `/health/live`, `/health/ready`
- nginx serves the viewer site
- enroll works
- approve works
- create stream works
- direct user grant works
- approved user stream listing works
- playback token issuance works
- internal media auth accepts valid playback token
- invalid playback token is rejected
- direct RTMP playback auth is denied
- RTMP ingest works using generated `ffmpeg` test source
- direct RTMP playback is denied

WHEP verification is best-effort and honest:

- it confirms the tokenized playback auth path works
- it confirms invalid token is rejected
- it does not claim full browser-rendered playback automation

## HTTP Bootstrap And HTTPS Renewal

Initial TLS flow:

1. set `ENABLE_TLS=true`
2. set `DOMAIN_NAME`
3. set `ACME_EMAIL`
4. run `sudo ./bootstrap-install.sh`
5. nginx starts on HTTP
6. `deploy/certbot-renew.sh` requests the certificate
7. nginx switches to HTTPS runtime mode

Renewal:

- `stream-platform-cert-renew.timer` runs automatically
- `deploy/certbot-renew.sh` performs renew
- nginx is reloaded after renewal

## Backup / Restore

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

Stored data to preserve across VPS rebuilds:

- `/opt/stream-platform/.env`
- `/opt/stream-platform/certs/letsencrypt`
- `/var/backups/stream-platform/postgres/*.sql.gz`

## Rebuilding A 7-Day VPS

Recommended recovery flow:

1. provision fresh Debian Bookworm VPS
2. run bootstrap installer
3. restore saved `.env`
4. restore `certs/letsencrypt` if HTTPS certs already exist
5. rerun `sudo ./bootstrap-install.sh`
6. restore latest PostgreSQL backup if state matters
7. rerun `./deploy/e2e-smoke.sh`

## Troubleshooting

Check status:

```bash
cd /opt/stream-platform
sudo docker compose --env-file .env -f docker/compose.yml ps
./deploy/health-summary.sh
```

Short logs only:

```bash
sudo docker logs stream-platform-backend --tail 50
sudo docker logs stream-platform-nginx --tail 50
sudo docker logs stream-platform-mediamtx --tail 50
sudo docker logs stream-platform-postgres --tail 50
sudo docker logs stream-platform-coturn --tail 50
```

## Important Files

- [`bootstrap-install.sh`](/home/debian/codex/2rev/bootstrap-install.sh)
- [`install.sh`](/home/debian/codex/2rev/install.sh)
- [`deploy/install.sh`](/home/debian/codex/2rev/deploy/install.sh)
- [`deploy/e2e-smoke.sh`](/home/debian/codex/2rev/deploy/e2e-smoke.sh)
- [`deploy/backup-postgres.sh`](/home/debian/codex/2rev/deploy/backup-postgres.sh)
- [`deploy/restore-postgres.sh`](/home/debian/codex/2rev/deploy/restore-postgres.sh)
- [`deploy/certbot-renew.sh`](/home/debian/codex/2rev/deploy/certbot-renew.sh)
- [`docker/compose.yml`](/home/debian/codex/2rev/docker/compose.yml)
