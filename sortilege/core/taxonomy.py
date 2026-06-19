"""
Taxonomy node CRUD. Manages the folder tree on top of registry.
Physical folders on the output drive are created alongside registry rows.
"""
from pathlib import Path

from sortilege.core import registry

SEED_FOLDERS: list[dict] = [
    {"name": "financial", "description": "Taxes, bank statements, insurance, receipts, and financial records."},
    {"name": "career",    "description": "Resumes, certifications, job applications, and professional development materials."},
    {"name": "health",    "description": "Medical records, lab results, prescriptions, and health-related documents."},
    {"name": "documents", "description": "Identity documents, legal papers, manuals, and official correspondence."},
    {"name": "photos",    "description": "Personal photographs from cameras, family events, and travel."},
    {"name": "media",     "description": "Downloaded images, wallpapers, videos, audio, and consumed media files."},
    {"name": "code",      "description": "Programming projects, scripts, snippets, and configuration files."},
    {"name": "creative",  "description": "Writing, worldbuilding notes, campaign materials, and creative projects."},
]

UNSORTED_NAME = "unsorted"
UNSORTED_DESCRIPTION = "Fallback for files that could not be confidently classified. Not a permanent home."


def _make_rel_path(parent_rel_path: str | None, name: str) -> str:
    if parent_rel_path is None:
        return name
    return f"{parent_rel_path}\\{name}"


def create_node(
    parent_id: int | None,
    name: str,
    output_root: Path,
    description: str | None = None,
    is_system: int = 0,
) -> int:
    parent_rel = None
    if parent_id is not None:
        parent = registry.get_taxonomy_node(parent_id)
        if parent is None:
            raise ValueError(f"Parent node {parent_id} not found")
        parent_rel = parent["rel_path"]

    rel_path = _make_rel_path(parent_rel, name)
    node_id = registry.create_taxonomy_node(
        parent_id=parent_id,
        name=name,
        rel_path=rel_path,
        description=description,
        is_system=is_system,
    )

    folder = output_root / rel_path
    folder.mkdir(parents=True, exist_ok=True)

    return node_id


def get_children(node_id: int | None) -> list[dict]:
    return registry.get_taxonomy_children(node_id)


def get_all_nodes() -> list[dict]:
    return registry.get_all_taxonomy_nodes()


def get_node_by_rel_path(rel_path: str) -> dict | None:
    return registry.get_taxonomy_node_by_rel_path(rel_path)


def get_subtree(node_id: int) -> dict:
    """Return a node and all its descendants as a nested dict. Used for LLM prompt context."""
    node = registry.get_taxonomy_node(node_id)
    if node is None:
        raise ValueError(f"Node {node_id} not found")
    children = registry.get_taxonomy_children(node_id)
    return {
        "id": node["id"],
        "name": node["name"],
        "rel_path": node["rel_path"],
        "description": node["description"],
        "children": [get_subtree(c["id"]) for c in children],
    }


def get_full_tree() -> list[dict]:
    """Full taxonomy as a nested list of root nodes with their subtrees."""
    roots = registry.get_taxonomy_children(None)
    return [get_subtree(r["id"]) for r in roots]


def seed_taxonomy(output_root: Path, folder_overrides: list[dict] | None = None) -> None:
    """
    Create the top-level folders on first run.
    folder_overrides: list of {"name": str, "description": str} dicts from the setup wizard.
    If None, uses the default SEED_FOLDERS.
    """
    folders = folder_overrides if folder_overrides is not None else SEED_FOLDERS

    for folder in folders:
        existing = registry.get_taxonomy_node_by_rel_path(folder["name"])
        if existing is None:
            create_node(
                parent_id=None,
                name=folder["name"],
                output_root=output_root,
                description=folder["description"],
                is_system=0,
            )

    existing_unsorted = registry.get_taxonomy_node_by_rel_path(UNSORTED_NAME)
    if existing_unsorted is None:
        create_node(
            parent_id=None,
            name=UNSORTED_NAME,
            output_root=output_root,
            description=UNSORTED_DESCRIPTION,
            is_system=1,
        )


def get_unsorted_node() -> dict:
    node = registry.get_taxonomy_node_by_rel_path(UNSORTED_NAME)
    if node is None:
        raise RuntimeError("unsorted node not found — was seed_taxonomy run?")
    return node
