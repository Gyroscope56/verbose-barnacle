"""ParkSight operator UI. Browser requests go through my-web-api."""

import os
from urllib.parse import urlsplit
from uuid import UUID

import requests
from flask import Flask, Response, jsonify, request


def create_app(upstream=requests.request):
    app = Flask(__name__, static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    api_url = os.environ.get("PARKSIGHT_API_URL", "").rstrip("/")
    if api_url:
        parsed = urlsplit(api_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".databricksapps.com")
            or parsed.netloc != parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PARKSIGHT_API_URL must be an HTTPS Databricks app origin")

    def forward(path, *, probe=False):
        if not api_url:
            return jsonify(detail="Camera API is not configured"), 503
        token = request.headers.get("X-Forwarded-Access-Token")
        if not token:
            return jsonify(
                detail="Sign in and grant the frontend user authorization"
            ), 401
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if request.method in {"POST", "PUT"}:
            if request.headers.get("X-ParkSight-Setup") != "1":
                return jsonify(
                    detail="Use the camera setup controls to make changes"
                ), 403
            headers["X-ParkSight-Setup"] = "1"
        try:
            response = upstream(
                request.method,
                api_url + path,
                headers=headers,
                data=request.get_data(),
                timeout=8,
                allow_redirects=False,
            )
        except requests.RequestException:
            return jsonify(detail="Camera API is unavailable"), 502
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        if probe:
            connected = (
                response.status_code == 200 and content_type == "application/json"
            )
            return jsonify(
                status="connected" if connected else "unavailable",
                upstream_status=response.status_code,
            ), 200 if connected else 502
        if response.is_redirect or content_type not in {
            "application/json",
            "image/jpeg",
        }:
            return jsonify(
                detail="Camera API did not return an authorized response"
            ), 502
        return Response(
            response.content,
            status=response.status_code,
            mimetype=content_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/")
    def home():
        return app.send_static_file("index.html")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/debug")
    def debug_page():
        access = forward("/api/camera-setup/debug/access")
        if isinstance(access, tuple) or access.status_code != 200:
            return access
        page = app.send_static_file("debug.html")
        page.headers["Cache-Control"] = "no-store"
        return page

    @app.post("/api/debug/view")
    def debug_view():
        return forward("/api/camera-setup/debug/view")

    @app.get("/api/debug/report")
    def debug_report():
        return forward("/api/camera-setup/debug/report")

    @app.post("/api/debug/run")
    def run_models():
        return forward("/api/camera-setup/debug/run")

    @app.get("/api/debug/run/<uuid:request_id>")
    def manual_result(request_id):
        return forward(f"/api/camera-setup/debug/run/{request_id}")

    @app.get("/api-check")
    def api_check():
        return forward("/", probe=True)

    @app.get("/api/camera-setup")
    def status():
        return forward("/api/camera-setup")

    @app.post("/api/camera-setup/capture")
    def capture():
        return forward("/api/camera-setup/capture")

    @app.get("/api/camera-setup/snapshot/<uuid:snapshot_id>")
    def snapshot(snapshot_id: UUID):
        return forward(f"/api/camera-setup/snapshot/{snapshot_id}")

    @app.put("/api/camera-setup/calibration")
    def save():
        return forward("/api/camera-setup/calibration")

    return app


app = create_app()
