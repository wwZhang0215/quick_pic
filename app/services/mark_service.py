from __future__ import annotations

from app.db import repository
from app.services.session import PhotoSession


class MarkService:
    """Thin facade that delegates all mark operations to PhotoSession."""

    def __init__(self, session: PhotoSession) -> None:
        self._session = session

    def toggle_keep(self) -> None:
        """Toggle keep mark on the current photo."""
        pair = self._session.current
        if pair is None:
            return
        from app.core.models import MarkType
        if pair.mark_type == MarkType.KEEP:
            self._session.unmark()
        else:
            self._session.mark_keep()

    def apply_folder_key(self, key: int) -> bool:
        """
        Mark current photo for the given folder key (1-9).
        Returns False if the key has no binding configured.
        """
        bindings = repository.get_all_bindings()
        if key not in bindings:
            return False
        self._session.mark_folder_key(key)
        return True

    def unmark_current(self) -> None:
        self._session.unmark()
