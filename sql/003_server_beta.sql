DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'users'
          AND column_name = 'id'
          AND data_type IN ('bigint', 'integer')
    ) THEN
        DROP TABLE IF EXISTS playback_sessions CASCADE;
        DROP TABLE IF EXISTS user_stream_grants CASCADE;
        DROP TABLE IF EXISTS ingest_sessions CASCADE;
        DROP TABLE IF EXISTS output_streams CASCADE;
        DROP TABLE IF EXISTS user_status_history CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
        DROP TABLE IF EXISTS audit_log CASCADE;
    END IF;
END $$;

DROP TABLE IF EXISTS audit_log CASCADE;

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
    playback_name VARCHAR(128) NOT NULL UNIQUE,
    ingest_key VARCHAR(64) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingest_sessions (
    id VARCHAR(36) PRIMARY KEY,
    output_stream_id VARCHAR(36) NULL REFERENCES output_streams(id) ON DELETE SET NULL,
    ingest_key VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('created','connecting','live','offline','revoked','error')),
    publisher_label TEXT NULL,
    last_seen_at TIMESTAMPTZ NULL,
    last_publish_started_at TIMESTAMPTZ NULL,
    last_publish_stopped_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ingest_sessions
    ADD COLUMN IF NOT EXISTS publisher_label TEXT NULL,
    ADD COLUMN IF NOT EXISTS last_publish_started_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS last_publish_stopped_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS last_error TEXT NULL;

ALTER TABLE ingest_sessions DROP CONSTRAINT IF EXISTS ingest_sessions_status_check;
ALTER TABLE ingest_sessions
    ADD CONSTRAINT ingest_sessions_status_check
    CHECK (status IN ('created','connecting','live','offline','revoked','error'));

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
    CONSTRAINT uq_stream_permissions_group UNIQUE (group_id, output_stream_id)
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
