# Sortilege — Development Spec for Claude Code
**Version:** v5.1 (June 2026)
**Read this entire document before writing any code.**

---

## What This App Does

Sortilege is a personal AI-powered file organization system for Windows. The user drags files from any drive onto a small desktop drop window. The system reads files **in place** (no relocation on drop), deduplicates via hash, classifies via a five-tier cascade (rules → embeddings → LLM), and proposes destinations under `E:\organized\`. Proposed actions accumulate silently; the user opens a browser-based review UI on their own schedule, confirms grouped actions, and can undo any batch. The app moves same-drive keepers, copies cross-drive keepers (originals left for the user), and skips dupes entirely. **The app never deletes user files.**

---

## Tech Stack

- **Language:** Python 3.11+
- **Backend:** FastAPI + uvicorn (resident server, Windows startup task)
- **Frontend:** React (served by FastAPI as static files)
- **Database:** SQLite (WAL mode, single-writer discipline via `registry.py`)
- **Embeddings:** Nomic Embed via `sentence-transformers` (local, zero API cost); model stays loaded in the resident server process
- **LLM API:** Anthropic (Claude Haiku for Tier 4 + folder descriptions, Claude Sonnet for Tier 5)
- **API key storage:** Windows Credential Manager via `keyring`
- **Drop window:** `pywebview` (lightweight desktop shell posting paths to backend); fallback option is Tauri if DnD payload handling is insufficient
- **Live progress:** Server-Sent Events (SSE) via `sse-starlette` — no WebSockets
- **Toast notifications:** `winotify` (or `windows-toasts` / `plyer` — whichever is least fragile)
- **Package management:** `uv` for environment setup

---

## Codebase Structure

```
sortilege/
├── core/
│   ├── cascade.py        # five-tier classification orchestrator
│   ├── embeddings.py     # Nomic Embed wrapper: embed text, compare, update folder embeddings
│   ├── extractor.py      # text/content extraction (pdf, docx, xlsx, pptx, images, etc.)
│   ├── registry.py       # SQLite interface — ALL reads/writes go through this module
│   └── taxonomy.py       # taxonomy node CRUD on top of registry
├── librarian/
│   ├── intake.py         # receives dropped paths from drop window, enqueues for processing
│   ├── router.py         # full-path resolution loop: cascade → planned_op → hold
│   ├── deduper.py        # hash (SHA-256) + pHash (imagehash) duplicate detection
│   ├── learner.py        # embedding updates on UI move (positive/negative signals)
│   └── suggester.py      # passive folder + rule proposals from correction log
├── api/
│   ├── routes.py         # FastAPI routes (REST + SSE endpoints)
│   └── sse.py            # SSE streaming helpers
├── ui/                   # React frontend (built to static, served by FastAPI)
├── dropwindow/           # pywebview drop-target shell
│   └── app.py            # captures DnD paths, POSTs to backend
├── cli.py                # dev-only dry-run harness for threshold calibration
├── setup.bat             # one-time: uv env + deps, start server, open /setup wizard
├── config.json           # user configuration (see below)
├── rules.yaml            # Tier 2 deterministic rules
└── schema.sql            # SQLite schema (source of truth — apply on first run)
```

---

## SQLite Schema

Apply this as `schema.sql` on first run. All paths inside the output tree are stored **relative** to the output root (drive letters change). Source paths on other volumes are stored **absolute**. Use `\\?\` long-path prefix on all filesystem operations.

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE taxonomy_node (
    id            INTEGER PRIMARY KEY,
    parent_id     INTEGER REFERENCES taxonomy_node(id),
    name          TEXT NOT NULL,
    rel_path      TEXT NOT NULL UNIQUE,
    description   TEXT,
    is_system     INTEGER NOT NULL DEFAULT 0,
    embedding     BLOB,
    embedding_updated_at TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(parent_id, name)
);

CREATE TABLE file (
    -- One row per captured file. For keepers this becomes the canonical
    -- destination record. For dupes this records the skip decision
    -- (state='skipped', current_rel_path stays NULL).
    id            INTEGER PRIMARY KEY,
    sha256        TEXT NOT NULL,
    phash         INTEGER,
    size          INTEGER NOT NULL,
    mtime         TEXT,
    ext           TEXT,
    source_path   TEXT,
    current_rel_path TEXT,
    state         TEXT NOT NULL,
    error_detail  TEXT,
    proposed_node_id  INTEGER REFERENCES taxonomy_node(id),
    planned_op        TEXT,     -- 'move' | 'copy' | 'skip'
    dupe_of_file_id   INTEGER REFERENCES file(id),
    dupe_kind         TEXT,     -- 'exact' | 'perceptual'
    tier          INTEGER,
    confidence    REAL,
    reasoning     TEXT,
    extracted_snippet TEXT,
    proposal_updated_at TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_file_sha256 ON file(sha256);
CREATE INDEX idx_file_state  ON file(state);
CREATE INDEX idx_file_phash  ON file(phash) WHERE phash IS NOT NULL;

CREATE TABLE file_embedding (
    file_id   INTEGER PRIMARY KEY REFERENCES file(id),
    embedding BLOB NOT NULL
);

CREATE TABLE known_source (
    id           INTEGER PRIMARY KEY,
    source_path  TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    duplicates_file_id INTEGER NOT NULL REFERENCES file(id),
    recorded_at  TEXT NOT NULL,
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
    id        INTEGER PRIMARY KEY,
    batch_id  INTEGER REFERENCES batch(id),
    file_id   INTEGER NOT NULL REFERENCES file(id),
    action    TEXT NOT NULL,
    from_path TEXT,
    to_path   TEXT,
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
```

