"""One outbound snapshot worker for the Databricks camera setup API."""

import json
import os
import sqlite3
from base64 import b64encode
from contextlib import closing
from threading import Event, Lock, Thread
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

import cv2
from stall_sensor import StallSensor


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_origin(url, suffix):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(suffix)
            or parsed.netloc != parsed.hostname or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("Expected a Databricks HTTPS origin")
    return url.rstrip("/")


def detection_regions(layout, width, height):
    """Return named pixel rectangles for a saved layout at a compatible aspect ratio."""
    if layout is None:
        return ()
    reference_width, reference_height = layout["image_size"]
    if layout["version"] != 1 or reference_width <= 0 or reference_height <= 0:
        raise ValueError("Invalid camera layout metadata")
    regions = []
    for name in ("entry", "exit"):
        zone = layout[name]
        left, top = zone["x"], zone["y"]
        right, bottom = left + zone["width"], top + zone["height"]
        if not (0 <= left < right <= 1.000001 and 0 <= top < bottom <= 1.000001):
            raise ValueError("Invalid camera detection zone")
        x = min(width - 1, round(left * width))
        y = min(height - 1, round(top * height))
        regions.append((name, (x, y, max(x + 1, min(width, round(right * width))),
                               max(y + 1, min(height, round(bottom * height))))))
    return tuple(regions) if reference_width * height == width * reference_height else ()


