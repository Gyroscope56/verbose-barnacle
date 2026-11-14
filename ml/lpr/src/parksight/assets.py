import json
import ssl
from pathlib import Path
from urllib.request import urlopen

import certifi
from PIL import Image, ImageFont

from parksight.records import file_hash, write_json

FONT_SOURCES = {
    "RobotoMono": "robotomono/RobotoMono%5Bwght%5D.ttf",
    "BarlowCondensed": "barlowcondensed/BarlowCondensed-SemiBold.ttf",
    "Oswald": "oswald/Oswald%5Bwght%5D.ttf",
}
BASE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/"


def prepare_assets(root: Path) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, source in FONT_SOURCES.items():
        font_path = root / f"{name}.ttf"
        license_path = root / f"{name}-OFL.txt"
        for destination, url in (
            (font_path, BASE_URL + source),
            (license_path, BASE_URL + source.split("/")[0] + "/OFL.txt"),
        ):
            if not destination.exists():
                temporary = destination.with_suffix(".download")
                try:
                    with urlopen(
                        url, timeout=40, context=ssl.create_default_context(cafile=certifi.where())
                    ) as response:
                        temporary.write_bytes(response.read())
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
        ImageFont.truetype(str(font_path), 32)
        manifest.append(
            {
                "source_id": name,
                "path": str(font_path.resolve()),
                "source": BASE_URL + source,
                "license": "SIL OFL 1.1",
                "attribution": license_path.read_text().splitlines()[0],
                "sha256": file_hash(font_path),
            }
        )
    write_json(root / "fonts.json", manifest)
    return manifest


def font_paths(root: Path) -> list[Path]:
    paths = sorted(root.glob("*.ttf"))
    if paths:
        return paths
    # Local-only fallback; these fonts are never bundled or redistributed.
    local = Path("/System/Library/Fonts/Supplemental")
    paths = [local / "Arial Narrow Bold.ttf", local / "Courier New Bold.ttf"]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise FileNotFoundError("No fonts. Run parksight assets or install TTF files in assets/")
    return paths


def load_backgrounds(path: Path | None) -> list[dict]:
    if path is None:
        return []
    rows = json.loads(path.read_text())
    seen = set()
    for row in rows:
        required = ("source_id", "path", "source", "license", "attribution")
        if (
            any(not row.get(key) for key in required)
            or row.get("plate_review") != "no-readable-plates"
        ):
            raise ValueError("Background requires source, license, attribution, and plate review")
        if row["source_id"] in seen:
            raise ValueError("Duplicate background source identity")
        seen.add(row["source_id"])
        image_path = (path.parent / row["path"]).resolve()
        with Image.open(image_path) as image:
            image.verify()
        row["path"] = str(image_path)
    if rows and len(rows) < 3:
        raise ValueError("Need at least three independent backgrounds for disjoint splits")
    return rows


def download_detector(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "yolo11n.pt"
    source = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
    if not destination.exists():
        temporary = destination.with_suffix(".download")
        try:
            with urlopen(
                source, timeout=60, context=ssl.create_default_context(cafile=certifi.where())
            ) as response:
                temporary.write_bytes(response.read())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    write_json(
        root / "detector.json",
        {
            "source": source,
            "license": "AGPL-3.0 / Ultralytics enterprise",
            "sha256": file_hash(destination),
        },
    )
    print(f"Detector weights: {destination}")
