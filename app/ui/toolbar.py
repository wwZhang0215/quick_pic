from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QWidget,
)

from app.db import repository


class FolderBindingsWidget(QWidget):
    """
    Sidebar panel showing which folder keys (1-9) are currently bound.
    Each key button opens the binding dialog when clicked.
    """

    binding_edit_requested = Signal(int)   # key number

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[int, QPushButton] = {}

        group = QGroupBox("Folder Keys")
        grid = QGridLayout(group)

        for key in range(1, 10):
            btn = QPushButton(f"[{key}] —")
            btn.setToolTip(f"Click to bind a folder to key {key}")
            btn.clicked.connect(lambda checked=False, k=key: self.binding_edit_requested.emit(k))
            self._buttons[key] = btn
            row, col = divmod(key - 1, 3)
            grid.addWidget(btn, row, col)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)
        self.refresh()

    def refresh(self) -> None:
        """Reload bindings from DB and update button labels."""
        bindings = repository.get_all_bindings()
        for key, btn in self._buttons.items():
            if key in bindings:
                path = bindings[key]["path"]
                short = path[-28:] if len(path) > 28 else path
                btn.setText(f"[{key}] {short}")
                btn.setToolTip(path)
            else:
                btn.setText(f"[{key}] —")
                btn.setToolTip(f"Click to bind a folder to key {key}")


class StatusBar(QWidget):
    """Shows current photo index, mark status, and navigation hints."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        self._label.setStyleSheet("color: #ccc; padding: 4px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self._label)

    def update_status(self, index: int, total: int, mark_info: str) -> None:
        text = f"{index + 1} / {total}"
        if mark_info:
            text += f"  |  {mark_info}"
        text += "   ·   ← → navigate  ·  K keep  ·  1-9 folder  ·  U unmark  ·  M move"
        self._label.setText(text)
