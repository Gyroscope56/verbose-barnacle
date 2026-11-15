"""ParkSight UNO Q: resilient camera, local dashboard, detector + OCR pipeline.

Keep this file at <app>/python/main.py alongside log_dashboard.py.
The models live at <app>/models/{detector,ocr}.onnx.
ONNX inference is optional until onnxruntime is installed in the App Lab environment.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import logging
import time
from time import monotonic

import cv2
import numpy as np
from arduino.app_utils import App, Bridge
from log_dashboard import LiveLogStore, configure_logging, start_web_server
from plate_crop import crop_quality, straighten_plate
from plate_line_ocr import PlateLineRecognizer, normalize_plate
from plate_state import guess_plate_state
from recognition_debug import save_debug_report

try:
    from arduino.app_utils import AppError
except ImportError:
    AppError = RuntimeError

try:
    from arduino.app_peripherals.camera import Camera
except ModuleNotFoundError as exc:
    if exc.name != "arduino.app_peripherals.camera":
        raise
    from arduino.app_peripherals.usb_camera import USBCamera

    class Camera:
        def __init__(self, source, **options):
            self.camera = USBCamera(camera=int(source.removeprefix("usb:")), **options)

        def __enter__(self):
            self.camera.start()
            return self

        def __exit__(self, *exc):
            self.camera.stop()

        def capture(self):
            image = self.camera.capture()
            if image is None:
                return None
            return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


CAMERA_SOURCE = "usb:0"
CAMERA_RESOLUTION = (1280, 720)
CAMERA_FPS = 15
MOTION_ROI = (0.15, 0.25, 0.85, 0.90)
MOTION_INTERVAL = 0.2
FOREGROUND_FRACTION = 0.05
WARMUP_SECONDS = 2.0
QUIET_SECONDS = 1.0
BURST_FRAMES = 6
CAMERA_RETRY_SECONDS = 10
BRIDGE_ERRORS = (AppError, RuntimeError, ConnectionError, TimeoutError, ValueError)

STORE = LiveLogStore()
LOG = configure_logging(STORE)
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
DEBUG_REPORT = MODEL_DIR.parent / ".cache" / "recognition-debug.html"
DETECTOR_THRESHOLD = 0.35

_detector = None
_ocr = None
_models_failed = False


def get_models():
    """Load models once, in the OCR worker; never crash the camera if unavailable."""
    global _detector, _ocr, _models_failed
    if _models_failed:
        return None
    if _detector is not None and _ocr is not None:
        return _detector, _ocr
    try:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        _detector = ort.InferenceSession(
            str(MODEL_DIR / "detector.onnx"), sess_options=so,
            providers=["CPUExecutionProvider"])
        session = ort.InferenceSession(
            str(MODEL_DIR / "ocr.onnx"), sess_options=so,
            providers=["CPUExecutionProvider"])
        LOG.info("Loaded ONNX detector and OCR; provider: %s", _detector.get_providers())
        LOG.info("Detector output shape: %s", [_o.shape for _o in _detector.get_outputs()])
        _ocr = PlateLineRecognizer(session)
        LOG.info("Loaded English PP-OCRv4 plate-line recognizer")
        return _detector, _ocr
    except Exception:
        _models_failed = True
        LOG.exception("ONNX models unavailable; motion detection and dashboard will continue")
        return None


def detect_plate(frame, session):
    """Return the selected XYWH box and score, or the best raw score on a miss."""
    height, width = frame.shape[:2]
    side = 320
    scale = min(side / width, side / height)
    nw, nh = round(width * scale), round(height * scale)
    left = (side - nw) // 2
    top = (side - nh) // 2
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (nw, nh))
    canvas = np.full((side, side, 3), 114, dtype=np.uint8)
    canvas[top:top + nh, left:left + nw] = resized
    tensor = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    output = np.asarray(session.run(None, {session.get_inputs()[0].name: tensor})[0])
    pred = output.squeeze()
    if pred.ndim != 2:
        raise ValueError(f"Unexpected detector output shape: {output.shape}")
    if pred.shape[0] == 5 and pred.shape[1] != 5:
        pred = pred.T  # (5, anchors) -> (anchors, 5)
    if pred.shape[1] != 5:
        raise ValueError(f"Expected YOLO11 [x,y,w,h,score], got {output.shape}")

    scores = pred[:, 4]
    best_score = float(np.max(scores)) if scores.size else None
    candidate_indices = np.flatnonzero(scores >= DETECTOR_THRESHOLD)
    if candidate_indices.size == 0:
        return None, best_score

    boxes = []
    candidate_scores = []
    for idx in candidate_indices:
        cx, cy, bw, bh = pred[idx, :4]
        x1 = int(np.clip((cx - bw / 2 - left) / scale, 0, width - 1))
        y1 = int(np.clip((cy - bh / 2 - top) / scale, 0, height - 1))
        x2 = int(np.clip((cx + bw / 2 - left) / scale, 0, width))
        y2 = int(np.clip((cy + bh / 2 - top) / scale, 0, height))
        if x2 - x1 >= 12 and y2 - y1 >= 7:
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            candidate_scores.append(float(scores[idx]))
    if not boxes:
        return None, best_score
    keep = cv2.dnn.NMSBoxes(boxes, candidate_scores, DETECTOR_THRESHOLD, 0.45)
    if len(keep) == 0:
        return None, best_score
    idx = max((int(i) for i in np.asarray(keep).flatten()),
              key=lambda i: candidate_scores[i])
    return boxes[idx], candidate_scores[idx]


@dataclass
class FrameRead:
    index: int
    text: str | None
    crop: np.ndarray
    ocr_input: np.ndarray | None
    quality: float


def read_frame(index, frame, box, ocr):
    x, y, w, h = box
    raw = frame[y:y + h, x:x + w]

    def evaluate(method, crop):
        plate, ocr_input = ocr.recognize(crop)
        sharpness, clipped = crop_quality(crop)
        quality = sharpness * (1 - clipped) ** 2
        eligible = normalize_plate(plate)
        result = "no character row found" if ocr_input is None else f"OCR text {plate!r}"
        detail = f"{method}: {result}, sharpness {sharpness:.0f}, highlights clipped {clipped:.0%}"
        return FrameRead(index, eligible, crop, ocr_input, quality), detail

    original, original_detail = evaluate("detector crop", raw)
    # A readable crop near the plate aspect ratio avoids an unnecessary, potentially destructive warp.
    if original.text and w / h >= 1.75:
        return original, original_detail
    straight = straighten_plate(frame, box)
    if straight is None:
        return original, original_detail
    corrected, corrected_detail = evaluate("straightened crop", straight)
    details = f"{original_detail}; {corrected_detail}"
    if original.text and corrected.text and original.text != corrected.text:
        corrected.text = None
        return corrected, details + "; conflicting crops, no vote"
    if original.text and not corrected.text:
        return original, details
    return corrected, details


def recognize_burst(frames):
    STORE.increment("ocr_attempts")
    LOG.info("Recognition triggered on %d frame(s)", len(frames))
    models = get_models()
    if models is None:
        LOG.info("No plate recognized")
        return

    detector, ocr = models
    notes = []
    readings = []
    decision = "No reliable read"
    started = monotonic()
    try:
        for index, frame in enumerate(frames):
            box, score = detect_plate(frame, detector)
            if box is None:
                best = "unavailable" if score is None else f"{score:.3f}"
                notes.append(f"No usable plate box. Best raw detector score {best}.")
                continue
            x, y, w, h = box
            detection = f"Box x={x}, y={y}, width={w}, height={h}. Detector score {score:.3f}."
            if w * h >= 0.90 * frame.shape[0] * frame.shape[1]:
                notes.append(f"{detection} Rejected because the box covers almost the entire frame.")
                continue
            reading, details = read_frame(index, frame, box, ocr)
            readings.append(reading)
            notes.append(f"{detection} {details}.")

        votes = Counter(reading.text for reading in readings if reading.text)
        if votes:
            plate, count = votes.most_common(1)[0]
            if count >= 2 and count > len(frames) / 2:
                readings = [reading for reading in readings if reading.text == plate]
                state = None
                try:
                    best_read = max(readings, key=lambda reading: reading.quality)
                    state = guess_plate_state(best_read.crop, ocr)
                except Exception:
                    LOG.exception("Issuing state OCR failed; keeping the confirmed plate read")
                STORE.increment("plate_reads")
                STORE.set(last_plate=plate, last_plate_state=state)
                decision = (f"Confirmed {plate} on {count} of {len(frames)} frames. "
                            f"Issuing state guess: {state or 'Unknown'}")
        LOG.info("%s", decision)
    except Exception:
        notes.append("Recognition failed. See the application log for the error.")
        LOG.exception("Recognition failed; continuing camera operation")
    finally:
        if frames:
            selected = max(readings, key=lambda reading: reading.quality, default=None)
            index = selected.index if selected else len(frames) - 1
            try:
                save_debug_report(
                    DEBUG_REPORT, frames[index], selected.ocr_input if selected else None,
                    notes, DETECTOR_THRESHOLD, monotonic() - started, decision=decision,
                    frame_number=index + 1, plate_crop=selected.crop if selected else None,
                )
            except (OSError, cv2.error) as exc:
                LOG.warning("Could not save recognition debug report: %s", exc)


def motion_fraction(frame, background):
    height, width = frame.shape[:2]
    left, top, right, bottom = MOTION_ROI
    roi = frame[int(top * height):int(bottom * height),
                int(left * width):int(right * width)]
    small = cv2.resize(roi, (160, 90), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    mask = background.apply(cv2.GaussianBlur(gray, (5, 5), 0))
    return cv2.countNonZero(mask) / mask.size


def poll_stall(last_stall):
    try:
        stall = str(Bridge.call("stall_state", timeout=0.25))
    except BRIDGE_ERRORS:
        stall = "unknown (Bridge unavailable)"
    if stall != last_stall:
        STORE.set(stall=stall)
        LOG.info("Stall: %s", stall)
    return stall


def run_camera(camera, worker):
    background = cv2.createBackgroundSubtractorMOG2(
        history=100, varThreshold=25, detectShadows=False)
    warmup_until = monotonic() + WARMUP_SECONDS
    next_motion_sample = 0.0
    next_stall_poll = 0.0
    last_motion = warmup_until
    last_stall = None
    consecutive_motion = 0
    armed = True
    burst = []
    ocr_job = None
    width, height = CAMERA_RESOLUTION
    LOG.info("Camera loop started (%s, %dx%d @ %d FPS requested)",
             CAMERA_SOURCE, width, height, CAMERA_FPS)
    STORE.set(camera="running")
    try:
        while True:
            frame = camera.capture()
            if frame is None:
                raise RuntimeError("USB camera stopped returning frames")
            now = monotonic()
            if ocr_job is not None and ocr_job.done():
                ocr_job.result()
                ocr_job = None
            if now >= next_stall_poll:
                next_stall_poll = now + 1.0
                last_stall = poll_stall(last_stall)
            if now < next_motion_sample:
                continue
            next_motion_sample = now + MOTION_INTERVAL
            moving = motion_fraction(frame, background) >= FOREGROUND_FRACTION
            if now < warmup_until:
                continue
            if moving:
                last_motion = now
                consecutive_motion += 1
            else:
                consecutive_motion = 0
                if now - last_motion >= QUIET_SECONDS and ocr_job is None:
                    armed = True
            if armed and consecutive_motion >= 2:
                armed = False
                STORE.increment("motion_events")
                LOG.info("Approach-area motion detected; collecting %d frames", BURST_FRAMES)
                burst.append(frame.copy())
                try:
                    Bridge.notify("signal_camera_motion")
                except BRIDGE_ERRORS as exc:
                    LOG.warning("Motion LED unavailable: %s", exc)
            elif burst:
                burst.append(frame.copy())
            if len(burst) == BURST_FRAMES:
                if ocr_job is None:
                    ocr_job = worker.submit(recognize_burst, burst)
                burst = []
    finally:
        STORE.set(camera="waiting for camera")


def run_service():
    """Remain alive and keep the dashboard up even with no webcam attached."""
    last_stall = None
    failures = 0
    with ThreadPoolExecutor(max_workers=1) as worker:
        while True:
            try:
                with Camera(CAMERA_SOURCE, resolution=CAMERA_RESOLUTION, fps=CAMERA_FPS) as camera:
                    failures = 0
                    run_camera(camera, worker)
            except Exception as exc:
                failures += 1
                STORE.set(camera="waiting for camera")
                if failures == 1 or failures % 6 == 0:
                    LOG.warning("Camera unavailable (%s); retrying every %ds. "
                                "Dashboard stays online.", exc, CAMERA_RETRY_SECONDS)
                # Keep polling the MCU sensor while the webcam is unplugged.
                end = monotonic() + CAMERA_RETRY_SECONDS
                while monotonic() < end:
                    last_stall = poll_stall(last_stall)
                    time.sleep(min(1.0, max(0.0, end - monotonic())))


def main():
    try:
        start_web_server(STORE, LOG, debug_report=DEBUG_REPORT)
    except OSError:
        LOG.exception("Could not bind dashboard to port 5001")
    LOG.info("ParkSight starting; Linux NetworkManager manages the Wi-Fi hotspot")
    LOG.info("Models directory: %s", MODEL_DIR)
    get_models()  # Log ONNX Runtime/model readiness at startup without crashing.
    LOG.info("Web dashboard remains available while the camera is disconnected")
    App.run(run_service)


if __name__ == "__main__":
    main()
