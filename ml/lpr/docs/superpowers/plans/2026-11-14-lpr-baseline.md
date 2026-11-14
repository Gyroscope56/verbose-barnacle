# ParkSight LPR Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Generate labeled synthetic U.S.-style plate scenes, train a detector and compact OCR on this Mac, and report reproducible baseline results.

**Architecture:** Deterministic rendering produces scene images, transformed plate crops, JSONL records, and YOLO labels. A pretrained nano detector and a convolutional CTC recognizer train independently, then share one image-inference and evaluation path.

**Tech Stack:** Python, Pillow, NumPy, OpenCV, PyTorch, Ultralytics YOLO11 nano, pytest; optional ONNX export after the baseline works.

**Spec:** `docs/superpowers/specs/2026-11-14-lpr-design.md`

## Global constraints

- Train initially on the inspected Apple M4 Pro Mac with 24 GB unified memory and Python 3.13.6.
- Read previously unseen plate strings, rather than classify a fixed list of identities.
- Support one visible plate per frame, printed indoors or mounted on a vehicle, with Wisconsin, Illinois, and Minnesota-inspired layouts.
- Initial printed strings contain 5-8 characters in one line.
- Start detector training at 640 pixels and OCR at 192 by 64 pixels. Preserve character proportions using padding.
- Do not claim real-time UNO Q performance from Mac measurements.
- Keep generated data, weights, and runs out of Git; preserve existing staged IDE files.
- UNO Q deployment, actual hardware acceleration, live webcam streaming, whitelist management, occupancy sensors, and Databricks integration are outside this first pass.
- No numerical accuracy or frame-rate threshold has been agreed. Synthetic results alone cannot establish real-camera accuracy.

## Review focus

- Repeated characters and all-blank OCR output must decode correctly; test in Task 3.
- Plate-free frames must produce empty labels and remain in false-positive evaluation; test in Tasks 2 and 4.
- Missing downloads, unreadable images, and interrupted runs must have explicit errors or documented fallbacks without invalid completed artifacts; test in Tasks 1, 3, and 4.
- Perspective warps and crop jitter must preserve correct scene boxes and valid nonempty crops; test in Task 2.
- Resume and reuse must not mix incompatible vocabularies, preprocessing, data splits, or configurations; test in Tasks 2 and 3.

## File responsibilities

- `pyproject.toml`, `.gitignore`: package dependencies, CLI entry point, generated artifact exclusions.
- `configs/baseline.toml`, `configs/smoke.toml`: reproducible dataset and training budgets.
- `src/parksight/config.py`, `records.py`: validated configuration and serialized sample schema.
- `src/parksight/assets.py`: licensed font/background acquisition, manifests, and fallback policy.
- `src/parksight/render.py`, `generate.py`: plate drawing, scene composition, augmentations, partitions, and annotations.
- `src/parksight/ocr.py`: model, vocabulary, image preprocessing, CTC decoding, and crop dataset.
- `src/parksight/train.py`: detector/OCR training, device selection, checkpoints, and provenance.
- `src/parksight/inference.py`, `evaluate.py`: shared prediction, accuracy metrics, synchronized latency, and reports.
- `src/parksight/cli.py`: commands for assets, generation, printing, training, prediction, and evaluation.
- `tests/`: focused geometry, split, decoding, metrics, and checkpoint tests.
- `README.md`, `ASSETS.md`: commands, licenses, data contracts, measured results, and limitations.

### Task 1: Configuration and reproducible asset setup

**Files:** Create package metadata, ignore rules, both TOML configurations, `config.py`, `records.py`, `assets.py`, CLI skeleton, `ASSETS.md`, and `tests/test_config_assets.py`.

**Interfaces:** `load_config(path: Path) -> Config`; `prepare_assets(root: Path) -> list[Asset]`; `Sample` includes paths, split, text, style, bbox, corners, image size, seed, source IDs, and augmentation metadata. Paths in records are relative to the dataset root. Asset manifests record source URL, license, attribution, and source identity.

