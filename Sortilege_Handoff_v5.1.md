# Sortilege — Handoff Report v5.1
**Session Date:** June 2026
**Project Status:** Architecture finalized, consistency-verified, pre-implementation
**Purpose:** Complete context for continuing this project in a new session. Read this entire document before responding to any questions. All decisions are confirmed unless explicitly marked as open questions.

**Revision note (v5 → v5.1):** Consistency audit of v5 found two contradictions and five gaps. Fixes: state machine now shows undo return paths (`moved/copied → held`); `file` table comment corrected (dupes are also rows); toast notification trigger specified ("batch classification completes"); `workspace_dir` contents defined; Tier 5 explicitly receives the taxonomy subtree; undo-of-copy cascades to `known_source` removal; `known_source` path-based pre-hash lookup added to routing algorithm as a pre-Tier-1 step. No decisions changed; all fixes are clarifications of existing intent.

**Revision note (v4 → v5):** Reworked ingest and execution model. The inbox is now a **drop-target app window that captures source paths without moving anything**; the **app never deletes**; **`misc` removed and `unsorted` promoted**; **hard depth cap removed**; seed taxonomy is **nine folders**; **SQLite schema designed**; **setup wizard specified**; **no application bundling** for v1. Do not re-suggest v4 versions.

**Lineage:** v3 = merge of Sortilege v1 (batch migration) + Recursive Librarian (inbox maintenance). v4 = first expert review (group review, folder/rule proposals, undo, Windows realities). v5 = second review (capture-by-path, no-delete execution, taxonomy + schema finalized). v5.1 = consistency audit.

---

## Project Goal

Build **Sortilege** — a personal AI-powered file organization system for Windows. One system, one capture gesture, no phases.

