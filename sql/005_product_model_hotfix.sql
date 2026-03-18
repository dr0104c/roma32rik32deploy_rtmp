ALTER TABLE ingest_sessions DROP CONSTRAINT IF EXISTS ingest_sessions_status_check;
ALTER TABLE ingest_sessions DROP CONSTRAINT IF EXISTS ck_ingest_sessions_status;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'output_streams'
          AND column_name = 'playback_name'
    ) THEN
        ALTER TABLE output_streams ALTER COLUMN playback_name DROP NOT NULL;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'output_streams'
          AND column_name = 'ingest_key'
    ) THEN
        ALTER TABLE output_streams ALTER COLUMN ingest_key DROP NOT NULL;
    END IF;
END $$;

UPDATE ingest_sessions
SET source_label = COALESCE(source_label, publisher_label),
    started_at = COALESCE(started_at, last_publish_started_at),
    ended_at = COALESCE(ended_at, last_publish_stopped_at),
    revoked_at = CASE WHEN status = 'revoked' AND revoked_at IS NULL THEN COALESCE(last_publish_stopped_at, NOW()) ELSE revoked_at END,
    current_output_stream_id = COALESCE(current_output_stream_id, output_stream_id),
    status = CASE
        WHEN status IN ('connecting', 'live') THEN 'live'
        WHEN status IN ('offline', 'error') THEN 'ended'
        ELSE status
    END
WHERE source_label IS NULL
   OR started_at IS NULL
   OR current_output_stream_id IS NULL
   OR status IN ('connecting', 'offline', 'error');

ALTER TABLE ingest_sessions
    ADD CONSTRAINT ck_ingest_sessions_status
    CHECK (status IN ('created','live','ended','revoked'));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_ingest_sessions_current_output_stream'
    ) THEN
        ALTER TABLE ingest_sessions
            ADD CONSTRAINT fk_ingest_sessions_current_output_stream
            FOREIGN KEY (current_output_stream_id) REFERENCES output_streams(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ingest_sessions_current_output_stream_id ON ingest_sessions(current_output_stream_id);
CREATE INDEX IF NOT EXISTS idx_ingest_sessions_status ON ingest_sessions(status);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_output_streams_source_ingest_session'
    ) THEN
        ALTER TABLE output_streams
            ADD CONSTRAINT fk_output_streams_source_ingest_session
            FOREIGN KEY (source_ingest_session_id) REFERENCES ingest_sessions(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS ingest_event_logs (
    id VARCHAR(36) PRIMARY KEY,
    ingest_session_id VARCHAR(36) NOT NULL REFERENCES ingest_sessions(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingest_event_logs_ingest_session_id_created_at
    ON ingest_event_logs(ingest_session_id, created_at DESC);

ALTER TABLE stream_permissions_group ADD COLUMN IF NOT EXISTS granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
