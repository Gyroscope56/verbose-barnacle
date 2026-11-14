import json

import numpy as np
import pytest
from PIL import Image

from parksight.config import Config
from parksight.generate import generate_dataset, validate_dataset
from parksight.render import box_from_corners


def test_box_clips_projected_geometry():
    assert box_from_corners(np.array([[-3, 5], [18, 2], [22, 14], [0, 16]]), 20, 15) == [
        0,
        2,
        20,
        15,
    ]


def test_generation_is_deterministic_and_split_disjoint(tmp_path):
    cfg = Config(scenes=30, crops=45, width=320, height=240, negative_fraction=0.25)
    a, b = tmp_path / "a", tmp_path / "b"
    generate_dataset(cfg, a)
    generate_dataset(cfg, b)
    assert (a / "scenes.jsonl").read_bytes() == (b / "scenes.jsonl").read_bytes()
    rows = [json.loads(line) for line in (a / "scenes.jsonl").read_text().splitlines()]
    assert len(rows) == 30
    identities = {}
    for row in rows:
        if row["text"]:
            assert identities.setdefault(row["text"], row["split"]) == row["split"]
            x1, y1, x2, y2 = row["bbox"]
            assert 0 <= x1 < x2 <= 320 and 0 <= y1 < y2 <= 240
            assert Image.open(a / row["crop"]).width > 0
        else:
            assert not (a / row["label"]).read_text().strip()
        assert (a / row["image"]).read_bytes() == (b / row["image"]).read_bytes()
    assert validate_dataset(a)["scenes"] == 30
    with pytest.raises(FileExistsError):
        generate_dataset(cfg, a)


def test_validator_rejects_out_of_bounds_label(tmp_path):
    generate_dataset(Config(scenes=20, crops=20, width=320, height=240), tmp_path / "data")
    root = tmp_path / "data"
    rows = [json.loads(line) for line in (root / "scenes.jsonl").read_text().splitlines()]
    row = next(r for r in rows if r["text"])
    (root / row["label"]).write_text("0 1.8 0.5 0.5 0.5\n")
    with pytest.raises(ValueError, match="label"):
        validate_dataset(root)
