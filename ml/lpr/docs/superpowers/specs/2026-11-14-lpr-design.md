# ParkSight synthetic LPR baseline

## Intent and agreed scope

Build and train a working license plate detection and text recognition baseline within a one-day hackathon budget. Generate most training data programmatically. Read previously unseen plate strings, rather than classify a fixed list of identities. Support one visible plate per frame, printed indoors or mounted on a vehicle, with Wisconsin, Illinois, and Minnesota-inspired layouts.

The first deliverable includes the generator, annotations, local training, evaluation, inference on images, and training artifacts. The user will provide webcam photographs of printed plates later today for separate real-image evaluation. Synthetic results alone cannot establish real-camera accuracy.

Train initially on the inspected Apple M4 Pro Mac with 24 GB unified memory and Python 3.13.6. Keep configuration portable to the user's RTX 5080 desktop with an i7-13700K and 96 GB RAM. Desktop access and software setup are outside this pass.

Success means an operational baseline with measured detection, text recognition, and latency metrics. No numerical accuracy or frame-rate threshold has been agreed. Do not claim real-time UNO Q performance from Mac measurements.

## Approaches considered

1. Compact detector plus purpose-built OCR. The user selected this approach for control over model size and a practical path toward edge deployment. It requires synthetic OCR training and evaluation of errors in each stage.
2. Adapt an existing pretrained OCR pipeline. Considered for reuse and potentially faster recognition setup, but larger models and runtime dependencies complicate later deployment.

Fixed-region recognition and fixed-identity classification were discussed and declined. Detect plates in full frames and read held-out strings.

## Proposed implementation choices for review

These are engineering proposals, not additional user requirements.

- Python package and command-line workflows, configured through checked-in configuration files. Use Pillow/NumPy/OpenCV for rendering and image transforms, PyTorch for OCR, and an Ultralytics YOLO11 nano detector initialized from public pretrained weights. Record dependency versions and random seeds.
- Ultralytics publishes YOLO11 under AGPL-3.0 and enterprise licensing. Document the dependency and model license in asset notices; do not select a license for the user's original code automatically. If those terms do not fit the project, replace the detector choice before implementation.
- Use a compact convolutional sequence recognizer trained with CTC loss, avoiding a large language model or whitelist-based corrections. Normalize text to uppercase A-Z and 0-9; display spaces and separators do not count as characters. Initial printed strings contain 5-8 characters in one line. This is a controlled demo format, not an exhaustive model of each state's registration rules.
- Prefer MPS on this Mac, CUDA on the desktop when available, and CPU as a supported fallback. Verify CTC support in the installed PyTorch version and use an explicit CPU loss path if necessary, retaining gradients and documenting the cost.
- Begin with a small smoke dataset, then a configurable baseline of approximately 10,000 full scenes and 30,000 OCR crops. Use a fixed seed and bounded initial training runs, with checkpoint resume and tunable epochs/batch sizes. Adjust counts and runtime based on measured generation speed, loss, memory, and validation behavior within the day.
- Start detector training at 640 pixels and OCR at 192 by 64 pixels. Preserve character proportions using padding. Record the minimum readable plate size in evaluation rather than implying arbitrary-distance support.

## Synthetic data and annotations

Render state-inspired color schemes and headers, with several licensed font choices and varied text spacing. Include a command to render matching printable demo plates. Designs are simplified and visually recognizable as synthetic examples; they are not exact state artwork reproductions.

Compose plates into indoor scenes and vehicle scenes. Support programmatically drawn vehicle bodies and mounting areas plus licensed photographic backgrounds where available. Assets must have recorded source, license, and attribution. Imported backgrounds must not introduce unlabeled readable plates; reject them or cover existing plates. Keep generation usable with procedural backgrounds if downloads fail, and identify that limitation in the report.

Vary plate placement, vehicle color, background, scale, perspective, exposure, gradients and shadows, glare, night illumination, motion/defocus blur, noise, JPEG quality, dirt, reflections, and limited occlusion. Keep a readable controlled-condition majority and a smaller harder subset; expose augmentation ranges in configuration. Avoid silently assigning clean-readable targets to samples where the text is entirely hidden or clipped.

