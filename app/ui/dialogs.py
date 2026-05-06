from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QLabel, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QMessageBox, QWidget,
)


class FolderBindingDialog(QDialog):
    """Dialog for assigning a folder path to a number key (1-9)."""

    def __init__(self, key: int, current_path: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Bind folder to key [{key}]")
        self.setMinimumWidth(480)
        self._key = key
        self._path = current_path

        self._path_edit = QLineEdit(current_path)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self._path_edit)
        path_row.addWidget(browse_btn)

        form = QFormLayout()
        form.addRow(f"Key [{key}] → folder:", path_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        start = self._path_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select folder", start)
        if folder:
            self._path_edit.setText(folder)

    @property
    def folder_path(self) -> str:
        return self._path_edit.text().strip()


class MoveConfirmDialog(QDialog):
    """Shows a summary of pending moves and asks the user to confirm."""

    def __init__(
        self,
        move_summary: str,
        keep_folder: str = "",
        needs_keep_folder: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move photos")
        self.setMinimumWidth(520)

        self._keep_path_edit: QLineEdit | None = None
        self._keep_folder = keep_folder

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(move_summary))

        if needs_keep_folder:
            layout.addWidget(QLabel("\nPhotos marked <b>KEEP</b> have no folder assigned. Choose a destination:"))
            self._keep_path_edit = QLineEdit(keep_folder)
            browse_btn = QPushButton("Browse…")
            browse_btn.clicked.connect(self._browse_keep)
            row = QHBoxLayout()
            row.addWidget(self._keep_path_edit)
            row.addWidget(browse_btn)
            layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_keep(self) -> None:
        start = self._keep_path_edit.text() if self._keep_path_edit else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select keep folder", start or str(Path.home()))
        if folder and self._keep_path_edit:
            self._keep_path_edit.setText(folder)

    def _on_accept(self) -> None:
        if self._keep_path_edit is not None:
            path = self._keep_path_edit.text().strip()
            if not path:
                QMessageBox.warning(self, "Missing folder", "Please select a destination folder for KEEP photos.")
                return
            self._keep_folder = path
        self.accept()

    @property
    def keep_folder(self) -> str:
        return self._keep_folder
