"""Passive folder and rule proposal generation from the correction log."""

import json
import logging
from collections import Counter

from sortilege.core import registry

logger = logging.getLogger(__name__)

_FOLDER_MIN_FILES = 5   # held files at same level before proposing a new child


def generate_suggestions() -> None:
    """Scan held files and correction history; create pending suggestions as needed.

    Called after each batch confirm. Fast — reads only, no LLM calls.
    """
    _propose_folders()
    _propose_rules()


# ---------------------------------------------------------------------------
# Folder proposals
# ---------------------------------------------------------------------------

def _propose_folders() -> None:
    groups = registry.get_held_groups()
    for group in groups:
        if group["file_count"] < _FOLDER_MIN_FILES:
            continue

        node_id = group["proposed_node_id"]
        node = registry.get_taxonomy_node(node_id) if node_id is not None else None
        if node is None:
            continue

        parent_rel = node["rel_path"]
        # Derive a candidate child name from the most common extension in the group
        files = registry.get_files_for_node(node_id, state="held")
        ext_counts: Counter[str] = Counter(
            f["ext"] for f in files if f.get("ext")
        )
        top_ext = ext_counts.most_common(1)[0][0] if ext_counts else "misc"
        proposed_rel = f"{parent_rel}\\{top_ext}"

        payload = json.dumps({
            "proposed_path": proposed_rel,
            "parent_node_id": node_id,
        })

        existing = registry.find_suggestion("folder", f'"parent_node_id": {node_id}')
        evidence = group["file_count"]

        if existing is None:
            registry.create_suggestion("folder", payload, evidence)
        elif existing["status"] == "dismissed":
            if evidence >= 2 * existing["evidence_count"]:
                registry.reopen_suggestion(existing["id"], evidence)
        # status == "pending": already surfaced, no action needed


# ---------------------------------------------------------------------------
# Rule proposals
# ---------------------------------------------------------------------------

def _propose_rules() -> None:
    from sortilege.core.cascade import _get_rules  # noqa: PLC2701

    patterns = registry.get_correction_patterns(min_count=3)
    existing_rules = _get_rules()

    for pattern in patterns:
        ext = pattern["ext"]
        node_id = pattern["actual_node_id"]
        count = pattern["cnt"]

        node = registry.get_taxonomy_node(node_id)
        if node is None:
            continue
        destination = node["rel_path"]

        # Skip if a rule already covers this extension → destination
        if _rule_exists(existing_rules, ext, destination):
            continue

        payload = json.dumps({
            "ext": ext,
            "destination": destination,
            "match": {"extension": ext},
        })

        existing = registry.find_suggestion("rule", f'"ext": "{ext}"')

        if existing is None:
            registry.create_suggestion("rule", payload, count)
        elif existing["status"] == "dismissed":
            if count >= 2 * existing["evidence_count"]:
                registry.reopen_suggestion(existing["id"], count)


def _rule_exists(rules: list[dict], ext: str, destination: str) -> bool:
    for rule in rules:
        match = rule.get("match", {})
        rule_ext = match.get("extension")
        if rule.get("destination") == destination and _ext_matches(rule_ext, ext):
            return True
    return False


def _ext_matches(rule_ext, ext: str) -> bool:
    if rule_ext is None:
        return False
    if isinstance(rule_ext, list):
        return ext in rule_ext
    return rule_ext == ext
