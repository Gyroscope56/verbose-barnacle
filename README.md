# ParkSight

Intelligent parking management for MadHacks using Arduino UNO Q, local license plate recognition, occupancy sensors, and Databricks analytics.

## Machine learning

The [synthetic LPR package](ml/lpr/README.md) generates annotated U.S.-style plate images, trains a plate detector and compact text recognizer, and reports validation/test accuracy and inference latency.

Source and tests are versioned; datasets, weights, and local run artifacts stay outside Git.
