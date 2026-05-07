from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView,
    QLabel, QVBoxLayout, QWidget,
)

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
        logger.debug("_ImageLoader.run START path=%s thread=%d", self._pair.display_path, threading.get_ident())
        data = get_display_bytes(self._pair.display_path)
        logger.debug("_ImageLoader.run DONE %d bytes %.1fms", len(data) if data else 0, (time.monotonic() - t0) * 1000)
        if data:
            self.loaded.emit(data, self._pair.pair_id)
        else:
            self.failed.emit(self._pair.pair_id)


_MARK_COLORS: dict[MarkType, QColor | None] = {
    MarkType.NONE: None,
    MarkType.KEEP: QColor(0, 200, 100, 60),
    MarkType.FOLDER_KEY: QColor(60, 120, 255, 60),
}


class _PhotoView(QGraphicsView):
    """
    Zoomable, pannable photo canvas.
    - Scroll wheel: zoom in/out around cursor
    - Click and drag: pan
    - Double-click: reset to fit view
    """

    _ZOOM_STEP = 1.15

    def __init__(self, parent=None) -> None:
        scene = QGraphicsScene()
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: #1a1a1a; border: none;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._img = QGraphicsPixmapItem()
        self._img.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        scene.addItem(self._img)

        self._tint = QGraphicsRectItem()
        self._tint.setPen(Qt.PenStyle.NoPen)
        self._tint.setVisible(False)
        scene.addItem(self._tint)

        self._badge = QGraphicsSimpleTextItem()
        f = QFont()
        f.setBold(True)
        f.setPointSize(14)
        self._badge.setFont(f)
        self._badge.setBrush(QColor(255, 255, 255))
        self._badge.setVisible(False)
        scene.addItem(self._badge)

        self._fit_mode = True

    # ------------------------------------------------------------------
    # Content API
    # ------------------------------------------------------------------

    def load_pixmap(self, px: QPixmap) -> None:
        self._img.setPixmap(px)
        self.scene().setSceneRect(self._img.boundingRect())
        self._fit_mode = True
        self._do_fit()

    def set_mark(self, color: QColor | None, badge: str) -> None:
        has_img = not self._img.pixmap().isNull()
        if color and has_img:
            self._tint.setRect(self._img.boundingRect())
            self._tint.setBrush(color)
            self._tint.setVisible(True)
        else:
            self._tint.setVisible(False)

        if badge and has_img:
            self._badge.setText(badge)
            br = self._img.boundingRect()
            bb = self._badge.boundingRect()
            self._badge.setPos(br.right() - bb.width() - 10, br.top() + 10)
            self._badge.setVisible(True)
        else:
            self._badge.setVisible(False)

    def clear_image(self) -> None:
        self._img.setPixmap(QPixmap())
        self._tint.setVisible(False)
        self._badge.setVisible(False)

    # ------------------------------------------------------------------
    # Zoom / pan
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        self._fit_mode = False
        f = self._ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self._ZOOM_STEP
        self.scale(f, f)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        self._fit_mode = True
        self._do_fit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._fit_mode and not self._img.pixmap().isNull():
            self._do_fit()

    def _do_fit(self) -> None:
        if not self._img.pixmap().isNull():
            self.fitInView(self._img, Qt.AspectRatioMode.KeepAspectRatio)


class PhotoViewer(QWidget):
    """
    Displays the current photo with a mark overlay.
    Scroll wheel zooms; drag pans; double-click resets to fit.
    Image loading runs in a background thread.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._current_pair: PhotoPair | None = None
        self._pending_pair_id: str | None = None
        self._loader: _ImageLoader | None = None
        self._loader_thread: QThread | None = None

        self._view = _PhotoView()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        # Floating status text (transparent overlay, passes mouse events through)
        self._status_lbl = QLabel(self)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color: #888; font-size: 14px; background: transparent;")
        self._status_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._set_status("按 Ctrl+O 打开文件夹")

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._status_lbl.setGeometry(self.rect())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display(self, pair: PhotoPair | None) -> None:
        """Start loading and displaying the given photo pair."""
        if pair is self._current_pair:
            return

        logger.debug("viewer.display pair=%s thread=%d", pair.pair_id if pair else None, threading.get_ident())
        self._current_pair = pair

        if pair is None:
            self._set_status("No photos loaded")
            return

        self._set_status("Loading…")
        self._pending_pair_id = pair.pair_id

        loader = _ImageLoader(pair)
        thread = QThread(self)
        loader.moveToThread(thread)
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_failed)
        thread.started.connect(loader.run)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._loader = loader
        self._loader_thread = thread
        thread.start()

    def refresh_mark(self) -> None:
        """Re-render the mark overlay without reloading the image."""
        self._update_mark()

    def stop_loading(self) -> None:
        """Stop all in-flight loader threads. Call before widget destruction."""
        for thread in self.findChildren(QThread):
            if thread.isRunning():
                thread.quit()
                thread.wait(2000)

    # ------------------------------------------------------------------
    # Slots (always called on main thread via AutoConnection)
    # ------------------------------------------------------------------

    def _on_loaded(self, data: bytes, pair_id: str) -> None:
        logger.debug("viewer._on_loaded pair_id=%s pending=%s thread=%d", pair_id, self._pending_pair_id, threading.get_ident())
        if pair_id != self._pending_pair_id:
            return
        px = QPixmap()
        px.loadFromData(data)
        self._view.load_pixmap(px)
        self._status_lbl.setVisible(False)
        self._update_mark()

    def _on_failed(self, pair_id: str) -> None:
        if pair_id != self._pending_pair_id:
            return
        self._set_status("Cannot display image")

    def _update_mark(self) -> None:
        pair = self._current_pair
        if pair is None:
            return
        color = _MARK_COLORS.get(pair.mark_type)
        if pair.mark_type == MarkType.KEEP:
            badge = "KEEP"
        elif pair.mark_type == MarkType.FOLDER_KEY:
            badge = f"[{pair.folder_key}]"
        else:
            badge = ""
        self._view.set_mark(color, badge)

    def _set_status(self, text: str) -> None:
        self._view.clear_image()
        self._status_lbl.setText(text)
        self._status_lbl.setVisible(True)
        self._status_lbl.raise_()
