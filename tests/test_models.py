"""Tests for kbweaver.models — WikiNode serialization round-trip."""

from datetime import datetime, timezone

from kbweaver.models import (
    Relation,
    WikiNode,
    deserialize_node,
    serialize_node,
    slug_from_title,
    title_from_wikilink,
)


class TestSlugFromTitle:
    def test_basic(self):
        assert slug_from_title("Transformer Architecture") == "transformer-architecture"

    def test_special_chars(self):
        assert slug_from_title("C++ Templates (Advanced)") == "c-templates-advanced"

    def test_leading_trailing(self):
        assert slug_from_title("  Hello World  ") == "hello-world"

    def test_multiple_spaces(self):
        assert slug_from_title("one   two   three") == "one-two-three"


class TestTitleFromWikilink:
    def test_basic(self):
        assert title_from_wikilink("[[Transformer Architecture]]") == "Transformer Architecture"


class TestRelation:
    def test_valid_types(self):
        for t in ("supports", "contradicts", "derived_from", "relates_to"):
            r = Relation(type=t, target="[[Test]]")
            assert r.type == t

    def test_invalid_type_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid relation type"):
            Relation(type="invalid", target="[[Test]]")


class TestWikiNodeRoundTrip:
    def _make_node(self) -> WikiNode:
        return WikiNode(
            id="transformer-architecture",
            title="Transformer Architecture",
            body="The transformer is a neural network architecture.",
            aliases=["transformers", "attention model"],
            created=datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc),
            updated=datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc),
            sources=["[[archive/paper.pdf]]"],
            relations=[
                Relation(type="supports", target="[[Attention Mechanism]]"),
                Relation(type="relates_to", target="[[Neural Networks]]"),
            ],
            tags=["ml", "architecture"],
        )

    def test_serialize_has_frontmatter(self):
        node = self._make_node()
        text = serialize_node(node)
        assert text.startswith("---\n")
        assert "id: transformer-architecture" in text
        assert "title: Transformer Architecture" in text

    def test_serialize_has_body(self):
        node = self._make_node()
        text = serialize_node(node)
        assert "# Transformer Architecture" in text
        assert "The transformer is a neural network architecture." in text

    def test_serialize_has_related(self):
        node = self._make_node()
        text = serialize_node(node)
        assert "## Related Concepts" in text
        assert "[[Attention Mechanism]]" in text

    def test_serialize_has_sources(self):
        node = self._make_node()
        text = serialize_node(node)
        assert "## Sources" in text
        assert "[[archive/paper.pdf]]" in text

    def test_round_trip(self):
        original = self._make_node()
        text = serialize_node(original)
        restored = deserialize_node(text)

        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.body == original.body
        assert restored.aliases == original.aliases
        assert restored.sources == original.sources
        assert len(restored.relations) == len(original.relations)
        assert restored.tags == original.tags

    def test_round_trip_preserves_relations(self):
        original = self._make_node()
        text = serialize_node(original)
        restored = deserialize_node(text)

        for orig_rel, rest_rel in zip(original.relations, restored.relations):
            assert orig_rel.type == rest_rel.type
            assert orig_rel.target == rest_rel.target

    def test_empty_node(self):
        node = WikiNode(id="empty", title="Empty Node")
        text = serialize_node(node)
        restored = deserialize_node(text)
        assert restored.id == "empty"
        assert restored.title == "Empty Node"
        assert restored.body == ""
        assert restored.relations == []

    def test_filename(self):
        node = self._make_node()
        assert node.filename == "transformer-architecture.md"
