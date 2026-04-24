"""LLM prompt templates for all KBWeaver pipeline stages.

Centralized here so prompt engineering changes don't scatter across modules.
"""

# ---------------------------------------------------------------------------
# Entity Resolution (Agent §4.2 — steps 1, 3, 5)
# ---------------------------------------------------------------------------

EXTRACT_CONCEPTS_SYSTEM = """\
You are a knowledge extraction engine. Your job is to identify distinct concepts, \
entities, and key claims from a text chunk. Output ONLY a JSON array of concept names. \
Each name should be a short, canonical noun phrase (2-5 words). Do not include duplicates. \
Do not include generic terms like "introduction" or "conclusion"."""

EXTRACT_CONCEPTS_USER = """\
Extract the key concepts from the following text chunk. \
Return ONLY a valid JSON array of strings. No explanation.

---
{chunk}
---"""

CONFIRM_MATCH_SYSTEM = """\
You are an entity resolution engine. You decide whether two concept names refer to \
the same underlying concept. Answer with ONLY "YES" or "NO". Nothing else."""

CONFIRM_MATCH_USER = """\
Is "{candidate}" the same concept as "{existing_title}"?
Consider these known aliases: {aliases}

Answer YES or NO."""

# ---------------------------------------------------------------------------
# Note Generation (Agent §4.2 — step 4)
# ---------------------------------------------------------------------------

GENERATE_NOTE_SYSTEM = """\
You are a knowledge base writer. Write a clear, concise Markdown note about the \
given concept based on the provided source text. Use plain prose. Do not use \
bullet points for the main body. Keep it to 1-3 paragraphs. Do not include \
headings, frontmatter, or metadata — just the body text."""

GENERATE_NOTE_USER = """\
Write a concise knowledge base entry about "{concept}" based on this source text:

---
{chunk}
---"""

UPDATE_NOTE_SYSTEM = """\
You are a knowledge base editor. You are given an existing note body and new source \
text. Integrate the new information into the existing note. Preserve existing content. \
Add new facts naturally. Keep it concise. Output ONLY the updated body text — no \
headings, no frontmatter, no metadata."""

UPDATE_NOTE_USER = """\
Existing note about "{concept}":
---
{existing_body}
---

New source text to integrate:
---
{chunk}
---

Write the updated note body."""

# ---------------------------------------------------------------------------
# Relationship Identification (Agent §4.2 — step 5)
# ---------------------------------------------------------------------------

IDENTIFY_RELATIONS_SYSTEM = """\
You are a knowledge graph builder. Given a list of concepts found in the same text \
chunk, identify relationships between them. Use ONLY these relation types: \
supports, contradicts, derived_from, relates_to.

Output ONLY a valid JSON array of objects with keys: "source", "target", "type". \
If no relationships exist, output an empty array []."""

IDENTIFY_RELATIONS_USER = """\
These concepts were found in the same text chunk:
{concepts}

Source text:
---
{chunk}
---

Identify relationships between these concepts. Output ONLY valid JSON."""

# ---------------------------------------------------------------------------
# Query Synthesis (Query Engine §5.1 — step 4)
# ---------------------------------------------------------------------------

SYNTHESIZE_ANSWER_SYSTEM = """\
You are a research assistant. Answer the user's question using ONLY the provided \
context from the knowledge base. Cite sources by their node title in square brackets, \
e.g. [Concept Title]. If the context does not contain enough information to answer, \
say so explicitly. Do not invent information."""

SYNTHESIZE_ANSWER_USER = """\
Question: {question}

Knowledge base context:
---
{context}
---

Answer the question using only the context above. Cite sources by title."""

# ---------------------------------------------------------------------------
# Novelty Check (Query Engine §5.1 — step 5)
# ---------------------------------------------------------------------------

NOVELTY_CHECK_SYSTEM = """\
You are a novelty detector. You determine whether an answer introduces a concept \
that is NOT already present in the provided context nodes. Answer with ONLY \
"YES" or "NO". If YES, also provide the novel concept name on the next line."""

NOVELTY_CHECK_USER = """\
Answer:
---
{answer}
---

Context node titles: {node_titles}

Does this answer introduce a concept not already present in the context nodes?
Answer YES or NO. If YES, state the novel concept name on the next line."""

# ---------------------------------------------------------------------------
# Duplicate Detection (Linter §6.1)
# ---------------------------------------------------------------------------

DUPLICATE_CHECK_SYSTEM = """\
You are a deduplication engine. You decide whether two knowledge base nodes are \
about the same concept and should be merged. Consider their titles, aliases, and \
body text. Answer with ONLY "YES" or "NO"."""

DUPLICATE_CHECK_USER = """\
Node A: "{title_a}"
Aliases: {aliases_a}
Body excerpt: {body_a}

Node B: "{title_b}"
Aliases: {aliases_b}
Body excerpt: {body_b}

Are these about the same concept and should be merged? YES or NO."""
