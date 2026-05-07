from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget, QVBoxLayout

from app.core.models import MarkType, PhotoPair
from app.core.thumbnail import get_display_bytes

logger = logging.getLogger(__name__)


class _ImageLoader(QObject):
    """Loads image bytes in a background thread."""
    loaded = Signal(bytes, str)   # (image_bytes, pair_id)
    failed = Signal(str)          # pair_id

    def __init__(self, pair: PhotoPair) -> None:
        super().__init__()
        self._pair = pair

    def run(self) -> None:
        t0 = time.monotonic()
        tid = threading.get_ident()
        logger.debug("_ImageLoader.run START path=%s thread=%d", self._pair.display_path, tid)
        data = get_display_bytes(self._pair.display_path)
        elapsed = (time.monotonic() - t0) * 1000
        logger.debug("_ImageLoader.run DONE %d bytes (%.1fms) thread=%d", len(data) if data else 0, elapsed, tid)
        if data:
            self.loaded.emit(data, self._pair.pair_id)
        else:
            self.failed.emit(self._pair.pair_id)


_MARK_COLORS: dict[MarkType, QColor | None] = {
    MarkType.NONE: None,
    MarkType.KEEP: QColor(0, 200, 100, 60),
    MarkType.FOLDER_KEY: QColor(60, 120, 255, 60),
}


class PhotoViewer(QWidget):
    """
    Displays the current photo with a mark overlay.
    Image loading runs in a background thread; results arrive via Qt signals
    using AutoConnection so they are always dispatched to the main thread.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_pair: PhotoPair | None = None
        self._pending_pair_id: str | None = None
        self._raw_pixmap: QPixmap | None = None
        self._loader: _ImageLoader | None = None   # strong ref prevents GC
        self._loader_thread: QThread | None = None

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._label.setStyleSheet("background-color: #1a1a1a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display(self, pair: PhotoPair | None) -> None:
        """Start loading and displaying the given photo pair."""
        if pair is self._current_pair:
            return

        tid = threading.get_ident()
        logger.debug("viewer.display ENTER pair=%s thread=%d", pair.pair_id if pair else None, tid)

        self._current_pair = pair
        self._raw_pixmap = None

        if pair is None:
            self._label.clear()
            self._label.setText("No photos loaded")
            return

        self._label.setText("Loading…")
        self._pending_pair_id = pair.pair_id

        # Keep strong references so neither loader nor thread are GC'd before the
        # signal fires. Without self._loader the loader object is immediately
        # eligible for collection, causing the loaded signal to never arrive (or
        # worse, crashing the worker thread when it tries to emit).
        loader = _ImageLoader(pair)
        thread = QThread(self)
        loader.moveToThread(thread)
        loader.loaded.connect(self._on_loaded)    # AutoConnection → main thread
        loader.failed.connect(self._on_failed)    # AutoConnection → main thread
        thread.started.connect(loader.run)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._loader = loader
        self._loader_thread = thread
        thread.start()
        logger.debug("viewer.display: loader thread started, thread=%d", tid)

    def refresh_mark(self) -> None:
        """Re-render the overlay when mark state changes without reloading the image."""
        self._update_display()

    def stop_loading(self) -> None:
        """Stop any in-flight image loader thread. Call before widget destruction."""
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.quit()
            self._loader_thread.wait(2000)

    # ------------------------------------------------------------------
    # Slots (always called on main thread via AutoConnection)
    # ------------------------------------------------------------------

    def _on_loaded(self, data: bytes, pair_id: str) -> None:
        tid = threading.get_ident()
        logger.debug("viewer._on_loaded pair_id=%s pending=%s thread=%d", pair_id, self._pending_pair_id, tid)
        if pair_id != self._pending_pair_id:
            logger.debug("viewer._on_loaded: stale result, discarding")
            return
        t0 = time.monotonic()
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        logger.debug("viewer._on_loaded: QPixmap loaded (%.1fms)", (time.monotonic() - t0) * 1000)
        self._raw_pixmap = pixmap
        self._update_display()

    def _on_failed(self, pair_id: str) -> None:
        logger.debug("viewer._on_failed pair_id=%s thread=%d", pair_id, threading.get_ident())
        if pair_id != self._pending_pair_id:
            return
        self._label.setText("Cannot display image")

    def _update_display(self) -> None:
        if self._raw_pixmap is None or self._raw_pixmap.isNull():
            return

        scaled = self._raw_pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        pair = self._current_pair
        if pair is None or pair.mark_type == MarkType.NONE:
            self._label.setPixmap(scaled)
            return

        result = QPixmap(scaled)
        painter = QPainter(result)
        overlay_color = _MARK_COLORS.get(pair.mark_type)
        if overlay_color:
            painter.fillRect(result.rect(), overlay_color)

        if pair.mark_type == MarkType.KEEP:
            badge_text = "KEEP"
        elif pair.mark_type == MarkType.FOLDER_KEY:
            badge_text = f"[{pair.folder_key}]"
        else:
            badge_text = ""

        if badge_text:
            font = QFont()
            font.setBold(True)
            font.setPointSize(14)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                result.rect().adjusted(0, 10, -10, 0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                badge_text,
            )
        painter.end()
        self._label.setPixmap(result)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_display()
