# Camera setup and garage updates

Open **Camera calibration** after mounting the camera. Click **Capture reference frame** and draw separate entry and exit boxes where plates are visible in the corresponding lanes. Save the layout. The UNO Q uses the boxes to limit motion and plate detection, and it falls back to the default search area if the camera image aspect ratio changes.

With garage updates enabled, a confirmed entry-zone read admits an existing booking. An exit-zone read closes and archives a visit that is already inside. Check the board logs for the garage outcome. Keep the boxes clear of the opposite lane, since the zone determines the action. The distance sensor remains a separate source of occupancy.

Recheck the layout after moving the camera. Verify each lane with a booked test vehicle before relying on automatic garage updates.