### File State Machine

```
captured → queued → classifying → held ←──────────────┐
                         │           │                 │
                         │           ├→ moved ─────────┤ (undo_move → held)
                         │           ├→ copied ────────┘ (undo_copy → removes dest, clears known_source → held)
                         │           └→ skipped              (terminal; not undoable)
                         ├→ budget_paused → queued       (ceiling raised)
                         └→ error
```

Valid `action_log.action` values: `'move'`, `'copy'`, `'undo_move'`, `'undo_copy'`, `'folder_create'`.

---

## Module Contracts

Build in this order. Each module's public interface is described below.

### 1. `core/registry.py`

Single-writer SQLite interface. Every database read/write in the entire app goes through this module. No other module imports `sqlite3`.

Key responsibilities:
- Initialize DB from `schema.sql` on first run (check `PRAGMA user_version`)
- Connection management (WAL mode, foreign keys ON)
- CRUD for every table
- Transaction wrappers for batch confirm and batch undo (atomic)
- Hash lookups: `get_file_by_sha256(hash)`, `get_known_source_by_path(path)`, `get_known_source_by_hash(hash)`
- State transitions: enforce the state machine (reject invalid transitions)

### 2. `core/taxonomy.py`

Taxonomy node CRUD on top of registry. Manages the folder tree.

Key responsibilities:
- `create_node(parent_id, name, description=None, is_system=False)` — generates `rel_path` from ancestry, creates physical folder on output drive
- `get_children(node_id)` → list of child nodes
- `get_subtree(node_id)` → full subtree as nested dict (for LLM prompt context)
- `get_all_nodes()` → flat list (for tree UI)
- `get_node_by_rel_path(path)` → node or None
- Seed taxonomy creation (nine folders + unsorted) during setup
- `unsorted` node: `is_system=1`, excluded from embedding matching in all queries

### 3. `core/extractor.py`

Text and metadata extraction from files. Used by Tiers 3–5 for embedding generation and LLM context.

Key responsibilities:
- Route by file extension to appropriate extractor
- PDF → `pypdf`; DOCX → `python-docx`; XLSX → `openpyxl`; PPTX → `python-pptx`; text → `chardet` + read; images → EXIF via `Pillow`; `.lnk` → `LnkParse3`
- Return structured result: `{ text: str, metadata: dict, exif: dict|None, thumbnail: bytes|None }`
- `extracted_snippet`: first 500 chars of extracted text, cached in file row
- GPS coordinates in EXIF → reverse geocode via `reverse_geocoder`
- All path handling uses `\\?\` prefix for long-path support
- Graceful failure: unreadable files → return empty result + error detail, never crash

### 4. `core/embeddings.py`

Nomic Embed wrapper. The model is loaded once at server start and stays in memory.

Key responsibilities:
- `embed_text(text) → np.ndarray` (float32[768])
- `embed_file(file_id)` — extract text → embed → store in `file_embedding`
- `update_folder_embedding(node_id)` — recompute from: description, child names, representative file embeddings, correction-weighted history
- `compare(embedding_a, embedding_b) → float` (cosine similarity)
- `find_best_child(parent_node_id, file_embedding, floor) → (node_id, score) | None` — returns best child above absolute floor, or None if no child clears it
- Batch embed for bulk processing

### 5. `core/cascade.py`

Five-tier classification orchestrator. Given a file, returns a proposed destination path and the tier/confidence that resolved it.

```python
def classify(file_id: int) -> ClassificationResult:
    """
    Returns: ClassificationResult(
        proposed_node_id: int,
        planned_op: 'move' | 'copy' | 'skip',
        tier: int,
        confidence: float,
        reasoning: str,
        dupe_of_file_id: int | None,
        dupe_kind: str | None,
    )
    """
