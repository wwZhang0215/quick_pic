from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import exifread

logger = logging.getLogger(__name__)

_EXIF_DATE_TAGS = [
    "EXIF DateTimeOriginal",
    "EXIF DateTimeDigitized",
    "Image DateTime",
]
_EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


def read_capture_date(file_path: str) -> datetime | None:
    """Return the capture datetime from EXIF, or None if unavailable."""
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        with open(file_path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)

        for tag_name in _EXIF_DATE_TAGS:
            tag = tags.get(tag_name)
            if tag is not None:
                raw_value = str(tag).strip()
                if raw_value and raw_value != "0000:00:00 00:00:00":
                    try:
                        return datetime.strptime(raw_value, _EXIF_DATE_FORMAT)
                    except ValueError:
                        logger.debug("Unparseable EXIF date '%s' in %s", raw_value, file_path)

    except Exception as exc:
        logger.debug("Could not read EXIF from %s: %s", file_path, exc)

    return None
