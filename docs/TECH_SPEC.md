# Technical Specification
**Project:** KBWeaver — Self-Organizing Personal Knowledge Engine
**Version:** 1.1
**Status:** Draft
**Owner:** SciScend
**Last Updated:** 2026-04-24
**Depends on:** PRD v1.1, SAD v1.2
**Changelog:** v1.1 — Kùzu removed; all graph operations migrated to SQLite adjacency tables in `search.db`; LLM model recommendation split by pipeline stage; per-subsystem timing added per SAD §7.

---

## 1. Wiki Node Format

Every concept in the knowledge base is a single `.md` file. This schema is the
contract between all subsystems. All components — the Agent, the Query Engine,
the Linter, and the index rebuild command — must read and write nodes in this format.

### 1.1 YAML Frontmatter Schema

```yaml
---
id: concept-slug                         # Required. Matches the filename stem. Lowercase, hyphenated.
title: "Concept Title"                   # Required. Human-readable name.
aliases: ["alternate name", "acronym"]   # Optional. Used by entity resolution to detect duplicates.
created: 2026-04-18T10:00:00             # Required. Set on creation, never updated.
updated: 2026-04-18T10:00:00             # Required. Updated on every write.
sources:
  - "[[archive/source-document.pdf]]"   # Wiki-link to the archived original. One entry per source.
relations:
  - type: supports                       # Typed edge. See allowed types below.
    target: "[[Another Concept]]"
  - type: contradicts
    target: "[[Conflicting Concept]]"
tags: [domain, subtopic]                 # Optional. Free-form lowercase tags.
---
```

**Allowed relation types:**

| Type           | Meaning                                                 |
| -------------- | ------------------------------------------------------- |
| `supports`     | This concept provides evidence for the target           |
| `contradicts`  | This concept conflicts with or refutes the target       |
| `derived_from` | This concept is a refinement or extension of the target |
| `relates_to`   | General association; use when no stronger type applies  |

### 1.2 Body Format

```markdown
# Concept Title

Body text written by the Agent. Plain Markdown prose. No special syntax required.

## Related Concepts

- [[Linked Concept]] — one-line rationale for the link

## Sources
- [[archive/source-document.pdf]] — optional context note
```

**Why relations appear in both YAML and the body:**
- YAML `relations` block: machine-readable typed edges consumed by the adjacency tables in `search.db` and by the Linter.
- `[[wiki-links]]` in the body: human navigation, compatible with Obsidian Graph View.

Both must be kept in sync by the Agent on every write.

---

## 2. Data Schemas

### 2.1 SQLite FTS5 Index

Database file: `db/search.db`

```sql
CREATE VIRTUAL TABLE fts_nodes USING fts5(
    id,           -- Matches the YAML id field and filename stem
    title,        -- Matches the YAML title field
    aliases,      -- Space-separated alias list from YAML
    body,         -- Full Markdown body text (frontmatter stripped)
    tags,         -- Space-separated tag list from YAML
    tokenize = 'porter unicode61'
);
```

All five columns are indexed and searchable. Queries against `title` and `aliases`
are used for entity resolution. Queries against `body` are used for the Query Engine
entry point.

The index is updated on every `.md` write by the Agent. It is never written to directly
— only the Agent writes `.md` files, which then trigger index updates.

### 2.2 Graph Adjacency Tables

Database file: `db/search.db` (same file as FTS5 index — no secondary directory or external process)

```sql
CREATE TABLE nodes (
    id    TEXT PRIMARY KEY,   -- slug derived from note title; matches YAML id and filename stem
    title TEXT NOT NULL,
    path  TEXT NOT NULL       -- relative path within wiki/
);

CREATE TABLE edges (
    src      TEXT NOT NULL,   -- node id
    dst      TEXT NOT NULL,   -- node id
    rel_type TEXT NOT NULL    -- supports | contradicts | derived_from | relates_to
);

CREATE INDEX idx_edges_src ON edges(src);
CREATE INDEX idx_edges_dst ON edges(dst);
```

The graph is populated by parsing the `relations` block in YAML frontmatter.
Graph traversal is in-process BFS over an adjacency list loaded from these tables.
The entire `db/` directory is derived state — deleting it and running `kbweaver rebuild`
restores full functionality from `wiki/` alone.

---

## 3. Ingestion Engine

### 3.1 File Watcher

Library: `watchdog`
Monitored path: `raw/`
Events handled: `FileCreatedEvent`, `FileMovedEvent` (into `raw/`)

On detection, the watcher places the file path into an in-memory queue.
A worker thread consumes the queue serially — one file at a time — to avoid
concurrent LLM calls competing for memory.

### 3.2 Supported Input Formats

Parsed by `unstructured.io` in local mode (no API calls):

| Format     | Notes                                                      |
| ---------- | ---------------------------------------------------------- |
| PDF        | Text extraction; layout-aware where possible               |
| DOCX       | Full text including headings and tables                    |
| HTML       | Body text extracted; boilerplate stripped                  |
| TXT        | Passed through directly                                    |
| Markdown   | Passed through; frontmatter stripped before chunking       |
| Code files | `.py`, `.js`, `.ts`, `.go`, `.rs`, `.sh`, `.yaml`, `.json` |

