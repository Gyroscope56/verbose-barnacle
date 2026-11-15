"""Read the dominant dark character row of a plate with English PP-OCRv4."""

import math
import re

import cv2
import numpy as np


def normalize_plate(text):
    if not text:
        return None
    normalized = re.sub(r"[\s-]", "", text.upper())
    return normalized if re.fullmatch(r"[A-Z0-9]{5,8}", normalized) else None


def isolate_line(crop):
    height, width = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    glyphs = [
        (x, y, w, h)
        for x, y, w, h, area in stats[1:]
        if 0.16 * height <= h <= 0.72 * height
        and 0.06 * h <= w <= h
        and area >= 0.09 * w * h
    ]
    best = []
    best_score = 0
    for _, y, _, h in glyphs:
        row = [
            (x2, y2, w2, h2)
            for x2, y2, w2, h2 in glyphs
            if abs(y2 + h2 / 2 - y - h / 2) <= 0.24 * h and 0.72 * h <= h2 <= 1.38 * h
        ]
        score = sum(g[3] for g in row)
        if len(row) >= 4 and score > best_score:
            best, best_score = row, score
    if not best:
        return None
    margin = round(np.median([g[3] for g in best]) * 0.24)
    x1 = max(0, min(x for x, y, w, h in best) - margin)
    y1 = max(0, min(y for x, y, w, h in best) - margin)
    x2 = min(width, max(x + w for x, y, w, h in best) + margin)
    y2 = min(height, max(y + h for x, y, w, h in best) + margin)
    return crop[y1:y2, x1:x2]


class PlateLineRecognizer:
    def __init__(self, session):
        self.session = session
        self.input_name = session.get_inputs()[0].name
        characters = (
            session.get_modelmeta().custom_metadata_map["character"].splitlines()
        )
        self.labels = ("", *characters, " ")

    def recognize(self, crop):
        line = isolate_line(crop)
        if line is None:
            return None, None
        return self.read_text(line)

    def read_text(self, line):
        height, width = line.shape[:2]
        resized_width = math.ceil(48 * width / height)
        resized = cv2.resize(line, (resized_width, 48))
        tensor = np.zeros((1, 3, 48, max(320, resized_width)), dtype=np.float32)
        tensor[0, :, :, :resized_width] = (
            resized.transpose(2, 0, 1).astype(np.float32) / 127.5 - 1
        )
        scores = self.session.run(None, {self.input_name: tensor})[0]
        if (
            scores.ndim != 3
            or scores.shape[0] != 1
            or scores.shape[-1] != len(self.labels)
        ):
            raise ValueError(f"Unexpected PP-OCRv4 output shape: {scores.shape}")
        ids = scores[0].argmax(axis=1)
        text = "".join(
            self.labels[token]
            for i, token in enumerate(ids)
            if token and (i == 0 or token != ids[i - 1])
        )
        canvas = np.full((48, tensor.shape[-1], 3), 128, dtype=np.uint8)
        canvas[:, :resized_width] = resized
        return text or None, canvas
