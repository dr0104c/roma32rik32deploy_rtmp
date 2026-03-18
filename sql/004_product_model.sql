ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS public_name VARCHAR(128);
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS visibility VARCHAR(16);
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS playback_path VARCHAR(128);
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS playback_name VARCHAR(128);
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS source_ingest_session_id VARCHAR(36);
ALTER TABLE output_streams ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE output_streams
SET public_name = COALESCE(NULLIF(public_name, ''), playback_name, name),
    title = COALESCE(NULLIF(title, ''), name),
    visibility = COALESCE(NULLIF(visibility, ''), 'private'),
    playback_path = COALESCE(NULLIF(playback_path, ''), playback_name)
WHERE public_name IS NULL
   OR title IS NULL
   OR visibility IS NULL
   OR playback_path IS NULL;

ALTER TABLE output_streams ALTER COLUMN public_name SET NOT NULL;
ALTER TABLE output_streams ALTER COLUMN title SET NOT NULL;
ALTER TABLE output_streams ALTER COLUMN visibility SET DEFAULT 'private';
ALTER TABLE output_streams ALTER COLUMN visibility SET NOT NULL;
ALTER TABLE output_streams ALTER COLUMN playback_path SET NOT NULL;

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

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_output_streams_visibility'
    ) THEN
        ALTER TABLE output_streams
            ADD CONSTRAINT ck_output_streams_visibility
            CHECK (visibility IN ('private','public','unlisted','disabled'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_output_streams_public_name ON output_streams(public_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_output_streams_playback_path ON output_streams(playback_path);
CREATE INDEX IF NOT EXISTS idx_output_streams_source_ingest_session_id ON output_streams(source_ingest_session_id);
CREATE INDEX IF NOT EXISTS idx_output_streams_visibility ON output_streams(visibility);

ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS source_label TEXT;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS current_output_stream_id VARCHAR(36);
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS publisher_label TEXT;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS last_publish_started_at TIMESTAMPTZ;
ALTER TABLE ingest_sessions ADD COLUMN IF NOT EXISTS last_publish_stopped_at TIMESTAMPTZ;

ALTER TABLE ingest_sessions DROP CONSTRAINT IF EXISTS ck_ingest_sessions_status;
ALTER TABLE ingest_sessions DROP CONSTRAINT IF EXISTS ingest_sessions_status_check;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'ingest_sessions'
          AND column_name = 'output_stream_id'
    ) THEN
        EXECUTE $sql$
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
               OR status IN ('connecting', 'offline', 'error')
        $sql$;
    ELSE
        EXECUTE $sql$
            UPDATE ingest_sessions
            SET source_label = COALESCE(source_label, publisher_label),
                started_at = COALESCE(started_at, last_publish_started_at),
                ended_at = COALESCE(ended_at, last_publish_stopped_at),
                revoked_at = CASE WHEN status = 'revoked' AND revoked_at IS NULL THEN COALESCE(last_publish_stopped_at, NOW()) ELSE revoked_at END,
                status = CASE
                    WHEN status IN ('connecting', 'live') THEN 'live'
                    WHEN status IN ('offline', 'error') THEN 'ended'
                    ELSE status
                END
            WHERE source_label IS NULL
               OR started_at IS NULL
               OR status IN ('connecting', 'offline', 'error')
        $sql$;
    END IF;
END $$;

ALTER TABLE ingest_sessions
    ADD CONSTRAINT ck_ingest_sessions_status
    CHECK (status IN ('created','live','ended','revoked'));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_ingest_sessions_ingest_key'
    ) THEN
        ALTER TABLE ingest_sessions
            ADD CONSTRAINT uq_ingest_sessions_ingest_key UNIQUE (ingest_key);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ingest_sessions_current_output_stream'
    ) THEN
        ALTER TABLE ingest_sessions
            ADD CONSTRAINT fk_ingest_sessions_current_output_stream
            FOREIGN KEY (current_output_stream_id) REFERENCES output_streams(id) ON DELETE SET NULL;
    END IF;
END $$;

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

CREATE INDEX IF NOT EXISTS idx_ingest_sessions_current_output_stream_id ON ingest_sessions(current_output_stream_id);
CREATE INDEX IF NOT EXISTS idx_ingest_sessions_status ON ingest_sessions(status);

CREATE TABLE IF NOT EXISTS ingest_event_logs (
    id VARCHAR(36) PRIMARY KEY,
    ingest_session_id VARCHAR(36) NOT NULL REFERENCES ingest_sessions(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingest_event_logs_ingest_session_id_created_at ON ingest_event_logs(ingest_session_id, created_at DESC);

ALTER TABLE stream_permissions_group ADD COLUMN IF NOT EXISTS granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
