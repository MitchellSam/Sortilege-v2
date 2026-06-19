# Sortilege — Claude Design Prompt

## Overview

Design a browser-based review UI for **Sortilege**, a personal AI-powered file organization app on Windows. The app classifies files dropped onto a desktop widget and proposes destinations in an organized folder tree. The user opens this UI in their browser when they're ready to review, confirms proposals in bulk, and can undo any batch. The app never deletes — it moves or copies keepers and skips duplicates.

The UI should feel like a **calm, competent utility** — not a dashboard, not a marketing page. Think VS Code's file explorer crossed with a review queue. Dark mode default. Minimal chrome. Dense information without clutter.

---

## Design Principles

- **Group-level review, not file-level.** The primary interaction is confirming a cluster of 10–400 files headed to the same destination with one click. Individual file inspection is always available but never required.
- **Quiet confidence.** Use color and density to communicate, not badges or alerts. Green means above threshold; amber means held for attention. No red unless something failed.
- **Zero learning curve.** A user who has never seen this screen should understand what to do within 5 seconds: scan the groups, confirm the ones that look right, expand any that need a closer look.
- **Drag is the power gesture.** Dragging a file (or files) from the right pane onto a folder in the left tree is how corrections happen. It should feel natural and immediate.

---

## Color & Typography

- **Dark theme.** Background: near-black (not pure black). Cards/panels: slightly lighter. Text: off-white for primary, muted gray for secondary.
- **Accent:** a single cool accent color (teal or muted blue) for interactive elements, selection states, and the confirm button.
- **Confidence colors:** Green (above threshold, high confidence). Amber/gold (below threshold, held for review). Red only for errors.
- **Font:** System font stack or a clean monospace-adjacent sans-serif (Inter, JetBrains Mono for paths/filenames). File paths always in monospace.
- **Density:** Compact rows. This UI may display 50+ groups; vertical space is precious.

---

## Screen 1: Review UI (Main Screen)

This is the screen users see 95% of the time.

### Layout: Split Pane

**Left pane (≈280px, resizable): Folder Tree**
- Full folder hierarchy of `E:\organized\`
- Root folders: `financial`, `career`, `health`, `documents`, `photos`, `media`, `code`, `creative`, `unsorted`
- Each node shows: folder icon, name, file count badge (how many files currently proposed to land here)
- Expandable/collapsible with disclosure triangles
- All nodes are **live drag targets** — they highlight on drag-over
- Hover a folder → subtle `+ New Folder` affordance appears (icon or text link, not a button that takes space)
- `unsorted` is visually distinct (dimmer, perhaps italic) to signal it's a fallback, not a real category
- At the bottom of the tree: a small summary line — "E:\organized\ — 2,847 files — 14.3 GB"

**Right pane: Grouped File Queue**

This pane shows files awaiting confirmation, **grouped by proposed destination.**

#### Group Row (collapsed — the primary unit of review)

```
☐  412 files  →  photos\vacation\japan       min confidence 91%    [CONFIRM]
```

Each group row contains:
- Checkbox (for batch select)
- File count
- Arrow (→) indicating direction of the move/copy
- Destination path (monospace, truncated with tooltip if long)
- Minimum confidence in the group (the weakest file determines the color: green if all above threshold, amber if any below)
- **CONFIRM** button (primary accent color, always visible — this is the main CTA per group)
- Subtle expand/collapse chevron

Groups are sorted: highest-confidence first, held (amber) groups at the bottom.

**Special group types:**
- **Dupe groups:** `☐  17 files  →  dupe — already filed    [CONFIRM]` — confirming acknowledges the skip and clears them from the queue. No filesystem action. These show with a distinct muted style (they need the least attention).
- **Error groups:** `⚠  3 files  →  error — unreadable    [expand]` — red accent, no confirm button (errors need individual attention).
- **Copied groups (post-confirm):** in the results/history view, show: `✓  28 files  →  photos\vacation  (copied — originals safe to delete)` — the "originals safe to delete" note is a muted secondary text.

#### Group Row (expanded)

Clicking the chevron or [expand] reveals the individual files inside that group:

```
  ☐  IMG_4832.heic         92%   photos\vacation\japan     3.4 MB   2023-09-14
  ☐  IMG_4833.heic         91%   photos\vacation\japan     3.2 MB   2023-09-14
  ☐  tokyo_tower.jpg       94%   photos\vacation\japan     2.1 MB   2023-09-15
  ☐  receipt_hotel.pdf      78%   photos\vacation\japan     145 KB   2023-09-14   ← amber
