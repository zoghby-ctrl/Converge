"""Safe JPEG/PNG ingestion and metadata-free normalization."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .image_contract import NORMALIZATION_VERSION

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_LONG_EDGE = 1280


class ImageIngestionError(ValueError):
    """Safe, user-facing validation failure with no decoder internals."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dhash(image: Image.Image) -> str:
    """Small perceptual near-duplicate flag; never used as exact identity."""
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data())
    bits = [pixels[row * 9 + col] > pixels[row * 9 + col + 1]
            for row in range(8) for col in range(8)]
    return f"{int(''.join('1' if bit else '0' for bit in bits), 2):016x}"


def _save_clean(image: Image.Image, path: Path, image_format: str) -> bytes:
    buffer = BytesIO()
    if image_format == "JPEG":
        image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=92, optimize=True, exif=b"")
    else:
        # Rebuild pixels into a fresh image so EXIF/ICC/text entries from a
        # decoder object cannot be carried into the persisted PNG.
        mode = "RGBA" if image.mode in ("RGBA", "LA") else "RGB"
        clean = Image.new(mode, image.size)
        clean.paste(image.convert(mode))
        clean.save(buffer, format="PNG", optimize=True)
    data = buffer.getvalue()
    path.write_bytes(data)
    return data


def normalize_image(raw: bytes, runtime_dir: Path) -> dict:
    """Validate an upload and persist orientation-correct, metadata-free copies.

    ``raw_hash`` identifies the exact upload for duplicate detection.  The
    provider receives only the normalized copy, never the original bytes.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ImageIngestionError("empty_image")
    raw = bytes(raw)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageIngestionError("image_too_large")
    raw_hash = _sha256(raw)
    try:
        with Image.open(BytesIO(raw)) as probe:
            image_format = (probe.format or "").upper()
            if image_format not in {"JPEG", "PNG"}:
                raise ImageIngestionError("unsupported_image_format")
            # verify() forces the decoder to inspect the complete payload.
            probe.verify()
        with Image.open(BytesIO(raw)) as source:
            if getattr(source, "n_frames", 1) != 1:
                raise ImageIngestionError("animated_image_not_supported")
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise ImageIngestionError("image_pixel_limit")
            image = ImageOps.exif_transpose(source)
            # Materialize pixels before closing the untrusted input stream.
            image.load()
            image = image.copy()
    except ImageIngestionError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise ImageIngestionError("invalid_image") from None

    runtime_dir = Path(runtime_dir)
    image_dir = runtime_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".jpg" if image_format == "JPEG" else ".png"
    preserved_path = image_dir / f"{raw_hash}.source{suffix}"
    normalized_path = image_dir / f"{raw_hash}.normalized{suffix}"
    preserved = _save_clean(image, preserved_path, image_format)

    scale = min(1.0, MAX_LONG_EDGE / max(image.size))
    normalized = image
    if scale < 1:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        normalized = image.resize(size, Image.Resampling.LANCZOS)
    normalized_bytes = _save_clean(normalized, normalized_path, image_format)
    return {
        "raw_hash": raw_hash,
        "stored_path": str(normalized_path),
        "normalized_hash": _sha256(normalized_bytes),
        "normalization_version": NORMALIZATION_VERSION,
        "width": normalized.width,
        "height": normalized.height,
        "format": image_format,
        "preserved_path": str(preserved_path),
        "preserved_hash": _sha256(preserved),
        "original_width": width,
        "original_height": height,
        "perceptual_hash": _dhash(normalized),
    }
