import os
import shutil
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from parksight.generate import crop_plate
from parksight.ocr import IMAGE_SIZE, VOCABULARY, decode_ctc, load_recognizer, preprocess
from parksight.records import file_hash, read_records, write_json


def ort_session(path: Path):
    import onnxruntime as ort

    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


@torch.inference_mode()
def export_ocr(model, examples: list[torch.Tensor], output: Path) -> dict:
    if not examples:
        raise ValueError("Export parity needs representative OCR inputs")
    model = model.cpu().eval()
    torch.onnx.export(
        model,
        (examples[0],),
        str(output),
        dynamo=True,
        opset_version=18,
        input_names=["images"],
        output_names=["logits"],
        external_data=False,
    )
    session = ort_session(output)
    errors = []
    for example in examples:
        expected = model(example).numpy()
        actual = session.run(None, {"images": example.numpy()})[0]
        np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-3)
        if (
            decode_ctc(torch.from_numpy(actual))[0][0]
            != decode_ctc(torch.from_numpy(expected))[0][0]
        ):
            raise ValueError("ONNX OCR decoded text differs from PyTorch")
        errors.append(float(np.max(np.abs(actual - expected))))
    return {
        "samples": len(examples),
        "max_absolute_error": max(errors),
        "rtol": 1e-3,
        "atol": 1e-3,
        "decoded_text_parity": True,
    }


@torch.inference_mode()
def export_models(
    detector_path: Path, ocr_path: Path, dataset: Path, output: Path, detector_size: int = 640
) -> dict:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite export {output}")
    if detector_size < 160 or detector_size % 32:
        raise ValueError("Detector size must be >=160 and divisible by 32")
    if (dataset / "INCOMPLETE").exists():
        raise ValueError("Dataset incomplete")
    rows = [r for r in read_records(dataset / "scenes.jsonl") if r["split"] == "val" and r["text"]]
    if not rows:
        raise ValueError("Export parity needs positive validation scenes")
    selected = [rows[i] for i in np.linspace(0, len(rows) - 1, min(6, len(rows)), dtype=int)]
    images, crops = [], []
    for row in selected:
        with Image.open(dataset / row["image"]) as image:
            image = image.convert("RGB")
            images.append(image)
            crops.append(preprocess(crop_plate(image, row["bbox"])).unsqueeze(0))
    output.mkdir(parents=True)
    (output / "INCOMPLETE").touch()
    torch.set_num_threads(2)
    metadata = {
        "opset": 18,
        "provider": "CPUExecutionProvider",
        "batch_size": 1,
        "source_detector_sha256": file_hash(detector_path),
        "source_ocr_sha256": file_hash(ocr_path),
        "validation_images": [row["image"] for row in selected],
        "uno_q_verified": False,
    }
    metadata["ocr_parity"] = export_ocr(
        load_recognizer(ocr_path, "cpu"), crops, output / "ocr.onnx"
    )
    os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(".cache/ultralytics").resolve()))
    from ultralytics import YOLO
    from ultralytics.data.augment import LetterBox

    temporary_weights = output / "detector.pt"
    shutil.copy2(detector_path, temporary_weights)
    detector = YOLO(str(temporary_weights))
    try:
        exported = Path(
            detector.export(
                format="onnx",
                imgsz=detector_size,
                opset=18,
                simplify=False,
                dynamic=False,
                nms=False,
                device="cpu",
                batch=1,
            )
        )
        session = ort_session(exported)
        detector.model.cpu().eval()
        errors = []
        for image in images:
            array = LetterBox(new_shape=(detector_size, detector_size), auto=False)(
                image=np.array(image)
            )
            tensor = torch.from_numpy(array.copy()).permute(2, 0, 1).unsqueeze(0).float() / 255
            expected = detector.model(tensor)[0].numpy()
            actual = session.run(None, {session.get_inputs()[0].name: tensor.numpy()})[0]
            np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-3)
            errors.append(float(np.max(np.abs(actual - expected))))
        metadata["detector_parity"] = {
            "samples": len(images),
            "max_absolute_error": max(errors),
            "rtol": 1e-3,
            "atol": 1e-3,
        }
    finally:
        temporary_weights.unlink(missing_ok=True)
    metadata["ocr"] = {
        "input": [1, 3, 64, 192],
        "vocabulary": VOCABULARY,
        "image_size": list(IMAGE_SIZE),
        "normalization": "RGB float32 /127.5 -1; aspect-preserving resize; white right padding",
        "output": "batch,time,37 logits; apply CTC greedy decoding with blank index 0",
    }
    metadata["detector"] = {
        "input": [1, 3, detector_size, detector_size],
        "normalization": "RGB float32 /255; centered letterbox padding value 114",
        "output": "raw YOLO11 single-class boxes and scores; apply confidence filtering, NMS, and inverse letterbox mapping on host",
    }
    metadata["onnx_sha256"] = {
        name: file_hash(output / name) for name in ("ocr.onnx", "detector.onnx")
    }
    write_json(output / "metadata.json", metadata)
    (output / "INCOMPLETE").unlink()
    return metadata
