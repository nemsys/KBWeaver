"""Configuration loader for KBWeaver.

Reads kbweaver.toml from the project root and provides a typed config object.
CLI flag overrides are merged on top of file-based config.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LLMModelConfig:
    """Configuration for a single LLM model binding."""

    model: str = ""


@dataclass
class LLMConfig:
    """LLM backend configuration."""

    backend: str = "ollama"
    base_url: str = "http://localhost:11434"
    entity_resolution: LLMModelConfig = field(default_factory=lambda: LLMModelConfig("llama3.2:3b"))
    synthesis: LLMModelConfig = field(default_factory=lambda: LLMModelConfig("llama3:8b"))


@dataclass
class IngestionConfig:
    """Ingestion engine parameters."""

    chunk_merge_threshold_tokens: int = 50
    chunk_max_tokens: int = 800


@dataclass
class QueryConfig:
    """Query engine parameters."""

    fts_top_k: int = 5
    graph_depth: int = 2
    novelty_check: bool = True
    file_insights: bool = True


@dataclass
class LinterConfig:
    """Linter parameters."""

    stale_threshold_days: int = 90


@dataclass
class Config:
    """Top-level KBWeaver configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    query: QueryConfig = field(default_factory=QueryConfig)
    linter: LinterConfig = field(default_factory=LinterConfig)

    # Resolved paths (set after loading)
    project_root: Path = field(default_factory=lambda: Path.cwd())
    raw_dir: Path = field(default_factory=lambda: Path.cwd() / "raw")
    archive_dir: Path = field(default_factory=lambda: Path.cwd() / "archive")
    wiki_dir: Path = field(default_factory=lambda: Path.cwd() / "wiki")
    db_dir: Path = field(default_factory=lambda: Path.cwd() / "db")
    db_path: Path = field(default_factory=lambda: Path.cwd() / "db" / "search.db")
    logs_dir: Path = field(default_factory=lambda: Path.cwd() / "logs")


def _find_project_root(start: Path | None = None) -> Path:
    """Walk upward from *start* to find the directory containing kbweaver.toml."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / "kbweaver.toml").exists():
            return parent
    return current


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    """Load configuration from a TOML file with optional overrides.

    Parameters
    ----------
    config_path:
        Explicit path to kbweaver.toml.  When *None*, the file is located
        by walking upward from the current working directory.
    overrides:
        Dict of nested overrides (e.g. from CLI flags) merged on top of
        the file-based configuration.
    """
    if config_path is None:
        root = _find_project_root()
        config_path = root / "kbweaver.toml"
    else:
        root = config_path.parent

    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh)

    if overrides:
        raw = _merge_dict(raw, overrides)

    # Build typed config
    llm_raw = raw.get("llm", {})
    er_raw = llm_raw.pop("entity_resolution", {})
    syn_raw = llm_raw.pop("synthesis", {})

    llm_cfg = LLMConfig(
        backend=llm_raw.get("backend", "ollama"),
        base_url=llm_raw.get("base_url", "http://localhost:11434"),
        entity_resolution=LLMModelConfig(model=er_raw.get("model", "llama3.2:3b")),
        synthesis=LLMModelConfig(model=syn_raw.get("model", "llama3:8b")),
    )

    ing_raw = raw.get("ingestion", {})
    ing_cfg = IngestionConfig(
        chunk_merge_threshold_tokens=ing_raw.get("chunk_merge_threshold_tokens", 50),
        chunk_max_tokens=ing_raw.get("chunk_max_tokens", 800),
    )

    q_raw = raw.get("query", {})
    q_cfg = QueryConfig(
        fts_top_k=q_raw.get("fts_top_k", 5),
        graph_depth=q_raw.get("graph_depth", 2),
        novelty_check=q_raw.get("novelty_check", True),
        file_insights=q_raw.get("file_insights", True),
    )

    l_raw = raw.get("linter", {})
    l_cfg = LinterConfig(
        stale_threshold_days=l_raw.get("stale_threshold_days", 90),
    )

    cfg = Config(
        llm=llm_cfg,
        ingestion=ing_cfg,
        query=q_cfg,
        linter=l_cfg,
        project_root=root,
        raw_dir=root / "raw",
        archive_dir=root / "archive",
        wiki_dir=root / "wiki",
        db_dir=root / "db",
        db_path=root / "db" / "search.db",
        logs_dir=root / "logs",
    )
    return cfg
