---
title: Test App as New User
timestamp: 20260426_190730
---

## Done
- Installed KBWeaver globally using `uv tool install -e .`
- Created `/data/KB_Personal/` workspace and attempted initialization.
- Replaced missing `kbweaver init` with manual folder creation (`raw/`, `wiki/`, `archive/`, `db/`, `logs/`) and `kbweaver rebuild`.
- Updated `kbweaver.toml` to use `gemma4-26b:latest` since the default `llama3.2:3b` was not found in the local Ollama instance.
- Ingested test documents (PDF from `Books/ComputerScience/LLMs/` and a markdown file).

## Found
- `kbweaver init` command is missing from the CLI implementation despite being documented in the README and USAGE_TUTORIAL.
- Default `llama3.2:3b` model is missing from the local Ollama instance, causing the ingestion pipeline to fail with HTTP 404.
- Ingesting PDFs fails with `unstructured package not installed` because the `unstructured[local-inference]` extra is missing from dependencies.
- Ingesting documents with `gemma4-26b:latest` takes an extremely long time (or hangs) due to the model size, blocking practical usage.

## Status
- The onboarding experience is broken due to missing `init` command and missing LLM dependencies/models.
- PDF ingestion is non-functional out of the box.

## Next Steps
- Implement `kbweaver init` command in `kbweaver/cli.py`.
- Update project dependencies to include `unstructured[local-inference]` or `unstructured[all-docs]`.
- Provide a clear error/prompt in the CLI when the configured LLM is missing from Ollama.
- Potentially switch default ingestion model back to a smaller, faster model (e.g. `llama3:8b` or `phi3`) or add setup instructions to pull `llama3.2:3b`.
