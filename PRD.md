# Product Requirements Document (PRD)
**Project:** KBWeaver — Self-Organizing Personal Knowledge Engine
**Status:** Draft\
**Objective:** Build a self-maintaining, continuously evolving personal knowledge management system that autonomously synthesizes unstructured inputs into a structured, interconnected ontology.

---

## 1. Product Vision & Scope

### 1.1 Product Vision
An autonomous, self-evolving knowledge engine that acts as an active research partner. Instead of serving as a static repository, the system autonomously processes raw data, extracts conceptual entities, maps relationships via a knowledge graph, and actively identifies content gaps to accelerate continuous learning and ideation.

### 1.2 Target Audience & Core Use Case
Designed for individual researchers, developers, and professionals who process large volumes of complex, unstructured information and need to synthesize it into structured, actionable ontologies — without the manual overhead of traditional wiki maintenance.

### 1.3 Core Value Proposition
- **Zero-Maintenance Architecture:** An autonomous LLM agent handles summarizing, interlinking, and updating Markdown files with no manual bookkeeping.
- **Structural Awareness:** A knowledge graph provides a top-down view of the entire dataset, going beyond flat semantic search.
- **Active Insight Generation:** The system shifts from passive retrieval to active ideation, autonomously surfacing knowledge gaps and structural improvements.
- **No Vendor Lock-in:** All data lives in plain Markdown files on local disk, fully usable in Obsidian, Logseq, or VSCode without any intermediary service.

---

## 2. User Workflows

### 2.1 Omnivorous Ingestion (Raw → Normalized)
- **Trigger:** User drops a raw file (PDF, `.docx`, `.txt`, code, web clipping) into the local `raw/` directory.
- **Action:** A background watcher detects the file, extracts raw text via `unstructured.io`, normalizes it to Markdown, and archives the original immutably.

### 2.2 Autonomous Ontology Extraction & Graph Synthesis
- **Trigger:** Automated on successful ingestion.
- **Action:**
  - **Entity Resolution:** The LLM agent identifies key concepts and claims in the new content. It queries the full-text search index to find candidate existing nodes, then confirms or rejects matches, handling aliases and paraphrases.
  - **Node Creation:** New concepts get a standalone `.md` page. Existing nodes are appended with new context and a citation to the source file.
  - **Edge Creation:** The agent injects bidirectional wiki-links (`[[Concept]]`) into relevant nodes.
  - **Metadata Tagging:** YAML frontmatter is generated or updated with relationship types (e.g., `relates_to`, `contradicts`, `supports`, `derived_from`).
  - **Index Sync:** The SQLite FTS5 index and Kùzu graph are updated atomically with any new or modified nodes.

### 2.3 Graph-Augmented Querying & Ideation
- **Trigger:** User submits a query via CLI or local web UI.
- **Action:**
  - The SQLite FTS5 index provides the semantic entry point — returning ranked candidate nodes for the query.
  - The system traverses the Kùzu knowledge graph from those entry nodes, collecting connected nodes and their relationship context.
  - The LLM synthesizes a comprehensive answer grounded in the retrieved subgraph.
  - If the synthesized answer represents a genuinely novel insight, the system autonomously formats and files it back into the wiki as a new linked node.

### 2.4 Autonomous Maintenance (Linter)
- **Trigger:** CLI command or scheduled cron job.
- **Action:**
  - Detects and proposes merges for duplicate or near-duplicate nodes.
  - Flags orphan nodes (concepts with no graph connections).
  - Highlights contradictory claims across different sources for user review.
  - Reports graph health metrics: node count, edge density, largest disconnected subgraphs.

---

## 3. Core Features

### 3.1 File Ingestion & Parsing Engine
- **Directory Watcher:** Lightweight daemon (e.g., `watchdog`) monitoring `raw/`.
- **Universal Parser:** `unstructured.io` for PDF, DOCX, HTML, plain text, and code files.
- **Chunking Strategy:** Semantically meaningful splits before LLM processing, respecting section boundaries where detectable.

