# System Architecture Document (SAD)
**Project:** KBWeaver — Self-Organizing Personal Knowledge Engine
**Version:** 1.1
**Status:** Draft
**Owner:** [Your Name]
**Last Updated:** 2026-04-18
**Depends on:** PRD v1.0

---

## 1. Core Principles

Every architectural decision in this project is governed by three rules, in priority order:

1. **Markdown is the source of truth.** The graph database and search index are derived
   artifacts. Deleting them and running `kbweaver rebuild` must restore the system fully
   from the `wiki/` folder alone.

2. **Local-first, always.** No data leaves the machine. The system must work fully
   offline with a local LLM. Cloud LLM backends are an optional upgrade, never a
   requirement.

3. **Zero-maintenance by design.** Automation should be the default path, not the
  opt-in path. The user should never be required to manually update indexes, relink
  nodes, or run cleanup after ingestion.
  
4. **Composability over monolith.** Each subsystem (ingestion, agent, graph, search,
  interface) is independently replaceable. Swapping the LLM backend or the graph
  engine should not require changes to other subsystems.

---

## 2. Directory Layout

```
kbweaver/
├── raw/        # Drop zone. User places files here. Originals are never modified.
├── archive/    # Processed originals are moved here after ingestion.
├── wiki/       # All knowledge lives here as .md files. Source of truth.
└── db/
    ├── search.db   # SQLite FTS5 full-text index. Derived. Rebuildable.
    └── graph/      # Kùzu graph database. Derived. Rebuildable.
```

The `wiki/` folder is a valid Obsidian vault. No configuration or adapter is required
to open it.

---

## 3. Data Flow

```
User drops file into raw/
        │
        ▼
[Ingestion Engine]
  unstructured.io parses the file → plain text chunks
        │
        ▼
[Agent]
  For each chunk:
    1. Extract concept names
    2. Query FTS5 → find existing matching nodes
    3. LLM confirms match or creates a new node
    4. Write or update .md file in wiki/
    5. Inject typed wiki-links into related nodes
        │
        ▼
[Index Sync]
  SQLite FTS5 updated
  Kùzu graph updated
  Original file moved to archive/
        │
        ▼
wiki/ is queryable via CLI or Obsidian
```

---

## 4. Technology Choices

| What | How | Why |
|---|---|---|
| Document parsing | `unstructured.io` (local) | Handles PDF, DOCX, HTML, TXT, code — no API calls |
| File watching | `watchdog` | Lightweight daemon; detects new files in `raw/` automatically |
| LLM inference | Ollama — Llama 3 8B or Mistral 7B | Fully local; NPU/iGPU offload on supported hardware |
| Full-text search | SQLite FTS5 via Python `sqlite3` | Zero dependencies; BM25 built-in; fast at personal-wiki scale |
| Knowledge graph | Kùzu (embedded) | No Docker, no server; Python-native API; files in `db/graph/` |
| Wiki storage | Local `.md` files | Plain text; works in Obsidian, Logseq, or any editor |
| Orchestration | Python + LangChain or LlamaIndex | Standard agentic loop tooling |
| Primary interface | Python CLI | Scriptable; cron-compatible; no UI dependency |
| Optional UI | Streamlit | Local browser interface if CLI is not enough |

**On the choice of SQLite FTS5 over a vector store:** At up to ~5,000 nodes, BM25
full-text search is faster and more predictable than semantic embeddings for entity
resolution and query entry. A vector index would become a second source of truth that
drifts from the Markdown files on direct edits, which violates Core Principle 1.
If the wiki grows beyond ~10,000 nodes, `sqlite-vec` can be added as a SQLite extension
without changing anything else in the architecture.

---

## 5. Subsystems

### 5.1 Ingestion Engine
Watches `raw/` for new files. Parses and chunks them. Passes chunks to the Agent.
Moves originals to `archive/` on success. Leaves failed files in `raw/` for retry.
Detailed specification: see TECHSPEC-ingestion.md.

### 5.2 Agent (Ontology Builder)
The core intelligence. Resolves concepts from text chunks against existing wiki nodes,
then creates or updates `.md` files. Never deletes nodes autonomously.
Detailed specification: see TECHSPEC-agent.md.

### 5.3 Query Engine
Accepts a natural-language query. Uses FTS5 to find entry-point nodes, traverses the
Kùzu graph for connected context, and synthesizes a cited answer via the LLM.
Detailed specification: see TECHSPEC-query-linter.md.

### 5.4 Linter
Periodic maintenance agent. Detects duplicates, orphan nodes, and contradictory claims.
Produces a report and applies fixes only on explicit user confirmation.
Detailed specification: see TECHSPEC-query-linter.md.

---

## 6. Recoverability

Delete the entire `db/` directory. Run `kbweaver rebuild`. The system must return
to a fully functional state with identical query output. This is a hard requirement,
verified as part of the integration test suite.

---

## 7. Out of Scope (v1)

- Vector embeddings or semantic search
- Multi-user or collaborative access
- Cloud deployment or sync
- Model fine-tuning on the wiki corpus
- Windows support (`unstructured.io` local mode has Linux/macOS dependencies)