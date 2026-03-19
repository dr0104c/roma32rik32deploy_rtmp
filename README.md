# Stream Platform

Платформа стриминга с:

- RTMP ingest
- viewer playback через WebRTC/WHEP
- viewer ACL на `output_stream`
- всегда запрещённым direct RTMP playback

## Доменная Модель Продукта

### `ingest_session`

`ingest_session` — это сущность со стороны публикации.

- хранит `ingest_key`
- управляет жизненным циклом публикации: `ready`, `live`, `ended`, `revoked`
- может быть перевязана на другой `output_stream`
- существует для управления ingest, а не для viewer discovery

### `output_stream`

`output_stream` — это сущность со стороны просмотра.

- имеет стабильный viewer identifier: `output_stream.id`
- имеет стабильный viewer path: `output_stream.playback_path`
- возвращается viewer API
- является единственной ACL-сущностью для пользователей и групп
- является единственной сущностью для выдачи playback token

### Почему это разные сущности

- ротация publish secret и viewer access — это разные задачи
- ingest credentials не должны становиться viewer identifier
- один ingest lifecycle object можно перевязать без изменения viewer ACL модели
- viewer API должны оставаться `output_stream`-centric, даже если ingest меняется

### Область ACL

ACL назначается только на `output_stream`.

- `stream_permissions_user.output_stream_id`
- `stream_permissions_group.output_stream_id`
- viewer ACL никогда не выдаётся на `ingest_session`

## Path Mapping

- ingest publish path: `live/{publisher_path}`
- viewer playback path: `live/{output_stream.playback_path}`
- `publisher_path` становится `ingest_session.ingest_key`
- `ingest_key` не является viewer identifier
- `playback_path` не является publish secret

Каноническое разрешение playback:

- запрос playback token принимает `output_stream_id`
- запрос playback token также принимает `playback_path`
- ingest key не должен работать как замена ни одному из этих идентификаторов

## Модель Безопасности

- RTMP ingest разрешён
- RTMP playback всегда запрещён
- playback token выдаётся только для `output_stream`
- ingest key никогда не раскрывается viewer-facing API
- internal media auth endpoints не являются публичными viewer API

Правила реализации:

- `POST /api/v1/playback-token` резолвит только `output_stream_id` или `playback_path`
- если `playback_path` совпадает с существующим `ingest_key`, запрос падает с `ingest_key_not_playback_identifier`
- viewer API возвращают только output-stream payload
- internal `/internal/media/*` endpoints требуют `INTERNAL_API_SECRET`, если защита включена

## Admin Flow

1. создать `output_stream`
2. опционально заранее создать `ingest_session`
3. привязать ingest к output через `current_output_stream_id`
4. выдать пользователю или группе доступ к `output_stream`

Нужные endpoints:

- `POST /api/v1/admin/output-streams`
- `POST /api/v1/admin/ingest-sessions`
- `PATCH /api/v1/admin/ingest-sessions/{ingest_session_id}`
- `POST /api/v1/admin/output-streams/{output_stream_id}/grant-user`
- `POST /api/v1/admin/output-streams/{output_stream_id}/grant-group`

Compatibility aliases под `/api/v1/admin/streams*` сохранены, но это только слой совместимости. Каноническая модель теперь `output_stream`-centric.

## Viewer Flow

1. enroll
2. approve
3. получить список доступных `output_stream`
4. запросить playback token для `output_stream`
5. смотреть через WebRTC/WHEP

Нужные endpoints:

- `POST /api/v1/enroll`
- `POST /api/v1/admin/users/{user_id}/approve`
- `GET /api/v1/streams?user_id=...`
- `POST /api/v1/viewer/session`
- `GET /api/v1/viewer/streams`
- `POST /api/v1/playback-token`
- `POST /api/v1/viewer/streams/{output_stream_id}/playback-session`

## Модель Верификации

Server-side верификация в этом репозитории доказывает:

- список стримов строится по `output_stream`
- viewer-facing ответы не содержат `ingest_key`
- playback token flow отвергает ingest-key semantics
- RTMP publish auth принимает `live/{ingest_key}`
- RTMP read запрещён и на `live/{ingest_key}`, и на `live/{output_stream.playback_path}`
- WHEP/WebRTC auth path строится из `playback_path`

