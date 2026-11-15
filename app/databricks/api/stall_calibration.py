"""Collect sensor samples and save the installed stall's distance thresholds."""

from typing import Literal
from uuid import UUID, uuid4
from contextlib import nullcontext
from functools import partial

from fastapi import Header, HTTPException
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

if __package__:
    from ...spot_updater import update_occupancy
else:
    from spot_updater import update_occupancy


class SampleResult(BaseModel):
    distance_mm: int | None = Field(ge=1, le=1200)
    error: Literal["insufficient", "unstable"] | None = None


class SpotAssignment(BaseModel):
    spot_id: str = Field(min_length=1, max_length=128)


class OccupancyReading(BaseModel):
    assignment_revision: UUID
    calibration_revision: UUID
    occupied: bool = Field(strict=True)


def register_stall_routes(router, connect, camera_id, require_operator, require_device,
                          require_setup_action):
    @router.get("/stall")
    def status(x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        with connect() as conn:
            row = conn.execute(
                """SELECT clear_mm, occupied_mm, settings, applied_revision, sample_error,
                          CASE WHEN sample_until > now() THEN sample_kind END,
                          CASE WHEN sample_until <= now() THEN sample_kind END,
                          spot_id, is_occupied, occupancy_reported_at,
                          occupancy_reported_at > now() - interval '60 seconds'
                   FROM parksight_stall_calibration
                   LEFT JOIN parking_spots ON floor_zone_number = spot_id
                   WHERE camera_id = %s""",
                (camera_id,),
            ).fetchone()
        (clear, occupied, settings, applied, error, pending, expired,
         spot, is_occupied, reported_at, fresh) = row or (None,) * 11
        return {
            "clear_mm": clear, "occupied_mm": occupied, "settings": settings,
            "applied": bool(settings and str(applied) == settings["revision"]),
            "error": "timeout" if expired else error, "pending": pending,
            "spot_id": spot, "is_occupied": is_occupied,
            "occupancy_reported_at": reported_at, "occupancy_fresh": bool(fresh),
        }

    @router.get("/stall/spots")
    def spots(x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        with connect() as conn:
            rows = conn.execute(
                """SELECT floor_zone_number FROM parking_spots
                   WHERE floor_zone_number IS NOT NULL ORDER BY floor_zone_number"""
            ).fetchall()
        return {"spots": [row[0] for row in rows]}

    @router.put("/stall/spot")
    def assign_spot(assignment: SpotAssignment, x_forwarded_user: str = Header(default=""),
                    x_parksight_setup: str = Header(default="")):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        try:
            with connect() as conn:
                if conn.execute(
                    "SELECT 1 FROM parking_spots WHERE floor_zone_number = %s",
                    (assignment.spot_id,),
                ).fetchone() is None:
                    raise HTTPException(404, "Parking spot not found.")
                conn.execute(
                    """INSERT INTO parksight_stall_calibration (camera_id, spot_id, spot_revision)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (camera_id) DO UPDATE
                       SET spot_id = EXCLUDED.spot_id, spot_revision = EXCLUDED.spot_revision,
                           occupancy_reported_at = NULL
                       WHERE parksight_stall_calibration.spot_id IS DISTINCT FROM EXCLUDED.spot_id""",
                    (camera_id, assignment.spot_id, uuid4()),
                )
        except UniqueViolation as error:
            raise HTTPException(409, "That spot is already linked to another sensor.") from error
        return {"spot_id": assignment.spot_id}

    @router.post("/stall/sample/{kind}", status_code=202)
    def request_sample(kind: Literal["clear", "occupied"],
                       x_forwarded_user: str = Header(default=""),
                       x_parksight_setup: str = Header(default="")):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        with connect() as conn:
            row = conn.execute(
                """INSERT INTO parksight_stall_calibration
                       (camera_id, sample_id, sample_kind, sample_until)
                   VALUES (%s, %s, %s, now() + interval '25 seconds')
                   ON CONFLICT (camera_id) DO UPDATE SET
                       sample_id = EXCLUDED.sample_id, sample_kind = EXCLUDED.sample_kind,
                       sample_until = EXCLUDED.sample_until, sample_error = NULL,
                       clear_mm = CASE WHEN EXCLUDED.sample_kind = 'clear' THEN NULL
                                       ELSE parksight_stall_calibration.clear_mm END,
                       occupied_mm = CASE WHEN EXCLUDED.sample_kind = 'occupied' THEN NULL
                                          ELSE parksight_stall_calibration.occupied_mm END
                   WHERE parksight_stall_calibration.sample_until IS NULL
                      OR parksight_stall_calibration.sample_until <= now()
                   RETURNING sample_id""",
                (camera_id, uuid4(), kind),
            ).fetchone()
        if row is None:
            raise HTTPException(409, "Wait for the current distance sample to finish.")
        return {"id": row[0]}

    @router.put("/device/stall/sample/{request_id}", status_code=204)
    def publish_sample(request_id: UUID, result: SampleResult,
                       x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        if (result.distance_mm is None) != (result.error is not None):
            raise HTTPException(422, "Supply either a distance or a sampling error.")
        with connect() as conn:
            updated = conn.execute(
                """UPDATE parksight_stall_calibration SET
                       clear_mm = CASE WHEN sample_kind = 'clear' THEN %s ELSE clear_mm END,
                       occupied_mm = CASE WHEN sample_kind = 'occupied' THEN %s ELSE occupied_mm END,
                       sample_error = %s, sample_id = NULL, sample_kind = NULL, sample_until = NULL
                   WHERE camera_id = %s AND sample_id = %s AND sample_until > now()""",
                (result.distance_mm, result.distance_mm, result.error, camera_id, request_id),
            ).rowcount
            if not updated:
                raise HTTPException(409, "Distance sample expired or was already received.")

    @router.post("/stall/apply")
    def apply(x_forwarded_user: str = Header(default=""),
              x_parksight_setup: str = Header(default="")):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        with connect() as conn:
            row = conn.execute(
                """SELECT clear_mm, occupied_mm, sample_until > now()
                   FROM parksight_stall_calibration WHERE camera_id = %s FOR UPDATE""",
                (camera_id,),
            ).fetchone()
            if not row or row[0] is None or row[1] is None or row[2]:
                raise HTTPException(409, "Capture an empty and an occupied sample first.")
            clear, occupied, _ = row
            gap = clear - occupied
            if gap < 20:
                raise HTTPException(422, "The empty sample must be at least 20 mm farther away.")
            settings = {
                "clear_mm": clear, "occupied_mm": occupied, "revision": str(uuid4()),
                "occupied_below_mm": occupied + gap // 3,
                "clear_above_mm": clear - gap // 3,
            }
            conn.execute(
                """UPDATE parksight_stall_calibration
                   SET settings = %s, occupancy_reported_at = NULL WHERE camera_id = %s""",
                (Jsonb(settings), camera_id),
            )
        return settings

    @router.put("/device/stall/applied/{revision}", status_code=204)
    def acknowledge(revision: UUID, x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        with connect() as conn:
            conn.execute(
                """UPDATE parksight_stall_calibration SET applied_revision = %s
                   WHERE camera_id = %s AND settings->>'revision' = %s""",
                (revision, camera_id, str(revision)),
            )

    @router.put("/device/stall/occupancy", status_code=204)
    def publish_occupancy(reading: OccupancyReading,
                          x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        with connect() as conn:
            row = conn.execute(
                """SELECT spot_id FROM parksight_stall_calibration
                   WHERE camera_id = %s AND spot_revision = %s AND applied_revision = %s
                     AND settings->>'revision' = %s FOR UPDATE""",
                (camera_id, reading.assignment_revision, reading.calibration_revision,
                 str(reading.calibration_revision)),
            ).fetchone()
            if row is None:
                raise HTTPException(409, "Sensor calibration or spot assignment has changed.")
            try:
                update_occupancy(row[0], reading.occupied, connection=partial(nullcontext, conn))
            except ValueError as error:
                raise HTTPException(409, "The assigned parking spot is unavailable.") from error
            conn.execute(
                """UPDATE parksight_stall_calibration SET occupancy_reported_at = now()
                   WHERE camera_id = %s""",
                (camera_id,),
            )
