# ParkSight camera setup in Databricks

The UNO Q still owns the camera. The Databricks frontend requests a reference through `my-web-api`. An opt-in worker on the UNO Q polls that API over HTTPS and returns a fresh JPEG from the existing camera loop. Operators draw a divider and two zones in the frontend and save normalized coordinates through the API. Lakebase stores one reference image and the calibration for the configured camera.

This version saves and previews the layout. It does not use the zones for motion detection or generate garage events.

## Deploy the setup code

1. In a test Lakebase database, review and run [the schema](api/schema.sql). Give the API app access to read, insert and update only the camera setup table for this feature. Configure the Lakebase connection through an app secret or the existing backend's connection configuration.
2. Add `api/camera_setup.py` and `api/install_camera_setup.py` to the existing FastAPI source for `my-web-api`. Install the requirements from `api/requirements.txt` alongside the existing dependencies. Call `install_camera_setup(app)` after creating its FastAPI app. The module adds routes only when `PARKSIGHT_CAMERA_SETUP_DSN`, `PARKSIGHT_CAMERA_OPERATORS`, and `PARKSIGHT_CAMERA_DEVICE_KEY` are present. Optionally set `PARKSIGHT_CAMERA_ID` for the installed camera. Configure the operators as a comma-separated list of identity-provider identifiers from Databricks' `X-Forwarded-User` header. The API trusts that header only behind the Databricks Apps proxy.
3. When connecting the workspace app to GitHub, deploy `app/databricks/frontend` as the source of the Databricks app named `frontend`. It forwards the signed-in operator's Databricks access token server-side to the fixed API origin. Operators need access to both apps. Verify their user authorization scopes against the backend. The frontend has no database credentials and browser requests go to its own origin.
4. Grant a dedicated UNO Q service principal permission to use `my-web-api`. Use a separate random device key for camera upload routes. On the board, copy `camera-setup.example.json` to `camera-setup.json`, set its mode to `0600`, and configure the device OAuth client ID, secret, and matching key. Set `enabled` to `true` and restart. The bridge needs an upstream route alongside the webcam and hotspot. The local dashboard still works when the bridge is disabled or the API is unreachable.

## Verify on the installed camera

In the Databricks frontend, click **Capture reference frame**. Mark the divider, reverse the entry arrow if needed, and draw both zones. Redraw a shape to resize it. Arrow keys move the selected shape when the image overlay has focus. Save and reload the page to verify the positions. If the camera mount moves, take a new reference and recalibrate. A changed capture aspect ratio hides the prior layout and requires a new save.

Test access with an operator and a non-operator before exposing the setup flow. A snapshot request expires after 30 seconds. The API rejects captures for expired or replaced requests and saves only against its current snapshot. The frontend and API send uncached image responses. The database retains the latest reference image for the configured camera.

See [Databricks Apps proxy headers](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/http-headers) and [API app authentication](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/connect-local) for the two authorization paths.
