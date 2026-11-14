import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

STYLES = {
    "WI": ("WISCONSIN", (246, 242, 225), (33, 46, 36), (175, 30, 42), "America’s Dairyland"),
    "IL": ("ILLINOIS", (232, 240, 247), (25, 48, 87), (48, 99, 153), "Land of Lincoln"),
    "MN": ("MINNESOTA", (237, 244, 245), (20, 51, 91), (31, 112, 146), "10,000 Lakes"),
}


def box_from_corners(corners: np.ndarray, width: int, height: int) -> list[int]:
    low = np.floor(corners.min(axis=0)).astype(int)
    high = np.ceil(corners.max(axis=0)).astype(int)
    return [
        int(np.clip(low[0], 0, width)),
        int(np.clip(low[1], 0, height)),
        int(np.clip(high[0], 0, width)),
        int(np.clip(high[1], 0, height)),
    ]


def render_plate(text: str, style: str, fonts: list[Path], rng: np.random.Generator) -> Image.Image:
    if not 5 <= len(text) <= 8 or any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in text
    ):
        raise ValueError("Plate text must contain 5-8 uppercase ASCII letters/digits")
    name, base, ink, accent, slogan = STYLES[style]
    plate = Image.new("RGB", (480, 240), base)
    draw = ImageDraw.Draw(plate)
    font_path = str(fonts[int(rng.integers(len(fonts)))])
    header = ImageFont.truetype(font_path, 31)
    small = ImageFont.truetype(font_path, 20)
    draw.rounded_rectangle((3, 3, 476, 236), radius=13, outline=(95, 95, 90), width=4)
    draw.rectangle((9, 9, 470, 57), fill=accent)
    draw.text((240, 32), name, font=header, fill="white", anchor="mm")
    if style == "IL":
        draw.line((20, 180, 460, 180), fill=accent, width=4)
    elif style == "MN":
        draw.polygon(
            [(15, 190), (90, 175), (200, 191), (310, 177), (465, 190), (465, 198), (15, 198)],
            fill=(120, 184, 194),
        )
    else:
        draw.line((18, 185, 462, 185), fill=accent, width=3)
    draw.text((240, 214), slogan, font=small, fill=accent, anchor="mm")
    # Fit the entire string; do not stretch individual glyphs or alter their labels.
    text_font = ImageFont.truetype(font_path, 105)
    gap = float(rng.uniform(2, 7))
    widths = [draw.textlength(c, font=text_font) for c in text]
    total = sum(widths) + gap * (len(text) - 1)
    if total > 425:
        text_font = ImageFont.truetype(font_path, int(105 * 425 / total))
        widths = [draw.textlength(c, font=text_font) for c in text]
        total = sum(widths) + gap * (len(text) - 1)
    x = (480 - total) / 2
    for char, char_width in zip(text, widths):
        draw.text((x, 123), char, font=text_font, fill=ink, anchor="lm", stroke_width=0)
        x += char_width + gap
    for x in (45, 435):
        draw.ellipse((x - 4, 66, x + 4, 74), fill=(115, 115, 110))
    return plate


def scene_background(width: int, height: int, kind: str, rng, photo: Path | None = None):
    if photo:
        with Image.open(photo) as image:
            return ImageOps.fit(image.convert("RGB"), (width, height))
    color = rng.integers(60, 215, 3)
    canvas = np.broadcast_to(color, (height, width, 3)).astype(np.float32).copy()
    canvas += rng.normal(0, 3, canvas.shape)
    canvas *= np.linspace(0.8, 1.08, height)[:, None, None]
    image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    if kind == "vehicle":
        draw.rectangle((0, height * 0.68, width, height), fill=(63, 64, 62))
        body = tuple(int(c) for c in rng.integers(25, 220, 3))
        draw.rounded_rectangle(
            (int(width * 0.08), int(height * 0.15), int(width * 0.92), int(height * 0.86)),
            radius=int(width * 0.08),
            fill=body,
            outline=(45, 45, 45),
            width=3,
        )
        draw.polygon(
            [
                (width * 0.24, height * 0.17),
                (width * 0.76, height * 0.17),
                (width * 0.85, height * 0.36),
                (width * 0.15, height * 0.36),
            ],
            fill=(52, 64, 74),
        )
        for left, right in ((0.1, 0.26), (0.74, 0.9)):
            draw.rounded_rectangle(
                (int(width * left), int(height * 0.45), int(width * right), int(height * 0.55)),
                radius=5,
                fill=(182, 32, 35),
            )
        draw.line(
            (width * 0.1, height * 0.78, width * 0.9, height * 0.78), fill=(35, 35, 35), width=9
        )
    else:
        horizon = int(height * rng.uniform(0.55, 0.8))
        draw.rectangle(
            (0, horizon, width, height), fill=tuple(int(c) for c in rng.integers(65, 185, 3))
        )
        for _ in range(int(rng.integers(2, 7))):
            x, y = rng.integers(0, width), rng.integers(0, max(1, horizon - 30))
            draw.rectangle(
                (
                    int(x),
                    int(y),
                    int(min(width, x + width * 0.12)),
                    int(min(horizon, y + height * 0.18)),
                ),
                fill=tuple(int(c) for c in rng.integers(40, 210, 3)),
            )
    return image


