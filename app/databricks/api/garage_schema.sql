CREATE TABLE IF NOT EXISTS parksight_garage_events (
    camera_id text NOT NULL,
    event_id uuid NOT NULL,
    zone text NOT NULL CHECK (zone IN ('entry', 'exit')),
    plate text NOT NULL,
    outcome text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (camera_id, event_id)
);
