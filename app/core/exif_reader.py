from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path

import exifread

logger = logging.getLogger(__name__)

_EXIF_DATE_TAGS = [
    "EXIF DateTimeOriginal",
    "EXIF DateTimeDigitized",
    "Image DateTime",
]
_EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


@dataclass
class ExifInfo:
    capture_date: datetime | None = None
    camera: str = ""          # e.g. "Canon EOS R5"
    lens: str = ""            # e.g. "RF 24-70mm F2.8 L IS USM"
    focal_length: str = ""    # e.g. "50mm"
    aperture: str = ""        # e.g. "f/2.8"
    shutter: str = ""         # e.g. "1/250s"
    iso: str = ""             # e.g. "ISO 400"
    width: int | None = None
    height: int | None = None

    def is_empty(self) -> bool:
        return not any([self.camera, self.lens, self.focal_length,
                        self.aperture, self.shutter, self.iso])


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


def read_full_exif(file_path: str) -> ExifInfo:
    """Read common shooting EXIF fields from a photo file."""
    info = ExifInfo()
    path = Path(file_path)
    if not path.exists():
        return info

    try:
        with open(file_path, "rb") as f:
            tags = exifread.process_file(f, details=False)

        # Camera
        make = _str(tags.get("Image Make"))
        model = _str(tags.get("Image Model"))
        if make and model and not model.startswith(make):
            info.camera = f"{make} {model}"
        else:
            info.camera = model or make

        # Lens
        info.lens = (
            _str(tags.get("EXIF LensModel"))
            or _str(tags.get("MakerNote LensType"))
            or ""
        )

        # Focal length
        fl = tags.get("EXIF FocalLength")
        if fl:
            info.focal_length = f"{_ratio_int(fl)}mm"

        # Aperture
        fn = tags.get("EXIF FNumber")
        if fn:
            info.aperture = f"f/{_ratio_float(fn):.1f}"

        # Shutter speed
        et = tags.get("EXIF ExposureTime")
        if et:
            info.shutter = _format_shutter(_ratio_float(et))

        # ISO
        iso = tags.get("EXIF ISOSpeedRatings")
        if iso:
            info.iso = f"ISO {iso}"

        # Dimensions
        w = tags.get("EXIF ExifImageWidth") or tags.get("Image ImageWidth")
        h = tags.get("EXIF ExifImageLength") or tags.get("Image ImageLength")
        if w:
            info.width = int(str(w))
        if h:
            info.height = int(str(h))

        # Date
        for tag_name in _EXIF_DATE_TAGS:
            tag = tags.get(tag_name)
            if tag:
                raw = str(tag).strip()
                if raw and raw != "0000:00:00 00:00:00":
                    try:
                        info.capture_date = datetime.strptime(raw, _EXIF_DATE_FORMAT)
                        break
                    except ValueError:
                        pass

    except Exception as exc:
        logger.debug("Could not read full EXIF from %s: %s", file_path, exc)

    return info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(tag) -> str:
    return str(tag).strip() if tag is not None else ""


def _ratio_float(tag) -> float:
    try:
        val = str(tag)
        if "/" in val:
            num, den = val.split("/")
            return float(num) / float(den)
        return float(val)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _ratio_int(tag) -> int:
    return int(_ratio_float(tag))


def _format_shutter(seconds: float) -> str:
    if seconds <= 0:
        return ""
    if seconds >= 1:
        return f"{seconds:.1f}s" if seconds != int(seconds) else f"{int(seconds)}s"
    # Express as fraction
    frac = Fraction(seconds).limit_denominator(10000)
    return f"1/{frac.denominator}s"
