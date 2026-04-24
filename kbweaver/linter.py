"""Linter — knowledge base maintenance agent.

Detects quality issues (duplicates, orphans, contradictions, stale nodes,
disconnected subgraphs) and produces actionable reports per TECH_SPEC §6.

The Linter never modifies data without explicit user confirmation.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kbweaver.config import Config
from kbweaver.database import Database
from kbweaver.llm.base import LLMProvider
from kbweaver.models import WikiNode, slug_from_title
from kbweaver.prompts import DUPLICATE_CHECK_SYSTEM, DUPLICATE_CHECK_USER
from kbweaver.timing import TimingRecord, timed
from kbweaver.wiki import list_nodes, read_node, write_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DuplicateCandidate:
    """A pair of nodes suspected to be duplicates."""

    node_a_id: str
    node_a_title: str
    node_a_path: str
    node_b_id: str
    node_b_title: str
    node_b_path: str
    similarity_score: float = 0.0


@dataclass
class LintReport:
    """Full lint report per TECH_SPEC §6.2."""

    total_nodes: int = 0
    total_edges: int = 0
    avg_edges_per_node: float = 0.0
    orphan_nodes: list[dict] = field(default_factory=list)
    duplicate_candidates: list[DuplicateCandidate] = field(default_factory=list)
    contradictions: list[tuple[str, str]] = field(default_factory=list)
    disconnected_clusters: list[list[str]] = field(default_factory=list)
    stale_nodes: list[dict] = field(default_factory=list)
    timing: TimingRecord = field(default_factory=TimingRecord)


# ---------------------------------------------------------------------------
# Lint checks
# ---------------------------------------------------------------------------


def lint(
    config: Config,
    db: Database,
    llm: LLMProvider | None = None,
) -> LintReport:
    """Run all maintenance checks and produce a report.

    Parameters
    ----------
    config:
        Loaded KBWeaver configuration.
    db:
        Initialized database instance.
    llm:
        Optional LLM provider for duplicate confirmation and contradiction
        analysis.  If None, LLM-dependent checks are skipped.

    Returns
    -------
    LintReport
        The full lint report.
    """
    report = LintReport()

    with timed(report.timing, "Lint"):
        stats = db.get_stats()
        report.total_nodes = stats.node_count
        report.total_edges = stats.edge_count
        report.avg_edges_per_node = stats.avg_edges_per_node

        # Orphan nodes
        report.orphan_nodes = db.get_orphans()

        # Duplicate candidates
        if llm:
            report.duplicate_candidates = _find_duplicates(config, db, llm)

        # Contradictions
        report.contradictions = _find_contradictions(db)

        # Disconnected subgraphs
        report.disconnected_clusters = _find_disconnected_clusters(db)

        # Stale nodes
        report.stale_nodes = _find_stale_nodes(config, db)

    return report


def _find_duplicates(
    config: Config,
    db: Database,
    llm: LLMProvider,
) -> list[DuplicateCandidate]:
    """Find potential duplicate nodes using FTS5 similarity + LLM confirmation."""
    candidates: list[DuplicateCandidate] = []
    all_nodes = db.get_all_nodes()
    checked_pairs: set[tuple[str, str]] = set()

    for node_info in all_nodes:
        node_id = node_info["id"]
        title = node_info["title"]

        # Search for similar nodes
        fts_results = db.search_fts(title, top_k=3)
        for hit in fts_results:
            if hit.id == node_id:
                continue
            pair = tuple(sorted([node_id, hit.id]))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            # Load both nodes for LLM comparison
            node_a_path = config.wiki_dir / f"{node_id}.md"
            node_b_path = config.wiki_dir / f"{hit.id}.md"
            if not node_a_path.exists() or not node_b_path.exists():
                continue

            try:
                node_a = read_node(node_a_path)
                node_b = read_node(node_b_path)
            except Exception:
                continue

            prompt = DUPLICATE_CHECK_USER.format(
                title_a=node_a.title,
                aliases_a=", ".join(node_a.aliases) or "(none)",
                body_a=node_a.body[:300],
                title_b=node_b.title,
                aliases_b=", ".join(node_b.aliases) or "(none)",
                body_b=node_b.body[:300],
            )
            response = llm.complete(DUPLICATE_CHECK_SYSTEM, prompt)

            if response.strip().upper().startswith("YES"):
                candidates.append(
                    DuplicateCandidate(
                        node_a_id=node_a.id,
                        node_a_title=node_a.title,
                        node_a_path=str(node_a_path),
                        node_b_id=node_b.id,
                        node_b_title=node_b.title,
                        node_b_path=str(node_b_path),
                        similarity_score=abs(hit.rank),
                    )
                )

    return candidates


def _find_contradictions(db: Database) -> list[tuple[str, str]]:
    """Find pairs of nodes connected by 'contradicts' edges."""
    all_edges = db.get_all_edges()
    return [(src, dst) for src, dst, rel in all_edges if rel == "contradicts"]


def _find_disconnected_clusters(db: Database) -> list[list[str]]:
    """Find connected components in the graph.

    Returns clusters sorted by size (largest first), excluding the main
    component (the largest one).
    """
    all_nodes = db.get_all_nodes()
    all_edges = db.get_all_edges()

    if not all_nodes:
        return []

    # Build adjacency list
    adj: dict[str, set[str]] = {n["id"]: set() for n in all_nodes}
    for src, dst, _ in all_edges:
        if src in adj:
            adj[src].add(dst)
        if dst in adj:
            adj[dst].add(src)

    # BFS connected components
    visited: set[str] = set()
    components: list[list[str]] = []

    for node_id in adj:
        if node_id in visited:
            continue
        component: list[str] = []
        queue: deque[str] = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in adj.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(component)

    # Sort by size, return all except the largest (main cluster)
    components.sort(key=len, reverse=True)
    if len(components) > 1:
        return components[1:]  # skip the main cluster
    return []


def _find_stale_nodes(config: Config, db: Database) -> list[dict]:
    """Find nodes not updated within the stale threshold and with zero incoming edges."""
    threshold_days = config.linter.stale_threshold_days
    cutoff = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Simple approach: check each node's updated timestamp
    stale: list[dict] = []
    all_edges = db.get_all_edges()
    nodes_with_incoming = {dst for _, dst, _ in all_edges}

    for node_path in list_nodes(config.wiki_dir):
        try:
            node = read_node(node_path)
        except Exception:
            continue

        if node.id in nodes_with_incoming:
            continue

        age_days = (cutoff - node.updated).days
        if age_days > threshold_days:
            stale.append({
                "id": node.id,
                "title": node.title,
                "age_days": age_days,
                "path": str(node_path),
            })

    return stale


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_lint_report(report: LintReport) -> str:
    """Format a lint report for CLI output per TECH_SPEC §6.2."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lines = [
        f"KBWeaver Lint Report — {now}",
        "=" * 42,
        f"Total nodes:              {report.total_nodes:,}",
        f"Total edges:              {report.total_edges:,}",
        f"Avg. edges per node:      {report.avg_edges_per_node:.2f}",
        "",
        f"Orphan nodes:             {len(report.orphan_nodes):<6}"
        "  [run: kbweaver lint --apply orphans]",
        f"Duplicate candidates:     {len(report.duplicate_candidates):<6}"
        "  [run: kbweaver lint --apply duplicates]",
        f"Contradictions flagged:   {len(report.contradictions):<6}"
        "  [manual review required]",
        f"Disconnected clusters:    {len(report.disconnected_clusters):<6}",
    ]

    # Annotate largest disconnected cluster
    if report.disconnected_clusters:
        largest = report.disconnected_clusters[0]
        lines[-1] += f"  [largest: {len(largest)} nodes]"

    lines.append(
        f"Stale nodes:              {len(report.stale_nodes):<6}"
        "  [run: kbweaver lint --apply stale]"
    )
    lines.extend(["", "Timing", report.timing.format_report()])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interactive apply mode (§6.3)
