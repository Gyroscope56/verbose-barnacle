import argparse
import json
from pathlib import Path

from parksight.config import load_config


def main():
    parser = argparse.ArgumentParser(description="ParkSight synthetic license plate baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    assets = commands.add_parser(
        "assets", help="Download licensed fonts and optional detector weights"
    )
    assets.add_argument("--output", type=Path, default=Path("assets"))
    assets.add_argument("--detector", action="store_true")
    generate = commands.add_parser("generate", help="Generate a new annotated dataset")
    generate.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
    generate.add_argument("--output", type=Path, required=True)
    for name in ("validate-data", "preview"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, required=True)
        if name == "preview":
            command.add_argument("--output", type=Path, required=True)
    printing = commands.add_parser("print-plate")
    printing.add_argument("text")
    printing.add_argument("--style", choices=["WI", "IL", "MN"], default="WI")
    printing.add_argument("--assets", type=Path, default=Path("assets"))
    printing.add_argument("--output", type=Path, required=True)
    for name in ("train-ocr", "train-detector"):
        training = commands.add_parser(name)
        training.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
        training.add_argument("--dataset", type=Path, required=True)
        training.add_argument("--output", type=Path, required=True)
        training.add_argument("--resume", type=Path)
    for name in ("predict", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--detector", type=Path, required=True)
        command.add_argument("--ocr", type=Path, required=True)
        command.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
        command.add_argument("--detector-size", type=int, default=640)
        command.add_argument("--threshold", type=float, default=0.25)
        command.add_argument("--output", type=Path, required=True)
        if name == "predict":
            command.add_argument("image", type=Path)
        else:
            command.add_argument("--dataset", type=Path, required=True)
            command.add_argument("--split", choices=["val", "test"], default="test")
            command.add_argument("--real-manifest", type=Path)
            command.add_argument("--latency-samples", type=int, default=50)
    exporting = commands.add_parser(
        "export", help="Export ONNX models and verify CPU output parity"
    )
    exporting.add_argument("--detector", type=Path, required=True)
    exporting.add_argument("--ocr", type=Path, required=True)
    exporting.add_argument("--dataset", type=Path, required=True)
    exporting.add_argument("--output", type=Path, required=True)
    exporting.add_argument("--detector-size", type=int, default=640)
    args = parser.parse_args()
    try:
        dispatch(args)
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        parser.exit(2, f"Error: {error}\n")


def dispatch(args):
    if args.command == "export":
        from parksight.exporting import export_models

        print(
            json.dumps(
                export_models(
                    args.detector, args.ocr, args.dataset, args.output, args.detector_size
                ),
                indent=2,
            )
        )
    elif args.command == "assets":
        from parksight.assets import download_detector, prepare_assets

        print(json.dumps(prepare_assets(args.output), indent=2))
        if args.detector:
            download_detector(args.output)
    elif args.command == "generate":
        from parksight.generate import generate_dataset

        print(generate_dataset(load_config(args.config), args.output))
    elif args.command == "validate-data":
        from parksight.generate import validate_dataset

        print(json.dumps(validate_dataset(args.dataset), indent=2))
    elif args.command == "preview":
        from parksight.generate import preview

        preview(args.dataset, args.output)
    elif args.command == "print-plate":
        import numpy as np

        from parksight.assets import font_paths
        from parksight.render import render_plate

        args.output.parent.mkdir(parents=True, exist_ok=True)
        image = render_plate(
            args.text, args.style, font_paths(args.assets), np.random.default_rng(42)
        )
        image.resize((1800, 900)).save(args.output, dpi=(300, 300))
    elif args.command.startswith("train-"):
        from parksight.train import train_detector, train_ocr

        function = train_ocr if args.command == "train-ocr" else train_detector
        print(function(load_config(args.config), args.dataset, args.output, args.resume))
    else:
        from parksight.inference import Pipeline

        pipeline = Pipeline(
            args.detector, args.ocr, args.device, args.detector_size, args.threshold
        )
        if args.command == "predict":
            from PIL import Image

            from parksight.records import write_json

            with Image.open(args.image) as image:
                predictions = pipeline.predict(image.convert("RGB"))
            write_json(args.output, predictions)
            print(json.dumps(predictions, indent=2))
        else:
            from parksight.evaluate import evaluate_dataset

            result = evaluate_dataset(
                pipeline,
                args.dataset,
                args.split,
                args.output,
                args.real_manifest,
                args.latency_samples,
            )
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
