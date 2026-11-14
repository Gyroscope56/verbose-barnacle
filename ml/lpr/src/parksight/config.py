import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    seed: int = 42
    scenes: int = 10_000
    crops: int = 30_000
    width: int = 640
    height: int = 480
    min_length: int = 5
    max_length: int = 8
    negative_fraction: float = 0.08
    hard_fraction: float = 0.2
    min_scale: float = 0.24
    max_scale: float = 0.6
    perspective: float = 0.09
    jpeg_min: int = 55
    assets: str = "assets"
    background_manifest: str = ""
    device: str = "auto"
    detector_epochs: int = 12
    detector_batch: int = 16
    detector_size: int = 640
    detector_hours: float = 1.5
    ocr_epochs: int = 20
    ocr_batch: int = 128
    ocr_minutes: float = 90
    learning_rate: float = 0.001
    workers: int = 0

    def __post_init__(self):
        if self.scenes < 20 or self.crops < self.scenes:
            raise ValueError("Use at least 20 scenes and crops >= scenes")
        if self.width < 160 or self.height < 120:
            raise ValueError("Images must be at least 160 x 120")
        if not 5 <= self.min_length <= self.max_length <= 8:
            raise ValueError("Text lengths must be within 5..8")
        if not 0 <= self.negative_fraction < 0.5 or not 0 <= self.hard_fraction <= 1:
            raise ValueError("Invalid negative or hard fraction")
        if not 0 < self.min_scale <= self.max_scale < 0.9:
            raise ValueError("Invalid plate scale")
        if not 0 <= self.perspective < 0.2 or not 20 <= self.jpeg_min <= 100:
            raise ValueError("Invalid perspective or JPEG range")
        if min(self.detector_epochs, self.ocr_epochs, self.detector_batch, self.ocr_batch) < 1:
            raise ValueError("Training epochs and batches must be positive")
        if min(self.detector_hours, self.ocr_minutes, self.learning_rate) <= 0:
            raise ValueError("Training time limits and learning rate must be positive")
        if self.workers < 0 or self.detector_size < 160 or self.detector_size % 32:
            raise ValueError("Invalid workers or detector image size")
        if self.device not in ("auto", "cpu", "mps", "cuda"):
            raise ValueError("Device must be auto, cpu, mps, or cuda")

    def to_dict(self):
        return asdict(self)


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        return Config(**tomllib.load(stream))
