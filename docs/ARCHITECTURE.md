# KBWeaver — System Architecture Document
**Version:** 1.0\
**Status:** Draft\
**Author:** Sonnet 4.6 Ext\
**Stack:** Python · Ollama (Gemma 4) · Kùzu · SQLite FTS5 · unstructured.io · instructor

---

## 1. Guiding Principles

1. **Markdown is the source of truth.** The graph DB and search index are derived, rebuildable artifacts. Deleting them and rebuilding from `wiki/` must always be possible.
2. **No framework lock-in.** No LangChain, no LlamaIndex. Pure Python with thin, replaceable adapters around each external dependency.
3. **Crash-safe by default.** Every processing step is idempotent and backed by a persistent job queue. A hard reboot must not corrupt state.
4. **Local-first, privacy-first.** No network calls except to the local Ollama endpoint.
5. **Derived indexes are rebuildable.** A single CLI command (`kbweaver rebuild`) reconstructs Kùzu and FTS5 from the `wiki/` directory.

---

## 2. Repository Structure

```
kbweaver/
├── raw/                        # Drop zone — immutable originals
├── wiki/                       # Source of truth — all .md files
├── db/
│   ├── queue.sqlite            # Job queue + FTS5 search index
│   └── graph/                  # Kùzu database directory
├── logs/
│   └── kbweaver.log
├── kbweaver/                  # Python package
│   ├── __init__.py
│   ├── config.py               # Pydantic Settings — single config object
│   ├── models.py               # Pydantic domain models
│   │
│   ├── ingestion/
│   │   ├── watcher.py          # watchdog filesystem event handler
│   │   ├── parser.py           # unstructured.io adapter
│   │   └── chunker.py          # Semantic chunking logic
│   │
│   ├── agent/
│   │   ├── client.py           # Ollama + instructor adapter
│   │   ├── extractor.py        # Entity/claim extraction prompts
│   │   ├── resolver.py         # Entity resolution (FTS5 + LLM confirm)
│   │   └── writer.py           # MD node creation/update logic
│   │
│   ├── graph/
│   │   ├── db.py               # Kùzu connection + schema management
│   │   └── queries.py          # Graph traversal, gap analysis
│   │
│   ├── search/
│   │   └── fts.py              # SQLite FTS5 index management
│   │
│   ├── queue/
│   │   └── jobs.py             # SQLite-backed job queue
│   │
│   ├── linter/
│   │   └── linter.py           # Duplicate detection, orphan flagging
│   │
│   └── cli/
│       └── main.py             # Typer CLI entry point
│
├── pyproject.toml              # uv-managed dependencies
├── .env                        # Local overrides (gitignored)
└── CLAUDE.md                   # Claude Code session context
```

---

## 3. Component Architecture

### 3.1 Ingestion Pipeline

```
raw/ filesystem event
        │
        ▼
  [watcher.py]                  watchdog DirectoryWatcher
  detects CREATE/MOVED_TO       filters: pdf, docx, txt, md, py, etc.
        │
        ▼
  [jobs.py]                     INSERT INTO jobs (path, status='pending')
  enqueues job                  status: pending → processing → done | failed
        │
        ▼
  [worker loop]                 polls: SELECT * FROM jobs WHERE status='pending'
        │
        ├──► [parser.py]        unstructured.io → raw text
        │
        ├──► [chunker.py]       split into semantic chunks
        │                       strategy: section headers > paragraph > token window
        │
        ├──► [extractor.py]     LLM: extract entities + claims per chunk
        │                       output: List[Entity], List[Claim]
        │
        ├──► [resolver.py]      for each entity:
        │                         1. FTS5 BM25 candidate lookup (top-5)
        │                         2. LLM: "Is entity X the same as candidate Y?" → bool
        │                         3. resolve to existing node or create new
        │
        ├──► [writer.py]        create/update .md files + YAML frontmatter
        │                       inject [[wiki-links]] bidirectionally
        │
        ├──► [fts.py]           re-index modified .md files in FTS5
        │
        └──► [db.py]            upsert nodes + edges in Kùzu
```

### 3.2 Agent (LLM Layer)

Single Ollama endpoint. All calls go through `client.py`, which wraps `instructor` for structured Pydantic outputs.

**Models used:**