```

Tier execution order:
1. **Pre-hash path check:** `known_source` lookup by `source_path` → skip without reading
2. **Tier 1 (hash):** SHA-256 → match in `file` table or `known_source` by hash → skip
3. **Tier 2 (rules):** load `rules.yaml`, apply in signal-priority order (EXIF → filename pattern → extension). No folder-path signal.
4. **Tier 3 (embeddings):** recursive descent via `embeddings.find_best_child()` from root; place at deepest match above absolute floor. **Partial-depth placement is correct, not failure.** If no top-level folder clears the floor → continue to Tier 4.
5. **Tier 4 (Haiku):** one API call with filename, extension, size, dates, extracted_snippet, and the **full taxonomy subtree** (names + descriptions). Returns a full destination path. Check against `api_usage` ceiling first; if exceeded → `budget_paused` state.
6. **Tier 5 (Sonnet):** one API call with full extracted text or image thumbnail, **plus the full taxonomy subtree**. Vision for scanned documents. Returns a full destination path. Below confidence floor → `unsorted`.

`planned_op` is determined by source vs. destination drive: same drive → `'move'`, different drive → `'copy'`, dupe → `'skip'`.

**Threshold policy:** per-tier thresholds in `config.json` are **placeholders**. They must be calibrated empirically via `cli.py` dry-run on the first real batch before being trusted.

### 6. `cli.py` (dev-only dry-run harness)

```bash
python cli.py dry-run --source "C:\Users\...\Downloads" --limit 100
```

Runs the cascade against real files. Logs tier, score, proposed destination for every file. Moves nothing. Outputs a CSV for threshold analysis. Does not require the UI or drop window.

### 7. `librarian/deduper.py`

Hash and perceptual-hash duplicate detection.

- `compute_sha256(filepath) → str` — long-path aware; streams in chunks for large files
- `compute_phash(filepath) → int` — via `imagehash`; images only
- `check_known_source(source_path) → file_id | None` — pre-hash path lookup
- `check_dupe_by_hash(sha256) → file_id | None`
- `check_dupe_by_phash(phash, threshold) → file_id | None` — hamming distance; load all phashes into memory (42K × 8 bytes = 336KB), numpy popcount, sub-millisecond
- `record_known_source(source_path, sha256, canonical_file_id)` — after cross-drive copy
- `remove_known_source(file_id)` — on undo_copy

### 8. `librarian/router.py`

Full-path resolution loop. Receives a list of captured file paths, orchestrates dedup → cascade → hold.

- `process_batch(paths: list[str])` — main entry point from `intake.py`
- For each path: stability check (file exists, readable, non-zero), then `cascade.classify()`, then update file row with proposal, set state to `held`
- After batch completes: fire SSE event, trigger Windows toast notification ("N files ready for review")
- Respect `checkpoint_batch_size` from config for progress reporting

### 9. `librarian/intake.py`

Receives dropped paths from the drop window (HTTP POST), enqueues for processing.

- `POST /api/intake` — accepts `{ paths: string[] }`
- Validates each path exists and is readable
- Creates `file` rows in `captured` state
- Hands off to `router.process_batch()` (async, non-blocking — returns immediately so the drop window doesn't freeze)

### 10. `dropwindow/app.py`

Desktop drop-target using `pywebview`. A small always-on-top window that accepts drag-and-drop.

- On drop: read source file paths from the DnD payload
- POST paths to `http://localhost:8000/api/intake`
- Visual feedback: brief flash or checkmark on successful POST
- Starts with the server (registered as part of the startup task)
- Minimal UI: app icon, maybe a file count badge, no complex chrome

### 11. `librarian/learner.py`

Embedding updates triggered by user moves in the review UI.

