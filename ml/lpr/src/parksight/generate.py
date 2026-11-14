import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageOps

from parksight.assets import font_paths, load_backgrounds
from parksight.config import Config
from parksight.records import file_hash, fingerprint, read_records, write_json
from parksight.render import STYLES, box_from_corners, compose_scene, render_plate

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def split_for(index: int, count: int) -> str:
    return "train" if index < int(count * 0.8) else "val" if index < int(count * 0.9) else "test"


def crop_plate(image: Image.Image, box: list, padding: float = 0.03) -> Image.Image:
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * padding, (y2 - y1) * padding
    clipped = (
        max(0, int(x1 - dx)),
        max(0, int(y1 - dy)),
        min(image.width, int(np.ceil(x2 + dx))),
        min(image.height, int(np.ceil(y2 + dy))),
    )
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise ValueError("Invalid or empty plate crop")
    return image.crop(clipped)


def generate_dataset(config: Config, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}; choose a new dataset directory")
    fonts = font_paths(Path(config.assets))
    backgrounds = load_backgrounds(
        Path(config.background_manifest) if config.background_manifest else None
    )
    output.mkdir(parents=True)
    marker = output / "INCOMPLETE"
    marker.touch()
    background_splits = {name: [] for name in ("train", "val", "test")}
    # Reserve at least one source for each held-out partition, even with three assets.
    if backgrounds:
        rng = np.random.default_rng(config.seed)
        rng.shuffle(backgrounds)
        for index, asset in enumerate(backgrounds):
            split = "test" if index == 0 else "val" if index == 1 else "train"
            background_splits[split].append(asset)
    identity_splits = {}
    crop_count = 0
    with (output / "scenes.jsonl").open("w") as scenes, (output / "crops.jsonl").open("w") as crops:
        total_extra = config.crops - config.scenes
        # Negative scenes do not provide crops; top them up after scene rendering.
        total = config.scenes + total_extra
        index = 0
        while index < total or crop_count < config.crops:
            is_scene = index < config.scenes
            split = (
                split_for(index, config.scenes)
                if is_scene
                else split_for((index - config.scenes) % max(10, total_extra), max(10, total_extra))
            )
            seed = config.seed + index * 104729
            rng = np.random.default_rng(seed)
            negative = is_scene and rng.random() < config.negative_fraction
            text = ""
            if not negative:
                while True:
                    text = "".join(
                        rng.choice(
                            list(ALPHABET),
                            int(rng.integers(config.min_length, config.max_length + 1)),
                        )
                    )
                    if text not in identity_splits or identity_splits[text] == split:
                        identity_splits[text] = split
                        break
            style = str(rng.choice(list(STYLES)))
            kind = str(rng.choice(["indoor", "vehicle"]))
            hard = bool(rng.random() < config.hard_fraction)
            asset = (
                background_splits[split][int(rng.integers(len(background_splits[split])))]
                if background_splits[split]
                else None
            )
            plate = render_plate(text, style, fonts, rng) if text else None
            render_config = config if is_scene else replace(config, width=320, height=240)
            image, corners, effects = compose_scene(
                plate, render_config, rng, kind, hard, Path(asset["path"]) if asset else None
            )
            sample_id = f"{index:07d}"
            bbox = box_from_corners(corners, image.width, image.height) if text else None
            row = {
                "id": sample_id,
                "split": split,
                "text": text,
                "style": style,
                "scene": kind,
                "difficulty": "hard" if hard else "controlled",
                "bbox": bbox,
                "corners": corners.tolist() if text else None,
                "width": image.width,
                "height": image.height,
                "seed": seed,
                "source_ids": [asset["source_id"]] if asset else [],
                "effects": effects,
            }
            if is_scene:
                row["image"] = f"images/{split}/{sample_id}.jpg"
                row["label"] = f"labels/{split}/{sample_id}.txt"
                image_path, label_path = output / row["image"], output / row["label"]
                image_path.parent.mkdir(parents=True, exist_ok=True)
                label_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(image_path, quality=95)
                label = ""
                if bbox:
                    x1, y1, x2, y2 = bbox
                    label = f"0 {(x1 + x2) / 2 / image.width:.8f} {(y1 + y2) / 2 / image.height:.8f} {(x2 - x1) / image.width:.8f} {(y2 - y1) / image.height:.8f}\n"
                label_path.write_text(label)
            if text and crop_count < config.crops:
                row["crop"] = f"ocr/{split}/{sample_id}.jpg"
                crop_path = output / row["crop"]
                crop_path.parent.mkdir(parents=True, exist_ok=True)
                jitter = float(rng.uniform(0.01, 0.06))
                crop_plate(image, bbox, jitter).save(crop_path, quality=95)
                crops.write(json.dumps(row) + "\n")
                crop_count += 1
            if is_scene:
                scenes.write(json.dumps(row) + "\n")
            index += 1
            if index % 1000 == 0:
                print(
                    f"Generated {min(index, config.scenes)}/{config.scenes} scenes, {crop_count}/{config.crops} crops",
                    flush=True,
                )
    for split in ("train", "val", "test"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)
    (output / "dataset.yaml").write_text(
        yaml.safe_dump(
            {
                "path": str(output.resolve()),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": {0: "plate"},
            }
        )
    )
    write_json(
        output / "manifest.json",
        {
            "config": config.to_dict(),
            "config_hash": fingerprint(config.to_dict()),
            "backgrounds": backgrounds,
            "font_files": [{"name": p.name, "sha256": file_hash(p)} for p in fonts],
            "photographic_backgrounds": len(backgrounds),
            "scenes": config.scenes,
            "crops": crop_count,
            "text_normalization": "uppercase ASCII A-Z and 0-9, no separators",
        },
    )
    validate_dataset(output, allow_incomplete=True)
    marker.unlink()
    preview(output, output / "preview.jpg")
    return output


