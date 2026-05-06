from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported RAW extensions (lowercase)
RAW_EXTENSIONS = frozenset({
    ".arw", ".cr2", ".cr3", ".nef", ".nrw", ".dng",
    ".orf", ".rw2", ".raf", ".pef", ".srw", ".x3f",
    ".3fr", ".mef", ".erf",
})

JPG_EXTENSIONS = frozenset({".jpg", ".jpeg"})


def is_raw(path: str) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def is_jpg(path: str) -> bool:
    return Path(path).suffix.lower() in JPG_EXTENSIONS


def extract_raw_thumbnail(raw_path: str) -> bytes | None:
    """
    Extract the embedded JPEG thumbnail from a RAW file using rawpy.
    Returns JPEG bytes, or None if extraction fails.
    """
    try:
        import rawpy  # type: ignore

        with rawpy.imread(raw_path) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                return thumb.data  # already JPEG bytes
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                # Convert bitmap to JPEG via imageio
                import imageio  # type: ignore
                import io
                buf = io.BytesIO()
                imageio.imwrite(buf, thumb.data, format="jpeg")
                return buf.getvalue()
    except Exception as exc:
        logger.debug("Could not extract thumbnail from %s: %s", raw_path, exc)
    return None


def get_display_bytes(display_path: str) -> bytes | None:
    """
    Return raw bytes suitable for display.
    For JPG: reads file bytes directly.
    For RAW: extracts embedded thumbnail.
    """
    path = Path(display_path)
    if not path.exists():
        return None

    suffix = path.suffix.lower()
    if suffix in JPG_EXTENSIONS:
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", display_path, exc)
            return None

    if suffix in RAW_EXTENSIONS:
        return extract_raw_thumbnail(display_path)

    # Unknown format — attempt direct read
    try:
        return path.read_bytes()
    except OSError:
        return None
