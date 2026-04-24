"""Ingestion engine — parsing, chunking, and orchestration.

Parses raw files using unstructured.io, chunks them respecting document
structure, and feeds chunks to the Agent for entity resolution.

See TECH_SPEC §3 for full specification.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kbweaver.agent import AgentResult, EntityResolver
from kbweaver.config import Config
from kbweaver.database import Database
from kbweaver.llm.base import LLMProvider
from kbweaver.timing import TimingRecord, timed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported format detection
# ---------------------------------------------------------------------------

_SUPPORTED_EXTENSIONS: set[str] = {
    ".pdf", ".docx", ".html", ".htm", ".txt", ".md",
    ".py", ".js", ".ts", ".go", ".rs", ".sh", ".yaml", ".yml", ".json",
}


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """Summary of a single file ingestion."""

    source_file: str = ""
    chunks_processed: int = 0
    nodes_created: int = 0
    nodes_updated: int = 0
    edges_added: int = 0
    timing: TimingRecord = field(default_factory=TimingRecord)
    error: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_file(path: Path) -> str:
    """Parse a file into plain text using unstructured.io.

    Falls back to direct text reading for formats that don't need
    complex parsing.
    """
    ext = path.suffix.lower()

    # Simple text formats — read directly
    if ext in {".txt", ".md", ".py", ".js", ".ts", ".go", ".rs", ".sh", ".yaml", ".yml", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace")

    # Complex formats — use unstructured
    try:
        from unstructured.partition.auto import partition

        elements = partition(filename=str(path))
        return "\n\n".join(str(el) for el in elements)
    except ImportError:
        logger.warning(
            "unstructured package not installed. "
            "Only plain text formats are supported. "
            "Install with: pip install 'unstructured[local-inference]'"
        )
        # Last resort: try reading as text
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to parse {path.name}: {exc}") from exc


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# Rough token estimate: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def chunk_text(
    text: str,
    max_tokens: int = 800,
    merge_threshold: int = 50,
) -> list[str]:
    """Split text into chunks respecting document structure.

    Priority order per TECH_SPEC §3.3:
    1. Section headings
    2. Paragraph breaks
    3. Sentence boundaries (fallback)

    Chunks smaller than *merge_threshold* tokens are merged with the next.
    """
    # Split on section headings first
    heading_pattern = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)
    sections = heading_pattern.split(text)

    # Recombine heading with its content
    raw_chunks: list[str] = []
    i = 0
    while i < len(sections):
        part = sections[i].strip()
        if heading_pattern.match(part) and i + 1 < len(sections):
            raw_chunks.append(part + "\n" + sections[i + 1].strip())
            i += 2
        elif part:
            raw_chunks.append(part)
            i += 1
        else:
            i += 1

    # If no headings found, split by paragraphs
    if len(raw_chunks) <= 1:
        raw_chunks = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Break oversized chunks at sentence boundaries
    max_chars = max_tokens * _CHARS_PER_TOKEN
    final_chunks: list[str] = []
    for chunk in raw_chunks:
        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
        else:
            # Split on sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", chunk)
            current = ""
            for sentence in sentences:
                if len(current) + len(sentence) > max_chars and current:
                    final_chunks.append(current.strip())
                    current = sentence
                else:
                    current = current + " " + sentence if current else sentence
            if current.strip():
                final_chunks.append(current.strip())

    # Merge tiny chunks with their neighbor
    merge_chars = merge_threshold * _CHARS_PER_TOKEN
    merged: list[str] = []
    for chunk in final_chunks:
        if merged and len(merged[-1]) < merge_chars:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)

    return merged


# ---------------------------------------------------------------------------
# Ingestion report
# ---------------------------------------------------------------------------


def format_ingestion_report(result: IngestResult) -> str:
    """Format an ingestion result as a human-readable report per TECH_SPEC §3.5."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lines = [
        f"KBWeaver Ingestion Report — {now}",
        "=" * 48,
        f"Source:            {result.source_file}",
        f"Chunks processed:  {result.chunks_processed}",
        f"Nodes created:     {result.nodes_created}",
        f"Nodes updated:     {result.nodes_updated}",
        f"Edges added:       {result.edges_added}",
        "",
        "Timing",
        result.timing.format_report(),
    ]
    if result.error:
        lines.extend(["", f"Error: {result.error}"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------


def ingest_file(
    path: Path,
    config: Config,
    db: Database,
    llm: LLMProvider,
) -> IngestResult:
    """Ingest a single file: parse → chunk → resolve entities → sync.

    Parameters
    ----------
    path:
        Path to the raw file to ingest.
    config:
        Loaded KBWeaver configuration.
    db:
        Initialized database instance.
    llm:
        LLM provider for entity resolution.

    Returns
    -------
    IngestResult
        Summary including counts and timing.
    """
    result = IngestResult(source_file=path.name)

    # Check format support
    if not _is_supported(path):
        _move_to_unsupported(path, config.archive_dir)
        result.error = f"Unsupported format: {path.suffix}"
        logger.warning("Unsupported format %s — moved to archive/unsupported/", path.suffix)
        return result

    # Parse
    with timed(result.timing, "Parse"):
        try:
            text = parse_file(path)
        except RuntimeError as exc:
            result.error = str(exc)
            logger.error("Parse failed for %s: %s", path.name, exc)
            return result

    # Strip frontmatter from markdown files
    if path.suffix.lower() == ".md":
        text = _strip_frontmatter(text)

    # Chunk
    chunks = chunk_text(
        text,
        max_tokens=config.ingestion.chunk_max_tokens,
        merge_threshold=config.ingestion.chunk_merge_threshold_tokens,
    )

    source_ref = f"[[archive/{path.name}]]"
    agent = EntityResolver(llm=llm, db=db, wiki_dir=config.wiki_dir, source_ref=source_ref)

    # Process chunks
    with timed(result.timing, "Entity resolution"):
        for chunk in chunks:
            try:
                agent_result = agent.process_chunk(chunk)
                result.chunks_processed += 1
                result.nodes_created += agent_result.nodes_created
                result.nodes_updated += agent_result.nodes_updated
                result.edges_added += agent_result.edges_added
            except Exception as exc:
                logger.error("Agent failed on chunk: %s", exc)
                # Continue processing remaining chunks (§3.4)
                continue

    # Index sync timing (most sync happens inline, this covers any finalization)
    with timed(result.timing, "Index sync"):
        pass  # sync is done per-node in the agent; placeholder for future batch ops

    # Move original to archive
    _move_to_archive(path, config.archive_dir)

    # Log the report
    report = format_ingestion_report(result)
    logger.info("\n%s", report)

    # Append to ingestion log
    _append_to_log(report, config.logs_dir)

    return result


# ---------------------------------------------------------------------------
# File management helpers
# ---------------------------------------------------------------------------


def _move_to_archive(path: Path, archive_dir: Path) -> None:
    """Move a processed file to the archive directory."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / path.name
    # Avoid overwriting — add timestamp suffix if needed
    if dest.exists():
        stem = path.stem
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        dest = archive_dir / f"{stem}_{ts}{path.suffix}"
    shutil.move(str(path), str(dest))
    logger.debug("Archived %s → %s", path.name, dest)


def _move_to_unsupported(path: Path, archive_dir: Path) -> None:
    """Move an unsupported file to archive/unsupported/."""
    unsupported_dir = archive_dir / "unsupported"
    unsupported_dir.mkdir(parents=True, exist_ok=True)
    dest = unsupported_dir / path.name
    shutil.move(str(path), str(dest))


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text before chunking."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].strip()
    return text


def _append_to_log(report: str, logs_dir: Path) -> None:
    """Append an ingestion report to the log file."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "ingestion.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(report + "\n\n")
