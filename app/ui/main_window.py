from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QMainWindow, QMessageBox,
    QProgressDialog, QSplitter, QVBoxLayout, QWidget,
)

from app.core.exif_reader import ExifInfo, read_full_exif
from app.core.models import MarkType, PhotoPair
from app.core.scanner import scan_folders
from app.db import repository
from app.services.mark_service import MarkService
from app.services.move_service import MoveResult, PendingMove, execute_moves, resolve_moves
from app.services.session import PhotoSession
from app.ui.dialogs import FolderBindingDialog, MoveConfirmDialog
from app.ui.toolbar import Sidebar, StatusBar
from app.ui.viewer import PhotoViewer

logger = logging.getLogger(__name__)


class _ScanWorker(QObject):
    finished = Signal(list)   # list[PhotoPair]
    progress = Signal(int, int)

    def __init__(self, folders: list[str]) -> None:
        super().__init__()
        self._folders = folders

    def run(self) -> None:
        logger.debug("_ScanWorker.run START thread=%d", threading.get_ident())
        pairs = scan_folders(self._folders, progress_callback=self.progress.emit)
        logger.debug("_ScanWorker.run DONE %d pairs thread=%d", len(pairs), threading.get_ident())
        self.finished.emit(pairs)


class _ExifWorker(QObject):
    finished = Signal(object, str)   # (ExifInfo, pair_id)

    def __init__(self, file_path: str | None, pair_id: str) -> None:
        super().__init__()
        self._path = file_path
        self._pair_id = pair_id

    def run(self) -> None:
        info = read_full_exif(self._path) if self._path else ExifInfo()
        self.finished.emit(info, self._pair_id)


