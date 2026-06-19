"""Embedding updates and correction recording triggered by user moves in the review UI."""

import logging

from sortilege.core import embeddings, registry
from sortilege.core.taxonomy import get_unsorted_node

logger = logging.getLogger(__name__)


def on_move(file_id: int, proposed_node_id: int | None, actual_node_id: int) -> None:
    """Called after a file is moved to record corrections and refresh embeddings.

    actual_node_id == unsorted node id re-queues the file for reclassification.
    """
    file = registry.get_file(file_id)
    if file is None:
        logger.warning("on_move called for unknown file_id=%d", file_id)
        return

    if proposed_node_id != actual_node_id:
        registry.create_correction(
            file_id=file_id,
            proposed_node_id=proposed_node_id,
            actual_node_id=actual_node_id,
            tier=file.get("tier"),
            confidence=file.get("confidence"),
        )

    embeddings.update_folder_embedding(actual_node_id)

    if proposed_node_id is not None and proposed_node_id != actual_node_id:
        embeddings.update_folder_embedding(proposed_node_id)

    unsorted_id = get_unsorted_node()["id"]
    if actual_node_id == unsorted_id:
        registry.update_file_state(file_id, "queued")
        logger.debug("File %d re-queued after move to unsorted", file_id)
