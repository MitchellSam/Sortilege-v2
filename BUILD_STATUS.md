# Sortilege — Build Status

**Last updated:** June 2026  
**Spec:** `Sortilege_Claude_Code_Spec.md` (primary) + `Sortilege_Handoff_v5.1.md` (context/rationale) + `Sortilege_Claude_Design_Prompt.md` (UI)  
**Read all three before continuing.** This file only records what's done, decisions made this session, and what comes next.

---

## What's Built (Spec Steps 1–17 of 17 — ALL COMPLETE)

| File | Status | Notes |
|---|---|---|
| `schema.sql` | Done | Full schema + indexes + `PRAGMA user_version = 1` |
| `rules.yaml` | Done | 9 seed rules; format documented below |
| `requirements.txt` | Done | All deps listed; install via `uv pip install -r requirements.txt` |
| `sortilege/core/registry.py` | Done | Single-writer SQLite; all tables; state machine enforced; atomic `execute_batch_confirm` / `execute_batch_undo` |
| `sortilege/core/taxonomy.py` | Done | Node CRUD; `seed_taxonomy()` creates 9 folders + unsorted; `get_subtree()` for LLM context |
| `sortilege/core/extractor.py` | Done | PDF/DOCX/XLSX/PPTX/images/text/.lnk; GPS reverse-geocode; `\\?\` long-path throughout; returns `ExtractionResult` |
| `sortilege/core/embeddings.py` | Done | Nomic Embed (load once via `load_model()`); `embed_file()`; `update_folder_embedding()`; `recursive_descent()` for Tier 3 |
| `sortilege/core/cascade.py` | Done | Full five-tier cascade; budget check before Tiers 4/5; single LLM call per file; `configure(rules_path)` must be called at startup |
| `cli.py` | Done | `python cli.py dry-run --source "..." --limit 100 [--no-api]`; outputs CSV for threshold calibration |
| `sortilege/librarian/deduper.py` | Done | SHA-256 + pHash; numpy vectorized hamming; known_source wrappers |
| `sortilege/librarian/router.py` | Done | `process_batch(paths)`; stability check → hash → classify → state transitions; SSE + toast |
| `sortilege/librarian/intake.py` | Done | FastAPI handler; path validation; background task dispatch |
| `sortilege/dropwindow/app.py` | Done | pywebview EdgeChromium; DnD → POST /api/intake; visual feedback |
| `sortilege/librarian/learner.py` | Done | `on_move()`; correction recording; embedding updates; unsorted re-queue |
| `sortilege/librarian/suggester.py` | Done | `generate_suggestions()`; folder + rule proposals; anti-nagging |
| `sortilege/api/sse.py` | Done | Thread-safe event bus; fan-out to multiple SSE clients |
| `sortilege/api/routes.py` | Done | All endpoints; batch confirm/undo; setup wizard routes; static UI serving |
| `sortilege/ui/` | Done | Vite React; ReviewScreen + FolderTree + ReviewQueue + GroupRow; SetupWizard 5-step; Settings |
| `main.py` | Done | Server entry point; starts drop window in thread |
| `setup.bat` | Done | uv env, pip install, npm build, start server, open /setup |

**Package init files** created for: `sortilege/`, `sortilege/core/`, `sortilege/librarian/`, `sortilege/api/`, `sortilege/dropwindow/`.

---

## Decisions Made This Session (Not in Spec)

### OneDrive check
**This machine is clear.** Desktop/Documents/Downloads are at standard `C:\Users\msam4\` paths, not OneDrive-redirected. Files On-Demand is off. Zero stubs found. Not a blocker. The `extractor.py` does not need OneDrive stub handling for this machine, but if you add it later, check `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x00400000) via `kernel32.GetFileAttributesW`.

### React toolchain
**Vite.** Scaffold with: `npm create vite@latest ui -- --template react` (run from `sortilege/` directory so it creates `sortilege/ui/`).

### `rules.yaml` schema
```yaml
rules:
  - name: <string>
    match:
      has_exif: true            # bool — file has camera EXIF Make/Model
      has_gps: true             # bool — file has GPS coordinates
      exif_make: "Apple"        # string — "*" = any value present
      filename_pattern: "IMG_*" # fnmatch glob, case-insensitive, filename only
      extension: "pdf"          # string or list of strings, no dot
    destination: "financial"    # taxonomy_node.rel_path value
    confidence: 0.88            # float 0-1
```
All match fields are AND'd. Checked in list order; first match wins. Accepted rule proposals from the UI are appended here.

### SSE event payloads (`GET /api/sse/progress`)
```python
# event: file_classified
{"file_id": 123, "filename": "IMG_4832.heic", "state": "held", "tier": 2, "confidence": 0.95, "proposed_path": "photos"}

# event: batch_ready  (fires when router.process_batch() finishes — triggers toast + UI refresh)
{"held": 12, "skipped": 2, "errors": 0, "budget_paused": 0}

# event: budget_paused
{"paused_count": 47, "spent_usd": 10.02, "ceiling_usd": 10.00}
```