- `on_move(file_id, proposed_node_id, actual_node_id)`:
  - If `proposed_node_id != actual_node_id`: record a `correction` row
  - Update embedding for `actual_node_id` (positive signal — file's embedding contributes)
  - Update embedding for `proposed_node_id` if not None (negative signal — reduce file's contribution)
  - If `actual_node_id` is `unsorted`: file re-enters routing from root with updated embeddings
- Immediate updates, no batching

### 12. `librarian/suggester.py`

Generates passive folder and rule proposals from the correction log.

**Folder proposals:**
- Scan `held` files grouped by proposed parent. If N+ files are held at the same level because no child matched → propose a new child folder with a name/description derived from the cluster's content embeddings.
- Ghost nodes in the UI; accept creates the real folder + seeds its embedding + re-resolves held files.

**Rule proposals:**
- Scan `correction` table for patterns: N+ corrections with the same extension/filename-pattern landing at the same destination → propose a Tier 2 rule.
- Accept appends to `rules.yaml`.

**Anti-nagging:** dismissed suggestions persist with `status='dismissed'`. Re-proposal requires evidence_count to have grown by a meaningful margin (e.g. 2× the count at dismissal).

### 13. `api/routes.py`

FastAPI application. Serves the React frontend as static files and exposes the REST + SSE API.

Key endpoints:
- `POST /api/intake` — receive paths from drop window
- `GET /api/files?state=held` — files grouped by proposed destination for review UI
- `GET /api/taxonomy` — full tree for the sidebar
- `POST /api/confirm` — `{ file_ids: int[], overrides: { file_id: node_id }[] }` → execute batch
- `POST /api/undo` — `{ batch_id: int }` → reverse batch
- `POST /api/folder` — `{ parent_id: int, name: str }` → create folder, generate description via Haiku
- `POST /api/suggestion/{id}/accept` — accept a folder or rule suggestion
- `POST /api/suggestion/{id}/dismiss` — dismiss
- `GET /api/sse/progress` — SSE stream for classification progress + toast triggers
- `GET /api/config` — current config for settings display
- `POST /api/config` — update config
- `GET /api/batches` — recent batches for undo history

**Batch confirm logic (atomic transaction):**
1. For each file in the batch:
   - If `planned_op == 'move'`: `shutil.move()` with long-path support → record in `action_log`
   - If `planned_op == 'copy'`: `shutil.copy2()` → SHA-256 verify destination → record in `action_log` → create `known_source` row
   - If `planned_op == 'skip'`: no filesystem action, just state transition
   - If user overrode the destination (drag to different folder): use overridden `node_id`, record `correction`
2. Update file states (`held → moved | copied | skipped`)
3. Trigger `learner.on_move()` for each file
4. Create `batch` row
5. If any file had `planned_op == 'copy'`: return the list of now-redundant source paths in the response (for the "safe to delete" UI display)

**Batch undo logic (atomic transaction):**
1. For each `action_log` row in the batch (reverse order):
   - `undo_move`: move file back from destination to `source_path`
   - `undo_copy`: delete destination copy + remove `known_source` row
2. Reset file states to `held`
3. Set `batch.undone = 1`

### 14. Setup Wizard

Served at `/setup` when config is incomplete. Five steps (see handoff doc for full spec):

1. Output destination (validate drive, space)
2. API key (keyring → validate with Haiku ping)
3. Environment check (OneDrive stub detection on source folders)
4. Seed taxonomy (editable list of nine folders; unsorted locked)
5. Finish (create tree, register startup task, launch drop window, flip config flag)

Wizard restarts from step 1 on abandonment (no resume state). API key persists via keyring.

---

## Configuration

`config.json` lives in `workspace_dir`:

```json
{
  "output_root": "E:\\organized",
  "workspace_dir": "C:\\sortilege-workspace",
  "confidence_thresholds": {
    "_comment": "PLACEHOLDERS — calibrate via cli.py dry-run before trusting",
    "tier2_rules_min": 0.85,
    "tier3_embedding_min": null,
    "tier4_haiku_min": 0.80,
    "tier5_sonnet_min": 0.70,
    "group_preselect_min": 0.85
  },
  "tier4_model": "claude-haiku-4-5-20251001",
  "tier5_model": "claude-sonnet-4-6",
  "description_model": "claude-haiku-4-5-20251001",
  "embedding_model": "nomic-embed-text",
  "api_cost_ceiling_usd": 10.00,
  "checkpoint_batch_size": 100,
  "min_size_for_api_bytes": 1024,
  "destination_space_buffer_pct": 10
}
```

`workspace_dir` contains: `sortilege.db`, `rules.yaml`, `config.json`, application logs.

---

## Python Dependencies

```
# stdlib: pathlib, hashlib, sqlite3, uuid, asyncio, shutil, os, json
keyring
chardet
imagehash
Pillow
pypdf
python-docx
openpyxl
python-pptx
reverse_geocoder
sentence-transformers
anthropic
fastapi
uvicorn
sse-starlette
pyyaml
LnkParse3
pywebview
winotify
numpy
```

Install via `uv`: `uv pip install -r requirements.txt`

---

## Execution Model — Critical Rules

1. **The app NEVER deletes user files.** Same-drive keepers are moved. Cross-drive keepers are copied (originals left). Dupes are skipped.
2. **Undo removes only app-created destination copies** (and their `known_source` entries). This does NOT violate the no-delete rule because destination copies are app-created artifacts, not user originals.
3. **All filesystem operations use `\\?\` long-path prefix** on Windows.
4. **`unsorted` is fallback-only** — `is_system=1`, excluded from Tier 3 embedding matching. Files land there only by falling below every confidence floor.
5. **One LLM API call per file** at Tiers 4/5. The call receives the taxonomy subtree and returns a full destination path. Never one call per depth level.
6. **Partial-depth placement is correct.** If Tier 3 matches `photos\vacation\` but no child clears the floor, the file is placed at `photos\vacation\`. This is not a failure.
7. **Cross-drive copy verification:** after `shutil.copy2()`, re-hash the destination and compare against the source hash. On mismatch → `error` state, do not proceed.
8. **Budget ceiling:** when `api_usage` sum exceeds ceiling, remaining API-tier files enter `budget_paused` state. Never silently dump to unsorted.
9. **Embedding model stays loaded.** `sentence-transformers` model is loaded once at server startup and kept in memory. Do not reload per-request.
10. **`rules.yaml` is the single source of truth for Tier 2.** No rules table in SQLite. Accepted rule suggestions append to the file.

---

## Build Order

Follow this sequence. Each step depends on the ones above it.

1. `schema.sql` → apply to SQLite
2. `core/registry.py` — SQLite interface
3. `core/taxonomy.py` — node CRUD
4. `core/extractor.py` — text extraction + long-path handling
5. `core/embeddings.py` — Nomic wrapper
6. `core/cascade.py` — five-tier orchestrator
7. `cli.py` — dry-run harness (validate cascade on real files before UI)
8. `librarian/deduper.py` — hash + pHash
9. `librarian/router.py` — batch processing loop
10. `librarian/intake.py` — HTTP path receiver
11. `dropwindow/app.py` — desktop drop target
12. `librarian/learner.py` — embedding updates on move
13. `librarian/suggester.py` — folder + rule proposals
14. `api/routes.py` — FastAPI routes + SSE + batch confirm/undo
15. `ui/` — React review UI (see separate Claude Design handoff)
16. Setup wizard (`/setup` route)
17. `setup.bat` — first-run script (uv, deps, start, open browser)

---

## What NOT to Build

These are explicitly rejected decisions. Do not implement them:

- Any form of file deletion, quarantine, or recycle logic
- A `watchdog` filesystem watcher (the drop window captures paths; there's no folder to watch)
- WebSocket connections (use SSE)
- A Rules UI / CRUD interface for rules.yaml
- An `_inbox` folder anywhere on any drive
- Per-folder threshold relaxation
- Per-level LLM calls (one call per file, full path)
- A `max_folder_depth` config or enforcement
- OCR / pytesseract (Tier 5 Sonnet vision handles scanned documents)
- Explorer/source-location move detection as a learning signal
- Application bundling (PyInstaller, etc.)
- A `misc\` folder (use `unsorted\` as fallback-only)
- Any second-level pre-seeded folders

---

## Filename Collision Policy

When two different files with the same name are routed to the same destination: append a deterministic suffix. Prefer short-hash: `document (a3f2).pdf`. Record the renamed path in the file row's `current_rel_path`. Never overwrite an existing file.

---

## API Prompt Templates

### Tier 4 (Haiku) — Metadata Classification
```
You are a file organizer. Given the file metadata and folder taxonomy below, 
return the best destination path for this file.

FILE:
- Filename: {filename}
- Extension: {ext}
- Size: {size} bytes
- Modified: {mtime}
- Content preview: {extracted_snippet}

TAXONOMY:
{taxonomy_subtree_json}

Respond with JSON only:
{
  "destination": "relative/path/to/folder",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explanation"
}
```

### Tier 5 (Sonnet) — Deep Classification
Same template but with full extracted text or image (as base64) instead of snippet, and the addition: "If this is a scanned document, use the image to determine content."

### Folder Description Generation (Haiku)
```
Generate a one-sentence description of a folder named "{folder_name}" 
that is a subfolder of "{parent_path}". The description should help an 
embedding model understand what files belong in this folder.
Respond with the description only, no quotes or formatting.
```
