import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from parksight.generate import crop_plate
from parksight.records import file_hash, read_records, write_json


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return intersection / max(1e-9, area_a + area_b - intersection)


def summarize_predictions(rows: list[dict], predictions: list[list[dict]]) -> dict:
    if not rows or len(rows) != len(predictions):
        raise ValueError("Evaluation needs nonempty, aligned records and predictions")
    positives = negatives = correct = matched = false_positives = errors = characters = 0
    for row, detected in zip(rows, predictions):
        if not row["text"]:
            negatives += 1
            false_positives += bool(detected)
            continue
        positives += 1
        characters += len(row["text"])
        match = next((p for p in detected if iou(p["bbox"], row["bbox"]) >= 0.5), None)
        predicted = match["text"] if match else ""
        matched += match is not None
        correct += bool(match and predicted == row["text"])
        errors += edit_distance(row["text"], predicted)
    return {
        "positive_scenes": positives,
        "negative_scenes": negatives,
        "end_to_end_exact_accuracy": correct / positives if positives else None,
        "end_to_end_character_error_rate": errors / characters if characters else None,
        "matched_detection_recall_iou50": matched / positives if positives else None,
        "negative_false_positive_rate": false_positives / negatives if negatives else None,
    }


def validate_real_rows(rows: list[dict], root: Path):
    if not rows:
        raise ValueError("Real evaluation manifest is empty")
    for row in rows:
        text = row.get("text")
        if text is None or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in text):
            raise ValueError(
                "Real text must be uppercase ASCII letters/digits, or empty for negatives"
            )
        with Image.open(root / row["image"]) as image:
            image.verify()
        if text:
            box = row.get("bbox")
            if not box or len(box) != 4:
                raise ValueError("Positive real images require a pixel bbox")
            with Image.open(root / row["image"]) as image:
                if not (
                    0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height
                ):
                    raise ValueError("Real bbox is outside image")


