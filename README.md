# Stream Platform Single-Node Deploy

Production-like single-operator foundation for the streaming platform. The existing architecture is preserved:

- ingest = RTMP
- viewer delivery = WebRTC/WHEP
- viewer access = backend-issued tokens
- direct RTMP playback = disabled
- stack = nginx + backend + postgres + MediaMTX + coturn

No transcoder is included in this stack. The media server relays the ingested stream; it does not claim to transcode it.

## One-shot Deploy

Clean Debian Bookworm server:

```bash
curl -fsSL https://gitlab.roma32rik.ru/roman1/server_deploy/-/raw/main/bootstrap-install.sh -o bootstrap-install.sh
chmod +x bootstrap-install.sh
sudo ./bootstrap-install.sh
```

Local checkout on Debian 12:

```bash
sudo ./bootstrap-install.sh
```

The deploy flow is one-shot:

- install packages and Docker
- sync project into `/opt/stream-platform`
- bootstrap secrets and runtime configs
- start the stack
- run DB migrations
- wait for readiness
- run media smoke verification
- run full automated verification
- write final verification reports

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

## Ingest Lifecycle And Media Mapping

Ingest session lifecycle states:

- `created`
- `connecting`
- `live`
- `offline`
- `revoked`
- `error`

Mapping rules in the current MVP:

- `output_stream.id` is the backend access object and is used in playback token claim `sid`
- `output_stream.playback_name` is the public viewer path segment used for WHEP/WebRTC read requests
- `output_stream.ingest_key` is the legacy open-ingest path segment
- `ingest_sessions.ingest_key` is the stable publisher key used for keyed ingest mode and key rotation
- MediaMTX publish path remains `live/{key}`
- viewer playback path remains `live/{playback_name}`

Publish-start handling is enforced through MediaMTX auth callbacks today. Publish-stop handling is implemented as a backend-compatible internal hook endpoint and used by smoke tests; wiring a native MediaMTX stop hook is still best-effort and depends on the chosen runtime image/tooling.

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
- `POST /api/v1/admin/ingest-sessions`
- `GET /api/v1/admin/ingest-sessions`
- `POST /api/v1/admin/ingest-sessions/{id}/rotate-key`
- `POST /api/v1/admin/ingest-sessions/{id}/revoke`

Internal:

- `POST /internal/media/auth`
- `POST /internal/media/publish-stop`
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
- ingest publish auth mode is controlled by `INGEST_AUTH_MODE=open|keyed`

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

- admin creates stream with `playback_name` and legacy stream-level `ingest_key`
- admin may create dedicated ingest sessions with stable publisher keys
- publisher ingests to `rtmp://HOST:RTMP_PORT/live/{ingest_key}`
- in `INGEST_AUTH_MODE=open`, legacy stream ingest keys still work for MVP compatibility
- in `INGEST_AUTH_MODE=keyed`, publish requires a matching active `ingest_sessions.ingest_key`
- MediaMTX publish auth marks the matching `ingest_session` as `connecting -> live`
- publish stop transitions the session to `offline`
- revoked ingest sessions cannot publish
- viewers access `live/{playback_name}` only through WebRTC/WHEP token auth

Ingest key rotation and revoke:

- `POST /api/v1/admin/ingest-sessions/{id}/rotate-key` issues a new stable publisher key
- `POST /api/v1/admin/ingest-sessions/{id}/revoke` marks the ingest session revoked
- direct RTMP playback stays denied in all modes

## Current MVP Limitations

- no RTMPS ingest yet
- no real admin identity provider yet
- no transcoding or adaptive bitrate pipeline
- group permission tables exist, but smoke currently exercises direct user grants
- WHEP test is auth-path verification, not full browser playback automation
- publish-stop callback wiring is backend-ready and smoke-tested, but native MediaMTX stop hook integration remains runtime-dependent

## Automated Media Verification

The deploy now ends with a dedicated verification phase:

- `deploy/verify-stack.sh`
- `deploy/media-smoke-test.sh`
- `deploy/write-verification-report.sh`

Verification includes:

- backend `/health`, `/health/live`, `/health/ready`
- nginx public endpoint availability
- synthetic RTMP ingest using `ffmpeg` test source
- MediaMTX ingest lifecycle visibility through backend API
- direct RTMP playback denial
- playback token + internal auth callback path
- WHEP/WebRTC endpoint HTTP semantics with valid and invalid token
- TURN service reachability on the published TCP port
- explicit separation of encrypted playback vs transcoding
- JSON and TXT verification reports

Generated reports:

- `deploy/verification-report.json`
- `deploy/verification-report.txt`

Report fields include:

