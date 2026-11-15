import importlib.util
import unittest
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.databricks.api.camera_setup import camera_setup_router
from app.databricks.api.garage_events import record_read
from app.databricks.frontend.app import create_app

ROOT = Path(__file__).resolve().parents[3]
BRIDGE = ROOT / "app" / "uno-q" / "python" / "camera_setup_bridge.py"
spec = importlib.util.spec_from_file_location("camera_setup_bridge", BRIDGE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

DB = environ.get("PARKSIGHT_TEST_POSTGRES")
OPERATOR = {"X-Forwarded-User": "operator", "X-ParkSight-Setup": "1"}
DEVICE = {"X-ParkSight-Device-Key": "device-key"}
LAYOUT = {
    "entry": {"x": 0.12, "y": 0.3, "width": 0.3, "height": 0.4},
    "exit": {"x": 0.55, "y": 0.3, "width": 0.3, "height": 0.4},
}


class FrontendTest(unittest.TestCase):
    def test_forward_user_token_without_accepting_browser_identity(self):
        upstream = Mock(
            return_value=SimpleNamespace(
                headers={"Content-Type": "application/json"},
                content=b'{"snapshot":null}',
                status_code=200,
                is_redirect=False,
            )
        )
        with patch.dict(
            environ,
            PARKSIGHT_API_URL="https://my-web-api-example.aws.databricksapps.com",
        ):
            app = create_app(upstream)
        browser = app.test_client()
        with browser.get("/") as home:
            self.assertEqual(home.status_code, 200)
        self.assertEqual(browser.get("/api/camera-setup").status_code, 401)
        self.assertEqual(
            browser.post(
                "/api/camera-setup/capture",
                headers={"X-Forwarded-Access-Token": "test-user-token"},
            ).status_code,
            403,
        )
        upstream.assert_not_called()
        response = browser.post(
            "/api/camera-setup/capture",
            headers={
                "X-Forwarded-Access-Token": "test-user-token",
                "X-Forwarded-User": "ignored",
                "X-ParkSight-Setup": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        args, kwargs = upstream.call_args
        self.assertEqual(
            args,
            (
                "POST",
                "https://my-web-api-example.aws.databricksapps.com/api/camera-setup/capture",
            ),
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-user-token")
        self.assertNotIn("X-Forwarded-User", kwargs["headers"])
        self.assertFalse(kwargs["allow_redirects"])
        probe = browser.get(
            "/api-check", headers={"X-Forwarded-Access-Token": "test-user-token"}
        )
        self.assertEqual(probe.json, {"status": "connected", "upstream_status": 200})
        self.assertEqual(
            upstream.call_args.args[1],
            "https://my-web-api-example.aws.databricksapps.com/",
        )

    def test_snapshot_id_is_validated(self):
        app = create_app(Mock())
        self.assertEqual(
            app.test_client().get("/api/camera-setup/snapshot/not-a-uuid").status_code,
            404,
        )


@unittest.skipUnless(DB, "Set PARKSIGHT_TEST_POSTGRES to a disposable database")
class CaptureTest(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.schema = f"camera_test_{uuid4().hex}"
        with psycopg.connect(DB) as conn:
            conn.execute(f"CREATE SCHEMA {self.schema}")
        self.addCleanup(self.drop_schema)
        with self.connect() as conn:
            conn.execute((ROOT / "app/databricks/api/schema.sql").read_text())
            conn.execute((ROOT / "app/databricks/api/garage_schema.sql").read_text())
            conn.execute("""
                CREATE TABLE g_sessions (
                    license_plate text PRIMARY KEY, has_entrance_ticket boolean NOT NULL,
                    time_in timestamptz, time_out timestamptz
                );
                CREATE TABLE garage_visit_history (
                    license_plate text NOT NULL, has_entrance_ticket boolean NOT NULL,
                    time_in timestamptz NOT NULL, time_out timestamptz NOT NULL
                );
            """)
        self.api = self.start_api()

    def connect(self):
        return self.psycopg.connect(DB, options=f"-c search_path={self.schema}")

    def drop_schema(self):
        with self.psycopg.connect(DB) as conn:
            conn.execute(f"DROP SCHEMA {self.schema} CASCADE")

    def start_api(self):
        app = FastAPI()
        app.include_router(
            camera_setup_router(
                self.connect, "entrance-camera", {"operator"}, "device-key", record_read
            )
        )
        return TestClient(app)

    def publish(self, request_id, frame):
        height, width = frame.shape[:2]
        success, image = cv2.imencode(".jpg", frame)
        self.assertTrue(success)
        return self.api.put(
            f"/api/camera-setup/device/snapshot/{request_id}",
            content=image.tobytes(),
            headers={
                **DEVICE,
                "Content-Type": "image/jpeg",
                "X-Image-Width": str(width),
                "X-Image-Height": str(height),
            },
        )

    def request_capture(self):
        response = self.api.post("/api/camera-setup/capture", headers=OPERATOR)
        self.assertEqual(response.status_code, 202)
        return response.json()["id"]

    def test_full_capture_save_and_restore(self):
        api = self.api
        request_id = self.request_capture()
        testcase = self

        class Device:
            def setup_state(self):
                return api.get(
                    "/api/camera-setup/device/request", headers=DEVICE
                ).json()

            def publish(self, current, frame):
                testcase.assertEqual(str(current), request_id)
                testcase.assertEqual(testcase.publish(current, frame).status_code, 204)

        cache_dir = TemporaryDirectory()
        self.addCleanup(cache_dir.cleanup)
        layout_path = Path(cache_dir.name) / "layout.json"
        bridge = module.CameraSetupBridge(Device(), Mock(), layout_path)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        bridge.offer(frame)  # No snapshot is retained before a request.
        bridge.poll()
        self.assertIsNone(
            api.get("/api/camera-setup", headers=OPERATOR).json()["snapshot"]
        )
        bridge.offer(frame)
        bridge.poll()

        reference = api.get("/api/camera-setup", headers=OPERATOR).json()["snapshot"]
        self.assertEqual(reference, {"id": request_id, "width": 1280, "height": 720})
        image = api.get(f"/api/camera-setup/snapshot/{request_id}", headers=OPERATOR)
        self.assertEqual(image.headers["content-type"], "image/jpeg")
        self.assertEqual(
            cv2.imdecode(
                np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR
            ).shape,
            frame.shape,
        )
        response = api.put(
            "/api/camera-setup/calibration",
            headers=OPERATOR,
            json={**LAYOUT, "reference_id": request_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("divider", response.json())
        bridge.poll()
        self.assertEqual(
            bridge.regions(1280, 720),
            (("entry", (154, 216, 538, 504)), ("exit", (704, 216, 1088, 504))),
        )
        self.assertEqual(bridge.regions(640, 480), ())
        offline = module.CameraSetupBridge(Mock(), Mock(), layout_path)
        self.assertEqual(offline.regions(640, 360), (
            ("entry", (77, 108, 269, 252)), ("exit", (352, 108, 544, 252))
        ))
        restarted = self.start_api()
        self.assertEqual(
            restarted.get("/api/camera-setup", headers=OPERATOR).json()["calibration"],
            response.json(),
        )

        resized_id = self.request_capture()
        self.assertEqual(
            self.publish(resized_id, cv2.resize(frame, (640, 480))).status_code, 204
        )
        self.assertIsNone(
            restarted.get("/api/camera-setup", headers=OPERATOR).json()["calibration"]
        )
        bridge.poll()
        self.assertEqual(bridge.regions(1280, 720), ())
        self.assertEqual(
            api.put(
                "/api/camera-setup/calibration",
                headers=OPERATOR,
                json={**LAYOUT, "reference_id": request_id},
            ).status_code,
            409,
        )

    def test_access_and_stale_or_invalid_capture(self):
        self.assertEqual(self.api.get("/api/camera-setup").status_code, 403)
        self.assertEqual(
            self.api.get("/api/camera-setup/device/request").status_code, 403
        )
        self.assertEqual(
            self.api.post(
                "/api/camera-setup/capture", headers={"X-Forwarded-User": "operator"}
            ).status_code,
            403,
        )
        expired = self.request_capture()
        active = self.request_capture()
        frame = np.zeros((16, 16, 3), np.uint8)
        self.assertEqual(self.publish(expired, frame).status_code, 409)
        bad_jpeg = self.api.put(
            f"/api/camera-setup/device/snapshot/{active}",
            content=b"invalid",
            headers={
                **DEVICE,
                "Content-Type": "image/jpeg",
                "X-Image-Width": "16",
                "X-Image-Height": "16",
            },
        )
        self.assertEqual(bad_jpeg.status_code, 400)
        self.assertEqual(self.publish(active, frame).status_code, 204)
        self.assertEqual(self.publish(active, frame).status_code, 409)
        invalid = {
            **LAYOUT,
            "reference_id": active,
            "entry": {"x": 0.8, "y": 0.5, "width": 0.5, "height": 0.2},
        }
        self.assertEqual(
            self.api.put(
                "/api/camera-setup/calibration", headers=OPERATOR, json=invalid
            ).status_code,
            422,
        )

    def test_zone_reads_update_existing_booking_once(self):
        path = "/api/camera-setup/device/garage-read"
        entry = {"id": str(uuid4()), "zone": "entry", "plate": "ABC1234"}
        self.assertEqual(self.api.post(path, json=entry).status_code, 403)
        self.assertEqual(self.api.post(path, json=entry, headers=DEVICE).json(),
                         {"outcome": "unbooked"})

        with self.connect() as conn:
            conn.execute("INSERT INTO g_sessions VALUES ('WI-ABC-1234', TRUE, NULL, NULL)")
        self.assertEqual(self.api.post(path, json=entry, headers=DEVICE).json(),
                         {"outcome": "unbooked"})
        entry["id"] = str(uuid4())
        self.assertEqual(self.api.post(path, json=entry, headers=DEVICE).json(),
                         {"outcome": "inside"})
        self.assertEqual(self.api.post(path, json=entry, headers=DEVICE).json(),
                         {"outcome": "inside"})
        exit_read = {**entry, "id": str(uuid4()), "zone": "exit"}
        for _ in range(2):
            self.assertEqual(self.api.post(path, json=exit_read, headers=DEVICE).json(),
                             {"outcome": "exited"})
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM g_sessions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM garage_visit_history").fetchone()[0], 1)
            conn.execute("""INSERT INTO g_sessions VALUES
                            ('IL-ABC-1234', TRUE, NULL, NULL), ('WI-ABC-1234', TRUE, NULL, NULL)""")
        entry["id"] = str(uuid4())
        self.assertEqual(self.api.post(path, json=entry, headers=DEVICE).json(),
                         {"outcome": "ambiguous"})

    def test_queue_retries_with_same_event_id_after_restart(self):
        with TemporaryDirectory() as directory:
            layout_path = Path(directory) / "layout.json"
            client = Mock()
            bridge = module.CameraSetupBridge(client, Mock(), layout_path)
            bridge.garage_enabled = True
            bridge.enqueue_garage_read("entry", "ABC1234")
            client.send_garage_read.side_effect = OSError
            bridge.sync_garage_read()
            args = client.send_garage_read.call_args.args

            restarted = module.CameraSetupBridge(client, Mock(), layout_path)
            restarted.garage_enabled = True
            client.send_garage_read.side_effect = None
            client.send_garage_read.return_value = {"outcome": "inside"}
            restarted.sync_garage_read()
            client.send_garage_read.assert_called_with(*args)
            client.send_garage_read.reset_mock()
            restarted.sync_garage_read()
            client.send_garage_read.assert_not_called()
