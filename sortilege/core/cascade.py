"""
Five-tier classification orchestrator.
Given a file_id, returns a ClassificationResult with the proposed destination
and the tier/confidence that resolved it. One LLM call per file at Tiers 4/5.
"""
import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from sortilege.core import embeddings, registry
from sortilege.core.extractor import extract

_rules: list[dict] | None = None
_rules_path: Path | None = None


@dataclass
class ClassificationResult:
    proposed_node_id: int | None
    planned_op: str          # 'move' | 'copy' | 'skip'
    tier: int
    confidence: float
    reasoning: str
    dupe_of_file_id: int | None = None
    dupe_kind: str | None = None


def configure(rules_path: Path) -> None:
    global _rules_path
    _rules_path = rules_path
    _reload_rules()


def _reload_rules() -> None:
    global _rules
    if _rules_path and _rules_path.exists():
        with open(_rules_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _rules = data.get("rules", []) if data else []
    else:
        _rules = []


def _get_rules() -> list[dict]:
    if _rules is None:
        _reload_rules()
    return _rules or []


def classify(
    file_id: int,
    output_root: Path,
    config: dict,
) -> ClassificationResult:
    """
    Run the five-tier cascade for a single file.
    config keys used: confidence_thresholds, api_cost_ceiling_usd,
                      tier4_model, tier5_model, min_size_for_api_bytes
    """
    file = registry.get_file(file_id)
    if file is None:
        raise ValueError(f"File {file_id} not found")

    source_path = file["source_path"]
    thresholds = config.get("confidence_thresholds", {})

    # -----------------------------------------------------------------------
    # Pre-hash path check — skip reading the file entirely if path is known
    # -----------------------------------------------------------------------
    known = registry.get_known_source_by_path(source_path)
    if known:
        canonical = registry.get_file(known["duplicates_file_id"])
        return ClassificationResult(
            proposed_node_id=canonical["proposed_node_id"] if canonical else None,
            planned_op="skip",
            tier=0,
            confidence=1.0,
            reasoning="Known cross-drive source — already filed",
            dupe_of_file_id=known["duplicates_file_id"],
            dupe_kind="exact",
        )

    # -----------------------------------------------------------------------
    # Tier 1 — Exact hash match
    # -----------------------------------------------------------------------
    sha256 = file["sha256"]
    existing = registry.get_file_by_sha256(sha256)
    if existing and existing["id"] != file_id and existing["state"] not in ("error", "captured"):
        return ClassificationResult(
            proposed_node_id=existing["proposed_node_id"],
            planned_op="skip",
            tier=1,
            confidence=1.0,
            reasoning=f"Exact duplicate of file id={existing['id']}",
            dupe_of_file_id=existing["id"],
            dupe_kind="exact",
        )

    known_by_hash = registry.get_known_source_by_hash(sha256)
    if known_by_hash:
        return ClassificationResult(
            proposed_node_id=None,
            planned_op="skip",
            tier=1,
            confidence=1.0,
            reasoning="Hash matches a known cross-drive original",
            dupe_of_file_id=known_by_hash["duplicates_file_id"],
            dupe_kind="exact",
        )

    # -----------------------------------------------------------------------
    # Tier 2 — Deterministic rules
    # -----------------------------------------------------------------------
    tier2_min = thresholds.get("tier2_rules_min", 0.85)
    rules_result = _apply_rules(file, source_path)
    if rules_result and rules_result[1] >= tier2_min:
        node_id, confidence, reasoning = rules_result
        planned_op = _planned_op(source_path, output_root)
        return ClassificationResult(
            proposed_node_id=node_id,
            planned_op=planned_op,
            tier=2,
            confidence=confidence,
            reasoning=reasoning,
        )

    # -----------------------------------------------------------------------
    # Tier 3 — Embedding match
    # -----------------------------------------------------------------------
    tier3_floor = thresholds.get("tier3_embedding_min") or 0.0
    file_vec = embeddings.embed_file(file_id)
    if file_vec is not None and tier3_floor is not None:
        node_id, score = embeddings.recursive_descent(file_vec, floor=tier3_floor)
        if node_id is not None:
            planned_op = _planned_op(source_path, output_root)
            return ClassificationResult(
                proposed_node_id=node_id,
                planned_op=planned_op,
                tier=3,
                confidence=float(score),
                reasoning=f"Embedding similarity {score:.3f} via recursive descent",
            )

    # -----------------------------------------------------------------------
    # Budget check before API tiers
    # -----------------------------------------------------------------------
    ceiling = config.get("api_cost_ceiling_usd", 10.0)
    if registry.get_total_api_cost() >= ceiling:
        return ClassificationResult(
            proposed_node_id=None,
            planned_op="skip",
            tier=4,
            confidence=0.0,
            reasoning="API cost ceiling reached — file paused",
        )

    min_size = config.get("min_size_for_api_bytes", 1024)
    if file["size"] < min_size:
        unsorted = _unsorted_node_id()
        planned_op = _planned_op(source_path, output_root)
        return ClassificationResult(
            proposed_node_id=unsorted,
            planned_op=planned_op,
            tier=3,
            confidence=0.0,
            reasoning="File too small for API classification",
        )

    # -----------------------------------------------------------------------
    # Tier 4 — Haiku (metadata only)
    # -----------------------------------------------------------------------
    tier4_min = thresholds.get("tier4_haiku_min", 0.80)
    tier4_model = config.get("tier4_model", "claude-haiku-4-5-20251001")
    result4 = _call_llm_tier(file, tier=4, model=tier4_model, use_full_text=False)
    if result4 and result4["confidence"] >= tier4_min:
        node_id = _resolve_path_to_node(result4["destination"])
        if node_id is not None:
            planned_op = _planned_op(source_path, output_root)
            _record_usage(tier4_model, result4, file_id)
            return ClassificationResult(
                proposed_node_id=node_id,
                planned_op=planned_op,
                tier=4,
                confidence=result4["confidence"],
                reasoning=result4["reasoning"],
            )
        _record_usage(tier4_model, result4, file_id)

    # -----------------------------------------------------------------------
    # Tier 5 — Sonnet (full content + vision)
    # -----------------------------------------------------------------------
    tier5_min = thresholds.get("tier5_sonnet_min", 0.70)
    tier5_model = config.get("tier5_model", "claude-sonnet-4-6")
    result5 = _call_llm_tier(file, tier=5, model=tier5_model, use_full_text=True)
    if result5:
        _record_usage(tier5_model, result5, file_id)
        if result5["confidence"] >= tier5_min:
            node_id = _resolve_path_to_node(result5["destination"])
            if node_id is not None:
                planned_op = _planned_op(source_path, output_root)
                return ClassificationResult(
                    proposed_node_id=node_id,
                    planned_op=planned_op,
                    tier=5,
                    confidence=result5["confidence"],
                    reasoning=result5["reasoning"],
                )

    # -----------------------------------------------------------------------
    # Fallback — unsorted
    # -----------------------------------------------------------------------
    unsorted = _unsorted_node_id()
    planned_op = _planned_op(source_path, output_root)
    return ClassificationResult(
        proposed_node_id=unsorted,
        planned_op=planned_op,
        tier=5,
        confidence=0.0,
        reasoning="Below all confidence floors — routed to unsorted",
    )


# ---------------------------------------------------------------------------
# Tier 2 helpers
# ---------------------------------------------------------------------------

def _apply_rules(
    file: dict, source_path: str
) -> tuple[int, float, str] | None:
    """Check rules.yaml rules. Returns (node_id, confidence, reasoning) or None."""
    from sortilege.core.extractor import extract as _extract
    path = Path(source_path)
    filename = path.name.lower()
    ext = path.suffix.lower().lstrip(".")

    # Lazy extraction for EXIF checks — only if a rule needs it
    _exif_checked = False
    _exif_data: dict | None = None

    def get_exif() -> dict | None:
        nonlocal _exif_checked, _exif_data
        if not _exif_checked:
            _exif_checked = True
            result = _extract(source_path)
            _exif_data = result.exif
        return _exif_data

    for rule in _get_rules():
        match = rule.get("match", {})
        confidence = float(rule.get("confidence", 0.9))
        destination = rule.get("destination", "")

        if "has_exif" in match:
            exif = get_exif()
            has = exif is not None and bool(exif)
            if match["has_exif"] != has:
                continue

        if "has_gps" in match:
            exif = get_exif()
            has = exif is not None and ("GPSLatitude" in exif or "_location" in exif)
            if match["has_gps"] != has:
                continue

        if "exif_make" in match:
            exif = get_exif()
            if not exif:
                continue
            make_val = exif.get("Make", "")
            pattern = match["exif_make"]
            if pattern != "*" and not fnmatch.fnmatch(make_val.lower(), pattern.lower()):
                continue

        if "filename_pattern" in match:
            pattern = match["filename_pattern"]
            if not fnmatch.fnmatch(filename, pattern.lower()):
                continue

        if "extension" in match:
            rule_ext = match["extension"]
            if isinstance(rule_ext, list):
                if ext not in [e.lower() for e in rule_ext]:
                    continue
            else:
                if ext != rule_ext.lower():
                    continue

        # All match fields passed — resolve destination
        node = registry.get_taxonomy_node_by_rel_path(destination)
        if node is None:
            continue
        return (node["id"], confidence, f"Rule '{rule['name']}' matched")

    return None


# ---------------------------------------------------------------------------
# LLM tier helpers
# ---------------------------------------------------------------------------

def _build_taxonomy_context() -> str:
    nodes = registry.get_all_taxonomy_nodes()
    lines = []
    for n in nodes:
        if n["is_system"]:
            continue
        indent = "  " * n["rel_path"].count("\\")
        desc = f" — {n['description']}" if n.get("description") else ""
        lines.append(f"{indent}{n['rel_path']}{desc}")
    return "\n".join(lines)


def _call_llm_tier(
    file: dict,
    tier: int,
    model: str,
    use_full_text: bool,
) -> dict | None:
    try:
        import anthropic
        import keyring
        api_key = keyring.get_password("sortilege", "anthropic_api_key")
        if not api_key:
            _logger.warning("No Anthropic API key in keyring — skipping LLM tier")
            return None
        client = anthropic.Anthropic(api_key=api_key)

        taxonomy = _build_taxonomy_context()
        snippet = file.get("extracted_snippet") or ""

        if use_full_text:
            result = extract(file["source_path"])
            content_text = result.text[:4000] if result.text else snippet
            thumbnail_bytes = result.thumbnail
        else:
            content_text = snippet
            thumbnail_bytes = None

        user_content: list = []

        if tier == 5 and thumbnail_bytes:
            import base64
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(thumbnail_bytes).decode(),
                },
            })

        prompt_text = (
            f"You are a file organizer. Given the file metadata and folder taxonomy below, "
            f"return the best destination path for this file.\n\n"
            f"FILE:\n"
            f"- Filename: {Path(file['source_path']).name}\n"
            f"- Extension: {file.get('ext', '')}\n"
            f"- Size: {file.get('size', 0)} bytes\n"
            f"- Modified: {file.get('mtime', 'unknown')}\n"
            f"- Content preview: {content_text}\n\n"
            f"TAXONOMY:\n{taxonomy}\n\n"
        )
        if tier == 5 and thumbnail_bytes:
            prompt_text += (
                "If this is a scanned document, use the image to determine content.\n\n"
            )
        prompt_text += (
            'Respond with JSON only:\n'
            '{"destination": "relative/path/to/folder", '
            '"confidence": 0.0, '
            '"reasoning": "one sentence explanation"}'
        )
        user_content.append({"type": "text", "text": prompt_text})

        message = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": user_content}],
        )

        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())

        return {
            "destination": parsed.get("destination", ""),
            "confidence": float(parsed.get("confidence", 0.0)),
            "reasoning": parsed.get("reasoning", ""),
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }

    except Exception as e:
        return None


