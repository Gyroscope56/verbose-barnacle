from contextlib import contextmanager
from http.client import HTTPConnection
import json
import logging
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from app import garage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "uno-q" / "python"))
from garage_sync import LakebaseIntegration, OccupancySync
from log_dashboard import LiveLogStore, start_web_server


LOG = logging.getLogger(__name__)
TOKEN = "test-operator-token"
SPOT = "1-A-01"


class OccupancyTest(unittest.TestCase):
    def test_latest_state_replaces_outage_and_survives_restart(self):
        writes = []
        with TemporaryDirectory() as directory:
            path = Path(directory) / "outbox.json"

            def offline(spot, value):
                raise ConnectionError("offline")

            sync = OccupancySync(SPOT, path, offline, lambda _: None, LOG)
            sync.observe("occupied")
            sync.sync_once()
            self.assertEqual(json.loads(path.read_text())["state"], "occupied")
            sync.observe("unknown")
            sync.observe("clear")
            self.assertEqual(json.loads(path.read_text())["state"], "clear")

            sync = OccupancySync(SPOT, path, lambda *args: writes.append(args), lambda _: None, LOG)
            sync.sync_once()  # Wait for a fresh reading when restarting.
            self.assertEqual(writes, [])
            sync.observe("clear")
            sync.sync_once()
            self.assertEqual(writes, [(SPOT, False)])
            self.assertFalse(path.exists())

    def test_unknown_never_clears_a_spot(self):
        writes = []
        with TemporaryDirectory() as directory:
            sync = OccupancySync(
                SPOT, Path(directory) / "outbox.json",
                lambda *args: writes.append(args), lambda _: None, LOG,
            )
            sync.observe("occupied")
            sync.sync_once()
            sync.observe("unknown (Bridge unavailable)")
            sync.sync_once()
            self.assertEqual(writes, [(SPOT, True)])

    def test_new_observation_survives_an_in_flight_write(self):
        writes = []
        with TemporaryDirectory() as directory:
            path = Path(directory) / "outbox.json"

            def write(spot, value):
                writes.append((spot, value))
                if value:
                    sync.observe("clear")

            sync = OccupancySync(SPOT, path, write, lambda _: None, LOG)
            sync.observe("occupied")
            sync.sync_once()
            self.assertEqual(json.loads(path.read_text())["state"], "clear")
            sync.sync_once()
            self.assertEqual(writes, [(SPOT, True), (SPOT, False)])
            self.assertFalse(path.exists())


class DashboardTest(unittest.TestCase):
    @contextmanager
    def web(self, lakebase=None):
        with TemporaryDirectory() as directory:
            server = start_web_server(
                LiveLogStore(), LOG, "127.0.0.1", 0,
                debug_report=Path(directory) / "debug.html", lakebase=lakebase,
            )
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                yield connection
            finally:
                connection.close()
                server.shutdown()
                server.server_close()

    def request(self, connection, method, path, body=None, *, token=None):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-ParkSight-Token"] = token
        connection.request(method, path, body=body, headers=headers)
        res = connection.getresponse()
        return res.status, res.read()

    def test_offline_health_and_disabled_garage(self):
        with self.web() as client:
            status, body = self.request(client, "GET", "/health")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["ok"])
            status, body = self.request(client, "GET", "/api/logs")
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(body)["status"]["lakebase_enabled"])
            status, _ = self.request(client, "POST", "/api/garage", "{}")
            self.assertEqual(status, 503)

    def test_explicit_authenticated_action_and_exact_key(self):
        calls = []

        def book(key, *, connection):
            calls.append(key)
            return garage.GarageResult("booked", "Booked. May enter.")

        integration = LakebaseIntegration(SPOT, TOKEN, None, {"book": book}, None, LOG)
        with self.web(integration) as client:
            body = json.dumps({"action": "book", "plate_key": "WI-ABC-1234"})
            self.assertEqual(self.request(client, "POST", "/api/garage", body)[0], 403)
            self.assertEqual(calls, [])
            status, payload = self.request(client, "POST", "/api/garage", body, token=TOKEN)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(payload)["status"], "booked")
            self.assertEqual(calls, ["WI-ABC-1234"])
            self.assertEqual(self.request(client, "POST", "/api/garage", "[]", token=TOKEN)[0], 400)
            self.assertEqual(self.request(client, "GET", "/api/garage")[0], 404)

    def test_uncertain_write_is_never_replayed(self):
        calls = []

        def exit_action(key, *, connection):
            calls.append(key)
            raise ConnectionError("simulated disconnect")

        integration = LakebaseIntegration(SPOT, TOKEN, None, {"exit": exit_action}, None, LOG)
        status, body = integration.garage(TOKEN, "exit", "WI-ABC-1234")
        self.assertEqual(status, 503)
        self.assertIn("Check", body["message"])
        self.assertEqual(calls, ["WI-ABC-1234"])


if __name__ == "__main__":
    unittest.main()