Unsupported formats: the file is moved to `archive/unsupported/` and the event
is logged. No error is raised to the user beyond the log entry.

### 3.3 Chunking Strategy

Target chunk size: **500–800 tokens.**

Chunking respects the following boundaries in priority order:
1. Section headings (Markdown `#`, `##`, `###` or DOCX heading styles)
2. Paragraph breaks
3. Sentence boundaries (fallback if a paragraph exceeds 800 tokens)

Chunks smaller than 50 tokens are merged with the next chunk rather than
processed alone, to avoid trivial agent calls on headings or captions.

### 3.4 Failure Handling

| Failure                  | Behaviour                                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------------------------- |
| Parsing fails            | File stays in `raw/`. Error logged. No data loss.                                                        |
| Agent fails mid-document | Completed nodes retained. Checkpoint file written to `logs/`. Re-run resumes from last successful chunk. |
| Index update fails       | Logged as a warning. `kbweaver rebuild` recovers consistency.                                            |

### 3.5 Ingestion Report

Emitted on completion of every file. Written to stdout and appended to `logs/ingestion.log`.

```
KBWeaver Ingestion Report — 2026-04-24T10:00:00
================================================
Source:            quarterly-review.pdf
Chunks processed:  34
Nodes created:     8
Nodes updated:     12
Edges added:       19

Timing
  Parse:            3.2s
  Entity resolution: 41.4s   (LLM: llama3.2:3b, 34 calls)
  Index sync:        0.3s
  Total:            44.9s
```

Timing is reported per stage so the user can identify which component to swap
if latency is unacceptable on their hardware (see PRD §4.2).

---

## 4. Agent (Ontology Builder)

### 4.1 LLM Backend Interface

The Agent communicates with the LLM through an abstract provider interface.
Swapping backends requires only a config change, not code changes.

```python
class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> str: ...
```

Supported backends:

| Backend           | Config key      | Privacy                  |
| ----------------- | --------------- | ------------------------ |
| Ollama (local)    | `ollama`        | Full — no egress         |
| Anthropic Claude  | `anthropic`     | Cloud — requires API key |
| OpenAI-compatible | `openai_compat` | Cloud — requires API key |

Default: `ollama`.

**Model selection by pipeline stage:**

| Stage                          | Recommended model | Rationale                                                                                                                                                             |
| ------------------------------ | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Entity resolution (§4.2)       | `llama3.2:3b`     | Repetitive structured classification; throughput matters more than reasoning depth. Benchmark against `llama3:8b` before committing — use 3B if accuracy is adequate. |
| Answer synthesis (§5.1 step 4) | `llama3:8b`       | Cross-note reasoning; quality matters more than speed.                                                                                                                |

Mistral 7B (Apache 2.0) is an alternative for either stage if the Meta Community License is a constraint.
Both models are configured separately — see §8.

### 4.2 Entity Resolution Algorithm

Run once per text chunk using the entity resolution model:

```
1. EXTRACT
   Prompt the LLM with the chunk text.
   Output: list of candidate concept names found in the chunk.

2. LOOKUP
   For each candidate concept name:
     Query FTS5: SELECT id, title, aliases FROM fts_nodes WHERE fts_nodes MATCH '<name>'
     Take top 5 results by BM25 rank.

3. CONFIRM
   If FTS5 returns candidates:
     Prompt the LLM: "Is '<candidate name>' the same concept as '<existing title>'?
     Consider aliases: <aliases>. Answer YES or NO."
     If YES → existing node confirmed. Proceed to UPDATE.
     If NO for all candidates → proceed to CREATE.
   If FTS5 returns no candidates:
     Proceed directly to CREATE.

4. CREATE or UPDATE
   CREATE: generate a new .md file with YAML frontmatter and body.
   UPDATE: append new context to the body; add new source to YAML sources list;
           update the `updated` timestamp.

5. LINK
   Prompt the LLM to identify relationships between the concepts touched in this chunk.
   For each identified relationship:
     Add a typed entry to the YAML `relations` block of both nodes (bidirectional).
     Add a [[wiki-link]] to the body of both nodes.

6. SYNC
   Update FTS5 index for all touched nodes.
   Update adjacency tables (nodes + edges) in search.db for all new or modified edges.
```

### 4.3 Agent Constraints

- The Agent **never deletes nodes.** Deletion is a Linter action requiring explicit
  user confirmation.
- All writes go to `.md` files first. Index and graph updates are always secondary.
- Every run produces a log entry in `logs/` with: timestamp, input file,
  chunks processed, nodes created, nodes updated, edges added.

---

## 5. Query Engine

### 5.1 Query Flow

