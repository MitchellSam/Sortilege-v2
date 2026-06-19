"""FastAPI application — REST API + SSE + static UI serving."""

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import keyring
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from sortilege.api import sse
from sortilege.core import cascade, embeddings, registry
from sortilege.core.extractor import long_path
from sortilege.core.taxonomy import create_node, get_unsorted_node
from sortilege.librarian import deduper, intake as intake_lib, learner, suggester
from sortilege.librarian import router as router_mod

# ---------------------------------------------------------------------------
# Workspace state — populated in lifespan
# ---------------------------------------------------------------------------
_workspace: Path = Path(os.environ.get("SORTILEGE_WORKSPACE", r"C:\sortilege-workspace"))
_config: dict = {}
_output_root: Path = Path(r"C:\sortilege-output")
_rules_path: Path = _workspace / "rules.yaml"
_config_path: Path = _workspace / "config.json"


def _reload_config() -> dict:
    global _config, _output_root, _rules_path, _config_path, _workspace
    if _config_path.exists():
        _config = json.loads(_config_path.read_text(encoding="utf-8"))
    _output_root = Path(_config.get("output_root", str(_output_root)))
    return _config


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _workspace, _config_path, _rules_path

    db_path = _workspace / "sortilege.db"
    schema_path = Path(__file__).parent.parent.parent / "schema.sql"
    _rules_path = _workspace / "rules.yaml"
    _config_path = _workspace / "config.json"

    registry.init_db(db_path, schema_path)
    _reload_config()
    cascade.configure(_rules_path)
    router_mod.configure(_config, _output_root)
    sse.init(asyncio.get_running_loop())

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, embeddings.load_model)

    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)

_UI_DIST = Path(__file__).parent.parent / "ui" / "dist"


# Redirect / based on config state
@app.get("/")
async def root():
    if not _config.get("configured"):
        return RedirectResponse("/setup")
    return RedirectResponse("/app")


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@app.post("/api/intake")
async def api_intake(req: intake_lib.IntakeRequest, background_tasks: BackgroundTasks):
    return intake_lib.handle_intake(req, background_tasks)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@app.get("/api/files")
async def api_files(state: str = "held"):
    if state != "held":
        files = registry.get_files_by_state(state)
        return {"files": files}

    groups_raw = registry.get_held_groups()
    groups: list[dict] = []
    for g in groups_raw:
        node_id = g["proposed_node_id"]
        node = registry.get_taxonomy_node(node_id) if node_id is not None else None
        files = registry.get_files_for_node(node_id, state="held")

        if files and files[0].get("planned_op") == "skip" and files[0].get("dupe_of_file_id"):
            kind = "dupe"
        else:
            kind = "destination"

        groups.append({
            "node_id": node_id,
            "rel_path": node["rel_path"] if node else "",
            "kind": kind,
            "planned_op": g["planned_op"],
            "file_count": g["file_count"],
            "min_confidence": g["min_confidence"],
            "files": files,
        })

    pending_suggestions = registry.get_pending_suggestions()
    suggestions = []
    for s in pending_suggestions:
        row = dict(s)
        try:
            row["payload"] = json.loads(row["payload"])
        except Exception:
            pass
        suggestions.append(row)

    counts_all = registry.get_counts_by_state()
    counts = {
        "held": counts_all.get("held", 0),
        "skipped": counts_all.get("skipped", 0),
        "errors": counts_all.get("error", 0),
        "budget_paused": counts_all.get("budget_paused", 0),
    }

    return {"groups": groups, "suggestions": suggestions, "counts": counts}


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

@app.get("/api/taxonomy")
async def api_taxonomy():
    nodes = registry.get_all_taxonomy_nodes()
    return {"nodes": nodes}


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

class ConfirmRequest(BaseModel):
    file_ids: list[int]
    overrides: dict[str, int] = {}  # str(file_id) → node_id