def compose_scene(plate, cfg, rng, kind: str, hard: bool, photo=None):
    image = scene_background(cfg.width, cfg.height, kind, rng, photo)
    corners = None
    if plate is not None:
        w = cfg.width * rng.uniform(cfg.min_scale, cfg.max_scale)
        h = w * 0.5 * rng.uniform(0.88, 1.08)
        x = rng.uniform(0.08 * cfg.width, cfg.width - w - 0.06 * cfg.width)
        y = (
            rng.uniform(
                0.36 * cfg.height, min(0.72 * cfg.height, cfg.height - h - 0.05 * cfg.height)
            )
            if kind == "vehicle"
            else rng.uniform(0.12 * cfg.height, cfg.height - h - 0.08 * cfg.height)
        )
        corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32)
        amount = cfg.perspective * (1 if hard else 0.45)
        corners += rng.uniform(-1, 1, (4, 2)).astype(np.float32) * np.array([w, h]) * amount
        corners[:, 0] = np.clip(corners[:, 0], 1, cfg.width - 2)
        corners[:, 1] = np.clip(corners[:, 1], 1, cfg.height - 2)
        source = np.array([[0, 0], [479, 0], [479, 239], [0, 239]], np.float32)
        transform = cv2.getPerspectiveTransform(source, corners)
        warped = cv2.warpPerspective(np.array(plate), transform, (cfg.width, cfg.height))
        mask = cv2.warpPerspective(
            np.full((240, 480), 255, np.uint8), transform, (cfg.width, cfg.height)
        )
        background = np.array(image)
        alpha = mask[..., None].astype(np.float32) / 255
        image = Image.fromarray((warped * alpha + background * (1 - alpha)).astype(np.uint8))
    image, effects = degrade(image, rng, hard, cfg.jpeg_min)
    return image, corners, effects


def degrade(image, rng, hard: bool, jpeg_min: int):
    array = np.array(image).astype(np.float32)
    height, width = array.shape[:2]
    exposure = float(rng.uniform(0.35, 1.3) if hard else rng.uniform(0.8, 1.15))
    array *= exposure
    if rng.random() < 0.4:
        shadow = np.linspace(rng.uniform(0.45, 0.85), 1, width)
        array *= shadow[None, :, None]
    glare = bool(rng.random() < (0.4 if hard else 0.12))
    if glare:
        xx = np.linspace(-1, 1, width)[None, :]
        yy = np.linspace(-1, 1, height)[:, None]
        glow = np.exp(
            -((xx - rng.uniform(-0.8, 0.8)) ** 2 / 0.12 + (yy - rng.uniform(-0.8, 0.8)) ** 2 / 0.3)
        )
        array += glow[..., None] * rng.uniform(20, 65 if hard else 35)
    dirt = int(rng.integers(1, 5)) if hard else 0
    for _ in range(dirt):
        x, y = int(rng.integers(width)), int(rng.integers(height))
        cv2.circle(array, (x, y), int(rng.integers(1, 5)), (70, 63, 54), -1)
    # Narrow foreground stripe models limited occlusion, at most ~1% of frame width.
    occluded = bool(hard and rng.random() < 0.2)
    if occluded:
        x = int(rng.integers(width))
        array[:, x : x + max(1, width // 150)] *= 0.4
    blur = int(rng.choice([0, 0, 3, 5] if hard else [0, 0, 0, 3]))
    if blur:
        if rng.random() < 0.5:
            kernel = np.zeros((blur, blur), np.float32)
            kernel[blur // 2] = 1 / blur
            array = cv2.filter2D(array, -1, kernel)
        else:
            array = cv2.GaussianBlur(array, (blur, blur), 0.5)
    noise = float(rng.uniform(1, 7 if hard else 3))
    array += rng.normal(0, noise, array.shape)
    result = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
    quality = int(rng.integers(jpeg_min if hard else max(80, jpeg_min), 101))
    buffer = io.BytesIO()
    result.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        result = decoded.convert("RGB")
    return result, {
        "exposure": exposure,
        "glare": glare,
        "dirt_spots": dirt,
        "occluded": occluded,
        "blur_kernel": blur,
        "noise_sigma": noise,
        "jpeg_quality": quality,
    }