### `GET /api/files?state=held` response shape
```json
{
  "groups": [
    {
      "node_id": 42,
      "rel_path": "photos\\vacation\\japan",
      "kind": "destination",
      "planned_op": "move",
      "file_count": 412,
      "min_confidence": 0.91,
      "files": [
        {
          "id": 123, "filename": "IMG_4832.heic",
          "source_path": "C:\\Users\\msam4\\Downloads\\IMG_4832.heic",
          "size": 3563520, "mtime": "2023-09-14T10:23:00", "ext": "heic",
          "tier": 2, "confidence": 0.95, "reasoning": "...", "planned_op": "move",
          "dupe_of_path": null
        }
      ]
    }
  ],
  "suggestions": [
    {"id": 1, "kind": "folder", "payload": {"proposed_path": "financial\\taxes\\2023", "parent_node_id": 5}, "evidence_count": 38, "status": "pending"}
  ],
  "counts": {"held": 429, "skipped": 17, "errors": 3, "budget_paused": 0}
}
```
`kind` values: `"destination"` | `"dupe"` | `"error"`

### `POST /api/confirm` response shape
```json
{
  "batch_id": 7, "moved": 412, "copied": 28, "skipped": 17, "errors": 0,
  "redundant_sources": [
    {"file_id": 201, "source_path": "C:\\Users\\...\\photo.jpg", "destination_rel_path": "photos\\vacation\\photo.jpg"}
  ]
}
```

### Windows startup task
`schtasks /create /tn "Sortilege" /tr "\"<venv_python>\" \"<main.py>\"" /sc ONLOGON /delay 0000:30 /ru %USERNAME% /f`  
Called from **wizard step 5 only** (not setup.bat). The `/delay 0000:30` gives the network 30s to settle.

---

## What Comes Next (Spec Steps 8–17)

### Step 8: `sortilege/librarian/deduper.py`
Hash + pHash duplicate detection. Key points from spec:
- `compute_sha256(filepath)` — long-path aware, streams chunks
- `compute_phash(filepath)` — `imagehash` library, images only
- `check_known_source(source_path)` — pre-hash path lookup (calls `registry.get_known_source_by_path`)
- `check_dupe_by_hash(sha256)` — calls `registry.get_file_by_sha256`
- `check_dupe_by_phash(phash, threshold)` — **load all phashes into memory** (`registry.get_all_phashes()`), numpy popcount hamming distance, sub-millisecond; use `registry.get_all_phashes()` which is already implemented
- `record_known_source(source_path, sha256, canonical_file_id)` — after cross-drive copy
- `remove_known_source(file_id)` — on undo_copy

### Step 9: `sortilege/librarian/router.py`
Full-path resolution loop. Key points:
- `process_batch(paths: list[str])` — main entry point
- Per file: stability check (exists, readable, non-zero) → `deduper.compute_sha256` → `registry.create_file` → `registry.update_file_state('captured'→'queued'→'classifying')` → `cascade.classify()` → `registry.update_file_proposal()` → `registry.update_file_state('classifying'→'held'|'error'|'budget_paused')`
- After batch: fire SSE `batch_ready` event, trigger Windows toast ("N files ready for review")
- Respect `checkpoint_batch_size` from config for progress SSE events
- The SSE channel is in `api/sse.py` (not yet built) — router needs a way to publish events. Simplest pattern: a module-level `asyncio.Queue` in `api/sse.py` that router puts events onto. Router should be importable without the API running (for cli.py dry-run).

### Step 10: `sortilege/librarian/intake.py`
- Receives `POST /api/intake` body `{ paths: string[] }`
- Validates each path exists and is readable
- Creates `file` rows in `captured` state
- Hands off to `router.process_batch()` as a background task (FastAPI `BackgroundTasks`)

### Step 11: `sortilege/dropwindow/app.py`
- `pywebview` always-on-top drop-target window
- On drop: read source paths from DnD payload, POST to `http://localhost:8000/api/intake`
- Visual feedback on success (brief flash or checkmark)
- **Note:** pywebview DnD on Windows requires using the `edgechromium` renderer and JS `ondragover`/`ondrop` handlers. The window HTML should be minimal. If pywebview DnD proves problematic, the fallback is a minimal Electron/Tauri shell — but try pywebview first.

### Step 12: `sortilege/librarian/learner.py`
- `on_move(file_id, proposed_node_id, actual_node_id)`:
  - If `proposed != actual`: `registry.create_correction(...)`
  - `embeddings.update_folder_embedding(actual_node_id)` (positive signal)
  - If proposed is not None: `embeddings.update_folder_embedding(proposed_node_id)` (negative signal — will dilute via re-averaging)
  - If `actual_node_id` == unsorted node id: re-queue the file (set state back to `queued`, let router re-process)

