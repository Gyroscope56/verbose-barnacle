import json

import pytest

from parksight.assets import load_backgrounds
from parksight.config import Config


@pytest.mark.parametrize(
    "values", [dict(scenes=0), dict(width=-1), dict(negative_fraction=1.2), dict(min_length=9)]
)
def test_reject_invalid_configuration(values):
    with pytest.raises(ValueError):
        Config(**values)


def test_background_requires_license_and_explicit_plate_review(tmp_path):
    path = tmp_path / "backgrounds.json"
    path.write_text(json.dumps([{"path": "photo.jpg", "source_id": "photo-1"}]))
    with pytest.raises(ValueError, match="license|plate"):
        load_backgrounds(path)
