# ParkSight on Arduino UNO Q

The App Lab app uses the Brio camera for 720p plate recognition and the Modulino Distance sketch for stall occupancy. It confirms a plate only when four of a six-frame burst agree. Application logs include the latest OCR result and issuing-state guess.

## Run on the board

1. Copy this directory to the UNO Q's `~/ArduinoApps/parksight-camera-starter/`. Preserve the `python`, `sketch`, and `models` layout.
2. Install the exact model pair listed in `models/metadata.json`. Copy the known-good ParkSight detector from the deployed board or a verified bundle. The OCR source and attribution are in `models/ocr-NOTICE.txt`. Compare both file hashes against the manifest before starting.
3. Provide the UNO Q Linux aarch64 Python 3.13 ONNX Runtime and its dependency wheels in `python-libraries/` for offline use. OpenCV and NumPy are provided by the App Lab image. If migrating an existing installation, reuse its working virtual environment and wheel cache.
4. Use an internet-connected Wi-Fi or Ethernet network to reach Databricks.
5. For webcam use, connect the Brio to a powered USB-C hub on the UNO Q before startup. The board's USB-C port connects to the hub for camera operation or to the Mac for USB ADB access.
6. Start the app from App Lab or run `TMPDIR=/tmp arduino-app-cli app start user:parksight-camera-starter` on the board. Set it as the default app to enable startup on boot.

Use `docker logs parksight-camera-starter-main-1` for runtime status. The latest recognition report is stored in `.cache/recognition-debug.html` in the app directory and can be copied over ADB or SSH. Its timestamps come from the board clock. Camera and sensor processing can run offline.

## Connect garage and occupancy to Lakebase

1. On the development computer, run `bash app/uno-q/setup/bundle-lakebase.sh` from the repository root. It copies the shared CLI backend into the App Lab package. Pass the path to a staging app directory to bundle there instead.
2. Download the Lakebase driver wheels on an internet-connected computer. From the repo root, run:

   ```sh
   python3 -m pip download --only-binary=:all: \
     --platform manylinux_2_28_aarch64 --platform manylinux2014_aarch64 \
     --python-version 3.13 --implementation cp --abi cp313 \
     -r app/uno-q/lakebase-requirements.txt -d app/uno-q/python-libraries
   ```

   Transfer the prepared app and wheels together. Leave ONNX Runtime's existing files in place.
3. On the board, copy `lakebase.example.json` to `lakebase.json`, set its mode to `0600`, and fill in a reserved spot ID, a URL-safe operator token, and test database details. Verify the container can reach Lakebase over the upstream network before setting `enabled` to `true` and restarting. An isolated hotspot has no Lakebase route on its own.
4. Known sensor states sync to the configured spot in the background. Only the latest pending state is kept during an outage, and the worker waits for a fresh known reading on restart. An unavailable sensor leaves the database's occupancy unchanged. An occupied spot refreshes its duration about every 30 seconds while connected. The database clock records the time a state is applied.

The test schema expects a unique value in `g_sessions.license_plate` and one `parking_spots` row per `floor_zone_number`. Verify those constraints and the canonical plate-key format on the intended Lakebase database before enabling writes. The integration does not alter the schema.

Run local checks from the repository root with `python -m unittest discover -s app/tests -v`. Supply `PARKSIGHT_TEST_POSTGRES` for the tests that create and drop a disposable PostgreSQL schema.

The [camera setup plan](docs/camera-setup-plan.md) covers the future installed-camera snapshot, divider editor, and entry/exit zones.

## Databricks camera setup bridge

The optional outbound snapshot worker serves the [Databricks calibration editor](../databricks/README.md). It is disabled until a local `camera-setup.json` enables it. The camera remains under the existing capture loop, and saved zones are preview-only.
