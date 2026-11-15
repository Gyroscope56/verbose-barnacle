"""One outbound snapshot worker for the Databricks camera setup API."""

import json
from base64 import b64encode
from threading import Event, Lock, Thread
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

import cv2


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

    def pending(self):
        value = json.loads(self.call("/request"))["id"]
        return UUID(value) if value else None

    def publish(self, request_id, frame):
        height, width = frame.shape[:2]
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok or jpeg.size > 1024 * 1024:
            raise ValueError("Cannot encode a reference JPEG")
        self.call(f"/snapshot/{request_id}", method="PUT", data=jpeg.tobytes(), headers={
            "Content-Type": "image/jpeg", "X-Image-Width": str(width), "X-Image-Height": str(height),
        })


class CameraSetupBridge:
    def __init__(self, client, log):
        self.client = client
        self.log = log
        self.stop_event = Event()
        self.lock = Lock()
        self.request_id = None
        self.frame = None

    @classmethod
    def load(cls, path, log):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or data.get("enabled") is not True:
                return None
            names = ("workspace_url", "api_url", "client_id", "client_secret", "device_key")
            if any(not isinstance(data.get(name), str) or not data[name] for name in names):
                raise ValueError("Incomplete camera setup settings")
            return cls(DeviceClient(*(data[name] for name in names)), log)
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

    def poll(self):
        request_id = self.client.pending()
        with self.lock:
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
                wait = 1
            except (URLError, OSError, ValueError, KeyError, TypeError, cv2.error) as error:
                if wait == 1:
                    self.log.warning("Camera setup API unavailable (%s)", type(error).__name__)
                wait = 5
            self.stop_event.wait(wait)