```

Each file row:
- Checkbox
- Filename (monospace)
- Individual confidence (color-coded)
- Proposed destination
- File size
- Modified date
- Click → opens the **Detail Panel** (slide-in from right or modal)

Files are individually draggable onto the folder tree to override their destination.

#### Detail Panel (per-file)

When a file row is clicked, a detail panel appears (slide-in right, ~400px):

- **File info:** full filename, extension, size, dates, source path (monospace)
- **AI reasoning:** the `reasoning` text from the cascade ("Matched photos\vacation based on EXIF GPS coordinates and filename pattern IMG_*")
- **Thumbnail/icon:** image thumbnail for images; file type icon for documents; PDF first-page render if available
- **Tier badge:** which tier resolved this file (Tier 2 / Tier 3 / Tier 4 / Tier 5)
- **Confidence:** numeric + bar
- **Source path:** where the file currently lives (shown for cross-drive files especially — helps the user decide about cleanup)
- **Move controls:** destination path (editable — dropdown of recent folders or type to search the tree), or drag the file onto the tree
- **For dupes:** show "Duplicate of: [path to canonical file]" with link/highlight

### Toolbar (top of right pane)

- **Select All High-Confidence** — checks all groups where min confidence ≥ threshold. The primary "I trust the AI, let's go" button.
- **Confirm Selected** — executes all checked groups. Shows a brief summary before executing: "Move 847 files, copy 203 files, acknowledge 17 dupes. Proceed?"
- **Undo** button (with dropdown for recent batches): "Undo last batch (1,067 files, 2 min ago)" — shows the most recent undoable batch inline, dropdown for earlier ones.
- **Filter/sort controls:** by state (held only / all), by confidence (ascending/descending), by destination.

### Passive Suggestion Rows

Interspersed with (or above) the group rows, visually distinct:

```
✦  Suggest creating:  financial\taxes\2023   — would receive 38 held files     [Accept] [Rename] [Dismiss]
✦  Suggest rule:  *.heic from "Camera Roll" → photos\phone  (8 matching corrections)   [Accept] [Dismiss]
```

- Different background or left-border accent (not the same as regular groups)
- **✦** marker (or lightbulb icon) to distinguish from actionable file groups
- `[Accept]` creates the folder / appends the rule and re-resolves held files
- `[Rename]` (folder suggestions only) — inline edit field to change the proposed name before accepting
- `[Dismiss]` — suggestion disappears; won't reappear unless evidence count significantly grows
- These never block workflow — the user can ignore them forever

---

## Screen 2: Setup Wizard

Linear, five-step wizard served at `/setup`. Clean, centered card layout (~600px wide). Progress indicator at top (step dots or numbered bar).

### Step 1: Output Destination
- Heading: "Where should your organized files live?"
- Path input field with browse button, prefilled with `E:\organized`
- Validation feedback: drive present ✓, writable ✓, free space (showing available vs. required)
- [Next] button

### Step 2: API Key
- Heading: "Connect to Claude"
- Password-type input field for Anthropic API key
- On entry: immediate validation (spinner → green check "Connected" or red "Invalid key")
- Note: "Stored securely in Windows Credential Manager — never saved to disk"
- If key already stored (wizard restart): show "API key stored ✓" with a [Replace] option
- [Next] button

### Step 3: Environment Check
- Heading: "Checking your system"
- Automated scan with animated progress
- Results displayed as a checklist:
  - ✓ Desktop — ready (or ⚠ Desktop — OneDrive redirected, files on demand detected)
  - ✓ Downloads — ready
  - ✓ Documents — ready
- If OneDrive issues found: expandable explainer with policy choice (radio buttons): "Hydrate files before processing (downloads cloud-only files)" vs. "Skip cloud-only files (flag for later)"
- [Next] button

### Step 4: Seed Taxonomy
- Heading: "Set up your top-level folders"
- Editable list of nine folder names, each as a row with:
  - Folder icon
  - Editable name field
  - Brief description text (muted, below the name)
  - [×] remove button
- `unsorted` row: shown but grayed/locked with a note: "Fallback for unclassifiable files — can't be removed"
- [+ Add folder] button at the bottom
- [Next] button

### Step 5: Finish
- Heading: "You're all set"
- Summary of what was configured
- [Create folders & start Sortilege] button
- On click: creates the tree, registers the startup task, transitions to the empty Review UI with a centered empty-state message: "Drag files onto the Sortilege window to begin"

---

## Screen 3: Settings (secondary — accessible from nav)

Minimal settings page for changing config post-setup. Not a priority for design; functional is fine.

- Output destination (display, with change button)
- API key (masked, with replace button)
- Cost ceiling ($, editable)
- Current spend (progress bar against ceiling, with "budget paused" state if applicable)
- Confidence thresholds (per-tier, editable — with "these are placeholders until calibrated" note if not yet calibrated)
- [Save] button

---

## Navigation

Top bar or minimal sidebar with:
- **Review** (the main screen — always the default landing)
- **Settings** (gear icon)
- File count in queue: a small badge on the Review nav item showing held file count (e.g., "Review (47)")

No dashboard. No analytics page. No logs page. The review screen IS the app.

---

## Interaction Patterns

### Drag & Drop (Review UI)
- Files (individual or multi-selected) are draggable from the right pane
- Folder tree nodes on the left highlight as valid drop targets on drag-over
- On drop: file's proposed destination updates immediately (row moves to its new group), confidence recalculates, a correction is logged
- Moving to `unsorted` is allowed (file re-enters routing from root)

### Confirm Flow
1. User clicks [Select All High-Confidence] or manually checks groups
2. User clicks [Confirm Selected]
3. Brief confirmation summary appears (inline banner or modal): "Move 412 files, copy 28 files, skip 17 dupes"
4. User clicks [Proceed] (or [Cancel])
5. Progress bar while operations execute
6. Groups disappear from queue; toast or inline banner: "Batch confirmed — 457 files processed. [Undo]"

### Undo Flow
1. User clicks [Undo] in toolbar (or the inline [Undo] in the post-confirm banner)
2. Confirmation: "Undo batch from 2 minutes ago? This will reverse 412 moves and remove 28 copies."
3. On confirm: files return to `held` state and reappear in the queue

### New Folder Creation
1. Hover over a folder in the tree → `+ New Folder` appears
2. Click → inline text input appears as a child node
3. User types folder name, presses Enter
4. Brief spinner while Haiku generates a one-sentence description
5. Description appears below the new folder name (editable before confirming)
6. [Create] / [Cancel] buttons
7. On create: folder appears in tree, held files recalculate (some may now route there)

---

## Empty States

- **Queue empty, folders exist:** centered message: "All caught up. Drag more files onto Sortilege when you're ready."
- **First launch (post-wizard):** centered message: "Drag files onto the Sortilege window to begin." with a subtle illustration or icon of a drag gesture.
- **Budget paused:** amber banner at top of review pane: "API budget reached ($10.00). 234 files waiting. [Raise ceiling] or classify remaining files manually by dragging them to folders."

---

## Responsive Behavior

This is primarily a desktop app (browser window). Minimum viable width: ~900px. Below that, the tree pane collapses to an icon rail or hides behind a toggle. The review pane should use the full available width — groups can be quite wide with long paths.

---

## What This Design is NOT

- Not a file manager. The user doesn't browse their organized files here — that's what Explorer is for.
- Not a dashboard. No charts, no stats, no analytics. The review queue is the product.
- Not a settings-heavy app. Settings exist but are secondary. The defaults should work.
- No onboarding tour. The wizard handles setup; the review screen should be self-explanatory.

---

## Deliverable

Prototype the Review UI (Screen 1) as the primary deliverable — it's 95% of the experience. Include the split pane layout, grouped file queue with expand/collapse, detail panel, toolbar, passive suggestion rows, and the drag-to-correct interaction pattern. The setup wizard (Screen 2) is the secondary deliverable. Settings (Screen 3) is lowest priority.

Use React. Dark theme. The output will be handed to Claude Code for integration with a FastAPI backend.
