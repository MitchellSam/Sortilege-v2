"""
SQLite interface. Every database read/write in the entire app goes through this module.
No other module imports sqlite3.
"""
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

# Valid state transitions — enforced on every update_file_state call.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "captured":      {"queued"},
    "queued":        {"classifying"},
    "classifying":   {"held", "budget_paused", "error"},
    "held":          {"moved", "copied", "skipped"},
    "budget_paused": {"queued"},
    "moved":         {"held", "queued"},
    "copied":        {"held", "queued"},
    "skipped":       set(),
    "error":         set(),
}


def init_db(db_path: Path, schema_path: Path) -> None:
    global _conn
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    _conn = conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    assert _conn is not None, "Database not initialized — call init_db first"
    return _conn


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------

def create_file(
    sha256: str,
    size: int,
    ext: str | None,
    source_path: str | None,
    phash: int | None = None,
    mtime: str | None = None,
) -> int:
    now = _now()
    with _lock:
        cur = _db().execute(
            """INSERT INTO file
               (sha256, phash, size, mtime, ext, source_path, state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'captured', ?, ?)""",
            (sha256, phash, size, mtime, ext, source_path, now, now),
        )
        _db().commit()
        return cur.lastrowid


def get_file(file_id: int) -> dict | None:
    row = _db().execute("SELECT * FROM file WHERE id = ?", (file_id,)).fetchone()
    return dict(row) if row else None


def get_file_by_sha256(sha256: str) -> dict | None:
    row = _db().execute("SELECT * FROM file WHERE sha256 = ?", (sha256,)).fetchone()
    return dict(row) if row else None


def update_file_state(file_id: int, new_state: str) -> None:
    with _lock:
        row = _db().execute("SELECT state FROM file WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            raise ValueError(f"File {file_id} not found")
        current = row["state"]
        if new_state not in VALID_TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Invalid state transition {current!r} → {new_state!r} for file {file_id}"
            )
        _db().execute(
            "UPDATE file SET state = ?, updated_at = ? WHERE id = ?",
            (new_state, _now(), file_id),
        )
        _db().commit()


def update_file_proposal(
    file_id: int,
    proposed_node_id: int | None,
    planned_op: str,
    tier: int,
    confidence: float | None,
    reasoning: str | None,
    dupe_of_file_id: int | None = None,
    dupe_kind: str | None = None,
    extracted_snippet: str | None = None,
) -> None:
    with _lock:
        _db().execute(
            """UPDATE file SET
               proposed_node_id = ?, planned_op = ?, tier = ?, confidence = ?,
               reasoning = ?, dupe_of_file_id = ?, dupe_kind = ?,
               extracted_snippet = COALESCE(?, extracted_snippet),
               proposal_updated_at = ?, updated_at = ?
               WHERE id = ?""",
            (
                proposed_node_id, planned_op, tier, confidence, reasoning,
                dupe_of_file_id, dupe_kind, extracted_snippet,
                _now(), _now(), file_id,
            ),
        )
        _db().commit()


def set_file_current_path(file_id: int, current_rel_path: str) -> None:
    with _lock:
        _db().execute(
            "UPDATE file SET current_rel_path = ?, updated_at = ? WHERE id = ?",
            (current_rel_path, _now(), file_id),
        )
        _db().commit()


def set_file_error(file_id: int, detail: str) -> None:
    with _lock:
        _db().execute(
            "UPDATE file SET state = 'error', error_detail = ?, updated_at = ? WHERE id = ?",
            (detail, _now(), file_id),
        )
        _db().commit()


def set_file_phash(file_id: int, phash: int) -> None:
    with _lock:
        _db().execute(
            "UPDATE file SET phash = ?, updated_at = ? WHERE id = ?",
            (phash, _now(), file_id),
        )
        _db().commit()


def get_files_by_state(state: str) -> list[dict]:
    rows = _db().execute("SELECT * FROM file WHERE state = ?", (state,)).fetchall()
    return [dict(r) for r in rows]


