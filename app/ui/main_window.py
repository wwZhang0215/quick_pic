from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QMainWindow, QMessageBox,
    QProgressDialog, QSplitter, QVBoxLayout, QWidget,
)

from app.core.models import MarkType
from app.core.scanner import scan_folders
from app.db import repository
from app.services.mark_service import MarkService
from app.services.move_service import MoveResult, PendingMove, execute_moves, resolve_moves
from app.services.session import PhotoSession
from app.ui.dialogs import FolderBindingDialog, MoveConfirmDialog
from app.ui.toolbar import FolderBindingsWidget, StatusBar
from app.ui.viewer import PhotoViewer

logger = logging.getLogger(__name__)


class _ScanWorker(QObject):
    finished = Signal(list)  # list[PhotoPair]
    progress = Signal(int, int)

    def __init__(self, folders: list[str]) -> None:
        super().__init__()
        self._folders = folders

    def run(self) -> None:
        pairs = scan_folders(self._folders, progress_callback=self.progress.emit)
        self.finished.emit(pairs)


class _MoveWorker(QObject):
    finished = Signal(object)  # MoveResult
    progress = Signal(int, int)

    def __init__(self, pending: list[PendingMove]) -> None:
        super().__init__()
        self._pending = pending

    def run(self) -> None:
        result = execute_moves(self._pending, progress_callback=self.progress.emit)
        self.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QuickPic")
        self.resize(1280, 800)

        repository.init_db()

        self._session = PhotoSession()
        self._mark_service = MarkService(self._session)

        self._setup_ui()
        self._setup_shortcuts()

        self._session.on_change(self._on_session_change)

        # Offer to restore last session
        self._try_restore_session()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        # Left: photo viewer
        self._viewer = PhotoViewer()

        # Right sidebar: folder key bindings
        self._bindings_widget = FolderBindingsWidget()
        self._bindings_widget.binding_edit_requested.connect(self._edit_binding)
        self._bindings_widget.setMaximumWidth(260)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._viewer)
        splitter.addWidget(self._bindings_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        # Bottom status bar
        self._status = StatusBar()

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        layout.addWidget(self._status)

        # Menu bar
        menu = self.menuBar()
        file_menu = menu.addMenu("File")
        file_menu.addAction("Open Folder(s)…", self._open_folders, QKeySequence("Ctrl+O"))
        file_menu.addSeparator()
        file_menu.addAction("Move Marked Photos…", self._move_photos, QKeySequence("Ctrl+M"))
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close, QKeySequence("Ctrl+Q"))

    def _setup_shortcuts(self) -> None:
        # Navigation
        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self._session.previous)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self._session.next)

        # Marking
        QShortcut(QKeySequence("K"), self).activated.connect(self._mark_service.toggle_keep)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(self._mark_service.toggle_keep)
        QShortcut(QKeySequence("U"), self).activated.connect(self._mark_service.unmark_current)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self).activated.connect(self._mark_service.unmark_current)

        # Folder keys 1-9
        for key in range(1, 10):
            QShortcut(QKeySequence(str(key)), self).activated.connect(
                lambda k=key: self._apply_folder_key(k)
            )

        # Move
        QShortcut(QKeySequence("M"), self).activated.connect(self._move_photos)

    # ------------------------------------------------------------------
    # Session restore
    # ------------------------------------------------------------------

    def _try_restore_session(self) -> None:
        saved = repository.get_session()
        if not saved or not saved["source_folders"]:
            return
        folders = saved["source_folders"]
        # Verify at least one folder still exists
        existing = [f for f in folders if Path(f).is_dir()]
        if not existing:
            return
        reply = QMessageBox.question(
            self,
            "Restore session",
            f"Restore last session?\n\n{chr(10).join(existing[:5])}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_scan(existing, start_index=saved["last_index"])

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_folders(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select photo folder", str(Path.home()))
        if not folder:
            return
        # Allow adding more folders
        folders = [folder]
        while True:
            reply = QMessageBox.question(
                self, "Add more folders?",
                "Add another folder to the current session?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                break
            extra = QFileDialog.getExistingDirectory(self, "Select additional folder", str(Path.home()))
            if extra:
                folders.append(extra)
            else:
                break
        self._start_scan(folders)

    def _start_scan(self, folders: list[str], start_index: int = 0) -> None:
        progress = QProgressDialog("Scanning photos…", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        worker = _ScanWorker(folders)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(lambda pairs: self._on_scan_done(pairs, folders, start_index, progress, thread))
        worker.progress.connect(lambda cur, tot: progress.setMaximum(tot) or progress.setValue(cur))
        thread.started.connect(worker.run)
        thread.start()
        self._scan_thread = thread  # keep reference

    def _on_scan_done(self, pairs, folders, start_index, progress, thread) -> None:
        progress.close()
        thread.quit()
        thread.wait()
        if not pairs:
            QMessageBox.information(self, "No photos", "No photos found in selected folder(s).")
            return
        self._session.load(pairs, folders, start_index=start_index)
        repository.save_session(folders, start_index)

    def _apply_folder_key(self, key: int) -> None:
        ok = self._mark_service.apply_folder_key(key)
        if not ok:
            # Key not bound — offer to bind it
            reply = QMessageBox.question(
                self, f"Key [{key}] not bound",
                f"Key [{key}] has no folder assigned. Assign one now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._edit_binding(key)

    def _edit_binding(self, key: int) -> None:
        bindings = repository.get_all_bindings()
        current = bindings.get(key, {}).get("path", "")
        dlg = FolderBindingDialog(key, current_path=current, parent=self)
        if dlg.exec() == FolderBindingDialog.DialogCode.Accepted:
            path = dlg.folder_path
            if path:
                repository.save_binding(key, path)
            else:
                repository.delete_binding(key)
            self._bindings_widget.refresh()

    def _move_photos(self) -> None:
        pairs = self._session.pairs
        marked = [p for p in pairs if p.mark_type != MarkType.NONE]
        if not marked:
            QMessageBox.information(self, "Nothing to move", "No photos are marked.")
            return

        pending, unresolved = resolve_moves(marked)
        needs_keep_folder = len(unresolved) > 0

        # Build summary text
        lines = [f"Total marked: {len(marked)}"]
        if pending:
            lines.append(f"  • {len(pending)} file pair(s) will be moved to bound folders")
        if unresolved:
            lines.append(f"  • {len(unresolved)} photo(s) marked KEEP need a destination folder")

        dlg = MoveConfirmDialog(
            move_summary="\n".join(lines),
            needs_keep_folder=needs_keep_folder,
            parent=self,
        )
        if dlg.exec() != MoveConfirmDialog.DialogCode.Accepted:
            return

        keep_folder = dlg.keep_folder if needs_keep_folder else None
        if unresolved and keep_folder:
            extra_pending, _ = resolve_moves(unresolved, default_keep_folder=keep_folder)
            pending.extend(extra_pending)

        if not pending:
            QMessageBox.information(self, "Nothing to move", "No photos to move after resolving destinations.")
            return

        # Execute in background
        progress = QProgressDialog("Moving photos…", None, 0, len(pending), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        move_worker = _MoveWorker(pending)
        thread = QThread(self)
        move_worker.moveToThread(thread)
        move_worker.finished.connect(lambda r: self._on_move_done(r, progress, thread))
        move_worker.progress.connect(lambda cur, _: progress.setValue(cur))
        thread.started.connect(move_worker.run)
        thread.start()
        self._move_thread = thread

    def _on_move_done(self, result: MoveResult, progress, thread) -> None:
        progress.close()
        thread.quit()
        thread.wait()

        msg = f"Moved: {result.moved} file(s)"
        if result.skipped:
            msg += f"\nSkipped: {result.skipped}"
        if result.errors:
            msg += "\n\nErrors:\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "Move complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Move complete", msg)

    # ------------------------------------------------------------------
    # Session change handler
    # ------------------------------------------------------------------

    def _on_session_change(self, index: int) -> None:
        pair = self._session.current
        self._viewer.display(pair)
        self._viewer.refresh_mark()

        # Status bar
        total = self._session.total
        if pair:
            if pair.mark_type == MarkType.NONE:
                mark_info = ""
            elif pair.mark_type == MarkType.KEEP:
                mark_info = "KEEP"
            else:
                bindings = repository.get_all_bindings()
                binding = bindings.get(pair.folder_key, {})
                label = binding.get("label") or binding.get("path", f"Key {pair.folder_key}")
                mark_info = f"→ [{pair.folder_key}] {label}"
        else:
            mark_info = ""

        self._status.update_status(index, total, mark_info)

        # Auto-save session position
        self._session.save_state()

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._session.save_state()
        super().closeEvent(event)
