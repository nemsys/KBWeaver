"""Tests for kbweaver.database — SQLite FTS5 and graph operations."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kbweaver.database import Database
from kbweaver.models import Relation, WikiNode


@pytest.fixture
def db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_search.db"
    database = Database(db_path)
    database.init()
    yield database
    database.close()


@pytest.fixture
def sample_node():
    return WikiNode(
        id="transformer-architecture",
        title="Transformer Architecture",
        body="The transformer is a neural network architecture based on self-attention.",
        aliases=["transformers", "attention model"],
        created=datetime(2026, 4, 18, tzinfo=timezone.utc),
        updated=datetime(2026, 4, 18, tzinfo=timezone.utc),
        tags=["ml", "architecture"],
    )


class TestFTS5:
    def test_upsert_and_search(self, db, sample_node):
        db.upsert_fts(sample_node)
        results = db.search_fts("transformer", top_k=5)
        assert len(results) >= 1
        assert results[0].id == "transformer-architecture"

    def test_search_by_alias(self, db, sample_node):
        db.upsert_fts(sample_node)
        results = db.search_fts("attention model", top_k=5)
        assert len(results) >= 1

    def test_search_empty_db(self, db):
        results = db.search_fts("anything", top_k=5)
        assert results == []

    def test_delete_fts(self, db, sample_node):
        db.upsert_fts(sample_node)
        db.delete_fts(sample_node.id)
        results = db.search_fts("transformer", top_k=5)
        assert len(results) == 0

    def test_upsert_replaces(self, db, sample_node):
        db.upsert_fts(sample_node)
        sample_node.body = "Updated body text about transformers."
        db.upsert_fts(sample_node)
        results = db.search_fts("transformer", top_k=5)
        assert len(results) == 1


class TestGraphNodes:
    def test_upsert_node(self, db):
        db.upsert_node("test-node", "Test Node", "test-node.md")
        nodes = db.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0]["id"] == "test-node"

    def test_delete_node(self, db):
        db.upsert_node("test-node", "Test Node", "test-node.md")
        db.delete_node("test-node")
        nodes = db.get_all_nodes()
        assert len(nodes) == 0


class TestGraphEdges:
    def test_upsert_edge(self, db):
        db.upsert_node("a", "Node A", "a.md")
        db.upsert_node("b", "Node B", "b.md")
        db.upsert_edge("a", "b", "supports")
        edges = db.get_all_edges()
        assert len(edges) == 1
        assert edges[0] == ("a", "b", "supports")

    def test_upsert_edge_no_duplicates(self, db):
        db.upsert_node("a", "Node A", "a.md")
        db.upsert_node("b", "Node B", "b.md")
        db.upsert_edge("a", "b", "supports")
        db.upsert_edge("a", "b", "supports")
        edges = db.get_all_edges()
        assert len(edges) == 1

    def test_delete_edges_for(self, db):
        db.upsert_node("a", "Node A", "a.md")
        db.upsert_node("b", "Node B", "b.md")
        db.upsert_node("c", "Node C", "c.md")
        db.upsert_edge("a", "b", "supports")
        db.upsert_edge("a", "c", "relates_to")
        db.delete_edges_for("a")
        edges = db.get_all_edges()
        assert len(edges) == 0


class TestBFSTraversal:
    def test_simple_traversal(self, db):
        db.upsert_node("a", "A", "a.md")
        db.upsert_node("b", "B", "b.md")
        db.upsert_node("c", "C", "c.md")
        db.upsert_edge("a", "b", "supports")
        db.upsert_edge("b", "c", "relates_to")

        result = db.get_neighbors("a", depth=2)
        assert "a" in result.node_ids
        assert "b" in result.node_ids
        assert "c" in result.node_ids

    def test_depth_limit(self, db):
        db.upsert_node("a", "A", "a.md")
        db.upsert_node("b", "B", "b.md")
        db.upsert_node("c", "C", "c.md")
        db.upsert_edge("a", "b", "supports")
        db.upsert_edge("b", "c", "relates_to")

        result = db.get_neighbors("a", depth=1)
        assert "a" in result.node_ids
        assert "b" in result.node_ids
        assert "c" not in result.node_ids

    def test_isolated_node(self, db):
        db.upsert_node("lonely", "Lonely", "lonely.md")
        result = db.get_neighbors("lonely", depth=2)
        assert result.node_ids == ["lonely"]
        assert result.edges == []


class TestGraphStats:
    def test_stats_empty(self, db):
        stats = db.get_stats()
        assert stats.node_count == 0
        assert stats.edge_count == 0

    def test_stats_with_data(self, db):
        db.upsert_node("a", "A", "a.md")
        db.upsert_node("b", "B", "b.md")
        db.upsert_edge("a", "b", "supports")
        stats = db.get_stats()
        assert stats.node_count == 2
        assert stats.edge_count == 1
        assert stats.orphan_count == 0

    def test_orphan_detection(self, db):
        db.upsert_node("a", "A", "a.md")
        db.upsert_node("b", "B", "b.md")
        db.upsert_node("orphan", "Orphan", "orphan.md")
        db.upsert_edge("a", "b", "supports")
        stats = db.get_stats()
        assert stats.orphan_count == 1


class TestRebuild:
    def test_rebuild_from_wiki(self, db, tmp_path):
        from kbweaver.wiki import write_node

        wiki_dir = tmp_path / "wiki"

        # Create some nodes
        node_a = WikiNode(
            id="concept-a", title="Concept A", body="Body A",
            created=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated=datetime(2026, 1, 1, tzinfo=timezone.utc),
            relations=[Relation(type="supports", target="[[Concept B]]")],
        )
        node_b = WikiNode(
            id="concept-b", title="Concept B", body="Body B",
            created=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        write_node(node_a, wiki_dir)
        write_node(node_b, wiki_dir)

        count = db.rebuild_from_wiki(wiki_dir)
        assert count == 2

        # Verify FTS
        results = db.search_fts("Concept A")
        assert len(results) >= 1

        # Verify graph
        nodes = db.get_all_nodes()
        assert len(nodes) == 2

        edges = db.get_all_edges()
        assert len(edges) == 1
        assert edges[0][2] == "supports"
