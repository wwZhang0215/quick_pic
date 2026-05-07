from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable

from app.core.models import PhotoPair
from app.core.thumbnail import JPG_EXTENSIONS, RAW_EXTENSIONS

logger = logging.getLogger(__name__)


def scan_folders(
    folder_paths: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[PhotoPair]:
    """
    Scan one or more folders for photos, pair JPG+RAW by filename stem,
    and return a list sorted by filename.

    EXIF capture dates are NOT read here — they are loaded lazily when a photo
    is displayed. This keeps scanning fast regardless of RAW file count.

    Args:
        folder_paths: List of absolute folder paths to scan (non-recursive).
        progress_callback: Optional callback(current, total) for progress updates.

    Returns:
        List of PhotoPair objects sorted by (folder, stem).
    """
    # Step 1: Collect all image files
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
        key = (folder_str, f.stem)
        if suffix in JPG_EXTENSIONS:
            groups[key]["jpg"] = str(f)
        elif suffix in RAW_EXTENSIONS:
            groups[key]["raw"] = str(f)

    # Step 3: Build PhotoPair objects (no EXIF reads)
    pairs: list[PhotoPair] = []
    total = len(groups)
    for i, ((folder, stem), paths) in enumerate(groups.items()):
        pair = PhotoPair(
            stem=stem,
            folder=folder,
            jpg_path=paths.get("jpg"),
            raw_path=paths.get("raw"),
        )
        pairs.append(pair)

        if progress_callback is not None:
            progress_callback(i + 1, total)

    # Step 4: Sort by folder then filename stem
    pairs.sort(key=lambda p: (p.folder, p.stem))
    logger.info("Scanned %d folders, found %d photo pairs", len(folder_paths), len(pairs))
    return pairs