class DeviceClient:
    def __init__(self, workspace_url, api_url, client_id, client_secret, device_key):
        workspace = https_origin(workspace_url, ".cloud.databricks.com")
        self.oauth_url = workspace + "/oidc/v1/token"
        self.api_url = https_origin(api_url, ".databricksapps.com") + "/api/camera-setup/device"
        self.basic = b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
        self.device_key = device_key
        self.opener = build_opener(NoRedirects())
        self.token = None
        self.refresh_at = 0

    def access_token(self):
        if self.token and monotonic() < self.refresh_at:
            return self.token
        body = urlencode({"grant_type": "client_credentials", "scope": "all-apis"}).encode()
        request = Request(self.oauth_url, data=body, headers={
            "Authorization": f"Basic {self.basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with self.opener.open(request, timeout=5) as response:
            data = json.load(response)
        self.token = data["access_token"]
        self.refresh_at = monotonic() + max(0, int(data["expires_in"]) - 60)
        return self.token

    def call(self, path, **options):
        headers = options.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {self.access_token()}",
            "X-ParkSight-Device-Key": self.device_key,
        })
        request = Request(self.api_url + path, headers=headers, **options)
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 401:
                self.token = None
            raise

    def setup_state(self):
        return json.loads(self.call("/request"))

    def send_garage_read(self, event_id, zone, plate):
        return json.loads(self.call("/garage-read", data=json.dumps({
            "id": event_id, "zone": zone, "plate": plate,
        }).encode(), headers={"Content-Type": "application/json"}))

    def publish_debug_preview(self, frame):
        height, width = frame.shape[:2]
        scale = min(1, 640 / max(width, height))
        if scale < 1:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)),
                               interpolation=cv2.INTER_AREA)
        height, width = frame.shape[:2]
        self.call("/debug/preview", method="PUT", data=jpeg_bytes(frame, 70), headers={
            "Content-Type": "image/jpeg", "X-Image-Width": str(width), "X-Image-Height": str(height),
        })

    def publish_debug_report(self, detail, frame, crop, ocr_input, *, manual=False):
        payload = {**detail}
        for name, image in (("frame", frame), ("crop", crop), ("ocr_input", ocr_input)):
            payload[name] = b64encode(jpeg_bytes(image, 82)).decode() if image is not None else None
        path = "/debug/manual-report" if manual else "/debug/report"
        self.call(path, method="PUT", data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"})

    def publish(self, request_id, frame):
        height, width = frame.shape[:2]
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok or jpeg.size > 1024 * 1024:
            raise ValueError("Cannot encode a reference JPEG")
        self.call(f"/snapshot/{request_id}", method="PUT", data=jpeg.tobytes(), headers={
            "Content-Type": "image/jpeg", "X-Image-Width": str(width), "X-Image-Height": str(height),
        })


def jpeg_bytes(frame, quality):
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("Cannot encode debug JPEG")
    return jpeg.tobytes()


class CameraSetupBridge:
    def __init__(self, client, log, layout_path):
        self.client = client
        self.log = log
        self.stop_event = Event()
        self.lock = Lock()
        self.request_id = None
        self.frame = None
        self.layout_path = layout_path
        self.stall_sensor = StallSensor(layout_path.with_name("stall-thresholds.json"), log)
        self.stall_available = False
        self.calibration = None
        self.garage_enabled = False
        self.garage_retry_at = 0.0
        self.garage_queue = layout_path.with_name("garage-outbox.sqlite")
        self.debug_requested = False
        self.debug_next_frame = 0.0
        self.debug_frame = None
        self.debug_report = None
        self.debug_sent_report = None
        self.debug_retry_at = 0.0
        self.manual_id = None
        self.manual_taken = None
        self.manual_frames = []
        self.manual_next_frame = 0.0
        self.manual_report = None
        try:
            self.set_calibration(json.loads(layout_path.read_text()), cache=False)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            self.log.warning("Could not load the cached camera layout")

    @classmethod
    def load(cls, path, log):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or data.get("enabled") is not True:
                return None
            names = ("workspace_url", "api_url", "client_id", "client_secret", "device_key")
            if any(not isinstance(data.get(name), str) or not data[name] for name in names):
                raise ValueError("Incomplete camera setup settings")
            return cls(DeviceClient(*(data[name] for name in names)), log,
                       path.parent / ".cache" / "camera-layout.json")
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            log.warning("Camera setup bridge configuration is invalid")
            return None

    def start(self):
        Thread(target=self.run, name="parksight-camera-setup", daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def offer(self, frame):
        # The camera loop owns capture. The worker copies only the first fresh
        # frame after a request appears; all network and encoding work stays off it.
        with self.lock:
            if self.request_id is not None and self.frame is None:
                self.frame = frame.copy()
            if self.debug_requested and monotonic() >= self.debug_next_frame:
                self.debug_frame = frame.copy()
                self.debug_next_frame = monotonic() + 0.5

    def take_manual_burst(self, frame, now, frame_count, interval):
        with self.lock:
            if self.manual_id is None or self.manual_id == self.manual_taken:
                return None
            if now < self.manual_next_frame:
                return None
            self.manual_next_frame = now + interval
            self.manual_frames.append(frame.copy())
            if len(self.manual_frames) < frame_count:
                return None
            frames, self.manual_frames = self.manual_frames, []
            self.manual_taken = self.manual_id
            return self.manual_id, frames

    def offer_debug_report(self, detail, frame, crop, ocr_input, *, manual_id=None):
        height, width = frame.shape[:2]
        report = ({**detail, "id": manual_id or str(uuid4()), "height": height, "width": width},
                  frame, crop, ocr_input)
        with self.lock:
            if manual_id:
                self.manual_report = report
            else:
                self.debug_report = report

    def sync_debug(self):
        if monotonic() < self.debug_retry_at:
            return
        with self.lock:
            frame, self.debug_frame = self.debug_frame, None
            report = self.debug_report
            manual = self.manual_report
        try:
            if manual is not None:
                try:
                    self.client.publish_debug_report(*manual, manual=True)
                except HTTPError as error:
                    if error.code != 409:
                        raise
                with self.lock:
                    if self.manual_report is manual:
                        self.manual_report = None
            if not self.debug_requested:
                return
            if frame is not None:
                self.client.publish_debug_preview(frame)
            if report is not None and report[0]["id"] != self.debug_sent_report:
                self.client.publish_debug_report(*report)
                self.debug_sent_report = report[0]["id"]
        except (URLError, OSError, ValueError, cv2.error):
            self.debug_retry_at = monotonic() + 3
            self.log.warning("Camera debug upload unavailable")

    def regions(self, width, height):
        with self.lock:
            layout = self.calibration
        return detection_regions(layout, width, height)

    def enqueue_garage_read(self, zone, plate):
        if not self.garage_enabled:
            return
        try:
            self.garage_queue.parent.mkdir(parents=True, exist_ok=True)
            os.close(os.open(self.garage_queue, os.O_CREAT | os.O_WRONLY, 0o600))
            with closing(sqlite3.connect(self.garage_queue)) as conn, conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS pending (
                    seq INTEGER PRIMARY KEY, id TEXT NOT NULL, zone TEXT NOT NULL,
                    plate TEXT NOT NULL)""")
                conn.execute("INSERT INTO pending (id, zone, plate) VALUES (?, ?, ?)",
                             (str(uuid4()), zone, plate))
        except (OSError, sqlite3.Error):
            self.log.exception("Could not queue garage read")

    def sync_garage_read(self):
        if not self.garage_enabled or monotonic() < self.garage_retry_at:
            return
        if not self.garage_queue.is_file():
            return
        try:
            with closing(sqlite3.connect(self.garage_queue)) as conn:
                row = conn.execute(
                    "SELECT seq, id, zone, plate FROM pending ORDER BY seq LIMIT 1"
                ).fetchone()
                if row is None:
                    return
                seq, event_id, zone, plate = row
                outcome = self.client.send_garage_read(event_id, zone, plate)["outcome"]
                with conn:
                    conn.execute("DELETE FROM pending WHERE seq = ?", (seq,))
                self.log.info("Garage %s for %s: %s", zone, plate, outcome)
        except (URLError, OSError, sqlite3.Error, ValueError, KeyError):
            self.garage_retry_at = monotonic() + 15
            self.log.warning("Garage update unavailable; queued reads will retry")

    def set_calibration(self, layout, *, cache=True):
        if layout == self.calibration:
            return
        if layout is not None:
            detection_regions(layout, *layout["image_size"])
        with self.lock:
            self.calibration = layout
        if cache:
            try:
                self.layout_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.layout_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(layout))
                temporary.replace(self.layout_path)
            except OSError:
                self.log.warning("Could not cache the camera layout")

    def poll(self):
        state = self.client.setup_state()
        self.stall_available = state.get("stall_available") is True
        self.stall_sensor.update(state.get("stall_sample_id"), state.get("stall_settings"),
                                 state.get("stall_assignment"))
        request_id = UUID(state["id"]) if state["id"] else None
        self.garage_enabled = state.get("garage_enabled") is True
        if "calibration" in state:
            try:
                self.set_calibration(state["calibration"])
            except (ValueError, TypeError, KeyError, OverflowError):
                self.log.warning("Ignoring an invalid camera layout from the API")
        with self.lock:
            manual_id = state.get("manual_id")
            if manual_id != self.manual_id:
                self.manual_id = manual_id
                self.manual_frames = []
                self.manual_next_frame = 0.0
            self.debug_requested = state.get("debug_requested") is True
            if not self.debug_requested:
                self.debug_frame = None
            if request_id != self.request_id:
                self.request_id = request_id
                self.frame = None
            frame = self.frame
        if frame is None:
            return
        self.client.publish(request_id, frame)
        with self.lock:
            self.request_id = None
            self.frame = None

    def run(self):
        wait = 1
        while not self.stop_event.is_set():
            try:
                self.poll()
                self.sync_garage_read()
                self.sync_debug()
                if self.stall_available:
                    self.stall_sensor.sync(self.client)
                wait = 0.5 if self.debug_requested else 1
            except (URLError, OSError, ValueError, KeyError, TypeError, cv2.error) as error:
                if wait != 5:
                    self.log.warning("Camera setup API unavailable (%s)", type(error).__name__)
                with self.lock:
                    self.debug_requested = False
                    self.debug_frame = None
                wait = 5
            self.stop_event.wait(wait)