def validate_dataset(root: Path, allow_incomplete: bool = False) -> dict:
    if (root / "INCOMPLETE").exists() and not allow_incomplete:
        raise ValueError("Dataset generation is incomplete")
    identities, sources = {}, {}
    rows = read_records(root / "scenes.jsonl")
    crop_rows = read_records(root / "crops.jsonl")
    if not rows or not crop_rows:
        raise ValueError("Dataset needs scenes and OCR crops")
    for row in rows + crop_rows:
        split = row["split"]
        if split not in ("train", "val", "test"):
            raise ValueError("Invalid split")
        if row["text"] and identities.setdefault(row["text"], split) != split:
            raise ValueError("Plate identity overlaps splits")
        for source in row["source_ids"]:
            if sources.setdefault(source, split) != split:
                raise ValueError("Background source overlaps splits")
        for key in ("image", "crop"):
            if key in row:
                with Image.open(root / row[key]) as image:
                    image.verify()
        if row["bbox"]:
            x1, y1, x2, y2 = row["bbox"]
            if not (0 <= x1 < x2 <= row["width"] and 0 <= y1 < y2 <= row["height"]):
                raise ValueError("Invalid bounding box")
        if "label" in row:
            label = (root / row["label"]).read_text().strip()
            if bool(label) != bool(row["text"]):
                raise ValueError("Invalid negative label")
            if label:
                values = label.split()
                if len(values) != 5 or values[0] != "0":
                    raise ValueError("Invalid YOLO label")
                x, y, w, h = map(float, values[1:])
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                    raise ValueError("Invalid YOLO label bounds")
                expected = [
                    (x1 + x2) / 2 / row["width"],
                    (y1 + y2) / 2 / row["height"],
                    (x2 - x1) / row["width"],
                    (y2 - y1) / row["height"],
                ]
                if not np.allclose([x, y, w, h], expected, atol=1e-6):
                    raise ValueError("YOLO label does not match pixel box")
    return {"scenes": len(rows), "crops": len(crop_rows), "text_identities": len(identities)}


def preview(root: Path, destination: Path, count: int = 24):
    rows = read_records(root / "scenes.jsonl")
    # Spread selection across all splits and scene types.
    rows = [rows[i] for i in np.linspace(0, len(rows) - 1, min(count, len(rows)), dtype=int)]
    sheet = Image.new("RGB", (4 * 320, ((len(rows) + 3) // 4) * 264), "white")
    for i, row in enumerate(rows):
        with Image.open(root / row["image"]) as source:
            image = source.convert("RGB")
        if row["bbox"]:
            ImageDraw.Draw(image).rectangle(row["bbox"], outline="lime", width=2)
        tile = ImageOps.pad(image, (320, 240))
        x, y = (i % 4) * 320, (i // 4) * 264
        sheet.paste(tile, (x, y))
        ImageDraw.Draw(sheet).text(
            (x + 4, y + 242),
            f"{row['style']} {row['text'] or 'NO PLATE'} | {row['split']} {row['difficulty']}",
            fill="black",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)
