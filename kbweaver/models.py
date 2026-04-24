"""Domain models for KBWeaver wiki nodes.

Defines the WikiNode schema (TECH_SPEC §1) and serialization between
YAML-frontmatter Markdown files and in-memory dataclasses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

ALLOWED_RELATION_TYPES = frozenset({"supports", "contradicts", "derived_from", "relates_to"})


@dataclass
class Relation:
    """A typed edge from one wiki node to another."""

    type: str
    target: str  # wiki-link target, e.g. "[[Another Concept]]"

    def __post_init__(self) -> None:
        if self.type not in ALLOWED_RELATION_TYPES:
            raise ValueError(
                f"Invalid relation type {self.type!r}. "
                f"Allowed: {', '.join(sorted(ALLOWED_RELATION_TYPES))}"
            )


@dataclass
class WikiNode:
    """A single concept in the knowledge base.

    Maps 1:1 to a ``.md`` file in ``wiki/``.
    """

    id: str
    title: str
    body: str = ""
    aliases: list[str] = field(default_factory=list)
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sources: list[str] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # ---- helpers ----------------------------------------------------------

    @property
    def filename(self) -> str:
        """Derive the expected filename from the node id."""
        return f"{self.id}.md"

    def touch(self) -> None:
        """Update the ``updated`` timestamp to *now*."""
        self.updated = datetime.now(timezone.utc)

    def add_relation(self, rel_type: str, target: str) -> None:
        """Add a relation if it doesn't already exist."""
        for r in self.relations:
            if r.type == rel_type and r.target == target:
                return
        self.relations.append(Relation(type=rel_type, target=target))

    def add_source(self, source: str) -> None:
        """Add a source wiki-link if not already present."""
        if source not in self.sources:
            self.sources.append(source)


# ---------------------------------------------------------------------------
# Slug utilities
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_from_title(title: str) -> str:
    """Convert a human-readable title to a filesystem-safe slug.

    >>> slug_from_title("Transformer Architecture")
    'transformer-architecture'
    """
    return _SLUG_RE.sub("-", title.lower()).strip("-")


def title_from_wikilink(link: str) -> str:
    """Extract the title string from a ``[[wiki-link]]``.

    >>> title_from_wikilink("[[Transformer Architecture]]")
    'Transformer Architecture'
    """
    return link.strip("[]")


# ---------------------------------------------------------------------------
# Serialization — WikiNode ↔ Markdown with YAML frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _datetime_representer(dumper: yaml.Dumper, data: datetime) -> yaml.Node:
    """Serialize datetime as ISO-8601 string for YAML."""
    return dumper.represent_scalar("tag:yaml.org,2002:str", data.isoformat(timespec="seconds"))


yaml.add_representer(datetime, _datetime_representer)


def serialize_node(node: WikiNode) -> str:
    """Serialize a WikiNode to a Markdown string with YAML frontmatter.

    Output format matches TECH_SPEC §1.1 and §1.2.
    """
    frontmatter: dict[str, Any] = {
        "id": node.id,
        "title": node.title,
    }
    if node.aliases:
        frontmatter["aliases"] = node.aliases
    frontmatter["created"] = node.created
    frontmatter["updated"] = node.updated
    if node.sources:
        frontmatter["sources"] = node.sources
    if node.relations:
        frontmatter["relations"] = [
            {"type": r.type, "target": r.target} for r in node.relations
        ]
    if node.tags:
        frontmatter["tags"] = node.tags

    yaml_str = yaml.dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )

    # Build body per §1.2
    body_parts: list[str] = [f"# {node.title}", ""]
    if node.body:
        body_parts.append(node.body)
        body_parts.append("")

    # Related Concepts section
    related = [r for r in node.relations if r.target]
    if related:
        body_parts.append("## Related Concepts")
        body_parts.append("")
        for r in related:
            body_parts.append(f"- {r.target} — {r.type}")
        body_parts.append("")

    # Sources section
    if node.sources:
        body_parts.append("## Sources")
        body_parts.append("")
        for s in node.sources:
            body_parts.append(f"- {s}")
        body_parts.append("")

    body_text = "\n".join(body_parts)
    return f"---\n{yaml_str}---\n{body_text}"


def deserialize_node(text: str) -> WikiNode:
    """Parse a Markdown string with YAML frontmatter into a WikiNode.

    Inverse of :func:`serialize_node`.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("No YAML frontmatter found in node text.")

    fm = yaml.safe_load(match.group(1))
    body_raw = text[match.end():]

    # Strip the auto-generated heading and sections — keep only user/agent prose
    body = _extract_body_prose(body_raw, fm.get("title", ""))

    relations: list[Relation] = []
    for r in fm.get("relations", []) or []:
        relations.append(Relation(type=r["type"], target=r["target"]))

    created = fm.get("created", datetime.now(timezone.utc))
    updated = fm.get("updated", datetime.now(timezone.utc))
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)

    return WikiNode(
        id=fm["id"],
        title=fm["title"],
        body=body,
        aliases=fm.get("aliases", []) or [],
        created=created,
        updated=updated,
        sources=fm.get("sources", []) or [],
        relations=relations,
        tags=fm.get("tags", []) or [],
    )


def _extract_body_prose(body_raw: str, title: str) -> str:
    """Extract the core prose body, stripping generated heading/sections.

    The body text lives between the ``# Title`` heading and the first
    ``## Related Concepts`` or ``## Sources`` section heading.
    """
    lines = body_raw.split("\n")
    prose_lines: list[str] = []
    in_prose = False
    for line in lines:
        stripped = line.strip()
        # Skip the top-level heading
        if stripped == f"# {title}" and not in_prose:
            in_prose = True
            continue
        # Stop at generated sections
        if stripped in ("## Related Concepts", "## Sources"):
            break
        if in_prose:
            prose_lines.append(line)
    # Trim leading/trailing blank lines
    text = "\n".join(prose_lines).strip()
    return text
