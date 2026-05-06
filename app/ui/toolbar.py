from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from app.core.exif_reader import ExifInfo
from app.db import repository


class ExifPanel(QWidget):
    """Shows EXIF shooting parameters for the current photo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        group = QGroupBox("EXIF")
        self._form = QFormLayout(group)
        self._form.setContentsMargins(6, 4, 6, 4)
        self._form.setSpacing(2)

        self._labels: dict[str, QLabel] = {}
        for key in ("拍摄时间", "相机", "镜头", "焦距", "光圈", "快门", "ISO", "分辨率"):
            val = QLabel("—")
            val.setWordWrap(True)
            val.setStyleSheet("color: #ddd; font-size: 11px;")
            self._form.addRow(_head(key), val)
            self._labels[key] = val

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)

    def update(self, info: ExifInfo | None) -> None:  # type: ignore[override]
        if info is None:
            for lbl in self._labels.values():
                lbl.setText("—")
            return

        def s(v: str) -> str:
            return v if v else "—"

        self._labels["拍摄时间"].setText(
            info.capture_date.strftime("%Y-%m-%d  %H:%M:%S") if info.capture_date else "—"
        )
        self._labels["相机"].setText(s(info.camera))
        self._labels["镜头"].setText(s(info.lens))
        self._labels["焦距"].setText(s(info.focal_length))
        self._labels["光圈"].setText(s(info.aperture))
        self._labels["快门"].setText(s(info.shutter))
        self._labels["ISO"].setText(s(info.iso))
        if info.width and info.height:
            self._labels["分辨率"].setText(f"{info.width} × {info.height}")
        else:
            self._labels["分辨率"].setText("—")


class StatsPanel(QWidget):
    """Shows session-level statistics: total, marked, per-folder counts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        group = QGroupBox("统计")
        inner = QVBoxLayout(group)
        inner.setContentsMargins(6, 4, 6, 4)
        inner.setSpacing(3)

        # Summary row
        self._summary = QLabel("总计 0 张  |  已标记 0 张")
        self._summary.setStyleSheet("color: #ddd; font-size: 11px;")
        inner.addWidget(self._summary)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #444;")
        inner.addWidget(line)

        # Per-folder/keep breakdown (dynamic labels)
        self._breakdown_layout = QVBoxLayout()
        self._breakdown_layout.setSpacing(2)
        inner.addLayout(self._breakdown_layout)

        self._breakdown_labels: list[QLabel] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)

    def update(  # type: ignore[override]
        self,
        total: int,
        marked: int,
        keep_count: int,
        per_key: dict[int, int],
    ) -> None:
        self._summary.setText(f"总计 {total} 张  |  已标记 {marked} 张")

        # Rebuild breakdown rows
        for lbl in self._breakdown_labels:
            lbl.setParent(None)
        self._breakdown_labels.clear()

        bindings = repository.get_all_bindings()

        rows: list[tuple[str, int]] = []
        if keep_count > 0:
            rows.append(("KEEP", keep_count))
        for key in sorted(per_key):
            count = per_key[key]
            label = bindings.get(key, {}).get("label") or ""
            path = bindings.get(key, {}).get("path", "")
            name = label or (path.split("/")[-1] or path.split("\\")[-1] if path else f"键 {key}")
            rows.append((f"[{key}] {name}", count))

        for name, count in rows:
            lbl = QLabel(f"  {name}: {count} 张")
            lbl.setStyleSheet("color: #bbb; font-size: 11px;")
            self._breakdown_layout.addWidget(lbl)
            self._breakdown_labels.append(lbl)


class FolderBindingsWidget(QWidget):
    """
    Sidebar panel showing which folder keys (1-9) are currently bound.
    Each button opens the binding dialog when clicked.
    """

    binding_edit_requested = Signal(int)   # key number

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[int, QPushButton] = {}

        group = QGroupBox("文件夹键 (1–9)")
        grid = QGridLayout(group)
        grid.setSpacing(4)

        for key in range(1, 10):
            btn = QPushButton(f"[{key}] —")
            btn.setToolTip(f"点击为键 {key} 绑定文件夹")
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda checked=False, k=key: self.binding_edit_requested.emit(k))
            self._buttons[key] = btn
            row, col = divmod(key - 1, 3)
            grid.addWidget(btn, row, col)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)
        self.refresh()

    def refresh(self, per_key_counts: dict[int, int] | None = None) -> None:
        """Reload bindings from DB and update button labels."""
        bindings = repository.get_all_bindings()
        counts = per_key_counts or {}
        for key, btn in self._buttons.items():
            count = counts.get(key, 0)
            count_str = f" ({count})" if count else ""
            if key in bindings:
                path = bindings[key]["path"]
                name = path.split("/")[-1] or path.split("\\")[-1] or path
                short = name[-18:] if len(name) > 18 else name
                btn.setText(f"[{key}] {short}{count_str}")
                btn.setToolTip(path)
            else:
                btn.setText(f"[{key}] —")
                btn.setToolTip(f"点击为键 {key} 绑定文件夹")


class StatusBar(QWidget):
    """Bottom bar: current index, mark status, hint text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        self._label.setStyleSheet("color: #ccc; padding: 4px 8px; font-size: 11px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def update_status(self, index: int, total: int, mark_info: str) -> None:
        pos = f"{index + 1} / {total}" if total else "— / —"
        mark = f"  ·  {mark_info}" if mark_info else ""
        hint = "  ·  ← → 浏览  K 保留  1-9 文件夹  U 取消标记  M 移动"
        self._label.setText(pos + mark + hint)


# ---------------------------------------------------------------------------
# Sidebar: wraps ExifPanel + StatsPanel + FolderBindingsWidget in a scroll area
# ---------------------------------------------------------------------------

class Sidebar(QWidget):
    """Right-side panel combining stats, EXIF info, and folder key bindings."""

    binding_edit_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)

        self.stats = StatsPanel()
        self.exif = ExifPanel()
        self.bindings = FolderBindingsWidget()
        self.bindings.binding_edit_requested.connect(self.binding_edit_requested)

        content = QWidget()
        vbox = QVBoxLayout(content)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(6)
        vbox.addWidget(self.stats)
        vbox.addWidget(self.exif)
        vbox.addWidget(self.bindings)
        vbox.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        from PySide6.QtCore import Qt
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _head(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #888; font-size: 11px;")
    return lbl
