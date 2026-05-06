from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MarkType(str, Enum):
    NONE = "none"
    KEEP = "keep"
    FOLDER_KEY = "folder_key"


@dataclass
class PhotoPair:
    """Represents a logical photo unit — a JPG, RAW, or a paired JPG+RAW."""

    stem: str                        # filename without extension, e.g. "IMG_001"
    folder: str                      # source folder (absolute path)
    jpg_path: str | None = None
    raw_path: str | None = None      # .arw, .cr2, .cr3, .nef, .dng, etc.
    capture_date: datetime | None = None

    # Mark state (kept in sync with DB)
    mark_type: MarkType = MarkType.NONE
    folder_key: int | None = None    # 1-9 when mark_type is FOLDER_KEY

    @property
    def display_path(self) -> str:
        """Return the path to display — prefer JPG for speed."""
        return self.jpg_path or self.raw_path  # type: ignore[return-value]

    @property
    def pair_id(self) -> str:
        """Stable identifier used as the database primary key."""
        return f"{self.folder}::{self.stem}"

    @property
    def is_marked(self) -> bool:
        return self.mark_type != MarkType.NONE

    @property
    def has_raw(self) -> bool:
        return self.raw_path is not None

    @property
    def has_jpg(self) -> bool:
        return self.jpg_path is not None

    def sort_key(self) -> tuple:
        """Sort by capture date, then by stem for stability."""
        if self.capture_date is not None:
            return (0, self.capture_date, self.stem)
        return (1, datetime.min, self.stem)