### 3.2 AI Ontology Builder (The Agent)
- **Entity Resolution via FTS + LLM:** BM25 candidate retrieval from SQLite FTS5, followed by LLM confirmation. In the future, we may add embedding infrastructure.
- **Markdown Generation:** Clean, consistently formatted `.md` files with YAML frontmatter.
- **Bidirectional Linking:** Native `[[wiki-link]]` style compatible with Obsidian and Logseq.
- **YAML Management:** Dynamic frontmatter properties tracking source citations, relationship types, and timestamps.

### 3.3 Knowledge Graph Engine
- **Backend:** Kùzu (embedded, no Docker, Python-native API).
- **Graph Mapping:** MD wiki-links and YAML metadata are the source of truth; Kùzu is a derived index rebuilt from them on demand.
- **Gap Analysis:** Node centrality calculations and disconnected subgraph detection to surface underexplored areas.

### 3.4 Search Layer
- **Backend:** SQLite FTS5 (built into Python's `sqlite3`, zero external dependencies).
- **Indexing:** All `.md` file content indexed on write; re-indexing triggered automatically by the watcher on any file change.
- **Role:** Primary query entry point and entity resolution candidate generator. Replaces the vector store entirely at personal-wiki scale.

### 3.5 Open Interoperability
- **Plain Text First:** All structured outputs are local Markdown files. The graph DB and search index are derived, rebuildable artifacts — never the source of truth.
- **Editor Compatible:** The `wiki/` folder is directly usable in Obsidian (with Graph View and Dataview), Logseq, or VSCode with no adapter layer.

---

## 4. System Architecture & Tech Stack

Designed for a fully local, privacy-first architecture
### 4.1 Data Storage Layer

| Layer | Technology | Notes |
|---|---|---|
| Raw files | Local filesystem (`/raw`) | Immutable originals |
| Structured wiki | Local filesystem (`/wiki`, `.md` files) | Source of truth |
| Knowledge graph | **Kùzu** (embedded) | Derived from MD links + YAML; no Docker |
| Search index | **SQLite FTS5** | Derived from MD content; auto-synced |

> **Rationale for no vector DB:** At personal-wiki scale (up to ~5k nodes), BM25 full-text search is faster, more predictable, and lexically more precise than semantic embeddings for entity resolution and query entry. A vector store introduces a second source of truth that drifts from the MD files on direct edits, undermining the zero-maintenance goal. If the wiki grows beyond ~10k nodes or cross-lingual semantic matching becomes necessary, `sqlite-vec` can be added as a SQLite extension without changing the architecture.

### 4.2 Application Logic & AI Layer

| Component | Technology | Notes |
|---|---|---|
| Orchestration | **Python** + LangChain or LlamaIndex | Agentic ingestion, extraction, query loops |
| Local LLM | **Ollama** | Llama 3 8B / Mistral; NPU/iGPU offload |
| Parsing | **unstructured.io** | Local, no external API calls |
| Graph client | **Kùzu Python SDK** | Embedded, no server process |
| Search client | **sqlite3** (stdlib) | FTS5; zero extra dependencies |

### 4.3 Interface Layer

| Interface | Technology | Purpose |
|---|---|---|
| Wiki viewer | **Obsidian** | Graph View, Dataview, daily exploration |
| Control interface | Python CLI | Trigger ingestion, queries, linter |
| Optional web UI | **Streamlit** | Lightweight local UI if CLI is insufficient |

### 4.4 Data Flow Summary

```
raw/ (drop zone)
    │
    ▼
[watchdog watcher]
    │
    ▼
[unstructured.io parser] → normalized text chunks
    │
    ▼
[LLM agent via Ollama]
    ├─ Entity resolution  ◄─── SQLite FTS5 (candidate lookup)
    ├─ Node create/update ────► wiki/ (.md files)  ◄── Obsidian
    └─ Edge injection     ────► Kùzu graph DB (derived index)
                                SQLite FTS5 (search index)
                                    │
                                    ▼
                              [Query / Linter CLI]
                                    │
                                    ▼
                         FTS5 entry → Kùzu traversal → LLM synthesis
                                    │
                                    ▼
                         Novel insight → new .md node → wiki/
```