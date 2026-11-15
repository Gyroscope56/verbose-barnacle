"""Opt-in wiring for the existing FastAPI application."""

import os

import psycopg
from camera_setup import camera_setup_router


def install_camera_setup(app):
    dsn = os.environ.get("PARKSIGHT_CAMERA_SETUP_DSN")
    operators = {
        value.strip().casefold()
        for value in os.environ.get("PARKSIGHT_CAMERA_OPERATORS", "").split(",")
        if value.strip()
    }
    key = os.environ.get("PARKSIGHT_CAMERA_DEVICE_KEY")
    if not dsn or not operators or not key:
        return False

    def connect():
        return psycopg.connect(
            dsn, connect_timeout=4, options="-c statement_timeout=5000"
        )

    app.include_router(
        camera_setup_router(
            connect,
            os.environ.get("PARKSIGHT_CAMERA_ID", "entrance-camera"),
            operators,
            key,
        )
    )
    return True
