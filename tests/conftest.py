"""Pytest fixtures for QuickPic tests."""
from __future__ import annotations

from pathlib import Path

import pytest

# Number of synthetic photo pairs created by tmp_photo_dir
PHOTO_COUNT = 6


@pytest.fixture()
def tmp_photo_dir(tmp_path: Path) -> Path:
    """Create a temp directory with synthetic JPG+ARW file pairs for testing."""
    dest = tmp_path / "photos"
    dest.mkdir()
    for i in range(1, PHOTO_COUNT + 1):
        stem = f"IMG_{i:04d}"
        (dest / f"{stem}.JPG").write_bytes(b"fake-jpg")
        (dest / f"{stem}.ARW").write_bytes(b"fake-raw")
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
