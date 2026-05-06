-- Folder key bindings: number keys 1-9 mapped to destination folders
CREATE TABLE IF NOT EXISTS folder_bindings (
    key   INTEGER PRIMARY KEY CHECK (key BETWEEN 1 AND 9),
    path  TEXT NOT NULL,
    label TEXT
);

-- Photo marks: persists user culling decisions
CREATE TABLE IF NOT EXISTS marks (
    pair_id     TEXT PRIMARY KEY,   -- "{folder}::{stem}"
    mark_type   TEXT NOT NULL CHECK (mark_type IN ('keep', 'folder_key')),
    folder_key  INTEGER,            -- NULL when mark_type = 'keep'
    marked_at   TEXT NOT NULL       -- ISO 8601 timestamp
);

-- Key-value settings (default_keep_folder, etc.)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Single-row table for session state (last opened folders + cursor position)
CREATE TABLE IF NOT EXISTS session_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    last_index      INTEGER NOT NULL DEFAULT 0,
    source_folders  TEXT NOT NULL DEFAULT '[]'  -- JSON array of folder paths
);
