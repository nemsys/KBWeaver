# System Architecture Document (SAD)

**Project:** KBWeaver — Self-Organizing Personal Knowledge Engine  
**Version:** 1.2  
**Status:** Draft  
**Owner:** SciScend  
**Last Updated:** 2026-04-24  
**Depends on:** PRD v1.1  
**Changelog:** v1.2 — Kùzu replaced by SQLite adjacency tables; orchestration framework decision resolved; LLM model guidance per pipeline stage added; NFR framing aligned with PRD v1.1.

---

## 1. Core Principles

Every architectural decision in this project is governed by the following rules, in priority order:

1. **Markdown is the source of truth.** The graph representation and search index are derived artifacts. Deleting them and running `kbweaver rebuild` must restore the system fully from the `wiki/` folder alone.

2. **Local-first, always.** No data leaves the machine. The system must work fully offline with a local LLM. Cloud LLM backends are an optional upgrade, never a requirement.

3. **Zero-maintenance by design.** Automation should be the default path, not the opt-in path. The user should never be required to manually update indexes, relink nodes, or run cleanup after ingestion.

4. **Composability over monolith.** Each subsystem (ingestion, agent, graph, search, interface) is independently replaceable. Swapping the LLM backend, the parsing library, or the graph representation should not require changes to other subsystems. No performance number in this document is a permanent constraint — it is a starting point from which a component swap is the answer when headroom runs out.

---

## 2. Directory Layout

```
kbweaver/
├── raw/          # Drop zone. User places files here. Originals are never modified.
├── archive/      # Processed originals are moved here after ingestion.
├── wiki/         # All knowledge lives here as .md files. Source of truth.
└── db/
    └── search.db # SQLite database. Contains FTS5 full-text index AND graph adjacency
                  # tables. Derived. Fully rebuildable from wiki/ alone.
```

The `wiki/` folder is a valid Obsidian vault. No configuration or adapter is required to open it.

`db/` is a single SQLite file. There is no embedded graph database server, no secondary directory, no external process. The entire derived state of the system lives in one file that can be deleted and rebuilt at any time.

---

## 3. Technology Choices

| What                      | How                                    | Why                                                                                                                                                                                                                                                                            | License                | Notes                                                                                                                                                                                                                 |
| ------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Document parsing          | `unstructured.io` (local mode)         | Uniform parsing API across PDF, DOCX, HTML, TXT, code — no API calls                                                                                                                                                                                                           | Apache 2.0             | Heavy dependency footprint (poppler, libmagic, tesseract). Acceptable for v1; if setup friction becomes a problem, replace with a thin format router: `pymupdf` for PDF, `python-docx` for DOCX, stdlib for TXT/HTML. |
| File watching             | `watchdog`                             | Lightweight daemon; detects new files in `raw/` automatically                                                                                                                                                                                                                  | Apache 2.0             | —                                                                                                                                                                                                                     |
| LLM inference             | Ollama runtime                         | Fully local; NPU/iGPU offload on supported hardware                                                                                                                                                                                                                            | MIT                    | —                                                                                                                                                                                                                     |
| — synthesis model         | Llama 3 8B (via Ollama)                | Strong general reasoning; used for query synthesis and note generation                                                                                                                                                                                                         | Meta Community License | Not standard OSS; attribution required; free for personal use                                                                                                                                                         |
| — entity resolution model | Llama 3.2 3B (via Ollama), or same 8B  | Entity resolution is a structured, repetitive classification task; a smaller/faster model may meet latency requirements with lower resource cost                                                                                                                               | Meta Community License | Benchmark both before committing. Use the 3B if it resolves entities correctly; use the 8B only if accuracy requires it.                                                                                              |
| Full-text search          | SQLite FTS5 via Python `sqlite3`       | Zero dependencies; BM25 built-in; fast at personal-wiki scale                                                                                                                                                                                                                  | Public Domain          | —                                                                                                                                                                                                                     |
| Graph representation      | SQLite adjacency tables in `search.db` | No external server, no archived dependency, no secondary directory; graph traversal at ≤5,000 nodes is trivial in-process BFS                                                                                                                                                  | Public Domain          | See §3.1 for schema. Replaces Kùzu.                                                                                                                                                                                   |
| Orchestration             | Direct Python implementation           | The ingestion and query pipelines are narrow, well-defined sequences — not generic agent loops. A direct implementation is more auditable, more stable, and has no framework-level opinions about indexing that could conflict with the Markdown-as-source-of-truth principle. | N/A                    | If a framework becomes necessary (e.g. for multi-step tool use), prefer LlamaIndex over LangChain — it is better aligned with knowledge base patterns and has a more stable API surface.                              |
| Primary interface         | Python CLI                             | Scriptable; cron-compatible; no UI dependency                                                                                                                                                                                                                                  | N/A                    | —                                                                                                                                                                                                                     |
| Optional UI               | Streamlit                              | Local browser interface if CLI is not enough                                                                                                                                                                                                                                   | Apache 2.0             | Owned by Snowflake; core library remains OSS                                                                                                                                                                          |

### 3.1 Graph Representation Schema

