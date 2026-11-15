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