| Task | Prompt style | Output model |
|---|---|---|
| Entity extraction | One-shot + schema | `List[Entity]` |
| Claim extraction | One-shot + schema | `List[Claim]` |
| Entity resolution | Binary decision | `ResolutionDecision` |
| Novel insight detection | Classification | `InsightDecision` |
| Linter merge proposal | Comparison | `MergeProposal` |

**client.py contract:**
```python
def complete(prompt: str, response_model: type[T], temperature: float = 0.1) -> T:
    # instructor-patched Ollama client
    # retries: 3, timeout: 60s
    # logs token usage to queue.sqlite for monitoring
```

Low temperature (0.1) is default across all extraction tasks — determinism over creativity. Temperature is raised only for the novel insight synthesis step.

### 3.3 Data Models (`models.py`)

```python
class Entity(BaseModel):
    name: str                       # canonical node name
    aliases: list[str]              # alternate names found in source
    entity_type: str                # concept | person | tool | method | claim
    summary: str                    # 1-2 sentence description
    source_file: str                # path to raw/ origin

class Claim(BaseModel):
    statement: str
    confidence: float               # 0.0–1.0, LLM self-assessed
    relation_type: str              # supports | contradicts | relates_to | derived_from
    subject: str                    # entity name
    object: str                     # entity name

class WikiNode(BaseModel):
    slug: str                       # filename without .md, kebab-case
    title: str
    entity_type: str
    summary: str
    aliases: list[str]
    tags: list[str]
    sources: list[str]              # raw/ file paths
    relates_to: list[str]
    contradicts: list[str]
    supports: list[str]
    derived_from: list[str]
    created_at: datetime
    updated_at: datetime

class Job(BaseModel):
    id: int
    raw_path: str
    status: Literal["pending", "processing", "done", "failed"]
    error: str | None
    retries: int
    created_at: datetime
    updated_at: datetime
```

### 3.4 Markdown Node Format

```markdown
---
title: "Knowledge Graph"
slug: knowledge-graph
entity_type: concept
aliases: ["KG", "graph database"]
tags: ["graph", "ai", "rag"]
sources:
  - raw/paper-graph-rag-2024.pdf
relates_to:
  - "[[Neo4j]]"
  - "[[Semantic Search]]"
contradicts: []
supports:
  - "[[RAG]]"
derived_from: []
created_at: 2026-04-17T10:00:00
updated_at: 2026-04-17T10:00:00
---

## Summary
One-paragraph synthesis generated by the agent.

## Key Claims
- Claim 1 (confidence: 0.9) — supports [[RAG]]
- Claim 2 (confidence: 0.7)

## Sources
- [[raw/paper-graph-rag-2024.pdf]] — ingested 2026-04-17
```

### 3.5 Knowledge Graph Schema (Kùzu)

```cypher
-- Node types
CREATE NODE TABLE Concept (
    slug STRING PRIMARY KEY,
    title STRING,
    entity_type STRING,
    summary STRING,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Edge types
CREATE REL TABLE RELATES_TO   (FROM Concept TO Concept);
CREATE REL TABLE CONTRADICTS  (FROM Concept TO Concept);
CREATE REL TABLE SUPPORTS     (FROM Concept TO Concept);
CREATE REL TABLE DERIVED_FROM (FROM Concept TO Concept);
```

Kùzu is always rebuilt from the `wiki/` YAML frontmatter. It is never written to directly by the agent — `writer.py` writes MD, then `db.py` syncs from MD.

### 3.6 SQLite Schema (`queue.sqlite`)

```sql
-- Job queue
CREATE TABLE jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_path    TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    retries     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- FTS5 search index
CREATE VIRTUAL TABLE wiki_fts USING fts5(
    slug,
    title,
    content,          -- full .md body text
    aliases,
    tags,
    tokenize = 'unicode61'
);

-- Token usage log (for monitoring Ollama costs/context)
CREATE TABLE llm_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task            TEXT,
    prompt_tokens   INTEGER,
    completion_tokens INTEGER,
    model           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## 4. Query Flow

```
User query (CLI or Streamlit)
        │
        ▼
[fts.py]
FTS5 BM25 search → top-N candidate node slugs
        │
        ▼