@app.post("/api/confirm")
async def api_confirm(req: ConfirmRequest):
    file_ops: list[dict] = []
    redundant_sources: list[dict] = []
    moved = copied = skipped = errors = 0

    for file_id in req.file_ids:
        file = registry.get_file(file_id)
        if file is None:
            errors += 1
            continue

        effective_node_id = req.overrides.get(str(file_id), file.get("proposed_node_id"))
        node = registry.get_taxonomy_node(effective_node_id) if effective_node_id is not None else None
        planned_op = file.get("planned_op", "move")

        if planned_op == "skip":
            file_ops.append({
                "file_id": file_id,
                "action": "skip",
                "from_path": file.get("source_path"),
                "to_path": None,
                "new_state": "skipped",
                "node_id": effective_node_id,
            })
            skipped += 1
            continue

        if node is None:
            registry.set_file_error(file_id, "No destination node")
            errors += 1
            continue

        src = file["source_path"]
        filename = Path(src).name
        dest_dir = _output_root / node["rel_path"]
        dest = dest_dir / filename

        # Avoid collisions
        dest = _unique_dest(dest)

        try:
            os.makedirs(long_path(str(dest_dir)), exist_ok=True)
            if planned_op == "move":
                shutil.move(long_path(src), long_path(str(dest)))
                file_ops.append({
                    "file_id": file_id,
                    "action": "move",
                    "from_path": src,
                    "to_path": str(dest),
                    "new_state": "moved",
                    "node_id": effective_node_id,
                })
                moved += 1
            else:  # copy
                shutil.copy2(long_path(src), long_path(str(dest)))
                dest_sha256 = deduper.compute_sha256(str(dest))
                if dest_sha256 != file["sha256"]:
                    os.remove(long_path(str(dest)))
                    raise ValueError("SHA-256 mismatch after copy")
                file_ops.append({
                    "file_id": file_id,
                    "action": "copy",
                    "from_path": src,
                    "to_path": str(dest),
                    "new_state": "copied",
                    "node_id": effective_node_id,
                })
                registry.create_known_source(src, file["sha256"], file_id)
                redundant_sources.append({
                    "file_id": file_id,
                    "source_path": src,
                    "destination_rel_path": str(dest.relative_to(_output_root)),
                })
                copied += 1
        except Exception as exc:
            registry.set_file_error(file_id, str(exc))
            errors += 1

    # Capture original proposals before execute_batch_confirm overwrites proposed_node_id
    original_proposals: dict[int, int | None] = {}
    for op in file_ops:
        f = registry.get_file(op["file_id"])
        if f:
            original_proposals[op["file_id"]] = f.get("proposed_node_id")

    batch_id = registry.execute_batch_confirm(file_ops)

    for op in file_ops:
        if op["action"] in ("move", "copy"):
            learner.on_move(
                op["file_id"],
                original_proposals.get(op["file_id"]),
                op.get("node_id"),
            )

    suggester.generate_suggestions()

    return {
        "batch_id": batch_id,
        "moved": moved,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "redundant_sources": redundant_sources,
    }


def _unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        candidate = dest.parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

class UndoRequest(BaseModel):
    batch_id: int


