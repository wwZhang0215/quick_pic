from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.models import MarkType, PhotoPair
from app.db import repository

logger = logging.getLogger(__name__)


@dataclass
class MoveResult:
    moved: int = 0
    skipped: int = 0
    errors: list[str] = None  # type: ignore[assignment]
    moved_pair_ids: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.moved_pair_ids is None:
            self.moved_pair_ids = []


@dataclass
class PendingMove:
    """Describes a single file move operation."""
    pair: PhotoPair
    target_root: str        # the resolved destination folder root


def resolve_moves(
    pairs: list[PhotoPair],
    default_keep_folder: str | None = None,
) -> tuple[list[PendingMove], list[PhotoPair]]:
    """
    Resolve which pairs to move and where.

    Returns:
        (pending_moves, unresolved_pairs)
        unresolved_pairs: marked 'keep' but no folder provided — caller must prompt user.
    """
    bindings = repository.get_all_bindings()
    pending: list[PendingMove] = []
    unresolved: list[PhotoPair] = []

    for pair in pairs:
        if pair.mark_type == MarkType.NONE:
            continue

        if pair.mark_type == MarkType.FOLDER_KEY:
            binding = bindings.get(pair.folder_key)
            if binding:
                pending.append(PendingMove(pair=pair, target_root=binding["path"]))
            else:
                logger.warning("No binding for key %d, skipping %s", pair.folder_key, pair.stem)

        elif pair.mark_type == MarkType.KEEP:
            if default_keep_folder:
                pending.append(PendingMove(pair=pair, target_root=default_keep_folder))
            else:
                unresolved.append(pair)

    return pending, unresolved


def execute_moves(
    pending: list[PendingMove],
    progress_callback: Callable[[int, int], None] | None = None,
) -> MoveResult:
    """
    Execute all pending file moves.

    JPG files go to {target_root}/JPG/
    RAW files go to {target_root}/RAW/
    """
    result = MoveResult()
    total = len(pending)

    for i, move in enumerate(pending):
        pair = move.pair
        root = Path(move.target_root)

        try:
            jpg_dest = root / "JPG"
            raw_dest = root / "RAW"

            if pair.jpg_path:
                jpg_dest.mkdir(parents=True, exist_ok=True)
                _move_file(pair.jpg_path, jpg_dest / Path(pair.jpg_path).name)
                result.moved += 1

            if pair.raw_path:
                raw_dest.mkdir(parents=True, exist_ok=True)
                _move_file(pair.raw_path, raw_dest / Path(pair.raw_path).name)
                result.moved += 1

            result.moved_pair_ids.append(pair.pair_id)

        except Exception as exc:
            msg = f"Failed to move {pair.stem}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            result.skipped += 1

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return result


def _move_file(src: str, dst: Path) -> None:
    """Move src to dst, handling the case where dst already exists."""
    if dst.exists():
        # Avoid overwrite: append a suffix
        stem = dst.stem
        suffix = dst.suffix
        counter = 1
        while dst.exists():
            dst = dst.parent / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.move(src, str(dst))
    logger.debug("Moved %s -> %s", src, dst)