- [x] Write tests rejecting invalid split fractions, nonpositive image dimensions, invalid text lengths, and incompatible existing output manifests; assert failed downloads cannot leave an asset marked ready.
- [x] Run `.venv/bin/python -m pytest tests/test_config_assets.py -q` and confirm the tests fail before implementation.
- [x] Implement configuration/schema boundaries and asset setup. Download redistributable fonts with license files. Support licensed background imports with an explicit plate-free/covered confirmation in their manifest; procedural scenes remain the fallback if no suitable photographs are available. Do not automatically trust arbitrary images as plate-free.
- [x] Install the package in the existing virtual environment using workspace-local package caches. Verify imports, MPS availability, and dependency versions. Lock the actual working environment to a reproducibility file after installation succeeds.
- [x] Run the tests and CLI help; require passing validation and explicit asset status.

### Task 2: Generator, labels, previews, and printable plates

**Files:** Create `render.py`, `generate.py`, `tests/test_generation.py`; extend CLI with `generate`, `validate-data`, `preview`, and `print-plate`.

**Interfaces:** `render_plate(text: str, style: str, assets: list[Asset], rng: Generator) -> Image`; `generate_dataset(config: Config, output: Path) -> Path`; `validate_dataset(root: Path) -> dict`. Generation writes separate scene and crop JSONL manifests, image files, YOLO labels, dataset YAML, provenance, and a preview sheet.

- [x] Write geometry tests using a known quadrilateral and image dimensions; require all box coordinates to be clipped and enclose the projected corners. Test deterministic regeneration, split-disjoint text/source identities, empty negative labels, nonempty crop jitter, and rejection of incompatible output reuse.
- [x] Run `pytest tests/test_generation.py -q` and confirm failure before adding the generator.
- [x] Implement state-inspired layouts, varied licensed fonts and spacing, indoor and procedural vehicle scenes, plate-free negatives, and transformed placement. Apply lighting, shadows, glare, night exposure, perspective, blur, dirt, limited occlusion, noise, and JPEG degradation with recorded severity parameters. Generate crops from the degraded scene, preserving character aspect ratio at OCR preprocessing time.
- [x] Partition text and imported background identity before rendering, using fixed train/validation/test proportions of 80/10/10. Allocate approximately 10,000 baseline scenes plus 30,000 total OCR examples, counting scene crops toward that total. Generate extra crop examples with matching geometry/photometric distributions. Smoke configuration uses small counts and short epochs.
- [x] Implement streaming output with an incomplete marker until generation and validation succeed; refuse accidental overwrite of complete datasets. Export pixel boxes and YOLO normalized labels from the same geometry.
- [x] Run tests, generate the smoke dataset, validate every record, and visually inspect the preview and printable samples before full generation.

### Task 3: Compact OCR and training workflows

**Files:** Create `ocr.py`, `train.py`, `tests/test_ocr.py`, `tests/test_training.py`; extend CLI with detector and OCR training commands.

**Interfaces:** `PlateRecognizer` maps `B x 3 x 64 x 192` images to sequence logits over a saved 37-token vocabulary including blank; `decode_ctc(logits: Tensor) -> list[tuple[str, float]]`; `train_ocr(config: Config, dataset: Path, output: Path, resume: Path | None) -> Path`; `train_detector(...) -> Path`. Save all preprocessing and vocabulary metadata with the checkpoint.

- [x] Test that A/blank/A decodes to AA, consecutive A/A collapses to A, an all-blank prediction returns empty text and zero score, and confidence excludes blank timesteps. Test aspect-preserving input padding and known character-error examples.
- [x] Test resume compatibility checks and a CPU forward/backward step with finite CTC loss including repeated target characters. Confirm tests fail before implementation.
- [x] Implement the small convolutional sequence model, dataset loading, normalized uppercase vocabulary, CTC decoding, and OCR probability aggregation. Select CUDA/MPS/CPU explicitly, probe CTC backward support, and use differentiable CPU loss if required. Expose device choice rather than silently changing the requested device.
- [x] Implement deterministic OCR training with validation-only checkpoint selection, best/last checkpoints, optimizer state, completed epoch, data/config hashes, seed, versions, history, and epoch/time limits. On interruption save resumable state and mark the run interrupted. Validate compatibility before resuming.
- [x] Wrap YOLO11 nano fine-tuning with explicit single plate class, image size, batch size, seed, output location, time/epoch budget, resume behavior, and saved resolved configuration. Restrict detector augmentations that would invalidate OCR evaluation; OCR training uses its own crops.
- [x] Run the tests, then a genuine short detector and OCR optimization on smoke data. Require finite losses and usable reloadable checkpoints before full generation and training.

