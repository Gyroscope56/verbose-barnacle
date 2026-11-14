import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from parksight.generate import crop_plate
from parksight.ocr import decode_ctc, load_recognizer, preprocess
from parksight.train import select_device


class Pipeline:
    def __init__(self, detector: Path, ocr: Path, device="auto", detector_size=640, threshold=0.25):
        if not 0 < threshold < 1:
            raise ValueError("Detection threshold must be between zero and one")
        if detector_size < 160 or detector_size % 32:
            raise ValueError("Detector size must be >=160 and divisible by 32")
        if not detector.is_file() or not ocr.is_file():
            raise FileNotFoundError("Detector and OCR checkpoint files must exist")
        os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(".cache/ultralytics").resolve()))
        from ultralytics import YOLO

        self.device = select_device(device)
        self.detector = YOLO(str(detector))
        self.recognizer = load_recognizer(ocr, self.device)
        self.detector_size = detector_size
        self.threshold = threshold
        self.detector_path, self.ocr_path = detector, ocr

    @torch.inference_mode()
    def recognize(self, images: list[Image.Image]):
        tensor = torch.stack([preprocess(image) for image in images]).to(self.device)
        return decode_ctc(self.recognizer(tensor))

    @torch.inference_mode()
    def predict(self, image: Image.Image) -> list[dict]:
        result = self.detector.predict(
            source=np.array(image.convert("RGB"))[:, :, ::-1],
            imgsz=self.detector_size,
            conf=self.threshold,
            device=0 if self.device == "cuda" else self.device,
            max_det=1,
            verbose=False,
        )[0]
        if not len(result.boxes):
            return []
        box = result.boxes.xyxy[0].cpu().tolist()
        box = [
            max(0.0, box[0]),
            max(0.0, box[1]),
            min(float(image.width), box[2]),
            min(float(image.height), box[3]),
        ]
        if box[0] >= box[2] or box[1] >= box[3]:
            return []
        text, score = self.recognize([crop_plate(image, box)])[0]
        return [
            {
                "text": text,
                "bbox": box,
                "detector_score": float(result.boxes.conf[0].cpu()),
                "ocr_score": score,
            }
        ]

    def synchronize(self):
        if self.device == "mps":
            torch.mps.synchronize()
        elif self.device == "cuda":
            torch.cuda.synchronize()