The user drags files (from any drive) onto the Sortilege drop window. The system reads the files **in place**, deduplicates, classifies, and proposes a destination under `E:\organized\`. Proposed actions accumulate quietly; the user opens a review UI on their own schedule, confirms grouped actions with minimal clicks, and can undo any batch. The app moves keepers that are already on the destination drive, copies keepers from other drives, and skips anything that's already filed. It never deletes.

The end user mental model: **I don't organize files. I toss them at Sortilege, it figures out where they go, and I approve in bulk when I feel like it. It never destroys anything.**

The immediate scope is ~42,776 files (~69GB) across Desktop, Downloads, and Documents — handled identically to any future drop. There is no separate migration mode.

---

## Guiding Principles

- **The librarian routes and proposes. The user decides.** AI never silently creates folders or rules. It proposes them in the review UI; the user accepts with one click or ignores.
- **Capture by reference, not by relocation.** Dropping files onto Sortilege registers their paths; no bytes move until a destination is confirmed. Analysis happens against files wherever they already live, on any volume.
- **The app never deletes.** Same-drive keepers are moved (original consumed by the move); cross-drive keepers are copied (original left in place for the user to clear themselves); dupes are skipped with no filesystem action. There is no delete path, no quarantine, no recycle.
- **Drop and forget.** The drop gesture is the only required interaction. The system absorbs chaos without requiring behavioral change.
- **Quiet by default.** Drops are processed and held silently. When a batch finishes classification, a Windows toast notification fires (e.g. "14 files ready for review"). The UI never auto-opens.
- **Review at the group level.** The UI confirms clusters of files headed to the same destination, not individual rows. Per-file inspection is always available, never required.
- **Undo is a trust feature.** Every confirmation batch is revertible (reverse moves, remove app-created destination copies). Aggressive confirming is safe.
- **No terminal after setup.** Terminal acceptable during development. Day-to-day usage requires zero terminal interaction.
- **Non-destructive by construction.** Because the app never deletes, the strongest non-destructive guarantee is automatic. The only verification that matters is cross-drive copy integrity: copy, hash-verify, then surface the now-redundant original as safe-to-delete (the app still doesn't delete it).
- **Local knowledge beats global knowledge.** Embedding-based routing resolves most files locally and free. API tiers are the exception path.
- **Simplicity over features.** Cut anything that adds complexity without direct user value. Justify complexity explicitly.
- **UI moves are the only learning signal.** The system learns exclusively from intentional moves in the review UI. Source-location moves outside the app are ignored.
- **Incremental learning.** Files routed early build embeddings that make later files cheaper and more accurate. Process Downloads first (smallest), then Desktop, then Documents.

---

## Background & Context

### User Profile
- Full-stack software engineer (JS/TS/React, Node.js), frontend lean, working at JPMC
- Windows PC is primary machine; external drive (`E:\`, ~1.36TB) is the output destination
- ~42,776 files (~69GB) of disorganized personal files across Desktop, Downloads, Documents

### The Problem
Years of disorganized storage: files on Desktop, dragged into unnamed folders, multiple computer backups dumped into single folders. Duplicates at different compressions, same document downloaded repeatedly under different names, tax documents / resumes / family photos / downloaded images all mixed together.

### Design History
- **Migration/maintenance split eliminated (v3):** same files, same cascade; incremental processing builds embeddings that make later files cheaper; one system is simpler.
- **First review (v4):** v3 over-invested in machinery (threshold relaxation, Rules UI, scoped inboxes) and under-invested in daily-touch surfaces (group review, folder proposals, undo). Cascade restructured so embeddings are an explicit tier. Windows realities added.
- **Second review (v5):** The inbox model was wrong on two counts — a fixed inbox folder forces a pre-analysis copy, and it can't capture files on other volumes without moving them across drives first. Both are solved by capturing source *paths* and analyzing in place. Separately, the disposal/quarantine/undo-of-delete complexity was eliminated wholesale by adopting a no-delete execution model: the point of dedup is to *skip* work, not relocate it.

---

## System Architecture

### Output Tree

```
E:\organized\
├── financial\        taxes, statements, insurance, receipts
├── career\           resumes, certifications, job-search artifacts
├── health\           medical records, lab results, imaging
├── documents\        identity, legal, manuals, correspondence (official papers)
├── photos\           personal photos — camera, family, events
├── media\            consumed media — downloaded images, wallpapers, video, audio
├── code\             projects, snippets, dotfiles
├── creative\         writing, worldbuilding, campaign materials
└── unsorted\         FALLBACK ONLY — see below
```

**Nine top-level seed folders**, presented as an editable list in the setup wizard (rename / remove / add). Chosen for semantic orthogonality (embedding discrimination is best when siblings are far apart) and corpus coverage. Notable splits: `career` out of `documents` (high-stakes retrieval, distinct enough to route cleanly); `photos` vs. `media` (corpus explicitly mixes family photos with downloaded images; EXIF presence gives Tier 2 a cheap deterministic split); `health` (medical PDFs are highly distinctive); `creative` (writing/D&D material embeds near nothing else). Stop at nine — every added top-level folder dilutes sibling discrimination; anything uncertain is better created later from a data-driven proposal.

**`unsorted\` is fallback-only and excluded from embedding matching entirely.** The cascade can never *route* to it by similarity; files land there only by falling below every confidence floor. It is a system folder (`is_system=1`), locked in the wizard (can't be renamed or removed).

**No second-level pre-seeding.** Subfolders are created from ghost-node proposals generated from real held files (with evidence and a content-derived seed embedding), which strictly dominates guessing structure up front with name-only embeddings.

### Capture Model — Drop-Target App Window

The drop target is a **small always-available application window** (system tray / dock widget) that accepts drag-and-drop and reads the **source paths** from the drop payload. Nothing is moved or copied on drop — the app records where each file lives and analyzes it in place, on whatever volume it sits.

Rationale: a plain folder cannot capture a path without Windows performing a move/copy first (the OS owns the drop before any program sees it). Capturing paths requires owning the drop, which requires the target to be a program. The drop window is the pragmatic version of "an inbox that registers files without relocating them" — it preserves drag-and-toss, works identically across C:, external, and network drives, and sidesteps the watcher stability-gate problem (a drop only fires on files that have already finished copying to wherever they are).

**Rejected: fixed `_inbox` folder (on E: or on C:).** On E: it forces a pre-analysis cross-volume copy, so dupes are paid for before being detected. On C: it can't capture files from other drives without first moving them across. Both are solved by path capture.
**Rejected: shell namespace extension** (a folder-looking icon that's actually code) — weeks of COM/C++, fragile across Windows updates. Overkill.
**Rejected: SendTo verb as the v1 mechanism** — satisfies path capture with zero GUI, but the right-click gesture doesn't match the drag-toss mental model. May be added later as a complementary path; the drop window is primary for v1.
**Rejected: watching source folders directly** — ingests files the user is actively working on; loses the intentional "sort *these*" signal the drop gesture provides for free.

### Tech Stack
- **Backend:** FastAPI + Python, resident server (Windows startup task, hidden window)
- **Drop window:** lightweight desktop shell (pywebview or minimal Tauri/Electron) that captures dropped paths and posts them to the backend
- **Frontend (review UI):** served by FastAPI; React acceptable during development; no end-user build step
- **Live progress:** Server-Sent Events (SSE) via FastAPI streaming (WebSockets cut — SSE is simpler, one fewer dependency)
- **Database:** SQLite — single source of truth (registry, folder embeddings, taxonomy, correction log, action history)
- **Embeddings:** Nomic Embed (local, English-optimized) via sentence-transformers; model stays loaded in the resident server (no per-use cold start). **Future footprint note:** fastembed (ONNX) serves the same model at ~200MB vs. ~3GB torch — a one-file change behind `embeddings.py`, deferred, would make bundling feasible if ever distributed.
- **API:** Anthropic (Haiku for Tier 4 + descriptions, Sonnet for Tier 5)
- **API key storage:** Windows Credential Manager via `keyring` — never written to disk

### Codebase Structure

```
sortilege/
├── core/
│   ├── cascade.py        # five-tier classification logic
│   ├── embeddings.py     # Nomic Embed wrapper, folder embedding CRUD
│   ├── extractor.py      # text/content extraction (pdf, docx, xlsx, etc.)
│   ├── registry.py       # SQLite interface (single-writer discipline)
│   └── taxonomy.py       # taxonomy node read/write
├── librarian/
│   ├── intake.py         # receives dropped paths, stability already guaranteed by drop semantics
│   ├── router.py         # full-path resolution (embedding recursion + single LLM call)
│   ├── deduper.py        # hash + pHash duplicate detection
│   ├── learner.py        # embedding updates on UI move
│   └── suggester.py      # passive folder + rule proposals from correction log
├── api/                  # FastAPI routes + SSE
├── ui/                   # Review UI frontend
├── dropwindow/           # desktop drop-target shell
├── cli.py                # dev-only dry-run harness for threshold calibration
└── setup.bat             # one-time: env + deps (via uv), start server, open wizard
```

### Server & Launch Model
Resident server, registered as a Windows startup task during first-run setup. The drop window launches with the session and posts paths to the running server. Daily review UI entry is a browser shortcut to `http://localhost:8000`. Model load is amortized once per boot.

