# Future camera setup and entry/exit zones

After mounting the camera, the operator opens **Camera setup** and clicks **Capture reference frame**. The app returns one current frame from the camera loop. The camera loop owns the device, so this action does not start a second capture process. An unavailable or stale frame shows a retry prompt.

On the reference image, the operator draws or adjusts a divider and two rectangular detection zones, one labeled **Entry** and one labeled **Exit**. The editor supports dragging, resizing, resetting, and saving. It shows the captured aspect ratio and overlays on a preview so the operator can check the placement before saving. Coordinates are normalized to the captured image, with a configuration version and capture aspect ratio. Resize and orientation changes on the client do not shift the zones. A changed camera mount or a different capture aspect ratio requires a new reference.

The divider is an oriented line, with an arrow preview showing which crossing direction counts as entry. Entry and exit zones constrain where the app looks for candidate plates. In the eventual automatic flow, it tracks the same plate across the line, ignores jitter close to the line, and requires a confirmed read and a sustained direction before emitting a crossing event. A plate visible in one zone alone does not establish direction. Occupancy continues to come from the separate distance sensor.

The setup preview initially records tentative crossing events for review. Before connecting it to Lakebase mutations, decide how to identify and deduplicate a vehicle crossing across retries, restarts, or a momentary obstruction. Keep explicit garage actions available for corrections. Event direction, agreement, and duplicate behavior should be proven with saved bursts before enabling automatic updates.

Test the editor on a phone and desktop, restore a saved layout after restart, and replay both travel directions, a stationary plate, a backing vehicle, and a plate that disappears at the line. The dashboard and camera must remain usable if a setup capture fails.