Что здесь не проверяется браузером:

- browser media rendering
- ICE success в реальном браузере
- фактическое декодирование и воспроизведение аудио/видео в реальной вкладке браузера

Encrypted playback и transcoding — разные вещи:

- encrypted playback означает, что WHEP/WebRTC signaling и доставка работают через TLS, если TLS включён
- transcoding означает ре-энкодинг или трансформацию медиа
- это разные свойства
- текущая verification-report логика отражает их отдельно

## E2E Proof Checklist

В репозитории теперь есть автоматическое доказательство следующего:

- viewer API не раскрывает ingest key
- playback token отвергает ingest key semantics
- RTMP publish работает на ingest path
- RTMP read запрещён на ingest path
- RTMP read запрещён на output path
- WHEP/WebRTC playback URL использует `playback_path`, а не `ingest_key`

Точки запуска proof:

- `pytest backend/tests/test_product_model.py`
- `./deploy/e2e-product-model.sh`
- `./deploy/verify-stack.sh`

## Короткий Пример

Создать `output_stream`:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/admin/output-streams \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H 'content-type: application/json' \
  -d '{"name":"Main Stage","public_name":"main-stage","title":"Main Stage","playback_path":"main-stage-watch"}'
```

Создать `ingest_session`, привязанную к этому output:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/admin/ingest-sessions \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H 'content-type: application/json' \
  -d '{"current_output_stream_id":"OUTPUT_STREAM_ID","source_label":"encoder-a"}'
```

Публиковать RTMP можно через любой path, который выберет publisher:

```bash
ffmpeg -re -f lavfi -i testsrc=size=640x360:rate=15 -f lavfi -i sine=frequency=1000 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -f flv \
  "rtmp://127.0.0.1:1935/live/my-camera-01"
```

Если такого ingest path ещё нет в базе:

- backend автоматически регистрирует `ingest_session`
- backend автоматически создаёт и связывает `output_stream`
- playback всё равно остаётся только через `output_stream` и playback token

Запросить playback token по `output_stream_id`:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/playback-token \
  -H 'content-type: application/json' \
  -d '{"user_id":"USER_ID","output_stream_id":"OUTPUT_STREAM_ID"}'
