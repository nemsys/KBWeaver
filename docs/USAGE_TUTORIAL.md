# KBWeaver Usage Tutorial

Welcome to the KBWeaver usage guide! KBWeaver is a self-organizing personal knowledge engine that automatically transforms raw documents into a highly interconnected, queryable knowledge base. 

This tutorial focuses entirely on **how to use KBWeaver** in your daily workflow. It assumes you have already installed the software and have your LLM backend (like Ollama) running locally.

---

## 1. The Core Workflow

KBWeaver operates on a simple, four-step lifecycle:
1. **Initialize:** Set up your workspace.
2. **Ingest:** Feed raw documents into the system.
3. **Query:** Ask natural-language questions to synthesize answers from your data.
4. **Maintain:** Run the automated linter to keep your knowledge graph clean and organized.

---

## 2. Initializing Your Workspace

Before you can use KBWeaver, you need to initialize your local knowledge base. Navigate to your desired working directory and run:

```bash
kbweaver init
```

This command sets up the necessary folder structure:
* `raw/` - Where you will drop new files for the system to process.
* `wiki/` - Where KBWeaver stores the generated, interlinked Markdown notes.
* `archive/` - Where original source documents are kept safely.
* `db/` - Contains the `search.db` SQLite database used for fast text and graph search.
* `logs/` - Contains system logs and ingestion reports.

---

## 3. Ingesting Knowledge

KBWeaver is designed to do the heavy lifting of reading, chunking, and organizing your files. It supports various formats including PDF, DOCX, HTML, Markdown, and source code.

### The Autonomous Watcher (Recommended)
The easiest way to use KBWeaver is to run the background watcher:

```bash
kbweaver watch
```

While this command is running, you can simply drag and drop files into the `raw/` directory. The watcher will automatically detect new files, process them chunk by chunk, extract concepts, and link them to your existing knowledge base. Original files are then moved to the `archive/` directory so they are never altered or lost.

### Manual Ingestion
If you prefer to manually trigger the ingestion of a specific file (useful for testing or one-off imports), you can use:

```bash
kbweaver ingest path/to/your/document.pdf
```

### What happens during ingestion?
Behind the scenes, KBWeaver reads your file, splits it into semantic chunks, and uses your local LLM to extract entities. It checks if these concepts already exist in your wiki, updates them if they do, or creates new Markdown nodes if they don't. It then draws relationships (e.g., "supports", "contradicts", "derived_from") between these concepts to build a rich knowledge graph.

---

## 4. Querying Your Knowledge Base

Once you have ingested some documents, you can ask KBWeaver questions. The query engine doesn't just keyword-search; it traverses your knowledge graph to synthesize a grounded answer.

```bash
kbweaver query "What are the key differences between Transformer and RNN architectures?"
```

**How it works:**
1. KBWeaver finds the most relevant starting notes using a fast full-text search.
2. It follows the links from those notes to gather broader context (up to 2 steps away by default).
3. It passes this context to the LLM to generate a comprehensive answer with citations.
4. **Self-Evolution:** By default, if the generated answer yields a *new* insight that isn't explicitly written in your notes, KBWeaver will automatically create a new note for that insight and link it back to the sources!

### Advanced Query Flags
You can fine-tune how KBWeaver searches your graph:

* `--depth INT`: Change how far the system traverses the graph. (e.g., `--depth 3` pulls in more distant connections, though it may take longer).
* `--top-k INT`: Change the number of initial entry points the search starts from (default is 5).
* `--no-file`: Disables the "self-evolution" feature, preventing KBWeaver from automatically creating new notes based on the query insights.

---

## 5. Maintenance and Organization

Over time, your knowledge base might accumulate duplicate concepts, orphaned notes (notes with no links), or contradictory claims. KBWeaver includes an autonomous Maintenance Agent (Linter) to help keep things pristine.

### Running a Health Check
To see a report of your knowledge base's health without making any changes, run:

```bash
kbweaver lint
```
This generates a report showing the number of orphans, duplicates, stale nodes, and potential contradictions.

### Applying Fixes Interactively
To clean up your graph, run the linter in interactive mode:

```bash
kbweaver lint --apply
```
KBWeaver will walk you through its suggestions one by one. For example, if it finds two notes named "Neural Nets" and "Neural Networks", it will ask if you want to:
* **[m]erge** them into one node.
* **[k]eep** both (which tells the system to stop flagging them).
* **[s]kip** for now.

You can also target specific checks, such as only fixing orphans:
```bash
kbweaver lint --apply orphans
```

---

## 6. System Health and Recovery

Because KBWeaver stores your actual data as plain text Markdown files in the `wiki/` directory, the system is incredibly resilient. The database is purely an index to make things fast.

* **Check System Status:** Get a quick overview of your graph size and last ingestion time:
  ```bash
  kbweaver status
  ```

* **Rebuild the Database:** If your database ever gets corrupted, or if you manually edit a bunch of Markdown files in Obsidian/Logseq and want KBWeaver to sync up, you can completely rebuild the search index and graph connections from scratch:
  ```bash
  kbweaver rebuild
  ```
  *(You can also use `kbweaver rebuild-index` or `kbweaver rebuild-graph` for targeted rebuilds).*

---

## 7. Configuration (`kbweaver.toml`)

You can customize KBWeaver's behavior by editing the `kbweaver.toml` file in your project root. Here, you can define:
* Which LLM models to use for different tasks (e.g., a fast model like `llama3.2:3b` for data ingestion, and a smarter model like `llama3:8b` for answering queries).
* Chunking sizes for document parsing.
* Default query traversal depths.

Happy knowledge weaving! By relying on `kbweaver watch` to ingest data and `kbweaver query` to retrieve it, you'll quickly build an incredibly powerful, deeply connected personal brain.
