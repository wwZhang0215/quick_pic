from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable

from app.core.exif_reader import read_capture_date
from app.core.models import PhotoPair
from app.core.thumbnail import JPG_EXTENSIONS, RAW_EXTENSIONS

logger = logging.getLogger(__name__)


def scan_folders(
    folder_paths: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[PhotoPair]:
    """
    Scan one or more folders for photos, pair JPG+RAW by filename stem,
    read EXIF capture dates, and return a list sorted by capture date.

    Args:
        folder_paths: List of absolute folder paths to scan (non-recursive).
        progress_callback: Optional callback(current, total) for progress updates.

    Returns:
        Sorted list of PhotoPair objects.
    """
    # Step 1: Collect all image files
    # key: (folder, stem) -> {'jpg': path, 'raw': path}
    groups: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)

    all_files: list[Path] = []
    for folder in folder_paths:
        p = Path(folder)
        if not p.is_dir():
            logger.warning("Not a directory, skipping: %s", folder)
            continue
        for f in p.iterdir():
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            if suffix in JPG_EXTENSIONS or suffix in RAW_EXTENSIONS:
                all_files.append(f)

    # Step 2: Group by (folder, stem)
    for f in all_files:
        suffix = f.suffix.lower()
        folder_str = str(f.parent)
        stem = f.stem
        key = (folder_str, stem)
        if suffix in JPG_EXTENSIONS:
            groups[key]["jpg"] = str(f)
        elif suffix in RAW_EXTENSIONS:
            groups[key]["raw"] = str(f)

    # Step 3: Build PhotoPair objects and read EXIF
    pairs: list[PhotoPair] = []
    total = len(groups)
    for i, ((folder, stem), paths) in enumerate(groups.items()):
        jpg_path = paths.get("jpg")
        raw_path = paths.get("raw")

        # Read EXIF from JPG first (faster), fall back to RAW
        capture_date = None
        if jpg_path:
            capture_date = read_capture_date(jpg_path)
        if capture_date is None and raw_path:
            capture_date = read_capture_date(raw_path)

        pair = PhotoPair(
            stem=stem,
            folder=folder,
            jpg_path=jpg_path,
            raw_path=raw_path,
            capture_date=capture_date,
        )
        pairs.append(pair)

        if progress_callback is not None:
            progress_callback(i + 1, total)

    # Step 4: Sort by capture date
    pairs.sort(key=lambda p: p.sort_key())
    logger.info("Scanned %d folders, found %d photo pairs", len(folder_paths), len(pairs))
    return pairs
