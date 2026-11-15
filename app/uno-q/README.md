# ParkSight on Arduino UNO Q

The App Lab app uses the Brio camera for 720p plate recognition and the Modulino Distance sketch for stall occupancy. It confirms a plate only when four of a six-frame burst agree. The dashboard at port 5001 includes the latest recognition report and an offline issuing-state guess.

## Run on the board

1. Copy this directory to the UNO Q's `~/ArduinoApps/parksight-camera-starter/`. Preserve the `python`, `sketch`, and `models` layout.
2. Install the exact model pair listed in `models/metadata.json`. Copy the known-good ParkSight detector from the deployed board or a verified bundle. The OCR source and attribution are in `models/ocr-NOTICE.txt`. Compare both file hashes against the manifest before starting.
3. Provide the UNO Q Linux aarch64 Python 3.13 ONNX Runtime and its dependency wheels in `python-libraries/` for offline use. OpenCV and NumPy are provided by the App Lab image. If migrating an existing installation, reuse its working virtual environment and wheel cache.
4. For an offline dashboard, run `sudo bash setup/install-hotspot.sh` on the board and choose a hotspot password when prompted. Join `ParkSight-UNOQ` from a client and open `http://10.42.0.1:5001/`. The script persists the hotspot through NetworkManager and disables autoconnect on other Wi-Fi profiles after successful activation. Use `setup/remove-hotspot.sh` to reverse it.
5. For webcam use, connect the Brio to a powered USB-C hub on the UNO Q before startup. The board's USB-C port connects to the hub for camera operation or to the Mac for USB ADB access.
6. Start the app from App Lab or run `TMPDIR=/tmp arduino-app-cli app start user:parksight-camera-starter` on the board. Set it as the default app to enable startup on boot.

Dashboard and debug images are served over local HTTP. Use the dashboard on a trusted network. The offline app does not require a cloud connection. The board's clock supplies report timestamps.