**Rejected: `launcher.bat` cold-start per use** — slow (torch load), still not a tray app.
**Rejected: bundling into an executable for v1** — PyInstaller-with-torch yields 2–4GB bundles, hidden-import fragility, `--onefile` temp-extraction on every launch, and Defender false-positives on unsigned exes. The resident-server model means launch is invisible and once-per-boot, so the benefit barely exists; meanwhile bundling fights the developer's own iteration loop (rebuild-per-change vs. edit-and-restart). v1 uses a one-time `setup.bat` under the terminal-during-development allowance, using **uv** (single binary, fast resolution, can fetch Python itself).

---

## Execution Model (the core of v5)

Three rules cover every file. **The app never deletes.**

```
not a dupe, source drive == destination drive (E: → E:)  → MOVE  (atomic rename; original consumed)
not a dupe, source drive != destination drive (C:/ext → E:) → COPY + hash-verify  (original left in place)
dupe of anything already in the registry                  → SKIP  (no filesystem action at all)
```

- **Move:** same-volume rename, near-atomic, no data copy regardless of size. The original ceases to exist by the act of moving.
- **Copy:** the only cross-volume transfer, performed once, only for confirmed keepers, only at confirm time. After copy + hash-verify, the file exists at both source and destination. The source original is now redundant; the app flags it as **safe for the user to delete** but does not delete it.
- **Skip:** the entire point of dedup is to *avoid work* on files already filed. A dupe triggers no move, no copy, no holding folder — it is recorded and skipped. This includes a file that duplicates something already inside `E:\organized\`: it stays where it is and is flagged; the app does nothing to it.

**Cross-drive originals are remembered as known-dupes.** After a cross-drive copy, the source path + hash is recorded as a duplicate of the canonical destination file. On any future drag (or when that drive is later processed wholesale), the file is recognized instantly at Tier 1 and skipped — never re-copied. This compounds: processing the external backup drive later skips everything already copied from C:.

### Results-Screen File States
```
moved     same-drive keeper; original consumed by the move
copied    cross-drive keeper; original now redundant — safe for you to delete (app does not delete it)
dupe      already in the tree / registry; skipped, no action
held      below threshold; awaiting your review
error     unreadable / zero-byte / failed verify
```
The `copied` state is how the user's "show the original's post-copy status" requirement surfaces: the destination is the keeper, the source is a flagged redundant leftover the user clears on their own schedule.

---

## Five-Tier Classification Cascade

Goal: 70–80% of files never touch the API — **validated empirically via dry-run before being relied on.** Embeddings improve with each batch. The embedding tier is the expected workhorse; filename rules alone won't reach the target on messy personal files.

### Tier 1 — Exact Hash Match
- Hash matches a registry record → dupe, skipped (no action)
- Hash matches a file already processed this session → inherit classification
- Hash matches a recorded cross-drive source original → recognized, skipped
- Canonical entry is always the **destination** file

### Tier 2 — Rules Engine
- Signal priority: EXIF/embedded metadata → filename pattern → extension → (no folder-path signal; source structure is the problem being solved and isn't trusted)
- Small, stable deterministic set (camera filename patterns, `*statement*` PDFs, unambiguous extension → top-folder). Expected to converge to ~a dozen rules and rarely change.
- All rules in `rules.yaml`. **No Rules UI** — maintained via passive rule suggestions in the review UI plus occasional hand edits; effectively system-managed.

### Tier 3 — Embedding Match (local, $0)
- File embedding (Nomic) compared against folder embeddings
- Recursive descent in embedding space: best-matching child at each level
- **Deepest *confident* match, absolute floor.** "Confident" means clearing the floor in absolute terms, not merely best-of-siblings. If no child clears the floor, placement stops at the current level — a file matching `photos\` and `vacation\` but no existing country folder is placed directly in `photos\vacation\`. Partial-depth placement is correct behavior, not failure. This is what lets the user decline a proposed deeper folder and still have the file land sensibly.

### Tier 4 — Cheap AI (Metadata Only)
- Claude Haiku. Input: filename, extension, size, dates, first 500 chars, **plus the relevant taxonomy subtree (names + descriptions)**.
- Returns a **full destination path in one call** — never one call per depth level.

### Tier 5 — Deep AI (Content + Vision)
- Claude Sonnet. Full text or image thumbnail, **plus the relevant taxonomy subtree (names + descriptions)**; vision reads scanned documents (this is why OCR/tesseract is rejected — redundant, not merely fragile).
- Returns a full destination path in one call. Below floor → `unsorted\`.

### Threshold Policy
- **Per-tier thresholds, calibrated empirically.** Rules scores, cosine similarity, and LLM self-reported confidence are not on a comparable scale. v3's single 0–1 ladder was a false assumption.
- Config values are placeholders until a **dry-run calibration pass** on the first real batch (Downloads, 655 files): log tier/score/destination for every file, move nothing, set thresholds from observed distributions. Also validates the 70–80% no-API claim.
- **No per-folder threshold relaxation** — cut as over-engineered (unpredictable moving target; group confirm already solves holds).

---

## Routing Algorithm

```
File path captured (already finished copying to its location)
↓
Pre-hash path check → source_path in known_source? Skip without reading (avoids re-hashing large files)
↓
Tier 1 dedup (hash) → dupe? Record + skip (no filesystem action)
↓
Tier 2 rules → confident deterministic match? Resolve.
↓
Tier 3 embedding recursion → descend through children that clear the absolute floor;
  place at deepest confident match (partial depth is correct)
