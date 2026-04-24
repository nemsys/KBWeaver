"""Tests for kbweaver.config — configuration loading."""

from pathlib import Path

import pytest

from kbweaver.config import Config, load_config


@pytest.fixture
def config_file(tmp_path):
    """Create a temporary kbweaver.toml."""
    toml_content = """\
[llm]
backend = "ollama"
base_url = "http://localhost:11434"

[llm.entity_resolution]
model = "llama3.2:3b"

[llm.synthesis]
model = "llama3:8b"

[ingestion]
chunk_merge_threshold_tokens = 50
chunk_max_tokens = 800

[query]
fts_top_k = 5
graph_depth = 2
novelty_check = true
file_insights = true

[linter]
stale_threshold_days = 90
"""
    config_path = tmp_path / "kbweaver.toml"
    config_path.write_text(toml_content)
    return config_path


class TestLoadConfig:
    def test_load_default(self, config_file):
        config = load_config(config_file)
        assert config.llm.backend == "ollama"
        assert config.llm.entity_resolution.model == "llama3.2:3b"
        assert config.llm.synthesis.model == "llama3:8b"

    def test_load_ingestion(self, config_file):
        config = load_config(config_file)
        assert config.ingestion.chunk_max_tokens == 800
        assert config.ingestion.chunk_merge_threshold_tokens == 50

    def test_load_query(self, config_file):
        config = load_config(config_file)
        assert config.query.fts_top_k == 5
        assert config.query.graph_depth == 2
        assert config.query.novelty_check is True

    def test_load_linter(self, config_file):
        config = load_config(config_file)
        assert config.linter.stale_threshold_days == 90

    def test_paths_resolved(self, config_file):
        config = load_config(config_file)
        assert config.wiki_dir == config_file.parent / "wiki"
        assert config.db_path == config_file.parent / "db" / "search.db"

    def test_overrides(self, config_file):
        config = load_config(
            config_file,
            overrides={"query": {"fts_top_k": 10}},
        )
        assert config.query.fts_top_k == 10

    def test_missing_file_uses_defaults(self, tmp_path):
        missing_path = tmp_path / "nonexistent.toml"
        config = load_config(missing_path)
        assert config.llm.backend == "ollama"
        assert config.ingestion.chunk_max_tokens == 800


class TestConfigDefaults:
    def test_default_config(self):
        config = Config()
        assert config.llm.backend == "ollama"
        assert config.ingestion.chunk_max_tokens == 800
        assert config.query.fts_top_k == 5
