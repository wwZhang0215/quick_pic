"""Pytest fixtures for QuickPic tests."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Test photo source directory
_PHOTO_SRC = Path("/Users/xpeng/Downloads/10660505")


@pytest.fixture()
def tmp_photo_dir(tmp_path: Path) -> Path:
    """Copy test photos into a fresh temp directory."""
    if not _PHOTO_SRC.is_dir():
        pytest.skip(f"Test photo folder not found: {_PHOTO_SRC}")
    dest = tmp_path / "photos"
    shutil.copytree(_PHOTO_SRC, dest)
    return dest


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect DB to a temp file so tests don't touch ~/.quickpic/data.db."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.repository._DB_FILE", db_path)
    from app.db import repository
    repository.init_db()
    return db_path


@pytest.fixture()
def target_dir(tmp_path: Path) -> Path:
    """Empty directory to use as move target."""
    d = tmp_path / "target"
    d.mkdir()
    return d