class _MoveWorker(QObject):
    finished = Signal(object)   # MoveResult
    progress = Signal(int, int)

    def __init__(self, pending: list[PendingMove]) -> None:
        super().__init__()
        self._pending = pending

    def run(self) -> None:
        logger.debug("_MoveWorker.run START thread=%d", threading.get_ident())
        result = execute_moves(self._pending, progress_callback=self.progress.emit)
        logger.debug("_MoveWorker.run DONE moved=%d thread=%d", result.moved, threading.get_ident())
        self.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QuickPic")
        self.resize(1280, 800)

        repository.init_db()

        self._session = PhotoSession()
        self._mark_service = MarkService(self._session)
        self._last_exif_pair_id: str | None = None
        self._exif_thread: QThread | None = None

        # Scan context — stored as instance vars so _on_scan_done needs no lambda
        self._scan_thread: QThread | None = None
        self._scan_folders: list[str] = []
        self._scan_start_index: int = 0
        self._scan_progress_dlg: QProgressDialog | None = None

        # Move context — same pattern
        self._move_thread: QThread | None = None
        self._move_progress_dlg: QProgressDialog | None = None

        self._setup_ui()
        self._setup_shortcuts()
        self._session.on_change(self._on_session_change)
        self._try_restore_session()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        self._viewer = PhotoViewer()

        self._sidebar = Sidebar()
        self._sidebar.binding_edit_requested.connect(self._edit_binding)
        self._sidebar.default_folder_edit_requested.connect(self._edit_default_folder)
        self._sidebar.default_folder_clear_requested.connect(self._clear_default_folder)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._viewer)
        splitter.addWidget(self._sidebar)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        self._status = StatusBar()

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        layout.addWidget(self._status)

        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        file_menu.addAction("打开文件夹…", self._open_folders, QKeySequence("Ctrl+O"))
        file_menu.addSeparator()
        file_menu.addAction("移动已标记照片…", self._move_photos, QKeySequence("Ctrl+Shift+M"))
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close, QKeySequence("Ctrl+Q"))

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self._session.previous)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self._session.next)

        QShortcut(QKeySequence("K"), self).activated.connect(self._mark_service.toggle_keep)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(self._mark_service.toggle_keep)
        QShortcut(QKeySequence("U"), self).activated.connect(self._mark_service.unmark_current)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self).activated.connect(self._mark_service.unmark_current)

        for key in range(1, 10):
            QShortcut(QKeySequence(str(key)), self).activated.connect(
                lambda k=key: self._apply_folder_key(k)
            )

        QShortcut(QKeySequence("M"), self).activated.connect(self._move_photos)

    # ------------------------------------------------------------------
    # Session restore
    # ------------------------------------------------------------------

    def _try_restore_session(self) -> None:
        saved = repository.get_session()
        if not saved or not saved["source_folders"]:
            return
        existing = [f for f in saved["source_folders"] if Path(f).is_dir()]
        if not existing:
            return
        reply = QMessageBox.question(
            self, "恢复上次会话",
            f"恢复上次会话？\n\n{chr(10).join(existing[:5])}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_scan(existing, start_index=saved["last_index"])

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _open_folders(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择照片文件夹", str(Path.home()))
        if not folder:
            return
        folders = [folder]
        while True:
            reply = QMessageBox.question(
                self, "继续添加文件夹？",
                "是否再添加一个文件夹到本次会话？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                break
            extra = QFileDialog.getExistingDirectory(self, "选择额外文件夹", str(Path.home()))
            if extra:
                folders.append(extra)
            else:
                break
        self._start_scan(folders)

    def _start_scan(self, folders: list[str], start_index: int = 0) -> None:
        logger.debug("_start_scan thread=%d folders=%s", threading.get_ident(), folders)

        # Store context so _on_scan_done can read it without a lambda
        self._scan_folders = folders
        self._scan_start_index = start_index

        dlg = QProgressDialog("正在扫描照片…", None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        dlg.show()
        self._scan_progress_dlg = dlg

        worker = _ScanWorker(folders)
        self._scan_worker = worker   # keep reference — prevents premature GC
        thread = QThread(self)
        worker.moveToThread(thread)

        # Connect to real methods only — Qt AutoConnection detects thread boundary
        # and uses QueuedConnection automatically, ensuring slots run on main thread.
        worker.finished.connect(self._on_scan_done)
        worker.progress.connect(self._on_scan_progress)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)

        thread.start()
        self._scan_thread = thread
        logger.debug("_start_scan: thread started")

    def _on_scan_done(self, pairs: list) -> None:
        t0 = time.monotonic()
        logger.debug("_on_scan_done ENTER thread=%d pairs=%d", threading.get_ident(), len(pairs))

        if self._scan_progress_dlg:
            self._scan_progress_dlg.close()
            self._scan_progress_dlg = None
        if self._scan_thread:
            self._scan_thread.quit()
            self._scan_thread = None

        if not pairs:
            QMessageBox.information(self, "无照片", "所选文件夹中未找到照片。")
            return

        logger.debug("_on_scan_done: calling session.load (%.1fms)", (time.monotonic() - t0) * 1000)
        self._session.load(pairs, self._scan_folders, start_index=self._scan_start_index)
        repository.save_session(self._scan_folders, self._scan_start_index)
        logger.debug("_on_scan_done EXIT (%.1fms)", (time.monotonic() - t0) * 1000)

    def _on_scan_progress(self, current: int, total: int) -> None:
        logger.debug("_on_scan_progress %d/%d thread=%d", current, total, threading.get_ident())
        if self._scan_progress_dlg:
            self._scan_progress_dlg.setMaximum(total)
            self._scan_progress_dlg.setValue(current)

    # ------------------------------------------------------------------
    # Folder key actions
    # ------------------------------------------------------------------

    def _apply_folder_key(self, key: int) -> None:
        ok = self._mark_service.apply_folder_key(key)
        if not ok:
            reply = QMessageBox.question(
                self, f"键 [{key}] 未绑定",
                f"键 [{key}] 尚未绑定文件夹，是否现在绑定？",
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
            self._sidebar.bindings.refresh(self._compute_per_key())
            self._sidebar.stats.update(*self._compute_stats())

    def _edit_default_folder(self) -> None:
        current = repository.get_default_keep_folder()
        dlg = FolderBindingDialog(key=None, current_path=current, parent=self)
        if dlg.exec() == FolderBindingDialog.DialogCode.Accepted:
            path = dlg.folder_path
            if path:
                repository.save_default_keep_folder(path)
            else:
                repository.clear_default_keep_folder()
            self._sidebar.bindings.refresh_default()

    def _clear_default_folder(self) -> None:
        repository.clear_default_keep_folder()
        self._sidebar.bindings.refresh_default(path="")

    # ------------------------------------------------------------------
    # Move
    # ------------------------------------------------------------------

    def _move_photos(self) -> None:
        pairs = self._session.pairs
        marked = [p for p in pairs if p.mark_type != MarkType.NONE]
        if not marked:
            QMessageBox.information(self, "无需移动", "没有已标记的照片。")
            return

        pending, unresolved = resolve_moves(marked)
        needs_keep_folder = len(unresolved) > 0

        lines = [f"已标记: {len(marked)} 张"]
        if pending:
            lines.append(f"  · {len(pending)} 张将移动到绑定文件夹")
        if unresolved:
            lines.append(f"  · {len(unresolved)} 张标记为 KEEP，需要指定目标文件夹")

        stored_default = repository.get_default_keep_folder()
        dlg = MoveConfirmDialog(
            move_summary="\n".join(lines),
            keep_folder=stored_default,
            needs_keep_folder=needs_keep_folder,
            parent=self,
        )
        if dlg.exec() != MoveConfirmDialog.DialogCode.Accepted:
            return

        keep_folder = dlg.keep_folder if needs_keep_folder else None
        if keep_folder and keep_folder != stored_default:
            repository.save_default_keep_folder(keep_folder)
            self._sidebar.bindings.refresh_default()

        if unresolved and keep_folder:
            extra, _ = resolve_moves(unresolved, default_keep_folder=keep_folder)
            pending.extend(extra)

        if not pending:
            QMessageBox.information(self, "无需移动", "解析目标后没有可移动的照片。")
            return

        dlg2 = QProgressDialog("正在移动照片…", None, 0, len(pending), self)
        dlg2.setWindowModality(Qt.WindowModality.WindowModal)
        dlg2.setMinimumDuration(0)
        dlg2.show()
        self._move_progress_dlg = dlg2

        worker = _MoveWorker(pending)
        self._move_worker = worker   # keep reference
        thread = QThread(self)
        worker.moveToThread(thread)

        # Real method connections — AutoConnection → QueuedConnection across threads
        worker.finished.connect(self._on_move_done)
        worker.progress.connect(self._on_move_progress)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)

        thread.start()
        self._move_thread = thread

    def _on_move_done(self, result: MoveResult) -> None:
        logger.debug("_on_move_done ENTER thread=%d moved=%d", threading.get_ident(), result.moved)
        if self._move_progress_dlg:
            self._move_progress_dlg.close()
            self._move_progress_dlg = None
        if self._move_thread:
            self._move_thread.quit()
            self._move_thread = None

        # Remove successfully moved pairs from session and DB marks
        if result.moved_pair_ids:
            self._session.remove_pairs(result.moved_pair_ids)

        msg = f"已移动: {result.moved} 个文件"
        if result.skipped:
            msg += f"\n跳过: {result.skipped}"
        if result.errors:
            msg += "\n\n错误:\n" + "\n".join(result.errors[:10])
            QMessageBox.warning(self, "移动完成（有错误）", msg)
        else:
            QMessageBox.information(self, "移动完成", msg)

    def _on_move_progress(self, current: int, total: int) -> None:
        if self._move_progress_dlg:
            self._move_progress_dlg.setValue(current)

    # ------------------------------------------------------------------
    # Session change handler (always called on main thread via on_change callback)
    # ------------------------------------------------------------------

    def _on_session_change(self, index: int) -> None:
        t0 = time.monotonic()
        logger.debug("_on_session_change ENTER index=%d thread=%d", index, threading.get_ident())
        pair = self._session.current

        self._viewer.display(pair)
        self._viewer.refresh_mark()
        logger.debug("_on_session_change: viewer updated (%.1fms)", (time.monotonic() - t0) * 1000)

        total = self._session.total
        self._status.update_status(index, total, self._mark_label(pair))

        total_n, marked_n, keep_n, per_key = self._compute_stats()
        self._sidebar.stats.update(total_n, marked_n, keep_n, per_key)
        self._sidebar.bindings.refresh(per_key)
        logger.debug("_on_session_change: sidebar updated (%.1fms)", (time.monotonic() - t0) * 1000)

        if pair is not None and pair.pair_id != self._last_exif_pair_id:
            self._last_exif_pair_id = pair.pair_id
            self._load_exif_async(pair)

        if pair is None:
            self._sidebar.exif.update(None)
            self._last_exif_pair_id = None

        self._session.save_state()
        logger.debug("_on_session_change EXIT (%.1fms)", (time.monotonic() - t0) * 1000)

    def _mark_label(self, pair: PhotoPair | None) -> str:
        if pair is None or pair.mark_type == MarkType.NONE:
            return ""
        if pair.mark_type == MarkType.KEEP:
            return "★ KEEP"
        bindings = repository.get_all_bindings()
        binding = bindings.get(pair.folder_key, {})
        dest = binding.get("label") or binding.get("path", f"键 {pair.folder_key}")
        return f"→ [{pair.folder_key}] {dest}"

    def _compute_stats(self) -> tuple[int, int, int, dict[int, int]]:
        pairs = self._session.pairs
        total = len(pairs)
        marked = sum(1 for p in pairs if p.mark_type != MarkType.NONE)
        keep = sum(1 for p in pairs if p.mark_type == MarkType.KEEP)
        per_key: dict[int, int] = {}
        for p in pairs:
            if p.mark_type == MarkType.FOLDER_KEY and p.folder_key is not None:
                per_key[p.folder_key] = per_key.get(p.folder_key, 0) + 1
        return total, marked, keep, per_key

    def _compute_per_key(self) -> dict[int, int]:
        return self._compute_stats()[3]

    # ------------------------------------------------------------------
    # EXIF async load
    # ------------------------------------------------------------------

    def _load_exif_async(self, pair: PhotoPair) -> None:
        if self._exif_thread and self._exif_thread.isRunning():
            self._exif_thread.quit()
            self._exif_thread.wait(50)

        worker = _ExifWorker(pair.jpg_path or pair.raw_path, pair.pair_id)
        self._exif_worker = worker   # keep reference
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_exif_loaded)   # AutoConnection → main thread
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._exif_thread = thread
        thread.start()

    def _on_exif_loaded(self, info: ExifInfo, pair_id: str) -> None:
        logger.debug("_on_exif_loaded pair_id=%s thread=%d", pair_id, threading.get_ident())
        if pair_id == self._last_exif_pair_id:
            self._sidebar.exif.update(info)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._session.save_state()
        super().closeEvent(event)
