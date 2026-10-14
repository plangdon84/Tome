"""LLM provider presets. All speak the OpenAI-compatible chat completions API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Literal

Hosting = Literal["self_hosted", "third_party"]

# Placeholder used when no key is configured. In Claude Code cloud sessions the
# network proxy injects the real Authorization header for openrouter.ai; local
# servers (vLLM, llama.cpp, Ollama) ignore the key.
PLACEHOLDER_KEY = "sk-placeholder-no-key"


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str  # ends in /v1
    hosting: Hosting
    api_key_env: str | None = None
    default_model: str | None = None
    extra_body: dict = field(default_factory=dict)
    supports_json_schema: bool = True

    def api_key(self) -> str:
        if self.api_key_env and os.environ.get(self.api_key_env):
            return os.environ[self.api_key_env]
        return PLACEHOLDER_KEY

    def with_overrides(self, **kw) -> Provider:
        return replace(self, **{k: v for k, v in kw.items() if v is not None})


PRESETS: dict[str, Provider] = {
    p.name: p
    for p in [
        Provider(
            "openrouter",
            "https://openrouter.ai/api/v1",
            "third_party",
            api_key_env="OPENROUTER_API_KEY",
            default_model="meta-llama/llama-3.1-8b-instruct",
            # Ask OpenRouter to include cost in the usage block.
            extra_body={"usage": {"include": True}},
        ),
        Provider(
            "vllm-local", "http://localhost:8000/v1", "self_hosted", api_key_env="VLLM_API_KEY"
        ),
        Provider("llamacpp-local", "http://localhost:8080/v1", "self_hosted"),
        Provider("ollama-local", "http://localhost:11434/v1", "self_hosted"),
    ]
}


def get_provider(name: str, *, base_url: str | None = None, model: str | None = None) -> Provider:
    """A preset, optionally pointed elsewhere (``TOME_<NAME>_BASE_URL`` also works)."""
    if name not in PRESETS:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(PRESETS)}")
    env_url = os.environ.get(f"TOME_{name.upper().replace('-', '_')}_BASE_URL")
    return PRESETS[name].with_overrides(base_url=base_url or env_url, default_model=model)
