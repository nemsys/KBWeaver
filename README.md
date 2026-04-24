# KBWeaver — Self-Organizing Personal Knowledge Engine

**KBWeaver** is an autonomous, self-evolving personal knowledge engine that acts as an active research partner. It continuously transforms raw, unstructured inputs (PDFs, code, articles, notes) into a structured, interconnected knowledge base — with no manual maintenance overhead.

Built entirely on local-first principles, KBWeaver keeps all your data in plain text on your own machine. No vendor lock-in, no mandatory cloud dependencies, and full privacy by default.

## Key Features

- **Autonomous Ingestion**: Drop any document into the input folder. KBWeaver automatically parses, normalizes, and archives it without altering the original.
- **Self-Evolving Knowledge Graph**: The system automatically extracts concepts, updates existing knowledge, and links new ideas together using a local SQLite-backed knowledge graph and Markdown notes.
- **LLM-Powered Insights**: Query your knowledge base using natural language. KBWeaver synthesizes well-grounded answers with citations, ensuring fidelity by strictly adhering to your data. New insights generated from queries are autonomously filed back into the knowledge base.
- **Maintenance Agent**: Automatically detects duplicates, orphans, and contradictions to keep the knowledge base pristine.
- **Plain Text Portability**: All notes are stored as standard Markdown files with YAML frontmatter, making them fully readable and editable in any standard Markdown editor (e.g., Obsidian, Logseq).

## Getting Started

### Prerequisites

- **Python 3.11+**
- **uv** (for dependency management)
- **Ollama** (running locally for the LLM backend)

### Installation

1. Clone the repository and navigate to the root directory:
   ```bash
   git clone <repository_url>
   cd KBWeaver
   ```

2. Initialize the project and sync dependencies using `uv`:
   ```bash
   uv sync
   ```

### Usage

KBWeaver is a CLI-driven tool. After setup, you can access the main commands:

Initialize the system and database:
```bash
kbweaver init
```

Start the autonomous watcher to ingest files from the designated input directory:
```bash
kbweaver watch
```

Query your local knowledge base:
```bash
kbweaver query "What are the latest updates on my AI projects?"
```

Run the maintenance agent to identify duplicates, orphans, and contradictions:
```bash
kbweaver lint
```

## Documentation

For a deeper dive into the system's design, architecture, and technical specifications, explore the `docs/` folder:
- [Product Requirements Document (PRD)](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Technical Specification](docs/TECH_SPEC.md)

## License

This project is licensed under the MIT License. See `pyproject.toml` for more details.