Export full scene images, OCR crops, and JSONL annotations containing sample ID, split, normalized text, state style, pixel bounding box, projected plate corners, image dimensions, generation seed, source asset IDs, and augmentation metadata. Also export normalized YOLO labels and its dataset configuration. Bounds derive from the final geometric transform and are clipped to the image; validate them against the output dimensions. OCR crops should reflect perspective and photometric degradation from scenes, with crop jitter to approximate detector errors.

Include a small configurable fraction of plate-free scenes with empty detection labels, covering both scene types. Exclude these from OCR training. Evaluate false detections separately.

## Splits and training

Create train/validation/test partitions before rendering. Allocate text identities to exactly one partition and keep repeated variants together. Partition photographic source backgrounds by source asset identity too. All layouts can occur across partitions. Training may augment training images only; held-out evaluation is deterministic. Include adjacent repeated characters in OCR coverage and tests of CTC decoding.

Train the detector and OCR separately. Save last and best validation checkpoints, configuration, character vocabulary, preprocessing parameters, dependency versions, and loss/metric history. Select checkpoints with validation data, then evaluate the selected checkpoints on the test partition without tuning on it.

Keep the initial full training bounded by configured epochs and elapsed time; report completed epochs and metrics even if a run stops at its budget. An interrupted or unsuccessful run must be reported honestly rather than described as trained successfully. Retain resumable checkpoints.

## Inference and confidence

Detect the plate, pad and clip its crop, apply saved OCR preprocessing, and decode character probabilities using CTC greedy decoding. Return text, pixel box, detector score, and OCR score. Return an empty detection result if no plate passes the configured detection threshold. Do not force an output from a blank OCR prediction.

Define the OCR score explicitly as an aggregate of decoded-character probabilities, excluding blanks. It is an uncalibrated model score, not the probability that the complete string is correct. Report detector and OCR scores separately rather than presenting their product as calibrated confidence. No whitelist enters recognition or evaluation.

## Evaluation and artifacts

Report detector precision/recall and mAP, OCR exact-string accuracy and character error rate on ground-truth crops, and end-to-end exact-string accuracy on all positive scenes. Count missed detections as end-to-end failures. Report plate-free false-positive rate and results by scene type, state, plate size, and augmentation difficulty where sample counts permit.

Measure warmed batch-one end-to-end latency with device synchronization where required, including preprocessing and postprocessing. Report median and p95, device, input resolution, sample count, and whether file I/O is excluded. Separate recognition accuracy from latency measurements.

Provide preview contact sheets, example predictions including failures, a machine-readable metrics file, and a concise training report. Add a documented local folder/JSONL format for user-captured validation images. Report real images separately, and avoid tuning on any images reserved as a final real test set. Missing user images leave real-camera evaluation pending without blocking the synthetic baseline.

## Boundaries and future deployment

UNO Q deployment, actual hardware acceleration, live webcam streaming, whitelist management, occupancy sensors, and Databricks integration are outside this first pass. Prepare model/preprocessing metadata and, if time permits, a verified ONNX export with output parity checks on representative images. Export is useful preparation, not a claim that deployment or acceleration has been validated.

The UNO Q runs Debian on a Qualcomm QRB2210 processor with an Adreno GPU. Do not assume VENTUNO Q NPU documentation applies to UNO Q. Later deployment work must verify the board's exact software stack and supported accelerator operators. CPU inference is the initial runtime compatibility reference, not a performance guarantee.

## Verification and maintenance

Keep functions focused and configuration explicit. Test geometry/label alignment, valid crop handling, non-overlapping text identities and background sources across splits, deterministic generation, repeated-character decoding, empty prediction behavior, and metric handling of missed detections. Run a real generation preview and a short optimization pass before the full training run. Inspect previews to catch distorted text and incorrect boxes. Keep generated data, weights, and runs out of Git; preserve existing staged IDE files.

## References

- Arduino UNO Q: https://www.arduino.cc/product-uno-q
- Ultralytics YOLO11 models and licensing: https://docs.ultralytics.com/models/yolo11/
- PyTorch CTC loss: https://docs.pytorch.org/docs/stable/generated/torch.nn.CTCLoss.html
- PyTorch MPS backend: https://docs.pytorch.org/docs/main/notes/mps.html

## Review status

Approved by the user on 2026-11-14. Proceed with implementation planning.