### Step 13: `sortilege/librarian/suggester.py`
- `generate_suggestions()` — called after batch confirm
- **Folder proposals:** scan `held` files grouped by proposed parent; if N+ at same level with no child match → propose new child. Check `registry.find_suggestion()` for existing pending suggestion first (dedup). Ghost node in UI — accept creates real folder, seeds embedding, re-resolves held files.
- **Rule proposals:** `registry.get_correction_patterns(min_count=3)` → for each pattern, check no existing rule covers it → call `registry.create_suggestion(kind='rule', ...)`
- Anti-nagging: dismissed suggestions need 2× evidence count to re-propose. Check `status='dismissed'` + `evidence_count` before creating.

### Step 14: `sortilege/api/routes.py` + `sortilege/api/sse.py`
Build together. Key points:
- `api/sse.py`: module-level `asyncio.Queue` for events; `EventSourceResponse` from `sse-starlette`; `router.py` calls a sync-safe `push_event(event_type, data)` function
- `routes.py`: all endpoints from spec; serve `ui/dist` as static files; redirect `/` to review UI or `/setup` if not configured
- Batch confirm logic is in spec section 13 — it's substantial; read carefully before implementing
- Config endpoint: `GET /api/config` reads from workspace `config.json`; `POST /api/config` writes it

### Step 15: `sortilege/ui/` — React frontend
Scaffold Vite first: `cd sortilege && npm create vite@latest ui -- --template react`  
Then build against the API shapes defined above. The design prompt (`Sortilege_Claude_Design_Prompt.md`) is the full UI spec. The `ui-design/` folder has screenshots and a prototype HTML file for reference.

### Step 16: Setup wizard (`/setup` route)
- 5-step wizard served at `/setup`
- Step 5 registers the Windows startup task (see schtasks command above)
- After step 5: write `config.json` to workspace, flip a `configured: true` flag, redirect to review UI
- On server start: if `config.json` missing or `configured != true` → redirect all routes to `/setup`

### Step 17: `setup.bat`
```bat
@echo off
uv venv .venv
.venv\Scripts\uv pip install -r requirements.txt
cd sortilege\ui && npm install && npm run build && cd ..\..
start /B .venv\Scripts\python.exe -m uvicorn sortilege.api.routes:app --host 127.0.0.1 --port 8000
timeout /t 3 /nobreak
start http://localhost:8000/setup
```

---

## Implementation Notes / Gotchas

1. **`cascade.configure(rules_path)` must be called at startup.** It's not called automatically. Both `main.py` (server startup) and `cli.py` call it. Forgetting this means Tier 2 always skips with empty rules.

2. **`embeddings.load_model()` must be called at server startup** (not per-request). Takes ~10s for torch load; stays resident. `cli.py` calls it explicitly. The FastAPI app's lifespan handler should call it.

3. **`registry.init_db(db_path, schema_path)` must be called before any registry function.** Called from `cli.py` and will need to be called from `api/routes.py` lifespan.

4. **The dry-run CLI creates real rows in the workspace DB.** Use a separate workspace for dev (`SORTILEGE_WORKSPACE=C:\sortilege-dev python cli.py ...`) to avoid polluting the prod DB.

5. **`cascade.py` silently swallows LLM call exceptions** (returns `None`, falls through to next tier / unsorted). This is intentional — a flaky API call should not crash the pipeline. Check logs if Tier 4/5 seems to never fire.

6. **Tier 3 floor threshold:** `tier3_embedding_min` in config defaults to `null`. In `cascade.py`, a null floor becomes `0.0` (any match passes). **This will route everything via embeddings before ever hitting Tier 4.** Set it empirically after the dry-run — start at ~0.5 and adjust from the CSV.

7. **`extract()` in `extractor.py`** returns `ExtractionResult(error=...)` on failure — it never raises. Callers should check `result.error` before using `result.text`.

8. **Long-path prefix:** `extractor.long_path()` is the utility. All `open()` calls that use file paths from the registry should go through it. `registry.py` stores paths as-is (without prefix); prefix is applied at filesystem access time.

9. **`get_held_groups()` uses `NULLS LAST`** — requires SQLite 3.30.0+. Windows 10 ships with a bundled SQLite but Python's `sqlite3` module uses its own. Verify with `python -c "import sqlite3; print(sqlite3.sqlite_version)"` — should be 3.35+ on Python 3.11.

10. **`known_source` path index** (`idx_known_source_path`) is in `schema.sql` but not in the handoff's schema listing. It IS present in `schema.sql` as written. Both the spec and the handoff text describe the path-based pre-hash lookup, so the index belongs there.