```

WHEP URL использует `playback_path`:

```text
http://127.0.0.1:8080/webrtc/live/main-stage-watch/whep?token=...
```

А не:

```text
http://127.0.0.1:8080/webrtc/live/INGEST_KEY/whep?token=...
```

## Тестирование

### API integration proof

Запускается в Python test stack и доказывает:

- enroll -> approve -> create output stream -> create ingest session -> grant access
- `GET /api/v1/streams` возвращает `output_stream` и не раскрывает ingest linkage
- viewer session и viewer stream list не раскрывают ingest linkage
- playback token работает с `output_stream_id`
- playback token работает с `playback_path`
- playback token падает с `ingest_key`
- internal media auth принимает publish на ingest path
- internal media auth запрещает RTMP read на ingest path и output path
- WHEP auth работает по `playback_path`

Запуск:

```bash
pytest backend/tests/test_product_model.py
```

### Deploy-side product-model proof

Запускается против развернутого стека и дополнительно использует реальный synthetic RTMP publish через `ffmpeg`.

Запуск:

```bash
./deploy/e2e-product-model.sh
```

Этот скрипт использует:

- `POST /api/v1/enroll`
- admin approval
- admin output-stream creation
- admin ingest-session creation
- output-stream ACL grant
- public и viewer stream listing
- playback token positive и negative cases
- synthetic RTMP publish на `live/{publisher_path}`
- RTMP read deny checks для ingest path и output path
- browserless WHEP HTTP auth-path verification

## Результаты Deploy Verification

`./deploy/verify-stack.sh` пишет:

- `deploy/verification-report.json`
- `deploy/verification-report.txt`

Важные поля отчёта:

- `viewer_api_hides_ingest_key`
- `playback_token_rejects_ingest_key`
- `rtmp_read_blocked_on_ingest_path`
- `rtmp_read_blocked_on_output_path`
- `playback_path_is_distinct_from_ingest_key`
- `whep_url_uses_playback_path`

Они идут в дополнение к:

- `rtmp_ingest_ok`
- `rtmp_playback_blocked`
- `whep_or_webrtc_endpoint_ok`
- `playback_auth_ok`

## Операционные Замечания

- не используйте `ingest_key` во viewer code
- не документируйте `ingest_key` как playback identifier
- не ослабляйте RTMP playback deny
- не раскрывайте internal `/internal/media/*` endpoints viewer'ам
- если используются legacy `/api/v1/admin/streams*` routes, считайте их compatibility aliases над той же `output_stream` моделью

## Android Integration Contract

Android Viewer App для MVP должен использовать только viewer-facing contract и не должен знать ingest lifecycle.

### Bootstrap / config

Bootstrap endpoint для Android:

- `GET /api/v1/viewer/config`

Он возвращает:

- `public_base_url`
- `webrtc_base_url`
- `stun_urls`
- `turn_urls`
- `turn_realm`
- `stream_list_poll_interval`
- `playback_token_ttl`
- `ingest_transport`
- `ingest_container`
- `playback_transport`
- `rtmp_playback_enabled`
- `output_stream_acl_scope`
- `playback_token_lookup_fields`
- `viewer_must_not_use_fields`
- `browser_rendering_verified`
- `real_android_ice_verified`
- `transcoding_enabled`
- `transcoding_verified`
- `expected_ingest_video_codec`
- `expected_ingest_audio_codec`
- `expected_ingest_notes`

Android использует этот endpoint, чтобы:

- получить `webrtc_base_url`, `stun_urls`, `turn_urls`, `turn_realm`
- зафиксировать, что viewer delivery для MVP это только `WebRTC/WHEP`
- зафиксировать, что `RTMP` playback выключен
- зафиксировать, что ACL живёт только на `output_stream`
- увидеть, что browser/device rendering и ICE на реальном Android автоматически не верифицированы

### Viewer endpoints used by Android

Минимальный Android flow:

1. `POST /api/v1/viewer/session`
2. `GET /api/v1/viewer/streams`
3. `POST /api/v1/viewer/streams/{output_stream_id}/playback-session`

Тела и заголовки:

- `POST /api/v1/viewer/session` принимает `{"client_code":"ABCD-1234"}`
- `GET /api/v1/viewer/streams` требует `Authorization: Bearer <viewer_token>`
- `POST /api/v1/viewer/streams/{output_stream_id}/playback-session` требует `Authorization: Bearer <viewer_token>`

Compatibility flow, если клиент пока не использует viewer bearer session:

1. `POST /api/v1/enroll`
2. admin approval
3. `GET /api/v1/streams?user_id=...`
4. `POST /api/v1/playback-token`

### Fields Android may use

Android может использовать:

- `viewer_token`
- `expires_in`
- `user.user_id`
- `user.display_name`
- `user.client_code`
- `user.status`
- `streams[].output_stream_id`
- `streams[].stream_id`
- `streams[].name`
- `streams[].public_name`
- `streams[].title`
- `streams[].description`
- `streams[].visibility`
- `streams[].playback_path`
- `streams[].playback_name`
- `streams[].is_active`
- `playback_token`
- `expires_at`
- `playback.webrtc_url`
- `output_stream.id`
- `output_stream.playback_path`

### Fields Android must not use

Android не должен использовать:

- `ingest_key`
- `ingest_session_id`
- internal `/internal/media/*` endpoints
- RTMP URL как playback URL
- любые предположения, что `playback_path == ingest_key`

### MVP media contract

- ingest transport: RTMP
- ingest container: FLV
- verified synthetic ingest profile: H.264 video + AAC audio
- viewer delivery: WebRTC/WHEP
- RTMP playback: always disabled
- playback token lookup: только `output_stream_id` или `playback_path`
- ACL target: только `output_stream`

Если `ENABLE_FFMPEG_TRANSCODE=true`:

- backend пытается готовить playback path через ffmpeg transcode path
- automated verification всё равно не доказывает device rendering
- automated verification не доказывает ICE success на реальном Android

Если `ENABLE_FFMPEG_TRANSCODE=false`:

- это явное ограничение MVP
- Android playback compatibility зависит от исходных codec characteristics ingest source
- verification report должен показывать, что transcoding disabled / not verified

### Public ports

Публичная поверхность стека:

- nginx HTTP: `${NGINX_HTTP_PORT}` -> container `80`
- nginx HTTPS: `${NGINX_HTTPS_PORT}` -> container `443`
- RTMP ingest: `${RTMP_PORT}` -> container `1935`
- WebRTC ICE: `${WEBRTC_ICE_PORT}` -> container `8189/tcp` и `8189/udp`
- TURN: `${TURN_PORT}` -> container `3478/tcp` и `3478/udp`
- TURN TLS: `${TURN_TLS_PORT}` -> container `5349/tcp` и `5349/udp`
- TURN relay range: `${TURN_MIN_PORT}-${TURN_MAX_PORT}/udp`

### Next Stage

Следующий этап, но не часть этой server-readiness подготовки:

- полноценный admin auth / RBAC
- richer observability platform
- Terraform / infra provisioning
- расширенный transcoding matrix
- real-device Android playback verification

## Admin Authentication

Начиная с этого этапа канонический admin auth для server MVP — bearer-based.

Новые auth endpoints:

- `POST /api/v1/admin/auth/login`
- `GET /api/v1/admin/auth/me`

Login request:

```json
{
  "username": "admin",
  "password": "..."
}
```

Login response:

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

`access_token` должен передаваться как:

```text
Authorization: Bearer <token>
```

## Bootstrap Admin

Bootstrap admin создаётся из env, если таблица `admin_users` пуста.

Новые env:

- `ADMIN_JWT_SECRET`
- `ADMIN_BOOTSTRAP_USERNAME`
- `ADMIN_BOOTSTRAP_PASSWORD`
- `ADMIN_ACCESS_TOKEN_TTL_SECONDS`
- `LEGACY_ADMIN_SECRET_ENABLED`

Минимальный bootstrap contract:

- `ADMIN_BOOTSTRAP_USERNAME=admin`
- `ADMIN_BOOTSTRAP_PASSWORD=<strong secret>`
- `ADMIN_JWT_SECRET=<strong secret>`

Пароль хранится только в hash виде в `admin_users.password_hash`.

## Legacy X-Admin-Secret Compatibility Mode

Старый `X-Admin-Secret` не удалён, но считается transitional compatibility mode.

Правила:

- если `LEGACY_ADMIN_SECRET_ENABLED=true`, старые admin routes продолжают принимать `X-Admin-Secret`
- если `LEGACY_ADMIN_SECRET_ENABLED=false`, admin bearer token становится единственным рекомендуемым способом доступа
- production recommendation: использовать bearer auth и выключать legacy secret mode

Это сделано, чтобы не ломать существующие deploy/e2e flows и compatibility aliases.

## Admin API

### Auth

- `POST /api/v1/admin/auth/login`
- `GET /api/v1/admin/auth/me`

### Users / moderation

- `GET /api/v1/admin/users?status=&search=&limit=&offset=`
- `GET /api/v1/admin/users/{user_id}`
- `POST /api/v1/admin/users/{user_id}/approve`
- `POST /api/v1/admin/users/{user_id}/reject`
- `POST /api/v1/admin/users/{user_id}/block`
- `POST /api/v1/admin/users/{user_id}/unblock`

MVP statuses:

- `pending`
- `approved`
- `rejected`
- `blocked`

`unblock` в текущем MVP возвращает пользователя в `approved`.

### Groups

- `GET /api/v1/admin/groups`
- `POST /api/v1/admin/groups`
- `POST /api/v1/admin/users/{user_id}/groups/{group_id}`
- `DELETE /api/v1/admin/users/{user_id}/groups/{group_id}`

### Output streams / ACL

Канонический ACL API остаётся `output_stream`-centric.

- `GET /api/v1/admin/output-streams`
- `GET /api/v1/admin/output-streams/{output_stream_id}`
- `POST /api/v1/admin/output-streams`
- `PATCH /api/v1/admin/output-streams/{output_stream_id}`
- `POST /api/v1/admin/output-streams/{output_stream_id}/grant-user`
- `DELETE /api/v1/admin/output-streams/{output_stream_id}/grant-user/{user_id}`
- `POST /api/v1/admin/output-streams/{output_stream_id}/grant-group`
- `DELETE /api/v1/admin/output-streams/{output_stream_id}/grant-group/{group_id}`

### Ingest sessions

- `POST /api/v1/admin/ingest-sessions`
- `GET /api/v1/admin/ingest-sessions`
- `GET /api/v1/admin/ingest-sessions/{ingest_session_id}`
- `PATCH /api/v1/admin/ingest-sessions/{ingest_session_id}`
- `POST /api/v1/admin/ingest-sessions/{ingest_session_id}/rotate-key`
- `POST /api/v1/admin/ingest-sessions/{ingest_session_id}/revoke`

### Audit

- `GET /api/v1/admin/audit?target_type=&target_id=&limit=&offset=`

## Admin UI

В стек добавлена очень простая server-served admin панель без отдельного frontend build pipeline.

Адрес:

- `/admin/`

Что умеет UI:

- login админом
- pending users
- all users
- user details
- groups
- output streams
- audit log
- approve / reject / block / unblock
- add user to group
- grant user -> output_stream
- grant group -> output_stream
- create group
- create output_stream

UI намеренно утилитарный:

- vanilla HTML/CSS/JS
- без node build chain
- без SPA framework
- работает в текущем docker/nginx stack

## Client Moderation Flow

Минимальный moderation flow для клиента и админа:

1. viewer вызывает `POST /api/v1/enroll`
2. пользователь появляется со статусом `pending`
3. admin видит пользователя через `GET /api/v1/admin/users?status=pending`
4. admin делает `approve`, `reject` или `block`
5. только `approved` user может получить viewer session и playback token

## Group-Based ACL

ACL по-прежнему выдаётся только на `output_stream`.

Теперь доступны два слоя назначения:

- direct user -> `output_stream`
- group -> `output_stream`

Эффективный viewer access:

- direct grant на `output_stream`
- или membership в группе, которой выдан grant на `output_stream`

Это не меняет viewer-facing contract:

- viewer client по-прежнему видит только `output_stream`
- `ingest_key` не раскрывается
- playback token выдаётся только для `output_stream`
- publisher может выбрать произвольный RTMP path, но этот path не становится viewer identifier

## Security Notes

- `ingest_key` не используется viewer clients и не должен использоваться Android или web viewer code
- publisher RTMP path может быть произвольным и авто-регистрируется сервером на первом publish
- bearer admin auth теперь канонический способ admin доступа
- `X-Admin-Secret` оставлен только как transitional compatibility mode
- если legacy secret mode не нужен, выключайте `LEGACY_ADMIN_SECRET_ENABLED`
- RTMP ingest разрешён
- RTMP playback остаётся полностью запрещённым
- internal `/internal/media/*` endpoints не должны быть доступны viewer/admin browser clients
- verification report теперь отдельно показывает `admin_auth_ok`, `admin_ui_ok`, `legacy_admin_secret_mode`, `user_moderation_ok`, `group_acl_ok`

## Curl Examples

Получить admin token:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/admin/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"REPLACE_ADMIN_PASSWORD"}'
```

Получить admin me:

```bash
curl -sS http://127.0.0.1:8080/api/v1/admin/auth/me \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

Создать `output_stream` через bearer auth:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/admin/output-streams \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H 'content-type: application/json' \
  -d '{"name":"Main Stage","public_name":"main-stage","title":"Main Stage","playback_path":"main-stage-watch"}'
```

Legacy compatibility example:

```bash
curl -sS http://127.0.0.1:8080/api/v1/admin/users \
  -H 'X-Admin-Secret: REPLACE_LEGACY_SECRET'
```

Используйте legacy secret только пока это нужно для совместимости.
