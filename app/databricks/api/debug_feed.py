"""Operator preview and recognition diagnostics for one camera."""

from base64 import b64encode
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import Header, HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

PREVIEW_LIMIT = 200_000
REPORT_LIMIT = 1_500_000


class Detection(BaseModel):
    box: tuple[int, int, int, int]
    score: float


class DebugReport(BaseModel):
    id: UUID
    width: int = Field(ge=1, le=3840)
    height: int = Field(ge=1, le=2160)
    frame_number: int = Field(ge=1)
    zone: str | None
    elapsed: float
    threshold: float
    decision: str = Field(max_length=300)
    notes: list[str] = Field(max_length=20)
    detection: Detection | None
    frame: str
    crop: str | None
    ocr_input: str | None


async def read_payload(request, limit):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise HTTPException(413, "Debug payload is too large")
        body.extend(chunk)
    return body


def register_debug_routes(router, connect, camera_id, require_operator, require_device,
                          require_setup_action, garage_enabled):
    @router.get("/debug/access")
    def debug_access(x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        return {"ok": True}

    @router.post("/debug/view")
    def view(x_forwarded_user: str = Header(default=""),
             x_parksight_setup: str = Header(default="")):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        with connect() as conn:
            frame, frame_at, report_id = conn.execute(
                """INSERT INTO parksight_camera_debug (camera_id, viewed_until)
                   VALUES (%s, now() + interval '10 seconds')
                   ON CONFLICT (camera_id) DO UPDATE
                   SET viewed_until = EXCLUDED.viewed_until
                   RETURNING CASE WHEN preview_at > now() - interval '4 seconds'
                                  THEN preview END, preview_at, report_id""",
                (camera_id,),
            ).fetchone()
            layout = conn.execute(
                """SELECT calibration FROM parksight_camera_setup WHERE camera_id = %s""",
                (camera_id,),
            ).fetchone()
            latest = None
            if garage_enabled:
                latest = conn.execute(
                    """SELECT plate, zone, outcome, received_at FROM parksight_garage_events
                       WHERE camera_id = %s ORDER BY received_at DESC LIMIT 1""",
                    (camera_id,),
                ).fetchone()
        return {
            "preview": b64encode(frame).decode() if frame is not None else None,
            "preview_at": frame_at,
            "report_id": report_id,
            "zones": {name: layout[0][name] for name in ("entry", "exit")}
            if layout and layout[0] else None,
            "zone_image_size": layout[0]["image_size"] if layout and layout[0] else None,
            "garage": dict(zip(("plate", "zone", "outcome", "received_at"), latest))
            if latest else None,
        }

    @router.get("/debug/report")
    def report(x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        with connect() as conn:
            row = conn.execute(
                """SELECT report, report_at FROM parksight_camera_debug WHERE camera_id = %s""",
                (camera_id,),
            ).fetchone()
        return {"report": row[0], "received_at": row[1]} if row else {"report": None}

    @router.post("/debug/run", status_code=202)
    def run_models(x_forwarded_user: str = Header(default=""),
                   x_parksight_setup: str = Header(default="")):
        require_operator(x_forwarded_user)
        require_setup_action(x_parksight_setup)
        with connect() as conn:
            row = conn.execute(
                """INSERT INTO parksight_camera_debug
                       (camera_id, viewed_until, manual_id, manual_until)
                   VALUES (%s, now(), %s, now() + interval '30 seconds')
                   ON CONFLICT (camera_id) DO UPDATE
                   SET manual_id = EXCLUDED.manual_id, manual_until = EXCLUDED.manual_until,
                       manual_report = NULL, manual_at = NULL
                   WHERE parksight_camera_debug.manual_until IS NULL
                      OR parksight_camera_debug.manual_until <= now()
                      OR parksight_camera_debug.manual_report IS NOT NULL
                   RETURNING manual_id""",
                (camera_id, uuid4()),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT manual_id FROM parksight_camera_debug WHERE camera_id = %s",
                    (camera_id,),
                ).fetchone()
        return {"id": row[0]}

    @router.get("/debug/run/{request_id}")
    def manual_result(request_id: UUID, x_forwarded_user: str = Header(default="")):
        require_operator(x_forwarded_user)
        with connect() as conn:
            row = conn.execute(
                """SELECT manual_report, manual_at, manual_until > now()
                   FROM parksight_camera_debug WHERE camera_id = %s AND manual_id = %s""",
                (camera_id, request_id),
            ).fetchone()
        if row is None or (row[0] is None and not row[2]):
            raise HTTPException(410, "Manual run expired. Check the camera and try again.")
        return {"report": row[0], "received_at": row[1]}

    def save_preview(jpeg, width, height):
        try:
            with Image.open(BytesIO(jpeg), formats=["JPEG"]) as image:
                if image.size != (width, height):
                    raise ValueError("Preview dimensions disagree")
                image.verify()
        except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError) as error:
            raise HTTPException(400, "Invalid debug preview") from error
        with connect() as conn:
            conn.execute(
                """UPDATE parksight_camera_debug SET preview = %s, preview_at = now()
                   WHERE camera_id = %s AND viewed_until > now()""",
                (bytes(jpeg), camera_id),
            )

    @router.put("/device/debug/preview", status_code=204)
    async def publish_preview(request: Request, x_image_width: int = Header(ge=1, le=640),
                              x_image_height: int = Header(ge=1, le=640),
                              x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        if request.headers.get("content-type") != "image/jpeg":
            raise HTTPException(415, "Expected a JPEG preview")
        jpeg = await read_payload(request, PREVIEW_LIMIT)
        await run_in_threadpool(save_preview, jpeg, x_image_width, x_image_height)
        return Response(status_code=204)

    def save_report(payload):
        with connect() as conn:
            updated = conn.execute(
                """UPDATE parksight_camera_debug SET report_id = %s, report = %s, report_at = now()
                   WHERE camera_id = %s AND viewed_until > now()""",
                (payload.id, Jsonb(payload.model_dump(mode="json")), camera_id),
            ).rowcount
            if not updated:
                raise HTTPException(409, "No active debug viewer")

    async def parse_report(request):
        body = await read_payload(request, REPORT_LIMIT)
        try:
            return DebugReport.model_validate_json(body)
        except ValidationError as error:
            raise HTTPException(400, "Invalid recognition report") from error

    @router.put("/device/debug/report", status_code=204)
    async def publish_report(request: Request, x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        payload = await parse_report(request)
        await run_in_threadpool(save_report, payload)
        return Response(status_code=204)

    def save_manual_report(payload):
        with connect() as conn:
            updated = conn.execute(
                """UPDATE parksight_camera_debug
                   SET manual_report = %s, manual_at = COALESCE(manual_at, now())
                   WHERE camera_id = %s AND manual_id = %s AND manual_until > now()""",
                (Jsonb(payload.model_dump(mode="json")), camera_id, payload.id),
            ).rowcount
            if not updated:
                raise HTTPException(409, "Manual run expired or was replaced")

    @router.put("/device/debug/manual-report", status_code=204)
    async def publish_manual_report(request: Request,
                                    x_parksight_device_key: str = Header(default="")):
        require_device(x_parksight_device_key)
        payload = await parse_report(request)
        await run_in_threadpool(save_manual_report, payload)
        return Response(status_code=204)
