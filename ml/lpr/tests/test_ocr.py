import numpy as np
import pytest
import torch
from PIL import Image

from parksight.ocr import PlateRecognizer, decode_ctc, preprocess


@pytest.mark.parametrize(
    "ids, expected", [([11, 0, 11], "AA"), ([11, 11, 0], "A"), ([0, 0, 0], "")]
)
def test_ctc_repeats_and_blank(ids, expected):
    logits = torch.full((1, len(ids), 37), -12.0)
    for t, token in enumerate(ids):
        logits[0, t, token] = 12
    text, score = decode_ctc(logits)[0]
    assert text == expected
    assert score > 0.99 if expected else score == 0


def test_preprocessing_preserves_proportions_and_padding():
    tensor = preprocess(Image.new("RGB", (100, 100), "black"))
    assert tensor.shape == (3, 64, 192)
    assert torch.all(tensor[:, :, :64] == -1)
    assert torch.all(tensor[:, :, 64:] == 1)


def test_ctc_training_step_has_finite_gradients_for_repeated_text():
    model = PlateRecognizer()
    logits = model(torch.randn(2, 3, 64, 192))
    loss = torch.nn.CTCLoss()(
        logits.log_softmax(-1).transpose(0, 1),
        torch.tensor([11, 11, 12, 11]),
        torch.full((2,), logits.shape[1]),
        torch.tensor([2, 2]),
    )
    loss.backward()
    assert np.isfinite(loss.item())
    assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