def get_held_groups() -> list[dict]:
    """Files grouped by proposed_node_id + planned_op for the review UI."""
    rows = _db().execute(
        """SELECT proposed_node_id, planned_op,
                  COUNT(*) as file_count,
                  MIN(confidence) as min_confidence
           FROM file WHERE state = 'held'
           GROUP BY proposed_node_id, planned_op
           ORDER BY min_confidence DESC NULLS LAST""",
    ).fetchall()
    return [dict(r) for r in rows]


def get_files_for_node(node_id: int | None, state: str = "held") -> list[dict]:
    if node_id is None:
        rows = _db().execute(
            "SELECT * FROM file WHERE state = ? AND proposed_node_id IS NULL",
            (state,),
        ).fetchall()
    else:
        rows = _db().execute(
            "SELECT * FROM file WHERE state = ? AND proposed_node_id = ?",
            (state, node_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_phashes() -> list[tuple[int, int]]:
    """Returns (file_id, phash) for all non-dupe files. Used for in-memory hamming search."""
    rows = _db().execute(
        "SELECT id, phash FROM file WHERE phash IS NOT NULL AND state != 'skipped'"
    ).fetchall()
    return [(r["id"], r["phash"]) for r in rows]


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

def create_taxonomy_node(
    parent_id: int | None,
    name: str,
    rel_path: str,
    description: str | None = None,
    is_system: int = 0,
) -> int:
    now = _now()
    with _lock:
        cur = _db().execute(
            """INSERT INTO taxonomy_node
               (parent_id, name, rel_path, description, is_system, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (parent_id, name, rel_path, description, is_system, now),
        )
        _db().commit()
        return cur.lastrowid


def get_taxonomy_node(node_id: int) -> dict | None:
    row = _db().execute(
        "SELECT * FROM taxonomy_node WHERE id = ?", (node_id,)
    ).fetchone()
    return dict(row) if row else None


def get_taxonomy_node_by_rel_path(rel_path: str) -> dict | None:
    row = _db().execute(
        "SELECT * FROM taxonomy_node WHERE rel_path = ?", (rel_path,)
    ).fetchone()
    return dict(row) if row else None


def get_taxonomy_children(parent_id: int | None) -> list[dict]:
    if parent_id is None:
        rows = _db().execute(
            "SELECT * FROM taxonomy_node WHERE parent_id IS NULL ORDER BY name"
        ).fetchall()
    else:
        rows = _db().execute(
            "SELECT * FROM taxonomy_node WHERE parent_id = ? ORDER BY name",
            (parent_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_taxonomy_nodes() -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM taxonomy_node ORDER BY rel_path"
    ).fetchall()
    return [dict(r) for r in rows]


def get_matchable_taxonomy_nodes() -> list[dict]:
    """All nodes excluding is_system=1 (unsorted). Used by embedding matching."""
    rows = _db().execute(
        "SELECT * FROM taxonomy_node WHERE is_system = 0 ORDER BY rel_path"
    ).fetchall()
    return [dict(r) for r in rows]


def update_taxonomy_node_embedding(node_id: int, embedding: bytes) -> None:
    with _lock:
        _db().execute(
            "UPDATE taxonomy_node SET embedding = ?, embedding_updated_at = ? WHERE id = ?",
            (embedding, _now(), node_id),
        )
        _db().commit()


def update_taxonomy_node_description(node_id: int, description: str) -> None:
    with _lock:
        _db().execute(
            "UPDATE taxonomy_node SET description = ? WHERE id = ?",
            (description, node_id),
        )
        _db().commit()


# ---------------------------------------------------------------------------
# Known Source
# ---------------------------------------------------------------------------

def get_known_source_by_path(source_path: str) -> dict | None:
    row = _db().execute(
        "SELECT * FROM known_source WHERE source_path = ?", (source_path,)
    ).fetchone()
    return dict(row) if row else None


def get_known_source_by_hash(sha256: str) -> dict | None:
    row = _db().execute(
        "SELECT * FROM known_source WHERE sha256 = ?", (sha256,)
    ).fetchone()
    return dict(row) if row else None


def create_known_source(
    source_path: str, sha256: str, duplicates_file_id: int
) -> int:
    with _lock:
        cur = _db().execute(
            """INSERT OR IGNORE INTO known_source
               (source_path, sha256, duplicates_file_id, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (source_path, sha256, duplicates_file_id, _now()),
        )
        _db().commit()
        return cur.lastrowid


def delete_known_source_by_file_id(file_id: int) -> None:
    with _lock:
        _db().execute(
            "DELETE FROM known_source WHERE duplicates_file_id = ?", (file_id,)
        )
        _db().commit()


# ---------------------------------------------------------------------------
# File Embeddings
# ---------------------------------------------------------------------------

def upsert_file_embedding(file_id: int, embedding: bytes) -> None:
    with _lock:
        _db().execute(
            """INSERT INTO file_embedding (file_id, embedding) VALUES (?, ?)
               ON CONFLICT(file_id) DO UPDATE SET embedding = excluded.embedding""",
            (file_id, embedding),
        )
        _db().commit()


def get_file_embedding(file_id: int) -> bytes | None:
    row = _db().execute(
        "SELECT embedding FROM file_embedding WHERE file_id = ?", (file_id,)
    ).fetchone()
    return row["embedding"] if row else None


def get_file_embeddings_for_node(node_id: int) -> list[tuple[int, bytes]]:
    """(file_id, embedding) for confirmed files in a node. Used to update folder embeddings."""
    rows = _db().execute(
        """SELECT fe.file_id, fe.embedding FROM file_embedding fe
           JOIN file f ON f.id = fe.file_id
           WHERE f.proposed_node_id = ? AND f.state IN ('moved', 'copied')""",
        (node_id,),
    ).fetchall()
    return [(r["file_id"], r["embedding"]) for r in rows]


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

def get_batch(batch_id: int) -> dict | None:
    row = _db().execute("SELECT * FROM batch WHERE id = ?", (batch_id,)).fetchone()
    return dict(row) if row else None


def get_counts_by_state() -> dict[str, int]:
    states = ["held", "skipped", "error", "budget_paused", "moved", "copied", "queued", "classifying"]
    result = {}
    for s in states:
        row = _db().execute("SELECT COUNT(*) as n FROM file WHERE state = ?", (s,)).fetchone()
        result[s] = int(row["n"]) if row else 0
    return result


def get_recent_batches(limit: int = 10) -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM batch WHERE undone = 0 ORDER BY confirmed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_action_log_for_batch(batch_id: int) -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM action_log WHERE batch_id = ? ORDER BY id",
        (batch_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Atomic transactions
# ---------------------------------------------------------------------------

def execute_batch_confirm(file_ops: list[dict]) -> int:
    """
    Atomically create batch, log actions, and transition file states.

    Each op dict: {
        file_id: int, action: str,
        from_path: str | None, to_path: str | None,
        new_state: str, node_id: int | None
    }
    Returns batch_id.
    """
    with _lock:
        _db().execute("BEGIN IMMEDIATE")
        try:
            now = _now()
            batch_cur = _db().execute(
                "INSERT INTO batch (confirmed_at, file_count, undone) VALUES (?, ?, 0)",
                (now, len(file_ops)),
            )
            batch_id = batch_cur.lastrowid
            for op in file_ops:
                fid = op["file_id"]
                row = _db().execute(
                    "SELECT state FROM file WHERE id = ?", (fid,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"File {fid} not found")
                current = row["state"]
                new_state = op["new_state"]
                if new_state not in VALID_TRANSITIONS.get(current, set()):
                    raise ValueError(
                        f"Invalid transition {current!r} → {new_state!r} for file {fid}"
                    )
                _db().execute(
                    """INSERT INTO action_log
                       (batch_id, file_id, action, from_path, to_path, executed_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (batch_id, fid, op["action"], op.get("from_path"), op.get("to_path"), now),
                )
                _db().execute(
                    """UPDATE file SET
                       state = ?,
                       current_rel_path = COALESCE(?, current_rel_path),
                       proposed_node_id = COALESCE(?, proposed_node_id),
                       updated_at = ?
                       WHERE id = ?""",
                    (new_state, op.get("to_path"), op.get("node_id"), now, fid),
                )
            _db().commit()
            return batch_id
        except Exception:
            _db().rollback()
            raise


def execute_batch_undo(batch_id: int, file_ops: list[dict]) -> None:
    """
    Atomically reverse a batch: log undo actions, reset file states to held, mark batch undone.

    Each op dict: {
        file_id: int, action: str ('undo_move'|'undo_copy'),
        from_path: str | None, to_path: str | None
    }
    """
    with _lock:
        _db().execute("BEGIN IMMEDIATE")
        try:
            now = _now()
            for op in reversed(file_ops):
                fid = op["file_id"]
                _db().execute(
                    """INSERT INTO action_log
                       (batch_id, file_id, action, from_path, to_path, executed_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (batch_id, fid, op["action"], op.get("from_path"), op.get("to_path"), now),
                )
                _db().execute(
                    "UPDATE file SET state = 'held', current_rel_path = NULL, updated_at = ? WHERE id = ?",
                    (now, fid),
                )
            _db().execute(
                "UPDATE batch SET undone = 1, undone_at = ? WHERE id = ?",
                (now, batch_id),
            )
            _db().commit()
        except Exception:
            _db().rollback()
            raise


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------

def create_correction(
    file_id: int,
    proposed_node_id: int | None,
    actual_node_id: int,
    tier: int | None = None,
    confidence: float | None = None,
) -> int:
    with _lock:
        cur = _db().execute(
            """INSERT INTO correction
               (file_id, proposed_node_id, actual_node_id, tier, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_id, proposed_node_id, actual_node_id, tier, confidence, _now()),
        )
        _db().commit()
        return cur.lastrowid


def get_corrections_for_node(actual_node_id: int, limit: int = 100) -> list[dict]:
    rows = _db().execute(
        """SELECT * FROM correction WHERE actual_node_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (actual_node_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_correction_patterns(min_count: int = 3) -> list[dict]:
    """Extension+destination combos with enough corrections to propose a rule."""
    rows = _db().execute(
        """SELECT f.ext, c.actual_node_id, COUNT(*) as cnt
           FROM correction c JOIN file f ON f.id = c.file_id
           WHERE f.ext IS NOT NULL
           GROUP BY f.ext, c.actual_node_id
           HAVING cnt >= ?
           ORDER BY cnt DESC""",
        (min_count,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def create_suggestion(kind: str, payload: str, evidence_count: int) -> int:
    with _lock:
        cur = _db().execute(
            """INSERT INTO suggestion (kind, payload, evidence_count, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (kind, payload, evidence_count, _now()),
        )
        _db().commit()
        return cur.lastrowid


def get_pending_suggestions() -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM suggestion WHERE status = 'pending' ORDER BY evidence_count DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def update_suggestion_status(
    suggestion_id: int, status: str, resolved: bool = False
) -> None:
    with _lock:
        _db().execute(
            "UPDATE suggestion SET status = ?, resolved_at = ? WHERE id = ?",
            (status, _now() if resolved else None, suggestion_id),
        )
        _db().commit()


def find_suggestion(kind: str, payload_fragment: str) -> dict | None:
    """Find an existing non-accepted suggestion by kind + payload substring."""
    row = _db().execute(
        "SELECT * FROM suggestion WHERE kind = ? AND payload LIKE ? AND status != 'accepted'",
        (kind, f"%{payload_fragment}%"),
    ).fetchone()
    return dict(row) if row else None


def reopen_suggestion(suggestion_id: int, evidence_count: int) -> None:
    """Un-dismiss a suggestion and refresh its evidence count."""
    with _lock:
        _db().execute(
            "UPDATE suggestion SET status = 'pending', evidence_count = ?, resolved_at = NULL WHERE id = ?",
            (evidence_count, suggestion_id),
        )
        _db().commit()


# ---------------------------------------------------------------------------
# API Usage
# ---------------------------------------------------------------------------

def record_api_usage(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float,
    file_id: int | None = None,
) -> None:
    with _lock:
        _db().execute(
            """INSERT INTO api_usage
               (ts, model, input_tokens, output_tokens, cost_usd, file_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_now(), model, input_tokens, output_tokens, cost_usd, file_id),
        )
        _db().commit()


def get_total_api_cost() -> float:
    row = _db().execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) as total FROM api_usage"
    ).fetchone()
    return row["total"]
