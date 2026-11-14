import pytest
import torch
from PIL import Image

from parksight.ocr import PlateRecognizer, preprocess


def test_ocr_export_matches_real_preprocessed_image(tmp_path):
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnxscript")
    from parksight.exporting import export_ocr

    torch.manual_seed(4)
    image = Image.new("RGB", (240, 120), "white")
    model = PlateRecognizer().eval()
    result = export_ocr(model, [preprocess(image).unsqueeze(0)], tmp_path / "ocr.onnx")
    assert (tmp_path / "ocr.onnx").exists()
    assert result["samples"] == 1
    assert result["max_absolute_error"] < 0.001
