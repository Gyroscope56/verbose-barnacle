"""Capture distance samples and apply saved thresholds through the MCU bridge."""

import json
from statistics import median
from threading import Lock
from time import monotonic
from urllib.error import HTTPError


class StallSensor:
    def __init__(self, cache, log):
        self.cache = cache
        self.log = log
        self.lock = Lock()
        self.settings = None
        self.applied = None
        self.sent_revision = None
        self.verify_at = 0.0
        self.sample_id = None
        self.samples = []
        self.result = None
        try:
            self.settings = json.loads(cache.read_text())
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("Could not read saved stall thresholds")

    def update(self, sample_id, settings):
        with self.lock:
            if self.sample_id != sample_id:
                self.sample_id = sample_id
                self.samples = []
                self.result = None
            if settings is not None:
                self.settings = settings

    def tick(self, read_mm, configure):
        with self.lock:
            settings = self.settings
            sample_id = self.sample_id if len(self.samples) < 5 else None
        now = monotonic()
        if settings and (self.applied != settings["revision"] or now >= self.verify_at):
            if configure(settings["occupied_below_mm"], settings["clear_above_mm"]):
                with self.lock:
                    previous = self.applied
                    self.applied = settings["revision"]
                    self.verify_at = now + 30
                if previous != self.applied:
                    try:
                        self.cache.parent.mkdir(parents=True, exist_ok=True)
                        temp = self.cache.with_suffix(".tmp")
                        temp.write_text(json.dumps(settings))
                        temp.replace(self.cache)
                    except OSError:
                        self.log.warning("Could not cache stall thresholds")
                    self.log.info("Applied stall thresholds: below %d mm occupied, above %d mm clear",
                                  settings["occupied_below_mm"], settings["clear_above_mm"])
        if sample_id is not None:
            reading = read_mm()
            with self.lock:
                if self.sample_id != sample_id:
                    return
                self.samples.append(reading)
                if len(self.samples) == 5:
                    valid = [mm for mm in self.samples if 1 <= mm <= 1200]
                    distance, error = None, None
                    if len(valid) < 4:
                        error = "insufficient"
                    elif max(valid) - min(valid) > 60:
                        error = "unstable"
                    else:
                        distance = round(median(valid))
                    self.result = (sample_id, {"distance_mm": distance, "error": error})

    def sync(self, client):
        with self.lock:
            result, revision = self.result, self.applied
        if result is not None:
            sample_id, payload = result
            try:
                client.call(f"/stall/sample/{sample_id}", method="PUT",
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json"})
            except HTTPError as error:
                if error.code != 409:
                    raise
            with self.lock:
                if self.result is result:
                    self.result = None
        if revision is not None and revision != self.sent_revision:
            client.call(f"/stall/applied/{revision}", method="PUT")
            self.sent_revision = revision