- `containers_ok`
- `backend_ready`
- `nginx_ok`
- `rtmp_ingest_ok`
- `rtmp_playback_blocked`
- `whep_or_webrtc_endpoint_ok`
- `turn_reachable`
- `playback_auth_ok`
- `media_encryption_ok`
- `transcoding_enabled`
- `transcoding_verified`
- `browser_level_rendering_verified`
- `overall_status`
- `failed_checks`

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
16. runs `deploy/verify-stack.sh`
17. writes verification reports
18. prints a final PASS/FAIL summary with access URLs

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

## Encrypted Playback vs Transcoding

These are separate concerns and the deploy report treats them separately:

- `ingest accepted`: RTMP publish was accepted by MediaMTX and surfaced in backend lifecycle state
- `stream republished to WebRTC/WHEP`: the viewer path and tokenized auth reached the media layer successfully
- `playback transport encrypted`: only reported as `true` when TLS is enabled and WHEP/WebRTC verification passes
- `transcoding absent / not configured`: current default mode

Optional env flag:

- `ENABLE_FFMPEG_TRANSCODE=false|true`
- `ENABLE_AUTOMATED_MEDIA_VERIFY=true|false`
- `VERIFY_TURN=true|false`
- `VERIFY_BROWSERLESS_WHEP=true|false`
- `VERIFY_RTMP_PLAYBACK_BLOCK=true|false`
- `VERIFY_REPORT_DIR=deploy`
- `MEDIA_SMOKE_TEST_DURATION_SEC=12`
- `MEDIA_SMOKE_TEST_STREAM_NAME=verification-smoke`

Right now this flag is diagnostic only. The default stack remains passthrough/relay oriented and does not add a transcoder pipeline automatically. If the flag is set to `true`, the verification report still marks transcoding as unverified unless a real transcoding path is added later.

## Smoke / E2E Verification

Main smoke entrypoint:

```bash
cd /opt/stream-platform
./deploy/verify-stack.sh
```

Compatibility wrapper:

```bash
cd /opt/stream-platform
./deploy/smoke-test.sh
```

The verification stage checks:

- backend `/health`, `/health/live`, `/health/ready`
- nginx serves the viewer site
- synthetic enroll / approve / stream / grant / token path
- internal media auth accepts valid playback token
- invalid playback token is rejected
- ingest session lifecycle transitions `created -> live -> offline`
- RTMP ingest works using generated `ffmpeg` test source
- direct RTMP playback is denied
- WHEP/WebRTC endpoint exposes the expected authenticated HTTP semantics
- TURN service is reachable
- final machine-readable and human-readable reports are written

Browser-level rendering is not claimed by this verification. The report explicitly records that verification is server-side transport and auth readiness, not a real browser playback assertion.

`deploy/media-smoke-test.sh` is also intentionally server-side only:

- it publishes a deterministic synthetic `ffmpeg` source for a bounded duration
- it verifies ingest lifecycle and WHEP auth semantics
- it verifies direct RTMP playback stays blocked
- it cleans up the publisher process and temporary files
- it does not claim real browser rendering

## HTTP Bootstrap And HTTPS Mode

HTTP bootstrap:

```bash
sudo ENABLE_TLS=false ./bootstrap-install.sh
```

HTTPS mode:

```bash
sudo ENABLE_TLS=true DOMAIN_NAME=stream.example.com ACME_EMAIL=ops@example.com ./bootstrap-install.sh
```

For HTTPS mode:

- DNS for `DOMAIN_NAME` must already point to the VPS
- ports `80/tcp` and `443/tcp` must be reachable
- the install will fail fast if ACME prerequisites are missing

## Typical Verification Problems

- `RTMP ingest accepted = false`
  Usually wrong firewall/NAT exposure for `${RTMP_PORT}` or MediaMTX not healthy.
- `WHEP/WebRTC endpoint OK = false`
  Usually a playback token/auth path mismatch or nginx routing issue under `/webrtc/`.
- `protected playback channel = false`
  Expected in bootstrap HTTP mode. Enable TLS for public encrypted signaling.
- `TURN reachable = false`
  Usually blocked `TURN_PORT` / `TURN_TLS_PORT` or coturn did not bind as expected.
- `transcoding verified = false`
  Expected in the current default stack because no transcoder is configured.
- `rtmp_playback_blocked = false`
  Hard failure. Viewer playback must stay on WebRTC/WHEP only.

## Restore After 7-Day VPS Rebuild

To rebuild a short-lived VPS without losing state, keep these artifacts:

- `.env`
- `certs/letsencrypt`
- PostgreSQL backups from `/var/backups/stream-platform/postgres`

Basic restore flow:

1. redeploy the node with `sudo ./bootstrap-install.sh`
2. restore `.env`
3. restore certificates if TLS is enabled
4. run `./deploy/restore-postgres.sh /path/to/backup.sql.gz`
5. run `./deploy/e2e-smoke.sh`

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
