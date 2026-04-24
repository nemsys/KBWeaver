# Product Requirements Document (PRD)


**Project:** KBWeaver — Self-Organizing Personal Knowledge Engine
**Version:** 1.0
**Status:** Draft
**Owner:** SciScend
**Last Updated:** 2026-04-17\


---


## 1. Product Vision


### 1.1 Problem Statement


Knowledge workers who process large volumes of unstructured information — research papers, articles, notes, code, web clippings — have no good tool that actively organizes that information for them. Existing popular tools (wikis, note apps, bookmarking services, etc. See: [COMPETITIVE_LANDSCAPE](./COMPETITIVE_LANDSCAPE.md)) are passive: they store what you put in, but they never synthesize, interlink, or surface what you're missing. The cognitive overhead of maintaining structure manually defeats the purpose.


### 1.2 Vision Statement


KBWeaver is an autonomous, self-evolving personal knowledge engine that acts as an active research partner. It continuously transforms raw, unstructured inputs into a structured, interconnected knowledge base — with no manual maintenance overhead.


### 1.3 Project Lineage


KBWeaver builds directly on the *LLM Wiki* concept published by Andrej Karpathy
in April 2026. Karpathy's core insight — that an LLM should act as a compiler,
building a persistent structured wiki from raw sources rather than rediscovering
knowledge from scratch on every query — is the intellectual foundation of this project.


His published concept is intentionally minimal: an idea specification without ingestion
automation, entity resolution, a queryable graph layer, or a maintenance agent.
KBWeaver's scope is defined by precisely those gaps.


### 1.4 Design Principles


- **Autonomy over manual effort:** The system should handle organizing, linking, and updating knowledge without user intervention.
- **Active over passive:** The system surfaces gaps, contradictions, and insights — it does not wait to be queried.
- **Openness and portability:** All data lives in plain text files on the user's own machine. No Vendor Lock-in. No cloud dependency (Cloud LLM backends are an optional upgrade).Data privacy by default.


---


## 2. Target Audience


### 2.1 Primary User


Individual researchers, developers, and knowledge professionals who:


- Regularly consume large volumes of complex, unstructured content
- Need to synthesize information across many sources over time
- Are technically capable of running a local CLI tool
- Have been frustrated by the overhead of maintaining a traditional wiki or Zettelkasten manually


### 2.2 Out of Scope


- Teams or collaborative use cases (no multi-user support in v1)
- Non-technical users who cannot operate a command-line interface
- Cloud-hosted or SaaS deployment


---


## 3. User Workflows


### 3.1 Ingesting Raw Content


**Goal:** The user should be able to drop any document into a folder and trust that it will be processed without any further action required.


**Workflow:**


1. User places a raw file (PDF, Word document, plain text, code file, web clipping) into the designated input folder.
2. The system detects the new file automatically.
3. The file is parsed, normalized, and archived. The original is never modified.
4. The system confirms successful ingestion to the user and write consise report.


**Success criteria:**


- No manual steps required after dropping the file.
- Original file is preserved exactly as dropped.
- Processing completes within a reasonable time for a typical 20-page document.


---


### 3.2 Autonomous Knowledge Organization


**Goal:** New content should be automatically integrated into the existing knowledge base — concepts extracted, linked to related existing content, and filed as structured notes.


**Workflow:**


1. After ingestion, the system identifies key concepts and claims in the new content.
2. It checks whether each concept already exists in the knowledge base.
3. For known concepts: the existing note is updated with new context and a citation to the source.
4. For new concepts: a new structured note is created and linked to related existing notes.
5. Relationships between concepts are recorded (e.g., *supports*, *contradicts*, *derived from*).


**Success criteria:**


- New concepts are consistently identified and filed.
- Existing concepts are correctly recognized even when phrased differently (aliases, paraphrases).
- All notes remain valid and openable in standard Markdown editors after processing.


---


### 3.3 Querying & Insight Generation


**Goal:** The user can ask a natural-language question and receive a synthesized, well-grounded answer that goes beyond what any single note contains.


**Workflow:**


1. User submits a query via CLI or local web interface.
2. The system retrieves the most relevant notes and their connected context from the knowledge base.
3. An answer is synthesized across multiple sources, with citations.
4. If the answer represents a genuinely novel insight not already captured in the knowledge base, the system files it as a new linked note automatically.


**Success criteria:**


- Answers are grounded in actual content from the knowledge base, not hallucinated.
- Sources are cited clearly so the user can verify.
- Novel insights are filed back without duplicating existing content.


---


### 3.4 Knowledge Base Maintenance


**Goal:** The knowledge base should stay clean, consistent, and connected over time — without the user having to audit it manually.


**Workflow:**


1. User triggers a maintenance check (manually via CLI, or on a schedule).
2. The system reports:- Duplicate or near-duplicate notes that could be merged


- Orphan notes with no connections to the rest of the knowledge base
- Contradictory claims across different sources, flagged for user review
- Overall health metrics (size, density of connections, isolated clusters)


1. The user reviews suggestions and approves or dismisses each one.


**Success criteria:**


- Duplicates and orphans are reliably detected.
- Contradictions are surfaced without requiring the user to read every note.
- Health metrics give a meaningful picture of knowledge base quality at a glance.


---


## 4. Non-Functional Requirements


| Requirement                    | Target                                                                            |
| ------------------------------ | --------------------------------------------------------------------------------- |
| Processing latency (ingestion) | < 60 seconds for a typical 20-page document                                       |
| Query response time            | < 15 seconds end-to-end                                                           |
| Knowledge base scale (v1)      | Up to ~5,000 notes                                                                |
| Privacy                        | Local by default; cloud LLM backends are opt-in and require explicit config       |
| Data portability               | All notes readable in Obsidian, Logseq, or any Markdown editor with no conversion |
| Supported input formats        | PDF, DOCX, TXT, HTML, common code file extensions                                 |


---


## 5. Out of Scope (v1)


- Real-time collaborative editing or multi-user access
- Mobile interface
- Cloud sync or backup (user manages their own backup)
- Support for non-English content (considered for a future version)


*Note: For technical and architectural exclusions (e.g., vector embeddings, Windows support), see [ARCHITECTURE.md](./ARCHITECTURE.md).*
