"""Optional Lakebase operations for the offline ParkSight dashboard."""

import json
import re
from hmac import compare_digest
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic


class OccupancySync:
    def __init__(self, spot, outbox, write, status, log):
        self.spot = spot
        self.outbox = outbox
        self.write = write
        self.status = status
        self.log = log
        self.lock = Lock()
        self.wake = Event()
        self.stop_requested = Event()
        self.current = None
        self.pending = None
        self.revision = 0
        self.refresh_at = 0.0
        try:
            saved = json.loads(outbox.read_text())
            if saved.get("spot") == spot and saved.get("state") in ("occupied", "clear"):
                self.pending = saved["state"]
        except FileNotFoundError:
            pass
        except (ValueError, OSError, AttributeError):
            log.warning("Could not read the occupancy outbox")
        self.status("Waiting for a known sensor state")

    def start(self):
        self.thread = Thread(target=self.run, name="parksight-lakebase", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_requested.is_set():
            self.wake.wait(5)
            self.wake.clear()
            if not self.stop_requested.is_set():
                self.sync_once()

    def stop(self):
        self.stop_requested.set()
        self.wake.set()

    def observe(self, state):
        known = state if state in ("occupied", "clear") else None
        with self.lock:
            if known == self.current:
                return
            self.current = known
            self.revision += 1
            if known is None:
                self.status("Sensor unavailable")
                return
            if self.pending != known:
                self.pending = known
                self.persist()
            self.status("Pending")
            self.wake.set()

    def persist(self):
        try:
            if self.pending is None:
                self.outbox.unlink(missing_ok=True)
            else:
                self.outbox.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.outbox.with_suffix(".tmp")
                temporary.write_text(json.dumps({"spot": self.spot, "state": self.pending}))
                temporary.replace(self.outbox)
        except OSError:
            self.log.warning("Could not persist the occupancy outbox")

    def sync_once(self):
        with self.lock:
            state, revision = self.current, self.revision
            refresh = state == "occupied" and monotonic() >= self.refresh_at
            if state is None or (self.pending is None and not refresh):
                return
        try:
            self.write(self.spot, state == "occupied")
        except Exception as error:
            with self.lock:
                if revision == self.revision:
                    self.status("Lakebase unavailable or spot not configured")
            self.log.debug("Lakebase occupancy update failed (%s)", type(error).__name__)
            return
        with self.lock:
            if revision == self.revision:
                if self.pending is not None:
                    self.pending = None
                    self.persist()
                self.refresh_at = monotonic() + 30
                self.status(f"Synced ({state})")


class LakebaseIntegration:
    def __init__(self, spot, operator_token, connection, commands, sync, log):
        self.spot = spot
        self.operator_token = operator_token.encode("utf-8")
        self.connection = connection
        self.commands = commands
        self.sync = sync
        self.log = log

    @classmethod
    def load(cls, config_path: Path, outbox: Path, store, log):
        try:
            config = json.loads(config_path.read_text())
            if not isinstance(config, dict):
                raise ValueError("Expected a configuration object")
            if config.get("enabled") is not True:
                return None
            from lakebase_backend.garage import COMMANDS
            from lakebase_backend.lakebase import DatabaseSettings
            from lakebase_backend.spot_updater import update_occupancy

            spot, token = config["spot"], config["operator_token"]
            if not isinstance(spot, str) or not spot.strip():
                raise ValueError("A parking spot is required")
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
                raise ValueError("Use a URL-safe operator token of 16 to 128 characters")
            db = DatabaseSettings(**config["database"])
            if not all(isinstance(value, str) and value for value in (
                db.host, db.password, db.user, db.dbname, db.sslmode
            )):
                raise ValueError("Expected nonempty database settings")
            if type(db.port) is not int or not 1 <= db.port <= 65535:
                raise ValueError("Invalid database port")

            def write(spot, occupied):
                update_occupancy(spot, occupied, connection=db.connect)

            def status(value):
                store.set(lakebase_sync=value)

            sync = OccupancySync(spot, outbox, write, status, log)
            store.set(lakebase_enabled=True, lakebase_spot=spot)
            return cls(spot, token, db.connect, COMMANDS, sync, log)
        except FileNotFoundError:
            return None
        except (ImportError, KeyError, OSError, TypeError, ValueError) as error:
            log.warning("Lakebase integration unavailable (%s); local dashboard is available",
                        type(error).__name__)
            store.set(lakebase_sync="Configuration error")
            return None

    def garage(self, token, action, key):
        if not compare_digest(token.encode("utf-8"), self.operator_token):
            return 403, {"message": "Operator token required."}
        if not isinstance(action, str) or action not in self.commands:
            return 400, {"message": "Unknown garage action."}
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,31}", key):
            return 400, {"message": "Enter the exact Lakebase plate key."}
        try:
            result = self.commands[action](key, connection=self.connection)
        except ValueError as error:
            return 409, {"message": str(error)}
        except Exception as error:
            self.log.warning("Garage %s could not complete (%s)", action, type(error).__name__)
            message = ("Lakebase is unavailable." if action == "check"
                       else "Write outcome unknown. Check the plate before retrying.")
            return 503, {"message": message}
        return 200, {"status": result.status, "message": result.message}
