# ParkSight

Intelligent parking management for MadHacks using Arduino UNO Q, local license plate recognition, occupancy sensors, and Databricks analytics.

## Machine learning

The [synthetic LPR package](ml/lpr/README.md) generates annotated U.S.-style plate images, trains a plate detector and compact text recognizer, and reports validation/test accuracy and inference latency.

Source and tests are versioned; datasets, weights, and local run artifacts stay outside Git.

## Arduino app and garage integration

The [UNO Q app](app/uno-q/README.md) runs the local camera, sensors, and dashboard. It can optionally use the shared garage and parking-space operations in `app/` to update Lakebase.

## Databricks apps

- [Camera setup API and operator front end](app/databricks/README.md): capture a reference frame from the installed camera, draw entry and exit zones, calibrate the stall distance sensor, and inspect live recognition results.
- [Driver app](app/driver/README.md): live parking availability by floor and zone, read from Lakebase.

## How it fits together

1. The UNO Q watches the lane and reads plates on-device, confirming a plate only when 4 of 6 frames agree.
2. The calibrated entry or exit zone decides whether a confirmed read starts or closes a booked visit in Lakebase.
3. A Modulino Distance sensor in each stall reports occupancy once the reading settles.
4. The driver app shows each change as soon as it reaches Lakebase. When the network drops, the board keeps working and retries queued updates with their original event IDs.
