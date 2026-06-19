"""Full-path resolution loop: stability check → dedup → cascade → hold."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sortilege.core import cascade, registry
from sortilege.librarian import deduper

logger = logging.getLogger(__name__)

_config: dict | None = None
_output_root: Path | None = None


def configure(config: dict, output_root: Path) -> None:
    global _config, _output_root
    _config = config
    _output_root = output_root


def _push_event(event_type: str, data: dict) -> None:
    """Fire an SSE event if the API is running. No-op otherwise (e.g. during dry-run)."""
    try:
        from sortilege.api import sse
        sse.push_event(event_type, data)
    except Exception:
        pass


def _toast(msg: str) -> None:
    try:
        from winotify import Notification
        Notification(app_id="Sortilege", title="Sortilege", msg=msg).show()
    except Exception:
        logger.debug("Toast unavailable: %s", msg)


def _is_stable(path: str) -> bool:
    try:
        return (
            os.path.exists(path)
            and os.access(path, os.R_OK)
            and os.path.getsize(path) > 0
        )
    except OSError:
        return False


def _node_rel_path(node_id: int | None) -> str:
    if node_id is None:
        return ""
    node = registry.get_taxonomy_node(node_id)
    return node["rel_path"] if node else ""


def process_batch(paths: list[str]) -> None:
    """Classify a list of paths and leave each file in held/budget_paused/error state."""
    config = _config or {}
    output_root = _output_root or Path(".")

    held = skipped = errors = budget_paused_count = 0

    for path in paths:
        file_id: int | None = None
        try:
            if not _is_stable(path):
                logger.warning("Skipping unstable or unreadable file: %s", path)
                errors += 1
                continue

            stat = os.stat(path)
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            ext = Path(path).suffix.lstrip(".").lower() or None

            sha256 = deduper.compute_sha256(path)

            file_id = registry.create_file(
                sha256=sha256,
                size=size,
                ext=ext,
                source_path=path,
                mtime=mtime,
            )
            registry.update_file_state(file_id, "queued")

            phash = deduper.compute_phash(path)
            if phash is not None:
                registry.set_file_phash(file_id, phash)

            registry.update_file_state(file_id, "classifying")

            result = cascade.classify(file_id, output_root, config)

            # Detect budget_paused: the budget-ceiling short-circuit in cascade
            # returns skip + no dupe context + no proposed destination.
            is_budget_paused = (
                result.planned_op == "skip"
                and result.dupe_of_file_id is None
                and result.proposed_node_id is None
            )

            registry.update_file_proposal(
                file_id=file_id,
                proposed_node_id=result.proposed_node_id,
                planned_op=result.planned_op,
                tier=result.tier,
                confidence=result.confidence,
                reasoning=result.reasoning,
                dupe_of_file_id=result.dupe_of_file_id,
                dupe_kind=result.dupe_kind,
            )

            new_state = "budget_paused" if is_budget_paused else "held"
            registry.update_file_state(file_id, new_state)

            if is_budget_paused:
                budget_paused_count += 1
                _push_event("budget_paused", {
                    "paused_count": budget_paused_count,
                    "spent_usd": registry.get_total_api_cost(),
                    "ceiling_usd": config.get("api_cost_ceiling_usd", 10.0),
                })
            elif result.planned_op == "skip":
                skipped += 1
            else:
                held += 1

            _push_event("file_classified", {
                "file_id": file_id,
                "filename": Path(path).name,
                "state": new_state,
                "tier": result.tier,
                "confidence": result.confidence,
                "proposed_path": _node_rel_path(result.proposed_node_id),
            })

        except Exception as exc:
            logger.exception("Error processing %s", path)
            if file_id is not None:
                registry.set_file_error(file_id, str(exc))
            errors += 1

    _push_event("batch_ready", {
        "held": held,
        "skipped": skipped,
        "errors": errors,
        "budget_paused": budget_paused_count,
    })

    reviewable = held + skipped
    if reviewable > 0:
        _toast(f"{reviewable} file{'s' if reviewable != 1 else ''} ready for review")