[graph/queries.py]
Kùzu: expand from candidates via BFS (depth 2)
collect subgraph: nodes + typed edges
        │
        ▼
[agent/client.py]
LLM synthesis prompt:
  system: "You are a research assistant. Answer using ONLY the provided context."
  context: serialized subgraph (node summaries + relationship map)
  query: user question
        │
        ├──► answer returned to user
        │
        └──► [agent/extractor.py]
             InsightDecision: is this a novel synthesis not present in any source node?
             if yes → writer.py creates new linked node in wiki/
```

---

## 5. Linter

Triggered via `kbweaver lint` or cron.

| Check | Method | Output |
|---|---|---|
| Duplicate nodes | FTS5 similarity + LLM confirm | `MergeProposal` list for user review |
| Orphan nodes | Kùzu: nodes with degree 0 | List of slugs + suggested connections |
| Contradictions | YAML `contradicts` edges | Formatted diff report |
| Broken wiki-links | Regex scan of all `.md` files | List of dangling `[[links]]` |
| Graph health | Kùzu: node count, edge density, largest component | Summary table |

Linter never auto-modifies — it produces a report. User confirms merges explicitly via CLI prompt.

---

## 6. CLI (`kbweaver`)

Built with **Typer**.

```
kbweaver ingest <file>         # manually ingest a single file
kbweaver worker                # start the background queue worker
kbweaver watch                 # start the filesystem watcher
kbweaver query "<text>"        # run a graph-augmented query
kbweaver lint                  # run full linter report
kbweaver rebuild               # rebuild Kùzu + FTS5 from wiki/ directory
kbweaver status                # show job queue stats + graph health
kbweaver serve                 # start optional Streamlit UI
```

`kbweaver watch` and `kbweaver worker` are designed to run as separate processes (or tmux panes), keeping concerns separated. A systemd user service file is provided for both.

---

## 7. Error Handling & Resilience

| Failure scenario | Behaviour |
|---|---|
| Ollama timeout / unavailable | Job retried up to 3 times with exponential backoff; marked `failed` after limit |
| unstructured.io parse error | Job marked `failed`; original file untouched; error logged |
| Writer produces invalid YAML | Validated against `WikiNode` Pydantic model before write; rejected if invalid |
| Kùzu write failure | Non-fatal; `kbweaver rebuild` recovers from MD files |
| FTS5 index drift | `kbweaver rebuild` re-indexes all MD files atomically |
| Crash during processing | Job remains `processing` on restart; worker resets stale `processing` jobs on boot |

---

## 8. Development Setup

```bash
# Clone and set up with uv
git clone <repo>
cd kbweaver
uv sync

# Pull model
ollama pull gemma4

# Initialise databases
uv run kbweaver rebuild --init

# Start services (two panes)
uv run kbweaver watch
uv run kbweaver worker

# Drop a file and watch it process
cp ~/Downloads/paper.pdf raw/
uv run kbweaver status
```

---

## 9. Configuration (`config.py`)

All configuration via environment variables, with `.env` file support (Pydantic Settings).

```
SYNTHWIKI_RAW_DIR=./raw
SYNTHWIKI_WIKI_DIR=./wiki
SYNTHWIKI_DB_DIR=./db
SYNTHWIKI_LOG_LEVEL=INFO

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4
OLLAMA_TIMEOUT=60
OLLAMA_MAX_RETRIES=3

CHUNK_MAX_TOKENS=512
CHUNK_OVERLAP_TOKENS=64

FTS_CANDIDATE_LIMIT=5
GRAPH_BFS_DEPTH=2
WORKER_POLL_INTERVAL=2          # seconds
JOB_STALE_TIMEOUT=300           # seconds before 'processing' job is reset
```

---

## 10. Upgrade Path

| Trigger | Action |
|---|---|
| Wiki exceeds ~10k nodes | Add `sqlite-vec` extension; embed node summaries; upgrade resolver to use vector similarity before LLM confirmation |
| Need cross-lingual matching (BG + EN) | Add multilingual embedding model via Ollama; plug into resolver alongside FTS5 |
| Need concurrent ingestion | Replace SQLite queue with `arq` (Redis-backed); keep all other components unchanged |
| Need multi-machine access | Expose FastAPI layer over query + linter endpoints; wiki/ synced via rclone |