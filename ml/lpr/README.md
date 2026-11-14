# ParkSight LPR

Generate labeled synthetic plates, fine-tune a plate detector, and train a compact text recognizer locally. The recognizer reads unseen strings rather than choosing a vehicle from a fixed list. This baseline supports one visible plate per image and Wisconsin, Illinois, and Minnesota-inspired single-line layouts.

## Setup

Use Python 3.11 or newer. The tested environment uses Python 3.13 on an M4 Pro Mac with 24 GB memory.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
parksight assets --detector
parksight --help
```

The assets command downloads three SIL Open Font License fonts with their notices, and YOLO11 nano weights. YOLO11 and its weights have AGPL-3.0/Ultralytics enterprise licensing. See [ASSETS.md](ASSETS.md). No license for ParkSight's original source is assigned by this change.

`requirements-lock.txt` records the tested Mac environment. On another platform, install the PyTorch build for that platform first, then install this package. For the RTX 5080, use a current CUDA-enabled PyTorch build that explicitly supports that GPU, verify `torch.cuda.is_available()`, and set `device = 'cuda'` in a copy of the configuration. The Mac lock file is provenance, not a portable CUDA installation recipe.

## Generate and inspect data

```sh
parksight generate --config configs/smoke.toml --output data/smoke
parksight validate-data --dataset data/smoke
parksight preview --dataset data/smoke --output data/smoke/contact-sheet.jpg
parksight print-plate ABC1234 --style WI --output data/printed-WI.png
```

The printable PNG is 1800 by 900 pixels with 300 DPI metadata. Choose the printed physical size in your print dialog. The artwork is state-inspired synthetic artwork, not an exact registration plate replica.

Inspect `preview.jpg` before training. Green outlines are generated bounding boxes. Backgrounds in the default run are stylized procedural indoor scenes and vehicles; they do not establish real-vehicle generalization. Fonts, string lengths, placement, perspective, brightness, glare, shadows, night exposure, blur, noise, JPEG compression, dirt, and limited occlusion vary. Most examples use controlled conditions; a configurable minority use harder conditions.

For the baseline:

```sh
parksight generate --config configs/baseline.toml --output data/baseline
parksight validate-data --dataset data/baseline
```

Default counts are 10,000 scene images and 30,000 OCR crops total. OCR crops include crops from positive scenes and additional independently generated examples. Plate-free negatives have empty detection labels and no OCR crop. All configuration values can be overridden in a TOML file; unknown or invalid values are rejected. The train/validation/test split is approximately 80/10/10. Plate strings and imported photographic source identities never cross partitions. Each dataset saves the resolved configuration, seed, font hashes, and asset provenance.

Generation refuses an existing output directory. A failed run leaves `INCOMPLETE`; inspect it and use a new directory for regeneration. Complete datasets are never silently overwritten. Generated data, weights, and local runs are ignored by Git.

### Annotation layout

```text
data/baseline/
  images/{train,val,test}/*.jpg
  labels/{train,val,test}/*.txt
  ocr/{train,val,test}/*.jpg
  scenes.jsonl
  crops.jsonl
  dataset.yaml
  manifest.json
  preview.jpg
```

Each scene JSONL record includes a relative image path, normalized text, state style, pixel box `[x1,y1,x2,y2]`, four transformed corners, image size, seed, scene/difficulty categories, asset IDs, augmentation values, and relative label/crop paths when present. Coordinates use image-edge units with an exclusive right/bottom crop bound. Empty text and a null box identify plate-free frames. YOLO labels use class zero and normalized center/width/height. OCR JSONL records contain only positive examples and a relative crop path.

To use photographic backgrounds, supply `background_manifest = 'path/to/backgrounds.json'` in your TOML. Provide at least three independently sourced, licensed images so source identities can remain disjoint. Image paths are relative to the manifest. Duplicate source IDs are rejected; use the same source identity for related footage rather than disguising neighboring frames as independent sources. Review and cover any existing readable plates before importing.

```json
[
  {
    "source_id": "independent-photo-001",
    "path": "photo001.jpg",
    "source": "https://example.org/original-photo",
    "license": "CC0-1.0",
    "attribution": "Photographer and source details",
    "plate_review": "no-readable-plates"
  }
]
```

The example shows the schema; it is not a supplied or verified background asset. The generator uses procedural backgrounds when no manifest is configured. A configured manifest with missing files or incomplete provenance fails rather than silently substituting a different dataset.

## Train

These commands start training immediately. Use the smoke configuration to verify your installation first:

```sh
parksight train-ocr --config configs/smoke.toml --dataset data/smoke --output runs/smoke-ocr
parksight train-detector --config configs/smoke.toml --dataset data/smoke --output runs/smoke-detector
```

Then train the baseline:

```sh
parksight train-ocr --config configs/baseline.toml --dataset data/baseline --output runs/baseline-ocr
parksight train-detector --config configs/baseline.toml --dataset data/baseline --output runs/baseline-detector
```

`device = 'auto'` selects CUDA, MPS, then CPU. Explicit device requests fail if unavailable. In the Codex sandbox, MPS may appear unavailable even though it works when launched locally. CTC forward/backward support is probed; an unsupported MPS loss uses a differentiable CPU loss while convolution remains on the GPU.

OCR uses RGB inputs padded to 192 by 64 pixels, a convolutional sequence network, and CTC over uppercase A-Z and digits. Display separators are excluded. Adjacent repeated characters are preserved when separated by a CTC blank. No whitelist alters predictions.

The baseline budgets are 20 OCR epochs or 90 minutes, and a hard cap of 12 detector epochs with a 1.5-hour time budget. Ultralytics can expand its displayed schedule in time mode; an epoch-end callback enforces the configured epoch cap. Checkpoint selection uses validation only. OCR saves optimizer state, last/best model, preprocessing, vocabulary, data/config fingerprints, dependency versions, and history. Interrupting saves resumable state. Mid-epoch resume restarts that epoch with the saved weights; it is not an exact continuation of the interrupted minibatch sequence. Use separate output directories for independent experiments.

```sh
parksight train-ocr --config configs/baseline.toml --dataset data/baseline \
  --output runs/baseline-ocr --resume runs/baseline-ocr/last.pt
parksight train-detector --config configs/baseline.toml --dataset data/baseline \
  --output runs/baseline-detector --resume runs/baseline-detector/weights/last.pt
```

Only load trusted PyTorch checkpoints. They are serialized executable Python data. Keep the generated dataset unchanged for resume. OCR permits changing device and epoch/time limits while rejecting incompatible training settings or vocabulary.

Resume in the original run directory. Checkpoints from another output directory are rejected; copying a checkpoint into an unrelated existing run is not a supported branching workflow. Keep the selected `best.pt` with its original OCR run.

## Predict and evaluate

```sh
parksight predict path/to/frame.jpg --detector runs/baseline-detector/weights/best.pt \
  --ocr runs/baseline-ocr/best.pt --output runs/prediction.json
parksight evaluate --dataset data/baseline --split test \
  --detector runs/baseline-detector/weights/best.pt --ocr runs/baseline-ocr/best.pt \
  --output runs/baseline-test
```

Use validation results to choose thresholds before evaluating the test partition. Prediction returns zero or one plate with text, pixel box, detector score, and OCR score. An empty OCR string remains empty. OCR confidence is an uncalibrated geometric mean of emitted-character probabilities; it is not the probability the whole string is correct.

Evaluation saves JSON metrics, per-image predictions, a visual prediction sheet, and a Markdown report. It reports detector precision/recall and mAP, ground-truth-crop OCR exact-string accuracy and character error rate, end-to-end exact-string accuracy, negative-frame false-positive rate, and breakdowns by style, scene, size, and difficulty. End-to-end matches require IoU >= 0.5; missed or misplaced detections count as failures. Character error rate is edit distance divided by ground-truth character count. Metrics with no applicable samples are null.

Latency measures warmed batch-one inference, includes preprocessing/postprocessing, synchronizes GPU work, and excludes disk reads. Reports include median, p95, device, resolution, warm-up, and sample count. Mac latency does not establish UNO Q performance.

### Real webcam validation

Capture the printed plates with the intended camera, distance, and lighting. Include empty frames. Keep photographs reserved for final testing separate from any adaptation/training images. Create `data/real/test.jsonl` with image paths relative to that file:

```json
{"image":"frame001.jpg","text":"ABC1234","bbox":[120,180,380,310],"scene":"indoor","style":"WI"}
{"image":"empty001.jpg","text":"","bbox":null,"scene":"indoor"}
```

```sh
parksight evaluate --dataset data/real --real-manifest data/real/test.jsonl \
  --detector runs/baseline-detector/weights/best.pt --ocr runs/baseline-ocr/best.pt \
  --output runs/real-test
```

Real evaluation is reported separately and needs ground-truth boxes for positive frames. Detector mAP is currently computed for the generated YOLO dataset; the external JSONL evaluation reports IoU-matched recall and end-to-end metrics instead.

### Add the Unidata dataset later

The user-supplied [Databricks Marketplace listing](https://marketplace.databricks.com/details/a1776113-4df3-4ce7-bf0c-05735cad8434/Unidata_Car-License-Plate-Detection-Dataset-3-809-704-Images-for-Plate-Detection-and-OCR) is a possible real-image source. It is not downloaded or included in the current run. The [provider](https://unidata.pro/datasets/car-license-plates-ocr-image/) describes full access as commercial and offers samples. Confirm the actual Marketplace entitlement and its terms before export; the public listing is not evidence that the full corpus is freely downloadable.

After obtaining access, export a modest U.S. subset plus the original annotation/schema documentation. Inspect whether coordinates describe full-scene boxes, polygons, or already-cropped plates. Convert verified full scenes into the external JSONL schema above for separate validation. Already-cropped images can evaluate OCR using a box covering the complete crop, but their detection scores are not a full-scene detection benchmark. Do not guess CSV column meanings or coordinate conventions.

Before any real-data training, split by plate identity and source video/session to keep neighboring frames and repeated vehicles out of validation/test. Preserve the original source/license metadata, retain a final untouched real holdout, and keep image data out of this repository. A training-data adapter should be written against the actual exported schema, not the marketing page. Integration remains pending access to that schema/data; synthetic-only training is the current user-approved scope.

## Checks and limits

```sh
pytest -q
ruff check src tests
ruff format --check src tests
```

Synthetic data is a baseline, not evidence of production LPR accuracy. Printed plates matching the supplied renderer are the intended controlled demo. Exact state artwork, arbitrary multi-line plates, strong clipping/occlusion, multiple readable plates per frame, and unconstrained traffic scenes are outside this baseline. Real-camera validation is required before claiming demo accuracy.

UNO Q runtime/acceleration, live webcam streaming, whitelist checks, occupancy sensors, and Databricks event ingestion are later work. No ONNX export or UNO Q deployment is claimed unless separately verified and documented in the run report.

### LPLCv2 review status

The user also suggested [LPLCv2](https://github.com/UFPR-IPASP-PR/LPLCv2-Dataset). Only its public documentation has been reviewed; no images or annotations were downloaded or used. The repository requires an application and states applicant-only academic research use, excluding commercial use. The [paper](https://arxiv.org/html/2604.08741v2) describes Brazilian traffic-radar imagery from Paraná. It is a potential later robustness benchmark, rather than a direct U.S.-plate validation set. Ask the user again before using it for either training or validation.