### Task 4: Shared inference and honest evaluation

**Files:** Create `inference.py`, `evaluate.py`, `tests/test_evaluation.py`; extend CLI with `predict` and `evaluate`.

**Interfaces:** `Pipeline.predict(image: Image) -> list[Prediction]` returns at most one selected plate with text, box, detector score, and uncalibrated OCR score. `evaluate_dataset(pipeline: Pipeline, root: Path, split: str, output: Path) -> dict` writes metrics, predictions, and visual examples. Accept external JSONL image/text/bbox records for separate real-image evaluation.

- [x] Test that a missed detection lowers end-to-end exact-text accuracy, that a high-confidence wrong-location detection is not matched, and that negative samples contribute only to negative-frame false-positive metrics. Test empty datasets, blank OCR, corrupt images, and clipping of padded detector boxes.
- [x] Run `pytest tests/test_evaluation.py -q`, confirm failure, then implement shared preprocessing/inference and evaluation. Use IoU >= 0.5 for end-to-end localization matching and count every positive scene in the denominator. Compute character error rate with edit distance; keep ground-truth-crop OCR metrics separate from detector-crop recognition.
- [x] Include detector precision/recall and mAP via detector validation, exact-string and character error metrics, negative-frame false-positive rate, and breakdowns by style, scene, size, and difficulty with sample counts. Test split is used only after checkpoint selection.
- [x] Measure warmed batch-one latency on decoded images, synchronize GPU work, include preprocessing/postprocessing, exclude disk I/O explicitly, and record median/p95, resolution, device, warm-up count, and measured sample count.
- [x] Save metrics JSON, per-image predictions, success/failure sheets, and a readable report. Real-camera evaluation remains explicitly pending until user images arrive.

### Task 5: Baseline training, report, and delivery

**Files:** Complete `README.md`, `ASSETS.md`, reproducibility manifest, and the generated local run report. Optional export module only if time remains after baseline verification.

- [ ] Run all focused tests and smoke commands. Inspect the generated preview and prediction sheets; correct invalid labels or unreadable rendering before the larger run.
- [ ] Generate the baseline dataset and train the detector/OCR with bounded initial budgets, monitoring elapsed time, memory, losses, and validation. Adjust runtime/counts only as permitted by the design; record every resolved value. Do not tune against held-out test scores.
- [ ] Reload selected checkpoints and evaluate the held-out synthetic test partition. Report completed epochs, actual dataset sizes, metrics, Mac latency, and procedural-versus-photographic background coverage. Preserve an unsuccessful baseline as a measured result rather than claiming an accuracy target was met.
- [ ] Document installation, generation, printing, training/resume, image prediction, evaluation, real capture annotation format, and RTX CUDA setup requirements. Include synthetic-domain and confidence-score limitations and the AGPL/model asset notices.
- [ ] If time permits, export both models to ONNX and compare logits/boxes on representative real generated inputs before documenting export as verified. Do not imply UNO Q deployment is tested.
- [ ] Run final tests, `git diff --check`, CLI examples, and a fresh image-inference command against saved artifacts. Review the final patch for scope and maintainability, leaving existing staged IDE files untouched. Do not create commits unless requested by the user.

## Execution status

Native execution selected by the user. Tasks 1-4 completed with real generation, MPS smoke training, image prediction, and evaluation. Final training, reporting, and requested repository migration are in progress. Independent review found two resume provenance issues; both were fixed with regression tests. Current suite: 24 passing tests.
