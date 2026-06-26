# Sortilege

A personal AI-powered file organization system for Windows. Drag files onto a small desktop window — Sortilege reads them in place, deduplicates, classifies, and proposes destinations. You approve in bulk when you feel like it. It never deletes anything.

## How it works

1. **Drop** — drag files from anywhere onto the Sortilege drop window
2. **Wait** — classification runs silently in the background; a Windows toast fires when the batch is ready
3. **Review** — open the browser UI, approve groups of files headed to the same destination
4. **Undo** — every confirmed batch is fully reversible

Files on the same drive as your output folder are **moved**. Files from other drives are **copied** (your originals stay put). Duplicates are **skipped**. Nothing is ever deleted.

## Classification cascade

Each file is classified by a five-tier system, stopping at the first confident match:

| Tier | Method | Cost |
|------|--------|------|
| 1 | SHA-256 hash (exact duplicate detection) | Free |
| 2 | Deterministic rules (`rules.yaml` — extension, filename pattern, EXIF) | Free |
| 3 | Local embeddings (Nomic Embed via `sentence-transformers`) | Free |
| 4 | Claude Haiku (metadata + content preview) | ~$0.001/file |
| 5 | Claude Sonnet (full text or image; scanned document vision) | ~$0.01/file |

Files that clear no confidence floor land in `unsorted\` — a fallback-only system folder.

## Prerequisites

- Windows 10/11
- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) package manager
- An [Anthropic API key](https://console.anthropic.com/) (for Tiers 4 and 5)
- An output drive with sufficient space (external drive recommended)

## Setup

```bat
.\setup.bat
```

`setup.bat` creates the virtual environment, installs dependencies, starts the resident server, and opens the setup wizard in your browser.

The wizard walks through five steps:

1. **Output destination** — pick the root folder where organized files will land (e.g. `E:\organized\`)
2. **API key** — enter your Anthropic key; stored in Windows Credential Manager, never in a config file
3. **Environment check** — detects OneDrive stubs on source folders
4. **Seed taxonomy** — review and customize the nine top-level folders (you can rename or add; `unsorted` is locked)
5. **Finish** — creates the folder tree, registers a Windows startup task, launches the drop window

After setup, the server and drop window start automatically on login. No terminal needed for daily use.

## Daily use

**Dropping files:** drag any files or folders onto the Sortilege drop window. You'll get a brief visual confirmation. Processing happens in the background.

**Reviewing:** navigate to `http://localhost:8000` in your browser. Files are grouped by proposed destination. You can:
- Confirm a group as-is
- Drag individual files to a different folder before confirming
- Create new subfolders inline
- Undo any previously confirmed batch

**Cross-drive copies:** after confirming, the UI shows you which source files are now redundant (their contents have been verified and copied). Sortilege does not delete them — that's your call.

## Output folder structure

```
E:\organized\
├── financial\        taxes, statements, insurance, receipts
├── career\           resumes, certifications, job-search artifacts
├── health\           medical records, lab results, imaging
├── documents\        identity, legal, manuals, correspondence
├── photos\           personal photos — camera, family, events
├── media\            downloaded images, wallpapers, video, audio
├── code\             projects, snippets, dotfiles
├── creative\         writing, worldbuilding, campaign materials
└── unsorted\         fallback only — files that cleared no confidence floor
```

The top-level folders are customizable during setup. Subfolders are created on demand as the system learns your file patterns.

## Configuration

`config.json` lives in `C:\sortilege-workspace\` (or your chosen `workspace_dir`):

```json
{
  "output_root": "E:\\organized",
  "workspace_dir": "C:\\sortilege-workspace",
  "api_cost_ceiling_usd": 10.00,
  "confidence_thresholds": {
    "tier2_rules_min": 0.85,
    "tier3_embedding_min": null,
    "tier4_haiku_min": 0.80,
    "tier5_sonnet_min": 0.70
  }
}
```

**`api_cost_ceiling_usd`** — when cumulative API spend reaches this limit, files that would need Tier 4/5 enter `budget_paused` state and wait until you raise the ceiling in the review UI. They are never silently dumped to `unsorted`.

**Confidence thresholds** — the values above are placeholders. Calibrate them with the dry-run tool before trusting them on a real batch.

## Dry-run calibration

Before running Sortilege on your actual files, calibrate the classification thresholds:

```bash
python cli.py dry-run --source "C:\Users\You\Downloads" --limit 100
```

This runs the full cascade against real files, logs the tier, score, and proposed destination for every file, and outputs a CSV — without moving anything. Adjust `confidence_thresholds` in `config.json` until the results look right, then run for real.

## Learning and suggestions

Sortilege learns from the moves you make in the review UI:
- When you redirect a file to a different folder than proposed, the folder embeddings update immediately
- After enough corrections to the same destination, Sortilege proposes a new Tier 2 rule (e.g. "always route `.pdf` files matching `tax_*` to `financial\`")
- When many files cluster at the same level without a matching subfolder, Sortilege proposes a new subfolder. Accepting the proposal creates the folder, seeds its embedding from the cluster's content, and re-runs classification on all held files — the clustered files will route into the new folder and appear as a group awaiting your confirmation. The same re-classification happens when you create a folder manually via the `+ New Folder` control in the tree.

Proposals appear in the review UI. Accept with one click or ignore — the system never creates folders or rules without your approval.

## Workspace files

Everything Sortilege writes lives in `workspace_dir` (default `C:\sortilege-workspace\`):

| File | Purpose |
|------|---------|
| `sortilege.db` | SQLite database — all file records, taxonomy, batches, corrections |
| `config.json` | Configuration |
| `rules.yaml` | Tier 2 deterministic rules (edited by accepting rule proposals) |
| `*.log` | Application logs |

The Anthropic API key is stored in Windows Credential Manager (not in the workspace).

## Tech stack

- **Backend:** FastAPI + uvicorn (resident Windows startup process)
- **Frontend:** React (served as static files by FastAPI)
- **Database:** SQLite (WAL mode)
- **Embeddings:** Nomic Embed via `sentence-transformers` (local, loaded once at startup)
- **LLM:** Anthropic Claude (Haiku for Tier 4, Sonnet for Tier 5)
- **Drop window:** `pywebview` desktop shell
- **Live progress:** Server-Sent Events
- **Notifications:** `winotify` Windows toasts
