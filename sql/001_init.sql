CREATE TABLE IF NOT EXISTS admin_users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(128) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'owner' CHECK (role IN ('owner','admin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    display_name TEXT NOT NULL,
    client_code VARCHAR(9) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('pending','approved','rejected','blocked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_status_history (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    previous_status VARCHAR(16) NULL,
    new_status VARCHAR(16) NOT NULL,
    reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS output_streams (
    id VARCHAR(36) PRIMARY KEY,
    name TEXT NOT NULL,
    public_name VARCHAR(128) NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    visibility VARCHAR(16) NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','public','unlisted','disabled')),
    playback_path VARCHAR(128) NOT NULL UNIQUE,
    source_ingest_session_id VARCHAR(36) NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingest_sessions (
    id VARCHAR(36) PRIMARY KEY,
    ingest_key VARCHAR(64) NOT NULL UNIQUE,
    source_label TEXT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('created','live','ended','revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    ended_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL,
    last_seen_at TIMESTAMPTZ NULL,
    current_output_stream_id VARCHAR(36) NULL REFERENCES output_streams(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_output_streams_source_ingest_session'
    ) THEN
        ALTER TABLE output_streams
            ADD CONSTRAINT fk_output_streams_source_ingest_session
            FOREIGN KEY (source_ingest_session_id) REFERENCES ingest_sessions(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS stream_permissions_user (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    output_stream_id VARCHAR(36) NOT NULL REFERENCES output_streams(id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_stream_permissions_user UNIQUE (user_id, output_stream_id)
);

CREATE TABLE IF NOT EXISTS groups (
    id VARCHAR(36) PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS group_members (
    id VARCHAR(36) PRIMARY KEY,
    group_id VARCHAR(36) NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_group_members UNIQUE (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS stream_permissions_group (
    id VARCHAR(36) PRIMARY KEY,
    group_id VARCHAR(36) NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    output_stream_id VARCHAR(36) NOT NULL REFERENCES output_streams(id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_stream_permissions_group UNIQUE (group_id, output_stream_id)
);

CREATE TABLE IF NOT EXISTS ingest_event_logs (
    id VARCHAR(36) PRIMARY KEY,
    ingest_session_id VARCHAR(36) NOT NULL REFERENCES ingest_sessions(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    actor_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NULL,
    action VARCHAR(128) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(64) NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_users_username ON admin_users(username);
CREATE INDEX IF NOT EXISTS idx_ingest_sessions_current_output_stream_id ON ingest_sessions(current_output_stream_id);
CREATE INDEX IF NOT EXISTS idx_ingest_sessions_status ON ingest_sessions(status);
CREATE INDEX IF NOT EXISTS idx_output_streams_source_ingest_session_id ON output_streams(source_ingest_session_id);
CREATE INDEX IF NOT EXISTS idx_output_streams_visibility ON output_streams(visibility);
CREATE INDEX IF NOT EXISTS idx_ingest_event_logs_ingest_session_id_created_at ON ingest_event_logs(ingest_session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_target_type_target_id_created_at ON audit_logs(target_type, target_id, created_at DESC);