↓
Unresolved → Tier 4 (Haiku, one call, full path) → Tier 5 (Sonnet, one call, full path)
↓
Still below floor → unsorted\
↓
On user confirm: MOVE (same drive) or COPY+verify (cross drive)
```

**Rejected: physical multi-hop routing** — stranded files on crash; in-memory resolution is cleaner.
**Rejected: per-level LLM calls** — up to 4× cost/latency; one call with the subtree returns the whole path.

---

## Move Rules (Review UI)
- Files can be dragged to **any folder** — cross-layer moves allowed. A move to a different subtree is the cleanest learning signal: negative on proposed destination, positive on actual.
- Moving to `unsorted\` re-routes the file from root with updated embeddings.

**Rejected (v3): cross-layer restriction** — blocked corrections at the worst moment; the "inconsistent embedding state" justification didn't hold.

---

## Review UI

### Layout
- Split pane: folder tree left, grouped file list right. All tree nodes are live drag targets.

### Primary Row Type: Destination Group
```
☐  412 files  →  photos\vacation\japan      min conf 91%   [expand] [CONFIRM GROUP]
☐   38 files  →  financial\taxes\2023        min conf 88%   [expand] [CONFIRM GROUP]
☐   17 files  →  dupe — skip                                [expand] [CONFIRM GROUP]
```
- The unit of review is the **group**, not the file — what makes both the 42K corpus and a 30-file Friday drop tractable. Expand to spot-check; confirm at group level. Held (below-floor) files appear in their own groups.
- Click a file row → inline detail panel: file info, AI reasoning, thumbnail/type icon, move controls, and (for cross-drive files) the source path.

### Passive Suggestion Rows (non-blocking, ignorable forever)
```
✦  Suggest folder: financial\taxes\2023 — would receive 38 held files   [accept] [rename] [dismiss]
✦  Suggest rule: *.heic from "Camera Roll" → photos\phone (8 corrections)   [accept] [dismiss]
```
- Folder proposals are ghost nodes; accept creates the folder, seeds its embedding, re-resolves held files.
- Rule proposals append to `rules.yaml` on accept; never auto-applied. These rows **are** the rules interface (replacing both the rejected blocking "Stage 4b" and the rejected Rules UI).
- Dismissed suggestions persist; re-proposal requires materially stronger evidence (no nagging).

### Toolbar
- **Select-all-high-confidence** — checks all groups clearing threshold
- **Confirm Selected** — executes checked actions, fires embedding updates, recalculates held files, repopulates groups
- **Undo** — reverts the last confirmation batch (or a chosen recent batch). With no deletes, undo only reverses **moves** (move back) and **copies** (remove the app-created *destination* copy — which is not a user original, so the no-delete rule doesn't apply to it; also removes the corresponding `known_source` entry so the source file isn't incorrectly recognized as a dupe on future drags). Files return to `held` state for re-review. Fully reversible. Built on the action-history table; first-class v1 feature.

### New Folder Creation (manual path)
Hover tree node → `+ New Folder` → type name → Haiku generates editable one-sentence description → confirm → folder created, embedding seeded → held files recalculated.

**Rejected: drop-onto-parent triggers create prompt** — ambiguous gesture.
**Rejected: popup on drop (Place Here / Create Subfolder)** — extra tap on every move.

---

## Folder Embeddings & Learning
- Every folder has a semantic embedding in SQLite, from: name, child names, representative file embeddings, AI description, correction history.
- Nomic Embed (local, $0). Updated immediately on every UI move — no batching.
- Cold start: name + description embedding for empty folders; deepens as files accumulate.
- **Embeddings are derived state** — rebuildable from file embeddings + corrections + descriptions. No embedding-history table; the correction log is the history. A future model swap (fastembed) is a re-derivation, not a migration.

### Learning Signal
- UI move to any destination → positive on actual, negative on proposed
- UI move to `unsorted\` → negative on source; re-routes from root
- Source-location moves outside the app → ignored
- Correction log additionally feeds `suggester.py`

---

## SQLite Schema

```sql
-- PRAGMA journal_mode=WAL; foreign_keys=ON; user_version for migrations.
-- All writes funnel through registry.py (single-writer discipline).
-- Paths inside the tree stored RELATIVE to output root (drive letters change);
-- source paths (other volumes) stored absolute.

