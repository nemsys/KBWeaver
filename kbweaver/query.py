"""Query engine — natural-language queries against the knowledge base.

Implements the 6-step query flow from TECH_SPEC §5.1:
SEARCH → TRAVERSE → ASSEMBLE CONTEXT → SYNTHESIZE → NOVELTY CHECK → REPORT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from kbweaver.config import Config
from kbweaver.database import Database
from kbweaver.llm.base import LLMProvider
from kbweaver.models import WikiNode, slug_from_title
from kbweaver.prompts import (
    NOVELTY_CHECK_SYSTEM,
    NOVELTY_CHECK_USER,
    SYNTHESIZE_ANSWER_SYSTEM,
    SYNTHESIZE_ANSWER_USER,
)
from kbweaver.timing import TimingRecord, timed
from kbweaver.wiki import read_node

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of a knowledge base query."""

    question: str = ""
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    novel_concept: str | None = None
    timing: TimingRecord = field(default_factory=TimingRecord)


def query(
    question: str,
    config: Config,
    db: Database,
    llm: LLMProvider,
) -> QueryResult:
    """Execute a natural-language query against the knowledge base.

    Parameters
    ----------
    question:
        The user's natural-language question.
    config:
        Loaded KBWeaver configuration.
    db:
        Initialized database instance.
    llm:
        LLM provider for answer synthesis (typically the 8B model).

    Returns
    -------
    QueryResult
        The synthesized answer with citations and timing data.
    """
    result = QueryResult(question=question)
    wiki_dir = config.wiki_dir
    top_k = config.query.fts_top_k
    graph_depth = config.query.graph_depth

    # Step 1: SEARCH — FTS5 full-text search
    with timed(result.timing, "FTS5 lookup"):
        fts_results = db.search_fts(question, top_k=top_k)

    if not fts_results:
        result.answer = (
            "No relevant nodes found in the knowledge base for this query. "
            "Try rephrasing or ingest more content."
        )
        return result

    entry_node_ids = [r.id for r in fts_results]
    logger.debug("FTS5 entry nodes: %s", entry_node_ids)

    # Step 2: TRAVERSE — BFS graph traversal
    with timed(result.timing, "Graph traversal"):
        all_node_ids: set[str] = set()
        for node_id in entry_node_ids:
            traversal = db.get_neighbors(node_id, depth=graph_depth)
            all_node_ids.update(traversal.node_ids)

    logger.debug("Traversal collected %d unique nodes", len(all_node_ids))

    # Step 3: ASSEMBLE CONTEXT
    with timed(result.timing, "Context assembly"):
        context_blocks: list[str] = []
        loaded_nodes: list[WikiNode] = []

        for node_id in sorted(all_node_ids):
            node_path = wiki_dir / f"{node_id}.md"
            if not node_path.exists():
                continue
            try:
                node = read_node(node_path)
                loaded_nodes.append(node)

                # Build context entry with relation annotations
                relations_str = ""
                if node.relations:
                    rels = [f"  - {r.type}: {r.target}" for r in node.relations]
                    relations_str = "\nRelations:\n" + "\n".join(rels)

                block = f"### {node.title}\n{node.body}{relations_str}"
                context_blocks.append(block)
                result.sources.append(node.title)
            except Exception as exc:
                logger.warning("Failed to load node %s: %s", node_id, exc)

    if not context_blocks:
        result.answer = "Found references but could not load any node content."
        return result

    context = "\n\n---\n\n".join(context_blocks)

    # Step 4: SYNTHESIZE
    with timed(result.timing, "LLM synthesis"):
        prompt = SYNTHESIZE_ANSWER_USER.format(question=question, context=context)
        result.answer = llm.complete(SYNTHESIZE_ANSWER_SYSTEM, prompt).strip()

    # Step 5: NOVELTY CHECK (optional)
    if config.query.novelty_check:
        with timed(result.timing, "Novelty check"):
            node_titles = [n.title for n in loaded_nodes]
            novelty_prompt = NOVELTY_CHECK_USER.format(
                answer=result.answer,
                node_titles=", ".join(node_titles),
            )
            novelty_response = llm.complete(NOVELTY_CHECK_SYSTEM, novelty_prompt).strip()

            if novelty_response.upper().startswith("YES"):
                lines = novelty_response.split("\n")
                if len(lines) >= 2:
                    novel_concept = lines[1].strip()
                    result.novel_concept = novel_concept

                    if config.query.file_insights and novel_concept:
                        _file_novel_insight(
                            concept_name=novel_concept,
                            answer=result.answer,
                            sources=result.sources,
                            config=config,
                            db=db,
                        )

    return result


def _file_novel_insight(
    concept_name: str,
    answer: str,
    sources: list[str],
    config: Config,
    db: Database,
) -> None:
    """Create a new wiki node for a novel insight derived from a query answer."""
    from datetime import datetime, timezone

    from kbweaver.wiki import write_node

    concept_id = slug_from_title(concept_name)
    now = datetime.now(timezone.utc)

    node = WikiNode(
        id=concept_id,
        title=concept_name,
        body=answer,
        created=now,
        updated=now,
        sources=[f"[[{s}]]" for s in sources],
        tags=["insight", "auto-generated"],
    )

    # Link to source nodes
    for source_title in sources:
        node.add_relation("derived_from", f"[[{source_title}]]")

    write_node(node, config.wiki_dir)
    db.sync_node(node, config.wiki_dir)
    logger.info("Filed novel insight: %s", concept_name)


def format_query_result(result: QueryResult) -> str:
    """Format a query result for display."""
    lines = [
        result.answer,
        "",
        "---",
        f"Sources: {', '.join(result.sources)}" if result.sources else "",
    ]
    if result.novel_concept:
        lines.append(f"Novel insight filed: {result.novel_concept}")
    lines.extend([
        "",
        "Timing",
        result.timing.format_report(),
    ])
    return "\n".join(lines)
