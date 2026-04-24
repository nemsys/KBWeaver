"""LLM provider factory.

Routes to the correct backend and model based on configuration and
pipeline stage (entity_resolution vs synthesis).
"""

from __future__ import annotations

from kbweaver.config import Config
from kbweaver.llm.base import LLMProvider
from kbweaver.llm.ollama import OllamaProvider


def get_provider(config: Config, stage: str = "synthesis") -> LLMProvider:
    """Instantiate an LLM provider for the given pipeline stage.

    Parameters
    ----------
    config:
        The loaded KBWeaver configuration.
    stage:
        One of ``"entity_resolution"`` or ``"synthesis"``.
        Determines which model binding is used.

    Returns
    -------
    LLMProvider
        A configured provider instance.

    Raises
    ------
    ValueError
        If the backend or stage is not recognized.
    """
    if stage == "entity_resolution":
        model = config.llm.entity_resolution.model
    elif stage == "synthesis":
        model = config.llm.synthesis.model
    else:
        raise ValueError(f"Unknown pipeline stage: {stage!r}")

    backend = config.llm.backend

    if backend == "ollama":
        return OllamaProvider(base_url=config.llm.base_url, model=model)
    else:
        raise ValueError(
            f"Unknown LLM backend: {backend!r}. "
            f"Supported: ollama"
        )
