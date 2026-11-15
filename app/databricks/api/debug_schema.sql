CREATE TABLE IF NOT EXISTS parksight_camera_debug (
    camera_id text PRIMARY KEY,
    viewed_until timestamptz NOT NULL,
    preview bytea,
    preview_at timestamptz,
    report_id uuid,
    report jsonb,
    report_at timestamptz
);

ALTER TABLE parksight_camera_debug
    ADD COLUMN IF NOT EXISTS manual_id uuid,
    ADD COLUMN IF NOT EXISTS manual_until timestamptz,
    ADD COLUMN IF NOT EXISTS manual_report jsonb,
    ADD COLUMN IF NOT EXISTS manual_at timestamptz;

CREATE INDEX IF NOT EXISTS parksight_garage_events_recent
    ON parksight_garage_events (camera_id, received_at DESC);
