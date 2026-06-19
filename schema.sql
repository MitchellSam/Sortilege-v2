PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Paths inside the output tree stored RELATIVE to output root (drive letters change).
-- Source paths on other volumes stored absolute.
-- All writes funnel through registry.py (single-writer discipline).

CREATE TABLE taxonomy_node (
    id                   INTEGER PRIMARY KEY,
    parent_id            INTEGER REFERENCES taxonomy_node(id),
    name                 TEXT NOT NULL,
    rel_path             TEXT NOT NULL UNIQUE,
    description          TEXT,
    is_system            INTEGER NOT NULL DEFAULT 0,
    embedding            BLOB,
    embedding_updated_at TEXT,
    created_at           TEXT NOT NULL,
    UNIQUE(parent_id, name)
);

CREATE TABLE file (
    -- One row per captured file. For keepers this becomes the canonical
    -- destination record. For dupes this records the skip decision
    -- (state='skipped', current_rel_path stays NULL).
    id                INTEGER PRIMARY KEY,
    sha256            TEXT NOT NULL,
    phash             INTEGER,
    size              INTEGER NOT NULL,
    mtime             TEXT,
    ext               TEXT,
    source_path       TEXT,
    current_rel_path  TEXT,
    state             TEXT NOT NULL,
    error_detail      TEXT,
    proposed_node_id  INTEGER REFERENCES taxonomy_node(id),
    planned_op        TEXT,
    dupe_of_file_id   INTEGER REFERENCES file(id),
    dupe_kind         TEXT,
    tier              INTEGER,
    confidence        REAL,
    reasoning         TEXT,
    extracted_snippet TEXT,
    proposal_updated_at TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX idx_file_sha256 ON file(sha256);
CREATE INDEX idx_file_state  ON file(state);
CREATE INDEX idx_file_phash  ON file(phash) WHERE phash IS NOT NULL;

CREATE TABLE file_embedding (
    file_id   INTEGER PRIMARY KEY REFERENCES file(id),
    embedding BLOB NOT NULL
);

CREATE TABLE known_source (
    -- Cross-drive originals left in place after copy; never re-copied.
    -- Serves as both a path-based pre-hash lookup and a hash-based fallback.
    id                 INTEGER PRIMARY KEY,
    source_path        TEXT NOT NULL,
    sha256             TEXT NOT NULL,
    duplicates_file_id INTEGER NOT NULL REFERENCES file(id),
    recorded_at        TEXT NOT NULL,
    UNIQUE(source_path, sha256)
);
CREATE INDEX idx_known_source_hash ON known_source(sha256);
CREATE INDEX idx_known_source_path ON known_source(source_path);

CREATE TABLE batch (
    id           INTEGER PRIMARY KEY,
    confirmed_at TEXT NOT NULL,
    file_count   INTEGER NOT NULL,
    undone       INTEGER NOT NULL DEFAULT 0,
    undone_at    TEXT
);

CREATE TABLE action_log (
    id          INTEGER PRIMARY KEY,
    batch_id    INTEGER REFERENCES batch(id),
    file_id     INTEGER NOT NULL REFERENCES file(id),
    action      TEXT NOT NULL,
    from_path   TEXT,
    to_path     TEXT,
    executed_at TEXT NOT NULL
);
CREATE INDEX idx_action_batch ON action_log(batch_id);

CREATE TABLE correction (
    id               INTEGER PRIMARY KEY,
    file_id          INTEGER NOT NULL REFERENCES file(id),
    proposed_node_id INTEGER REFERENCES taxonomy_node(id),
    actual_node_id   INTEGER NOT NULL REFERENCES taxonomy_node(id),
    tier             INTEGER,
    confidence       REAL,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_correction_actual ON correction(actual_node_id);

CREATE TABLE suggestion (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL,
    payload        TEXT NOT NULL,
    evidence_count INTEGER NOT NULL,
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    resolved_at    TEXT
);

CREATE TABLE api_usage (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL NOT NULL,
    file_id       INTEGER REFERENCES file(id)
);

PRAGMA user_version = 1;
