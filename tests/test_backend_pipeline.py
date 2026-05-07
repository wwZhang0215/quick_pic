"""
Backend integration tests: scan → session → mark → move pipeline.
No Qt dependency. Uses real files from /Users/xpeng/Downloads/10660505.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import MarkType
from app.core.scanner import scan_folders
from app.db import repository
from app.services.mark_service import MarkService
from app.services.move_service import execute_moves, resolve_moves
from app.services.session import PhotoSession


# ---------------------------------------------------------------------------
# scan_folders
# ---------------------------------------------------------------------------

_EXPECTED_PAIRS = len(list(__import__('pathlib').Path("/Users/xpeng/Downloads/10660505").glob("*.JPG")))


class TestScanFolders:
    def test_finds_all_pairs(self, tmp_photo_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        assert len(pairs) == _EXPECTED_PAIRS

    def test_pairs_have_jpg_and_raw(self, tmp_photo_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        for p in pairs:
            assert p.jpg_path is not None, f"{p.stem} missing JPG"
            assert p.raw_path is not None, f"{p.stem} missing RAW"

    def test_sorted_by_stem(self, tmp_photo_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        stems = [p.stem for p in pairs]
        assert stems == sorted(stems)

    def test_progress_callback_called(self, tmp_photo_dir: Path) -> None:
        calls: list[tuple[int, int]] = []
        scan_folders([str(tmp_photo_dir)], progress_callback=lambda c, t: calls.append((c, t)))
        assert len(calls) > 0
        assert calls[-1][0] == calls[-1][1]  # last call: current == total

    def test_empty_folder_returns_empty(self, tmp_path: Path) -> None:
        pairs = scan_folders([str(tmp_path)])
        assert pairs == []

    def test_nonexistent_folder_skipped(self) -> None:
        pairs = scan_folders(["/nonexistent/path/xyz"])
        assert pairs == []

    def test_pair_id_format(self, tmp_photo_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        for p in pairs:
            assert p.pair_id == f"{p.folder}::{p.stem}"

    def test_multiple_folders(self, tmp_path: Path, tmp_photo_dir: Path) -> None:
        second = tmp_path / "empty"
        second.mkdir()
        pairs = scan_folders([str(tmp_photo_dir), str(second)])
        assert len(pairs) == _EXPECTED_PAIRS


# ---------------------------------------------------------------------------
# PhotoSession
# ---------------------------------------------------------------------------

class TestPhotoSession:
    def test_load_sets_pairs(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        assert session.total == _EXPECTED_PAIRS
        assert session.index == 0
        assert session.current is not None

    def test_navigation(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.next()
        assert session.index == 1
        session.previous()
        assert session.index == 0

    def test_navigation_clamps_at_boundaries(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.previous()
        assert session.index == 0  # clamp at 0
        session.go_to(_EXPECTED_PAIRS - 1)
        session.next()
        assert session.index == _EXPECTED_PAIRS - 1  # clamp at max

    def test_on_change_called_on_load(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        called: list[int] = []
        session.on_change(called.append)
        session.load(pairs, [str(tmp_photo_dir)])
        assert called == [0]

    def test_on_change_called_on_navigate(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        called: list[int] = []
        session.on_change(called.append)
        session.next()
        assert called == [1]

    def test_start_index_restored(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)], start_index=5)
        assert session.index == 5

    def test_load_empty_list(self, tmp_db: Path) -> None:
        session = PhotoSession()
        session.load([], [])
        assert session.total == 0
        assert session.current is None


# ---------------------------------------------------------------------------
# Mark operations
# ---------------------------------------------------------------------------

class TestMarkOperations:
    def _make_session(self, tmp_photo_dir: Path) -> PhotoSession:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        return session

    def test_mark_keep(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        session = self._make_session(tmp_photo_dir)
        pair = session.current
        assert pair is not None
        session.mark_keep()
        assert pair.mark_type == MarkType.KEEP
        # Verify persisted to DB
        marks = repository.get_all_marks()
        assert pair.pair_id in marks
        assert marks[pair.pair_id]["mark_type"] == "keep"

    def test_mark_folder_key(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        repository.save_binding(1, "/tmp/dest")
        session = self._make_session(tmp_photo_dir)
        pair = session.current
        assert pair is not None
        session.mark_folder_key(1)
        assert pair.mark_type == MarkType.FOLDER_KEY
        assert pair.folder_key == 1
        marks = repository.get_all_marks()
        assert marks[pair.pair_id]["folder_key"] == 1

    def test_unmark(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        session = self._make_session(tmp_photo_dir)
        pair = session.current
        assert pair is not None
        session.mark_keep()
        session.unmark()
        assert pair.mark_type == MarkType.NONE
        marks = repository.get_all_marks()
        assert pair.pair_id not in marks

    def test_marks_survive_reload(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        session = self._make_session(tmp_photo_dir)
        pair = session.current
        assert pair is not None
        pair_id = pair.pair_id
        session.mark_keep()
        # Simulate app restart: reload session
        pairs2 = scan_folders([str(tmp_photo_dir)])
        session2 = PhotoSession()
        session2.load(pairs2, [str(tmp_photo_dir)])
        match = next(p for p in session2.pairs if p.pair_id == pair_id)
        assert match.mark_type == MarkType.KEEP

    def test_toggle_keep(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        session = self._make_session(tmp_photo_dir)
        svc = MarkService(session)
        pair = session.current
        assert pair is not None
        svc.toggle_keep()
        assert pair.mark_type == MarkType.KEEP
        svc.toggle_keep()
        assert pair.mark_type == MarkType.NONE

    def test_apply_folder_key_no_binding_returns_false(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        session = self._make_session(tmp_photo_dir)
        svc = MarkService(session)
        result = svc.apply_folder_key(9)  # key 9 has no binding
        assert result is False

    def test_apply_folder_key_with_binding(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        repository.save_binding(2, "/tmp/dest2")
        session = self._make_session(tmp_photo_dir)
        svc = MarkService(session)
        result = svc.apply_folder_key(2)
        assert result is True
        assert session.current.mark_type == MarkType.FOLDER_KEY

    def test_remove_pairs_clears_session_and_db(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        session = self._make_session(tmp_photo_dir)
        pair0 = session.pairs[0]
        pair1 = session.pairs[1]
        session.mark_keep()
        session.go_to(1)
        session.mark_keep()

        assert repository.get_all_marks().get(pair0.pair_id) is not None
        assert repository.get_all_marks().get(pair1.pair_id) is not None

        session.remove_pairs([pair0.pair_id, pair1.pair_id])

        # Removed from memory
        assert pair0.pair_id not in [p.pair_id for p in session.pairs]
        assert pair1.pair_id not in [p.pair_id for p in session.pairs]
        assert session.total == _EXPECTED_PAIRS - 2

        # Removed from DB
        marks = repository.get_all_marks()
        assert pair0.pair_id not in marks
        assert pair1.pair_id not in marks


# ---------------------------------------------------------------------------
# resolve_moves + execute_moves
# ---------------------------------------------------------------------------

class TestMoveService:
    def test_resolve_keep_without_default_returns_unresolved(self, tmp_photo_dir: Path, tmp_db: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.mark_keep()
        pending, unresolved = resolve_moves(session.pairs)
        assert len(pending) == 0
        assert len(unresolved) == 1

    def test_resolve_keep_with_default_adds_to_pending(self, tmp_photo_dir: Path, tmp_db: Path, target_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.mark_keep()
        pending, unresolved = resolve_moves(session.pairs, default_keep_folder=str(target_dir))
        assert len(pending) == 1
        assert len(unresolved) == 0

    def test_resolve_folder_key_with_binding(self, tmp_photo_dir: Path, tmp_db: Path, target_dir: Path) -> None:
        repository.save_binding(3, str(target_dir))
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.mark_folder_key(3)
        pending, unresolved = resolve_moves(session.pairs)
        assert len(pending) == 1

    def test_execute_moves_jpg_and_raw(self, tmp_photo_dir: Path, tmp_db: Path, target_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        # Mark first 3 pairs as KEEP
        for i in range(3):
            session.go_to(i)
            session.mark_keep()
        pending, _ = resolve_moves(session.pairs, default_keep_folder=str(target_dir))
        assert len(pending) == 3
        result = execute_moves(pending)
        assert result.moved == 6  # 3 JPG + 3 RAW
        assert result.errors == []
        jpg_dir = target_dir / "JPG"
        raw_dir = target_dir / "RAW"
        assert len(list(jpg_dir.iterdir())) == 3
        assert len(list(raw_dir.iterdir())) == 3

    def test_execute_moves_progress_callback(self, tmp_photo_dir: Path, tmp_db: Path, target_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.go_to(0)
        session.mark_keep()
        pending, _ = resolve_moves(session.pairs, default_keep_folder=str(target_dir))
        calls: list[tuple[int, int]] = []
        execute_moves(pending, progress_callback=lambda c, t: calls.append((c, t)))
        assert len(calls) > 0

    def test_execute_moves_none_marked(self, tmp_photo_dir: Path, tmp_db: Path, target_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        pending, _ = resolve_moves(session.pairs)
        result = execute_moves(pending)
        assert result.moved == 0

    def test_source_files_removed_after_move(self, tmp_photo_dir: Path, tmp_db: Path, target_dir: Path) -> None:
        pairs = scan_folders([str(tmp_photo_dir)])
        session = PhotoSession()
        session.load(pairs, [str(tmp_photo_dir)])
        session.go_to(0)
        session.mark_keep()
        first = session.current
        assert first is not None
        jpg_src = Path(first.jpg_path)
        raw_src = Path(first.raw_path)
        pending, _ = resolve_moves(session.pairs, default_keep_folder=str(target_dir))
        execute_moves(pending)
        assert not jpg_src.exists()
        assert not raw_src.exists()


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class TestRepository:
    def test_save_and_get_binding(self, tmp_db: Path) -> None:
        repository.save_binding(5, "/tmp/foo", "foo label")
        bindings = repository.get_all_bindings()
        assert 5 in bindings
        assert bindings[5]["path"] == "/tmp/foo"
        assert bindings[5]["label"] == "foo label"

    def test_delete_binding(self, tmp_db: Path) -> None:
        repository.save_binding(5, "/tmp/foo")
        repository.delete_binding(5)
        bindings = repository.get_all_bindings()
        assert 5 not in bindings

    def test_default_keep_folder(self, tmp_db: Path) -> None:
        assert repository.get_default_keep_folder() == ""
        repository.save_default_keep_folder("/tmp/keep")
        assert repository.get_default_keep_folder() == "/tmp/keep"
        repository.clear_default_keep_folder()
        assert repository.get_default_keep_folder() == ""

    def test_session_state(self, tmp_db: Path) -> None:
        assert repository.get_session() is None
        repository.save_session(["/tmp/a", "/tmp/b"], 7)
        s = repository.get_session()
        assert s is not None
        assert s["last_index"] == 7
        assert s["source_folders"] == ["/tmp/a", "/tmp/b"]
