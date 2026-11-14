import pytest
import torch

from parksight.config import Config
from parksight.generate import generate_dataset
from parksight.ocr import IMAGE_SIZE, VOCABULARY, PlateRecognizer
from parksight.records import write_json
from parksight.train import check_resume, dataset_hash, train_detector, train_ocr


def test_resume_rejects_different_dataset_or_vocabulary():
    checkpoint = {"dataset_hash": "a", "vocabulary": "abc", "image_size": [192, 64]}
    with pytest.raises(ValueError, match="dataset"):
        check_resume(checkpoint, "b")
    with pytest.raises(ValueError, match="vocabulary"):
        check_resume(checkpoint, "a")


@pytest.mark.parametrize(
    "training,checkpoint", [(train_ocr, "best.pt"), (train_detector, "weights/last.pt")]
)
def test_resume_rejects_another_output_before_loading_data(tmp_path, training, checkpoint):
    original = tmp_path / "original"
    original.mkdir()
    other = tmp_path / "unrelated"
    other.mkdir()
    sentinel = other / "best.pt"
    sentinel.write_bytes(b"unrelated model must not be touched")
    with pytest.raises(ValueError, match="same run"):
        training(Config(device="cpu"), tmp_path / "unused-dataset", other, original / checkpoint)
    assert sentinel.read_bytes() == b"unrelated model must not be touched"
    assert not (other / "run.json").exists()


def test_ocr_resume_rejects_stale_best_in_same_directory(tmp_path):
    cfg = Config(device="cpu", scenes=20, crops=20, width=320, height=240)
    data = tmp_path / "data"
    generate_dataset(cfg, data)
    output = tmp_path / "run"
    output.mkdir()
    checkpoint = {
        "dataset_hash": dataset_hash(data),
        "vocabulary": VOCABULARY,
        "image_size": list(IMAGE_SIZE),
        "config": cfg.to_dict(),
        "epoch": 1,
    }
    torch.save(checkpoint, output / "last.pt")
    torch.save({**checkpoint, "dataset_hash": "another-dataset"}, output / "best.pt")
    with pytest.raises(ValueError, match="dataset"):
        train_ocr(cfg, data, output, output / "last.pt")
    assert not (output / "run.json").exists()


@pytest.mark.parametrize("wrong_field", ["data", "project"])
def test_detector_resume_rejects_copied_checkpoint_provenance(tmp_path, wrong_field):
    cfg = Config(device="cpu", scenes=20, crops=20, width=320, height=240)
    data = tmp_path / "data"
    generate_dataset(cfg, data)
    output = tmp_path / "run"
    (output / "weights").mkdir(parents=True)
    metadata = {"dataset_hash": dataset_hash(data), "config": cfg.to_dict()}
    write_json(output / "parksight.json", metadata)
    arguments = {
        "data": str(data / "dataset.yaml"),
        "project": str(output.parent),
        "name": output.name,
    }
    arguments[wrong_field] = str(tmp_path / "other")
    torch.save({"train_args": arguments}, output / "weights/last.pt")
    with pytest.raises(ValueError, match="checkpoint"):
        train_detector(cfg, data, output, output / "weights/last.pt")
    import json

    assert json.loads((output / "parksight.json").read_text()) == metadata


def test_resume_allows_changed_budget_without_losing_original_selected_best(tmp_path):
    cfg = Config(device="cpu", scenes=20, crops=20, width=320, height=240, ocr_epochs=1)
    data = tmp_path / "data"
    generate_dataset(cfg, data)
    output = tmp_path / "run"
    output.mkdir()
    model = PlateRecognizer()
    checkpoint = {
        "dataset_hash": dataset_hash(data),
        "vocabulary": VOCABULARY,
        "image_size": list(IMAGE_SIZE),
        "config": cfg.to_dict(),
        "epoch": 1,
        "model": model.state_dict(),
        "optimizer": torch.optim.AdamW(model.parameters()).state_dict(),
        "best_accuracy": 0.5,
        "history": [],
    }
    torch.save(checkpoint, output / "last.pt")
    best = {**checkpoint, "config": {**cfg.to_dict(), "ocr_epochs": 2}}
    torch.save(best, output / "best.pt")
    before = (output / "best.pt").read_bytes()
    assert train_ocr(cfg, data, output, output / "last.pt") == output / "best.pt"
    assert (output / "best.pt").read_bytes() == before