def prediction_sheet(rows, predictions, root, destination):
    ranked = sorted(
        zip(rows, predictions),
        key=lambda pair: bool(pair[1] and pair[1][0]["text"] == pair[0]["text"]),
    )
    chosen = ranked[:24]
    sheet = Image.new("RGB", (1280, ((len(chosen) + 3) // 4) * 270), "white")
    for index, (row, predicted) in enumerate(chosen):
        with Image.open(root / row["image"]) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        if row.get("bbox"):
            draw.rectangle(row["bbox"], outline="lime", width=2)
        for detection in predicted:
            draw.rectangle(detection["bbox"], outline="red", width=2)
        x, y = index % 4 * 320, index // 4 * 270
        sheet.paste(ImageOps.pad(image, (320, 240)), (x, y))
        ImageDraw.Draw(sheet).text((x + 3, y + 242), "GT: " + (row["text"] or "NONE"), fill="black")
        ImageDraw.Draw(sheet).text(
            (x + 3, y + 255),
            "Pred: " + (predicted[0]["text"] if predicted else "NO DETECTION"),
            fill="black",
        )
    sheet.save(destination)


def evaluate_dataset(
    pipeline,
    root: Path,
    split: str,
    output: Path,
    real_manifest: Path | None = None,
    latency_samples: int = 50,
):
    if latency_samples < 1:
        raise ValueError("Latency sample count must be positive")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite evaluation {output}")
    if real_manifest:
        rows = read_records(real_manifest)
        root = real_manifest.parent
        validate_real_rows(rows, root)
    else:
        if (root / "INCOMPLETE").exists():
            raise ValueError("Dataset generation incomplete")
        rows = [r for r in read_records(root / "scenes.jsonl") if r["split"] == split]
        if not rows:
            raise ValueError(f"No scenes in {split}")
    output.mkdir(parents=True)
    (output / "INCOMPLETE").touch()
    predictions, crop_truths, crop_predictions = [], [], []
    for index, row in enumerate(rows):
        with Image.open(root / row["image"]) as source:
            image = source.convert("RGB")
        predictions.append(pipeline.predict(image))
        if row["text"]:
            crop = crop_plate(image, row["bbox"])
            crop_predictions.append(pipeline.recognize([crop])[0][0])
            crop_truths.append(row["text"])
        if (index + 1) % 100 == 0:
            print(f"Evaluated {index + 1}/{len(rows)} scenes", flush=True)
    metrics = summarize_predictions(rows, predictions)
    metrics["domain"] = "real_camera" if real_manifest else "synthetic"
    metrics["split"] = split
    metrics["ground_truth_crop_ocr"] = {
        "count": len(crop_truths),
        "exact_accuracy": sum(a == b for a, b in zip(crop_truths, crop_predictions))
        / len(crop_truths)
        if crop_truths
        else None,
        "character_error_rate": sum(
            edit_distance(a, b) for a, b in zip(crop_truths, crop_predictions)
        )
        / sum(map(len, crop_truths))
        if crop_truths
        else None,
    }
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        for key in ("style", "scene", "difficulty"):
            if key in row:
                groups[f"{key}/{row[key]}"].append(index)
        if row.get("bbox"):
            width = row["bbox"][2] - row["bbox"][0]
            groups[
                "plate_width/"
                + ("under_100" if width < 100 else "100_to_199" if width < 200 else "200_plus")
            ].append(index)
    metrics["breakdowns"] = {
        key: summarize_predictions([rows[i] for i in ids], [predictions[i] for i in ids])
        for key, ids in groups.items()
    }
    latency_images = []
    for row in rows[:latency_samples]:
        with Image.open(root / row["image"]) as image:
            latency_images.append(image.convert("RGB"))
    for _ in range(5):
        pipeline.predict(latency_images[0])
    pipeline.synchronize()
    timings = []
    for image in latency_images:
        pipeline.synchronize()
        start = time.perf_counter()
        pipeline.predict(image)
        pipeline.synchronize()
        timings.append((time.perf_counter() - start) * 1000)
    metrics["latency"] = {
        "median_ms": float(np.median(timings)),
        "p95_ms": float(np.percentile(timings, 95)),
        "device": pipeline.device,
        "detector_size": pipeline.detector_size,
        "input_sizes": sorted({image.size for image in latency_images}),
        "samples": len(timings),
        "warmup": 5,
        "disk_io_included": False,
        "batch_size": 1,
        "pre_and_postprocessing_included": True,
    }
    if not real_manifest:
        detection = pipeline.detector.val(
            data=str((root / "dataset.yaml").resolve()),
            split=split,
            imgsz=pipeline.detector_size,
            device=0 if pipeline.device == "cuda" else pipeline.device,
            project=str(output.resolve()),
            name="detector",
            plots=False,
            verbose=False,
            workers=0,
        )
        metrics["detector"] = {
            "precision": float(detection.box.mp),
            "recall": float(detection.box.mr),
            "map50": float(detection.box.map50),
            "map50_95": float(detection.box.map),
        }
        metrics["photographic_backgrounds"] = json.loads((root / "manifest.json").read_text())[
            "photographic_backgrounds"
        ]
    metrics["models"] = {
        "detector_sha256": file_hash(pipeline.detector_path),
        "ocr_sha256": file_hash(pipeline.ocr_path),
    }
    metrics["detection_threshold"] = pipeline.threshold
    metrics["ocr_score_note"] = (
        "Geometric mean of emitted-character maximum probabilities; uncalibrated."
    )
    write_json(output / "metrics.json", metrics)
    with (output / "predictions.jsonl").open("w") as stream:
        for row, predicted in zip(rows, predictions):
            stream.write(
                json.dumps({"image": row["image"], "truth": row["text"], "predictions": predicted})
                + "\n"
            )
    prediction_sheet(rows, predictions, root, output / "predictions.jpg")
    (output / "report.md").write_text(
        "# ParkSight baseline evaluation\n\n"
        + f"Domain: {metrics['domain']}. Device: {pipeline.device}.\n\n"
        + "Synthetic results do not establish real-camera accuracy. UNO Q performance is unverified.\n\n"
        + "```json\n"
        + json.dumps(metrics, indent=2)
        + "\n```\n"
    )
    (output / "INCOMPLETE").unlink()
    return metrics