```
1. SEARCH
   User query string → FTS5 full-text search against fts_nodes
   Returns: top-k node IDs ranked by BM25 (default k=5)

2. TRAVERSE
   For each entry-point node:
     Load adjacency list from edges table in search.db
     BFS traversal up to depth 2
     Collect all connected nodes and their relation types
   Deduplicate collected node set.

3. ASSEMBLE CONTEXT
   For each node in the collected set:
     Load title, body, and relation metadata from .md file
   Concatenate into a structured context block with relation annotations.

4. SYNTHESIZE
   Prompt the synthesis LLM (llama3:8b) with:
     - The user's original query
     - The assembled context block
   Instruction: "Answer using only the provided context. Cite sources by node title."
   Output: answer text with inline citations.

5. NOVELTY CHECK (optional, configurable)
   Prompt the LLM: "Does this answer introduce a concept not already present
   in the provided context nodes?"
   If YES → Agent creates a new linked node for the insight.
   If NO → answer returned as-is.

6. REPORT
   Query latency reported per stage:
     FTS5 lookup, graph traversal, context assembly, LLM synthesis.
```

### 5.2 Query Parameters (configurable via CLI flags or config file)

| Parameter       | Default | Description                                       |
| --------------- | ------- | ------------------------------------------------- |
| `fts_top_k`     | 5       | Number of FTS5 entry-point nodes                  |
| `graph_depth`   | 2       | BFS traversal depth from entry nodes              |
| `novelty_check` | true    | Whether to run the novelty check step             |
| `file_insights` | true    | Whether to file novel insights back into the wiki |

---

## 6. Linter

### 6.1 Checks

| Check                  | Method                                                                                     | Output                    |
| ---------------------- | ------------------------------------------------------------------------------------------ | ------------------------- |
| Duplicate nodes        | FTS5 title+alias similarity, confirmed by LLM                                              | Merge proposals           |
| Orphan nodes           | `SELECT id FROM nodes WHERE id NOT IN (SELECT src FROM edges UNION SELECT dst FROM edges)` | List with suggested links |
| Contradictory claims   | LLM cross-referencing nodes connected by `contradicts` edges                               | Review queue              |
| Disconnected subgraphs | In-process connected-components over adjacency list loaded from edges table                | Cluster report            |
| Stale nodes            | Nodes with `updated` > 90 days ago and zero incoming edges                                 | Archival candidates       |

### 6.2 Report Format

```
KBWeaver Lint Report — 2026-04-24T10:00:00
==========================================
Total nodes:              1,247
Total edges:              4,832
Avg. edges per node:      3.87

Orphan nodes:             23    [run: kbweaver lint --apply orphans]
Duplicate candidates:      7    [run: kbweaver lint --apply duplicates]
Contradictions flagged:    4    [manual review required]
Disconnected clusters:     2    [largest: 12 nodes — topic: "audio-synthesis"]
Stale nodes:               9    [run: kbweaver lint --apply stale]

Timing:                    8.3s
```

### 6.3 Interactive Apply Mode

`kbweaver lint --apply` presents each suggestion one at a time:

```
[1/7] DUPLICATE CANDIDATE
  "Transformer Architecture" (wiki/transformer-architecture.md)
  "Attention Mechanism in Transformers" (wiki/attention-mechanism-in-transformers.md)
  Similarity score: 0.91

  Action? [m]erge / [k]eep both / [s]kip  →
```

Merge writes a combined node and removes the source node. Keep both adds an explicit
`relates_to` edge between them to suppress future duplicate detection.

---

## 7. CLI Specification

```
kbweaver watch
  Start the background file watcher daemon.
  Monitors raw/ and processes new files automatically.

kbweaver ingest <path>
  Manually trigger ingestion for a single file.
  Bypasses the watcher; useful for testing or one-off imports.

kbweaver query "<question>"
  Submit a natural-language query.
  Flags:
    --depth INT      Override graph_depth for this query (default: 2)
    --top-k INT      Override fts_top_k for this query (default: 5)
    --no-file        Disable filing of novel insights for this query

kbweaver lint
  Run all maintenance checks and print the report.
  No changes are made.

kbweaver lint --apply [check]
  Run checks interactively and apply confirmed suggestions.
  Optional [check]: orphans | duplicates | stale | all (default: all)

kbweaver rebuild
  Rebuild all derived state in db/search.db from wiki/ files.
  Equivalent to: kbweaver rebuild-index && kbweaver rebuild-graph

kbweaver rebuild-index
  Rebuild only the FTS5 virtual table in search.db.

kbweaver rebuild-graph
  Rebuild only the nodes and edges adjacency tables in search.db.

kbweaver status
  Print a one-page graph health summary (node count, edge count,
  orphan count, last ingestion timestamp).
```

---

## 8. Configuration

All runtime parameters are read from `kbweaver.toml` in the project root.
CLI flags override config file values.

```toml
[llm]
backend = "ollama"
base_url = "http://localhost:11434"

[llm.entity_resolution]
model = "llama3.2:3b"    # Used by Agent (§4.2). Swap to llama3:8b if accuracy is inadequate.

[llm.synthesis]
model = "llama3:8b"      # Used by Query Engine (§5.1 step 4).

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
```****