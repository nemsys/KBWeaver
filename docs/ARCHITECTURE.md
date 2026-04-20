# System Architecture Document (SAD)
**Project:** KBWeaver — Self-Organizing Personal Knowledge Engine
**Version:** 1.0
**Status:** Draft
**Owner:** [Your Name]
**Last Updated:** 2026-04-18
**Depends on:** PRD v1.0

---

## 1. Architecture Goals & Constraints

### 1.1 Governing Principles
These principles take precedence over any individual technology choice. If a decision
conflicts with one of these, it must be explicitly justified.

- **Local-first, always.** No data leaves the machine. No external API calls for
  core functionality. Cloud LLM providers (e.g., Claude, Gemini) may be supported
  as optional backends, but the system must function fully offline with a local model.
- **Markdown is the source of truth.** The graph database and search index are derived,
  rebuildable artifacts. If they are deleted, a single rebuild command must restore
  them from the Markdown files alone. Nothing critical lives only in a database.
- **Zero-maintenance by design.** Automation should be the default path, not the
  opt-in path. The user should never be required to manually update indexes, relink
  nodes, or run cleanup after ingestion.
- **Composability over monolith.** Each subsystem (ingestion, agent, graph, search,
  interface) is independently replaceable. Swapping the LLM backend or the graph
  engine should not require changes to other subsystems.

### 1.2 Non-Functional Requirements

| Concern | Target | Notes |
|---|---|---|
| Ingestion latency | < 60s for a 20-page document | On a mid-range laptop with a local 8B model |
| Query latency | < 15s end-to-end | FTS entry + graph traversal + LLM synthesis |
| Knowledge base scale | Up to ~5,000 nodes (v1) | BM25 remains effective at this scale |
| Privacy | Zero egress | Verified at the network layer; no telemetry |
| Recoverability | Full rebuild from Markdown only | Graph and index are derived artifacts |
| Editor compatibility | Obsidian, Logseq, VSCode | No adapter or conversion layer required |

---

## 2. System Overview

KBWeaver is composed of five loosely coupled subsystems communicating through the
filesystem and two derived indexes. The Markdown wiki is the central artifact that
all subsystems read from or write to.