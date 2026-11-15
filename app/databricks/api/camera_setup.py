"""Mount on my-web-api. The Databricks Apps proxy authenticates callers."""

from hmac import compare_digest
from io import BytesIO
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

MAX_IMAGE_BYTES = 1024 * 1024


class Zone(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0.02, le=1)
    height: float = Field(ge=0.02, le=1)

    @model_validator(mode="after")
    def within_frame(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Zone extends outside the reference image")
        return self


class Calibration(BaseModel):
    reference_id: UUID
    entry: Zone
    exit: Zone

    @model_validator(mode="after")
    def separate_zones(self):
        a, b = self.entry, self.exit
        if (min(a.x + a.width, b.x + b.width) - max(a.x, b.x) > 1e-6
                and min(a.y + a.height, b.y + b.height) - max(a.y, b.y) > 1e-6):
            raise ValueError("Entry and exit zones must not overlap")
        return self


class GarageRead(BaseModel):
    id: UUID
    zone: Literal["entry", "exit"]
    plate: str = Field(pattern=r"^[A-Z0-9]{5,8}$")


def camera_setup_router(connect, camera_id, operators, device_key, record_read=None,
                        debug_enabled=False):
    """Connect is the existing backend's PostgreSQL connection factory."""
    if not operators or not device_key:
        raise ValueError("Camera setup requires allowed operators and a device key")
    router = APIRouter(prefix="/api/camera-setup")

    def require_operator(user):
        if not user or user.casefold() not in operators:
            raise HTTPException(403, "Camera setup requires operator access")

    def require_device(key):
        if not key or not compare_digest(key.encode(), device_key.encode()):
            raise HTTPException(403, "Camera device access denied")

    def require_setup_action(value):
        if value != "1":
            raise HTTPException(403, "Use the camera setup controls to make changes")

    if debug_enabled:
        if __package__:
            from .debug_feed import register_debug_routes
        else:
            from debug_feed import register_debug_routes

        register_debug_routes(router, connect, camera_id, require_operator, require_device,
                              require_setup_action, record_read is not None)

    def compatible_calibration(calibration, width, height):
        if calibration is not None and width and height:
            old_width, old_height = calibration["image_size"]
            if old_width * height == width * old_height:
                return {key: value for key, value in calibration.items()
                        if key not in {"divider", "reverse"}}
        return None

    @router.get("")
    def status(x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        with connect() as conn:
            row = conn.execute(
                """SELECT snapshot_id, width, height, calibration, request_id,
                          requested_at > NOW() - interval '30 seconds'
                   FROM parksight_camera_setup WHERE camera_id = %s""",
                (camera_id,),
            ).fetchone()
        if row is None:
            return {"snapshot": None, "calibration": None, "pending": None}
        snapshot, width, height, calibration, request_id, active = row
        return {
            "snapshot": {"id": snapshot, "width": width, "height": height}
            if snapshot
            else None,
            "calibration": compatible_calibration(calibration, width, height),
            "pending": request_id if active else None,
        }

    @router.post("/capture", status_code=202)
    def capture(
        x_forwarded_user: str = Header(default=""),
        x_parksight_setup: str = Header(default=""),
    ):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        request_id = uuid4()
        with connect() as conn:
            conn.execute(
                """INSERT INTO parksight_camera_setup (camera_id, request_id, requested_at)
                   VALUES (%s, %s, NOW())
                   ON CONFLICT (camera_id) DO UPDATE
                   SET request_id = EXCLUDED.request_id, requested_at = EXCLUDED.requested_at""",
                (camera_id, request_id),
            )
        return {"id": request_id}

    @router.get("/snapshot/{snapshot_id}")
    def snapshot(snapshot_id: UUID, x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        with connect() as conn:
            row = conn.execute(
                "SELECT jpeg FROM parksight_camera_setup WHERE camera_id = %s AND snapshot_id = %s",
                (camera_id, snapshot_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Reference image not found")
        return Response(
            bytes(row[0]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @router.put("/calibration")
    def save(
        calibration: Calibration,
        x_forwarded_user: str = Header(default=""),
        x_parksight_setup: str = Header(default=""),
    ):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        with connect() as conn:
            row = conn.execute(
                """SELECT width, height FROM parksight_camera_setup
                   WHERE camera_id = %s AND snapshot_id = %s FOR UPDATE""",
                (camera_id, calibration.reference_id),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    409, "The reference image changed; reload before saving"
                )
            saved = {
                **calibration.model_dump(mode="json"),
                "image_size": list(row),
                "version": 1,
            }
            conn.execute(
                "UPDATE parksight_camera_setup SET calibration = %s WHERE camera_id = %s",
                (Jsonb(saved), camera_id),
            )
        return saved

    @router.get("/device/request")
    def next_request(x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        with connect() as conn:
            row = conn.execute(
                """SELECT CASE WHEN requested_at > NOW() - interval '30 seconds'
                               THEN request_id END, calibration, width, height
                   FROM parksight_camera_setup WHERE camera_id = %s""",
                (camera_id,),
            ).fetchone()
            debug_requested = debug_enabled and conn.execute(
                """SELECT EXISTS (SELECT 1 FROM parksight_camera_debug
                                  WHERE camera_id = %s AND viewed_until > now())""",
                (camera_id,),
            ).fetchone()[0]
        request_id, calibration, width, height = row or (None, None, None, None)
        return {
            "id": request_id,
            "calibration": compatible_calibration(calibration, width, height),
            "garage_enabled": record_read is not None,
            "debug_requested": debug_requested,
        }

    if record_read is not None:
        @router.post("/device/garage-read")
        def garage_read(read: GarageRead, x_parksight_device_key: str = Header(default="")):
            require_device(x_parksight_device_key)
            with connect() as conn:
                return record_read(conn, camera_id, read.id, read.zone, read.plate)

    def store_snapshot(request_id, jpeg, width, height):
        try:
            with Image.open(BytesIO(jpeg), formats=["JPEG"]) as image:
                if image.size != (width, height):
                    raise HTTPException(
                        400, "Reference dimensions do not match the JPEG"
                    )
                image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise HTTPException(400, "Invalid JPEG reference image") from error
        with connect() as conn:
            row = conn.execute(
                """UPDATE parksight_camera_setup
                   SET jpeg = %s, width = %s, height = %s, snapshot_id = request_id,
                       request_id = NULL, requested_at = NULL
                   WHERE camera_id = %s AND request_id = %s
                     AND requested_at > NOW() - interval '30 seconds'
                   RETURNING snapshot_id""",
                (jpeg, width, height, camera_id, request_id),
            ).fetchone()
        if row is None:
            raise HTTPException(409, "Capture request expired or was replaced")

    @router.put("/device/snapshot/{request_id}", status_code=204)
    async def publish(
        request_id: UUID,
        request: Request,
        x_image_width: int = Header(),
        x_image_height: int = Header(),
        x_parksight_device_key: str = Header(default=""),
    ):
        require_device(x_parksight_device_key)
        if not (1 <= x_image_width <= 3840 and 1 <= x_image_height <= 2160):
            raise HTTPException(400, "Invalid reference dimensions")
        if request.headers.get("content-type") != "image/jpeg":
            raise HTTPException(415, "Expected a JPEG reference image")
        jpeg = bytearray()
        async for chunk in request.stream():
            if len(jpeg) + len(chunk) > MAX_IMAGE_BYTES:
                raise HTTPException(413, "Reference image is too large")
            jpeg.extend(chunk)
        await run_in_threadpool(
            store_snapshot, request_id, bytes(jpeg), x_image_width, x_image_height
        )
        return Response(status_code=204)

    return router
