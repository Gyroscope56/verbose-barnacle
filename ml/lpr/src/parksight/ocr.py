import math
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import Dataset

from parksight.records import read_records

VOCABULARY = "_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
IMAGE_SIZE = (192, 64)


def preprocess(image: Image.Image) -> torch.Tensor:
    image = image.convert("RGB")
    ratio = min(IMAGE_SIZE[0] / image.width, IMAGE_SIZE[1] / image.height)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    resized = image.resize(size, Image.Resampling.BILINEAR)
    padded = Image.new("RGB", IMAGE_SIZE, "white")
    padded.paste(resized, (0, (IMAGE_SIZE[1] - size[1]) // 2))
    return torch.from_numpy(np.array(padded).copy()).permute(2, 0, 1).float() / 127.5 - 1


class PlateRecognizer(nn.Module):
    def __init__(self):
        super().__init__()
        layers = []
        previous = 3
        for channels, stride in ((32, 2), (64, 2), (96, (2, 1)), (128, (2, 1))):
            layers.extend(
                [
                    nn.Conv2d(previous, channels, 3, stride, 1, bias=False),
                    nn.BatchNorm2d(channels),
                    nn.ReLU(inplace=True),
                ]
            )
            previous = channels
        layers.extend([nn.Conv2d(128, 128, (4, 1)), nn.ReLU(inplace=True)])
        self.encoder = nn.Sequential(*layers)
        self.sequence = nn.Sequential(
            nn.Conv1d(128, 128, 3, padding=1), nn.ReLU(), nn.Conv1d(128, len(VOCABULARY), 1)
        )

    def forward(self, images):
        features = self.encoder(images).squeeze(2)
        return self.sequence(features).transpose(1, 2)


def decode_ctc(logits: torch.Tensor) -> list[tuple[str, float]]:
    probabilities, indices = logits.detach().softmax(-1).max(-1)
    results = []
    for ids, probs in zip(indices.cpu().tolist(), probabilities.cpu().tolist()):
        chars, scores, previous = [], [], 0
        for token, probability in zip(ids, probs):
            if token and token != previous:
                chars.append(VOCABULARY[token])
                scores.append(probability)
            previous = token
        score = (
            math.exp(sum(math.log(max(p, 1e-12)) for p in scores) / len(scores)) if scores else 0.0
        )
        results.append(("".join(chars), score))
    return results


class CropDataset(Dataset):
    def __init__(self, root: Path, split: str):
        self.root = root
        self.rows = [row for row in read_records(root / "crops.jsonl") if row["split"] == split]
        if not self.rows:
            raise ValueError(f"No OCR samples in split {split}")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with Image.open(self.root / row["crop"]) as image:
            tensor = preprocess(image)
        target = torch.tensor([VOCABULARY.index(c) for c in row["text"]], dtype=torch.long)
        return tensor, target, row["text"]


def collate_crops(batch):
    images, targets, texts = zip(*batch)
    return torch.stack(images), torch.cat(targets), torch.tensor([len(t) for t in targets]), texts


def load_recognizer(path: Path, device: str):
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if checkpoint["vocabulary"] != VOCABULARY or checkpoint["image_size"] != list(IMAGE_SIZE):
        raise ValueError("Unsupported OCR vocabulary or preprocessing")
    model = PlateRecognizer()
    model.load_state_dict(checkpoint["model"])
    return model.to(device).eval()
