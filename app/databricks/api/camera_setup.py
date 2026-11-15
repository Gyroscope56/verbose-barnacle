"""Mount on my-web-api. The Databricks Apps proxy authenticates callers."""

from hmac import compare_digest
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

MAX_IMAGE_BYTES = 1024 * 1024


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


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
    divider: tuple[Point, Point]
    entry: Zone
    exit: Zone
    reverse: bool = False

    @model_validator(mode="after")
    def valid_divider(self):
        a, b = self.divider
        if (a.x - b.x) ** 2 + (a.y - b.y) ** 2 < 0.02**2:
            raise ValueError("Draw a divider with two distinct endpoints")
        return self


def camera_setup_router(connect, camera_id, operators, device_key):
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
        if calibration and snapshot and calibration["reference_id"] != str(snapshot):
            old_width, old_height = calibration["image_size"]
            if old_width * height != width * old_height:
                calibration = None
        return {
            "snapshot": {"id": snapshot, "width": width, "height": height}
            if snapshot
            else None,
            "calibration": calibration,
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
                """SELECT request_id FROM parksight_camera_setup
                   WHERE camera_id = %s AND requested_at > NOW() - interval '30 seconds'""",
                (camera_id,),
            ).fetchone()
        return {"id": row[0] if row else None}

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
