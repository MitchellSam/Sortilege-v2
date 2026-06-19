"""
Nomic Embed wrapper. The model is loaded once at server start and kept in memory.
All embeddings are float32[768]. Stored as raw bytes (numpy tobytes/frombuffer).
"""
import numpy as np

from sortilege.core import registry
from sortilege.core.extractor import extract

_model = None
_MODEL_NAME = "nomic-ai/nomic-embed-text-v1"
_DIM = 768


def load_model() -> None:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME, trust_remote_code=True)


def _get_model():
    if _model is None:
        raise RuntimeError("Embedding model not loaded — call load_model() at startup")
    return _model


def _to_bytes(arr: np.ndarray) -> bytes:
    return arr.astype(np.float32).tobytes()


def _from_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def embed_text(text: str) -> np.ndarray:
    """Embed a string. Returns float32[768]."""
    if not text or not text.strip():
        return np.zeros(_DIM, dtype=np.float32)
    # Nomic embed requires a task prefix for asymmetric use
    prefixed = f"search_document: {text}"
    vec = _get_model().encode(prefixed, normalize_embeddings=True)
    return vec.astype(np.float32)


def embed_texts(texts: list[str]) -> list[np.ndarray]:
    """Batch embed. More efficient than repeated embed_text calls."""
    if not texts:
        return []
    prefixed = [f"search_document: {t}" if t.strip() else "" for t in texts]
    results = _get_model().encode(prefixed, normalize_embeddings=True, batch_size=32)
    out = []
    for i, vec in enumerate(results):
        if not texts[i].strip():
            out.append(np.zeros(_DIM, dtype=np.float32))
        else:
            out.append(vec.astype(np.float32))
    return out


def compare(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity. Both vectors assumed unit-normalized."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def embed_file(file_id: int) -> np.ndarray | None:
    """
    Extract text from a file, embed it, store in file_embedding, return the vector.
    Returns None if extraction yields no usable text.
    """
    file = registry.get_file(file_id)
    if file is None:
        return None

    result = extract(file["source_path"])
    if result.error or not result.text.strip():
        return None

    vec = embed_text(result.text)
    registry.upsert_file_embedding(file_id, _to_bytes(vec))

    if result.snippet and not file.get("extracted_snippet"):
        registry.update_file_proposal(
            file_id=file_id,
            proposed_node_id=file["proposed_node_id"],
            planned_op=file["planned_op"] or "move",
            tier=file["tier"] or 0,
            confidence=file["confidence"],
            reasoning=file["reasoning"],
            extracted_snippet=result.snippet,
        )

    return vec


def update_folder_embedding(node_id: int) -> None:
    """
    Recompute a folder's embedding from: description, child names, and
    representative file embeddings (confirmed files). Positive/negative
    correction weighting comes from the correction log.
    """
    node = registry.get_taxonomy_node(node_id)
    if node is None:
        return

    parts: list[np.ndarray] = []

    # Description + name seed
    seed_text = node["name"]
    if node.get("description"):
        seed_text += ". " + node["description"]
    seed_vec = embed_text(seed_text)
    parts.append(seed_vec)

    # Child folder names
    children = registry.get_taxonomy_children(node_id)
    if children:
        child_text = " ".join(c["name"] for c in children)
        parts.append(embed_text(child_text))

    # Confirmed file embeddings (up to 50 most recent)
    file_embeddings = registry.get_file_embeddings_for_node(node_id)
    for _, emb_bytes in file_embeddings[:50]:
        parts.append(_from_bytes(emb_bytes))

    # Correction weighting: files correctly routed here (positive)
    corrections = registry.get_corrections_for_node(node_id, limit=20)
    for corr in corrections:
        emb_bytes = registry.get_file_embedding(corr["file_id"])
        if emb_bytes:
            parts.append(_from_bytes(emb_bytes))

    if not parts:
        return

    stacked = np.stack(parts)
    mean_vec = stacked.mean(axis=0)
    norm = np.linalg.norm(mean_vec)
    if norm > 0:
        mean_vec /= norm

    registry.update_taxonomy_node_embedding(node_id, _to_bytes(mean_vec))


def find_best_child(
    parent_node_id: int | None,
    file_embedding: np.ndarray,
    floor: float,
) -> tuple[int, float] | None:
    """
    Among the immediate children of parent_node_id (excluding system nodes),
    return (node_id, score) of the best match that clears `floor`.
    Returns None if no child clears the floor.
    """
    children = registry.get_taxonomy_children(parent_node_id)
    best_id: int | None = None
    best_score: float = -1.0

    for child in children:
        if child["is_system"]:
            continue
        emb_bytes = child.get("embedding")
        if not emb_bytes:
            continue
        folder_vec = _from_bytes(emb_bytes)
        score = compare(file_embedding, folder_vec)
        if score > best_score:
            best_score = score
            best_id = child["id"]

    if best_id is not None and best_score >= floor:
        return (best_id, best_score)
    return None


def recursive_descent(
    file_embedding: np.ndarray,
    floor: float,
    start_node_id: int | None = None,
) -> tuple[int | None, float]:
    """
    Descend through the taxonomy starting at start_node_id's children,
    always taking the best-matching child that clears the floor.
    Returns (deepest_node_id, score) where deepest_node_id is the last
    node that cleared the floor. Partial-depth placement is correct behavior.

    Returns (None, 0.0) if no top-level child clears the floor.
    """
    current_id = start_node_id
    current_score = 0.0

    # First step: find a top-level (or start-level) match
    result = find_best_child(current_id, file_embedding, floor)
    if result is None:
        return (None, 0.0)

    current_id, current_score = result

    # Descend as deep as possible
    while True:
        deeper = find_best_child(current_id, file_embedding, floor)
        if deeper is None:
            break
        current_id, current_score = deeper

    return (current_id, current_score)
