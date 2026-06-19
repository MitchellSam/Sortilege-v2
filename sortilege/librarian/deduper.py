"""Hash-based and perceptual-hash duplicate detection."""

import hashlib
import logging
from pathlib import Path

import numpy as np

from sortilege.core import registry
from sortilege.core.extractor import long_path

logger = logging.getLogger(__name__)

_IMAGE_EXTS = frozenset({
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "heic", "heif",
})

_CHUNK = 1 << 20  # 1 MB


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(long_path(filepath), "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def compute_phash(filepath: str) -> int | None:
    """Returns 64-bit pHash as int, or None for non-images or on error."""
    ext = Path(filepath).suffix.lstrip(".").lower()
    if ext not in _IMAGE_EXTS:
        return None
    try:
        import imagehash
        from PIL import Image

        img = Image.open(long_path(filepath))
        return int(str(imagehash.phash(img)), 16)
    except Exception:
        logger.debug("phash failed for %s", filepath, exc_info=True)
        return None


def check_known_source(source_path: str) -> int | None:
    """Pre-hash path lookup — fast shortcut for already-seen sources."""
    row = registry.get_known_source_by_path(source_path)
    return row["duplicates_file_id"] if row else None


def check_dupe_by_hash(sha256: str) -> int | None:
    row = registry.get_file_by_sha256(sha256)
    return row["id"] if row else None


def check_dupe_by_phash(phash: int, threshold: int = 10) -> int | None:
    """Hamming distance search over all stored pHashes via numpy popcount.

    threshold=10 is ~15% bit-distance; tighten if false positives appear.
    """
    phashes = registry.get_all_phashes()
    if not phashes:
        return None
    ids = np.array([p[0] for p in phashes], dtype=np.int64)
    vals = np.array([p[1] for p in phashes], dtype=np.uint64)
    xored = vals ^ np.uint64(phash)
    # each uint64 is 8 bytes; unpackbits counts set bits per element
    counts = np.unpackbits(xored.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)
    min_idx = int(np.argmin(counts))
    if counts[min_idx] <= threshold:
        return int(ids[min_idx])
    return None


def record_known_source(source_path: str, sha256: str, canonical_file_id: int) -> None:
    """Record a cross-drive copy so the source can be skipped on future drops."""
    registry.create_known_source(source_path, sha256, canonical_file_id)


def remove_known_source(file_id: int) -> None:
    """Remove known-source record when an undo_copy operation reverses a copy."""
    registry.delete_known_source_by_file_id(file_id)
