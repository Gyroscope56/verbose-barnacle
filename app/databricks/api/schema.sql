CREATE TABLE IF NOT EXISTS parksight_camera_setup (
    camera_id text PRIMARY KEY,
    request_id uuid,
    requested_at timestamptz,
    snapshot_id uuid,
    width integer,
    height integer,
    jpeg bytea,
    calibration jsonb
);
