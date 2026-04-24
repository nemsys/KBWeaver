"""KBWeaver CLI — command-line interface.

All commands per TECH_SPEC §7.
Entry point: ``kbweaver`` (registered in pyproject.toml).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from kbweaver.config import load_config

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option(
    "-c", "--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None,
    help="Path to kbweaver.toml (auto-detected if omitted).",
)
@click.pass_context
def main(ctx: click.Context, verbose: bool, config_path: Path | None) -> None:
    """KBWeaver — Self-Organizing Personal Knowledge Engine."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


# ---------------------------------------------------------------------------
# Helper: get shared resources
# ---------------------------------------------------------------------------


def _get_db(config):
    """Instantiate and initialize the database."""
    from kbweaver.database import Database

    db = Database(config.db_path)
    db.init()
    return db


def _get_llm(config, stage="synthesis"):
    """Instantiate an LLM provider for the given stage."""
    from kbweaver.llm.factory import get_provider

    return get_provider(config, stage)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Start the background file watcher daemon.

    Monitors raw/ and processes new files automatically.
    """
    config = ctx.obj["config"]
    db = _get_db(config)
    llm = _get_llm(config, "entity_resolution")

    from kbweaver.watcher import FileWatcher

    watcher = FileWatcher(config, db, llm)
    try:
        watcher.start()
    finally:
        db.close()


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def ingest(ctx: click.Context, path: Path) -> None:
    """Manually trigger ingestion for a single file.

    Bypasses the watcher; useful for testing or one-off imports.
    """
    config = ctx.obj["config"]
    db = _get_db(config)
    llm = _get_llm(config, "entity_resolution")

    from kbweaver.ingestion import format_ingestion_report, ingest_file

    result = ingest_file(path, config, db, llm)
    click.echo(format_ingestion_report(result))
    db.close()


@main.command("query")
@click.argument("question")
@click.option("--depth", type=int, default=None, help="Override graph_depth for this query.")
@click.option("--top-k", type=int, default=None, help="Override fts_top_k for this query.")
@click.option("--no-file", is_flag=True, help="Disable filing of novel insights.")
@click.pass_context
def query_cmd(
    ctx: click.Context,
    question: str,
    depth: int | None,
    top_k: int | None,
    no_file: bool,
) -> None:
    """Submit a natural-language query."""
    config = ctx.obj["config"]

    # Apply overrides
    overrides = {}
    if depth is not None:
        config.query.graph_depth = depth
    if top_k is not None:
        config.query.fts_top_k = top_k
    if no_file:
        config.query.file_insights = False

    db = _get_db(config)
    llm = _get_llm(config, "synthesis")

    from kbweaver.query import format_query_result
    from kbweaver.query import query as run_query

    result = run_query(question, config, db, llm)
    click.echo(format_query_result(result))
    db.close()


@main.command("lint")
@click.option(
    "--apply",
    "apply_check",
    type=click.Choice(["orphans", "duplicates", "stale", "all"]),
    default=None,
    help="Run interactively and apply confirmed suggestions.",
)
@click.pass_context
def lint_cmd(ctx: click.Context, apply_check: str | None) -> None:
    """Run all maintenance checks and print the report.

    Use --apply to interactively resolve issues.
    """
    config = ctx.obj["config"]
    db = _get_db(config)

    # LLM is optional for lint — only needed for duplicate detection
    llm = None
    try:
        llm = _get_llm(config, "entity_resolution")
    except Exception:
        click.echo("Warning: LLM not available. Duplicate detection will be skipped.")

    from kbweaver.linter import apply_duplicates, format_lint_report, lint

    report = lint(config, db, llm)
    click.echo(format_lint_report(report))

    if apply_check:
        if apply_check in ("duplicates", "all") and report.duplicate_candidates:
            merged = apply_duplicates(report.duplicate_candidates, config, db)
            click.echo(f"\n{merged} duplicate(s) merged.")

        if apply_check in ("orphans", "all") and report.orphan_nodes:
            click.echo(f"\nOrphan nodes ({len(report.orphan_nodes)}):")
            for orphan in report.orphan_nodes:
                click.echo(f"  - {orphan['title']} ({orphan['id']})")
            click.echo("Orphan resolution requires manual linking or removal.")

        if apply_check in ("stale", "all") and report.stale_nodes:
            click.echo(f"\nStale nodes ({len(report.stale_nodes)}):")
            for stale in report.stale_nodes:
                click.echo(f"  - {stale['title']} ({stale['age_days']} days old)")

    db.close()


@main.command()
@click.pass_context
def rebuild(ctx: click.Context) -> None:
    """Rebuild all derived state in db/search.db from wiki/ files.

    Equivalent to: kbweaver rebuild-index && kbweaver rebuild-graph
    """
    config = ctx.obj["config"]
    db = _get_db(config)

    count = db.rebuild_from_wiki(config.wiki_dir)
    click.echo(f"Rebuilt index and graph from wiki/: {count} nodes indexed.")
    db.close()


@main.command("rebuild-index")
@click.pass_context
def rebuild_index(ctx: click.Context) -> None:
    """Rebuild only the FTS5 virtual table in search.db."""
    config = ctx.obj["config"]
    db = _get_db(config)

    # Drop and recreate only FTS5
    db.conn.execute("DROP TABLE IF EXISTS fts_nodes")
    db.conn.executescript(
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_nodes USING fts5("
        "id, title, aliases, body, tags, tokenize = 'porter unicode61');"
    )

    from kbweaver.wiki import list_nodes, read_node

    count = 0
    for node_path in list_nodes(config.wiki_dir):
        try:
            node = read_node(node_path)
            db.upsert_fts(node)
            count += 1
        except Exception as exc:
            click.echo(f"Warning: skipped {node_path.name}: {exc}")

    click.echo(f"Rebuilt FTS5 index: {count} nodes indexed.")
    db.close()


@main.command("rebuild-graph")
@click.pass_context
def rebuild_graph(ctx: click.Context) -> None:
    """Rebuild only the nodes and edges adjacency tables in search.db."""
    config = ctx.obj["config"]
    db = _get_db(config)

    from kbweaver.models import slug_from_title
    from kbweaver.wiki import list_nodes, read_node

    # Drop and recreate graph tables
    db.conn.executescript("""
        DROP TABLE IF EXISTS edges;
        DROP TABLE IF EXISTS nodes;
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, path TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS edges (
            src TEXT NOT NULL, dst TEXT NOT NULL, rel_type TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
    """)

    count = 0
    for node_path in list_nodes(config.wiki_dir):
        try:
            node = read_node(node_path)
            rel_path = node_path.relative_to(config.wiki_dir)
            db.upsert_node(node.id, node.title, str(rel_path))

            for rel in node.relations:
                target_title = rel.target.strip("[]")
                target_id = slug_from_title(target_title)
                db.upsert_edge(node.id, target_id, rel.type)

            count += 1
        except Exception as exc:
            click.echo(f"Warning: skipped {node_path.name}: {exc}")

    click.echo(f"Rebuilt graph: {count} nodes indexed.")
    db.close()


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Print a one-page graph health summary."""
    config = ctx.obj["config"]

    if not config.db_path.exists():
        click.echo("No database found. Run 'kbweaver rebuild' first.")
        return

    db = _get_db(config)
    stats = db.get_stats()

    click.echo("KBWeaver Status")
    click.echo("=" * 30)
    click.echo(f"Nodes:          {stats.node_count:,}")
    click.echo(f"Edges:          {stats.edge_count:,}")
    click.echo(f"Orphan nodes:   {stats.orphan_count:,}")
    click.echo(f"Avg edges/node: {stats.avg_edges_per_node:.2f}")

    # Wiki dir stats
    from kbweaver.wiki import list_nodes

    wiki_files = list_nodes(config.wiki_dir)
    click.echo(f"Wiki files:     {len(wiki_files)}")
    click.echo(f"Wiki dir:       {config.wiki_dir}")
    click.echo(f"Database:       {config.db_path}")

    db.close()
