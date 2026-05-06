from __future__ import annotations

import logging
from typing import Callable

from app.core.models import MarkType, PhotoPair
from app.db import repository

logger = logging.getLogger(__name__)


class PhotoSession:
    """
    Owns the current list of PhotoPairs and the active index.
    Provides navigation and mark retrieval, no Qt dependencies.
    """

    def __init__(self) -> None:
        self._pairs: list[PhotoPair] = []
        self._index: int = 0
        self._source_folders: list[str] = []
        # Callbacks registered by the UI
        self._on_change: list[Callable[[int], None]] = []

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, pairs: list[PhotoPair], source_folders: list[str], start_index: int = 0) -> None:
        """Replace the current photo list and restore saved marks."""
        self._pairs = pairs
        self._source_folders = source_folders
        self._index = max(0, min(start_index, len(pairs) - 1)) if pairs else 0
        self._apply_saved_marks()
        self._notify()

    def _apply_saved_marks(self) -> None:
        """Load all persisted marks from DB and apply them to pairs in memory."""
        all_marks = repository.get_all_marks()
        for pair in self._pairs:
            mark_data = all_marks.get(pair.pair_id)
            if mark_data:
                pair.mark_type = MarkType(mark_data["mark_type"])
                pair.folder_key = mark_data.get("folder_key")
            else:
                pair.mark_type = MarkType.NONE
                pair.folder_key = None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @property
    def current(self) -> PhotoPair | None:
        if not self._pairs:
            return None
        return self._pairs[self._index]

    @property
    def index(self) -> int:
        return self._index

    @property
    def total(self) -> int:
        return len(self._pairs)

    @property
    def source_folders(self) -> list[str]:
        return list(self._source_folders)

    @property
    def pairs(self) -> list[PhotoPair]:
        return list(self._pairs)

    def go_to(self, index: int) -> None:
        if not self._pairs:
            return
        self._index = max(0, min(index, len(self._pairs) - 1))
        self._notify()

    def next(self) -> None:
        self.go_to(self._index + 1)

    def previous(self) -> None:
        self.go_to(self._index - 1)

    # ------------------------------------------------------------------
    # Mark operations
    # ------------------------------------------------------------------

    def mark_keep(self) -> None:
        pair = self.current
        if pair is None:
            return
        pair.mark_type = MarkType.KEEP
        pair.folder_key = None
        repository.save_mark(pair.pair_id, MarkType.KEEP.value)
        self._notify()

    def mark_folder_key(self, key: int) -> None:
        pair = self.current
        if pair is None:
            return
        pair.mark_type = MarkType.FOLDER_KEY
        pair.folder_key = key
        repository.save_mark(pair.pair_id, MarkType.FOLDER_KEY.value, key)
        self._notify()

    def unmark(self) -> None:
        pair = self.current
        if pair is None:
            return
        pair.mark_type = MarkType.NONE
        pair.folder_key = None
        repository.delete_mark(pair.pair_id)
        self._notify()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """Persist current position to DB for session restore."""
        repository.save_session(self._source_folders, self._index)

    # ------------------------------------------------------------------
    # Observer
    # ------------------------------------------------------------------

    def on_change(self, callback: Callable[[int], None]) -> None:
        """Register a callback invoked whenever index or mark state changes."""
        self._on_change.append(callback)

    def _notify(self) -> None:
        for cb in self._on_change:
            cb(self._index)
