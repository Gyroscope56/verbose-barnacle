import pytest
from PIL import Image

from parksight.evaluate import summarize_predictions, text_metrics
from parksight.generate import crop_plate


def test_misses_and_wrong_boxes_count_as_end_to_end_failures():
    rows = [
        dict(text="ABC12", bbox=[0, 0, 100, 50]),
        dict(text="ABC13", bbox=[0, 0, 100, 50]),
        dict(text="", bbox=None),
    ]
    predictions = [
        [],
        [dict(text="ABC13", bbox=[200, 0, 300, 50])],
        [dict(text="X", bbox=[0, 0, 10, 10])],
    ]
    metrics = summarize_predictions(rows, predictions)
    assert metrics["positive_scenes"] == 2
    assert metrics["end_to_end_exact_accuracy"] == 0
    assert metrics["negative_false_positive_rate"] == 1


def test_ocr_metrics_use_character_edit_distance():
    rows = [dict(text="ABC12", bbox=[0, 0, 100, 50])]
    predictions = [[dict(text="ABC1", bbox=[0, 0, 100, 50])]]
    metrics = summarize_predictions(rows, predictions)
    assert metrics["end_to_end_character_error_rate"] == 0.2
    assert metrics["matched_detection_recall_iou50"] == 1


def test_metrics_reject_empty_evaluation_and_length_mismatch():
    with pytest.raises(ValueError):
        summarize_predictions([], [])
    with pytest.raises(ValueError):
        summarize_predictions([dict(text="ABC12", bbox=[0, 0, 10, 10])], [])


def test_invalid_crop_rejected_and_padding_clipped():
    image = Image.new("RGB", (100, 50))
    assert crop_plate(image, [0, 0, 100, 50], 0.1).size == (100, 50)
    with pytest.raises(ValueError):
        crop_plate(image, [90, 10, 10, 20])


def test_crop_text_metrics_include_every_target_and_character():
    metrics = text_metrics(["AAB12", "XYZ99"], ["AAB12", "XY99"])
    assert metrics == {"count": 2, "exact_accuracy": 0.5, "character_error_rate": 0.1}
    with pytest.raises(ValueError):
        text_metrics(["AAB12"], [])
