import importlib.metadata
import json
import os
import random
import time
from functools import partial
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from parksight.config import Config
from parksight.ocr import (
    IMAGE_SIZE,
    VOCABULARY,
    CropDataset,
    PlateRecognizer,
    collate_crops,
    decode_ctc,
)
from parksight.records import file_hash, fingerprint, write_json


def select_device(requested: str = "auto") -> str:
    if requested == "auto":
        return (
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
    if requested == "mps" and not torch.backends.mps.is_available():
        raise ValueError(
            "MPS unavailable; on this Mac, GPU access requires running outside the sandbox"
        )
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable in this Python environment")
    return requested


def versions():
    return {
        name: importlib.metadata.version(name)
        for name in ("torch", "torchvision", "ultralytics", "numpy", "pillow")
    }


def dataset_hash(root: Path):
    if (root / "INCOMPLETE").exists():
        raise ValueError("Cannot train on incomplete dataset")
    return fingerprint(
        [file_hash(root / name) for name in ("manifest.json", "crops.jsonl", "scenes.jsonl")]
    )


def check_resume(checkpoint: dict, expected_hash: str):
    if checkpoint["dataset_hash"] != expected_hash:
        raise ValueError("Resume dataset does not match checkpoint")
    if checkpoint["vocabulary"] != VOCABULARY or checkpoint["image_size"] != list(IMAGE_SIZE):
        raise ValueError("Resume vocabulary or preprocessing does not match")


def check_resume_location(resume: Path | None, output: Path, detector: bool = False):
    if resume is None:
        return
    origin = resume.parent.parent if detector else resume.parent
    if origin.resolve() != output.resolve():
        raise ValueError("Resume must use the same run directory as its checkpoint")
    if not resume.is_file():
        raise FileNotFoundError(f"Missing resume checkpoint {resume}")


def ctc_loss_device(device: str) -> str:
    if device != "mps":
        return device
    try:
        logits = torch.randn(5, 1, 37, device="mps", requires_grad=True)
        loss = torch.nn.CTCLoss()(
            logits.log_softmax(-1), torch.tensor([11]), torch.tensor([5]), torch.tensor([1])
        )
        loss.backward()
        return "mps"
    except (RuntimeError, NotImplementedError):
        return "cpu"


def save_checkpoint(path: Path, checkpoint: dict):
    temporary = path.with_suffix(".tmp")
    torch.save(checkpoint, temporary)
    temporary.replace(path)


@torch.inference_mode()
def validate_ocr(model, loader, device):
    model.eval()
    correct = total = 0
    for images, _, _, texts in loader:
        predicted = decode_ctc(model(images.to(device)))
        correct += sum(text == truth for (text, _), truth in zip(predicted, texts))
        total += len(texts)
    return correct / total


def train_ocr(config: Config, dataset: Path, output: Path, resume: Path | None = None) -> Path:
    check_resume_location(resume, output)
    device = select_device(config.device)
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    data_hash = dataset_hash(dataset)
    if output.exists() and not resume:
        raise FileExistsError(f"Refusing to overwrite training run {output}")
    output.mkdir(parents=True, exist_ok=True)
    model = PlateRecognizer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=1e-4)
    start_epoch, best, history = 0, -1.0, []
    if resume:
        checkpoint = torch.load(resume, map_location="cpu", weights_only=False)
        check_resume(checkpoint, data_hash)
        mutable = {"ocr_epochs", "ocr_minutes", "device"}
        selected_path = output / "best.pt"
        if selected_path.exists():
            selected = torch.load(selected_path, map_location="cpu", weights_only=False)
            check_resume(selected, data_hash)
            if any(
                selected["config"][key] != value
                for key, value in checkpoint["config"].items()
                if key not in mutable
            ):
                raise ValueError(
                    "Selected best checkpoint belongs to another training configuration"
                )
        elif checkpoint.get("epoch", 0) > 0:
            raise ValueError("Resume run is missing its selected best.pt checkpoint")
        # Epoch/time limits and device may change, other training choices must match.
        if any(
            checkpoint["config"][key] != value
            for key, value in config.to_dict().items()
            if key not in mutable
        ):
            raise ValueError("Resume training configuration differs from checkpoint")
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        start_epoch, best, history = (
            checkpoint["epoch"],
            checkpoint["best_accuracy"],
            checkpoint["history"],
        )
    train_data, val_data = CropDataset(dataset, "train"), CropDataset(dataset, "val")
    loader_options = dict(
        batch_size=config.ocr_batch, num_workers=config.workers, collate_fn=collate_crops
    )
    val_loader = DataLoader(val_data, shuffle=False, **loader_options)
    loss_device = ctc_loss_device(device)
    print(
        f"OCR device={device}, CTC loss={loss_device}, train={len(train_data)}, val={len(val_data)}",
        flush=True,
    )
    criterion = torch.nn.CTCLoss(blank=0, zero_infinity=False)
    started = time.monotonic()
    epoch = start_epoch
    status = "running"
    provenance = {
        "config": config.to_dict(),
        "dataset_hash": data_hash,
        "versions": versions(),
        "device": device,
        "ctc_device": loss_device,
        "vocabulary": VOCABULARY,
        "image_size": list(IMAGE_SIZE),
    }
    write_json(output / "run.json", {**provenance, "status": status})

    def snapshot():
        return {
            **provenance,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "epoch": epoch,
            "best_accuracy": best,
            "history": history,
            "status": status,
        }

    try:
        for current in range(start_epoch, config.ocr_epochs):
            generator = torch.Generator().manual_seed(config.seed + current)
            loader = DataLoader(train_data, shuffle=True, generator=generator, **loader_options)
            model.train()
            total_loss, batches = 0.0, 0
            expired = False
            for images, targets, lengths, _ in loader:
                if time.monotonic() - started > config.ocr_minutes * 60:
                    expired = True
                    break
                optimizer.zero_grad(set_to_none=True)
                logits = model(images.to(device))
                log_probs = logits.log_softmax(-1).transpose(0, 1).to(loss_device)
                inputs = torch.full((len(images),), logits.shape[1], dtype=torch.long)
                loss = criterion(log_probs, targets.to(loss_device), inputs, lengths)
                if not torch.isfinite(loss):
                    raise RuntimeError("Nonfinite OCR loss; inspect crops and target lengths")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
                total_loss += float(loss.detach().cpu())
                batches += 1
            if expired:
                status = "time_limit"
                break
            accuracy = validate_ocr(model, val_loader, device)
            epoch = current + 1
            history.append(
                {
                    "epoch": epoch,
                    "loss": total_loss / max(1, batches),
                    "val_exact_accuracy": accuracy,
                    "seconds": time.monotonic() - started,
                }
            )
            print(json.dumps(history[-1]), flush=True)
            if accuracy > best:
                best = accuracy
                save_checkpoint(output / "best.pt", snapshot())
            save_checkpoint(output / "last.pt", snapshot())
            write_json(output / "history.json", history)
        else:
            status = "completed"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception:
        status = "failed"
        raise
    finally:
        save_checkpoint(output / "last.pt", snapshot())
        write_json(
            output / "run.json",
            {
                **provenance,
                "status": status,
                "completed_epochs": epoch,
                "best_val_exact_accuracy": best,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
    if not (output / "best.pt").exists():
        raise RuntimeError(
            "No completed validation epoch; resumable last.pt saved, but no selected model"
        )
    return output / "best.pt"


def enforce_epoch_cap(trainer, max_epochs: int):
    # Ultralytics time mode re-estimates epochs after every epoch.
    trainer.stop |= trainer.epoch + 1 >= max_epochs


def train_detector(config: Config, dataset: Path, output: Path, resume: Path | None = None) -> Path:
    check_resume_location(resume, output, detector=True)
    # Keep Ultralytics settings and caches within the project.
    os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(".cache/ultralytics").resolve()))
    from ultralytics import YOLO

    device = select_device(config.device)
    data_hash = dataset_hash(dataset)
    run_metadata = output / "parksight.json"
    if output.exists() and not resume:
        raise FileExistsError(f"Refusing to overwrite detector run {output}")
    if resume:
        metadata = json.loads(run_metadata.read_text())
        if metadata["dataset_hash"] != data_hash:
            raise ValueError("Resume dataset does not match detector run")
        mutable = {"detector_epochs", "detector_hours", "device"}
        if any(
            metadata["config"][key] != value
            for key, value in config.to_dict().items()
            if key not in mutable
        ):
            raise ValueError("Resume detector configuration differs from run")
        checkpoint = torch.load(resume, map_location="cpu", weights_only=False)
        arguments = checkpoint.get("train_args", {})
        if Path(arguments.get("data", "")).resolve() != (dataset / "dataset.yaml").resolve():
            raise ValueError("Resume checkpoint dataset does not match requested dataset")
        checkpoint_output = arguments.get("save_dir") or str(
            Path(arguments.get("project", "")) / arguments.get("name", "")
        )
        if Path(checkpoint_output).resolve() != output.resolve():
            raise ValueError("Resume checkpoint output does not match the same run")
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "config": config.to_dict(),
        "dataset_hash": data_hash,
        "versions": versions(),
        "device": device,
        "status": "running",
    }
    write_json(run_metadata, metadata)
    weights = resume if resume else Path(config.assets) / "yolo11n.pt"
    if not weights.exists():
        raise FileNotFoundError(f"Missing {weights}; run parksight assets --detector first")
    model = YOLO(str(weights))
    model.add_callback(
        "on_fit_epoch_end", partial(enforce_epoch_cap, max_epochs=config.detector_epochs)
    )
    try:
        model.train(
            data=str((dataset / "dataset.yaml").resolve()),
            epochs=config.detector_epochs,
            imgsz=config.detector_size,
            batch=config.detector_batch,
            device=0 if device == "cuda" else device,
            workers=config.workers,
            project=str(output.parent.resolve()),
            name=output.name,
            exist_ok=True,
            seed=config.seed,
            deterministic=True,
            time=config.detector_hours,
            resume=bool(resume),
            amp=False,
            cache=False,
            plots=True,
            fliplr=0.0,
            flipud=0.0,
            mosaic=0.0,
            degrees=0.0,
            translate=0.05,
            scale=0.15,
            hsv_h=0.015,
            hsv_s=0.2,
            hsv_v=0.2,
            patience=config.detector_epochs,
        )
        if Path(model.trainer.save_dir).resolve() != output.resolve():
            raise RuntimeError("Detector trainer wrote to an unexpected output directory")
        metadata["status"] = "completed"
    except KeyboardInterrupt:
        metadata["status"] = "interrupted"
        raise
    except Exception:
        metadata["status"] = "failed"
        raise
    finally:
        write_json(run_metadata, metadata)
    return output / "weights/best.pt"