# ---------------------------------------------------------------------------


def apply_duplicates(
    candidates: list[DuplicateCandidate],
    config: Config,
    db: Database,
) -> int:
    """Interactively resolve duplicate candidates.

    Returns the number of merges performed.
    """
    merged = 0
    for i, dup in enumerate(candidates, 1):
        print(f"\n[{i}/{len(candidates)}] DUPLICATE CANDIDATE")
        print(f'  "{dup.node_a_title}" (wiki/{dup.node_a_id}.md)')
        print(f'  "{dup.node_b_title}" (wiki/{dup.node_b_id}.md)')
        print(f"  Similarity score: {dup.similarity_score:.2f}")
        print()

        choice = input("  Action? [m]erge / [k]eep both / [s]kip  → ").strip().lower()

        if choice == "m":
            _merge_nodes(dup.node_a_id, dup.node_b_id, config, db)
            merged += 1
        elif choice == "k":
            # Add explicit relates_to edge to suppress future detection
            db.upsert_edge(dup.node_a_id, dup.node_b_id, "relates_to")
            print("  → Kept both; added relates_to edge.")
        else:
            print("  → Skipped.")

    return merged


def _merge_nodes(keep_id: str, remove_id: str, config: Config, db: Database) -> None:
    """Merge two nodes: combine content into the first, remove the second."""
    keep_path = config.wiki_dir / f"{keep_id}.md"
    remove_path = config.wiki_dir / f"{remove_id}.md"

    if not keep_path.exists() or not remove_path.exists():
        logger.warning("Cannot merge: one or both nodes missing from disk.")
        return

    keep_node = read_node(keep_path)
    remove_node = read_node(remove_path)

    # Merge content
    if remove_node.body:
        keep_node.body = keep_node.body + "\n\n" + remove_node.body

    # Merge aliases
    for alias in remove_node.aliases:
        if alias not in keep_node.aliases:
            keep_node.aliases.append(alias)
    if remove_node.title not in keep_node.aliases:
        keep_node.aliases.append(remove_node.title)

    # Merge sources
    for source in remove_node.sources:
        keep_node.add_source(source)

    # Merge relations (skip self-references)
    for rel in remove_node.relations:
        target_title = rel.target.strip("[]")
        if slug_from_title(target_title) != keep_id:
            keep_node.add_relation(rel.type, rel.target)

    keep_node.touch()
    write_node(keep_node, config.wiki_dir)

    # Remove the merged node
    remove_path.unlink()
    db.delete_node(remove_id)
    db.delete_fts(remove_id)
    db.sync_node(keep_node, config.wiki_dir)

    print(f'  → Merged into "{keep_node.title}".')