CREATE TABLE taxonomy_node (
    id            INTEGER PRIMARY KEY,
    parent_id     INTEGER REFERENCES taxonomy_node(id),
    name          TEXT NOT NULL,
    rel_path      TEXT NOT NULL UNIQUE,        -- cached; derived from ancestry
    description   TEXT,                         -- Haiku-generated, editable
    is_system     INTEGER NOT NULL DEFAULT 0,   -- unsorted=1: locked, excluded from embedding match
    embedding     BLOB,                         -- float32[768]; NULL until seeded
    embedding_updated_at TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(parent_id, name)
);

CREATE TABLE file (                             -- one row per captured file; for keepers this becomes
                                                -- the canonical destination record; for dupes this records
                                                -- the skip decision (state='skipped', no current_rel_path)
    id            INTEGER PRIMARY KEY,
    sha256        TEXT NOT NULL,
    phash         INTEGER,                      -- 64-bit, images only
    size          INTEGER NOT NULL,
    mtime         TEXT,
    ext           TEXT,
    source_path   TEXT,                         -- where it was captured from (absolute)
    current_rel_path TEXT,                      -- destination after move/copy; NULL while held
    state         TEXT NOT NULL,                -- see state machine
    error_detail  TEXT,
    -- current proposal (overwritten on recalc; disagreement history lives in `correction`)
    proposed_node_id  INTEGER REFERENCES taxonomy_node(id),
    planned_op        TEXT,                     -- 'move' | 'copy' | 'skip'
    dupe_of_file_id   INTEGER REFERENCES file(id),
    dupe_kind         TEXT,                     -- 'exact' | 'perceptual'
    tier          INTEGER,
    confidence    REAL,                         -- meaningful only per-tier
    reasoning     TEXT,
    extracted_snippet TEXT,                     -- first 500 chars; cached for recalc
    proposal_updated_at TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_file_sha256 ON file(sha256);
CREATE INDEX idx_file_state  ON file(state);
CREATE INDEX idx_file_phash  ON file(phash) WHERE phash IS NOT NULL;

CREATE TABLE file_embedding (                   -- side table: keeps file-row scans fast
    file_id   INTEGER PRIMARY KEY REFERENCES file(id),
    embedding BLOB NOT NULL                      -- float32[768]
);

CREATE TABLE known_source (                      -- cross-drive originals left in place; never re-copied
    id           INTEGER PRIMARY KEY,
    source_path  TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    duplicates_file_id INTEGER NOT NULL REFERENCES file(id),
    recorded_at  TEXT NOT NULL,
    UNIQUE(source_path, sha256)
);
CREATE INDEX idx_known_source_hash ON known_source(sha256);

CREATE TABLE batch (                             -- one row per Confirm Selected
    id           INTEGER PRIMARY KEY,
    confirmed_at TEXT NOT NULL,
    file_count   INTEGER NOT NULL,
    undone       INTEGER NOT NULL DEFAULT 0,
    undone_at    TEXT
);

CREATE TABLE action_log (                        -- executed actions; undo replays in reverse
    id        INTEGER PRIMARY KEY,
    batch_id  INTEGER REFERENCES batch(id),
    file_id   INTEGER NOT NULL REFERENCES file(id),
    action    TEXT NOT NULL,    -- 'move'|'copy'|'undo_move'|'undo_copy'|'folder_create'
    from_path TEXT,
    to_path   TEXT,
    executed_at TEXT NOT NULL
);
CREATE INDEX idx_action_batch ON action_log(batch_id);

CREATE TABLE correction (                        -- user moved file somewhere other than proposed
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
    kind           TEXT NOT NULL,                -- 'folder' | 'rule'
    payload        TEXT NOT NULL,                -- JSON: proposed path / rule spec + evidence file ids
    evidence_count INTEGER NOT NULL,
    status         TEXT NOT NULL,                -- 'pending'|'accepted'|'dismissed'
    created_at     TEXT NOT NULL,
    resolved_at    TEXT
);

CREATE TABLE api_usage (                          -- ceiling enforcement + budget_paused resume
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER, output_tokens INTEGER,
    cost_usd      REAL NOT NULL,
    file_id       INTEGER REFERENCES file(id)
);
```

### File State Machine
```
captured → queued → classifying → held ←──────────────┐
                         │           │                 │
                         │           ├→ moved ─────────┤ (undo_move → returns to held)
                         │           ├→ copied ────────┘ (undo_copy → removes dest copy, returns to held)
                         │           └→ skipped              (terminal; dupe, no action, not undoable)
                         ├→ budget_paused → queued       (ceiling raised/reset)
                         └→ error                         (unreadable / zero-byte / failed verify)
```

### Schema Design Notes
- **No quarantine / recycle / undo-of-delete tables** — the no-delete model removes them. Undo reverses moves and removes app-created destination copies only.
- **`known_source`** serves two purposes: (1) a pre-hash path lookup that skips re-reading large files entirely if the exact source_path is already recorded, and (2) a hash-based fallback if the path changed but the bytes didn't. Recorded once on cross-drive copy; also removed on undo_copy to prevent dangling references.
- **No rules table** — `rules.yaml` stays the single source of truth for Tier 2; accepted rule suggestions append to it. Mirroring into SQLite would create two masters.
- **No folder rename/delete in v1** — would cascade through `rel_path` caches. The wizard is the moment to get top-level names right; defer subtree edits post-v1.
- **pHash needs no index machinery** — linear hamming distance over 42K integers with numpy popcount is sub-millisecond; a single in-memory array satisfies the matching requirement.
- File embeddings live in a side table (42K × ~3KB BLOBs inline would drag every registry scan); taxonomy embeddings stay inline (few hundred rows).

---

## API Cost Model

| Event | Model | Cost |
|---|---|---|
| Embedding match (Tier 3) | Nomic (local) | $0 |
| Tier 4 classification | Haiku | ~$0.001/file |
| Tier 5 classification | Sonnet | ~$0.01/file |
| New folder description | Haiku | ~$0.001/folder |

**Realistic migration estimate:** at 25% Tier 4 / 5% Tier 5 on 42K files, expect roughly **$30** total. The default $10 ceiling will likely trip mid-migration; behavior is defined:

**Cost ceiling behavior:** at the soft ceiling, remaining API-tier files enter a visible **`budget_paused`** state — resumable after the ceiling is raised or a new period starts. Never silently dumped to `unsorted`.

**Optional optimization (not v1):** Anthropic's Batch API is 50% cheaper, suited to large non-interactive passes (the initial corpus). Regular API for daily drops.

### Alternative LLM Backends (not v1)

The current implementation uses the `anthropic` Python SDK, which speaks Anthropic's native `/v1/messages` format. Two alternative backends were discussed but deferred:

**OpenRouter**
- OpenRouter exposes an OpenAI-compatible API (`/v1/chat/completions`), not an Anthropic-compatible one.
- Cannot be a config-only swap — requires replacing `anthropic` SDK with `openai` SDK in `cascade.py`, updating model names to OpenRouter format (e.g. `anthropic/claude-haiku-4-5`), and changing the message construction to the OpenAI format.
- Also requires removing the keyring/Anthropic API key flow from the setup wizard and replacing it with an OpenRouter key.
- Not worthwhile for single-user use given Haiku's low cost and the existing $10 ceiling.

**Local LLM via Ollama** (for zero API cost)
- Ollama exposes an OpenAI-compatible endpoint at `http://localhost:11434/v1`.
- Same SDK swap as OpenRouter (`openai` SDK with `base_url` pointed at Ollama).
- Model names change to Ollama model names (e.g. `qwen2.5:7b`, `llama3.1:8b`).
- Setup wizard step 2 (API key) would be removed or replaced with an Ollama model-selection step.
- **Trade-offs:**
  - Tier 5 vision quality drops significantly — local vision models (`llama3.2-vision`, `moondream`) are much weaker than Sonnet on dense scanned documents.
  - JSON reliability is lower; parsing/retry logic around LLM calls would need hardening.
  - Slower unless running on GPU. A 7B model needs ~5–8GB RAM on top of Nomic Embed.
  - Since Tier 3 (local embeddings) already handles most files, Tiers 4/5 are the exception path — actual cost savings depend on how many files fall through to those tiers.
- Implement by: swapping `anthropic` SDK → `openai` SDK in `cascade.py`; pointing `base_url` at Ollama; updating `tier4_model` / `tier5_model` in `config.json` to Ollama model names.

**Not pursued:** a proxy that speaks the Anthropic API format (e.g. LiteLLM) wrapping OpenRouter or Ollama — adds infrastructure complexity without proportional benefit for single-user use.

---

## Configuration (`config.json`)

```json
{
  "output_drive": "E:\\organized",
  "workspace_dir": "C:\\sortilege-workspace",
  "confidence_thresholds": {
    "_comment": "PLACEHOLDERS — per-tier scales are not comparable; calibrate via dry-run on first real batch",
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
- `anthropic_api_key` in Windows Credential Manager via `keyring`. Never in `config.json`.
- `workspace_dir` (`C:\sortilege-workspace`) contains: `sortilege.db` (SQLite), `rules.yaml`, `config.json`, and application logs. No inbox folder, no quarantine — just app state. The workspace is on C: so it persists regardless of the output drive's presence.
- `max_folder_depth` **removed** — the depth cap was redundant once the AI cannot create folders and recursion terminates at user-approved leaves. Depth is self-limiting (deep trees → thin embeddings → more holds → user flattens); `suggester.py` should mildly resist proposing deep nesting without strong signal, but this is tuning, not a rule.
- `github_username` removed (leakage from another project).
- All filesystem paths handled with long-path support (`\\?\` prefix) — decade-old backup trees exceed MAX_PATH.

---

## Python Dependencies

```
pathlib, hashlib, sqlite3, uuid, asyncio, shutil  # stdlib
keyring               # Windows Credential Manager API key storage
chardet               # encoding detection
imagehash             # perceptual hashing
Pillow                # image processing
pypdf                 # PDF text extraction
python-docx           # Word text extraction
openpyxl              # Excel text extraction
python-pptx           # PowerPoint text extraction
reverse_geocoder      # offline GPS reverse geocoding
sentence-transformers # local embeddings (Nomic Embed); resident server amortizes torch load
anthropic             # Claude API
fastapi               # backend + static serving + SSE
uvicorn               # ASGI server
sse-starlette         # SSE (replaces websockets)
pyyaml                # rules.yaml parsing
LnkParse3             # Windows .lnk shortcut target extraction
pywebview             # drop-target window (or minimal Tauri/Electron shell)
winotify              # Windows toast notifications (or windows-toasts / plyer — pick least fragile)
```
*Removed since v4: `watchdog` (no folder to watch — drop window captures paths), `send2trash` (no deletes), `websockets` (SSE).*

---

## Rejected Ideas — Master List

| Idea | Why Rejected | Status |
|---|---|---|
| Two-phase architecture (migration + maintenance) | Same files, same cascade; incremental learns along the way | Firm |
| Fixed `_inbox` folder (E: or C:) | E: forces pre-analysis cross-volume copy; C: can't capture other-drive files without moving them — path capture solves both (v5) | Reversed |
| Shell namespace extension (fake folder) | Weeks of COM/C++, fragile across Windows updates | Firm |
| SendTo verb as v1 capture | Zero-GUI path capture, but right-click ≠ drag-toss; may add later as complement | Deferred |
| Watching source folders directly | Ingests in-progress files; loses intentional sort signal | Firm |
| App deletes originals / quarantine / recycle / undo-of-delete | No-delete model: move same-drive, copy cross-drive, skip dupes; the point of dedup is to skip work, not relocate it (v5) | Cut |
| Relocating dupes to a `_duplicates\` folder | A dupe should be skipped entirely — no action is the whole point | Firm |
| `max_folder_depth` hard cap | Redundant once AI can't create folders; depth self-limits via embedding thinness (v5) | Cut |
| `misc\` top-level folder | Semantically empty; `unsorted\` promoted and made fallback-only (v5) | Cut |
| Second-level pre-seeding | Name-only embeddings, guessed structure; proposals from real files dominate (v5) | Firm |
| AI silently creates folders | Replaced by propose-and-accept (v4) | Amended |
| Per-file review rows as primary unit | Doesn't scale; group-by-destination is the unit (v4) | Firm |
| Cross-layer move restriction | Blocked corrections at the worst moment; direct correction is the better signal (v4) | Reversed |
| UI auto-opens on every drop | Interruption; quiet hold + toast preserves "no silent moves" (v4) | Reversed |
| Per-folder threshold relaxation | Unpredictable moving target; group confirm solves holds (v4) | Cut |
| Single 0–1 confidence ladder across tiers | Scales not comparable; per-tier empirical calibration (v4) | Reversed |
| Per-level LLM calls in recursion | Up to 4× cost/latency; one call returns full path (v4) | Clarified |
| Rules UI | CRUD for a rarely-edited file; passive suggestions are the interface (v4) | Cut |
| AI-proposed rules as blocking stage | Mandatory interruption; replaced by passive ignorable rows (v4) | Amended |
| `launcher.bat` cold-start per use | Slow (torch); resident server via startup task (v4) | Reversed |
| Bundling app into an executable (v1) | 2–4GB torch bundles, Defender false-positives, fights iteration loop; resident server makes launch invisible anyway (v5) | Firm |
| Scoped per-folder inboxes | One capture mechanism; v3 self-contradiction resolved (v4) | Firm |
| WebSockets for progress | SSE simpler, one fewer dependency (v4) | Replaced |
| Physical multi-hop routing | Stranded files on crash; in-memory resolution | Firm |
| Explorer/source moves as learning signal | Ambiguous intent | Firm |
| Near-duplicate text detection | Version decisions are consequential; manual review better | Firm |
| Source prestige ranking | Shortest-path heuristic sufficient | Firm |
| Partial hashing for video/audio | Not justified at 69GB — **re-evaluate at external-drive phase** (1.36TB full-hash is hours of I/O) | Conditional |
| OCR / pytesseract | Redundant — Tier 5 Sonnet vision reads scans better | Firm |
| Optimize panel in Settings | Not v1 | Firm |
| Windows tray application (as primary) | Drop window covers the need; full tray app is overkill | Firm |
| BGE-M3 embeddings | Multilingual/heavy; Nomic right for English | Firm |
| Local LLM for folder descriptions | One bad seed poisons a folder embedding permanently; worth $0.001 | Firm |
| In-place reorganization | (Now moot under no-delete, but historically: no rollback on a bad run) | Firm |
| Copying GPL open source (dupeGuru etc.) | Viral license; boilerplate cheap with AI assistance | Firm |

---

## Open Questions

### 1. OneDrive redirection check — **pre-implementation blocker**
Desktop/Documents may be OneDrive-redirected with Files On-Demand, so many "files" are cloud-only stubs (`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`). Reading a stub fails or triggers mass downloads. Note: path-capture means analysis reads files in place, so a stub dropped onto the window must be detected and either hydrated-then-read or skipped-and-flagged. Decide policy; surface the check in the setup wizard. Check this machine before writing code.

### 2. Drop-window framework
`pywebview` vs. minimal `Tauri`/`Electron` shell for the drop-target window. Tradeoff: pywebview is Python-native (no JS toolchain, smaller) but thinner drag-drop ergonomics; Tauri/Electron give richer DnD at the cost of a second runtime. Lean pywebview unless DnD payload handling proves limiting.

### 3. Threshold calibration values
Per-tier thresholds set empirically from the dry-run on Downloads (655 files). Config values are placeholders. Validates the 70–80% no-API claim.

### 4. Filename collision policy
Two *different* files with the same name routed to the same destination. Recommendation direction: deterministic suffix (` (2)` or short-hash), recorded in registry; never overwrite.

### 5. Setup / First Launch Experience (mostly specified — see below)
Remaining detail: exact OneDrive policy presentation; toast library choice.

### 6. External Drive Phase
~1.36TB external drive (`dell_backup`, `macbook_backup`, etc.) deferred. No architectural change — path capture and `known_source` already handle arbitrary volumes. Re-evaluate partial hashing (see rejected list) when this phase starts.

---

## Setup Wizard (specified)

Served at `/setup` by the resident server; the server serves `/setup` whenever config is incomplete, otherwise the normal UI. Restart-from-step-1 on abandonment (only the API key persists, since keyring writes immediately; step 2 becomes "key stored ✓ / replace?"). No resume-state machinery.

1. **Output destination** — default `E:\organized`, browsable; validate drive present, writable, free space vs. buffer.
2. **API key** — input → keyring → validate with a minimal Haiku call (fail fast).
3. **Environment check** — automatic OneDrive scan of likely sources; if redirection/stubs found, present the hydrate-vs-skip policy; else a green checkmark.
4. **Seed taxonomy** — the nine folders as an editable list (rename/remove/add); `unsorted\` shown but locked.
5. **Finish** — create the tree, register the Windows startup task, launch the drop window, write config, flip the configured flag, land on the empty review UI with one line: *drag files onto Sortilege to begin.*

**Step zero:** one-time `setup.bat` (via uv: create env, install deps, start server, open `/setup`). Never needed again after step 5 registers the startup task.

---

## Working Style Notes
- **Dense and direct.** No filler, no performative positivity, no "great question!" openers.
- **Recommendation first**, before alternatives.
- **One question at a time** when interviewing for design decisions, with recommendation inline.
- **No call-to-action closers.**
- **Agreed = move on.** Don't restate confirmed decisions.
- **Decisions are locked** once confirmed — but well-argued challenges with new information are welcome (v4 and v5 are both products of adversarial review). Distinguish re-litigating (bad) from new argument with new information (welcome).
- **Simplicity challenges welcome.** Justify complexity explicitly.
- **Analytical, systems-oriented.** Surface dependencies and precedence.
- **No emojis. Document outputs, not conversation.**

---

## Recommended Next Steps

1. **OneDrive check** — five minutes; blocks everything if positive. First.
2. **Design is complete enough to build — start with the SQLite schema above** as `schema.sql`; it's the hard dependency for all modules.
3. **Build `core/registry.py`** — SQLite interface; all reads/writes funnel through it (single-writer).
4. **Build `core/taxonomy.py`** — node CRUD on the registry.
5. **Build `core/extractor.py`** — text/content extraction (Tiers 4/5 + embeddings); long-path handling lives here and at every filesystem touchpoint.
6. **Build `core/embeddings.py`** — Nomic wrapper, folder embedding generation/update.
7. **Build `core/cascade.py`** — five tiers (embedding recursion + single-call LLM path resolution).
8. **Build `cli.py` dry-run harness** — run the cascade against real files, log tier/score/destination, move nothing; calibrate thresholds on Downloads before any UI. Dev-only.
9. **Build `librarian/deduper.py`** — hash + pHash; `known_source` matching.
10. **Build `librarian/router.py`** — full-path resolution + move/copy/skip planning.
11. **Build `librarian/intake.py`** — receive dropped paths from the drop window, enqueue.
12. **Build `dropwindow/`** — desktop drop-target shell; post paths to backend.
13. **Build `librarian/learner.py`** — embedding updates on UI move.
14. **Build `librarian/suggester.py`** — folder + rule proposals from correction log.
15. **Build Review UI** — split pane, destination-group rows, expand/detail, suggestion rows, new-folder flow, **batch undo**.
16. **Build `api/`** — FastAPI routes + SSE.
17. **Setup wizard + startup-task registration** — server resident thereafter; drop window + browser shortcut are the daily entry points.
18. **First real run** — drag Downloads (655 files) onto Sortilege. Validate routing, group review, move/copy/skip execution, dedup, undo against real data before the full corpus.
19. **External drives phase** — after core is validated.

---

*End of handoff document. All decisions above are confirmed unless explicitly marked as open questions. Begin the next session by asking which open question or next step the user wants to tackle first.*