@app.post("/api/undo")
async def api_undo(req: UndoRequest):
    batch = registry.get_batch(req.batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["undone"]:
        raise HTTPException(status_code=409, detail="Batch already undone")

    actions = registry.get_action_log_for_batch(req.batch_id)
    undo_ops: list[dict] = []

    for action in reversed(actions):
        act = action["action"]
        from_path = action["from_path"]
        to_path = action["to_path"]
        file_id = action["file_id"]

        if act == "move" and from_path and to_path:
            dest_dir = Path(from_path).parent
            os.makedirs(long_path(str(dest_dir)), exist_ok=True)
            shutil.move(long_path(to_path), long_path(from_path))
            undo_ops.append({
                "file_id": file_id,
                "action": "undo_move",
                "from_path": to_path,
                "to_path": from_path,
            })
        elif act == "copy" and to_path:
            try:
                os.remove(long_path(to_path))
            except OSError:
                pass
            deduper.remove_known_source(file_id)
            undo_ops.append({
                "file_id": file_id,
                "action": "undo_copy",
                "from_path": to_path,
                "to_path": None,
            })
        elif act == "skip":
            undo_ops.append({
                "file_id": file_id,
                "action": "undo_skip",
                "from_path": None,
                "to_path": None,
            })

    registry.execute_batch_undo(req.batch_id, undo_ops)
    return {"batch_id": req.batch_id, "undone": len(undo_ops)}


# ---------------------------------------------------------------------------
# Folder creation
# ---------------------------------------------------------------------------

class FolderRequest(BaseModel):
    parent_id: int
    name: str


@app.post("/api/folder")
async def api_folder(req: FolderRequest):
    parent = registry.get_taxonomy_node(req.parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent node not found")

    description = await _generate_folder_description(req.name, parent["rel_path"])
    node_id = create_node(
        parent_id=req.parent_id,
        name=req.name,
        output_root=_output_root,
        description=description,
    )
    node = registry.get_taxonomy_node(node_id)
    return node


async def _generate_folder_description(name: str, parent_rel: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_folder_description, name, parent_rel)


def _sync_folder_description(name: str, parent_rel: str) -> str:
    try:
        import anthropic as _anthropic
        api_key = keyring.get_password("sortilege", "anthropic_api_key")
        if not api_key:
            return ""
        client = _anthropic.Anthropic(api_key=api_key)
        model = _config.get("description_model", "claude-haiku-4-5-20251001")
        msg = client.messages.create(
            model=model,
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": (
                    f'Write a one-sentence description (max 15 words) for a file folder '
                    f'named "{name}" inside "{parent_rel}". '
                    f'Plain text, no quotes.'
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

@app.post("/api/suggestion/{suggestion_id}/accept")
async def api_suggestion_accept(suggestion_id: int):
    rows = registry.get_pending_suggestions()
    target = next((r for r in rows if r["id"] == suggestion_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    payload = json.loads(target["payload"])

    if target["kind"] == "folder":
        parent_id = payload.get("parent_node_id")
        proposed_path: str = payload.get("proposed_path", "")
        folder_name = proposed_path.rsplit("\\", 1)[-1] if "\\" in proposed_path else proposed_path
        node_id = create_node(
            parent_id=parent_id,
            name=folder_name,
            output_root=_output_root,
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, embeddings.update_folder_embedding, node_id)
        registry.update_suggestion_status(suggestion_id, "accepted", resolved=True)
        return {"kind": "folder", "node_id": node_id}

    elif target["kind"] == "rule":
        _append_rule(payload)
        cascade.configure(_rules_path)
        registry.update_suggestion_status(suggestion_id, "accepted", resolved=True)
        return {"kind": "rule"}

    raise HTTPException(status_code=400, detail="Unknown suggestion kind")


def _append_rule(payload: dict) -> None:
    import yaml
    data: dict[str, Any] = {}
    if _rules_path.exists():
        with open(_rules_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    rules: list = data.get("rules", [])
    rules.append({
        "name": f"auto-{payload['ext']}-to-{payload['destination'].replace(chr(92), '-')}",
        "match": payload.get("match", {"extension": payload["ext"]}),
        "destination": payload["destination"],
        "confidence": 0.90,
    })
    data["rules"] = rules
    with open(_rules_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


@app.post("/api/suggestion/{suggestion_id}/dismiss")
async def api_suggestion_dismiss(suggestion_id: int):
    registry.update_suggestion_status(suggestion_id, "dismissed", resolved=True)
    return {"dismissed": suggestion_id}


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------

@app.get("/api/sse/progress")
async def api_sse(request: Request):
    return EventSourceResponse(sse.event_generator(request))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def api_config_get():
    _reload_config()
    return _config


@app.post("/api/config")
async def api_config_set(body: dict):
    _config.update(body)
    _config_path.write_text(json.dumps(_config, indent=2), encoding="utf-8")
    router_mod.configure(_config, Path(_config.get("output_root", str(_output_root))))
    return _config


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@app.get("/api/batches")
async def api_batches(limit: int = 10):
    batches = registry.get_recent_batches(limit=limit)
    return {"batches": batches}


# ---------------------------------------------------------------------------
# Setup wizard endpoints
# ---------------------------------------------------------------------------

class ValidatePathRequest(BaseModel):
    output_root: str


@app.post("/api/setup/validate-path")
async def api_setup_validate_path(req: ValidatePathRequest):
    p = Path(req.output_root)
    try:
        p.mkdir(parents=True, exist_ok=True)
        test = p / ".sortilege_write_test"
        test.write_text("ok")
        test.unlink()
        import shutil as _shutil
        free = _shutil.disk_usage(str(p)).free
        return {"ok": True, "free_gb": free / (1024 ** 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class ValidateKeyRequest(BaseModel):
    api_key: str


@app.post("/api/setup/validate-key")
async def api_setup_validate_key(req: ValidateKeyRequest):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _sync_validate_key, req.api_key)
    return result


def _sync_validate_key(api_key: str) -> dict:
    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        import keyring as _keyring
        _keyring.set_password("sortilege", "anthropic_api_key", api_key)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/setup/check-env")
async def api_setup_check_env():
    import ctypes
    checks = []
    for label, folder in [
        ("Desktop",   Path.home() / "Desktop"),
        ("Downloads", Path.home() / "Downloads"),
        ("Documents", Path.home() / "Documents"),
    ]:
        ok = folder.exists()
        detail = "ready" if ok else "not found"
        checks.append({"label": label, "ok": ok, "detail": detail})
    return {"checks": checks}


class SetupFinishRequest(BaseModel):
    output_root: str
    api_key: str
    folders: list[str]


@app.post("/api/setup/finish")
async def api_setup_finish(req: SetupFinishRequest):
    global _output_root

    output_root = Path(req.output_root)
    _output_root = output_root

    # Save API key to keyring
    import keyring as _keyring
    if req.api_key:
        _keyring.set_password("sortilege", "anthropic_api_key", req.api_key)

    # Create output directory
    output_root.mkdir(parents=True, exist_ok=True)

    # Seed taxonomy
    from sortilege.core.taxonomy import seed_taxonomy
    seed_taxonomy(output_root)

    # Register startup task
    import subprocess
    import sys
    python = sys.executable
    main_py = Path(__file__).parent.parent.parent / "main.py"
    task_cmd = (
        f'schtasks /create /tn "Sortilege" /tr \\"{python}\\" \\"{main_py}\\"'
        f' /sc ONLOGON /delay 0000:30 /ru %USERNAME% /f'
    )
    try:
        subprocess.run(task_cmd, shell=True, check=True, capture_output=True)
    except Exception:
        pass  # non-fatal if schtasks fails

    # Write config
    new_config = {
        **_config,
        "output_root": str(output_root),
        "workspace_dir": str(_workspace),
        "configured": True,
        "confidence_thresholds": {
            "tier2_rules_min": 0.85,
            "tier3_embedding_min": None,
            "tier4_haiku_min": 0.80,
            "tier5_sonnet_min": 0.70,
            "group_preselect_min": 0.85,
        },
        "tier4_model": "claude-haiku-4-5-20251001",
        "tier5_model": "claude-sonnet-4-6",
        "description_model": "claude-haiku-4-5-20251001",
        "api_cost_ceiling_usd": 10.0,
        "checkpoint_batch_size": 100,
        "min_size_for_api_bytes": 1024,
        "destination_space_buffer_pct": 10,
    }
    _workspace.mkdir(parents=True, exist_ok=True)
    _config_path.write_text(json.dumps(new_config, indent=2), encoding="utf-8")
    _config.update(new_config)
    router_mod.configure(_config, _output_root)

    return {"ok": True}


# ---------------------------------------------------------------------------
# Static UI + setup redirect
# ---------------------------------------------------------------------------

if _UI_DIST.exists():
    app.mount("/app", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
