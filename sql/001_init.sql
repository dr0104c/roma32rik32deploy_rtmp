CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    client_code VARCHAR(9) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'blocked')),
    status_version INTEGER NOT NULL DEFAULT 1,
    blocked_reason VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS output_streams (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    stream_key VARCHAR(64) NOT NULL UNIQUE,
    path_name VARCHAR(128) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'offline' CHECK (status IN ('offline', 'starting', 'live', 'stalled', 'ended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_publish_started_at TIMESTAMPTZ NULL,
    last_publish_stopped_at TIMESTAMPTZ NULL,
    last_seen_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS user_stream_grants (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    output_stream_id BIGINT NOT NULL REFERENCES output_streams(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_stream_grants UNIQUE (user_id, output_stream_id)
);

CREATE TABLE IF NOT EXISTS ingest_sessions (
    id BIGSERIAL PRIMARY KEY,
    output_stream_id BIGINT NULL REFERENCES output_streams(id) ON DELETE SET NULL,
    ingest_key VARCHAR(255) NOT NULL,
    source_name VARCHAR(255) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'publishing', 'ended', 'denied')),
    started_at TIMESTAMPTZ NULL,
    ended_at TIMESTAMPTZ NULL,
    last_heartbeat_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS playback_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    output_stream_id BIGINT NOT NULL REFERENCES output_streams(id) ON DELETE CASCADE,
    jti VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'active', 'ended', 'denied', 'revoked', 'expired')),
    client_ip VARCHAR(64) NULL,
    user_agent VARCHAR(255) NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    activated_at TIMESTAMPTZ NULL,
    ended_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_type VARCHAR(64) NOT NULL,
    actor_id BIGINT NULL,
    action VARCHAR(128) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id BIGINT NULL,
    result VARCHAR(32) NULL,
    reason VARCHAR(255) NULL,
    payload_json JSONB NULL,
    ip VARCHAR(64) NULL,
    user_agent VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_output_streams_stream_key ON output_streams(stream_key);
CREATE INDEX IF NOT EXISTS idx_output_streams_path_name ON output_streams(path_name);
CREATE INDEX IF NOT EXISTS idx_playback_sessions_jti ON playback_sessions(jti);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