def _record_usage(model: str, result: dict, file_id: int) -> None:
    input_t = result.get("input_tokens", 0) or 0
    output_t = result.get("output_tokens", 0) or 0
    # Approximate pricing — actual rates from Anthropic docs
    if "haiku" in model.lower():
        cost = (input_t * 0.80 + output_t * 4.0) / 1_000_000
    else:
        cost = (input_t * 3.0 + output_t * 15.0) / 1_000_000
    registry.record_api_usage(
        model=model,
        input_tokens=input_t,
        output_tokens=output_t,
        cost_usd=cost,
        file_id=file_id,
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _planned_op(source_path: str, output_root: Path) -> str:
    try:
        src_drive = Path(source_path).drive.upper()
        dst_drive = output_root.drive.upper()
        return "move" if src_drive == dst_drive else "copy"
    except Exception:
        return "copy"


def _resolve_path_to_node(destination: str) -> int | None:
    """Find the deepest existing taxonomy node matching the LLM-returned path."""
    if not destination:
        return None
    # Normalise separators
    dest = destination.replace("/", "\\").strip("\\")
    # Try exact match first
    node = registry.get_taxonomy_node_by_rel_path(dest)
    if node:
        return node["id"]
    # Walk up until we find a match (LLM may propose a non-existent subfolder)
    parts = dest.split("\\")
    for i in range(len(parts) - 1, 0, -1):
        partial = "\\".join(parts[:i])
        node = registry.get_taxonomy_node_by_rel_path(partial)
        if node:
            return node["id"]
    return None


def _unsorted_node_id() -> int | None:
    node = registry.get_taxonomy_node_by_rel_path("unsorted")
    return node["id"] if node else None
