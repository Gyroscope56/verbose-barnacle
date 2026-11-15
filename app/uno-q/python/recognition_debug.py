"""Save a self-contained view of the last recognition attempt."""

from base64 import b64encode
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2


def _image_section(title, frame):
    if frame is None:
        return f"<section><h2>{title}</h2><p>No image for this frame.</p></section>"
    encoded, png = cv2.imencode(".png", frame)
    if not encoded:
        raise OSError(f"Could not encode {title}")
    height, width = frame.shape[:2]
    image = b64encode(png.tobytes()).decode("ascii")
    return (
        f"<section><h2>{title}</h2><p>{width} × {height} pixels</p>"
        f'<img alt="{title}" src="data:image/png;base64,{image}"></section>'
    )


def save_debug_report(
    path, frame, ocr_input, notes, threshold, elapsed, *, decision, frame_number, plate_crop
):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = "".join(f"<li>{escape(note)}</li>" for note in notes)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ParkSight recognition debug</title>
<style>
body {{ background: #111b22; color: #e7eff5; font: 16px system-ui, sans-serif;
       line-height: 1.5; max-width: 820px; margin: 2rem auto; padding: 0 1rem; }}
a {{ color: #8ee1d5; }} h2 {{ margin-bottom: 0; }}
img {{ display: block; max-width: 100%; height: auto; }}
</style></head><body>
<a href="/">Back to dashboard</a>
<h1>Latest recognition attempt</h1>
<p><time datetime="{timestamp}">{timestamp}</time> · {elapsed:.2f} s · Detector threshold {threshold:.2f}</p>
<p><strong>{escape(decision)}</strong></p>
<h2>Frame results</h2>
<ol>{rows}</ol>
{_image_section(f"Selected camera frame {frame_number}", frame)}
{_image_section("Plate crop before resizing", plate_crop)}
{_image_section("OCR input for that frame", ocr_input)}
</body></html>"""

    # Replace the report in one step so a dashboard request sees a complete attempt.
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temporary_path = Path(temp.name)
        try:
            temp.write(page)
            temp.close()
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
