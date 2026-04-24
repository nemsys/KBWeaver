"""Wiki filesystem operations.

Handles reading and writing WikiNode .md files in the wiki/ directory.
"""

from __future__ import annotations

from pathlib import Path

from kbweaver.models import WikiNode, deserialize_node, serialize_node


def read_node(path: Path) -> WikiNode:
    """Read a wiki node from a .md file.

    Parameters
    ----------
    path:
        Absolute or relative path to the ``.md`` file.

    Returns
    -------
    WikiNode
        Parsed node with all fields populated.
    """
    text = path.read_text(encoding="utf-8")
    return deserialize_node(text)


def write_node(node: WikiNode, wiki_dir: Path) -> Path:
    """Write a WikiNode to a .md file in *wiki_dir*.

    Creates the directory if it does not exist.  Always overwrites the
    target file — the caller is responsible for updating timestamps
    before calling this function.

    Returns
    -------
    Path
        The path of the written file.
    """
    wiki_dir.mkdir(parents=True, exist_ok=True)
    target = wiki_dir / node.filename
    text = serialize_node(node)
    target.write_text(text, encoding="utf-8")
    return target


def list_nodes(wiki_dir: Path) -> list[Path]:
    """List all .md node files in *wiki_dir*.

    Returns a sorted list of paths (non-recursive — nodes are flat).
    """
    if not wiki_dir.exists():
        return []
    return sorted(wiki_dir.glob("*.md"))


def node_exists(node_id: str, wiki_dir: Path) -> bool:
    """Check whether a node with the given id exists on disk."""
    return (wiki_dir / f"{node_id}.md").exists()
