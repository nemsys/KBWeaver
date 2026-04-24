"""SQLite database layer for KBWeaver.

Manages the FTS5 full-text index and graph adjacency tables in ``db/search.db``.
Both are derived state — fully rebuildable from ``wiki/`` alone.

Schema defined in TECH_SPEC §2.1 (FTS5) and §2.2 (adjacency tables).
"""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kbweaver.models import WikiNode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- FTS5 full-text index (§2.1)
CREATE VIRTUAL TABLE IF NOT EXISTS fts_nodes USING fts5(
    id,
    title,
    aliases,
    body,
    tags,
    tokenize = 'porter unicode61'
);

-- Graph adjacency tables (§2.2)
CREATE TABLE IF NOT EXISTS nodes (
    id    TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    path  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL,
    rel_type TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FTSResult:
    """A single FTS5 search result."""

    id: str
    title: str
    aliases: str
    rank: float


@dataclass
class GraphStats:
    """Summary statistics for the knowledge graph."""

    node_count: int = 0
    edge_count: int = 0
    orphan_count: int = 0
    avg_edges_per_node: float = 0.0
    last_ingestion: str = ""


@dataclass
class TraversalResult:
    """Result of a BFS graph traversal."""

    node_ids: list[str] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (src, dst, rel_type)


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------


class Database:
    """Wrapper around the SQLite database containing FTS5 index and graph tables.

    Instantiate with the path to ``search.db``.  Call :meth:`init` before
    any other operation to ensure the schema exists.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle -----------------------------------------------------------

    def init(self) -> None:
        """Create the database file and schema if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialised. Call .init() first.")
        return self._conn

    # -- FTS5 operations -----------------------------------------------------

    def upsert_fts(self, node: WikiNode) -> None:
        """Insert or replace a node in the FTS5 index."""
        aliases_str = " ".join(node.aliases)
        tags_str = " ".join(node.tags)

        # FTS5 doesn't support UPDATE — delete then insert
        self.delete_fts(node.id)
        self.conn.execute(
            "INSERT INTO fts_nodes(id, title, aliases, body, tags) VALUES (?, ?, ?, ?, ?)",
            (node.id, node.title, aliases_str, node.body, tags_str),
        )
        self.conn.commit()

    def delete_fts(self, node_id: str) -> None:
        """Remove a node from the FTS5 index."""
        # For a standard (non-external-content) FTS5 table, use rowid-based DELETE.
        row = self.conn.execute(
            "SELECT rowid FROM fts_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row:
            self.conn.execute("DELETE FROM fts_nodes WHERE rowid = ?", (row[0],))
            self.conn.commit()

    def search_fts(self, query: str, top_k: int = 5) -> list[FTSResult]:
        """Search the FTS5 index, returning top-k results ranked by BM25.

        Parameters
        ----------
        query:
            The search string.  FTS5 query syntax is supported.
        top_k:
            Maximum number of results to return.
        """
        # Escape special FTS5 characters for safety
        safe_query = query.replace('"', '""')
        try:
            rows = self.conn.execute(
                'SELECT id, title, aliases, rank FROM fts_nodes WHERE fts_nodes MATCH ? '
                'ORDER BY rank LIMIT ?',
                (f'"{safe_query}"', top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.warning("FTS5 query failed for %r, falling back to title search", query)
            rows = self.conn.execute(
                "SELECT id, title, aliases, rank FROM fts_nodes "
                "WHERE fts_nodes MATCH ? ORDER BY rank LIMIT ?",
                (f"title:{safe_query}", top_k),
            ).fetchall()

        return [
            FTSResult(id=r["id"], title=r["title"], aliases=r["aliases"], rank=r["rank"])
            for r in rows
        ]

    # -- Graph node operations -----------------------------------------------

    def upsert_node(self, node_id: str, title: str, path: str) -> None:
        """Insert or replace a node in the adjacency table."""
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes(id, title, path) VALUES (?, ?, ?)",
            (node_id, title, path),
        )
        self.conn.commit()

    def delete_node(self, node_id: str) -> None:
        """Remove a node and its edges from the graph."""
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self.conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?", (node_id, node_id))
        self.conn.commit()

    # -- Graph edge operations -----------------------------------------------

    def upsert_edge(self, src: str, dst: str, rel_type: str) -> None:
        """Add an edge if it doesn't already exist."""
        existing = self.conn.execute(
            "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND rel_type = ?",
            (src, dst, rel_type),
        ).fetchone()
        if not existing:
            self.conn.execute(
                "INSERT INTO edges(src, dst, rel_type) VALUES (?, ?, ?)",
                (src, dst, rel_type),
            )
            self.conn.commit()

    def delete_edges_for(self, node_id: str) -> None:
        """Remove all edges where *node_id* is source or destination."""
        self.conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?", (node_id, node_id))
        self.conn.commit()

    # -- Graph traversal -----------------------------------------------------

    def get_neighbors(self, node_id: str, depth: int = 2) -> TraversalResult:
        """BFS traversal from *node_id* up to *depth* hops.

        Returns all discovered node IDs and the edges traversed.
        """
        visited: set[str] = {node_id}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        collected_edges: list[tuple[str, str, str]] = []

        while queue:
            current, d = queue.popleft()
            if d >= depth:
                continue

            rows = self.conn.execute(
                "SELECT src, dst, rel_type FROM edges WHERE src = ? OR dst = ?",
                (current, current),
            ).fetchall()

            for row in rows:
                src, dst, rel_type = row["src"], row["dst"], row["rel_type"]
                neighbor = dst if src == current else src
                collected_edges.append((src, dst, rel_type))
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, d + 1))

        return TraversalResult(
            node_ids=sorted(visited),
            edges=collected_edges,
        )

    # -- Graph queries -------------------------------------------------------

    def get_orphans(self) -> list[dict[str, Any]]:
        """Return nodes with no edges (orphans)."""
        rows = self.conn.execute(
            "SELECT id, title, path FROM nodes "
            "WHERE id NOT IN (SELECT src FROM edges UNION SELECT dst FROM edges)"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes in the graph."""
        rows = self.conn.execute("SELECT id, title, path FROM nodes").fetchall()
        return [dict(r) for r in rows]

    def get_all_edges(self) -> list[tuple[str, str, str]]:
        """Return all edges as (src, dst, rel_type) tuples."""
        rows = self.conn.execute("SELECT src, dst, rel_type FROM edges").fetchall()
        return [(r["src"], r["dst"], r["rel_type"]) for r in rows]

    def get_stats(self) -> GraphStats:
        """Compute summary statistics for the graph."""
        node_count = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        orphan_count = len(self.get_orphans())
        avg = edge_count / node_count if node_count > 0 else 0.0
        return GraphStats(
            node_count=node_count,
            edge_count=edge_count,
            orphan_count=orphan_count,
            avg_edges_per_node=round(avg, 2),
        )

    # -- Rebuild -------------------------------------------------------------

    def rebuild_from_wiki(self, wiki_dir: Path) -> int:
        """Drop and recreate all tables, then reindex every .md file in *wiki_dir*.

        Returns the number of nodes indexed.
        """
        from kbweaver.wiki import list_nodes, read_node

        # Drop existing tables
        self.conn.executescript("""
            DROP TABLE IF EXISTS edges;
            DROP TABLE IF EXISTS nodes;
            DROP TABLE IF EXISTS fts_nodes;
        """)
        # Recreate schema
        self.conn.executescript(_SCHEMA_SQL)

        count = 0
        for node_path in list_nodes(wiki_dir):
            try:
                node = read_node(node_path)
            except Exception:
                logger.warning("Failed to parse %s during rebuild, skipping", node_path)
                continue

            self.upsert_fts(node)
            rel_path = node_path.relative_to(wiki_dir)
            self.upsert_node(node.id, node.title, str(rel_path))

            for rel in node.relations:
                target_title = rel.target.strip("[]")
                from kbweaver.models import slug_from_title

                target_id = slug_from_title(target_title)
                self.upsert_edge(node.id, target_id, rel.type)

            count += 1

        logger.info("Rebuilt index with %d nodes from %s", count, wiki_dir)
        return count

    # -- Sync a single node --------------------------------------------------

    def sync_node(self, node: WikiNode, wiki_dir: Path) -> None:
        """Sync a single node's FTS and graph entries from its WikiNode data.

        Call this after writing the .md file to keep derived state current.
        """
        from kbweaver.models import slug_from_title

        self.upsert_fts(node)
        rel_path = f"{node.id}.md"
        self.upsert_node(node.id, node.title, rel_path)

        # Replace edges: delete old, insert new
        self.delete_edges_for(node.id)
        for rel in node.relations:
            target_title = rel.target.strip("[]")
            target_id = slug_from_title(target_title)
            self.upsert_edge(node.id, target_id, rel.type)
