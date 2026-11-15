CREATE TABLE IF NOT EXISTS parksight_stall_calibration (
    camera_id text PRIMARY KEY,
    clear_mm integer,
    occupied_mm integer,
    sample_id uuid,
    sample_kind text CHECK (sample_kind IN ('clear', 'occupied')),
    sample_until timestamptz,
    sample_error text,
    settings jsonb,
    applied_revision uuid
);

ALTER TABLE parksight_stall_calibration
    ADD COLUMN IF NOT EXISTS spot_id text,
    ADD COLUMN IF NOT EXISTS spot_revision uuid,
    ADD COLUMN IF NOT EXISTS occupancy_reported_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS parksight_stall_spot_unique
    ON parksight_stall_calibration (spot_id) WHERE spot_id IS NOT NULL;
