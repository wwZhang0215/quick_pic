from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_FILE = Path.home() / ".quickpic" / "data.db"
_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def _get_connection() -> sqlite3.Connection:
    """Return a connection to the application database, creating it if needed."""
    _DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    schema = _SCHEMA_FILE.read_text(encoding="utf-8")
    with _get_connection() as conn:
        conn.executescript(schema)
    logger.info("Database initialised at %s", _DB_FILE)


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------

def save_mark(pair_id: str, mark_type: str, folder_key: int | None = None) -> None:
    """Insert or replace a mark record."""
    now = datetime.now(tz=timezone.utc).isoformat()
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO marks (pair_id, mark_type, folder_key, marked_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pair_id) DO UPDATE SET
                mark_type  = excluded.mark_type,
                folder_key = excluded.folder_key,
                marked_at  = excluded.marked_at
            """,
            (pair_id, mark_type, folder_key, now),
        )


def delete_mark(pair_id: str) -> None:
    """Remove a mark (set photo back to 'none')."""
    with _get_connection() as conn:
        conn.execute("DELETE FROM marks WHERE pair_id = ?", (pair_id,))


def get_all_marks() -> dict[str, dict]:
    """Return {pair_id: {mark_type, folder_key}} for all marked photos."""
    with _get_connection() as conn:
        rows = conn.execute("SELECT pair_id, mark_type, folder_key FROM marks").fetchall()
    return {
        row["pair_id"]: {"mark_type": row["mark_type"], "folder_key": row["folder_key"]}
        for row in rows
    }


# ---------------------------------------------------------------------------
# Folder bindings
# ---------------------------------------------------------------------------

def save_binding(key: int, path: str, label: str = "") -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO folder_bindings (key, path, label) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET path = excluded.path, label = excluded.label
            """,
            (key, path, label),
        )


def delete_binding(key: int) -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM folder_bindings WHERE key = ?", (key,))


def get_all_bindings() -> dict[int, dict]:
    """Return {key: {path, label}} for all bound folder keys."""
    with _get_connection() as conn:
        rows = conn.execute("SELECT key, path, label FROM folder_bindings").fetchall()
    return {row["key"]: {"path": row["path"], "label": row["label"]} for row in rows}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_KEY_DEFAULT_KEEP_FOLDER = "default_keep_folder"


def get_default_keep_folder() -> str:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (_KEY_DEFAULT_KEEP_FOLDER,)
        ).fetchone()
    return row["value"] if row else ""


def save_default_keep_folder(path: str) -> None:
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_KEY_DEFAULT_KEEP_FOLDER, path),
        )


def clear_default_keep_folder() -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (_KEY_DEFAULT_KEEP_FOLDER,))


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def save_session(source_folders: list[str], last_index: int) -> None:
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_state (id, last_index, source_folders)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_index     = excluded.last_index,
                source_folders = excluded.source_folders
            """,
            (last_index, json.dumps(source_folders)),
        )


def get_session() -> dict | None:
    """Return {last_index, source_folders} or None if no session exists."""
    with _get_connection() as conn:
        row = conn.execute("SELECT last_index, source_folders FROM session_state WHERE id = 1").fetchone()
    if row is None:
        return None
    return {
        "last_index": row["last_index"],
        "source_folders": json.loads(row["source_folders"]),
    }
