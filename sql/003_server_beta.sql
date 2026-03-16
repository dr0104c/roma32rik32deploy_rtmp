ALTER TABLE users ADD COLUMN IF NOT EXISTS status_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_reason VARCHAR(255) NULL;

ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS path_name VARCHAR(128);
UPDATE output_streams SET path_name = COALESCE(path_name, regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g')) WHERE path_name IS NULL;
ALTER TABLE output_streams ALTER COLUMN path_name SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'output_streams_path_name_key') THEN
    ALTER TABLE output_streams ADD CONSTRAINT output_streams_path_name_key UNIQUE (path_name);
  END IF;
END $$;
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'offline';
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS last_publish_started_at TIMESTAMPTZ NULL;
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS last_publish_stopped_at TIMESTAMPTZ NULL;
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL;

ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'created';
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NULL;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ NULL;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS playback_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    output_stream_id BIGINT NOT NULL REFERENCES output_streams(id) ON DELETE CASCADE,
    jti VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'issued',
    client_ip VARCHAR(64) NULL,
    user_agent VARCHAR(255) NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    activated_at TIMESTAMPTZ NULL,
    ended_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL
);

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS result VARCHAR(32) NULL;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS reason VARCHAR(255) NULL;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip VARCHAR(64) NULL;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent VARCHAR(255) NULL;