The graph lives in `search.db` alongside the FTS5 index. Two tables (`nodes`, `edges`), no additional dependency. The full DDL and column-level documentation are defined in [Techspec.md §2.2 — Graph Adjacency Tables](./TECH_SPEC.md#22-graph-adjacency-tables).

Graph traversal is BFS over an in-process adjacency list loaded from these tables. At ≤5,000 nodes this is fast enough to be unnoticeable. If the knowledge base grows significantly beyond that threshold, the same tables support the same queries — the only change would be adding query-level optimisation (depth limits, caching), not a database swap.

### 3.2 On BM25 vs Vector Search

At up to ~5,000 nodes, BM25 full-text search is faster and more predictable than semantic embeddings for entity resolution and query entry. A vector index would become a second source of truth that drifts from the Markdown files on direct edits, which violates Core Principle 1. If the wiki grows beyond ~10,000 nodes, `sqlite-vec` can be added as a SQLite extension without changing anything else in the architecture.

### 3.3 On LLM Model Selection

Two distinct pipeline stages have different requirements:

- **Entity resolution** (ingestion loop, called once per chunk): a classification task with a structured prompt. Throughput matters more than depth of reasoning. Start with Llama 3.2 3B and benchmark against accuracy on real inputs before upgrading to 8B.
- **Answer synthesis** (query engine, called once per query): requires genuine cross-note reasoning. Use Llama 3 8B here. This is where the larger model earns its resource cost.

Mistral 7B (Apache 2.0) remains an option if the Meta Community License is a constraint. Its accuracy on entity resolution tasks is comparable to Llama 3.2 3B.

---

## 4. Data Flow

```
User drops file into raw/
        │
        ▼
[Ingestion Engine]
  watchdog detects new file
  unstructured.io parses → plain text chunks
        │
        ▼
[Agent — Entity Resolution]
  For each chunk:
    1. Extract candidate concept names
    2. Query FTS5 → find existing matching nodes
    3. LLM (3B model) confirms match or flags as new concept
    4. Write or update .md file in wiki/
    5. Inject typed wiki-links into related nodes
        │
        ▼
[Index Sync]
  SQLite FTS5 updated
  SQLite adjacency tables updated
  Original file moved to archive/
        │
        ▼
[Report Generator]
  Ingestion report written:
    - Extracted concepts (new vs. updated)
    - Source metadata (filename, type, timestamp)
    - New wiki-links created
    - Wall-clock time per stage (for observability)
        │
        ▼
wiki/ is queryable via CLI or Streamlit

        [Query Path]
        │
        ▼
[Query Engine]
  FTS5 entry-point lookup
  BFS graph traversal over adjacency tables → connected context
  LLM (8B model) synthesises cited answer
  If answer is a novel insight → filed as new linked note
        │
        ▼
Answer returned to user with citations + query latency reported
```

---

## 5. Subsystems

### 5.1 Ingestion Engine
Watches `raw/` for new files. Parses and chunks them using `unstructured.io`. Passes chunks to the Agent. Moves originals to `archive/` on success. Leaves failed files in `raw/` for retry. On completion, emits a concise ingestion report including per-stage timing.  
Detailed specification: see Techspec.md (Section 3. Ingestion Engine).

### 5.2 Agent (Ontology Builder)
The entity resolution layer. Resolves concepts from text chunks against existing wiki nodes using FTS5, then creates or updates `.md` files. Uses the smaller/faster LLM (3B) by default for this stage. Never deletes nodes autonomously.  
Detailed specification: see Techspec.md (Section 4. Agent).

### 5.3 Query Engine
Accepts a natural-language query. Uses FTS5 to find entry-point nodes, traverses the adjacency tables for connected context, and synthesises a cited answer via the 8B LLM. If the synthesised answer represents a genuinely novel insight not already captured in the knowledge base, the Query Engine files it as a new linked note automatically (see PRD §3.3, step 4). Reports query latency per run.  
Detailed specification: see Techspec.md (Section 5. Query Engine).

### 5.4 Linter
Periodic maintenance agent. Detects duplicates, orphan nodes, and contradictory claims. Produces a report and applies fixes only on explicit user confirmation. Can be triggered manually via CLI or run on a schedule (e.g., cron) — see PRD §3.4.  
Detailed specification: see Techspec.md (Section 6. Linter).

---

## 6. Recoverability

Delete the entire `db/` directory (which contains only `search.db`). Run `kbweaver rebuild`. The system must return to a fully functional state with identical query output. This is a hard requirement, verified as part of the integration test suite.

---

## 7. Observability

Each subsystem boundary must emit timing data. Minimum required instrumentation:

- Ingestion: total wall-clock time, time per stage (parse, entity resolution, index sync)
- Query: total wall-clock time, FTS5 lookup time, LLM synthesis time
- Linter: total wall-clock time, counts of issues detected per category

This is not optional instrumentation. It is the mechanism by which a user decides whether a component swap is warranted (see PRD §4.2). Without it, performance degradation is invisible until it is severe.

---

## 8. Out of Scope (v1)

- Vector embeddings or semantic search (BM25 full-text used instead; `sqlite-vec` is the stated upgrade path)
- Model fine-tuning on the wiki corpus
- Windows support (`unstructured.io` local mode has Linux/macOS dependencies)
- LangChain or LlamaIndex framework (direct Python implementation used; LlamaIndex named as fallback if a framework becomes necessary)

*For product and feature-level exclusions (e.g., mobile interface, multi-user), see PRD v1.1.*