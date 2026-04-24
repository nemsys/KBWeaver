"""Ollama LLM provider — fully local inference via HTTP API.

Communicates with a running Ollama server (default: http://localhost:11434).
No data leaves the machine.
"""

from __future__ import annotations

import json
import logging

import requests

logger = logging.getLogger(__name__)


class OllamaProvider:
    """LLM provider backed by a local Ollama instance.

    Satisfies the :class:`~kbweaver.llm.base.LLMProvider` protocol.
    """

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3:8b") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def complete(self, system: str, user: str) -> str:
        """Call the Ollama ``/api/generate`` endpoint.

        Parameters
        ----------
        system:
            System prompt.
        user:
            User prompt.

        Returns
        -------
        str
            The generated text response.

        Raises
        ------
        RuntimeError
            If the Ollama API returns a non-200 status or the response
            cannot be parsed.
        """
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "system": system,
            "prompt": user,
            "stream": False,
        }

        logger.debug("Ollama request: model=%s, prompt_len=%d", self._model, len(user))

        try:
            resp = requests.post(url, json=payload, timeout=300)
        except requests.ConnectionError as exc:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Is the Ollama server running?"
            ) from exc

        if resp.status_code != 200:
            raise RuntimeError(
                f"Ollama API error (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {resp.text[:500]}") from exc

        response_text = data.get("response", "")
        logger.debug(
            "Ollama response: model=%s, response_len=%d, eval_duration=%s",
            self._model,
            len(response_text),
            data.get("eval_duration", "N/A"),
        )
        return response_text

    def __repr__(self) -> str:
        return f"OllamaProvider(model={self._model!r}, base_url={self._base_url!r})"
