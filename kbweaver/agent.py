"""Agent — Ontology Builder.

Implements the 6-step entity resolution algorithm (TECH_SPEC §4.2):
EXTRACT → LOOKUP → CONFIRM → CREATE/UPDATE → LINK → SYNC.

The Agent never deletes nodes (§4.3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kbweaver.database import Database
from kbweaver.llm.base import LLMProvider
from kbweaver.models import WikiNode, slug_from_title
from kbweaver.prompts import (
    CONFIRM_MATCH_SYSTEM,
    CONFIRM_MATCH_USER,
    EXTRACT_CONCEPTS_SYSTEM,
    EXTRACT_CONCEPTS_USER,
    GENERATE_NOTE_SYSTEM,
    GENERATE_NOTE_USER,
    IDENTIFY_RELATIONS_SYSTEM,
    IDENTIFY_RELATIONS_USER,
    UPDATE_NOTE_SYSTEM,
    UPDATE_NOTE_USER,
)
from kbweaver.wiki import node_exists, read_node, write_node

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Summary of what the agent did for a single chunk."""

    nodes_created: int = 0
    nodes_updated: int = 0
    edges_added: int = 0
    concepts: list[str] = field(default_factory=list)


class EntityResolver:
    """Resolves concepts from text chunks against the existing wiki.

    Uses the entity resolution LLM (typically a smaller/faster model)
    for all steps except note body generation, which benefits from
    the same model's prose capabilities.
    """

    def __init__(
        self,
        llm: LLMProvider,
        db: Database,
        wiki_dir: Path,
        source_ref: str = "",
    ) -> None:
        self._llm = llm
        self._db = db
        self._wiki_dir = wiki_dir
        self._source_ref = source_ref  # e.g. "[[archive/source.pdf]]"

    def process_chunk(self, chunk: str) -> AgentResult:
        """Run the full 6-step entity resolution pipeline on a text chunk.

        Returns an AgentResult summarizing what was created/updated.
        """
        result = AgentResult()

        # Step 1: EXTRACT
        concepts = self._extract_concepts(chunk)
        if not concepts:
            logger.debug("No concepts extracted from chunk")
            return result
        result.concepts = concepts

        # Steps 2-4: LOOKUP → CONFIRM → CREATE/UPDATE
        resolved_nodes: list[WikiNode] = []
        for concept_name in concepts:
            node = self._resolve_concept(concept_name, chunk, result)
            if node:
                resolved_nodes.append(node)

        # Step 5: LINK
        if len(resolved_nodes) >= 2:
            edges = self._identify_relations(resolved_nodes, chunk)
            for src_title, dst_title, rel_type in edges:
                src_id = slug_from_title(src_title)
                dst_id = slug_from_title(dst_title)
                self._add_relation(src_id, dst_id, rel_type, result)

        # Step 6: SYNC — already done per-node in _resolve_concept
        return result

    # ------------------------------------------------------------------
    # Step 1: EXTRACT
    # ------------------------------------------------------------------

    def _extract_concepts(self, chunk: str) -> list[str]:
        """Prompt the LLM to extract concept names from a chunk."""
        prompt = EXTRACT_CONCEPTS_USER.format(chunk=chunk)
        response = self._llm.complete(EXTRACT_CONCEPTS_SYSTEM, prompt)

        try:
            concepts = json.loads(response.strip())
            if isinstance(concepts, list):
                return [str(c).strip() for c in concepts if c]
        except (json.JSONDecodeError, TypeError):
            # Try to extract JSON array from response
            import re

            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                try:
                    concepts = json.loads(match.group())
                    return [str(c).strip() for c in concepts if c]
                except json.JSONDecodeError:
                    pass
            logger.warning("Failed to parse concept list from LLM response: %s", response[:200])
        return []

    # ------------------------------------------------------------------
    # Steps 2-4: LOOKUP → CONFIRM → CREATE/UPDATE
    # ------------------------------------------------------------------

    def _resolve_concept(
        self, concept_name: str, chunk: str, result: AgentResult
    ) -> WikiNode | None:
        """Resolve a single concept: find existing match or create new node."""
        concept_id = slug_from_title(concept_name)

        # Step 2: LOOKUP — FTS5 search for existing matches
        fts_results = self._db.search_fts(concept_name, top_k=5)

        # Step 3: CONFIRM — check each candidate
        matched_node: WikiNode | None = None
        for fts_hit in fts_results:
            if self._confirm_match(concept_name, fts_hit.title, fts_hit.aliases):
                # Load the existing node
                node_path = self._wiki_dir / f"{fts_hit.id}.md"
                if node_path.exists():
                    matched_node = read_node(node_path)
                break

        # Step 4: CREATE or UPDATE
        if matched_node:
            node = self._update_node(matched_node, concept_name, chunk)
            result.nodes_updated += 1
        else:
            node = self._create_node(concept_name, concept_id, chunk)
            result.nodes_created += 1

        # SYNC — update index immediately
        write_node(node, self._wiki_dir)
        self._db.sync_node(node, self._wiki_dir)

        return node

    def _confirm_match(self, candidate: str, existing_title: str, aliases: str) -> bool:
        """Ask the LLM whether candidate matches an existing concept."""
        # Exact match shortcut
        if candidate.lower() == existing_title.lower():
            return True
        if candidate.lower() in [a.lower() for a in aliases.split()]:
            return True

        prompt = CONFIRM_MATCH_USER.format(
            candidate=candidate,
            existing_title=existing_title,
            aliases=aliases or "(none)",
        )
        response = self._llm.complete(CONFIRM_MATCH_SYSTEM, prompt)
        return response.strip().upper().startswith("YES")

    def _create_node(self, concept_name: str, concept_id: str, chunk: str) -> WikiNode:
        """Create a new wiki node for a concept."""
        prompt = GENERATE_NOTE_USER.format(concept=concept_name, chunk=chunk)
        body = self._llm.complete(GENERATE_NOTE_SYSTEM, prompt).strip()

        now = datetime.now(timezone.utc)
        node = WikiNode(
            id=concept_id,
            title=concept_name,
            body=body,
            created=now,
            updated=now,
        )
        if self._source_ref:
            node.add_source(self._source_ref)

        logger.info("Created node: %s (%s)", concept_name, concept_id)
        return node

    def _update_node(self, node: WikiNode, concept_name: str, chunk: str) -> WikiNode:
        """Update an existing node with new information from a chunk."""
        prompt = UPDATE_NOTE_USER.format(
            concept=concept_name,
            existing_body=node.body,
            chunk=chunk,
        )
        updated_body = self._llm.complete(UPDATE_NOTE_SYSTEM, prompt).strip()

        node.body = updated_body
        node.touch()
        if self._source_ref:
            node.add_source(self._source_ref)

        logger.info("Updated node: %s (%s)", node.title, node.id)
        return node

    # ------------------------------------------------------------------
    # Step 5: LINK
    # ------------------------------------------------------------------

    def _identify_relations(
        self, nodes: list[WikiNode], chunk: str
    ) -> list[tuple[str, str, str]]:
        """Ask the LLM to identify relationships between concepts found in a chunk."""
        concept_names = [n.title for n in nodes]
        prompt = IDENTIFY_RELATIONS_USER.format(
            concepts=json.dumps(concept_names),
            chunk=chunk,
        )
        response = self._llm.complete(IDENTIFY_RELATIONS_SYSTEM, prompt)

        try:
            relations = json.loads(response.strip())
            if not isinstance(relations, list):
                return []
        except (json.JSONDecodeError, TypeError):
            import re

            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                try:
                    relations = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                logger.warning("Failed to parse relations from LLM: %s", response[:200])
                return []

        result: list[tuple[str, str, str]] = []
        valid_types = {"supports", "contradicts", "derived_from", "relates_to"}
        for rel in relations:
            if isinstance(rel, dict):
                src = rel.get("source", "")
                dst = rel.get("target", "")
                rtype = rel.get("type", "relates_to")
                if src and dst and rtype in valid_types:
                    result.append((src, dst, rtype))
        return result

    def _add_relation(
        self, src_id: str, dst_id: str, rel_type: str, result: AgentResult
    ) -> None:
        """Add a bidirectional relation between two nodes."""
        src_path = self._wiki_dir / f"{src_id}.md"
        dst_path = self._wiki_dir / f"{dst_id}.md"

        if src_path.exists():
            src_node = read_node(src_path)
            dst_title = self._get_node_title(dst_id)
            src_node.add_relation(rel_type, f"[[{dst_title}]]")
            src_node.touch()
            write_node(src_node, self._wiki_dir)
            self._db.sync_node(src_node, self._wiki_dir)

        if dst_path.exists():
            dst_node = read_node(dst_path)
            src_title = self._get_node_title(src_id)
            # Reverse the relation type where appropriate
            reverse_type = self._reverse_relation(rel_type)
            dst_node.add_relation(reverse_type, f"[[{src_title}]]")
            dst_node.touch()
            write_node(dst_node, self._wiki_dir)
            self._db.sync_node(dst_node, self._wiki_dir)

        self._db.upsert_edge(src_id, dst_id, rel_type)
        result.edges_added += 1

    def _get_node_title(self, node_id: str) -> str:
        """Get the title for a node, falling back to the id."""
        node_path = self._wiki_dir / f"{node_id}.md"
        if node_path.exists():
            node = read_node(node_path)
            return node.title
        return node_id.replace("-", " ").title()

    @staticmethod
    def _reverse_relation(rel_type: str) -> str:
        """Get the reverse relation type for bidirectional linking."""
        # Most relations are symmetric or use the same type in reverse.
        # supports/contradicts are symmetric in meaning at this level.
        return rel_type
